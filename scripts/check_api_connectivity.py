#!/usr/bin/env python3
"""
API Connectivity & SAL Validation Probe
======================================
Sends REAL requests through the SAL layer to verify that:
  1. Each provider's endpoint URL + parameters are correct (not just mocked).
  2. The response parses into the expected DTO / structure.
  3. Network + TLS (incl. SEC curl_cffi bypass) actually work.

Routes everything through `sal` (get_finmind / get_twse / get_yahoo / get_sec)
so a failure here is a failure of the REAL integration, not the unit tests.

Usage:
    source venv/bin/activate
    python scripts/check_api_connectivity.py          # all probes
    python scripts/check_api_connectivity.py --no-cache # ignore local_cache, force fetch
    python scripts/check_api_connectivity.py --only yahoo,twse

Exit code: 0 = all reached; 1 = at least one critical failure.
"""
import argparse
import os
import sys
import time
from typing import Callable, Dict, List, Tuple

# Make sure we import the repo's `sal`, not anything else on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env so FINMIND_TOKEN / FRED_API_KEY are available (no-op if absent).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Probe:
    def __init__(self, name: str, fn: Callable[[], str], critical: bool = True):
        self.name = name
        self.fn = fn
        self.critical = critical


def _yahoo_probe() -> str:
    from sal import get_yahoo
    y = get_yahoo()
    adr = y.get_tsmc_adr_price()
    fx = y.get_usd_twd_rate()
    if adr is None or fx is None:
        raise AssertionError(f"Yahoo returned None (adr={adr}, fx={fx})")
    return f"TSM ADR=${adr:.2f}, USD/TWD={fx:.4f}"


def _twse_probe() -> str:
    from sal import get_twse
    from datetime import date
    t = get_twse()
    ym = date.today().strftime("%Y%m")
    daily = t.get_stock_day("2330", ym)
    if not daily:
        raise AssertionError("TWSE STOCK_DAY returned no rows")
    last = daily[-1]
    return f"STOCK_DAY {ym}: {len(daily)} rows, last close={last.close}"


def _finmind_probe() -> str:
    from sal import get_finmind
    token = os.getenv("FINMIND_TOKEN")
    if not token:
        raise SystemExit("SKIP: FINMIND_TOKEN not set in env")
    f = get_finmind()
    rev = f.get_monthly_revenue("2330", months=3)
    if not rev:
        raise AssertionError("FinMind monthly revenue returned empty")
    r0 = rev[-1]
    return f"MonthlyRevenue last={r0.year}/{r0.month} revenue={r0.revenue:,.0f} (Yoy={r0.yoy_pct})"


def _sec_submissions_probe() -> str:
    from sal import get_sec
    # BlackRock core parent CIK (per project memory)
    s = get_sec()
    data = s.get_submissions("0002012383")
    if not data or "filings" not in data:
        raise AssertionError("SEC submissions missing 'filings'")
    forms = data["filings"]["recent"]["form"]
    n_13f = sum(1 for x in forms if x == "13F-HR")
    return f"SEC submissions OK, 13F-HR filings found={n_13f}"


def _sec_13f_probe() -> str:
    from sal import get_sec
    # Known BlackRock 13F accession (illustrative; may 403 on some networks).
    s = get_sec()
    xml = s.get_13f_holdings("0002012383", "0002012383-26-001841")
    low = (xml or "").lower()
    # Real SEC XML uses the camelCase element <informationTable> and the
    # namespace .../thirteenf/informationtable — NOT the literal "INFORMATION TABLE".
    if not xml or "infotable" not in low or "taiwan semiconductor" not in low:
        raise AssertionError("SEC 13F infotable missing expected content")
    return f"SEC 13F infotable fetched ({len(xml)} chars)"


def _fred_probe() -> str:
    import requests
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise SystemExit("SKIP: FRED_API_KEY not set in env")
    url = "https://api.stlouisfed.org/fred/series/observations"
    r = requests.get(url, params={
        "series_id": "CPIAUCSL", "api_key": key,
        "file_type": "json", "limit": "5", "sort_order": "desc",
    }, timeout=20)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        raise AssertionError("FRED returned no observations")
    return f"FRED CPIAUCSL latest={obs[0]['date']}={obs[0]['value']}"


def build_probes() -> List[Probe]:
    return [
        Probe("Yahoo Finance (TSM ADR / USD-TWD)", _yahoo_probe),
        Probe("TWSE STOCK_DAY (2330)", _twse_probe),
        Probe("FinMind monthly revenue", _finmind_probe, critical=False),
        Probe("SEC EDGAR submissions", _sec_submissions_probe),
        Probe("SEC 13F infotable (curl_cffi)", _sec_13f_probe, critical=False),
        Probe("FRED CPI (needs key)", _fred_probe, critical=False),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of probe names (substring match)")
    ap.add_argument("--no-cache", action="store_true",
                    help="set all cache TTLs to 0 to force a real fetch")
    args = ap.parse_args()

    if args.no_cache:
        import sal.providers as p
        # Force fresh fetches for this probe run.
        for fn in ("_read_fresh_cache", "_read_latest_cache"):
            setattr(p, fn, lambda *a, **k: None)

    probes = build_probes()
    if args.only:
        wanted = {w.strip().lower() for w in args.only.split(",")}
        probes = [p for p in probes if any(w in p.name.lower() for w in wanted)]

    results: List[Tuple[str, str, float, str]] = []
    failures = 0
    for pr in probes:
        t0 = time.time()
        try:
            msg = pr.fn()
            dt = time.time() - t0
            results.append((pr.name, "OK", dt, msg))
        except SystemExit as e:
            dt = time.time() - t0
            results.append((pr.name, "SKIP", dt, str(e)))
        except Exception as e:
            dt = time.time() - t0
            results.append((pr.name, "FAIL", dt, f"{type(e).__name__}: {e}"))
            if pr.critical:
                failures += 1

    w = max(len(r[0]) for r in results)
    print("\n" + "=" * (w + 40))
    print("API CONNECTIVITY PROBE — routed through SAL")
    print("=" * (w + 40))
    for name, status, dt, msg in results:
        print(f"{name:<{w}}  {status:<4}  {dt:5.2f}s  {msg}")
    print("=" * (w + 40))
    skipped = sum(1 for r in results if r[1] == "SKIP")
    print(f"Summary: {len(results)-failures-skipped} ok, {failures} critical fail, {skipped} skip")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
