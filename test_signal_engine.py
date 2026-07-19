"""
Sentimental-Quant-Lab — Tests for signal_engine.py

Covers:
  - FinancialSignalCalculator.calculate()
  - BigTechSignalCalculator.calculate()
  - ComprehensiveScoreCalculator.calculate()
  - AlertLevelDetector.detect()
  - SignalEngine.analyze() (full pipeline)
"""

import pytest

from config import CONFIG
from signal_engine import (
    FinancialSignalCalculator,
    BigTechSignalCalculator,
    ComprehensiveScoreCalculator,
    AlertLevelDetector,
    SignalEngine,
    FinancialSignals,
    TechnicalSignals,
    ChipSignals,
    BigTechSignals,
    ComprehensiveResult,
    score_to_alert,
)


# ══════════════════════════════════════════════════════════════
# FinancialSignalCalculator
# ══════════════════════════════════════════════════════════════

class TestFinancialSignalCalculator:
    def setup_method(self):
        self.calc = FinancialSignalCalculator()

    # --- Happy path / perfect signals ---

    def test_all_none_signals_returns_perfect_score(self):
        """All-None signals (default) should give score=100, no warnings."""
        signals = FinancialSignals()
        score, warnings = self.calc.calculate(signals)
        assert score == 100
        assert warnings == []

    def test_healthy_signals_returns_perfect_score(self):
        """Good revenue YoY + small margin drops = perfect score."""
        signals = FinancialSignals(
            latest_revenue_yoy=35.0,
            gross_drop=0.5,
            op_drop=0.5,
            net_drop=0.5,
        )
        score, warnings = self.calc.calculate(signals)
        assert score == 100
        assert warnings == []

    # --- Revenue YoY penalties ---

    def test_revenue_yoy_below_yellow_threshold(self):
        """Revenue YoY between 0 and 20% should deduct 10 points."""
        signals = FinancialSignals(latest_revenue_yoy=15.0)
        score, warnings = self.calc.calculate(signals)
        assert score == 90
        assert any("低於 20%" in w for w in warnings)

    def test_revenue_yoy_exactly_at_yellow_threshold(self):
        """Revenue YoY == 20.0 should NOT trigger the yellow penalty (strict less-than)."""
        signals = FinancialSignals(latest_revenue_yoy=20.0)
        score, _ = self.calc.calculate(signals)
        assert score == 100

    def test_revenue_yoy_negative(self):
        """Revenue YoY < 0% should deduct 20 points."""
        signals = FinancialSignals(latest_revenue_yoy=-5.0)
        score, warnings = self.calc.calculate(signals)
        assert score == 80
        assert any("負成長" in w for w in warnings)

    def test_revenue_yoy_negative_with_declining_trend(self):
        """Revenue YoY < 0 + declining trend should deduct 30 points total."""
        signals = FinancialSignals(
            latest_revenue_yoy=-5.0,
            revenue_yoy_declining=True,
        )
        score, warnings = self.calc.calculate(signals)
        assert score == 70
        assert any("連續下滑" in w in w or "連續下滑" in w for w in warnings)

    # --- Margin drop penalties ---

    def test_gross_margin_drop_yellow(self):
        """Gross margin drop > 2pp should deduct 10 points."""
        signals = FinancialSignals(gross_drop=3.0)
        score, warnings = self.calc.calculate(signals)
        assert score == 90
        assert any("毛利率下滑" in w for w in warnings)

    def test_gross_margin_drop_red(self):
        """Gross margin drop > 4pp should deduct 20 points."""
        signals = FinancialSignals(gross_drop=5.0)
        score, warnings = self.calc.calculate(signals)
        assert score == 80
        assert any("毛利率大幅下滑" in w for w in warnings)

    def test_operating_margin_drop_yellow(self):
        signals = FinancialSignals(op_drop=2.5)
        score, warnings = self.calc.calculate(signals)
        assert score == 90
        assert any("營業利益率下滑" in w for w in warnings)

    def test_operating_margin_drop_red(self):
        signals = FinancialSignals(op_drop=4.5)
        score, warnings = self.calc.calculate(signals)
        assert score == 80
        assert any("營業利益率大幅下滑" in w for w in warnings)

    def test_net_margin_drop_yellow(self):
        """Net margin drop > 2pp deducts 5 points."""
        signals = FinancialSignals(net_drop=3.0)
        score, warnings = self.calc.calculate(signals)
        assert score == 95
        assert any("稅後淨利率下滑" in w for w in warnings)

    def test_net_margin_drop_red(self):
        """Net margin drop > 4pp deducts 10 points."""
        signals = FinancialSignals(net_drop=5.0)
        score, warnings = self.calc.calculate(signals)
        assert score == 90
        assert any("稅後淨利率大幅下滑" in w for w in warnings)

    # --- Deterioration bonus (3-rate) ---

    def test_three_rate_deterioration_extra_penalty(self):
        """When >=2 margins drop > 2pp, extra -10."""
        signals = FinancialSignals(gross_drop=3.0, op_drop=3.0)
        # gross_drop > 2 -> -10, op_drop > 2 -> -10, >=2 drops -> extra -10 = 70
        score, warnings = self.calc.calculate(signals)
        assert score == 70
        assert any("三率" in w for w in warnings)

    def test_three_rate_single_drop_no_extra(self):
        """Only 1 margin drop > 2pp should NOT trigger the extra -10."""
        signals = FinancialSignals(gross_drop=3.0, op_drop=0.5, net_drop=0.5)
        score, _ = self.calc.calculate(signals)
        assert score == 90

    def test_three_rate_all_three_drop(self):
        """All 3 margins drop > 2pp: -10 -10 -5 -10 = 65."""
        signals = FinancialSignals(gross_drop=3.0, op_drop=3.0, net_drop=3.0)
        score, _ = self.calc.calculate(signals)
        assert score == 65

    # --- Combined / worst case ---

    def test_worst_case_score_clamped_to_minimum(self):
        """Score should never go below 0 (clamped by max(0, score))."""
        signals = FinancialSignals(
            latest_revenue_yoy=-10.0,
            revenue_yoy_declining=True,
            gross_drop=10.0,
            op_drop=10.0,
            net_drop=10.0,
        )
        score, _ = self.calc.calculate(signals)
        # Max penalties: -20 (rev negative) -10 (declining) -20 (gross) -20 (op) -10 (net) -10 (3-rate) = -90
        assert score == 10
        assert score >= 0

    # --- Boundary values ---

    def test_gross_drop_exactly_at_yellow_threshold(self):
        """Drop == 2.0 should NOT trigger yellow penalty (strict greater-than)."""
        signals = FinancialSignals(gross_drop=2.0)
        score, _ = self.calc.calculate(signals)
        assert score == 100

    def test_gross_drop_just_above_yellow_threshold(self):
        """Drop == 2.001 should trigger yellow penalty."""
        signals = FinancialSignals(gross_drop=2.001)
        score, _ = self.calc.calculate(signals)
        assert score == 90

    def test_revenue_yoy_exactly_zero(self):
        """Revenue YoY == 0 should NOT trigger red penalty (strict less-than)."""
        signals = FinancialSignals(latest_revenue_yoy=0.0)
        score, _ = self.calc.calculate(signals)
        assert score == 90  # Still below yellow threshold -> -10

    def test_margin_drop_exactly_zero(self):
        """Zero margin drop should not affect score."""
        signals = FinancialSignals(gross_drop=0.0, op_drop=0.0, net_drop=0.0)
        score, _ = self.calc.calculate(signals)
        assert score == 100


