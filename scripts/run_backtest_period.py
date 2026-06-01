#!/usr/bin/env python3
"""定向时间区间回测：2025-10-01 ~ 2026-05-31。

特征：
  - 大样本（1500只）覆盖完整区间
  - 按月汇总信号数量和收益
  - 自动执行 LLM 形态判断（规则引擎模拟）
  - 对比纯量化 vs LLM过滤 后的收益

不包含真实 LLM API 调用，LLM 判断用规则引擎模拟。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.kline import describe_stock
from sagent.models import DailyBar
from sagent.technical import _ma

# ─── 行业归属获取（简化版 L6）─────────────────────────────────
# 注意：回测中的 L6 是简化版，仅获取行业归属并做集中度统计，
# 不执行完整的主线验证（需要实时板块成交额/涨幅/涨停扩散数据）。


def get_stock_industry(symbol: str) -> str:
    """获取股票所属申万行业（通过 AKShare 东方财富接口）。

    网络获取可能失败，fallback 到 "未知"。
    """
    import akshare as ak

    try:
        df = ak.stock_individual_info_em(symbol=symbol)
        for _, row in df.iterrows():
            if row.get("item") == "行业":
                return str(row.get("value", "未知"))
    except Exception:
        pass
    return "未知"


# ─── 数据获取 ─────────────────────────────────────────────────


def fetch_all_stocks() -> list[dict]:
    import akshare as ak

    df = ak.stock_info_a_code_name()
    return df.to_dict("records")


def fetch_bars(symbol: str, offset: int = 370) -> list[DailyBar]:
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
    if idx < 260:
        return None
    window = bars[: idx + 1]
    closes = [b.close for b in window]
    current = closes[-1]
    ma250 = _ma(closes, 250)

    if current <= ma250:
        return None

    recent_60 = closes[-60:]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    if rise_60d < 0.5:
        return None

    pullback = (high_60 - min(closes[-30:])) / max(high_60 - low_60, 0.01)
    if not (0.15 <= pullback <= 0.5):
        return None

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


def forward_returns(bars: list[DailyBar], signal_idx: int) -> dict:
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


# ─── LLM 模拟判断（规则引擎）──────────────────────────────


def simulated_llm_judge(signal: dict, kline_desc_text: str, key_low: float) -> dict:
    """模拟 LLM 形态判断逻辑。

    基于方案A回测中 LLM 实际判断的关键模式：
    1. ST 股 → 放弃
    2. 涨幅 >100% → 放弃（涨幅透支）
    3. 涨幅 80-100% + 深回撤 >45% → 放弃
    4. 缩量 <0.85 倍 + 阶段高点附近 → 观察
    5. 放量 >1.2 倍 + 涨幅 50-80% + 回调健康 → 买入
    6. 其他 → 观察
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

    at_high = entry >= high * 0.98  # 在阶段高点附近

    reasons = []
    action = "观察"
    confidence = 0.5

    # 规则1: 涨幅极端过高
    if rise > 1.2:
        action = "放弃"
        confidence = 0.85
        reasons.append(f"涨幅{rise:.0%}极高，严重透支")
    # 规则2: 涨幅偏高 + 深回撤
    elif rise > 0.8 and pullback > 0.45:
        action = "放弃"
        confidence = 0.7
        reasons.append(f"涨幅{rise:.0%}偏高且回撤{pullback:.0%}过深")
    # 规则3: 阶段高点 + 缩量
    elif at_high and volume_ratio < 0.9:
        action = "观察"
        confidence = 0.5
        reasons.append("阶段高点附近缩量突破不确认")
    # 规则4: 温和涨幅 + 放量确认 + 回调适中
    elif rise <= 0.8 and volume_ratio >= 1.2 and pullback <= 0.45:
        action = "买入"
        confidence = 0.7
        reasons.append(
            f"涨幅{rise:.0%}温和，放量{volume_ratio:.1f}倍确认突破，回调{pullback:.0%}健康"
        )
    # 规则5: 温和涨幅 + 中等量 + 浅回调
    elif rise <= 0.65 and pullback <= 0.35:
        action = "买入"
        confidence = 0.65
        reasons.append(f"涨幅{rise:.0%}温和，回调{pullback:.0%}浅，形态完整")
    # 规则6: 高价股 + 涨幅大
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


