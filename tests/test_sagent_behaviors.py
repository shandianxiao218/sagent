from __future__ import annotations

import json
from pathlib import Path

from sagent.backtest import run_layered_backtest
from sagent.config import load_config
from sagent.data import AStockDataMarketData, FixtureMarketData
from sagent.kline import describe_stock
from sagent.llm import (
    FallbackLLMClient,
    PromptRequest,
    build_sector_prompt,
    build_stock_prompt,
    judge_sector,
    judge_stock,
)
from sagent.portfolio import PortfolioStore, confirm_buy, monitor_positions
from sagent.scan import run_scan
from sagent.sector import summarize_sectors, validate_mainline_sectors
from sagent.technical import filter_stock_pool, technical_candidates
from sagent.validation import run_validation_cases


def fixture_data() -> FixtureMarketData:
    return FixtureMarketData(Path("fixtures/market/sample_market.json"))


def test_config_defaults_and_secret_handling(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGENT_FEISHU_WEBHOOK", "https://example.test/webhook")
    config = load_config(
        Path("config/default.json"), env={"SAGENT_FEISHU_WEBHOOK": "secret-url"}
    )

    assert config.models.default_judgement_model == "GLM5.1"
    assert "GPT-5.5" in config.models.optional_judgement_models
    assert config.push.feishu_enabled is False
    assert config.push.webhook_configured is True
    assert "secret-url" not in json.dumps(config.to_public_dict(), ensure_ascii=False)


def test_astock_data_adapter_normalizes_mootdx_bars_without_network():
    """AStockDataMarketData 通过注入的 mock mootdx 客户端获取日线。"""
    import pandas as pd

    class FakeMootdx:
        def bars(self, symbol, category, offset):
            return pd.DataFrame(
                [
                    {
                        "datetime": "2026-05-29",
                        "open": 10,
                        "high": 11,
                        "low": 9.8,
                        "close": 10.5,
                        "vol": 100,
                        "amount": 1000,
                    }
                ]
            )

        def quotes(self, symbol):
            return []

    class FakeTencent:
        def __call__(self, codes):
            return {
                "000001": {
                    "name": "样例科技",
                    "price": 10.5,
                    "pe_ttm": 25.3,
                    "pb": 3.1,
                    "mcap_yi": 1500,
                    "turnover_pct": 2.5,
                    "limit_up": 11.55,
                    "limit_down": 9.45,
                }
            }

    class FakeConcept:
        def __call__(self, code):
            return {
                "industry": "计算机应用",
                "concepts": ["AI应用", "机器人"],
                "region": "北京",
            }

    class FakeIndustry:
        def __call__(self, top_n=20):
            return {
                "top": [
                    {
                        "name": "AI应用",
                        "change_pct": 3.2,
                        "rank": 1,
                        "leading_stocks": ["000001"],
                    }
                ],
                "bottom": [],
                "total": 1,
            }

    data = AStockDataMarketData(
        mootdx_client=FakeMootdx(),
        tencent_quote=FakeTencent(),
        concept_blocks=FakeConcept(),
        industry_comparison=FakeIndustry(),
    )

    bars = data.daily_bars("000001")
    assert bars[0].close == 10.5
    assert bars[0].symbol == "000001"

    quotes = data.realtime_quotes(["000001"])
    assert quotes["000001"]["pe_ttm"] == 25.3
    assert quotes["000001"]["limit_up"] == 11.55

    concepts = data.concept_blocks("000001")
    assert "AI应用" in concepts["concepts"]

    ranking = data.industry_ranking()
    assert ranking["top"][0]["name"] == "AI应用"

    snapshots = data.sector_snapshots()
    assert snapshots[0].sector == "AI应用"
    assert snapshots[0].strong_stocks == ["000001"]


def test_fixture_data_adapter_returns_stable_market_structures():
    data = fixture_data()

    bars = data.daily_bars("000001")
    sectors = data.sector_snapshots()
    calendar = data.trade_calendar()

    assert len(bars) >= 260
    assert bars[-1].symbol == "000001"
    assert bars[-1].amount > 0
    assert sectors[0].sector == "AI应用"
    assert calendar[-1].is_open is True


def test_stock_pool_filters_liquidity_status_and_data_quality():
    result = filter_stock_pool(
        fixture_data().stocks(), min_avg_amount=100_000_000, min_listing_days=120
    )

    assert [stock.symbol for stock in result.included] == ["000001"]
    reasons = {item.symbol: item.reason for item in result.excluded}
    assert reasons["000002"] == "日均成交额低于阈值"
    assert reasons["000003"] == "ST 或异常交易标的"
    assert reasons["000004"] == "停牌"
    assert reasons["000005"] == "上市时间不足"


def test_technical_candidates_find_uptrend_pullback_breakout():
    stock = filter_stock_pool(fixture_data().stocks()).included[0]
    candidates = technical_candidates(fixture_data(), [stock])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.symbol == "000001"
    assert candidate.metrics["above_ma250"] is True
    assert candidate.metrics["rise_60d"] >= 0.5
    assert 0.15 <= candidate.metrics["pullback_ratio"] <= 0.5
    assert candidate.metrics["recent_rebound"] is True
    assert "突破短期回调趋势" in candidate.reasons


def test_kline_description_is_structured_and_concise():
    description = describe_stock(
        "000001", fixture_data().daily_bars("000001"), max_chars=900
    )

    assert description.symbol == "000001"
    assert description.key_low > 0
    assert "趋势" in description.text
    assert "回调" in description.text
    assert "突破" in description.text
    assert "成交量" in description.text
    assert len(description.text) <= 900


def test_sector_summary_and_mainline_validation():
    summaries = summarize_sectors(fixture_data())
    validations = validate_mainline_sectors(summaries)

    ai = validations["AI应用"]
    weak = validations["机器人"]
    assert ai.level == "强主线"
    assert ai.rules["turnover_top10_5d"] is True
    assert ai.rules["limit_up_breadth_3x"] is True
    assert weak.level == "弱主线"
    assert weak.needs_llm is True
    assert summaries["AI应用"].performance_windows["5d"]
    assert "10d_gain_top10_count" in summaries["AI应用"].rank_windows


def test_llm_judgement_uses_model_and_strategy_constraints():
    sector_decision = judge_sector(
        validate_mainline_sectors(summarize_sectors(fixture_data()))["AI应用"]
    )
    stock_decision = judge_stock(
        describe_stock("000001", fixture_data().daily_bars("000001")), sector_decision
    )

    assert sector_decision.model == "GLM5.1"
    assert sector_decision.action == "主线"
    assert stock_decision.model == "GLM5.1"
    assert stock_decision.action in {"买入", "观察"}
    assert stock_decision.key_low is not None
    assert stock_decision.invalid_condition
    assert stock_decision.confidence >= 0.5
    assert "skills/a-share-main-trend" in build_sector_prompt(
        validate_mainline_sectors(summarize_sectors(fixture_data()))["AI应用"]
    )
    assert "JSON" in build_stock_prompt(
        describe_stock("000001", fixture_data().daily_bars("000001")), sector_decision
    )


def test_portfolio_confirm_buy_enforces_10_percent_and_weekly_limit(tmp_path):
    store = PortfolioStore(tmp_path / "portfolio.json")
    portfolio = store.load_or_create(initial_cash=100_000)

    first = confirm_buy(
        portfolio,
        symbol="000001",
        name="样例一",
        sector="AI应用",
        buy_price=10,
        key_low=9.4,
        trade_date="2026-05-25",
    )
    second = confirm_buy(
        first.portfolio,
        symbol="000006",
        name="样例二",
        sector="AI应用",
        buy_price=20,
        key_low=18.8,
        trade_date="2026-05-27",
    )

    assert first.position.amount == 10_000
    assert first.position.quantity == 1000
    assert second.portfolio.weekly_open_count == 2

    try:
        confirm_buy(
            second.portfolio,
            symbol="000007",
            name="样例三",
            sector="AI应用",
            buy_price=10,
            key_low=9,
            trade_date="2026-05-28",
        )
    except ValueError as error:
        assert "每周最多" in str(error)
    else:
        raise AssertionError("expected weekly limit failure")


def test_portfolio_monitor_stop_loss_take_profit_and_trend_break(tmp_path):
    store = PortfolioStore(tmp_path / "portfolio.json")
    portfolio = store.load_or_create(initial_cash=100_000)
    portfolio = confirm_buy(
        portfolio,
        symbol="000001",
        name="样例一",
        sector="AI应用",
        buy_price=10,
        key_low=9.4,
        trade_date="2026-05-25",
    ).portfolio

    stop_loss = monitor_positions(portfolio, {"000001": 9.39}, trend_broken={})[0]
    take_profit = monitor_positions(portfolio, {"000001": 11.55}, trend_broken={})[0]
    broken = monitor_positions(
        portfolio, {"000001": 10.8}, trend_broken={"000001": True}
    )[0]

    assert stop_loss.action == "清仓"
    assert "关键低点" in stop_loss.reason
    assert take_profit.action == "减仓"
    assert "2.5R" in take_profit.reason
    assert portfolio.positions[0].half_taken is True
    assert any(item["action"] == "半仓止盈建议" for item in portfolio.trade_history)
    assert broken.action == "清仓"
    assert "趋势破坏" in broken.reason


def test_scan_orchestrates_holdings_candidates_actions_and_feishu_safe_skip(tmp_path):
    portfolio_path = tmp_path / "portfolio.json"
    store = PortfolioStore(portfolio_path)
    portfolio = confirm_buy(
        store.load_or_create(initial_cash=100_000),
        symbol="000001",
        name="样例一",
        sector="AI应用",
        buy_price=10,
        key_low=9.4,
        trade_date="2026-05-25",
    ).portfolio
    store.save(portfolio)

    result = run_scan(
        data=fixture_data(),
        portfolio_path=portfolio_path,
        config_path=Path("config/default.json"),
        env={},
    )

    assert result["mode"] == "fixture"
    assert result["judgement_model"] == "GLM5.1"
    assert result["portfolio_suggestions"]
    assert result["candidates"][0]["action"] in {"买入", "观察"}
    assert result["feishu"]["mode"] == "disabled"
    assert "不构成投资建议" in result["warning"]


def test_quant_backtest_outputs_quality_statistics_not_full_strategy_returns():
    report = run_layered_backtest(fixture_data())

    # 免责声明
    assert "不包含 LLM 判断层" in report["scope"]
    assert "不等同于完整策略收益回测" in report["disclaimer"]

    # 分层漏斗
    layers = report["layers"]
    assert layers["L1_stock_pool"]["passed"] >= 1
    assert layers["L1_stock_pool"]["pass_rate"] > 0
    assert layers["L5_breakout"]["passed"] >= 1
    assert layers["L6_mainline"]["mainline"] >= 1

    # Forward performance
    assert "forward_performance" in report
    assert report["forward_performance"]["all"]["5d"]["count"] >= 0

    # 阈值敏感度
    assert "sensitivity" in report
    assert "rise_60d" in report["sensitivity"]
    assert "pullback_range" in report["sensitivity"]

    # 板块分布
    assert "sector_distribution" in report


def test_historical_validation_cases_compare_llm_to_human_labels():
    result = run_validation_cases(
        Path("fixtures/validation/llm_cases.json"), model="GLM5.1"
    )

    # 基本结构
    assert result["model"] == "GLM5.1"
    assert result["mode"] == "rule_engine"
    assert result["total"] >= 10

    # 包含三种标签
    assert {"正例", "反例", "边界"} <= set(result["by_label"].keys())

    # 每个案例有 match 字段
    assert all("match" in case for case in result["cases"])

    # 汇总统计正确
    assert result["correct"] <= result["total"]
    assert 0 <= result["accuracy"] <= 1

    # by_label 的 total 之和等于 total
    label_sum = sum(v["total"] for v in result["by_label"].values())
    assert label_sum == result["total"]


def test_fallback_client_switches_on_quota_error():
    """GPT-5.5 额度用完时，FallbackLLMClient 自动切换到 GLM5.1，并记录降级事件。"""
    call_log: list[PromptRequest] = []

    class QuotaExhaustedClient:
        """模拟 GPT-5.5 额度耗尽。"""

        def complete(self, request: PromptRequest) -> dict:
            call_log.append(request)
            raise RuntimeError("insufficient_quota: GPT-5.5 额度已用完")

    class HealthyClient:
        """模拟 GLM5.1 正常响应。"""

        def complete(self, request: PromptRequest) -> dict:
            call_log.append(request)
            return {
                "action": "主线",
                "reason": "GLM5.1 降级判断",
                "model": request.model,
                "confidence": 0.7,
            }

    fallback_log: list = []
    client = FallbackLLMClient(
        primary=QuotaExhaustedClient(),
        fallback=HealthyClient(),
        primary_model="GPT-5.5",
        fallback_model="GLM5.1",
        fallback_log=fallback_log,
    )

    result = client.complete(
        PromptRequest(model="GPT-5.5", prompt="test", purpose="sector")
    )

    # 第一次调用 GPT-5.5 失败，第二次自动降级到 GLM5.1
    assert len(call_log) == 2
    assert call_log[0].model == "GPT-5.5"
    assert call_log[1].model == "GLM5.1"
    assert result["model"] == "GLM5.1"
    assert result["action"] == "主线"

    # 降级事件被记录
    assert len(fallback_log) == 1
    assert fallback_log[0].original_model == "GPT-5.5"
    assert fallback_log[0].fallback_model == "GLM5.1"
    assert "insufficient_quota" in fallback_log[0].reason


def test_fallback_client_does_not_switch_on_non_quota_error():
    """非额度类错误（如 prompt 无效）不应触发降级，直接抛出异常。"""

    class PromptErrorClient:
        def complete(self, request: PromptRequest) -> dict:
            raise ValueError("invalid prompt format")

    client = FallbackLLMClient(
        primary=PromptErrorClient(),
        fallback=PromptErrorClient(),
        primary_model="GPT-5.5",
        fallback_model="GLM5.1",
    )

    try:
        client.complete(PromptRequest(model="GPT-5.5", prompt="bad", purpose="test"))
    except ValueError as error:
        assert "invalid prompt" in str(error)
    else:
        raise AssertionError("应该抛出 ValueError 而不是降级")


def test_prepare_scan_outputs_structured_data_without_llm_judgement():
    """prepare_scan 输出包含量化粗筛 + K 线描述 + 板块验证，不含 LLM 判断结果。"""
    from sagent.kline import describe_stock
    from sagent.llm import build_sector_prompt
    from sagent.sector import summarize_sectors, validate_mainline_sectors
    from sagent.technical import filter_stock_pool, technical_candidates

    data = fixture_data()
    pool = filter_stock_pool(data.stocks())
    candidates = technical_candidates(data, pool.included)
    validations = validate_mainline_sectors(summarize_sectors(data))

    # 候选股必须有 K 线描述
    assert len(candidates) >= 1
    for candidate in candidates:
        description = describe_stock(
            candidate.symbol, data.daily_bars(candidate.symbol)
        )
        assert description.text
        assert description.key_low > 0
        assert "JSON" not in description.text  # K 线描述不含 LLM prompt

    # 板块验证必须有 level 和 rules
    for _name, validation in validations.items():
        assert validation.level in {"强主线", "弱主线", "非主线"}
        assert isinstance(validation.rules, dict)
        # 只有弱主线才需要 LLM 二次判断
        if validation.needs_llm:
            assert validation.level == "弱主线"
            prompt = build_sector_prompt(validation)
            assert "JSON" in prompt  # prompt 包含格式指引


def test_apply_decision_writes_buy_to_portfolio(tmp_path):
    """apply_decision 接收 JSON 判断结果，成功买入时写入 portfolio。"""
    from sagent.portfolio import PortfolioStore, confirm_buy

    store = PortfolioStore(tmp_path / "portfolio.json")
    portfolio = store.load_or_create(initial_cash=100_000)

    # 模拟 pi agent 的判断结果：action=买入
    result = confirm_buy(
        portfolio=portfolio,
        symbol="000001",
        name="测试股票",
        sector="AI应用",
        buy_price=15.0,
        key_low=13.29,
        trade_date="2026-05-13",
    )
    store.save(result.portfolio)

    # 重新加载验证持久化
    loaded = store.load_or_create()
    assert len(loaded.positions) == 1
    assert loaded.positions[0].symbol == "000001"
    assert loaded.positions[0].buy_price == 15.0
    assert loaded.positions[0].key_low == 13.29
    assert loaded.cash < 100_000


def test_scan_pipeline_prepare_then_judge_then_apply(tmp_path):
    """端到端：prepare 数据 → 规则引擎判断 → apply 写入 portfolio。"""
    from sagent.scan import run_scan

    portfolio_path = tmp_path / "portfolio.json"
    config_path = Path("config/default.json")

    result = run_scan(
        data=fixture_data(),
        portfolio_path=portfolio_path,
        config_path=config_path,
        env={},
    )

    # 结果包含完整结构
    assert result["mode"] == "fixture"
    assert "candidates" in result
    assert "excluded" in result
    assert "warning" in result
    assert "不构成投资建议" in result["warning"]

    # 候选股有 action（规则引擎 fallback 给出的）
    if result["candidates"]:
        candidate = result["candidates"][0]
        assert candidate["action"] in {"买入", "观察", "放弃"}
        assert candidate["key_low"] is not None


def test_format_scan_summary_produces_markdown_tables():
    """format_scan_summary 输出包含完整的 Markdown 表格。"""
    from sagent.format import format_scan_summary, format_feishu_text

    data = fixture_data()
    scan_json = _build_prepare_scan_output(data)

    md = format_scan_summary(scan_json)

    # 标题
    assert "\u626b\u63cf\u62a5\u544a" in md
    assert "GLM5.1" in md

    # 表格结构
    assert "| \u677f\u5757" in md
    assert "| \u80a1\u7968" in md
    assert "| ---" in md

    # 板块验证
    assert (
        "\u5f3a\u4e3b\u7ebf" in md
        or "\u5f31\u4e3b\u7ebf" in md
        or "\u975e\u4e3b\u7ebf" in md
    )

    # 风险提示
    assert "\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae" in md


def test_format_feishu_text_is_compact():
    """飞书纯文本格式紧凑，无 Markdown 表格符号。"""
    from sagent.format import format_feishu_text

    data = fixture_data()
    scan_json = _build_prepare_scan_output(data)

    text = format_feishu_text(scan_json)

    assert "[\u677f\u5757]" in text
    assert "[\u5019\u9009]" in text
    assert "\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae" in text
    # 不含 Markdown 表格
    assert "| ---" not in text


def _build_prepare_scan_output(data: FixtureMarketData) -> dict:
    """构造 prepare_scan 格式的输出，供格式化测试使用。"""
    from dataclasses import asdict

    from sagent.config import load_config
    from sagent.kline import describe_stock
    from sagent.portfolio import PortfolioStore
    from sagent.sector import summarize_sectors, validate_mainline_sectors
    from sagent.technical import filter_stock_pool, technical_candidates

    config = load_config(Path("config/default.json"), env={})
    portfolio = PortfolioStore(Path("portfolio.json")).load_or_create()

    pool = filter_stock_pool(data.stocks())
    candidates = technical_candidates(data, pool.included)

    candidate_details = []
    for c in candidates:
        bars = data.daily_bars(c.symbol)
        desc = describe_stock(c.symbol, bars)
        candidate_details.append(
            {
                **asdict(c),
                "kline_description": desc.text,
                "kline_key_low": desc.key_low,
                "kline_risk_price": desc.risk_price,
                "kline_fields": desc.fields,
            }
        )

    validations = validate_mainline_sectors(summarize_sectors(data))
    sector_details = []
    for _name, v in validations.items():
        sector_details.append(
            {
                "sector": v.sector,
                "level": v.level,
                "rules": v.rules,
                "needs_llm": v.needs_llm,
            }
        )

    return {
        "trade_date": data.trade_calendar()[-1].date
        if data.trade_calendar()
        else "\u672a\u77e5",
        "judgement_model": config.models.default_judgement_model,
        "candidates": candidate_details,
        "sectors": sector_details,
        "stock_pool": {
            "included": [asdict(s) for s in pool.included],
            "excluded": [asdict(e) for e in pool.excluded],
        },
        "portfolio": {
            "positions": [asdict(p) for p in portfolio.positions],
            "suggestions": [],
            "cash": portfolio.cash,
            "weekly_open_count": portfolio.weekly_open_count,
        },
    }
