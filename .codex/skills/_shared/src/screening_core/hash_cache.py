# Hash-based JSON cache for deterministic parsing outputs.
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any


class HashCache:
    """Hash-based JSON cache for deterministic parsing outputs."""

    # Creates a cache directory for MD5-keyed JSON payloads.
    def __init__(self, cache_dir: str) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # Returns the MD5 hex digest of a file without blocking the event loop.
    @staticmethod
    async def md5_for_file(file_path: str) -> str:
        path = Path(file_path)
        return await asyncio.to_thread(HashCache._md5_sync, path)

    # Reads a file in chunks and computes its MD5 digest.
    @staticmethod
    def _md5_sync(path: Path) -> str:
        md5 = hashlib.md5()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(8192), b""):
                md5.update(chunk)
        return md5.hexdigest()

    # Resolves the on-disk JSON path for a cache key.
    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    # Loads a cached JSON object, or None when missing.
    async def get(self, key: str) -> dict[str, Any] | None:
        cache_path = self._cache_path(key)
        if not cache_path.exists():
            return None
        payload = await asyncio.to_thread(cache_path.read_text, "utf-8")
        return json.loads(payload)

    # Writes a JSON object into the cache under the given key.
    async def set(self, key: str, value: dict[str, Any]) -> None:
        cache_path = self._cache_path(key)
        payload = json.dumps(value, ensure_ascii=False, indent=2)
        await asyncio.to_thread(cache_path.write_text, payload, "utf-8")
