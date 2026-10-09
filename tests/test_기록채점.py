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


def _jrow(asof, code, pattern, stage, stop=None, close=100.0):
    return {"asof": asof, "code": code, "pattern": pattern, "stage": stage, "stop": stop, "close": close}


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
    rows = [_jrow(D[4], "T1", "vcp", "breakout", 95.0),       # 손절 먼저(그 뒤 +25%)
            _jrow(D[4], "T2", "vcp", "breakout", 95.0),       # 목표 먼저(그 뒤 손절가 아래)
            _jrow(D[4], "T3", "vcp", "forming", 90.0),        # 60일 다 지나 열린 채
            _jrow(D[280], "T4", "vcp", "breakout", 90.0),     # 아직 60일 안 됨 — 빼고 센다
            _jrow(D[4], "L", "leader", "")]                   # 손절가 없음 — 빼고 센다
    tech = M.score([], rows, p, UNIV)["tech"]
    g = {x["key"]: x for x in tech["groups"]}
    a = g["all"]
    assert a["n_exit"] == 3 and a["stop_first"] == 33.33 and a["target_first"] == 33.33
    assert g["stage:breakout"]["n_exit"] == 2 and g["stage:breakout"]["stop_first"] == 50.0
    assert g["pattern:leader"]["n_exit"] == 0 and g["pattern:leader"]["stop_first"] is None
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


def test_tech_groups_rec_avoid_new():
    t = flat_univ()
    for c in "ABCDEFGL":
        t[c] = flat()
    p = M.Prices(loader(t))
    rows = [_jrow(D[4], "A", "big_value_pullback", "breakout"),
            _jrow(D[4], "B", "vcp", "near_pivot"),
            _jrow(D[4], "C", "cup_handle", "breakout"),
            _jrow(D[4], "L", "leader", ""),
            _jrow(D[4], "L", "canslim", "forming"),                # 같은 날 같은 종목 — 전체에선 한 번
            _jrow(D[4], "E", "canslim", "extended"),
            _jrow(D[4], "F", "flat_base", "failed"),
            _jrow(D[5], "A", "big_value_pullback", "near_pivot"),
            _jrow(D[5], "G", "vcp", "breakout")]
    tech = M.score([], rows, p, UNIV)["tech"]
    g = {x["key"]: x for x in tech["groups"]}
    assert tech["dates"] == [D[4], D[5]]
    assert [x["key"] for x in tech["groups"]][:4] == ["all", "new", "rec", "avoid"]
    assert g["all"]["n_obs"] == 8 and g["all"]["n_codes"] == 7
    assert g["new"]["n_obs"] == 7                              # 첫날 여섯 + 둘째 날 G
    assert g["rec"]["n_obs"] == 4                              # A · C · A(피벗 근처) · G
    assert g["avoid"]["n_obs"] == 3                            # 주도주 L · 이격 E · 실패 F
    assert g["pattern:canslim"]["n_obs"] == 2 and g["pattern:big_value_pullback"]["n_obs"] == 2
    assert g["stage:-"]["n_obs"] == 1 and g["stage:-"]["label"] == "단계 · 단계 없음"
    assert g["pattern:vcp"]["label"] == "패턴 · VCP"
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
    assert back["value"]["dates"] == [D[4]] and back["tech"]["dates"] == [D[4]]
    assert back["price_last"] == D[100] and back["cutoff"] == D[100]
    assert set(back["value"]["groups"][0]["h"]) == {"5", "20", "60", "120", "250"}
    assert back["tech"]["groups"][0]["n_obs"] == 1 and back["tech"]["groups"][0]["n_exit"] == 1
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
