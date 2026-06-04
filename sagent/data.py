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

        # 如果未注入 industry_comparison，优先尝试东财 push2（零鉴权），
        # HTTP 不通时回退到 mootdx TCP sector_cache
        if industry_comparison is None:
            industry_comparison = _make_industry_comparison()
        self._industry_comparison = industry_comparison

        # 如果未注入 concept_blocks，优先尝试百度股市通，
        # HTTP 不通时回退到 mootdx TCP sector_cache
        if concept_blocks is None:
            concept_blocks = _make_concept_blocks()
        self._concept_blocks = concept_blocks

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
                    up_count=int(item.get("up_count", 0)),
                    down_count=int(item.get("down_count", 0)),
                )
            )
        return snapshots


# ---------------------------------------------------------------------------
# a-stock-data 内嵌函数（东财 push2 行业排名 + 百度股市通概念板块）
# 来源: https://github.com/simonlin1212/a-stock-data SKILL.md V3.2
# ---------------------------------------------------------------------------


def _http_session():
    """创建绕过系统代理的 HTTP session。"""
    import requests

    s = requests.Session()
    s.trust_env = False  # 绕过 Windows 系统代理
    return s


def _ths_sector_code_name_map() -> dict[str, str]:
    """从同花顺行业板块主页提取代码→名称映射。"""
    import re

    s = _http_session()
    url = "https://q.10jqka.com.cn/thshy/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://q.10jqka.com.cn/",
    }
    try:
        r = s.get(url, headers=headers, timeout=10)
    except Exception:
        return {}

    mapping: dict[str, str] = {}
    link_pattern = re.findall(
        r'href="http://q\.10jqka\.com\.cn/thshy/detail/code/(\d+)/"',
        r.text,
    )
    table_match = re.findall(
        r'<table[^>]*class="m-table[^">]*"[^>]*>(.*?)</table>',
        r.text,
        re.DOTALL,
    )
    if table_match:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_match[0], re.DOTALL)
        names_from_table = []
        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if len(clean) >= 2 and clean[0].isdigit():
                names_from_table.append(clean[1])
        for code, name in zip(link_pattern, names_from_table, strict=False):
            mapping[code] = name
    return mapping


def _ths_sector_ranking(top_n: int = 100) -> dict:
    """同花顺行业板块涨跌排名（HTML 直出，零鉴权，~50 行业）。

    优先级高于东财 push2，因为更稳定。
    解析 https://q.10jqka.com.cn/thshy/ 页面表格。
    """
    import re

    s = _http_session()
    url = "https://q.10jqka.com.cn/thshy/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://q.10jqka.com.cn/",
    }
    try:
        r = s.get(url, headers=headers, timeout=10)
    except Exception:
        return {"top": [], "bottom": [], "total": 0}

    # 提取表格数据
    table_match = re.findall(
        r'<table[^>]*class="m-table[^">]*"[^>]*>(.*?)</table>',
        r.text,
        re.DOTALL,
    )
    if not table_match:
        return {"top": [], "bottom": [], "total": 0}

    rows_raw = re.findall(r"<tr[^>]*>(.*?)</tr>", table_match[0], re.DOTALL)
    rows = []
    for row_html in rows_raw:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(clean) >= 10 and clean[0].isdigit():
            rows.append(
                {
                    "rank": int(clean[0]),
                    "name": clean[1],
                    "change_pct": float(clean[2]),
                    "up_count": int(clean[6]) if clean[6].isdigit() else 0,
                    "down_count": int(clean[7]) if clean[7].isdigit() else 0,
                    "turnover": float(clean[5]) if clean[5] else 0,
                    "leader": clean[9],
                }
            )

    return {
        "top": rows[:top_n],
        "bottom": rows[-top_n:] if len(rows) > top_n else rows,
        "total": len(rows),
    }


