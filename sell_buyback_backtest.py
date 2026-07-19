#!/usr/bin/env python3
"""賣出後 20 交易日買回回測。

挑出：2024 四個 as-of 日 + 一個「誤判」候選（非 2024 崩盤日的 as-of）。
對每個 sell 日：以該日收盤賣出，檢查隨後 20 個交易日最低收盤是否低於賣價
（即「能以更低價買回」）。min_close >= sell_close 即代表賣出後無法更低買回 = 誤判。
"""
from __future__ import annotations
import json
import datetime as dt
import pandas as pd

CACHE = "local_cache/hcd_yahoo_ohlcv_2330.TW_1672531200_1784419200.json"

WIN = 20  # 隨後交易日數


def load_ohlcv() -> pd.DataFrame:
    d = json.load(open(CACHE))
    df = pd.DataFrame(d["data"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df.dropna(subset=["close"])


def asof_close_on_or_before(ohlcv: pd.DataFrame, target: dt.date) -> tuple[dt.date, float]:
    """回傳 <= target 的最近交易日收盤（as-of 日若非交易日則往前取）。"""
    sub = ohlcv[ohlcv.index <= pd.Timestamp(target)]
    c = sub.iloc[-1]
    return sub.index[-1].date(), float(c["close"])


def buyback(ohlcv: pd.DataFrame, sell_day: dt.date, win: int = WIN):
    sell_date, sell_price = asof_close_on_or_before(ohlcv, sell_day)
    if sell_date != sell_day:
        note = f"(as-of {sell_day} 非交易日，取最近 {sell_date})"
    else:
        note = ""
    post = ohlcv[ohlcv.index > pd.Timestamp(sell_date)].head(win)
    if post.empty:
        return dict(sell_date=sell_date, sell_price=sell_price, note=note,
                    avail=0, min_close=None, min_date=None, max_close=None,
                    buyback_possible=None, edge_pct=None, recover_above=None)
    closes = post["close"].astype(float)
    min_close = float(closes.min())
    min_date = closes.idxmin().date()
    max_close = float(closes.max())
    min_idx = list(closes.index).index(closes.idxmin())
    # 最低點出現的第幾個交易日（1-based）
    min_rank = min_idx + 1
    buyback_possible = min_close < sell_price
    edge_pct = (sell_price - min_close) / sell_price * 100
    recover_above = max_close > sell_price
    return dict(sell_date=sell_date, sell_price=sell_price, note=note,
                avail=len(closes), min_close=min_close, min_date=min_date,
                min_rank=min_rank, max_close=max_close,
                buyback_possible=buyback_possible, edge_pct=edge_pct,
                recover_above=recover_above)


def main():
    ohlcv = load_ohlcv()
    print(f"OHLCV 範圍: {ohlcv.index.min().date()} ~ {ohlcv.index.max().date()} "
          f"({len(ohlcv)} 日)\n")

    # 來自 backtest_crash_signals.CRASH_DATES 與 CSV 的 as_of前一日
    groups = {
        "2024 as-of": [
            dt.date(2024, 7, 23), dt.date(2024, 8, 1),
            dt.date(2024, 8, 2), dt.date(2024, 9, 3),
        ],
        "非2024 候選(as-of)": [
            dt.date(2025, 1, 22),   # 2025-02-03 崩盤 as-of
            dt.date(2025, 4, 2),    # 2025-04-07 崩盤 as-of
            dt.date(2026, 7, 16),   # 2026-07-17 崩盤 as-of (誤判候選?)
        ],
    }

    for gname, days in groups.items():
        print("=" * 100)
        print(gname)
        print("=" * 100)
        hdr = (f"{'賣出(as-of)':<12}{'賣價':>9}{'窗口交易日':>10}"
               f"{'最低收盤':>10}{'最低日':>12}{'最低序':>7}"
               f"{'最高收盤':>10}{'可更低買回?':>12}{'買回價差':>10}{'曾漲回賣價上?':>14}")
        print(hdr)
        print("-" * 100)
        for d in days:
            r = buyback(ohlcv, d)
            sp = r["sell_price"]
            if r["min_close"] is None:
                print(f"{r['sell_date']}  {sp:>9.1f}{'資料不足':>10}  (窗口無後續交易日)")
                continue
            bp = "✅是" if r["buyback_possible"] else "❌否(誤判)"
            rec = "是" if r["recover_above"] else "否"
            edge = f"{(r['edge_pct'] or 0):+.1f}%" if r["buyback_possible"] else "—"
            print(f"{r['sell_date']}{r['note']:<6}{sp:>9.1f}{r['avail']:>10}"
                  f"{r['min_close']:>10.1f}{str(r['min_date']):>12}{r['min_rank']:>7}"
                  f"{r['max_close']:>10.1f}{bp:>12}{edge:>10}{rec:>14}")
        print()


if __name__ == "__main__":
    main()
