"""
ResolveMergeConflictAction — LLM 辅助解决 Git 合并冲突

输入：含 `<<<<<<<` / `=======` / `>>>>>>>` 冲突标记的文件内容
输出：解决后的完整文件内容（不含冲突标记）

策略：
- 读文件内容 + 两边分支名 + 可选的 diff 上下文 → 构造 prompt
- 调 llm_client.chat（低温 0.2）→ 产出合并版本
- 基本校验：返回内容不应再包含冲突标记；若仍含则判失败
- 返回 ActionResult.data = {"resolved": {path: content}, "failed": [paths]}

使用场景：CI pipeline 的 develop → main 合并失败时，对代码类文件（.html/.js/.py 等）
调本 Action 尝试自动解决；成功则继续提交，失败则 abort 并人工介入。

⚠️ 为降低静默丢代码风险：
- 调用方应当为每个调用写 LLM 会话日志（llm_conversations 表）
- Action 只产出内容，不做 git 操作；git add / commit 交给上层
- 冲突块 > 10 或文件 > 2000 行直接 decline（避免 LLM 吃不下）
"""
import logging
import re
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult

logger = logging.getLogger("actions.resolve_merge_conflict")


_CONFLICT_RE = re.compile(
    r"<{7} [^\n]*\n(.*?)\n={7}\n(.*?)\n>{7} [^\n]*",
    re.DOTALL,
)

# 安全阈值
_MAX_FILE_LINES = 2000
_MAX_CONFLICT_HUNKS = 10


class ResolveMergeConflictAction(ActionBase):

    @property
    def name(self) -> str:
        return "resolve_merge_conflict"

    @property
    def description(self) -> str:
        return "用 LLM 解决单个文件的 Git 合并冲突，返回合并后的完整文件内容"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        # 不对 LLM 暴露为 tool——只在 CI 里程序化调用
        return {
            "name": self.name,
            "description": "（内部用）仅 CI pipeline 合并失败时调用，不对聊天 LLM 暴露。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "description": "{path, content, ours_label, theirs_label} 列表",
                    },
                },
                "required": ["files"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        files: List[Dict[str, Any]] = context.get("files") or []
        if not files:
            return ActionResult(success=False, error="未提供待解决的冲突文件")

        resolved: Dict[str, str] = {}
        failed: List[Dict[str, str]] = []

        for entry in files:
            path = entry.get("path", "")
            content = entry.get("content", "")
            ours_label = entry.get("ours_label", "ours")
            theirs_label = entry.get("theirs_label", "theirs")

            if not path or not content:
                failed.append({"path": path, "reason": "缺少 path 或 content"})
                continue

            # 安全阈值
            line_count = content.count("\n") + 1
            if line_count > _MAX_FILE_LINES:
                failed.append({"path": path, "reason": f"文件过大（{line_count} 行 > {_MAX_FILE_LINES}）"})
                continue

            hunks = _CONFLICT_RE.findall(content)
            if not hunks:
                # 已经没有冲突了，原文透传
                resolved[path] = content
                continue
            if len(hunks) > _MAX_CONFLICT_HUNKS:
                failed.append({"path": path, "reason": f"冲突块过多（{len(hunks)} > {_MAX_CONFLICT_HUNKS}）"})
                continue

            try:
                merged = await self._resolve_one(path, content, ours_label, theirs_label)
            except Exception as e:
                logger.warning("LLM 解决冲突异常 (%s): %s", path, e)
                failed.append({"path": path, "reason": f"LLM 调用失败: {e}"})
                continue

            # 校验：不应再含冲突标记
            if _CONFLICT_RE.search(merged) or "<<<<<<<" in merged or ">>>>>>>" in merged:
                failed.append({"path": path, "reason": "LLM 产出仍含冲突标记"})
                continue

            resolved[path] = merged
            logger.info("✅ LLM 解决冲突成功: %s (%d 行 → %d 行)", path, line_count, merged.count("\n") + 1)

        return ActionResult(
            success=bool(resolved),
            data={
                "type": "merge_conflict_resolved",
                "resolved": resolved,   # {path: content}
                "failed": failed,       # [{path, reason}]
                "resolved_count": len(resolved),
                "failed_count": len(failed),
            },
        )

    async def _resolve_one(self, path: str, content: str, ours_label: str, theirs_label: str) -> str:
        """单文件解冲突：构造 prompt → 调 LLM → 提取产出"""
        from llm_client import llm_client, set_llm_context, clear_llm_context

        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

        prompt = f"""你需要解决一个 Git 合并冲突。下面给你冲突文件的完整内容，文件里有 `<<<<<<<` / `=======` / `>>>>>>>` 标记的冲突块。

**文件路径**：`{path}`
**文件类型**：`.{ext}`（根据扩展名判断语言）
**两个分支**：
- `{ours_label}`（当前分支，冲突标记上半段）
- `{theirs_label}`（要合入的分支，冲突标记下半段）

**合并原则（按优先级）**：
1. **保留两边的新增功能**：如果两边分别加了不同的函数/字段/元素，两个都保留
2. **同一处改了不同值**：优先 `{theirs_label}` 的版本（它是要合入的"新"代码）
3. **保持语法合法**：输出必须是合法的 `.{ext}` 代码，不能有孤立的 `<<<<<<<` / `>>>>>>>`
4. **保留文件其他未冲突部分不动**
5. **保留原文件的编码、缩进风格**

**输出要求**：
- **只输出合并后的完整文件内容**
- **不要**包裹代码块（不要 ```），不要加任何解释、前言、尾声
- 第一个字符就是文件第一行，最后一个字符是文件最后一行
- 如果你不确定某处怎么合，在那行上面加一行注释（注释语法要对的，比如 `.py` 用 `#`、`.js/.html/.css` 用 `//` 或 `<!-- -->`）标 `TODO: manual review`，但**仍然要给出一个合理的默认值**，不要留着冲突标记

---
## 冲突文件内容

```
{content}
```
"""

        set_llm_context(agent_type="CIPipeline", action="resolve_merge_conflict")
        try:
            reply = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=16000,
            )
        finally:
            clear_llm_context()

        return _strip_code_fence(reply)


def _strip_code_fence(text: str) -> str:
    """如果 LLM 不听话用 ``` 包了，剥掉最外层代码块。"""
    t = text.strip()
    if t.startswith("```"):
        # 去掉第一行 ```xxx
        nl = t.find("\n")
        if nl > 0:
            t = t[nl + 1:]
        # 去掉结尾 ```
        if t.endswith("```"):
            t = t[:-3]
        t = t.rstrip()
    return t
