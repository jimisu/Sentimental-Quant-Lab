"""
Unit tests for tsmc_signal_dashboard.py

Covers the pure utility functions and data-processing helpers in the dashboard module:
- build_cache_key: cache key sanitization
- write_circular_cache / read_latest_cache: filesystem cache with ring buffer
- get_cached_data: data-field extraction from cache
- read_fresh_cached_payload: TTL-based cache freshness check
- serialize_quarterly_margins / deserialize_quarterly_margins: key conversion
- parse_twse_int / parse_twse_float / parse_twse_date: TWSE string parsing
- get_recent_month_starts: month start date generation
- build_dataframe: DataFrame construction from revenue + margin data
- apply_color_logic: color coding rules for dashboard display

Uses unittest.TestCase style with pytest runner.
Filesystem operations use tempfile.mkdtemp() for isolation.
"""

import datetime as dt
import json
import os
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import tsmc_signal_dashboard as dash


class TestBuildCacheKey(unittest.TestCase):
    """Tests for build_cache_key()."""

    def test_alphanumeric_unchanged(self):
        result = dash.build_cache_key("finmind", "TaiwanStockMonthRevenue", "2330")
        self.assertEqual(result, "finmind_TaiwanStockMonthRevenue_2330")

    def test_special_chars_replaced(self):
        result = dash.build_cache_key("twse@report", "date=2026#01")
        self.assertEqual(result, "twse_report_date_2026_01")

    def test_empty_parts_skipped(self):
        result = dash.build_cache_key("key", None, "value")
        self.assertEqual(result, "key_value")

    def test_empty_string(self):
        result = dash.build_cache_key("")
        self.assertEqual(result, "")

    def test_unicode_replaced(self):
        result = dash.build_cache_key("中文", "key")
        self.assertEqual(result, "key")

    def test_dots_and_dashes_preserved(self):
        result = dash.build_cache_key("v1.0", "my-key")
        self.assertEqual(result, "v1.0_my-key")

    def test_leading_trailing_underscores_stripped(self):
        result = dash.build_cache_key("@@@key@@@")
        self.assertEqual(result, "key")

    def test_consecutive_special_chars_collapsed(self):
        result = dash.build_cache_key("a#$%b")
        self.assertEqual(result, "a_b")

    def test_single_part(self):
        result = dash.build_cache_key("single")
        self.assertEqual(result, "single")


class TestWriteCircularCache(unittest.TestCase):
    """Tests for write_circular_cache() and read_latest_cache()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="sq_test_")
        self._orig_cache_dir = dash.CACHE_DIR
        dash.CACHE_DIR = self.tmpdir

    def tearDown(self):
        dash.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read_back(self):
        payload = {"data": [1, 2, 3], "cached_at": "2026-01-01T00:00:00"}
        dash.write_circular_cache("test_key", payload)
        result = dash.read_latest_cache("test_key")
        self.assertEqual(result, payload)

    def test_read_missing_returns_none(self):
        result = dash.read_latest_cache("nonexistent_key")
        self.assertIsNone(result)

    def test_ring_buffer_keeps_latest_three(self):
        for i in range(5):
            dash.write_circular_cache("ring_key", {"index": i})
        prefix = "ring_key_"
        files = [f for f in os.listdir(self.tmpdir) if f.startswith(prefix) and f.endswith(".json")]
        self.assertEqual(len(files), 3)

    def test_ring_buffer_latest_is_most_recent(self):
        for i in range(5):
            dash.write_circular_cache("ring_key", {"index": i})
        result = dash.read_latest_cache("ring_key")
        self.assertEqual(result["index"], 4)

    def test_corrupt_json_returns_none(self):
        # Write a corrupt file directly
        filepath = os.path.join(self.tmpdir, "corrupt_key_20260101_000000_000000.json")
        with open(filepath, "w") as f:
            f.write("not valid json{{{")
        result = dash.read_latest_cache("corrupt_key")
        self.assertIsNone(result)

    def test_cache_dir_created_if_missing(self):
        subdir = os.path.join(self.tmpdir, "sub", "cache")
        dash.CACHE_DIR = subdir
        dash.write_circular_cache("deep_key", {"data": True})
        self.assertTrue(os.path.isdir(subdir))
        result = dash.read_latest_cache("deep_key")
        self.assertIsNotNone(result)


class TestGetCachedData(unittest.TestCase):
    """Tests for get_cached_data()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="sq_test_")
        self._orig_cache_dir = dash.CACHE_DIR
        dash.CACHE_DIR = self.tmpdir

    def tearDown(self):
        dash.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_data_field(self):
        payload = {"data": {"price": 900}, "cached_at": "2026-01-01T00:00:00"}
        dash.write_cache = dash.write_circular_cache
        dash.write_circular_cache("ck_data", payload)
        result = dash.get_cached_data("ck_data")
        self.assertEqual(result, {"price": 900})

    def test_missing_cache_returns_none(self):
        result = dash.get_cached_data("no_such_key")
        self.assertIsNone(result)

    def test_cache_with_no_data_key_returns_none(self):
        payload = {"cached_at": "2026-01-01T00:00:00"}
        dash.write_circular_cache("ck_nodata", payload)
        result = dash.get_cached_data("ck_nodata")
        self.assertIsNone(result)


