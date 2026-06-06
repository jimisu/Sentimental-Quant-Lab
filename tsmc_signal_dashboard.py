#!/usr/bin/env python3
"""
TSMC 信號儀表板
抓取台積電 (2330.TW) 最新 12 個月的月營收 YoY 與最近 4 季的毛利率、營業利益率，
並使用 rich 庫輸出彩色儀表板。
新增：從 TWSE 列出近 10 個交易日成交金額，並偵測個股與大盤交易量連三降。
"""

import datetime as dt
import json
import os
import re
import argparse
import random
import sys
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from rich import box
from rich.console import Console
from rich.table import Table
from data_cache import fetch_with_cache
from tsmc_ai_agents import Orchestrator

API_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_AFTER_TRADING_URL = "https://www.twse.com.tw/rwd/zh/afterTrading"
CACHE_DIR = "local_cache"
CACHE_KEEP = 3
FINANCIAL_CACHE_MAX_AGE_DAYS = 7

# 初始化 Session 以維持 Cookies，並定義多組 User-Agent 以模擬真實瀏覽器
session = requests.Session()
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
]

REVENUE_KEYS = ["Revenue", "TotalRevenue"]
GROSS_PROFIT_KEYS = ["GrossProfit", "Gross_Profit"]
OPERATING_INCOME_KEYS = ["OperatingIncome", "Operating_Income"]
NET_INCOME_KEYS = [
    "IncomeAfterTaxes",
    "Net_Income",
    "NetIncome",
    "Net_Income_Attributable_To_Owners_Of_The_Parent",
    "ProfitLossAttributableToOwnersOfParent",
    "Consolidated_Net_Income_Attributable_To_Stockholders_Of_The_Parent",
    "NetIncomeAfterTax",
    "Net_Income_After_Tax",
]
NET_INCOME_ORIGIN_KEYWORDS = ["本期淨利", "稅後淨利"]
NET_INCOME_ORIGIN_EXCLUDE_KEYWORDS = ["稅前", "綜合損益", "其他綜合", "歸屬"]

# 日期範圍
TODAY = dt.date.today()
TWO_YEARS_AGO = TODAY - dt.timedelta(days=730)  # 約兩年，以便計算 YoY

# TWSE 限制：查詢日期地板，根據回傳訊息彈性調整 (最早可達民國 79/01/04)
TWSE_MIN_DATE = dt.date(1990, 1, 4)


def build_cache_key(*parts) -> str:
    """
    建立檔名安全的 cache key。
    """
    raw_key = "_".join(str(part) for part in parts if part is not None)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_key).strip("_")


