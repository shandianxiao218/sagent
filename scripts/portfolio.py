#!/usr/bin/env python3
"""本地 portfolio.json 状态入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_PORTFOLIO = {
    "cash": 0,
    "positions": [],
    "weekly_open_count": 0,
    "trade_history": [],
    "notes": "骨架阶段的初始状态。后续 issue 会实现真实资金、持仓和交易历史管理。",
}


def load_or_init(path: Path) -> dict:
    if not path.exists():
        return DEFAULT_PORTFOLIO.copy()
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent portfolio 状态工具")
    parser.add_argument("command", choices=["check", "init"], help="操作")
    parser.add_argument("--path", default="portfolio.json", help="portfolio 文件路径")
    args = parser.parse_args()

    path = Path(args.path)
    data = load_or_init(path)

    if args.command == "init" and not path.exists():
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"path": str(path), "exists": path.exists(), "portfolio": data}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