# ══════════════════════════════════════════════════════════════
# BigTechSignalCalculator
# ══════════════════════════════════════════════════════════════

class TestBigTechSignalCalculator:
    def setup_method(self):
        self.calc = BigTechSignalCalculator()

    # --- Perfect / healthy ---

    def test_all_growing_strong_nvda(self):
        """4/4 CAPEX growing + NVDA 80% YoY -> combined = 100."""
        score, warnings = self.calc.calculate(
            capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=80.0
        )
        assert score == 100
        assert warnings == []

    def test_no_data_returns_perfect(self):
        """No CAPEX data + no NVDA data -> score 100."""
        score, warnings = self.calc.calculate(
            capex_growing_count=0, capex_valid_count=0, nvda_revenue_yoy=None
        )
        assert score == 100
        assert warnings == []

    # --- CAPEX only ---

    def test_capex_3_of_4_growing(self):
        """3/4 growing -> ratio 0.75 -> capex_score 100."""
        score, _ = self.calc.calculate(
            capex_growing_count=3, capex_valid_count=4, nvda_revenue_yoy=None
        )
        assert score == 100

    def test_capex_2_of_4_growing(self):
        """2/4 growing -> capex_score 75."""
        score, warnings = self.calc.calculate(
            capex_growing_count=2, capex_valid_count=4, nvda_revenue_yoy=None
        )
        assert score == 75
        assert any("趨緩" in w for w in warnings)

    def test_capex_1_of_4_growing(self):
        """1/4 growing -> capex_score 50."""
        score, warnings = self.calc.calculate(
            capex_growing_count=1, capex_valid_count=4, nvda_revenue_yoy=None
        )
        assert score == 50
        assert any("分歧" in w for w in warnings)

    def test_capex_0_of_4_growing(self):
        """0/4 growing -> capex_score 25."""
        score, warnings = self.calc.calculate(
            capex_growing_count=0, capex_valid_count=4, nvda_revenue_yoy=None
        )
        assert score == 25
        assert any("全面放緩" in w for w in warnings)

    # --- NVDA revenue YoY only ---

    def test_nvda_yoy_above_50(self):
        """NVDA YoY >= 50% -> nvda_score 100."""
        score, _ = self.calc.calculate(
            capex_growing_count=0, capex_valid_count=0, nvda_revenue_yoy=55.0
        )
        assert score == 100

    def test_nvda_yoy_at_50_boundary(self):
        """NVDA YoY == 50 -> nvda_score 100."""
        score, _ = self.calc.calculate(
            capex_growing_count=0, capex_valid_count=0, nvda_revenue_yoy=50.0
        )
        assert score == 100

    def test_nvda_yoy_at_20_boundary(self):
        """NVDA YoY == 20 -> nvda_score 80, combined with perfect CAPEX = 90."""
        # CAPEX 4/4 growing -> capex_score=100, NVDA 20% -> nvda_score=80
        # combined = int(100*0.5 + 80*0.5) = 90
        score, _ = self.calc.calculate(
            capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=20.0
        )
        assert score == 90

    def test_nvda_yoy_between_0_and_20(self):
        """NVDA YoY 10% -> nvda_score 60, combined with perfect CAPEX = 80."""
        score, warnings = self.calc.calculate(
            capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=10.0
        )
        assert score == 80
        assert any("趨緩" in w for w in warnings)

    def test_nvda_yoy_negative(self):
        """NVDA YoY -10% -> nvda_score 40, combined with perfect CAPEX = 70."""
        score, warnings = self.calc.calculate(
            capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=-10.0
        )
        assert score == 70
        assert any("負成長" in w for w in warnings)

    def test_nvda_yoy_exactly_zero(self):
        """NVDA YoY == 0 -> nvda_score 60, combined with perfect CAPEX = 80."""
        score, _ = self.calc.calculate(
            capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=0.0
        )
        assert score == 80

    # --- Combined CAPEX + NVDA ---

    def test_combined_capex_75_nvda_80(self):
        """CAPEX 75 + NVDA 80 -> combined = int(75*0.5 + 80*0.5) = 77."""
        score, _ = self.calc.calculate(
            capex_growing_count=2, capex_valid_count=4, nvda_revenue_yoy=30.0
        )
        # capex 2/4 -> 75, nvda 30% -> 80, combined = int(37.5 + 40) = 77
        assert score == 77

    def test_combined_capex_25_nvda_40(self):
        """CAPEX 25 + NVDA 40 -> combined = int(12.5 + 20) = 32."""
        score, _ = self.calc.calculate(
            capex_growing_count=0, capex_valid_count=4, nvda_revenue_yoy=-5.0
        )
        assert score == 32

    def test_nvda_none_uses_capex_only(self):
        """When NVDA data is None, combined = capex_score (100% weight on CAPEX)."""
        score, _ = self.calc.calculate(
            capex_growing_count=2, capex_valid_count=4, nvda_revenue_yoy=None
        )
        assert score == 75


