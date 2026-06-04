"""板块指数K线缓存 — mootdx TCP index_bars() + SQLite 本地存储。

数据源：通达信 index_bars() TCP 接口，获取同花顺行业板块(881xxx)日线。
缓存到 SQLite WAL，3 年历史，增量更新。

与 bars.db (个股K线) 共存，设计模式一致。

表结构：
  sector_bars: symbol, date, open, high, low, close, vol, amount, up_count, down_count
  sector_meta: key-value 元信息（板块代码→名称映射、最后刷新时间等）

用法：
    from sagent.sector_bars_cache import SectorBarCache
    cache = SectorBarCache(Path("data/sector_bars.db"))
    cache.ensure_sectors()           # 增量补缺
    bars = cache.sector_bars("881121")  # 读本地
    mapping = cache.sector_name_map()   # {code: name}
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from .market import DailyBar


class MootdxIndexBarsLike(Protocol):
    def index_bars(
        self,
        symbol: str = "000001",
        frequency: int = 9,
        start: int = 0,
        offset: int = 800,
        **kwargs: Any,
    ) -> Any: ...


class SectorBarCache:
    """板块指数K线本地缓存。

    基于 mootdx index_bars() TCP 接口，存储同花顺行业板块日线。
    表 daily_bars 复用个股格式，额外表 sector_names 存代码→名称映射。
    """

    # 同花顺行业板块代码范围（881101~881999）
    DEFAULT_SECTOR_CODES = [
        "881101",
        "881102",
        "881103",
        "881104",
        "881105",
        "881106",
        "881107",
        "881108",
        "881109",
        "881110",
        "881111",
        "881112",
        "881113",
        "881114",
        "881115",
        "881116",
        "881117",
        "881118",
        "881119",
        "881120",
        "881121",
        "881122",
        "881123",
        "881124",
        "881125",
        "881126",
        "881127",
        "881128",
        "881129",
        "881130",
        "881131",
        "881132",
        "881133",
        "881134",
        "881135",
        "881136",
        "881137",
        "881138",
        "881139",
        "881140",
        "881141",
        "881142",
        "881143",
        "881144",
        "881145",
        "881146",
        "881147",
        "881148",
        "881149",
        "881150",
        "881151",
        "881152",
        "881153",
        "881154",
        "881155",
        "881156",
        "881157",
        "881158",
        "881159",
        "881160",
        "881161",
        "881162",
        "881163",
        "881164",
        "881165",
        "881166",
        "881167",
        "881168",
        "881169",
        "881170",
        "881171",
        "881172",
        "881173",
        "881174",
        "881175",
        "881176",
        "881177",
        "881178",
        "881179",
        "881180",
        "881181",
        "881182",
        "881183",
        "881184",
        "881185",
        "881186",
        "881187",
        "881188",
        "881189",
        "881190",
        "881191",
        "881192",
        "881193",
        "881194",
        "881195",
        "881196",
        "881197",
        "881198",
        "881199",
        "881200",
        "881201",
        "881202",
        "881203",
        "881204",
        "881205",
        "881206",
        "881207",
        "881208",
        "881209",
        "881210",
        "881211",
        "881212",
        "881213",
        "881214",
        "881215",
        "881216",
        "881217",
        "881218",
        "881219",
        "881220",
        "881221",
        "881222",
        "881223",
        "881224",
        "881225",
        "881226",
        "881227",
        "881228",
        "881229",
        "881230",
        "881231",
        "881232",
        "881233",
        "881234",
        "881235",
        "881236",
        "881237",
        "881238",
        "881239",
        "881240",
        "881241",
        "881242",
        "881243",
        "881244",
        "881245",
        "881246",
        "881247",
        "881248",
        "881249",
        "881250",
        "881251",
        "881252",
        "881253",
        "881254",
        "881255",
        "881256",
        "881257",
        "881258",
        "881259",
        "881260",
        "881261",
        "881262",
        "881263",
        "881264",
        "881265",
        "881266",
        "881267",
        "881268",
        "881269",
        "881270",
        "881271",
        "881272",
        "881273",
        "881274",
        "881275",
        "881276",
        "881277",
        "881278",
        "881279",
        "881280",
        "881281",
        "881282",
        "881283",
        "881284",
        "881285",
        "881286",
        "881287",
        "881288",
        "881289",
        "881290",
        "881291",
        "881292",
        "881293",
        "881294",
        "881295",
        "881296",
        "881297",
        "881298",
        "881299",
    ]

    def __init__(
        self, db_path: Path, mootdx_client: MootdxIndexBarsLike | None = None
    ) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._mootdx = mootdx_client
        self._conn = None
        self._ensure_table()

    def _ensure_table(self) -> None:
        import sqlite3

        conn = self._get_conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sector_bars ("
            "symbol TEXT NOT NULL, "
            "date TEXT NOT NULL, "
            "open REAL NOT NULL, "
            "high REAL NOT NULL, "
            "low REAL NOT NULL, "
            "close REAL NOT NULL, "
            "volume REAL NOT NULL, "
            "amount REAL NOT NULL, "
            "up_count INTEGER DEFAULT 0, "
            "down_count INTEGER DEFAULT 0, "
            "PRIMARY KEY (symbol, date))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sector_bars_symbol_date "
            "ON sector_bars (symbol, date)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sector_names ("
            "code TEXT PRIMARY KEY, "
            "name TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sector_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.commit()

    def _get_conn(self):
        import sqlite3

        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")
        return self._conn

    def _get_mootdx(self) -> MootdxIndexBarsLike:
        if self._mootdx is None:
            from mootdx.quotes import Quotes

            self._mootdx = Quotes.factory(market="std")
        return self._mootdx

    def _parse_index_bars(self, symbol: str, frame: Any) -> list[dict]:
        """向量化解析 mootdx index_bars DataFrame → dict 列表。"""
        if frame is None or frame.empty:
            return []
        import numpy as np

        n = len(frame)
        result = [None] * n

        opens = frame["open"].values
        highs = frame["high"].values
        lows = frame["low"].values
        closes = frame["close"].values
        volumes = (
            frame["volume"].values if "volume" in frame.columns else frame["vol"].values
        )
        amounts = frame["amount"].values
        datetimes = frame["datetime"].values
        up_counts = (
            frame["up_count"].values if "up_count" in frame.columns else np.zeros(n)
        )
        down_counts = (
            frame["down_count"].values if "down_count" in frame.columns else np.zeros(n)
        )

        for i in range(n):
            dt = str(datetimes[i])[:10]  # "2026-06-03"
            result[i] = (
                symbol,
                dt,
                float(opens[i]),
                float(highs[i]),
                float(lows[i]),
                float(closes[i]),
                float(volumes[i]),
                float(amounts[i]),
                int(up_counts[i]),
                int(down_counts[i]),
            )
        return result

    def refresh_sector(self, symbol: str, years: int = 3) -> int:
        """拉取单个板块的全量/增量K线并存入缓存。

        Returns: 新增行数
        """
        conn = self._get_conn()
        client = self._get_mootdx()

        # 计算需要多少行（~250 交易日/年）
        offset = years * 250

        # 检查已有数据的最新日期
        latest = conn.execute(
            "SELECT MAX(date) FROM sector_bars WHERE symbol = ?", (symbol,)
        ).fetchone()[0]

        if latest:
            # 增量：计算需要补充多少天
            # 简单做法：拉 offset 行，让 INSERT OR IGNORE 去重
            pass

        try:
            frame = client.index_bars(symbol=symbol, offset=offset)
        except Exception:
            return 0

        rows = self._parse_index_bars(symbol, frame)
        if not rows:
            return 0

        conn.executemany(
            "INSERT OR IGNORE INTO sector_bars "
            "(symbol, date, open, high, low, close, volume, amount, up_count, down_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)

    def ensure_sectors(self, sector_codes: list[str] | None = None) -> dict[str, int]:
        """批量确保板块K线数据已缓存。

        Returns: {symbol: new_rows}
        """
        codes = sector_codes or self.DEFAULT_SECTOR_CODES
        result: dict[str, int] = {}
        conn = self._get_conn()

        # 找出已有数据的板块和最新日期
        existing = {}
        for row in conn.execute(
            "SELECT symbol, MAX(date) FROM sector_bars GROUP BY symbol"
        ).fetchall():
            existing[row[0]] = row[1]

        total_new = 0
        t0 = time.perf_counter()

        for i, code in enumerate(codes):
            # 已有今天数据的跳过
            if existing.get(code) == time.strftime("%Y-%m-%d"):
                result[code] = 0
                continue

            new_rows = self.refresh_sector(code, years=3)
            result[code] = new_rows
            total_new += new_rows

            if (i + 1) % 10 == 0:
                elapsed = time.perf_counter() - t0
                print(
                    f"  板块K线进度: {i + 1}/{len(codes)} ({elapsed:.1f}s)",
                )

        elapsed = time.perf_counter() - t0
        active = sum(1 for v in result.values() if v > 0)
        print(
            f"板块K线缓存完成：{active}/{len(codes)} 有数据，"
            f"共 {total_new} 行 ({elapsed:.1f}s)"
        )
        return result

    def sector_bars(self, symbol: str) -> list[DailyBar]:
        """读取单个板块的K线数据。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, amount "
            "FROM sector_bars WHERE symbol = ? ORDER BY date",
            (symbol,),
        ).fetchall()
        return [
            DailyBar(
                symbol=symbol,
                date=r[0],
                open=r[1],
                high=r[2],
                low=r[3],
                close=r[4],
                volume=r[5],
                amount=r[6],
            )
            for r in rows
        ]

    def sector_bars_with_counts(self, symbol: str) -> list[dict]:
        """读取板块K线（含涨跌家数）。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, amount, up_count, down_count "
            "FROM sector_bars WHERE symbol = ? ORDER BY date",
            (symbol,),
        ).fetchall()
        return [
            {
                "date": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
                "amount": r[6],
                "up_count": r[7],
                "down_count": r[8],
            }
            for r in rows
        ]

    def bulk_sector_bars(self, symbols: list[str]) -> dict[str, list[DailyBar]]:
        """批量读取多个板块的K线。"""
        conn = self._get_conn()
        if not symbols:
            return {}
        result: dict[str, list[DailyBar]] = {s: [] for s in symbols}
        batch_size = 100
        for start in range(0, len(symbols), batch_size):
            batch = symbols[start : start + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT symbol, date, open, high, low, close, volume, amount "
                f"FROM sector_bars WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
                batch,
            ).fetchall()
            for r in rows:
                result[r[0]].append(
                    DailyBar(
                        symbol=r[0],
                        date=r[1],
                        open=r[2],
                        high=r[3],
                        low=r[4],
                        close=r[5],
                        volume=r[6],
                        amount=r[7],
                    )
                )
        return result

    def bulk_sector_bars_with_counts(self, symbols: list[str]) -> dict[str, list[dict]]:
        """批量读取板块K线（含涨跌家数）。"""
        conn = self._get_conn()
        if not symbols:
            return {}
        result: dict[str, list[dict]] = {s: [] for s in symbols}
        batch_size = 100
        for start in range(0, len(symbols), batch_size):
            batch = symbols[start : start + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT symbol, date, open, high, low, close, volume, amount, up_count, down_count "
                f"FROM sector_bars WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
                batch,
            ).fetchall()
            for r in rows:
                result[r[0]].append(
                    {
                        "date": r[1],
                        "open": r[2],
                        "high": r[3],
                        "low": r[4],
                        "close": r[5],
                        "volume": r[6],
                        "amount": r[7],
                        "up_count": r[8],
                        "down_count": r[9],
                    }
                )
        return result

    def save_sector_names(self, mapping: dict[str, str]) -> int:
        """保存板块代码→名称映射。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM sector_names")
        rows = [(code, name) for code, name in mapping.items()]
        conn.executemany("INSERT INTO sector_names (code, name) VALUES (?, ?)", rows)
        conn.commit()
        return len(rows)

    def sector_name_map(self) -> dict[str, str]:
        """获取板块代码→名称映射。"""
        conn = self._get_conn()
        rows = conn.execute("SELECT code, name FROM sector_names").fetchall()
        return {r[0]: r[1] for r in rows}

    def active_sector_codes(self) -> list[str]:
        """获取有数据的板块代码列表。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM sector_bars ORDER BY symbol"
        ).fetchall()
        return [r[0] for r in rows]

    def stats(self) -> dict:
        conn = self._get_conn()
        total_rows = conn.execute("SELECT COUNT(*) FROM sector_bars").fetchone()[0]
        total_sectors = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM sector_bars"
        ).fetchone()[0]
        date_range = conn.execute(
            "SELECT MIN(date), MAX(date) FROM sector_bars"
        ).fetchone()
        names_count = conn.execute("SELECT COUNT(*) FROM sector_names").fetchone()[0]
        return {
            "total_rows": total_rows,
            "total_sectors": total_sectors,
            "date_min": date_range[0] or "?",
            "date_max": date_range[1] or "?",
            "sector_names_count": names_count,
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1),
        }

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()
