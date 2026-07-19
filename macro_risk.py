"""
macro_risk.py — 外部系統性風險判讀模組

職責：區分「台積電自身基本面 / 籌碼面變化」與「跨市場連動、
槓桿商品斷鏈所驅動的外部系統性風險」。

為什麼需要它：
  技術面帶量破線、籌碼面外資連續賣超，並不必然是台積電基本面轉弱。
  若同期發生跨市場連動（韓股 / 費半 / 美股科技股同步重挫）或槓桿商品
  斷鏈式去槓桿，則當日暴跌與外資賣超多屬「技術性去風險」，而非法人
  對台積電基本面看法轉空。將此類賣超直接計入「轉空」判讀，會把
  系統性風險誤判為個股基本面訊號。

設計原則：
  - 純邏輯、低依賴：預設不觸發任何外部 API（可完全離線 / 快取驅動）。
  - 對外提供穩定介面，真實跨市場數據源可於未來接回（FinMind / Yahoo）。
  - 所有判讀結果均為「可注入 / 可覆寫」設計，便於單元與行為測試。

對外 API：
  - MacroRiskSignal            : 判讀結果資料結構
  - assess_macro_risk(...)    : 回傳當前外部系統性風險燈號（red / yellow / green）
  - is_systemic_event_day(...) : 判斷某日是否為外部系統性事件驅動的異常暴跌
  - classify_sell_pressure(...) : 分類外資賣超成因（systemic / fundamental / unknown）
  - days_since_earnings(...)  : 法說會後交易日數（動態欄位用）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Dict, List, Optional

try:
    import pandas as pd
except ImportError:
    pd = None


# ── 風險燈號常數 ───────────────────────────────────────────────────────
LEVEL_RED = "red"      # 外部系統性風險（跨市場連動 / 槓桿斷鏈）
LEVEL_YELLOW = "yellow"
LEVEL_GREEN = "green"

# 可注入的覆寫結果（測試 / 未來接真實數據源時使用）
_INJECTED: Dict[str, object] = {}


@dataclass
class MacroRiskSignal:
    """
    外部系統性風險判讀結果。

    level   : "red" | "yellow" | "green"
    is_red  : 是否處於外部系統性風險（紅燈）
    reason  : 人類可讀的判讀理由
    factors : 觸發的具體因子清單（如 "跨市場連動"、"槓桿商品斷鏈"）
    severity: 嚴重度描述（供報告顯示）
    """
    level: str = LEVEL_GREEN
    is_red: bool = False
    reason: str = "無外部系統性風險訊號"
    factors: List[str] = field(default_factory=list)
    severity: str = "低"

    @property
    def is_systemic(self) -> bool:
        """是否為外部系統性風險事件（紅燈）。"""
        return self.is_red


def assess_macro_risk(
    trading_df=None,
    price_df=None,
    *,
    as_of: Optional[_date] = None,
) -> MacroRiskSignal:
    """
    判讀當前「外部系統性風險」燈號。

    預設行為（無注入、無真實數據源）：回傳綠燈，理由為無外部系統性
    風險訊號。真實的跨市場連動 / 槓桿斷鏈檢測將於未來接回 FinMind /
    Yahoo 數據源後在此實作；對外介面與紅燈語意保持不變。

    注入（測試 / 手動覆寫）：
      透過 macro_risk._INJECTED["assess_macro_risk"] = MacroRiskSignal(...)
      可強制回傳特定結果，便於模擬「7/17 跨市場連動暴跌」場景。

    回傳：MacroRiskSignal
    """
    injected = _INJECTED.get("assess_macro_risk")
    if isinstance(injected, MacroRiskSignal):
        return injected

    # ── 真實實作占位（未來擴充）──────────────────────────────────
    # 此處應比對：韓股 / 費半 SOX / 美股科技股同期漲跌與成交量，
    # 以及槓桿 ETF（如 TQQQ / 槓桿期貨）是否出現斷鏈式折價 / 追繳。
    # 目前僅回傳綠燈，避免無數據時誤報紅燈。
    return MacroRiskSignal(
        level=LEVEL_GREEN,
        is_red=False,
        reason="無外部系統性風險訊號（跨市場連動 / 槓桿商品斷鏈監測待接回）",
        factors=[],
        severity="低",
    )


def is_systemic_event_day(price_df, day: _date) -> bool:
    """
    判斷 `day` 是否為「外部系統性事件驅動的異常暴跌日」。

    判斷邏輯（技術性定義，可注入覆寫）：
      該日出現「顯著下跌（預設 ≥ -5%）」且「成交量顯著放大
      （預設 ≥ 近 20 日均量 1.8 倍）」→ 視為系統性事件驅動的
      技術性下殺，而非個股基本面定價結果。

    price_df 需含「日期」索引與「收盤價」、「成交量」欄位；格式不符或
    無資料時回傳 False（保守：不誤判為事件日）。

    注入：透過 macro_risk._INJECTED["is_systemic_event_day"] = callable(day)->bool
    """
    injected = _INJECTED.get("is_systemic_event_day")
    if callable(injected):
        return bool(injected(day))

    if price_df is None or len(price_df) == 0:
        return False

    try:
        day_str = day.isoformat()
        # 索引可能為 DatetimeIndex（str(timestamp) 含時間）或字串索引，
        # 統一以 %Y-%m-%d 比對，避免 DatetimeIndex 比對失敗而誤判為非事件日。
        idx_dates = [
            d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
            for d in price_df.index
        ]
        if day_str not in idx_dates:
            return False
        row = price_df.loc[day_str]
        close_col = _first_col(price_df, ["收盤價", "close", "收盤", "Close"])
        vol_col = _first_col(price_df, ["成交量", "volume", "vol", "Volume"])
        if close_col is None or vol_col is None:
            return False

        closes = price_df[close_col].astype(float)
        prev = closes.shift(1)
        valid = prev.notna() & (prev != 0)
        drop_pct = ((closes - prev) / prev * 100).where(valid)

        vols = price_df[vol_col].astype(float)
        avg_vol = vols.rolling(20, min_periods=5).mean()

        day_drop = drop_pct.get(day_str, 0.0)
        day_vol = vols.get(day_str, 0.0)
        base_vol = avg_vol.get(day_str, 0.0)

        if base_vol <= 0:
            return False
        return bool((day_drop <= -5.0) and (day_vol >= base_vol * 1.8))
    except Exception:
        # 任何解析異常皆保守回傳 False，不影響主流程
        return False


def classify_sell_pressure(
    foreign_sell_shares: float,
    day: _date,
    *,
    event_days=None,
    is_systemic: Optional[bool] = None,
) -> Dict[str, object]:
    """
    分類「外資賣超」的成因，決定是否計入「轉空」判讀邏輯。

    參數：
      foreign_sell_shares : 該日外資賣超張數（正值表示淨賣超）
      day                  : 該賣超發生日期
      event_days           : 已知的外部系統性事件日集合（date 清單 / 可迭代）
      is_systemic         : 直接指定該日是否為系統性事件日（優先於 event_days）

    回傳 dict：
      {
        "driven_by": "systemic" | "fundamental" | "unknown",
        "counts_toward_bearish": bool,   # 是否計入「轉空」判讀
        "note": str,                      # 報告標註文字
      }

    規則：
      - 若該日為外部系統性事件日 → driven_by="systemic"，
        counts_toward_bearish=False（技術性去槓桿，非法人對基本面看法轉弱）。
      - 若非事件日但有顯著賣超 → driven_by="fundamental"，
        counts_toward_bearish=True（需計入轉空判讀）。
      - 若無法確認（無事件日資訊、賣超不顯著）→ driven_by="unknown"，
        counts_toward_bearish=False，建議搭配 macro_risk 燈號判讀。
    """
    if is_systemic is None:
        if event_days is not None:
            is_systemic = day in set(event_days)
        else:
            is_systemic = False

    if is_systemic:
        return {
            "driven_by": "systemic",
            "counts_toward_bearish": False,
            "note": "系統性風險驅動（外部連動 / 槓桿斷鏈），不計入轉空判讀",
        }

    if foreign_sell_shares and foreign_sell_shares > 0:
        return {
            "driven_by": "fundamental",
            "counts_toward_bearish": True,
            "note": "非系統性事件日之顯著賣超，計入轉空判讀",
        }

    return {
        "driven_by": "unknown",
        "counts_toward_bearish": False,
        "note": "外資賣超原因待確認，可能為基本面轉弱或外部連動效應，建議搭配 macro_risk.py 燈號判讀",
    }


def days_since_earnings(earnings_date: _date, as_of: Optional[_date] = None) -> int:
    """
    計算「法說會後 N 個交易日」。

    earnings_date : 最近一次法說會日期（應 ≤ as_of）
    as_of        : 基準日（預設為今日）

    實作：優先使用 pandas 營業日曆（BDay）精確計算交易日；
    若 pandas 不可用，則以「日曆天數 × 5/7」近似（保守高估，避免低估）。

    回傳：非負整數（若 as_of < earnings_date 則回傳 0）。
    """
    if as_of is None:
        as_of = _date.today()
    if earnings_date is None or as_of < earnings_date:
        return 0

    try:
        from pandas.tseries.offsets import BDay  # type: ignore

        n = len(pd.date_range(earnings_date, as_of, freq=BDay())) - 1
        return max(0, int(n))
    except Exception:
        # 備援近似：日曆天數 × 5/7（約當交易日）
        cal_days = (as_of - earnings_date).days
        return max(0, int(round(cal_days * 5.0 / 7.0)))


# ── 內部工具 ─────────────────────────────────────────────────────────────
def _first_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None
