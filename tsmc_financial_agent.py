#!/usr/bin/env python3
"""
TSMC 財務分析 Agent
負責季度三率趨勢分析。
"""

from typing import Dict


class QuarterlyFinancialAgent:
    """
    Agent 1: 財務預測與三率分析專家
    """
    def __init__(self):
        self.name = "財務分析 Agent"
        self.source = "FinMind 財務報表資料集 (TaiwanStockFinancialStatements)"
        self.logic = "監控毛利率、營業利益率與稅後淨利率之季度趨勢。檢查最新季度是否達成『三率持續上升』之強勢基本面訊號。"

    def summarize(self, analysis: str) -> str:
        return f"[{self.name}] 報告摘要: {analysis}"

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
