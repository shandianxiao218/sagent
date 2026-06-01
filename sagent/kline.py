from __future__ import annotations

from statistics import mean

from .models import DailyBar, KlineDescription


def find_swing_lows(
    bars: list[DailyBar], left: int = 5, right: int = 3
) -> list[tuple[int, float]]:
    """检测利弗摩尔结构转折低点（swing low）。

    某日 low 同时小于左侧 left 个和右侧 right 个相邻日的 low，
    则该日为一个 swing low。

    Returns:
        [(索引, low值), ...] 按索引升序排列。
    """
    n = len(bars)
    if n < left + right + 1:
        return []
    result: list[tuple[int, float]] = []
    for i in range(left, n - right):
        is_swing = True
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if bars[i].low >= bars[j].low:
                is_swing = False
                break
        if is_swing:
            result.append((i, bars[i].low))
    return result


def find_key_low(
    bars: list[DailyBar], recent_high_idx: int | None = None
) -> tuple[float, str, int]:
    """在回调区间中找到关键结构转折低点。

    1. 确定回调区间：从阶段高点（recent_high_idx）到 bars 末尾。
    2. 在回调区间内找所有 swing lows。
    3. 取最后一个 swing low 作为 key_low。
    4. 回退保障：找不到 swing low 时取回调区间最低价。

    Args:
        bars: 日K线数据。
        recent_high_idx: 阶段高点在 bars 中的索引。若为 None，
            取最近30日收盘最高日作为阶段高点。

    Returns:
        (key_low值, 来源描述, 日期索引)
    """
    n = len(bars)
    if n < 2:
        return bars[-1].low, "数据不足，取最后一日低价", n - 1

    # 确定回调区间起点（阶段高点的索引）
    if recent_high_idx is None:
        closes = [bar.close for bar in bars[-30:]]
        recent_high = max(closes)
        # 在最近30日中找到最高收盘价对应的索引（取最后一个）
        # closes[::-1].index(recent_high) 是从末尾数的位置，
        # 转换回正向索引：len(closes) - 1 - rev_idx
        rev_idx = closes[::-1].index(recent_high)
        recent_high_idx = n - 30 + (len(closes) - 1 - rev_idx)

    start = max(0, recent_high_idx)
    end = n  # 不含

    if start >= end - 1:
        return bars[-1].low, "回调区间过短，取最后一日低价", n - 1

    pullback_bars = bars[start:end]
    # 将 swing low 索引映射回原始 bars 的索引
    swing_lows = find_swing_lows(pullback_bars)
    global_swings = [(start + idx, low) for idx, low in swing_lows]

    if global_swings:
        idx, low = global_swings[-1]
        date_str = bars[idx].date
        return low, f"{date_str}的回调结构转折低点", idx

    # 回退：回调区间内的最低价
    min_idx = start
    min_low = pullback_bars[0].low
    for i, bar in enumerate(pullback_bars):
        if bar.low < min_low:
            min_low = bar.low
            min_idx = start + i
    date_str = bars[min_idx].date
    return min_low, f"{date_str}的回调区间最低价（无明确转折点）", min_idx


def find_trend_break_ref(
    bars: list[DailyBar],
    signal_idx: int,
    key_low_idx: int | None = None,
) -> tuple[float, str]:
    """识别趋势破坏参考位。

    从 key_low 到信号日之间的上升波段中，找到 higher low 序列，
    最后一个 higher low 作为趋势破坏参考位。
    如果没有 higher low 序列，退回到 key_low。

    Args:
        bars: 日K线数据。
        signal_idx: 信号日在 bars 中的索引。
        key_low_idx: key_low 在 bars 中的索引。若为 None，自动计算。

    Returns:
        (参考位价格, 描述文本)
    """
    # 1. 获取 key_low 位置
    if key_low_idx is None:
        window = bars[: signal_idx + 1]
        _kl, _src, key_low_idx = find_key_low(window)

    # 2. 从 key_low 到 signal_idx 找 swing lows
    trend_bars = bars[key_low_idx : signal_idx + 1]
    swing_lows = find_swing_lows(trend_bars)
    # 映射回全局索引
    global_swings = [(key_low_idx + idx, low) for idx, low in swing_lows]

    if not global_swings:
        return bars[key_low_idx].low, f"与止损位相同（{bars[key_low_idx].date}）"

    # 3. 找 higher low 序列
    higher_lows: list[tuple[int, float]] = []
    for i in range(1, len(global_swings)):
        _idx_i, low_i = global_swings[i]
        _idx_prev, low_prev = global_swings[i - 1]
        if low_i > low_prev:
            higher_lows.append(global_swings[i])

    if higher_lows:
        last_idx, last_low = higher_lows[-1]
        return last_low, f"{bars[last_idx].date}的更高低点"

    # 没有形成 higher low → 用 key_low
    return bars[key_low_idx].low, f"与止损位相同（{bars[key_low_idx].date}）"


