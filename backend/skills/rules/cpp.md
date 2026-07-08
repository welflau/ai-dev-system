---
alwaysApply: false
pack: code-quality
paths:
  - "**/*.cpp"
  - "**/*.h"
  - "**/*.hpp"
  - "**/*.cc"
priority: high
description: C++ 文件专属规范（内存管理 / 空指针 / RAII / 并发安全）
---

# C++ 编码规范

> 仅在编辑 .cpp / .h / .hpp 文件时注入。

## 一、内存管理

- 优先使用智能指针：`std::unique_ptr`（独占）、`std::shared_ptr`（共享）
- UE 项目中用 `TUniquePtr` / `TSharedPtr` / `TWeakPtr`
- 禁止裸 `new`/`delete`（除非封装在 RAII 对象内）
- 堆分配的资源必须有明确所有者

## 二、空指针防御

- 解引用指针前必须判 `nullptr`
- UE 中 `GetComponent<T>()` / `Cast<T>()` 返回值**必须**检查非 null 后再使用
- 返回指针的函数，文档中明确标注是否可能返回 `nullptr`

## 三、RAII 原则

- 资源获取即初始化：锁、文件句柄、网络连接等必须用 RAII 包装
- 不要在构造函数中调用虚函数
- 析构函数不应抛出异常

## 四、并发安全

- 共享数据的读写必须加锁（`std::mutex` / UE `FCriticalSection`）
- 避免双重检查锁定（DCLP）的错误实现
- UE 中跨线程操作资产/Actor 必须通过 `AsyncTask(ENamedThreads::GameThread, ...)` 回到 GameThread

## 五、常见陷阱

- 数组/容器访问前检查边界（`Num()` / `size()` 判断）
- 整数除法注意截断（需要浮点结果时至少一个操作数转为 float）
- 字符串格式化使用 `FString::Printf` / `TEXT()` 宏，避免 `std::string` 与 `FString` 混用
- 循环中不要修改正在遍历的容器（可能导致迭代器失效）

## 六、代码风格

- 函数单一职责，超过 80 行考虑拆分
- 复杂条件提取为具名 bool 变量（`bool bIsValidTarget = ...`）
- `#include` 顺序：对应头文件 → 系统头文件 → 第三方 → 项目头文件
