"""
TSMC Quant Lab — 統一快取層

依資料類型定義 TTL 策略，避免每日執行時重複抓取變化頻率低的資料
（宏觀、財務），僅每日變化資料（技術、籌碼）每次重新抓取。
"""

import dataclasses
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional


class DataclassEncoder(json.JSONEncoder):
    """支援 dataclass 的 JSON 編碼器"""
    def default(self, obj):
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        return super().default(obj)


# ──────────────────────────────────────────────────────────────────────
# 快取策略定義
# ──────────────────────────────────────────────────────────────────────

@dataclass
class CachePolicy:
    """單一資料類型的快取策略"""
    ttl_hours: float = 0.0     # 0 = 永遠重新抓取
    keep_count: int = 3        # 同一 key 保留最新幾份（環形快取）
    directory: str = "local_cache"


# 依資料變化頻率定義 TTL
DATA_POLICIES: Dict[str, CachePolicy] = {
    # 每日變化 → 永遠抓取
    "twse_daily":        CachePolicy(ttl_hours=0,    keep_count=3),
    "institutional":     CachePolicy(ttl_hours=0,    keep_count=3),
    # 月營收每月公布 → 24 小時快取
    "monthly_revenue":   CachePolicy(ttl_hours=24,   keep_count=3),
    # 季報每季公布 → 7 天快取
    "quarterly_margins": CachePolicy(ttl_hours=168,  keep_count=3),
    # ADR 價格盤中變化但不需要每分鐘重抓 → 1 小時快取
    "macro_adr":         CachePolicy(ttl_hours=1,    keep_count=3),
    # SEC 財報每季更新 → 7 天快取
    "macro_capex":       CachePolicy(ttl_hours=168,  keep_count=3),
    # NVDA 營收（季報級別）→ 7 天快取
    "nvda_revenue":      CachePolicy(ttl_hours=168,  keep_count=3),
    # SEC 13F 每季更新（季末後 45 天內提交）→ 90 天快取
    "sec_13f":           CachePolicy(ttl_hours=2160, keep_count=3),
    # US CPI/PPI 月度數據 → 24 小時快取
    "macro_inflation":   CachePolicy(ttl_hours=24,   keep_count=3),
    # 領先指標歷史追蹤 → 永久保留（不檢查新鮮度），每次執行更新
    "leading_indicator_history": CachePolicy(ttl_hours=0, keep_count=10),
}


# ──────────────────────────────────────────────────────────────────────
# 內部工具函式
# ──────────────────────────────────────────────────────────────────────

def _safe_key(key: str) -> str:
    """建立檔名安全的 key"""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key)).strip("_")


def _ensure_dir(directory: str) -> None:
    os.makedirs(directory, exist_ok=True)


def _list_cache_files(directory: str, prefix: str):
    """列出符合 prefix 的快取檔案，依檔名排序（即時間排序）"""
    if not os.path.exists(directory):
        return []
    return sorted(
        f for f in os.listdir(directory)
        if f.startswith(prefix) and f.endswith(".json")
    )


# ──────────────────────────────────────────────────────────────────────
# 公開 API
# ──────────────────────────────────────────────────────────────────────

