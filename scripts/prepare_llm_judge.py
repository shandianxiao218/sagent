#!/usr/bin/env python3
"""从回测结果中提取信号详情，获取K线并生成描述，供LLM盲判。

输出 JSON，每个信号包含 K 线描述和 forward performance（forward 数据在 _forward 字段，对LLM隐藏）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.kline import describe_stock  # noqa: E402
from sagent.models import DailyBar  # noqa: E402


def fetch_bars(symbol: str, offset: int = 350) -> list[DailyBar]:
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    frame = client.bars(symbol=symbol, category=4, offset=offset)
    if frame is None or frame.empty:
        return []
    bars = []
    for idx, row in frame.iterrows():
        date_str = str(row.get("datetime", idx))
        bars.append(
            DailyBar(
                symbol=symbol,
                date=date_str[:10],
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("vol", 0)),
                amount=float(row.get("amount", 0)),
            )
        )
    return bars


def find_signal_idx(bars: list[DailyBar], signal_date: str, entry_price: float) -> int:
    """根据信号日期和入场价定位信号在 bars 中的位置。"""
    for i, bar in enumerate(bars):
        if bar.date == signal_date and abs(bar.close - entry_price) < 0.05:
            return i
    # 宽松匹配：只匹配日期
    for i, bar in enumerate(bars):
        if bar.date == signal_date:
            return i
    return -1


def main() -> None:
    backtest_path = Path(ROOT / "backtest_result_v2.json")
    result = json.loads(backtest_path.read_text(encoding="utf-8"))

    # 合并所有唯一信号
    seen = set()
    all_signals = []
    for s in result.get("top_winners", []) + list(
        reversed(result.get("top_losers", []))
    ):
        key = (s["symbol"], s["date"])
        if key not in seen:
            seen.add(key)
            all_signals.append(s)

    print(f"共 {len(all_signals)} 个唯一信号", file=sys.stderr)

    output_signals = []
    for i, sig in enumerate(all_signals):
        symbol = sig["symbol"]
        name = sig["name"]
        signal_date = sig["date"]
        entry_price = sig["entry"]

        print(
            f"  [{i + 1}/{len(all_signals)}] {symbol} {name} {signal_date}...",
            file=sys.stderr,
        )

        try:
            bars = fetch_bars(symbol, offset=350)
        except Exception:
            print("    获取失败", file=sys.stderr)
            continue

        if len(bars) < 260:
            print(f"    K线不足: {len(bars)}", file=sys.stderr)
            continue

        idx = find_signal_idx(bars, signal_date, entry_price)
        if idx < 0:
            print("    未找到信号位置", file=sys.stderr)
            continue

        # 只取信号日之前的 bars 生成描述（模拟真实场景）
        window_bars = bars[: idx + 1]
        desc = describe_stock(symbol, window_bars)

        # 计算 forward（已有，但重新验证）
        entry = bars[idx].close
        fwd = {}
        for w in (5, 10, 20):
            target = idx + w
            if target < len(bars):
                fwd[f"return_{w}d"] = round((bars[target].close - entry) / entry, 4)
            else:
                fwd[f"return_{w}d"] = None

        # 最大回撤
        peak = entry
        max_dd = 0.0
        end = min(idx + 20, len(bars))
        for j in range(idx + 1, end):
            if bars[j].high > peak:
                peak = bars[j].high
            dd = (peak - bars[j].low) / peak
            if dd > max_dd:
                max_dd = dd
        fwd["max_drawdown_20d"] = round(max_dd, 4)

        # 分类
        r20 = fwd.get("return_20d")
        mdd = fwd.get("max_drawdown_20d", 0)
        if r20 is not None and r20 > 0.10 and mdd < 0.12:
            label = "正例"
        elif r20 is not None and (r20 < -0.05 or (r20 > 0 and mdd > 0.15)):
            label = "反例"
        else:
            label = "边界"

        output_signals.append(
            {
                "id": f"S-{i + 1:02d}",
                "symbol": symbol,
                "name": name,
                "signal_date": signal_date,
                "entry_price": entry,
                "kline_description": desc.text,
                "key_low": desc.key_low,
                "metrics": {
                    "rise_60d": sig["rise_60d"],
                    "pullback_ratio": sig["pullback"],
                },
                "_forward": fwd,
                "_auto_label": label,
            }
        )

    output = {
        "version": "1.0",
        "description": "方案A回测数据：27个量化粗筛信号的K线描述。LLM需对每个信号做形态判断（买入/观察/放弃）。_forward和_auto_label对LLM隐藏。",
        "signals": output_signals,
    }

    out_path = ROOT / "backtest_llm_judge_input.json"
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n已写入 {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
