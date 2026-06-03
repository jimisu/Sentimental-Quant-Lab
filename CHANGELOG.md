# 變更紀錄 (CHANGELOG)

所有關於 Sentimental-Quant-Lab 專案的開發動態與版本更新將記錄於此。

---

## [2026-06-03 23:55]
- **Added**: 在 `tsmc_signal_dashboard.py` 加入 `--test` 參數與自測模式，支援目錄權限、Token 狀態與 API 連線診斷。

## [2026-06-02 16:30]
- **Changed**: 優化 `analysis_log.md` 報告結構，使用標題層級與引用區塊提升可讀性。
- **Changed**: 調整 `config.py` 保留策略，將每日日誌與圖表保留數 (`keep_count`) 統一設定為 1。
- **Improved**: 強化 Markdown 圖片嵌入顯示，確保技術線圖與籌碼圖緊隨專家判讀內容。

## [2026-06-02]
- **Added**: 新增 `DEVELOPMENT_FLOW.md` 開發協作規範，定義多 AI 協作下的架構防禦、Git 策略與交接流程。
- **Docs**: 正式確立「原子化提交」與「AI 輪班交接」作為專案開發標準。

## [2026-06-02 Rollback]
- **Fixed**: 回滾上一次不穩定的架構改動。
- **Changed**: 將 Agent 類別重新整合至 `tsmc_ai_agents.py` 檔案中，解決模組導入錯誤。
- **Changed**: 移除 `Orchestrator` 中未成熟的 Capex 本機快取邏輯，恢復報告輸出順序（財務、技術、籌碼、宏觀）。

## [2026-06-02]
- **Added**: 實作「大型科技客戶資本支出分析」的本機快取機制。
- **Changed**: 在 `config.py` 新增 `capex_ttl_days` 設定，預設為 14 天。
- **Changed**: 重新編排分析報告與日誌的輸出順序，調整為：宏觀、財務、技術、籌碼。
- **Improved**: 優化 `Orchestrator` 以支援過期判定，若快取在兩週內，將直接使用本機 Capex 分析結果，減少外部 API 依賴。
- **Fixed**: 修正 `GlobalMacroAgent` 在 `tsmc_macro_agent.py` 的外部資料抓取邏輯，新增 `requests.Session` 重試策略與 SEC 資料快取回退機制。
- **Fixed**: 處理 `tsmc_ai_agents.py` 圖表中文字型缺失問題，為 matplotlib 設定中文常用字型清單並關閉 `unicode_minus`，避免 `DejaVu Sans` 警告。

## [2026-05-31 05:45]
- **Fixed**: 強化 Yahoo Finance 抓取魯棒性。實作過期快取回退（Stale Fallback）機制，確保在 API 攔截時仍能顯示分析結果。
- **Changed**: `_fetch_with_cache` 支援 `query1` 與 `query2` 動態切換，並加入隨機 User-Agent 輪詢以降低 429 發生率。
- **Fixed**: 修正 `_fetch_yahoo_price` 在數據結構缺失時的錯誤處理。

## [2026-05-31 05:30]
- **Fixed**: 解決 Yahoo Finance 429 Too Many Requests 錯誤。
- **Added**: 為 `GlobalMacroAgent` 實作獨立快取機制（財報 24h/價格 1h）與隨機退避重試邏輯。
- **Changed**: 優化請求流程，減少對外部 API 的重複存取。

## [2026-05-31 05:15]
- **Fixed**: 修正 `MarketDynamicsAgent` 與 `InstitutionalInvestorAgent` 在資料缺失時回傳 Tuple 而非 `AgentResult` 的問題，預防 `Orchestrator` 產生 `AttributeError`。
- **Changed**: 優化技術分析邏輯優先權，確保大戶賣超訊號優先於一般量能描述顯示。

## [2026-05-31 05:00]
- **Fixed**: 實作 `GlobalMacroAgent` 遺漏的 `_get_yahoo_headers` 方法，徹底解決 `AttributeError` 並強化 Yahoo Finance 數據抓取的穩定性。

## [2026-05-31 04:45]
- **Fixed**: 修正 `GlobalMacroAgent` 遺漏 `_get_yahoo_headers` 方法導致的 `AttributeError`，並統一 Yahoo Finance 請求標頭以提升抓取成功率。

