# AI 輪班交接報告 (AI Handoff Report)

<!--
  當更換 AI 工具或下班前，請根據目前的開發進度填寫此文件。
  這能確保下一個接手的 AI 代理程式具備完整的開發上下文。
-->

## 📌 基本資訊

- **目前所在分支 (Current Branch)**: `fix/findmind-return-error`
- **本次交接時間 (Timestamp)**: 2026-06-12 (UTC+8)
- **目前負責人/AI (Handler)**: OWL (Claude Code)

---

## ✅ 已完成的工作 (What's Done)

### 本次分支新功能（feat/auto-optimization）
- [x] **產業分析框架全面升級**：改寫 `_build_industry_analysis_section()`，從五大優化面向擴展為七大章節
- [x] **法說會行為模式框架**：新增 `_estimate_earnings_date()`，自動判斷當前處於法說會前/後/間距期，並給出 de-risking 模式解讀
- [x] **客戶集中度風險段落**：Apple (~25%) 與 NVIDIA (~10-12%) 的單點脆弱性分析
- [x] **ADR 溢價 SOX 邏輯修正**：將「SOX 同步走強」改為更精確的「NVIDIA 財報上修 + Apple 訂單追蹤」
- [x] **PEG 錨定 consensus EPS**：不再自行假設 30% 成長率，改為從 `bigtech_data` 實際 EPS 推算；若無數據則提示以 Bloomberg/Refinitiv 替代
- [x] **轉空觸發條件歷史校準**：5 萬張門檻加入 2022 年（80 萬張/月）、2024 年（30-40 萬張）歷史對照
- [x] **合規免責聲明**：報告開頭自動加入分析基準日與免責聲明
- [x] **分析師整合結論**：取代條列式總結，改為核心矛盾描述 → 因果鏈圖 → 操作建議矩陣
- [x] **f-string 格式 bug 修正**：修復法說會日期顯示的 `.format()` / f-string 混用問題
- [x] **完整測試驗證**：語法檢查、自測模式、完整分析執行、日誌內容驗證全部通過

### 歷史已完成（先前分支）
- [x] **feat/add-codex-ai-working-follow**：Codex/Gemini/Copilot 多 AI 協作規則整合、SessionStart hook、原生指令文件（已合併至 main）
- [x] 統一快取層 data_cache.py、Matplotlib 中文字型修正
- [x] --test 自測功能
- [x] SessionStart hook 自動載入所有說明文件

### 歷史已完成（本次 session）
- [x] **format_tsmc_report.py 整合進 Orchestrator**：`_append_to_log` 寫入成功後自動呼叫 `_generate_formatted_report()`，產出 `reports/tsmc_report_YYYYMMDD_HHMMSS.md`
- [x] **端到端測試驗證**：儀表板執行後自動產出格式化報告，數據正確無誤
- [x] **報告數據交叉驗證**：財務、技術、籌碼、宏觀、估值各面向數據均與原始快取一致

### 本次 session 完成（fix/findmind-return-error / 2026-06-12）
- [x] **FINMIND_TOKEN 環境變數設定**：
  - 已將 token 寫入 `~/.bashrc`（`export FINMIND_TOKEN="..."`），新 terminal session 自動載入
  - 已建立 `.env` 檔案（專案目錄下），並加入 `.gitignore` 避免 token 洩露
  - **⚠️ Token 安全規範**：token 只存放於本機 `~/.bashrc` 與 `.env`，嚴禁上傳至任何外部服務或 API
- [x] **FinMind API token 驗證**：帶 token 呼叫 `TaiwanStockMonthRevenue` API，成功回傳 200 與月營收數據，token 有效
- [x] **完整儀表板執行驗證**：五大 Agent（財務、技術、籌碼、宏觀、大廠基本面）全部成功運行，綜合健康得分 89.0/100（綠燈）

## ⚠️ Lesson Learned（本次 session 發現的問題）

### 1. `--test` 自測模式 FinMind 422 是假警報
- **現象**：`python tsmc_signal_dashboard.py --test` 固定顯示 `FinMind API: 回傳狀態 422`
- **原因**：自測程式碼（第 1056 行）在測試 FinMind 時直接用 `requests.get(url)` 打 base URL，**沒有帶 token 和任何參數**（dataset、data_id 等），FinMind 伺服器因缺少必要參數回傳 422（Unprocessable Entity）
- **結論**：這不是真正的連線問題。只要帶 token 和正確參數打 API 即可成功（已驗證回傳 200）
- **建議修复**（低優先）：修改 `run_self_test()` 中的 FinMind 測試邏輯，帶入 token 和 sample 參數，或將 422 也視為「服務有反應」（類似 TWSE 將 400/401 視為成功）

