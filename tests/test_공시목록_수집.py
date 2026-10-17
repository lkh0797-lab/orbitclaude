# -*- coding: utf-8 -*-
"""공시목록 수집기 — DART 빈 응답(013) · 덜 받은 판으로 열린 분기 파일을 덮지 않는다(2026-10-17). 네트워크 없이 fetch 를 갈아 끼운다."""
import os, sys, json, datetime as dt, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("공시목록_수집_시험", os.path.join(BASE, "도구", "공시목록_수집.py"))
C = ilu.module_from_spec(_sp); _sp.loader.exec_module(C)


def R(n, d="20261015"):
    return {"rcept_no": "2026%010d" % n, "rcept_dt": d, "corp_code": "0", "corp_name": "가", "stock_code": "000001",
            "corp_cls": "Y", "report_nm": "공시 %d" % n, "flr_nm": "가"}


def test_settle_rules():
    old = [R(i) for i in range(100)]
    assert C.settle([], [R(1)], True) == ([R(1)], None)
    new, note = C.settle(old, old[:99], True)                 # 다 받았고 한 줄(철회) 줄었다 — 새 목록
    assert len(new) == 99 and note is None
    new, note = C.settle(old, old[:50], True)                 # 크게 줄었다 — 옛 줄을 합쳐 남긴다
    assert len(new) == 100 and "줄어듦" in note
    new, note = C.settle(old, [], False)                      # 013 — 옛 파일 그대로
    assert len(new) == 100 and "끝까지 못 받음" in note
    new, _ = C.settle(old[:10], old[:10] + [R(500)], True)    # 늘었다 — 새 목록
    assert len(new) == 11


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", str(tmp_path))
    monkeypatch.setattr(C.time, "sleep", lambda s: None)
    monkeypatch.setattr(C.F, "API_KEY", "x", raising=False)
    return tmp_path


def run(monkeypatch, pages, argv=("--from", "2026", "--types", "I")):
    """pages: 쪽 번호 → 응답 dict. 지금 분기(열린 분기)만 돌게 오늘 날짜를 고정하지 않고 2026 부터 — 닫힌 분기는 .done 이 있으면 건너뛴다."""
    def fake(params, calls):
        calls[0] += 1
        return pages(params)
    monkeypatch.setattr(C, "fetch", fake)
    return C.main(list(argv))


def _cur_lab():
    t = dt.date.today()
    return "%dQ%d" % (t.year, (t.month - 1) // 3 + 1)


def _mark_closed_done(tmp, upto_lab):
    for y in (2026,):
        for q in (1, 2, 3, 4):
            lab = "%dQ%d" % (y, q)
            if lab >= upto_lab:
                return
            open(os.path.join(str(tmp), "I_%s.jsonl.done" % lab), "w").close()


def test_013_keeps_open_quarter_file(env, monkeypatch):
    lab = _cur_lab()
    _mark_closed_done(env, lab)
    p = os.path.join(str(env), "I_%s.jsonl" % lab)
    C.write_rows(p, [R(i) for i in range(30)])
    run(monkeypatch, lambda prm: {"status": "013", "message": "조회된 데이터가 없습니다."})
    assert len(C.read_rows(p)) == 30


def test_empty_page_midway_merges(env, monkeypatch):
    lab = _cur_lab()
    _mark_closed_done(env, lab)
    p = os.path.join(str(env), "I_%s.jsonl" % lab)
    C.write_rows(p, [R(i) for i in range(250)])
    def pages(prm):
        if prm["page_no"] == 1:
            return {"status": "000", "total_page": 3, "total_count": 251, "list": [R(i) for i in range(100)]}
        return {"status": "000", "total_page": 3, "total_count": 251, "list": []}     # 둘째 쪽이 비어 옴
    run(monkeypatch, pages)
    rows = C.read_rows(p)
    assert len(rows) == 250 and len({r["rcept_no"] for r in rows}) == 250


def test_complete_fetch_replaces_and_drops_withdrawn(env, monkeypatch):
    lab = _cur_lab()
    _mark_closed_done(env, lab)
    p = os.path.join(str(env), "I_%s.jsonl" % lab)
    C.write_rows(p, [R(i) for i in range(101)])               # R(100) 은 철회됨
    def pages(prm):
        k = prm["page_no"]
        return {"status": "000", "total_page": 2, "total_count": 102,
                "list": [R(i) for i in range(100)] if k == 1 else [R(i) for i in (99, 101, 102)]}   # 쪽 밀림으로 99 가 두 번
    run(monkeypatch, pages)
    got = {r["rcept_no"] for r in C.read_rows(p)}
    assert len(got) == 102 and R(100)["rcept_no"] not in got and R(102)["rcept_no"] in got


def test_closed_empty_quarter_not_marked_done(env, monkeypatch):
    run(monkeypatch, lambda prm: {"status": "013"}, argv=("--from", "2025", "--types", "I", "--max-calls", "4"))
    assert not os.path.exists(os.path.join(str(env), "I_2025Q1.jsonl.done"))