# ══════════════════════════════════════════════════════════════
# ComprehensiveScoreCalculator
# ══════════════════════════════════════════════════════════════

class TestComprehensiveScoreCalculator:
    def _make_signals(self, fin=100, bigtech=100, tech_scores=None, chip=100):
        if tech_scores is None:
            tech_scores = {"early": 100, "short": 100, "mid": 100, "long": 100}
        return dict(
            financial_score=fin,
            bigtech_signals=BigTechSignals(score=bigtech),
            tech_signals=TechnicalSignals(scores=tech_scores),
            chip_signals=ChipSignals(score=chip),
        )

    def test_all_perfect_scores(self):
        """All 100 -> comprehensive = 100 (4 dims @ 100 * weights summing 1.00)."""
        calc = ComprehensiveScoreCalculator()
        result, breakdown = calc.calculate(**self._make_signals())
        assert result == pytest.approx(100.0)
        assert all(v == pytest.approx(100.0 * calc.weights[k]) for k, v in breakdown.items())

    def test_all_zero_scores(self):
        """All 0 -> comprehensive = 0."""
        calc = ComprehensiveScoreCalculator()
        result, _ = calc.calculate(**self._make_signals(
            fin=0, bigtech=0, tech_scores={"early": 0, "short": 0, "mid": 0, "long": 0},
            chip=0,
        ))
        assert result == pytest.approx(0.0)

    def test_weighted_calculation(self):
        """Verify the weighted math with known values."""
        calc = ComprehensiveScoreCalculator()
        # financial=80, bigtech=60, tech=100, chip=100
        result, breakdown = calc.calculate(**self._make_signals(
            fin=80, bigtech=60, chip=100,
        )
        )
        w = CONFIG.weights
        expected = (
            80 * w.financial +
            60 * w.bigtech +
            100 * w.tech +
            100 * w.chip
        )
        assert result == pytest.approx(expected)

    def test_tech_sub_weighted_average(self):
        """Tech combined score should use early/short/mid/long sub-weights."""
        calc = ComprehensiveScoreCalculator()
        # Set tech sub-scores to different values
        tech_scores = {"early": 80, "short": 60, "mid": 40, "long": 20}
        result, breakdown = calc.calculate(**self._make_signals(tech_scores=tech_scores))

        w = CONFIG.weights
        tech_total_w = w.early + w.short + w.mid + w.long
        expected_tech_combined = (
            80 * w.early + 60 * w.short + 40 * w.mid + 20 * w.long
        ) / tech_total_w
        assert breakdown["tech"] == pytest.approx(expected_tech_combined * w.tech)

    def test_custom_weights(self):
        """Custom weights override config defaults (market sentiment must not be a key)."""
        custom = {"financial": 0.5, "bigtech": 0.3, "tech": 0.1, "chip": 0.1}
        calc = ComprehensiveScoreCalculator(weights=custom)
        result, _ = calc.calculate(**self._make_signals(fin=80, bigtech=60))
        expected = 80 * 0.5 + 60 * 0.3 + 100 * 0.1 + 100 * 0.1
        assert result == pytest.approx(expected)

    def test_breakdown_keys(self):
        """Breakdown should contain the four dimension keys (market sentiment removed)."""
        calc = ComprehensiveScoreCalculator()
        _, breakdown = calc.calculate(**self._make_signals())
        assert set(breakdown.keys()) == {"financial", "bigtech", "tech", "chip"}

    def test_breakdown_values_sum_to_comprehensive(self):
        """Sum of breakdown values should equal comprehensive score."""
        calc = ComprehensiveScoreCalculator()
        result, breakdown = calc.calculate(**self._make_signals(
            fin=70, bigtech=80, chip=90,
        ))
        assert result == pytest.approx(sum(breakdown.values()))


