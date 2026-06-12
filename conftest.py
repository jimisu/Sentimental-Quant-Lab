"""
Sentimental-Quant-Lab — Shared Pytest Fixtures

Provides common test fixtures used across all test modules:
- Sample signal data classes
- Temporary directories for cache tests
- Mock configurations
"""

import os
import tempfile
import shutil
from datetime import datetime, timedelta

import pytest

from config import (
    AnalysisConfig,
    CacheConfig,
    ScoreWeightsConfig,
    TechnicalPenaltyConfig,
    BollingerConfig,
    DashboardAlertConfig,
    BigTechConfig,
    ChipAlertConfig,
    ApiConfig,
)
from signal_engine import (
    FinancialSignals,
    TechnicalSignals,
    ChipSignals,
    BigTechSignals,
    MarketSentimentSignals,
    MacroSignals,
    ComprehensiveResult,
)


# ──────────────────────────────────────────────────────────────────────
# Config fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    """Fresh AnalysisConfig instance (not the global singleton)."""
    return AnalysisConfig()


@pytest.fixture
def weights():
    """Fresh ScoreWeightsConfig instance."""
    return ScoreWeightsConfig()


@pytest.fixture
def cache_config():
    """Fresh CacheConfig instance."""
    return CacheConfig()


@pytest.fixture
def penalty_config():
    """Fresh TechnicalPenaltyConfig instance."""
    return TechnicalPenaltyConfig()


@pytest.fixture
def bollinger_config():
    """Fresh BollingerConfig instance."""
    return BollingerConfig()


@pytest.fixture
def alert_config():
    """Fresh DashboardAlertConfig instance."""
    return DashboardAlertConfig()


@pytest.fixture
def bigtech_config():
    """Fresh BigTechConfig instance."""
    return BigTechConfig()


@pytest.fixture
def chip_config():
    """Fresh ChipAlertConfig instance."""
    return ChipAlertConfig()


@pytest.fixture
def api_config():
    """Fresh ApiConfig instance."""
    return ApiConfig()


# ──────────────────────────────────────────────────────────────────────
# Signal data fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def financial_signals_default():
    """Default (clean) financial signals — no warnings expected."""
    return FinancialSignals(
        latest_revenue_yoy=30.0,
        latest_gross_margin=55.0,
        latest_operating_margin=45.0,
        latest_net_margin=40.0,
        gross_drop=0.5,
        op_drop=0.5,
        net_drop=0.5,
        revenue_yoy_declining=False,
        margin_deteriorating=False,
    )


@pytest.fixture
def financial_signals_weak():
    """Weak financial signals — multiple warnings expected."""
    return FinancialSignals(
        latest_revenue_yoy=-5.0,
        latest_gross_margin=45.0,
        latest_operating_margin=35.0,
        latest_net_margin=30.0,
        gross_drop=5.0,
        op_drop=5.0,
        net_drop=5.0,
        revenue_yoy_declining=True,
        margin_deteriorating=True,
    )


@pytest.fixture
def financial_signals_none():
    """All-None financial signals — should return perfect score."""
    return FinancialSignals()


@pytest.fixture
def tech_signals_perfect():
    """Perfect technical signals — all sub-scores at 100."""
    return TechnicalSignals(
        scores={"early": 100, "short": 100, "mid": 100, "long": 100},
        flags={},
    )


@pytest.fixture
def tech_signals_weak():
    """Weak technical signals — all sub-scores low."""
    return TechnicalSignals(
        scores={"early": 30, "short": 40, "mid": 35, "long": 25},
        flags={
            "ma20_cross_below": True,
            "monthly_break_ma12": True,
            "bb_squeeze_break": True,
        },
    )


@pytest.fixture
def chip_signals_perfect():
    """Perfect chip signals."""
    return ChipSignals(score=100, flags={})


@pytest.fixture
def chip_signals_weak():
    """Weak chip signals with big foreign sell."""
    return ChipSignals(score=40, flags={"big_foreign_sell": True})


@pytest.fixture
def bigtech_signals_perfect():
    """Perfect bigtech signals — all capex growing, NVDA strong."""
    return BigTechSignals(
        capex_score=100,
        capex_growing_count=4,
        capex_valid_count=4,
        nvda_revenue_yoy=80.0,
        score=100,
    )


@pytest.fixture
def bigtech_signals_weak():
    """Weak bigtech signals — no capex growing, NVDA declining."""
    return BigTechSignals(
        capex_score=25,
        capex_growing_count=0,
        capex_valid_count=4,
        nvda_revenue_yoy=-10.0,
        score=25,
    )


@pytest.fixture
def bigtech_signals_no_nvda():
    """Bigtech signals with no NVDA data."""
    return BigTechSignals(
        capex_score=75,
        capex_growing_count=2,
        capex_valid_count=4,
        nvda_revenue_yoy=None,
        score=75,
    )


@pytest.fixture
def market_sentiment_perfect():
    """Perfect market sentiment."""
    return MarketSentimentSignals(score=100, volume_trend="normal")


@pytest.fixture
def market_sentiment_weak():
    """Weak market sentiment — declining volume."""
    return MarketSentimentSignals(
        score=40,
        tsmc_volume_declining=True,
        market_volume_declining=True,
        triple_decline=True,
        volume_trend="declining",
    )


# ──────────────────────────────────────────────────────────────────────
# Cache test fixtures
# ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_cache_dir():
    """Create a temporary directory for cache tests, cleaned up after test."""
    d = tempfile.mkdtemp(prefix="sq_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_cache_data():
    """Sample data to store in cache."""
    return {"price": 900.0, "volume": 35000, "date": "2026-01-15"}


@pytest.fixture
def stale_timestamp():
    """A timestamp that is definitely stale (24+ hours old)."""
    return (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")


@pytest.fixture
def fresh_timestamp():
    """A timestamp that is fresh (just now)."""
    return datetime.now().isoformat(timespec="seconds")
