# Sentimental-Quant-Lab

A quantitative analysis laboratory that combines **TSMC (2330.TW) market data acquisition** with **multi-agent AI analysis** and **technical indicator detection**.

## 📋 Overview

This repository provides tools to:
- Fetch TSMC's monthly revenue YoY from FinMind
- Retrieve quarterly gross margin and operating margin from financial statements
- Analyze technical indicators (Bollinger Bands, RSI, KD, MACD, moving averages)
- Track institutional investor (foreign/trust/dealer) buy-sell dynamics
- Monitor ADR premium/discount and big-tech CAPEX trends from SEC filings
- Track SEC 13F institutional holdings (BlackRock, Bridgewater) with quarterly analysis
- Display a colour-coded dashboard in the terminal using the `rich` library
- Generate 4-panel technical charts (price/volume/RSI+KD/MACD)

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/jimisu/Sentimental-Quant-Lab.git
cd Sentimental-Quant-Lab

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the dashboard
python tsmc_signal_dashboard.py
```

*If you have a FinMind token for higher rate limits:*
```bash
export FINMIND_TOKEN=your_token_here
```

*For SEC 13F institutional holdings tracking (requires `curl_cffi`):*
```bash
pip install curl_cffi
python scripts/fetch_13f_research.py
```

## 📖 Architecture

### Data Sources
| Source | Data | Cache |
|--------|------|-------|
| FinMind API | Monthly revenue, quarterly financials, institutional buy/sell | 24h–7d TTL |
| TWSE API | Daily OHLCV (STOCK_DAY), market trading value (FMTQIK) | 24h for past months |
| Yahoo Finance | TSM ADR price, USD/TWD rate | 1h |
| SEC EDGAR XBRL | Big-tech CAPEX (AMZN, MSFT, NVDA, AAPL, TSLA, GOOGL, META) | 7d |
| SEC EDGAR 13F | Institutional holdings (BlackRock, Bridgewater) | 90d |

### AI Agent System
Four specialized agents collaborate via an Orchestrator:

| Agent | Expertise | Key Indicators |
|-------|-----------|----------------|
| **Financial Agent** | Quarterly margins | Gross/operating/net margin QoQ trends |
| **Technical Agent** | Market dynamics | Bollinger Bands, RSI, KD, MACD, MA alignment, support/resistance |
| **Chip Agent** | Institutional flow | Foreign/trust/dealer 5-day cumulative, 3-institution resonance |
| **Macro Agent** | Global trends | ADR premium, big-tech CAPEX trends |

### SEC 13F Institutional Holdings Tracker

Tracks quarterly 13F filings from major institutional investors:

| Institution | CIK | Form | Notes |
|-------------|-----|------|-------|
| **BlackRock, Inc.** | 0001364742 | 13F-HR | BlackRock Finance, Inc., core corporate CIK (holdings in .txt) |
| **Bridgewater Associates, LP** | 0001350694 | 13F-HR | Ray Dalio founded, direct filing (82 13F-HR filings) |

**Key findings (2026-06-13)**:
- **TSMC divergence**: BlackRock trimmed -4.6% vs Bridgewater new position +1,077,079 shares ($364M)
- **7 common top-10 holdings**: MSFT, NVDA, AAPL, GOOGL, AMZN, META, ISHARES TR
- **Data access**: SEC Archives (`www.sec.gov/Archives/edgar/data/`) blocks standard Python requests (HTTP 403); use `curl_cffi` with `impersonate='chrome'` to bypass TLS fingerprinting
- **Holdings data**: Located in `xslForm13F_X02/infotable.xml` (not `primary_doc.xml` which is the cover page)
- **Cache TTL**: 90 days (2160 hours), sufficient for quarterly updates

Reports are generated to `reports/13f_research_YYYYMMDD.md`.

### Composite Scoring
```
Score = Technical(early)*0.10 + Technical(short)*0.10 + Technical(mid)*0.15
      + Technical(long)*0.15 + Chip*0.25 + Macro*0.25
```

### Colour Logic (Dashboard)
| Indicator | Condition | Colour |
|-----------|-----------|--------|
| **Monthly Revenue YoY** | < 20% | 🟡 Yellow |
| | Two consecutive months < 20% | 🔴 Red |
| **Gross/Operating Margin** | QoQ decline > 2pp | 🟡 Yellow |
| | Both margins declining > 2pp | 🔴 Red |
| **Market Sentiment** | TSMC + market 3-day volume decline | 🔴 Red banner |

## 🛠️ Requirements

```
requests
httpx
rich
pandas
matplotlib
```

## 📝 Notes

- The script automatically handles missing data and API failures with cache fallback
- All outputs are printed to the terminal; charts saved to `charts/`, logs to `analysis_log.md`
- TWSE has intermittent CDN security blocks — handled by retry logic + 24h cache for past months
- Charts are auto-cleaned to latest per day

## 📜 License

MIT © 2026 Jan-isa
