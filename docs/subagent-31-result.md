# #31 LLM 精筛增加 key_low 结构识别 — 实施结果

## 修改文件

1. `sagent/kline.py` — 新增 `describe_pullback_structure()` 函数，增强 `describe_stock()` 
2. `sagent/llm.py` — 增强 `build_stock_prompt()` 增加 key_low 识别指令
3. `tests/test_sagent_behaviors.py` — 新增 `Decision` 导入 + 2 个测试用例

## 变更内容

### 1. kline.py — 新增 `describe_pullback_structure()`

```python
def describe_pullback_structure(bars: list[DailyBar], signal_idx: int) -> str:
    """生成回调结构的自然语言描述。"""
```

算法：
1. 取 `bars[:signal_idx+1]` 作为窗口
2. 调用 `find_key_low()` 获取 key_low 和其索引
3. 在 key_low 前 20 日到信号日的区间内调用 `find_swing_lows()` 检测结构转折低点
4. 描述 swing low 序列，区分"更高的低点"和"更低的低点"
5. 无 swing low 时返回兜底描述

示例输出：
- `"回调过程中02-05 出现结构转折低点 51.29，随后02-18 形成更高的低点 53.10。"`
- `"回调区间内未检测到明确的结构转折低点，key_low=45.00。"`

### 2. kline.py — `describe_stock()` 增强

- 在文本末尾追加 `pullback_desc`（回调结构描述）
- 文本长度仍受 `max_chars=900` 限制

### 3. llm.py — `build_stock_prompt()` 增强

在 prompt 中新增 key_low 识别指令块：

```
请根据 K 线描述识别买点前关键低点（key_low）：
- 这是利弗摩尔体系中的同级别结构转折低点
- 不是简单的前 N 日最低价
- 而是回调波段中最后一个结构性的止跌回升点
- 在 JSON 输出中包含 key_low 字段（价格数值）
```

JSON 输出格式中已包含 `key_low` 字段（之前就有，此次确认保留）。

### 4. 新增测试用例

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_build_stock_prompt_includes_key_low_instruction` | prompt 包含"key_low"、"利弗摩尔"、"结构转折低点"、"不是简单的前 N 日最低价"、"止跌回升点" |
| 2 | `test_describe_stock_pullback_structure` | 描述文本包含回调结构信息（"结构转折低点"或"更高的低点"或"更低的低点"或"回调过程中"） |

## 验证结果

```
64 passed in 1.08s
```

- 原有 62 个测试全部通过
- 新增 2 个测试全部通过
- 不破坏已有功能

## 未修改的部分

- `judge_stock()` 规则引擎 fallback — 已正确使用 `description.key_low`，无需修改
- `Decision` 模型 — 已有 `key_low` 字段，无需修改
- `plot_stock_kline` 相关 — 未修改

## 向后兼容性

- `describe_pullback_structure()` 是新增函数，不影响已有接口
- `describe_stock()` 的输出文本变长（增加回调结构描述），但仍在 `max_chars` 限制内
- `build_stock_prompt()` 的输出变长，但这是预期的增强
- 所有已有测试无需修改（仅新增 `Decision` 导入）
