#!/usr/bin/env python3
"""
Leading Indicator Crash Avoidance Backtest (PE > 30 Strict Version)
====================================================================

嚴格版：PE 門檻固定 30（泡沫區才預警）、外資賣超佔比 > 1%、近 5 日無單日大跌 > 5%。
新增：觸發後 20 個交易日內「有更低價格買回」機會分析。

策略：
1. 主要領先指標：PE > 30 + 外資兩月淨賣超佔外資持股 > 1% + 近 5 日無單日大跌 > 5%
2. 觸發後觀察隨後 20 個交易日：最低收盤價是否 < 觸發日收盤價、何日最低、是否回升
3. 僅在泡沫期（PE > 30）發出預警，接受較低召回率換取高精確度
"""

import json
import datetime as dt
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import argparse

import pandas as pd

from signal_engine import (
    compute_leading_indicator,
    compute_trailing_pe,
    LeadingIndicator,
)
from config import CONFIG

# ── 參數 ──
CRASH_THRESHOLD_PCT = -5.0
WARNING_WINDOW_DAYS = 10
CLUSTER_MAX_GAP = 3
COOLDOWN_DAYS = 5
EPS_REPORT_LAG_DAYS = 50
BUYBACK_WINDOW_DAYS = 20        # 買回觀察窗口：20 個交易日

# ── 讀取快取 ──
def _load(path: str):
    with open(path) as f:
        return json.load(f)["data"]

print("Loading cached data...")
INST_ROWS = _load("local_cache/hcd_finmind_inst_rows_2330_2023-04-06_2026-07-19.json")
SHAREHOLDING = _load("local_cache/hcd_finmind_shareholding_2330_2023-04-06_2026-07-19.json")
OHLC = _load("local_cache/hcd_yahoo_ohlcv_2330.TW_1672531200_1784419200.json")
WIDE_FIN = json.load(
    open("local_cache/finmind_TaiwanStockFinancialStatements_2330_wide_20260719_213936_266291.json")
)["data"]

# EPS 時間線
EPS_BY_QEND = {}
for r in WIDE_FIN:
    if r["type"] == "EPS" and r.get("value") is not None:
        EPS_BY_QEND[r["date"]] = float(r["value"])

EPS_KNOWN = []
for qend, eps in sorted(EPS_BY_QEND.items()):
    qe = datetime.strptime(qend, "%Y-%m-%d")
    report = (qe + timedelta(days=EPS_REPORT_LAG_DAYS)).strftime("%Y-%m-%d")
    year, month = qe.year, qe.month
    quarter = {3: 1, 6: 2, 9: 3, 12: 4}[month]
    EPS_KNOWN.append((report, year, quarter, eps))
EPS_KNOWN.sort()

def eps_asof(asof: str) -> dict:
    known = [(y, q, e) for (rep, y, q, e) in EPS_KNOWN if rep <= asof]
    return {(y, q): {"eps": e} for (y, q, e) in known[-4:]}

CLOSE = {r["date"]: float(r["close"]) for r in OHLC}
SH_BY_DATE = {r["date"]: r for r in SHAREHOLDING}

def foreign_shares_asof(asof: str) -> Optional[float]:
    cand = [d for d in SHAREHOLDING if d["date"] <= asof]
    if not cand:
        return None
    return float(max(cand, key=lambda r: r["date"])["foreign_shares"])

def price_df_asof(asof: str) -> pd.DataFrame:
    rows = [{"date": r["date"], "台積電收盤價": float(r["close"])}
            for r in OHLC if r["date"] <= asof]
    return pd.DataFrame(rows)

def compute_daily_returns() -> Dict[str, float]:
    dates = sorted(CLOSE.keys())
    returns = {}
    for i in range(1, len(dates)):
        prev = CLOSE[dates[i-1]]
        cur = CLOSE[dates[i]]
        if prev > 0:
            returns[dates[i]] = (cur - prev) / prev * 100
    return returns

DAILY_RETURNS = compute_daily_returns()

