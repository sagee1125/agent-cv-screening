from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any


class HashCache:
    """Hash-based JSON cache for deterministic parsing outputs."""

    def __init__(self, cache_dir: str) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    async def md5_for_file(file_path: str) -> str:
        path = Path(file_path)
        return await asyncio.to_thread(HashCache._md5_sync, path)

    @staticmethod
    def _md5_sync(path: Path) -> str:
        md5 = hashlib.md5()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(8192), b""):
                md5.update(chunk)
        return md5.hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    async def get(self, key: str) -> dict[str, Any] | None:
        cache_path = self._cache_path(key)
        if not cache_path.exists():
            return None
        payload = await asyncio.to_thread(cache_path.read_text, "utf-8")
        return json.loads(payload)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        cache_path = self._cache_path(key)
        payload = json.dumps(value, ensure_ascii=False, indent=2)
        await asyncio.to_thread(cache_path.write_text, payload, "utf-8")
