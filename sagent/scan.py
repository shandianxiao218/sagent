from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .config import load_config
from .kline import describe_stock
from .llm import FallbackLLMClient, LLMClient, judge_sector, judge_stock
from .notify import send_feishu_summary
from .portfolio import PortfolioStore, monitor_positions
from .sector import summarize_sectors, validate_mainline_sectors
from .technical import filter_stock_pool, technical_candidates


def run_scan(
    data,
    portfolio_path: Path,
    config_path: Path,
    env: dict[str, str],
    llm_client: LLMClient | None = None,
) -> dict:
    """执行完整扫描流程。

    llm_client:
      - None（默认）：使用规则引擎 fallback，不调用任何 LLM API。
        适合 fixture 测试和纯量化场景。
      - FallbackLLMClient 或其他 LLMClient 实例：由调用方注入。
        pi 环境下由 extension 注入 pi 的模型能力。
    """
    config = load_config(config_path, env=env)
    model_name = config.models.default_judgement_model
    fallback_model = (
        config.models.optional_judgement_models[0]
        if config.models.optional_judgement_models
        else model_name
    )
    portfolio = PortfolioStore(portfolio_path).load_or_create()

    current_prices = {
        position.symbol: data.daily_bars(position.symbol)[-1].close
        for position in portfolio.positions
        if data.daily_bars(position.symbol)
    }
    portfolio_suggestions = monitor_positions(
        portfolio, current_prices, trend_broken={}
    )

    pool = filter_stock_pool(data.stocks())
    raw_candidates = technical_candidates(data, pool.included)
    validations = validate_mainline_sectors(summarize_sectors(data))

    # 如果调用方注入了 client 且有备用模型，包装为自动降级链
    effective_client = llm_client
    fallback_log: list = []
    if llm_client is not None and model_name != fallback_model:
        effective_client = FallbackLLMClient(
            primary=llm_client,
            fallback=llm_client,
            primary_model=model_name,
            fallback_model=fallback_model,
            fallback_log=fallback_log,
        )

    candidates: list[dict] = []
    for candidate in raw_candidates:
        validation = validations.get(candidate.sector)
        if validation is None:
            continue
        sector_decision = judge_sector(
            validation, model=model_name, client=effective_client
        )
        description = describe_stock(
            candidate.symbol, data.daily_bars(candidate.symbol)
        )
        decision = judge_stock(
            description, sector_decision, model=model_name, client=effective_client
        )
        candidates.append(
            {
                "symbol": candidate.symbol,
                "name": candidate.name,
                "sector": candidate.sector,
                "action": decision.action,
                "reason": decision.reason,
                "key_low": decision.key_low,
                "invalid_condition": decision.invalid_condition,
                "risk": decision.risk,
                "metrics": candidate.metrics,
            }
        )

    text = (
        "\n".join(
            [
                f"{item['symbol']} {item['name']} {item['action']} {item['reason']}"
                for item in candidates
            ]
        )
        or "今日无候选股"
    )
    feishu = (
        send_feishu_summary(text, env)
        if config.push.feishu_enabled
        else {"ok": True, "mode": "disabled"}
    )
    return {
        "mode": "fixture",
        "judgement_model": model_name,
        "portfolio_suggestions": [asdict(item) for item in portfolio_suggestions],
        "candidates": candidates,
        "excluded": [asdict(item) for item in pool.excluded],
        "feishu": feishu,
        "warning": "仅作研究和辅助分析，不构成投资建议。",
        "fallback_events": [
            {
                "original_model": e.original_model,
                "fallback_model": e.fallback_model,
                "purpose": e.purpose,
                "reason": e.reason,
            }
            for e in fallback_log
        ],
    }
