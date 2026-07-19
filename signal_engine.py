#!/usr/bin/env python3
"""
TSMC 信號引擎 (Signal Engine)

統一管理所有燈號判斷與綜合健康得分計算。
將原本散落在 tsmc_signal_dashboard.py 與 tsmc_ai_agents.py 的邏輯集中於此。

架構：
  FinancialSignalCalculator  — 純財務（營收 YoY、三率）→ 財務分數 0~100
  BigTechSignalCalculator    — 大廠基本面（CAPEX + NVDA 營收 YoY）→ 分數 0~100
  ComprehensiveScoreCalculator — 四面向加權 → 綜合健康得分 0~100
  AlertLevelDetector          — 綜合分數 + 特殊條件 → 紅/黃/綠燈
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import CONFIG


# ══════════════════════════════════════════════════════════════
# 資料容器
# ══════════════════════════════════════════════════════════════

@dataclass
class FinancialSignals:
    """財務面向信號（由 QuarterlyFinancialAgent / dashboard 提供）"""
    # 最新一季數據
    latest_revenue_yoy: Optional[float] = None       # 最新月營收 YoY%
    latest_gross_margin: Optional[float] = None      # 最新季度毛利率%
    latest_operating_margin: Optional[float] = None  # 最新季度營業利益率%
    latest_net_margin: Optional[float] = None        # 最新季度稅後淨利率%
    # 季度環比變化（正數 = 下滑）
    gross_drop: Optional[float] = None               # 毛利率季度變化（pp）
    op_drop: Optional[float] = None                  # 營業利益率季度變化（pp）
    net_drop: Optional[float] = None                 # 稅後淨利率季度變化（pp）
    # 趨勢
    revenue_yoy_declining: bool = False              # 營收 YoY 是否連續下滑
    margin_deteriorating: bool = False               # 三率是否連續惡化


@dataclass
class TechnicalSignals:
    """技術面向信號（由 MarketDynamicsAgent 提供）"""
    scores: Dict[str, int] = field(default_factory=lambda: {
        "early": 100, "short": 100, "mid": 100, "long": 100
    })
    flags: Dict = field(default_factory=dict)


@dataclass
class ChipSignals:
    """籌碼面向信號（由 InstitutionalInvestorAgent 提供）"""
    score: int = 100
    flags: Dict = field(default_factory=dict)


@dataclass
class BigTechSignals:
    """大廠基本面信號（由 GlobalMacroAgent.analyze_bigtech_fundamentals 提供）"""
    # CAPEX 趨勢 (0~100)
    capex_score: int = 100
    capex_growing_count: int = 0
    capex_valid_count: int = 0
    # NVDA 營收 YoY%（最新一季）
    nvda_revenue_yoy: Optional[float] = None
    # NVDA 過去三季營收 YoY% 列表（每季 dict: {"period": str, "yoy": float}）
    nvda_revenue_yoy_quarters: List = field(default_factory=list)
    # NVDA 營收趨勢分數 (0~100)
    nvda_revenue_score: int = 100
    # 綜合大廠分數（由 BigTechSignalCalculator 計算後寫入）
    score: int = 100
    # 細節
    capex_details: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class MacroSignals:
    """宏觀面向信號（由 GlobalMacroAgent 提供，不含 CAPEX）"""
    score: int = 100


@dataclass
class ComprehensiveResult:
    """綜合分析結果"""
    # 各面向分數
    financial_score: float = 100.0
    bigtech_score: float = 100.0
    tech_score: float = 100.0               # 技術面綜合（早期/短期/中期/長期合併）
    chip_score: float = 100.0
    macro_score: float = 100.0
    # 綜合
    comprehensive_score: float = 100.0
    # 燈號
    alert_level: str = "green"   # "red" / "yellow" / "green"
    alert_label: str = "綠燈"
    alert_emoji: str = "🟢"
    alert_message: str = ""
    # 特殊訊號
    reversal_signal: bool = False
    reversal_advanced: bool = False
    double_warning: bool = False
    # 細節
    details: Dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════
# 財務信號計算器
# ══════════════════════════════════════════════════════════════

class FinancialSignalCalculator:
    """
    將基本面資料轉換為 0~100 財務分數。

    評分邏輯：
    - 基礎分 100，根據各項訊號扣分
    - 營收 YoY 扣分：< 20% → -10, < 0% → -20, 連續下滑 → 額外 -10
    - 毛利率季度下滑：> 2pp → -10, > 4pp → -20
    - 營業利益率季度下滑：> 2pp → -10, > 4pp → -20
    - 稅後淨利率季度下滑：> 2pp → -5, > 4pp → -10
    - 三率中 ≥2 項下滑 > 2pp → 額外 -10（基本面全面轉弱）
    """

    # 扣分閾值
    REV_YOY_YELLOW = 20.0    # 營收 YoY 黃線
    REV_YOY_RED = 0.0        # 營收 YoY 紅線（負成長）
    MARGIN_DROP_YELLOW = 2.0 # 利率下滑黃線（pp）
    MARGIN_DROP_RED = 4.0    # 利率下滑紅線（pp）

    def calculate(self, signals: FinancialSignals) -> Tuple[float, List[str]]:
        """
        計算財務分數。
        回傳：(score, warnings)
        """
        score = 100
        warnings = []

        # ── 營收 YoY ──
        if signals.latest_revenue_yoy is not None:
            if signals.latest_revenue_yoy < self.REV_YOY_RED:
                score -= 20
                warnings.append(f"營收 YoY 負成長 ({signals.latest_revenue_yoy:.1f}%)")
            elif signals.latest_revenue_yoy < self.REV_YOY_YELLOW:
                score -= 10
                warnings.append(f"營收 YoY 低於 20% ({signals.latest_revenue_yoy:.1f}%)")

            if signals.revenue_yoy_declining:
                score -= 10
                warnings.append("營收 YoY 連續下滑")

        # ── 毛利率 ──
        if signals.gross_drop is not None:
            if signals.gross_drop > self.MARGIN_DROP_RED:
                score -= 20
                warnings.append(f"毛利率大幅下滑 {signals.gross_drop:.1f}pp")
            elif signals.gross_drop > self.MARGIN_DROP_YELLOW:
                score -= 10
                warnings.append(f"毛利率下滑 {signals.gross_drop:.1f}pp")

        # ── 營業利益率 ──
        if signals.op_drop is not None:
            if signals.op_drop > self.MARGIN_DROP_RED:
                score -= 20
                warnings.append(f"營業利益率大幅下滑 {signals.op_drop:.1f}pp")
            elif signals.op_drop > self.MARGIN_DROP_YELLOW:
                score -= 10
                warnings.append(f"營業利益率下滑 {signals.op_drop:.1f}pp")

        # ── 稅後淨利率 ──
        if signals.net_drop is not None:
            if signals.net_drop > self.MARGIN_DROP_RED:
                score -= 10
                warnings.append(f"稅後淨利率大幅下滑 {signals.net_drop:.1f}pp")
            elif signals.net_drop > self.MARGIN_DROP_YELLOW:
                score -= 5
                warnings.append(f"稅後淨利率下滑 {signals.net_drop:.1f}pp")

        # ── 三率全面下滑加成 ──
        drops = [
            (signals.gross_drop or 0) > self.MARGIN_DROP_YELLOW,
            (signals.op_drop or 0) > self.MARGIN_DROP_YELLOW,
            (signals.net_drop or 0) > self.MARGIN_DROP_YELLOW,
        ]
        if sum(drops) >= 2:
            score -= 10
            warnings.append("三率中 ≥2 項同步下滑，基本面全面轉弱")

        score = max(0, score)
        return score, warnings


# ══════════════════════════════════════════════════════════════
# 大廠基本面計算器
# ══════════════════════════════════════════════════════════════

class BigTechSignalCalculator:
    """
    計算大廠基本面分數（CAPEX + NVDA 營收 YoY）。

    CAPEX 分數邏輯：
    - 4 家公司（MSFT/META/GOOGL/AMZN）的近三季 CAPEX 趨勢
    - ≥3/4 持續成長 → 100
    - 2/4 → 75
    - 1/4 → 50
    - 0/4 → 25

    NVDA 營收 YoY 分數：
    - YoY ≥ 50% → 100（AI 需求爆發）
    - YoY ≥ 20% → 80
    - YoY ≥ 0%  → 60
    - YoY < 0%  → 40
    - 資料不足 → 不影響分數

   綜合大廠分數 = CAPEX 分數 * 0.5 + NVDA 營收分數 * 0.5
    """

    def calculate(
        self,
        capex_growing_count: int = 0,
        capex_valid_count: int = 0,
        nvda_revenue_yoy: Optional[float] = None,
    ) -> Tuple[int, List[str]]:
        warnings = []

        # ── CAPEX 分數 ──
        if capex_valid_count == 0:
            capex_score = 100  # 資料不足時不扣分
        else:
            capex_ratio = capex_growing_count / capex_valid_count
            if capex_ratio >= 0.75:
                capex_score = 100
            elif capex_ratio >= 0.5:
                capex_score = 75
                warnings.append(f"CAPEX 成長趨緩：{capex_growing_count}/{capex_valid_count} 家持續成長")
            elif capex_ratio >= 0.25:
                capex_score = 50
                warnings.append(f"CAPEX 成長分歧：僅 {capex_growing_count}/{capex_valid_count} 家持續成長")
            else:
                capex_score = 25
                warnings.append(f"CAPEX 全面放緩：僅 {capex_growing_count}/{capex_valid_count} 家持續成長")

        # ── NVDA 營收 YoY 分數 ──
        if nvda_revenue_yoy is None:
            nvda_score = 100  # 資料不足時不扣分
        elif nvda_revenue_yoy >= 50:
            nvda_score = 100
        elif nvda_revenue_yoy >= 20:
            nvda_score = 80
        elif nvda_revenue_yoy >= 0:
            nvda_score = 60
            warnings.append(f"NVDA 營收 YoY 趨緩 ({nvda_revenue_yoy:.1f}%)")
        else:
            nvda_score = 40
            warnings.append(f"NVDA 營收 YoY 負成長 ({nvda_revenue_yoy:.1f}%)")

        # ── 綜合（CAPEX 50% + NVDA 50%）──
        if nvda_revenue_yoy is None:
            # NVDA 資料不足時，CAPEX 權重拉滿
            combined = capex_score
        else:
            combined = int(capex_score * 0.5 + nvda_score * 0.5)

        return combined, warnings


# ══════════════════════════════════════════════════════════════
# 綜合得分計算器
# ══════════════════════════════════════════════════════════════

class ComprehensiveScoreCalculator:
    """
    整合四面向計算綜合健康得分。

    權重（config.py ScoreWeightsConfig 可調整）：
    - 純財務面   30%
    - 大廠基本面 30%
    - 技術面     20%（早期/短期/中期/長期合併計算）
    - 籌碼面     20%（含外資高檔出貨監測）

    註：四面向權重合計 1.00，綜合得分上限為 100；燈號門檻
    （<50 紅 / <70 黃）為百分比門檻，無須歸一化。
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        if weights is None:
            w = CONFIG.weights
            self.weights = {
                "financial": w.financial,
                "bigtech":   w.bigtech,
                "tech":      w.tech,
                "chip":      w.chip,
            }
        else:
            self.weights = weights

    def calculate(
        self,
        financial_score: float,
        bigtech_signals: BigTechSignals,
        tech_signals: TechnicalSignals,
        chip_signals: ChipSignals,
    ) -> Tuple[float, Dict[str, float]]:
        """
        計算綜合健康得分。
        技術面四項（早期/短期/中期/長期）先加權平均為單一 tech 分數。
        回傳：(comprehensive_score, breakdown)
        """
        # 技術面四項加權平均
        tech = tech_signals.scores
        tech_sub_weights = CONFIG.weights
        tech_total_w = tech_sub_weights.early + tech_sub_weights.short + tech_sub_weights.mid + tech_sub_weights.long
        if tech_total_w > 0:
            tech_combined = (
                tech["early"]  * tech_sub_weights.early +
                tech["short"]  * tech_sub_weights.short +
                tech["mid"]    * tech_sub_weights.mid +
                tech["long"]   * tech_sub_weights.long
            ) / tech_total_w
        else:
            tech_combined = 100.0

        breakdown = {
            "financial":        financial_score * self.weights["financial"],
            "bigtech":          bigtech_signals.score * self.weights["bigtech"],
            "tech":             tech_combined * self.weights["tech"],
            "chip":             chip_signals.score * self.weights["chip"],
        }
        comprehensive = sum(breakdown.values())
        return comprehensive, breakdown


