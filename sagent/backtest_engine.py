"""逐日止损/止盈回测引擎 (#23)。

对每个买入信号，从买入次日逐日遍历 K 线，执行止损、半仓止盈、
趋势破坏退出和持有到期逻辑。输出每笔交易的完整生命周期和整体统计。

纯计算模块，不依赖网络或外部数据源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from .kline import find_key_low, find_trend_break_ref
from .models import DailyBar
from .strategy.params import StopLossParams


# 模块级默认参数
_stop_params = StopLossParams()


@dataclass(frozen=True)
class TradeLifecycle:
    """单笔交易的生命周期。"""

    symbol: str
    signal_date: str  # 信号日
    entry_price: float  # 买入价（信号日收盘价）
    key_low: float  # 关键低点
    stop_loss_price: float  # 止损价 = max(entry_price * 0.90, key_low * 0.97)

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

    # 止损类型追踪 (#26)
    stop_loss_type: str = ""  # "绝对止损10%" | "关键低点" | ""（未止损时为空）
    stop_loss_distance_pct: float = 0.0  # 止损价距买入价的百分比距离（负数）

    # 全程持有对比 (#27)
    buy_and_hold_return: float = (
        0.0  # 全程持有收益（不考虑止损止盈，持有到 max_holding 天）
    )

    # 趋势破坏参考位 (#28)
    trend_break_ref: float = 0.0  # 趋势破坏参考位
    trend_break_desc: str = ""  # 参考位描述


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

    # 止损类型分组统计 (#26)
    hard_stop_loss_count: int = 0  # 绝对止损10%次数
    key_low_stop_loss_count: int = 0  # 关键低点止损次数
    hard_stop_loss_rate: float = 0.0  # 绝对止损率
    key_low_stop_loss_rate: float = 0.0  # 关键低点止损率
    avg_return_hard_stop_loss: float = 0.0  # 绝对止损组平均收益
    avg_return_key_low_stop_loss: float = 0.0  # 关键低点止损组平均收益
    oversized_stop_loss_count: int = 0  # 止损空间>10%的交易数

    # 半仓止盈统计 (#27)
    half_profit_triggered_count: int = (
        0  # 触发半仓止盈的交易数（含后续止损/趋势破坏/持有到期）
    )
    half_profit_triggered_rate: float = 0.0  # 触发率
    avg_return_half_profit_triggered: float = 0.0  # 触发止盈的组平均收益
    avg_return_half_profit_not_triggered: float = 0.0  # 未触发止盈的组平均收益

    # 全程持有对比 (#27)
    buy_and_hold_avg_return: float = 0.0  # 全程持有平均收益（所有信号）
    strategy_vs_buyhold_diff: float = 0.0  # 止盈策略 vs 全程持有 收益差


def find_key_low_for_signal(bars: list[DailyBar], signal_idx: int) -> tuple[float, int]:
    """获取信号日的 key_low 和索引（使用信号日及之前的数据）。

    Returns:
        (key_low 值, key_low 在 bars 中的索引)
    """
    window = bars[: signal_idx + 1]
    key_low, _source, local_idx = find_key_low(window)
    return round(key_low, 2), local_idx


def simulate_trade(
    bars: list[DailyBar],
    signal_idx: int,
    max_holding: int | None = None,
    slp: StopLossParams | None = None,
) -> TradeLifecycle:
    """模拟单笔交易的逐日止损/止盈生命周期。

    从 signal_idx 的下一个交易日开始，逐日检查止损、半仓止盈、趋势破坏，
    最长持有 max_holding 个交易日。

    Args:
        bars: 完整的日K线数据。
        signal_idx: 信号日（买入日）在 bars 中的索引。
        max_holding: 最大持有天数（不含买入日），None 则用参数默认值。
        slp: 止损参数，None 则用模块默认值。

    Returns:
        TradeLifecycle 包含完整的退出信息和逐日事件。
    """
    p = slp or _stop_params
    _max_holding = max_holding if max_holding is not None else p.max_holding
    n = len(bars)
    signal_bar = bars[signal_idx]
    symbol = signal_bar.symbol
    signal_date = signal_bar.date
    entry_price = signal_bar.close

    # 计算 key_low、止损价和趋势破坏参考位
    key_low, key_low_idx = find_key_low_for_signal(bars, signal_idx)
    stop_loss_price = round(
        max(
            entry_price * (1 - p.absolute_stop),
            key_low * (1 - p.key_low_buffer),
        ),
        2,
    )
    r_denom = entry_price - stop_loss_price  # 盈亏比分母（基于实际止损价）

    # 计算趋势破坏参考位 (#28)
    trend_break_ref, trend_break_desc = find_trend_break_ref(
        bars, signal_idx, key_low_idx=key_low_idx
    )

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
    end_idx = min(signal_idx + _max_holding, n - 1)

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
        if not half_taken and current_r >= p.half_profit_r:
            half_taken = True
            half_profit_r = current_r
            daily_events[-1]["event"] = "半仓止盈"
            daily_events[-1]["trigger_price"] = daily_high
            # 半仓锁定，继续持有剩余半仓

        # 3. 如果已止盈一半，检查趋势破坏（跌破 trend_break_ref）
        if half_taken and daily_low <= trend_break_ref:
            exit_date = bar.date
            exit_price = round(trend_break_ref, 2)
            exit_reason = "半仓止盈后趋势破坏"
            locked_return = half_profit_r * r_denom / entry_price
            remain_return = (trend_break_ref - entry_price) / entry_price
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

    # 判断止损类型
    absolute_stop_threshold = round(entry_price * (1 - p.absolute_stop), 2)
    keylow_stop_threshold = round(key_low * (1 - p.key_low_buffer), 2)
    if exit_reason == "止损":
        if (
            exit_price == absolute_stop_threshold
            and absolute_stop_threshold > keylow_stop_threshold
        ):
            stop_loss_type = "绝对止损10%"
        else:
            stop_loss_type = "关键低点"
    else:
        stop_loss_type = ""

    stop_loss_distance_pct = round((stop_loss_price - entry_price) / entry_price, 4)

    # 全程持有收益 (#27)：不考虑止损止盈，持有到 max_holding 天
    buy_and_hold_price = bars[end_idx].close
    buy_and_hold_return = round((buy_and_hold_price - entry_price) / entry_price, 4)

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
        stop_loss_type=stop_loss_type,
        stop_loss_distance_pct=stop_loss_distance_pct,
        buy_and_hold_return=buy_and_hold_return,
        trend_break_ref=round(trend_break_ref, 2),
        trend_break_desc=trend_break_desc,
    )


def run_backtest_engine(
    bars_map: dict[str, list[DailyBar]],
    signals: list[dict[str, Any]],
    max_holding: int = 20,
    min_sl_distance: float = 0.0,
    exclude_st: bool = True,
) -> BacktestStats:
    """对多个信号执行逐日止损/止盈回测。

    Args:
        bars_map: 股票代码 → K 线数据映射。
        signals: 信号列表，每个包含:
            - symbol: 股票代码
            - signal_date: 信号日（str，格式 YYYY-MM-DD）
            - signal_idx: 信号日在 bars 中的索引（可选，若不提供则按日期查找）
        max_holding: 最大持有天数。
        min_sl_distance: 最小止损距离（如 0.03 = 3%），低于此值的信号被过滤。
        exclude_st: 是否过滤 ST 股票（名称含 ST）。

    Returns:
        BacktestStats 包含整体统计和逐笔交易生命周期。
    """
    trades: list[TradeLifecycle] = []
    filtered_count = 0

    for signal in signals:
        symbol = signal["symbol"]
        bars = bars_map.get(symbol)
        if bars is None or len(bars) < 2:
            continue

        # 过滤 ST 股票
        if exclude_st:
            name = signal.get("name", "")
            if "ST" in name.upper() or "*ST" in name.upper():
                filtered_count += 1
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

        # 先模拟交易
        trade = simulate_trade(bars, signal_idx, max_holding)

        # 过滤止损距离过小的信号
        if min_sl_distance > 0:
            sl_dist = (trade.entry_price - trade.stop_loss_price) / trade.entry_price
            if sl_dist < min_sl_distance:
                filtered_count += 1
                continue

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

    # 止损类型分组统计 (#26)
    hard_sl = [t for t in trades if t.stop_loss_type == "绝对止损10%"]
    key_low_sl = [t for t in trades if t.stop_loss_type == "关键低点"]
    oversized = [t for t in trades if t.stop_loss_distance_pct < -0.10]

    # 半仓止盈统计 (#27)
    half_triggered = [t for t in trades if t.half_profit_locked]
    half_not_triggered = [t for t in trades if not t.half_profit_locked]

    # 全程持有对比 (#27)
    buy_and_hold_returns = [t.buy_and_hold_return for t in trades]
    buy_and_hold_avg = safe_mean(buy_and_hold_returns)
    strategy_avg = safe_mean(all_returns)

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
        hard_stop_loss_count=len(hard_sl),
        key_low_stop_loss_count=len(key_low_sl),
        hard_stop_loss_rate=round(len(hard_sl) / max(total_trades, 1), 4),
        key_low_stop_loss_rate=round(len(key_low_sl) / max(total_trades, 1), 4),
        avg_return_hard_stop_loss=safe_mean([t.total_return for t in hard_sl]),
        avg_return_key_low_stop_loss=safe_mean([t.total_return for t in key_low_sl]),
        oversized_stop_loss_count=len(oversized),
        half_profit_triggered_count=len(half_triggered),
        half_profit_triggered_rate=round(len(half_triggered) / max(total_trades, 1), 4),
        avg_return_half_profit_triggered=safe_mean(
            [t.total_return for t in half_triggered]
        ),
        avg_return_half_profit_not_triggered=safe_mean(
            [t.total_return for t in half_not_triggered]
        ),
        buy_and_hold_avg_return=buy_and_hold_avg,
        strategy_vs_buyhold_diff=round(strategy_avg - buy_and_hold_avg, 4),
    )
