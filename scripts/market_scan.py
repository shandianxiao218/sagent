#!/usr/bin/env python3
"""市场扫描入口。"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FixtureMarketData = importlib.import_module("sagent.data").FixtureMarketData
run_scan = importlib.import_module("sagent.scan").run_scan


def build_mock_result() -> dict:
    return {
        "trade_date": date.today().isoformat(),
        "mode": "mock",
        "judgement_model": "GLM5.1",
        "candidates": [
            {
                "symbol": "000001",
                "name": "示例股票",
                "sector": "示例板块",
                "action": "观察",
                "reason": "mock：价格位于长期均线上方，近期回调整理后出现突破迹象。",
                "risk": "mock：需要后续接入真实 K 线和板块数据验证。",
            }
        ],
        "portfolio_suggestions": [],
        "warning": "当前为 mock 输出，仅作研究和辅助分析，不构成投资建议。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 市场扫描")
    parser.add_argument("--mock", action="store_true", help="返回 mock 数据")
    parser.add_argument("--fixture", help="使用本地 fixture 数据运行完整无网络流程")
    parser.add_argument(
        "--portfolio", default="portfolio.json", help="portfolio 文件路径"
    )
    parser.add_argument("--config", default="config/default.json", help="配置文件路径")
    args = parser.parse_args()

    if args.fixture:
        result = run_scan(
            data=FixtureMarketData(Path(args.fixture)),
            portfolio_path=Path(args.portfolio),
            config_path=Path(args.config),
            env=dict(os.environ),
        )
    else:
        result = build_mock_result()
        if not args.mock:
            result["warning"] = (
                "未指定 --fixture，当前返回 mock；真实 AKShare 接入由后续运行环境提供。"
            )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
