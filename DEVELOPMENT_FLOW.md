# 多 AI 協作開發流程規範 (DEVELOPMENT_FLOW)

本專案採用多 AI 工具（Gemini Code Assist, GitHub Copilot/Codex, Claude Code）輪流協作模式。為了確保系統架構的穩定性、程式碼的一致性以及開發歷史的可追蹤性，所有參與開發的 AI 代理程式必須嚴格遵守 `AI_COLLABORATION_RULES.md` 與以下四大規範。

---

## 0. 開發指令速查 (CLI Commands)

### 環境設定
```bash
python3 -m venv venv              # 建立虛擬環境
source venv/bin/activate           # 啟動環境
pip install -r requirements.txt    # 安裝依賴
```

### 執行主程式
```bash
python tsmc_signal_dashboard.py     # 執行儀表板
python tsmc_signal_dashboard.py --test  # 系統診斷自測 (API, 網路, 環境)
```

### 獨立代理程式測試
```bash
python tsmc_financial_agent.py      # 獨立執行財務分析
python tsmc_macro_agent.py          # 獨立執行宏觀分析
python test.py                      # 測試 Yahoo Finance 即時價格
```

---

## 1. 架構防禦 (Architectural Defense)
- **嚴禁擅自重構**：未經使用者明確授權，AI 禁止擅自更動目錄結構、拆分現有穩定模組（例如將 `tsmc_ai_agents.py` 拆分為多個檔案）或修改底層單例設計（如 `config.py` 中的 `CONFIG`）。
- **風格一致性**：新撰寫的程式碼必須遵循現有的編碼模式。例如：
    - 所有的權重與閾值必須從 `config.py` 讀取。
    - 所有的 Agent 執行結果必須回傳一致的數據結構（如 `Tuple[str, Dict, int]`）。
    - 優先維持「單一功能模組化」而非「過度封裝」。

## 2. Git 分支策略 (Git Branching Strategy)
- **受保護的分支**：嚴禁直接在 `main` 或 `develop` 分支上進行任何代碼修改。
- **特性與修復分支**：
    - 開發新功能：必須從最新的 `main` 切出 `feat/功能名稱` 分支。
    - 修復 Bug：必須從最新的 `main` 切出 `fix/問題描述` 分支。
- **合併前置**：在提出合併請求前，AI 必須確保代碼在當前分支能通過 `python tsmc_signal_dashboard.py` 的基本執行測試。

## 3. 原子化提交 (Atomic Commit)
- **微小增量**：每完成一個獨立的邏輯修改、新增一個小功能或修復一個特定錯誤，AI **必須**立即停止後續動作。
- **主動提示**：在確認當前變更無誤後，AI **必須主動提示**使用者進行 `git commit`。
- **規範內容**：提交訊息應包含行為標記（feat, fix, docs, refactor, style）及其具體變更內容。
- **⛔ 禁止自動 `git push`**：詳細規則見 `AI_COLLABORATION_RULES.md` 第 4 節。任何情況下 AI 不得自行推送，必須由人類明確指令方可執行。

## 4. AI 輪班交接 (AI Handoff Protocol)
- **交接檔案**：在切換 AI 開發工具前（或使用者要求時），目前的 AI 必須在根目錄建立或更新 **`AI_HANDOFF.md`**。
- **交接內容**：
    1. **當前狀態**：目前開發的分支與進度。
    2. **已知問題**：開發中遇到的障礙或尚未解決的 Bug。
    3. **下一步指示**：明確建議下一個接手的 AI 應該執行的具體任務。
- **交接關鍵字觸發**：當使用者說出「下班了」、「交班」、「任務結束」、「先這樣」、「暫停」、「收工」、「handoff」、「done for today」、「bye」等關鍵字時，AI **必須自動且主動**執行以下動作：
    1. 檢查當前 Git 分支的所有代碼變更（`git status`、`git diff --stat`）。
    2. 自動更新 `AI_HANDOFF.md`。
    3. 在對話結束前，跳出標準交接提示區塊（詳見 `.claude/HANDOFF_PROMPT.md`）。
- **交接提示模板**：完整的交接流程與提示格式請參閱 `.claude/HANDOFF_PROMPT.md`。
- **⚠️ 絕不靜默離開**：無論對話長短，只要觸發交接關鍵字，就必須完成交接流程並跳出提示。

---

## 執行聲明
當使用者啟動 AI 助手時，AI 應先讀取 `AI_COLLABORATION_RULES.md` 與本文件以同步開發共識。任何違反上述規範的建議，使用者有權拒絕並要求 AI 重新調整。

**版本**: 1.1.0
**最後更新日期**: 2026-06-07
