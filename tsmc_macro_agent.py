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
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CACHE_DIR = os.path.join("local_cache", "macro_agent")
CACHE_MAX_AGE_DAYS = 3

SEC_HEADERS = {
    "User-Agent": "Sentimental-Quant-Lab/1.0 contact@example.com",
    "Accept-Encoding": "gzip, deflate",
}


def _ensure_cache_dir() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)


def _safe_cache_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_")


def _cache_path(cache_key: str) -> str:
    _ensure_cache_dir()
    return os.path.join(CACHE_DIR, f"{_safe_cache_key(cache_key)}.json")


def _read_cached_payload(cache_key: str, max_age_days: int = CACHE_MAX_AGE_DAYS) -> Optional[Dict]:
    path = _cache_path(cache_key)
    if not os.path.exists(path):
        return None

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    cached_at = payload.get("cached_at")
    if not cached_at:
        return payload.get("data")

    try:
        cached_dt = datetime.fromisoformat(cached_at)
    except ValueError:
        return payload.get("data")

    if datetime.now() - cached_dt > timedelta(days=max_age_days):
        return None

    return payload.get("data")


def _write_cached_payload(cache_key: str, data: Dict) -> None:
    path = _cache_path(cache_key)
    payload = {
        "cached_at": datetime.now().isoformat(timespec="seconds"),
        "data": data,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


BIG_TECH_COMPANIES = {
    "Amazon": {"ticker": "AMZN", "cik": "0001018724"},
    "Microsoft": {"ticker": "MSFT", "cik": "0000789019"},
    "NVIDIA": {
        "ticker": "NVDA",
        "cik": "0001045810",
    },
    "Apple": {"ticker": "AAPL", "cik": "0000320193"},
    "Tesla": {"ticker": "TSLA", "cik": "0001318605"},
    "Google": {"ticker": "GOOGL", "cik": "0001652044"},
    "Meta": {"ticker": "META", "cik": "0001326801"},
}

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
        self.source = "Yahoo Finance (TSM ADR & TWD=X) / SEC 官方 10-Q/10-K filings"
        self.logic = "分析美股 ADR 溢價狀況，以及 AI 與雲端大廠資本支出趨勢，捕捉台積電外部需求變化。"
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

    def _fetch_json_with_cache(self, cache_key: str, url: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, str]] = None, timeout: int = 20) -> Dict:
        cached = _read_cached_payload(cache_key, max_age_days=CACHE_MAX_AGE_DAYS)
        if cached is not None:
            return cached

        try:
            data = self._http_get_json(url, headers=headers, params=params, timeout=timeout)
            _write_cached_payload(cache_key, data)
            return data
        except Exception as exc:
            # 若快取過期但仍可用，則以舊快取為備援
            cache_path = _cache_path(cache_key)
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, encoding="utf-8") as f:
                        payload = json.load(f)
                        return payload.get("data", {})
                except (OSError, json.JSONDecodeError):
                    pass
            raise

    def analyze_global_risk(self, tw_price: float) -> Tuple[str, int]:
        if tw_price <= 0:
            return "宏觀專家: 無法取得台股收盤價，跳過 ADR 分析。", 100

        try:
            # 取得 TSM (ADR) 與 TWD=X (匯率)
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
            capex_report, capex_score = self.analyze_big_tech_capex()
            report = f"{report}\n\n{capex_report}"
            score = min(score, capex_score)
            return report, score
        except Exception as e:
            return f"⚠️ 宏觀專家: 外部數據抓取失敗 ({e})，請檢查網路連線或 API 狀態。", 100

    def analyze_big_tech_capex(self) -> Tuple[str, int]:
        """
        抓取七家大型科技公司的近三季資本支出，並判斷是否逐季成長。
        """
        lines = [
            "【大型科技客戶資本支出分析】",
            "數據來源: 各公司遞交給 SEC 的官方 10-Q/10-K 財報；以 SEC XBRL facts 追溯 accession number 與 filing 連結。",
            "取數規則: 只採用最近三個連續季度；優先採用單季 fact，Q2/Q3/Q4 必要時以同一 tag 的 YTD 差分推算。",
        ]
        growing_count = 0
        valid_count = 0

        for company_name, meta in BIG_TECH_COMPANIES.items():
            try:
                quarters = self._fetch_recent_capex_quarters(meta)
                if len(quarters) < 3:
                    if company_name == "NVIDIA":
                        lines.append(
                            f"- {company_name} ({meta['ticker']}): 資料不足，無法判斷近三季趨勢。"
                            "已排除較廣義的 PaymentsToAcquireProductiveAssets，避免把非純 PP&E CapEx 納入。"
                        )
                    else:
                        lines.append(f"- {company_name} ({meta['ticker']}): 資料不足，無法判斷近三季趨勢。")
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
                lines.append(f"- {company_name} ({meta['ticker']}): {trend}，{values}{source_suffix}")
            except Exception as exc:
                lines.append(f"- {company_name} ({meta['ticker']}): 抓取失敗 ({exc})")

        if valid_count == 0:
            lines.append("結論: 無可用資料，暫不調整宏觀分數。")
            return "\n".join(lines), 100

        ratio = growing_count / valid_count
        if ratio >= 0.6:
            conclusion = f"結論: {growing_count}/{valid_count} 家資本支出持續成長，AI/雲端需求動能偏強。"
            score = 100
        elif ratio >= 0.3:
            conclusion = f"結論: {growing_count}/{valid_count} 家資本支出持續成長，需求動能分歧。"
            score = 85
        else:
            conclusion = f"結論: 僅 {growing_count}/{valid_count} 家資本支出持續成長，需留意大型客戶投資放緩。"
            score = 70

        lines.append(conclusion)
        return "\n".join(lines), score

    @functools.lru_cache(maxsize=8)
    def _fetch_yahoo_price(self, ticker: str) -> float:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        data = self._http_get_json(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)

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
    args = parser.parse_args()

    agent = GlobalMacroAgent()
    if args.tw_price > 0:
        report, score = agent.analyze_global_risk(args.tw_price)
    else:
        report, score = agent.analyze_big_tech_capex()

    print("=== 全球宏觀 Agent 單獨分析 ===")
    print(report)
    print(f"\n宏觀分數: {score}/100")


if __name__ == "__main__":
    main()
