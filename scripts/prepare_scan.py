#!/usr/bin/env python3
"""准备扫描数据：量化粗筛 + K 线描述 + LLM 判断 + 板块验证 + 持仓监控。

使用 mootdx + AKShare 真实行情数据。
输出结构化 JSON，包含：
  - 初筛理由和结果（量化指标）
  - LLM 判断后的理由和结果（规则引擎 fallback）
  - 板块验证
  - 持仓监控

支持 --days N 参数扫描近 N 个交易日。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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


def _scan_candidates(
    data: AStockDataMarketData,
    all_stocks: list,
    signal_offset: int = 0,
) -> tuple[list[dict], int, int, int]:
    """扫描候选股。

    Args:
        data: 行情数据源
        all_stocks: 全部 A 股列表
        signal_offset: 信号日偏移量（0=最新日，1=昨日，以此类推）

    Returns:
        (candidates, skipped_st, skipped_amount, skipped_bars)
    """
    candidates = []
    skipped_st = 0
    skipped_amount = 0
    skipped_bars = 0

    for i, stock in enumerate(all_stocks):
        if (i + 1) % 500 == 0:
            print(
                f"  已扫描 {i + 1}/{len(all_stocks)}（偏移 {signal_offset}日）...",
                file=sys.stderr,
            )
        try:
            name = stock.name
            symbol = stock.symbol
            if "ST" in name or "*ST" in name:
                skipped_st += 1
                continue

            bars = data.daily_bars(symbol)
            # 需要 signal_offset + 1 天的数据（offset=0 用到最新日）
            min_bars = 260 + signal_offset
            if len(bars) < min_bars:
                skipped_bars += 1
                continue

            # 取偏移后的数据窗口
            end_idx = len(bars) - signal_offset
            working_bars = bars[:end_idx]

            # 成交额过滤：20 日均成交额 >= 1 亿
            amounts_20d = [b.amount for b in working_bars[-20:]]
            avg_amount = _mean(amounts_20d) if amounts_20d else 0
            if avg_amount < 100_000_000:
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

                # 尝试获取行业归属
                industry = "未知"
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
                    f"  * 发现候选：{symbol} {name} "
                    f"价格 {current:.2f} 涨幅 {rise_60d:.1%} 日期 {signal_date}",
                    file=sys.stderr,
                )
        except Exception:
            continue

    return candidates, skipped_st, skipped_amount, skipped_bars


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
    args = parser.parse_args()

    config_path = ROOT / "config" / "default.json"
    portfolio_path = ROOT / "portfolio.json"

    config = load_config(config_path, env=dict(os.environ))
    model_name = config.models.default_judgement_model

    print("正在连接通达信行情服务器...", file=sys.stderr)
    data = AStockDataMarketData()

    # 1. 获取全部 A 股列表
    print("正在获取 A 股列表...", file=sys.stderr)
    all_stocks = data.stocks()
    print(f"获取到 {len(all_stocks)} 只股票", file=sys.stderr)

    # 2. 逐日扫描（days > 1 时扫描多个信号日）
    all_candidates: list[dict] = []
    total_scanned = len(all_stocks)
    skipped_st = skipped_amount = skipped_bars = 0
    scan_days = min(args.days, 20)  # 最多扫 20 天

    for offset in range(scan_days):
        print(f"\n--- 扫描信号日偏移 {offset}（近 {scan_days} 日中的第 {offset + 1} 天）---", file=sys.stderr)
        day_cands, dst, damt, dbars = _scan_candidates(data, all_stocks, signal_offset=offset)
        all_candidates.extend(day_cands)
        skipped_st += dst
        skipped_amount += damt
        skipped_bars += dbars

    # 去重
    candidates = _deduplicate_candidates(all_candidates)
    print(
        f"\n扫描完成：{len(all_candidates)} 个信号（去重后 {len(candidates)} 个候选）| "
        f"ST跳过 {skipped_st} | 金额不足 {skipped_amount} | K线不足 {skipped_bars}",
        file=sys.stderr,
    )

    # 3. 板块数据
    print("正在获取板块数据...", file=sys.stderr)
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

    # 4. LLM 判断每个候选股
    print("正在执行 LLM 判断...", file=sys.stderr)
    for c in candidates:
        sector_name = c.get("sector", "未知")
        # 找匹配的板块判断
        sd_action = "主线"  # 默认
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

    # 5. 持仓监控
    portfolio = PortfolioStore(portfolio_path).load_or_create()
    current_prices = {}
    for position in portfolio.positions:
        try:
            bars = data.daily_bars(position.symbol)
            if bars:
                current_prices[position.symbol] = bars[-1].close
        except Exception:
            pass
    portfolio_suggestions = monitor_positions(
        portfolio, current_prices, trend_broken={}
    )

    # 6. 输出
    result = {
        "step": "scan_complete",
        "data_source": "mootdx + AKShare（真实行情）",
        "scan_days": scan_days,
        "judgement_model": model_name,
        "fallback_models": config.models.optional_judgement_models,
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
