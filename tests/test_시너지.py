# -*- coding: utf-8 -*-
"""시너지 점수 식(2026-10-14 v2) — 전환 적자 None · 결측 50 · 확인 가중 0 · 싼 수주 필터 · per_pct_at.
스펙 docs/superpowers/specs/2026-10-14-synergy-value-design.md 1절(문턱)."""
import os, sys, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("시너지_시험", os.path.join(BASE, "시너지.py"))
SYN = ilu.module_from_spec(_sp); _sp.loader.exec_module(SYN)


def _row(code, btb=1.2, cov=0.2, m4=5.0, gap=20.0, new_pct=None, lead=20.0, per_pct=30.0, flags=None):
    return {"code": code, "reliable": True, "btb": btb, "cover_chg": cov, "margin4": m4, "gap": gap,
            "new_pct": new_pct, "flags": flags or [], "lead": lead, "per_pct": per_pct,
            "loss4": m4 is not None and m4 <= 0, "stage": "잠복"}


def test_weights_confirm_is_zero():
    assert SYN.WEIGHTS == {"선행": .35, "전환": .25, "확인": 0.0, "가격": .25}


def test_loss_company_gets_neutral_transition_not_top():
    rows = [_row("A", m4=12.0), _row("B", m4=4.0), _row("C", m4=1.0), _row("L", m4=-10.0)]
    SYN.score(rows)
    by = {r["code"]: r for r in rows}
    assert by["L"]["parts"]["전환"] is None                      # 적자 = 해당 없음
    assert by["C"]["parts"]["전환"] > by["A"]["parts"]["전환"]  # 흑자끼리는 낮을수록 높다
    # 적자는 50 대입 — 흑자 셋의 가운데와 같은 자리, 최상위 아님
    assert by["L"]["score"] < by["C"]["score"] and by["L"]["score"] > by["A"]["score"]
    assert by["L"]["score"] == by["B"]["score"]                  # 흑자 중앙(B 50)과 같은 자리


def test_missing_parts_substitute_50_not_renormalize():
    a, b = _row("A", gap=None), _row("B", gap=None, m4=None)
    rows = [a, b, _row("C"), _row("D", gap=-30.0, m4=20.0)]
    SYN.score(rows)
    for r in rows:
        assert r["score"] is not None
    # 가격이 None 인 행은 가격 50 — 선행이 같은 행끼리 비교하면 가격 높은 C 보다 낮고 가격 낮은 D 보다 높다
    sc = {r["code"]: r["score"] for r in rows}
    assert sc["C"] > sc["A"] > sc["D"]
    assert a["parts"]["가격"] is None and b["parts"]["전환"] is None  # parts 엔 결측 그대로(50 은 점수 계산에서만)


def test_no_leading_part_means_no_score():
    r = _row("X", btb=None, cov=None)
    y = _row("Y")
    SYN.score([r, y, _row("Z", btb=1.5, cov=0.4)])
    assert r["score"] is None and r["parts"].get("선행") is None
    assert y["score"] is not None                                # 선행이 있는 행은 점수가 선다


def test_confirm_part_is_shown_but_has_no_weight():
    a, a2, b = _row("A", new_pct=50.0), _row("A2", new_pct=10.0), _row("B", new_pct=None)
    SYN.score([a, a2, b])
    assert a["parts"]["확인"] is not None and a2["parts"]["확인"] is not None
    assert a["parts"]["확인"] > a2["parts"]["확인"]
    assert b["parts"]["확인"] is None                            # 공시 없음 = 해당 없음(0점 아님)
    assert a["score"] == a2["score"] == b["score"]               # 가중 0 — 점수는 같다


def test_unreliable_row_has_no_score():
    r = dict(_row("U"), reliable=False)
    SYN.score([r, _row("A"), _row("B", btb=1.5)])
    assert r["score"] is None and r["parts"] == {}


def test_flags_still_penalize():
    a, b = _row("A"), _row("B", flags=["유상증자"])
    SYN.score([a, b, _row("C", btb=1.5)])
    assert a["score"] - b["score"] == 10


def test_cheap_filter_and_rec_pass_keys():
    rc = next(x for x in SYN.SYN_REC if x["id"] == "cheap")
    assert SYN.SYN_REC[0]["id"] == "cheap" and rc["f"] == {"stages": SYN._NOT_SLOW, "btbMin": 1.1, "leadMin": 15, "perPctMax": 50}
    assert SYN.rec_pass(_row("A"), rc["f"])
    assert not SYN.rec_pass(_row("A", per_pct=None), rc["f"])      # PER 없음 = 통과 못 함
    assert not SYN.rec_pass(_row("A", per_pct=51.0), rc["f"])
    assert SYN.rec_pass(_row("A", per_pct=50.0), rc["f"])          # 경계 포함
    assert not SYN.rec_pass(_row("A", lead=14.9), rc["f"])
    assert SYN.rec_pass(_row("A", lead=15.0), rc["f"])
    assert not SYN.rec_pass(_row("A", lead=None), rc["f"])         # lead 없음 = 통과 못 함
    assert not SYN.rec_pass(_row("A", btb=1.05), rc["f"])
    assert not SYN.rec_pass(dict(_row("A"), stage="둔화"), rc["f"])


def test_rec_pass_new_keys_are_optional():
    """leadMin · perPctMax 가 없는 예전 필터는 lead · per_pct 가 없어도 통과한다."""
    rc = next(x for x in SYN.SYN_REC if x["id"] == "noslow")
    r = _row("A", lead=None, per_pct=None)
    assert SYN.rec_pass(r, rc["f"])
    assert SYN.rec_pass(r, {"leadMin": "", "perPctMax": ""})       # 화면이 빈 칸을 보낼 때


def test_per_pct_at_uses_only_filed_rows():
    e = [("20240515", 20.0), ("20240814", 60.0), ("20241114", 90.0)]
    assert SYN.per_pct_at(e, "20240601") == 20.0
    assert SYN.per_pct_at(e, "20240814") == 60.0
    assert SYN.per_pct_at(e, "20240101") is None
    assert SYN.per_pct_at(e + [("20250101", 5.0)], "20240901") == 60.0       # 미래 줄은 안 본다
    assert SYN.per_pct_at([], "20240901") is None
    assert SYN.per_pct_at([("20240814", 60.0), ("20240515", 20.0)], "20240601") == 20.0  # 순서 무관


def test_gap_clips_both_sides():
    """반영 갭 = min(잔고 1년, 300) − min(주가 1년, 300) — 주가 쪽도 자른다(백테스트 row_at · 서버 _syn_row 공통)."""
    assert SYN.gap_of(544.0, 137.0) == 300.0 - 137.0
    assert SYN.gap_of(20.0, 337.0) == 20.0 - 300.0        # 1년 주가 +337% 는 300 으로
    assert SYN.gap_of(50.0, -20.0) == 70.0
    assert SYN.gap_of(None, 10.0) is None and SYN.gap_of(10.0, None) is None


def test_lead_is_backlog_minus_rev4():
    assert SYN.lead_of(40.0, 10.0) == 30.0
    assert SYN.lead_of(40.0, None) is None and SYN.lead_of(None, 10.0) is None
