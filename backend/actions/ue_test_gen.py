"""UETestGenAction —— 为 UE 项目自动生成 Automation 测试（C++）

背景（docs/20260918_01_OpenSpec四阶段闭环修复方案.md §4）：
两条测试路径的分工一直是不对称的 ——

    | 项目类型   | 生成测试                          | 执行测试            |
    |-----------|----------------------------------|--------------------|
    | web/Python | TestAgent._generate_test_cases ✅ | _run_pytest      ✅ |
    | UE         | 空缺                            ❌ | UEPlaytestAction ✅ |

`run_playtest` 只**跑**测试不**写**测试，而 UE 项目里一个 Automation 测试都没有，
于是 `ue_playtest.py` 里 `no_tests → success` 那条分支的实际含义是「没测试就算通过」——
play_test 阶段从来没有验证过任何东西。这个 Action 补上生成侧。

设计要点（全部来自手写 SprintComponentTest.cpp 时的实际踩坑）：

  1. **编不过就不落盘。** pytest 生成错了只是 fail 一条；C++ 编译不过会让整个
     module 挂掉，连带下游 engine_compile 和 playtest 全废。所以走
     「写盘 → lint → UBT -SingleFile → 不过则删掉」，仓库里只留编得过的文件。
     注意这跟最初设想的「让生成的测试跟着 engine_compile 一起编」不同：那样
     一旦编不过，工单会因为「它自己没写的代码」被 reject 回 development，
     DevAgent 拿着一份不是自己产出的报错反复空转。就地验证、就地回滚更干净。

  2. **include 路径自己算，不问 LLM。** 这条是纯经验性的、看头文件推不出来：
     无 Public/Private 分层的项目（flat layout），子目录 Tests/ 里必须写
     `#include "../Xxx.h"`，写 `#include "Xxx.h"` 必 C1083 —— UBT 不会把 flat
     模块根加进 include 搜索路径，同级能过靠的是 quoted include 的相对查找。
     这是机械可算的，交给 LLM 猜纯属浪费一轮编译。

  3. **flags 组合受 static_assert 约束。** EAutomationTestFlags 要求命中至少一个
     ApplicationContext，且 Filter 恰好一个。编错了是编译期 static_assert 失败，
     报错信息还很难读。已实测可用：EditorContext | CommandletContext | ProductFilter。

  4. **测试名必须以 `Project.` 开头**，否则不被 play_test.yaml 的
     `test_filter: "Project."` 命中 —— 生成了也等于没生成。

  5. **不建 World / 不 SpawnActor。** 跑在 `-nullrhi` 的 commandlet 上下文里，
     有渲染或关卡依赖会让测试自身崩掉。

失败语义：**永不阻塞工单。** 测试生成是增强不是门禁，它挂了不该让功能进不去。
所有失败路径都返回 success=True + warnings，但必须留下痕迹 —— 否则又变回
「静默地没有测试」，跟修之前没区别。
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.ue_test_gen")


# ==================== EAutomationTestFlags 约束 ====================
# 对照 Engine/Source/Runtime/Core/Public/Misc/AutomationTest.h 的两个 static_assert：
#   _ApplicationContextMask —— 必须命中至少一个
#   _FilterMask             —— 必须恰好命中一个
_CONTEXT_FLAGS = (
    "EditorContext", "ClientContext", "ServerContext",
    "CommandletContext", "ProgramContext",
)
_FILTER_FLAGS = (
    "SmokeFilter", "EngineFilter", "ProductFilter",
    "PerfFilter", "StressFilter", "NegativeFilter",
)
# 已实测通过的组合（headless commandlet 下能被 `Automation RunTests Project.` 捞到）
_BLESSED_FLAGS = (
    "EAutomationTestFlags::EditorContext | EAutomationTestFlags::CommandletContext\n"
    "\t\t| EAutomationTestFlags::ProductFilter"
)

_TEST_MACROS = (
    "IMPLEMENT_SIMPLE_AUTOMATION_TEST",
    "IMPLEMENT_COMPLEX_AUTOMATION_TEST",
    "IMPLEMENT_CUSTOM_SIMPLE_AUTOMATION_TEST",
    "DEFINE_SPEC",
    "BEGIN_DEFINE_SPEC",
)

# -nullrhi commandlet 下会崩 / 不可用的东西
_BANNED_TOKENS = (
    "SpawnActor",
    "UWorld",
    "GetWorld()",
    "FAutomationEditorCommonUtils::LoadMap",
    "AutomationOpenMap",
    "UGameplayStatics::OpenLevel",
    "FEditorFileUtils",
)

_RE_TEST_NAME = re.compile(r'IMPLEMENT_\w*AUTOMATION_TEST\s*\(\s*\w+\s*,\s*"([^"]+)"')
_RE_SPEC_NAME = re.compile(r'DEFINE_SPEC\s*\(\s*\w+\s*,\s*"([^"]+)"')
_RE_UCLASS_LINE = re.compile(r"^\s*(?:UCLASS|USTRUCT)\b")
_RE_CLASS_DECL = re.compile(
    r"^\s*(?:class|struct)\s+(?:\w+_API\s+)?([A-Za-z_]\w*)"
)


def _extract_class_names(header_src: str) -> List[str]:
    """抓出头文件里 UCLASS/USTRUCT 修饰的类型名。

    别用单条正则去匹配 `UCLASS(...)` 的括号：真实代码里参数是嵌套的 ——
    `UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))`
    用 `\\([^)]*\\)` 会停在 `(Custom)` 的右括号上，整条匹配失败，
    于是对所有带 ClassGroup/meta 的类（也就是绝大多数组件类）都报
    「头文件里没有 UCLASS/USTRUCT」。实测 SprintComponent.h 就是这么漏的。
    宏参数还可能跨行，逐行扫更稳：找到 UCLASS/USTRUCT 行，再往下找最近的
    class/struct 声明行。
    """
    names: List[str] = []
    lines = header_src.splitlines()
    for i, line in enumerate(lines):
        if not _RE_UCLASS_LINE.match(line):
            continue
        # 宏参数可能跨几行，往下找最近的 class/struct 声明
        for j in range(i + 1, min(i + 8, len(lines))):
            m = _RE_CLASS_DECL.match(lines[j])
            if m:
                n = m.group(1)
                if n not in names:
                    names.append(n)
                break
    return names


_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RE_LINE_COMMENT = re.compile(r"//[^\n]*")


def _strip_comments(code: str) -> str:
    """去掉 // 和 /* */ 注释。

    禁用词扫描必须在去注释之后做，否则注释里提到某个词就会被判违规。
    这不是假想的风险：真机实测通过的 SprintComponentTest.cpp 里有一行
    `// 不建 World / 不 SpawnActor：...`，而我给 LLM 的正例又要求照抄这种注释 ——
    结果连续三轮生成全被自己的规则毙掉，报「用到了 SpawnActor」。
    一个连人工写的、已编译已跑绿的样板都判不过的检查，判的是检查自己。
    （ue_lint/rules.py 里同样有 _strip_line_comment，同一个道理。）
    """
    return _RE_LINE_COMMENT.sub("", _RE_BLOCK_COMMENT.sub("", code))


class UETestGenAction(ActionBase):
    """为本次改动的 UE C++ 头文件生成最小 Automation 测试"""

    available_for_traits = {"any_of": ["engine:ue5", "engine:ue4"]}

    @property
    def name(self) -> str:
        return "ue_test_gen"

    @property
    def description(self) -> str:
        return "为本次改动的 UE 类生成 Automation 测试（生成后 lint + UBT SingleFile 验证）"

    # ==================== 主流程 ====================

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        sop_cfg = context.get("sop_config") or {}
        if not sop_cfg.get("ue_test_gen_enabled", True):
            return self._skip("SOP 关闭了 ue_test_gen")

        project_id = context.get("project_id", "")
        repo_path = await self._resolve_repo(context, project_id)
        if repo_path is None:
            return self._skip("仓库路径不可用")

        # ---- 1. 挑要测的头文件 ----
        max_targets = int(sop_cfg.get("ue_test_gen_max_targets", 2) or 2)
        targets = self._pick_targets(context, repo_path, max_targets)
        if not targets:
            return self._skip("本次改动里没有可测的 UE 头文件")

        log = context.get("log_callback")
        generated: List[str] = []
        warnings: List[str] = []
        details: List[Dict[str, Any]] = []

        for header_abs in targets:
            try:
                d = await self._gen_one(context, repo_path, header_abs, sop_cfg)
            except Exception as e:
                logger.warning("生成 %s 的测试失败（忽略）: %s", header_abs.name, e)
                warnings.append(f"{header_abs.name}: 生成异常 {e}")
                continue
            details.append(d)
            if d.get("written"):
                generated.append(d["path"])
                await self._log(log, f"[ue_test_gen] 已生成 {d['path']}")
            elif d.get("reason"):
                warnings.append(f"{header_abs.name}: {d['reason']}")

        msg = (
            f"生成 {len(generated)} 个 Automation 测试"
            if generated else
            "未生成测试（见 warnings）"
        )
        # 不阻塞：success 恒为 True。但 warnings 必须带出去，
        # 否则又退化成「静默地没有测试」。
        return ActionResult(
            success=True,
            data={
                "status": "success",
                "ue_test_gen": {
                    "generated": generated,
                    "warnings": warnings,
                    "details": details,
                    "summary": msg,
                },
            },
            files={},
            message=msg,
        )

    # ==================== 单个头文件 ====================

    async def _gen_one(
        self, context: Dict[str, Any], repo_path: Path,
        header_abs: Path, sop_cfg: Dict[str, Any],
    ) -> Dict[str, Any]:
        module_root = self._module_root(repo_path, header_abs)
        if module_root is None:
            return {"header": header_abs.name, "written": False,
                    "reason": "找不到所属模块（无 *.Build.cs）"}

        tests_dir = module_root / "Tests"
        out_abs = tests_dir / f"{header_abs.stem}Test.cpp"
        out_rel = out_abs.relative_to(repo_path).as_posix()

        # 已有测试不覆盖 —— 人工写的测试比生成的值钱得多
        if out_abs.exists():
            return {"header": header_abs.name, "path": out_rel, "written": False,
                    "reason": "测试文件已存在，跳过（不覆盖既有测试）"}

        # include 路径自己算（硬约束 #5），不进 LLM
        include_line = self._include_path_for(header_abs, tests_dir, module_root)

        try:
            header_src = header_abs.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"header": header_abs.name, "written": False, "reason": f"读头文件失败: {e}"}

        class_names = _extract_class_names(header_src)
        if not class_names:
            return {"header": header_abs.name, "written": False,
                    "reason": "头文件里没有 UCLASS/USTRUCT，无可测类型"}

        # ---- 生成 → 静态检查 → lint，最多 3 轮 ----
        # 3 轮不是拍脑袋：真机实测过 LLM 连续两轮都往里塞 SpawnActor（prompt 里
        # 明令禁止也照塞），2 轮会直接放弃。加了正/反例示范后好转，但生成本身
        # 有随机性，多给一轮的成本（一次 LLM 调用）远低于白跑一趟整个阶段。
        feedback = ""
        code: Optional[str] = None
        for attempt in range(1, 4):
            raw = await self._ask_llm(
                context, header_abs, header_src, class_names, include_line, feedback,
            )
            if not raw:
                return {"header": header_abs.name, "written": False,
                        "reason": "LLM 不可用或未返回代码"}
            cand = self._normalize(raw, include_line)
            problems = self._static_check(cand, include_line)
            if not problems:
                code = cand
                break
            feedback = "上一版有这些问题，请修正后重新输出完整文件：\n- " + "\n- ".join(problems)
            logger.info(
                "ue_test_gen 静态检查未过（第 %d 轮，%d 个问题）: %s",
                attempt, len(problems), problems[:3],
            )
        if code is None:
            return {"header": header_abs.name, "path": out_rel, "written": False,
                    "reason": f"静态检查三轮未通过：{feedback[:200]}"}

        # ---- 落盘 ----
        tests_dir.mkdir(parents=True, exist_ok=True)
        out_abs.write_text(code, encoding="utf-8")

        # ---- lint（复用 R1-R8，其中 R3 会核 include 路径）----
        lint_problems = self._lint(repo_path, out_rel, context)
        if lint_problems:
            out_abs.unlink(missing_ok=True)
            self._rmdir_if_empty(tests_dir)
            return {"header": header_abs.name, "path": out_rel, "written": False,
                    "reason": f"lint blocking: {'; '.join(lint_problems[:2])}"}

        # ---- UBT -SingleFile 实编（默认开；关掉就只有静态保证）----
        if sop_cfg.get("ue_test_gen_compile", True):
            ok, err = await self._compile_check(context, out_abs, sop_cfg)
            if not ok:
                # 编不过就删干净：留在仓库里会让下游 engine_compile 整个挂掉
                out_abs.unlink(missing_ok=True)
                self._rmdir_if_empty(tests_dir)
                return {"header": header_abs.name, "path": out_rel, "written": False,
                        "reason": f"UBT SingleFile 编译失败，已回滚：{err[:300]}"}

        return {
            "header": header_abs.name,
            "path": out_rel,
            "written": True,
            "tests": _RE_TEST_NAME.findall(code) + _RE_SPEC_NAME.findall(code),
        }

    # ==================== LLM ====================

    async def _ask_llm(
        self, context: Dict[str, Any], header_abs: Path, header_src: str,
        class_names: List[str], include_line: str, feedback: str,
    ) -> str:
        from llm_client import llm_client

        module = header_abs.parent.name
        prompt = f"""为下面这个 UE C++ 类写最小 Automation 测试。直接返回完整 .cpp 源码，不要 markdown 围栏、不要解释。

