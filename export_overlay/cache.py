"""Small JSON file cache with per-read TTL. Keys must never contain API keys."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class JsonCache:
    def __init__(self, root: Path, clock: Callable[[], float] = time.time):
        self._root = Path(root)
        self._clock = clock

    def path(self, key: str) -> Path:
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
        prefix = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", key)[:40].strip("_")
        return self._root / f"{prefix}_{digest}.json"

    def get(self, key: str, ttl: float) -> Any | None:
        """The stored value, or None when it is missing, older than `ttl` seconds or unreadable."""
        path = self.path(key)
        try:
            if self._clock() - path.stat().st_mtime >= ttl:
                return None
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def put(self, key: str, value: Any) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False)
        os.replace(tmp, path)
