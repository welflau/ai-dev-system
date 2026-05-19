# NextPhase B-0：UE Python 桥接

> 系列：NextPhase  
> 日期：2026-05-18  
> 提交：`5bdbd8b`  
> 对应计划：`docs/20260518_04_ADS下一阶段综合开发计划.md` 方向 B-0

---

## 背景

ADS 原有 UCP 协议（TCP 9876）发送结构化命令（截图、启动等），但无法发送任意 Python 代码。ECC 的 `ue_python.py` 使用 UE 官方 `remote_execution.py`（UDP 多播发现 + TCP 执行），能发送任意 Python，是 Blueprint 生成、关卡布置等创作能力的基础。

---

## 实现

### `backend/engines/ue_python_bridge.py`

移植 ECC/scripts/ue_python.py，适配 ADS 异步环境：

**通信协议**：
```
ADS 后端
  ↓ asyncio.create_subprocess_exec（非阻塞）
子进程（runner 脚本）
  ↓ UDP 多播（port 6776）
UE Editor（发现阶段，3秒）
  ↓ TCP 连接
执行 Python 代码 → 返回 JSON 结果
```

**引擎路径优先顺序**：
1. 显式传入 `engine_path`
2. 环境变量 `UE_ENGINE_PATH`
3. Windows 注册表（复用 ADS `ue_resolver.detect_installed_engines()`）
4. 常见路径枚举（C:-I: 盘 × UE 5.1-5.7）

**多 Editor 匹配**：
- 查 `projects.local_repo_path` 作为 hint
- 按 `project_root` 或 `project_name` 精准匹配
- 多个 Editor 无法匹配时取第一个并警告

**返回格式**：
```python
{
    "success": bool,
    "stdout": str,   # 合并的 print() 输出
    "result": str,   # 最后一个表达式的值
    "error": str | None,
    "exit_code": int,
}
```

### `backend/actions/ue_run_python.py`

`UERunPythonAction`：作为 ChatAssistantAgent 的工具暴露，LLM 可主动调用。

### `/ue-run` 命令升级

从「⚠️ 尚未实现」升级为真实桥接：
```
/ue-run import unreal; print(unreal.SystemLibrary.get_engine_version())
→ ✅ 执行成功
```
→ `5.5.0-37670630+++UE5+Release-5.5`

---

## 前置条件

UE Editor 启用 Remote Execution Server：
```
Edit > Project Settings > Plugins > Python > Enable Remote Execution Server ✓
```

或设置环境变量：
```
set UE_ENGINE_PATH=C:\Epic Games\UE_5.5
```

---

## 下一步

- **B-1**：BlueprintGenAction — 基于 Python 桥接生成 BP
- **B-2**：LevelGenAction — 基于 Python 桥接布置关卡
- **B-3**：UEEditorAgent — 封装 BP/Level 生成为工单 Agent
