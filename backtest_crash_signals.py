#!/usr/bin/env python3
"""
backtest_crash_signals.py
=========================
崩盤日前一天「綜合燈號 / 籌碼面燈號」回測。

做法：重現原本測試 2026-07-16（7/17 暴跌前一日）的信號邏輯，
擴展到兩年視窗抓到的另外六個崩盤日的前一日，共七個 as-of 日期。

對每一個 as-of 日期（崩盤日的前一個交易日）：
  1. 用 Yahoo 歷史 OHLCV 重建技術面資料 → MarketDynamicsAgent.analyze_sentiment
     → 技術面四項分數 + 轉折 flag（ma20_cross_below / monthly_break_ma12 /
       bb_squeeze_break）。
  2. 用 FinMind 歷史三大法人買賣超 → InstitutionalInvestorAgent.analyze_flow
     → 籌碼面分數 + 外資賣超 flag。
  3. 財務面 / 大廠基本面以「最新代表值」代入（強勢，score=100），
     因歷史財報/大廠資料較難取得（符合需求：技術+籌碼用真實 as-of 歷史）。
  4. 以上四面向交給 signal_engine.SignalEngine.analyze → 綜合燈號 + 籌碼面燈號。

資料來源：
  * 2330.TW / ^TWII 日線：Yahoo Finance
  * 三大法人買賣超：FinMind TaiwanStockInstitutionalInvestorsBuySell
    （register 等級可用；Foreign_Investor 為外資）

說明：
  * 「大盤成交金額」欄位 Yahoo 未取得，僅作為技術面量價背離敘事的佔位值，
    不影響技術面分數（分數只取決於 台積電收盤價 / OHLC）。
  * 技術面圖表在回測中不產生（_generate_technical_chart 已停用），避免雜訊。
  * 綜合燈號 = 財務30% + 大廠30% + 技術20% + 籌碼20%；財務/大廠=100 時，
    綜合得分 = 60 + 0.2×(技術+籌碼)，故單靠技術/籌碼不會低於 60（黃燈區下緣）；
    紅燈僅由結構性轉折訊號（reversal_advanced）強制觸發。

用法：
  python backtest_crash_signals.py              # 預設抓 1200 天歷史
  python backtest_crash_signals.py --no-cache   # 強制重抓
  python backtest_crash_signals.py --csv out.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv

import historical_crash_days as hcd
from config import CONFIG
from sal.providers import get_finmind
from signal_engine import (
    BigTechSignals,
    ChipSignals,
    FinancialSignals,
    SignalEngine,
    TechnicalSignals,
    score_to_alert,
)
from tsmc_ai_agents import InstitutionalInvestorAgent, MarketDynamicsAgent

# 停用技術面圖表產生（回測不需要 PNG，且避免字型/IO 雜訊）
MarketDynamicsAgent._generate_technical_chart = lambda self, df: ""  # type: ignore[assignment]

# ──────────────────────────────────────────────
# 崩盤日清單（來自 historical_crash_days.py 兩年視窗，門檻 -5%）
# (崩盤日, 次日跌幅%)
# ──────────────────────────────────────────────
CRASH_DATES: List[Tuple[dt.date, float]] = [
    (dt.date(2024, 7, 26), -5.62),
    (dt.date(2024, 8, 2), -5.94),
    (dt.date(2024, 8, 5), -9.75),
    (dt.date(2024, 9, 4), -5.43),
    (dt.date(2025, 2, 3), -5.73),
    (dt.date(2025, 4, 7), -9.98),
    (dt.date(2026, 7, 17), -7.29),  # 7/16 為其前一日（原 7/16 測試）
]


# ──────────────────────────────────────────────
# 資料抓取
# ──────────────────────────────────────────────
def fetch_yahoo_ohlcv(symbol: str, period1: int, period2: int,
                      use_cache: bool = True) -> pd.DataFrame:
    """抓取 Yahoo OHLCV，回傳以台灣日曆日為索引的 DataFrame。"""
    cache_key = f"yahoo_ohlcv_{symbol}_{period1}_{period2}"
    if use_cache:
        c = hcd._read_cache(cache_key)
        if c is not None:
            print(f"  -> 使用快取: {cache_key}")
            df = pd.DataFrame.from_records(c)
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date").sort_index()
    recs = []
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{hcd.YAHOO_URL}/{symbol}",
                params={"period1": period1, "period2": period2,
                        "interval": "1d", "events": "history"},
                headers={"User-Agent": hcd.USER_AGENT, "Accept": "application/json"},
                timeout=30,
            )
            payload = resp.json()
            break
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(f"Yahoo {symbol} OHLCV 抓取失敗: {last_err}") from last_err

    ch = (payload.get("chart") or {}).get("result")
    if not ch:
        raise RuntimeError(f"Yahoo {symbol} 無資料: {payload.get('chart')}")
    res = ch[0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    for i, t in enumerate(ts):
        d = hcd._ts_to_tpe_date(t)
        recs.append({
            "date": pd.Timestamp(d),
            "open": q["open"][i], "high": q["high"][i],
            "low": q["low"][i], "close": q["close"][i], "volume": q["volume"][i],
        })
    df = pd.DataFrame(recs).dropna(subset=["close"]).set_index("date").sort_index()
    if use_cache:
        hcd._write_cache(cache_key, df.reset_index().assign(
            date=df.index.astype(str)).to_dict("records"))
    print(f"  -> Yahoo {symbol} OHLCV: {len(df)} 日")
    return df


def fetch_finmind_inst_rows(stock_id: str, start: dt.date, end: dt.date,
                            use_cache: bool = True) -> List[Dict]:
    """抓取 FinMind 三大法人買賣超原始資料（所有法人類別）。"""
    cache_key = f"finmind_inst_rows_{stock_id}_{start}_{end}"
    if use_cache:
        c = hcd._read_cache(cache_key)
        if c is not None:
            print(f"  -> 使用快取: {cache_key}")
            return c
    if not hcd.FINMIND_TOKEN:
        print("  !! 未設定 FINMIND_TOKEN，籌碼面將無法計算")
        return []
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "token": hcd.FINMIND_TOKEN,
    }
    try:
        resp = requests.get(hcd.FINMIND_API_URL, params=params,
                            headers={"User-Agent": hcd.USER_AGENT}, timeout=30)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  !! FinMind 抓取失敗: {exc}")
        return []
    if data.get("status") != 200:
        print(f"  !! FinMind 錯誤: {data.get('msg')}")
        return []
    rows = [
        {"date": x.get("date"), "name": x.get("name"),
         "buy": int(x.get("buy") or 0), "sell": int(x.get("sell") or 0)}
        for x in data.get("data", [])
    ]
    if use_cache:
        hcd._write_cache(cache_key, rows)
    print(f"  -> FinMind 三大法人: {len(rows)} 筆")
    return rows


def fetch_finmind_shareholding(stock_id: str, start: dt.date, end: dt.date,
                               use_cache: bool = True) -> List[Dict]:
    """抓取 FinMind 外資持股 (TaiwanStockShareholding)：外資持股股數 / 總股數。"""
    cache_key = f"finmind_shareholding_{stock_id}_{start}_{end}"
    if use_cache:
        c = hcd._read_cache(cache_key)
        if c is not None:
            print(f"  -> 使用快取: {cache_key}")
            return c
    if not hcd.FINMIND_TOKEN:
        print("  !! 未設定 FINMIND_TOKEN，無法取得外資持股")
        return []
    params = {
        "dataset": "TaiwanStockShareholding",
        "data_id": stock_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "token": hcd.FINMIND_TOKEN,
    }
    try:
        resp = requests.get(hcd.FINMIND_API_URL, params=params,
                            headers={"User-Agent": hcd.USER_AGENT}, timeout=30)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  !! FinMind 持股抓取失敗: {exc}")
        return []
    if data.get("status") != 200:
        print(f"  !! FinMind 持股錯誤: {data.get('msg')}")
        return []
    rows = [
        {
            "date": x.get("date"),
            "foreign_shares": int(x.get("ForeignInvestmentShares") or 0),
            "total_shares": int(x.get("NumberOfSharesIssued") or 0),
            "foreign_ratio": float(x.get("ForeignInvestmentSharesRatio") or 0),
        }
        for x in data.get("data", [])
    ]
    if use_cache:
        hcd._write_cache(cache_key, rows)
    print(f"  -> FinMind 外資持股: {len(rows)} 筆")
    return rows


# ──────────────────────────────────────────────
# 資料整形
# ──────────────────────────────────────────────
def build_tech_df(slice_df: pd.DataFrame, twii: Dict[dt.date, float]) -> pd.DataFrame:
    """將 OHLCV 切片轉為 MarketDynamicsAgent 所需的欄位 schema。"""
    rows = []
    for ts, r in slice_df.iterrows():
        d = ts.date()
        twii_close = twii.get(d)
        tsmc_turnover = (float(r["close"]) * float(r["volume"])) if r.get("volume") else 0.0
        # 大盤成交金額：Yahoo 未取得，使用 TAIEX 收盤指數的佔位倍率（僅供量價背離敘事）
        mkt_turnover = (float(twii_close) * 1e9) if twii_close else 0.0
        rows.append({
            "日期": pd.Timestamp(d),
            "台積電開盤價": float(r["open"]) if pd.notna(r["open"]) else float(r["close"]),
            "台積電最高價": float(r["high"]) if pd.notna(r["high"]) else float(r["close"]),
            "台積電最低價": float(r["low"]) if pd.notna(r["low"]) else float(r["close"]),
            "台積電收盤價": float(r["close"]),
            "台積電成交金額": tsmc_turnover,
            "大盤成交金額": mkt_turnover,
        })
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────
# 歷史本益比（用於回測各 as-of 的 P/E）
# ──────────────────────────────────────────────
def load_quarterly_eps(use_cache: bool = True) -> Dict[dt.date, float]:
    """回傳 {季度末日: 基本EPS}，取自 FinMind TaiwanStockFinancialStatements。

    拉取較寬區間（2023-01-01 起）以涵蓋較早 as-of 當時可得的前四季 EPS。
    """
    fm = get_finmind()
    raw = fm._fetch(
        "TaiwanStockFinancialStatements", "2330",
        "2023-01-01", dt.date.today().isoformat(),
        cache_key="finmind_TaiwanStockFinancialStatements_2330_wide_backtest",
        cache_hours=168,
    )
    qend_eps: Dict[dt.date, float] = {}
    for r in raw:
        d = r.get("date", "")
        if not d or r.get("type") != "EPS":
            continue
        try:
            v = float(r.get("value")) if r.get("value") is not None else None
            qend = dt.date.fromisoformat(d)
        except (ValueError, TypeError):
            continue
        if v is not None:
            qend_eps[qend] = v
    return qend_eps


def compute_pe_ratio(as_of: dt.date, close: float,
                     qend_eps: Dict[dt.date, float]) -> Optional[float]:
    """本益比 = 收盤價 / 過去四季 EPS 加總（取的四季為 as-of 當時已公告、最近者）。"""
    usable = sorted(d for d in qend_eps if d <= as_of)
    trailing = usable[-4:] if len(usable) >= 4 else usable
    ttm_eps = sum(qend_eps[d] for d in trailing)
    if ttm_eps > 0:
        return close / ttm_eps
    return None


# ──────────────────────────────────────────────
# 回測主流程
# ──────────────────────────────────────────────
def run_backtest(fetch_days: int = 1200, use_cache: bool = True) -> List[dict]:
    today = dt.date.today()
    start = today - dt.timedelta(days=fetch_days)
    p1 = int(dt.datetime(start.year, start.month, start.day,
                         tzinfo=dt.timezone.utc).timestamp())
    p2 = int(dt.datetime(today.year, today.month, today.day,
                         tzinfo=dt.timezone.utc).timestamp())

    print(f"[1/3] 抓取 2330.TW OHLCV ({start} ~ {today}) ...")
    ohlcv = fetch_yahoo_ohlcv("2330.TW", p1, p2, use_cache)
    print(f"[2/3] 抓取 ^TWII 收盤指數 ...")
    twii = hcd.fetch_yahoo_close("^TWII", p1, p2, use_cache)
    print(f"[3/3] 抓取 FinMind 三大法人買賣超 (2330) ...")
    inst_rows = fetch_finmind_inst_rows("2330", start, today, use_cache)
    print(f"[*] 抓取 FinMind 外資持股 (2330) ...")
    shareholding = fetch_finmind_shareholding("2330", start, today, use_cache)
    shareholding.sort(key=lambda x: x["date"])
    print(f"[*] 抓取 FinMind 財務報表 (2330) 用於歷史本益比 ...")
    qend_eps = load_quarterly_eps(use_cache)

    price_dates = [ts.date() for ts in ohlcv.index]
    engine = SignalEngine()
    tech_agent = MarketDynamicsAgent()
    chip_agent = InstitutionalInvestorAgent()

    # 財務 / 大廠：以最新代表值（強勢）代入
    fin_signals = FinancialSignals(
        latest_revenue_yoy=40.0, latest_gross_margin=58.0,
        latest_operating_margin=45.0, latest_net_margin=40.0,
        gross_drop=0.0, op_drop=0.0, net_drop=0.0,
        revenue_yoy_declining=False, margin_deteriorating=False,
    )
    bigtech_signals = BigTechSignals(
        capex_growing_count=4, capex_valid_count=4, nvda_revenue_yoy=80.0,
    )

    results: List[dict] = []
    for crash_date, crash_ret in CRASH_DATES:
        # as-of = 嚴格早於崩盤日的最近一個交易日
        candidates = [d for d in price_dates if d < crash_date]
        if not candidates:
            print(f"  !! {crash_date} 之前無價格資料，跳過")
            continue
        as_of = candidates[-1]

        row: dict = {"crash_date": crash_date, "as_of": as_of, "crash_ret": crash_ret}

        try:
            # 技術面
            tech_slice = ohlcv[ohlcv.index <= pd.Timestamp(as_of)]
            df = build_tech_df(tech_slice, twii)
            _, tech_flags, tech_scores, _ = tech_agent.analyze_sentiment(df)
            # 歷史本益比（收盤價 / 過去四季 EPS）
            close = float(tech_slice.iloc[-1]["close"])
            pe_ratio = compute_pe_ratio(as_of, close, qend_eps)
            # 籌碼面
            as_of_str = as_of.isoformat()
            chip_data = [r for r in inst_rows if r["date"] <= as_of_str]
            _, chip_flags, chip_score = chip_agent.analyze_flow(chip_data, df)

            tech_signals = TechnicalSignals(scores=tech_scores, flags=tech_flags)
            chip_signals = ChipSignals(score=chip_score, flags=chip_flags)
            res = engine.analyze(fin_signals, bigtech_signals, tech_signals, chip_signals)

            # ── 外資兩個月累計淨買賣佔持股比 ──
            cutoff = (as_of - dt.timedelta(days=CONFIG.chip.two_month_window_days)).isoformat()
            net_2m_shares = sum(
                (r["buy"] - r["sell"]) for r in inst_rows
                if r["name"] == "Foreign_Investor" and cutoff <= r["date"] <= as_of_str
            )
            foreign_2m_lots = net_2m_shares / 1000.0
            # 外資當日實際持股（強制紅燈分母：用外資持股而非總流通股）
            hold = next((sh for sh in reversed(shareholding) if sh["date"] <= as_of_str), None)
            foreign_shares_as_of = (hold["foreign_shares"] if (hold and hold.get("foreign_shares"))
                                    else CONFIG.chip.tsmc_float_shares)
            # 外資高檔出貨強制紅燈：P/E > 門檻 且 兩月淨賣超超過「外資當日持股」之門檻比例
            sellout_threshold = CONFIG.chip.two_month_high_sellout_pct * foreign_shares_as_of
            forced_red = (pe_ratio is not None
                          and pe_ratio > CONFIG.chip.high_sellout_pe_threshold
                          and net_2m_shares < -sellout_threshold)
            if hold and hold["foreign_shares"] > 0:
                foreign_holdings_lots = hold["foreign_shares"] / 1000.0
                total_shares_lots = hold["total_shares"] / 1000.0
                pct_of_foreign_holdings = foreign_2m_lots / foreign_holdings_lots * 100
                pct_of_total_shares = foreign_2m_lots / total_shares_lots * 100
            else:
                foreign_holdings_lots = None
                pct_of_foreign_holdings = None
                pct_of_total_shares = None

            c_level, c_label, c_emoji = res.alert_level, res.alert_label, res.alert_emoji
            k_level, k_label, k_emoji = score_to_alert(chip_score)

            row.update({
                "composite_level": c_level, "composite_label": c_label,
                "composite_emoji": c_emoji, "composite_score": res.comprehensive_score,
                "chip_level": k_level, "chip_label": k_label, "chip_emoji": k_emoji,
                "chip_score": chip_score,
                "tech_early": tech_scores.get("early", 0),
                "tech_short": tech_scores.get("short", 0),
                "tech_mid": tech_scores.get("mid", 0),
                "tech_long": tech_scores.get("long", 0),
                "tech_combined": res.tech_score,
                "foreign_5d_lots": (chip_flags.get("foreign_net_sell_shares") or 0) / 1000.0,
                "sell_ratio": chip_flags.get("sell_ratio", 0),
                "max_consecutive_sell": chip_flags.get("max_consecutive_sell", 0),
                "foreign_2m_lots": foreign_2m_lots,
                "foreign_holdings_lots": foreign_holdings_lots,
                "pct_of_foreign_holdings": pct_of_foreign_holdings,
                "pct_of_total_shares": pct_of_total_shares,
                "pe_ratio": pe_ratio,
                "pe_threshold": CONFIG.chip.high_sellout_pe_threshold,
                "forced_red": forced_red,
                "reversal_basic": res.reversal_signal,
                "reversal_advanced": res.reversal_advanced,
                "ma20_cross": tech_flags.get("ma20_cross_below", False),
                "monthly_break": tech_flags.get("monthly_break_ma12", False),
                "bb_squeeze_break": tech_flags.get("bb_squeeze_break", False),
                "error": None,
            })
            # 警示：綜合黃/紅燈、轉折訊號、或籌碼面偏弱
            warned = (c_level in ("yellow", "red") or res.reversal_signal
                      or k_level in ("yellow", "red"))
            row["warned"] = warned
        except Exception as exc:  # 單日分析失敗不中斷整體
            row.update({"error": str(exc), "warned": None})
            print(f"  !! {as_of} 分析失敗: {exc}")

        results.append(row)
    return results


# ──────────────────────────────────────────────
# 輸出
# ──────────────────────────────────────────────
def to_markdown(results: List[dict]) -> str:
    lines = []
    lines.append("# 崩盤日前一日 綜合燈號 / 籌碼面燈號 回測")
    lines.append("")
    lines.append("範圍：七個崩盤日的前一個交易日（as-of）。財務/大廠以最新代表值(=100)代入；")
    lines.append(f"本益比為各 as-of 當時真實收盤價 / 過去四季 EPS。強制紅燈條件：P/E > {CONFIG.chip.high_sellout_pe_threshold:.0f} "
                 f"且外資兩月淨賣超 > 外資當日實際持股之 {CONFIG.chip.two_month_high_sellout_pct*100:.0f}%（分母改用各 as-of 外資持股，非總流通股）。")
    lines.append("")
    lines.append("| 崩盤日 | as-of(前一日) | 次日跌幅 | 綜合燈號 | 綜合分 | 籌碼面燈號 | 籌碼分 | 技術(早/短/中/長) | 外資5日(張) | 賣超比 | 連續賣超 | 外資2月(張) | 佔外資持股% | 佔總股% | 本益比 | 強制紅燈? | 轉折 | 警示 |")
    lines.append("|------|------|------:|------|------:|------|------:|------|------:|------:|------:|------:|------:|------:|------:|------|------|------|")
    for r in results:
        if r.get("error"):
            lines.append(f"| {r['crash_date']} | {r['as_of']} | {r['crash_ret']:+.2f}% | "
                         f"分析失敗: {r['error']} |")
            continue
        tech = f"{r['tech_early']:.0f}/{r['tech_short']:.0f}/{r['tech_mid']:.0f}/{r['tech_long']:.0f}"
        rev = "進階" if r["reversal_advanced"] else ("基礎" if r["reversal_basic"] else "-")
        warn = "⚠️" if r["warned"] else "—"
        pct_f = f"{r['pct_of_foreign_holdings']:+.2f}%" if r["pct_of_foreign_holdings"] is not None else "資料缺漏"
        pct_t = f"{r['pct_of_total_shares']:+.2f}%" if r["pct_of_total_shares"] is not None else "資料缺漏"
        pe_s = f"{r['pe_ratio']:.1f}" if r.get("pe_ratio") is not None else "資料缺漏"
        fred = "🔴強制" if r.get("forced_red") else "-"
        lines.append(
            f"| {r['crash_date']} | {r['as_of']} | {r['crash_ret']:+.2f}% | "
            f"{r['composite_emoji']}{r['composite_label']} | {r['composite_score']:.1f} | "
            f"{r['chip_emoji']}{r['chip_label']} | {r['chip_score']:.0f} | "
            f"{tech} | {r['foreign_5d_lots']:+,.0f} | {r['sell_ratio']:.0f}% | "
            f"{r['max_consecutive_sell']}日 | {r['foreign_2m_lots']:+,.0f} | {pct_f} | {pct_t} | "
            f"{pe_s} | {fred} | {rev} | {warn} |"
        )
    # 小計
    n = len([r for r in results if not r.get("error")])
    warned = len([r for r in results if r.get("warned")])
    lines.append("")
    lines.append(f"共 {n} 個 as-of 日期；其中 {warned} 個在崩盤前已出現警示（綜合黃/紅燈、轉折訊號或籌碼面偏弱）。")
    return "\n".join(lines)


def to_csv(results: List[dict], path: str) -> None:
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["崩盤日", "as_of前一日", "次日跌幅%", "綜合燈號", "綜合分",
                    "籌碼面燈號", "籌碼分", "技術早", "技術短", "技術中", "技術長",
                    "外資5日淨張", "賣超比%", "連續賣超日", "外資2月淨張",
                    "外資總持股張", "佔外資持股%", "佔總股%", "本益比", "PE門檻", "強制紅燈",
                    "轉折基礎", "轉折進階", "ma20破", "月線破MA12", "布林壓縮破",
                    "警示", "錯誤"])
        for r in results:
            if r.get("error"):
                w.writerow([r["crash_date"], r["as_of"], f"{r['crash_ret']:.2f}",
                            "ERROR", "", "", "", "", "", "", "", "", "", "", "",
                            "", "", "", "", "", "", "",
                            "", "", "", "", "", r["error"]])
                continue
            w.writerow([
                r["crash_date"], r["as_of"], f"{r['crash_ret']:.2f}",
                r["composite_label"], f"{r['composite_score']:.1f}",
                r["chip_label"], f"{r['chip_score']:.0f}",
                r["tech_early"], r["tech_short"], r["tech_mid"], r["tech_long"],
                f"{r['foreign_5d_lots']:.0f}", f"{r['sell_ratio']:.0f}",
                r["max_consecutive_sell"], f"{r['foreign_2m_lots']:.0f}",
                f"{(r['foreign_holdings_lots'] or 0):.0f}",
                f"{(r['pct_of_foreign_holdings'] or 0):.2f}",
                f"{(r['pct_of_total_shares'] or 0):.2f}",
                f"{r['pe_ratio']:.1f}" if r.get("pe_ratio") is not None else "",
                f"{r['pe_threshold']:.0f}", r["forced_red"],
                r["reversal_basic"], r["reversal_advanced"],
                r["ma20_cross"], r["monthly_break"], r["bb_squeeze_break"],
                r["warned"], "",
            ])
    print(f"\nCSV 已寫入: {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="崩盤日前一日燈號回測")
    ap.add_argument("--days", type=int, default=1200,
                    help="歷史資料抓取天數 (預設 1200)")
    ap.add_argument("--csv", type=str, default="backtest_crash_signals.csv",
                    help="CSV 輸出路徑")
    ap.add_argument("--no-cache", action="store_true", help="忽略快取強制重抓")
    args = ap.parse_args()

    try:
        results = run_backtest(args.days, use_cache=not args.no_cache)
    except RuntimeError as exc:
        print(f"錯誤: {exc}", file=sys.stderr)
        return 1

    print("\n" + to_markdown(results))
    to_csv(results, args.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
