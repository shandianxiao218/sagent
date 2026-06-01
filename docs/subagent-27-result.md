# #27 半仓止盈统计和策略对比实施结果

## 修改文件

1. `sagent/backtest_engine.py` — 增强 TradeLifecycle 和 BacktestStats
2. `tests/test_sagent_behaviors.py` — 新增 4 个测试用例

## 变更内容

### 1. TradeLifecycle 新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `buy_and_hold_return` | `float` | `0.0` | 全程持有收益（不考虑止损止盈，持有到 max_holding 天收盘价） |

在 `simulate_trade` 中计算：无论交易过程中发生了什么止损/止盈，始终计算 `(bars[end_idx].close - entry_price) / entry_price` 作为 buy_and_hold_return。

### 2. BacktestStats 新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `half_profit_triggered_count` | `int` | `0` | 触发半仓止盈的交易数 |
| `half_profit_triggered_rate` | `float` | `0.0` | 触发率 |
| `avg_return_half_profit_triggered` | `float` | `0.0` | 触发止盈组平均收益 |
| `avg_return_half_profit_not_triggered` | `float` | `0.0` | 未触发止盈组平均收益 |
| `buy_and_hold_avg_return` | `float` | `0.0` | 全程持有平均收益 |
| `strategy_vs_buyhold_diff` | `float` | `0.0` | 止盈策略 vs 全程持有收益差 |

### 3. run_backtest_engine 新增统计逻辑

```python
# 半仓止盈分组
half_triggered = [t for t in trades if t.half_profit_locked]
half_not_triggered = [t for t in trades if not t.half_profit_locked]

# 全程持有对比
buy_and_hold_returns = [t.buy_and_hold_return for t in trades]
strategy_vs_buyhold_diff = strategy_avg - buy_and_hold_avg
```

## 新增测试用例（4 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_half_profit_buy_and_hold_comparison` | 半仓止盈后止损场景：buy_and_hold_return 存在且 ≠ total_return |
| 2 | `test_half_profit_stats_triggered_vs_not` | 3 信号（1 触发止盈、2 不触发）：分组统计正确，触发率=1/3 |
| 3 | `test_fuda_alloy_scenario` | 福达合金场景模拟：entry=31.64, key_low=28.0, 半仓止盈触发后持有到期 |
| 4 | `test_gaole_stock_scenario` | 高乐股份场景模拟：entry=6.25, key_low ≈ 5.25, R≥2.5 触发半仓止盈 |

### 测试发现

- `_make_trade_bars` 的 key_low 可能与 target 不完全一致（因 swing low 结构构造和 find_key_low 的回调区间检测），实际 key_low 可能更低
- 高乐股份测试中调整了 post_entry_prices 的高点（9.0+），确保在任意 key_low 下 R ≥ 2.5 都能触发

## 验证结果

```
47 passed in 0.41s
```

- 原有 43 个测试全部通过
- 新增 4 个半仓止盈统计测试全部通过

## 向后兼容性

- TradeLifecycle 新增 `buy_and_hold_return` 有默认值 0.0
- BacktestStats 新增 6 个字段都有默认值
- 所有已有构造代码无需修改
