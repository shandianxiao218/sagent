# #29 组合级持仓生命周期管理回测实施结果

## 新建文件

- `sagent/backtest_portfolio.py` — 组合级回测模块

## 修改文件

- `tests/test_sagent_behaviors.py` — 新增 2 个辅助函数 + 4 个测试用例

## 数据结构

### DailyNAV
| 字段 | 类型 | 说明 |
|------|------|------|
| date | str | 交易日 |
| cash | float | 现金余额 |
| position_value | float | 持仓市值 |
| total_value | float | 总资产 |
| open_positions | int | 活跃持仓数 |

### PortfolioStats
| 字段 | 类型 | 说明 |
|------|------|------|
| initial_cash | float | 初始资金 |
| final_value | float | 最终资产 |
| total_return | float | 总收益率 |
| max_drawdown | float | 最大回撤 |
| sharpe_ratio | float | Sharpe 比率 |
| total_trades | int | 总交易笔数 |
| winning_trades | int | 盈利笔数 |
| losing_trades | int | 亏损笔数 |
| win_rate | float | 胜率 |
| avg_profit | float | 平均盈利 |
| avg_loss | float | 平均亏损 |
| profit_loss_ratio | float | 盈亏比 |
| max_single_profit | float | 最大单笔盈利 |
| max_single_loss | float | 最大单笔亏损 |
| stop_loss_count | int | 止损次数 |
| take_profit_count | int | 趋势破坏退出次数 |
| natural_exit_count | int | 持有到期次数 |
| avg_holding_days | float | 平均持有天数 |
| capital_utilization | float | 资金利用率 |
| nav_curve | list[DailyNAV] | 净值曲线 |

## BacktestPortfolio 类

### 方法

| 方法 | 说明 |
|------|------|
| `try_open(symbol, bars, signal_idx, signal_date)` | 尝试开仓（受周限制+资金+重复持仓限制） |
| `daily_monitor(date, bars_map)` | 每日监控（止损/止盈/趋势破坏/持有到期） |
| `close_all_remaining(date, bars_map)` | 清仓所有剩余持仓 |
| `record_nav(date, bars_map)` | 记录当日净值快照 |
| `get_stats()` | 计算组合统计 |

### 开仓逻辑
1. 检查 ISO 周限制（默认 max_weekly_open=2）
2. 检查是否已有同股票活跃持仓
3. 计算买入量 = cash * position_ratio // entry_price
4. 获取 key_low（find_key_low_for_signal）
5. 获取 trend_break_ref（find_trend_break_ref）
6. 扣减现金，记录持仓

### 每日监控逻辑
对每个活跃持仓：
1. 持有到期检查（>= max_holding 天 → 强制平仓）
2. 止损检查（bar.low <= stop_loss_price → 平仓）
3. 半仓止盈（R >= 2.5 且未止盈 → 标记）
4. 趋势破坏（已止盈 + bar.low <= trend_break_ref → 平仓）

平仓时回收资金（quantity * exit_price），记录交易到 closed_trades。

## 顶层函数

### `run_portfolio_backtest(bars_map, signals, ...)`

1. 按日期排序信号
2. 收集所有交易日（bars_map 日期并集 + 信号日）
3. 逐日：尝试开仓 → 每日监控 → 记录净值
4. 清仓剩余持仓
5. 返回 PortfolioStats

## 新增测试辅助函数

| 函数 | 用途 |
|------|------|
| `_make_portfolio_test_bars(symbol, dates_and_prices)` | 从 (date, close) 对列表构造 bars |
| `_make_signal_bars(symbol, entry_price, key_low_target, signal_date, ...)` | 构造含信号结构的完整 bars |

## 新增测试用例（4 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_portfolio_backtest_basic` | 2 个信号（一涨一跌），验证组合统计、净值曲线 |
| 2 | `test_portfolio_weekly_limit_enforced` | 同周 3 个信号，max_weekly_open=2，只开 2 笔 |
| 3 | `test_portfolio_stop_loss_releases_capital` | A 止损后释放资金，B 在同周可开仓 |
| 4 | `test_portfolio_nav_curve` | 净值曲线非空，日期递增，字段合法 |

## 验证结果

```
59 passed in 0.40s
```

- 原有 55 个测试全部通过
- 新增 4 个组合回测测试全部通过
- Lint clean（pi-lens import resolve 警告不影响运行）

## 未修改的文件

- `sagent/backtest_engine.py` — 不变
- `sagent/kline.py` — 不变
- `sagent/models.py` — 不变
- `sagent/portfolio.py` — 不变
