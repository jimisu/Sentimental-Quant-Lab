#!/usr/bin/env python3
"""
TSMC 全球宏觀 Agent
負責 ADR 折溢價與外部市場資料分析。
"""

import argparse
import functools
import json
import os
import re
import time
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 引入統一快取層，取代私有快取函式
from data_cache import fetch_with_cache

SEC_HEADERS = {
    "User-Agent": "Sentimental-Quant-Lab/1.0 contact@example.com",
    "Accept-Encoding": "gzip, deflate",
}

# 不再使用私有快取目錄，統一由 data_cache 管理（local_cache/）
# 保留常數供參考，但不再寫入 local_cache/macro_agent/
CACHE_MAX_AGE_DAYS = 7  # 與 data_cache.DATA_POLICIES["macro_capex"] 一致


# CAPEX 分析公司（只留這 4 家作為大廠基本面指標）
CAPEX_COMPANIES = {
    "Microsoft": {"ticker": "MSFT", "cik": "0000789019"},
    "Meta":      {"ticker": "META", "cik": "0001326801"},
    "Google":    {"ticker": "GOOGL", "cik": "0001652044"},
    "Amazon":    {"ticker": "AMZN", "cik": "0001018724"},
}

# NVDA 營收 YoY（單獨抓取財報資料）
NVDA_CIK = "0001045810"
NVDA_TICKER = "NVDA"

CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "CapitalExpendituresIncurredButNotYetPaid",
]


