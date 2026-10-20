# -*- coding: utf-8 -*-
"""변화 브리핑 v12 — 감사(2026-10-21)에서 나온 문장으로 거르기 · 앵커 · 방향 · 재무 위생 · 숫자 신호 · 위치 · 묶기를 고정한다.
서버를 띄우지 않고 모듈만 읽는다(tests/test_탑픽_서버.py 와 같은 식)."""
import os
import sys
import json
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_브리핑_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp)
_sp.loader.exec_module(SRV)

# 감사 보고서(docs/superpowers/specs/2026-10-21-brief-audit-before.md)의 문장들
BOIL = [
    "개정사항은 사업결합 시 인식할 자산과 부채는 개정된 재무보고를 위한 개념체계의 자산과 부채의 정의를 참조하도록 하되, 기준서 제1037호 '충당부채, 우발부채 및 우발자산'의 적용범위에 포함되는 경우 해당 기준서를 적용하도록 하였음.",
    "④ 이익배당은 주주총회의 결의로 정한다.",
    "주요 고객에 대한 의존도가 높으며 주요고객은 다음과 같음.",
    "주1) 상기 결산배당횟수는 1991년부터 2025년까지의 횟수임.",
    "당사는 한국거래소 공시 규정에 따라 단일판매ㆍ공급계약체결 공시를 진행하였으며 계약 진행 현황은 아래와 같음.",
    "매출 10% 이상 거래처 없음.",
]
INDUSTRY = [
    "글로벌 E&M 산업 매출은 연평균(CAGR) 3.7% 성장하여 2029년 3.5조 달러에 이를 전망임.",
    "국내 PC방 매출액은 2조 2,556억원으로 전년 대비 12.8% 증가하였음.",
]
GOOD = [
    "2026-04-24 이사회 결의에 따른 자기주식 직접 취득(예정 6,000억)을 2026-07-16 100% 완료하였음.",
    "잡손실 중 증선위 감리결과 과징금 205억원을 인식하였음.",
    "당사는 2026년 7월 29일 에스엠엔터테인먼트와 지분 10,108,159주(42.58%) 양수도 계약을 체결하였음.",
    "변동이자율 차입금 879,162,536천원(전기말 738,267,028천원)은 금리 100bp 상승 시 이자비용이 늘어남.",
]


def _killed(x, year=2026):
    """_inv_collect.killed 와 같은 규칙(문장 나누기는 끝 마침표를 떼므로 여기서도 뗀다)."""
    x = x.rstrip(".")
    if SRV.INV_FOOT.search(x) and not SRV._inv_anchor(x, year):
        return True
    return bool(SRV.INV_STD.search(x) or SRV.INV_CAPTION.search(x) or SRV.INV_NONE.search(x) or SRV.INV_POLICY.search(x) or SRV.ASK_STATUTE.search(x))


def test_kill_regexes_catch_audit_boilerplate():
    killed = [_killed(x) for x in BOIL]
    assert all(killed), killed
    assert not any(_killed(x) for x in GOOD)


def test_industry_sentences_are_flagged_not_company_facts():
    assert all(SRV._inv_is_industry(x) for x in INDUSTRY)
    assert not any(SRV._inv_is_industry(x) for x in GOOD)
    assert not SRV._inv_is_industry("당사는 글로벌 시장에서 2026년 3월 신제품을 출시하였음.")     # 주어가 당사면 산업 문장이 아니다