## 待测头文件：{header_abs.name}
```cpp
{header_src[:6000]}
```

可测类型：{', '.join(class_names[:5])}

## 硬约束（违反其一就编不过 / 跑不到，必须全部满足）

1. 文件开头的 include 块**必须逐字使用**下面这段，一个字都不要改：
```cpp
#include "Misc/AutomationTest.h"
{include_line}
```
   这是按项目实际目录布局算好的。自己改成别的写法会 C1083 编译失败。
   除此之外只能再加引擎头（如 "GameFramework/CharacterMovementComponent.h"）。

2. 全部测试代码包在 `#if WITH_DEV_AUTOMATION_TESTS` / `#endif` 之间。

3. 用 `IMPLEMENT_SIMPLE_AUTOMATION_TEST`，flags 逐字写成：
```cpp
{_BLESSED_FLAGS}
```
   （EAutomationTestFlags 有 static_assert：必须含至少一个 Context、恰好一个 Filter。）

4. 测试名**必须**以 `Project.` 开头，例如
   `"Project.{module}.{class_names[0][1:] if class_names else 'Foo'}.Defaults"`。
   不以 Project. 开头就不会被测试过滤器捞到，等于白写。

5. 测试跑在 `-nullrhi` 的 commandlet 里：**禁止**建 World、SpawnActor、
   GetWorld()、加载关卡、任何渲染或编辑器 UI 依赖。
   只能 `NewObject<UXxx>()` 之后验对象自身的契约。

