# #26 止损类型追踪和验证实施结果

## 修改文件

1. `sagent/backtest_engine.py` — 增强止损类型追踪
2. `tests/test_sagent_behaviors.py` — 新增 5 个测试用例

## 变更内容

### 1. TradeLifecycle 新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `stop_loss_type` | `str` | `""` | "硬性5%" \| "key_low" \| ""（未止损） |
| `stop_loss_distance_pct` | `float` | `0.0` | 止损价距买入价的百分比距离（负数） |

### 2. simulate_trade 止损类型判断逻辑

```python
hard_stop_threshold = round(entry_price * 0.95, 2)
if exit_reason == "止损":
    if exit_price == hard_stop_threshold and hard_stop_threshold > key_low:
        stop_loss_type = "硬性5%"
    else:
        stop_loss_type = "key_low"
```

判断规则：
- 当 `stop_loss_price = entry_price * 0.95 > key_low` 时，触发的是硬性5%止损
- 当 `stop_loss_price = key_low ≥ entry_price * 0.95` 时，触发的是key_low止损
- 未止损时为空字符串

### 3. BacktestStats 新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `hard_stop_loss_count` | `int` | 硬性5%止损次数 |
| `key_low_stop_loss_count` | `int` | key_low止损次数 |
| `hard_stop_loss_rate` | `float` | 硬性止损率 |
| `key_low_stop_loss_rate` | `float` | key_low止损率 |
| `avg_return_hard_stop_loss` | `float` | 硬性止损组平均收益 |
| `avg_return_key_low_stop_loss` | `float` | key_low止损组平均收益 |
| `oversized_stop_loss_count` | `int` | 止损空间>8%的交易数 |

### 4. run_backtest_engine 新增统计

```python
hard_sl = [t for t in trades if t.stop_loss_type == "硬性5%"]
key_low_sl = [t for t in trades if t.stop_loss_type == "key_low"]
oversized = [t for t in trades if t.stop_loss_distance_pct < -0.08]
```

## 新增测试用例（5 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_stop_loss_type_hard_5pct` | key_low=85，stop_loss=95，止损类型="硬性5%" |
| 2 | `test_stop_loss_type_key_low` | key_low=97，stop_loss=97，止损类型="key_low" |
| 3 | `test_stop_loss_distance_pct` | 硬性止损 distance=-0.05，key_low止损 distance=-0.03 |
| 4 | `test_backtest_stats_stop_loss_breakdown` | 2个止损信号：1硬性+1key_low，验证分组统计 |
| 5 | `test_oversized_stop_loss_warning` | 正常场景下 oversized_count==0（因stop_loss=max(0.95×entry, key_low)≥0.95×entry） |

## 关键发现：oversized_stop_loss_count 在当前逻辑下永远为 0

由于 `stop_loss_price = max(entry_price * 0.95, key_low)`：
- 最小 stop_loss_distance = -5%（硬性止损）
- key_low 止损时 key_low ≥ entry_price * 0.95 → distance ≥ -5%
- -5% > -8%，所以不会出现 oversized 场景

这个字段为将来策略调整（如放宽止损比例）预留了监控能力。

## 验证结果

```
43 passed in 0.38s
```

- 原有 38 个测试全部通过
- 新增 5 个止损类型追踪测试全部通过

## 向后兼容性

- TradeLifecycle 新字段 `stop_loss_type` 和 `stop_loss_distance_pct` 都有默认值
- BacktestStats 新字段都有默认值
- 所有已有的构造 TradeLifecycle/BacktestStats 的代码无需修改
