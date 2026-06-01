from __future__ import annotations

from statistics import mean
from typing import Protocol

from .models import Candidate, DailyBar, Exclusion, StockInfo, StockPoolResult


class HasDailyBars(Protocol):
    def daily_bars(self, symbol: str) -> list[DailyBar]: ...


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


def _ma(values: list[float], window: int) -> float:
    return mean(values[-window:])


def technical_candidates(
    data: HasDailyBars, stocks: list[StockInfo]
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for stock in stocks:
        bars = data.daily_bars(stock.symbol)
        if len(bars) < 260:
            continue
        closes = [bar.close for bar in bars]
        current = closes[-1]
        ma250 = _ma(closes, 250)
        recent_60 = closes[-60:]
        low_60 = min(recent_60)
        high_60 = max(recent_60)
        rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
        pullback = (high_60 - min(closes[-30:])) / max(high_60 - low_60, 0.01)
        recent_rebound = closes[-1] > closes[-2] > closes[-3]
        breakout = closes[-1] > max(closes[-8:-1])
        metrics = {
            "above_ma250": current > ma250,
            "ma250": round(ma250, 2),
            "rise_60d": round(rise_60d, 4),
            "pullback_ratio": round(pullback, 4),
            "recent_rebound": recent_rebound,
            "breakout": breakout,
        }
        # 盈亏比估算：用回调区间最低价近似 key_low
        pullback_low = min(closes[-30:])
        risk = current - pullback_low
        reward = high_60 - current
        risk_reward = reward / risk if risk > 0 else 0.0
        metrics["risk_reward_ratio"] = round(risk_reward, 2)

        reasons: list[str] = []
        if current > ma250:
            reasons.append("价格位于250日均线之上")
        if rise_60d >= 0.5:
            reasons.append("60日内涨幅达到主升浪阈值")
        if 0.15 <= pullback <= 0.5:
            reasons.append("回撤处于健康区间")
        if recent_rebound and breakout:
            reasons.append("突破短期回调趋势")
        if len(reasons) == 4:
            candidates.append(
                Candidate(
                    stock.symbol,
                    stock.name,
                    stock.sector,
                    metrics,
                    reasons,
                    risk_reward_ratio=round(risk_reward, 2),
                )
            )
    return candidates
