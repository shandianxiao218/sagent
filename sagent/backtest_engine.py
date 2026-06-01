"""逐日止损/止盈回测引擎 (#23)。

对每个买入信号，从买入次日逐日遍历 K 线，执行止损、半仓止盈、
趋势破坏退出和持有到期逻辑。输出每笔交易的完整生命周期和整体统计。

纯计算模块，不依赖网络或外部数据源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from .kline import find_key_low
from .models import DailyBar


@dataclass(frozen=True)
class TradeLifecycle:
    """单笔交易的生命周期。"""

    symbol: str
    signal_date: str  # 信号日
    entry_price: float  # 买入价（信号日收盘价）
    key_low: float  # 关键低点
    stop_loss_price: float  # 止损价 = max(entry_price * 0.95, key_low)

    # 退出信息
    exit_date: str | None  # 退出日期（None=未退出）
    exit_price: float | None  # 退出价格
    exit_reason: str  # "止损" | "半仓止盈后趋势破坏" | "持有到期" | "未退出"
    holding_days: int  # 实际持有天数（买入日=0，次日=1）

    # 逐日事件
    daily_events: list[dict[str, Any]] = field(default_factory=list)

    # 收益
    total_return: float = 0.0  # 综合收益率（考虑半仓）
    half_profit_locked: bool = False  # 是否触发过半仓止盈
    half_profit_r: float = 0.0  # 半仓止盈时的R倍数
    max_r: float = 0.0  # 持仓期间最大盈亏比


@dataclass(frozen=True)
class BacktestStats:
    """回测整体统计。"""

    total_signals: int
    total_trades: int
    stop_loss_count: int
    take_profit_count: int
    natural_exit_count: int

    stop_loss_rate: float
    take_profit_rate: float

    avg_holding_days: float
    avg_return_all: float
    avg_return_stop_loss: float
    avg_return_take_profit: float
    avg_return_natural: float

    win_rate: float

    trades: list[TradeLifecycle]


def find_key_low_for_signal(bars: list[DailyBar], signal_idx: int) -> float:
    """获取信号日的 key_low（使用信号日及之前的数据）。"""
    window = bars[: signal_idx + 1]
    key_low, _source, _idx = find_key_low(window)
    return round(key_low, 2)


def simulate_trade(
    bars: list[DailyBar],
    signal_idx: int,
    max_holding: int = 20,
) -> TradeLifecycle:
    """模拟单笔交易的逐日止损/止盈生命周期。

    从 signal_idx 的下一个交易日开始，逐日检查止损、半仓止盈、趋势破坏，
    最长持有 max_holding 个交易日。

    Args:
        bars: 完整的日K线数据。
        signal_idx: 信号日（买入日）在 bars 中的索引。
        max_holding: 最大持有天数（不含买入日）。

    Returns:
        TradeLifecycle 包含完整的退出信息和逐日事件。
    """
    n = len(bars)
    signal_bar = bars[signal_idx]
    symbol = signal_bar.symbol
    signal_date = signal_bar.date
    entry_price = signal_bar.close

    # 计算 key_low 和止损价
    key_low = find_key_low_for_signal(bars, signal_idx)
    stop_loss_price = round(max(entry_price * 0.95, key_low), 2)
    r_denom = entry_price - key_low  # 盈亏比分母

    # 状态变量
    half_taken = False
    half_profit_r = 0.0
    max_r = 0.0
    daily_events: list[dict[str, Any]] = []
    exit_date: str | None = None
    exit_price: float | None = None
    exit_reason = "未退出"
    total_return = 0.0
    holding_days = 0

    # 逐日遍历：从买入次日到 max_holding
    end_idx = min(signal_idx + max_holding, n - 1)

    for i in range(signal_idx + 1, end_idx + 1):
        bar = bars[i]
        holding_days = i - signal_idx
        daily_high = bar.high
        daily_low = bar.low
        daily_close = bar.close

        # 计算当日最高价对应的R倍数
        current_r = (daily_high - entry_price) / r_denom if r_denom > 0 else 0.0
        max_r = max(max_r, current_r)

        # 记录每日状态
        daily_events.append(
            {
                "date": bar.date,
                "day": holding_days,
                "high": daily_high,
                "low": daily_low,
                "close": daily_close,
                "r_ratio": round(current_r, 4),
            }
        )

        # 1. 止损检查（优先于止盈）
        if daily_low <= stop_loss_price:
            exit_date = bar.date
            exit_price = stop_loss_price
            exit_reason = "止损"
            # 如果已半仓止盈，需要综合计算
            if half_taken:
                locked_return = half_profit_r * r_denom / entry_price
                remain_return = (stop_loss_price - entry_price) / entry_price
                total_return = (locked_return + remain_return) / 2
            else:
                total_return = (stop_loss_price - entry_price) / entry_price
            # 标记最后一天的事件
            daily_events[-1]["event"] = "止损退出"
            daily_events[-1]["exit_price"] = exit_price
            break

        # 2. 半仓止盈检查（只触发一次）
        if not half_taken and current_r >= 2.5:
            half_taken = True
            half_profit_r = current_r
            daily_events[-1]["event"] = "半仓止盈"
            daily_events[-1]["trigger_price"] = daily_high
            # 半仓锁定，继续持有剩余半仓

        # 3. 如果已止盈一半，检查趋势破坏（跌破 key_low）
        if half_taken and daily_low <= key_low:
            exit_date = bar.date
            exit_price = key_low
            exit_reason = "半仓止盈后趋势破坏"
            locked_return = half_profit_r * r_denom / entry_price
            remain_return = (key_low - entry_price) / entry_price
            total_return = (locked_return + remain_return) / 2
            daily_events[-1]["event"] = "趋势破坏退出"
            daily_events[-1]["exit_price"] = exit_price
            break

    else:
        # 遍历完没有提前退出 → 持有到期
        last_bar = bars[end_idx]
        exit_date = last_bar.date
        exit_price = last_bar.close
        exit_reason = "持有到期"
        holding_days = end_idx - signal_idx

        if half_taken:
            locked_return = half_profit_r * r_denom / entry_price
            remain_return = (exit_price - entry_price) / entry_price
            total_return = (locked_return + remain_return) / 2
        else:
            total_return = (exit_price - entry_price) / entry_price

        if daily_events:
            daily_events[-1]["event"] = "持有到期退出"
            daily_events[-1]["exit_price"] = exit_price

    return TradeLifecycle(
        symbol=symbol,
        signal_date=signal_date,
        entry_price=round(entry_price, 2),
        key_low=key_low,
        stop_loss_price=stop_loss_price,
        exit_date=exit_date,
        exit_price=round(exit_price, 2) if exit_price is not None else None,
        exit_reason=exit_reason,
        holding_days=holding_days,
        daily_events=daily_events,
        total_return=round(total_return, 4),
        half_profit_locked=half_taken,
        half_profit_r=round(half_profit_r, 4),
        max_r=round(max_r, 4),
    )


def run_backtest_engine(
    bars_map: dict[str, list[DailyBar]],
    signals: list[dict[str, Any]],
    max_holding: int = 20,
) -> BacktestStats:
    """对多个信号执行逐日止损/止盈回测。

    Args:
        bars_map: 股票代码 → K 线数据映射。
        signals: 信号列表，每个包含:
            - symbol: 股票代码
            - signal_date: 信号日（str，格式 YYYY-MM-DD）
            - signal_idx: 信号日在 bars 中的索引（可选，若不提供则按日期查找）
        max_holding: 最大持有天数。

    Returns:
        BacktestStats 包含整体统计和逐笔交易生命周期。
    """
    trades: list[TradeLifecycle] = []

    for signal in signals:
        symbol = signal["symbol"]
        bars = bars_map.get(symbol)
        if bars is None or len(bars) < 2:
            continue

        # 确定信号日索引
        signal_idx = signal.get("signal_idx")
        if signal_idx is None:
            signal_date = signal["signal_date"]
            # 按日期查找
            signal_idx = None
            for j, bar in enumerate(bars):
                if bar.date == signal_date:
                    signal_idx = j
                    break
            if signal_idx is None:
                continue

        # 需要至少有 signal_idx + 1 根 bars
        if signal_idx >= len(bars) - 1:
            continue

        trade = simulate_trade(bars, signal_idx, max_holding)
        trades.append(trade)

    # 汇总统计
    total_signals = len(signals)
    total_trades = len(trades)

    stop_loss_trades = [t for t in trades if t.exit_reason == "止损"]
    take_profit_trades = [t for t in trades if t.exit_reason == "半仓止盈后趋势破坏"]
    natural_trades = [t for t in trades if t.exit_reason == "持有到期"]

    stop_loss_count = len(stop_loss_trades)
    take_profit_count = len(take_profit_trades)
    natural_exit_count = len(natural_trades)

    def safe_mean(values: list[float]) -> float:
        return round(mean(values), 4) if values else 0.0

    all_returns = [t.total_return for t in trades]
    sl_returns = [t.total_return for t in stop_loss_trades]
    tp_returns = [t.total_return for t in take_profit_trades]
    nat_returns = [t.total_return for t in natural_trades]
    holding_days_list = [float(t.holding_days) for t in trades]

    win_count = sum(1 for r in all_returns if r > 0)

    return BacktestStats(
        total_signals=total_signals,
        total_trades=total_trades,
        stop_loss_count=stop_loss_count,
        take_profit_count=take_profit_count,
        natural_exit_count=natural_exit_count,
        stop_loss_rate=round(stop_loss_count / max(total_trades, 1), 4),
        take_profit_rate=round(take_profit_count / max(total_trades, 1), 4),
        avg_holding_days=safe_mean(holding_days_list),
        avg_return_all=safe_mean(all_returns),
        avg_return_stop_loss=safe_mean(sl_returns),
        avg_return_take_profit=safe_mean(tp_returns),
        avg_return_natural=safe_mean(nat_returns),
        win_rate=round(win_count / max(total_trades, 1), 4),
        trades=trades,
    )
