"""
TSMC Quant Lab — 集中設定檔
所有魔法數字、權重、閾值統一在此管理。
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class CacheConfig:
    """快取相關設定"""
    ttl_hours: float = 4.0          # 快取有效期（小時）
    keep_count: int = 3             # 同一 key 保留最新幾份
    directory: str = "local_cache"  # 快取目錄


@dataclass
class ScoreWeightsConfig:
    """AI Agent 評分權重（有效資料時動態重新計算分母）"""
    early:  float = 0.10   # 早期警示（RSI 頂背離、量價背離）
    short:  float = 0.10   # 短期形態（K線、MA20 破位）
    mid:    float = 0.15   # 中期趨勢（週線指標）
    long:   float = 0.15   # 長期趨勢（月線）
    chip:   float = 0.25   # 籌碼分析（三大法人）
    macro:  float = 0.25   # 全球宏觀（ADR、匯率）

    def as_dict(self) -> Dict[str, float]:
        return {
            "early": self.early, "short": self.short, "mid": self.mid,
            "long": self.long,   "chip": self.chip,   "macro": self.macro,
        }


@dataclass
class TechnicalPenaltyConfig:
    """技術指標懲罰分（扣分值）"""
    # 早期警示
    volume_price_divergence:    int = 50
    rsi_daily_divergence:       int = 20
    rsi_weekly_divergence:      int = 30
    # 短期形態
    upper_shadow_kline:         int = 10
    engulf_black_kline:         int = 15
    consecutive_small_body:     int = 10
    ma20_cross_below:           int = 20
    # 中期趨勢
    weekly_ma12_turn_down:      int = 15
    weekly_rsi_break_60:        int = 10
    weekly_macd_death_cross:    int = 15
    # 長期趨勢
    monthly_ma12_turn_down:     int = 30
    monthly_break_ma12:         int = 40


@dataclass
class BollingerConfig:
    """布林通道設定"""
    period:   int   = 20
    std_mult: float = 2.0
    # 懲罰分
    penalty_break_upper: int = 15
    penalty_break_lower: int = 25
    # 帶寬收縮比例（相對近 60 日均值）
    squeeze_ratio: float = 0.60


@dataclass
class DashboardAlertConfig:
    """儀表板警示閾值"""
    revenue_yoy_yellow:     float = 20.0   # 營收 YoY 低於此值 → 黃燈
    margin_qoq_drop_yellow: float = 2.0    # 季度利率下滑超過此值 → 黃燈
    score_green_threshold:  float = 80.0   # 綜合分 > 此值 → 綠燈
    score_yellow_threshold: float = 60.0   # 綜合分 < 此值 → 黃燈


@dataclass
class ChipAlertConfig:
    """籌碼分析警示設定"""
    consecutive_days:       int   = 5      # 連續賣超天數
    big_sell_threshold_bn:  float = 1.0    # 大額賣超門檻（億元）
    chip_penalty_big_sell:  int   = 20     # 大額賣超扣分
    # 三大法人共振加成
    resonance_buy_bonus:    int   = 5      # 三大法人共振買超加分


@dataclass
class ApiConfig:
    """外部 API 設定"""
    finmind_url:        str = "https://api.finmindtrade.com/api/v4/data"
    twse_url:           str = "https://www.twse.com.tw/rwd/zh/afterTrading"
    yahoo_url_template: str = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    request_timeout:    int = 30
    twse_max_retries:   int = 3
    # TWSE 最早支援日期（民國 79/01/04）
    twse_min_date:      str = "1990-01-04"
    # 並行抓取最大執行緒數
    max_workers:        int = 4


@dataclass
class AnalysisConfig:
    """主設定物件，整合所有子設定"""
    cache:     CacheConfig            = field(default_factory=CacheConfig)
    weights:   ScoreWeightsConfig     = field(default_factory=ScoreWeightsConfig)
    penalty:   TechnicalPenaltyConfig = field(default_factory=TechnicalPenaltyConfig)
    bollinger: BollingerConfig        = field(default_factory=BollingerConfig)
    alert:     DashboardAlertConfig   = field(default_factory=DashboardAlertConfig)
    chip:      ChipAlertConfig        = field(default_factory=ChipAlertConfig)
    api:       ApiConfig              = field(default_factory=ApiConfig)

    # 日誌設定
    log_path:          str = "analysis_log.md"
    log_keep_per_day:  int = 1
    charts_dir:        str = "charts"
    charts_keep:       int = 1


# 全域單例，所有模組直接 import
CONFIG = AnalysisConfig()
