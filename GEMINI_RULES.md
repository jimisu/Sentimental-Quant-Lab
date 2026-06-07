# Gemini Code Assist 入口規範 (GEMINI_RULES.md)

Gemini Code Assist 在參與 `Sentimental-Quant-Lab` 專案時，必須遵循共同規範：

- 主要規範：`AI_COLLABORATION_RULES.md`
- 目前交接：`AI_HANDOFF.md`
- 協作流程：`DEVELOPMENT_FLOW.md`
- 技術架構：`PROJECT_ARCHITECTURE.md`
- 演進歷史：`CHANGELOG.md`

## Gemini 特定要求
- 當使用者提及「遵循 GEMINI_RULES」時，請嚴格執行 `AI_COLLABORATION_RULES.md` 的所有檢查點。
- 在修改、重構或新增功能前，若 Git 分支、交接狀態或待辦狀態無法由本機工具確認，必須主動詢問使用者。
- 若 `AI_HANDOFF.md` 顯示當前分支待辦已完成，應引導使用者先提交、推送並建立 PR，避免在已完工分支上追加不相干工作。

本文件僅保留 Gemini 入口與觸發語；共同規則以 `AI_COLLABORATION_RULES.md` 為準。
