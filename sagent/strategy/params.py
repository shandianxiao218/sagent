"""策略参数集中管理。

所有策略阈值统一定义在此文件，方便调参和回测对比。
每个参数类对应策略的一个维度。

使用 dataclass 实现，支持构造时覆盖默认值：
    sp = SignalParams(min_rise_60d=0.8)  # 覆盖单个参数
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SignalParams:
    """信号检测参数（check_signal_from_closes / _check_candidate_conditions）。"""

    # ── 均线过滤 ──
    ma_window: int = 250  # MA 窗口（默认 250 日均线）
    min_bars: int = 260  # 最少需要的 K 线根数（ma_window + 10）

    # ── 60 日主升浪检测 ──
    rise_window: int = 60  # 涨幅统计窗口
    min_rise_60d: float = 0.5  # 60 日最低涨幅（50%）

    # ── 回撤健康区间 ──
    pullback_window: int = 30  # 回撤统计窗口（最近 30 日）
    pullback_min: float = 0.15  # 最小回撤比（15%）
    pullback_max: float = 0.50  # 最大回撤比（50%）

    # ── 突破确认 ──
    rebound_days: int = 3  # 连续反弹天数
    breakout_window: int = 8  # 突破前 N 日（不含当日）


@dataclass
class JudgeParams:
    """LLM 规则引擎判断参数（simulated_llm_judge）。"""

    # ── 硬性拒绝 ──
    pullback_abandon: float = 0.55  # 回撤 >55% → 放弃
    volume_abandon: float = 0.70  # 量比 <0.7 + 无转折点 → 放弃

    # ── 最强信号：放量 + 浅回调 → 买入 ──
    volume_strong: float = 1.20  # 放量阈值（均量的 1.2 倍）
    pullback_strong: float = 0.42  # 浅回调阈值（42%）

    # ── 强趋势回踩 → 买入 ──
    rise_trend: float = 0.80  # 强趋势涨幅阈值（80%）
    volume_trend: float = 1.00  # 趋势回踩放量阈值（1.0 倍）
    pullback_trend: float = 0.50  # 趋势回踩最大回调（50%）

    # ── 温和涨幅 + 放量 + 浅回调 → 买入 ──
    pullback_gentle: float = 0.40  # 温和涨幅浅回调（40%）

    # ── 置信度 ──
    confidence_abandon_deep: float = 0.80  # 深回撤放弃置信度
    confidence_abandon_volume: float = 0.70  # 缩量放弃置信度
    confidence_strong: float = 0.78  # 最强信号置信度
    confidence_trend: float = 0.74  # 趋势回踩置信度
    confidence_gentle: float = 0.72  # 温和涨幅置信度
    confidence_observe_turn: float = 0.55  # 有转折点观察置信度
    confidence_observe_weak: float = 0.45  # 偏弱观察置信度
    confidence_default: float = 0.50  # 默认置信度


@dataclass
class StopLossParams:
    """止损/止盈参数（backtest_engine / backtest_portfolio）。"""

    # ── 止损计算 ──
    absolute_stop: float = 0.10  # 绝对止损距离（买入价 -10%）
    key_low_buffer: float = 0.03  # 关键低点缓冲（key_low * (1 - buffer)）
    # 实际止损价 = max(entry_price * (1 - absolute_stop), key_low * (1 - key_low_buffer))

    # ── 半仓止盈 ──
    half_profit_r: float = 2.5  # 半仓止盈触发 R 倍数

    # ── 持有期 ──
    max_holding: int = 20  # 最大持有天数（不含买入日）

    # ── 组合止损（backtest_portfolio 用） ──
    portfolio_stop_pct: float = 0.05  # 组合止损距离（5%）


@dataclass
class ScanParams:
    """回测扫描参数（run_backtest_period.py）。"""

    # ── 数据加载 ──
    min_bars_cache: int = 300  # 缓存最少 K 线根数
    bars_offset: int = 370  # 预加载偏移量（超过一年）

    # ── 扫描窗口 ──
    window_step: int = 3  # 扫描步长（每 3 日检测一次）

    # ── 过滤 ──
    min_avg_amount: float = 100_000_000  # 最低日均成交额（1 亿）
    min_listing_days: int = 120  # 最少上市天数
    min_forward: int = 20  # 最少前向天数（用于统计）

    # ── 采样 ──
    sample_size: int = 1500  # 默认采样数量
    seed: int = 42  # 随机种子

    # ── 成交额窗口 ──
    amount_window: int = 20  # 成交额统计窗口（最近 20 日）

    # ── 统计定义 ──
    good_mdd_threshold: float = 0.15  # 好信号最大回撤阈值
    bad_return_threshold: float = -0.05  # 差信号收益阈值
    stop_loss_return_threshold: float = -0.05  # 止损统计阈值
    strong_return_threshold: float = 0.10  # 强信号收益阈值
    strong_mdd_threshold: float = 0.12  # 强信号最大回撤阈值


@dataclass
class EntryParams:
    """入场确认参数（strategy/entry.py）。

    解决核心痛点：-7 天退出的 61 笔交易胜率 0%。
    """

    require_next_day_confirm: bool = False  # 是否要求次日确认
    confirm_drop: float = 0.02  # 次日收盘不得低于信号日收盘*(1-drop)


@dataclass
class PortfolioParams:
    """组合管理参数（backtest_portfolio.py）。"""

    initial_cash: float = 100_000  # 初始资金
    position_ratio: float = 0.1  # 单笔资金占比（10%）
    max_weekly_open: int = 2  # 每周最多开仓次数
