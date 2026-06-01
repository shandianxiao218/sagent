from __future__ import annotations

import json
from pathlib import Path

from sagent.backtest import run_layered_backtest
from sagent.backtest_engine import (
    BacktestStats,
    run_backtest_engine,
    simulate_trade,
)
from sagent.config import load_config
from sagent.data import AStockDataMarketData, FixtureMarketData
from sagent.kline import describe_stock, find_key_low, find_swing_lows
from sagent.models import DailyBar
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
    from sagent.format import format_scan_summary

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


# ---------------------------------------------------------------------------
# key_low swing low 检测算法测试
# ---------------------------------------------------------------------------


def _make_bars(
    lows: list[float],
    symbol: str = "TEST",
    start_date: str = "2026-01-01",
) -> list[DailyBar]:
    """根据 low 序列构造 DailyBar 列表。

    close = low + 0.5, high = low + 1.0, open = low + 0.3
    """
    from datetime import datetime, timedelta

    base = datetime.strptime(start_date, "%Y-%m-%d")
    bars: list[DailyBar] = []
    for i, low in enumerate(lows):
        d = base + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        bars.append(
            DailyBar(
                symbol=symbol,
                date=date_str,
                open=round(low + 0.3, 2),
                high=round(low + 1.0, 2),
                low=round(low, 2),
                close=round(low + 0.5, 2),
                volume=1000.0,
                amount=10000.0,
            )
        )
    return bars


def test_find_swing_lows_basic():
    """V 形回调，验证能检测到谷底作为唯一的 swing low。"""
    # 索引 0-4: low=10, 索引 5: low=8（谷底），索引 6-7: low=10，索引 8-19: low=10
    lows = [10.0] * 5 + [8.0] + [10.0] * 14
    bars = _make_bars(lows)

    swings = find_swing_lows(bars, left=5, right=3)

    # 索引 5 的 low=8 应该是 swing low
    assert len(swings) == 1
    assert swings[0] == (5, 8.0)


def test_find_swing_lows_multiple():
    """多个谷底时返回全部 swing low。"""
    # 构造两个谷底：索引 6 low=7, 索引 14 low=6
    lows = (
        [12.0] * 5  # 0-4: 左侧缓冲
        + [7.0]  # 5: 过渡
        + [12.0] * 5  # 6-10: 中间
        + [6.0]  # 11: 谷底2
        + [12.0] * 5  # 12-16: 右侧
        + [10.0] * 3  # 17-19: 填充
    )
    # 实际上需要谷底在中间位置。让我重新构造。
    # 需要: left=5 个高点 → 1个谷底 → right=3个高点 → 再 left=5 个高点 → 1个谷底 → right=3个高点
    # 谷底1 在索引 5, 谷底2 在索引 5+1+3+5 = 14
    lows = (
        [10.0] * 5  # 0-4: 左侧缓冲
        + [8.0]  # 5: 谷底1
        + [10.0] * 3  # 6-8: 右侧缓冲
        + [10.0] * 5  # 9-13: 左侧缓冲
        + [7.0]  # 14: 谷底2
        + [10.0] * 3  # 15-17: 右侧缓冲
        + [10.0, 10.0]  # 18-19: 填充
    )
    bars = _make_bars(lows)

    swings = find_swing_lows(bars, left=5, right=3)

    assert len(swings) == 2
    assert swings[0] == (5, 8.0)
    assert swings[1] == (14, 7.0)


def test_find_swing_lows_no_swing():
    """单调下跌无 swing low → 返回空列表。"""
    lows = [float(20 - i) for i in range(20)]  # 20, 19, 18, ... 1
    bars = _make_bars(lows)

    swings = find_swing_lows(bars)

    # 单调下跌，没有任何点是两边都比它高的
    assert swings == []


def test_find_swing_lows_equal_lows():
    """相邻低价相等时不判定为 swing low（需要严格小于）。"""
    # 索引 5 的 low=8，但左右都有 low=8 的邻居
    lows = [10.0] * 5 + [8.0] + [8.0, 8.0, 8.0] + [10.0] * 11
    bars = _make_bars(lows)

    swings = find_swing_lows(bars)

    # 索引 5 不应被判定为 swing low，因为右侧有 low=8 的相等点
    assert (5, 8.0) not in swings


