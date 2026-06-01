# #37 组合级回测仪表盘实施结果

## 修改文件

1. `sagent/chart.py` — 新增 `plot_portfolio_dashboard()` 和 `_compute_monthly_returns()` 函数
2. `tests/test_sagent_behaviors.py` — 新增 2 个测试用例

## 变更内容

### 1. `plot_portfolio_dashboard(stats, output_path=None) -> go.Figure`

使用 `make_subplots(rows=2, cols=2)` 布局：

| 位置 | 内容 | 实现 |
|------|------|------|
| 左上 | 净值曲线 | `go.Scatter` — 总资产归一化为 1.0 起始 + 峰值线展示回撤 |
| 右上 | 月度收益柱状图 | `go.Bar` — 正绿负红，标注百分比 |
| 左下 | 交易分布 | `go.Bar` — 按退出方式（止损/趋势破坏/持有到期）分组 |
| 右下 | 统计卡片 | `go.Scatter(mode='text')` — 7 项关键指标 |

#### 统计卡片内容
- 总收益率
- 最大回撤
- 夏普比率
- 胜率
- 盈亏比
- 止损率
- 平均持有天数

#### 空数据保护
`nav_curve` 为空时返回空 Figure，标题为"组合回测仪表盘（无数据）"。

### 2. `_compute_monthly_returns(stats) -> list[dict]`

从 `nav_curve` 按月聚合收益率：
- 每月取最后一个 `total_value`
- 月度收益率 = (月末值 - 上月末值) / 上月末值
- 跳过首月（无上月数据）
- 返回 `[{"month": "2026-01", "return": 0.02}, ...]`

### 3. 导入变更

新增 `from .backtest_portfolio import PortfolioStats`。

## 新增测试用例（2 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_plot_portfolio_dashboard_returns_figure` | 构造含 5 天 NAV 的 PortfolioStats → 返回 Figure，标题正确，2x2 子图有 4 个 yaxis，净值 trace 存在 |
| 2 | `test_plot_portfolio_dashboard_empty_nav` | nav_curve 为空 → 返回 Figure，标题含"无数据" |

## 验证结果

```
69 passed in 1.32s
```

- 原有 67 个测试全部通过
- 新增 2 个仪表盘测试全部通过
- 不破坏已有功能

## 依赖关系

- `PortfolioStats` from `sagent.backtest_portfolio`（#29 实现）
- `make_subplots` from `plotly.subplots`（#33 实现）
- `go.Figure` / `go.Scatter` / `go.Bar` from `plotly.graph_objects`
