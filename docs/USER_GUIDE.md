# sagent 用户指南

`sagent` 是基于 pi 的 A 股主线交易分析 agent。它只提供研究和辅助分析，不自动下单，不构成投资建议。任何交易决策都需要用户自行判断并承担风险。

## 安装

```bash
cd D:/suishi/sagent/repo
npm install
```

Python 侧核心逻辑只依赖标准库；测试需要 `pytest`。如果本机没有 pytest：

```bash
python -m pip install pytest
```

## 配置

复制 `.env.example` 为 `.env`，或配置系统环境变量：

- `SAGENT_MODEL_NAME`：默认 `GLM5.1`，可切换到 `GPT-5.5`。
- `SAGENT_FEISHU_WEBHOOK`：可选飞书自定义机器人 webhook。未配置时不会报错，只跳过推送。

默认配置位于 `config/default.json`：

- 单次开仓比例：总资金 10%。
- 每周最多新开仓 2 次。
- portfolio 路径：`portfolio.json`。
- 判断模型默认：`GLM5.1`。

敏感信息不要提交进 git。

## 每日收盘后流程

建议在收盘后、数据相对稳定后手动执行：

```bash
npm run scan:fixture
```

在 pi 中使用本仓库时，可通过 `/scan` 触发 project-local extension。当前本地 fixture 流程可验证完整编排；真实 AKShare 网络数据接入时，应保持同样输出结构。

每日 checklist：

1. 收盘后运行 `/scan` 或 `npm run scan:fixture`。
2. 先看已有持仓建议：是否触发关键低点止损、5% 止损、2.5–3R 半仓止盈、趋势破坏退出。
3. 再看新候选股：主线板块、买入理由、关键低点、无效条件、风险点。
4. 下一交易日只在用户自行确认后行动；系统不会自动下单。
5. 如确认买入，用 portfolio 命令记录持仓。

## portfolio 使用

查看或初始化：

```bash
npm run portfolio:check
python scripts/portfolio.py init --cash 100000
```

确认买入后写入本地状态：

```bash
python scripts/portfolio.py confirm-buy \
  --symbol 000001 \
  --name 样例科技 \
  --sector AI应用 \
  --buy-price 10 \
  --key-low 9.4 \
  --trade-date 2026-05-25 \
  --cash 100000
```

写入内容包括买入价、数量、10% 仓位金额、关键低点、止损价、每周开仓次数和交易历史。

## 输出格式

扫描结果包含：

- `portfolio_suggestions`：已有持仓处理建议。
- `candidates`：候选股、所属板块、建议动作、理由、关键低点、无效条件、风险点和技术指标。
- `excluded`：被过滤标的及原因。
- `feishu`：飞书推送状态。
- `warning`：风险声明。

## 测试与验证

```bash
npm test
npx tsc --noEmit
npm run notify:mock
```

测试不依赖真实网络和 LLM，使用 `fixtures/` 中的本地样例数据。

## 数据限制与风险

- AKShare、交易所、行情源可能延迟、缺失或字段变化。
- LLM 对主线、形态、关键低点和趋势破坏的判断可能错误。
- 模型版本、provider、prompt 变化会影响输出。
- 回测当前只覆盖量化粗筛和主线验证，不等同于完整策略收益回测。
- 本系统不会自动交易，也不保证任何收益。
