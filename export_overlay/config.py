"""Sector/company preset types and API key lookup. Keys never live in source or in the repo.

The presets themselves live in `sectors.py`.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # 기업추적 (2026-10-21 주식3 max20 에서 옮김)
CACHE_DIR = ROOT / ".cache" / "export_overlay"
OUTPUT_DIR = ROOT / ".cache" / "수출겹쳐보기"            # 만든 화면 — 뷰어가 /overlay/ 로 내준다(.cache 라 git 제외)
LOCAL_ENV = ROOT / ".env"
SITE_SETTINGS = ROOT / "설정.py"                        # 기업추적의 키 찾기(DART: 환경변수 → .env → D.env → DART_ENV_PATH)
START_YEAR = 2015
CUSTOMS_KEY = "DATA_GO_KR_KEY"
DART_KEY = "DART_API_KEY"


@dataclass(frozen=True)
class View:
    key: str
    label: str
    prefixes: tuple[str, ...]      # HS codes whose rows this view sums (prefix match on the returned codes)
    in_mix: bool = True            # shown as a bar in the item-mix panel (off for overlapping groups)
    # (first quarter, last quarter, reason): export quarters left out of this view's correlations and analogs
    # (an HS code created mid-series, goods that are not the sector's — e.g. COVID test kits in 300215).
    breaks: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class Company:
    stock_code: str
    name: str
    # (first quarter, last quarter, reason): YoY in these quarters is not comparable and is left out
    # of the company line, the basket and every correlation.
    breaks: tuple[tuple[str, str, str], ...] = ()
    note: str = ""                 # what the company is and how its numbers should be read (shown on the page)
    # (absorbed stock code, first quarter): from that quarter the YoY base also includes the absorbed
    # company's revenue a year earlier (pro-forma), since the merger's comparatives were not restated.
    absorbed: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Sector:
    key: str                       # file name: output/<key>.html
    name: str                      # 섹터 이름
    noun: str                      # what to call the companies: '장비사', '조선사' …
    hs: tuple[str, ...]            # customs query codes (2-, 4- or 6-digit); a query returns one level down
    views: tuple[View, ...]        # the first view is the sector's main definition
    companies: tuple[Company, ...]
    caveat: str                    # what the customs number does and does not capture — shown under the chart
    excluded_note: str = ""        # big companies left out and why
    mix_note: str = ""             # optional sentence about the item mix

    def __post_init__(self):
        for a in self.hs:
            for b in self.hs:
                if a != b and b.startswith(a):
                    raise ValueError(f"{self.key}: 질의 {a} 가 {b} 를 포함해 두 번 센다")
        for v in self.views:
            if not any(p.startswith(q) or q.startswith(p) for p in v.prefixes for q in self.hs):
                raise ValueError(f"{self.key}: 보기 {v.key} 의 코드가 질의 밖이다")


class KeyMissing(RuntimeError):
    pass


def read_kv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines (# comments, optional quotes). A missing file reads as empty."""
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            out[name.strip()] = value
    return out


def api_key(name: str, environ: Mapping[str, str] = os.environ, local_env: Path = LOCAL_ENV) -> str:
    """Environment → repo `.env` → each file listed in KEY_FILES (`;`-separated).

    A relative KEY_FILES entry is read from the folder holding `.env`, so `..\\주식\\기업추적\\.env`
    keeps working on another PC where the synced Google Drive has a different drive letter or name.
    """
    value = environ.get(name, "").strip()
    if value:
        return value
    local = read_kv(local_env)
    if local.get(name):
        return local[name]
    key_files = environ.get("KEY_FILES", "").strip() or local.get("KEY_FILES", "")
    for raw in key_files.split(";"):
        if raw.strip():
            path = Path(raw.strip())
            value = read_kv(path if path.is_absolute() else Path(local_env).parent / path).get(name, "")
            if value:
                return value
    raise KeyMissing(f"{name} 를 찾지 못했습니다. 저장소 루트 .env 에 {name}=... 또는 "
                     "KEY_FILES=<키가 든 파일 경로;...> 를 적으세요.")


def site_dart_key(settings: Path = SITE_SETTINGS) -> str:
    """기업추적 `설정.dart_api_key()` — 수집기 · 뷰어와 같은 곳에서 DART 키를 찾는다. 못 찾거나 읽지 못하면 ''."""
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("기업추적_설정", settings)
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return (mod.dart_api_key() or "").strip()
    except Exception:
        return ""


def resolve_key(name: str) -> str:
    """api_key, 그리고 DART 키는 없으면 기업추적 설정.py 로 한 번 더(이 패키지가 기업추적 안에 있을 때)."""
    try:
        return api_key(name)
    except KeyMissing:
        if name == DART_KEY:
            value = site_dart_key()
            if value:
                return value
        raise
