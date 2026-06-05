#!/usr/bin/env python3
"""从回测 JSON 生成 Markdown + HTML 报表。

输出内容包括：
  - 回测参数与概况
  - 引擎逐笔统计
  - 组合管理统计
  - 按月分析
  - 退出方式分布
  - 每笔交易的选股理由 + LLM 判断理由（HTML 展开详情）
  - 策略优化建议

用法：
  python scripts/backtest_report.py --input backtest_6m_full.json
"""

from __future__ import annotations

import html as html_mod
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fp(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:+.2%}"


def fn(v: float | None, fmt: str = ".2f") -> str:
    if v is None:
        return "N/A"
    return f"{v:{fmt}}"


def esc(s: str) -> str:
    return html_mod.escape(str(s))


# ═══════════════════════════════════════════════════════════
# Markdown 报表
# ═══════════════════════════════════════════════════════════


def generate_markdown(data: dict) -> str:
    meta = data["meta"]
    engine = data["engine_summary"]
    monthly = data.get("monthly_engine", {})
    portfolio = data.get("portfolio", {})
    old_vs_new = data.get("old_vs_new", {})
    trades = data.get("trades", [])
    p = meta["parameters"]

    lines: list[str] = []

    lines.append("# 回测报告\n")
    lines.append(f"> {meta.get('scope', '')}")
    lines.append(f"> {meta.get('disclaimer', '')}\n")

    # 1. 回测参数
    lines.append("## 1. 回测参数\n")
    lines.append("| 参数 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 回测区间 | {p['start_date']} ~ {p['end_date']} |")
    lines.append(f"| 扫描股票 | {p['total_scanned']} 只 |")
    lines.append(f"| 初始资金 | {p.get('initial_cash', 0):,.0f} |")
    lines.append(f"| 最大持有 | {p.get('max_holding', 0)} 天 |")
    lines.append(f"| K线不足 | {p.get('short_bars', 0)} |")
    lines.append(f"| 成交额不足 | {p.get('low_amount_count', 0)} |\n")

    # 2. 引擎逐笔统计
    lines.append("## 2. 引擎逐笔统计\n")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 总交易 | {engine['total_trades']} 笔 |")
    lines.append(f"| 平均收益 | {fp(engine['avg_return_all'])} |")
    lines.append(f"| 胜率 | {engine['win_rate']:.1%} |")
    lines.append(f"| 平均持仓 | {fn(engine['avg_holding_days'], '.1f')} 天 |\n")

    lines.append("### 退出方式\n")
    lines.append("| 方式 | 笔数 | 占比 | 均收益 |")
    lines.append("|------|------|------|--------|")
    for label, key in [
        ("止损", "stop_loss"),
        ("半仓止盈后趋势破坏", "take_profit"),
        ("持有到期", "natural_exit"),
    ]:
        cnt = engine[f"{key}_count"]
        rate = engine[f"{key}_rate"]
        avg = engine.get(f"avg_return_{key}")
        lines.append(f"| {label} | {cnt} | {rate:.1%} | {fp(avg)} |")
    lines.append("")

    # 3. 策略 vs 买入持有
    lines.append("## 3. 策略 vs 买入持有\n")
    lines.append("| 策略 | 平均收益 |")
    lines.append("|------|---------|")
    lines.append(f"| 买入持有 20 天 | {fp(old_vs_new.get('old_buyhold_avg'))} |")
    lines.append(f"| 逐日止损止盈 | {fp(old_vs_new.get('new_engine_avg'))} |")
    lines.append(f"| 差值 | {fp(old_vs_new.get('diff'))} |\n")

    # 4. 组合管理
    if portfolio:
        lines.append("## 4. 组合管理\n")
        lines.append("| 指标 | 值 |")
        lines.append("|------|-----|")
        for label, key in [
            ("期末净值", ("final_value", ",.0f")),
            ("总收益", ("total_return", "%")),
            ("最大回撤", ("max_drawdown", "%")),
            ("夏普比率", ("sharpe_ratio", "f")),
            ("总交易", ("total_trades", "d")),
            ("胜/负", None),
            ("胜率", ("win_rate", "%")),
            ("盈亏比", ("profit_loss_ratio", "f")),
        ]:
            if key is None:
                lines.append(
                    f"| 胜/负 | {portfolio.get('winning_trades', 0)}/{portfolio.get('losing_trades', 0)} |"
                )
            else:
                k, fmt = key
                v = portfolio.get(k, 0)
                if fmt == "%":
                    lines.append(f"| {label} | {fp(v)} |")
                elif fmt == "d":
                    lines.append(f"| {label} | {v} 笔 |")
                else:
                    lines.append(f"| {label} | {v:{fmt}} |")
        lines.append("")

    # 5. 按月分析
    if monthly:
        lines.append("## 5. 按月分析\n")
        lines.append("| 月份 | 交易 | 均收益 | 胜率 | 止损 | 均持仓 |")
        lines.append("|------|------|--------|------|------|--------|")
        for month in sorted(monthly):
            m = monthly[month]
            wr = f"{m['win_rate']:.1%}" if m.get("win_rate") is not None else "N/A"
            hd = (
                f"{m['avg_holding_days']:.1f}d"
                if m.get("avg_holding_days") is not None
                else "N/A"
            )
            lines.append(
                f"| {month} | {m['total']} | {fp(m.get('avg_return'))} | {wr} | {m['stop_loss_count']} | {hd} |"
            )
        lines.append("")

    # 6. 关键交易
    if trades:
        sorted_t = sorted(trades, key=lambda t: t["total_return"], reverse=True)
        lines.append("## 6. 关键交易\n")
        lines.append("### 最佳交易 Top 10\n")
        _trade_table(lines, sorted_t[:10])
        lines.append("### 最差交易 Top 10\n")
        _trade_table(lines, sorted_t[-10:])

    # 7. 策略优化建议
    lines.append("## 7. 策略优化建议\n")
    if engine["stop_loss_rate"] > 0.5:
        lines.append(
            f"- ⚠️ 止损率 {engine['stop_loss_rate']:.0%} 过高，信号质量需要提升"
        )
    if engine["win_rate"] < 0.4:
        lines.append(f"- ⚠️ 胜率 {engine['win_rate']:.0%} 偏低，考虑更严格的入场条件")
    if portfolio and portfolio.get("sharpe_ratio", 0) < 0:
        lines.append("- ⚠️ 夏普比率为负，策略未跑赢无风险收益")
    if engine["avg_return_all"] and engine["avg_return_all"] > 0:
        lines.append(
            f"- ✅ 逐笔平均收益 {engine['avg_return_all']:+.2%} 为正，信号方向正确"
        )
    if monthly:
        best = max(monthly.items(), key=lambda x: x[1].get("avg_return", -999) or -999)
        worst = min(monthly.items(), key=lambda x: x[1].get("avg_return", 999) or 999)
        lines.append(f"- 📊 最佳月份 {best[0]} ({fp(best[1].get('avg_return'))})")
        lines.append(f"- 📊 最差月份 {worst[0]} ({fp(worst[1].get('avg_return'))})")
    lines.append("\n---\n*仅作研究和辅助分析，不构成投资建议。*\n")

    return "\n".join(lines)


