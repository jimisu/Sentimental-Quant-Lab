#!/usr/bin/env python3
"""
領先指標（預測用）as-of 回測

從 2026-07-16 起往前逐交易日，以「當日可得資料」計算領先指標：
  - chip_data        : 截至該日的三大法人買賣超（外資每日淨買賣）
  - foreign_shares   : 截至該日的外資實際持股（強制紅燈分母）
  - pe_ratio         : 該日收盤價 ÷ 截至該日可得的近四季 EPS（含財報發布時滯 +50 日）
  - price_df         : 截至該日的收盤價序列（用於近 5 日無單日大跌 >5% 檢查）

觸發條件（三者同時成立，詳見 signal_engine.compute_leading_indicator）：
  1) 往前兩個月累計淨賣超佔外資持股 > 1%
  2) 本益比 (TTM) > 30 倍
  3) 往前五個交易日無單日大跌 > 5%

輸出：每個掃描交易日（日期 / 是否觸發 / 收盤價 / 三條件數值），
以及觸發天數與各觸發日收盤價；連續 3 個交易日未觸發即停止。

資料全程來自 local_cache，不觸網。
"""

import json
import datetime as dt
from datetime import datetime, timedelta

import pandas as pd

from signal_engine import compute_leading_indicator, compute_trailing_pe

# ── 回測參數 ──
START_DATE = "2026-07-16"
STOP_NO_TRIGGER_STREAK = 3          # 連續 N 日未觸發即停止
EPS_REPORT_LAG_DAYS = 50            # 季報視為「可得」的發布時滯（季底 + 50 日）

# ── 讀取 local_cache ──
def _load(path: str):
    with open(path) as f:
        return json.load(f)["data"]


INST_ROWS = _load("local_cache/hcd_finmind_inst_rows_2330_2023-04-06_2026-07-19.json")
SHAREHOLDING = _load("local_cache/hcd_finmind_shareholding_2330_2023-04-06_2026-07-19.json")
OHLC = _load("local_cache/hcd_yahoo_ohlcv_2330.TW_1672531200_1784419200.json")
WIDE_FIN = json.load(
    open("local_cache/finmind_TaiwanStockFinancialStatements_2330_wide_20260719_213936_266291.json")
)["data"]

# EPS 時間線：季底日 -> EPS（來自 wide 財報）
EPS_BY_QEND = {}
for r in WIDE_FIN:
    if r["type"] == "EPS" and r.get("value") is not None:
        EPS_BY_QEND[r["date"]] = float(r["value"])

# 每季 EPS 的「可得日」= 季底 + 時滯；外加 (year, quarter) 解析
EPS_KNOWN = []  # list of (report_date_str, year, quarter, eps)
for qend, eps in sorted(EPS_BY_QEND.items()):
    qe = datetime.strptime(qend, "%Y-%m-%d")
    report = (qe + timedelta(days=EPS_REPORT_LAG_DAYS)).strftime("%Y-%m-%d")
    year, month = qe.year, qe.month
    quarter = {3: 1, 6: 2, 9: 3, 12: 4}[month]
    EPS_KNOWN.append((report, year, quarter, eps))
EPS_KNOWN.sort()


def eps_asof(asof: str) -> dict:
    """截至 asof 可得的近四季 EPS，組成 {(year, quarter): {"eps": v}}。"""
    known = [(y, q, e) for (rep, y, q, e) in EPS_KNOWN if rep <= asof]
    return {(y, q): {"eps": e} for (y, q, e) in known[-4:]}


# 收盤價查表（日期 -> 收盤）
CLOSE = {r["date"]: float(r["close"]) for r in OHLC}
# 外資持股查表（日期 -> foreign_shares），用於取「最新 <= asof」
SH_BY_DATE = {r["date"]: r for r in SHAREHOLDING}


def foreign_shares_asof(asof: str) -> float:
    cand = [d for d in SHAREHOLDING if d["date"] <= asof]
    if not cand:
        return None
    return float(max(cand, key=lambda r: r["date"])["foreign_shares"])


def price_df_asof(asof: str) -> pd.DataFrame:
    rows = [{"date": r["date"], "台積電收盤價": float(r["close"])}
            for r in OHLC if r["date"] <= asof]
    return pd.DataFrame(rows)


def main():
    # 交易日宇宙：同時具備法人買賣超與收盤價的日期，降冪排序
    inst_dates = {r["date"] for r in INST_ROWS}
    trading_days = sorted(
        (d for d in inst_dates if d in CLOSE and d in SH_BY_DATE), reverse=True
    )

    if START_DATE not in trading_days:
        # 向後找最近的交易日
        earlier = [d for d in trading_days if d <= START_DATE]
        start = earlier[0] if earlier else trading_days[0]
        print(f"⚠️ {START_DATE} 非交易日/缺資料，改自 {start} 起算")
    else:
        start = START_DATE

    # 自 start 往前的交易日序列
    seq = [d for d in trading_days if d <= start]

    print(f"{'日期':<12} {'觸發':<6} {'收盤價':>9} {'淨賣超佔比':>12} {'本益比':>8} {'近5日最大跌':>12}")
    print("-" * 78)

    triggered_days = []          # (date, close)
    streak_no_trigger = 0
    stop_date = None
    total_scanned = 0

    for d in seq:
        chip_data = [r for r in INST_ROWS if r["date"] <= d]
        fsh = foreign_shares_asof(d)
        close = CLOSE[d]
        pe = compute_trailing_pe(close, eps_asof(d))
        pdf = price_df_asof(d)
        li = compute_leading_indicator(chip_data, fsh, pe, price_df=pdf)

        total_scanned += 1
        sell_pct = f"{li.sell_pct:.2f}%" if li.sell_pct is not None else "N/A"
        pe_str = f"{pe:.1f}" if pe > 0 else "N/A"
        drop = f"{li.max_single_day_drop_pct:.2f}%"
        flag = "🔴是" if li.triggered else "—否"
        print(f"{d:<12} {flag:<6} {close:>9.1f} {sell_pct:>12} {pe_str:>8} {drop:>12}")

        if li.triggered:
            triggered_days.append((d, close))
            streak_no_trigger = 0
        else:
            streak_no_trigger += 1
            if streak_no_trigger >= STOP_NO_TRIGGER_STREAK:
                stop_date = d
                break

    # ── 摘要 ──
    print("-" * 78)
    print(f"掃描交易日數（含停止日）: {total_scanned}")
    print(f"連續 {STOP_NO_TRIGGER_STREAK} 日未觸發停止於: {stop_date}")
    print(f"領先指標觸發天數: {len(triggered_days)}")
    if triggered_days:
        print("觸發日與當日收盤價:")
        for d, c in triggered_days:
            print(f"  {d}  收盤價 {c:.1f}")
    else:
        print("無任何交易日觸發領先指標。")


if __name__ == "__main__":
    main()