# ══════════════════════════════════════════════════════════════
# 燈號偵測器
# ══════════════════════════════════════════════════════════════

class AlertLevelDetector:
    """
    根據綜合分數 + 特殊條件決定燈號。

    燈號規則：
    - 🔴 紅燈：綜合分數 < 50，或觸發進階轉折訊號，或基本面 + 技術面同時黃燈以下
    - 🟡 黃燈：綜合分數 < 70，或觸發基礎轉折訊號，或籌碼面嚴重惡化（< 30）
    - 🟢 綠燈：綜合分數 ≥ 70 且無特殊訊號

    結構性警示（不影響分數，僅升級燈號）：
    - 籌碼面 < 30 → 強制至少黃燈
    （籌碼面另受「外資高檔出貨」獨立紅燈規則約束，見 Orchestrator 總覽。）

    註：原「籌碼面 < 50 且 市場情緒 < 50 → 強制黃燈」之結構性警示已移除。
    市場情緒（量能）為落後指標，會在技術/籌碼已轉弱時仍因「量能未萎縮」
    把分數撐在綠燈區，造成失真；故情緒已完全移出計分與燈號判定。
    """

    RED_THRESHOLD: float = 50.0
    YELLOW_THRESHOLD: float = 70.0

    # 結構性警示閾值：籌碼面低於此值視為嚴重惡化
    CHIP_WARNING_THRESHOLD: float = 50.0

    def detect(
        self,
        comprehensive_score: float,
        financial_warnings: List[str],
        tech_flags: Dict,
        chip_flags: Dict,
        reversal_basic: bool = False,
        reversal_advanced: bool = False,
        chip_score: float = 100.0,
    ) -> Tuple[str, str, str, str]:
        """
        偵測燈號。
        回傳：(alert_level, alert_label, alert_emoji, alert_message)

        結構性警示規則：
        - 籌碼面單項嚴重惡化（< 30）→ 強制至少黃燈
        """
        messages = []

        # ── 進階轉折訊號 → 直接紅燈 ──
        if reversal_advanced:
            return (
                "red", "紅燈", "🔴",
                "🚨🚨🚨 高強度轉折訊號：20MA 轉負 + 月線破 MA12 + 外資大額賣超 + 布林通道壓縮後破位，趨勢強烈反轉！"
            )

        # ── 基礎轉折訊號 → 至少黃燈 ──
        if reversal_basic:
            messages.append("⚠️ 轉折訊號：20MA 轉負 + 月線破 MA12 + 外資大額賣超")

        # ── 雙重預警（基本面 + 技術面同時轉弱）──
        has_finacial_warning = len(financial_warnings) > 0
        tech_weak = comprehensive_score < self.YELLOW_THRESHOLD
        if has_finacial_warning and tech_weak:
            messages.append("⚠️ 基本面與技術面同時轉弱，出現雙重預警")

        # ── 結構性警示：籌碼面嚴重惡化 ──
        if chip_score < 30:
            messages.append(f"⚠️ 籌碼面嚴重惡化（{chip_score:.0f} 分），外資持續撤退")

        # ── 根據綜合分數判定 ──
        if comprehensive_score < self.RED_THRESHOLD:
            level, label, emoji = "red", "紅燈", "🔴"
        elif comprehensive_score < self.YELLOW_THRESHOLD:
            level, label, emoji = "yellow", "黃燈", "🟡"
        else:
            level, label, emoji = "green", "綠燈", "🟢"

        # ── 結構性升級（在分數判定之後套用，避免訊息與最終燈號不一致）──
        # 有轉折訊號 → 黃燈升紅燈
        if reversal_basic and level == "yellow":
            level, label, emoji = "red", "紅燈", "🔴"
        # 籌碼面嚴重惡化（< 30）→ 強制至少黃燈
        if chip_score < 30 and level == "green":
            level, label, emoji = "yellow", "黃燈", "🟡"

        # ── 依最終燈號產出基準訊息（確保與升級後燈號一致）──
        if level == "red":
            base_msg = f"綜合健康得分 {comprehensive_score:.1f} 低於 {self.RED_THRESHOLD}，處於紅燈區間"
        elif level == "yellow":
            base_msg = f"綜合健康得分 {comprehensive_score:.1f} 處於黃燈區間（{self.YELLOW_THRESHOLD} 以下）"
        else:
            base_msg = f"綜合健康得分 {comprehensive_score:.1f}，處於綠燈區間"

        if messages:
            full_msg = " | ".join(messages) + f"；{base_msg}"
        else:
            full_msg = base_msg

        return level, label, emoji, full_msg


