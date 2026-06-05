# Sagent Handoff — Session 8

**日期**: 2026-06-04 · **仓库**: `D:\suishi\sagent` · **分支**: `master`
**测试**: 117 passing · **Python**: Anaconda `D:\ProgramData\anaconda3`
**Git**: 所有改动已提交并 push（HEAD = `1dfc07d`）

---

## 本次会话完成内容

### 1. 格式化改动提交（`27bb677`）
### 2. 回测缓存速度优化（`792ff35`）
- `cache.py` 新增 `global_max_date()` + `skip_incremental` 参数 + 进度显示
- `run_backtest_period.py` 新增 `_check_cache_freshness()` — 缓存落后 >5 天时提示用户选择
- 效果：缓存新鲜时 3981 只从 ~3min → **~5s**
### 3. LLM 规则引擎 v3（`4010822`）
- `technical.py` 重写：移除「涨幅高=透支」错误逻辑，改为数据驱动的放量/回撤/结构转折判断
- 「买入」79 笔胜率 44% vs「观察」86 笔胜率 37%，方向正确
### 4. 回测报表 K 线图按钮（`4010822`）
- `backtest_report.py` 每笔交易新增「K线」按钮，链接到 `output/charts/combined_{symbol}_{YYYYMMDD}.html`
### 5. 完整回测 + 今日扫描
- 回测结果：165 笔，胜率 40.6%，均收 +2.66%，组合 -9.09%
- 扫描 8 只候选股，所有板块非主线，推荐 301070 开勒股份 / 300720 海川智能

---

## 下次会话重点：策略模块拆分（Step 1-4）

用户明确要求实施策略架构拆分。详细计划已在本次对话中列出，核心问题：

**策略逻辑没有和其它部分分开：**
- `run_backtest_period.py` 1155 行中 76%（875 行）是策略逻辑
- 策略参数散落在 4 个文件：`technical.py`、`run_backtest_period.py`、`backtest_engine.py`、`config/default.json`
- `technical.py` 272 行混合了信号检测 + LLM 判断 + K 线描述

### Step 1: 提取 `strategy/params.py`（~100 行新增，极低风险）

集中管理所有策略阈值到一个文件：

```python
# sagent/strategy/params.py
class SignalParams:    # min_rise_60d=0.5, pullback_min=0.15, pullback_max=0.50
class JudgeParams:     # pullback_abandon=0.55, volume_abandon=0.70, volume_strong=1.20, etc.
class StopLossParams:  # absolute_stop=0.10, key_low_buffer=0.03, half_profit_r=1.5
class ScanParams:      # min_bars=300, window_step=3, min_avg_amount=1e8, max_holding=20
class EntryParams:     # require_next_day_confirm=False (新增)
```

**改动文件**：
- 新建 `sagent/strategy/__init__.py` + `sagent/strategy/params.py`
- 修改 `sagent/technical.py` — 从 params 导入阈值替换硬编码
- 修改 `sagent/backtest_engine.py` — 从 params 导入止损参数
- 修改 `scripts/run_backtest_period.py` — 从 params 导入扫描参数

**验证**：`pytest tests/ -x` + 100 支回测结果不变

### Step 2: 拆分 `technical.py` → `strategy/signal.py` + `strategy/judge.py`（~50 行移动，低风险）

| 原位置 | 目标 | 内容 |
|--------|------|------|
| `technical.py` 的 `check_signal_from_closes()` | `strategy/signal.py` | 纯数学信号检测 |
| `technical.py` 的 `simulated_llm_judge()` | `strategy/judge.py` | 规则引擎 + 量比/转折点提取 |
| `technical.py` 的 `describe_*()` 辅助函数 | `strategy/signal.py` | 统计描述 |

`technical.py` 改为 re-export 兼容层，现有 import 不断。

### Step 3: 从 `run_backtest_period.py` 提取策略逻辑（~875 行移动，中风险）

