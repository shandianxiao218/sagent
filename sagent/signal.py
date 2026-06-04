"""信号检测模型：候选股、K线描述、排除记录、粗筛结果。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .market import StockInfo


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
