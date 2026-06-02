# Sagent Handoff Document — 2026-06-02

**Repo**: `D:\suishi\sagent` · remote `shandianxiao218/sagent` · branch `master`
**Tests**: 73 passing · **Python**: Anaconda `D:\ProgramData\anaconda3`
**Git status**: clean (only pi-lens cache diffs, no uncommitted code changes)
**All commits pushed** to origin/master.

---

## What Changed This Session

### Stop-Loss Strategy Overhaul (core fix)
- **Old**: `stop_loss = max(entry×0.95, key_low)` — 5% hard cap, ignored key_low when it was >5% below entry
- **New**: `stop_loss = max(entry×0.92, key_low)` — 8% hard cap, uses key_low (structural support) when it's within 8%
- **Impact**: stop-loss rate dropped from 69.6% → 62%, win rate rose 30% → 44%, avg return +3.41% → +5.55%
- Files: `sagent/backtest_engine.py` (lines ~149, ~265), `tests/test_sagent_behaviors.py` (11 tests updated)

### New Filtering in `run_backtest_engine()`
- `min_sl_distance: float` param — reject signals where stop-loss < N% below entry
- `exclude_st: bool` param — filter ST stocks by name
- File: `sagent/backtest_engine.py` function `run_backtest_engine()`

### NAV Curve Serialization
- `backtest_engine_v2.json` now contains full 415-point nav_curve with date/cash/position_value/total_value/open_positions
- File: `scripts/run_backtest_period.py` (~line 950)

### K-Line Chart Improvements (from earlier in session)
- No-gap x-axis (integer indices + date labels)
- Candlestick styles: limit-up=red solid, bullish=red hollow, bearish=green solid
- Board-specific limit detection: main board 10%, ChiNext/STAR 20%, BSE 30%
- Crosshair (gray dotted spikelines) + hover shows date/OHLC/change%/volume
- File: `sagent/chart.py` — functions `_limit_up_pct()`, `_classify_bars()`, `plot_stock_kline()`

### V2 Backtest Results (1500 stocks, 50 signals)
| Metric | V1 (5% SL) | V2 (8% SL) |
|--------|-----------|-----------|
| Signals | 23 | 50 |
| Stop-loss rate | 69.6% | 62.0% |
| Avg return | +3.41% | **+5.55%** |
| Win rate | 30.4% | **44.0%** |
| Half-profit rate | 17.4% | **36.0%** |
| Profit/loss ratio | 3.85 | 3.53 |
| Best single trade | ~27% | **+75.01%** |
| Portfolio return | +5.64% | +3.61% |

---

## Architecture Quick Reference

### Module Map (`sagent/`)
| File | Role |
|------|------|
| `backtest_engine.py` | `simulate_trade()` daily stop/TP, `run_backtest_engine()` batch stats + filters |
| `backtest_portfolio.py` | `BacktestPortfolio` cash/weekly limits/NAV, `PortfolioStats`, `DailyNAV` |
| `chart.py` | Plotly charts: candlestick (3 styles), signal, structure, lifecycle, dashboard |
| `kline.py` | Swing lows/highs, key_low, pullback structure, trend-break ref |
| `models.py` | `DailyBar`, `Candidate`, `TradeLifecycle`, `BacktestStats`, `ChartAnnotation`, etc. |
| `technical.py` | MA/MACD/volume screening → `technical_candidates()` |
| `llm.py` | Prompt builder + rule-engine mock for backtesting |

### Scripts (`scripts/`)
| File | Purpose |
|------|---------|
| `run_backtest_period.py` | Main backtest runner, `--engine` flag, `--min-amount`, `--sample` |
| `generate_charts.py` | Generates 151 HTML charts from backtest JSON (auto-picks v2 if exists) |
| `analyze_stoploss.py` | Diagnostic: stop-loss distance distribution + filter simulation |
| `analyze_v2.py` | V2 backtest results analysis |
| `check_nav.py` | Verify nav_curve serialization |

### Data Files
| File | Content |
|------|---------|
| `backtest_engine_v1.json` | V1 results (5% SL, 23 signals) |
| `backtest_engine_v2.json` | V2 results (8% SL, 50 signals, full nav_curve) |
| `charts/*.html` | 151 chart files (gitignored) |

### Docs (`docs/`)
- `HANDOFF.md` — original handoff with issue dependency order
- `backtest_engine_v1_report.md` — V1 analysis
- `backtest_v3_report.md` — old method analysis

---

## Key Design Decisions

1. **Stop-loss formula**: `max(entry×0.92, key_low)` — key_low is the primary structural stop; 8% is the maximum acceptable risk per trade
2. **R-value denominator**: changed from `entry - key_low` to `entry - stop_loss_price` (the actual risk taken)
3. **Candlestick rendering**: 3 separate Candlestick traces (limit-up/bullish/bearish) with None-masked data per group, rather than custom color functions
4. **Limit-up detection**: compares day's close change vs board-specific limit percentage with 0.5% tolerance
5. **Stop-loss type renamed**: "硬性5%" → "硬性8%" in `TradeLifecycle.stop_loss_type`

---

## Remaining Work (Priority Order)

### High Priority
1. **Reduce stop-loss rate further (still 62%)** — consider:
   - ATR-based stop instead of fixed key_low
   - Require key_low distance ≥ 3% below entry (use `min_sl_distance=0.03`)
   - Trend quality filter (only buy when higher-lows sequence is clear)
2. **Replace rule-engine LLM mock with real LLM API** — expected precision ~83% vs current rule-engine ~40%
3. **Filter ST stocks properly** — current name-based filter works but industry-level ST detection would be more robust

### Medium Priority
4. **Fix industry lookup** — use 申万二级 classification instead of 东方财富
5. **Portfolio dashboard needs real nav_curve rendering** — currently `plot_portfolio_dashboard()` uses `DailyNAV` objects but the chart may need date formatting tweaks
6. **Signal quality scoring** — combine R-value, stop-loss distance, trend strength into a composite score for position sizing

### Low Priority
7. **LSP warnings** — `dict()` literal suggestions, plotly import resolution (cosmetic, non-blocking)
8. **`_classify_bars` type annotations** — LSP infers `list[None]`, could add `# type: ignore` or explicit `list[float | None]`
9. **Code quality** — many `dict()` calls flagged as "unnecessary", f-strings without placeholders in print statements

---

## Known Gotchas

- **PowerShell `&&` doesn't work in ctx_batch_execute** — use `; ` or separate commands
- **Python inline scripts with quotes** — PowerShell mangles nested quotes; write to .py file instead
- **GBK encoding** — Windows console can't print Unicode symbols (★✗→); use ASCII alternatives
- **plotly import** — LSP can't resolve it but it works at runtime via Anaconda
- **`generate_charts.py` picks v2 automatically** — checks for `backtest_engine_v2.json` first

---

## Suggested Skills

| Skill | Use Case |
|-------|----------|
| `context-mode` | Processing large backtest output, multi-file analysis |
| `diagnose` | Investigating remaining high stop-loss rate systematically |
| `pi-subagents` | Parallel development if tackling multiple items above |

### Recommended First Actions
1. Run `python -m pytest tests/ -v` to verify clean state
2. Pick from "Remaining Work" based on user priority
3. If working on stop-loss optimization, use `scripts/analyze_stoploss.py` as template for filter simulation
