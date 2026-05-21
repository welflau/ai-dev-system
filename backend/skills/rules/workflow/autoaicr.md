---
alwaysApply: false
scene: autoaicr
priority: high
description: AutoAICR 场景规则：AI 完成编辑后的行为约束检查
---

# AutoAICR 审查准则

> 本规则仅在 AutoAICR 场景（Agent 完成文件编辑后）触发。
> 目标：轻量自检，发现常见行为偏差，不替代全量 Code Review。

## 检查项

### keep-scope
- 本次修改是否超出任务描述的范围？
- 禁止「路过式重构」：不要顺手改无关代码
- 若发现值得改进的无关代码，记录到 TODO 而非直接修改

### no-todo-left
- 代码中是否有未处理的 `TODO` / `FIXME` / `HACK` 注释？
- 若有，判断是否属于本任务范围——范围内的必须处理，范围外的记录

### avoid-over-design
- 是否引入了不必要的抽象（为一个用例写了通用框架）？
- 是否有「为未来需求预留」的代码（YAGNI 原则）？
- 三行重复代码不需要立即提取为函数

### no-hardcoded-values
- 是否有应该配置化但被硬编码的数值/字符串？
- 魔法数字必须提取为有意义的常量

### security-basics
- 是否引入了凭证硬编码、SQL 拼接、未校验的用户输入？
- 参见全局安全红线

## 输出格式

发现问题时，按以下格式输出（无问题时静默）：

```
⚠ AutoAICR 发现 N 项提示：
- [keep-scope] 具体描述
- [no-todo-left] 具体描述
```
