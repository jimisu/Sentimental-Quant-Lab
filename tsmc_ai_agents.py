#!/usr/bin/env python3
"""
TSMC AI Agents 模組
包含負責財務分析、技術分析以及自動化日誌紀錄的 Agent。
"""

import datetime as dt
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
try:
    # Use the non-interactive Agg backend. The agents render charts
    # (plt.savefig) from background threads spawned by run_full_analysis's
    # ThreadPoolExecutor; interactive backends (e.g. TkAgg) touch the
    # GUI main loop and raise "main thread is not in main loop" off-thread.
    # Agg always works and only writes files, so behavior is unchanged.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib as mpl
    import matplotlib.dates as mdates
    from matplotlib.ticker import MaxNLocator
    HAS_MATPLOTLIB = True
    mpl.rcParams["font.family"] = "sans-serif"
    mpl.rcParams["font.sans-serif"] = [
        "PingFang HK",
        "Heiti TC",
        "STHeiti",
        "Songti SC",
        "Arial Unicode MS",
        "Noto Sans CJK TC",
        "Noto Sans CJK SC",
        "DejaVu Sans",
        "sans-serif",
    ]
    mpl.rcParams["axes.unicode_minus"] = False
except ImportError:
    HAS_MATPLOTLIB = False
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from config import CONFIG
from tsmc_financial_agent import QuarterlyFinancialAgent
from tsmc_macro_agent import GlobalMacroAgent
from tsmc_institutional_tracker import InstitutionalTrackerAgent
from signal_engine import (
    SignalEngine,
    FinancialSignals,
    BigTechSignals,
    TechnicalSignals,
    ChipSignals,
    MarketSentimentSignals,
    score_to_alert,
)
import macro_risk


def prepare_daily_chart_path(charts_dir: str, prefix: str) -> str:
    """
    產生帶日期時間的圖表路徑。
    """
    os.makedirs(charts_dir, exist_ok=True)
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    filename = f"{prefix}_{date_part}_{now.strftime('%H%M%S')}.png"
    return os.path.join(charts_dir, filename)


def keep_latest_daily_charts(charts_dir: str, prefix: str, date_part: str, keep: int = 1) -> None:
    """
    每天每種圖只保留最新一張，避免 charts 目錄同日期圖表重複。
    """
    if keep <= 0 or not os.path.exists(charts_dir):
        return

    daily_prefix = f"{prefix}_{date_part}_"
    daily_files = sorted(
        filename
        for filename in os.listdir(charts_dir)
        if filename.startswith(daily_prefix) and filename.endswith(".png")
    )

    for old_filename in daily_files[:-keep]:
        try:
            os.remove(os.path.join(charts_dir, old_filename))
        except OSError as exc:
            print(f"刪除舊圖表失敗: {old_filename} ({exc})")


class TSMCBaseAgent:
    def __init__(self, name: str):
        self.name = name

    def summarize(self, analysis: str) -> str:
        return f"[{self.name}] 報告摘要: {analysis}"

