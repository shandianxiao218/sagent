"""图表标注模型：点标注、水平线、区间高亮。"""

from __future__ import annotations

from dataclasses import dataclass


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
