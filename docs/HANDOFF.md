# Sagent Handoff Document — 2026-06-02 (Session 3)

**Repo**: `D:\suishi\sagent` · remote `shandianxiao218/sagent` · branch `master`
**Tests**: 73 passing · **Python**: Anaconda `D:\ProgramData\anaconda3`
**Git status**: clean (only pi-lens cache diffs, no uncommitted code changes)
**All commits pushed** to origin/master.

---

## What Changed This Session

### 实时扫描管线接入真实行情（核心修复）

**问题根因**：项目有两条独立的数据管线，回测管线一直用 mootdx 真实数据，但实时扫描管线（`prepare_scan.py` + extension）从 init 那天起就只读 `fixtures/market/sample_market.json`（5 只虚构样例股票），从未更新。

**修复内容**：

1. **`scripts/prepare_scan.py`** — 完全重写：
   - 去掉 `--fixture` 参数和 `FixtureMarketData` 依赖
   - 改用 `AStockDataMarketData`（mootdx TCP + AKShare）
   - 运行时过滤：ST 名称过滤 → K 线长度 ≥ 260 → 20 日均成交额 ≥ 1 亿
   - 每只候选自动获取行业归属（AKShare `stock_individual_info_em`）
   - 全量扫描 5525 只 A 股，发现 3 个真实候选信号

2. **`scripts/analyze_stock.py`** — 去掉 `--fixture`/`--mock`，直接 mootdx 真实数据

3. **`.pi/extensions/sagent/index.ts`** — 3 处改动：
   - `prepare_scan` tool：去掉 `fixture` 参数，不传 `--fixture`
   - `analyze_stock` tool：去掉 `fixture` 参数和 `--mock` fallback
   - `/scan` command：去掉硬编码的 `--fixture fixtures/market/sample_market.json`

**验证结果**：
- 73 测试全部通过
- 真实扫描 5525 只 A 股 → 3 候选（002937、300561、603687）

---

## Architecture Quick Reference

### 两条数据管线（现已统一为真实数据）

| 管线 | 入口 | 数据源 | 用途 |
|------|------|--------|------|
| **回测** | `scripts/run_backtest_period.py` | mootdx + AKShare | 历史区间回测 |
| **实时扫描** | `scripts/prepare_scan.py` → extension | mootdx + AKShare | 每日扫描 |

### Module Map (`sagent/`)
| File | Role |
|------|------|
| `backtest_engine.py` | `simulate_trade()` daily stop/TP, `run_backtest_engine()` batch stats + filters |
| `backtest_portfolio.py` | `BacktestPortfolio` cash/weekly limits/NAV, `PortfolioStats`, `DailyNAV` |
| `chart.py` | Plotly charts: candlestick (3 styles), signal, structure, lifecycle, dashboard |
| `data.py` | `AStockDataMarketData` (mootdx+AKShare) + `FixtureMarketData` (测试用) |
| `kline.py` | Swing lows/highs, key_low, pullback structure, trend-break ref |
| `models.py` | `DailyBar`, `Candidate`, `TradeLifecycle`, `BacktestStats`, `ChartAnnotation`, etc. |
| `technical.py` | MA/MACD/volume screening → `technical_candidates()` |
| `llm.py` | Prompt builder + rule-engine mock for backtesting |
| `sector.py` | 板块汇总 + 主线验证（强主线/弱主线/非主线） |

### Scripts (`scripts/`)
| File | Purpose | 数据源 |
|------|---------|--------|
| `prepare_scan.py` | 量化粗筛，输出 JSON 供 pi agent 判断 | **真实行情** |
| `analyze_stock.py` | 单只股票 K 线描述 | **真实行情** |
| `run_backtest_period.py` | 主回测入口，`--engine` 模式 | **真实行情** |
| `generate_charts.py` | 151 个 HTML 图表（自动选 v2） | 本地 JSON |
| `market_scan.py` | 旧版入口，仅 mock/fixture | ⚠️ 待清理 |

