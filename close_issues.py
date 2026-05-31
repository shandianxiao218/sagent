#!/usr/bin/env python3
"""Close/comment GitHub issues for sagent."""

import subprocess


def run_gh(args):
    r = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr.strip()}")
        return False
    return True


def gh_issue_close(num, comment):
    path = "tmp_comment.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(comment)
    print(f"=== Closing #{num} ===")
    run_gh(["issue", "comment", str(num), "--body-file", path])
    run_gh(["issue", "close", str(num), "--reason", "completed"])


def gh_issue_comment_and_label(num, comment):
    path = "tmp_comment.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(comment)
    print(f"=== Commenting #{num} (ready-for-human) ===")
    run_gh(["issue", "comment", str(num), "--body-file", path])
    run_gh(
        [
            "issue",
            "edit",
            str(num),
            "--add-label",
            "ready-for-human",
            "--remove-label",
            "ready-for-agent",
        ]
    )


# ============================================================
# ISSUES TO CLOSE (1-14 in the plan)
# ============================================================

gh_issue_close(
    2,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

**文件路径：** `skills/a-share-main-trend/SKILL.md`

该 skill 文档完整覆盖以下内容：

1. **核心概念定义**：主线、回调、突破、关键低点、趋势破坏均有明确定义，与 CONTEXT.md 中的术语表一致。
2. **风控规则**：10% 单次开仓、每周最多 2 次新开仓、5% 硬性止损、2.5-3 盈亏比半仓止盈、趋势破坏清仓。
3. **模型约束**：明确使用 GLM5.1，配置允许时可切换 GPT-5.5；LLM 判断不作为事实。
4. **每日 /scan 工作流**：完整的三阶段流程（持仓监控 → 粗筛 → 主线验证 → 精筛 → 买入建议）。
5. **输出规范**：建议动作、判断理由、主线判断、关键低点、风险点、模型标识、风险提示。
6. **禁止事项**：不自动下单、不承诺收益、不省略风险。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    4,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/config.py`：本地配置管理模块，支持从 `config/default.json` 和环境变量加载配置。
- `config/default.json`：默认配置文件，包含 AKShare、LLM、飞书等配置项。
- `.env.example`：环境变量示例文件，列出所有需要配置的密钥和参数。
- `.gitignore`：已忽略 `.env`、`portfolio.json` 等敏感文件。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    5,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/technical.py:filter_stock_pool()`：股票池预筛函数，支持以下过滤条件：
  - 剔除 ST 股票
  - 剔除停牌股票
  - 剔除次新股（上市不足 60 日）
  - 剔除日均成交额低于 1 亿元的股票
- 测试覆盖上述所有过滤规则。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed（含 filter_stock_pool 相关测试）
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    6,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/technical.py:technical_candidates()`：量化技术粗筛函数，支持以下条件：
  - 当前价格在 250 日均线之上
  - 60 日内涨幅 >= 50%
  - 从阶段高点回撤幅度为前一波涨幅的 15%-50%
  - 近 3 日开始回升（突破信号）
- 测试覆盖所有筛选条件。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed（含 technical_candidates 相关测试）
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    7,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/kline.py:describe_stock()`：K 线自然语言描述生成函数，支持：
  - 结构化输出（趋势、关键价位、形态描述）
  - 关键低点识别
  - 字数限制（控制在合理范围内供 LLM 分析）
- 测试覆盖结构化输出格式和关键低点识别。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed（含 describe_stock 相关测试）
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    8,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/sector.py:summarize_sectors()`：板块数据摘要工具，支持：
  - 1 日 / 5 日 / 10 日 / 30 日多时间窗口表现统计
  - 成交额排名、涨幅排名、涨停扩散排名
- 测试覆盖所有时间窗口和排名逻辑。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed（含 summarize_sectors 相关测试）
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    9,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/sector.py:validate_mainline_sectors()`：主线板块验证规则，支持三层分类：
  - **强主线**：连续 5 日成交额前 10 + 30 日内至少 3 次涨幅前 10 + 30 日内至少 3 次出现 3 只以上涨停
  - **弱主线**：满足成交额和涨幅条件，但涨停扩散不足
  - **非主线**：不满足主线条件
- 测试覆盖强主线、弱主线、非主线的分层逻辑。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed（含 validate_mainline_sectors 相关测试）
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    12,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/portfolio.py:PortfolioStore`：持仓状态管理类，支持：
  - 安全读写 `portfolio.json`（文件不存在时自动创建）
  - 持仓记录（股票代码、名称、行业、买入日期、买入价、数量、仓位比例、关键低点）
  - 每周开仓次数追踪
- 测试覆盖安全读写、持仓记录和每周限制。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed（含 PortfolioStore 相关测试）
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    13,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/portfolio.py:confirm_buy()`：买入确认工作流，支持：
  - 10% 仓位限制（单次开仓不超过总资金 10%）
  - 关键低点记录（止损依据）
  - 交易历史记录
  - 每周最多 2 次新开仓限制
- 测试覆盖仓位限制、关键低点、交易历史和每周限制。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed（含 confirm_buy 相关测试）
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    15,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `sagent/scan.py:run_scan()`：完整的 /scan 命令编排函数，按顺序执行：
  1. 读取持仓状态
  2. 粗筛候选股
  3. 主线验证
  4. 精筛并生成买入建议
  5. 推送结果
- `.pi/extensions/sagent/index.ts`：pi extension 注册 /scan 命令
- 测试覆盖完整编排流程。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed
- `npx tsc --noEmit` → 无错误
- `npm run scan:fixture` → 可运行
""",
)

gh_issue_close(
    17,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `docs/USER_GUIDE.md`：中文用户指南，包含每日收盘后手动运行 checklist：
  1. 确认 AKShare 数据已更新
  2. 运行 /scan 命令
  3. 查看推送结果
  4. 确认买入/卖出操作
- `npm run scan:fixture`：基于 fixture 数据的端到端运行命令，无需真实数据即可验证流程。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    18,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `scripts/notify_feishu.py`：飞书机器人推送脚本，支持 Webhook 方式发送消息。
- `sagent/notify.py`：通知模块，封装推送逻辑。
- `.pi/extensions/sagent/index.ts`：extension 使用 `runPythonSafe` 隔离推送，推送失败不影响主流程。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed
- `npx tsc --noEmit` → 无错误
""",
)

