"""分析 V2 回测结果（8%止损上限）。"""

import json

with open("backtest_engine_v2.json", "r", encoding="utf-8") as f:
    data = json.load(f)

stats = data.get("stats", {})
trades = data.get("trades", [])
portfolio = data.get("portfolio", {})

print("=== V2 引擎回测统计（止损上限 8%）===")
for k, v in stats.items():
    if k != "trades":
        print(f"  {k}: {v}")

print(f"\n=== 交易明细 ({len(trades)} 笔) ===\n")
sl_cnt = 0
tp_cnt = 0
hold_cnt = 0
half_cnt = 0
returns = []

for i, t in enumerate(trades):
    entry = t.get("entry_price", 0)
    sl = t.get("stop_loss_price", 0)
    kl = t.get("key_low", 0)
    sl_dist = (entry - sl) / entry * 100 if entry > 0 else 0
    kl_dist = (entry - kl) / entry * 100 if entry > 0 else 0
    ret = t.get("total_return", 0)
    ret_pct = ret * 100
    returns.append(ret_pct)
    exit_r = t.get("exit_reason", "")

    if "止损" in exit_r and "半仓" not in exit_r:
        sl_cnt += 1
    elif "半仓" in exit_r or "趋势" in exit_r:
        tp_cnt += 1
    elif "到期" in exit_r:
        hold_cnt += 1
    if t.get("half_profit_locked"):
        half_cnt += 1

    flag = "+" if ret_pct > 0 else "-"
    print(
        f"  [{i + 1:2d}] {flag} {t.get('symbol', ''):6s} {t.get('signal_date', '')} "
        f"entry={entry:.2f} SL={sl:.2f}({sl_dist:.1f}%) KL={kl:.2f}({kl_dist:.1f}%) "
        f"exit={exit_r} ret={ret_pct:+.2f}% Rmax={t.get('max_r', 0):.1f} "
        f"half={'Y' if t.get('half_profit_locked') else 'N'}"
    )

total = len(trades)
wins = sum(1 for r in returns if r > 0)
print(f"\n=== 汇总 ===")
print(f"  止损: {sl_cnt}/{total} ({sl_cnt / total * 100:.1f}%)")
print(f"  趋势破坏: {tp_cnt}/{total}")
print(f"  持有到期: {hold_cnt}/{total}")
print(f"  半仓止盈: {half_cnt}/{total}")
print(f"  胜率: {wins}/{total} ({wins / total * 100:.1f}%)")
print(f"  平均收益: {sum(returns) / len(returns):+.2f}%")
if returns:
    pos = [r for r in returns if r > 0]
    neg = [r for r in returns if r < 0]
    avg_win = sum(pos) / len(pos) if pos else 0
    avg_loss = sum(neg) / len(neg) if neg else 0
    print(f"  平均盈利: {avg_win:+.2f}% ({len(pos)} 笔)")
    print(f"  平均亏损: {avg_loss:+.2f}% ({len(neg)} 笔)")
    if avg_loss != 0:
        print(f"  盈亏比: {abs(avg_win / avg_loss):.2f}")

print(f"\n=== 组合级统计 ===")
for k, v in portfolio.items():
    print(f"  {k}: {v}")
