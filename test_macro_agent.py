"""
Sentimental-Quant-Lab — Tests for tsmc_macro_agent.py

Covers the GlobalMacroAgent class:
- __init__ / summarize
- _http_get_json (success and failure)
- _fetch_json_with_cache (delegates to fetch_with_cache)
- analyze_global_risk (skip, normal premium/discount, exception)
- analyze_bigtech_fundamentals (no-data, report structure)
- _fetch_tsm_eps_estimate (None, trailing, Q1-2026, ratio-based)
- _fetch_yahoo_price (mock fetch_with_cache)
- _format_usd_billions
- CAPEX normalization helpers (_normalize_capex_entry, _is_single_quarter_entry, etc.)
- _calendar_period_from_end
- _target_ytd_days
- _has_consecutive_quarter_ends
- _derive_quarterly_capex
- _extract_recent_capex_quarters (via _derive + consecutive)
"""

import os
import pytest
from unittest.mock import patch, MagicMock, call
from datetime import date

from tsmc_macro_agent import (
    GlobalMacroAgent,
    SEC_HEADERS,
    CAPEX_COMPANIES,
    CAPEX_TAGS,
    NVDA_CIK,
    NVDA_TICKER,
)


# ══════════════════════════════════════════════════════════════
# Agent initialization and summarize
# ══════════════════════════════════════════════════════════════