## [2026-05-31 04:30]
- **Fixed**: 修正 `GlobalMacroAgent` 方法呼叫錯誤，確保正確使用詳細抓取器獲取 Capex 數值。
- **Added**: 實作 Capex 金額序列化輸出，報告中現在會精確列出六大巨頭最近三季的支出金額 (以 $B 為單位)。
- **Changed**: 在宏觀分析中引入 `ThreadPoolExecutor` 並行化 6 家美股公司的財報抓取，顯著提升執行效率。

## [2026-05-31 04:00]
- **Added**: `GlobalMacroAgent` 新增美國六大科技巨頭 (NVDA, MSFT, AMZN, META, GOOGL, AAPL) 資本支出 (Capex) 分析。
- **Changed**: 實作「連續三季 Capex 成長」偵測邏輯，並將其納入宏觀專家評分修正項，動態反應台積電下游需求強度。
- **Fixed**: 優化 `GlobalMacroAgent` 報告格式，採用清單化呈現 ADR、匯率與 Capex 狀態。

## [2026-05-31 03:00]
- **Removed**: 刪除 `sentiment_venv` 隔離環境，簡化專案依賴管理。
- **Changed**: 全面重寫 `README.md`，新增 AI Agent 評分系統說明與分析範例。

## [2026-05-31 02:15]
- **Changed**: 重構 `fetch_twse_report` 策略，移除固定長延遲。
- **Added**: 實作「精準標頭模擬」(Referer/Origin) 與「指數退避重試機制」，優先透過模擬真實行為規避 307 攔截，僅在失敗時才觸發等待。

## [2026-05-31 02:00]
- **Changed**: 升級 `fetch_twse_report` 抓取策略。引入 `requests.Session` 以維持 Cookies 狀態，並實作隨機 `User-Agent` 切換。
- **Changed**: 將固定延遲改為真正的「隨機浮動延遲」(2.5s - 5.5s)，以更有效率地規避 TWSE 的安全性攔截。

## [2026-05-31 01:45]
- **Fixed**: 處理 TWSE API 的安全性攔截 (HTTP 307)。
- **Changed**: 在 `fetch_twse_report` 中加入 2 秒延遲，並優化偵測 HTML 回傳的邏輯，避免噴出大量無用的 HTML 錯誤代碼。

## [2026-05-31 01:30]
- **Changed**: 優化技術 Agent 報告格式，將「週線 RSI 頂背離」加入具體的數值對比說明，與日線格式保持一致。

## [2026-05-31 01:15]
- **Changed**: 優化儀表板總結顯示，為紅、黃、綠燈狀態新增對應的 Emoji (🔴, 🟡, 🟢) 與 ANSI 顏色高亮。

## [2026-05-31 01:00]
- **Fixed**: 修正 `tsmc_ai_agents.py` 中的 `NameError`，補全 `severe_msg` 與 `reversal_msg` 的定義邏輯。

## [2026-05-31 00:45]
- **Added**: 在 `Orchestrator` 中實作「雙重黃燈嚴重警示」。當儀表板與 AI 評分同時為黃燈時，輸出高亮度紅底白字警告，並同步寫入日誌。

## [2026-05-31 00:35]
- **Changed**: 優化 `Orchestrator` 評分顯示邏輯，當綜合健康得分高於 80 分時，在控制台以綠色燈號 (🟢) 標示健康狀態。

## [2026-05-31 00:30]
- **Changed**: 優化 `Orchestrator` 評分顯示邏輯，當綜合健康得分低於 60 分時，在控制台以黃色燈號 (🟡) 標示警告。

## [2026-05-31 00:20]
- **Fixed**: 修正 `Orchestrator` 未將 `GlobalMacroAgent` 報告寫入 `analysis_log.md` 的問題。

## [2026-05-31 00:15]
- **Added**: `GlobalMacroAgent` 現在能透過 Yahoo Finance API 即時抓取 TSM ADR 與 TWD=X 匯率。
- **Changed**: 實作 ADR 折溢價分析邏輯，並將分析結果納入長期趨勢評分權重。

## [2026-05-31 00:05]
- **Changed**: 更新 `Orchestrator` 綜合評分權重，將 `GlobalMacroAgent` 分數正式納入「長期趨勢」維度並給予 25% 佔比。
- **Changed**: 重新調整其餘權重分佈：早期警示(10%)、短期形態(10%)、中期趨勢(15%)、技術長期(15%)、籌碼分析(25%)。

