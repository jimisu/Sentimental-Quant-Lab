"""
TSMC Quant Lab — 統一快取層

依資料類型定義 TTL 策略，避免每日執行時重複抓取變化頻率低的資料
（宏觀、財務），僅每日變化資料（技術、籌碼）每次重新抓取。
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional


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
               directory: str = "local_cache") -> Optional[Dict]:
    """
    讀取快取。若 max_age_hours > 0 則檢查新鮮度，過期回傳 None。
    max_age_hours = 0 表示永遠回傳最新快取（不檢查新鮮度）。
    """
    safe_key = _safe_key(cache_key)
    prefix = f"{safe_key}_"
    files = _list_cache_files(directory, prefix)
    if not files:
        return None

    latest_path = os.path.join(directory, files[-1])
    try:
        with open(latest_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  [data_cache] 讀取快取失敗: {latest_path} ({exc})", file=sys.stderr)
        return None

    # 檢查新鮮度
    if max_age_hours > 0:
        cached_at = payload.get("cached_at")
        if not cached_at:
            return None
        try:
            cached_dt = datetime.fromisoformat(cached_at)
        except ValueError:
            return None
        age = datetime.now() - cached_dt
        if age > timedelta(hours=max_age_hours):
            return None
        print(f"  -> 使用快取: {cache_key} (cached_at={cached_at})")

    return payload.get("data")


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
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 環形清理：只保留最新 keep_count 份
    prefix = f"{safe_key}_"
    files = _list_cache_files(directory, prefix)
    for old_file in files[:-keep_count]:
        try:
            os.remove(os.path.join(directory, old_file))
        except OSError as exc:
            print(f"  [data_cache] 刪除舊快取失敗: {old_file} ({exc})", file=sys.stderr)


def fetch_with_cache(policy_name: str, cache_key: str, fetch_fn: Callable,
                     directory: str = "local_cache"):
    """
    統一的「先檢查快取，過期才抓取」入口。

    Args:
        policy_name: DATA_POLICIES 中的 key（如 "monthly_revenue"）
        cache_key: 快取檔案的 key
        fetch_fn: 無參數函式，回傳要快取的資料
        directory: 快取目錄

    Returns:
        資料（來自快取或新抓取）
    """
    policy = DATA_POLICIES.get(policy_name)
    if policy is None:
        raise ValueError(f"未知的 policy: {policy_name}，可用: {list(DATA_POLICIES.keys())}")

    # TTL = 0 表示永遠抓取，跳過快取讀取
    if policy.ttl_hours > 0:
        cached = read_cache(cache_key, max_age_hours=policy.ttl_hours,
                            directory=directory)
        if cached is not None:
            return cached

    # 抓取新資料
    data = fetch_fn()

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