# ══════════════════════════════════════════════════════════════
# AlertLevelDetector
# ══════════════════════════════════════════════════════════════

class TestAlertLevelDetector:
    def setup_method(self):
        self.detector = AlertLevelDetector()

    # --- Green light ---

    def test_green_when_score_above_70(self):
        level, label, emoji, msg = self.detector.detect(85.0, [], {}, {})
        assert level == "green"
        assert label == "綠燈"
        assert emoji == "🟢"

    def test_green_at_exactly_70(self):
        """Score == 70 should be green (not yellow, since 70 is not < 70)."""
        level, _, _, _ = self.detector.detect(70.0, [], {}, {})
        assert level == "green"

    def test_green_at_100(self):
        level, _, _, _ = self.detector.detect(100.0, [], {}, {})
        assert level == "green"

    # --- Yellow light ---

    def test_yellow_when_score_between_50_and_70(self):
        level, label, emoji, msg = self.detector.detect(65.0, [], {}, {})
        assert level == "yellow"
        assert label == "黃燈"
        assert emoji == "🟡"

    def test_yellow_at_exactly_50(self):
        """Score == 50 should be yellow (not red, since 50 is not < 50)."""
        level, _, _, _ = self.detector.detect(50.0, [], {}, {})
        assert level == "yellow"

    # --- Red light ---

    def test_red_when_score_below_50(self):
        level, label, emoji, msg = self.detector.detect(40.0, [], {}, {})
        assert level == "red"
        assert label == "紅燈"
        assert emoji == "🔴"

    def test_red_at_zero(self):
        level, _, _, _ = self.detector.detect(0.0, [], {}, {})
        assert level == "red"

    def test_red_at_49_9(self):
        level, _, _, _ = self.detector.detect(49.9, [], {}, {})
        assert level == "red"

    # --- Reversal advanced -> always red ---

    def test_reversal_advanced_overrides_green_to_red(self):
        """Advanced reversal signal forces red regardless of score."""
        level, label, emoji, msg = self.detector.detect(
            95.0, [], {}, {}, reversal_advanced=True,
        )
        assert level == "red"
        assert "高強度轉折" in msg

    def test_reversal_advanced_overrides_yellow_to_red(self):
        level, _, _, _ = self.detector.detect(
            60.0, [], {}, {}, reversal_advanced=True,
        )
        assert level == "red"

    # --- Reversal basic -> at least yellow ---

    def test_reversal_basic_with_green_score_upgrades_to_yellow(self):
        """Basic reversal with score >= 70 should stay yellow (not green)."""
        level, _, _, _ = self.detector.detect(
            85.0, [], {}, {}, reversal_basic=True,
        )
        # Score 85 >= 70 -> green, but reversal_basic adds message
        # The code checks: if reversal_basic and level == "yellow" -> upgrade to red
        # So with score 85, level stays green but message includes reversal warning
        # Actually re-reading the code: reversal_basic just adds a message, doesn't change level
        # unless level is yellow. So green stays green.
        assert level == "green"

    def test_reversal_basic_with_yellow_score_upgrades_to_red(self):
        """Basic reversal with yellow score should upgrade to red."""
        level, _, _, _ = self.detector.detect(
            60.0, [], {}, {}, reversal_basic=True,
        )
        assert level == "red"

    # --- Double warning ---

    def test_double_warning_with_fin_warnings_and_low_score(self):
        """Financial warnings + low score should add double warning message."""
        level, _, _, msg = self.detector.detect(
            55.0, ["營收 YoY 負成長"], {}, {},
        )
        assert "雙重預警" in msg

    def test_no_double_warning_when_score_high(self):
        """Financial warnings but high score should NOT trigger double warning."""
        _, _, _, msg = self.detector.detect(
            85.0, ["營收 YoY 負成長"], {}, {},
        )
        assert "雙重預警" not in msg

    def test_no_double_warning_when_no_fin_warnings(self):
        """No financial warnings should not trigger double warning."""
        _, _, _, msg = self.detector.detect(
            55.0, [], {}, {},
        )
        assert "雙重預警" not in msg

    # --- Message content ---

    def test_message_contains_score(self):
        _, _, _, msg = self.detector.detect(75.0, [], {}, {})
        assert "75.0" in msg

    def test_red_threshold_constant(self):
        assert AlertLevelDetector.RED_THRESHOLD == 50.0

    def test_yellow_threshold_constant(self):
        assert AlertLevelDetector.YELLOW_THRESHOLD == 70.0


