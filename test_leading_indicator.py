"""
Sentimental-Quant-Lab — Tests for the leading indicator (預測用領先指標)

領先指標觸發條件（三者同時成立）：
  1. 外資近 N 個交易日「連續賣超」（每日淨買賣股數皆 < 0）
  2. 近 N 日累計淨賣超佔外資持股 > 1%
  3. 本益比 (TTM) > 25 倍
觸發即視為強制紅燈領先訊號。
"""

import pandas as pd
import pytest

from signal_engine import (
    LeadingIndicator,
    compute_leading_indicator,
    compute_trailing_pe,
)

# 外資持股約 93 億股，作為強制紅燈分母
FOREIGN_SHARES = 9_300_000_000


def _chip(*pairs):
    """pairs: ((date, net_shares), ...) 外資每日淨買賣股數（負=賣超）。"""
    rows = []
    for d, net in pairs:
        buy = 0 if net < 0 else net
        sell = -net if net < 0 else 0
        rows.append({"date": d, "type": "Foreign_Investor", "buy": buy, "sell": sell})
    return rows


def test_triggered_when_two_day_sellout_exceeds_1pct_and_pe_high():
    # 2 日各賣超 6,000 萬股 → 累計 1.2 億股 = 1.29% > 1%，PE 28 > 25
    chip = _chip(("2026-07-17", -60_000_000), ("2026-07-16", -62_002_000))
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=28.0)
    assert r.available is True
    assert r.both_selling is True
    assert r.sell_pct > 1.0
    assert r.triggered is True
    assert r.forced_red is True


def test_not_triggered_when_one_day_is_buy():
    chip = _chip(("2026-07-17", 60_000_000), ("2026-07-16", -62_002_000))
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=28.0)
    assert r.both_selling is False
    assert r.triggered is False
    assert r.forced_red is False


def test_not_triggered_when_pe_below_threshold():
    chip = _chip(("2026-07-17", -60_000_000), ("2026-07-16", -62_002_000))
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=20.0)
    assert r.both_selling is True
    assert r.triggered is False


def test_not_triggered_when_sell_pct_below_1pct():
    # 2 日各賣超 100 萬股 → 累計 200 萬股 = 0.02% < 1%，即便 PE 很高也不觸發
    chip = _chip(("2026-07-17", -1_000_000), ("2026-07-16", -1_000_000))
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=40.0)
    assert r.both_selling is True
    assert r.sell_pct < 1.0
    assert r.triggered is False


def test_insufficient_data_returns_unavailable():
    r = compute_leading_indicator([], FOREIGN_SHARES, pe_ratio=28.0)
    assert r.available is False
    assert r.note
    assert r.triggered is False


def test_fallback_to_float_shares_when_foreign_none():
    # foreign_shares 未提供 → 分母回退總流通股（25.9B），1% 門檻更難達成。
    chip = _chip(("2026-07-17", -60_000_000), ("2026-07-16", -62_002_000))
    r = compute_leading_indicator(chip, None, pe_ratio=28.0)
    assert r.denom_label == "流通股"
    assert r.available is True
    # 回退分母（總流通股）較外資持股更大，1% 門檻更嚴 → 賣超佔比 < 1%、不觸發
    assert r.sell_pct is not None
    assert 0 < r.sell_pct < 1.0
    assert r.triggered is False


def test_triggered_with_float_shares_fallback_when_sell_large():
    # 回退分母下，2 日賣超超過總流通股 1%（>259M 股）仍會觸發。
    chip = _chip(("2026-07-17", -160_000_000), ("2026-07-16", -160_000_000))
    r = compute_leading_indicator(chip, None, pe_ratio=28.0)
    assert r.denom_label == "流通股"
    assert r.sell_pct > 1.0
    assert r.triggered is True


def test_compute_trailing_pe_basic():
    q = {
        (2026, 2): {"eps": 14.0},
        (2026, 1): {"eps": 13.5},
        (2025, 4): {"eps": 13.0},
        (2025, 3): {"eps": 12.5},
    }
    assert compute_trailing_pe(2470.0, q) == pytest.approx(2470.0 / 53.0, rel=1e-6)


def test_compute_trailing_pe_returns_zero_without_eps():
    assert compute_trailing_pe(0.0, {}) == 0.0
    assert compute_trailing_pe(100.0, {(2026, 1): {"eps": None}}) == 0.0
