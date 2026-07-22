# Backtest Core Modules 文檔

`backtest_core/` 是量化回測框架的核心模組套件，將四個回測腳本的共通邏輯模組化、去重複，提供統一的資料載入、指標計算、訊號分析、群集化、評估、模擬與報表功能。

---

## 📁 模組結構

```
backtest_core/
├── __init__.py              # 套件入口，統一匯出所有公開 API
├── data_loader.py           # 快取資料載入器
├── eps_calculator.py        # EPS 時間線與 TTM P/E 計算
├── technical_indicators.py  # 技術指標與日報酬計算
├── signal_analyzer.py       # 領先指標與崩盤訊號分析器
├── cluster.py               # 觸發日群集化
├── evaluator.py             # 回測評估指標 (TP/FP/FN, Precision/Recall/F1)
├── simulator.py             # 策略模擬器 (避險、機會成本、買回分析)
├── buyback_analyzer.py      # 買回機會專項分析
└── reporting.py             # 報告生成與列印工具
```

---

## 🔧 各模組功能詳解

### 1. `data_loader.py` - 快取資料載入器

**用途**：統一管理四大回測腳本共用的 JSON 快取檔案讀取邏輯。

**主要類別**：
- `CachedDataPaths` - 資料路徑設定（dataclass，可自訂路徑）
- `BacktestDataLoader` - 載入器主類，支援 lazy loading 與內部快取
- `load_all_cached_data()` - 便利函數，一次載入所有資料

**支援的快取檔案**：
| 屬性 | 預設路徑 | 說明 |
|------|----------|------|
| `inst_rows` | `local_cache/hcd_finmind_inst_rows_2330_*.json` | 三大法人買賣超原始資料 |
| `shareholding` | `local_cache/hcd_finmind_shareholding_2330_*.json` | 外資持股 |
| `ohlc` | `local_cache/hcd_yahoo_ohlcv_2330.TW_*.json` | OHLCV 價量資料 |
| `wide_fin` | `local_cache/finmind_TaiwanStockFinancialStatements_2330_wide_*.json` | 寬表財報 |

**使用範例**：
```python
from backtest_core import BacktestDataLoader, load_all_cached_data

# 方式 1：使用預設路徑
data = load_all_cached_data()
inst_rows = data["inst_rows"]

# 方式 2：自訂路徑
loader = BacktestDataLoader(CachedDataPaths(
    inst_rows="custom/path/inst.json",
    shareholding="custom/path/shareholding.json",
    ...
))
data = loader.load_all()
```

---

### 2. `eps_calculator.py` - EPS 時間線與本益比計算

**用途**：從 FinMind 寬表財報建構 EPS 時間線，支援 as-of 日期查詢近四季 EPS 並計算 TTM P/E。

**主要類別與函數**：
- `QuarterlyEPS` - 單季 EPS 記錄（季底日、可得日、年份、季度、EPS 值）
- `EPSTimeline` - EPS 時間線管理器
  - `from_wide_financial()` - 從寬表資料建構
  - `from_cache_file()` - 從快取檔案載入
  - `get_eps_asof(asof)` - 查詢截至 asof 可得的近四季 EPS
- `compute_trailing_pe(close, eps_dict)` - 計算 TTM P/E
- `build_price_lookup(ohlc_data)` - 建構收盤價查表
- `build_shareholding_lookup(shareholding_data)` - 建構外資持股查表
- `get_foreign_shares_asof(data, asof, fallback)` - 取得 as-of 外資持股（張）
- `build_price_dataframe_asof(ohlc_data, asof)` - 建構相容 signal_engine 的價格 DataFrame

**關鍵邏輯**：
- 季報發布時滯：季底 + 50 天視為「可得」（可配置）
- TTM EPS = 近四季 EPS 總和（以可得日排序取最新四季）
- P/E = 收盤價 / TTM EPS

---

### 3. `technical_indicators.py` - 技術指標工具

**用途**：提供日報酬率、近 N 日最大跌幅、價格資料框等共用技術計算。

**主要類別與函數**：
- `PriceDataFrame` - 標準化價格資料框容器
  - `from_ohlc(ohlc_data, asof)` - 從 OHLC 建構
  - `get_recent_closes(n)` - 取最近 N 日收盤價
  - `get_max_single_day_drop_pct(window)` - 近 N 日最大單日跌幅%
- `TechnicalSnapshot` - 單日技術面快照
- `compute_daily_returns(close_dict)` - 計算每日報酬率%
- `build_price_lookup()` - 建構收盤價查表
- `get_foreign_shares_asof()` - 取得外資持股
- `get_price_dataframe_asof()` - 建構價格 DataFrame（別名）
- `build_technical_snapshots()` - 批次建構技術面快照列表

---

### 4. `signal_analyzer.py` - 領先指標與崩盤訊號分析器

**用途**：封裝 `signal_engine` 的計算邏輯，提供三種領先指標版本與完整崩盤訊號分析。

**主要類別**：

