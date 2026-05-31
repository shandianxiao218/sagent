from __future__ import annotations

from collections import Counter
from statistics import mean

from .sector import summarize_sectors, validate_mainline_sectors
from .technical import filter_stock_pool, technical_candidates


def run_quant_backtest(data, start: str, end: str) -> dict:
    pool = filter_stock_pool(data.stocks())
    candidates = technical_candidates(data, pool.included)
    sectors = validate_mainline_sectors(summarize_sectors(data))
    sector_distribution = Counter(candidate.sector for candidate in candidates)
    forward_returns = []
    for candidate in candidates:
        bars = [
            bar for bar in data.daily_bars(candidate.symbol) if start <= bar.date <= end
        ]
        if len(bars) >= 6:
            forward_returns.append(
                round((bars[-1].close - bars[-6].close) / bars[-6].close, 4)
            )
    return {
        "start": start,
        "end": end,
        "scope": "量化粗筛与主线验证，不包含 LLM 判断层",
        "candidate_count": len(candidates),
        "sector_distribution": dict(sector_distribution),
        "mainline_sectors": {sector: item.level for sector, item in sectors.items()},
        "forward_performance": {
            "sample_count": len(forward_returns),
            "avg_5d_return": round(mean(forward_returns), 4)
            if forward_returns
            else None,
            "returns": forward_returns,
        },
        "threshold_notes": "250日均线、60日涨幅、回撤比例、近3日回升等阈值用于评估候选池质量；本回测不包含 LLM 判断层，不等同于完整策略收益回测。",
    }
