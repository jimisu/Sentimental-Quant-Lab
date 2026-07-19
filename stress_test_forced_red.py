#!/usr/bin/env python3
"""
stress_test_forced_red.py
==========================
對 2024 年「每個月的 15 號」（若當日非交易則往後 +2 天，至多 +5 天）
做強制紅燈規則的 walk-forward 壓力測試。

強制紅燈規則（與 backtest_crash_signals.py 完全相同，原樣複用）：
    P/E > CONFIG.chip.high_sellout_pe_threshold (25)
    且 外資「當日前兩個月（60 自然日）淨賣超」
        > 外資當日實際持股之 CONFIG.chip.two_month_high_sellout_pct (1%)
        （分母用各 as-of 外資持股，非總流通股）

目的：驗證這條規則在 2024 平靜 / 非崩盤月份是否會「誤判」（false positive /
誤觸發）——即規則亮紅燈，但隨後 25 個交易日內並無 -5% 以上的崩盤日。

資料來源（全部走 local_cache 快取）：
  * 2330.TW 日線：Yahoo Finance
  * 三大法人買賣超 / 外資持股：FinMind
  * 歷史 EPS：FinMind TaiwanStockFinancialStatements

用法：
  python stress_test_forced_red.py            # 預設測 2024 全年每月 15 號
  python stress_test_forced_red.py --no-cache
"""
from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd

import backtest_crash_signals as bt
from config import CONFIG

PE_TH = CONFIG.chip.high_sellout_pe_threshold       # 25.0
SELL_PCT = CONFIG.chip.two_month_high_sellout_pct  # 0.01
WIN_DAYS = CONFIG.chip.two_month_window_days        # 60


def next_trading_day(target: dt.date, trading_days: list) -> dt.date:
    """從 target 起往後找第一個交易日（至多 +5 天）。"""
    d = target
    for _ in range(6):
        if d in trading_days:
            return d
        d += dt.timedelta(days=1)
    return target  # 找不到則回傳原日（標註用）


def forward_tail(as_of: dt.date, ohlcv: pd.DataFrame, n: int = 25):
    """回傳 as_of 之後 n 個交易日的：最小單日漲跌幅、是否出現 -5% 崩盤、最大回撤。"""
    post = ohlcv[ohlcv.index > pd.Timestamp(as_of)].head(n)
    closes = post["close"].astype(float)
    if len(closes) < 2:
        return None, False, None
    rets = closes.pct_change().dropna()
    min_ret = float(rets.min())
    crash = bool((rets <= -0.05).any())
    peak = closes.cummax()
    max_dd = float(((closes - peak) / peak).min())
    return min_ret, crash, max_dd


