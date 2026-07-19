#!/usr/bin/env python3
"""
historical_crash_days.py
========================
分析台積電 (2330.TW) 過去一年 (今日往回 365 天) 的「崩盤日」：

  1. 抓取 2330 每日收盤價 (Yahoo Finance, 1y 日線)。
  2. 計算每日漲跌幅 = (今日收盤 - 昨日收盤) / 昨日收盤。
  3. 篩選漲跌幅 <= -5% 的所有日期。
  4. 對每個崩盤日，取出當日外資 (Foreign_Investor) 買賣超
     (FinMind TaiwanStockInstitutionalInvestorsBuySell)。
  5. 同時取當日大盤 (TAIEX, ^TWII) 漲跌幅，用於判斷是
     個股獨立事件還是系統性下跌。
  6. 輸出表格 (Markdown 至 stdout + CSV 至檔案)。

資料來源說明
------------
  * 收盤價 / 大盤指數：Yahoo Finance。
    (FinMind 此 token 為 register 等級，TaiwanStockTradingDailyReport
     與大盤指數 dataset 會回傳 400，故改用 Yahoo。)
  * 外資買賣超：FinMind TaiwanStockInstitutionalInvestorsBuySell
    (register 等級可用，單次抓取整年再依日期對照)。
  * 外資買賣超單位：FinMind 回傳為「股」，本腳本換算為「張」
    (1 張 = 1000 股) 以利閱讀，並保留股數欄位。

錯誤處理
--------
  任一崩盤日的「外資資料」或「大盤資料」缺漏時，該欄位標註
  「資料缺漏」並照常顯示該列，不跳過，避免誤判為「那天沒跌」。

用法
----
  python historical_crash_days.py                 # 預設：一年、門檻 -5%
  python historical_crash_days.py --threshold -7  # 自訂門檻
  python historical_crash_days.py --days 730       # 抓兩年
  python historical_crash_days.py --csv out.csv    # 指定 CSV 輸出
  python historical_crash_days.py --no-cache       # 忽略快取強制重抓
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────
load_dotenv(".env")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
FINMIND_API_URL = "https://api.finmindtrade.com/api/v4/data"

CACHE_DIR = Path("local_cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_HOURS = 24
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

TPE_OFFSET_SECONDS = 8 * 3600  # Yahoo 時間戳為 UTC，+8h 得台灣日曆日


# ──────────────────────────────────────────────
# 快取 (沿用專案 local_cache 環形快取慣例，單檔)
# ──────────────────────────────────────────────
def _cache_path(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")
    return CACHE_DIR / f"hcd_{safe}.json"


def _read_cache(key: str, ttl_hours: int = CACHE_TTL_HOURS) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    cached_at = payload.get("cached_at")
    if not cached_at:
        return None
    try:
        age = dt.datetime.now() - dt.datetime.fromisoformat(cached_at)
    except ValueError:
        return None
    if age > dt.timedelta(hours=ttl_hours):
        return None
    return payload.get("data")


def _write_cache(key: str, data: dict) -> None:
    p = _cache_path(key)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(
                {"cached_at": dt.datetime.now().isoformat(timespec="seconds"), "data": data},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except OSError:
        pass  # 快取寫入失敗不影響主流程


# ──────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────
def _ts_to_tpe_date(ts: int) -> dt.date:
    """將 Yahoo UTC 時間戳轉為台灣日曆日。"""
    return dt.datetime.fromtimestamp(ts + TPE_OFFSET_SECONDS, dt.timezone.utc).date()


def _fmt_num(x: float, digits: int = 2) -> str:
    return f"{x:,.{digits}f}"


# ──────────────────────────────────────────────
# 資料抓取
# ──────────────────────────────────────────────
def fetch_yahoo_close(symbol: str, period1: int, period2: int,
                      use_cache: bool = True) -> Dict[dt.date, float]:
    """抓取 Yahoo Finance 日線收盤價，回傳 {日期: 收盤價}。"""
    cache_key = f"yahoo_{symbol}_{period1}_{period2}"
    if use_cache:
        cached = _read_cache(cache_key)
        if cached is not None:
            print(f"  -> 使用快取: {cache_key}")
            return {dt.date.fromisoformat(d): v for d, v in cached.items()}

    result: Dict[dt.date, float] = {}
    last_err: Optional[Exception] = None
    # Yahoo chart 端點需將 symbol 放進 URL 路徑，而非 query 參數
    url = f"{YAHOO_URL}/{symbol}"
    for attempt in range(3):  # Yahoo 偶爾回傳非 JSON，重試一次
        try:
            resp = requests.get(
                url,
                params={
                    "period1": period1,
                    "period2": period2,
                    "interval": "1d",
                    "events": "history",
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=30,
            )
            payload = resp.json()
            break
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"Yahoo {symbol} 抓取失敗: {last_err}") from last_err

    chart = (payload.get("chart") or {}).get("result")
    if not chart:
        raise RuntimeError(f"Yahoo {symbol} 無資料: {payload.get('chart')}")
    res = chart[0]
    timestamps = res.get("timestamp", [])
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    for ts, c in zip(timestamps, closes):
        if c is None:
            continue
        result[_ts_to_tpe_date(ts)] = float(c)

    if use_cache:
        _write_cache(cache_key, {d.isoformat(): v for d, v in result.items()})
    print(f"  -> Yahoo {symbol}: 取得 {len(result)} 個交易日收盤價")
    return result


def fetch_finmind_foreign_net(stock_id: str, start: dt.date, end: dt.date,
                              use_cache: bool = True) -> Dict[dt.date, dict]:
    """抓取 FinMind 三大法人買賣超，回傳 {日期: {net_shares, buy, sell}} (Foreign_Investor)。"""
    cache_key = f"finmind_inst_{stock_id}_{start}_{end}"
    if use_cache:
        cached = _read_cache(cache_key)
        if cached is not None:
            print(f"  -> 使用快取: {cache_key}")
            return {dt.date.fromisoformat(d): v for d, v in cached.items()}

    if not FINMIND_TOKEN:
        print("  !! 未設定 FINMIND_TOKEN，外資資料將標註「資料缺漏」")
        return {}

    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "token": FINMIND_TOKEN,
    }
    try:
        resp = requests.get(FINMIND_API_URL, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=30)
        data = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"  !! FinMind 外資抓取失敗: {exc} (將標註「資料缺漏」)")
        return {}

    if data.get("status") != 200:
        print(f"  !! FinMind 外資 API 錯誤: {data.get('msg')} (將標註「資料缺漏」)")
        return {}

    # 同一天可能有多筆 (不同 name)，依 name 分組後取 Foreign_Investor
    by_date: Dict[dt.date, dict] = {}
    for row in data.get("data", []):
        date_str = row.get("date", "")
        name = row.get("name", "")
        if not date_str or name != "Foreign_Investor":
            continue
        try:
            d = dt.date.fromisoformat(date_str)
            buy = int(row.get("buy") or 0)
            sell = int(row.get("sell") or 0)
        except (ValueError, TypeError):
            continue
        by_date[d] = {"buy": buy, "sell": sell, "net_shares": buy - sell}

    if use_cache:
        _write_cache(cache_key, {d.isoformat(): v for d, v in by_date.items()})
    print(f"  -> FinMind 外資買賣超: 取得 {len(by_date)} 個交易日")
    return by_date


# ──────────────────────────────────────────────
# 核心分析
# ──────────────────────────────────────────────
def compute_returns(prices: Dict[dt.date, float]) -> Dict[dt.date, float]:
    """回傳 {日期: 漲跌幅}，首個交易日無前日收盤故不計入。"""
    ret: Dict[dt.date, float] = {}
    dates = sorted(prices)
    for i in range(1, len(dates)):
        prev, cur = prices[dates[i - 1]], prices[dates[i]]
        if prev:
            ret[dates[i]] = (cur - prev) / prev
    return ret


def classify_market(idx_ret: Optional[float]) -> str:
    """依大盤漲跌幅給出系統性/個股判讀備註。"""
    if idx_ret is None:
        return "大盤資料缺漏"
    if idx_ret <= -0.03:
        return "系統性下跌(大盤重挫)"
    if idx_ret >= 0:
        return "個股獨立事件(大盤上漲)"
    if idx_ret < -0.01:
        return "個股弱於大盤(大盤小跌)"
    return "個股弱於大盤(大盤近持平)"


def analyze(threshold: float, days: int, use_cache: bool = True) -> List[dict]:
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    period1 = int(dt.datetime(start.year, start.month, start.day,
                              tzinfo=dt.timezone.utc).timestamp())
    period2 = int(dt.datetime(today.year, today.month, today.day,
                              tzinfo=dt.timezone.utc).timestamp())

    print(f"[1/3] 抓取 2330.TW 收盤價 ({start} ~ {today}) ...")
    stock_prices = fetch_yahoo_close("2330.TW", period1, period2, use_cache)
    print(f"[2/3] 抓取 TAIEX (^TWII) 收盤指數 ...")
    index_prices = fetch_yahoo_close("^TWII", period1, period2, use_cache)
    print(f"[3/3] 抓取 FinMind 外資買賣超 (2330) ...")
    foreign = fetch_finmind_foreign_net("2330", start, today, use_cache)

    stock_ret = compute_returns(stock_prices)
    index_ret = compute_returns(index_prices)

    rows: List[dict] = []
    for d in sorted(stock_ret):
        ret = stock_ret[d]
        if ret * 100 > threshold:
            continue  # 非崩盤日 (threshold 以 % 為單位)

        close = stock_prices.get(d)
        # 外資資料
        f = foreign.get(d)
        if f is None:
            foreign_cell = "資料缺漏"
            foreign_lots = None
            foreign_shares = None
            foreign_dir = "資料缺漏"
        else:
            net = f["net_shares"]
            foreign_shares = net
            foreign_lots = round(net / 1000)  # 股 -> 張
            foreign_dir = "買超" if net > 0 else ("賣超" if net < 0 else "持平")
            foreign_cell = f"{foreign_lots:+,} 張"

        # 大盤資料
        ir = index_ret.get(d)
        if ir is None:
            idx_cell = "資料缺漏"
            idx_ret_val = None
        else:
            idx_ret_val = ir
            idx_cell = f"{ir * 100:+.2f}%"

        note = classify_market(idx_ret_val)

        rows.append({
            "date": d,
            "close": close,
            "ret_pct": ret * 100,
            "foreign_cell": foreign_cell,
            "foreign_lots": foreign_lots,
            "foreign_shares": foreign_shares,
            "foreign_dir": foreign_dir,
            "idx_cell": idx_cell,
            "idx_ret_pct": idx_ret_val,
            "note": note,
        })
    return rows


# ──────────────────────────────────────────────
# 輸出
# ──────────────────────────────────────────────
def to_markdown(rows: List[dict], threshold: float, days: int) -> str:
    lines = []
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    n = len(rows)
    missing_foreign = sum(1 for r in rows if r["foreign_dir"] == "資料缺漏")
    missing_idx = sum(1 for r in rows if r["idx_cell"] == "資料缺漏")
    lines.append(f"# 台積電崩盤日分析 (漲跌幅 ≤ {threshold:.1f}%)")
    lines.append("")
    lines.append(f"- 分析區間：**{start} ~ {today}** (往回 {days} 天)")
    lines.append(f"- 收錄崩盤日數：**{n}**")
    lines.append(f"- 外資資料缺漏：**{missing_foreign}** 日 ｜ 大盤資料缺漏：**{missing_idx}** 日")
    lines.append("")
    lines.append("| 日期 | 收盤價 | 漲跌幅 | 外資買賣超(張) | 外資買賣超(股) | 外資方向 | 大盤漲跌幅 | 備註 |")
    lines.append("|------|-------:|------:|------:|------:|------|------:|------|")
    for r in rows:
        close = f"{r['close']:,.0f}" if r["close"] is not None else "資料缺漏"
        lines.append(
            f"| {r['date']} | {close} | {r['ret_pct']:+.2f}% | "
            f"{r['foreign_cell']} | "
            f"{r['foreign_shares']:,} | {r['foreign_dir']} | "
            f"{r['idx_cell']} | {r['note']} |"
        )
    if not rows:
        lines.append("")
        lines.append("區間內無符合門檻的崩盤日。")
    return "\n".join(lines)


def to_csv(rows: List[dict], path: str) -> None:
    fields = ["date", "close", "ret_pct", "foreign_lots", "foreign_shares",
              "foreign_dir", "idx_ret_pct", "note"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日期", "收盤價", "漲跌幅(%)", "外資買賣超(張)", "外資買賣超(股)",
                    "外資方向", "大盤漲跌幅(%)", "備註"])
        for r in rows:
            w.writerow([
                r["date"],
                r["close"] if r["close"] is not None else "資料缺漏",
                f"{r['ret_pct']:.2f}",
                r["foreign_lots"] if r["foreign_lots"] is not None else "資料缺漏",
                r["foreign_shares"] if r["foreign_shares"] is not None else "資料缺漏",
                r["foreign_dir"],
                f"{r['idx_ret_pct'] * 100:.2f}" if r["idx_ret_pct"] is not None else "資料缺漏",
                r["note"],
            ])
    print(f"\nCSV 已寫入: {path}")


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="台積電過去一年崩盤日分析")
    ap.add_argument("--threshold", type=float, default=-5.0,
                    help="崩盤門檻漲跌幅 (預設 -5.0%%，篩選 <= 此值)")
    ap.add_argument("--days", type=int, default=365,
                    help="往回天數 (預設 365)")
    ap.add_argument("--csv", type=str, default="historical_crash_days.csv",
                    help="CSV 輸出路徑 (預設 historical_crash_days.csv)")
    ap.add_argument("--no-cache", action="store_true",
                    help="忽略快取，強制重新抓取")
    args = ap.parse_args()

    try:
        rows = analyze(args.threshold, args.days, use_cache=not args.no_cache)
    except RuntimeError as exc:
        print(f"錯誤: {exc}", file=sys.stderr)
        return 1

    print("\n" + to_markdown(rows, args.threshold, args.days))
    to_csv(rows, args.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
