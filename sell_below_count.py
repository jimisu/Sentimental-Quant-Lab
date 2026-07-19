#!/usr/bin/env python3
"""四個崩盤日賣出後，20 交易日內收盤價低於賣出日收盤的天數。"""
from __future__ import annotations
import json
import datetime as dt
import pandas as pd

CACHE = "local_cache/hcd_yahoo_ohlcv_2330.TW_1672531200_1784419200.json"
WIN = 20

df = pd.DataFrame(json.load(open(CACHE))["data"])
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date").sort_index()[["open", "high", "low", "close", "volume"]].astype(float)
df = df.dropna(subset=["close"])

SELL_DAYS = [dt.date(2024, 7, 26), dt.date(2024, 8, 2),
             dt.date(2024, 8, 5), dt.date(2024, 9, 4)]

print(f"{'崩盤日(賣出)':<14}{'賣價':>9}{'20日窗':>8}{'低於賣價天數':>14}{'佔比':>8}{'最低收盤':>10}{'最低日':>12}")
print("-" * 80)
for sd in SELL_DAYS:
    sub = df[df.index <= pd.Timestamp(sd)]
    if sub.empty:
        print(f"{sd}  無資料"); continue
    sell_date = sub.index[-1].date()
    sell_price = float(sub.iloc[-1]["close"])
    post = df[df.index > pd.Timestamp(sell_date)].head(WIN)
    closes = post["close"].astype(float)
    below = int((closes < sell_price).sum())
    n = len(closes)
    min_close = float(closes.min()); min_date = closes.idxmin().date()
    ratio = f"{below/n*100:.0f}%"
    print(f"{sell_date.isoformat():<14}{sell_price:>9.1f}{n:>8}{below:>14}{ratio:>8}{min_close:>10.1f}{min_date.isoformat():>12}")
    # 列出低於賣價的日期
    low_dates = [d.date().isoformat() for d, c in closes.items() if c < sell_price]
    print(f"   低於賣價的交易日: {', '.join(low_dates) if low_dates else '無'}")
    print()