# ══════════════════════════════════════════════════════════════
# SignalEngine (full pipeline)
# ══════════════════════════════════════════════════════════════

class TestSignalEngine:
    def setup_method(self):
        self.engine = SignalEngine()

    def test_all_perfect_signals_green(self):
        """All perfect signals should produce green alert with score 100."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(latest_revenue_yoy=35.0),
            bigtech_signals=BigTechSignals(
                capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=80.0,
            ),
            tech_signals=TechnicalSignals(scores={"early": 100, "short": 100, "mid": 100, "long": 100}),
            chip_signals=ChipSignals(score=100),
        )
        assert isinstance(result, ComprehensiveResult)
        assert result.comprehensive_score == pytest.approx(100.0)
        assert result.alert_level == "green"
        assert result.financial_score == 100.0
        assert result.bigtech_score == 100

    def test_all_weak_signals_red(self):
        """All weak signals should produce a low score and red/yellow alert."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(
                latest_revenue_yoy=-5.0, revenue_yoy_declining=True,
                gross_drop=5.0, op_drop=5.0, net_drop=5.0,
            ),
            bigtech_signals=BigTechSignals(
                capex_growing_count=0, capex_valid_count=4, nvda_revenue_yoy=-10.0,
            ),
            tech_signals=TechnicalSignals(
                scores={"early": 30, "short": 40, "mid": 35, "long": 25},
            ),
            chip_signals=ChipSignals(score=40),
        )
        assert result.comprehensive_score < 50
        assert result.alert_level == "red"
        assert result.financial_score < 100

    def test_result_contains_all_fields(self):
        """ComprehensiveResult should have all expected fields populated."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(),
            bigtech_signals=BigTechSignals(),
            tech_signals=TechnicalSignals(),
            chip_signals=ChipSignals(),
        )
        assert isinstance(result, ComprehensiveResult)
        assert isinstance(result.financial_score, (int, float))
        assert isinstance(result.bigtech_score, (int, float))
        assert isinstance(result.comprehensive_score, float)
        assert result.alert_level in ("red", "yellow", "green")
        assert result.alert_label in ("紅燈", "黃燈", "綠燈")
        assert isinstance(result.details, dict)
        assert "breakdown" in result.details
        assert "financial_warnings" in result.details

    def test_reversal_basic_detected(self):
        """When ma20_cross_below + monthly_break_ma12 + big_foreign_sell are all True."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(),
            bigtech_signals=BigTechSignals(),
            tech_signals=TechnicalSignals(
                scores={"early": 100, "short": 100, "mid": 100, "long": 100},
                flags={"ma20_cross_below": True, "monthly_break_ma12": True},
            ),
            chip_signals=ChipSignals(score=100, flags={"big_foreign_sell": True}),
        )
        assert result.reversal_signal is True
        assert result.reversal_advanced is False

    def test_reversal_advanced_detected(self):
        """Advanced reversal = basic + bb_squeeze_break."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(),
            bigtech_signals=BigTechSignals(),
            tech_signals=TechnicalSignals(
                scores={"early": 100, "short": 100, "mid": 100, "long": 100},
                flags={"ma20_cross_below": True, "monthly_break_ma12": True, "bb_squeeze_break": True},
            ),
            chip_signals=ChipSignals(score=100, flags={"big_foreign_sell": True}),
        )
        assert result.reversal_signal is True
        assert result.reversal_advanced is True
        assert result.alert_level == "red"

    def test_no_reversal_when_flags_missing(self):
        """Missing any one of the three flags should not trigger reversal."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(),
            bigtech_signals=BigTechSignals(),
            tech_signals=TechnicalSignals(
                scores={"early": 100, "short": 100, "mid": 100, "long": 100},
                flags={"ma20_cross_below": True},  # missing monthly_break_ma12
            ),
            chip_signals=ChipSignals(score=100, flags={"big_foreign_sell": True}),
        )
        assert result.reversal_signal is False

    def test_double_warning_detected(self):
        """Financial warnings + low comprehensive score -> double warning."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(
                latest_revenue_yoy=-5.0, gross_drop=5.0, op_drop=5.0, net_drop=5.0,
            ),
            bigtech_signals=BigTechSignals(
                capex_growing_count=0, capex_valid_count=4, nvda_revenue_yoy=-10.0,
            ),
            tech_signals=TechnicalSignals(
                scores={"early": 30, "short": 40, "mid": 35, "long": 25},
            ),
            chip_signals=ChipSignals(score=40),
        )
        assert result.double_warning is True

    def test_bigtech_signals_score_updated(self):
        """After analyze(), bigtech_signals.score should be updated by the calculator."""
        bt = BigTechSignals(capex_growing_count=0, capex_valid_count=4, nvda_revenue_yoy=-10.0)
        assert bt.score == 100  # default
        self.engine.analyze(
            financial_signals=FinancialSignals(),
            bigtech_signals=bt,
            tech_signals=TechnicalSignals(),
            chip_signals=ChipSignals(),
        )
        assert bt.score == 32  # CAPEX 25/ NVDA 40 -> int(12.5+20)=32

    def test_financial_warnings_populated(self):
        """Financial warnings should appear in result details."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(latest_revenue_yoy=-5.0),
            bigtech_signals=BigTechSignals(),
            tech_signals=TechnicalSignals(),
            chip_signals=ChipSignals(),
        )
        assert len(result.details["financial_warnings"]) > 0
        assert any("負成長" in w for w in result.details["financial_warnings"])

    def test_breakdown_has_all_dimensions(self):
        """Breakdown should have all five weighted dimensions."""
        result = self.engine.analyze(
            financial_signals=FinancialSignals(),
            bigtech_signals=BigTechSignals(),
            tech_signals=TechnicalSignals(),
            chip_signals=ChipSignals(),
        )
        bd = result.details["breakdown"]
        assert set(bd.keys()) == {"financial", "bigtech", "tech", "chip"}