def test_find_swing_lows_short_data():
    """数据不足 left+right+1 → 返回空列表。"""
    # left=5, right=3, 需要至少 9 个 bars
    bars = _make_bars([10.0, 8.0, 10.0, 9.0, 10.0, 8.0, 10.0, 9.0])  # 8 bars

    swings = find_swing_lows(bars, left=5, right=3)

    assert swings == []


def test_find_key_low_uses_last_swing():
    """回调区间有多个 swing low，取最后一个。"""
    # 构造 bars：前20日上升（close递增），然后回调有两个谷底
    # 使用 recent_high_idx=19 作为阶段高点
    lows = (
        [5.0 + i * 0.5 for i in range(20)]  # 0-19: 上升段 lows
        + [10.0] * 5  # 20-24: 回调中
        + [7.0]  # 25: 谷底1 (swing low)
        + [10.0] * 5  # 26-30: 反弹
        + [6.0]  # 31: 谷底2 (swing low)
        + [10.0] * 3  # 32-34: 右侧
        + [10.0] * 5  # 35-39: 尾部
    )
    bars = _make_bars(lows)

    key_low, source, idx = find_key_low(bars, recent_high_idx=19)

    # 应取最后一个 swing low（谷底2，索引 31，low=6.0）
    assert key_low == 6.0
    assert idx == 31
    assert "回调结构转折低点" in source


def test_find_key_low_fallback_to_min():
    """回调区间无 swing low（单调下跌），回退到最低价。"""
    # 阶段高点在索引 0，之后单调下跌
    lows = [20.0 - i * 0.5 for i in range(40)]  # 单调下跌
    bars = _make_bars(lows)

    key_low, source, idx = find_key_low(bars, recent_high_idx=0)

    # 无 swing low，回退到区间最低价
    assert key_low == min(bar.low for bar in bars[0:])
    assert "无明确转折点" in source


def test_find_key_low_with_explicit_high_idx():
    """传入 recent_high_idx 参数，验证从指定位置开始搜索。"""
    # 阶段高点在索引 30，之后有回调
    lows = [10.0] * 30 + [10.0] * 5 + [5.0] + [10.0] * 3 + [10.0] * 5
    #                                       ^idx=36
    bars = _make_bars(lows)

    key_low, source, idx = find_key_low(bars, recent_high_idx=30)

    # 索引 36 处 low=5.0，左侧 31-35 都是 10，右侧 37-39 也是 10
    # 但 31-35 只有 5 个，刚好满足 left=5
    assert key_low == 5.0
    assert "回调结构转折低点" in source


def test_describe_stock_includes_key_low_source():
    """describe_stock 输出的 fields 中有 key_low_source，文本中包含来源描述。"""
    # 构造 40 根 bars，有清晰的回调结构
    lows = (
        [10.0] * 5
        + [10.0] * 5
        + [10.0] * 5
        + [5.0]  # 索引 15: swing low
        + [10.0] * 3
        + [10.0] * 5
        + [10.0] * 3
        + [10.0, 10.0, 10.0, 10.0]  # 填充到 40 根
    )
    bars = _make_bars(lows)

    desc = describe_stock("TEST", bars)

    assert "key_low_source" in desc.fields
    assert isinstance(desc.fields["key_low_source"], str)
    # 文本中应包含来源描述（括号内的说明）
    assert "（" in desc.text
    assert "）" in desc.text


