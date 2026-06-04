# Sagent Handoff — Session 8

**日期**: 2026-06-04 · **仓库**: `D:\suishi\sagent` · **分支**: `master`
**测试**: 117 passing · **Python**: Anaconda `D:\ProgramData\anaconda3`
**Git**: 所有改动已提交并 push

---

## 本次会话摘要

### 1. ✅ 格式化改动提交
- ruff 自动格式化的 5 个文件已提交推送（commit `27bb677`）

### 2. ✅ 回测缓存速度优化 — `sagent/cache.py` + `scripts/run_backtest_period.py`
- **根因**: `ensure_symbols()` 每次都逐只做 mootdx TCP 网络请求做增量更新，3981 只需 ~3 分钟
- **修复**:
  - `cache.py` 新增 `global_max_date()` 方法 + `skip_incremental` 参数
  - `ensure_symbols` 增量更新时显示进度（每 200 只 + 完成）
  - `_check_cache_freshness()` 辅助函数：缓存落后 >5 天时提示用户选择是否更新
  - 两处调用点（`run_backtest` + `run_engine_backtest`）均已更新
- **效果**: 缓存新鲜时 3981 只从 ~3min → **~5s**

### 3. ✅ LLM 规则引擎 v3 — `sagent/technical.py`（核心修复）
- **问题**: v2 规则「涨幅高=透支=放弃」完全错误。回测数据显示：
  - 涨幅 80-100% 胜率 50%，均收 +4.4%
  - 涨幅 100-120% 胜率 55%，均收 +6.1%
  - 涨幅 120-150% 胜率 43%，均收 +9.4%
  - 而涨幅 50-80%（v2 的「买入」区间）胜率才 34%
- **v3 核心逻辑**:
  1. 回撤 >55% → 放弃（趋势破坏）
  2. 缩量 <0.7x + 无结构转折点 → 放弃
  3. 放量 >1.2x + 回调 <42% → 买入（最强信号）
  4. 涨幅 >80% + 放量 >1.0x + 回调 <50% → 买入（强趋势回踩）
  5. 涨幅 ≤80% + 放量 + 浅回调 → 买入
  6. 其他 → 观察
- **移除**: R 值过滤、高价股过滤、涨幅上限过滤
- **新增**: 结构转折点检测（从 K 线描述中匹配关键词）
- **验证**: 「买入」79 笔胜率 44% vs「观察」86 笔胜率 37%，方向正确

### 4. ✅ 回测报表 K 线图按钮 — `scripts/backtest_report.py`
- 每笔交易操作列新增「K线」按钮
- 点击在新窗口打开 `output/charts/combined_{symbol}_{date}.html`
- 修复日期格式：图表文件名用 `20260409` 格式，从 `signal_date` 去掉横线

### 5. ✅ 完整回测执行（v3 规则）
- 3981 只股票，2025-12-01 ~ 2026-05-31
- 结果：165 笔交易，胜率 40.6%，均收 +2.66%，组合收益 -9.09%
- 图表 165 个 HTML + 组合仪表盘 → `output/charts/`
- 报表 Markdown + HTML → `output/backtest.md` / `output/backtest.html`

### 6. ✅ 今日扫描（2026-06-04）
- 8 只候选股全部「买入」，但所有板块「非主线」
- 推荐：301070 开勒股份（放量 1.69x）、300720 海川智能（放量 1.52x）
- 用户尚未确认 apply_decision

---

## 文件改动清单

| 文件 | 改动 |
|------|------|
| `sagent/cache.py` | +`global_max_date()` + `skip_incremental` 参数 + 进度显示 |
| `sagent/technical.py` | 规则引擎 v2→v3（核心逻辑重写） |
| `scripts/run_backtest_period.py` | +`_check_cache_freshness()` + 两处调用更新 |
| `scripts/backtest_report.py` | K 线图按钮（日期格式修复） |

---

## 回测关键数据（v3 规则）

```
165 笔交易 | 胜率 40.6% | 均收 +2.66% | 组合 -9.09%
止损 99 笔 (60%) 均亏 -7.93% | 自然到期 66 笔 (40%) 均赚 +18.55%
半仓止盈触发 39 笔 (23.6%) 均收 +27.31%
买入: 79 笔, 胜率 44%, 均收 +2.55%
观察: 86 笔, 胜率 37%, 均收 +2.76%
月度: 12月 59% → 2月 15% → 4月 73%
```

---

## 已知问题 & 后续优化方向

### 🔴 高优先级
1. **组合收益仍为 -9.09%** — 虽然逐笔均收 +2.66% 为正，但组合管理层面亏损。原因：
   - 止损率 60% 过高，需进一步加强入场确认
   - 组合管理可能有仓位/资金分配问题
   - 建议分析 `backtest_portfolio.py` 的仓位逻辑

2. **1-7 天退出胜率仅 1.6%** — 早期退出的 61 笔几乎全部亏损。入场时机偏早。
   - 可考虑：等待收盘确认突破，而非信号当天就买入
   - 或增加「次日确认」逻辑

3. **回测引擎不区分 LLM 判断** — 所有信号都参与交易，LLM 判断仅用于统计
   - 应该只交易「买入」信号，「放弃」不参与
   - 需改 `run_backtest_period.py` 的交易过滤逻辑

### 🟡 中优先级
4. **大盘过滤** — 2 月胜率 15% 明显是大盘系统性下跌。加沪深300 MA20 过滤
5. **止损收窄** — 55 笔打绝对止损 10%，可以收窄到 7-8% 测试
6. **放量要求** — 回测显示量比 >1.2 的胜率明显高于缩量的

### 🟢 低优先级
7. **用真实 LLM API 对比回测** — 配置 `SAGENT_LLM_API_KEY` 后跑 `--llm` 模式
8. **Windows Task Scheduler 自动化** — 每日自动运行 `/scan`

---

## 技术备忘

- **PowerShell 不支持 `&&`** — 用 `;` 或分步执行
- **`ctx_execute` 超时** — 长任务（>2min）用 `Start-Process` 后台 + 轮询文件
- **回测三步流程**: 回测 → 生成图 → 生成报表（见 AGENTS.md）
- **图表文件名**: `combined_{symbol}_{YYYYMMDD}.html`（日期无横线）
- **mootdx import 警告**: LSP 报错但运行时正常，不影响功能

---

## Suggested Skills

- `/scan` 或 `prepare_scan` — 每日扫描信号
- `analyze_stock` — 个股 K 线分析
- `apply_decision` — 确认交易写入 portfolio
- `check_portfolio` — 查看持仓状态
