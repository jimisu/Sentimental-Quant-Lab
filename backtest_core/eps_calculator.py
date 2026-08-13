"""
EPS Calculator Module
=====================
EPS 時間線建構與本益比計算工具。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass


@dataclass
class QuarterlyEPS:
    """季度 EPS 資料"""
    quarter_end: str          # 季底日 YYYY-MM-DD
    report_date: str          # 可得日（季底 + 時滯）YYYY-MM-DD
    year: int
    quarter: int              # 1-4
    eps: float


@dataclass
class EPSTimeline:
    """
    EPS 時間線管理器

    從 FinMind 寬表財報資料建構 EPS 時間線，
    支援 as-of 日期查詢近四季 EPS。
    """

    eps_known: List[QuarterlyEPS]  # 已知 EPS 列表，按 report_date 排序
    report_lag_days: int = 50      # 財報發布時滯（天）

    @classmethod
    def from_wide_financial(
        cls,
        wide_fin_data: List[Dict[str, Any]],
        report_lag_days: int = 50
    ) -> "EPSTimeline":
        """
        從 FinMind 寬表財報資料建構 EPS 時間線

        Args:
            wide_fin_data: FinMind TaiwanStockFinancialStatements 寬表資料
            report_lag_days: 季報視為「可得」的發布時滯（季底 + N 日）

        Returns:
            EPSTimeline 實例
        """
        eps_by_qend: Dict[str, float] = {}
        for r in wide_fin_data:
            if r.get("type") == "EPS" and r.get("value") is not None:
                eps_by_qend[r["date"]] = float(r["value"])

        eps_known: List[QuarterlyEPS] = []
        for qend, eps in sorted(eps_by_qend.items()):
            qe = datetime.strptime(qend, "%Y-%m-%d")
            report = (qe + timedelta(days=report_lag_days)).strftime("%Y-%m-%d")
            year, month = qe.year, qe.month
            quarter = {3: 1, 6: 2, 9: 3, 12: 4}[month]
            eps_known.append(QuarterlyEPS(
                quarter_end=qend,
                report_date=report,
                year=year,
                quarter=quarter,
                eps=eps
            ))
        eps_known.sort(key=lambda x: x.report_date)

        return cls(eps_known=eps_known, report_lag_days=report_lag_days)

    @classmethod
    def from_cache_file(
        cls,
        cache_path: str,
        report_lag_days: int = 50
    ) -> "EPSTimeline":
        """從快取檔案載入"""
        with open(cache_path) as f:
            data = json.load(f)["data"]
        return cls.from_wide_financial(data, report_lag_days)

    def get_eps_asof(self, asof: str) -> Dict[Tuple[int, int], Dict[str, float]]:
        """
        取得截至 asof 可得的近四季 EPS

        Args:
            asof: 查詢基準日 YYYY-MM-DD

        Returns:
            {(year, quarter): {"eps": value}} 最多 4 季
        """
        known = [
            (e.year, e.quarter, e.eps)
            for e in self.eps_known
            if e.report_date <= asof
        ]
        return {(y, q): {"eps": e} for (y, q, e) in known[-4:]}


def compute_trailing_pe(
    close_price: float,
    eps_asof: Dict[Tuple[int, int], Dict[str, float]]
) -> float:
    """
    計算本益比（Trailing P/E）

    Args:
        close_price: 收盤價
        eps_asof: eps_asof() 回傳的字典 {(year, quarter): {"eps": v}}

    Returns:
        P/E 比率，若 EPS 合計 <= 0 則回傳 0
    """
    ttm_eps = sum(v["eps"] for v in eps_asof.values())
    if ttm_eps > 0:
        return close_price / ttm_eps
    return 0.0


def build_price_lookup(ohlc_data: List[Dict]) -> Dict[str, float]:
    """建構收盤價查表 {date: close}"""
    return {r["date"]: float(r["close"]) for r in ohlc_data}


def build_shareholding_lookup(shareholding_data: List[Dict]) -> Dict[str, Dict]:
    """建構外資持股查表 {date: record}"""
    return {r["date"]: r for r in shareholding_data}


def get_foreign_shares_asof(
    shareholding_data: List[Dict],
    asof: str,
    fallback_float_shares: Optional[float] = None
) -> Optional[float]:
    """
    取得截至 asof 的最新外資持股（張）

    Args:
        shareholding_data: 外資持股原始資料
        asof: 查詢基準日
        fallback_float_shares: 找不到時的備用值（流通股/張）

    Returns:
        外資持股張數，找不到且無備用值則回傳 None
    """
    candidates = [r for r in shareholding_data if r["date"] <= asof]
    if not candidates:
        return fallback_float_shares
    latest = max(candidates, key=lambda r: r["date"])
    shares = latest.get("foreign_shares")
    if shares is None or shares <= 0:
        return fallback_float_shares
    return float(shares)


def build_price_dataframe_asof(
    ohlc_data: List[Dict],
    asof: str
) -> "pd.DataFrame":
    """
    建構截至 asof 的價格 DataFrame（相容 signal_engine 介面）

    Returns:
        columns: ["date", "台積電收盤價"]
    """
    import pandas as pd
    rows = [
        {"date": r["date"], "台積電收盤價": float(r["close"])}
        for r in ohlc_data if r["date"] <= asof
    ]
    return pd.DataFrame(rows)