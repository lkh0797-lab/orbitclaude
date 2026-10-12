# -*- coding: utf-8 -*-
"""밸류체인 뽑기(밸류체인.py) · 서버 valuechain_view 손질 (2026-10-12, 삼성전기 009150 점검에서 나온 버그).
시험 본문은 삼성전기 사업보고서(수집기 strip_markup 결과: 칸 하나 = 한 줄, 행 사이 빈 줄, HTML 조각이 한 낱말 가운데서 줄을 바꾼다)의
꼴만 줄여 지어낸 것이다 — 회사(가나전자 · 다라전기 · 가나신소재 …) · 숫자는 가짜. 서버 시험은 tmp_path 의 가짜 캐시로만."""
import os, sys, json, importlib.util as ilu
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("밸류체인_시험", os.path.join(BASE, "밸류체인.py"))
V = ilu.module_from_spec(_sp); _sp.loader.exec_module(V)


def named(text):
    return {x["name"]: x["pct"] for x in V.customers(text) if x["kind"] == "named"}


# ---------------------------------------------------------------- 1. 매출처 문장 — '10% 이상인 거래처는 A 및 종속회사' · 조각 난 줄
T12 = """마. 주요 매출처

당사 및 종속
회사의 매출에서 차지하는 비중이 10% 이상인 거래처는 가나전자 및 종속회사이며 약

50%

입니다.

6. 수주상황
"""

T15 = """마. 주요 매출처

당사 및 종속
회사의 매출에서 차지하는 비중이 10% 이상인 거래처는 가나전자 및
가나전자의 해외종속회사입니다. 2015년 당기 중 해당 거래처에 대한 매출 비율은

약

61.8%

입
니다.

6. 수주상황

2015년말 현재 주문생산에 의한 장기공급계약 수주현황은 없습니다.
"""

T20 = """마. 주요 매출처

2020년 당사의 주요

매출처
는 가나전자와 그 종속기업이며,
해당 거래처에 대한 매출 비중
은
전체 매출액 대
비
약

33.7%
입
니다
.

6. 수주상황
"""

# 개요 문단(조각 난 '매출처\n는') + 부문 매출표 + 마. 주요 매출처(괄호 속 고객별 비중)
T21 = """1. 사업의 개요

2021년말 누적 매출액
은
9조 6,750억원으로
, 각 사업부문별 매출액 및 매출비중은 컴포넌트 사업부문

4조 7,718억원
(49.32%), 광학 사업부문 3조 2,241억원(33.32%)입니
다.

. 당
사의 주요

매출처
는 가
나전자와 그 종속기업 및 XIAOLONG이며,
주
요 매출처에 대한 매출비중
은
전체 매출액 대
비
약

39.0%

수준 입
니다
.

2. 주요 제품 및 서비스

가. 주요 제품 등의 현황

[제49기 ('21.01.01 ~ '21.12.31)]
(단위 : 백만원)

사업부문
주요제품
구체적용도
매출액
비중

컴포넌트
수동소자(MLCC 등)
PC용, 스마트폰용 등
4,771,830
49.32%

광학
카메라모듈
스마트폰용 등
3,224,056
33.32%

마. 주요 매출처

20
21년말 당사의 주요

매출처
는 가나전자와 그 종속회사 및 XIAOLONG이며,
해당 거래처에 대한 매출 비중
은
전체 매출액 대
비
약

39.0%
(
전
자 28.6%, XIAOLONG 10.4%)
입
니다
.

바. 수주상황
"""

# 매출처 문장 바로 뒤 수주잔고 표 — 품목 행('BGA(㎢)')을 매출처로 읽던 것
T11 = """마. 주요 매출처

당사 및 종속회사의 매출에서 차지하는 비중이 10% 이상인 거래처는 가나전자이며 수익금액은 약
9,638억원입니다.

6. 수주상황

당사 및 종속회사의 사업보고서 작성기준일 현재 주요제품에 대한 수주잔고 현황은 다음과 같습니다.

(단위 : 천개/㎢, 백만원)

품 목
수주
일자
납 기
수주총액
기납품액
수주잔고

수 량
금 액
수 량
금 액
수 량
금 액

HDI(㎢)
'11.01~12월
'12.01
722
360,186
717
357,124
5
3,062

BGA (천㎡)
'11.01~12월
'12.01
621
820,881
591
769,488
30
51,393
"""


