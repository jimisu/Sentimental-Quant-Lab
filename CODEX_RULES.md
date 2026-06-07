# Codex / GitHub Copilot 入口規範 (CODEX_RULES.md)

Codex (GitHub Copilot) 在參與 `Sentimental-Quant-Lab` 專案時，必須遵循共同規範。

## 自動載入

當你在 VS Code 中開啟此專案時，GitHub Copilot 會自動讀取 `.github/copilot-instructions.md` 作為專案指令。該文件包含完整的 Pre-flight Check、架構防禦、原子化提交、多 Agent 併發安全與交接規範。

本文件（`CODEX_RULES.md`）作為補充入口，供手動查閱、CLI 環境（OpenAI Codex）或其他工具載入時使用。

## 快速參考

- 主要規範：`AI_COLLABORATION_RULES.md`
- 完整指令：`.github/copilot-instructions.md`
- 目前交接：`AI_HANDOFF.md`
- 協作流程：`DEVELOPMENT_FLOW.md`
- 技術架構：`PROJECT_ARCHITECTURE.md`
- 演進歷史：`CHANGELOG.md`

## Codex 特定要求
- 當使用者提及「遵循 CODEX_RULES」時，請嚴格執行 `AI_COLLABORATION_RULES.md` 的所有檢查點。
- 鑒於 Codex 較少參與，**在生成程式碼前，必須完整讀取 `AI_HANDOFF.md` 與 `PROJECT_ARCHITECTURE.md`** 以確保補齊遺漏的上下文。
- 在修改或新增功能前，若 Git 分支、交接狀態或待辦狀態無法由本機工具確認，必須主動詢問使用者。
- 遵守「原子化提交」原則，每完成一個邏輯單元即主動提醒使用者進行 `git commit`。

## Codex 承接檢查清單（Handoff Takeover Steps）

當 Codex 從其他 AI 工具接手工作時，必須依序執行以下步驟：

### Step 1：確認環境
```bash
git branch --show-current    # 確認目前在 feature/fix 分支，不在 main/develop
git status                   # 檢查是否有未提交的變更
```

### Step 2：讀取上下文
1. 讀取 `AI_HANDOFF.md` → 確認當前分支、已完成工作、待辦事項、架構注意事項
2. 讀取 `PROJECT_ARCHITECTURE.md` → 確認檔案職責、數據流、API 限制
3. 讀取 `AI_COLLABORATION_RULES.md` → 確認 Pre-flight 檢查與架構防禦規則

### Step 3：確認接手狀態
- 若 `AI_HANDOFF.md` 的待辦事項是空的或已完成 → 詢問使用者是否要建立新分支進行新任務
- 若 `git status` 有未提交的變更 → **不得擅自覆蓋**，必須先詢問使用者這些變更的意圖
- 若 `AI_HANDOFF.md` 中有「⚠️ 待人類確認的衝突」標記 → 暫停並通知人類工程師

### Step 4：開始工作
- 嚴格遵守 `AI_COLLABORATION_RULES.md` 的 Pre-flight Check
- 一次只處理一個邏輯單元，完成後主動提醒 `git commit`
- 修改程式碼時，遵循 `PROJECT_ARCHITECTURE.md` 中的架構防禦規則

---
**提示**: 本文件僅保留 Codex 入口與觸發語；共同規則以 `AI_COLLABORATION_RULES.md` 為準。