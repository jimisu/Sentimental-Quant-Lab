---
name: testing-patterns
description: Mocking strategies and common pitfalls for Sentimental-Quant-Lab tests
metadata:
  type: reference
---

# Testing Patterns for Sentimental-Quant-Lab

## Project Architecture Notes

- **config.py**: Singleton `CONFIG = AnalysisConfig()`. Dataclasses with `field(default_factory=...)` for nesting. Use fresh instances in fixtures (not the global) for isolation.
- **data_cache.py**: Filesystem-based cache. Uses real files in tests via `tempfile.TemporaryDirectory`. No mocking of os/file ops needed -- temp dirs are fast enough.
- **signal_engine.py**: Pure calculation logic with zero I/O. SignalEngine.analyze() mutates the `bigtech_signals.score` and `bigtech_signals.warnings` fields in-place on the passed object.

## Key Pitfalls Discovered

### 1. _safe_key collapses consecutive special chars
`_safe_key` uses `re.sub(r"[^A-Za-z0-9_.-]+", "_", ...)` which replaces **consecutive** non-alphanumeric chars with a **single** underscore, then `.strip("_")`. So `"key@#$%!"` becomes `"key"` not `"key_____"`.

### 2. BigTechSignalCalculator combined scoring
When `capex_valid_count=0`, capex_score defaults to 100 (no-data = no-penalty). When `nvda_revenue_yoy=None`, combined = capex_score (CAPEX-only). To test NVDA tiers in isolation, you must set CAPEX to perfect (4/4 growing) so combined = int(100*0.5 + nvda_score*0.5).

### 3. FinancialSignalCalculator penalty caps
Penalties are fixed amounts (not proportional to drop size). Max penalty = -90 (rev -20, declining -10, gross -20, op -20, net -10, 3-rate -10), so minimum score is 10, not 0. Each margin drop has a fixed red/yellow threshold.

### 4. FinancialSignalCalculator returns int, not float
`score` starts as `100` (int) and integer penalties are subtracted. `max(0, score)` returns int. So `isinstance(result.financial_score, float)` fails. Use `(int, float)`.

### 5. Fixture naming collision
In conftest.py, a fixture named `weights()` returns `ScoreWeightsConfig()`. If tests call `weights()` as a function (not as a parameter), they get `NameError`. Use `ScoreWeightsConfig()` directly in tests instead.

### 6. SignalEngine.analyze() mutates bigtech_signals
The method sets `bigtech_signals.score` and `bigtech_signals.warnings` in-place. Tests should check these fields after calling analyze().

## Fixtures in conftest.py

Key fixtures available to all test files:
- `temp_cache_dir` — `tempfile.TemporaryDirectory`, cleaned up after test
- `financial_signals_default`, `financial_signals_weak`, `financial_signals_none`
- `tech_signals_perfect`, `tech_signals_weak`
- `chip_signals_perfect`, `chip_signals_weak`
- `bigtech_signals_perfect`, `bigtech_signals_weak`, `bigtech_signals_no_nvda`
- `market_sentiment_perfect`, `market_sentiment_weak`
- All config fixtures: `config`, `weights`, `cache_config`, etc.
- `sample_cache_data`, `stale_timestamp`, `fresh_timestamp`

## Running Tests

```bash
python3 -m pytest -v            # All tests
python3 -m pytest -v -k "..."   # Filtered
```

**Always use `python3`**, not just `python` (system may not have venv activated).
