from __future__ import annotations

from statistics import mean

from .models import DailyBar, KlineDescription


def describe_stock(
    symbol: str, bars: list[DailyBar], max_chars: int = 900
) -> KlineDescription:
    if len(bars) < 30:
        raise ValueError("K线数据不足，至少需要30个交易日")
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    current = closes[-1]
    ma20 = mean(closes[-20:])
    ma60 = mean(closes[-60:]) if len(closes) >= 60 else mean(closes)
    recent_high = max(closes[-30:])
    key_low = min(bar.low for bar in bars[-15:])
    volume_ratio = volumes[-1] / mean(volumes[-10:]) if mean(volumes[-10:]) else 0
    breakout = current >= max(closes[-8:])
    pullback_ratio = (recent_high - key_low) / recent_high if recent_high else 0
    text = (
        f"{symbol} 当前价格 {current:.2f}，位于20日均线 {ma20:.2f} 和60日均线 {ma60:.2f} 附近；"
        f"趋势上，前期形成明显上升波段，近期从阶段高点 {recent_high:.2f} 回调至候选关键低点 {key_low:.2f}；"
        f"回调幅度约 {pullback_ratio:.1%}，近几日开始回升并{'尝试突破' if breakout else '尚未突破'}短期回调趋势；"
        f"成交量为近10日均量的 {volume_ratio:.2f} 倍，需关注突破是否放量确认；"
        f"风险位置为买点前关键低点 {key_low:.2f}，跌破则形态无效。"
    )
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return KlineDescription(
        symbol=symbol,
        text=text,
        key_low=round(key_low, 2),
        risk_price=round(key_low, 2),
        fields={
            "current": current,
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "recent_high": recent_high,
            "key_low": round(key_low, 2),
            "volume_ratio": round(volume_ratio, 2),
            "breakout": breakout,
        },
    )
