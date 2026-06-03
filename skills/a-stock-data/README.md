# a-stock-data 依赖说明

行业板块数据和个股行业归属使用 [a-stock-data](https://github.com/simonlin1212/a-stock-data) SKILL.md 中内嵌的函数。

## 已集成的函数

| 函数 | 用途 | 数据源 |
|------|------|--------|
| `industry_comparison()` | 全行业涨跌排名（~100 行业） | 东财 push2（零鉴权） |
| `baidu_concept_blocks()` | 个股行业/概念/地域归属 | 百度股市通（零鉴权） |

## 数据源优先级

来自 a-stock-data V3.2 的设计原则：
1. **mootdx/腾讯** — 不封 IP，优先使用
2. **东财 push2** — 行业板块等（零鉴权，低风险）
3. **百度股市通** — 概念板块（零鉴权，极低风险）
4. **东财 datacenter** — 龙虎榜/解禁等（需限流）

## 集成方式

`data.py` 的 `AStockDataMarketData.__init__()` 在未注入 `industry_comparison` 和 `concept_blocks` 时，
自动尝试从 a-stock-data SKILL.md 中提取的函数创建默认实现。
