"""Default CI 策略——兜底（traits 空 / 没有专精策略命中时）

行为等同 Web 策略，保证老项目不崩。未来可以根据实际使用模式收紧。
"""
from __future__ import annotations

from ci.strategies.web import WebCIStrategy


class DefaultCIStrategy(WebCIStrategy):
    name = "default"
    required_traits = {}   # 不参与匹配；Loader 靠 name == "default" 认出它做兜底
    priority = 0