class GlobalMacroAgent:
    """
    Agent 4: 全球市場連動專家
    監控 ADR 折溢價、費城半導體指數 (SOX) 以及美股主要客戶動態。
    """
    def __init__(self):
        self.name = "全球宏觀 Agent"
        self.source = "Yahoo Finance (TSM ADR & TWD=X)"
        self.logic = "分析美股 ADR 溢價狀況與美元/台幣匯率，捕捉台積電外部需求變化。"
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "Sentimental-Quant-Lab/1.0 (+https://github.com/jimisu)",
        })

    def summarize(self, analysis: str) -> str:
        return f"[{self.name}] 報告摘要: {analysis}"

    def _http_get_json(self, url: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, str]] = None, timeout: int = 20) -> Dict:
        try:
            resp = self.session.get(url, headers=headers, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP request failed: {exc}")
        except ValueError as exc:
            raise RuntimeError(f"無效 JSON 回傳: {exc}")

    def _fetch_json_with_cache(self, cache_key: str, url: str, policy_name: str = "macro_capex",
                              headers: Optional[Dict[str, str]] = None,
                              params: Optional[Dict[str, str]] = None,
                              timeout: int = 20) -> Dict:
        # 使用統一快取層（data_cache）取代私有函式
        return fetch_with_cache(
            policy_name=policy_name,
            cache_key=cache_key,
            fetch_fn=lambda: self._http_get_json(url, headers=headers, params=params, timeout=timeout),
        )

    def analyze_global_risk(self, tw_price: float) -> Tuple[str, int]:
        """分析 ADR 折溢價與匯率（純宏觀面，不含 CAPEX）"""
        if tw_price <= 0:
            return "宏觀專家: 無法取得台股收盤價，跳過 ADR 分析。", 100

        try:
            tsm_price = self._fetch_yahoo_price("TSM")
            usdtwd = self._fetch_yahoo_price("TWD=X")

            # 1 TSM ADR = 5 2330 Ordinary Shares
            adr_tw_equiv = (tsm_price * usdtwd) / 5
            premium = (adr_tw_equiv - tw_price) / tw_price * 100

            score = 100
            if premium < -1:
                score -= 40
            elif premium < 0:
                score -= 20

            status = "溢價" if premium >= 0 else "折價"
            conclusion = f"{status} {abs(premium):.2f}% (ADR折算價: {adr_tw_equiv:.2f} / 台股現價: {tw_price:.2f})"

            report = (
                f"數據來源: {self.source}\n"
                f"分析邏輯: {self.logic}\n"
                f"結論: {conclusion}\n"
                f"匯率參考: {usdtwd:.2f}"
            )
            return report, score
        except Exception as e:
            return f"⚠️ 宏觀專家: 外部數據抓取失敗 ({e})，請檢查網路連線或 API 狀態。", 100

    def analyze_bigtech_fundamentals(self, quarterly_data: Dict = None) -> Tuple[Dict, str]:
        """
        分析大廠基本面：CAPEX 趨勢（4 家）+ NVDA 營收 YoY + TSMC EPS 預估。

        參數：
        - quarterly_data: 可選，FinMind 季度財務資料（含 EPS），用於推算 2026 預估 EPS

        回傳：
        - data: dict 包含 capex_growing_count, capex_valid_count, nvda_revenue_yoy, score, capex_score, nvda_score
        - report: 文字報告
        """
        report_lines = [
            "【大廠基本面分析】",
            f"CAPEX 分析對象: {', '.join(CAPEX_COMPANIES.keys())}",
            "數據來源: SEC 官方 10-Q/10-K 財報 XBRL facts。",
        ]
        growing_count = 0
        valid_count = 0

        for company_name, meta in CAPEX_COMPANIES.items():
            try:
                quarters = self._fetch_recent_capex_quarters(meta)
                if len(quarters) < 3:
                    report_lines.append(f"- {company_name} ({meta['ticker']}): 資料不足，無法判斷近三季趨勢。")
                    continue

                valid_count += 1
                oldest, middle, latest = quarters[-1], quarters[-2], quarters[-3]
                is_growing = oldest["value"] < middle["value"] < latest["value"]
                if is_growing:
                    growing_count += 1

                trend = "持續成長" if is_growing else "未持續成長"
                values = " -> ".join(
                    f"{q['period']} {self._format_usd_billions(q['value'])} [{q['method']}; {q['accession']}]"
                    for q in (oldest, middle, latest)
                )
                latest_source = latest.get("sec_filing_url", "")
                source_suffix = f"；最新 filing: {latest_source}" if latest_source else ""
                report_lines.append(f"- {company_name} ({meta['ticker']}): {trend}，{values}{source_suffix}")
            except Exception as exc:
                report_lines.append(f"- {company_name} ({meta['ticker']}): 抓取失敗 ({exc})")

        # ── CAPEX 結論 ──
        if valid_count == 0:
            report_lines.append("CAPEX 結論: 無可用資料。")
            capex_score = 100
        else:
            ratio = growing_count / valid_count
            if ratio >= 0.75:
                capex_score = 100
                report_lines.append(f"CAPEX 結論: {growing_count}/{valid_count} 家持續成長，AI/雲端需求動能偏強。")
            elif ratio >= 0.5:
                capex_score = 75
                report_lines.append(f"CAPEX 結論: {growing_count}/{valid_count} 家持續成長，需求動能放緩。")
            elif ratio >= 0.25:
                capex_score = 50
                report_lines.append(f"CAPEX 結論: 僅 {growing_count}/{valid_count} 家持續成長，分歧。")
            else:
                capex_score = 25
                report_lines.append(f"CAPEX 結論: 僅 {growing_count}/{valid_count} 家持續成長，全面放緩。")

        # ── NVDA 營收 YoY ──
        nvda_yoy = None
        nvda_score = 100
        nvda_quarters = []
        try:
            nvda_yoy, nvda_quarters = self._fetch_nvda_revenue_yoy()
            if nvda_yoy is not None:
                if nvda_yoy >= 50:
                    nvda_score = 100
                    report_lines.append(f"- NVDA 營收 YoY: {nvda_yoy:.1f}%（AI 需求爆發）")
                elif nvda_yoy >= 20:
                    nvda_score = 80
                    report_lines.append(f"- NVDA 營收 YoY: {nvda_yoy:.1f}%（穩健成長）")
                elif nvda_yoy >= 0:
                    nvda_score = 60
                    report_lines.append(f"- NVDA 營收 YoY: {nvda_yoy:.1f}%（成長趨緩）")
                else:
                    nvda_score = 40
                    report_lines.append(f"- NVDA 營收 YoY: {nvda_yoy:.1f}%（負成長）")
                # 列出過去三季 YoY
                if nvda_quarters:
                    report_lines.append("  過去三季營收 YoY：")
                    for q in nvda_quarters:
                        report_lines.append(f"    · {q['period']}: {q['yoy']:.1f}%")
            else:
                report_lines.append("- NVDA 營收 YoY: 資料不足")
        except Exception as exc:
            report_lines.append(f"- NVDA 營收 YoY: 抓取失敗 ({exc})")

        # ── 綜合大廠分數（CAPEX 50% + NVDA 50%）──
        if nvda_yoy is None:
            combined_score = capex_score
        else:
            combined_score = int(capex_score * 0.5 + nvda_score * 0.5)

        report_lines.append(f"\n大廠基本面綜合分數: {combined_score}/100（CAPEX {capex_score} / NVDA {nvda_score}）")

        # ── TSMC 2026 預估 EPS ──
        try:
            # 從 quarterly_data 取得 EPS 歷史資料
            eps_est = self._fetch_tsm_eps_estimate(quarterly_data)
            if eps_est:
                report_lines.append(f"\n【TSMC 2026 預估 EPS】")
                if "eps_detail" in eps_est:
                    report_lines.append(f"  過去四季 EPS：{eps_est['eps_detail']}")
                if "eps_trailing_4q" in eps_est:
                    report_lines.append(f"  過去 4 季加總：{eps_est['eps_trailing_4q']:.2f} 元")
                if "eps_q1_2026" in eps_est:
                    report_lines.append(f"  2026 Q1 EPS：{eps_est['eps_q1_2026']:.2f} 元")
                if "eps_2026_estimate" in eps_est:
                    report_lines.append(f"  2026 全年預估 EPS：{eps_est['eps_2026_estimate']:.2f} 元（依 Q1 比例推算）")
                elif "eps_2026_annualized" in eps_est:
                    report_lines.append(f"  2026 全年預估 EPS：{eps_est['eps_2026_annualized']:.2f} 元（Q1 年化）")
            else:
                report_lines.append(f"\n【TSMC 2026 預估 EPS】資料不足")
        except Exception as exc:
            report_lines.append(f"\n【TSMC 2026 預估 EPS】抓取失敗 ({exc})")

        data = {
            "capex_growing_count": growing_count,
            "capex_valid_count": valid_count,
            "capex_score": capex_score,
            "nvda_revenue_yoy": nvda_yoy,
            "nvda_revenue_yoy_quarters": nvda_quarters,
            "nvda_score": nvda_score,
            "score": combined_score,
        }
        return data, "\n".join(report_lines)

    def _fetch_tsm_eps_estimate(self, quarterly_data: Dict = None) -> Optional[Dict]:
        """
        根據 FinMind 歷史 EPS 資料推算 TSMC 2026 全年預估 EPS。
        使用過去 4 季 EPS 年化 + Q1 2026 推算全年。
        回傳 dict 包含 eps_trailing_4q, eps_2026_estimate 或 None。
        """
        eps_info = {}

        if quarterly_data:
            sorted_keys = sorted(quarterly_data.keys(), reverse=True)
            eps_values = []
            for k in sorted_keys:
                ev = quarterly_data[k].get("eps")
                if ev is not None:
                    eps_values.append((k, ev))

            if len(eps_values) >= 1:
                # 過去 4 季 EPS 加總（年化基準）
                trailing_4q = sum(v for _, v in eps_values[:4])
                eps_info["eps_trailing_4q"] = round(trailing_4q, 2)

                # 2026 全年預估：若已有 Q1 2026，用 Q1 × 4 或 Q1 / 過去 Q1 比例推算
                q1_2026 = None
                q1_2025 = None
                for (y, q), v in eps_values:
                    if y == 2026 and q == 1:
                        q1_2026 = v
                    if y == 2025 and q == 1:
                        q1_2025 = v

                if q1_2026 is not None:
                    # 方法一：Q1 年化 × 4
                    eps_2026_annualized = round(q1_2026 * 4, 2)
                    eps_info["eps_2026_annualized"] = eps_2026_annualized

                    # 方法二：用 Q1 佔去年全年比例推算
                    if q1_2025 is not None and q1_2025 > 0:
                        # 2025 全年 EPS
                        eps_2025_total = sum(v for (y, q), v in eps_values if y == 2025)
                        if eps_2025_total > 0:
                            q1_ratio = q1_2025 / eps_2025_total
                            if q1_ratio > 0:
                                eps_2026_estimate = round(q1_2026 / q1_ratio, 2)
                                eps_info["eps_2026_estimate"] = eps_2026_estimate

                    eps_info["eps_q1_2026"] = q1_2026

                # 過去四季 EPS 明細
                eps_detail = " → ".join(f"{y}Q{q}: {v:.2f}" for (y, q), v in eps_values[:4])
                eps_info["eps_detail"] = eps_detail

        return eps_info if eps_info else None

    def _fetch_nvda_revenue_yoy(self) -> Tuple[Optional[float], List[Dict]]:
        """
        從 SEC XBRL 抓取 NVDA 過去三季的營收 YoY%。
        回傳：(latest_yoy, quarters)
          - latest_yoy: 最新一季 YoY% 或 None
          - quarters: list of {"period": str, "yoy": float}，最多三季（新→舊）
        """
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{NVDA_CIK}.json"
        cache_key = f"sec_companyfacts_{NVDA_CIK}"

        try:
            data = self._fetch_json_with_cache(
                cache_key, url, policy_name="nvda_revenue",
                headers=SEC_HEADERS, timeout=20,
            )
        except Exception:
            return None, []

        facts = data.get("facts", {}).get("us-gaap", {})

        # 嘗試不同的營收 tag
        revenue_tags = [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ]

        for tag in revenue_tags:
            entries = facts.get(tag, {}).get("units", {}).get("USD", [])
            if not entries:
                continue

            # 篩選單季（非 YTD）的 10-Q/10-K entries
            quarterly = [
                e for e in entries
                if e.get("form") in {"10-Q", "10-K"}
                and e.get("fp") in {"Q1", "Q2", "Q3", "Q4", "FY"}
                and e.get("val") is not None
            ]

            if len(quarterly) < 2:
                continue

            # 按 end date 排序（舊→新）
            quarterly.sort(key=lambda e: e.get("end", ""))

            # 對每一季（從最新的最多三季）計算 YoY
            quarters = []
            for i in range(len(quarterly) - 1, max(len(quarterly) - 4, -1), -1):
                if len(quarters) >= 3:
                    break
                cur = quarterly[i]
                cur_val = float(cur["val"])
                cur_end = date.fromisoformat(cur["end"])
                target_date = cur_end - timedelta(days=365)

                # 找去年同季（排除自己）
                best_match = None
                best_diff = None
                for j, e in enumerate(quarterly):
                    if j == i:
                        continue
                    e_end = date.fromisoformat(e.get("end", "2000-01-01"))
                    diff = abs((e_end - target_date).days)
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        best_match = e

                if best_match is None or best_diff is None or best_diff > 60:
                    continue

                prev_val = float(best_match["val"])
                if prev_val <= 0:
                    continue

                yoy = (cur_val - prev_val) / prev_val * 100
                period_label = f"{cur.get('fp', '?')} ({cur['end']})"
                quarters.append({"period": period_label, "yoy": yoy})

            if quarters:
                latest_yoy = quarters[0]["yoy"]
                return latest_yoy, quarters

        return None, []

    def _fetch_yahoo_price(self, ticker: str) -> float:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        # 使用統一快取層，1 小時 TTL（macro_adr policy）
        data = fetch_with_cache(
            policy_name="macro_adr",
            cache_key=f"yahoo_price_{ticker}",
            fetch_fn=lambda: self._http_get_json(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10),
        )

        result = data.get("chart", {}).get("result")
        if not result or not isinstance(result, list):
            raise RuntimeError("Yahoo Finance 回傳格式異常，無法解析價格。")

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            raise RuntimeError("Yahoo Finance 無法取得 regularMarketPrice。")

        return float(price)

    def _fetch_recent_capex_quarters(self, company_meta: Dict) -> List[Dict]:
        cik = company_meta["cik"]
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        cache_key = f"sec_companyfacts_{cik}"

        try:
            data = self._fetch_json_with_cache(cache_key, url, headers=SEC_HEADERS, timeout=20)
        except Exception as exc:
            raise RuntimeError(f"SEC 資料抓取失敗: {exc}")

        facts = data.get("facts", {}).get("us-gaap", {})
        best_quarters = []
        capex_tags = company_meta.get("capex_tags", CAPEX_TAGS)
        for tag in capex_tags:
            usd_entries = facts.get(tag, {}).get("units", {}).get("USD", [])
            entries = [self._normalize_capex_entry(entry, cik) for entry in usd_entries]
            quarters = self._extract_recent_capex_quarters(entries)
            if self._is_better_capex_series(quarters, best_quarters):
                best_quarters = quarters

        return best_quarters

    def _extract_recent_capex_quarters(self, entries: List[Optional[Dict]]) -> List[Dict]:
        filing_entries = [
            entry
            for entry in entries
            if entry
            and entry.get("form") in {"10-Q", "10-K"}
            and entry.get("fp") in {"Q1", "Q2", "Q3", "FY"}
            and entry.get("value") is not None
        ]

        derived = self._derive_quarterly_capex(filing_entries)
        recent = sorted(derived, key=lambda item: item["end"], reverse=True)[:3]
        if not self._has_consecutive_quarter_ends(recent):
            return []
        return recent

    def _is_better_capex_series(self, quarters: List[Dict], previous: List[Dict]) -> bool:
        if len(quarters) != len(previous):
            return len(quarters) > len(previous)
        if not quarters:
            return False
        if not previous:
            return True
        return quarters[0]["end"] > previous[0]["end"]

    def _derive_quarterly_capex(self, entries: List[Dict]) -> List[Dict]:
        order = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}
        direct_by_end = {}
        ytd_by_start_and_fp = {}

        for entry in entries:
            if self._is_single_quarter_entry(entry):
                previous = direct_by_end.get(entry["end"])
                if not previous or self._should_replace_capex_entry(entry, previous):
                    direct_by_end[entry["end"]] = {
                        **entry,
                        "period": self._calendar_period_from_end(entry["end"]),
                        "method": "direct",
                    }

            if not self._is_valid_ytd_entry(entry):
                continue

            ytd_key = (entry["start"], entry["fp"])
            previous_ytd = ytd_by_start_and_fp.get(ytd_key)
            if not previous_ytd or self._should_replace_ytd_capex_entry(entry, previous_ytd):
                ytd_by_start_and_fp[ytd_key] = entry

        derived = {}
        for entry in direct_by_end.values():
            derived[entry["end"]] = entry

        for entry in sorted(ytd_by_start_and_fp.values(), key=lambda item: (item["start"], order.get(item["fp"], 0))):
            if entry["end"] in derived:
                continue

            if entry["fp"] == "Q1":
                quarter_value = entry["value"]
                method = "direct"
            else:
                previous_fp = "Q3" if entry["fp"] == "FY" else f"Q{order[entry['fp']] - 1}"
                previous = ytd_by_start_and_fp.get((entry["start"], previous_fp))
                if not previous:
                    continue
                quarter_value = entry["value"] - previous["value"]
                method = "derived from YTD"

            if quarter_value < 0:
                continue

            derived[entry["end"]] = {
                **entry,
                "period": self._calendar_period_from_end(entry["end"]),
                "value": quarter_value,
                "method": method,
            }

        return list(derived.values())

    def _has_consecutive_quarter_ends(self, quarters: List[Dict]) -> bool:
        if len(quarters) < 3:
            return False

        ordered = sorted(quarters, key=lambda item: item["end"])
        gaps = []
        for idx in range(1, len(ordered)):
            previous_end = date.fromisoformat(ordered[idx - 1]["end"])
            current_end = date.fromisoformat(ordered[idx]["end"])
            gaps.append((current_end - previous_end).days)

        return all(75 <= gap <= 115 for gap in gaps)

    def _should_replace_capex_entry(self, entry: Dict, previous: Dict) -> bool:
        entry_is_single = self._is_single_quarter_entry(entry)
        previous_is_single = self._is_single_quarter_entry(previous)

        if entry_is_single != previous_is_single:
            return entry_is_single

        return (
            entry["filed"] > previous["filed"]
            or (entry["filed"] == previous["filed"] and entry["end"] > previous["end"])
        )

    def _should_replace_ytd_capex_entry(self, entry: Dict, previous: Dict) -> bool:
        target_days = self._target_ytd_days(entry["fp"])
        entry_diff = abs(self._entry_days(entry) - target_days)
        previous_diff = abs(self._entry_days(previous) - target_days)

        if entry_diff != previous_diff:
            return entry_diff < previous_diff

        return (
            entry["filed"] > previous["filed"]
            or (entry["filed"] == previous["filed"] and entry["end"] > previous["end"])
        )

    def _target_ytd_days(self, fiscal_period: str) -> int:
        return {
            "Q1": 90,
            "Q2": 181,
            "Q3": 273,
            "FY": 365,
        }.get(fiscal_period, 90)

    def _is_valid_ytd_entry(self, entry: Dict) -> bool:
        target_days = self._target_ytd_days(entry["fp"])
        return abs(self._entry_days(entry) - target_days) <= 25

    def _is_stale_annual_comparison(self, entry: Dict) -> bool:
        if entry.get("fp") != "FY":
            return False

        end_year = date.fromisoformat(entry["end"]).year
        return end_year < entry["fy"]

    def _is_single_quarter_entry(self, entry: Dict) -> bool:
        if entry.get("qtrs") == 1:
            return True

        return 60 <= self._entry_days(entry) <= 115

    def _entry_days(self, entry: Dict) -> int:
        start = date.fromisoformat(entry["start"])
        end = date.fromisoformat(entry["end"])
        return (end - start).days

    def _calendar_period_from_end(self, end: str) -> str:
        end_date = date.fromisoformat(end)
        quarter = (end_date.month - 1) // 3 + 1
        return f"{end_date.year}Q{quarter}"

    def _normalize_capex_entry(self, entry: Dict, cik: str) -> Optional[Dict]:
        value = entry.get("val")
        start = entry.get("start")
        end = entry.get("end")
        filed = entry.get("filed", "")
        form = entry.get("form")
        fp = entry.get("fp")
        fy = entry.get("fy")
        accession = entry.get("accn", "")

        if value is None or not start or not end or not fp or not fy:
            return None

        cik_int = str(int(cik))
        accession_path = accession.replace("-", "")
        sec_filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_path}/"
            if accession else ""
        )

        return {
            "period": f"{fy}{fp}",
            "start": start,
            "end": end,
            "filed": filed,
            "form": form,
            "fp": fp,
            "fy": int(fy),
            "frame": entry.get("frame"),
            "qtrs": entry.get("qtrs"),
            "accession": accession,
            "sec_filing_url": sec_filing_url,
            "value": abs(float(value)),
        }

    def _format_usd_billions(self, value: float) -> str:
        return f"${value / 1_000_000_000:.2f}B"


def main() -> None:
    parser = argparse.ArgumentParser(description="單獨執行全球宏觀專家分析。")
    parser.add_argument(
        "--tw-price",
        type=float,
        default=0,
        help="台積電台股收盤價；提供後會一併輸出 ADR 折溢價分析。",
    )
    parser.add_argument(
        "--bigtech",
        action="store_true",
        help="同時輸出大廠基本面分析（CAPEX + NVDA 營收 YoY）。",
    )
    args = parser.parse_args()

    agent = GlobalMacroAgent()

    # 宏觀分析（ADR + 匯率）
    if args.tw_price > 0:
        report, score = agent.analyze_global_risk(args.tw_price)
        print("=== 全球宏觀 Agent 分析 ===")
        print(report)
        print(f"\n宏觀分數: {score}/100")

    # 大廠基本面分析
    if args.bigtech or args.tw_price <= 0:
        data, report = agent.analyze_bigtech_fundamentals()
        print("\n=== 大廠基本面分析 ===")
        print(report)


if __name__ == "__main__":
    main()