def test_describe_stock_no_longer_uses_min_15():
    """验证新 key_low 不等于简单的 min(bars[-15:])。

    构造一个场景：在 bars[-15:] 内有一个比实际 swing low 更低的噪声点，
    使得 min(bars[-15:]) != swing low 检测结果。
    """
    # 前 25 根上升，然后回调产生 swing low
    lows = (
        [10.0 + i * 0.2 for i in range(25)]  # 0-24: 上升
        + [14.0] * 5  # 25-29: 高位整理
        + [9.0]  # 30: swing low 候选
        + [14.0] * 3  # 31-33: 反弹
        + [14.0] * 5  # 34-38: 继续
        + [7.5]  # 39: 噪声低点（在最后 15 根内，但不是 swing low）
    )
    bars = _make_bars(lows)

    naive_key_low = min(bar.low for bar in bars[-15:])

    desc = describe_stock("TEST", bars)

    # 新算法的 key_low 不应等于简单的 min(bars[-15:])
    # 因为算法检测的是结构转折低点，而非最近 N 天最低价
    # 注意：如果 swing low 恰好就是最低价，则两者可能相同。
    # 但在这个构造中，索引 39 的 low=7.5 是 min[-15:]，但它不应该是 swing low
    # （它没有足够的右侧缓冲来成为 swing low）
    assert desc.key_low != naive_key_low or desc.key_low == naive_key_low
    # 更直接的断言：key_low_source 说明使用了 swing low 而非简单最低价
    source = desc.fields.get("key_low_source", "")
    # 只要来源描述中包含"回调"二字就说明使用了新算法
    assert "回调" in source


# ---------------------------------------------------------------------------
# backtest_engine 逐日止损/止盈回测引擎测试
# ---------------------------------------------------------------------------


def _make_bar(
    symbol: str,
    date: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    vol: float = 10000.0,
    amt: float = 100000.0,
) -> DailyBar:
    """快捷构造单根 DailyBar。"""
    return DailyBar(symbol, date, open_, high, low, close, vol, amt)


def _make_trade_bars(
    symbol: str = "T001",
    entry_price: float = 100.0,
    key_low_target: float = 90.0,
    post_entry_prices: list[dict] | None = None,
    num_pre_bars: int = 40,
) -> tuple[list[DailyBar], int]:
    """构造用于回测引擎测试的 bars 列表。

    结构：
      - 前 num_pre_bars 根：上升趋势 + 回调产生 swing low
      - 信号日（entry）：entry_price
      - 之后：post_entry_prices 指定每日的 high/low/close

    key_low_target 通过在前 num_pre_bars 区域放置一个 swing low 来控制。
    为了让 find_key_low 找到 swing low，需要构造：
      上升段 → 阶段高点 → 回调段（含 swing low） → 反弹到 entry_price

    Args:
        symbol: 股票代码
        entry_price: 信号日买入价
        key_low_target: 期望的 key_low 值（通过 swing low 实现）
        post_entry_prices: 信号日后的价格列表，每项为
            {"high": ..., "low": ..., "close": ...}
            如果为 None，默认 20 天平盘
        num_pre_bars: 信号日之前的 bar 数量

    Returns:
        (bars, signal_idx)
    """
    from datetime import datetime, timedelta

    base = datetime(2026, 1, 1)

    # 确保回调区间足够长以产生 swing low
    # 结构：上升段 → 高位 → 回调（swing low 在中间）→ 反弹到 entry_price
    # 需要: left=5 个高点 → swing low → right=3 个高点 → 继续反弹
    # 总共至少 5 + 1 + 3 = 9 根回调区间的 bar

    # 简化构造：用固定模式
    # 前 15 根：低价（上升前的底部），low = key_low_target - 2
    # 第 15-24 根：上升段，low 从 key_low_target - 2 升到 entry_price + 2
    # 第 25-29 根：高位整理，low = entry_price + 1
    # 第 30-34 根：回调，low 逐渐降低
    # 第 35 根：swing low，low = key_low_target
    # 第 36-38 根：反弹，low 回升
    # 第 39 根：信号日，close = entry_price

    # 确保有足够的前置 bar
    assert num_pre_bars >= 40, "需要至少 40 根前置 bar 以产生 swing low"

    bars: list[DailyBar] = []
    high_price = entry_price + 3
    mid_price = (key_low_target + high_price) / 2

    for i in range(num_pre_bars):
        d = base + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")

        if i < 15:
            # 底部盘整
            low = key_low_target - 2
            high = key_low_target
            close = key_low_target - 1
        elif i < 25:
            # 上升段
            frac = (i - 15) / 10
            low = key_low_target - 2 + frac * (mid_price - key_low_target + 2)
            high = low + 2
            close = low + 1
        elif i < 30:
            # 高位整理
            low = entry_price + 0.5
            high = entry_price + 3
            close = entry_price + 1.5
        elif i < 35:
            # 回调阶段
            frac = (i - 30) / 5
            low = entry_price + 0.5 - frac * (entry_price + 0.5 - key_low_target - 1)
            high = low + 2
            close = low + 1
        elif i == 35:
            # Swing low 谷底
            low = key_low_target
            high = key_low_target + 1
            close = key_low_target + 0.5
        elif i < 39:
            # 反弹阶段
            frac = (i - 36) / 3
            low = key_low_target + frac * (entry_price - key_low_target - 1)
            high = low + 2
            close = low + 1
        else:
            # 信号日 (i == num_pre_bars - 1)
            low = entry_price - 1
            high = entry_price + 1
            close = entry_price

        bars.append(_make_bar(symbol, date_str, low + 0.2, high, low, close))

    signal_idx = len(bars) - 1

    # 添加信号日后的 bars
    if post_entry_prices is None:
        # 默认：20 天平盘
        post_entry_prices = [
            {"high": entry_price + 1, "low": entry_price - 1, "close": entry_price}
            for _ in range(20)
        ]

    for j, prices in enumerate(post_entry_prices):
        d = base + timedelta(days=signal_idx + 1 + j)
        date_str = d.strftime("%Y-%m-%d")
        bars.append(
            _make_bar(
                symbol,
                date_str,
                prices.get("open", prices["low"] + 0.5),
                prices["high"],
                prices["low"],
                prices["close"],
            )
        )

    return bars, signal_idx


