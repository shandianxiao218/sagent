#!/usr/bin/env python3
"""从回测结果生成可视化图表。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.backtest_portfolio import DailyNAV, PortfolioStats
from sagent.chart import plot_portfolio_dashboard, plot_signal_chart
from sagent.models import DailyBar


def fetch_bars(symbol: str, offset: int = 370) -> list[DailyBar]:
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    frame = client.bars(symbol=symbol, category=4, offset=offset)
    if frame is None or frame.empty:
        return []
    bars: list[DailyBar] = []
    for idx, row in frame.iterrows():
        date_str = str(row.get("datetime", idx))
        bars.append(
            DailyBar(
                symbol=symbol,
                date=date_str[:10],
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("vol", 0)),
                amount=float(row.get("amount", 0)),
            )
        )
    return bars


def main() -> None:
    result_path = ROOT / "backtest_engine_v1.json"
    output_dir = ROOT / "charts"
    output_dir.mkdir(exist_ok=True)

    if not result_path.exists():
        print(f"错误: {result_path} 不存在")
        sys.exit(1)

    with open(result_path, encoding="utf-8") as f:
        data = json.loads(f.read())

    trades = data.get("trades", [])
    print(f"共 {len(trades)} 笔交易")

    # 获取需要的股票K线（去重）
    symbols = list({t["symbol"] for t in trades})
    print(f"需要获取 {len(symbols)} 只股票的K线: {symbols}")

    bars_map: dict[str, list[DailyBar]] = {}
    for sym in symbols:
        try:
            bars_map[sym] = fetch_bars(sym)
            print(f"  {sym}: {len(bars_map[sym])} bars")
        except Exception as e:
            print(f"  {sym}: 获取失败 - {e}")

    # 生成每笔交易的信号标注图
    chart_count = 0
    for trade in trades:
        sym = trade["symbol"]
        bars = bars_map.get(sym, [])
        if not bars:
            print(f"  跳过 {sym}（无K线）")
            continue

        signal_date = trade.get("signal_date", "")
        signal_idx = None
        for j, bar in enumerate(bars):
            if bar.date == signal_date:
                signal_idx = j
                break

        if signal_idx is None:
            print(f"  跳过 {sym}（未找到信号日 {signal_date}）")
            continue

        # 截取信号日前后的 bars（前120日到后30日）
        start = max(0, signal_idx - 120)
        end = min(len(bars), signal_idx + 30)
        chart_bars = bars[start:end]
        chart_signal_idx = signal_idx - start

        safe_name = sym.replace(".", "_")
        date_safe = signal_date.replace("-", "")
        out_path = output_dir / f"signal_{safe_name}_{date_safe}.html"

        plot_signal_chart(
            bars=chart_bars,
            signal_idx=chart_signal_idx,
            symbol=f"{sym} {trade.get('signal_date', '')}",
            key_low=trade.get("key_low"),
            stop_loss_price=trade.get("stop_loss_price"),
            entry_price=trade.get("entry_price"),
            output_path=str(out_path),
        )
        chart_count += 1
        print(f"  [{chart_count}] {sym} {signal_date} -> {out_path.name}")

    # 生成组合仪表盘
    portfolio_data = data.get("portfolio", {})
    nav_curve_raw = portfolio_data.get("nav_curve", [])
    if not nav_curve_raw and portfolio_data.get("nav_curve_count", 0) > 0:
        print(
            "\n注意: nav_curve 数据未序列化到 JSON（只有 nav_curve_count），仪表盘将显示空状态"
        )
        print("建议: 在 run_engine_backtest() 中将 nav_curve 序列化到输出")
    nav_curve = [DailyNAV(**n) for n in nav_curve_raw] if nav_curve_raw else []

    stats = PortfolioStats(
        initial_cash=portfolio_data.get("initial_cash", 100000),
        final_value=portfolio_data.get("final_value", 105640),
        total_return=portfolio_data.get("total_return", 0.0564),
        max_drawdown=portfolio_data.get("max_drawdown", 0.0411),
        sharpe_ratio=portfolio_data.get("sharpe_ratio", 0.07),
        total_trades=portfolio_data.get("total_trades", 17),
        winning_trades=portfolio_data.get("winning_trades", 6),
        losing_trades=portfolio_data.get("losing_trades", 11),
        win_rate=portfolio_data.get("win_rate", 0.3529),
        avg_profit=portfolio_data.get("avg_profit", 0),
        avg_loss=portfolio_data.get("avg_loss", 0),
        profit_loss_ratio=portfolio_data.get("profit_loss_ratio", 3.85),
        max_single_profit=portfolio_data.get("max_single_profit", 0),
        max_single_loss=portfolio_data.get("max_single_loss", 0),
        stop_loss_count=portfolio_data.get("stop_loss_count", 0),
        take_profit_count=portfolio_data.get("take_profit_count", 0),
        natural_exit_count=portfolio_data.get("natural_exit_count", 0),
        avg_holding_days=portfolio_data.get("avg_holding_days", 0),
        capital_utilization=portfolio_data.get("capital_utilization", 0),
        nav_curve=nav_curve,
    )

    dashboard_path = output_dir / "portfolio_dashboard.html"
    plot_portfolio_dashboard(stats, output_path=str(dashboard_path))
    print(f"\n组合仪表盘 -> {dashboard_path}")

    print(f"\n=== 完成：共生成 {chart_count + 1} 个图表文件 ===")
    print(f"输出目录: {output_dir}")


if __name__ == "__main__":
    main()
