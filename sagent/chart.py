"""K 线绘图基础模块（plotly）。

绘制日本蜡烛图（红涨绿跌）+ 成交量柱状图 + 标注层。
输出为 plotly Figure 对象或独立 HTML 文件，不依赖 GUI 环境。
"""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

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
