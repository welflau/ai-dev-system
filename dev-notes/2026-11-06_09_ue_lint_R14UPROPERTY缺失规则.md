# DevLog：ue_lint R14 UPROPERTY 缺失规则

> 日期：2026-11-06
> 关联：R9-R13 生命周期资源检查
> 位置：`plugins/ue5/actions/ue_lint/rules.py`

## 目标

延续生命周期资源检查，落地 R14：UObject 指针成员缺 UPROPERTY() 宏。

## 设计动机

UObject 裸指针成员没有 `UPROPERTY()` 时，**GC 不知晓该引用**，可能回收对象导致悬挂指针——这是 UE 最常见、最危险的 bug 之一，与 R13（弱引用）形成呼应：R13 管 TWeakObjectPtr，R14 管裸 UObject 指针。

## 设计

- `_RE_UOBJECT_PTR_DECL`：匹配 `U/A` 开头的类型指针成员声明（`Uxxx* Name;` / `Axxx* Name;`）
- 检查声明前 300 字符是否有 `UPROPERTY` 宏
- 无 UPROPERTY → warning

**关键决策**：
1. **只检查 .h 文件**：成员声明通常在头文件，.cpp 里的局部变量/参数不需要 UPROPERTY。
2. **正则只匹配 U/A 开头**：F 结构体指针（FVector*）不是 UObject，自动排除。
3. **排除函数参数**：同一行内声明前有未闭合 `(` 的（如 `void Foo(AActor* X);`）跳过。
4. **snippet 300 字符**：覆盖带长 specifier 的 UPROPERTY 宏。

## 验证（7 场景全过）

| 场景 | 结果 |
|---|---|
| 成员有 UPROPERTY | ✅ 不报 |
| 成员无 UPROPERTY | ✅ 报 warning，含变量名 |
| 函数参数/声明 | ✅ 不报（括号未闭合排除） |
| F 结构体指针 | ✅ 不报（正则只匹配 U/A） |
| 逃生注释 | ✅ 不报 |
| 非 .h 文件 | ✅ 跳过 |
| 长 UPROPERTY 宏 | ✅ 不报 |

## 收尾

ue_lint 规则集现为 R1-R14。生命周期资源检查完整闭环：委托配对(R9)/空引用(R10)/递归(R11)/Timer配对(R12)/弱引用守卫(R13)/UPROPERTY缺失(R14)。
