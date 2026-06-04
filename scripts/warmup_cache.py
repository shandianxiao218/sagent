#!/usr/bin/env python3
"""缓存预热脚本 — 一次性加载所有数据到本地 SQLite。

预热内容：
  1. 个股 K 线缓存 (data/bars.db) — 全 A 股日线
  2. 行业映射缓存 (data/sector.db) — mootdx block() 全量映射
  3. 板块指数 K 线缓存 (data/sector_bars.db) — 同花顺行业板块日线

用法：
  python scripts/warmup_cache.py [--all] [--stocks] [--sectors] [--sector-bars]

  --all          预热所有缓存（默认）
  --stocks       只预热个股 K 线
  --sectors      只预热行业映射
  --sector-bars  只预热板块指数 K 线

示例：
  python scripts/warmup_cache.py                    # 预热全部
  python scripts/warmup_cache.py --stocks           # 只预热个股
  python scripts/warmup_cache.py --sectors          # 只预热行业映射
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def warmup_stocks(sample: int = 0, min_bars: int = 300) -> dict:
    """预热个股 K 线缓存。

    Args:
        sample: 预热股票数量，0=全部。
        min_bars: 最低 K 线条数。
    """
    print("\n=== [1/3] 预热个股 K 线缓存 ===", file=sys.stderr)

    from sagent.cache import LocalBarCache

    db_path = ROOT / "data" / "bars.db"
    cache = LocalBarCache(db_path)

    # 获取股票列表
    print("  获取股票列表...", file=sys.stderr)
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        valid_prefixes = ("000", "001", "002", "300", "600", "601", "603")
        stocks = [
            str(row.get("code", ""))
            for row in df.to_dict("records")
            if str(row.get("code", "")).startswith(valid_prefixes)
        ]
    except Exception as e:
        print(f"  获取股票列表失败: {e}", file=sys.stderr)
        return {"error": str(e)}

    if sample > 0:
        stocks = stocks[:sample]

    print(f"  共 {len(stocks)} 只股票，开始加载...", file=sys.stderr)

    t0 = time.perf_counter()
    cache.ensure_symbols(stocks, min_bars=min_bars)
    elapsed = time.perf_counter() - t0

    stats = cache.stats()
    cache.close()

    print(
        f"  完成: {stats['total_symbols']} 只, {stats['total_rows']} 条, "
        f"{stats['db_size_mb']} MB, 耗时 {elapsed:.1f}s",
        file=sys.stderr,
    )
    return {"elapsed_sec": round(elapsed, 1), **stats}


def warmup_sectors() -> dict:
    """预热行业映射缓存。"""
    print("\n=== [2/3] 预热行业映射缓存 ===", file=sys.stderr)

    from sagent.sector_cache import SectorCache

    db_path = ROOT / "data" / "sector.db"
    cache = SectorCache(db_path)

    t0 = time.perf_counter()
    result = cache.refresh()
    elapsed = time.perf_counter() - t0

    stats = cache.stats()
    cache.close()

    print(
        f"  完成: {stats['total_sectors']} 个板块, "
        f"{stats['total_symbols']} 只股票, "
        f"{stats['db_size_mb']} MB, 耗时 {elapsed:.1f}s",
        file=sys.stderr,
    )
    return {"elapsed_sec": round(elapsed, 1), "refresh_result": result, **stats}


def warmup_sector_bars() -> dict:
    """预热板块指数 K 线缓存。"""
    print("\n=== [3/3] 预热板块指数 K 线缓存 ===", file=sys.stderr)

    from sagent.sector_bars_cache import SectorBarCache

    db_path = ROOT / "data" / "sector_bars.db"
    cache = SectorBarCache(db_path)

    t0 = time.perf_counter()
    cache.ensure_sectors()
    elapsed = time.perf_counter() - t0

    stats = cache.stats()
    cache.close()

    print(
        f"  完成: {stats.get('total_sectors', 0)} 个板块, "
        f"{stats.get('total_rows', 0)} 条, "
        f"{stats.get('db_size_mb', 0)} MB, 耗时 {elapsed:.1f}s",
        file=sys.stderr,
    )
    return {"elapsed_sec": round(elapsed, 1), **stats}


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 缓存预热脚本")
    parser.add_argument("--all", action="store_true", help="预热所有缓存（默认）")
    parser.add_argument("--stocks", action="store_true", help="只预热个股 K 线")
    parser.add_argument("--sectors", action="store_true", help="只预热行业映射")
    parser.add_argument("--sector-bars", action="store_true", help="只预热板块指数 K 线")
    parser.add_argument("--sample", type=int, default=0, help="预热股票数量（0=全部）")
    args = parser.parse_args()

    do_all = args.all or not (args.stocks or args.sectors or args.sector_bars)

    results: dict = {"status": "ok"}

    try:
        if do_all or args.stocks:
            results["stocks"] = warmup_stocks(sample=args.sample)
    except Exception as e:
        print(f"  个股缓存预热失败: {e}", file=sys.stderr)
        results["stocks"] = {"error": str(e)}

    try:
        if do_all or args.sectors:
            results["sectors"] = warmup_sectors()
    except Exception as e:
        print(f"  行业映射预热失败: {e}", file=sys.stderr)
        results["sectors"] = {"error": str(e)}

    try:
        if do_all or args.sector_bars:
            results["sector_bars"] = warmup_sector_bars()
    except Exception as e:
        print(f"  板块 K 线预热失败: {e}", file=sys.stderr)
        results["sector_bars"] = {"error": str(e)}

    print("\n=== 预热完成 ===", file=sys.stderr)
    for name, result in results.items():
        if name == "status":
            continue
        if "error" in result:
            print(f"  {name}: 失败 - {result['error']}", file=sys.stderr)
        else:
            elapsed = result.get("elapsed_sec", "?")
            print(f"  {name}: 成功 ({elapsed}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
