#!/usr/bin/env python3
"""
Unit tests for macro_risk.py

Verifies:
- assess_macro_risk: defaults to green, honors _INJECTED override
- is_systemic_event_day: detects >= -5% drop + >= 1.8x avg volume; robust to
  DatetimeIndex; honors _INJECTED override; conservative on bad input
- classify_sell_pressure: systemic / fundamental / unknown branches
- days_since_earnings: BDay count with calendar fallback
"""

import pandas as pd
import pytest
from datetime import date

import macro_risk
from macro_risk import (
    MacroRiskSignal,
    assess_macro_risk,
    is_systemic_event_day,
    classify_sell_pressure,
    days_since_earnings,
    LEVEL_RED,
    LEVEL_GREEN,
)


@pytest.fixture(autouse=True)
def _clear_injection():
    """Each test starts clean; restore no injections afterwards."""
    macro_risk._INJECTED.clear()
    yield
    macro_risk._INJECTED.clear()


# ──────────────────────────────────────────────────────────────────────
# assess_macro_risk
# ──────────────────────────────────────────────────────────────────────
class TestAssessMacroRisk:
    def test_default_is_green(self):
        sig = assess_macro_risk()
        assert sig.level == LEVEL_GREEN
        assert sig.is_red is False
        assert sig.severity == "低"

    def test_injected_red_override(self):
        macro_risk._INJECTED["assess_macro_risk"] = MacroRiskSignal(
            level=LEVEL_RED, is_red=True, reason="跨市場連動",
            factors=["跨市場連動"], severity="高",
        )
        sig = assess_macro_risk()
        assert sig.is_red is True
        assert sig.reason == "跨市場連動"
        assert sig.factors == ["跨市場連動"]


# ──────────────────────────────────────────────────────────────────────
# is_systemic_event_day
# ──────────────────────────────────────────────────────────────────────
def _make_price_df(drop_on=None, vol_mult=1.0):
    """Build a BDay-indexed price df; optionally trigger a crash on `drop_on`."""
    idx = pd.date_range("2026-07-10", "2026-07-17", freq="B")
    close = [1000.0] * len(idx)
    base_vol = 1e9
    vol = [base_vol] * len(idx)
    if drop_on is not None:
        pos = [d.date() for d in idx].index(drop_on)
        close[pos] = 900.0          # -10% drop
        vol[pos] = base_vol * 3.0 * vol_mult
    return pd.DataFrame({"收盤價": close, "成交量": vol}, index=idx)


class TestIsSystemicEventDay:
    def test_normal_day_is_false(self):
        df = _make_price_df()
        assert is_systemic_event_day(df, date(2026, 7, 17)) is False

    def test_crash_day_is_true(self):
        df = _make_price_df(drop_on=date(2026, 7, 17))
        assert is_systemic_event_day(df, date(2026, 7, 17)) is True

    def test_crash_with_insufficient_volume_is_false(self):
        # volume only 1.1x avg, below the 1.8x threshold -> not an event day
        df = _make_price_df(drop_on=date(2026, 7, 17), vol_mult=0.4)
        assert is_systemic_event_day(df, date(2026, 7, 17)) is False

    def test_datetime_index_membership(self):
        # DatetimeIndex must be matched by date string (regression guard)
        df = _make_price_df(drop_on=date(2026, 7, 17))
        assert is_systemic_event_day(df, date(2026, 7, 17)) is True

    def test_string_index_membership(self):
        df = _make_price_df(drop_on=date(2026, 7, 17))
        df.index = [d.strftime("%Y-%m-%d") for d in df.index]
        assert is_systemic_event_day(df, date(2026, 7, 17)) is True

    def test_missing_day_is_false(self):
        df = _make_price_df()
        assert is_systemic_event_day(df, date(2026, 7, 1)) is False

    def test_empty_df_is_false(self):
        assert is_systemic_event_day(pd.DataFrame(), date(2026, 7, 17)) is False

    def test_none_df_is_false(self):
        assert is_systemic_event_day(None, date(2026, 7, 17)) is False

    def test_injected_override(self):
        macro_risk._INJECTED["is_systemic_event_day"] = lambda day: True
        df = _make_price_df()
        assert is_systemic_event_day(df, date(2026, 7, 17)) is True


# ──────────────────────────────────────────────────────────────────────
# classify_sell_pressure
# ──────────────────────────────────────────────────────────────────────
class TestClassifySellPressure:
    def test_systemic_when_is_systemic_true(self):
        res = classify_sell_pressure(90000, date(2026, 7, 17), is_systemic=True)
        assert res["driven_by"] == "systemic"
        assert res["counts_toward_bearish"] is False

    def test_systemic_via_event_days(self):
        res = classify_sell_pressure(
            90000, date(2026, 7, 17),
            event_days={date(2026, 7, 17)},
        )
        assert res["driven_by"] == "systemic"

    def test_fundamental_when_significant_sell(self):
        res = classify_sell_pressure(80000, date(2026, 7, 17))
        assert res["driven_by"] == "fundamental"
        assert res["counts_toward_bearish"] is True

    def test_unknown_when_no_sell(self):
        res = classify_sell_pressure(0, date(2026, 7, 17))
        assert res["driven_by"] == "unknown"
        assert res["counts_toward_bearish"] is False


# ──────────────────────────────────────────────────────────────────────
# days_since_earnings
# ──────────────────────────────────────────────────────────────────────
class TestDaysSinceEarnings:
    def test_bday_count(self):
        # Jul 16 (Thu) -> Jul 17 (Fri) = 1 trading day
        assert days_since_earnings(date(2026, 7, 16), as_of=date(2026, 7, 17)) == 1

    def test_spanning_weekend(self):
        # Jul 16 (Thu) -> Jul 20 (Mon) = 2 trading days
        assert days_since_earnings(date(2026, 7, 16), as_of=date(2026, 7, 20)) == 2

    def test_future_earnings_returns_zero(self):
        assert days_since_earnings(date(2026, 7, 20), as_of=date(2026, 7, 17)) == 0

    def test_none_earnings_returns_zero(self):
        assert days_since_earnings(None, as_of=date(2026, 7, 17)) == 0
