"""行情数据模型：股票信息、日K线、交易日历。"""

from __future__ import annotations

from dataclasses import dataclass


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
