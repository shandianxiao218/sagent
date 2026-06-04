# Sagent Handoff — Session 6

**日期**: 2026-06-04 · **仓库**: `D:\suishi\sagent` · **分支**: `master`
**测试**: 110 passing · **Python**: Anaconda `D:\ProgramData\anaconda3`
**Git**: 所有改动已提交并 push

---

## 本次会话摘要

### 1. 关闭 Issue #38 — 简化止损策略
- 止损价从 `max(entry×0.92, key_low)` → `max(entry×0.90, key_low×0.97)`
- 止损类型标签：绝对止损10% / 关键低点
- CONTEXT.md 止损规则已同步更新

### 2. 回测三图合并为一
- `plot_combined_trade_chart()`: K 线 + 成交量 + R 值曲线三行子图
- 每笔交易只输出 1 个 combined HTML（原 3 个）

### 3. 图表显示股票代码和所属板块
- 标题显示行业 + 前 2 个概念板块

### 4. 三项架构优化
- **C3**: models.py 拆分为 market/signal/chart_models/portfolio/sector + re-export 兼容层
- **C2**: sector.py 新增 SectorStore 深模块，统一行业/概念/K线/主线验证入口
- **C1**: 信号检测 + LLM 模拟判断提取到 technical.py，脚本 1138→1010 行

### 5. 清理根目录临时文件
- 删除 21 个临时文件 + 634 个 charts HTML
- 新建 `output/` 统一临时产出目录
- AGENTS.md 新增「临时文件规则」

---

## 文件改动清单

| 文件 | 角色 | 改动类型 |
|------|------|---------|
| `sagent/market.py` | 行情数据模型 | 新增 |
| `sagent/signal.py` | 信号检测模型 | 新增 |
| `sagent/chart_models.py` | 图表标注模型 | 新增 |
| `sagent/models.py` | re-export 兼容层 | 重写 |
| `sagent/portfolio.py` | +5 个 dataclass 定义 | 修改 |
| `sagent/sector.py` | +3 个 dataclass + SectorStore | 修改 |
| `sagent/technical.py` | +check_signal_from_closes + simulated_llm_judge | 修改 |
| `sagent/chart.py` | +plot_combined_trade_chart（含 sector_info） | 修改 |
| `scripts/run_backtest_period.py` | 删除内联函数，默认输出→output/ | 修改 |
| `scripts/generate_charts.py` | 合并图表+板块获取+默认→output/charts/ | 修改 |
| `CONTEXT.md` | 止损公式更新 | 修改 |
| `AGENTS.md` | +临时文件规则 | 修改 |
| `.gitignore` | output/ 覆盖规则 | 修改 |

---

## 回测标准流程（已写入 AGENTS.md）

```bash
# 1. 回测（~10s，3981只）
python scripts/run_backtest_period.py --start 2025-12-01 --end 2026-05-31 \
  --sample 5500 --engine --cache data/bars.db --output output/backtest.json

# 2. 生成图（~30s，从缓存加载）
python scripts/generate_charts.py --input output/backtest.json --cache data/bars.db --output-dir output/charts

# 3. 生成报表（<1s，同时输出 MD + HTML）
python scripts/backtest_report.py --input output/backtest.json
```

---

## 待办事项

### 高优先级
1. **Replace rule-engine LLM mock with real LLM API** — 预期精确率 ~83% vs 当前 ~40%
2. **行业归属优化** — 逐只 AKShare 查行业太慢，改为 SectorStore 缓存

### 中优先级
3. **信号质量优化** — 止损率仍偏高，需要更严格的入场条件
4. **组合管理优化** — 周限 2 笔太保守
5. **缓存预热脚本** — `scripts/warmup_cache.py`

### 低优先级
6. PowerShell GBK 中文乱码
7. LSP plotly import warnings

---

## 已知陷阱

- **models.py re-export**: `from sagent.models import ...` 仍有效。新代码应直接 import 领域模块
- **SectorStore 是 Facade**: 内部委托给 SectorCache 和 SectorBarCache
- **防未来函数**: 回测 K 线通过 `daily_bars_up_to(symbol, end_date)` SQL 截断
- **PowerShell `&&` 不工作**: 用 `;` 或分步执行
- **临时文件规则**: 所有产出必须放 `output/`，见 AGENTS.md