# ── 計算每日領先指標（嚴格版 PE > 30） ──
def compute_leading_indicator_strict(
    chip_data,
    foreign_shares,
    pe_ratio,
    price_df
) -> LeadingIndicator:
    """
    嚴格版領先指標：PE 門檻固定 30（從 CONFIG 讀取），不降低門檻。

    觸發條件（三者同時成立）：
    1. 往前兩個月累計淨賣超佔外資持股 > 1%（two_month_high_sellout_pct = 0.01）
    2. 本益比 (TTM) > 30 倍（leading_indicator_pe_threshold = 30，泡沫區才預警）
    3. 往前五個交易日，不曾單日大跌超過 5%

    觸發即視為「強制紅燈」領先訊號。
    """
    from signal_engine import CONFIG, _foreign_daily_net, _two_month_window

    pct_threshold = CONFIG.chip.two_month_high_sellout_pct  # 0.01 (1%)
    pe_threshold = CONFIG.chip.leading_indicator_pe_threshold  # 30.0 (嚴格版)
    window_days = CONFIG.chip.two_month_window_days
    denom = foreign_shares if (foreign_shares and foreign_shares > 0) else CONFIG.chip.tsmc_float_shares
    denom_label = "外資持股" if (foreign_shares and foreign_shares > 0) else "流通股"

    result = LeadingIndicator(
        pct_threshold=pct_threshold,
        pe_threshold=pe_threshold,
        window_days=window_days,
        foreign_holdings=denom,
        denom_label=denom_label,
        pe_ratio=pe_ratio,
    )

    series = _foreign_daily_net(chip_data)
    if series is None or len(series) == 0:
        result.note = "籌碼資料不足"
        return result

    result.available = True
    window_start, window_end, window_series = _two_month_window(series, window_days)
    result.window_start = window_start
    result.window_end = window_end
    result.window_sessions = len(window_series)
    cumulative = float(window_series.sum())
    result.cumulative_sell_shares = abs(cumulative) if cumulative < 0 else 0.0

    if denom and denom > 0:
        result.sell_pct = result.cumulative_sell_shares / denom * 100

    # 條件 3：近 5 日無單日大跌 > 5%
    no_crash = True
    max_drop = 0.0
    if price_df is not None and not price_df.empty and "台積電收盤價" in price_df.columns:
        recent = price_df["台積電收盤價"].dropna().tail(5)
        if len(recent) >= 2:
            pct_changes = recent.pct_change().dropna()
            max_drop = abs(pct_changes.min()) * 100
            no_crash = max_drop <= 5.0
    result.max_single_day_drop_pct = max_drop

    triggered = (
        result.sell_pct is not None
        and result.sell_pct > pct_threshold * 100
        and pe_ratio > pe_threshold
        and no_crash
    )
    result.triggered = triggered
    result.forced_red = triggered
    if not no_crash:
        result.note = f"近 5 日有單日跌幅 {max_drop:.2f}% > 5%"
    return result


# ── 掃描完整歷史 ──
def scan_full_history() -> List[Dict]:
    inst_dates = {r["date"] for r in INST_ROWS}
    trading_days = sorted(d for d in inst_dates if d in CLOSE and d in SH_BY_DATE)
    print(f"掃描交易日區間: {trading_days[0]} ~ {trading_days[-1]} (共 {len(trading_days)} 日)")

    results = []

    for d in trading_days:
        chip_data = [r for r in INST_ROWS if r["date"] <= d]
        fsh = foreign_shares_asof(d)
        close = CLOSE[d]
        pe = compute_trailing_pe(close, eps_asof(d))
        pdf = price_df_asof(d)

        # 嚴格版領先指標 (PE > 30)
        li = compute_leading_indicator_strict(chip_data, fsh, pe, pdf)

        results.append({
            "date": d,
            "close": close,
            "pe": pe,
            "foreign_shares": fsh,
            "li": li,
        })

        if li.triggered:
            print(f"  🔴 {d} 觸發 | 收盤 {close:.1f} | 賣超佔比 {li.sell_pct:.2f}% | PE {pe:.1f} | 近5日最大跌幅 {li.max_single_day_drop_pct:.2f}%")

    triggered_count = sum(1 for r in results if r["li"].triggered)
    print(f"\n嚴格版 (PE>30) 觸發: {triggered_count} 次")

    return results


