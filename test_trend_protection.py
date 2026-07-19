"""
趨勢保護信號 單元測試。

用合成台股日線 DataFrame 驗證各情境下的燈號與強制降級邏輯。
"""

import pandas as pd
import pytest

from trend_protection import evaluate_trend_protection, TrendProtectionSignal
from signal_engine import AlertLevelDetector, _level_rank


def _make_df(closes, vols=None, start="2026-01-01"):
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="D").strftime("%Y-%m-%d")
    data = {
        "日期": dates,
        "台積電收盤價": closes,
    }
    if vols is not None:
        data["台積電成交金額"] = vols
    return pd.DataFrame(data)


def test_insufficient_data_is_unavailable():
    df = _make_df([1000.0] * 30)  # 少於 MA60_WIN(60)
    sig = evaluate_trend_protection(df)
    assert sig.available is False
    assert sig.level == "green"


def test_flat_price_is_green():
    df = _make_df([1000.0] * 80)
    sig = evaluate_trend_protection(df)
    assert sig.level == "green"
    assert not sig.reasons


def test_break_below_ma60_is_red():
    # 前 79 根維持 1000，最後一根重挫至 800 → 收盤價跌破 MA60/MA20
    closes = [1000.0] * 79 + [800.0]
    df = _make_df(closes)
    sig = evaluate_trend_protection(df)
    assert sig.level == "red"
    assert any("60MA" in r for r in sig.reasons)


def test_dip_in_uptrend_is_yellow():
    # 強勢多頭後單日拉回，收盤價跌破 MA20 但仍在 MA60 之上
    closes = [900.0 + i * (200.0 / 59.0) for i in range(60)]  # 60 根：900→1100
    closes += [1100.0] * 9                                      # 61..69
    closes += [1050.0]                                          # 70：拉回
    assert len(closes) == 70
    df = _make_df(closes)
    sig = evaluate_trend_protection(df)
    # 1050 < MA20(~1097) 且 > MA60(~1016) → 黃燈（非紅燈）
    assert sig.level == "yellow"
    assert any("20MA" in r or "低點支撐" in r for r in sig.reasons)


def test_markdown_includes_sections():
    df = _make_df([1000.0] * 80)
    md = evaluate_trend_protection(df).to_markdown()
    assert "趨勢保護信號" in md
    assert "MA20" in md and "MA60" in md


# ── signal_engine 強制降級 (protect_override) ──────────────
def test_override_red_forces_red_when_green():
    det = AlertLevelDetector()
    level, label, emoji, msg = det.detect(
        comprehensive_score=95, financial_warnings=[], tech_flags={}, chip_flags={},
        protect_override="red",
    )
    assert level == "red"
    assert "趨勢保護" in msg


def test_override_yellow_forces_yellow_when_green():
    det = AlertLevelDetector()
    level, label, emoji, msg = det.detect(
        comprehensive_score=95, financial_warnings=[], tech_flags={}, chip_flags={},
        protect_override="yellow",
    )
    assert level == "yellow"
    assert "趨勢保護" in msg


def test_no_override_keeps_green():
    det = AlertLevelDetector()
    level, label, emoji, msg = det.detect(
        comprehensive_score=95, financial_warnings=[], tech_flags={}, chip_flags={},
    )
    assert level == "green"


def test_override_no_downgrade_when_already_red():
    det = AlertLevelDetector()
    # comp_score 低於紅燈門檻 → 本就紅燈，override 不應改變
    level, label, emoji, msg = det.detect(
        comprehensive_score=40, financial_warnings=["x"], tech_flags={}, chip_flags={},
        protect_override="yellow",
    )
    assert level == "red"


def test_level_rank_ordering():
    assert _level_rank("green") < _level_rank("yellow") < _level_rank("red")
