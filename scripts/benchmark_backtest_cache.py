#!/usr/bin/env python3
"""对比回测数据加载：直连 mootdx vs SQLite 缓存。

测试场景：
  1. 预热缓存（确保数据就绪）
  2. 缓存模式：daily_bars_up_to() × N 只
  3. 直连模式：fetch_bars() × N 只（对比用）
  4. 缓存模式信号扫描（模拟回测 Phase 2）
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.cache import LocalBarCache
from sagent.models import DailyBar

SAMPLE_SIZE = 200
END_DATE = "2026-05-31"
BACKTEST_START = "2025-10-01"


def get_sample_symbols(n: int) -> list[str]:
    """从缓存中取 n 只有足够数据的股票。"""
    import akshare as ak

    df = ak.stock_info_a_code_name()
    valid = ("000", "001", "002", "300", "600", "601", "603")
    codes = [
        str(r["code"])
        for _, r in df.iterrows()
        if str(r.get("code", "")).startswith(valid)
    ]
    return codes[:n]


def check_signal_fast(closes: list[float], idx: int) -> bool:
    """优化版信号检测（直接用 closes 数组，不重建）。"""
    if idx < 260:
        return False
    current = closes[idx]
    ma250 = sum(closes[idx - 249 : idx + 1]) / 250
    if current <= ma250:
        return False
    s60 = idx - 59
    recent_60 = closes[s60 : idx + 1]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    if rise_60d < 0.5:
        return False
    s30 = idx - 29
    recent_30 = closes[s30 : idx + 1]
    pullback = (high_60 - min(recent_30)) / max(high_60 - low_60, 0.01)
    if not (0.15 <= pullback <= 0.5):
        return False
    recent_rebound = closes[idx] > closes[idx - 1] > closes[idx - 2]
    breakout = closes[idx] > max(closes[idx - 7 : idx])
    return recent_rebound and breakout


def benchmark_cache_load(cache: LocalBarCache, symbols: list[str]) -> dict:
    """缓存模式加载 K 线（轻量 closes 版）。"""
    t0 = time.perf_counter()
    closes_map = cache.bulk_closes_up_to(symbols, END_DATE)
    elapsed = time.perf_counter() - t0
    valid_stocks = sum(1 for v in closes_map.values() if len(v[1]) >= 300)
    total_points = sum(len(v[1]) for v in closes_map.values())
    return {"elapsed": elapsed, "stocks": valid_stocks, "total_bars": total_points}


def benchmark_cache_full_load(cache: LocalBarCache, symbols: list[str]) -> dict:
    """缓存模式加载完整 DailyBar（对比用）。"""
    t0 = time.perf_counter()
    bars_map = cache.bulk_daily_bars_up_to(symbols, END_DATE)
    elapsed = time.perf_counter() - t0
    valid_stocks = sum(1 for v in bars_map.values() if len(v) >= 300)
    total_bars = sum(len(v) for v in bars_map.values())
    return {"elapsed": elapsed, "stocks": valid_stocks, "total_bars": total_bars}


def benchmark_cache_scan(closes_map: dict[str, tuple[list[str], list[float]]]) -> dict:
    """缓存模式信号扫描（优化版：预提取 closes）。"""
    t0 = time.perf_counter()
    signals = 0
    for dates, closes in closes_map.values():
        if len(closes) < 300:
            continue
        start_idx = end_idx = None
        for j in range(len(dates)):
            if dates[j] >= BACKTEST_START and start_idx is None:
                start_idx = j
            if dates[j] <= END_DATE:
                end_idx = j
        if start_idx is None or end_idx is None:
            continue
        scan_start = max(260, start_idx)
        scan_end = min(end_idx, len(closes) - 20)
        for idx in range(scan_start, scan_end, 3):
            if check_signal_fast(closes, idx):
                signals += 1
    elapsed = time.perf_counter() - t0
    return {"elapsed": elapsed, "signals": signals}


def benchmark_direct_load(symbols: list[str]) -> dict:
    """直连 mootdx 加载 K 线（旧方式）。"""
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    t0 = time.perf_counter()
    bars_map: dict[str, list[DailyBar]] = {}
    errors = 0
    for sym in symbols:
        try:
            frame = client.bars(symbol=sym, category=4, offset=370)
            if frame is None or frame.empty:
                continue
            bars = []
            for idx, row in frame.iterrows():
                date_str = str(row.get("datetime", idx))
                bars.append(
                    DailyBar(
                        symbol=sym,
                        date=date_str[:10],
                        open=float(row.get("open", 0)),
                        high=float(row.get("high", 0)),
                        low=float(row.get("low", 0)),
                        close=float(row.get("close", 0)),
                        volume=float(row.get("vol", 0)),
                        amount=float(row.get("amount", 0)),
                    )
                )
            # 截断到 END_DATE（模拟防未来函数）
            bars = [b for b in bars if b.date <= END_DATE]
            if len(bars) >= 300:
                bars_map[sym] = bars
        except Exception:
            errors += 1
    elapsed = time.perf_counter() - t0
    total_bars = sum(len(v) for v in bars_map.values())
    return {
        "elapsed": elapsed,
        "stocks": len(bars_map),
        "total_bars": total_bars,
        "errors": errors,
    }


def main():
    print(f"=== 回测数据加载基准测试 (样本 {SAMPLE_SIZE} 只) ===\n")

    symbols = get_sample_symbols(SAMPLE_SIZE)
    print(f"采样 {len(symbols)} 只股票")

    cache = LocalBarCache(ROOT / "data" / "bars.db")
    stats = cache.stats()
    print(
        f"缓存状态: {stats['total_symbols']} 只, {stats['total_rows']} 条, {stats['db_size_mb']} MB\n"
    )

    # ── 1. 轻量 closes 加载 ──
    print("[1] 缓存模式加载 closes (bulk_closes_up_to)...")
    r1 = benchmark_cache_load(cache, symbols)
    print(f"    {r1['stocks']} 只, {r1['total_bars']} points, {r1['elapsed']:.3f}s")

    # ── 1b. 完整 DailyBar 加载（对比） ──
    print("[1b] 缓存模式加载完整 DailyBar (bulk_daily_bars_up_to)...")
    rb = benchmark_cache_full_load(cache, symbols)
    print(f"    {rb['stocks']} 只, {rb['total_bars']} bars, {rb['elapsed']:.3f}s")

    # ── 2. 缓存信号扫描 ──
    print("[2] 缓存模式信号扫描...")
    closes_map = cache.bulk_closes_up_to(symbols, END_DATE)
    r2 = benchmark_cache_scan(closes_map)
    print(f"    {r2['signals']} 信号, {r2['elapsed']:.3f}s")

    cache.close()

    # ── 3. 直连加载 ──
    print(f"\n[3] 直连模式加载 K 线 (mootdx TCP × {SAMPLE_SIZE})...")
    r3 = benchmark_direct_load(symbols[:50])  # 只测 50 只，太慢了
    r3_elapsed_per_50 = r3["elapsed"]
    print(f"    50 只: {r3['stocks']} 成功, {r3['elapsed']:.1f}s ({r3['errors']} 错误)")
    r3_estimated = r3_elapsed_per_50 * (SAMPLE_SIZE / 50)
    print(f"    推算 {SAMPLE_SIZE} 只: ~{r3_estimated:.1f}s")

    # ── 汇总 ──
    speedup_load = r3_estimated / r1["elapsed"] if r1["elapsed"] > 0 else float("inf")
    print(f"\n=== 汇总 ({SAMPLE_SIZE} 只) ===")
    print(f"  closes 加载:     {r1['elapsed']:.3f}s")
    print(
        f"  DailyBar 加载:   {rb['elapsed']:.3f}s  ({rb['elapsed'] / r1['elapsed']:.1f}x 慢于 closes)"
    )
    print(f"  信号扫描:        {r2['elapsed']:.3f}s")
    print(f"  closes+扫描:     {r1['elapsed'] + r2['elapsed']:.3f}s")
    print(f"  直连加载:        ~{r3_estimated:.1f}s (推算)")
    print(f"  提速比(closes):  {speedup_load:.1f}x")
    print(f"  提速比(DailyBar):{r3_estimated / rb['elapsed']:.1f}x")


if __name__ == "__main__":
    main()
