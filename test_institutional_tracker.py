"""
Sentimental-Quant-Lab — Tests for tsmc_institutional_tracker.py

Covers: INSTITUTION_REGISTRY, DEFAULT_TRACKED_CIKs, _match_name,
InstitutionalTrackerAgent initialization, analyze_all_institutions structure,
and the multi-institution report format.
"""

import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock, call

import pytest

import tsmc_institutional_tracker
from tsmc_institutional_tracker import (
    INSTITUTION_REGISTRY,
    DEFAULT_TRACKED_CIKs,
    TARGET_COMPANIES,
    _match_name,
    InstitutionalTrackerAgent,
    SEC_HEADERS,
    NS,
)


# ══════════════════════════════════════════════════════════════
# INSTITUTION_REGISTRY & DEFAULT_TRACKED_CIKs
# ══════════════════════════════════════════════════════════════

class TestInstitutionRegistry:
    def test_blackrock_registered(self):
        assert "0002012383" in INSTITUTION_REGISTRY
        assert INSTITUTION_REGISTRY["0002012383"]["name"] == "BlackRock, Inc."
        assert INSTITUTION_REGISTRY["0002012383"]["short_name"] == "BlackRock"

    def test_bridgewater_registered(self):
        assert "0001350694" in INSTITUTION_REGISTRY
        assert INSTITUTION_REGISTRY["0001350694"]["name"] == "Bridgewater Associates, LP"
        assert INSTITUTION_REGISTRY["0001350694"]["short_name"] == "Bridgewater"

    def test_at_least_two_institutions(self):
        assert len(INSTITUTION_REGISTRY) >= 2

    def test_each_institution_has_required_keys(self):
        for cik, info in INSTITUTION_REGISTRY.items():
            assert "name" in info, f"CIK {cik} missing 'name'"
            assert "short_name" in info, f"CIK {cik} missing 'short_name'"

    def test_default_tracked_ciks_matches_registry(self):
        assert set(DEFAULT_TRACKED_CIKs) == set(INSTITUTION_REGISTRY.keys())

    def test_default_tracked_ciks_includes_blackrock(self):
        assert "0002012383" in DEFAULT_TRACKED_CIKs

    def test_default_tracked_ciks_includes_bridgewater(self):
        assert "0001350694" in DEFAULT_TRACKED_CIKs


# ══════════════════════════════════════════════════════════════
# TARGET_COMPANIES
# ══════════════════════════════════════════════════════════════

class TestTargetCompanies:
    def test_five_targets_defined(self):
        assert len(TARGET_COMPANIES) == 5

    def test_all_required_tickers_present(self):
        assert set(TARGET_COMPANIES.keys()) == {"TSM", "MSFT", "GOOGL", "AMZN", "NVDA"}

    def test_each_target_has_match_names(self):
        for ticker, meta in TARGET_COMPANIES.items():
            assert "match_names" in meta, f"{ticker} missing match_names"
            assert len(meta["match_names"]) > 0, f"{ticker} has empty match_names"

    def test_tsm_match_names_include_tsmc(self):
        assert any("TAIWAN SEMICONDUCTOR" in mn for mn in TARGET_COMPANIES["TSM"]["match_names"])


# ══════════════════════════════════════════════════════════════
# _match_name
# ══════════════════════════════════════════════════════════════

class TestMatchName:
    def test_exact_match(self):
        assert _match_name("TAIWAN SEMICONDUCTOR MFG CO", ["TAIWAN SEMICONDUCTOR"]) is True

    def test_case_insensitive(self):
        assert _match_name("taiwan semiconductor mfg", ["TAIWAN SEMICONDUCTOR"]) is True

    def test_no_match(self):
        assert _match_name("APPLE INC", ["TAIWAN SEMICONDUCTOR"]) is False

    def test_empty_issuer_name(self):
        assert _match_name("", ["TAIWAN SEMICONDUCTOR"]) is False

    def test_none_issuer_name(self):
        assert _match_name(None, ["TAIWAN SEMICONDUCTOR"]) is False

    def test_empty_match_names(self):
        assert _match_name("TAIWAN SEMICONDUCTOR", []) is False

    def test_partial_match_within_string(self):
        assert _match_name("NVIDIA CORP.", ["NVIDIA CORP"]) is True

    def test_whitespace_handling(self):
        assert _match_name("  NVIDIA CORP  ", ["NVIDIA CORP"]) is True


