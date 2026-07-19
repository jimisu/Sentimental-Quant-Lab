"""
Sentimental-Quant-Lab — Tests for config.py

Covers all dataclass configs: AnalysisConfig, CacheConfig, ScoreWeightsConfig,
TechnicalPenaltyConfig, BollingerConfig, DashboardAlertConfig, BigTechConfig,
ChipAlertConfig, ApiConfig, and the global CONFIG singleton.
"""

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
    CONFIG,
)


# ══════════════════════════════════════════════════════════════
# AnalysisConfig (main composite)
# ══════════════════════════════════════════════════════════════

class TestAnalysisConfig:
    def test_default_instantiation_succeeds(self, config):
        """AnalysisConfig instantiates with all sub-configs present."""
        assert isinstance(config.cache, CacheConfig)
        assert isinstance(config.weights, ScoreWeightsConfig)
        assert isinstance(config.penalty, TechnicalPenaltyConfig)
        assert isinstance(config.bollinger, BollingerConfig)
        assert isinstance(config.alert, DashboardAlertConfig)
        assert isinstance(config.bigtech, BigTechConfig)
        assert isinstance(config.chip, ChipAlertConfig)
        assert isinstance(config.api, ApiConfig)

    def test_log_path_default(self, config):
        assert config.log_path == "analysis_log.md"

    def test_log_keep_per_day_default(self, config):
        assert config.log_keep_per_day == 1

    def test_charts_dir_default(self, config):
        assert config.charts_dir == "charts"

    def test_charts_keep_default(self, config):
        assert config.charts_keep == 1


# ══════════════════════════════════════════════════════════════
# Global singleton
# ══════════════════════════════════════════════════════════════

class TestGlobalConfig:
    def test_global_config_is_analysis_config(self):
        """The global CONFIG is an AnalysisConfig instance."""
        assert isinstance(CONFIG, AnalysisConfig)

    def test_global_config_has_all_sub_configs(self):
        assert isinstance(CONFIG.weights, ScoreWeightsConfig)
        assert isinstance(CONFIG.cache, CacheConfig)


# ══════════════════════════════════════════════════════════════
# CacheConfig
# ══════════════════════════════════════════════════════════════

class TestCacheConfig:
    def test_ttl_twse_daily_is_zero(self):
        assert CacheConfig().ttl_twse_daily_hours == 0.0

    def test_ttl_institutional_is_zero(self):
        assert CacheConfig().ttl_institutional_hours == 0.0

    def test_ttl_monthly_revenue(self):
        assert CacheConfig().ttl_monthly_revenue_hours == 24.0

    def test_ttl_quarterly_margins(self):
        assert CacheConfig().ttl_quarterly_margins_hours == 168.0

    def test_ttl_macro_adr(self):
        assert CacheConfig().ttl_macro_adr_hours == 1.0

    def test_ttl_macro_capex(self):
        assert CacheConfig().ttl_macro_capex_hours == 168.0

    def test_keep_count_default(self):
        assert CacheConfig().keep_count == 3

    def test_directory_default(self):
        assert CacheConfig().directory == "local_cache"


# ══════════════════════════════════════════════════════════════
# ScoreWeightsConfig
# ══════════════════════════════════════════════════════════════

class TestScoreWeightsConfig:
    def test_financial_weight(self):
        assert ScoreWeightsConfig().financial == 0.30

    def test_bigtech_weight(self):
        assert ScoreWeightsConfig().bigtech == 0.30

    def test_tech_weight(self):
        assert ScoreWeightsConfig().tech == 0.20

    def test_chip_weight(self):
        assert ScoreWeightsConfig().chip == 0.10

    def test_market_sentiment_weight(self):
        """市場情緒已移出燈號計算（量能為落後指標），權重應為 0.0。"""
        assert ScoreWeightsConfig().market_sentiment == 0.0

    def test_main_weights_sum_to_point_90(self):
        """四面向加總 = 0.90（市場情緒 10% 已移出燈號計算）。

        刻意不重新歸一化為 1.0，以保留綜合得分門檻（紅 <50 / 黃 <70）
        的既有校準。"""
        w = ScoreWeightsConfig()
        total = w.financial + w.bigtech + w.tech + w.chip + w.market_sentiment
        assert total == pytest.approx(0.90)

    def test_early_weight(self):
        assert ScoreWeightsConfig().early == 0.07

    def test_short_weight(self):
        assert ScoreWeightsConfig().short == 0.07

    def test_mid_weight(self):
        assert ScoreWeightsConfig().mid == 0.10

    def test_long_weight(self):
        assert ScoreWeightsConfig().long == 0.11

    def test_tech_sub_weights_sum(self):
        """early + short + mid + long == 0.35 (internal tech ratio)."""
        w = ScoreWeightsConfig()
        total = w.early + w.short + w.mid + w.long
        assert total == pytest.approx(0.35)

    def test_as_dict_keys(self, weights):
        d = weights.as_dict()
        assert set(d.keys()) == {"financial", "bigtech", "tech", "chip", "market_sentiment"}

    def test_as_dict_values(self, weights):
        d = weights.as_dict()
        assert d["financial"] == 0.30
        assert d["bigtech"] == 0.30
        assert d["tech"] == 0.20
        assert d["chip"] == 0.10
        assert d["market_sentiment"] == 0.0


# ══════════════════════════════════════════════════════════════
# TechnicalPenaltyConfig
# ══════════════════════════════════════════════════════════════

