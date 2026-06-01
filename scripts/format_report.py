#!/usr/bin/env python3
"""将 prepare_scan 的 JSON 输出格式化为表格报告。

用法：
  python scripts/prepare_scan.py --fixture fixtures/market/sample_market.json | python scripts/format_report.py
  python scripts/format_report.py --input scan_result.json
  python scripts/format_report.py --input scan_result.json --format feishu
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

format_mod = importlib.import_module("sagent.format")


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 报告格式化")
    parser.add_argument("--input", help="prepare_scan JSON 文件路径（不指定则读 stdin）")
    parser.add_argument(
        "--format",
        choices=["markdown", "feishu"],
        default="markdown",
        help="输出格式（默认 markdown）",
    )
    args = parser.parse_args()

    if args.input:
        raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        raw = json.loads(sys.stdin.read())

    if args.format == "feishu":
        print(format_mod.format_feishu_text(raw))
    else:
        print(format_mod.format_scan_summary(raw))


if __name__ == "__main__":
    main()
