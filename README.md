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

## 📈 Long-term Investment Monitor (3-5 Year Horizon)

A structural monitor that filters out short-term noise and tracks only the variables that matter for multi-year holders:

| Structural Variable | Source | Threshold |
|---------------------|--------|-----------|
| EPS 3Y CAGR | FinMind Financial Statements | > 15% |
| Big-Tech CAPEX YoY | SEC XBRL (MSFT, GOOGL, AMZN, META) | ≥3/4 growing |
| N2 Node Timeline | TSMC Earnings Calls | On track for risk prod H2 2025 |
| Earnings Call Tone | Cached transcripts | POSITIVE/NEUTRAL/NEGATIVE |
| Fair Value Range | Forward EPS × PE 25-30x | Within band = FAIR |
| Foreign Ownership YoY | TWSE Shareholding | Decline < 2pp |

### Three Usage Modes

```bash
# 1️⃣ One-shot run (manual / cron)
python long_term_monitor.py --schedule

# 2️⃣ Cron job (runs every Monday 08:00)
0 8 * * 1 cd /path/to/Sentimental-Quant-Lab && python long_term_monitor.py --schedule >> logs/longterm_monitor.log 2>&1

# 3️⃣ Daemon mode (runs continuously, auto-executes every Monday 08:00)
python long_term_monitor.py --daemon &
```

**Outputs:**
- Terminal: Colour-coded dashboard with assessment (BULLISH/NEUTRAL/BEARISH), fair value, risks & catalysts
- JSON: `local_cache/longterm_snapshot_YYYYMMDD.json` for programmatic use

**Post-Earnings Maintenance:** Update `local_cache/tsmc_earnings_signals.json` after each quarterly call with:
```json
{
  "quarter": "2025Q3",
  "date": "2025-10-16",
  "capex_guidance": "2025 CAPEX 指引內容",
  "n2_yield": "N2 良率/時程更新",
  "customer_visibility": "客戶需求能見度描述",
  "key_quotes": ["關鍵引述 1", "關鍵引述 2"],
  "sentiment": "POSITIVE|NEUTRAL|NEGATIVE"
}
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
| **BlackRock, Inc.** | 0002012383 | 13F-HR | BlackRock, Inc. (core parent, SIC 6211); holdings in `.txt` (50,651 entries, ~$5.7T AUM) |
| **Bridgewater Associates, LP** | 0001350694 | 13F-HR | Ray Dalio founded, direct filing (82 13F-HR filings) |

**Key findings (2026-06-13)**:
- **BlackRock Q1 2026**: TSMC 18,224,186 shares ($61.6B), **增持 +10.6%** vs Q4 2025; total AUM ~$5,723B
- **Bridgewater Q1 2026**: TSMC 1,077,079 shares ($364M), new position
- **Top holdings alignment**: Both hold NVDA, AAPL, MSFT, GOOGL, AMZN, META in top 10

**統一抓取架構（2026-06-14 更新）**:
- **相同 URL 格式**：兩機構都用 `infotable.xml`，統一使用 `curl_cffi` + `impersonate='chrome'`
- **排程（美東時間）**：固定抓取日 2/15, 5/15, 8/15, 11/15；失敗後 24 小時重試；其餘時間用 local cache
- **URL 路徑**：用 accession number 前綴（非 CIK），正確處理 accession 前綴變化
- **Data access**: SEC Archives 封鎖標準 Python requests (HTTP 403)；使用 `curl_cffi` + `impersonate='chrome'` 繞過 TLS 指紋封鎖
- **Cache TTL**: 90 天（2,160 小時），抓取日後自動更新

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
