---
alwaysApply: true
priority: high
description: 全局硬基线（语言一致性 / 安全红线），跟技术栈正交；细则见 global-coding
---

# 全局硬基线

> 每轮常驻。命名 / 文档 / commit / 测试等细则见 `global-coding`（写代码需要时再读）。

1. **代码标识符用英文**：变量 / 函数 / 类 / 文件 / 目录 / 分支名；禁止中文标识符与中英混写命名。注释、面向用户的文案、Markdown 可用中文。
2. **禁止写入凭证**：不写 API Key / Secret / Token / 私钥 / 含密码连接串；不碰 `.env`、`*.pem`、`credentials.*`；密钥从环境变量读取。
3. **改动克制**：不做路过式无关重构；删除大段代码或文件前先确认引用。
