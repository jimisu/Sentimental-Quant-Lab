"""
Buyback Analyzer Module
=======================
觸發群集後買回機會分析：觀察觸發後 N 個交易日內是否有更低價格買回機會。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class BuybackResult:
    """單一群集買回分析結果"""
    cluster_start: str
    cluster_end: str
    entry_date: str
    entry_price: float
    window_days: int
    min_price: Optional[float]
    min_date: Optional[str]
    min_rank: Optional[int]        # 第幾個交易日出現最低價
    max_price: Optional[float]
    buyback_possible: bool         # 是否有低於買出價的買回機會
    max_drawdown_pct: float        # 最大回檔幅度
    recovered_above_entry: bool    # 期間內是否曾回升超過觸發價

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_start": self.cluster_start,
            "cluster_end": self.cluster_end,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "window_days": self.window_days,
            "min_price": self.min_price,
            "min_date": self.min_date,
            "min_rank": self.min_rank,
            "max_price": self.max_price,
            "buyback_possible": self.buyback_possible,
            "max_drawdown_pct": self.max_drawdown_pct,
            "recovered_above_entry": self.recovered_above_entry,
        }


@dataclass
class BuybackSummary:
    """買回分析彙總"""
    total_clusters: int = 0
    buyback_successful: int = 0
    buyback_success_rate: float = 0.0
    avg_max_drawdown_pct: float = 0.0
    avg_min_rank_day: float = 0.0
    recovered_above_entry_count: int = 0
    recovered_rate: float = 0.0
    details: List[BuybackResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "total_clusters": self.total_clusters,
                "buyback_successful": self.buyback_successful,
                "buyback_success_rate": self.buyback_success_rate,
                "avg_max_drawdown_pct": self.avg_max_drawdown_pct,
                "avg_min_rank_day": self.avg_min_rank_day,
                "recovered_above_entry_count": self.recovered_above_entry_count,
                "recovered_rate": self.recovered_rate,
            },
            "details": [d.to_dict() for d in self.details],
        }


class BuybackAnalyzer:
    """
    買回機會分析器

    分析每個觸發群集結束後 N 個交易日內：
    - 最低價是否低於觸發日收盤價
    - 最低價出現於第幾個交易日
    - 期間最高價是否超過觸發日收盤價（是否有回升機會）
    - 平均最大回檔幅度
    """

    def __init__(self, buyback_window: int = 20):
        """
        Args:
            buyback_window: 觀察窗口（交易日數）
        """
        self.buyback_window = buyback_window

    def analyze(
        self,
        clusters: List[Dict[str, Any]],
        all_trading_days: List[str],
        close_prices: Dict[str, float],
    ) -> BuybackSummary:
        """
        執行買回分析

        Args:
            clusters: 群集列表，每項含 end_date, rep_close
            all_trading_days: 所有交易日列表
            close_prices: 收盤價查表 {date: close}

        Returns:
            BuybackSummary
        """
        results: List[BuybackResult] = []

        for cl in clusters:
            try:
                end_idx = all_trading_days.index(cl["end_date"])
            except ValueError:
                continue

            entry_date = cl["end_date"]
            entry_price = cl.get("rep_close", close_prices.get(entry_date, 0))

            if entry_price <= 0:
                results.append(BuybackResult(
                    cluster_start=cl["start_date"],
                    cluster_end=cl["end_date"],
                    entry_date=entry_date,
                    entry_price=entry_price,
                    window_days=0,
                    min_price=None,
                    min_date=None,
                    min_rank=None,
                    max_price=None,
                    buyback_possible=False,
                    max_drawdown_pct=0.0,
                    recovered_above_entry=False,
                ))
                continue

            # 觀察窗口：後續 buyback_window 個交易日
            window_end_idx = min(end_idx + self.buyback_window, len(all_trading_days) - 1)
            window_days = all_trading_days[end_idx + 1:window_end_idx + 1]

            if not window_days:
                results.append(BuybackResult(
                    cluster_start=cl["start_date"],
                    cluster_end=cl["end_date"],
                    entry_date=entry_date,
                    entry_price=entry_price,
                    window_days=0,
                    min_price=None,
                    min_date=None,
                    min_rank=None,
                    max_price=None,
                    buyback_possible=False,
                    max_drawdown_pct=0.0,
                    recovered_above_entry=False,
                ))
                continue

            window_prices = [close_prices[d] for d in window_days if d in close_prices]

            if not window_prices:
                results.append(BuybackResult(
                    cluster_start=cl["start_date"],
                    cluster_end=cl["end_date"],
                    entry_date=entry_date,
                    entry_price=entry_price,
                    window_days=len(window_days),
                    min_price=None,
                    min_date=None,
                    min_rank=None,
                    max_price=None,
                    buyback_possible=False,
                    max_drawdown_pct=0.0,
                    recovered_above_entry=False,
                ))
                continue

            min_price = min(window_prices)
            min_date = window_days[window_prices.index(min_price)]
            min_rank = window_prices.index(min_price) + 1  # 1-based
            max_price = max(window_prices)

            buyback_possible = min_price < entry_price
            max_drawdown_pct = (entry_price - min_price) / entry_price * 100 if entry_price > 0 else 0
            recovered_above_entry = max_price > entry_price

            results.append(BuybackResult(
                cluster_start=cl["start_date"],
                cluster_end=cl["end_date"],
                entry_date=entry_date,
                entry_price=entry_price,
                window_days=len(window_days),
                min_price=min_price,
                min_date=min_date,
                min_rank=min_rank,
                max_price=max_price,
                buyback_possible=buyback_possible,
                max_drawdown_pct=max_drawdown_pct,
                recovered_above_entry=recovered_above_entry,
            ))

        # 彙總統計
        total = len(results)
        successful = sum(1 for r in results if r.buyback_possible)
        success_rate = successful / total if total > 0 else 0

        avg_drawdown = sum(r.max_drawdown_pct for r in results) / total if total > 0 else 0
        avg_min_rank = (
            sum(r.min_rank for r in results if r.min_rank) / successful
            if successful > 0 else 0
        )
        recovered_count = sum(1 for r in results if r.recovered_above_entry)
        recovered_rate = recovered_count / total if total > 0 else 0

        return BuybackSummary(
            total_clusters=total,
            buyback_successful=successful,
            buyback_success_rate=success_rate,
            avg_max_drawdown_pct=avg_drawdown,
            avg_min_rank_day=avg_min_rank,
            recovered_above_entry_count=recovered_count,
            recovered_rate=recovered_rate,
            details=results,
        )


def analyze_buyback_opportunity(
    clusters: List[Dict[str, Any]],
    all_trading_days: List[str],
    close_prices: Dict[str, float],
    buyback_window: int = 20,
) -> BuybackSummary:
    """便利函數：分析買回機會"""
    analyzer = BuybackAnalyzer(buyback_window=buyback_window)
    return analyzer.analyze(clusters, all_trading_days, close_prices)


def print_buyback_analysis(buyback: BuybackSummary, window: int = 20) -> None:
    """列印買回分析結果"""
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