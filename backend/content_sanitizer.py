"""交付文件内容净化 —— 防止 LLM 的对话回复文本被当成代码写进仓库。

## 修的真实事故

TK-20260817-39e0d4（建立难度参数配置常量表）连续 5 轮被打回后 blocked。
根因不是逻辑写错，是 `src/config/difficulty.ts` 整个文件变成了这样：

    已修复。两个文件此前都被误写入了上一轮会话的回复文本：      <- 第 1 行
    - `src/config/difficulty.ts` — 整段被替换成中文说明，已恢复…
    ...
    ```typescript                                              <- 第 10 行
    import type { DifficultyConfig } from "./difficulty.types";  <- 真正的代码
    ...
    ```                                                        <- 第 48 行

也就是说 LLM 返回的是「**一段解释 + 围栏包着的代码**」，而落盘逻辑把
整个回复原样写进了 .ts 文件。文件既不能编译，又在下一轮被当成「原文件」
喂回给 LLM，于是每轮"修复"都在重新污染 —— 这是个自我延续的循环，
ReviewAgent 打了 5/10、5/10、4/10、2/10、5/10，最后撞上限 blocked。

## 为什么原来的清理没挡住

代码库里有 5 处以上重复的同一个写法：

    if content.strip().startswith("```"):
        ...去掉围栏行...

它只在**回复以围栏开头**时才生效。而 LLM 最常见的行为恰恰是先写一句
"已修复。"再贴围栏 —— 前面有一个字的散文，这个判断就整个失效，
于是散文和围栏标记一起进了文件。

所以这里按「围栏**所在位置**」而不是「是否在开头」来处理。

## 取舍

净化只在能明确判定时动手，判不准就原样返回：宁可放过一个脏文件，
也不要把一个合法文件切坏。特别地：
  - .md / .txt / .markdown 不做围栏提取（围栏是正文的一部分）
  - 围栏外的文本必须看起来像散文，才认为围栏内才是正文
  - 只有一个围栏块时才提取，多个块含义不明确（可能是文档），不猜
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger("content_sanitizer")

# 围栏是正文语义的一部分，不能提取
_PROSE_EXTS = {".md", ".markdown", ".txt", ".rst", ".adoc"}

# ```lang 开栏 / ``` 闭栏。语言标记允许 c++、objective-c 之类的符号
_FENCE_RE = re.compile(r"^[ \t]*```+[ \t]*([a-zA-Z0-9_+#.\-]*)[ \t]*$", re.MULTILINE)

# 散文信号：出现这些就更像人在说话，而不是源码
_PROSE_HINTS = (
    "已修复", "已完成", "已恢复", "已剔除", "已更新", "已调整", "已添加",
    "修复了", "完整内容", "以下是", "如下所示", "说明：", "注意：",
    "here is", "here's", "i've ", "i have ", "fixed", "updated the",
    "the following", "as requested", "let me know",
)

# 代码信号：出现这些就更像源码而不是散文
_CODE_HINTS = (
    "import ", "from ", "export ", "const ", "let ", "var ", "function ",
    "class ", "def ", "return", "public ", "private ", "#include",
    "package ", "using ", "interface ", "type ", "struct ", "enum ",
    "=>", "{", "}", ";", "()",
)


def _fence_spans(text: str) -> List[Tuple[int, int, int, int]]:
    """配对围栏，返回 [(开栏行首, 开栏行尾, 闭栏行首, 闭栏行尾)]。

    奇数个围栏（最后一个没闭合）时丢掉落单的那个 —— 半个块无法安全提取。
    """
    marks = list(_FENCE_RE.finditer(text))
    spans = []
    for i in range(0, len(marks) - 1, 2):
        open_m, close_m = marks[i], marks[i + 1]
        spans.append((open_m.start(), open_m.end(), close_m.start(), close_m.end()))
    return spans


def _is_comment_or_docstring(line: str) -> bool:
    """这一行是注释或 docstring 开头？

    注释里写中文完全正常（`// 难度参数表`、三引号 docstring 里的中文说明），
    不能因为「首行是中文」就判成回复文本 —— 那会把大量合法源文件误报成脏文件。
    """
    s = (line or "").strip()
    if not s:
        return False
    return s.startswith((
        "//", "/*", "*", "#", "--", ";", "%", "<!--",
        '"""', "'''", '"', "'",
    ))


