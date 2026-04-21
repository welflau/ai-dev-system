# FastAPI 后端开发最佳实践

> 本项目后端 = Python 3.11+ / FastAPI / SQLite（async）/ Pydantic v2。

## async 全栈

- **所有路由用 `async def`**，即使里面没有 await 也一样（便于未来加异步调用，不改签名）
- IO 操作（DB / HTTP / 文件）全部用 async 版本：`aiosqlite` / `httpx.AsyncClient` / `aiofiles`
- 不要在 async 函数里调同步阻塞 IO（`requests.get` / `time.sleep` / 同步 `sqlite3`），会阻塞整个事件循环

```python
# 好
import aiosqlite
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    async with aiosqlite.connect("app.db") as db:
        row = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return await row.fetchone()

# 坏 — 阻塞事件循环
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    conn = sqlite3.connect("app.db")  # 同步 IO
    ...
```

## Pydantic v2 Schema

- 请求体 / 响应体都定义 Pydantic model，不要用裸 dict
- 字段用类型注解 + `Field(description=..., ge=..., le=...)`
- 响应用 `response_model=XxxSchema` 显式声明，让 FastAPI 自动过滤敏感字段

```python
from pydantic import BaseModel, Field

class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    email: str = Field(pattern=r".+@.+\..+")

class UserResponse(BaseModel):
    id: int
    username: str

@app.post("/users", response_model=UserResponse)
async def create_user(req: CreateUserRequest):
    ...
```

## 错误处理

- 业务错误用 `HTTPException(status_code=..., detail=...)`，不要 return `{"error": "..."}` 后还返回 200
- 500 错误要在 log 里记录完整 traceback（`logger.exception`），不要只 log 一行 "error"
- 全局异常拦截：注册 `@app.exception_handler(Exception)` 兜底所有未处理异常

```python
from fastapi import HTTPException
import logging
logger = logging.getLogger(__name__)

@app.get("/items/{item_id}")
async def get_item(item_id: int):
    item = await db.fetch_one("SELECT * FROM items WHERE id = ?", (item_id,))
    if not item:
        raise HTTPException(status_code=404, detail=f"item {item_id} not found")
    return item

@app.exception_handler(Exception)
async def default_handler(request, exc):
    logger.exception("unhandled: %s", exc)
    return JSONResponse(status_code=500, content={"error": "internal error"})
```

## 依赖注入

- 复用的逻辑（DB 连接、当前用户、分页参数）用 `Depends()` 抽出
- 不要在每个路由里重复写 `conn = ...` / `user = get_current_user(token)`

```python
async def get_db():
    async with aiosqlite.connect("app.db") as db:
        yield db

@app.get("/items")
async def list_items(db = Depends(get_db), limit: int = 20):
    ...
```

## 启动 / 端口 / 部署

- 监听 `0.0.0.0`，不要写 `127.0.0.1`（容器里访问不到）
- 端口从环境变量读：`PORT = int(os.getenv("PORT", 8080))`
- 开发模式用 `uvicorn app:app --reload`，生产不要加 `--reload`
- 入口文件放 `if __name__ == "__main__"` 块便于 `python main.py` 直接跑

```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
```

## 性能

- 不要在请求里做重计算，超过 100ms 的用 `BackgroundTasks` 或队列
- SQLite 并发写用 `busy_timeout`（至少 5000ms）防 `database is locked`
- 大 JSON 响应（>1MB）考虑流式：`StreamingResponse`
