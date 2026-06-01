# Agent 指令

本仓库的 agent 配置、issue 流程和领域文档规则如下。所有面向用户的沟通、文档和 issue 内容默认使用中文。

## Git 工作流

- 所有更改先在本地实现并验证（测试通过），再提交到 GitHub。
- 每次提交前：`git pull origin master` → 本地改动 → 测试通过 → `git add` + `git commit` + `git push`。
- 保证本地和远程始终同步，避免 stash 或未推送的积压。
- 提交信息使用中文，格式：`feat: / fix: / docs: 描述`。

## Agent skills

### Issue tracker

Issues 和 PRD 统一发布到 GitHub Issues：`shandianxiao218/sagent`。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认的五个 triage 标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库采用 single-context 布局：优先读取根目录 `CONTEXT.md` 和 `docs/adr/`。详见 `docs/agents/domain.md`。