## 正确写法示例（这段是真机编译并跑通过的，照这个结构写）

```cpp
#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
\tFMyComponentDefaultsTest,
\t"Project.MyModule.MyComponent.Defaults",
{_BLESSED_FLAGS})

bool FMyComponentDefaultsTest::RunTest(const FString& Parameters)
{{
\t// 不建 World / 不 SpawnActor：只验组件自身的初始契约
\tUMyComponent* Comp = NewObject<UMyComponent>();
\tif (!TestNotNull(TEXT("UMyComponent 可实例化"), Comp))
\t{{
\t\treturn false;
\t}}
\tTestTrue(TEXT("MaxValue 为正值"), Comp->GetMaxValue() > 0.f);
\t// BeginPlay 未执行，运行期字段仍是构造默认值
\tTestFalse(TEXT("初始未激活"), Comp->IsActiveState());
\treturn true;
}}

#endif // WITH_DEV_AUTOMATION_TESTS
```

**反例（绝对不要这么写，会让测试进程崩掉）：**

```cpp
UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);   // 错
AActor* Owner = World->SpawnActor<AActor>();                    // 错
UMyComponent* Comp = Owner->FindComponentByClass<UMyComponent>();
```

需要「组件没有预期 Owner」这种场景时，**不要去造 Owner** —— 直接
`NewObject<UMyComponent>()`（它本来就没有 Owner），然后验调用接口不崩即可。

