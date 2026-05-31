#!/usr/bin/env python3
"""单只股票 K 线描述入口。

当前返回 mock 描述。后续 issue 会把 AKShare K 线、均线、成交量、关键低点转成 LLM 可读描述。
"""

from __future__ import annotations

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description="生成股票 K 线自然语言描述")
    parser.add_argument("--symbol", required=True, help="股票代码")
    parser.add_argument("--mock", action="store_true", help="返回 mock 描述")
    args = parser.parse_args()

    result = {
        "symbol": args.symbol,
        "mode": "mock",
        "description": "mock：该标的处于长期均线之上，近期出现回调、缩量整理，并尝试突破短期回调趋势线。",
        "llm_instruction": "请默认使用 GLM5.1 判断趋势、回调、突破、关键低点；如配置指定，可切换 GPT-5.5。",
        "warning": "骨架阶段尚未接入真实 K 线数据。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