### Data Files
| File | Content |
|------|---------|
| `backtest_engine_v1.json` | V1 results (5% SL, 23 signals) |
| `backtest_engine_v2.json` | V2 results (8% SL, 50 signals, full nav_curve) |
| `charts/*.html` | 151 chart files (gitignored) |
| `fixtures/market/sample_market.json` | ⚠️ 旧 fixture，extension 已不再使用 |

---

## Key Design Decisions

1. **实时扫描不做预过滤** — AKShare `stock_info_a_code_name()` 只返回 code/name，缺少 avg_amount_20d/is_st/listing_days，所以改为获取 K 线后运行时过滤（ST → 成交额 → K线长度），和回测脚本 `run_backtest_period.py` 同一模式
2. **Stop-loss formula**: `max(entry×0.90, key_low×0.97)` — absolute stop at 10%; structural stop is key_low buffered by 3% below; take the higher (tighter) of the two
3. **R-value denominator**: `entry - stop_loss_price` (the actual risk taken, based on new stop-loss formula)
4. **行业归属**：实时扫描用 AKShare `stock_individual_info_em` 逐只查询（较慢但可用），后续应改为申万二级分类缓存

---

## Remaining Work (Priority Order)

### High Priority
1. **行业归属优化** — 当前逐只调用 AKShare 查行业太慢，应：
   - 用申万二级分类一次获取全市场行业映射
   - 缓存到本地 JSON，每日更新一次
2. **~~Reduce stop-loss rate further~~** → 已完成：止损策略从 `max(entry×0.92, key_low)` 改为 `max(entry×0.90, key_low×0.97)`，绝对止损放宽到10%，key_low 下方留3%缓冲
3. **Replace rule-engine LLM mock with real LLM API** — expected precision ~83% vs current rule-engine ~40%

### Medium Priority
4. **清理旧代码** — `market_scan.py` 仍用 mock/fixture，可删除或标记废弃
5. **`fixtures/market/sample_market.json`** — extension 不再使用，但测试仍依赖，保留
6. **Signal quality scoring** — combine R-value, stop-loss distance, trend strength into a composite score
7. **Portfolio dashboard** — real nav_curve rendering date formatting tweaks

### Low Priority
8. **LSP warnings** — `dict()` literal suggestions, plotly import resolution (cosmetic)
9. **GBK encoding** — Windows PowerShell 重定向输出时编码问题，prepare_scan stdout 中的中文在 PowerShell 管道中乱码

---

## Known Gotchas

- **PowerShell `&&` doesn't work** — use `; ` or separate commands
- **Python inline scripts with quotes** — PowerShell mangles nested quotes; write to .py file instead
- **GBK encoding** — Windows console can't print Unicode symbols (★✗→); use ASCII alternatives
- **PowerShell 重定向编码** — `python script.py > file.json` 会写入 UTF-16LE BOM，导致 JSON 不可读。用 Python subprocess + `encoding="gbk"` 或直接在脚本内写文件
- **plotly import** — LSP can't resolve it but it works at runtime via Anaconda
- **`generate_charts.py` picks v2 automatically** — checks for `backtest_engine_v2.json` first
- **AKShare 分页进度条** — `stock_info_a_code_name()` 会输出 tqdm 进度条到 stderr，不影响 stdout JSON

---

## Suggested Skills

| Skill | Use Case |
|-------|----------|
| `context-mode` | Processing large backtest output, multi-file analysis |
| `diagnose` | Investigating remaining high stop-loss rate systematically |
| `pi-subagents` | Parallel development if tackling multiple items above |

### Recommended First Actions
1. Run `python -m pytest tests/ -v` to verify clean state
2. 优先解决行业归属优化（申万二级缓存），实时扫描才能正确做主线验证
3. If working on stop-loss optimization, use `scripts/analyze_stoploss.py` as template for filter simulation