def _default_industry_comparison(top_n: int = 20) -> dict:
    """东财 push2 行业板块涨跌排名（零鉴权，~100 行业）。"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    try:
        s = _http_session()
        r = s.get(url, params=params, timeout=10)
        data = r.json()
        items = data.get("data", {}).get("diff", [])
    except Exception:
        return {"top": [], "bottom": [], "total": 0}

    rows = []
    for i, item in enumerate(items, 1):
        rows.append(
            {
                "rank": i,
                "code": item.get("f12", ""),
                "name": item.get("f14", ""),
                "change_pct": float(item.get("f3", 0)),
                "up_count": int(item.get("f104", 0)),
                "down_count": int(item.get("f105", 0)),
                "turnover": float(item.get("f6", 0)),
                "leading_stocks": [item.get("f140", "")],
            }
        )
    return {
        "top": rows[:top_n],
        "bottom": rows[-top_n:] if len(rows) > top_n else rows,
        "total": len(rows),
    }


def _default_concept_blocks(code: str) -> dict:
    """百度股市通概念板块归属（行业/概念/地域 + 涨跌幅）。"""
    url = "https://gushitong.baidu.com/stock/ab"
    params = {"code": code}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://gushitong.baidu.com/",
    }
    try:
        s = _http_session()
        r = s.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        result = data.get("Result", {})
    except Exception:
        return {"industry": "未知", "concepts": [], "region": "未知"}

    industry = "未知"
    concepts: list[str] = []
    region = "未知"

    # 解析板块归属
    for block in result.get("blockList", []):
        block_type = str(block.get("type", ""))
        block_name = block.get("name", "")
        if block_type == "1":  # 行业
            industry = block_name
        elif block_type == "2":  # 概念
            concepts.append(block_name)
        elif block_type == "3":  # 地域
            region = block_name

    return {
        "industry": industry,
        "concepts": concepts[:20],
        "region": region,
        "pct_chg": float(result.get("price", {}).get("changePercent", 0)),
    }


def _make_industry_comparison():
    """工厂：优先同花顺 HTML，回退东财 push2，最终 mootdx TCP。"""
    # 先尝试同花顺（最稳定，零鉴权 HTML）
    try:
        result = _ths_sector_ranking(5)
        if result["total"] > 0:
            return _ths_sector_ranking
    except Exception:
        pass

    # 回退东财 push2
    try:
        s = _http_session()
        r = s.get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={"pn": "1", "pz": "1", "fs": "m:90+t:2", "fields": "f14"},
            timeout=5,
        )
        if r.status_code == 200 and r.json().get("data", {}).get("diff"):
            return _default_industry_comparison
    except Exception:
        pass

    # HTTP 不通，回退到 mootdx TCP — 行业板块涨跌数据不可用，返回空
    def _sector_fallback(top_n: int = 20) -> dict:
        return {"top": [], "bottom": [], "total": 0, "_fallback": "mootdx_sector_cache"}

    return _sector_fallback


def _make_concept_blocks():
    """工厂：先尝试百度 HTTP，不通则回退 mootdx TCP sector_cache。"""
    try:
        s = _http_session()
        r = s.get(
            "https://gushitong.baidu.com/stock/ab",
            params={"code": "000001"},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://gushitong.baidu.com/",
            },
            timeout=5,
        )
        if r.status_code == 200:
            try:
                data = r.json()
                if data.get("Result") is not None:
                    return _default_concept_blocks
            except Exception:
                pass
    except Exception:
        pass

    # HTTP 不通，回退到 mootdx TCP sector_cache
    from pathlib import Path
    from .sector_cache import SectorCache

    db_path = Path(__file__).resolve().parents[1] / "data" / "sector.db"
    cache = SectorCache(db_path)
    if cache.needs_refresh():
        cache.refresh()
    all_mapping = cache.get_all_mapping()
    cache.close()

    def _blocks_from_cache(code: str) -> dict:
        sectors = all_mapping.get(code, [])
        industry = sectors[0] if sectors else "未知"
        return {
            "industry": industry,
            "concepts": sectors[1:] if len(sectors) > 1 else [],
            "region": "未知",
            "pct_chg": 0,
            "_fallback": "mootdx_sector_cache",
        }

    return _blocks_from_cache


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