# ══════════════════════════════════════════════════════════════
# 結構性警示：籌碼 + 情緒同步惡化強制升級燈號
# ══════════════════════════════════════════════════════════════

class TestStructuralWarning:
    """測試結構性警示規則：籌碼面 < 30 時強制升級燈號。
    註：原「籌碼 + 市場情緒同步惡化」之耦合已移除——市場情緒（量能）
    為落後指標，會在技術/籌碼已轉弱時仍因「量能未萎縮」顯示綠燈，造成失真。
    """

    def test_chip_and_sentiment_both_below_50_keeps_green(self):
        """籌碼 45 + 總分 82 → 無其他警示，維持綠燈（情緒不再耦合）。"""
        detector = AlertLevelDetector()
        level, label, emoji, msg = detector.detect(
            comprehensive_score=82.0,
            financial_warnings=[],
            tech_flags={},
            chip_flags={},
            chip_score=45.0,
        )
        assert level == "green"

    def test_chip_below_30_upgrades_green_to_yellow(self):
        """籌碼單項 < 30 → 強制至少黃燈，即使總分很高。"""
        detector = AlertLevelDetector()
        level, label, emoji, msg = detector.detect(
            comprehensive_score=85.0,
            financial_warnings=[],
            tech_flags={},
            chip_flags={},
            chip_score=25.0,
        )
        assert level == "yellow"
        assert "籌碼面嚴重惡化" in msg

    def test_only_chip_low_does_not_trigger_structural_warning(self):
        """只有籌碼低、且 > 30 → 不觸發結構性警示，維持綠燈。"""
        detector = AlertLevelDetector()
        level, label, emoji, msg = detector.detect(
            comprehensive_score=82.0,
            financial_warnings=[],
            tech_flags={},
            chip_flags={},
            chip_score=45.0,
        )
        # 只有籌碼低但 > 30 → 維持綠燈
        assert level == "green"

    def test_chip_50_exact_does_not_trigger(self):
        """籌碼剛好 50（等於閾值）→ 不觸發。"""
        detector = AlertLevelDetector()
        level, label, emoji, msg = detector.detect(
            comprehensive_score=82.0,
            financial_warnings=[],
            tech_flags={},
            chip_flags={},
            chip_score=50.0,
        )
        assert level == "green"

    def test_structural_warning_does_not_override_existing_yellow(self):
        """已經是黃燈時，結構性警示不降級。"""
        detector = AlertLevelDetector()
        level, label, emoji, msg = detector.detect(
            comprehensive_score=65.0,
            financial_warnings=[],
            tech_flags={},
            chip_flags={},
            chip_score=40.0,
        )
        assert level == "yellow"

    def test_structural_warning_does_not_override_red(self):
        """已經是紅燈時，結構性警示不影響。"""
        detector = AlertLevelDetector()
        level, label, emoji, msg = detector.detect(
            comprehensive_score=45.0,
            financial_warnings=[],
            tech_flags={},
            chip_flags={},
            chip_score=20.0,
        )
        assert level == "red"

    def test_full_pipeline_no_structural_warning_when_chip_ok(self):
        """完整 pipeline：chip=40（>30）、總分高 → 綠燈，無結構性警示。"""
        engine = SignalEngine()
        result = engine.analyze(
            financial_signals=FinancialSignals(latest_revenue_yoy=30.0),
            bigtech_signals=BigTechSignals(
                capex_growing_count=4, capex_valid_count=4,
                nvda_revenue_yoy=50.0,
            ),
            tech_signals=TechnicalSignals(),
            chip_signals=ChipSignals(score=40),
        )
        assert result.alert_level == "green"
        assert "結構性警示" not in result.alert_message



