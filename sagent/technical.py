"""技术分析模块（兼容层）。

所有函数已拆分到 strategy/signal.py 和 strategy/judge.py。
本文件保持 re-export，现有 import 不断。
"""

from __future__ import annotations

# Re-export everything from the new locations
from .strategy.judge import simulated_llm_judge
from .strategy.signal import (
    HasDailyBars,
    _ma,
    check_signal_from_closes,
    filter_stock_pool,
    technical_candidates,
    technical_candidates_from_bars_map,
)

__all__ = [
    "simulated_llm_judge",
    "check_signal_from_closes",
    "filter_stock_pool",
    "technical_candidates",
    "technical_candidates_from_bars_map",
    "HasDailyBars",
    "_ma",
]