def describe_pullback_structure(bars: list[DailyBar], signal_idx: int) -> str:
    """生成回调结构的自然语言描述。

    基于 find_key_low 和 find_swing_lows 的结果，
    描述回调过程中的结构转折低点序列。
    """
    window = bars[: signal_idx + 1]
    key_low, source, kl_idx = find_key_low(window)

    # 在 key_low 附近区域（前20日到信号日）检测 swing lows
    start = max(0, kl_idx - 20)
    region = window[start:]
    swing_lows = find_swing_lows(region)
    # 映射回 window 索引
    global_swings = [(start + idx, low) for idx, low in swing_lows]

    if not global_swings:
        return f"回调区间内未检测到明确的结构转折低点，key_low={key_low:.2f}。"

    # 构建转折点描述
    parts: list[str] = []
    for i, (idx, low) in enumerate(global_swings):
        bar = window[idx]
        # 从日期中提取月-日
        date_str = bar.date
        if len(date_str) >= 10:
            md = date_str[5:10]  # "MM-DD"
        else:
            md = date_str

        if i == 0:
            parts.append(f"{md} 出现结构转折低点 {low:.2f}")
        else:
            prev_low = global_swings[i - 1][1]
            if low > prev_low:
                parts.append(f"{md} 形成更高的低点 {low:.2f}")
            elif low < prev_low:
                parts.append(f"{md} 出现更低的低点 {low:.2f}")
            else:
                parts.append(f"{md} 形成平齐低点 {low:.2f}")

    if len(parts) == 1:
        detail = parts[0]
    else:
        detail = "，".join(parts[:-1]) + "，随后" + parts[-1]

    return f"回调过程中{detail}。"


def describe_stock(
    symbol: str, bars: list[DailyBar], max_chars: int = 900
) -> KlineDescription:
    if len(bars) < 30:
        raise ValueError("K线数据不足，至少需要30个交易日")
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    current = closes[-1]
    ma20 = mean(closes[-20:])
    ma60 = mean(closes[-60:]) if len(closes) >= 60 else mean(closes)
    recent_high = max(closes[-30:])
    key_low, key_low_source, _key_low_idx = find_key_low(bars)
    volume_ratio = volumes[-1] / mean(volumes[-10:]) if mean(volumes[-10:]) else 0
    breakout = current >= max(closes[-8:])
    pullback_ratio = (recent_high - key_low) / recent_high if recent_high else 0
    # 盈亏比计算
    risk = current - key_low
    r_ratio = (recent_high - current) / risk if risk > 0 else 0.0
    target_2_5r = current + 2.5 * risk
    target_3r = current + 3.0 * risk

    # 生成回调结构描述
    pullback_desc = describe_pullback_structure(bars, len(bars) - 1)

    text = (
        f"{symbol} 当前价格 {current:.2f}，位于20日均线 {ma20:.2f} 和60日均线 {ma60:.2f} 附近；"
        f"趋势上，前期形成明显上升波段，近期从阶段高点 {recent_high:.2f} 回调至候选关键低点 {key_low:.2f}；"
        f"回调幅度约 {pullback_ratio:.1%}，近几日开始回升并{'尝试突破' if breakout else '尚未突破'}短期回调趋势；"
        f"成交量为近10日均量的 {volume_ratio:.2f} 倍，需关注突破是否放量确认；"
        f"风险位置为买点前关键低点 {key_low:.2f}（{key_low_source}），跌破则形态无效；"
        f"当前风险 {risk:.2f} 元，盈亏比 R=2.5 价位 {target_2_5r:.2f}、R=3 价位 {target_3r:.2f}，止损价 {key_low:.2f}。"
        f"{pullback_desc}"
    )
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return KlineDescription(
        symbol=symbol,
        text=text,
        key_low=round(key_low, 2),
        risk_price=round(key_low, 2),
        fields={
            "current": current,
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "recent_high": recent_high,
            "key_low": round(key_low, 2),
            "key_low_source": key_low_source,
            "volume_ratio": round(volume_ratio, 2),
            "breakout": breakout,
            "risk": round(risk, 2),
            "r_ratio": round(r_ratio, 2),
            "target_2_5r": round(target_2_5r, 2),
            "target_3r": round(target_3r, 2),
        },
    )
