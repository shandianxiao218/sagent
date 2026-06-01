# #36 单笔交易生命周期可视化实施结果

## 修改文件

1. `sagent/chart.py` — 新增 `plot_trade_lifecycle()` 和 `_add_trade_event_markers()` 函数
2. `tests/test_sagent_behaviors.py` — 新增 1 个测试用例

## 新增函数

### `plot_trade_lifecycle(bars, trade, output_path=None) -> go.Figure`

布局：`make_subplots(rows=2, row_heights=[0.7, 0.3])`

**Row 1 — K线图 + 标注：**
- 蜡烛图（红涨绿跌）
- 买入点：绿色三角向上 + 文字标注
- 止损线：红色虚线
- key_low 线：蓝色点线
- 持仓区间：绿色半透明背景
- 退出点：根据退出类型着色（止损红▼、趋势破坏紫▼、持有到期灰●）
- 半仓止盈事件：橙色◆ + R值标注
- 止损触发事件：红色× 标记

**Row 2 — 逐日R值曲线：**
- `go.Scatter` 绘制 daily_events 中的 r_ratio
- R=2.5 目标线：橙色虚线
- R=0 基准线：灰色点线

### `_add_trade_event_markers(fig, trade)`

根据 `trade.exit_reason` 和 `trade.daily_events` 中的事件标记，在 K 线图上添加：
- 退出点标注（颜色/形状随退出类型变化）
- 半仓止盈事件（橙色◆）
- 止损触发事件（红色×）

## 新增测试用例

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_plot_trade_lifecycle_returns_figure` | 返回 go.Figure，标题含股票代码，trace 包含 Candlestick 和 Scatter |

## 验证结果

```
65 passed in 1.14s
```

- 原有 64 个测试全部通过
- 新增 1 个测试通过
- 不破坏已有功能

## 导入依赖

- `from .backtest_engine import TradeLifecycle` — 新增导入
- plotly make_subplots 用于双行布局

## 未修改的文件

- `sagent/backtest_engine.py` — 不变（TradeLifecycle 已有 daily_events/r_ratio 字段）
- `sagent/models.py` — 不变
