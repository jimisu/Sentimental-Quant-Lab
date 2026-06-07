# Claude Code 入口規範 (CLAUDE.md)

Claude Code 在參與 `Sentimental-Quant-Lab` 專案時，必須遵循共同規範。原本在本文件中的技術細節已整合至核心文檔，請優先參考以下文件：

- 主要規範：`AI_COLLABORATION_RULES.md`
- 目前交接：`AI_HANDOFF.md`
- 協作流程：`DEVELOPMENT_FLOW.md` (已整合原有的 CLI 指令)
- 技術架構：`PROJECT_ARCHITECTURE.md` (已整合原有的數據流與指標詳解)
- 演進歷史：`CHANGELOG.md`

## Claude 特定要求
- 當啟動 Session 時，請先讀取 `AI_COLLABORATION_RULES.md` 並核對 `AI_HANDOFF.md` 中的當前分支。
- 在修改或新增功能前，若 Git 分支、交接狀態或待辦狀態無法由本機工具確認，必須主動詢問使用者。
- 遵守「原子化提交」原則，每完成一個邏輯單元即主動提醒使用者進行 `git commit`。
- **絕不靜默離開**：觸發交接關鍵字（如 handoff, bye, 收工）時，必須更新 `AI_HANDOFF.md` 並顯示交接摘要。

---
**提示**: 本文件僅保留 Claude 入口與觸發語；所有技術實作細節與共同規則已分別移至架構說明與協作準則。
