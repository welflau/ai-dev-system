---
name: ue5-build-rules
description: UE5 项目构建与编码规范
type: always
---

# {{project_name}} — UE5 规范

**项目路径**：`{{repo_path}}`  
**技术栈**：{{tech_stack}}

## 与 UE Editor 通信

唯一方式是通过 `scripts/ue_python.py`：

```bash
python scripts/ue_python.py "import unreal; <操作代码>"
```

- 退出码 2 = Editor 未运行；退出码 1 = Python 执行出错
- 单次调用包含完整逻辑，避免多次往返

## C++ 命名规范

- Actor 子类前缀 `A`，UObject 子类前缀 `U`，接口前缀 `I`，结构体前缀 `F`
- UPROPERTY / UFUNCTION 宏必填
- 蓝图可见属性加 `BlueprintReadWrite`

## 禁止事项

- 禁止直接修改 `.uasset` 二进制文件
- 禁止跳过 `save_asset()` 直接退出
