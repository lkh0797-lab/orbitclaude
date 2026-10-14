# -*- coding: utf-8 -*-
"""일봉 캐시 신선도(2026-10-14) — 그날 값이 굳는 평일 20:10(넥스트레이드 애프터마켓 끝) 전에 받은 캐시는 그 뒤 다시 받는다.
2026-10-13 19:02~19:04 에 받은 그날 값 7종목이 모두 다음 날 값과 달랐다(LG전자 179,200 → 178,300)."""
import os, sys, json, datetime as dt, importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("재무_주가캐시_시험", os.path.join(BASE, "재무.py"))
FIN = ilu.module_from_spec(_sp); _sp.loader.exec_module(FIN)

D = dt.datetime


def test_last_final_weekdays_and_weekend():
    assert FIN.FINAL_AT == (20, 10)
    assert FIN.last_final(D(2026, 10, 14, 14, 0)) == D(2026, 10, 13, 20, 10)     # 수 장중 → 화 20:10
    assert FIN.last_final(D(2026, 10, 14, 19, 0)) == D(2026, 10, 13, 20, 10)     # 정규장 끝났어도 시간외 중
    assert FIN.last_final(D(2026, 10, 14, 20, 10)) == D(2026, 10, 14, 20, 10)
    assert FIN.last_final(D(2026, 10, 12, 9, 0)) == D(2026, 10, 9, 20, 10)       # 월 아침 → 금
    assert FIN.last_final(D(2026, 10, 11, 12, 0)) == D(2026, 10, 9, 20, 10)      # 일요일


def _cache_at(tmp_path, when, name="x.json"):
    p = tmp_path / name
    p.write_text("{}", encoding="utf-8")
    os.utime(p, (when.timestamp(), when.timestamp()))
    return str(p)


def test_cache_fetched_before_final_goes_stale(tmp_path):
    p = _cache_at(tmp_path, D(2026, 10, 13, 19, 2))                 # 화 19:02 — 정규장 뒤, 시간외 중(LG전자 사례)
    assert FIN._cache_ok(p, 86400, now=D(2026, 10, 13, 20, 0))
    assert not FIN._cache_ok(p, 86400, now=D(2026, 10, 13, 20, 11))  # 굳은 뒤 — 다시
    assert not FIN._cache_ok(p, 86400, now=D(2026, 10, 14, 15, 58)) # 예전 24시간 규칙이면 그대로 쓰던 때
    q = _cache_at(tmp_path, D(2026, 10, 13, 10, 0), "y.json")       # 장중
    assert FIN._cache_ok(q, 86400, now=D(2026, 10, 13, 15, 0))
    assert not FIN._cache_ok(q, 86400, now=D(2026, 10, 14, 9, 0))


def test_cache_fetched_after_final_kept_until_next_final(tmp_path):
    p = _cache_at(tmp_path, D(2026, 10, 13, 21, 43))
    assert FIN._cache_ok(p, 86400, now=D(2026, 10, 14, 15, 0))
    assert not FIN._cache_ok(p, 86400, now=D(2026, 10, 14, 20, 11))
    fri = _cache_at(tmp_path, D(2026, 10, 9, 21, 0), "f.json")      # 금 밤 → 주말엔 24시간 규칙만
    assert FIN._cache_ok(fri, 86400, now=D(2026, 10, 10, 12, 0))
    assert not FIN._cache_ok(fri, 86400, now=D(2026, 10, 10, 21, 1))
    assert not FIN._cache_ok(str(tmp_path / "없음.json"), 86400)


def test_write_json_is_whole(tmp_path):
    p = str(tmp_path / "y.json")
    FIN._write_json(p, {"20261013": 178300.0})
    assert json.load(open(p, encoding="utf-8")) == {"20261013": 178300.0}
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
