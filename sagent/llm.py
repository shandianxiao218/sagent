from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import Decision, KlineDescription, SectorValidation


@dataclass(frozen=True)
class PromptRequest:
    model: str
    prompt: str
    purpose: str


@dataclass(frozen=True)
class FallbackEvent:
    """记录一次模型降级事件。"""

    original_model: str
    fallback_model: str
    purpose: str
    reason: str


class LLMClient(Protocol):
    """LLM 客户端协议。pi 环境下由 pi agent 自身的模型承担判断，无需 Python 侧调用 API。"""

    def complete(self, request: PromptRequest) -> dict: ...


# ─── Prompt 构建（供 pi agent + skill 使用）──────────────────────


def build_sector_prompt(validation: SectorValidation) -> str:
    """构建板块主线判断 prompt，供 pi agent 或外部 LLM 调用。"""
    return (
        "你是 sagent A 股主线交易分析助手，必须遵守 skills/a-share-main-trend/SKILL.md。\n"
        f"板块：{validation.sector}\n"
        f"量化层级：{validation.level}\n"
        f"命中规则：{validation.rules}\n"
        "请用 JSON 格式输出：\n"
        '{"action": "主线/弱主线观察/非主线", "reason": "...", "confidence": 0.0-1.0, "risk": "..."}'
    )


def build_stock_prompt(description: KlineDescription, sector_decision: Decision) -> str:
    """构建个股形态判断 prompt，供 pi agent 或外部 LLM 调用。"""
    return (
        "你是 sagent A 股主线交易分析助手。\n"
        "只判断上升趋势中回调、整理并突破短期回调趋势的标的。\n"
        f"板块判断：{sector_decision.action}，理由：{sector_decision.reason}\n"
        f"K线描述：{description.text}\n"
        "请用 JSON 格式输出：\n"
        '{"action": "买入/观察/放弃", "reason": "...", "confidence": 0.0-1.0, '
        '"key_low": 0.00, "invalid_condition": "...", "risk": "..."}'
    )


# ─── 降级机制 ──────────────────────────────────────────────────


_QUOTA_ERROR_PATTERNS = (
    "quota",
    "rate_limit",
    "rate limit",
    "429",
    "insufficient_quota",
    "billing",
    "capacity",
    "overloaded",
    "server_error",
    "500",
    "503",
)


def _is_quota_error(error: Exception) -> bool:
    msg = str(error).lower()
    return any(pattern in msg for pattern in _QUOTA_ERROR_PATTERNS)


class FallbackLLMClient:
    """自动降级 LLM 客户端。主模型失败时自动切换到备用模型。"""

    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient,
        primary_model: str,
        fallback_model: str,
        fallback_log: list[FallbackEvent] | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.fallback_log: list[FallbackEvent] = (
            fallback_log if fallback_log is not None else []
        )

    def complete(self, request: PromptRequest) -> dict:
        if request.model == self.fallback_model:
            return self.fallback.complete(request)
        try:
            return self.primary.complete(request)
        except Exception as primary_error:
            if not _is_quota_error(primary_error):
                raise
            self.fallback_log.append(
                FallbackEvent(
                    original_model=self.primary_model,
                    fallback_model=self.fallback_model,
                    purpose=request.purpose,
                    reason=str(primary_error),
                )
            )
            return self.fallback.complete(
                PromptRequest(
                    model=self.fallback_model,
                    prompt=request.prompt,
                    purpose=request.purpose,
                )
            )


# ─── 规则引擎 fallback（无 LLM 时使用）──────────────────────────


def _decision_from_llm(payload: dict, fallback: Decision) -> Decision:
    return Decision(
        action=str(payload.get("action", fallback.action)),
        reason=str(payload.get("reason", fallback.reason)),
        model=str(payload.get("model", fallback.model)),
        risk=str(payload.get("risk", fallback.risk)),
        confidence=float(payload.get("confidence", fallback.confidence)),
        key_low=payload.get("key_low", fallback.key_low),
        invalid_condition=str(
            payload.get("invalid_condition", fallback.invalid_condition)
        ),
    )


def judge_sector(
    validation: SectorValidation, model: str = "GLM5.1", client: LLMClient | None = None
) -> Decision:
    """板块主线判断。有 LLM 客户端时调用 LLM，否则用规则引擎。"""
    if validation.level == "强主线":
        fallback = Decision(
            action="主线",
            reason=f"{validation.sector} 满足强主线量化条件",
            model=model,
            confidence=0.85,
        )
    elif validation.level == "弱主线":
        fallback = Decision(
            action="弱主线观察",
            reason=f"{validation.sector} 满足成交额和涨幅条件，但涨停扩散不足",
            model=model,
            confidence=0.62,
        )
    else:
        fallback = Decision(
            action="非主线",
            reason=f"{validation.sector} 未满足主线条件",
            model=model,
            confidence=0.8,
        )
    if client is None:
        return fallback
    return _decision_from_llm(
        client.complete(
            PromptRequest(
                model=model, prompt=build_sector_prompt(validation), purpose="sector"
            )
        ),
        fallback,
    )


def judge_stock(
    description: KlineDescription,
    sector_decision: Decision,
    model: str = "GLM5.1",
    client: LLMClient | None = None,
) -> Decision:
    """个股形态判断。有 LLM 客户端时调用 LLM，否则用规则引擎。"""
    text = description.text
    if sector_decision.action == "非主线":
        action, confidence = "放弃", 0.8
    elif "突破" in text and "回调" in text and description.key_low > 0:
        action = "买入" if sector_decision.action == "主线" else "观察"
        confidence = 0.74 if action == "买入" else 0.6
    else:
        action, confidence = "观察", 0.55
    fallback = Decision(
        action=action,
        reason=f"板块判断为{sector_decision.action}；个股描述显示上升趋势、回调结构和突破状态。",
        model=model,
        confidence=confidence,
        key_low=description.key_low,
        invalid_condition=f"跌破买点前关键低点 {description.key_low:.2f} 或单笔亏损达到5%时无效。",
    )
    if client is None:
        return fallback
    return _decision_from_llm(
        client.complete(
            PromptRequest(
                model=model,
                prompt=build_stock_prompt(description, sector_decision),
                purpose="stock",
            )
        ),
        fallback,
    )
