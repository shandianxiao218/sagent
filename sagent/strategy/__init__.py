"""策略模块：信号检测、LLM 判断、入场确认、扫描参数。"""

from .judge import simulated_llm_judge
from .params import (
    EntryParams,
    JudgeParams,
    PortfolioParams,
    ScanParams,
    SignalParams,
    StopLossParams,
)
from .scanner import (
    desc,
    forward_returns,
    load_and_filter_signals,
    scan_signals_from_closes,
)
from .signal import (
    HasDailyBars,
    _ma,
    check_signal_from_closes,
    filter_stock_pool,
    technical_candidates,
    technical_candidates_from_bars_map,
)

__all__ = [
    # Signal
    "check_signal_from_closes",
    "filter_stock_pool",
    "technical_candidates",
    "technical_candidates_from_bars_map",
    "HasDailyBars",
    # Judge
    "simulated_llm_judge",
    # Params
    "SignalParams",
    "JudgeParams",
    "StopLossParams",
    "ScanParams",
    "EntryParams",
    "PortfolioParams",
]
