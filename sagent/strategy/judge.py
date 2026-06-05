"""LLM 规则引擎判断模块。

从 technical.py 拆分而来，包含 simulated_llm_judge：
基于回测数据驱动的规则引擎，模拟 LLM 形态判断。
"""

from __future__ import annotations

from .params import JudgeParams

# 模块级默认参数
_judge_params = JudgeParams()


def simulated_llm_judge(
    signal: dict,
    kline_desc_text: str,
    key_low: float,
    jp: JudgeParams | None = None,
) -> dict:
    """模拟 LLM 形态判断逻辑（规则引擎 v3 — 回测数据驱动）。

    基于 2025-12~2026-05 回测 165 笔交易的关键发现：
    - 涨幅 80%+ 胜率 50-55%（趋势强劲），不应因涨幅高而放弃
    - 涨幅 50-80% 反而胜率仅 34%
    - 真正的杀手是：缩量突破（量比<0.8）+ 深回撤（>55%）
    - 放量（>1.2x）+ 浅回调（<40%）是最强组合

    决策逻辑：
    1. 回撤 >55% → 放弃（趋势破坏）
    2. 量比 <0.7 + 无明确转折点 → 放弃（突破无确认）
    3. 放量 >1.2 + 回调 <42% → 买入（最强信号）
    4. 放量 >1.0 + 回调 <50% + 涨幅 >80% → 买入（强趋势回踩）
    5. 量比 0.7-1.0 → 观察（需确认）
    6. 其他 → 观察
    """
    p = jp or _judge_params
    rise = signal["rise_60d"]
    pullback = signal["pullback_ratio"]

    # 提取量比（从 K 线描述中）
    volume_ratio = 1.0
    if "均量的" in kline_desc_text:
        try:
            idx_vr = kline_desc_text.index("均量的")
            segment = kline_desc_text[idx_vr + 3 : idx_vr + 10]
            volume_ratio = float(segment.split("倍")[0])
        except (ValueError, IndexError):
            pass

    # ── 检测是否有明确结构转折点 ──
    has_turn = "结构转折低点" in kline_desc_text or "更低的低点" in kline_desc_text

    reasons = []
    action = "观察"
    confidence = 0.5

    # ── 1. 硬性拒绝（趋势已破坏） ─────────────────────────
    if pullback > p.pullback_abandon:
        action = "放弃"
        confidence = p.confidence_abandon_deep
        reasons.append(f"回撤{pullback:.0%}过深，趋势可能已破坏")
    # ── 2. 缩量 + 无转折点 → 放弃 ─────────────────────────
    elif volume_ratio < p.volume_abandon and not has_turn:
        action = "放弃"
        confidence = p.confidence_abandon_volume
        reasons.append(f"缩量{volume_ratio:.1f}倍且无结构转折点，突破无确认")
    # ── 3. 最强信号：放量 + 浅回调 → 买入 ─────────────────
    elif volume_ratio >= p.volume_strong and pullback <= p.pullback_strong:
        action = "买入"
        confidence = p.confidence_strong
        reasons.append(f"放量{volume_ratio:.1f}倍确认突破，回调{pullback:.0%}健康")
    # ── 4. 强趋势回踩：涨幅大 + 放量 + 回调适中 → 买入 ────
    elif (
        rise > p.rise_trend
        and volume_ratio >= p.volume_trend
        and pullback <= p.pullback_trend
    ):
        action = "买入"
        confidence = p.confidence_trend
        reasons.append(
            f"强趋势涨幅{rise:.0%}回踩，放量{volume_ratio:.1f}倍，回调{pullback:.0%}"
        )
    # ── 5. 温和涨幅 + 放量 + 浅回调 → 买入 ─────────────────
    elif (
        rise <= p.rise_trend
        and volume_ratio >= p.volume_trend
        and pullback <= p.pullback_gentle
    ):
        action = "买入"
        confidence = p.confidence_gentle
        reasons.append(
            f"涨幅{rise:.0%}温和，放量{volume_ratio:.1f}倍，回调{pullback:.0%}浅"
        )
    # ── 6. 缩量但有明确转折 → 观察（有希望） ───────────────
    elif volume_ratio < p.volume_trend and has_turn:
        action = "观察"
        confidence = p.confidence_observe_turn
        reasons.append(f"缩量{volume_ratio:.1f}倍但有结构转折点，需放量确认")
    # ── 7. 缩量且无转折 → 观察（偏弱） ─────────────────────
    else:
        action = "观察"
        confidence = p.confidence_observe_weak
        reasons.append(
            f"量能{volume_ratio:.1f}倍偏弱，涨幅{rise:.0%}，回撤{pullback:.0%}"
        )

    return {
        "action": action,
        "reason": "；".join(reasons),
        "confidence": confidence,
        "key_low": key_low,
        "volume_ratio": volume_ratio,
    }
