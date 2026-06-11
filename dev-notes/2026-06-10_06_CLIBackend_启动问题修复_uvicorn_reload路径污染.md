# CLIBackend — 启动问题修复：uvicorn reload 路径污染

> 日期：2026-06-10  
> 系列：CLIBackend（CLI 基座支持）

---

## 问题现象

`main.py` 改动后，HTTP 接口返回的响应里缺少新增字段（`api_format`、`cli_model_options` 等），
但直接 `python -c "import main; ..."` 运行结果完全正确。

## 根本原因

`main.py` 的 `__main__` 块原来是：

```python
uvicorn.run(
    "main:app",           # 字符串形式
    reload=settings.DEBUG,  # DEBUG=true → 开启 reload
    ...
)
```

`uvicorn --reload` 模式下：
1. 父进程（reloader）监听文件变化
2. 子进程（worker）通过字符串 `"main:app"` 重新 import 模块
3. **子进程继承的 `sys.path` 不包含 `backend/`**，导致 Python 从其他位置（缓存、site-packages 等）找到旧的 `main` 模块
4. 结果：代码改了，但服务器运行的还是旧版本

额外副作用：`__main__` 块里清除 `__pycache__` 的逻辑在 reload 模式下每次文件变化都会触发，导致 watchfiles 检测到文件删除后再次 reload，形成死循环。

## 修复方案

`main.py` `__main__` 块改为：

```python
uvicorn.run(
    app,          # 直接传 app 对象，不走字符串解析
    host=...,
    port=...,
    reload=False, # 永远禁用 reload
)
```

## 正确启动方式

```bash
cd backend
python main.py
```

代码修改后手动重启即可（Ctrl+C 后重新运行）。不再依赖 uvicorn reload。

## 经验教训

- `uvicorn.run("module:app", reload=True)` 在 Windows + Git Bash 环境下存在 `sys.path` 污染问题
- 传 app 对象而非字符串是更安全的做法，避免子进程路径解析不确定性
- `__pycache__` 清除逻辑不应在 reload 模式下运行（会触发无限 reload 循环）
