# -*- coding: utf-8 -*-
"""밸류체인 한 장(밸류체인_지도.py · 서버 vcmap_view). 소유 파서 시험 텍스트는 삼성전기 · 삼성전자 · SK하이닉스 · 한미반도체
수집 보고서(strip_markup 결과: 칸 하나 = 한 줄, 행 사이 빈 줄)의 꼴만 줄여 지어낸 것이다 — 행 · 숫자는 일부만 옮기거나 바꿨다.
서버 시험은 tmp_path 의 가짜 캐시로만(실제 .cache 는 건드리지 않는다)."""
import os, sys, json, time, threading, datetime as dt, importlib.util as ilu
from collections import Counter
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("밸류체인_지도", os.path.join(BASE, "밸류체인_지도.py"))
M = ilu.module_from_spec(_sp); _sp.loader.exec_module(M)
_np = ilu.spec_from_file_location("내러티브_vm", os.path.join(BASE, "내러티브.py"))
NAR = ilu.module_from_spec(_np); _np.loader.exec_module(NAR)

CORPS = [("005930", "삼성전자", "SAMSUNG ELECTRONICS CO,.LTD", "20251201"), ("032830", "삼성생명", "Samsung Life Insurance Co., Ltd.", "20250101"),
         ("402340", "SK스퀘어", "SK Square Co., Ltd.", "20250101"), ("000830", "삼성물산", "SAMSUNG C&T", "20170630"),
         ("028260", "삼성물산", "Samsung C&T Corporation", "20260323"), ("003600", "SK", "SK Holdings", "20170630"), ("034730", "SK", "SK Inc.", "20240328"),
         ("005070", "코스모신소재", "COSMO ADVANCED MATERIALS & TECHNOLOGY CO., LTD", "20260515"),
         ("005420", "코스모화학", "COSMOCHEMICALCO.,LTD", "20260319"), ("439960", "코스모로보틱스", "COSMO ROBOTICS CO., Ltd", "20260701"),
         ("078600", "대주전자재료", "DaejooElectronicMaterialsCo.,Ltd.", "20221207"), ("003310", "대주산업", "Daejoo Inc.", "20260320"),
         ("290740", "액트로", "ACTRO CO.,Ltd", "20220225"), ("028050", "삼성E&A", "Samsung E&A Co., Ltd.", "20250101"),
         ("092220", "KEC", "KEC Corporation", "20250101"), ("122900", "아이마켓코리아", "iMarketKorea Inc.", "20250514"),
         ("010140", "삼성중공업", "SAMSUNG HEAVY INDUSTRIES", "20250101"), ("206950", "볼빅", "Volvik Inc.", "20250101"),
         ("009150", "삼성전기", "SAMSUNG ELECTRO-MECHANICS CO.,LTD", "20230102")]
COLLECTED = {"005930": "삼성전자", "005070": "코스모신소재", "005420": "코스모화학", "078600": "대주전자재료", "028260": "삼성물산",
             "032830": "삼성생명", "028050": "삼성E&A", "402340": "SK스퀘어", "034730": "SK", "009150": "삼성전기", "010140": "삼성중공업"}
LK = M.Linker(CORPS, COLLECTED)


def cells(*rows):
    """행마다 칸 하나 = 한 줄, 행 사이 빈 줄(수집기 strip_markup 꼴)."""
    return "\n\n".join("\n".join(r) for r in rows)


# ---------------------------------------------------------------- 1. 이름 → 코드
@pytest.mark.parametrize("name, code", [
    ("삼성물산(주)", "028260"),            # 같은 이름 둘 — 수집 회사(그리고 modify_date 최신)
    ("SK(주)", "034730"),
    ("삼성이앤에이(주)", "028050"),        # & = 앤
    ("삼성생명보험㈜", "032830"),          # '보험' 꼬리
    ("삼성에스디아이", None),              # 목록에 없는 회사
    ("COSMO", "005070"),                   # 한 낱말 — 수집 회사 중 그 낱말로 시작하는 곳 하나
    ("COSMO AMT", "005070"),               # 머리 낱말 + 머리글자
    ("DAEJOO", "078600"),                  # 수집 회사 첫 낱말이 비수집 '대주산업(Daejoo Inc.)' 통째 일치보다 먼저
    ("ACTRO", "290740"),                   # 비수집 상장사 — 통째 일치
    ("iMarket Korea", "122900"),
    ("MEC", None), ("KEC", None),          # 4글자 미만 영문은 잇지 않는다(인도 KEC)
    ("SONY", None), ("TORAY", None),
])
def test_linker(name, code):
    assert LK.code(name) == code


def test_linker_acronym_only_for_multiword_names():
    lk = M.Linker(CORPS + [("448780", "마이크로엔엑스", "Micro-NX Co., Ltd.", "20260313")], dict(COLLECTED, **{"448780": "마이크로엔엑스"}))
    assert lk.code("Micron") is None                 # micro + n 머리글자 = 'micron' — 한 낱말 이름에는 머리글자를 쓰지 않는다
    assert lk.code("COSMO AMT") == "005070"          # 여러 낱말은 그대로


def test_linker_listed_code_prefix_only_for_known_listed():
    lk = M.Linker(CORPS + [("244920", "에이플러스에셋", "A Plus Asset Advisor Co., Ltd.", "20240329")], COLLECTED)
    assert lk.code("에이플러스에셋어드바이저") is None                        # 아무 이름에는 머리 맞추기를 하지 않는다
    assert lk.listed_code("에이플러스에셋어드바이저(주)") == "244920"         # 계열 '상장' 목록 이름만
    assert lk.listed_code("삼성생명보험㈜") == "032830" and lk.listed_code("없는회사") is None
    assert lk.listed_code("SK위탁관리부동산투자회사") is None        # 'SK' = '에스케이' 4자 머리로 SK 를 끌어오지 않는다
    assert lk.listed_code("KEC") == "092220"                         # 상장이라고 아는 짧은 영문 이름은 통째 맞춤


def test_linker_old_delisted_name_takes_newest_modify_date():
    lk = M.Linker(CORPS, {})
    assert lk.code("삼성물산") == "028260" and lk.code("SK(주)") == "034730" and lk.code("SK") is None    # 영문 4자 미만은 잇지 않는다


# ---------------------------------------------------------------- 2. 소유 파서
HEAD = ["성 명", "관 계", "주식의\n종류", "소유주식수 및 지분율", "비 고"]
SUB = ["기 초", "기 말", "주식수", "지분율", "주식수", "지분율"]
SH_SEMCO = "VII. 주주에 관한 사항\n\n1. 최대주주 및 특수관계인의 주식소유 현황\n\n(기준일 :\n2025년 12월 31일\n)\n(단위 : 주, %)\n\n" + cells(
    HEAD, SUB,
    ["삼성전자(주)", "최대주주 본인", "보통주", "17,693,084", "23.69", "17,693,084", "23.69", "-"],
    ["김두일", "발행회사 임원", "보통주", "4,000", "0.01", "4,000", "0.01", "-"],
    ["계", "보통주", "17,806,111", "23.84", "17,779,556", "23.80", "-"],
    ["계", "우선주", "0", "0.00", "0", "0.00", "-"]) + "\n\n2. 최대주주의 개요\n\n삼성전자(주)\n..."
SH_SEC = "1. 최대주주 및 특수관계인의 주식소유 현황\n\n" + cells(
    HEAD, SUB,
    ["삼성생명보험㈜", "최대주주 본인", "보통주", "508,157,148", "8.51", "508,157,148", "8.51", "-"],
    ["삼성생명보험㈜", "최대주주 본인", "우선주", "1,000", "0.01", "1,000", "0.01", "-"],
    ["삼성생명보험㈜(특별계정)", "최대주주 본인", "보통주", "3,500,000", "0.06", "3,600,000", "0.06", "-"],
    ["삼성물산㈜", "계열회사", "보통주", "298,818,100", "5.01", "298,818,100", "5.01", "-"],
    ["계", "보통주", "1,180,000,000", "19.84", "1,180,000,000", "19.84", "-"])
SH_HYNIX = "1. 최대주주 및 특수관계인의 주식소유 현황\n\n" + cells(
    HEAD, SUB, ["SK스퀘어(주)", "최대주주", "의결권 있는 주식", "146,100,000", "20.07", "146,100,000", "20.07", "-"],
    ["곽노정", "계열회사 임원", "의결권 있는 주식", "1,000", "0.00", "1,000", "0.00", "-"],
    ["계", "의결권 있는 주식", "146,101,000", "20.07", "146,101,000", "20.07", "-"])
SH_HANMI = "가. 최대주주 및 특수관계인의 주식소유 현황\n\n" + cells(
    HEAD, SUB, ["곽동신", "本人", "보통주", "32,370,000", "33.95", "31,937,861", "33.51", "-"],
    ["곽신홀딩스(주)", "계열회사", "보통주", "1,000,000", "1.05", "1,000,000", "1.05", "-"],
    ["계", "보통주", "53,000,000", "55.70", "53,000,000", "55.70", "-"])


def test_owner_listed_person_and_special_account():
    o = M.owner_of({"sh": SH_SEMCO}, LK.code)
    assert (o["name"], o["code"], o["pct"], o["kind"], o["rel"], o["total"]) == ("삼성전자", "005930", 23.69, "listed", "최대주주 본인", 23.8)
    o = M.owner_of({"sh": SH_SEC}, LK.code)
    assert o["name"] == "삼성생명보험" and o["code"] == "032830" and o["pct"] == 8.51 and o["pct_sum"] == 8.57
    o = M.owner_of({"sh": SH_HYNIX}, LK.code)
    assert (o["name"], o["code"], o["pct"], o["rel"]) == ("SK스퀘어", "402340", 20.07, "최대주주")
    o = M.owner_of({"sh": SH_HANMI}, LK.code)
    assert (o["name"], o["code"], o["kind"], o["pct"], o["total"]) == ("곽동신", None, "person", 33.51, 55.7)
    assert M.owner_of({"sh": "표 없음"}, LK.code) is None


OV_SEMCO = "라. 연결대상 종속회사 현황(요약)\n\n(단위 : 사)\n\n" + cells(
    ["구분", "연결대상회사수", "주요\n종속회사수"], ["기초", "증가", "감소", "기말"],
    ["상장", "-", "-", "-", "-", "-"], ["비상장", "14", "-", "-", "14", "8"], ["합계", "14", "-", "-", "14", "8"]) + \
    "\n\n※ 연결대상 종속기업 중 국내상장 기업은 없습니다."
OV_SEC = "연결대상 종속회사 현황(요약)\n\n" + cells(["상장", "-", "1", "-", "1", "1"], ["비상장", "228", "90", "11", "307", "157"])

DT_SEMCO = "1. 연결대상 종속회사 현황(상세)\n\n...\n\n2. 계열회사 현황(상세)\n\n가. 국내 계열회사 현황\n\n(기준일 :\n2025년 12월 31일\n)\n(단위 : 사)\n\n" + cells(
    ["상장여부", "회사수", "기업명", "법인등록번호"], ["상장", "18", "삼성물산(주)", "1101110015762"], ["삼성생명보험(주)", "1101110005953"],
    ["삼성이앤에이(주)", "1101110240509"], ["삼성전자(주)", "1301110006246"], ["비상장", "45", "가나(주)", "1101110000000"]) + \
    "\n\n3. 타법인출자 현황(상세)\n\n(단위 : 백만원, 주, %)\n\n" + cells(
    ["법인명", "상장\n여부", "최초취득일자", "출자목적"], ["수량", "지분율", "장부가액"],
    ["Tianjin Samsung Electro-Mechanics Co., Ltd.", "비상장", "1994.01.31", "경영참여", "3,220", "-", "81.8", "149,913", "-", "-", "-", "-", "81.8",
     "149,913", "2,143,180", "129,722"],
    ["삼성중공업(주)", "상장", "1983.11.30", "경영참여", "600", "18,150,855", "2.1", "205,104", "-", "-", "232,332", "18,150,855", "2.1", "437,436",
     "14,948,900", "535,800"],
    ["iMarket Korea", "상장", "2000.12.08", "경영참여", "1,000", "647,320", "1.8", "4,832", "-", "-", "-", "647,320", "1.8", "4,832", "1", "1"],
    ["삼성중공업(주)우선주", "상장", "1983.11.30", "경영참여", "1", "100", "0.5", "1", "-", "-", "-", "100", "0.5", "1", "1", "1"])
DT_HANMI = "2. 계열회사 현황(상세)\n\n-\n\n3. 타법인출자 현황(상세)\n\n" + cells(
    ["(주)볼빅", "(*3)", "상장", "2012년 01월 03일", "투자", "1,000", "100", "4.09", "1", "-", "-", "-", "100", "4.09", "899,400", "1", "1"],
    ["SPACE X", "상장", "2020년 01월 03일", "투자", "1,000", "100", "0.002", "1", "-", "-", "-", "100", "0.002", "56,784,877", "1", "1"])


def test_listed_subs_holdings_affiliates():
    t = {"ov": OV_SEMCO, "dt": DT_SEMCO}
    ls = M.listed_subs(t)
    assert ls["n"] == 0 and "국내상장" in ls["note"]
    assert M.listed_subs({"ov": OV_SEC})["n"] == 1
    assert M.listed_subs({"ov": "없음"}) == {"n": None, "note": None}
    h = M.holdings_of(t, LK.code)
    assert [(x["name"], x["code"], x["pct"], x["purpose"], x["book"]) for x in h] == [("삼성중공업", "010140", 2.1, "경영참여", "437,436"),
                                                                                     ("iMarket Korea", "122900", 1.8, "경영참여", "4,832")]
    g = M.affiliates_listed(t, LK.code)
    assert g["n"] == 18 and g["names"][:3] == [["삼성물산", "028260"], ["삼성생명보험", "032830"], ["삼성이앤에이", "028050"]]
    assert len(g["names"]) == 4                                   # '비상장' 앞에서 멈춘다
    hm = M.parse_own({"dt": DT_HANMI}, LK.code)
    assert [(x["name"], x["code"], x["pct"]) for x in hm["holdings"]] == [("볼빅", "206950", 4.09)]      # 각주 칸 건너뛰기 · 0.1% 미만 뺌
    assert hm["group"] == {"n": None, "names": []} and hm["listed_subs"] is None


# ---------------------------------------------------------------- 3. 낱말
def test_story_words_join_hyphen_and_drop_generic():
    rows = [{"date": "2026-10-0%d 08:00" % (i % 9 + 1), "title": t, "lines": ls} for i, (t, ls) in enumerate([
        ("MLCC 가격 인상 사이클", ["AI 서버용 MLCC 수요"]), ("FC-BGA 증설", ["FCBGA 가격 인상", "AI 서버 MLCC"]),
        ("MLCC 호황", ["FC-BGA 공급 부족"]), ("AI 서버 수요", ["MLCC"])])]
    ws = [w["w"] for w in M.story_words(rows, "2026-07-01", "삼성전기", NAR.hot_words, code="009150", top=4)]
    assert ws[:2] == ["MLCC", "AI"] and "FC-BGA" in ws and "가격" not in ws and "인상" not in ws
    assert M.specific("FC-BGA") and M.specific("기판") and not M.specific("AI") and not M.specific("서버") and not M.specific("으로")
    assert M.kw_norm("FC-BGA") == M.kw_norm("FC BGA") == "fcbga" and M.kw_norm("Camera Module") == "카메라모듈"