## [2026-05-30 23:45]
- **Fixed**: 統一 `Orchestrator` 評分總結格式，將籌碼面總分修正為加權顯示格式 `(分數) * 0.25`。

## [2026-05-30 23:15]
- **Fixed**: 修正 `analysis_log.md` 紀錄到 Tuple 與 Numpy 型別的問題，確保日誌內容僅包含純文字報告。
- **Changed**: 強制轉換 Agent 旗標為標準 Python 布林值，提升 Orchestrator 邏輯穩定性。

## [2026-05-30 23:00]
- **Changed**: 優化 `reversal_analysis.py`，新增「轉折訊號提醒」偵測與訊號出現後的最大跌幅 (Drawdown) 統計功能。

## [2026-05-30 22:30]
- **Fixed**: 優化 TWSE API 日期邊界偵測邏輯，將 `TWSE_MIN_DATE` 調整為 1990-01-04 (民國 79 年)。
- **Changed**: `fetch_twse_report` 改用通用字串比對偵測日期限制錯誤，增加對不同年份限制訊息的相容性。

## [2026-05-30 22:05]
- **Changed**: 優化 `reversal_analysis.py`，新增「正乖離壓力拉回」與「負乖離支撐拉回」的雙向分析功能。

## [2026-05-30 21:45]
- **Added**: 新增 `reversal_analysis.py` 腳本，用於從歷史日誌中分析台積電跌破 20MA 的拉回門檻（Support Threshold）。

## [2026-05-30 20:49]
- **Added**: 新增 `local_cache/` 本機 circular cache，FinMind 與 TWSE 原始資料成功抓取後會保存最新三份，API 失敗時可回退使用最新快取。
- **Changed**: 將 `local_cache/` 加入 `.gitignore`，避免本機快取資料進入版本控制。

## [2026-05-30 20:43]
- **Added**: 技術 Agent 分析新增 20MA 乖離率，顯示最新收盤價相對 20 日均線的偏離百分比。

## [2026-05-30 20:38]
- **Changed**: `charts/` 圖表清理規則改為同一天同類型保留最新三張，`tech_chart` 與 `chip_chart` 會各自修剪，不同日期不受影響。

## [2026-05-30 20:35]
- **Added**: `analysis_log.md` 寫入後會自動修剪同一天紀錄，只保留最新三筆分析，避免日誌檔持續膨脹。

## [2026-05-30 20:28]
- **Changed**: 稅後淨利率恢復為上一版計算方式：以稅後淨利金額除以營收計算，不再改抓「稅後純益率 / Net Profit Margin」比率欄位。
- **Removed**: 移除 TSMC Earnings Release PDF fallback 與 `pypdf` 依賴。

## [2026-05-30 20:25]
- **Changed**: 稅後淨利率改為優先抓「稅後純益率 / Net Profit Margin」比率欄位，不再用稅後淨利除以營收自行換算。
- **Added**: 新增 TSMC investor.tsmc.com 每季 Earnings Release fallback；FinMind 抓不到稅後純益率時，會嘗試從官方 PDF 擷取 `net profit margin`。

## [2026-05-30 20:17]
- **Fixed**: 修正稅後淨利率抓不到的問題，新增 FinMind 官方常見欄位 `IncomeAfterTaxes`，並加入 `origin_name` 中文名稱 fallback 以提高財報欄位相容性。

## [2026-05-30 20:14]
- **Changed**: 圖表輸出改為每天每種圖只保留最新一張；重新產生 `tech_chart` 或 `chip_chart` 時會刪除同日舊圖，避免 `charts/` 目錄持續膨脹。

## [2026-05-30]
- **Added**: 實作了三個 AI Agent (財務、技術、籌碼) 聯手分析系統。
- **Added**: 新增自動化繪圖功能，產出技術線圖與外資買賣超圖表。
- **Changed**: 儀表板 UI 升級，完整顯示「三率」（毛利、營益、淨利）並加入紅黃綠燈邏輯。
- **Fixed**: 修正了 `NetIncome` 欄位抓取不到以及 DataFrame `KeyError` 的問題。
- **Fixed**: 擴展淨利欄位搜尋清單，支援台積電合併報表特有的 `Net_Income_Attributable_To_Owners_Of_The_Parent` 欄位。