def _looks_like_prose(text: str) -> bool:
    """这段文字更像「人在说话」而不是源码？"""
    s = (text or "").strip()
    if not s:
        return False

    low = s.lower()
    if any(h in low for h in _PROSE_HINTS):
        return True

    # 中文占比高 → 散文（源码里的中文通常只在注释/字符串里，占比不会高）
    cjk = sum(1 for ch in s if "一" <= ch <= "鿿")
    if cjk and cjk / max(len(s), 1) > 0.12:
        # 但要排除「全是中文注释的源码」：有明确代码信号就不算散文
        if not any(h in s for h in ("import ", "export ", "const ", "def ", "function ", "#include")):
            return True

    # markdown 列表 / 引用开头，且没有代码信号
    if re.match(r"^[-*>]\s", s) and not any(h in s for h in _CODE_HINTS):
        return True

    return False


def strip_code_fences(content: str, path: str = "") -> Tuple[str, Optional[str]]:
    """摘掉 LLM 回复里的围栏和散文，返回 (净化后内容, 说明) 。

    说明为 None 表示没动过；非 None 时是一句人话，供日志/审计说明改了什么。

    只在**能明确判定**时动手：
      1. 整个回复就是一个围栏块（前后可能有散文）→ 取块内内容
      2. 回复以围栏开头并以围栏结尾 → 去掉首尾围栏行
    其余情况原样返回。
    """
    if not content:
        return content, None

    ext = ""
    if path:
        m = re.search(r"(\.[A-Za-z0-9_+]+)$", path.strip())
        ext = (m.group(1).lower() if m else "")
    if ext in _PROSE_EXTS:
        return content, None  # .md 的围栏是正文

    spans = _fence_spans(content)
    if len(spans) != 1:
        # 0 个：没围栏，无事可做。
        # 多个：可能是文档或多文件回复，切哪个都可能错，不猜。
        return content, None

    open_s, open_e, close_s, close_e = spans[0]
    before = content[:open_s]
    inside = content[open_e:close_s]
    after = content[close_e:]

    if not inside.strip():
        return content, None

    outside = (before + "\n" + after).strip()
    if not outside:
        # 情况 2：干净的整体围栏包裹
        return inside.strip("\n"), "去掉包裹整个文件的 ``` 围栏"

    # 情况 1：围栏外还有文字。只有当它像散文、且围栏内像代码时才提取，
    # 否则可能是「源码里恰好有个围栏」（比如 docstring 里贴了示例）。
    if _looks_like_prose(outside) and any(h in inside for h in _CODE_HINTS):
        head = outside.replace("\n", " ")[:60]
        return inside.strip("\n"), f"剔除围栏外的回复文本（{len(outside)} 字符，开头：{head}…）"

    return content, None


def find_content_defects(content: str, path: str = "") -> List[str]:
    """交付文件里仍然可疑的地方；空列表表示看起来正常。

    净化之后再跑一遍，用于兜底告警 —— 净化只处理能确定的情况，
    剩下的说不清的脏内容至少要留下痕迹，不能静默写盘。
    """
    if not content or not content.strip():
        return ["内容为空"]

    ext = ""
    if path:
        m = re.search(r"(\.[A-Za-z0-9_+]+)$", path.strip())
        ext = (m.group(1).lower() if m else "")
    if ext in _PROSE_EXTS:
        return []

    defects: List[str] = []

    if _FENCE_RE.search(content):
        defects.append("仍含 markdown ``` 围栏标记")

    # 首个非空行是散文 → 大概率整个文件是回复文本。
    # 注释/docstring 行先排除：源码里用中文写注释很正常。
    first = next((ln for ln in content.splitlines() if ln.strip()), "")
    if not _is_comment_or_docstring(first) and _looks_like_prose(first):
        defects.append(f"首行疑似回复文本：{first.strip()[:60]}")

    if content.lstrip().startswith("[LLM_UNAVAILABLE]"):
        defects.append("内容是 LLM 不可用的占位符")

    return defects


def sanitize_delivery_files(files: dict, *, source: str = "") -> Tuple[dict, List[str]]:
    """批量净化待落盘的 {path: content}，返回 (净化后, 告警列表)。

    落盘前的最后一道闸。不抛异常、不丢文件 —— 写盘失败比写脏更难排查，
    所以这里只修能修的、报不确定的，永远把一份可写的 dict 交出去。
    """
    if not files:
        return files, []

    cleaned: dict = {}
    warnings: List[str] = []
    for path, content in files.items():
        if not isinstance(content, str):
            cleaned[path] = content
            continue

        new_content, note = strip_code_fences(content, path)
        if note:
            warnings.append(f"{path}: {note}")
            logger.warning("[净化%s] %s: %s", f"/{source}" if source else "", path, note)

        for defect in find_content_defects(new_content, path):
            warnings.append(f"{path}: ⚠ {defect}")
            logger.warning("[净化%s] %s 仍可疑: %s", f"/{source}" if source else "", path, defect)

        cleaned[path] = new_content

    return cleaned, warnings
