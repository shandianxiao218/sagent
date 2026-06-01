# #23 逐日止损/止盈回测引擎实施结果

## 新建文件

- `sagent/backtest_engine.py`

## 数据结构

### `TradeLifecycle`
- symbol, signal_date, entry_price, key_low, stop_loss_price
- exit_date, exit_price, exit_reason ("止损" | "半仓止盈后趋势破坏" | "持有到期" | "未退出")
- holding_days, daily_events (逐日价格+事件)
- total_return (综合收益率，考虑半仓加权), half_profit_locked, half_profit_r, max_r

### `BacktestStats`
- total_signals, total_trades, stop_loss_count, take_profit_count, natural_exit_count
- stop_loss_rate, take_profit_rate
- avg_holding_days, avg_return_all, avg_return_stop_loss, avg_return_take_profit, avg_return_natural
- win_rate, trades

## 核心函数

### `find_key_low_for_signal(bars, signal_idx) -> float`
调用 `find_key_low(bars[:signal_idx+1])` 获取信号日的 key_low。

### `simulate_trade(bars, signal_idx, max_holding=20) -> TradeLifecycle`
逐日遍历逻辑：
1. entry_price = 信号日收盘价
2. key_low = find_key_low_for_signal(bars, signal_idx)
3. stop_loss_price = max(entry_price * 0.95, key_low)
4. 从 signal_idx+1 到 signal_idx+max_holding 逐日检查：
   - 止损（daily_low <= stop_loss_price）→ 立即退出
   - 半仓止盈（R >= 2.5，只触发一次）→ 锁定半仓收益
   - 趋势破坏（已止盈 + daily_low <= key_low）→ 剩余半仓退出
5. 未退出 → 第 max_holding 天收盘价退出
6. 综合收益率：半仓加权 = (锁定收益 + 剩余收益) / 2

### `run_backtest_engine(bars_map, signals, max_holding=20) -> BacktestStats`
对多个信号执行 simulate_trade 并汇总统计。

## 验证结果

- ✅ 模块导入正常
- ✅ 30 个现有测试全部通过（无破坏性变更）
- ✅ 止损逻辑功能验证通过（南大光电场景模拟）
- ✅ 止损价 = max(entry_price * 0.95, key_low)
- ✅ 半仓止盈在 R >= 2.5 时触发
- ✅ 已止盈后的趋势破坏检测
- ✅ 持有到期自动退出
- ✅ Python type check clean

## 未修改的文件

- 未修改任何已有文件，纯粹新建模块
