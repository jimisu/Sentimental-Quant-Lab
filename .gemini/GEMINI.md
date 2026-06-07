# Gemini Code Assist 專案指令

你正在參與 `Sentimental-Quant-Lab` 專案。請嚴格遵守以下規範。

## 第一步：讀取上下文（每次 Session 開始時）

在執行任何任務前，依序讀取以下文件：

1. `GEMINI_RULES.md` — Gemini 入口規範
2. `AI_COLLABORATION_RULES.md` — 多 AI 協作共同規範
3. `AI_HANDOFF.md` — 當前交接狀態與待辦事項
4. `PROJECT_ARCHITECTURE.md` — 專案架構與檔案職責

## 核心規則

### Pre-flight Check（修改前必做）
- 確認目前不在 `main` 或 `develop` 分支
- 讀取 `AI_HANDOFF.md` 確認當前狀態
- 檢查 `git status`，若已有未提交變更，不得覆蓋
- 若 `AI_HANDOFF.md` 顯示待辦已完成，引導使用者先提交並評估是否建立 PR（注意：推送必須由人類執行，AI 不自行 push）

### 架構防禦
- 禁止未授權重構（不拆分穩定模組、不修改 `config.py` 單例設計）
- 資料獲取統一經過 `data_cache.py` 快取層
- 配置統一由 `config.py` 管理
- Agent 回傳結構保持一致（`Tuple[str, Dict, int]`）

### 原子化提交
- 每完成一個邏輯單元立即停止並提醒 `git commit`
- 提交訊息使用 `feat:` / `fix:` / `docs:` / `refactor:` / `style:` 前綴
- **⛔ 禁止自動 `git push`**：任何情況下都不得自行推送。即使交接報告建議推送，只能提醒人類評估，**絕不自行執行**。違反視為嚴重錯誤。

### 多 Agent 併發安全
- 同一檔案同時只允許一個 AI 修改
- 不得寫入或覆蓋 `analysis_log.md`（由主程式管理）
- 若發現 `git merge conflict`，不得自行解決，通知人類工程師

### 交接
- 觸發關鍵字（下班、交班、收工、handoff、bye）時，必須更新 `AI_HANDOFF.md` 並顯示交接摘要
- **絕不靜默離開**

## 參考文件
- `DEVELOPMENT_FLOW.md` — 開發流程規範
- `CHANGELOG.md` — 專案演進歷史
