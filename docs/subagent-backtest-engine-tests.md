# backtest_engine.py 单元测试结果

## 修改文件

- `tests/test_sagent_behaviors.py` — 新增辅助函数 + 8 个测试用例

## 新增辅助函数

| 函数 | 用途 |
|------|------|
| `_make_bar(symbol, date, open_, high, low, close, vol, amt)` | 快捷构造单根 DailyBar |
| `_make_trade_bars(symbol, entry_price, key_low_target, post_entry_prices, num_pre_bars)` | 构造完整的回测 bars 序列，含 swing low 结构 |

### `_make_trade_bars` 设计

构造 40+ 根前置 bars，包含：
- 底部盘整（索引 0-14）
- 上升段（索引 15-24）
- 高位整理（索引 25-29）
- 回调阶段（索引 30-34）
- Swing low 谷底（索引 35，low = key_low_target）
- 反弹阶段（索引 36-38）
- 信号日（索引 39，close = entry_price）

信号日后的 bars 由 `post_entry_prices` 参数控制每日的 high/low/close。

## 新增测试用例（8 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_simulate_trade_stop_loss_triggered` | -5% 硬止损触发：entry=100, key_low=90 → stop_loss=95, 第3天 low=94 → 止损退出 |
| 2 | `test_simulate_trade_key_low_stop_loss` | key_low 止损（key_low > entry*0.95）：entry=100, key_low=97 → stop_loss=97, 以 97 止损 |
| 3 | `test_simulate_trade_half_profit_take` | 半仓止盈：entry=100, key_low=90, R=3.0 触发半仓止盈，之后持有到期 |
| 4 | `test_simulate_trade_full_lifecycle` | 完整生命周期：半仓止盈(R=2.5) → 止损退出（stop_loss_price == key_low 场景）|
| 5 | `test_simulate_trade_hold_to_expiry` | 持有到期：价格平稳，20 天后以收盘价退出 |
| 6 | `test_simulate_trade_stop_loss_after_half_profit` | 半仓止盈后再止损：stop_loss_price(95) > key_low(90)，综合收益加权计算 |
| 7 | `test_run_backtest_engine_aggregation` | 3 信号汇总：1 止损 + 2 持有到期，验证 BacktestStats 的 count/rate/avg |
| 8 | `test_simulate_trade_nodata_exit` | bars 不足 max_holding：4 根后续 bar，以最后一根收盘价退出 |

## 关键发现

### 引擎逻辑优先级

`simulate_trade` 的检查顺序：
1. **止损检查**（`daily_low <= stop_loss_price`）— **最优先**
2. **半仓止盈检查**（`R >= 2.5` 且未止盈过）
3. **趋势破坏检查**（已止盈 + `daily_low <= key_low`）

这意味着：当 `stop_loss_price > key_low` 时，任何触及 key_low 的价格会先触发止损（因为 stop_loss_price 更高）。趋势破坏退出只有在 `stop_loss_price == key_low`（即 `key_low >= entry_price * 0.95`）时才可能与止损区分。

### 综合收益计算

半仓止盈后的综合收益 = (锁定收益 + 剩余收益) / 2：
- 锁定收益 = half_profit_r × r_denom / entry_price
- 剩余收益 = (exit_price - entry_price) / entry_price

## 验证结果

```
38 passed in 0.37s
```

- 原有 30 个测试全部通过
- 新增 8 个回测引擎测试全部通过
- Lint clean
