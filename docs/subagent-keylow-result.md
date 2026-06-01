# #24 key_low 修复实施结果

## 修改文件

- `sagent/kline.py` — 唯一修改的文件

## 变更内容

### 1. 新增 `find_swing_lows()` 函数

- 参数：`bars: list[DailyBar]`, `left: int = 5`, `right: int = 3`
- 遍历 `bars[left : n-right]`，检查每个点是否满足 swing low 条件：
  `bars[i].low < bars[j].low` for all j in `[i-left, i+right]`, j != i
- 返回 `list[tuple[int, float]]`（索引和 low 值，升序）
- 边界处理：前 left 个和后 right 个不参与判断

### 2. 新增 `find_key_low()` 函数

- 参数：`bars: list[DailyBar]`, `recent_high_idx: int | None = None`
- 自动确定回调区间：最近30日最高收盘价所在日 → bars末尾
- 在回调区间内调用 `find_swing_lows()` 检测结构转折低点
- 取**最后一个** swing low 作为 key_low
- 回退保障：找不到 swing low → 回调区间最低价；数据不足 → 最后一日低价
- 返回 `tuple[float, str, int]`：(key_low值, 来源描述, 日期索引)

### 3. 修改 `describe_stock()`

- 删除 `key_low = min(bar.low for bar in bars[-15:])`
- 改为 `key_low, key_low_source, _key_low_idx = find_key_low(bars)`
- 文本新增 key_low 来源说明："（X的回调结构转折低点）"
- fields 新增 `"key_low_source"` 字段

### 4. 修复 recent_high_idx 计算的 bug

原代码中 `closes[::-1].index(recent_high)` 的索引映射公式有误：
- 错误：`n - 30 + rev_idx`
- 正确：`n - 30 + (len(closes) - 1 - rev_idx)`

## 验证结果

- ✅ 所有 20 个现有测试通过
- ✅ 不再使用 `min(bar.low for bar in bars[-15:])`
- ✅ 新算法基于回调区间的 swing low 检测
- ✅ K 线描述文本包含 key_low 来源说明
- ✅ 边界条件正确处理（短数据、无 swing low、相等低价等）
- ✅ `key_low_source` 字段已加入 KlineDescription.fields

### 手动验证场景

| 场景 | 结果 |
|------|------|
| V 形回调，单个 swing low | 正确检测 |
| 多个 swing low | 取最后一个（最接近信号日） |
| 单调下跌，无 swing low | 回退到区间最低价 |
| 所有低价相等 | 不误判为 swing low，使用回退 |
| 边界索引（前 left / 后 right） | 正确排除 |
| 数据不足（<10 bars） | 安全回退 |
| fixture 样本数据（000001） | 回调区间过短，使用回退逻辑 |

## 未修改的文件

- `sagent/models.py` — KlineDefinition 结构不变（fields 已是 dict[str, Any]）
- `sagent/llm.py` — 不变
- `tests/` — 不变（现有测试全部通过）

## 风险

- fixture 样本数据（000001）中回调区间过短（不足 left+right+1 = 9 个交易日），导致无法检测 swing low，回退到区间最低价。这不影响功能正确性，但说明 fixture 数据的 key_low 值可能与之前不同。
- 南大光电 300346 的验证需要实际 K 线数据（不在 fixture 中），无法在离线测试中确认 51.29。

## 建议下一步

1. 用真实 K 线数据运行 `describe_stock('300346', bars)` 验证南大光电的 key_low
2. 对 `fixtures/validation/llm_cases.json` 中的案例重新生成 K 线描述
3. 开始 #23（回测引擎重写），依赖新的 key_low 值计算止损价
