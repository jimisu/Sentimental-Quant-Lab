# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Environment Setup
```bash
python3 -m venv venv              # create main virtual environment
source venv/bin/activate           # macOS / Linux
pip install -r requirements.txt    # install all dependencies
```

### Automatic Environment Setup (Recommended)
To ensure the correct environment is always set up, you can use the environment setup skill:
- Claude Code will automatically detect and suggest running environment setup when needed
- Or manually trigger with: `/skill environment-setup`

## Run Scripts

### Main Dashboard
```bash
python tsmc_signal_dashboard.py     # runs the TSMC signal dashboard with rich output
```

### Utility Scripts
```bash
python test.py                                          # latest TSMC price via Yahoo Finance
python finmind_tsmc.py [--token TOKEN] [--output-dir DIR]  # 1-year TSMC data via FinMind API
python sentiment_engine.py                              # run sentiment analysis example
python test_openrouter_models.py                        # test OpenRouter free models (needs OPENROUTER_API_KEY)
python tsmc_financial_agent.py                          # run financial analysis agent standalone
python tsmc_macro_agent.py [--tw-price PRICE]           # run macro analysis agent standalone
```

### Testing & Linting
```bash
# No test suite currently configured; pytest is available as a dev dependency if tests are added
# No linting config yet; ruff or black can be introduced later
```

## High-Level Architecture

The repository is a quantitative analysis lab focused on TSMC (2330.TW) that combines:
1. **Data Acquisition** - Fetching fundamental and market data from FinMind and TWSE
2. **Analysis Engine** - Multi-agent AI system for financial, technical, institutional, and macro analysis
3. **Signal Dashboard** - Terminal-based visualization using rich library

### Core Components

#### 1. Data Acquisition Layer
- **`finmind_tsmc.py`** - FinMind API client for TSMC fundamental data (revenue, margins, financial statements)
  - Caches responses in `local_cache/` directory to reduce API calls
  - Supports `--token` for higher rate limits and `--output-dir` for custom output paths
  - Outputs JSON and CSV formats
- **`test.py`** - Lightweight Yahoo Finance client for real-time TSMC price
  - Implements retry logic (MAX_RETRIES=3) for reliability
- **TWSE Integration** - Direct TWSE API calls embedded in `tsmc_signal_dashboard.py` for:
  - Daily traded value (成交金額) for TSMC and Taiwan weighted index
  - Last 10 trading days displayed in dashboard

#### 2. Analysis Engine (`tsmc_ai_agents.py`)
Implements four specialized AI agents that collaborate via an Orchestrator:
- **QuarterlyFinancialAgent (財務分析專家)**:
  - Analyzes quarterly gross margin, operating margin, and net profit margin
  - Triggers alerts when QoQ decline exceeds 2% for key metrics
  - Interprets guidance and earnings forecasts
- **MarketDynamicsAgent (技術市場專家)**:
  - Detects volume-price divergence (量價背離) - rising volume with falling price
  - Identifies consecutive volume contraction (連鎖縮量) for stock and market
  - Confirms trends via moving average alignment (5MA, 20MA)
- **InstitutionalInvestorAgent (籌碼分析專家)**:
  - Tracks foreign investment, trust, and dealer買賣超 dynamics
  - Flags Trend-killer signals (continuous foreign selling)
  - Confirms downtrends when large foreign selling combines with technical breakdown
- **GlobalMacroAgent (全球宏觀專家)**:
  - Monitors ADR premium/discount and external market data
  - Tracks big tech CAPEX trends as demand indicators
  - Analyzes currency effects on TSMC ADR pricing

#### 3. Signal Dashboard (`tsmc_signal_dashboard.py`)
- **Primary Interface**: Combines all data sources and agent analyses into a color-coded terminal dashboard
- **Key Indicators**:
  - Monthly Revenue YoY (from FinMind TaiwanStockMonthRevenue)
  - Quarterly Gross Margin & Operating Margin (from financial statements)
  - Market Sentiment: 3-day consecutive traded-value decline for both TSMC and TWSE index
- **Color Logic**:
  - Yellow: Single warning condition (e.g., YoY < 20% or margin decline > 2pp)
  - Red: Multiple/consecutive warnings (e.g., two months YoY < 20% or both margins declining)
  - Green: All indicators healthy
- **Output**: Rich-formatted tables with summary recommendation (減碼/觀察/加碼)

#### 4. Standalone Agent Scripts
- **`tsmc_financial_agent.py`** - Independent execution of financial analysis
- **`tsmc_macro_agent.py`** - Independent execution of macro analysis with optional TWSE price input for ADR analysis

#### 5. Caching System
- **`local_cache/` directory**: Stores API responses to minimize redundant calls
- **Cache Policy**: Keeps only the 3 most recent copies per cache key (CACHE_KEEP=3)
- **Cache Keys**: Generated from request parameters to ensure uniqueness

## Repository Layout

- **`tsmc_signal_dashboard.py`** - Main execution script for the dashboard
- **`tsmc_ai_agents.py`** - Contains the four AI agents and Orchestrator
- **`finmind_tsmc.py`** - FinMind API client for fundamental data
- **`test.py`** - Yahoo Finance client for real-time price
- **`sentiment_engine.py`** - VaderSentiment-based sentiment analysis utility
- **`test_openrouter_models.py`** - OpenRouter model benchmarking tool
- **`tsmc_financial_agent.py`** - Standalone financial analysis agent
- **`tsmc_macro_agent.py`** - Standalone global macro analysis agent
- **`local_cache/`** - Automatic cache of API responses (gitignored)
- **`test_data/`** - Pre-fetched datasets for offline analysis (gitignored)
- **`requirements.txt`** - Project dependencies: requests, httpx, rich, pandas, matplotlib
- **`sentiment_venv/`** - Separate virtual environment for sentiment utilities (gitignored)
- **`charts/`** - Generated visualizations (if any)
- **`analysis_log.md`** - Historical analysis records
- **`.gitignore`** - Excludes virtual environments, caches, and data directories

## Key Dependencies
- **Data Fetching**: requests, httpx, pandas
- **Visualization**: rich (terminal), matplotlib (plotting)
- **Caching**: Built-in JSON-based filesystem cache
- **Sentiment**: VaderSentiment (via sentiment_engine.py)

## Development Notes
1. The dashboard is designed to be run standalone for quick market inspection
2. All data fetching includes error handling for network/API failures
3. Agent analyses are deterministic based on input data - no external ML models
4. Output is terminal-only by design; no files written unless caching or explicit save
5. For deeper analysis, import functions from component scripts rather than modifying dashboard
6. Charts directory stores technical and chip analysis visualizations (auto-cleaned to latest 3 per day)