def write_circular_cache(cache_key: str, payload: Dict) -> None:
    """
    寫入本機快取，並讓同一 cache key 只保留最新 CACHE_KEEP 份。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filepath = os.path.join(CACHE_DIR, f"{cache_key}_{timestamp}.json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    prefix = f"{cache_key}_"
    cache_files = sorted(
        filename
        for filename in os.listdir(CACHE_DIR)
        if filename.startswith(prefix) and filename.endswith(".json")
    )
    for old_filename in cache_files[:-CACHE_KEEP]:
        try:
            os.remove(os.path.join(CACHE_DIR, old_filename))
        except OSError as exc:
            print(f"刪除舊快取失敗: {old_filename} ({exc})", file=sys.stderr)


def read_latest_cache(cache_key: str) -> Optional[Dict]:
    """
    讀取同一 cache key 的最新本機快取。
    """
    if not os.path.exists(CACHE_DIR):
        return None

    prefix = f"{cache_key}_"
    cache_files = sorted(
        filename
        for filename in os.listdir(CACHE_DIR)
        if filename.startswith(prefix) and filename.endswith(".json")
    )
    if not cache_files:
        return None

    latest_path = os.path.join(CACHE_DIR, cache_files[-1])
    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"讀取快取失敗: {latest_path} ({exc})", file=sys.stderr)
        return None


def get_cached_data(cache_key: str):
    """
    取出最新快取中的 data 欄位。
    """
    cached = read_latest_cache(cache_key)
    if cached is None:
        return None
    print(f"  -> 使用本機快取: {cache_key}")
    return cached.get("data")


def read_fresh_cached_payload(cache_key: str, max_age_days: int) -> Optional[Dict]:
    """
    讀取未過期的快取 payload。
    """
    cached = read_latest_cache(cache_key)
    if cached is None:
        return None

    cached_at = cached.get("cached_at")
    if not cached_at:
        return None

    try:
        cached_dt = dt.datetime.fromisoformat(cached_at)
    except ValueError:
        return None

    age = dt.datetime.now() - cached_dt
    if age > dt.timedelta(days=max_age_days):
        return None

    print(f"  -> 使用一週內財務快取: {cache_key} (cached_at={cached_at})")
    return cached


def serialize_quarterly_margins(quarterly_margins: Dict[Tuple[int, int], Dict]) -> Dict[str, Dict]:
    """
    將 tuple key 轉成 JSON 可存的字串 key。
    """
    return {
        f"{year}Q{quarter}": values
        for (year, quarter), values in quarterly_margins.items()
    }


def deserialize_quarterly_margins(payload: Dict) -> Dict[Tuple[int, int], Dict]:
    """
    將 JSON 快取中的季度字串 key 還原成 tuple key。
    """
    result = {}
    for key, values in payload.items():
        match = re.fullmatch(r"(\d{4})Q([1-4])", key)
        if not match:
            continue
        result[(int(match.group(1)), int(match.group(2)))] = values
    return result


def fetch_finmind_dataset(
    dataset: str,
    data_id: str,
    start_date: str,
    end_date: str,
    token: Optional[str] = None,
) -> List[Dict]:
    """
    從 FinMind API 取得資料。
    """
    params = {
        "dataset": dataset,
        "data_id": data_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if token:
        params["token"] = token

    cache_key = build_cache_key("finmind", dataset, data_id)
    cache_metadata = {k: v for k, v in params.items() if k != "token"}

    print(f"Fetching {dataset} for {data_id} from {start_date} to {end_date}...")
    try:
        resp = requests.get(API_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"Error: API request failed: {exc}", file=sys.stderr)
        cached_data = get_cached_data(cache_key)
        if cached_data is not None:
            return cached_data
        sys.exit(1)

    if resp.status_code != 200:
        print(
            f"Error: API request failed with status {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        cached_data = get_cached_data(cache_key)
        if cached_data is not None:
            return cached_data
        sys.exit(1)

    data = resp.json()
    if data.get("status") != 200:
        print(
            f"Error: FinMind returned error status: {data.get('msg')}",
            file=sys.stderr,
        )
        cached_data = get_cached_data(cache_key)
        if cached_data is not None:
            return cached_data
        sys.exit(1)

    records = data.get("data", [])
    write_circular_cache(
        cache_key,
        {
            "source": "FinMind",
            "metadata": cache_metadata,
            "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
            "data": records,
        },
    )
    print(f"  -> Received {len(records)} records.")
    return records


def _fetch_monthly_revenue_records(token: Optional[str] = None) -> List[Dict]:
    """實際呼叫 FinMind API 取得月營收原始記錄"""
    start_date = TWO_YEARS_AGO.isoformat()
    end_date = TODAY.isoformat()
    return fetch_finmind_dataset(
        dataset="TaiwanStockMonthRevenue",
        data_id="2330",
        start_date=start_date,
        end_date=end_date,
        token=token,
    )


def get_monthly_revenue_yoy(token: Optional[str] = None) -> List[Dict]:
    """
    取得最近 12 個月的月營收年增率（YoY）。
    回傳 list of dict，每筆包含 date (YYYY-MM) 和 revenue_yoy (百分比)。
    使用 24 小時快取，避免每日重複抓取。
    """
    # 透過統一快取層取得月營收原始記錄（24 小時 TTL）
    records = fetch_with_cache(
        policy_name="monthly_revenue",
        cache_key="tsmc_monthly_revenue_24m",
        fetch_fn=lambda: _fetch_monthly_revenue_records(token),
    )
    # 將 records 轉換為以日期為 key 的字典，值為 revenue
    revenue_by_date = {}
    for r in records:
        date_str = r.get("date")  # 格式: YYYY-MM-DD
        if not date_str:
            continue
        # 只取年月部分 (YYYY-MM)
        year_month = date_str[:7]  # YYYY-MM
        try:
            revenue = float(r.get("revenue", 0))
        except (ValueError, TypeError):
            continue
        revenue_by_date[year_month] = revenue

    # 產生最近 12 個月的年月列表（從當前月往前推 11 個月，共 12 個月）
    months_yoy = []
    year = TODAY.year
    month = TODAY.month
    for i in range(12):
        # 計算當前月往前 i 個月
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        months_yoy.append(f"{y:04d}-{m:02d}")
    months_yoy = list(reversed(months_yoy))  # 從遠到近排序

    result = []
    for ym in months_yoy:
        if ym not in revenue_by_date:
            # 若當月資料缺失，則跳過（或設為 None）
            continue
        # 計算去年同月的年月
        prev_year = int(ym[:4]) - 1
        prev_ym = f"{prev_year:04d}-{ym[5:7]}"
        if prev_ym not in revenue_by_date:
            # 若去年同月資料缺失，則無法計算 YoY
            continue
        cur_rev = revenue_by_date[ym]
        prev_rev = revenue_by_date[prev_ym]
        if prev_rev == 0:
            yoy = None
        else:
            yoy = (cur_rev - prev_rev) / prev_rev * 100.0
        result.append({"date": ym, "revenue_yoy": yoy})
    return result


def get_financial_value(
    quarter_values: Dict,
    keys: List[str],
    origin_keywords: Optional[List[str]] = None,
    exclude_origin_keywords: Optional[List[str]] = None,
) -> Optional[float]:
    """
    從 FinMind 財報欄位取值；優先用 type，必要時用 origin_name 中文名稱 fallback。
    """
    for key in keys:
        if key in quarter_values:
            return quarter_values[key]

    origin_names = quarter_values.get("_origin_names", {})
    if not origin_keywords:
        return None

    excludes = exclude_origin_keywords or []
    for statement_type, origin_name in origin_names.items():
        if statement_type not in quarter_values:
            continue
        normalized_origin = origin_name.lower()
        if any(keyword.lower() in normalized_origin for keyword in origin_keywords) and not any(
            keyword.lower() in normalized_origin for keyword in excludes
        ):
            return quarter_values[statement_type]

    return None


def get_quarterly_margins(token: Optional[str] = None) -> Dict[Tuple[int, int], Dict]:
    """
    取得最近 4 季的毛利率與營業利益率，並計算季度環比變化。
    回傳 dict，key 為 (year, quarter)，value 為包含以下欄位的 dict:
        - gross_margin: 毛利率 (%)
        - operating_margin: 營業利益率 (%)
        - gross_drop: 與上一季的毛利率變化百分點 (上一季 - 當季)，正數代表下滑
        - op_drop: 與上一季的營業利益率變化百分點 (上一季 - 當季)，正數代表下滑
    對於第一季（最早的一季），drop 為 None。
    """
    cache_key = build_cache_key("financial_agent", "quarterly_margins", "2330")
    cached = read_fresh_cached_payload(cache_key, FINANCIAL_CACHE_MAX_AGE_DAYS)
    if cached is not None:
        return deserialize_quarterly_margins(cached.get("data", {}))

    # 取得過去一年的財務報表（季資料）
    start_date = (TODAY - dt.timedelta(days=500)).isoformat()
    end_date = TODAY.isoformat()
    # 包含 Revenue, GrossProfit, OperatingIncome, NetIncome
    records = fetch_finmind_dataset(
        dataset="TaiwanStockFinancialStatements",
        data_id="2330",
        start_date=start_date,
        end_date=end_date,
        token=token,
    )
    # 我們需要每季的 Revenue, GrossProfit, OperatingIncome
    # 將同一季度的不同 type 值匯總
    quarterly_data = {}  # key: (year, quarter) -> dict of values
    for r in records:
        date_str = r.get("date")  # YYYY-MM-DD
        if not date_str:
            continue
        # 從日期取得年份和季度
        try:
            year = int(date_str[:4])
            month = int(date_str[5:7])
            quarter = (month - 1) // 3 + 1
        except (ValueError, TypeError):
            continue
        key = (year, quarter)
        if key not in quarterly_data:
            quarterly_data[key] = {}
        # 讀取數值
        try:
            value = float(r.get("value", 0))
        except (ValueError, TypeError):
            continue
        statement_type = r.get("type")
        if not statement_type:
            continue
        quarterly_data[key][statement_type] = value
        if r.get("origin_name"):
            quarterly_data[key].setdefault("_origin_names", {})[statement_type] = r.get("origin_name")

    # 計算每季的毛利率和營業利益率，並計算與上一季的變化
    result = {}
    # 先排序季度（從遠到近）
    sorted_quarters = sorted(quarterly_data.keys())
    for idx, (year, quarter) in enumerate(sorted_quarters):
        d = quarterly_data[(year, quarter)]
        
        # 營收
        revenue = get_financial_value(d, REVENUE_KEYS)
        # 毛利
        gross_profit = get_financial_value(d, GROSS_PROFIT_KEYS)
        # 營業利益
        operating_income = get_financial_value(d, OPERATING_INCOME_KEYS)
        # 稅後淨利：保留以稅後淨利金額 / 營收計算稅後淨利率的方式。
        net_income = get_financial_value(
            d,
            NET_INCOME_KEYS,
            origin_keywords=NET_INCOME_ORIGIN_KEYWORDS,
            exclude_origin_keywords=NET_INCOME_ORIGIN_EXCLUDE_KEYWORDS,
        )

        if revenue is None or revenue == 0:
            continue
        gross_margin = (gross_profit / revenue * 100) if gross_profit is not None else None
        operating_margin = (operating_income / revenue * 100) if operating_income is not None else None
        net_margin = (net_income / revenue * 100) if net_income is not None else None

        # 計算與上一季的變化（上一季 - 當季）
        gross_drop = None
        op_drop = None
        net_drop = None
        if idx > 0:
            p_key = sorted_quarters[idx - 1]
            p_d = quarterly_data[p_key]
            
            prev_revenue = get_financial_value(p_d, REVENUE_KEYS)
            prev_gross_profit = get_financial_value(p_d, GROSS_PROFIT_KEYS)
            prev_operating_income = get_financial_value(p_d, OPERATING_INCOME_KEYS)
            prev_net_income = get_financial_value(
                p_d,
                NET_INCOME_KEYS,
                origin_keywords=NET_INCOME_ORIGIN_KEYWORDS,
                exclude_origin_keywords=NET_INCOME_ORIGIN_EXCLUDE_KEYWORDS,
            )

            if prev_revenue is not None and prev_revenue != 0:
                if prev_gross_profit is not None and gross_margin is not None:
                    prev_gross_margin = (prev_gross_profit / prev_revenue * 100)
                    gross_drop = prev_gross_margin - gross_margin
                if prev_operating_income is not None and operating_margin is not None:
                    prev_op_margin = (prev_operating_income / prev_revenue * 100)
                    op_drop = prev_op_margin - operating_margin
                if prev_net_income is not None and net_margin is not None:
                    prev_net_margin = (prev_net_income / prev_revenue * 100)
                    net_drop = prev_net_margin - net_margin
        result[(year, quarter)] = {
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_margin": net_margin,
            "gross_drop": gross_drop,
            "op_drop": op_drop,
            "net_drop": net_drop,
        }

    write_circular_cache(
        cache_key,
        {
            "source": "processed_financial_agent",
            "metadata": {
                "stock_id": "2330",
                "max_age_days": FINANCIAL_CACHE_MAX_AGE_DAYS,
                "start_date": start_date,
                "end_date": end_date,
            },
            "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
            "data": serialize_quarterly_margins(result),
        },
    )
    return result


def parse_twse_int(value) -> Optional[int]:
    """
    將 TWSE 回傳的數字字串轉成 int，例如 '1,234,567'。
    """
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "X", "除權息"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None

def parse_twse_float(value) -> Optional[float]:
    """將 TWSE 回傳的數字字串轉成 float。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "X", "除權息"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_twse_date(value) -> Optional[str]:
    """
    將 TWSE 民國日期（例如 115/05/15）轉成 YYYY-MM-DD。
    """
    if value is None:
        return None
    parts = str(value).strip().split("/")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[0])
        if year < 1911:
            year += 1911
        month = int(parts[1])
        day = int(parts[2])
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def get_recent_month_starts(months: int = 3) -> List[dt.date]:
    """
    回傳從本月往前推的月份起始日。
    會確保日期不早於 TWSE 限制的 1990-01-04。
    """
    month_starts = []
    year = TODAY.year
    month = TODAY.month
    for _ in range(months):
        d = dt.date(year, month, 1)
        if d < TWSE_MIN_DATE:
            break
        month_starts.append(d)
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return month_starts


