from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StockInfo:
    symbol: str
    name: str
    sector: str
    avg_amount_20d: float
    is_st: bool = False
    is_suspended: bool = False
    listing_days: int = 999


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


@dataclass(frozen=True)
class TradeDay:
    date: str
    is_open: bool


@dataclass(frozen=True)
class SectorSnapshot:
    sector: str
    date: str
    turnover_rank: int
    gain_rank: int
    pct_chg: float
    limit_up_count: int
    strong_stocks: list[str]
    up_count: int = 0
    down_count: int = 0


@dataclass(frozen=True)
class Exclusion:
    symbol: str
    reason: str


@dataclass(frozen=True)
class StockPoolResult:
    included: list[StockInfo]
    excluded: list[Exclusion]


@dataclass(frozen=True)
class Candidate:
    symbol: str
    name: str
    sector: str
    metrics: dict[str, Any]
    reasons: list[str]
    risk_reward_ratio: float = 0.0


@dataclass(frozen=True)
class KlineDescription:
    symbol: str
    text: str
    key_low: float
    risk_price: float
    fields: dict[str, Any]


@dataclass(frozen=True)
class SectorSummary:
    sector: str
    turnover_top10_days: int
    gain_top10_count_30d: int
    limit_up_breadth_count_30d: int
    recent_pct_chg: float
    representative_stocks: list[str]
    performance_windows: dict[str, float] = field(default_factory=dict)
    rank_windows: dict[str, int] = field(default_factory=dict)
    data_source: str = "fixture"
    window: str = "30d"


@dataclass(frozen=True)
class SectorValidation:
    sector: str
    level: str
    rules: dict[str, bool]
    reasons: list[str]
    needs_llm: bool = False


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    model: str = "GLM5.1"
    risk: str = "仅作研究和辅助分析，不构成投资建议。"
    confidence: float = 0.7
    key_low: float | None = None
    invalid_condition: str = ""


@dataclass
class Position:
    symbol: str
    name: str
    sector: str
    buy_price: float
    quantity: int
    amount: float
    key_low: float
    stop_loss_price: float
    trade_date: str
    half_taken: bool = False
    remaining_quantity: int | None = None
    trend_break_ref: float = 0.0  # 趋势破坏参考位
    trend_break_desc: str = ""  # 趋势破坏参考位描述

    def __post_init__(self) -> None:
        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity


@dataclass
class Portfolio:
    cash: float
    positions: list[Position] = field(default_factory=list)
    weekly_open_count: int = 0
    week_id: str = ""
    trade_history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BuyResult:
    portfolio: Portfolio
    position: Position


@dataclass(frozen=True)
class PositionSuggestion:
    symbol: str
    action: str
    reason: str
    risk: str = "仅作研究和辅助分析，不构成投资建议。"


@dataclass(frozen=True)
class ChartAnnotation:
    """K线图上的点标注（买卖点、关键低点等）。"""

    date: str
    price: float
    text: str
    color: str = "blue"
    symbol: str = "star"
    size: int = 12


@dataclass(frozen=True)
class ChartHLine:
    """水平参考线（止损线、关键低点线等）。"""

    price: float
    color: str = "gray"
    dash: str = "dash"
    label: str = ""
    width: int = 1


@dataclass(frozen=True)
class ChartRange:
    """区间高亮（持仓区间、回调区间等）。"""

    start_date: str
    end_date: str
    color: str = "rgba(255,255,0,0.1)"
    label: str = ""


def dataclass_to_dict(value: Any) -> Any:
    return asdict(value)