# ── 群集化 ──
def group_trigger_clusters(daily_results: List[Dict]) -> List[Dict]:
    triggered_days = [r for r in daily_results if r["li"].triggered]
    if not triggered_days:
        return []

    clusters = []
    current = [triggered_days[0]]

    for i in range(1, len(triggered_days)):
        prev_date = current[-1]["date"]
        curr_date = triggered_days[i]["date"]
        all_days = [r["date"] for r in daily_results]
        try:
            gap = all_days.index(curr_date) - all_days.index(prev_date) - 1
        except ValueError:
            gap = CLUSTER_MAX_GAP + 1

        if gap <= CLUSTER_MAX_GAP:
            current.append(triggered_days[i])
        else:
            clusters.append(current)
            current = [triggered_days[i]]
    clusters.append(current)

    cluster_infos = []
    for cl in clusters:
        start = cl[0]["date"]
        end = cl[-1]["date"]
        rep = cl[len(cl) // 2]
        cluster_infos.append({
            "start_date": start, "end_date": end,
            "trigger_dates": [c["date"] for c in cl],
            "rep_date": rep["date"], "rep_close": rep["close"],
            "rep_li": rep["li"], "duration": len(cl),
        })
        print(f"群集: {start} ~ {end} ({len(cl)}日) | 代表日: {rep['date']} 收盤 {rep['close']:.1f}")

    return cluster_infos


# ── 找崩盤日 ──
def find_crash_dates(threshold: float = CRASH_THRESHOLD_PCT) -> List[Tuple[str, float]]:
    crashes = []
    for d, ret in DAILY_RETURNS.items():
        if ret <= threshold:
            crashes.append((d, ret))
    return sorted(crashes)


# ── 評估預警效果 ──
def evaluate_clusters(clusters: List[Dict], crash_dates: List[Tuple[str, float]],
                      daily_results: List[Dict], warning_window: int = WARNING_WINDOW_DAYS) -> Dict:
    all_trading_days = [r["date"] for r in daily_results]
    crash_set = {d for d, _ in crash_dates}

    tp = fp = fn = 0
    tp_details, fp_details, fn_details = [], [], []

    for crash_date, crash_ret in crash_dates:
        try:
            cidx = all_trading_days.index(crash_date)
        except ValueError:
            continue

        found = False
        for cl in clusters:
            try:
                end_idx = all_trading_days.index(cl["end_date"])
            except ValueError:
                continue
            if end_idx >= cidx:
                continue
            if cidx - end_idx <= warning_window:
                found = True
                tp += 1
                tp_details.append({"cluster": cl, "crash_date": crash_date,
                                   "crash_ret": crash_ret, "lead_days": cidx - end_idx})
                break
        if not found:
            fn += 1
            nearest = None
            for cl in reversed(clusters):
                try:
                    if all_trading_days.index(cl["end_date"]) < cidx:
                        nearest = cl["end_date"]
                        break
                except ValueError:
                    continue
            fn_details.append({"crash_date": crash_date, "crash_ret": crash_ret,
                               "nearest_cluster_end": nearest})

    for cl in clusters:
        try:
            end_idx = all_trading_days.index(cl["end_date"])
        except ValueError:
            continue
        future = all_trading_days[end_idx+1:end_idx+1+warning_window]
        if not any(d in crash_set for d in future):
            fp += 1
            max_drop = min(DAILY_RETURNS.get(d, 0) for d in future) if future else 0
            fp_details.append({"cluster": cl, "max_drop_in_window": max_drop})

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1,
            "tp_details": tp_details, "fp_details": fp_details, "fn_details": fn_details,
            "total_crashes": len(crash_dates), "total_clusters": len(clusters)}


