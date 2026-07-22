"""
Simulator Module
================
策略模擬器：基於觸發群集模擬買賣策略，計算避開跌幅、機會成本、淨收益。
支援買回機會分析。
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class SimulatedTrade:
    """模擬交易記錄"""
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    crashed: bool              # 期間內是否發生崩盤
    crash_return: float = 0.0  # 崩盤單日跌幅
    avoided_pct: float = 0.0   # 避開的跌幅
    missed_pct: float = 0.0    # 錯失的漲幅（機會成本）
    # 買回分析
    can_buyback_lower: bool = False
    buyback_drawdown_pct: float = 0.0


@dataclass
class SimulationResult:
    """模擬結果"""
    total_avoided: float = 0.0      # 總避開跌幅
    total_missed: float = 0.0       # 總機會成本
    net_pnl: float = 0.0            # 淨收益
    trades: List[SimulatedTrade] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_avoided": self.total_avoided,
            "total_missed": self.total_missed,
            "net_pnl": self.net_pnl,
            "trade_count": len(self.trades),
            "trades": [
                {
                    "entry": t.entry_date,
                    "exit": t.exit_date,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl_pct": t.pnl_pct,
                    "crashed": t.crashed,
                    "crash_return": t.crash_return,
                    "avoided": t.avoided_pct,
                    "missed": t.missed_pct,
                    "can_buyback_lower": t.can_buyback_lower,
                    "buyback_drawdown": t.buyback_drawdown_pct,
                }
                for t in self.trades
            ],
        }


class StrategySimulator:
    """
    策略模擬器

    模擬邏輯：
    1. 每個群集結束日作為「賣出/避險」點
    2. 持有 warning_window 天或直到下一群集開始
    3. 計算期間損益、避開崩盤、機會成本
    4. 可選：離場後 buyback_window 內是否有更低價買回
    """

    def __init__(
        self,
        warning_window: int = 10,
        cooldown_days: int = 5,
        buyback_window: int = 20,
        crash_threshold: float = -5.0,
    ):
        """
        初始化模擬器

        Args:
            warning_window: 預警持有天數
            cooldown_days: 交易冷卻期（避免頻繁進出）
            buyback_window: 離場後觀察買回機會的天數
            crash_threshold: 崩盤門檻
        """
        self.warning_window = warning_window
        self.cooldown_days = cooldown_days
        self.buyback_window = buyback_window
        self.crash_threshold = crash_threshold

    def simulate(
        self,
        clusters: List[Dict[str, Any]],
        crash_dates: List[Tuple[str, float]],
        all_trading_days: List[str],
        close_prices: Dict[str, float],
        daily_returns: Dict[str, float],
    ) -> SimulationResult:
        """
        執行模擬

        Args:
            clusters: 群集列表
            crash_dates: 崩盤日列表
            all_trading_days: 所有交易日
            close_prices: 收盤價查表 {date: close}
            daily_returns: 每日報酬 {date: return_pct}

        Returns:
            SimulationResult
        """
        crash_set = {d for d, _ in crash_dates}
        result = SimulationResult()
        last_end_idx = -self.cooldown_days - 1

        for cl in clusters:
            try:
                end_idx = all_trading_days.index(cl["end_date"])
            except ValueError:
                continue

            # 冷卻期檢查
            if end_idx - last_end_idx <= self.cooldown_days:
                continue

            entry_date = cl["end_date"]
            entry_price = close_prices.get(entry_date, 0)
            if entry_price <= 0:
                continue

            # 離場日：warning_window 後，或下一群集開始前
            exit_idx = min(end_idx + self.warning_window, len(all_trading_days) - 1)

            # 找下一群集開始日作為上限
            for next_cl in clusters:
                try:
                    ns = all_trading_days.index(next_cl["start_date"])
                    if ns > end_idx:
                        exit_idx = min(exit_idx, ns - 1)
                        break
                except ValueError:
                    continue

            exit_date = all_trading_days[exit_idx]
            exit_price = close_prices.get(exit_date, entry_price)

            # 期間報酬
            pnl = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0

            # 是否期間內有崩盤
            period = all_trading_days[end_idx + 1:exit_idx + 1]
            crashed = any(d in crash_set for d in period)
            crash_ret = 0.0
            if crashed:
                crash_day = next(d for d in period if d in crash_set)
                crash_ret = daily_returns.get(crash_day, 0)

            # 避開跌幅 / 機會成本
            avoided = abs(crash_ret) if crashed else 0
            missed = max(0, pnl) if not crashed else 0

            # 買回分析：離場後 buyback_window 內是否有更低價
            buyback_start = exit_idx + 1
            buyback_end = min(buyback_start + self.buyback_window, len(all_trading_days) - 1)
            buyback_days = all_trading_days[buyback_start:buyback_end + 1]
            buyback_prices = [close_prices[d] for d in buyback_days if d in close_prices]

            can_buyback = False
            buyback_dd = 0.0
            if buyback_prices:
                min_buyback = min(buyback_prices)
                if min_buyback < exit_price:
                    can_buyback = True
                    buyback_dd = (exit_price - min_buyback) / exit_price * 100

            trade = SimulatedTrade(
                entry_date=entry_date,
                exit_date=exit_date,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl_pct=pnl,
                crashed=crashed,
                crash_return=crash_ret,
                avoided_pct=avoided,
                missed_pct=missed,
                can_buyback_lower=can_buyback,
                buyback_drawdown_pct=buyback_dd,
            )

            result.trades.append(trade)
            result.total_avoided += avoided
            result.total_missed += missed
            last_end_idx = exit_idx

        result.net_pnl = result.total_avoided - result.total_missed
        return result


def simulate_strategy(
    clusters: List[Dict[str, Any]],
    crash_dates: List[Tuple[str, float]],
    all_trading_days: List[str],
    close_prices: Dict[str, float],
    daily_returns: Dict[str, float],
    warning_window: int = 10,
    cooldown_days: int = 5,
    buyback_window: int = 20,
    crash_threshold: float = -5.0,
) -> SimulationResult:
    """便利函數：執行策略模擬"""
    sim = StrategySimulator(
        warning_window=warning_window,
        cooldown_days=cooldown_days,
        buyback_window=buyback_window,
        crash_threshold=crash_threshold,
    )
    return sim.simulate(clusters, crash_dates, all_trading_days, close_prices, daily_returns)


def print_simulation(result: SimulationResult, label: str = "") -> None:
    """列印模擬結果"""
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