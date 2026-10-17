# -*- coding: utf-8 -*-
"""관심 종목 성장 장부 — 사실 · 판정 · 가짜 변화 막기 · 저장(2026-10-17)."""
import os, sys, json, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("관심장부_시험", os.path.join(BASE, "관심장부.py"))
W = ilu.module_from_spec(_sp); _sp.loader.exec_module(W)


def pt(n, B, phase, base="20250514", bdate=None, ttm=None, inv=None, q=None, turn=None, label=None):
    return {"n": n, "label": label or "Q%d" % n, "가속B": B, "국면": phase, "변곡": turn, "기준일": base, "B기준일": bdate or base,
            "매출_TTM": ttm, "재고일수": inv, "품질": q or [], "fs": "CFS"}


def druck(points, v=4):
    return {"v": v, "basis": "rev", "points": points}


def facts_q(n, B, phase, ttm0=120.0, ttm4=100.0, inv0=50, inv4=40, q=None, turn=None, base=None):
    pts = [pt(k, 1.0, "확장 유지", base="2024%04d" % k, ttm=100.0, inv=40) for k in range(n - 6, n)]
    pts[-4]["매출_TTM"], pts[-4]["재고일수"] = ttm4, inv4
    pts.append(pt(n, B, phase, base=base or "2025%04d" % n, ttm=ttm0, inv=inv0, q=q, turn=turn))
    return W.druck_facts(druck(pts))


def test_druck_facts_now_point_and_growth():
    f = facts_q(10, 4.2, "확장 가속")
    assert f["accel_b"]["v"] == 4.2 and f["accel_b"]["ok"]
    assert f["phase"]["v"] == "확장 가속"
    assert f["rev_yoy"]["v"] == pytest.approx(20.0)
    assert f["inv_d4"]["v"] == pytest.approx(10.0)
    assert f["accel_b"]["x"]["label"] == "Q10"


def test_druck_facts_bad_quality_and_late_phase_untrusted():
    f = facts_q(10, 4.2, "확장 가속", q=["basis"])
    assert not f["accel_b"]["ok"] and "basis" in f["accel_b"]["why"]
    pts = [pt(1, 2.0, "확장 유지"), pt(2, 2.0, "확장 유지"), pt(3, None, None), pt(4, None, None)]
    f = W.druck_facts(druck(pts))
    assert f["accel_b"]["x"]["label"] == "Q2" and not f["accel_b"]["ok"] and "늦음" in f["accel_b"]["why"]


def test_druck_facts_cut_uses_only_known_points():
    pts = [pt(1, 1.0, "확장 유지", base="20240101"), pt(2, -5.0, "둔화", base="20250101")]
    assert W.druck_facts(druck(pts), cut="20241231")["phase"]["v"] == "확장 유지"
    assert W.druck_facts(druck(pts), cut="20250102")["phase"]["v"] == "둔화"


def test_classify_rebase_wait_amend_new():
    a = W.F(1.0, "Q5", "d4", "x")
    assert W.classify(a, W.F(2.0, "Q5", "d5", "x")) == "rebase"
    assert W.classify(a, W.F(2.0, "Q4", "d4", "x")) == "wait"
    assert W.classify(a, W.F(2.0, "Q5", "d4", "y")) == "amend"
    assert W.classify(a, W.F(2.0, "Q6", "d4", "x")) == "new"
    assert W.classify(a, W.F(1.0, "Q5", "d4", "x")) is None
    assert W.classify(a, W.F(None, "Q6", "d4", "x")) is None          # 값 없음 = 바뀜 아님
    assert W.classify(a, W.F(9.0, "Q6", "d4", "x", ok=False)) is None


def test_judge_hysteresis():
    h = {"id": "a1", "tpl": "per_zone"}                                  # PER 자리 ≤ 75, hyst 3
    f = lambda v: W.F(v, "d", "l10", "")                                  # noqa: E731
    assert W.judge(h, f(76)) == "broken"
    assert W.judge(h, f(77), "ok") == "ok"                                # 75+3 안 — 앞 판정 유지
    assert W.judge(h, f(78.5), "ok") == "broken"
    assert W.judge(h, f(73), "broken") == "broken"                        # 75−3 까지 내려와야
    assert W.judge(h, f(71.9), "broken") == "ok"
    assert W.judge(h, W.F(None, "d")) == "unknown"
    assert W.judge({"id": "r", "tpl": "risk_none"}, W.F("작전주 꼴", "d")) == "broken"
    assert W.judge({"id": "r", "tpl": "risk_none"}, W.F("", "d")) == "ok"