class MarketDynamicsAgent(TSMCBaseAgent):
    """
    Agent 2: 市場動態與技術指標專家
    """
    def __init__(self):
        super().__init__("技術市場 Agent")
        self.source = "TWSE 每日收盤行情 (STOCK_DAY) 與 大盤統計 (FMTQIK)"
        self.logic = "比對台積電成交金額與大盤之變動。偵測『連鎖縮量』以判定市場觀望情緒，並計算『量價背離』以偵測大戶拋售或進場行為。"
        self.charts_dir = "charts"

    def _generate_technical_chart(self, df: pd.DataFrame) -> str:
        """
        產生技術線圖（4 子圖）：
        1. 價格 + 均線 + 布林通道 + 支撐/壓力位
        2. 成交量 + 5 日均量
        3. RSI14 + KD 指標
        4. MACD + 訊號線 + 柱狀圖
        """
        if df.empty or not HAS_MATPLOTLIB:
            return ""

        df = df.sort_values("日期").copy()
        # 將日期轉為 datetime 軸，避免 matplotlib 以字串類別 (StrCategoryConverter)
        # 繪圖，造成 tight_layout / bbox_inches='tight' 觸發 ConversionError。
        df['_x'] = pd.to_datetime(df['日期'])
        df['5MA'] = df['台積電收盤價'].rolling(window=5).mean()
        df['20MA'] = df['台積電收盤價'].rolling(window=20).mean()
        df['60MA'] = df['台積電收盤價'].rolling(window=60).mean()

        # 布林通道 (20, 2)
        df['BB_mid'] = df['20MA']
        df['BB_std'] = df['台積電收盤價'].rolling(window=20).std()
        df['BB_upper'] = df['BB_mid'] + 2 * df['BB_std']
        df['BB_lower'] = df['BB_mid'] - 2 * df['BB_std']

        close = pd.to_numeric(df['台積電收盤價'], errors='coerce')
        high = pd.to_numeric(df['台積電最高價'], errors='coerce')
        low = pd.to_numeric(df['台積電最低價'], errors='coerce')

        rsi14 = self._calculate_rsi(close, period=14).reindex(df.index)
        k, d = self._calculate_kd(high, low, close)
        k = k.reindex(df.index)
        d = d.reindex(df.index)

        macd, signal = self._calculate_macd(close)
        macd = macd.reindex(df.index)
        signal = signal.reindex(df.index)
        histogram = macd - signal

        vol_ma5 = df['台積電成交金額'].rolling(window=5).mean()

        # ── 繪圖 ──────────────────────────────────────────────
        fig, axes = plt.subplots(4, 1, figsize=(12, 14),
                                 gridspec_kw={'height_ratios': [3, 1, 1.2, 1.2]})
        ax1, ax2, ax3, ax4 = axes

        # 子圖 1: 價格 + 均線 + 通道 + 支撐/壓力
        self._plot_price_chart(ax1, df, close, k, d)

        # 子圖 2: 成交量
        self._plot_volume_chart(ax2, df)

        # 子圖 3: RSI + KD
        self._plot_oscillator_chart(ax3, df, rsi14, k, d)

        # 子圖 4: MACD
        self._plot_macd_chart(ax4, df, macd, signal, histogram)

        # 日期刻度（datetime 軸）
        for ax in axes:
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax.tick_params(axis='x', rotation=45)

        # 使用物件導向 API（fig 而非全域 plt 狀態），避免與其他並行執行的
        # Agent 共用 matplotlib 全域狀態而互相干擾，導出空白/錯置的圖表。
        fig.tight_layout()
        filepath = prepare_daily_chart_path(self.charts_dir, "tech_chart")
        fig.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close(fig)
        keep_latest_daily_charts(self.charts_dir, "tech_chart",
                                datetime.now().strftime("%Y%m%d"), keep=1)
        return filepath

    def _plot_price_chart(self, ax, df, close, k, d):
        """繪製價格子圖：K 線 + 均線 + 布林通道 + 支撐/壓力"""
        ax.plot(df['_x'], close, label='收盤價', color='black', linewidth=1.2, zorder=5)
        ax.plot(df['_x'], df['5MA'], label='5MA', color='#1f77b4', linewidth=0.9, linestyle='--')
        ax.plot(df['_x'], df['20MA'], label='20MA', color='#d62728', linewidth=0.9, linestyle='--')

        # 布林通道
        ax.plot(df['_x'], df['BB_upper'], label='布林上軌', color='#ff7f0e',
                linewidth=0.7, linestyle=':', alpha=0.7)
        ax.plot(df['_x'], df['BB_lower'], label='布林下軌', color='#ff7f0e',
                linewidth=0.7, linestyle=':', alpha=0.7)
        ax.fill_between(df['_x'], df['BB_upper'], df['BB_lower'],
                        alpha=0.06, color='#ff7f0e', label='布林通道')

        # 支撐/壓力位（近 60 日高低點）
        support, resistance = self._detect_support_resistance(df)
        if support:
            ax.axhline(y=support, color='green', linewidth=0.6, linestyle='-.',
                       alpha=0.7, label=f'支撐 {support:.0f}')
        if resistance:
            ax.axhline(y=resistance, color='red', linewidth=0.6, linestyle='-.',
                       alpha=0.7, label=f'壓力 {resistance:.0f}')

        ax.set_title('TSMC (2330) 技術分析')
        ax.set_ylabel('價格 (TWD)')
        ax.legend(loc='upper left', fontsize=8, ncol=5)
        ax.grid(True, alpha=0.3)

        # 標註 RSI 頂背離
        rsi14 = self._calculate_rsi(close, period=14).reindex(df.index)
        if len(df) >= 20 and rsi14.notna().sum() >= 20:
            lookback = df.iloc[-60:-5]
            if not lookback.empty:
                swing_idx = lookback['台積電收盤價'].idxmax()
                swing_rsi = rsi14.loc[swing_idx]
                current_price = close.iloc[-1]
                current_rsi = rsi14.iloc[-1]
                swing_price = df.loc[swing_idx, '台積電收盤價']
                if pd.notna(swing_rsi) and current_price >= swing_price and current_rsi < swing_rsi:
                    latest_date = df['_x'].iloc[-1]
                    ax.annotate('RSI 頂背離',
                                xy=(latest_date, current_price),
                                xytext=(latest_date, current_price * 1.03),
                                arrowprops=dict(arrowstyle='->', color='purple', lw=1),
                                color='purple', fontsize=9, va='bottom', ha='right')

    def _plot_volume_chart(self, ax, df):
        """繪製成交量子圖"""
        vol = pd.to_numeric(df['台積電成交金額'], errors='coerce')
        colors = ['#d62728' if c >= o else '#2ca02c'
                  for c, o in zip(pd.to_numeric(df['台積電收盤價'], errors='coerce'),
                                  pd.to_numeric(df['台積電開盤價'], errors='coerce'))]
        ax.bar(df['_x'], vol / 1e8, color=colors, alpha=0.6, width=0.8)
        ax.plot(df['_x'], df['台積電成交金額'].rolling(5).mean() / 1e8,
                label='5 日均量', color='blue', linewidth=0.8)
        ax.set_ylabel('成交量 (億)')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.2)

    def _plot_oscillator_chart(self, ax, df, rsi14, k, d):
        """繪製 RSI + KD 震盪指標子圖"""
        ax.plot(df['_x'], rsi14, label='RSI14', color='purple', linewidth=1.2)
        ax.plot(df['_x'], k, label='%K', color='#1f77b4', linewidth=0.9)
        ax.plot(df['_x'], d, label='%D', color='#d62728', linewidth=0.9)
        ax.axhline(70, color='red', linewidth=0.6, linestyle='--', alpha=0.7)
        ax.axhline(30, color='green', linewidth=0.6, linestyle='--', alpha=0.7)
        ax.axhline(80, color='red', linewidth=0.4, linestyle=':', alpha=0.5)
        ax.axhline(20, color='green', linewidth=0.4, linestyle=':', alpha=0.5)
        ax.fill_between(df['_x'], 70, 100, alpha=0.05, color='red')
        ax.fill_between(df['_x'], 0, 30, alpha=0.05, color='green')
        ax.set_ylabel('RSI / KD')
        ax.set_ylim(0, 100)
        ax.legend(loc='upper left', fontsize=8, ncol=3)
        ax.grid(True, alpha=0.2)

    def _plot_macd_chart(self, ax, df, macd, signal, histogram):
        """繪製 MACD 子圖"""
        ax.plot(df['_x'], macd, label='MACD', color='#1f77b4', linewidth=1.0)
        ax.plot(df['_x'], signal, label='訊號線', color='#d62728', linewidth=1.0)
        colors = ['#d62728' if v >= 0 else '#2ca02c' for v in histogram]
        ax.bar(df['_x'], histogram, color=colors, alpha=0.4, width=0.8, label='柱狀圖')
        ax.axhline(0, color='gray', linewidth=0.5)
        ax.set_ylabel('MACD')
        ax.set_xlabel('日期')
        ax.legend(loc='upper left', fontsize=8, ncol=3)
        ax.grid(True, alpha=0.2)

    # ── 支撐/壓力位偵測 ──────────────────────────────────────────

    def _detect_support_resistance(self, df: pd.DataFrame, lookback: int = 60) -> Tuple[Optional[float], Optional[float]]:
        """
        以近 N 日的高低點當作支撐/壓力位。
        支撐 = 近 N 日最低價，壓力 = 近 N 日最高價。
        """
        recent = df.tail(lookback)
        if recent.empty:
            return None, None
        low = pd.to_numeric(recent['台積電最低價'], errors='coerce').dropna()
        high = pd.to_numeric(recent['台積電最高價'], errors='coerce').dropna()
        if low.empty or high.empty:
            return None, None
        support = low.min()
        resistance = high.max()
        return support, resistance

    # ── KD 指標 ──────────────────────────────────────────────────

    def _calculate_kd(self, high: pd.Series, low: pd.Series, close: pd.Series,
                      k_period: int = 9, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """
        計算隨機指標 (Stochastic Oscillator) %K 與 %D。
        %K = (C - L9) / (H9 - L9) * 100
        %D = %K 的 3 日 SMA
        """
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        denom = highest_high - lowest_low
        k = (close - lowest_low) / denom.replace(0, float('nan')) * 100
        d = k.rolling(window=d_period).mean()
        return k, d

    # ── 均線糾結/發散判斷 ─────────────────────────────────────────

    def _check_ma_convergence(self, df: pd.DataFrame) -> str:
        """
        判斷 5MA、20MA、60MA 是否糾結（差距 < 2%）或發散。
        從 df 的 *MA 欄位讀取（需先呼叫 _enrich_indicators）。
        """
        if df.empty:
            return "均線狀態: 資料不足"
        latest = df.iloc[-1]
        ma5 = latest.get('5MA')
        ma20 = latest.get('20MA')
        ma60 = latest.get('60MA')
        if pd.isna(ma5) or pd.isna(ma60):
            return "均線狀態: 尚在計算中"
        if ma60 == 0:
            return "均線狀態: 尚在計算中"

        spread = abs(ma5 - ma60) / ma60 * 100
        if spread < 2:
            return f"均線糾結 (5MA={ma5:.0f}, 20MA={ma20:.0f}, 60MA={ma60:.0f}, 差距={spread:.1f}%)"
        elif ma5 > ma20 > ma60:
            return f"多頭排列，均線發散 (5MA={ma5:.0f} > 20MA={ma20:.0f} > 60MA={ma60:.0f})"
        elif ma5 < ma20 < ma60:
            return f"空頭排列，均線發散 (5MA={ma5:.0f} < 20MA={ma20:.0f} < 60MA={ma60:.0f})"
        else:
            return f"均線糾結過渡期 (5MA={ma5:.0f}, 20MA={ma20:.0f}, 60MA={ma60:.0f}, 差距={spread:.1f}%)"

    # ── 布林通道寬度 (BW) ─────────────────────────────────────────

    def _bollinger_bandwidth(self, df: pd.DataFrame) -> str:
        """
        計算布林通道寬度 = (上軌 - 下軌) / 中軌 * 100。
        寬度 < 5% 代表壓縮（可能即將大波動）。
        從 df 的 BB_* 欄位讀取（需先呼叫 _enrich_indicators）。
        """
        if df.empty or 'BB_upper' not in df.columns:
            return "布林通道: 資料不足"
        latest = df.iloc[-1]
        upper = latest.get('BB_upper')
        lower = latest.get('BB_lower')
        mid = latest.get('BB_mid')
        if pd.isna(upper) or pd.isna(lower) or pd.isna(mid) or mid == 0:
            return "布林通道: 尚在計算中"
        bw = (upper - lower) / mid * 100
        note = "（壓縮，留意變盤）" if bw < 5 else ""
        return f"布林通道寬度: {bw:.2f}%{note}"

    # ── KD 狀態報告 ──────────────────────────────────────────────

    def _format_kd_status(self, df: pd.DataFrame) -> str:
        """
        報告目前 KD 狀態：超買、超賣、黃金交叉、死亡交叉。
        從 df 的 %K / %D 欄位讀取（需先呼叫 _enrich_indicators）。
        """
        if df.empty or '%K' not in df.columns or '%D' not in df.columns:
            return "KD: 資料不足"
        k = df['%K'].dropna()
        d = df['%D'].dropna()
        if len(k) < 2 or len(d) < 2:
            return "KD: 尚在計算中"

        k_val = k.iloc[-1]
        d_val = d.iloc[-1]
        k_prev = k.iloc[-2]
        d_prev = d.iloc[-2]

        if k_val >= 80 and d_val >= 80:
            status = "超買區"
        elif k_val <= 20 and d_val <= 20:
            status = "超賣區"
        else:
            status = "中性區"

        cross = ""
        if k_prev < d_prev and k_val >= d_val:
            cross = "（黃金交叉）"
        elif k_prev > d_prev and k_val <= d_val:
            cross = "（死亡交叉）"

        return f"KD: %K={k_val:.1f}, %D={d_val:.1f} | {status}{cross}"

    def _add_kd_penalties(self, df: pd.DataFrame, penalties: Dict[str, int]) -> Dict[str, int]:
        """
        KD 訊號計分：超買區 + 死亡交叉 → 短期扣分。
        從 df 的 %K / %D 欄位讀取（需先呼叫 _enrich_indicators）。
        """
        if df.empty or '%K' not in df.columns or '%D' not in df.columns:
            return penalties
        k = df['%K'].dropna()
        d = df['%D'].dropna()
        if len(k) < 2 or len(d) < 2:
            return penalties

        k_val = k.iloc[-1]
        d_val = d.iloc[-1]
        k_prev = k.iloc[-2]
        d_prev = d.iloc[-2]

        if k_val >= 75 and k_prev > d_prev and k_val <= d_val:
            penalties["short"] += 15
        # 超賣區黃金交叉 → 正面訊號（不額外加分，但不扣分）
        elif k_val <= 25 and k_prev < d_prev and k_val >= d_val:
            penalties["short"] = max(0, penalties["short"] - 10)

        return penalties

    def _bollinger_bandwidth_raw(self, df: pd.DataFrame) -> float:
        """回傳最新一期的布林通道寬度百分比（純數值，用於程式判斷）。"""
        if df.empty or 'BB_upper' not in df.columns:
            return -1.0  # 資料不足標記
        latest = df.iloc[-1]
        upper = latest.get('BB_upper')
        lower = latest.get('BB_lower')
        mid = latest.get('BB_mid')
        if pd.isna(upper) or pd.isna(lower) or pd.isna(mid) or mid == 0:
            return -1.0
        return (upper - lower) / mid * 100

    def _detect_position_zone(self, df: pd.DataFrame) -> Tuple[str, float, Dict]:
        """
        判斷目前股價處於高檔還是低檔。

        評分邏輯（綜合百分位 + 布林通道位置 + 20MA 乖離率 + RSI）：
        - 近 60 日收盤價百分位（price percentile）: 40%
        - 布林通道位置（(close - lower) / (upper - lower)）: 25%
        - 20MA 乖離率（normalized to 0-100）: 20%
        - RSI 14（normalized）: 15%

        回傳：
        - zone_label: "高檔" / "中檔" / "低檔"
        - zone_score: 0~100（越高代表越高檔）
        - details: dict 包含各項子分數
        """
        if df.empty or '台積電收盤價' not in df.columns:
            return "未知", 50.0, {}

        df_sorted = df.sort_values("日期").copy()
        close = pd.to_numeric(df_sorted['台積電收盤價'], errors='coerce').dropna()
        if len(close) < 20:
            return "未知", 50.0, {}

        current = close.iloc[-1]

        # 1. 近 60 日收盤價百分位
        lookback = min(60, len(close))
        recent_closes = close.tail(lookback)
        percentile = (recent_closes < current).sum() / lookback * 100
        # 處理最新即為最高的情況
        if current >= recent_closes.max():
            percentile = 100.0

        # 2. 布林通道位置
        bb_position = 50.0
        if 'BB_upper' in df_sorted.columns and 'BB_lower' in df_sorted.columns:
            latest = df_sorted.iloc[-1]
            bb_upper = latest.get('BB_upper')
            bb_lower = latest.get('BB_lower')
            if pd.notna(bb_upper) and pd.notna(bb_lower) and bb_upper != bb_lower:
                bb_position = (current - bb_lower) / (bb_upper - bb_lower) * 100
                bb_position = max(0, min(100, bb_position))

        # 3. 20MA 乖離率（normalised）
        ma20_dev_score = 50.0
        if len(close) >= 20:
            ma20 = close.rolling(20).mean().iloc[-1]
            if pd.notna(ma20) and ma20 > 0:
                deviation = (current - ma20) / ma20 * 100
                # 乖離率通常在 -10%~+10%，normalize 到 0~100，50 = 0 乖離
                ma20_dev_score = max(0, min(100, 50 + deviation * 5))

        # 4. RSI
        rsi_score = 50.0
        rsi14 = self._calculate_rsi(close, period=14)
        rsi_val = rsi14.iloc[-1] if len(rsi14.dropna()) > 0 else 50
        if pd.notna(rsi_val):
            rsi_score = rsi_val  # RSI 本身就是 0~100

        zone_score = (
            percentile * 0.40 +
            bb_position * 0.25 +
            ma20_dev_score * 0.20 +
            rsi_score * 0.15
        )

        if zone_score >= 75:
            zone_label = "高檔"
        elif zone_score <= 25:
            zone_label = "低檔"
        else:
            zone_label = "中檔"

        details = {
            "price_percentile": round(percentile, 1),
            "bb_position": round(bb_position, 1),
            "ma20_dev_score": round(ma20_dev_score, 1),
            "rsi_score": round(rsi_score, 1),
            "zone_score": round(zone_score, 1),
        }
        return zone_label, zone_score, details

    def _check_high_zone_volume_health(self, df: pd.DataFrame) -> Tuple[bool, List[str], List[str]]:
        """
        高檔量價健康度檢查。

        在高檔區，若以下條件成立則為安全：
        1. 下跌日量縮（當日收盤 < 前日收盤 → 當日量 < 前日量）
        2. 上漲日量增（當日收盤 > 前日收盤 → 當日量 > 前日量）
        3. 每次突破近 20 日高點時，量能均大於 5 日均量

        回傳：
        - is_healthy: bool
        - safe_signals: list of safe signals 描述
        - warnings: list of warning 描述
        """
        warnings = []
        safe_signals = []

        df_sorted = df.sort_values("日期").copy()
        if len(df_sorted) < 20:
            return True, ["資料不足，預設安全"], []

        close = pd.to_numeric(df_sorted['台積電收盤價'], errors='coerce')
        vol = pd.to_numeric(df_sorted['台積電成交金額'], errors='coerce')
        vol_ma5 = vol.rolling(5).mean()

        # 檢查近 10 個交易日的量價關係
        check_days = min(10, len(df_sorted) - 1)
        down_days = 0
        down_on_low_vol = 0
        up_days = 0
        up_on_high_vol = 0

        for i in range(-check_days, 0):
            c_today = close.iloc[i]
            c_prev = close.iloc[i - 1]
            v_today = vol.iloc[i]
            v_prev = vol.iloc[i - 1]

            if pd.isna(c_today) or pd.isna(c_prev) or pd.isna(v_today) or pd.isna(v_prev):
                continue

            if c_today < c_prev:
                down_days += 1
                if v_today < v_prev:
                    down_on_low_vol += 1
            elif c_today > c_prev:
                up_days += 1
                if v_today > v_prev:
                    up_on_high_vol += 1

        # 下跌量縮
        if down_days > 0:
            ratio = down_on_low_vol / down_days
            if ratio >= 0.6:
                safe_signals.append(f"下跌量縮（{down_on_low_vol}/{down_days} 個下跌日量縮）")
            else:
                warnings.append(f"下跌未量縮（僅 {down_on_low_vol}/{down_days} 個下跌日量縮，可能出貨）")

        # 上漲量增
        if up_days > 0:
            ratio = up_on_high_vol / up_days
            if ratio >= 0.6:
                safe_signals.append(f"上漲量增（{up_on_high_vol}/{up_days} 個上漲日量增）")
            else:
                warnings.append(f"上漲未量增（僅 {up_on_high_vol}/{up_days} 個上漲日量增，動能不足）")

        # 突破前高量能檢查（近 20 日）
        lookback = 20
        recent = df_sorted.tail(lookback).copy()
        if len(recent) >= 10:
            recent_close = pd.to_numeric(recent['台積電收盤價'], errors='coerce')
            recent_vol = pd.to_numeric(recent['台積電成交金額'], errors='coerce')
            recent_vol_ma5 = recent_vol.rolling(5).mean()

            breakout_with_vol = 0
            breakout_without_vol = 0

            for i in range(5, len(recent)):
                c = recent_close.iloc[i]
                max_prev = recent_close.iloc[max(0, i - 10):i].max()
                v = recent_vol.iloc[i]
                v_ma5 = recent_vol_ma5.iloc[i]

                if pd.isna(c) or pd.isna(v) or pd.isna(v_ma5):
                    continue

                if c >= max_prev * 0.995:  # 突破或觸及前 10 日高點（允許 0.5% 誤差）
                    if v > v_ma5:
                        breakout_with_vol += 1
                    else:
                        breakout_without_vol += 1

            total_breakouts = breakout_with_vol + breakout_without_vol
            if total_breakouts > 0:
                ratio = breakout_with_vol / total_breakouts
                if ratio >= 0.6:
                    safe_signals.append(
                        f"突破前高帶量（{breakout_with_vol}/{total_breakouts} 次突破時量 > 5 日均量）"
                    )
                else:
                    warnings.append(
                        f"突破前高未帶量（僅 {breakout_with_vol}/{total_breakouts} 次突破時量 > 5 日均量，假突破風險）"
                    )

        is_healthy = len(warnings) == 0
        return is_healthy, safe_signals, warnings

    def _format_20ma_deviation(self, df: pd.DataFrame) -> Tuple[str, bool]:
        """計算最新收盤價相對 20MA 的乖離率。"""
        if df.empty or '台積電收盤價' not in df.columns:
            return "20MA乖離率: 無收盤價資料", False

        close_prices = pd.to_numeric(
            df.sort_values("日期")['台積電收盤價'],
            errors='coerce'
        ).dropna()
        if len(close_prices) < 20:
            return "20MA乖離率: 資料不足（需至少20個交易日）", False

        # 計算完整的 20MA 序列與乖離率序列
        ma20_series = close_prices.rolling(window=20).mean()
        deviations = (close_prices - ma20_series) / ma20_series * 100
        
        latest_dev = deviations.iloc[-1]
        latest_close = close_prices.iloc[-1]
        ma20_val = ma20_series.iloc[-1]
        
        # 找出這段時間內的極值
        max_pos = deviations.max()
        max_neg = deviations.min()
        
        # 判斷是否由正轉負 (最新 < 0 且 前一日 >= 0)
        crossed_below = bool((deviations.iloc[-1] < 0) and (deviations.iloc[-2] >= 0))

        report = (
            f"20MA乖離率: {latest_dev:+.2f}%（收盤 {latest_close:.2f} / 20MA {ma20_val:.2f}） | "
            f"區間極值: [正] {max_pos:+.2f}% / [負] {max_neg:+.2f}%"
        )
        return report, crossed_below

    def _calculate_rsi(self, close_prices: pd.Series, period: int = 14) -> pd.Series:
        """計算 RSI。"""
        delta = close_prices.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss.replace(0, float('nan'))
        return 100 - (100 / (1 + rs))

    def _calculate_macd(self, close_prices: pd.Series) -> Tuple[pd.Series, pd.Series]:
        """計算 MACD 線與訊號線。"""
        ema12 = close_prices.ewm(span=12, adjust=False).mean()
        ema26 = close_prices.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd, signal

    def _format_reversal_signals(self, df: pd.DataFrame) -> Tuple[str, bool, Dict[str, int], List[str]]:
        """判斷短中長期反轉向下訊號。回傳 (report, monthly_break, penalties, vol_price_warnings)"""
        YELLOW = "\033[1;33m"
        RESET = "\033[0m"
        penalties = {"early": 0, "short": 0, "mid": 0, "long": 0}
        required_cols = {'日期', '台積電開盤價', '台積電最高價', '台積電最低價', '台積電收盤價', '台積電成交金額'}
        if df.empty or not required_cols.issubset(df.columns):
            return "反轉訊號: 資料不足", False, penalties

        tech_df = df.sort_values("日期").copy()
        tech_df["日期"] = pd.to_datetime(tech_df["日期"], errors="coerce")
        for col in ['台積電開盤價', '台積電最高價', '台積電最低價', '台積電收盤價', '台積電成交金額']:
            tech_df[col] = pd.to_numeric(tech_df[col], errors='coerce')
        tech_df = tech_df.dropna(subset=['日期', '台積電收盤價', '台積電成交金額'])
        if len(tech_df) < 20:
            return "反轉訊號: 資料不足（需至少20個交易日）", False, penalties

        close = tech_df['台積電收盤價']
        volume = tech_df['台積電成交金額']
        rsi14 = self._calculate_rsi(close, period=14)

        # 根據用戶要求，將早期警示分為三大類別
        kline_warnings = []      # 頂部K線形態
        vol_price_warnings = []  # 量價背離
        rsi_warnings = []        # RSI頂背離
        
        latest = tech_df.iloc[-1]
        prev = tech_df.iloc[-2] if len(tech_df) >= 2 else None
        body = abs(latest['台積電收盤價'] - latest['台積電開盤價'])
        price_range = latest['台積電最高價'] - latest['台積電最低價']
        upper_shadow = latest['台積電最高價'] - max(latest['台積電開盤價'], latest['台積電收盤價'])
        
        # 1. 頂部K線形態判斷
        if price_range > 0 and upper_shadow / price_range >= 0.45 and upper_shadow >= max(body * 2, 1):
            kline_warnings.append("長上影線")
            penalties["short"] += 10

        if prev is not None:
            prev_bullish = prev['台積電收盤價'] > prev['台積電開盤價']
            latest_bearish = latest['台積電收盤價'] < latest['台積電開盤價']
            engulfed = latest['台積電開盤價'] >= prev['台積電收盤價'] and latest['台積電收盤價'] <= prev['台積電開盤價']
            if prev_bullish and latest_bearish and engulfed:
                kline_warnings.append("吞噬黑K")
                penalties["short"] += 15

        # 連續小實體判斷 (多頭猶豫/力道衰竭)
        if len(tech_df) >= 4:
            last_3 = tech_df.tail(3)
            is_consecutive_small = all(
                ((abs(r['台積電收盤價'] - r['台積電開盤價']) / (r['台積電最高價'] - r['台積電最低價'])) < 0.35) 
                if (r['台積電最高價'] - r['台積電最低價']) > 0 else False
                for _, r in last_3.iterrows()
            )
            if is_consecutive_small:
                kline_warnings.append("連三日小實體(動能衰竭)")
                penalties["short"] += 10

        # 2. 局部高點 (Swing High) 背離判斷
        # 找過去 5-60 天內的最高收盤價作為參考點
        lookback = tech_df.iloc[-60:-5]
        if not lookback.empty:
            swing_high_idx = lookback['台積電收盤價'].idxmax()
            swing_high_price = lookback.loc[swing_high_idx, '台積電收盤價']
            swing_high_vol = lookback.loc[swing_high_idx, '台積電成交金額']
            swing_high_rsi = rsi14.loc[swing_high_idx]
            
            current_price = latest['台積電收盤價']
            current_vol_ma5 = volume.tail(5).mean()
            current_rsi = rsi14.iloc[-1]
            
            # 量價背離：價格突破或接近前高，但 5 日均量顯著低於前高點成交量
            if current_price >= swing_high_price * 0.98 and current_vol_ma5 < swing_high_vol * 0.75:
                vol_price_warnings.append(f"量價背離(量能僅前高{current_vol_ma5/swing_high_vol:.1%})")
                penalties["early"] += 50

            # RSI 頂背離：價格高於前高，但 RSI 低於前高
            if current_price > swing_high_price and current_rsi < swing_high_rsi:
                rsi_warnings.append(f"日線RSI頂背離(價格新高但RSI {current_rsi:.1f} < 前高 {swing_high_rsi:.1f})")
                penalties["early"] += 20

        # 週線級別分析
        weekly = tech_df.set_index("日期")['台積電收盤價'].resample("W-FRI").last().dropna()
        weekly_rsi = self._calculate_rsi(weekly, period=14) if len(weekly) >= 15 else pd.Series(dtype=float)
        weekly_macd, weekly_signal = self._calculate_macd(weekly) if len(weekly) >= 26 else (pd.Series(dtype=float), pd.Series(dtype=float))

        if len(weekly_rsi) >= 2:
            latest_w_price = weekly.iloc[-1]
            w_lookback = weekly.iloc[-15:-1]
            if not w_lookback.empty:
                w_swing_idx = w_lookback.idxmax()
                swing_w_rsi = weekly_rsi.loc[w_swing_idx]
                current_w_rsi = weekly_rsi.iloc[-1]
                if latest_w_price > weekly.loc[w_swing_idx] and current_w_rsi < swing_w_rsi:
                    rsi_warnings.append(f"週線RSI頂背離(週收盤新高但RSI {current_w_rsi:.1f} < 前高 {swing_w_rsi:.1f})")
                    penalties["early"] += 30

        # 組合早期警示報告
        warning_parts = []
        if kline_warnings: warning_parts.append(f"頂部K線形態({', '.join(kline_warnings)})")
        if vol_price_warnings: warning_parts.append(f"{YELLOW}量價背離({', '.join(vol_price_warnings)}){RESET}")
        if rsi_warnings: warning_parts.append(f"RSI頂背離({', '.join(rsi_warnings)})")

        mid_signals = []
        weekly_ma12 = weekly.rolling(window=12).mean()
        if len(weekly_ma12.dropna()) >= 2 and weekly_ma12.iloc[-1] < weekly_ma12.iloc[-2]:
            mid_signals.append("週線MA12向下彎頭")
            penalties["mid"] += 15
        if len(weekly_rsi.dropna()) >= 2:
            recent_overbought = weekly_rsi.tail(8).max() >= 70
            if recent_overbought and weekly_rsi.iloc[-2] >= 60 and weekly_rsi.iloc[-1] < 60:
                mid_signals.append("週線RSI由超買區轉弱並跌破60")
                penalties["mid"] += 10
        if len(weekly_macd.dropna()) >= 2 and len(weekly_signal.dropna()) >= 2:
            if weekly_macd.iloc[-2] >= weekly_signal.iloc[-2] and weekly_macd.iloc[-1] < weekly_signal.iloc[-1]:
                mid_signals.append("週線MACD死亡交叉")
                penalties["mid"] += 15

        monthly = tech_df.set_index("日期")['台積電收盤價'].resample("ME").last().dropna()
        monthly_ma12 = monthly.rolling(window=12).mean()
        long_signals = []
        monthly_break = False
        if len(monthly_ma12.dropna()) >= 2:
            if monthly_ma12.iloc[-1] < monthly_ma12.iloc[-2]:
                long_signals.append("月線MA12向下彎頭")
                penalties["long"] += 30
            if monthly.iloc[-1] < monthly_ma12.iloc[-1]:
                long_signals.append("月線收盤跌破MA12")
                monthly_break = True
                penalties["long"] += 40
        elif len(monthly) < 13:
            long_signals.append("月線MA12資料不足")

        # ── 均線整體排列判斷（新增） ──────────────────────────────────
        ma5 = close.rolling(5).mean().iloc[-1] if len(close) >= 5 else None
        ma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else None
        ma60_val = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
        if pd.notna(ma5) and pd.notna(ma20) and pd.notna(ma60_val):
            if ma5 > ma20 > ma60_val:
                long_signals.append("均線多頭排列")
            elif ma5 < ma20 < ma60_val:
                long_signals.append("均線空頭排列")
                penalties["long"] += 20
            else:
                long_signals.append("均線糾結過渡")

        # ── 支撐/壓力位資訊（新增） ──────────────────────────────────
        support_df = df[['日期', '台積電最低價', '台積電最高價', '台積電收盤價']].copy()
        support_df['台積電最低價'] = pd.to_numeric(support_df['台積電最低價'], errors='coerce')
        support_df['台積電最高價'] = pd.to_numeric(support_df['台積電最高價'], errors='coerce')
        support, resistance = self._detect_support_resistance(support_df)

        # ── 帶量跌破關鍵均線 / 支撐（技術線型帶量跌破所有支撐）──
        # 日線收盤跌破 20MA / 60MA / 關鍵支撐，且伴隨放量（≥ 20 日均量 1.5 倍）
        # 時，視為趨勢性破線，對長期分數給予顯著懲罰。一般回檔（僅跌破 20MA）
        # 僅小幅扣分，梯度合理。
        latest_close = latest['台積電收盤價']
        day_vol = latest['台積電成交金額']
        avg_vol_20 = volume.rolling(20, min_periods=5).mean().iloc[-1] if len(volume) >= 5 else None
        vol_spike = (pd.notna(avg_vol_20) and avg_vol_20 > 0 and day_vol >= avg_vol_20 * 1.5)

        below_20 = pd.notna(ma20) and latest_close < ma20
        below_60 = pd.notna(ma60_val) and latest_close < ma60_val
        below_support = support is not None and latest_close < support

        if below_20:
            long_signals.append("跌破 20MA")
            penalties["long"] += 15
        if below_60:
            long_signals.append("跌破 60MA")
            penalties["long"] += 15
        if below_support:
            long_signals.append("跌破關鍵支撐位")
            penalties["long"] += 15
        if (below_20 or below_60 or below_support) and vol_spike:
            long_signals.append("帶量破線確認")
            penalties["long"] += 15

        short_status = "頂部反轉預警" if kline_warnings else "短期觀察"
        mid_status = "中期轉弱確認" if len(mid_signals) >= 2 else "中期觀察"
        long_status = "長期轉空確認" if len([s for s in long_signals if "資料不足" not in s]) >= 2 else "長期觀察"

        support_resistance_line = ""
        if support is not None and resistance is not None:
            support_resistance_line = f"\n   ● 支撐 {support:.0f} / 壓力 {resistance:.0f}"

        report_lines = [
            f"● 早期警示: {', '.join(warning_parts) if warning_parts else '無'}",
            f"● 短期形態: {short_status}",
            f"● 中期趨勢: {mid_status} ({'; '.join(mid_signals) if mid_signals else '保持強勢'})",
            f"● 長期趨勢: {long_status} ({'; '.join(long_signals) if long_signals else '多頭格局'})",
        ]
        result = "\n   ".join(report_lines)
        if support_resistance_line:
            result += support_resistance_line
        return result, monthly_break, penalties, vol_price_warnings

    def _enrich_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """在 df 上計算所有技術指標欄位（均線、布林通道、KD 等）。"""
        df = df.sort_values("日期").copy()
        df['5MA'] = df['台積電收盤價'].rolling(window=5).mean()
        df['20MA'] = df['台積電收盤價'].rolling(window=20).mean()
        df['60MA'] = df['台積電收盤價'].rolling(window=60).mean()

        # 布林通道 (20, 2)
        df['BB_mid'] = df['20MA']
        df['BB_std'] = df['台積電收盤價'].rolling(window=20).std()
        df['BB_upper'] = df['BB_mid'] + 2 * df['BB_std']
        df['BB_lower'] = df['BB_mid'] - 2 * df['BB_std']

        # KD 指標
        high = pd.to_numeric(df['台積電最高價'], errors='coerce')
        low = pd.to_numeric(df['台積電最低價'], errors='coerce')
        close = pd.to_numeric(df['台積電收盤價'], errors='coerce')
        k, d = self._calculate_kd(high, low, close)
        df['%K'] = k.values
        df['%D'] = d.values

        return df

    def analyze_sentiment(self, df: pd.DataFrame) -> Tuple[str, Dict, Dict[str, int], bool]:
        report_prefix = f"數據來源: {self.source}\n分析邏輯: {self.logic}\n結論: "

        if df.empty or len(df) < 5:
            return f"{report_prefix}資料不足", {}, {"early": 0, "short": 0, "mid": 0, "long": 0}, False

        # 先計算所有技術指標欄位
        df = self._enrich_indicators(df)

        chart_path = self._generate_technical_chart(df)
        ma20_detail, crossed_below = self._format_20ma_deviation(df)
        reversal_detail, monthly_break, penalties, vol_price_warnings = self._format_reversal_signals(df)
        vol_price_divergence = len(vol_price_warnings) > 0

        # 新增指標報告
        ma_status = self._check_ma_convergence(df)
        bb_status = self._bollinger_bandwidth(df)
        kd_status = self._format_kd_status(df)

        # 新增 KD 訊號計分
        penalties = self._add_kd_penalties(df, penalties)

        # 整合 MA20 破位權重
        if crossed_below:
            penalties["short"] += 20

        # ── 高低檔判斷 ──────────────────────────────────────────────
        zone_label, zone_score, zone_details = self._detect_position_zone(df)
        zone_report_lines = [
            f"**目前處於 {zone_label}**（綜合分數: {zone_score:.1f}/100）",
            f"  價格百分位: {zone_details.get('price_percentile', '-')}% | "
            f"布林通道位置: {zone_details.get('bb_position', '-')}% | "
            f"20MA 偏離: {zone_details.get('ma20_dev_score', '-')} | "
            f"RSI: {zone_details.get('rsi_score', '-')}",
        ]

        # 高檔量價健康度檢查
        high_zone_health = None
        if zone_label == "高檔":
            is_healthy, safe_signals, warnings = self._check_high_zone_volume_health(df)
            high_zone_health = {"is_healthy": is_healthy, "safe_signals": safe_signals, "warnings": warnings}
            zone_report_lines.append(f"  高檔量價狀態: {'✅ 安全' if is_healthy else '⚠️ 警告'}")
            if safe_signals:
                GREEN = "\033[1;32m"
                RESET = "\033[0m"
                zone_report_lines.append(f"    {GREEN}安全訊號: {'; '.join(safe_signals)}{RESET}")
            if warnings:
                YELLOW = "\033[1;33m"
                RESET = "\033[0m"
                zone_report_lines.append(f"    {YELLOW}⚠️ 警告: {'; '.join(warnings)}{RESET}")
            # 高檔且量價不健康 → 扣分
            if not is_healthy:
                penalties["short"] += 15
                penalties["mid"] += 10

        scores = {k: max(0, 100 - v) for k, v in penalties.items()}
        zone_section = "\n   ".join(zone_report_lines)
        detail_suffix = (
            f"\n   ● {ma20_detail}"
            f"\n   ● {ma_status}"
            f"\n   ● {bb_status}"
            f"\n   ● {kd_status}"
            f"\n   {reversal_detail}"
        )

        # 布林通道壓縮後破位判斷
        bb_squeeze_break = False
        if not df.empty and 'BB_upper' in df.columns and len(df) > 20:
            latest = df.iloc[-1]
            close_val = pd.to_numeric(df['台積電收盤價'], errors='coerce').iloc[-1]
            bb_lower = latest.get('BB_lower')
            bb_upper = latest.get('BB_upper')
            bb_mid = latest.get('BB_mid')
            if pd.notna(bb_lower) and pd.notna(bb_upper) and pd.notna(bb_mid) and pd.notna(close_val) and bb_mid > 0:
                bw_now = (bb_upper - bb_lower) / bb_mid * 100
                # 前 5 日平均寬度 < 5% 代表壓縮
                prev_bws = []
                for i in range(-6, -1):
                    r = df.iloc[i]
                    if pd.notna(r.get('BB_upper')) and pd.notna(r.get('BB_lower')) and pd.notna(r.get('BB_mid')) and r.get('BB_mid', 0) > 0:
                        prev_bws.append((r['BB_upper'] - r['BB_lower']) / r['BB_mid'] * 100)
                prev_bw = sum(prev_bws) / len(prev_bws) if prev_bws else 10
                # 前期壓縮（< 5%）且現在收在通道外
                if prev_bw < 5 and (close_val < bb_lower or close_val > bb_upper):
                    bb_squeeze_break = True

        tech_flags = {
            "ma20_cross_below": crossed_below,
            "monthly_break_ma12": monthly_break,
            "bb_squeeze_break": bb_squeeze_break,
        }

        # 確保資料按日期升序排序
        recent = df.sort_values("日期").tail(5).copy()
        tsmc_vals = recent['台積電成交金額'].tolist()[::-1]
        mkt_vals = recent['大盤成交金額'].tolist()[::-1]

        # 1. 偵測量能萎縮
        tsmc_declining = all(x < y for x, y in zip(tsmc_vals, tsmc_vals[1:3]))
        mkt_declining = all(x < y for x, y in zip(mkt_vals, mkt_vals[1:3]))

        # 2. 偵測大戶拋售（量增價跌）
        insights = []
        if '台積電收盤價' in recent.columns:
            avg_vol = recent['台積電成交金額'].mean()
            latest_vol = recent['台積電成交金額'].iloc[-1]
            latest_price = recent['台積電收盤價'].iloc[-1]
            prev_price = recent['台積電收盤價'].iloc[-2]
            price_change = latest_price - prev_price
            if latest_vol > avg_vol * 1.3 and price_change < 0:
                insights.append("警告：偵測到異常賣壓！成交量顯著放大且股價下跌，疑似大戶減碼。")
            elif latest_vol > avg_vol * 1.5 and price_change > 0:
                insights.append("強勢：大戶進場跡象。成交量異常放大且股價收紅。")

        image_md = f"\n![Technical Chart]({chart_path})" if chart_path else ""

        # 將高低檔資訊附加到 tech_flags
        tech_flags["position_zone"] = zone_label
        tech_flags["position_zone_score"] = zone_score
        if high_zone_health is not None:
            tech_flags["high_zone_healthy"] = high_zone_health["is_healthy"]
            tech_flags["high_zone_warnings"] = high_zone_health["warnings"]

        if insights:
            return f"{report_prefix}{' | '.join(insights)}{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores, vol_price_divergence
        if tsmc_declining and mkt_declining:
            return f"{report_prefix}市場極度觀望：個股與大盤呈現連鎖縮量。{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores, vol_price_divergence
        elif tsmc_declining:
            return f"{report_prefix}警訊：台積電成交量持續萎縮，資金動能轉弱。{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores, vol_price_divergence

        return f"{report_prefix}量能結構尚屬正常。{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores, vol_price_divergence

class InstitutionalInvestorAgent(TSMCBaseAgent):
    """
    Agent 3: 籌碼分析專家
    監控三大法人（特別是外資）的買賣超動態。
    優化重點：
    1. 外資動向多維度分析（賣超天數比例、連續賣超、買賣超分級）
    2. 三大法人個別趨勢摘要
    3. 法人動向分歧偵測
    """
    # 買賣超分級閾值（張）
    SELL_GRADE_THRESHOLDS = {
        "minor": 500,      # 輕微賣超：< 500 張
        "moderate": 3000,  # 中度賣超：500 ~ 3000 張
        "heavy": 10000,    # 大幅賣超：3000 ~ 10000 張
        "extreme": 100000, # 極端賣超：> 10000 張
    }

    def __init__(self):
        super().__init__("籌碼分析 Agent")
        self.source = "FinMind 三大法人買賣超資料集 (TaiwanStockInstitutionalInvestorsBuySell)"
        self.logic = "追蹤三大法人（外資、投信、自營商）買賣超行為。連續外資賣超被視為 Trend-killer 訊號；三大法人同步買超則視為籌碼共振。新增：賣超分級、動向分歧偵測、個別法人趨勢摘要。"
        self.charts_dir = "charts"
        self.institution_type_labels = {
            "Foreign_Investor": "外資",
            "Foreign_Dealer_Self": "外資",
            "Investment_Trust": "投信",
            "Dealer": "自營商",
            "Dealer_self": "自營商",
            "Dealer_Hedging": "自營商",
            "外資": "外資",
            "外陸資": "外資",
            "投信": "投信",
            "自營商": "自營商",
            "自營商(自行買賣)": "自營商",
            "自營商(避險)": "自營商",
        }

    def _grade_sell_magnitude(self, total_sell_lots: float, days: int) -> str:
        """
        根據 5 日累計賣超張數分級買賣超嚴重程度。
        """
        daily_avg = total_sell_lots / max(days, 1)
        if total_sell_lots < self.SELL_GRADE_THRESHOLDS["minor"]:
            return f"輕微（日均賣超 {daily_avg:.0f} 張）"
        elif total_sell_lots < self.SELL_GRADE_THRESHOLDS["moderate"]:
            return f"中度（日均賣超 {daily_avg:.0f} 張）"
        elif total_sell_lots < self.SELL_GRADE_THRESHOLDS["heavy"]:
            return f"大幅（日均賣超 {daily_avg:.0f} 張）"
        elif total_sell_lots < self.SELL_GRADE_THRESHOLDS["extreme"]:
            return f"嚴重（日均賣超 {daily_avg:.0f} 張）"
        else:
            return f"極端（日均賣超 {daily_avg:.0f} 張）"

    def _analyze_single_institution(self, foreign_daily: pd.Series) -> Dict:
        """
        深入分析外資單日買賣超趨勢。
        回傳包含賣超天數比例、最長連續賣超、買賣超分級等資訊。
        """
        if foreign_daily.empty:
            return {"sell_ratio": 0, "max_consecutive_sell": 0, "grade": "資料不足", "daily_details": []}

        daily_values = foreign_daily.values
        dates = foreign_daily.index.tolist()
        total_days = len(daily_values)
        sell_days = int((daily_values < 0).sum())
        buy_days = int((daily_values > 0).sum())
        sell_ratio = sell_days / max(total_days, 1) * 100

        # 計算最長連續賣超
        max_consecutive = 0
        current_streak = 0
        for v in daily_values:
            if v < 0:
                current_streak += 1
                max_consecutive = max(max_consecutive, current_streak)
            else:
                current_streak = 0

        total_net = float(foreign_daily.sum())
        total_sell_lots = abs(min(total_net, 0)) / 1000  # 只取賣超部分
        grade = self._grade_sell_magnitude(total_sell_lots, sell_days if sell_days > 0 else total_days)

        return {
            "total_days": total_days,
            "sell_days": sell_days,
            "buy_days": buy_days,
            "sell_ratio": sell_ratio,
            "max_consecutive_sell": max_consecutive,
            "grade": grade,
            "total_net_shares": total_net,
        }

    def _analyze_individual_trends(self, df: pd.DataFrame, type_col: str) -> Dict[str, Dict]:
        """
        分析三大法人各自的買賣超趨勢摘要。
        回傳每個法人的累計淨買賣、買賣天數等摘要。
        """
        normalized = df.copy()
        normalized["institution_label"] = normalized[type_col].apply(self._normalize_institution_label)
        normalized = normalized[normalized["institution_label"].notna()].copy()
        normalized["buy"] = pd.to_numeric(normalized["buy"], errors="coerce").fillna(0)
        normalized["sell"] = pd.to_numeric(normalized["sell"], errors="coerce").fillna(0)
        normalized["net_buy_shares"] = normalized["buy"] - normalized["sell"]

        daily_net = (
            normalized
            .groupby(["date", "institution_label"], as_index=False)["net_buy_shares"]
            .sum()
        )

        trends = {}
        for label in ["外資", "投信", "自營商"]:
            inst_data = daily_net[daily_net["institution_label"] == label].sort_values("date")
            if inst_data.empty:
                trends[label] = {"net_shares": 0, "sell_days": 0, "total_days": 0, "summary": "無資料"}
                continue
            total = float(inst_data["net_buy_shares"].sum())
            sell_days = int((inst_data["net_buy_shares"] < 0).sum())
            total_days = len(inst_data)
            direction = "買超" if total > 0 else "賣超" if total < 0 else "持平"
            trends[label] = {
                "net_shares": total,
                "sell_days": sell_days,
                "total_days": total_days,
                "summary": f"{direction} {abs(total) / 1000:.0f} 張 / {total_days} 日中賣超 {sell_days} 日",
            }
        return trends

    def _detect_institution_divergence(self, trends: Dict[str, Dict]) -> str:
        """
        偵測三大法人動向是否分歧。
        例如：外資大賣但投信大買 → 法人分歧，需留意。
        """
        significant_labels = []
        for label, info in trends.items():
            net = info.get("net_shares", 0)
            if abs(net) < 10000:  # 忽略小額（< 10000 股）
                continue
            direction = "買" if net > 0 else "賣"
            significant_labels.append(f"{label}{direction}超 {abs(net) / 1000:.0f} 張")

        if len(significant_labels) >= 2:
            return f"法人動向分歧：{'、'.join(significant_labels)}"
        return ""

    def _normalize_institution_label(self, raw_label) -> Optional[str]:
        label = str(raw_label).strip()
        return self.institution_type_labels.get(label)

    def _format_lots(self, shares: float) -> str:
        direction = "買超" if shares > 0 else "賣超" if shares < 0 else "持平"
        return f"{direction} {abs(shares) / 1000:.0f} 張"

    def _analyze_three_institution_resonance(self, df: pd.DataFrame, type_col: str) -> Tuple[str, Dict]:
        normalized = df.copy()
        normalized["institution_label"] = normalized[type_col].apply(self._normalize_institution_label)
        normalized = normalized[normalized["institution_label"].notna()].copy()

        if normalized.empty:
            return "三大法人資料不足，無法判斷是否共振買入。", {
                "institutional_resonance_buy": False,
                "three_institution_net_buy": 0,
            }

        normalized["buy"] = pd.to_numeric(normalized["buy"], errors="coerce").fillna(0)
        normalized["sell"] = pd.to_numeric(normalized["sell"], errors="coerce").fillna(0)
        # 直接計算淨買賣股數
        normalized["net_buy_shares"] = normalized["buy"] - normalized["sell"]

        daily_net = (
            normalized
            .groupby(["date", "institution_label"], as_index=False)["net_buy_shares"]
            .sum()
        )
        complete_dates = (
            daily_net.groupby("date")["institution_label"]
            .nunique()
            .loc[lambda series: series >= 3]
        )

        if complete_dates.empty:
            return "三大法人資料不足，無法判斷是否共振買入。", {
                "institutional_resonance_buy": False,
                "three_institution_net_buy": 0,
            }

        # 取最近 5 個交易日累計
        recent_dates = sorted(complete_dates.index)[-5:]
        start_date = recent_dates[0]
        end_date = recent_dates[-1]

        recent_data = daily_net[daily_net["date"].isin(recent_dates)]
        net_by_shares = (
            recent_data.groupby("institution_label")["net_buy_shares"]
            .sum()
            .to_dict()
        )

        required_labels = ["外資", "投信", "自營商"]
        is_sync_buy = all(net_by_shares.get(label, 0) > 0 for label in required_labels)
        total_net_shares = sum(net_by_shares.get(label, 0) for label in required_labels)
        detail = "，".join(
            f"{label}{self._format_lots(net_by_shares.get(label, 0))}"
            for label in required_labels
        )
        resonance_text = "是共振買入" if is_sync_buy else "不是共振買入"
        report = (
            f"三大法人近 5 日累計 ({start_date} ~ {end_date}): {detail}；"
            f"合計{self._format_lots(total_net_shares)}，判定：{resonance_text}。"
        )
        return report, {
            "institutional_resonance_buy": is_sync_buy,
            "three_institution_net_buy": total_net_shares,
        }

    def analyze_flow(self, chip_data: List[Dict], price_df: pd.DataFrame) -> Tuple[str, Dict, int]:
        report_prefix = f"數據來源: {self.source}\n分析邏輯: {self.logic}\n結論: "

        if not chip_data:
            return f"{report_prefix}查無法人籌碼資料。", {}, 0

        df = pd.DataFrame(chip_data)

        # 防禦性檢查：確保必要欄位存在 (FinMind API v4 常用 'name' 或 'type')
        type_col = 'type' if 'type' in df.columns else 'name' if 'name' in df.columns else None
        base_columns = {'date', 'buy', 'sell'}

        if not type_col or not base_columns.issubset(df.columns):
            found_cols = set(df.columns)
            missing = base_columns - found_cols
            if not type_col:
                missing.add('type/name')
            return f"{report_prefix}籌碼資料格式不符，缺少欄位: {missing}。", {}, 0

        df["institution_label"] = df[type_col].apply(self._normalize_institution_label)

        # 篩選外資資料用於分析
        foreign_all = df[df["institution_label"] == '外資'].sort_values('date', ascending=True)
        resonance_report, resonance_flags = self._analyze_three_institution_resonance(df, type_col)

        # 依日期加總外資淨買賣股數
        foreign_daily = (
            foreign_all.copy()
            .assign(net_buy_shares=lambda x: pd.to_numeric(x['buy']) - pd.to_numeric(x['sell']))
            .groupby('date')['net_buy_shares']
            .sum()
            .sort_index(ascending=False)
        )

        if len(foreign_daily) < 5:
            return f"{report_prefix}籌碼資料不足(需5日)，無法判斷趨勢。{resonance_report}", resonance_flags, 0

        # ── 外資多維度分析 ──────────────────────────────────────────
        foreign_analysis = self._analyze_single_institution(foreign_daily)

        # 過去 5 天累計
        recent_5d_net_shares = float(foreign_daily.head(5).sum())
        total_sell_lots = abs(recent_5d_net_shares) / 1000

        # 過去 10 天累計（更貼近「連續賣超」語意；資料不足 10 日時退化为 5 日值）
        recent_10d_net_shares = float(foreign_daily.head(10).sum())
        total_sell_lots_10d = abs(recent_10d_net_shares) / 1000

        # 籌碼面圖表已依需求移除（見 _generate_chip_chart 之移除）
        image_md = ""

        # ── 三大法人個別趨勢 ────────────────────────────────────────
        individual_trends = self._analyze_individual_trends(df, type_col)
        trend_lines = []
        for label in ["外資", "投信", "自營商"]:
            t = individual_trends.get(label, {})
            trend_lines.append(f"  · {label}: {t.get('summary', '無資料')}")

        # ── 法人動向分歧偵測 ────────────────────────────────────────
        divergence = self._detect_institution_divergence(individual_trends)

        # ── 籌碼評分（多層級） ──────────────────────────────────────
        # 基礎分 100，根據多項訊號扣分。
        # 重校準：量級懲罰改用 10 日累計視窗並與嚴重度成比例（原 5 日視窗
        # 於 ≥1 萬張即封頂 −30，對「連續賣超數萬張」過寬）；連續賣超天數
        # 改為分級（取代固定 −10）。目標：外資 10 日賣超 ≥ 8 萬張時
        # chip_score 顯著低於 30，觸發結構性黃燈。
        chip_penalties = 0

        # 10 日累計賣超量級（張數 = 1000 股）
        is_net_selling = recent_5d_net_shares < 0
        if is_net_selling:
            if total_sell_lots_10d >= 60000:
                chip_penalties += 55
            elif total_sell_lots_10d >= 30000:
                chip_penalties += 45
            elif total_sell_lots_10d >= 10000:
                chip_penalties += 35
            elif total_sell_lots_10d >= 3000:
                chip_penalties += 25
            elif total_sell_lots_10d >= 1000:
                chip_penalties += 18
            else:
                chip_penalties += 12

        # 賣超天數比例 > 60%
        if foreign_analysis["sell_ratio"] > 60:
            chip_penalties += 10

        # 連續賣超天數分級（取代固定 −10）
        cons = foreign_analysis["max_consecutive_sell"]
        if cons >= 7:
            chip_penalties += 30
        elif cons >= 5:
            chip_penalties += 20
        elif cons >= 3:
            chip_penalties += 10

        chip_score = max(0, 100 - chip_penalties)

        big_foreign_sell = is_net_selling and (total_sell_lots >= 1000)
        extreme_sell = is_net_selling and (total_sell_lots >= 5000)

        chip_flags = {
            "big_foreign_sell": big_foreign_sell,
            "extreme_sell": extreme_sell,
            "sell_ratio": foreign_analysis["sell_ratio"],
            "max_consecutive_sell": foreign_analysis["max_consecutive_sell"],
            "foreign_net_sell_shares": recent_5d_net_shares,  # 負值表示淨賣超
            **resonance_flags,
        }

        # ── 組合報告 ────────────────────────────────────────────────
        detail_parts = [
            f"外資 5 日累計: {'賣超' if is_net_selling else '買超'} {abs(recent_5d_net_shares) / 1000:.0f} 張",
            f"外資動向: 佔 {foreign_analysis['total_days']} 日中的 "
            f"買超 {foreign_analysis['buy_days']} 日 / 賣超 {foreign_analysis['sell_days']} 日 "
            f"（賣超比例 {foreign_analysis['sell_ratio']:.0f}%）",
            f"最長連續賣超: {foreign_analysis['max_consecutive_sell']} 日",
            f"賣超分級: {foreign_analysis['grade']}",
        ]
        if divergence:
            detail_parts.append(f"⚠️ {divergence}")

        detail_section = "\n".join(detail_parts)
        trend_section = "三大法人個別趨勢:\n" + "\n".join(trend_lines)

        if extreme_sell:
            verdict = (f"🚨 外資強力賣出警告：5 日累計賣超 {total_sell_lots:.0f} 張，"
                       f"賣超比例 {foreign_analysis['sell_ratio']:.0f}%，最長連續賣超 {foreign_analysis['max_consecutive_sell']} 日！"
                       f"\n{detail_section}\n{trend_section}\n{resonance_report}")
        elif is_net_selling:
            verdict = (f"趨勢警告：外資近 5 日呈累計賣超 {total_sell_lots:.0f} 張。"
                       f"\n{detail_section}\n{trend_section}\n{resonance_report}")
        else:
            verdict = (f"籌碼動向平穩或呈現累計買盤支撐。"
                       f"\n{detail_section}\n{trend_section}\n{resonance_report}")

        return f"{report_prefix}{verdict}{image_md}", chip_flags, chip_score

class Orchestrator:
    """
    編排器：統合分析結論並寫入 Markdown 日誌
    """
    def __init__(self, log_path: str = "analysis_log.md"):
        self.fin_agent = QuarterlyFinancialAgent()
        self.tech_agent = MarketDynamicsAgent()
        self.chip_agent = InstitutionalInvestorAgent()
        self.macro_agent = GlobalMacroAgent()
        self.tracker_agent = InstitutionalTrackerAgent()
        self.signal_engine = SignalEngine()
        self.log_path = log_path

        # 建立圖表儲存目錄
        if not os.path.exists("charts"):
            os.makedirs("charts")

    def _df_to_md_table(self, df: pd.DataFrame) -> str:
        """
        將 DataFrame 轉換為 Markdown 表格字串。
        - 自動過濾色彩欄位
        - 營收 YoY 低於 20% 的數字加上 🟡 標記
        - 成交金額使用整數千分位，其餘百分比保留兩位小數
        """
        if df is None or df.empty:
            return ""
        # 排除用於 UI 顯示的色彩欄位
        display_cols = [c for c in df.columns if "色彩" not in c]
        display_df = df[display_cols].copy()

        # 找出營收 YoY 欄位的 index，以便從色彩欄位取得對應顏色
        rev_yoy_col = "營收 YoY (%)"
        rev_color_col = "營收 YoY 色彩"
        has_rev_color = rev_color_col in df.columns
        # 建立欄位名稱到 display_cols 索引的對應
        col_index = {c: i for i, c in enumerate(display_cols)}

        headers = display_df.columns.tolist()
        md_table = "| " + " | ".join(headers) + " |\n"
        md_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"

        rows = []
        for idx, row in display_df.iterrows():
            formatted_row = []
            for col in headers:
                val = row[col]
                if pd.isna(val) or val is None:
                    formatted_row.append("-")
                elif isinstance(val, (int, float)):
                    formatted_val = f"{int(val):,}" if "金額" in col else f"{val:.2f}"
                    # 營收 YoY 低於 20% 時加上 🟡 標記
                    if col == rev_yoy_col and has_rev_color:
                        color = df.loc[idx, rev_color_col] if idx in df.index else ""
                        if color in ("yellow", "red"):
                            formatted_val = f"🟡 {formatted_val}"
                    formatted_row.append(formatted_val)
                else:
                    formatted_row.append(str(val))
            rows.append("| " + " | ".join(formatted_row) + " |")

        return md_table + "\n".join(rows)

    def _build_financial_signals(self, quarterly_data: Dict, styled_df: pd.DataFrame) -> FinancialSignals:
        """
        從季度資料與儀表板 DataFrame 建構 FinancialSignals。
        """
        signals = FinancialSignals()

        # 從 quarterly_data 取得最新一季數據
        if quarterly_data:
            sorted_keys = sorted(quarterly_data.keys(), reverse=True)
            if sorted_keys:
                latest = quarterly_data[sorted_keys[0]]
                signals.latest_gross_margin = latest.get("gross_margin")
                signals.latest_operating_margin = latest.get("operating_margin")
                signals.latest_net_margin = latest.get("net_margin")
                signals.gross_drop = latest.get("gross_drop")
                signals.op_drop = latest.get("op_drop")
                signals.net_drop = latest.get("net_drop")

                # 檢查三率是否連續惡化（需要至少 3 季）
                if len(sorted_keys) >= 3:
                    q0 = quarterly_data[sorted_keys[0]]
                    q1 = quarterly_data[sorted_keys[1]]
                    q2 = quarterly_data[sorted_keys[2]]
                    for key in ["gross_margin", "operating_margin", "net_margin"]:
                        v0 = q0.get(key)
                        v1 = q1.get(key)
                        v2 = q2.get(key)
                        if v0 is not None and v1 is not None and v2 is not None:
                            if v0 < v1 < v2:
                                signals.margin_deteriorating = True
                                break

        # 從 styled_df 取得最新月營收 YoY
        if styled_df is not None and not styled_df.empty:
            rev_col = "營收 YoY (%)"
            if rev_col in styled_df.columns:
                valid_rev = pd.to_numeric(styled_df[rev_col], errors='coerce').dropna()
                if not valid_rev.empty:
                    signals.latest_revenue_yoy = float(valid_rev.iloc[-1])
                    # 檢查最近 3 個月是否連續下滑
                    if len(valid_rev) >= 3:
                        last_3 = valid_rev.tail(3)
                        if last_3.iloc[-1] < last_3.iloc[-2] < last_3.iloc[-3]:
                            signals.revenue_yoy_declining = True

        return signals

    def _build_market_sentiment_signals(
        self, trading_df: pd.DataFrame, market_sentiment_red: bool
    ) -> MarketSentimentSignals:
        """
        從交易資料建構市場情緒信號。

        評分邏輯：
        - 個股 + 大盤連三降（market_sentiment_red）→ 40 分
        - 僅個股連三降 → 60 分
        - 僅大盤連三降 → 70 分
        - 正常 → 100 分
        """
        signals = MarketSentimentSignals()

        if trading_df.empty or len(trading_df) < 3:
            return signals

        recent = trading_df.tail(10)
        tsmc_vals = recent['台積電成交金額'].tolist()[::-1]  # 最新在前
        mkt_vals = recent['大盤成交金額'].tolist()[::-1]

        # 檢查連三降
        def _has_three_consecutive_decline(values):
            if len(values) < 3:
                return False
            for i in range(len(values) - 2):
                if values[i] < values[i + 1] < values[i + 2]:
                    return True
            return False

        tsmc_declining = _has_three_consecutive_decline(tsmc_vals)
        mkt_declining = _has_three_consecutive_decline(mkt_vals)

        signals.tsmc_volume_declining = tsmc_declining
        signals.market_volume_declining = mkt_declining
        signals.triple_decline = market_sentiment_red

        if market_sentiment_red:
            signals.score = 40
            signals.volume_trend = "declining"
        elif tsmc_declining and mkt_declining:
            signals.score = 50
            signals.volume_trend = "declining"
        elif tsmc_declining:
            signals.score = 60
            signals.volume_trend = "declining"
        elif mkt_declining:
            signals.score = 70
            signals.volume_trend = "declining"
        else:
            signals.score = 100
            signals.volume_trend = "normal"

        return signals

    def _get_quarterly_fx_averages(self) -> Dict[str, float]:
        """
        取得最新季與前一季的 USD/TWD 平均匯率。
        使用 SAL YahooFinanceProvider 取得即時匯率。
        回傳 {"latest": float, "previous": float}，若取得失敗則回傳空 dict。
        """
        try:
            yahoo = get_yahoo()
            latest = yahoo.get_usd_twd_rate()
            if latest is None:
                return {}

            # 簡化：目前只取即時匯率，前一季用同一個值近似
            # 未來可擴展為取得歷史匯率
            return {"latest": latest, "previous": latest}
        except Exception:
            return {}

    def run_full_analysis(self, quarterly_data: Dict, trading_df: pd.DataFrame, chip_data: List[Dict],
                          styled_df: pd.DataFrame,
                          revenue_by_date: Optional[Dict[str, float]] = None) -> str:
        """
        執行完整分析並回傳 dashboard_summary 字串。
        綜合得分燈號邏輯統一由 signal_engine 處理。
        """
        # ── Step 0: 取得匯率季度均值 ──
        fx_averages = self._get_quarterly_fx_averages()

        # ── Step 1: 各 Agent 分析（並行） ──
        # 七個 Agent 分析彼此獨立、無共享可變狀態，且各自走統一快取層，
        # 故以 ThreadPoolExecutor 並行執行，總耗時趨近於最慢單一 Agent。
        # tw_price 供 macro.analyze_global_risk 使用，先算好再並行。
        tw_price = trading_df['台積電收盤價'].iloc[-1] if not trading_df.empty else 0

        with ThreadPoolExecutor(max_workers=7) as executor:
            f_fin = executor.submit(self.fin_agent.analyze_margins, quarterly_data)
            f_fin_struct = executor.submit(
                self.fin_agent.build_structured_report,
                quarterly_data=quarterly_data,
                fx_averages=fx_averages,
            )
            f_tech = executor.submit(self.tech_agent.analyze_sentiment, trading_df)
            f_chip = executor.submit(self.chip_agent.analyze_flow, chip_data, trading_df)
            f_macro = executor.submit(self.macro_agent.analyze_global_risk, tw_price)
            f_bigtech = executor.submit(self.macro_agent.analyze_bigtech_fundamentals, quarterly_data)
            f_tracker = executor.submit(self.tracker_agent.analyze_all_institutions)

            fin_report = f_fin.result()
            fin_report_structured = f_fin_struct.result()
            tech_report, tech_flags, tech_scores, vol_price_divergence = f_tech.result()
            chip_report, chip_flags, chip_score = f_chip.result()
            macro_report, macro_score = f_macro.result()
            bigtech_data, bigtech_report = f_bigtech.result()
            tracker_all_data, tracker_report = f_tracker.result()

        # ── Step 2: 建構信號 ──
        financial_signals = self._build_financial_signals(quarterly_data, styled_df)
        bigtech_signals = BigTechSignals(
            capex_growing_count=bigtech_data.get("capex_growing_count", 0),
            capex_valid_count=bigtech_data.get("capex_valid_count", 0),
            nvda_revenue_yoy=bigtech_data.get("nvda_revenue_yoy"),
            nvda_revenue_yoy_quarters=bigtech_data.get("nvda_revenue_yoy_quarters", []),
        )
        tech_signals = TechnicalSignals(scores=tech_scores, flags=tech_flags)
        chip_flags["vol_price_divergence"] = vol_price_divergence
        chip_signals = ChipSignals(score=chip_score, flags=chip_flags)

        # ── Step 3: Signal Engine 整合計算 ──
        # 註：市場情緒（量能）已移出綜合燈號計算，不參與燈號判定。
        result = self.signal_engine.analyze(
            financial_signals, bigtech_signals, tech_signals, chip_signals
        )

        # ── Step 4: 組合報告 ──
        comprehensive_score = result.comprehensive_score
        alert_emoji = result.alert_emoji
        alert_label = result.alert_label
        alert_level = result.alert_level
        alert_message = result.alert_message

        # 建構 score_summary（顯示新權重；市場情緒已移出綜合燈號計算）
        w = CONFIG.weights
        breakdown = result.details["breakdown"]
        score_summary = (
            f"● 財務面({result.financial_score:.0f})*{w.financial*100:.0f}% = {breakdown['financial']:.1f}/{w.financial*100:.0f}\n"
            f"● 大廠基本面({result.bigtech_score:.0f})*{w.bigtech*100:.0f}% = {breakdown['bigtech']:.1f}/{w.bigtech*100:.0f}\n"
            f"● 技術面({result.tech_score:.0f})*{w.tech*100:.0f}% = {breakdown['tech']:.1f}/{w.tech*100:.0f}\n"
            f"● 簱碼面({chip_score})*{w.chip*100:.0f}% = {breakdown['chip']:.1f}/{w.chip*100:.0f}\n"
            f"● 綜合健康得分: {comprehensive_score:.1f}/100"
        )

        # EPS 趨勢摘要
        eps_summary = ""
        if quarterly_data:
            sorted_eps_keys = sorted(quarterly_data.keys(), reverse=True)
            eps_vals = []
            for k in sorted_eps_keys[:4]:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    eps_vals.append((f"{k[0]}Q{k[1]}", ev))
            if len(eps_vals) >= 2:
                eps_arrows = " → ".join(f"{label}: {val:.2f}" for label, val in eps_vals)
                if eps_vals[0][1] > eps_vals[-1][1]:
                    trend_icon = "⬆"
                elif eps_vals[0][1] < eps_vals[-1][1]:
                    trend_icon = "⬇"
                else:
                    trend_icon = "→"
                eps_summary = f"\n   EPS 趨勢：{eps_arrows}（{trend_icon}）"

        # 控制台輸出
        print("\n=== [AI Agent 聯手分析報告] ===")
        print(f"[宏觀專家] > {macro_report}")
        print()
        print(f"[財務專家] > {fin_report}{eps_summary}")
        print()
        print(f"[技術專家] > {tech_report}")
        print()
        print(f"[籌碼專家] > {chip_report}")
        print()
        print(f"[大廠基本面] > {bigtech_report}")
        print()
        print(f"[機構 13F] > {tracker_report}")
        print()

        # 市場情緒（量能）已移出燈號計算，僅供觀察，不參與判定
        # 註：量能為落後指標，會在技術/籌碼已轉弱時仍因「量能未萎縮」顯示綠燈，造成失真。

        print(f"{'='*50}")
        print(f"{alert_emoji} 燈號：{alert_label}")
        print(f"   {alert_message}")
        print(f"{'='*50}")

        # 特殊訊號警示
        if result.reversal_advanced:
            print(f"\033[1;31;40m[🚨🚨🚨 高強度轉折訊號 🚨🚨🚨]\033[0m")
            print(f"\033[1;31m   20MA 轉負 + 月線破 MA12 + 外資大額賣超 + 布林通道壓縮後破位\033[0m")
        elif result.reversal_signal:
            print(f"\033[1;33m[！！！轉折訊號提醒！！！]\033[0m")
            print(f"\033[1;33m   20MA 轉負 + 月線破 MA12 + 外資大額賣超\033[0m")

        if result.double_warning:
            fin_warnings = result.details.get("financial_warnings", [])
            print(f"\033[1;37;41m【！嚴重警示！】基本面與技術面同時轉弱\033[0m")
            for fw in fin_warnings:
                print(f"\033[1;31m   ⚠ {fw}\033[0m")

        # 財務面警告（如果有的話）
        fin_warnings = result.details.get("financial_warnings", [])
        if fin_warnings and not result.double_warning:
            print(f"\n⚠️ 財務面警示:")
            for fw in fin_warnings:
                print(f"   · {fw}")

        # 大廠基本面警告（如果有的話）
        bigtech_warnings = result.details.get("bigtech_warnings", [])
        if bigtech_warnings:
            print(f"\n⚠️ 大廠基本面警示:")
            for bw in bigtech_warnings:
                print(f"   · {bw}")

        # ── 本益比警告 ──────────────────────────────────────────
        # 計算本益比 = 股價 / 過去四季 EPS 加總
        current_price = tw_price  # 已取得於 Step 1
        if quarterly_data and current_price > 0:
            sorted_eps_keys = sorted(quarterly_data.keys(), reverse=True)
            trailing_4q_eps = 0.0
            eps_count = 0
            for k in sorted_eps_keys[:4]:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    trailing_4q_eps += ev
                    eps_count += 1
            if eps_count >= 2 and trailing_4q_eps > 0:
                pe_ratio = current_price / trailing_4q_eps
                # 判斷各面向是否同時偏空（量能/情緒已移出，不再參與）
                has_vol_price_div = chip_flags.get("vol_price_divergence", False)
                has_chip_sell = chip_flags.get("big_foreign_sell", False) or chip_flags.get("extreme_sell", False)

                if pe_ratio > 31 and has_vol_price_div and has_chip_sell:
                    print(f"\033[1;37;41m【🚨 高檔全面警示 🚨】\033[0m")
                    print(f"\033[1;31m   本益比 {pe_ratio:.1f} 倍（股價 {current_price:.0f} / 過去四季 EPS {trailing_4q_eps:.2f}）> 31 倍\033[0m")
                    print(f"\033[1;31m   + 技術面量價背離\033[0m")
                    print(f"\033[1;31m   + 籌碼面外資賣超\033[0m")
                    print(f"\033[1;33m   → 建議：高檔全面偏空，留意追高風險\033[0m")
                elif pe_ratio > 31:
                    print(f"\n⚠️ 本益比偏高（>31 倍）：{pe_ratio:.1f} 倍（股價 {current_price:.0f} / 過去四季 EPS {trailing_4q_eps:.2f}）")

        # 燈號顏色顯示綜合分數
        console_summary = score_summary
        score_str = f"{comprehensive_score:.1f}/100"
        if alert_level == "green":
            console_summary = console_summary.replace(score_str, f"\033[1;32m🟢 {score_str}\033[0m")
        elif alert_level == "yellow":
            console_summary = console_summary.replace(score_str, f"\033[1;33m🟡 {score_str}\033[0m")
        else:
            console_summary = console_summary.replace(score_str, f"\033[1;31m🔴 {score_str}\033[0m")

        print(f"\n--- 綜合評分總結 ---\n{console_summary}\n------------------")

        # 建立 dashboard_summary（統一燈號）
        dashboard_summary = f"{alert_emoji} {alert_label} | {alert_message}"

        # 建立 Markdown 表格
        fin_table_md = self._df_to_md_table(styled_df)
        vol_table_md = self._df_to_md_table(trading_df.tail(10)[["日期", "台積電成交金額", "大盤成交金額"]])

        # 本益比警告（寫入日誌用，不含 ANSI escape code）
        pe_warning_md = ""
        if quarterly_data and current_price > 0:
            sorted_eps_keys = sorted(quarterly_data.keys(), reverse=True)
            trailing_4q_eps = 0.0
            eps_count = 0
            for k in sorted_eps_keys[:4]:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    trailing_4q_eps += ev
                    eps_count += 1
            if eps_count >= 2 and trailing_4q_eps > 0:
                pe_ratio = current_price / trailing_4q_eps
                has_vol_price_div = chip_flags.get("vol_price_divergence", False)
                has_chip_sell = chip_flags.get("big_foreign_sell", False) or chip_flags.get("extreme_sell", False)

                if pe_ratio > 31 and has_vol_price_div and has_chip_sell:
                    pe_warning_md = (
                        f"\n\n### 🚨 高檔全面警示\n\n"
                        f"> **本益比 {pe_ratio:.1f} 倍**（股價 {current_price:.0f} / 過去四季 EPS {trailing_4q_eps:.2f}）> 31 倍  \n"
                        f"> + 技術面量價背離  \n"
                        f"> + 籌碼面外資賣超  \n"
                        f"> → **建議：高檔全面偏空，留意追高風險**\n"
                    )
                elif pe_ratio > 31:
                    pe_warning_md = (
                        f"\n\n### ⚠️ 本益比偏高（>31 倍）\n\n"
                        f"> 本益比 **{pe_ratio:.1f} 倍**（股價 {current_price:.0f} / 過去四季 EPS {trailing_4q_eps:.2f}）\n"
                    )

        # ── Step 5: 建構產業分析框架章節 ──
        industry_analysis_md = self._build_industry_analysis_section(
            quarterly_data=quarterly_data,
            styled_df=styled_df,
            chip_flags=chip_flags,
            chip_score=chip_score,
            tech_flags=tech_flags,
            tech_scores=tech_scores,
            macro_report=macro_report,
            bigtech_data=bigtech_data,
            result=result,
            tw_price=tw_price,
            fx_averages=fx_averages,
        )

        # 寫入日誌（重構版：直接產出結構化報告）
        self._append_to_log(
            dashboard_summary=dashboard_summary,
            fin_report=fin_report,
            tech_report=tech_report,
            chip_report=chip_report,
            macro_report=macro_report,
            bigtech_report=bigtech_report,
            score_summary=score_summary,
            fin_table=fin_table_md,
            vol_table=vol_table_md,
            pe_warning_md=pe_warning_md,
            industry_analysis_md=industry_analysis_md,
            fin_report_structured=fin_report_structured,
            tracker_report=tracker_report,
            quarterly_data=quarterly_data,
            styled_df=styled_df,
            chip_flags=chip_flags,
            chip_score=chip_score,
            tech_flags=tech_flags,
            tech_scores=tech_scores,
            bigtech_data=bigtech_data,
            result=result,
            tw_price=tw_price,
            fx_averages=fx_averages,
            revenue_by_date=revenue_by_date or {},
            price_df=trading_df,
        )
        print(f"\n[系統] 分析結果已同步寫入至 {self.log_path}")

        return dashboard_summary

    def _estimate_earnings_date(self, today: dt.date) -> Tuple[str, int, str]:
        """
        根據当前日期估算最近的台積電法說會日期與距離天數。
        台積電法說會約在每年 1、4、7、10 月的第三週週四。
        回傳：(法說會日期字串, 距離天數, 法說會季度描述)
        """
        import calendar
        # 法說會月份：1, 4, 7, 10
        earnings_months = [1, 4, 7, 10]
        candidates = []
        for m in earnings_months:
            # 找該月第三週的週四
            cal = calendar.monthcalendar(today.year, m)
            thursdays = [week[calendar.THURSDAY] for week in cal if week[calendar.THURSDAY] != 0]
            if len(thursdays) >= 3:
                cal_date = dt.date(today.year, m, thursdays[2])  # 第三個週四
                candidates.append(cal_date)

        # 找最近的法說會（已過或未來）
        past = [d for d in candidates if d <= today]
        future = [d for d in candidates if d > today]

        if future:
            nearest = future[0]
            days_away = (nearest - today).days
            desc = f"Q{nearest.month // 3 if nearest.month % 3 != 0 else nearest.month // 3} 法說會"
            return nearest.isoformat(), days_away, desc
        elif past:
            nearest = past[-1]
            days_away = (today - nearest).days
            desc = f"Q{(nearest.month - 1) // 3 + 1} 法說會後"
            return nearest.isoformat(), -days_away, desc
        else:
            return "未知", 0, "法說會日期未定"

    def _revenue_yoy_dynamic_trigger(self, revenue_by_date: Optional[Dict[str, float]]) -> str:
        """
        以「近 12 個月月營收 YoY 的動態均值 ± 標準差」取代固定 10% 門檻。

        回傳一段文字，描述觸發轉空的月營收 YoY 條件；若資料不足 13 個月
        （無法計算至少 12 個 YoY 樣本）則回退到保守的固定門檻說明。
        """
        if not revenue_by_date or len(revenue_by_date) < 13:
            return "月營收 YoY 轉負或較前月顯著下滑（資料不足 13 個月，暫採保守門檻）"
        try:
            months = sorted(revenue_by_date.keys())
            yoys = []
            for i in range(1, len(months)):
                cur = revenue_by_date.get(months[i])
                prev = revenue_by_date.get(months[i - 1])
                if cur is not None and prev not in (None, 0):
                    yoys.append((cur - prev) / prev * 100.0)
            if len(yoys) < 12:
                return "月營收 YoY 轉負或較前月顯著下滑（YoY 樣本不足，暫採保守門檻）"
            window = yoys[-12:]
            mean = sum(window) / len(window)
            var = sum((x - mean) ** 2 for x in window) / len(window)
            std = var ** 0.5
            # 觸發：較近 12 月均值下滑超過 1 個標準差（且均值本身為正時才看下滑）
            threshold = mean - std
            return (
                f"月營收 YoY 較近 12 月均值（{mean:.1f}%）下滑超過 1 個標準差"
                f"（σ={std:.1f}%，觸發線 ≈ {threshold:.1f}%）"
            )
        except Exception:
            return "月營收 YoY 轉負或較前月顯著下滑（計算異常，暫採保守門檻）"

    def _build_industry_analysis_section(
        self,
        quarterly_data: Dict,
        styled_df: pd.DataFrame,
        chip_flags: Dict,
        chip_score: int,
        tech_flags: Dict,
        tech_scores: Dict,
        macro_report: str,
        bigtech_data: Dict,
        result,
        tw_price: float,
        fx_averages: Optional[Dict[str, float]] = None,
    ) -> str:
        """
        建構「五、產業分析框架與深度解讀」章節。

        涵蓋：
        0. 法說會前後行為模式定位
        1. ADR 溢價解讀修正（匯率預期 / 市場准入 / 做空成本，非純需求指標）
        2. 客戶集中度風險（Apple ~25%、NVIDIA ~10-12%）
        3. 財務深度增強（CoWoS / 產能利用率 / EPS 拆解 / 營收 YoY 基期效應）
        4. 技術面與籌碼面矛盾整合
        5. 量化風險提示（含歷史校準的轉空觸發條件）
        6. 產業比較基準（錨定 consensus EPS 的 PEG）
        7. 分析師整合敘事（各維度因果鏈）
        """
        lines = []
        lines.append("## 📊 五、產業分析框架與深度解讀")
        lines.append("")
        lines.append("---")

        # ── 0. 法說會前後行為模式 ────────────────────────────────────
        lines.append("")
        lines.append("### 0️⃣ 法說會框架定位")
        lines.append("")

        from datetime import date as _date
        today = _date.today()
        earnings_str, days_offset, earnings_desc = self._estimate_earnings_date(today)

        if days_offset > 0 and days_offset <= 45:
            phase = f"法說會前 **{days_offset}** 天（{earnings_desc}：{earnings_str}）"
            de_risk_note = (
                "目前處於法說會前的 **de-risking 窗口**。外資在法說會前的系統性賣超有兩種典型模式：\n"
                "1. **先賣後買**：提前減碼保守部位，待法說會釋出正向展望後回補\n"
                "2. **先買後賣**：提前押注法說會利多，法說會後利多出盡獲利了結\n\n"
                "**判斷關鍵：** 觀察外資賣超是否伴隨選擇權 Put/Call Ratio 同步走高。\n"
                "若 Put/Call Ratio 走高 → 外資在買保險避險（模式 1），法說會後可能回補。\n"
                "若 Put/Call Ratio 持平或走低 → 外資真實看法轉空（非 de-risking），需提高警覺。"
            )
        elif days_offset < 0 and abs(days_offset) <= 30:
            phase = f"法說會後 **{abs(days_offset)}** 天（{earnings_desc}：{earnings_str}）"
            de_risk_note = (
                "目前處於法說會後窗口。法說會後的籌碼行為更能反映真實看法：\n"
                "若法說會後外資持續賣超 → 代表法說會內容未能消除疑慮，屬偏空訊號。\n"
                "若法說會後外資回補 → 代表法說會確認或上修展望，偏多。"
            )
        else:
            phase = f"法說會間距期（最近法說會：{earnings_str}，{earnings_desc}）"
            de_risk_note = "目前不處於法說會窗口，外資行為解讀不受法說會效應干擾。"

        lines.append(f"**分析基準日：** {today.isoformat()}")
        lines.append(f"**法說會定位：** {phase}")
        lines.append("")
        lines.append(de_risk_note)
        lines.append("")

        # ── 1. ADR 溢價解讀修正 ──────────────────────────────────────
        lines.append("")
        lines.append("### 1️⃣ ADR 溢價解讀修正")
        lines.append("")
        lines.append("**當前 ADR 分析結果（來自宏觀專家報告）：**")
        adr_lines = [l.strip() for l in macro_report.split('\n') if l.strip() and
                     ('ADR' in l or '溢價' in l or '折價' in l or '折算' in l or 'TSM' in l or '匯率' in l)]
        if adr_lines:
            for al in adr_lines:
                lines.append(f"> {al}")
        lines.append("")
        lines.append("**⚠️ 重要方法論修正：**")
        lines.append("")
        lines.append("ADR 溢價/折價**不能直接等同於基本面需求強弱**。溢價的形成機制包含多重因素：")
        lines.append("")
        lines.append("| 因素 | 對 ADR 溢價的影響 | 解讀方向 |")
        lines.append("|------|-------------------|----------|")
        lines.append("| **匯率預期** | 若市場預期 USD/TWD 走強，ADR 折算後自然偏高 | 反映外匯市場預期，非需求 |")
        lines.append("| **台股准入限制** | 海外資金無法直接買台股，需透過 ADR 曝光 | 溢價反映准入溢價，非超額需求 |")
        lines.append("| **做空成本** | ADR 做空借券成本高，空方不易施壓 | 溢價可能只是賣方流動性不足 |")
        lines.append("| **流動性差異** | ADR 交易量遠小於台股，少量買盤即可推升 | 結構性溢價常態 |")
        lines.append("| **AI 主題溢價** | 美股市場對 AI 概念股的定價較台股積極 | 若伴隨 NVIDIA 財報上修 + 台股同步走強，才具參考價值 |")
        lines.append("")
        lines.append("> **結論：** ADR 溢價 > 5% 時，需區分「匯率驅動」與「主題溢價」兩個維度。")
        lines.append("> 若溢價主要由匯率預期帶動（USD/TWD 趨勢走強），則不能作為加碼依據。")
        lines.append("> 更精確的需求面驗證指標：追蹤 NVIDIA 財報後營收指引上修幅度、Apple 晶片訂單變化，")
        lines.append("> 而非以 SOX 指數替代（SOX 包含 AMD/Broadcom/Marvell，無法精確映射台積電 AI 需求）。")
        lines.append("")

        # ── 2. 客戶集中度風險 ────────────────────────────────────────
        lines.append("### 2️⃣ 客戶集中度風險")
        lines.append("")
        lines.append("**台積電前兩大客戶佔營收比重：**")
        lines.append("")
        lines.append("| 客戶 | 營收佔比 | 主要產品 | 關鍵風險因子 |")
        lines.append("|------|----------|----------|--------------|")
        lines.append("| **Apple** | ~25% | A 系列/M 系列晶片 | iPhone 17 備貨動能、自研晶片進度 |")
        lines.append("| **NVIDIA** | ~10-12% | GPU/AI Accelerator | Blackwell 出貨時程、CoWoS 訂單排程 |")
        lines.append("")
        lines.append("**單點風險分析：**")
        lines.append("")
        lines.append("- **Apple 風險**：若 iPhone 17 銷售不如預期導致砍單，或 Apple 自研晶片（如 A19/M5）提前轉片三星，台積電營收將直接承受 5-10% 的下行壓力。目前 Apple 佔比已從 2023 年的 23% 升至 ~25%，集中度不降反升。")
        lines.append("- **NVIDIA 風險**：Blackwell（B200/B300）的 CoWoS 封裝需求是台積電 2025-2026 年最關鍵的營收驅動力。若 Blackwell 出貨時程遞延（良率問題或客戶設計變更），將直接衝擊 N3/N5 製程的產能利用率。")
        lines.append("- **分散化進展**：高通（Qualcomm）與 AMD 的佔比合計約 8-10%，但不足以抵消 Apple 或 NVIDIA 單一客戶的砍單衝擊。")
        lines.append("")
        lines.append("> 📌 **結論**：客戶集中度風險是台積電最大的單點脆弱性。三率上升的可持續性論述，")
        lines.append("> 必須建立在「Apple 與 NVIDIA 訂單不出現重大變數」的前提之上。")
        lines.append("")

        # ── 3. 財務深度增強 ──────────────────────────────────────────
        lines.append("### 3️⃣ 財務分析深度增強")
        lines.append("")

        # 3a. CoWoS 與先進製程
        lines.append("**🔧 CoWoS 供需與先進製程驅動力：**")
        lines.append("")
        lines.append("目前台積電最關鍵的財務驅動力不僅是三率趨勢，更在於：")
        lines.append("")
        lines.append("- **CoWoS 供需缺口**：AI 伺服器（GB200/GB300）對 CoWoS-L 需求的爆炸性成長，使 CoWoS 產能成為全產業鏈的瓶頸。若法說會釋放 CoWoS 擴產進度超前，則毛利率上行具備結構性支撐。")
        lines.append("- **N3/N2 製程良率**：N3E 已進入放量階段，N2 預計 2025 H2 量產。良率爬坡進度直接影響客戶（Apple/NVIDIA）的晶片成本結構，進而影響代工定價能力。")
        lines.append("- **三率上升的本質**：若毛利率上升主要由「高毛利製程（N3/N5）佔比提升」驅動，這代表產品組合優化，是可持續的；若僅因「產能利用率拉滿的規模經濟」驅動，則一旦需求反轉，三率回落速度也會很快。")
        lines.append("")

        # 3b. EPS 拆解
        lines.append("**💰 EPS 結構拆解（區分可持續性）：**")
        lines.append("")
        if quarterly_data:
            sorted_keys = sorted(quarterly_data.keys(), reverse=True)
            eps_vals = []
            for k in sorted_keys[:4]:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    eps_vals.append((f"{k[0]}Q{k[1]}", ev))
            if len(eps_vals) >= 2:
                eps_arrows = " → ".join(f"{label}: {val:.2f}" for label, val in eps_vals)
                lines.append(f"   - 過去四季 EPS：{eps_arrows}")
                latest_eps = eps_vals[0][1]
                prior_eps = eps_vals[-1][1]
                if latest_eps > prior_eps * 1.15:
                    jump_pct = (latest_eps / prior_eps - 1) * 100 if prior_eps > 0 else 0
                    lines.append(f"   - ⚠️ EPS 從 {eps_vals[-1][0]} 的 {prior_eps:.2f} 跳升至 {eps_vals[0][0]} 的 {latest_eps:.2f}（+{jump_pct:.0f}%），需進一步拆解原因：")
                    lines.append(f"     - **情境 A：美元升值匯兌利益** → USD/TWD 從 32.5 升至 33.x 可能貢獻每股 1-2 元匯損減少")
                    lines.append(f"     - **情境 B：AI Server 急單貢獻** → NVIDIA/AMD CoWoS 訂單放量，高單價大晶片面積拉升 ASP")
                    lines.append(f"     - **情境 C：業外收益** → KFA/JV 投資利益、一次性授權金等")
                    lines.append(f"     - 📌 **解讀原則**：若 EPS 增長主要來自情境 C（業外），則不具備持續性")
                else:
                    lines.append(f"   - EPS 變化幅度在合理區間，無異常跳升")
            lines.append("")
        lines.append("**📌 建議修法：** 未來報告應在 EPS 趨勢旁加註「匯損/匯益預估值」及「業外收益佔比」，以利判斷盈餘品質。")
        lines.append("")

        # 3c. 匯率逆風量化分析
        lines.append("**💱 匯率逆風量化分析：**")
        lines.append("")
        # 從 fx_averages 取得季度均值變化
        fx_latest = None
        fx_previous = None
        if fx_averages:
            fx_latest = fx_averages.get("latest")
            fx_previous = fx_averages.get("previous")
        if fx_latest is not None and fx_previous is not None:
            fx_delta = fx_latest - fx_previous
            fx_pct = (fx_delta / fx_previous) * 100 if fx_previous != 0 else 0
            lines.append(f"   - 最新季 USD/TWD 均值：**{fx_latest:.2f}** vs 前一季均值：**{fx_previous:.2f}**（變化 {fx_delta:+.2f}，{fx_pct:+.1f}%）")
            if fx_delta < -0.5:
                # 台幣升值逆風
                margin_impact = fx_delta * 0.4  # 粗估每 1 單位變化影響 0.4pp
                eps_impact = fx_delta * 0.65
                lines.append(f"   - 🔴 **台幣升值逆風**：估計拖累毛利率約 {abs(margin_impact):.1f}pp，影響 EPS 約 {eps_impact:+.2f} 元")
                lines.append(f"   - 💡 **關鍵發現**：在台幣升值逆風下，毛利率仍從 59.5% 升至 66.2%，代表本業獲利能力比表面數字更強。")
                lines.append(f"     若排除匯率逆風，本業毛利率估計可達 **{66.2 + abs(margin_impact):.1f}%** 以上。")
                lines.append(f"     **這意味著 Pricing Power（定價能力）被匯率噪音掩蓋，實際的結構性改善比財報數字更強。**")
            elif fx_delta > 0.5:
                margin_impact = fx_delta * 0.4
                eps_impact = fx_delta * 0.65
                lines.append(f"   - 🟢 **台幣貶值順風**：估計助力毛利率約 +{margin_impact:.1f}pp，貢獻 EPS 約 +{eps_impact:.2f} 元")
                lines.append(f"   - ⚠️ 毛利率改善部分受惠於匯率順風，若未來台幣反轉升值，毛利率將面臨額外下行壓力。")
            else:
                lines.append(f"   - ⚪ 匯率波動中性，對毛利率與 EPS 影響可忽略。")
        else:
            lines.append(f"   - ⚪ 匯率季度均值資料不足，無法進行量化分析。")
        lines.append("")

        # 3d. 營收 YoY 基期效應
        lines.append("**📅 營收基期效應解讀：**")
        lines.append("")
        if styled_df is not None and not styled_df.empty:
            rev_col = "營收 YoY (%)"
            if rev_col in styled_df.columns:
                valid_rev = pd.to_numeric(styled_df[rev_col], errors='coerce').dropna()
                if not valid_rev.empty:
                    latest_rev = float(valid_rev.iloc[-1])
                    lines.append(f"   - 最新月營收 YoY：**{latest_rev:.1f}%**")
                    if latest_rev > 30:
                        lines.append(f"   - 高 YoY 需注意**基期效應**：若對應前一年月份為低基期（例如 2025-04 受手機/PC 庫存調整影響），則高 YoY 部分反映的是基期低而非真實需求爆發")
                        lines.append(f"   - **建議對比**：應以「近 3 個月營收累計金額 vs. 去年同期累計」來消除單月基期雜訊")
                    elif latest_rev < 20:
                        lines.append(f"   - YoY 僅 {latest_rev:.1f}%，低於 20% 黃線標準，需確認是否為季節性因素")
                    else:
                        lines.append(f"   - YoY {latest_rev:.1f}%，處於合理成長區間")
        lines.append("")

        # ── 4. 技術面與籌碼面矛盾整合 ────────────────────────────────
        lines.append("### 4️⃣ 技術面與籌碼面矛盾整合")
        lines.append("")
        lines.append("**現況描述：**")
        lines.append("")

        ma_status = ""
        if tech_flags.get("position_zone"):
            zone = tech_flags.get("position_zone", "未知")
            zone_score = tech_flags.get("position_zone_score", 50)
            ma_status = f"技術面處於 **{zone}**（綜合分數 {zone_score:.0f}/100）"

        foreign_5d = chip_flags.get("big_foreign_sell", False)
        sell_ratio = chip_flags.get("sell_ratio", 0)
        extreme_sell = chip_flags.get("extreme_sell", False)
        consecutive_sell = chip_flags.get("max_consecutive_sell", 0)

        if ma_status:
            lines.append(f"- {ma_status}")

        if extreme_sell:
            lines.append(f"- 籌碼面：**外資 5 日大幅賣超**，5 日累計達嚴重級別，連續賣超 {consecutive_sell} 日")
        elif foreign_5d:
            lines.append(f"- 籌碼面：外資 5 日累計賣超，賣超天數佔比 {sell_ratio:.0f}%，最長連續 {consecutive_sell} 日")
        else:
            lines.append(f"- 籌碼面：外資動向無異常大量賣超")

        tech_bullish = False
        if tech_scores:
            tech_avg = sum(tech_scores.values()) / max(len(tech_scores), 1)
            tech_bullish = tech_avg > 70

        chip_bearish = chip_score < 70

        lines.append("")
        lines.append("**🔍 矛盾分析：**")
        lines.append("")

        if ma_status and "高檔" in ma_status and (foreign_5d or extreme_sell):
            lines.append("當技術面顯示高檔偏多但外資持續賣超，這是一個**經典的籌碼面逆風信號**。")
            lines.append("")
            lines.append("外資在賣，誰在接？可能來源：")
            lines.append("")
            lines.append("| 來源 | 可能性 | 影響 |")
            lines.append("|------|--------|------|")
            lines.append("| **散戶（自然人）** | 高 | 散戶在高檔承接外資拋售，歷史上是偏空信號 |")
            lines.append("| **其他外資帳戶** | 中 | Passive fund 調倉 vs. Active fund 減碼，方向一致但不同帳戶 |")
            lines.append("| **公司庫藏股** | 低 | 需查詢每日公告 |")
            lines.append("| **ETF 被動買盤** | 中 | 0050/00881 等高頻再平衡可能在吸收外資賣壓 |")
            lines.append("")
            lines.append("> **關鍵問題：** 若外資賣超的缺口最終由散戶承接（可從融資餘額變化驗證），")
            lines.append("> 則即便技術面仍呈現多頭排列，籌碼結構已開始惡化，後續修正風險升高。")
            lines.append("> **建議操盤手：** 追蹤每日融資餘額變化，若融資持續增加且外資持續賣超，需提高警覺。")
        elif tech_bullish and not chip_bearish:
            lines.append("技術面與籌碼面目前方向一致（偏多），無需特別矛盾解讀。")
        elif not tech_bullish and chip_bearish:
            lines.append("技術面偏弱且籌碼面外資賣超，**雙重偏空**，需嚴格控制部位。")
        else:
            lines.append("技術面與籌碼面訊號混雜，建議縮小部位、等待方向明確後再行操作。")

        lines.append("")

        # ── 5. 量化風險提示 ──────────────────────────────────────────
        lines.append("### 5️⃣ 量化風險提示與操作建議")
        lines.append("")
        lines.append("**🎯 具體風險管理框架：**")
        lines.append("")

        support_level = 0
        resistance_level = 0
        if tw_price > 0:
            support_level = int(tw_price * 0.85)
            resistance_level = int(tw_price * 1.08)

            lines.append("| 操作層級 | 建議 | 觸發條件 |")
            lines.append("|----------|------|----------|")
            lines.append(f"| **短線（1-2 週）** | **觀察不追高** | 若外資連續 3 日回補 → 轉為中性偏多 |")
            lines.append(f"| **中線（1-3 月）** | **等待拉回** | 若跌破 20MA 且量縮 → 確認轉弱 |")
            lines.append(f"| **長線（6 月+）** | **N2 量產邏輯不變則續抱** | 若法說會確認 N2 量產遞延 → 重新評估 |")
            lines.append("")
            lines.append(f"| 價位 | 意義 | 操作建議 |")
            lines.append(f"|------|------|----------|")
            lines.append(f"| **{tw_price:.0f}**（現價）| 當前價位 | 不追高，觀察 |")
            if support_level > 0:
                lines.append(f"| **{support_level}**（-15%）| 近 60 日支撐區 | 若拉回至此可分批佈局 |")
            lines.append(f"| **跌破 20MA** | 短期趨勢轉弱 | 減碼 30-50% |")
            if resistance_level > 0:
                lines.append(f"| **{resistance_level}**（+8%）| 前高壓力區 | 若突破則確認多頭延續 |")
            lines.append("")
        else:
            lines.append("> ⚠️ 未取得有效股價，無法產出價位建議")
            lines.append("")

        lines.append("**🔄 結論反轉觸發條件：**")
        lines.append("")
        lines.append("| 情境 | 觸發條件 | 操作建議 |")
        lines.append("|------|----------|----------|")
        lines.append("| **轉多** | 外資連續 3 日淨買入 + 收盤站穩 20MA + 量能回升至 5 日均量以上 | 可建立 30% 基本部位 |")
        lines.append("| **轉空** | 外資累計賣超 > 5 萬張（≈流通股 0.19%）+ 週線 MACD 死亡交叉 + 月營收 YoY 跌破 10% | 全面減碼至 10% 以下 |")
        lines.append("| **維持觀望** | 以上條件均未觸發 | 持有現金，等待方向明確 |")
        lines.append("")
        lines.append("> **轉空觸發條件歷史校準說明：** 5 萬張約佔台積電流通股數（~259 億股）的 0.19%。")
        lines.append("> 對照 2022 年修正期間外資單月最大賣超達 80 萬張、2024 年 AI 拉回期間約 30-40 萬張，")
        lines.append("> 5 萬張屬於「持續性賣超」而非「單日異常值」的門檻，需搭配週線 MACD 死亡交叉確認趨勢性。")
        lines.append("")

        # ── 6. 產業比較基準 ──────────────────────────────────────────
        lines.append("### 6️⃣ 產業比較基準")
        lines.append("")

        pe_ratio = 0
        trailing_4q_eps = 0
        if quarterly_data and tw_price > 0:
            sorted_eps_keys = sorted(quarterly_data.keys(), reverse=True)
            eps_count = 0
            for k in sorted_eps_keys[:4]:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    trailing_4q_eps += ev
                    eps_count += 1
            if eps_count >= 2 and trailing_4q_eps > 0:
                pe_ratio = tw_price / trailing_4q_eps

        lines.append("**📊 台積電估值在同業中的位置：**")
        lines.append("")
        if pe_ratio > 0:
            lines.append(f"- 當前本益比（TTM）：**{pe_ratio:.1f} 倍**（股價 {tw_price:.0f} / 過去四季 EPS {trailing_4q_eps:.2f}）")
        lines.append("")
        lines.append("| 公司 | 預估 P/E (2026) | 與台積電差異 | 解讀 |")
        lines.append("|------|-------------------|--------------|------|")
        lines.append("| **台積電（2330.TW）** | ~30-32x | 基準 | 代工龍頭溢價 |")
        lines.append("| **三星電子** | ~12-15x | 折價 ~50% | 記憶體週期 + 代工追趕中，估值重壓 |")
        lines.append("| **Intel (INTC)** | ~25-30x | 相近但無光環 | IDM 模式轉型期，foundry 業務仍在虧損 |")
        lines.append("| **GlobalFoundries** | ~20-22x | 折價 ~30% | 成熟製程為主，無 AI 主題溢價 |")
        lines.append("")
        lines.append("- **台積電 5 年歷史 P/E 區間**：約 12x-35x（2020 低點 ~15x, 2024 AI 週期高峰 ~32x）")
        if pe_ratio > 0:
            lines.append(f"  - 若以 {pe_ratio:.1f} 倍來看，處於歷史**偏上區間**（約 70-80 百分位）")
        lines.append("")

        # ── PEG 錨定 consensus EPS ──
        lines.append("- **PEG Ratio（錨定市場共識 EPS）：**")
        lines.append("")
        # 從 bigtech_data 取得實際的 EPS 估算數據
        consensus_growth = None
        eps_2026_est = None
        if bigtech_data:
            # bigtech_data 內含 TSMC 2026 預估 EPS（由 macro_agent._fetch_tsm_eps_estimate 計算）
            eps_2026_est = bigtech_data.get("eps_2026_estimate") or bigtech_data.get("eps_2026_annualized")
            eps_trailing_4q = bigtech_data.get("eps_trailing_4q")
            if eps_2026_est and eps_trailing_4q and eps_trailing_4q > 0:
                consensus_growth = (eps_2026_est / eps_trailing_4q - 1) * 100

        if consensus_growth is not None and pe_ratio > 0:
            peg = pe_ratio / consensus_growth if consensus_growth > 0 else float('inf')
            lines.append(f"  - 2026 預估 EPS（Q1 比例推算）：{eps_2026_est:.2f} 元")
            lines.append(f"  - 過去四季 EPS 加總：{eps_trailing_4q:.2f} 元")
            lines.append(f"  - 隱含 EPS 成長率：{consensus_growth:.1f}%")
            lines.append(f"  - PEG = {pe_ratio:.1f} / {consensus_growth:.1f} = **{peg:.2f}**")
            if peg <= 1.0:
                lines.append(f"  - 📌 PEG ≤ 1.0 → 估值相對成長性仍屬合理")
            elif peg <= 1.5:
                lines.append(f"  - 📌 PEG 1.0-1.5 → 估值合理偏高，需 EPS 成長支撐")
            else:
                lines.append(f"  - 📌 PEG > 1.5 → 估值偏貴，成長性不足以支撐當前 P/E")
        else:
            lines.append("  - 目前無可用的 consensus EPS 成長率數據（需 FinMind 季度資料至少 2 季）")
            lines.append("  - 建議以 Bloomberg / Refinitiv 法人共識預估替代，避免自行假設成長率")
        lines.append("")

        if pe_ratio > 0:
            if pe_ratio > 35:
                lines.append(f"> 📌 **結論：{pe_ratio:.1f} 倍已接近歷史高檔區**，在缺乏 EPS 進一步上修空間下，估值擴張空間有限。")
                lines.append(f"> 操作上應以「等估值拉回」為主，而非「追價買入」。")
            elif pe_ratio > 28:
                lines.append(f"> 📌 **結論：{pe_ratio:.1f} 倍處於合理偏上**，估值本身不是賣出理由，但需 EPS 成長支撐。")
                lines.append(f"> 若後續法說會上修全年 EPS 展望，則目前估值仍具上修空間。")
            else:
                lines.append(f"> 📌 **結論：{pe_ratio:.1f} 倍處於合理區間**，估值風險可控。")
        lines.append("")

        # ── 7. 分析師整合敘事 ────────────────────────────────────────
        lines.append("### 📝 分析師整合結論")
        lines.append("")
        lines.append("**核心矛盾：**")
        lines.append("")

        # 根據實際數據動態生成整合敘事
        narrative_parts = []

        # 技術面描述
        if tech_flags.get("position_zone"):
            zone = tech_flags.get("position_zone", "未知")
            narrative_parts.append(f"技術面處於{zone}，多頭排列反映的是**慣性而非新的買入訊號**")

        # 籌碼面描述
        if extreme_sell:
            narrative_parts.append(f"外資 5 日累計大幅賣超，籌碼結構正在惡化")
        elif foreign_5d:
            narrative_parts.append(f"外資持續賣超，但幅度尚未達極端值")

        # 法說會催化劑
        if days_offset > 0 and days_offset <= 45:
            narrative_parts.append(f"市場正在等待 {earnings_str} 法說會作為打破僵局的催化劑")

        # 估值描述
        if pe_ratio > 30:
            narrative_parts.append(f"P/E {pe_ratio:.1f} 倍已反映多數利多，估值擴張空間有限")

        if narrative_parts:
            core_narrative = "；".join(narrative_parts) + "。"
        else:
            core_narrative = "各維度訊號混雜，無明確方向性。"

        lines.append(f"> 台積電當前的核心矛盾是：**AI 結構性成長邏輯完整，但外資在高檔系統性出貨，市場在等待一個催化劑（法說會上修展望 or N2 量產確認）來打破這個僵局。**")
        lines.append(f"> {core_narrative}")
        lines.append(f"> 在催化劑出現之前，技術面的多頭排列只是慣性，不是新的買入理由。")
        lines.append("")
        lines.append("**各維度因果鏈：**")
        lines.append("")
        lines.append("```")
        lines.append("Apple/NVIDIA 訂單能見度")
        lines.append("    ↓")
        lines.append("CoWoS 供需缺口 + N3/N2 良率")
        lines.append("    ↓")
        lines.append("三率趨勢（毛利率/營益率/淨利率）")
        lines.append("    ↓")
        lines.append("EPS 成長（需區分本業/業外/匯損）")
        lines.append("    ↓")
        lines.append("外資法人評價 → 籌碼流向")
        lines.append("    ↓")
        lines.append("技術面價量關係 → 散戶 vs 法人博弈")
        lines.append("    ↓")
        lines.append("ADR 溢價（需過濾匯率因子）")
        lines.append("```")
        lines.append("")
        return "\n".join(lines)

    def _append_to_log(self, dashboard_summary: str, fin_report: str, tech_report: str,
                       chip_report: str, macro_report: str, score_summary: str,
                       fin_table: str, vol_table: str, bigtech_report: str = "",
                       pe_warning_md: str = "",
                       industry_analysis_md: str = "",
                       fin_report_structured: str = "",
                       tracker_report: str = "",
                       quarterly_data: Dict = None,
                       styled_df: pd.DataFrame = None,
                       chip_flags: Dict = None,
                       chip_score: int = 0,
                       tech_flags: Dict = None,
                       tech_scores: Dict = None,
                       bigtech_data: Dict = None,
                       result = None,
                       tw_price: float = 0,
                       fx_averages: Optional[Dict[str, float]] = None,
                       revenue_by_date: Optional[Dict[str, float]] = None,
                       price_df: Optional[pd.DataFrame] = None,
                       ) -> None:
        """將分析結果以 Markdown 格式附加到檔案（重構版：直接產出結構化報告）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        analysis_date = timestamp[:10]
        quarterly_data = quarterly_data or {}
        chip_flags = chip_flags or {}
        tech_flags = tech_flags or {}
        tech_scores = tech_scores or {}
        bigtech_data = bigtech_data or {}
        fx_averages = fx_averages or {}
        revenue_by_date = revenue_by_date or {}

        # ── 輔助函式 ──────────────────────────────────────────────────
        def _fmt_num(v, d=1, s=""):
            if v is None:
                return "N/A"
            return f"{v:.{d}f}{s}"

        def _fmt_int(v):
            if v is None:
                return "N/A"
            return f"{int(round(v)):,}"

        def _md_table(headers, rows):
            out = "| " + " | ".join(headers) + " |"
            out += "\n| " + " | ".join(["------"] * len(headers)) + " |"
            for row in rows:
                out += "\n| " + " | ".join(str(c) if str(c) else "N/A" for c in row) + " |"
            return out

        def _demote_headings(md: str, levels: int = 1) -> str:
            """將嵌入子報告的 Markdown ATX 標題降級，避免破壞『## 章節 / ### 小節』層級。"""
            if not md:
                return md

            def _shift(m):
                hashes = m.group(1)
                rest = m.group(2)
                return "#" * min(len(hashes) + levels, 6) + rest

            return re.sub(r'^(#{1,5})(\s+.*)$', _shift, md, flags=re.MULTILINE)

        def _build_3month_cumulative_table():
            """建立近 N 組 3 個月累計營收 vs. 去年同期的比較表格。"""
            if not revenue_by_date:
                return "> ⚠️ 營收金額資料不足，無法計算累計比較。"

            from datetime import date as _date
            today = _date.today()

            # 收集所有可用的月份（排序）
            available_months = sorted(revenue_by_date.keys())

            # 從最新月份往前，每 3 個月一組，最多取 4 組
            groups = []
            cur_year = today.year
            cur_month = today.month

            for _ in range(4):
                # 計算這組的 3 個月
                group_months = []
                y, m = cur_year, cur_month
                for _ in range(3):
                    group_months.append(f"{y:04d}-{m:02d}")
                    m -= 1
                    if m <= 0:
                        m = 12
                        y -= 1
                group_months.reverse()  # 由遠到近

                # 去年同期
                prev_group_months = []
                for ym in group_months:
                    py = int(ym[:4]) - 1
                    prev_group_months.append(f"{py:04d}-{ym[5:7]}")

                # 檢查資料是否齊全
                cur_sum = sum(revenue_by_date.get(ym, 0) for ym in group_months)
                prev_sum = sum(revenue_by_date.get(ym, 0) for ym in prev_group_months)
                has_cur = all(ym in revenue_by_date for ym in group_months)
                has_prev = all(ym in revenue_by_date for ym in prev_group_months)

                if has_cur and has_prev and prev_sum > 0:
                    yoy_pct = (cur_sum - prev_sum) / prev_sum * 100
                    label = f"{group_months[0]} ~ {group_months[-1]}"
                    groups.append([
                        label,
                        f"{cur_sum / 1e8:.1f}",
                        f"{prev_sum / 1e8:.1f}",
                        f"{yoy_pct:+.1f}%",
                        "🟢" if yoy_pct > 15 else ("🟡" if yoy_pct > 0 else "🔴"),
                    ])

                # 往前推 3 個月
                cur_month -= 3
                while cur_month <= 0:
                    cur_month += 12
                    cur_year -= 1

            if not groups:
                return "> ⚠️ 營收金額資料不足，無法計算累計比較。"

            table_rows = groups[:4]  # 最多 4 組
            return _md_table(
                ["期間", "當期累計（億元）", "去年同期（億元）", "YoY", ""],
                table_rows,
            )

        # ── 基本數據計算 ──────────────────────────────────────────────
        # 本益比
        pe_ratio = 0.0
        trailing_4q_eps = 0.0
        eps_count = 0
        if quarterly_data and tw_price > 0:
            sorted_eps_keys = sorted(quarterly_data.keys(), reverse=True)
            for k in sorted_eps_keys[:4]:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    trailing_4q_eps += ev
                    eps_count += 1
            if eps_count >= 2 and trailing_4q_eps > 0:
                pe_ratio = tw_price / trailing_4q_eps

        # 燈號
        alert_emoji = "🟢"
        alert_label = "綠燈"
        if result is not None:
            alert_emoji = result.alert_emoji
            alert_label = result.alert_label

        # 綜合得分
        comprehensive_score = 0.0
        if result is not None:
            comprehensive_score = result.comprehensive_score

        # 權重
        w = CONFIG.weights

        # 各面向得分
        fin_score = result.financial_score if result else 0
        bigtech_score = result.bigtech_score if result else 0
        tech_score_val = result.tech_score if result else 0

        # 法說會日期
        from datetime import date as _date
        today = _date.today()
        earnings_str, days_offset, earnings_desc = self._estimate_earnings_date(today)
        days_to_earnings = max(days_offset, 0)

        # ── 外部系統性風險判讀（macro_risk.py）──
        # 區分「台積電自身基本面 / 籌碼變化」與「跨市場連動、槓桿商品斷鏈
        # 所驅動的外部系統性風險」。此判讀決定 ch7/ch8 是否標註「此次下跌
        # 主因為外部系統性風險，非台積電基本面轉弱」。
        try:
            analysis_day = _date.fromisoformat(analysis_date)
        except Exception:
            analysis_day = today
        try:
            earnings_date = _date.fromisoformat(earnings_str) if earnings_str not in ("未知", "", None) else None
        except Exception:
            earnings_date = None

        macro_signal = macro_risk.assess_macro_risk(price_df=price_df, as_of=analysis_day)
        is_systemic_risk = bool(macro_signal.is_red)
        is_systemic_event_day = bool(macro_risk.is_systemic_event_day(price_df, analysis_day))
        days_since_earn = macro_risk.days_since_earnings(earnings_date, as_of=today) if earnings_date else 0

        # ── 報告各節 ──────────────────────────────────────────────────
        sections = []
        present_chapters = set()
        CHAPTERS = [
            ("ch1", "一、總覽儀表板"),
            ("ch2", "二、財務面分析"),
            ("ch3", "三、基本面分析（大廠基本面 / CAPEX）"),
            ("ch4", "四、技術面分析"),
            ("ch5", "五、籌碼面分析"),
            ("ch6", "六、估值定位"),
            ("ch7", "七、風險管理與操作建議"),
            ("ch8", "八、分析師整合結論"),
            ("ch9", "九、宏觀與 ADR 分析（參考資料）"),
            ("ch10", "十、機構法人 13F 持倉追蹤（參考資料）"),
            ("ch11", "十一、產業深度解讀（參考資料）"),
        ]

        # ═══ 標題 ═══
        price_str = f"NT${tw_price:,.0f}" if tw_price > 0 else "N/A"
        pe_str = f"{pe_ratio:.1f}" if pe_ratio > 0 else "N/A"
        sections.append(
            f"# TSMC 量化分析報告\n\n"
            f"**分析基準日：** {analysis_date}　｜　**股價：** {price_str}　｜　**本益比（TTM）：** {pe_str} 倍\n\n"
            f"> **免責聲明：** 本報告內容僅供內部研究參考，不構成任何投資要約或買賣建議。"
            f"使用者應自行評估風險，作者不對依賴本報告所產生之損失承擔責任。"
        )

        # ═══ 一、總覽儀表板 ═══
        # 各面向分數（優先取 SignalEngine 結果，確保與綜合得分一致）
        fin_s   = result.financial_score if result else fin_score
        bt_s    = result.bigtech_score if result else bigtech_score
        tech_s  = result.tech_score if result else tech_score_val
        chip_s  = result.chip_score if result else chip_score

        # 燈號分組：基本面 = 財務面 + 大廠基本面；技術籌碼 = 技術面 + 籌碼面
        # 合併分數依各面向原有權重加權平均，與綜合得分邏輯一致。
        fin_w, bt_w   = w.financial, w.bigtech
        tech_w, chip_w = w.tech, w.chip

        def _combine(s1, w1, s2, w2):
            tot = w1 + w2
            if tot <= 0:
                return (s1 + s2) / 2
            return (s1 * w1 + s2 * w2) / tot

        fundamental_score = _combine(fin_s, fin_w, bt_s, bt_w)
        techchip_score    = _combine(tech_s, tech_w, chip_s, chip_w)

        fund_emoji     = score_to_alert(fundamental_score)[2]
        techchip_emoji = score_to_alert(techchip_score)[2]

        score_rows = [
            [f"基本面（財務 + 大廠）", "100", f"{(fin_w+bt_w)*100:.0f}%", f"{fundamental_score:.1f}", fund_emoji],
            [f"技術籌碼（技術 + 籌碼）", "100", f"{(tech_w+chip_w)*100:.0f}%", f"{techchip_score:.1f}", techchip_emoji],
            ["**合計**", "—", "100%", f"**{comprehensive_score:.1f}**", alert_emoji],
        ]

        # 主要警示
        warnings = []
        if pe_ratio > 31:
            warnings.append(f"🟡 **本益比偏高**：TTM P/E {pe_ratio:.1f} 倍，處於歷史 70–80 百分位，估值擴張空間有限")
        if chip_flags.get("extreme_sell") or chip_flags.get("big_foreign_sell"):
            warnings.append("🔴 **外資持續賣超**：5 日累計大幅賣超，籌碼結構惡化")

        warn_block = ""
        if warnings:
            warn_block = "\n".join(f"- {w}" for w in warnings)

        sections.append(
            "---\n\n"
            "<a id=\"ch1\"></a>\n\n## 一、總覽儀表板\n\n"
            f"### {alert_emoji} 綜合健康得分：{comprehensive_score:.1f} / 100（{alert_label}）\n\n"
            + _md_table(["面向", "滿分", "權重", "得分", "燈號"], score_rows)
            + "\n\n"
            + "### ⚠️ 主要警示\n\n"
            + (warn_block if warn_block else "- 無重大警示")
        )

        # ═══ 二、財務面分析 ═══
        # 三率趨勢表格
        q_rows = []
        if quarterly_data:
            sorted_q_keys = sorted(quarterly_data.keys(), reverse=True)
            for k in sorted_q_keys[:3]:
                q = quarterly_data[k]
                q_label = f"{k[0]}Q{k[1]}"
                q_rows.append([
                    q_label,
                    _fmt_num(q.get("gross_margin"), 2, "%"),
                    _fmt_num(q.get("operating_margin"), 2, "%"),
                    _fmt_num(q.get("net_margin"), 2, "%"),
                    _fmt_num(q.get("eps"), 2, ""),
                ])

        # 趨勢判斷
        fin_trend = "✅ 上升"
        if len(q_rows) >= 3:
            gm_vals = [quarterly_data[k].get("gross_margin") for k in sorted(quarterly_data.keys(), reverse=True)[:3]]
            if all(v is not None for v in gm_vals) and not (gm_vals[0] > gm_vals[1] > gm_vals[2]):
                fin_trend = "⚠️ 分歧"

        # 月營收表格
        month_rows = []
        if styled_df is not None and not styled_df.empty:
            rev_col = "營收 YoY (%)"
            if rev_col in styled_df.columns:
                for idx, row in styled_df.tail(12).iterrows():
                    month_val = idx if isinstance(idx, str) else str(idx)
                    yoy = row.get(rev_col)
                    if pd.notna(yoy):
                        yoy_f = float(yoy)
                        note = ""
                        if yoy_f < 20:
                            note = "🟡"
                        month_rows.append([month_val, f"{yoy_f:.2f}%", note])

        # EPS 成長結構
        eps_decomp = ""
        if quarterly_data:
            sorted_eps_keys = sorted(quarterly_data.keys(), reverse=True)
            eps_vals = []
            for k in sorted_eps_keys[:4]:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    eps_vals.append((f"{k[0]}Q{k[1]}", ev))
            if len(eps_vals) >= 2:
                eps_arrows = " → ".join(f"{l}: {v:.2f}" for l, v in eps_vals)
                eps_decomp = f"\n\n過去四季 EPS：{eps_arrows}（+{(eps_vals[0][1]/eps_vals[-1][1]-1)*100:.0f}%）"

        sections.append(
            "---\n\n"
            "<a id=\"ch2\"></a>\n\n## 二、財務面分析\n\n"
            "**資料來源：** FinMind 財務報表 / 月營收資料集、Yahoo Finance\n\n"
            "### 三率趨勢（逐季）\n\n"
            + _md_table(["季度", "毛利率", "營業利益率", "稅後淨利率", "EPS（元）"],
                       q_rows if q_rows else [["N/A"] * 5])
            + "\n\n"
            + f"> 💡 **結論：** 三率連續兩季同步上升，基本面強勁，多頭格局明確。\n\n"
            "### 月營收 YoY（近 12 個月）\n\n"
            + _md_table(["月份", "YoY (%)", "備註"],
                       month_rows if month_rows else [["N/A", "N/A", "N/A"]])
            + "\n\n"
            "### 近 3 個月累計營收 vs. 去年同期\n\n"
            + "> 消除單月基期雜訊，以近 3 個月累計金額與去年同期累計比較，更能反映真實需求趨勢。\n\n"
            + _build_3month_cumulative_table()
            + "\n\n"
            + f"> 🔍 高 YoY 月份需留意基期效應。累計 3 個月 YoY 可消除單月雜訊，更能反映真實需求趨勢。"
            + eps_decomp
        )

        # ═══ 三、基本面分析（大廠基本面 / CAPEX）═══
        sections.append(
            "---\n\n"
            "<a id=\"ch3\"></a>\n\n## 三、基本面分析（大廠基本面 / CAPEX）\n\n"
            "**資料來源：** 各大廠（MSFT / META / GOOGL / AMZN）資本支出趨勢、"
            "NVIDIA 財報營收 YoY（FinMind / SEC 10-K / 財報披露）\n\n"
            + _demote_headings(bigtech_report)
        )

        # ═══ 四、技術面分析 ═══
        # 技術指標摘要
        tech_zone = tech_flags.get("position_zone", "未知")
        tech_zone_score = tech_flags.get("position_zone_score", 50)

        # 從 tech_report 解析關鍵指標
        import re as _re
        ma20_match = _re.search(r"20MA ([\d.]+)", tech_report)
        ma20_val = ma20_match.group(1) if ma20_match else "N/A"
        div_match = _re.search(r"20MA乖離率: ([\-\d.]+%)", tech_report)
        div_val = div_match.group(1) if div_match else "N/A"
        k_match = _re.search(r"KD: %K=([\d.]+)", tech_report)
        d_match = _re.search(r"%D=([\d.]+)", tech_report)
        k_val = k_match.group(1) if k_match else "N/A"
        d_val = d_match.group(1) if d_match else "N/A"
        rsi_match = _re.search(r"RSI: ([\d.]+)", tech_report)
        rsi_val = rsi_match.group(1) if rsi_match else "N/A"
        support_match = _re.search(r"支撐 ([\d.]+)", tech_report)
        resist_match = _re.search(r"壓力 ([\d.]+)", tech_report)
        support_val = support_match.group(1) if support_match else "N/A"
        resist_val = resist_match.group(1) if resist_match else "N/A"
        bb_match = _re.search(r"布林通道寬度: ([\d.]+%)", tech_report)
        bb_val = bb_match.group(1) if bb_match else "N/A"

        # 均線結構
        ma_order_match = _re.search(r"(5MA=[\d.]+, 20MA=[\d.]+, 60MA=[\d.]+)", tech_report)
        ma_order = ma_order_match.group(1) if ma_order_match else "N/A"

        # 趨勢判斷
        early_trend = tech_flags.get("early_trend", "觀察")
        short_trend = tech_flags.get("short_trend", "觀察")
        mid_trend = tech_flags.get("mid_trend", "觀察")
        long_trend = tech_flags.get("long_trend", "觀察")

        vol_table_block = vol_table if vol_table else "N/A"

        sections.append(
            "---\n\n"
            "<a id=\"ch4\"></a>\n\n## 四、技術面分析\n\n"
            "**資料來源：** TWSE 每日收盤行情（STOCK_DAY）、大盤統計（FMTQIK）\n\n"
            "### 近 10 個交易日成交金額（單位：元）\n\n"
            + vol_table_block + "\n\n"
            "### 技術指標摘要\n\n"
            + _md_table(["指標", "數值", "解讀"], [
                ["綜合技術分數", f"{tech_zone_score} / 100", tech_zone],
                ["20MA 乖離率", f"收 {price_str} / MA {ma20_val}", div_val],
                ["布林通道寬度", bb_val, "波動正常" if bb_val != "N/A" else "N/A"],
                ["KD 值", f"%K={k_val}, %D={d_val}", "中性區（黃金交叉）" if k_val != "N/A" else "N/A"],
                ["RSI", rsi_val, "中性" if rsi_val != "N/A" else "N/A"],
                ["支撐 / 壓力", f"{support_val} / {resist_val}", "—"],
            ])
            + "\n\n"
            f"**均線結構：** {ma_order}\n\n"
            f"> 📈 **趨勢判斷：** 短期{short_trend} ｜ 中期{mid_trend} ｜ 長期{long_trend}\n\n"
            + _demote_headings(tech_report)
        )

        # ═══ 五、籌碼面分析 ═══
        # 從 chip_report 解析三大法人數據
        foreign_5d_match = _re.search(r"外資 5 日累計: 賣超 ([\d,]+) 張", chip_report)
        foreign_5d_val = foreign_5d_match.group(1) if foreign_5d_match else "N/A"
        consecutive_match = _re.search(r"最長連續賣超: ([\d]+) 日", chip_report)
        consecutive_val = consecutive_match.group(1) if consecutive_match else "N/A"
        grade_match = _re.search(r"賣超分級: ([^（\n]+)", chip_report)
        grade_val = grade_match.group(1).strip() if grade_match else "N/A"

        # 三大法人個別趨勢
        foreign_dir = "🔴 賣超" if chip_flags.get("big_foreign_sell") else "🟡"
        trust_match = _re.search(r"投信: 買超 ([\d,]+) 張", chip_report)
        trust_val = trust_match.group(1) if trust_match else "N/A"
        dealer_match = _re.search(r"自營商: 買超 ([\d,]+) 張", chip_report)
        dealer_val = dealer_match.group(1) if dealer_match else "N/A"

        sections.append(
            "---\n\n"
            "<a id=\"ch5\"></a>\n\n## 五、籌碼面分析\n\n"
            "**資料來源：** FinMind 三大法人買賣超資料集（TaiwanStockInstitutionalInvestorsBuySell）\n\n"
            "### 三大法人近況\n\n"
            + _md_table(["法人", "方向", "張數", "備註"], [
                ["外資", foreign_dir, foreign_5d_val if foreign_5d_val != "N/A" else "N/A",
                 f"最長連續賣超 {consecutive_val} 日，{grade_val}" if consecutive_val != "N/A" else "N/A"],
                ["投信", "🟢 買超" if trust_val != "N/A" else "N/A",
                 trust_val if trust_val != "N/A" else "N/A", ""],
                ["自營商", "🟢 買超" if dealer_val != "N/A" else "N/A",
                 dealer_val if dealer_val != "N/A" else "N/A", ""],
            ])
            + "\n\n"
            + _demote_headings(chip_report)
        )

        # ═══ 六、估值定位 ═══
        sections.append(
            "---\n\n"
            "<a id=\"ch6\"></a>\n\n## 六、估值定位\n\n"
            + _md_table(["指標", "數值", "解讀"], [
                ["當前 P/E（TTM）", f"**{pe_str} 倍**" if pe_ratio > 0 else "N/A",
                 "歷史 70–80 百分位" if pe_ratio > 0 else "N/A"],
                ["5 年歷史 P/E 區間", "12x ~ 35x", "—"],
                ["三星電子 P/E", "~12–15x", "折價約 50%"],
                ["Intel P/E", "~25–30x", "相近"],
                ["GlobalFoundries P/E", "~20–22x", "折價約 30%"],
            ])
            + "\n\n"
            + (f"> 📌 {pe_ratio:.1f} 倍屬合理偏上，估值本身不是賣出理由，但需要法說會後 EPS 展望上修支撐。"
               if pe_ratio > 0 else "> 估值資料不足")
        )

        # ═══ 七、風險管理與操作建議 ═══
        support_level = int(tw_price * 0.85) if tw_price > 0 else 0
        resist_level = int(tw_price * 1.08) if tw_price > 0 else 0

        # ── 外部系統性風險標註（區分基本面 vs. 外部連動）──
        if is_systemic_risk:
            systemic_banner = (
                "\n> 🔴 **外部系統性風險警示（紅燈）：** 當前價格波動主要反映外部風險"
                f"（{macro_signal.reason}），非台積電法說會內容或基本面轉弱所致。"
                "操作建議以「風險控管、避免追殺」為主，待跨市場連動 / 槓桿斷鏈平息後再評估回補。\n"
            )
        else:
            systemic_banner = ""

        # ── 操作時間框架表（移除過期的「法說會前」敘事，改為動態「法說會後 N 個交易日」）──
        if earnings_date and days_since_earn > 0:
            post_earnings_row = [
                f"法說會後 {days_since_earn} 個交易日",
                "依指引方向操作",
                f"上修 → 回補；下修 → 減碼（法說會 {earnings_str} 已召開）",
            ]
        else:
            post_earnings_row = ["法說會後", "依指引方向操作", "上修 → 回補；下修 → 減碼"]

        op_rows = [
            post_earnings_row,
            ["中期", "拉回至支撐區分批佈局", "AI 結構性成長邏輯不變"],
            ["止損", "跌破 20MA 減碼 30–50%", "短期趨勢轉弱確認"],
        ]

        # ── 關鍵價位表（新增「此價位形成原因」欄，區分正常修正 vs. 外部系統性事件）──
        if is_systemic_event_day:
            current_cause = f"此為 {analysis_date} 外部風險事件後價格，非台積電獨立基本面定價結果"
        else:
            current_cause = "正常估值修正 / 技術性回檔"
        price_rows = [
            [f"{price_str}（現價）", "當前位置", current_cause, "不追高，觀察"],
            [f"{resist_level}（+8%）" if resist_level > 0 else "N/A", "前高壓力區", "技術壓力位", "突破則確認多頭延續"],
            ["跌破 20MA", "短期趨勢轉弱", "技術轉弱訊號", "減碼 30–50%"],
            [f"{support_level}（-15%）" if support_level > 0 else "N/A", "近 60 日支撐區", "技術支撐位", "可分批佈局"],
        ]

        # ── 反轉觸發條件（重校準：月營收 YoY 改用動態標準差；外資賣超需經 macro_risk 判因）──
        yoy_trigger = self._revenue_yoy_dynamic_trigger(revenue_by_date)
        # 外資賣超成因分類：若為系統性事件日驅動，標註「系統性風險驅動」且不計入轉空判讀
        foreign_sell_shares = 0.0
        recent_net = chip_flags.get("foreign_net_sell_shares", 0.0) or 0.0
        if recent_net < 0:
            foreign_sell_shares = abs(recent_net)
        sell_class = macro_risk.classify_sell_pressure(
            foreign_sell_shares, analysis_day, is_systemic=is_systemic_event_day
        )
        if foreign_sell_shares > 0 and sell_class["driven_by"] == "systemic":
            sell_trigger_txt = "外資賣超經判讀為「系統性風險驅動」（外部連動 / 槓桿斷鏈），不計入轉空判讀"
        else:
            sell_trigger_txt = "外資 5 日累計賣超 > 5 萬張"
        turn_bearish_cond = f"{sell_trigger_txt} + 週線 MACD 死亡交叉 + {yoy_trigger}"

        sections.append(
            "---\n\n"
            "<a id=\"ch7\"></a>\n\n## 七、風險管理與操作建議\n\n"
            + systemic_banner
            + "### 操作時間框架\n\n"
            + _md_table(["時間框架", "建議", "核心邏輯"], op_rows)
            + "\n\n"
            "### 關鍵價位參考\n\n"
            + _md_table(["價位", "意義", "此價位形成原因", "操作建議"], price_rows)
            + "\n\n"
            "### 結論反轉觸發條件\n\n"
            + _md_table(["情境", "觸發條件", "操作建議"], [
                ["**轉多**", "外資連續 3 日淨買入 + 收盤站穩 20MA + 量能回升至 5 日均量以上", "建立 30% 基本部位"],
                ["**轉空**", turn_bearish_cond, "全面減碼至 10% 以下"],
                ["**維持觀望**", "以上條件均未觸發", "持有現金，等待方向明確"],
            ])
            + "\n\n"
            + f"> **校準說明：** 5 萬張約佔台積電流通股（~259 億股）的 0.19%。"
            f"對照 2022 年修正期外資單月最大賣超 80 萬張、2024 年 AI 拉回期約 30–40 萬張，"
            f"5 萬張為「持續性賣超」而非「單日異常」的門檻，需搭配週線 MACD 死亡交叉確認趨勢。"
            + (f"\n> **外資賣超判因：** {sell_class['note']}" if foreign_sell_shares > 0 else "")
        )

        # ═══ 八、分析師整合結論 ═══
        # 核心矛盾：不得逕自斷言「外資在高檔系統性出貨」。若 macro_risk 判讀為
        # 外部系統性風險（紅燈），則明確標註此次下跌主因為外部風險；否則以外資
        # 賣超「原因待確認」措辭，並建議搭配 macro_risk.py 燈號判讀。
        if is_systemic_risk:
            foreign_note = (
                "但當前股價重挫主因為外部系統性風險（跨市場連動 / 槓桿商品斷鏈），"
                "非台積電基本面轉弱；外資賣超原因待確認，可能為基本面轉弱或外部連動效應，"
                "建議搭配 macro_risk.py 燈號判讀"
            )
        elif foreign_sell_shares > 0:
            foreign_note = (
                "且外資近期呈淨賣超（籌碼結構轉弱）；外資賣超原因待確認，"
                "可能為基本面轉弱或外部連動效應，建議搭配 macro_risk.py 燈號判讀"
            )
        else:
            foreign_note = "技術面價量關係反映短期資金動向，需與籌碼面交叉驗證"

        contradiction = (
            f"> **台積電當前的核心矛盾是：AI 結構性成長邏輯完整，{foreign_note}。**\n\n"
        )

        sections.append(
            "---\n\n"
            "<a id=\"ch8\"></a>\n\n## 八、分析師整合結論\n\n"
            "### 核心矛盾\n\n"
            + contradiction
            + "- 技術面多頭排列反映的是**慣性，而非新的買入訊號**\n"
            + (f"- P/E {pe_ratio:.1f} 倍已反映多數利多，**估值擴張空間有限**\n" if pe_ratio > 0 else "")
            + (f"- 法說會 **{earnings_str}** 已召開，方向由法說會指引與後續營收驗證主導\n" if earnings_date else "")
            + "\n"
            "### 各維度因果鏈\n\n"
            "```text\n"
            "Apple / NVIDIA 訂單能見度\n"
            "        ↓\n"
            "CoWoS 供需缺口 + N3/N2 良率\n"
            "        ↓\n"
            "三率趨勢（毛利率 / 營益率 / 淨利率）\n"
            "        ↓\n"
            "EPS 成長（需區分本業 / 業外 / 匯損）\n"
            "        ↓\n"
            "外資法人評價 → 籌碼流向\n"
            "        ↓\n"
            "技術面價量關係 → 散戶 vs. 法人博弈\n"
            "        ↓\n"
            "外部系統性風險（跨市場連動、槓桿商品斷鏈）\n"
            "        ↓  （與台積電自身基本面無關，但可能短期主導股價波動方向）\n"
            "ADR 溢價（需過濾匯率因子）\n"
            "```"
        )

        # ═══ 九、宏觀與 ADR 分析（參考資料）═══
        # 從 macro_report 解析 ADR 數據
        adr_premium = _re.search(r"溢價 ([\d.]+%)", macro_report)
        adr_premium_val = adr_premium.group(1) if adr_premium else "N/A"
        adr_price = _re.search(r"ADR折算價: ([\d.]+)", macro_report)
        adr_price_val = adr_price.group(1) if adr_price else "N/A"
        fx_ref = _re.search(r"匯率參考: ([\d.]+)", macro_report)
        fx_ref_val = fx_ref.group(1) if fx_ref else "N/A"

        sections.append(
            "---\n\n"
            "<a id=\"ch9\"></a>\n\n## 九、宏觀與 ADR 分析（參考資料）\n\n"
            "**資料來源：** Yahoo Finance（TSM ADR、TWD=X）\n\n"
            + _md_table(["項目", "數值"], [
                ["台股現價", price_str],
                ["ADR 折算價", f"NT${adr_price_val}" if adr_price_val != "N/A" else "N/A"],
                ["ADR 溢價", f"**{adr_premium_val}**" if adr_premium_val != "N/A" else "N/A"],
                ["匯率參考", f"{fx_ref_val} USD/TWD" if fx_ref_val != "N/A" else "N/A"],
            ])
            + "\n\n"
            + _demote_headings(macro_report)
        )

        # ═══ 十、機構法人 13F 持倉追蹤（參考資料）═══
        if tracker_report:
            sections.append(
                "---\n\n"
                "<a id=\"ch10\"></a>\n\n## 十、機構法人 13F 持倉追蹤（參考資料）\n\n"
                "**資料來源：** SEC EDGAR Form 13F-HR（infotable.xml）\n\n"
                + _demote_headings(tracker_report)
            )

        # ═══ 十一、產業深度解讀（參考資料）═══
        if industry_analysis_md:
            # 將舊的 ## 📊 五、產業分析框架 改為 ## 十一、產業深度解讀（參考資料）
            ia_clean = industry_analysis_md.replace(
                "## 📊 五、產業分析框架與深度解讀",
                "<a id=\"ch11\"></a>\n\n## 十一、產業深度解讀（參考資料）"
            )
            sections.append("---\n\n" + ia_clean)

        # ── 報告目錄（TOC）────────────────────────────────────────────
        # 核心章節固定出現；追蹤（ch10）與產業（ch11）為條件式參考資料。
        present_chapters.update(
            {"ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8", "ch9"}
        )
        if tracker_report:
            present_chapters.add("ch10")
        if industry_analysis_md:
            present_chapters.add("ch11")
        toc_lines = ["## 📑 報告目錄\n"]
        for _anchor, _label in CHAPTERS:
            if _anchor in present_chapters:
                toc_lines.append(f"- [{_label}](#{_anchor})")
        toc_block = "---\n\n" + "\n".join(toc_lines) + "\n"
        # 目錄置於標題（sections[0]）之後
        sections.insert(1, toc_block)

        # ── 寫入檔案 ──────────────────────────────────────────────────
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write("\n\n".join(sections) + "\n")
            self._keep_latest_daily_logs(analysis_date)
        except Exception as e:
            print(f"寫入日誌失敗: {e}")

    def _generate_formatted_report(self, timestamp: str) -> None:
        """在 analysis_log.md 寫入完成後，自動產出格式化報告至 reports/ 目錄。"""
        try:
            from scripts.format_tsmc_report import build_report
            from pathlib import Path

            reports_dir = Path("reports")
            reports_dir.mkdir(parents=True, exist_ok=True)

            ts = timestamp.replace(":", "").replace(" ", "_").replace("-", "")
            output_path = reports_dir / f"tsmc_report_{ts}.md"

            cache_dir = Path("local_cache")
            report = build_report(Path(self.log_path), cache_dir)
            output_path.write_text(report, encoding="utf-8")
            print(f"[系統] 格式化報告已產出至 {output_path}")
        except Exception as e:
            print(f"[系統] 格式化報告產出失敗（不影響分析）: {e}")

    def _keep_latest_daily_logs(self, date_str: str, keep: int = 3) -> None:
        """同一天只保留最新 N 筆分析紀錄。"""
        if keep <= 0 or not os.path.exists(self.log_path):
            return

        with open(self.log_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 修正：正則表達式必須與 _append_to_log 寫入的標題 (# 🚀 TSMC) 一致
        blocks = re.split(r"(?=^# 🚀 TSMC 量化分析報告 - )", content, flags=re.MULTILINE)
        kept_blocks = []
        daily_blocks = []

        for block in blocks:
            if not block.strip():
                continue
            m = re.match(r"# 🚀 TSMC 量化分析報告 - (\d{4}-\d{2}-\d{2})", block)
            if m and m.group(1) == date_str:
                daily_blocks.append(block)
            else:
                kept_blocks.append(block)

        kept_blocks.extend(daily_blocks[-keep:])
        trimmed_content = "".join(block if block.endswith("\n") else block + "\n" for block in kept_blocks)

        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(trimmed_content)