def print_evaluation(stats: Dict):
    print(f"\n{'='*70}")
    print(f"📊 嚴格版 (PE>30) 崩盤預警評估")
    print(f"{'='*70}")
    print(f"崩盤門檻: ≤ {CRASH_THRESHOLD_PCT}% | 預警窗口: {WARNING_WINDOW_DAYS} 日")
    print(f"崩盤總數: {stats['total_crashes']} | 觸發群集: {stats['total_clusters']}")
    print(f"TP: {stats['tp']} | FP: {stats['fp']} | FN: {stats['fn']}")
    print(f"Precision: {stats['precision']:.1%} | Recall: {stats['recall']:.1%} | F1: {stats['f1']:.1%}")
    print("-"*70)
    for d in stats['tp_details']:
        cl = d['cluster']
        print(f"  ✅ 群集 {cl['start_date']}~{cl['end_date']} → {d['lead_days']}日後崩盤 {d['crash_date']} ({d['crash_ret']:+.2f}%)")
    for d in stats['fn_details']:
        near = f" (最近群集結束: {d['nearest_cluster_end']})" if d['nearest_cluster_end'] else " (前無群集)"
        print(f"  ❌ 崩盤 {d['crash_date']} ({d['crash_ret']:+.2f}%){near}")
    for d in stats['fp_details'][:10]:
        cl = d['cluster']
        print(f"  ⚠️ 群集 {cl['start_date']}~{cl['end_date']} → 未來 {WARNING_WINDOW_DAYS} 日最大跌幅 {d['max_drop_in_window']:+.2f}%")
    if len(stats['fp_details']) > 10:
        print(f"  ... 及其他 {len(stats['fp_details'])-10} 群")


# ── 買回機會分析（核心新增功能） ──
def analyze_buyback_opportunity(clusters: List[Dict], daily_results: List[Dict],
                                 buyback_window: int = BUYBACK_WINDOW_DAYS) -> Dict:
    """
    分析每個觸發群集後 20 個交易日內的買回機會。

    回傳：
    - 每群集：觸發日收盤價、最低價、最低價日期、是否低於觸發價、跌幅%、何日最低、是否回升超過觸發價
    - 彙總：買回成功率、平均最大跌幅、平均最低出現天數
    """
    all_days = [r["date"] for r in daily_results]
    buyback_results = []

    for cl in clusters:
        try:
            end_idx = all_days.index(cl["end_date"])
        except ValueError:
            continue

        entry_date = cl["end_date"]
        entry_price = cl["rep_close"]  # 用代表日收盤價作為賣出價

        # 觀察窗口：後續 20 個交易日
        window_end_idx = min(end_idx + buyback_window, len(all_days) - 1)
        window_days = all_days[end_idx + 1:window_end_idx + 1]

        if not window_days:
            buyback_results.append({
                "cluster": cl,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "window_days": 0,
                "min_price": None,
                "min_date": None,
                "min_rank": None,
                "max_price": None,
                "buyback_possible": False,
                "max_drawdown_pct": 0.0,
                "recovered_above_entry": False,
            })
            continue

        window_prices = [CLOSE[d] for d in window_days]
        min_price = min(window_prices)
        min_date = window_days[window_prices.index(min_price)]
        min_rank = window_prices.index(min_price) + 1  # 第幾個交易日出現最低
        max_price = max(window_prices)

        buyback_possible = min_price < entry_price
        max_drawdown_pct = (entry_price - min_price) / entry_price * 100 if entry_price > 0 else 0
        recovered_above_entry = max_price > entry_price

        buyback_results.append({
            "cluster": cl,
            "entry_date": entry_date,
            "entry_price": entry_price,
            "window_days": len(window_days),
            "min_price": min_price,
            "min_date": min_date,
            "min_rank": min_rank,
            "max_price": max_price,
            "buyback_possible": buyback_possible,
            "max_drawdown_pct": max_drawdown_pct,
            "recovered_above_entry": recovered_above_entry,
        })

    # 彙總統計
    total = len(buyback_results)
    successful = sum(1 for r in buyback_results if r["buyback_possible"])
    success_rate = successful / total if total > 0 else 0
    avg_drawdown = sum(r["max_drawdown_pct"] for r in buyback_results) / total if total > 0 else 0
    avg_min_rank = sum(r["min_rank"] for r in buyback_results if r["min_rank"]) / successful if successful > 0 else 0
    recovered_count = sum(1 for r in buyback_results if r["recovered_above_entry"])

    return {
        "details": buyback_results,
        "summary": {
            "total_clusters": total,
            "buyback_successful": successful,
            "buyback_success_rate": success_rate,
            "avg_max_drawdown_pct": avg_drawdown,
            "avg_min_rank_day": avg_min_rank,
            "recovered_above_entry_count": recovered_count,
            "recovered_rate": recovered_count / total if total > 0 else 0,
        }
    }


