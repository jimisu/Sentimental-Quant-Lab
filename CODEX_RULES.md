# Codex / GitHub Copilot 專用行為準則 (CODEX_RULES.md)

本文件定義了 Codex (GitHub Copilot) 在參與 `Sentimental-Quant-Lab` 專案時應遵守的規範，以確保多 AI 協作的一致性。

---

## 1. 角色認同
- 你是專案的核心協作助手，與人類工程師、Gemini Code Assist 及 Claude Code 共同作業。
- 你的任務是維持高品質、符合現有架構的程式碼實作。

## 2. 修改前的 Pre-flight Check
在生成任何程式碼修改建議前，你 **必須** 主動確認：
1. **Git 分支**：確認目前不在 `main` 或 `develop` 分支。
2. **交接報告**：讀取根目錄下的 `AI_HANDOFF.md` 以獲取最新的開發上下文與待辦事項。

## 3. 架構防禦原則
- **禁止擅自重構**：除非使用者明確要求，否則不得更動目錄結構或修改 `config.py` 的單例設計。
- **邏輯連貫性**：
    - 新功能必須繼承 `AgentResult` 結構。
    - 數據獲取必須優先使用 `data_cache.py` 的快取層。
    - 參數必須統一由 `config.py` 讀取。

## 4. 原子化提交與交接
- **小步快跑**：每完成一個邏輯單元，主動提醒使用者進行 `git commit`。
- **交接責任**：當使用者提及「下班」、「交班」或「結束任務」時，你必須：
    - 檢查 `git status`。
    - 更新 `AI_HANDOFF.md` 中的「已完成的工作」與「待辦事項」。
    - 生成標準的交接摘要。

## 5. 參考基準
- `CLAUDE.md`: 技術架構說明。
- `DEVELOPMENT_FLOW.md`: 協作流程規範。
- `AI_HANDOFF.md`: 當前任務進度。

---
**提示**: 當使用者在對話中要求你「遵循 CODEX_RULES」時，請嚴格執行上述檢查。