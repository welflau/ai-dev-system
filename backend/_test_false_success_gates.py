"""验证「代码生成 ✅ 但没有任何代码」这条假成功链路上的 6 道闸门。

复现对象：TK-20260920-ce79a9 —— LLM 返回 [LLM_UNAVAILABLE] → 降级模板产出
`src/focus__resolve_.js`（只有一行 console.log）→ emit_step 照样打勾 →
后端重启后僵尸检测把 development_in_progress 前推成 development_done →
代码审查 3/10 不阻塞 → 验收 LLM 超时 602s 读到 ReviewOutput 默认值
(passed=True, score=6) 而 pass_score=6 → acceptance_passed → deployed。

跑法：python _test_false_success_gates.py
"""
import asyncio
import sys

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  — {detail}" if detail and not cond else ""))


def banner(t):
    print(f"\n{'=' * 64}\n{t}\n{'=' * 64}")


# ========== 1. ActionNode 降级必须留标记 ==========
banner("1. ActionNode 降级标记（降级 ≠ 通过）")
from actions.action_node import ActionNode
from actions.schemas import ReviewOutput, TestReviewOutput

node = ActionNode(key="t", expected_type=ReviewOutput, instruction="")
check("新建 node 默认 degraded=False", node.degraded is False)
node._degrade("LLM 超时 602s")
check("_degrade 置 degraded=True", node.degraded is True)
check("_degrade 记录原因", node.degrade_reason == "LLM 超时 602s")
check("降级后 instruct_content 是默认值模型", node.instruct_content is not None)
# 这就是原来的陷阱：默认值本身看起来像"通过"
check("默认 ReviewOutput 确实 passed=True（所以必须靠 degraded 拦）",
      getattr(node.instruct_content, "passed", None) is True)


# ========== 2. 两个评审 Action 降级时判不通过 ==========
banner("2. 验收/审查：降级一律判不通过")
import inspect
from actions import acceptance_review as ar, code_review as cr

ar_src = inspect.getsource(ar)
check("acceptance_review 检查 node.degraded", "if node.degraded:" in ar_src)
check("acceptance 降级判 acceptance_rejected",
      'status = "acceptance_rejected"' in ar_src and "score = 0" in ar_src)
cr_src = inspect.getsource(cr)
check("code_review 检查 node.degraded", "if node.degraded:" in cr_src)
check("code_review 降级置 has_critical=True", "has_critical = True" in cr_src)


# ========== 3. 规则兜底模板不再算成功 ==========
banner("3. write_code 降级模板：已有代码的项目一律判失败")
from actions.write_code import WriteCodeAction

act = WriteCodeAction()
# 3a. 已有代码（增量场景）→ 必须失败，且不得产出空壳
r = act._fallback({"ticket_title": "修复图片聚焦竞态", "module": "frontend",
                   "existing_code": {"index.html": "<html>", "gallery.js": "x"}})
check("已有代码时 success=False", r.success is False)
check("已有代码时不产出任何文件", not r.files, f"产出了 {list(r.files or {})}")
check("已有代码时不再生成 console.log 空壳",
      "console.log" not in str(r.files or {}) and "console.log" not in str(r.data))
# 3b. UE 保持原有失败行为
r_ue = act._fallback({"ticket_title": "NPC Actor", "module": "ue", "existing_code": {}})
check("UE/C++ 仍然 success=False", r_ue.success is False)
# 3c. 空项目脚手架仍可用（这不是冒充修复，是有意义的起点）
r_new = act._fallback({"ticket_title": "todo app", "module": "frontend", "existing_code": {}})
check("空项目仍产出脚手架 index.html", "index.html" in (r_new.files or {}))
check("空项目脚手架 success=True", r_new.success is True)

wc_src = inspect.getsource(act.__class__)
check("源码中已无 console.log 空壳模板", "loaded');" not in wc_src)


# ========== 4. CodeChangePlan 兼容字符串数组 ==========
banner("4. CodeChangePlan schema 兼容（零文件的直接起因）")
from actions.plan_code_change import CodeChangePlan, PlanCodeChangeAction

# 真实故障输入：LLM 回了字符串数组而非对象数组
p = CodeChangePlan(files_to_modify=["gallery.js", "post.js"], files_to_create=["a.js"])
check("字符串数组被强转成 [{path,...}]",
      p.files_to_modify == [{"path": "gallery.js", "changes": ""},
                            {"path": "post.js", "changes": ""}],
      str(p.files_to_modify))
check("files_to_create 同样强转", p.files_to_create == [{"path": "a.js", "purpose": ""}])
p2 = CodeChangePlan(files_to_modify=[{"file": "a.js", "changes": "x"}])
check("别名 key（file）被补成 path", p2.files_to_modify[0].get("path") == "a.js")
p3 = CodeChangePlan(files_to_modify=[{"path": "b.js", "changes": "y"}])
check("正常 dict 不受影响", p3.files_to_modify == [{"path": "b.js", "changes": "y"}])
p4 = CodeChangePlan(files_unchanged=[{"path": "c.js"}, "d.js"])
check("files_unchanged 反向兼容 dict", p4.files_unchanged == ["c.js", "d.js"])