def print_buyback_analysis(buyback: Dict):
    print(f"\n{'='*70}")
    print(f"💰 觸發後 {BUYBACK_WINDOW_DAYS} 交易日買回機會分析")
    print(f"{'='*70}")
    print(f"觸發群集總數: {buyback['summary']['total_clusters']}")
    print(f"可更低買回: {buyback['summary']['buyback_successful']} ({buyback['summary']['buyback_success_rate']:.1%})")
    print(f"平均最大回檔: {buyback['summary']['avg_max_drawdown_pct']:.2f}%")
    print(f"平均最低價出現: 第 {buyback['summary']['avg_min_rank_day']:.1f} 個交易日")
    print(f"期間曾回升超過觸發價: {buyback['summary']['recovered_above_entry_count']} ({buyback['summary']['recovered_rate']:.1%})")
    print("-"*70)

    for r in buyback["details"]:
        cl = r["cluster"]
        bp = "✅ 是" if r["buyback_possible"] else "❌ 否"
        rec = "⬆ 是" if r["recovered_above_entry"] else "⬇ 否"
        dd = f"{r['max_drawdown_pct']:.2f}%" if r["buyback_possible"] else "—"
        print(f"  群集 {cl['start_date']}~{cl['end_date']} | 賣出 {r['entry_date']}@{r['entry_price']:.1f} | "
              f"最低 {r['min_date']}@{r['min_price']:.1f} (第{r['min_rank']}日) | "
              f"最大回檔 {dd} | 買回機會 {bp} | 回升 {rec}")


# ── 策略模擬（含買回） ──
def simulate_strategy_with_buyback(clusters: List[Dict], crash_dates: List[Tuple[str, float]],
                                    daily_results: List[Dict], warning_window: int = WARNING_WINDOW_DAYS,
                                    cooldown: int = COOLDOWN_DAYS, buyback_window: int = BUYBACK_WINDOW_DAYS) -> Dict:
    all_days = [r["date"] for r in daily_results]
    crash_set = {d for d, _ in crash_dates}

    total_avoided = 0.0
    total_missed = 0.0
    trades = []
    last_end_idx = -cooldown - 1

    for cl in clusters:
        try:
            end_idx = all_days.index(cl["end_date"])
        except ValueError:
            continue
        if end_idx - last_end_idx <= cooldown:
            continue

        entry_date = cl["end_date"]
        entry_price = CLOSE[entry_date]
        exit_idx = min(end_idx + warning_window, len(all_days) - 1)

        # 找下一群集開始
        for next_cl in clusters:
            try:
                ns = all_days.index(next_cl["start_date"])
                if ns > end_idx:
                    exit_idx = min(exit_idx, ns - 1)
                    break
            except ValueError:
                continue

        exit_date = all_days[exit_idx]
        exit_price = CLOSE[exit_date]

        period = all_days[end_idx+1:exit_idx+1]
        crashed = any(d in crash_set for d in period)
        crash_ret = DAILY_RETURNS[period[next(i for i,d in enumerate(period) if d in crash_set)]] if crashed else 0
        pnl = (exit_price - entry_price) / entry_price * 100

        # 買回分析：在 exit_date 之後 BUYBACK_WINDOW_DAYS 內是否有更低價
        buyback_start = exit_idx + 1
        buyback_end = min(buyback_start + buyback_window, len(all_days) - 1)
        buyback_days = all_days[buyback_start:buyback_end+1]
        buyback_prices = [CLOSE[d] for d in buyback_days] if buyback_days else []
        min_buyback_price = min(buyback_prices) if buyback_prices else None
        can_buyback_lower = min_buyback_price is not None and min_buyback_price < exit_price
        buyback_drawdown = (exit_price - min_buyback_price) / exit_price * 100 if can_buyback_lower else 0

        if crashed:
            total_avoided += abs(crash_ret)
            trades.append({"entry": entry_date, "exit": exit_date, "pnl": pnl,
                           "crashed": True, "crash_ret": crash_ret, "avoided": abs(crash_ret),
                           "can_buyback_lower": can_buyback_lower, "buyback_drawdown": buyback_drawdown})
        else:
            total_missed += max(0, pnl)
            trades.append({"entry": entry_date, "exit": exit_date, "pnl": pnl,
                           "crashed": False, "missed": max(0, pnl),
                           "can_buyback_lower": can_buyback_lower, "buyback_drawdown": buyback_drawdown})

        last_end_idx = exit_idx

    return {"total_avoided": total_avoided, "total_missed": total_missed,
            "net": total_avoided - total_missed, "trades": trades}