def test_customers_ten_pct_group_form_value_on_next_fragment():
    assert named(T12) == {"가나전자": 50.0}                 # '가나전자 및 종속회사'(비중 없음)가 따로 남지 않는다


def test_customers_ten_pct_group_form_pct_in_next_sentence():
    assert named(T15) == {"가나전자": 61.8}


def test_customers_lead_split_by_line_fragments():
    assert named(T20) == {"가나전자": 33.7}


def test_customers_breakdown_in_parens_and_no_segment_rows():
    got = named(T21)
    assert got == {"가나전자": 28.6, "XIAOLONG": 10.4}       # 합계 39.0 은 누구 몫도 아니다 · '컴포넌트 49.32' 는 고객이 아니다


def test_customers_order_backlog_rows_are_not_customers():
    got = named(T11)
    assert "가나전자" in got
    assert not any("㎢" in n or "㎡" in n or n.startswith(("HDI", "BGA")) for n in got)


# ---------------------------------------------------------------- 2. 제품 · 원재료 표 — 칸 안 빈 줄이 행 경계로 읽히던 것
T_PROD = """가. 주요 제품 등의 현황

(단위 : 백만원,%)

사업부문
주요제품
구체적용도
순매출액
비율

가나
카메라모듈, 통신모듈
스마트폰용 등
2,636,397
42.69%

다라

수동소자(MLCC, Chip Inductor 등)

PC용,스마트폰용,범용 등
2,008,010
32.51%

마바

반도체패키지기판, 경연성인쇄회로기판

PC용, 스마트폰용 등
1,531,851
24.80%

계
6,176,258
100.00%

나. 주요 제품 등의 가격변동추이
"""

T_MAT = """가. 주요 원재료 등의 현황

(단위 : 백만원)

사업부문
매입유형
품목
용도
매입액
비중
업체명(매입처)

가나
원자재
PASTE/POWDER

수동소자
주재료

402,997
40.4%
SHOEI, GUANGBO

원자재
FILM
적층Base
220,933
22.2%
COSMO, TORAY

다라
원자재
센서 IC
센서
734,634
34.4%
가나전자(*), SONY

원자재
기타 반도체
신호 변환
246,193
11.6%

BROADCOM,
ONSEMI

원자재
기타
-
1,150,649
54.0%
-

총 계
4,010,434

나. 주요 원재료 등의 가격변동추이
"""


def test_products_cell_with_blank_lines_is_one_row():
    got = [(r["segment"], r["item"], r["amt"], r["pct"]) for r in V.products(T_PROD)]
    assert got == [("가나", "카메라모듈, 통신모듈", 2636397.0, 42.69),
                   ("다라", "수동소자(MLCC, Chip Inductor 등)", 2008010.0, 32.51),
                   ("마바", "반도체패키지기판, 경연성인쇄회로기판", 1531851.0, 24.8)]


T_PROD_LABEL = """가. 주요 제품 등의 현황

사업부문
매출유형
품 목
구체적용도
주요상표등
매출액
비율

제 약
제 품
포리부틴류
위장관운동조절제
포리부틴
14,103
6.7%

액티피드
항히스타민제
액티피드
3,843
1.8%

기 타

62,465
29.7%

소 계

118,071
56.2%

상 품
모노프로스트
녹내장
모노프로스트
14,677
7.0%

나. 가격변동추이
"""

T_PROD_CHANNEL = """가. 주요 제품 등의 현황

사업부문
매출유형
품 목
구체적용도
주요상표 등
구 분
매출액
비율(%)

화장품
제 품
기 초
피부 컨디션 개선
가나 크림 외
수 출
32,627,753
15.16%

내 수
42,711,886
19.85%

합 계
75,339,639
35.01%

색 조
피부 손질
가나 쿠션 외
수 출
65,058,972
30.24%

내 수
18,019,176
8.37%

합 계
83,078,148
38.61%

나. 가격변동추이
"""