## 内容要求
- 2 个测试：一个验默认状态/初始契约，一个验边界或防御性行为
  （例如组件没有预期 Owner 时调用接口必须安全 no-op 不崩）。
- 用 TestNotNull / TestTrue / TestFalse / TestEqual 断言，每条带中文说明字符串。
- 注意：`NewObject` 出来的对象**没有走 BeginPlay**，运行期才初始化的字段仍是
  构造默认值 —— 断言要按这个前提写，不要假设 BeginPlay 跑过。
- 关键断言上方写一行中文注释说明为什么这么断。
{('## 上一轮的问题（必须全部修掉）' + chr(10) + feedback) if feedback else ''}"""

        try:
            out = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=2500,
            )
        except Exception as e:
            logger.warning("ue_test_gen LLM 调用失败: %s", e)
            return ""
        if not out or out.startswith("[LLM_UNAVAILABLE]"):
            return ""
        return out

    # ==================== 净化 / 校验 ====================

    def _normalize(self, raw: str, include_line: str) -> str:
        from content_sanitizer import strip_code_fences
        code, note = strip_code_fences(raw.strip(), "Generated.cpp")
        if note:
            logger.debug("ue_test_gen 净化: %s", note)
        return code.replace("\r\n", "\n").rstrip() + "\n"

    def _static_check(self, code: str, include_line: str) -> List[str]:
        """纯字符串校验，不落盘。抓的都是「编译一次才能发现」的低级错。"""
        problems: List[str] = []

        if not any(m in code for m in _TEST_MACROS):
            problems.append(
                f"没有任何 Automation 测试宏（需要 {_TEST_MACROS[0]} 之类）"
            )
        if "WITH_DEV_AUTOMATION_TESTS" not in code:
            problems.append("测试代码没有包在 #if WITH_DEV_AUTOMATION_TESTS / #endif 里")
        if '#include "Misc/AutomationTest.h"' not in code:
            problems.append('缺少 #include "Misc/AutomationTest.h"')
        if include_line not in code:
            problems.append(f"include 块被改动了，必须逐字包含：{include_line}")

        # 测试名前缀 —— 不满足就不会被 test_filter="Project." 捞到
        names = _RE_TEST_NAME.findall(code) + _RE_SPEC_NAME.findall(code)
        if not names:
            problems.append("解析不到测试名（宏第二个参数应是 \"Project.xxx\" 字符串）")
        for n in names:
            if not n.startswith("Project."):
                problems.append(f'测试名 "{n}" 必须以 "Project." 开头')

        # flags：static_assert 约束
        for m in re.finditer(
            r"IMPLEMENT_\w*AUTOMATION_TEST\s*\((.*?)\)\s*\n\s*bool", code, re.S,
        ):
            args = m.group(1)
            ctx_hit = [f for f in _CONTEXT_FLAGS if f in args]
            flt_hit = [f for f in _FILTER_FLAGS if f in args]
            if not ctx_hit:
                problems.append(
                    "flags 缺少 ApplicationContext（需含 EditorContext / CommandletContext 之一）"
                )
            if len(flt_hit) != 1:
                problems.append(
                    f"flags 的 Filter 必须恰好 1 个，实际 {len(flt_hit)} 个：{flt_hit}"
                )

        # -nullrhi 下会崩的东西。只扫代码，不扫注释 —— 注释里提到
        # 「不要 SpawnActor」是好注释，不是违规（见 _strip_comments）。
        code_only = _strip_comments(code)
        for tok in _BANNED_TOKENS:
            if tok in code_only:
                problems.append(
                    f"用到了 {tok} —— 测试跑在 -nullrhi commandlet 下，不能有 World/关卡/编辑器依赖"
                )
        return problems

    def _lint(self, repo_path: Path, rel: str, context: Dict[str, Any]) -> List[str]:
        """跑 ue_lint 的静态规则，只取 blocking。

        R3（include 路径）是这里的主角：它现在按「引用方所在目录」判 quoted
        include 能否解析，正好覆盖 Tests/ 子目录这个生成器最容易踩的坑。
        """
        try:
            from actions.ue_lint import run_all_rules
        except Exception:
            return []
        try:
            issues = run_all_rules(
                [rel], repo_path,
                {"ue_engine_version": context.get("ue_engine_version") or "5.3"},
            )
        except Exception as e:
            logger.debug("ue_test_gen lint 异常（忽略）: %s", e)
            return []
        return [i.get("msg", "") for i in issues if i.get("blocking")]

    async def _compile_check(
        self, context: Dict[str, Any], out_abs: Path, sop_cfg: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """UBT -SingleFile 实编 —— 只编这一个 .cpp，30~90s，不是全量 3~5min。"""
        try:
            from actions.ue_compile_check import UECompileCheckAction
        except Exception as e:
            return True, f"编译检查不可用，跳过: {e}"   # 编不了就别拦，交给下游 engine_compile
        try:
            result = await UECompileCheckAction().run({
                **context,
                "single_files": [str(out_abs)],
                "timeout_seconds": int(sop_cfg.get("ue_test_gen_timeout", 180) or 180),
            })
        except Exception as e:
            logger.warning("ue_test_gen SingleFile 编译异常: %s", e)
            return True, ""   # 同上：基础设施问题不该判测试有罪
        d = result.data or {}
        if d.get("status") == "success":
            return True, ""
        errs = d.get("errors") or []
        brief = "; ".join(
            f"{e.get('file', '')}:{e.get('line', '')} {e.get('code', '')} {e.get('msg', '')}"
            for e in errs[:3]
        ) or (d.get("message") or "未知编译错误")
        return False, brief

    # ==================== 工具 ====================

    def _pick_targets(
        self, context: Dict[str, Any], repo_path: Path, limit: int,
    ) -> List[Path]:
        """挑本次改动里值得测的 .h。优先 context，其次退回 git HEAD 的改动。"""
        rels: List[str] = []
        dev_result = context.get("dev_result") or {}
        if isinstance(dev_result, dict) and isinstance(dev_result.get("files"), dict):
            rels = list(dev_result["files"].keys())
        if not rels and isinstance(context.get("_files"), dict):
            rels = list(context["_files"].keys())
        if not rels:
            rels = self._git_changed(repo_path)

        out: List[Path] = []
        for rel in rels:
            r = rel.replace("\\", "/")
            if not r.endswith(".h"):
                continue
            if "/Tests/" in r or r.endswith("Test.h"):
                continue          # 别给测试再生成测试
            p = repo_path / r
            if p.is_file():
                out.append(p)
            if len(out) >= limit:
                break
        return out

    def _git_changed(self, repo_path: Path) -> List[str]:
        try:
            import subprocess
            r = subprocess.run(
                ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
                cwd=str(repo_path), capture_output=True, text=True, timeout=15,
            )
            return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
        except Exception:
            return []

    @staticmethod
    def _module_root(repo_path: Path, file_abs: Path) -> Optional[Path]:
        """向上找到含 *.Build.cs 的那一级（与 ue_lint._module_root_for_file 同语义）"""
        try:
            cur = file_abs.resolve().parent
            root = repo_path.resolve()
            while cur != cur.parent and cur.is_relative_to(root):
                if any(cur.glob("*.Build.cs")):
                    return cur
                cur = cur.parent
        except Exception:
            pass
        return None

    @staticmethod
    def _include_path_for(header_abs: Path, from_dir: Path, module_root: Path) -> str:
        """算出从 from_dir 引用 header_abs 该写什么 —— 硬约束 #5，机械可算。

        按 UBT / C++ 的实际解析顺序：
          ① 与引用方同级 → 裸文件名（quoted include 的相对查找）
          ② 模块有 Public/ 或 Private/ 分层 → 相对该锚点（UBT 的 include 搜索路径）
          ③ 都不是（flat layout + 子目录）→ 相对路径，如 "../SprintComponent.h"
        第 ③ 种就是 SprintComponentTest.cpp 第一次编译 C1083 的那个坑。
        """
        try:
            h = header_abs.resolve()
            d = from_dir.resolve()
            if h.parent == d:
                return f'#include "{h.name}"'
            for anchor in (module_root / "Public", module_root / "Private"):
                if anchor.exists():
                    try:
                        rel = h.relative_to(anchor.resolve()).as_posix()
                        return f'#include "{rel}"'
                    except Exception:
                        pass
            rel = os.path.relpath(str(h), str(d)).replace("\\", "/")
            return f'#include "{rel}"'
        except Exception:
            return f'#include "{header_abs.name}"'

    @staticmethod
    async def _resolve_repo(context: Dict[str, Any], project_id: str) -> Optional[Path]:
        """定位项目仓库。

        `git_manager._repo_path()` 只认进程内 `_custom_paths` 里注册过的自定义路径，
        没注册就退回 `PROJECTS_DIR / project_id` —— 对 TestFPS 这种仓库在
        F:/ADS_Projects/ 的项目会静默指到一个不存在的目录，本 Action 于是报
        「本次改动里没有可测的 UE 头文件」，错得还很难查。
        所以跟 actions/chat/_git_base.py:24-28 一样，先从 projects.git_repo_path 补注册。
        context 里已有 repo_path 时优先用它（orchestrator 会透传）。
        """
        ctx_repo = (context.get("repo_path") or "").strip()
        if ctx_repo:
            p = Path(ctx_repo)
            if p.is_dir():
                return p
        if not project_id:
            return None
        try:
            from git_manager import git_manager, PROJECTS_DIR
            if project_id not in git_manager._custom_paths:
                try:
                    from database import db
                    row = await db.fetch_one(
                        "SELECT git_repo_path FROM projects WHERE id = ?", (project_id,),
                    )
                    custom = ((row or {}).get("git_repo_path") or "").strip()
                    if custom and custom != str(PROJECTS_DIR / project_id):
                        git_manager.set_project_path(project_id, custom)
                except Exception as e:
                    logger.debug("补注册自定义仓库路径失败（忽略）: %s", e)
            p = Path(str(git_manager._repo_path(project_id)))
            return p if p.is_dir() else None
        except Exception:
            return None

    @staticmethod
    def _rmdir_if_empty(d: Path) -> None:
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except Exception:
            pass

    @staticmethod
    async def _log(cb, text: str) -> None:
        logger.info(text)
        if not cb:
            return
        try:
            r = cb(text)
            if hasattr(r, "__await__"):
                await r
        except Exception:
            pass

    @staticmethod
    def _skip(reason: str) -> ActionResult:
        logger.info("ue_test_gen 跳过: %s", reason)
        return ActionResult(success=True, data={
            "status": "success",
            "ue_test_gen": {"generated": [], "warnings": [], "skipped": reason,
                            "summary": f"跳过：{reason}"},
        }, message=f"跳过：{reason}")
