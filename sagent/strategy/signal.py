"""信号检测模块：纯数学信号检测和候选股筛选。

从 technical.py 拆分而来，包含：
- _check_candidate_conditions: 检查候选股条件
- check_signal_from_closes: 回测信号检测（绝对索引版）
- technical_candidates / technical_candidates_from_bars_map: 批量扫描
- filter_stock_pool: 股票池过滤
"""

from __future__ import annotations

from statistics import mean
from typing import Protocol

from ..models import Candidate, DailyBar, Exclusion, StockInfo, StockPoolResult
from .params import SignalParams

# 模块级默认参数
_signal_params = SignalParams()


def _check_candidate_conditions(
    closes: list[float],
    sp: SignalParams | None = None,
) -> tuple[dict, list[str]] | None:
    """纯计算：检查候选股条件。返回 (metrics, reasons) 或 None。

    提取为纯函数，方便预过滤和向量化优化。
    """
    p = sp or _signal_params
    current = closes[-1]
    ma = mean(closes[-p.ma_window :])
    recent_60 = closes[-p.rise_window :]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    pullback = (high_60 - min(closes[-p.pullback_window :])) / max(
        high_60 - low_60, 0.01
    )
    recent_rebound = all(
        closes[-1 - i] > closes[-2 - i] for i in range(p.rebound_days - 1)
    )
    breakout = current > max(closes[-p.breakout_window : -1])

    # 快速失败：先检查最严格的条件
    if not (
        current > ma
        and rise_60d >= p.min_rise_60d
        and p.pullback_min <= pullback <= p.pullback_max
        and recent_rebound
        and breakout
    ):
        return None

    pullback_low = min(closes[-30:])
    risk = current - pullback_low
    reward = high_60 - current
    risk_reward = reward / risk if risk > 0 else 0.0

    metrics = {
        "above_ma250": True,
        "ma250": round(ma, 2),
        "rise_60d": round(rise_60d, 4),
        "pullback_ratio": round(pullback, 4),
        "recent_rebound": True,
        "breakout": True,
        "risk_reward_ratio": round(risk_reward, 2),
    }
    reasons = [
        "价格位于250日均线之上",
        "60日内涨幅达到主升浪阈值",
        "回撤处于健康区间",
        "突破短期回调趋势",
    ]
    return metrics, reasons


class HasDailyBars(Protocol):
    def daily_bars(self, symbol: str) -> list[DailyBar]: ...


def _ma(values: list[float], window: int) -> float:
    """简单移动平均辅助函数。"""
    return mean(values[-window:])


def filter_stock_pool(
    stocks: list[StockInfo],
    min_avg_amount: float = 100_000_000,
    min_listing_days: int = 120,
) -> StockPoolResult:
    included: list[StockInfo] = []
    excluded: list[Exclusion] = []
    for stock in stocks:
        reason = ""
        if stock.is_st:
            reason = "ST 或异常交易标的"
        elif stock.is_suspended:
            reason = "停牌"
        elif stock.listing_days < min_listing_days:
            reason = "上市时间不足"
        elif stock.avg_amount_20d < min_avg_amount:
            reason = "日均成交额低于阈值"
        if reason:
            excluded.append(Exclusion(symbol=stock.symbol, reason=reason))
        else:
            included.append(stock)
    return StockPoolResult(included=included, excluded=excluded)


def technical_candidates(
    data: HasDailyBars, stocks: list[StockInfo]
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for stock in stocks:
        bars = data.daily_bars(stock.symbol)
        if len(bars) < _signal_params.min_bars:
            continue
        closes = [bar.close for bar in bars]
        result = _check_candidate_conditions(closes)
        if result is None:
            continue
        metrics, reasons = result
        candidates.append(
            Candidate(
                stock.symbol,
                stock.name,
                stock.sector,
                metrics,
                reasons,
                risk_reward_ratio=metrics["risk_reward_ratio"],
            )
        )
    return candidates


def technical_candidates_from_bars_map(
    bars_map: dict[str, list[DailyBar]],
    stocks: list[StockInfo],
) -> list[Candidate]:
    """从预加载的 bars_map 批量扫描，跳过网络请求。"""
    candidates: list[Candidate] = []
    for stock in stocks:
        bars = bars_map.get(stock.symbol, [])
        if len(bars) < _signal_params.min_bars:
            continue
        closes = [bar.close for bar in bars]
        result = _check_candidate_conditions(closes)
        if result is None:
            continue
        metrics, reasons = result
        candidates.append(
            Candidate(
                stock.symbol,
                stock.name,
                stock.sector,
                metrics,
                reasons,
                risk_reward_ratio=metrics["risk_reward_ratio"],
            )
        )
    return candidates


def check_signal_from_closes(
    closes: list[float],
    idx: int,
    sp: SignalParams | None = None,
) -> dict | None:
    """回测信号检测（纯 closes 数组版）。

    与 _check_candidate_conditions 逻辑相同，但接受绝对索引
    而非只看最后 260 日，用于回测循环中按日期逐日扫描。
    """
    p = sp or _signal_params
    if idx < p.min_bars:
        return None
    current = closes[idx]
    ma_val = sum(closes[idx - p.ma_window + 1 : idx + 1]) / p.ma_window

    if current <= ma_val:
        return None

    s60 = idx - (p.rise_window - 1)
    recent_60 = closes[s60 : idx + 1]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    if rise_60d < p.min_rise_60d:
        return None

    s30 = idx - (p.pullback_window - 1)
    recent_30 = closes[s30 : idx + 1]
    pullback = (high_60 - min(recent_30)) / max(high_60 - low_60, 0.01)
    if not (p.pullback_min <= pullback <= p.pullback_max):
        return None

    recent_rebound = all(
        closes[idx - i] > closes[idx - i - 1] for i in range(p.rebound_days - 1)
    )
    breakout = current > max(closes[idx - p.breakout_window + 1 : idx])
    if not (recent_rebound and breakout):
        return None

    return {
        "ma250": round(ma_val, 2),
        "rise_60d": round(rise_60d, 4),
        "pullback_ratio": round(pullback, 4),
        "entry_price": round(current, 2),
        "high_60": round(high_60, 2),
        "low_60": round(low_60, 2),
    }