def test_step_first_run_silent_then_new_quarter_event():
    hy = [{"id": "h1", "tpl": "phase_ok"}]
    st, ev = W.step(None, facts_q(10, 4.0, "확장 가속"), hy, "2025-05-15")
    assert ev == [] and st["hyp"]["h1"] == "ok"
    st, ev = W.step(st, facts_q(11, -4.0, "정체", turn="▼"), hy, "2025-08-15")
    kinds = [e["kind"] for e in ev]
    assert "quarter" in kinds and "hyp" in kinds
    q = next(e for e in ev if e["kind"] == "quarter")
    assert q["level"] == "warn" and any("확장 가속 → 정체" in x for x in q["lines"])
    h = next(e for e in ev if e["kind"] == "hyp")
    assert h["level"] == "warn" and h["title"].startswith("가설 깨짐")
    assert st["hyp"]["h1"] == "broken"


def test_step_rebase_is_silent_and_wait_keeps_status():
    hy = [{"id": "h1", "tpl": "accel_pos"}]
    st, _ = W.step(None, facts_q(10, 4.0, "확장 가속"), hy, "d1")
    f = facts_q(10, -9.0, "둔화")
    for k in f:
        f[k]["ver"] = "d5.rev"                                            # 식 버전이 바뀜
    st2, ev = W.step(st, f, hy, "d2")
    assert ev == [] and st2["hyp"]["h1"] == "broken"                      # 조용히 다시 기준
    back = facts_q(9, -9.0, "둔화")                                       # 기준이 뒤로(013) — 비교하지 않는다
    for k in back:
        back[k]["ver"] = "d5.rev"
    st3, ev = W.step(st2, back, hy, "d3")
    assert ev == [] and st3["good"]["accel_b"]["x"]["label"] == "Q10"


def test_step_amend_flip_is_info_not_warning():
    hy = [{"id": "h1", "tpl": "accel_pos"}]
    st, _ = W.step(None, facts_q(10, 4.0, "확장 가속", base="20250514"), hy, "d1")
    st, ev = W.step(st, facts_q(10, -6.0, "둔화", base="20250601"), hy, "d2")   # 같은 분기, 기준일(정정) 바뀜
    assert len(ev) == 1 and ev[0]["level"] == "info" and ev[0]["title"].startswith("정정 반영")


def test_step_risk_debounced_and_export_state():
    hy = [{"id": "r1", "tpl": "risk_none"}]
    f0 = {"risk": W.F("", "20261001", "r1"), "export": W.F(10.0, "2026Q3:202607", "x1.1", "", extra={"state": "고성장 유지"})}
    st, _ = W.step(None, f0, hy, "d1")
    risky = lambda day: W.F("작전주 꼴", day, "r1", extra={"hits": ["제3자배정"]})      # noqa: E731
    f1 = {"risk": risky("20261002"), "export": W.F(25.0, "2026Q3:202607,202608", "x1.1", "", extra={"state": "고성장 유지"})}
    st, ev = W.step(st, f1, hy, "d2")
    assert ev == [] and st["hyp"]["r1"] == "ok"                           # 한 번 본 등급 바뀜은 아직 받지 않는다(013 일 수 있다)
    st, ev = W.step(st, dict(f1, risk=risky("20261003")), hy, "d3")
    assert sorted(e["kind"] for e in ev) == ["hyp", "risk"]               # 다른 기준일에서 또 보면 받는다 · 수출은 같은 흐름이라 조용
    f2 = dict(f1, risk=risky("20261004"), export=W.F(-5.0, "2026Q3:202607,202608,202609", "x1.1", "", extra={"state": "꺾임"}))
    st, ev = W.step(st, f2, hy, "d4")
    assert [e["kind"] for e in ev] == ["export"]


def test_risk_blink_from_013_is_silent():
    hy = [{"id": "r1", "tpl": "risk_none"}]
    st, _ = W.step(None, {"risk": W.F("작전주 꼴", "20261001", "r1")}, hy, "d1")
    st, ev = W.step(st, {"risk": W.F("", "20261001", "r1")}, hy, "d2")     # 같은 기준일에 등급이 빠짐(열린 분기 파일이 빔)
    assert ev == [] and st["hyp"]["r1"] == "broken"
    st, ev = W.step(st, {"risk": W.F("작전주 꼴", "20261002", "r1")}, hy, "d3")   # 다음 날 돌아옴
    assert ev == [] and "risk_pending" not in st


