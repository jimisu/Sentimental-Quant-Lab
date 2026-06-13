"""
Tests for tsmc_financial_agent.py — QuarterlyFinancialAgent

Covers:
- __init__ attribute assignment
- summarize()
- _format_quarter() static method
- _safe_float() static method
- _get_record_value() static method
- _records_to_latest_quarter()
- analyze_margin_trend() — empty, insufficient, all-uptrend, mixed, all-falling
- analyze_margins() — empty, insufficient, all-uptrend, mixed
- analyze_margin_driver() — Type A, A+fx, B, C, C+fx
- analyze_eps_quality() — no data, complete data with FX, partial data
- analyze_revenue_base_effect() — no data, with data, base effect detection
- build_structured_report() — all sections present, minimal data
"""

import datetime as dt
from unittest import TestCase

import pytest

from tsmc_financial_agent import QuarterlyFinancialAgent


# ──────────────────────────────────────────────────────────────────────
# Module-level data helpers (not fixtures — plain functions for reuse)
# ──────────────────────────────────────────────────────────────────────

def _three_quarters_rising():
    return {
        "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
        "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
        "2025Q3": {"gross_margin": 52.0, "operating_margin": 42.0, "net_margin": 36.0},
    }


def _three_quarters_mixed():
    return {
        "2026Q1": {"gross_margin": 58.0, "operating_margin": 40.0, "net_margin": 36.0},
        "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 36.0},
        "2025Q3": {"gross_margin": 52.0, "operating_margin": 42.0, "net_margin": 33.0},
    }


def _three_quarters_all_falling():
    return {
        "2026Q1": {"gross_margin": 50.0, "operating_margin": 40.0, "net_margin": 35.0},
        "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
        "2025Q3": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
    }


def _sample_financial_records():
    return [
        {"date": "2026-03-31", "type": "gross_margin", "value": "58.0"},
        {"date": "2026-03-31", "type": "operating_margin", "value": "48.0"},
        {"date": "2026-03-31", "type": "net_margin", "value": "42.0"},
        {"date": "2026-03-31", "type": "EPS", "value": "9.5"},
        {"date": "2026-03-31", "type": "PreTaxIncome", "value": "250000"},
        {"date": "2026-03-31", "type": "TotalNonoperatingIncomeAndExpense", "value": "10000"},
        {"date": "2026-03-31", "type": "TAX", "value": "30000"},
        {"date": "2026-03-31", "type": "EquityAttributableToOwnersOfParent", "value": "230000"},
        {"date": "2026-03-31", "type": "IncomeAfterTaxes", "value": "220000"},
    ]


def _sample_revenue_records():
    records = []
    for m in range(1, 13):
        records.append({"revenue_year": 2024, "revenue_month": m, "revenue": 200000 + m * 5000})
    for m in range(1, 7):
        records.append({"revenue_year": 2025, "revenue_month": m, "revenue": 220000 + m * 6000})
    return records


def _revenue_records_base_effect():
    records = []
    records.append({"revenue_year": 2024, "revenue_month": 6, "revenue": 50000})
    records.append({"revenue_year": 2024, "revenue_month": 5, "revenue": 300000})
    records.append({"revenue_year": 2024, "revenue_month": 4, "revenue": 280000})
    records.append({"revenue_year": 2024, "revenue_month": 3, "revenue": 260000})
    records.append({"revenue_year": 2025, "revenue_month": 6, "revenue": 250000})
    records.append({"revenue_year": 2025, "revenue_month": 5, "revenue": 310000})
    records.append({"revenue_year": 2025, "revenue_month": 4, "revenue": 290000})
    records.append({"revenue_year": 2025, "revenue_month": 3, "revenue": 270000})
    return records


# ──────────────────────────────────────────────────────────────────────
# Test class
# ──────────────────────────────────────────────────────────────────────

