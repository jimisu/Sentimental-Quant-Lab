"""
Sentimental-Quant-Lab — Tests for long_term_monitor.py

Covers the TSMC long-term (3-5 year horizon) structural monitor:
- cached_fetch() — cache hit, cache miss + network fetch/write, stale-TTL
  refetch, and empty-URL failure path (network mocked, CACHE_DIR -> temp).
- fetch_eps_trend() — dict-shaped and list-shaped FinMind parsing, plus the
  empty/no-data fallback returning an empty EPSTrend.
  NOTE: the dict branch contains a real bug (lines 158-159 append EPS twice per
  quarter); that case is marked xfail and documents the correct expectation.
- calculate_fair_value() — UNDERVALUED / FAIR / OVERVALUED branches.
- fetch_current_price() — mocked success and failure (falls back to CURRENT_PRICE).
- fetch_foreign_ownership() — TWSE-shaped cached parsing; empty-cache fallback.
- fetch_earnings_signals() — cached-reconstruction path and known-fallback path.
- assess_earnings_signals() — sentiment / capex / n2 / customer-visibility branches.
- assess_long_term() — BULLISH / NEUTRAL / BEARISH scoring.
- render_dashboard() — string output with section headers + assessment badge.
- EarningsCallSignal.__post_init__ — key_quotes defaults to [].

All filesystem I/O uses tempfile.TemporaryDirectory via the temp_cache_dir fixture.
All network calls are mocked via unittest.mock (patch / MagicMock).
"""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from long_term_monitor import (
    CACHE_DIR,  # imported only to confirm module-level existence; patched in fixture
    EPSTrend,
    CAPEXGuidance,
    N2Timeline,
    ForeignOwnership,
    FairValueRange,
    EarningsCallSignal,
    LongTermSnapshot,
    cached_fetch,
    fetch_eps_trend,
    calculate_fair_value,
    fetch_current_price,
    fetch_foreign_ownership,
    fetch_earnings_signals,
    assess_earnings_signals,
    assess_long_term,
    render_dashboard,
)


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def temp_cache_dir():
    """Point module-level CACHE_DIR at a temp dir for the duration of a test."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with patch("long_term_monitor.CACHE_DIR", tmp):
            yield tmp


def _make_capex(growing: int = 4) -> list:
    capex = []
    for i in range(4):
        yoy = 5.0 if i < growing else -5.0
        capex.append(
            CAPEXGuidance(
                company=f"Co{i}",
                latest_quarter="2026Q1",
                capex_billion_usd=10.0 + i,
                qoq_change=1.0,
                yoy_change=yoy,
            )
        )
    return capex


def _build_snapshot(style: str) -> LongTermSnapshot:
    """Build a LongTermSnapshot engineered to score BULLISH / NEUTRAL / BEARISH."""
    if style == "BULLISH":
        eps = EPSTrend(
            quarters=["2024Q1", "2024Q2", "2024Q3", "2024Q4"],
            eps_values=[3.0, 3.5, 4.0, 4.5],
            yoy_growth=[None, None, None, None],
            cagr_3y=20.0,
            latest_quarter="2024Q4",
            latest_eps=10.0,
        )
        capex = _make_capex(4)
        n2 = N2Timeline(yield_status="On track for 2025 H2")
        foreign = ForeignOwnership(45.0, 1.0, 5.0, [45.0], ["2025-01-01"])
        fair = FairValueRange(
            forward_eps=40.0, pe_low=25, pe_high=30,
            fair_low=1000.0, fair_high=1200.0, current_price=800.0,
            upside_low_pct=25.0, upside_high_pct=50.0, assessment="UNDERVALUED",
        )
        signals = [
            EarningsCallSignal(
                quarter="2025Q2", date="2025-07-17",
                capex_guidance="2025 CAPEX may exceed $42B upper end",
                n2_yield="N2 on track, risk production H2 2025 confirmed",
                customer_visibility="AI demand stronger than forecast",
                sentiment="POSITIVE",
            )
        ]
    elif style == "BEARISH":
        eps = EPSTrend(
            quarters=["2024Q1", "2024Q2", "2024Q3", "2024Q4"],
            eps_values=[3.0, 3.5, 4.0, 4.5],
            yoy_growth=[None, None, None, None],
            cagr_3y=5.0,
            latest_quarter="2024Q4",
            latest_eps=10.0,
        )
        capex = _make_capex(0)
        n2 = N2Timeline(yield_status="Delayed due to yield issues")
        foreign = ForeignOwnership(40.0, -1.0, -3.0, [40.0], ["2025-01-01"])
        fair = FairValueRange(
            forward_eps=40.0, pe_low=25, pe_high=30,
            fair_low=1000.0, fair_high=1200.0, current_price=1300.0,
            upside_low_pct=-23.1, upside_high_pct=-7.7, assessment="OVERVALUED",
        )
        signals = [
            EarningsCallSignal(
                quarter="2025Q2", date="2025-07-17",
                capex_guidance="we cut CAPEX given weak demand",
                n2_yield="N2 delay reported in risk production",
                customer_visibility="demand visibility weak, orders slowing",
                sentiment="NEGATIVE",
            )
        ]
    else:  # NEUTRAL
        eps = EPSTrend(
            quarters=["2024Q1", "2024Q2", "2024Q3", "2024Q4"],
            eps_values=[3.0, 3.5, 4.0, 4.5],
            yoy_growth=[None, None, None, None],
            cagr_3y=12.0,
            latest_quarter="2024Q4",
            latest_eps=10.0,
        )
        capex = _make_capex(2)  # 2/4 growing -> CAPEX momentum risk
        n2 = N2Timeline(yield_status="On track per Q4 call")
        foreign = ForeignOwnership(42.0, 0.5, -1.0, [42.0], ["2025-01-01"])
        fair = FairValueRange(
            forward_eps=40.0, pe_low=25, pe_high=30,
            fair_low=1000.0, fair_high=1200.0, current_price=1100.0,
            upside_low_pct=0.0, upside_high_pct=9.1, assessment="FAIR",
        )
        signals = []  # empty -> assess_earnings_signals returns ([], [])

    snap = LongTermSnapshot(
        timestamp="2025-01-01 00:00:00",
        eps=eps,
        capex=capex,
        n2=n2,
        foreign_ownership=foreign,
        fair_value=fair,
        earnings_signals=signals,
        assessment="",
        key_risks=[],
        catalysts=[],
    )
    # Populate assessment/risks/catalysts the way run_once() does, so the
    # snapshot is render-ready (render_dashboard indexes on snap.assessment).
    assessment, risks, catalysts = assess_long_term(snap)
    snap.assessment = assessment
    snap.key_risks = risks
    snap.catalysts = catalysts
    return snap


# ══════════════════════════════════════════════════════════════
# cached_fetch
# ══════════════════════════════════════════════════════════════

class TestCachedFetch:
    def test_cache_hit_returns_data_without_network(self, temp_cache_dir):
        cache_file = temp_cache_dir / "mykey.json"
        cache_file.write_text(json.dumps({"hello": "world"}))

        with patch("long_term_monitor.requests.get") as mock_get:
            result = cached_fetch("http://example.com", "mykey", 24)

        mock_get.assert_not_called()
        assert result == {"hello": "world"}

    def test_cache_miss_fetches_and_writes(self, temp_cache_dir):
        with patch("long_term_monitor.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"fresh": True}
            mock_get.return_value = mock_resp

            result = cached_fetch("http://example.com", "newkey", 24)

        assert result == {"fresh": True}
        assert (temp_cache_dir / "newkey.json").exists()
        written = json.loads((temp_cache_dir / "newkey.json").read_text())
        assert written == {"fresh": True}

    def test_stale_cache_triggers_refetch(self, temp_cache_dir):
        cache_file = temp_cache_dir / "stalekey.json"
        cache_file.write_text(json.dumps({"old": True}))
        # Backdate the cache file beyond the 1-hour TTL
        old_mtime = (Path(temp_cache_dir) / "stalekey.json").stat().st_mtime - 48 * 3600
        os.utime(cache_file, (old_mtime, old_mtime))

        with patch("long_term_monitor.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"refreshed": True}
            mock_get.return_value = mock_resp

            result = cached_fetch("http://example.com", "stalekey", 1)

        mock_get.assert_called_once()
        assert result == {"refreshed": True}

    def test_empty_url_failure_returns_none(self, temp_cache_dir):
        """Empty URL + no cache -> network failure path -> None (no real network)."""
        with patch("long_term_monitor.requests.get", side_effect=Exception("network down")) as mock_get:
            result = cached_fetch("", "failkey", 24)

        mock_get.assert_called_once()
        assert result is None

    def test_network_failure_without_cache_returns_none(self, temp_cache_dir):
        with patch("long_term_monitor.requests.get", side_effect=RuntimeError("timeout")) as mock_get:
            result = cached_fetch("http://example.com", "no_cache_key", 24)

        mock_get.assert_called_once()
        assert result is None


# ══════════════════════════════════════════════════════════════
# fetch_eps_trend
# ══════════════════════════════════════════════════════════════

class TestFetchEpsTrend:
    @patch("long_term_monitor.cached_fetch")
    def test_list_shaped_data_parses_once_per_record(self, mock_cached):
        mock_cached.return_value = {
            "data": [
                {"type": "EPS", "value": "9.0", "date": "2025-03-31"},
                {"type": "EPS", "value": "10.0", "date": "2025-06-30"},
                {"type": "EPS", "value": "11.0", "date": "2025-09-30"},
                {"type": "NOT_EPS", "value": "999.0", "date": "2025-12-31"},
            ]
        }
        trend = fetch_eps_trend()
        assert trend.quarters == ["2025-03", "2025-06", "2025-09"]
        assert trend.eps_values == [9.0, 10.0, 11.0]
        assert trend.latest_eps == 11.0
        assert trend.latest_quarter == "2025-09"

    @patch("long_term_monitor.cached_fetch")
    def test_dict_shaped_data_parses_once_per_quarter(self, mock_cached):
        """
        The dict branch reads the dashboard's quarterly-margins cache, which is
        produced by serialize_quarterly_margins(): keys are "YYYYQ<n>" strings
        (JSON cannot store tuple keys) and each value dict carries an "eps"
        field. Each quarter's EPS must be appended exactly once, sorted
        chronologically by the (string) quarter label.
        """
        mock_cached.return_value = {
            "data": {
                "2026Q1": {"eps": 11.0},
                "2025Q4": {"eps": 10.0},
                "2025Q3": {"eps": 9.0},
            }
        }
        trend = fetch_eps_trend()
        # One EPS value per quarter, sorted by the "YYYYQ<n>" string key.
        assert trend.quarters == ["2025Q3", "2025Q4", "2026Q1"]
        assert trend.eps_values == [9.0, 10.0, 11.0]
        assert trend.latest_eps == 11.0
        assert trend.latest_quarter == "2026Q1"

    @patch("long_term_monitor.cached_fetch")
    def test_empty_data_fallback_returns_empty_trend(self, mock_cached):
        mock_cached.return_value = None

        # Fallback network call returns non-200 -> empty EPSTrend.
        # NOTE: fetch_eps_trend does a *local* `import requests`, so the network
        # call must be mocked via the real `requests.get`, not
        # long_term_monitor.requests.get.
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_get.return_value = mock_resp
            trend = fetch_eps_trend()

        assert isinstance(trend, EPSTrend)
        assert trend.quarters == []
        assert trend.eps_values == []
        assert trend.yoy_growth == []
        assert trend.latest_eps == 0.0

    @patch("long_term_monitor.cached_fetch")
    def test_no_data_key_fallback_returns_empty_trend(self, mock_cached):
        mock_cached.return_value = {"other": "payload-without-data-key"}
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_get.return_value = mock_resp
            trend = fetch_eps_trend()
        assert trend.eps_values == []


# ══════════════════════════════════════════════════════════════
# calculate_fair_value
# ══════════════════════════════════════════════════════════════

class TestCalculateFairValue:
    def _eps(self, latest_eps=10.0, values=None):
        return EPSTrend(
            quarters=["2024Q1"], eps_values=values or [latest_eps],
            yoy_growth=[None], latest_quarter="2024Q4", latest_eps=latest_eps,

        )

    def test_undervalued_branch(self):
        eps = self._eps(10.0)
        fv = calculate_fair_value(eps, current_price=800.0)
        # forward_eps = 10*4 = 40; fair_low = 1000, fair_high = 1200
        assert fv.forward_eps == 40.0
        assert fv.fair_low == 1000.0
        assert fv.fair_high == 1200.0
        assert fv.upside_low_pct == 25.0   # (1000-800)/800*100
        assert fv.upside_high_pct == 50.0  # (1200-800)/800*100
        assert fv.assessment == "UNDERVALUED"

    def test_fair_branch(self):
        eps = self._eps(10.0)
        fv = calculate_fair_value(eps, current_price=1100.0)
        assert fv.assessment == "FAIR"

    def test_overvalued_branch(self):
        eps = self._eps(10.0)
        fv = calculate_fair_value(eps, current_price=1300.0)
        assert fv.assessment == "OVERVALUED"
        # upside is negative (downside)
        assert fv.upside_low_pct < 0

    def test_forward_eps_uses_latest_value_when_latest_eps_zero(self):
        # latest_eps <= 0 -> falls back to last element of eps_values
        eps = EPSTrend(
            quarters=["2024Q1", "2024Q2"], eps_values=[2.0, 3.0],
            yoy_growth=[None, None], latest_quarter="2024Q2", latest_eps=0.0,
        )
        fv = calculate_fair_value(eps, current_price=800.0)
        assert fv.forward_eps == 12.0  # 3.0 * 4

    def test_trailing_4q_used_when_available(self):
        eps = EPSTrend(
            quarters=["x"] * 5, eps_values=[1.0, 2.0, 3.0, 4.0, 5.0],
            yoy_growth=[None] * 5, latest_quarter="q", latest_eps=5.0,
        )
        fv = calculate_fair_value(eps, current_price=100.0)
        # forward_eps based on latest_eps=5 -> 20; trailing 4Q sum = 14 (reference only)
        assert fv.forward_eps == 20.0


# ══════════════════════════════════════════════════════════════
# fetch_current_price
# ══════════════════════════════════════════════════════════════

class TestFetchCurrentPrice:
    def test_success_returns_market_price(self):
        with patch("long_term_monitor.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "chart": {"result": [{"meta": {"regularMarketPrice": 2300.0}}]}
            }
            mock_get.return_value = mock_resp

            price = fetch_current_price()

        assert price == 2300.0

    def test_failure_falls_back_to_current_price(self):
        with patch("long_term_monitor.requests.get", side_effect=Exception("down")):
            price = fetch_current_price()
        # CURRENT_PRICE constant from module
        assert price == 2465

    def test_non_200_falls_back_to_current_price(self):
        with patch("long_term_monitor.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_get.return_value = mock_resp
            price = fetch_current_price()
        assert price == 2465


# ══════════════════════════════════════════════════════════════
# fetch_foreign_ownership
# ══════════════════════════════════════════════════════════════

class TestFetchForeignOwnership:
    def test_empty_cache_fallback_returns_zeros(self, temp_cache_dir):
        with patch("long_term_monitor.requests.get", side_effect=Exception("no net")):
            fo = fetch_foreign_ownership()
        assert fo.current_pct == 0
        assert fo.monthly_change == 0
        assert fo.yearly_change == 0
        assert fo.trend_12m == []
        assert fo.dates_12m == []

    def test_parses_twse_shaped_cache(self, temp_cache_dir):
        payload = {
            "data": [
                {"date": "2024-01-01", "ForeignInvestmentSharesRatio": "38.0"},
                {"date": "2024-02-01", "ForeignInvestmentSharesRatio": "40.0"},
                {"date": "2024-03-01", "ForeignInvestmentSharesRatio": "42.0"},
            ]
        }
        (temp_cache_dir / "tsmc_foreign_ownership.json").write_text(json.dumps(payload))

        fo = fetch_foreign_ownership()
        assert fo.current_pct == 42.0
        assert fo.dates_12m == ["2024-01-01", "2024-02-01", "2024-03-01"]
        assert fo.trend_12m == [38.0, 40.0, 42.0]
        # Not enough history for monthly/yearly deltas -> 0
        assert fo.monthly_change == 0
        assert fo.yearly_change == 0

    def test_parses_full_252_entry_history(self, temp_cache_dir):
        data = [
            {"date": f"2024-{i:03d}", "ForeignInvestmentSharesRatio": str(float(i))}
            for i in range(252)
        ]
        payload = {"data": data}
        (temp_cache_dir / "tsmc_foreign_ownership.json").write_text(json.dumps(payload))

        fo = fetch_foreign_ownership()
        assert fo.current_pct == 251.0
        assert fo.monthly_change == 21.0   # values[-1] - values[-22] = 251 - 230
        assert fo.yearly_change == 251.0   # values[-1] - values[-252] = 251 - 0
        assert len(fo.trend_12m) == 252


# ══════════════════════════════════════════════════════════════
# fetch_earnings_signals
# ══════════════════════════════════════════════════════════════

class TestFetchEarningsSignals:
    def test_cached_path_reconstructs_and_sorts(self, temp_cache_dir):
        cached_payload = {
            "data": [
                {
                    "quarter": "2025Q1", "date": "2025-04-17",
                    "capex_guidance": "maintained", "n2_yield": "on track",
                    "customer_visibility": "robust", "sentiment": "NEUTRAL",
                },
                {
                    "quarter": "2025Q2", "date": "2025-07-17",
                    "capex_guidance": "exceed", "n2_yield": "on track",
                    "customer_visibility": "strong", "sentiment": "POSITIVE",
                },
            ]
        }
        (temp_cache_dir / "tsmc_earnings_signals.json").write_text(
            json.dumps(cached_payload)
        )

        signals = fetch_earnings_signals()
        assert len(signals) == 2
        # Sorted by date descending: 2025-07-17 first
        assert signals[0].quarter == "2025Q2"
        assert signals[0].key_quotes == []

    def test_fallback_path_returns_known_signals_sorted(self, temp_cache_dir):
        with patch("long_term_monitor.requests.get", side_effect=Exception("no net")):
            signals = fetch_earnings_signals()

        assert len(signals) == 3
        # Latest date first: 2025-07-17 (2025Q2)
        assert signals[0].quarter == "2025Q2"
        # Cache file should have been written
        assert (temp_cache_dir / "tsmc_earnings_signals.json").exists()

    def test_fallback_path_writes_cache_file(self, temp_cache_dir):
        with patch("long_term_monitor.requests.get", side_effect=Exception("no net")):
            fetch_earnings_signals()
        cache_file = temp_cache_dir / "tsmc_earnings_signals.json"
        assert cache_file.exists()
        written = json.loads(cache_file.read_text())
        assert "data" in written
        assert len(written["data"]) == 3


# ══════════════════════════════════════════════════════════════
# assess_earnings_signals
# ══════════════════════════════════════════════════════════════

class TestAssessEarningsSignals:
    def test_empty_signals_returns_empty_lists(self):
        risks, catalysts = assess_earnings_signals([])
        assert risks == []
        assert catalysts == []

    def test_positive_sentiment_catalyst(self):
        sig = [
            EarningsCallSignal(
                quarter="2025Q2", date="2025-07-17",
                capex_guidance="no change to outlook",
                n2_yield="on track", customer_visibility="strong demand",
                sentiment="POSITIVE",
            )
        ]
        risks, catalysts = assess_earnings_signals(sig)
        assert any("positive" in c.lower() for c in catalysts)
        assert any("exceed" in c.lower() or "maintain" in c.lower() for c in catalysts)
        assert any("on track" in c.lower() for c in catalysts)
        assert any("strong" in c.lower() for c in catalysts)
        assert risks == []

    def test_negative_sentiment_risk(self):
        sig = [
            EarningsCallSignal(
                quarter="2025Q2", date="2025-07-17",
                capex_guidance="we cut CAPEX",
                n2_yield="delay in production",
                customer_visibility="weak demand, slowing",
                sentiment="NEGATIVE",
            )
        ]
        risks, catalysts = assess_earnings_signals(sig)
        assert any("cautious" in r.lower() for r in risks)
        assert any("cut" in r.lower() for r in risks)
        assert any("delay" in r.lower() for r in risks)
        assert any("weak" in r.lower() for r in risks)
        assert catalysts == []

    def test_capex_increase_catalyst(self):
        sig = [
            EarningsCallSignal(
                quarter="2025Q2", date="2025-07-17",
                capex_guidance="we increase CAPEX to meet demand",
                n2_yield="x", customer_visibility="y", sentiment="NEUTRAL",
            )
        ]
        risks, catalysts = assess_earnings_signals(sig)
        assert any("raised" in c.lower() for c in catalysts)
        assert risks == []

    def test_n2_progressing_catalyst(self):
        sig = [
            EarningsCallSignal(
                quarter="2025Q2", date="2025-07-17",
                capex_guidance="x", n2_yield="yield progressing well",
                customer_visibility="y", sentiment="NEUTRAL",
            )
        ]
        risks, catalysts = assess_earnings_signals(sig)
        assert any("on track" in c.lower() or "progressing" in c.lower() for c in catalysts)

    def test_customer_exceed_catalyst(self):
        sig = [
            EarningsCallSignal(
                quarter="2025Q2", date="2025-07-17",
                capex_guidance="x", n2_yield="y",
                customer_visibility="demand exceed expectations",
                sentiment="NEUTRAL",
            )
        ]
        risks, catalysts = assess_earnings_signals(sig)
        assert any("strong" in c.lower() or "exceed" in c.lower() for c in catalysts)


# ══════════════════════════════════════════════════════════════
# assess_long_term
# ══════════════════════════════════════════════════════════════

class TestAssessLongTerm:
    def test_bullish_scoring(self):
        snap = _build_snapshot("BULLISH")
        assessment, risks, catalysts = assess_long_term(snap)
        assert assessment == "BULLISH"
        assert len(catalysts) - len(risks) >= 2

    def test_neutral_scoring(self):
        snap = _build_snapshot("NEUTRAL")
        assessment, risks, catalysts = assess_long_term(snap)
        assert assessment == "NEUTRAL"
        # score in (-1, 2)
        assert -1 < (len(catalysts) - len(risks)) < 2

    def test_bearish_scoring(self):
        snap = _build_snapshot("BEARISH")
        assessment, risks, catalysts = assess_long_term(snap)
        assert assessment == "BEARISH"
        assert len(catalysts) - len(risks) <= -1

    def test_eps_cagr_risk_branch(self):
        snap = _build_snapshot("BULLISH")
        snap.eps.cagr_3y = 5.0  # below 10 -> risk branch
        assessment, risks, catalysts = assess_long_term(snap)
        assert any("below 10%" in r for r in risks)

    def test_eps_cagr_catalyst_branch(self):
        snap = _build_snapshot("NEUTRAL")
        snap.eps.cagr_3y = 18.0  # >= 15 -> catalyst
        assessment, risks, catalysts = assess_long_term(snap)
        assert any("> 15% hurdle" in c for c in catalysts)


# ══════════════════════════════════════════════════════════════
# EarningsCallSignal dataclass
# ══════════════════════════════════════════════════════════════

class TestEarningsCallSignalPostInit:
    def test_key_quotes_defaults_to_empty_list(self):
        sig = EarningsCallSignal(quarter="2025Q1", date="2025-01-01")
        assert sig.key_quotes == []
        assert isinstance(sig.key_quotes, list)

    def test_key_quotes_preserved_when_provided(self):
        quotes = ["CAPEX flexibility to the upside", "N2 on schedule"]
        sig = EarningsCallSignal(
            quarter="2025Q1", date="2025-01-01", key_quotes=quotes
        )
        assert sig.key_quotes == quotes


# ══════════════════════════════════════════════════════════════
# render_dashboard
# ══════════════════════════════════════════════════════════════

class TestRenderDashboard:
    def _check_sections(self, output: str):
        assert "STRUCTURAL ASSESSMENT" in output
        assert "EPS TRAJECTORY" in output
        assert "BIG TECH CAPEX" in output
        assert "N2 NODE TIMELINE" in output
        assert "FAIR VALUE RANGE" in output
        assert "EARNINGS CALL SIGNALS" in output
        assert "FOREIGN OWNERSHIP" in output
        assert "KEY RISKS" in output
        assert "CATALYSTS" in output

    def test_render_bullish(self):
        snap = _build_snapshot("BULLISH")
        output = render_dashboard(snap)
        assert isinstance(output, str)
        assert "🟢" in output
        assert "BULLISH" in output
        self._check_sections(output)

    def test_render_neutral(self):
        snap = _build_snapshot("NEUTRAL")
        output = render_dashboard(snap)
        assert "🟡" in output
        assert "NEUTRAL" in output
        self._check_sections(output)

    def test_render_bearish(self):
        snap = _build_snapshot("BEARISH")
        output = render_dashboard(snap)
        assert "🔴" in output
        assert "BEARISH" in output
        self._check_sections(output)

    def test_render_handles_empty_earnings_signals(self):
        snap = _build_snapshot("NEUTRAL")
        output = render_dashboard(snap)
        assert "(No earnings signals cached)" in output
