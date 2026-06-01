# 回测引擎集成实施报告

## 修改文件

- `scripts/run_backtest_period.py`

## 变更内容

### 1. 新增导入

```python
from sagent.backtest_engine import simulate_trade, run_backtest_engine
from sagent.backtest_portfolio import run_portfolio_backtest
```

### 2. 新增 `run_engine_backtest()` 函数

使用逐日止损/止盈引擎 + 组合管理的新回测流程。

**6 步流程：**

| 步骤 | 内容 |
|------|------|
| [1/6] | 获取A股列表、采样 |
| [2/6] | 获取K线 + 检测信号（**缓存 bars 到 bars_cache**） |
| [3/6] | 对每个信号调用 `simulate_trade()` 获取 `TradeLifecycle` |
| [4/6] | 调用 `run_portfolio_backtest()` 模拟组合管理 |
| [5/6] | 汇总统计（引擎统计、按月分组、旧方式 vs 新方式对比） |
| [6/6] | 组装输出 |

**关键改动 — bars 缓存：**

```python
bars_cache: dict[str, list[DailyBar]] = {}
# 在循环中缓存
bars_cache[symbol] = bars
```

信号检测和引擎回测共享同一份 bars 数据。

**关键改动 — signal_idx 追踪：**

```python
all_signals.append({
    "symbol": symbol,
    "name": name,
    "signal_date": sig_date,
    "signal_idx": check_idx,  # 新增：引擎需要此索引
    "metrics": metrics,
})
```

### 3. 输出结构

```python
{
    "meta": {
        "scope": "引擎回测（逐日止损/止盈 + 组合管理）",
        "parameters": {
            "initial_cash": 100000,
            "max_holding": 20,
            ...
        }
    },
    "engine_summary": {
        "total_trades": N,
        "stop_loss_count": N,
        "take_profit_count": N,
        "natural_exit_count": N,
        "stop_loss_rate": 0.XX,
        "avg_return_all": X.XX,
        "avg_return_stop_loss": X.XX,
        "avg_return_natural": X.XX,
        "win_rate": 0.XX,
        "avg_holding_days": X.X,
        "half_profit_triggered_count": N,
        "buy_and_hold_avg_return": X.XX,
        "strategy_vs_buyhold_diff": X.XX,
    },
    "monthly_engine": {
        "2026-01": {"total": N, "avg_return": X.XX, "win_rate": X.XX, ...},
        ...
    },
    "old_vs_new": {
        "old_buyhold_avg": X.XX,
        "new_engine_avg": X.XX,
        "diff": X.XX,
    },
    "portfolio": {
        "initial_cash": 100000,
        "final_value": XXXXX,
        "total_return": X.XX,
        "max_drawdown": X.XX,
        "sharpe_ratio": X.XX,
        "total_trades": N,
        "win_rate": X.XX,
        "profit_loss_ratio": X.XX,
        "nav_curve_count": N,
        ...
    },
    "trades": [
        {
            "symbol": "000001",
            "entry_price": X.XX,
            "exit_reason": "止损/半仓止盈后趋势破坏/持有到期",
            "total_return": X.XX,
            "buy_and_hold_return": X.XX,
            ...
        },
        ...
    ],
}
```

### 4. argparse 更新

```python
parser.add_argument("--engine", action="store_true",
                    help="使用逐日止损/止盈引擎 + 组合管理回测")
parser.add_argument("--initial-cash", type=float, default=100000,
                    help="组合管理初始资金（仅 --engine 模式）")
```

- 不加 `--engine`：使用原有 `run_backtest()`（买入持有20天），输出 `backtest_oct25_jun26.json`
- 加 `--engine`：使用 `run_engine_backtest()`（逐日止损止盈+组合管理），输出 `backtest_engine_v1.json`

### 5. 不修改的部分

- `run_backtest()` 函数完全不变
- `fetch_bars()`, `check_signal()`, `forward_returns()` 等不变
- 测试文件不变

## 使用方法

```bash
# 旧方式（买入持有20天）
python scripts/run_backtest_period.py --sample 500

# 新方式（逐日止损/止盈 + 组合管理）
python scripts/run_backtest_period.py --engine --sample 500

# 新方式 + 自定义参数
python scripts/run_backtest_period.py --engine --sample 500 --initial-cash 200000 --output result.json
```

## 验证结果

- ✅ 语法检查通过
- ✅ 73 个现有测试全部通过
- ✅ `run_engine_backtest` 可正常导入
- ✅ `run_backtest()` 函数未受影响

## 风险

- `run_engine_backtest()` 中未包含行业查询（L6）和 LLM 模拟判断，因为引擎模式的重点是验证止损/止盈效果。如需可后续加入。
- `bars_cache` 会将所有获取到的 bars 保存在内存中，对于 1500 只 × 370 日数据量约 55 万条 DailyBar，内存占用可控。
