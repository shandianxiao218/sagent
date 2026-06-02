"""分析回测止损率问题的诊断脚本。"""

import json

with open("backtest_engine_v1.json", "r", encoding="utf-8") as f:
    data = json.load(f)

trades = data.get("trades", [])
stats = data.get("stats", {})

print("=== 总体统计 ===")
for k, v in stats.items():
    print(f"  {k}: {v}")

print(f"\n=== 各交易止损距离分析 ({len(trades)} 笔) ===\n")

# 统计
sl_triggered = 0
sl_dists = []
half_profit_cnt = 0

for i, t in enumerate(trades):
    entry = t.get("entry_price", 0)
    sl = t.get("stop_loss_price", 0)
    kl = t.get("key_low", 0)
    sl_type = t.get("stop_loss_type", "")
    exit_reason = t.get("exit_reason", "")
    total_ret = t.get("total_return", 0)
    half_locked = t.get("half_profit_locked", False)
    max_r = t.get("max_r", 0)
    exit_price = t.get("exit_price", 0)
    holding_days = t.get("holding_days", 0)

    sl_dist = (entry - sl) / entry * 100 if entry > 0 else 0

    sl_dists.append(sl_dist)

    if "止损" in exit_reason:
        sl_triggered += 1
    if half_locked:
        half_profit_cnt += 1

    flag = "*" if total_ret > 0 else "x"
    print(
        f"  [{i + 1:2d}] {flag} {t.get('symbol', ''):6s} {t.get('signal_date', '')} "
        f"entry={entry:.2f} exit={exit_price:.2f} SL={sl:.2f}({sl_dist:.1f}%) "
        f"type={sl_type} exit={exit_reason} ret={total_ret:+.2f}% "
        f"Rmax={max_r:.1f} days={holding_days}"
    )

print(f"\n=== 止损距离统计 ===")
print(
    f"  止损触发: {sl_triggered}/{len(trades)} ({sl_triggered / len(trades) * 100:.1f}%)"
)
print(f"  半仓止盈: {half_profit_cnt}")
print(
    f"  SL距离: min={min(sl_dists):.1f}% max={max(sl_dists):.1f}% avg={sum(sl_dists) / len(sl_dists):.1f}%"
)

# 盈亏分组
wins = [t for t in trades if t.get("total_return", 0) > 0]
losses = [t for t in trades if t.get("total_return", 0) <= 0]
print(f"\n=== 盈亏分析 ===")
print(f"  盈利: {len(wins)} 笔")
for t in wins:
    print(
        f"    {t.get('symbol', '')} {t.get('signal_date', '')} ret={t.get('total_return', 0):+.2f}% Rmax={t.get('max_r', 0):.1f} half={t.get('half_profit_locked', False)}"
    )
print(f"  亏损: {len(losses)} 笔")
for t in losses:
    print(
        f"    {t.get('symbol', '')} {t.get('signal_date', '')} ret={t.get('total_return', 0):+.2f}% exit={t.get('exit_reason', '')} SL_dist={((t['entry_price'] - t['stop_loss_price']) / t['entry_price'] * 100):.1f}%"
    )

# 模拟过滤效果
print(f"\n=== 模拟止损距离过滤效果 ===")
for min_sl_dist in [3.0, 3.5, 4.0, 4.5, 5.0]:
    filtered = [(t, d) for t, d in zip(trades, sl_dists) if d >= min_sl_dist]
    if not filtered:
        print(f"  SL>={min_sl_dist}%: 无信号")
        continue
    rets = [t.get("total_return", 0) for t, _ in filtered]
    stopped_cnt = sum(1 for t, _ in filtered if "止损" in t.get("exit_reason", ""))
    avg_ret = sum(rets) / len(rets)
    win_cnt = sum(1 for r in rets if r > 0)
    half_cnt = sum(1 for t, _ in filtered if t.get("half_profit_locked", False))
    print(
        f"  SL>={min_sl_dist}%: {len(filtered)} 笔, "
        f"止损率 {stopped_cnt / len(filtered) * 100:.1f}%, "
        f"平均收益 {avg_ret:+.2f}%, "
        f"胜率 {win_cnt / len(filtered) * 100:.1f}%, "
        f"半仓止盈 {half_cnt}"
    )
