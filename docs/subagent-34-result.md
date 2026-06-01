# #34 单股信号标注可视化实施结果

## 修改文件

1. `sagent/chart.py` — 新增 `plot_signal_chart()` 函数
2. `tests/test_sagent_behaviors.py` — 新增 2 个测试用例

## 新增函数 `plot_signal_chart()`

### 函数签名
```python
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
```

### 标注层

| # | 标注 | 颜色 | 线型/形状 | 说明 |
|---|------|------|-----------|------|
| 1 | 买入信号 | 绿色 | triangle-up | 信号日收盘价 |
| 2 | 止损线 | 红色 | dash | max(买入价×0.95, key_low) |
| 3 | key_low线 | 蓝色 | dot | 关键低点 |
| 4 | R=2.5 目标线 | 橙色 | dash | 买入价 + 2.5 × 风险 |
| 5 | 趋势破坏参考线 | 紫色 | dash | 仅当 trend_break_ref > key_low 时显示 |
| 6 | 回调区间高亮 | 矢车菊蓝半透明 | vrect | signal_idx前30日到信号日 |

### 自动参数获取

- `entry_price` 默认取 `bars[signal_idx].close`
- `key_low` 默认调用 `find_key_low(bars[:signal_idx+1])`
- `stop_loss_price` 默认 `max(entry_price * 0.95, key_low)`

### 标题格式

`{symbol} | 信号日 {date} | 买入 {price} | 止损 {sl} | R=2.5 目标 {target}`

### 复用

内部调用已有的 `plot_stock_kline()` 函数，构建 annotations、hlines、highlight_ranges 后传入。

## 新增测试用例（2 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_plot_signal_chart_returns_figure` | 返回 go.Figure，标题含 symbol/买入/止损，≥3 traces |
| 2 | `test_plot_signal_chart_has_key_annotations` | 标题含止损/R=2.5，layout annotations 含止损/key_low/R=2.5；传入 trend_break_ref 时含"趋势破坏" |

## 验证结果

```
67 passed in 1.23s
```

- 原有 65 个测试全部通过
- 新增 2 个信号标注测试全部通过
- 不破坏已有功能

## 向后兼容性

- `plot_signal_chart()` 是新增函数，不影响已有接口
- `plot_stock_kline()`、`plot_trade_lifecycle()` 等函数不变
