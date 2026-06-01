# #33 K 线绘图基础模块（plotly）实施结果

## 新建文件
- `sagent/chart.py` — K 线绘图核心模块

## 修改文件
- `sagent/models.py` — 新增 ChartAnnotation, ChartHLine, ChartRange 数据结构
- `tests/test_sagent_behaviors.py` — 新增 3 个测试用例

## 数据结构（models.py 新增）

### ChartAnnotation
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| date | str | — | 标注日期 |
| price | float | — | 标注价格 |
| text | str | — | 标注文字 |
| color | str | "blue" | 颜色 |
| symbol | str | "star" | 标记形状（star/triangle-up/triangle-down/diamond/circle/cross） |
| size | int | 12 | 标记大小 |

### ChartHLine
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| price | float | — | 水平线价格 |
| color | str | "gray" | 颜色 |
| dash | str | "dash" | 线型（solid/dash/dot） |
| label | str | "" | 标签文字 |
| width | int | 1 | 线宽 |

### ChartRange
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| start_date | str | — | 起始日期 |
| end_date | str | — | 结束日期 |
| color | str | "rgba(255,255,0,0.1)" | 背景色 |
| label | str | "" | 区间标签 |

## 核心函数

### `plot_stock_kline(bars, ...) -> go.Figure`
- 蜡烛图（红涨绿跌）+ 成交量柱状图（子图布局 75%/25%）
- 支持叠加标注点（annotations）、水平参考线（hlines）、区间高亮（highlight_ranges）
- 输出为 plotly Figure 对象，可选导出为独立 HTML 文件

## 新增测试用例（3 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_chart_plot_stock_kline_returns_figure` | 返回 go.Figure，包含蜡烛图+成交量 |
| 2 | `test_chart_annotations_and_hlines` | 带标注/水平线/区间调用，验证 4 个 trace |
| 3 | `test_chart_export_html` | 导出 HTML 文件，验证非空且含 plotly |

## 验证结果
- ✅ 64 passed in 1.09s（全部通过）
- ✅ 蜡烛图红涨绿跌
- ✅ 成交量柱在 K 线下方
- ✅ 标注点在指定位置显示
- ✅ 水平线贯穿图表
- ✅ 区间高亮（vrect）正常渲染
- ✅ HTML 导出独立可交互