# ─── 统计工具 ─────────────────────────────────────────────────


def desc(values: list[float]) -> dict:
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


# ─── 主回测 ──────────────────────────────────────────────────


def run_backtest(
    start_date: str = "2025-10-01",
    end_date: str = "2026-05-31",
    sample_size: int = 1500,
    seed: int = 42,
    window_step: int = 3,
    min_forward: int = 20,
    min_avg_amount: float = 100_000_000,
) -> dict:
    print(f"=== 定向时间区间回测: {start_date} ~ {end_date} ===", file=sys.stderr)
    print(
        f"参数: 采样{sample_size}只, 步长{window_step}日, 最低日均成交额{min_avg_amount / 1e8:.1f}亿",
        file=sys.stderr,
    )

    # 1. 获取股票列表
    print("\n[1/5] 获取A股列表...", file=sys.stderr)
    all_stocks = fetch_all_stocks()
    valid_prefixes = ("000", "001", "002", "300", "600", "601", "603")
    all_stocks = [
        s for s in all_stocks if str(s.get("code", "")).startswith(valid_prefixes)
    ]
    print(f"  主板共 {len(all_stocks)} 只", file=sys.stderr)

    random.seed(seed)
    sample = random.sample(all_stocks, min(sample_size, len(all_stocks)))
    print(f"  采样 {len(sample)} 只", file=sys.stderr)

    # 2. 获取K线 + 检测信号
    print("\n[2/5] 获取K线并检测信号...", file=sys.stderr)
    all_signals: list[dict] = []
    fetch_errors = 0
    short_bars = 0
    low_amount_count = 0

    for i, stock in enumerate(sample):
        symbol = str(stock.get("code", ""))
        name = str(stock.get("name", ""))

        if (i + 1) % 100 == 0:
            print(
                f"  进度: {i + 1}/{len(sample)}, 信号: {len(all_signals)}",
                file=sys.stderr,
            )

        try:
            bars = fetch_bars(symbol, offset=370)
        except Exception:
            fetch_errors += 1
            continue

        if len(bars) < 300:
            short_bars += 1
            continue

        # 成交额过滤：最近20日日均成交额低于阈值则跳过
        recent_bars = bars[-20:]
        avg_amount = mean(bar.amount for bar in recent_bars) if recent_bars else 0
        if avg_amount < min_avg_amount:
            low_amount_count += 1
            continue

        # 找到日期范围内的索引
        range_start_idx = None
        range_end_idx = None
        for j, bar in enumerate(bars):
            if bar.date >= start_date and range_start_idx is None:
                range_start_idx = j
            if bar.date <= end_date:
                range_end_idx = j

        if range_start_idx is None or range_end_idx is None:
            continue

        # 需要至少260根前置K线，所以从 max(260, range_start_idx) 开始
        scan_start = max(260, range_start_idx)
        scan_end = min(range_end_idx, len(bars) - min_forward)

        for check_idx in range(scan_start, scan_end, window_step):
            sig_date = bars[check_idx].date
            if sig_date < start_date or sig_date > end_date:
                continue

            metrics = check_signal(bars, check_idx)
            if metrics is None:
                continue

            fwd = forward_returns(bars, check_idx)

            # K线描述（用于LLM模拟判断）
            window_bars = bars[: check_idx + 1]
            desc_result = describe_stock(symbol, window_bars)

            # LLM模拟判断
            llm_result = simulated_llm_judge(
                metrics, desc_result.text, desc_result.key_low
            )

            all_signals.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "signal_date": sig_date,
                    "metrics": metrics,
                    "forward": fwd,
                    "kline_description": desc_result.text,
                    "key_low": desc_result.key_low,
                    "llm_action": llm_result["action"],
                    "llm_reason": llm_result["reason"],
                    "llm_confidence": llm_result["confidence"],
                }
            )

    print(
        f"\n  完成: 错误{fetch_errors}, K线不足{short_bars}, 成交额不足{low_amount_count}",
        file=sys.stderr,
    )
    print(f"  总信号: {len(all_signals)}", file=sys.stderr)

    if not all_signals:
        return {"error": "未找到信号", "total_signals": 0}

    # 3. 获取行业归属（简化版 L6）
    print("\n[3/7] 获取行业归属（简化版 L6）...", file=sys.stderr)
    unique_symbols = list({s["symbol"] for s in all_signals})
    industry_cache: dict[str, str] = {}
    for idx_us, sym in enumerate(unique_symbols):
        if (idx_us + 1) % 20 == 0:
            print(f"  行业查询: {idx_us + 1}/{len(unique_symbols)}", file=sys.stderr)
        industry_cache[sym] = get_stock_industry(sym)
    print(
        f"  完成: {len(industry_cache)} 只股票, "
        f"{sum(1 for v in industry_cache.values() if v == '未知')} 只未获取到行业",
        file=sys.stderr,
    )

    # 将行业归属写入每个信号
    for s in all_signals:
        s["industry"] = industry_cache.get(s["symbol"], "未知")

    # 4. 统计分析
    print("\n[4/7] 统计分析...", file=sys.stderr)

    # 定义好/差信号
    def is_good(s):
        r20 = s["forward"].get("return_20d")
        mdd = s["forward"].get("max_drawdown_20d", 1)
        return r20 is not None and r20 > 0 and mdd < 0.15

    def is_bad(s):
        r20 = s["forward"].get("return_20d")
        return r20 is not None and r20 <= -0.05

    has_fwd = [s for s in all_signals if s["forward"].get("return_20d") is not None]

    # 纯量化 vs LLM过滤
    llm_buy = [s for s in has_fwd if s["llm_action"] == "买入"]
    llm_observe = [s for s in has_fwd if s["llm_action"] == "观察"]
    llm_reject = [s for s in has_fwd if s["llm_action"] == "放弃"]

    # 按月分组（含板块维度）
    by_month: dict[str, dict] = {}
    monthly_signals = defaultdict(list)
    for s in has_fwd:
        month = s["signal_date"][:7]
        monthly_signals[month].append(s)

    for month in sorted(monthly_signals.keys()):
        group = monthly_signals[month]
        r20_all = [s["forward"]["return_20d"] for s in group]
        r20_buy = [
            s["forward"]["return_20d"] for s in group if s["llm_action"] == "买入"
        ]
        wr_all = round(sum(1 for v in r20_all if v > 0) / max(len(r20_all), 1), 4)
        wr_buy = round(sum(1 for v in r20_buy if v > 0) / max(len(r20_buy), 1), 4)
        sl_all = round(sum(1 for v in r20_all if v <= -0.05) / max(len(r20_all), 1), 4)

        # 板块维度：该月按行业分组
        month_sectors: dict[str, int] = defaultdict(int)
        for s in group:
            month_sectors[s.get("industry", "未知")] += 1
        # 按数量降序取前 5
        top_sectors = sorted(month_sectors.items(), key=lambda x: -x[1])[:5]

        by_month[month] = {
            "total": len(group),
            "quant_mean_20d": round(mean(r20_all), 4) if r20_all else None,
            "quant_win_rate": wr_all,
            "quant_stop_loss_rate": sl_all,
            "llm_buy_count": len(r20_buy),
            "llm_buy_mean_20d": round(mean(r20_buy), 4) if r20_buy else None,
            "llm_buy_win_rate": wr_buy,
            "top_sectors": [{"sector": sec, "count": cnt} for sec, cnt in top_sectors],
        }

    # 5. 板块分析（简化版 L6）
    print("\n[5/7] 板块分析（简化版 L6）...", file=sys.stderr)
    sector_groups: dict[str, list[dict]] = defaultdict(list)
    for s in has_fwd:
        sector_groups[s.get("industry", "未知")].append(s)

    by_sector: dict[str, dict] = {}
    for sector, group in sorted(sector_groups.items(), key=lambda x: -len(x[1])):
        r20s = [s["forward"]["return_20d"] for s in group]
        wins = [v for v in r20s if v > 0]
        by_sector[sector] = {
            "count": len(group),
            "avg_return": round(mean(r20s), 4) if r20s else None,
            "win_rate": round(len(wins) / len(r20s), 4) if r20s else None,
            "symbols": list({s["symbol"] for s in group}),
        }

    suspected_mainlines = [
        sector
        for sector, info in by_sector.items()
        if info["count"] >= 3 and sector != "未知"
    ]

    # 主线 vs 非主线对比
    mainline_signals = []
    non_mainline_signals = []
    for s in has_fwd:
        if s.get("industry") in suspected_mainlines:
            mainline_signals.append(s)
        else:
            non_mainline_signals.append(s)

    ml_r20 = [s["forward"]["return_20d"] for s in mainline_signals]
    nml_r20 = [s["forward"]["return_20d"] for s in non_mainline_signals]
    ml_llm_buy = [s for s in mainline_signals if s["llm_action"] == "买入"]
    nml_llm_buy = [s for s in non_mainline_signals if s["llm_action"] == "买入"]

    sector_analysis = {
        "note": "简化版 L6（仅行业归属+集中度统计，不含实时板块成交额/涨幅/涨停扩散验证）",
        "by_sector": by_sector,
        "suspected_mainlines": suspected_mainlines,
        "mainline_vs_non": {
            "suspected_mainline": {
                "count": len(mainline_signals),
                "return_20d": desc(ml_r20),
                "llm_buy_count": len(ml_llm_buy),
                "llm_buy_mean_20d": round(
                    mean([s["forward"]["return_20d"] for s in ml_llm_buy]), 4
                )
                if ml_llm_buy
                else None,
            },
            "non_mainline": {
                "count": len(non_mainline_signals),
                "return_20d": desc(nml_r20),
                "llm_buy_count": len(nml_llm_buy),
                "llm_buy_mean_20d": round(
                    mean([s["forward"]["return_20d"] for s in nml_llm_buy]), 4
                )
                if nml_llm_buy
                else None,
            },
        },
    }

    # 6. 混淆矩阵
    print("\n[6/7] 混淆矩阵...", file=sys.stderr)

    tp = len([s for s in llm_buy if is_good(s)])
    fp = len([s for s in llm_buy if not is_good(s)])
    fn_good = len([s for s in has_fwd if is_good(s) and s["llm_action"] != "买入"])
    tn = len([s for s in llm_reject if is_bad(s)])

    actual_good = len([s for s in has_fwd if is_good(s)])
    actual_bad = len([s for s in has_fwd if is_bad(s)])

    # 7. 组装
    print("\n[7/7] 输出...", file=sys.stderr)

    r20_quant = [s["forward"]["return_20d"] for s in has_fwd]
    r20_llm_buy = [s["forward"]["return_20d"] for s in llm_buy]
    r20_llm_rej = [s["forward"]["return_20d"] for s in llm_reject]

    def sl_rate(group):
        if not group:
            return None
        return round(
            sum(1 for s in group if s["forward"].get("return_20d", 0) <= -0.05)
            / len(group),
            4,
        )

    # 止盈率：20d >= 10% 且 MDD < 12%
    def tp_rate(group):
        if not group:
            return None
        hits = sum(
            1
            for s in group
            if s["forward"].get("return_20d", 0) >= 0.10
            and s["forward"].get("max_drawdown_20d", 1) < 0.12
        )
        return round(hits / len(group), 4)

    # 累计收益模拟（等权买入，每月取LLM买入信号的均值）
    cumulative = 1.0
    cum_curve = []
    for month in sorted(by_month.keys()):
        bm = by_month[month]
        if bm["llm_buy_mean_20d"] is not None and bm["llm_buy_count"] > 0:
            cumulative *= 1 + bm["llm_buy_mean_20d"]
        cum_curve.append({"month": month, "cumulative": round(cumulative, 4)})

    return {
        "meta": {
            "scope": f"定向区间回测 {start_date}~{end_date}，含LLM模拟判断",
            "disclaimer": "本回测不构成投资建议。LLM判断为规则引擎模拟，不等同于真实LLM判断。",
            "parameters": {
                "start_date": start_date,
                "end_date": end_date,
                "sample_size": sample_size,
                "total_scanned": len(sample),
                "fetch_errors": fetch_errors,
                "short_bars": short_bars,
                "low_amount_count": low_amount_count,
                "min_avg_amount": min_avg_amount,
            },
        },
        "summary": {
            "total_signals": len(all_signals),
            "signals_with_forward": len(has_fwd),
            "unique_stocks": len({s["symbol"] for s in all_signals}),
            "date_range": {
                "earliest": min(s["signal_date"] for s in all_signals),
                "latest": max(s["signal_date"] for s in all_signals),
            },
        },
        "quant_vs_llm": {
            "quant_all": {
                "count": len(has_fwd),
                "return_20d": desc(r20_quant),
                "stop_loss_rate": sl_rate(has_fwd),
                "take_profit_rate": tp_rate(has_fwd),
            },
            "llm_buy": {
                "count": len(llm_buy),
                "return_20d": desc(r20_llm_buy),
                "stop_loss_rate": sl_rate(llm_buy),
                "take_profit_rate": tp_rate(llm_buy),
            },
            "llm_observe": {
                "count": len(llm_observe),
                "return_20d": desc([s["forward"]["return_20d"] for s in llm_observe]),
            },
            "llm_reject": {
                "count": len(llm_reject),
                "return_20d": desc(r20_llm_rej),
                "stop_loss_rate": sl_rate(llm_reject),
            },
        },
        "confusion_matrix": {
            "actual_good": actual_good,
            "actual_bad": actual_bad,
            "TP": tp,
            "FP": fp,
            "FN": fn_good,
            "TN": tn,
            "buy_precision": round(tp / max(tp + fp, 1), 4),
            "buy_recall": round(tp / max(actual_good, 1), 4),
        },
        "monthly_breakdown": by_month,
        "cumulative_curve": cum_curve,
        "sector_analysis": sector_analysis,
        "sample_signals": {
            "top_winners": sorted(
                has_fwd, key=lambda s: s["forward"].get("return_20d", 0), reverse=True
            )[:10],
            "top_losers": sorted(
                has_fwd, key=lambda s: s["forward"].get("return_20d", 0)
            )[:10],
        },
        "all_signals": sorted(has_fwd, key=lambda s: s["signal_date"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-10-01")
    parser.add_argument("--end", default="2026-05-31")
    parser.add_argument("--sample", type=int, default=1500)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--min-amount",
        type=float,
        default=100_000_000,
        help="最低日均成交额（元），默认1亿",
    )
    args = parser.parse_args()

    result = run_backtest(
        start_date=args.start,
        end_date=args.end,
        sample_size=args.sample,
        min_avg_amount=args.min_amount,
    )

    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    out_path = Path(args.output) if args.output else ROOT / "backtest_oct25_jun26.json"
    out_path.write_text(text, encoding="utf-8")
    print(f"\n结果已写入 {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