#### `LeadingIndicatorConfig` - 參數設定
```python
@dataclass
class LeadingIndicatorConfig:
    pe_threshold: float = 30.0       # P/E 門檻
    sell_pct_threshold: float = 0.01 # 外資賣超佔比門檻 (1%)
    max_drop_pct: float = 5.0        # 近5日最大跌幅門檻
    window_days: int = 60            # 觀察窗口天數
```

#### `LeadingIndicatorAnalyzer` - 領先指標分析器
三種計算模式對應三個回測腳本：
| 方法 | 對應腳本 | 特點 |
|------|----------|------|
| `compute_for_date()` | `leading_indicator_backtest.py` | 標準版，使用 signal_engine 原版邏輯 |
| `compute_optimized_for_date()` | `leading_indicator_crash_avoidance_backtest.py` | 優化版，PE 門檻可調、分母固定用外資持股 |
| `compute_strict_for_date()` | `backtest_pe30_crash_avoidance.py` | 嚴格版，PE > 30 固定、不降門檻 |

#### `CrashSignalAnalyzer` - 崩盤訊號分析器
對應 `backtest_crash_signals.py`，針對崩盤日前一交易日執行完整四大面向分析：
- 財務面（as-of 真實季報三率、營收 YoY）
- 大廠基本面（NVDA 營收 YoY）
- 技術面（四周期分數、轉折旗標）
- 籌碼面（外資買賣超、連續賣超、兩月淨賣超佔持股比）

**輸出**：`CrashSignalResult` - 包含綜合/籌碼燈號、各細項分數、強制紅燈判定、預警旗標等完整資訊。

---

### 5. `cluster.py` - 觸發日群集化

**用途**：將連續或間隔較短的觸發日合併為群集，避免單日雜訊產生過多獨立訊號。

**主要類別**：
- `TriggerCluster` - 群集資料結構（起迄日、觸發日列表、代表日、代表價、持續天數）
- `TriggerClusterer` - 群集化器
  - `max_gap_days` - 群集內允許最大間隔（預設 3 天）
  - `min_cluster_size` - 最小群集大小（預設 1）
  - `cluster(triggered_days, all_trading_days)` - 執行群集化

**便利函數**：`cluster_triggers(triggered_days, all_trading_days, max_gap=3)`

---

### 6. `evaluator.py` - 回測評估指標

**用途**：計算預警群集對崩盤日的預測效能指標。

**主要類別**：
- `EvaluationResult` - 評估結果（TP/FP/FN、Precision/Recall/F1、詳細明細）
- `BacktestEvaluator` - 評估器
  - `warning_window` - 預警窗口（群集結束後 N 日內算有效預警，預設 10）
  - `crash_threshold` - 崩盤門檻（單日跌幅 ≤ 此值視為崩盤，預設 -5%）
  - `evaluate(clusters, crash_dates, all_trading_days, daily_returns)` - 執行評估

**判定邏輯**：
- **TP**：群集結束日後 `warning_window` 日內發生崩盤
- **FP**：群集結束日後 `warning_window` 日內**無**崩盤
- **FN**：崩盤日前**無**任何群集預警

---

### 7. `simulator.py` - 策略模擬器

**用途**：模擬基於預警群集的避險策略表現。

**主要類別**：
- `SimulatedTrade` - 單筆模擬交易記錄
- `SimulationResult` - 模擬彙總結果
- `StrategySimulator` - 模擬器
  - `warning_window` - 持有天數（預設 10）
  - `cooldown_days` - 交易冷卻期（預設 5）
  - `buyback_window` - 離場後觀察買回機會天數（預設 20）
  - `simulate(clusters, crash_dates, all_trading_days, close_prices, daily_returns)`

**模擬邏輯**：
1. 每個群集結束日 = 賣出/避險點
2. 持有至 `warning_window` 後或下一群集開始前
3. 計算期間損益、是否避開崩盤、機會成本
4. **買回分析**：離場後 `buyback_window` 內是否有更低價買回

**便利函數**：
- `simulate_strategy(...)` - 一鍵模擬
- `print_simulation(result, label)` - 格式化列印

---

### 8. `buyback_analyzer.py` - 買回機會專項分析

**用途**：獨立的買回機會深度分析（`backtest_pe30_crash_avoidance.py` 的核心功能模組化）。

**主要類別**：
- `BuybackResult` - 單群集買回分析
- `BuybackSummary` - 彙總統計
- `BuybackAnalyzer` - 分析器
  - `buyback_window` - 觀察窗口（預設 20）
  - `analyze(clusters, all_trading_days, close_prices)`

**分析指標**：
- 買回成功率：最低價 < 觸發日收盤價的比例
- 平均最大回檔幅度
- 平均最低價出現天數（第幾個交易日）
- 期間回升超過觸發價比例

**便利函數**：
- `analyze_buyback_opportunity(...)`
- `print_buyback_analysis(summary, window)`

---

### 9. `reporting.py` - 報告生成工具

**用途**：統一的評估結果、模擬結果、買回分析報表生成與列印。

