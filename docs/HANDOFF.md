# Sagent Handoff — Session 5 完整记录

**日期**: 2026-06-03 · **仓库**: `D:\suishi\sagent` · **分支**: `master`
**测试**: 108 passing · **Python**: Anaconda `D:\ProgramData\anaconda3`
**Git**: 大量 new/modified 文件待提交

---

## 本次会话完整改动

### 改动 1：回测改为 SQLite 缓存模式 + 防未来函数

**问题**：回测直连 mootdx，3981 只 ~4 分钟，无防未来函数保护。

**解决方案**（`sagent/cache.py` 新增 3 个方法）：
- `daily_bars_up_to(symbol, max_date)` — SQL 层截断，只返回 ≤ max_date 的 K 线
- `bulk_daily_bars_up_to(symbols, max_date)` — 批量版本
- `bulk_closes_up_to(symbols, max_date)` — 轻量版只取 (date, close)，比 DailyBar 快 ~10x

**防未来函数机制**：回测时所有 K 线通过 `daily_bars_up_to(symbol, end_date)` 加载，SQL `WHERE date <= ?` 保证不包含 end_date 之后的数据。信号检测只看 `closes[:idx+1]`。

### 改动 2：回测信号扫描优化（40x 提速）

三轮优化过程：
1. `check_signal(bars, idx)` 每次从 DailyBar 列表重建 closes → `check_signal_from_closes(closes, idx)` 预提取 closes 数组（21x）
2. 两阶段加载：Phase A 用 `bulk_closes_up_to` 轻量扫描 → Phase B 只为信号股加载 DailyBar（~10x）
3. 最终：closes 加载 0.16s + 扫描 0.05s = **0.21s / 200 只**，旧版直连 ~4.7s

### 改动 3：回测输出补充选股理由 + LLM 判断

引擎回测每笔交易现在包含：
- `metrics` — 选股指标（MA250、60日涨幅、回调比、60日高低点）
- `kline_description` — K 线形态描述（`describe_stock()` 输出）
- `llm_action` / `llm_reason` / `llm_confidence` — LLM 模拟判断

### 改动 4：报表同时生成 Markdown + HTML

`backtest_report.py` 生成：
- Markdown 报表（7 个章节）
- HTML 交互式报表：165 笔交易明细表，每笔可展开查看选股指标、LLM 判断、K 线描述

### 改动 5：`AGENTS.md` 新增回测管线规则

报表必须包含：选股理由、LLM 判断理由、HTML 交互式报表、免责声明。

---

## 文件改动清单

| 文件 | 角色 | 改动类型 |
|------|------|---------|
| `sagent/cache.py` | +3 个防未来函数/轻量方法 | 修改 |
| `scripts/run_backtest_period.py` | 缓存+两阶段+选股理由+LLM判断 | 修改 |
| `scripts/generate_charts.py` | 改用缓存+CLI参数 | 修改 |
| `scripts/backtest_report.py` | Markdown+HTML报表生成器 | 新增 |
| `scripts/benchmark_backtest_cache.py` | 回测性能基准测试 | 新增 |
| `tests/test_cache.py` | +4 防未来函数测试（共16个） | 修改 |
| `AGENTS.md` | +Backtest pipeline 规则 | 修改 |
| `docs/HANDOFF.md` | 项目级 handoff | 修改 |

## 回测产出文件（已生成）

| 文件 | 大小 | 内容 |
|------|------|------|
| `backtest_6m_full.json` | 2.1MB | 回测数据（165笔，含选股理由+LLM判断） |
| `backtest_6m_full.md` | 7KB | Markdown 报表 |
| `backtest_6m_full.html` | 238KB | 交互式 HTML 报表 |
| `charts/` | 496 个 HTML | 信号图+结构图+生命周期图+仪表盘 |

## 回测标准流程（已写入 AGENTS.md）

```bash
# 1. 回测（~10s，3981只）
python scripts/run_backtest_period.py --start 2025-12-01 --end 2026-05-31 \
  --sample 5500 --engine --cache data/bars.db --output backtest_6m_full.json

# 2. 生成图（~30s，从缓存加载）
python scripts/generate_charts.py --input backtest_6m_full.json --cache data/bars.db

# 3. 生成报表（<1s，同时输出 MD + HTML）
python scripts/backtest_report.py --input backtest_6m_full.json
```

---

## 回测结果概要 (2025-12-01 ~ 2026-05-31)

- 3981 只扫描 → 165 笔交易
- 逐笔均收益 +2.66%，胜率 40.6%，止损率 60%
- 组合管理总收益 -9.09%（周限2笔只执行了40笔）
- 4 月最佳 +14.84%，2 月最差 -4.84%

---

## 待办事项

### 高优先级
1. **Replace rule-engine LLM mock with real LLM API** — 预期精确率 ~83% vs 当前 ~40%
2. **行业归属优化** — 逐只 AKShare 查行业太慢，改为申万二级分类缓存

### 中优先级
3. **信号质量优化** — 止损率 60% 过高，需要更严格的入场条件
   - ✅ 已完成：止损策略已从 max(entry×0.92, key_low) 更新为 max(entry×0.90, key_low×0.97)（issue #38）
4. **组合管理优化** — 周限 2 笔太保守
5. **缓存预热脚本** — `scripts/warmup_cache.py`

### 低优先级
6. PowerShell GBK 中文乱码
7. LSP plotly import warnings

---

## 已知陷阱

- **防未来函数**：所有 K 线通过 `daily_bars_up_to(symbol, end_date)` SQL 截断
- **两阶段加载**：Phase A 轻量 closes 扫描 → Phase B 只加载信号股 DailyBar
- **SQLite WAL 模式**：并发安全但同进程不要多线程共享连接
- **`generate_charts.py` 每笔交易 3 个 HTML**：165 笔 = 496 文件
- **PowerShell `&&` 不工作**：用 `;` 或分步执行

---

## Suggested Skills

- **handoff** — 当前 skill，用于会话交接
- **diagnose** — 如果遇到回测数据异常或性能回归，用此 skill 排查
- **grill-with-docs** — 如果要修改回测策略参数，用此 skill 对照 CONTEXT.md 和 ADRs 验证
- **tdd** — 如果要新增回测策略层（如新止损规则），建议 TDD 方式开发

### 项目内关键文档
- `docs/HANDOFF.md` — 项目持久化 handoff（随 git 提交）
- `AGENTS.md` — 回测管线规则
- `CONTEXT.md` — 领域模型
- `docs/adr/` — 架构决策记录
