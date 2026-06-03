"""行业映射缓存 — 用 mootdx TCP block() 一次获取全市场行业-股票映射。

数据源：通达信 block() TCP 接口（不走 HTTP 代理，与 K 线数据同一通道）。
缓存到 SQLite，与 bars.db 共存或独立文件。

用法：
    from sagent.sector_cache import SectorCache
    cache = SectorCache(Path("data/sector.db"))
    cache.refresh()  # 从 mootdx 拉取
    industry = cache.get_industry("000001")  # "通信设备"
    all_mapping = cache.get_all_mapping()  # {"000001": "通信设备", ...}
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol


class MootdxLike(Protocol):
    def block(self) -> object: ...


class SectorCache:
    """用 mootdx block() 建立行业映射并缓存到 SQLite。

    mootdx block() 返回 DataFrame，包含:
      - blockname: 板块名称（GBK 编码的中文）
      - block_type: 板块类型
      - code: 股票代码
      - code_index: 板块内序号

    block_type 含义:
      - 2: 概念/行业板块（我们需要的）
      - 其他: 指数成分等
    """

    def __init__(self, db_path: Path, mootdx_client: MootdxLike | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._mootdx = mootdx_client
        self._conn: sqlite3.Connection | None = None
        self._ensure_table()

    def _ensure_table(self) -> None:
        conn = self._get_conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS stock_sector ("
            "symbol TEXT NOT NULL, "
            "sector TEXT NOT NULL, "
            "PRIMARY KEY (symbol, sector))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sector_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _get_mootdx(self) -> MootdxLike:
        if self._mootdx is None:
            try:
                from mootdx.quotes import Quotes

                self._mootdx = Quotes.factory(market="std")
            except Exception as e:
                raise RuntimeError("未安装或无法连接 mootdx") from e
        return self._mootdx

    def refresh(self) -> dict:
        """从 mootdx block() 拉取全量行业映射，存入缓存。

        Returns:
            {"total_sectors": N, "total_mappings": M, "elapsed_sec": T}
        """
        import time

        t0 = time.perf_counter()

        client = self._get_mootdx()
        df = client.block()
        if df is None or df.empty:
            return {"total_sectors": 0, "total_mappings": 0, "elapsed_sec": 0}

        conn = self._get_conn()
        # 清空旧数据
        conn.execute("DELETE FROM stock_sector")

        # mootdx block() 返回的 blockname 可能是 GBK 编码
        # pandas 已自动处理编码，直接用即可
        # block_type=2 是个股-板块归属关系
        block_df = df[df["block_type"] == 2]

        rows = []
        for _, row in block_df.iterrows():
            code = str(row["code"]).strip()
            blockname = str(row["blockname"]).strip()
            if code and blockname and len(code) == 6 and code.isdigit():
                rows.append((code, blockname))

        conn.executemany(
            "INSERT OR IGNORE INTO stock_sector (symbol, sector) VALUES (?, ?)",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO sector_meta (key, value) VALUES (?, ?)",
            ("last_refresh", str(time.time())),
        )
        conn.commit()

        elapsed = time.perf_counter() - t0

        # 统计
        total_mappings = len(rows)
        total_sectors = len(set(r[1] for r in rows))

        return {
            "total_sectors": total_sectors,
            "total_mappings": total_mappings,
            "elapsed_sec": round(elapsed, 2),
        }

    def get_industry(self, symbol: str) -> str:
        """获取某只股票所属行业（返回第一个匹配）。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT sector FROM stock_sector WHERE symbol = ? LIMIT 1",
            (symbol,),
        ).fetchone()
        return row[0] if row else "未知"

    def get_all_sectors(self, symbol: str) -> list[str]:
        """获取某只股票所属的所有板块。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT sector FROM stock_sector WHERE symbol = ?",
            (symbol,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_all_mapping(self) -> dict[str, list[str]]:
        """获取全量 symbol → [sectors] 映射。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT symbol, sector FROM stock_sector ORDER BY symbol"
        ).fetchall()
        mapping: dict[str, list[str]] = {}
        for symbol, sector in rows:
            if symbol not in mapping:
                mapping[symbol] = []
            mapping[symbol].append(sector)
        return mapping

    def get_industry_mapping(self) -> dict[str, str]:
        """获取 symbol → 主行业映射（每只股票取第一个板块）。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT symbol, sector FROM stock_sector GROUP BY symbol"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def sector_list(self) -> list[str]:
        """获取所有唯一板块名。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT sector FROM stock_sector ORDER BY sector"
        ).fetchall()
        return [r[0] for r in rows]

    def sector_stock_count(self) -> dict[str, int]:
        """每个板块的股票数量。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT sector, COUNT(DISTINCT symbol) FROM stock_sector GROUP BY sector ORDER BY COUNT(DISTINCT symbol) DESC"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def needs_refresh(self) -> bool:
        """检查是否需要刷新（无数据或超过 1 天）。"""
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM stock_sector").fetchone()[0]
        if count == 0:
            return True
        return False

    def stats(self) -> dict:
        conn = self._get_conn()
        total_mappings = conn.execute("SELECT COUNT(*) FROM stock_sector").fetchone()[0]
        total_symbols = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM stock_sector"
        ).fetchone()[0]
        total_sectors = conn.execute(
            "SELECT COUNT(DISTINCT sector) FROM stock_sector"
        ).fetchone()[0]
        return {
            "total_mappings": total_mappings,
            "total_symbols": total_symbols,
            "total_sectors": total_sectors,
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1),
        }

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
