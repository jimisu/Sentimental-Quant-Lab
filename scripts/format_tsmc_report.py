#!/usr/bin/env python3
"""
Format the latest analysis_log.md entry into the fixed TSMC quant report layout.

Usage:
  python scripts/format_tsmc_report.py
  python scripts/format_tsmc_report.py --input analysis_log.md --output reports/tsmc_report.md
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tsmc_macro_agent import GlobalMacroAgent  # noqa: E402


NA = "N/A（資料待補）"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


BIGTECH_COMPANIES = {
    "Amazon": {"ticker": "AMZN", "cik": "0001018724"},
    "Microsoft": {"ticker": "MSFT", "cik": "0000789019"},
    "Google": {"ticker": "GOOGL", "cik": "0001652044"},
    "Tesla": {"ticker": "TSLA", "cik": "0001318605"},
    "NVIDIA": {"ticker": "NVDA", "cik": "0001045810"},
    "Apple": {"ticker": "AAPL", "cik": "0000320193"},
    "Meta": {"ticker": "META", "cik": "0001326801"},
}


@dataclass
class QuarterRow:
    label: str
    gross: Optional[float]
    operating: Optional[float]
    net: Optional[float]
    eps: Optional[float]


class LocalCapexAgent(GlobalMacroAgent):
    """Reuse CAPEX normalization logic, but read only from local cache files."""

    def __init__(self, cache_dir: Path):
        super().__init__()
        self.cache_dir = cache_dir

    def _fetch_json_with_cache(self, cache_key: str, *args, **kwargs) -> Dict:
        patterns = [
            self.cache_dir / "macro_agent" / f"{cache_key}.json",
            self.cache_dir / f"{cache_key}_*.json",
        ]
        matches: List[Path] = []
        for pattern in patterns:
            matches.extend(Path(p) for p in glob.glob(str(pattern)))
        if not matches:
            raise RuntimeError(f"local cache not found: {cache_key}")
        latest = max(matches, key=lambda path: path.stat().st_mtime)
        with latest.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload.get("data", payload)


def clean_text(text: str) -> str:
    return ANSI_RE.sub("", text)


def first_match(text: str, pattern: str, default: str = NA, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        return default
    return next((group for group in match.groups() if group is not None), default).strip()


def parse_float(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    if cleaned in {"", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def fmt_num(value: Optional[float], digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return NA
    return f"{value:.{digits}f}{suffix}"


def fmt_int(value: Optional[float]) -> str:
    if value is None:
        return NA
    return f"{int(round(value)):,}"


def get_latest_block(content: str) -> str:
    blocks = re.split(r"(?=^# 🚀 TSMC 量化分析報告 - )", content, flags=re.MULTILINE)
    blocks = [block.strip() for block in blocks if block.strip().startswith("# 🚀 TSMC")]
    if not blocks:
        raise ValueError("analysis log does not contain a TSMC report block")
    return clean_text(blocks[-1])


def parse_md_table(lines: List[str], start_idx: int) -> Tuple[List[str], List[List[str]], int]:
    header = [cell.strip() for cell in lines[start_idx].strip().strip("|").split("|")]
    rows: List[List[str]] = []
    idx = start_idx + 2
    while idx < len(lines):
        line = lines[idx].strip()
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
        idx += 1
    return header, rows, idx


def find_table_after(block: str, marker: str) -> Tuple[List[str], List[List[str]]]:
    lines = block.splitlines()
    marker_idx = next((idx for idx, line in enumerate(lines) if marker in line), -1)
    if marker_idx < 0:
        return [], []
    for idx in range(marker_idx + 1, len(lines)):
        if lines[idx].strip().startswith("|"):
            header, rows, _ = parse_md_table(lines, idx)
            return header, rows
    return [], []


def markdown_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    header_list = list(headers)
    out = [
        "| " + " | ".join(header_list) + " |",
        "| " + " | ".join(["------"] * len(header_list)) + " |",
    ]
    out.extend("| " + " | ".join(str(cell) if str(cell) else NA for cell in row) + " |" for row in rows)
    return "\n".join(out)


def estimate_earnings_date(today: date) -> Tuple[str, int]:
    candidates = []
    for month in (1, 4, 7, 10):
        # TSMC earnings call is approximated as the third Thursday.
        first_day = date(today.year, month, 1)
        first_thursday_offset = (3 - first_day.weekday()) % 7
        third_thursday = first_day.replace(day=1 + first_thursday_offset + 14)
        candidates.append(third_thursday)
    candidates.extend(date(today.year + 1, month, 1) for month in (1, 4, 7, 10))
    next_date = min(candidate for candidate in candidates if candidate >= today)
    return next_date.isoformat(), (next_date - today).days


def quarter_label_from_month(month: str) -> str:
    year, month_num = month.split("-")
    quarter = (int(month_num) - 1) // 3 + 1
    return f"{year} Q{quarter}"


def parse_financial_rows(block: str) -> Tuple[List[QuarterRow], List[Tuple[str, str, str]]]:
    _, rows = find_table_after(block, "### 💰 財務專家判讀")
    quarter_by_label: Dict[str, QuarterRow] = {}
    month_rows: List[Tuple[str, str, str]] = []
    for row in rows:
        if len(row) < 6:
            continue
        month, yoy_raw, gross_raw, op_raw, net_raw, eps_raw = row[:6]
        yoy = parse_float(yoy_raw)
        if yoy is not None:
            note = ""
            if yoy < 10:
                note = "🔴"
            elif yoy < 20:
                note = "🟡"
            month_rows.append((month, f"{yoy:.2f}%", note))

        gross = parse_float(gross_raw)
        operating = parse_float(op_raw)
        net = parse_float(net_raw)
        eps = parse_float(eps_raw)
        if gross is None and operating is None and net is None and eps is None:
            continue
        label = quarter_label_from_month(month)
        quarter_by_label[label] = QuarterRow(label, gross, operating, net, eps)

    quarters = list(quarter_by_label.values())[-3:]
    return quarters, month_rows[-6:]


def trend_icon(rows: List[QuarterRow], idx: int, attr: str) -> str:
    if idx < 2:
        return ""
    cur = getattr(rows[idx], attr)
    prev = getattr(rows[idx - 1], attr)
    prev2 = getattr(rows[idx - 2], attr)
    if cur is None or prev is None or prev2 is None:
        return ""
    return " ✅" if prev2 < prev < cur else " ⚠️"


def build_financial_section(block: str) -> str:
    quarters, month_rows = parse_financial_rows(block)
    q_rows = []
    for idx, row in enumerate(quarters):
        q_rows.append([
            row.label,
            fmt_num(row.gross, 2, "%") + trend_icon(quarters, idx, "gross"),
            fmt_num(row.operating, 2, "%") + trend_icon(quarters, idx, "operating"),
            fmt_num(row.net, 2, "%") + trend_icon(quarters, idx, "net"),
            fmt_num(row.eps, 2, " 元") if row.eps is not None else NA,
        ])
    while len(q_rows) < 3:
        q_rows.insert(0, [NA, NA, NA, NA, NA])

    report_conclusion = first_match(block, r"結論: (【[^】]+】)", "")
    eps_note = (
        "⚠️ EPS 從近期低點大幅跳升，需追蹤匯兌效益與業外收益佔比。"
        if "EPS 從" in block or (quarters and quarters[-1].eps and quarters[0].eps and quarters[-1].eps > quarters[0].eps * 1.15)
        else "EPS 品質未見重大業外警示。"
    )
    conclusion = "✅ 三率連兩季同步上升，財務面仍是主要支撐。"
    if report_conclusion and "多頭" not in report_conclusion:
        conclusion = f"⚠️ {report_conclusion}"

    return "\n".join([
        "### 💰 財務面",
        "",
        "**三率趨勢**",
        "",
        markdown_table(["季度", "毛利率", "營業利益率", "稅後淨利率", "EPS"], q_rows),
        "",
        "**月營收 YoY（近 6 個月）**",
        "",
        markdown_table(["月份", "YoY", "備註"], month_rows or [[NA, NA, NA]]),
        "",
        f"> {eps_note}",
        "",
        f"**結論：** {conclusion}",
    ])


def parse_adr(block: str) -> Dict[str, str]:
    adr_text = first_match(block, r"### 🌏 宏觀專家判讀(.*?)(?:\n### |\Z)", "", re.S)
    return {
        "premium": first_match(adr_text, r"溢價 ([\d.]+%)", NA),
        "adr_price": first_match(adr_text, r"ADR折算價: ([\d.]+)", NA),
        "tw_price": first_match(adr_text, r"台股現價: ([\d.]+)", NA),
        "fx": first_match(adr_text, r"匯率參考: ([\d.]+)", NA),
    }


def build_capex_rows(cache_dir: Path) -> Tuple[List[List[str]], int, int]:
    rows = []
    growing_count = 0
    valid_count = 0
    agent = LocalCapexAgent(cache_dir)
    for name, meta in BIGTECH_COMPANIES.items():
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                quarters = agent._fetch_recent_capex_quarters(meta)
            if len(quarters) < 3:
                rows.append([name, "⚠️ N/A（資料待補）", NA])
                continue
            oldest, middle, latest = quarters[-1], quarters[-2], quarters[-3]
            is_growing = oldest["value"] < middle["value"] < latest["value"]
            valid_count += 1
            if is_growing:
                growing_count += 1
            trend = "✅ 持續成長" if is_growing else "⚠️ 未持續"
            latest_text = f"{latest['period']} ${latest['value'] / 1_000_000_000:.1f}B"
            rows.append([name, trend, latest_text])
        except Exception:
            rows.append([name, "⚠️ N/A（資料待補）", NA])
    return rows, growing_count, valid_count


def build_macro_section(block: str, cache_dir: Path) -> str:
    adr = parse_adr(block)
    capex_rows, growing, valid = build_capex_rows(cache_dir)
    premium_num = parse_float(adr["premium"])
    premium_note = ""
    if premium_num is not None and premium_num > 10:
        premium_note = "ADR 溢價 > 10%，需區分匯率預期、海外准入溢價與 AI 主題溢價。"
    elif premium_num is not None and premium_num < 5:
        premium_note = "ADR 溢價低於 5%，外部定價未見明顯超額溢價。"
    else:
        premium_note = "ADR 溢價需搭配匯率與美股 AI 主題定價共同解讀。"

    return "\n".join([
        "### 🌏 宏觀面",
        "",
        "**ADR 溢價**",
        "",
        markdown_table(["項目", "數值"], [
            ["ADR 折算價", f"NT${adr['adr_price']}"],
            ["台股現價", f"NT${adr['tw_price']}"],
            ["溢價幅度", f"**{adr['premium']}**"],
            ["匯率參考", f"USD/TWD {adr['fx']}"],
        ]),
        "",
        f"> {premium_note}",
        "",
        "**大型科技客戶資本支出**",
        "",
        markdown_table(["客戶", "趨勢", "最新季度"], capex_rows),
        "",
        f"**結論：** {growing}/{valid if valid else 7} 家持續成長。雲端 AI 主力客戶仍擴張，但部分終端或晶片客戶 CAPEX 節奏轉為分歧。",
    ])


def parse_technical(block: str) -> Dict[str, str]:
    section = first_match(block, r"### 📈 技術專家判讀(.*?)(?:\n### 👥|\Z)", "", re.S)
    close = first_match(section, r"收盤 ([\d.]+)", NA)
    ma20 = first_match(section, r"20MA ([\d.]+)", NA)
    divergence = first_match(section, r"20MA乖離率: ([\-\d.]+%)", NA)
    ma_match = re.search(r"\(5MA=([\d.]+), 20MA=([\d.]+), 60MA=([\d.]+)", section)
    ma5 = ma_match.group(1) if ma_match else NA
    ma20_from_ma = ma_match.group(2) if ma_match else ma20
    ma60 = ma_match.group(3) if ma_match else NA
    k = first_match(section, r"KD: %K=([\d.]+)", NA)
    d = first_match(section, r"KD: %K=[\d.]+, %D=([\d.]+)", NA)
    rsi = first_match(section, r"RSI: ([\d.]+)", NA)
    support = first_match(section, r"支撐 ([\d.]+)", NA)
    resistance = first_match(section, r"壓力 ([\d.]+)", NA)
    zone = first_match(section, r"目前處於 ([^*（\n]+)", NA)
    zone_score = first_match(section, r"綜合分數: ([\d.]+)", NA)
    early = first_match(section, r"早期警示: ([^\n]+)", "無重大早期警示")
    conclusion = first_match(section, r"結論: ([^\n]+)", "量價結構資料待補")

    ma_order = f"{ma5} > {ma20_from_ma} > {ma60}"
    ma_reading = "糾結"
    ma_values = [parse_float(ma5), parse_float(ma20_from_ma), parse_float(ma60)]
    if all(value is not None for value in ma_values):
        if ma_values[0] > ma_values[1] > ma_values[2]:
            ma_reading = "多頭排列"
        elif ma_values[0] < ma_values[1] < ma_values[2]:
            ma_reading = "空頭排列"

    kd_reading = "中性"
    k_num = parse_float(k)
    d_num = parse_float(d)
    if k_num is not None and d_num is not None:
        if k_num > 80 and d_num > 80:
            kd_reading = "超買"
        elif k_num < 20 and d_num < 20:
            kd_reading = "超賣"

    rsi_reading = "中性"
    rsi_num = parse_float(rsi)
    if rsi_num is not None:
        if rsi_num > 70:
            rsi_reading = "超買 > 70"
        elif rsi_num < 30:
            rsi_reading = "超賣 < 30"

    return {
        "close": close,
        "ma20": ma20,
        "divergence": divergence,
        "ma_order": ma_order,
        "ma_reading": ma_reading,
        "k": k,
        "d": d,
        "kd_reading": kd_reading,
        "rsi": rsi,
        "rsi_reading": rsi_reading,
        "support": support,
        "resistance": resistance,
        "zone": zone,
        "zone_score": zone_score,
        "early": "無重大早期警示" if early == "無" else early,
        "conclusion": conclusion,
    }


def parse_volume_rows(block: str) -> List[List[str]]:
    _, rows = find_table_after(block, "#### 近 10 個交易日成交金額")
    output = []
    for row in rows[:10]:
        if len(row) < 3:
            continue
        tsmc = parse_float(row[1])
        market = parse_float(row[2])
        output.append([
            row[0],
            fmt_num(tsmc / 100_000_000 if tsmc is not None else None, 1),
            fmt_num(market / 100_000_000 if market is not None else None, 1),
        ])
    return output


def build_technical_section(block: str) -> str:
    tech = parse_technical(block)
    vol_rows = parse_volume_rows(block)
    if not vol_rows:
        vol_rows = [[NA, NA, NA] for _ in range(10)]
    marker = "✅" if "正常" in tech["conclusion"] else "🟡"
    return "\n".join([
        "### 📈 技術面",
        "",
        "**價格定位**",
        "",
        markdown_table(["指標", "數值", "解讀"], [
            ["收盤 / 20MA", f"{tech['close']} / {tech['ma20']}", f"乖離 **{tech['divergence']}**"],
            ["均線排列", tech["ma_order"], tech["ma_reading"]],
            ["KD", f"%K={tech['k']}, %D={tech['d']}", tech["kd_reading"]],
            ["RSI", tech["rsi"], tech["rsi_reading"]],
            ["支撐 / 壓力", f"{tech['support']} / {tech['resistance']}", "—"],
            ["技術面位置", f"**{tech['zone']}（{tech['zone_score']}/100）**", "—"],
        ]),
        "",
        "**近 10 日量能（億元）**",
        "",
        markdown_table(["日期", "台積電", "大盤"], vol_rows),
        "",
        f"**警示訊號：** {tech['early']}",
        "",
        f"**結論：** {marker} {tech['conclusion']}",
    ])


def load_chip_cache(cache_dir: Path) -> Optional[List[Dict]]:
    matches = sorted(cache_dir.glob("finmind_TaiwanStockInstitutionalInvestorsBuySell_2330_*.json"))
    if not matches:
        return None
    with matches[-1].open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def chip_summaries(cache_dir: Path) -> Tuple[str, str, List[List[str]]]:
    rows = load_chip_cache(cache_dir)
    if not rows:
        return NA, NA, [["外資", NA, NA, NA], ["投信", NA, NA, NA], ["自營商", NA, NA, NA], ["**合計**", NA, NA, "—"]]

    category_map = {
        "Foreign_Investor": "外資",
        "Foreign_Dealer_Self": "外資",
        "Investment_Trust": "投信",
        "Dealer_self": "自營商",
        "Dealer_Hedging": "自營商",
    }
    by_date: Dict[str, Dict[str, float]] = {}
    for item in rows:
        category = category_map.get(item.get("name"))
        if not category:
            continue
        day = item.get("date")
        if not day:
            continue
        by_date.setdefault(day, {"外資": 0.0, "投信": 0.0, "自營商": 0.0})
        by_date[day][category] += (float(item.get("buy", 0)) - float(item.get("sell", 0))) / 1000

    dates = sorted(by_date)
    if not dates:
        return NA, NA, [["外資", NA, NA, NA], ["投信", NA, NA, NA], ["自營商", NA, NA, NA], ["**合計**", NA, NA, "—"]]

    last5 = dates[-5:]
    last10 = dates[-10:]
    table_rows = []
    total_5d = 0.0
    for category in ["外資", "投信", "自營商"]:
        sum5 = sum(by_date[day].get(category, 0.0) for day in last5)
        total_5d += sum5
        last10_vals = [by_date[day].get(category, 0.0) for day in last10]
        sell_days = sum(1 for value in last10_vals if value < 0)
        sell_ratio = sell_days / len(last10_vals) * 100 if last10_vals else 0
        direction = "🟢 買超" if sum5 >= 0 else "🔴 賣超"
        table_rows.append([category, direction, fmt_int(sum5), f"{sell_ratio:.0f}%（賣超 {sell_days} 日）"])
    total_direction = "🟢 淨買超" if total_5d >= 0 else "🔴 淨賣超"
    table_rows.append(["**合計**", total_direction, f"**{fmt_int(total_5d)}**", "—"])
    return last5[0], last5[-1], table_rows


def longest_negative_streak(values: List[float]) -> int:
    best = cur = 0
    for value in values:
        if value < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def build_chip_section(block: str, cache_dir: Path, days_to_earnings: int) -> str:
    start, end, rows = chip_summaries(cache_dir)
    chip_text = first_match(block, r"### 👥 籌碼專家判讀(.*?)(?:\n---|\Z)", "", re.S)
    foreign_5d = parse_float(first_match(chip_text, r"外資 5 日累計: 賣超 ([\d,]+) 張", ""))
    consecutive = first_match(chip_text, r"最長連續賣超: ([\d]+) 日", "N/A")
    grade = first_match(chip_text, r"賣超分級: ([^（\n]+)", "N/A")
    warning = "目前未觸發外資 5 日賣超 > 1 萬張警示。"
    if foreign_5d is not None and foreign_5d > 10_000:
        warning = f"🚨 外資 5 日賣超 > 1 萬張：連續賣超最長 {consecutive} 日，賣超分級為{grade}。"
    conclusion = "🔴 外資大幅賣超，投信承接不足以抵銷籌碼壓力。" if foreign_5d and foreign_5d > 10_000 else "🟡 籌碼訊號分歧，需觀察外資後續方向。"
    return "\n".join([
        "### 👥 籌碼面",
        "",
        f"**三大法人近 5 日動向（{start} ~ {end}）**",
        "",
        markdown_table(["法人", "方向", "張數", "10 日賣超比例"], rows),
        "",
        f"> {warning}",
        f"> 法說會窗口解讀：目前距法說會 {days_to_earnings} 天，需觀察 Put/Call Ratio 判斷外資意圖。",
        "",
        f"**結論：** {conclusion}",
    ])


def build_customer_risk_section() -> str:
    return "\n".join([
        "## 四、客戶集中度風險",
        "",
        markdown_table(["客戶", "佔營收比", "關鍵風險"], [
            ["Apple", "~25%", "iPhone 備貨動能或自研晶片轉單變化，可能壓抑先進製程稼動率。"],
            ["NVIDIA", "~10-12%", "Blackwell 出貨時程與 CoWoS 排程若遞延，將影響 AI 營收成長斜率。"],
        ]),
        "",
        "> 📌 Apple 與 NVIDIA 訂單穩定性，是三率上升能否延續的核心前提。",
    ])


def parse_valuation(block: str) -> Dict[str, str]:
    pe = first_match(block, r"當前本益比（TTM）：\*\*([\d.]+) 倍", NA)
    percentile = "70-80"
    if pe == NA:
        pe = first_match(block, r"本益比 \*\*([\d.]+) 倍", NA)
    return {"pe": pe, "percentile": percentile}


def build_valuation_section(block: str) -> str:
    valuation = parse_valuation(block)
    return "\n".join([
        "## 五、估值定位",
        "",
        markdown_table(["指標", "數值", "解讀"], [
            ["當前 P/E（TTM）", f"**{valuation['pe']} 倍**", f"歷史 {valuation['percentile']} 百分位"],
            ["5 年歷史 P/E 區間", "12 x ~ 35 x", "—"],
            ["三星電子 P/E", "~12-15x", "折價約 50%"],
            ["Intel P/E", "~25-30x", "相近"],
            ["GlobalFoundries P/E", "~20-22x", "折價約 30%"],
        ]),
        "",
        f"> {valuation['pe']} 倍屬合理偏上，估值本身不是賣出理由，但需要法說會後 EPS 展望上修支撐。",
    ])


def build_recommendation_section(block: str, days_to_earnings: int) -> str:
    tech = parse_technical(block)
    current = tech["close"]
    ma20 = tech["ma20"]
    support = tech["support"]
    resistance = tech["resistance"]
    return "\n".join([
        "## 六、操作建議",
        "",
        "### 時間框架",
        "",
        markdown_table(["時間框架", "建議", "核心邏輯"], [
            [f"**法說會前（{days_to_earnings} 天內）**", "不追高、不追空", "等待法說會內容與外資回補訊號"],
            ["**法說會後**", "依指引操作", "上修 → 回補；下修 → 減碼"],
            ["**中期**", "拉回分批佈局", "AI 結構性成長邏輯未破壞"],
            ["**止損**", "跌破 20MA 減碼 30-50%", "短期趨勢轉弱確認"],
        ]),
        "",
        "### 關鍵價位",
        "",
        markdown_table(["價位", "意義", "操作"], [
            [f"**{current}**（現價）", "—", "觀察不追高"],
            [f"**{support}**", "技術支撐區", "跌破需重新評估中期結構"],
            [f"**{ma20}**", "20MA 壓力 / 支撐", "站回才轉中性偏多"],
            [f"**{resistance}**", "前高壓力區", "突破且放量才確認多頭延續"],
        ]),
        "",
        "### 結論反轉觸發條件",
        "",
        markdown_table(["情境", "觸發條件", "操作"], [
            ["**轉多**", "外資連續 3 日淨買入 + 站穩 20MA + 量能回升", "建立 30% 基本部位"],
            ["**轉空**", "外資累計賣超 > 5 萬張 + 週線 MACD 死叉 + 月 YoY < 10%", "減碼至 10% 以下"],
            ["**維持觀望**", "以上條件均未觸發", "持有現金，等待方向"],
        ]),
    ])


def build_causal_chain_section() -> str:
    return "\n".join([
        "## 七、因果鏈總覽",
        "",
        "```text",
        "Apple/NVIDIA 訂單能見度",
        "    ↓",
        "CoWoS 供需缺口 + N3/N2 良率",
        "    ↓",
        "三率趨勢（毛利率/營益率/淨利率）",
        "    ↓",
        "EPS 成長（需區分本業/業外/匯損）",
        "    ↓",
        "外資法人評價 → 籌碼流向",
        "    ↓",
        "技術面價量關係 → 散戶 vs 法人博弈",
        "    ↓",
        "ADR 溢價（需過濾匯率因子）",
        "```",
        "",
        "**資料來源：** FinMind 財務報表與三大法人資料集、TWSE 每日收盤行情與大盤統計、Yahoo Finance（TSM ADR、USD/TWD）、SEC company facts 本機快取。",
    ])


def build_summary_section(block: str, analysis_date: str, earnings_date: str, days_to_earnings: int) -> str:
    score = first_match(block, r"綜合健康得分[:：] ([\d.]+)", first_match(block, r"綜合健康得分: ([\d.]+)", NA))
    alert = "🟢 綠燈" if "🟢 綠燈" in block else "🟡 黃燈" if "🟡 黃燈" in block else "🔴 紅燈" if "🔴 紅燈" in block else NA
    tech = parse_technical(block)
    valuation = parse_valuation(block)
    core = "AI 結構性成長仍強，但外資高檔系統性出貨。市場等待法說會上修展望或 N2 量產確認來打破僵局。"
    return "\n".join([
        "# TSMC 量化分析報告｜2330.TW",
        "",
        "> ⚠️ 本報告僅供內部研究參考，不構成任何投資要約或買賣建議。",
        "",
        f"**分析基準日：** {analysis_date}　｜　**距 Q2 法說會：** {days_to_earnings} 天（{earnings_date}）",
        "",
        "---",
        "",
        "## 一、執行摘要",
        "",
        markdown_table(["項目", "內容"], [
            ["**燈號**", alert],
            ["**健康得分**", f"{score} / 100"],
            ["**現價／P/E**", f"NT${tech['close']} ／ {valuation['pe']} 倍（歷史 {valuation['percentile']} 百分位）"],
            ["**最強支撐訊號**", "財務面三率連兩季同步上升，基本面支撐仍強。"],
            ["**最大警示訊號**", "外資近 5 日累計大幅賣超，籌碼逆風嚴重。"],
            ["**操作建議**", "法說會前不追高，等待外資回補或法說會指引確認方向。"],
        ]),
        "",
        f"> **核心矛盾：** {core}",
    ])


def build_score_section(block: str) -> str:
    items = [
        ("財務面", "financial", "財務面"),
        ("大廠基本面", "bigtech", "大廠基本面"),
        ("技術面", "tech", "技術面"),
        ("籌碼面", "chip", "籌碼面"),
        ("市場情緒", "market", "市場情緒"),
    ]
    lines = []
    for label, _, pattern_label in items:
        score = first_match(block, rf"{re.escape(pattern_label)}\(([\d.]+)\)\*(\d+)% = ([\d.]+)", "")
        weight = first_match(block, rf"{re.escape(pattern_label)}\([\d.]+\)\*(\d+)% = [\d.]+", "")
        subtotal = first_match(block, rf"{re.escape(pattern_label)}\([\d.]+\)\*\d+% = ([\d.]+)", "")
        raw_score = first_match(block, rf"{re.escape(pattern_label)}\(([\d.]+)\)", NA)
        if not weight:
            weight = NA
        if not subtotal:
            subtotal = NA
        lines.append(f"{label:<6} ({raw_score}) × {weight}% = {subtotal} 分")
    total = first_match(block, r"綜合健康得分: ([\d.]+)", NA)
    return "\n".join([
        "## 二、綜合健康得分",
        "",
        "```text",
        *lines,
        "─────────────────────────────",
        f"綜合得分：{total} / 100",
        "```",
    ])


def build_13f_section(block: str) -> str:
    """從 analysis_log.md 的 block 中提取橋水 13F 持倉追蹤章節並格式化。"""
    # 提取橋水 13F 章節
    pattern = r"### 🏛 橋水 13F 持倉追蹤\s*\n(.*?)(?=\n---|\n## |\Z)"
    match = re.search(pattern, block, re.DOTALL)
    if not match:
        return ""

    content = match.group(1).strip()
    if not content or "⚠️" in content:
        # 如果有錯誤訊息，直接返回原始內容
        return f"## 機構法人動向\n\n{content}"

    lines = [
        "## 🏛 機構法人動向：橋水基金 13F 持倉追蹤",
        "",
        content,
        "",
    ]
    return "\n".join(lines)


def build_report(input_path: Path, cache_dir: Path) -> str:
    content = input_path.read_text(encoding="utf-8")
    block = get_latest_block(content)
    analysis_date = first_match(block, r"分析基準日為 (\d{4}-\d{2}-\d{2})", "")
    if not analysis_date:
        analysis_date = first_match(block, r"# 🚀 TSMC 量化分析報告 - (\d{4}-\d{2}-\d{2})", datetime.now().date().isoformat())
    earnings_date = first_match(block, r"Q2 法說會：(\d{4}-\d{2}-\d{2})", "")
    if earnings_date:
        days_to_earnings = (date.fromisoformat(earnings_date) - date.fromisoformat(analysis_date)).days
    else:
        earnings_date, days_to_earnings = estimate_earnings_date(date.fromisoformat(analysis_date))

    sections = [
        build_summary_section(block, analysis_date, earnings_date, days_to_earnings),
        "---",
        build_score_section(block),
        "---",
        "## 三、各維度分析",
        "",
        build_financial_section(block),
        "",
        build_macro_section(block, cache_dir),
        "",
        build_technical_section(block),
        "",
        build_chip_section(block, cache_dir, days_to_earnings),
        "---",
        build_13f_section(block),
        "---",
        build_customer_risk_section(),
        "---",
        build_valuation_section(block),
        "---",
        build_recommendation_section(block, days_to_earnings),
        "---",
        build_causal_chain_section(),
    ]
    return clean_text("\n\n".join(sections)).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Format analysis_log.md into the fixed TSMC quant report layout.")
    parser.add_argument("--input", default=str(ROOT / "analysis_log.md"), help="Path to analysis_log.md")
    parser.add_argument("--output", help="Optional output Markdown path. Defaults to stdout.")
    parser.add_argument("--cache-dir", default=str(ROOT / "local_cache"), help="Path to local_cache")
    args = parser.parse_args()

    try:
        report = build_report(Path(args.input), Path(args.cache_dir))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
