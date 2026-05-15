# Sentimental-Quant-Lab

A quantitative analysis laboratory that combines **stock market data acquisition** (TSMC/2330.TW) with **sentiment analysis** and **market sentiment detection**.

## 📋 Overview

This repository provides tools to:
- Fetch TSMC's monthly revenue year‑over‑year (YoY) from FinMind.
- Retrieve quarterly gross margin and operating margin from financial statements.
- Detect consecutive three‑day volume declines for both TSMC and the Taiwan weighted index (^TWII) using yfinance.
- Display a colour‑coded dashboard in the terminal using the `rich` library.

## 📂 Project Structure

```
Sentimental-Quant-Lab/
├── tsmc_signal_dashboard.py   # Main script: fetches data, applies logic, prints dashboard
├── requirements.txt           # Python dependencies
├── CLAUDE.md                  # Usage instructions for Claude Code
└── .gitignore                 # Ignore virtual environments, caches, etc.
```

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/jimisu/Sentimental-Quant-Lab.git
cd Sentimental-Quant-Lab

# 2. Create and activate a virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the dashboard
python tsmc_signal_dashboard.py
```

*If you have a FinMind token for higher rate limits, set it as an environment variable:*
```bash
export FINMIND_TOKEN=your_token_here
```

## 📖 Usage Details

### Data Sources
- **Monthly Revenue**: `TaiwanStockMonthRevenue` dataset (FinMind) – calculates YoY change.
- **Quarterly Margins**: `TaiwanStockFinancialStatements` dataset – computes gross margin and operating margin, and quarter‑over‑quarter changes.
- **Volume Data**: `yfinance` – fetches daily volume for `2330.TW` (TSMC) and `^TWII` (Taiwan Weighted Index).

### Colour Logic (Dashboard)
| Indicator | Condition | Colour |
|-----------|-----------|--------|
| **Monthly Revenue YoY** | < 20 % | Yellow |
| | Two consecutive months < 20 % | Red |
| **Gross Margin** | QoQ decline > 2 pp | Yellow |
| **Operating Margin** | QoQ decline > 2 pp | Yellow |
| **Both Margins** | Both QoQ declines > 2 pp | Red |
| **Market Sentiment** | TSMC and ^TWII each show 3‑day consecutive volume decline | Red banner: “市場情緒指標：個股與大盤交易量連三降” |

### Summary Message
After the table, a sentence is printed:
- **Red Alert** → “目前處於紅燈預警，建議減碼並密切監控。”
- **Yellow Alert** → “目前處於黃燈預警，建議啟動階梯式觀察，暫不加碼。”
- **Green** → “目前皆為綠燈，可正常觀察並考慮適度加碼。”

## 🛠️ Requirements

See `requirements.txt`:
```
requests
httpx
rich
pandas
yfinance
```
(Pytest and vaderSentiment were removed as they are not used in the current dashboard.)

## 📝 Notes

- The script automatically handles missing data (e.g., if volume data cannot be retrieved, the market sentiment check is skipped).
- All outputs are printed to the terminal; no files are written by default.
- The dashboard is intended for quick visual inspection; for deeper analysis, modify the script or import its functions.

## 📜 License

MIT © 2026 Jan‑isa
