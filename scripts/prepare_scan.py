#!/usr/bin/env python3
"""准备扫描数据：量化粗筛 + K 线描述 + 板块验证 + 持仓监控。

输出结构化 JSON，供 pi agent 做 LLM 判断。
不做任何 LLM 调用。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

data_mod = importlib.import_module("sagent.data")
kline_mod = importlib.import_module("sagent.kline")
llm_mod = importlib.import_module("sagent.llm")
portfolio_mod = importlib.import_module("sagent.portfolio")
scan_mod = importlib.import_module("sagent.scan")
sector_mod = importlib.import_module("sagent.sector")
technical_mod = importlib.import_module("sagent.technical")
config_mod = importlib.import_module("sagent.config")


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 准备扫描数据")
    parser.add_argument("--fixture", required=True, help="本地 fixture 数据文件路径")
    parser.add_argument(
        "--portfolio", default="portfolio.json", help="portfolio 文件路径"
    )
    parser.add_argument("--config", default="config/default.json", help="配置文件路径")
    args = parser.parse_args()

    data = data_mod.FixtureMarketData(Path(args.fixture))
    config = config_mod.load_config(Path(args.config), env=dict(os.environ))
    portfolio = portfolio_mod.PortfolioStore(Path(args.portfolio)).load_or_create()

    # 1. 股票池过滤
    pool = technical_mod.filter_stock_pool(data.stocks())

    # 2. 量化候选股
    candidates = technical_mod.technical_candidates(data, pool.included)

    # 3. K 线描述（给 pi agent 做形态判断用）
    candidate_details = []
    for candidate in candidates:
        bars = data.daily_bars(candidate.symbol)
        description = kline_mod.describe_stock(candidate.symbol, bars)
        candidate_details.append(
            {
                **asdict(candidate),
                "kline_description": description.text,
                "kline_key_low": description.key_low,
                "kline_risk_price": description.risk_price,
                "kline_fields": description.fields,
            }
        )

    # 4. 板块验证
    sector_summaries = sector_mod.summarize_sectors(data)
    validations = sector_mod.validate_mainline_sectors(sector_summaries)
    sector_details = []
    for _name, validation in validations.items():
        sector_details.append(
            {
                "sector": validation.sector,
                "level": validation.level,
                "rules": validation.rules,
                "reasons": validation.reasons,
                "needs_llm": validation.needs_llm,
                "prompt_for_llm": llm_mod.build_sector_prompt(validation)
                if validation.needs_llm
                else None,
            }
        )

    # 5. 持仓监控
    current_prices = {}
    for position in portfolio.positions:
        bars = data.daily_bars(position.symbol)
        if bars:
            current_prices[position.symbol] = bars[-1].close
    portfolio_suggestions = portfolio_mod.monitor_positions(
        portfolio, current_prices, trend_broken={}
    )

    # 6. 输出
    result = {
        "step": "prepare_scan",
        "trade_date": data.trade_calendar()[-1].date
        if data.trade_calendar()
        else "未知",
        "judgement_model": config.models.default_judgement_model,
        "fallback_models": config.models.optional_judgement_models,
        "stock_pool": {
            "included": [asdict(s) for s in pool.included],
            "excluded": [asdict(e) for e in pool.excluded],
        },
        "candidates": candidate_details,
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
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
