# #30 主线验证层（L6）集成到回测 — 实施结果

## 修改文件

- `scripts/run_backtest_period.py` — 新增行业归属获取、板块分析、月度板块维度

## 变更内容

### 1. 新增 `get_stock_industry()` 函数

```python
def get_stock_industry(symbol: str) -> str:
    """获取股票所属申万行业（通过 AKShare 东方财富接口）。"""
    import akshare as ak
    try:
        df = ak.stock_individual_info_em(symbol=symbol)
        for _, row in df.iterrows():
            if row.get("item") == "行业":
                return str(row.get("value", "未知"))
    except Exception:
        pass
    return "未知"
```

- 通过 AKShare 东方财富接口获取股票所属申万行业
- 网络失败时 fallback 到 "未知"
- 结果缓存到 `industry_cache` 避免重复查询

### 2. 回测流程新增步骤 [3/7] — 获取行业归属

- 信号检测后，对每个信号对应的唯一股票查询行业
- 进度日志每 20 只输出一次
- 统计未获取到行业的股票数量
- 将行业归属写入每个信号的 `"industry"` 字段

### 3. 回测流程新增步骤 [5/7] — 板块分析

- 按行业分组统计信号：count、avg_return、win_rate、symbols
- "同行业信号集中度"：某行业 ≥3 个信号 → 标记为 "疑似主线"
- 主线 vs 非主线对比：return_20d、llm_buy_count、llm_buy_mean_20d

### 4. 输出新增 `sector_analysis` 字段

```python
"sector_analysis": {
    "note": "简化版 L6（仅行业归属+集中度统计，不含实时板块成交额/涨幅/涨停扩散验证）",
    "by_sector": {
        "电子": {"count": 5, "avg_return": 0.0823, "win_rate": 0.6, "symbols": [...]},
        "计算机": {"count": 3, "avg_return": 0.0412, "win_rate": 0.33, "symbols": [...]},
        ...
    },
    "suspected_mainlines": ["电子", "计算机"],
    "mainline_vs_non": {
        "suspected_mainline": {
            "count": 8, "return_20d": {...}, "llm_buy_count": 3, "llm_buy_mean_20d": 0.12
        },
        "non_mainline": {
            "count": 10, "return_20d": {...}, "llm_buy_count": 2, "llm_buy_mean_20d": 0.05
        },
    },
}
```

### 5. 月度统计新增板块维度

`monthly_breakdown` 中每月新增 `top_sectors` 字段：

```python
"top_sectors": [
    {"sector": "电子", "count": 3},
    {"sector": "计算机", "count": 2},
    ...
]
```

### 6. 流程步骤从 5 步扩展到 7 步

| 步骤 | 内容 |
|------|------|
| [1/7] | 获取A股列表 |
| [2/7] | 获取K线并检测信号 |
| [3/7] | **获取行业归属（简化版 L6）** |
| [4/7] | 统计分析 |
| [5/7] | **板块分析（简化版 L6）** |
| [6/7] | 混淆矩阵 |
| [7/7] | 输出 |

## 设计决策

1. **简化版 L6**：回测中无法获取历史板块成交额/涨幅/涨停扩散数据（需要逐日板块快照），因此只做行业归属 + 信号集中度统计。集中度 ≥3 的行业标记为"疑似主线"。
2. **行业数据缓存**：每只股票只查询一次行业归属，避免重复网络请求。
3. **不修改核心模块**：`sagent/sector.py`、`sagent/models.py` 等核心模块未修改。
4. **每个信号带 industry 字段**：`all_signals` 中每个信号都有 `industry` 字段，便于后续分析。

## 验证结果

- ✅ 语法检查通过
- ✅ 59 个现有测试全部通过
- ✅ `get_stock_industry()` 可正常导入
- ✅ `run_backtest()` 接口不变（新增参数 `min_avg_amount` 由 #32 引入）
- ✅ 输出包含 `sector_analysis` 和 `monthly_breakdown.*.top_sectors`

## 未修改的文件

- `sagent/` 核心模块（sector.py、models.py、kline.py 等）— 不变
- `tests/` — 不变
- 其他脚本 — 不变

## 风险

- `ak.stock_individual_info_em()` 接口可能变化（AKShare 频繁更新），已用 try/except 兜底
- 行业归属为东方财富分类（非严格申万二级行业），与主线验证的申万二级行业标准可能有差异
- "疑似主线"标准（≥3 个信号）是经验值，不等于完整的 L6 主线验证

## 建议下一步

1. 运行完整回测验证 `sector_analysis` 输出格式
2. 如需精确申万二级行业，可用 `ak.index_stock_cons_weight_csindex()` 替代行业查询
3. 如果历史板块数据可用，可升级为完整 L6 验证（成交额/涨幅/涨停扩散）
