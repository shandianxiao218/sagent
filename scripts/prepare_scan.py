#!/usr/bin/env python3
"""准备扫描数据：量化粗筛 + K 线描述 + 板块验证 + 持仓监控。

使用 mootdx + AKShare 真实行情数据。
输出结构化 JSON，供 pi agent 做 LLM 判断。
不做任何 LLM 调用。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from statistics import mean as _mean

from sagent.config import load_config
from sagent.data import AStockDataMarketData
from sagent.kline import describe_stock
from sagent.llm import build_sector_prompt
from sagent.portfolio import PortfolioStore, monitor_positions
from sagent.sector import summarize_sectors, validate_mainline_sectors


def main() -> None:
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

    # 2. 逐只获取 K 线，边取边做技术候选筛选
    #    注：AKShare stock_info_a_code_name() 只返回代码和名称，
    #    缺少 avg_amount_20d/is_st/listing_days 等字段，
    #    所以不能预先用 filter_stock_pool 过滤，
    #    改为在获取 K 线后根据成交额和名称做运行时过滤。
    print("正在扫描技术形态...", file=sys.stderr)
    candidates = []
    total = len(all_stocks)
    skipped_st = 0
    skipped_amount = 0
    skipped_bars = 0

    for i, stock in enumerate(all_stocks):
        if (i + 1) % 100 == 0:
            print(f"  已扫描 {i+1}/{total}...", file=sys.stderr)
        try:
            # ST 过滤（根据名称）
            name = stock.name
            symbol = stock.symbol
            if "ST" in name or "*ST" in name:
                skipped_st += 1
                continue

            bars = data.daily_bars(symbol)
            if len(bars) < 260:
                skipped_bars += 1
                continue

            # 成交额过滤：20 日均成交额 >= 1 亿
            amounts_20d = [b.amount for b in bars[-20:]]
            avg_amount = _mean(amounts_20d) if amounts_20d else 0
            if avg_amount < 100_000_000:
                skipped_amount += 1
                continue

            closes = [b.close for b in bars]
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

                description = describe_stock(symbol, bars)

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

                candidates.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "sector": industry,
                        "current": round(current, 2),
                        "ma250": round(ma250, 2),
                        "rise_60d": round(rise_60d, 4),
                        "pullback_ratio": round(pullback, 4),
                        "breakout": breakout,
                        "risk_reward_ratio": round(risk_reward, 2),
                        "key_low": description.key_low,
                        "kline_description": description.text,
                        "kline_fields": description.fields,
                        "reasons": reasons,
                    }
                )
                print(
                    f"  * 发现候选：{symbol} {name} "
                    f"价格 {current:.2f} 涨幅 {rise_60d:.1%} R/R {risk_reward:.2f}",
                    file=sys.stderr,
                )
        except Exception:
            continue

    print(
        f"\n扫描完成：{len(candidates)} 个候选 | "
        f"ST跳过 {skipped_st} | 金额不足 {skipped_amount} | K线不足 {skipped_bars}",
        file=sys.stderr,
    )

    # 4. 板块数据
    print("正在获取板块数据...", file=sys.stderr)
    try:
        snapshots = data.sector_snapshots()

        class _SectorData:
            def sector_snapshots(self):
                return snapshots

        summaries = summarize_sectors(_SectorData())
        validations = validate_mainline_sectors(summaries)
        sector_details = []
        for _name, v in validations.items():
            sector_details.append(
                {
                    "sector": v.sector,
                    "level": v.level,
                    "rules": v.rules,
                    "reasons": v.reasons,
                    "needs_llm": v.needs_llm,
                    "prompt_for_llm": build_sector_prompt(v) if v.needs_llm else None,
                }
            )
    except Exception as e:
        print(f"板块数据获取失败：{e}", file=sys.stderr)
        sector_details = []

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
    portfolio_suggestions = monitor_positions(portfolio, current_prices, trend_broken={})

    # 6. 输出
    result = {
        "step": "prepare_scan",
        "data_source": "mootdx + AKShare（真实行情）",
        "judgement_model": model_name,
        "fallback_models": config.models.optional_judgement_models,
        "stock_pool": {
            "total_listed": len(all_stocks),
            "scanned": total,
            "skipped_st": skipped_st,
            "skipped_low_amount": skipped_amount,
            "skipped_insufficient_bars": skipped_bars,
        },
        "candidates": candidates,
        "sectors": sector_details,
        "portfolio": {
            "positions": [asdict(p) for p in portfolio.positions],
            "suggestions": [asdict(s) for s in portfolio_suggestions],
            "cash": portfolio.cash,
            "weekly_open_count": portfolio.weekly_open_count,
            "week_id": portfolio.week_id,
        },
        "next_step": "pi_agent_judge",
        "instructions": (
            "请使用 a-share-main-trend skill，对每个 candidate 做板块主线判断和个股形态判断。"
            "对 needs_llm=True 的板块，用 LLM 判断是主线/弱主线/非主线。"
            "对每个候选股，根据板块判断结果和 K 线描述，判断买入/观察/放弃。"
            "输出 JSON 格式的判断结果，供 apply_decision 写入 portfolio。"
        ),
        "warning": "仅作研究和辅助分析，不构成投资建议。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