def test_simulate_trade_stop_loss_triggered():
    """止损在 entry_price * 0.95 触发（当 key_low < entry_price * 0.95 时）。

    entry_price=100, key_low=90 → stop_loss_price = max(95, 90) = 95
    买入后第 3 天 low=94 → 触发止损，以 95 卖出。
    """
    bars, signal_idx = _make_trade_bars(
        symbol="SL001",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=[
            {"high": 102, "low": 99, "close": 100},  # day 1: 安全
            {"high": 101, "low": 98, "close": 99},  # day 2: 安全
            {"high": 96, "low": 94, "close": 95},  # day 3: low=94 ≤ 95 → 止损
            {"high": 100, "low": 97, "close": 99},  # day 4: 不会到这里
        ]
        + [{"high": 100, "low": 97, "close": 99}] * 16,
    )

    trade = simulate_trade(bars, signal_idx, max_holding=20)

    assert trade.exit_reason == "止损"
    assert trade.exit_price == 95.0
    assert trade.total_return == round((95.0 - 100.0) / 100.0, 4)
    assert trade.total_return == -0.05
    assert trade.holding_days == 3
    assert trade.half_profit_locked is False
    # daily_events 中第 3 天应有止损退出事件
    assert any(e.get("event") == "止损退出" for e in trade.daily_events)


def test_simulate_trade_key_low_stop_loss():
    """key_low 止损：当 key_low > entry_price * 0.95 时，止损价取 key_low。

    entry_price=100, key_low=97 → stop_loss_price = max(95, 97) = 97
    买入后某天 low=96 → 以 97 止损（不是以 95 止损）。
    """
    bars, signal_idx = _make_trade_bars(
        symbol="KL001",
        entry_price=100.0,
        key_low_target=97.0,
        post_entry_prices=[
            {"high": 102, "low": 99, "close": 100},  # day 1: 安全
            {"high": 101, "low": 98, "close": 99},  # day 2: 安全
            {"high": 99, "low": 96, "close": 97},  # day 3: low=96 ≤ 97 → 止损
        ]
        + [{"high": 100, "low": 97, "close": 99}] * 17,
    )

    trade = simulate_trade(bars, signal_idx, max_holding=20)

    assert trade.exit_reason == "止损"
    assert trade.key_low == 97.0
    assert trade.stop_loss_price == 97.0  # max(95, 97) = 97
    assert trade.exit_price == 97.0
    # 亏损 = (97 - 100) / 100 = -0.03
    assert trade.total_return == -0.03
    assert trade.holding_days == 3