def test_anchor_gate_reads_amounts_without_won_and_near_dates():
    assert SRV._inv_won2("자기주식 직접 취득(예정 6,000억)") == 6000e8
    assert SRV._inv_won2("과징금 205억원") == 205e8 and SRV._inv_won2("과징금 205억") == 205e8
    assert SRV._inv_won2("주당 500원 배당") is None                      # 1억 미만
    a = SRV._inv_anchor(GOOD[0], 2026)
    assert a and a["amt"] == 6000e8 and a["date"]
    assert SRV._inv_anchor(GOOD[1], 2026) == {"amt": 205e8, "auth": True}
    assert SRV._inv_anchor(GOOD[2], 2026)["party"] and SRV._inv_anchor(GOOD[2], 2026)["date"]
    assert SRV._inv_anchor("현재 국내/외 대기업 등에서 좋은 평가를 받고 있고 수많은 프로젝트에 참여하고 있음.", 2022) is None
    assert SRV._inv_anchor("2019년 3월 공장을 준공하였음.", 2026) is None            # 보고 해에서 먼 날짜는 앵커가 아니다
    assert SRV._inv_anchor("코나플레이트는 리테일 · 커머스 · 핀테크 기업이 자체 선불카드를 발행하도록 지원하고 있음.", 2026) is None


def test_direction_reads_the_subject_of_a_suit():
    tags = ["리스크·소송"]
    assert SRV._inv_dir_role("항소심 1건(소송가액 약 72,761천원)은 항소 기각(회사 승소)으로 종결되었음.", tags, -0.6) >= 0
    assert SRV._inv_dir_role("회사는 일부 공급자를 상대로 손해배상청구소송을 제기하였음.", tags, -1.0) == 0.0
    assert SRV._inv_dir_role("원고가 당사를 상대로 제기한 손해배상 소송이 진행 중임.", tags, -1.0) == -1.0
    assert SRV._inv_dir_role("시공사로 선정된 원고가 당사에 50억원을 청구하였음.", tags, -0.6) == -0.6


def test_order_tag_needs_contract_words_and_amount_or_party():
    assert not SRV._inv_order_ok("정화명령을 받지 않은 건축물 하부토양에 대하여도 정화를 실시할 예정임.", ["수주·계약"])
    assert SRV._inv_order_ok("한국전력공사와 170kV 변압기 공급계약 350억원을 체결하였음.", ["수주·계약"])
    assert SRV._inv_order_ok("정화를 실시할 예정임.", ["설비·증설"])                  # 수주 꼬리표가 아니면 안 본다


def test_fin_hygiene_thresholds_and_bank_debt():
    rows = [{"key": "매출액", "pct": 3.0, "value": 1}, {"key": "영업이익", "pct": 4.0, "value": 5, "prev": 4},
            {"key": "영업이익률", "value": 0.2, "prev": -1, "delta": 1.2}, {"key": "ROE", "value": 3, "delta": 0.5}, {"key": "부채비율", "value": 1283, "delta": 102},
            {"key": "유보금", "pct": 7.0, "value": 1}, {"key": "당기순이익", "pct": 80.0, "value": 1}]
    out = SRV._inv_fin(rows, fin_co=True)
    keys = [x["key"] for x in out]
    assert "매출액" not in keys and "영업이익" not in keys and "영업이익률" not in keys and "ROE" not in keys and "유보금" not in keys
    assert "부채비율" not in keys                                 # 은행
    assert "순이익" in keys                                        # 영업외 주의 — 영업이익 크기와 무관
    out2 = SRV._inv_fin([{"key": "매출액", "pct": 42.0, "value": 1}, {"key": "영업이익", "pct": 101.0, "value": 15, "prev": -30}, {"key": "영업이익률", "value": 0.2, "prev": -0.5, "delta": 0.7}])
    turn = next(x for x in out2 if x["label"] == "흑자 전환")
    assert turn["mag"] < 0.35                                      # 이익률 0.2% 흑자 전환은 작게
    assert not any(x["key"] == "레버리지" for x in out2)            # 기준 이익이 적자면 레버리지 아님
    out3 = SRV._inv_fin([{"key": "매출액", "pct": 24.0, "value": 1}, {"key": "영업이익", "pct": 107.0, "value": 10, "prev": 5}, {"key": "영업이익률", "value": 12.7, "prev": 7.6, "delta": 5.1}])
    assert any(x["key"] == "레버리지" for x in out3)


