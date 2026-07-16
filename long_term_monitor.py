#!/usr/bin/env python3
"""
Long-term TSMC Investment Monitor (3-5 Year Horizon)
Focuses on structural variables only — filters out short-term noise.

Usage:
  python long_term_monitor.py                 # Run once, print dashboard
  python long_term_monitor.py --schedule      # Run once (for cron)
  python long_term_monitor.py --daemon        # Run continuously, every Monday 08:00
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import requests

CACHE_DIR = Path("local_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
CURRENT_PRICE = 2465  # Will be auto-fetched if possible
FAIR_PE_LOW = 25      # Conservative PE
FAIR_PE_HIGH = 30     # Aggressive PE
FORWARD_QUARTERS = 4  # Use next 4 quarters EPS for forward PE

# ──────────────────────────────────────────────
# Data Structures
# ──────────────────────────────────────────────
@dataclass
class EPSTrend:
    quarters: list[str]
    eps_values: list[float]
    yoy_growth: list[float]
    cagr_3y: Optional[float] = None
    latest_quarter: str = ""
    latest_eps: float = 0.0

@dataclass
class CAPEXGuidance:
    company: str
    latest_quarter: str
    capex_billion_usd: float
    qoq_change: float
    yoy_change: float
    guidance_next_quarter: Optional[str] = None

@dataclass
class N2Timeline:
    risk_production: Optional[str] = None
    volume_production: Optional[str] = None
    yield_status: str = "Unknown"
    latest_update: str = ""
    source: str = ""

@dataclass
class ForeignOwnership:
    current_pct: float
    monthly_change: float
    yearly_change: float
    trend_12m: list[float]
    dates_12m: list[str]

@dataclass
class FairValueRange:
    forward_eps: float
    pe_low: int
    pe_high: int
    fair_low: float
    fair_high: float
    current_price: float
    upside_low_pct: float
    upside_high_pct: float
    assessment: str  # "UNDERVALUED" | "FAIR" | "OVERVALUED"

@dataclass
class EarningsCallSignal:
    quarter: str
    date: str
    capex_guidance: str = ""
    n2_yield: str = ""
    customer_visibility: str = ""
    key_quotes: list[str] = None
    sentiment: str = "NEUTRAL"  # POSITIVE | NEUTRAL | NEGATIVE

    def __post_init__(self):
        if self.key_quotes is None:
            self.key_quotes = []

@dataclass
class LongTermSnapshot:
    timestamp: str
    eps: EPSTrend
    capex: list[CAPEXGuidance]
    n2: N2Timeline
    foreign_ownership: ForeignOwnership
    fair_value: FairValueRange
    earnings_signals: list[EarningsCallSignal]
    assessment: str  # "BULLISH" | "NEUTRAL" | "BEARISH"
    key_risks: list[str]
    catalysts: list[str]

# ──────────────────────────────────────────────
# Data Fetchers (with caching)
# ──────────────────────────────────────────────
def cached_fetch(url: str, cache_key: str, ttl_hours: int = 24) -> Optional[dict]:
    cache_file = CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime < timedelta(hours=ttl_hours):
            return json.loads(cache_file.read_text())
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            cache_file.write_text(json.dumps(data))
            return data
    except Exception as e:
        print(f"⚠️ Fetch failed {cache_key}: {e}")
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    return None

def fetch_eps_trend() -> EPSTrend:
    """Fetch TSMC quarterly EPS from FinMind"""
    # Use the same cache key as dashboard
    data = cached_fetch("", "financial_agent_quarterly_margins_2330", 168)
    if not data or "data" not in data:
        # Fallback: fetch directly
        url = "https://api.finmindtrade.com/api/v4/data"
        params = {
            "dataset": "TaiwanStockFinancialStatements",
            "data_id": "2330",
            "start_date": "2020-01-01",
        }
        import requests
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
        else:
            return EPSTrend(quarters=[], eps_values=[], yoy_growth=[])

    # Parse from quarterly margins cache structure
    # The cached data has "data" key with quarterly margins dict
    quarters = []
    eps_values = []

    if isinstance(data.get("data"), dict):
        for (year, quarter), vals in sorted(data["data"].items()):
            eps = vals.get("eps")
            if eps is not None:
                quarters.append(f"{year}Q{quarter}")
                eps_values.append(float(eps))
                eps_values.append(float(eps))
    elif isinstance(data.get("data"), list):
        eps_records = [r for r in data["data"] if r.get("type") == "EPS" and r.get("value") is not None]
        eps_records.sort(key=lambda x: x["date"])
        quarters = [r["date"][:7] for r in eps_records]
        eps_values = [float(r["value"]) for r in eps_records]

    if not eps_values:
        return EPSTrend(quarters=[], eps_values=[], yoy_growth=[])

    yoy = []
    for i in range(len(eps_values)):
        if i >= 4 and eps_values[i-4] > 0:
            yoy.append((eps_values[i] - eps_values[i-4]) / eps_values[i-4] * 100)
        else:
            yoy.append(None)

    # 3-year CAGR (12 quarters)
    cagr = None
    if len(eps_values) >= 12:
        start = eps_values[-12]
        end = eps_values[-1]
        if start > 0:
            cagr = (end / start) ** (1/3) - 1

    return EPSTrend(
        quarters=quarters[-12:],
        eps_values=eps_values[-12:],
        yoy_growth=yoy[-12:],
        cagr_3y=cagr * 100 if cagr else None,
        latest_quarter=quarters[-1] if quarters else "",
        latest_eps=eps_values[-1] if eps_values else 0,
    )

def fetch_capex_guidance() -> list[CAPEXGuidance]:
    """Fetch CAPEX from SEC XBRL for Big Tech (simplified - uses cached data)"""
    # In production, fetch from SEC EDGAR XBRL
    # For now, return structured known data
    return [
        CAPEXGuidance("Microsoft", "2026Q1", 30.88, 3.3, 59.3, "Maintain high AI investment"),
        CAPEXGuidance("Google", "2026Q1", 35.67, 28.1, 49.0, "Accelerate AI infrastructure"),
        CAPEXGuidance("Amazon", "2026Q1", 44.20, 11.8, 26.0, "AWS capacity expansion"),
        CAPEXGuidance("Meta", "2026Q1", 19.00, -11.1, 1.0, "Efficiency focus, AI selective"),
    ]

def fetch_n2_timeline() -> N2Timeline:
    """N2 timeline from company guidance / industry reports"""
    # In production: parse from TSMC earnings calls, tech conferences
    return N2Timeline(
        risk_production="2025 H2 (guided)",
        volume_production="2026 H1 (guided)",
        yield_status="On track per 2024 Q4 call",
        latest_update="2025-01-16 (Q4 2024 earnings)",
        source="TSMC Earnings Call Transcript",
    )

def fetch_foreign_ownership() -> ForeignOwnership:
    """Fetch foreign ownership % from TWSE"""
    data = cached_fetch("", "tsmc_foreign_ownership", 168)
    if not data or "data" not in data:
        return ForeignOwnership(0, 0, 0, [], [])

    df = data["data"]
    foreign = sorted(df, key=lambda x: x["date"])

    dates = [r["date"] for r in foreign]
    values = [float(r["ForeignInvestmentSharesRatio"]) for r in foreign]

    current = values[-1] if values else 0
    monthly_chg = values[-1] - values[-22] if len(values) >= 22 else 0
    yearly_chg = values[-1] - values[-252] if len(values) >= 252 else 0

    return ForeignOwnership(
        current_pct=current,
        monthly_change=monthly_chg,
        yearly_change=yearly_chg,
        trend_12m=values[-252:] if len(values) >= 252 else values,
        dates_12m=dates[-252:] if len(dates) >= 252 else dates,
    )


def fetch_current_price() -> float:
    """Fetch current TSMC price from Yahoo Finance"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return float(price)
    except Exception:
        pass
    return CURRENT_PRICE


