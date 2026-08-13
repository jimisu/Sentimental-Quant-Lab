#!/usr/bin/env python3
"""
領先指標（預測用）as-of 回測

從指定日期起往前逐交易日，以「當日可得資料」計算領先指標：
  - chip_data        : 截至該日的三大法人買賣超（外資每日淨買賣）
  - foreign_shares   : 截至該日的外資實際持股（強制紅燈分母）
  - pe_ratio         : 該日收盤價 ÷ 截至該日可得的近四季 EPS（含財報發布時滯 +50 日）
  - price_df         : 截至該日的收盤價序列（用於近 5 日無單日大跌 >5% 檢查）

觸發條件（三者同時成立，詳見 signal_engine.compute_leading_indicator）：
  1) 往前兩個月累計淨賣超佔外資持股 > 1%
  2) 本益比 (TTM) > 30 倍
  3) 往前五個交易日無單日大跌 > 5%

輸出：每個掃描交易日（日期 / 是否觸發 / 收盤價 / 三條件數值），
以及觸發天數與各觸發日收盤價；連續 10 個交易日未觸發即停止。

資料全程來自 local_cache，不觸網。

用法：
  python leading_indicator_backtest.py              # 互動式輸入起始日
  python leading_indicator_backtest.py --start 2026-06-01  # 指定起始日
  python leading_indicator_backtest.py --latest     # 從最新交易日往前回測
"""

import argparse
import sys
from typing import List, Dict

from backtest_core import (
    BacktestDataLoader,
    CachedDataPaths,
    EPSTimeline,
    LeadingIndicatorAnalyzer,
    LeadingIndicatorConfig,
)


# ── 回測參數 ──
DEFAULT_START_DATE = "2026-06-01"
STOP_NO_TRIGGER_STREAK = 10          # 連續 N 日未觸發即停止
EPS_REPORT_LAG_DAYS = 50             # 季報視為「可得」的發布時滯（季底 + 50 日）


def run_backtest(start_date: str) -> None:
    """執行回測，起始日為 start_date"""
    # 1. 載入所有快取資料
    print("載入快取資料...")
    loader = BacktestDataLoader()
    data = loader.load_all()

    inst_rows = data["inst_rows"]
    shareholding = data["shareholding"]
    ohlc = data["ohlc"]
    wide_fin = data["wide_fin"]

    # 2. 建構 EPS 時間線
    eps_timeline = EPSTimeline.from_wide_financial(wide_fin, EPS_REPORT_LAG_DAYS)

    # 3. 建立分析器（標準版：PE > 30）
    config = LeadingIndicatorConfig(pe_threshold=30.0)
    analyzer = LeadingIndicatorAnalyzer(
        config=config,
        eps_timeline=eps_timeline,
        inst_rows=inst_rows,
        shareholding_data=shareholding,
        ohlc_data=ohlc,
    )

    # 4. 交易日宇宙：同時具備法人買賣超、收盤價、外資持股的日期
    inst_dates = {r["date"] for r in inst_rows}
    close_lookup = {r["date"]: float(r["close"]) for r in ohlc}
    shareholding_lookup = {r["date"]: r for r in shareholding}

    trading_days = sorted(
        (d for d in inst_dates if d in close_lookup and d in shareholding_lookup),
        reverse=True
    )

    if not trading_days:
        print("❌ 找不到有效交易日，請檢查快取資料")
        sys.exit(1)

    # 5. 決定起始日
    if start_date not in trading_days:
        # 向後找最近的交易日
        earlier = [d for d in trading_days if d <= start_date]
        start = earlier[0] if earlier else trading_days[0]
        print(f"⚠️ {start_date} 非交易日/缺資料，改自 {start} 起算")
    else:
        start = start_date

    # 6. 自 start 往前的交易日序列
    seq = [d for d in trading_days if d <= start]

    # 7. 逐日計算領先指標
    daily_results: List[Dict] = []

    for d in seq:
        li = analyzer.compute_for_date(d)
        close = close_lookup[d]

        daily_results.append({
            "date": d,
            "close": close,
            "pe": li.pe_ratio if li.pe_ratio else 0.0,
            "li": li,
        })

    # 8. 輸出結果
    print_leading_indicator_scan(daily_results, STOP_NO_TRIGGER_STREAK)


def print_leading_indicator_scan(daily_results: List[Dict], stop_streak: int) -> None:
    """列印領先指標掃描結果"""
    triggered_days = []          # (date, close)
    streak_no_trigger = 0
    stop_date = None
    total_scanned = 0

    print(f"{'日期':<12} {'觸發':<6} {'收盤價':>10} {'淨賣超佔比':>14} {'本益比':>10} {'近5日最大跌幅':>14}")
    print("-" * 80)

    for dr in daily_results:
        d = dr["date"]
        li = dr["li"]
        close = dr["close"]
        pe = dr["pe"]

        total_scanned += 1
        sell_pct = f"{li.sell_pct:.2f}%" if li.sell_pct is not None else "N/A"
        pe_str = f"{pe:.1f}" if pe > 0 else "N/A"
        drop = f"{li.max_single_day_drop_pct:.2f}%"
        flag = "🔴 是" if li.triggered else "— 否"
        print(f"{d:<12} {flag:<8} {close:>10.1f} {sell_pct:>14} {pe_str:>10} {drop:>14}")

        if li.triggered:
            triggered_days.append((d, close))
            streak_no_trigger = 0
        else:
            streak_no_trigger += 1
            if streak_no_trigger >= stop_streak:
                stop_date = d
                break

    # ── 摘要 ──
    print("-" * 80)
    print(f"掃描交易日數（含停止日）: {total_scanned}")
    print(f"連續 {stop_streak} 日未觸發停止於: {stop_date}")
    print(f"領先指標觸發天數: {len(triggered_days)}")
    if triggered_days:
        print("觸發日與當日收盤價:")
        for d, c in triggered_days:
            print(f"  {d}  收盤價 {c:.1f}")
    else:
        print("無任何交易日觸發領先指標。")


def main():
    parser = argparse.ArgumentParser(description="領先指標（預測用）as-of 回測")
    parser.add_argument("--start", type=str, default=None, help="起始日期 (YYYY-MM-DD)，預設為互動式輸入")
    parser.add_argument("--latest", action="store_true", help="從最新交易日往前回測")
    args = parser.parse_args()

    if args.latest:
        # 找最新交易日
        loader = BacktestDataLoader()
        data = loader.load_all()
        inst_dates = {r["date"] for r in data["inst_rows"]}
        close_lookup = {r["date"]: float(r["close"]) for r in data["ohlc"]}
        shareholding_lookup = {r["date"]: r for r in data["shareholding"]}
        trading_days = sorted(
            (d for d in inst_dates if d in close_lookup and d in shareholding_lookup),
            reverse=True
        )
        start_date = trading_days[0]
        print(f"使用最新交易日: {start_date}")
    elif args.start:
        start_date = args.start
    else:
        # 互動式輸入
        print(f"預設起始日: {DEFAULT_START_DATE}")
        user_input = input(f"請輸入起始日期 (YYYY-MM-DD) [直接按 Enter 使用 {DEFAULT_START_DATE}]: ").strip()
        start_date = user_input if user_input else DEFAULT_START_DATE

    run_backtest(start_date)


if __name__ == "__main__":
    main()