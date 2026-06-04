from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

# Re-export cache classes for backward compatibility
from .sector_bars_cache import SectorBarCache
from .sector_cache import SectorCache


@dataclass(frozen=True)
class SectorSnapshot:
    sector: str
    date: str
    turnover_rank: int
    gain_rank: int
    pct_chg: float
    limit_up_count: int
    strong_stocks: list[str]
    up_count: int = 0
    down_count: int = 0


@dataclass(frozen=True)
class SectorSummary:
    sector: str
    turnover_top10_days: int
    gain_top10_count_30d: int
    limit_up_breadth_count_30d: int
    recent_pct_chg: float
    representative_stocks: list[str]
    performance_windows: dict[str, float] = field(default_factory=dict)
    rank_windows: dict[str, int] = field(default_factory=dict)
    data_source: str = "fixture"
    window: str = "30d"


@dataclass(frozen=True)
class SectorValidation:
    sector: str
    level: str
    rules: dict[str, bool]
    reasons: list[str]
    needs_llm: bool = False


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


class SectorStore:
    """统一板块数据访问的深模块。

    合并 SectorCache（行业归属）和 SectorBarCache（板块K线）
    为单一入口。调用方只需 import SectorStore。
    """

    def __init__(self, db_path: Path | str, bars_db_path: Path | str | None = None):
        self._cache = SectorCache(Path(db_path))
        bars_path = (
            Path(bars_db_path)
            if bars_db_path
            else Path(db_path).parent / "sector_bars.db"
        )
        self._bars_cache = SectorBarCache(bars_path)

    # ── 行业归属 ──────────────────────────────────────
    def get_industry(self, code: str) -> str:
        return self._cache.get_industry(code)

    def get_all_mapping(self) -> dict[str, list[str]]:
        return self._cache.get_all_mapping()

    def get_industry_mapping(self) -> dict[str, str]:
        return self._cache.get_industry_mapping()

    def needs_refresh(self) -> bool:
        return self._cache.needs_refresh()

    def refresh(self) -> None:
        self._cache.refresh()

    # ── 板块K线 ────────────────────────────────────────
    def sector_bars(self, sector_code: str, max_date: str | None = None):
        return self._bars_cache.sector_bars(sector_code, max_date)

    def sector_bars_with_counts(self, sector_code: str, max_date: str | None = None):
        return self._bars_cache.sector_bars_with_counts(sector_code, max_date)

    def ensure_sectors(self, sector_codes: list[str]) -> None:
        self._bars_cache.ensure_sectors(sector_codes)

    # ── 通用 ──────────────────────────────────────────
    def stats(self) -> dict:
        return {"cache": self._cache.stats(), "bars": self._bars_cache.stats()}

    def close(self) -> None:
        self._cache.close()
        self._bars_cache.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
