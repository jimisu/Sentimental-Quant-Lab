# 修正綠燈失真 + 重寫風險管理/分析師結論模組

## 問題陳述
- 技術面 7/17 帶量跌破所有均線、籌碼面外資十天九日賣超，綜合卻仍顯示綠燈 → 因 `市場情緒分數`（量能）佔 `config.py` 權重 10%，且與籌碼面 <50 共同觸發「結構性警示 → 強制黃燈」，但單獨量能正常時會把分數撐在綠燈區。
- 風險管理（ch7）與分析師結論（ch8）建立於「法說會尚未召開、等待催化劑」的過期假設；實際上法說會已於 2026-07-16 召開，7/17 暴跌主因是外部系統性風險（詳 `macro_risk.py`），非台積電基本面惡化。

## 已確認決策
1. 市場情緒分數 **完全移出燈號計算**。
2. `macro_risk.py` 由我新建（提供「外部系統性風險」紅/黃/綠燈判讀）。
3. 先 `git checkout` 還原本分支未提交的半成品重構（`_build_industry_analysis_section` 改成 `-> Tuple[str,str]` 但實作未完成、`analysis` 列表被棄用），回到穩定單一字串版本，再進行本次任務。

---

## 步驟

### Step 0 — 還原半成品重構
- `git checkout -- tsmc_ai_agents.py`：放棄未提交的產業分析重構 diff（與本任務無關，且已損毀）。
- 確認 `_build_industry_analysis_section` 回到單一 `return "\n".join(lines)`（HEAD 版本），`industry_analysis_md` 仍為單一字串，與 `_append_to_log` 現有呼叫相容。

### Step 1 — 新建 `macro_risk.py`
純邏輯、不依賴新 API、可離線（必要時讀本地快取）。對外提供：
- `MacroRiskSignal` dataclass：`level`(red/yellow/green)、`is_red: bool`、`reason: str`、`factors: List[str]`、`severity`。
- `assess_macro_risk(trading_df=None, price_df=None, *, as_of=None) -> MacroRiskSignal`：依跨市場連動/槓桿商品斷鏈線索判讀當前外部系統性風險燈號（預設 `green` + `reason="無外部系統性風險訊號"`；提供 inject 介面供測試與未來接真實數據）。
- `is_systemic_event_day(price_df, date) -> bool`：判斷某日是否為「跨市場連動/槓桿斷鏈驅動的異常暴跌」（大幅下跌 + 異常放量）。
- `classify_sell_pressure(foreign_sell_shares, date, *, event_days=None, is_systemic=None) -> dict`：回傳 `{"driven_by": "systemic"|"fundamental"|"unknown", "counts_toward_bearish": bool, "note": str}`。當 `is_systemic_event_day(date)` 為真時標記 `systemic`、`counts_toward_bearish=False`。
- `days_since_earnings(earnings_date, as_of) -> int`：交易日曆算（含淨化 fallback），供 ch7 動態欄位。

### Step 2 — 從燈號計算移除情緒（`signal_engine.py` + `config.py`）
- `config.py` `ScoreWeightsConfig.market_sentiment = 0.10` → `0.0`；同步更新 docstring。剩餘四面向（財務30/大廠30/技術20/籌碼10）合計 0.90；綜合分數上限 90，燈號門檻（<50紅/<70黃）維持不變，**不重新歸一化**（避免動到門檻校準）。
- `ComprehensiveScoreCalculator`：移除 `market_sentiment` 權重與 `breakdown["market_sentiment"]`。
- `AlertLevelDetector.detect`：移除 `market_sentiment_score` 參數與「籌碼+情緒同步惡化 → 強制黃燈」邏輯，保留「籌碼 <30 → 強制黃燈」。
- `SignalEngine.analyze`：移除 `market_sentiment_signals` 參數與相關 `result.market_sentiment_score` 設值、`detect(...)` 呼叫中的該參數。

### Step 3 — 清理 `tsmc_ai_agents.py` 中情緒引用（`run_full_analysis`）
- 移除 `_build_market_sentiment_signals` 呼叫與 `market_sentiment_signals` 建構（保留函式定義供未來復用，或在確認無測試依賴後移除；先保留定義）。
- `score_summary` 字串移除「● 市場情緒(bs.score)*...」那一行。
- 控制台「市場情緒」列印區塊移除。
- PE 警告邏輯中 `has_bad_sentiment = market_sentiment_signals.score <= 60` 改為 `False`（或移除該變數及其在 AND 條件中的參與），使 PE 警告改由「技術量價背離 + 籌碼賣超」決定，不再被量能「正常」掩蓋。
- `_append_to_log` 總覽儀表板：「市場情緒」列移除；剩餘四面向仍顯示。

### Step 4 — 重寫 ch7 風險管理與操作建議（`_append_to_log` 約 L2735）
- **操作時間框架表格**：
  - 移除「法說會前（N 天內）」過期列。
  - 改用 `macro_risk.days_since_earnings(earnings_date, today)` 計算 `N`，新增動態列「法說會後 N 個交易日」。
  - 若 `assess_macro_risk(...).is_red`：表格後加註區塊：「當前價格波動主要反映外部風險（詳見風險燈號說明），非台積電法說會內容或基本面轉弱所致」。
