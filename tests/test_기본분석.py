# -*- coding: utf-8 -*-
"""기본분석.py — 원문 추출(절 · 개요 · 부문 비중 · 가격표 · 위험 문장 · 업의 본질 · 지역 · 공장 · 민감도) · 원재료 매핑 · 상관 · 호재/악재 규칙. 순수 함수만."""
import os
import sys
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_sp = ilu.spec_from_file_location("기본분석_시험", os.path.join(BASE, "기본분석.py"))
F = ilu.module_from_spec(_sp)
_sp.loader.exec_module(F)

BIZ = """II. 사업의 내용
1. 사업의 개요
당사는 국내 본사를 비롯하여 해외 생산법인과 브랜드 회사로 구성된 글로벌 아웃도어 및 스포츠 기업입니다. 주요 바이어로부터 주문을 받아 해외 공장에서 만들어 수출합니다.
사업부문
주요사업영역
매출비중
제조OEM 사업부문
아웃도어 의류 생산 수출
68%
SCOTT 사업부문
프리미엄 자전거 유통
28%
기타 사업부문
브랜드 유통
4%
주) 상기 매출비중은 연간 기준임.
2. 주요 제품 및 서비스
(1) 주요 제품 등의 가격변동추이
품목
제17기
제16기
제15기
원단
1,200
1,000
900
3. 원재료 및 생산설비
가. 원재료 등의 현황
원부자재
Taiwan
Hong Kong
USA
21.2%
16.6%
8.8%
나. 주요 해외 생산설비 현황
소 재 지
생산 법인명
방글라데시
YOUNGONE (CEPZ) LTD.
베트남
YOUNGONE NAM DINH CO. LTD.
4. 매출 및 수주상황
가. 사업부문별 매출
사업부문
수 출
5,000
해외(연결)
1,200
내 수
200
5. 위험관리 및 파생거래
당사는 수출 비중이 높아 원/달러 환율이 오르면 수익성에 긍정적인 영향이 있습니다.
경제적 여유가 생긴 소비자가 늘어 프리미엄 제품 수요는 꾸준히 증가해왔습니다.
주요 원자재인 원단 가격 상승은 원가 부담으로 이어집니다.
7. 기타 참고사항
[제조OEM 사업부문]
(1) 아웃도어 산업의 특성
아웃도어 의류 제조산업은 기능성을 강조하는 고기능성 의류를 만들어 바이어에게 납품하는 산업입니다. 인건비가 저렴한 개발도상국에서 생산합니다.
(2) 산업의 성장성
아웃도어 의류는 캐주얼 의류의 대체재로 자리매김했기 때문에 수요층이 넓어졌습니다.
"""

FIN = """주석
(단위 : 천원)
시장위험의 각 유형별 민감도분석
USD
현재 다른 변수가 일정하고 해당통화에 대한 기능통화의 환율이 5%절상 및 절하인 경우
43,483,117
43,483,117
EUR
현재 다른 변수가 일정하고 해당통화에 대한 기능통화의 환율이 5%절상 및 절하인 경우
13,914,711
13,914,711
이자율 위험
다른 변수가 일정하다고 가정할 때의 이자율이 0.1% 상승 또는 하락할 경우
382,366
382,366
"""


def test_sections_split_seven_parts():
    s = F.sections(BIZ)
    assert "사업의 개요" in s["overview"] and "가격변동추이" in s["products"] and "생산설비" in s["materials"]
    assert "수 출" in s["sales"] and "환율" in s["risk"] and "산업의 특성" in s["etc"]
    # 머리가 없는 옛 보고서는 전부 개요로
    assert F.sections("당사는 그냥 글만 있습니다.")["overview"].startswith("당사는")


def test_overview_prose_only_and_limit():
    paras, total = F.overview(BIZ)
    assert paras and paras[0].startswith("당사는 국내 본사") and total >= len(paras[0])
    assert all("%" not in p for p in paras)                     # 표 칸은 산문이 아니다


def test_segments_pct_name_desc_pct_layout():
    segs = F.segments_pct(BIZ)
    assert [(s["name"], s["pct"]) for s in segs] == [("제조OEM 사업부문", 68.0), ("SCOTT 사업부문", 28.0), ("기타 사업부문", 4.0)]
    assert segs[0]["desc"] == "아웃도어 의류 생산 수출"


