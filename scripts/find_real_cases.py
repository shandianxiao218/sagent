#!/usr/bin/env python3
"""用真实数据寻找验证案例。

流程：
  1. 从 mootdx 获取 A 股列表
  2. 对每只股票拉取 300 日 K 线
  3. 滑动窗口模拟不同时间点的量化粗筛
  4. 找到符合买入形态的时间点（正例候选）
  5. 找到符合但后续失败的案例（反例候选）
  6. 找到模棱两可的案例（边界候选）
  7. 用 describe_stock() 生成 K 线描述
  8. 输出 JSON 供用户标注

输出到 stdout，重定向到文件即可。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sagent.kline import describe_stock
from sagent.models import DailyBar


def fetch_all_stocks() -> list[dict]:
    """获取 A 股列表。"""
    import akshare as ak

    df = ak.stock_info_a_code_name()
    return df.to_dict("records")


def fetch_bars(symbol: str, offset: int = 350) -> list[DailyBar]:
    """从 mootdx 获取 K 线。"""
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
                volume=float(row.get("volume", 0)),
                amount=float(row.get("amount", 0)),
            )
        )
    return bars


def check_candidate_at(bars: list[DailyBar], idx: int) -> dict | None:
    """在 bars[idx] 位置检查是否满足量化粗筛条件。

    返回 dict（metrics）或 None（不满足）。
    """
    if idx < 260 or idx >= len(bars):
        return None

    window = bars[: idx + 1]
    closes = [b.close for b in window]

    from statistics import mean as _mean

    current = closes[-1]
    ma250 = _mean(closes[-250:])

    # L2: 均线之上
    if current <= ma250:
        return None

    # L3: 60日涨幅
    recent_60 = closes[-60:]
    low_60 = min(recent_60)
    high_60 = max(recent_60)
    rise_60d = (high_60 - low_60) / low_60 if low_60 else 0
    if rise_60d < 0.5:
        return None

    # L4: 回调结构
    pullback = (high_60 - min(closes[-30:])) / max(high_60 - low_60, 0.01)
    if not (0.15 <= pullback <= 0.5):
        return None

    # L5: 突破信号
    recent_rebound = closes[-1] > closes[-2] > closes[-3]
    breakout = closes[-1] > max(closes[-8:-1])
    if not (recent_rebound and breakout):
        return None

    return {
        "above_ma250": True,
        "ma250": round(ma250, 2),
        "rise_60d": round(rise_60d, 4),
        "pullback_ratio": round(pullback, 4),
        "recent_rebound": recent_rebound,
        "breakout": breakout,
        "high_60": round(high_60, 2),
        "low_60": round(low_60, 2),
        "current": round(current, 2),
    }


def forward_performance(bars: list[DailyBar], signal_idx: int) -> dict:
    """计算信号后的 forward performance。"""
    entry_price = bars[signal_idx].close
    result: dict = {"entry_price": round(entry_price, 2)}

    for days in (5, 10, 20):
        target = signal_idx + days
        if target < len(bars):
            ret = (bars[target].close - entry_price) / entry_price
            result[f"return_{days}d"] = round(ret, 4)
        else:
            result[f"return_{days}d"] = None

    # 最大回撤
    peak = entry_price
    max_dd = 0.0
    end = min(signal_idx + 20, len(bars))
    for i in range(signal_idx + 1, end):
        if bars[i].high > peak:
            peak = bars[i].high
        dd = (peak - bars[i].low) / peak
        if dd > max_dd:
            max_dd = dd
    result["max_drawdown_20d"] = round(max_dd, 4)

    return result


def classify_case(fwd: dict) -> str:
    """根据 forward performance 分类案例。"""
    r5 = fwd.get("return_5d")
    r10 = fwd.get("return_10d")
    r20 = fwd.get("return_20d")
    mdd = fwd.get("max_drawdown_20d", 0)

    _ = r5  # 保留供后续规则细化
    _ = r10

    if r20 is None:
        return "边界"

    # 正例：20日收益 > 10%，回撤可控
    if r20 > 0.10 and mdd < 0.12:
        return "正例"
    # 反例：20日亏损
    if r20 < -0.05:
        return "反例"
    # 反例：虽然赚了但中间回撤大
    if r20 > 0 and mdd > 0.15:
        return "反例"
    # 边界
    return "边界"


def main() -> None:
    print("获取 A 股列表...", file=sys.stderr)
    stocks = fetch_all_stocks()
    print(f"共 {len(stocks)} 只股票", file=sys.stderr)

    # 过滤：只要主板（000/001/002/300/600/601/603 开头）
    valid_prefixes = ("000", "001", "002", "300", "600", "601", "603")
    stocks = [s for s in stocks if str(s.get("code", "")).startswith(valid_prefixes)]
    print(f"过滤后 {len(stocks)} 只", file=sys.stderr)

    # 采样：先取 200 只，避免太久
    import random

    random.seed(42)
    sample = random.sample(stocks, min(500, len(stocks)))
    print(f"采样 {len(sample)} 只进行扫描", file=sys.stderr)

    all_findings: list[dict] = []

    for i, stock in enumerate(sample):
        symbol = str(stock.get("code", ""))
        name = str(stock.get("name", ""))

        if (i + 1) % 20 == 0:
            print(
                f"  进度: {i + 1}/{len(sample)}，已找到 {len(all_findings)} 个信号",
                file=sys.stderr,
            )

        try:
            bars = fetch_bars(symbol, offset=350)
        except Exception:
            continue

        if len(bars) < 300:
            continue

        # 滑动窗口：从第 270 根 K 线开始，每 10 根检查一次
        for check_idx in range(270, len(bars) - 20, 3):
            metrics = check_candidate_at(bars, check_idx)
            if metrics is None:
                continue

            # 有 forward 数据才有意义
            if check_idx + 20 >= len(bars):
                continue

            fwd = forward_performance(bars, check_idx)
            label = classify_case(fwd)

            # 生成 K 线描述
            window_bars = bars[: check_idx + 1]
            desc = describe_stock(symbol, window_bars)

            all_findings.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "signal_date": bars[check_idx].date,
                    "label": label,
                    "metrics": metrics,
                    "forward": fwd,
                    "kline_description": desc.text,
                    "key_low": desc.key_low,
                }
            )

    print(f"\n共找到 {len(all_findings)} 个信号点", file=sys.stderr)

    # 按类别分组，各取若干
    positive = [f for f in all_findings if f["label"] == "正例"]
    negative = [f for f in all_findings if f["label"] == "反例"]
    borderline = [f for f in all_findings if f["label"] == "边界"]

    print(
        f"正例: {len(positive)}，反例: {len(negative)}，边界: {len(borderline)}",
        file=sys.stderr,
    )

    # 各取 4 个（按 20 日收益排序选典型的）
    positive.sort(key=lambda x: x["forward"].get("return_20d", 0), reverse=True)
    negative.sort(key=lambda x: x["forward"].get("return_20d", 0))
    borderline.sort(key=lambda x: abs(x["forward"].get("return_20d", 0) or 0))

    selected = positive[:4] + negative[:4] + borderline[:4]

    # 格式化为案例集
    cases = []
    for i, f in enumerate(selected):
        cases.append(
            {
                "id": f"VR-{i + 1:03d}",
                "name": f"{f['name']}({f['symbol']}) {f['signal_date']}",
                "period": f["signal_date"],
                "category": "板块+个股",
                "human_label": f["label"],
                "sector_info": {
                    "sector": "待标注",
                    "level": "待标注",
                    "rules": {},
                    "needs_llm": False,
                },
                "kline_description": f["kline_description"],
                "expected_action": "待标注",
                "expected_key_low": f.get("key_low"),
                "_forward_performance": f["forward"],
                "_metrics": f["metrics"],
                "_auto_label": f["label"],
                "human_rationale": "待标注",
            }
        )

    output = {
        "version": "3.0",
        "description": "从真实市场数据中提取的验证案例。human_label 和 expected_action 已由 forward performance 自动预标注，需人工复核。",
        "cases": cases,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