def calculate_fair_value(eps: EPSTrend, current_price: float) -> FairValueRange:
    """Calculate fair value range based on forward EPS × PE bands"""
    # Forward EPS estimation methods:
    # 1. Latest quarter annualized (conservative)
    # 2. Trailing 4Q sum (historical)
    # 3. Consensus forward estimates (ideal but needs API)
    #
    # Use latest quarter * 4 as forward proxy (conservative, assumes current run rate)
    latest_q_eps = eps.latest_eps if eps.latest_eps > 0 else (eps.eps_values[-1] if eps.eps_values else 0)
    forward_eps = latest_q_eps * 4

    # Also calculate based on trailing 4Q for reference
    trailing_4q_eps = sum(eps.eps_values[-4:]) if len(eps.eps_values) >= 4 else forward_eps

    fair_low = forward_eps * FAIR_PE_LOW
    fair_high = forward_eps * FAIR_PE_HIGH

    upside_low = (fair_low - current_price) / current_price * 100
    upside_high = (fair_high - current_price) / current_price * 100

    if current_price < fair_low:
        assessment = "UNDERVALUED"
    elif current_price > fair_high:
        assessment = "OVERVALUED"
    else:
        assessment = "FAIR"

    return FairValueRange(
        forward_eps=round(forward_eps, 1),
        pe_low=FAIR_PE_LOW,
        pe_high=FAIR_PE_HIGH,
        fair_low=round(fair_low, 1),
        fair_high=round(fair_high, 1),
        current_price=current_price,
        upside_low_pct=round(upside_low, 1),
        upside_high_pct=round(upside_high, 1),
        assessment=assessment,
    )


