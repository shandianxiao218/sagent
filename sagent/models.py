"""数据模型兼容层 — 所有 dataclass 仍可从此模块导入。

实际定义已迁移到按领域拆分的子模块：
  market.py  → StockInfo, DailyBar, TradeDay
  signal.py  → Exclusion, StockPoolResult, Candidate, KlineDescription
  sector.py  → SectorSnapshot, SectorSummary, SectorValidation
  portfolio.py → Position, Portfolio, BuyResult, PositionSuggestion, Decision
  chart_models.py → ChartAnnotation, ChartHLine, ChartRange
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

# Re-export all models for backward compatibility
from .chart_models import ChartAnnotation, ChartHLine, ChartRange
from .market import DailyBar, StockInfo, TradeDay
from .portfolio import BuyResult, Decision, Portfolio, Position, PositionSuggestion
from .sector import SectorSnapshot, SectorSummary, SectorValidation
from .signal import Candidate, Exclusion, KlineDescription, StockPoolResult


def dataclass_to_dict(value: Any) -> Any:
    return asdict(value)
