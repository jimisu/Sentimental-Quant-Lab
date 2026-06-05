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
        "Noto Sans CJK TC",
        "Noto Sans CJK SC",
        "Noto Sans CJK JP",
        "Noto Sans CJK KR",
        "AR PL UMing TW",
        "AR PL UKai TW",
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

from tsmc_financial_agent import QuarterlyFinancialAgent
from tsmc_macro_agent import GlobalMacroAgent


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
        """產生技術線圖與成交量圖"""
        if df.empty or not HAS_MATPLOTLIB: return ""
        
        df = df.sort_values("日期").copy()
        df['5MA'] = df['台積電收盤價'].rolling(window=5).mean()
        df['20MA'] = df['台積電收盤價'].rolling(window=20).mean()
        
        close_prices = pd.to_numeric(df['台積電收盤價'], errors='coerce').dropna()
        rsi14 = self._calculate_rsi(close_prices, period=14).reindex(df.index)

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 10), gridspec_kw={'height_ratios': [3, 1, 1]})
        
        # 價格與均線
        ax1.plot(df['日期'], df['台積電收盤價'], label='Close Price', color='black', linewidth=1.5)
        ax1.plot(df['日期'], df['5MA'], label='5MA', color='blue', linestyle='--')
        ax1.plot(df['日期'], df['20MA'], label='20MA', color='red', linestyle='--')
        ax1.set_title("TSMC (2330) Technical Analysis")
        ax1.set_ylabel("Price (TWD)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 成交量
        ax2.bar(df['日期'], df['台積電成交金額'] / 10**8, color='gray', alpha=0.5, label='Volume (100M)')
        ax2.set_ylabel("Volume (100M)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.2)

        # RSI
        ax3.plot(df['日期'], rsi14, label='RSI14', color='purple', linewidth=1.5)
        ax3.axhline(70, color='red', linestyle='--', linewidth=0.8)
        ax3.axhline(30, color='green', linestyle='--', linewidth=0.8)
        ax3.set_ylabel('RSI')
        ax3.set_xlabel('Date')
        ax3.set_ylim(0, 100)
        ax3.legend(loc='upper left')
        ax3.grid(True, alpha=0.2)

        # 標註 RSI 頂背離
        if len(df) >= 20 and rsi14.notna().sum() >= 20:
            lookback = df.iloc[-60:-5]
            if not lookback.empty:
                swing_idx = lookback['台積電收盤價'].idxmax()
                swing_rsi = rsi14.loc[swing_idx]
                current_price = df['台積電收盤價'].iloc[-1]
                current_rsi = rsi14.iloc[-1]
                swing_price = df.loc[swing_idx, '台積電收盤價']
                if pd.notna(swing_rsi) and current_price >= swing_price and current_rsi < swing_rsi:
                    latest_date = df['日期'].iloc[-1]
                    ax1.annotate(
                        'RSI 頂背離',
                        xy=(latest_date, current_price),
                        xytext=(latest_date, current_price * 1.03),
                        arrowprops=dict(arrowstyle='->', color='purple', lw=1),
                        color='purple',
                        fontsize=10,
                        va='bottom',
                        ha='right'
                    )
                    ax3.annotate(
                        'RSI 頂背離',
                        xy=(latest_date, current_rsi),
                        xytext=(latest_date, min(current_rsi + 12, 98)),
                        arrowprops=dict(arrowstyle='->', color='purple', lw=1),
                        color='purple',
                        fontsize=10,
                        va='bottom',
                        ha='right'
                    )

        # 優化 x 軸日期標籤顯示：減少刻度數量避免重疊
        date_count = len(df)
        max_ticks = min(8, max(4, date_count // 20))  # 根據資料量調整刻度數
        for ax in [ax1, ax2, ax3]:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=max_ticks, integer=False))
            ax.tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        filepath = prepare_daily_chart_path(self.charts_dir, "tech_chart")
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close()
        keep_latest_daily_charts(self.charts_dir, "tech_chart", datetime.now().strftime("%Y%m%d"), keep=1)
        return filepath

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
                monthly_break = bool(True)
                penalties["long"] += 40
        elif len(monthly) < 13:
            long_signals.append("月線MA12資料不足")

        short_status = "頂部反轉預警" if kline_warnings else "短期觀察"
        mid_status = "中期轉弱確認" if len(mid_signals) >= 2 else "中期觀察"
        long_status = "長期轉空確認" if len([s for s in long_signals if "資料不足" not in s]) >= 2 else "長期觀察"

        report_lines = [
            f"● 早期警示: {', '.join(warning_parts) if warning_parts else '無'}",
            f"● 短期形態: {short_status}",
            f"● 中期趨勢: {mid_status} ({'; '.join(mid_signals) if mid_signals else '保持強勢'})",
            f"● 長期趨勢: {long_status} ({'; '.join(long_signals) if long_signals else '多頭格局'})"
        ]
        return "\n   ".join(report_lines), monthly_break, penalties

    def analyze_sentiment(self, df: pd.DataFrame) -> Tuple[str, Dict, Dict[str, int]]:
        report_prefix = f"數據來源: {self.source}\n分析邏輯: {self.logic}\n結論: "

        if df.empty or len(df) < 5:
            return f"{report_prefix}資料不足", {}, {"early": 0, "short": 0, "mid": 0, "long": 0}

        chart_path = self._generate_technical_chart(df)
        ma20_detail, crossed_below = self._format_20ma_deviation(df)
        reversal_detail, monthly_break, penalties = self._format_reversal_signals(df)
        
        # 整合 MA20 破位權重
        if crossed_below: penalties["short"] += 20
        
        scores = {k: max(0, 100 - v) for k, v in penalties.items()}
        detail_suffix = f"\n   ● {ma20_detail}\n   {reversal_detail}"
        
        tech_flags = {
            "ma20_cross_below": crossed_below,
            "monthly_break_ma12": monthly_break
        }

        # 確保資料按日期升序排序
        recent = df.sort_values("日期").tail(5).copy()
        tsmc_vals = recent['台積電成交金額'].tolist()[::-1]
        mkt_vals = recent['大盤成交金額'].tolist()[::-1]
        
        # 1. 偵測量能萎縮（原有的觀望邏輯）
        tsmc_declining = all(x < y for x, y in zip(tsmc_vals, tsmc_vals[1:3]))
        mkt_declining = all(x < y for x, y in zip(mkt_vals, mkt_vals[1:3]))

        # 2. 偵測大戶拋售（量增價跌）
        # 定義：今日成交金額大於過去 5 日平均的 1.3 倍，且股價下跌
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
        if insights:
            return f"{report_prefix}{' | '.join(insights)}{detail_suffix}{image_md}", tech_flags, scores
        if tsmc_declining and mkt_declining:
            return f"{report_prefix}市場極度觀望：個股與大盤呈現連鎖縮量。{detail_suffix}{image_md}", tech_flags, scores
        elif tsmc_declining:
            return f"{report_prefix}警訊：台積電成交量持續萎縮，資金動能轉弱。{detail_suffix}{image_md}", tech_flags, scores
        
        return f"{report_prefix}量能結構尚屬正常。{detail_suffix}{image_md}", tech_flags, scores

class InstitutionalInvestorAgent(TSMCBaseAgent):
    """
    Agent 3: 籌碼分析專家
    監控三大法人（特別是外資）的買賣超動態。
    """
    def __init__(self):
        super().__init__("籌碼分析 Agent")
        self.source = "FinMind 三大法人買賣超資料集 (TaiwanStockInstitutionalInvestorsBuySell)"
        self.logic = "追蹤三大法人（外資、投信、自營商）買賣超行為。連續外資賣超被視為 Trend-killer 訊號；三大法人同步買超則視為籌碼共振。"
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

        # 過去 5 天累計
        recent_5d_net_shares = foreign_daily.head(5).sum()
        total_sell_lots = abs(recent_5d_net_shares) / 1000

        image_md = f"\n![Chip Chart]({chart_path})" if chart_path else ""

        # 檢查 5 日累計是否為賣超
        is_net_selling = recent_5d_net_shares < 0
        big_foreign_sell = bool(is_net_selling and (total_sell_lots >= 1000)) # 5日累計賣超達 1000 張
        
        chip_score = 80 if big_foreign_sell else 100  # 用戶指定權重: 20 (100-20=80)
        
        chip_flags = {
            "big_foreign_sell": big_foreign_sell,
            **resonance_flags,
        }

        if is_net_selling:
            return f"{report_prefix}趨勢警告：外資近 5 日呈累計賣超！累計賣超約 {total_sell_lots:.0f} 張。{resonance_report}{image_md}", chip_flags, chip_score
        
        return f"{report_prefix}籌碼動向平穩或呈現累計買盤支撐。{resonance_report}{image_md}", chip_flags, chip_score

class Orchestrator:
    """
    編排器：統合分析結論並寫入 Markdown 日誌
    """
    def __init__(self, log_path: str = "analysis_log.md"):
        self.fin_agent = QuarterlyFinancialAgent()
        self.tech_agent = MarketDynamicsAgent()
        self.chip_agent = InstitutionalInvestorAgent()
        self.macro_agent = GlobalMacroAgent()
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

    def run_full_analysis(self, quarterly_data: Dict, trading_df: pd.DataFrame, chip_data: List[Dict],
                          dashboard_summary: str, styled_df: pd.DataFrame,
                          market_sentiment_red: bool = False) -> None:
        # 執行分析
        fin_report = self.fin_agent.analyze_margins(quarterly_data)
        tech_report, tech_flags, tech_scores = self.tech_agent.analyze_sentiment(trading_df)
        chip_report, chip_flags, chip_score = self.chip_agent.analyze_flow(chip_data, trading_df)
        tw_price = trading_df['台積電收盤價'].iloc[-1] if not trading_df.empty else 0
        macro_report, macro_score = self.macro_agent.analyze_global_risk(tw_price)
        
        # 計算綜合分數 (根據用戶要求權重)
        # 1.早期 10%, 2.短期 10%, 3.中期 15%, 4.技術長期 15%, 5.籌碼分析 25%, 6.全球宏觀(長期趨勢) 25%
        comprehensive_score = (
            tech_scores["early"] * 0.10 +
            tech_scores["short"] * 0.10 +
            tech_scores["mid"] * 0.15 +
            tech_scores["long"] * 0.15 +
            chip_score * 0.25 +
            macro_score * 0.25
        )

        # 檢查轉折訊號 (Trend Reversal Recognition)
        reversal_active = (
            tech_flags.get("ma20_cross_below", False) and 
            tech_flags.get("monthly_break_ma12", False) and 
            chip_flags.get("big_foreign_sell", False)
        )
        reversal_msg = ""
        if reversal_active:
            reversal_msg = "\n[！！！轉折訊號提醒！！！] 偵測到 20MA 轉負、月線破 MA12 且外資大額賣超，趨勢可能已出現反轉點！"
            dashboard_summary += f" | {reversal_msg.strip()}"

        # 檢查雙重黃燈警示 (Double Yellow Warning Recognition)
        double_yellow = ("目前處於黃燈預警" in dashboard_summary) and (comprehensive_score < 60)
        severe_msg = ""
        if double_yellow:
            severe_msg = "\n\033[1;37;41m【！嚴重警示！】儀表板與 AI 專家同時發出黃燈預警，基本面與技術面出現轉弱共振，請極度小心！\033[0m"

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
        
        # 整合評分總結字串
        score_summary = (
            f"● 技術分項: 早期({tech_scores['early']})*0.1 | 短期({tech_scores['short']})*0.1 | 中期({tech_scores['mid']})*0.15 | 長期({tech_scores['long']})*0.15\n"
            f"● 籌碼面總分: ({chip_score}) * 0.25 | 全球宏觀(長期趨勢): ({macro_score}) * 0.25\n"
            f"● 綜合健康得分: {comprehensive_score:.1f}/100"
        )

        if reversal_msg:
            print(f"\033[1;31;40m{reversal_msg}\033[0m")

        # 控制台輸出評分總結，高於 80 分以綠色顯示，低於 60 分以黃色顯示
        console_summary = score_summary
        if comprehensive_score > 80:
            console_summary = score_summary.replace(f"{comprehensive_score:.1f}/100", f"\033[1;32m🟢 {comprehensive_score:.1f}/100\033[0m")
        elif comprehensive_score < 60:
            console_summary = score_summary.replace(f"{comprehensive_score:.1f}/100", f"\033[1;33m🟡 {comprehensive_score:.1f}/100\033[0m")

        print(f"\n--- 綜合評分總結 ---\n{console_summary}\n------------------")
        if severe_msg:
            print(severe_msg)

        # 建立 Markdown 表格
        fin_table_md = self._df_to_md_table(styled_df)
        vol_table_md = self._df_to_md_table(trading_df.tail(10)[["日期", "台積電成交金額", "大盤成交金額"]])

        # 寫入日誌
        log_summary = dashboard_summary + (" | 嚴重警示：雙重黃燈共振" if double_yellow else "")
        self._append_to_log(log_summary, fin_report, tech_report, chip_report, macro_report,
                            score_summary, fin_table_md, vol_table_md, market_sentiment_red)
        print(f"\n[系統] 分析結果已同步寫入至 {self.log_path}")

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
