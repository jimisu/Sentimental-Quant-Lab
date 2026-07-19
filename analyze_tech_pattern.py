#!/usr/bin/env python3
"""聚焦分析：5 個強制紅燈 as-of 日的底層技術指標，找共同 pattern。"""
from __future__ import annotations
import datetime as dt
import pandas as pd

import backtest_crash_signals as bt

today = dt.date.today()
start = today - dt.timedelta(days=1200)
p1 = int(dt.datetime(start.year, start.month, start.day, tzinfo=dt.timezone.utc).timestamp())
p2 = int(dt.datetime(today.year, today.month, today.day, tzinfo=dt.timezone.utc).timestamp())

ohlcv = bt.fetch_yahoo_ohlcv("2330.TW", p1, p2, use_cache=True)
twii = bt.hcd.fetch_yahoo_close("^TWII", p1, p2, use_cache=True)

# 強制紅燈的 5 個 as-of（與 backtest_crash_signals.CRASH_DATES 對應）
FORCED = [
    dt.date(2024, 7, 26), dt.date(2024, 8, 2), dt.date(2024, 8, 5),
    dt.date(2024, 9, 4), dt.date(2026, 7, 17),
]


def indicators_asof(as_of: dt.date) -> dict:
    s = ohlcv[ohlcv.index <= pd.Timestamp(as_of)]
    close = s["close"].astype(float)
    c = float(close.iloc[-1])
    # MA
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else float("nan")
    # 20MA 乖離
    dev20 = (c - ma20) / ma20 * 100
    dev60 = (c - ma60) / ma60 * 100 if len(close) >= 60 else float("nan")
    # 60 日價格百分位
    recent = close.tail(60)
    pctile = (recent < c).sum() / len(recent) * 100
    if c >= recent.max():
        pctile = 100.0
    # RSI14 (Wilder 平滑)
    delta = close.diff()
    up = delta.clip(lower=0); dn = -delta.clip(upper=0)
    ag = up.ewm(alpha=1/14, adjust=False).mean()
    al = dn.ewm(alpha=1/14, adjust=False).mean()
    rs = ag.iloc[-1] / al.iloc[-1] if al.iloc[-1] > 0 else float("inf")
    rsi = 100 - (100 / (1 + rs)) if rs != float("inf") else 100.0
    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    hist_now = float(hist.iloc[-1]); hist_prev = float(hist.iloc[-2])
    macd_now = float(macd.iloc[-1])
    hist_slope = hist_now - hist_prev  # >0 持續放大, <0 柱狀圖收斂/轉弱
    # 布林
    mid = ma20
    std = float(close.tail(20).std())
    upper = mid + 2 * std; lower = mid - 2 * std
    bb_pos = (c - lower) / (upper - lower) * 100 if (upper - lower) else 50.0
    # KD (9,3)
    low9 = close.rolling(9).min(); high9 = close.rolling(9).max()
    rsv = (c - low9.iloc[-1]) / (high9.iloc[-1] - low9.iloc[-1]) * 100 if (high9.iloc[-1] - low9.iloc[-1]) else 50.0
    # %K 用 RSV 近似（單日），%D 用前一日 RSV 的 3 日均
    k = rsv
    # 量能：近 5 日均量 vs 近 20 日均量
    vol = s["volume"].astype(float)
    vol5 = float(vol.tail(5).mean()); vol20 = float(vol.tail(20).mean())
    vol_ratio = vol5 / vol20
    return dict(close=c, ma20=ma20, ma60=ma60, dev20=dev20, dev60=dev60,
                pctile=pctile, rsi=rsi, macd=macd_now, hist=hist_now,
                hist_slope=hist_slope, bb_pos=bb_pos, k=rsv, vol_ratio=vol_ratio)


print("=" * 96)
print("5 個強制紅燈 as-of 日 — 底層技術指標")
print("=" * 96)
hdr = f"{'as-of':<12}{'收盤':>9}{'20MA乖離':>10}{'60MA乖離':>10}{'60日百分位':>11}{'RSI14':>8}{'MACD柱':>9}{'柱斜率':>9}{'布林位置':>10}{'KD%K':>7}{'量比':>7}"
print(hdr)
print("-" * 96)
for cd in FORCED:
    cand = [d for d in (ts.date() for ts in ohlcv.index) if d < cd]
    if not cand:
        continue
    as_of = cand[-1]
    r = indicators_asof(as_of)
    print(f"{as_of}  {r['close']:>9.1f}{r['dev20']:>+9.1f}%{r['dev60']:>+9.1f}%"
          f"{r['pctile']:>10.0f}{r['rsi']:>8.1f}{r['hist']:>9.2f}{r['hist_slope']:>+8.2f}"
          f"{r['bb_pos']:>9.0f}%{r['k']:>7.0f}{r['vol_ratio']:>7.2f}")
print("-" * 96)
print("註：柱斜率<0 = MACD 柱狀圖收斂（動能轉弱）；60日百分位/布林位置高 = 處於高檔；")
print("     RSI14>70 = 超買；20MA乖離高 = 價格遠離均線（延伸）。")
