"""本地 SQLite 日线缓存层。

首次运行时批量下载全 A 股近 3 年日线，存入本地 SQLite 文件。
后续扫描只增量补齐最新缺失交易日，避免重复网络请求。

用法：
    from sagent.cache import LocalBarCache

    cache = LocalBarCache(Path("data/bars.db"))
    cache.ensure_symbols(["000001", "600036", ...])  # 增量补缺
    bars = cache.daily_bars("000001")                 # 读本地
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from .models import DailyBar


class MootdxLike(Protocol):
    def bars(self, symbol: str, category: int, offset: int) -> object: ...


# ---------------------------------------------------------------------------
# 快速 DataFrame → list[DailyBar] 解析（无 iterrows）
# ---------------------------------------------------------------------------


def _parse_bars(symbol: str, frame: object) -> list[DailyBar]:
    """将 mootdx 返回的 DataFrame 解析为 DailyBar 列表（向量化）。"""
    if frame is None:
        return []
    import pandas as pd

    if isinstance(frame, pd.DataFrame) and not frame.empty:
        n = len(frame)
        date_col = (
            frame["datetime"]
            if "datetime" in frame.columns
            else frame.index.to_series().astype(str)
        )
        dates = date_col.values  # numpy array of str
        opens = frame["open"].values
        highs = frame["high"].values
        lows = frame["low"].values
        closes = frame["close"].values
        vols = frame["vol"].values
        amounts = frame["amount"].values

        bars: list[DailyBar] = []
        for i in range(n):
            d = str(dates[i])
            date_str = d[:10] if len(d) >= 10 else d
            bars.append(
                DailyBar(
                    symbol=symbol,
                    date=date_str,
                    open=float(opens[i]),
                    high=float(highs[i]),
                    low=float(lows[i]),
                    close=float(closes[i]),
                    volume=float(vols[i]),
                    amount=float(amounts[i]),
                )
            )
        return bars
    return []


# ---------------------------------------------------------------------------
# SQLite 缓存
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_bars (
    symbol   TEXT NOT NULL,
    date     TEXT NOT NULL,
    open     REAL NOT NULL,
    high     REAL NOT NULL,
    low      REAL NOT NULL,
    close    REAL NOT NULL,
    volume   REAL NOT NULL,
    amount   REAL NOT NULL,
    PRIMARY KEY (symbol, date)
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_bars_symbol_date
ON daily_bars (symbol, date)
"""


