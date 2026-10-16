# LightAI key 覆盖修复 + demo-cover 出图验证（2026-10-17）

2026-10-17

前置：`2026-10-16_01_真实CLI跑通skill.md`（留下「LightAI key 续期后补真实出图」）

## 一、结论

两件事：

1. demo-cover 真实出图验证补齐 —— 通过，16_01 的最后一项遗留关闭。
2. 挖出 16_01「LightAI key 401」的真正根因：**不是 key 没续期**，而是进程环境里
   残留的旧 `LIGHTAI_API_KEY` 盖过了 `.env` 的新 key。

## 二、demo-cover 出图验证通过

`_verify_cli_skill_cover.py` 真机跑通（真实 LLM + 真实 LightAI gemini）：

```
status : success   (96s, gemini)
outputs: images/cover.png  (image/png, 4312014 bytes, kind=cover_image, binary=True)
PNG 头: 正确
```

gen_image happy path 全链路到位：LLM 调 `mcp__skill_io__gen_image` → LightAI
create/poll/download → PNG 落盘 → `is_binary=True` → `kind=cover_image` 二进制回收。
16_01 里「LightAI key 续期后重跑 cover 补真实出图」这一项完成。

## 三、401 真正根因：环境变量覆盖

排查的关键一步是「同一把 key，lightai-skill 能出图、backend 却 401」：

| 来源 | key 前缀 | 状态 |
|------|---------|------|
| 进程环境变量 `LIGHTAI_API_KEY` | c854… | 旧 key，已过期 |
| `backend/.env` | da7606bf… | 新 key，有效 |
| lightai-skill `env.json` | da7606bf… | 新 key，有效 |

`load_dotenv()` 默认 `override=False`，进程环境里的旧 key 盖过 `.env`，而
`config.py` 用 `os.getenv("LIGHTAI_API_KEY")` 读 → 读到旧值 → 401。

旧 key 的来源：User/Machine 环境变量均为空，只存在于 Process 级 —— 是**宿主进程
启动时注入的残留**（早于 key 更新），进程没重启就一直带着旧值。所以删环境变量
治不了根，只能在 config 层让 `.env` 成为权威源。

## 四、修复

`config.py`：load_dotenv 之后，强制用 `.env` 覆盖 LightAI 两个配置项：

```python
_ENV_PATH = (_APP_DIR if _FROZEN else BASE_DIR) / ".env"
try:
    _dotenv = dotenv_values(str(_ENV_PATH))
    for _k in ("LIGHTAI_API_KEY", "LIGHTAI_API_BASE"):
        if _dotenv.get(_k):
            os.environ[_k] = _dotenv[_k]
except Exception:
    pass
```

只影响 LightAI 两个 key，不碰其他环境变量的覆盖行为。`.env` 是权威源
（image_gen 的 refresh 端点写的就是它）。

验证：不 unset 环境变量，`settings.LIGHTAI_API_KEY` 正确读到新 key，
`_create_lightai_task` 不再 401。

## 五、提交

- `7f8d39f` fix(config): 强制 .env 覆盖 LightAI key，避免进程环境残留旧 key 导致 401
- `ad412d2` fix(frontend): 后台任务/时间轴正确提取嵌套工具 input 的命令摘要

> 附：同一会话还修了前端 `[object Object]` 显示问题 —— DeferExecuteTool 等转发
> 工具的 input 是 `{ toolName, params: {...} }` 嵌套结构，旧逻辑
> `Object.values()[0]` 取到对象后 `String()` 变成 `[object Object]`（后台任务面板 +
> 聊天时间轴都中招）。新增 `_firstInputString` 递归提取有语义的字符串字段
> （command/cmd/path/prompt 等），跳过嵌套对象并钻进 params/input/args。
