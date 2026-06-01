# sagent Handoff Document

**Date**: 2026-06-01
**Session Focus**: 回测系统建设 + 系统缺陷发现 + 可视化规划
**Next Session Focus**: 按 issues 优先级实施修复和功能开发

---

## 1. Project Overview

**sagent** 是一个基于 pi 的 A 股主线交易分析 agent。核心流程：
1. 每日收盘后扫描全 A 股（量化粗筛 L1-L5）
2. 板块主线验证（L6，申万二级行业）
3. LLM 形态精筛（判断买入/观察/放弃）
4. 持仓监控（止损/止盈/趋势破坏）

**Domain doc**: `CONTEXT.md`（必读，包含完整策略规则）
**Repo**: `shandianxiao218/sagent` on GitHub

---

## 2. What Was Done This Session

### 2.1 纯量化回测（无 LLM）
- 采样 300→800→1500 只股票，mootdx TCP 获取 370 日 K 线
- 滑动窗口检测 L1-L5 信号，计算 5d/10d/20d forward return
- 结果：72 个信号（2025-12 ~ 2026-04），均值 +5.27%，胜率 53%，止损率 35%
- **脚本**: `scripts/run_backtest.py`, `scripts/run_backtest_period.py`
- **结果**: `backtest_result_v2.json`, `backtest_oct25_jun26.json`, `backtest_oct25_jun26_full.json`

### 2.2 LLM 形态盲判（方案 A + B）
- **方案 A**: 对 27 个信号做真实 LLM 形态盲判
  - 买入精确率 83.3%，均值收益 +40.09%（纯量化 +9.55%）
  - 止损率从 37% 降到 16.7%
- **方案 B**: 对 10 个验证案例盲判，宽松准确率 100%
- **文件**: `backtest_llm_judgement_a.json`, `backtest_llm_judgement_b.json`, `backtest_llm_analysis.json`
- **脚本**: `scripts/prepare_llm_judge.py`, `scripts/analyze_llm_judge.py`