def test_products_comma_wrapped_cell_keeps_amount():
    text = ("가. 주요 제품 등의 현황\n\n사업부문\n주요제품\n구체적용도\n매출액\n비율\n\n"
            "다라\n칩부품 (MLCC, Chip Inductor,\nChip Resistor, Crystal)\nPC용,스마트폰용,범용 등\n1,918,173\n23.2%\n\n"
            "마바\n반도체패키지기판\nPC용 등\n1,889,954\n22.9%\n\n나. 가격변동추이\n")
    got = [(r["segment"], r["item"], r["amt"], r["pct"]) for r in V.products(text)]
    assert got[0] == ("다라", "칩부품 (MLCC, Chip Inductor, Chip Resistor, Crystal)", 1918173.0, 23.2)


def test_products_merged_label_row_and_subtotal():
    got = [(r["kind"], r["item"], r["amt"]) for r in V.products(T_PROD_LABEL)]
    assert got == [("제 품", "포리부틴류", 14103.0), ("제 품", "액티피드", 3843.0), ("제 품", "기타", 62465.0), ("상 품", "모노프로스트", 14677.0)]


def test_products_numbers_row_completes_row_without_amount():
    text = ("가. 주요 제품 등의 현황\n\n업종상업부문\n매출유형\n품 목\n구체적용도\n주요상표등\n매출액\n비율\n\n"
            "제조.유류\n제 품\n윤 활 유\n공작기계 외\nD-ATF\n295,092,538\n72.8%\n\n소 계\n\n388,956,565\n96.0%\n\n"
            "상 품\n윤 활 유\n그리이스 외\n\n5,929,745\n1.4%\n\n기 타\n원 료 유\n윤활유원료\n\n10,600,345\n2.6%\n\n합 계\n\n405,486,655\n100%\n\n"
            "나. 주요 제품 등의 가격변동추이\n")
    got = [(r["kind"], r["item"], r["amt"]) for r in V.products(text)]
    assert got == [("제 품", "윤활유", 295092538.0), ("상 품", "윤활유", 5929745.0), ("기 타", "원료유", 10600345.0)]


def test_products_export_domestic_rows_are_told_apart():
    got = [(r["item"], r["amt"]) for r in V.products(T_PROD_CHANNEL)]
    assert got == [("기초 · 수출", 32627753.0), ("기초 · 내수", 42711886.0), ("색조 · 수출", 65058972.0), ("색조 · 내수", 18019176.0)]


def test_materials_leading_and_trailing_fragments():
    got = V.materials(T_MAT)
    rows = [(r["segment"], r["item"], r["amt"], [s["name"] for s in r["suppliers"]]) for r in got]
    assert rows == [("가나", "PASTE/POWDER", 402997.0, ["SHOEI", "GUANGBO"]),
                    ("가나", "FILM", 220933.0, ["COSMO", "TORAY"]),
                    ("다라", "센서 IC", 734634.0, ["가나전자(*)", "SONY"]),
                    ("다라", "기타 반도체", 246193.0, ["BROADCOM", "ONSEMI"]),
                    ("다라", "기타", 1150649.0, [])]
    assert got[0]["pct"] == 40.4


# ---------------------------------------------------------------- 3. 수출 · 내수 — 개요 문장의 '매출실적' 에서 6000자만 보던 것
SALES = """4. 매출 및 수주상황

가. 매출실적
당사의 매출은 9조 127억원입니다. 세부내역은 다음과 같습니다.

(단위 : 백만원)

사업부문
매출유형
품 목
제53기
제52기
제51기

가나
제 품
수동소자
수출
5,006,765
4,307,441
3,762,448

내수
191,737
154,609
140,574

합계
5,198,502
4,462,050
3,903,022

다라
제 품
카메라모듈
수출
3,615,414
3,534,086
2,993,994

내수
198,790
263,310
278,018

합계
3,814,204
3,797,396
3,272,012

합 계
수출
8,622,179
7,841,527
6,756,442

내수
390,527
417,919
418,592

합계
9,012,706
8,259,446
7,175,034

※ 연결재무제표기준입니다.- 매출 유형별 매출실적

(단위 : 백만원)
"""
HEAD = "1. 사업의 개요\n\n매출 유형별 매출실적은 제품/상품 8조 9,800억원, 용역 및 기타매출 3,345억원으로 구성되어 있습니다.\n\n"


