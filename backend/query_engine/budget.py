"""
Budget — 工具调用循环的三重安全阀：Token / 轮次 / 时间

用法：
    budget = Budget(max_turns=30, max_tokens=100_000, max_seconds=180.0)
    # 每轮开始前检查
    if reason := budget.check():
        yield BudgetExceededEvent(reason=reason)
        return
    # 每轮结束后消耗
    budget.consume(tokens=input_tokens + output_tokens, turns=1)
"""
import time
from dataclasses import dataclass, field


@dataclass
class Budget:
    """三重预算上限：Token 总量 / 轮次数 / 执行秒数 + Diminishing Returns 检测"""
    max_tokens:  int   = 200_000
    max_turns:   int   = 50
    max_seconds: float = 600.0
    # Diminishing Returns：连续 N 轮每轮 token 增量 < threshold → 判定原地踏步
    diminishing_threshold: int = 500   # 每轮增量低于此值视为无效轮次
    diminishing_window:    int = 3     # 连续 N 轮无效才触发

    # 内部计数（不参与 __init__）
    _used_tokens:  int   = field(default=0,                        init=False, repr=False)
    _used_turns:   int   = field(default=0,                        init=False, repr=False)
    _start_time:   float = field(default_factory=time.monotonic,   init=False, repr=False)
    _token_deltas: list  = field(default_factory=list,             init=False, repr=False)

    def check(self) -> str | None:
        """返回超限/空转原因字符串，未超限返回 None。在每轮 LLM 调用前调用。"""
        if self._used_tokens >= self.max_tokens:
            return f"Token 上限已达到（{self._used_tokens:,} / {self.max_tokens:,}）"
        if self._used_turns >= self.max_turns:
            return f"轮次上限已达到（{self._used_turns} / {self.max_turns}）"
        elapsed = time.monotonic() - self._start_time
        if elapsed >= self.max_seconds:
            return f"时间上限已达到（{elapsed:.1f}s / {self.max_seconds:.0f}s）"
        if self.is_diminishing():
            last = self._token_deltas[-self.diminishing_window:]
            return (
                f"检测到原地踏步（连续 {self.diminishing_window} 轮每轮增量 "
                f"{[int(d) for d in last]} < {self.diminishing_threshold} token）"
            )
        return None

    def consume(self, tokens: int = 0, turns: int = 0) -> None:
        """消耗预算（每轮 LLM 返回后调用）"""
        self._used_tokens += tokens
        self._used_turns  += turns
        # 滑动窗口记录每轮 token 增量
        self._token_deltas.append(tokens)
        if len(self._token_deltas) > self.diminishing_window:
            self._token_deltas.pop(0)

    def is_diminishing(self) -> bool:
        """连续 N 轮每轮增量 < threshold → 原地踏步"""
        if len(self._token_deltas) < self.diminishing_window:
            return False
        return all(d < self.diminishing_threshold for d in self._token_deltas[-self.diminishing_window:])

    @property
    def used_tokens(self) -> int:
        return self._used_tokens

    @property
    def used_turns(self) -> int:
        return self._used_turns

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time
