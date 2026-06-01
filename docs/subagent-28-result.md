# #28 趋势破坏参考位自动识别实施结果

## 修改文件

1. `sagent/kline.py` — 新增 `find_trend_break_ref()` 函数
2. `sagent/models.py` — Position 新增 `trend_break_ref` 和 `trend_break_desc` 字段
3. `sagent/backtest_engine.py` — TradeLifecycle 新增字段，simulate_trade 使用 trend_break_ref 替代 key_low 做趋势破坏检查
4. `tests/test_sagent_behaviors.py` — 新增 5 个测试用例

## 变更内容

### 1. kline.py — find_trend_break_ref()

```python
def find_trend_break_ref(
    bars: list[DailyBar],
    signal_idx: int,
    key_low_idx: int | None = None,
) -> tuple[float, str]:
```

算法：
1. 获取 key_low 位置（自动计算或显式传入）
2. 从 key_low 到 signal_idx 的区间内找 swing lows
3. 在 swing lows 中找"更高的低点"序列（每个比前一个高）
4. 取最后一个 higher low 作为趋势破坏参考位
5. 如果没有 higher low → 回退到 key_low

### 2. models.py — Position

```python
trend_break_ref: float = 0.0   # 趋势破坏参考位
trend_break_desc: str = ""      # 参考位描述
```

### 3. backtest_engine.py

#### TradeLifecycle 新增字段
- `trend_break_ref: float = 0.0` — 趋势破坏参考位
- `trend_break_desc: str = ""` — 参考位描述

#### simulate_trade 修改
- `find_key_low_for_signal` 返回值从 `float` 改为 `tuple[float, int]`（增加 key_low 索引）
- 新增 `find_trend_break_ref()` 调用
- 趋势破坏检查从 `daily_low <= key_low` 改为 `daily_low <= trend_break_ref`
- 退出价从 `key_low` 改为 `trend_break_ref`
- **止损检查不变**：仍用 `stop_loss_price = max(entry_price * 0.95, key_low)`

### 4. 新增测试用例（5 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_find_trend_break_ref_higher_lows` | 有 higher low 序列时取最后一个 (61.0) |
| 2 | `test_find_trend_break_ref_no_higher_lows` | swing lows 递减时回退到 key_low (55.0) |
| 3 | `test_find_trend_break_ref_no_swing_lows` | 无 swing lows 时回退到 key_low (50.0) |
| 4 | `test_simulate_trade_populates_trend_break_ref` | simulate_trade 正确填入 trend_break_ref 和描述 |
| 5 | `test_simulate_trade_trend_break_uses_ref_not_key_low` | 显式 key_low_idx=40 时正确找到 ref=61.0 |

## 关键设计决策

### 止损 vs 趋势破坏的优先级

止损检查**始终优先于**趋势破坏检查。当 `stop_loss_price > trend_break_ref` 时：
- 任何触及 trend_break_ref 的价格会先触发止损（因为 stop_loss_price 更高）
- 趋势破坏退出只有在 `trend_break_ref >= stop_loss_price` 时才能与止损区分

这意味着：
- 如果 `key_low < entry_price * 0.95`，则 `stop_loss = entry * 0.95`，trend_break_ref 可能高于 stop_loss → 趋势破坏可区分
- 如果 `key_low >= entry_price * 0.95`，则 `stop_loss = key_low = trend_break_ref`（除非有 higher low 使 ref > key_low）

### find_trend_break_ref 的 key_low_idx 参数

函数接受可选的 `key_low_idx` 参数：
- 显式传入时，直接从该位置搜索 higher lows
- 自动模式时，调用 `find_key_low` 获取位置（可能不准确，取决于 find_key_low 的自动检测）

在 `simulate_trade` 中，自动获取 key_low_idx（通过 `find_key_low_for_signal` 的返回值）。

## 验证结果

```
55 passed in 0.40s
```

- 原有 50 个测试全部通过
- 新增 5 个趋势破坏参考位测试全部通过
- Lint clean

## 向后兼容性

- TradeLifecycle 新增 `trend_break_ref` 和 `trend_break_desc` 有默认值
- Position 新增 `trend_break_ref` 和 `trend_break_desc` 有默认值
- `find_key_low_for_signal` 返回类型从 `float` 改为 `tuple[float, int]`（breaking change，但仅在 backtest_engine 内部使用）
- 所有已有测试无需修改
