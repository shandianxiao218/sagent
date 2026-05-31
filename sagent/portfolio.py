from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .models import BuyResult, Portfolio, Position, PositionSuggestion


class PortfolioStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_or_create(self, initial_cash: float = 0) -> Portfolio:
        if not self.path.exists():
            return Portfolio(cash=initial_cash)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"portfolio.json 损坏：{error}") from error
        positions = [Position(**item) for item in raw.get("positions", [])]
        return Portfolio(
            cash=float(raw.get("cash", initial_cash)),
            positions=positions,
            weekly_open_count=int(raw.get("weekly_open_count", 0)),
            week_id=raw.get("week_id", ""),
            trade_history=list(raw.get("trade_history", [])),
        )

    def save(self, portfolio: Portfolio) -> None:
        self.path.write_text(
            json.dumps(asdict(portfolio), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _week_id(trade_date: str) -> str:
    year, week, _ = date.fromisoformat(trade_date).isocalendar()
    return f"{year}-W{week:02d}"


def confirm_buy(
    portfolio: Portfolio,
    symbol: str,
    name: str,
    sector: str,
    buy_price: float,
    key_low: float,
    trade_date: str,
    position_ratio: float = 0.1,
    max_weekly_open: int = 2,
) -> BuyResult:
    week = _week_id(trade_date)
    if portfolio.week_id != week:
        portfolio.week_id = week
        portfolio.weekly_open_count = 0
    if portfolio.weekly_open_count >= max_weekly_open:
        raise ValueError(f"每周最多新开仓 {max_weekly_open} 次")
    amount = round(portfolio.cash * position_ratio, 2)
    quantity = int(amount // buy_price)
    amount = round(quantity * buy_price, 2)
    position = Position(
        symbol=symbol,
        name=name,
        sector=sector,
        buy_price=buy_price,
        quantity=quantity,
        amount=amount,
        key_low=key_low,
        stop_loss_price=max(round(buy_price * 0.95, 2), key_low),
        trade_date=trade_date,
    )
    portfolio.positions.append(position)
    portfolio.cash -= amount
    portfolio.weekly_open_count += 1
    portfolio.trade_history.append(
        {
            "action": "确认买入",
            "symbol": symbol,
            "date": trade_date,
            "price": buy_price,
            "quantity": quantity,
            "amount": amount,
            "key_low": key_low,
        }
    )
    return BuyResult(portfolio=portfolio, position=position)


def monitor_positions(
    portfolio: Portfolio,
    current_prices: dict[str, float],
    trend_broken: dict[str, bool],
) -> list[PositionSuggestion]:
    suggestions: list[PositionSuggestion] = []
    for position in portfolio.positions:
        current = current_prices.get(position.symbol, position.buy_price)
        risk_per_share = max(
            position.buy_price - position.key_low, position.buy_price * 0.05, 0.01
        )
        r_multiple = (current - position.buy_price) / risk_per_share
        if current < position.key_low:
            suggestions.append(
                PositionSuggestion(
                    position.symbol, "清仓", "跌破买点前关键低点，触发止损。"
                )
            )
        elif current <= position.buy_price * 0.95:
            suggestions.append(
                PositionSuggestion(
                    position.symbol, "清仓", "单笔亏损达到5%，触发硬性止损。"
                )
            )
        elif trend_broken.get(position.symbol):
            suggestions.append(
                PositionSuggestion(
                    position.symbol, "清仓", "趋势破坏，剩余仓位全部退出。"
                )
            )
        elif not position.half_taken and r_multiple >= 2.5:
            sell_quantity = int((position.remaining_quantity or position.quantity) // 2)
            position.half_taken = True
            position.remaining_quantity = (
                position.remaining_quantity or position.quantity
            ) - sell_quantity
            portfolio.trade_history.append(
                {
                    "action": "半仓止盈建议",
                    "symbol": position.symbol,
                    "price": current,
                    "quantity": sell_quantity,
                    "r_multiple": round(r_multiple, 2),
                }
            )
            suggestions.append(
                PositionSuggestion(
                    position.symbol,
                    "减仓",
                    "盈亏比达到2.5R-3R，建议止盈一半，并已记录半仓止盈状态。",
                )
            )
        else:
            suggestions.append(
                PositionSuggestion(
                    position.symbol, "持有", "未触发止损、止盈或趋势破坏条件。"
                )
            )
    return suggestions


def portfolio_to_dict(portfolio: Portfolio) -> dict[str, Any]:
    return asdict(portfolio)
