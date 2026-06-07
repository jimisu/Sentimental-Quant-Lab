# Sentimental-Quant-Lab 專案架構說明

這份文件詳細描述了 Sentimental-Quant-Lab 專案的架構、每個檔案的職責以及 AI 代理程式的功能分工。

## 📁 專案結構概覽

```
Sentimental-Quant-Lab/
├── tsmc_signal_dashboard.py   # 主程式：儀表板顯示與協調中心
├── tsmc_ai_agents.py          # AI 代理程式模組：四大專家代理程式與編排器
├── tsmc_financial_agent.py    # 財務分析代理程式（獨立腳本）
├── tsmc_macro_agent.py        # 全球宏觀代理程式（獨立腳本）
├── finmind_tsmc.py            # FinMind API 客戶端（未在主程式中使用）
├── test.py                    # Yahoo Finance 即時價格客戶端
├── sentiment_engine.py        # 情感分析工具（未在主程式中使用）
├── test_openrouter_models.py  # OpenRouter 模型基準測試工具
├── config.py                  # 配置管理
├── analysis_log.md            # 歷史分析紀錄（Markdown 格式）
├── requirements.txt           # Python 依賴項
├── local_cache/               # API 快取目錄（自動生成）
├── charts/                    # 生成的技術分析圖表（自動生成）
├── test_data/                 # 離線分析的預先擷取資料集（未追蹤）
├── .claude/                   # Claude Code 配置
│   ├── settings.json          # Hooks 和權限設置
│   ├── HANDOFF_PROMPT.md      # AI 輪班交接提示模板
│   └── ...                    # 其他 Claude 相關檔案
├── CLAUDE.md                  # 給 Claude Code 的使用指南
├── README.md                  # 項目概覽和快速開始指南
├── DEVELOPMENT_FLOW.md        # 多 AI 協作開發流程規範
├── AI_HANDOFF.md              # AI 輪班交接報告
├── AI_COLLABORATION_RULES.md  # Gemini/Codex 共用協作規範
├── CODEX_RULES.md             # Codex / GitHub Copilot 入口規範
├── GEMINI_RULES.md            # Gemini Code Assist 入口規範
└── .gitignore                 # Git 忽略檔案
```

## 🔄 數據流架構 (Data Flow)

```
FinMind API ──┬── TaiwanStockMonthRevenue ──→ 月營收 YoY
              ├── TaiwanStockFinancialStatements ──→ 季度毛利/營益/淨利
              └── TaiwanStockInstitutionalInvestorsBuySell ──→ 籌碼資料

TWSE API ─────┬── STOCK_DAY (2330) ──→ 台積電日線 OHLCV
              └── FMTQIK ──→ 大盤每日成交金額

Yahoo Finance ──→ TSM ADR 價格 + USD/TWD 匯率
SEC EDGAR XBRL ──→ 大型科技公司 CAPEX 數據 (4-7 家)

所有來源 ─────→ local_cache/ (JSON, 環形快取, 每個 Key 保留 3 份)
                    ↓
          tsmc_signal_dashboard.py (主程式進入點)
                    ↓
          Orchestrator.run_full_analysis()
                    ↓
    ┌──────────┬──────────┬──────────┬──────────┐
    │ 財務專家  │ 技術專家  │ 籌碼專家  │ 宏觀專家  │
    └──────────┴──────────┴──────────┴──────────┘
                    ↓
          綜合評分 + 儀表板顯示 + analysis_log.md
```

## 🔄 數據流架構 (Data Flow)