**主要函數**：
- `print_evaluation(result, label)` - 列印評估指標表（含 TP/FP/FN 明細）
- `print_simulation(result, label)` - 列印模擬交易明細
- `print_buyback_analysis(summary, window)` - 列印買回分析
- `generate_markdown_report(...)` - 生成完整 Markdown 報告字串
- `save_markdown_report(content, filepath)` - 儲存 Markdown 檔案

---

## 📦 來源腳本對照表

| backtest_core 模組 | 來源腳本 | 提取功能 |
|-------------------|----------|----------|
| `data_loader.py` | 4 支腳本共通 | JSON 快取載入、路徑管理 |
| `eps_calculator.py` | 4 支腳本共通 | EPS 時間線、TTM P/E、查表函數 |
| `technical_indicators.py` | 4 支腳本共通 | 日報酬、最大跌幅、價格 DataFrame |
| `signal_analyzer.py` | `leading_indicator_backtest.py`<br>`leading_indicator_crash_avoidance_backtest.py`<br>`backtest_pe30_crash_avoidance.py`<br>`backtest_crash_signals.py` | 三版領先指標、崩盤訊號完整分析 |
| `cluster.py` | 3 支領先指標腳本 | 觸發日群集化 |
| `evaluator.py` | `leading_indicator_crash_avoidance_backtest.py`<br>`backtest_pe30_crash_avoidance.py` | TP/FP/FN、Precision/Recall/F1 |
| `simulator.py` | `leading_indicator_crash_avoidance_backtest.py`<br>`backtest_pe30_crash_avoidance.py` | 策略模擬、買回分析 |
| `buyback_analyzer.py` | `backtest_pe30_crash_avoidance.py` | 專項買回機會分析 |
| `reporting.py` | 3 支腳本共通 | 表格列印、Markdown 生成 |

---

## 🚀 使用範例：重構後的回測腳本

```python
#!/usr/bin/env python3
"""重構版：領先指標回測"""

from backtest_core import (
    BacktestDataLoader, load_all_cached_data,
    EPSTimeline, compute_trailing_pe,
    LeadingIndicatorAnalyzer, LeadingIndicatorConfig,
    TriggerClusterer, cluster_triggers,
    BacktestEvaluator, evaluate_clusters,
    StrategySimulator, simulate_strategy,
    BuybackAnalyzer, analyze_buyback_opportunity,
    print_evaluation, print_simulation, print_buyback_analysis,
)

# 1. 載入資料
data = load_all_cached_data()
inst_rows = data["inst_rows"]
shareholding = data["shareholding"]
ohlc = data["ohlc"]
wide_fin = data["wide_fin"]

# 2. 建構 EPS 時間線
eps_timeline = EPSTimeline.from_wide_financial(wide_fin)

# 3. 建構分析器
analyzer = LeadingIndicatorAnalyzer(
    eps_timeline=eps_timeline,
    inst_rows=inst_rows,
    shareholding_data=shareholding,
    ohlc_data=ohlc,
    config=LeadingIndicatorConfig(pe_threshold=30.0),  # 嚴格版
)

# 4. 掃描歷史
all_trading_days = sorted(
    d for d in set(r["date"] for r in inst_rows)
    if d in {r["date"] for r in ohlc} and d in {r["date"] for r in shareholding}
)

triggered_days = []
for d in all_trading_days:
    li = analyzer.compute_strict_for_date(d)
    if li.triggered:
        triggered_days.append({"date": d, "close": close_lookup[d]})

# 5. 群集化
clusters = cluster_triggers(triggered_days, all_trading_days, max_gap=3)

# 6. 評估
crash_dates = [("2024-07-26", -5.62), ("2024-08-02", -5.94), ...]
evaluator = BacktestEvaluator(warning_window=10)
eval_result = evaluator.evaluate(clusters, crash_dates, all_trading_days, daily_returns)
print_evaluation(eval_result, "嚴格版 PE>30")

# 7. 模擬
sim = StrategySimulator(warning_window=10, cooldown_days=5, buyback_window=20)
sim_result = sim.simulate(clusters, crash_dates, all_trading_days, close_lookup, daily_returns)
print_simulation(sim_result, "嚴格版 PE>30")

# 8. 買回分析
buyback = analyze_buyback_opportunity(clusters, all_trading_days, close_lookup)
print_buyback_analysis(buyback, 20)
```

---

## ✅ 重構效益

1. **去重複**：四支腳本共用 ~500 行重複程式碼，現集中於 `backtest_core`
2. **可測試**：每個模組獨立、可單元測試
3. **可擴充**：新增領先指標版本只需擴充 `LeadingIndicatorAnalyzer`
4. **統一介面**：所有回測腳本使用相同的評估、模擬、報表 API
5. **維護性**：修改邏輯只需改一處，所有腳本自動受惠

---

## 📝 後續遷移計畫

- [ ] 將 `leading_indicator_backtest.py` 重構為使用 `backtest_core`
- [ ] 將 `leading_indicator_crash_avoidance_backtest.py` 重構
- [ ] 將 `backtest_pe30_crash_avoidance.py` 重構
- [ ] 將 `backtest_crash_signals.py` 重構（部分邏輯不同，需保留獨特資料抓取）
- [ ] 新增 `test_backtest_core.py` 單元測試