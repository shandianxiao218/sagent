# #32 回测中增加成交额过滤实施结果

## 修改文件

- `scripts/run_backtest_period.py`

## 变更内容

### 1. `run_backtest()` 新增参数 `min_avg_amount`

```python
def run_backtest(
    ...
    min_avg_amount: float = 100_000_000,  # 默认1亿元
) -> dict:
```

### 2. fetch_bars 后增加成交额过滤

在 `len(bars) < 300` 检查之后、日期范围扫描之前：

```python
recent_bars = bars[-20:]
avg_amount = mean(bar.amount for bar in recent_bars) if recent_bars else 0
if avg_amount < min_avg_amount:
    low_amount_count += 1
    continue
```

### 3. 新增计数器 `low_amount_count`

记录因日均成交额低于阈值而被跳过的股票数。

### 4. 输出中记录

- `meta.parameters` 中增加 `min_avg_amount` 和 `low_amount_count`
- 进度日志中增加"成交额不足"计数

### 5. argparse 新增 `--min-amount` 参数

```python
parser.add_argument("--min-amount", type=float, default=100_000_000,
                    help="最低日均成交额（元），默认1亿")
```

## 注意事项

- mootdx 的 `amount` 字段单位为**元**，与 `min_avg_amount` 默认值 100_000_000（1亿）一致
- 不修改 sagent/ 核心模块
- 不修改测试文件
- 59 个测试全部通过
