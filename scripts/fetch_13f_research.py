#!/usr/bin/env python3
"""
SEC 13F 季度持倉研究腳本
自動抓取 BlackRock 與 Bridgewater 最新 13F 報告，
分析 TSMC 及前十大持股變化，產出結構化研究報告。

數據來源：SEC EDGAR Form 13F-HR / 13F-NT
使用 data_cache.fetch_with_cache 統一快取層
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 加入專案根目錄到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from data_cache import fetch_with_cache

# ── 常數 ──────────────────────────────────────────────────────────────

NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

# 機構資訊
# BlackRock 透過 BlackRock Advisors LLC (CIK 0001086364) 申報 13F-NT
# Bridgewater 透過 GC Wealth Management (CIK 0002011169) 申報 13F-HR，
#   但 accession number 使用 0001172661 前綴
INSTITUTIONS = {
    "blackrock": {
        "name": "BlackRock, Inc.",
        "short_name": "BlackRock",
        "cik": "0001086364",
        "form_type": "13F-NT",
        "description": "全球最大資產管理機構",
    },
    "bridgewater": {
        "name": "Bridgewater Associates, LP",
        "short_name": "Bridgewater",
        "cik": "0002011169",
        "accession_prefix": "0001172661",
        "form_type": "13F-HR",
        "description": "全球最大避險基金（橋水基金）",
    },
}

# TSMC 識別關鍵字
TSMC_KEYWORDS = ["TAIWAN SEMICONDUCTOR", "TSMC", "TAIWAN SEMICONDUCTOR MFG"]


# ── HTTP 工具 ─────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # 使用標準瀏覽器 User-Agent（SEC 會封鎖非標準 UA）
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Encoding": "gzip, deflate",
    })
    return session


# ── SEC EDGAR API ─────────────────────────────────────────────────────

def get_latest_13f_filings(session: requests.Session, cik: str,
                          form_type: str = "13F-HR",
                          count: int = 2) -> List[Dict]:
    """從 SEC EDGAR submissions API 取得機構法人的 13F filing 索引"""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    cache_key = f"sec_13f_submissions_{cik}"

    def _fetch():
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    data = fetch_with_cache(
        policy_name="sec_13f",
        cache_key=cache_key,
        fetch_fn=_fetch,
    )

    filings = data.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    accession_numbers = filings.get("accessionNumber", [])
    filing_dates = filings.get("filingDate", [])
    primary_docs = filings.get("primaryDocument", [])
    report_dates = filings.get("reportDate", [])

    results = []
    for i, form in enumerate(forms):
        if not form.startswith(form_type):
            continue
        results.append({
            "accessionNumber": accession_numbers[i] if i < len(accession_numbers) else "",
            "filingDate": filing_dates[i] if i < len(filing_dates) else "",
            "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
            "reportDate": report_dates[i] if i < len(report_dates) else "",
            "form": form,
        })
        if len(results) >= count:
            break

    return results


def fetch_13f_xml(session: requests.Session, accession: str,
                 cik: str = None) -> str:
    """
    抓取 13F 報告的 XML 持股明細。

    URL 格式：
    - BlackRock: https://www.sec.gov/Archives/edgar/data/1086364/{acc}/xslForm13F_X02/primary_doc.xml
    - Bridgewater: https://www.sec.gov/Archives/edgar/data/2011169/{acc}/xslForm13F_X02/primary_doc.xml

    注意：URL 中的 CIK 路徑是實際申报機構的 CIK（BlackRock=1086364, Bridgewater GC Wealth=2011169），
    不是從 accession number 前綴取得的。
    """
    accession_clean = accession.replace("-", "")
    # 使用傳入的 cik (數字字串，如 "1086364" 或 "2011169")
    cik_num = str(int(cik)) if cik else "1086364"
    # 嘗試 xslForm13F_X02 子目錄
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/xslForm13F_X02/primary_doc.xml"
    cache_key = f"sec_13f_info_{accession}"

    def _fetch():
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            # fallback: 嘗試標準路径
            url2 = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/primary_doc.xml"
            resp = session.get(url2, timeout=60)
        resp.raise_for_status()
        return resp.text

    return fetch_with_cache(
        policy_name="sec_13f",
        cache_key=cache_key,
        fetch_fn=_fetch,
    )


# ── XML 解析 ──────────────────────────────────────────────────────────

def parse_holdings(xml_text: str) -> Dict[str, Dict]:
    """
    解析 form13fInfoTable.xml，提取所有持倉。
    回傳: {identifier: {"name": str, "shares": int, "value_usd": float, "class": str}}
    """
    holdings = defaultdict(lambda: {"name": "", "shares": 0, "value_usd": 0.0, "class": ""})

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML 解析失敗: {exc}")

    info_tables = root.findall(f"{{{NS}}}infoTable")
    if not info_tables:
        info_tables = root.findall(".//infoTable")

    for table in info_tables:
        name_el = table.find(f"{{{NS}}}nameOfIssuer")
        if name_el is None:
            name_el = table.find("nameOfIssuer")
        if name_el is None:
            continue
        issuer_name = (name_el.text or "").strip()

        class_el = table.find(f"{{{NS}}}titleOfClass")
        if class_el is None:
            class_el = table.find("titleOfClass")
        class_name = (class_el.text or "").strip() if class_el is not None else ""

        value_el = table.find(f"{{{NS}}}value")
        if value_el is None:
            value_el = table.find("value")
        if value_el is None:
            continue
        try:
            value = float(value_el.text or 0)
        except (ValueError, TypeError):
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

        key = issuer_name.upper()
        holdings[key]["name"] = issuer_name
        holdings[key]["shares"] += shares
        holdings[key]["value_usd"] += value
        holdings[key]["class"] = class_name

    return dict(holdings)


def find_tsmc(holdings: Dict[str, Dict]) -> Optional[Dict]:
    """在持倉中尋找 TSMC"""
    for key, data in holdings.items():
        for kw in TSMC_KEYWORDS:
            if kw in key:
                return data
    return None


def get_top_holdings(holdings: Dict[str, Dict], n: int = 10) -> List[Tuple[str, Dict]]:
    """按市值排序，回傳前 N 大持倉"""
    sorted_holdings = sorted(holdings.items(), key=lambda x: x[1]["value_usd"], reverse=True)
    return sorted_holdings[:n]


# ── 分析邏輯 ──────────────────────────────────────────────────────────

def analyze_tsmc(current: Optional[Dict], previous: Optional[Dict]) -> Dict:
    """分析 TSMC 持股變化"""
    if current is None and previous is None:
        return {"status": "not_held", "score": 50}

    if current is None:
        return {
            "status": "exited",
            "score": 20,
            "previous_shares": previous["shares"],
            "previous_value_usd": previous["value_usd"],
        }

    if previous is None:
        return {
            "status": "new",
            "score": 80,
            "shares": current["shares"],
            "value_usd": current["value_usd"],
        }

    change_shares = current["shares"] - previous["shares"]
    change_pct = (change_shares / previous["shares"] * 100) if previous["shares"] > 0 else float("inf")

    if change_shares > 0:
        status = "increased"
        score = 80
    elif change_shares < 0:
        status = "decreased"
        score = 40
    else:
        status = "unchanged"
        score = 65

    return {
        "status": status,
        "score": score,
        "shares": current["shares"],
        "value_usd": current["value_usd"],
        "previous_shares": previous["shares"],
        "previous_value_usd": previous["value_usd"],
        "change_shares": change_shares,
        "change_pct": change_pct,
    }


def format_shares(n: int) -> str:
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif abs(n) >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def format_usd(value_usd: float) -> str:
    """格式化美元（SEC 13F 的 value 單位是美元）"""
    if abs(value_usd) >= 1_000_000_000:
        return f"${value_usd / 1_000_000_000:.1f}B"
    elif abs(value_usd) >= 1_000_000:
        return f"${value_usd / 1_000_000:.1f}M"
    elif abs(value_usd) >= 1_000:
        return f"${value_usd / 1_000:.1f}K"
    return f"${value_usd:,.0f}"


def status_emoji(status: str) -> str:
    return {
        "new": "🟢 新建",
        "increased": "🟢 增持",
        "unchanged": "🟡 不變",
        "decreased": "🟠 減持",
        "exited": "🔴 清倉",
        "not_held": "⚪ 未持有",
    }.get(status, status)


# ── 報告生成 ──────────────────────────────────────────────────────────

def generate_report(all_results: Dict[str, Dict], report_date: str) -> str:
    """生成 Markdown 研究報告"""
    lines = [
        "# 🏛 機構法人 13F 季度持倉研究報告",
        "",
        f"**報告日期**: {report_date}",
        f"**數據來源**: SEC EDGAR Form 13F-HR / 13F-NT",
        f"**分析機構**: BlackRock, Inc. / Bridgewater Associates, LP",
        "",
        "---",
        "",
    ]

    # 摘要表
    lines.append("## 摘要")
    lines.append("")
    lines.append("| 機構 | TSMC 狀態 | TSMC 股數 | TSMC 市值 | 變動 | 分數 |")
    lines.append("|------|----------|----------|----------|------|------|")

    for key, info in INSTITUTIONS.items():
        result = all_results.get(key, {})
        tsmc = result.get("tsmc_analysis", {})
        status = tsmc.get("status", "not_held")
        shares = tsmc.get("shares", 0)
        value = tsmc.get("value_usd", 0)
        change_pct = tsmc.get("change_pct", 0)
        score = tsmc.get("score", "N/A")

        change_str = ""
        if status in ("increased", "decreased"):
            change_str = f"{change_pct:+.1f}%"
        elif status == "new":
            change_str = "新建"
        elif status == "exited":
            change_str = "清倉"

        shares_str = format_shares(shares) if shares > 0 else "—"
        value_str = format_usd(value) if value > 0 else "—"

        lines.append(
            f"| {info['short_name']} | {status_emoji(status)} | "
            f"{shares_str} | {value_str} | {change_str} | {score}/100 |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # 各機構詳細
    for key, info in INSTITUTIONS.items():
        result = all_results.get(key, {})
        if not result:
            lines.append(f"## {info['name']}")
            lines.append("")
            lines.append("⚠️ 資料取得失敗")
            lines.append("")
            continue

        filings = result.get("filings", [])
        current_filing = filings[0] if filings else {}
        previous_filing = filings[1] if len(filings) >= 2 else None

        lines.append(f"## {info['name']}（CIK: {info['cik']}）")
        lines.append("")

        lines.append("### 最新 13F 資訊")
        lines.append(f"- **報告季度**: {current_filing.get('reportDate', 'N/A')}")
        lines.append(f"- **申報日期**: {current_filing.get('filingDate', 'N/A')}")
        lines.append(f"- **表單類型**: {current_filing.get('form', 'N/A')}")
        if previous_filing:
            lines.append(f"- **上一季**: {previous_filing.get('reportDate', 'N/A')}（申報日: {previous_filing.get('filingDate', 'N/A')}）")
        lines.append("")

        # TSMC 分析
        tsmc = result.get("tsmc_analysis", {})
        lines.append("### TSMC 持股分析")
        lines.append("")

        status = tsmc.get("status", "not_held")
        if status == "new":
            lines.append(
                f"- **狀態**: 🟢 新建持倉\n"
                f"- **本季股數**: {format_shares(tsmc.get('shares', 0))}\n"
                f"- **市值**: {format_usd(tsmc.get('value_usd', 0))}"
            )
        elif status == "exited":
            lines.append(
                f"- **狀態**: 🔴 清倉離場\n"
                f"- **上季股數**: {format_shares(tsmc.get('previous_shares', 0))}\n"
                f"- **上季市值**: {format_usd(tsmc.get('previous_value_usd', 0))}"
            )
        elif status in ("increased", "decreased"):
            change = tsmc.get("change_shares", 0)
            pct = tsmc.get("change_pct", 0)
            direction = "增持" if change > 0 else "減持"
            lines.append(
                f"- **狀態**: {status_emoji(status)}\n"
                f"- **本季股數**: {format_shares(tsmc.get('shares', 0))}\n"
                f"- **上季股數**: {format_shares(tsmc.get('previous_shares', 0))}\n"
                f"- **變化**: {direction} {format_shares(abs(change))}（{pct:+.1f}%）\n"
                f"- **市值**: {format_usd(tsmc.get('value_usd', 0))}"
            )
        elif status == "unchanged":
            lines.append(
                f"- **狀態**: 🟡 持股不變\n"
                f"- **股數**: {format_shares(tsmc.get('shares', 0))}\n"
                f"- **市值**: {format_usd(tsmc.get('value_usd', 0))}"
            )
        else:
            lines.append("- **狀態**: ⚪ 目前未持有 TSMC 相關部位")

        lines.append("")

        # 前十大持股
        top_holdings = result.get("top_holdings", [])
        prev_holdings_map = result.get("previous_holdings_map", {})

        if top_holdings:
            total_value = sum(h[1]["value_usd"] for h in top_holdings) if top_holdings else 0

            lines.append("### 前十大持股")
            lines.append("")
            lines.append("| # | 公司 | 股數 | 市值 | 佔比 | 變動 |")
            lines.append("|---|------|------|------|------|------|")

            for rank, (name, data) in enumerate(top_holdings, 1):
                shares = data["shares"]
                value = data["value_usd"]
                pct = (value / total_value * 100) if total_value > 0 else 0

                prev_data = prev_holdings_map.get(name.upper())
                change_str = "—"
                if prev_data:
                    prev_value = prev_data["value_usd"]
                    if prev_value > 0:
                        value_change = ((value - prev_value) / prev_value) * 100
                        change_str = f"{value_change:+.1f}%"
                    elif value > 0:
                        change_str = "🆕"
                elif prev_holdings_map and value > 0:
                    change_str = "🆕"

                lines.append(
                    f"| {rank} | {name} | {format_shares(shares)} | "
                    f"{format_usd(value)} | {pct:.1f}% | {change_str} |"
                )

            lines.append("")

        # 重要變動
        significant_changes = result.get("significant_changes", [])
        if significant_changes:
            lines.append("### 重要變動")
            lines.append("")
            for change in significant_changes:
                lines.append(f"- {change}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # 跨機構比較
    lines.append("## 🔍 跨機構比較")
    lines.append("")

    lines.append("### TSMC 動向")
    lines.append("")
    lines.append("| 機構 | 狀態 | 分數 |")
    lines.append("|------|------|------|")
    for key, info in INSTITUTIONS.items():
        result = all_results.get(key, {})
        tsmc = result.get("tsmc_analysis", {})
        status = tsmc.get("status", "not_held")
        score = tsmc.get("score", "N/A")
        lines.append(f"| {info['short_name']} | {status_emoji(status)} | {score}/100 |")
    lines.append("")

    lines.append("### 主題分析")
    lines.append("")
    themes = analyze_themes(all_results)
    for theme in themes:
        lines.append(f"- {theme}")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*報告由 sec-13f-researcher agent 自動產成*")
    lines.append("*數據來源：SEC EDGAR，為公開資訊*")

    return "\n".join(lines)


def analyze_themes(all_results: Dict[str, Dict]) -> List[str]:
    """根據兩機構的持股變化，分析產業趨勢"""
    themes = []
    tsmc_statuses = {}

    for key, info in INSTITUTIONS.items():
        result = all_results.get(key, {})
        tsmc = result.get("tsmc_analysis", {})
        tsmc_statuses[key] = tsmc.get("status", "not_held")

    statuses = set(tsmc_statuses.values())
    if "increased" in statuses or "new" in statuses:
        themes.append("**半導體/AI 供應鏈**: 至少一家機構增持或新建 TSMC 部位，表達對半導體賽道的正面看法。")
    if "exited" in statuses:
        themes.append("**半導體降溫**: 至少一家機構清空 TSMC 部位，可能反映對半導體需求的保留態度。")
    if statuses == {"unchanged"}:
        themes.append("**TSMC 持股穩定**: 兩機構均維持 TSMC 持股不變，看法中性。")

    for key, info in INSTITUTIONS.items():
        result = all_results.get(key, {})
        top = result.get("top_holdings", [])
        if top:
            top_names = [h[0] for h in top[:5]]
            themes.append(f"**{info['short_name']} 前五大**: {', '.join(top_names)}")

    return themes


# ── 主程式 ──────────────────────────────────────────────────────────

def analyze_institution(session: requests.Session, key: str, info: Dict,
                        count: int = 2) -> Dict:
    """分析單一機構的最新 13F"""
    result = {"filings": []}

    try:
        filings = get_latest_13f_filings(
            session, info["cik"], info.get("form_type", "13F-HR"), count=count
        )

        if not filings:
            return {"error": f"找不到 {info['name']} 的 13F 報告"}

        result["filings"] = filings
        current = filings[0]
        previous = filings[1] if len(filings) >= 2 else None

        current_xml = fetch_13f_xml(session, current["accessionNumber"], info["cik"])
        current_holdings = parse_holdings(current_xml)

        previous_holdings = {}
        if previous:
            try:
                prev_xml = fetch_13f_xml(session, previous["accessionNumber"], info["cik"])
                previous_holdings = parse_holdings(prev_xml)
            except Exception:
                previous = None

        current_tsmc = find_tsmc(current_holdings)
        previous_tsmc = find_tsmc(previous_holdings) if previous_holdings else None
        result["tsmc_analysis"] = analyze_tsmc(current_tsmc, previous_tsmc)

        top_holdings = get_top_holdings(current_holdings, n=10)
        result["top_holdings"] = top_holdings
        result["previous_holdings_map"] = previous_holdings

        significant = []
        prev_top = get_top_holdings(previous_holdings, n=20) if previous_holdings else []
        prev_names = set(h[0] for h in prev_top)
        curr_names = set(h[0] for h in top_holdings)

        new_positions = curr_names - prev_names
        exited_positions = prev_names - curr_names

        for name in sorted(new_positions):
            data = current_holdings[name.upper()]
            if data["value_usd"] > 1_000_000:
                significant.append(f"🆕 新建持倉: {name}（{format_usd(data['value_usd'])}）")

        for name in sorted(exited_positions):
            if name in previous_holdings:
                data = previous_holdings[name]
                if data["value_usd"] > 1_000_000:
                    significant.append(f"❌ 清倉離場: {name}（原 {format_usd(data['value_usd'])}）")

        result["significant_changes"] = significant

    except Exception as exc:
        import traceback
        traceback.print_exc()
        result["error"] = str(exc)

    return result


def main():
    parser = argparse.ArgumentParser(description="SEC 13F 季度持倉研究")
    parser.add_argument("--output", type=str, default=None,
                        help="報告輸出路徑（預設: reports/13f_research_YYYYMMDD.md）")
    parser.add_argument("--count", type=int, default=2,
                        help="比較的季度數（預設: 2 = 最新 + 上一季）")
    args = parser.parse_args()

    session = make_session()
    report_date = datetime.now().strftime("%Y-%m-%d")

    print("=" * 60)
    print("🏛 SEC 13F 季度持倉研究")
    print("=" * 60)
    print()

    all_results = {}
    for key, info in INSTITUTIONS.items():
        print(f"📡 正在分析 {info['name']}（CIK: {info['cik']}）...")
        result = analyze_institution(session, key, info, count=args.count)
        all_results[key] = result

        if "error" in result:
            print(f"  ⚠️ 錯誤: {result['error']}")
        else:
            filings = result.get("filings", [])
            if filings:
                print(f"  ✅ 最新 13F: {filings[0].get('reportDate', 'N/A')}（{filings[0].get('filingDate', 'N/A')}）")
            tsmc = result.get("tsmc_analysis", {})
            print(f"  📊 TSMC: {status_emoji(tsmc.get('status', 'not_held'))}")
        print()

    report = generate_report(all_results, report_date)

    os.makedirs("reports", exist_ok=True)

    if args.output:
        output_path = args.output
    else:
        output_path = f"reports/13f_research_{datetime.now().strftime('%Y%m%d')}.md"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"📝 報告已寫入: {output_path}")
    print()
    print("=" * 60)
    print("📋 報告摘要")
    print("=" * 60)
    print()

    for key, info in INSTITUTIONS.items():
        result = all_results.get(key, {})
        tsmc = result.get("tsmc_analysis", {})
        status = tsmc.get("status", "not_held")
        score = tsmc.get("score", "N/A")
        print(f"  {info['short_name']}: TSMC {status_emoji(status)} | 分數: {score}/100")

    print()
    print("完整報告請見:", output_path)


if __name__ == "__main__":
    main()