def print_simulation(sim: Dict):
    print(f"\n{'='*70}")
    print(f"💰 策略模擬 (含買回分析)")
    print(f"{'='*70}")
    print(f"交易次數: {len(sim['trades'])} | 避開跌幅: {sim['total_avoided']:.2f}% | 機會成本: {sim['total_missed']:.2f}% | 淨收益: {sim['net']:.2f}%")
    for t in sim['trades']:
        if t['crashed']:
            bb = f" | 可低買回 {t['buyback_drawdown']:.2f}%" if t.get('can_buyback_lower') else " | 無買回機會"
            print(f"  ✅ {t['entry']}→{t['exit']} 避開 {t['crash_ret']:+.2f}% (期間 {t['pnl']:+.2f}%){bb}")
        else:
            s = "📈" if t['pnl'] > 0 else "📉"
            bb = f" | 可低買回 {t['buyback_drawdown']:.2f}%" if t.get('can_buyback_lower') else " | 無買回機會"
            print(f"  {s} {t['entry']}→{t['exit']} 期間 {t['pnl']:+.2f}% (機會成本 {t.get('missed',0):.2f}%){bb}")


def main():
    parser = argparse.ArgumentParser(description="領先指標崩盤預警回測 (PE>30 嚴格版 + 買回分析)")
    parser.add_argument("--warning-window", type=int, default=10, help="預警窗口天數")
    parser.add_argument("--cluster-gap", type=int, default=3, help="群集最大間隔天數")
    parser.add_argument("--cooldown", type=int, default=5, help="交易冷卻天數")
    parser.add_argument("--buyback-window", type=int, default=20, help="買回觀察窗口(交易日)")
    parser.add_argument("--no-sim", action="store_true", help="不執行策略模擬")
    args = parser.parse_args()

    global WARNING_WINDOW_DAYS, CLUSTER_MAX_GAP, COOLDOWN_DAYS, BUYBACK_WINDOW_DAYS
    WARNING_WINDOW_DAYS = args.warning_window
    CLUSTER_MAX_GAP = args.cluster_gap
    COOLDOWN_DAYS = args.cooldown
    BUYBACK_WINDOW_DAYS = args.buyback_window

    # 1. 掃描歷史
    daily = scan_full_history()

    # 2. 崩盤日
    crashes = find_crash_dates()
    print(f"\n📉 歷史崩盤 (≤{CRASH_THRESHOLD_PCT}%): {len(crashes)} 次")
    for d, r in crashes:
        print(f"  {d}  {r:+.2f}%")

    # 3. 群集化
    clusters = group_trigger_clusters(daily)

    # 4. 評估預警效果
    stats = evaluate_clusters(clusters, crashes, daily)
    print_evaluation(stats)

    # 5. 買回機會分析
    buyback = analyze_buyback_opportunity(clusters, daily)
    print_buyback_analysis(buyback)

    # 6. 策略模擬
    if not args.no_sim:
        sim = simulate_strategy_with_buyback(clusters, crashes, daily)
        print_simulation(sim)

    # 7. 輸出摘要
    print(f"\n{'='*70}")
    print(f"📋 總結")
    print(f"{'='*70}")
    print(f"PE 門檻: > 30 (嚴格泡沫區預警)")
    print(f"外資賣超門檻: > 1% 佔外資持股")
    print(f"排除條件: 近 5 日有單日跌幅 > 5%")
    print(f"預警窗口: {WARNING_WINDOW_DAYS} 日 | 買回觀察: {BUYBACK_WINDOW_DAYS} 交易日")
    print(f"Precision: {stats['precision']:.1%} | Recall: {stats['recall']:.1%} | F1: {stats['f1']:.1%}")
    print(f"買回成功率: {buyback['summary']['buyback_success_rate']:.1%} | 平均最大回檔: {buyback['summary']['avg_max_drawdown_pct']:.2f}%")
    if not args.no_sim:
        print(f"策略淨收益: {sim['net']:.2f}% (避開 {sim['total_avoided']:.2f}% - 機會成本 {sim['total_missed']:.2f}%)")


if __name__ == "__main__":
    main()