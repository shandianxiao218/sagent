"""测试 LocalBarCache 和向量化解析。"""

from __future__ import annotations

import sqlite3 as _sqlite3  # noqa: F401 — test file, kept for reference
from pathlib import Path

import pandas as pd

from sagent.cache import LocalBarCache, _parse_bars
from sagent.models import DailyBar


def _make_frame(n: int = 5, symbol: str = "000001") -> pd.DataFrame:
    """构造模拟 mootdx 返回的 DataFrame。"""
    return pd.DataFrame(
        {
            "datetime": [f"2026-01-{i + 10:02d}" for i in range(n)],
            "open": [10.0 + i for i in range(n)],
            "high": [11.0 + i for i in range(n)],
            "low": [9.0 + i for i in range(n)],
            "close": [10.5 + i for i in range(n)],
            "vol": [1000.0] * n,
            "amount": [10000.0] * n,
        }
    )


def test_parse_bars_vectorized():
    """向量化解析应正确转换 DataFrame 为 DailyBar 列表。"""
    frame = _make_frame(3)
    bars = _parse_bars("000001", frame)

    assert len(bars) == 3
    assert bars[0].symbol == "000001"
    assert bars[0].date == "2026-01-10"
    assert bars[0].open == 10.0
    assert bars[0].close == 10.5
    assert bars[2].close == 12.5


def test_parse_bars_none():
    """frame=None 时返回空列表。"""
    assert _parse_bars("000001", None) == []


def test_parse_bars_empty():
    """空 DataFrame 时返回空列表。"""
    assert _parse_bars("000001", pd.DataFrame()) == []


def test_parse_bars_with_datetime_index():
    """当 datetime 在 index 而非列中时也能解析。"""
    frame = pd.DataFrame(
        {
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "vol": [1000.0],
            "amount": [10000.0],
        },
        index=pd.to_datetime(["2026-05-29"]),
    )
    bars = _parse_bars("600036", frame)
    assert len(bars) == 1
    assert bars[0].symbol == "600036"
    assert bars[0].date == "2026-05-29"


def test_cache_roundtrip(tmp_path: Path):
    """写入 → 读取的 roundtrip 测试。"""
    cache = LocalBarCache(tmp_path / "test.db")

    # 构造测试数据
    bars = [
        DailyBar("000001", "2026-01-10", 10.0, 11.0, 9.0, 10.5, 1000, 10000),
        DailyBar("000001", "2026-01-11", 10.5, 11.5, 9.5, 11.0, 1100, 11000),
        DailyBar("000001", "2026-01-12", 11.0, 12.0, 10.0, 11.5, 1200, 12000),
    ]

    # 直接写入
    conn = cache._get_conn()
    for b in bars:
        conn.execute(
            "INSERT OR IGNORE INTO daily_bars "
            "(symbol, date, open, high, low, close, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (b.symbol, b.date, b.open, b.high, b.low, b.close, b.volume, b.amount),
        )
    conn.commit()

    # 读取
    loaded = cache.daily_bars("000001")
    assert len(loaded) == 3
    assert loaded[0].close == 10.5
    assert loaded[2].close == 11.5

    cache.close()


def test_cache_stats(tmp_path: Path):
    """缓存统计信息正确。"""
    cache = LocalBarCache(tmp_path / "test.db")

    bars = [
        DailyBar("000001", "2026-01-10", 10.0, 11.0, 9.0, 10.5, 1000, 10000),
        DailyBar("600036", "2026-01-10", 50.0, 51.0, 49.0, 50.5, 2000, 20000),
    ]
    conn = cache._get_conn()
    for b in bars:
        conn.execute(
            "INSERT OR IGNORE INTO daily_bars "
            "(symbol, date, open, high, low, close, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (b.symbol, b.date, b.open, b.high, b.low, b.close, b.volume, b.amount),
        )
    conn.commit()

    stats = cache.stats()
    assert stats["total_rows"] == 2
    assert stats["total_symbols"] == 2
    assert stats["date_min"] == "2026-01-10"
    assert stats["date_max"] == "2026-01-10"
    assert stats["db_size_mb"] >= 0  # 空库可能为 0

    cache.close()


