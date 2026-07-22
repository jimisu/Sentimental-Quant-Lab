"""
Technical Indicators & Daily Returns
====================================
共用的技術指標計算工具。

從四個回測腳本中提取的共通邏輯：
- 日報酬率計算
- 近 N 日最大單日跌幅
- 價格資料框建構
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class PriceDataFrame:
    """標準化價格資料框容器"""
    df: pd.DataFrame  # columns: ["date", "台積電收盤價"]

    @classmethod
    def from_ohlc(cls, ohlc_data: List[Dict], asof: str) -> "PriceDataFrame":
        """
        從 OHLC 原始資料建構截至 asof 的價格資料框

        Args:
            ohlc_data: OHLCV 原始資料列表
            asof: 截止日期 YYYY-MM-DD

        Returns:
            PriceDataFrame 實例
        """
        rows = [
            {"date": r["date"], "台積電收盤價": float(r["close"])}
            for r in ohlc_data
            if r["date"] <= asof
        ]
        return cls(pd.DataFrame(rows))

    def get_recent_closes(self, n: int = 5) -> pd.Series:
        """取得最近 N 日收盤價"""
        return self.df["台積電收盤價"].dropna().tail(n)

    def get_max_single_day_drop_pct(self, window: int = 5) -> float:
        """
        計算近 N 個交易日最大單日跌幅百分比

        Args:
            window: 觀察窗口天數

        Returns:
            最大跌幅百分比（正數，如 5.2 表示最大跌幅 5.2%）
        """
        recent = self.get_recent_closes(window)
        if len(recent) < 2:
            return 0.0
        pct_changes = recent.pct_change().dropna()
        max_drop = abs(pct_changes.min()) * 100
        return max_drop if max_drop > 0 else 0.0


def compute_daily_returns(close_prices: Dict[str, float]) -> Dict[str, float]:
    """
    計算每日報酬率

    Args:
        close_prices: {date_str: close_price} 收盤價字典

    Returns:
        {date_str: return_pct} 每日報酬率字典（百分比，如 -2.5 表示 -2.5%）
    """
    dates = sorted(close_prices.keys())
    returns = {}
    for i in range(1, len(dates)):
        prev = close_prices[dates[i - 1]]
        cur = close_prices[dates[i]]
        if prev > 0:
            returns[dates[i]] = (cur - prev) / prev * 100
    return returns


def build_price_lookup(ohlc_data: List[Dict]) -> Dict[str, float]:
    """建構日期 -> 收盤價查找表"""
    return {r["date"]: float(r["close"]) for r in ohlc_data}


def build_foreign_share_lookup(shareholding_data: List[Dict]) -> Dict[str, Dict]:
    """建構日期 -> 外資持股記錄查找表"""
    return {r["date"]: r for r in shareholding_data}


def get_foreign_shares_asof(
    shareholding_data: List[Dict],
    asof: str,
    fallback_float_shares: float = 25930380.0  # 台積電流通股(張) 預設值
) -> Optional[float]:
    """
    取得截至 asof 日期的最新外資持股數（張）

    Args:
        shareholding_data: 外資持股原始資料
        asof: 判斷基準日
        fallback_float_shares: 找不到資料時的備用值（流通股/張）

    Returns:
        外資持股張數，找不到則回傳 None
    """
    candidates = [r for r in shareholding_data if r["date"] <= asof]
    if not candidates:
        return None
    latest = max(candidates, key=lambda r: r["date"])
    shares = latest.get("foreign_shares")
    if shares is None or shares <= 0:
        return fallback_float_shares
    return float(shares)


def get_price_dataframe_asof(
    ohlc_data: List[Dict],
    asof: str
) -> pd.DataFrame:
    """
    建構截至 asof 的價格 DataFrame（相容舊版介面）

    Returns:
        columns: ["date", "台積電收盤價"]
    """
    rows = [
        {"date": r["date"], "台積電收盤價": float(r["close"])}
        for r in ohlc_data if r["date"] <= asof
    ]
    return pd.DataFrame(rows)


@dataclass
class TechnicalSnapshot:
    """單日技術面快照"""
    date: str
    close: float
    max_drop_5d: float
    daily_return: Optional[float] = None


def build_technical_snapshots(
    ohlc_data: List[Dict],
    daily_returns: Dict[str, float],
    lookback_window: int = 5
) -> List[TechnicalSnapshot]:
    """批次建構技術面快照列表"""
    close_lookup = build_price_lookup(ohlc_data)
    dates = sorted(close_lookup.keys())
    snapshots = []
    for d in dates:
        # 取近 lookback_window 日收盤價計算最大跌幅
        idx = dates.index(d)
        start_idx = max(0, idx - lookback_window + 1)
        window_closes = [close_lookup[dates[i]] for i in range(start_idx, idx + 1)]
        if len(window_closes) >= 2:
            import numpy as np
            pct_changes = np.diff(window_closes) / window_closes[:-1] * 100
            max_drop = abs(min(pct_changes)) if len(pct_changes) > 0 else 0.0
        else:
            max_drop = 0.0

        snapshots.append(TechnicalSnapshot(
            date=d,
            close=close_lookup[d],
            max_drop_5d=max_drop,
            daily_return=daily_returns.get(d)
        ))
    return snapshots