# Sagent Handoff — Session 7

**日期**: 2026-06-04 · **仓库**: `D:\suishi\sagent` · **分支**: `master`
**测试**: 104 passing (11 skipped for plotly) · **Python**: Anaconda `D:\ProgramData\anaconda3`
**Git**: 所有改动已提交并 push

---

## 本次会话摘要

### 1. 🔴 接入真实 LLM API — `sagent/real_llm.py` (新文件)
- 创建 `OpenAILLMClient`：支持智谱 GLM、DeepSeek、OpenAI 等任何 OpenAI 兼容 API
- 环境变量配置：`SAGENT_LLM_API_KEY` / `SAGENT_LLM_BASE_URL` / `SAGENT_LLM_MODEL`
- 双模型自动降级链：`_FallbackChain`，配置 `SAGENT_LLM_FALLBACK_*` 即可
- `scan.py` 自动检测：有 API key 用 LLM，无 key 用规则引擎
- 回测脚本 `--llm` 参数：`python scripts/run_backtest_period.py --llm`
- JSON 解析容错：支持纯 JSON、markdown 代码块、混合文字
- 新增 7 个测试用例

### 2. 🔴 行业归属优化 — SectorStore 缓存加速
- 回测脚本中 `get_stock_industry()` 从逐只 AKShare 查询改为 `SectorCache` 批量加载
- mootdx TCP `block()` 一次获取全市场行业-股票映射，缓存到 SQLite
- 修复循环导入：`sector_bars_cache.py` 改为从 `market.py` 直接导入 `DailyBar`

### 3. 🟡 信号质量优化 — 降低止损率
- `simulated_llm_judge` v2 规则引擎：
  - 新增 R 值过滤：R < 1.5 放弃（上行空间不足）
  - 回撤 >55% 放弃（趋势可能已破坏）
  - 放量确认阈值收紧：回撤 ≤40%（原 45%）才允许买入
  - 买入置信度从 0.65-0.70 提升到 0.70-0.75

### 4. 🟡 组合管理优化 — 周限放宽
- 每周新开仓上限从 2 笔放宽到 3 笔
- `config/default.json` 和 `portfolio.py` `confirm_buy` 默认值同步更新
- 测试用例同步更新

### 5. 🟡 缓存预热脚本 — `scripts/warmup_cache.py` (新文件)
- 支持三个维度的缓存预热：个股 K 线、行业映射、板块指数 K 线
- 灵活参数：`--all / --stocks / --sectors / --sector-bars`
- `--sample N` 控制预热股票数量

### 6. 🟢 PowerShell GBK 乱码 / LSP warnings
- 创建 `scripts/fix_console_encoding.py` 编码修复工具
- 回测脚本入口自动修复 Windows 终端编码（`PYTHONIOENCODING=utf-8`）
- `sector_bars_cache.py` 修复循环导入（LSP warnings 根因）

---

## 文件改动清单

| 文件 | 角色 | 改动类型 |
|------|------|---------|
| `sagent/real_llm.py` | 真实 LLM API 客户端 | **新增** |
| `scripts/warmup_cache.py` | 缓存预热脚本 | **新增** |
| `scripts/fix_console_encoding.py` | 编码修复工具 | **新增** |
| `sagent/scan.py` | +LLM 自动检测 + llm_status | 修改 |
| `sagent/technical.py` | 信号质量优化 v2 | 修改 |
| `sagent/portfolio.py` | 周限 2→3 | 修改 |
| `sagent/sector_bars_cache.py` | 循环导入修复 | 修改 |
| `sagent/sector.py` | 格式修复 | 修改 |
| `config/default.json` | 周限 2→3 | 修改 |
| `scripts/run_backtest_period.py` | +真实 LLM +SectorCache +编码修复 | 修改 |
| `scripts/generate_charts.py` | 格式修复 | 修改 |
| `tests/test_sagent_behaviors.py` | +7 个 LLM 测试 +周限测试更新 | 修改 |

---

## LLM API 配置说明

```bash
# 环境变量配置（任选其一）
set SAGENT_LLM_API_KEY=your_api_key
set SAGENT_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 智谱 GLM（默认）
set SAGENT_LLM_MODEL=glm-4-flash                                # 模型名（默认）

# 可选：配置 fallback 模型
set SAGENT_LLM_FALLBACK_API_KEY=your_fallback_key
set SAGENT_LLM_FALLBACK_MODEL=deepseek-chat
set SAGENT_LLM_FALLBACK_BASE_URL=https://api.deepseek.com/v1

# 使用真实 LLM 进行回测
python scripts/run_backtest_period.py --llm --engine --cache data/bars.db
```

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

## 待办事项（已全部完成）

~~1. 🔴 接入真实 LLM API~~ ✅
~~2. 🔴 行业归属优化~~ ✅
~~3. 🟡 信号质量优化~~ ✅
~~4. 🟡 组合管理优化~~ ✅
~~5. 🟡 缓存预热脚本~~ ✅
~~6. 🟢 PowerShell GBK 乱码~~ ✅

### 后续优化方向
- 安装 plotly 以启用图表测试
- 使用真实 LLM API 跑完整回测，对比规则引擎 vs LLM 精确率
- 根据回测结果进一步调整信号阈值
- 配置 Windows Task Scheduler 自动运行 `/scan`

---

## 已知陷阱

- **models.py re-export**: `from sagent.models import ...` 仍有效。新代码应直接 import 领域模块
- **SectorStore 是 Facade**: 内部委托给 SectorCache 和 SectorBarCache
- **防未来函数**: 回测 K 线通过 `daily_bars_up_to(symbol, end_date)` SQL 截断
- **PowerShell `&&` 不工作**: 用 `;` 或分步执行
- **临时文件规则**: 所有产出必须放 `output/`，见 AGENTS.md
- **plotly 未安装**: 图表相关测试需 `pip install plotly`，不影响核心功能
- **LLM 无 key 时**: 自动 fallback 到规则引擎，无需额外配置
