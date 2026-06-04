from __future__ import annotations

from statistics import mean
from typing import Protocol

from .models import Candidate, DailyBar, Exclusion, StockInfo, StockPoolResult


def _check_candidate_conditions(closes: list[float]) -> tuple[dict, list[str]] | None:
    """纯计算：检查候选股条件。返回 (metrics, reasons) 或 None。

    提取为纯函数，方便预过滤和向量化优化。
    """
    current = closes[-1]
    ma250 = mean(closes[-250:])
    recent_60 = closes[-60:]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    pullback = (high_60 - min(closes[-30:])) / max(high_60 - low_60, 0.01)
    recent_rebound = closes[-1] > closes[-2] > closes[-3]
    breakout = closes[-1] > max(closes[-8:-1])

    # 快速失败：先检查最严格的条件
    if not (
        current > ma250
        and rise_60d >= 0.5
        and 0.15 <= pullback <= 0.5
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
        "ma250": round(ma250, 2),
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
        if len(bars) < 260:
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


def check_signal_from_closes(closes: list[float], idx: int) -> dict | None:
    """回测信号检测（纯 closes 数组版）。

    与 _check_candidate_conditions 逻辑相同，但接受绝对索引
    而非只看最后 260 日，用于回测循环中按日期逐日扫描。
    """
    if idx < 260:
        return None
    current = closes[idx]
    ma250 = sum(closes[idx - 249 : idx + 1]) / 250

    if current <= ma250:
        return None

    s60 = idx - 59
    recent_60 = closes[s60 : idx + 1]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    if rise_60d < 0.5:
        return None

    s30 = idx - 29
    recent_30 = closes[s30 : idx + 1]
    pullback = (high_60 - min(recent_30)) / max(high_60 - low_60, 0.01)
    if not (0.15 <= pullback <= 0.5):
        return None

    recent_rebound = closes[idx] > closes[idx - 1] > closes[idx - 2]
    breakout = closes[idx] > max(closes[idx - 7 : idx])
    if not (recent_rebound and breakout):
        return None

    return {
        "ma250": round(ma250, 2),
        "rise_60d": round(rise_60d, 4),
        "pullback_ratio": round(pullback, 4),
        "entry_price": round(current, 2),
        "high_60": round(high_60, 2),
        "low_60": round(low_60, 2),
    }


def simulated_llm_judge(signal: dict, kline_desc_text: str, key_low: float) -> dict:
    """模拟 LLM 形态判断逻辑（规则引擎 v2 — 降低止损率）。

    基于回测统计优化后的关键模式：
    1. 涨幅 >100% → 放弃（涨幅透支）
    2. 涨幅 80-100% + 深回撤 >45% → 放弃
    3. R 值 < 1.5 → 放弃（上行空间不足，止损概率高）
    4. 缩量 <0.8 倍 + 突破不确认 → 观察
    5. 回撤 >50% → 放弃（趋势可能已破坏）
    6. 放量 >1.2 倍 + 涨幅 50-80% + 回调健康 → 买入
    7. 其他 → 观察
    """
    rise = signal["rise_60d"]
    pullback = signal["pullback_ratio"]
    entry = signal["entry_price"]
    high = signal["high_60"]

    # 提取量比（从 K 线描述中）
    volume_ratio = 1.0
    if "均量的" in kline_desc_text:
        try:
            idx_vr = kline_desc_text.index("均量的")
            segment = kline_desc_text[idx_vr + 3 : idx_vr + 10]
            volume_ratio = float(segment.split("倍")[0])
        except (ValueError, IndexError):
            pass

    # 从描述中提取 R 值
    r_ratio = 0.0
    if "盈亏比 R=" in kline_desc_text or "R=2.5" in kline_desc_text:
        try:
            stop_loss = max(entry * 0.90, key_low * 0.97)
            risk = entry - stop_loss
            if risk > 0:
                r_ratio = (high - entry) / risk
        except (ValueError, ZeroDivisionError):
            pass

    at_high = entry >= high * 0.98

    reasons = []
    action = "观察"
    confidence = 0.5

    # ── 硬性拒绝条件（降低止损率） ──────────────────────────
    if rise > 1.2:
        action = "放弃"
        confidence = 0.85
        reasons.append(f"涨幅{rise:.0%}极高，严重透支")
    elif rise > 0.8 and pullback > 0.45:
        action = "放弃"
        confidence = 0.75
        reasons.append(f"涨幅{rise:.0%}偏高且回撤{pullback:.0%}过深")
    elif pullback > 0.55:
        action = "放弃"
        confidence = 0.7
        reasons.append(f"回撤{pullback:.0%}过深，趋势可能已破坏")
    elif r_ratio < 1.5 and r_ratio > 0:
        action = "放弃"
        confidence = 0.65
        reasons.append(f"盈亏比 R={r_ratio:.1f} 过低（<1.5），上行空间不足")
    elif at_high and volume_ratio < 0.8:
        action = "观察"
        confidence = 0.5
        reasons.append("阶段高点附近缩量，突破不确认")
    elif rise <= 0.8 and volume_ratio >= 1.2 and pullback <= 0.40:
        action = "买入"
        confidence = 0.75
        reasons.append(
            f"涨幅{rise:.0%}温和，放量{volume_ratio:.1f}倍确认突破，回调{pullback:.0%}健康"
        )
    elif rise <= 0.65 and pullback <= 0.35 and volume_ratio >= 1.0:
        action = "买入"
        confidence = 0.70
        reasons.append(f"涨幅{rise:.0%}温和，回调{pullback:.0%}浅，形态完整")
    elif entry > 100 and rise > 0.8:
        action = "放弃"
        confidence = 0.7
        reasons.append("高价股涨幅过大，流动性风险")
    else:
        action = "观察"
        confidence = 0.5
        reasons.append(f"涨幅{rise:.0%}，回撤{pullback:.0%}，信号中性")

    return {
        "action": action,
        "reason": "；".join(reasons),
        "confidence": confidence,
        "key_low": key_low,
        "volume_ratio": volume_ratio,
    }
