# CLIBackend — Phase 1：配置层

> 日期：2026-06-10  
> 系列：CLIBackend（CLI 基座支持）  
> 参考计划：`docs/20260610_01_CLI基座支持开发计划.md` § Phase 1

---

## 改动内容

### `backend/config.py`

`LLM_API_FORMAT` 注释扩展为 `anthropic / openai / cli`，并在其后紧接新增四个 CLI 专属配置项：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_CLI_TYPE` | str | `"claude"` | CLI 工具类型：`claude` / `codebuddy` / `custom` |
| `LLM_CLI_CMD` | str | `"claude"` | 可执行文件名（在 PATH 中）或完整路径 |
| `LLM_CLI_MODEL` | str | `""` | 传给 CLI 的模型名；留空时复用 `LLM_MODEL` |
| `LLM_CLI_TIMEOUT` | int | `120` | 子进程最大等待秒数 |

四个字段均放在 `LLM_API_FORMAT` 行正下方，对应同一配置块，便于查找。

### `backend/.env.example`

重构为结构化分块注释，新增 CLI 模式示例段：

```ini
# ── LLM CLI 模式（LLM_API_FORMAT=cli 时生效）─────────────────────────────────
# LLM_API_FORMAT=cli
# LLM_CLI_TYPE=claude
# LLM_CLI_CMD=claude
# ...（CodeBuddy 示例也在此段）
```

两种模式的配置全部注释并存，用户只需取消注释对应段即可切换，无需手动删除旧配置。

---

## 注意事项

- `LLM_CLI_MODEL` 留空是刻意设计：允许 CLI 模式复用顶层 `LLM_MODEL`，不强制重复配置
- Windows 用户若 `claude.exe` 不在 PATH，需填完整路径（如 `C:\Users\xxx\AppData\Roaming\...\claude.exe`）
- 本阶段仅配置层，`LLM_API_FORMAT=cli` 尚未生效（需 Phase 2 实现 `_call_cli`）
