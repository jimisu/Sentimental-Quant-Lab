#!/usr/bin/env python3
"""
13F 抓取診斷工具 — 逐步顯示每個環節的狀態，方便排查問題。

用法：
  python diag_13f.py [--cik <CIK>] [--all]
  python diag_13f.py --cik 0002012383
  python diag_13f.py --all
"""

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# ── 配置 ──
FETCH_TZ = timezone(timedelta(hours=-5))  # 美東時間

INSTITUTIONS = {
    "0002012383": "BlackRock, Inc.",
    "0001350694": "Bridgewater Associates, LP",
}

TARGET_COMPANIES = {
    "TSM":  ["TAIWAN SEMICONDUCTOR", "TSMC"],
    "MSFT": ["MICROSOFT CORP"],
    "GOOGL":["ALPHABET INC"],
    "AMZN": ["AMAZON COM INC"],
    "NVDA": ["NVIDIA CORPORATION"],
}

SEC_HEADERS = {
    "User-Agent": "Sentimental-Quant-Lab/1.0 (diagnostic)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def log(step: str, msg: str, ok: bool = True):
    icon = "✅" if ok else "❌"
    print(f"  {icon} [{step}] {msg}")


def warn(msg: str):
    print(f"  ⚠️  {msg}")


def diag_cik(cik: str, name: str):
    print(f"\n{'='*60}")
    print(f"🔍 診斷：{name}（CIK: {cik}）")
    print(f"{'='*60}")

    now_eastern = datetime.now(FETCH_TZ)
    print(f"\n📅 目前美東時間：{now_eastern.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    fetch_months = {2, 5, 8, 11}
    fetch_day = 15
    is_fetch_day = now_eastern.month in fetch_months and now_eastern.day == fetch_day
    log("排程", f"{'是' if is_fetch_day else '非'}抓取日（{fetch_months}/{fetch_day}）", is_fetch_day)

    # ── Step 1: Submissions API ──
    print(f"\n── Step 1: Submissions API ──")
    sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    log("URL", sub_url)

    # 檢查快取
    cache_files = sorted(glob.glob(f"local_cache/sec_13f_submissions_{cik}*.json"))
    if cache_files:
        newest = cache_files[-1]
        with open(newest) as f:
            cached = json.load(f)
        cached_at = cached.get("cached_at", "?")
        age_h = (datetime.now() - datetime.fromisoformat(cached_at.replace("Z", "+00:00"))).total_seconds() / 3600
        log("快取", f"{len(cache_files)} 個快取檔，最新：{os.path.basename(newest)}（{cached_at}，{age_h:.1f}h 前）")
    else:
        log("快取", "無快取", False)

    try:
        r = requests.get(sub_url, headers=SEC_HEADERS, timeout=30)
        log("HTTP", f"Status {r.status_code}", r.status_code == 200)
        if r.status_code != 200:
            log("錯誤", r.text[:200], False)
            return
        data = r.json()
        entity_name = data.get("name", "?")
        log("機構", entity_name)
    except Exception as e:
        log("錯誤", str(e), False)
        return

    # ── Step 2: 找 13F filings ──
    print(f"\n── Step 2: 13F Filings ──")
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    reports = recent.get("reportDate", [])

    filings_13f = []
    for i, form in enumerate(forms):
        if not form.startswith("13F"):
            continue
        filings_13f.append({
            "form": form,
            "date": dates[i] if i < len(dates) else "?",
            "acc": accs[i] if i < len(accs) else "?",
            "doc": docs[i] if i < len(docs) else "?",
            "report": reports[i] if i < len(reports) else "?",
        })

    log("13F", f"找到 {len(filings_13f)} 筆 13F filing")
    for f in filings_13f[:6]:
        is_nt = f["form"] == "13F-NT"
        log(f"  {f['report']}", f"{f['form']} | 申報 {f['date']} | acc={f['acc']} | doc={f['doc']}", not is_nt)

    # ── Step 3: 測試每個 accession 的 URL ──
    print(f"\n── Step 3: 持股明細 URL 測試 ──")
    for f in filings_13f[:4]:
        if f["form"] == "13F-NT":
            log("跳過", f"{f['acc']} 為 13F-NT Notice（無持股明細）", False)
            continue

        acc = f["acc"]
        acc_clean = acc.replace("-", "")
        cik_path = acc.split("-")[0]

        # 測試 .txt
        url_txt = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{acc_clean}/{acc}.txt"
        try:
            r_txt = requests.get(url_txt, headers=SEC_HEADERS, timeout=30)
            txt_ok = r_txt.status_code == 200 and len(r_txt.text) > 100
            log(".txt", f"{r_txt.status_code} | {len(r_txt.text):,} bytes | {url_txt[-60:]}", txt_ok)
            if not txt_ok:
                # 測試 infotable.xml
                url_xml = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{acc_clean}/xslForm13F_X02/infotable.xml"
                r_xml = requests.get(url_xml, headers=SEC_HEADERS, timeout=30)
                xml_ok = r_xml.status_code == 200 and len(r_xml.text) > 100
                log("  .xml", f"{r_xml.status_code} | {len(r_xml.text):,} bytes", xml_ok)
                if not xml_ok:
                    # 測試 primary_doc.xml
                    url_pri = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{acc_clean}/xslForm13F_X02/primary_doc.xml"
                    r_pri = requests.get(url_pri, headers=SEC_HEADERS, timeout=30)
                    pri_ok = r_pri.status_code == 200 and len(r_pri.text) > 100
                    log("  primary", f"{r_pri.status_code} | {len(r_pri.text):,} bytes", pri_ok)
        except Exception as e:
            log("錯誤", f"{acc}: {e}", False)

    # ── Step 4: 解析測試 ──
    print(f"\n── Step 4: 解析測試 ──")
    for f in filings_13f[:4]:
        if f["form"] == "13F-NT":
            continue
        acc = f["acc"]
        acc_clean = acc.replace("-", "")
        cik_path = acc.split("-")[0]

        # 檢查快取
        info_cache = sorted(glob.glob(f"local_cache/sec_13f_infotable_{acc}*.json"))
        if not info_cache:
            # 嘗試從 SEC 抓
            url_txt = f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{acc_clean}/{acc}.txt"
            try:
                r = requests.get(url_txt, headers=SEC_HEADERS, timeout=30)
                if r.status_code != 200 or len(r.text) < 100:
                    log("解析", f"{acc}: 無快取且無法抓取", False)
                    continue
                content = r.text
            except Exception as e:
                log("解析", f"{acc}: {e}", False)
                continue
        else:
            with open(info_cache[-1]) as fh:
                content = json.load(fh).get("data", "")

        # 偵測格式
        has_info_table = bool(re.search(r"<\w+:infoTable>", content))
        has_n2 = "<n2:infoTable>" in content
        has_ns1 = "<ns1:infoTable>" in content
        has_bare = "<infoTable>" in content
        has_tr = "<tr>" in content

        ns_prefixes = set(re.findall(r"<(\w+):infoTable>", content))
        log("格式", f"infoTable 前綴: {ns_prefixes or '無'} | tr={has_tr} | 大小={len(content):,}", has_info_table or has_tr)

        # 用 regex 解析
        entries = re.findall(r"<\w+:infoTable>(.*?)</\w+:infoTable>", content, re.DOTALL)
        if not entries:
            entries = re.findall(r"<infoTable>(.*?)</infoTable>", content, re.DOTALL)
        log("entries", f"找到 {len(entries)} 個 infoTable entries", len(entries) > 0)

        # 找目標持股
        found = {}
        for ticker, names in TARGET_COMPANIES.items():
            for entry in entries:
                name_m = re.search(r"<\w+:nameOfIssuer>(.*?)</\w+:nameOfIssuer>", entry)
                if not name_m:
                    name_m = re.search(r"<nameOfIssuer>(.*?)</nameOfIssuer>", entry)
                if name_m:
                    issuer = name_m.group(1).strip()
                    for n in names:
                        if n.upper() in issuer.upper():
                            shares_m = re.search(r"<\w+:sshPrnamt>(.*?)</\w+:sshPrnamt>", entry)
                            if not shares_m:
                                shares_m = re.search(r"<sshPrnamt>(.*?)</sshPrnamt>", entry)
                            value_m = re.search(r"<\w+:value>(.*?)</\w+:value>", entry)
                            if not value_m:
                                value_m = re.search(r"<value>(.*?)</value>", entry)
                            shares = int(shares_m.group(1)) if shares_m else 0
                            value = float(value_m.group(1)) if value_m else 0
                            found[ticker] = {"shares": shares, "value_k": value / 1000, "name": issuer}
                            break

        if found:
            for ticker, info in found.items():
                log(f"  {ticker}", f"{info['name'][:40]} | {info['shares']:,} 股 | ${info['value_k']:,.0f}K")
        else:
            log("持股", "未找到目標持股", False)

    # ── Step 5: 現有快取狀態 ──
    print(f"\n── Step 5: 快取狀態 ──")
    all_cache = sorted(glob.glob(f"local_cache/sec_13f_*{cik}*.json"))
    log("快取檔", f"共 {len(all_cache)} 個")
    for f in all_cache[-10:]:
        size = os.path.getsize(f)
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%m-%d %H:%M")
        print(f"    {os.path.basename(f)[:70]:70s} {size:>10,}B  {mtime}")

    # ── Step 6: 建議 ──
    print(f"\n── 建議 ──")
    issues = []

    # 檢查 submissions 快取年齡
    if cache_files:
        with open(cache_files[-1]) as f:
            cached = json.load(f)
        cached_at = cached.get("cached_at", "")
        if cached_at:
            age_h = (datetime.now() - datetime.fromisoformat(cached_at.replace("Z", "+00:00"))).total_seconds() / 3600
            if age_h > 48:
                issues.append(f"submissions 快取過舊（{age_h:.0f}h），建議刪除重新抓取")

    # 檢查是否有 infotable 快取
    info_caches = glob.glob(f"local_cache/sec_13f_infotable_*.json")
    if not info_caches:
        issues.append("無任何 infotable 快取，首次抓取需要存取 SEC Archives")

    # 檢查 retry 標記
    retry_files = glob.glob("local_cache/sec_13f_retry_*.json")
    if retry_files:
        issues.append(f"有 {len(retry_files)} 個 retry 標記檔，可能阻擋重新抓取")

    if issues:
        for i, issue in enumerate(issues, 1):
            warn(f"{i}. {issue}")
    else:
        log("狀態", "無明顯問題")

    print()


def main():
    parser = argparse.ArgumentParser(description="13F 抓取診斷工具")
    parser.add_argument("--cik", help="指定 CIK 號碼")
    parser.add_argument("--all", action="store_true", help="診斷所有已註冊機構")
    args = parser.parse_args()

    print("🔧 13F 抓取診斷工具")
    print(f"   local_cache/: {os.path.abspath('local_cache')}")

    if args.cik:
        name = INSTITUTIONS.get(args.cik, f"CIK {args.cik}")
        diag_cik(args.cik, name)
    elif args.all:
        for cik, name in INSTITUTIONS.items():
            diag_cik(cik, name)
    else:
        parser.print_help()
        print(f"\n已註冊機構：")
        for cik, name in INSTITUTIONS.items():
            print(f"  {cik}: {name}")


if __name__ == "__main__":
    main()
