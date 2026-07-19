"""
Sentimental-Quant-Lab — Tests for the leading indicator (預測用領先指標)

領先指標觸發條件（三者同時成立）：
  1. 外資近 N 個交易日「連續賣超」（每日淨買賣股數皆 < 0）
  2. 往前兩個月（two_month_window_days=60 自然日）累計淨賣超佔外資持股 > 1%
  3. 本益比 (TTM) > 30 倍
觸發即視為強制紅燈領先訊號。
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from signal_engine import (
    LeadingIndicator,
    compute_leading_indicator,
    compute_trailing_pe,
    compute_forward_pe,
)

# 外資持股約 93 億股，作為強制紅燈分母；1% = 9,300 萬股
FOREIGN_SHARES = 9_300_000_000


def _chip_days(end: str, nets):
    """
    由 end（YYYY-MM-DD）往前每日展開 nets（負=賣超）。

    nets[0] 對應最新一日（end），nets[1] 為 end 前 1 日，依此類推。
    每個 i 產生唯一日期，確保 groupby(date) 後一日一列。
    """
    end_d = date.fromisoformat(end)
    rows = []
    for i, net in enumerate(nets):
        d = (end_d - timedelta(days=i)).isoformat()
        buy = 0 if net < 0 else net
        sell = -net if net < 0 else 0
        rows.append({"date": d, "type": "Foreign_Investor", "buy": buy, "sell": sell})
    return rows


def test_triggered_when_two_month_sellout_exceeds_1pct_and_pe_high():
    # 往前兩個月（40 日）每日賣超 300 萬股 → 累計 1.2 億股 = 1.29% > 1%，PE 28 > 25
    chip = _chip_days("2026-07-17", [-3_000_000] * 40)
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=31.0)
    assert r.available is True
    assert r.both_selling is True
    assert r.sell_pct > 1.0
    assert r.triggered is True
    assert r.forced_red is True
    # 視窗應落在最新日往前約 60 自然日內
    assert r.window_sessions >= 40


def test_not_triggered_when_one_day_is_buy():
    # 最新一日為買超 → 不構成「近 2 日連續賣超」→ 不觸發
    nets = [-3_000_000] * 40
    nets[0] = 3_000_000  # 最新一日改為買超
    chip = _chip_days("2026-07-17", nets)
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=31.0)
    assert r.both_selling is False
    assert r.triggered is False
    assert r.forced_red is False


def test_not_triggered_when_pe_below_threshold():
    # 兩個月累計賣超達門檻，但 PE 20 < 25 → 不觸發
    chip = _chip_days("2026-07-17", [-3_000_000] * 40)
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=20.0)
    assert r.both_selling is True
    assert r.sell_pct > 1.0
    assert r.triggered is False


def test_not_triggered_when_sell_pct_below_1pct():
    # 兩個月每日僅賣超 100 萬股 → 累計 4,000 萬股 = 0.43% < 1%，即便 PE 很高也不觸發
    chip = _chip_days("2026-07-17", [-1_000_000] * 40)
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=40.0)
    assert r.both_selling is True
    assert r.sell_pct < 1.0
    assert r.triggered is False


def test_insufficient_data_returns_unavailable():
    r = compute_leading_indicator([], FOREIGN_SHARES, pe_ratio=31.0)
    assert r.available is False
    assert r.note
    assert r.triggered is False


def test_fallback_to_float_shares_when_foreign_none():
    # foreign_shares 未提供 → 分母回退總流通股（25.9B），1% 門檻更難達成。
    chip = _chip_days("2026-07-17", [-3_000_000] * 40)
    r = compute_leading_indicator(chip, None, pe_ratio=31.0)
    assert r.denom_label == "流通股"
    assert r.available is True
    # 回退分母（總流通股）較外資持股更大，1% 門檻更嚴 → 賣超佔比 < 1%、不觸發
    assert r.sell_pct is not None
    assert 0 < r.sell_pct < 1.0
    assert r.triggered is False


def test_triggered_with_float_shares_fallback_when_sell_large():
    # 回退分母下，兩個月賣超超過總流通股 1%（>259M 股）仍會觸發。
    chip = _chip_days("2026-07-17", [-8_000_000] * 40)
    r = compute_leading_indicator(chip, None, pe_ratio=31.0)
    assert r.denom_label == "流通股"
    assert r.sell_pct > 1.0
    assert r.triggered is True


def test_two_month_window_excludes_older_data():
    # 關鍵回歸：往前兩個月視窗以外的舊資料不應計入累計淨賣超。
    # 最近 61 日（視窗內）皆為微量買超 → 視窗淨額為正 → 累計賣超 = 0；
    # 更早 60 日（視窗外）每日鉅額賣超 1,000 萬股，若被誤納入會使佔比暴衝。
    recent = [1_000_000] * 61          # 視窗內：微量買超
    older = [-10_000_000] * 60         # 視窗外：鉅額賣超（應排除）
    chip = _chip_days("2026-07-17", recent + older)
    r = compute_leading_indicator(chip, FOREIGN_SHARES, pe_ratio=31.0)
    assert r.available is True
    # 視窗只包含最新 ~60 自然日（含 cutoff 邊界），舊資料被排除
    assert r.window_sessions <= 62
    # 若視窗邏輯失效，cumulative 會是數億股；此處應嚴格為 0
    assert r.cumulative_sell_shares == 0.0
    assert r.sell_pct == 0.0
    assert r.triggered is False


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


def test_compute_forward_pe_with_sufficient_data():
    """測試有 8 季數據時，基於增長率推估的 Forward PE"""
    q = {
        # 最新 4 季：每季 14 / 13.5 / 13 / 12.5 = 53
        (2026, 2): {"eps": 14.0},
        (2026, 1): {"eps": 13.5},
        (2025, 4): {"eps": 13.0},
        (2025, 3): {"eps": 12.5},
        # 更早 4 季：12 / 11.5 / 11 / 10.5 = 45（略低）
        (2025, 2): {"eps": 12.0},
        (2025, 1): {"eps": 11.5},
        (2024, 4): {"eps": 11.0},
        (2024, 3): {"eps": 10.5},
    }
    price = 2470.0
    forward_pe = compute_forward_pe(price, q)
    # 應該返回一個有效的正數
    assert forward_pe > 0
    assert forward_pe < 50  # Forward PE 通常在合理範圍


def test_compute_forward_pe_with_limited_data():
    """測試只有 2~4 季數據時，使用最新季度 EPS 乘以 4 的簡化方法"""
    q = {
        (2026, 2): {"eps": 14.0},
        (2026, 1): {"eps": 13.5},
        (2025, 4): {"eps": 13.0},
    }
    price = 2470.0
    forward_pe = compute_forward_pe(price, q)
    # 簡化計算：price / (14 * 4) = 2470 / 56
    assert forward_pe == pytest.approx(price / 56.0, rel=1e-6)


def test_compute_forward_pe_returns_zero_without_eps():
    """Forward PE 在沒有足夠數據時回傳 0"""
    assert compute_forward_pe(0.0, {}) == 0.0
    assert compute_forward_pe(100.0, {(2026, 1): {"eps": None}}) == 0.0
    assert compute_forward_pe(100.0, {(2026, 1): {"eps": 5.0}}) == 0.0  # 只有 1 季
