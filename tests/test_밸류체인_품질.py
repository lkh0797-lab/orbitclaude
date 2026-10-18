# -*- coding: utf-8 -*-
"""밸류체인 '누구냐' 판정 · 표 줄 거르기 회귀 시험(2026-10-19 리뷰). 순수 함수만 — 캐시 · 서버 없이."""
import os, sys, datetime as dt, importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _load(name, file):
    sp = ilu.spec_from_file_location(name, os.path.join(BASE, file))
    m = ilu.module_from_spec(sp); sp.loader.exec_module(m)
    return m


V = _load("밸류체인_지도_품질", "밸류체인_지도.py")
X = _load("제품믹스_품질", "제품믹스.py")


def P(item, pct=None, amt=None, seg=None, use=None, kind=None):
    return {"item": item, "pct": pct, "amt": amt, "segment": seg, "use": use, "kind": kind}


def test_spaced_adjustment_and_total_rows_are_not_products():
    # 엘에스일렉트릭 꼴 — IT 부문의 띄어 쓴 '연 결 조 정' 줄이 제품으로 들어가 IT 22.4% 로 보였다
    rows = [P("전력기기", 81.8, seg="전력"), P("동관", 9.1, seg="금속"), P("PLC", 7.1, seg="자동화"), P("IT서비스", 2.0, seg="IT"),
            P("연 결 조 정", 20.4, seg="IT"), P("총 매 출 액", 200.0), P("내부매출액", 5.0, seg="자동차"), P("영업이익", 9.0)]
    got = V.products_of(rows)
    items = [x["item"] for x in got]
    assert "연 결 조 정" not in items and "총 매 출 액" not in items and "내부매출액" not in items and "영업이익" not in items
    it = next(x for x in got if x["item"] == "IT서비스")
    assert it["pct"] == 2.0 and max(x["pct"] for x in got) <= 100
    assert all(not V.is_sum_row(p) for p in V.big_lines(rows))
    assert X.is_adj(P("연 결 조 정")) and not X.is_adj(P("공기제거기")) and not X.is_adj(P("가상계좌, 펌뱅킹"))


def test_amount_share_one_basis_and_main_line_kept():
    # LS 꼴 — 주력 줄만 비중이 비고 금액은 다 있다: 모두 금액 몫(한 기준)으로, 띄어 쓴 조정 줄은 분모에서 빠진다
    rows = [P("전력기기", None, amt=8180), P("동관", 12.3, amt=910), P("PLC", 9.6, amt=710), P("IT서비스", 2.8, amt=200), P("연 결 조 정", 20.0, amt=2000)]
    got = {x["item"]: x["pct"] for x in V.products_of(rows)}
    assert got["전력기기"] == 81.8 and got["IT서비스"] == 2.0 and "연 결 조 정" not in got
    keep = {x["item"]: x["pct"] for x in V.products_of([P("A", 70.0), P("B", 30.0), P("C", None)])}   # 금액이 없으면 표 비중 그대로
    assert keep["A"] == 70.0 and keep["C"] is None


def test_self_words_from_name():
    assert "중공업" in V.self_words("효성중공업")
    sw = V.self_words("엘에스일렉트릭", ["ls", "electric"])
    assert {"ls", "electric", "일렉트릭"} <= sw
    assert "광통신" not in V.self_words("대한광통신")                                # 업종을 말하는 꼬리는 남긴다


def test_story_words_drop_self_tokens():
    def hot(items, since, name, links, top=80, code=""):
        return [{"w": w, "n": 5} for w in ("LS", "ELECTRIC", "배전반", "중공업", "데이터센터", "LS의")]
    rows = [{"date": "2026-10-10", "title": "LS ELECTRIC 배전반 데이터센터", "lines": []}]
    got = [x["w"] for x in V.story_words(rows, "2026-07-01", "엘에스일렉트릭", hot, top=10, drop=V.self_words("엘에스일렉트릭", ["ls", "electric"]))]
    assert "LS" not in got and "ELECTRIC" not in got and "LS의" not in got and "배전반" in got and "데이터센터" in got


def test_contract_trigger_splits_affiliate_contracts():
    today = dt.date(2026, 10, 19)
    discs = [{"d": "20261010", "rcept": "r1", "title": "단일판매ㆍ공급계약체결"}, {"d": "20260901", "rcept": "r2", "title": "단일판매ㆍ공급계약체결"}]
    contracts = {"r1": {"amount": 1.0e12, "pct": 20.0, "party": "LS ELECTRIC AMERICA Inc."}, "r2": {"amount": 2.0e11, "pct": 4.0, "party": "한국전력공사"}}
    out = V.disc_triggers(discs, contracts, None, today, own=lambda p: "AMERICA" in p)
    assert "그중 계열 법인 경유 1건" in out[0]["text"]
    plain = V.disc_triggers(discs, contracts, None, today)
    assert "계열" not in plain[0]["text"]


def test_up_groups_skip_self_supplier_and_mark_group():
    mats = [{"item": "세라믹Assy", "segment": "전력", "pct": 50, "amt": 10, "suppliers": [{"name": "엘에스일렉트릭"}, {"name": "무석러현전자"}]},
            {"item": "전기동", "segment": "금속", "pct": 90, "amt": 100, "suppliers": [{"name": "엘에스엠앤엠"}]}]
    link = {"엘에스일렉트릭": "010120", "엘에스엠앤엠": "999999"}.get
    out = V.up_groups(mats, [], link, lead_name="엘에스일렉트릭", lead_code="010120", grp={"999999"})
    names = [sp["name"] for g in out for it in g["items"] for sp in it["sup"]]
    assert "엘에스일렉트릭" not in names and "무석러현전자" in names
    grp = [sp for g in out for it in g["items"] for sp in it["sup"] if sp["name"] == "엘에스엠앤엠"]
    assert grp and grp[0].get("grp")
