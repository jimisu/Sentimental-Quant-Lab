# Codex / GitHub Copilot 入口規範 (CODEX_RULES.md)

Codex (GitHub Copilot) 在參與 `Sentimental-Quant-Lab` 專案時，必須遵循共同規範。雖然目前參與頻率較低，但協作標準應與其他 AI 工具保持一致：

- 主要規範：`AI_COLLABORATION_RULES.md`
- 目前交接：`AI_HANDOFF.md`
- 協作流程：`DEVELOPMENT_FLOW.md`
- 技術架構：`CLAUDE.md`、`PROJECT_ARCHITECTURE.md`
- 演進歷史：`CHANGELOG.md`

## Codex 特定要求
- 當使用者提及「遵循 CODEX_RULES」時，請嚴格執行 `AI_COLLABORATION_RULES.md` 的所有檢查點。
- 鑒於 Codex 較少參與，**在生成程式碼前，必須完整讀取 `AI_HANDOFF.md` 與 `PROJECT_ARCHITECTURE.md`** 以確保補齊遺漏的上下文。
- 在修改或新增功能前，若 Git 分支、交接狀態或待辦狀態無法由本機工具確認，必須主動詢問使用者。
- 遵守「原子化提交」原則，每完成一個邏輯單元即主動提醒使用者進行 `git commit`。

---
**提示**: 本文件僅保留 Codex 入口與觸發語；共同規則以 `AI_COLLABORATION_RULES.md` 為準。