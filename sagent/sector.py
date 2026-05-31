from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from .models import SectorSnapshot, SectorSummary, SectorValidation


class HasSectorSnapshots(Protocol):
    def sector_snapshots(self) -> list[SectorSnapshot]: ...


def summarize_sectors(data: HasSectorSnapshots) -> dict[str, SectorSummary]:
    grouped: dict[str, list[SectorSnapshot]] = defaultdict(list)
    for snapshot in data.sector_snapshots():
        grouped[snapshot.sector].append(snapshot)
    summaries: dict[str, SectorSummary] = {}
    for sector, rows in grouped.items():
        rows = sorted(rows, key=lambda row: row.date)
        latest = rows[-1]
        performance_windows = {
            "1d": latest.pct_chg,
            "5d": round(sum(row.pct_chg for row in rows[-5:]), 2),
            "10d": round(sum(row.pct_chg for row in rows[-10:]), 2),
            "30d": round(sum(row.pct_chg for row in rows[-30:]), 2),
        }
        rank_windows = {
            "1d_gain_rank": latest.gain_rank,
            "5d_avg_turnover_rank": round(
                sum(row.turnover_rank for row in rows[-5:]) / min(len(rows), 5)
            ),
            "10d_gain_top10_count": sum(1 for row in rows[-10:] if row.gain_rank <= 10),
            "30d_gain_top10_count": sum(1 for row in rows if row.gain_rank <= 10),
        }
        summaries[sector] = SectorSummary(
            sector=sector,
            turnover_top10_days=sum(1 for row in rows[-5:] if row.turnover_rank <= 10),
            gain_top10_count_30d=sum(1 for row in rows if row.gain_rank <= 10),
            limit_up_breadth_count_30d=sum(
                1 for row in rows if row.limit_up_count >= 3
            ),
            recent_pct_chg=latest.pct_chg,
            representative_stocks=latest.strong_stocks,
            performance_windows=performance_windows,
            rank_windows=rank_windows,
        )
    return summaries


def validate_mainline_sectors(
    summaries: dict[str, SectorSummary],
    turnover_days_threshold: int = 5,
    gain_count_threshold: int = 3,
    limit_up_count_threshold: int = 3,
) -> dict[str, SectorValidation]:
    result: dict[str, SectorValidation] = {}
    for sector, summary in summaries.items():
        rules = {
            "turnover_top10_5d": summary.turnover_top10_days >= turnover_days_threshold,
            "gain_top10_3x": summary.gain_top10_count_30d >= gain_count_threshold,
            "limit_up_breadth_3x": summary.limit_up_breadth_count_30d
            >= limit_up_count_threshold,
        }
        if all(rules.values()):
            level = "强主线"
        elif rules["turnover_top10_5d"] and rules["gain_top10_3x"]:
            level = "弱主线"
        else:
            level = "非主线"
        result[sector] = SectorValidation(
            sector=sector,
            level=level,
            rules=rules,
            reasons=[name for name, passed in rules.items() if passed],
            needs_llm=level == "弱主线",
        )
    return result
