"""入场确认模块。

解决核心痛点：-7 天退出的 61 笔交易胜率 0%，全部止损。
原因是信号日当天就买入，缺少次日确认。

入场确认逻辑：
1. 信号日次日收盘 > key_low + buffer（未破关键支撑）
2. 信号日次日收盘 > 信号日收盘 * (1 - confirm_drop)（未大跌）
3. 可选：次日成交量 > 信号日成交量（放量确认）

当 require_next_day_confirm=False（默认），行为与改动前完全一致。
"""

from __future__ import annotations

from .params import EntryParams


def confirm_entry(
    bars: list,  # list[DailyBar]
    signal_idx: int,
    ep: EntryParams | None = None,
) -> tuple[bool, int, str]:
    """检查入场确认条件。

    Args:
        bars: 完整 K 线数据。
        signal_idx: 信号日在 bars 中的索引。
        ep: 入场确认参数。

    Returns:
        (confirmed, entry_idx, reason)
        - confirmed: 是否确认入场
        - entry_idx: 入场日索引（signal_idx 或 signal_idx + 1）
        - reason: 确认/拒绝原因
    """
    p = ep or EntryParams()

    if not p.require_next_day_confirm:
        # 默认：直接入场，不做确认
        return True, signal_idx, "无需次日确认"

    next_idx = signal_idx + 1
    if next_idx >= len(bars):
        return False, signal_idx, "次日无数据"

    signal_bar = bars[signal_idx]
    next_bar = bars[next_idx]

    # 条件 1: 次日收盘 > 信号日收盘 * (1 - confirm_drop)
    min_close = signal_bar.close * (1 - p.confirm_drop)
    if next_bar.close < min_close:
        return (
            False,
            next_idx,
            f"次日收盘{next_bar.close:.2f} < {min_close:.2f}，确认失败",
        )

    # 条件 2: 次日最低价不破信号日最低价（日内也不应大幅破位）
    if next_bar.low < signal_bar.low * 0.98:
        return (
            False,
            next_idx,
            f"次日低点{next_bar.low:.2f}破信号日低点{signal_bar.low:.2f}的2%",
        )

    return True, next_idx, f"次日确认通过，收盘{next_bar.close:.2f}"
