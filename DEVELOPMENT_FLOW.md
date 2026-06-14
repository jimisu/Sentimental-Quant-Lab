# 多 AI 協作開發流程規範 (DEVELOPMENT_FLOW)

本專案採用多 AI 工具（Gemini Code Assist, GitHub Copilot/Codex, Claude Code）輪流協作模式。所有參與開發的 AI 代理程式必須嚴格遵守 `AI_COLLABORATION_RULES.md` 與本文件。

> **⚠️ 規則唯一真相源**：Pre-flight、架構防禦、原子化提交、AI 輪班交接、多 Agent 併發衝突處理等協作規則，以 [`AI_COLLABORATION_RULES.md`](./AI_COLLABORATION_RULES.md) 為準。本文件不再重複，僅保留 CLI 指令與 Git 分支策略。

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

## 1. Git 分支策略 (Git Branching Strategy)

- **受保護的分支**：嚴禁直接在 `main` 或 `develop` 分支上進行任何代碼修改。
- **特性與修復分支**：
    - 開發新功能：必須從最新的 `main` 切出 `feat/功能名稱` 分支。
    - 修復 Bug：必須從最新的 `main` 切出 `fix/問題描述` 分支。
- **合併前置**：在提出合併請求前，AI 必須確保代碼在當前分支能通過 `python tsmc_signal_dashboard.py` 的基本執行測試。

> 更詳細的分支上下文與 Pre-flight 檢查，見 `AI_COLLABORATION_RULES.md` §2。

---

## 2. 參考文件

| 檔案 | 用途 |
|------|------|
| `AI_COLLABORATION_RULES.md` | 協作規則唯一真相源（Pre-flight、架構防禦、提交規則、交接、多 Agent 併發） |
| `PROJECT_ARCHITECTURE.md` | 專案架構、數據流、Agent 詳解 |
| `AI_HANDOFF.md` | 當前交接狀態與待辦 |
| `CLAUDE.md` | Claude Code 入口規範 |
| `CHANGELOG.md` | 專案演進歷史 |

---

## 執行聲明

當使用者啟動 AI 助手時，AI 應先讀取 `AI_COLLABORATION_RULES.md` 與本文件以同步開發共識。任何違反上述規範的建議，使用者有權拒絕並要求 AI 重新調整。

**版本**: 2.0.0
**最後更新日期**: 2026-06-14
