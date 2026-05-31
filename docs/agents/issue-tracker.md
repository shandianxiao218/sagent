# Issue tracker：GitHub

本仓库的 issues 和 PRD 存放在 GitHub Issues：`shandianxiao218/sagent`。

所有 issue 标题、正文、评论默认使用中文。

## 操作约定

- **创建 issue**：使用 `gh issue create --title "..." --body "..."`。多行正文使用 heredoc 或临时文件，避免中文编码问题。
- **读取 issue**：使用 `gh issue view <number> --comments`，必要时同时读取 labels。
- **列出 issue**：使用 `gh issue list --state open --json number,title,body,labels,comments`，并按 label/state 过滤。
- **评论 issue**：使用 `gh issue comment <number> --body "..."`。
- **添加/移除标签**：使用 `gh issue edit <number> --add-label "..."` / `--remove-label "..."`。
- **关闭 issue**：使用 `gh issue close <number> --comment "..."`。

在 Windows 环境下，如果 `gh` 命令参数出现中文乱码，优先使用 GitHub REST API 或 `gh api --input <json-file>`，并确保 JSON 文件为 UTF-8。

## 当 skill 说“发布到 issue tracker”

创建一个 GitHub issue。

## 当 skill 说“读取相关 ticket”

运行 `gh issue view <number> --comments`，并同时检查标签和依赖关系。
