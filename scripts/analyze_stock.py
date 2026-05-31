#!/usr/bin/env python3
"""单只股票 K 线描述入口。"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FixtureMarketData = importlib.import_module("sagent.data").FixtureMarketData
describe_stock = importlib.import_module("sagent.kline").describe_stock


def main() -> None:
    parser = argparse.ArgumentParser(description="生成股票 K 线自然语言描述")
    parser.add_argument("--symbol", required=True, help="股票代码")
    parser.add_argument("--mock", action="store_true", help="返回 mock 描述")
    parser.add_argument(
        "--fixture",
        default="fixtures/market/sample_market.json",
        help="本地 fixture 数据路径",
    )
    args = parser.parse_args()

    if args.mock:
        result = {
            "symbol": args.symbol,
            "mode": "mock",
            "description": "mock：该标的处于长期均线之上，近期出现回调、缩量整理，并尝试突破短期回调趋势线。",
            "llm_instruction": "请默认使用 GLM5.1 判断趋势、回调、突破、关键低点；如配置指定，可切换 GPT-5.5。",
            "warning": "骨架阶段 mock 输出，不构成投资建议。",
        }
    else:
        data = FixtureMarketData(Path(args.fixture))
        description = describe_stock(args.symbol, data.daily_bars(args.symbol))
        result = {
            "symbol": description.symbol,
            "mode": "fixture",
            "description": description.text,
            "key_low": description.key_low,
            "risk_price": description.risk_price,
            "fields": description.fields,
            "llm_instruction": "请默认使用 GLM5.1 判断趋势、回调、突破、关键低点；如配置指定，可切换 GPT-5.5。",
            "warning": "仅作研究和辅助分析，不构成投资建议。",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
