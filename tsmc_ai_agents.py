#!/usr/bin/env python3
"""
TSMC AI Agents 模組
包含負責財務分析、技術分析以及自動化日誌紀錄的 Agent。
"""

import pandas as pd
import requests
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def prepare_daily_chart_path(charts_dir: str, prefix: str) -> str:
    """
    產生帶日期時間的圖表路徑。
    """
    os.makedirs(charts_dir, exist_ok=True)
    now = datetime.now()
    date_part = now.strftime("%Y%m%d")
    filename = f"{prefix}_{date_part}_{now.strftime('%H%M%S')}.png"
    return os.path.join(charts_dir, filename)


def keep_latest_daily_charts(charts_dir: str, prefix: str, date_part: str, keep: int = 3) -> None:
    """
    每天每種圖只保留最新 N 張，避免 charts 目錄持續膨脹。
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

class QuarterlyFinancialAgent(TSMCBaseAgent):
    """
    Agent 1: 財務預測與三率分析專家
    """
    def __init__(self):
        super().__init__("財務分析 Agent")
        self.source = "FinMind 財務報表資料集 (TaiwanStockFinancialStatements)"
        self.logic = "監控毛利率、營業利益率與稅後淨利率之季度趨勢。檢查最新季度是否達成『三率持續上升』之強勢基本面訊號。"

    def analyze_margins(self, quarterly_data: Dict) -> str:
        if not quarterly_data:
            return "查無季度財務資料。"
        
        insights = []
        # 由新到舊排序
        sorted_keys = sorted(quarterly_data.keys(), reverse=True)
        if len(sorted_keys) < 3:
            return f"[數據來源: {self.source}] 資料不足三季，無法判斷持續趨勢。"

        q0 = quarterly_data[sorted_keys[0]]
        q1 = quarterly_data[sorted_keys[1]]
        q2 = quarterly_data[sorted_keys[2]]

        def safe_val(q, key):
            val = q.get(key)
            return val if val is not None else 0

        # 檢查三率是否持續上升 (Q0 > Q1 > Q2)
        metrics = {
            '毛利率': ('gross_margin', safe_val(q0, 'gross_margin'), safe_val(q1, 'gross_margin'), safe_val(q2, 'gross_margin')),
            '營業利益率': ('operating_margin', safe_val(q0, 'operating_margin'), safe_val(q1, 'operating_margin'), safe_val(q2, 'operating_margin')),
            '稅後淨利率': ('net_margin', safe_val(q0, 'net_margin'), safe_val(q1, 'net_margin'), safe_val(q2, 'net_margin'))
        }

        uptrend_count = 0
        for name, (key, v0, v1, v2) in metrics.items():
            if v0 > v1 > v2:
                insights.append(f"✅ {name}持續上升 (連兩季成長: {v2:.1f}% -> {v1:.1f}% -> {v0:.1f}%)")
                uptrend_count += 1
            elif v0 > v1:
                insights.append(f"📈 {name}單季回升 ({v1:.1f}% -> {v0:.1f}%)，但未達連兩季成長")
            elif v0 < v1:
                insights.append(f"⚠️ {name}最新一季出現下滑 ({v1:.1f}% -> {v0:.1f}%)")

        status = "【多頭：三率持續同步上升】" if uptrend_count == 3 else "【警告：成長趨勢出現分歧】"
        summary = " | ".join(insights)
        
        return f"數據來源: {self.source}\n分析邏輯: {self.logic}\n結論: {status}\n細節: {summary}"

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
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={'height_ratios': [3, 1]})
        
        # 價格與均線
        ax1.plot(df['日期'], df['台積電收盤價'], label='Close Price', color='black', linewidth=1.5)
        ax1.plot(df['日期'], df['5MA'], label='5MA', color='blue', linestyle='--')
        ax1.plot(df['日期'], df['20MA'], label='20MA', color='red', linestyle='--')
        ax1.set_title("TSMC (2330) Technical Analysis")
        ax1.set_ylabel("Price (TWD)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 成交量
        colors = ['red' if c >= 0 else 'green' for c in df['台積電收盤價'].diff()]
        ax2.bar(df['日期'], df['台積電成交金額'] / 10**8, color='gray', alpha=0.5, label='Volume (100M)')
        ax2.set_ylabel("Volume (100M)")
        ax2.set_xlabel("Date")
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        filepath = prepare_daily_chart_path(self.charts_dir, "tech_chart")
        plt.savefig(filepath)
        plt.close()
        keep_latest_daily_charts(self.charts_dir, "tech_chart", datetime.now().strftime("%Y%m%d"))
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
        self.logic = "追蹤三大法人（特別是外資）之連續買賣超行為。連續賣超被視為 Trend-killer 訊號，代表大資金撤離。"
        self.charts_dir = "charts"

    def _generate_chip_chart(self, df: pd.DataFrame) -> str:
        """產生籌碼流向圖"""
        if df.empty or not HAS_MATPLOTLIB: return ""
        
        # 計算外資淨買賣超
        df['net_buy'] = pd.to_numeric(df['buy']) - pd.to_numeric(df['sell'])
        df = df.sort_values('date')
        
        plt.figure(figsize=(10, 4))
        colors = ['red' if x >= 0 else 'green' for x in df['net_buy']]
        plt.bar(df['date'], df['net_buy'] / 10**8, color=colors, alpha=0.7)
        plt.title("Foreign Investor Net Buy/Sell (TSMC)")
        plt.ylabel("Net Amount (100M TWD)")
        plt.axhline(0, color='black', linewidth=0.8)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filepath = prepare_daily_chart_path(self.charts_dir, "chip_chart")
        plt.savefig(filepath)
        plt.close()
        keep_latest_daily_charts(self.charts_dir, "chip_chart", datetime.now().strftime("%Y%m%d"))
        return filepath

    def analyze_flow(self, chip_data: List[Dict]) -> Tuple[str, Dict, int]:
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

        # 篩選外資資料用於繪圖與分析
        foreign_all = df[df[type_col] == 'Foreign_Investor'].sort_values('date', ascending=True)
        chart_path = self._generate_chip_chart(foreign_all)
        
        foreign = foreign_all.sort_values('date', ascending=False)

        if len(foreign) < 3:
            return f"{report_prefix}籌碼資料不足，無法判斷趨勢。", {}, 0

        # 計算每日買賣超 (buy - sell)，使用 pd.to_numeric 確保轉換安全
        net_buy = pd.to_numeric(foreign['buy']) - pd.to_numeric(foreign['sell'])
        recent_net = net_buy.head(3).tolist()
        total_sell_bn = abs(sum(recent_net)) / 10**8

        image_md = f"\n![Chip Chart]({chart_path})" if chart_path else ""

        # 檢查是否連續賣超
        is_selling = all(x < 0 for x in recent_net)
        big_foreign_sell = bool(is_selling and (total_sell_bn >= 1.0)) # 達億元規模
        
        chip_score = 80 if big_foreign_sell else 100  # 用戶指定權重: 20 (100-20=80)
        
        if is_selling:
            return f"{report_prefix}趨勢警告：外資出現連續賣超！近三日累計賣超約 {total_sell_bn:.2f} 億元。{image_md}", {"big_foreign_sell": big_foreign_sell}, chip_score
        
        return f"{report_prefix}籌碼動向平穩或呈現買盤支撐。{image_md}", {"big_foreign_sell": False}, chip_score

class GlobalMacroAgent(TSMCBaseAgent):
    """
    Agent 4: 全球市場連動專家
    監控 ADR 折溢價、費城半導體指數 (SOX) 以及美股主要客戶動態。
    """
    def __init__(self):
        super().__init__("全球宏觀 Agent")
        self.source = "Yahoo Finance (TSM ADR & TWD=X)"
        self.logic = "分析美股 ADR 溢價狀況與費半指數走勢，捕捉台股開盤前的外部衝擊。"

    def analyze_global_risk(self, tw_price: float) -> Tuple[str, int]:
        if tw_price <= 0:
            return "宏觀專家: 無法取得台股收盤價，跳過 ADR 分析。", 100

        try:
            # 取得 TSM (ADR) 與 TWD=X (匯率)
            tsm_price = self._fetch_yahoo_price("TSM")
            usdtwd = self._fetch_yahoo_price("TWD=X")
            
            # 1 TSM ADR = 5 2330 Ordinary Shares
            adr_tw_equiv = (tsm_price * usdtwd) / 5
            premium = (adr_tw_equiv - tw_price) / tw_price * 100
            
            score = 100
            if premium < -1:
                score -= 40
            elif premium < 0:
                score -= 20
            
            status = "溢價" if premium >= 0 else "折價"
            conclusion = f"{status} {abs(premium):.2f}% (ADR折算價: {adr_tw_equiv:.2f} / 台股現價: {tw_price:.2f})"
            
            report = (
                f"數據來源: {self.source}\n"
                f"分析邏輯: {self.logic}\n"
                f"結論: {conclusion}\n"
                f"匯率參考: {usdtwd:.2f}"
            )
            return report, score
        except Exception as e:
            return f"⚠️ 宏觀專家: 外部數據抓取失敗 ({e})，請檢查網路連線或 API 狀態。", 100

    def _fetch_yahoo_price(self, ticker: str) -> float:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data['chart']['result'][0]['meta']['regularMarketPrice'])

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

    def run_full_analysis(self, quarterly_data: Dict, trading_df: pd.DataFrame, chip_data: List[Dict], dashboard_summary: str) -> None:
        # 執行分析
        fin_report = self.fin_agent.analyze_margins(quarterly_data)
        tech_report, tech_flags, tech_scores = self.tech_agent.analyze_sentiment(trading_df)
        chip_report, chip_flags, chip_score = self.chip_agent.analyze_flow(chip_data)
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
        print(f"[財務專家] > {fin_report}")
        print(f"[技術專家] > {tech_report}")
        print(f"[籌碼專家] > {chip_report}")
        print(f"[宏觀專家] > {macro_report}")
        
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

        # 寫入日誌
        log_summary = dashboard_summary + (" | 嚴重警示：雙重黃燈共振" if double_yellow else "")
        self._append_to_log(log_summary, fin_report, tech_report, chip_report, macro_report, score_summary)
        print(f"\n[系統] 分析結果已同步寫入至 {self.log_path}")

    def _append_to_log(self, dashboard_summary: str, fin_report: str, tech_report: str, chip_report: str, macro_report: str, score_summary: str) -> None:
        """將分析結果以 Markdown 格式附加到檔案"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_content = [
            f"## 分析日期: {timestamp}",
            f"**儀表板總結**: {dashboard_summary}",
            f"### 綜合評分\n{score_summary}",
            f"- **財務 Agent 分析**: {fin_report}",
            f"- **技術 Agent 分析**: {tech_report}",
            f"- **籌碼 Agent 分析**: {chip_report}",
            f"- **宏觀 Agent 分析**: {macro_report}",
            "\n---\n"
        ]
        
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(log_content))
            self._keep_latest_daily_logs(timestamp[:10], keep=3)
        except Exception as e:
            print(f"寫入日誌失敗: {e}")

    def _keep_latest_daily_logs(self, date_str: str, keep: int = 3) -> None:
        """同一天只保留最新 N 筆分析紀錄。"""
        if keep <= 0 or not os.path.exists(self.log_path):
            return

        with open(self.log_path, "r", encoding="utf-8") as f:
            content = f.read()

        blocks = re.split(r"(?=^## 分析日期: )", content, flags=re.MULTILINE)
        kept_blocks = []
        daily_blocks = []

        for block in blocks:
            if not block.strip():
                continue
            match = re.match(r"## 分析日期: (\d{4}-\d{2}-\d{2})", block)
            if match and match.group(1) == date_str:
                daily_blocks.append(block)
            else:
                kept_blocks.append(block)

        kept_blocks.extend(daily_blocks[-keep:])
        trimmed_content = "".join(block if block.endswith("\n") else block + "\n" for block in kept_blocks)

        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(trimmed_content)
