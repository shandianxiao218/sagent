"""K 线绘图基础模块（plotly）。

绘制日本蜡烛图（红涨绿跌）+ 成交量柱状图 + 标注层。
输出为 plotly Figure 对象或独立 HTML 文件，不依赖 GUI 环境。
"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .backtest_engine import TradeLifecycle
from .backtest_portfolio import PortfolioStats
from .models import ChartAnnotation, ChartHLine, ChartRange, DailyBar


def _limit_up_pct(symbol: str) -> float:
    """根据股票代码判断涨停幅度。"""
    code = symbol.lstrip("0")  # 去前导零不影响判断
    # 科创板 688xxx → 20%
    if symbol.startswith("688"):
        return 0.20
    # 创业板 300xxx → 20%
    if symbol.startswith("300"):
        return 0.20
    # 北交所 8xxxxx / 4xxxxx → 30%
    if symbol.startswith("8") or symbol.startswith("4"):
        return 0.30
    # 主板（含ST）默认 10%，ST 另外由调用方处理
    return 0.10


def _classify_bars(bars: list[DailyBar], symbol: str = "") -> tuple:
    """将 bars 分为三组：涨停/阳线/阴线，返回 (limit_up, bullish, bearish)。

    每组是与 bars 等长的列表，非该组的元素为 None。
    """
    n = len(bars)
    limit_pct = _limit_up_pct(symbol)

    # 用于各组的数据
    lu_o, lu_h, lu_l, lu_c = [None] * n, [None] * n, [None] * n, [None] * n
    bu_o, bu_h, bu_l, bu_c = [None] * n, [None] * n, [None] * n, [None] * n
    be_o, be_h, be_l, be_c = [None] * n, [None] * n, [None] * n, [None] * n

    prev_close = bars[0].close  # 第一根没有前收，用自身 close
    for i, bar in enumerate(bars):
        if i > 0:
            prev_close = bars[i - 1].close
        chg = (bar.close - prev_close) / prev_close if prev_close > 0 else 0

        if bar.close >= bar.open:  # 阳线
            # 涨停判断：收盘涨幅 >= 涨停幅度 - 0.5%（容差）
            if chg >= limit_pct - 0.005 and i > 0:
                lu_o[i], lu_h[i], lu_l[i], lu_c[i] = (
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                )
            else:
                bu_o[i], bu_h[i], bu_l[i], bu_c[i] = (
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                )
        else:  # 阴线
            be_o[i], be_h[i], be_l[i], be_c[i] = bar.open, bar.high, bar.low, bar.close

    return (lu_o, lu_h, lu_l, lu_c), (bu_o, bu_h, bu_l, bu_c), (be_o, be_h, be_l, be_c)


def plot_stock_kline(
    bars: list[DailyBar],
    title: str = "",
    symbol: str = "",
    annotations: list[ChartAnnotation] | None = None,
    hlines: list[ChartHLine] | None = None,
    highlight_ranges: list[ChartRange] | None = None,
    show_volume: bool = True,
    width: int = 1200,
    height: int = 800,
    output_path: str | None = None,
) -> go.Figure:
    """绘制 K 线图（蜡烛图 + 成交量 + 标注层）。

    蜡烛图风格（中国股市惯例）：
    - 涨停：红色实心
    - 阳线（收>开）：红色空心（红边白心）
    - 阴线（收<开）：绿色实心

    涨停幅度根据板块自动判断：
    - 主板 10%，创业板/科创板 20%，北交所 30%

    Args:
        bars: 日 K 线数据。
        title: 图表标题。
        symbol: 股票代码（用于判断板块涨停幅度）。
        annotations: 点标注列表（买卖点、关键低点等）。
        hlines: 水平参考线列表（止损线、key_low 线等）。
        highlight_ranges: 区间高亮列表（持仓区间、回调区间等）。
        show_volume: 是否显示成交量。
        width: 图表宽度。
        height: 图表高度。
        output_path: 若指定，导出为 HTML 文件路径。

    Returns:
        plotly Figure 对象。
    """
    if not bars:
        fig = go.Figure()
        fig.update_layout(title="无数据", width=width, height=height)
        return fig

    # 子图布局
    rows = 2 if show_volume else 1
    row_heights = [0.75, 0.25] if show_volume else [1.0]
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
    )

    dates = [bar.date for bar in bars]
    opens = [bar.open for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    amounts = [bar.amount for bar in bars]

    # 用整数索引作为 x 轴，去除非交易日间隔
    x_idx = list(range(len(bars)))

    # 计算涨幅用于 hover
    prev_closes = [closes[0]] + closes[:-1]
    changes = [(c - p) / p * 100 if p > 0 else 0 for c, p in zip(closes, prev_closes)]

    # 构建 hover 文本（日期、OHLC、涨幅、成交量）
    hover_texts = [
        f"{dates[i]}<br>"
        f"开 {opens[i]:.2f}  高 {highs[i]:.2f}<br>"
        f"低 {lows[i]:.2f}  收 {closes[i]:.2f}<br>"
        f"涨幅 {changes[i]:+.2f}%<br>"
        f"成交量 {volumes[i]:,.0f}"
        for i in range(len(bars))
    ]

    # ── 蜡烛图：涨停实心红 / 阳线空心红 / 阴线实心绿 ──
    lu, bu, be = _classify_bars(bars, symbol)

    # 1. 涨停 — 红色实心
    fig.add_trace(
        go.Candlestick(
            x=x_idx,
            open=lu[0],
            high=lu[1],
            low=lu[2],
            close=lu[3],
            increasing_line_color="red",
            increasing_fillcolor="red",
            decreasing_line_color="red",
            decreasing_fillcolor="red",
            text=hover_texts,
            hoverinfo="text",
            name="涨停",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # 2. 阳线 — 红色空心（红边白心）
    fig.add_trace(
        go.Candlestick(
            x=x_idx,
            open=bu[0],
            high=bu[1],
            low=bu[2],
            close=bu[3],
            increasing_line_color="red",
            increasing_fillcolor="white",
            decreasing_line_color="red",
            decreasing_fillcolor="white",
            text=hover_texts,
            hoverinfo="text",
            name="阳线",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # 3. 阴线 — 绿色实心
    fig.add_trace(
        go.Candlestick(
            x=x_idx,
            open=be[0],
            high=be[1],
            low=be[2],
            close=be[3],
            increasing_line_color="green",
            increasing_fillcolor="green",
            decreasing_line_color="green",
            decreasing_fillcolor="green",
            text=hover_texts,
            hoverinfo="text",
            name="阴线",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # 成交量柱状图（涨停=红色，阳线=红色，阴线=绿色）
    if show_volume:
        vol_colors = []
        for i, bar in enumerate(bars):
            if bar.close < bar.open:
                vol_colors.append("green")
            else:
                vol_colors.append("red")
        # 涨停日加深红色
        for i, bar in enumerate(bars):
            if i > 0:
                prev_close = bars[i - 1].close
                limit_pct = _limit_up_pct(symbol)
                chg = (bar.close - prev_close) / prev_close if prev_close > 0 else 0
                if chg >= limit_pct - 0.005 and bar.close >= bar.open:
                    vol_colors[i] = "#CC0000"  # 深红

        vol_hover = [
            f"{dates[i]}<br>成交量 {volumes[i]:,.0f}<br>成交额 {amounts[i]:,.0f}"
            for i in range(len(bars))
        ]
        fig.add_trace(
            go.Bar(
                x=x_idx,
                y=volumes,
                marker_color=vol_colors,
                text=vol_hover,
                hoverinfo="text",
                name="成交量",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # 构建日期→索引映射（用于标注定位）
    date_to_idx = {bar.date: i for i, bar in enumerate(bars)}

    # 点标注
    if annotations:
        for ann in annotations:
            marker_symbol = _map_marker_symbol(ann.symbol)
            ann_x = date_to_idx.get(ann.date, ann.date)
            fig.add_trace(
                go.Scatter(
                    x=[ann_x],
                    y=[ann.price],
                    mode="markers+text",
                    marker=dict(
                        symbol=marker_symbol,
                        color=ann.color,
                        size=ann.size,
                    ),
                    text=[ann.text],
                    textposition="top center",
                    name=ann.text,
                    showlegend=False,
                ),
                row=1,
                col=1,
            )

    # 水平参考线
    if hlines:
        for hl in hlines:
            fig.add_hline(
                y=hl.price,
                line_dash=hl.dash,
                line_color=hl.color,
                line_width=hl.width,
                annotation_text=hl.label,
                annotation_position="top left",
                row=1,
                col=1,
            )

    # 区间高亮
    if highlight_ranges:
        for hr in highlight_ranges:
            x0 = date_to_idx.get(hr.start_date, hr.start_date)
            x1 = date_to_idx.get(hr.end_date, hr.end_date)
            fig.add_vrect(
                x0=x0,
                x1=x1,
                fillcolor=hr.color,
                layer="below",
                line_width=0,
                annotation_text=hr.label,
                annotation_position="top left",
                row=1,
                col=1,
            )

    # ── 布局 ──
    fig.update_layout(
        title=title,
        width=width,
        height=height,
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        showlegend=True,
        # 十字光标贯穿整个图表
        hovermode="x unified",
        xaxis=dict(
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikedash="dot",
            spikecolor="gray",
            spikethickness=1,
        ),
        yaxis=dict(
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikedash="dot",
            spikecolor="gray",
            spikethickness=1,
        ),
    )

    # X轴：用日期标签替换数字索引，去除非交易日间隙
    tick_step = max(1, len(dates) // 20)  # 约20个刻度
    tick_vals = list(range(0, len(dates), tick_step))
    tick_text = [dates[i] for i in tick_vals]
    fig.update_xaxes(
        tickvals=tick_vals,
        ticktext=tick_text,
        tickangle=45,
        row=1,
        col=1,
    )
    if show_volume:
        fig.update_xaxes(
            tickvals=tick_vals,
            ticktext=tick_text,
            tickangle=45,
            row=2,
            col=1,
        )

    fig.update_yaxes(title_text="价格", row=1, col=1)
    if show_volume:
        fig.update_yaxes(title_text="成交量", row=2, col=1)

    # 导出
    if output_path:
        fig.write_html(output_path)

    return fig


def plot_trade_lifecycle(
    bars: list[DailyBar],
    trade: TradeLifecycle,
    output_path: str | None = None,
) -> go.Figure:
    """可视化单笔交易的生命周期。

    图表包含：
    1. 上半部分：K线图 + 买卖标注 + 止损/止盈线
    2. 下半部分：逐日R值曲线

    标注：
    - 买入点（绿色三角向上）
    - 退出点（红色三角向下/蓝色圆形）
    - 止损线（红色虚线）
    - key_low线（蓝色虚线）
    - R=2.5 目标线（橙色虚线，在R值图中）
    - 半仓止盈事件标记
    - 止损事件标记
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
    )

    dates = [bar.date for bar in bars]
    opens = [bar.open for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    closes = [bar.close for bar in bars]

    # 用整数索引作为 x 轴，去除非交易日间隔
    x_idx = list(range(len(bars)))
    date_to_idx = {bar.date: i for i, bar in enumerate(bars)}

    # ── Row 1: K线 + 标注 ──────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=x_idx,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            increasing_line_color="red",
            decreasing_line_color="green",
            name="K线",
        ),
        row=1,
        col=1,
    )

    # 止损线（红色虚线）
    fig.add_hline(
        y=trade.stop_loss_price,
        line_dash="dash",
        line_color="red",
        line_width=1,
        annotation_text=f"止损 {trade.stop_loss_price:.2f}",
        annotation_position="top left",
        row=1,
        col=1,
    )

    # key_low 线（蓝色虚线）
    fig.add_hline(
        y=trade.key_low,
        line_dash="dot",
        line_color="blue",
        line_width=1,
        annotation_text=f"key_low {trade.key_low:.2f}",
        annotation_position="bottom left",
        row=1,
        col=1,
    )

    # 买入点（绿色三角向上）
    buy_x = date_to_idx.get(trade.signal_date, trade.signal_date)
    fig.add_trace(
        go.Scatter(
            x=[buy_x],
            y=[trade.entry_price],
            mode="markers+text",
            marker=dict(symbol="triangle-up", color="green", size=14),
            text=[f"买入 {trade.entry_price:.2f}"],
            textposition="bottom center",
            name="买入",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # 持仓区间高亮
    if trade.exit_date:
        vrect_x0 = date_to_idx.get(trade.signal_date, trade.signal_date)
        vrect_x1 = date_to_idx.get(trade.exit_date, trade.exit_date)
        fig.add_vrect(
            x0=vrect_x0,
            x1=vrect_x1,
            fillcolor="rgba(0,200,0,0.08)",
            layer="below",
            line_width=0,
            row=1,
            col=1,
        )

    # 退出点标注 + 事件标注
    _add_trade_event_markers(fig, trade, date_to_idx)

    # ── Row 2: R值曲线 ────────────────────────────────────
    event_dates = [e["date"] for e in trade.daily_events]
    event_x = [date_to_idx.get(e["date"], e["date"]) for e in trade.daily_events]
    r_values = [e.get("r_ratio", 0) for e in trade.daily_events]

    if event_dates:
        fig.add_trace(
            go.Scatter(
                x=event_x,
                y=r_values,
                mode="lines+markers",
                line=dict(color="purple", width=1.5),
                marker=dict(size=4),
                name="R值",
            ),
            row=2,
            col=1,
        )

        # R=2.5 目标线
        fig.add_hline(
            y=2.5,
            line_dash="dash",
            line_color="orange",
            line_width=1,
            annotation_text="R=2.5",
            annotation_position="top left",
            row=2,
            col=1,
        )

        # R=0 基准线
        fig.add_hline(
            y=0,
            line_dash="dot",
            line_color="gray",
            line_width=1,
            row=2,
            col=1,
        )

    # ── 布局 ──────────────────────────────────────────────
    title_text = (
        f"{trade.symbol} 交易生命周期 — "
        f"买入 {trade.entry_price:.2f} → "
        f"{trade.exit_reason} "
        f"({trade.holding_days}天, 收益 {trade.total_return:.1%})"
    )
    fig.update_layout(
        title=title_text,
        width=1200,
        height=900,
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        showlegend=False,
    )

    # X轴日期标签
    tick_step = max(1, len(dates) // 15)
    tick_vals = list(range(0, len(dates), tick_step))
    tick_text = [dates[i] for i in tick_vals]
    fig.update_xaxes(tickvals=tick_vals, ticktext=tick_text, tickangle=45, row=1, col=1)
    fig.update_xaxes(tickvals=tick_vals, ticktext=tick_text, tickangle=45, row=2, col=1)

    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="R值", row=2, col=1)

    if output_path:
        fig.write_html(output_path)

    return fig


def _add_trade_event_markers(
    fig: go.Figure, trade: TradeLifecycle, date_to_idx: dict[str, int] | None = None
) -> None:
    """在 K 线图上添加退出点和事件标注。"""
    if date_to_idx is None:
        date_to_idx = {}
    # 退出点
    if trade.exit_date and trade.exit_price is not None:
        if trade.exit_reason == "止损":
            color, marker, label = (
                "red",
                "triangle-down",
                f"止损 {trade.exit_price:.2f}",
            )
        elif trade.exit_reason == "半仓止盈后趋势破坏":
            color, marker, label = (
                "purple",
                "triangle-down",
                f"趋势破坏 {trade.exit_price:.2f}",
            )
        elif trade.exit_reason == "持有到期":
            color, marker, label = "gray", "circle", f"到期退出 {trade.exit_price:.2f}"
        else:
            color, marker, label = "blue", "circle", f"退出 {trade.exit_price:.2f}"

        exit_x = date_to_idx.get(trade.exit_date, trade.exit_date)
        fig.add_trace(
            go.Scatter(
                x=[exit_x],
                y=[trade.exit_price],
                mode="markers+text",
                marker=dict(symbol=marker, color=color, size=14),
                text=[label],
                textposition="top center",
                name="退出",
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    # 逐日事件中的半仓止盈和止损标记
    for event in trade.daily_events:
        evt = event.get("event", "")
        evt_date = event.get("date", "")
        evt_x = date_to_idx.get(evt_date, evt_date)
        if evt == "半仓止盈":
            trigger_price = event.get("trigger_price", trade.entry_price)
            fig.add_trace(
                go.Scatter(
                    x=[evt_x],
                    y=[trigger_price],
                    mode="markers+text",
                    marker=dict(symbol="diamond", color="orange", size=12),
                    text=[f"半仓止盈 R={trade.half_profit_r:.1f}"],
                    textposition="top center",
                    name="半仓止盈",
                    showlegend=False,
                ),
                row=1,
                col=1,
            )
        elif evt == "止损退出":
            fig.add_trace(
                go.Scatter(
                    x=[evt_x],
                    y=[trade.stop_loss_price],
                    mode="markers+text",
                    marker=dict(symbol="x", color="red", size=12),
                    text=["止损触发"],
                    textposition="top center",
                    name="止损触发",
                    showlegend=False,
                ),
                row=1,
                col=1,
            )


def plot_signal_chart(
    bars: list[DailyBar],
    signal_idx: int,
    symbol: str = "",
    key_low: float | None = None,
    stop_loss_price: float | None = None,
    trend_break_ref: float | None = None,
    entry_price: float | None = None,
    output_path: str | None = None,
) -> go.Figure:
    """在K线图上标注买卖信号、止损线、key_low、止盈目标。

    标注层：
    1. 买入信号标注（绿色三角向上）
    2. 止损水平线（红色虚线）
    3. key_low 水平线（蓝色虚线）
    4. 止盈目标R=2.5水平线（橙色虚线）
    5. 趋势破坏参考线（紫色虚线，如果高于key_low）
    6. 回调区间高亮（signal_idx前30日到信号日）

    Args:
        bars: 日K线数据。
        signal_idx: 信号日在 bars 中的索引。
        symbol: 股票代码（用于标题）。
        key_low: 关键低点价格。若为 None，自动计算。
        stop_loss_price: 止损价。若为 None，自动计算。
        trend_break_ref: 趋势破坏参考位。若为 None 且高于 key_low 则显示。
        entry_price: 买入价。若为 None，取信号日收盘价。
        output_path: 若指定，导出为 HTML 文件路径。

    Returns:
        plotly Figure 对象。
    """
    from .kline import find_key_low

    # 自动获取参数
    if entry_price is None:
        entry_price = bars[signal_idx].close
    if key_low is None:
        window = bars[: signal_idx + 1]
        key_low, _, _ = find_key_low(window)
    if stop_loss_price is None:
        stop_loss_price = max(entry_price * 0.95, key_low)

    signal_date = bars[signal_idx].date
    risk = entry_price - key_low
    target_2_5r = entry_price + 2.5 * risk if risk > 0 else entry_price

    # 构建标题
    title_parts: list[str] = []
    if symbol:
        title_parts.append(symbol)
    title_parts.append(f"信号日 {signal_date}")
    title_parts.append(f"买入 {entry_price:.2f}")
    title_parts.append(f"止损 {stop_loss_price:.2f}")
    title_parts.append(f"R=2.5 目标 {target_2_5r:.2f}")
    title = " | ".join(title_parts)

    # 1. 买入信号标注（绿色三角向上）
    annotations = [
        ChartAnnotation(
            date=signal_date,
            price=entry_price,
            text=f"买入 {entry_price:.2f}",
            color="green",
            symbol="triangle-up",
            size=14,
        )
    ]

    # 2-5. 水平参考线
    hlines: list[ChartHLine] = []

    # 止损线（红色虚线）
    hlines.append(
        ChartHLine(
            price=stop_loss_price,
            color="red",
            dash="dash",
            label=f"止损 {stop_loss_price:.2f}",
            width=1,
        )
    )

    # key_low 线（蓝色虚线）
    hlines.append(
        ChartHLine(
            price=key_low,
            color="blue",
            dash="dot",
            label=f"key_low {key_low:.2f}",
            width=1,
        )
    )

    # 止盈目标 R=2.5 线（橙色虚线）
    hlines.append(
        ChartHLine(
            price=target_2_5r,
            color="orange",
            dash="dash",
            label=f"R=2.5 目标 {target_2_5r:.2f}",
            width=1,
        )
    )

    # 趋势破坏参考线（紫色虚线，如果高于key_low）
    if trend_break_ref is not None and trend_break_ref > key_low:
        hlines.append(
            ChartHLine(
                price=trend_break_ref,
                color="purple",
                dash="dash",
                label=f"趋势破坏参考 {trend_break_ref:.2f}",
                width=1,
            )
        )

    # 6. 回调区间高亮（signal_idx前30日到信号日）
    highlight_start_idx = max(0, signal_idx - 30)
    highlight_ranges = [
        ChartRange(
            start_date=bars[highlight_start_idx].date,
            end_date=signal_date,
            color="rgba(100,149,237,0.1)",  # 矢车菊蓝半透明
            label="回调区间",
        )
    ]

    return plot_stock_kline(
        bars=bars,
        title=title,
        annotations=annotations,
        hlines=hlines,
        highlight_ranges=highlight_ranges,
        output_path=output_path,
    )


def _map_marker_symbol(name: str) -> str:
    """将友好名称映射为 plotly marker symbol。"""
    mapping = {
        "star": "star",
        "triangle-up": "triangle-up",
        "triangle-down": "triangle-down",
        "diamond": "diamond",
        "cross": "x",
        "circle": "circle",
    }
    return mapping.get(name, "circle")


def plot_portfolio_dashboard(
    stats: PortfolioStats,
    output_path: str | None = None,
) -> go.Figure:
    """组合级回测仪表盘。

    子图布局 (2x2 grid)：
    1. 左上：净值曲线（总资产随时间变化）
    2. 右上：月度收益柱状图
    3. 左下：交易分布（按退出方式的收益散点图）
    4. 右下：关键统计指标文本卡片

    Args:
        stats: PortfolioStats 组合统计对象。
        output_path: 若指定，导出为 HTML 文件路径。

    Returns:
        plotly Figure 对象。
    """
    if not stats.nav_curve:
        fig = go.Figure()
        fig.update_layout(
            title="组合回测仪表盘（无数据）",
            width=1200,
            height=800,
            template="plotly_white",
        )
        if output_path:
            fig.write_html(output_path)
        return fig

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=("净值曲线", "月度收益", "交易分布", "关键统计"),
    )

    # ─── 左上：净值曲线 ──────────────────────────────────
    dates = [nav.date for nav in stats.nav_curve]
    values = [nav.total_value for nav in stats.nav_curve]
    initial = values[0] if values[0] > 0 else 1.0
    norm_values = [v / initial for v in values]

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=norm_values,
            mode="lines",
            line=dict(color="royalblue", width=2),
            name="净值",
        ),
        row=1,
        col=1,
    )

    # 峰值线（用于展示回撤区域）
    peak = norm_values[0]
    peak_dates: list[str] = []
    peak_values: list[float] = []
    for i, nv in enumerate(norm_values):
        if nv > peak:
            peak = nv
        peak_dates.append(dates[i])
        peak_values.append(peak)
    fig.add_trace(
        go.Scatter(
            x=peak_dates,
            y=peak_values,
            mode="lines",
            line=dict(color="rgba(0,0,0,0.15)", width=1, dash="dot"),
            name="峰值",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # ─── 右上：月度收益柱状图 ─────────────────────────────
    monthly_data = _compute_monthly_returns(stats)
    if monthly_data:
        m_labels = [m["month"] for m in monthly_data]
        m_returns = [m["return"] for m in monthly_data]
        m_colors = ["green" if r >= 0 else "red" for r in m_returns]
        m_texts = [f"{r:.1%}" for r in m_returns]

        fig.add_trace(
            go.Bar(
                x=m_labels,
                y=m_returns,
                marker_color=m_colors,
                text=m_texts,
                textposition="auto",
                name="月度收益",
                showlegend=False,
            ),
            row=1,
            col=2,
        )

    # ─── 左下：交易分布（按退出方式柱状图）──────────────
    exit_labels = ["止损", "趋势破坏退出", "持有到期"]
    exit_counts = [
        stats.stop_loss_count,
        stats.take_profit_count,
        stats.natural_exit_count,
    ]
    exit_colors = ["red", "orange", "gray"]

    for label, count, color in zip(exit_labels, exit_counts, exit_colors):
        if count > 0:
            fig.add_trace(
                go.Bar(
                    x=[label],
                    y=[count],
                    marker_color=color,
                    text=str(count),
                    textposition="auto",
                    name=label,
                    showlegend=True,
                ),
                row=2,
                col=1,
            )

    # ─── 右下：统计卡片 ──────────────────────────────────
    stop_loss_rate = stats.stop_loss_count / max(stats.total_trades, 1)
    stats_text = (
        f"总收益率: {stats.total_return:.1%}\n"
        f"最大回撤: {stats.max_drawdown:.1%}\n"
        f"夏普比率: {stats.sharpe_ratio:.2f}\n"
        f"胜率: {stats.win_rate:.1%}\n"
        f"盈亏比: {stats.profit_loss_ratio:.2f}\n"
        f"止损率: {stop_loss_rate:.1%}\n"
        f"平均持有天数: {stats.avg_holding_days:.1f}"
    )

    fig.add_trace(
        go.Scatter(
            x=[0.5],
            y=[0.5],
            mode="text",
            text=[stats_text],
            textfont=dict(size=14, family="monospace"),
            textposition="middle center",
            showlegend=False,
            hoverinfo="skip",
        ),
        row=2,
        col=2,
    )

    # ─── 布局 ──────────────────────────────────────────────
    fig.update_layout(
        title="组合级回测仪表盘",
        width=1200,
        height=800,
        template="plotly_white",
        showlegend=True,
    )
    fig.update_yaxes(title_text="净值", row=1, col=1)
    fig.update_yaxes(title_text="收益率", row=1, col=2, tickformat=".0%")
    fig.update_yaxes(title_text="笔数", row=2, col=1)
    fig.update_xaxes(visible=False, showgrid=False, zeroline=False, row=2, col=2)
    fig.update_yaxes(visible=False, showgrid=False, zeroline=False, row=2, col=2)

    if output_path:
        fig.write_html(output_path)

    return fig


def plot_combined_trade_chart(
    bars: list[DailyBar],
    signal_idx: int,
    trade: TradeLifecycle,
    key_low: float | None = None,
    stop_loss_price: float | None = None,
    trend_break_ref: float | None = None,
    output_path: str | None = None,
) -> go.Figure:
    """合并信号标注 + 波峰波谷结构 + 生命周期为一张综合图表。

    三行子图布局：
      Row 1 (60%): K线 + 全部标注层（买卖信号、止损/key_low/R=2.5线、
                   波峰波谷、higher highs/lows 连线、持仓区间高亮）
      Row 2 (15%): 成交量柱状图
      Row 3 (25%): 逐日 R 值曲线

    Args:
        bars: 日K线数据。
        signal_idx: 信号日在 bars 中的索引。
        trade: TradeLifecycle 交易生命周期对象。
        key_low: 关键低点价格。若为 None，使用 trade.key_low。
        stop_loss_price: 止损价。若为 None，使用 trade.stop_loss_price。
        trend_break_ref: 趋势破坏参考位。
        output_path: 若指定，导出为 HTML 文件路径。

    Returns:
        plotly Figure 对象。
    """
    from .kline import (
        find_key_low,
        find_swing_highs,
        find_swing_lows,
    )

    if key_low is None:
        key_low = trade.key_low
    if stop_loss_price is None:
        stop_loss_price = trade.stop_loss_price

    entry_price = trade.entry_price
    risk = entry_price - stop_loss_price
    target_2_5r = entry_price + 2.5 * risk if risk > 0 else entry_price

    # ── 创建 3 行子图 ───────────────────────────────────────
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.60, 0.15, 0.25],
    )

    dates = [bar.date for bar in bars]
    opens = [bar.open for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    amounts = [bar.amount for bar in bars]
    x_idx = list(range(len(bars)))
    date_to_idx = {bar.date: i for i, bar in enumerate(bars)}

    # 计算涨幅用于 hover
    prev_closes = [closes[0]] + closes[:-1]
    changes = [(c - p) / p * 100 if p > 0 else 0 for c, p in zip(closes, prev_closes)]

    hover_texts = [
        f"{dates[i]}<br>"
        f"开 {opens[i]:.2f}  高 {highs[i]:.2f}<br>"
        f"低 {lows[i]:.2f}  收 {closes[i]:.2f}<br>"
        f"涨幅 {changes[i]:+.2f}%<br>"
        f"成交量 {volumes[i]:,.0f}"
        for i in range(len(bars))
    ]

    # ── Row 1: K 线蜡烛图（涨停实心红 / 阳线空心红 / 阴线实心绿）──
    symbol = trade.symbol
    lu, bu, be = _classify_bars(bars, symbol)

    for lu_o, lu_h, lu_l, lu_c, name, inc_c, inc_f, dec_c, dec_f in [
        (lu[0], lu[1], lu[2], lu[3], "涨停", "red", "red", "red", "red"),
        (bu[0], bu[1], bu[2], bu[3], "阳线", "red", "white", "red", "white"),
        (be[0], be[1], be[2], be[3], "阴线", "green", "green", "green", "green"),
    ]:
        fig.add_trace(
            go.Candlestick(
                x=x_idx,
                open=lu_o,
                high=lu_h,
                low=lu_l,
                close=lu_c,
                increasing_line_color=inc_c,
                increasing_fillcolor=inc_f,
                decreasing_line_color=dec_c,
                decreasing_fillcolor=dec_f,
                text=hover_texts,
                hoverinfo="text",
                name=name,
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    # ── Row 1: 水平参考线 ──────────────────────────────────
    # 止损线
    fig.add_hline(
        y=stop_loss_price,
        line_dash="dash",
        line_color="red",
        line_width=1,
        annotation_text=f"止损 {stop_loss_price:.2f}",
        annotation_position="top left",
        row=1,
        col=1,
    )
    # key_low 线
    fig.add_hline(
        y=key_low,
        line_dash="dot",
        line_color="blue",
        line_width=1,
        annotation_text=f"key_low {key_low:.2f}",
        annotation_position="bottom left",
        row=1,
        col=1,
    )
    # R=2.5 目标线
    fig.add_hline(
        y=target_2_5r,
        line_dash="dash",
        line_color="orange",
        line_width=1,
        annotation_text=f"R=2.5 目标 {target_2_5r:.2f}",
        annotation_position="top left",
        row=1,
        col=1,
    )
    # 趋势破坏参考线（如果高于 key_low）
    if trend_break_ref is not None and trend_break_ref > key_low:
        fig.add_hline(
            y=trend_break_ref,
            line_dash="dash",
            line_color="purple",
            line_width=1,
            annotation_text=f"趋势破坏 {trend_break_ref:.2f}",
            annotation_position="top left",
            row=1,
            col=1,
        )

    # ── Row 1: 买入信号标注（绿色三角）──────────────────────
    buy_x = date_to_idx.get(trade.signal_date, signal_idx)
    fig.add_trace(
        go.Scatter(
            x=[buy_x],
            y=[entry_price],
            mode="markers+text",
            marker=dict(symbol="triangle-up", color="green", size=14),
            text=[f"买入 {entry_price:.2f}"],
            textposition="bottom center",
            name="买入",
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # ── Row 1: 回调区间高亮 ─────────────────────────────────
    pullback_start = max(0, signal_idx - 30)
    fig.add_vrect(
        x0=pullback_start,
        x1=signal_idx,
        fillcolor="rgba(100,149,237,0.1)",
        layer="below",
        line_width=0,
        annotation_text="回调区间",
        annotation_position="top left",
        row=1,
        col=1,
    )

    # ── Row 1: 持仓区间高亮 ─────────────────────────────────
    if trade.exit_date:
        exit_x = date_to_idx.get(trade.exit_date)
        if exit_x is not None:
            fig.add_vrect(
                x0=buy_x,
                x1=exit_x,
                fillcolor="rgba(0,200,0,0.08)",
                layer="below",
                line_width=0,
                row=1,
                col=1,
            )

    # ── Row 1: 退出点 + 事件标注 ────────────────────────────
    _add_trade_event_markers(fig, trade, date_to_idx)

    # ── Row 1: 波峰波谷结构标注 ─────────────────────────────
    swing_highs = find_swing_highs(bars)
    swing_lows = find_swing_lows(bars)

    # Swing Highs
    if swing_highs:
        sh_x = [idx for idx, _ in swing_highs]
        sh_prices = [high for _, high in swing_highs]
        fig.add_trace(
            go.Scatter(
                x=sh_x,
                y=sh_prices,
                mode="markers+text",
                marker=dict(symbol="triangle-down", color="red", size=8),
                text=[f"{high:.2f}" for _, high in swing_highs],
                textposition="top center",
                textfont=dict(color="red", size=8),
                name="Swing High",
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # Swing Lows
    if swing_lows:
        sl_x = [idx for idx, _ in swing_lows]
        sl_prices = [low for _, low in swing_lows]
        fig.add_trace(
            go.Scatter(
                x=sl_x,
                y=sl_prices,
                mode="markers+text",
                marker=dict(symbol="triangle-up", color="green", size=8),
                text=[f"{low:.2f}" for _, low in swing_lows],
                textposition="bottom center",
                textfont=dict(color="green", size=8),
                name="Swing Low",
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # Higher Highs 连线
    if swing_highs:
        hh_x: list[int] = []
        hh_prices: list[float] = []
        for i in range(1, len(swing_highs)):
            idx_i, high_i = swing_highs[i]
            _, high_prev = swing_highs[i - 1]
            if high_i > high_prev:
                if not hh_x:
                    hh_x.append(swing_highs[i - 1][0])
                    hh_prices.append(high_prev)
                hh_x.append(idx_i)
                hh_prices.append(high_i)
        if len(hh_x) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=hh_x,
                    y=hh_prices,
                    mode="lines",
                    line=dict(color="red", width=1.5, dash="dash"),
                    name="Higher Highs",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

    # Higher Lows 连线
    if swing_lows:
        hl_x: list[int] = []
        hl_prices: list[float] = []
        for i in range(1, len(swing_lows)):
            idx_i, low_i = swing_lows[i]
            _, low_prev = swing_lows[i - 1]
            if low_i > low_prev:
                if not hl_x:
                    hl_x.append(swing_lows[i - 1][0])
                    hl_prices.append(low_prev)
                hl_x.append(idx_i)
                hl_prices.append(low_i)
        if len(hl_x) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=hl_x,
                    y=hl_prices,
                    mode="lines",
                    line=dict(color="green", width=1.5, dash="dash"),
                    name="Higher Lows",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

    # Key Low 星号标注
    window = bars[: signal_idx + 1]
    _kl_val, _kl_src, kl_idx = find_key_low(window)
    if 0 <= kl_idx < len(bars):
        fig.add_trace(
            go.Scatter(
                x=[kl_idx],
                y=[_kl_val],
                mode="markers+text",
                marker=dict(symbol="star", color="blue", size=16),
                text=[f"Key Low {_kl_val:.2f}"],
                textposition="bottom center",
                textfont=dict(color="blue", size=10),
                name="Key Low",
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # ── Row 2: 成交量 ──────────────────────────────────────
    vol_colors = []
    for bar in bars:
        vol_colors.append("green" if bar.close < bar.open else "red")

    vol_hover = [
        f"{dates[i]}<br>成交量 {volumes[i]:,.0f}<br>成交额 {amounts[i]:,.0f}"
        for i in range(len(bars))
    ]
    fig.add_trace(
        go.Bar(
            x=x_idx,
            y=volumes,
            marker_color=vol_colors,
            text=vol_hover,
            hoverinfo="text",
            name="成交量",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # ── Row 3: R 值曲线 ────────────────────────────────────
    event_dates = [e["date"] for e in trade.daily_events]
    event_x = [date_to_idx.get(e["date"], e["date"]) for e in trade.daily_events]
    r_values = [e.get("r_ratio", 0) for e in trade.daily_events]

    if event_dates:
        fig.add_trace(
            go.Scatter(
                x=event_x,
                y=r_values,
                mode="lines+markers",
                line=dict(color="purple", width=1.5),
                marker=dict(size=4),
                name="R值",
                showlegend=True,
            ),
            row=3,
            col=1,
        )
        # R=2.5 目标线
        fig.add_hline(
            y=2.5,
            line_dash="dash",
            line_color="orange",
            line_width=1,
            annotation_text="R=2.5",
            annotation_position="top left",
            row=3,
            col=1,
        )
        # R=0 基准线
        fig.add_hline(
            y=0,
            line_dash="dot",
            line_color="gray",
            line_width=1,
            row=3,
            col=1,
        )

    # ── 布局 ──────────────────────────────────────────────
    # 退出理由摘要
    exit_info = ""
    if trade.exit_reason and trade.exit_reason != "未退出":
        exit_info = f" → {trade.exit_reason}"
    stop_type_info = f" ({trade.stop_loss_type})" if trade.stop_loss_type else ""

    title_text = (
        f"{trade.symbol} 综合图表 — "
        f"买入 {entry_price:.2f}"
        f"{exit_info}{stop_type_info} "
        f"({trade.holding_days}天, 收益 {trade.total_return:.1%})"
    )

    fig.update_layout(
        title=title_text,
        width=1400,
        height=1000,
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        showlegend=True,
        hovermode="x unified",
        xaxis=dict(
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikedash="dot",
            spikecolor="gray",
            spikethickness=1,
        ),
        yaxis=dict(
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikedash="dot",
            spikecolor="gray",
            spikethickness=1,
        ),
    )

    # X 轴日期标签
    tick_step = max(1, len(dates) // 20)
    tick_vals = list(range(0, len(dates), tick_step))
    tick_text = [dates[i] for i in tick_vals]
    for row in [1, 2, 3]:
        fig.update_xaxes(
            tickvals=tick_vals,
            ticktext=tick_text,
            tickangle=45,
            row=row,
            col=1,
        )

    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    fig.update_yaxes(title_text="R值", row=3, col=1)

    if output_path:
        fig.write_html(output_path)

    return fig


def _compute_monthly_returns(stats: PortfolioStats) -> list[dict]:
    """从 nav_curve 中按月聚合收益率。"""
    from collections import OrderedDict

    month_ends: OrderedDict[str, float] = OrderedDict()
    for nav in stats.nav_curve:
        month = nav.date[:7]
        month_ends[month] = nav.total_value

    result: list[dict] = []
    prev_value: float | None = None
    for month, end_value in month_ends.items():
        if prev_value is not None and prev_value > 0:
            ret = (end_value - prev_value) / prev_value
            result.append({"month": month, "return": round(ret, 4)})
        prev_value = end_value

    return result


def plot_structure_chart(
    bars: list[DailyBar],
    signal_idx: int,
    symbol: str = "",
    output_path: str | None = None,
) -> go.Figure:
    """在K线图上标注波峰波谷结构和趋势线。

    标注层：
    1. Swing Highs（红色圆点，向下箭头文字"高"）
    2. Swing Lows（绿色圆点，向上箭头文字"低"）
    3. Higher Highs 连线（红色上升趋势线）
    4. Higher Lows 连线（绿色上升趋势线）
    5. Key Low 特别标注（大蓝色星号）
    6. 趋势破坏参考位标注（紫色线）
    """
    from .kline import (
        find_key_low,
        find_swing_highs,
        find_swing_lows,
        find_trend_break_ref,
    )

    if not bars or signal_idx < 0 or signal_idx >= len(bars):
        fig = go.Figure()
        fig.update_layout(title="无效数据", width=1200, height=800)
        return fig

    # 1. 先画基础K线图
    fig = plot_stock_kline(
        bars=bars,
        title=f"{symbol} 波峰波谷结构与趋势线",
        show_volume=True,
        width=1200,
        height=800,
    )

    # 2. 检测 swing highs 和 swing lows
    swing_highs = find_swing_highs(bars)
    swing_lows = find_swing_lows(bars)

    # 3. 获取 key_low 信息
    window = bars[: signal_idx + 1]
    key_low_val, _key_low_source, key_low_idx = find_key_low(window)

    # 4. Swing Highs 标注（红色圆点 + 文字"高"）
    if swing_highs:
        sh_x = [idx for idx, _ in swing_highs]
        sh_prices = [high for _, high in swing_highs]
        sh_texts = [f"高 {high:.2f}" for _, high in swing_highs]
        fig.add_trace(
            go.Scatter(
                x=sh_x,
                y=sh_prices,
                mode="markers+text",
                marker=dict(symbol="triangle-down", color="red", size=10),
                text=sh_texts,
                textposition="top center",
                textfont=dict(color="red", size=9),
                name="Swing High",
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # 5. Swing Lows 标注（绿色圆点 + 文字"低"）
    if swing_lows:
        sl_x = [idx for idx, _ in swing_lows]
        sl_prices = [low for _, low in swing_lows]
        sl_texts = [f"低 {low:.2f}" for _, low in swing_lows]
        fig.add_trace(
            go.Scatter(
                x=sl_x,
                y=sl_prices,
                mode="markers+text",
                marker=dict(symbol="triangle-up", color="green", size=10),
                text=sl_texts,
                textposition="bottom center",
                textfont=dict(color="green", size=9),
                name="Swing Low",
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # 6. Higher Highs 连线（红色虚线）
    if swing_highs:
        hh_x: list[int] = []
        hh_prices: list[float] = []
        for i in range(1, len(swing_highs)):
            idx_i, high_i = swing_highs[i]
            _, high_prev = swing_highs[i - 1]
            if high_i > high_prev:
                if not hh_x:
                    hh_x.append(swing_highs[i - 1][0])
                    hh_prices.append(high_prev)
                hh_x.append(idx_i)
                hh_prices.append(high_i)
        if len(hh_x) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=hh_x,
                    y=hh_prices,
                    mode="lines",
                    line=dict(color="red", width=2, dash="dash"),
                    name="Higher Highs",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

    # 7. Higher Lows 连线（绿色虚线）
    if swing_lows:
        hl_x: list[int] = []
        hl_prices: list[float] = []
        for i in range(1, len(swing_lows)):
            idx_i, low_i = swing_lows[i]
            _, low_prev = swing_lows[i - 1]
            if low_i > low_prev:
                if not hl_x:
                    hl_x.append(swing_lows[i - 1][0])
                    hl_prices.append(low_prev)
                hl_x.append(idx_i)
                hl_prices.append(low_i)
        if len(hl_x) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=hl_x,
                    y=hl_prices,
                    mode="lines",
                    line=dict(color="green", width=2, dash="dash"),
                    name="Higher Lows",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

    # 8. Key Low 特别标注（大蓝色星号）
    if 0 <= key_low_idx < len(bars):
        fig.add_trace(
            go.Scatter(
                x=[key_low_idx],
                y=[key_low_val],
                mode="markers+text",
                marker=dict(symbol="star", color="blue", size=18),
                text=[f"Key Low {key_low_val:.2f}"],
                textposition="bottom center",
                textfont=dict(color="blue", size=11),
                name="Key Low",
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # 9. 趋势破坏参考位（紫色水平线）
    trend_ref, _trend_desc = find_trend_break_ref(bars, signal_idx, key_low_idx)
    fig.add_hline(
        y=trend_ref,
        line_dash="dot",
        line_color="purple",
        line_width=1.5,
        annotation_text=f"趋势破坏参考 {trend_ref:.2f}",
        annotation_position="top left",
        row=1,
        col=1,
    )

    # 导出
    if output_path:
        fig.write_html(output_path)

    return fig