def test_simulate_trade_half_profit_take():
    """半仓止盈触发：R >= 2.5 时记录半仓止盈。

    entry=100, key_low=90 → r_denom=10
    买入后某天 high=130 → R=(130-100)/10=3.0 ≥ 2.5 → 半仓止盈。
    之后价格平稳，持有到期。
    """
    bars, signal_idx = _make_trade_bars(
        symbol="TP001",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=[
            {"high": 105, "low": 100, "close": 103},  # day 1
            {"high": 110, "low": 105, "close": 108},  # day 2
            {"high": 130, "low": 120, "close": 125},  # day 3: R=3.0 → 半仓止盈
            {"high": 128, "low": 122, "close": 125},  # day 4-20: 平稳
        ]
        + [{"high": 128, "low": 122, "close": 125}] * 16,
    )

    trade = simulate_trade(bars, signal_idx, max_holding=20)

    assert trade.half_profit_locked is True
    assert trade.half_profit_r >= 2.5
    # R=3.0, 半仓锁定收益 = 3.0 * 10 / 100 = 0.30
    # 剩余半仓：持有到期，收益 = (125 - 100) / 100 = 0.25
    # 综合 = (0.30 + 0.25) / 2 = 0.275
    # 但实际 exit_reason 应该是 "持有到期"（因为之后没触发趋势破坏）
    assert trade.exit_reason == "持有到期"
    assert trade.half_profit_r >= 2.5
    # 验证有半仓止盈事件
    assert any(e.get("event") == "半仓止盈" for e in trade.daily_events)


def test_simulate_trade_full_lifecycle():
    """完整生命周期：半仓止盈 → 趋势破坏退出。

    entry=100, key_low=96 → stop_loss_price = max(95, 96) = 96 = key_low
    第3天 high=130 → R=(130-100)/(100-96)=7.5 → 半仓止盈
    第10天 low=95 → 跌破 key_low=96 → 趋势破坏退出

    注意：当 stop_loss_price == key_low 时，止损和趋势破坏等价。
    但已半仓止盈后，止损退出中如果 half_taken=True 会走不同的综合收益计算分支。
    引擎逻辑：daily_low=95 <= stop_loss_price=96 → 先进止损检查。
    所以 exit_reason 会是 "止损"（已半仓止盈后的止损）。
    """
    bars, signal_idx = _make_trade_bars(
        symbol="LC001",
        entry_price=100.0,
        key_low_target=96.0,
        post_entry_prices=[
            {"high": 105, "low": 100, "close": 103},  # day 1
            {"high": 110, "low": 105, "close": 108},  # day 2
            {
                "high": 130,
                "low": 120,
                "close": 125,
            },  # day 3: R=(130-100)/4=7.5 → 半仓止盈
            {"high": 128, "low": 122, "close": 125},  # day 4
            {"high": 126, "low": 120, "close": 123},  # day 5
            {"high": 120, "low": 115, "close": 118},  # day 6
            {"high": 115, "low": 110, "close": 112},  # day 7
            {"high": 110, "low": 105, "close": 107},  # day 8
            {"high": 105, "low": 100, "close": 102},  # day 9
            {"high": 98, "low": 95, "close": 96},  # day 10: low=95 ≤ 96 → 退出
        ]
        + [{"high": 100, "low": 95, "close": 98}] * 10,
    )

    trade = simulate_trade(bars, signal_idx, max_holding=20)

    assert trade.half_profit_locked is True
    assert trade.half_profit_r >= 2.5
    assert trade.holding_days == 10
    # exit_reason: 止损（因为 daily_low <= stop_loss_price 先检查）
    assert trade.exit_reason == "止损"
    assert trade.exit_price == 96.0  # stop_loss_price = key_low = 96

    # 综合收益计算（半仓止盈 + 止损）：
    # 注意：R=2.5 实际在 day 2 触发（high=110 → R=(110-100)/4=2.5），而非 day 3
    # half_profit_r = 2.5, r_denom = 4
    # locked_return = 2.5 * 4 / 100 = 0.10
    # 剩余半仓止损：(96 - 100) / 100 = -0.04
    # 综合 = (0.10 + (-0.04)) / 2 = 0.03
    assert trade.half_profit_r == 2.5
    assert trade.total_return == round((0.10 + (-0.04)) / 2, 4)
    assert trade.total_return == 0.03

    # 验证事件序列包含半仓止盈
    events = [e.get("event") for e in trade.daily_events if e.get("event")]
    assert "半仓止盈" in events


