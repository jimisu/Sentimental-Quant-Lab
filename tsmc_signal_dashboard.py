#!/usr/bin/env python3
"""
TSMC 信號儀表板
抓取台積電 (2330.TW) 最新 12 個月的月營收 YoY 與最近 4 季的毛利率、營業利益率，
並使用 rich 庫輸出彩色儀表板。
新增：從 TWSE 列出近 10 個交易日成交金額，並偵測個股與大盤交易量連三降。
"""

import datetime as dt
import os
import sys
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from rich import box
from rich.console import Console
from rich.table import Table

API_URL = "https://api.finmindtrade.com/api/v4/data"
TWSE_AFTER_TRADING_URL = "https://www.twse.com.tw/rwd/zh/afterTrading"

# 日期範圍
TODAY = dt.date.today()
TWO_YEARS_AGO = TODAY - dt.timedelta(days=730)  # 約兩年，以便計算 YoY


def fetch_finmind_dataset(
    dataset: str,
    data_id: str,
    start_date: str,
    end_date: str,
    token: Optional[str] = None,
) -> List[Dict]:
    """
    從 FinMind API 取得資料。
    """
    params = {
        "dataset": dataset,
        "data_id": data_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if token:
        params["token"] = token

    print(f"Fetching {dataset} for {data_id} from {start_date} to {end_date}...")
    resp = requests.get(API_URL, params=params, timeout=30)
    if resp.status_code != 200:
        print(
            f"Error: API request failed with status {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)

    data = resp.json()
    if data.get("status") != 200:
        print(
            f"Error: FinMind returned error status: {data.get('msg')}",
            file=sys.stderr,
        )
        sys.exit(1)

    records = data.get("data", [])
    print(f"  -> Received {len(records)} records.")
    return records


def get_monthly_revenue_yoy(token: Optional[str] = None) -> List[Dict]:
    """
    取得最近 12 個月的月營收年增率（YoY）。
    回傳 list of dict，每筆包含 date (YYYY-MM) 和 revenue_yoy (百分比)。
    """
    # 取得過去 24 個月的月營收，以便計算 YoY（當前月與去年同月比較）
    start_date = TWO_YEARS_AGO.isoformat()
    end_date = TODAY.isoformat()
    records = fetch_finmind_dataset(
        dataset="TaiwanStockMonthRevenue",
        data_id="2330",
        start_date=start_date,
        end_date=end_date,
        token=token,
    )
    # 將 records 轉換為以日期為 key 的字典，值為 revenue
    revenue_by_date = {}
    for r in records:
        date_str = r.get("date")  # 格式: YYYY-MM-DD
        if not date_str:
            continue
        # 只取年月部分 (YYYY-MM)
        year_month = date_str[:7]  # YYYY-MM
        try:
            revenue = float(r.get("revenue", 0))
        except (ValueError, TypeError):
            continue
        revenue_by_date[year_month] = revenue

    # 產生最近 12 個月的年月列表（從當前月往前推 11 個月，共 12 個月）
    months_yoy = []
    year = TODAY.year
    month = TODAY.month
    for i in range(12):
        # 計算當前月往前 i 個月
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        months_yoy.append(f"{y:04d}-{m:02d}")
    months_yoy = list(reversed(months_yoy))  # 從遠到近排序

    result = []
    for ym in months_yoy:
        if ym not in revenue_by_date:
            # 若當月資料缺失，則跳過（或設為 None）
            continue
        # 計算去年同月的年月
        prev_year = int(ym[:4]) - 1
        prev_ym = f"{prev_year:04d}-{ym[5:7]}"
        if prev_ym not in revenue_by_date:
            # 若去年同月資料缺失，則無法計算 YoY
            continue
        cur_rev = revenue_by_date[ym]
        prev_rev = revenue_by_date[prev_ym]
        if prev_rev == 0:
            yoy = None
        else:
            yoy = (cur_rev - prev_rev) / prev_rev * 100.0
        result.append({"date": ym, "revenue_yoy": yoy})
    return result


def get_quarterly_margins(token: Optional[str] = None) -> Dict[Tuple[int, int], Dict]:
    """
    取得最近 4 季的毛利率與營業利益率，並計算季度環比變化。
    回傳 dict，key 為 (year, quarter)，value 為包含以下欄位的 dict:
        - gross_margin: 毛利率 (%)
        - operating_margin: 營業利益率 (%)
        - gross_drop: 與上一季的毛利率變化百分點 (上一季 - 當季)，正數代表下滑
        - op_drop: 與上一季的營業利益率變化百分點 (上一季 - 當季)，正數代表下滑
    對於第一季（最早的一季），drop 為 None。
    """
    # 取得過去一年的財務報表（季資料）
    start_date = (TODAY - dt.timedelta(days=365)).isoformat()
    end_date = TODAY.isoformat()
    records = fetch_finmind_dataset(
        dataset="TaiwanStockFinancialStatements",
        data_id="2330",
        start_date=start_date,
        end_date=end_date,
        token=token,
    )
    # 我們需要每季的 Revenue, GrossProfit, OperatingIncome
    # 將同一季度的不同 type 值匯總
    quarterly_data = {}  # key: (year, quarter) -> dict of values
    for r in records:
        date_str = r.get("date")  # YYYY-MM-DD
        if not date_str:
            continue
        # 從日期取得年份和季度
        try:
            year = int(date_str[:4])
            month = int(date_str[5:7])
            quarter = (month - 1) // 3 + 1
        except (ValueError, TypeError):
            continue
        key = (year, quarter)
        if key not in quarterly_data:
            quarterly_data[key] = {}
        # 讀取數值
        try:
            value = float(r.get("value", 0))
        except (ValueError, TypeError):
            continue
        quarterly_data[key][r.get("type")] = value

    # 計算每季的毛利率和營業利益率，並計算與上一季的變化
    result = {}
    # 先排序季度（從遠到近）
    sorted_quarters = sorted(quarterly_data.keys())
    for idx, (year, quarter) in enumerate(sorted_quarters):
        values = quarterly_data[(year, quarter)]
        revenue = values.get("Revenue")
        gross_profit = values.get("GrossProfit")
        operating_income = values.get("OperatingIncome")
        if revenue is None or revenue == 0:
            continue
        gross_margin = (gross_profit / revenue * 100) if gross_profit is not None else None
        operating_margin = (operating_income / revenue * 100) if operating_income is not None else None
        if gross_margin is None or operating_margin is None:
            # 若任一欄位缺失，則跳過該季
            continue
        # 計算與上一季的變化（上一季 - 當季）
        gross_drop = None
        op_drop = None
        if idx > 0:
            prev_year, prev_quarter = sorted_quarters[idx - 1]
            prev_values = quarterly_data[(prev_year, prev_quarter)]
            prev_revenue = prev_values.get("Revenue")
            prev_gross_profit = prev_values.get("GrossProfit")
            prev_operating_income = prev_values.get("OperatingIncome")
            if prev_revenue is not None and prev_revenue != 0:
                if prev_gross_profit is not None:
                    prev_gross_margin = (prev_gross_profit / prev_revenue * 100)
                    gross_drop = prev_gross_margin - gross_margin
                if prev_operating_income is not None:
                    prev_op_margin = (prev_operating_income / prev_revenue * 100)
                    op_drop = prev_op_margin - operating_margin
        result[(year, quarter)] = {
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "gross_drop": gross_drop,
            "op_drop": op_drop,
        }
    return result


def parse_twse_int(value) -> Optional[int]:
    """
    將 TWSE 回傳的數字字串轉成 int，例如 '1,234,567'。
    """
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "X", "除權息"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_twse_date(value) -> Optional[str]:
    """
    將 TWSE 民國日期（例如 115/05/15）轉成 YYYY-MM-DD。
    """
    if value is None:
        return None
    parts = str(value).strip().split("/")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[0])
        if year < 1911:
            year += 1911
        month = int(parts[1])
        day = int(parts[2])
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def get_recent_month_starts(months: int = 3) -> List[dt.date]:
    """
    回傳從本月往前推的月份起始日。
    """
    month_starts = []
    year = TODAY.year
    month = TODAY.month
    for _ in range(months):
        month_starts.append(dt.date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return month_starts


def fetch_twse_report(report: str, params: Dict[str, str]) -> List[List[str]]:
    """
    從 TWSE afterTrading API 取得報表資料列。
    """
    url = f"{TWSE_AFTER_TRADING_URL}/{report}"
    request_params = {"response": "json", **params}
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, params=request_params, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(
            f"Error: TWSE request failed with status {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        return []

    payload = resp.json()
    if payload.get("stat") not in {"OK", "很抱歉，沒有符合條件的資料!"}:
        print(f"Error: TWSE returned status: {payload.get('stat')}", file=sys.stderr)
        return []
    return payload.get("data", [])


def get_twse_stock_trading_values(stock_no: str, months: int = 3) -> pd.DataFrame:
    """
    從 TWSE STOCK_DAY 抓取個股各日成交金額。
    """
    records = []
    for month_start in get_recent_month_starts(months):
        rows = fetch_twse_report(
            "STOCK_DAY",
            {"date": month_start.strftime("%Y%m%d"), "stockNo": stock_no},
        )
        for row in rows:
            if len(row) < 3:
                continue
            date = parse_twse_date(row[0])
            trading_value = parse_twse_int(row[2])
            if date and trading_value is not None:
                records.append({"日期": date, "台積電成交金額": trading_value})

    if not records:
        return pd.DataFrame(columns=["日期", "台積電成交金額"])
    return pd.DataFrame(records).drop_duplicates(subset=["日期"]).sort_values("日期")


def get_twse_market_trading_values(months: int = 3) -> pd.DataFrame:
    """
    從 TWSE FMTQIK 抓取大盤各日成交金額。
    """
    records = []
    for month_start in get_recent_month_starts(months):
        rows = fetch_twse_report("FMTQIK", {"date": month_start.strftime("%Y%m%d")})
        for row in rows:
            if len(row) < 3:
                continue
            date = parse_twse_date(row[0])
            trading_value = parse_twse_int(row[2])
            if date and trading_value is not None:
                records.append({"日期": date, "大盤成交金額": trading_value})

    if not records:
        return pd.DataFrame(columns=["日期", "大盤成交金額"])
    return pd.DataFrame(records).drop_duplicates(subset=["日期"]).sort_values("日期")


def get_recent_trading_value_history(days: int = 10) -> pd.DataFrame:
    """
    從 TWSE 抓取最近 N 個交易日的成交金額。
    回傳 DataFrame，日期由舊到新，欄位包含日期、台積電成交金額、大盤成交金額。
    """
    stock_df = get_twse_stock_trading_values("2330")
    market_df = get_twse_market_trading_values()

    if stock_df.empty and market_df.empty:
        return pd.DataFrame(columns=["日期", "台積電成交金額", "大盤成交金額"])

    value_df = pd.merge(stock_df, market_df, on="日期", how="outer")
    value_df = value_df.sort_values("日期").tail(days).reset_index(drop=True)

    return value_df


def has_three_consecutive_decline(values: List[float]) -> bool:
    """
    檢查是否存在連續三天每日成交金額均低於前一天。
    values 為 list，最新在前：[V0, V1, V2, ...]
    條件：V0 < V1 < V2 （即三天遞減）
    """
    if len(values) < 3:
        return False
    for i in range(len(values) - 2):
        if values[i] < values[i + 1] < values[i + 2]:
            return True
    return False


def build_dataframe(
    revenue_yoy: List[Dict], quarterly_margins: Dict[Tuple[int, int], Dict]
) -> pd.DataFrame:
    """
    建立 DataFrame，每列為一個月（最近12個月）。
    包含月份、營收 YoY%、該月所在季度的毛利率%、該月所在季度的營業利益率%、
    以及該季度的毛利率季度下滑值、營業利益率季度下滑值（用於顏色判斷）。
    """
    # 月份列表
    months = [item["date"] for item in revenue_yoy]
    revenue_vals = [item["revenue_yoy"] for item in revenue_yoy]

    # 對每個月，找出所在季度並取得對應的值
    gross_margin_list = []
    operating_margin_list = []
    gross_drop_list = []
    op_drop_list = []
    for ym in months:
        year = int(ym[:4])
        month = int(ym[5:7])
        quarter = (month - 1) // 3 + 1
        q_key = (year, quarter)
        if q_key in quarterly_margins:
            qm = quarterly_margins[q_key]
            gross_margin_list.append(qm["gross_margin"])
            operating_margin_list.append(qm["operating_margin"])
            gross_drop_list.append(qm["gross_drop"])
            op_drop_list.append(qm["op_drop"])
        else:
            gross_margin_list.append(None)
            operating_margin_list.append(None)
            gross_drop_list.append(None)
            op_drop_list.append(None)

    # 建立 DataFrame
    df = pd.DataFrame(
        {
            "月份": months,
            "營收 YoY (%)": revenue_vals,
            "毛利率 (%)": gross_margin_list,
            "營業利益率 (%)": operating_margin_list,
            "_gross_drop": gross_drop_list,
            "_op_drop": op_drop_list,
        }
    )
    return df


def apply_color_logic(df: pd.DataFrame) -> pd.DataFrame:
    """
    根據規則加入顏色欄位（供 rich 使用）。
    回傳包含原始值和色彩標記的 DataFrame。
    """
    # 複製以免修改原始
    styled = df.copy()

    # 營收 YoY 色彩：低於 20% 標示黃色，連續兩月低於 20% 標示紅色
    rev_colors = []
    for i, val in enumerate(styled["營收 YoY (%)"]):
        if val is None:
            rev_colors.append("")
            continue
        if val < 20:
            # 檢查是否連續兩月低於 20%
            if i > 0 and styled["營收 YoY (%)"].iloc[i - 1] < 20:
                rev_colors.append("red")
            else:
                rev_colors.append("yellow")
        else:
            rev_colors.append("")
    styled["營收 YoY 色彩"] = rev_colors

    # 毛利率 與 營業利益率 色彩：
    # 根據季度下滑 >2% 標示黃色；
    # 如果毛利率下滑>2% 且 營業利益率下滑>2% 則標示紅色。
    margin_colors = []  # 這個顏色將同時適用於毛利率和營業利益率兩欄
    for gd, od in zip(styled["_gross_drop"], styled["_op_drop"]):
        # 如果任一 drop 為 None，則無法判斷，設為無顏色
        if gd is None or od is None:
            margin_colors.append("")
            continue
        if gd > 2 and od > 2:
            margin_colors.append("red")
        elif gd > 2 or od > 2:
            margin_colors.append("yellow")
        else:
            margin_colors.append("")
    styled["毛利率 色彩"] = margin_colors
    styled["營業利益率 色彩"] = margin_colors

    # 移除暫存欄位
    styled = styled.drop(columns=["_gross_drop", "_op_drop"])
    return styled


def print_dashboard(
    styled_df: pd.DataFrame,
    value_df: pd.DataFrame,
    market_sentiment_red: bool,
):
    """
    使用 rich 輸出彩色表格、成交金額表格，並在需要時顯示市場情緒指標紅色警示。
    """
    console = Console()
    table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE_HEAVY)
    table.add_column("月份", style="dim", width=12)
    table.add_column("營收 YoY (%)", justify="right")
    table.add_column("毛利率 (%)", justify="right")
    table.add_column("營業利益率 (%)", justify="right")

    def format_number(value) -> str:
        return "-" if pd.isna(value) else f"{value:.2f}"

    for _, row in styled_df.iterrows():
        # 營收 YoY 顏色
        rev_text = format_number(row["營收 YoY (%)"])
        if row["營收 YoY 色彩"] == "red":
            rev_text = f"[red]{rev_text}[/red]"
        elif row["營收 YoY 色彩"] == "yellow":
            rev_text = f"[yellow]{rev_text}[/yellow]"

        # 毛利率 顏色
        gross_text = format_number(row["毛利率 (%)"])
        if row["毛利率 色彩"] == "red":
            gross_text = f"[red]{gross_text}[/red]"
        elif row["毛利率 色彩"] == "yellow":
            gross_text = f"[yellow]{gross_text}[/yellow]"

        # 營業利益率 顏色
        op_text = format_number(row["營業利益率 (%)"])
        if row["營業利益率 色彩"] == "red":
            op_text = f"[red]{op_text}[/red]"
        elif row["營業利益率 色彩"] == "yellow":
            op_text = f"[yellow]{op_text}[/yellow]"

        table.add_row(
            str(row["月份"]),
            rev_text,
            gross_text,
            op_text,
        )

    console.print(table)

    value_table = Table(
        title="近 10 個交易日成交金額",
        show_header=True,
        header_style="bold cyan",
        box=box.SIMPLE_HEAVY,
    )
    value_table.add_column("日期", style="dim", width=12)
    value_table.add_column("台積電成交金額", justify="right")
    value_table.add_column("大盤成交金額", justify="right")

    for _, row in value_df.iterrows():
        tsmc_value = row.get("台積電成交金額")
        market_value = row.get("大盤成交金額")
        tsmc_text = "-" if pd.isna(tsmc_value) else f"{int(tsmc_value):,}"
        market_text = "-" if pd.isna(market_value) else f"{int(market_value):,}"
        value_table.add_row(str(row["日期"]), tsmc_text, market_text)

    console.print()
    console.print(value_table)

    # 市場情緒指標：若同時符合條件則顯示紅色警示
    if market_sentiment_red:
        console.print("[red]市場情緒指標：個股與大盤交易量連三降[/red]")


def generate_summary(styled_df: pd.DataFrame, market_sentiment_red: bool) -> str:
    """
    根據表格顏色產生一句總結。
    """
    has_red = (
        (styled_df["營收 YoY 色彩"] == "red").any()
        or (styled_df["毛利率 色彩"] == "red").any()
        or (styled_df["營業利益率 色彩"] == "red").any()
        or market_sentiment_red
    )
    has_yellow = (
        (styled_df["營收 YoY 色彩"] == "yellow").any()
        or (styled_df["毛利率 色彩"] == "yellow").any()
        or (styled_df["營業利益率 色彩"] == "yellow").any()
    )

    if has_red:
        return "目前處於紅燈預警，建議減碼並密切監控。"
    elif has_yellow:
        return "目前處於黃燈預警，建議啟動階梯式觀察，暫不加碼。"
    else:
        return "目前皆為綠燈，可正常觀察並考慮適度加碼。"


def main():
    """
    主程式流程。
    """
    # 可選的 FinMind token，從環境變數讀取
    token = os.getenv("FINMIND_TOKEN")

    # 取得資料
    revenue_yoy = get_monthly_revenue_yoy(token)
    quarterly_margins = get_quarterly_margins(token)
    value_df = get_recent_trading_value_history(days=10)

    if not revenue_yoy:
        print("錯誤：未能取得月營收資料。", file=sys.stderr)
        sys.exit(1)
    if not quarterly_margins:
        print("警告：未能取得季度毛利率/營業利益率資料，將以空白顯示。", file=sys.stderr)

    # 建立 DataFrame
    df = build_dataframe(revenue_yoy, quarterly_margins)

    # 加入顏色邏輯
    styled_df = apply_color_logic(df)

    # 判斷市場情緒指標：個股與大盤交易量連三降
    latest_first_values = value_df.sort_values("日期", ascending=False)
    stock_values = (
        latest_first_values["台積電成交金額"].dropna().tolist()
        if "台積電成交金額" in latest_first_values
        else []
    )
    index_values = (
        latest_first_values["大盤成交金額"].dropna().tolist()
        if "大盤成交金額" in latest_first_values
        else []
    )
    market_sentiment_red = (
        has_three_consecutive_decline(stock_values)
        and has_three_consecutive_decline(index_values)
    )

    # 輸出儀表板
    print_dashboard(styled_df, value_df, market_sentiment_red)

    # 產生並印出總結
    summary = generate_summary(styled_df, market_sentiment_red)
    print("\n" + summary)


if __name__ == "__main__":
    main()