# ══════════════════════════════════════════════════════════════
# InstitutionalTrackerAgent — Initialization
# ══════════════════════════════════════════════════════════════

class TestAgentInit:
    def test_default_tracked_ciks(self):
        agent = InstitutionalTrackerAgent()
        assert agent.tracked_ciks == DEFAULT_TRACKED_CIKs

    def test_custom_tracked_ciks(self):
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        assert agent.tracked_ciks == ["0002012383"]

    def test_none_tracked_ciks_uses_default(self):
        agent = InstitutionalTrackerAgent(tracked_ciks=None)
        assert agent.tracked_ciks == DEFAULT_TRACKED_CIKs

    def test_name_attribute(self):
        agent = InstitutionalTrackerAgent()
        assert agent.name == "機構法人 13F 追蹤 Agent"

    def test_source_attribute(self):
        agent = InstitutionalTrackerAgent()
        assert agent.source == "SEC EDGAR Form 13F-HR"


# ══════════════════════════════════════════════════════════════
# _parse_holdings
# ══════════════════════════════════════════════════════════════

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>TAIWAN SEMICONDUCTOR MFG CO LTD</nameOfIssuer>
    <titleOfClass>SPONSORED ADR</titleOfClass>
    <cusip>874039100</cusip>
    <value>1500000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>10000000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>MICROSOFT CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>594918104</cusip>
    <value>2000000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>5000000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>3000000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>8000000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
  </infoTable>
</informationTable>"""

SAMPLE_XML_NO_NS = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable>
  <infoTable>
    <nameOfIssuer>NVIDIA CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>67066G104</cusip>
    <value>500000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>2000000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


class TestParseHoldings:
    def test_parses_tsm_holding(self):
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        holdings = agent._parse_holdings(SAMPLE_XML)
        assert "TSM" in holdings
        assert holdings["TSM"]["shares"] == 10000000
        assert holdings["TSM"]["value_k"] == 1500000.0  # 1.5B / 1000

    def test_parses_msft_holding(self):
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        holdings = agent._parse_holdings(SAMPLE_XML)
        assert "MSFT" in holdings
        assert holdings["MSFT"]["shares"] == 5000000

    def test_ignores_non_target_companies(self):
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        holdings = agent._parse_holdings(SAMPLE_XML)
        # APPLE is not in TARGET_COMPANIES
        assert len(holdings) == 2  # Only TSM and MSFT

    def test_namespace_fallback(self):
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        holdings = agent._parse_holdings(SAMPLE_XML_NO_NS)
        assert "NVDA" in holdings
        assert holdings["NVDA"]["shares"] == 2000000

    def test_empty_xml(self):
        """XML with infoTable tag but no entries should return empty dict."""
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        empty_xml = '<?xml version="1.0"?><informationTable xmlns="' + NS + '"><infoTable></infoTable></informationTable>'
        holdings = agent._parse_holdings(empty_xml)
        assert holdings == {}

    def test_unrecognized_format_raises_error(self):
        """Text with no <infoTable> or <tr> tags should raise RuntimeError."""
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        import pytest
        with pytest.raises(RuntimeError, match="無法識別的 13F 持股明細格式"):
            agent._parse_holdings("not valid xml")

    def test_accumulates_multiple_entries_for_same_ticker(self):
        """If two infoTable entries match the same ticker, shares and value should accumulate."""
        xml = """<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>TAIWAN SEMICONDUCTOR MFG CO LTD</nameOfIssuer>
    <value>1000000000</value>
    <shrsOrPrnAmt><sshPrnamt>5000000</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>TSMC ADR</nameOfIssuer>
    <value>500000000</value>
    <shrsOrPrnAmt><sshPrnamt>3000000</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        holdings = agent._parse_holdings(xml)
        assert "TSM" in holdings
        assert holdings["TSM"]["shares"] == 8000000  # 5M + 3M
        assert holdings["TSM"]["value_k"] == 1500000.0  # 1.5B / 1000


# ══════════════════════════════════════════════════════════════
# analyze_13f_holdings — Single Institution
# ══════════════════════════════════════════════════════════════