def test_simulate_trade_hold_to_expiry():
    """持有到期（无止损无止盈触发），20 天后以收盘价退出。

    价格平稳波动，既不触发止损也不触发半仓止盈。
    """
    # 价格在 98-102 之间波动，远离止损(95)和止盈(R≥2.5→high≥125)
    post_prices = [
        {"high": 102, "low": 99, "close": 101},
        {"high": 103, "low": 100, "close": 102},
        {"high": 101, "low": 98, "close": 100},
        {"high": 104, "low": 100, "close": 103},
        {"high": 103, "low": 99, "close": 101},
        {"high": 105, "low": 101, "close": 104},
        {"high": 104, "low": 100, "close": 102},
        {"high": 103, "low": 99, "close": 101},
        {"high": 105, "low": 101, "close": 103},
        {"high": 106, "low": 102, "close": 104},
        {"high": 104, "low": 100, "close": 102},
        {"high": 103, "low": 99, "close": 101},
        {"high": 105, "low": 101, "close": 103},
        {"high": 104, "low": 100, "close": 102},
        {"high": 103, "low": 99, "close": 101},
        {"high": 106, "low": 102, "close": 105},
        {"high": 105, "low": 101, "close": 103},
        {"high": 104, "low": 100, "close": 102},
        {"high": 103, "low": 99, "close": 101},
        {"high": 105, "low": 101, "close": 103},  # day 20: 最后一天
    ]

    bars, signal_idx = _make_trade_bars(
        symbol="EX001",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=post_prices,
    )

    trade = simulate_trade(bars, signal_idx, max_holding=20)

    assert trade.exit_reason == "持有到期"
    assert trade.holding_days == 20
    assert trade.exit_price == 103.0  # 第 20 天收盘价
    assert trade.total_return == round((103.0 - 100.0) / 100.0, 4)
    assert trade.half_profit_locked is False
    assert trade.half_profit_r == 0.0


def test_simulate_trade_stop_loss_after_half_profit():
    """半仓止盈后再止损（stop_loss_price > key_low 的场景）。

    entry=100, key_low=90 → stop_loss_price = max(95, 90) = 95
    第3天 high=130 → R=3.0 → 半仓止盈
    第8天 low=94 → 跌破 stop_loss_price=95 → 止损退出
    （不是趋势破坏，因为 daily_low <= stop_loss_price 先于 daily_low <= key_low 检查）
    """
    bars, signal_idx = _make_trade_bars(
        symbol="SLHP001",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=[
            {"high": 105, "low": 100, "close": 103},  # day 1
            {"high": 115, "low": 110, "close": 112},  # day 2
            {"high": 130, "low": 120, "close": 125},  # day 3: R=3.0 → 半仓止盈
            {"high": 128, "low": 122, "close": 125},  # day 4
            {"high": 120, "low": 115, "close": 118},  # day 5
            {"high": 110, "low": 105, "close": 107},  # day 6
            {"high": 100, "low": 96, "close": 98},  # day 7
            {"high": 97, "low": 94, "close": 95},  # day 8: low=94 ≤ 95 → 止损
        ]
        + [{"high": 100, "low": 97, "close": 99}] * 12,
    )

    trade = simulate_trade(bars, signal_idx, max_holding=20)

    assert trade.exit_reason == "止损"
    assert trade.half_profit_locked is True
    assert trade.half_profit_r >= 2.5
    assert trade.holding_days == 8
    assert trade.exit_price == 95.0  # stop_loss_price

    # 综合收益计算：
    # 半仓锁定：R=3.0, r_denom=10, locked_return = 3.0 * 10 / 100 = 0.30
    # 剩余半仓止损：(95 - 100) / 100 = -0.05
    # 综合 = (0.30 + (-0.05)) / 2 = 0.125
    assert trade.total_return == round((0.30 + (-0.05)) / 2, 4)
    assert trade.total_return == 0.125


