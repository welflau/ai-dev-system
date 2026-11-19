"""frontmatter 解析纯函数 —— P2 拆环叶子模块。

原先 ``_parse_frontmatter`` 定义在 ``skills.loader``，``plugins.registry``
为了用它反过来 import ``skills.loader``，与 ``skills.loader → plugins.registry``
（取 iter_plugin_dirs）构成双向环。抽到本叶子模块后两边都单向依赖它。

本模块刻意不 import 任何项目内模块，只依赖标准库，因此在静态依赖图里是叶子。
"""
from __future__ import annotations

import logging
import re
from typing import Tuple

logger = logging.getLogger("skills.frontmatter")

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    """解析 YAML frontmatter + body。没有 frontmatter 时 body 是全文，frontmatter 为 {}。"""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    try:
        import yaml
        return yaml.safe_load(fm_text) or {}, body
    except Exception as e:
        logger.warning("frontmatter 解析失败: %s", e)
        return {}, body