def _trade_table(lines: list[str], trades: list[dict]) -> None:
    lines.append("| 股票 | 名称 | 信号日 | 收益 | 退出 | 持仓 | LLM判断 | LLM理由 |")
    lines.append("|------|------|--------|------|------|------|---------|---------|")
    for t in trades:
        name = esc(t.get("name", ""))
        llm_action = esc(t.get("llm_action", ""))
        llm_reason = esc(t.get("llm_reason", ""))
        lines.append(
            f"| {t['symbol']} | {name} | {t['signal_date']} "
            f"| {t['total_return']:+.2%} | {t.get('exit_reason', '')} "
            f"| {t.get('holding_days', '')}d | {llm_action} | {llm_reason} |"
        )
    lines.append("")


# ═══════════════════════════════════════════════════════════
# HTML 报表（包含每只股票的选股理由 + LLM 判断）
# ═══════════════════════════════════════════════════════════


def generate_html(data: dict) -> str:
    meta = data["meta"]
    engine = data["engine_summary"]
    monthly = data.get("monthly_engine", {})
    portfolio = data.get("portfolio", {})
    trades = data.get("trades", [])
    p = meta["parameters"]

    parts: list[str] = []

    # ── <head> ──
    parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>回测报告</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; color: #333; background: #fafafa; }
