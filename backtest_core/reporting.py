"""
Reporting Module
================
統一的報表生成與列印工具，提供回測結果的標準化輸出格式。
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple

from .evaluator import EvaluationResult
from .simulator import SimulationResult
from .buyback_analyzer import BuybackSummary
from .cluster import TriggerCluster


def print_evaluation(result: EvaluationResult, label: str = "",
                     crash_threshold: float = -5.0, warning_window: int = 10) -> None:
    """
    列印評估結果

    Args:
        result: EvaluationResult 物件
        label: 標籤前綴（如 "原版 (PE>30)"、"優化版 (PE>25)"）
        crash_threshold: 崩盤門檻
        warning_window: 預警窗口
    """
    prefix = f" {label}" if label else ""
    print(f"\n{'='*70}")
    print(f"📊{prefix}崩盤預警評估")
    print(f"{'='*70}")
    print(f"崩盤門檻: ≤ {crash_threshold}% | 預警窗口: {warning_window} 日")
    print(f"崩盤總數: {result.total_crashes} | 觸發群集: {result.total_clusters}")
    print(f"TP: {result.tp} | FP: {result.fp} | FN: {result.fn}")
    print(f"Precision: {result.precision:.1%} | Recall: {result.recall:.1%} | F1: {result.f1:.1%}")
    print("-"*70)

    for d in result.tp_details:
        cl = d["cluster"]
        print(f"  ✅ 群集 {cl['start_date']}~{cl['end_date']} → "
              f"{d['lead_days']}日後崩盤 {d['crash_date']} ({d['crash_return']:+.2f}%)")

    for d in result.fn_details:
        near = f" (最近群集結束: {d['nearest_cluster_end']})" if d.get("nearest_cluster_end") else " (前無群集)"
        print(f"  ❌ 崩盤 {d['crash_date']} ({d['crash_return']:+.2f}%){near}")

    for d in result.fp_details[:10]:
        cl = d["cluster"]
        print(f"  ⚠️ 群集 {cl['start_date']}~{cl['end_date']} → "
              f"未來 {warning_window} 日最大跌幅 {d['max_drop_in_window']:+.2f}%")

    if len(result.fp_details) > 10:
        print(f"  ... 及其他 {len(result.fp_details) - 10} 群")


def print_simulation(result: SimulationResult, label: str = "") -> None:
    """
    列印策略模擬結果
    """
    prefix = f" {label}" if label else ""
    print(f"\n{'='*70}")
    print(f"💰{prefix}策略模擬")
    print(f"{'='*70}")
    print(f"交易次數: {len(result.trades)} | "
          f"避開跌幅: {result.total_avoided:.2f}% | "
          f"機會成本: {result.total_missed:.2f}% | "
          f"淨收益: {result.net_pnl:.2f}%")

    for t in result.trades:
        if t.crashed:
            bb = f" | 可低買回 {t.buyback_drawdown_pct:.2f}%" if t.can_buyback_lower else " | 無買回機會"
            print(f"  ✅ {t.entry_date}→{t.exit_date} "
                  f"避開 {t.crash_return:+.2f}% (期間 {t.pnl_pct:+.2f}%){bb}")
        else:
            s = "📈" if t.pnl_pct > 0 else "📉"
            bb = f" | 可低買回 {t.buyback_drawdown_pct:.2f}%" if t.can_buyback_lower else " | 無買回機會"
            print(f"  {s} {t.entry_date}→{t.exit_date} "
                  f"期間 {t.pnl_pct:+.2f}% (機會成本 {t.missed_pct:.2f}%){bb}")


def print_buyback_analysis(buyback: BuybackSummary, window: int = 20) -> None:
    """
    列印買回分析結果
    """
    s = buyback
    print(f"\n{'='*70}")
    print(f"💰 觸發後 {window} 交易日買回機會分析")
    print(f"{'='*70}")
    print(f"觸發群集總數: {s.total_clusters}")
    print(f"可更低買回: {s.buyback_successful} ({s.buyback_success_rate:.1%})")
    print(f"平均最大回檔: {s.avg_max_drawdown_pct:.2f}%")
    print(f"平均最低價出現: 第 {s.avg_min_rank_day:.1f} 個交易日")
    print(f"期間曾回升超過觸發價: {s.recovered_above_entry_count} ({s.recovered_rate:.1%})")
    print("-"*70)

    for r in s.details:
        bp = "✅ 是" if r.buyback_possible else "❌ 否"
        rec = "⬆ 是" if r.recovered_above_entry else "⬇ 否"
        dd = f"{r.max_drawdown_pct:.2f}%" if r.buyback_possible else "—"
        print(f"  群集 {r.cluster_start}~{r.cluster_end} | "
              f"賣出 {r.entry_date}@{r.entry_price:.1f} | "
              f"最低 {r.min_date}@{r.min_price:.1f} (第{r.min_rank}日) | "
              f"最大回檔 {dd} | 買回機會 {bp} | 回升 {rec}")


def print_leading_indicator_scan(daily_results: List[Dict[str, Any]],
                                  stop_streak: int = 10) -> None:
    """
    列印領先指標逐日掃描結果（對應 leading_indicator_backtest.py）
    """
    print(f"{'日期':<12} {'觸發':<8} {'收盤價':>10} {'淨賣超佔比':>14} {'本益比':>10} {'近5日最大跌幅':>14}")
    print("-" * 80)

    streak = 0
    triggered_days = []
    stop_date = None

    for r in daily_results:
        li = r.get("li") or r.get("li_opt") or r.get("li_orig")
        if not li:
            continue

        sell_pct = f"{li.sell_pct:.2f}%" if li.sell_pct is not None else "N/A"
        pe = f"{r['pe']:.1f}" if r.get("pe", 0) > 0 else "N/A"
        drop = f"{li.max_single_day_drop_pct:.2f}%"
        flag = "🔴 是" if li.triggered else "— 否"

        print(f"{r['date']:<12} {flag:<8} {r['close']:>10.1f} {sell_pct:>14} {pe:>10} {drop:>14}")

        if li.triggered:
            triggered_days.append((r['date'], r['close']))
            streak = 0
        else:
            streak += 1
            if streak >= stop_streak and stop_date is None:
                stop_date = r['date']

    print("-" * 80)
    print(f"掃描交易日數: {len(daily_results)}")
    print(f"連續 {stop_streak} 日未觸發停止於: {stop_date}")
    print(f"領先指標觸發天數: {len(triggered_days)}")
    if triggered_days:
        print("觸發日與當日收盤價:")
        for d, c in triggered_days:
            print(f"  {d}  收盤價 {c:.1f}")
    else:
        print("無任何交易日觸發領先指標。")


def print_clusters(clusters: List[TriggerCluster], label: str = "") -> None:
    """
    列印群集資訊
    """
    prefix = f" ({label})" if label else ""
    print(f"\n{'='*70}")
    print(f"📦 觸發群集{prefix}")
    print(f"{'='*70}")

    for cl in clusters:
        print(f"群集: {cl.start_date} ~ {cl.end_date} ({cl.duration}日) | "
              f"代表日: {cl.rep_date} 收盤 {cl.rep_close:.1f}")


def print_crash_dates(crash_dates: List[Tuple[str, float]], threshold: float = -5.0) -> None:
    """
    列印崩盤日期
    """
    print(f"\n📉 歷史崩盤 (≤{threshold}%): {len(crash_dates)} 次")
    for d, r in crash_dates:
        print(f"  {d}  {r:+.2f}%")


def print_summary(
    pe_threshold: float,
    sell_pct_threshold: float,
    max_drop_pct: float,
    warning_window: int,
    buyback_window: int,
    evaluation: EvaluationResult,
    buyback: Optional[BuybackSummary] = None,
    simulation: Optional[SimulationResult] = None,
) -> None:
    """
    列印完整回測摘要
    """
    print(f"\n{'='*70}")
    print(f"📋 總結")
    print(f"{'='*70}")
    print(f"PE 門檻: > {pe_threshold:.0f}")
    print(f"外資賣超門檻: > {sell_pct_threshold*100:.0f}% 佔外資持股")
    print(f"排除條件: 近 5 日有單日跌幅 > {max_drop_pct:.0f}%")
    print(f"預警窗口: {warning_window} 日 | 買回觀察: {buyback_window} 交易日")
    print(f"Precision: {evaluation.precision:.1%} | Recall: {evaluation.recall:.1%} | F1: {evaluation.f1:.1%}")

    if buyback:
        print(f"買回成功率: {buyback.buyback_success_rate:.1%} | "
              f"平均最大回檔: {buyback.avg_max_drawdown_pct:.2f}%")

    if simulation:
        print(f"策略淨收益: {simulation.net_pnl:.2f}% "
              f"(避開 {simulation.total_avoided:.2f}% - 機會成本 {simulation.total_missed:.2f}%)")


def generate_markdown_report(
    title: str,
    evaluation: EvaluationResult,
    buyback: Optional[BuybackSummary] = None,
    simulation: Optional[SimulationResult] = None,
    clusters: Optional[List[TriggerCluster]] = None,
    crash_dates: Optional[List[Tuple[str, float]]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    生成 Markdown 格式回測報告

    Args:
        title: 報告標題
        evaluation: 評估結果
        buyback: 買回分析結果
        simulation: 模擬結果
        clusters: 群集列表
        crash_dates: 崩盤日期列表
        config: 回測參數設定

    Returns:
        Markdown 字串
    """
    lines = []
    lines.append(f"# {title}")
    lines.append("")

    # 參數設定
    if config:
        lines.append("## 回測參數")
        lines.append("")
        for k, v in config.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    # 評估結果
    lines.append("## 預警效能評估")
    lines.append("")
    lines.append(f"- 崩盤總數: {evaluation.total_crashes}")
    lines.append(f"- 觸發群集: {evaluation.total_clusters}")
    lines.append(f"- TP: {evaluation.tp} | FP: {evaluation.fp} | FN: {evaluation.fn}")
    lines.append(f"- Precision: {evaluation.precision:.1%}")
    lines.append(f"- Recall: {evaluation.recall:.1%}")
    lines.append(f"- F1: {evaluation.f1:.1%}")
    lines.append("")

    # TP 明細
    if evaluation.tp_details:
        lines.append("### 真陽性 (TP) - 成功預警")
        lines.append("")
        lines.append("| 群集區間 | 代表日 | 領先天數 | 崩盤日 | 崩盤跌幅 |")
        lines.append("|----------|--------|----------|--------|----------|")
        for d in evaluation.tp_details:
            cl = d["cluster"]
            lines.append(f"| {cl['start_date']}~{cl['end_date']} | "
                        f"{cl.get('rep_date', '-') or '-'} | "
                        f"{d['lead_days']} | {d['crash_date']} | {d['crash_return']:+.2f}% |")
        lines.append("")

    # FN 明細
    if evaluation.fn_details:
        lines.append("### 假陰性 (FN) - 漏報崩盤")
        lines.append("")
        lines.append("| 崩盤日 | 崩盤跌幅 | 最近群集結束 |")
        lines.append("|--------|----------|--------------|")
        for d in evaluation.fn_details:
            near = d.get("nearest_cluster_end", "無")
            lines.append(f"| {d['crash_date']} | {d['crash_return']:+.2f}% | {near} |")
        lines.append("")

    # FP 明細
    if evaluation.fp_details:
        lines.append("### 假陽性 (FP) - 誤報預警")
        lines.append("")
        lines.append("| 群集區間 | 代表日 | 窗口內最大跌幅 |")
        lines.append("|----------|--------|----------------|")
        for d in evaluation.fp_details[:20]:
            cl = d["cluster"]
            lines.append(f"| {cl['start_date']}~{cl['end_date']} | "
                        f"{cl.get('rep_date', '-') or '-'} | {d['max_drop_in_window']:+.2f}% |")
        if len(evaluation.fp_details) > 20:
            lines.append(f"| ... | ... | ... (共 {len(evaluation.fp_details)} 筆) |")
        lines.append("")

    # 買回分析
    if buyback:
        s = buyback
        lines.append("## 買回機會分析")
        lines.append("")
        lines.append(f"- 觸發群集總數: {s.total_clusters}")
        lines.append(f"- 可更低買回: {s.buyback_successful} ({s.buyback_success_rate:.1%})")
        lines.append(f"- 平均最大回檔: {s.avg_max_drawdown_pct:.2f}%")
        lines.append(f"- 平均最低價出現: 第 {s.avg_min_rank_day:.1f} 個交易日")
        lines.append(f"- 期間曾回升超過觸發價: {s.recovered_above_entry_count} ({s.recovered_rate:.1%})")
        lines.append("")

    # 模擬結果
    if simulation:
        lines.append("## 策略模擬")
        lines.append("")
        lines.append(f"- 交易次數: {len(simulation.trades)}")
        lines.append(f"- 避開跌幅: {simulation.total_avoided:.2f}%")
        lines.append(f"- 機會成本: {simulation.total_missed:.2f}%")
        lines.append(f"- 淨收益: {simulation.net_pnl:.2f}%")
        lines.append("")

        if simulation.trades:
            lines.append("### 交易明細")
            lines.append("")
            lines.append("| 進場日 | 離場日 | 進場價 | 離場價 | 損益% | 崩盤 | 避開% | 機會成本% | 買回機會 |")
            lines.append("|--------|--------|--------|--------|-------|------|-------|-----------|----------|")
            for t in simulation.trades:
                crashed = "✅" if t.crashed else "—"
                avoided = f"{t.avoided_pct:.2f}" if t.crashed else "—"
                missed = f"{t.missed_pct:.2f}" if not t.crashed else "—"
                buyback = "✅" if t.can_buyback_lower else "❌"
                lines.append(f"| {t.entry_date} | {t.exit_date} | {t.entry_price:.1f} | "
                            f"{t.exit_price:.1f} | {t.pnl_pct:+.2f}% | {crashed} | "
                            f"{avoided} | {missed} | {buyback} |")
            lines.append("")

    return "\n".join(lines)


def save_markdown_report(content: str, filepath: str) -> None:
    """儲存 Markdown 報告到檔案"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"📄 Markdown 報告已儲存: {filepath}")