# sagent

`sagent` 是一个基于 pi 的 A 股主线交易分析 agent。它只做辅助分析，不自动下单，不构成投资建议。

## 当前阶段

当前仓库已包含可本地重复运行的 fixture 闭环：

- `.pi/extensions/sagent/index.ts`：pi project-local extension，注册 `/scan` 命令和 custom tools。
- `sagent/`：配置、fixture 数据适配、股票池过滤、量化粗筛、板块验证、K 线描述、LLM 规则判断、portfolio、扫描编排、回测和验证案例核心逻辑。
- `scripts/`：命令行入口。
- `tests/`：无网络 TDD 测试。
- `skills/a-share-main-trend/SKILL.md`：A 股主线交易策略 skill。
- `config/default.json`：默认配置，判断模型默认 GLM5.1，可配置切换 GPT-5.5。
- `docs/USER_GUIDE.md`：中文用户指南。

## 快速验证

```bash
npm run scan:mock
npm run portfolio:check
npm run analyze:mock
npm run notify:mock
npm run scan:fixture
npm test
```

在 pi 中使用本仓库时，project-local extension 位于 `.pi/extensions/sagent/index.ts`，可通过 `/reload` 重新加载。

## pi 命令

- `/scan`：执行一次每日收盘后扫描流程，串联持仓检查、市场扫描和飞书推送。配置 `SAGENT_FEISHU_WEBHOOK` 后自动推送飞书；未配置时安全跳过。

## 自定义工具

extension 注册以下工具：

- `market_scan`：市场扫描入口，可运行 mock/fixture 流程。
- `check_portfolio`：读取/初始化本地 `portfolio.json` 状态。
- `analyze_stock`：生成单只股票的 K 线自然语言描述。
- `send_feishu_notification`：发送飞书机器人通知；未配置 `SAGENT_FEISHU_WEBHOOK` 时返回 skipped。

## 飞书推送配置

1. 复制 `.env.example` 为 `.env`（或在系统环境变量中配置）。
2. 设置 `SAGENT_FEISHU_WEBHOOK` 为飞书自定义机器人 webhook。
3. 运行 `npm run notify:mock` 可验证 dry-run 消息结构；在 pi 中执行 `/scan` 会在扫描后尝试推送。

## 用户指南

详见 `docs/USER_GUIDE.md`，包含安装、配置、每日使用流程、portfolio 操作、数据限制和风险声明。

## 风险声明

本项目只提供研究和辅助分析。AKShare 数据、LLM 判断、模型版本变化、网络状态都可能导致错误或延迟。任何交易决策都需要用户自行判断并承担风险。
