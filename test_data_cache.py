"""
Sentimental-Quant-Lab — Tests for data_cache.py

Covers: CachePolicy, DATA_POLICIES, _safe_key, read_cache, write_cache,
fetch_with_cache, get_policy_ttl, and ring buffer eviction.

All filesystem I/O uses tempfile.TemporaryDirectory via the temp_cache_dir fixture.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from data_cache import (
    CachePolicy,
    DATA_POLICIES,
    _safe_key,
    _ensure_dir,
    _list_cache_files,
    read_cache,
    write_cache,
    fetch_with_cache,
    get_policy_ttl,
)


# ══════════════════════════════════════════════════════════════
# CachePolicy
# ══════════════════════════════════════════════════════════════

class TestCachePolicy:
    def test_default_ttl_is_zero(self):
        assert CachePolicy().ttl_hours == 0.0

    def test_default_keep_count(self):
        assert CachePolicy().keep_count == 3

    def test_default_directory(self):
        assert CachePolicy().directory == "local_cache"

    def test_custom_values(self):
        p = CachePolicy(ttl_hours=48, keep_count=5, directory="/tmp/test")
        assert p.ttl_hours == 48
        assert p.keep_count == 5
        assert p.directory == "/tmp/test"


# ══════════════════════════════════════════════════════════════
# DATA_POLICIES
# ══════════════════════════════════════════════════════════════

class TestDataPolicies:
    def test_nine_policies_defined(self):
        assert len(DATA_POLICIES) == 9

    def test_all_required_keys_present(self):
        required = {
            "twse_daily", "institutional", "monthly_revenue",
            "quarterly_margins", "macro_adr", "macro_capex",
            "nvda_revenue", "sec_13f", "macro_inflation",
        }
        assert set(DATA_POLICIES.keys()) == required

    def test_twse_daily_ttl_is_zero(self):
        assert DATA_POLICIES["twse_daily"].ttl_hours == 0

    def test_institutional_ttl_is_zero(self):
        assert DATA_POLICIES["institutional"].ttl_hours == 0

    def test_monthly_revenue_ttl(self):
        assert DATA_POLICIES["monthly_revenue"].ttl_hours == 24

    def test_quarterly_margins_ttl(self):
        assert DATA_POLICIES["quarterly_margins"].ttl_hours == 168

    def test_macro_adr_ttl(self):
        assert DATA_POLICIES["macro_adr"].ttl_hours == 1

    def test_macro_capex_ttl(self):
        assert DATA_POLICIES["macro_capex"].ttl_hours == 168

    def test_nvda_revenue_ttl(self):
        assert DATA_POLICIES["nvda_revenue"].ttl_hours == 168

    def test_sec_13f_ttl(self):
        assert DATA_POLICIES["sec_13f"].ttl_hours == 2160

    def test_macro_inflation_ttl(self):
        assert DATA_POLICIES["macro_inflation"].ttl_hours == 24

    def test_all_policies_have_keep_count_3(self):
        for name, policy in DATA_POLICIES.items():
            assert policy.keep_count == 3, f"{name} has keep_count != 3"


# ══════════════════════════════════════════════════════════════
# _safe_key
# ══════════════════════════════════════════════════════════════

class TestSafeKey:
    def test_alphanumeric_unchanged(self):
        assert _safe_key("abc123") == "abc123"

    def test_slashes_replaced(self):
        assert _safe_key("path/to/key") == "path_to_key"

    def test_spaces_replaced(self):
        assert _safe_key("my key") == "my_key"

    def test_special_chars_replaced(self):
        # Consecutive special chars collapse to a single "_", then stripped
        assert _safe_key("key@#$%!") == "key"

    def test_dots_and_dashes_preserved(self):
        assert _safe_key("key-2.0") == "key-2.0"

    def test_leading_trailing_underscores_stripped(self):
        assert _safe_key("__key__") == "key"

    def test_empty_string(self):
        assert _safe_key("") == ""

    def test_unicode_replaced(self):
        result = _safe_key("營收_YoY")
        # Non-ASCII chars should be replaced with underscores
        assert re.match(r"^[A-Za-z0-9_.-]+$", result) or result == "_YoY"


# ══════════════════════════════════════════════════════════════
# _ensure_dir
# ══════════════════════════════════════════════════════════════

class TestEnsureDir:
    def test_creates_directory(self, temp_cache_dir):
        new_dir = os.path.join(temp_cache_dir, "subdir")
        _ensure_dir(new_dir)
        assert os.path.isdir(new_dir)

    def test_existing_directory_no_error(self, temp_cache_dir):
        _ensure_dir(temp_cache_dir)  # Should not raise


# ══════════════════════════════════════════════════════════════
# _list_cache_files
# ══════════════════════════════════════════════════════════════

class TestListCacheFiles:
    def test_nonexistent_directory_returns_empty(self):
        result = _list_cache_files("/nonexistent/path", "prefix_")
        assert result == []

    def test_no_matching_files_returns_empty(self, temp_cache_dir):
        # Create a file that doesn't match
        filepath = os.path.join(temp_cache_dir, "other_file.json")
        with open(filepath, "w") as f:
            json.dump({}, f)
        result = _list_cache_files(temp_cache_dir, "myprefix_")
        assert result == []

    def test_lists_matching_files_sorted(self, temp_cache_dir):
        for name in ["key_20260101_120000_000000.json", "key_20260102_120000_000000.json"]:
            with open(os.path.join(temp_cache_dir, name), "w") as f:
                json.dump({}, f)
        result = _list_cache_files(temp_cache_dir, "key_")
        assert len(result) == 2
        assert result == sorted(result)

    def test_ignores_non_json_files(self, temp_cache_dir):
        with open(os.path.join(temp_cache_dir, "key_001.txt"), "w") as f:
            f.write("not json")
        result = _list_cache_files(temp_cache_dir, "key_")
        assert result == []


# ══════════════════════════════════════════════════════════════
# read_cache
# ══════════════════════════════════════════════════════════════

class TestReadCache:
    def test_cache_miss_returns_none(self, temp_cache_dir):
        result = read_cache("nonexistent", max_age_hours=24, directory=temp_cache_dir)
        assert result is None

    def test_cache_hit_returns_data(self, temp_cache_dir, sample_cache_data):
        write_cache("mykey", sample_cache_data, directory=temp_cache_dir)
        result = read_cache("mykey", max_age_hours=24, directory=temp_cache_dir)
        assert result == sample_cache_data

    def test_stale_cache_returns_none(self, temp_cache_dir):
        """Cache older than max_age_hours should return None."""
        stale_time = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
        payload = {"cached_at": stale_time, "data": {"old": True}}
        safe = _safe_key("stale_key")
        filepath = os.path.join(temp_cache_dir, f"{safe}_stale.json")
        with open(filepath, "w") as f:
            json.dump(payload, f)
        result = read_cache("stale_key", max_age_hours=24, directory=temp_cache_dir)
        assert result is None

    def test_fresh_cache_returns_data(self, temp_cache_dir, fresh_timestamp):
        """Cache newer than max_age_hours should return data."""
        payload = {"cached_at": fresh_timestamp, "data": {"fresh": True}}
        safe = _safe_key("fresh_key")
        filepath = os.path.join(temp_cache_dir, f"{safe}_fresh.json")
        with open(filepath, "w") as f:
            json.dump(payload, f)
        result = read_cache("fresh_key", max_age_hours=24, directory=temp_cache_dir)
        assert result == {"fresh": True}

    def test_max_age_zero_returns_without_checking_freshness(self, temp_cache_dir):
        """max_age_hours=0 should return the latest cache regardless of age."""
        stale_time = (datetime.now() - timedelta(days=365)).isoformat(timespec="seconds")
        payload = {"cached_at": stale_time, "data": {"very_old": True}}
        safe = _safe_key("zero_ttl")
        filepath = os.path.join(temp_cache_dir, f"{safe}_old.json")
        with open(filepath, "w") as f:
            json.dump(payload, f)
        result = read_cache("zero_ttl", max_age_hours=0, directory=temp_cache_dir)
        assert result == {"very_old": True}

    def test_missing_cached_at_with_positive_ttl_returns_none(self, temp_cache_dir):
        """If cached_at is missing and max_age_hours > 0, return None."""
        payload = {"data": {"no_timestamp": True}}
        safe = _safe_key("no_ts")
        filepath = os.path.join(temp_cache_dir, f"{safe}_file.json")
        with open(filepath, "w") as f:
            json.dump(payload, f)
        result = read_cache("no_ts", max_age_hours=24, directory=temp_cache_dir)
        assert result is None

    def test_invalid_cached_at_format_returns_none(self, temp_cache_dir):
        """If cached_at is not a valid ISO format, return None."""
        payload = {"cached_at": "not-a-date", "data": {"bad_ts": True}}
        safe = _safe_key("bad_ts")
        filepath = os.path.join(temp_cache_dir, f"{safe}_file.json")
        with open(filepath, "w") as f:
            json.dump(payload, f)
        result = read_cache("bad_ts", max_age_hours=24, directory=temp_cache_dir)
        assert result is None

    def test_corrupt_json_returns_none(self, temp_cache_dir):
        """If the cache file is not valid JSON, return None."""
        safe = _safe_key("corrupt")
        filepath = os.path.join(temp_cache_dir, f"{safe}_file.json")
        with open(filepath, "w") as f:
            f.write("not valid json{{{")
        result = read_cache("corrupt", max_age_hours=24, directory=temp_cache_dir)
        assert result is None

    def test_returns_latest_file_when_multiple(self, temp_cache_dir):
        """When multiple cache files exist, read the latest one."""
        safe = _safe_key("multi")
        # Write older file
        old_payload = {"cached_at": datetime.now().isoformat(timespec="seconds"), "data": {"version": 1}}
        old_path = os.path.join(temp_cache_dir, f"{safe}_20260101_000000_000000.json")
        with open(old_path, "w") as f:
            json.dump(old_payload, f)

        # Write newer file
        new_payload = {"cached_at": datetime.now().isoformat(timespec="seconds"), "data": {"version": 2}}
        new_path = os.path.join(temp_cache_dir, f"{safe}_20260102_000000_000000.json")
        with open(new_path, "w") as f:
            json.dump(new_payload, f)

        result = read_cache("multi", max_age_hours=24, directory=temp_cache_dir)
        assert result == {"version": 2}


# ══════════════════════════════════════════════════════════════
# write_cache
# ══════════════════════════════════════════════════════════════

class TestWriteCache:
    def test_creates_cache_file(self, temp_cache_dir, sample_cache_data):
        write_cache("testkey", sample_cache_data, directory=temp_cache_dir)
        files = [f for f in os.listdir(temp_cache_dir) if f.endswith(".json")]
        assert len(files) == 1

    def test_cache_file_contains_data(self, temp_cache_dir, sample_cache_data):
        write_cache("testkey", sample_cache_data, directory=temp_cache_dir)
        files = [f for f in os.listdir(temp_cache_dir) if f.endswith(".json")]
        with open(os.path.join(temp_cache_dir, files[0]), "r") as f:
            payload = json.load(f)
        assert payload["data"] == sample_cache_data
        assert "cached_at" in payload

    def test_write_with_metadata(self, temp_cache_dir):
        meta = {"source": "test", "version": 1}
        write_cache("metakey", {"val": 1}, directory=temp_cache_dir, metadata=meta)
        files = [f for f in os.listdir(temp_cache_dir) if f.endswith(".json")]
        with open(os.path.join(temp_cache_dir, files[0]), "r") as f:
            payload = json.load(f)
        assert payload["metadata"] == meta

    def test_write_without_metadata(self, temp_cache_dir):
        write_cache("nometakey", {"val": 1}, directory=temp_cache_dir)
        files = [f for f in os.listdir(temp_cache_dir) if f.endswith(".json")]
        with open(os.path.join(temp_cache_dir, files[0]), "r") as f:
            payload = json.load(f)
        assert "metadata" not in payload

    def test_ring_buffer_eviction(self, temp_cache_dir):
        """Writing more than keep_count files should evict the oldest."""
        for i in range(5):
            write_cache("ringkey", {"i": i}, directory=temp_cache_dir, keep_count=3)
        files = _list_cache_files(temp_cache_dir, "ringkey_")
        assert len(files) == 3

    def test_ring_buffer_keeps_latest(self, temp_cache_dir):
        """After eviction, the remaining files should be the most recent ones."""
        for i in range(5):
            write_cache("ringkey2", {"i": i}, directory=temp_cache_dir, keep_count=3)
        # Read the latest cache — should have the last value
        result = read_cache("ringkey2", max_age_hours=0, directory=temp_cache_dir)
        assert result == {"i": 4}

    def test_keep_count_1(self, temp_cache_dir):
        """With keep_count=1, only the latest file should remain."""
        for i in range(3):
            write_cache("single", {"i": i}, directory=temp_cache_dir, keep_count=1)
        files = _list_cache_files(temp_cache_dir, "single_")
        assert len(files) == 1

    def test_creates_directory_if_missing(self):
        """write_cache should create the directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as d:
            new_dir = os.path.join(d, "new_subdir")
            write_cache("key", {"v": 1}, directory=new_dir)
            assert os.path.isdir(new_dir)


