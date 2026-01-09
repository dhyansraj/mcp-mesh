"""Caching utilities for the data processor agent."""

import hashlib
import json
import os
import pickle
import time
from pathlib import Path
from typing import Any, Dict, Optional


def cache_key(*args, **kwargs) -> str:
    """Generate a cache key from arguments."""
    # Convert all arguments to a string representation
    key_data = {
        "args": [str(arg) for arg in args],
        "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
    }

    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(key_string.encode()).hexdigest()


class CacheManager:
    """Simple file-based cache manager for data processing operations."""

    def __init__(
        self, cache_dir: str = "/tmp/data_processor_cache", ttl_seconds: int = 3600
    ):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Create cache info file
        self.info_file = self.cache_dir / "cache_info.json"
        self._init_cache_info()

    def _init_cache_info(self):
        """Initialize cache information file."""
        if not self.info_file.exists():
            cache_info = {
                "created": time.time(),
                "entries": {},
                "stats": {"hits": 0, "misses": 0, "total_size_bytes": 0},
            }
            with open(self.info_file, "w") as f:
                json.dump(cache_info, f, indent=2)

    def _load_cache_info(self) -> Dict[str, Any]:
        """Load cache information."""
        if self.info_file.exists():
            with open(self.info_file, "r") as f:
                return json.load(f)
        return {"entries": {}, "stats": {"hits": 0, "misses": 0, "total_size_bytes": 0}}

    def _save_cache_info(self, info: Dict[str, Any]):
        """Save cache information."""
        with open(self.info_file, "w") as f:
            json.dump(info, f, indent=2)

    def get(self, key: str) -> Optional[Any]:
        """Get an item from cache."""
        info = self._load_cache_info()

        if key not in info["entries"]:
            info["stats"]["misses"] += 1
            self._save_cache_info(info)
            return None

        entry = info["entries"][key]

        # Check if entry is expired
        if time.time() - entry["timestamp"] > self.ttl_seconds:
            self.delete(key)
            info["stats"]["misses"] += 1
            self._save_cache_info(info)
            return None

        # Load data
        cache_file = self.cache_dir / f"{key}.pkl"
        if not cache_file.exists():
            # Entry exists in info but file is missing
            del info["entries"][key]
            info["stats"]["misses"] += 1
            self._save_cache_info(info)
            return None

        try:
            with open(cache_file, "rb") as f:
                data = pickle.load(f)

            info["stats"]["hits"] += 1
            self._save_cache_info(info)
            return data

        except Exception:
            # Corrupted cache file
            self.delete(key)
            info["stats"]["misses"] += 1
            self._save_cache_info(info)
            return None

    def set(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None):
        """Set an item in cache."""
        cache_file = self.cache_dir / f"{key}.pkl"

        # Save data
        try:
            with open(cache_file, "wb") as f:
                pickle.dump(value, f)

            # Update info
            info = self._load_cache_info()
            file_size = cache_file.stat().st_size

            # Remove old entry size if it exists
            if key in info["entries"]:
                info["stats"]["total_size_bytes"] -= info["entries"][key]["size"]

            info["entries"][key] = {
                "timestamp": time.time(),
                "size": file_size,
                "metadata": metadata or {},
            }
            info["stats"]["total_size_bytes"] += file_size

            self._save_cache_info(info)

        except Exception as e:
            # Failed to cache
            if cache_file.exists():
                cache_file.unlink()
            raise e

    def delete(self, key: str):
        """Delete an item from cache."""
        info = self._load_cache_info()

        if key in info["entries"]:
            # Remove file
            cache_file = self.cache_dir / f"{key}.pkl"
            if cache_file.exists():
                cache_file.unlink()

            # Update info
            info["stats"]["total_size_bytes"] -= info["entries"][key]["size"]
            del info["entries"][key]
            self._save_cache_info(info)

    def clear(self):
        """Clear all cache entries."""
        info = self._load_cache_info()

        # Remove all cache files
        for key in info["entries"]:
            cache_file = self.cache_dir / f"{key}.pkl"
            if cache_file.exists():
                cache_file.unlink()

        # Reset info
        info["entries"] = {}
        info["stats"]["total_size_bytes"] = 0
        self._save_cache_info(info)

    def cleanup_expired(self):
        """Remove expired cache entries."""
        info = self._load_cache_info()
        current_time = time.time()
        expired_keys = []

        for key, entry in info["entries"].items():
            if current_time - entry["timestamp"] > self.ttl_seconds:
                expired_keys.append(key)

        for key in expired_keys:
            self.delete(key)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        info = self._load_cache_info()
        stats = info["stats"].copy()

        stats["total_entries"] = len(info["entries"])
        stats["total_size_formatted"] = self._format_size(stats["total_size_bytes"])

        total_requests = stats["hits"] + stats["misses"]
        stats["hit_rate"] = (
            round(stats["hits"] / total_requests * 100, 2) if total_requests > 0 else 0
        )

        return stats

    def _format_size(self, size_bytes: int) -> str:
        """Format byte size in human-readable format."""
        try:
            from .formatting import format_size

            return format_size(size_bytes)
        except ImportError:
            from formatting import format_size

            return format_size(size_bytes)