class TestReadFreshCachedPayload(unittest.TestCase):
    """Tests for read_fresh_cached_payload()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="sq_test_")
        self._orig_cache_dir = dash.CACHE_DIR
        dash.CACHE_DIR = self.tmpdir

    def tearDown(self):
        dash.CACHE_DIR = self._orig_cache_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fresh_cache_returns_payload(self):
        now = dt.datetime.now().isoformat(timespec="seconds")
        payload = {"data": {"val": 1}, "cached_at": now}
        dash.write_circular_cache("fresh_key", payload)
        result = dash.read_fresh_cached_payload("fresh_key", max_age_days=7)
        self.assertIsNotNone(result)
        self.assertEqual(result["data"], {"val": 1})

    def test_stale_cache_returns_none(self):
        old = (dt.datetime.now() - dt.timedelta(days=8)).isoformat(timespec="seconds")
        payload = {"data": {"val": 1}, "cached_at": old}
        dash.write_circular_cache("stale_key", payload)
        result = dash.read_fresh_cached_payload("stale_key", max_age_days=7)
        self.assertIsNone(result)

    def test_missing_cached_at_returns_none(self):
        payload = {"data": {"val": 1}}
        dash.write_circular_cache("no_ts_key", payload)
        result = dash.read_fresh_cached_payload("no_ts_key", max_age_days=7)
        self.assertIsNone(result)

    def test_missing_cache_returns_none(self):
        result = dash.read_fresh_cached_payload("absent_key", max_age_days=7)
        self.assertIsNone(result)

    def test_invalid_iso_format_returns_none(self):
        payload = {"data": {"val": 1}, "cached_at": "not-a-date"}
        dash.write_circular_cache("bad_ts_key", payload)
        result = dash.read_fresh_cached_payload("bad_ts_key", max_age_days=7)
        self.assertIsNone(result)

    def test_exactly_at_boundary_is_fresh(self):
        # A cache written exactly max_age_days ago should be stale (age > timedelta)
        # Write a cache with timestamp just barely within the window
        recent = (dt.datetime.now() - dt.timedelta(days=6, hours=23)).isoformat(timespec="seconds")
        payload = {"data": {"val": 1}, "cached_at": recent}
        dash.write_circular_cache("boundary_key", payload)
        result = dash.read_fresh_cached_payload("boundary_key", max_age_days=7)
        self.assertIsNotNone(result)


class TestSerializeDeserializeQuarterlyMargins(unittest.TestCase):
    """Tests for serialize_quarterly_margins() and deserialize_quarterly_margins()."""

    def test_roundtrip(self):
        original = {
            (2025, 1): {"gross_margin": 55.0},
            (2025, 2): {"gross_margin": 56.0},
        }
        serialized = dash.serialize_quarterly_margins(original)
        deserialized = dash.deserialize_quarterly_margins(serialized)
        self.assertEqual(deserialized, original)

    def test_serialize_format(self):
        data = {(2025, 3): {"val": 1}}
        result = dash.serialize_quarterly_margins(data)
        self.assertIn("2025Q3", result)
        self.assertEqual(result["2025Q3"], {"val": 1})

    def test_empty_dict(self):
        self.assertEqual(dash.serialize_quarterly_margins({}), {})
        self.assertEqual(dash.deserialize_quarterly_margins({}), {})

    def test_deserialize_skips_invalid_keys(self):
        payload = {
            "2025Q1": {"val": 1},
            "invalid_key": {"val": 2},
            "2025Q5": {"val": 3},  # Q5 is invalid
            "abcd": {"val": 4},
        }
        result = dash.deserialize_quarterly_margins(payload)
        self.assertEqual(len(result), 1)
        self.assertIn((2025, 1), result)

    def test_deserialize_all_four_quarters(self):
        payload = {
            "2025Q1": {"a": 1},
            "2025Q2": {"a": 2},
            "2025Q3": {"a": 3},
            "2025Q4": {"a": 4},
        }
        result = dash.deserialize_quarterly_margins(payload)
        self.assertEqual(len(result), 4)
        self.assertIn((2025, 1), result)
        self.assertIn((2025, 4), result)

    def test_roundtrip_preserves_all_fields(self):
        original = {
            (2024, 4): {
                "gross_margin": 58.2,
                "operating_margin": 48.1,
                "net_margin": 42.0,
                "gross_drop": 0.5,
                "op_drop": 1.2,
                "net_drop": 0.8,
                "eps": 9.5,
            }
        }
        serialized = dash.serialize_quarterly_margins(original)
        deserialized = dash.deserialize_quarterly_margins(serialized)
        self.assertEqual(deserialized[(2024, 4)]["gross_margin"], 58.2)
        self.assertEqual(deserialized[(2024, 4)]["eps"], 9.5)


class TestParseTwseInt(unittest.TestCase):
    """Tests for parse_twse_int()."""

    def test_normal_comma_separated(self):
        self.assertEqual(dash.parse_twse_int("1,234,567"), 1234567)

    def test_simple_number(self):
        self.assertEqual(dash.parse_twse_int("42"), 42)

    def test_none_input(self):
        self.assertIsNone(dash.parse_twse_int(None))

    def test_dash_placeholder(self):
        self.assertIsNone(dash.parse_twse_int("--"))

    def test_x_placeholder(self):
        self.assertIsNone(dash.parse_twse_int("X"))

    def test_dividend_text(self):
        self.assertIsNone(dash.parse_twse_int("除權息"))

    def test_empty_string(self):
        self.assertIsNone(dash.parse_twse_int(""))

    def test_whitespace_only(self):
        self.assertIsNone(dash.parse_twse_int("   "))

    def test_float_string_truncated(self):
        self.assertEqual(dash.parse_twse_int("3.14"), 3)

    def test_negative_number(self):
        self.assertEqual(dash.parse_twse_int("-1,234"), -1234)

    def test_invalid_text(self):
        self.assertIsNone(dash.parse_twse_int("abc"))


class TestParseTwseFloat(unittest.TestCase):
    """Tests for parse_twse_float()."""

    def test_normal_comma_separated(self):
        self.assertAlmostEqual(dash.parse_twse_float("1,234,567.89"), 1234567.89)

    def test_simple_float(self):
        self.assertAlmostEqual(dash.parse_twse_float("3.14"), 3.14)

    def test_none_input(self):
        self.assertIsNone(dash.parse_twse_float(None))

    def test_dash_placeholder(self):
        self.assertIsNone(dash.parse_twse_float("--"))

    def test_x_placeholder(self):
        self.assertIsNone(dash.parse_twse_float("X"))

    def test_dividend_text(self):
        self.assertIsNone(dash.parse_twse_float("除權息"))

    def test_empty_string(self):
        self.assertIsNone(dash.parse_twse_float(""))

    def test_integer_string(self):
        self.assertAlmostEqual(dash.parse_twse_float("42"), 42.0)

    def test_negative_float(self):
        self.assertAlmostEqual(dash.parse_twse_float("-1,234.56"), -1234.56)

    def test_invalid_text(self):
        self.assertIsNone(dash.parse_twse_float("abc"))


class TestParseTwseDate(unittest.TestCase):
    """Tests for parse_twse_date()."""

    def test_roc_date_conversion(self):
        # ROC 115 = Gregorian 2026
        result = dash.parse_twse_date("115/05/15")
        self.assertEqual(result, "2026-05-15")

    def test_roc_year_100(self):
        result = dash.parse_twse_date("100/01/01")
        self.assertEqual(result, "2011-01-01")

    def test_none_input(self):
        self.assertIsNone(dash.parse_twse_date(None))

    def test_empty_string(self):
        self.assertIsNone(dash.parse_twse_date(""))

    def test_wrong_parts_count_two(self):
        self.assertIsNone(dash.parse_twse_date("115/05"))

    def test_wrong_parts_count_four(self):
        self.assertIsNone(dash.parse_twse_date("115/05/15/01"))

    def test_invalid_month(self):
        self.assertIsNone(dash.parse_twse_date("115/13/01"))

    def test_invalid_day(self):
        self.assertIsNone(dash.parse_twse_date("115/05/32"))

    def test_non_numeric_parts(self):
        self.assertIsNone(dash.parse_twse_date("abc/def/ghi"))

    def test_whitespace_handled(self):
        result = dash.parse_twse_date("  115/05/15  ")
        self.assertEqual(result, "2026-05-15")

    def test_year_already_gregorian(self):
        # If year >= 1911, no adjustment is made (year stays as-is)
        result = dash.parse_twse_date("2026/05/15")
        self.assertEqual(result, "2026-05-15")


class TestGetRecentMonthStarts(unittest.TestCase):
    """Tests for get_recent_month_starts()."""

    def test_returns_correct_count(self):
        result = dash.get_recent_month_starts(3)
        self.assertEqual(len(result), 3)

    def test_all_are_first_of_month(self):
        result = dash.get_recent_month_starts(5)
        for d in result:
            self.assertEqual(d.day, 1)

    def test_most_recent_is_current_month(self):
        result = dash.get_recent_month_starts(3)
        today = dash.TODAY
        self.assertEqual(result[0], dt.date(today.year, today.month, 1))

    def test_chronological_order(self):
        # get_recent_month_starts returns newest first (descending)
        result = dash.get_recent_month_starts(6)
        for i in range(len(result) - 1):
            self.assertGreater(result[i], result[i + 1])

    def test_respects_twse_min_date(self):
        # Request many months; should stop at TWSE_MIN_DATE
        result = dash.get_recent_month_starts(500)
        for d in result:
            self.assertGreaterEqual(d, dash.TWSE_MIN_DATE)

    def test_single_month(self):
        result = dash.get_recent_month_starts(1)
        self.assertEqual(len(result), 1)

    def test_crosses_year_boundary(self):
        # If TODAY is January, requesting 3 months should cross into previous year
        with patch.object(dash, "TODAY", dt.date(2026, 1, 15)):
            result = dash.get_recent_month_starts(3)
            self.assertEqual(len(result), 3)
            self.assertEqual(result[0], dt.date(2026, 1, 1))
            self.assertEqual(result[1], dt.date(2025, 12, 1))
            self.assertEqual(result[2], dt.date(2025, 11, 1))


class TestBuildDataframe(unittest.TestCase):
    """Tests for build_dataframe()."""

    def test_correct_columns(self):
        revenue_yoy = [
            {"date": "2025-01", "revenue_yoy": 25.0},
            {"date": "2025-02", "revenue_yoy": 30.0},
        ]
        quarterly_margins = {
            (2025, 1): {
                "gross_margin": 55.0,
                "operating_margin": 45.0,
                "net_margin": 40.0,
                "gross_drop": 0.5,
                "op_drop": 0.3,
                "net_drop": 0.2,
                "eps": 9.0,
            }
        }
        df = dash.build_dataframe(revenue_yoy, quarterly_margins)
        expected_cols = [
            "月份", "營收 YoY (%)", "毛利率 (%)", "營業利益率 (%)",
            "稅後淨利率 (%)", "EPS (元)", "_gross_drop", "_op_drop", "_net_drop",
        ]
        self.assertEqual(list(df.columns), expected_cols)

    def test_correct_row_count(self):
        revenue_yoy = [{"date": f"2025-{m:02d}", "revenue_yoy": 20.0 + m} for m in range(1, 13)]
        quarterly_margins = {
            (2025, 1): {
                "gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 40.0,
                "gross_drop": None, "op_drop": None, "net_drop": None, "eps": 9.0,
            },
            (2025, 2): {
                "gross_margin": 56.0, "operating_margin": 46.0, "net_margin": 41.0,
                "gross_drop": 1.0, "op_drop": 1.0, "net_drop": 1.0, "eps": 10.0,
            },
            (2025, 3): {
                "gross_margin": 57.0, "operating_margin": 47.0, "net_margin": 42.0,
                "gross_drop": 1.0, "op_drop": 1.0, "net_drop": 1.0, "eps": 11.0,
            },
            (2025, 4): {
                "gross_margin": 58.0, "operating_margin": 48.0, "net_margin": 43.0,
                "gross_drop": 1.0, "op_drop": 1.0, "net_drop": 1.0, "eps": 12.0,
            },
        }
        df = dash.build_dataframe(revenue_yoy, quarterly_margins)
        self.assertEqual(len(df), 12)

    def test_yoy_values_correct(self):
        revenue_yoy = [
            {"date": "2025-06", "revenue_yoy": 22.5},
        ]
        quarterly_margins = {
            (2025, 2): {
                "gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 40.0,
                "gross_drop": 0.5, "op_drop": 0.3, "net_drop": 0.2, "eps": 9.0,
            }
        }
        df = dash.build_dataframe(revenue_yoy, quarterly_margins)
        self.assertAlmostEqual(df["營收 YoY (%)"].iloc[0], 22.5)

    def test_missing_quarter_fills_none(self):
        revenue_yoy = [
            {"date": "2025-01", "revenue_yoy": 25.0},
        ]
        quarterly_margins = {}  # No quarter data
        df = dash.build_dataframe(revenue_yoy, quarterly_margins)
        self.assertIsNone(df["毛利率 (%)"].iloc[0])
        self.assertIsNone(df["營業利益率 (%)"].iloc[0])

    def test_quarter_assignment_by_month(self):
        # Month 4 should map to Q2
        revenue_yoy = [{"date": "2025-04", "revenue_yoy": 20.0}]
        quarterly_margins = {
            (2025, 2): {
                "gross_margin": 60.0, "operating_margin": 50.0, "net_margin": 45.0,
                "gross_drop": 1.0, "op_drop": 1.0, "net_drop": 1.0, "eps": 10.0,
            }
        }
        df = dash.build_dataframe(revenue_yoy, quarterly_margins)
        self.assertAlmostEqual(df["毛利率 (%)"].iloc[0], 60.0)

    def test_months_ordered_chronologically(self):
        revenue_yoy = [
            {"date": "2025-01", "revenue_yoy": 10.0},
            {"date": "2025-02", "revenue_yoy": 20.0},
            {"date": "2025-03", "revenue_yoy": 30.0},
        ]
        quarterly_margins = {
            (2025, 1): {
                "gross_margin": 55.0, "operating_margin": 45.0, "net_margin": 40.0,
                "gross_drop": None, "op_drop": None, "net_drop": None, "eps": 9.0,
            }
        }
        df = dash.build_dataframe(revenue_yoy, quarterly_margins)
        self.assertEqual(list(df["月份"]), ["2025-01", "2025-02", "2025-03"])


class TestApplyColorLogic(unittest.TestCase):
    """Tests for apply_color_logic()."""

    def _make_df(self, revenue_yoys, gross_drops, op_drops, net_drops):
        """Helper to build a minimal DataFrame for color testing."""
        rows = []
        for i, rev in enumerate(revenue_yoys):
            rows.append({
                "月份": f"2025-{i+1:02d}",
                "營收 YoY (%)": rev,
                "毛利率 (%)": 55.0,
                "營業利益率 (%)": 45.0,
                "稅後淨利率 (%)": 40.0,
                "EPS (元)": 9.0,
                "_gross_drop": gross_drops[i],
                "_op_drop": op_drops[i],
                "_net_drop": net_drops[i],
            })
        return pd.DataFrame(rows)

    def test_revenue_yoy_above_20_no_color(self):
        df = self._make_df([25.0], [0.5], [0.5], [0.5])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["營收 YoY 色彩"].iloc[0], "")

    def test_revenue_yoy_below_20_yellow(self):
        df = self._make_df([15.0], [0.5], [0.5], [0.5])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["營收 YoY 色彩"].iloc[0], "yellow")

    def test_revenue_yoy_two_consecutive_below_20_red(self):
        df = self._make_df([15.0, 10.0], [0.5, 0.5], [0.5, 0.5], [0.5, 0.5])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["營收 YoY 色彩"].iloc[0], "yellow")
        self.assertEqual(styled["營收 YoY 色彩"].iloc[1], "red")

    def test_revenue_yoy_none_no_color(self):
        df = self._make_df([None], [0.5], [0.5], [0.5])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["營收 YoY 色彩"].iloc[0], "")

    def test_margin_single_drop_over_2_yellow(self):
        # Only gross_drop > 2, others <= 2 => yellow
        df = self._make_df([25.0], [3.0], [1.0], [1.0])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["毛利率 色彩"].iloc[0], "yellow")

    def test_margin_two_drops_over_2_red(self):
        # gross_drop > 2 and op_drop > 2 => red
        df = self._make_df([25.0], [3.0], [3.0], [1.0])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["毛利率 色彩"].iloc[0], "red")

    def test_margin_all_drops_over_2_red(self):
        # All three > 2 => red
        df = self._make_df([25.0], [3.0], [3.0], [3.0])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["毛利率 色彩"].iloc[0], "red")

    def test_margin_no_drops_no_color(self):
        df = self._make_df([25.0], [1.0], [1.0], [1.0])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["毛利率 色彩"].iloc[0], "")

    def test_margin_none_drops_no_color(self):
        df = self._make_df([25.0], [None], [None], [None])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["毛利率 色彩"].iloc[0], "")

    def test_margin_drop_exactly_2_no_color(self):
        # Drop of exactly 2 is not > 2
        df = self._make_df([25.0], [2.0], [2.0], [2.0])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["毛利率 色彩"].iloc[0], "")

    def test_margin_drop_just_over_2_yellow(self):
        df = self._make_df([25.0], [2.1], [0.5], [0.5])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["毛利率 色彩"].iloc[0], "yellow")

    def test_color_columns_exist(self):
        df = self._make_df([25.0], [0.5], [0.5], [0.5])
        styled = dash.apply_color_logic(df)
        self.assertIn("營收 YoY 色彩", styled.columns)
        self.assertIn("毛利率 色彩", styled.columns)
        self.assertIn("營業利益率 色彩", styled.columns)
        self.assertIn("稅後淨利率 色彩", styled.columns)

    def test_internal_drop_columns_removed(self):
        df = self._make_df([25.0], [0.5], [0.5], [0.5])
        styled = dash.apply_color_logic(df)
        self.assertNotIn("_gross_drop", styled.columns)
        self.assertNotIn("_op_drop", styled.columns)
        self.assertNotIn("_net_drop", styled.columns)

    def test_margin_colors_applied_to_all_three_columns(self):
        """All three margin columns should share the same color."""
        df = self._make_df([25.0], [3.0], [3.0], [1.0])
        styled = dash.apply_color_logic(df)
        color = styled["毛利率 色彩"].iloc[0]
        self.assertEqual(styled["營業利益率 色彩"].iloc[0], color)
        self.assertEqual(styled["稅後淨利率 色彩"].iloc[0], color)

    def test_revenue_yoy_recovers_after_one_yellow(self):
        # First month < 20 (yellow), second >= 20 (no color), third < 20 (yellow again)
        df = self._make_df([15.0, 25.0, 10.0], [0.5, 0.5, 0.5], [0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
        styled = dash.apply_color_logic(df)
        self.assertEqual(styled["營收 YoY 色彩"].iloc[0], "yellow")
        self.assertEqual(styled["營收 YoY 色彩"].iloc[1], "")
        self.assertEqual(styled["營收 YoY 色彩"].iloc[2], "yellow")


if __name__ == "__main__":
    unittest.main()
