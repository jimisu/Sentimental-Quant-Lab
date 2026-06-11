#!/usr/bin/env python3
"""
TSMC 財務分析 Agent
負責季度三率趨勢、EPS 品質與營收基期修正分析。
"""

import datetime as dt
from typing import Dict, Iterable, Optional, Tuple


class QuarterlyFinancialAgent:
    """
    Agent 1: 財務預測與三率分析專家
    """
    def __init__(self):
        self.name = "財務分析 Agent"
        self.source = "FinMind 財務報表資料集 (TaiwanStockFinancialStatements)"
        self.logic = "監控毛利率、營業利益率與稅後淨利率之季度趨勢。檢查最新季度是否達成『三率持續上升』之強勢基本面訊號。"
        self.revenue_source = "FinMind 月營收資料集 (TaiwanStockMonthRevenue)"
        self.fx_source = "Yahoo Finance (TWD=X)"

    def summarize(self, analysis: str) -> str:
        return f"[{self.name}] 報告摘要: {analysis}"

    @staticmethod
    def _format_quarter(key) -> str:
        if isinstance(key, tuple) and len(key) == 2:
            return f"{key[0]}Q{key[1]}"
        return str(key)

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_record_value(records_by_type: Dict, key: str) -> Optional[float]:
        return QuarterlyFinancialAgent._safe_float(records_by_type.get(key))

    def _records_to_latest_quarter(self, financial_records: Iterable[Dict]) -> Tuple[Optional[str], Dict]:
        """
        將 FinMind TaiwanStockFinancialStatements 原始列轉成最新季度欄位 dict。
        回傳：(YYYYQn, {type: value})。
        """
        quarters: Dict[Tuple[int, int], Dict] = {}
        for record in financial_records or []:
            date_str = record.get("date")
            statement_type = record.get("type")
            value = self._safe_float(record.get("value"))
            if not date_str or not statement_type or value is None:
                continue
            try:
                year = int(date_str[:4])
                month = int(date_str[5:7])
            except (TypeError, ValueError):
                continue
            quarter = (month - 1) // 3 + 1
            quarters.setdefault((year, quarter), {})[statement_type] = value

        if not quarters:
            return None, {}
        latest_key = sorted(quarters.keys())[-1]
        return self._format_quarter(latest_key), quarters[latest_key]

    def analyze_margin_trend(self, quarterly_data: Dict) -> Dict:
        """
        STEP 1: 三率趨勢偵測。
        """
        if not quarterly_data:
            return {
                "status": "⚠️",
                "summary": "查無季度財務資料。",
                "metrics": [],
                "divergences": [],
            }

        sorted_keys = sorted(quarterly_data.keys(), reverse=True)
        if len(sorted_keys) < 3:
            return {
                "status": "⚠️",
                "summary": "資料不足三季，無法判斷持續趨勢。",
                "metrics": [],
                "divergences": [],
            }

        q0_key, q1_key, q2_key = sorted_keys[:3]
        q0 = quarterly_data[q0_key]
        q1 = quarterly_data[q1_key]
        q2 = quarterly_data[q2_key]

        metric_defs = [
            ("毛利率", "gross_margin"),
            ("營業利益率", "operating_margin"),
            ("稅後淨利率", "net_margin"),
        ]
        metrics = []
        divergences = []
        uptrend_count = 0

        for label, field in metric_defs:
            v0 = self._safe_float(q0.get(field))
            v1 = self._safe_float(q1.get(field))
            v2 = self._safe_float(q2.get(field))
            is_uptrend = all(v is not None for v in (v0, v1, v2)) and v0 > v1 > v2
            if is_uptrend:
                uptrend_count += 1
                marker = "✅ 連續兩季上升"
            elif v0 is not None and v1 is not None and v0 < v1:
                marker = "⚠️ 最新一季下滑"
                divergences.append(label)
            elif v1 is not None and v2 is not None and v1 < v2:
                marker = "⚠️ 前一季下滑"
                divergences.append(label)
            else:
                marker = "⚠️ 趨勢未連續上升"
                divergences.append(label)

            metrics.append({
                "label": label,
                "q2_label": self._format_quarter(q2_key),
                "q1_label": self._format_quarter(q1_key),
                "q0_label": self._format_quarter(q0_key),
                "q2": v2,
                "q1": v1,
                "q0": v0,
                "marker": marker,
            })

        if uptrend_count == 3:
            status = "✅"
            summary = "✅ 多頭：三率持續上升"
        else:
            status = "⚠️"
            summary = "⚠️ 警示：三率出現分歧"

        return {
            "status": status,
            "summary": summary,
            "metrics": metrics,
            "divergences": sorted(set(divergences)),
        }

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

    def analyze_margin_driver(
        self,
        process_mix: Optional[Dict] = None,
        capacity_utilization_up: Optional[bool] = None,
        fx_direction: Optional[str] = None,
        fx_margin_impact: Optional[float] = None,
    ) -> Dict:
        """
        STEP 2: 三率驅動力判斷。

        process_mix 格式可為：
        {
            "q1": {"advanced": 77, "n3": 28},
            "q0": {"advanced": 74, "n3": 25},
        }
        若未提供 advanced，會嘗試加總 n2/n3/n5/n7。

        fx_direction: "headwind" | "tailwind" | "neutral" — 匯率方向
        fx_margin_impact: 匯率對毛利率的估計影響（pp），負值表示台幣升值逆風
        """
        process_mix = process_mix or {}
        q1_mix = process_mix.get("q1") or process_mix.get("previous") or {}
        q0_mix = process_mix.get("q0") or process_mix.get("latest") or {}

        def advanced_share(mix: Dict) -> Optional[float]:
            explicit = self._safe_float(mix.get("advanced"))
            if explicit is not None:
                return explicit
            parts = [self._safe_float(mix.get(key)) for key in ("n2", "n3", "n5", "n7")]
            parts = [part for part in parts if part is not None]
            return sum(parts) if parts else None

        q1_advanced = advanced_share(q1_mix)
        q0_advanced = advanced_share(q0_mix)
        advanced_delta = None
        if q0_advanced is not None and q1_advanced is not None:
            advanced_delta = q0_advanced - q1_advanced

        # 匯率逆風加成判斷：若毛利率改善是在台幣升值逆風下達成，結構性驅動力評分上調
        fx_bonus = (fx_direction == "headwind" and fx_margin_impact is not None and fx_margin_impact < -0.3)

        if advanced_delta is not None and (advanced_delta > 2 or (advanced_delta > 1 and fx_bonus)):
            label = "🟢 結構性上升，可持續性高"
            description = f"先進製程營收佔比 QoQ 增加 {advanced_delta:.2f}pp"
            if fx_bonus:
                description += (
                    f"。💡 且在台幣升值逆風下（匯率拖累毛利率約 {abs(fx_margin_impact):.1f}pp）仍達成改善，"
                    f"代表本業定價能力（Pricing Power）比表面數字更強。"
                )
            else:
                description += "，高於 2pp 門檻。"
            return {
                "type": "A",
                "label": label,
                "description": description,
                "advanced_delta": advanced_delta,
                "fx_bonus": fx_bonus,
            }

        if advanced_delta is not None and capacity_utilization_up:
            label = "🟡 週期性上升，需監控需求持續性"
            description = "先進製程佔比未顯著提升，但產能利用率/需求動能上升，三率改善較偏固定成本攤薄。"
            if fx_bonus:
                description += (
                    f"💡 但值得注意的是，此改善是在台幣升值逆風（拖累毛利率約 {abs(fx_margin_impact):.1f}pp）下達成，"
                    f"若未來匯率回穩，毛利率有額外上行空間。"
                )
            return {
                "type": "B",
                "label": label,
                "description": description,
                "advanced_delta": advanced_delta,
                "fx_bonus": fx_bonus,
            }

        if advanced_delta is not None:
            return {
                "type": "C",
                "label": "⚪ 驅動力不明，建議補充製程佔比資料",
                "description": "先進製程佔比未顯著提升，且未提供產能利用率改善訊號。",
                "advanced_delta": advanced_delta,
                "fx_bonus": False,
            }

        # 無製程資料但匯率逆風下的特別標註
        if fx_bonus:
            return {
                "type": "C",
                "label": "⚪ 驅動力不明，但匯率逆風下的表現值得注意",
                "description": (
                    f"缺少可比較的製程佔比資料。但觀察到毛利率改善是在台幣升值逆風下達成"
                    f"（匯率拖累約 {abs(fx_margin_impact):.1f}pp），暗示本業獲利能力可能被低估。"
                ),
                "advanced_delta": None,
                "fx_bonus": True,
            }

        return {
            "type": "C",
            "label": "⚪ 驅動力不明，建議補充製程佔比資料",
            "description": "缺少可比較的最新季與前一季製程佔比資料。",
            "advanced_delta": None,
            "fx_bonus": False,
        }

    def analyze_eps_quality(
        self,
        financial_records: Optional[Iterable[Dict]] = None,
        latest_financials: Optional[Dict] = None,
        fx_averages: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """
        STEP 3: EPS 成長來源拆解。
        """
        quarter_label = None
        records_by_type = latest_financials or {}
        if financial_records is not None:
            quarter_label, records_by_type = self._records_to_latest_quarter(financial_records)

        eps = self._get_record_value(records_by_type, "EPS")
        pretax = self._get_record_value(records_by_type, "PreTaxIncome")
        nonop = self._get_record_value(records_by_type, "TotalNonoperatingIncomeAndExpense")
        tax = self._get_record_value(records_by_type, "TAX")
        parent_income = self._get_record_value(records_by_type, "EquityAttributableToOwnersOfParent")
        net_income = self._get_record_value(records_by_type, "IncomeAfterTaxes")

        shares = None
        if eps and eps != 0:
            income_for_shares = parent_income or net_income
            if income_for_shares is not None:
                shares = income_for_shares / eps

        nonop_ratio = (nonop / pretax * 100) if pretax else None
        tax_rate = (tax / pretax) if pretax else None
        core_eps = None
        nonop_eps = None
        if pretax is not None and nonop is not None and tax_rate is not None and shares:
            core_after_tax = (pretax - nonop) * (1 - tax_rate)
            nonop_after_tax = nonop * (1 - tax_rate)
            core_eps = core_after_tax / shares
            nonop_eps = nonop_after_tax / shares

        if nonop_ratio is None:
            nonop_marker = "⚪ 業外資料不足"
        elif nonop_ratio > 15:
            nonop_marker = "⚠️ 業外收益偏高，盈餘品質需關注"
        elif nonop_ratio < 5:
            nonop_marker = "✅ 盈餘品質良好，主要來自本業"
        else:
            nonop_marker = "✅ 業外收益佔比可控"

        fx_averages = fx_averages or {}
        previous_fx = self._safe_float(fx_averages.get("previous"))
        latest_fx = self._safe_float(fx_averages.get("latest"))
        fx_eps_impact = None          # 匯率對 EPS 的估計影響（元）
        fx_margin_impact = None       # 匯率對毛利率的估計影響（pp）
        fx_marker = "⚪ 匯率資料不足"
        fx_direction = None           # "headwind" | "tailwind" | "neutral"
        fx_adjusted_gm = None         # 匯率調整後毛利率（排除匯率逆風後的估計值）

        if previous_fx is not None and latest_fx is not None:
            fx_delta = latest_fx - previous_fx
            # 台積電約 70% 營收以美元計價、65% 成本以台幣計價
            # USD/TWD 下降（台幣升值）→ 美元營收換回台幣縮水 → 毛利率受壓
            # 粗估：USD/TWD 每變化 1 單位，影響毛利率約 0.3-0.5pp
            fx_margin_impact = fx_delta * 0.4   # 正 = 台幣貶值助毛利率，負 = 台幣升值壓毛利率
            fx_eps_impact = fx_delta * 0.65      # 正 = 匯兌利益，負 = 匯兌損失

            if fx_delta > 0.5:
                fx_direction = "tailwind"
                fx_marker = f"🟢 台幣貶值匯兌助力（USD/TWD +{fx_delta:.2f}）"
            elif fx_delta < -0.5:
                fx_direction = "headwind"
                fx_marker = f"🔴 台幣升值匯率逆風（USD/TWD {fx_delta:.2f}）"
            else:
                fx_direction = "neutral"
                fx_marker = f"⚪ 匯率波動中性（USD/TWD {fx_delta:+.2f}）"

        # 計算匯率調整後毛利率（排除匯率逆風/順風後的本業估計值）
        latest_gm = self._get_record_value(records_by_type, "gross_margin")
        if latest_gm is not None and fx_margin_impact is not None:
            fx_adjusted_gm = latest_gm - fx_margin_impact
            # 若 fx_margin_impact 為負（台幣升值壓毛利率），減去負值 = 加上，代表本業毛利率更高

        quality_status = "⚠️ 需關注" if (
            (nonop_ratio is not None and nonop_ratio > 15)
        ) else "✅ 良好"

        return {
            "quarter": quarter_label,
            "eps": eps,
            "core_eps": core_eps,
            "nonop_eps": nonop_eps,
            "nonop_ratio": nonop_ratio,
            "nonop_marker": nonop_marker,
            "fx_eps_impact": fx_eps_impact,
            "fx_margin_impact": fx_margin_impact,
            "fx_direction": fx_direction,
            "fx_marker": fx_marker,
            "fx_adjusted_gm": fx_adjusted_gm,
            "latest_gm": latest_gm,
            "quality_status": quality_status,
        }

    def analyze_revenue_base_effect(self, revenue_records: Iterable[Dict]) -> Dict:
        """
        STEP 4: 營收基期效應修正。
        """
        revenue_by_month: Dict[Tuple[int, int], float] = {}
        for record in revenue_records or []:
            revenue = self._safe_float(record.get("revenue"))
            year = record.get("revenue_year")
            month = record.get("revenue_month")
            if revenue is None or year is None or month is None:
                continue
            try:
                revenue_by_month[(int(year), int(month))] = revenue
            except (TypeError, ValueError):
                continue

        if not revenue_by_month:
            return {
                "single_yoy": None,
                "three_month_yoy": None,
                "base_effect": None,
                "message": "查無月營收資料。",
            }

        latest = max(revenue_by_month.keys())
        last_year = (latest[0] - 1, latest[1])
        single_yoy = None
        if last_year in revenue_by_month and revenue_by_month[last_year] != 0:
            single_yoy = (revenue_by_month[latest] - revenue_by_month[last_year]) / revenue_by_month[last_year] * 100

        months = []
        year, month = latest
        for offset in range(2, -1, -1):
            cur_year = year
            cur_month = month - offset
            while cur_month <= 0:
                cur_month += 12
                cur_year -= 1
            months.append((cur_year, cur_month))
        previous_months = [(y - 1, m) for y, m in months]

        three_month_yoy = None
        if all(key in revenue_by_month for key in months + previous_months):
            current_sum = sum(revenue_by_month[key] for key in months)
            previous_sum = sum(revenue_by_month[key] for key in previous_months)
            if previous_sum != 0:
                three_month_yoy = (current_sum - previous_sum) / previous_sum * 100

        base_effect = None
        if single_yoy is not None and three_month_yoy is not None:
            base_effect = abs(single_yoy - three_month_yoy) > 10

        return {
            "latest_month": f"{latest[0]}-{latest[1]:02d}",
            "single_yoy": single_yoy,
            "three_month_yoy": three_month_yoy,
            "base_effect": base_effect,
            "message": "⚠️ 單月 YoY 受基期影響，請參考累計值" if base_effect else "✅ 無明顯單月基期扭曲",
        }

    def build_structured_report(
        self,
        quarterly_data: Dict,
        financial_records: Optional[Iterable[Dict]] = None,
        revenue_records: Optional[Iterable[Dict]] = None,
        process_mix: Optional[Dict] = None,
        capacity_utilization_up: Optional[bool] = None,
        fx_averages: Optional[Dict[str, float]] = None,
        analysis_date: Optional[str] = None,
    ) -> str:
        """
        輸出使用者指定的 STEP 1~4 完整財務 Agent 分析報告。
        """
        analysis_date = analysis_date or dt.date.today().isoformat()
        trend = self.analyze_margin_trend(quarterly_data)

        # 先跑 EPS 品質分析取得匯率數據，再傳給驅動力判斷
        eps_quality = self.analyze_eps_quality(financial_records=financial_records, fx_averages=fx_averages)
        driver = self.analyze_margin_driver(
            process_mix,
            capacity_utilization_up,
            fx_direction=eps_quality.get("fx_direction"),
            fx_margin_impact=eps_quality.get("fx_margin_impact"),
        )
        revenue_effect = self.analyze_revenue_base_effect(revenue_records or [])

        def pct(value) -> str:
            return "N/A" if value is None else f"{value:.2f}%"

        def num(value) -> str:
            return "N/A" if value is None else f"{value:.2f}"

        metric_lines = []
        for metric in trend["metrics"]:
            metric_lines.append(
                f"- {metric['label']}：{metric['q2_label']} {pct(metric['q2'])} → "
                f"{metric['q1_label']} {pct(metric['q1'])} → "
                f"{metric['q0_label']} {pct(metric['q0'])}（{metric['marker']}）"
            )

        # 匯率段落：顯示方向、對 EPS 與毛利率的估計影響、匯率調整後毛利率
        fx_eps_impact = eps_quality.get("fx_eps_impact")
        fx_margin_impact = eps_quality.get("fx_margin_impact")
        fx_adjusted_gm = eps_quality.get("fx_adjusted_gm")
        latest_gm = eps_quality.get("latest_gm")

        if fx_eps_impact is not None:
            fx_text = f"{fx_eps_impact:+.2f} 元"
        else:
            fx_text = "N/A"

        if fx_margin_impact is not None:
            fx_margin_text = f"{fx_margin_impact:+.2f}pp"
        else:
            fx_margin_text = "N/A"

        fx_adjusted_text = pct(fx_adjusted_gm) if fx_adjusted_gm is not None else "N/A"

        # 匯率調整後毛利率的解讀文字
        fx_insight = ""
        if fx_margin_impact is not None and latest_gm is not None:
            if fx_margin_impact < -0.3:
                fx_insight = (
                    f"\n   💡 **關鍵發現**：在台幣升值逆風（拖累毛利率約 {abs(fx_margin_impact):.1f}pp）下，"
                    f"毛利率仍達 {latest_gm:.1f}%。排除匯率逆風後，本業毛利率估計約 **{fx_adjusted_gm:.1f}%**，"
                    f"代表定價能力（Pricing Power）比表面數字更強。"
                )
            elif fx_margin_impact > 0.3:
                fx_insight = (
                    f"\n   ⚠️ 台幣貶值順風助力毛利率約 +{fx_margin_impact:.1f}pp，"
                    f"若排除匯率因素，本業毛利率估計約 {fx_adjusted_gm:.1f}%。"
                )

        base_effect = revenue_effect.get("base_effect")
        base_text = "N/A" if base_effect is None else ("有" if base_effect else "無")

        # 動態結論
        conclusion_parts = []
        if trend["status"] == "✅":
            conclusion_parts.append("三率持續同步上升，基本面強勁。")
        else:
            conclusion_parts.append("三率趨勢出現分歧，需持續追蹤。")

        if eps_quality["quality_status"] == "✅ 良好":
            conclusion_parts.append("EPS 品質良好，獲利主要來自本業。")
        else:
            conclusion_parts.append("EPS 品質需關注業外佔比。")

        if fx_margin_impact is not None and fx_margin_impact < -0.3:
            conclusion_parts.append(
                f"匯率逆風下毛利率仍創高，本業獲利能力被低估。"
                f"若未來台幣回貶，毛利率有額外上行空間。"
            )
        elif fx_margin_impact is not None and fx_margin_impact > 0.3:
            conclusion_parts.append("毛利率部分受惠於台幣貶值，需區分本業與匯率貢獻。")

        conclusion = "".join(conclusion_parts)

        return "\n".join([
            "### 財務 Agent 分析報告",
            f"數據來源：{self.source}、{self.revenue_source}、{self.fx_source}",
            f"分析日期：{analysis_date}",
            "",
            "**【三率趨勢】**",
            *metric_lines,
            f"→ 綜合判斷：{trend['summary']}",
            "",
            "**【驅動力判斷】**",
            f"→ 類型：{driver['type']}",
            f"→ 說明：{driver['description']}",
            "",
            "**【EPS 品質拆解】**",
            f"- 最新季 EPS：{num(eps_quality.get('eps'))} 元",
            f"- 本業貢獻 EPS：{num(eps_quality.get('core_eps'))} 元",
            f"- 業外收益佔比：{pct(eps_quality.get('nonop_ratio'))}（{eps_quality['nonop_marker']}）",
            "",
            "**【匯率敏感度分析】**",
            f"- 匯率方向：{eps_quality['fx_marker']}",
            f"- 對 EPS 估計影響：{fx_text}",
            f"- 對毛利率估計影響：{fx_margin_text}",
            f"- 匯率調整後毛利率：{fx_adjusted_text}（排除匯率因素後的本業估計值）",
            fx_insight,
            f"→ 盈餘品質結論：{eps_quality['quality_status']}",
            "",
            "**【營收基期修正】**",
            f"- 單月 YoY：{pct(revenue_effect.get('single_yoy'))}",
            f"- 3 個月累計 YoY：{pct(revenue_effect.get('three_month_yoy'))}",
            f"→ 基期影響評估：{base_text}",
            "",
            "**【財務面綜合結論】**",
            conclusion,
        ])