def fetch_earnings_signals() -> list[EarningsCallSignal]:
    """
    Fetch TSMC earnings call signals.
    Note: No free API for transcripts. This uses cached/known data.
    In production, integrate with Seeking Alpha, Motley Fool, or SEC 8-K filings.
    """
    # Cache key for earnings signals
    cache_key = "tsmc_earnings_signals"
    cached = cached_fetch("", cache_key, 720)  # 30-day cache

    if cached and "data" in cached:
        signals = []
        for s in cached["data"]:
            signals.append(EarningsCallSignal(**s))
        # Sort by date descending (latest first)
        signals.sort(key=lambda x: x.date, reverse=True)
        return signals

    # Fallback: known recent signals from TSMC earnings calls
    # These should be updated after each quarterly call
    signals = [
        EarningsCallSignal(
            quarter="2025Q2",
            date="2025-07-17",
            capex_guidance="2025 CAPEX may exceed $42B upper end given AI demand strength",
            n2_yield="N2 risk production H2 2025 confirmed, volume production 2026 H1",
            customer_visibility="AI accelerator demand stronger than forecast, CoWoS still tight",
            key_quotes=[
                "CAPEX flexibility to the upside",
                "N2 on schedule",
            ],
            sentiment="POSITIVE",
        ),
        EarningsCallSignal(
            quarter="2025Q1",
            date="2025-04-17",
            capex_guidance="2025 CAPEX maintained at $38-42B, no change from Jan guidance",
            n2_yield="N2 risk production H2 2025 on track, early customer engagement started",
            customer_visibility="AI demand remains robust, smartphone/PC seasonal recovery",
            key_quotes=[
                "No change to CAPEX outlook",
                "N2 yield learning curve meeting internal targets",
            ],
            sentiment="NEUTRAL",
        ),
        EarningsCallSignal(
            quarter="2024Q4",
            date="2025-01-16",
            capex_guidance="2025 CAPEX $38-42B (record high), driven by AI/HPC demand",
            n2_yield="N2 risk production on track for H2 2025, yield learning progressing well",
            customer_visibility="Strong demand visibility through 2025, AI accelerator demand exceeding expectations",
            key_quotes=[
                "AI-related demand is real and accelerating",
                "N2 development progressing as planned",
                "CoWoS capacity to more than double in 2025",
            ],
            sentiment="POSITIVE",
        ),
    ]

    # Save to cache
    cache_file = CACHE_DIR / f"{cache_key}.json"
    cache_file.write_text(json.dumps({"data": [asdict(s) for s in signals]}, ensure_ascii=False, indent=2))

    # Sort by date descending
    signals.sort(key=lambda x: x.date, reverse=True)
    return signals


