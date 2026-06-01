#!/usr/bin/env python3
"""分析LLM盲判结果：方案A + 方案B。

输出精确率、召回率、分层收益对比等统计。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def analyze_plan_a():
    """方案A：27个信号的LLM判断 vs forward performance。"""
    signals = json.loads(
        (ROOT / "backtest_llm_judge_input.json").read_text(encoding="utf-8")
    )["signals"]
    judgements = json.loads(
        (ROOT / "backtest_llm_judgement_a.json").read_text(encoding="utf-8")
    )["judgements"]

    # 构建 lookup
    j_map = {j["id"]: j for j in judgements}

    # 定义"真实好信号"：20d收益 > 0 且 20d最大回撤 < 15%
    def is_good(s):
        r20 = s["_forward"].get("return_20d")
        mdd = s["_forward"].get("max_drawdown_20d", 1)
        if r20 is None:
            return False
        return r20 > 0 and mdd < 0.15

    # 定义"真实差信号"：20d亏损 >= 5%
    def is_bad(s):
        r20 = s["_forward"].get("return_20d")
        if r20 is None:
            return False
        return r20 <= -0.05

    total = len(signals)
    actual_good = [s for s in signals if is_good(s)]
    actual_bad = [s for s in signals if is_bad(s)]

    # LLM 判断分组
    llm_buy = [s for s in signals if j_map[s["id"]]["action"] == "买入"]
    llm_observe = [s for s in signals if j_map[s["id"]]["action"] == "观察"]
    llm_reject = [s for s in signals if j_map[s["id"]]["action"] == "放弃"]

    # 精确率/召回率
    tp = len([s for s in llm_buy if is_good(s)])  # 判买入且真的好
    fp = len([s for s in llm_buy if not is_good(s)])  # 判买入但实际不好
    fn = len(
        [s for s in signals if is_good(s) and j_map[s["id"]]["action"] != "买入"]
    )  # 好的但没判买入
    tn = len([s for s in llm_reject if is_bad(s)])  # 判放弃且真的差

    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    reject_accuracy = tn / max(len(llm_reject), 1)

    # 各组 forward return 统计
    def group_stats(group, field="return_20d"):
        values = [
            s["_forward"][field] for s in group if s["_forward"].get(field) is not None
        ]
        if not values:
            return {"count": 0, "mean": None, "median": None, "win_rate": None}
        return {
            "count": len(values),
            "mean": round(mean(values), 4),
            "median": round(median(values), 4),
            "win_rate": round(sum(1 for v in values if v > 0) / len(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    # 对比：纯量化（全部27个）vs LLM判买入 vs LLM判放弃
    quant_all = [s for s in signals if s["_forward"].get("return_20d") is not None]
    quant_buy_stats = group_stats(quant_all)

    # LLM判买入的 forward
    llm_buy_stats = group_stats(llm_buy)

    # LLM判放弃的 forward
    llm_reject_stats = group_stats(llm_reject)

    # LLM判观察的 forward
    llm_observe_stats = group_stats(llm_observe)

    # 止损率对比
    def stop_loss_rate(group):
        valid = [s for s in group if s["_forward"].get("return_20d") is not None]
        if not valid:
            return None
        hits = sum(1 for s in valid if s["_forward"]["return_20d"] <= -0.05)
        return round(hits / len(valid), 4)

    result = {
        "plan": "A",
        "description": "LLM对27个量化粗筛信号的形态盲判",
        "confusion_matrix": {
            "total_signals": total,
            "actual_good": len(actual_good),
            "actual_bad": len(actual_bad),
            "llm_buy_count": len(llm_buy),
            "llm_observe_count": len(llm_observe),
            "llm_reject_count": len(llm_reject),
            "TP_buy_correct": tp,
            "FP_buy_wrong": fp,
            "FN_missed_good": fn,
            "TN_reject_correct": tn,
        },
        "metrics": {
            "buy_precision": round(precision, 4),
            "buy_recall": round(recall, 4),
            "reject_accuracy": round(reject_accuracy, 4),
        },
        "forward_comparison": {
            "quant_all_27": quant_buy_stats,
            "llm_buy": llm_buy_stats,
            "llm_observe": llm_observe_stats,
            "llm_reject": llm_reject_stats,
        },
        "stop_loss_comparison": {
            "quant_all": stop_loss_rate(quant_all),
            "llm_buy": stop_loss_rate(llm_buy),
            "llm_reject": stop_loss_rate(llm_reject),
        },
        "llm_buy_details": [
            {
                "id": s["id"],
                "symbol": s["symbol"],
                "name": s["name"],
                "date": s["signal_date"],
                "entry": s["entry_price"],
                "return_20d": s["_forward"].get("return_20d"),
                "max_dd": s["_forward"].get("max_drawdown_20d"),
                "auto_label": s["_auto_label"],
                "llm_reason": j_map[s["id"]]["reason"][:60],
            }
            for s in llm_buy
        ],
        "llm_reject_details": [
            {
                "id": s["id"],
                "symbol": s["symbol"],
                "name": s["name"],
                "return_20d": s["_forward"].get("return_20d"),
                "llm_reason": j_map[s["id"]]["reason"][:60],
            }
            for s in llm_reject
        ],
    }
    return result


def analyze_plan_b():
    """方案B：10个验证案例的LLM盲判 vs auto_label。"""
    cases = json.loads(
        (ROOT / "fixtures/validation/llm_cases.json").read_text(encoding="utf-8")
    )["cases"]
    judgements = json.loads(
        (ROOT / "backtest_llm_judgement_b.json").read_text(encoding="utf-8")
    )["judgements"]

    j_map = {j["id"]: j for j in judgements}

    total = len(cases)
    correct = 0
    details = []

    for case in cases:
        j = j_map.get(case["id"])
        if not j:
            continue

        expected = case["expected_action"]  # 买入/观察/放弃
        actual = j["action"]

        # 宽松匹配：买入和观察都算"接受"
        strict_match = expected == actual
        loose_match = (expected in ("买入", "观察") and actual in ("买入", "观察")) or (
            expected == "放弃" and actual == "放弃"
        )

        if loose_match:
            correct += 1

        details.append(
            {
                "id": case["id"],
                "name": case["name"],
                "human_label": case["human_label"],
                "expected_action": expected,
                "llm_action": actual,
                "strict_match": strict_match,
                "loose_match": loose_match,
                "forward_20d": case["_forward_performance"].get("return_20d"),
                "max_dd": case["_forward_performance"].get("max_drawdown_20d"),
                "llm_confidence": j["confidence"],
            }
        )

    # 按标签分组统计
    by_label = {}
    for label in ("正例", "反例", "边界"):
        group = [d for d in details if d["human_label"] == label]
        if group:
            by_label[label] = {
                "count": len(group),
                "llm_buy": sum(1 for d in group if d["llm_action"] == "买入"),
                "llm_observe": sum(1 for d in group if d["llm_action"] == "观察"),
                "llm_reject": sum(1 for d in group if d["llm_action"] == "放弃"),
            }

    # LLM判买入的案例的 forward 统计
    llm_buy_cases = [d for d in details if d["llm_action"] == "买入"]
    llm_buy_returns = [
        d["forward_20d"] for d in llm_buy_cases if d["forward_20d"] is not None
    ]

    result = {
        "plan": "B",
        "description": "LLM对10个验证案例（正例4+反例4+边界2）的盲判",
        "accuracy": {
            "total": total,
            "loose_correct": correct,
            "loose_accuracy": round(correct / total, 4),
        },
        "by_label": by_label,
        "details": details,
        "llm_buy_forward": {
            "count": len(llm_buy_returns),
            "mean": round(mean(llm_buy_returns), 4) if llm_buy_returns else None,
        },
    }
    return result


def main() -> None:
    print("=== 方案A + 方案B LLM回测分析 ===\n", file=sys.stderr)

    a = analyze_plan_a()
    b = analyze_plan_b()

    # 输出方案A
    print("── 方案A ──", file=sys.stderr)
    cm = a["confusion_matrix"]
    print(f"  信号总数: {cm['total_signals']}", file=sys.stderr)
    print(f"  实际好信号(20d>0且MDD<15%): {cm['actual_good']}", file=sys.stderr)
    print(f"  实际差信号(20d<=-5%): {cm['actual_bad']}", file=sys.stderr)
    print(
        f"  LLM判买入: {cm['llm_buy_count']}, 观察: {cm['llm_observe_count']}, 放弃: {cm['llm_reject_count']}",
        file=sys.stderr,
    )
    print(
        f"  TP={cm['TP_buy_correct']}, FP={cm['FP_buy_wrong']}, FN={cm['FN_missed_good']}, TN={cm['TN_reject_correct']}",
        file=sys.stderr,
    )
    m = a["metrics"]
    print(
        f"  买入精确率: {m['buy_precision']}, 买入召回率: {m['buy_recall']}, 放弃准确率: {m['reject_accuracy']}",
        file=sys.stderr,
    )

    fc = a["forward_comparison"]
    print("\n  Forward 20d 对比:", file=sys.stderr)
    print(
        f"    纯量化(全27): mean={fc['quant_all_27']['mean']}, win_rate={fc['quant_all_27']['win_rate']}",
        file=sys.stderr,
    )
    print(
        f"    LLM判买入:    mean={fc['llm_buy']['mean']}, win_rate={fc['llm_buy']['win_rate']}",
        file=sys.stderr,
    )
    print(
        f"    LLM判观察:    mean={fc['llm_observe']['mean']}, win_rate={fc['llm_observe']['win_rate']}",
        file=sys.stderr,
    )
    print(
        f"    LLM判放弃:    mean={fc['llm_reject']['mean']}, win_rate={fc['llm_reject']['win_rate']}",
        file=sys.stderr,
    )

    sl = a["stop_loss_comparison"]
    print("\n  止损率对比:", file=sys.stderr)
    print(
        f"    纯量化: {sl['quant_all']}, LLM买入: {sl['llm_buy']}, LLM放弃: {sl['llm_reject']}",
        file=sys.stderr,
    )

    # 输出方案B
    print("\n── 方案B ──", file=sys.stderr)
    acc = b["accuracy"]
    print(
        f"  总案例: {acc['total']}, 宽松准确率: {acc['loose_accuracy']} ({acc['loose_correct']}/{acc['total']})",
        file=sys.stderr,
    )
    for label, stats in b["by_label"].items():
        print(
            f"  {label}: 买入={stats['llm_buy']}, 观察={stats['llm_observe']}, 放弃={stats['llm_reject']}",
            file=sys.stderr,
        )

    # 保存结果
    output = {"plan_a": a, "plan_b": b}
    out_path = ROOT / "backtest_llm_analysis.json"
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n已写入 {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
