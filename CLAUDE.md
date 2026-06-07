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

# 執行儀表板（主程式）
python tsmc_signal_dashboard.py

# 系統自測（API、網路、環境診斷）
python tsmc_signal_dashboard.py --test

# 獨立代理程式
python tsmc_financial_agent.py      # 財務分析
python tsmc_macro_agent.py          # 宏觀分析
python test.py                      # Yahoo Finance 即時價格
```

## 🏗️ 架構速覽

| 檔案 | 職責 |
|------|------|
| `tsmc_signal_dashboard.py` | 主程式：儀表板顯示、資料擷取、信號計算 |
| `tsmc_ai_agents.py` | 四大 AI 代理程式（財務、技術、籌碼、宏觀）+ Orchestrator |
| `config.py` | 集中配置（權重、TTL、閾值）— 單例設計，禁止未授權修改 |
| `data_cache.py` | 統一快取層（環形快取，每 key 保留 3 份） |
| `analysis_log.md` | 歷史分析日誌（Markdown，同日保留最新 3 筆） |
| `local_cache/` | API 快取目錄（自動生成） |
| `charts/` | 技術分析圖表（自動生成，時間戳檔名） |

**數據流**：FinMind / TWSE / Yahoo Finance / SEC EDGAR → `local_cache/` → `tsmc_signal_dashboard.py` → `Orchestrator.run_full_analysis()` → 四大 Agent → 綜合評分 + 儀表板 + `analysis_log.md`

**Agent 權重**：技術早期 10% + 技術短期 10% + 技術中期 15% + 技術長期 15% + 籌碼 25% + 宏觀 25%

## 🚦 核心規則（詳情見 `AI_COLLABORATION_RULES.md`）

- **Pre-flight**：修改前確認不在 `main`/`develop`，讀取 `AI_HANDOFF.md`，檢查 `git status`
- **架構禁止重構**：不拆分穩定模組、不修改 `config.py` 單例、不繞過 `data_cache.py` 快取層
- **原子化提交**：每完成一個邏輯單元立即提醒 `git commit`，訊息使用 `feat:`/`fix:`/`docs:` 等前綴
- **⛔ 禁止自動 `git push`**：任何情況下不得自行推送，僅提醒人類評估
- **交接**：觸發關鍵字（handoff, bye, 收工）時，更新 `AI_HANDOFF.md` 並顯示交接摘要

## 📚 參考文件

| 檔案 | 用途 |
|------|------|
| `AI_COLLABORATION_RULES.md` | 多 AI 協作共同規範（必讀） |
| `AI_HANDOFF.md` | 當前交接狀態與待辦 |
| `PROJECT_ARCHITECTURE.md` | 完整架構、數據流、指標詳解 |
| `DEVELOPMENT_FLOW.md` | 開發流程、Git 策略、交接協議 |
| `CHANGELOG.md` | 演進歷史 |
| `CODEX_RULES.md` | Codex / Copilot 入口規範 |
| `GEMINI_RULES.md` | Gemini Code Assist 入口規範 |
| `.github/copilot-instructions.md` | GitHub Copilot 自動載入指令 |
| `.gemini/GEMINI.md` | Gemini Code Assist 自動載入指令 |