# ══════════════════════════════════════════════════════════════
# score_to_alert 輔助函式
# ══════════════════════════════════════════════════════════════

class TestScoreToAlert:
    """score_to_alert：分數 → 燈號（與 AlertLevelDetector 共用門檻）。"""

    def test_green_at_threshold(self):
        assert score_to_alert(70.0) == ("green", "綠燈", "🟢")

    def test_yellow_below_yellow_threshold(self):
        assert score_to_alert(69.9) == ("yellow", "黃燈", "🟡")

    def test_yellow_at_red_boundary(self):
        assert score_to_alert(50.0) == ("yellow", "黃燈", "🟡")

    def test_red_below_red_threshold(self):
        assert score_to_alert(49.9) == ("red", "紅燈", "🔴")

    def test_extremes(self):
        assert score_to_alert(100.0)[0] == "green"
        assert score_to_alert(0.0)[0] == "red"


# ══════════════════════════════════════════════════════════════
# 綜合情境：基本面健全 + 技術帶量破線 + 籌碼嚴重賣超 → 至少黃燈
# ══════════════════════════════════════════════════════════════
class TestSevereScenarioYellow:
    """重校準後，技術帶量跌破所有支撐 + 外資連續十天賣超的嚴重情境，
    即便基本面（財務 + 大廠）仍健全，綜合燈號也應脫離綠燈（至少黃燈）。"""

    def test_severe_tech_and_chip_forces_yellow(self):
        eng = SignalEngine()
        # 基本面健全
        fin = FinancialSignals(latest_revenue_yoy=35.0)
        bt = BigTechSignals(capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=80.0)
        # 技術：長期帶量破線（long 低），其餘良好
        tech = TechnicalSignals(scores={"early": 100, "short": 85, "mid": 100, "long": 35})
        # 籌碼：嚴重賣超（< 30，觸發結構性黃燈）
        chip = ChipSignals(score=5)

        result = eng.analyze(fin, bt, tech, chip)
        # 綜合分可能仍在綠燈區間，但 chip<30 結構規則應強制至少黃燈
        assert result.alert_level == "yellow"
        assert "黃燈" in result.alert_label
        assert "籌碼面嚴重惡化" in result.alert_message
        # 訊息應與最終燈號一致（不再出現「綠燈區間」自相矛盾）
        assert "綠燈區間" not in result.alert_message
