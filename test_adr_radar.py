"""
ADR / 美股隔夜風險雷達 單元測試。

透過注入假 provider（實作 get_chart(symbol)）驗證各情境下的燈號與文案，
不觸發真實網路請求。
"""

import pytest

from adr_radar import (
    OvernightRiskReport,
    SymbolMove,
    is_tw_pre_open,
    scan_overnight_risk,
)


def _chart(price: float, prev: float) -> dict:
    return {
        "chart": {
            "result": [{"meta": {"regularMarketPrice": price, "previousClose": prev}}],
            "error": None,
        }
    }


class FakeProvider:
    """依 symbol 回傳預設漲跌的假 Yahoo provider。"""

    def __init__(self, prices: dict, missing: set = None):
        # prices: {symbol: (price, prev_close)}
        self._prices = prices
        self._missing = missing or set()
        self.calls = []

    def get_chart(self, symbol: str, *args, **kwargs):
        self.calls.append(symbol)
        if symbol in self._missing:
            # 模擬抓取失敗：result 為空
            return {"chart": {"result": [], "error": None}}
        if symbol == "TWD=X":
            # USD/TWD: 預設台幣小幅貶值
            return _chart(31.50, 31.20)
        price, prev = self._prices.get(symbol, (100.0, 100.0))
        return _chart(price, prev)


# ── 燈號判定 ──────────────────────────────────────────────
def test_all_flat_is_green():
    p = FakeProvider({"TSM": (250.0, 250.0), "NVDA": (130.0, 130.0), "SMH": (250.0, 250.0)})
    rep = scan_overnight_risk(p)
    assert rep.level == "green"
    assert rep.emoji == "🟢"
    assert "無明顯風險" in rep.headline


def test_tsm_down_2_5pct_is_yellow():
    p = FakeProvider({"TSM": (243.75, 250.0), "NVDA": (130.0, 130.0), "SMH": (250.0, 250.0)})
    rep = scan_overnight_risk(p)
    assert rep.level == "yellow"
    tsm = rep.tsm_move
    assert tsm is not None and tsm.change_pct == pytest.approx(-2.5)


def test_tsm_down_5pct_is_red():
    p = FakeProvider({"TSM": (237.5, 250.0), "NVDA": (130.0, 130.0), "SMH": (250.0, 250.0)})
    rep = scan_overnight_risk(p)
    assert rep.level == "red"


def test_sector_weak_upgrades_yellow_to_red():
    # TSM 僅 -2.5%（黃燈），但 NVDA 與 SMH 同步重挫 → 升級紅燈
    p = FakeProvider({"TSM": (243.75, 250.0), "NVDA": (127.4, 130.0), "SMH": (244.25, 250.0)})
    rep = scan_overnight_risk(p)
    assert rep.level == "red"
    assert "系统性" in rep.headline


def test_sector_only_weak_gives_yellow():
    # TSM 平盤，但 SMH 單獨重挫 -3.5% → 黃燈（類股風險外溢）
    p = FakeProvider({"TSM": (250.0, 250.0), "NVDA": (130.0, 130.0), "SMH": (241.25, 250.0)})
    rep = scan_overnight_risk(p)
    assert rep.level == "yellow"


def test_tsm_unavailable_treats_as_no_driver():
    # TSM 抓取失敗 → 視為無主驅動數據，不應誤判紅燈
    p = FakeProvider({"NVDA": (130.0, 130.0), "SMH": (250.0, 250.0)}, missing={"TSM"})
    rep = scan_overnight_risk(p)
    assert rep.level == "green"
    assert rep.tsm_move is None or not rep.tsm_move.available


def test_fx_move_captured():
    p = FakeProvider({"TSM": (250.0, 250.0), "NVDA": (130.0, 130.0), "SMH": (250.0, 250.0)})
    rep = scan_overnight_risk(p)
    assert rep.fx_change_pct is not None
    assert rep.fx_change_pct == pytest.approx((31.50 - 31.20) / 31.20 * 100.0)


def test_markdown_contains_symbols():
    p = FakeProvider({"TSM": (243.75, 250.0), "NVDA": (130.0, 130.0), "SMH": (250.0, 250.0)})
    rep = scan_overnight_risk(p)
    md = rep.to_markdown()
    assert "TSM" in md and "NVDA" in md and "SMH" in md
    assert "🔻" in md  # TSM 下跌箭頭


# ── 開盤前視窗判斷 ────────────────────────────────────────
def test_is_pre_open_before_0830():
    from datetime import datetime, timezone, timedelta
    t = datetime(2026, 7, 19, 7, 0, tzinfo=timezone(timedelta(hours=8)))
    assert is_tw_pre_open(t) is True


def test_is_pre_open_during_market():
    from datetime import datetime, timezone, timedelta
    t = datetime(2026, 7, 19, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    assert is_tw_pre_open(t) is False
