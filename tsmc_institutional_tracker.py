#!/usr/bin/env python3
"""
TSMC 機構法人 13F 持倉追蹤 Agent
追蹤多個大型機構法人每季向 SEC 提交的 13F 報告，
分析其在 TSMC ADR (TSMC)、Microsoft (MSFT)、Google (GOOGL)、
Amazon (AMZN)、NVIDIA (NVDA) 的持股變化。

目前追蹤：
  - BlackRock, Inc.（貝萊德）CIK: 0002012383（BlackRock, Inc.，核心母公司，13F-HR，50,000+ holdings）
  - Bridgewater Associates, LP（橋水基金）CIK: 0001350694（Ray Dalio 創立，13F-HR）

SEC 13F 報告在每個季度結束後 45 天內提交。
數據源：SEC EDGAR Form 13F-HR（infotable.xml / .txt）

抓取排程（美東時間）：
  - 固定抓取日：2/15, 5/15, 8/15, 11/15（季度結束後 ~45 天）
  - 重試機制：抓取失敗後 24 小時重試一次
  - 其餘時間：使用 local_cache（TTL 90 天）

注意：SEC Archives 端點需要 curl_cffi（TLS 指紋偽裝）才能存取。
      持股明細在 infotable.xml（非 primary_doc.xml，後者是封面頁）。
      BlackRock 的 holdings 在 .txt 檔案（非 infotable.xml）。
      Bridgewater 的 holdings 在 infotable.xml（HTML 表格格式）。
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from data_cache import fetch_with_cache
from datetime import datetime, timedelta, timezone

# curl_cffi for bypassing SEC TLS fingerprint blocking
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

SEC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Encoding": "gzip, deflate",
}

# ── 13F 抓取排程常數 ──
# 美東時間固定抓取日（季度結束後 ~45 天）
# Q4→2/15, Q1→5/15, Q2→8/15, Q3→11/15
FETCH_MONTHS = {2, 5, 8, 11}      # 月份
FETCH_DAY = 15                     # 日
FETCH_TZ = timezone(timedelta(hours=-5))  # 美東時間 (EST, UTC-5)
FETCH_RETRY_HOURS = 24             # 失敗後重試間隔（小時）
CACHE_TTL_HOURS = 2160             # 90 天

# SEC 13F XML namespace
NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

# ── 機構法人註冊表 ──
# 每個機構以 cik 為 key，包含名稱與可選說明。
# 新增追蹤對象只需在此字典新增一筆即可。
INSTITUTION_REGISTRY: Dict[str, Dict[str, str]] = {
    "0002012383": {
        "name": "BlackRock, Inc.",
        "short_name": "BlackRock",
        "description": "全球最大資產管理機構（BlackRock, Inc.，核心母公司 CIK，13F-HR，50,000+ holdings，總持倉 ~$5.7T）",
    },
    "0001350694": {
        "name": "Bridgewater Associates, LP",
        "short_name": "Bridgewater",
        "description": "全球最大避險基金（橋水基金，Ray Dalio 創立，直接申報 13F-HR）",
    },
}

# 預設追蹤所有已註冊機構
DEFAULT_TRACKED_CIKs = list(INSTITUTION_REGISTRY.keys())


# ── 排程輔助函數 ──

def _today_eastern() -> datetime:
    """取得目前美東時間"""
    return datetime.now(tz=FETCH_TZ)


def is_fetch_day() -> bool:
    """
    判斷今天是否為 13F 固定抓取日（美東時間 2/15, 5/15, 8/15, 11/15）
    """
    today = _today_eastern()
    return today.month in FETCH_MONTHS and today.day == FETCH_DAY


def should_fetch_from_sec(cache_key: str) -> bool:
    """
    判斷是否應該從 SEC 抓取新資料（而非使用 local cache）

    規則：
    1. 固定抓取日（美東 2/15, 5/15, 8/15, 11/15）→ 抓取
    2. 抓取日後 24 小時內（重試窗口）→ 抓取
    3. 其餘時間 → 使用 cache（不抓取）
    """
    from data_cache import read_cache as _read_cache

    # 固定抓取日：強制重新抓取
    if is_fetch_day():
        return True

    # 檢查是否有「抓取失敗標記」（24 小時重試窗口）
    retry_flag_key = f"sec_13f_retry_{cache_key}"
    retry_flag = _read_cache(retry_flag_key, max_age_hours=FETCH_RETRY_HOURS)
    if retry_flag is not None:
        return True  # 24 小時內重試

    # 其餘時間：使用 cache
    return False


def mark_fetch_failed(cache_key: str) -> None:
    """標記抓取失敗，觸發 24 小時重試窗口"""
    import json as _json
    flag_key = f"sec_13f_retry_{cache_key}"
    cache_path = os.path.join("local_cache", f"{flag_key}_{_today_eastern().strftime('%Y%m%d_%H%M%S')}.json")
    with open(cache_path, 'w') as fh:
        _json.dump({"cached_at": _today_eastern().isoformat(), "data": "retry"}, fh)

# ── 目標持股（使用名稱匹配，比 CUSIP 更可靠）──
TARGET_COMPANIES = {
    "TSM": {
        "name": "TSMC",
        "match_names": ["TAIWAN SEMICONDUCTOR", "TSMC", "TAIWAN SEMICONDUCTOR MFG"],
    },
    "MSFT": {
        "name": "Microsoft",
        "match_names": ["MICROSOFT CORP", "MICROSOFT CORPORATION"],
    },
    "GOOGL": {
        "name": "Alphabet (Google)",
        "match_names": ["ALPHABET INC", "ALPHABET INC.", "GOOGLE INC"],
    },
    "AMZN": {
        "name": "Amazon",
        "match_names": ["AMAZON COM INC", "AMAZON.COM INC", "AMAZON COM INC."],
    },
    "NVDA": {
        "name": "NVIDIA",
        "match_names": ["NVIDIA CORP", "NVIDIA CORPORATION", "NVIDIA CORP."],
    },
}


def _match_name(issuer_name: str, match_names: List[str]) -> bool:
    """檢查 issuer name 是否匹配目標公司"""
    if not issuer_name:
        return False
    issuer_upper = issuer_name.upper().strip()
    for mn in match_names:
        if mn.upper() in issuer_upper:
            return True
    return False


class InstitutionalTrackerAgent:
    """
    機構法人 13F 持倉追蹤 Agent
    抓取 SEC EDGAR 13F 報告，分析目標持股的季度變化。
    支援同時追蹤多個機構法人（BlackRock、Bridgewater 等）。
    """

    def __init__(self, tracked_ciks: Optional[List[str]] = None):
        self.name = "機構法人 13F 追蹤 Agent"
        self.source = "SEC EDGAR Form 13F-HR"
        self.logic = "追蹤大型機構法人每季 13F 持倉變化，分析 TSMC 與四大科技巨頭持股方向。"
        self.tracked_ciks = tracked_ciks or DEFAULT_TRACKED_CIKs
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
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

    def _http_get(self, url: str, headers: Optional[Dict[str, str]] = None,
                  timeout: int = 30) -> requests.Response:
        try:
            resp = self.session.get(url, headers=headers or SEC_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP request failed: {url} — {exc}")

    def _http_get_json(self, url: str, timeout: int = 30) -> Dict:
        resp = self._http_get(url, timeout=timeout)
        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Invalid JSON from {url} — {exc}")

    def _http_get_text(self, url: str, timeout: int = 30) -> str:
        return self._http_get(url, timeout=timeout).text

    # ── SEC EDGAR API 互動 ──────────────────────────────────────────

    def _fetch_submission_index(self, cik: str) -> Dict:
        """從 SEC EDGAR 取得機構法人的 filing 索引"""
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        cache_key = f"sec_13f_submissions_{cik}"
        return fetch_with_cache(
            policy_name="sec_13f",
            cache_key=cache_key,
            fetch_fn=lambda: self._http_get_json(url),
        )

    def _find_13f_filings(self, submissions: Dict, count: int = 2,
                          skip_notice: bool = False) -> List[Dict]:
        """
        從 submission 索引中找出最近的 13F filings。

        Args:
            submissions: SEC submission API 回應
            count: 返回幾個 filing
            skip_notice: 若為 True，跳過 13F-NT（Notice 形式，無完整持股明細）
        """
        recent = submissions.get("filings", {}).get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])
        report_dates = recent.get("reportDate", [])

        filings = []
        for i, form in enumerate(forms):
            if not form.startswith("13F"):
                continue
            if skip_notice and form == "13F-NT":
                # 13F-NT 為 Notice 形式，無完整持股明細（BlackRock 2024-12-31 起使用）
                continue
            filings.append({
                "accessionNumber": accession_numbers[i] if i < len(accession_numbers) else "",
                "filingDate": filing_dates[i] if i < len(filing_dates) else "",
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                "reportDate": report_dates[i] if i < len(report_dates) else "",
                "form": form,
            })
            if len(filings) >= count:
                break

        return filings

    def _fetch_13f_info_table(self, cik: str, accession: str) -> str:
        """
        統一抓取 13F 持股明細（兩機構相同邏輯）

        資料來源：SEC EDGAR Archives
        - URL 格式：https://www.sec.gov/Archives/edgar/data/{cik_path}/{acc_clean}/xslForm13F_X02/infotable.xml
        - cik_path 從 accession number 前綴取得（非 CIK 本身，因 accession 前綴可能不同）
        - 兩機構都用相同 URL 格式，統一使用 curl_cffi + impersonate='chrome'

        排程邏輯：
        - 固定抓取日（美東 2/15, 5/15, 8/15, 11/15）→ 強制重新抓取
        - 抓取失敗後 24 小時內 → 重試
        - 其餘時間 → 使用 local cache（TTL 90 天）
        """
        accession_clean = accession.replace("-", "")
        # URL 路徑用 accession 前綴（可能與 CIK 不同，如 Bridgewater 早期 accession 用不同前綴）
        cik_path = accession.split("-")[0]
        cache_key = f"sec_13f_infotable_{accession}"

        # ── 排程判斷：是否應從 SEC 抓取 ──
        if not should_fetch_from_sec(cache_key):
            # 非抓取日：使用 local cache
            from data_cache import read_cache as _read_cache
            cached = _read_cache(cache_key, max_age_hours=CACHE_TTL_HOURS)
            if cached is not None:
                return cached
            # cache 過期但非抓取日：仍然使用 cache（不抓取）
            cached_any = _read_cache(cache_key, max_age_hours=0)
            if cached_any is not None:
                return cached_any

        # ── 從 SEC 抓取 ──
        if not _HAS_CURL_CFFI:
            raise RuntimeError(
                "需要 curl_cffi 才能存取 SEC Archives。請安裝：pip install curl_cffi"
            )

        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        def _fetch_from_sec():
            """從 SEC Archives 抓取

            優先嘗試 infotable.xml（Bridgewater 等 HTML 表格格式）
            若 404，fallback 到 .txt（BlackRock 等 XML 格式）
            """
            # 嘗試 infotable.xml
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik_path}"
                   f"/{accession_clean}/xslForm13F_X02/infotable.xml")
            resp = cffi_requests.get(url, headers=headers, impersonate='chrome', timeout=120)

            if resp.status_code == 200 and len(resp.text) > 100:
                return resp.text

            # Fallback：嘗試 .txt（BlackRock 等）
            url_txt = (f"https://www.sec.gov/Archives/edgar/data/{cik_path}"
                       f"/{accession_clean}/{accession}.txt")
            resp_txt = cffi_requests.get(url_txt, headers=headers, impersonate='chrome', timeout=120)

            if resp_txt.status_code == 200 and len(resp_txt.text) > 100:
                return resp_txt.text

            raise RuntimeError(
                f"SEC Archives 無法取得持股明細：CIK {cik} Acc {accession} "
                f"(infotable.xml: {resp.status_code}, .txt: {resp_txt.status_code})"
            )

        try:
            return fetch_with_cache(
                policy_name="sec_13f",
                cache_key=cache_key,
                fetch_fn=_fetch_from_sec,
            )
        except Exception:
            # 標記抓取失敗，觸發 24 小時重試
            mark_fetch_failed(cache_key)
            raise

    def _save_to_cache(self, cache_key: str, data: str) -> str:
        """儲存快取並返回資料（使用 data_cache.py 相容格式）"""
        import json as _json
        from datetime import datetime as _dt
        now = _dt.now()
        ts = now.strftime("%Y%m%d_%H%M%S")
        ms = f"{now.microsecond:06d}"
        cache_path = os.path.join("local_cache", f"{cache_key}_{ts}_{ms}.json")
        payload = {"cached_at": now.isoformat(), "data": data}
        with open(cache_path, 'w') as fh:
            _json.dump(payload, fh)
        return data

    def _load_cached_holdings(self, cik: str, exclude_acc: str = None) -> List[Dict]:
        """
        從 local_cache 載入所有可用的舊版 sec_13f_info_{accession} 快取。

        注意：BlackRock 舊快取檔名包含的是 BlackRock Advisors 的 accession
        （sec_13f_info_0001086364-24-008417_...），但 CIK 路徑用 BlackRock Finance
        (1364742)。因此搜尋時使用 accession 前綴而非 CIK。

        回傳: [(accession, holdings_dict), ...] 按 accession 降序排列
        """
        import glob
        cache_dir = "local_cache"
        results = []
        # 搜尋所有 sec_13f_info_ 前綴檔案（相容新舊格式）
        pattern = os.path.join(cache_dir, "sec_13f_info_*.json")
        for fpath in sorted(glob.glob(pattern), reverse=True):
            try:
                with open(fpath) as fh:
                    cached = json.load(fh)
                xml_data = cached.get("data", "")
                if not xml_data:
                    continue
                holdings = self._parse_holdings(xml_data)
                fname = os.path.basename(fpath)
                # 從檔名提取 accession（格式：sec_13f_info_{accession}_{timestamp}.json）
                acc = fname.replace("sec_13f_info_", "").split("_")[0]
                if acc != exclude_acc and holdings:
                    results.append((acc, holdings))
            except Exception:
                continue
        return results

    def _parse_holdings(self, xml_text: str) -> Dict[str, Dict]:
        """
        解析 13F 持股明細，提取目標持股。
        回傳: {ticker: {"shares": int, "value_k": float, "name": str}}

        支援兩種格式：
        1. XML 格式（BlackRock）：<infoTable> 帶 namespace
        2. HTML 格式（Bridgewater）：<tr><td> 表格
        """
        # 先嘗試 XML 格式
        if "<infoTable>" in xml_text or "<n2:infoTable>" in xml_text:
            return self._parse_holdings_xml(xml_text)
        # 再嘗試 HTML 格式
        elif "<tr>" in xml_text:
            return self._parse_holdings_html(xml_text)
        else:
            raise RuntimeError("無法識別的 13F 持股明細格式")

    def _parse_holdings_xml(self, xml_text: str) -> Dict[str, Dict]:
        """解析 XML 格式的 13F 持股（BlackRock CIK 0002012383，.txt 格式）

        注意：BlackRock 的 .txt 檔案包含 SEC-DOCUMENT 包裝（非純 XML），
        ET.fromstring() 可能因 HTML 實體（&amp; 等）而失敗。
        若 XML 解析失敗，自動 fallback 到 regex 解析。
        """
        holdings = {}

        # 嘗試用 XML parser 解析（Bridgewater infotable.xml XML 格式）
        root = None
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            pass  # fallback to regex below

        if root is not None:
            info_tables = root.findall(f"{{{NS}}}infoTable")
            if not info_tables:
                info_tables = root.findall(".//infoTable")
            use_regex = False
        else:
            info_tables = None
            use_regex = True

        # 若 XML parser 找不到 infoTable，用 regex fallback
        if not info_tables:
            use_regex = True

        if use_regex:
            return self._parse_holdings_regex(xml_text)

        for table in info_tables:
            name_el = table.find(f"{{{NS}}}nameOfIssuer")
            if name_el is None:
                name_el = table.find("nameOfIssuer")
            if name_el is None:
                continue
            issuer_name = (name_el.text or "").strip()

            matched_ticker = None
            for ticker, meta in TARGET_COMPANIES.items():
                if _match_name(issuer_name, meta["match_names"]):
                    matched_ticker = ticker
                    break
            if matched_ticker is None:
                continue

            value_el = table.find(f"{{{NS}}}value")
            if value_el is None:
                value_el = table.find("value")
            if value_el is None:
                continue

            shares = 0
            shrs_el = table.find(f"{{{NS}}}shrsOrPrnAmt")
            if shrs_el is None:
                shrs_el = table.find("shrsOrPrnAmt")
            if shrs_el is not None:
                ssh_el = shrs_el.find(f"{{{NS}}}sshPrnamt")
                if ssh_el is None:
                    ssh_el = shrs_el.find("sshPrnamt")
                if ssh_el is not None and ssh_el.text:
                    try:
                        shares = int(float(ssh_el.text.strip()))
                    except (ValueError, TypeError):
                        pass

            try:
                value = float(value_el.text or 0)
            except (ValueError, TypeError):
                continue

            if matched_ticker in holdings:
                holdings[matched_ticker]["shares"] += shares
                holdings[matched_ticker]["value_k"] += value / 1000
            else:
                holdings[matched_ticker] = {
                    "shares": shares,
                    "value_k": value / 1000,
                    "name": issuer_name,
                }

        return holdings

    def _parse_holdings_regex(self, text: str) -> Dict[str, Dict]:
        """用 regex 解析 13F 持股（處理非標準 XML，如 BlackRock .txt 中的 &amp; 等實體）"""
        holdings = {}

        entries = re.findall(r'<infoTable>(.*?)</infoTable>', text, re.DOTALL)
        for e in entries:
            name_m = re.search(r'<nameOfIssuer>(.*?)</nameOfIssuer>', e)
            if not name_m:
                continue
            issuer_name = name_m.group(1).strip()

            matched_ticker = None
            for ticker, meta in TARGET_COMPANIES.items():
                if _match_name(issuer_name, meta["match_names"]):
                    matched_ticker = ticker
                    break
            if matched_ticker is None:
                continue

            shares_m = re.search(r'<sshPrnamt>(.*?)</sshPrnamt>', e)
            value_m = re.search(r'<value>(.*?)</value>', e)

            shares = int(shares_m.group(1)) if shares_m else 0
            value = float(value_m.group(1)) if value_m else 0.0

            if matched_ticker in holdings:
                holdings[matched_ticker]["shares"] += shares
                holdings[matched_ticker]["value_k"] += value / 1000
            else:
                holdings[matched_ticker] = {
                    "shares": shares,
                    "value_k": value / 1000,
                    "name": issuer_name,
                }

        return holdings

    def _parse_holdings_html(self, html_text: str) -> Dict[str, Dict]:
        """解析 HTML 格式的 13F 持股（Bridgewater）"""
        holdings = {}

        rows = re.findall(r'<tr>(.*?)</tr>', html_text, re.DOTALL | re.IGNORECASE)
        for row in rows:
            cols = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
            if len(cols) < 5:
                continue
            clean_cols = [re.sub(r'<[^>]+>', ' ', c).strip() for c in cols]
            issuer_name = clean_cols[0]
            if not issuer_name:
                continue

            matched_ticker = None
            for ticker, meta in TARGET_COMPANIES.items():
                if _match_name(issuer_name, meta["match_names"]):
                    matched_ticker = ticker
                    break
            if matched_ticker is None:
                continue

            # 從欄位中找出 value（>100K）和 shares（>1K）
            value = 0.0
            shares = 0
            for ci in range(3, min(len(clean_cols), 7)):
                val_str = clean_cols[ci].replace(',', '').replace('$', '').strip()
                try:
                    val = float(val_str)
                    if val > 100000 and value == 0:  # value in dollars
                        value = val
                        # shares 通常在下一欄
                        if ci + 1 < len(clean_cols):
                            sh_str = clean_cols[ci + 1].replace(',', '').strip()
                            try:
                                sh = int(float(sh_str))
                                if sh > 100:
                                    shares = sh
                            except ValueError:
                                pass
                        break
                except ValueError:
                    pass

            if value == 0:
                continue

            if matched_ticker in holdings:
                holdings[matched_ticker]["shares"] += shares
                holdings[matched_ticker]["value_k"] += value / 1000
            else:
                holdings[matched_ticker] = {
                    "shares": shares,
                    "value_k": value / 1000,
                    "name": issuer_name,
                }

        return holdings

    # ── 核心分析邏輯 ──────────────────────────────────────────────

    def analyze_13f_holdings(self, cik: str,
                            target_tickers: Optional[List[str]] = None) -> Tuple[Dict, str]:
        """
        核心方法：抓取單一機構最近兩份 13F，比較目標持股的季度變化。

        回傳：
        - data: dict 包含每檔股票的持股比較、變化量、分數
        - report: Markdown 格式的報告字串
        """
        if target_tickers is None:
            target_tickers = list(TARGET_COMPANIES.keys())

        institution = INSTITUTION_REGISTRY.get(cik, {})
        inst_name = institution.get("name", f"CIK {cik}")
        inst_short = institution.get("short_name", inst_name)

        report_lines = [
            f"## 🏛 {inst_name}（CIK: {cik}）",
            f"",
        ]

        try:
            # Step 1: 取得 filing 索引
            submissions = self._fetch_submission_index(cik)
            filings = self._find_13f_filings(submissions, count=4)

            if len(filings) == 0:
                return {"error": "找不到 13F 報告", "cik": cik}, (
                    f"⚠️ 無法取得 {inst_name}（CIK {cik}）的 13F 報告。"
                    f"可能 SEC 資料尚未更新或 CIK 不正確。"
                )

            # 找出最近有完整持股明細的季度（跳過 13F-NT Notice 形式）
            # 注意：BlackRock (CIK 0002012383) 全部為 13F-HR，無 Notice 問題
            current = None
            previous = None
            notice_skipped = []

            for f in filings:
                if f["form"] == "13F-NT":
                    notice_skipped.append(f["reportDate"])
                    continue
                if current is None:
                    current = f
                elif previous is None:
                    previous = f
                    break

            # 如果前4季全是 Notice，降級使用最新兩季（嘗試從舊快取讀取）
            if current is None:
                filings_all = self._find_13f_filings(submissions, count=2)
                current = filings_all[0]
                previous = filings_all[1] if len(filings_all) >= 2 else None
                notice_skipped = [current["reportDate"]]

            if notice_skipped:
                report_lines.append(
                    f"⚠️ **注意**: {inst_name} 近期 13F 為 Notice 形式"
                    f"（{', '.join(notice_skipped)}），無完整持股明細。"
                    f"退回使用 {current['reportDate']} 資料。"
                )
                report_lines.append("")

            report_lines.append(
                f"**最新 13F:** {current['reportDate']}（申報日: {current['filingDate']}）"
            )
            if previous:
                report_lines.append(
                    f"**上一季:** {previous['reportDate']}（申報日: {previous['filingDate']}）"
                )
            report_lines.append("")

            # Step 2: 抓取持股明細（含 fallback）
            current_holdings = {}
            previous_holdings = {}

            # 嘗試抓取最新季的持股明細
            try:
                xml = self._fetch_13f_info_table(cik, current["accessionNumber"])
                current_holdings = self._parse_holdings(xml)
            except Exception:
                pass

            # 若最新季無持股（Notice 形式），從舊快取載入
            if not current_holdings:
                cached_list = self._load_cached_holdings(cik)
                if cached_list:
                    acc, current_holdings = cached_list[0]
                    note = (f"⚠️ {inst_name} 近期 13F 為 Notice 形式"
                            f"，使用本地快取（{acc}，{len(current_holdings)} 檔持股）。")
                    report_lines.append(note)
                    report_lines.append("")
                    # 嘗試找前一期作為比較基準
                    if len(cached_list) >= 2:
                        _, previous_holdings = cached_list[1]
                        previous = {"accessionNumber": cached_list[1][0],
                                    "filingDate": "N/A", "reportDate": "N/A",
                                    "form": "13F", "primaryDocument": ""}
                    current = {"accessionNumber": acc,
                               "filingDate": "N/A", "reportDate": "N/A",
                               "form": "13F", "primaryDocument": ""}
                else:
                    raise RuntimeError(
                        f"無法取得 {inst_name} 的持股明細"
                        f"（最新幾季皆為 13F-NT Notice 形式，且無本地快取）。"
                    )

            previous_holdings = {}
            if previous:
                try:
                    prev_xml = self._fetch_13f_info_table(cik, previous["accessionNumber"])
                    previous_holdings = self._parse_holdings(prev_xml)
                except Exception:
                    # 嘗試從 local_cache 找舊快取作為 previous
                    import os as _os
                    cache_dir = "local_cache"
                    cik_no = str(int(cik))
                    prefix = "sec_13f_info_"
                    if _os.path.isdir(cache_dir):
                        matching_files = sorted(
                            [fn for fn in _os.listdir(cache_dir)
                             if fn.startswith(prefix) and cik_no in fn and fn.endswith(".json")],
                            reverse=True
                        )
                        # 跳過已經用作 current 的檔案
                        used_fn = None
                        if current and current.get("accessionNumber"):
                            used_acc = current["accessionNumber"]
                            for _fn in matching_files:
                                if used_acc in _fn:
                                    used_fn = _fn
                                    break
                        for fn in matching_files:
                            if fn == used_fn:
                                continue
                            try:
                                cache_path = _os.path.join(cache_dir, fn)
                                with open(cache_path) as _fh:
                                    import json as _json
                                    _cached = _json.load(_fh)
                                xml_data = _cached.get("data", "")
                                if xml_data:
                                    parsed = self._parse_holdings(xml_data)
                                    if parsed:
                                        previous_holdings = parsed
                                        acc_part = fn[len(prefix):].split("_")[0]
                                        # 更新 previous 的日期資訊
                                        previous = {"accessionNumber": acc_part,
                                                    "filingDate": "N/A",
                                                    "reportDate": "N/A",
                                                    "form": "13F",
                                                    "primaryDocument": ""}
                                        break
                            except Exception:
                                continue
                    if not previous_holdings:
                        previous = None

            # Step 3: 比較持股變化
            data = {
                "cik": cik,
                "institution_name": inst_name,
                "institution_short": inst_short,
                "current_date": current["reportDate"],
                "current_filing_date": current["filingDate"],
                "previous_date": previous["reportDate"] if previous else None,
                "previous_filing_date": previous["filingDate"] if previous else None,
                "holdings": {},
                "score": 50,
            }

            has_previous = previous is not None
            if has_previous:
                report_lines.append(
                    "| 股票 | 名稱 | 上季股數 | 本季股數 | 變化 | 變化% | 持倉價值(千美元) |"
                )
                report_lines.append("|------|------|---------|---------|------|-------|-----------------|")
            else:
                report_lines.append(
                    "| 股票 | 名稱 | 本季股數 | 持倉價值(千美元) |"
                )
                report_lines.append("|------|------|---------|-----------------|")

            for ticker in target_tickers:
                meta = TARGET_COMPANIES[ticker]
                curr = current_holdings.get(ticker)
                prev = previous_holdings.get(ticker) if has_previous else None

                curr_shares = curr["shares"] if curr else 0
                curr_value = curr["value_k"] if curr else 0
                curr_name = curr["name"] if curr else meta["name"]

                holding_data = {
                    "name": curr_name,
                    "current_shares": curr_shares,
                    "current_value_k": round(curr_value, 1),
                }

                if has_previous:
                    prev_shares = prev["shares"] if prev else 0
                    prev_value = prev["value_k"] if prev else 0

                    change_shares = curr_shares - prev_shares
                    if prev_shares > 0:
                        change_pct = (change_shares / prev_shares) * 100
                    elif curr_shares > 0:
                        change_pct = float('inf')
                    else:
                        change_pct = 0

                    holding_data["previous_shares"] = prev_shares
                    holding_data["previous_value_k"] = round(prev_value, 1)
                    holding_data["change_shares"] = change_shares
                    holding_data["change_pct"] = change_pct

                    if prev_shares == 0 and curr_shares > 0:
                        holding_data["status"] = "new"
                    elif prev_shares > 0 and curr_shares == 0:
                        holding_data["status"] = "exited"
                    elif change_shares > 0:
                        holding_data["status"] = "increased"
                    elif change_shares < 0:
                        holding_data["status"] = "decreased"
                    else:
                        holding_data["status"] = "unchanged"

                    pct_str = f"{change_pct:+.1f}%" if change_pct != float('inf') else "+∞"
                    report_lines.append(
                        f"| {ticker} | {curr_name} | {prev_shares:,} | {curr_shares:,} | "
                        f"{change_shares:+,} | {pct_str} | {curr_value:,.1f} |"
                    )
                else:
                    holding_data["status"] = "held" if curr_shares > 0 else "not_held"
                    report_lines.append(
                        f"| {ticker} | {curr_name} | {curr_shares:,} | {curr_value:,.1f} |"
                    )

                data["holdings"][ticker] = holding_data

            # Step 4: 分析文字
            report_lines.append("")
            report_lines.append("**📊 動向分析：**")
            report_lines.append("")

            # TSMC 重點分析
            tsm_data = data["holdings"].get("TSM", {})
            tsm_status = tsm_data.get("status", "not_held")
            if tsm_status == "new":
                report_lines.append(
                    f"- **TSMC**: 本季新建持倉 {tsm_data['current_shares']:,} 股"
                    f"（價值 ${tsm_data['current_value_k']:,.1f}K），表達對台積電的正面看法。"
                )
            elif tsm_status == "exited":
                report_lines.append(
                    f"- **TSMC**: 本季清空所有持倉（上季 {tsm_data.get('previous_shares', 0):,} 股），"
                    "可能反映對半導體賽道的重新評估。"
                )
            elif tsm_status == "increased":
                change = tsm_data.get("change_shares", 0)
                report_lines.append(
                    f"- **TSMC**: 增持 {change:,} 股（{tsm_data.get('change_pct', 0):+.1f}%），持續加碼。"
                )
            elif tsm_status == "decreased":
                change = abs(tsm_data.get("change_shares", 0))
                report_lines.append(
                    f"- **TSMC**: 減持 {change:,} 股（{tsm_data.get('change_pct', 0):+.1f}%），部分獲利了結。"
                )
            elif tsm_status == "unchanged" and tsm_data.get("current_shares", 0) > 0:
                report_lines.append(
                    f"- **TSMC**: 持股維持不變（{tsm_data['current_shares']:,} 股，"
                    f"價值 ${tsm_data['current_value_k']:,.1f}K）。"
                )
            else:
                report_lines.append("- **TSMC**: 目前未持有 TSMC 相關部位。")

            report_lines.append("")

            # 四大科技巨頭摘要
            for t in ["MSFT", "GOOGL", "AMZN", "NVDA"]:
                td = data["holdings"].get(t, {})
                name = TARGET_COMPANIES[t]["name"]
                status = td.get("status", "not_held")
                if status == "new":
                    report_lines.append(
                        f"- **{name} ({t})**: 新建持倉 {td['current_shares']:,} 股"
                        f"（價值 ${td['current_value_k']:,.1f}K）"
                    )
                elif status == "exited":
                    report_lines.append(
                        f"- **{name} ({t})**: 清倉離場"
                        f"（上季 {td.get('previous_shares', 0):,} 股，${td.get('previous_value_k', 0):,.1f}K）"
                    )
                elif status in ("increased", "decreased"):
                    change = td.get("change_shares", 0)
                    pct = td.get("change_pct", 0)
                    direction = "增持" if change > 0 else "減持"
                    report_lines.append(
                        f"- **{name} ({t})**: {direction} {abs(change):,} 股（{pct:+.1f}%）"
                    )
                elif status == "unchanged" and td.get("current_shares", 0) > 0:
                    report_lines.append(
                        f"- **{name} ({t})**: 持股 {td['current_shares']:,} 股"
                        f"（價值 ${td['current_value_k']:,.1f}K）"
                    )
                else:
                    report_lines.append(f"- **{name} ({t})**: 未持有")

            # Step 5: 計算綜合分數
            score = 50
            if tsm_status in ("new", "increased"):
                score = 80
            elif tsm_status == "unchanged" and tsm_data.get("current_shares", 0) > 0:
                score = 65
            elif tsm_status == "decreased":
                score = 40
            elif tsm_status == "exited":
                score = 20

            data["score"] = score

            if score >= 70:
                report_lines.append("")
                report_lines.append(
                    f"**{inst_short} 解讀：** 對 TSMC 持正面看法，增持動作顯示對半導體/AI 供應鏈的信心。"
                )
            elif score >= 50:
                report_lines.append("")
                report_lines.append(
                    f"**{inst_short} 解讀：** 對 TSMC 看法中性，持股穩定並未大幅調整。"
                )
            else:
                report_lines.append("")
                report_lines.append(
                    f"**{inst_short} 解讀：** 對 TSMC 偏空，減碼或清倉可能反映對半導體需求的保留態度。"
                )

        except Exception as exc:
            import traceback
            traceback.print_exc()
            return {"error": str(exc), "cik": cik}, (
                f"⚠️ {inst_name} 13F 追蹤失敗：{exc}\n"
                f"可能原因：SEC API 暫時不可用、網路問題、或 13F 報告尚未提交。"
            )

        return data, "\n".join(report_lines)

    def analyze_all_institutions(
        self,
        target_tickers: Optional[List[str]] = None,
    ) -> Tuple[List[Dict], str]:
        """
        追蹤所有已註冊機構法人，彙整報告。

        回傳：
        - all_data: list of per-institution data dicts
        - combined_report: Markdown 格式的合併報告
        """
        all_data = []
        report_sections = [
            "# 機構法人 13F 持倉追蹤",
            f"數據來源: SEC EDGAR Form 13F-NT / 13F-HR (infotable.xml)",
            f"分析邏輯: 比較最近兩季 13F 報告中目標持股的股數與價值變化",
            f"追蹤機構: {', '.join(INSTITUTION_REGISTRY[cik]['name'] for cik in self.tracked_ciks)}",
            "",
        ]

        for cik in self.tracked_ciks:
            data, report = self.analyze_13f_holdings(cik=cik, target_tickers=target_tickers)
            all_data.append(data)
            report_sections.append(report)
            report_sections.append("")

        # 跨機構摘要比較
        report_sections.append("---")
        report_sections.append("")
        report_sections.append("## 🔍 跨機構比較摘要")
        report_sections.append("")

        # 建立跨機構 TSMC 動向對照表
        report_sections.append("| 機構 | TSMC 動向 | 分數 |")
        report_sections.append("|------|----------|------|")
        for data in all_data:
            if "error" in data:
                report_sections.append(f"| {data.get('institution_short', 'N/A')} | ⚠️ 資料取得失敗 | N/A |")
                continue
            tsm = data.get("holdings", {}).get("TSM", {})
            status = tsm.get("status", "not_held")
            status_label = {
                "new": "🟢 新建持倉",
                "increased": "🟢 增持",
                "unchanged": "🟡 持股不變",
                "decreased": "🟠 減持",
                "exited": "🔴 清倉",
                "not_held": "⚪ 未持有",
                "held": "🟡 持有",
            }.get(status, status)
            score = data.get("score", "N/A")
            report_sections.append(f"| {data.get('institution_short', 'N/A')} | {status_label} | {score}/100 |")

        report_sections.append("")

        return all_data, "\n".join(report_sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="機構法人 13F 持倉追蹤 Agent")
    parser.add_argument(
        "--cik",
        type=str,
        default=None,
        help="指定單一 SEC CIK 號碼（預設：追蹤所有已註冊機構）",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=",".join(TARGET_COMPANIES.keys()),
        help="逗號分隔的 ticker 列表（預設：TSM,MSFT,GOOGL,AMZN,NVDA）",
    )
    parser.add_argument(
        "--list-institutions",
        action="store_true",
        help="列出所有已註冊的機構法人",
    )
    args = parser.parse_args()

    if args.list_institutions:
        print("=== 已註冊機構法人 ===")
        for cik, info in INSTITUTION_REGISTRY.items():
            print(f"  CIK {cik}: {info['name']}（{info.get('short_name', '')}）— {info.get('description', '')}")
        return

    target_list = [t.strip().upper() for t in args.tickers.split(",")]

    agent = InstitutionalTrackerAgent(tracked_ciks=[args.cik] if args.cik else None)
    print(f"=== {agent.name} ===")
    print(f"目標持股: {', '.join(target_list)}")
    print()

    if args.cik:
        # 單一機構模式（向後相容）
        print(f"目標 CIK: {args.cik}")
        data, report = agent.analyze_13f_holdings(cik=args.cik, target_tickers=target_list)
        print(report)
        if "error" in data:
            print(f"\n錯誤詳情: {data['error']}")
            sys.exit(1)
        print(f"\nTSMC 動向分數: {data.get('score', 'N/A')}/100")
    else:
        # 全部機構模式
        agent = InstitutionalTrackerAgent()
        all_data, combined_report = agent.analyze_all_institutions(target_tickers=target_list)
        print(combined_report)

        has_error = any("error" in d for d in all_data)
        if has_error:
            errors = [d for d in all_data if "error" in d]
            for err in errors:
                print(f"\n⚠️ {err.get('institution_name', err.get('cik', 'N/A'))}: {err['error']}")
            sys.exit(1)


if __name__ == "__main__":
    main()
