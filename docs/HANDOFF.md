# Sagent Handoff — Session 9

**日期**: 2026-06-05 · **仓库**: `D:\suishi\sagent` · **分支**: `master`
**HEAD**: `e73dcf4` · **测试**: 117 passing · **Python**: Anaconda 3.12
**Git**: 所有改动已提交并 push

---

## 本次会话完成内容

### 1. 策略模块拆分（Step 1-4）— 全部完成

- **Step 1** (`10a34f4`): `strategy/params.py` — 6 个 `@dataclass` 参数类
- **Step 2** (`da50e1e`): `strategy/signal.py` + `strategy/judge.py` — 拆分 technical.py
- **Step 3** (`6d3b03a`): `strategy/scanner.py` — 提取批量扫描和统计
- **Step 4** (`1216f0d`): `strategy/entry.py` — 入场确认机制

### 2. 入场确认回测对比 (`ba91a2d`)

- `confirm_drop=0.02` 效果负面：胜率 33.3% → 23.2%
- 17/69 笔被拒绝 (24.6%)，拉低胜率
- 原因：阈值太严格 + 确认失败的交易以 0 收益计入统计

### 3. 策略 S1 保存 (`e73dcf4`)

- `docs/strategies/S1-ma250-pullback-v3.md`
- 完整参数快照 + 回测表现 + 变体测试结果

---

## 当前 strategy 模块结构

```
sagent/strategy/
  __init__.py       # 统一导出
  params.py         # 6 个 @dataclass 参数类
  signal.py         # 信号检测 + 候选股筛选
  judge.py          # LLM 规则引擎 v3
  scanner.py        # 批量扫描 + 统计工具
  entry.py          # 入场确认
```

`technical.py` = re-export 兼容层。

---

## 下次会话重点

### 方向 A（推荐）：修复统计 + 放宽阈值
1. 确认失败 → 不计入统计（当前记为 0 收益交易）
2. `confirm_drop` 0.02 → 0.05
3. 重新回测

### 方向 B：止损距离筛选
- 止损空间 <5% 的信号直接放弃
- `--min-sl-distance 0.05`

### 方向 C：参数网格搜索
- absolute_stop × half_profit_r × max_holding 网格搜索

---

## 策略 S1 基线数据

```
69 笔 | 胜率 33.3% | 均收 +0.02% | 止损率 62.3%
止损均亏 -8.70% | 自然到期均赚 +14.44%
组合 28 笔 | 总收益 -1.43% | 胜率 17.9%
早期止损(<=7天) 27 笔，胜率 0%，均亏 -8.96%
```

---

## 技术备忘

- **dataclass 参数覆盖**: `SignalParams(min_rise_60d=0.8)`
- **回测命令**: `python scripts/run_backtest_period.py --engine --sample 1500 --cache data/bars.db [--entry-confirm]`
- **回测三步流程**: 回测 → 生成图 → 生成报表（见 AGENTS.md）
- **run_engine_backtest 仍有内联代码**，与 run_backtest 共享逻辑未完全提取
- **mootdx import 警告**: LSP 报错但运行时正常
