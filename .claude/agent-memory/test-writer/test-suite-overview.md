---
name: test-suite-overview
description: Overview of the 194-test suite for Sentimental-Quant-Lab
metadata:
  type: project
---

# Test Suite Overview

**194 tests across 4 files, all passing (0.51s run time).**

## Files

| File | Tests | Covers |
|------|-------|--------|
| `conftest.py` | 0 (fixtures) | Shared fixtures: config instances, signal data classes, temp cache dir, timestamps |
| `test_config.py` | 42 | All dataclass configs, global singleton, weight sums, as_dict(), isolation |
| `test_data_cache.py` | 58 | CachePolicy, DATA_POLICIES, _safe_key, read/write cache, fetch_with_cache, ring buffer eviction, TTL |
| `test_signal_engine.py` | 94 | FinancialSignalCalculator, BigTechSignalCalculator, ComprehensiveScoreCalculator, AlertLevelDetector, SignalEngine pipeline |

## Key Coverage Areas

### config.py
- All 8 sub-config dataclasses and their defaults
- Global CONFIG singleton
- ScoreWeightsConfig.as_dict() method
- Main weights sum to 1.0, sub-weights sum to 0.35
- Instance isolation (no shared mutable state)

### data_cache.py
- All 8 DATA_POLICIES entries and their TTL values
- _safe_key sanitization (alphanumeric preserved, special chars replaced, leading/trailing _ stripped)
- read_cache: hit, miss, stale, fresh, zero TTL, corrupt JSON, missing cached_at, invalid ISO format
- write_cache: file creation, metadata, ring buffer eviction (keep_count=3 and keep_count=1)
- fetch_with_cache: cache hit skips fetch, miss triggers fetch, TTL=0 always fetches, stale triggers refetch
- get_policy_ttl: valid and invalid policy names

### signal_engine.py
- FinancialSignalCalculator: revenue YoY penalties, margin drop penalties, 3-rate deterioration, boundary values, score clamping
- BigTechSignalCalculator: CAPEX ratio tiers (100/75/50/25), NVDA revenue YoY tiers, combined scoring, NVDA=None fallback
- ComprehensiveScoreCalculator: weighted math verification, custom weights, tech sub-weighting, breakdown sum
- AlertLevelDetector: green/yellow/red thresholds, reversal advanced forces red, reversal basic upgrades yellow to red, double warning
- SignalEngine pipeline: full analysis, reversal detection, double warning, field population, bigtech score mutation

## Gaps (not yet covered)
- tsmc_signal_dashboard.py (display/fetching layer)
- tsmc_ai_agents.py (AI agent orchestration)
- tsmc_financial_agent.py (standalone agent)
- tsmc_macro_agent.py (standalone agent)
