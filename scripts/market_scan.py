#!/usr/bin/env python3
"""市场扫描入口。

当前是项目骨架阶段：默认返回 mock 数据。后续 issue 会接入 AKShare、股票池预筛、量化技术粗筛和 LLM 精筛。
"""

from __future__ import annotations

import argparse
import json
from datetime import date


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
                "reason": "mock：价格位于长期均线上方，近期回调整理后出现突破迹象。",
                "risk": "mock：需要后续接入真实 K 线和板块数据验证。",
            }
        ],
        "next_steps": [
            "实现 AKShare 数据访问层",
            "实现股票池与流动性预筛",
            "实现量化技术粗筛",
            "接入 GLM5.1 做主线和形态判断",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 市场扫描")
    parser.add_argument("--mock", action="store_true", help="返回 mock 数据")
    args = parser.parse_args()

    if not args.mock:
        # 骨架阶段仍返回 mock，避免误以为已经接入真实行情。
        result = build_mock_result()
        result["warning"] = "当前仍是骨架实现，尚未接入 AKShare。"
    else:
        result = build_mock_result()

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