| 脚本中的函数/逻辑 | 目标 | 行数 |
|------------------|------|------|
| `_judge_signal()` | `strategy/judge.py` | 43 |
| `forward_returns()`, `desc()` | `strategy/signal.py` | 47 |
| 信号扫描循环 (Phase A) + 成交额过滤 | `strategy/scanner.py`（新） | ~60 |
| `run_backtest()`, `run_engine_backtest()` | `backtest_runner.py`（新） | 805 |

**目标**：`run_backtest_period.py` 从 1155 行 → ~200 行纯 CLI 入口

新建文件：
- `sagent/strategy/scanner.py` — 批量信号扫描（closes + 日期 → 信号列表）
- `sagent/backtest_runner.py` — 回测编排（数据加载→扫描→交易→统计→输出 JSON）

### Step 4: 新增 `strategy/entry.py` 入场确认（~80 行新增，低风险）

**解决核心痛点**：1-7 天退出的 61 笔交易胜率 0%，全部止损。原因是信号日当天就买入，缺少确认。

```python
# sagent/strategy/entry.py
def confirm_entry(bars, signal_idx, params) -> bool:
    """入场确认：次日收盘 > key_low + buffer，且不破信号日低点"""
```

改动 `backtest_engine.py` 的 `simulate_trade()` 增加确认步骤。

---

## 回测关键数据（v3 规则，供下次对比用）

```
165 笔交易 | 胜率 40.6% | 均收 +2.66% | 组合 -9.09%
止损 99 笔 (60%) 均亏 -7.93% | 自然到期 66 笔 (40%) 均赚 +18.55%
半仓止盈触发 39 笔 (23.6%) 触发后均收 +27.31%

早期止损（1-7天）: 61 笔, 胜率 0%, 全部止损
  - 1天退出 13笔, 2天 14笔, 4天 18笔
  - 止损类型: 绝对止损10% 25笔, 关键低点 36笔
  - 入场到止损平均距离仅 7.9%

LLM 判断分布（v3）:
  买入: 79笔, 胜率44%, 均收+2.55%, 止损率59%
  观察: 86笔, 胜率37%, 均收+2.76%, 止损率60%

月度: 12月59% → 2月15% → 4月73%
```

---

## 当前模块依赖图（拆分前）

```
sagent/
  technical.py → models              ← 策略：信号检测 + LLM判断（混合体）
  signal.py    → market              ← 策略：K线描述结构
  llm.py       → models              ← 策略：LLM prompt
  real_llm.py  → llm                 ← 策略：LLM API
  scan.py      → config,kline,llm,notify,portfolio,real_llm,sector,technical
  backtest_engine.py → kline,models  ← 回测引擎（纯）
  backtest_portfolio.py → backtest_engine,kline,models ← 组合管理（纯）
  cache.py → models                  ← 数据层
  ...

scripts/run_backtest_period.py → backtest_engine,backtest_portfolio,cache,kline,
  models,real_llm,technical,llm,signal,portfolio,sector_cache
  (1155行, 76%是策略逻辑)
```

---

## 技术备忘

- **PowerShell 不支持 `&&`** — 用 `;` 或分步执行
- **`ctx_execute` 超时** — 长任务（>2min）用 `Start-Process` 后台 + 轮询文件
- **回测三步流程**: 回测 → 生成图 → 生成报表（见 AGENTS.md）
- **图表文件名**: `combined_{symbol}_{YYYYMMDD}.html`（日期无横线）
- **mootdx import 警告**: LSP 报错但运行时正常
- **回测基准速度**: 缓存新鲜时 100 支 ~10s，纯计算阶段 ~5s/3981 支

---

## Suggested Skills

- `/scan` 或 `prepare_scan` — 每日扫描信号
- `analyze_stock` — 个股 K 线分析
- `apply_decision` — 确认交易写入 portfolio
- `check_portfolio` — 查看持仓状态
