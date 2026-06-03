#!/usr/bin/env python3
"""端到端时间基准测试。

用 100 只股票采样对比：
  - 缓存预热（全量下载 3 年日线）
  - 增量更新（只补最新缺失日）
  - 全量扫描（从缓存读 + 技术指标计算）
  - 直连扫描（从 mootdx 逐只拉取）

用法：
  python scripts/benchmark_scan.py
  python scripts/benchmark_scan.py --sample 50
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.data import AStockDataMarketData
from sagent.kline import describe_stock
from sagent.technical import _check_candidate_conditions


def _get_sample_stocks(data: AStockDataMarketData, sample_size: int = 100) -> list:
    """获取采样股票列表。优先选非 ST、有成交量的。"""
    all_stocks = data.stocks()
    # 过滤 ST
    filtered = [s for s in all_stocks if "ST" not in s.name and "*ST" not in s.name]
    if len(filtered) <= sample_size:
        return filtered
    # 均匀采样
    step = len(filtered) / sample_size
    return [filtered[int(i * step)] for i in range(sample_size)]


def bench_cache_warmup(cache, symbols: list[str]) -> dict:
    """Benchmark: 全量下载 3 年日线。"""
    print(f"\n[1] 缓存预热：下载 {len(symbols)} 只股票 3 年日线...", file=sys.stderr)
    t0 = time.perf_counter()
    result = cache.download_and_cache(symbols, offset=750)
    elapsed = time.perf_counter() - t0
    total_bars = sum(result.values())
    return {
        "phase": "cache_warmup",
        "stock_count": len(symbols),
        "total_bars": total_bars,
        "elapsed_sec": round(elapsed, 2),
        "bars_per_sec": round(total_bars / elapsed, 0) if elapsed > 0 else 0,
    }


def bench_cache_incremental(cache, symbols: list[str]) -> dict:
    """Benchmark: 增量更新（只补最新缺失日）。"""
    print(f"\n[2] 增量更新：检查 {len(symbols)} 只股票...", file=sys.stderr)
    t0 = time.perf_counter()
    result = cache.ensure_symbols(symbols, min_bars=250)
    elapsed = time.perf_counter() - t0
    new_bars = sum(v for v in result.values() if v > 0)
    return {
        "phase": "cache_incremental",
        "stock_count": len(symbols),
        "new_bars": new_bars,
        "elapsed_sec": round(elapsed, 2),
    }


def bench_cache_scan(bars_map: dict, sample_size: int) -> dict:
    """Benchmark: 从缓存读 + 全量扫描。"""
    print(f"\n[3] 缓存扫描：{len(bars_map)} 只股票...", file=sys.stderr)
    t0 = time.perf_counter()
    candidates = 0
    skipped = 0
    for _symbol, bars in bars_map.items():
        if len(bars) < 260:
            skipped += 1
            continue
        closes = [b.close for b in bars]
        result = _check_candidate_conditions(closes)
        if result is not None:
            candidates += 1
    elapsed = time.perf_counter() - t0
    return {
        "phase": "cache_scan",
        "stock_count": len(bars_map),
        "candidates_found": candidates,
        "skipped": skipped,
        "elapsed_sec": round(elapsed, 2),
        "stocks_per_sec": round(len(bars_map) / elapsed, 0) if elapsed > 0 else 0,
    }


def bench_cache_scan_with_kline(bars_map: dict, sample_size: int) -> dict:
    """Benchmark: 缓存扫描 + K 线描述生成（对候选股）。"""
    print(f"\n[4] 缓存扫描 + K线描述：{len(bars_map)} 只股票...", file=sys.stderr)
    t0 = time.perf_counter()
    candidates = 0
    kline_count = 0
    for symbol, bars in bars_map.items():
        if len(bars) < 260:
            continue
        closes = [b.close for b in bars]
        result = _check_candidate_conditions(closes)
        if result is not None:
            candidates += 1
            describe_stock(symbol, bars)
            kline_count += 1
    elapsed = time.perf_counter() - t0
    return {
        "phase": "cache_scan_with_kline",
        "stock_count": len(bars_map),
        "candidates_found": candidates,
        "kline_descriptions": kline_count,
        "elapsed_sec": round(elapsed, 2),
    }


def bench_direct_scan(data: AStockDataMarketData, stocks: list) -> dict:
    """Benchmark: 直连 mootdx 逐只下载 + 扫描。"""
    print(f"\n[5] 直连扫描：逐只下载 {len(stocks)} 只股票...", file=sys.stderr)
    t0 = time.perf_counter()
    candidates = 0
    downloaded = 0
    for stock in stocks:
        try:
            bars = data.daily_bars(stock.symbol)
            downloaded += 1
            if len(bars) < 260:
                continue
            closes = [b.close for b in bars]
            result = _check_candidate_conditions(closes)
            if result is not None:
                candidates += 1
        except Exception:
            continue
    elapsed = time.perf_counter() - t0
    return {
        "phase": "direct_scan",
        "stock_count": len(stocks),
        "downloaded": downloaded,
        "candidates_found": candidates,
        "elapsed_sec": round(elapsed, 2),
        "stocks_per_sec": round(downloaded / elapsed, 1) if elapsed > 0 else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 端到端基准测试")
    parser.add_argument(
        "--sample",
        type=int,
        default=100,
        help="采样股票数量（默认 100）",
    )
    parser.add_argument(
        "--skip-warmup",
        action="store_true",
        help="跳过缓存预热（如果已有缓存）",
    )
    parser.add_argument(
        "--skip-direct",
        action="store_true",
        help="跳过直连对比（省时间）",
    )
    args = parser.parse_args()

    print(f"=== sagent 端到端基准测试 (采样 {args.sample} 只) ===", file=sys.stderr)

    # 初始化
    data = AStockDataMarketData()
    sample_stocks = _get_sample_stocks(data, args.sample)
    symbols = [s.symbol for s in sample_stocks]
    print(f"采样 {len(sample_stocks)} 只非 ST 股票", file=sys.stderr)

    # 缓存路径
    cache_path = ROOT / "data" / "benchmark_bars.db"
    from sagent.cache import LocalBarCache

    cache = LocalBarCache(cache_path)

    results: list[dict] = []

    # Phase 1: 缓存预热
    if not args.skip_warmup:
        r = bench_cache_warmup(cache, symbols)
        results.append(r)
        print(f"  → {r['elapsed_sec']}s, {r['bars_per_sec']} bars/s", file=sys.stderr)

    # Phase 2: 增量更新
    r = bench_cache_incremental(cache, symbols)
    results.append(r)
    print(f"  → {r['elapsed_sec']}s, {r['new_bars']} new bars", file=sys.stderr)

    # Phase 3: 缓存批量读取
    print("\n[3-pre] 批量读取缓存...", file=sys.stderr)
    t0 = time.perf_counter()
    bars_map = cache.bulk_daily_bars(symbols)
    t_load = time.perf_counter() - t0
    print(f"  → 加载 {len(bars_map)} 只股票 ({t_load:.2f}s)", file=sys.stderr)
    results.append(
        {
            "phase": "cache_bulk_load",
            "stock_count": len(symbols),
            "loaded": len(bars_map),
            "elapsed_sec": round(t_load, 2),
        }
    )

    # Phase 4: 缓存扫描
    r = bench_cache_scan(bars_map, len(symbols))
    results.append(r)
    print(f"  → {r['elapsed_sec']}s, {r['stocks_per_sec']} stocks/s", file=sys.stderr)

    # Phase 5: 缓存扫描 + K 线描述
    r = bench_cache_scan_with_kline(bars_map, len(symbols))
    results.append(r)
    print(f"  → {r['elapsed_sec']}s", file=sys.stderr)

    # Phase 6: 直连对比
    if not args.skip_direct:
        r = bench_direct_scan(data, sample_stocks)
        results.append(r)
        print(
            f"  → {r['elapsed_sec']}s, {r['stocks_per_sec']} stocks/s", file=sys.stderr
        )

    # 缓存统计
    cache_stats = cache.stats()
    cache.close()

    # 输出汇总
    summary = {
        "sample_size": len(sample_stocks),
        "cache_stats": cache_stats,
        "benchmarks": results,
        "estimated_full_scan": {},
    }

    # 估算全量扫描时间
    if results:
        cache_scan = next((r for r in results if r["phase"] == "cache_scan"), None)
        direct_scan = next((r for r in results if r["phase"] == "direct_scan"), None)
        incremental = next(
            (r for r in results if r["phase"] == "cache_incremental"), None
        )

        total_stocks = 5500  # 全 A 股约 5500 只
        if cache_scan and cache_scan["elapsed_sec"] > 0:
            ratio = total_stocks / len(sample_stocks)
            summary["estimated_full_scan"] = {
                "cache_scan_sec": round(cache_scan["elapsed_sec"] * ratio, 1),
                "direct_scan_sec": round(direct_scan["elapsed_sec"] * ratio, 1)
                if direct_scan
                else None,
                "incremental_update_sec": round(incremental["elapsed_sec"] * ratio, 1)
                if incremental
                else None,
                "speedup": round(
                    direct_scan["elapsed_sec"] / cache_scan["elapsed_sec"], 1
                )
                if direct_scan and cache_scan["elapsed_sec"] > 0
                else None,
            }

    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
