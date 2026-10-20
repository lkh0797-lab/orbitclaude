# -*- coding: utf-8 -*-
"""꿰미.py — 구슬 함수 · 문턱이 그 탭과 같음 · K 와 순위 · 해석 줄 (2026-10-20)."""
import os
import re
import sys
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _load(name):
    sp = ilu.spec_from_file_location(name, os.path.join(BASE, name + ".py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


KM = _load("꿰미")
TOP = _load("탑픽")


def _src(rel):
    with open(os.path.join(BASE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def test_thresholds_match_their_tabs():
    """문턱은 그 탭 것 그대로 — 탑픽 TH · 서버 VAL_* · 엇갈림 백테스트 M_TH/P_TH · 궤도 ORBIT_TIERS · 저평가 DRISK_RED."""
    assert KM.TH["op_yoy"] == TOP.TH["op_yoy"] and KM.TH["rev_yoy"] == TOP.TH["rev_yoy"]
    srv = _src("서버.py")
    assert re.search(r"^VAL_DD = -25\b", srv, re.M) and KM.TH["dd"] == -25
    assert re.search(r"^VAL_NI = -5\b", srv, re.M) and KM.TH["ni"] == -5
    assert re.search(r"^VAL_MIN = 50\b", srv, re.M) and KM.TH["score"] == 50
    assert re.search(r'ORBIT_TIERS = \[\(2\.0, "격변"\), \(1\.5, "큼"\)', srv) and KM.TH["text_x"] == 1.5
    assert re.search(r'DRISK_RED = \{?[^\n]*"상폐 절차"', srv) and set(KM.RISK_RED) == {"상폐 절차", "보고서 없음", "작전주 꼴"}
    gap = _src(os.path.join("도구", "엇갈림_백테스트.py"))
    assert re.search(r"^M_TH, P_TH = 0\.5, 5\.0", gap, re.M) and (KM.TH["gap_m"], KM.TH["gap_p"]) == (0.5, 5.0)
    assert abs(KM.TH["su"] - 200 / 3) < 1e-9


def test_bead_kinds_and_order():
    assert [b["key"] for b in KM.BEADS] == ["exp", "su", "earn", "text", "gap", "val", "dip", "chain", "chart", "rep"]
    assert KM.BASE_KEYS == ["su", "gap", "val", "dip", "chain"] and KM.REF_KEYS == ["exp", "earn", "text", "chart", "rep"]
    assert all(b["rule"] and b["ev"] and b["tab"] for b in KM.BEADS)


def test_unknown_is_never_on():
    assert KM.bead_su(None) == {"on": False, "known": False, "stage": None}
    assert KM.bead_su({"reliable": False, "p_su": 90, "stage": "점화"})["known"] is False
    assert not KM.bead_val({"per": -3.0, "pct": 10.0})["known"]            # 적자
    assert not KM.bead_val({"per": 9.0, "pct": 10.0, "n": 5})["known"]     # 표본 8분기 미만
    assert not KM.bead_gap({"dm": None, "dp": -10})["known"]
    assert not KM.bead_chain({"custs": [{"code": "005930", "pct": 4.0, "p3": 99}]})["known"]     # 비중 10% 미만
    assert not KM.bead_rep({"up": 50, "n": 3})["known"]                    # 안 데워짐
    assert not KM.bead_earn({"A": True, "fin": True})["known"]             # 금융은 탑픽 적격 밖


def test_each_bead_threshold_edge():
    assert KM.bead_su({"reliable": True, "p_su": 66.7, "stage": "잠복"})["on"] and not KM.bead_su({"reliable": True, "p_su": 66.6, "stage": "잠복"})["on"]
    assert not KM.bead_su({"reliable": True, "p_su": 90, "stage": "둔화"})["on"]
    assert KM.bead_val({"per": 9.0, "pct": 30.0, "n": 12})["on"] and not KM.bead_val({"per": 9.0, "pct": 30.1, "n": 12})["on"]
    assert KM.gap_of(0.5, -5) == "blue" and KM.gap_of(0.4, -5) is None and KM.gap_of(-0.5, 5) == "magenta" and KM.gap_of(0.5, 5) is None
    assert KM.bead_gap({"dm": 1.2, "dp": -20})["on"] and not KM.bead_gap({"dm": -1.2, "dp": 20})["on"]
    assert KM.bead_dip({"tier": "저평가", "score": 61})["on"] and not KM.bead_dip({"tier": "관찰", "score": 61})["on"]
    d = KM.bead_dip(None)
    assert d["known"] and not d["on"] and d["fell"] is False
    assert KM.bead_chain({"custs": [{"code": "005930", "name": "삼성전자", "pct": 26.0, "p3": 90}]})["on"]
    assert not KM.bead_chain({"custs": [{"code": "005930", "name": "삼성전자", "pct": 26.0, "p3": 89.9}]})["on"]
    assert KM.bead_earn({"A": False, "B": True, "ttm_g": 12.0})["on"] and not KM.bead_earn({"A": False, "B": False})["on"]
    assert KM.bead_text({"x": 1.5, "tier": "큼"})["on"] and not KM.bead_text({"x": 1.49, "tier": "평소"})["on"]
    assert KM.bead_exp({"clue": True, "grade": "A", "cur": 31.0})["on"] and not KM.bead_exp({"clue": False})["on"]
    assert KM.bead_rep({"warm": True, "up": 20.0, "n": 2})["on"] and not KM.bead_rep({"warm": True, "up": 19.9, "n": 2})["on"] and not KM.bead_rep({"warm": True, "up": 40, "n": 1})["on"]
    assert KM.bead_chart({"has_journal": True, "rows": [{"pattern": "cup_with_handle", "asof": "20261020"}]})["on"] and not KM.bead_chart({"has_journal": True, "rows": []})["on"]


def _inp(**kw):
    base = {"code": "000001", "name": "가", "cap_rank": 100}
    base.update(kw)
    return base


def test_string_counts_base_and_ref_and_gates():
    s = KM.string(_inp(syn={"reliable": True, "p_su": 80, "stage": "점화", "btb": 1.9, "cover_chg": 0.4},
                       val={"per": 8.0, "pct": 12.0, "n": 20}, gap={"dm": 2.0, "dp": -15.0}, dip={"tier": "관찰", "score": 40, "dd": -30},
                       earn={"A": True, "op_yoy": 35, "rev_yoy": 8}, risk={"level": None, "flags": [], "kis": []}))
    assert s["k"] == 3 and s["k_ref"] == 1 and s["n_known"] == 4 and not s["gated"] and s["rank_key"][:3] == (False, -3, -1)
    g = KM.string(_inp(syn={"reliable": True, "p_su": 80, "stage": "둔화"}, gap={"dm": -1.0, "dp": 12.0},
                       risk={"level": "작전주 꼴", "flags": ["희석 — CB 발행 (12개월, 마지막 2026-08-12)"], "kis": ["관리종목"]}))
    assert [x["key"] for x in g["gates"]] == ["risk", "slow", "magenta"] and g["gated"] and g["k"] == 0
    assert "공시 위험 작전주 꼴" in g["gates"][0]["why"] and "희석: CB 발행" in g["gates"][0]["why"] and "증권사 상태 관리종목" in g["gates"][0]["why"]
    assert g["rank_key"][0] is True            # 가림은 맨 뒤


def test_rank_key_orders_k_then_ref_then_cap():
    a = KM.string(_inp(code="A", cap_rank=300, val={"per": 8, "pct": 10, "n": 20}, gap={"dm": 1, "dp": -10}))
    b = KM.string(_inp(code="B", cap_rank=5, val={"per": 8, "pct": 10, "n": 20}))
    c = KM.string(_inp(code="C", cap_rank=5, val={"per": 8, "pct": 10, "n": 20}, earn={"B": True}))
    d = KM.string(_inp(code="D", cap_rank=None, val={"per": 8, "pct": 10, "n": 20}, earn={"B": True}))
    assert sorted([b, a, d, c], key=lambda s: s["rank_key"]) == [a, c, d, b]


def test_explain_lines_carry_numbers_and_tab_names():
    row = _inp(syn={"reliable": True, "p_su": 72.4, "stage": "점화", "btb": 1.9, "cover_chg": 0.6}, val={"per": 9.6, "pct": 23.0, "n": 20},
               gap={"dm": 1.8, "dp": -22.0, "label": "2026Q2"}, dip={"tier": "저평가", "score": 58.2, "dd": -31.0, "ni_yoy": 12.0},
               chain={"custs": [{"code": "005930", "name": "삼성전자", "pct": 26.0, "p3": 96.0}], "year": "2026-06"},
               earn={"A": False, "B": False, "op_yoy": 4.0, "rev_yoy": 2.0, "label": "2026Q2"}, text={"x": 2.3, "tier": "격변", "label": "반기보고서", "stamp": "2026-06", "gist": "신규 수주 공시함"},
               exp=None, chart={"has_journal": True, "rows": []}, rep={"warm": True, "up": 27.0, "n": 3}, risk={}, mine={"watch": True, "n_judge": 2})
    e = dict(KM.explain(row))
    assert e["꿰미"].startswith("근거 구슬 5개 켜짐(관측 가능 5/5) · 참고 2개 · 가림 없음")
    assert e["● 수주"].startswith("수주 부분 72점(상⅓ = 67↑) — 북투빌 1.9배 · 잔고/연매출 1년 +0.6년 · 단계 점화 [호재기업]")
    assert e["● 값"] == "PER 9.6배 — 자기 과거 PER 가운데 23% 자리(30 이하 = 싸다) [풍경]"
    assert e["● 엇갈림"] == "이익률 1년 +1.8%p · 주가 1년 −22% (2026Q2) — 파랑(이익률↑ · 주가↓) [가속도]".replace("−", "-")
    assert e["● 눌림"].startswith("저평가 저평가 점수 58 · 52주 고점 대비 -31% · 순이익 1년 +12%")
    assert e["● 사슬"].startswith("고객 삼성전자(매출의 26%, 3개월 상위 4%) 가 올랐다 (2026-06 매출처 표)")
    assert e["○ 실적"].startswith("영업이익 YoY +4% · 매출 +2% — A(+20 · +5) 도 B(신고점) 도 아님 (2026Q2)")
    assert e["● 글"].startswith("2026-06 반기보고서 평소 대비 2.3× (격변) — 신규 수주 공시함")
    assert e["◌ 수출"].startswith("통관 통로 없음") and e["○ 차트"].startswith("최근 7일 스캔에 없음") and e["● 리포트"].startswith("증권사 3곳 목표가 평균 상승여력 +27%")
    assert e["내 기록"] == "관심 장부에 있다 · 판정 기록 2번"


def test_explain_gated_row_lists_gates():
    row = _inp(syn={"reliable": True, "p_su": 10, "stage": "둔화"}, gap={"dm": -2.0, "dp": 30.0}, risk={"level": "작전주 꼴"})
    e = KM.explain(row)
    keys = [k for k, _ in e]
    assert keys[0] == "꿰미" and "가림 위험" in keys and "가림 둔화" in keys and "가림 자홍" in keys
    assert dict(e)["가림 자홍"] == "이익률 1년 -2.0%p 인데 주가 1년 +30%"


def test_counts():
    rows = [{"string": KM.string(_inp(code="A", val={"per": 8, "pct": 10, "n": 20}))}, {"string": KM.string(_inp(code="B", risk={"level": "상폐 절차"}))}]
    c = KM.counts(rows)
    assert c["beads"]["val"] == {"on": 1, "known": 1} and c["beads"]["dip"]["known"] == 2 and c["gates"]["risk"] == 1 and c["k"] == {"0": 1, "1": 1}
