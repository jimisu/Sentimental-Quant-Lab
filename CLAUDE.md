# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Common Development Commands

### Environment Setup
```bash
python3 -m venv venv              # create main virtual environment
source venv/bin/activate           # macOS / Linux
pip install -r requirements.txt    # install all dependencies
```

### Run Scripts

#### Main Dashboard
```bash
python tsmc_signal_dashboard.py     # runs the TSMC signal dashboard with rich output
python tsmc_signal_dashboard.py --test  # run self-diagnostics (env, network, API checks)
```

#### Standalone Agents
```bash
python tsmc_financial_agent.py                          # standalone financial analysis
python tsmc_macro_agent.py [--tw-price PRICE]           # standalone macro analysis
python test.py                                           # latest TSMC price via Yahoo Finance
python finmind_tsmc.py [--token TOKEN] [--output-dir DIR]  # 1-year TSMC data via FinMind API
python sentiment_engine.py                               # VaderSentiment example
python test_openrouter_models.py                         # OpenRouter model benchmark (needs OPENROUTER_API_KEY)
```

#### Testing & Linting
```bash
# No test suite currently configured; pytest is available as a dev dependency
# No linting config yet; ruff or black can be introduced later
```

## High-Level Architecture

The repository is a quantitative analysis lab focused on TSMC (2330.TW) that combines:
1. **Data Acquisition** — Fetching fundamental and market data from FinMind, TWSE, Yahoo Finance, SEC
2. **Analysis Engine** — Multi-agent system for financial, technical, institutional, and macro analysis
3. **Signal Dashboard** — Terminal-based visualization using the `rich` library

### Data Flow

```
FinMind API ──┬── TaiwanStockMonthRevenue ──→ monthly revenue YoY
              ├── TaiwanStockFinancialStatements ──→ quarterly margins
              └── TaiwanStockInstitutionalInvestorsBuySell ──→ chip data

TWSE API ─────┬── STOCK_DAY (2330) ──→ daily OHLCV for TSMC
              └── FMTQIK ──→ daily market-wide trading value

Yahoo Finance ──→ TSM ADR price + USD/TWD rate
SEC EDGAR XBRL ──→ big-tech CAPEX data (7 companies)

All sources ──→ local_cache/ (JSON, circular, 3 copies per key)
                    ↓
          tsmc_signal_dashboard.py (main entry point)
                    ↓
          Orchestrator.run_full_analysis()
                    ↓
    ┌──────────┬──────────┬──────────┬──────────┐
    │Financial │Technical │  Chip    │  Macro   │
    │  Agent   │  Agent   │  Agent   │  Agent   │
    └──────────┴──────────┴──────────┴──────────┘
                    ↓
          Composite Score + Dashboard + analysis_log.md
```

### Core Components

#### 1. Data Acquisition Layer

- **`tsmc_signal_dashboard.py`** (lines ~560–730) — TWSE API client with session management, retry logic, and 24-hour TTL caching for past months. Only the current month triggers live TWSE requests.
- **`finmind_tsmc.py`** — FinMind API client for TSMC fundamental data (revenue, margins, financial statements). Supports `--token` for higher rate limits.
- **`data_cache.py`** — Unified TTL cache layer (`fetch_with_cache()`). Policies defined in `DATA_POLICIES` dict (e.g., `monthly_revenue` = 24h, `quarterly_margins` = 7d, `twse_daily` = 0).
- **`test.py`** — Lightweight Yahoo Finance client for real-time TSMC price.

#### 2. Analysis Engine (`tsmc_ai_agents.py`)

All technical indicator logic lives in `MarketDynamicsAgent`. The class is organized into these sections:

| Section | Methods | Purpose |
|---------|---------|---------|
| **Indicator Calculation** | `_calculate_rsi()`, `_calculate_kd()`, `_calculate_macd()`, `_enrich_indicators()` | Core math; `_enrich_indicators()` adds all MA/BB/KD columns to a DataFrame |
| **Chart Plotting** | `_generate_technical_chart()`, `_plot_price_chart()`, `_plot_volume_chart()`, `_plot_oscillator_chart()`, `_plot_macd_chart()` | 4-panel matplotlib chart (price+BB / volume / RSI+KD / MACD) |
| **Signal Detection** | `_format_reversal_signals()`, `_format_20ma_deviation()`, `_check_ma_convergence()`, `_format_kd_status()`, `_add_kd_penalties()`, `_detect_support_resistance()`, `_bollinger_bandwidth()` | All scoring/penalty logic and threshold checks |
| **Sentiment Output** | `analyze_sentiment()` | Orchestrates all indicators → scores dict + report string + tech_flags |

