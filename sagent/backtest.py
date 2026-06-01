"""量化层分层回测。

对量化粗筛和主线验证规则做历史回测，评估候选池质量。
不包含 LLM 判断层，不等同于完整策略收益回测。

分层：
  L1 股票池过滤（ST/停牌/次新/流动性）
  L2 均线过滤（250日均线之上）
  L3 涨幅过滤（60日涨幅 >= 50%）
  L4 回调结构（回撤 15%-50%）
  L5 突破信号（近3日回升 + 突破短期高点）
  L6 主线验证（所属板块为主线/弱主线）
"""

from __future__ import annotations

from collections import Counter
from statistics import mean, median, stdev

from .sector import summarize_sectors, validate_mainline_sectors
from .technical import _ma, filter_stock_pool


def _forward_returns(
    bars: list, entry_idx: int, windows: tuple[int, ...] = (5, 10, 20)
) -> dict[str, float | None]:
    """计算从 entry_idx 开始的 forward return。"""
    entry_price = bars[entry_idx].close
    result: dict[str, float | None] = {}
    for w in windows:
        target_idx = entry_idx + w
        if target_idx < len(bars):
            result[f"{w}d"] = round(
                (bars[target_idx].close - entry_price) / entry_price, 4
            )
        else:
            result[f"{w}d"] = None
    return result


def _max_drawdown(bars: list, entry_idx: int, horizon: int = 20) -> float | None:
    """计算买入后 horizon 天内的最大回撤。"""
    entry_price = bars[entry_idx].close
    end = min(entry_idx + horizon, len(bars))
    if end <= entry_idx + 1:
        return None
    peak = entry_price
    max_dd = 0.0
    for i in range(entry_idx + 1, end):
        if bars[i].high > peak:
            peak = bars[i].high
        dd = (peak - bars[i].low) / peak
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 4)


def _describe_distribution(values: list[float]) -> dict:
    """统计分布摘要。"""
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "win_rate": None,
        }
    wins = [v for v in values if v > 0]
    return {
        "count": len(values),
        "mean": round(mean(values), 4),
        "median": round(median(values), 4),
        "std": round(stdev(values), 4) if len(values) >= 2 else None,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "win_rate": round(len(wins) / len(values), 4) if values else None,
    }


