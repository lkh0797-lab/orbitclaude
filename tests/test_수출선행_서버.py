# -*- coding: utf-8 -*-
"""수출 선행 발굴 서버 — 가짜 캐시로 exlead_view · value_view 배지(2026-10-14).
설계 docs/superpowers/specs/2026-10-14-export-lead-value-design.md 4절, 계획 Task 3."""
import os, sys, json, copy, datetime as dt, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_수출선행_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)


def _mon(last="202608", v=100.0, bump=1.5):
    out = {}
    y, m = 2023, 1
    while "%04d%02d" % (y, m) <= last:
        k = "%04d%02d" % (y, m)
        out[k] = v * (bump if k >= "202607" else 1.0)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _item(code="000001", name="가짜", grade="A", cur=50.0, reported=False, lumpy=False):
    return {"code": code, "name": name, "status": "ok", "grade": grade, "series_long": _mon(),
            "signals": {"last": "202608", "y12": 30.0, "state": "가속"},
            "aligned": {"cur_q": "2026Q3", "prev_q": "2026Q2", "months": ["202607", "202608"], "reported": reported, "cur": cur,
                        "prev": 10.0, "acc": 40.0, "lumpy": lumpy, "est": 25.0, "err": 8.0, "state": "가속", "last": "202608"},
            "validation": {"pairs": [{"q": "2026Q1", "x": 20, "r": 15}, {"q": "2026Q2", "x": -5, "r": 2}], "last_rev_q": "2026Q2"},
            "national": [{"hs": "854232", "unit_yoy": 12.0, "name": "메모리"}]}


def _px(days=400, start=10000.0, end=9000.0):
    d0 = dt.date.today() - dt.timedelta(days=days)        # 오늘까지 — 주가 조건은 공통 기준일(_last_close 날짜) 열흘 안 봉에서 잰다
    out = {}
    for i in range(days + 1):
        d = d0 + dt.timedelta(days=i)
        if d.weekday() < 5:
            out[d.strftime("%Y%m%d")] = start + (end - start) * i / days
    return out


@pytest.fixture
def world(monkeypatch, tmp_path):
    items = [_item(), _item("000002", "비쌈", cur=60.0)]
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "export_view", lambda: {"items": copy.deepcopy(items), "month": "202608"})
    px = {"000001": _px(), "000002": _px(end=13000.0)}
    for k in ("000003", "000004", "000005"):
        px[k] = _px(end=10500.0)                       # 전 종목 3개월 중앙값 ≈ +1% (5곳 — _exl_univ3m 최소)
    monkeypatch.setattr(SRV, "_px_file", lambda code: dict(px.get(code) or {}))
    monkeypatch.setattr(SRV, "_score_universe", lambda: sorted(px))
    monkeypatch.setattr(SRV, "FIN", None)              # value_view 가 _run_value 스레드를 띄우지 않게
    land = {"000001": {"decide": {"pct": 30.0, "per": 8.5, "zone": "쌈"}, "rows": [{"de": 40.0}]},
            "000002": {"decide": {"pct": 80.0, "per": 30.0, "zone": "비쌈"}, "rows": [{"de": 40.0}]}}
    monkeypatch.setattr(SRV, "_land_read", lambda code: copy.deepcopy(land.get(code)))
    monkeypatch.setattr(SRV, "_disc_risk", lambda: {"codes": {}})
    monkeypatch.setattr(SRV, "_kis_snapshot", lambda: None)
    monkeypatch.setattr(SRV, "sector_map", lambda: {"stocks": {}})
    monkeypatch.setattr(SRV, "VAL", {"rows": [], "at": 0, "running": False})
    monkeypatch.setattr(SRV, "VAL_DIR", str(tmp_path))  # 저장된 실제 저평가 결과(_result.json)를 읽지 않게
    SRV._EXL.update(key=None, d=None, univ={})          # 전 종목 중앙값 캐시(줄 캐시와 같은 키)도 비운다 — 시험마다 다시 센다
    return tmp_path


