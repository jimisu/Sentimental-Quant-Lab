# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## 📌 專案概述

Sentimental-Quant-Lab 是一個台積電（2330.TW）量化分析實驗室，結合多數據源抓取、四大 AI 專家代理程式分析與技術指標偵測，產出彩色終端儀表板與 Markdown 分析日誌。

## 🔄 Session 啟動流程

每次啟動 Session 時，依序讀取以下文件：

1. `AI_COLLABORATION_RULES.md` — 多 AI 協作共同規範（Pre-flight、架構防禦、提交規則）
2. `AI_HANDOFF.md` — 當前分支、已完成工作、待辦事項
3. `PROJECT_ARCHITECTURE.md` — 專案架構、檔案職責、數據流
4. `DEVELOPMENT_FLOW.md` — 開發流程規範與常用指令
5. `CHANGELOG.md` — 近期變更歷史

## ⚡ 常用指令

```bash
# 環境設定
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 並填入 API tokens

# 執行儀表板（主程式）
python tsmc_signal_dashboard.py

# 系統自測（API、網路、環境診斷）
python tsmc_signal_dashboard.py --test

# 獨立代理程式
python tsmc_financial_agent.py      # 財務分析
python tsmc_macro_agent.py          # 宏觀分析
python test.py                      # Yahoo Finance 即時價格

# 長期監看板
python long_term_monitor.py         # 完整分析（含排程/常駐模式）
python long_term_monitor.py --schedule  # Cron 模式（單次執行）
python long_term_monitor.py --daemon    # 常駐模式（每週一 08:00 自動執行）

# 機構 13F 追蹤
python tsmc_institutional_tracker.py           # 全機構分析
python tsmc_institutional_tracker.py --list-institutions  # 列出已註冊機構

# 回測與分析腳本（當前分支 fix/chip-red-light-threshold-1pct）
python sell_buyback_backtest.py    # 賣出→20日內買回回測
python sell_below_count.py         # 統計賣出後 20 日低於賣價天數
python stress_test_forced_red.py   # 強制紅燈壓力測試
python backtest_crash_signals.py   # 崩盤訊號回測
python analyze_tech_pattern.py     # 技術型態分析

# 測試套件
python -m pytest                    # 全測試套件（756 passed）
python -m pytest test_sal.py -v     # SAL 服務抽象層測試
python -m pytest test_signal_engine.py -v  # 信號引擎測試
python -m pytest test_institutional_tracker.py -v  # 13F 追蹤器測試
python -m pytest test_dashboard.py -v  # 儀表板測試
```

## 🏗️ 架構速覽

| 檔案 | 職責 |
|------|------|
| `tsmc_signal_dashboard.py` | 主程式：儀表板顯示、資料擷取、基礎信號計算 |
| `tsmc_ai_agents.py` | 四大 AI 代理程式（財務、技術、籌碼、宏觀）+ Orchestrator |
| `signal_engine.py` | **獨立信號引擎**：統一燈號邏輯、綜合得分計算、領先指標 |
| `tsmc_institutional_tracker.py` | 機構法人 13F 持倉追蹤（BlackRock、Bridgewater） |
| `long_term_monitor.py` | 長期投資監看板（排程、估值錨點、法說會關鍵字） |
| `macro_risk.py` | 宏觀風險評分模組（獨立可測試） |
| `config.py` | 集中配置（權重、TTL、閾值）— 單例設計，禁止未授權修改 |
| `data_cache.py` | 統一快取層（環形快取，每 key 保留 3 份） |
| `sal/` | **服務抽象層 (SAL)**：隔離上層判斷邏輯與下層 API 呼叫 |
| `analysis_log.md` | 歷史分析日誌（Markdown，同日保留最新 3 筆） |
| `local_cache/` | API 快取目錄（自動生成，環形快取） |
| `charts/` | 技術分析圖表（自動生成，時間戳檔名） |
| `reports/` | 格式化報告輸出（自動生成） |

### SAL (Service Abstraction Layer) 架構