def _is_current_month(date_obj: dt.date) -> bool:
    """檢查指定日期是否屬於當月（當月資料需每次抓取）"""
    return date_obj.year == TODAY.year and date_obj.month == TODAY.month


def fetch_twse_report(report: str, params: Dict[str, str],
                      force_refresh: bool = False) -> List[List[str]]:
    """
    從 TWSE afterTrading API 取得報表資料列。

    快取策略：
    - 當月資料（force_refresh=True）：每次重新抓取，不快取
    - 已過月份（force_refresh=False）：使用 24 小時快取，減少 TWSE 請求量
    """
    url = f"{TWSE_AFTER_TRADING_URL}/{report}"
    request_params = {"response": "json", **params}

    # 建立更完整的瀏覽器標頭，偽裝成從官網查詢頁面發出的請求
    selected_ua = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": selected_ua,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.twse.com.tw/zh/trading/historical/stock-day.html",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
        "Host": "www.twse.com.tw",
    }

    # 為不同的報表類型設定不同的 Referer
    if "FMTQIK" in report:
        headers["Referer"] = "https://www.twse.com.tw/zh/trading/historical/fmtqik.html"

    cache_key = build_cache_key(
        "twse",
        report,
        params.get("date"),
        params.get("stockNo", "market"),
    )

    # ── 快取讀取（已過月份使用 24h TTL）──────────────────────────
    if not force_refresh:
        cached_data = _read_twse_cache(cache_key, max_age_hours=24)
        if cached_data is not None:
            return cached_data

    # ── 實際請求 TWSE ────────────────────────────────────────────
    max_retries = 3
    blocked = False
    for attempt in range(max_retries):
        try:
            time.sleep(0.1 + random.random() * 0.4)

            resp = session.get(url, params=request_params, headers=headers,
                               timeout=30, allow_redirects=False)

            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code == 307 or "text/html" in content_type:
                blocked = True
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 2)
                    continue
                break

            if resp.status_code == 200:
                break

        except requests.RequestException:
            blocked = True
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            break

    # ── 被防護或請求失敗 → fallback 到快取 ─────────────────────
    if blocked or resp.status_code != 200:
        cached_data = get_cached_data(cache_key)
        if cached_data is not None:
            return cached_data
        return []

    # ── 解析回應 ─────────────────────────────────────────────────
    payload = resp.json()
    stat = payload.get("stat")
    if stat not in {"OK", "很抱歉，沒有符合條件的資料!"}:
        is_date_limit = "查詢日期小於" in stat or "查詢日期大於今日" in stat
        cached_data = get_cached_data(cache_key)

        if is_date_limit and cached_data is not None:
            return cached_data

        if stat != "很抱歉，沒有符合條件的資料!":
            print(f"Error: TWSE returned status: {stat}", file=sys.stderr)

        return cached_data if cached_data is not None else []

    rows = payload.get("data", [])
    if rows:
        write_circular_cache(
            cache_key,
            {
                "source": "TWSE",
                "metadata": {"report": report, **params},
                "cached_at": dt.datetime.now().isoformat(timespec="seconds"),
                "data": rows,
            },
        )
    return rows


