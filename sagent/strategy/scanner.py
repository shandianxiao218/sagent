"""批量信号扫描和数据加载。

从 run_backtest_period.py 提取的共享逻辑：
- forward_returns: 前向收益计算
- desc: 统计描述
- scan_signals_from_closes: Phase A 批量信号扫描
- load_and_filter_signals: Phase B 加载完整 bars + 过滤
"""

from __future__ import annotations

from statistics import mean, median, stdev
from typing import Any

from ..models import DailyBar
from .params import ScanParams, SignalParams
from .signal import check_signal_from_closes


def forward_returns(bars: list[DailyBar], signal_idx: int) -> dict:
    """计算信号日后的前向收益和最大回撤。"""
    entry_price = bars[signal_idx].close
    result: dict = {"entry_price": round(entry_price, 2)}
    for w in (5, 10, 20):
        target = signal_idx + w
        if target < len(bars):
            result[f"return_{w}d"] = round(
                (bars[target].close - entry_price) / entry_price, 4
            )
        else:
            result[f"return_{w}d"] = None
    peak = entry_price
    max_dd = 0.0
    end = min(signal_idx + 20, len(bars))
    for i in range(signal_idx + 1, end):
        if bars[i].high > peak:
            peak = bars[i].high
        dd = (peak - bars[i].low) / peak
        if dd > max_dd:
            max_dd = dd
    result["max_drawdown_20d"] = round(max_dd, 4)
    return result


def desc(values: list[float]) -> dict:
    """统计描述：均值、中位数、标准差、胜率等。"""
    if not values:
        return {"count": 0, "mean": None, "median": None, "win_rate": None}
    wins = [v for v in values if v > 0]
    sorted_v = sorted(values)
    n = len(sorted_v)
    return {
        "count": n,
        "mean": round(mean(values), 4),
        "median": round(median(values), 4),
        "std": round(stdev(values), 4) if n >= 2 else 0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "win_rate": round(len(wins) / n, 4),
    }


def scan_signals_from_closes(
    all_closes_map: dict[str, tuple[list[str], list[float]]],
    stocks: list[dict],
    start_date: str,
    end_date: str,
    sp: SignalParams | None = None,
    scanp: ScanParams | None = None,
) -> list[dict]:
    """Phase A: 从预加载的 closes 批量扫描信号。

    Args:
        all_closes_map: {symbol: (dates, closes)}
        stocks: 股票列表 [{code, name, ...}]
        start_date: 扫描起始日期
        end_date: 扫描截止日期
        sp: 信号参数
        scanp: 扫描参数

    Returns:
        命中信号的列表 [{symbol, name, signal_date, check_idx, metrics, closes, dates}]
    """
    _sp = sp or SignalParams()
    _scanp = scanp or ScanParams()
    scan_hits: list[dict] = []
    short_bars = 0

    for stock in stocks:
        symbol = str(stock.get("code", ""))
        name = str(stock.get("name", ""))

        dates, closes = all_closes_map.get(symbol, ([], []))
        if len(closes) < _scanp.min_bars_cache:
            short_bars += 1
            continue

        # 找日期范围
        range_start_idx = range_end_idx = None
        for j in range(len(dates)):
            if dates[j] >= start_date and range_start_idx is None:
                range_start_idx = j
            if dates[j] <= end_date:
                range_end_idx = j
        if range_start_idx is None or range_end_idx is None:
            continue

        scan_start = max(_sp.min_bars, range_start_idx)
        scan_end = min(range_end_idx, len(closes) - _scanp.min_forward)

        for check_idx in range(scan_start, scan_end, _scanp.window_step):
            sig_date = dates[check_idx]
            if sig_date < start_date or sig_date > end_date:
                continue

            metrics = check_signal_from_closes(closes, check_idx, sp=_sp)
            if metrics is not None:
                scan_hits.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "signal_date": sig_date,
                        "check_idx": check_idx,
                        "metrics": metrics,
                        "closes": closes,
                        "dates": dates,
                    }
                )

    return scan_hits


def load_and_filter_signals(
    scan_hits: list[dict],
    bars_map: dict[str, list[DailyBar]],
    judge_fn: Any,
    min_avg_amount: float | None = None,
    amount_window: int | None = None,
) -> tuple[list[dict], int]:
    """Phase B: 为命中信号的股票加载完整 bars，过滤并调用 LLM 判断。

    Args:
        scan_hits: Phase A 的扫描结果
        bars_map: {symbol: [DailyBar]}
        judge_fn: 判断函数 (metrics, kline_text, key_low) -> dict
        min_avg_amount: 最低日均成交额
        amount_window: 成交额统计窗口

    Returns:
        (all_signals, low_amount_count)
    """
    from ..kline import describe_stock

    _scanp = ScanParams()
    _amount = min_avg_amount or _scanp.min_avg_amount
    _window = amount_window or _scanp.amount_window

    all_signals: list[dict] = []
    low_amount_count = 0

    for hit in scan_hits:
        symbol = hit["symbol"]
        bars = bars_map.get(symbol, [])
        if not bars:
            continue
        check_idx = hit["check_idx"]

        # 成交额过滤
        recent_bars = bars[-_window:]
        avg_amount = mean(bar.amount for bar in recent_bars) if recent_bars else 0
        if avg_amount < _amount:
            low_amount_count += 1
            continue

        fwd = forward_returns(bars, check_idx)
        window_bars = bars[: check_idx + 1]
        desc_result = describe_stock(symbol, window_bars)
        llm_result = judge_fn(hit["metrics"], desc_result.text, desc_result.key_low)

        all_signals.append(
            {
                "symbol": symbol,
                "name": hit["name"],
                "signal_date": hit["signal_date"],
                "metrics": hit["metrics"],
                "forward": fwd,
                "kline_description": desc_result.text,
                "key_low": desc_result.key_low,
                "llm_action": llm_result["action"],
                "llm_reason": llm_result["reason"],
                "llm_confidence": llm_result["confidence"],
            }
        )

    return all_signals, low_amount_count
