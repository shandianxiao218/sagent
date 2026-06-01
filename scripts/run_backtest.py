#!/usr/bin/env python3
"""真实数据滑动窗口历史回测。

流程：
  1. 从 mootdx 获取 A 股列表
  2. 随机采样 N 只股票，获取 350 日 K 线
  3. 在多个历史时间点（每 5 个交易日一个窗口）执行量化粗筛
  4. 对每个信号点计算 5d/10d/20d forward return 和最大回撤
  5. 按时间汇总统计，输出 JSON 结果

不包含 LLM 判断层，不等同于完整策略收益回测。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, stdev

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.models import DailyBar
from sagent.technical import _ma


# ─── 数据获取 ─────────────────────────────────────────────────


def fetch_all_stocks() -> list[dict]:
    """获取 A 股列表。"""
    import akshare as ak

    df = ak.stock_info_a_code_name()
    return df.to_dict("records")


def fetch_bars(symbol: str, offset: int = 350) -> list[DailyBar]:
    """从 mootdx 获取 K 线。"""
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    frame = client.bars(symbol=symbol, category=4, offset=offset)
    if frame is None or frame.empty:
        return []
    bars = []
    for idx, row in frame.iterrows():
        date_str = str(row.get("datetime", idx))
        bars.append(
            DailyBar(
                symbol=symbol,
                date=date_str[:10],
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("vol", 0)),
                amount=float(row.get("amount", 0)),
            )
        )
    return bars


# ─── 信号检测 ─────────────────────────────────────────────────


def check_signal(bars: list[DailyBar], idx: int) -> dict | None:
    """在 bars[idx] 位置检查是否满足量化粗筛条件 (L1-L5)。

    返回 metrics dict 或 None。
    """
    if idx < 260:
        return None

    window = bars[: idx + 1]
    closes = [b.close for b in window]

    current = closes[-1]
    ma250 = _ma(closes, 250)

    # L2: 价格在 250 日均线之上
    if current <= ma250:
        return None

    # L3: 60 日内涨幅 >= 50%
    recent_60 = closes[-60:]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    if rise_60d < 0.5:
        return None

    # L4: 回撤处于 15%-50%
    recent_30_closes = closes[-30:]
    pullback = (high_60 - min(recent_30_closes)) / max(high_60 - low_60, 0.01)
    if not (0.15 <= pullback <= 0.5):
        return None

    # L5: 突破信号（近 3 日回升 + 突破短期高点）
    if len(closes) < 8:
        return None
    recent_rebound = closes[-1] > closes[-2] > closes[-3]
    breakout = closes[-1] > max(closes[-8:-1])
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


def forward_returns(
    bars: list[DailyBar], signal_idx: int, windows: tuple[int, ...] = (5, 10, 20)
) -> dict:
    """计算信号后的 forward return 和最大回撤。"""
    entry_price = bars[signal_idx].close
    result: dict = {"entry_price": round(entry_price, 2)}

    for w in windows:
        target = signal_idx + w
        if target < len(bars):
            ret = (bars[target].close - entry_price) / entry_price
            result[f"return_{w}d"] = round(ret, 4)
        else:
            result[f"return_{w}d"] = None

    # 20 日内最大回撤
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


# ─── 统计工具 ─────────────────────────────────────────────────


def describe(values: list[float]) -> dict:
    """分布摘要统计。"""
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "win_rate": None,
            "p25": None,
            "p75": None,
        }
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
        "p25": round(sorted_v[n // 4], 4),
        "p75": round(sorted_v[3 * n // 4], 4),
    }


# ─── 主回测逻辑 ──────────────────────────────────────────────


def run_backtest(
    sample_size: int = 300,
    seed: int = 42,
    window_step: int = 5,
    min_forward: int = 20,
    top_n_details: int = 20,
) -> dict:
    """执行滑动窗口回测。"""
    print("=== sagent 真实数据历史回测 ===", file=sys.stderr)
    print(
        f"参数: 采样 {sample_size} 只, 窗口步长 {window_step} 日, 最少 forward {min_forward} 日",
        file=sys.stderr,
    )

    # 1. 获取股票列表
    print("\n[1/4] 获取 A 股列表...", file=sys.stderr)
    all_stocks = fetch_all_stocks()
    valid_prefixes = ("000", "001", "002", "300", "600", "601", "603")
    all_stocks = [
        s for s in all_stocks if str(s.get("code", "")).startswith(valid_prefixes)
    ]
    print(f"  共 {len(all_stocks)} 只主板股票", file=sys.stderr)

    # 2. 采样
    random.seed(seed)
    sample = random.sample(all_stocks, min(sample_size, len(all_stocks)))
    print(f"  随机采样 {len(sample)} 只", file=sys.stderr)

    # 3. 获取 K 线并检测信号
    print("\n[2/4] 获取 K 线并检测信号...", file=sys.stderr)
    all_signals: list[dict] = []
    fetch_errors = 0
    short_bars = 0

    for i, stock in enumerate(sample):
        symbol = str(stock.get("code", ""))
        name = str(stock.get("name", ""))

        if (i + 1) % 30 == 0:
            print(
                f"  进度: {i + 1}/{len(sample)}, 已找到 {len(all_signals)} 个信号",
                file=sys.stderr,
            )

        try:
            bars = fetch_bars(symbol, offset=350)
        except Exception:
            fetch_errors += 1
            continue

        if len(bars) < 300:
            short_bars += 1
            continue

        # 滑动窗口：从第 270 根 K 线开始，留出 forward 空间
        last_checkable = len(bars) - min_forward
        for check_idx in range(270, last_checkable, window_step):
            metrics = check_signal(bars, check_idx)
            if metrics is None:
                continue

            fwd = forward_returns(bars, check_idx)
            all_signals.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "signal_date": bars[check_idx].date,
                    "signal_idx": check_idx,
                    "metrics": metrics,
                    "forward": fwd,
                }
            )

    print(f"\n  完成: 获取错误 {fetch_errors}, K线不足 {short_bars}", file=sys.stderr)
    print(f"  共找到 {len(all_signals)} 个信号点", file=sys.stderr)

    if not all_signals:
        print("  未找到任何信号，回测结束", file=sys.stderr)
        return {"error": "未找到任何信号点", "total_signals": 0}

    # 4. 统计分析
    print("\n[3/4] 统计分析...", file=sys.stderr)

    # 按月份分组
    by_month: dict[str, list[dict]] = defaultdict(list)
    for sig in all_signals:
        month_key = sig["signal_date"][:7]  # "YYYY-MM"
        by_month[month_key].append(sig)

    # 总体 forward return
    all_5d = [
        s["forward"]["return_5d"]
        for s in all_signals
        if s["forward"]["return_5d"] is not None
    ]
    all_10d = [
        s["forward"]["return_10d"]
        for s in all_signals
        if s["forward"]["return_10d"] is not None
    ]
    all_20d = [
        s["forward"]["return_20d"]
        for s in all_signals
        if s["forward"]["return_20d"] is not None
    ]
    all_mdd = [
        s["forward"]["max_drawdown_20d"]
        for s in all_signals
        if s["forward"]["max_drawdown_20d"] is not None
    ]

    # 止损场景：20 日亏损 >= 5%
    stop_loss_hits = [
        s
        for s in all_signals
        if s["forward"].get("return_20d") is not None
        and s["forward"]["return_20d"] <= -0.05
    ]
    # 止盈场景：20 日收益 >= 10%且回撤 < 12%
    take_profit_hits = [
        s
        for s in all_signals
        if s["forward"].get("return_20d") is not None
        and s["forward"]["return_20d"] >= 0.10
        and s["forward"].get("max_drawdown_20d", 1) < 0.12
    ]

    # 按月份的胜率
    monthly_stats = {}
    for month, signals in sorted(by_month.items()):
        r5 = [
            s["forward"]["return_5d"]
            for s in signals
            if s["forward"]["return_5d"] is not None
        ]
        r20 = [
            s["forward"]["return_20d"]
            for s in signals
            if s["forward"]["return_20d"] is not None
        ]
        monthly_stats[month] = {
            "count": len(signals),
            "win_rate_5d": round(sum(1 for v in r5 if v > 0) / max(len(r5), 1), 4),
            "mean_return_5d": round(mean(r5), 4) if r5 else None,
            "win_rate_20d": round(sum(1 for v in r20 if v > 0) / max(len(r20), 1), 4),
            "mean_return_20d": round(mean(r20), 4) if r20 else None,
        }

    # 涨幅分段分析：信号时的涨幅大小是否影响后续收益
    rise_buckets = {"50%-80%": [], "80%-120%": [], ">120%": []}
    for sig in all_signals:
        rise = sig["metrics"]["rise_60d"]
        r20 = sig["forward"].get("return_20d")
        if r20 is None:
            continue
        if 0.5 <= rise < 0.8:
            rise_buckets["50%-80%"].append(r20)
        elif 0.8 <= rise < 1.2:
            rise_buckets["80%-120%"].append(r20)
        else:
            rise_buckets[">120%"].append(r20)

    rise_analysis = {}
    for bucket, values in rise_buckets.items():
        rise_analysis[bucket] = {
            "count": len(values),
            **describe(values),
        }

    # 回撤分段分析
    pullback_buckets = {"15%-25%": [], "25%-35%": [], "35%-50%": []}
    for sig in all_signals:
        pb = sig["metrics"]["pullback_ratio"]
        r20 = sig["forward"].get("return_20d")
        if r20 is None:
            continue
        if 0.15 <= pb < 0.25:
            pullback_buckets["15%-25%"].append(r20)
        elif 0.25 <= pb < 0.35:
            pullback_buckets["25%-35%"].append(r20)
        else:
            pullback_buckets["35%-50%"].append(r20)

    pullback_analysis = {}
    for bucket, values in pullback_buckets.items():
        pullback_analysis[bucket] = {
            "count": len(values),
            **describe(values),
        }

    # 5. Top N 详情
    print("\n[4/4] 提取 Top 详情...", file=sys.stderr)
    sorted_by_return = sorted(
        [s for s in all_signals if s["forward"].get("return_20d") is not None],
        key=lambda x: x["forward"]["return_20d"],
        reverse=True,
    )
    top_winners = sorted_by_return[:top_n_details]
    top_losers = sorted_by_return[-top_n_details:]

    # 信号最多的股票
    signal_counter = Counter(s["symbol"] for s in all_signals)
    most_signals = signal_counter.most_common(10)

    # 6. 组装结果
    result = {
        "meta": {
            "scope": "量化粗筛滑动窗口回测 (L1-L5)，不包含 LLM 判断层和主线验证层",
            "disclaimer": "本回测不构成投资建议。仅评估量化候选池的历史表现，不等同于完整策略收益。",
            "parameters": {
                "sample_size": sample_size,
                "seed": seed,
                "window_step": window_step,
                "min_forward_days": min_forward,
                "total_stocks_scanned": len(sample),
                "fetch_errors": fetch_errors,
                "short_bars": short_bars,
            },
        },
        "summary": {
            "total_signals": len(all_signals),
            "date_range": {
                "earliest": min(s["signal_date"] for s in all_signals),
                "latest": max(s["signal_date"] for s in all_signals),
            },
            "unique_stocks_with_signal": len({s["symbol"] for s in all_signals}),
            "forward_returns": {
                "5d": describe(all_5d),
                "10d": describe(all_10d),
                "20d": describe(all_20d),
            },
            "max_drawdown_20d": describe(all_mdd),
            "stop_loss_rate": round(len(stop_loss_hits) / max(len(all_20d), 1), 4),
            "take_profit_rate": round(len(take_profit_hits) / max(len(all_20d), 1), 4),
        },
        "factor_analysis": {
            "by_rise_60d": rise_analysis,
            "by_pullback_ratio": pullback_analysis,
        },
        "monthly_breakdown": monthly_stats,
        "top_winners": [
            {
                "symbol": s["symbol"],
                "name": s["name"],
                "date": s["signal_date"],
                "entry": s["forward"]["entry_price"],
                "return_20d": s["forward"]["return_20d"],
                "max_dd": s["forward"]["max_drawdown_20d"],
                "rise_60d": s["metrics"]["rise_60d"],
                "pullback": s["metrics"]["pullback_ratio"],
            }
            for s in top_winners
        ],
        "top_losers": [
            {
                "symbol": s["symbol"],
                "name": s["name"],
                "date": s["signal_date"],
                "entry": s["forward"]["entry_price"],
                "return_20d": s["forward"]["return_20d"],
                "max_dd": s["forward"]["max_drawdown_20d"],
                "rise_60d": s["metrics"]["rise_60d"],
                "pullback": s["metrics"]["pullback_ratio"],
            }
            for s in top_losers
        ],
        "most_frequent_signals": [
            {
                "symbol": sym,
                "name": next(s["name"] for s in all_signals if s["symbol"] == sym),
                "count": cnt,
            }
            for sym, cnt in most_signals
        ],
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 真实数据历史回测")
    parser.add_argument(
        "--sample", type=int, default=300, help="采样股票数（默认 300）"
    )
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--step", type=int, default=5, help="滑动窗口步长（交易日）")
    parser.add_argument("--output", default=None, help="输出文件路径（默认 stdout）")
    parser.add_argument("--top", type=int, default=20, help="Top N 详情数量")
    args = parser.parse_args()

    result = run_backtest(
        sample_size=args.sample,
        seed=args.seed,
        window_step=args.step,
        top_n_details=args.top,
    )

    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"\n结果已写入 {args.output}", file=sys.stderr)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