def _read_twse_cache(cache_key: str, max_age_hours: int) -> Optional[List]:
    """
    讀取 TWSE 快取，檢查新鮮度。
    命中時印出提示（僅限第一次，避免重複）。
    """
    cached = read_latest_cache(cache_key)
    if cached is None:
        return None

    cached_at = cached.get("cached_at")
    if not cached_at:
        return None

    try:
        cached_dt = dt.datetime.fromisoformat(cached_at)
    except ValueError:
        return None

    age = dt.datetime.now() - cached_dt
    if age > dt.timedelta(hours=max_age_hours):
        return None

    return cached.get("data")


def get_twse_stock_trading_values(stock_no: str, months: int = 3) -> pd.DataFrame:
    """
    從 TWSE STOCK_DAY 抓取個股各日成交金額。
    當月以外月份使用 24h 快取，減少 TWSE 請求量。
    """
    records = []
    for month_start in get_recent_month_starts(months):
        is_current = _is_current_month(month_start)
        rows = fetch_twse_report(
            "STOCK_DAY",
            {"date": month_start.strftime("%Y%m%d"), "stockNo": stock_no},
            force_refresh=is_current,
        )
        for row in rows:
            if len(row) < 7:
                continue
            date = parse_twse_date(row[0])
            trading_value = parse_twse_int(row[2])
            open_price = parse_twse_float(row[3])
            high_price = parse_twse_float(row[4])
            low_price = parse_twse_float(row[5])
            close_price = parse_twse_float(row[6])
            if date and trading_value is not None and close_price is not None:
                records.append({
                    "日期": date,
                    "台積電成交金額": trading_value,
                    "台積電開盤價": open_price,
                    "台積電最高價": high_price,
                    "台積電最低價": low_price,
                    "台積電收盤價": close_price,
                })

    if not records:
        return pd.DataFrame(columns=["日期", "台積電成交金額", "台積電開盤價",
                                      "台積電最高價", "台積電最低價", "台積電收盤價"])
    return pd.DataFrame(records).drop_duplicates(subset=["日期"]).sort_values("日期")