```
sal/
├── __init__.py           # 公開 API、便利函數、ProviderRegistry
├── interfaces.py         # DTOs + 抽象基類
│   ├── MonthlyRevenue, DailyPrice, QuarterlyMargin, InstitutionalFlow
│   ├── ForeignOwnership, EarningsCallSignal, SEC13FHolding, BigTechCAPEX
│   └── FinancialDataProvider, MarketDataProvider, InstitutionalDataProvider...
├── providers.py          # 具體實作
│   ├── FinMindProvider, TWSEProvider, YahooFinanceProvider
│   ├── SECEdgarProvider (curl_cffi TLS 指紋偽裝), FileCacheProvider
└── (ProviderRegistry 工廠模式)
```

**數據流**：
```
FinMind / TWSE / Yahoo Finance / SEC EDGAR
    ↓
sal/providers.py (Provider 實作)
    ↓
sal/interfaces.py (DTO 統一格式)
    ↓
tsmc_signal_dashboard.py / tsmc_ai_agents.py / tsmc_institutional_tracker.py
    ↓
Orchestrator.run_full_analysis() → 四大 Agent → 綜合評分 + 儀表板 + analysis_log.md
```

**Agent 權重**（`signal_engine.py` 統一管理）：
- 技術早期 10% + 技術短期 10% + 技術中期 15% + 技術長期 15% + 籌碼 25% + 宏觀 25%

## 🚦 核心規則（詳情見 `AI_COLLABORATION_RULES.md`）

- **Pre-flight**：修改前確認不在 `main`/`develop`，讀取 `AI_HANDOFF.md`，檢查 `git status`
- **架構禁止重構**：不拆分穩定模組、不修改 `config.py` 單例、不繞過 `data_cache.py` 快取層、不繞過 SAL Provider
- **原子化提交**：每完成一個邏輯單元立即提醒 `git commit`，訊息使用 `feat:`/`fix:`/`docs:` 等前綴
- **⛔ 禁止自動 `git push`**：任何情況下不得自行推送，僅提醒人類評估
- **交接**：觸發關鍵字（handoff, bye, 收工）時，更新 `AI_HANDOFF.md` 並顯示交接摘要

## 📊 關鍵技術細節

### 信號引擎 (`signal_engine.py`)
- `SignalEngine` 類：統一計算綜合得分、燈號判定、領先指標
- `calculate_composite_score()`：加權聚合六大維度分數
- `determine_light()`：綠燈（≥80）/ 黃燈（60-79）/ 紅燈（<60）
- `calculate_leading_indicator()`：外資近 2 日連續賣超 + 佔持股≥1% + PE>25 → 領先指標觸發

### 燈號計分哲學（`AI_HANDOFF.md` 2026-07-19 記錄）
- 嚴重技術/籌碼弱勢必須拉低燈號
- 外部系統性風險走 `macro_rpy` 而非強制紅燈

### FinMind Token 限制（`AI_HANDOFF.md` 2026-07-19 記錄）
- Token 為 register 等級：價格/大盤指數被擋，外資買賣超可用
- TWSE T86 已 404 → 價格/指數改用 Yahoo Finance

### SEC Archives 403 封鎖（高優先待辦）
- `www.sec.gov` 全站 IP 封鎖，`curl_cffi` 無法解決
- 解法：離線快取下載方案（見 `AI_HANDOFF.md`「🚨 SEC Archives 封鎖問題與解決方案」）
- 需在可存取環境執行下載腳本，將 JSON 放入 `local_cache/`

## 📚 參考文件

| 檔案 | 用途 |
|------|------|
| `AI_COLLABORATION_RULES.md` | 多 AI 協作共同規範（必讀） |
| `AI_HANDOFF.md` | 當前交接狀態與待辦 |
| `PROJECT_ARCHITECTURE.md` | 完整架構、數據流、指標詳解 |
| `DEVELOPMENT_FLOW.md` | CLI 指令速查 + Git 分支策略 |
| `CHANGELOG.md` | 演進歷史 |
| `CODEX_RULES.md` | Codex / Copilot 入口規範 |
| `GEMINI_RULES.md` | Gemini Code Assist 入口規範 |
| `.github/copilot-instructions.md` | GitHub Copilot 自動載入指令 |
| `.gemini/GEMINI.md` | Gemini Code Assist 自動載入指令 |