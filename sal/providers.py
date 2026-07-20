#!/usr/bin/env python3
"""
SAL Concrete Providers
======================
Implements data fetching for each external source with unified interface.
All providers return DTOs from sal.interfaces, not raw dicts.
"""
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from sal.interfaces import (
    BigTechCAPEX,
    CacheMissError,
    DataParseError,
    DailyPrice,
    EarningsCallSignal,
    FinancialDataProvider,
    ForeignOwnership,
    InstitutionalFlow,
    InstitutionalFlowProvider,
    SECDataProvider,
    TWSEDataProvider,
    QuoteProvider,
    MonthlyRevenue,
    CacheProvider,
    ProviderNotFoundError,
    QuarterlyMargin,
    SALProviderError,
    SEC13FHolding,
)


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
CACHE_DIR = Path("local_cache")
CACHE_DIR.mkdir(exist_ok=True)

FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_AFTER_TRADING_URL = "https://www.twse.com.tw/rwd/zh/afterTrading"
YAHOO_FINANCE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
SEC_EDGAR_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

CACHE_KEEP = 3
FINANCIAL_CACHE_MAX_AGE_DAYS = 7

# curl_cffi for bypassing SEC TLS fingerprint blocking
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

# ──────────────────────────────────────────────
# User-Agent rotation
# ──────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
]

# ──────────────────────────────────────────────
# Session with rotation
# ──────────────────────────────────────────────
_session = requests.Session()
_ua_index = 0