def run_layered_backtest(data, start: str = "", end: str = "") -> dict:
    """执行量化层分层回测。

    Parameters
    ----------
    data : 数据源（需提供 stocks(), daily_bars(), sector_snapshots()）
    start, end : 回测区间（留空则使用全部数据）

    Returns
    -------
    dict 分层统计结果
    """
    all_stocks = data.stocks()

    # ─── L1 股票池过滤 ──────────────────────────────────────────
    pool = filter_stock_pool(all_stocks)
    l1_included = len(pool.included)
    l1_excluded = len(pool.excluded)
    l1_reasons = Counter(e.reason for e in pool.excluded)

    # ─── L2-L5 逐层筛选 ────────────────────────────────────────
    l2_ma_pass: list[dict] = []  # 均线之上
    l3_rise_pass: list[dict] = []  # 涨幅达标
    l4_pullback_pass: list[dict] = []  # 回调结构
    l5_breakout_pass: list[dict] = []  # 突破信号

    for stock in pool.included:
        bars = data.daily_bars(stock.symbol)
        if len(bars) < 260:
            continue
        closes = [bar.close for bar in bars]
        current = closes[-1]
        ma250 = _ma(closes, 250)

        info: dict = {
            "symbol": stock.symbol,
            "name": stock.name,
            "sector": stock.sector,
            "close": current,
            "ma250": round(ma250, 2),
        }

        # L2
        if current <= ma250:
            continue
        l2_ma_pass.append(info)

        # L3
        recent_60 = closes[-60:]
        low_60 = min(recent_60)
        high_60 = max(recent_60)
        rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
        info["rise_60d"] = round(rise_60d, 4)

        if rise_60d < 0.5:
            continue
        l3_rise_pass.append(info)

        # L4
        pullback = (high_60 - min(closes[-30:])) / max(high_60 - low_60, 0.01)
        info["pullback_ratio"] = round(pullback, 4)

        if not (0.15 <= pullback <= 0.5):
            continue
        l4_pullback_pass.append(info)

        # L5
        recent_rebound = closes[-1] > closes[-2] > closes[-3]
        breakout = closes[-1] > max(closes[-8:-1])
        info["recent_rebound"] = recent_rebound
        info["breakout"] = breakout

        if recent_rebound and breakout:
            l5_breakout_pass.append(info)

    # ─── L6 主线验证 ────────────────────────────────────────────
    validations = validate_mainline_sectors(summarize_sectors(data))
    mainline_stocks: list[dict] = []
    non_mainline_stocks: list[dict] = []
    for item in l5_breakout_pass:
        v = validations.get(item["sector"])
        if v and v.level in ("强主线", "弱主线"):
            item["mainline_level"] = v.level
            mainline_stocks.append(item)
        else:
            item["mainline_level"] = "非主线"
            non_mainline_stocks.append(item)

    # ─── Forward performance ────────────────────────────────────
    forward_data: list[dict] = []
    for item in mainline_stocks + non_mainline_stocks:
        bars = data.daily_bars(item["symbol"])
        if len(bars) < 6:
            continue
        entry_idx = len(bars) - 1  # 最后一根 bar 为信号日
        # 用前一根 bar 的 close 作为模拟买入价（信号次日开盘）
        if entry_idx < 1:
            continue
        fr = _forward_returns(bars, entry_idx - 1, windows=(5, 10, 20))
        mdd = _max_drawdown(bars, entry_idx - 1, horizon=20)
        item["forward"] = fr
        item["max_drawdown_20d"] = mdd
        forward_data.append(item)

    # ─── 汇总统计 ───────────────────────────────────────────────
    # 全候选 forward
    all_5d = [d["forward"]["5d"] for d in forward_data if d["forward"]["5d"] is not None]
    all_10d = [d["forward"]["10d"] for d in forward_data if d["forward"]["10d"] is not None]
    all_20d = [d["forward"]["20d"] for d in forward_data if d["forward"]["20d"] is not None]
    all_mdd = [d["max_drawdown_20d"] for d in forward_data if d["max_drawdown_20d"] is not None]

    # 主线 vs 非主线
    mainline_forward = [d for d in forward_data if d.get("mainline_level") in ("强主线", "弱主线")]
    non_mainline_forward = [d for d in forward_data if d.get("mainline_level") == "非主线"]

    ml_5d = [d["forward"]["5d"] for d in mainline_forward if d["forward"]["5d"] is not None]
    nml_5d = [d["forward"]["5d"] for d in non_mainline_forward if d["forward"]["5d"] is not None]

    # ─── 阈值敏感度 ─────────────────────────────────────────────
    sensitivity = _threshold_sensitivity(data, pool.included)

    return {
        "scope": "量化粗筛与主线验证分层回测，不包含 LLM 判断层",
        "disclaimer": "本回测不包含 LLM 判断层，不等同于完整策略收益回测。仅用于评估量化候选池质量。",
        "layers": {
            "L1_stock_pool": {
                "input": len(all_stocks),
                "passed": l1_included,
                "excluded": l1_excluded,
                "pass_rate": round(l1_included / max(len(all_stocks), 1), 4),
                "exclusion_reasons": dict(l1_reasons),
            },
            "L2_above_ma250": {
                "input": l1_included,
                "passed": len(l2_ma_pass),
                "pass_rate": round(len(l2_ma_pass) / max(l1_included, 1), 4),
            },
            "L3_rise_60d": {
                "input": len(l2_ma_pass),
                "passed": len(l3_rise_pass),
                "pass_rate": round(len(l3_rise_pass) / max(len(l2_ma_pass), 1), 4),
            },
            "L4_pullback": {
                "input": len(l3_rise_pass),
                "passed": len(l4_pullback_pass),
                "pass_rate": round(len(l4_pullback_pass) / max(len(l3_rise_pass), 1), 4),
            },
            "L5_breakout": {
                "input": len(l4_pullback_pass),
                "passed": len(l5_breakout_pass),
                "pass_rate": round(len(l5_breakout_pass) / max(len(l4_pullback_pass), 1), 4),
            },
            "L6_mainline": {
                "input": len(l5_breakout_pass),
                "mainline": len(mainline_stocks),
                "non_mainline": len(non_mainline_stocks),
                "mainline_rate": round(
                    len(mainline_stocks) / max(len(l5_breakout_pass), 1), 4
                ),
            },
        },
        "forward_performance": {
            "all": {
                "5d": _describe_distribution(all_5d),
                "10d": _describe_distribution(all_10d),
                "20d": _describe_distribution(all_20d),
                "max_drawdown_20d": _describe_distribution(all_mdd),
            },
            "mainline": {
                "count": len(mainline_forward),
                "5d": _describe_distribution(ml_5d),
            },
            "non_mainline": {
                "count": len(non_mainline_forward),
                "5d": _describe_distribution(nml_5d),
            },
        },
        "sector_distribution": dict(Counter(d["sector"] for d in forward_data)),
        "sensitivity": sensitivity,
        "threshold_notes": (
            "sensitivity 字段展示不同阈值组合下的候选股数量变化，"
            "可用于调整粗筛阈值。当前默认：涨幅>=50%, 回撤15%-50%。"
        ),
    }


def _threshold_sensitivity(data, stocks: list) -> dict:
    """阈值敏感度分析：关键阈值变化对候选数量的影响。"""
    results: dict[str, list[dict]] = {}

    # 涨幅阈值敏感度
    rise_thresholds = [0.3, 0.4, 0.5, 0.6, 0.8]
    rise_sensitivity: list[dict] = []
    for threshold in rise_thresholds:
        count = 0
        for stock in stocks:
            bars = data.daily_bars(stock.symbol)
            if len(bars) < 260:
                continue
            closes = [bar.close for bar in bars]
            if closes[-1] <= _ma(closes, 250):
                continue
            recent_60 = closes[-60:]
            rise = (max(recent_60) - min(recent_60)) / min(recent_60) if min(recent_60) else 0
            if rise >= threshold:
                count += 1
        rise_sensitivity.append({"threshold": f"rise>={int(threshold * 100)}%", "candidates": count})
    results["rise_60d"] = rise_sensitivity

    # 回调区间敏感度
    pullback_ranges = [(0.1, 0.6), (0.15, 0.5), (0.2, 0.5), (0.15, 0.4)]
    pullback_sensitivity: list[dict] = []
    for lo, hi in pullback_ranges:
        count = 0
        for stock in stocks:
            bars = data.daily_bars(stock.symbol)
            if len(bars) < 260:
                continue
            closes = [bar.close for bar in bars]
            if closes[-1] <= _ma(closes, 250):
                continue
            recent_60 = closes[-60:]
            high_60 = max(recent_60)
            low_60 = min(recent_60)
            rise = (high_60 - low_60) / low_60 if low_60 else 0
            if rise < 0.5:
                continue
            pullback = (high_60 - min(closes[-30:])) / max(high_60 - low_60, 0.01)
            if lo <= pullback <= hi:
                count += 1
        pullback_sensitivity.append({
            "threshold": f"pullback {int(lo * 100)}%-{int(hi * 100)}%",
            "candidates": count,
        })
    results["pullback_range"] = pullback_sensitivity

    return results
