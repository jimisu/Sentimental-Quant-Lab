"""
Evaluator Module
================
回測預警效果評估器。

計算 Precision, Recall, F1 等指標，支援 TP/FP/FN 明細。
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class EvaluationDetail:
    """評估明細項目"""
    cluster: Dict[str, Any]
    crash_date: str
    crash_return: float
    lead_days: int = 0
    max_drop_in_window: float = 0.0
    nearest_cluster_end: Optional[str] = None


@dataclass
class EvaluationResult:
    """評估結果"""
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    total_crashes: int = 0
    total_clusters: int = 0

    tp_details: List[EvaluationDetail] = field(default_factory=list)
    fp_details: List[EvaluationDetail] = field(default_factory=list)
    fn_details: List[EvaluationDetail] = field(default_factory=list)


class BacktestEvaluator:
    """
    回測評估器

    評估觸發群集對崩盤的預警效果：
    - TP: 群集結束後 warning_window 內發生崩盤
    - FP: 群集結束後 warning_window 內未發生崩盤
    - FN: 崩盤前無群集預警
    """

    def __init__(
        self,
        crash_threshold: float = -5.0,
        warning_window: int = 10,
    ):
        """
        初始化評估器

        Args:
            crash_threshold: 崩盤門檻（日報酬率 <= 此值視為崩盤）
            warning_window: 預警窗口（群集結束後 N 個交易日內）
        """
        self.crash_threshold = crash_threshold
        self.warning_window = warning_window

    def evaluate(
        self,
        clusters: List[Dict[str, Any]],
        crash_dates: List[Tuple[str, float]],
        all_trading_days: List[str],
        daily_returns: Dict[str, float],
    ) -> EvaluationResult:
        """
        執行評估

        Args:
            clusters: 群集列表，每項需含 'end_date'
            crash_dates: 崩盤日期列表 [(date, return_pct), ...]
            all_trading_days: 所有交易日列表（時間順序）
            daily_returns: 每日報酬率 {date: return_pct}

        Returns:
            EvaluationResult
        """
        result = EvaluationResult()
        crash_set = {d for d, _ in crash_dates}
        result.total_crashes = len(crash_dates)
        result.total_clusters = len(clusters)

        # 建立日期索引
        date_to_idx = {d: i for i, d in enumerate(all_trading_days)}

        # --- TP / FN: 對每個崩盤，找是否有群集預警 ---
        for crash_date, crash_ret in crash_dates:
            try:
                cidx = date_to_idx[crash_date]
            except KeyError:
                continue

            found = False
            for cl in clusters:
                try:
                    end_idx = date_to_idx[cl["end_date"]]
                except KeyError:
                    continue

                if end_idx >= cidx:
                    continue  # 群集在崩盤日之後，不算預警

                if cidx - end_idx <= self.warning_window:
                    # TP: 群集在預警窗口內
                    result.tp += 1
                    result.tp_details.append(EvaluationDetail(
                        cluster=cl,
                        crash_date=crash_date,
                        crash_return=crash_ret,
                        lead_days=cidx - end_idx,
                    ))
                    found = True
                    break

            if not found:
                # FN: 崩盤前無預警群集
                result.fn += 1
                # 找最近的前一群集
                nearest = None
                for cl in reversed(clusters):
                    try:
                        if date_to_idx[cl["end_date"]] < cidx:
                            nearest = cl["end_date"]
                            break
                    except KeyError:
                        continue

                result.fn_details.append(EvaluationDetail(
                    cluster={},
                    crash_date=crash_date,
                    crash_return=crash_ret,
                    nearest_cluster_end=nearest,
                ))

        # --- FP: 對每個群集，檢查預警窗口內是否有崩盤 ---
        for cl in clusters:
            try:
                end_idx = date_to_idx[cl["end_date"]]
            except KeyError:
                continue

            future = all_trading_days[end_idx + 1:end_idx + 1 + self.warning_window]
            has_crash = any(d in crash_set for d in future)

            if not has_crash:
                result.fp += 1
                max_drop = 0.0
                if future:
                    max_drop = min(daily_returns.get(d, 0) for d in future)
                result.fp_details.append(EvaluationDetail(
                    cluster=cl,
                    crash_date="",
                    crash_return=0.0,
                    max_drop_in_window=max_drop,
                ))

        # --- 計算指標 ---
        result.precision = result.tp / (result.tp + result.fp) if (result.tp + result.fp) > 0 else 0.0
        result.recall = result.tp / (result.tp + result.fn) if (result.tp + result.fn) > 0 else 0.0
        if result.precision + result.recall > 0:
            result.f1 = 2 * result.precision * result.recall / (result.precision + result.recall)

        return result


def evaluate_clusters(
    clusters: List[Dict[str, Any]],
    crash_dates: List[Tuple[str, float]],
    all_trading_days: List[str],
    daily_returns: Dict[str, float],
    crash_threshold: float = -5.0,
    warning_window: int = 10,
) -> EvaluationResult:
    """便利函數：直接評估"""
    evaluator = BacktestEvaluator(crash_threshold, warning_window)
    return evaluator.evaluate(clusters, crash_dates, all_trading_days, daily_returns)


def print_evaluation(result: EvaluationResult, label: str = "") -> None:
    """列印評估結果"""
    prefix = f" {label}" if label else ""
    print(f"\n{'='*70}")
    print(f"📊{prefix}崩盤預警評估")
    print(f"{'='*70}")
    print(f"崩盤門檻: ≤ {result.tp_details[0].crash_return if result.tp_details else 'N/A'}%  "
          f"| 預警窗口: {result.warning_window if hasattr(result, 'warning_window') else 'N/A'} 日")
    print(f"崩盤總數: {result.total_crashes} | 觸發群集: {result.total_clusters}")
    print(f"TP: {result.tp} | FP: {result.fp} | FN: {result.fn}")
    print(f"Precision: {result.precision:.1%} | Recall: {result.recall:.1%} | F1: {result.f1:.1%}")
    print("-"*70)

    for d in result.tp_details:
        cl = d.cluster
        print(f"  ✅ 群集 {cl['start_date']}~{cl['end_date']} → "
              f"{d.lead_days}日後崩盤 {d.crash_date} ({d.crash_return:+.2f}%)")

    for d in result.fn_details:
        near = f" (最近群集結束: {d.nearest_cluster_end})" if d.nearest_cluster_end else " (前無群集)"
        print(f"  ❌ 崩盤 {d.crash_date} ({d.crash_return:+.2f}%){near}")

    for d in result.fp_details[:10]:
        cl = d.cluster
        print(f"  ⚠️ 群集 {cl['start_date']}~{cl['end_date']} → "
              f"未來窗口最大跌幅 {d.max_drop_in_window:+.2f}%")

    if len(result.fp_details) > 10:
        print(f"  ... 及其他 {len(result.fp_details) - 10} 群")