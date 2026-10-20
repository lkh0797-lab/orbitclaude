# -*- coding: utf-8 -*-
"""시너지 점수 식(2026-10-20 v3) — 수주 · 값 · 여지 ⅓씩 − 위험 표지 10 · 여지 적자 None · 결측 50 · 해석 1~2줄 · 싼 수주 필터 · per_pct_at.
스펙 docs/superpowers/specs/2026-10-20-synergy-score-v3-design.md 1 · 3절(v2 문턱은 2026-10-14 스펙)."""
import os, sys, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("시너지_시험", os.path.join(BASE, "시너지.py"))
SYN = ilu.module_from_spec(_sp); _sp.loader.exec_module(SYN)


def _row(code, btb=1.2, cov=0.2, m4=5.0, gap=20.0, new_pct=None, lead=20.0, per_pct=30.0, flags=None):
    return {"code": code, "reliable": True, "btb": btb, "cover_chg": cov, "margin4": m4, "gap": gap,
            "new_pct": new_pct, "flags": flags or [], "lead": lead, "per_pct": per_pct,
            "loss4": m4 is not None and m4 <= 0, "stage": "잠복"}


def test_weights_three_equal_parts():
    assert set(SYN.WEIGHTS) == {"수주", "값", "여지"} and all(abs(w - 1 / 3) < 1e-12 for w in SYN.WEIGHTS.values())
    assert [p["key"] for p in SYN.PARTS] == ["수주", "값", "여지"] and SYN.RISK_PEN == 10


def test_loss_company_gets_neutral_room_not_top():
    rows = [_row("A", m4=12.0), _row("B", m4=4.0), _row("C", m4=1.0), _row("L", m4=-10.0)]
    SYN.score(rows)
    by = {r["code"]: r for r in rows}
    assert by["L"]["parts"]["여지"] is None                      # 적자 = 해당 없음
    assert by["C"]["parts"]["여지"] > by["A"]["parts"]["여지"]  # 흑자끼리는 낮을수록 높다
    # 적자는 50 대입 — 흑자 셋의 가운데와 같은 자리, 최상위 아님
    assert by["L"]["score"] < by["C"]["score"] and by["L"]["score"] > by["A"]["score"]
    assert by["L"]["score"] == by["B"]["score"]                  # 흑자 중앙(B 50)과 같은 자리


def test_net_loss_with_tiny_operating_profit_is_not_room():
    """순손실 · 영업 미세 흑자(코스모화학 op +14억 · ni −249억 — 2026-10-15 리뷰)는 여지 '해당 없음'(None → 50).
    기준 = loss4(영업 또는 순이익 4분기 합 ≤ 0) — 흑자(둘 다 > 0)만 백분위."""
    rows = [_row("A", m4=12.0), _row("B", m4=4.0), _row("C", m4=1.0),
            dict(_row("N", m4=0.5), loss4=True)]            # 영업이익률 +0.5% · 순손실 → loss4 True
    SYN.score(rows)
    by = {r["code"]: r for r in rows}
    assert by["N"]["parts"]["여지"] is None
    assert by["N"]["score"] == by["B"]["score"]
    assert by["C"]["parts"]["여지"] == 83 and by["A"]["parts"]["여지"] == 17
    rows = [{k: v for k, v in _row(c, m4=m).items() if k != "loss4"} for c, m in (("A", 12.0), ("B", 4.0), ("P", 0.5), ("L", -1.0))]
    SYN.score(rows)
    by = {r["code"]: r for r in rows}
    assert by["P"]["parts"]["여지"] == 83 and by["L"]["parts"]["여지"] is None


def test_value_part_is_cheapness_vs_own_history():
    """값 = 100 − PER 자기 역사 % 의 백분위 — 자기 과거보다 쌀수록(per_pct 낮을수록) 높다. 없으면 None(점수에선 50)."""
    rows = [_row("C", per_pct=10.0), _row("M", per_pct=50.0), _row("X", per_pct=90.0), _row("N", per_pct=None)]
    SYN.score(rows)
    by = {r["code"]: r for r in rows}
    assert by["C"]["parts"]["값"] == 83 and by["M"]["parts"]["값"] == 50 and by["X"]["parts"]["값"] == 17
    assert by["N"]["parts"]["값"] is None
    assert by["C"]["score"] > by["M"]["score"] == by["N"]["score"] > by["X"]["score"]


def test_missing_parts_substitute_50_not_renormalize():
    a, b = _row("A", per_pct=None), _row("B", per_pct=None, m4=None)
    rows = [a, b, _row("C", per_pct=10.0), _row("D", per_pct=90.0, m4=20.0)]
    SYN.score(rows)
    for r in rows:
        assert r["score"] is not None
    sc = {r["code"]: r["score"] for r in rows}
    assert sc["C"] > sc["A"] > sc["D"]
    assert a["parts"]["값"] is None and b["parts"]["여지"] is None  # parts 엔 결측 그대로(50 은 점수 계산에서만)