- **關鍵價位參考表格**：新增「形成原因」欄：
  - 每個價位標註 (a) 正常估值修正 或 (b) 外部系統性事件驅動的技術性下殺。
  - 若 `today == 外部風險事件日`（以 `is_systemic_event_day` 判斷）且現價即該日收盤價：標註「此為[日期]外部風險事件後價格，非台積電獨立基本面定價結果」。
- **結論反轉觸發條件**：
  - 「月營收 YoY」門檻改動態：取近 12 個月營收 YoY（來自 `styled_df`），算移動平均與標準差，`較近 12 月均值下滑超過 X 個標準差` 作為轉空訊號（X 取 config 可調，預設 1.5），取代寫死的 10%。
  - 「外資賣超」觸發：呼叫 `macro_risk.classify_sell_pressure(..., date=today)`；若回傳 `driven_by=="systemic"`，該日賣超張數標記「系統性風險驅動」，**不計入轉空判斷邏輯**，避免技術性去槓桿被誤判為法人對基本面看法轉弱。

### Step 5 — 重寫 ch8 分析師整合結論（`_append_to_log` 約 L2770）
- **因果鏈**：在 ADR 溢價環節之前或之後，新增一環「外部系統性風險（跨市場連動、槓桿商品斷鏈）」，並標註「與台積電自身基本面無關，但可能短期主導股價波動方向」。
- **核心矛盾段落**：
  - 不再直接斷言「外資在高檔系統性出貨」，除非有具體數據支撐（確認賣超集中於特定幾日、且同期無伴隨韓股/費半系統性賣壓）。
  - 改為：以外資賣超是否經 `classify_sell_pressure` 判為 `systemic` 決定措辭——若為 systemic，標註「外部連動效應，非基本面轉弱」；若無法確認（unknown），改寫「外資賣超原因待確認，可能為基本面轉弱或外部連動效應，建議搭配 `macro_risk.py` 燈號判讀」。

### Step 6 — 測試（`test_ai_agents.py` + `test_macro_risk.py`）
- **`macro_risk.py` 單元測試**：`assess_macro_risk`（green 預設 / 注入 red 理由）、`is_systemic_event_day`（異常暴跌日 True / 一般日 False）、`classify_sell_pressure`（systemic→不計入、fundamental→計入、unknown→待確認）、`days_since_earnings`（含淨化 fallback）。
- **行為測試（2026-07-16 法說會 / 2026-07-17 暴跌日場景）**：
  - 以 `patch.object(Orchestrator, "__init__", ...)` 建構 Orchestrator 實例（沿用既有 fixture 模式）。
  - `monkeypatch` / `patch` 注入 `macro_risk.assess_macro_risk` → `is_red=True, reason="跨市場連動+槓桿斷鏈"`；`is_systemic_event_day` → 對 2026-07-17 回傳 True；`days_since_earnings` → 回傳 1（法說會後 1 交易日）。
  - 注入 `today = date(2026,7,17)`（透過 patch `datetime.date.today` 或傳入參數；`_estimate_earnings_date` 與 `_append_to_log` 用 `date.today()`）。
  - 準備最小 `styled_df`（含 12 個月營收 YoY，均值 ~40%、最新月下滑至 ~10% 以觸發動態標準差轉空）、`chip_flags`（外資賣超）、`result`、`tw_price`、`quarterly_data`、`pe_ratio` 等。
  - 呼叫內部章節建構（或 `_append_to_log` 片段）取得 ch7/ch8 Markdown，斷言：
    1. ch7 出現「法說會後 1 個交易日」動態欄位、**無**「法說會前」列。
    2. ch7 出現「當前價格波動主要反映外部風險…非台積電…基本面轉弱」註記。
    3. 關鍵價位表含「形成原因」欄，且現價標註「[2026-07-17]外部風險事件後價格」。
    4. 轉空觸發條件使用「近12月營收YoY均值下滑 X 個標準差」，**無**寫死「<10%」；外資賣超標記「系統性風險驅動」未計入轉空。
    5. ch8 因果鏈含「外部系統性風險（跨市場連動、槓桿商品斷鏈）」環節。
    6. ch8 核心矛盾**未**出現「外資在高檔系統性出貨」硬斷言；改為待確認/外部連動措辭。
- 執行：`python -m pytest test_ai_agents.py test_macro_risk.py -q`（必要時加 `test_signal_engine.py` 確認燈號計算回歸綠/黃/紅門檻正確）。

---

## 影響範圍
- 新增：`macro_risk.py`、`test_macro_risk.py`
- 修改：`config.py`（權重）、`signal_engine.py`（移除情緒）、`tsmc_ai_agents.py`（清理情緒引用 + 重寫 ch7/ch8）、`test_ai_agents.py`（行為測試）
- 還原：本分支未提交之 `_build_industry_analysis_section` 半成品 diff
- 不動：`data_cache.py`、`sal/`、`tsmc_*_agent.py` 獨立代理、架構單例

## 提交策略
原子化提交（依 CLAUDE.md）：
1. `revert: 還原未提交之產業分析半成品重構`
2. `feat: 新增 macro_risk.py 外部系統性風險判讀模組`
3. `fix: 移除市場情緒分數出綜合燈號計算`
4. `feat: 重寫風險管理與分析師結論（對齊法說會後+外部系統性風險）`
5. `test: 新增 macro_risk 單元與 7/17 暴跌場景行為測試`
（不執行 `git push`，僅提醒人類評估。）