### 2.3 关键发现：回测系统存在根本性缺陷
用户指出南大光电亏损 -19.6% 但没有执行止损（应该 -5% 就止损）。系统性检查后确认 10 个遗漏项，创建了 10 个 GitHub Issues (#23-#32)。

### 2.4 可视化规划
用户要求回测 K 线图显示买卖点、LLM 判断、关键高低点等。分解为 5 个 issues (#33-#37)。

---

## 3. Critical Findings / Decisions

### 回测数字不可信
当前回测的收益数据（+5.27%, +40.09% 等）**没有参考价值**，因为：
1. **止损未执行**：南大光电应 -5% 止损，回测显示 -19.6%
2. **止盈未执行**：福达合金应有半仓止盈，回测假设全程持有
3. **key_low 计算错误**：用最近 15 日最低价，不是利弗摩尔结构转折低点

### LLM 形态判断确实有增量价值
方案 A 证明 LLM 能显著提升候选池质量（精确率 83%，收益 4x），但这是在止损未执行的前提下的结论，需要重跑。

### 回测中 LLM 规则引擎模拟效果差
用简单规则模拟 LLM 判断（`scripts/run_backtest_period.py` 中的 `simulated_llm_judge`），精确率只有 27%，远低于真实 LLM 的 83%。原因：规则引擎无法识别"阶段高点放量见顶"等复杂形态。

---

## 4. Open Issues (15 total)

### Priority 0 — 阻塞所有后续工作
| # | Title | Key Point |
|---|---|---|
| **#24** | key_low 计算方法错误 | 当前用 `min(bars[-15:], key=low)`，应改为结构转折低点检测 |
| **#23** | 回测引擎缺少止损/止盈 | 只有"买入持有20天收益"，没有逐日止损/止盈 |

### Priority 1 — 策略完整性
| # | Title |
|---|---|
| **#26** | 止损价计算与执行验证 |
| **#27** | 半仓止盈与趋势破坏退出 |
| **#25** | 预期盈亏比计算与筛选 |
| **#29** | 组合级持仓生命周期管理回测 |

### Priority 2 — 增强
| # | Title |
|---|---|
| **#28** | 趋势破坏参考位自动识别 |
| **#30** | 主线验证层（L6）集成 |
| **#31** | LLM 精筛增加 key_low 结构识别 |

### 可视化（依赖 #23-#29 完成后再做）
| # | Title |
|---|---|
| **#33** | K 线绘图基础模块（plotly） |
| **#34** | 单股信号标注可视化 |
| **#35** | 波峰波谷结构与趋势线可视化 |
| **#36** | 单笔交易生命周期可视化 |
| **#37** | 组合级回测仪表盘 |

### Priority 3
| # | Title |
|---|---|
| **#32** | 成交额过滤 |

### 依赖关系与建议实施顺序
```
#24 key_low → #23 止损止盈引擎 → #26 止损验证
→ #27 止盈 → #25 盈亏比 → #28 趋势破坏
→ #29 组合管理 → #33-#37 可视化
→ #30 主线 → #31 LLM key_low → #32 成交额
```

---

## 5. Key Files and Their Roles

| Path | Purpose |
|---|---|
| `CONTEXT.md` | 领域上下文，完整策略规则（必读） |
| `sagent/models.py` | 所有数据结构（StockInfo, DailyBar, Position, Decision 等） |
| `sagent/kline.py` | K 线描述生成（key_low 计算在这里，需修复） |
| `sagent/technical.py` | 量化粗筛（L1-L5），`_ma()`, `filter_stock_pool()`, `technical_candidates()` |
| `sagent/sector.py` | 板块主线验证（L6） |
| `sagent/llm.py` | LLM prompt 构建 + 规则引擎 fallback |
| `sagent/portfolio.py` | 持仓管理、买入确认、持仓监控 |
| `sagent/backtest.py` | 旧版分层回测（需要重写） |
| `sagent/data.py` | 数据源（mootdx TCP + AKShare + fixture） |
| `scripts/run_backtest.py` | 第一版回测脚本（无止损止盈） |
| `scripts/run_backtest_period.py` | 定向区间回测（含规则引擎模拟 LLM） |
| `scripts/prepare_llm_judge.py` | 提取信号 K 线描述供 LLM 判断 |
| `scripts/analyze_llm_judge.py` | 分析 LLM 判断结果与 forward 对比 |
| `fixtures/validation/llm_cases.json` | 10 个验证案例（4 正例 + 4 反例 + 2 边界） |
| `config/default.json` | 策略配置文件 |

---

## 6. Environment Notes

- **Runtime**: Python 3.12 (Anaconda), Windows
- **Data source**: mootdx TCP（通达信协议，直连不封 IP）+ AKShare
- **Key deps**: mootdx 0.11.7, akshare 1.18.64, pandas 2.2.2, plotly 5.24.1, matplotlib 3.9.2, mplfinance 0.12.10b0
- **LLM**: 回测中未调用真实 LLM API，用的是规则引擎模拟或人工盲判
- **GitHub CLI**: `gh` 已配置，可创建/查看/评论 issues
- **Issue labels**: `bug`, `enhancement`, `ready-for-agent`, `ready-for-human`, `needs-triage`, `needs-info`, `wontfix`

---

## 7. Suggested Skills

| Skill | When to Use |
|---|---|
| `tdd` | 实施每个 issue 时先写测试（特别是 #24 key_low 算法、#23 止损止盈逻辑） |
| `diagnose` | 如果 mootdx 连接不稳定或数据异常 |
| `triage` | 如果需要重新评估 issues 优先级 |
| `context-mode` | 处理大量回测输出数据时使用 ctx_execute 而非直接读取 |
| `pi-subagents` | 多个独立 issue 可并行用 subagent 实施 |

---

## 8. Things to Watch Out For

1. **Windows 环境**：PowerShell 的 `&&` 不工作，用 `;` 分号代替，或分步执行
2. **mootdx 连接**：有时 TCP 连接会超时，需要重试；mootdx 的 `vol` 字段（不是 `volume`）是成交量
3. **K 线数据量**：370 日 K 线只覆盖约 1.5 年，信号最早从 2025-12 开始，无法回测更早区间
4. **ST 股票**：量化粗筛已过滤 ST，但 `find_real_cases.py` 采样时没有过滤，导致 ST 京蓝出现在回测中
5. **describe_stock() 的 key_low**：当前是 `min(bar.low for bar in bars[-15:])`，这是 #24 要修复的核心问题
6. **不要重复已完成的工作**：LLM 盲判数据已保存在 json 文件中，不需要重新做

---

## 9. Continuation Instructions for Next Agent

本 session 的工作已全部完成，所有改进项已创建为 GitHub Issues。后续 agent 可以立即开始实施。

### 立即可开始的工作

#### Step 1: #24 — 修复 key_low 计算方法
这是最高优先级，因为 key_low 影响止损价、盈亏比、止盈触发。

**具体步骤**：
1. 读取 `sagent/kline.py`，找到 `describe_stock()` 中 `key_low = min(bar.low for bar in bars[-15:])`
2. 实现局部最低点检测算法（Swing Low Detection）：
   - 遍历回调区间（从阶段高点到当前）
   - 某日 low < 前 5 日 low 且 < 后 3 日 low → 标记为 swing low
   - 取最后一个 swing low 作为 key_low
3. 写测试：用 `fixtures/validation/llm_cases.json` 的案例验证
4. 更新 K 线描述文本，标注 key_low 的结构意义

**验证**：南大光电 300346 的 key_low 应在 51.29 附近（当前为 51.57）

#### Step 2: #23 — 重写回测引擎（逐日止损/止盈）
依赖 #24 完成后进行。

**具体步骤**：
1. 创建新模块 `sagent/backtest_engine.py`（或在 `scripts/run_backtest_period.py` 中重写）
2. 核心逻辑：对每个信号，从买入次日逐日遍历 bars
3. 每日检查：止损（max(买入价×0.95, key_low)）、止盈（R≥2.5 半仓）
4. 输出 `TradeLifecycle` 数据（含逐日事件）
5. 用南大光电验证：止损应在 -5% 触发而非 -19.6%

#### Step 3: #26 — 止损验证
用多个案例验证止损逻辑正确后，继续 #27 止盈 → #25 盈亏比 → #28 趋势破坏

#### Step 4: #29 — 组合管理
整合所有单笔交易逻辑，模拟真实资金管理（初始资金 100K，每笔 10%，每周 ≤2 笔）

#### Step 5: #33-#37 — 可视化
组合管理完成后，实现 K 线可视化（plotly），输出 HTML 图表

### 如何确认 issue 完成
每个 issue 都有详细的验收标准（checkbox 格式），用 `gh issue view <number>` 查看。完成所有 checkbox 后关闭 issue：
```bash
gh issue close <number> --comment "全部验收标准已满足"
```

### 不可跳过的步骤
1. **每个 issue 都要先写测试**（tdd skill），特别是算法类（#24, #23, #28）
2. **用真实案例验证**：南大光电（止损）、福达合金（止盈）、高乐股份（自然退出）
3. **运行现有测试**：`cd D:\suishi\sagent; python -m pytest tests/ -v` 确保不破坏已有功能

### Git 工作流
```bash
git pull origin master
# 做改动 → 测试通过
git add . && git commit -m "fix: #24 修复key_low计算方法"
git push origin master
```
