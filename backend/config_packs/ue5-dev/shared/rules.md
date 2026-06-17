# {{project_name}}

## UE5 项目规范

**项目路径**：`{{repo_path}}`
**技术栈**：{{tech_stack}}

### 与 UE Editor 通信

唯一方式是通过 `scripts/ue_python.py` 发送 Python 代码：

```bash
python scripts/ue_python.py "import unreal; <操作代码>"
```

- UE Editor 必须已运行，Python Editor Script Plugin 已启用
- 退出码 2 = Editor 未运行；退出码 1 = Python 执行出错
- 单次调用包含完整逻辑（查询+操作+验证），避免多次往返

### 禁止事项

- 禁止直接修改 `.uasset` 二进制文件
- 禁止在 Python 代码中 `import os` 执行系统命令
- 禁止跳过 `unreal.EditorAssetLibrary.save_asset()` 直接退出

### C++ 命名规范

- 类前缀：AActor 派生用 `A`，UObject 派生用 `U`，接口用 `I`，结构体用 `F`
- 文件名与类名一致，头文件 `.h`，实现 `.cpp`
- UPROPERTY / UFUNCTION 宏必须写，蓝图可见属性加 `BlueprintReadWrite`
