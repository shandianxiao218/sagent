from __future__ import annotations

from statistics import mean
from typing import Protocol

from .models import Candidate, DailyBar, Exclusion, StockInfo, StockPoolResult
from .strategy.params import JudgeParams, SignalParams  # noqa: E402


# 模块级默认参数实例（可被测试或调用方覆盖）
_signal_params = SignalParams()
_judge_params = JudgeParams()


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


def simulated_llm_judge(
    signal: dict,
    kline_desc_text: str,
    key_low: float,
    jp: JudgeParams | None = None,
) -> dict:
    """模拟 LLM 形态判断逻辑（规则引擎 v3 — 回测数据驱动）。

    基于 2025-12~2026-05 回测 165 笔交易的关键发现：
    - 涨幅 80%+ 胜率 50-55%（趋势强劲），不应因涨幅高而放弃
    - 涨幅 50-80% 反而胜率仅 34%
    - 真正的杀手是：缩量突破（量比<0.8）+ 深回撤（>55%）
    - 放量（>1.2x）+ 浅回调（<40%）是最强组合

    决策逻辑：
    1. 回撤 >55% → 放弃（趋势破坏）
    2. 量比 <0.7 + 无明确转折点 → 放弃（突破无确认）
    3. 放量 >1.2 + 回调 <42% → 买入（最强信号）
    4. 放量 >1.0 + 回调 <50% + 涨幅 >80% → 买入（强趋势回踩）
    5. 量比 0.7-1.0 → 观察（需确认）
    6. 其他 → 观察
    """
    p = jp or _judge_params
    rise = signal["rise_60d"]
    pullback = signal["pullback_ratio"]

    # 提取量比（从 K 线描述中）
    volume_ratio = 1.0
    if "均量的" in kline_desc_text:
        try:
            idx_vr = kline_desc_text.index("均量的")
            segment = kline_desc_text[idx_vr + 3 : idx_vr + 10]
            volume_ratio = float(segment.split("倍")[0])
        except (ValueError, IndexError):
            pass

    # ── 检测是否有明确结构转折点 ──
    has_turn = "结构转折低点" in kline_desc_text or "更低的低点" in kline_desc_text

    reasons = []
    action = "观察"
    confidence = 0.5

    # ── 1. 硬性拒绝（趋势已破坏） ─────────────────────────
    if pullback > p.pullback_abandon:
        action = "放弃"
        confidence = p.confidence_abandon_deep
        reasons.append(f"回撤{pullback:.0%}过深，趋势可能已破坏")
    # ── 2. 缩量 + 无转折点 → 放弃 ─────────────────────────
    elif volume_ratio < p.volume_abandon and not has_turn:
        action = "放弃"
        confidence = p.confidence_abandon_volume
        reasons.append(f"缩量{volume_ratio:.1f}倍且无结构转折点，突破无确认")
    # ── 3. 最强信号：放量 + 浅回调 → 买入 ─────────────────
    elif volume_ratio >= p.volume_strong and pullback <= p.pullback_strong:
        action = "买入"
        confidence = p.confidence_strong
        reasons.append(f"放量{volume_ratio:.1f}倍确认突破，回调{pullback:.0%}健康")
    # ── 4. 强趋势回踩：涨幅大 + 放量 + 回调适中 → 买入 ────
    elif (
        rise > p.rise_trend
        and volume_ratio >= p.volume_trend
        and pullback <= p.pullback_trend
    ):
        action = "买入"
        confidence = p.confidence_trend
        reasons.append(
            f"强趋势涨幅{rise:.0%}回踩，放量{volume_ratio:.1f}倍，回调{pullback:.0%}"
        )
    # ── 5. 温和涨幅 + 放量 + 浅回调 → 买入 ─────────────────
    elif (
        rise <= p.rise_trend
        and volume_ratio >= p.volume_trend
        and pullback <= p.pullback_gentle
    ):
        action = "买入"
        confidence = p.confidence_gentle
        reasons.append(
            f"涨幅{rise:.0%}温和，放量{volume_ratio:.1f}倍，回调{pullback:.0%}浅"
        )
    # ── 6. 缩量但有明确转折 → 观察（有希望） ───────────────
    elif volume_ratio < p.volume_trend and has_turn:
        action = "观察"
        confidence = p.confidence_observe_turn
        reasons.append(f"缩量{volume_ratio:.1f}倍但有结构转折点，需放量确认")
    # ── 7. 缩量且无转折 → 观察（偏弱） ─────────────────────
    else:
        action = "观察"
        confidence = p.confidence_observe_weak
        reasons.append(
            f"量能{volume_ratio:.1f}倍偏弱，涨幅{rise:.0%}，回撤{pullback:.0%}"
        )

    return {
        "action": action,
        "reason": "；".join(reasons),
        "confidence": confidence,
        "key_low": key_low,
        "volume_ratio": volume_ratio,
    }