def test_num_signal_needs_keyword_right_before_the_number():
    b = {"sections": [{"section": "사업의 내용", "file": "f1", "numbers": [
        {"after": "보고기간 말 현재 피고 소송 4건, 소송가액 15,055,622천원", "diff": [{"pct": -33.0, "from": "6", "to": "4"}], "tags": ["리스크·소송"]},
        {"after": "변동이자율 차입금 879,162,536천원(전기말 738,267,028천원)", "diff": [{"pct": 19.1, "from": "738,267,028", "to": "879,162,536"}], "tags": ["자금조달"]}]}]}
    out = SRV._inv_nums(b, "20260814000001")
    assert [x["label"].split()[0] for x in out] == ["차입금"]       # 건수 6→4 는 소송가액이 아니다
    assert out[0]["loc"]["rcept"] == "20260814000001" and out[0]["loc"]["file"] == "f1" and out[0]["raw"].startswith("변동이자율")


def test_loc_points_at_the_sentence():
    text = "첫 문단입니다.\n\n두 번째 문단. 당사는 2026년 7월 29일 계약을 체결하였음. 끝.\n세 번째 문단.\n"
    sent = "당사는 2026년 7월 29일 계약을 체결하였음."
    blk, off, ln = SRV._inv_loc(text, sent)
    assert blk == 1 and text[off:off + ln] == sent
    assert SRV._inv_loc(text, "없는 문장")[:2] == (None, None)
    ss = SRV._inv_sents(text)
    assert any(s_ == sent.rstrip(".") and b_ == 1 for s_, b_, _ in ss)      # 문장 나누기는 끝 마침표를 떼어 둔다


def test_index_matches_reworded_sentence():
    ix = SRV._InvIndex()
    a = "현재 국내 대기업 등에서 좋은 평가를 받고 있고 세계적으로 인지도가 높은 기업에 공급자 승인을 받아 여러 프로젝트에 참여하고 있습니다"
    b = "현재 국내/외 대기업 등에서 좋은 평가를 받고 있고 세계적으로 인지도가 높은 기업에 공급자 승인을 받아 수많은 프로젝트에 참여하고 있습니다"
    ix.add_skels([SRV._ask_skel(a)])
    assert ix.has(SRV._ask_skel(b))                                 # 두 낱말 고친 문장은 새 문장이 아니다
    assert not ix.has(SRV._ask_skel(GOOD[0]))
    assert not ix.has(SRV._ask_skel("짧은 문장"))                   # 20자 미만 뼈대는 안 본다


def test_refine_groups_same_paragraph_and_same_amount_and_keeps_unanchored_light():
    base = {"src": "new", "label": "리스크 · 과징금", "text": "t", "section": "재무에 관한 사항", "sec": "재무", "tags": ["리스크·소송"], "dir": -0.8, "hz": .45, "mag": .6, "gurus": []}
    sigs = [dict(base, raw="잡손실 중 증선위 감리결과 과징금 205억원을 인식하였음.", loc={"rcept": "r", "file": "f", "blk": 3, "off": 0, "len": 10}, anchor=True, anc={"amt": 205e8, "auth": True}),
            dict(base, text="t2", raw="과징금 205억원은 2026년 9월 납부하였음.", loc={"rcept": "r", "file": "f", "blk": 3, "off": 40, "len": 10}, anchor=True, anc={"amt": 205e8}),
            dict(base, text="t3", raw="감리 결과에 따른 과징금 약 200억원 관련 소송을 검토 중임.", loc={"rcept": "r", "file": "g", "blk": 7, "off": 0, "len": 10}, anchor=True, anc={"amt": 200e8}),
            dict(base, label="R&D · 프로젝트", text="t4", raw="좋은 평가를 받고 있음", loc={"rcept": "r", "file": "f", "blk": 9, "off": 0, "len": 10}, anchor=False, anc=None, dir=0.3)]
    out = SRV._inv_refine(sigs, {"rev": 1e12, "op": 1e11, "cap": 1e13})
    assert len(out) == 2 and out[0]["n_rel"] == 2                   # 같은 문단 둘 + 같은 금액(±25%) 하나 → 한 줄
    assert out[1]["mag"] < out[0]["mag"] and not out[1]["anchor"]   # 앵커 없는 문장은 가볍다


