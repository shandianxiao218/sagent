"""LLM 验证案例运行器。

读取验证案例集，用规则引擎或 pi agent 的 LLM 判断每个案例，
输出与人工标注的对比报告。

用法：
  - Python 规则引擎验证：run_validation_cases(path)
  - pi agent LLM 验证：prepare_scan 输出案例 JSON → pi agent 逐个判断 → apply_decision
"""

from __future__ import annotations

import json
from pathlib import Path


def _rule_engine_predict(case: dict) -> dict:
    """规则引擎预测。模拟量化粗筛 + 简单形态规则的判断。"""
    sector = case.get("sector_info", {})
    level = sector.get("level", "非主线")
    kline = case.get("kline_description", "")

    # 非主线 → 放弃
    if level == "非主线":
        return {
            "action": "放弃",
            "reason": f"板块为{level}，非市场主线",
            "confidence": 0.85,
        }

    # 强主线 + 突破 + 回调 → 买入
    if level == "强主线" and "突破" in kline and "回调" in kline:
        # 检查回调是否过深
        if "70%" in kline or "回调幅度约为前波涨幅的 70%" in kline:
            return {
                "action": "放弃",
                "reason": "回调幅度过大，可能已破坏趋势结构",
                "confidence": 0.7,
            }
        # 检查量能
        if "0.8" in kline and "量能不足" in kline:
            return {
                "action": "放弃",
                "reason": "量能不足，突破信号不可靠",
                "confidence": 0.65,
            }
        return {
            "action": "买入",
            "reason": f"板块为{level}，上升趋势回调后突破",
            "confidence": 0.8,
        }

    # 弱主线或突破不明确 → 观察
    return {
        "action": "观察",
        "reason": f"板块为{level}或突破信号不充分，需继续观察",
        "confidence": 0.6,
    }


def run_validation_cases(
    path: Path,
    model: str = "GLM5.1",
    use_llm: bool = False,
) -> dict:
    """运行验证案例集。

    Parameters
    ----------
    path : 案例文件路径
    model : 记录使用的模型名称
    use_llm : 是否调用真实 LLM（当前仅支持规则引擎）

    Returns
    -------
    dict 包含每个案例的匹配结果和汇总统计
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases_raw = raw.get("cases", [])

    results: list[dict] = []
    for case in cases_raw:
        expected = case.get("expected_action", "")
        if use_llm:
            # LLM 判断由 pi agent 执行，这里只记录 case
            predicted = {"action": "待LLM判断", "reason": "", "confidence": 0}
        else:
            predicted = _rule_engine_predict(case)

        match = predicted["action"] == expected
        results.append({
            "id": case.get("id"),
            "name": case.get("name"),
            "category": case.get("category"),
            "human_label": case.get("human_label"),
            "expected_action": expected,
            "expected_key_low": case.get("expected_key_low"),
            "predicted_action": predicted["action"],
            "predicted_reason": predicted.get("reason", ""),
            "predicted_confidence": predicted.get("confidence", 0),
            "match": match,
        })

    # 汇总统计
    total = len(results)
    matches = sum(1 for r in results if r["match"])

    by_label: dict[str, dict] = {}
    for label in ("正例", "反例", "边界"):
        group = [r for r in results if r["human_label"] == label]
        label_matches = sum(1 for r in group if r["match"])
        by_label[label] = {
            "total": len(group),
            "correct": label_matches,
            "accuracy": round(label_matches / max(len(group), 1), 4),
            "errors": [
                {"id": r["id"], "expected": r["expected_action"], "predicted": r["predicted_action"]}
                for r in group
                if not r["match"]
            ],
        }

    return {
        "model": model,
        "mode": "llm" if use_llm else "rule_engine",
        "total": total,
        "correct": matches,
        "accuracy": round(matches / max(total, 1), 4),
        "by_label": by_label,
        "cases": results,
        "notes": (
            "规则引擎准确率仅供参考。LLM 判断需要通过 pi agent 使用 a-share-main-trend skill 逐案例运行。"
            "建议用 prepare_validation → pi agent 判断 → collect_results 流程进行 LLM 验证。"
        ),
    }


def prepare_validation_prompt(case: dict) -> str:
    """为单个案例构建 pi agent 验证 prompt。"""
    sector = case.get("sector_info", {})
    return (
        "你是 sagent A 股主线交易分析助手，必须遵守 skills/a-share-main-trend/SKILL.md。\n"
        "请根据以下信息判断该案例的建议动作。\n\n"
        f"案例编号：{case.get('id')}\n"
        f"案例名称：{case.get('name')}\n"
        f"板块：{sector.get('sector', '未知')}\n"
        f"板块主线级别：{sector.get('level', '未知')}\n"
        f"板块规则命中：{sector.get('rules', {})}\n"
        f"是否需要 LLM 板块判断：{'是' if sector.get('needs_llm') else '否'}\n\n"
        f"K线描述：{case.get('kline_description', '')}\n\n"
        "请用 JSON 格式输出：\n"
        '{"action": "买入/观察/放弃", "reason": "...", "confidence": 0.0-1.0, '
        '"key_low": 0.00, "invalid_condition": "...", "risk": "..."}'
    )


def prepare_all_validation_prompts(path: Path) -> list[dict]:
    """为所有案例生成验证 prompt，供 pi agent 批量处理。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases", [])
    output: list[dict] = []
    for case in cases:
        output.append({
            "id": case.get("id"),
            "name": case.get("name"),
            "human_label": case.get("human_label"),
            "expected_action": case.get("expected_action"),
            "prompt": prepare_validation_prompt(case),
        })
    return output
