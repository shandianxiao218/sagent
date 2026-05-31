from __future__ import annotations

import json
from pathlib import Path


def _predict(case: dict) -> str:
    if case.get("sector_level") == "非主线":
        return "放弃"
    text = case.get("description", "")
    if case.get("sector_level") == "强主线" and "突破" in text and "回调" in text:
        return "买入"
    return "观察"


def run_validation_cases(path: Path, model: str = "GLM5.1") -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for case in raw.get("cases", []):
        predicted = _predict(case)
        cases.append(
            {
                "id": case.get("id"),
                "human_label": case.get("human_label"),
                "expected_action": case.get("expected_action"),
                "predicted_action": predicted,
                "match": predicted == case.get("expected_action"),
            }
        )
    return {"model": model, "total": len(cases), "cases": cases}