def test_exlead_rows_and_tiers(world):
    d = SRV.exlead_view()
    assert d["verdict"] is None and "(검증 전)" in d["title"]
    by = {r["code"]: r for r in d["rows"]}
    a, b = by["000001"], by["000002"]
    assert a["tier"] == "발굴" and a["why"] == [] and a["due"]["due"] == "2026-11-16" and a["hit"] == [1, 2]
    assert a["months_label"] == "7~8월" and a["cur_q"] == "2026Q3" and a["unit_yoy"] == 12.0
    assert a["per_pct"] == 30.0 and a["zone"] == "쌈" and len(a["idx"]) == 24
    assert b["tier"] == "관찰" and any("상위 20%" in w for w in b["why"]) and any("이미 올랐다" in w for w in b["why"])
    assert d["rows"][0]["code"] == "000001"                         # 발굴 먼저


def test_exlead_missing_landscape_is_unknown_value(world, monkeypatch):
    monkeypatch.setattr(SRV, "_land_read", lambda code: None)
    SRV._EXL.update(key=None, d=None)
    r = {x["code"]: x for x in SRV.exlead_view()["rows"]}["000001"]
    assert r["tier"] == "관찰" and r["per_pct"] is None and any("값 모름" in w for w in r["why"])


def test_exlead_reads_bt_and_sets_title(world):
    os.makedirs(os.path.join(str(world), "수출선행"), exist_ok=True)
    bt = {"v": 1, "verdict": "관찰", "groups": {"발굴": {"n": 40, "firms": 9, "days": 30, "ex12": {"med": -1.2, "ci": [-5.0, 2.0], "early": -2.0, "late": 1.0, "n": 40}}}}
    with open(os.path.join(str(world), "수출선행", "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(bt, fh)
    SRV._EXL.update(key=None, d=None)
    d = SRV.exlead_view()
    assert d["verdict"] == "관찰" and "과거 우위 근거 없음" in d["title"] and d["bt"]["groups"]["발굴"]["n"] == 40
    assert all(r["tier_label"] == "관찰 후보" for r in d["rows"] if r["tier"] == "발굴")


def test_exlead_uses_saved_value_red_even_before_value_tab(world):
    # 저평가 결과를 아직 메모리에 안 읽었어도(VAL 비어 있음) 저장분 _result.json 의 빨간불을 쓴다 — /api/exlead 를 먼저 열어도 같은 등급
    saved = {"v": SRV.VAL_V, "at": 5, "n_fell": 0, "n_univ": 0,
             "rows": [{"code": "000001", "name": "가짜", "tier": "관찰", "score": 40, "red": ["부채비율 240% — 200% 넘는 빚"]}]}
    with open(os.path.join(str(world), "_result.json"), "w", encoding="utf-8") as fh:
        json.dump(saved, fh)
    SRV._EXL.update(key=None, d=None)
    r = {x["code"]: x for x in SRV.exlead_view()["rows"]}["000001"]
    assert r["tier"] == "관찰" and r["checks"]["red"] is True and r["why"] == ["빨간불: 부채비율 240% — 200% 넘는 빚"]
    assert SRV.VAL["at"] == 5                                      # 저장분이 메모리에 올라왔다(계산 스레드는 없다)


def test_value_rows_get_export_badge(world, monkeypatch):
    monkeypatch.setattr(SRV, "VAL", {"rows": [{"code": "000001", "name": "가짜", "tier": "저평가", "score": 60, "red": []}], "at": 1, "running": False})
    monkeypatch.setattr(SRV, "_val_score_spec", lambda: None)
    SRV._EXL.update(key=None, d=None)
    rows = SRV.value_view()["rows"]
    assert rows[0]["exl"]["tier"] == "발굴" and rows[0]["exl"]["cur"] == 50.0 and rows[0]["exl"]["months_label"] == "7~8월"


# ---- 2026-10-14 리뷰 뒤 회귀 검사(T1 · R1 · R2 · R3 · R4 · EXL-LA-1)
def _count_universe(monkeypatch):
    calls, base = [], SRV._score_universe
    monkeypatch.setattr(SRV, "_score_universe", lambda: (calls.append(1), base())[1])
    return calls


def test_exlead_small_per_sample_is_unknown_value(world, monkeypatch):
    # 풍경 PER 표본(band.n) 2분기 → 백분위 100 이어도 '싸지 않다' 가 아니라 값 모름(관찰) — 과거 검증(bt_panel 8분기↑)과 같은 조건 (T1)
    land = {"decide": {"pct": 100.0, "per": 2348.9, "zone": "비싸다", "date": "20261013"}, "band": {"n": 2, "mid": 18.8}, "rows": [{"de": 28.0}]}
    monkeypatch.setattr(SRV, "_land_read", lambda code: copy.deepcopy(land))
    SRV._EXL.update(key=None, d=None)
    d = SRV.exlead_view()
    r = {x["code"]: x for x in d["rows"]}["000001"]
    assert r["tier"] == "관찰" and r["why"] == ["값 모름 — PER 표본 2분기(8 미만)"] and r["checks"]["value"] is None
    assert r["per_pct"] is None and r["per_n"] == 2 and r["zone"] is None and r["per"] == 2348.9 and r["land_d"] == "20261013"
    assert d["rules"]["per_n"] == 8


def test_univ3m_recomputed_with_rows_when_price_cache_refreshes(world, monkeypatch):
    # 06:30 주가 갱신 흉내(모든 봉 +5%, 저평가 계산 시각 바뀜) → 줄의 ret3m 과 전 종목 중앙값이 같이 다시 계산된다 — day 만 키였을 때는 중앙값만 묵었다(R1)
    calls = _count_universe(monkeypatch)
    d1 = SRV.exlead_view()
    u1 = d1["rows"][0]["univ3m"]
    assert len(calls) == 1 and u1 is not None
    base = SRV._px_file
    cut = (dt.date.today() - dt.timedelta(days=12)).strftime("%Y%m%d")
    monkeypatch.setattr(SRV, "_px_file", lambda code: {k: (v * 1.05 if k >= cut else v) for k, v in (base(code) or {}).items()})
    SRV.VAL["at"] = 2
    d2 = SRV.exlead_view()
    u2 = d2["rows"][0]["univ3m"]
    assert len(calls) == 2 and u2 > u1 and all(r["univ3m"] == u2 for r in d2["rows"])
    assert SRV.exlead_view() is d2 and len(calls) == 2            # 키 그대로면 캐시


def test_key_tracks_price_dir_signature(world, monkeypatch):
    # .cache/price 에 파일이 새로 쓰이면(수 · 최신 mtime) 다음 호출이 다시 센다 — 06:30 갱신이 저평가 계산 시각을 안 바꿔도
    calls = _count_universe(monkeypatch)
    SRV.exlead_view()
    pdir = os.path.join(str(world), "price")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "000009.json"), "w", encoding="utf-8") as fh:
        json.dump({"20260102": 1.0}, fh)
    SRV.exlead_view()
    assert len(calls) == 2 and SRV._px_dir_sig()[0] == 1
    SRV.exlead_view()
    assert len(calls) == 2


