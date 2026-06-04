# Agent 指令

本仓库的 agent 配置、issue 流程和领域文档规则如下。所有面向用户的沟通、文档和 issue 内容默认使用中文。

## Git 工作流

- 所有更改先在本地实现并验证（测试通过），再提交到 GitHub。
- 每次提交前：`git pull origin master` → 本地改动 → 测试通过 → `git add` + `git commit` + `git push`。
- 保证本地和远程始终同步，避免 stash 或未推送的积压。
- 提交信息使用中文，格式：`feat: / fix: / docs: 描述`。

## Handoff 规则

- handoff 文档统一保存到 `docs/HANDOFF.md`（覆盖更新），**不要**保存到系统临时目录。
- 每次会话结束时如果有实质性进展，更新 `docs/HANDOFF.md`。
- handoff 内容应包含：本次改动摘要、架构决策、测试状态、待办事项。
- handoff 文档属于项目持久化资产，随 git 提交推送。

## Agent skills

### Issue tracker

Issues 和 PRD 统一发布到 GitHub Issues：`shandianxiao218/sagent`。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认的五个 triage 标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库采用 single-context 布局：优先读取根目录 `CONTEXT.md` 和 `docs/adr/`。详见 `docs/agents/domain.md`。

### Data sources

行业板块和个股行业归属依赖 [a-stock-data](https://github.com/simonlin1212/a-stock-data) V3.2：
- `skills/a-stock-data/SKILL.md` 内嵌全部 Python 代码，无需 pip 安装
- `data.py` 已集成 `industry_comparison()`（东财 push2）和 `concept_blocks()`（百度股市通）
- 板块数据是扫描分析的核心输入，必须正常工作

### Backtest pipeline

回测必须执行完整三步流程（回测→生成图→生成报表）：
1. **回测**：`python scripts/run_backtest_period.py --engine --cache data/bars.db --output <json>`
2. **生成图**：`python scripts/generate_charts.py --input <json> --cache data/bars.db`
3. **生成报表**：`python scripts/backtest_report.py --input <json>`（同时生成 Markdown + HTML）

所有回测数据使用 SQLite 缓存（`data/bars.db`），防未来函数。详见 `sagent/cache.py` 的 `daily_bars_up_to` / `bulk_closes_up_to`。

报表必须包含以下内容：
- **每个选中股票的选股理由**：MA250 位置、60日涨幅、回调比、60日高低点等信号指标
- **LLM 判断理由**：动作（买入/观察/放弃）、置信度、判断理由文本
- **K线形态描述**：`describe_stock()` 输出的形态描述
- **HTML 报表**：除 Markdown 外必须生成一份交互式 HTML，每笔交易可展开查看完整详情
- 末尾附带免责声明：仅作研究和辅助分析，不构成投资建议