def _get_headers(extra: Optional[Dict] = None) -> Dict[str, str]:
    global _ua_index
    headers = {
        "User-Agent": USER_AGENTS[_ua_index % len(USER_AGENTS)],
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    _ua_index += 1
    if extra:
        headers.update(extra)
    return headers


# ──────────────────────────────────────────────
# Cache Utilities
# ──────────────────────────────────────────────
def _build_cache_key(*parts: str) -> str:
    raw = "_".join(str(p) for p in parts if p is not None)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")


def _write_circular_cache(cache_key: str, payload: Dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filepath = CACHE_DIR / f"{cache_key}_{timestamp}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    prefix = f"{cache_key}_"
    cache_files = sorted(
        f for f in CACHE_DIR.glob(f"{prefix}*.json")
    )
    for old_file in cache_files[:-CACHE_KEEP]:
        try:
            old_file.unlink()
        except OSError:
            pass


def _read_latest_cache(cache_key: str) -> Optional[Dict]:
    if not CACHE_DIR.exists():
        return None

    prefix = f"{cache_key}_"
    cache_files = sorted(
        f for f in CACHE_DIR.glob(f"{prefix}*.json")
    )
    if not cache_files:
        return None

    latest = cache_files[-1]
    try:
        with open(latest, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _read_fresh_cache(cache_key: str, max_age_hours: int) -> Optional[Dict]:
    cached = _read_latest_cache(cache_key)
    if cached is None:
        return None

    cached_at = cached.get("cached_at")
    if not cached_at:
        return None

    try:
        cached_dt = dt.datetime.fromisoformat(cached_at)
    except ValueError:
        return None

    if dt.datetime.now() - cached_dt > dt.timedelta(hours=max_age_hours):
        return None

    return cached


def _is_valid_yahoo_chart(data) -> bool:
    """判斷 Yahoo Finance chart 回應是否含有效資料。

    Yahoo 限流或查無資料時，常以 HTTP 200 回傳
    ``{"chart": {"result": null, "error": {...}}}``。此類回應不得被視為
    有效，否則會（1）被寫入 1 小時快取而毒化後續讀取、（2）導致
    ``get_current_price`` 回傳 None 使宏觀 ADR 分析持續降級。
    """
    if not isinstance(data, dict):
        return False
    chart = data.get("chart")
    if not isinstance(chart, dict):
        return False
    if chart.get("error"):
        return False
    return bool(chart.get("result"))


# ──────────────────────────────────────────────
# FinMind Provider (implements FinancialDataProvider, InstitutionalFlowProvider)
# ──────────────────────────────────────────────
class FinMindProvider(FinancialDataProvider, InstitutionalFlowProvider):
    """FinMind API data provider for Taiwan stock data."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("FINMIND_TOKEN")

    def _fetch(
        self,
        dataset: str,
        data_id: str,
        start_date: str,
        end_date: str,
        cache_key: Optional[str] = None,
        cache_hours: int = 24,
    ) -> List[Dict]:
        """Internal fetch with caching."""
        if cache_key is None:
            cache_key = _build_cache_key("finmind", dataset, data_id)

        # Try cache first
        if cache_hours > 0:
            cached = _read_fresh_cache(cache_key, cache_hours)
            if cached:
                print(f"  -> 使用快取: {cache_key} (cached_at={cached.get('cached_at')})")
                return cached.get("data", [])

        params = {
            "dataset": dataset,
            "data_id": data_id,
            "start_date": start_date,
            "end_date": end_date,
        }
        if self.token:
            params["token"] = self.token

        print(f"Fetching {dataset} for {data_id} from {start_date} to {end_date}...")
        try:
            resp = _session.get(FINMIND_API_URL, params=params, headers=_get_headers(), timeout=30)
        except requests.RequestException as exc:
            if cache_hours > 0:
                cached = _read_latest_cache(cache_key)
                if cached:
                    print(f"  -> API失敗，回退快取: {cache_key}")
                    return cached.get("data", [])
            raise SALProviderError(f"FinMind request failed: {exc}") from exc

        if resp.status_code != 200:
            if cache_hours > 0:
                cached = _read_latest_cache(cache_key)
                if cached:
                    return cached.get("data", [])
            raise SALProviderError(f"FinMind API {resp.status_code}: {resp.text}")

        data = resp.json()
        if data.get("status") != 200:
            if cache_hours > 0:
                cached = _read_latest_cache(cache_key)
                if cached:
                    return cached.get("data", [])
            raise SALProviderError(f"FinMind error: {data.get('msg')}")

        records = data.get("data", [])
        _write_circular_cache(
            cache_key,
            {
                "source": "FinMind",
                "dataset": dataset,
                "data_id": data_id,
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": records,
            },
        )
        print(f"  -> Received {len(records)} records.")
        return records

    # ─── FinancialDataProvider ───

    def get_monthly_revenue(self, stock_id: str = "2330", months: int = 24) -> List[MonthlyRevenue]:
        """Get monthly revenue records."""
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=months * 31)
        raw = self._fetch(
            "TaiwanStockMonthRevenue",
            stock_id,
            start_date.isoformat(),
            end_date.isoformat(),
            cache_hours=24,
        )
        result = []
        for r in raw:
            date_str = r.get("date", "")
            if not date_str:
                continue
            try:
                year = int(date_str[:4])
                month = int(date_str[5:7])
                revenue = float(r.get("revenue", 0))
            except (ValueError, TypeError):
                continue
            yoy = r.get("revenue_yoy")
            if yoy is not None:
                try:
                    yoy = float(yoy)
                except (ValueError, TypeError):
                    yoy = None
            result.append(MonthlyRevenue(year=year, month=month, revenue=revenue, yoy_pct=yoy))
        return result

    def get_quarterly_margins(self, stock_id: str = "2330", quarters: int = 8) -> List[QuarterlyMargin]:
        """Get quarterly margins (gross, operating, net) and EPS."""
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=quarters * 91)
        raw = self._fetch(
            "TaiwanStockFinancialStatements",
            stock_id,
            start_date.isoformat(),
            end_date.isoformat(),
            cache_hours=168,  # 7 days
        )
        # Group by quarter
        quarterly: Dict[Tuple[int, int], Dict] = {}
        for r in raw:
            date_str = r.get("date", "")
            if not date_str:
                continue
            try:
                year = int(date_str[:4])
                month = int(date_str[5:7])
                quarter = (month - 1) // 3 + 1
                key = (year, quarter)
            except (ValueError, TypeError):
                continue
            if key not in quarterly:
                quarterly[key] = {}
            statement_type = r.get("type", "")
            value = r.get("value")
            if value is not None:
                quarterly[key][statement_type] = value

        def _get_val(vals: Dict, keys: List[str]) -> Optional[float]:
            for k in keys:
                if k in vals:
                    try:
                        return float(vals[k])
                    except (ValueError, TypeError):
                        continue
            return None

        result = []
        for (year, quarter), vals in sorted(quarterly.items()):
            revenue = _get_val(vals, ["Revenue", "TotalRevenue"])
            gross = _get_val(vals, ["GrossProfit", "Gross_Profit"])
            op_income = _get_val(vals, ["OperatingIncome", "Operating_Income"])
            net_income = _get_val(vals, ["NetIncome", "Net_Income", "IncomeAfterTaxes", "ProfitLossAttributableToOwnersOfParent"])
            eps = _get_val(vals, ["EPS", "BasicEPS"])

            qm = QuarterlyMargin(
                year=year,
                quarter=quarter,
                gross_margin_pct=(gross / revenue * 100) if revenue and gross else None,
                operating_margin_pct=(op_income / revenue * 100) if revenue and op_income else None,
                net_margin_pct=(net_income / revenue * 100) if revenue and net_income else None,
                eps=eps,
            )
            result.append(qm)
        return result

    def get_latest_quarter_eps(self, stock_id: str = "2330") -> Optional[float]:
        """Get latest quarter EPS."""
        margins = self.get_quarterly_margins(stock_id, quarters=1)
        return margins[0].eps if margins else None

    # ─── InstitutionalFlowProvider ───

    def get_institutional_flow(
        self,
        stock_id: str = "2330",
        days: int = 30,
    ) -> List[InstitutionalFlow]:
        """Get institutional investors buy/sell records."""
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=days)
        raw = self._fetch(
            "TaiwanStockInstitutionalInvestorsBuySell",
            stock_id,
            start_date.isoformat(),
            end_date.isoformat(),
            cache_hours=6,
        )
        result = []
        for r in raw:
            date_str = r.get("date", "")
            if not date_str:
                continue
            try:
                date = dt.datetime.fromisoformat(date_str)
                foreign = int(r.get("Foreign_Investor", 0) or 0)
                trust = int(r.get("Investment_Trust", 0) or 0)
                dealer = int(r.get("Dealer", 0) or 0)
            except (ValueError, TypeError):
                continue
            result.append(InstitutionalFlow(
                date=date,
                foreign_net=foreign,
                trust_net=trust,
                dealer_net=dealer,
            ))
        return result

    def get_foreign_ownership(
        self,
        stock_id: str = "2330",
        days: int = 252,
    ) -> List[ForeignOwnership]:
        """Get foreign ownership percentage history."""
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=days)
        raw = self._fetch(
            "TaiwanStockShareholding",
            stock_id,
            start_date.isoformat(),
            end_date.isoformat(),
            cache_hours=168,
        )
        result = []
        for r in raw:
            date_str = r.get("date", "")
            if not date_str:
                continue
            try:
                date = dt.datetime.fromisoformat(date_str)
                pct = float(r.get("ForeignInvestmentSharesRatio", 0) or 0)
                shares = int(r.get("ForeignInvestmentShares", 0) or 0)
                total = int(r.get("NumberOfSharesIssued", 0) or 0)
            except (ValueError, TypeError):
                continue
            result.append(ForeignOwnership(
                date=date,
                pct=pct,
                shares=shares,
                total_shares=total,
            ))
        return result

    # ─── Market data (FinMind daily prices) ───

    def get_daily_prices(self, stock_id: str = "2330", days: int = 60) -> List[DailyPrice]:
        """Get daily OHLCV from FinMind."""
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=days)
        raw = self._fetch(
            "TaiwanStockDailyTrading",
            stock_id,
            start_date.isoformat(),
            end_date.isoformat(),
            cache_hours=6,
        )
        result = []
        for r in raw:
            date_str = r.get("date", "")
            if not date_str:
                continue
            try:
                date = dt.datetime.fromisoformat(date_str)
                o = float(r.get("open", 0))
                h = float(r.get("max", 0))
                l = float(r.get("min", 0))
                c = float(r.get("close", 0))
                v = int(r.get("Trading_Volume", 0) or 0)
                t = int(r.get("Trading_Turnover", 0) or 0)
            except (ValueError, TypeError):
                continue
            result.append(DailyPrice(
                date=date,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                turnover=t,
            ))
        return result


# ──────────────────────────────────────────────
# TWSE Provider (implements TWSEDataProvider)
# ──────────────────────────────────────────────
class TWSEProvider(TWSEDataProvider):
    """TWSE (Taiwan Stock Exchange) data provider."""

    def __init__(self):
        self.session = _session

    def _fetch_json(
        self,
        endpoint: str,
        params: Dict,
        cache_key: str,
        cache_hours: int = 24,
    ) -> Tuple[Optional[Dict], bool]:
        """Fetch JSON from TWSE with caching.

        Returns a tuple of (data, from_cache):
          - data: the inner raw response dict (consistent with the prior
            "return cached.get('data')" behaviour), or None on miss/error.
          - from_cache: True when the result came from a fresh cache hit
            (no network request was issued), False when a live request ran.
        """
        if cache_hours > 0:
            cached = _read_fresh_cache(cache_key, cache_hours)
            if cached:
                # Unwrap: cache stores {source, cached_at, data:<raw response>};
                # live fetch returns the inner raw dict, so do the same here.
                return cached.get("data"), True

        url = f"{TWSE_AFTER_TRADING_URL}/{endpoint}"
        try:
            resp = self.session.get(url, params=params, headers=_get_headers(), timeout=30)
        except requests.RequestException as exc:
            cached = _read_latest_cache(cache_key)
            if cached:
                return cached, True
            raise SALProviderError(f"TWSE request failed: {exc}") from exc

        if resp.status_code != 200:
            cached = _read_latest_cache(cache_key)
            if cached:
                return cached, True
            raise SALProviderError(f"TWSE API {resp.status_code}")

        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise DataParseError("TWSE response not valid JSON")

        _write_circular_cache(
            cache_key,
            {
                "source": "TWSE",
                "endpoint": endpoint,
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": data,
            },
        )
        return data, False

    def get_stock_day(self, stock_id: str = "2330", year_month: Optional[str] = None) -> List[DailyPrice]:
        """Get daily OHLCV for a stock (STOCK_DAY)."""
        if year_month is None:
            year_month = dt.date.today().strftime("%Y%m")

        params = {
            "response": "json",
            "date": year_month,
            "stockNo": stock_id,
            "_": str(int(time.time() * 1000)),
        }
        cache_key = _build_cache_key("twse", "STOCK_DAY", stock_id, year_month)

        data, _ = self._fetch_json("STOCK_DAY", params, cache_key, cache_hours=24)
        if not data or data.get("stat") != "OK":
            return []

        fields = data.get("fields", [])
        records = data.get("data", [])
        result = []
        for row in records:
            rec = dict(zip(fields, row))
            try:
                # TWSE uses Chinese field names
                date_str = rec.get("日期", "")
                # Convert ROC date format "115/07/01" to datetime
                if date_str:
                    parts = date_str.split("/")
                    if len(parts) == 3:
                        roc_year = int(parts[0])
                        month = int(parts[1])
                        day = int(parts[2])
                        gregorian_year = roc_year + 1911
                        date = dt.datetime(gregorian_year, month, day)
                    else:
                        continue
                else:
                    continue

                # Map Chinese field names to values
                def get_num(key: str) -> float:
                    val = rec.get(key, "0")
                    if isinstance(val, str):
                        val = val.replace(",", "")
                    return float(val or 0)

                def get_int(key: str) -> int:
                    val = rec.get(key, "0")
                    if isinstance(val, str):
                        val = val.replace(",", "")
                    return int(val or 0)

                result.append(DailyPrice(
                    date=date,
                    open=get_num("開盤價"),
                    high=get_num("最高價"),
                    low=get_num("最低價"),
                    close=get_num("收盤價"),
                    volume=get_int("成交股數"),
                    turnover=get_int("成交金額"),
                ))
            except (ValueError, TypeError, KeyError):
                continue
        return result

    def get_market_turnover(self, days: int = 30) -> List[Tuple[dt.datetime, int]]:
        """Get market-wide trading value (FMTQIK)."""
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=days * 2)

        all_records = []
        current = start_date
        while current <= end_date:
            ym = current.strftime("%Y%m")
            params = {
                "response": "json",
                "date": ym,
                "selectType": "ALL",
                "_": str(int(time.time() * 1000)),
            }
            cache_key = _build_cache_key("twse", "FMTQIK", ym)

            data, from_cache = self._fetch_json("FMTQIK", params, cache_key, cache_hours=24)
            # 僅在實際發出網路請求時退避，命中快取（例行執行）時跳過，減少總耗時。
            if not from_cache:
                time.sleep(0.3)
            if data and data.get("stat") == "OK":
                fields = data.get("fields", [])
                records = data.get("data", [])
                for row in records:
                    rec = dict(zip(fields, row))
                    rec = {k.strip(): v for k, v in rec.items()}
                    try:
                        date_str = rec.get("Date", "")
                        date = dt.datetime.strptime(date_str, "%Y/%m/%d")
                        value_str = rec.get("TotalValue", "0") or "0"
                        value = int(value_str.replace(",", ""))
                        all_records.append((date, value))
                    except (ValueError, TypeError):
                        continue

            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

            time.sleep(0.3)

        return sorted(all_records, key=lambda x: x[0])[-days:]


# ──────────────────────────────────────────────
# Yahoo Finance Provider (implements QuoteProvider)
# ──────────────────────────────────────────────
class YahooFinanceProvider(QuoteProvider):
    """Yahoo Finance data provider for ADR, FX, and US stocks."""

    def __init__(self):
        self.session = _session

    def get_chart(
        self,
        symbol: str,
        period1: int = 0,
        period2: int = 9999999999,
        interval: str = "1d",
    ) -> Optional[Dict]:
        """Get chart data for a symbol."""
        cache_key = _build_cache_key("yahoo", "chart", symbol, interval)
        cached = _read_fresh_cache(cache_key, 1)  # 1 hour cache
        if cached:
            # Unwrap to the inner raw response (consistent with live fetch).
            data = cached.get("data")
            # 只有含有效資料的新鮮快取才可直接回傳；曾被寫入的限流/空回應
            # 需略過，改走實際請求以嘗試恢復。
            if _is_valid_yahoo_chart(data):
                return data

        url = f"{YAHOO_FINANCE_URL}/{symbol}"
        params = {
            "period1": period1,
            "period2": period2,
            "interval": interval,
            "includePrePost": "false",
        }
        try:
            resp = self.session.get(url, params=params, headers=_get_headers(), timeout=15)
        except requests.RequestException as exc:
            fallback = self._latest_valid_chart(cache_key)
            if fallback is not None:
                return fallback
            raise SALProviderError(f"Yahoo Finance request failed: {exc}") from exc

        if resp.status_code != 200:
            fallback = self._latest_valid_chart(cache_key)
            if fallback is not None:
                return fallback
            raise SALProviderError(f"Yahoo Finance API {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            fallback = self._latest_valid_chart(cache_key)
            if fallback is not None:
                return fallback
            raise SALProviderError(f"Yahoo Finance 回應非 JSON: {exc}") from exc

        if not _is_valid_yahoo_chart(data):
            # Yahoo 限流或查無資料（result 為 null / 帶 error 物件）。
            # 絕不寫入快取——否則會毒化 1 小時 TTL，使宏觀 ADR 分析持續降級。
            # 優先回退最近一次「有效」快取，否則上拋讓上層優雅降級。
            fallback = self._latest_valid_chart(cache_key)
            if fallback is not None:
                return fallback
            chart_err = data.get("chart", {}).get("error") if isinstance(data, dict) else None
            raise SALProviderError(
                f"Yahoo Finance 回應無有效資料: {chart_err or 'result 為空'}"
            )

        _write_circular_cache(
            cache_key,
            {
                "source": "YahooFinance",
                "symbol": symbol,
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": data,
            },
        )
        return data

    def _latest_valid_chart(self, cache_key: str) -> Optional[Dict]:
        """回退到最近一次含有效資料的快取（略過曾寫入的限流/空回應）。"""
        cached = _read_latest_cache(cache_key)
        if cached is None:
            return None
        data = cached.get("data")
        return data if _is_valid_yahoo_chart(data) else None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current regular market price.

        回傳 None（而非 0.0）表示無有效報價，讓上層（如宏觀 ADR 分析）
        能明確偵測並優雅降級，避免以 0 價進行折溢價計算。
        """
        data = self.get_chart(symbol)
        if not _is_valid_yahoo_chart(data):
            return None
        meta = data["chart"]["result"][0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None

    def get_tsmc_adr_price(self) -> Optional[float]:
        """Get TSM ADR current price."""
        return self.get_current_price("TSM")

    def get_usd_twd_rate(self) -> Optional[float]:
        """Get USD/TWD exchange rate."""
        return self.get_current_price("TWD=X")


# ──────────────────────────────────────────────
# SEC EDGAR Provider
# ──────────────────────────────────────────────
class SECEdgarProvider(SECDataProvider):
    """SEC EDGAR data provider for 13F filings and company facts."""

    def __init__(self):
        self.session = _session
        self.session.headers.update({
            "User-Agent": "Sentimental-Quant-Lab/1.0 (jimisu@example.com)",
            "Accept": "application/json",
        })

    def get_company_facts(self, cik: str) -> Optional[Dict]:
        """Get company facts (XBRL) for a CIK."""
        cik_padded = cik.zfill(10)
        cache_key = _build_cache_key("sec", "companyfacts", cik_padded)
        cached = _read_fresh_cache(cache_key, 168)
        if cached:
            return cached.get("data")

        url = f"{SEC_EDGAR_URL}/CIK{cik_padded}.json"
        try:
            resp = self.session.get(url, timeout=30)
        except requests.RequestException as exc:
            cached = _read_latest_cache(cache_key)
            if cached:
                return cached.get("data")
            raise SALProviderError(f"SEC companyfacts request failed: {exc}") from exc

        if resp.status_code != 200:
            cached = _read_latest_cache(cache_key)
            if cached:
                return cached.get("data")
            if resp.status_code == 403:
                raise SALProviderError("SEC API 403 - IP may be blocked")
            raise SALProviderError(f"SEC companyfacts {resp.status_code}")

        data = resp.json()
        _write_circular_cache(
            cache_key,
            {
                "source": "SEC",
                "type": "companyfacts",
                "cik": cik_padded,
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": data,
            },
        )
        return data

    def fetch_submissions_raw(self, cik: str) -> Dict:
        """Fetch SEC submissions JSON (no caching).

        Pure transport: raises SALProviderError on network/HTTP failure so the
        caller (SAL cache wrapper or an upper-layer cache) owns fallback policy.
        """
        cik_padded = cik.zfill(10)
        url = f"{SEC_EDGAR_URL}/CIK{cik_padded}.json"
        try:
            resp = self.session.get(url, timeout=30)
        except requests.RequestException as exc:
            raise SALProviderError(f"SEC submissions request failed: {exc}") from exc
        if resp.status_code == 403:
            raise SALProviderError("SEC API 403 - IP may be blocked")
        if resp.status_code != 200:
            raise SALProviderError(f"SEC submissions {resp.status_code}")
        return resp.json()

    def get_submissions(self, cik: str) -> Optional[Dict]:
        """Get recent filings submissions for a CIK (cached)."""
        cik_padded = cik.zfill(10)
        cache_key = _build_cache_key("sec", "submissions", cik_padded)
        cached = _read_fresh_cache(cache_key, 168)
        if cached:
            return cached.get("data")

        try:
            data = self.fetch_submissions_raw(cik)
        except SALProviderError:
            cached = _read_latest_cache(cache_key)
            if cached:
                return cached.get("data")
            raise

        _write_circular_cache(
            cache_key,
            {
                "source": "SEC",
                "type": "submissions",
                "cik": cik_padded,
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": data,
            },
        )
        return data

    def _discover_13f_urls(self, cik: str, accession: str) -> List[Tuple[str, str]]:
        """Systematically try all candidate 13F holdings URLs.

        SEC Archives paths are inconsistent; try both the accession prefix and
        the CIK as the path component, with .txt (standard requests) and
        infotable.xml (needs curl_cffi TLS bypass) variants.
        """
        accession_clean = accession.replace("-", "")
        acc_prefix = accession.split("-")[0]
        cik_paths = list(dict.fromkeys([acc_prefix, cik]))  # dedupe, keep order
        urls = []
        for cp in cik_paths:
            base = f"{SEC_ARCHIVES_URL}/{cp}/{accession_clean}"
            urls.append((f"{base}/{accession}.txt", "txt"))
            urls.append((f"{base}/xslForm13F_X02/infotable.xml", "xml"))
            urls.append((f"{base}/xslForm13F_X01/infotable.xml", "xml"))
            urls.append((f"{base}/xslForm13F_X02/primary_doc.xml", "xml"))
            urls.append((f"{base}/xslForm13F_X01/primary_doc.xml", "xml"))
        return urls

    def fetch_13f_infotable_raw(self, cik: str, accession: str) -> str:
        """Fetch raw 13F infotable XML/text (no caching).

        Mirrors the prior tracker transport: tries each candidate URL, preferring
        .txt (standard requests) and falling back to infotable.xml via curl_cffi
        (TLS fingerprint bypass). Raises SALProviderError if all candidates fail.
        """
        headers = {
            "User-Agent": "Sentimental-Quant-Lab/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        errors = []
        for url, method in self._discover_13f_urls(cik, accession):
            is_txt = method == "txt"
            try:
                if _HAS_CURL_CFFI:
                    resp = cffi_requests.get(url, headers=headers, impersonate="chrome", timeout=120)
                elif is_txt:
                    resp = self.session.get(url, headers=headers, timeout=120)
                else:
                    continue
            except Exception as exc:
                errors.append(f"{method}:{exc}")
                continue
            if resp.status_code == 200 and len(resp.text) > 100:
                return resp.text
            errors.append(f"{method}:{resp.status_code}")
        raise SALProviderError(
            f"SEC Archives 無法取得持股明細：CIK {cik} Acc {accession}\n"
            f"  嘗試 URL：{len(errors)} 個\n"
            f"  結果：{', '.join(errors[:6])}"
        )

    def get_13f_holdings(
        self,
        cik: str,
        accession_number: str,
    ) -> Optional[str]:
        """
        Get 13F holdings raw XML/text content (cached).

        Returns raw text for parsing by caller. Underlying transport is
        fetch_13f_infotable_raw (curl_cffi TLS bypass for SEC Archives).
        """
        cik_path = accession_number.split("-")[0]
        acc_clean = accession_number.replace("-", "")

        cache_key = _build_cache_key("sec", "13f_infotable", cik, acc_clean)
        cached = _read_fresh_cache(cache_key, 2160)
        if cached:
            return cached.get("data")

        try:
            text = self.fetch_13f_infotable_raw(cik, accession_number)
        except SALProviderError:
            cached = _read_latest_cache(cache_key)
            if cached:
                return cached.get("data")
            raise

        _write_circular_cache(
            cache_key,
            {
                "source": "SEC",
                "type": "13f_infotable",
                "cik": cik,
                "accession": accession_number,
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": text,
            },
        )
        return text


# ──────────────────────────────────────────────
# Cache Provider (implements CacheProvider)
# ──────────────────────────────────────────────
class FileCacheProvider(CacheProvider):
    """File-based cache implementation."""

    def get(self, key: str, max_age_hours: Optional[int] = None) -> Optional[Any]:
        if max_age_hours:
            cached = _read_fresh_cache(key, max_age_hours)
        else:
            cached = _read_latest_cache(key)
        if cached:
            return cached.get("data")
        return None

    def set(self, key: str, value: Any) -> None:
        _write_circular_cache(
            key,
            {
                "source": "CacheProvider",
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": value,
            },
        )

    def delete(self, key: str) -> None:
        prefix = f"{key}_"
        for f in CACHE_DIR.glob(f"{prefix}*.json"):
            try:
                f.unlink()
            except OSError:
                pass

    def clear_expired(self, max_age_hours: int = 24) -> int:
        cleared = 0
        for f in CACHE_DIR.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                cached_at = data.get("cached_at")
                if cached_at:
                    cached_dt = dt.datetime.fromisoformat(cached_at)
                    if dt.datetime.now() - cached_dt > dt.timedelta(hours=max_age_hours):
                        f.unlink()
                        cleared += 1
            except Exception:
                pass
        return cleared


# ──────────────────────────────────────────────
# Provider Registry / Factory
# ──────────────────────────────────────────────
class ProviderRegistry:
    """Central registry for all data providers."""

    _instance: Optional["ProviderRegistry"] = None
    _providers: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._providers:
            self._init_default_providers()

    def _init_default_providers(self):
        """Initialize default provider instances."""
        self._providers["finmind"] = FinMindProvider()
        self._providers["twse"] = TWSEProvider()
        self._providers["yahoo"] = YahooFinanceProvider()
        self._providers["sec"] = SECEdgarProvider()
        self._providers["cache"] = FileCacheProvider()

    def get(self, name: str) -> Any:
        """Get provider by name."""
        if name not in self._providers:
            raise ProviderNotFoundError(f"Provider '{name}' not registered")
        return self._providers[name]

    def register(self, name: str, provider: Any) -> None:
        """Register a custom provider."""
        self._providers[name] = provider

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())


# Global registry instance
registry = ProviderRegistry()


# ──────────────────────────────────────────────
# Convenience Functions
# ──────────────────────────────────────────────
def get_finmind() -> FinMindProvider:
    return registry.get("finmind")


def get_twse() -> TWSEProvider:
    return registry.get("twse")


def get_yahoo() -> YahooFinanceProvider:
    return registry.get("yahoo")


def get_sec() -> SECEdgarProvider:
    return registry.get("sec")


def get_cache() -> FileCacheProvider:
    return registry.get("cache")