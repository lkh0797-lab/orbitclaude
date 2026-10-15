# -*- coding: utf-8 -*-
"""기록채점 — 가짜 주가 · tmp_path 파일로만 잰다(실제 캐시는 건드리지 않는다)."""
import os, sys, json, datetime as dt, importlib.util as ilu
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("기록채점", os.path.join(BASE, "기록채점.py"))
M = ilu.module_from_spec(_sp); _sp.loader.exec_module(M)


def bdays(n, start=dt.date(2026, 1, 5)):
    """월~금만 — 2026-01-05 은 월요일."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += dt.timedelta(days=1)
    return out


D = bdays(300)
UNIV = ["U%02d" % k for k in range(25)]


def flat(v=100.0, dates=D):
    return {d: v for d in dates}


def step(after, v1, v0=100.0, dates=D):
    """after 번째 날까지 v0, 그 뒤 v1."""
    return {d: (v0 if i <= after else v1) for i, d in enumerate(dates)}


def loader(table, calls=None):
    def load(code):
        if calls is not None:
            calls.append(code)
        t = table.get(code)
        return dict(t) if t is not None else None
    return load


def flat_univ():
    return {u: flat() for u in UNIV}


# ---------------------------------------------------------------- 실전 기록 읽기
def _wfwd(dirp, name, price_ds, tier="저평가"):
    rows = [{"code": "%06d" % (i + 1), "name": "x", "tier": tier, "score": 50.0, "price": 1000.0,
             "price_d": p, "risk": None} for i, p in enumerate(price_ds)]
    (dirp / name).write_text(json.dumps({"at": 0, "score_spec": "t", "rows": rows}, ensure_ascii=False),
                             encoding="utf-8")


def test_load_forward_dedupes_by_data_date(tmp_path):
    _wfwd(tmp_path, "20261006.json", ["20261002"] * 3)
    _wfwd(tmp_path, "20261007.json", ["20261006"] * 3)
    _wfwd(tmp_path, "20261008.json", ["20261006", "20261006", "20261007"])   # 섞인 파일 — 가장 늦은 날(10-07)
    _wfwd(tmp_path, "20261009.json", ["20261008"] * 2)                       # 휴일에 다시 쓴 파일
    _wfwd(tmp_path, "20261010.json", ["20261008"] * 3)
    _wfwd(tmp_path, "20261013.json", ["20261009", "20261012"])               # 가장 늦은 날
    (tmp_path / "_result.json").write_text("{}", encoding="utf-8")
    (tmp_path / "20261014.json").write_text("{broken", encoding="utf-8")
    snaps = M.load_forward(str(tmp_path))
    assert [s["data_date"] for s in snaps] == ["20261002", "20261006", "20261007", "20261008", "20261012"]
    # 같은 기준일이면 가장 이른 파일(가장 먼저 진입할 수 있던 기록) — 휴일 · 주말에 다시 쓴 것은 버린다
    assert [s["file"] for s in snaps] == ["20261006.json", "20261007.json", "20261008.json", "20261009.json",
                                          "20261013.json"]
    assert [s["file_date"] for s in snaps] == ["20261006", "20261007", "20261008", "20261009", "20261013"]
    assert len(snaps[1]["rows"]) == 3 and len(snaps[3]["rows"]) == 2
    assert M.load_forward(str(tmp_path / "없음")) == []


# ---------------------------------------------------------------- 진입 · 기간
def test_entry_is_next_trading_day_close():
    t = flat_univ()
    t["000001"] = {d: 100.0 + i for i, d in enumerate(D)}
    p = M.Prices(loader(t))
    ev = M._evaluate(p, UNIV, "000001", D[4])               # 금요일 기록 → 월요일 종가
    assert D[4] == "20260109" and ev["entry_d"] == "20260112" == D[5]
    r, ex = ev["h"][5]
    assert r == pytest.approx(110.0 / 105.0 - 1) and ex == pytest.approx(r)   # 벤치 0
    assert M._evaluate(p, UNIV, "000001", "20260110")["entry_d"] == D[5]    # 토요일 기준일도 월요일
    # 파일을 늦게 썼으면(섞인 날) 그 날보다 앞서 진입하지 않는다
    assert M._evaluate(p, UNIV, "000001", D[4], not_before="20260114")["entry_d"] == "20260114"
    snap = {"file": "20260114.json", "data_date": D[4],
            "rows": [{"code": "000001", "tier": "저평가", "score": 1.0, "price_d": D[4]}]}
    res = M.score([snap], [], p, UNIV)
    g = res["value"]["groups"][0]
    assert g["h"]["5"]["median"] == round((112.0 / 107.0 - 1) * 100, 2)
    # 마지막 날 기록은 아직 진입 전
    ev = M._evaluate(p, UNIV, "000001", D[-1])
    assert ev["entry_d"] is None and ev["h"] == {} and ev["now"] is None
    assert M._evaluate(p, UNIV, "없는코드", D[4]) is None


def test_horizon_maturity_and_cutoff():
    t = flat_univ()
    t["000002"] = {d: 100.0 + i * 0.1 for i, d in enumerate(D)}
    p = M.Prices(loader(t))
    ev = M._evaluate(p, UNIV, "000002", D[200])              # 진입 D[201], 남은 98거래일
    assert sorted(ev["h"]) == [5, 20, 60]
    assert ev["h"][60][0] == pytest.approx((100 + 26.1) / (100 + 20.1) - 1)
    assert ev["now"][2] == 299 - 201
    ev = M._evaluate(p, UNIV, "000002", D[200], cutoff=D[230])
    assert sorted(ev["h"]) == [5, 20] and ev["now"][2] == 29
    snap = {"data_date": D[200], "rows": [{"code": "000002", "tier": "저평가", "score": 1.0}]}
    g = M.score([snap], [], p, UNIV, today=D[230])["value"]["groups"][0]
    assert g["h"]["20"]["n"] == 1 and g["h"]["60"]["n"] == 0 and g["h"]["60"]["median"] is None
    assert g["h"]["60"]["n_all"] == 1 and g["now"]["days_median"] == 29


# ---------------------------------------------------------------- 분할 보정
def test_split_repair_and_cache():
    raw = {}
    for i, d in enumerate(D[:30]):
        raw[d] = 1000.0 if i < 10 else (500.0 if i < 20 else 520.0)   # 10번째 날 2:1 분할
    raw[D[30]] = None                                                  # 빈 값은 버린다
    raw[D[31]] = 0
    early = {d: (100.0 if i < 3 else 200.0) for i, d in enumerate(D[:20])}   # 상장 직후 — 그대로
    calls = []
    p = M.Prices(loader({"S": raw, "E": early}, calls))
    ds, cs = p.series("S")
    assert len(ds) == 30 and cs[:10] == [500.0] * 10 and cs[10:20] == [500.0] * 10 and cs[-1] == 520.0
    ds, cs = p.series("E")
    assert cs[:3] == [100.0] * 3 and cs[3] == 200.0
    p.series("S")
    assert calls == ["S", "E"]                                         # 종목마다 한 번만 읽는다
    assert p.series("없음") == ([], []) and p.last == D[29]
    # since — 보정은 전체로 하고 앞을 버린다
    q = M.Prices(loader({"S": raw}), since=D[5])
    ds, cs = q.series("S")
    assert ds[0] == D[5] and cs[0] == 500.0
    # 시너지._adjusted 와 같은 규칙
    ds = sorted(d for d in raw if raw[d])
    assert M._adjusted({d: raw[d] for d in ds}, ds)[:10] == [500.0] * 10


# ---------------------------------------------------------------- 벤치마크
def test_bench_median_and_excess():
    t = {u: step(9, 100.0 * (1 + k / 100.0)) for k, u in enumerate(UNIV)}     # D[10] 부터 k% 오른다
    t["S_old"] = {d: 100.0 for d in D[:4]}                                    # 너무 오래된 주가
    t["S_near"] = step(9, 110.0, dates=D[:13])                                # 5일 전 주가 — 쓴다
    t["X"] = step(9, 130.0)
    calls = []
    p = M.Prices(loader(t, calls))
    assert M.bench(p, UNIV, D[5], D[15]) == pytest.approx(0.12)
    n = len(calls)
    assert M.bench(p, UNIV, D[5], D[15]) == pytest.approx(0.12) and len(calls) == n   # 기억
    assert (D[5], D[15]) in p.bench_memo
    assert M.bench(p, UNIV[:19], D[5], D[15]) is None                         # 20종목 못 됨
    assert M.bench(p, UNIV[:19] + ["S_old"], D[5], D[15]) is None
    assert M.bench(p, UNIV[:19] + ["S_near"], D[5], D[15]) == pytest.approx(0.095)
    assert sum(1 for c in calls if c == "U00") == 1                           # 다시 읽지 않는다
    r, ex = M._evaluate(p, UNIV, "X", D[4])["h"][5]                           # 진입 D[5] → D[10]
    assert r == pytest.approx(0.30) and ex == pytest.approx(0.30 - 0.12)


# ---------------------------------------------------------------- 저평가 묶음
RET = {"000010": 0.10, "000020": -0.05, "000030": 0.20, "000040": 0.0, "000050": -0.10, "000060": 0.30}


def _value_setup():
    t = flat_univ()
    for c, r in RET.items():
        t[c] = step(5, 100.0 * (1 + r))           # D[6] 부터 r 만큼
    snaps = [
        {"data_date": D[4], "rows": [
            {"code": "000010", "tier": "저평가", "score": 90.0, "risk": None},
            {"code": "000020", "tier": "저평가", "score": 80.0, "risk": None},
            {"code": "000030", "tier": "관찰", "score": 70.0, "risk": None},
            {"code": "000040", "tier": "관찰", "score": 60.0, "risk": None},
            {"code": "000050", "tier": "관찰", "score": 50.0, "risk": None},
            {"code": "000060", "tier": "관찰", "score": None, "risk": "작전주 꼴"},
            {"code": "000060", "tier": "관찰", "score": None, "risk": "작전주 꼴"}]},   # 같은 날 겹침
        {"data_date": D[5], "rows": [
            {"code": "000010", "tier": "저평가", "score": 95.0, "risk": None},
            {"code": "000030", "tier": "저평가", "score": 85.0, "risk": None},
            {"code": "000020", "tier": "관찰", "score": 75.0, "risk": None}]},
    ]
    return M.Prices(loader(t)), snaps


def test_value_groups():
    p, snaps = _value_setup()
    v = M.score(snaps, [], p, UNIV)["value"]
    g = {x["key"]: x for x in v["groups"]}
    assert [x["key"] for x in v["groups"]] == ["tier_v", "tier_o", "score_top", "score_bot", "risk", "new_v"]
    assert v["dates"] == [D[4], D[5]] and v["n_codes"] == 6
    assert g["tier_v"]["n_obs"] == 4 and g["tier_v"]["n_codes"] == 3
    h5 = g["tier_v"]["h"]["5"]                 # 0.10, −0.05(첫날) · 0, 0(둘째 날 — 진입이 오른 뒤)
    assert h5["n"] == 4 and h5["mean"] == 1.25 and h5["median"] == 0.0 and h5["worst"] == -5.0
    assert h5["ex_median"] == 0.0 and h5["win"] == 25.0
    assert g["tier_o"]["n_obs"] == 5
    assert g["score_top"]["n_obs"] == 2 and g["score_top"]["h"]["5"]["median"] == 5.0
    assert g["score_bot"]["h"]["5"]["median"] == -5.0 and g["score_bot"]["h"]["5"]["worst"] == -10.0
    assert g["risk"]["n_obs"] == 1 and g["risk"]["h"]["5"]["median"] == 30.0
    assert g["new_v"]["n_obs"] == 3 and g["new_v"]["n_codes"] == 3        # 첫날 둘 + 둘째 날 000030
    c = v["cohorts"]
    assert [(x["date"], x["n_v"], x["n_o"]) for x in c] == [(D[4], 2, 4), (D[5], 2, 1)]
    assert c[0]["now_v"]["median"] == 2.5 and c[0]["now_v"]["days_median"] == 299 - 5
    assert v["ref"]["label"] == "백테스트 기대(README)"


# ---------------------------------------------------------------- Tech 일지
def test_load_journal_bom_zfill_leader(tmp_path):
    f = tmp_path / "journal.csv"
    f.write_text(
        "asof,code,name,market,pattern,stage,pivot,stop,composite,rs,close,value,leader,track_ret\n"
        "2026-10-08,5930,삼성전자,KOSPI,vcp,breakout,70000.0,65000.0,90,95,71000,1e11,False,3.2\n"
        "2026-10-08,131290,티에스이,KOSDAQ,leader,,,,33.7,99.0,309000.0,22391000000.0,True,\n"
        "2026-10-08,303810.0,동국,KOSDAQ,,,,,4.3,36.0,2665.0,2078000000.0,False,\n"
        ",999999,날짜없음,KOSPI,vcp,breakout,1,1,1,1,1,1,False,\n",
        encoding="utf-8-sig")
    raw = f.read_bytes()
    rows = M.load_journal(str(f))
    assert f.read_bytes() == raw                       # 읽기만
    assert [r["code"] for r in rows] == ["005930", "131290", "303810"]
    a, b, c = rows
    assert a["asof"] == "20261008" and a["stop"] == 65000.0 and a["value"] == 1e11 and a["leader"] is False
    assert b["pattern"] == "leader" and b["stage"] == "" and b["pivot"] is None and b["stop"] is None
    assert b["leader"] is True and b["rs"] == 99.0
    assert c["pattern"] == "" and "track_ret" not in a


def _jrow(asof, code, pattern, stage, stop=None, close=100.0, rule=""):
    """rule 이 비면 옛 탐지기 기록(2026-10-14 Tech 패턴 초기화 전, 제거된 식) — 채점에서 빠진다(2026-10-16)."""
    return {"asof": asof, "code": code, "pattern": pattern, "stage": stage, "stop": stop, "close": close, "rule": rule}


def test_stop_target_first_by_closes():
    t = flat_univ()
    # 하루 ±30% 안에서만 움직여 분할 보정이 끼지 않게
    t["T1"] = {d: (96.0 if i == 6 else 94.0 if i == 7 else 110.0 if i in (8, 9) else 125.0 if i > 9 else 100.0)
               for i, d in enumerate(D)}
    t["T2"] = {d: (121.0 if i == 8 else 90.0 if i > 8 else 100.0) for i, d in enumerate(D)}
    t["T3"] = flat()
    t["T4"] = flat()
    t["L"] = flat()
    p = M.Prices(loader(t))
    fib = dict(rule="fibpb_v1")
    rows = [_jrow(D[4], "T1", "fib_pullback", "breakout", 95.0, **fib),       # 손절 먼저(그 뒤 +25%)
            _jrow(D[4], "T2", "fib_pullback", "breakout", 95.0, **fib),       # 목표 먼저(그 뒤 손절가 아래)
            _jrow(D[4], "T3", "fib_pullback", "forming", 90.0, **fib),        # 60일 다 지나 열린 채
            _jrow(D[280], "T4", "fib_pullback", "breakout", 90.0, **fib),     # 아직 60일 안 됨 — 빼고 센다
            _jrow(D[4], "L", "vcp", "breakout", 95.0)]                        # 옛 탐지기 기록 — 채점에서 빠진다
    res = M.score([], rows, p, UNIV)
    assert "tech_legacy" not in res
    g = {x["key"]: x for x in res["tech"]["groups"]}
    a = g["all"]
    assert a["n_exit"] == 3 and a["stop_first"] == 33.33 and a["target_first"] == 33.33
    assert a["n_obs"] == 4 and "pattern:vcp" not in g
    assert g["stage:breakout"]["n_exit"] == 2 and g["stage:breakout"]["stop_first"] == 50.0
    assert M._evaluate(p, UNIV, "T1", D[4], stop=95.0)["exit"] == "stop"
    assert M._evaluate(p, UNIV, "T2", D[4], stop=95.0)["exit"] == "target"
    ev = M._evaluate(p, UNIV, "T4", D[280], stop=90.0)
    assert ev["exit"] == "open" and ev["exit_done"] is False


def test_stop_follows_split_after_record():
    raw = {d: (1000.0 if i < 10 else 480.0) for i, d in enumerate(D)}    # D[10] 에 주식 수 변화(1000 → 480)
    p = M.Prices(loader(dict(flat_univ(), S=raw)))
    ev = M._evaluate(p, UNIV, "S", D[4], stop=950.0)                       # 손절가도 보정 기준(×0.48)으로
    assert ev["exit"] == "open" and ev["exit_done"] is True
    gap = {d: v for d, v in raw.items() if d != D[4]}                        # 기록 날 종가가 없어도 직전 거래일 비율
    p2 = M.Prices(loader(dict(flat_univ(), S=gap)))
    assert M._evaluate(p2, UNIV, "S", D[4], stop=950.0)["exit"] == "open"


def test_tech_groups_new_pattern_stage():
    t = flat_univ()
    for c in "ABCDEFGL":
        t[c] = flat()
    p = M.Prices(loader(t))
    tl, fb, cw = dict(rule="tlbrk_v1"), dict(rule="fibpb_v1"), dict(rule="cwh_reference_v1.0.0")
    rows = [_jrow(D[4], "A", "trendline_break", "breakout", **tl),
            _jrow(D[4], "B", "fib_pullback", "near_pivot", **fb),
            _jrow(D[4], "C", "cup_with_handle", "breakout", **cw),
            _jrow(D[4], "L", "ma60_supply", "", rule="ma60s_v1"),
            _jrow(D[4], "L", "fib_pullback", "forming", **fb),            # 같은 날 같은 종목 — 전체에선 한 번
            _jrow(D[4], "E", "fib_pullback", "extended", **fb),
            _jrow(D[4], "F", "trendline_break", "failed", **tl),
            _jrow(D[5], "A", "trendline_break", "near_pivot", **tl),
            _jrow(D[5], "G", "cup_with_handle", "breakout", **cw),
            _jrow(D[4], "Z", "vcp", "breakout"),                          # 옛 탐지기 기록 — 빠진다
            _jrow(D[5], "Z", "canslim", "forming")]
    res = M.score([], rows, p, UNIV)
    assert "tech_legacy" not in res and res["schema"] == M.SCHEMA == 4
    tech = res["tech"]
    g = {x["key"]: x for x in tech["groups"]}
    assert tech["dates"] == [D[4], D[5]]
    assert [x["key"] for x in tech["groups"]][:2] == ["all", "new"] and "rec" not in g and "avoid" not in g
    assert g["all"]["n_obs"] == 8 and g["all"]["n_codes"] == 7           # 옛 기록 Z 는 세지 않는다
    assert g["new"]["n_obs"] == 7                                         # 첫날 여섯 + 둘째 날 G
    assert g["pattern:fib_pullback"]["n_obs"] == 3 and g["pattern:trendline_break"]["n_obs"] == 3
    assert g["pattern:fib_pullback"]["label"] == "패턴 · 피보나치 눌림 반등"
    assert not any("제거" in x["label"] or "옛" in x["label"] for x in tech["groups"])
    assert g["stage:-"]["n_obs"] == 1 and g["stage:-"]["label"] == "단계 · 단계 없음"
    assert "옛" not in tech["ref"]["text"] and "+3.3/+6.7" not in tech["ref"]["text"]
    assert g["all"]["h"]["5"]["median"] == 0.0 and g["all"]["h"]["5"]["win"] == 0.0


# ---------------------------------------------------------------- 통계 · 출력
def test_stats_rounding():
    st = M._stats([(0.01234, 0.01), (-0.05, -0.02), (0.1, None)], 4)
    assert st == {"n": 3, "n_all": 4, "mean": 2.08, "median": 1.23, "ex_median": -0.5,
                  "win": 50.0, "worst": -5.0, "n_ex": 2}
    st = M._stats([(0.1, 0.1, 3), (0.2, 0.2, 4)], 2, with_days=True)
    assert st["days_median"] == 3.5 and st["median"] == 15.0 and st["win"] == 100.0
    st = M._stats([], 3, with_days=True)
    assert st["n"] == 0 and st["n_all"] == 3 and st["mean"] is None and st["win"] is None
    assert st["days_median"] is None


def test_run_output_is_json_safe(tmp_path):
    p_fwd = tmp_path / "forward"
    p_fwd.mkdir()
    rows = [{"code": c, "name": c, "tier": "저평가" if i < 2 else "관찰", "score": 90.0 - i,
             "price": 100.0, "price_d": D[4], "risk": None, "per": None} for i, c in enumerate(RET)]
    (p_fwd / (D[5] + ".json")).write_text(json.dumps({"at": 1.0, "score_spec": "t", "rows": rows}), encoding="utf-8")
    jp = tmp_path / "journal.csv"
    jp.write_text("asof,code,name,market,pattern,stage,pivot,stop,composite,rs,close,value,leader\n"
                  "%s-%s-%s,10,가,KOSPI,vcp,breakout,101,95,1,1,100,1,False\n" % (D[4][:4], D[4][4:6], D[4][6:]),
                  encoding="utf-8-sig")
    t = flat_univ()
    for c, r in RET.items():
        t[c] = step(5, 100.0 * (1 + r))
    res = M.run(str(p_fwd), str(jp), loader(t), UNIV, today=D[100])
    s = json.dumps(res, ensure_ascii=False, allow_nan=False)
    back = json.loads(s)
    assert back["value"]["dates"] == [D[4]] and "tech_legacy" not in back
    assert back["tech"]["dates"] == [] and back["tech"]["n_obs"] == 0         # rule 칸 없는 일지 = 옛 기록 — 빠진다
    assert back["price_last"] == D[100] and back["cutoff"] == D[100]
    assert set(back["value"]["groups"][0]["h"]) == {"5", "20", "60", "120", "250"}
    assert back["value"]["groups"][0]["h"]["5"]["median"] == 2.5
    assert back["notes"] and back["basis"] and back["value"]["ref"]["text"].startswith("저평가 묶음")
    assert M.run(str(tmp_path / "없음"), str(tmp_path / "없음.csv"), loader({}), [])["value"]["groups"][0]["n_obs"] == 0


def test_stalled_stock_counts_last_close_as_exit():
    t = flat_univ()
    t["DEAD"] = {d: 100.0 * (0.8 ** i) for i, d in enumerate(D[:12])}     # 12거래일 뒤 주가 끊김(상장폐지)
    long_d = D + [M._shift(D[-1], k) for k in range(40, 100)]            # 전체 마지막 날은 그보다 한참 뒤
    for c in list(t):
        if c != "DEAD":
            t[c] = {d: 100.0 for d in long_d}
    p = M.Prices(loader(t))
    snap = {"file": D[4] + ".json", "data_date": D[3],
            "rows": [{"code": "DEAD", "tier": "저평가", "score": 1.0, "price_d": D[3]}]}
    out = M.score([snap], [], p, UNIV)
    g = {x["key"]: x for x in out["value"]["groups"]}["tier_v"]
    assert g["n_stalled"] == 1
    assert g["h"]["250"]["n"] == 1 and g["h"]["250"]["worst"] < -50      # 끊긴 날 종가로 끝남 — 숨지 않는다


def test_invalid_dates_are_ignored(tmp_path):
    _wfwd(tmp_path, "20261340.json", ["20261008"])
    (tmp_path / "20261341.json").write_text('{"rows":[{"code":"1"}]}', encoding="utf-8")
    assert M.load_forward(str(tmp_path)) == []
    assert M._d8("20261340") is None and M._d8("2026-10-08") == "20261008"


def test_legacy_rows_dropped_current_rule_kept():
    """rule 칸이 있는 행(지금 식)만 센다 — 없는 행(2026-10-14 제거된 옛 탐지기)은 채점에서 뺀다(2026-10-16)."""
    t = flat_univ()
    for c in "ABCV":
        t[c] = flat()
    p = M.Prices(loader(t))
    rows = [_jrow(D[4], "A", "vcp", "breakout", 95.0),                                      # 옛 기록
            _jrow(D[4], "B", "", ""),                                                       # 옛 기록 — 보컬만 걸린 후보
            _jrow(D[4], "A", "cup_with_handle", "breakout", rule="cwh_reference_v1.0.0"),  # 같은 날 같은 종목, 새 식
            _jrow(D[5], "C", "cup_with_handle", "near_pivot", rule="cwh_reference_v1.0.0"),
            _jrow(D[5], "V", "vocal", "forming", 90.0, rule="vocal")]
    res = M.score([], rows, p, UNIV)
    cur = res["tech"]
    assert "tech_legacy" not in res
    assert cur["n_obs"] == 3 and cur["dates"] == [D[4], D[5]]
    g = {x["key"]: x for x in cur["groups"]}
    assert "rec" not in g and "avoid" not in g                       # 새 식은 백테스트 전 — 권장 · 피하기 묶음 없음
    assert g["pattern:cup_with_handle"]["label"] == "패턴 · 컵 앤 핸들 (사용자 식)"
    assert g["pattern:vocal"]["label"] == "패턴 · 보컬 (관찰용)"
    assert g["new"]["n_obs"] == 3                                    # 새 식 첫날 A + 둘째 날 C · V (옛 기록과 비교 안 함)
    assert "legacy" not in cur and cur["ref"]["label"] == "지금 식 백테스트"
    ref = cur["ref"]["text"]
    assert "컵 앤 핸들(사용자 식): 백테스트 아직 없음" in ref
    assert "346거래" in ref and "−2.4%" in ref and "승률 31%" in ref        # 보컬은 이미 백테스트됨(손실) — 숨기지 않는다
    assert "+4.0" not in ref                                          # 옛 식 수치를 새 식에 붙이지 않는다
    assert res["schema"] == M.SCHEMA == 4
    assert "pattern:vcp" not in g and "pattern:-" not in g                   # 옛 기록 묶음은 아예 없다
    assert not hasattr(M, "LEGACY_EMPTY") and not hasattr(M, "TECH_LEGACY_REF")


def test_current_rule_exit_rates_not_mixed_with_no_stop_rows():
    """지금 식: 컵 앤 핸들(손절 규칙 없음)이 섞인 묶음은 손절 · +20% 먼저 비율을 내지 않는다 — 보컬 몇 건이 전체 비율로 보이지 않게."""
    t = flat_univ()
    t["A"], t["C"] = flat(), flat()
    t["V"] = {d: (100.0 if i <= 5 else 85.0) for i, d in enumerate(D)}       # 보컬 — 손절가 90 아래로
    p = M.Prices(loader(t))
    rows = [_jrow(D[4], "A", "cup_with_handle", "breakout", rule="cwh_reference_v1.0.0"),
            _jrow(D[4], "C", "cup_with_handle", "breakout", rule="cwh_reference_v1.0.0"),
            _jrow(D[4], "V", "vocal", "breakout", 90.0, rule="vocal")]
    g = {x["key"]: x for x in M.score([], rows, p, UNIV)["tech"]["groups"]}
    for k in ("all", "new", "stage:breakout"):
        assert g[k]["n_exit"] == 1 and g[k]["n_nostop"] == 2, k
        assert g[k]["stop_first"] is None and g[k]["target_first"] is None and "섞여" in g[k]["exit_note"], k
    cup = g["pattern:cup_with_handle"]
    assert cup["stop_first"] is None and cup["exit_note"].startswith("손절 규칙 없음")
    v = g["pattern:vocal"]
    assert v["stop_first"] == 100.0 and v["n_nostop"] == 0 and "exit_note" not in v


def test_exit_note_names_the_patterns_actually_in_the_group():
    """손절가 없는 까닭은 묶음에 든 패턴으로 — 60일선 · 적삼병 묶음에 '컵 앤 핸들'을, 섞인 묶음에 '보컬'만 적지 않는다."""
    t = flat_univ()
    for c in ("M", "R", "F", "T", "B"):
        t[c] = flat()
    p = M.Prices(loader(t))
    rows = [_jrow(D[4], "M", "ma60_supply", "breakout", rule="ma60s_v1"),
            _jrow(D[4], "R", "red_three_monthly", "breakout", rule="red3m_v1"),
            _jrow(D[4], "F", "fib_pullback", "breakout", 90.0, rule="fibpb_v1"),
            _jrow(D[4], "T", "trendline_break", "near_pivot", rule="tlbrk_v1"),          # 돌파 임박 — 손절 아직 없음
            _jrow(D[4], "B", "trendline_break", "breakout", 95.0, rule="tlbrk_v1")]
    g = {x["key"]: x for x in M.score([], rows, p, UNIV)["tech"]["groups"]}
    ma = g["pattern:ma60_supply"]["exit_note"]
    assert ma.startswith("손절 규칙 없음") and "60일선 수급 돌파" in ma and "컵 앤 핸들" not in ma
    allg = g["all"]["exit_note"]
    assert "섞여" in allg and "보컬" not in allg and "피보나치 눌림 반등" in allg and "빗각 추세선 돌파" in allg
    assert "손절가 없는 단계(돌파 · 신호 전 · 실패 표시)" in allg and "60일선 수급 돌파 · 월봉 적삼병: 식 · 기법에 손절 규칙 없음" in allg
    tl = g["pattern:trendline_break"]
    assert tl["stop_first"] is None and "손절가 없는 단계" in tl["exit_note"] and "참고" not in tl["exit_note"]
    assert M.TL_STOP_CAVEAT in tl["exit_note"]                    # 고정 손절 · 관찰 기록이 섞인 한계를 적는다
    assert "exit_note" not in g["pattern:fib_pullback"]


def test_server_hides_cached_result_from_old_scorer(tmp_path, monkeypatch):
    """서버가 옛 기록채점이 쓴 _result.json(형식 판 schema 없음)을 지금 화면 이름표로 보이지 않고 다시 잰다."""
    sp = ilu.spec_from_file_location("서버_채점시험", os.path.join(BASE, "서버.py"))
    srv = ilu.module_from_spec(sp)
    sp.loader.exec_module(srv)
    if srv.SCR is None:
        pytest.skip("서버가 기록채점.py 를 읽지 못함")
    started = []
    monkeypatch.setattr(srv, "SCORE_DIR", str(tmp_path))
    monkeypatch.setattr(srv, "_score_inputs_mtime", lambda: 0.0)
    monkeypatch.setattr(srv, "_run_score", lambda: started.append(1))
    f = tmp_path / "_result.json"
    f.write_text(json.dumps({"tech": {"ref": {"text": "컵 돌파 +3.3/+6.7"}}, "inputs_mtime": 1.0}), encoding="utf-8")
    monkeypatch.setattr(srv, "SCORE", {"running": False, "at": None, "result": None, "error": None})
    v = srv.score_view()
    assert v["result"] is None and v["running"] is True              # 옛 결과는 보이지 않고 다시 잰다
    f.write_text(json.dumps({"schema": srv.SCR.SCHEMA, "tech": {}, "inputs_mtime": 1.0}),
                 encoding="utf-8")
    monkeypatch.setattr(srv, "SCORE", {"running": False, "at": None, "result": None, "error": None})
    v = srv.score_view()
    assert v["result"]["schema"] == srv.SCR.SCHEMA and v["running"] is False


def test_load_journal_reads_rule_column(tmp_path):
    f = tmp_path / "journal.csv"
    f.write_text("asof,code,name,market,pattern,stage,pivot,stop,composite,rs,close,value,leader,rule\n"
                 "2026-10-13,5930,삼성전자,KOSPI,vcp,breakout,1,1,1,1,1,1,False,\n"
                 "2026-10-14,5930,삼성전자,KOSPI,cup_with_handle,near_pivot,1,,1,1,1,1,False,cwh_reference_v1.0.0\n",
                 encoding="utf-8-sig")
    a, b = M.load_journal(str(f))
    assert a["rule"] == "" and M.is_legacy(a) and b["rule"] == "cwh_reference_v1.0.0" and not M.is_legacy(b)
    assert b["stop"] is None and b["code"] == "005930"


def test_pending_cells_get_first_due_date():
    """'익는 중' 대신 첫 숫자가 나오는 날(평일 어림) — 진입한 기록은 마지막 주가 날에서, 진입 전 기록은 다음 평일 진입에서 센다."""
    assert M._add_weekdays("20261016", 1) == "20261019" and M._add_weekdays("20261016", 5) == "20261023"   # 금 → 월
    short = D[:200]
    t = {u: flat(dates=short) for u in UNIV}
    t["A"], t["B"] = flat(dates=short), flat(dates=short)
    p = M.Prices(loader(t))
    fb = dict(rule="fibpb_v1")
    rows = [_jrow(D[198], "A", "fib_pullback", "breakout", 95.0, **fb),     # 진입 D[199] = 주가 마지막 날 — 지금까지 아직
            _jrow(D[199], "B", "fib_pullback", "breakout", 95.0, **fb)]     # 진입 전 — 다음 평일 D[200] 진입 어림
    g = {x["key"]: x for x in M.score([], rows, p, UNIV)["tech"]["groups"]}["all"]
    long_d = bdays(500)
    assert g["now"]["n"] == 0 and g["now"]["due"] == D[200]                  # A: 진입 다음 평일
    assert g["h"]["5"]["n"] == 0 and g["h"]["5"]["due"] == D[204]            # A(D[199]+5) 가 B(D[200]+5) 보다 빠르다
    assert g["h"]["250"]["due"] == long_d[449]
    ev = M._evaluate(p, UNIV, "B", D[199])
    assert ev["entry_d"] is None and ev["due"]["now"] == D[201] and ev["due"]["5"] == D[205]
    done = M._evaluate(p, UNIV, "A", D[100])                                 # 다 지난 기간에는 날짜가 없다
    assert "5" not in done["due"] and "now" not in done["due"] and done["due"]["250"] == long_d[100 + 1 + 250]
