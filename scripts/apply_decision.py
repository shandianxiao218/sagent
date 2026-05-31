#!/usr/bin/env python3
"""接收 pi agent 的 JSON 判断结果，写入 portfolio + 可选飞书推送。

输入：stdin 或 --decisions-file，JSON 格式：
{
  "judgements": [
    {
      "symbol": "000001",
      "name": "样例科技",
      "sector": "AI应用",
      "action": "买入",
      "reason": "...",
      "key_low": 13.29,
      "risk": "...",
      "confidence": 0.85
    }
  ],
  "portfolio_actions": [
    {"symbol": "000001", "action": "减仓", "reason": "盈亏比达到2.5R"}
  ]
}
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

portfolio_mod = importlib.import_module("sagent.portfolio")
config_mod = importlib.import_module("sagent.config")
notify_mod = importlib.import_module("sagent.notify")


def main() -> None:
    parser = argparse.ArgumentParser(description="sagent 应用判断结果")
    parser.add_argument(
        "--portfolio", default="portfolio.json", help="portfolio 文件路径"
    )
    parser.add_argument("--config", default="config/default.json", help="配置文件路径")
    parser.add_argument("--decisions-file", help="JSON 文件路径（不指定则读 stdin）")
    parser.add_argument("--trade-date", help="交易日期 YYYY-MM-DD")
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100_000,
        help="初始资金（新建 portfolio 时）",
    )
    args = parser.parse_args()

    config = config_mod.load_config(Path(args.config), env=dict(os.environ))
    store = portfolio_mod.PortfolioStore(Path(args.portfolio))
    portfolio = store.load_or_create(initial_cash=args.initial_cash)

    # 读取判断结果
    if args.decisions_file:
        raw = json.loads(Path(args.decisions_file).read_text(encoding="utf-8"))
    else:
        raw = json.loads(sys.stdin.read())

    judgements = raw.get("judgements", [])
    portfolio_actions = raw.get("portfolio_actions", [])
    trade_date = args.trade_date or raw.get("trade_date", "")

    results: list[dict] = []
    errors: list[str] = []

    # 处理买入
    for judgement in judgements:
        if judgement.get("action") != "买入":
            results.append(
                {
                    "symbol": judgement["symbol"],
                    "action": judgement["action"],
                    "status": "skipped",
                }
            )
            continue
        try:
            buy_result = portfolio_mod.confirm_buy(
                portfolio=portfolio,
                symbol=judgement["symbol"],
                name=judgement.get("name", ""),
                sector=judgement.get("sector", ""),
                buy_price=0,  # 由 pi agent 补充或从 K 线取 close
                key_low=judgement.get("key_low", 0),
                trade_date=trade_date,
                position_ratio=config.scan.position_size_ratio,
                max_weekly_open=config.scan.max_new_positions_per_week,
            )
            results.append(
                {
                    "symbol": judgement["symbol"],
                    "action": "买入",
                    "status": "success",
                    "position": {
                        "quantity": buy_result.position.quantity,
                        "amount": buy_result.position.amount,
                        "stop_loss": buy_result.position.stop_loss_price,
                    },
                }
            )
        except ValueError as error:
            errors.append(f"{judgement['symbol']}: {error}")
            results.append(
                {
                    "symbol": judgement["symbol"],
                    "action": "买入",
                    "status": "rejected",
                    "reason": str(error),
                }
            )

    # 保存 portfolio
    store.save(portfolio)

    # 飞书推送
    feishu_result = {"ok": True, "mode": "disabled"}
    if config.push.feishu_enabled and (judgements or portfolio_actions):
        lines = []
        for r in results:
            lines.append(f"{r['symbol']} {r['action']} {r.get('status', '')}")
        for a in portfolio_actions:
            lines.append(f"[持仓] {a['symbol']} {a['action']} {a.get('reason', '')}")
        feishu_result = notify_mod.send_feishu_summary(
            "\n".join(lines), dict(os.environ)
        )

    output = {
        "step": "apply_decision",
        "trade_date": trade_date,
        "results": results,
        "errors": errors,
        "portfolio": {
            "cash": portfolio.cash,
            "positions_count": len(portfolio.positions),
            "weekly_open_count": portfolio.weekly_open_count,
        },
        "feishu": feishu_result,
        "warning": "仅作研究和辅助分析，不构成投资建议。",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
