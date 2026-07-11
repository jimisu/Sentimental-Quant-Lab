"""
Service Abstraction Layer (SAL)
Isolates upper-layer judgment logic from lower-layer API calls and external data scraping.

Architecture:
┌─────────────────────────────────────────────────────────────┐
│  Upper Layer: Judgment / Analysis / Agents                 │
│  (Orchestrator, SignalEngine, AI Agents, LongTermMonitor)  │
├─────────────────────────────────────────────────────────────┤
│  SAL (Service Abstraction Layer)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Interfaces │  │  Providers  │  │   Registry  │         │
│  │  (Abstract) │──│(Concrete)   │──│  (Factory)  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
├─────────────────────────────────────────────────────────────┤
│  Lower Layer: External APIs / Scraping                      │
│  (FinMind, TWSE, Yahoo Finance, SEC EDGAR, Cache)          │
└─────────────────────────────────────────────────────────────┘

Usage:
    from sal import get_finmind, get_twse, get_yahoo, get_sec, get_cache

    finmind = get_finmind()
    revenue = finmind.get_monthly_revenue("2330")

    twse = get_twse()
    daily = twse.get_stock_day("2330")

    yahoo = get_yahoo()
    adr_price = yahoo.get_tsmc_adr_price()

    sec = get_sec()
    facts = sec.get_company_facts("0002012383")

    cache = get_cache()
    cache.set("my_key", {"data": "value"})
    value = cache.get("my_key", max_age_hours=24)
"""
from sal.interfaces import (
    # Core interfaces
    SALProviderError,
    ProviderNotFoundError,
    APIRateLimitError,
    DataParseError,
    CacheMissError,
    # Cache interface
    # Provider classes (imported from providers)
)

from sal.providers import (
    FinMindProvider,
    TWSEProvider,
    YahooFinanceProvider,
    SECEdgarProvider,
    FileCacheProvider,
    ProviderRegistry,
    registry,
    get_finmind,
    get_twse,
    get_yahoo,
    get_sec,
    get_cache,
)

__all__ = [
    # Exceptions
    "SALProviderError",
    "ProviderNotFoundError",
    "APIRateLimitError",
    "DataParseError",
    "CacheMissError",
    # Providers
    "FinMindProvider",
    "TWSEProvider",
    "YahooFinanceProvider",
    "SECEdgarProvider",
    "FileCacheProvider",
    "ProviderRegistry",
    "registry",
    # Convenience functions
    "get_finmind",
    "get_twse",
    "get_yahoo",
    "get_sec",
    "get_cache",
]

__version__ = "1.0.0"