class TestAnalyze13fHoldings:
    """Test single-institution analysis with mocked HTTP calls."""

    def setup_method(self):
        """Clear local cache before each test to prevent real cache interference."""
        import glob as _glob, os as _os
        for pattern in ["local_cache/sec_13f_infotable_0002012383*.json",
                        "local_cache/sec_13f_info_0002012383*.json"]:
            for fpath in _glob.glob(pattern):
                _os.remove(fpath)

    def _make_submission_response(self):
        return {
            "filings": {
                "recent": {
                    "form": ["13F-HR", "13F-HR", "10-K"],
                    "accessionNumber": ["0002012383-24-000001", "0002012383-23-000001", "other"],
                    "filingDate": ["2024-02-14", "2023-11-14", "2024-01-30"],
                    "primaryDocument": ["infotable.xml", "infotable.xml", ""],
                    "reportDate": ["2023-12-31", "2023-09-30", ""],
                }
            }
        }

    def _make_info_table_xml(self, holdings_data):
        """Generate a minimal 13F info table XML."""
        entries = ""
        for name, shares, value in holdings_data:
            entries += f"""
            <infoTable>
                <nameOfIssuer>{name}</nameOfIssuer>
                <value>{value}</value>
                <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt></shrsOrPrnAmt>
            </infoTable>"""
        return f'<?xml version="1.0"?><informationTable xmlns="{NS}">{entries}</informationTable>'

    @patch("tsmc_institutional_tracker.should_fetch_from_sec", return_value=True)
    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_single_institution_tsm_increased(self, mock_fetch, _mock_should):
        """TSM shares increased → score should be 80."""
        # curl_cffi is not installed in test env; bypass the check
        tsmc_institutional_tracker._HAS_CURL_CFFI = True
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])

        # Track call count to distinguish current (1st info call) vs previous (2nd)
        call_count = {"info": 0}

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                call_count["info"] += 1
                if call_count["info"] == 1:  # current quarter
                    return self._make_info_table_xml([
                        ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                    ])
                else:  # previous quarter
                    return self._make_info_table_xml([
                        ("TAIWAN SEMICONDUCTOR MFG CO LTD", 8000000, 1200000000),
                    ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        data, report = agent.analyze_13f_holdings(cik="0002012383")
        assert data["score"] == 80
        assert data["cik"] == "0002012383"
        assert data["institution_name"] == "BlackRock, Inc."
        assert "TSM" in data["holdings"]
        assert data["holdings"]["TSM"]["status"] == "increased"
        assert "BlackRock" in report

    @patch("tsmc_institutional_tracker.should_fetch_from_sec", return_value=True)
    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_single_institution_tsm_decreased(self, mock_fetch, _mock_should):
        """TSM shares decreased → score should be 40."""
        tsmc_institutional_tracker._HAS_CURL_CFFI = True
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])

        call_count = {"info": 0}

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                call_count["info"] += 1
                if call_count["info"] == 1:  # current quarter (fewer shares)
                    return self._make_info_table_xml([
                        ("TAIWAN SEMICONDUCTOR MFG CO LTD", 7000000, 1000000000),
                    ])
                else:  # previous quarter (more shares)
                    return self._make_info_table_xml([
                        ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                    ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        data, report = agent.analyze_13f_holdings(cik="0002012383")
        assert data["score"] == 40
        assert data["holdings"]["TSM"]["status"] == "decreased"

    @patch("tsmc_institutional_tracker.should_fetch_from_sec", return_value=True)
    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_single_institution_tsm_exited(self, mock_fetch, _mock_should):
        """TSM fully exited → score should be 20."""
        tsmc_institutional_tracker._HAS_CURL_CFFI = True
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])

        call_count = {"info": 0}

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                call_count["info"] += 1
                if call_count["info"] == 1:  # current quarter (no TSM)
                    return self._make_info_table_xml([
                        ("MICROSOFT CORP", 5000000, 2000000000),
                    ])
                else:  # previous quarter (had TSM)
                    return self._make_info_table_xml([
                        ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                    ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        data, report = agent.analyze_13f_holdings(cik="0002012383")
        assert data["score"] == 20
        assert data["holdings"]["TSM"]["status"] == "exited"

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_single_institution_error_handling(self, mock_fetch):
        """If SEC API fails, should return error data."""
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])
        mock_fetch.side_effect = RuntimeError("SEC API unavailable")

        data, report = agent.analyze_13f_holdings(cik="0002012383")
        assert "error" in data
        assert data["cik"] == "0002012383"
        assert "SEC API unavailable" in report

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_no_13f_filings_returns_error(self, mock_fetch):
        """If no 13F filings found, should return error."""
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return {"filings": {"recent": {"form": ["10-K"], "accessionNumber": ["x"],
                    "filingDate": ["2024-01-01"], "primaryDocument": [""], "reportDate": [""]}}}
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        data, report = agent.analyze_13f_holdings(cik="0002012383")
        assert "error" in data


