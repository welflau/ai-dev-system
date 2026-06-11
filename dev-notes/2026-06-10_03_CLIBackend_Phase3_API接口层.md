# CLIBackend — Phase 3：API 接口层

> 日期：2026-06-10  
> 系列：CLIBackend（CLI 基座支持）  
> 参考计划：`docs/20260610_01_CLI基座支持开发计划.md` § Phase 3

---

## 改动文件

`backend/main.py`

---

## 改动详情

### `/api/llm/status`（GET）

新增字段：

| 字段 | 说明 |
|------|------|
| `api_format` | 当前接入方式：`anthropic` / `openai` / `cli` |
| `cli_type` | CLI 工具类型（非 CLI 模式返回 `null`） |
| `cli_cmd` | CLI 可执行路径（非 CLI 模式返回 `null`） |
| `cli_model` | CLI 使用的模型名（非 CLI 模式返回 `null`） |
| `cli_timeout` | CLI 超时秒数（非 CLI 模式返回 `null`） |

`base_url` 在 CLI 模式下返回 `null`（不适用）。

### `/api/llm/config`（POST）

运行时更新扩展：
- 新增 `api_format` / `cli_type` / `cli_cmd` / `cli_model` / `cli_timeout` 字段处理
- `settings` 同步更新对应字段
- `.env` 持久化新增五个 CLI 键（`LLM_API_FORMAT` 也一并写入，原来只靠初始化读取）

返回值新增 `api_format` 字段，方便前端确认切换结果。

### `/api/llm/test`（POST）

无需改动——`test_connection()` 的 CLI 分支已在 Phase 2 的 `llm_client.py` 中实现，
接口层直接透传结果即可。

---

## 验证

```bash
python -c "import config; import llm_client; import main; print('OK')"
# → OK
```

三个模块导入无异常，语法检查通过。