def test_cache_insert_or_ignore_no_duplicates(tmp_path: Path):
    """重复写入同一条数据不会产生重复行。"""
    cache = LocalBarCache(tmp_path / "test.db")
    bar = DailyBar("000001", "2026-01-10", 10.0, 11.0, 9.0, 10.5, 1000, 10000)

    conn = cache._get_conn()
    for _ in range(3):
        conn.execute(
            "INSERT OR IGNORE INTO daily_bars "
            "(symbol, date, open, high, low, close, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bar.symbol,
                bar.date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.amount,
            ),
        )
    conn.commit()

    loaded = cache.daily_bars("000001")
    assert len(loaded) == 1

    cache.close()


def test_bulk_daily_bars(tmp_path: Path):
    """批量读取多只股票。"""
    cache = LocalBarCache(tmp_path / "test.db")
    conn = cache._get_conn()

    for sym in ["000001", "000002", "000003"]:
        for day in range(3):
            conn.execute(
                "INSERT OR IGNORE INTO daily_bars "
                "(symbol, date, open, high, low, close, volume, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sym, f"2026-01-{10 + day}", 10.0, 11.0, 9.0, 10.5, 1000, 10000),
            )
    conn.commit()

    result = cache.bulk_daily_bars(["000001", "000003"])
    assert len(result) == 2
    assert "000001" in result
    assert "000003" in result
    assert "000002" not in result
    assert len(result["000001"]) == 3

    cache.close()


def test_download_and_cache_with_mock_mootdx(tmp_path: Path):
    """用 mock mootdx 测试 download_and_cache。"""

    class FakeMootdx:
        def bars(self, symbol, category, offset):
            return _make_frame(5, symbol)

    cache = LocalBarCache(tmp_path / "test.db", mootdx_client=FakeMootdx())
    result = cache.download_and_cache(["000001", "600036"])

    assert result["000001"] == 5
    assert result["600036"] == 5

    loaded = cache.daily_bars("000001")
    assert len(loaded) == 5
    assert loaded[0].close == 10.5

    cache.close()


def test_ensure_symbols_incremental(tmp_path: Path):
    """ensure_symbols 第二次调用应该只做增量。"""
    call_count = 0

    class FakeMootdx:
        def bars(self, symbol, category, offset):
            nonlocal call_count
            call_count += 1
            return _make_frame(offset if offset <= 30 else 5, symbol)

    cache = LocalBarCache(tmp_path / "test.db", mootdx_client=FakeMootdx())

    # 第一次：全量下载
    cache.ensure_symbols(["000001"], min_bars=3)
    assert call_count >= 1
    _first_calls = call_count  # noqa: F841

    # 第二次：增量（只需拉最新 30 根对比）
    call_count = 0
    cache.ensure_symbols(["000001"], min_bars=3)
    assert call_count <= 1  # 只拉一次增量

    cache.close()


def test_max_cached_date(tmp_path: Path):
    """max_cached_date 返回最新日期。"""
    cache = LocalBarCache(tmp_path / "test.db")
    conn = cache._get_conn()

    dates = ["2026-01-10", "2026-01-11", "2026-01-12"]
    for d in dates:
        conn.execute(
            "INSERT OR IGNORE INTO daily_bars "
            "(symbol, date, open, high, low, close, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("000001", d, 10.0, 11.0, 9.0, 10.5, 1000, 10000),
        )
    conn.commit()

    assert cache.max_cached_date("000001") == "2026-01-12"
    assert cache.max_cached_date("999999") is None
    assert cache.count_bars("000001") == 3

    cache.close()


def test_wal_mode_enabled(tmp_path: Path):
    """SQLite WAL 模式启用。"""
    cache = LocalBarCache(tmp_path / "test.db")
    conn = cache._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    cache.close()
