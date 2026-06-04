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
import time
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.backtest_engine import simulate_trade
from sagent.backtest_portfolio import run_portfolio_backtest
from sagent.cache import LocalBarCache
from sagent.kline import describe_stock
from sagent.models import DailyBar
from sagent.technical import check_signal_from_closes, simulated_llm_judge

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
    """直连 mootdx 获取 K 线（旧方式，不推荐用于回测）。"""
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
    cache_path: str | None = None,
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

    # 1.5 初始化 SQLite 缓存 + 预加载
    db_path = Path(cache_path) if cache_path else ROOT / "data" / "bars.db"
    cache = LocalBarCache(db_path)
    sample_symbols = [str(s.get("code", "")) for s in sample]
    print(f"\n  预加载缓存 ({db_path})...", file=sys.stderr)
    cache.ensure_symbols(sample_symbols, min_bars=300)
    cache_stats = cache.stats()
    print(
        f"  缓存就绪: {cache_stats['total_symbols']} 只, "
        f"{cache_stats['total_rows']} 条, "
        f"{cache_stats['db_size_mb']} MB",
        file=sys.stderr,
    )

    # 2. 获取K线 + 检测信号
    #    Phase A: 轻量级批量加载 (dates, closes) 做信号扫描
    #    Phase B: 只有命中信号的股票才加载完整 DailyBar
    #    关键防未来函数：所有数据只到 end_date
    print("\n[2/5] 获取K线并检测信号...", file=sys.stderr)

    # Phase A: 批量加载 closes（只取 date + close，比 DailyBar 快 ~10x）
    print("  Phase A: 批量加载 closes...", file=sys.stderr)
    t0 = time.perf_counter()
    all_closes_map = cache.bulk_closes_up_to(sample_symbols, end_date)
    t_load = time.perf_counter() - t0
    print(f"    加载 {len(all_closes_map)} 只, {t_load:.3f}s", file=sys.stderr)

    # Phase A 扫描：用 closes 做信号检测
    print("  Phase A: 信号扫描...", file=sys.stderr)
    t0 = time.perf_counter()
    scan_hits: list[dict] = []  # {symbol, name, signal_date, check_idx, metrics}
    short_bars = 0
    for i, stock in enumerate(sample):
        symbol = str(stock.get("code", ""))
        name = str(stock.get("name", ""))

        dates, closes = all_closes_map.get(symbol, ([], []))
        if len(closes) < 300:
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

        scan_start = max(260, range_start_idx)
        scan_end = min(range_end_idx, len(closes) - min_forward)

        for check_idx in range(scan_start, scan_end, window_step):
            sig_date = dates[check_idx]
            if sig_date < start_date or sig_date > end_date:
                continue
            metrics = check_signal_from_closes(closes, check_idx)
            if metrics is not None:
                scan_hits.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "signal_date": sig_date,
                        "check_idx": check_idx,
                        "metrics": metrics,
                        "closes": closes,  # 保留给 Phase B 的 forward_returns
                        "dates": dates,
                    }
                )
    t_scan = time.perf_counter() - t0
    print(f"    扫描完成: {len(scan_hits)} 信号, {t_scan:.3f}s", file=sys.stderr)

    # Phase B: 只为命中信号的股票加载完整 DailyBar
    print(f"  Phase B: 加载 {len(scan_hits)} 个信号的完整 K 线...", file=sys.stderr)
    t0 = time.perf_counter()
    all_signals: list[dict] = []
    fetch_errors = 0
    low_amount_count = 0
    # 按信号股票去重加载
    hit_symbols = {h["symbol"] for h in scan_hits}
    bars_map: dict[str, list] = {}
    for sym in hit_symbols:
        bars_map[sym] = cache.daily_bars_up_to(sym, end_date)

    for hit in scan_hits:
        symbol = hit["symbol"]
        bars = bars_map.get(symbol, [])
        if not bars:
            continue
        check_idx = hit["check_idx"]

        # 成交额过滤（最近20日）
        recent_bars = bars[-20:]
        avg_amount = mean(bar.amount for bar in recent_bars) if recent_bars else 0
        if avg_amount < min_avg_amount:
            low_amount_count += 1
            continue

        fwd = forward_returns(bars, check_idx)
        window_bars = bars[: check_idx + 1]
        desc_result = describe_stock(symbol, window_bars)
        llm_result = simulated_llm_judge(
            hit["metrics"], desc_result.text, desc_result.key_low
        )

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
    t_phase_b = time.perf_counter() - t0
    print(
        f"    Phase B 完成: {len(all_signals)} 有效信号, {t_phase_b:.3f}s",
        file=sys.stderr,
    )

    cache.close()
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