```
FinMind API ──┬── TaiwanStockMonthRevenue ──→ 月營收 YoY
              ├── TaiwanStockFinancialStatements ──→ 季度毛利/營益/淨利
              └── TaiwanStockInstitutionalInvestorsBuySell ──→ 籌碼資料

TWSE API ─────┬── STOCK_DAY (2330) ──→ 台積電日線 OHLCV
              └── FMTQIK ──→ 大盤每日成交金額

Yahoo Finance ──→ TSM ADR 價格 + USD/TWD 匯率
SEC EDGAR XBRL ──→ 大型科技公司 CAPEX 數據 (4-7 家)

所有來源 ─────→ local_cache/ (JSON, 環形快取, 每個 Key 保留 3 份)
                    ↓
          tsmc_signal_dashboard.py (主程式進入點)
                    ↓
          Orchestrator.run_full_analysis()
                    ↓
    ┌──────────┬──────────┬──────────┬──────────┐
    │ 財務專家  │ 技術專家  │ 籌碼專家  │ 宏觀專家  │
    └──────────┴──────────┴──────────┴──────────┘
                    ↓
          綜合評分 + 儀表板顯示 + analysis_log.md
```

## 🔧 核心組件功能說明

### 1. 主程式: `tsmc_signal_dashboard.py`

**職責**：
- 作為系統的主要進入點和協調中心
- 負責資料擷取（FinMind、TWSE、Yahoo Finance）
- 執行基本的市場信號計算（營收 YoY、毛利率、營業利益率等）
- 使用 rich 庫產生彩色終端儀表板
- 調用 AI 代理程式編排器進行深度分析
- 支援 `--test` 參數進行系統自測

**主要功能**：
- 月營收年增率 (YoY) 計算（最近 12 個月）
- 季度毛利率、營業利益率、稅後淨利率擷取
- TWSE 近 10 個交易日成交金額表格顯示
- 市場情緒偵測（個股與大盤連續三日成交金額下降）
- 顏色編碼邏輯：黃燈（單一警告）、紅燈（多重/連續警告）、綠燈（所有指標健康）
- 自動調用 `Orchestrator.run_full_analysis()` 進行 AI 深度分析
- 將分析結果附加寫入 `analysis_log.md`

### 2. AI 代理程式模組: `tsmc_ai_agents.py`

**職責**：
- 包含四個專業化的 AI 代理程式和一個編排器（Orchestrator）
- 負責深度市場分析和自動化日誌紀錄
- 每個代理程式專注於特定分析維度

#### 四大 AI 代理程式：

**A. QuarterlyFinancialAgent (財務分析專家)**
- **資料來源**：FinMind 財務報表資料集 (TaiwanStockFinancialStatements)
- **分析邏輯**：
  - 監控毛利率、營業利益率與稅後淨利率之季度趨勢
  - 檢查最新季度是否達成「三率持續上升」之強勢基本面訊號
  - 比較最近三個季度 (Q0 > Q1 > Q2) 判斷趨勢
- **輸出**：
  - 識別持續上升、單季回升或最新下滑的財務指標
  - 提供多頭或警告狀態的結論

**B. MarketDynamicsAgent (技術市場專家)**
**資料來源**：TWSE 每日收盤行情 (STOCK_DAY) 與 大盤統計 (FMTQIK)
**實作細節與指標**：
  - **核心計算方法**：
    - `_calculate_rsi()`, `_calculate_kd()`, `_calculate_macd()`: 核心數學邏輯。
    - `_enrich_indicators()`: 負責將所有 MA/BB/KD 欄位附加至 DataFrame。
  - **技術指標清單**：
    - 均線系統：5MA, 20MA, 60MA + 週線 MA12 + 月線 MA12。
    - 布林通道：(20, 2) 帶寬擠壓偵測 (Squeeze detection)。
    - RSI (14)：日線與週線頂背離偵測。
    - KD (9, 3)：超買/超賣區判定與黃金/死亡交叉。
    - MACD (12, 26, 9)：日線與週線訊號。
    - 支撐阻力：近 60 日高低點。
    - 價量關係：Swing High 的價量背離偵測。
    - K線形態：長上影線、吞噬黑K、連續小實體。
  - **評分機制**：
    - 扣分會累積在 `early`, `short`, `mid`, `long` 四個桶子。
    - 每個維度的最終分數為 `max(0, 100 - penalty)`。