def get_twse_market_trading_values(months: int = 3) -> pd.DataFrame:
    """
    從 TWSE FMTQIK 抓取大盤各日成交金額。
    當月以外月份使用 24h 快取，減少 TWSE 請求量。
    """
    records = []
    for month_start in get_recent_month_starts(months):
        is_current = _is_current_month(month_start)
        rows = fetch_twse_report(
            "FMTQIK",
            {"date": month_start.strftime("%Y%m%d")},
            force_refresh=is_current,
        )
        for row in rows:
            if len(row) < 3:
                continue
            date = parse_twse_date(row[0])
            trading_value = parse_twse_int(row[2])
            if date and trading_value is not None:
                records.append({"日期": date, "大盤成交金額": trading_value})

    if not records:
        return pd.DataFrame(columns=["日期", "大盤成交金額"])
    return pd.DataFrame(records).drop_duplicates(subset=["日期"]).sort_values("日期")


def get_recent_trading_value_history(days: int = 260) -> pd.DataFrame:
    """
    從 TWSE 抓取最近 N 個交易日的成交金額。
    回傳 DataFrame，日期由舊到新，包含足夠天數以計算技術指標。

    月份計算：每月平均 ~19 個交易日，加 1 個月緩衝。
    已過月份使用 24h 快取，僅當月實際請求 TWSE，大幅減少 API 呼叫。
    """
    # 每月平均 19 個交易日，加 1 個月緩衝，最少 3 個月，最多 18 個月
    months = max(3, min(18, -(-days // 19) + 1))
    stock_df = get_twse_stock_trading_values("2330", months=months)
    market_df = get_twse_market_trading_values(months=months)

    if stock_df.empty and market_df.empty:
        return pd.DataFrame(columns=["日期", "台積電成交金額", "台積電開盤價", "台積電最高價", "台積電最低價", "台積電收盤價", "大盤成交金額"])

    value_df = pd.merge(stock_df, market_df, on="日期", how="outer")
    value_df = value_df.sort_values("日期").tail(days).reset_index(drop=True)

    return value_df


def has_three_consecutive_decline(values: List[float]) -> bool:
    """
    檢查是否存在連續三天每日成交金額均低於前一天。
    values 為 list，最新在前：[V0, V1, V2, ...]
    條件：V0 < V1 < V2 （即三天遞減）
    """
    if len(values) < 3:
        return False
    for i in range(len(values) - 2):
        if values[i] < values[i + 1] < values[i + 2]:
            return True
    return False


def build_dataframe(
    revenue_yoy: List[Dict], quarterly_margins: Dict[Tuple[int, int], Dict]
) -> pd.DataFrame:
    """
    建立 DataFrame，每列為一個月（最近12個月）。
    包含月份、營收 YoY%、該月所在季度的毛利率%、該月所在季度的營業利益率%、
    以及該季度的毛利率季度下滑值、營業利益率季度下滑值（用於顏色判斷）。
    """
    # 月份列表
    months = [item["date"] for item in revenue_yoy]
    revenue_vals = [item["revenue_yoy"] for item in revenue_yoy]

    # 對每個月，找出所在季度並取得對應的值
    gross_margin_list = []
    operating_margin_list = []
    net_margin_list = []
    gross_drop_list = []
    op_drop_list = []
    net_drop_list = []
    for ym in months:
        year = int(ym[:4])
        month = int(ym[5:7])
        quarter = (month - 1) // 3 + 1
        q_key = (year, quarter)
        if q_key in quarterly_margins:
            qm = quarterly_margins[q_key]
            gross_margin_list.append(qm["gross_margin"])
            operating_margin_list.append(qm["operating_margin"])
            net_margin_list.append(qm["net_margin"])
            gross_drop_list.append(qm["gross_drop"])
            op_drop_list.append(qm["op_drop"])
            net_drop_list.append(qm["net_drop"])
        else:
            gross_margin_list.append(None)
            operating_margin_list.append(None)
            net_margin_list.append(None)
            gross_drop_list.append(None)
            op_drop_list.append(None)
            net_drop_list.append(None)

    # 建立 DataFrame
    df = pd.DataFrame(
        {
            "月份": months,
            "營收 YoY (%)": revenue_vals,
            "毛利率 (%)": gross_margin_list,
            "營業利益率 (%)": operating_margin_list,
            "稅後淨利率 (%)": net_margin_list,
            "_gross_drop": gross_drop_list,
            "_op_drop": op_drop_list,
            "_net_drop": net_drop_list,
        }
    )
    return df


def apply_color_logic(df: pd.DataFrame) -> pd.DataFrame:
    """
    根據規則加入顏色欄位（供 rich 使用）。
    回傳包含原始值和色彩標記的 DataFrame。
    """
    # 複製以免修改原始
    styled = df.copy()

    # 營收 YoY 色彩：低於 20% 標示黃色，連續兩月低於 20% 標示紅色
    rev_colors = []
    for i, val in enumerate(styled["營收 YoY (%)"]):
        if val is None:
            rev_colors.append("")
            continue
        if val < 20:
            # 檢查是否連續兩月低於 20%
            if i > 0 and styled["營收 YoY (%)"].iloc[i - 1] < 20:
                rev_colors.append("red")
            else:
                rev_colors.append("yellow")
        else:
            rev_colors.append("")
    styled["營收 YoY 色彩"] = rev_colors

    # 毛利率 與 營業利益率 色彩：
    # 根據季度下滑 >2% 標示黃色；
    # 如果三率中任意兩項下滑>2% 則標示紅色。
    margin_colors = []  # 這個顏色將同時適用於三率欄位
    for gd, od, nd in zip(styled["_gross_drop"], styled["_op_drop"], styled["_net_drop"]):
        # 如果任一 drop 為 None，則無法判斷，設為無顏色
        if gd is None or od is None or nd is None:
            margin_colors.append("")
            continue
        
        drops = [gd > 2, od > 2, nd > 2]
        if sum(drops) >= 2:
            margin_colors.append("red")
        elif sum(drops) >= 1:
            margin_colors.append("yellow")
        else:
            margin_colors.append("")
    styled["毛利率 色彩"] = margin_colors
    styled["營業利益率 色彩"] = margin_colors
    styled["稅後淨利率 色彩"] = margin_colors

    # 移除暫存欄位
    styled = styled.drop(columns=["_gross_drop", "_op_drop", "_net_drop"])
    return styled


def print_dashboard(
    styled_df: pd.DataFrame,
    value_df: pd.DataFrame,
    market_sentiment_red: bool,
):
    """
    使用 rich 輸出彩色表格、成交金額表格，並在需要時顯示市場情緒指標紅色警示。
    """
    console = Console()
    table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE_HEAVY)
    table.add_column("月份", style="dim", width=12)
    table.add_column("營收 YoY (%)", justify="right")
    table.add_column("毛利率 (%)", justify="right")
    table.add_column("營業利益率 (%)", justify="right")
    table.add_column("稅後淨利率 (%)", justify="right")

    def format_number(value) -> str:
        return "-" if pd.isna(value) else f"{value:.2f}"

    for _, row in styled_df.iterrows():
        # 營收 YoY 顏色
        rev_text = format_number(row["營收 YoY (%)"])
        if row["營收 YoY 色彩"] == "red":
            rev_text = f"[red]{rev_text}[/red]"
        elif row["營收 YoY 色彩"] == "yellow":
            rev_text = f"[yellow]{rev_text}[/yellow]"

        # 毛利率 顏色
        gross_text = format_number(row["毛利率 (%)"])
        if row["毛利率 色彩"] == "red":
            gross_text = f"[red]{gross_text}[/red]"
        elif row["毛利率 色彩"] == "yellow":
            gross_text = f"[yellow]{gross_text}[/yellow]"

        # 營業利益率 顏色
        op_text = format_number(row["營業利益率 (%)"])
        if row["營業利益率 色彩"] == "red":
            op_text = f"[red]{op_text}[/red]"
        elif row["營業利益率 色彩"] == "yellow":
            op_text = f"[yellow]{op_text}[/yellow]"

        # 稅後淨利率 顏色
        net_text = format_number(row["稅後淨利率 (%)"])
        if row["稅後淨利率 色彩"] == "red":
            net_text = f"[red]{net_text}[/red]"
        elif row["稅後淨利率 色彩"] == "yellow":
            net_text = f"[yellow]{net_text}[/yellow]"

        table.add_row(
            str(row["月份"]),
            rev_text,
            gross_text,
            op_text,
            net_text,
        )

    console.print(table)

    value_table = Table(
        title="近 10 個交易日成交金額",
        show_header=True,
        header_style="bold cyan",
        box=box.SIMPLE_HEAVY,
    )
    value_table.add_column("日期", style="dim", width=12)
    value_table.add_column("台積電成交金額", justify="right")
    value_table.add_column("大盤成交金額", justify="right")

    for _, row in value_df.iterrows():
        tsmc_value = row.get("台積電成交金額")
        market_value = row.get("大盤成交金額")
        tsmc_text = "-" if pd.isna(tsmc_value) else f"{int(tsmc_value):,}"
        market_text = "-" if pd.isna(market_value) else f"{int(market_value):,}"
        value_table.add_row(str(row["日期"]), tsmc_text, market_text)

    console.print()
    console.print(value_table)

    # 市場情緒指標：若同時符合條件則顯示紅色警示
    if market_sentiment_red:
        console.print("[red]市場情緒指標：個股與大盤交易量連三降[/red]")


def generate_summary(styled_df: pd.DataFrame, market_sentiment_red: bool) -> str:
    """
    根據表格顏色產生一句總結。
    """
    has_red = (
        (styled_df["營收 YoY 色彩"] == "red").any()
        or (styled_df["毛利率 色彩"] == "red").any()
        or (styled_df["營業利益率 色彩"] == "red").any()
        or (styled_df["稅後淨利率 色彩"] == "red").any()
        or market_sentiment_red
    )
    has_yellow = (
        (styled_df["營收 YoY 色彩"] == "yellow").any()
        or (styled_df["毛利率 色彩"] == "yellow").any()
        or (styled_df["營業利益率 色彩"] == "yellow").any()
        or (styled_df["稅後淨利率 色彩"] == "yellow").any()
    )

    if has_red:
        return "🔴 目前處於紅燈預警，建議減碼並密切監控。"
    elif has_yellow:
        return "🟡 目前處於黃燈預警，建議啟動階梯式觀察，暫不加碼。"
    else:
        return "🟢 目前皆為綠燈，可正常觀察並考慮適度加碼。"


def run_self_test():
    """
    執行系統診斷測試，驗證環境、目錄權限與外部 API 連線。
    """
    console = Console()
    console.print("\n[bold cyan]🚀 開始執行 Sentimental-Quant-Lab 系統自測...[/bold cyan]\n")

    # 1. 檢查必要的本機目錄
    folders = [CACHE_DIR, "charts"]
    for folder in folders:
        if not os.path.exists(folder):
            try:
                os.makedirs(folder)
                console.print(f"📂 目錄檢查 - {folder}: [yellow]已成功建立[/yellow]")
            except Exception as e:
                console.print(f"📂 目錄檢查 - {folder}: [red]建立失敗 ({e})[/red]")
                continue
        
        if os.access(folder, os.W_OK):
            console.print(f"📂 目錄權限 - {folder}: [green]寫入權限 OK[/green]")
        else:
            console.print(f"📂 目錄權限 - {folder}: [red]無寫入權限[/red]")

    # 2. 檢查關鍵環境變數
    token = os.getenv("FINMIND_TOKEN")
    token_status = "[green]已設定[/green]" if token else "[yellow]未設定 (將以限制頻率模式運行)[/yellow]"
    console.print(f"🔑 環境變數 - FINMIND_TOKEN: {token_status}")

    # 3. 測試網路連線與 API 狀態
    targets = [
        ("FinMind API", API_URL),
        ("TWSE API", f"{TWSE_AFTER_TRADING_URL}/STOCK_DAY"),
        ("Yahoo Finance", "https://query1.finance.yahoo.com/v8/finance/chart/TSM")
    ]
    
    for name, url in targets:
        try:
            resp = requests.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=10)
            # 200 代表完全成功，400/401 代表服務有反應但未帶正確參數，皆視為連線成功
            status_color = "green" if resp.status_code in [200, 400, 401] else "yellow"
            console.print(f"🌐 網路連線 - {name}: [{status_color}]回傳狀態 {resp.status_code}[/{status_color}]")
        except Exception as e:
            console.print(f"🌐 網路連線 - {name}: [red]連線失敗 ({str(e)})[/red]")

    console.print("\n[bold cyan]✨ 自測完成。[/bold cyan]\n")


def main():
    """
    主程式流程。
    """
    parser = argparse.ArgumentParser(description="TSMC 信號儀表板")
    parser.add_argument("--test", action="store_true", help="執行系統診斷自測")
    args = parser.parse_args()

    if args.test:
        run_self_test()
        return

    # 可選的 FinMind token，從環境變數讀取
    token = os.getenv("FINMIND_TOKEN")

    # ══════════════════════════════════════════════════════════════
    # 資料抓取：依變化頻率分為兩個層級
    # ══════════════════════════════════════════════════════════════

    # Tier 1: 每日變化資料 — 每次執行皆重新抓取
    value_df = get_recent_trading_value_history(days=260)
    chip_data = fetch_finmind_dataset(
        dataset="TaiwanStockInstitutionalInvestorsBuySell",
        data_id="2330",
        start_date=(TODAY - dt.timedelta(days=15)).isoformat(),
        end_date=TODAY.isoformat(),
        token=token,
    )

    # Tier 2: 低頻變化資料 — 使用 TTL 快取（月營收 24h、季報 7d）
    revenue_yoy = get_monthly_revenue_yoy(token)
    quarterly_margins = get_quarterly_margins(token)

    if not revenue_yoy:
        print("錯誤：未能取得月營收資料。", file=sys.stderr)
        sys.exit(1)
    if not quarterly_margins:
        print("警告：未能取得季度毛利率/營業利益率資料，將以空白顯示。", file=sys.stderr)

    # 建立 DataFrame
    df = build_dataframe(revenue_yoy, quarterly_margins)

    # 加入顏色邏輯
    styled_df = apply_color_logic(df)

    # 呼叫 AI Agent 編排器
    orchestrator = Orchestrator()
    # 這裡保留原有的 market_sentiment_red 邏輯，但使用 tail(10) 確保邏輯範圍一致
    recent_v = value_df.tail(10)
    market_sentiment_red = has_three_consecutive_decline(recent_v['台積電成交金額'].tolist()[::-1]) and \
                           has_three_consecutive_decline(recent_v['大盤成交金額'].tolist()[::-1])

    # 輸出儀表板
    print_dashboard(styled_df, value_df.tail(10), market_sentiment_red)

    # 執行 Agent 深度分析（統一由 signal_engine 計算綜合燈號）
    dashboard_summary = orchestrator.run_full_analysis(
        quarterly_margins, value_df, chip_data, styled_df,
        market_sentiment_red=market_sentiment_red
    )

    print(f"\n{dashboard_summary}")


if __name__ == "__main__":
    main()
