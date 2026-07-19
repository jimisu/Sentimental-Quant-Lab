"""
ADR / 美股隔夜風險雷達 (Overnight Shock Radar)
================================================

填補原系統的關鍵缺口：原 signal_engine 是「台股收盤後的回顧性情緒聚合器」，
所有輸入（財報、收盤量價、法人買賣超、宏觀最新值）在單日大跌當下都還是
「大跌前」的健康狀態，因此綠燈無法預警 7/17 那類由外部 / 事件驅動的跳空大跌。

本模組在台股開盤前監控海外標的的隔夜漲跌幅：
  - TSM  (台積電 ADR，台股 2330 開盤跳空最直接的領先指標)
  - NVDA (AI 多頭總舵手)
  - SMH  (半導體 ETF，費城半導體指數 SOX 的流動性代理)
  - TWD=X (美元兌台幣，匯率 context，不計入嚴重度)

若 TSM ADR 隔夜顯著下跌，開盤前即發出「跳空低開預警」，讓使用者在台股
開盤、原系統綠燈還沒反應之前，就先看到減碼 / 觀望信號。

設計原則：
  - 純監控 / 預警，不併入綜合燈號權重 → 不動 config.py 單例。
  - 複用 SAL YahooFinanceProvider（其 get_chart 已有 1 小時環形快取）。
  - 所有閾值為模組常數，未來若需集中管理可遷入 config.py（需授權）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── 監控標的 ──────────────────────────────────────────────
# (symbol, 中文標籤, 是否為台股跳空主驅動)
WATCH_SYMBOLS = [
    ("TSM", "台積電 ADR", True),
    ("NVDA", "NVIDIA", False),
    ("SMH", "半導體 ETF (SOX 代理)", False),
]

# ── 預警閾值（模組常數，非 config 單例）─────────────────────
TSM_RED_PCT = -4.0       # TSM ADR 跌逾 4% → 紅燈（預期顯著跳空低開）
TSM_YELLOW_PCT = -2.0    # TSM ADR 跌逾 2% → 黃燈（留意低開）
SECTOR_RED_PCT = -1.5    # 同時 NVDA 與 SMH 皆跌逾 1.5% → 類股系统性轉弱，升級
SECTOR_YELLOW_PCT = -3.0 # SMH 單獨跌逾 3% 而 TSM 平盤 → 類股風險，黃燈


@dataclass
class SymbolMove:
    """單一標的的隔夜漲跌。"""
    symbol: str
    label: str
    price: Optional[float] = None
    prev_close: Optional[float] = None
    change_pct: Optional[float] = None
    available: bool = True
    error: Optional[str] = None


@dataclass
class OvernightRiskReport:
    """ADR 隔夜風險掃描結果。"""
    level: str = "green"            # "red" / "yellow" / "green"
    emoji: str = "🟢"
    headline: str = ""
    recommendation: str = ""
    is_pre_open: bool = False       # 是否為台股開盤前情境
    tw_local_time: str = ""
    fx_change_pct: Optional[float] = None
    moves: list = field(default_factory=list)   # List[SymbolMove]

    @property
    def tsm_move(self) -> Optional[SymbolMove]:
        for m in self.moves:
            if m.symbol == "TSM":
                return m
        return None

    def to_markdown(self) -> str:
        lines = [
            "## 🌐 ADR / 美股隔夜風險雷達",
            "",
            f"**掃描時間（台灣）：** {self.tw_local_time} ｜ "
            f"{'開盤前預警' if self.is_pre_open else '盤中跟蹤'}",
            "",
            f"{self.emoji} **{self.headline}**",
            "",
            f"> {self.recommendation}",
            "",
            "| 標的 | 現價 | 前收 | 隔夜漲跌 |",
            "|------|------|------|----------|",
        ]
        for m in self.moves:
            if not m.available or m.change_pct is None:
                lines.append(f"| {m.label} ({m.symbol}) | - | - | 資料未取得 |")
                continue
            arrow = "🔻" if m.change_pct < 0 else ("🔺" if m.change_pct > 0 else "➖")
            lines.append(
                f"| {m.label} ({m.symbol}) | {m.price:.2f} | {m.prev_close:.2f} "
                f"| {arrow} {m.change_pct:+.2f}% |"
            )
        if self.fx_change_pct is not None:
            fx_arrow = "⬆️" if self.fx_change_pct > 0 else ("⬇️" if self.fx_change_pct < 0 else "➖")
            lines.append("")
            lines.append(f"**匯率 (USD/TWD) 隔夜：** {fx_arrow} {self.fx_change_pct:+.2f}%"
                         f"（台幣貶值會墊高 ADR 折算價、壓低溢價，但不改變跳空方向）")
        lines.append("")
        return "\n".join(lines)


def _taiwan_local_now() -> datetime:
    """回傳台灣本地時間（UTC+8）。"""
    return datetime.now(timezone.utc) + timedelta(hours=8)


def is_tw_pre_open(now: Optional[datetime] = None) -> bool:
    """
    判斷是否為台股開盤前情境。
    台股一般 09:00 開盤；08:30 前即為「開盤前預警」窗口。
    （不含盤中 / 盤後跟蹤）
    """
    if now is None:
        now = _taiwan_local_now()
    # 週六、週日非交易日前夕，仍視為預警窗口（週日晚間美股開盤後即有意義）
    return now.hour < 8 or (now.hour == 8 and now.minute < 30)


def _extract_move(provider, symbol: str, label: str, is_driver: bool) -> SymbolMove:
    """從 Yahoo chart 萃取單一標的的現價 / 前收 / 隔夜漲跌。"""
    try:
        data = provider.get_chart(symbol)
    except Exception as exc:  # noqa: BLE001 — 單一標的失敗不中斷整體掃描
        return SymbolMove(symbol=symbol, label=label, available=False,
                          error=f"fetch failed: {exc}")

    if not data or "chart" not in data or not data["chart"].get("result"):
        return SymbolMove(symbol=symbol, label=label, available=False, error="empty response")

    meta = data["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    if price is None or prev in (None, 0):
        return SymbolMove(symbol=symbol, label=label, available=False, error="missing meta fields")

    change_pct = (price - prev) / prev * 100.0
    return SymbolMove(
        symbol=symbol, label=label, price=float(price),
        prev_close=float(prev), change_pct=change_pct, available=True,
    )


def _fx_move(provider) -> Optional[float]:
    """USD/TWD 隔夜漲跌（台幣貶值為正）。"""
    try:
        data = provider.get_chart("TWD=X")
    except Exception:  # noqa: BLE001
        return None
    if not data or "chart" not in data or not data["chart"].get("result"):
        return None
    meta = data["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    if price is None or prev in (None, 0):
        return None
    return (price - prev) / prev * 100.0


def _assess_level(moves: list) -> tuple:
    """
    根據各標的漲跌決定燈號與文案。
    回傳 (level, emoji, headline, recommendation)。
    """
    tsm = next((m for m in moves if m.symbol == "TSM" and m.available), None)
    nvda = next((m for m in moves if m.symbol == "NVDA" and m.available), None)
    smh = next((m for m in moves if m.symbol == "SMH" and m.available), None)

    tsm_pct = tsm.change_pct if tsm else 0.0
    nvda_pct = nvda.change_pct if nvda else 0.0
    smh_pct = smh.change_pct if smh else 0.0

    # 基礎：以 TSM ADR 為主驅動
    if tsm_pct <= TSM_RED_PCT:
        level, emoji = "red", "🔴"
    elif tsm_pct <= TSM_YELLOW_PCT:
        level, emoji = "yellow", "🟡"
    else:
        level, emoji = "green", "🟢"

    # 類股系统性轉弱：NVDA 與 SMH 同步大跌 → 升級一級
    sector_weak = (nvda_pct <= SECTOR_RED_PCT) and (smh_pct <= SECTOR_RED_PCT)
    if sector_weak and level == "yellow":
        level, emoji = "red", "🔴"
    elif sector_weak and level == "green":
        level, emoji = "yellow", "🟡"

    # 類股單獨重挫但 TSM 平盤：仍給黃燈（外資情緒可能外溢）
    if level == "green" and smh_pct <= SECTOR_YELLOW_PCT:
        level, emoji = "yellow", "🟡"

    # 文案
    if level == "red":
        headline = "預期台股顯著跳空低開 — 外部 / 類股系统性賣壓"
        recommendation = ("⚠️ 開盤前即出現明確下跌信號，建議開盤減碼 / 觀望，"
                          "不追價；若已持有可考慮開盤後反彈減倉。")
    elif level == "yellow":
        headline = "留意開盤可能低開 — 隔夜風險偏空"
        recommendation = ("開盤前監控到偏空信號，建議控制部位、不急著加碼，"
                          "等待開盤後量價確認方向。")
    else:
        headline = "ADR 隔夜無明顯風險"
        recommendation = "海外標的隔夜平穩，依原系統信號正常觀察即可。"

    return level, emoji, headline, recommendation


def scan_overnight_risk(provider=None) -> OvernightRiskReport:
    """
    掃描 ADR / 美股隔夜風險。

    Args:
        provider: 可注入的 YahooFinanceProvider（測試用）；預設取 get_yahoo()。

    Returns:
        OvernightRiskReport
    """
    if provider is None:
        from sal import get_yahoo
        provider = get_yahoo()

    now = _taiwan_local_now()
    pre_open = is_tw_pre_open(now)

    moves = [
        _extract_move(provider, sym, lbl, drv)
        for sym, lbl, drv in WATCH_SYMBOLS
    ]
    fx = _fx_move(provider)

    level, emoji, headline, recommendation = _assess_level(moves)

    return OvernightRiskReport(
        level=level,
        emoji=emoji,
        headline=headline,
        recommendation=recommendation,
        is_pre_open=pre_open,
        tw_local_time=now.strftime("%Y-%m-%d %H:%M (UTC+8)"),
        fx_change_pct=fx,
        moves=moves,
    )


# 供 CLI 直接執行：python adr_radar.py
if __name__ == "__main__":
    rep = scan_overnight_risk()
    print(rep.to_markdown())
    sys.exit(0)
