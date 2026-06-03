from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .models import DailyBar, SectorSnapshot, StockInfo, TradeDay


class MootdxLike(Protocol):
    def bars(self, symbol: str, category: int, offset: int) -> Any: ...
    def quotes(self, symbol: list[str]) -> Any: ...


class TencentQuoteFunc(Protocol):
    def __call__(self, codes: list[str]) -> dict[str, dict]: ...


class ConceptBlocksFunc(Protocol):
    def __call__(self, code: str) -> dict: ...


class IndustryComparisonFunc(Protocol):
    def __call__(self, top_n: int = 20) -> dict: ...


class AStockDataMarketData:
    """a-stock-data 数据访问层。

    基于 mootdx（TCP 直连通达信，不封 IP）+ 腾讯财经 + 百度股市通 + 同花顺。
    比纯 AKShare 稳定得多，且自带 PE/PB/市值/概念板块/资金流向。

    测试不依赖真实网络；生产运行时如果未安装依赖，会给出清晰中文错误。
    """

    def __init__(
        self,
        mootdx_client: MootdxLike | None = None,
        tencent_quote: TencentQuoteFunc | None = None,
        concept_blocks: ConceptBlocksFunc | None = None,
        industry_comparison: IndustryComparisonFunc | None = None,
    ) -> None:
        if mootdx_client is None:
            try:
                from mootdx.quotes import Quotes

                mootdx_client = Quotes.factory(market="std")
            except Exception as error:
                raise RuntimeError(
                    "未安装或无法连接 mootdx，请先安装：pip install mootdx akshare requests pandas stockstats\n"
                    "或使用 --fixture 运行本地无网络流程。"
                ) from error
        self.mootdx = mootdx_client

        if tencent_quote is None:
            try:
                from importlib import import_module

                # a-stock-data 的 tencent_quote 是 SKILL.md 中的内嵌函数
                # 生产环境直接从 skill 加载；这里尝试动态导入
                skill_module = import_module("a_stock_data")
                tencent_quote = getattr(skill_module, "tencent_quote", None)
            except Exception:
                pass
        self._tencent_quote = tencent_quote

        self._concept_blocks = concept_blocks
        self._industry_comparison = industry_comparison

    def daily_bars(
        self, symbol: str, category: int = 4, offset: int = 300
    ) -> list[DailyBar]:
        """通过 mootdx TCP 获取 K 线。category=4 日线。

        使用向量化解析替代 iterrows，速度提升约 5x。
        """
        from .cache import _parse_bars
        frame = self.mootdx.bars(symbol=symbol, category=category, offset=offset)
        return _parse_bars(symbol, frame)

    def realtime_quotes(self, codes: list[str]) -> dict[str, dict]:
        """通过腾讯财经获取 PE/PB/市值/换手率/涨跌停价。"""
        if self._tencent_quote is not None:
            return self._tencent_quote(codes)
        return {}

    def concept_blocks(self, code: str) -> dict:
        """百度股市通三维归属（行业/概念/地域）+ 当日涨跌幅。"""
        if self._concept_blocks is not None:
            return self._concept_blocks(code)
        return {"industry": "未知", "concepts": [], "region": "未知"}

    def industry_ranking(self, top_n: int = 20) -> dict:
        """同花顺 ~90 行业涨跌排名 + 成交额 + 领涨股。"""
        if self._industry_comparison is not None:
            return self._industry_comparison(top_n)
        return {"top": [], "bottom": [], "total": 0}

    def trade_calendar(self) -> list[TradeDay]:
        """交易日历（通过 AKShare 获取，mootdx 不提供此功能）。"""
        try:
            import akshare as ak

            frame = ak.tool_trade_date_hist_sina()
            return [
                TradeDay(date=str(row.get("trade_date")), is_open=True)
                for row in frame.to_dict("records")
            ]
        except Exception:
            return []

    def stocks(self) -> list[StockInfo]:
        """股票列表（通过 AKShare 获取基础列表，再通过腾讯财经补 PE/市值）。"""
        try:
            import akshare as ak

            frame = ak.stock_info_a_code_name()
            return [
                StockInfo(
                    symbol=str(row.get("code")),
                    name=str(row.get("name")),
                    sector="未知",
                    avg_amount_20d=0,
                )
                for row in frame.to_dict("records")
            ]
        except Exception:
            return []

    def sector_snapshots(self) -> list[SectorSnapshot]:
        """板块快照（通过行业排名构建）。"""
        ranking = self.industry_ranking(top_n=90)
        snapshots: list[SectorSnapshot] = []
        for item in ranking.get("top", []):
            snapshots.append(
                SectorSnapshot(
                    sector=item.get("name", "未知"),
                    date=item.get("date", ""),
                    turnover_rank=item.get("rank", 99),
                    gain_rank=item.get("rank", 99),
                    pct_chg=float(item.get("change_pct", 0)),
                    limit_up_count=int(item.get("limit_up_count", 0)),
                    strong_stocks=item.get("leading_stocks", []),
                )
            )
        return snapshots


class FixtureMarketData:
    """本地 fixture 数据源，用于测试和无网络演示。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.raw = json.loads(path.read_text(encoding="utf-8"))

    def stocks(self) -> list[StockInfo]:
        return [StockInfo(**item) for item in self.raw.get("stocks", [])]

    def daily_bars(self, symbol: str) -> list[DailyBar]:
        return [
            DailyBar(**item) for item in self.raw.get("daily_bars", {}).get(symbol, [])
        ]

    def sector_snapshots(self) -> list[SectorSnapshot]:
        return [SectorSnapshot(**item) for item in self.raw.get("sectors", [])]

    def trade_calendar(self) -> list[TradeDay]:
        return [TradeDay(**item) for item in self.raw.get("trade_calendar", [])]
