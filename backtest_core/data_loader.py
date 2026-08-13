"""
Data Loader Module
==================
統一的快取資料載入器，避免各回測腳本重複讀取相同的 JSON 檔案。
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class CachedDataPaths:
    """快取檔案路徑設定"""
    inst_rows: str = "local_cache/hcd_finmind_inst_rows_2330_2023-04-06_2026-07-19.json"
    shareholding: str = "local_cache/hcd_finmind_shareholding_2330_2023-04-06_2026-07-19.json"
    ohlc: str = "local_cache/hcd_yahoo_ohlcv_2330.TW_1672531200_1784419200.json"
    wide_fin: str = "local_cache/finmind_TaiwanStockFinancialStatements_2330_wide_20260719_213936_266291.json"


class BacktestDataLoader:
    """
    回測資料載入器

    使用方式：
        loader = BacktestDataLoader()
        data = loader.load_all()

        # 或指定自訂路徑
        loader = BacktestDataLoader(CachedDataPaths(
            inst_rows="custom/path/inst_rows.json",
            ...
        ))
    """

    def __init__(self, paths: Optional[CachedDataPaths] = None):
        self.paths = paths or CachedDataPaths()
        self._cache: Dict[str, Any] = {}

    def _load_json(self, path: str) -> List[Dict]:
        """載入 JSON 檔案並回傳 data 欄位"""
        full_path = Path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"快取檔案不存在: {full_path}")
        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)["data"]

    def load_institutional_rows(self) -> List[Dict]:
        """載入三大法人買賣超資料"""
        if "inst_rows" not in self._cache:
            self._cache["inst_rows"] = self._load_json(self.paths.inst_rows)
        return self._cache["inst_rows"]

    def load_shareholding(self) -> List[Dict]:
        """載入外資持股資料"""
        if "shareholding" not in self._cache:
            self._cache["shareholding"] = self._load_json(self.paths.shareholding)
        return self._cache["shareholding"]

    def load_ohlc(self) -> List[Dict]:
        """載入 OHLCV 價格資料"""
        if "ohlc" not in self._cache:
            self._cache["ohlc"] = self._load_json(self.paths.ohlc)
        return self._cache["ohlc"]

    def load_wide_financial(self) -> List[Dict]:
        """載入寬表格式財報資料"""
        if "wide_fin" not in self._cache:
            self._cache["wide_fin"] = self._load_json(self.paths.wide_fin)
        return self._cache["wide_fin"]

    def load_all(self) -> Dict[str, List[Dict]]:
        """一次性載入所有資料"""
        return {
            "inst_rows": self.load_institutional_rows(),
            "shareholding": self.load_shareholding(),
            "ohlc": self.load_ohlc(),
            "wide_fin": self.load_wide_financial(),
        }

    def clear_cache(self):
        """清除內部快取"""
        self._cache.clear()


def load_all_cached_data(paths: Optional[CachedDataPaths] = None) -> Dict[str, List[Dict]]:
    """
    便利函數：載入所有快取資料

    Args:
        paths: 可選的自訂路徑設定

    Returns:
        包含所有資料的字典
    """
    loader = BacktestDataLoader(paths)
    return loader.load_all()