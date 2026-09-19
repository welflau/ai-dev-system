"""验证：LLM 回复文本不会被当成代码写进交付文件

回归的是 TK-20260817-39e0d4 的真实事故 —— `src/config/difficulty.ts` 整个
文件变成「一段中文说明 + ```typescript 围栏 + 真代码 + ```」，无法编译，
而且下一轮被当成「原文件」喂回 LLM，每轮"修复"都在重新污染，5 轮后 blocked。

原来的清理写法 `if content.startswith("```")` 只在回复**以围栏开头**时生效，
而 LLM 最常见的是先写一句"已修复。"再贴围栏 —— 一个字的散文就让它整个失效。

除了「该切的要切干净」，更重要的是「不该切的绝对不能动」：
把一个合法源文件切坏比放过一个脏文件严重得多。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from content_sanitizer import (
    find_content_defects,
    sanitize_delivery_files,
    strip_code_fences,
)

# === 真实事故现场：从 feat/20260817-req-32500b 的 difficulty.ts 取的原样内容 ===
REAL_CORRUPTED = '''已修复。两个文件此前都被误写入了上一轮会话的回复文本：

- `src/config/difficulty.ts` — 整段被替换成中文说明，已恢复为正确的 `DIFFICULTY_CONFIG` 常量表代码
- `src/config/constants.ts` — 文件头部混入了回复文本（`已修复。原文件混入了…`），已剔除，只保留常量本体

`difficulty.ts` 依赖 `constants.ts` 导出的 `MIN_GAP_HEIGHT`，所以两者必须一起修复才能编译。测试 16/16 通过。

`src/config/difficulty.ts` 完整内容：

```typescript
import type { DifficultyConfig } from "./difficulty.types";
import { MIN_GAP_HEIGHT } from "./constants";

export const DIFFICULTY_CONFIG: DifficultyConfig = Object.freeze({
  pipeSpeed: Object.freeze({
    initial: 2.0,
    ratePerScore: 0.02,
    min: 2.0,
    max: 6.0,
  }),
  gapHeight: Object.freeze({
    initial: 200,
    ratePerScore: -1.5,
    min: MIN_GAP_HEIGHT,
    max: 200,
  }),
});
```
'''

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ========== 1. 真实事故现场能被净化 ==========
cleaned, note = strip_code_fences(REAL_CORRUPTED, "src/config/difficulty.ts")
check(
    "真实事故: 剔除回复文本",
    cleaned.startswith("import type { DifficultyConfig }"),
    f"首行 = {cleaned.splitlines()[0][:50] if cleaned else '(空)'}",
)
check("真实事故: 无残留围栏", "```" not in cleaned)
check("真实事故: 无残留散文", "已修复" not in cleaned)
check("真实事故: 保住真代码", "MIN_GAP_HEIGHT" in cleaned and "DIFFICULTY_CONFIG" in cleaned)
check("真实事故: 给出说明", bool(note), str(note)[:70])
check("真实事故: 净化后自检通过", find_content_defects(cleaned, "src/config/difficulty.ts") == [])
check(
    "真实事故: 污染版自检能报出问题",
    len(find_content_defects(REAL_CORRUPTED, "src/config/difficulty.ts")) >= 2,
    str(find_content_defects(REAL_CORRUPTED, "src/config/difficulty.ts")),
)

# ========== 2. 各种污染形态 ==========
CASES = [
    ("纯围栏包裹", "```ts\nexport const A = 1;\n```", "a.ts", "export const A = 1;"),
    ("无语言标记", "```\nexport const A = 1;\n```", "a.ts", "export const A = 1;"),
    ("前置散文", "以下是实现：\n\n```ts\nexport const A = 1;\n```", "a.ts", "export const A = 1;"),
    ("后置散文", "```ts\nexport const A = 1;\n```\n\n测试已通过。", "a.ts", "export const A = 1;"),
    ("前后都有散文", "已修复。\n\n```py\nimport os\ndef f(): return 1\n```\n\n完成。", "a.py", "import os\ndef f(): return 1"),
    ("英文散文", "Here's the fix:\n\n```js\nexport const A = 1;\n```", "a.js", "export const A = 1;"),
]
for name, raw, path, want in CASES:
    got, _ = strip_code_fences(raw, path)
    check(f"净化/{name}", got.strip() == want, f"得到 {got.strip()[:40]!r}")

# ========== 3. 合法文件绝对不能被改动（最关键） ==========
UNTOUCHED = [
    ("普通 ts", "export const A = 1;\nexport const B = 2;\n", "a.ts"),
    ("中文注释源码", "// 难度参数表\nimport { X } from './x';\nexport const CFG = { a: 1 };\n", "a.ts"),
    ("纯中文注释多行", "/**\n * 难度参数唯一常量源（config-driven）。\n * 调平衡只需改这一处。\n */\nexport const C = 1;\n", "a.ts"),
    ("Python docstring", '"""模块说明：这是一个中文文档字符串，说明本模块用途。"""\nimport os\n\n\ndef f():\n    return os.getcwd()\n', "a.py"),
    ("markdown 保留围栏", "# 标题\n\n说明文字\n\n```ts\nconst a = 1;\n```\n", "README.md"),
    ("md 纯散文", "已修复。两个文件此前都被误写入了回复文本。\n", "notes.md"),
    ("源码含两个围栏块", "// docs:\n// ```\n// example\n// ```\nexport const A = 1;\n", "a.ts"),
    ("HTML", "<!DOCTYPE html>\n<html><body><h1>标题</h1></body></html>\n", "i.html"),
    ("JSON", '{\n  "name": "x",\n  "version": "1.0.0"\n}\n', "p.json"),
]
for name, raw, path in UNTOUCHED:
    got, note2 = strip_code_fences(raw, path)
    check(f"不动/{name}", got == raw and note2 is None,
          "被改了!" if got != raw else "")

# 合法文件自检也不该报警
for name, raw, path in UNTOUCHED:
    if path.endswith((".md", ".txt")):
        continue
    d = find_content_defects(raw, path)
    check(f"自检不误报/{name}", d == [], str(d))

# ========== 4. 批量落盘净化 ==========
files = {
    "src/config/difficulty.ts": REAL_CORRUPTED,
    "src/config/constants.ts": "已修复。原文件混入了回复文本：\n\n```ts\nexport const MIN_GAP_HEIGHT = 100;\n```\n",
    "src/ok.ts": "export const OK = true;\n",
    "README.md": "# 项目\n\n```sh\nnpm i\n```\n",
}
out, warns = sanitize_delivery_files(files, source="test")
check("批量: 污染文件已净化",
      out["src/config/difficulty.ts"].startswith("import type")
      and out["src/config/constants.ts"].strip() == "export const MIN_GAP_HEIGHT = 100;")
check("批量: 干净文件原样", out["src/ok.ts"] == files["src/ok.ts"])
check("批量: markdown 原样", out["README.md"] == files["README.md"])
check("批量: 文件数不变", set(out) == set(files))
check("批量: 有告警记录", len(warns) >= 2, f"{len(warns)} 条")

# ========== 5. 边界，不能崩 ==========
for name, raw in [("空串", ""), ("None", None), ("只有围栏", "```\n```"),
                  ("单个围栏", "```ts\nconst a=1;"), ("只有散文", "已修复。")]:
    try:
        strip_code_fences(raw, "a.ts")
        find_content_defects(raw or "", "a.ts")
        check(f"边界/{name}", True)
    except Exception as e:
        check(f"边界/{name}", False, f"{type(e).__name__}: {e}")

check("边界/非字符串内容不丢失",
      sanitize_delivery_files({"a.ts": None, "b.ts": 123})[0] == {"a.ts": None, "b.ts": 123})
check("边界/空 dict", sanitize_delivery_files({})[0] == {})

# ========== 6. 注释行不能被当成回复文本（防误报回归） ==========
# 源码里用中文写注释非常普遍，不能因为「首行是中文」就报脏。
COMMENT_FIRST = [
    ("// 中文行注释", "// 难度参数表，已修复过一次\nexport const A = 1;\n", "a.ts"),
    ("/* 块注释", "/* 已完成的实现说明 */\nexport const A = 1;\n", "a.ts"),
    ("# Python 注释", "# 已修复：补上缺失的导入\nimport os\n", "a.py"),
    ("docstring", '"""已完成的模块说明。"""\nimport os\n', "a.py"),
    ("JSDoc", "/**\n * 已修复。说明如下：\n */\nexport const A = 1;\n", "a.ts"),
    ("HTML 注释", "<!-- 已修复：补上 meta -->\n<html></html>\n", "i.html"),
    ("SQL 注释", "-- 已修复：加了索引\nSELECT 1;\n", "q.sql"),
]
for name, raw, path in COMMENT_FIRST:
    d = find_content_defects(raw, path)
    check(f"注释不误报/{name}", d == [], str(d))
    got, note3 = strip_code_fences(raw, path)
    check(f"注释不改动/{name}", got == raw and note3 is None)

# 但真正的回复文本仍要被识别出来
for name, raw in [
    ("中文回复", "已修复。文件内容如下：\nexport const A = 1;\n"),
    ("英文回复", "Here's the fixed file:\nexport const A = 1;\n"),
]:
    d = find_content_defects(raw, "a.ts")
    check(f"回复仍被识别/{name}", any("首行" in x for x in d), str(d))

print(f"\n=== {len(PASSED)} 通过 / {len(FAILED)} 失败 ===")
if FAILED:
    for f in FAILED:
        print(f"  FAILED: {f}")
    sys.exit(1)
print("=== 全部通过 ===")