class TestGlobalMacroAgentInit:
    @patch("tsmc_macro_agent.requests.Session")
    def test_init_sets_name_source_logic(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        agent = GlobalMacroAgent()
        assert agent.name == "全球宏觀 Agent"
        assert agent.source == "Yahoo Finance (TSM ADR & TWD=X)"
        assert "ADR" in agent.logic

    @patch("tsmc_macro_agent.requests.Session")
    def test_init_creates_session_with_retry(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        agent = GlobalMacroAgent()
        mock_session_cls.assert_called_once()
        assert mock_session.mount.call_count == 2
        mock_session.headers.update.assert_called_once()


class TestSummarize:
    @patch("tsmc_macro_agent.requests.Session")
    def test_summarize_returns_formatted_string(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        result = agent.summarize("ADR 溢價 2.5%")
        assert "[全球宏觀 Agent]" in result
        assert "ADR 溢價 2.5%" in result


# ══════════════════════════════════════════════════════════════
# _http_get_json
# ══════════════════════════════════════════════════════════════

class TestHttpGetJson:
    @patch("tsmc_macro_agent.requests.Session")
    def test_http_get_json_success(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"price": 900.0}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        agent = GlobalMacroAgent()
        result = agent._http_get_json("https://example.com/api")
        assert result == {"price": 900.0}
        mock_session.get.assert_called_once_with(
            "https://example.com/api", headers=None, params=None, timeout=20
        )

    @patch("tsmc_macro_agent.requests.Session")
    def test_http_get_json_with_params_and_headers(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [1, 2]}
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        agent = GlobalMacroAgent()
        agent._http_get_json(
            "https://example.com",
            headers={"User-Agent": "test"},
            params={"key": "val"},
            timeout=10,
        )
        mock_session.get.assert_called_once_with(
            "https://example.com",
            headers={"User-Agent": "test"},
            params={"key": "val"},
            timeout=10,
        )

    @patch("tsmc_macro_agent.requests.Session")
    def test_http_get_json_request_exception_raises_runtime(self, mock_session_cls):
        import requests as req
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.get.side_effect = req.RequestException("timeout")

        agent = GlobalMacroAgent()
        with pytest.raises(RuntimeError, match="HTTP request failed"):
            agent._http_get_json("https://example.com")

    @patch("tsmc_macro_agent.requests.Session")
    def test_http_get_json_invalid_json_raises_runtime(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_session.get.return_value = mock_resp

        agent = GlobalMacroAgent()
        with pytest.raises(RuntimeError, match="無效 JSON 回傳"):
            agent._http_get_json("https://example.com")


# ══════════════════════════════════════════════════════════════
# _fetch_json_with_cache
# ══════════════════════════════════════════════════════════════

class TestFetchJsonWithCache:
    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_fetch_json_with_cache_calls_fetch_with_cache(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.return_value = {"cached": True}

        agent = GlobalMacroAgent()
        result = agent._fetch_json_with_cache(
            "test_key", "https://example.com", policy_name="test_policy",
            headers={"H": "V"}, params={"P": "V"}, timeout=15,
        )

        assert result == {"cached": True}
        mock_fetch_cache.assert_called_once()
        call_kwargs = mock_fetch_cache.call_args
        assert call_kwargs.kwargs["policy_name"] == "test_policy"
        assert call_kwargs.kwargs["cache_key"] == "test_key"
        assert callable(call_kwargs.kwargs["fetch_fn"])

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_fetch_json_with_cache_default_policy(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        agent._fetch_json_with_cache("key", "https://example.com")
        call_kwargs = mock_fetch_cache.call_args
        assert call_kwargs.kwargs["policy_name"] == "macro_capex"


# ══════════════════════════════════════════════════════════════
# analyze_global_risk
# ══════════════════════════════════════════════════════════════

class TestAnalyzeGlobalRisk:
    @patch("tsmc_macro_agent.requests.Session")
    def test_skip_when_tw_price_zero(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        report, score = agent.analyze_global_risk(0)
        assert score == 100
        assert "跳過" in report

    @patch("tsmc_macro_agent.requests.Session")
    def test_skip_when_tw_price_negative(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        report, score = agent.analyze_global_risk(-10)
        assert score == 100
        assert "跳過" in report

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_premium_scenario(self, mock_fetch_cache, mock_session_cls):
        """TSM=180, USD/TWD=32 -> ADR equiv = (180*32)/5 = 1152; tw_price=1100
        premium = (1152-1100)/1100*100 = 4.73% -> premium, score=100"""
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        def fake_fetch(policy_name, cache_key, fetch_fn):
            if "TSM" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 180.0}}]}}
            elif "TWD" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 32.0}}]}}
            return {}

        mock_fetch_cache.side_effect = fake_fetch
        report, score = agent.analyze_global_risk(1100.0)
        assert score == 100
        assert "溢價" in report
        assert "ADR折算價" in report
        assert "匯率參考" in report

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_small_discount_score_80(self, mock_fetch_cache, mock_session_cls):
        """premium = -0.5% -> score 80 (premium < 0 but >= -1)"""
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        # ADR equiv = (174 * 31.48) / 5 = 1095.5, tw=1100 -> p=-0.41% -> score 80
        def fake_fetch(policy_name, cache_key, fetch_fn):
            if "TSM" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 174.0}}]}}
            elif "TWD" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 31.48}}]}}
            return {}

        mock_fetch_cache.side_effect = fake_fetch
        report, score = agent.analyze_global_risk(1100.0)
        assert score == 80
        assert "折價" in report

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_large_discount_score_60(self, mock_fetch_cache, mock_session_cls):
        """premium < -1% -> score 60"""
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        # TSM=170, TWD=31 => (170*31)/5 = 1054 => p=-4.18%
        def fake_fetch(policy_name, cache_key, fetch_fn):
            if "TSM" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 170.0}}]}}
            elif "TWD" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 31.0}}]}}
            return {}

        mock_fetch_cache.side_effect = fake_fetch
        report, score = agent.analyze_global_risk(1100.0)
        assert score == 60
        assert "折價" in report

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_exception_returns_error_and_score_100(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.side_effect = RuntimeError("API down")

        agent = GlobalMacroAgent()
        report, score = agent.analyze_global_risk(900.0)
        assert score == 100
        assert "失敗" in report


# ══════════════════════════════════════════════════════════════
# analyze_bigtech_fundamentals
# ══════════════════════════════════════════════════════════════

class TestAnalyzeBigTechFundamentals:
    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_no_sec_data_returns_score_100(self, mock_fetch_cache, mock_session_cls):
        """All SEC fetches fail -> valid_count=0, capex_score=100"""
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.side_effect = RuntimeError("SEC unavailable")

        agent = GlobalMacroAgent()
        data, report = agent.analyze_bigtech_fundamentals()

        assert data["capex_valid_count"] == 0
        assert data["capex_score"] == 100
        assert "大廠基本面分析" in report
        assert "CAPEX 結論" in report

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_report_contains_capex_companies(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.side_effect = RuntimeError("SEC unavailable")

        agent = GlobalMacroAgent()
        data, report = agent.analyze_bigtech_fundamentals()
        for company in CAPEX_COMPANIES:
            assert company in report
        assert "SEC" in report

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_data_structure(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.side_effect = RuntimeError("SEC unavailable")

        agent = GlobalMacroAgent()
        data, report = agent.analyze_bigtech_fundamentals()
        assert "capex_growing_count" in data
        assert "capex_valid_count" in data
        assert "capex_score" in data
        assert "nvda_revenue_yoy" in data
        assert "nvda_score" in data
        assert "score" in data


# ══════════════════════════════════════════════════════════════
# _fetch_tsm_eps_estimate
# ══════════════════════════════════════════════════════════════

class TestFetchTsmEpsEstimate:
    @patch("tsmc_macro_agent.requests.Session")
    def test_none_input_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._fetch_tsm_eps_estimate(None) is None

    @patch("tsmc_macro_agent.requests.Session")
    def test_empty_dict_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        result = agent._fetch_tsm_eps_estimate({})
        assert result is None

    @patch("tsmc_macro_agent.requests.Session")
    def test_with_trailing_4q(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarterly = {
            (2025, 4): {"eps": 10.0},
            (2025, 3): {"eps": 9.0},
            (2025, 2): {"eps": 8.0},
            (2025, 1): {"eps": 7.0},
        }
        result = agent._fetch_tsm_eps_estimate(quarterly)
        assert result is not None
        assert result["eps_trailing_4q"] == 34.0  # 10+9+8+7
        assert "2025Q4" in result["eps_detail"]

    @patch("tsmc_macro_agent.requests.Session")
    def test_with_q1_2026_data(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarterly = {
            (2026, 1): {"eps": 11.0},
            (2025, 4): {"eps": 10.0},
            (2025, 3): {"eps": 9.0},
            (2025, 2): {"eps": 8.0},
        }
        result = agent._fetch_tsm_eps_estimate(quarterly)
        assert result is not None
        assert result["eps_q1_2026"] == 11.0
        assert result["eps_2026_annualized"] == 44.0  # 11*4

    @patch("tsmc_macro_agent.requests.Session")
    def test_ratio_based_estimate_with_q1_2025_and_2026(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        # 2025 total = 8+9+10+11 = 38; q1_2025=8; ratio = 8/38
        # 2026 q1 = 12; estimate = 12 / (8/38) = 57.0
        quarterly = {
            (2026, 1): {"eps": 12.0},
            (2025, 4): {"eps": 11.0},
            (2025, 3): {"eps": 10.0},
            (2025, 2): {"eps": 9.0},
            (2025, 1): {"eps": 8.0},
        }
        result = agent._fetch_tsm_eps_estimate(quarterly)
        assert result is not None
        assert "eps_2026_estimate" in result
        assert result["eps_2026_estimate"] == 57.0  # 12 / (8/38) = 57.0

    @patch("tsmc_macro_agent.requests.Session")
    def test_eps_detail_in_result(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarterly = {
            (2025, 4): {"eps": 10.5},
        }
        result = agent._fetch_tsm_eps_estimate(quarterly)
        assert result is not None
        assert "eps_detail" in result
        assert "2025Q4" in result["eps_detail"]
        assert "10.50" in result["eps_detail"]


# ══════════════════════════════════════════════════════════════
# _fetch_yahoo_price (tested via mock of fetch_with_cache)
# ══════════════════════════════════════════════════════════════

class TestFetchYahooPrice:
    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_fetch_yahoo_price_calls_correct_ticker(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.return_value = {
            "chart": {"result": [{"meta": {"regularMarketPrice": 180.0}}]}
        }

        agent = GlobalMacroAgent()
        price = agent._fetch_yahoo_price("TSM")
        assert price == 180.0

        call_kwargs = mock_fetch_cache.call_args.kwargs
        assert call_kwargs["cache_key"] == "yahoo_price_TSM"
        assert call_kwargs["policy_name"] == "macro_adr"

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_fetch_yahoo_price_raises_on_missing_result(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.return_value = {"chart": {"result": []}}

        agent = GlobalMacroAgent()
        with pytest.raises(RuntimeError, match="格式異常"):
            agent._fetch_yahoo_price("TSM")

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_fetch_yahoo_price_raises_on_missing_price(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.return_value = {
            "chart": {"result": [{"meta": {"regularMarketPrice": None}}]}
        }

        agent = GlobalMacroAgent()
        with pytest.raises(RuntimeError, match="regularMarketPrice"):
            agent._fetch_yahoo_price("TSM")


# ══════════════════════════════════════════════════════════════
# _format_usd_billions
# ══════════════════════════════════════════════════════════════

class TestFormatUsdBillions:
    @patch("tsmc_macro_agent.requests.Session")
    def test_format_one_and_half_billion(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._format_usd_billions(1_500_000_000) == "$1.50B"

    @patch("tsmc_macro_agent.requests.Session")
    def test_format_zero(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._format_usd_billions(0) == "$0.00B"

    @patch("tsmc_macro_agent.requests.Session")
    def test_format_large_number(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._format_usd_billions(123_456_789_000) == "$123.46B"

    @patch("tsmc_macro_agent.requests.Session")
    def test_format_negative(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        result = agent._format_usd_billions(-500_000_000)
        assert result == "$-0.50B"


# ══════════════════════════════════════════════════════════════
# _normalize_capex_entry
# ══════════════════════════════════════════════════════════════

class TestNormalizeCapexEntry:
    @patch("tsmc_macro_agent.requests.Session")
    def test_complete_entry(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {
            "val": -5000000000,
            "start": "2025-01-01",
            "end": "2025-03-31",
            "filed": "2025-04-25",
            "form": "10-Q",
            "fp": "Q1",
            "fy": "2025",
            "accn": "0001234567-25-000001",
            "frame": "CY2025Q1",
            "qtrs": 1,
        }
        result = agent._normalize_capex_entry(entry, "0000789019")
        assert result is not None
        assert result["value"] == 5_000_000_000.0  # abs()
        assert result["fp"] == "Q1"
        assert result["fy"] == 2025
        assert result["period"] == "2025Q1"
        assert result["form"] == "10-Q"
        assert "sec_filing_url" in result
        assert "sec.gov/Archives" in result["sec_filing_url"]

    @patch("tsmc_macro_agent.requests.Session")
    def test_missing_value_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {
            "val": None,
            "start": "2025-01-01",
            "end": "2025-03-31",
            "filed": "2025-04-25",
            "fp": "Q1",
            "fy": "2025",
        }
        assert agent._normalize_capex_entry(entry, "0000789019") is None

    @patch("tsmc_macro_agent.requests.Session")
    def test_missing_start_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {
            "val": 1000,
            "start": "",
            "end": "2025-03-31",
            "filed": "2025-04-25",
            "fp": "Q1",
            "fy": "2025",
        }
        assert agent._normalize_capex_entry(entry, "0000789019") is None

    @patch("tsmc_macro_agent.requests.Session")
    def test_missing_fp_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {
            "val": 1000,
            "start": "2025-01-01",
            "end": "2025-03-31",
            "filed": "2025-04-25",
            "fp": "",
            "fy": "2025",
        }
        assert agent._normalize_capex_entry(entry, "0000789019") is None

    @patch("tsmc_macro_agent.requests.Session")
    def test_missing_fy_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {
            "val": 1000,
            "start": "2025-01-01",
            "end": "2025-03-31",
            "filed": "2025-04-25",
            "fp": "Q1",
            "fy": "",
        }
        assert agent._normalize_capex_entry(entry, "0000789019") is None

    @patch("tsmc_macro_agent.requests.Session")
    def test_cik_leading_zeros_stripped(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {
            "val": 1000,
            "start": "2025-01-01",
            "end": "2025-03-31",
            "filed": "2025-04-25",
            "form": "10-Q",
            "fp": "Q1",
            "fy": "2025",
            "accn": "000123-45-6",
        }
        result = agent._normalize_capex_entry(entry, "0000789019")
        assert "789019" in result["sec_filing_url"]
        assert "0000789019" not in result["sec_filing_url"].split("edgar/data/")[1].split("/")[0]

    @patch("tsmc_macro_agent.requests.Session")
    def test_no_accn_url_is_empty(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {
            "val": 1000,
            "start": "2025-01-01",
            "end": "2025-03-31",
            "filed": "2025-04-25",
            "form": "10-Q",
            "fp": "Q1",
            "fy": "2025",
        }
        result = agent._normalize_capex_entry(entry, "0000789019")
        assert result["sec_filing_url"] == ""


# ══════════════════════════════════════════════════════════════
# _is_single_quarter_entry
# ══════════════════════════════════════════════════════════════

class TestIsSingleQuarterEntry:
    @patch("tsmc_macro_agent.requests.Session")
    def test_qtrs_1_is_single(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-06-30", "qtrs": 1, "fp": "Q1"}
        assert agent._is_single_quarter_entry(entry) is True

    @patch("tsmc_macro_agent.requests.Session")
    def test_90_days_no_qtrs_is_single(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-03-31", "qtrs": None, "fp": "Q1"}
        assert agent._is_single_quarter_entry(entry) is True

    @patch("tsmc_macro_agent.requests.Session")
    def test_60_days_is_single(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        # Jan 1 to Mar 2 = 31 + 28 + 1 = 60 days (2025 is not a leap year)
        entry = {"start": "2025-01-01", "end": "2025-03-02", "qtrs": None, "fp": "Q1"}
        assert agent._is_single_quarter_entry(entry) is True

    @patch("tsmc_macro_agent.requests.Session")
    def test_115_days_is_single(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-04-26", "qtrs": None, "fp": "Q1"}
        assert agent._is_single_quarter_entry(entry) is True

    @patch("tsmc_macro_agent.requests.Session")
    def test_200_days_is_not_single(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-07-20", "qtrs": None, "fp": "Q1"}
        assert agent._is_single_quarter_entry(entry) is False

    @patch("tsmc_macro_agent.requests.Session")
    def test_30_days_is_not_single(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-01-31", "qtrs": None, "fp": "Q1"}
        assert agent._is_single_quarter_entry(entry) is False


# ══════════════════════════════════════════════════════════════
# _is_valid_ytd_entry
# ══════════════════════════════════════════════════════════════

class TestIsValidYtdEntry:
    @patch("tsmc_macro_agent.requests.Session")
    def test_exact_q1_days_valid(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        # Q1: target=90 days; Jan 1 to Apr 1 = 90 days
        entry = {"start": "2025-01-01", "end": "2025-04-01", "fp": "Q1"}
        assert agent._is_valid_ytd_entry(entry) is True

    @patch("tsmc_macro_agent.requests.Session")
    def test_far_off_q1_invalid(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-06-30", "fp": "Q1"}
        # ~180 days, target=90 -> diff=90 > 25
        assert agent._is_valid_ytd_entry(entry) is False

    @patch("tsmc_macro_agent.requests.Session")
    def test_fy_365_days_valid(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-12-31", "fp": "FY"}
        # 364 days, target=365 -> diff=1 <= 25
        assert agent._is_valid_ytd_entry(entry) is True


# ══════════════════════════════════════════════════════════════
# _entry_days
# ══════════════════════════════════════════════════════════════

class TestEntryDays:
    @patch("tsmc_macro_agent.requests.Session")
    def test_entry_days_calculation(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        # Jan 1 to Apr 1 = 31 + 28 + 31 = 90 days (2025 non-leap year)
        entry = {"start": "2025-01-01", "end": "2025-04-01"}
        assert agent._entry_days(entry) == 90

    @patch("tsmc_macro_agent.requests.Session")
    def test_entry_days_same_day(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entry = {"start": "2025-01-01", "end": "2025-01-01"}
        assert agent._entry_days(entry) == 0


# ══════════════════════════════════════════════════════════════
# _calendar_period_from_end
# ══════════════════════════════════════════════════════════════

class TestCalendarPeriodFromEnd:
    @patch("tsmc_macro_agent.requests.Session")
    def test_march_31_is_q1(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._calendar_period_from_end("2025-03-31") == "2025Q1"

    @patch("tsmc_macro_agent.requests.Session")
    def test_june_30_is_q2(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._calendar_period_from_end("2025-06-30") == "2025Q2"

    @patch("tsmc_macro_agent.requests.Session")
    def test_september_30_is_q3(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._calendar_period_from_end("2025-09-30") == "2025Q3"

    @patch("tsmc_macro_agent.requests.Session")
    def test_december_31_is_q4(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._calendar_period_from_end("2025-12-31") == "2025Q4"

    @patch("tsmc_macro_agent.requests.Session")
    def test_february_in_q1(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._calendar_period_from_end("2025-02-28") == "2025Q1"

    @patch("tsmc_macro_agent.requests.Session")
    def test_november_in_q4(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._calendar_period_from_end("2025-11-15") == "2025Q4"


# ══════════════════════════════════════════════════════════════
# _target_ytd_days
# ══════════════════════════════════════════════════════════════

class TestTargetYtdDays:
    @patch("tsmc_macro_agent.requests.Session")
    def test_q1_target(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._target_ytd_days("Q1") == 90

    @patch("tsmc_macro_agent.requests.Session")
    def test_q2_target(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._target_ytd_days("Q2") == 181

    @patch("tsmc_macro_agent.requests.Session")
    def test_q3_target(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._target_ytd_days("Q3") == 273

    @patch("tsmc_macro_agent.requests.Session")
    def test_fy_target(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._target_ytd_days("FY") == 365

    @patch("tsmc_macro_agent.requests.Session")
    def test_unknown_returns_90(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._target_ytd_days("unknown") == 90

    @patch("tsmc_macro_agent.requests.Session")
    def test_q4_is_not_in_map_returning_90(self, mock_session_cls):
        """The _target_ytd_days map only has Q1/Q2/Q3/FY; Q4 returns default 90."""
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        assert agent._target_ytd_days("Q4") == 90


# ══════════════════════════════════════════════════════════════
# _has_consecutive_quarter_ends
# ══════════════════════════════════════════════════════════════

class TestHasConsecutiveQuarterEnds:
    @patch("tsmc_macro_agent.requests.Session")
    def test_three_quarters_with_valid_gaps(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarters = [
            {"end": "2025-01-31"},
            {"end": "2025-04-30"},
            {"end": "2025-07-31"},
        ]
        assert agent._has_consecutive_quarter_ends(quarters) is True

    @patch("tsmc_macro_agent.requests.Session")
    def test_less_than_three_fails(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarters = [
            {"end": "2025-01-31"},
            {"end": "2025-04-30"},
        ]
        assert agent._has_consecutive_quarter_ends(quarters) is False

    @patch("tsmc_macro_agent.requests.Session")
    def test_gap_too_large_fails(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarters = [
            {"end": "2025-01-31"},
            {"end": "2025-04-30"},
            {"end": "2026-12-31"},
        ]
        assert agent._has_consecutive_quarter_ends(quarters) is False

    @patch("tsmc_macro_agent.requests.Session")
    def test_gap_too_small_fails(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarters = [
            {"end": "2025-01-31"},
            {"end": "2025-02-15"},
            {"end": "2025-04-30"},
        ]
        assert agent._has_consecutive_quarter_ends(quarters) is False

    @patch("tsmc_macro_agent.requests.Session")
    def test_exact_boundary_gaps(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarters = [
            {"end": "2025-01-01"},
            {"end": "2025-03-17"},  # 75 days
            {"end": "2025-06-15"},  # 115 days from March 17
        ]
        assert agent._has_consecutive_quarter_ends(quarters) is True

    @patch("tsmc_macro_agent.requests.Session")
    def test_four_quarters_valid(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        quarters = [
            {"end": "2024-10-31"},
            {"end": "2025-01-31"},
            {"end": "2025-04-30"},
            {"end": "2025-07-31"},
        ]
        assert agent._has_consecutive_quarter_ends(quarters) is True


# ══════════════════════════════════════════════════════════════
# _derive_quarterly_capex
# ══════════════════════════════════════════════════════════════

class TestDeriveQuarterlyCapex:
    """_derive_quarterly_capex expects entries already normalized (field 'value' not 'val')."""
    @patch("tsmc_macro_agent.requests.Session")
    def test_direct_single_quarter_entries(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            {
                "start": "2025-01-01", "end": "2025-03-31",
                "filed": "2025-04-25", "form": "10-Q",
                "fp": "Q1", "fy": 2025, "qtrs": 1,
                "value": 5_000_000_000, "accn": "accn1",
            },
            {
                "start": "2025-04-01", "end": "2025-06-30",
                "filed": "2025-07-25", "form": "10-Q",
                "fp": "Q2", "fy": 2025, "qtrs": 1,
                "value": 6_000_000_000, "accn": "accn2",
            },
            {
                "start": "2025-07-01", "end": "2025-09-30",
                "filed": "2025-10-25", "form": "10-Q",
                "fp": "Q3", "fy": 2025, "qtrs": 1,
                "value": 7_000_000_000, "accn": "accn3",
            },
        ]
        result = agent._derive_quarterly_capex(entries)
        assert len(result) == 3
        for r in result:
            assert r["method"] == "direct"

    @patch("tsmc_macro_agent.requests.Session")
    def test_negative_quarterly_value_skipped(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            {
                "start": "2025-01-01", "end": "2025-03-31",
                "filed": "2025-04-25", "form": "10-Q",
                "fp": "Q1", "fy": 2025, "qtrs": 1,
                "value": 5_000_000_000, "accn": "accn1",
            },
            {
                "start": "2025-01-01", "end": "2025-06-30",
                "filed": "2025-07-25", "form": "10-Q",
                "fp": "Q2", "fy": 2025, "value": 4_000_000_000,
                "accn": "accn2",
            },
        ]
        result = agent._derive_quarterly_capex(entries)
        assert len(result) == 1
        assert result[0]["value"] == 5_000_000_000

    @patch("tsmc_macro_agent.requests.Session")
    def test_ytd_derivation(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            {
                "start": "2025-01-01", "end": "2025-03-31",
                "filed": "2025-04-25", "form": "10-Q",
                "fp": "Q1", "fy": 2025, "value": 5_000_000_000,
                "accn": "accn1",
            },
            {
                "start": "2025-01-01", "end": "2025-06-30",
                "filed": "2025-07-25", "form": "10-Q",
                "fp": "Q2", "fy": 2025, "value": 12_000_000_000,
                "accn": "accn2",
            },
        ]
        result = agent._derive_quarterly_capex(entries)
        assert len(result) == 2
        q2_entry = [r for r in result if r["fp"] == "Q2"][0]
        assert q2_entry["value"] == 7_000_000_000  # 12B - 5B
        assert q2_entry["method"] == "derived from YTD"

    @patch("tsmc_macro_agent.requests.Session")
    def test_direct_preferred_over_derived(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            {
                "start": "2025-07-01", "end": "2025-09-30",
                "filed": "2025-10-25", "form": "10-Q",
                "fp": "Q3", "fy": 2025, "qtrs": 1,
                "value": 7_000_000_000, "accn": "accn1",
            },
            {
                "start": "2025-01-01", "end": "2025-09-30",
                "filed": "2025-10-25", "form": "10-K",
                "fp": "Q3", "fy": 2025, "value": 18_000_000_000,
                "accn": "accn2",
            },
        ]
        result = agent._derive_quarterly_capex(entries)
        q3_entries = [r for r in result if r["end"] == "2025-09-30"]
        assert len(q3_entries) == 1
        assert q3_entries[0]["value"] == 7_000_000_000
        assert q3_entries[0]["method"] == "direct"


# ══════════════════════════════════════════════════════════════
# _extract_recent_capex_quarters (integration via derive + consecutive)
# ══════════════════════════════════════════════════════════════

class TestExtractRecentCapexQuarters:
    """_extract_recent_capex_quarters expects normalized entries (field 'value', not 'val')."""
    @patch("tsmc_macro_agent.requests.Session")
    def test_three_consecutive_quarters_pass(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            {"start": "2024-10-01", "end": "2024-12-31",
             "filed": "2025-01-25", "form": "10-Q",
             "fp": "Q4", "fy": 2024, "qtrs": 1,
             "value": 5_000_000_000, "accn": "a1"},
            {"start": "2025-01-01", "end": "2025-03-31",
             "filed": "2025-04-25", "form": "10-Q",
             "fp": "Q1", "fy": 2025, "qtrs": 1,
             "value": 6_000_000_000, "accn": "a2"},
            {"start": "2025-04-01", "end": "2025-06-30",
             "filed": "2025-07-25", "form": "10-Q",
             "fp": "Q2", "fy": 2025, "qtrs": 1,
             "value": 7_000_000_000, "accn": "a3"},
            {"start": "2025-07-01", "end": "2025-09-30",
             "filed": "2025-10-25", "form": "10-Q",
             "fp": "Q3", "fy": 2025, "qtrs": 1,
             "value": 8_000_000_000, "accn": "a4"},
        ]
        result = agent._extract_recent_capex_quarters(entries)
        assert len(result) == 3
        periods = {r["period"] for r in result}
        assert "2025Q1" in periods
        assert "2025Q2" in periods
        assert "2025Q3" in periods

    @patch("tsmc_macro_agent.requests.Session")
    def test_non_consecutive_returns_empty(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            {"start": "2025-01-01", "end": "2025-03-31",
             "filed": "2025-04-25", "form": "10-Q",
             "fp": "Q1", "fy": 2025, "qtrs": 1,
             "value": 5_000_000_000, "accn": "a1"},
            {"start": "2025-04-01", "end": "2025-06-30",
             "filed": "2025-07-25", "form": "10-Q",
             "fp": "Q2", "fy": 2025, "qtrs": 1,
             "value": 6_000_000_000, "accn": "a2"},
            {"start": "2025-10-01", "end": "2025-12-31",
             "filed": "2026-01-25", "form": "10-Q",
             "fp": "Q4", "fy": 2025, "qtrs": 1,
             "value": 8_000_000_000, "accn": "a3"},
        ]
        result = agent._extract_recent_capex_quarters(entries)
        assert len(result) == 0

    @patch("tsmc_macro_agent.requests.Session")
    def test_10k_excluded_if_no_10q(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            {"start": "2025-01-01", "end": "2025-12-31",
             "filed": "2026-03-01", "form": "10-K",
             "fp": "FY", "fy": 2025, "qtrs": None,
             "value": 20_000_000_000, "accn": "a1",
             "qtrs": 4},
        ]
        result = agent._extract_recent_capex_quarters(entries)
        assert len(result) == 0

    @patch("tsmc_macro_agent.requests.Session")
    def test_entries_with_none_filtered_out(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        entries = [
            None,
            {"start": "2025-07-01", "end": "2025-09-30",
             "filed": "2025-10-25", "form": "10-Q",
             "fp": "Q3", "fy": 2025, "qtrs": 1,
             "value": 8_000_000_000, "accn": "a1"},
            {"start": "2025-04-01", "end": "2025-06-30",
             "filed": "2025-07-25", "form": "10-Q",
             "fp": "Q2", "fy": 2025, "qtrs": 1,
             "value": 7_000_000_000, "accn": "a2"},
            {"start": "2025-01-01", "end": "2025-03-31",
             "filed": "2025-04-25", "form": "10-Q",
             "fp": "Q1", "fy": 2025, "qtrs": 1,
             "value": 6_000_000_000, "accn": "a3"},
        ]
        result = agent._extract_recent_capex_quarters(entries)
        assert len(result) == 3


# ══════════════════════════════════════════════════════════════
# Module-level constants
# ══════════════════════════════════════════════════════════════

class TestModuleConstants:
    def test_sec_headers_has_user_agent(self):
        assert "User-Agent" in SEC_HEADERS

    def test_capex_companies_has_four(self):
        assert len(CAPEX_COMPANIES) == 4
        for name in ["Microsoft", "Meta", "Google", "Amazon"]:
            assert name in CAPEX_COMPANIES

    def test_capex_tags_not_empty(self):
        assert len(CAPEX_TAGS) > 0
        assert "PaymentsToAcquirePropertyPlantAndEquipment" in CAPEX_TAGS

    def test_nvda_cik_correct(self):
        assert NVDA_CIK == "0001045810"

    def test_nvda_ticker_correct(self):
        assert NVDA_TICKER == "NVDA"


# ══════════════════════════════════════════════════════════════
# US Inflation Data (FRED API) — fetch_inflation_report
# ══════════════════════════════════════════════════════════════

class TestFetchInflationReport:
    @patch("tsmc_macro_agent.requests.Session")
    def test_no_api_key_returns_empty(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRED_API_KEY", None)
            result = agent.fetch_inflation_report()
            assert result == ""

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_with_api_key_cpi_only(self, mock_fetch_cache, mock_session_cls):
        """Only CPIAUCSL returns valid data; other series return empty observations."""
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        def fake_fetch(policy_name, cache_key, fetch_fn):
            if "fred_CPIAUCSL" in cache_key:
                return {
                    "observations": [
                        {"date": f"2024-{m:02d}-01", "value": str(300.0 + i * 0.8)}
                        for i, m in enumerate(range(1, 14))
                    ]
                }
            return {"observations": []}

        mock_fetch_cache.side_effect = fake_fetch

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            result = agent.fetch_inflation_report()

        assert "US Inflation Data" in result
        assert "CPI (All Items)" in result
        assert "FRED" in result

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_all_series_fail_returns_empty(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.side_effect = RuntimeError("FRED down")
        agent = GlobalMacroAgent()
        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            result = agent.fetch_inflation_report()
        assert result == ""

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_three_series_all_succeed(self, mock_fetch_cache, mock_session_cls):
        """All three series (CPI, Core CPI, PPI) return valid data."""
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        def fake_fetch(policy_name, cache_key, fetch_fn):
            base_values = {
                "fred_CPIAUCSL": 300.0,
                "fred_CPILFESL": 305.0,
                "fred_PPIACO": 250.0,
            }
            base = None
            for key, val in base_values.items():
                if key in cache_key:
                    base = val
                    break
            if base is None:
                return {"observations": []}
            return {
                "observations": [
                    {"date": f"2024-{m:02d}-01", "value": str(base + i * 0.5)}
                    for i, m in enumerate(range(1, 14))
                ]
            }

        mock_fetch_cache.side_effect = fake_fetch

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            result = agent.fetch_inflation_report()

        assert "CPI (All Items)" in result
        assert "Core CPI (ex Food & Energy)" in result
        assert "PPI (All Commodities)" in result
        assert "YoY:" in result

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_dot_values_skipped(self, mock_fetch_cache, mock_session_cls):
        """FRED returns '.' for unpublished observations — should be skipped."""
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        def fake_fetch(policy_name, cache_key, fetch_fn):
            if "fred_CPIAUCSL" in cache_key:
                obs = []
                for i in range(12):
                    obs.append({"date": f"2024-{i+1:02d}-01", "value": str(300.0 + i * 0.5)})
                obs.append({"date": "2025-01-01", "value": "."})   # unpublished, skipped
                obs.append({"date": "2025-02-01", "value": "310.0"})
                return {"observations": obs}
            return {"observations": []}

        mock_fetch_cache.side_effect = fake_fetch

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            result = agent.fetch_inflation_report()

        # Should still work, skipping the "." value; 12 valid + 1 dot = 13 valid after skip
        assert "CPI (All Items)" in result


# ══════════════════════════════════════════════════════════════
# _fetch_fred_series
# ══════════════════════════════════════════════════════════════

class TestFetchFredSeries:
    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_returns_sorted_ascending(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        mock_fetch_cache.return_value = {
            "observations": [
                {"date": "2025-03-01", "value": "310.0"},
                {"date": "2025-01-01", "value": "300.0"},
                {"date": "2025-02-01", "value": "305.0"},
            ]
        }

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            result = agent._fetch_fred_series("CPIAUCSL", limit=3)

        assert len(result) == 3
        assert result[0]["date"] == "2025-01-01"
        assert result[-1]["date"] == "2025-03-01"
        assert result[0]["value"] == 300.0

    @patch("tsmc_macro_agent.requests.Session")
    def test_no_api_key_raises_runtime(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRED_API_KEY", None)
            with pytest.raises(RuntimeError, match="FRED_API_KEY"):
                agent._fetch_fred_series("CPIAUCSL")

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_empty_observations_raises_runtime(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        mock_fetch_cache.return_value = {"observations": []}
        agent = GlobalMacroAgent()
        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            with pytest.raises(RuntimeError, match="no observations"):
                agent._fetch_fred_series("CPIAUCSL")

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_dot_values_excluded(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        mock_fetch_cache.return_value = {
            "observations": [
                {"date": "2025-01-01", "value": "."},
                {"date": "2025-02-01", "value": "300.0"},
                {"date": "2025-03-01", "value": "305.0"},
            ]
        }

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            result = agent._fetch_fred_series("CPIAUCSL")

        assert len(result) == 2
        assert all(o["value"] != "." for o in result)


# ══════════════════════════════════════════════════════════════
# _compute_inflation_yoy
# ══════════════════════════════════════════════════════════════

class TestComputeInflationYoy:
    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_yoy_calculation(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        # 13 observations: 300.0 (oldest) -> 312.0 (latest) = 4.0% YoY
        mock_fetch_cache.return_value = {
            "observations": [
                {"date": f"2024-{m:02d}-01", "value": str(300.0 + i)}
                for i, m in enumerate(range(1, 14))
            ]
        }

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            result = agent._compute_inflation_yoy("CPIAUCSL", "CPI (All Items)")

        assert result is not None
        assert "CPI (All Items) YoY: 4.0%" in result
        assert "312.0" in result
        assert "300.0" in result

    @patch("tsmc_macro_agent.requests.Session")
    def test_insufficient_data_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        with patch("tsmc_macro_agent.GlobalMacroAgent._fetch_fred_series") as mock_fetch:
            mock_fetch.return_value = [{"date": "2025-01-01", "value": 300.0}]  # only 1
            result = agent._compute_inflation_yoy("CPIAUCSL", "CPI")
        assert result is None

    @patch("tsmc_macro_agent.requests.Session")
    def test_fetch_failure_returns_none(self, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        with patch("tsmc_macro_agent.GlobalMacroAgent._fetch_fred_series") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("FRED down")
            result = agent._compute_inflation_yoy("CPIAUCSL", "CPI")
        assert result is None


# ══════════════════════════════════════════════════════════════
# analyze_global_risk with inflation
# ══════════════════════════════════════════════════════════════

class TestAnalyzeGlobalRiskWithInflation:
    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_inflation_appended_when_key_set(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        call_count = 0
        def fake_fetch(policy_name, cache_key, fetch_fn):
            nonlocal call_count
            call_count += 1
            if "TSM" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 180.0}}]}}
            elif "TWD" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 32.0}}]}}
            elif "fred_" in cache_key:
                base = 300.0
                return {
                    "observations": [
                        {"date": f"2024-{m:02d}-01", "value": str(base + i * 0.5)}
                        for i, m in enumerate(range(1, 14))
                    ]
                }
            return {}

        mock_fetch_cache.side_effect = fake_fetch

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            report, score = agent.analyze_global_risk(1100.0)

        assert "US Inflation Data" in report
        assert "CPI (All Items)" in report
        assert "溢價" in report  # ADR part still works

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_no_inflation_when_key_missing(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        def fake_fetch(policy_name, cache_key, fetch_fn):
            if "TSM" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 180.0}}]}}
            elif "TWD" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 32.0}}]}}
            return {}

        mock_fetch_cache.side_effect = fake_fetch

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRED_API_KEY", None)
            report, score = agent.analyze_global_risk(1100.0)

        assert "US Inflation Data" not in report
        assert "溢價" in report  # ADR part still works

    @patch("tsmc_macro_agent.requests.Session")
    @patch("tsmc_macro_agent.fetch_with_cache")
    def test_inflation_failure_does_not_break_adr(self, mock_fetch_cache, mock_session_cls):
        mock_session_cls.return_value = MagicMock()
        agent = GlobalMacroAgent()

        def fake_fetch(policy_name, cache_key, fetch_fn):
            if "TSM" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 180.0}}]}}
            elif "TWD" in cache_key:
                return {"chart": {"result": [{"meta": {"regularMarketPrice": 32.0}}]}}
            raise RuntimeError("FRED down")

        mock_fetch_cache.side_effect = fake_fetch

        with patch.dict(os.environ, {"FRED_API_KEY": "test_key"}):
            report, score = agent.analyze_global_risk(1100.0)

        assert "溢價" in report  # ADR still works
        assert "US Inflation Data" not in report  # inflation gracefully skipped
