#!/usr/bin/env python3
"""
TSMC AI Agents 模組
包含負責財務分析、技術分析以及自動化日誌紀錄的 Agent。
"""

import pandas as pd
try:
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
from signal_engine import (
    SignalEngine,
    FinancialSignals,
    BigTechSignals,
    TechnicalSignals,
    ChipSignals,
    MarketSentimentSignals,
)


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

        # 日期刻度
        date_count = len(df)
        max_ticks = min(10, max(5, date_count // 25))
        for ax in axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=max_ticks, integer=False))
            ax.tick_params(axis='x', rotation=45)

        plt.tight_layout()
        filepath = prepare_daily_chart_path(self.charts_dir, "tech_chart")
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close()
        keep_latest_daily_charts(self.charts_dir, "tech_chart",
                                datetime.now().strftime("%Y%m%d"), keep=1)
        return filepath

    def _plot_price_chart(self, ax, df, close, k, d):
        """繪製價格子圖：K 線 + 均線 + 布林通道 + 支撐/壓力"""
        ax.plot(df['日期'], close, label='收盤價', color='black', linewidth=1.2, zorder=5)
        ax.plot(df['日期'], df['5MA'], label='5MA', color='#1f77b4', linewidth=0.9, linestyle='--')
        ax.plot(df['日期'], df['20MA'], label='20MA', color='#d62728', linewidth=0.9, linestyle='--')

        # 布林通道
        ax.plot(df['日期'], df['BB_upper'], label='布林上軌', color='#ff7f0e',
                linewidth=0.7, linestyle=':', alpha=0.7)
        ax.plot(df['日期'], df['BB_lower'], label='布林下軌', color='#ff7f0e',
                linewidth=0.7, linestyle=':', alpha=0.7)
        ax.fill_between(df['日期'], df['BB_upper'], df['BB_lower'],
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
                    latest_date = df['日期'].iloc[-1]
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
        ax.bar(df['日期'], vol / 1e8, color=colors, alpha=0.6, width=0.8)
        ax.plot(df['日期'], df['台積電成交金額'].rolling(5).mean() / 1e8,
                label='5 日均量', color='blue', linewidth=0.8)
        ax.set_ylabel('成交量 (億)')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.2)

    def _plot_oscillator_chart(self, ax, df, rsi14, k, d):
        """繪製 RSI + KD 震盪指標子圖"""
        ax.plot(df['日期'], rsi14, label='RSI14', color='purple', linewidth=1.2)
        ax.plot(df['日期'], k, label='%K', color='#1f77b4', linewidth=0.9)
        ax.plot(df['日期'], d, label='%D', color='#d62728', linewidth=0.9)
        ax.axhline(70, color='red', linewidth=0.6, linestyle='--', alpha=0.7)
        ax.axhline(30, color='green', linewidth=0.6, linestyle='--', alpha=0.7)
        ax.axhline(80, color='red', linewidth=0.4, linestyle=':', alpha=0.5)
        ax.axhline(20, color='green', linewidth=0.4, linestyle=':', alpha=0.5)
        ax.fill_between(df['日期'], 70, 100, alpha=0.05, color='red')
        ax.fill_between(df['日期'], 0, 30, alpha=0.05, color='green')
        ax.set_ylabel('RSI / KD')
        ax.set_ylim(0, 100)
        ax.legend(loc='upper left', fontsize=8, ncol=3)
        ax.grid(True, alpha=0.2)

    def _plot_macd_chart(self, ax, df, macd, signal, histogram):
        """繪製 MACD 子圖"""
        ax.plot(df['日期'], macd, label='MACD', color='#1f77b4', linewidth=1.0)
        ax.plot(df['日期'], signal, label='訊號線', color='#d62728', linewidth=1.0)
        colors = ['#d62728' if v >= 0 else '#2ca02c' for v in histogram]
        ax.bar(df['日期'], histogram, color=colors, alpha=0.4, width=0.8, label='柱狀圖')
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

    def _format_reversal_signals(self, df: pd.DataFrame) -> Tuple[str, bool, Dict[str, int]]:
        """判斷短中長期反轉向下訊號。"""
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
        if vol_price_warnings: warning_parts.append(f"量價背離({', '.join(vol_price_warnings)})")
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
        return result, monthly_break, penalties

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

    def analyze_sentiment(self, df: pd.DataFrame) -> Tuple[str, Dict, Dict[str, int]]:
        report_prefix = f"數據來源: {self.source}\n分析邏輯: {self.logic}\n結論: "

        if df.empty or len(df) < 5:
            return f"{report_prefix}資料不足", {}, {"early": 0, "short": 0, "mid": 0, "long": 0}

        # 先計算所有技術指標欄位
        df = self._enrich_indicators(df)

        chart_path = self._generate_technical_chart(df)
        ma20_detail, crossed_below = self._format_20ma_deviation(df)
        reversal_detail, monthly_break, penalties = self._format_reversal_signals(df)

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
                zone_report_lines.append(f"    安全訊號: {'; '.join(safe_signals)}")
            if warnings:
                zone_report_lines.append(f"    ⚠️ 警告: {'; '.join(warnings)}")
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
            return f"{report_prefix}{' | '.join(insights)}{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores
        if tsmc_declining and mkt_declining:
            return f"{report_prefix}市場極度觀望：個股與大盤呈現連鎖縮量。{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores
        elif tsmc_declining:
            return f"{report_prefix}警訊：台積電成交量持續萎縮，資金動能轉弱。{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores

        return f"{report_prefix}量能結構尚屬正常。{detail_suffix}\n   {zone_section}{image_md}", tech_flags, scores

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

    def _generate_chip_chart(self, df: pd.DataFrame) -> str:
        """產生籌碼流向圖"""
        if df.empty or not HAS_MATPLOTLIB: return ""
        
        # 計算外資淨買賣超
        df['net_buy'] = pd.to_numeric(df['buy']) - pd.to_numeric(df['sell'])
        df = df.sort_values('date')
        
        plt.figure(figsize=(10, 4))
        colors = ['red' if x >= 0 else 'green' for x in df['net_buy']]
        bars = plt.bar(df['date'], df['net_buy'] / 1000, color=colors, alpha=0.7)
        plt.title("Foreign Investor Net Buy/Sell (TSMC)")
        plt.ylabel("Net Quantity (Lots/張)")
        plt.axhline(0, color='black', linewidth=0.8)

        if not df.empty:
            summary_idx = (df['net_buy'].abs() / 1000).idxmax()
            summary_date = df.loc[summary_idx, 'date']
            summary_value = df.loc[summary_idx, 'net_buy'] / 1000
            summary_label = f"最大{'買超' if summary_value >= 0 else '賣超'} {abs(summary_value):.0f} 張"
            plt.text(
                summary_date,
                summary_value,
                summary_label,
                ha='center',
                va='bottom' if summary_value >= 0 else 'top',
                color='black',
                fontsize=9,
                bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', boxstyle='round,pad=0.2')
            )

        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filepath = prepare_daily_chart_path(self.charts_dir, "chip_chart")
        plt.savefig(filepath)
        plt.close()
        keep_latest_daily_charts(self.charts_dir, "chip_chart", datetime.now().strftime("%Y%m%d"), keep=1)
        return filepath

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

        # 篩選外資資料用於繪圖與分析
        foreign_all = df[df["institution_label"] == '外資'].sort_values('date', ascending=True)
        chart_path = self._generate_chip_chart(foreign_all)
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

        image_md = f"\n![Chip Chart]({chart_path})" if chart_path else ""

        # ── 三大法人個別趨勢 ────────────────────────────────────────
        individual_trends = self._analyze_individual_trends(df, type_col)
        trend_lines = []
        for label in ["外資", "投信", "自營商"]:
            t = individual_trends.get(label, {})
            trend_lines.append(f"  · {label}: {t.get('summary', '無資料')}")

        # ── 法人動向分歧偵測 ────────────────────────────────────────
        divergence = self._detect_institution_divergence(individual_trends)

        # ── 籌碼評分（多層級） ──────────────────────────────────────
        # 基礎分 100，根據多項訊號扣分
        chip_penalties = 0

        # 5 日累計賣超
        is_net_selling = recent_5d_net_shares < 0
        if is_net_selling:
            if total_sell_lots >= 10000:
                chip_penalties += 30
            elif total_sell_lots >= 3000:
                chip_penalties += 20
            elif total_sell_lots >= 1000:
                chip_penalties += 15
            else:
                chip_penalties += 10

        # 賣超天數比例 > 60%
        if foreign_analysis["sell_ratio"] > 60:
            chip_penalties += 10

        # 連續賣超 >= 3 日
        if foreign_analysis["max_consecutive_sell"] >= 3:
            chip_penalties += 10

        chip_score = max(0, 100 - chip_penalties)

        big_foreign_sell = is_net_selling and (total_sell_lots >= 1000)
        extreme_sell = is_net_selling and (total_sell_lots >= 5000)

        chip_flags = {
            "big_foreign_sell": big_foreign_sell,
            "extreme_sell": extreme_sell,
            "sell_ratio": foreign_analysis["sell_ratio"],
            "max_consecutive_sell": foreign_analysis["max_consecutive_sell"],
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

    def run_full_analysis(self, quarterly_data: Dict, trading_df: pd.DataFrame, chip_data: List[Dict],
                          styled_df: pd.DataFrame,
                          market_sentiment_red: bool = False) -> str:
        """
        執行完整分析並回傳 dashboard_summary 字串。
        綜合得分燈號邏輯統一由 signal_engine 處理。
        """
        # ── Step 1: 各 Agent 分析 ──
        fin_report = self.fin_agent.analyze_margins(quarterly_data)
        tech_report, tech_flags, tech_scores = self.tech_agent.analyze_sentiment(trading_df)
        chip_report, chip_flags, chip_score = self.chip_agent.analyze_flow(chip_data, trading_df)
        tw_price = trading_df['台積電收盤價'].iloc[-1] if not trading_df.empty else 0
        macro_report, macro_score = self.macro_agent.analyze_global_risk(tw_price)
        bigtech_data, bigtech_report = self.macro_agent.analyze_bigtech_fundamentals()

        # ── Step 2: 建構信號 ──
        financial_signals = self._build_financial_signals(quarterly_data, styled_df)
        bigtech_signals = BigTechSignals(
            capex_growing_count=bigtech_data.get("capex_growing_count", 0),
            capex_valid_count=bigtech_data.get("capex_valid_count", 0),
            nvda_revenue_yoy=bigtech_data.get("nvda_revenue_yoy"),
            nvda_revenue_yoy_quarters=bigtech_data.get("nvda_revenue_yoy_quarters", []),
        )
        tech_signals = TechnicalSignals(scores=tech_scores, flags=tech_flags)
        chip_signals = ChipSignals(score=chip_score, flags=chip_flags)

        # 市場情緒信號
        market_sentiment_signals = self._build_market_sentiment_signals(
            trading_df, market_sentiment_red
        )

        # ── Step 3: Signal Engine 整合計算 ──
        result = self.signal_engine.analyze(
            financial_signals, bigtech_signals, tech_signals, chip_signals,
            market_sentiment_signals
        )

        # ── Step 4: 組合報告 ──
        comprehensive_score = result.comprehensive_score
        alert_emoji = result.alert_emoji
        alert_label = result.alert_label
        alert_level = result.alert_level
        alert_message = result.alert_message

        # 建構 score_summary（顯示新權重）
        w = CONFIG.weights
        breakdown = result.details["breakdown"]
        bs = market_sentiment_signals
        score_summary = (
            f"● 財務面({result.financial_score:.0f})*{w.financial*100:.0f}% = {breakdown['financial']:.1f}/{w.financial*100:.0f}\n"
            f"● 大廠基本面({result.bigtech_score:.0f})*{w.bigtech*100:.0f}% = {breakdown['bigtech']:.1f}/{w.bigtech*100:.0f}\n"
            f"● 技術面({result.tech_score:.0f})*{w.tech*100:.0f}% = {breakdown['tech']:.1f}/{w.tech*100:.0f}\n"
            f"● 籌碼面({chip_score})*{w.chip*100:.0f}% = {breakdown['chip']:.1f}/{w.chip*100:.0f}\n"
            f"● 市場情緒({bs.score})*{w.market_sentiment*100:.0f}% = {breakdown['market_sentiment']:.1f}/{w.market_sentiment*100:.0f}\n"
            f"● 綜合健康得分: {comprehensive_score:.1f}/100"
        )

        # 控制台輸出
        print("\n=== [AI Agent 聯手分析報告] ===")
        print(f"[宏觀專家] > {macro_report}")
        print()
        print(f"[財務專家] > {fin_report}")
        print()
        print(f"[技術專家] > {tech_report}")
        print()
        print(f"[籌碼專家] > {chip_report}")
        print()
        print(f"[大廠基本面] > {bigtech_report}")
        print()

        # 市場情緒
        ms = market_sentiment_signals
        sentiment_label = "🔴 量能衰退" if ms.score <= 40 else "🟡 量能偏弱" if ms.score <= 70 else "🟢 量能正常"
        sentiment_detail = []
        if ms.triple_decline:
            sentiment_detail.append("個股+大盤連三降")
        elif ms.tsmc_volume_declining:
            sentiment_detail.append("個股連三降")
        elif ms.market_volume_declining:
            sentiment_detail.append("大盤連三降")
        detail_str = f"（{', '.join(sentiment_detail)}）" if sentiment_detail else ""
        print(f"[市場情緒] {sentiment_label} {ms.score}/100{detail_str}")
        print()

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

        # 市場情緒警示
        ms = market_sentiment_signals
        if ms.score <= 60:
            print(f"\n⚠️ 市場情緒警示: 量能衰退（{ms.score}/100）")
            if ms.triple_decline:
                print(f"   · 個股與大盤連續三日量縮")

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

        # 寫入日誌
        self._append_to_log(dashboard_summary, fin_report, tech_report, chip_report, macro_report,
                            score_summary, fin_table_md, vol_table_md, market_sentiment_red)
        print(f"\n[系統] 分析結果已同步寫入至 {self.log_path}")

        return dashboard_summary

    def _append_to_log(self, dashboard_summary: str, fin_report: str, tech_report: str,
                       chip_report: str, macro_report: str, score_summary: str,
                       fin_table: str, vol_table: str,
                       market_sentiment_red: bool = False) -> None:
        """將分析結果以 Markdown 格式附加到檔案"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 市場情緒指標：個股與大盤交易量連三降
        sentiment_section = ""
        if market_sentiment_red:
            sentiment_section = (
                f"\n\n### ⚠️ 市場情緒指標\n\n"
                f"> 🔴 **個股與大盤交易量連三降** — 短期資金動能同步轉弱，建議提高警覺。\n"
            )

        log_content = [
            f"# 🚀 TSMC 量化分析報告 - {timestamp}",
            f"### 📊 儀表板總結\n\n> {dashboard_summary}{sentiment_section}\n",
            f"### 🎯 綜合健康得分\n\n```text\n{score_summary}\n```\n",
            f"---",
            f"### 🌏 宏觀專家判讀\n\n{macro_report}\n",
            f"### 💰 財務專家判讀\n\n{fin_table}\n\n{fin_report}\n",
            f"### 📈 技術專家判讀\n\n#### 近 10 個交易日成交金額\n\n{vol_table}\n\n{tech_report}\n",
            f"### 👥 籌碼專家判讀\n\n{chip_report}\n",
            "---"
        ]
        
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write("\n\n".join(log_content))
            self._keep_latest_daily_logs(timestamp[:10])
        except Exception as e:
            print(f"寫入日誌失敗: {e}")

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
