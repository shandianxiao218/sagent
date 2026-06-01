"""扫描结果表格格式化。

把 prepare_scan 的 JSON 输出转成可读的表格格式。
支持：控制台 Markdown 表格、飞书富文本消息。
"""

from __future__ import annotations

from .models import Position, PositionSuggestion


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _price(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def format_sector_table(sectors: list[dict]) -> str:
    """板块验证结果表格。"""
    rows: list[list[str]] = []
    for s in sectors:
        level = s.get("level", "")
        needs = "需LLM" if s.get("needs_llm") else "已确定"
        rules = s.get("rules", {})
        hit = [k for k, v in rules.items() if v]
        rows.append([s.get("sector", ""), level, needs, ", ".join(hit) or "无"])

    header = ["板块", "主线级别", "状态", "命中规则"]
    widths = _col_widths(header, rows)
    return _markdown_table(header, rows, widths)


def format_candidate_table(candidates: list[dict]) -> str:
    """候选股表格。"""
    rows: list[list[str]] = []
    for c in candidates:
        m = c.get("metrics", {})
        rows.append([
            f"{c.get('symbol', '')} {c.get('name', '')}",
            c.get("sector", ""),
            _pct(m.get("rise_60d")),
            _pct(m.get("pullback_ratio")),
            "是" if m.get("breakout") else "否",
            _price(c.get("kline_key_low")),
        ])

    header = ["股票", "板块", "60日涨幅", "回调比例", "突破", "关键低点"]
    widths = _col_widths(header, rows)
    return _markdown_table(header, rows, widths)


def format_position_table(
    positions: list[Position],
    current_prices: dict[str, float],
    suggestions: list[PositionSuggestion],
) -> str:
    """持仓监控表格。"""
    if not positions:
        return "当前无持仓。"

    suggestion_map = {s.symbol: s for s in suggestions}
    rows: list[list[str]] = []
    for p in positions:
        price = current_prices.get(p.symbol, 0)
        if price <= 0 or p.buy_price <= 0:
            pnl_pct = "-"
            rr = "-"
        else:
            pnl_pct = _pct((price - p.buy_price) / p.buy_price)
            loss_to_key = p.buy_price - p.key_low
            if loss_to_key > 0:
                rr = f"{(price - p.buy_price) / loss_to_key:.1f}R"
            else:
                rr = "-"

        s = suggestion_map.get(p.symbol)
        action = s.action if s else "持有"
        reason = s.reason if s else ""

        rows.append([
            f"{p.symbol} {p.name}",
            _price(p.buy_price),
            _price(price),
            pnl_pct,
            rr,
            _price(p.key_low),
            f"{action} {reason}",
        ])

    header = ["股票", "买入价", "现价", "盈亏", "盈亏比", "关键低点", "建议"]
    widths = _col_widths(header, rows)
    return _markdown_table(header, rows, widths)


def format_scan_summary(scan_result: dict) -> str:
    """把完整的 scan result 格式化为可读的 Markdown 报告。"""
    lines: list[str] = []

    trade_date = scan_result.get("trade_date", "未知")
    model = scan_result.get("judgement_model", "未知")
    lines.append(f"## 扫描报告 — {trade_date}")
    lines.append(f"判断模型：{model}")
    lines.append("")

    # 板块
    sectors = scan_result.get("sectors", [])
    if sectors:
        lines.append("### 板块主线验证")
        lines.append(format_sector_table(sectors))
        lines.append("")

    # 候选股
    candidates = scan_result.get("candidates", [])
    if candidates:
        lines.append("### 候选股")
        lines.append(format_candidate_table(candidates))
        lines.append("")
        for c in candidates:
            desc = c.get("kline_description", "")
            if desc:
                lines.append(f"**{c.get('symbol', '')} {c.get('name', '')}** K线描述：")
                lines.append(f"> {desc}")
                lines.append("")
    else:
        lines.append("### 候选股")
        lines.append("今日无候选股。")
        lines.append("")

    # 持仓
    portfolio = scan_result.get("portfolio", {})
    positions_data = portfolio.get("positions", [])
    suggestions_data = portfolio.get("suggestions", [])
    if positions_data:
        from .models import Position, PositionSuggestion

        positions = [Position(**p) for p in positions_data]
        suggestions = [PositionSuggestion(**s) for s in suggestions_data]
        # 简化：无法从 scan result 取 current_prices，用 buy_price 占位
        current_prices = {p.symbol: p.buy_price for p in positions}
        lines.append("### 持仓监控")
        lines.append(format_position_table(positions, current_prices, suggestions))
        lines.append(f"可用资金：{_price(portfolio.get('cash', 0))}")
        lines.append(f"本周已开仓：{portfolio.get('weekly_open_count', 0)} 次")
        lines.append("")
    else:
        lines.append("### 持仓")
        lines.append(f"可用资金：{_price(portfolio.get('cash', 100000))}，无持仓。")
        lines.append("")

    # 股票池统计
    pool = scan_result.get("stock_pool", {})
    included = len(pool.get("included", []))
    excluded = len(pool.get("excluded", []))
    lines.append(f"### 股票池：{included} 只纳入，{excluded} 只剔除")

    # 降级事件
    fallback_events = scan_result.get("fallback_events", [])
    if fallback_events:
        lines.append("")
        lines.append("### 模型降级")
        for e in fallback_events:
            lines.append(f"- {e.get('original_model', '')} → {e.get('fallback_model', '')}：{e.get('reason', '')}")

    lines.append("")
    lines.append("---")
    lines.append("*风险提示：仅作研究和辅助分析，不构成投资建议。*")

    return "\n".join(lines)


def format_feishu_text(scan_result: dict) -> str:
    """飞书纯文本格式（表格用空格对齐）。"""
    lines: list[str] = []

    trade_date = scan_result.get("trade_date", "未知")
    model = scan_result.get("judgement_model", "未知")
    lines.append(f"sagent 扫描报告 {trade_date}")
    lines.append(f"判断模型：{model}")
    lines.append("")

    sectors = scan_result.get("sectors", [])
    for s in sectors:
        level = s.get("level", "")
        needs = "需LLM判断" if s.get("needs_llm") else "已确定"
        lines.append(f"[板块] {s.get('sector', '')} — {level} ({needs})")

    candidates = scan_result.get("candidates", [])
    if candidates:
        lines.append("")
        for c in candidates:
            m = c.get("metrics", {})
            lines.append(
                f"[候选] {c.get('symbol', '')} {c.get('name', '')} | "
                f"板块={c.get('sector', '')} | "
                f"60日涨幅={_pct(m.get('rise_60d'))} | "
                f"回调={_pct(m.get('pullback_ratio'))} | "
                f"突破={'是' if m.get('breakout') else '否'} | "
                f"关键低点={_price(c.get('kline_key_low'))}"
            )
    else:
        lines.append("")
        lines.append("[候选] 今日无候选股")

    portfolio = scan_result.get("portfolio", {})
    positions = portfolio.get("positions", [])
    if positions:
        lines.append("")
        for p in positions:
            lines.append(
                f"[持仓] {p.get('symbol', '')} {p.get('name', '')} | "
                f"买入={_price(p.get('buy_price'))} | "
                f"关键低点={_price(p.get('key_low'))}"
            )

    lines.append("")
    lines.append(f"可用资金：{_price(portfolio.get('cash', 100000))}")
    lines.append("风险提示：仅作研究和辅助分析，不构成投资建议。")

    return "\n".join(lines)


# ─── 内部工具函数 ───────────────────────────────────────────────


def _col_widths(header: list[str], rows: list[list[str]]) -> list[int]:
    """计算每列最大宽度。"""
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], _display_width(cell))
    return widths


def _display_width(text: str) -> int:
    """计算字符串显示宽度（CJK 字符算 2）。"""
    width = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f":
            width += 2
        else:
            width += 1
    return width


def _pad(text: str, width: int) -> str:
    """右填充到指定显示宽度。"""
    diff = width - _display_width(text)
    return text + " " * max(diff, 0)


def _markdown_table(header: list[str], rows: list[list[str]], widths: list[int]) -> str:
    """生成 Markdown 表格。"""
    lines: list[str] = []
    hdr = "| " + " | ".join(_pad(h, w) for h, w in zip(header, widths, strict=True)) + " |"
    sep = "| " + " | ".join("-" * (w + 1) for w in widths) + " |"
    lines.append(hdr)
    lines.append(sep)
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            w = widths[i] if i < len(widths) else 0
            cells.append(_pad(cell, w))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
