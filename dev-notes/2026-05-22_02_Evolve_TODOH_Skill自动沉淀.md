# Evolve — TODO H：Skill 自动沉淀

> 日期：2026-05-22
> 提交：`7e72802`
> 方案文档：`docs/20260509_04_系统自进化_Skill自动沉淀方案.md`

---

## 背景

ADS 已有 Reflexion（失败修复）、Failure Library（历史失败记忆），但成功案例无法自动流入技能库。本次实现第 L5 层：**AI 草稿 → 人工确认 → 自动写入**。

---

## 完整流程

```
工单验收通过（acceptance_passed）
    ↓ asyncio.create_task（不阻塞主流程）
SkillExtractorAction
    ↓ 读取工单轨迹（ticket + logs + artifacts）
    ↓ LLM 分析：是否有可复用技术模式？
    ├─ 有 → 写入 pending_skills 表（status=draft）
    └─ 无 → 静默跳过
         ↓
ChatAssistant 下次对话时感知到草案
→ system prompt 追加：「有 N 条新 Skill 草案，可询问用户是否查看」
         ↓
用户：「看看」
→ confirm_skill(action=list) 列出草案
→ confirm_skill(action=get, skill_id=xxx) 查看详情
→ confirm_skill(action=confirm) 写入 skills.json + 热重载
   confirm_skill(action=reject) 标记拒绝
```

---

## 新增文件

| 文件 | 职责 |
|------|------|
| `skills/pending_skills.py` | PendingSkillsManager：CRUD + confirm 写入 + 热重载 |
| `actions/skill_extractor.py` | SkillExtractorAction：轨迹分析 → LLM 提取 → 保存草案 |
| `actions/chat/confirm_skill.py` | ConfirmSkillAction：chat 工具，list/get/confirm/reject |

---

## 关键设计

**降级安全**：`SkillExtractorAction` 所有异常均被 `try/except` 捕获，静默跳过，绝不影响主流程。

**同名去重**：`pending_skills.add()` 检查同名草案已存在时跳过，避免重复提取。

**热重载**：`confirm()` 写入 `skills.json` 后调用 `skill_loader.reload()`，下次对话即生效，无需重启服务。

**草案标记**：写入 `skills.json` 时附加 `auto_generated: true` 和 `source_ticket`，便于审计和批量清理。

---

## LLM 提取判断标准

| 提取 | 不提取 |
|------|--------|
| 需要特定领域知识（UE Bug 规律、框架特殊约定） | 通用编程知识 |
| 多次 Reflexion 后发现的通用策略 | 只适用于本工单，无法泛化 |
| 可被未来工单直接复用的代码模式 | 已有 Skills 高度重叠 |

---

## 对话示例

```
AI 助手：「发现 1 条新 Skill 草案（来自工单 #ed915d）：
  ue-softobjectpath-lazy-load — UE StaticMesh 循环依赖改用 FSoftObjectPath 延迟加载
  要查看详情并决定是否加入技能库吗？」

用户：「确认」
→ Skill 写入 skills.json，DevAgent 后续 UE 工单自动注入此知识
```

---

## TODO.md 状态更新

H. 系统自进化 → **✅ 已完成**