**Scoring system**: Penalties accumulate in `{"early", "short", "mid", "long"}` buckets. Final score per bucket = `max(0, 100 - penalty)`. Composite = `early*0.10 + short*0.10 + mid*0.15 + long*0.15 + chip*0.25 + macro*0.25`.

**Technical indicators implemented**:
- Moving averages: 5MA, 20MA, 60MA + weekly MA12 + monthly MA12
- Bollinger Bands (20, 2) with bandwidth squeeze detection
- RSI (14) — daily + weekly divergence
- KD stochastic (9, 3) — overbought/oversold + golden/death cross
- MACD (12, 26, 9) — daily + weekly death cross
- Support/resistance (60-day high/low)
- Volume-price divergence (swing high comparison)
- K-line patterns (long upper shadow, bearish engulfing, small bodies)
- MA alignment (bullish/bearish/transition)

**Other agents**:
- **`QuarterlyFinancialAgent`** (imported from `tsmc_financial_agent.py`) — Quarterly margin trend analysis with QoQ change detection
- **`InstitutionalInvestorAgent`** — Foreign/trust/dealer buy-sell tracking; 3-institution resonance detection; 5-day cumulative analysis
- **`GlobalMacroAgent`** (imported from `tsmc_macro_agent.py`) — ADR premium/discount, big-tech CAPEX trends from SEC filings
- **`Orchestrator`** — Runs all 4 agents, computes composite score, detects trend reversal (basic + advanced), writes `analysis_log.md`

#### 3. Signal Dashboard (`tsmc_signal_dashboard.py`)

- **Color logic**: Yellow = single warning (YoY < 20% or margin decline > 2pp); Red = multiple/consecutive warnings; Green = healthy
- **Market sentiment**: 3-day consecutive volume decline for both TSMC AND market index → red alert
- **Summary**: 🔴 減碼 / 🟡 觀察 / 🟢 加碼

#### 4. Caching System

- **`local_cache/`** — JSON-based filesystem cache, gitignored
- **Circular policy**: Keeps only the 3 most recent copies per cache key
- **TWSE cache**: Past months use 24h TTL; current month always re-fetched
- **FinMind cache**: Via `data_cache.py` policies (24h for revenue, 7d for financial statements)

## Repository Layout

| File | Purpose |
|------|---------|
| `tsmc_signal_dashboard.py` | Main entry point: data fetching + dashboard output + Orchestrator invocation |
| `tsmc_ai_agents.py` | All 4 AI agents + Orchestrator + all technical indicator logic |
| `tsmc_financial_agent.py` | QuarterlyFinancialAgent (standalone runnable) |
| `tsmc_macro_agent.py` | GlobalMacroAgent (standalone runnable) |
| `finmind_tsmc.py` | FinMind API client |
| `data_cache.py` | Unified TTL cache layer |
| `test.py` | Yahoo Finance price check |
| `sentiment_engine.py` | VaderSentiment utility |
| `config.py` | Configuration constants |
| `setup_env.py` | Environment setup helper |
| `local_cache/` | API response cache (gitignored) |
| `charts/` | Generated technical + chip charts (auto-cleaned to latest per day) |
| `analysis_log.md` | Historical analysis records (Markdown) |

## Key Dependencies
- **Data Fetching**: requests, httpx, pandas
- **Visualization**: rich (terminal), matplotlib (plotting with PingFang HK CJK font)
- **Caching**: Built-in JSON-based filesystem cache
- **Sentiment**: VaderSentiment (via `sentiment_engine.py`)

## Development Notes
1. The dashboard is designed to be run standalone for quick market inspection
2. All data fetching includes error handling for network/API failures
3. Agent analyses are deterministic based on input data — no external ML models
4. Output is terminal-only by design; no files written unless caching or explicit save
5. For deeper analysis, import functions from component scripts rather than modifying dashboard
6. Charts directory stores technical and chip analysis visualizations (auto-cleaned to latest per day)
7. **Never disclose model/provider identity** — only use the name OWL
8. FinMind token via `FINMIND_TOKEN` env var; TWSE has intermittent CDN security blocks (handled by retry + cache fallback)
