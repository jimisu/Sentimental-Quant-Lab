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

import argparse
import datetime as dt
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backtest_core import (
    BacktestDataLoader,
    CachedDataPaths,
    EPSTimeline,
    LeadingIndicatorAnalyzer,
    LeadingIndicatorConfig,
    cluster_triggers,
    TriggerCluster,
    BacktestEvaluator,
    EvaluationResult,
    StrategySimulator,
    SimulationResult,
    BuybackAnalyzer,
    BuybackSummary,
    print_evaluation,
    print_simulation,
    print_buyback_analysis,
    compute_trailing_pe,
    build_price_lookup,
    compute_daily_returns,
)

# ── 參數 ──
CRASH_THRESHOLD_PCT = -5.0
WARNING_WINDOW_DAYS = 10
CLUSTER_MAX_GAP = 3
COOLDOWN_DAYS = 5
EPS_REPORT_LAG_DAYS = 50
BUYBACK_WINDOW_DAYS = 20        # 買回觀察窗口：20 個交易日


def find_crash_dates(daily_returns: Dict[str, float], threshold: float = CRASH_THRESHOLD_PCT) -> List[Tuple[str, float]]:
    """找出崩盤日（日報酬率 <= threshold）"""
    crashes = []
    for d, ret in daily_returns.items():
        if ret <= threshold:
            crashes.append((d, ret))
    return sorted(crashes)


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

    # 1. 載入資料
    print("Loading cached data...")
    loader = BacktestDataLoader()
    data = loader.load_all()

    inst_rows = data["inst_rows"]
    shareholding = data["shareholding"]
    ohlc = data["ohlc"]
    wide_fin = data["wide_fin"]

    # 2. 建構 EPS 時間線
    eps_timeline = EPSTimeline.from_wide_financial(wide_fin, EPS_REPORT_LAG_DAYS)

    # 3. 建構查表
    close_lookup = build_price_lookup(ohlc)
    daily_returns = compute_daily_returns(close_lookup)

    # 4. 初始化領先指標分析器（嚴格版：使用預設 config，PE>30）
    analyzer = LeadingIndicatorAnalyzer(
        inst_rows=inst_rows,
        shareholding_data=shareholding,
        ohlc_data=ohlc,
        eps_timeline=eps_timeline,
    )

    # 5. 掃描完整歷史
    inst_dates = {r["date"] for r in inst_rows}
    trading_days = sorted(d for d in inst_dates if d in close_lookup and d in {r["date"] for r in shareholding})
    print(f"掃描交易日區間: {trading_days[0]} ~ {trading_days[-1]} (共 {len(trading_days)} 日)")

    daily_results = []
    for d in trading_days:
        li = analyzer.compute_strict_for_date(d)
        close = close_lookup[d]

        daily_results.append({
            "date": d,
            "close": close,
            "pe": li.pe_ratio,
            "foreign_shares": li.foreign_holdings if li.foreign_holdings > 0 else None,
            "li": li,
        })

        if li.triggered:
            print(f"  🔴 {d} 觸發 | 收盤 {close:.1f} | 賣超佔比 {li.sell_pct:.2f}% | PE {li.pe_ratio:.1f} | 近5日最大跌幅 {li.max_single_day_drop_pct:.2f}%")

    triggered_count = sum(1 for r in daily_results if r["li"].triggered)
    print(f"\n嚴格版 (PE>30) 觸發: {triggered_count} 次")

    # 6. 群集化
    clusters = cluster_triggers(
        daily_results,
        trigger_key="li.triggered",
        max_gap_days=CLUSTER_MAX_GAP,
        data_key="li",
    )

    # 7. 崩盤日
    crashes = find_crash_dates(daily_returns)
    print(f"\n📉 歷史崩盤 (≤{CRASH_THRESHOLD_PCT}%): {len(crashes)} 次")
    for d, r in crashes:
        print(f"  {d}  {r:+.2f}%")

    # 8. 評估預警效果
    all_trading_days = [r["date"] for r in daily_results]
    evaluator = BacktestEvaluator(crash_threshold=CRASH_THRESHOLD_PCT, warning_window=WARNING_WINDOW_DAYS)
    eval_result = evaluator.evaluate(
        clusters=[{
            "start_date": c.start_date,
            "end_date": c.end_date,
            "trigger_dates": c.trigger_dates,
            "rep_date": c.rep_date,
            "rep_close": c.rep_close,
            "rep_li": c.rep_data,
            "duration": c.duration,
        } for c in clusters],
        crash_dates=crashes,
        all_trading_days=all_trading_days,
        daily_returns=daily_returns,
    )

    # 為了相容 print_evaluation，需要補充一些屬性
    eval_result.total_crashes = len(crashes)
    eval_result.total_clusters = len(clusters)
    eval_result.warning_window = WARNING_WINDOW_DAYS

    print_evaluation(eval_result)

    # 9. 買回機會分析
    buyback_analyzer = BuybackAnalyzer(buyback_window=BUYBACK_WINDOW_DAYS)
    buyback = buyback_analyzer.analyze(
        clusters=[{
            "start_date": c.start_date,
            "end_date": c.end_date,
            "rep_close": c.rep_close,
        } for c in clusters],
        all_trading_days=all_trading_days,
        close_prices=close_lookup,
    )
    print_buyback_analysis(buyback, window=BUYBACK_WINDOW_DAYS)

    # 10. 策略模擬
    if not args.no_sim:
        simulator = StrategySimulator(
            warning_window=WARNING_WINDOW_DAYS,
            cooldown_days=COOLDOWN_DAYS,
            buyback_window=BUYBACK_WINDOW_DAYS,
            crash_threshold=CRASH_THRESHOLD_PCT,
        )
        sim_result = simulator.simulate(
            clusters=[{
                "start_date": c.start_date,
                "end_date": c.end_date,
                "rep_close": c.rep_close,
            } for c in clusters],
            crash_dates=crashes,
            all_trading_days=all_trading_days,
            close_prices=close_lookup,
            daily_returns=daily_returns,
        )
        print_simulation(sim_result)

    # 11. 輸出摘要
    print(f"\n{'='*70}")
    print(f"📋 總結")
    print(f"{'='*70}")
    print(f"PE 門檻: > 30 (嚴格泡沫區預警)")
    print(f"外資賣超門檻: > 1% 佔外資持股")
    print(f"排除條件: 近 5 日有單日跌幅 > 5%")
    print(f"預警窗口: {WARNING_WINDOW_DAYS} 日 | 買回觀察: {BUYBACK_WINDOW_DAYS} 交易日")
    print(f"Precision: {eval_result.precision:.1%} | Recall: {eval_result.recall:.1%} | F1: {eval_result.f1:.1%}")
    print(f"買回成功率: {buyback.buyback_success_rate:.1%} | 平均最大回檔: {buyback.avg_max_drawdown_pct:.2f}%")
    if not args.no_sim:
        print(f"策略淨收益: {sim_result.net_pnl:.2f}% (避開 {sim_result.total_avoided:.2f}% - 機會成本 {sim_result.total_missed:.2f}%)")


if __name__ == "__main__":
    main()