def test_product_words_labels_and_uses():
    prods = [{"segment": "컴포넌트", "item": "수동소자(MLCC, Inductor, Chip Resistor 등)", "use": "스마트폰용, 전장용, PC용 등", "amt": 3057919, "pct": 45.87},
             {"segment": "패키지솔루션", "item": "반도체패키지기판", "use": "PC용, 스마트폰용 등", "amt": 1496649, "pct": 22.45},
             {"segment": "광학솔루션", "item": "카메라모듈", "use": "스마트폰용, 전장용 등", "amt": 2111750, "pct": 31.68},
             {"segment": "합계", "item": "합 계", "amt": 6666318, "pct": 100.0}]
    ws = M.product_words(prods)
    assert {"수동소자", "MLCC", "반도체패키지기판", "기판", "카메라모듈"} <= set(ws) and "모듈" not in ws
    p = M.products_of(prods)
    assert [(x["item"], x["pct"], x["c"]) for x in p] == [("수동소자(MLCC 등)", 45.9, 0), ("카메라모듈", 31.7, 1), ("반도체패키지기판", 22.4, 2)]
    assert M.uses_of(prods) == ["스마트폰", "전장", "PC"]
    # 합계 행(100%)은 나머지가 100% 가까이일 때만 뺀다 · 뭉뚱그린 품목은 용도로 · 같은 이름은 합친다
    q = M.products_of([{"item": "제품상품", "use": "전도성 페이스트", "pct": 60.0}, {"item": "제품상품", "use": "전도성 페이스트", "pct": 40.0},
                       {"item": "제품상품", "use": "전도성 페이스트", "pct": 100.0}])
    assert [(x["item"], x["pct"]) for x in q] == [("전도성 페이스트", 100.0)]
    r = M.products_of([{"segment": "장비", "item": "반도체 제조용 장비 外", "amt": 500.0}, {"segment": "장비", "item": "HANMI", "amt": 0.01}])
    assert r[0]["item"] == "반도체 제조용 장비 外" and r[0]["pct"] == 100.0


# ---------------------------------------------------------------- 4. 트리거
def _classify(t):
    return ("good", "설비투자", 3, "") if "시설투자" in t or "유형자산취득" in t else (None, None, 0, "")


def test_disc_triggers_contract_sum_and_capex():
    today = dt.date(2026, 10, 12)
    discs = [{"d": "20261006", "rcept": "20261006800130", "title": "단일판매ㆍ공급계약체결"},
             {"d": "20260929", "rcept": "R5", "title": "단일판매ㆍ공급계약체결"},
             {"d": "20260928", "rcept": "C1", "title": "신규시설투자등"},
             {"d": "20260901", "rcept": "R4", "title": "[기재정정]단일판매ㆍ공급계약체결"},
             {"d": "20260520", "rcept": "R1", "title": "단일판매ㆍ공급계약체결"},
             {"d": "20250101", "rcept": "OLD", "title": "단일판매ㆍ공급계약체결"}]
    con = {"R5": {"amount": 2.85e11, "pct": 2.5}, "R1": {"amount": 1.557e12, "pct": 13.8}, "OLD": {"amount": 9e12, "pct": 50}}
    t = M.disc_triggers(discs, con, _classify, today)
    assert t[0]["kind"] == "contract" and t[0]["text"] == "공급계약 2건 · 1.84조 (매출 대비 16.3%) · 금액 미확인 1건"
    assert t[0]["date"] == "20260929" and t[0]["url"].endswith("R5")
    assert t[1]["kind"] == "capex" and t[1]["text"] == "설비투자 공시 · 신규시설투자등" and t[1]["amount"] is None
    assert M.disc_triggers([discs[0]], {}, None, today)[0]["text"] == "공급계약 공시 1건(금액 미확인)"


def test_report_triggers_and_pick():
    rows = [{"date": "2026-10-08 07:25", "title": "3Q26 Pre", "broker": None, "msg_url": "u1",
             "lines": ["세종 4.27조원, 베트남 2.51조원 등 ABF 증설", "27~28년 반영 수주금액 4조원 규모"]},
            {"date": "2026-09-28 21:55", "title": "다시 이익 상향", "broker": "하나증권", "msg_url": "u2",
             "lines": ["MLCC 판가인상 및 고객사별 LTA 제한(60~70% 미만)", "가동률 90% 중반"]},
            {"date": "2026-08-31 08:00", "title": "MLCC", "broker": "B", "msg_url": "u3", "lines": ["범용 MLCC는 30% 이상 가격 인상"]},
            {"date": "2026-01-01 08:00", "title": "옛 글", "lines": ["가격 50% 인상"]}]
    r = M.report_triggers(rows, "2026-06-14", ["MLCC"])
    assert r["price"]["text"] == "범용 MLCC는 30% 이상 가격 인상" and r["price"]["date"] == "2026-08-31"     # '60~70%' 는 가격 변동이 아니다
    assert r["capex"]["url"] == "u1" and r["order"]["text"].startswith("27~28년") and r["util"]["by"] == "하나증권"
    disc = [{"kind": "contract", "text": "공급계약 5건", "src": "공시", "date": "20260929", "url": "d", "amount": 1e12},
            {"kind": "capex", "text": "설비투자 공시 · 신규시설투자등", "src": "공시", "date": "20260928", "url": "c", "amount": None}]
    p = M.pick_triggers(disc, r)
    assert [x["kind"] for x in p] == ["contract", "price", "capex", "util"]                 # 공시 먼저 · 같은 범주(order)는 공시만
    cap = p[2]
    assert cap["src"] == "리포트" and cap["note"] == "공시 2026.09.28 신규시설투자등"         # 금액 없는 설비투자 공시 → 금액 있는 리포트 줄
    p2 = M.pick_triggers(disc, {})
    assert [x["kind"] for x in p2] == ["contract", "capex"] and "amount" not in p2[0]
    same = {"kind": "order", "text": "LTA 기반 캐파 증설 1.6조원", "src": "리포트"}
    p3 = M.pick_triggers([disc[1]], {"order": same, "capex": dict(same, kind="capex")})
    assert [(x["kind"], x["src"]) for x in p3] == [("capex", "공시"), ("order", "리포트")]      # 한 줄이 두 범주면 앞 범주만 → 설비투자는 공시로


