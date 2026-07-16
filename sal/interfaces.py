"""
SAL Interfaces - Abstract Base Classes
=======================================
Defines the contracts that all concrete providers must implement.
Upper-layer judgment logic depends ONLY on these interfaces.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────
# Data Transfer Objects (DTOs)
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class MonthlyRevenue:
    """Monthly revenue record from financial statements."""
    year: int
    month: int
    revenue: float          # in TWD thousands
    yoy_pct: Optional[float] = None


@dataclass(frozen=True)
class QuarterlyMargin:
    """Quarterly margin record."""
    year: int
    quarter: int
    gross_margin_pct: Optional[float] = None
    operating_margin_pct: Optional[float] = None
    net_margin_pct: Optional[float] = None
    eps: Optional[float] = None


@dataclass(frozen=True)
class DailyPrice:
    """Daily OHLCV price data."""
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: Optional[int] = None  # in TWD


@dataclass(frozen=True)
class InstitutionalFlow:
    """Institutional investor buy/sell flow."""
    date: datetime
    foreign_net: int      # shares
    trust_net: int        # shares
    dealer_net: int       # shares
    foreign_pct: Optional[float] = None
    trust_pct: Optional[float] = None
    dealer_pct: Optional[float] = None


@dataclass(frozen=True)
class ForeignOwnership:
    """Foreign ownership percentage."""
    date: datetime
    pct: float
    shares: int
    total_shares: int


@dataclass(frozen=True)
class EarningsCallSignal:
    """Parsed earnings call signal."""
    quarter: str          # e.g., "2025Q2"
    date: datetime
    capex_guidance: str
    n2_yield: str
    customer_visibility: str
    key_quotes: List[str]
    sentiment: str        # POSITIVE, NEUTRAL, NEGATIVE


@dataclass(frozen=True)
class SEC13FHolding:
    """13F holding record."""
    cik: str
    accession: str
    report_date: datetime
    filing_date: datetime
    ticker: str
    name: str
    shares: int
    value_usd_thousands: float


@dataclass(frozen=True)
class BigTechCAPEX:
    """Big tech CAPEX data point."""
    company: str
    quarter: str          # e.g., "2026Q1"
    capex_billion_usd: float
    qoq_pct: float
    yoy_pct: float
    guidance: Optional[str] = None


# ──────────────────────────────────────────────
# Provider Interfaces
# ──────────────────────────────────────────────
class FinancialDataProvider(ABC):
    """Interface for financial statement data (revenue, margins, EPS)."""

    @abstractmethod
    def get_monthly_revenue(
        self,
        stock_id: str,
        months: int = 24,
    ) -> List[MonthlyRevenue]:
        """Get monthly revenue with YoY growth."""
        ...

    @abstractmethod
    def get_quarterly_margins(
        self,
        stock_id: str,
        quarters: int = 8,
    ) -> List[QuarterlyMargin]:
        """Get quarterly margins (gross, operating, net) and EPS."""
        ...

    @abstractmethod
    def get_latest_quarter_eps(self, stock_id: str) -> Optional[float]:
        """Get latest quarter EPS."""
        ...


class InstitutionalFlowProvider(ABC):
    """Interface for institutional investor flow & foreign ownership data."""

    @abstractmethod
    def get_institutional_flow(
        self,
        stock_id: str,
        days: int = 30,
    ) -> List[InstitutionalFlow]:
        """Get daily institutional buy/sell flow."""
        ...

    @abstractmethod
    def get_foreign_ownership(
        self,
        stock_id: str,
        days: int = 252,
    ) -> List[ForeignOwnership]:
        """Get foreign ownership percentage history."""
        ...


class TWSEDataProvider(ABC):
    """Interface for TWSE market data (daily trading + market turnover)."""

    @abstractmethod
    def get_stock_day(
        self,
        stock_id: str,
        year_month: Optional[str] = None,
    ) -> List[DailyPrice]:
        """Get daily OHLCV for a stock (STOCK_DAY)."""
        ...

    @abstractmethod
    def get_market_turnover(
        self,
        days: int = 10,
    ) -> List[Tuple[datetime, int]]:
        """Get market-wide daily turnover (TWD)."""
        ...


class QuoteProvider(ABC):
    """Interface for current price quotes (Yahoo Finance ADR, FX, etc.)."""

    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol."""
        ...


class EarningsCallProvider(ABC):
    """Interface for earnings call transcripts and signals (not yet implemented)."""

    @abstractmethod
    def get_institutional_flow(
        self,
        stock_id: str,
        days: int = 30,
    ) -> List[InstitutionalFlow]:
        """Get daily institutional buy/sell flow."""
        ...

    @abstractmethod
    def get_foreign_ownership(
        self,
        stock_id: str,
        days: int = 252,
    ) -> List[ForeignOwnership]:
        """Get foreign ownership percentage history."""
        ...


class EarningsCallProvider(ABC):
    """Interface for earnings call transcripts and signals."""

    @abstractmethod
    def get_latest_signals(self, count: int = 5) -> List[EarningsCallSignal]:
        """Get latest earnings call signals."""
        ...

    @abstractmethod
    def upsert_signal(self, signal: EarningsCallSignal) -> None:
        """Add or update an earnings call signal (for manual maintenance)."""
        ...


class SECDataProvider(ABC):
    """Interface for SEC EDGAR data (company facts, submissions, 13F)."""

    @abstractmethod
    def get_company_facts(self, cik: str) -> Optional[Dict]:
        """Get company facts (XBRL) for a CIK."""
        ...

    @abstractmethod
    def get_submissions(self, cik: str) -> Optional[Dict]:
        """Get recent filings submissions for a CIK."""
        ...

    @abstractmethod
    def get_13f_holdings(
        self,
        cik: str,
        accession_number: str,
    ) -> Optional[str]:
        """Fetch raw 13F infotable XML/text for an accession.

        Returns the raw text; the caller parses it. Parsing is planned to
        move into SAL in a later step so this returns DTOs instead of text.
        """
        ...


class CacheProvider(ABC):
    """Interface for cache operations."""

    @abstractmethod
    def get(self, key: str, max_age_hours: Optional[int] = None) -> Optional[Any]:
        """Get cached value if fresh enough."""
        ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Set cached value with timestamp."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete cached value."""
        ...

    @abstractmethod
    def clear_expired(self, max_age_hours: int = 24) -> int:
        """Clear expired cache entries. Returns count cleared."""
        ...


# ──────────────────────────────────────────────
# Provider Exceptions
# ──────────────────────────────────────────────
class SALProviderError(Exception):
    """Base exception for SAL provider errors."""
    pass


class ProviderNotFoundError(SALProviderError):
    """Requested provider not registered."""
    pass


class APIRateLimitError(SALProviderError):
    """API rate limit exceeded."""
    pass


class DataParseError(SALProviderError):
    """Failed to parse API response."""
    pass


class CacheMissError(SALProviderError):
    """Cache miss - data not available."""
    pass