# ══════════════════════════════════════════════════════════════
# fetch_with_cache
# ══════════════════════════════════════════════════════════════

class TestFetchWithCache:
    def test_invalid_policy_raises_value_error(self):
        with pytest.raises(ValueError, match="未知的 policy"):
            fetch_with_cache("nonexistent_policy", "key", lambda: None)

    def test_cache_hit_does_not_call_fetch_fn(self, temp_cache_dir):
        """If cache is valid, fetch_fn should not be called."""
        mock_fetch = MagicMock(return_value={"new": True})
        # Pre-populate cache
        write_cache("hit_key", {"cached": True}, directory=temp_cache_dir)
        result = fetch_with_cache("monthly_revenue", "hit_key", mock_fetch, directory=temp_cache_dir)
        mock_fetch.assert_not_called()
        assert result == {"cached": True}

    def test_cache_miss_calls_fetch_fn(self, temp_cache_dir):
        """If cache is empty, fetch_fn should be called."""
        mock_fetch = MagicMock(return_value={"fetched": True})
        result = fetch_with_cache("monthly_revenue", "miss_key", mock_fetch, directory=temp_cache_dir)
        mock_fetch.assert_called_once()
        assert result == {"fetched": True}

    def test_ttl_zero_always_fetches(self, temp_cache_dir):
        """TTL=0 policies should always call fetch_fn, even with valid cache."""
        mock_fetch = MagicMock(return_value={"fresh": True})
        # Pre-populate cache
        write_cache("zero_key", {"cached": True}, directory=temp_cache_dir)
        result = fetch_with_cache("twse_daily", "zero_key", mock_fetch, directory=temp_cache_dir)
        mock_fetch.assert_called_once()
        assert result == {"fresh": True}

    def test_writes_cache_after_fetch(self, temp_cache_dir):
        """After fetching, the result should be written to cache."""
        mock_fetch = MagicMock(return_value={"written": True})
        fetch_with_cache("monthly_revenue", "write_test", mock_fetch, directory=temp_cache_dir)
        # Now read_cache should find it
        result = read_cache("write_test", max_age_hours=24, directory=temp_cache_dir)
        assert result == {"written": True}

    def test_stale_cache_triggers_fetch(self, temp_cache_dir):
        """Stale cache should trigger a new fetch."""
        mock_fetch = MagicMock(return_value={"refreshed": True})
        # Write a stale cache entry
        stale_time = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
        payload = {"cached_at": stale_time, "data": {"stale": True}}
        safe = _safe_key("stale_fetch")
        filepath = os.path.join(temp_cache_dir, f"{safe}_old.json")
        with open(filepath, "w") as f:
            json.dump(payload, f)

        result = fetch_with_cache("monthly_revenue", "stale_fetch", mock_fetch, directory=temp_cache_dir)
        mock_fetch.assert_called_once()
        assert result == {"refreshed": True}

    def test_all_valid_policy_names(self):
        """All policy names in DATA_POLICIES should be accepted without error."""
        for policy_name in DATA_POLICIES:
            # Use a unique key per policy to avoid cross-contamination
            mock_fetch = MagicMock(return_value={"ok": True})
            with tempfile.TemporaryDirectory() as d:
                result = fetch_with_cache(policy_name, f"probe_{policy_name}", mock_fetch, directory=d)
                assert result == {"ok": True}


# ══════════════════════════════════════════════════════════════
# get_policy_ttl
# ══════════════════════════════════════════════════════════════

class TestGetPolicyTtl:
    def test_returns_correct_ttl(self):
        assert get_policy_ttl("monthly_revenue") == 24

    def test_returns_zero_for_twse_daily(self):
        assert get_policy_ttl("twse_daily") == 0

    def test_returns_2160_for_sec_13f(self):
        assert get_policy_ttl("sec_13f") == 2160

    def test_invalid_policy_raises_value_error(self):
        with pytest.raises(ValueError, match="未知的 policy"):
            get_policy_ttl("nonexistent")

    def test_all_policies_have_non_negative_ttl(self):
        for name in DATA_POLICIES:
            ttl = get_policy_ttl(name)
            assert ttl >= 0, f"{name} has negative TTL"