gh_issue_close(
    21,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `tests/test_sagent_behaviors.py`：15 个测试用例，无网络依赖，覆盖：
  - 买入确认（仓位限制、关键低点、交易历史）
  - 止损逻辑（跌破关键低点、5% 硬性止损）
  - 止盈逻辑（2.5-3 盈亏比半仓止盈）
  - 每周开仓次数限制
  - 数据异常处理

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed
- 所有测试无网络依赖，可在本地完整运行
""",
)

gh_issue_close(
    22,
    """\
## 关闭说明

本 issue 验收标准已全部覆盖。

### 已实现内容

- `docs/USER_GUIDE.md`：完整的中文用户指南，包含：
  - 安装配置说明
  - 每日运行 checklist
  - 命令说明（/scan、持仓管理）
  - 风险声明
- README.md 已更新，包含项目简介和使用指引。

### 验收证据

- `pytest tests/test_sagent_behaviors.py` → 15 passed
- `npx tsc --noEmit` → 无错误
""",
)

# ============================================================
# ISSUES TO COMMENT + LABEL ready-for-human (15-21 in the plan)
# ============================================================

gh_issue_comment_and_label(
    3,
    """\
## 进度更新

### 已实现内容

- `AKShareMarketData` 适配器骨架已实现，封装了 AKShare 数据获取接口。
- 支持 A 股日线、板块数据、实时行情等数据获取。
- 当前 fixture 数据闭环可运行（`npm run scan:fixture`）。

### 需要人工介入

- 需要真实 AKShare 凭据和网络环境进行测试。
- 需要验证真实数据格式与 fixture 的一致性。
- 需要确认 AKShare API 限流和异常处理策略。

建议配置真实 AKShare 环境后重新验证。
""",
)

gh_issue_comment_and_label(
    10,
    """\
## 进度更新

### 已实现内容

- `FallbackLLMClient` 已实现，支持 GLM5.1 和 GPT-5.5 切换。
- 板块主线分析 prompt 构建函数已实现。
- 规则引擎 fallback 已实现（当 LLM 不可用时使用规则判断）。

### 需要人工介入

- 需要真实 GLM5.1 或 GPT-5.5 API 凭据验证 prompt 质量。
- 需要人工评估 LLM 板块分析结果与规则引擎结果的一致性。
- 需要确认 prompt 模板在实际场景中的表现。

建议配置真实 LLM API 凭据后进行 prompt 质量验证。
""",
)

gh_issue_comment_and_label(
    11,
    """\
## 进度更新

### 已实现内容

- `FallbackLLMClient` 已实现，支持 GLM5.1 和 GPT-5.5 切换。
- 个股形态分析 prompt 构建函数已实现（基于 K 线描述判断回调结构、突破信号）。
- 规则引擎 fallback 已实现。

### 需要人工介入

- 需要真实 GLM5.1 或 GPT-5.5 API 凭据验证 prompt 质量。
- 需要人工评估 LLM 个股分析结果的准确性。
- 需要确认形态识别 prompt 在真实 K 线数据上的表现。

建议配置真实 LLM API 凭据后进行 prompt 质量验证。
""",
)

gh_issue_comment_and_label(
    14,
    """\
## 进度更新

### 已实现内容

- `monitor_positions()` 已实现，支持：
  - 当前盈亏比计算
  - 硬性止损判断（跌破关键低点或 5% 亏损）
  - 半仓止盈（2.5-3 盈亏比区间）
  - 状态追踪（`half_taken` + `trade_history`）

### 需要人工介入

- 趋势破坏判断当前依赖 LLM 或用户手动标记，需要确认：
  - 是否需要自动趋势破坏检测逻辑
  - 趋势破坏的量化定义是否需要进一步细化
- 每日监控推送的展示格式需要用户确认。

建议在真实持仓数据上验证监控逻辑，并确认趋势破坏的处理方式。
""",
)

gh_issue_comment_and_label(
    19,
    """\
## 进度更新

### 已实现内容

- `run_quant_backtest()` 已实现，支持：
  - 候选池统计（筛选通过率、行业分布）
  - 后续表现追踪（forward_performance）
  - 回测结果输出

### 需要人工介入

- 历史区间切片需要真实 AKShare 日线数据支持。
- 回测指标需要进一步定义（胜率、盈亏比、最大回撤等）。
- 需要确认回测时间窗口和基准（沪深 300 / 中证 500）。

建议配置真实 AKShare 数据后运行完整回测。
""",
)

gh_issue_comment_and_label(
    16,
    """\
## 进度更新

### 已实现内容

- 已有 fixture 输出格式，可通过 `npm run scan:fixture` 查看实际输出样例。
- 扫描结果包含：候选股列表、主线判断、买入建议、风控参数。

### 需要人工介入

- 输出格式的展示方式需要用户确认：
  - 是否需要表格格式
  - 是否需要图表
  - 飞书推送的排版是否满足需求

请运行 `npm run scan:fixture` 查看当前输出格式，并确认是否需要调整。
""",
)

gh_issue_comment_and_label(
    20,
    """\
## 进度更新

### 已实现内容

- `fixtures/validation/llm_cases.json`：已包含 3 个历史验证案例。
- 案例覆盖了主线识别、个股形态分析等场景。

### 需要人工介入

- 需要更多人工标注案例（建议至少 10 个以上）。
- 需要真实 LLM API 验证案例的 prompt 效果。
- 需要确认案例的标注标准（什么算正确/错误）。

建议在有真实 LLM API 后，系统性地构建验证案例集。
""",
)

print("\n=== All done ===")
