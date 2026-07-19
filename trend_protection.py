"""
趨勢保護信號 (Trend Protection Signal)
=======================================

原系統的綜合燈號是「健康診斷」，綠燈只代表基本面 / 籌碼 / 宏觀當前健康，
不代表價格不會跌。7/17 那類單日大跌發生時，輸入數據都還是「大跌前」的健康
狀態，綠燈照亮。本模組用「價格本身」做保護：當收盤價跌破關鍵均線 / 近期
支撐，即便基本面仍綠，也強制翻為減碼警示，承認「綠燈 ≠ 不會跌」。

判斷依據（全部來自台股 2330 日線，已在 dashboard 抓取）：
  - 收盤價 vs MA20 / MA60
  - MA20 斜率（是否下彎）
  - 收盤價 vs 近 N 日低點（是否跌破近期支撐）
  - 下跌日是否伴隨量增（出貨疑慮）

嚴重度可透過 signal_engine 的 protect_override 強制降級綜合燈號。
設計原則：純價格保護，不併入綜合燈號權重 → 不動 config.py 單例。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

CLOSE_COL = "台積電收盤價"
VOL_COL = "台積電成交金額"

MA20_WIN = 20
MA60_WIN = 60
SWING_WIN = 20          # 近期支撐觀察窗口
MA20_SLOPE_BARS = 5     # 比較 MA20 當下與 N 根前，判斷是否下彎
VOL_SPIKE_RATIO = 1.5   # 成交量為 20 日均量之倍數，視為量增


@dataclass
class TrendProtectionSignal:
    """趨勢保護評估結果。"""
    level: str = "green"        # "red" / "yellow" / "green"
    emoji: str = "🟢"
    headline: str = ""
    recommendation: str = ""
    close: float = 0.0
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    swing_low: Optional[float] = None
    ma20_slope_down: bool = False
    volume_spike_on_down: bool = False
    reasons: List[str] = field(default_factory=list)
    available: bool = True
    note: str = ""

    def to_markdown(self) -> str:
        if not self.available:
            return (f"## 🛡️ 趨勢保護信號\n\n"
                    f"> ⚠️ 價格資料不足（需至少 {MA60_WIN} 個交易日），無法評估。\n")
        lines = [
            "## 🛡️ 趨勢保護信號",
            "",
            f"{self.emoji} **{self.headline}**",
            "",
            f"> {self.recommendation}",
            "",
            "| 項目 | 數值 |",
            "|------|------|",
            f"| 收盤價 | {self.close:.2f} |",
            f"| MA20 | {self.ma20:.2f} |" if self.ma20 is not None else "| MA20 | N/A |",
            f"| MA60 | {self.ma60:.2f} |" if self.ma60 is not None else "| MA60 | N/A |",
            f"| 近 {SWING_WIN} 日低點 | {self.swing_low:.2f} |" if self.swing_low is not None else f"| 近 {SWING_WIN} 日低點 | N/A |",
            f"| MA20 斜率 | {'下彎 ⬇' if self.ma20_slope_down else '平 / 上揚 ⬆'} |",
            f"| 下跌量增 | {'是 🔻' if self.volume_spike_on_down else '否'} |",
            "",
            "**觸發理由：**",
        ]
        for r in self.reasons:
            lines.append(f"- {r}")
        if not self.reasons:
            lines.append("- 無（趨勢結構尚穩）")
        lines.append("")
        return "\n".join(lines)


def _severity(level: str) -> int:
    return {"green": 0, "yellow": 1, "red": 2}.get(level, 0)


def _upgrade(current: str, target: str) -> str:
    return current if _severity(current) >= _severity(target) else target


def evaluate_trend_protection(df, ma20_win: int = MA20_WIN, ma60_win: int = MA60_WIN,
                              swing_win: int = SWING_WIN) -> TrendProtectionSignal:
    """
    根據台股 2330 日線 DataFrame 評估趨勢保護。

    Args:
        df: 含 `台積電收盤價` 與 `台積電成交金額` 欄位的 DataFrame（依日期升冪）。
        ma20_win / ma60_win / swing_win: 視窗參數。

    Returns:
        TrendProtectionSignal
    """
    if df is None or CLOSE_COL not in df.columns or len(df) < ma60_win:
        return TrendProtectionSignal(available=False,
                                     note=f"需要至少 {ma60_win} 個交易日")

    closes = df[CLOSE_COL].astype(float)
    vols = df[VOL_COL].astype(float) if VOL_COL in df.columns else None

    close = float(closes.iloc[-1])
    ma20 = float(closes.rolling(ma20_win).mean().iloc[-1]) if len(closes) >= ma20_win else None
    ma60 = float(closes.rolling(ma60_win).mean().iloc[-1])

    # MA20 斜率：比較當下與 N 根前
    ma20_slope_down = False
    if ma20 is not None and len(closes) > MA20_SLOPE_BARS:
        prev_ma20 = float(closes.rolling(ma20_win).mean().iloc[-(MA20_SLOPE_BARS + 1)])
        ma20_slope_down = ma20 < prev_ma20

    # 近期支撐：前 swing_win 根（不含最後一根）的最低收盤
    swing_low = None
    if len(closes) > swing_win:
        swing_low = float(closes.iloc[-(swing_win + 1):-1].min())

    # 下跌量增
    volume_spike_on_down = False
    down_day = len(closes) >= 2 and close < float(closes.iloc[-2])
    if vols is not None and down_day and len(vols) >= ma20_win:
        vol_mean = float(vols.rolling(ma20_win).mean().iloc[-1])
        if vol_mean > 0:
            volume_spike_on_down = float(vols.iloc[-1]) > vol_mean * VOL_SPIKE_RATIO

    level = "green"
    reasons: List[str] = []

    # 1) 跌破 60MA → 中期趨勢轉弱（強）
    if ma60 is not None and close < ma60:
        level = _upgrade(level, "red")
        reasons.append(f"收盤價 {close:.2f} 跌破 60MA（{ma60:.2f}），中期趨勢轉弱")

    # 2) 跌破 20MA（配合 MA20 下彎更確立）
    if ma20 is not None and close < ma20:
        level = _upgrade(level, "yellow")
        if ma20_slope_down:
            reasons.append(f"收盤價 {close:.2f} 跌破 20MA（{ma20:.2f}）且 20MA 下彎")
        else:
            reasons.append(f"收盤價 {close:.2f} 跌破 20MA（{ma20:.2f}）")

    # 3) 跌破近期支撐
    if swing_low is not None and close < swing_low:
        level = _upgrade(level, "yellow")
        reasons.append(f"收盤價跌破近 {swing_win} 日低點支撐（{swing_low:.2f}）")

    # 4) 下跌伴量增 → 出貨疑慮
    if down_day and volume_spike_on_down:
        level = _upgrade(level, "yellow")
        reasons.append("下跌日伴隨成交量放大（>20 日均量 1.5 倍），出貨疑慮")

    if level == "red":
        headline = "趨勢保護觸發 — 價格結構轉弱"
        recommendation = ("🛡️ 即便基本面仍綠，價格已跌破關鍵支撐，建議減碼 / 設停損，"
                          "嚴控下行風險。")
        emoji = "🔴"
    elif level == "yellow":
        headline = "趨勢轉弱訊號 — 留意減碼"
        recommendation = ("🛡️ 價格出現轉弱跡象，建議降低部位、設定停損，不追價；"
                          "等待重新站穩均線再考慮加碼。")
        emoji = "🟡"
    else:
        headline = "趨勢結構尚穩"
        recommendation = "🛡️ 價格仍在關鍵均線之上，依原系統信號操作即可。"
        emoji = "🟢"

    return TrendProtectionSignal(
        level=level, emoji=emoji, headline=headline, recommendation=recommendation,
        close=close, ma20=ma20, ma60=ma60, swing_low=swing_low,
        ma20_slope_down=ma20_slope_down, volume_spike_on_down=volume_spike_on_down,
        reasons=reasons,
    )


# 供 CLI 直接執行（需先有 trading df；此處僅提供說明）
if __name__ == "__main__":
    print("trend_protection 需由 tsmc_signal_dashboard.main() 傳入台股日線 DataFrame 呼叫。")
