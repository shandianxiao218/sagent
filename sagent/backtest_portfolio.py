"""组合级持仓生命周期管理回测 (#29)。

模拟真实的资金管理和持仓监控：初始资金、每笔仓位比例、
每周开仓频率限制、逐日止损/止盈/趋势破坏检查、资金曲线追踪。

纯计算模块，不依赖网络或外部数据源。
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, stdev
from typing import Any

from .backtest_engine import find_key_low_for_signal
from .kline import find_trend_break_ref
from .models import DailyBar


def _iso_week_id(date_str: str) -> str:
    """获取 ISO 周标识。"""
    from datetime import date as date_type

    year, week, _ = date_type.fromisoformat(date_str).isocalendar()
    return f"{year}-W{week:02d}"


@dataclass
class DailyNAV:
    """每日净值快照。"""

    date: str
    cash: float
    position_value: float
    total_value: float
    open_positions: int


@dataclass
class PortfolioStats:
    """组合级回测统计。"""

    initial_cash: float
    final_value: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_loss_ratio: float
    max_single_profit: float
    max_single_loss: float
    stop_loss_count: int
    take_profit_count: int
    natural_exit_count: int
    avg_holding_days: float
    capital_utilization: float
    nav_curve: list[DailyNAV]


class BacktestPortfolio:
    """组合级回测持仓管理器。

    模拟真实的资金管理流程：
    - 每笔开仓使用 cash * position_ratio
    - 每周最多 max_weekly_open 笔
    - 逐日执行止损/止盈/趋势破坏检查
    - 持有到期自动平仓
    """

    def __init__(
        self,
        initial_cash: float = 100_000,
        position_ratio: float = 0.1,
        max_weekly_open: int = 2,
        max_holding: int = 20,
    ) -> None:
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.position_ratio = position_ratio
        self.max_weekly_open = max_weekly_open
        self.max_holding = max_holding

        # 活跃持仓列表，每项为 dict：
        # symbol, entry_price, quantity, key_low, stop_loss_price,
        # trend_break_ref, open_date, open_idx, half_taken, half_profit_r
        self.open_positions: list[dict[str, Any]] = []

        # 已关闭的交易
        self.closed_trades: list[dict[str, Any]] = []

        # 周控制
        self._current_week: str = ""
        self._weekly_open_count: int = 0

        # 每日净值
        self.nav_curve: list[DailyNAV] = []

    def try_open(
        self,
        symbol: str,
        bars: list[DailyBar],
        signal_idx: int,
        signal_date: str,
    ) -> dict[str, Any] | None:
        """尝试开仓。受资金和每周频率限制。

        Args:
            symbol: 股票代码
            bars: 完整 K 线数据
            signal_idx: 信号日在 bars 中的索引
            signal_date: 信号日日期

        Returns:
            成功开仓返回持仓信息 dict，失败返回 None。
        """
        # 1. 检查周限制
        week = _iso_week_id(signal_date)
        if week != self._current_week:
            self._current_week = week
            self._weekly_open_count = 0
        if self._weekly_open_count >= self.max_weekly_open:
            return None

        # 2. 检查是否有同股票活跃持仓
        for pos in self.open_positions:
            if pos["symbol"] == symbol:
                return None

        # 3. 计算买入量
        entry_price = bars[signal_idx].close
        alloc_amount = self.cash * self.position_ratio
        quantity = int(alloc_amount // entry_price)
        if quantity <= 0:
            return None

        # 4. 获取 key_low 和趋势破坏参考位
        key_low, key_low_idx = find_key_low_for_signal(bars, signal_idx)
        stop_loss_price = round(max(entry_price * 0.95, key_low), 2)
        trend_break_ref, trend_break_desc = find_trend_break_ref(
            bars, signal_idx, key_low_idx=key_low_idx
        )

        # 5. 扣减现金
        cost = round(quantity * entry_price, 2)
        if cost > self.cash:
            return None
        self.cash -= cost
        self._weekly_open_count += 1

        position = {
            "symbol": symbol,
            "entry_price": round(entry_price, 2),
            "quantity": quantity,
            "cost": cost,
            "key_low": key_low,
            "stop_loss_price": stop_loss_price,
            "trend_break_ref": round(trend_break_ref, 2),
            "trend_break_desc": trend_break_desc,
            "open_date": signal_date,
            "open_idx": signal_idx,
            "half_taken": False,
            "half_profit_r": 0.0,
        }
        self.open_positions.append(position)
        return position

    def daily_monitor(
        self, date: str, bars_map: dict[str, list[DailyBar]]
    ) -> list[dict[str, Any]]:
        """每日收盘后执行持仓监控。

        逐个持仓检查：
        1. 持有到期 → 强制平仓
        2. 止损：bar.low <= stop_loss_price → 平仓
        3. 半仓止盈：R >= 2.5 且未止盈过 → 标记
        4. 趋势破坏：已止盈 + bar.low <= trend_break_ref → 平仓

        Args:
            date: 当前交易日
            bars_map: 股票代码 → K 线数据

        Returns:
            当日平仓的交易列表。
        """
        closed: list[dict[str, Any]] = []
        still_open: list[dict[str, Any]] = []

        for pos in self.open_positions:
            symbol = pos["symbol"]
            bars = bars_map.get(symbol, [])

            # 查找当日 bar
            today_bar: DailyBar | None = None
            for bar in bars:
                if bar.date == date:
                    today_bar = bar
                    break

            if today_bar is None:
                # 没有当日数据（停牌等），保持持仓
                still_open.append(pos)
                continue

            # 计算持有天数
            holding_days = self._calc_holding_days(pos["open_date"], date)

            # 1. 持有到期检查
            if holding_days >= self.max_holding:
                self._close_position(pos, date, today_bar.close, "持有到期", closed)
                continue

            entry_price = pos["entry_price"]
            key_low = pos["key_low"]
            stop_loss_price = pos["stop_loss_price"]
            trend_break_ref = pos["trend_break_ref"]
            r_denom = entry_price - key_low

            daily_high = today_bar.high
            daily_low = today_bar.low
            current_r = (daily_high - entry_price) / r_denom if r_denom > 0 else 0.0

            # 2. 止损检查（最优先）
            if daily_low <= stop_loss_price:
                exit_price = stop_loss_price
                self._close_position(pos, date, exit_price, "止损", closed)
                continue

            # 3. 半仓止盈检查（只触发一次）
            if not pos["half_taken"] and current_r >= 2.5:
                pos["half_taken"] = True
                pos["half_profit_r"] = current_r

            # 4. 如果已止盈一半，检查趋势破坏
            if pos["half_taken"] and daily_low <= trend_break_ref:
                exit_price = round(trend_break_ref, 2)
                self._close_position(
                    pos, date, exit_price, "半仓止盈后趋势破坏", closed
                )
                continue

            still_open.append(pos)

        self.open_positions = still_open
        return closed

    def close_all_remaining(
        self, date: str, bars_map: dict[str, list[DailyBar]]
    ) -> list[dict[str, Any]]:
        """清仓所有剩余持仓。"""
        closed: list[dict[str, Any]] = []
        for pos in self.open_positions:
            symbol = pos["symbol"]
            bars = bars_map.get(symbol, [])
            exit_price = pos["entry_price"]
            for bar in bars:
                if bar.date == date:
                    exit_price = bar.close
                    break
            self._close_position(pos, date, exit_price, "回测结束清仓", closed)
        self.open_positions = []
        return closed

    def record_nav(self, date: str, bars_map: dict[str, list[DailyBar]]) -> None:
        """记录当日净值。"""
        position_value = 0.0
        for pos in self.open_positions:
            symbol = pos["symbol"]
            bars = bars_map.get(symbol, [])
            current_price = pos["entry_price"]
            for bar in bars:
                if bar.date == date:
                    current_price = bar.close
                    break
            position_value += pos["quantity"] * current_price

        total_value = self.cash + position_value
        self.nav_curve.append(
            DailyNAV(
                date=date,
                cash=round(self.cash, 2),
                position_value=round(position_value, 2),
                total_value=round(total_value, 2),
                open_positions=len(self.open_positions),
            )
        )

    def get_stats(self) -> PortfolioStats:
        """计算组合统计。"""
        all_trades = self.closed_trades
        total_trades = len(all_trades)

        if total_trades == 0:
            return PortfolioStats(
                initial_cash=self.initial_cash,
                final_value=round(self.cash, 2),
                total_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                avg_profit=0.0,
                avg_loss=0.0,
                profit_loss_ratio=0.0,
                max_single_profit=0.0,
                max_single_loss=0.0,
                stop_loss_count=0,
                take_profit_count=0,
                natural_exit_count=0,
                avg_holding_days=0.0,
                capital_utilization=0.0,
                nav_curve=self.nav_curve,
            )

        # 按笔统计
        returns = [t["return_pct"] for t in all_trades]
        profits = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        winning_trades = len(profits)
        losing_trades = len(losses)

        avg_profit = mean(profits) if profits else 0.0
        avg_loss = mean(losses) if losses else 0.0
        profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 0.0

        # 退出原因分组
        stop_loss_count = sum(1 for t in all_trades if t["exit_reason"] == "止损")
        take_profit_count = sum(
            1 for t in all_trades if t["exit_reason"] == "半仓止盈后趋势破坏"
        )
        natural_exit_count = sum(
            1 for t in all_trades if t["exit_reason"] == "持有到期"
        )

        holding_days_list = [t["holding_days"] for t in all_trades]

        # 净值曲线统计
        final_value = self.nav_curve[-1].total_value if self.nav_curve else self.cash
        total_return = (final_value - self.initial_cash) / self.initial_cash

        max_drawdown = self._calc_max_drawdown()
        sharpe_ratio = self._calc_sharpe()

        # 资金利用率 = 持仓市值峰值 / 初始资金
        max_position_value = max(
            (nav.position_value for nav in self.nav_curve), default=0.0
        )
        capital_utilization = (
            max_position_value / self.initial_cash if self.initial_cash else 0.0
        )

        return PortfolioStats(
            initial_cash=round(self.initial_cash, 2),
            final_value=round(final_value, 2),
            total_return=round(total_return, 4),
            max_drawdown=round(max_drawdown, 4),
            sharpe_ratio=round(sharpe_ratio, 4),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(winning_trades / total_trades, 4),
            avg_profit=round(avg_profit, 4),
            avg_loss=round(avg_loss, 4),
            profit_loss_ratio=round(profit_loss_ratio, 4),
            max_single_profit=round(max(returns), 4) if returns else 0.0,
            max_single_loss=round(min(returns), 4) if returns else 0.0,
            stop_loss_count=stop_loss_count,
            take_profit_count=take_profit_count,
            natural_exit_count=natural_exit_count,
            avg_holding_days=round(mean(holding_days_list), 2),
            capital_utilization=round(capital_utilization, 4),
            nav_curve=self.nav_curve,
        )

    # ─── 内部方法 ─────────────────────────────────────────────

    def _close_position(
        self,
        pos: dict[str, Any],
        exit_date: str,
        exit_price: float,
        exit_reason: str,
        closed_list: list[dict[str, Any]],
    ) -> None:
        """关闭持仓并记录交易。"""
        entry_price = pos["entry_price"]
        quantity = pos["quantity"]
        half_taken = pos["half_taken"]
        half_profit_r = pos["half_profit_r"]
        key_low = pos["key_low"]
        r_denom = entry_price - key_low

        # 计算综合收益率
        if half_taken and r_denom > 0:
            locked_return = half_profit_r * r_denom / entry_price
            remain_return = (exit_price - entry_price) / entry_price
            total_return = (locked_return + remain_return) / 2
        else:
            total_return = (exit_price - entry_price) / entry_price

        # 回收资金（按卖出价回收全部股数）
        proceeds = round(quantity * exit_price, 2)
        self.cash += proceeds

        holding_days = self._calc_holding_days(pos["open_date"], exit_date)

        trade_record = {
            "symbol": pos["symbol"],
            "entry_price": entry_price,
            "exit_price": round(exit_price, 2),
            "quantity": quantity,
            "open_date": pos["open_date"],
            "exit_date": exit_date,
            "exit_reason": exit_reason,
            "return_pct": round(total_return, 4),
            "holding_days": holding_days,
            "half_taken": half_taken,
            "half_profit_r": half_profit_r,
        }
        closed_list.append(trade_record)
        self.closed_trades.append(trade_record)

    def _calc_holding_days(self, open_date: str, current_date: str) -> int:
        """计算交易日持有天数（用自然日差近似）。"""
        from datetime import date as date_type

        d1 = date_type.fromisoformat(open_date)
        d2 = date_type.fromisoformat(current_date)
        return (d2 - d1).days

    def _calc_max_drawdown(self) -> float:
        """计算净值曲线的最大回撤。"""
        if not self.nav_curve:
            return 0.0
        peak = 0.0
        max_dd = 0.0
        for nav in self.nav_curve:
            if nav.total_value > peak:
                peak = nav.total_value
            if peak > 0:
                dd = (peak - nav.total_value) / peak
                max_dd = max(max_dd, dd)
        return max_dd

    def _calc_sharpe(self) -> float:
        """计算日收益率 Sharpe（简化，年化系数=1）。"""
        if len(self.nav_curve) < 2:
            return 0.0
        daily_returns: list[float] = []
        for i in range(1, len(self.nav_curve)):
            prev = self.nav_curve[i - 1].total_value
            curr = self.nav_curve[i].total_value
            if prev > 0:
                daily_returns.append((curr - prev) / prev)
        if len(daily_returns) < 2:
            return 0.0
        avg_ret = mean(daily_returns)
        std_ret = stdev(daily_returns)
        return avg_ret / std_ret if std_ret > 0 else 0.0


def run_portfolio_backtest(
    bars_map: dict[str, list[DailyBar]],
    signals: list[dict[str, Any]],
    initial_cash: float = 100_000,
    max_holding: int = 20,
    position_ratio: float = 0.1,
    max_weekly_open: int = 2,
) -> PortfolioStats:
    """运行组合级回测。

    Args:
        bars_map: 股票代码 → K 线数据。
        signals: 信号列表，每个包含：
            - symbol: 股票代码
            - signal_date: 信号日
            - signal_idx: 信号日在 bars 中的索引（可选）
        initial_cash: 初始资金。
        max_holding: 最大持有天数。
        position_ratio: 每笔仓位比例。
        max_weekly_open: 每周最多开仓次数。

    Returns:
        PortfolioStats 组合统计。
    """
    portfolio = BacktestPortfolio(
        initial_cash=initial_cash,
        position_ratio=position_ratio,
        max_weekly_open=max_weekly_open,
        max_holding=max_holding,
    )

    # 1. 按日期排序信号
    sorted_signals = sorted(signals, key=lambda s: s["signal_date"])

    # 2. 收集所有出现的日期（交易日的并集）
    all_dates: set[str] = set()
    for bars in bars_map.values():
        for bar in bars:
            all_dates.add(bar.date)
    # 也加入信号日
    for s in sorted_signals:
        all_dates.add(s["signal_date"])
    trade_dates = sorted(all_dates)

    # 建立信号日 → 信号的映射（可能有同一天多个信号）
    signals_by_date: dict[str, list[dict[str, Any]]] = {}
    for sig in sorted_signals:
        d = sig["signal_date"]
        if d not in signals_by_date:
            signals_by_date[d] = []
        signals_by_date[d].append(sig)

    # 3. 逐日执行
    for date in trade_dates:
        # 3a. 尝试开仓
        if date in signals_by_date:
            for sig in signals_by_date[date]:
                symbol = sig["symbol"]
                bars = bars_map.get(symbol, [])
                if not bars:
                    continue

                # 确定 signal_idx
                signal_idx = sig.get("signal_idx")
                if signal_idx is None:
                    signal_date = sig["signal_date"]
                    for j, bar in enumerate(bars):
                        if bar.date == signal_date:
                            signal_idx = j
                            break
                if signal_idx is None:
                    continue

                portfolio.try_open(symbol, bars, signal_idx, date)

        # 3b. 每日监控
        portfolio.daily_monitor(date, bars_map)

        # 3c. 记录净值
        portfolio.record_nav(date, bars_map)

    # 4. 清仓剩余持仓（用最后一个交易日）
    if trade_dates:
        last_date = trade_dates[-1]
        portfolio.close_all_remaining(last_date, bars_map)
        portfolio.record_nav(last_date, bars_map)

    # 5. 返回统计
    return portfolio.get_stats()