### 2. FinMind API 無 token 時的行為
- **無 token 呼叫**：回傳 422，不會提供資料
- **無 token 但本地有快取**：主程式會自動降級讀取 `local_cache/` 中的舊快取（月營收 24h TTL、季報 7d TTL），所以之前沒 token 也能跑
- **快取過期後無 token**：`fetch_finmind_dataset` 會 `sys.exit(1)` 崩潰
- **結論**：設定 `FINMIND_TOKEN` 是必要的，不能只依賴快取

### 3. Token 安全注意事項
- Token 已存入 `~/.bashrc` 和 `.env`，`.env` 已加入 `.gitignore`
- **⛔ 禁止將 token 傳送至任何外部服務**（包括 AI API、遠端伺服器、第三方工具）
- **⛔ 禁止將 token 寫入任何會被 git commit 的檔案**
- Token 僅用於本機開發環境呼叫 FinMind API

## ⏳ 未完成 / 待事項 (Pending Tasks)
<<<<<<< HEAD
1. **[已完成]** ~~建立 PR 合併到 main~~：`feat/claude-refactor` 已通過 PR #15 合併至 main（2026-06-12）。
2. **[優先級：低] 清除本地舊分支**：`feat/claude-refactor` 和 `feat/add-codex-ai-working-follow` 已合併，可本地刪除。
3. **[優先級：低] 舊報告清理**：`reports/` 目錄會隨每次執行累積，已有 `.gitignore` 排除，可考慮定期清理機制。
4. **[優先級：低] 修復 `--test` 自測模式 FinMind 422 假警報**：修改 `run_self_test()`，讓 FinMind 測試帶入 token 或將 422 視為連線成功。
5. **[已完成]** `FINMIND_TOKEN` 設定：已寫入 `~/.bashrc` 和 `.env`，`.env` 已加入 `.gitignore`。

---

## 🏗️ 架構注意事項 (Architecture Notes)
> 1. `MarketDynamicsAgent.analyze_sentiment()` 現在回傳 4 元組：`(report, tech_flags, tech_scores, vol_price_divergence)`
> 2. `MarketDynamicsAgent._format_reversal_signals()` 現在回傳 4 元組：`(report, monthly_break, penalties, vol_price_warnings)`
> 3. `GlobalMacroAgent.analyze_bigtech_fundamentals()` 現在接受 `quarterly_data: Dict = None` 參數
> 4. `Orchestrator._append_to_log()` 新增 `industry_analysis_md: str = ""` 參數
> 5. `Orchestrator._build_industry_analysis_section()` 為新增方法，產出「五、產業分析框架與深度解讀」章節
> 6. `Orchestrator._estimate_earnings_date()` 為新增方法，自動估算法說會日期
> 7. `_keep_latest_daily_logs` 採用「讀取全部內容 → 追加新內容 → 原子性覆寫」模式
> 8. 多 AI 自動載入入口：Claude Code（`CLAUDE.md` + hook）、Copilot（`.github/copilot-instructions.md`）、Gemini（`.gemini/GEMINI.md`）
> 9. 報告生成邏輯統一在 `tsmc_ai_agents.py` 的 `Orchestrator` 類中，signal 計算在 `signal_engine.py`
> 10. 本次 session 發現的 bug：f-string 中不可混用 `.format()` 變數名稱（已修復）
> 11. `Orchestrator._append_to_log()` 成功寫入後，自動呼叫 `_generate_formatted_report()` 產出 `reports/tsmc_report_*.md`
> 12. `scripts/format_tsmc_report.py` 仍保留為獨立 CLI 工具，可手動執行 `python scripts/format_tsmc_report.py --output reports/tsmc_report.md`

## 🚀 給下一個 AI 建議
1. **新分支開發**：目前已在 `main`，新功能請開新分支開發。
2. **後續開發程式碼修改前**：請先進入對應的自動載入入口確認協作規則，並保持小步提交。
3. **⚠️ 禁止自動 git push**：任何情況下 AI 都不得自行推送，只能提醒人類評估。
---
