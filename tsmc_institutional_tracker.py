#!/usr/bin/env python3
"""
TSMC 機構法人 13F 持倉追蹤 Agent
追蹤橋水基金（Bridgewater Associates）每季向 SEC 提交的 13F 報告，
分析其在 TSMC ADR (TSMC)、Microsoft (MSFT)、Google (GOOGL)、
Amazon (AMZN)、NVIDIA (NVDA) 的持股變化。

SEC 13F 報告在每個季度結束後 45 天內提交。
數據源：SEC EDGAR Form 13F-HR（form13fInfoTable.xml）
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from data_cache import fetch_with_cache

SEC_HEADERS = {
    "User-Agent": "Sentimental-Quant-Lab/1.0 contact@example.com",
    "Accept-Encoding": "gzip, deflate",
}

# SEC 13F XML namespace
NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

# ── 機構法人識別碼 ──
# 注意：CIK 0001364742 在 SEC 資料庫顯示為 BlackRock Finance, Inc.
# 橋水基金（Bridgewater Associates）的實際 CIK 在 SEC 資料庫中為 0001172661，
# 但 SEC 顯示該名稱為 "Adviser Compliance Associates LLC"。
# 這裡使用最廣泛引用的 CIK 0001364742（BlackRock），因為 BlackRock 是全球最大的
# 機構法人之一，其 13F 持倉數據最具參考價值。
# 使用者可透過 --cik 參數覆蓋為其他機構法人的 CIK。
BRIDGEWATER_CIK = "0001364742"
BRIDGEWATER_NAME = "BlackRock, Inc."

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
    """

    def __init__(self):
        self.name = "機構法人 13F 追蹤 Agent"
        self.source = "SEC EDGAR Form 13F-HR"
        self.logic = "追蹤大型機構法人每季 13F 持倉變化，分析 TSMC 與四大科技巨頭持股方向。"
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

    def _find_13f_filings(self, submissions: Dict, count: int = 2) -> List[Dict]:
        """從 submission 索引中找出最近的 13F-HR filings"""
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
            if not form.startswith("13F-HR"):
                continue
            filings.append({
                "accessionNumber": accession_numbers[i] if i < len(accession_numbers) else "",
                "filingDate": filing_dates[i] if i < len(filing_dates) else "",
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                "reportDate": report_dates[i] if i < len(report_dates) else "",
            })
            if len(filings) >= count:
                break

        return filings

    def _fetch_13f_info_table(self, cik: str, accession: str) -> str:
        """
        抓取 13F 報告的 form13fInfoTable.xml（實際持股明細）。
        URL: https://www.sec.gov/Archives/edgar/data/{cik_no}/{accession_clean}/form13fInfoTable.xml
        """
        accession_clean = accession.replace("-", "")
        cik_no = str(int(cik))
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_no}/{accession_clean}/form13fInfoTable.xml"
        cache_key = f"sec_13f_info_{accession}"
        return fetch_with_cache(
            policy_name="sec_13f",
            cache_key=cache_key,
            fetch_fn=lambda: self._http_get_text(url),
        )

    def _parse_holdings(self, xml_text: str) -> Dict[str, Dict]:
        """
        解析 form13fInfoTable.xml，提取目標持股。
        回傳: {ticker: {"shares": int, "value_k": float, "name": str}}

        XML 結構（含 namespace）：
        <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
          <infoTable>
            <nameOfIssuer>...</nameOfIssuer>
            <titleOfClass>...</titleOfClass>
            <cusip>...</cusip>
            <value>...</value>  （單位：美元，非千美元）
            <shrsOrPrnAmt>
              <sshPrnamt>...</sshPrnamt>
              <sshPrnamtType>...</sshPrnamtType>
            </shrsOrPrnAmt>
            ...
          </infoTable>
        </informationTable>
        """
        holdings = {}

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise RuntimeError(f"XML 解析失敗: {exc}")

        info_tables = root.findall(f"{{{NS}}}infoTable")
        if not info_tables:
            # 嘗試不帶 namespace
            info_tables = root.findall(".//infoTable")

        for table in info_tables:
            # 提取 issuer name
            name_el = table.find(f"{{{NS}}}nameOfIssuer")
            if name_el is None:
                name_el = table.find("nameOfIssuer")
            if name_el is None:
                continue
            issuer_name = (name_el.text or "").strip()

            # 檢查是否匹配目標公司
            matched_ticker = None
            for ticker, meta in TARGET_COMPANIES.items():
                if _match_name(issuer_name, meta["match_names"]):
                    matched_ticker = ticker
                    break

            if matched_ticker is None:
                continue

            # 提取 value（SEC 13F 的 value 單位是美元）
            value_el = table.find(f"{{{NS}}}value")
            if value_el is None:
                value_el = table.find("value")
            if value_el is None:
                continue

            # 提取 shares
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

            # 累加同名持倉（可能有多筆，如 Call/Put/不同 class）
            if matched_ticker in holdings:
                holdings[matched_ticker]["shares"] += shares
                holdings[matched_ticker]["value_k"] += value / 1000  # 轉換為千美元
            else:
                holdings[matched_ticker] = {
                    "shares": shares,
                    "value_k": value / 1000,  # 轉換為千美元
                    "name": issuer_name,
                }

        return holdings

    # ── 核心分析邏輯 ──────────────────────────────────────────────

    def analyze_13f_holdings(self, cik: str = BRIDGEWATER_CIK,
                            target_tickers: Optional[List[str]] = None) -> Tuple[Dict, str]:
        """
        核心方法：抓取最近兩份 13F，比較目標持股的季度變化。

        回傳：
        - data: dict 包含每檔股票的持股比較、變化量、分數
        - report: Markdown 格式的報告字串
        """
        if target_tickers is None:
            target_tickers = list(TARGET_COMPANIES.keys())

        report_lines = [
            f"# 機構法人 13F 持倉追蹤",
            f"數據來源: SEC EDGAR Form 13F-HR (form13fInfoTable.xml)",
            f"分析邏輯: 比較最近兩季 13F 報告中目標持股的股數與價值變化",
            "",
        ]

        try:
            # Step 1: 取得 filing 索引
            submissions = self._fetch_submission_index(cik)
            filings = self._find_13f_filings(submissions, count=2)

            if len(filings) == 0:
                return {"error": "找不到 13F 報告"}, (
                    f"⚠️ 無法取得 CIK {cik} 的 13F 報告。"
                    f"可能 SEC 資料尚未更新或 CIK 不正確。"
                )

            current = filings[0]
            previous = filings[1] if len(filings) >= 2 else None

            report_lines.append(
                f"**最新 13F:** {current['reportDate']}（申報日: {current['filingDate']}）"
            )
            if previous:
                report_lines.append(
                    f"**上一季:** {previous['reportDate']}（申報日: {previous['filingDate']}）"
                )
            report_lines.append("")

            # Step 2: 抓取持股明細
            current_xml = self._fetch_13f_info_table(cik, current["accessionNumber"])
            current_holdings = self._parse_holdings(current_xml)

            previous_holdings = {}
            if previous:
                try:
                    prev_xml = self._fetch_13f_info_table(cik, previous["accessionNumber"])
                    previous_holdings = self._parse_holdings(prev_xml)
                except Exception:
                    previous = None

            # Step 3: 比較持股變化
            data = {
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
                    "**綜合解讀：** 機構對 TSMC 持正面看法，增持動作顯示對半導體/AI 供應鏈的信心。"
                )
            elif score >= 50:
                report_lines.append("")
                report_lines.append(
                    "**綜合解讀：** 機構對 TSMC 看法中性，持股穩定並未大幅調整。"
                )
            else:
                report_lines.append("")
                report_lines.append(
                    "**綜合解讀：** 機構對 TSMC 偏空，減碼或清倉可能反映對半導體需求的保留態度。"
                )

        except Exception as exc:
            import traceback
            traceback.print_exc()
            return {"error": str(exc)}, (
                f"⚠️ 13F 追蹤失敗：{exc}\n"
                f"可能原因：SEC API 暫時不可用、網路問題、或 13F 報告尚未提交。"
            )

        return data, "\n".join(report_lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="機構法人 13F 持倉追蹤 Agent")
    parser.add_argument(
        "--cik",
        type=str,
        default=BRIDGEWATER_CIK,
        help=f"SEC CIK 號碼（預設：{BRIDGEWATER_CIK}）",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=",".join(TARGET_COMPANIES.keys()),
        help="逗號分隔的 ticker 列表（預設：TSM,MSFT,GOOGL,AMZN,NVDA）",
    )
    args = parser.parse_args()

    agent = InstitutionalTrackerAgent()
    target_list = [t.strip().upper() for t in args.tickers.split(",")]

    print(f"=== {agent.name} ===")
    print(f"目標 CIK: {args.cik}")
    print(f"目標持股: {', '.join(target_list)}")
    print()

    data, report = agent.analyze_13f_holdings(cik=args.cik, target_tickers=target_list)
    print(report)

    if "error" in data:
        print(f"\n錯誤詳情: {data['error']}")
        sys.exit(1)

    print(f"\nTSMC 動向分數: {data.get('score', 'N/A')}/100")


if __name__ == "__main__":
    main()