def test_concurrent_cold_calls_compute_once(world, monkeypatch):
    # 차가운 첫 호출 둘이 겹쳐도 988곳 읽기(_score_universe)는 한 번 — 둘째는 잠금에서 기다렸다 같은 결과를 받는다(R2)
    import threading, time as _t
    calls, base = [], SRV._score_universe

    def slow():
        calls.append(1)
        _t.sleep(0.3)
        return base()
    monkeypatch.setattr(SRV, "_score_universe", slow)
    SRV._EXL.update(key=None, d=None, univ={})
    outs = []
    ts = [threading.Thread(target=lambda: outs.append(SRV.exlead_view())) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1 and len(outs) == 2 and outs[0] is outs[1]


def test_rows_use_common_basis_day(world, monkeypatch):
    # 줄과 전 종목 중앙값은 같은 기준일(_last_close 날짜) 열흘 안 마지막 봉에서 — 파일별 마지막 봉이 아니다(T3 · R3)
    d = SRV.exlead_view()
    _, lc, _ = SRV._last_close()
    assert d["px_day"] == lc.strftime("%Y%m%d")
    assert all(r["price_d"] and r["price_d"] <= d["px_day"] for r in d["rows"]) and d["px_days"] == sorted({r["price_d"] for r in d["rows"]})
    base = SRV._px_file
    old = (dt.date.today() - dt.timedelta(days=30)).strftime("%Y%m%d")
    monkeypatch.setattr(SRV, "_px_file", lambda code: ({k: v for k, v in base(code).items() if k < old} if code == "000001" else base(code)))
    SRV._EXL.update(key=None, d=None, univ={})
    r = {x["code"]: x for x in SRV.exlead_view()["rows"]}["000001"]           # 기준일 열흘 안 봉이 없는 묵은 파일 → 주가 모름(관찰)
    assert r["ret3m"] is None and r["dd52"] is None and r["price_d"] is None and r["tier"] == "관찰" and "주가 모름 — 이력 91일 미만" in r["why"]


def test_px_file_drops_unconfirmed_last_bar(monkeypatch, tmp_path):
    # 마지막 봉(평일 D)을 그날 20:10(FINAL_AT) 전에 쓴 파일은 그 봉이 확정 전 값 — 뺀다. 20:10 뒤 · 다음 날 받은 파일은 그대로(EXL-LA-1)
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "FIN", None)
    pdir = os.path.join(str(tmp_path), "price")
    os.makedirs(pdir)

    def put(code, when):
        p = os.path.join(pdir, code + ".json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"20261008": 100.0, "20261013": 236000.0}, fh)
        os.utime(p, (when.timestamp(), when.timestamp()))
    put("900001", dt.datetime(2026, 10, 13, 19, 3))        # 화요일 봉을 그날 19:03 에 — 확정 전
    put("900002", dt.datetime(2026, 10, 13, 20, 30))       # 20:10 뒤 — 굳은 값
    put("900003", dt.datetime(2026, 10, 14, 6, 31))        # 다음 날 아침 다시 받음 — 굳은 값
    assert SRV._px_file("900001") == {"20261008": 100.0}
    assert SRV._px_file("900002") == {"20261008": 100.0, "20261013": 236000.0}
    assert SRV._px_file("900003") == {"20261008": 100.0, "20261013": 236000.0}
    assert SRV._px_unconfirmed("20261011", dt.datetime(2026, 10, 11, 9, 0).timestamp()) is False    # 일요일 날짜
    assert SRV._px_unconfirmed("20261013", dt.datetime(2026, 10, 13, 20, 10).timestamp()) is False  # 꼭 20:10 은 굳은 값
    assert SRV._px_unconfirmed("bad", 0) is False and SRV._px_unconfirmed("20261013", None) is False


def test_open_server_refuses_port_in_use():
    # 같은 포트에 서버 둘이 조용히 뜨지 않는다 — 이미 LISTENING 이면 SystemExit(확인 명령 포함), 빈 포트는 열린다(R4)
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        with pytest.raises(SystemExit) as ei:
            SRV._open_server(port)
        assert "이미 사용 중" in str(ei.value) and str(port) in str(ei.value)
    finally:
        s.close()
    srv = SRV._open_server(0)
    try:
        assert srv.server_address[1] > 0 and srv.allow_reuse_address is False
    finally:
        srv.server_close()