def test_segments_pct_amount_then_pct_layout():
    t = """1. 사업의 개요
2. 주요 제품 및 서비스
(1) 주요 제품 등의 매출
사업부문
용도
주요상표 등
생산 제품
제8기(당기)
제7기(전기)
매출액
비중
매출액
비중
중공업
산업용
HICO 등
변압기, 차단기
4,149,258
69.52%
3,098,831
63.31%
건설
-
해링턴
아파트
1,786,501
29.93%
1,765,459
36.07%
합계
5,968,512
100%
"""
    segs = F.segments_pct(t)
    assert [(s["name"], s["pct"], s["desc"]) for s in segs] == [("중공업", 69.52, "변압기, 차단기"), ("건설", 29.93, "아파트")]


def test_segments_pct_rejects_bad_sum():
    t = "1. 사업의 개요\n사업부문\n비중\nA\n10%\nB\n20%\n"
    assert F.segments_pct(t) == []


def test_price_table_reads_latest_first_and_change():
    rows = F.price_table(F.sections(BIZ)["products"])
    assert len(rows) == 1 and rows[0]["item"] == "원단" and rows[0]["vals"] == [1200.0, 1000.0, 900.0]
    assert abs(rows[0]["change"] - 20.0) < 1e-9
    # 가격 표가 없고 생산실적 표만 있으면 잡지 않는다(효성중공업)
    t = "(2) 주요 제품 등의 가격변동추이\n해당사항 없음\n(3) 생산실적\n제8기\n제7기\n창원\n3,128,398\n2,540,371\n"
    assert F.price_table(t) == []


def test_export_split_sums_export_like_rows():
    e = F.export_split(BIZ)
    assert e and e["export"] == 6200.0 and e["domestic"] == 200.0 and abs(e["export_pct"] - 6200 / 6400 * 100) < 1e-9


def test_plants_from_skips_sourcing_country_table():
    assert sorted(F.plants_from(BIZ)) == ["방글라데시", "베트남"]          # Taiwan · USA(원부자재 조달국)는 공장이 아니다


def test_risk_sentences_keys_and_false_positives():
    r = F.risk_sentences(BIZ)
    assert any("환율" in x["s"] for x in r["fx"]) and r["fx"][0]["tone"] == "up"
    assert any("원단 가격" in x["s"] for x in r["input"])
    assert not any("여유가" in x["s"] for x in r["input"])       # '여유가' 는 유가가 아니다
    assert any("수요" in x["s"] for x in r["demand"])


def test_industry_notes_grouped_by_segment():
    notes = F.industry_notes(BIZ)
    assert [(n["seg"], n["kind"]) for n in notes] == [("제조OEM 사업부문", "특성"), ("제조OEM 사업부문", "성장성")]
    assert notes[0]["p"].startswith("아웃도어 의류 제조산업")


def test_regions_counts_and_order():
    r = F.regions(BIZ)
    names = [x["name"] for x in r]
    assert "방글라데시" in names and "베트남" in names and "미국" in names


def test_fx_sensitivity_pairs_numbers_with_short_labels():
    s = F.fx_sensitivity(FIN)
    fx = [x for x in s if x["kind"] == "fx"]
    assert fx and fx[0]["pct"] == "5" and fx[0]["unit"] == "천원" and fx[0]["nums"][:2] == [43483117.0, 43483117.0]
    assert [r[0] for r in fx[0]["rows"][:3]] == ["", "", "EUR"]            # 긴 설명 줄은 이름표가 아니다 · 다음 통화 EUR 는 짧아 붙는다
    rate = [x for x in s if x["kind"] == "rate"]
    assert rate and rate[0]["pct"] == "0.1" and rate[0]["nums"][0] == 382366.0


def test_commodity_mapping_symbols_are_word_bounded():
    assert F.commodity_of("전기동") == "구리" and F.commodity_of("Cu") == "구리"
    assert F.commodity_of("Chemical") is None                      # 'al' 꼬리가 알루미늄이 아니다
    assert F.commodity_of("Al") == "알루미늄" and F.commodity_of("강판") == "철강·철광석" and F.commodity_of("Wafer") == "반도체·웨이퍼"
    assert F.commodity_of("경제적 여유가") is None and F.commodity_of("원유") == "유가·나프타"