def test_risk_facts_groups():
    assert not W.risk_facts(None, "20261001")["risk"]["ok"]
    assert "잣대 밖" in W.risk_facts({"group": "스팩"}, "20261001")["risk"]["why"]
    assert W.risk_facts({"group": "본표본", "level": None}, "20261001")["risk"]["v"] == ""


def rev_fact(v, label, ttm=5.694e12, ver="d4.rev", as_of="008105", fp="a"):
    return W.F(v, as_of, ver, fp, True, None, {"ttm": ttm, "label": label})


def test_backlog_and_per_facts():
    tr = {"n": 8, "jumps": 0, "last_switch": False, "yoy": 81.5, "b1": 3.8557e12, "last": 6.9998e12, "to": "2026-06", "last_method": "표·합계"}
    f = W.backlog_facts(tr, 2, rev_fact(23.6, "2026Q2"))
    assert f["btb"]["v"] == pytest.approx(1.552, abs=1e-3) and f["blog_gap"]["v"] == pytest.approx(57.9) and f["btb"]["ok"]
    bad = W.backlog_facts(dict(tr, last_switch=True), 2, rev_fact(23.6, "2026Q2"))
    assert not bad["btb"]["ok"]
    land = {"v": 10, "sig": "20260814003088:68:2026-10-15:10", "decide": {"pct": 96.55, "date": "20261015"}, "band": {"n": 58}}
    assert W.per_facts(land, 10, "20260814003088")["per_pct"]["ok"]
    assert not W.per_facts(land, 10, "20261114000001")["per_pct"]["ok"]  # 판이 새 보고서보다 옛것
    assert W.per_facts(land, 11) == {} and W.per_facts({"v": 10, "error": "x"}, 10) == {}


def test_backlog_quarter_mismatch_holds_then_one_new():
    hy = [{"id": "g1", "tpl": "blog_gap"}]
    tr = lambda to, yoy: {"n": 8, "jumps": 0, "last_switch": False, "yoy": yoy, "b1": 1e12, "last": 1.1e12, "to": to, "last_method": "표·합계"}  # noqa: E731
    st, _ = W.step(None, W.backlog_facts(tr("2026-06", 12.0), 2, rev_fact(20.0, "2026Q2")), hy, "d0")
    assert st["hyp"]["g1"] == "ok"
    # 잔고는 3분기로 갔는데 매출(가속도)은 아직 2분기 — 어긋난 분기끼리 빼지 않는다
    f1 = W.backlog_facts(tr("2026-09", 0.0), 2, rev_fact(20.0, "2026Q2"))
    assert not f1["blog_gap"]["ok"] and "분기가 다름" in f1["blog_gap"]["why"]
    st, ev = W.step(st, f1, hy, "d1")
    assert not [e for e in ev if e["kind"] == "hyp"] and st["hyp"]["g1"] == "ok"
    # 다음 날 가속도가 따라옴 — 새 분기 한 번만 따진다(−2 → 지킴, 알림 없음)
    st, ev = W.step(st, W.backlog_facts(tr("2026-09", 0.0), 2, rev_fact(2.0, "2026Q3", as_of="008106")), hy, "d2")
    assert not [e for e in ev if e["kind"] == "hyp"] and st["hyp"]["g1"] == "ok"


def test_backlog_derived_rebase_when_druck_version_changes():
    hy = [{"id": "g1", "tpl": "blog_gap"}]
    tr = {"n": 8, "jumps": 0, "last_switch": False, "yoy": 0.0, "b1": 1e12, "last": 1e12, "to": "2026-06", "last_method": "표·합계"}
    st, _ = W.step(None, W.backlog_facts(tr, 2, rev_fact(10.0, "2026Q2")), hy, "d0")
    st, ev = W.step(st, W.backlog_facts(tr, 2, rev_fact(30.0, "2026Q2", ver="d5.rev")), hy, "d1")
    assert ev == [] and st["hyp"]["g1"] == "broken"                       # 식 버전이 바뀐 다시 계산 — 조용히 다시 기준