def main() -> int:
    ap = argparse.ArgumentParser(description="強制紅燈規則 2024 月度壓力測試")
    ap.add_argument("--no-cache", action="store_true", help="忽略快取強制重抓")
    ap.add_argument("--year", type=int, default=2024, help="測試年份（預設 2024）")
    args = ap.parse_args()
    year = args.year

    start = dt.date(year - 1, 12, 1)
    end = dt.date(year + 1, 1, 31)
    p1 = int(dt.datetime(start.year, start.month, start.day, tzinfo=dt.timezone.utc).timestamp())
    p2 = int(dt.datetime(end.year, end.month, end.day, tzinfo=dt.timezone.utc).timestamp())

    print(f"[1/4] 抓取 2330.TW OHLCV ({start} ~ {end}) ...")
    ohlcv = bt.fetch_yahoo_ohlcv("2330.TW", p1, p2, use_cache=not args.no_cache)
    print("[2/4] 抓取 FinMind 三大法人買賣超 ...")
    inst_rows = bt.fetch_finmind_inst_rows("2330", start, end, use_cache=not args.no_cache)
    print("[3/4] 抓取 FinMind 外資持股 ...")
    shareholding = bt.fetch_finmind_shareholding("2330", start, end, use_cache=not args.no_cache)
    shareholding.sort(key=lambda x: x["date"])
    print("[4/4] 抓取 FinMind 財務報表（歷史 EPS）..")
    qend_eps = bt.load_quarterly_eps(use_cache=not args.no_cache)

    trading_days = sorted(ts.date() for ts in ohlcv.index)

    print("\n" + "=" * 118)
    print(f"{year} 年 每月 15 號 強制紅燈壓力測試（規則：PE>{PE_TH:.0f} 且 "
          f"外資兩月淨賣超 > 持股 {SELL_PCT*100:.0f}%）")
    print("=" * 118)
    hdr = (f"{'目標(15號)':<14}{'as-of(實際)':<14}{'收盤':>9}{'P/E':>7}"
           f"{'外資2月淨張':>14}{'1%持股閾':>14}{'強制紅燈':>10}"
           f"{'隨後25日最小漲跌':>16}{'崩盤?':>8}{'最大回撤':>10}{'判定':>8}")
    print(hdr)
    print("-" * 118)

    fired = 0
    tp = 0       # 觸發且隨後真崩（true positive）
    fp = 0       # 觸發但隨後未崩（誤判 / false positive）
    fp_months = []
    for m in range(1, 13):
        target = dt.date(year, m, 15)
        as_of = next_trading_day(target, trading_days)
        if as_of not in trading_days:
            as_of = target  # 極端退路
        as_of_str = as_of.isoformat()

        slice_df = ohlcv[ohlcv.index <= pd.Timestamp(as_of)]
        close = float(slice_df.iloc[-1]["close"])
        pe = bt.compute_pe_ratio(as_of, close, qend_eps)

        cutoff = (as_of - dt.timedelta(days=WIN_DAYS)).isoformat()
        net_2m = sum(
            (r["buy"] - r["sell"]) for r in inst_rows
            if r["name"] == "Foreign_Investor" and cutoff <= r["date"] <= as_of_str
        )
        net_2m_lots = net_2m / 1000.0

        hold = next((sh for sh in reversed(shareholding) if sh["date"] <= as_of_str), None)
        foreign_shares = (hold["foreign_shares"] if (hold and hold.get("foreign_shares"))
                            else CONFIG.chip.tsmc_float_shares)
        sellout_threshold = SELL_PCT * foreign_shares
        sellout_lots = sellout_threshold / 1000.0

        forced = (pe is not None and pe > PE_TH and net_2m < -sellout_threshold)

        min_ret, crash, max_dd = forward_tail(as_of, ohlcv, n=25)
        min_ret_s = f"{min_ret*100:+.2f}%" if min_ret is not None else "資料不足"
        dd_s = f"{max_dd*100:+.2f}%" if max_dd is not None else "—"
        crash_s = "是" if crash else "否"

        if forced:
            fired += 1
            if crash:
                tp += 1
                verdict = "✅真陽"
            else:
                fp += 1
                verdict = "⚠️誤判"
                fp_months.append(as_of.strftime("%Y-%m"))
        else:
            verdict = "—"

        pe_s = f"{pe:.1f}" if pe is not None else "缺漏"
        fred = "🔴強制" if forced else "—"
        print(f"{target.isoformat():<14}{as_of.isoformat():<14}{close:>9.1f}{pe_s:>7}"
              f"{net_2m_lots:>+13,.0f}{sellout_lots:>13,.0f} {fred:>9}"
              f"{min_ret_s:>15}{crash_s:>7}{dd_s:>9} {verdict:>7}")

    print("-" * 118)
    print(f"共觸發強制紅燈 {fired} 個月；其中 真陽(隨後崩盤) {tp} 次、"
          f"誤判(隨後未崩) {fp} 次。")
    if fp_months:
        print(f"誤判月份（規則亮紅燈但 25 交易日內無 -5% 崩盤）：{', '.join(fp_months)}")
    else:
        print("無誤判：所有觸發月份隨後皆出現崩盤日。")
    print(f"註：判定窗 = as-of 之後 25 個交易日（約 1.2 個月）。"
          f"「誤判」= 規則觸發但窗內無單日 -5% 以上跌幅。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
