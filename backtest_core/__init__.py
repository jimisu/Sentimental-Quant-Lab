"""
Backtest Core Modules
=====================
回測核心模組套件，提供共用的資料載入、指標計算、訊號分析、評估與模擬功能。
"""

from .data_loader import BacktestDataLoader, load_all_cached_data, CachedDataPaths
from .eps_calculator import (
    EPSTimeline,
    QuarterlyEPS,
    compute_trailing_pe,
    build_price_lookup,
    build_shareholding_lookup,
    get_foreign_shares_asof,
    build_price_dataframe_asof,
)
from .technical_indicators import (
    PriceDataFrame,
    TechnicalSnapshot,
    compute_daily_returns,
    build_price_lookup as build_price_lookup_ti,
    get_foreign_shares_asof as get_foreign_shares_asof_ti,
    get_price_dataframe_asof,
    build_technical_snapshots,
)
from .signal_analyzer import (
    LeadingIndicatorConfig,
    LeadingIndicatorAnalyzer,
    CrashSignalResult,
    CrashSignalAnalyzer,
)
from .cluster import (
    TriggerCluster,
    cluster_triggers,
)
from .evaluator import (
    EvaluationResult,
    BacktestEvaluator,
    evaluate_clusters,
)
from .simulator import (
    SimulatedTrade,
    SimulationResult,
    StrategySimulator,
    simulate_strategy,
    print_simulation,
)
from .buyback_analyzer import (
    BuybackResult,
    BuybackSummary,
    BuybackAnalyzer,
    analyze_buyback_opportunity,
    print_buyback_analysis,
)
from .reporting import (
    print_evaluation,
    generate_markdown_report,
    save_markdown_report,
)

__all__ = [
    # data_loader
    "BacktestDataLoader",
    "load_all_cached_data",
    "CachedDataPaths",
    # eps_calculator
    "EPSTimeline",
    "QuarterlyEPS",
    "compute_trailing_pe",
    "build_price_lookup",
    "build_shareholding_lookup",
    "get_foreign_shares_asof",
    "build_price_dataframe_asof",
    # technical_indicators
    "PriceDataFrame",
    "TechnicalSnapshot",
    "compute_daily_returns",
    "build_price_lookup",
    "get_foreign_shares_asof",
    "get_price_dataframe_asof",
    "build_technical_snapshots",
    # signal_analyzer
    "LeadingIndicatorConfig",
    "LeadingIndicatorAnalyzer",
    "CrashSignalResult",
    "CrashSignalAnalyzer",
    # cluster
    "TriggerCluster",
    "cluster_triggers",
    # evaluator
    "EvaluationResult",
    "BacktestEvaluator",
    "evaluate_clusters",
    # simulator
    "SimulatedTrade",
    "SimulationResult",
    "StrategySimulator",
    "simulate_strategy",
    "print_simulation",
    # buyback_analyzer
    "BuybackResult",
    "BuybackSummary",
    "BuybackAnalyzer",
    "analyze_buyback_opportunity",
    "print_buyback_analysis",
    # reporting
    "print_evaluation",
    "generate_markdown_report",
    "save_markdown_report",
]