def assess_earnings_signals(signals: list[EarningsCallSignal]) -> tuple[list[str], list[str]]:
    """Extract risks and catalysts from earnings signals"""
    risks = []
    catalysts = []

    if not signals:
        return risks, catalysts

    latest = signals[0]

    # Sentiment
    if latest.sentiment == "POSITIVE":
        catalysts.append(f"Latest call ({latest.quarter}): Management tone positive")
    elif latest.sentiment == "NEGATIVE":
        risks.append(f"Latest call ({latest.quarter}): Management tone cautious")

    # CAPEX guidance
    if "exceed" in latest.capex_guidance.lower() or "increase" in latest.capex_guidance.lower():
        catalysts.append(f"CAPEX guidance raised: {latest.capex_guidance[:80]}...")
    elif "maintain" in latest.capex_guidance.lower() or "no change" in latest.capex_guidance.lower():
        catalysts.append(f"CAPEX guidance maintained at high level: {latest.capex_guidance[:80]}...")
    elif "cut" in latest.capex_guidance.lower() or "reduce" in latest.capex_guidance.lower():
        risks.append(f"CAPEX guidance cut: {latest.capex_guidance[:80]}...")

    # N2 yield
    if "on track" in latest.n2_yield.lower() or "progressing" in latest.n2_yield.lower():
        catalysts.append(f"N2 timeline on track: {latest.n2_yield[:80]}...")
    elif "delay" in latest.n2_yield.lower() or "issue" in latest.n2_yield.lower():
        risks.append(f"N2 timeline risk: {latest.n2_yield[:80]}...")

    # Customer visibility
    if "strong" in latest.customer_visibility.lower() or "exceed" in latest.customer_visibility.lower():
        catalysts.append(f"Demand visibility strong: {latest.customer_visibility[:80]}...")
    elif "weak" in latest.customer_visibility.lower() or "slow" in latest.customer_visibility.lower():
        risks.append(f"Demand visibility weakening: {latest.customer_visibility[:80]}...")

    return risks, catalysts


# ──────────────────────────────────────────────
# Assessment Engine
# ──────────────────────────────────────────────
def assess_long_term(snap: LongTermSnapshot) -> tuple[str, list[str], list[str]]:
    risks = []
    catalysts = []

    # EPS CAGR check
    if snap.eps.cagr_3y and snap.eps.cagr_3y >= 15:
        catalysts.append(f"EPS 3Y CAGR {snap.eps.cagr_3y:.1f}% > 15% hurdle")
    elif snap.eps.cagr_3y and snap.eps.cagr_3y < 10:
        risks.append(f"EPS 3Y CAGR {snap.eps.cagr_3y:.1f}% below 10%")

    # CAPEX trend
    growing_capex = sum(1 for c in snap.capex if c.yoy_change > 0)
    if growing_capex >= 3:
        catalysts.append(f"{growing_capex}/4 big tech CAPEX growing YoY")
    else:
        risks.append("Big tech CAPEX momentum slowing")

    # N2 timeline
    if "On track" in snap.n2.yield_status:
        catalysts.append("N2 risk production on track for 2025 H2")
    else:
        risks.append("N2 timeline uncertainty")

    # Foreign ownership
    if snap.foreign_ownership.yearly_change > 0:
        catalysts.append(f"Foreign ownership +{snap.foreign_ownership.yearly_change:.1f}pp YoY")
    elif snap.foreign_ownership.yearly_change < -2:
        risks.append(f"Foreign ownership {snap.foreign_ownership.yearly_change:.1f}pp YoY decline")

    # Fair value assessment
    if snap.fair_value.assessment == "UNDERVALUED":
        catalysts.append(f"Fair value: UNDERVALUED ({snap.fair_value.upside_high_pct:+.1f}% upside to high band)")
    elif snap.fair_value.assessment == "OVERVALUED":
        risks.append(f"Fair value: OVERVALUED ({snap.fair_value.upside_low_pct:+.1f}% downside to low band)")

    # Earnings signals
    earn_risks, earn_catalysts = assess_earnings_signals(snap.earnings_signals)
    risks.extend(earn_risks)
    catalysts.extend(earn_catalysts)

    # Overall assessment
    score = len(catalysts) - len(risks)
    if score >= 2:
        assessment = "BULLISH"
    elif score <= -1:
        assessment = "BEARISH"
    else:
        assessment = "NEUTRAL"

    return assessment, risks, catalysts

    # Overall assessment
    score = len(catalysts) - len(risks)
    if score >= 2:
        assessment = "BULLISH"
    elif score <= -1:
        assessment = "BEARISH"
    else:
        assessment = "NEUTRAL"

    return assessment, risks, catalysts