**輸出**：
  - 四面板 Matplotlib 圖表 (價格+BB / 成交量 / RSI+KD / MACD)。
  - 20MA 乖離率分析與反轉訊號判斷。

**C. InstitutionalInvestorAgent (籌碼分析專家)**
- **資料來源**：FinMind 三大法人買賣超資料集 (TaiwanStockInstitutionalInvestorsBuySell)
- **分析邏輯**：
  - 追蹤三大法人（外資、投信、自營商）買賣超行為
  - 連續外資賣超被視為 Trend-killer 訊號
  - 三大法人同步買超則視為籌碼共振
  - 外資近5日累計賣超達1000張時觸發警告
- **輸出**：
  - 籌碼流向圖（外資淨買賣超長條圖）
  - 三大法人近5日累計共振買入分析
  - 外資買賣超趨勢判斷
  - 籠統籌碼分數（基於外資賣超情況）

**D. GlobalMacroAgent (全球宏觀專家)**
- **資料來源**：ADR 溢價/折變、外部市場數據、大型科技 CAPEX 趨勢
- **分析邏輯**：
  - 監控 ADR 溢價/折變與外部市場數據
  - 追蹤大型科技 CAPEX 趨勢作為需求指標
  - 分析貨幣效應對 TSMC ADR 定價的影響
  - 整合多個宏觀因素產出風險評分
- **輸出**：
  - 全球宏觀風險評分（0-100 分）
  - 宏觀市場狀況摘要

#### 編排器: Orchestrator
- **職責**：
  - 統合四大 AI 代理程式的分析結論
  - 計算綜合健康得分（根據預設權重）
  - 生成 Markdown 格式的分析日誌
  - 自動清理日誌（同一天只保留最新 N 筆）
  - 趨勢轉折訊號偵測（20MA 轉負 + 月線破 MA12 + 外資大額賣超）
  - 雙重黃燈警示識別（儀表板黃燈 + 綜合得分 < 60）

**權重分配**：
- 技術早期: 10%
- 技術短期: 10% 
- 技術中期: 15%
- 技術長期: 15%
- 籌碼面: 25%
- 全球宏觀(長期趨勢): 25%

### 3. 獨立代理程式腳本

#### A. `tsmc_financial_agent.py`
- **職責**：獨立執行財務分析
- **核心類別**：`QuarterlyFinancialAgent`
- **使用方式**：`python tsmc_financial_agent.py`
- **功能**：與儀表板中相同的財務分析邏輯，但可獨立運行

#### B. `tsmc_macro_agent.py`
- **職責**：獨立執行全球宏觀分析
- **核心類別**：`GlobalMacroAgent`
- **使用方式**：`python tsmc_macro_agent.py [--tw-price PRICE]`
- **功能**：支援自定義 TWSE 價格進行 ADR 分析

### 4. 資料獲取與快取系統

#### FinMind 數據獲取
- 透過 `fetch_finmind_dataset()` 函數存取
- 支援快取機制以減少 API 呼叫
- 快取策略：同一 cache key 只保留最新 3 份（CACHE_KEEP = 3）
- 財務資料快取最大有效期：7 天

#### TWSE 數據獲取
- 透過 `fetch_twse_report()` 函數存取
- 模擬真實瀏覽器請求以防止被攔截
- 智慧重試機制：遇到安全防護時自動等待並重試
- 自動切換至快取模式作為備援

#### 快取管理
- 目錄：`local_cache/`
- 函數：`write_circular_cache()`, `read_latest_cache()`, `get_cached_data()`
- 自動清理：保持每個 cache key 只有最新的 N 份檔案

### 5. 輔助功能

#### 配置管理: `config.py`
- 中央化配置參數
- 日誌與圖表保留數量控制 (`keep_count`)
- 其他系統參數

#### 圖表生成
- 使用 Matplotlib 生成技術分析與籌碼分析圖表
- 中文字型回退機制解決顯示問題
- 自動清理：每天每種圖只保留最新一張