def test_no_backlog_part_means_no_score():
    r = _row("X", btb=None, cov=None)
    y = _row("Y")
    SYN.score([r, y, _row("Z", btb=1.5, cov=0.4)])
    assert r["score"] is None and r["parts"].get("수주") is None
    assert y["score"] is not None


def test_gap_and_new_contracts_no_longer_move_the_score():
    """v3 는 가격(반영 갭) · 확인(수주 공시)을 뺐다 — 둘이 달라도 점수가 같다(열 · 펼친 행에 정보로만)."""
    a, b = _row("A", gap=300.0, new_pct=80.0), _row("B", gap=-300.0, new_pct=None)
    SYN.score([a, b, _row("C", btb=1.5)])
    assert a["score"] == b["score"] and set(a["parts"]) == {"수주", "값", "여지"}


def test_unreliable_row_has_no_score():
    r = dict(_row("U"), reliable=False)
    SYN.score([r, _row("A"), _row("B", btb=1.5)])
    assert r["score"] is None and r["parts"] == {}


def test_risk_flags_penalize_ten_each():
    a = _row("A")
    b = _row("B", flags=SYN.risk_flags({"CB발행": 1}))
    c = _row("C", flags=SYN.risk_flags({"유상증자": {"n": 2, "last": "20260812"}, "횡령배임": {"n": 1, "last": "20260101"}}))
    SYN.score([a, b, c, _row("D", btb=1.5)])
    assert a["score"] - b["score"] == 10 and a["score"] - c["score"] == 20


def test_risk_flags_kinds_and_format():
    assert SYN.risk_flags({}) == [] and SYN.risk_flags(None) == []
    assert SYN.risk_flags({"CB발행": 0, "현금배당": 3, "최대주주변경": 2}) == []          # 0 · 다른 범주는 표지 아님
    f = SYN.risk_flags({"CB발행": {"n": 1, "last": "20260301"}, "유상증자": {"n": 1, "last": "20260812"}})
    assert f == ["희석 — CB 발행 · 유상증자 (12개월, 마지막 2026-08-12)"]
    f = SYN.risk_flags({"감사의견비적정": 1, "EB발행": 2})
    assert f == ["희석 — EB 발행 (12개월)", "부실 — 감사의견 비적정 (12개월)"]


def test_explain_two_lines_with_real_numbers():
    rows = [dict(_row("A", btb=2.3, cov=0.6, m4=3.1, per_pct=55.0), cover=1.8),
            dict(_row("B", btb=1.0, cov=0.0, m4=12.0, per_pct=20.0), cover=1.0),
            dict(_row("C", btb=1.1, cov=0.1, m4=None, per_pct=None), cover=0.9, loss4=True),
            dict(_row("D", btb=1.5, cov=0.3, m4=6.0, per_pct=80.0, flags=SYN.risk_flags({"CB발행": 1})), cover=1.2, stage="반영", stage_why="주가가 수주보다 앞서 갔다")]
    SYN.score(rows)
    by = {r["code"]: r for r in rows}
    a = SYN.explain(by["A"])
    assert len(a) == 2 and a[0].startswith("점수 %d = (수주 " % round(by["A"]["score"]))
    assert "강점: 수주" in a[0] and "매출의 2.3배" in a[0] and "1.8년치(1년 새 +0.6년)" in a[0]
    b = SYN.explain(by["B"])
    assert "강점: 값" in b[0] and "자기 과거 20% 자리 — 과거보다 싸다" in b[0] and b[1].startswith("약점: 수주")
    c = SYN.explain(by["C"])
    assert "값 50 · 여지 50" in c[0]                                       # 빈 부분은 50 으로 셈 — 줄 머리 산수가 맞는다
    assert "PER 자기 역사 없음" in c[1] and "4분기 적자 — 50 으로 셈" in c[1]
    d = SYN.explain(by["D"])
    assert "− 위험 10" in d[0] and "위험 희석 −10(CB 발행)" in d[1] and "반영 단계" in d[1] and "과거보다 비싸다" in d[1]
    assert SYN.explain({"reliable": False, "why_not": "검산 부족"}) == ["점수 없음 — 검산 부족. 순위 밖이다."]
    assert SYN.explain(dict(_row("N"), score=None, parts={}))[0].startswith("점수 없음")


def test_rec_safe_filter_checks_risk_flags():
    rc = next(x for x in SYN.SYN_REC if x["id"] == "safe")
    assert SYN.rec_pass(_row("A"), rc["f"])
    assert not SYN.rec_pass(_row("A", flags=SYN.risk_flags({"CB발행": 1})), rc["f"])


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


