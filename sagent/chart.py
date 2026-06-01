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


def plot_stock_kline(
    bars: list[DailyBar],
    title: str = "",
    annotations: list[ChartAnnotation] | None = None,
    hlines: list[ChartHLine] | None = None,
    highlight_ranges: list[ChartRange] | None = None,
    show_volume: bool = True,
    width: int = 1200,
    height: int = 800,
    output_path: str | None = None,
) -> go.Figure:
    """绘制 K 线图（蜡烛图 + 成交量 + 标注层）。

    Args:
        bars: 日 K 线数据。
        title: 图表标题。
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

    # 蜡烛图 — 红涨绿跌
    fig.add_trace(
        go.Candlestick(
            x=dates,
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

    # 成交量柱状图
    if show_volume:
        vol_colors = ["red" if c >= o else "green" for c, o in zip(closes, opens)]
        fig.add_trace(
            go.Bar(
                x=dates,
                y=volumes,
                marker_color=vol_colors,
                name="成交量",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # 点标注
    if annotations:
        for ann in annotations:
            marker_symbol = _map_marker_symbol(ann.symbol)
            fig.add_trace(
                go.Scatter(
                    x=[ann.date],
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
            fig.add_vrect(
                x0=hr.start_date,
                x1=hr.end_date,
                fillcolor=hr.color,
                layer="below",
                line_width=0,
                annotation_text=hr.label,
                annotation_position="top left",
                row=1,
                col=1,
            )

    # 布局
    fig.update_layout(
        title=title,
        width=width,
        height=height,
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        showlegend=True,
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

    # ── Row 1: K线 + 标注 ──────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=dates,
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
    fig.add_trace(
        go.Scatter(
            x=[trade.signal_date],
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
        fig.add_vrect(
            x0=trade.signal_date,
            x1=trade.exit_date,
            fillcolor="rgba(0,200,0,0.08)",
            layer="below",
            line_width=0,
            row=1,
            col=1,
        )

    # 退出点标注 + 事件标注
    _add_trade_event_markers(fig, trade)

    # ── Row 2: R值曲线 ────────────────────────────────────
    event_dates = [e["date"] for e in trade.daily_events]
    r_values = [e.get("r_ratio", 0) for e in trade.daily_events]

    if event_dates:
        fig.add_trace(
            go.Scatter(
                x=event_dates,
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
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="R值", row=2, col=1)

    if output_path:
        fig.write_html(output_path)

    return fig


def _add_trade_event_markers(fig: go.Figure, trade: TradeLifecycle) -> None:
    """在 K 线图上添加退出点和事件标注。"""
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

        fig.add_trace(
            go.Scatter(
                x=[trade.exit_date],
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
        if evt == "半仓止盈":
            trigger_price = event.get("trigger_price", trade.entry_price)
            fig.add_trace(
                go.Scatter(
                    x=[evt_date],
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
                    x=[evt_date],
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
        sh_dates = [bars[idx].date for idx, _ in swing_highs]
        sh_prices = [high for _, high in swing_highs]
        sh_texts = [f"高 {high:.2f}" for _, high in swing_highs]
        fig.add_trace(
            go.Scatter(
                x=sh_dates,
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
        sl_dates = [bars[idx].date for idx, _ in swing_lows]
        sl_prices = [low for _, low in swing_lows]
        sl_texts = [f"低 {low:.2f}" for _, low in swing_lows]
        fig.add_trace(
            go.Scatter(
                x=sl_dates,
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
        hh_dates: list[str] = []
        hh_prices: list[float] = []
        for i in range(1, len(swing_highs)):
            idx_i, high_i = swing_highs[i]
            _, high_prev = swing_highs[i - 1]
            if high_i > high_prev:
                if not hh_dates:
                    prev_idx = swing_highs[i - 1][0]
                    hh_dates.append(bars[prev_idx].date)
                    hh_prices.append(high_prev)
                hh_dates.append(bars[idx_i].date)
                hh_prices.append(high_i)
        if len(hh_dates) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=hh_dates,
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
        hl_dates: list[str] = []
        hl_prices: list[float] = []
        for i in range(1, len(swing_lows)):
            idx_i, low_i = swing_lows[i]
            _, low_prev = swing_lows[i - 1]
            if low_i > low_prev:
                if not hl_dates:
                    prev_idx = swing_lows[i - 1][0]
                    hl_dates.append(bars[prev_idx].date)
                    hl_prices.append(low_prev)
                hl_dates.append(bars[idx_i].date)
                hl_prices.append(low_i)
        if len(hl_dates) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=hl_dates,
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
        kl_date = bars[key_low_idx].date
        fig.add_trace(
            go.Scatter(
                x=[kl_date],
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
