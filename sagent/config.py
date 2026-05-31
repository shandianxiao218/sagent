from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelConfig:
    default_judgement_model: str
    optional_judgement_models: list[str]


@dataclass(frozen=True)
class ScanConfig:
    max_new_positions_per_week: int
    position_size_ratio: float


@dataclass(frozen=True)
class PortfolioConfig:
    path: str


@dataclass(frozen=True)
class PushConfig:
    feishu_enabled: bool
    feishu_webhook_env: str
    webhook_configured: bool


@dataclass(frozen=True)
class AppConfig:
    models: ModelConfig
    scan: ScanConfig
    portfolio: PortfolioConfig
    push: PushConfig

    def to_public_dict(self) -> dict:
        return {
            "models": {
                "defaultJudgementModel": self.models.default_judgement_model,
                "optionalJudgementModels": self.models.optional_judgement_models,
            },
            "scan": {
                "maxNewPositionsPerWeek": self.scan.max_new_positions_per_week,
                "positionSizeRatio": self.scan.position_size_ratio,
            },
            "portfolio": {"path": self.portfolio.path},
            "push": {
                "feishuEnabled": self.push.feishu_enabled,
                "feishuWebhookEnv": self.push.feishu_webhook_env,
                "webhookConfigured": self.push.webhook_configured,
            },
        }


def load_config(path: Path, env: Mapping[str, str] | None = None) -> AppConfig:
    env = env or {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    models = raw.get("models", {})
    scan = raw.get("scan", {})
    portfolio = raw.get("portfolio", {})
    push = raw.get("push", {})
    webhook_env = push.get("feishuWebhookEnv", "SAGENT_FEISHU_WEBHOOK")
    return AppConfig(
        models=ModelConfig(
            default_judgement_model=models.get("defaultJudgementModel", "GLM5.1"),
            optional_judgement_models=list(
                models.get("optionalJudgementModels", ["GPT-5.5"])
            ),
        ),
        scan=ScanConfig(
            max_new_positions_per_week=int(scan.get("maxNewPositionsPerWeek", 2)),
            position_size_ratio=float(scan.get("positionSizeRatio", 0.1)),
        ),
        portfolio=PortfolioConfig(path=portfolio.get("path", "portfolio.json")),
        push=PushConfig(
            feishu_enabled=bool(push.get("feishuEnabled", False)),
            feishu_webhook_env=webhook_env,
            webhook_configured=bool(env.get(webhook_env)),
        ),
    )