def test_common_index_key_and_threshold_rule():
    k = SRV._inv_skel_key("동 개정사항은 2026년 1월 1일 이후 시작하는 회계연도부터 적용되며 조기적용이 허용됩니다.")
    assert len(k) >= 20 and k == SRV._inv_skel_key("동 개정사항은 2027년 1월 1일 이후 시작하는 회계연도부터 적용되며 조기적용이 허용됩니다.")   # 숫자 · 띄어쓰기 무시
    assert SRV.INV_COMMON_MIN == 5 and SRV.INV_COMMON_PREFIX == 3 and SRV.INV_V == 12 and SRV.QTR_V == 6


def test_between_reports_picks_regular_ones_inside_the_window():
    c = {"reports": [{"rcept": "20250515000001", "label": "분기보고서", "tag": "", "stamp": "2025-03"},
                     {"rcept": "20250814000001", "label": "반기보고서", "tag": "", "stamp": "2025-06"},
                     {"rcept": "20251114000001", "label": "분기보고서", "tag": "", "stamp": "2025-09"},
                     {"rcept": "20251201000001", "label": "분기보고서", "tag": "[기재정정]", "stamp": "2025-09"},
                     {"rcept": "20260318000001", "label": "사업보고서", "tag": "", "stamp": "2025-12"},
                     {"rcept": "20260515000001", "label": "분기보고서", "tag": "", "stamp": "2026-03"},
                     {"rcept": "20260814000001", "label": "반기보고서", "tag": "", "stamp": "2026-06"}]}
    mid = SRV._inv_between(c, c["reports"][1], c["reports"][6])
    assert [r["stamp"] for r in mid] == ["2025-09", "2025-12", "2026-03"]


# ---------------------------------------------------------------- 재감사(같은 10곳 + 하이록 2022-09, v12 첫 판 GOOD 23%) 뒤 보탠 것
def test_footnote_with_anchor_survives_and_policy_sentence_dies():
    kb = "주3) 2026년 4월 24일 시작한 직접 취득(예정금액 600,000백만원)은 2026년 7월 16일 취득을 100% 완료하였음."
    yp = "(주1) 잡손실 중 증권선물위원회의 감리결과 조치 통보에 따른 회사 과징금으로 205억원을 인식하였음."
    se = "※ 상기 공급계약은 계약기간의 시작일이 2027년 1월 1일임."
    foot = "주1) 상기 결산배당횟수는 1991년부터 2025년까지의 횟수임."
    assert all(SRV.INV_FOOT.search(x) for x in (kb, yp, se, foot))
    assert all(SRV._inv_anchor(x, 2026) for x in (kb, yp, se)) and SRV._inv_anchor(foot, 2026) is None
    assert SRV.INV_POLICY.search("고객과의 계약에서 수행의무를 이행하는 시점에 수익을 인식함")
    assert not SRV.INV_CAPTION.search(kb)                                  # 각주 머리는 더 이상 캡션 규칙이 아니다


def test_party_token_hygiene():
    assert not SRV._inv_party("국내 반도체 수요가 늘어 관련 회사들과 계약을 검토하고 있음")        # '반도체' · '회사들' 은 상대방이 아니다
    assert SRV._inv_party("LG전자와 2026년 3월 공급계약을 체결하였음")
    assert SRV._inv_party("제이피모간체이스은행 등으로부터 계약이행보증을 제공받고 있음")
    assert not SRV._inv_party("고객과의 계약에서 수익을 인식함")