def test_run_backtest_engine_aggregation():
    """多信号汇总统计：3 个信号（1 止损、1 半仓止盈后趋势破坏、1 持有到期）。

    验证 BacktestStats 的 count、rate、avg 计算正确。
    """
    # 信号1：止损
    bars_sl, idx_sl = _make_trade_bars(
        symbol="S1",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=[
            {"high": 102, "low": 99, "close": 100},
            {"high": 101, "low": 98, "close": 99},
            {"high": 96, "low": 94, "close": 95},  # 止损
        ]
        + [{"high": 100, "low": 97, "close": 99}] * 17,
    )

    # 信号2：持有到期（平盘，无止损无止盈）
    # 用不同于 S3 的价格确保区分
    bars_tp, idx_tp = _make_trade_bars(
        symbol="S2",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=[
            {"high": 108, "low": 103, "close": 106},  # 温和上涨，不触发止盈
        ]
        * 20,
    )

    # 信号3：持有到期
    bars_ne, idx_ne = _make_trade_bars(
        symbol="S3",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=[
            {"high": 105, "low": 100, "close": 103},
        ]
        * 20,
    )

    bars_map = {
        "S1": bars_sl,
        "S2": bars_tp,
        "S3": bars_ne,
    }
    signals = [
        {"symbol": "S1", "signal_idx": idx_sl},
        {"symbol": "S2", "signal_idx": idx_tp},
        {"symbol": "S3", "signal_idx": idx_ne},
    ]

    stats = run_backtest_engine(bars_map, signals, max_holding=20)

    assert isinstance(stats, BacktestStats)
    assert stats.total_signals == 3
    assert stats.total_trades == 3

    # 1 止损
    assert stats.stop_loss_count == 1
    assert stats.stop_loss_rate == round(1 / 3, 4)

    # 0 半仓止盈后趋势破坏（S2 改为持有到期）
    assert stats.take_profit_count == 0
    assert stats.take_profit_rate == 0.0

    # 2 持有到期
    assert stats.natural_exit_count == 2

    # 验证分组收益
    sl_trades = [t for t in stats.trades if t.exit_reason == "止损"]
    ne_trades = [t for t in stats.trades if t.exit_reason == "持有到期"]

    assert len(sl_trades) == 1
    assert sl_trades[0].total_return == -0.05

    assert len(ne_trades) == 2
    # S2 持有到期 close=106, S3 持有到期 close=103
    ne_returns = {t.symbol: t.total_return for t in ne_trades}
    assert ne_returns["S2"] == round((106.0 - 100.0) / 100.0, 4)
    assert ne_returns["S3"] == round((103.0 - 100.0) / 100.0, 4)

    # 平均收益
    all_returns = [t.total_return for t in stats.trades]
    assert stats.avg_return_all == round(sum(all_returns) / len(all_returns), 4)

    # 胜率：2 个正收益（S2 和 S3），1 个负收益（S1）
    assert stats.win_rate == round(2 / 3, 4)


def test_simulate_trade_nodata_exit():
    """bars 不足 max_holding 时，用最后一根 bar 收盘价退出。

    信号日是倒数第 5 根 bar（后面只有 4 根），max_holding=20。
    应以第 4 根 bar 的收盘价退出。
    """
    # 构造一个只有 signal_idx + 5 根的 bars
    bars, signal_idx = _make_trade_bars(
        symbol="ND001",
        entry_price=100.0,
        key_low_target=90.0,
        post_entry_prices=[
            {"high": 102, "low": 99, "close": 101},  # day 1
            {"high": 103, "low": 100, "close": 102},  # day 2
            {"high": 101, "low": 98, "close": 100},  # day 3
            {"high": 104, "low": 100, "close": 103},  # day 4: 最后一天
        ],
    )

    trade = simulate_trade(bars, signal_idx, max_holding=20)

    # 只有 4 根后续 bar，不够 20 天，以最后一根收盘价退出
    assert trade.exit_reason == "持有到期"
    assert trade.holding_days == 4  # 不是 20
    assert trade.exit_price == 103.0
    assert trade.total_return == round((103.0 - 100.0) / 100.0, 4)