class LocalBarCache:
    """SQLite 本地日线缓存。

    三年日线约 750 条/只 × 5500 只 ≈ 400 万行，SQLite 轻松处理。
    文件大小约 200-400 MB。
    """

    def __init__(self, db_path: Path, mootdx_client: MootdxLike | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._mootdx = mootdx_client
        self._conn: sqlite3.Connection | None = None
        self._ensure_table()

    # ---- 内部连接管理 ----

    def _ensure_table(self) -> None:
        conn = self._get_conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS daily_bars (symbol TEXT NOT NULL, date TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL, amount REAL NOT NULL, PRIMARY KEY (symbol, date))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bars_symbol_date ON daily_bars (symbol, date)"
        )
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            # WAL 模式提升并发读性能
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            # 批量写入时大幅提速
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB
        return self._conn

    def _get_mootdx(self) -> MootdxLike:
        if self._mootdx is None:
            try:
                from mootdx.quotes import Quotes

                self._mootdx = Quotes.factory(market="std")
            except Exception as e:
                raise RuntimeError(
                    "未安装或无法连接 mootdx，请先安装：pip install mootdx"
                ) from e
        return self._mootdx

    # ---- 公开 API ----

    def cached_dates(self, symbol: str) -> set[str]:
        """返回某只股票已缓存的日期集合。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT date FROM daily_bars WHERE symbol = ? ORDER BY date",
            (symbol,),
        ).fetchall()
        return {r[0] for r in rows}

    def cached_symbols(self) -> set[str]:
        """返回已缓存的所有股票代码。"""
        conn = self._get_conn()
        rows = conn.execute("SELECT DISTINCT symbol FROM daily_bars").fetchall()
        return {r[0] for r in rows}

    def max_cached_date(self, symbol: str) -> str | None:
        """返回某只股票已缓存的最大日期。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT MAX(date) FROM daily_bars WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return row[0] if row and row[0] else None

    def count_bars(self, symbol: str) -> int:
        """返回已缓存的 bar 数量。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM daily_bars WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return row[0] if row else 0

    def daily_bars(self, symbol: str) -> list[DailyBar]:
        """从本地缓存读取日线数据。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, amount "
            "FROM daily_bars WHERE symbol = ? ORDER BY date",
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

    def download_and_cache(
        self, symbols: list[str], offset: int = 750
    ) -> dict[str, int]:
        """批量下载日线并存入缓存。返回 {symbol: 新增行数}。

        Args:
            symbols: 需要下载的股票代码列表
            offset: 从 mootdx 拉取的 bar 数量（默认 750 ≈ 3 年）
        """
        client = self._get_mootdx()
        conn = self._get_conn()
        result: dict[str, int] = {}

        for i, symbol in enumerate(symbols):
            if (i + 1) % 500 == 0:
                print(f"  下载进度: {i + 1}/{len(symbols)}", flush=True)
            try:
                frame = client.bars(symbol=symbol, category=4, offset=offset)
                bars = _parse_bars(symbol, frame)
                if not bars:
                    result[symbol] = 0
                    continue
                # 批量 INSERT OR IGNORE（已有数据不重复写入）
                rows = [
                    (
                        b.symbol,
                        b.date,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.volume,
                        b.amount,
                    )
                    for b in bars
                ]
                conn.executemany(
                    "INSERT OR IGNORE INTO daily_bars "
                    "(symbol, date, open, high, low, close, volume, amount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                result[symbol] = len(rows)
            except Exception:
                result[symbol] = 0

        conn.commit()
        return result

    def global_max_date(self) -> str | None:
        """返回缓存中全局最新日期（所有股票的最大 date）。"""
        conn = self._get_conn()
        row = conn.execute("SELECT MAX(date) FROM daily_bars").fetchone()
        return row[0] if row else None

    def ensure_symbols(
        self,
        symbols: list[str],
        min_bars: int = 250,
        skip_incremental: bool = False,
    ) -> dict[str, int]:
        """确保指定股票有足够的本地缓存数据。

        对于已缓存的股票：只增量下载缺失的最新数据。
        对于未缓存的股票：下载 3 年数据。

        Args:
            skip_incremental: 跳过增量更新（回测时缓存够用可跳过网络请求）

        Returns:
            {symbol: 新增 bar 数}
        """
        # 分为两类：需要全量下载的和只需增量的
        full_download: list[str] = []
        incremental: list[str] = []

        conn = self._get_conn()
        for symbol in symbols:
            count = self.count_bars(symbol)
            if count < min_bars:
                full_download.append(symbol)
            else:
                incremental.append(symbol)

        result: dict[str, int] = {}

        # 全量下载
        if full_download:
            print(f"  全量下载 {len(full_download)} 只股票（3 年日线）...", flush=True)
            result.update(self.download_and_cache(full_download, offset=750))

        # 增量补齐：检查最新日期，下载缺失部分
        if incremental and not skip_incremental:
            total = len(incremental)
            est_min = total * 0.002  # 每只约 2ms
            print(
                f"  增量更新 {total} 只股票（预计 {est_min:.1f}s）...",
                flush=True,
            )
            client = self._get_mootdx()
            updated = 0
            for idx, symbol in enumerate(incremental, 1):
                if idx % 200 == 0 or idx == total:
                    print(
                        f"    更新进度: {idx}/{total} ({idx * 100 // total}%)",
                        flush=True,
                    )
                try:
                    # 取本地最新日期
                    local_max = self.max_cached_date(symbol)
                    if local_max is None:
                        # 本地没数据，走全量
                        full_download.append(symbol)
                        continue
                    # 拉最近 30 根（覆盖节假日和周末）
                    frame = client.bars(symbol=symbol, category=4, offset=30)
                    bars = _parse_bars(symbol, frame)
                    new_rows = 0
                    for b in bars:
                        if b.date > local_max:
                            conn.execute(
                                "INSERT OR IGNORE INTO daily_bars "
                                "(symbol, date, open, high, low, close, volume, amount) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (
                                    b.symbol,
                                    b.date,
                                    b.open,
                                    b.high,
                                    b.low,
                                    b.close,
                                    b.volume,
                                    b.amount,
                                ),
                            )
                            new_rows += 1
                    if new_rows > 0:
                        updated += 1
                    result[symbol] = new_rows
                except Exception:
                    result[symbol] = 0

            conn.commit()
            if updated:
                print(f"  增量更新完成：{updated} 只股票有新数据", flush=True)

        # 处理被补到 full_download 的增量股
        if full_download:
            extra = [s for s in full_download if s not in result]
            if extra:
                result.update(self.download_and_cache(extra, offset=750))

        return result

    def bulk_daily_bars(self, symbols: list[str]) -> dict[str, list[DailyBar]]:
        """批量读取多只股票的日线，一次性 SQL 查询。"""
        conn = self._get_conn()
        if not symbols:
            return {}

        # 分批查询避免 SQL 过长
        batch_size = 500
        all_bars: dict[str, list[DailyBar]] = {}

        for batch_start in range(0, len(symbols), batch_size):
            batch = symbols[batch_start : batch_start + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT symbol, date, open, high, low, close, volume, amount "
                f"FROM daily_bars WHERE symbol IN ({placeholders}) ORDER BY date",
                batch,
            ).fetchall()

            for r in rows:
                sym = r[0]
                if sym not in all_bars:
                    all_bars[sym] = []
                all_bars[sym].append(
                    DailyBar(
                        symbol=sym,
                        date=r[1],
                        open=r[2],
                        high=r[3],
                        low=r[4],
                        close=r[5],
                        volume=r[6],
                        amount=r[7],
                    )
                )

        return all_bars

    def daily_bars_up_to(self, symbol: str, max_date: str) -> list[DailyBar]:
        """从本地缓存读取日线数据，只返回 <= max_date 的 bar。

        回测时必须使用此方法（或 bulk_daily_bars_up_to），
        防止信号检测用到未来数据（look-ahead bias）。
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, amount "
            "FROM daily_bars WHERE symbol = ? AND date <= ? ORDER BY date",
            (symbol, max_date),
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

    def bulk_daily_bars_up_to(
        self, symbols: list[str], max_date: str
    ) -> dict[str, list[DailyBar]]:
        """批量读取多只股票日线，只返回 <= max_date 的 bar。

        回测专用：一次性加载所有股票截至回测日期的数据。
        """
        conn = self._get_conn()
        if not symbols:
            return {}

        batch_size = 500
        all_bars: dict[str, list[DailyBar]] = {}

        for batch_start in range(0, len(symbols), batch_size):
            batch = symbols[batch_start : batch_start + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT symbol, date, open, high, low, close, volume, amount "
                f"FROM daily_bars "
                f"WHERE symbol IN ({placeholders}) AND date <= ? ORDER BY date",
                (*batch, max_date),
            ).fetchall()

            for r in rows:
                sym = r[0]
                if sym not in all_bars:
                    all_bars[sym] = []
                all_bars[sym].append(
                    DailyBar(
                        symbol=sym,
                        date=r[1],
                        open=r[2],
                        high=r[3],
                        low=r[4],
                        close=r[5],
                        volume=r[6],
                        amount=r[7],
                    )
                )

        return all_bars

    def bulk_closes_up_to(
        self, symbols: list[str], max_date: str
    ) -> dict[str, tuple[list[str], list[float]]]:
        """批量读取多只股票截至 max_date 的 (dates, closes) 元组。

        比 bulk_daily_bars_up_to 快 ~10x，因为不构建 DailyBar 对象，
        只提取信号扫描需要的 date 和 close 两列。

        Returns:
            {symbol: (dates_list, closes_list)} 按 date 升序
        """
        conn = self._get_conn()
        if not symbols:
            return {}

        batch_size = 500
        result: dict[str, tuple[list[str], list[float]]] = {}
        dates_map: dict[str, list[str]] = {}
        closes_map: dict[str, list[float]] = {}

        for batch_start in range(0, len(symbols), batch_size):
            batch = symbols[batch_start : batch_start + batch_size]
            placeholders = ",".join("?" * len(batch))
            rows = conn.execute(
                f"SELECT symbol, date, close "
                f"FROM daily_bars "
                f"WHERE symbol IN ({placeholders}) AND date <= ? ORDER BY date",
                (*batch, max_date),
            ).fetchall()

            for r in rows:
                sym = r[0]
                if sym not in dates_map:
                    dates_map[sym] = []
                    closes_map[sym] = []
                dates_map[sym].append(r[1])
                closes_map[sym].append(r[2])

        for sym in dates_map:
            result[sym] = (dates_map[sym], closes_map[sym])

        return result

    def stats(self) -> dict:
        """返回缓存统计信息。"""
        conn = self._get_conn()
        total_rows = conn.execute("SELECT COUNT(*) FROM daily_bars").fetchone()[0]
        total_symbols = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM daily_bars"
        ).fetchone()[0]
        date_range = conn.execute(
            "SELECT MIN(date), MAX(date) FROM daily_bars"
        ).fetchone()
        return {
            "total_rows": total_rows,
            "total_symbols": total_symbols,
            "date_min": date_range[0],
            "date_max": date_range[1],
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1),
        }

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()
