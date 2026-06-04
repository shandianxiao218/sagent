#!/usr/bin/env python3
"""从回测结果生成全部4种可视化图表。

图表类型：
  1. signal_{code}_{date}.html  — 信号标注图（K线+止损/key_low/R=2.5+回调区间）
  2. structure_{code}_{date}.html — 波峰波谷结构图（swing highs/lows + higher lows连线）
  3. lifecycle_{code}_{date}.html — 交易生命周期图（K线+买卖标注 + 逐日R值曲线）
  4. portfolio_dashboard.html   — 组合仪表盘（净值+月度收益+交易分布+统计卡片）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.backtest_portfolio import DailyNAV, PortfolioStats
from sagent.cache import LocalBarCache
from sagent.chart import (
    plot_combined_trade_chart,
    plot_portfolio_dashboard,
)
from sagent.backtest_engine import simulate_trade
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


def _find_signal_idx(bars: list[DailyBar], signal_date: str) -> int | None:
    for j, bar in enumerate(bars):
        if bar.date == signal_date:
            return j
    return None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="从回测 JSON 生成图表")
    parser.add_argument("--input", default=None, help="回测 JSON 文件路径")
    parser.add_argument("--cache", default=None, help="SQLite 缓存路径")
    parser.add_argument("--output-dir", default=None, help="输出目录")
    args = parser.parse_args()

    # 自动查找最新的回测文件
    candidates = [
        "backtest_6m_full.json",
        "backtest_engine_v1.json",
        "backtest_engine_v2.json",
    ]
    result_path = Path(args.input) if args.input else None
    if result_path is None:
        for c in candidates:
            p = ROOT / c
            if p.exists():
                result_path = p
                break
    if result_path is None or not result_path.exists():
        print(f"错误: 未找到回测文件，请用 --input 指定")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "output" / "charts"
    output_dir.mkdir(exist_ok=True)

    with open(result_path, encoding="utf-8") as f:
        data = json.loads(f.read())

    trades = data.get("trades", [])
    end_date = data.get("meta", {}).get("parameters", {}).get("end_date", "2026-05-31")
    print(f"加载 {result_path.name}: {len(trades)} 笔交易")

    # ── 1. 用缓存获取K线 ──────────────────────────────────────
    symbols = list({t["symbol"] for t in trades})
    db_path = Path(args.cache) if args.cache else ROOT / "data" / "bars.db"
    cache = LocalBarCache(db_path)

    print(f"\n[1/4] 从缓存加载 {len(symbols)} 只股票K线 ({db_path})...")
    bars_map: dict[str, list[DailyBar]] = {}
    for sym in symbols:
        bars_map[sym] = cache.daily_bars_up_to(sym, end_date)
    cache.close()
    loaded = sum(1 for v in bars_map.values() if v)
    print(f"  加载 {loaded}/{len(symbols)} 只")

    # ── 1b. 批量获取板块归属（行业+概念）───────────────────
    print(f"\n[1b/4] 获取板块归属...")
    sector_map: dict[str, dict] = {}
    try:
        from sagent.data import _make_concept_blocks

        get_blocks = _make_concept_blocks()
        for sym in symbols:
            try:
                sector_map[sym] = get_blocks(sym)
            except Exception:
                sector_map[sym] = {"industry": "未知", "concepts": []}
        ok_count = sum(
            1 for v in sector_map.values() if v.get("industry", "未知") != "未知"
        )
        print(f"  {ok_count}/{len(symbols)} 只获取成功")
    except Exception as e:
        print(f"  板块获取失败（{e}），将跳过板块信息")

    # ── 2. 合并综合图表（信号+结构+生命周期合一）──────────
    print(f"\n[2/4] 生成综合图表（信号+结构+生命周期合并）...")
    combined_count = 0

    for trade in trades:
        sym = trade["symbol"]
        bars = bars_map.get(sym, [])
        if not bars:
            continue

        signal_date = trade.get("signal_date", "")
        signal_idx = _find_signal_idx(bars, signal_date)
        if signal_idx is None:
            continue

        start = max(0, signal_idx - 120)
        end = min(len(bars), signal_idx + 30)
        chart_bars = bars[start:end]
        chart_signal_idx = signal_idx - start

        # 模拟交易获取完整生命周期
        lifecycle = simulate_trade(bars, signal_idx)

        safe = sym.replace(".", "_")
        dsafe = signal_date.replace("-", "")

        plot_combined_trade_chart(
            bars=chart_bars,
            signal_idx=chart_signal_idx,
            trade=lifecycle,
            key_low=trade.get("key_low"),
            stop_loss_price=trade.get("stop_loss_price"),
            trend_break_ref=trade.get("trend_break_ref"),
            sector_info=sector_map.get(sym),
            output_path=str(output_dir / f"combined_{safe}_{dsafe}.html"),
        )
        combined_count += 1

    print(f"  {combined_count} 个综合图表")

    # ── 3. 组合仪表盘 ───────────────────────────────────────
    print(f"\n[3/4] 生成组合仪表盘...")
    portfolio_data = data.get("portfolio", {})

    # 尝试恢复 nav_curve
    nav_curve_raw = portfolio_data.get("nav_curve", [])
    if nav_curve_raw:
        nav_curve = [
            DailyNAV(
                date=n["date"],
                cash=n["cash"],
                position_value=n["position_value"],
                total_value=n["total_value"],
                open_positions=n["open_positions"],
            )
            for n in nav_curve_raw
        ]
    else:
        # nav_curve 未序列化，用交易数据模拟一条简单净值曲线
        nav_curve = _build_simulated_nav(trades)
        print(f"  nav_curve 未序列化，用 {len(nav_curve)} 个交易日模拟")

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
    print(f"  组合仪表盘 -> {dashboard_path}")

    print(f"\n[4/4] === 完成 ===")
    print(f"  综合图表:     {combined_count} 个")
    print(f"  组合仪表盘:   1 个")
    print(f"  总计:         {combined_count + 1} 个 HTML")
    print(f"  输出目录:     {output_dir}")


def _build_simulated_nav(trades: list[dict]) -> list[DailyNAV]:
    """当 nav_curve 未序列化时，用交易数据模拟一条简化净值曲线。"""
    if not trades:
        return []

    initial = 100000.0
    cash = initial
    open_positions: list[dict] = []
    daily_nav: list[DailyNAV] = []
    sorted_trades = sorted(trades, key=lambda t: t.get("signal_date", ""))

    # 收集所有相关日期
    all_dates = set()
    for t in sorted_trades:
        all_dates.add(t.get("signal_date", ""))
        if t.get("exit_date"):
            all_dates.add(t["exit_date"])
    all_dates = sorted(all_dates)

    for date in all_dates:
        # 开仓
        for t in sorted_trades:
            if t.get("signal_date") == date:
                entry = t.get("entry_price", 0)
                amount = round(initial * 0.1, 2)
                qty = int(amount // entry) if entry > 0 else 0
                if qty > 0:
                    cash -= qty * entry
                    open_positions.append(
                        {
                            "symbol": t["symbol"],
                            "entry": entry,
                            "qty": qty,
                            "open_date": date,
                        }
                    )

        # 平仓
        for pos in list(open_positions):
            for t in sorted_trades:
                if (
                    t.get("symbol") == pos["symbol"]
                    and t.get("signal_date") == pos["open_date"]
                    and t.get("exit_date") == date
                ):
                    exit_price = t.get("exit_price", t.get("entry_price", 0))
                    cash += pos["qty"] * exit_price
                    open_positions.remove(pos)

        # 计算持仓市值（简化：用 entry_price 估算）
        pos_value = sum(p["qty"] * p["entry"] for p in open_positions)
        total_value = cash + pos_value

        daily_nav.append(
            DailyNAV(
                date=date,
                cash=round(cash, 2),
                position_value=round(pos_value, 2),
                total_value=round(total_value, 2),
                open_positions=len(open_positions),
            )
        )

    return daily_nav


if __name__ == "__main__":
    main()
