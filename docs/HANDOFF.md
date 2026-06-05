# Sagent Handoff — Session 9

**日期**: 2026-06-05 · **仓库**: `D:\suishi\sagent` · **分支**: `master`
**测试**: 117 passing · **Python**: Anaconda `D:\ProgramData\anaconda3`

---

## 本次会话完成内容

### 策略模块拆分（Step 1-4 全部完成）

**Step 1** (`10a34f4`): 提取 `strategy/params.py`
- 6 个参数类：SignalParams, JudgeParams, StopLossParams, ScanParams, EntryParams, PortfolioParams
- 所有策略阈值集中管理，可外部覆盖
- technical.py, backtest_engine.py, backtest_portfolio.py, run_backtest_period.py 全部改为从 params 导入

**Step 2** (`da50e1e`): 拆分 `technical.py`
- `strategy/signal.py`: 信号检测（check_signal_from_closes, _check_candidate_conditions, technical_candidates, filter_stock_pool, _ma）
- `strategy/judge.py`: LLM 规则引擎（simulated_llm_judge）
- `technical.py`: 改为 re-export 兼容层，现有 import 不断

**Step 3** (`6d3b03a`): 提取 `strategy/scanner.py`
- forward_returns, desc, scan_signals_from_closes, load_and_filter_signals
- run_backtest() 使用 scanner 函数，消除 ~100 行重复代码
- run_engine_backtest 暂保留内联

**Step 4** (`1216f0d`): 新增 `strategy/entry.py` 入场确认
- confirm_entry() 支持次日确认
- simulate_trade 支持 ep 参数（EntryParams）
- 默认不启用，向后兼容

---

## 当前 strategy 模块结构

```
sagent/strategy/
  __init__.py       # 统一导出
  params.py         # 6 个参数类（集中管理所有阈值）
  signal.py         # 信号检测 + 候选股筛选
  judge.py          # LLM 规则引擎 v3
  scanner.py        # 批量扫描 + 前向收益 + 统计
  entry.py          # 入场确认（次日确认机制）
```

---

## 回测关键数据（v3 规则，供下次对比用）

```
165 笔交易 | 胜率 40.6% | 均收 +2.66% | 组合 -9.09%
止损 99 笔(60%) 均亏 -7.93% | 自然到期 66 笔(40%) 均赚 +18.55%
半仓止盈触发 39 笔(23.6%) 触发后均收 +27.31%

早期止损（-7天）: 61 笔, 胜率 0%, 全部止损
  - 1天退出 13笔, 2天 14笔, 4天 18笔
  - 止损类型: 绝对止损10% 25笔, 关键低点 36笔
  - 入场到止损平均距离仅 7.9%

LLM 判断分布（v3）
  买入: 79笔, 胜率44%, 均收+2.55%, 止损率59%
  观察: 86笔, 胜率37%, 均收+2.76%, 止损率60%

月度: 12月 49% | 2月 45% | 4月 33%
```

---

## 下次会话重点

### 1. 启用入场确认并回测对比
```python
ep = EntryParams(require_next_day_confirm=True, confirm_drop=0.02)
```
目标：将 61 笔 0% 胜率的早期止损减少，提升整体胜率。

### 2. 继续提取 run_engine_backtest 的重复代码
当前 run_engine_backtest 仍有大量与 run_backtest 相同的扫描逻辑。

### 3. 参数调优
- EntryParams.confirm_drop: 0.01 vs 0.02 vs 0.03
- StopLossParams.absolute_stop: 0.08 vs 0.10 vs 0.12
- JudgeParams 的各阈值

---

## 技术备忘
- **PowerShell 不支持 `&&`**: 用 `;` 或分步执行
- **回测三步流程**: 回测 → 生成图 → 生成报表（见 AGENTS.md）
- **策略参数**: 全部在 `sagent/strategy/params.py`，改动只改一处
- **backward compat**: 所有函数签名保持兼容，不传参时行为与改动前完全一致
- **mootdx import 警告**: LSP 报错但运行时正常