# ══════════════════════════════════════════════════════════════
# analyze_all_institutions — Multi-Institution
# ══════════════════════════════════════════════════════════════

class TestAnalyzeAllInstitutions:
    """Test multi-institution analysis."""

    def _make_submission_response(self):
        return {
            "filings": {
                "recent": {
                    "form": ["13F-HR", "13F-HR"],
                    "accessionNumber": ["0002012383-24-000001", "0002012383-23-000001"],
                    "filingDate": ["2024-02-14", "2023-11-14"],
                    "primaryDocument": ["infotable.xml", "infotable.xml"],
                    "reportDate": ["2023-12-31", "2023-09-30"],
                }
            }
        }

    def _make_info_table_xml(self, holdings_data):
        entries = ""
        for name, shares, value in holdings_data:
            entries += f"""
            <infoTable>
                <nameOfIssuer>{name}</nameOfIssuer>
                <value>{value}</value>
                <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt></shrsOrPrnAmt>
            </infoTable>"""
        return f'<?xml version="1.0"?><informationTable xmlns="{NS}">{entries}</informationTable>'

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_returns_data_for_all_institutions(self, mock_fetch):
        """analyze_all_institutions should return data for each tracked institution."""
        agent = InstitutionalTrackerAgent()  # Uses DEFAULT_TRACKED_CIKs

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                return self._make_info_table_xml([
                    ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                    ("MICROSOFT CORP", 5000000, 2000000000),
                ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        all_data, combined_report = agent.analyze_all_institutions()

        # Should have one data dict per tracked institution
        assert len(all_data) == len(DEFAULT_TRACKED_CIKs)
        # Each should have a CIK
        for data in all_data:
            assert "cik" in data
            assert data["cik"] in INSTITUTION_REGISTRY

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_combined_report_contains_all_institution_names(self, mock_fetch):
        """Combined report should mention each institution's name."""
        agent = InstitutionalTrackerAgent()

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                return self._make_info_table_xml([
                    ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        all_data, combined_report = agent.analyze_all_institutions()

        # Report should contain each institution's name
        for cik in agent.tracked_ciks:
            inst_name = INSTITUTION_REGISTRY[cik]["name"]
            assert inst_name in combined_report, f"Report missing {inst_name}"

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_combined_report_has_cross_institution_comparison(self, mock_fetch):
        """Combined report should include a cross-institution comparison section."""
        agent = InstitutionalTrackerAgent()

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                return self._make_info_table_xml([
                    ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        all_data, combined_report = agent.analyze_all_institutions()

        assert "跨機構比較摘要" in combined_report
        assert "BlackRock" in combined_report
        assert "Bridgewater" in combined_report

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_combined_report_has_tracking_institution_list(self, mock_fetch):
        """Combined report header should list all tracked institutions."""
        agent = InstitutionalTrackerAgent()

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                return self._make_info_table_xml([
                    ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        all_data, combined_report = agent.analyze_all_institutions()

        assert "追蹤機構" in combined_report

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_partial_failure_still_returns_other_institutions(self, mock_fetch):
        """If one institution fails, others should still be returned."""
        agent = InstitutionalTrackerAgent()

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                if "1364742" in cache_key:
                    return self._make_submission_response()
                else:
                    raise RuntimeError("Bridgewater data unavailable")
            elif "infotable_" in cache_key:
                return self._make_info_table_xml([
                    ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        all_data, combined_report = agent.analyze_all_institutions()

        # Should have data for both institutions
        assert len(all_data) == len(DEFAULT_TRACKED_CIKs)
        # One should have an error
        errors = [d for d in all_data if "error" in d]
        assert len(errors) >= 1

    @patch("tsmc_institutional_tracker.fetch_with_cache")
    def test_custom_ciks_subset(self, mock_fetch):
        """Agent with custom tracked_ciks should only analyze those."""
        agent = InstitutionalTrackerAgent(tracked_ciks=["0002012383"])

        def side_effect(policy_name, cache_key, fetch_fn, directory="local_cache"):
            if "submissions" in cache_key:
                return self._make_submission_response()
            elif "infotable_" in cache_key:
                return self._make_info_table_xml([
                    ("TAIWAN SEMICONDUCTOR MFG CO LTD", 10000000, 1500000000),
                ])
            return fetch_fn()

        mock_fetch.side_effect = side_effect

        all_data, combined_report = agent.analyze_all_institutions()

        assert len(all_data) == 1
        assert all_data[0]["cik"] == "0002012383"