# 路径对不上导致的静默零产出
_rp = PlanCodeChangeAction._resolve_path
ec = {"src/gallery.js": "", "index.html": "", "a/util.js": "", "b/util.js": ""}
check("裸文件名能对到 src/ 下的真实文件", _rp("gallery.js", ec) == "src/gallery.js")
check("./ 前缀能归一化", _rp("./index.html", ec) == "index.html")
check("大小写不敏感匹配", _rp("SRC/Gallery.js", ec) == "src/gallery.js")
check("同名歧义时拒绝瞎猜", _rp("util.js", ec) == "")
check("不存在的文件返回空", _rp("nope.js", ec) == "")


# ========== 5. emit_step 带产出 / dev.py 零产出判失败 ==========
banner("5. emit_step 产出校验")
from agents.base import BaseAgent
from agents import dev as dev_mod

sig = inspect.signature(BaseAgent.emit_step)
check("emit_step 接受 files 参数", "files" in sig.parameters)
check("emit_step 接受 reason 参数", "reason" in sig.parameters)

dev_src = inspect.getsource(dev_mod.DevAgent._do_develop)
check("_do_develop 零文件时判失败", '"未产出任何代码文件"' in dev_src)
check("_do_develop 降级模板判失败", "[降级]" in dev_src)
check("_do_develop 失败时 emit phase=error", 'phase="error"' in dev_src)
check("_do_develop 失败返回 development_failed（可重试而非 blocked）",
      '"development_failed"' in dev_src)
check("OpenSpec 硬失败仍走 blocked", "hard_fail" in dev_src)


# ========== 6. SOP：development_failed 能回到 fix_issues ==========
banner("6. SOP 重试链路")
from sop.loader import load_sop, sop_to_transition_rules, compose_sop

rules = sop_to_transition_rules(load_sop())
r = rules.get("development_failed")
check("default_sop 有 development_failed 规则", r is not None)
if r:
    check("development_failed → DevAgent.fix_issues",
          r["agent"] == "DevAgent" and r["action"] == "fix_issues", str(r))
for traits in ([], ["engine:ue5", "lang:cpp"]):
    cr_rules = sop_to_transition_rules(compose_sop(traits))
    check(f"compose_sop({traits or '无 traits'}) 也有 development_failed 规则",
          cr_rules.get("development_failed") is not None)

from actions.reflection import ReflectionAction
refl_src = inspect.getsource(ReflectionAction)
check("reflection 有 development_failed 分支", '"development_failed"' in refl_src)
check("reflection 明确禁止再产出空壳", "console.log" in refl_src)


# ========== 7. 僵尸重置：回退重跑而不是前推成功 ==========
banner("7. 僵尸工单回退（不再替死掉的阶段宣布成功）")
import orchestrator as orch_mod

Orch = orch_mod.TicketOrchestrator
poll_src = inspect.getsource(Orch._poll_once)
check("已删除 fast-forward 的 reset_map（不再把 in_progress 推成 done）",
      "reset_map" not in poll_src)
check("_poll_once 调用 _zombie_rewind_status", "_zombie_rewind_status" in poll_src)
check("存在 _zombie_rewind_status 方法", hasattr(Orch, "_zombie_rewind_status"))
zsrc = inspect.getsource(Orch._zombie_rewind_status)
check("回退优先读 assign 日志的 from_status", "action = 'assign'" in zsrc)
check("有无限重跑止损（MAX_ZOMBIE_REWIND）", "MAX_ZOMBIE_REWIND" in zsrc)
check("超限转 blocked", "TicketStatus.BLOCKED.value" in zsrc)

upd_src = inspect.getsource(Orch._handle_agent_result)
check("orchestrator 处理 development_failed 并记 reject",
      'result.get("status") == "development_failed"' in upd_src and '"reject"' in upd_src)
check("development_failed 不落代码产物", "不落代码产物" in upd_src)


# ========== 8. 前端：步骤行渲染产出 ==========
banner("8. 前端时间轴步骤行")
import io
app_js = io.open("../frontend/app.js", encoding="utf-8").read()
check("有 _renderFileChips 公共函数", "function _renderFileChips(" in app_js)
check("skill_step 渲染产出 chip", "_renderFileChips(files, files" in app_js)
check("完成但零产出显示「无产出文件」", "无产出文件" in app_js)
check("失败步骤展示 reason", "skill-step-reason" in app_js)
css = io.open("../frontend/styles.css", encoding="utf-8").read()
check("CSS 有 skill-step-reason 样式", ".skill-step-reason" in css)
check("步骤行允许换行（否则 chip 被挤进单行）",
      "flex-wrap: wrap;" in css.split("Agent 步骤打点条目")[1][:400])


# ========== 汇总 ==========
banner(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    for f in FAIL:
        print(f"  ❌ {f}")
    sys.exit(1)
print("  🎉 假成功链路上的闸门全部就位")