class TestTechnicalPenaltyConfig:
    def test_volume_price_divergence_penalty(self):
        assert TechnicalPenaltyConfig().volume_price_divergence == 50

    def test_rsi_daily_divergence_penalty(self):
        assert TechnicalPenaltyConfig().rsi_daily_divergence == 20

    def test_rsi_weekly_divergence_penalty(self):
        assert TechnicalPenaltyConfig().rsi_weekly_divergence == 30

    def test_upper_shadow_kline_penalty(self):
        assert TechnicalPenaltyConfig().upper_shadow_kline == 10

    def test_engulf_black_kline_penalty(self):
        assert TechnicalPenaltyConfig().engulf_black_kline == 15

    def test_consecutive_small_body_penalty(self):
        assert TechnicalPenaltyConfig().consecutive_small_body == 10

    def test_ma20_cross_below_penalty(self):
        assert TechnicalPenaltyConfig().ma20_cross_below == 20

    def test_weekly_ma12_turn_down_penalty(self):
        assert TechnicalPenaltyConfig().weekly_ma12_turn_down == 15

    def test_weekly_rsi_break_60_penalty(self):
        assert TechnicalPenaltyConfig().weekly_rsi_break_60 == 10

    def test_weekly_macd_death_cross_penalty(self):
        assert TechnicalPenaltyConfig().weekly_macd_death_cross == 15

    def test_monthly_ma12_turn_down_penalty(self):
        assert TechnicalPenaltyConfig().monthly_ma12_turn_down == 30

    def test_monthly_break_ma12_penalty(self):
        assert TechnicalPenaltyConfig().monthly_break_ma12 == 40


# ══════════════════════════════════════════════════════════════
# BollingerConfig
# ══════════════════════════════════════════════════════════════

class TestBollingerConfig:
    def test_period(self):
        assert BollingerConfig().period == 20

    def test_std_mult(self):
        assert BollingerConfig().std_mult == 2.0

    def test_penalty_break_upper(self):
        assert BollingerConfig().penalty_break_upper == 15

    def test_penalty_break_lower(self):
        assert BollingerConfig().penalty_break_lower == 25

    def test_squeeze_ratio(self):
        assert BollingerConfig().squeeze_ratio == 0.60


# ══════════════════════════════════════════════════════════════
# DashboardAlertConfig
# ══════════════════════════════════════════════════════════════

class TestDashboardAlertConfig:
    def test_revenue_yoy_yellow(self):
        assert DashboardAlertConfig().revenue_yoy_yellow == 20.0

    def test_margin_qoq_drop_yellow(self):
        assert DashboardAlertConfig().margin_qoq_drop_yellow == 2.0

    def test_score_green_threshold(self):
        assert DashboardAlertConfig().score_green_threshold == 80.0

    def test_score_yellow_threshold(self):
        assert DashboardAlertConfig().score_yellow_threshold == 60.0


# ══════════════════════════════════════════════════════════════
# BigTechConfig
# ══════════════════════════════════════════════════════════════

class TestBigTechConfig:
    def test_capex_companies(self, bigtech_config):
        assert bigtech_config.capex_companies == ("MSFT", "META", "GOOGL", "AMZN")

    def test_nvda_ticker(self):
        assert BigTechConfig().nvda_ticker == "NVDA"

    def test_capex_ttl_hours(self):
        assert BigTechConfig().capex_ttl_hours == 168.0

    def test_nvda_revenue_ttl_hours(self):
        assert BigTechConfig().nvda_revenue_ttl_hours == 24.0


# ══════════════════════════════════════════════════════════════
# ChipAlertConfig
# ══════════════════════════════════════════════════════════════

class TestChipAlertConfig:
    def test_consecutive_days(self):
        assert ChipAlertConfig().consecutive_days == 5

    def test_big_sell_threshold_bn(self):
        assert ChipAlertConfig().big_sell_threshold_bn == 1.0

    def test_chip_penalty_big_sell(self):
        assert ChipAlertConfig().chip_penalty_big_sell == 20

    def test_resonance_buy_bonus(self):
        assert ChipAlertConfig().resonance_buy_bonus == 5


# ══════════════════════════════════════════════════════════════
# ApiConfig
# ══════════════════════════════════════════════════════════════

class TestApiConfig:
    def test_finmind_url(self):
        assert ApiConfig().finmind_url == "https://api.finmindtrade.com/api/v4/data"

    def test_twse_url(self):
        assert "twse.com.tw" in ApiConfig().twse_url

    def test_yahoo_url_template(self):
        assert "{ticker}" in ApiConfig().yahoo_url_template

    def test_request_timeout(self):
        assert ApiConfig().request_timeout == 30

    def test_twse_max_retries(self):
        assert ApiConfig().twse_max_retries == 3

    def test_twse_min_date(self):
        assert ApiConfig().twse_min_date == "1990-01-04"

    def test_max_workers(self):
        assert ApiConfig().max_workers == 4


# ══════════════════════════════════════════════════════════════
# Immutable / isolation tests
# ══════════════════════════════════════════════════════════════

class TestConfigIsolation:
    def test_fresh_instances_independent(self):
        """Modifying one AnalysisConfig instance should not affect another."""
        cfg1 = AnalysisConfig()
        cfg2 = AnalysisConfig()
        cfg1.weights.financial = 0.99
        assert cfg2.weights.financial == 0.30

    def test_fresh_weights_instances_independent(self):
        w1 = ScoreWeightsConfig()
        w2 = ScoreWeightsConfig()
        w1.financial = 0.50
        assert w2.financial == 0.30