# ---------------------------------------------------------------- 5. 단면
def test_px_stats_and_ranks():
    days = [(dt.date(2025, 10, 1) + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(373)]
    up = [(d, 100.0 + i) for i, d in enumerate(days)]
    s = M.px_stats(up)
    assert s["d"] == "20261008" and s["px"] == 472.0 and s["hi"] == 472.0 and s["dd"] == 0.0
    assert s["r1"] == round((472 / 442 - 1) * 100, 1)
    rows = {"A": s, "B": dict(s, r1=-5.0, r3=-5.0, r6=-5.0), "C": dict(s, d="20261001", r1=99.0)}
    assert M.xs_ranks(rows) == "20261008"
    assert rows["A"]["p1"] == 100 and rows["B"]["p1"] == 50 and rows["C"]["p1"] is None           # 그날 거래 없던 종목은 백분위 없음


# ---------------------------------------------------------------- 6. 후보 합치기
def test_candidates_union_exclusion_and_noise():
    stocks = {"009150": {"themes": ["MLCC(적층세라믹콘덴서)", "반도체 기판(FC-BGA/PCB/MLB 등)", "온디바이스 AI"]},
              "001820": {"themes": ["MLCC(적층세라믹콘덴서)"]}, "353200": {"themes": ["반도체 기판(FC-BGA/PCB/MLB 등)", "온디바이스 AI"]},
              "005930": {"themes": ["온디바이스 AI"]}, "999999": {"themes": ["MLCC(적층세라믹콘덴서)"]}}
    univ = {c: c for c in ("009150", "001820", "353200", "005930", "011070", "000660", "004170", "003230", "005070", "126730")}
    card = {"date": "2026-06-30 08:00", "title": "중장기 투자유망 포트폴리오", "lines": ["서버용 MLCC 탑재량 증가"]}
    reps = {"011070": [{"date": "2026-09-01", "title": "FC-BGA 증설", "lines": []}] * 3,
            "000660": [card], "004170": [card], "003230": [card]}
    supply = {"005070": [{"w": "코스모신소재가 삼성전기를 매출처로 적음", "s": "삼성전기 공급사"}], "005930": [{"w": "x", "s": "x"}]}
    prod = {"126730": [("MLCC", None, 100.0)], "353200": [("인쇄회로기판", "PCB", 95.0), ("회로기판 소재", "IT", 30.0)],
            "005930": [("DRAM", None, 60.0)]}
    c = M.candidates("009150", univ=univ, stocks=stocks, theme_keys=["mlcc", "fcbga", "기판"], story_keys=["mlcc", "fcbga"],
                     reps=reps, since180="2026-04-15", rep_keys=[("MLCC", "mlcc"), ("FC-BGA", "fcbga")], supply=supply, prod_index=prod,
                     prod_keys=[("MLCC", "mlcc"), ("기판", "기판")], exclude={"005930"})
    assert set(c) == {"001820", "353200", "011070", "005070", "126730"}       # 고른 회사 · 모회사(exclude) · 수집 밖 · 포트폴리오 카드 잡음은 빠진다
    assert c["011070"]["rep_n"] == 3 and M.link_score(c["011070"]) == 3
    assert M.link_score(c["005070"]) == 5 and M.link_score(c["126730"]) == 4 and M.link_score(c["001820"]) == 1
    assert c["353200"]["prod"] == [("기판", "인쇄회로기판", 95.0, False)] and c["353200"]["st"] == 1     # '회로기판 소재'는 기판이 아니라 소재 · 비중은 근거 줄용(est False = 표 값)
    order = sorted(c, key=lambda k: M.evidence_rank(c[k]), reverse=True)
    assert order[0] == "005070" and order[-1] == "001820"
    # 주도주 테마가 없으면 전체 테마에서 · 두 낱말 테마는 제품 줄 낱말로도
    st2 = {"042700": {"themes": []}, "111111": {"themes": ["반도체 장비"]}, "222222": {"themes": ["HBM"]}}
    c2 = M.candidates("042700", univ={"111111": 1, "222222": 1}, stocks=st2, phrases=M.phrase_tokens([{"item": "반도체 제조용 장비 外"}]))
    assert set(c2) == {"111111"}


def test_candidates_report_only_needs_shared_sector():
    stocks = {"353200": {"themes": [], "sector": "디스플레이/전자부품"}, "383220": {"themes": [], "sector": "소비재"},
              "222800": {"themes": [], "sector": "반도체"}, "077360": {"themes": [], "sector": "디스플레이/전자부품"}}
    rows = lambda t: [{"date": "2026-09-01", "title": t, "lines": ["MLB"]}]       # noqa: E731 — 제목이 같으면 여러 종목 카드로 본다
    c = M.candidates("353200", univ={"383220": 1, "222800": 1, "077360": 1}, stocks=stocks,
                     reps={"383220": rows("의류"), "222800": rows("기판"), "077360": rows("소재")},
                     since180="2026-04-15", rep_keys=[("MLB", "mlb")], supply={"222800": [{"w": "w", "s": "s"}]})
    assert set(c) == {"222800", "077360"}             # 의류(MLB 야구 브랜드)는 빠진다 · 공급망 후보의 업종(반도체)은 열린다


def test_candidates_drop_broad_report_words():
    # '제시'(리포트 상투어, 실제 180일 212곳)가 스토리 낱말로 들면 아무 종목이나 동시 언급으로 끌려온다 — 넓은 말은 빼고 다시 센다
    univ = {c: 1 for c in ("105560", "055550", "006800", "011070", "066570")}
    row = lambda t, ln: {"date": "2026-09-01", "title": t, "lines": [ln]}      # noqa: E731
    reps = {"055550": [row("은행 1", "CET-1 비율 개선 · 목표주가 제시")], "006800": [row("증권 2", "목표주가 제시")],
            "011070": [row("기판 3", "목표주가 제시")], "066570": [row("가전 4", "목표주가 제시")]}
    keys = [("은행", "은행"), ("CET-1", "cet1"), ("제시", "제시")]
    c = M.candidates("105560", univ=univ, stocks={}, reps=reps, since180="2026-04-15", rep_keys=keys, rep_df_max=2)
    assert set(c) == {"055550"} and c["055550"]["rep_n"] == 1 and set(c["055550"]["rep_by"]) == {"은행", "CET-1"}   # 제시(4곳 > 2)만 빠진다
    c2 = M.candidates("105560", univ=univ, stocks={}, reps=reps, since180="2026-04-15", rep_keys=keys, rep_df_max=10)
    assert set(c2) == {"055550", "006800", "011070", "066570"}         # 문턱 안이면 그대로


# ---------------------------------------------------------------- 7. 점수 · 군 경계
def _c(**kw):
    c = {"themes": [], "st": 0, "rep_n": 0, "rep_by": Counter(), "supply": [], "prod": []}
    c.update(kw)
    return c


PH = {"phase": "확장 가속", "B": 23.5, "opm": 17.5, "label": "2026Q2", "old": True}


def test_score_parts_and_groups():
    s = M.score(_c(prod=[("FC-BGA", "반도체패키지기판")], rep_n=16, rep_by=Counter({"FC-BGA": 16})), lead_p3=45,
                px={"p1": 98, "p3": 87, "dd": -17.4}, ph=PH, n_rep=34, up=27.0)
    assert s["parts"] == {"link": 4, "fund": 5, "attn": 4, "lag": 1, "safe": 5} and s["score"] == 19 and s["group"] == "B" and s["stars"] == 4
    assert s["why"] == "FC-BGA 동종 · 리포트 16건 · 확장 가속"
    assert [e["t"] for e in s["ev"]["lag"]] == ["3개월 수익률 백분위 87 (주도주 45) · 52주 고점 대비 -17.4%"] and s["ev"]["safe"][0]["t"] == "위험 꼬리표 없음"
    assert s["group_note"] == M.GROUP_NOTE["B"] and "확장 가속" in s["expl"] and "앞섰고" in s["expl"]
    # B 경계: 연결 4 · 합 14 → C
    s = M.score(_c(prod=[("MLCC", "MLCC")]), lead_p3=50, px={"p1": 50, "p3": 50, "dd": -10}, ph=None, up=None)
    assert s["parts"] == {"link": 4, "fund": 2, "attn": 0, "lag": 3, "safe": 5} and s["score"] == 14 and s["group"] == "C"
    # 상승여력 +30% 이면 주목 +1 · 덜 오름 30p 이상 5 · 고점 대비 −50% 아래 −1
    s = M.score(_c(rep_n=10, rep_by=Counter({"MLCC": 10})), lead_p3=90, px={"p1": 10, "p3": 40, "dd": -62.6}, ph=PH, up=98.9)
    assert s["parts"]["attn"] == 5 and s["parts"]["lag"] == 4 and s["parts"]["link"] == 3 and s["group"] == "C"
    # C 경계: 연결 2 · 합 10 → D
    s = M.score(_c(rep_n=1, rep_by=Counter({"MLCC": 1})), lead_p3=None, px=None, ph={"phase": "수축 심화", "opm": 1.0, "label": "q"}, up=None)
    assert s["parts"] == {"link": 2, "fund": 1, "attn": 2, "lag": 2, "safe": 5} and s["group"] == "C"
    s = M.score(_c(rep_n=1, rep_by=Counter({"MLCC": 1})), lead_p3=None, px=None, ph={"phase": "수축 심화", "opm": -3.0, "label": "q"}, up=None)
    assert s["parts"]["fund"] == 0 and s["parts"]["safe"] == 4 and s["score"] == 10 and s["group"] == "D"
    # Fake: 건전성 ≤ 2 · 또는 테마만 + 1개월 백분위 ≥ 95 + 실적 ≤ 1
    s = M.score(_c(supply=[{"w": "w", "s": "s"}]), lead_p3=50, px={"p1": 50, "p3": 50}, ph=PH, risk={"level": "작전주 꼴"})
    assert s["parts"]["safe"] == 0 and s["group"] == "Fake" and s["why"].startswith("작전주 꼴")
    s = M.score(_c(themes=["MLCC"]), lead_p3=50, px={"p1": 95, "p3": 99}, ph={"phase": "부진 지속", "opm": 2.0, "label": "q"})
    assert s["group"] == "Fake"
    s = M.score(_c(themes=["MLCC"]), lead_p3=50, px={"p1": 94, "p3": 99}, ph={"phase": "부진 지속", "opm": 2.0, "label": "q"})
    assert s["group"] == "D"


def test_risk_flags():
    assert M.risk_flags(None) == (5, [])
    assert M.risk_flags({"ref": [{"cat": "감사의견비적정"}, {"cat": "자본잠식"}]})[0] == 0
    assert M.risk_flags({}, [], ["투자경고"]) == (2, ["투자경고"])
    assert M.risk_flags({"hits": [{"cat": "CB발행", "days": 2}]}, [], ["투자주의"], -1.0) == (2, ["투자주의", "자금조달 잦음", "적자"])
    assert M.risk_flags({"ref": [{"cat": "불성실_지정"}]}) == (4, ["불성실공시"])                 # 2026-10-13 부터 −1(전엔 표시만)


# ---------------------------------------------------------------- 8. 그물망 조립
def test_up_groups_order_colors_other_last_and_sellers():
    prods = M.products_of([{"segment": "컴포넌트", "item": "MLCC", "pct": 46.0}, {"segment": "광학솔루션", "item": "카메라모듈", "pct": 32.0},
                           {"segment": "패키지솔루션", "item": "기판", "pct": 22.0}])
    mats = [{"segment": "컴포넌트", "item": "기타", "amt": 245270, "pct": 29.3, "suppliers": []},
            {"segment": "컴포넌트", "item": "PASTE/POWDER", "amt": 383730, "pct": 45.8, "suppliers": [{"name": "SHOEI"}]},
            {"segment": "컴포넌트", "item": "FILM", "amt": 208215, "pct": 24.9, "suppliers": [{"name": "TORAY"}, {"name": "COSMO"}]},
            {"segment": "광학솔루션", "item": "센서 IC", "amt": 668103, "pct": 47.7, "suppliers": [{"name": "삼성전자(*)"}]},
            {"segment": "광학솔루션", "item": "기타", "amt": 1420486, "pct": 52.3, "suppliers": []},
            {"segment": "패키지솔루션", "item": "CCL/PPG", "amt": 70644, "pct": 20.7, "suppliers": []},
            {"segment": "패키지솔루션", "item": "합계", "amt": 341812, "pct": 100.0, "suppliers": []},
            {"segment": "기타부문", "item": "X", "amt": 10, "pct": 100.0, "suppliers": []}]
    sellers = [{"code": "005070", "name": "코스모신소재", "group": False}, {"code": "005420", "name": "코스모화학", "group": False},
               {"code": "028050", "name": "삼성E&A", "group": True}, {"code": "122900", "name": "아이마켓코리아", "group": False}]
    up = M.up_groups(mats, prods, LK.code, sellers=sellers, skip={"122900"}, lead_name="삼성전기")
    assert [(g["seg"], g["c"]) for g in up] == [("광학솔루션", 1), ("컴포넌트", 0), ("패키지솔루션", 2)]      # 금액 큰 부문부터 3묶음 · 부문 색 = 제품 색
    comp = up[1]
    assert [it["item"] for it in comp["items"]] == ["PASTE/POWDER", "FILM", "기타"]                         # '기타' 뒤로
    assert comp["items"][1]["sup"] == [{"name": "TORAY", "code": None}, {"name": "COSMO", "code": "005070"}]
    assert comp["listed"] == [{"name": "코스모신소재", "code": "005070", "why": "코스모신소재가 삼성전기를 매출처로 적음"}]     # 품목(FILM)은 내 원재료 표 것 — 그 회사 매출처 표 줄엔 안 적는다
    assert up[0]["listed"] == [] and up[0]["label"] == "상류 · 광학솔루션 소재 · 장비"                   # 코스모화학(지주 연결) · 계열 · skip 은 빠진다
    assert [it["item"] for it in up[2]["items"]] == ["CCL/PPG"]                                              # 합계 줄(100%) 뺌
    up2 = M.up_groups(mats, prods, LK.code, lead_name="삼성전기", name_of=LK.name_of.get)
    assert up2[1]["items"][1]["sup"][1] == {"name": "COSMO", "code": "005070", "co": "코스모신소재"}           # 이은 이름이 다를 때만 co
    assert "co" not in up2[0]["items"][0]["sup"][0]                                                         # '삼성전자(*)' = 삼성전자


def test_down_nodes_and_period():
    custs = [{"name": "삼성전자", "pct": 26.0, "link": {"code": "005930"}}, {"name": "본인", "pct": 5.0, "self": True}]
    # 서버는 회사마다 한 줄(첫 줄의 seg · pct · per_sup, items 는 모든 줄) — 영풍 BASE 31.47 은 'FPCB, PCB 부문 BASE' 매입 중 삼성전기 몫(매입처마다 한 줄인 표), BGA PCB 68.83 은 다른 줄
    buyers = [{"code": "000670", "name": "영풍", "pct": 31.47, "items": ["BASE", "BGA PCB"], "seg": "FPCB, PCB 부문", "per_sup": True},
              {"code": "000670", "name": "영풍", "pct": 68.83, "items": ["BGA PCB"], "seg": "반도체 제조", "per_sup": True},
              {"code": "036540", "name": "SFA반도체", "pct": 90.3, "items": ["PCB"], "seg": "반도체"}]
    orders = [{"party": "글로벌 대형기업", "n": 5, "amount": 3663372174336.0, "link": None}]
    period = M.period_label({"stamp": "2026-06", "label": "반기보고서"})
    d = M.down_nodes(custs, buyers, orders, None, period, lead_name="삼성전기")
    assert [x["kind"] for x in d] == ["customer", "buyer", "buyer", "contract"]
    assert d[0]["why"] == "매출처 26.0% (2026 반기)" and d[1]["name"] == "SFA반도체" and d[1]["why"] == "SFA반도체 반도체 매입 중 PCB 90.3%"
    assert d[2]["pct"] == 31.47 and d[2]["why"] == "영풍 FPCB, PCB 부문 BASE 매입 중 삼성전기 31.5% · BGA PCB 줄에도"      # 같은 회사는 하나로 — 첫 줄 비중(큰 쪽을 고르지 않는다)
    assert d[3]["why"] == "공급계약 5건 · 3.66조" and d[3]["code"] is None
    d2 = M.down_nodes([{"name": "LG전자", "pct": 30.0, "link": {"code": "066570"}, "seg": "VS부문", "basis": "부문"}], [], [], None, "2025")
    assert d2[0]["why"] == "VS부문 매출처 30.0% (2025)"                                                  # 부문별 매출처 표면 그 부문 매출의 몫
    assert M.period_label({"stamp": "2026-03", "label": "분기보고서"}) == "2026 1분기" and M.period_label({"stamp": "2025-12", "label": "사업보고서"}) == "2025"


def test_peer_nodes_put_supply_chain_last():
    rows = [{"code": c, "name": c, "group": g} for c, g in
            [("011070", "B"), ("005070", "B"), ("000670", "B"), ("091700", "B"), ("353200", "C"), ("001820", "C"), ("008060", "C"), ("097520", "C"), ("126730", "D")]]
    up = [{"items": [{"item": "FILM", "sup": [{"name": "COSMO", "code": "005070"}, {"name": "TORAY", "code": None}]}], "listed": [{"code": "005070"}]}]
    down = [{"kind": "buyer", "code": "000670"}, {"kind": "contract", "code": None}]
    got = [p["code"] for p in M.peer_nodes(rows, up, down)]
    assert got == ["011070", "091700", "353200", "001820", "008060", "097520"]           # 코스모신소재 · 영풍(위 · 아래 칸)은 밀려남, D 는 안 든다
    assert [p["code"] for p in M.peer_nodes(rows[:3], up, down)] == ["011070", "005070", "000670"]   # 모자라면 채운다


def test_node_rel_names_report_and_table():
    d = {"name": "삼성전기", "src": {"vc": {"period": "2026 반기"}, "own": {"src": "2026-06 반기보고서 · 상세표 · 회사의 개요"}},
         "net": {"holdings": [{"name": "삼성중공업", "code": "010140", "pct": 2.1, "purpose": "경영참여"}],
                 "up": [{"seg": "광학솔루션", "items": [{"item": "ACTUATOR", "pct": 22.3, "sup": [{"name": "HAESUNG OPTICS", "code": "076610", "co": "해성옵틱스"}]}], "listed": []}]}}
    r = M.node_rel(d, "010140")
    assert [(x["t"], x["src"]) for x in r] == [("삼성전기 보유 2.10% · 경영참여", "2026-06 반기보고서 · 타법인출자 현황(상세)")] and "url" not in r[0]   # 접수번호 없으면 링크 없음
    r = M.node_rel(d, "076610")
    assert [(x["t"], x["src"]) for x in r] == [("광학솔루션 원재료 ACTUATOR 매입처 · 매입 비중 22.3% · 보고서 표기 'HAESUNG OPTICS'",
                                              "삼성전기 2026 반기보고서 원재료 표")]
    d["src"]["vc"]["rcept"] = "20260814003805"
    d["src"]["own"]["rcept"] = "20260814003805"
    assert M.node_rel(d, "076610")[0]["url"] == M.DART % "20260814003805" and M.node_rel(d, "076610")[0]["date"] == "20260814"
    assert M.node_rel(d, "010140")[0]["url"] == M.DART % "20260814003805"


def test_payload_shape_and_node_rel():
    rows = [dict(M.score(_c(prod=[("MLCC", "MLCC")]), lead_p3=50, px={"p1": 50, "p3": 10}, ph=PH, up=40.0), code="001820", name="삼화콘덴서"),
            dict(M.score(_c(themes=["MLCC"]), lead_p3=50, px={"p1": 50, "p3": 90}, ph=None), code="126730", name="코칩")]
    rows = M.sort_rows(rows)
    net = {"owner": {"name": "삼성전자", "code": "005930", "pct": 23.69, "rel": "최대주주 본인", "src": "2025-12 사업보고서"},
           "holdings": [{"name": "삼성중공업", "code": "010140", "pct": 2.1, "purpose": "경영참여"}], "up": [], "down": [], "peers": []}
    d = M.payload(code="009150", name="삼성전기", built="2026-10-12 09:00:00", leader={"code": "009150"}, story={"words": []},
                  triggers=[], net=net, matrix=rows, src={})
    assert set(d) == {"v", "code", "name", "built", "head", "net", "matrix", "src", "note"} and d["note"] == M.NOTE
    assert set(d["head"]) == {"leader", "story", "triggers", "counts"}
    assert d["head"]["counts"] == {"total": 2, "B": 1, "C": 0, "D": 1, "Fake": 0} and d["matrix"][0]["code"] == "001820"
    r0 = d["matrix"][0]
    assert set(r0["parts"]) == {"link", "fund", "attn", "lag", "safe"} and set(r0["ev"]) == set(r0["parts"])
    assert all(set(x) >= {"t", "src"} for v in r0["ev"].values() for x in v) and r0["expl"] and r0["group_note"]     # 근거는 모두 객체
    o = M.node_rel(d, "005930")[0]
    assert (o["t"], o["src"]) == ("삼성전기 최대주주 23.69%", "2025-12 사업보고서") and "url" not in o      # '최대주주 최대주주 본인' 겹침 없이 · 접수번호 없으면 링크 없음
    assert [x["t"] for x in M.node_rel(d, "010140")] == ["삼성전기 보유 2.10% · 경영참여"]
    rel = M.node_rel(d, "001820")
    assert rel[0]["t"].startswith("후속주 B군") and rel[0]["src"] == M.NOTE and rel[1]["t"].startswith("같은 제품 'MLCC'")
    json.dumps(d, ensure_ascii=False)


# ---------------------------------------------------------------- 9. 서버 vcmap_view 배선(서버를 띄우지 않고 모듈만)
CO = "999990"


@pytest.fixture(scope="module")
def SRV():
    sp = ilu.spec_from_file_location("서버_vcmap_시험", os.path.join(BASE, "서버.py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


@pytest.fixture
def srv(SRV, monkeypatch, tmp_path):
    co = {"code": CO, "name": "가나전자", "dir": "x", "reports": [{"stamp": "2026-06", "label": "반기보고서", "tag": "", "rcept": "20260814000123",
                                                                    "dir": "r", "sections": []}]}
    monkeypatch.setattr(SRV, "INDEX", {"companies": [co], "built": 0})
    monkeypatch.setattr(SRV, "company_by_code", lambda c: co if c == CO else None)
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "VCMAP_DIR", str(tmp_path / "vcmap"))
    monkeypatch.setattr(SRV, "OWN_DIR", str(tmp_path / "own"))
    monkeypatch.setattr(SRV, "STORY_DISC_DIR", str(tmp_path / "공시목록"))
    monkeypatch.setattr(SRV, "VCMAP", {"running": False, "code": None, "step": "", "want": {}, "err": {}, "memo": {}, "xs_fail": 0.0, "force": set()})
    monkeypatch.setattr(SRV, "_story_disc", lambda: None)
    xs = {"v": SRV.VCMAP_XS_V, "date": "20261008", "at": time.time(), "rows": {CO: {"d": "20261008", "px": 100.0, "hi": 120.0, "hd": "20260601",
                                                                               "dd": -16.7, "r1": 1.0, "r3": 2.0, "r6": 3.0, "p1": 50, "p3": 50, "p6": 50}}}
    box = {"xs": xs}
    monkeypatch.setattr(SRV, "_vcmap_xs_read", lambda: box["xs"])
    monkeypatch.setattr(SRV, "_vcmap_xs_stale", lambda x, code=None: False)
    monkeypatch.setattr(SRV, "_rep_rows", lambda: {"by_code": {CO: [{"date": "2026-10-01 08:00", "title": "가나전자 MLCC 호황", "lines": ["MLCC"],
                                                                      "broker": "가나증권", "msg_url": "https://t.me/c/1"}]}})
    monkeypatch.setattr(SRV, "_REP", {"sig": "x", "rows": [], "by_code": {}})
    monkeypatch.setattr(SRV, "valuechain_view", lambda code: {"error": "없음"})
    monkeypatch.setattr(SRV, "_vc_peers", lambda: {"prod": {}})
    monkeypatch.setattr(SRV, "_vcmap_linker", lambda build=True: M.Linker([], {CO: "가나전자"}))
    (tmp_path / "공시목록").mkdir()
    SRV._box = box
    return SRV


def _wait(SRV, sec=20):
    t = time.time()
    while SRV.VCMAP["running"] and time.time() - t < sec:
        time.sleep(0.05)


def test_vcmap_view_pending_then_fresh(srv):
    assert srv.vcmap_view("888888") is None
    p = srv.vcmap_view(CO)
    assert p["pending"] is True and "step" in p
    _wait(srv)
    d = srv.vcmap_view(CO)
    assert d.get("pending") is None and d["stale"] is False and "sig" not in d
    assert d["code"] == CO and d["head"]["leader"]["px"] == 100.0 and d["head"]["counts"]["total"] == 0 and d["note"] == M.NOTE
    assert d["net"]["owner"] is None and d["head"]["story"]["line"]["by"] == "가나증권"
    assert os.path.exists(os.path.join(srv.VCMAP_DIR, CO + ".json")) and os.path.exists(os.path.join(srv.OWN_DIR, CO + ".json"))
    assert srv.vcmap_view(CO)["built"] == d["built"]                                      # 같은 sig → 다시 안 만든다
    n = srv.vcmap_node(CO, CO)
    assert n["code"] == CO and n["px"]["px"] == 100.0 and n["reports_n"] == 0 and n["rel"] == []


def test_vcmap_view_stale_while_rebuilding(srv, monkeypatch):
    srv.vcmap_view(CO)
    _wait(srv)
    first = srv.vcmap_view(CO)["built"]
    gate = threading.Event()
    real = srv.VMAP.payload
    monkeypatch.setattr(srv.VMAP, "payload", lambda **kw: (gate.wait(5), real(**kw))[1])
    srv._box["xs"] = dict(srv._box["xs"], date="20261012")                                # 단면 날짜 → sig 바뀜
    d = srv.vcmap_view(CO)
    assert d["stale"] is True and d["built"] == first
    gate.set()
    _wait(srv)
    d2 = srv.vcmap_view(CO)
    assert d2["stale"] is False and d2["src"]["xs"]["date"] == "20261012"


def test_vcmap_view_refresh_rebuilds_once_with_same_inputs(srv):
    srv.vcmap_view(CO)
    _wait(srv)
    first = srv.vcmap_view(CO)["built"]
    time.sleep(1.05)
    d = srv.vcmap_view(CO, refresh=True)
    assert d["stale"] is True and d["built"] == first                                      # 입력이 같아도 한 번 다시
    _wait(srv)
    d2 = srv.vcmap_view(CO)
    assert d2["stale"] is False and d2["built"] > first and not srv.VCMAP["force"]


def test_vcmap_view_error_once_then_build_error_keeps_payload(srv, monkeypatch):
    calls = []

    def boom(**kw):
        calls.append(1)
        raise RuntimeError("시험 실패")
    monkeypatch.setattr(srv.VMAP, "payload", boom)
    srv.vcmap_view(CO)
    _wait(srv)
    assert srv.vcmap_view(CO) == {"error": "RuntimeError: 시험 실패"}
    _wait(srv)
    srv.vcmap_view(CO)
    _wait(srv)
    assert len(calls) == 1                                                                # 같은 입력이면 ERR_TTL 동안 다시 안 만든다


# ---------------------------------------------------------------- 10. 검토 고침(2026-10-12) — 실제 보고서 · 캐시 꼴을 줄여 지어낸 것
def _sh(*rows):
    return "1. 최대주주 및 특수관계인의 주식소유 현황\n\n" + cells(HEAD, SUB, *rows)


def test_owner_skips_zero_issuer_and_takes_top_relation():
    # 애경산업 — 기간 중 판 옛 최대주주(기말 0%)가 아니라 새 최대주주
    o = M.owner_of({"sh": _sh(["에이케이홀딩스(주)", "최대주주", "보통주", "11,904,812", "45.08", "0", "0.00", "주식양도"],
                              ["뷰티라이프원(유)", "최대주주", "보통주", "0", "0.00", "8,336,290", "31.56", "주식양수"])})
    assert (o["name"], o["pct"], o["kind"]) == ("뷰티라이프원", 31.56, "corp")
    # 코웨이 — '최대주주의최대주주' 행이 아니라 '최대주주 본인'
    o = M.owner_of({"sh": _sh(["방준혁", "최대주주의최대주주", "보통주", "0", "0.00", "107,942", "0.15", "장내매매"],
                              ["넷마블(주)", "최대주주 본인", "보통주", "18,511,446", "25.74", "18,943,446", "26.77", "장내매매"])})
    assert (o["name"], o["pct"]) == ("넷마블", 26.77)
    # 트리니티항공 — 발행회사 자기주식 행 빼기 · NAVER — '본인' 0% 행 대신 기금
    o = M.owner_of({"sh": _sh(["(주)트리니티항공", "발행회사", "보통주", "205,392", "0.06", "205,392", "0.05", "의결권이 없는 주식 (자기주식)"],
                              ["(주)소노인터내셔널", "최대주주 본인", "보통주", "146,406,125", "43.58", "173,259,867", "41.95", "-"])})
    assert o["name"] == "소노인터내셔널" and o["pct"] == 41.95
    o = M.owner_of({"sh": _sh(["국민연금공단", "본인", "보통주", "0", "0", "0", "0", "-"],
                              ["국민연금기금", "특수관계인", "보통주", "14,502,670", "9.25", "13,504,269", "8.91", "장내매도"])})
    assert (o["name"], o["pct"]) == ("국민연금기금", 8.91)
    # 대주전자재료 — 관계 '부' 첫 행이 아니라 '최대주주' · 셀트리온 — '본인'(홀딩스)과 '최대주주'(사람)를 거꾸로 적어도 큰 쪽
    o = M.owner_of({"sh": _sh(["임무현", "부", "보통주", "807,176", "5.21", "807,176", "5.14", "-"],
                              ["임중규", "최대주주", "보통주", "1,121,500", "7.24", "1,121,500", "7.14", "-"])})
    assert (o["name"], o["kind"]) == ("임중규", "person")
    o = M.owner_of({"sh": _sh(["(주)셀트리온홀딩스", "본인", "보통주", "56,448,667", "24.44", "60,125,135", "25.85", "-"],
                              ["서정진", "최대주주", "보통주", "9,310,000", "4.03", "9,775,500", "4.20", "-"])})
    assert o["name"] == "셀트리온홀딩스"
    # 비고 '자기주식 소각에 따른 지분율 변동'은 빼는 까닭이 아니다(SK디스커버리) · 계 행 뒤 다른 표(CJ제일제당)는 안 본다
    o = M.owner_of({"sh": _sh(["최창원", "본인", "보통주", "7,650,128", "43.93", "7,650,128", "43.93", "자기주식 소각에 따른 지분율 변동"],
                              ["계", "보통주", "7,650,128", "43.93", "7,650,128", "43.93", "-"],
                              ["이재현", "최대주주 본인", "보통주", "1", "42.07", "1", "42.07", "-"])})
    assert (o["name"], o["pct"], o["total"]) == ("최창원", 43.93, 43.93)
    # 보통주 행이 다 0% 면 None(서버가 앞 보고서로)
    assert M.owner_of({"sh": _sh(["가", "최대주주", "보통주", "0", "0", "0", "0", "-"])}) is None


@pytest.mark.parametrize("kind", ["의결권 있는 주식(보통주)", "보통주 (의결권있는주식)", "의결권이 있는 주식", "의결권이있는 주식", "기명식 보통주",
                                  "보통주(의결권 있음)", "보통주식", "의결권 있는 보통주"])
def test_owner_share_kind_spellings(kind):
    o = M.owner_of({"sh": _sh(["함영준", "본인", kind, "1,004,949", "25.07", "1,004,949", "25.07", "-"])})
    assert o and (o["name"], o["pct"]) == ("함영준", 25.07)
    assert M.KIND_RX.match("의결권 없는 주식(보통주)") and not M._common("의결권 없는 주식(보통주)") and not M._common("종류주식(우선주)")


def test_owner_footnote_cell_and_person_names():
    o = M.owner_of({"sh": _sh(["(주)성우홀딩스", "(주1)", "최대주주", "보통주", "26,190,556", "32.74", "26,190,556", "32.74", "-"],
                              ["이명근", "본인", "보통주", "4,643,088", "5.80", "4,643,088", "5.80", "-"])})
    assert (o["name"], o["rel"], o["pct"], o["kind"]) == ("성우홀딩스", "최대주주", 32.74, "corp")
    o = M.owner_of({"sh": _sh(["이 재 용", "최대주주 본인", "보통주", "33,880,220", "19.76", "35,688,797", "21.81", "-"])})
    assert (o["name"], o["kind"]) == ("이재용", "person")
    o = M.owner_of({"sh": _sh(["김종훈(등기)", "본인", "보통주", "1,139,920", "10.40", "1,139,920", "10.40", "-"])})
    assert (o["name"], o["kind"]) == ("김종훈", "person")
    o = M.owner_of({"sh": _sh(["대명화학", "최대주주", "보통주", "17,366,382", "53.69", "30,915,196", "53.70", "-"])})
    assert (o["name"], o["kind"]) == ("대명화학", "corp")


def test_holdings_skip_preferred_rcps_and_group_stock_codes():
    dt_ = "3. 타법인출자 현황(상세)\n\n" + cells(
        ["솔루스첨단소재㈜(우1)", "상장", "2019.10.01", "단순투자", "1", "1", "2.59", "1", "-", "-", "-", "1", "2.59", "1", "1", "1"],
        ["로킷헬스케어16 RCPS", "상장", "2021.01.01", "단순투자", "1", "1", "3.48", "1", "-", "-", "-", "1", "3.48", "1", "1", "1"],
        ["삼성중공업(주)", "상장", "1983.11.30", "경영참여", "600", "1", "2.1", "1", "-", "-", "-", "1", "2.1", "1", "1", "1"])
    assert [h["name"] for h in M.holdings_of({"dt": dt_}, LK.code)] == ["삼성중공업"]
    g = M.affiliates_listed({"dt": "2. 계열회사 현황(상세)\n\n" + cells(["상장", "3", "씨제이 (종목코드 001040)", "1101110000001"],
                                                                     ["씨제이씨지브이 (종목코드: 079160)", "1101110000002"], ["해당사항 없음"],
                                                                     ["비상장", "1", "가(주)", "1"])}, LK.code)
    assert g["names"] == [["씨제이", "001040"], ["씨제이씨지브이", "079160"]]


def test_linker_listed_code_exact_english_name():
    lk = M.Linker(CORPS + [("012030", "DB", "DB Inc.", "20260314")], COLLECTED)
    assert lk.code("DB Inc.") is None                          # 아무 이름에는 4자 미만 영문을 잇지 않는다
    assert lk.listed_code("DB Inc.") == "012030"               # 계열 '상장' 블록 이름이면 corp_eng_name 통째
    assert lk.listed_code("SK위탁관리부동산투자회사") is None     # 한글이 든 이름은 영문 통째 길로 가지 않는다


def test_product_words_floor_revenue_items_and_broad_words():
    db = [{"item": "Wafer 등", "pct": 97.7}, {"item": "그린피, 자산관리 등", "pct": 1.7}, {"item": "건축/환경플랜드", "pct": 0.6}]
    assert M.product_words(db) == ["Wafer"]                                                   # 5% 미만 줄은 빼기(DB하이텍 → 건설사)
    mc = [{"item": "구동계", "pct": 14.61}, {"item": "카메라모듈", "pct": 26.76}, {"item": "생체인식", "pct": 4.95},
          {"item": "상품매출", "pct": 6.0}, {"item": "개발매출", "pct": 5.5}, {"item": "매출총계", "pct": 100.0}]
    assert M.product_words(mc) == ["구동계", "카메라모듈", "생체인식"]                          # 매출 구분 말 빼기 · 4.95 = 5.0
    lg = [{"item": "모터/센서, 통신, Lighting Solution, Power Module 등", "pct": 9.0}, {"item": "반도체기판, Tape Substrate", "pct": 8.5}]
    ws = M.product_words(lg)
    assert not {"모터", "센서", "통신"} & set(ws) and "기판" in ws
    assert M.product_words([{"item": "여객주1)", "pct": 80.0}]) == ["여객"]
    assert M.prod_hits([("상품매출(의류 등)", None, 50.0)], [("상품매출", "상품매출")]) == []        # 남의 줄도 매출 구분이면 같은 제품 아님
    assert M.products_of([{"item": "('11.1.1~09.30)", "pct": 10.1}, {"item": "복합기", "pct": 1.1}])[0]["item"] == "복합기"
    nx = [{"segment": "타이어", "item": "임대, 렌탈 및 용역 등", "pct": 2.26}, {"segment": "비타이어", "item": "금형", "pct": 0.03}]
    assert M.product_words(nx) == [] and "타이어" in M.segment_words(nx)                       # 넥센타이어 — 부문 이름으로 테마를
    assert M.segment_words([{"segment": "DX 부문", "item": "TV", "pct": 60}, {"segment": "Harman", "item": "카오디오", "pct": 2.7}]) == []


def test_report_triggers_capex_needs_capex_word_and_skips_noise():
    row = lambda ln, d="2026-09-01", t="글": {"date": d, "title": t, "broker": "B", "msg_url": "u", "lines": [ln]}     # noqa: E731
    cases = ["현금성자산 181조원 확보로 투자 및 재무건전성 기반 마련", "기관 3.9조원 순매수 · 투자주체별 수급",
             "배당가능이익 약 2.5조원으로 투자수익률 개선", "테일러팹 가동과 함께 비용 요인이 지속 출회하며, 영업손실 1.5조원으로 적자",
             "2026년 CAPEX 상향(1,300~1,450억달러)", "대규모 CapEx에도 250조원 육박의 자유현금흐름(FCF) 기반 주주환원",
             "공장 수처리 사업권 확보로 약 800억원 매출 추가 가능"]
    for ln in cases:
        assert "capex" not in M.report_triggers([row(ln)], "2026-06-01"), ln
    assert "order" not in M.report_triggers([row("손실부담계약비용 약 2,700억원 환입")], "2026-06-01")
    r = M.report_triggers([row("서버 가속기 관련 계약 구체화 기대, 베트남 신공장 CapEx 2조원 상회 예상")], "2026-06-01")
    assert set(r) == {"capex"}                                                                 # 계약 … CapEx 금액은 수주가 아니다
    r = M.report_triggers([row("건설 부문 2Q 수주 5.4조원 달성, 반도체 팹 등 대형 프로젝트")], "2026-06-01")
    assert set(r) == {"order"}                                                                 # 한 줄은 앞 범주 하나만
    # 여러 종목에 붙은 행(업종 카드) — 줄 · 제목에 내 이름이 없으면 안 쓴다
    card = row("청주 생산기지 100조원 투자로 낸드 증설", t="반도체(Overweight)")
    skip = M.shared_rows({"005930": [card], "000660": [card]}, "2026-06-01", k=2)
    assert M.report_triggers([card], "2026-06-01", skip=skip, name="삼성전자") == {}
    assert "capex" in M.report_triggers([dict(card, lines=["삼성전자 평택 50조원 증설"])], "2026-06-01", skip=skip, name="삼성전자")
    # 금액 없는 설비투자 공시는 증설 · CAPEX 를 말하는 리포트 줄만 갈음한다
    disc = [{"kind": "capex", "text": "설비투자 공시 · 신규시설투자등", "src": "공시", "date": "20260807", "url": "c", "amount": None}]
    p = M.pick_triggers(disc, {"capex": {"kind": "capex", "text": "M15X 라인 20조원 투입", "src": "리포트"}})
    assert [(x["kind"], x["src"]) for x in p] == [("capex", "공시")]
    p = M.pick_triggers(disc, {"capex": {"kind": "capex", "text": "청주 20조원 증설", "src": "리포트"}})
    assert [(x["kind"], x["src"]) for x in p] == [("capex", "리포트")] and p[0]["note"].startswith("공시 2026.08.07")


def test_story_words_strip_urls_boilerplate_and_stop_words():
    ln = "https://buly.kr/Ga0TyFZ 위 문자는 컴플라이언스의 승인을 득하였음 텔레그램 채널 신한생각 저평가 추가 매년 은행 CET-1"
    rows = [{"date": "2026-10-0%d" % (i + 1), "title": "KB금융 은행 CET-1", "lines": [ln]} for i in range(5)]
    ws = [w["w"] for w in M.story_words(rows, "2026-07-01", "KB금융", NAR.hot_words, code="105560", top=12)]
    assert "은행" in ws and not {"buly", "https", "문자", "득하였음", "신한생각", "저평가", "추가", "매년", "텔레그램"} & set(ws)


def test_rep_scan_two_syllable_korean_key_boundary_and_loose_df():
    rows = [{"date": "2026-09-01", "title": "중앙은행 금리", "lines": []}, {"date": "2026-09-02", "title": "은행 NIM 개선", "lines": []},
            {"date": "2026-09-03", "title": "PCB 수요", "lines": []}]
    assert M.rep_scan(rows, "2026-04-15", [("은행", "은행")]) == [{"은행"}]                    # '중앙은행'은 은행 언급이 아니다
    assert M.rep_scan(rows, "2026-04-15", [("기판", "기판")]) == [{"기판"}]                    # PCB = 기판(SYN)은 앞 글자 조건을 넘는다
    df = Counter()
    M.rep_hits({"A": rows[:1], "B": rows[1:2]}, "2026-04-15", [("은행", "은행")], df=df)
    assert df["은행"] == 2 and M.broad_words(None, 1, df) == {"은행"}                          # 넓은 말 셈은 느슨하게


def test_candidates_fill_narrow_themes_industry_gate_and_rank():
    stocks = {"005830": {"themes": ["손해보험", "밸류업(25년)"], "industry": "손해보험", "sector": "금융"},
              "000810": {"themes": ["손해보험", "밸류업(25년)"], "industry": "손해보험"}, "001450": {"themes": ["손해보험"], "industry": "손해보험"},
              "999999": {"themes": ["밸류업(25년)"], "industry": "식품"}}
    univ = {c: 1 for c in stocks}
    c = M.candidates("005830", univ=univ, stocks=stocks)
    assert set(c) == {"000810", "001450"} and M.link_score(c["000810"]) == 1                  # 좁은 테마로 채움 · 밸류업(META)은 안 씀
    assert c["000810"]["nth"] == 1 and c["001450"]["nth"] == 1
    # 업종 거름 — 같은 industry 는 그대로, 공급망 후보 업종은 동시 언급 2건↑, sector 만 같으면 빠짐(철강 ≠ 화학)
    st2 = {"004020": {"themes": [], "industry": "철강", "sector": "화학/소재"}, "S": {"themes": [], "industry": "자동차부품", "sector": "자동차"},
           "STEEL": {"themes": [], "industry": "철강", "sector": "화학/소재"}, "CHEM": {"themes": [], "industry": "화학", "sector": "화학/소재"},
           "AUTO1": {"themes": [], "industry": "자동차부품", "sector": "자동차"}, "AUTO2": {"themes": [], "industry": "자동차부품", "sector": "자동차"}}
    r = lambda n, t: [{"date": "2026-09-0%d" % (i + 1), "title": "%s %d" % (t, i), "lines": ["스프레드"]} for i in range(n)]     # noqa: E731
    reps = {"STEEL": r(1, "철강"), "CHEM": r(3, "화학"), "AUTO1": r(2, "자동차"), "AUTO2": r(1, "부품")}
    c = M.candidates("004020", univ={k: 1 for k in st2}, stocks=st2, reps=reps, since180="2026-04-15", rep_keys=[("스프레드", "스프레드")],
                     supply={"S": [{"w": "w", "s": "s"}]})
    assert set(c) == {"S", "STEEL", "AUTO1"}
    # 30줄 자르기 순위 — 주도주 테마를 더 많이 같이 든 회사가 앞(한미반도체 HBM)
    a, b = M.candidates("042700", univ={"A": 1, "B": 1}, stocks={"042700": {"themes": ["반도체 장비", "HBM"]}, "A": {"themes": ["반도체 장비"]},
                                                                "B": {"themes": ["반도체 장비", "HBM"]}},
                        phrases=M.phrase_tokens([{"item": "반도체 제조용 장비 外"}])).values()
    assert M.evidence_rank(b) > M.evidence_rank(a)


def test_weak_supply_light_risk_and_why_keyword():
    weak = _c(supply=[{"w": "영풍이 삼성전기를 매입처로 적음 — 연결 자회사(코리아써키트) 매입", "s": "연결 자회사 매입 · 코리아써키트", "weak": True}])
    assert M.link_score(weak) == 3 and M.link_score(dict(weak, prod=[("기판", "PCB")])) == 4
    assert M.why_line(dict(weak, prod=[("기판", "PCB")]), None, 2, "C", []).startswith("기판 동종")
    s = M.score(_c(rep_n=8, rep_by=Counter({"DRAM": 8})), lead_p3=None, px=None, ph=PH)
    assert s["why"].startswith("DRAM 리포트 8건")                                              # 리포트만이면 낱말을 붙인다
    light = {"level": "작전주 꼴", "hits": [{"cat": "금전대여", "days": 3}]}
    assert M.risk_flags(light) == (3, ["자금 거래"]) and M.risk_flags(dict(light, hits=[{"cat": "CB발행"}]))[0] == 0


def test_down_nodes_drop_non_companies_merge_same_code_and_up_names():
    custs = [{"name": "삼성전자", "pct": 26.0, "link": {"code": "005930"}}, {"name": "이자율스왑", "pct": 3.7}, {"name": "카드론수익", "pct": 9.0},
             {"name": "A 거래처", "pct": 5.0}]
    buyers = [{"code": "005930", "name": "삼성전자", "pct": 7.9, "items": ["Camera Module"]}]
    d = M.down_nodes(custs, buyers, [], None, "2026 반기")
    assert [(x["kind"], x["name"]) for x in d] == [("customer", "삼성전자")]
    assert d[0]["why"] == "매출처 26.0% (2026 반기) · 매입 중 Camera Module 7.9%"
    up = M.up_groups([{"item": "코드", "pct": 20.0, "suppliers": [{"name": "효성"}, {"name": "효성"}, {"name": "㈜파트론"}]}], [], None)
    assert [s["name"] for s in up[0]["items"][0]["sup"]] == ["효성", "파트론"]
    assert M.node_name({"matrix": [{"code": "005930", "name": "삼성전자"}]}, "005930") == "삼성전자" and M.node_name(None, "x") is None


def test_item_fit_for_short_supplier_names():
    assert M.item_fit("수동소자", [("콘덴서", None, 88.0)]) and M.item_fit("수동소자", [("MLCC", None, 55.3)])
    assert not M.item_fit("수동소자", [("PPC", None, 32.6), ("이축연신필름", None, 17.5)])
    assert M.BUNDLE_RX.search("WAFER 외") and M.BUNDLE_RX.search("강재, 기자재, 의장재 등") and not M.BUNDLE_RX.search("PCB")


def test_server_line_link_and_weak_buyers(srv, monkeypatch):
    univ = {"003720": "삼영", "005680": "삼영전자공업", "001820": "삼화콘덴서공업", "009470": "삼화전기"}
    prod = {"003720": [("PPC", None, 32.6)], "005680": [("콘덴서", None, 88.0)], "001820": [("MLCC", None, 55.3)], "009470": [("전해콘덴서", None, 50.9)]}
    link = {"삼영": "003720"}.get
    assert srv._vcmap_line_link("삼영", "수동소자", link, prod, univ) == "005680"             # 삼영(필름)이 아니라 삼영전자공업
    assert srv._vcmap_line_link("삼화", "수동소자", link, prod, univ) is None                 # 둘이 맞으면 잇지 않는다
    assert srv._vcmap_line_link("TORAY", "FILM", lambda nm: "X", prod, univ) == "X"
    co = {"code": "000670", "name": "영풍"}
    monkeypatch.setattr(srv, "company_by_code", lambda c: co if c == "000670" else None)
    monkeypatch.setattr(srv, "_vcmap_own", lambda c: {"holdings": [{"name": "코리아써키트", "code": "007810", "pct": 40.96, "purpose": "경영참여"}]})
    cands = {"000670": _c(supply=[{"w": "영풍이 삼성전기를 매입처로 적음 · BASE", "s": "삼성전기 고객 · BASE", "k": "buyer"}]),
             "007810": _c(prod=[("기판", "PCB")])}
    srv._vcmap_weak_buyers(cands, ["000670", "000670"])                                       # 같은 회사가 줄마다 두 번 와도 한 번만
    assert M.link_score(cands["000670"]) == 3 and cands["000670"]["supply"][0]["w"].count("연결 자회사(코리아써키트)") == 1


def test_vcmap_build_drops_bundled_line_competitors(srv, monkeypatch):
    names = {CO: "가나전자", "B00001": "바이어", "C00001": "경쟁일", "C00002": "경쟁이", "C00003": "경쟁삼"}
    monkeypatch.setattr(srv, "INDEX", {"companies": [dict(srv.company_by_code(CO))] + [{"code": k, "name": v, "reports": []} for k, v in names.items() if k != CO],
                                       "built": 0})
    monkeypatch.setattr(srv, "_vcmap_linker", lambda build=True: M.Linker([], names))
    monkeypatch.setattr(srv, "valuechain_view", lambda code: {"buyers": [{"code": "B00001", "name": "바이어", "pct": 50.0}], "years": []})
    monkeypatch.setattr(srv, "_vcmap_buyer_lines", lambda b, k: [{"item": "WAFER 외", "pct": None, "others": ["경쟁일", "경쟁이"], "seg": None, "per_sup": False},
                                                                  {"item": "PCB", "pct": 90.3, "others": ["경쟁삼"], "seg": "반도체", "per_sup": False}])
    srv.vcmap_view(CO)
    _wait(srv)
    d = srv.vcmap_view(CO)
    rows = {r["code"]: r for r in d["matrix"]}
    assert "B00001" in rows and "C00003" in rows and not {"C00001", "C00002"} & set(rows)
    b = rows["B00001"]
    assert b["ev"]["link"][0]["t"] == "바이어가 가나전자를 WAFER 외 매입처로 적음" and b["expl"].startswith("바이어는 가나전자를 WAFER 외 매입처로 적었다(")     # 첫 줄엔 비중 없음 → 비중 말 없음
    assert d["net"]["down"][0]["why"] == "바이어 매입 중 WAFER 외 (비중 미기재) · PCB 줄에도"


def test_vcmap_view_stale_while_daily_cross_section_rebuilds(srv, monkeypatch):
    srv.vcmap_view(CO)
    _wait(srv)
    first = srv.vcmap_view(CO)
    assert first["stale"] is False
    box = {"old": True}
    monkeypatch.setattr(srv, "_vcmap_xs_stale", lambda x, code=None: box["old"])
    gate = threading.Event()

    def rebuild():
        gate.wait(5)
        box["old"] = False
        return srv._box["xs"]                      # 날짜 그대로 — 회사 판은 다시 안 만든다
    monkeypatch.setattr(srv, "_vcmap_xs_build", rebuild)
    d = srv.vcmap_view(CO)
    assert d["stale"] is True and d["built"] == first["built"]       # 그날 첫 화면 — 단면을 다시 만드는 동안은 stale(화면이 다시 묻는다)
    gate.set()
    _wait(srv)
    assert srv.vcmap_view(CO)["stale"] is False


def test_vcmap_node_never_rebuilds_linker_in_request(srv, monkeypatch):
    calls = []

    def lk(build=True):
        calls.append(build)
        return None                                 # 아직 지은 Linker 가 없다
    monkeypatch.setattr(srv, "_vcmap_linker", lk)
    os.makedirs(srv.VCMAP_DIR, exist_ok=True)
    with open(os.path.join(srv.VCMAP_DIR, CO + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "가나전자", "net": {"owner": {"name": "다라홀딩스", "code": "777770", "pct": 30.0}}, "matrix": []}, fh, ensure_ascii=False)
    n = srv.vcmap_node("777770", CO)
    assert n["name"] == "다라홀딩스" and n["collected"] is False and calls == [False]
    assert n["rel"][0]["t"].startswith("가나전자 최대주주 30.00%")


# ---------------------------------------------------------------- 11. 2차 개선(2026-10-13) — 출처 붙은 근거 · 설명 문장 · 과거 공급망 · 같은 고객 · 차감 · 트리거 자르기
SRCS = {"theme": "네이버 금융 테마 분류 2026-10-11", "xs": "종가 20261013 · 전 종목 988곳 단면", "xs_date": "20261013", "kis_date": "20261013", "risk_date": "20261013",
        "prod": ("대덕전자 2025 사업보고서 「사업의 내용」 주요 제품 표", "20260310", M.DART % "20260310003071")}


def test_ev_objects_carry_sources_and_links():
    assert M.ev("x", "s", "2026-10-08 07:25", "u", {"tab": "rep"}) == {"t": "x", "src": "s", "date": "20261008", "url": "u", "go": {"tab": "rep"}}
    assert M.ev("x", None, None, None, None) == {"t": "x", "src": None}            # 없는 값은 키를 뺀다(화면 vbEv 는 없는 키를 비어 있다고 읽는다)
    sup = {"w": "SFA반도체 PCB 매입처에 삼성전기와 함께 적힘(제품별 경쟁사)", "s": "PCB 동종 공급사", "k": "line",
           "src": "SFA반도체 2026 반기보고서 「사업의 내용」 원재료 매입처 표", "date": "20260814", "url": M.DART % "20260814000001", "d": {"name": "SFA반도체", "item": "PCB"}}
    refs = [{"date": "2026-10-02", "by": "하나증권", "url": "https://t.me/companyreport/1", "title": "FC-BGA 증설"},
            {"date": "2026-09-20", "by": None, "url": "https://t.me/companyreport/2", "title": "기판"}]
    s = M.score(_c(supply=[sup], prod=[("기판", "인쇄회로기판", 71.0)], rep_n=18, rep_by=Counter({"FC-BGA": 18}), rep_refs=refs, themes=["반도체 기판(FC-BGA/PCB/MLB 등)"]),
                lead_p3=45, px={"p1": 98, "p3": 87, "dd": -17.4}, ph=dict(PH, v=4, asof="20260813"), n_rep=34, up={"up": 27.0, "n": 5, "avg": 190000},
                lead_name="삼성전기", name="대덕전자", srcs=SRCS)
    L = s["ev"]["link"]
    assert [x["t"] for x in L][:2] == [sup["w"], "같은 제품 '인쇄회로기판' (매출 비중 71%)"]
    assert (L[0]["src"], L[0]["url"], L[0]["date"]) == (sup["src"], sup["url"], "20260814") and L[1]["src"] == SRCS["prod"][0] and L[1]["url"] == SRCS["prod"][2]
    rep = L[2]
    assert rep["t"] == "FC-BGA 리포트 18건(180일) — 최신 'FC-BGA 증설'" and rep["src"] == "하나증권 2026-10-02" and rep["url"].endswith("/1")
    assert rep["go"] == {"tab": "rep"} and rep["more"]["url"].endswith("/2") and rep["more"]["src"].startswith("증권사 미표기")
    assert L[3] == {"t": "네이버 테마 '반도체 기판(FC-BGA/PCB/MLB 등)' 같이 소속", "src": SRCS["theme"]} and len(L) == 4     # 테마는 한 줄에 둘까지
    f = s["ev"]["fund"][0]
    assert f["t"] == "확장 가속 · 가속B +23.5 · OPM 17.5% (2026Q2)" and f["go"] == {"tab": "druck"} and f["date"] == "20260813" and "v4" in f["src"] and "옛 판" in f["src"]
    a = s["ev"]["attn"]
    assert a[1]["t"] == "리포트 목표가 평균 190,000원 → +27%" and a[1]["src"] == "증권사 5곳 180일 증권사별 최신 목표가 평균" and a[1]["go"] == {"tab": "rep"}   # n 은 증권사 곳 수
    assert s["ev"]["lag"] == [{"t": "3개월 수익률 백분위 87 (주도주 45) · 52주 고점 대비 -17.4%", "src": SRCS["xs"]}]      # 날짜는 출처 줄에
    assert s["ev"]["safe"] == [{"t": "위험 꼬리표 없음", "src": "공시위험 · KIS 종목 상태 20261013"}]          # 두 기준일이 같으면 한 번만
    e = s["expl"]
    assert e.startswith("대덕전자는 SFA반도체의 PCB 매입처에 삼성전기와 함께 적혔다(2026 반기보고서 원재료 매입처 표).")       # 출처는 짧게(주어가 그 회사)
    assert "또 삼성전기와 같은 기판을 만든다(2025 사업보고서 주요 제품 표 '인쇄회로기판' 71%)." in e and M._eul("MLCC") == "를"
    assert "실적 국면은 확장 가속(2026Q2 · 가속B +23.5 · OPM 17.5%)이고 최근 180일 FC-BGA 리포트 18건이 있으며, 리포트 목표가 평균 190,000원 기준 상승여력은 +27%다." in e
    assert "주가는 3개월 수익률 백분위 87로 주도주(45)보다 앞섰고 52주 고점 대비 -17.4%이며, 위험 꼬리표는 없다(공시위험 · KIS 20261013)." in e
    s2 = M.score(_c(themes=["PCB(FPCB 등)", "유리 기판"]), lead_p3=45, px={"p1": 50, "p3": 60, "dd": -5.0}, ph=None, risk={"ref": [{"cat": "불성실_지정", "rows": [["20260624", "불성실공시법인지정", "R1"]]}]},
                 kis_tags=["투자경고"], lead_name="삼성전기", name="가", srcs=SRCS)
    assert s2["ev"]["link"][0]["t"] == "네이버 테마 'PCB(FPCB 등)' · '유리 기판' 같이 소속"
    assert s2["expl"].endswith("위험 꼬리표는 불성실공시(공시 20260624) · 투자경고(KIS 20261013)다.")             # 설명 문장의 출처는 짧게, 긴 제목 · 링크는 ev.safe 에
    json.dumps(s, ensure_ascii=False)


def test_history_supply_is_link_3_unless_current():
    h = {"w": "2020–2022년 삼성전기 PASTE/POWDER 매입처 'DAEJOO' (지금은 빠짐)", "s": "과거 삼성전기 매입처 · PASTE/POWDER", "k": "hist_sup",
         "src": "삼성전기 2022 사업보고서 「사업의 내용」 원재료 표", "date": "20230307", "url": M.DART % "20230307000653", "d": {"item": "PASTE/POWDER", "y1": "2020", "y2": "2022", "as": "DAEJOO"}}
    stocks = {"009150": {"themes": ["MLCC(적층세라믹콘덴서)"]}, "078600": {"themes": ["MLCC(적층세라믹콘덴서)"]}}
    c = M.candidates("009150", univ={"078600": 1, "005070": 1}, stocks=stocks, theme_keys=["mlcc"], hist={"078600": [h], "005070": [dict(h, w="w2")]},
                     supply={"005070": [{"w": "코스모신소재가 삼성전기를 매출처로 적음 · FILM", "s": "삼성전기 공급사", "k": "seller"}]}, lead_name="삼성전기")
    assert M.link_score(c["078600"]) == 3 and c["078600"]["supply"][0]["weak"] is True
    assert M.link_score(c["005070"]) == 5                                              # 지금 있으면 5 — 과거 줄은 덧붙는 근거일 뿐
    s = M.score(c["078600"], lead_p3=45, px={"p1": 50, "p3": 40, "dd": -30.0}, ph=PH, lead_name="삼성전기", name="대주전자재료", srcs=SRCS)
    assert s["parts"]["link"] == 3 and s["ev"]["link"][0]["url"] == h["url"] and s["ev"]["link"][0]["src"] == h["src"]
    assert s["expl"].startswith("대주전자재료는 2020–2022년 삼성전기의 PASTE/POWDER 매입처였다(지금은 빠짐 · 2022 사업보고서 원재료 표).")
    assert s["why"].startswith("과거 삼성전기 매입처 · PASTE/POWDER")


def test_same_customer_needs_matching_theme_or_product():
    stocks = {"009150": {"themes": ["카메라모듈/부품"]}, "190510": {"themes": ["카메라모듈/부품"]}, "000001": {"themes": ["반도체 장비"]}}
    same = {"190510": {"cust": "삼성전자", "pct": 96.0, "lead_pct": 26.0, "name": "나무가"}, "000001": {"cust": "삼성전자", "pct": 50.0, "lead_pct": 26.0, "name": "장비사"}}
    c = M.candidates("009150", univ={"190510": 1, "000001": 1}, stocks=stocks, theme_keys=["카메라모듈"], samecust=same, lead_name="삼성전기")
    assert set(c) == {"190510"}                                                        # 같은 고객만(장비사)으로는 후보가 아니다
    w = c["190510"]["supply"][0]
    assert M.link_score(c["190510"]) == 3 and w["k"] == "same" and w["w"] == "삼성전자에 매출 96% (삼성전기도 26%) · 카메라모듈/부품 테마"
    w.update(src="나무가 2026 반기보고서 「사업의 내용」 매출처 표", date="20260814", url=M.DART % "20260814002273")
    s = M.score(c["190510"], lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="나무가", srcs=SRCS)
    assert s["ev"]["link"][0]["url"].endswith("20260814002273") and s["ev"]["link"][1]["t"].startswith("네이버 테마 '카메라모듈/부품'")
    assert s["expl"].startswith("나무가는 삼성전기와 같은 고객 삼성전자에 팔고(매출 96%, 삼성전기도 26% · 2026 반기보고서 매출처 표) 네이버 테마 '카메라모듈/부품'에도 같이 들었다.")
    assert "가속도 자료는 없고" in s["expl"]
    seller = {"w": "코스모신소재가 삼성전기를 매출처로 적음 · FILM", "s": "삼성전기 공급사", "k": "seller", "src": "코스모신소재 2026 반기보고서 매출처 표",
              "d": {"name": "코스모신소재", "item": "FILM", "pct": None}}
    s = M.score(_c(supply=[seller]), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="코스모신소재", srcs=SRCS)
    assert s["expl"].startswith("코스모신소재는 삼성전기를 매출처로 적었다(2026 반기보고서 매출처 표).")      # 주어와 같은 회사면 이름을 되풀이하지 않는다 · 품목(FILM)은 내 원재료 표 것이라 여기 안 적는다
    assert "3개월 백분위 자료가 없고 52주 고점 자료도 없으며" in s["expl"]


def test_theme_only_expl_says_no_direct_evidence():
    s = M.score(_c(themes=["PCB(FPCB 등)"]), lead_p3=45, px={"p1": 50, "p3": 60, "dd": -5.0}, ph=PH, lead_name="삼성전기", name="비에이치", srcs=SRCS)
    assert s["expl"].startswith("비에이치는 네이버 테마 'PCB' 소속 외에 보고서 · 리포트에서 삼성전기와의 직접 연결 근거는 찾지 못했다.")
    assert s["group"] == "D" and s["group_note"] == M.GROUP_NOTE["D"] and s["ev"]["link"][0]["src"] == SRCS["theme"]
    s = M.score(_c(), lead_p3=None, px=None, ph=None, lead_name="삼성전기", name="가나", srcs={})
    assert "연결 근거를 찾지 못했다" in s["expl"] and "키워드 리포트는 없다(180일 글 없음)" in s["expl"]
    assert s["ev"]["safe"][0]["src"] == "공시위험 · KIS 종목 상태 캐시"


def test_particles_follow_final_sound_and_expl_does_not_repeat_report_count():
    # 조사는 끝소리로 — 한글 받침 · 대문자 약어 글자 이름(씨 · 엠) · 숫자 소리(삼 · 육). 영문 낱말은 모르니 '을(를)'
    assert (M._eul("MLCC"), M._eul("HBM"), M._eul("FC-BGA"), M._eul("기판"), M._eul("카메라모듈"), M._eul("Camera Module"), M._eul("Photomask")) == ("를", "을", "를", "을", "을", "을", "을(를)")
    assert (M._eul("DRAM"), M._eul("NAND Flash"), M._eul("FILM"), M._eul("WAFER")) == ("을", "를", "을", "를")        # 흔한 영문 제품 낱말은 표로(디램 · 플래시)
    assert (M._ro(3), M._ro(87), M._ro(96), M._ro(10), M._ro(1)) == ("으로", "로", "으로", "으로", "로")
    assert (M._wa("나노엔텍"), M._wa("삼성전기"), M._ga("HLB"), M._ga("DB하이텍")) == ("과", "와", "가", "이")
    refs = [{"date": "2026-08-24", "by": None, "url": "u", "title": "t"}]
    s = M.score(_c(rep_n=2, rep_by=Counter({"MLCC": 2}), rep_refs=refs, themes=["MLCC(적층세라믹콘덴서)"]), lead_p3=62, px={"p1": 50, "p3": 96, "dd": -23.6},
                ph=dict(PH, opm=-0.9), up={"up": -12.0, "n": 2, "avg": 127000}, lead_name="나노엔텍", name="삼화콘덴서공업", srcs=SRCS)
    e = s["expl"]
    assert e.startswith("삼화콘덴서공업은 최근 180일 MLCC 리포트 2건에 함께 언급됐다(최신 증권사 미표기 2026-08-24).")
    assert "실적은 적자(2026Q2 · OPM -0.9%)이고 리포트 목표가 평균 127,000원 기준 상승여력은 -12%다." in e          # 건수는 첫 문장에서 말했다 — 되풀이 없음
    assert "백분위 96으로 주도주(62)보다 앞섰고 52주 고점 대비 -23.6%이며, 위험 꼬리표는 적자(분기 재무 2026Q2)다." in e   # 적자 출처는 분기만(druck 판 이름은 ev.safe)
    s = M.score(_c(themes=["MLCC(적층세라믹콘덴서)"]), lead_p3=62, px={"p1": 50, "p3": 3, "dd": -10.0}, ph=None, n_rep=24, up={"up": 52.0, "n": 3, "avg": 178182},
                lead_name="나노엔텍", name="코칩", srcs=SRCS)
    assert "나노엔텍과의 직접 연결 근거는 찾지 못했다." in s["expl"] and "백분위 3으로" in s["expl"]
    assert "가속도 자료는 없고(분기 재무 캐시 없음) 키워드 리포트는 없으며(180일 글 24건 중) 리포트 목표가 평균 178,182원 기준 상승여력은 +52%다." in s["expl"]
    s = M.score(_c(rep_n=3, rep_by=Counter({"HBM": 3}), rep_refs=refs, themes=["HBM"]), lead_p3=62, px={"p1": 50, "p3": 40, "dd": -10.0}, ph=PH, lead_name="SK하이닉스", name="가", srcs=SRCS)
    assert "실적 국면은 확장 가속(2026Q2 · 가속B +23.5 · OPM 17.5%)이다." in s["expl"]                       # 건수는 첫 문장에 · 상승여력 없음 → 서술어만
    buyer = {"w": "SFA반도체가 삼성전기를 PCB 매입처로 적음 (반도체 매입 중 PCB 90.3%)", "s": "삼성전기 고객 · PCB", "k": "buyer", "src": "SFA반도체 2026 반기보고서 「사업의 내용」 원재료 매입처 표",
             "d": {"name": "SFA반도체", "item": "PCB", "pct": 90.3, "seg": "반도체"}}
    s = M.score(_c(supply=[buyer]), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="SFA반도체", srcs=SRCS)
    assert s["expl"].startswith("SFA반도체는 삼성전기를 PCB 매입처로 적었다(2026 반기보고서 원재료 매입처 표 · 반도체 매입 중 PCB 90.3%).")       # 비중은 그 품목이 (부문) 매입에서 차지하는 몫


def test_risk_deductions_with_disclosure_sources():
    row = ["20260624", "불성실공시법인지정", "20260624800637"]
    s, items = M.risk_items({"ref": [{"cat": "불성실_지정", "rows": [row]}]}, risk_date="20261013")
    assert s == 4 and items == [{"t": "불성실공시", "src": "공시위험 20261013 — 불성실공시법인지정 20260624", "date": "20260624", "url": M.DART % row[2]}]
    assert M.risk_flags({"ref": [{"cat": "횡령배임"}]})[0] == 2 and M.risk_flags({"ref": [{"cat": "보고서지연"}]})[0] == 3
    assert M.risk_flags({"ref": [{"cat": "투자주의환기"}]})[0] == 3
    s, items = M.risk_items({"ref": [{"cat": "횡령배임"}, {"cat": "불성실_지정"}]}, [], ["투자경고"], -2.0, kis_date="20261013", druck_src="가속도")
    assert s == 0 and [(x["t"], x["src"]) for x in items] == [("횡령 · 배임 혐의", "공시위험"), ("불성실공시", "공시위험"), ("투자경고", "KIS 종목 상태 20261013"), ("적자", "가속도")]
    light = {"level": "작전주 꼴", "hits": [{"cat": "금전대여", "days": 3, "rows": [["20260908", "금전대여결정", "20260908900198"]]}]}
    s, items = M.risk_items(light, risk_date="20261013")
    assert s == 3 and items[0]["t"] == "자금 거래" and items[0]["url"].endswith("20260908900198") and items[0]["src"].endswith("금전대여결정 20260908")


def test_clip_sent_cuts_at_sentence_boundaries():
    rx = M.TRIG_RULES[2][1]                                           # '30% 이상 가격 인상'
    ln = "MLCC 사이클 본격화: 범용 MLCC는 30% 이상 가격 인상되고 있으며, AI용 MLCC는 짧은 공급 계약 기간으로 가격 협상력이 높아 수익성이 좋다고 보며 내년에도 지속된다."
    m = rx.search(ln)
    t = M.clip_sent(ln, m)
    assert t == "범용 MLCC는 30% 이상 가격 인상되고 있으며" and not t.startswith("…")          # 앞은 콜론 뒤부터, 뒤는 60자 안 마지막 '며' 뒤
    short = "범용 MLCC는 30% 이상 가격 인상되고 있다."
    assert M.clip_sent(short, rx.search(short)) == short                                      # 76자 안이면 통째
    ln2 = "A" * 30 + ". 범용 MLCC는 30% 이상 가격 인상 전망. " + "B" * 70
    assert M.clip_sent(ln2, rx.search(ln2)) == "범용 MLCC는 30% 이상 가격 인상 전망."                 # 맞은 문장만(앞 '…' 없이)
    ln3 = "가" * 50 + " 범용 MLCC는 30% 이상 가격 인상 " + "나" * 50
    assert M.clip_sent(ln3, rx.search(ln3)).startswith("…")                                      # 경계가 아예 없으면 둘레 자르기
    rows = [{"date": "2026-08-31 08:00", "title": "MLCC", "broker": "B", "msg_url": "u3", "lines": [ln]}]
    assert M.report_triggers(rows, "2026-06-14", ["MLCC"])["price"]["text"] == "범용 MLCC는 30% 이상 가격 인상되고 있으며"


def test_up_down_nodes_pass_sources_and_node_rel_uses_them():
    sellers = [{"code": "005070", "name": "코스모신소재", "group": False, "src": "코스모신소재 2026 반기보고서 「사업의 내용」 매출처 표", "date": "20260814", "url": "u1"}]
    mats = [{"segment": "컴포넌트", "item": "FILM", "amt": 1, "pct": 24.9, "suppliers": [{"name": "COSMO"}]}]
    up = M.up_groups(mats, [], LK.code, sellers=sellers, lead_name="삼성전기")
    assert up[0]["listed"][0]["url"] == "u1" and up[0]["listed"][0]["src"].startswith("코스모신소재 2026")
    custs = [{"name": "삼성전자", "pct": 26.0, "link": {"code": "005930"}, "src": "삼성전기 2026 반기보고서 「사업의 내용」 매출처 표", "url": "c1"}]
    buyers = [{"code": "036540", "name": "SFA반도체", "pct": 90.3, "items": ["PCB"], "src": "SFA반도체 2026 반기보고서 「사업의 내용」 원재료 매입처 표", "url": "b1"}]
    d = M.down_nodes(custs, buyers, [{"party": "글로벌 대형기업", "n": 5, "amount": 1e12, "link": None, "src": "공시 · 단일판매ㆍ공급계약 체결", "date": "20260929"}], None, "2026 반기")
    assert d[0]["url"] == "c1" and d[1]["url"] == "b1" and d[2]["date"] == "20260929"
    pay = {"name": "삼성전기", "src": {"vc": {"period": "2026 반기", "rcept": "20260814003805"}}, "net": {"up": up, "down": d}, "matrix": []}
    rel = M.node_rel(pay, "036540")
    assert rel == [{"t": "SFA반도체 매입 중 PCB 90.3%", "src": buyers[0]["src"], "url": "b1"}]
    rel = M.node_rel(pay, "005070")
    assert [x["url"] for x in rel] == [M.DART % "20260814003805", "u1"]                      # 내 원재료 표(접수번호 링크) · 그쪽 매출처 표


def test_vcmap_build_history_and_same_customer_links(srv, monkeypatch):
    names = {CO: "가나전자", "H00001": "옛공급", "S00001": "같은고객사", "N00001": "장비사", "B00001": "옛고객", "OLD001": "옛제품사", "NEW001": "새제품사"}
    monkeypatch.setattr(srv, "INDEX", {"companies": [dict(srv.company_by_code(CO))] + [{"code": k, "name": v, "reports": []} for k, v in names.items() if k != CO],
                                       "built": 0})
    monkeypatch.setattr(srv, "_vcmap_linker", lambda build=True: M.Linker([], names))
    monkeypatch.setattr(srv, "valuechain_view", lambda code: {
        "years": ["2022", "2025"], "periods": {"2025": {"stamp": "2025-12", "label": "사업보고서"}}, "stamp": "2025-12",
        "customers": [{"name": "대고객", "pct": 40.0, "first": "2022", "last": "2025", "by_year": {"2022": 30.0, "2025": 40.0}, "link": None, "own": False}],
        "suppliers_hist": [{"name": "옛공급", "years": ["2022"], "items": ["PASTE"], "first": "2022", "last": "2022", "link": None}],
        "materials": [], "sellers": [], "buyers": [], "orders": [], "products": [{"item": "MLCC", "pct": 90.0}]})
    monkeypatch.setattr(srv, "_vc_peers", lambda: {"prod": {"OLD001": [("MLCC", "", 50.0)], "NEW001": [("MLCC", "", 50.0)]}, "prod_y": {"OLD001": "2012", "NEW001": "2025"}, "supp": {},
                                                    "cust": {srv._vc_key("대고객"): [("S00001", "같은고객사", 96.0, "대고객"), ("N00001", "장비사", 50.0, "대고객")]}})
    monkeypatch.setattr(srv, "_vcmap_hist", lambda: {"cust": {}, "supp": {srv._vc_key("가나전자"): {"B00001": {"ys": ["2020", "2021"], "item": "MLCC"}}},
                                                     "latest": {"B00001": "2025"}, "last": {"B00001": {"sn": "2025", "sa": "2025"}}})     # 2025 원재료 표가 이름을 안 적었다 → 지금은 빠짐
    monkeypatch.setattr(srv, "_vcmap_themes", lambda: {"stocks": {CO: {"themes": ["MLCC(적층세라믹콘덴서)"]}, "S00001": {"themes": ["MLCC(적층세라믹콘덴서)"]}}, "date": "2026-10-11"})
    srv.vcmap_view(CO)
    _wait(srv)
    d = srv.vcmap_view(CO)
    rows = {r["code"]: r for r in d["matrix"]}
    assert set(rows) == {"H00001", "S00001", "B00001", "NEW001"} and d["src"]["hist"] == {"n": 2, "same": 2}      # 장비사(같은 고객만)는 없다 · 2012 제품 표(옛제품사)는 같은 제품이 아니다
    assert rows["NEW001"]["parts"]["link"] == 4 and rows["NEW001"]["expl"].startswith("새제품사는 가나전자와 같은 MLCC를 만든다(")
    h = rows["H00001"]
    assert h["parts"]["link"] == 3 and h["ev"]["link"][0]["t"] == "2022년 가나전자 PASTE 매입처 '옛공급' (지금은 빠짐)" and h["expl"].startswith("옛공급은 2022년 가나전자의 PASTE 매입처였다(지금은 빠짐")
    b = rows["B00001"]
    assert b["parts"]["link"] == 3 and b["ev"]["link"][0]["t"] == "2020–2021년 옛고객이 가나전자를 MLCC 매입처로 적음 (지금은 빠짐)"
    s = rows["S00001"]
    assert s["parts"]["link"] == 3 and s["ev"]["link"][0]["t"] == "대고객에 매출 96% (가나전자도 40%) · MLCC 테마"
    assert s["ev"]["link"][1]["src"] == "네이버 금융 테마 분류 2026-10-11" and s["group_note"] and s["expl"].startswith("같은고객사는 가나전자와 같은 고객 대고객에 팔고(매출 96%, 가나전자도 40%")
    assert all("expl" in r and isinstance(r["ev"]["fund"][0], dict) for r in d["matrix"]) and d["src"]["dates"]["theme"] == "2026-10-11"


# ---------------------------------------------------------------- 3차 손질(2026-10-13) — 비중은 표 꼴대로 · 해 목록 · 같은 제품 비중은 표 값만 · 표 없는 최신 칸
def test_yrs_of_lists_years_as_cached():
    assert M.yrs_of(["2014", "2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022"]) == "2014–2022년"
    assert M.yrs_of(["2021", "2024"]) == "2021 · 2024년" and M.yrs_of(["2025", "2026-06"]) == "2025–2026년" and M.yrs_of(["2020"]) == "2020년"
    assert M.yrs_of(["2012", "2015", "2018", "2020", "2021", "2022"]) == "2012–2022년 중 6개 해(2012 · 2015 · 2018 · 2020–2022)"    # 처음–마지막만 적으면 없는 해까지 적은 셈
    assert M.yrs_of([]) == "" and M._yrs("2020", "2022") == "2020–2022년"


def test_share_phrases_follow_table_shape():
    # 매입처마다 한 줄인 표(영풍 BASE 줄 일곱)면 그 줄 비중은 매입처(주도주)가 그 품목 매입에서 차지하는 몫. 품목마다 한 줄이면 품목이 (부문) 매입에서 차지하는 몫 — 부문은 늘 적는다
    assert M.buy_share({"item": "BASE", "seg": "FPCB, PCB 부문", "pct": 31.47, "per_sup": True}, "삼성전기") == "FPCB, PCB 부문 BASE 매입 중 삼성전기 31.5%"
    assert M.buy_share({"item": "수동소자", "seg": "전자부품", "pct": 10.4}, "삼성전기") == "전자부품 매입 중 수동소자 10.4%"
    assert M.buy_share({"item": "PCB", "pct": 90.3}, "삼성전기") == "매입 중 PCB 90.3%"
    assert M.sell_share({"pct": 96.0}, "삼성전자") == "삼성전자가 매출의 96.0%" and M.sell_share({"pct": 30.0, "seg": "VS부문", "basis": "부문"}, "LG전자") == "VS부문 매출 중 LG전자 30.0%"
    w = {"w": "영풍이 삼성전기를 BASE 매입처로 적음 (FPCB, PCB 부문 BASE 매입 중 삼성전기 31.5%)", "s": "삼성전기 고객 · BASE", "k": "buyer", "src": "영풍 2025 사업보고서 「사업의 내용」 원재료 매입처 표",
         "d": {"name": "영풍", "item": "BASE", "pct": 31.47, "seg": "FPCB, PCB 부문", "per_sup": True, "sub": "코리아써키트"}}
    s = M.score(_c(supply=[dict(w, weak=True)]), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="영풍", srcs=SRCS)
    assert s["expl"].startswith("영풍은 연결 자회사(코리아써키트) 매입으로 삼성전기를 BASE 매입처로 적었다(2025 사업보고서 원재료 매입처 표 · FPCB, PCB 부문 BASE 매입 중 삼성전기 31.5%).")
    assert "31.5%" in s["ev"]["link"][0]["t"]                                     # 설명 문장의 숫자는 근거 줄에도 있다
    seller = {"w": "나무가가 삼성전자를 매출처로 적음 (삼성전자가 매출의 96.0%)", "s": "삼성전자 공급사", "k": "seller", "src": "나무가 2026 반기보고서 매출처 표", "d": {"name": "나무가", "pct": 96.0}}
    s = M.score(_c(supply=[seller]), lead_p3=45, px=None, ph=None, lead_name="삼성전자", name="나무가", srcs=SRCS)
    assert s["expl"].startswith("나무가는 삼성전자를 매출처로 적었다(2026 반기보고서 매출처 표 · 삼성전자가 매출의 96.0%).")
    mine = {"w": "삼성전기 FILM 매입처 'COSMO' (컴포넌트 매입 중 FILM 24.9%)", "s": "삼성전기 공급사 · FILM", "k": "mine", "src": "삼성전기 2026 반기보고서 원재료 표",
            "d": {"item": "FILM", "seg": "컴포넌트", "pct": 24.9, "as": "COSMO"}}
    s = M.score(_c(supply=[mine]), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="코스모신소재", srcs=SRCS)
    assert s["expl"].startswith("코스모신소재는 삼성전기의 FILM 매입처다(2026 반기보고서 원재료 표 · 컴포넌트 매입 중 FILM 24.9% · 보고서 표기 'COSMO').")
    cust = {"w": "LG전자 VS부문 매출처 30.0%", "s": "LG전자 고객 30%", "k": "cust", "src": "LG전자 2025 사업보고서 매출처 표", "d": {"pct": 30.0, "seg": "VS부문", "basis": "부문"}}
    s = M.score(_c(supply=[cust]), lead_p3=45, px=None, ph=None, lead_name="LG전자", name="가", srcs=SRCS)
    assert s["expl"].startswith("가는 LG전자의 매출처다(2025 사업보고서 매출처 표 · LG전자 VS부문 매출의 30.0%).")
    # 과거 줄 — 해 목록 그대로 · 꼬리는 서버가 정한 말(더 새 보고서에 표가 없으면 '빠짐'이 아니다)
    h = {"w": "2021 · 2024년 코리아써키트가 삼성전기를 BGA외 매입처로 적음 (지금은 빠짐)", "s": "과거 삼성전기 고객", "k": "hist_buyer", "weak": True,
         "src": "코리아써키트 2024 사업보고서 「사업의 내용」 원재료 매입처 표", "d": {"name": "코리아써키트", "item": "BGA외", "y1": "2021", "y2": "2024", "ys": ["2021", "2024"]}}
    s = M.score(_c(supply=[h]), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="코리아써키트", srcs=SRCS)
    assert s["expl"].startswith("코리아써키트는 2021 · 2024년 삼성전기를 BGA외 매입처로 적었다(지금은 빠짐 · 2024 사업보고서 원재료 매입처 표).")
    h2 = dict(h, k="hist_seller", src="HLB생명과학 2025 사업보고서 매출처 표", d={"name": "HLB생명과학", "ys": ["2022", "2023", "2024", "2025"], "tail": "최신 2026 반기보고서엔 매출처 표 없음"})
    s = M.score(_c(supply=[h2]), lead_p3=45, px=None, ph=None, lead_name="에스디바이오센서", name="HLB생명과학", srcs=SRCS)
    assert s["expl"].startswith("HLB생명과학은 2022–2025년 에스디바이오센서를 매출처로 적었다(최신 2026 반기보고서엔 매출처 표 없음 · 2025 사업보고서 매출처 표).")
    assert "지금은 빠짐" not in s["expl"]


def test_products_of_sum_rows_estimated_pct_and_rounding():
    posco = [{"segment": "철강부문", "item": "냉연", "use": "자동차,가전 등", "pct": 32.8, "amt": 99516.0},
             {"segment": "철강부문", "item": "기타제품 등", "use": "후판,선재 등", "pct": 33.7, "amt": 102277.0},
             {"segment": "철강부문", "item": "기타제품 등", "use": "단순합계", "pct": 100.0, "amt": 303569.0},
             {"segment": "철강부문", "item": "기타제품 등", "use": "내부거래제거", "pct": None, "amt": 115638.0},
             {"segment": "인프라", "item": "물류등부문", "use": "기타", "pct": 6.6, "amt": 19332.0},
             {"segment": "인프라", "item": "물류등부문", "use": "단순합계", "pct": 100.0, "amt": 293241.0}]
    p = M.products_of(posco)
    assert [(x["item"], x["pct"]) for x in p] == [("냉연", 32.8), ("물류등부문", 6.6)] and not any(x.get("est") for x in p)     # 합계 · 내부거래제거 줄은 빠지고 '기타제품 등'은 용도로 안 바뀐다
    assert M.product_label({"item": "기타제품 등", "use": "후판,선재 등"}) == "기타제품 등" and M.product_label({"item": "제품", "use": "후판"}) == "후판"
    dd = [{"segment": "PCB사업부문", "item": "인쇄회로기판", "use": "메모리", "pct": None, "amt": 769692.0, "kind": "제품"},
          {"segment": "PCB사업부문", "item": "내부거래 제거", "use": "-", "pct": 3.0, "amt": 22403.0, "kind": "기타"}]
    p = M.products_of(dd)
    assert p == [{"item": "인쇄회로기판", "seg": "PCB사업부문", "pct": 100.0, "raw": 100.0, "use": "메모리", "c": 0, "est": True}]     # 금액으로 나눈 비중 — est
    assert M.products_of([{"item": "기판", "pct": 82.46}, {"item": "모듈", "pct": 17.54}])[0]["raw"] == 82.46                      # raw = 안 둥글린 표 값(pct0 가 두 번 둥글리지 않게)
    hit = M.prod_hits([(x["item"], x["seg"], x["pct"], x.get("est", False)) for x in p], [("기판", "기판")])
    assert hit == [("기판", "인쇄회로기판", 100.0, True)]
    s = M.score(_c(prod=hit), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="대덕전자", srcs=SRCS)
    assert s["ev"]["link"][0]["t"] == "같은 제품 '인쇄회로기판' (금액 비율 추정 100%)" and "주요 제품 표 '인쇄회로기판' 금액 비율 추정 100%)" in s["expl"]
    s = M.score(_c(prod=[("기판", "인쇄회로기판", 34.52, False)]), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="제주반도체", srcs=SRCS)
    assert s["ev"]["link"][0]["t"] == "같은 제품 '인쇄회로기판' (매출 비중 35%)" and M.pct0(34.5) == "35%" and M.pct0(0.4) == "0%"      # 반올림은 올림 쪽(짝수 반올림 34 아님)
    s = M.score(_c(prod=[("기판", "인쇄회로기판", None)]), lead_p3=45, px=None, ph=None, lead_name="삼성전기", name="가", srcs=SRCS)
    assert s["ev"]["link"][0]["t"] == "같은 제품 '인쇄회로기판'"


def test_upside_detail_counts_reports_and_brokers():
    rows = [{"date": "2026-10-01", "tp": 100, "broker": "A"}, {"date": "2026-09-01", "tp": 80, "broker": "A"}, {"date": "2026-09-15", "tp": 120, "broker": "B"},
            {"date": "2026-01-01", "tp": 50, "broker": "C"}, {"date": "2026-10-02", "broker": "D"}]
    u = M.upside_detail(rows, 100.0, "2026-04-15")
    assert u == {"up": 10.0, "n": 2, "reps": 3, "avg": 110}                      # 증권사 2곳(A 최신 100 · B 120) · 목표가 적힌 글 3건
    s = M.score(_c(themes=["x"]), lead_p3=45, px={"p3": 50, "dd": -1.0}, ph=None, up=u, lead_name="가", name="나", srcs=SRCS)
    assert s["ev"]["attn"][1]["src"] == "리포트 3건 · 증권사 2곳 180일 증권사별 최신 목표가 평균"


def _yr(stamp, label, rcept, customers=None, materials=None, products=None, partial=False):
    return dict({"stamp": stamp, "label": label, "rcept": rcept, "customers": customers or [], "materials": materials or [], "products": products or []},
                **({"partial": True} if partial else {}))


def _mat(item, sups, pct=None, seg=None, amt=1.0):
    return {"segment": seg, "item": item, "pct": pct, "amt": amt, "suppliers": [{"name": s} for s in sups]}


def test_vcmap_build_reads_year_caches_and_partial_latest(srv, monkeypatch, tmp_path):
    """진짜 꼴의 .cache/밸류체인/{code}.json 으로 _vcmap_hist · _vcmap_meta · _vcmap_src 를 돌린다(monkeypatch 없이). 주도주 최신 칸(2026-06 반기)은 부분 보고서라
    매출처 · 원재료 표가 없다 — 그 앞 칸(2025)의 매출처 · 매입처가 '지금'이고 '지금은 빠짐'은 더 새 표가 이름을 안 적은 회사(옛고객 · 띄엄고객)에만 붙는다.
    후보 쪽도 최신 보고서에 표 · 이름이 없으면(부분반기사 · 유형만사) 빠진 게 아니라 '최신 … 표 없음 · 이름 없음'."""
    names = {CO: "가나전자", "D00001": "대고객", "M00001": "현공급", "O00001": "옛공급", "S00001": "코스모소재", "S00002": "코스모화학",
             "B00001": "옛고객", "P00001": "부분반기사", "T00001": "유형만사", "G00001": "띄엄고객"}
    vc_dir = tmp_path / "밸류체인"
    vc_dir.mkdir()
    me = [{"name": "가나전자"}]
    files = {
        CO: {"2024": _yr("2024-12", "사업보고서", "20250314000001", [{"name": "대고객", "pct": 40.0, "kind": "named"}],
                        [_mat("FILM", ["현공급"], 24.9, "컴포넌트", 100.0), _mat("BASE", ["코스모소재"], 60.0, "소재", 5.0)], [{"item": "MLCC", "pct": 90.0}]),
             "2025": _yr("2025-12", "사업보고서", "20260316000002", [{"name": "대고객", "pct": 42.0, "kind": "named"}],
                        [_mat("FILM", ["현공급"], 24.9, "컴포넌트", 100.0), _mat("BASE", ["코스모소재"], 60.0, "소재", 5.0)], [{"item": "MLCC", "pct": 90.0}]),
             "2026-06": _yr("2026-06", "반기보고서", "20260814000123", partial=True)},
        "B00001": {"2020": _yr("2020-12", "사업보고서", "20210315000010", materials=[_mat("MLCC", ["가나전자"], 50.0)]),
                   "2021": _yr("2021-12", "사업보고서", "20220315000011", materials=[_mat("MLCC", ["가나전자"], 50.0)]),
                   "2024": _yr("2024-12", "사업보고서", "20250315000012", materials=[_mat("MLCC", ["다른회사"], 50.0)])},
        "P00001": {"2023": _yr("2023-12", "사업보고서", "20240315000020", materials=[_mat("PCB", ["가나전자"], 70.0)]),
                   "2024": _yr("2024-12", "사업보고서", "20250315000021", materials=[_mat("PCB", ["가나전자"], 70.0)]),
                   "2026-06": _yr("2026-06", "반기보고서", "20260814000022", partial=True)},
        "T00001": {"2024": _yr("2024-12", "사업보고서", "20250315000030", [{"name": "가나전자", "pct": 50.0, "kind": "named"}]),
                   "2025": _yr("2025-12", "사업보고서", "20260316000031", [{"name": "국내 대기업", "pct": 60.0, "kind": "type"}])},
        "G00001": {"2021": _yr("2021-12", "사업보고서", "20220315000040", materials=[_mat("FILM", ["가나전자"], 30.0)]),
                   "2024": _yr("2024-12", "사업보고서", "20250315000041", materials=[_mat("FILM", ["가나전자"], 30.0)]),
                   "2025": _yr("2025-12", "사업보고서", "20260316000042", materials=[_mat("FILM", ["다른회사"], 30.0)])},
        "S00001": {"2025": _yr("2025-12", "사업보고서", "20260316000050", [{"name": "가나전자", "pct": 60.0, "kind": "named"}])},
        "S00002": {"2025": _yr("2025-12", "사업보고서", "20260316000060", [{"name": "가나전자", "pct": 10.0, "kind": "named"}])}}
    for cd, ys in files.items():
        (vc_dir / (cd + ".json")).write_text(json.dumps({"years": ys}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(srv, "VC_DIR", str(vc_dir))
    monkeypatch.setattr(srv, "_VCMAP_HIST", {"at": 0.0, "files": 0, "cust": {}, "supp": {}, "latest": {}, "last": {}})
    monkeypatch.setattr(srv, "INDEX", {"companies": [dict(srv.company_by_code(CO))] + [{"code": k, "name": v, "reports": []} for k, v in names.items() if k != CO],
                                       "built": 0})
    monkeypatch.setattr(srv, "_vcmap_linker", lambda build=True: M.Linker([], names))
    monkeypatch.setattr(srv, "_vc_peers", lambda: {"prod": {}, "prod_y": {}, "supp": {}, "cust": {}})
    periods = {"2024": {"stamp": "2024-12", "label": "사업보고서"}, "2025": {"stamp": "2025-12", "label": "사업보고서"}, "2026-06": {"stamp": "2026-06", "label": "반기보고서", "partial": True}}
    monkeypatch.setattr(srv, "valuechain_view", lambda code: {
        "years": ["2024", "2025", "2026-06"], "periods": periods, "stamp": "2026-06", "cust_years": ["2024", "2025"],
        "customers": [{"name": "대고객", "pct": None, "first": "2024", "last": "2025", "by_year": {"2024": 40.0, "2025": 42.0}, "link": {"code": "D00001"}, "own": False}],
        "suppliers_hist": [{"name": "현공급", "years": ["2024", "2025"], "items": ["FILM"], "first": "2024", "last": "2025", "link": None},
                           {"name": "코스모소재", "years": ["2024", "2025"], "items": ["BASE"], "first": "2024", "last": "2025", "link": None},
                           {"name": "옛공급", "years": ["2024"], "items": ["PASTE"], "first": "2024", "last": "2024", "link": None}],
        "materials": [], "buyers": [], "orders": [], "products": [{"item": "MLCC", "pct": 90.0}],
        "sellers": [{"code": "S00001", "name": "코스모소재", "pct": None, "as": "가나전자", "group": False}, {"code": "S00002", "name": "코스모화학", "pct": None, "as": "가나전자", "group": False}]})
    srv.vcmap_view(CO)
    _wait(srv)
    d = srv.vcmap_view(CO)
    rows = {r["code"]: r for r in d["matrix"]}
    assert set(rows) == {"M00001", "D00001", "S00001", "O00001", "B00001", "P00001", "T00001", "G00001"} and d["src"]["hist"]["n"] == 5     # 코스모화학은 지주 연결 베낌(dedup)
    # 주도주 쪽 — 표가 있는 마지막 칸(2025)이 '지금': 매입처 · 매출처는 거기서, 출처도 그 칸의 보고서 · 접수번호
    m = rows["M00001"]
    assert m["parts"]["link"] == 5 and m["ev"]["link"][0] == {"t": "가나전자 FILM 매입처 '현공급' (컴포넌트 매입 중 FILM 24.9%)", "src": "가나전자 2025 사업보고서 원재료 표",
                                                               "date": "20260316", "url": M.DART % "20260316000002"}
    assert "지금은 빠짐" not in m["expl"] and m["expl"].startswith("현공급은 가나전자의 FILM 매입처다(2025 사업보고서 원재료 표 · 컴포넌트 매입 중 FILM 24.9% · 보고서 표기 '현공급').")
    c = rows["D00001"]
    assert c["ev"]["link"][0] == {"t": "가나전자 매출처 42.0%", "src": "가나전자 2025 사업보고서 매출처 표", "date": "20260316", "url": M.DART % "20260316000002"}
    assert d["net"]["down"] == [{"kind": "customer", "name": "대고객", "code": "D00001", "pct": 42.0, "why": "매출처 42.0% (2025)", "src": "가나전자 2025 사업보고서 매출처 표",
                                 "date": "20260316", "url": M.DART % "20260316000002"}]
    assert d["src"]["vc"]["rcept"] == "20260814000123" and d["src"]["vc"]["period"] == "2026 반기" and (d["src"]["vc"]["cust_y"], d["src"]["vc"]["mat_y"]) == ("2025", "2025")
    assert d["src"]["vc"]["mat_period"] == "2025" and d["src"]["vc"]["mat_rcept"] == "20260316000002"
    rel = M.node_rel(d, "M00001")
    assert rel[0] == {"t": "컴포넌트 원재료 FILM 매입처 · 매입 비중 24.9%", "src": "가나전자 2025 사업보고서 원재료 표", "date": "20260316", "url": M.DART % "20260316000002"}
    # 매출처로 적은 회사 — 출처는 거르기 전에 모두 찍혀 up 칸 줄에도 있다(코스모화학은 build · up_groups 둘 다에서 빠진다). 비중은 그 회사 매출처 표의 내 줄
    s = rows["S00001"]
    assert s["ev"]["link"][0] == {"t": "코스모소재가 가나전자를 매출처로 적음 (가나전자가 매출의 60.0%)", "src": "코스모소재 2025 사업보고서 매출처 표", "date": "20260316", "url": M.DART % "20260316000050"}
    assert s["expl"].startswith("코스모소재는 가나전자를 매출처로 적었다(2025 사업보고서 매출처 표 · 가나전자가 매출의 60.0%). 또 가나전자의 BASE 매입처다(2025 사업보고서 원재료 표 · 소재 매입 중 BASE 60.0%")
    listed = [x for g in d["net"]["up"] for x in g["listed"]]
    assert [(x["code"], x["why"], x["src"], x["url"]) for x in listed] == [("S00001", "코스모소재가 가나전자를 매출처로 적음", "코스모소재 2025 사업보고서 매출처 표", M.DART % "20260316000050")]
    assert [g["seg"] for g in d["net"]["up"]] == ["컴포넌트", "소재"]                                   # 원재료 줄은 2025 날것 표에서
    # 과거 — 더 새 표가 이름을 안 적었을 때만 '지금은 빠짐'(해는 캐시에 적힌 칸 그대로)
    assert rows["O00001"]["ev"]["link"][0] == {"t": "2024년 가나전자 PASTE 매입처 '옛공급' (지금은 빠짐)", "src": "가나전자 2024 사업보고서 원재료 표", "date": "20250314", "url": M.DART % "20250314000001"}
    b = rows["B00001"]
    assert b["ev"]["link"][0] == {"t": "2020–2021년 옛고객이 가나전자를 MLCC 매입처로 적음 (지금은 빠짐)", "src": "옛고객 2021 사업보고서 「사업의 내용」 원재료 매입처 표",
                                  "date": "20220315", "url": M.DART % "20220315000011"} and b["parts"]["link"] == 3
    assert rows["G00001"]["ev"]["link"][0]["t"] == "2021 · 2024년 띄엄고객이 가나전자를 FILM 매입처로 적음 (지금은 빠짐)"       # 2022 · 2023 은 캐시에 없다
    p = rows["P00001"]
    assert p["ev"]["link"][0]["t"] == "2023–2024년 부분반기사가 가나전자를 PCB 매입처로 적음 (최신 2026 반기보고서엔 매입처 표 없음)" and p["ev"]["link"][0]["date"] == "20250315"
    assert p["expl"].startswith("부분반기사는 2023–2024년 가나전자를 PCB 매입처로 적었다(최신 2026 반기보고서엔 매입처 표 없음 · 2024 사업보고서 원재료 매입처 표).") and p["why"].startswith("가나전자 고객 · 최신 표 없음")
    t = rows["T00001"]
    assert t["ev"]["link"][0]["t"] == "2024년 유형만사가 가나전자를 매출처로 적음 (최신 2025 사업보고서엔 매출처 이름 없음)" and t["ev"]["link"][0]["url"] == M.DART % "20250315000030"
    assert not any("지금은 빠짐" in r["expl"] for r in (p, t, m, c, s))
    H = srv._vcmap_hist()
    assert H["last"]["P00001"] == {"cn": None, "ca": None, "sn": "2024", "sa": "2024"} and H["last"]["T00001"] == {"cn": "2024", "ca": "2025", "sn": None, "sa": None}
    assert H["supp"][srv._vc_key("가나전자")]["G00001"] == {"ys": ["2021", "2024"], "item": "FILM"} and H["latest"]["P00001"] == "2026-06"
