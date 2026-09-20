# -*- coding: utf-8 -*-
"""
로컬 경로·비밀값 로더.

내 PC에만 있는 경로(다른 프로젝트의 .env, 시총 스크리닝 엑셀 등)를
소스에 박지 않기 위한 모듈. 공개 저장소에 개인 폴더 구조가 남지 않는다.

찾는 순서:
  1) 환경변수
  2) 이 폴더의 .env
  3) 이 폴더의 경로설정.txt   (git 에 올리지 않는다)

경로설정.txt 예시:
    DART_ENV_PATH=C:\\어딘가\\다른프로젝트\\D.env
    UNIVERSE_XLSX=C:\\어딘가\\개별종목_시총*.xlsx
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
_CACHE = None


def _read_kv(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                out[k.strip()] = v
    return out


def _local():
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        _CACHE.update(_read_kv(os.path.join(BASE, "경로설정.txt")))
        _CACHE.update(_read_kv(os.path.join(BASE, ".env")))
    return _CACHE


def get(name, default=None):
    """환경변수 > .env > 경로설정.txt 순으로 값 하나."""
    v = os.environ.get(name, "").strip()
    if v:
        return v
    return _local().get(name, default)


def env_files():
    """DART_API_KEY 가 들어있을 만한 파일 경로들. 앞에 있는 것이 우선."""
    out = [os.path.join(BASE, ".env"), os.path.join(BASE, "D.env")]
    extra = get("DART_ENV_PATH")
    if extra:
        out.append(extra)
    return out


def dart_api_key():
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    for path in env_files():
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("DART_API_KEY") and "=" in line:
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
    return ""