def _filler(n):
    return ("당사는 고객 요구에 대응하고 있습니다.\n\n" * (n // 22 + 1))[:n] + "\n\n"


def test_export_split_total_row_beyond_first_mention_window():
    # 첫 '매출실적'(개요 문장)에서 6000자 되는 자리가 합계 행의 수출과 내수 사이에 떨어지게 — 예전엔 부문 수출 + 합계 수출을 더했다
    cut = SALES.index("8,622,179\n7,841,527\n6,756,442") + 30
    text = HEAD + _filler(6000 - cut - len(HEAD) + HEAD.index("매출실적")) + SALES
    assert HEAD.index("매출실적") + 6000 < len(HEAD) + len(_filler(6000 - cut - len(HEAD) + HEAD.index("매출실적"))) + SALES.index("\n내수\n390,527")
    got = V.export_split(text)
    assert got["export"] == 8622179e6 and got["domestic"] == 390527e6
    assert round(got["export_pct"], 1) == 95.7


def test_export_split_table_far_after_first_mention():
    got = V.export_split(HEAD + _filler(7000) + SALES)
    assert got is not None and round(got["export_pct"], 1) == 95.7


def test_export_split_segment_rows_without_total_do_not_add_totals():
    text = SALES.replace("합 계\n수출", "총매출\n수출")           # 합계 행 머리가 다르면 부문 행을 더한다 — 그래도 전체 합계 줄을 또 더하지 않는다
    got = V.export_split(text)
    assert got["export"] == (5006765 + 3615414) * 1e6


DOM_FIRST = """가. 매출실적

(단위 : 백만원)

사업부문
매출유형
품 목
제39기
제38기
제37기

-
제 품
정밀화학
내 수
153,184
159,760
140,499

수 출
19,034
15,766
14,875

합 계
172,218
175,526
155,375

제품계
내 수
153,184
159,760
140,499

수 출
19,034
15,766
14,875

합 계
172,218
175,526
155,375

상 품
상품계
내 수
16,013
16,950
11,065

수 출
6,132
3,813
4,079

합 계
22,145
20,763
15,144

합 계
내 수
169,197
176,710
151,564

수 출
25,166
19,579
18,954

합 계
194,363
196,289
170,518

가-1. 주요종속회사인 (주)가나팩스의 매출실적

(단위 : 백만원)

사업부문
매출유형
품 목
제39기
제38기
제37기

-
제 품
포장소재
내 수
39,524
41,623
42,686

수 출
7,819
8,408
6,441

합 계
47,343
50,031
49,127

합 계
내 수
39,524
41,623
42,686

수 출
7,819
8,408
6,441

합 계
47,343
50,031
49,127

나. 판매경로
"""

WIDE_THEN_SUB = """가. 매출실적
공시대상기간 중 사업부문별 매출실적(내수 및 수출)은 다음과 같습니다.

(단위:백만원)

사업부문
대상 회사
2025년
2024년

내수
수출
내수
수출

지주회사
(주)가나
389,299
-
432,079
-

총 합계
5,806,491
1,446,056
5,918,288
1,257,217

나. 매출액 및 비중

● IT 서비스 부문 (대상회사 : 가나씨엔에스)

1. 매출실적

(단위 : 백만원)

구분
매출 유형
품목
제39기말

IT 서비스
용역
개발용역
수출
900,000

내수
4,500,000
"""


MULTI_CO = """가. 매출실적

(단위 : 백만원)

회사명
사업부문
매출유형
품 목
제9기
제8기

(주)가나
음식료품제조
제품
비스킷
내 수
326,471
298,173

수 출
18,129
19,865

소 계
344,600
318,038

합 계
내 수
326,471
298,173

수 출
18,129
19,865

합 계
344,600
318,038

Gana Food Co., Ltd
음식료품제조
제품
파 이
내 수
1,000
900

수 출
-
-

합 계
내 수
1,000
900

수 출
-
-

나. 판매경로
"""

SEG_THEN_TYPE = """가. 매출실적

(1) 사업부문에 대한 정보

기간: 2025.01.01 ~ 2025.12.31

부문
매출액
영업이익

반도체
500,000
40,000

가. 매출실적
(1) 연결기준

(단위 : 백만원)

구분
품 목
제11기

제품
리더기
수출
110,741

내수
26,561
"""


CIRCLED = """가. 매출실적

① (주)가나테크 (지배회사)

(단위 : 백만원)

매출
유형
품목
제24기

제품
Probe Card
수출
4,870

내수
48,870

소계
53,740

Interface Board
수출
25,519

내수
18,608

소계
44,127

합계
97,867

② (주)가나테스트

(단위 : 백만원)

구분
국내/수입
제14기

OLED
내수
4,989

수출
5,279

합 계
내수
4,989

수출
5,279

소계
10,268

나. 판매경로
"""

KUKNAE = """1) 매출 실적

(1) 연결 기준

(단위: 백만원, %)

구분
국내 / 수출
2025년

매출액
비중

용역
국 내
46,894
56%

수 출
3,106
4%

합 계
국 내
79,746
95%

수 출
4,234
5%

(2) 별도기준

(단위: 백만원, %)

구분
국내 / 수출
2025년

용역
국 내
45,678
56%

수 출
3,106
4%

합 계
국 내
78,000
95%

수 출
4,000
5%
"""


TOTAL_WITH_TYPE = """가. 매출실적(1) 매출현황 당사 제품은 사업부문별로 전선, 중전기로 구분되며, 각 사업부문별 매출 실적은 아래와 같습니다.

(단위 : 백만원)

사업부문
매출유형
품 목
제18기

전선
제품상품
나동선 등
내수
1,027,971

수출
513,970

계
1,541,941

중전기
제품상품
변압기 등
내수
224,820

수출
274,225

계
499,045

합계
제품상품
-
내수
1,252,791

수출
788,195

계
2,040,986

(2) 지역별 매출 현황

(단위 : 백만원)

지역
제18기

국내
1,252,791

미주
297,955

합계
2,040,986

나. 판매경로
"""

OVERVIEW_TWICE = """1. 사업의 개요

당사의 주요 생산 품목은 CTS, EFEM 입니다. 보고기간종료일 현재 매출실적은 다음과 같습니다.

(단위 : 백만원)

국내/수출
금액
%

국내
139,817
85.0%

수출
24,857
15.1%

합계
164,405
100.0%

2. 주요 제품 및 서비스

주요 제품의 매출실적은 아래 표와 같습니다.

(단위 : 백만원)

국내/수출
금액
%

국내
139,817
85.0%

수출
24,857
15.1%

합계
164,405
100.0%
"""

CIRCLED_SEGMENTS = """가. 매출 실적

①

신약연구개발

(단위: 천원, %)

매출
유형
품 목
2018년도

연구용역
수출
158,670

내수
196,364

합계
수출
1,000,920

내수
1,490,063

② 의약사업부문

(단위: 천원, %)

매출
유형
품 목
2018년

제품
수출
900,000

내수
30,000,000

합계
수출
900,000

내수
30,000,000
"""


def test_export_split_total_row_with_type_cells_and_region_table_after():
    got = V.export_split(TOTAL_WITH_TYPE)                   # '합계 / 제품상품 / - / 내수' 행은 합계 · '(2) 지역별' 표의 '국내' 는 또 더하지 않는다
    assert got["export"] == (513970 + 274225) * 1e6 and got["domestic"] == (1027971 + 224820) * 1e6


def test_export_split_same_table_repeated_after_next_heading():
    got = V.export_split(OVERVIEW_TWICE)
    assert got["export"] == 24857e6 and got["domestic"] == 139817e6


def test_export_split_circled_segments_are_not_one_company():
    assert V.export_split(CIRCLED_SEGMENTS) is None           # ① 신약 · ② 의약 사업부문 — ① 몫만 회사 수출로 적지 않는다


def test_export_split_circled_entity_tables_parent_only():
    got = V.export_split(CIRCLED)                           # ② 종속회사 표의 합계가 아니라 ① 지배회사 행 합
    assert got["export"] == (4870 + 25519) * 1e6 and got["domestic"] == (48870 + 18608) * 1e6


def test_export_split_kuknae_label_and_consolidated_first():
    got = V.export_split(KUKNAE)                            # '국 내' = 내수, 연결 표 먼저(뒤 '(2) 별도기준' 표가 아니라)
    assert got["export"] == 4234e6 and got["domestic"] == 79746e6


def test_export_split_does_not_jump_to_far_subsidiary_section():
    head = "가. 매출실적\n\n- 연결 (지역에 대한 정보)\n\n(단위 : 백만원)\n\n구분\n제28기\n\n국내\n443,867\n\n해외\n56,295\n\n나. 판매경로\n\n"
    sub = "가.매출실적 (별도기준)\n\n(단위 : 백만원)\n\n유형\n품목\n2018년\n\n제품\n가스\n수출\n27,896\n\n합계\n27,896\n"
    assert V.export_split(head + _filler(20000) + sub) is None          # 2만 자 뒤 자회사 절의 표는 이 회사 것이 아니다


def test_export_split_multi_company_table_takes_first_block():
    got = V.export_split(MULTI_CO)                          # 마지막 블록(종속법인, 수출 '-')이 아니라 회사 자신
    assert got["export"] == 18129e6 and got["domestic"] == 326471e6


def test_export_split_skips_title_table_without_export_rows():
    got = V.export_split(SEG_THEN_TYPE)                     # 부문 정보 표엔 수출 · 내수 칸이 없다 — 다음 '매출실적' 표로
    assert got["export"] == 110741e6 and got["domestic"] == 26561e6


def test_export_split_domestic_first_and_subsidiary_table_after():
    got = V.export_split(DOM_FIRST)                         # 지배회사 합계 행 — 뒤 '가-1.' 종속회사 표의 합계가 아니다
    assert got["export"] == 25166e6 and got["domestic"] == 169197e6


def test_export_split_stops_when_title_table_unreadable():
    assert V.export_split(WIDE_THEN_SUB) is None             # 가로형 표를 못 읽었다고 계열사 부문의 '1. 매출실적' 으로 가지 않는다


# ---------------------------------------------------------------- 4. 경쟁 — 각주 · 특허 · 다짐 문장 대신 점유율 표
COMP = """(시장여건)

수동소자의 수요가 늘고 있습니다.

제 품
2025년
2024년
2023년

MLCC
23%
23%
21%

※ 시장점유율은 당사의 추정치이므로 조사기관별로 시장점유율이 상이할 수 있습니다.

당사는 지속적인 최선단품 개발을 통해 글로벌 시장 점유율을 확대하고 견조한 수익성을 확보하겠습니다.

이들은 대부분 스마트폰 부품 등에 관한 특허로서 당사 제품에 사용중이거나 향후 활용될 예정으로, 사업보호의 역할뿐만 아니라 경쟁사 견제의 역할도 하고 있습니다.

중국 경쟁업체의 저가 공세로 범용 제품의 가격 경쟁이 심화되고 있습니다.
"""


def test_competitors_share_table_and_no_boilerplate():
    got = V.competitors(COMP)
    assert any("MLCC" in s and "23%" in s and "2025" in s for s in got)
    assert any(s.startswith("중국 경쟁업체") for s in got)
    assert not any(s.startswith("※") or "특허" in s or "하겠습니다" in s for s in got)


# ---------------------------------------------------------------- 5. 영문 매입처 → 상장사(CORPCODE corp_eng_name)
CORPS = [("905070", "가나신소재", "GANA ADVANCED MATERIALS &amp; TECHNOLOGY CO., LTD", "20260515"),
         ("905420", "가나화학", "GANACHEMICALCO.,LTD", "20260319"),
         ("939960", "가나로보틱스", "GANA ROBOTICS CO., Ltd", "20260701"),
         ("978600", "다라전자재료", "DaraElectronicMaterialsCo.,Ltd.", "20221207"),
         ("903310", "다라산업", "Dara Inc.", "20260320"),
         ("900150", "마바", "MABA CO.,LTD", "20260506"),
         ("934020", "마바에너빌리티", "MABA ENERBILITY CO., LTD.", "20260506"),
         ("976610", "사아옵틱스", "Saa Optics Co.,Ltd", "20231128"),
         ("990740", "자차", "JACHA CO.,Ltd", "20220225"),
         ("992220", "KEX", "KEX Corporation", "20250101"),
         ("900830", "가나물산", "GANA C&amp;T", "20170630"),
         ("928260", "가나물산", "GANA C&amp;T Corporation", "20260323")]
COLLECTED = {"905070", "905420", "939960", "978600", "900150", "934020", "928260"}


@pytest.mark.parametrize("name, prefer, code", [
    ("GANA AMT", (), "905070"),                 # 머리 낱말 + 머리글자
    ("GANA", (), None),                         # 수집 회사 둘(신소재 · 로보틱스)이 'GANA' 로 시작 — 고를 수 없으면 잇지 않는다
    ("GANA", ("905070", "905420"), "905070"),   # 나를 고객으로 적은 회사로 좁히면 하나
    ("DARA", (), "978600"),                     # 붙여 쓴 영문(DaraElectronicMaterials) — 수집 회사 첫 낱말이 비수집 통째 일치보다 먼저
    ("MABA", (), "900150"),                     # 통째 일치가 첫 낱말(MABA ENERBILITY)보다 먼저
    ("SAA OPTICS", (), "976610"),               # 비수집 상장사도 통째 일치면
    ("JACHA", (), "990740"),
    ("KEX", (), None),                          # 4글자 미만은 잇지 않는다
    ("SONY", (), None),
])
def test_en_names_code(name, prefer, code):
    assert V.EnNames(CORPS).code(name, COLLECTED, prefer) == code


def test_country_cosmo_not_japan():
    assert V._country("COSMO") != "일본"


# ---------------------------------------------------------------- 6. 서버 — 이름 키 · 상장사 이름 · valuechain_view
ME = "999150"


@pytest.fixture(scope="module")
def SRV():
    sp = ilu.spec_from_file_location("서버_vc_시험", os.path.join(BASE, "서버.py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _corpcode_xml(rows):
    body = "".join("<list><corp_code>%08d</corp_code><corp_name>%s</corp_name><corp_eng_name>%s</corp_eng_name><stock_code>%s</stock_code>"
                   "<modify_date>%s</modify_date></list>" % (i, nm, en, sc, md) for i, (sc, nm, en, md) in enumerate(rows))
    return '<?xml version="1.0" encoding="UTF-8"?><result>%s</result>' % body


@pytest.fixture
def srv(SRV, monkeypatch, tmp_path):
    (tmp_path / "CORPCODE.xml").write_text(_corpcode_xml(CORPS), encoding="utf-8")
    cos = [{"code": ME, "name": "다라전기", "reports": []}] + [{"code": sc, "name": nm, "reports": []} for sc, nm, _, _ in CORPS if sc in COLLECTED]
    monkeypatch.setattr(SRV, "INDEX", {"companies": cos, "built": 0})
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "_NAMES", {})
    monkeypatch.setattr(SRV, "_NAMES_EN", {})
    by = {c["code"]: c for c in cos}
    monkeypatch.setattr(SRV, "company_by_code", lambda c: by.get(c))
    monkeypatch.setattr(SRV, "_ord_series", lambda c, budget=0, net=True: [])
    return SRV


@pytest.mark.parametrize("nm", ["가나전자 및 종속회사", "가나전자와 그 종속기업", "가나전자 및 가나전자의 해외종속회사", "가나전자(주)"])
def test_vc_key_strips_group_suffix(SRV, nm):
    assert SRV._vc_key(nm) == SRV._vc_key("가나전자")
    assert SRV._vc_canon(nm).startswith("가나전자")
    assert "종속" not in SRV._vc_canon(nm)


def test_listed_names_prefers_newest_modify_date(srv):
    assert srv._listed_names()[srv._norm_corp("가나물산")] == "928260"        # 옛 상폐 corp(900830)이 종목코드를 단 채 남아 있다


def _fake_vc(srv, monkeypatch, years):
    monkeypatch.setattr(srv, "_vc_company", lambda c: {"code": c["code"], "name": c["name"], "years": years})
    me_k = srv._vc_key("다라전기")
    monkeypatch.setattr(srv, "_vc_peers", lambda: {"cust": {me_k: [("905070", "가나신소재", None, "다라전기"), ("905420", "가나화학", None, "다라전기")]},
                                                   "supp": {}, "prod": {}, "n": 3})


def test_valuechain_view_links_english_suppliers_and_merges_group_suffix(srv, monkeypatch):
    mats = [{"segment": "가나", "item": "기타", "amt": 900.0, "pct": 50.0, "suppliers": []},
            {"segment": "다라", "item": "기타", "amt": 800.0, "pct": 60.0, "suppliers": []},
            {"segment": "가나", "item": "FILM", "amt": 300.0, "pct": 20.0, "suppliers": [{"name": "GANA", "country": "해외"}, {"name": "TOREX", "country": "해외"}]},
            {"segment": "다라", "item": "ACTUATOR", "amt": 200.0, "pct": 20.0, "suppliers": [{"name": "JACHA", "country": "해외"}, {"name": "SAA OPTICS", "country": "해외"}]},
            {"segment": "가나", "item": "PASTE", "amt": 100.0, "pct": 10.0, "suppliers": [{"name": "DARA", "country": "해외"}]}]
    prods = [{"segment": "컴포넌트", "item": "수동소자", "amt": 10.0, "pct": 49.3}]
    years = {"2024": {"customers": [{"name": "가나전자 및 종속회사", "pct": None, "kind": "named", "scope": "연결"},
                                    {"name": "컴포넌트", "pct": 49.3, "kind": "named", "scope": "표"}], "materials": mats, "products": prods},
             "2025": {"customers": [{"name": "가나전자", "pct": 27.0, "kind": "named", "scope": "연결"}], "materials": mats, "products": prods}}
    _fake_vc(srv, monkeypatch, years)
    d = srv.valuechain_view(ME)
    cust = {h["name"]: h for h in d["customers"]}
    assert set(cust) == {"가나전자"}                                       # '및 종속회사' 는 같은 고객 · 부문 이름은 고객 아님
    assert cust["가나전자"]["by_year"] == {"2024": None, "2025": 27.0}
    sp = {s["name"]: s for m in d["materials"] for s in m["suppliers"]}
    assert sp["GANA"]["link"]["code"] == "905070" and sp["GANA"]["country"] == "한국"
    assert sp["DARA"]["link"]["code"] == "978600" and sp["JACHA"]["link"] == {"code": "990740", "collected": False, "name": None}
    assert sp["SAA OPTICS"]["link"]["code"] == "976610" and sp["SAA OPTICS"]["country"] == "한국"
    assert sp["TOREX"]["link"] is None and sp["TOREX"]["country"] == "해외"
    hist = {h["name"]: h for h in d["suppliers_hist"]}
    assert hist["GANA"]["link"]["code"] == "905070" and hist["GANA"]["country"] == "한국"
    # '기타' 원재료는 금액이 커도 뒤로 — 지도 카드 위 여섯 자리를 차지하지 않게
    assert [m["item"] for m in d["materials"]][:3] == ["FILM", "ACTUATOR", "PASTE"]
    assert [m.get("etc") for m in d["materials"]] == [False, False, False, True, True]