def read_cache(cache_key: str, max_age_hours: float,
               directory: str = "local_cache",
               validate: Optional[Callable[[Any], bool]] = None) -> Optional[Any]:
    """
    讀取快取。若 max_age_hours > 0 則檢查新鮮度，過期回傳 None。
    max_age_hours = 0 表示永遠回傳最新快取（不檢查新鮮度）。

    validate: 可選完整性校驗回呼。若提供，由新到舊逐份檢查快取，
    跳過未通過校驗（例如半截 JSON / 缺 tag）的檔案，回傳第一份
    同時滿足新鮮度與校驗的資料。全部不符則回傳 None。
    """
    safe_key = _safe_key(cache_key)
    prefix = f"{safe_key}_"
    files = _list_cache_files(directory, prefix)
    if not files:
        return None

    # 由新到舊，回傳第一份通過新鮮度 + 完整性校驗的快取
    for fname in reversed(files):
        path = os.path.join(directory, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  [data_cache] 讀取快取失敗: {path} ({exc})", file=sys.stderr)
            continue

        # 檢查新鮮度
        if max_age_hours > 0:
            cached_at = payload.get("cached_at")
            if not cached_at:
                continue
            try:
                cached_dt = datetime.fromisoformat(cached_at)
            except ValueError:
                continue
            # 處理帶 timezone 的 timestamp：統一轉為 naive UTC
            if cached_dt.tzinfo is not None:
                from datetime import timezone as _tz
                cached_dt = cached_dt.astimezone(_tz.utc).replace(tzinfo=None)
            age = datetime.now() - cached_dt
            if age > timedelta(hours=max_age_hours):
                continue
            print(f"  -> 使用快取: {cache_key} (cached_at={cached_at})")

        data = payload.get("data")
        if validate is not None and not validate(data):
            continue
        return data

    return None


def _read_any_valid(cache_key: str, directory: str,
                   validate: Callable[[Any], bool]) -> Optional[Any]:
    """
    回退用：忽略新鮮度，由新到舊回傳第一份通過 validate 的快取。
    僅在「即時抓取結果未通過完整性校驗」時呼叫，避免長時間 SEC 抖動
    期間直接回報失敗，改回退至最後一份已知有效（可能過期）的快取。
    """
    safe_key = _safe_key(cache_key)
    prefix = f"{safe_key}_"
    files = _list_cache_files(directory, prefix)
    for fname in reversed(files):
        path = os.path.join(directory, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        data = payload.get("data")
        if validate(data):
            return data
    return None


def write_cache(cache_key: str, data, directory: str = "local_cache",
               keep_count: int = 3, metadata: Optional[Dict] = None) -> None:
    """
    寫入環形快取。同一 key 只保留最新 keep_count 份。
    """
    _ensure_dir(directory)
    safe_key = _safe_key(cache_key)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filepath = os.path.join(directory, f"{safe_key}_{timestamp}.json")

    payload = {
        "cached_at": datetime.now().isoformat(timespec="seconds"),
        "data": data,
    }
    if metadata:
        payload["metadata"] = metadata

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, cls=DataclassEncoder)

    # 環形清理：只保留最新 keep_count 份
    prefix = f"{safe_key}_"
    files = _list_cache_files(directory, prefix)
    for old_file in files[:-keep_count]:
        try:
            os.remove(os.path.join(directory, old_file))
        except OSError as exc:
            print(f"  [data_cache] 刪除舊快取失敗: {old_file} ({exc})", file=sys.stderr)


def fetch_with_cache(policy_name: str, cache_key: str, fetch_fn: Callable,
                     directory: str = "local_cache",
                     validate: Optional[Callable[[Any], bool]] = None):
    """
    統一的「先檢查快取，過期才抓取」入口。

    Args:
        policy_name: DATA_POLICIES 中的 key（如 "monthly_revenue"）
        cache_key: 快取檔案的 key
        fetch_fn: 無參數函式，回傳要快取的資料
        directory: 快取目錄
        validate: 可選完整性校驗回呼。若提供，快取讀取會跳過未通過者；
            即時抓取結果若未通過則「不寫入快取」（避免半截 JSON 污染 TTL），
            並嘗試回退至既有有效快取，否則拋出 RuntimeError。

    Returns:
        資料（來自快取或新抓取）
    """
    policy = DATA_POLICIES.get(policy_name)
    if policy is None:
        raise ValueError(f"未知的 policy: {policy_name}，可用: {list(DATA_POLICIES.keys())}")

    # TTL = 0 表示永遠抓取，跳過快取讀取
    if policy.ttl_hours > 0:
        cached = read_cache(cache_key, max_age_hours=policy.ttl_hours,
                            directory=directory, validate=validate)
        if cached is not None:
            return cached

    # 抓取新資料
    data = fetch_fn()

    # 完整性校驗：不通過就不寫入快取，改回退既有有效快取或拋錯，
    # 避免一次 transient 把整個 TTL 毒成半截資料。
    if validate is not None and not validate(data):
        fallback = _read_any_valid(cache_key, directory, validate)
        if fallback is not None:
            print(f"  [data_cache] 抓取結果未通過完整性校驗，回退至既有有效快取: {cache_key}",
                  file=sys.stderr)
            return fallback
        raise RuntimeError(f"抓取結果未通過完整性校驗，且無可用舊快取: {cache_key}")

    # 寫入快取（TTL = 0 的資料也寫入，作為 API 失敗時的 fallback）
    write_cache(cache_key, data, directory=directory,
                keep_count=policy.keep_count)
    return data


def get_policy_ttl(policy_name: str) -> float:
    """取得指定 policy 的 TTL（小時）"""
    policy = DATA_POLICIES.get(policy_name)
    if policy is None:
        raise ValueError(f"未知的 policy: {policy_name}")
    return policy.ttl_hours