#### 日誌系統
- 格式：Markdown (analysis_log.md)
- 結構：
  1. 報表標題 (# 🚀 TSMC 量化分析報告 - 時間戳)
  2. 儀表板總結
  3. 綜合健康得分
  4. 四大專家判讀（宏觀、財務、技術、籌碼）
  5. 分隔線
- 自動維護：同一天只保留最新 3 筆紀錄

## 🔄 資料流程

1. **資料擷取階段** (`tsmc_signal_dashboard.py`):
   - FinMind: 月營收 (TaiwanStockMonthRevenue)
   - FinMind: 季度財務報表 (TaiwanStockFinancialStatements) 
   - FinMind: 三大法人買賣超 (TaiwanStockInstitutionalInvestorsBuySell)
   - TWSE: 個股日線 (STOCK_DAY) 
   - TWSE: 大盤成交金額 (FMTQIK)

2. **基礎分析階段** (`tsmc_signal_dashboard.py`):
   - 計算月營收 YoY
   - 整理季度毛利率/營業利益率
   - 準備近 10 日交易資料表格
   - 執行市場情緒偵測（連三降）

3. **AI 深度分析階段** (`tsmc_ai_agents.py`):
   - QuarterlyFinancialAgent: 財務三率趨勢分析
   - MarketDynamicsAgent: 技術面與量價關係分析
   - InstitutionalInvestorAgent: 籌碼流向與法人動向分析
   - GlobalMacroAgent: 全球宏觀風險評估
   - Orchestrator: 權重計分、趨勢偵測、日誌生成

4. **輸出階段**:
   - 終端彩色儀表板顯示
   - 總結建議（減碼/觀察/加碼）
   - Markdown 日誌檔案寫入 (`analysis_log.md`)
   - 技術分析與籌碼圖表生成 (`charts/` 目錄)

## ⚙ 環境與依賴

### 必要依賴 (requirements.txt)
- `requests`: HTTP 客戶端
- `httpx`: HTTP 客戶端（備用）
- `rich`: 終端彩色輸出與表格
- `pandas`: 資料處理與分析

### 選擇性依賴
- `matplotlib`: 圖表生成（用於 AI 代理程式）
- `VaderSentiment`: 情感分析（用於 sentiment_engine.py）

### 虛擬環境
- 主環境: `venv/` (專案根目錄)
- 情感分析環境: `sentiment_venv/` (獨立)

## 📊 顏色邏輯說明

### 儀表板顏色規則 (`tsmc_signal_dashboard.py`)
| 指標 | 條件 | 顏色 |
|------|------|------|
| 月營收 YoY | < 20% | Yellow |
| 月營收 YoY | 連續兩月 < 20% | Red |
| 毛利率 | QoQ 下滑 > 2 pp | Yellow |
| 營業利益率 | QoQ 下滑 > 2 pp | Yellow |
| 兩率同時 | QoQ 下滑 > 2 pp | Red |
| 市場情緒 | 個股+大盤 連三日成交金額下降 | Red 橫幅 |

### 綜合建議
- **紅燈**: 目前處於紅燈預警，建議減碼並密切監控。
- **黃燈**: 目前處於黃燈預警，建議啟動階梯式觀察，暫不加碼。
- **綠燈**: 目前皆為綠燈，可正常觀察並考慮適度加碼。

## 🔧 開發與維護

### 常用命令
```bash
# 執行儀表板
python tsmc_signal_dashboard.py

# 執行系統自測
python tsmc_signal_dashboard.py --test

# 獨立財務分析
python tsmc_financial_agent.py

# 獨立宏觀分析
python tsmc_macro_agent.py [--tw-price PRICE]

# 安裝依賴
pip install -r requirements.txt
```

### 日誌與快取維護
- 日誌檔案: `analysis_log.md` (自動追加，同日保留最新3筆)
- 快取目錄: `local_cache/` (自動管理，無需手動清理)
- 圖表目錄: `charts/` (自動管理，同日每種圖保留最新1張)

## 🤖 多 AI 代理程式協同開發指南

為確保專案在 Gemini Code Assist、Claude Code CLI 和 Codex 之間的協同開發安全且高效，所有代理程式應以 `AI_COLLABORATION_RULES.md` 為共同規範，並遵守以下指南：

### 架構防禦與風格一致性
- **禁止未授權重構**：未經明確授權，不得拆分現有穩定模組（例如不得將 `tsmc_ai_agents.py` 拆分為多個檔案）或修改底層單例設計（如 `config.py` 中的配置）。
- **保持編碼風格一致**：新程式碼必須遵循現有編碼模式：
  - 所有資料獲取必須經過統一快取層 (`data_cache.py`) 而非直接請求外部 API
  - 所有配置必須經由 `config.py` 集中管理
  - 所有 Agent 分析結果必須回傳一致的資料結構（如 `Tuple[str, Dict, int]`）
  - 優先「單一功能模組化」而非「過度封裝」

### Git 分支策略遵守
- **功能開發**：必須從最新的 `main` 切出 `feat/功能名稱` 分支
- **錯誤修復**：必須從最新的 `main` 切出 `fix/問題描述` 分支
- **嚴禁直接在 `main` 或 `develop` 分支上進行任何代碼修改**
- **合併前置**：在提出合併請求前，必須確保代碼在當前分支能通過 `python tsmc_signal_dashboard.py` 的基本執行測試

### 原子化提交原則
- **微小增量**：每完成一個獨立的邏輯修改、新增一個小功能或修復一個特定錯誤，**必須立即停止後續動作並提交**
- **提交訊息規範**：訊息應包含行為標記（feat, fix, docs, refactor, style）及其具體變更內容
- **範例**：`feat: add unified data cache layer with per-type TTL policies`

### AI 輪班交接協議
- **交接檔案**：在切換 AI 開發工具前（或使用者要求時），目前的 AI 必須更新專案根目錄的 `AI_HANDOFF.md`
- **交接內容必須包含**：
  1. **當前狀態**：目前開發的分支與進度
  2. **已知問題**：開發中遇到的障礙或尚未解決的 Bug
  3. **下一步指示**：明確建議下一個接手的 AI 應該執行的具體任務
- **交接觸發關鍵字**：當使用者說出「下班了」、「交班」、「任務結束」等關鍵字時，AI 必須自動執行交接流程
- **開發流程文件**：每次 SessionStart 時自動載入 `AI_COLLABORATION_RULES.md`、`CLAUDE.md`、`AI_HANDOFF.md`、`CHANGELOG.md`、`DEVELOPMENT_FLOW.md`、`PROJECT_ARCHITECTURE.md` 和 `HANDOFF_PROMPT.md`

### 多 Agent 安全協作重點
- **資料競爭避免**：統一快取層 (`data_cache.py`) 使用檔案鎖定機制，確保多 Agent 安全讀寫快取
- **配置單一來源**：所有 TTL、門檻值等設定經由 `config.py` 集中管理，避免配置衝突
- **日誌寫入安全**：`_keep_latest_daily_logs` 函式設計為讀取全部內容後重寫，簡短衝突會被後續寫入覆蓋而不會損壞日誌
- **圖表生成獨立**：`charts/` 目錄使用時間戳檔名策略，即使多 Agent 同時生成也不會檔案衝突

### 效率優化實踐
- **快取層統一**：所有資料獲取（月營收、季報、ADR、CAPEX 等）經過統一快取層，顯著減少重複 API 請求
- **TTL 精細化**：不同資料類型有不同快取策略（月營收 24h、季報 7d、ADR 1h、CAPEX 7d），平衡新鮮度與效率
- **Tiered 執行模式**：儀表板分為 Tier 1（快取命中快速響應）和 Tier 2（需要真實 API 請求）兩層
- **視窗輸出優化**：Matplotlib 字型設定優化為優先使用系統可用的中文字型，減少無效的字型搜尋警告

## 📜 License

MIT © 2026 Jan‑isa
