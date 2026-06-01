# key_low swing low 检测算法单元测试结果

## 修改文件
- `tests/test_sagent_behaviors.py` — 新增辅助函数 + 10 个测试用例

## 新增内容

### 辅助函数
- `_make_bars(lows, symbol, start_date)` — 根据 low 序列快速构造 `DailyBar` 列表

### 新增测试用例（10 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_find_swing_lows_basic` | V 形回调检测到唯一谷底作为 swing low |
| 2 | `test_find_swing_lows_multiple` | 多个谷底时返回全部 swing low |
| 3 | `test_find_swing_lows_no_swing` | 单调下跌无 swing low → 空列表 |
| 4 | `test_find_swing_lows_equal_lows` | 相邻低价相等时严格小于不成立，不判定为 swing low |
| 5 | `test_find_swing_lows_short_data` | 数据不足 left+right+1 → 空列表 |
| 6 | `test_find_key_low_uses_last_swing` | 多个 swing low 时取最后一个 |
| 7 | `test_find_key_low_fallback_to_min` | 无 swing low 时回退到区间最低价，描述含"无明确转折点" |
| 8 | `test_find_key_low_with_explicit_high_idx` | 传入 recent_high_idx 从指定位置搜索 |
| 9 | `test_describe_stock_includes_key_low_source` | fields 中有 key_low_source 字段，文本含来源描述 |
| 10 | `test_describe_stock_no_longer_uses_min_15` | 新算法基于结构转折而非简单 min(bars[-15:]) |

## 验证结果
```
30 passed in 0.36s
```
- 原有 20 个测试全部通过
- 新增 10 个测试全部通过
- Lint clean
