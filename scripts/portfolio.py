#!/usr/bin/env python3
"""本地 portfolio.json 状态入口。"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

portfolio_module = importlib.import_module("sagent.portfolio")
PortfolioStore = portfolio_module.PortfolioStore
confirm_buy = portfolio_module.confirm_buy


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent portfolio 状态工具")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["check", "init"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--path", default="portfolio.json", help="portfolio 文件路径")
        cmd.add_argument("--cash", type=float, default=0, help="初始化资金")
    buy = sub.add_parser("confirm-buy")
    buy.add_argument("--path", default="portfolio.json")
    buy.add_argument("--cash", type=float, default=100_000)
    buy.add_argument("--symbol", required=True)
    buy.add_argument("--name", required=True)
    buy.add_argument("--sector", required=True)
    buy.add_argument("--buy-price", type=float, required=True)
    buy.add_argument("--key-low", type=float, required=True)
    buy.add_argument("--trade-date", required=True)
    args = parser.parse_args()

    store = PortfolioStore(Path(args.path))
    if args.command == "init":
        portfolio = store.load_or_create(initial_cash=args.cash)
        store.save(portfolio)
        result = {"path": args.path, "exists": True, "portfolio": asdict(portfolio)}
    elif args.command == "check":
        portfolio = store.load_or_create(initial_cash=args.cash)
        result = {
            "path": args.path,
            "exists": Path(args.path).exists(),
            "portfolio": asdict(portfolio),
        }
    else:
        portfolio = store.load_or_create(initial_cash=args.cash)
        result_obj = confirm_buy(
            portfolio,
            symbol=args.symbol,
            name=args.name,
            sector=args.sector,
            buy_price=args.buy_price,
            key_low=args.key_low,
            trade_date=args.trade_date,
        )
        store.save(result_obj.portfolio)
        result = {
            "path": args.path,
            "position": asdict(result_obj.position),
            "portfolio": asdict(result_obj.portfolio),
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