def test_threshold_change_resets_judgement():
    d = W.empty()
    d, e = W.apply(d, "add", {"code": "005930", "hyps": [{"tpl": "per_zone"}]}, "2026-10-17", "t")
    h = e["hyps"][0]
    d["state"]["005930"] = {"good": {"per_pct": W.F(72.0, "20261015", "l10")}, "hyp": {h["id"]: "ok"}, "log": []}
    d2, _ = W.apply(d, "update", {"id": e["id"], "hyps": [{"id": h["id"], "tpl": "per_zone", "th": 60}]}, "2026-10-17", "t")
    assert h["id"] not in d2["state"]["005930"]["hyp"]                    # 옛 판정을 지운다 — 다음 판에서 지금 값으로 앞 판정 없이
    d3, _ = W.apply(d, "update", {"id": e["id"], "hyps": [{"id": h["id"], "tpl": "per_zone", "th": 75.0}]}, "2026-10-17", "t")
    assert d3["state"]["005930"]["hyp"][h["id"]] == "ok"                  # 문턱이 그대로면 판정도 그대로


def test_apply_add_update_close_delete_and_validation():
    d = W.empty()
    d, e = W.apply(d, "add", {"code": "005930", "why": "HBM", "hyps": [{"tpl": "per_zone", "th": 70}]}, "2026-10-17", "t", lambda c: "삼성전자")
    assert e["name"] == "삼성전자" and e["hyps"][0]["th"] == 70
    with pytest.raises(ValueError):
        W.apply(d, "add", {"code": "005930"}, "2026-10-17", "t")
    with pytest.raises(ValueError):
        W.apply(d, "add", {"code": "12345"}, "2026-10-17", "t")
    with pytest.raises(ValueError):
        W.apply(d, "add", {"code": "000660", "hyps": [{"tpl": "nope"}]}, "2026-10-17", "t")
    with pytest.raises(ValueError):
        W.apply(d, "add", {"code": "000660", "hyps": [{"tpl": "per_zone", "th": "abc"}]}, "2026-10-17", "t")
    d2, _ = W.apply(d, "update", {"id": e["id"], "hyps": [{"tpl": "btb"}]}, "2026-10-17", "t")
    assert d2["entries"][0]["hyps"][0]["tpl"] == "btb" and d["entries"][0]["hyps"][0]["tpl"] == "per_zone"   # 입력은 그대로
    d3, _ = W.apply(d2, "close", {"id": e["id"], "why": "가설 깨짐"}, "2026-10-18", "t")
    assert d3["entries"][0]["closed"]["date"] == "2026-10-18"
    d4, _ = W.apply(d3, "delete", {"id": e["id"]}, "2026-10-18", "t")
    assert d4["entries"] == []


def test_run_all_inbox_and_failing_reader():
    d = W.empty()
    d, a = W.apply(d, "add", {"code": "005930", "hyps": [{"tpl": "accel_pos"}]}, "2026-10-17", "t")
    d, b = W.apply(d, "add", {"code": "000660"}, "2026-10-17", "t")
    seq = {"005930": [facts_q(10, 4.0, "확장 가속"), facts_q(11, -5.0, "둔화")]}

    def reader(code):
        if code == "000660":
            raise RuntimeError("깨진 캐시")
        return seq[code].pop(0)
    d, ev = W.run_all(d, reader, "2026-10-17")
    assert ev == [] and d["state"]["000660"]["err"].startswith("RuntimeError")
    d, ev = W.run_all(d, reader, "2026-10-18")
    assert {e["kind"] for e in ev} == {"quarter", "hyp"}
    assert len(d["inbox"]) == 2 and all(not m["seen"] for m in d["inbox"])
    d, _ = W.apply(d, "seen_all", {}, "2026-10-18", "t")
    assert all(m["seen"] for m in d["inbox"])


def test_save_load_roundtrip_backup_and_corrupt(tmp_path):
    p = str(tmp_path / "개인" / "관심장부.json")
    d, _ = W.apply(W.empty(), "add", {"code": "005930"}, "2026-10-17", "t")
    W.save(p, d, "2026-10-17")
    assert W.load(p)["entries"][0]["code"] == "005930"
    W.save(p, d, "2026-10-18")
    assert os.path.exists(os.path.join(os.path.dirname(p), "backup", "관심장부_20261018.json"))
    open(p, "w", encoding="utf-8").write("{깨짐")
    with pytest.raises(ValueError):
        W.load(p)
    with pytest.raises(ValueError):
        W.save(p, d, "2026-10-19")
    assert open(p, encoding="utf-8").read() == "{깨짐"                      # 깨진 파일은 덮어쓰지 않는다
