#!/usr/bin/env python3
"""准备扫描数据：量化粗筛 + K 线描述 + LLM 判断 + 板块验证 + 持仓监控。

优化要点：
  - 本地 SQLite 缓存日线数据，首次下载 3 年，后续增量补缺
  - 多日扫描复用同一份 K 线数据（不再 5525×N 次 TCP 请求）
  - 向量化 DataFrame 解析（替代 iterrows）

支持 --days N 参数扫描近 N 个交易日。
支持 --cache PATH 指定缓存数据库路径（默认 data/bars.db）。
支持 --no-cache 禁用缓存，直接从 mootdx 拉取。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# noqa: E402 — sys.path must be set before these imports
from statistics import mean as _mean  # noqa: E402

from sagent.config import load_config  # noqa: E402
from sagent.data import AStockDataMarketData  # noqa: E402
from sagent.kline import describe_stock  # noqa: E402
from sagent.llm import judge_sector, judge_stock  # noqa: E402
from sagent.models import Decision, KlineDescription  # noqa: E402
from sagent.portfolio import PortfolioStore, monitor_positions  # noqa: E402
from sagent.sector import summarize_sectors, validate_mainline_sectors  # noqa: E402


def _scan_all_days_from_cache(
    all_stocks: list,
    bars_map: dict[str, list],
    scan_days: int,
    data=None,
) -> tuple[list[dict], int, int, int, int]:
    """从预加载的 bars_map 中扫描多个信号日，复用数据。

    核心优化：bars_map 只加载一次，多日扫描全部复用，零网络请求。

    Returns:
        (candidates, skipped_st, skipped_amount, skipped_bars, total_scanned)
    """
    candidates: list[dict] = []
    skipped_st = 0
    skipped_amount = 0
    skipped_bars = 0
    total_scanned = 0

    for stock in all_stocks:
        name = stock.name
        symbol = stock.symbol

        if "ST" in name or "*ST" in name:
            skipped_st += 1
            continue

        bars = bars_map.get(symbol, [])
        if not bars:
            skipped_bars += 1
            continue

        total_scanned += 1

        # 对每个 offset 尝试扫描
        for offset in range(scan_days):
            min_bars = 260 + offset
            if len(bars) < min_bars:
                if offset == 0:
                    skipped_bars += 1
                continue

            end_idx = len(bars) - offset
            working_bars = bars[:end_idx]

            # 成交额过滤：20 日均成交额 >= 1 亿
            amounts_20d = [b.amount for b in working_bars[-20:]]
            avg_amount = _mean(amounts_20d) if amounts_20d else 0
            if avg_amount < 100_000_000:
                if offset == 0:
                    skipped_amount += 1
                continue

            closes = [b.close for b in working_bars]
            current = closes[-1]
            ma250 = _mean(closes[-250:])
            recent_60 = closes[-60:]
            low_60 = min(recent_60)
            high_60 = max(recent_60)
            rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
            pullback = (high_60 - min(closes[-30:])) / max(high_60 - low_60, 0.01)
            recent_rebound = closes[-1] > closes[-2] > closes[-3]
            breakout = closes[-1] > max(closes[-8:-1])

            reasons: list[str] = []
            if current > ma250:
                reasons.append("价格位于250日均线之上")
            if rise_60d >= 0.5:
                reasons.append("60日内涨幅达到主升浪阈值")
            if 0.15 <= pullback <= 0.5:
                reasons.append("回撤处于健康区间")
            if recent_rebound and breakout:
                reasons.append("突破短期回调趋势")

            if len(reasons) == 4:
                pullback_low = min(closes[-30:])
                risk = current - pullback_low
                reward = high_60 - current
                risk_reward = reward / risk if risk > 0 else 0.0

                description = describe_stock(symbol, working_bars)

                # 获取行业归属（优先百度股市通，回退 AKShare）
                industry = "未知"
                if data is not None:
                    try:
                        blocks = data.concept_blocks(symbol)
                        industry = blocks.get("industry", "未知")
                    except Exception:
                        pass
                if industry == "未知":
                    try:
                        import akshare as ak

                        df = ak.stock_individual_info_em(symbol=symbol)
                        for _, row in df.iterrows():
                            if row.get("item") == "行业":
                                industry = str(row.get("value", "未知"))
                                break
                    except Exception:
                        pass

                signal_date = working_bars[-1].date
                candidates.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "sector": industry,
                        "signal_date": signal_date,
                        "current": round(current, 2),
                        "ma250": round(ma250, 2),
                        "rise_60d": round(rise_60d, 4),
                        "pullback_ratio": round(pullback, 4),
                        "breakout": breakout,
                        "risk_reward_ratio": round(risk_reward, 2),
                        "key_low": description.key_low,
                        "stop_loss_price": description.risk_price,
                        "kline_description": description.text,
                        "kline_fields": description.fields,
                        "screening_reasons": reasons,
                    }
                )
                print(
                    f"  * 候选：{symbol} {name} "
                    f"价格 {current:.2f} 涨幅 {rise_60d:.1%} 日期 {signal_date}",
                    file=sys.stderr,
                )

    return candidates, skipped_st, skipped_amount, skipped_bars, total_scanned


def _deduplicate_candidates(all_candidates: list[dict]) -> list[dict]:
    """多日候选去重：同一股票保留最近的信号日。"""
    seen: dict[str, dict] = {}
    for c in all_candidates:
        sym = c["symbol"]
        if sym not in seen or c["signal_date"] > seen[sym]["signal_date"]:
            seen[sym] = c
    # 标记出现天数
    sym_counts = Counter(c["symbol"] for c in all_candidates)
    for c in seen.values():
        c["signal_days"] = sym_counts[c["symbol"]]
    return list(seen.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 量化扫描 + LLM 判断")
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="扫描近 N 个交易日（默认 1，即仅当天）",
    )
    parser.add_argument(
        "--cache",
        type=str,
        default=None,
        help="缓存数据库路径（默认 data/bars.db）",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="禁用缓存，直接从 mootdx 拉取",
    )
    args = parser.parse_args()

    t_total_start = time.perf_counter()

    config_path = ROOT / "config" / "default.json"
    portfolio_path = ROOT / "portfolio.json"

    config = load_config(config_path, env=dict(os.environ))
    model_name = config.models.default_judgement_model

    # ---------------------------------------------------------------
    # Phase 1: 获取股票列表
    # ---------------------------------------------------------------
    print("正在连接通达信行情服务器...", file=sys.stderr)
    data = AStockDataMarketData()

    print("正在获取 A 股列表...", file=sys.stderr)
    t0 = time.perf_counter()
    all_stocks = data.stocks()
    t_list = time.perf_counter() - t0
    print(f"获取到 {len(all_stocks)} 只股票 ({t_list:.2f}s)", file=sys.stderr)

    symbols = [s.symbol for s in all_stocks]

    scan_days = min(args.days, 20)

    # ---------------------------------------------------------------
    # Phase 2: 加载 K 线数据（缓存 or 直连）
    # ---------------------------------------------------------------
    t0 = time.perf_counter()
    bars_map: dict[str, list] = {}

    use_cache = not args.no_cache
    cache_path = Path(args.cache) if args.cache else ROOT / "data" / "bars.db"

    if use_cache:
        try:
            from sagent.cache import LocalBarCache

            print(f"正在初始化本地缓存 ({cache_path})...", file=sys.stderr)
            cache = LocalBarCache(cache_path)
            cache_stats = cache.stats()
            print(
                f"缓存状态：{cache_stats['total_symbols']} 只股票 "
                f"{cache_stats['total_rows']} 行 "
                f"({cache_stats['db_size_mb']} MB) "
                f"日期范围 {cache_stats.get('date_min', '?')} ~ {cache_stats.get('date_max', '?')}",
                file=sys.stderr,
            )

            # 增量补缺
            print("正在检查增量更新...", file=sys.stderr)
            t1 = time.perf_counter()
            ensure_result = cache.ensure_symbols(symbols, min_bars=250)
            t_ensure = time.perf_counter() - t1
            new_bars = sum(v for v in ensure_result.values() if v > 0)
            updated_count = sum(1 for v in ensure_result.values() if v > 0)
            print(
                f"增量更新完成：{updated_count} 只股票有新数据，"
                f"共 {new_bars} 行 ({t_ensure:.2f}s)",
                file=sys.stderr,
            )

            # 批量读取全部 K 线
            print("正在从缓存加载 K 线数据...", file=sys.stderr)
            t1 = time.perf_counter()
            bars_map = cache.bulk_daily_bars(symbols)
            t_load = time.perf_counter() - t1
            loaded_count = sum(1 for v in bars_map.values() if v)
            print(
                f"加载完成：{loaded_count} 只股票 ({t_load:.2f}s)",
                file=sys.stderr,
            )

            cache.close()
        except Exception as e:
            print(f"缓存初始化失败，降级为直连模式：{e}", file=sys.stderr)
            use_cache = False

    if not use_cache:
        # 直连模式：逐只下载
        print("直连模式：逐只下载 K 线...", file=sys.stderr)
        for i, stock in enumerate(all_stocks):
            if (i + 1) % 500 == 0:
                print(f"  下载进度: {i + 1}/{len(all_stocks)}", file=sys.stderr)
            try:
                bars = data.daily_bars(stock.symbol)
                if bars:
                    bars_map[stock.symbol] = bars
            except Exception:
                pass

    t_data = time.perf_counter() - t0
    print(f"K 线数据准备完成 ({t_data:.2f}s)", file=sys.stderr)

    # ---------------------------------------------------------------
    # Phase 3: 扫描候选股（复用 bars_map）
    # ---------------------------------------------------------------
    print(
        f"\n开始扫描 {scan_days} 日信号（{len(bars_map)} 只股票有数据）...",
        file=sys.stderr,
    )
    t0 = time.perf_counter()
    all_candidates, skipped_st, skipped_amount, skipped_bars, total_scanned = (
        _scan_all_days_from_cache(all_stocks, bars_map, scan_days, data=data)
    )
    t_scan = time.perf_counter() - t0

    candidates = _deduplicate_candidates(all_candidates)
    print(
        f"\n扫描完成 ({t_scan:.2f}s)：{len(all_candidates)} 个信号 "
        f"（去重后 {len(candidates)} 个候选）| "
        f"ST跳过 {skipped_st} | 金额不足 {skipped_amount} | K线不足 {skipped_bars}",
        file=sys.stderr,
    )

    # ---------------------------------------------------------------
    # Phase 4: 板块数据
    # ---------------------------------------------------------------
    print("正在获取板块数据...", file=sys.stderr)
    t0 = time.perf_counter()
    sector_decisions: dict[str, dict] = {}
    try:
        snapshots = data.sector_snapshots()

        class _SectorData:
            def sector_snapshots(self):
                return snapshots

        summaries = summarize_sectors(_SectorData())
        validations = validate_mainline_sectors(summaries)
        for _name, v in validations.items():
            sector_decision = judge_sector(v, model=model_name)
            sector_decisions[v.sector] = {
                "sector": v.sector,
                "level": v.level,
                "rules": v.rules,
                "reasons": v.reasons,
                "needs_llm": v.needs_llm,
                "judgment": {
                    "action": sector_decision.action,
                    "reason": sector_decision.reason,
                    "model": sector_decision.model,
                    "confidence": sector_decision.confidence,
                },
            }
    except Exception as e:
        print(f"板块数据获取失败：{e}", file=sys.stderr)
    t_sector = time.perf_counter() - t0
    print(f"板块数据完成 ({t_sector:.2f}s)", file=sys.stderr)

    # ---------------------------------------------------------------
    # Phase 5: LLM 判断
    # ---------------------------------------------------------------
    print("正在执行 LLM 判断...", file=sys.stderr)
    t0 = time.perf_counter()
    for c in candidates:
        sector_name = c.get("sector", "未知")
        sd_action = "主线"
        sd_reason = "无板块数据，默认主线"
        sd_confidence = 0.5
        for _sname, sd in sector_decisions.items():
            if sector_name == sd["sector"]:
                sd_action = sd["judgment"]["action"]
                sd_reason = sd["judgment"]["reason"]
                sd_confidence = sd["judgment"]["confidence"]
                break

        sector_d = Decision(
            action=sd_action,
            reason=sd_reason,
            model=model_name,
            confidence=sd_confidence,
        )
        kline_desc = KlineDescription(
            symbol=c["symbol"],
            text=c["kline_description"],
            key_low=c["key_low"],
            risk_price=c["stop_loss_price"],
            fields=c["kline_fields"],
        )
        stock_decision = judge_stock(kline_desc, sector_d, model=model_name)

        c["llm_judgment"] = {
            "action": stock_decision.action,
            "reason": stock_decision.reason,
            "model": stock_decision.model,
            "confidence": stock_decision.confidence,
            "key_low": stock_decision.key_low,
            "invalid_condition": stock_decision.invalid_condition,
        }
        print(
            f"  {c['symbol']} {c['name']}: {stock_decision.action} "
            f"(置信度 {stock_decision.confidence:.0%})",
            file=sys.stderr,
        )
    t_llm = time.perf_counter() - t0
    print(f"LLM 判断完成 ({t_llm:.2f}s)", file=sys.stderr)

    # ---------------------------------------------------------------
    # Phase 6: 持仓监控
    # ---------------------------------------------------------------
    portfolio = PortfolioStore(portfolio_path).load_or_create()
    current_prices: dict[str, float] = {}
    for position in portfolio.positions:
        pos_bars = bars_map.get(position.symbol, [])
        if pos_bars:
            current_prices[position.symbol] = pos_bars[-1].close
    portfolio_suggestions = monitor_positions(
        portfolio, current_prices, trend_broken={}
    )

    t_total = time.perf_counter() - t_total_start

    # ---------------------------------------------------------------
    # 输出
    # ---------------------------------------------------------------
    result = {
        "step": "scan_complete",
        "data_source": f"mootdx + AKShare（{'缓存模式' if use_cache else '直连模式'}）",
        "scan_days": scan_days,
        "judgement_model": model_name,
        "fallback_models": config.models.optional_judgement_models,
        "timing": {
            "total_sec": round(t_total, 2),
            "data_load_sec": round(t_data, 2),
            "scan_sec": round(t_scan, 2),
            "sector_sec": round(t_sector, 2),
            "llm_sec": round(t_llm, 2),
            "cache_enabled": use_cache,
        },
        "stock_pool": {
            "total_listed": len(all_stocks),
            "scanned": total_scanned,
            "skipped_st": skipped_st,
            "skipped_low_amount": skipped_amount,
            "skipped_insufficient_bars": skipped_bars,
        },
        "candidates": candidates,
        "sectors": list(sector_decisions.values()),
        "portfolio": {
            "positions": [asdict(p) for p in portfolio.positions],
            "suggestions": [asdict(s) for s in portfolio_suggestions],
            "cash": portfolio.cash,
            "weekly_open_count": portfolio.weekly_open_count,
            "week_id": portfolio.week_id,
        },
        "next_step": "apply_decision",
        "warning": "仅作研究和辅助分析，不构成投资建议。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
