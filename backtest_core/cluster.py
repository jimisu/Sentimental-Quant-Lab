"""
Cluster Module
==============
觸發日群集化工具。

將連續或相近的觸發日群集化，避免重複計算。
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class TriggerCluster:
    """觸發群集"""
    start_date: str
    end_date: str
    trigger_dates: List[str]
    rep_date: str              # 代表日（群集中間的日期）
    rep_close: float           # 代表日收盤價
    rep_data: Dict[str, Any]   # 代表日完整資料
    duration: int              # 群集持續天數


def cluster_triggers(
    daily_results: List[Dict[str, Any]],
    trigger_key: str = "triggered",
    max_gap_days: int = 3,
    data_key: str = "li_opt",
) -> List[TriggerCluster]:
    """
    將每日觸發結果群集化

    Args:
        daily_results: 每日分析結果列表，需包含 'date'、'close' 與觸發標記
        trigger_key: 觸發標記的鍵名（如 'triggered'、'li_opt.triggered'）
        max_gap_days: 群集最大間隔交易日數
        data_key: 代表日資料的鍵名

    Returns:
        TriggerCluster 列表
    """
    if not daily_results:
        return []

    # 提取觸發日
    triggered = [r for r in daily_results if _get_trigger_value(r, trigger_key)]
    if not triggered:
        return []

    all_dates = [r["date"] for r in daily_results]
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    clusters_raw: List[List[Dict]] = []
    current = [triggered[0]]

    for i in range(1, len(triggered)):
        prev_date = current[-1]["date"]
        curr_date = triggered[i]["date"]

        # 計算交易日間隔
        try:
            gap = date_to_idx[curr_date] - date_to_idx[prev_date] - 1
        except KeyError:
            gap = max_gap_days + 1

        if gap <= max_gap_days:
            current.append(triggered[i])
        else:
            clusters_raw.append(current)
            current = [triggered[i]]

    clusters_raw.append(current)

    # 建構 TriggerCluster 物件
    clusters: List[TriggerCluster] = []
    for cl in clusters_raw:
        start = cl[0]["date"]
        end = cl[-1]["date"]
        rep = cl[len(cl) // 2]

        # 取得代表日收盤價
        rep_close = rep.get("close", 0.0)

        # 代表日完整資料
        rep_data = rep.get(data_key, rep) if data_key in rep else rep

        clusters.append(TriggerCluster(
            start_date=start,
            end_date=end,
            trigger_dates=[c["date"] for c in cl],
            rep_date=rep["date"],
            rep_close=rep_close,
            rep_data=rep_data,
            duration=len(cl),
        ))

    return clusters


def _get_trigger_value(record: Dict[str, Any], key: str) -> bool:
    """從記錄中取得觸發值，支援巢狀鍵（如 'li_opt.triggered'）。"""
    if "." in key:
        parts = key.split(".")
        val = record
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part)
            elif hasattr(val, part):
                val = getattr(val, part)
            else:
                return False
        return bool(val)
    return bool(record.get(key, False))


def print_clusters(clusters: List[TriggerCluster], label: str = "") -> None:
    """列印群集摘要"""
    prefix = f"[{label}] " if label else ""
    for cl in clusters:
        print(f"  {prefix}群集: {cl.start_date} ~ {cl.end_date} "
              f"({cl.duration}日) | 代表日: {cl.rep_date} 收盤 {cl.rep_close:.1f}")


def get_cluster_summary(clusters: List[TriggerCluster]) -> Dict[str, Any]:
    """取得群集統計摘要"""
    if not clusters:
        return {
            "total_clusters": 0,
            "total_trigger_days": 0,
            "avg_duration": 0.0,
            "max_duration": 0,
            "date_range": None,
        }

    total_days = sum(c.duration for c in clusters)
    return {
        "total_clusters": len(clusters),
        "total_trigger_days": total_days,
        "avg_duration": total_days / len(clusters),
        "max_duration": max(c.duration for c in clusters),
        "date_range": (clusters[0].start_date, clusters[-1].end_date),
    }
