"""
Signal Analyzer Module
======================
領先指標分析器與崩盤訊號分析器。
統一封裝 signal_engine 的計算邏輯，提供回測專用介面。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import pandas as pd

from signal_engine import (
    compute_leading_indicator,
    compute_trailing_pe,
    LeadingIndicator,
    SignalEngine,
    CONFIG,
    _foreign_daily_net,
    _two_month_window,
)
from .eps_calculator import EPSTimeline, compute_trailing_pe as compute_pe
from .technical_indicators import (
    build_price_lookup,
    get_foreign_shares_asof,
    get_price_dataframe_asof,
)


@dataclass
class LeadingIndicatorConfig:
    """領先指標參數設定"""
    pe_threshold: float = 30.0           # P/E 門檻
    sell_pct_threshold: float = 0.01     # 外資賣超佔比門檻 (1%)
    max_drop_pct: float = 5.0            # 近5日最大跌幅門檻
    window_days: int = 60                # 觀察窗口天數
    use_foreign_holdings_as_denom: bool = True  # 分母用外資持股而非流通股


class LeadingIndicatorAnalyzer:
    """
    領先指標分析器

    封裝 signal_engine.compute_leading_indicator，
    提供回測專用的批次計算與參數覆寫功能。
    """

    def __init__(
        self,
        config: Optional[LeadingIndicatorConfig] = None,
        eps_timeline: Optional[EPSTimeline] = None,
        inst_rows: Optional[List[Dict]] = None,
        shareholding_data: Optional[List[Dict]] = None,
        ohlc_data: Optional[List[Dict]] = None,
    ):
        """
        初始化分析器

        Args:
            config: 領先指標參數設定
            eps_timeline: EPS 時間線（用於計算 P/E）
            inst_rows: 三大法人買賣超原始資料
            shareholding_data: 外資持股原始資料
            ohlc_data: OHLCV 原始資料
        """
        self.config = config or LeadingIndicatorConfig()
        self.eps_timeline = eps_timeline
        self.inst_rows = inst_rows or []
        self.shareholding_data = shareholding_data or []
        self.ohlc_data = ohlc_data or []

        # 建構查表
        self.close_lookup = build_price_lookup(self.ohlc_data)
        self.shareholding_lookup = {r["date"]: r for r in self.shareholding_data}

    def compute_for_date(self, asof: str) -> LeadingIndicator:
        """
        計算單一日期的領先指標

        Args:
            asof: 計算基準日 YYYY-MM-DD

        Returns:
            LeadingIndicator 結果物件
        """
        # 籌碼資料：截至 asof
        chip_data = [r for r in self.inst_rows if r["date"] <= asof]

        # 外資持股（分母）
        foreign_shares = get_foreign_shares_asof(
            self.shareholding_data,
            asof,
            fallback_float_shares=CONFIG.chip.tsmc_float_shares
        )

        # 收盤價
        close = self.close_lookup.get(asof, 0.0)

        # P/E
        eps_asof = self.eps_timeline.get_eps_asof(asof) if self.eps_timeline else {}
        pe = compute_pe(close, eps_asof)

        # 價格 DataFrame
        price_df = get_price_dataframe_asof(self.ohlc_data, asof)

        # 呼叫 signal_engine 核心計算
        return compute_leading_indicator(chip_data, foreign_shares, pe, price_df=price_df)

    def compute_optimized_for_date(self, asof: str) -> LeadingIndicator:
        """
        計算優化版領先指標（PE 門檻可調、分母固定用外資持股）

        此為 leading_indicator_crash_avoidance_backtest.py 的優化版邏輯
        """
        from signal_engine import LeadingIndicator

        chip_data = [r for r in self.inst_rows if r["date"] <= asof]
        foreign_shares = get_foreign_shares_asof(
            self.shareholding_data,
            asof,
            fallback_float_shares=CONFIG.chip.tsmc_float_shares
        )
        close = self.close_lookup.get(asof, 0.0)
        eps_asof = self.eps_timeline.get_eps_asof(asof) if self.eps_timeline else {}
        pe = compute_pe(close, eps_asof)
        price_df = get_price_dataframe_asof(self.ohlc_data, asof)

        # 參數
        pct_threshold = self.config.sell_pct_threshold
        pe_threshold = self.config.pe_threshold
        window_days = self.config.window_days
        denom = foreign_shares if (foreign_shares and foreign_shares > 0) else CONFIG.chip.tsmc_float_shares
        denom_label = "外資持股" if (foreign_shares and foreign_shares > 0) else "流通股"

        result = LeadingIndicator(
            pct_threshold=pct_threshold,
            pe_threshold=pe_threshold,
            window_days=window_days,
            foreign_holdings=denom,
            denom_label=denom_label,
            pe_ratio=pe,
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

        # 條件 3：近 5 日無單日大跌 > max_drop_pct
        no_crash = True
        max_drop = 0.0
        if price_df is not None and not price_df.empty and "台積電收盤價" in price_df.columns:
            recent = price_df["台積電收盤價"].dropna().tail(5)
            if len(recent) >= 2:
                pct_changes = recent.pct_change().dropna()
                max_drop = abs(pct_changes.min()) * 100
                no_crash = max_drop <= self.config.max_drop_pct
        result.max_single_day_drop_pct = max_drop

        triggered = (
            result.sell_pct is not None
            and result.sell_pct > pct_threshold * 100
            and pe > pe_threshold
            and no_crash
        )
        result.triggered = triggered
        result.forced_red = triggered
        if not no_crash:
            result.note = f"近 5 日有單日跌幅 {max_drop:.2f}% > {self.config.max_drop_pct}%"
        return result

    def compute_strict_for_date(self, asof: str) -> LeadingIndicator:
        """
        計算嚴格版領先指標（PE > 30 固定、不降低門檻）

        此為 backtest_pe30_crash_avoidance.py 的嚴格版邏輯
        """
        from signal_engine import LeadingIndicator

        chip_data = [r for r in self.inst_rows if r["date"] <= asof]
        foreign_shares = get_foreign_shares_asof(
            self.shareholding_data,
            asof,
            fallback_float_shares=CONFIG.chip.tsmc_float_shares
        )
        close = self.close_lookup.get(asof, 0.0)
        eps_asof = self.eps_timeline.get_eps_asof(asof) if self.eps_timeline else {}
        pe = compute_pe(close, eps_asof)
        price_df = get_price_dataframe_asof(self.ohlc_data, asof)

        # 參數：嚴格版固定從 CONFIG 讀取
        pct_threshold = CONFIG.chip.two_month_high_sellout_pct  # 0.01
        pe_threshold = CONFIG.chip.leading_indicator_pe_threshold  # 30.0
        window_days = CONFIG.chip.two_month_window_days
        denom = foreign_shares if (foreign_shares and foreign_shares > 0) else CONFIG.chip.tsmc_float_shares
        denom_label = "外資持股" if (foreign_shares and foreign_shares > 0) else "流通股"

        result = LeadingIndicator(
            pct_threshold=pct_threshold,
            pe_threshold=pe_threshold,
            window_days=window_days,
            foreign_holdings=denom,
            denom_label=denom_label,
            pe_ratio=pe,
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
            and pe > pe_threshold
            and no_crash
        )
        result.triggered = triggered
        result.forced_red = triggered
        if not no_crash:
            result.note = f"近 5 日有單日跌幅 {max_drop:.2f}% > 5%"
        return result


@dataclass
class CrashSignalResult:
    """崩盤訊號分析結果（對應 backtest_crash_signals.py）"""
    crash_date: str
    as_of: str
    crash_ret: float

    # 綜合燈號
    composite_level: str
    composite_label: str
    composite_emoji: str
    composite_score: float

    # 籌碼面燈號
    chip_level: str
    chip_label: str
    chip_emoji: str
    chip_score: float

    # 技術面細分
    tech_early: float
    tech_short: float
    tech_mid: float
    tech_long: float
    tech_combined: float

    # 籌碼細節
    foreign_5d_lots: float
    sell_ratio: float
    max_consecutive_sell: int
    foreign_2m_lots: float
    foreign_holdings_lots: Optional[float]
    pct_of_foreign_holdings: Optional[float]
    pct_of_total_shares: Optional[float]

    # 本益比
    pe_ratio: Optional[float]
    pe_threshold: float
    forced_red: bool

    # 財務面
    fin_gross_margin: Optional[float]
    fin_op_margin: Optional[float]
    fin_net_margin: Optional[float]
    fin_rev_yoy: Optional[float]
    fin_rev_declining: bool
    fin_margin_deter: bool
    fin_score: float

    # 大廠基本面
    bt_nvda_yoy: Optional[float]
    bt_capex_growing: int
    bt_capex_valid: int
    bt_score: float

    # 轉折訊號
    reversal_basic: bool
    reversal_advanced: bool
    ma20_cross: bool
    monthly_break: bool
    bb_squeeze_break: bool

    # 警示
    warned: bool

    error: Optional[str] = None


class CrashSignalAnalyzer:
    """
    崩盤訊號分析器

    對應 backtest_crash_signals.py 邏輯：
    針對崩盤日前一交易日，重現完整的四大面向分析
    """

    def __init__(
        self,
        inst_rows: List[Dict],
        shareholding_data: List[Dict],
        ohlc_data: List[Dict],
        twii_data: Dict[str, float],
        eps_timeline: EPSTimeline,
        qfin_data: Dict[str, Dict],
        nvda_pts: List[Dict],
    ):
        self.inst_rows = inst_rows
        self.shareholding_data = shareholding_data
        self.ohlc_data = ohlc_data
        self.twii_data = twii_data
        self.eps_timeline = eps_timeline
        self.qfin_data = qfin_data
        self.nvda_pts = nvda_pts

        self.engine = SignalEngine()
        self.tech_agent = None  # Lazy init
        self.chip_agent = None  # Lazy init

    def _get_tech_agent(self):
        from tsmc_ai_agents import MarketDynamicsAgent
        if self.tech_agent is None:
            self.tech_agent = MarketDynamicsAgent()
            # 關閉圖表生成
            self.tech_agent._generate_technical_chart = lambda df: ""
        return self.tech_agent

    def _get_chip_agent(self):
        from tsmc_ai_agents import InstitutionalInvestorAgent
        if self.chip_agent is None:
            self.chip_agent = InstitutionalInvestorAgent()
        return self.chip_agent

    def analyze_asof(self, asof_date: str) -> CrashSignalResult:
        """
        分析單一 as-of 日期的完整訊號

        Args:
            asof_date: 分析基準日 YYYY-MM-DD（崩盤日前一交易日）

        Returns:
            CrashSignalResult 完整分析結果
        """
        from signal_engine import (
            FinancialSignals, BigTechSignals,
            TechnicalSignals, ChipSignals,
            score_to_alert,
        )
        import datetime as dt

        asof = dt.date.fromisoformat(asof_date)
        asof_str = asof.isoformat()

        # 1. 財務面（as-of 真實季報）
        fin_signals = self._compute_financial_signals_asof(asof)

        # 2. 大廠基本面（NVDA 營收 YoY）
        nvda_yoy = self._compute_nvda_yoy_asof(asof)
        bigtech_signals = BigTechSignals(
            capex_growing_count=0,
            capex_valid_count=0,
            nvda_revenue_yoy=nvda_yoy,
        )

        # 3. 技術面
        tech_slice = self._get_tech_slice(asof)
        df = self._build_tech_df(tech_slice)
        _, tech_flags, tech_scores, _ = self._get_tech_agent().analyze_sentiment(df)

        close = float(tech_slice.iloc[-1]["close"])
        pe_ratio = self._compute_pe_ratio(asof, close)

        # 4. 籌碼面
        chip_data = [r for r in self.inst_rows if r["date"] <= asof_str]
        _, chip_flags, chip_score = self._get_chip_agent().analyze_flow(chip_data, df)

        tech_signals = TechnicalSignals(scores=tech_scores, flags=tech_flags)
        chip_signals = ChipSignals(score=chip_score, flags=chip_flags)

        # 5. 綜合分析
        res = self.engine.analyze(fin_signals, bigtech_signals, tech_signals, chip_signals)

        # 6. 外資兩月淨買賣佔持股比
        foreign_2m_lots, pct_foreign, pct_total = self._compute_foreign_2m_stats(asof_str)

        # 7. 強制紅燈判定
        forced_red = self._check_forced_red(pe_ratio, foreign_2m_lots, pct_foreign)

        # 8. 燈號轉換
        c_level, c_label, c_emoji = res.alert_level, res.alert_label, res.alert_emoji
        k_level, k_label, k_emoji = score_to_alert(chip_score)

        # 9. 警示判定
        warned = (c_level in ("yellow", "red") or res.reversal_signal or k_level in ("yellow", "red"))

        return CrashSignalResult(
            crash_date="",  # 由呼叫端填入
            as_of=asof_str,
            crash_ret=0.0,  # 由呼叫端填入

            composite_level=c_level,
            composite_label=c_label,
            composite_emoji=c_emoji,
            composite_score=res.comprehensive_score,

            chip_level=k_level,
            chip_label=k_label,
            chip_emoji=k_emoji,
            chip_score=chip_score,

            tech_early=tech_scores.get("early", 0),
            tech_short=tech_scores.get("short", 0),
            tech_mid=tech_scores.get("mid", 0),
            tech_long=tech_scores.get("long", 0),
            tech_combined=res.tech_score,

            foreign_5d_lots=(chip_flags.get("foreign_net_sell_shares") or 0) / 1000.0,
            sell_ratio=chip_flags.get("sell_ratio", 0),
            max_consecutive_sell=chip_flags.get("max_consecutive_sell", 0),
            foreign_2m_lots=foreign_2m_lots,
            foreign_holdings_lots=pct_foreign,
            pct_of_foreign_holdings=pct_foreign * 100 if pct_foreign else None,
            pct_of_total_shares=pct_total * 100 if pct_total else None,

            pe_ratio=pe_ratio,
            pe_threshold=CONFIG.chip.high_sellout_pe_threshold,
            forced_red=forced_red,

            fin_gross_margin=fin_signals.latest_gross_margin,
            fin_op_margin=fin_signals.latest_operating_margin,
            fin_net_margin=fin_signals.latest_net_margin,
            fin_rev_yoy=fin_signals.latest_revenue_yoy,
            fin_rev_declining=fin_signals.revenue_yoy_declining,
            fin_margin_deter=fin_signals.margin_deteriorating,
            fin_score=res.financial_score,

            bt_nvda_yoy=nvda_yoy,
            bt_capex_growing=0,
            bt_capex_valid=0,
            bt_score=res.bigtech_score,

            reversal_basic=res.reversal_signal,
            reversal_advanced=res.reversal_advanced,
            ma20_cross=tech_flags.get("ma20_cross_below", False),
            monthly_break=tech_flags.get("monthly_break_ma12", False),
            bb_squeeze_break=tech_flags.get("bb_squeeze_break", False),

            warned=warned,
        )

    def _compute_financial_signals_asof(self, asof: dt.date) -> FinancialSignals:
        """計算 as-of 真實財務訊號"""
        from signal_engine import FinancialSignals

        dates = sorted(d for d in self.qfin_data if d <= asof)
        if len(dates) < 2:
            return FinancialSignals()

        q0 = self.qfin_data[dates[-1]]
        q_prev = self.qfin_data[dates[-2]]
        q_yoy = self.qfin_data[dates[-5]] if len(dates) >= 5 else None

        rev0, gross0 = q0.get("Revenue"), q0.get("GrossProfit")
        op0, net0 = q0.get("OperatingIncome"), q0.get("IncomeAfterTaxes")
        rev_prev, gross_prev = q_prev.get("Revenue"), q_prev.get("GrossProfit")
        op_prev, net_prev = q_prev.get("OperatingIncome"), q_prev.get("IncomeAfterTaxes")

        def margin(num, den):
            return (num / den * 100) if (num is not None and den) else None

        gross_m = margin(gross0, rev0)
        op_m = margin(op0, rev0)
        net_m = margin(net0, rev0)
        gross_m_prev = margin(gross_prev, rev_prev)
        op_m_prev = margin(op_prev, rev_prev)
        net_m_prev = margin(net_prev, rev_prev)

        rev_yoy = None
        if q_yoy is not None and rev0 and q_yoy.get("Revenue"):
            rev_yoy = (rev0 - q_yoy["Revenue"]) / q_yoy["Revenue"] * 100

        def drop(cur, prev):
            return (cur - prev) if (cur is not None and prev is not None) else 0.0

        gross_drop = drop(gross_m, gross_m_prev)
        op_drop = drop(op_m, op_m_prev)
        net_drop = drop(net_m, net_m_prev)

        # 營收 YoY 連續下滑
        yoys = []
        for i in range(4, 0, -1):
            if len(dates) >= i + 1:
                cur = self.qfin_data[dates[-i]].get("Revenue")
                yago = self.qfin_data[dates[-i - 4]].get("Revenue") if len(dates) >= i + 4 else None
                if cur and yago:
                    yoys.append((cur - yago) / yago * 100)
        rev_declining = len(yoys) >= 3 and yoys[-1] < yoys[-2] and yoys[0] > yoys[-1]

        margin_deter = (gross_drop > 0) or (op_drop > 0) or (net_drop > 0)

        return FinancialSignals(
            latest_revenue_yoy=rev_yoy,
            latest_gross_margin=gross_m,
            latest_operating_margin=op_m,
            latest_net_margin=net_m,
            gross_drop=gross_drop,
            op_drop=op_drop,
            net_drop=net_drop,
            revenue_yoy_declining=rev_declining,
            margin_deteriorating=margin_deter,
        )

    def _compute_nvda_yoy_asof(self, asof: dt.date) -> Optional[float]:
        """計算 as-of NVDA 營收 YoY"""
        avail = [p for p in self.nvda_pts if p["end"] <= asof]
        if not avail:
            return None
        cur = avail[-1]
        yago = next(
            (p for p in avail if p["fp"] == cur["fp"] and p["fy"] == (cur["fy"] or 0) - 1),
            None
        )
        if yago is None:
            target = cur["end"] - dt.timedelta(days=365)
            cands = [p for p in avail if abs((p["end"] - target).days) < 60]
            if cands:
                yago = min(cands, key=lambda p: abs((p["end"] - target).days))
        if yago is None or yago["val"] <= 0:
            return None
        return (cur["val"] - yago["val"]) / yago["val"] * 100

    def _compute_pe_ratio(self, asof: dt.date, close: float) -> Optional[float]:
        """計算 as-of 本益比"""
        usable = sorted(d for d in self.eps_timeline.eps_known if d.report_date <= asof.isoformat())
        trailing = usable[-4:] if len(usable) >= 4 else usable
        ttm_eps = sum(e.eps for e in trailing)
        if ttm_eps > 0:
            return close / ttm_eps
        return None

    def _get_tech_slice(self, asof: dt.date) -> pd.DataFrame:
        """取得技術面切片資料"""
        dates = [ts.date() for ts in self.ohlc_data.index]  # type: ignore
        slice_df = self.ohlc_data[self.ohlc_data.index <= pd.Timestamp(asof)]
        return slice_df

    def _build_tech_df(self, slice_df: pd.DataFrame) -> pd.DataFrame:
        """建構技術面 DataFrame（相容 MarketDynamicsAgent）"""
        rows = []
        for ts, r in slice_df.iterrows():
            d = ts.date()
            twii_close = self.twii_data.get(d)
            tsmc_turnover = (float(r["close"]) * float(r["volume"])) if r.get("volume") else 0.0
            mkt_turnover = (float(twii_close) * 1e9) if twii_close else 0.0
            rows.append({
                "日期": pd.Timestamp(d),
                "台積電開盤價": float(r["open"]) if pd.notna(r["open"]) else float(r["close"]),
                "台積電最高價": float(r["high"]) if pd.notna(r["high"]) else float(r["close"]),
                "台積電最低價": float(r["low"]) if pd.notna(r["low"]) else float(r["close"]),
                "台積電收盤價": float(r["close"]),
                "台積電成交金額": tsmc_turnover,
                "大盤成交金額": mkt_turnover,
            })
        return pd.DataFrame(rows)

    def _compute_foreign_2m_stats(self, asof_str: str) -> Tuple[float, Optional[float], Optional[float]]:
        """計算外資兩月淨買賣張數與佔比"""
        cutoff = (dt.date.fromisoformat(asof_str) - dt.timedelta(days=CONFIG.chip.two_month_window_days)).isoformat()
        net_2m = sum(
            (r["buy"] - r["sell"]) for r in self.inst_rows
            if r["name"] == "Foreign_Investor" and cutoff <= r["date"] <= asof_str
        )
        foreign_2m_lots = net_2m / 1000.0

        hold = next((sh for sh in reversed(self.shareholding_data) if sh["date"] <= asof_str), None)
        if hold and hold.get("foreign_shares", 0) > 0:
            foreign_holdings_lots = hold["foreign_shares"] / 1000.0
            total_shares_lots = hold["total_shares"] / 1000.0
            pct_foreign = foreign_2m_lots / foreign_holdings_lots
            pct_total = foreign_2m_lots / total_shares_lots
        else:
            foreign_holdings_lots = None
            pct_foreign = None
            pct_total = None

        return foreign_2m_lots, pct_foreign, pct_total

    def _check_forced_red(
        self,
        pe_ratio: Optional[float],
        foreign_2m_lots: float,
        pct_foreign: Optional[float]
    ) -> bool:
        """檢查強制紅燈條件"""
        if pe_ratio is None:
            return False
        if pe_ratio <= CONFIG.chip.high_sellout_pe_threshold:
            return False
        if pct_foreign is None:
            # 回退：用流通股當分母
            sellout_threshold = CONFIG.chip.two_month_high_sellout_pct * CONFIG.chip.tsmc_float_shares
            return foreign_2m_lots * 1000 < -sellout_threshold
        sellout_threshold = CONFIG.chip.two_month_high_sellout_pct * (pct_foreign * 1000 * 1000)  # 概估
        return foreign_2m_lots * 1000 < -sellout_threshold