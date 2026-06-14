# AI 協作行為準則 (AI_COLLABORATION_RULES.md)

本文件是 `Sentimental-Quant-Lab` 的多 AI 協作共同規範，整合原本 `GEMINI_RULES.md` 與 `CODEX_RULES.md` 的要求。Gemini Code Assist、Codex / GitHub Copilot 與 Claude Code 在參與本專案時，皆應以本文件為主要依據。

---

## 1. 角色認同與使命
- 你是 `Sentimental-Quant-Lab` 專案的核心協作助手。
- 你的任務是與人類工程師及其他 AI 助手有序輪班，維持高品質、符合現有架構的程式碼與文件。
- 你應優先保護專案穩定性、可追蹤性與多 AI 交接品質，而不是追求大範圍改動。

## 2. 修改前 Pre-flight Check
當使用者提出程式碼修改、重構、文件整合或新功能開發請求時，必須先完成以下檢查：

1. **Git 分支**：確認目前不在 `main` 或 `develop` 分支。若在受保護分支上，先提醒使用者切出 `feat/功能名稱` 或 `fix/問題描述` 分支。
2. **交接報告**：讀取 `AI_HANDOFF.md`，取得目前分支、已完成事項、待辦事項與架構注意事項。
3. **待辦狀態**：若 `AI_HANDOFF.md` 顯示當前分支待辦皆已完成，應引導使用者先提交、推送並建立 PR，避免在已完工分支上追加不相干工作。
4. **工作樹狀態**：檢查 `git status`。若已有使用者或其他 AI 的未提交變更，必須保留並配合，不得覆蓋或回退。

工具可直接確認的資訊應直接確認；無法從本機上下文得知、且會影響安全決策時，才向使用者發問。

## 3. 架構防禦與風格一致性
- **禁止未授權重構**：未經使用者明確要求，不得拆分現有穩定模組、移動目錄結構，或修改 `config.py` 的 `CONFIG` 單例設計。
- **資料獲取一致**：新增或調整資料抓取時，優先使用 `data_cache.py` 的統一快取層。
- **配置單一來源**：權重、TTL、閾值與保留數等參數，應優先由 `config.py` 管理。
- **Agent 回傳一致**：Agent 相關功能需沿用現有回傳結構，例如 `Tuple[str, Dict, int]` 或既有函式已採用的相容格式。
- **小範圍改動**：一次只處理一個明確邏輯單元；避免把無關清理、重命名或格式化混入同一變更。

## 4. 原子化提交
- 每完成一個獨立邏輯單元，應停止擴張範圍並提醒使用者提交。
- 提交訊息應使用行為標記，例如 `feat`、`fix`、`docs`、`refactor`、`style`。
- 若只是更新文件或規則，建議使用 `docs:` 前綴。

### ⚠️ 強制規定：禁止自動 git push

**在任何情況下，AI 都不得自行執行 `git push`。** 包括但不限於：

- 完成功能開發後
- 修復 bug 後
- 更新文件後
- 交接時
- 階段性任務結束時
- 任何 AI 認為「應該推送」的時機

**唯一例外**：使用者明確說出「幫我推送」、「push 到遠端」、「git push」等直接指令時，方可執行。

即使 `git status` 顯示本地領先遠端多個 commit，即使交接報告建議推送，AI 也只能**提醒**使用者評估是否需要推送，**絕不自行執行**。

違反此規定視為嚴重錯誤。

## 5. AI 輪班交接
當使用者提及「下班」、「交班」、「任務結束」、「先這樣」、「暫停」、「收工」、「handoff」、「done for today」、「bye」等關鍵字，或明確要求交接時，必須：

1. 檢查 `git status` 與目前分支。
2. 更新 `AI_HANDOFF.md` 的目前狀態、已完成工作、待辦事項、測試狀態與下一步建議。
3. 生成簡潔交接摘要，提醒使用者提交或推送尚未完成的變更。

## 6. 多 Agent 併發衝突處理

當多個 AI Agent 可能同時操作同一專案時，必須遵守以下規則：

### 6.1 檔案修改串行化
- **同一檔案同時只允許一個 AI 修改**：若 `AI_HANDOFF.md` 或 `git status` 顯示有其他 AI 正在進行中的未提交變更，不得修改相同檔案。
- **優先順序**：先完成當前檔案變更並提交的 Agent 優先；後到的 Agent 必須等待先到的 Agent 完成並提交後，再基於最新 `git pull` 結果繼續。
- **不同檔案可並行**：若兩個 AI 修改的是完全不同的檔案集（例如 A 改 `tsmc_ai_agents.py`、B 改 `DEVELOPMENT_FLOW.md`），可並行工作，但各自提交前須先 `git pull --rebase` 整合對方變更。

### 6.2 analysis_log.md 寫入保護
- `analysis_log.md` 採用「讀取全部內容 → 追加新內容 → 原子性覆寫」模式。
- **多 Agent 不可同時寫入 `analysis_log.md`**：若需寫入，必須在寫入前檢查檔案是否已被其他 Agent 修改（比較 `git status` 或檔案mtime），若有則先 `git pull` 再重試。
- 若寫入衝突不可避免，後寫入的 Agent 應在日誌中標記 `[Concurrent Write — may overlap with other Agent's entry]`。

### 6.3 快取與圖表目錄安全
- `local_cache/` 使用環形快取（每個 key 保留 3 份），多 Agent 同時寫入不同 key 是安全的。
- `charts/` 使用時間戳檔名，多 Agent 同時生成不同圖表是安全的。
- **但不得刪除其他 Agent 剛生成的檔案**：清理過期檔案時，只刪除超過保留期限的檔案。

### 6.4 衝突升級機制
- 若兩個 Agent 的修改產生 `git merge conflict`，**不得自行解決衝突**，必須暫停並通知人類工程師處理。
- 若發現其他 Agent 的變更與自己的修改邏輯矛盾，必須在 `AI_HANDOFF.md` 中標記為「⚠️ 待人類確認的衝突」。

## 7. 工具特定入口
- `GEMINI_RULES.md`：Gemini Code Assist 的入口文件，應指向本共同規範並保留 Gemini 觸發語。
- `CODEX_RULES.md`：Codex / GitHub Copilot 的入口文件，應指向本共同規範並保留 Codex 觸發語。
- 若兩份入口文件與本文件衝突，以本文件為準；若 `AI_HANDOFF.md` 提供更新的分支上下文，以 `AI_HANDOFF.md` 為當前任務上下文。

## 8. 參考文件

| 檔案 | 用途 | 職責 |
|------|------|------|
| `AI_COLLABORATION_RULES.md` | 本文件 | 協作規則**唯一真相源**（Pre-flight、架構防禦、提交規則、交接、多 Agent 併發） |
| `DEVELOPMENT_FLOW.md` | CLI 指令 + Git 分支策略 | 開發流程操作細節，規則引用本文件 |
| `PROJECT_ARCHITECTURE.md` | 專案結構 + 數據流 + Agent 詳解 | 架構面內容，協作規則引用本文件 |
| `AI_HANDOFF.md` | 當前交接狀態與待辦 | 每次交接時更新 |
| `CLAUDE.md` | Claude Code 入口規範 | 輕量化入口，技術細節見 `PROJECT_ARCHITECTURE.md` |
| `CHANGELOG.md` | 專案演進歷史 | — |

---

**提示**：使用者若要求遵循 `GEMINI_RULES` 或 `CODEX_RULES`，等同要求遵循本共同規範與對應入口文件。