class TestQuarterlyFinancialAgent(TestCase):
    """Tests for QuarterlyFinancialAgent."""

    def setUp(self):
        """Create a fresh agent for each test."""
        self.agent = QuarterlyFinancialAgent()

    # ── __init__ ──────────────────────────────────────────────────

    def test_init_sets_attributes(self):
        """__init__ should set name, source, logic, revenue_source, fx_source."""
        agent = QuarterlyFinancialAgent()
        self.assertEqual(agent.name, "財務分析 Agent")
        self.assertEqual(agent.source, "FinMind 財務報表資料集 (TaiwanStockFinancialStatements)")
        self.assertEqual(
            agent.logic,
            "監控毛利率、營業利益率與稅後淨利率之季度趨勢。檢查最新季度是否達成『三率持續上升』之強勢基本面訊號。",
        )
        self.assertEqual(agent.revenue_source, "FinMind 月營收資料集 (TaiwanStockMonthRevenue)")
        self.assertEqual(agent.fx_source, "Yahoo Finance (TWD=X)")

    # ── summarize ─────────────────────────────────────────────────

    def test_summarize_wraps_analysis(self):
        """summarize() should return formatted string with agent name."""
        result = self.agent.summarize("三率持續上升")
        self.assertEqual(result, "[財務分析 Agent] 報告摘要: 三率持續上升")

    def test_summarize_empty_string(self):
        """summarize() with empty string should still wrap."""
        result = self.agent.summarize("")
        self.assertEqual(result, "[財務分析 Agent] 報告摘要: ")

    # ── _format_quarter ───────────────────────────────────────────

    def test_format_quarter_tuple(self):
        """_format_quarter with (year, quarter) tuple should return YYYYQn."""
        self.assertEqual(QuarterlyFinancialAgent._format_quarter((2026, 1)), "2026Q1")
        self.assertEqual(QuarterlyFinancialAgent._format_quarter((2025, 4)), "2025Q4")

    def test_format_quarter_string_passthrough(self):
        """_format_quarter with string should return str(key)."""
        self.assertEqual(QuarterlyFinancialAgent._format_quarter("2026Q1"), "2026Q1")

    def test_format_quarter_int_passthrough(self):
        """_format_quarter with non-tuple should return str(key)."""
        self.assertEqual(QuarterlyFinancialAgent._format_quarter(42), "42")

    def test_format_quarter_single_element_tuple(self):
        """_format_quarter with single-element tuple should return str(key)."""
        self.assertEqual(QuarterlyFinancialAgent._format_quarter((2026,)), "(2026,)")

    def test_format_quarter_three_element_tuple(self):
        """_format_quarter with 3-element tuple should return str(key) (not exactly 2)."""
        self.assertEqual(QuarterlyFinancialAgent._format_quarter((2026, 1, "extra")), "(2026, 1, 'extra')")

    # ── _safe_float ───────────────────────────────────────────────

    def test_safe_float_none(self):
        """_safe_float(None) should return None."""
        self.assertIsNone(QuarterlyFinancialAgent._safe_float(None))

    def test_safe_float_valid_float(self):
        """_safe_float with valid float string should return float."""
        self.assertEqual(QuarterlyFinancialAgent._safe_float("3.14"), 3.14)

    def test_safe_float_valid_int(self):
        """_safe_float with int should return float."""
        result = QuarterlyFinancialAgent._safe_float(42)
        self.assertEqual(result, 42.0)
        self.assertIsInstance(result, float)

    def test_safe_float_invalid_string(self):
        """_safe_float with non-numeric string should return None."""
        self.assertIsNone(QuarterlyFinancialAgent._safe_float("abc"))

    def test_safe_float_empty_string(self):
        """_safe_float with empty string should return None."""
        self.assertIsNone(QuarterlyFinancialAgent._safe_float(""))

    def test_safe_float_already_float(self):
        """_safe_float with float input should return same float."""
        self.assertEqual(QuarterlyFinancialAgent._safe_float(3.14), 3.14)

    def test_safe_float_negative(self):
        """_safe_float with negative number should work."""
        self.assertEqual(QuarterlyFinancialAgent._safe_float(-5.5), -5.5)

    def test_safe_float_list_raises(self):
        """_safe_float with list should return None (TypeError caught)."""
        self.assertIsNone(QuarterlyFinancialAgent._safe_float([1, 2]))

    def test_safe_float_zero(self):
        """_safe_float(0) should return 0.0."""
        self.assertEqual(QuarterlyFinancialAgent._safe_float(0), 0.0)

    def test_safe_float_numeric_string_int(self):
        """_safe_float with numeric string of an integer should return float."""
        self.assertEqual(QuarterlyFinancialAgent._safe_float("42"), 42.0)

    # ── _get_record_value ─────────────────────────────────────────

    def test_get_record_value_present(self):
        """_get_record_value should return float for existing key."""
        records = {"gross_margin": "55.0", "EPS": "9.5"}
        self.assertEqual(QuarterlyFinancialAgent._get_record_value(records, "gross_margin"), 55.0)

    def test_get_record_value_missing(self):
        """_get_record_value should return None for missing key."""
        records = {"gross_margin": "55.0"}
        self.assertIsNone(QuarterlyFinancialAgent._get_record_value(records, "EPS"))

    def test_get_record_value_none_value(self):
        """_get_record_value should return None when value is None."""
        records = {"gross_margin": None}
        self.assertIsNone(QuarterlyFinancialAgent._get_record_value(records, "gross_margin"))

    def test_get_record_value_invalid_value(self):
        """_get_record_value should return None for non-numeric value."""
        records = {"gross_margin": "N/A"}
        self.assertIsNone(QuarterlyFinancialAgent._get_record_value(records, "gross_margin"))

    def test_get_record_value_numeric_value(self):
        """_get_record_value with already-numeric value should return float."""
        records = {"gross_margin": 55.0}
        self.assertEqual(QuarterlyFinancialAgent._get_record_value(records, "gross_margin"), 55.0)

    # ── _records_to_latest_quarter ────────────────────────────────

    def test_records_to_latest_quarter_empty(self):
        """Empty records should return (None, {})."""
        quarter, data = self.agent._records_to_latest_quarter([])
        self.assertIsNone(quarter)
        self.assertEqual(data, {})

    def test_records_to_latest_quarter_none(self):
        """None records should return (None, {})."""
        quarter, data = self.agent._records_to_latest_quarter(None)
        self.assertIsNone(quarter)
        self.assertEqual(data, {})

    def test_records_to_latest_quarter_normal(self):
        """Normal records should return latest quarter key and data dict."""
        records = [
            {"date": "2025-09-30", "type": "gross_margin", "value": "52.0"},
            {"date": "2025-12-31", "type": "gross_margin", "value": "55.0"},
            {"date": "2025-12-31", "type": "EPS", "value": "9.0"},
        ]
        quarter, data = self.agent._records_to_latest_quarter(records)
        self.assertEqual(quarter, "2025Q4")
        self.assertEqual(data["gross_margin"], 55.0)
        self.assertEqual(data["EPS"], 9.0)

    def test_records_to_latest_quarter_missing_date(self):
        """Records with missing date should be skipped."""
        records = [
            {"date": None, "type": "gross_margin", "value": "52.0"},
            {"date": "2025-06-30", "type": "gross_margin", "value": "50.0"},
        ]
        quarter, data = self.agent._records_to_latest_quarter(records)
        self.assertEqual(quarter, "2025Q2")
        self.assertEqual(data["gross_margin"], 50.0)

    def test_records_to_latest_quarter_missing_type(self):
        """Records with missing type should be skipped."""
        records = [
            {"date": "2025-06-30", "type": None, "value": "52.0"},
            {"date": "2025-06-30", "type": "gross_margin", "value": "50.0"},
        ]
        quarter, data = self.agent._records_to_latest_quarter(records)
        self.assertEqual(quarter, "2025Q2")
        self.assertEqual(data["gross_margin"], 50.0)

    def test_records_to_latest_quarter_missing_value(self):
        """Records with None value should be skipped."""
        records = [
            {"date": "2025-06-30", "type": "gross_margin", "value": None},
            {"date": "2025-06-30", "type": "gross_margin", "value": "50.0"},
        ]
        quarter, data = self.agent._records_to_latest_quarter(records)
        self.assertEqual(quarter, "2025Q2")
        self.assertEqual(data["gross_margin"], 50.0)

    def test_records_to_latest_quarter_invalid_date(self):
        """Records with unparseable date should be skipped."""
        records = [
            {"date": "invalid", "type": "gross_margin", "value": "52.0"},
            {"date": "2025-03-31", "type": "gross_margin", "value": "50.0"},
        ]
        quarter, data = self.agent._records_to_latest_quarter(records)
        self.assertEqual(quarter, "2025Q1")

    def test_records_to_latest_quarter_multiple_types(self):
        """Multiple statement types in same quarter should all be collected."""
        records = [
            {"date": "2026-03-31", "type": "gross_margin", "value": "58.0"},
            {"date": "2026-03-31", "type": "operating_margin", "value": "48.0"},
            {"date": "2026-03-31", "type": "net_margin", "value": "42.0"},
        ]
        quarter, data = self.agent._records_to_latest_quarter(records)
        self.assertEqual(quarter, "2026Q1")
        self.assertEqual(len(data), 3)
        self.assertEqual(data["gross_margin"], 58.0)
        self.assertEqual(data["operating_margin"], 48.0)
        self.assertEqual(data["net_margin"], 42.0)

    def test_records_to_latest_quarter_last_writer_wins(self):
        """Two records of same type in same quarter: last one wins."""
        records = [
            {"date": "2025-12-31", "type": "gross_margin", "value": "52.0"},
            {"date": "2025-12-31", "type": "gross_margin", "value": "60.0"},
        ]
        quarter, data = self.agent._records_to_latest_quarter(records)
        self.assertEqual(data["gross_margin"], 60.0)

    # ── analyze_margin_trend ──────────────────────────────────────

    def test_analyze_margin_trend_empty(self):
        """Empty data should return warning status and 'no data' message."""
        result = self.agent.analyze_margin_trend({})
        self.assertEqual(result["status"], "⚠️")
        self.assertEqual(result["summary"], "查無季度財務資料。")
        self.assertEqual(result["metrics"], [])
        self.assertEqual(result["divergences"], [])

    def test_analyze_margin_trend_none(self):
        """None data (falsy) should return warning status."""
        result = self.agent.analyze_margin_trend(None)
        self.assertEqual(result["status"], "⚠️")
        self.assertEqual(result["summary"], "查無季度財務資料。")

    def test_analyze_margin_trend_insufficient(self):
        """Less than 3 quarters should return 'insufficient data' message."""
        data = {
            "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
        }
        result = self.agent.analyze_margin_trend(data)
        self.assertEqual(result["status"], "⚠️")
        self.assertEqual(result["summary"], "資料不足三季，無法判斷持續趨勢。")

    def test_analyze_margin_trend_all_rising(self):
        """All 3 margins rising for 3 quarters should return success."""
        result = self.agent.analyze_margin_trend(_three_quarters_rising())
        self.assertEqual(result["status"], "✅")
        self.assertEqual(result["summary"], "✅ 多頭：三率持續上升")
        self.assertEqual(len(result["metrics"]), 3)
        self.assertEqual(result["divergences"], [])
        for m in result["metrics"]:
            self.assertEqual(m["marker"], "✅ 連續兩季上升")

    def test_analyze_margin_trend_mixed(self):
        """Mixed trends should return warning with divergences listed."""
        result = self.agent.analyze_margin_trend(_three_quarters_mixed())
        self.assertEqual(result["status"], "⚠️")
        self.assertEqual(result["summary"], "⚠️ 警示：三率出現分歧")
        self.assertTrue(len(result["divergences"]) > 0)

    def test_analyze_margin_trend_all_falling(self):
        """All falling should return warning with all 3 in divergences."""
        result = self.agent.analyze_margin_trend(_three_quarters_all_falling())
        self.assertEqual(result["status"], "⚠️")
        self.assertEqual(len(result["divergences"]), 3)

    def test_analyze_margin_trend_metric_structure(self):
        """Each metric entry should have label, quarter labels, values, and marker."""
        result = self.agent.analyze_margin_trend(_three_quarters_rising())
        for m in result["metrics"]:
            self.assertIn("label", m)
            self.assertIn("q0_label", m)
            self.assertIn("q1_label", m)
            self.assertIn("q2_label", m)
            self.assertIn("q0", m)
            self.assertIn("q1", m)
            self.assertIn("q2", m)
            self.assertIn("marker", m)

    def test_analyze_margin_trend_divergences_deduplicated(self):
        """Divergences should be sorted and deduplicated."""
        data = {
            "2026Q1": {"gross_margin": 50.0, "operating_margin": 40.0, "net_margin": 35.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
            "2025Q3": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
        }
        result = self.agent.analyze_margin_trend(data)
        self.assertEqual(result["divergences"], sorted(set(result["divergences"])))

    def test_analyze_margin_trend_with_none_values(self):
        """Quarters with None margin values should not crash."""
        data = {
            "2026Q1": {"gross_margin": None, "operating_margin": 48.0, "net_margin": 42.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": None, "net_margin": 39.0},
            "2025Q3": {"gross_margin": 52.0, "operating_margin": 42.0, "net_margin": None},
        }
        result = self.agent.analyze_margin_trend(data)
        self.assertEqual(result["status"], "⚠️")
        self.assertEqual(len(result["metrics"]), 3)

    def test_analyze_margin_trend_two_quarters_only(self):
        """Exactly 2 quarters should be insufficient."""
        data = {
            "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
        }
        result = self.agent.analyze_margin_trend(data)
        self.assertIn("不足三季", result["summary"])

    def test_analyze_margin_trend_exactly_three_quarters(self):
        """Exactly 3 quarters should be sufficient for trend analysis."""
        result = self.agent.analyze_margin_trend(_three_quarters_rising())
        self.assertEqual(result["status"], "✅")

    # ── analyze_margins ───────────────────────────────────────────

    def test_analyze_margins_empty(self):
        """Empty data should return 'no data' string."""
        result = self.agent.analyze_margins({})
        self.assertEqual(result, "查無季度財務資料。")

    def test_analyze_margins_none(self):
        """None data should return 'no data' string."""
        result = self.agent.analyze_margins(None)
        self.assertEqual(result, "查無季度財務資料。")

    def test_analyze_margins_insufficient(self):
        """Less than 3 quarters should return insufficient message."""
        data = {
            "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
        }
        result = self.agent.analyze_margins(data)
        self.assertIn("資料不足三季", result)

    def test_analyze_margins_all_rising(self):
        """All rising should return bullish status."""
        result = self.agent.analyze_margins(_three_quarters_rising())
        self.assertIn("【多頭：三率持續同步上升】", result)
        self.assertIn("數據來源", result)
        self.assertIn("分析邏輯", result)

    def test_analyze_margins_mixed(self):
        """Mixed trends should return warning status."""
        result = self.agent.analyze_margins(_three_quarters_mixed())
        self.assertIn("【警告：成長趨勢出現分歧】", result)

    def test_analyze_margins_contains_source(self):
        """Result should contain data source info."""
        result = self.agent.analyze_margins(_three_quarters_rising())
        self.assertIn("FinMind", result)

    def test_analyze_margins_four_quarters(self):
        """4 quarters of data — only the latest 3 should be used."""
        data = {
            "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
            "2025Q3": {"gross_margin": 52.0, "operating_margin": 42.0, "net_margin": 36.0},
            "2025Q2": {"gross_margin": 50.0, "operating_margin": 40.0, "net_margin": 34.0},
        }
        result = self.agent.analyze_margins(data)
        self.assertIn("【多頭：三率持續同步上升】", result)

    def test_analyze_margins_single_quarter(self):
        """Single quarter should return insufficient message."""
        data = {
            "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
        }
        result = self.agent.analyze_margins(data)
        self.assertIn("資料不足三季", result)

    # ── analyze_margin_driver ─────────────────────────────────────

    def test_analyze_margin_driver_type_a(self):
        """Type A: advanced_delta > 2 should return structural uptrend."""
        process_mix = {
            "q1": {"advanced": 70.0},
            "q0": {"advanced": 74.0},
        }
        result = self.agent.analyze_margin_driver(process_mix=process_mix)
        self.assertEqual(result["type"], "A")
        self.assertIn("結構性上升", result["label"])
        self.assertEqual(result["advanced_delta"], 4.0)
        self.assertFalse(result["fx_bonus"])

    def test_analyze_margin_driver_type_a_fx_bonus(self):
        """Type A with fx_bonus: advanced_delta > 1 and headwind should still be Type A."""
        process_mix = {
            "q1": {"advanced": 70.0},
            "q0": {"advanced": 72.0},
        }
        result = self.agent.analyze_margin_driver(
            process_mix=process_mix,
            fx_direction="headwind",
            fx_margin_impact=-0.5,
        )
        self.assertEqual(result["type"], "A")
        self.assertIn("結構性上升", result["label"])
        self.assertTrue(result["fx_bonus"])
        self.assertIn("台幣升值逆風", result["description"])

    def test_analyze_margin_driver_type_a_no_fx_bonus_sharp_rise(self):
        """Type A with delta > 2 but no fx_bonus (tailwind) should not mention FX."""
        process_mix = {
            "q1": {"advanced": 70.0},
            "q0": {"advanced": 74.0},
        }
        result = self.agent.analyze_margin_driver(
            process_mix=process_mix,
            fx_direction="tailwind",
            fx_margin_impact=0.5,
        )
        self.assertEqual(result["type"], "A")
        self.assertFalse(result["fx_bonus"])
        self.assertIn("高於 2pp 門檻", result["description"])

    def test_analyze_margin_driver_type_b(self):
        """Type B: delta <= 2 but capacity_utilization_up should be cyclical."""
        process_mix = {
            "q1": {"advanced": 70.0},
            "q0": {"advanced": 71.0},
        }
        result = self.agent.analyze_margin_driver(
            process_mix=process_mix,
            capacity_utilization_up=True,
        )
        self.assertEqual(result["type"], "B")
        self.assertIn("週期性上升", result["label"])

    def test_analyze_margin_driver_type_b_with_fx_bonus(self):
        """Type B with fx_bonus should include FX note in description."""
        process_mix = {
            "q1": {"advanced": 70.0},
            "q0": {"advanced": 71.0},
        }
        result = self.agent.analyze_margin_driver(
            process_mix=process_mix,
            capacity_utilization_up=True,
            fx_direction="headwind",
            fx_margin_impact=-0.5,
        )
        self.assertEqual(result["type"], "B")
        self.assertTrue(result["fx_bonus"])
        self.assertIn("台幣升值逆風", result["description"])

    def test_analyze_margin_driver_type_c_no_data(self):
        """Type C: no process mix data at all."""
        result = self.agent.analyze_margin_driver()
        self.assertEqual(result["type"], "C")
        self.assertIn("驅動力不明", result["label"])
        self.assertIsNone(result["advanced_delta"])
        self.assertFalse(result["fx_bonus"])

    def test_analyze_margin_driver_type_c_with_fx_bonus(self):
        """Type C with fx_bonus: no data but headwind FX."""
        result = self.agent.analyze_margin_driver(
            fx_direction="headwind",
            fx_margin_impact=-0.5,
        )
        self.assertEqual(result["type"], "C")
        self.assertTrue(result["fx_bonus"])
        self.assertIn("台幣升值逆風", result["description"])

    def test_analyze_margin_driver_type_c_delta_not_significant(self):
        """Type C: delta present but <= 2 and no capacity_utilization_up."""
        process_mix = {
            "q1": {"advanced": 70.0},
            "q0": {"advanced": 71.0},
        }
        result = self.agent.analyze_margin_driver(
            process_mix=process_mix,
            capacity_utilization_up=False,
        )
        self.assertEqual(result["type"], "C")
        self.assertIn("驅動力不明", result["label"])

    def test_analyze_margin_driver_fx_not_headwind(self):
        """fx_direction='tailwind' should not trigger fx_bonus."""
        result = self.agent.analyze_margin_driver(
            fx_direction="tailwind",
            fx_margin_impact=0.5,
        )
        self.assertFalse(result["fx_bonus"])

    def test_analyze_margin_driver_fx_impact_not_negative_enough(self):
        """fx_margin_impact=-0.2 should not trigger fx_bonus (needs < -0.3)."""
        result = self.agent.analyze_margin_driver(
            fx_direction="headwind",
            fx_margin_impact=-0.2,
        )
        self.assertFalse(result["fx_bonus"])

    def test_analyze_margin_driver_fx_impact_at_boundary(self):
        """fx_margin_impact=-0.3 should not trigger fx_bonus (needs strictly < -0.3)."""
        result = self.agent.analyze_margin_driver(
            fx_direction="headwind",
            fx_margin_impact=-0.3,
        )
        self.assertFalse(result["fx_bonus"])

    def test_analyze_margin_driver_fx_impact_just_over_boundary(self):
        """fx_margin_impact=-0.31 should trigger fx_bonus."""
        result = self.agent.analyze_margin_driver(
            fx_direction="headwind",
            fx_margin_impact=-0.31,
        )
        self.assertTrue(result["fx_bonus"])

    def test_analyze_margin_driver_alternative_keys(self):
        """Should accept 'previous' and 'latest' as alternative keys."""
        process_mix = {
            "previous": {"advanced": 70.0},
            "latest": {"advanced": 74.0},
        }
        result = self.agent.analyze_margin_driver(process_mix=process_mix)
        self.assertEqual(result["type"], "A")
        self.assertEqual(result["advanced_delta"], 4.0)

    def test_analyze_margin_driver_composite_advanced(self):
        """Should sum n2/n3/n5/n7 when 'advanced' key is not present."""
        process_mix = {
            "q1": {"n2": 30.0, "n3": 20.0, "n5": 10.0, "n7": 5.0},
            "q0": {"n2": 35.0, "n3": 25.0, "n5": 12.0, "n7": 8.0},
        }
        result = self.agent.analyze_margin_driver(process_mix=process_mix)
        # q1 sum = 65, q0 sum = 80, delta = 15 > 2 => Type A
        self.assertEqual(result["type"], "A")
        self.assertEqual(result["advanced_delta"], 15.0)

    def test_analyze_margin_driver_empty_process_mix(self):
        """Empty process_mix dict should return Type C."""
        result = self.agent.analyze_margin_driver(process_mix={})
        self.assertEqual(result["type"], "C")
        self.assertIsNone(result["advanced_delta"])

    def test_analyze_margin_driver_fx_none_direction(self):
        """fx_direction=None should not trigger fx_bonus."""
        result = self.agent.analyze_margin_driver(
            fx_direction=None,
            fx_margin_impact=-1.0,
        )
        self.assertFalse(result["fx_bonus"])

    def test_analyze_margin_driver_fx_none_impact(self):
        """fx_margin_impact=None should not trigger fx_bonus."""
        result = self.agent.analyze_margin_driver(
            fx_direction="headwind",
            fx_margin_impact=None,
        )
        self.assertFalse(result["fx_bonus"])

    # ── analyze_eps_quality ───────────────────────────────────────

    def test_analyze_eps_quality_no_data(self):
        """No data should return None eps and default quality status."""
        result = self.agent.analyze_eps_quality()
        self.assertIsNone(result["eps"])
        self.assertEqual(result["quality_status"], "✅ 良好")
        self.assertEqual(result["nonop_marker"], "⚪ 業外資料不足")
        self.assertEqual(result["fx_marker"], "⚪ 匯率資料不足")
        self.assertIsNone(result["fx_direction"])

    def test_analyze_eps_quality_complete_data(self):
        """Complete financial records should compute EPS, core_eps, nonop_ratio."""
        result = self.agent.analyze_eps_quality(financial_records=_sample_financial_records())
        self.assertIsNotNone(result["eps"])
        self.assertEqual(result["eps"], 9.5)
        self.assertIsNotNone(result["quarter"])
        self.assertEqual(result["quality_status"], "✅ 良好")

    def test_analyze_eps_quality_nonop_ratio_high(self):
        """nonop_ratio > 15 should trigger warning marker."""
        records = [
            {"date": "2026-03-31", "type": "EPS", "value": "9.5"},
            {"date": "2026-03-31", "type": "PreTaxIncome", "value": "100000"},
            {"date": "2026-03-31", "type": "TotalNonoperatingIncomeAndExpense", "value": "20000"},
            {"date": "2026-03-31", "type": "TAX", "value": "10000"},
            {"date": "2026-03-31", "type": "EquityAttributableToOwnersOfParent", "value": "90000"},
        ]
        result = self.agent.analyze_eps_quality(financial_records=records)
        # nonop_ratio = 20000/100000 * 100 = 20% > 15
        self.assertIsNotNone(result["nonop_ratio"])
        self.assertTrue(result["nonop_ratio"] > 15)
        self.assertEqual(result["nonop_marker"], "⚠️ 業外收益偏高，盈餘品質需關注")
        self.assertEqual(result["quality_status"], "⚠️ 需關注")

    def test_analyze_eps_quality_nonop_ratio_low(self):
        """nonop_ratio < 5 should show 'good quality' marker."""
        records = [
            {"date": "2026-03-31", "type": "EPS", "value": "9.5"},
            {"date": "2026-03-31", "type": "PreTaxIncome", "value": "100000"},
            {"date": "2026-03-31", "type": "TotalNonoperatingIncomeAndExpense", "value": "3000"},
            {"date": "2026-03-31", "type": "TAX", "value": "10000"},
            {"date": "2026-03-31", "type": "EquityAttributableToOwnersOfParent", "value": "90000"},
        ]
        result = self.agent.analyze_eps_quality(financial_records=records)
        # nonop_ratio = 3000/100000 * 100 = 3% < 5
        self.assertTrue(result["nonop_ratio"] < 5)
        self.assertEqual(result["nonop_marker"], "✅ 盈餘品質良好，主要來自本業")

    def test_analyze_eps_quality_nonop_ratio_mid(self):
        """nonop_ratio between 5 and 15 should show 'controllable' marker."""
        records = [
            {"date": "2026-03-31", "type": "EPS", "value": "9.5"},
            {"date": "2026-03-31", "type": "PreTaxIncome", "value": "100000"},
            {"date": "2026-03-31", "type": "TotalNonoperatingIncomeAndExpense", "value": "10000"},
            {"date": "2026-03-31", "type": "TAX", "value": "10000"},
            {"date": "2026-03-31", "type": "EquityAttributableToOwnersOfParent", "value": "90000"},
        ]
        result = self.agent.analyze_eps_quality(financial_records=records)
        # nonop_ratio = 10%
        self.assertTrue(5 <= result["nonop_ratio"] <= 15)
        self.assertEqual(result["nonop_marker"], "✅ 業外收益佔比可控")

    def test_analyze_eps_quality_fx_tailwind(self):
        """USD/TWD up > 0.5 should be tailwind."""
        fx = {"previous": 31.0, "latest": 32.0}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertEqual(result["fx_direction"], "tailwind")
        self.assertIn("匯兌助力", result["fx_marker"])
        self.assertIsNotNone(result["fx_eps_impact"])
        self.assertTrue(result["fx_eps_impact"] > 0)

    def test_analyze_eps_quality_fx_headwind(self):
        """USD/TWD down < -0.5 should be headwind."""
        fx = {"previous": 32.0, "latest": 31.0}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertEqual(result["fx_direction"], "headwind")
        self.assertIn("匯率逆風", result["fx_marker"])
        self.assertTrue(result["fx_eps_impact"] < 0)

    def test_analyze_eps_quality_fx_neutral(self):
        """USD/TWD change within +/-0.5 should be neutral."""
        fx = {"previous": 31.5, "latest": 31.7}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertEqual(result["fx_direction"], "neutral")
        self.assertIn("中性", result["fx_marker"])

    def test_analyze_eps_quality_fx_adjusted_gm(self):
        """FX-adjusted gross margin should be computed when both GM and FX data present."""
        fx = {"previous": 32.0, "latest": 31.0}  # headwind
        result = self.agent.analyze_eps_quality(
            fx_averages=fx,
            latest_gross_margin=55.0,
        )
        self.assertIsNotNone(result["fx_adjusted_gm"])
        # fx_delta = -1.0, fx_margin_impact = -0.4, fx_adjusted_gm = 55.0 - (-0.4) = 55.4
        self.assertAlmostEqual(result["fx_adjusted_gm"], 55.4, places=2)

    def test_analyze_eps_quality_fx_adjusted_gm_from_records(self):
        """FX-adjusted GM should use gross_margin from financial records."""
        records = [
            {"date": "2026-03-31", "type": "gross_margin", "value": "55.0"},
            {"date": "2026-03-31", "type": "EPS", "value": "9.5"},
        ]
        fx = {"previous": 32.0, "latest": 31.0}
        result = self.agent.analyze_eps_quality(financial_records=records, fx_averages=fx)
        self.assertEqual(result["latest_gm"], 55.0)
        self.assertIsNotNone(result["fx_adjusted_gm"])

    def test_analyze_eps_quality_fx_no_gm(self):
        """Without GM data, fx_adjusted_gm should be None."""
        fx = {"previous": 32.0, "latest": 31.0}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertIsNone(result["fx_adjusted_gm"])
        self.assertIsNone(result["latest_gm"])

    def test_analyze_eps_quality_latest_financials_override(self):
        """latest_financials should be used when financial_records is None."""
        latest = {"EPS": "10.0", "gross_margin": "56.0"}
        result = self.agent.analyze_eps_quality(latest_financials=latest)
        self.assertEqual(result["eps"], 10.0)

    def test_analyze_eps_quality_fx_boundary_exact(self):
        """fx_delta exactly 0.5 should be neutral (not tailwind)."""
        fx = {"previous": 31.0, "latest": 31.5}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertEqual(result["fx_direction"], "neutral")

    def test_analyze_eps_quality_fx_boundary_negative_exact(self):
        """fx_delta exactly -0.5 should be neutral (not headwind)."""
        fx = {"previous": 31.5, "latest": 31.0}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertEqual(result["fx_direction"], "neutral")

    def test_analyze_eps_quality_fx_just_over_tailwind(self):
        """fx_delta 0.51 should be tailwind."""
        fx = {"previous": 31.0, "latest": 31.51}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertEqual(result["fx_direction"], "tailwind")

    def test_analyze_eps_quality_fx_just_over_headwind(self):
        """fx_delta -0.51 should be headwind."""
        fx = {"previous": 31.51, "latest": 31.0}
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        self.assertEqual(result["fx_direction"], "headwind")

    def test_analyze_eps_quality_core_eps_calculation(self):
        """core_eps and nonop_eps should be calculated when all data present."""
        records = [
            {"date": "2026-03-31", "type": "EPS", "value": "10.0"},
            {"date": "2026-03-31", "type": "PreTaxIncome", "value": "100000"},
            {"date": "2026-03-31", "type": "TotalNonoperatingIncomeAndExpense", "value": "5000"},
            {"date": "2026-03-31", "type": "TAX", "value": "15000"},
            {"date": "2026-03-31", "type": "EquityAttributableToOwnersOfParent", "value": "85000"},
        ]
        result = self.agent.analyze_eps_quality(financial_records=records)
        self.assertIsNotNone(result["core_eps"])
        self.assertIsNotNone(result["nonop_eps"])
        # core_eps + nonop_eps should approximately equal EPS
        self.assertAlmostEqual(result["core_eps"] + result["nonop_eps"], 10.0, places=2)

    def test_analyze_eps_quality_no_pretax(self):
        """Without PreTaxIncome, nonop_ratio should be None."""
        records = [
            {"date": "2026-03-31", "type": "EPS", "value": "9.5"},
            {"date": "2026-03-31", "type": "TotalNonoperatingIncomeAndExpense", "value": "10000"},
        ]
        result = self.agent.analyze_eps_quality(financial_records=records)
        self.assertIsNone(result["nonop_ratio"])
        self.assertEqual(result["nonop_marker"], "⚪ 業外資料不足")

    def test_analyze_eps_quality_fx_margin_impact_sign(self):
        """fx_margin_impact sign should match fx_delta direction."""
        fx = {"previous": 32.0, "latest": 31.0}  # delta = -1.0
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        # fx_margin_impact = -1.0 * 0.4 = -0.4
        self.assertAlmostEqual(result["fx_margin_impact"], -0.4, places=2)

    def test_analyze_eps_quality_fx_eps_impact_sign(self):
        """fx_eps_impact sign should match fx_delta direction."""
        fx = {"previous": 32.0, "latest": 31.0}  # delta = -1.0
        result = self.agent.analyze_eps_quality(fx_averages=fx)
        # fx_eps_impact = -1.0 * 0.65 = -0.65
        self.assertAlmostEqual(result["fx_eps_impact"], -0.65, places=2)

    # ── analyze_revenue_base_effect ────────────────────────────────

    def test_analyze_revenue_base_effect_no_data(self):
        """No revenue records should return None values and 'no data' message."""
        result = self.agent.analyze_revenue_base_effect([])
        self.assertIsNone(result["single_yoy"])
        self.assertIsNone(result["three_month_yoy"])
        self.assertIsNone(result["base_effect"])
        self.assertEqual(result["message"], "查無月營收資料。")

    def test_analyze_revenue_base_effect_none(self):
        """None records should return 'no data' message."""
        result = self.agent.analyze_revenue_base_effect(None)
        self.assertEqual(result["message"], "查無月營收資料。")

    def test_analyze_revenue_base_effect_with_data(self):
        """With 12+ months of data, should compute YoY values."""
        result = self.agent.analyze_revenue_base_effect(_sample_revenue_records())
        self.assertIsNotNone(result["single_yoy"])
        self.assertIsNotNone(result["three_month_yoy"])
        self.assertIsNotNone(result["latest_month"])

    def test_analyze_revenue_base_effect_base_effect_detected(self):
        """When |single_yoy - three_month_yoy| > 10, base_effect should be True."""
        result = self.agent.analyze_revenue_base_effect(_revenue_records_base_effect())
        self.assertTrue(result["base_effect"])
        self.assertIn("基期", result["message"])

    def test_analyze_revenue_base_effect_no_base_effect(self):
        """When YoY values are close, base_effect should be False."""
        result = self.agent.analyze_revenue_base_effect(_sample_revenue_records())
        # These records have smooth growth, so base_effect should be False
        self.assertFalse(result["base_effect"])
        self.assertEqual(result["message"], "✅ 無明顯單月基期扭曲")

    def test_analyze_revenue_base_effect_missing_fields(self):
        """Records with missing fields should be skipped gracefully."""
        records = [
            {"revenue_year": None, "revenue_month": 1, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": None, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 1, "revenue": None},
        ]
        result = self.agent.analyze_revenue_base_effect(records)
        self.assertEqual(result["message"], "查無月營收資料。")

    def test_analyze_revenue_base_effect_latest_month_format(self):
        """latest_month should be in YYYY-MM format."""
        result = self.agent.analyze_revenue_base_effect(_sample_revenue_records())
        self.assertIn("-", result["latest_month"])
        parts = result["latest_month"].split("-")
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(parts[1]), 2)  # zero-padded month

    def test_analyze_revenue_base_effect_single_yoy_calculation(self):
        """Single YoY should be correctly computed as percentage."""
        records = [
            {"revenue_year": 2024, "revenue_month": 6, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 6, "revenue": 120000},
        ]
        result = self.agent.analyze_revenue_base_effect(records)
        # (120000 - 100000) / 100000 * 100 = 20%
        self.assertAlmostEqual(result["single_yoy"], 20.0, places=2)

    def test_analyze_revenue_base_effect_three_month_yoy(self):
        """Three-month YoY should use rolling 3-month sums."""
        records = [
            {"revenue_year": 2024, "revenue_month": 4, "revenue": 100000},
            {"revenue_year": 2024, "revenue_month": 5, "revenue": 100000},
            {"revenue_year": 2024, "revenue_month": 6, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 4, "revenue": 120000},
            {"revenue_year": 2025, "revenue_month": 5, "revenue": 120000},
            {"revenue_year": 2025, "revenue_month": 6, "revenue": 120000},
        ]
        result = self.agent.analyze_revenue_base_effect(records)
        # current_sum = 360000, previous_sum = 300000, yoy = 20%
        self.assertAlmostEqual(result["three_month_yoy"], 20.0, places=2)

    def test_analyze_revenue_base_effect_incomplete_three_month(self):
        """When 3-month window is incomplete, three_month_yoy should be None."""
        records = [
            {"revenue_year": 2024, "revenue_month": 6, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 5, "revenue": 120000},
            {"revenue_year": 2025, "revenue_month": 6, "revenue": 120000},
        ]
        result = self.agent.analyze_revenue_base_effect(records)
        # Missing 2025-04 and 2024-04/05 for the 3-month window
        self.assertIsNone(result["three_month_yoy"])

    def test_analyze_revenue_base_effect_zero_base(self):
        """When prior year revenue is 0, single_yoy should be None (avoid div by zero)."""
        records = [
            {"revenue_year": 2024, "revenue_month": 6, "revenue": 0},
            {"revenue_year": 2025, "revenue_month": 6, "revenue": 120000},
        ]
        result = self.agent.analyze_revenue_base_effect(records)
        self.assertIsNone(result["single_yoy"])

    def test_analyze_revenue_base_effect_single_month_only(self):
        """Single month with no prior year match should return None single_yoy."""
        records = [
            {"revenue_year": 2025, "revenue_month": 6, "revenue": 120000},
        ]
        result = self.agent.analyze_revenue_base_effect(records)
        self.assertIsNone(result["single_yoy"])

    def test_analyze_revenue_base_effect_base_effect_boundary(self):
        """When |single - 3mo| == 10 exactly, base_effect should be False (needs > 10)."""
        # Construct records where the difference is exactly 10
        records = [
            {"revenue_year": 2024, "revenue_month": 3, "revenue": 100000},
            {"revenue_year": 2024, "revenue_month": 4, "revenue": 100000},
            {"revenue_year": 2024, "revenue_month": 5, "revenue": 100000},
            {"revenue_year": 2024, "revenue_month": 6, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 3, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 4, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 5, "revenue": 100000},
            {"revenue_year": 2025, "revenue_month": 6, "revenue": 110000},
        ]
        result = self.agent.analyze_revenue_base_effect(records)
        # single_yoy = (110000 - 100000) / 100000 * 100 = 10%
        # 3mo current = 100000+100000+110000 = 310000
        # 3mo prev = 100000+100000+100000 = 300000
        # 3mo yoy = (310000 - 300000) / 300000 * 100 = 3.33%
        # |10 - 3.33| = 6.67 < 10 => no base effect
        self.assertFalse(result["base_effect"])

    # ── build_structured_report ───────────────────────────────────

    def test_build_structured_report_all_sections(self):
        """Report should contain all required section headers."""
        report = self.agent.build_structured_report(
            quarterly_data=_three_quarters_rising(),
            financial_records=_sample_financial_records(),
            revenue_records=_sample_revenue_records(),
        )
        self.assertIn("### 財務 Agent 分析報告", report)
        self.assertIn("【三率趨勢】", report)
        self.assertIn("【驅動力判斷】", report)
        self.assertIn("【EPS 品質拆解】", report)
        self.assertIn("【匯率敏感度分析】", report)
        self.assertIn("【營收基期修正】", report)
        self.assertIn("【財務面綜合結論】", report)

    def test_build_structured_report_data_sources(self):
        """Report should mention all data sources."""
        report = self.agent.build_structured_report(quarterly_data=_three_quarters_rising())
        self.assertIn("FinMind", report)
        self.assertIn("Yahoo Finance", report)

    def test_build_structured_report_analysis_date(self):
        """Report should include the analysis date."""
        report = self.agent.build_structured_report(
            quarterly_data=_three_quarters_rising(),
            analysis_date="2026-06-12",
        )
        self.assertIn("2026-06-12", report)

    def test_build_structured_report_default_date(self):
        """Without explicit date, report should use today's date."""
        today = dt.date.today().isoformat()
        report = self.agent.build_structured_report(quarterly_data=_three_quarters_rising())
        self.assertIn(today, report)

    def test_build_structured_report_minimal_data(self):
        """Report with empty data should still produce all sections."""
        report = self.agent.build_structured_report(quarterly_data={})
        self.assertIn("【三率趨勢】", report)
        self.assertIn("【驅動力判斷】", report)
        self.assertIn("【EPS 品質拆解】", report)
        self.assertIn("【匯率敏感度分析】", report)
        self.assertIn("【營收基期修正】", report)
        self.assertIn("【財務面綜合結論】", report)

    def test_build_structured_report_with_fx(self):
        """Report with FX data should show FX analysis."""
        report = self.agent.build_structured_report(
            quarterly_data=_three_quarters_rising(),
            fx_averages={"previous": 32.0, "latest": 31.0},
        )
        self.assertIn("匯率方向", report)
        self.assertIn("對 EPS 估計影響", report)
        self.assertIn("對毛利率估計影響", report)
        self.assertIn("匯率調整後毛利率", report)

    def test_build_structured_report_with_process_mix(self):
        """Report with process mix should show driver type."""
        report = self.agent.build_structured_report(
            quarterly_data=_three_quarters_rising(),
            process_mix={"q1": {"advanced": 70.0}, "q0": {"advanced": 74.0}},
        )
        self.assertIn("類型：A", report)

    def test_build_structured_report_conclusion_bullish(self):
        """With all-rising data, conclusion should mention strong fundamentals."""
        report = self.agent.build_structured_report(quarterly_data=_three_quarters_rising())
        self.assertTrue("三率持續同步上升" in report or "基本面強勁" in report)

    def test_build_structured_report_conclusion_bearish(self):
        """With all-falling data, conclusion should mention divergence."""
        report = self.agent.build_structured_report(quarterly_data=_three_quarters_all_falling())
        self.assertTrue("分歧" in report or "需持續追蹤" in report)

    def test_build_structured_report_eps_values(self):
        """Report should show EPS values from financial records."""
        report = self.agent.build_structured_report(
            quarterly_data=_three_quarters_rising(),
            financial_records=_sample_financial_records(),
        )
        self.assertIn("最新季 EPS", report)
        self.assertIn("本業貢獻 EPS", report)
        self.assertIn("業外收益佔比", report)

    def test_build_structured_report_revenue_values(self):
        """Report should show revenue YoY values."""
        report = self.agent.build_structured_report(
            quarterly_data=_three_quarters_rising(),
            revenue_records=_sample_revenue_records(),
        )
        self.assertIn("單月 YoY", report)
        self.assertIn("3 個月累計 YoY", report)
        self.assertIn("基期影響評估", report)

    def test_build_structured_report_fx_insight_headwind(self):
        """With FX headwind and GM data, report should include key finding insight."""
        quarterly = {
            "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
            "2025Q3": {"gross_margin": 52.0, "operating_margin": 42.0, "net_margin": 36.0},
        }
        report = self.agent.build_structured_report(
            quarterly_data=quarterly,
            fx_averages={"previous": 32.0, "latest": 31.0},
        )
        # Headwind with GM data should produce the key finding insight
        self.assertTrue("關鍵發現" in report or "Pricing Power" in report)

    def test_build_structured_report_fx_insight_tailwind(self):
        """With FX tailwind and GM data, report should mention tailwind effect."""
        quarterly = {
            "2026Q1": {"gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 42.0},
            "2025Q4": {"gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 39.0},
            "2025Q3": {"gross_margin": 52.0, "operating_margin": 42.0, "net_margin": 36.0},
        }
        report = self.agent.build_structured_report(
            quarterly_data=quarterly,
            fx_averages={"previous": 31.0, "latest": 32.0},
        )
        self.assertIn("貶值順風", report)

    def test_build_structured_report_with_all_params(self):
        """Report with all parameters should produce a complete report."""
        quarterly = _three_quarters_rising()
        report = self.agent.build_structured_report(
            quarterly_data=quarterly,
            financial_records=_sample_financial_records(),
            revenue_records=_sample_revenue_records(),
            process_mix={"q1": {"advanced": 70.0}, "q0": {"advanced": 74.0}},
            capacity_utilization_up=False,
            fx_averages={"previous": 32.0, "latest": 31.0},
            analysis_date="2026-06-12",
        )
        # Should be a non-empty string with all sections
        self.assertTrue(len(report) > 200)
        self.assertIn("### 財務 Agent 分析報告", report)
        self.assertIn("2026-06-12", report)