def test_suit_direction_when_company_is_defendant_but_wins():
    tags = ["리스크·소송"]
    s1 = "회사는 당반기말 현재 피고로 계류 중인 손해배상 청구 소송 중 항소심 1건(소송가액 약 72,761천원)에서 2026년 7월 8일자로 항소 기각(회사 승소) 판결을 받았음."
    assert SRV._inv_dir_role(s1, tags, -0.6) > 0
    s2 = "원고가 당사를 상대로 제기한 손해배상 청구가 1심에서 기각되었음."
    assert SRV._inv_dir_role(s2, tags, -0.8) > 0
    s3 = "원고가 당사를 상대로 제기한 손해배상 청구 소송에서 당사가 패소하였음."
    assert SRV._inv_dir_role(s3, tags, -0.8) == -0.8


def test_index_treats_split_history_list_as_known():
    ix = SRV._InvIndex()
    old = ["- 2020.05 인도네시아 현지 법인 85% 지분 취득 (지분율 : KB캐피탈 85%, Sunindo Primasura 15%)", "- 2021.05 박성우 법인장 취임 및 현지 영업 개시"]
    ix.add_skels([SRV._ask_skel(x) for x in old])
    joined = "- 2020.05 인도네시아 현지 법인 85% 지분 취득 (지분율 : KB캐피탈 85%, Sunindo Primasura 15%) - 2021.05 박성우 법인장 취임 및 현지 영업 개시"
    assert ix.has(SRV._ask_skel(joined))                                   # 두 문장이 나눠 덮어도 있던 말


def test_num_channel_ignores_trailing_note_reference():
    after = "보고기간말 현재 변동이자율이 적용되는 차입금은 879,162,536천원(전기말 : 738,267,028천원)이며, 다른 모든 변수가 동일하고 이자율이 100 basis points 변동하는 경우 이자비용이 변동함(주석 29 참조)."
    b = {"sections": [{"section": "재무에 관한 사항", "file": "f", "numbers": [{"after": after, "diff": [{"pct": 44.4, "from": "608,807,108", "to": "879,162,536"}], "tags": []}]}]}
    out = SRV._inv_nums(b, "r")
    assert len(out) == 1 and out[0]["label"].startswith("차입금 +44%")


def test_industry_macro_prose_flagged():
    assert SRV._inv_is_industry("다만, 향후 환율 경로는 한ㆍ미ㆍ일 정책 공조와 글로벌 위험 선호 심리 회복 등에 힘입어 연말까지 하락할 수 있다는 전망임.")
    assert SRV._inv_is_industry("AI 서버·고사양용 고부가 MLCC는 주문이 급증해 일본·한국 업체 가동률이 80%를 웃도는 반면 범용 IT용은 상대적으로 부진함.")


def test_tiny_amount_sentence_is_small_and_scope_hint_survives_stale():
    kona = "회사는 당반기말 현재 피고로 계류 중인 손해배상 청구 소송 중 항소심 1건(소송가액 약 72,761천원)에서 2026년 7월 8일자로 항소 기각(회사 승소) 판결을 받았음"
    a = SRV._inv_anchor(kona, 2026)
    assert a and a.get("tiny") and "amt" not in a
    base = {"src": "new", "label": "리스크 · 손해배상", "text": "t", "raw": kona, "section": "재무에 관한 사항", "sec": "재무", "tags": ["리스크·소송"], "dir": 0.3, "hz": .45, "mag": .5, "gurus": [],
            "loc": {"rcept": "r", "file": "f", "blk": 1, "off": 0, "len": 10}, "anchor": True, "anc": a}
    out = SRV._inv_refine([base], {"rev": 1e12, "op": 1e11, "cap": 1e13})
    assert out[0]["size"] == "작음"
    assert SRV.INV_SCOPE.search("2026년 4월 30일자 이사회 결의에 따라 종속기업인 CCP ehf.와 그 종속기업의 지분매각을 결정하였으며")