# ══════════════════════════════════════════════════════════════
# 分數 → 燈號 輔助函式
# ══════════════════════════════════════════════════════════════

def score_to_alert(score: float) -> Tuple[str, str, str]:
    """
    將 0~100 分數對應為燈號 (level, label, emoji)。

    與 AlertLevelDetector 共用相同門檻：<50 紅燈、<70 黃燈、≥70 綠燈。
    供總覽儀表板將多面向合併為單一燈號時複用，確保與綜合燈號邏輯一致。
    """
    if score < AlertLevelDetector.RED_THRESHOLD:
        return "red", "紅燈", "🔴"
    elif score < AlertLevelDetector.YELLOW_THRESHOLD:
        return "yellow", "黃燈", "🟡"
    return "green", "綠燈", "🟢"


# ══════════════════════════════════════════════════════════════
# 整合入口
# ══════════════════════════════════════════════════════════════

class SignalEngine:
    """
    信號引擎整合入口。
    一次呼叫完成所有計算，回傳 ComprehensiveResult。
    """

    def __init__(self):
        self.fin_calc = FinancialSignalCalculator()
        self.bigtech_calc = BigTechSignalCalculator()
        self.score_calc = ComprehensiveScoreCalculator()
        self.alert_detector = AlertLevelDetector()

    def analyze(
        self,
        financial_signals: FinancialSignals,
        bigtech_signals: BigTechSignals,
        tech_signals: TechnicalSignals,
        chip_signals: ChipSignals,
    ) -> ComprehensiveResult:
        """
        完整分析流程：
        1. 計算財務分數
        2. 計算大廠基本面分數
        3. 計算綜合得分
        4. 偵測特殊訊號
        5. 判定燈號
        """
        result = ComprehensiveResult()

        # Step 1: 財務分數
        fin_score, fin_warnings = self.fin_calc.calculate(financial_signals)
        result.financial_score = fin_score

        # Step 2: 大廠基本面分數
        bigtech_score, bigtech_warnings = self.bigtech_calc.calculate(
            capex_growing_count=bigtech_signals.capex_growing_count,
            capex_valid_count=bigtech_signals.capex_valid_count,
            nvda_revenue_yoy=bigtech_signals.nvda_revenue_yoy,
        )
        bigtech_signals.score = bigtech_score
        bigtech_signals.warnings = bigtech_warnings
        result.bigtech_score = bigtech_score

        # Step 3: 綜合得分
        comp_score, breakdown = self.score_calc.calculate(
            fin_score, bigtech_signals, tech_signals, chip_signals
        )
        result.comprehensive_score = comp_score
        result.tech_score = breakdown.get("tech", 0) / self.score_calc.weights["tech"] if self.score_calc.weights["tech"] > 0 else 100
        result.chip_score = chip_signals.score

        # Step 4: 特殊訊號偵測
        reversal_basic = (
            tech_signals.flags.get("ma20_cross_below", False) and
            tech_signals.flags.get("monthly_break_ma12", False) and
            chip_signals.flags.get("big_foreign_sell", False)
        )
        reversal_advanced = (
            reversal_basic and
            tech_signals.flags.get("bb_squeeze_break", False)
        )
        result.reversal_signal = reversal_basic
        result.reversal_advanced = reversal_advanced

        # 雙重預警
        result.double_warning = (
            len(fin_warnings) > 0 and comp_score < AlertLevelDetector.YELLOW_THRESHOLD
        )

        # Step 5: 燈號
        level, label, emoji, message = self.alert_detector.detect(
            comp_score, fin_warnings, tech_signals.flags, chip_signals.flags,
            reversal_basic=reversal_basic,
            reversal_advanced=reversal_advanced,
            chip_score=chip_signals.score,
        )
        result.alert_level = level
        result.alert_label = label
        result.alert_emoji = emoji
        result.alert_message = message

        # 細節
        result.details = {
            "breakdown": breakdown,
            "financial_warnings": fin_warnings,
            "financial_score": fin_score,
            "bigtech_score": bigtech_score,
            "bigtech_warnings": bigtech_warnings,
            "reversal_basic": reversal_basic,
            "reversal_advanced": reversal_advanced,
            "double_warning": result.double_warning,
        }

        return result