# ──────────────────────────────────────────────
# Dashboard Renderer
# ──────────────────────────────────────────────
def render_dashboard(snap: LongTermSnapshot) -> str:
    lines = []
    lines.append("═" * 70)
    lines.append("  📈 TSMC LONG-TERM MONITOR (3-5 YEAR HORIZON)")
    lines.append(f"  Generated: {snap.timestamp}")
    lines.append("═" * 70)
    lines.append("")

    # Assessment Banner
    badge = {"BULLISH": "🟢", "NEUTRAL": "🟡", "BEARISH": "🔴"}[snap.assessment]
    lines.append(f"  {badge} STRUCTURAL ASSESSMENT: {snap.assessment}")
    lines.append("")

    # 1. EPS Trend
    lines.append("  ┌─ EPS TRAJECTORY ────────────────────────────────────────────┐")
    lines.append(f"  │ Latest Quarter: {snap.eps.latest_quarter}  |  EPS: {snap.eps.latest_eps:.2f}  │")
    if snap.eps.cagr_3y:
        lines.append(f"  │ 3-Year CAGR: {snap.eps.cagr_3y:.1f}%  │")
    lines.append("  │ Recent Quarters:  " + "  │")
    for q, e, y in zip(snap.eps.quarters[-4:], snap.eps.eps_values[-4:], snap.eps.yoy_growth[-4:]):
        yoy_str = f"{y:+.1f}%" if y is not None else "N/A"
        lines.append(f"  │   {q}: {e:.2f}  (YoY: {yoy_str})  │")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    # 2. Big Tech CAPEX
    lines.append("  ┌─ BIG TECH CAPEX (AI DEMAND PROXY) ────────────────────────┐")
    for c in snap.capex:
        trend = "📈" if c.yoy_change > 0 else "📉"
        lines.append(f"  │ {trend} {c.company:10s} {c.latest_quarter}: ${c.capex_billion_usd:.2f}B  "
                     f"(QoQ: {c.qoq_change:+.1f}%  YoY: {c.yoy_change:+.1f}%)")
        if c.guidance_next_quarter:
            lines.append(f"  │     Guidance: {c.guidance_next_quarter}")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    # 3. N2 Timeline
    lines.append("  ┌─ N2 NODE TIMELINE (MOAT DEFENDER) ────────────────────────┐")
    lines.append(f"  │ Risk Production:    {snap.n2.risk_production or 'N/A'}")
    lines.append(f"  │ Volume Production:  {snap.n2.volume_production or 'N/A'}")
    lines.append(f"  │ Yield Status:       {snap.n2.yield_status}")
    lines.append(f"  │ Last Update:        {snap.n2.latest_update} ({snap.n2.source})")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    # 5. Fair Value Range
    lines.append("  ┌─ FAIR VALUE RANGE (EPS × PE) ───────────────────────────────┐")
    fv = snap.fair_value
    badge_fv = {"UNDERVALUED": "🟢", "FAIR": "🟡", "OVERVALUED": "🔴"}[fv.assessment]
    lines.append(f"  │ {badge_fv} Assessment: {fv.assessment}")
    # Calculate trailing 4Q for reference
    trailing_4q = sum(snap.eps.eps_values[-4:]) if len(snap.eps.eps_values) >= 4 else fv.forward_eps
    lines.append(f"  │ Forward EPS (latest Q × 4): {fv.forward_eps:.1f}  |  Trailing 4Q EPS: {trailing_4q:.1f}")
    lines.append(f"  │ PE Band: {fv.pe_low}x – {fv.pe_high}x  |  Fair Value: {fv.fair_low:,.1f} – {fv.fair_high:,.1f}")
    lines.append(f"  │ Current Price: {fv.current_price:,.1f}  |  Upside/Downside: {fv.upside_low_pct:+.1f}% to {fv.upside_high_pct:+.1f}%")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    # 6. Earnings Call Signals
    lines.append("  ┌─ EARNINGS CALL SIGNALS ────────────────────────────────────┐")
    if snap.earnings_signals:
        latest = snap.earnings_signals[0]
        badge_es = {"POSITIVE": "🟢", "NEUTRAL": "🟡", "NEGATIVE": "🔴"}[latest.sentiment]
        lines.append(f"  │ Latest: {latest.quarter} ({latest.date})  {badge_es} {latest.sentiment}")
        lines.append(f"  │ CAPEX Guidance:     {latest.capex_guidance[:60]}...")
        lines.append(f"  │ N2 Yield:           {latest.n2_yield[:60]}...")
        lines.append(f"  │ Demand Visibility:  {latest.customer_visibility[:60]}...")
        if latest.key_quotes:
            for q in latest.key_quotes[:2]:
                lines.append(f"  │   \"{q[:60]}...\"")
    else:
        lines.append("  │  (No earnings signals cached)")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    # 7. Foreign Ownership
    lines.append("  ┌─ FOREIGN OWNERSHIP (STRUCTURAL FLOW) ─────────────────────┐")
    lines.append(f"  │ Current: {snap.foreign_ownership.current_pct:.2f}%  │")
    lines.append(f"  │ Monthly Change: {snap.foreign_ownership.monthly_change:+.2f}pp  │")
    lines.append(f"  │ Yearly Change:  {snap.foreign_ownership.yearly_change:+.2f}pp  │")
    if snap.foreign_ownership.trend_12m:
        min_v = min(snap.foreign_ownership.trend_12m)
        max_v = max(snap.foreign_ownership.trend_12m)
        lines.append(f"  │ 12M Range: {min_v:.2f}% - {max_v:.2f}%  │")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    # 8. Risks & Catalysts
    lines.append("  ┌─ KEY RISKS ────────────────────────────────────────────────┐")
    for r in snap.key_risks:
        lines.append(f"  │ ⚠️  {r}")
    if not snap.key_risks:
        lines.append("  │  (None identified)")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    lines.append("  ┌─ CATALYSTS ────────────────────────────────────────────────┐")
    for c in snap.catalysts:
        lines.append(f"  │ ✅  {c}")
    if not snap.catalysts:
        lines.append("  │  (None identified)")
    lines.append("  └─────────────────────────────────────────────────────────────┘")
    lines.append("")

    lines.append("═" * 70)
    lines.append("  💡 DECISION FRAMEWORK: Adjust only if structural variables shift.")
    lines.append("  💡 Short-term foreign selling / price action = noise for 3-5Y holder.")
    lines.append("═" * 70)

    return "\n".join(lines)

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def run_once() -> LongTermSnapshot:
    """Run one monitoring cycle and return snapshot"""
    print("🔄 Fetching long-term structural data...")

    eps = fetch_eps_trend()
    capex = fetch_capex_guidance()
    n2 = fetch_n2_timeline()
    foreign = fetch_foreign_ownership()
    current_price = fetch_current_price()
    fair_value = calculate_fair_value(eps, current_price)
    earnings_signals = fetch_earnings_signals()

    snap = LongTermSnapshot(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        eps=eps,
        capex=capex,
        n2=n2,
        foreign_ownership=foreign,
        fair_value=fair_value,
        earnings_signals=earnings_signals,
        assessment="",
        key_risks=[],
        catalysts=[],
    )

    assessment, risks, catalysts = assess_long_term(snap)
    snap.assessment = assessment
    snap.key_risks = risks
    snap.catalysts = catalysts

    output = render_dashboard(snap)
    print(output)

    # Save JSON for programmatic use
    out_file = CACHE_DIR / f"longterm_snapshot_{datetime.now().strftime('%Y%m%d')}.json"
    out_file.write_text(json.dumps(asdict(snap), ensure_ascii=False, indent=2, default=str))
    print(f"\n💾 Snapshot saved to {out_file}")

    return snap


def run_daemon():
    """Run continuously, executing every Monday at 08:00"""
    print("🤖 Long-term monitor daemon started. Runs every Monday 08:00.")
    print("   Press Ctrl+C to stop.")
    while True:
        now = datetime.now()
        # Next Monday 08:00
        days_ahead = (7 - now.weekday()) % 7  # Monday = 0
        if days_ahead == 0 and now.hour >= 8:
            days_ahead = 7
        next_run = (now + timedelta(days=days_ahead)).replace(hour=8, minute=0, second=0, microsecond=0)
        sleep_seconds = (next_run - now).total_seconds()

        print(f"⏰ Next run: {next_run.strftime('%Y-%m-%d %H:%M')} (in {sleep_seconds/3600:.1f} hours)")
        time.sleep(sleep_seconds)

        try:
            run_once()
        except Exception as e:
            print(f"❌ Run failed: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TSMC Long-term Investment Monitor")
    parser.add_argument("--schedule", action="store_true", help="Run once (for cron/systemd)")
    parser.add_argument("--daemon", action="store_true", help="Run continuously, every Monday 08:00")
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        run_once()


if __name__ == "__main__":
    main()