def test_followers_pearson_and_sample_count():
    px = {n: 100 + (n % 7) * 10 + (n % 5) * 3 for n in range(8000, 8030)}       # 1년 변화가 분기마다 다르게
    up = {n: px[n] / 10 for n in range(8000, 8030)}                               # 주가와 같은 비율로 — r = 1
    noise = {n: 10 + (n % 3) for n in range(8000, 8030)}
    out = F.followers(px, {"같이": up, "잡음": noise})
    assert out[0]["name"] == "같이" and abs(out[0]["r"] - 1.0) < 1e-6 and out[0]["n"] == 24
    assert out[1]["name"] == "잡음" and out[1]["r"] is not None and abs(out[1]["r"]) < 1.0
    # 변화가 늘 같은(분산 0) 열은 r 없음 — 복리 증가 열이 그렇다
    flat = {n: 10 * (1.05 ** (n - 8000)) for n in range(8000, 8030)}
    assert F.followers(flat, {"x": flat})[0]["r"] is None
    assert F.followers({8000: 1, 8001: 2}, {"x": {8000: 1, 8001: 2}})[0]["r"] is None     # 표본 모자람


def test_drivers_rules_direction_and_basis():
    rows = F.drivers(export_pct=80, materials=[{"item": "구리", "pct": 40}, {"item": "기타", "pct": 60}], fx_sens=[], risk={},
                     net_debt_ratio=0.5, backlog={"value": 1e12, "text": "1.0조 (2026Q2 기준)"}, regions_=[{"name": "미국", "n": 10}, {"name": "국내", "n": 5}],
                     product_index={"name": "전기", "chg12": 8.8}, competitors=["중국 경쟁사의 가격 경쟁 심화로 시장가격 하락 위험"], customers=[], plants=["미국"])
    by = {r["factor"]: r for r in rows}
    assert by["원/달러 환율 ↑ (원화 약세)"]["up"] == 1 and by["원/달러 환율 ↑ (원화 약세)"]["strength"] == 3 and by["원/달러 환율 ↑ (원화 약세)"]["basis"] == "공시 숫자"
    assert by["금리 ↑"]["up"] == -1 and by["금리 ↑"]["strength"] == 2
    assert by["구리 가격 ↑"]["up"] == -1 and by["구리 가격 ↑"]["strength"] == 3
    assert not any("기타" in k for k in by)                                   # '기타' 줄은 요인이 아니다
    assert by["제품 값 ↑ (업종 수출물가 지수)"]["up"] == 1 and by["수주 잔고 ↑"]["up"] == 1
    assert by["미국 쪽 관세 · 규제 · 경기 악화"]["up"] == -1 and by["경쟁사(특히 중국) 가격 인하"]["up"] == -1
    assert all(r["basis"] in ("공시 숫자", "공시 문장", "구조에서 추론", "공시 밖 통계") for r in rows)
    # 수출 비중을 모르고 문장도 없으면 환율 줄이 없다 · 내수 회사는 환율 ↑ 악재
    assert not any(r["factor"].startswith("원/달러") for r in F.drivers())
    assert F.drivers(export_pct=5)[0]["up"] == -1
    # 어기지 않을 것 — 처방 · 판정 낱말 없음
    for r in rows:
        for w in ("매수", "매도", "사라", "팔라", "좋다", "나쁘다"):
            assert w not in (r["why"] or "") and w not in r["factor"]


def test_summary_line_and_josa():
    assert F.josa("영원무역") == "은" and F.josa("효성중공업") == "은" and F.josa("삼성전자") == "는" and F.josa("LG") == "는"
    line = F.summary_line("영원무역", F.segments_pct(BIZ), [{"name": "The North Face", "kind": "named"}], 96.9, None, ["방글라데시"])
    assert line.startswith("영원무역은 제조OEM 사업부문 68% · SCOTT 사업부문 28% · 기타 사업부문 4%로 매출을 올린다.")
    assert "주요 고객 The North Face" in line and "수출 97%" in line and "공장 방글라데시" in line
    assert "못 읽었다" in F.summary_line("회사", [], None, None, None, None)