h1 { color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 8px; }
h2 { color: #16213e; margin-top: 32px; border-left: 4px solid #e94560; padding-left: 12px; }
h3 { color: #0f3460; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; font-size: 14px; }
th { background: #1a1a2e; color: white; font-weight: 600; }
tr:nth-child(even) { background: #f8f8f8; }
tr:hover { background: #e8f4fd; }
.positive { color: #e74c3c; font-weight: bold; }
.negative { color: #27ae60; font-weight: bold; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.tag-buy { background: #ffe0e0; color: #c0392b; }
.tag-sell { background: #d4edda; color: #155724; }
.tag-hold { background: #fff3cd; color: #856404; }
.tag-abandon { background: #d6d8db; color: #383d41; }
.metric-card { display: inline-block; background: white; border-radius: 8px; padding: 16px 24px; margin: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); text-align: center; min-width: 140px; }
.metric-card .value { font-size: 28px; font-weight: 700; }
.metric-card .label { font-size: 13px; color: #888; margin-top: 4px; }
.details-row { display: none; }
.details-row.show { display: table-row; background: #f0f7ff !important; }
.details-content { padding: 12px; font-size: 13px; line-height: 1.8; }
.details-content .section-title { font-weight: 700; color: #0f3460; margin-top: 8px; }
.toggle-btn { background: #1a1a2e; color: white; border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
.toggle-btn:hover { background: #e94560; }
.disclaimer { margin-top: 40px; padding: 12px; background: #fff3cd; border-radius: 4px; font-size: 13px; color: #856404; }
</style>
</head>
<body>
""")

    # ── 标题 ──
    scope = esc(meta.get("scope", ""))
    parts.append("<h1>回测报告</h1>")
    parts.append(f"<p><strong>{scope}</strong></p>")
    parts.append(
        f"<p style='color:#888;font-size:13px'>{esc(meta.get('disclaimer', ''))}</p>"
    )

    # ── 1. 核心指标卡片 ──
    parts.append("<h2>1. 核心指标</h2>")
    parts.append("<div style='margin: 16px 0'>")

    def card(label, value, color=""):
        c = f" style='color:{color}'" if color else ""
        parts.append(
            f"<div class='metric-card'><div class='value'{c}>{value}</div><div class='label'>{label}</div></div>"
        )

    avg_r = engine.get("avg_return_all", 0) or 0
    wr = engine.get("win_rate", 0) or 0
    card("总交易", f"{engine['total_trades']} 笔")
    card("平均收益", fp(avg_r), "#c0392b" if avg_r > 0 else "#27ae60")
    card("胜率", f"{wr:.1%}", "#c0392b" if wr > 0.4 else "#e67e22")
    card("平均持仓", f"{fn(engine.get('avg_holding_days'), '.1f')} 天")
    if portfolio:
        card(
            "组合收益",
            fp(portfolio.get("total_return")),
            "#c0392b" if (portfolio.get("total_return") or 0) > 0 else "#27ae60",
        )
        card("最大回撤", fp(portfolio.get("max_drawdown")), "#27ae60")
    parts.append("</div>")

    # ── 2. 回测参数 ──
    parts.append("<h2>2. 回测参数</h2>")
    parts.append("<table><tr><th>参数</th><th>值</th></tr>")
    for label, val in [
        ("回测区间", f"{p['start_date']} ~ {p['end_date']}"),
        ("扫描股票", f"{p['total_scanned']} 只"),
        ("初始资金", f"{p.get('initial_cash', 0):,.0f}"),
        ("最大持有", f"{p.get('max_holding', 0)} 天"),
    ]:
        parts.append(f"<tr><td>{label}</td><td>{val}</td></tr>")
    parts.append("</table>")

    # ── 3. 退出方式 ──
    parts.append("<h2>3. 退出方式分布</h2>")
    parts.append(
        "<table><tr><th>方式</th><th>笔数</th><th>占比</th><th>均收益</th></tr>"
    )
    for label, key in [
        ("止损", "stop_loss"),
        ("半仓止盈后趋势破坏", "take_profit"),
        ("持有到期", "natural_exit"),
    ]:
        cnt = engine[f"{key}_count"]
        rate = engine[f"{key}_rate"]
        avg = engine.get(f"avg_return_{key}")
        color = (
            " class='negative'"
            if avg and avg < 0
            else (" class='positive'" if avg and avg > 0 else "")
        )
        parts.append(
            f"<tr><td>{label}</td><td>{cnt}</td><td>{rate:.1%}</td><td{color}>{fp(avg)}</td></tr>"
        )
    parts.append("</table>")

    # ── 4. 按月分析 ──
    if monthly:
        parts.append("<h2>4. 按月分析</h2>")
        parts.append(
            "<table><tr><th>月份</th><th>交易</th><th>均收益</th><th>胜率</th><th>止损</th><th>均持仓</th></tr>"
        )
        for month in sorted(monthly):
            m = monthly[month]
            avg_v = m.get("avg_return") or 0
            c = (
                " class='positive'"
                if avg_v > 0
                else (" class='negative'" if avg_v < 0 else "")
            )
            wr = f"{m['win_rate']:.1%}" if m.get("win_rate") is not None else "N/A"
            hd = (
                f"{m['avg_holding_days']:.1f}d"
                if m.get("avg_holding_days") is not None
                else "N/A"
            )
            parts.append(
                f"<tr><td>{month}</td><td>{m['total']}</td><td{c}>{fp(m.get('avg_return'))}</td><td>{wr}</td><td>{m['stop_loss_count']}</td><td>{hd}</td></tr>"
            )
        parts.append("</table>")

    # ── 5. 全部交易明细（含选股理由 + LLM 判断）──
    if trades:
        sorted_t = sorted(trades, key=lambda t: t["total_return"], reverse=True)
        parts.append("<h2>5. 全部交易明细</h2>")
        parts.append(
            "<p style='color:#888;font-size:13px'>点击「详情」展开选股理由、K线描述、LLM 判断</p>"
        )
        parts.append("<table><thead><tr>")
        parts.append(
            "<th>#</th><th>代码</th><th>名称</th><th>信号日</th><th>收益</th><th>退出</th><th>持仓</th><th>LLM</th><th>操作</th>"
        )
        parts.append("</tr></thead><tbody>")

        for i, t in enumerate(sorted_t):
            ret = t["total_return"]
            ret_class = "positive" if ret > 0 else "negative"
            llm = t.get("llm_action", "")
            if llm == "买入":
                tag_class = "tag-buy"
            elif llm == "放弃":
                tag_class = "tag-abandon"
            elif llm == "观察":
                tag_class = "tag-hold"
            else:
                tag_class = "tag-sell"

            # 展开：选股理由 + K线描述 + LLM 判断
            metrics = t.get("metrics", {})
            kline_desc = esc(t.get("kline_description", ""))
            llm_reason = esc(t.get("llm_reason", ""))
            entry = t.get("entry_price", 0)
            sl = t.get("stop_loss_price", 0)
            kl = t.get("key_low", 0)
            tbr = t.get("trend_break_ref", "")

            detail_html = f"""
<div class='details-content'>
  <div class='section-title'>📊 选股指标</div>
  <table style='box-shadow:none;margin:4px 0'><tr>
    <td><b>MA250</b>: {fn(metrics.get("ma250"), ".2f")}</td>
    <td><b>60日涨幅</b>: {fp(metrics.get("rise_60d"))}</td>
    <td><b>回调比</b>: {fn(metrics.get("pullback_ratio"), ".2%")}</td>
    <td><b>60日高</b>: {fn(metrics.get("high_60"), ".2f")}</td>
    <td><b>60日低</b>: {fn(metrics.get("low_60"), ".2f")}</td>
  </tr></table>

  <div class='section-title'>💰 交易参数</div>
  <table style='box-shadow:none;margin:4px 0'><tr>
    <td><b>买入价</b>: {fn(entry, ".2f")}</td>
    <td><b>止损价</b>: {fn(sl, ".2f")}</td>
    <td><b>Key Low</b>: {fn(kl, ".2f")}</td>
    <td><b>趋势破坏参考</b>: {fn(tbr, ".2f")}</td>
  </tr></table>

  <div class='section-title'>🤖 LLM 判断</div>
  <p>动作: <span class='tag {tag_class}'>{esc(llm)}</span> | 置信度: {t.get("llm_confidence", 0):.0%} | 理由: {llm_reason}</p>

  <div class='section-title'>📈 K线形态描述</div>
  <p style='background:#f5f5f5;padding:8px;border-radius:4px;white-space:pre-wrap'>{kline_desc}</p>
</div>"""

            parts.append("<tr>")
            parts.append(f"<td>{i + 1}</td>")
            parts.append(f"<td><b>{t['symbol']}</b></td>")
            parts.append(f"<td>{esc(t.get('name', ''))}</td>")
            parts.append(f"<td>{t['signal_date']}</td>")
            parts.append(f"<td class='{ret_class}'>{ret:+.2%}</td>")
            parts.append(f"<td>{t.get('exit_reason', '')}</td>")
            parts.append(f"<td>{t.get('holding_days', '')}d</td>")
            parts.append(f"<td><span class='tag {tag_class}'>{esc(llm)}</span></td>")
            parts.append(
                "<td><button class='toggle-btn' onclick='toggleDetail(this)'>详情</button>"
            )
            # K 线图按钮
            signal_date_clean = t["signal_date"].replace("-", "")
            chart_file = f"charts/combined_{t['symbol']}_{signal_date_clean}.html"
            parts.append(
                f" <a href='{chart_file}' target='_blank' class='toggle-btn' style='text-decoration:none;display:inline-block;margin-left:4px'>K线</a></td>"
            )
            parts.append("</tr>")
            parts.append(
                f"<tr class='details-row'><td colspan='9'>{detail_html}</td></tr>"
            )

        parts.append("</tbody></table>")

    # ── 策略优化建议 ──
    parts.append("<h2>6. 策略优化建议</h2><ul>")
    if engine["stop_loss_rate"] > 0.5:
        parts.append(
            f"<li>⚠️ 止损率 {engine['stop_loss_rate']:.0%} 过高，信号质量需要提升</li>"
        )
    if engine["win_rate"] < 0.4:
        parts.append(
            f"<li>⚠️ 胜率 {engine['win_rate']:.0%} 偏低，考虑更严格的入场条件</li>"
        )
    if portfolio and portfolio.get("sharpe_ratio", 0) < 0:
        parts.append("<li>⚠️ 夏普比率为负，策略未跑赢无风险收益</li>")
    if engine["avg_return_all"] and engine["avg_return_all"] > 0:
        parts.append(
            f"<li>✅ 逐笔平均收益 {engine['avg_return_all']:+.2%} 为正，信号方向正确</li>"
        )
    parts.append("</ul>")

    # ── Footer ──
    parts.append("<div class='disclaimer'>⚠️ 仅作研究和辅助分析，不构成投资建议。</div>")

    # ── Toggle script ──
    parts.append("""
<script>
function toggleDetail(btn) {
    var row = btn.closest('tr').nextElementSibling;
    row.classList.toggle('show');
    btn.textContent = row.classList.contains('show') ? '收起' : '详情';
}
</script>
</body></html>""")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="生成回测报表 (Markdown + HTML)")
    parser.add_argument("--input", required=True, help="回测 JSON 文件路径")
    parser.add_argument("--output-md", default=None, help="Markdown 输出路径")
    parser.add_argument("--output-html", default=None, help="HTML 输出路径")
    args = parser.parse_args()

    result_path = Path(args.input)
    if not result_path.exists():
        print(f"错误: {result_path} 不存在")
        sys.exit(1)

    data = json.loads(result_path.read_text(encoding="utf-8"))

    # Markdown
    md_path = Path(args.output_md) if args.output_md else result_path.with_suffix(".md")
    md_path.write_text(generate_markdown(data), encoding="utf-8")
    print(f"Markdown 报表: {md_path}")

    # HTML
    html_path = (
        Path(args.output_html) if args.output_html else result_path.with_suffix(".html")
    )
    html_path.write_text(generate_html(data), encoding="utf-8")
    print(f"HTML 报表: {html_path}")


if __name__ == "__main__":
    main()