# ─── 逐日止损/止盈引擎回测 ────────────────────────────────────


def run_engine_backtest(
    start_date: str = "2025-10-01",
    end_date: str = "2026-05-31",
    sample_size: int = 500,
    seed: int = 42,
    window_step: int = 3,
    min_avg_amount: float = 100_000_000,
    initial_cash: float = 100_000,
    max_holding: int = 20,
    cache_path: str | None = None,
) -> dict:
    """使用逐日止损/止盈引擎 + 组合管理的回测。

    与 run_backtest() 的区别：
    - 使用 backtest_engine.simulate_trade() 逐日遍历，而非简单持有 20 天
    - 使用 backtest_portfolio.run_portfolio_backtest() 模拟资金管理
    - 每笔交易有退出方式（止损/趋势破坏/持有到期）
    - 组合管理：初始资金、每笔 10%、每周最多 2 笔

    防未来函数：所有 K 线只加载到 end_date，simulate_trade 的 bars 不会包含未来数据。
    """
    print(
        f"=== 引擎回测 (逐日止损/止盈 + 组合管理): {start_date} ~ {end_date} ===",
        file=sys.stderr,
    )
    print(
        f"参数: 采样{sample_size}只, 步长{window_step}日, "
        f"初始资金{initial_cash:,.0f}, 最大持有{max_holding}天",
        file=sys.stderr,
    )

    # 1. 获取股票列表
    print("\n[1/6] 获取A股列表...", file=sys.stderr)
    all_stocks = fetch_all_stocks()
    valid_prefixes = ("000", "001", "002", "300", "600", "601", "603")
    all_stocks = [
        s for s in all_stocks if str(s.get("code", "")).startswith(valid_prefixes)
    ]
    print(f"  主板共 {len(all_stocks)} 只", file=sys.stderr)

    random.seed(seed)
    sample = random.sample(all_stocks, min(sample_size, len(all_stocks)))
    print(f"  采样 {len(sample)} 只", file=sys.stderr)

    # 1.5 初始化 SQLite 缓存 + 预加载
    db_path = Path(cache_path) if cache_path else ROOT / "data" / "bars.db"
    cache = LocalBarCache(db_path)
    sample_symbols = [str(s.get("code", "")) for s in sample]
    print(f"\n  预加载缓存 ({db_path})...", file=sys.stderr)
    cache.ensure_symbols(sample_symbols, min_bars=300)
    cache_stats = cache.stats()
    print(
        f"  缓存就绪: {cache_stats['total_symbols']} 只, "
        f"{cache_stats['total_rows']} 条, "
        f"{cache_stats['db_size_mb']} MB",
        file=sys.stderr,
    )

    # 2. 获取K线 + 检测信号
    #    Phase A: 轻量级批量 closes 扫描
    #    Phase B: 只为命中股票加载完整 DailyBar
    print("\n[2/6] 获取K线并检测信号...", file=sys.stderr)
    name_cache: dict[str, str] = {
        str(s.get("code", "")): str(s.get("name", "")) for s in sample
    }

    # Phase A: 批量 closes 扫描
    print("  Phase A: 批量加载 closes...", file=sys.stderr)
    t0 = time.perf_counter()
    all_closes_map = cache.bulk_closes_up_to(sample_symbols, end_date)
    print(
        f"    {len(all_closes_map)} 只, {time.perf_counter() - t0:.3f}s",
        file=sys.stderr,
    )

    print("  Phase A: 信号扫描...", file=sys.stderr)
    t0 = time.perf_counter()
    scan_hits: list[dict] = []
    short_bars = 0
    for sym in sample_symbols:
        dates, closes = all_closes_map.get(sym, ([], []))
        if len(closes) < 300:
            short_bars += 1
            continue
        range_start_idx = range_end_idx = None
        for j in range(len(dates)):
            if dates[j] >= start_date and range_start_idx is None:
                range_start_idx = j
            if dates[j] <= end_date:
                range_end_idx = j
        if range_start_idx is None or range_end_idx is None:
            continue
        scan_start = max(260, range_start_idx)
        scan_end = min(range_end_idx, len(closes) - max_holding)
        for check_idx in range(scan_start, scan_end, window_step):
            sig_date = dates[check_idx]
            if sig_date < start_date or sig_date > end_date:
                continue
            sig_metrics = check_signal_from_closes(closes, check_idx)
            if sig_metrics is not None:
                scan_hits.append(
                    {
                        "symbol": sym,
                        "signal_date": sig_date,
                        "signal_idx": check_idx,
                        "metrics": sig_metrics,
                    }
                )
    print(
        f"    {len(scan_hits)} 信号, {time.perf_counter() - t0:.3f}s", file=sys.stderr
    )

    # Phase B: 只加载命中信号股票的完整 DailyBar
    print(
        f"  Phase B: 加载 {len({h['symbol'] for h in scan_hits})} 只信号股票完整 K 线...",
        file=sys.stderr,
    )
    t0 = time.perf_counter()
    hit_symbols = {h["symbol"] for h in scan_hits}
    bars_cache: dict[str, list[DailyBar]] = {}
    for sym in hit_symbols:
        bars_cache[sym] = cache.daily_bars_up_to(sym, end_date)
    print(f"    {time.perf_counter() - t0:.3f}s", file=sys.stderr)

    # 成交额过滤 + 组装 all_signals
    all_signals: list[dict] = []
    low_amount_count = 0
    for hit in scan_hits:
        sym = hit["symbol"]
        bars = bars_cache.get(sym, [])
        if not bars:
            continue
        # 成交额过滤
        recent_bars = bars[-20:]
        avg_amount = mean(bar.amount for bar in recent_bars) if recent_bars else 0
        if avg_amount < min_avg_amount:
            low_amount_count += 1
            continue
        all_signals.append(
            {
                "symbol": sym,
                "name": name_cache.get(sym, ""),
                "signal_date": hit["signal_date"],
                "signal_idx": hit["signal_idx"],
                "metrics": hit["metrics"],
            }
        )

    fetch_errors = 0
    print(
        f"\n  完成: 错误{fetch_errors}, K线不足{short_bars}, "
        f"成交额不足{low_amount_count}",
        file=sys.stderr,
    )
    print(f"  总信号: {len(all_signals)}", file=sys.stderr)

    if not all_signals:
        return {"error": "未找到信号", "total_signals": 0}

    # 3. 逐日止损/止盈回测 + K线描述 + LLM判断
    print("\n[3/6] 逐日止损/止盈引擎回测...", file=sys.stderr)
    engine_results: list[dict] = []

    for sig in all_signals:
        symbol = sig["symbol"]
        bars = bars_cache.get(symbol, [])
        signal_idx = sig["signal_idx"]
        if not bars or signal_idx is None:
            continue

        trade = simulate_trade(bars, signal_idx, max_holding=max_holding)

        # K线描述（用于 LLM 判断和报表展示）
        window_bars = bars[: signal_idx + 1]
        desc_result = describe_stock(symbol, window_bars)

        # LLM 模拟判断
        llm_result = simulated_llm_judge(
            sig["metrics"], desc_result.text, desc_result.key_low
        )

        engine_results.append(
            {
                "symbol": symbol,
                "name": sig["name"],
                "signal_date": sig["signal_date"],
                # ── 选股理由 ──
                "metrics": sig["metrics"],
                "kline_description": desc_result.text,
                "key_low": desc_result.key_low,
                # ── LLM 判断 ──
                "llm_action": llm_result["action"],
                "llm_reason": llm_result["reason"],
                "llm_confidence": llm_result["confidence"],
                # ── 交易结果 ──
                "entry_price": trade.entry_price,
                "stop_loss_price": trade.stop_loss_price,
                "exit_reason": trade.exit_reason,
                "exit_date": trade.exit_date,
                "exit_price": trade.exit_price,
                "holding_days": trade.holding_days,
                "total_return": trade.total_return,
                "half_profit_locked": trade.half_profit_locked,
                "half_profit_r": trade.half_profit_r,
                "max_r": trade.max_r,
                "stop_loss_type": trade.stop_loss_type,
                "trend_break_ref": trade.trend_break_ref,
                "buy_and_hold_return": trade.buy_and_hold_return,
            }
        )

    print(f"  引擎回测完成: {len(engine_results)} 笔交易", file=sys.stderr)

    # 4. 组合管理回测
    print("\n[4/6] 组合管理回测...", file=sys.stderr)
    portfolio_signals = [
        {
            "symbol": s["symbol"],
            "signal_date": s["signal_date"],
            "signal_idx": s["signal_idx"],
        }
        for s in all_signals
    ]
    portfolio_stats = run_portfolio_backtest(
        bars_cache,
        portfolio_signals,
        initial_cash=initial_cash,
        max_holding=max_holding,
    )
    print(
        f"  组合回测完成: {portfolio_stats.total_trades} 笔交易, "
        f"总收益 {portfolio_stats.total_return:.2%}",
        file=sys.stderr,
    )

    # 5. 汇总统计
    cache.close()
    print("\n[5/6] 汇总统计...", file=sys.stderr)

    def safe_mean(values: list[float]) -> float | None:
        return round(mean(values), 4) if values else None

    all_returns = [t["total_return"] for t in engine_results]
    sl_trades = [t for t in engine_results if t["exit_reason"] == "止损"]
    tp_trades = [t for t in engine_results if t["exit_reason"] == "半仓止盈后趋势破坏"]
    nat_trades = [t for t in engine_results if t["exit_reason"] == "持有到期"]
    half_triggered = [t for t in engine_results if t["half_profit_locked"]]
    hold_returns = [t["buy_and_hold_return"] for t in engine_results]

    engine_summary = {
        "total_trades": len(engine_results),
        "stop_loss_count": len(sl_trades),
        "take_profit_count": len(tp_trades),
        "natural_exit_count": len(nat_trades),
        "stop_loss_rate": round(len(sl_trades) / max(len(engine_results), 1), 4),
        "take_profit_rate": round(len(tp_trades) / max(len(engine_results), 1), 4),
        "natural_exit_rate": round(len(nat_trades) / max(len(engine_results), 1), 4),
        "avg_return_all": safe_mean(all_returns),
        "avg_return_stop_loss": safe_mean([t["total_return"] for t in sl_trades]),
        "avg_return_take_profit": safe_mean([t["total_return"] for t in tp_trades]),
        "avg_return_natural": safe_mean([t["total_return"] for t in nat_trades]),
        "win_rate": round(
            sum(1 for r in all_returns if r > 0) / max(len(all_returns), 1), 4
        ),
        "avg_holding_days": safe_mean(
            [float(t["holding_days"]) for t in engine_results]
        ),
        "half_profit_triggered_count": len(half_triggered),
        "half_profit_triggered_rate": round(
            len(half_triggered) / max(len(engine_results), 1), 4
        ),
        "avg_return_half_triggered": safe_mean(
            [t["total_return"] for t in half_triggered]
        ),
        "avg_return_half_not_triggered": safe_mean(
            [t["total_return"] for t in engine_results if not t["half_profit_locked"]]
        ),
        "buy_and_hold_avg_return": safe_mean(hold_returns),
        "strategy_vs_buyhold_diff": round(
            (safe_mean(all_returns) or 0) - (safe_mean(hold_returns) or 0), 4
        ),
    }

    # 按月分组
    monthly_engine: dict[str, dict] = {}
    monthly_groups: dict[str, list[dict]] = defaultdict(list)
    for t in engine_results:
        month = t["signal_date"][:7]
        monthly_groups[month].append(t)

    for month in sorted(monthly_groups.keys()):
        group = monthly_groups[month]
        returns = [t["total_return"] for t in group]
        sl = [t for t in group if t["exit_reason"] == "止损"]
        monthly_engine[month] = {
            "total": len(group),
            "avg_return": safe_mean(returns),
            "win_rate": round(
                sum(1 for r in returns if r > 0) / max(len(returns), 1), 4
            ),
            "stop_loss_count": len(sl),
            "avg_holding_days": safe_mean([float(t["holding_days"]) for t in group]),
        }

    # 旧方式对比（买入持有 20 天）
    old_vs_new = {
        "old_buyhold_avg": safe_mean(hold_returns),
        "new_engine_avg": safe_mean(all_returns),
        "diff": round(
            (safe_mean(all_returns) or 0) - (safe_mean(hold_returns) or 0), 4
        ),
        "note": "old=买入持有20天收益, new=逐日止损止盈综合收益",
    }

    # 6. 组装输出
    print("\n[6/6] 输出...", file=sys.stderr)

    return {
        "meta": {
            "scope": f"引擎回测 {start_date}~{end_date}（逐日止损/止盈 + 组合管理）",
            "disclaimer": (
                "本回测不构成投资建议。LLM判断为规则引擎模拟，"
                "不等同于真实LLM判断。使用逐日止损/止盈引擎。"
            ),
            "parameters": {
                "start_date": start_date,
                "end_date": end_date,
                "sample_size": sample_size,
                "initial_cash": initial_cash,
                "max_holding": max_holding,
                "total_scanned": len(sample),
                "fetch_errors": fetch_errors,
                "short_bars": short_bars,
                "low_amount_count": low_amount_count,
                "min_avg_amount": min_avg_amount,
            },
        },
        "engine_summary": engine_summary,
        "monthly_engine": monthly_engine,
        "old_vs_new": old_vs_new,
        "portfolio": {
            "initial_cash": portfolio_stats.initial_cash,
            "final_value": portfolio_stats.final_value,
            "total_return": portfolio_stats.total_return,
            "max_drawdown": portfolio_stats.max_drawdown,
            "sharpe_ratio": portfolio_stats.sharpe_ratio,
            "total_trades": portfolio_stats.total_trades,
            "winning_trades": portfolio_stats.winning_trades,
            "losing_trades": portfolio_stats.losing_trades,
            "win_rate": portfolio_stats.win_rate,
            "avg_profit": portfolio_stats.avg_profit,
            "avg_loss": portfolio_stats.avg_loss,
            "profit_loss_ratio": portfolio_stats.profit_loss_ratio,
            "max_single_profit": portfolio_stats.max_single_profit,
            "max_single_loss": portfolio_stats.max_single_loss,
            "stop_loss_count": portfolio_stats.stop_loss_count,
            "take_profit_count": portfolio_stats.take_profit_count,
            "natural_exit_count": portfolio_stats.natural_exit_count,
            "avg_holding_days": portfolio_stats.avg_holding_days,
            "capital_utilization": portfolio_stats.capital_utilization,
            "nav_curve_count": len(portfolio_stats.nav_curve),
            "nav_curve": [
                {
                    "date": nc.date,
                    "cash": round(nc.cash, 2),
                    "position_value": round(nc.position_value, 2),
                    "total_value": round(nc.total_value, 2),
                    "open_positions": nc.open_positions,
                }
                for nc in portfolio_stats.nav_curve
            ],
        },
        "trades": engine_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "sagent 回测脚本。默认使用旧方式（买入持有20天），"
            "--engine 使用逐日止损/止盈引擎。"
            "数据源使用 SQLite 缓存，防未来函数。"
        ),
    )
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
    parser.add_argument(
        "--engine",
        action="store_true",
        help="使用逐日止损/止盈引擎 + 组合管理回测",
    )
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100_000,
        help="组合管理初始资金（仅 --engine 模式），默认 100000",
    )
    parser.add_argument(
        "--cache",
        default=None,
        help="SQLite 缓存文件路径（默认 data/bars.db）",
    )
    args = parser.parse_args()

    if args.engine:
        result = run_engine_backtest(
            start_date=args.start,
            end_date=args.end,
            sample_size=args.sample,
            min_avg_amount=args.min_amount,
            initial_cash=args.initial_cash,
            cache_path=args.cache,
        )
        default_output = ROOT / "backtest_engine_v1.json"
    else:
        result = run_backtest(
            start_date=args.start,
            end_date=args.end,
            sample_size=args.sample,
            min_avg_amount=args.min_amount,
            cache_path=args.cache,
        )
        default_output = ROOT / "backtest_oct25_jun26.json"

    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    out_path = Path(args.output) if args.output else default_output
    out_path.write_text(text, encoding="utf-8")
    print(f"\n结果已写入 {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