def test_date_pct_ranks_within_each_date_and_drops_small_dates():
    """상⅓−하⅓ 컷은 날짜 안에서(2026-10-15 리뷰 재현): 날짜 A 요인 1..30 수익 0 · 날짜 B 요인 101..130 수익 +10 —
    pooled 컷이면 상⅓(전부 B) − 하⅓(전부 A) = +10 이지만, 날짜 안 분위면 두 날짜가 상·하에 반반 들어 0 이다."""
    import statistics as st
    rows = [{"t": "20150131", "_s": float(i), "y": 0.0} for i in range(1, 31)] + \
           [{"t": "20230131", "_s": float(100 + i), "y": 10.0} for i in range(1, 31)] + \
           [{"t": "20240131", "_s": 1.0 + i, "y": 99.0} for i in range(5)] + [{"t": "20240229", "_s": None, "y": 1.0}]
    out = SYN.date_pct(rows, "_s", "t")
    assert len(out) == 60                                       # 5행뿐인 날짜 · 값 None 행은 뺀다
    for t in ("20150131", "20230131"):
        g = [r for r in out if r["t"] == t]
        assert len(g) == 30 and 0 < min(r["_s"] for r in g) and max(r["_s"] for r in g) < 100
    top = [r["y"] for r in out if r["_s"] >= 200 / 3]
    bot = [r["y"] for r in out if r["_s"] < 100 / 3]
    assert len(top) == len(bot) == 20
    assert st.median(top) - st.median(bot) == 0                 # pooled 였다면 +10
    # 동률은 가운데 백분위(_pct_rank 와 같다)
    g = SYN.date_pct([{"t": "x", "_s": 1.0} for _ in range(3)] + [{"t": "x", "_s": 2.0} for _ in range(3)], "_s", "t")
    assert sorted({r["_s"] for r in g}) == [25.0, 75.0]


def _qrow(**kw):
    r = {"backlog_yoy": 40.0, "btb": 1.2, "cover": 0.5, "price_1y": 10.0, "dd52": -5.0, "margin_delta": 1.0, "rev_accel": 1.0,
         "per": None, "per_filed": 13.4, "loss4": False, "parties_listed": [], "customer_of": [], "same_as": [], "stage": "잠복"}
    r.update(kw)
    return r


def test_questions_loss_uses_loss4_not_per():
    """풍경 PER 이 없는(per None) 흑자 회사에 '적자' 질문이 붙지 않는다(2026-10-15 리뷰 — 한화오션 등 18곳 회귀)."""
    assert not any("적자인데" in x for x in SYN.questions(_qrow(), []))
    assert any("적자인데" in x for x in SYN.questions(_qrow(loss4=True), []))
    assert not any("적자인데" in x for x in SYN.questions(_qrow(loss4=True, backlog_yoy=10.0), []))   # 잔고 +20% 미만
    assert not any("적자인데" in x for x in SYN.questions(_qrow(per=0.0, loss4=False), []))          # per 로 읽지 않는다
    assert not any("적자인데" in x for x in SYN.questions(_qrow(per=50.0, loss4=False), []))


def _rrow(**kw):
    r = {"backlog_yoy": 20.0, "backlog": 5.0e10, "cover": 0.5, "btb": 1.2, "rev_accel": None, "rev_yoy": None, "margin_delta": None,
         "new_contracts": [], "new_pct": None, "price_1y": 337.0, "per_filed": 10.0, "per": 12.0, "flags": [], "same_as": []}
    r.update(kw)
    r["gap"] = SYN.gap_of(r["backlog_yoy"], r["price_1y"])
    return r


def test_reasons_gap_note_names_each_clipped_side():
    """반영 갭 문장의 '300%로 잘라 계산' 각주는 잘린 쪽을 다 적는다 — 주가 쪽만 잘려도(2026-10-15 리뷰)."""
    s = next(x for x in SYN.reasons(_rrow()) if "반영 갭" in x)
    assert "-280%p" in s and "(주가 1년은 300%로 잘라 계산)" in s
    s = next(x for x in SYN.reasons(_rrow(backlog_yoy=544.0, price_1y=137.0)) if "반영 갭" in x)
    assert "(잔고 증가율은 300%로 잘라 계산)" in s
    s = next(x for x in SYN.reasons(_rrow(backlog_yoy=400.0, price_1y=350.0)) if "반영 갭" in x)
    assert "(잔고 증가율 · 주가 1년은 300%로 잘라 계산)" in s and "+0%p" in s
    s = next(x for x in SYN.reasons(_rrow(backlog_yoy=50.0, price_1y=20.0)) if "반영 갭" in x)
    assert "300%" not in s and "+30%p" in s


def test_explain_warns_slowdown_stage():
    """점수는 단계를 안 본다 — 둔화(잔고 감소) 회사가 값 · 여지로 높은 점수를 받아도 해석 둘째 줄이 둔화를 적는다."""
    rows = [dict(_row("S", btb=0.8, cov=-0.2, m4=2.0, per_pct=5.0), cover=0.8, stage="둔화"), _row("A"), _row("B", btb=1.6)]
    SYN.score(rows)
    w = SYN.explain(rows[0])
    assert "둔화 단계" in w[1]
