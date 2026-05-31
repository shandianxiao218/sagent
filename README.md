# sagent

`sagent` 是一个基于 pi 的 A 股主线交易分析 agent。它只做辅助分析，不自动下单，不构成投资建议。

## 当前阶段

当前仓库先搭建项目骨架：

- `.pi/extensions/sagent/index.ts`：pi project-local extension，注册 `/scan` 命令和基础 custom tools。
- `scripts/`：Python 数据与状态脚本，占位实现先返回 mock 数据。
- `skills/a-share-main-trend/SKILL.md`：A 股主线交易策略 skill。
- `config/default.json`：默认配置，判断模型默认 GLM5.1，可配置切换 GPT-5.5。
- `docs/agents/`：agent 工作流配置。

## 快速验证

```bash
npm run scan:mock
npm run portfolio:check
npm run analyze:mock
```

在 pi 中使用本仓库时，project-local extension 位于 `.pi/extensions/sagent/index.ts`，可通过 `/reload` 重新加载。

## pi 命令

- `/scan`：执行一次每日收盘后扫描流程。目前是骨架命令，会调用 mock 市场扫描脚本并提示后续 issue。

## 自定义工具

extension 注册以下工具：

- `market_scan`：市场扫描入口，目前返回 mock 候选股。
- `check_portfolio`：读取/初始化本地 `portfolio.json` 状态。
- `analyze_stock`：生成单只股票的 mock K 线描述。

## 风险声明

本项目只提供研究和辅助分析。AKShare 数据、LLM 判断、模型版本变化、网络状态都可能导致错误或延迟。任何交易决策都需要用户自行判断并承担风险。
