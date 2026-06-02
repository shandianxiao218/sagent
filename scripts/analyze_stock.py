#!/usr/bin/env python3
"""单只股票 K 线描述入口。使用 mootdx 真实行情数据。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.data import AStockDataMarketData
from sagent.kline import describe_stock


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="生成股票 K 线自然语言描述")
    parser.add_argument("--symbol", required=True, help="股票代码")
    args = parser.parse_args()

    print(f"正在获取 {args.symbol} 真实行情...", file=sys.stderr)
    data = AStockDataMarketData()
    bars = data.daily_bars(args.symbol)
    if not bars:
        result = {
            "symbol": args.symbol,
            "error": f"无法获取 {args.symbol} 的 K 线数据，请检查代码是否正确。",
            "warning": "仅作研究和辅助分析，不构成投资建议。",
        }
    else:
        description = describe_stock(args.symbol, bars)
        result = {
            "symbol": description.symbol,
            "data_source": "mootdx（真实行情）",
            "bars_count": len(bars),
            "latest_date": bars[-1].date,
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
