# -*- coding: utf-8 -*-
"""
산업 성장률 — 섞인 회사의 사업부문별 매출 · 영업이익 (2026-10-06)

산업_섹터.SEGMENTS 에 적힌 열네 회사(삼성전자 · SK이노베이션 · LG화학 · 한화솔루션 · POSCO홀딩스 · HD현대, 2026-10-06 추가
현대자동차 · KT · 삼성물산 · 현대글로비스 · 풍산 · 현대로템 · LG생활건강 · SKC)는
연결 매출 하나를 한 섹터에 넣으면 틀린다(삼성전자 = 반도체 + 디스플레이 + 가전·IT). 부문마다 따로 넣으려고
수집해 둔 정기보고서 본문에서 부문별 매출 · 영업이익을 읽는다 → .cache/산업/부문.json (산업.py 가 합칠 때 쓴다).

2026-10-06 고침 · 확장
  · 저장 이름(name)은 빈칸을 뺀다('석 유' → '석유', 'Industry 소재' → 'Industry소재', 삼성 '기타(DS내잔여)').
    보고서 원문이 다르면 name_src 에 남긴다(오타 'Haman' · '기업사업부분', 삼성물산 2016 '건설1' → '건설' 도 같은 방식).
    SK이노베이션 2021 2 · 3분기 '석 유' · '화 학'이 이제 '석유' · '화학'으로 저장돼 정규식에 맞는다.
  · 새 표 모양: 부문이 행인 표의 '3개월 · 누적' 짝 칸(KT · 현대로템 분기)과 한 '(단위' 아래 당기 표 + 전기 표(row_blocks),
    부문마다 '당기 · 전기' 짝 칸(풍산 옛 서식 — 칸이 당기 · 전기를 정한다), XBRL '매출액 · 내부거래 · 순매출액' 세 칸 묶음 뒤
    합계 칸(삼성물산), 머리글에 부문 이름이 두 번 — 총매출 묶음 + 부문간 제거 묶음(dup_cols: 삼성물산 2026 · 풍산 2024),
    부문 행 표의 '부문 합계' 줄(소계면 건너뛰고 아니면 제거 묶음), 머리글 맨 앞 XBRL 축 이름 '부문 합계'(자리 맞추기 안 함 —
    LG생활건강 2024), '(가) 매출액' 줄 머리 · '(**)' 각주, 300자 넘는 문단 끝의 '(단위' 줄(unit_line_max), '누적 당 3분기' 글자.
  · '매출액' + '내부매출액' 표에서 매출액이 이미 외부매출인지(현대차 2021 ~ 2022)는 원장으로 가린다(gross_is_ext).
  · 회사별 설정(CO): row_kind(줄 이름 뜻 바꾸기 — 삼성물산 '외부매출액' = 총매출 · '순매출액' = 외부), rename_solo, gone,
    op_pti(부문 영업이익이 없어 세전이익을 쓴다 — 풍산), keep_ni(부문 순손익만 있으면 segments 의 ni — SKC 2024 ~),
    prefer_restated · skip_restated · drop_q(재작성 숫자를 쓰거나 버리거나 같은 기준이 안 되는 분기를 뺀다 — 아래 한계).
  · 추가 회사만(NEW_2026_10): 원장과 안 맞고 기간 글자도 없는 전기 표는 머리글이 같은 당기 표의 길이를 따른다
    (prev_span_from_cur), 다음 해 보고서가 전년 숫자를 다른 구성으로 다시 쓴 기간(섹터에 넣는 부문 매출 3% 넘게 차이)에는
    'restated_by_next'(다음 해 기준 부문 숫자)를 붙이고 issues 에 남긴다(check_restated). 저장 숫자는 처음 보고 그대로.

출처(네트워크는 쓰지 않는다 — 기업추적_수집/<회사>_<코드>/<기간>_<종류>_<접수번호>/ 의 텍스트만 읽는다)
  1) 연결재무제표 주석의 '영업부문 · 부문별 보고 · 부문정보' 표
       사업보고서 = '(첨부)연결재무제표' 감사보고서 주석(없으면 「III. 재무에 관한 사항 > 3. 연결재무제표 주석」)
       분기 · 반기 = 「III. 재무에 관한 사항 > 3. 연결재무제표 주석」. 정정본 · 원본을 모두 후보로 놓고 점수로 고른다.
  2) 「II. 사업의 내용」 '사업부문별 요약 재무현황 · 연결재무현황' — 주석 표를 못 읽은 기간의 대체(한화솔루션 2016~2022 일부),
     그리고 POSCO홀딩스 영업이익(주석 '부문이익'은 순이익 기준이라 매출만 주석에서, 영업이익은 II 에서 부문 이름으로 맞춘다).
검산은 .cache/fin 의 DART 원장(CFS)을 직접 읽는다. 원장 파일이 없는 기간(SK이노베이션 2015~2021 분기 등)은
보고서 본문 손익계산서(본문재무.py 의 표 읽기 함수만 빌려 쓴다 — 그 캐시는 쓰지 않는다)로 대신한다.

표 읽기
  본문 텍스트는 표의 칸이 한 줄씩 풀려 있고 빈 칸은 사라진다. 옛 서식은 행 사이에 빈 줄, 2023년 이후 XBRL 서식은
  칸마다 빈 줄이다. 그래서 줄 구조 대신 '글자 칸 + 뒤따르는 숫자 칸들 = 한 행'으로 읽고,
  부문 이름은 회사별 이름 목록(CO[code]['seg'])으로 머리글에서 찾는다. 단위(원 · 천원 · 백만원 · 억원)는 '(단위' 줄로 원 환산.
    · 머리글 칸 수 = 숫자 칸 수이면 자리로 맞춘다(소계 · 연결조정 · 합계 칸이 어디 있든).
    · 아니면 '부문 칸이 먼저, 그 뒤가 소계 · 조정 · 합계'로 본다. '기타'는 부문 끝으로, 하위 칸(삼성 DS 의
      반도체 · DP, POSCO 인프라의 무역 · 건설 · 물류)은 부모 자리에 끼운다. 사라진 부문(한화 리테일) 칸이 비어
      값이 당겨진 XBRL 표는 '앞 k 칸 합 = 부문 합계 칸'으로 알아채 그 부문을 뺀다.
    · '3개월 · 누적' 짝 칸, '영업부문 · 부문간 제거 · 순액' 세 칸 묶음, 부문이 행인 표(HD현대 · POSCO II)도 읽는다.
  표가 당기 · 전기, 3개월 · 누적 중 무엇인지는 원장 연결 매출(당기 · 전년 같은 기간)과 1.5% 안에서 가장 가까운 자리로
  정하고, 원장과 안 맞으면 표 앞 글자(당분기 · 전반기 · 3개월 · 누적 · '2015 1분기' · '제 52(당) 기 3분기')로 정한다.

단독 분기 = 3개월 표가 있으면 그것, 없으면 누적 − 직전 누적(부문 이름별), 4분기 = 사업보고서 연간 − 3분기 누적.
  부문 구성이 해 중간에 바뀌면 다음 해 보고서의 전년 비교 숫자(재작성)로 빼 보고, 원장 3개월 매출 · 영업이익과
  맞는 쪽을 쓴다('석유 및 화학' = 직전 누적의 '석유' + '화학'처럼 '및' 이름은 묶어서 뺀다). 고른 방법은 derived 에 적는다.
매출은 외부매출(부문간 거래 제외)을 먼저 쓰고, 총매출 · 내부매출만 있으면 둘의 차, 총매출만 있으면 그대로 쓴다(basis).
  삼성전자의 '순매출액'은 회사 안 부문간 매출을 포함한다(주석 각주) — basis '부문간 내부거래 포함'.
삼성전자 DS 가 반도체 · DP 를 품던 해(2015~2021)는 DS 합계 대신 반도체 · DP 와 '기타(DS내잔여)'(섹터 skip)를 쓴다.
elim_rev = 표의 연결 매출 합계 − 부문 합, other_rev = 정부보조금(IRA AMPC) 등 매출 밖 영업수익(있을 때).

검산(각 레코드의 check · 회사 issues): |sum_rev + elim_rev − 원장 매출| / 원장 < 2%(안 되면 other_rev 까지 더해 본다),
  부문 영업이익 합이 원장 영업이익과 5% 안, 아니면 표의 연결조정까지 더해 5% 안(이유를 남긴다).

한계
  · 부문 이름 → 섹터(sector)는 산업_섹터.SEGMENTS 정규식 그대로다(맞는 게 없으면 'skip'). 정규식이 놓친 이름은
    regex_miss 와 '점검' 출력에 제안 정규식과 함께 남긴다(산업_섹터.py 는 고치지 않는다).
  · SK이노베이션 2024 사업보고서부터 주석 부문이 '석유 및 화학' → '에너지 및 화학'으로 합쳐져 정유 · 석유화학을 가를 수 없다.
  · POSCO홀딩스 II 요약표 영업이익은 2023년부터 회사별 별도 기준 합(연결조정 없음, 기타에 지주 배당수익)이라 합이 연결
    영업이익보다 크다. 2022 1분기는 물적분할 전 1~2월 철강분이 원래 보고서에서 기타부문에 있어 재작성 숫자를 쓴다.
  · HD현대 2017년은 설립(4월) 이후 9개월이다.
  · 현대자동차: 차량 · 금융 · 기타(현대로템 포함). 2022 ~ 2023 주석 이름은 '자동차'(ALIAS 로 차량과 같은 부문으로 뺀다).
  · KT: 주석의 부문 영업수익은 부문간 거래 포함(basis '부문간 내부거래 포함', 연결조정 칸이 elim). 2015 ~ 2018 은
    Marketing/Customer(+2018 기업사업) — ICT 정규식에 안 맞는다. 2019 1 · 2분기는 2020 보고서의 ICT 재작성 숫자,
    2019 3분기는 옛 구성 그대로, 2019 4분기는 같은 기준이 없어 뺀다(drop_q).
  · 삼성물산: 2015 1 · 2분기는 합병 전 제일모직(건설 · 레져 · 급식/식자재유통 · 패션), 2015 연간 · 3 · 4분기는 합병(9-1)
    뒤 건설1(구 삼성물산, 9월부터) · 건설2(구 제일모직) — 2015 · 2016 증가율은 합병 효과다. 바이오 = 삼성바이오로직스 연결.
  · 현대글로비스: 2015 ~ 2017 은 물류(해운 포함) · CKD · 기타라 해운을 못 가른다. 2018 은 2019 보고서들의 물류 · 유통 · 해운
    재작성 숫자(prefer_restated).
  · 풍산: 주석에 부문 영업이익이 없다 — 부문 '법인세비용차감전순손익'을 영업이익 자리에 쓰고 op_basis 에 적는다(검산은
    대부분 5% 밖 — 이유가 check.why 에 있다).
  · 현대로템: 중기(2015 ~ 2016) = 방산, 2026 반기부터 AD&RH · RS · EP — 지금 정규식은 중기 · AD&RH 를 못 맞춘다.
  · LG생활건강: 2015 ~ 2019 Healthy · Beautiful · Refreshing(정규식 Beauty · Refreshment 에 안 맞음). 2026 보고서는
    2025 를 HDB → Beauty 로 옮겨 다시 썼다(restated_by_next).
  · SKC: 2024 1분기부터 주석 · II 모두 부문 영업이익 없이 부문 순손익만 낸다(op 없음, ni 에 둠). 2020 Mobility(SK넥실리스 동박)는
    2차전지 정규식에 안 맞는다. 중단영업 재분류가 잦아 2023 4분기는 뺀다(drop_q), 2022 1 · 2분기는 2023 보고서 재작성 숫자.

CLI: python 산업_부문.py        → 만든다(약 2 ~ 4분, 구글 드라이브 읽기가 대부분)
     python 산업_부문.py 점검   → 만든 부문.json 의 검산표(부문 합 + 조정 vs 원장 연결 매출 · 영업이익)를 찍는다
"""
import os
import re
import sys
import glob
import json
import time
import datetime as dt
import importlib.util

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "기업추적_수집")
FIN_DIR = os.path.join(BASE, ".cache", "fin")
OUT_DIR = os.path.join(BASE, ".cache", "산업")
OUT = os.path.join(OUT_DIR, "부문.json")
VERSION = 1
YEARS = range(2015, 2027)               # 2015 연간 ~ 2026 분기

sys.path.insert(0, BASE)
import 산업_섹터 as SEC                  # noqa: E402

_BODY = None


def _body_mod():
    """본문재무.py — 손익계산서 표 읽기 함수만 빌린다(statement() 는 캐시를 쓰므로 부르지 않는다)."""
    global _BODY
    if _BODY is None:
        sp = importlib.util.spec_from_file_location("본문재무_ro", os.path.join(BASE, "본문재무.py"))
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _BODY = m
    return _BODY


# ---------------------------------------------------------------- 회사 설정
# seg: 머리글 · 행 이름(빈칸 · 각주 뗀 것)이 부문인지 가르는 정규식. kids: (부모, 자식, 부모 합계 칸이 있는가)
CO = {
    "005930": {"name": "삼성전자", "corp": "00126380",
               "seg": r"^(?:CE|IM|DS|DX|SDC|DP|Harman|Haman|반도체)(?:부문)?$",       # 'Haman' — 2026 1 · 반기 보고서 오타
               "kids": [(r"^DS(?:부문)?$", r"^(?:반도체|DP)$", True)],
               "src": ("note", "biz")},
    "096770": {"name": "SK이노베이션", "corp": "00631518",
               "seg": r"^(?:석유|화학|윤활유|배터리|소재|석유개발|자원개발|E&P|이엔에스|이앤에스|E&S|에너지및화학|석유및화학|"
                      r"배터리및소재|에너지/화학|배터리/소재|기타)(?:사업|부문)?$",
               "kids": [], "src": ("note", "biz")},
    "051910": {"name": "LG화학", "corp": "00356361",
               "seg": r"^(?:기초소재|석유화학|정보전자소재|정보전자소재및재료|전지|재료|첨단소재|생명과학|LG에너지솔루션|에너지솔루션|"
                      r"팜한농|공통부문및기타|기타)(?:사업|부문)?$",
               "kids": [], "src": ("note", "biz")},
    "009830": {"name": "한화솔루션", "corp": "00162461",
               "seg": r"^(?:원료|가공|유통|태양광|기타|기초소재|가공소재|리테일|신재생에너지|첨단소재|케미칼|큐셀|도시개발|갤러리아)"
                      r"(?:사업|부문)?$",
               "kids": [], "gone": r"^리테일", "src": ("note", "biz")},
    "005490": {"name": "POSCO홀딩스", "corp": "00155319",
               "seg": r"^(?:철강|무역|건설|E&C|기타|친환경인프라|친환경미래소재|인프라|이차전지소재|에너지소재|에너지등|물류등|"
                      r"(?:친환경)?인프라(?:부문)?\((?:무역|건설|물류등|에너지등)(?:부문)?\))(?:사업|부문)?$",
               "kids": [(r"^(?:친환경)?인프라(?:부문)?$", r"^(?:무역|건설|물류등|에너지등)(?:부문)?$", False)],
               # 매출은 주석(외부매출액), 영업이익은 II '사업부문별 요약 재무현황'(주석의 부문이익은 순이익 기준)
               "src": ("note", "biz"), "op_from": "biz",
               "op_note": "II 요약표의 부문 영업이익은 회사별 별도 기준 합이라 연결조정이 없다(기타에 지주 배당수익 포함) — "
                          "철강 등 각 부문 값은 보고서 그대로",
               # 물적분할(2022-03-02) 전 1~2월 포스코 철강 매출 · 이익이 원래 1분기 보고서에서는 기타부문에 들어 있다
               "prefer_restated": {(2022, 1): "물적분할(2022-03-02) 전 1~2월 포스코 철강분이 원래 보고서에서는 기타부문에 있어 "
                                              "2023년 1분기 보고서의 재작성 숫자를 쓴다(영업이익은 주석 부문이익 — 순이익 기준)"}},
    "267250": {"name": "HD현대", "corp": "01205709",
               "seg": r"^(?:로봇|정유|전기전자|건설장비|건설기계|선박서비스|선박AM|조선해양|조선|기타|에너지)(?:사업|부문)?$",
               "kids": [], "src": ("note", "biz"),
               "partial": {2017: "2017년은 설립(2017-04-01, 현대중공업 인적분할) 이후 9개월 — 연간 · 2분기 모두 4월부터"}},
    # ---- 2026-10-06 추가 여덟 회사(산업_섹터.SEGMENTS 확장)
    "005380": {"name": "현대자동차", "corp": "00164742",
               "seg": r"^(?:차량|자동차|금융|기타)(?:사업)?(?:부문)?$", "kids": [], "src": ("note", "biz")},
    # KT 주석의 부문 영업수익은 부문간 거래 포함(총액) — 연결조정 칸이 따로 있다. 2015 ~ 2018 은 'Marketing/Customer'(+2018 기업사업)
    "030200": {"name": "KT", "corp": "00190321",
               "seg": r"^(?:ICT|Marketing/Customer|Customer/Marketing|기업사업|금융|위성방송|미디어/?콘텐츠|부동산|기타)"
                      r"(?:사업)?(?:부문|부분)?$", "kids": [], "src": ("note", "biz"), "row_blocks": True,  # '기업사업부분' — 2018 1분기 오타
               # 2019 사업보고서부터 ICT(= 옛 Marketing/Customer + 기업사업 + 기타 일부). 2020 1 · 2분기 보고서는 2019 비교 숫자를
               # ICT 로 재작성했지만 2020 3분기 보고서의 2019 3분기 비교 숫자는 옛 구성 그대로(ICT 9개월 10.4조 vs 연간 18.2조)다
               "prefer_restated": {(2019, 1): "2019 사업보고서의 ICT 구성(2020 1분기 보고서의 재작성 숫자)",
                                   (2019, 2): "2019 사업보고서의 ICT 구성(2020 반기 보고서의 재작성 숫자)"},
               "skip_restated": {(2019, 3): "2020 3분기 보고서의 2019 3분기 비교 숫자는 재작성이 안 된 옛 구성"
                                            "(ICT = Marketing/Customer + 기업사업, 9개월 10.4조)이라 2019 연간 ICT(18.2조)와 기준이 다르다"},
               "drop_q": {"2019Q4": "2019 연간(ICT 구성) − 3분기 누적(옛 Marketing/Customer 구성)은 같은 기준이 아니고 "
                                    "ICT 구성의 3분기 누적이 어느 보고서에도 없다"}},
    # 2015 1 · 2분기는 합병 전 제일모직(건설 · 레져 · 급식/식자재유통 · 패션), 2015 연간은 합병(9-1) 뒤 건설1(구 삼성물산) · 건설2(구 제일모직)
    "028260": {"name": "삼성물산", "corp": "00149655",
               "seg": r"^(?:건설\d?|상사|패션|리조트|레져|식음|급식/식자재유통|바이오|공통|미배분손익|기타)(?:사업)?(?:부문)?$",
               "kids": [], "src": ("note", "biz"),
               # 주석의 '외부매출액'은 부문간 거래를 빼기 전 금액이고 '순매출액'(= 외부매출액 − 내부거래)이 외부매출이다
               "row_kind": {"외부매출액": "gross", "순매출액": "ext"},
               "rename_solo": {"건설1": "건설"},
               # 2026 XBRL: 순매출액 줄 = 부문 총매출 묶음 + 부문간 제거 묶음(dup_cols), 순매출액만 낸 표는 0 인 '공통' 칸이 빠진다(gone)
               "dup_cols": True, "gone": r"^공통",
               # 2022 반기 ~ 2023 3분기: '(단위:백만원)'이 300자 넘는 설명 문단 끝에 붙어 있다
               "unit_line_max": 700},
    "086280": {"name": "현대글로비스", "corp": "00360595",
               "seg": r"^(?:물류|해운|유통|CKD|기타)(?:사업)?(?:부문)?$", "kids": [], "src": ("note", "biz"),
               # 2015 ~ 2018 보고서는 물류(해운 포함) · CKD · 기타. 2019 사업보고서가 2018 을 물류 · 유통 · 해운으로 재작성했다
               "prefer_restated": {(2018, 4): "2018 사업보고서는 물류(해운 포함) · CKD · 기타 구성 — 2019 사업보고서의 "
                                              "물류 · 유통 · 해운 재작성 숫자를 쓴다(분기도 2019 보고서들의 재작성 숫자)"}},
    # 풍산 주석은 부문 영업이익을 내지 않는다 — 부문 '법인세비용차감전순손익'을 영업이익 자리에 쓴다(op_basis 에 적는다)
    "103140": {"name": "풍산", "corp": "00684714",
               "seg": r"^(?:신동(?:사업|산업)?|방위산업|방산|공통|기타)(?:부문)?$", "kids": [], "src": ("note", "biz"),
               "op_pti": True,
               # 2024 반기 · 3분기 XBRL 은 '수익(매출액)' 줄이 [부문 총매출, 소계, 부문간 제거, 소계, 합계] — 부문 순액 = 총 + 제거
               "dup_cols": True,
               # 2023 ~ 2024 1분기 표: '부문수익'(총) · '내부거래조정' · '수익(매출액)'(외부) — 외부 줄을 쓴다
               "row_kind": {"수익(매출액)": "ext"}},
    # 중기(2015 ~ 2016) = 방산(K2 전차 등), 2026 부터 AD&RH(방산) · RS(레일) · EP(에코플랜트)
    "064350": {"name": "현대로템", "corp": "00302926",
               "seg": r"^(?:철도|중기|방산|플랜트|레일솔루션|디펜스솔루션|에코플랜트|RS|AD&RH|EP|기타)(?:사업)?(?:부문)?$",
               "kids": [], "src": ("note", "biz"), "row_blocks": True},
    # 2015 ~ 2019 Healthy · Beautiful · Refreshing → 2020 ~ HDB · Beauty · Refreshment
    "051900": {"name": "LG생활건강", "corp": "00356370",
               "seg": r"^(?:Healthy|Beautiful|Refreshing|HDB|Beauty|Refreshment|화장품|생활용품|음료|기타)(?:사업)?(?:부문)?$",
               "kids": [], "src": ("note", "biz")},
    # 필름 · 화학 · 정보통신(2015) → Industry 소재 · 화학 · 전자재료 · BHC(2017 ~ 2019) → + Mobility(2020 SK넥실리스) →
    # 화학 · 반도체 소재 · 2차전지 소재(2022 ~). 2023 이후 주석 · II 모두 부문 영업이익 없이 부문 순손익만 낸다(op 없음)
    "011790": {"name": "SKC", "corp": "00139889",
               "seg": r"^(?:필름|화학|정보통신|Industry소재|인더스트리소재|전자재료|BHC|Mobility|모빌리티(?:소재)?|반도체소재|"
                      r"2차전지소재|이차전지소재|기타)(?:사업)?(?:부문)?$",
               "kids": [], "src": ("note", "biz"), "keep_ni": True,
               # 2023 사업보고서는 SK피유코어(화학) 등을 중단영업으로 바꿔 연간을 냈는데 3분기 누적은 그 전 기준 — 연간 − 3분기 누적이
               # 음수가 된다(원장 4분기도 같은 이유로 음수). 2024 보고서들의 2023 재작성 숫자도 보고서마다 중단영업 범위가 달라
               # (3분기 보고서의 9개월 − 반기 보고서의 6개월 = 3분기 2,993억) 같은 기준의 4분기를 만들 수 없다 — 4분기는 뺀다.
               # 1 ~ 3분기 · 연간은 처음 보고 그대로, 다음 해 기준 숫자는 restated_by_next 에 붙는다
               "skip_restated": {(2023, 3): "2024 3분기 보고서의 2023 9개월은 2024 반기 보고서의 2023 6개월과 중단영업 범위가 달라 "
                                            "빼면 3분기가 2,993억(처음 보고 5,506억)이 된다"},
               "drop_q": {"2023Q4": "2023 연간(중단영업 재분류 뒤) − 3분기 누적(재분류 전)은 음수 매출(화학 −2,474억)이고 "
                                    "같은 기준의 2023 3분기 누적이 어느 보고서에도 없다"}},
}
# 2026-10-06 추가 회사 — 다음 해 보고서의 재작성 비교 숫자와 어긋나는 기간을 찾아 'restated_by_next' 를 붙인다(기존 여섯 회사는 그대로)
NEW_2026_10 = ("005380", "030200", "028260", "086280", "103140", "064350", "051900", "011790")
for _c in NEW_2026_10:
    CO[_c]["check_restated"] = True
    CO[_c]["prev_span_from_cur"] = True
ETC_RE = re.compile(r"^(?:공통부문및)?기타(?:사업|부문)?$")
TYPO = {"Haman": "Harman", "기업사업부분": "기업사업부문"}      # 보고서 원문 오타 → 바른 이름(name_src 에 원문을 남긴다)

# ---------------------------------------------------------------- 칸 읽기
UNIT_RE = re.compile(r"단위\s*[:：]?\s*(천원|백만원|억원|원)")
UNIT_MUL = {"원": 1.0, "천원": 1e3, "백만원": 1e6, "억원": 1e8}
FOOT_RE = re.compile(r"\(\s*\*+\s*\d*\s*\)|\(\s*주\s*\d*\s*\)|\*\d+\)?|(?<![가-힣A-Za-z])주\s*\d\)")
NUM_RE = re.compile(r"^[+\-−△▲]?\s*\(?\s*[+\-−△▲]?\s*\d[\d,]*(?:\.\d+)?\s*\)?$")
DASH_RE = re.compile(r"^[-−–—]$")
PCT_RE = re.compile(r"^\(?[+\-−△]?\s*[\d.,]+\s*\)?\s*%\s*\)?$|^[-−]\s*%$")      # '38%' '(18%)' '(16%)' — 비중 칸은 버린다
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
JUNK_RE = re.compile(r"^(?:\(|\)|\*|\(\*|\*?\d\)|\(\s*\*\s*\d?\s*\)?)$")    # 각주 조각 '(' '*' '1)' '(*1)' — '0' · '(1)' 은 값이다


def _clean(t):
    t = FOOT_RE.sub("", t.strip()).strip()
    return "" if JUNK_RE.match(t) else t


def _is_num(t):
    if YEAR_RE.match(t):
        return False                       # '2020' 머리글(LG화학) — 값은 늘 쉼표가 있다
    return bool(NUM_RE.match(t)) or bool(DASH_RE.match(t))


def _num(t):
    s = t.replace(" ", "")
    if DASH_RE.match(s):
        return 0.0
    neg = ("(" in s and ")" in s) or s[:1] in "-−△▲"
    s = re.sub(r"[()+\-−△▲,]", "", s)
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _norm(name):
    """비교용 이름 — 빈칸 · 각주 · 끝 괄호설명을 뗀다."""
    s = FOOT_RE.sub("", name or "")
    s = re.sub(r"\s+", "", s)
    return s


# ---------------------------------------------------------------- 보고서 목록
def reports(code):
    """{(연도, 분기): [폴더, ...]} — 같은 기간이 여럿(정정)이면 접수번호가 늦은 것부터."""
    comp = glob.glob(os.path.join(DATA, "*_" + code))
    out = {}
    if not comp:
        return out
    for d in glob.glob(os.path.join(comp[0], "20*_*")):
        m = re.match(r"^(\d{4})-(\d{2})_(분기보고서|반기보고서|사업보고서)(?:\[정정\])?_(\d{14})$", os.path.basename(d))
        if not m or not os.path.isdir(d):
            continue
        y, mo, kind, rc = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        q = {3: 1, 6: 2, 9: 3, 12: 4}.get(mo)
        if q is None or (kind == "사업보고서") != (q == 4):
            continue
        out.setdefault((y, q), []).append((rc, d))
    return {k: [d for _, d in sorted(v, reverse=True)] for k, v in out.items()}


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().split("\n")
    except OSError:
        return []


def _file(d, pat):
    for fn in sorted(os.listdir(d)):
        if re.search(pat, re.sub(r"\s+", "", fn)):
            return os.path.join(d, fn)
    return None


def note_regions(d):
    """[(출처 이름, 줄들)] — 첨부 연결재무제표(사업보고서) 주석, 그다음 III 의 '연결재무제표 주석' 구간."""
    out = []
    att = _file(d, r"^\d+_\(첨부\)연결재무제표\.txt$")
    if att:
        L = _read(att)
        st = next((i for i, l in enumerate(L) if re.match(r"^\s*(?:\d+\s*\.\s*)?주\s*석\s*$", l)
                   or re.match(r"^\s*1\s*\.\s*(?:일반\s*사항|회사의\s*개요|일반적\s*사항)", l)), 0)
        out.append((os.path.basename(att), L[st:]))
    f3 = _file(d, r"재무에관한사항\.txt$")
    if f3:
        L = _read(f3)
        st = next((i for i, l in enumerate(L) if re.match(r"^\s*3\s*\.\s*연\s*결\s*재\s*무\s*제\s*표\s*주\s*석", l)), None)
        if st is not None:
            en = next((j for j in range(st + 1, len(L))
                       if re.match(r"^\s*4\s*\.\s*(?:별\s*도\s*)?재\s*무\s*제\s*표\s*$", L[j])), len(L))
            out.append((os.path.basename(f3), L[st:en]))
    return out


def biz_region(d):
    f2 = _file(d, r"^\d+_II\.사업의내용\.txt$")
    return [(os.path.basename(f2), _read(f2))] if f2 else []


# ---------------------------------------------------------------- 표 자르기
PERIOD_TOK = re.compile(r"^(?:\(?\s*\d\s*\)\s*|\d\)\s*|[①-⑩]\s*)?(?:\(|\[)?(?:누적\s*)?(?:당|전|전전)\s*(?:기|분기|반기|누적|\d\s*분기|년)"
                        r"|^(?:\d\)\s*)?제\s*\d+\s*(?:\((?:당|전)\))?\s*기|^(?:19|20)\d{2}\s*(?:년|\.|\s*[1-4]\s*분기|\s*반기|$)"
                        r"|^\(?(?:3\s*개월|누적)\)?$")


def raw_tables(lines, maxlen=200):
    """'(단위' 줄마다 표 하나. {ctx: 앞 글자, mul, toks: 칸들}"""
    units = [i for i, l in enumerate(lines) if UNIT_RE.search(l) and len(l) < maxlen]
    out = []
    for k, u in enumerate(units):
        en = min(units[k + 1] if k + 1 < len(units) else len(lines), u + 250)
        ctx_lines = [l.strip() for l in lines[max(0, u - 10):u] if l.strip()][-5:]
        head = lines[u][:UNIT_RE.search(lines[u]).start()].strip(" (")
        if head:
            ctx_lines.append(head)
        toks = []
        for l in lines[u + 1:en]:
            t = _clean(l)
            if not t or PCT_RE.match(t.replace(" ", "")):
                continue
            toks.append(t)
        out.append({"ctx": ctx_lines, "mul": UNIT_MUL[UNIT_RE.search(lines[u]).group(1)], "toks": toks, "at": u})
    return out


def split_rows(toks):
    """머리글 칸들과 행들 [(이름, [값])] — 글자 칸 뒤에 숫자 칸이 오면 한 행."""
    head, rows, started, i = [], [], False, 0
    while i < len(toks):
        t = toks[i]
        if _is_num(t):
            if not started:
                head.append(t)
            i += 1
            continue
        j, vals = i + 1, []
        while j < len(toks) and _is_num(toks[j]):
            vals.append(_num(toks[j]))
            j += 1
        if vals:
            name = t
            if re.match(r"^\(.{1,8}\)$", t):
                # '연결조정 후 영업이익' '(A+B)' 처럼 이름 끝 괄호가 다음 줄로 넘어온 경우 — 앞 글자 칸과 붙인다
                prev = (rows[-1][0] if rows and not rows[-1][1] else None) if started else (head[-1] if head else None)
                if prev:
                    name = prev + t
            rows.append((name, vals))
            started = True
            i = j
            continue
        if not started:
            head.append(t)
        else:
            rows.append((t, []))           # 값 없는 글자 칸(설명 · 소제목) — 자리만 남긴다
        i += 1
    return head, rows


# ---------------------------------------------------------------- 행 종류
ROW_KIND = [
    ("ext", r"^(?:외부매출액?|외부고객으로부터의수익|순매출액?|외부고객매출액?|외부고객수익|외부수익)$"),
    ("int", r"^(?:내부매출액?|부문간(?:내부)?(?:매출액?|수익)|내부거래(?:매출)?|부문간내부매출|내부수익)$"),
    ("gross", r"^(?:총매출액?|매출액|매출|영업수익|총부문수익|부문(?:별)?수익|수익\(매출액\)|수익|총수익|합계)$"),
    ("op", r"^(?:영업이익|영업손익|영업이익\(손실\)|영업손실|보고부문영업이익(?:\(손실\))?|부문(?:별)?영업(?:이익|손익)(?:\(손실\))?|"
           r"계속영업이익(?:\(손실\))?|영업이익\(A\)|부문영업이익)$"),
    ("op_seg", r"^(?:부문이익|부문손익|부문이익\(손실\))$"),
    # 부문 세전이익 — 부문 영업이익을 내지 않는 회사(풍산)만 영업이익 자리에 쓴다(CO op_pti)
    ("pti", r"^법인세비용차감전(?:계속영업)?순(?:이익|손익)(?:\(손실\))?$"),
    # 부문 순손익 — SKC 2023 ~ 은 이것뿐이다. 영업이익으로 쓰지 않고 부문 'ni' 로만 남긴다
    ("ni", r"^(?:당기|분기|반기)?순(?:이익|손익)(?:\(손실\))?$|^계속사업(?:당기|분기|반기)?순(?:이익|손익)(?:\(손실\))?$"),
    # 매출 밖의 영업수익 — IRA 첨단제조 생산세액공제(AMPC) 등. 원장 매출 줄에 들어가는 해가 있다(LG화학 2026 '매출 및 기타수익')
    ("oth", r"^(?:정부보조금으로부터의수익|기타영업수익)$"),
]


def row_kind(name):
    n = _norm(name)
    n = re.sub(r"^\d+\.|^[가-하]\.|^\([가-하]\)", "", n)        # '1.' '가.' '(가)'(현대글로비스 '(가) 매출액')
    for k, rx in ROW_KIND:
        if re.match(rx, n):
            return k
    return None


METRIC_RE = re.compile(r"매출|수익|이익|손익|상각|자산|부채|순이익")      # '상각비'(KT) — 칸 자리를 세려고


# ---------------------------------------------------------------- 표 해석
def _seg_names(head, cfg):
    rx = re.compile(cfg["seg"])
    out = []
    for t in head:
        n = _norm(t)
        if rx.match(n) and n not in [_norm(x) for x in out]:
            out.append(t.strip())
    return out


def _order(segs, cfg):
    """기타는 끝으로, 하위 칸은 부모 자리로. [(이름, 부모합계칸인가)]"""
    named = [s for s in segs if not ETC_RE.match(_norm(s))]
    etc = [s for s in segs if ETC_RE.match(_norm(s))]
    order = [(s, False) for s in named + etc]
    for prx, crx, keep_parent in cfg.get("kids", []):
        par = [i for i, (s, _) in enumerate(order) if re.match(prx, _norm(s))]
        kids = [s for s, _ in order if re.match(crx, _norm(s))]
        if not par or not kids:
            continue
        rest = [x for x in order if x[0] not in kids]
        pi = next(i for i, (s, _) in enumerate(rest) if re.match(prx, _norm(s)))
        ins = ([(rest[pi][0], True)] if keep_parent else []) + [(k, False) for k in kids]
        order = rest[:pi] + ins + rest[pi + 1:]
    return order


def _positional(head, n, cfg):
    """머리글 칸 수가 숫자 칸 수와 같으면 자리로 맞춘다. [(이름, 역할)] 역할 = seg · total · elim · sub"""
    rx = re.compile(cfg["seg"])
    i0 = max((i for i, t in enumerate(head) if re.match(r"^(?:구분|구분\(.*\)|사업부문|부문)$", _norm(t))), default=-1)
    cols = []
    for t in head[i0 + 1:]:
        n_ = _norm(t)
        if PERIOD_TOK.match(t.strip()) or re.match(r"^(?:부문별(?:수익|자산|부채|손익)|3개월|누적|금액|비중)$", n_):
            continue
        cols.append(t)
    if len(cols) != n:
        return None
    out = []
    for t in cols:
        n_ = _norm(t)
        if rx.match(n_):
            out.append((t.strip(), "seg"))
        elif re.search(r"연결조정|내부거래|조정|제거", n_):
            out.append((t, "elim"))
        elif re.match(r"^(?:합계|계|총계|연결후금액|조정후금액|연결재무제표|연결계|연결)$", n_):
            out.append((t, "total"))
        elif re.match(r"^(?:소계|부문합계|부문계)$", n_):
            out.append((t, "sub"))
        else:
            return None                    # 모르는 칸 — 자리 맞추기를 포기
    if sum(1 for _, r in out if r == "seg") < 2:
        return None
    if out[0][1] in ("sub", "total"):
        return None                        # XBRL 축 이름 '부문 합계'가 부문 이름들 앞에 온다(값은 부문 다음 합계 — LG생활건강 2024)
    return out


def interpret(raw, cfg):
    """표 하나 → 해석 목록. 3개월 · 누적 짝 칸 표는 둘을 낸다.
    {segs: [이름], parent: {이름: 자식들}, rows: {종류: {'seg': {이름: 값}, 'total': x, 'elim': y}}, span: '3m'|'cum'|None}"""
    head, rows = split_rows(raw["toks"])
    rx = re.compile(cfg["seg"])
    data_rows = [(nm, v) for nm, v in rows if v]
    if not data_rows:
        return []
    seg_rows = [nm for nm, v in data_rows if rx.match(_norm(nm))]
    head_segs = _seg_names(head, cfg)
    mul = raw["mul"]
    res = []
    # (가) 부문이 행인 표(HD현대 · POSCO II 요약) — 머리글이 지표 이름
    metrics = [t for t in head if METRIC_RE.search(_norm(t)) and len(_norm(t)) <= 20]
    htxt = [_norm(t) for t in head]
    if len(seg_rows) >= 2 and len(head_segs) < 2 and metrics:
        # POSCO II 요약: 자산 · 매출 · 영업이익 이 기간마다 되풀이 — 첫 묶음이 당기
        # KT · 현대로템 분기: 지표마다 '3개월 · 누적' 두 칸 — 지표 j 의 값은 v[2j + sub]
        rpair = htxt.count("3개월") >= 2 and htxt.count("누적") >= 2
        f3 = rpair and htxt.index("3개월") < htxt.index("누적")
        subs = [("3m", 0 if f3 else 1), ("cum", 1 if f3 else 0)] if rpair else [(None, 0)]
        # KT · 현대로템: 한 '(단위' 아래 당기 표 뒤에 전기 표가 같은 모양으로 이어진다 — 합계 줄마다 끊어 둘째 묶음을 전기로
        groups = _row_blocks(data_rows, rx) if cfg.get("row_blocks") else [data_rows]
        for gi, grp in enumerate(groups[:2]):
            for span, sub in subs:
                for r in _rows_layout(grp, metrics, rx, mul, head, span, 2 if rpair else 1, sub):
                    if len(groups) > 1:
                        r["cp"] = "cur" if gi == 0 else "prev"
                    res.append(r)
        return res
    if len(head_segs) < 2:
        return []
    return _cols_layout(head, htxt, data_rows, head_segs, rx, mul, cfg)


def _row_blocks(data_rows, rx):
    """합계 줄에서 끊은 묶음들 — 부문 줄이 둘 이상인 묶음만"""
    out, cur = [], []
    for nm, v in data_rows:
        cur.append((nm, v))
        n_ = _norm(nm)
        if re.search(r"^(?:합계|계|총계)|합계$|총계합계$", n_) and not re.match(r"^(?:소계|부문합계|부문계)$", n_):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [b for b in out if sum(1 for nm, _v in b if rx.match(_norm(nm))) >= 2] or [data_rows]


def _rows_layout(data_rows, metrics, rx, mul, head, span, w, sub):
    """부문이 행인 표 — 머리글이 지표 이름. w = 지표마다 칸 수(3개월 · 누적이면 2), sub = 그 안의 자리"""
    rec = {"segs": [], "rows": {}, "span": span, "parent": {}, "head": head}
    ssum = 0.0
    for nm, v in data_rows:
        n_ = _norm(nm)
        if rx.match(n_):
            role = "seg"
        elif re.match(r"^(?:소계|부문합계|부문계)$", n_):
            # 부문 합계 줄 — 부문 합과 같으면 소계(건너뜀), 아니면 그 뒤 '부문간 제거한 금액' 묶음의 값(KT 2026 XBRL)
            x = v[sub] if len(v) > sub else None
            if x is None or (ssum and abs(x - ssum) <= 0.005 * abs(ssum)):
                continue
            role = "elim"
        elif re.search(r"연결조정|내부거래|조정|제거", n_):
            role = "elim"
        elif re.search(r"^(?:합계|계|총계)|합계$|총계합계$", n_):
            role = "total"
        else:
            continue
        if role == "seg" and len(v) > sub and v[sub] is not None and nm.strip() not in rec["segs"]:
            ssum += v[sub]
        if role == "seg" and nm.strip() in rec["segs"]:
            continue                           # 같은 부문이 또 나오면(뒤쪽 다른 표) 앞의 것을 쓴다
        if role == "seg":
            rec["segs"].append(nm.strip())
        seen = set()
        for j, mname in enumerate(metrics):
            jj = w * j + sub
            if jj >= len(v):
                break
            k = row_kind(mname) or ("op" if re.search(r"영업(?:이익|손익)", _norm(mname)) else None)
            if k is None or k in seen:
                continue
            if _norm(mname) == "매출":
                k = "gross"
            seen.add(k)
            slot = rec["rows"].setdefault(k, {"seg": {}, "total": None, "elim": None, "label": mname})
            val = v[jj] * mul if v[jj] is not None else None
            if role == "seg":
                slot["seg"][nm.strip()] = val
            elif slot.get(role) is None:
                slot[role] = val
        if role == "total":
            break                              # 합계 행이 표의 끝
    if rec["rows"]:
        rec["layout"] = "rows"
        return [rec]
    return []


CP_TOK = {"당기": "cur", "전기": "prev", "당분기": "cur", "전분기": "prev", "당반기": "cur", "전반기": "prev"}


def _cols_layout(head, htxt, data_rows, head_segs, rx, mul, cfg):
    """(나) 부문이 칸인 표. 칸 묶음: '3개월 · 누적' 짝(span), 부문마다 '당기 · 전기' 짝(풍산 — cp),
    '총 · 제거 · 순' 세 칸(SK 영업부문 · 부문간 제거, 삼성물산 XBRL 매출액 · 내부거래 · 순매출액)."""
    res = []
    pair = "3개월" in htxt and "누적" in htxt
    first3 = pair and htxt.index("3개월") < htxt.index("누적")
    cps = [CP_TOK[t] for t in htxt if t in CP_TOK]
    cp_pair = not pair and len(cps) >= 4 and cps.count("cur") == cps.count("prev") and cps[0] != cps[1]
    triple = (sum(1 for t in htxt if t in ("부문간제거한금액", "내부매출액")) >= 2 and
              sum(1 for t in htxt if t in ("영업부문",)) >= 2) or \
        ((htxt.count("내부거래") >= 2 or htxt.count("내부매출액") >= 2) and
         max(htxt.count("매출액"), htxt.count("외부매출액"), htxt.count("총매출액")) >= 2)   # 삼성물산 2023 ~ XBRL
    order = _order(head_segs, cfg)
    L = len(order)
    # 기간 묶음(한화 II '제47기 … 제46기 …'): 부문 이름이 머리글에 두 번 넘게 되풀이되고 기수 머리글이 둘 이상
    reps = sum(1 for t in head if rx.match(_norm(t)))
    periods = [t for t in head if re.match(r"^제\s*\d+\s*기", t.strip())]
    blocks = len(periods) if len(periods) >= 2 and reps >= 2 * len(head_segs) else 1
    dup2 = bool(cfg.get("dup_cols")) and blocks == 1 and not pair and not cp_pair and not triple and \
        reps == 2 * len(head_segs)

    if pair:
        spans = [("3m", 0 if first3 else 1, None), ("cum", 1 if first3 else 0, None)]
    elif cp_pair:
        spans = [(None, 0, cps[0]), (None, 1, cps[1])]
    else:
        spans = [(None, 0, None)]
    for span, sub, cp in spans:
        rec = {"segs": [], "rows": {}, "span": span, "parent": {}, "layout": "cols", "head": head}
        if cp:
            rec["cp"] = cp                     # 칸이 당기 · 전기를 정한다
        for nm, v in data_rows:
            k = (cfg.get("row_kind") or {}).get(_norm(nm)) or row_kind(nm)     # 회사별 줄 이름 뜻(삼성물산 '외부매출액' = 총매출)
            if k is None:
                continue
            if blocks > 1 and len(v) % blocks == 0:
                v = v[:len(v) // blocks]
            pos = _positional(head, len(v), cfg) if not pair and not triple and not cp_pair else None
            vals, rest = None, []
            if pos:
                vals = [x for x, (c, r) in zip(v, pos) if r == "seg"]
                names = [c for c, r in pos if r == "seg"]
                tot = [x for x, (c, r) in zip(v, pos) if r == "total"]
                eli = [x for x, (c, r) in zip(v, pos) if r == "elim"]
                seg_map = dict(zip(names, vals))
                total = tot[-1] if tot else None
                elim = eli[-1] if eli else None
                if not rec["segs"]:
                    rec["segs"] = names
            else:
                m = 2 if (pair or cp_pair) else (3 if triple else 1)
                if len(v) < L * m:
                    m = 1
                if len(v) < L:
                    continue
                order_r = order
                if dup2 and k in ("ext", "gross") and len(v) in (2 * L + 1, 2 * L + 3):
                    # XBRL: 머리글에 부문 이름이 두 번(총매출 묶음 · 부문간 제거 묶음) — 순액 = 앞 + 뒤, 끝 칸 = 연결 합계.
                    # 삼성물산 2026 은 [총 L, 제거 L, 합계], 풍산 2024 는 [총 L, 소계, 제거 L, 소계, 합계]
                    off = L if len(v) == 2 * L + 1 else L + 1
                    seg_map = {s: (v[i] or 0) + (v[off + i] or 0) for i, (s, _p) in enumerate(order_r)}
                    total, elim = v[-1], None
                    k = "ext"
                else:
                    if m == 1 and cfg.get("gone"):
                        # XBRL 표는 빈 칸이 사라진다 — 없어진 부문(한화 리테일, 2023 인적분할) 칸이 비면 값이 한 칸씩 당겨진다.
                        # 앞 k 칸의 합 = 다음 칸(부문 합계)인 k 가 부문 수보다 하나 작으면 그 부문을 뺀다.
                        kk = next((j for j in range(2, L) if j < len(v) and v[j] and
                                   abs(sum(x or 0 for x in v[:j]) - v[j]) <= max(2.0, abs(v[j]) * 1e-6)), None)
                        gone = [x for x in order if re.match(cfg["gone"], _norm(x[0]))]
                        if kk == L - 1 and len(gone) == 1:
                            order_r = [x for x in order if x is not gone[0]]
                    seg_map = {}
                    for i, (s, _par) in enumerate(order_r):
                        if m == 2:
                            seg_map[s] = v[2 * i + sub]
                        elif m == 3:
                            seg_map[s] = v[3 * i + 2]           # 순액(외부)
                            if k == "gross":
                                seg_map[s] = v[3 * i]
                        else:
                            seg_map[s] = v[i]
                    rest = v[len(order_r) * m:]
                    if m == 2:
                        rest = rest[sub::2] if len(rest) % 2 == 0 else rest
                    if m == 3 and k in ("gross", "ext"):
                        # 연결조정 묶음(총 · 제거 · 순) — 순액 줄이면 total = 부문 순액 합 + 조정 순액
                        total, elim = None, (rest[2] if len(rest) >= 3 else None)
                        nsum = sum(v[3 * i + 2] or 0 for i, (s, _p) in enumerate(order_r) if not _p)
                        last = rest[2] if len(rest) >= 3 else (rest[0] if len(rest) == 1 else None)
                        if last is not None and nsum and abs(last - nsum) <= 0.005 * abs(nsum):
                            total, elim = last, None            # 남는 칸이 연결조정이 아니라 합계(삼성물산 XBRL)
                        if k == "gross":
                            k = "ext"                           # 세 칸 묶음의 셋째 칸이 외부(순) 매출
                            seg_map = {s: v[3 * i + 2] for i, (s, _p) in enumerate(order_r)}
                            gross = {s: v[3 * i] for i, (s, _p) in enumerate(order_r)}
                            rec["rows"].setdefault("gross", {"seg": {s: x * mul for s, x in gross.items()},
                                                             "total": None, "elim": None, "label": nm})
                    elif len(rest) == 1:
                        # 남는 칸 하나 — 합계(삼성 '계')인가 연결조정(SK 세 칸 표의 영업이익 줄)인가. 부문 합과 가까우면 합계
                        ssum = sum(x for (s_, par), x in zip(order_r, seg_map.values()) if x is not None and not par)
                        x = rest[0]
                        if ssum and x and (x > 0) == (ssum > 0) and abs(x - ssum) <= 0.2 * abs(ssum):
                            total, elim = x, None
                        else:
                            total, elim = None, x
                    else:
                        total = rest[-1] if rest else None
                        elim = rest[-2] if len(rest) >= 2 else None
                if not rec["segs"]:
                    rec["segs"] = [s for s, _p in order_r]
                    rec["parent"] = {s: True for s, p in order_r if p}
            if k in rec["rows"]:
                continue
            if pos:
                rec["pos"] = True                  # 머리글 칸 수 = 숫자 칸 수 (옛 서식 — 칸 밀림 없음)
            rec["rows"][k] = {"seg": {s: (x * mul if x is not None else None) for s, x in seg_map.items()},
                              "total": total * mul if total is not None else None,
                              "elim": elim * mul if elim is not None else None, "label": nm}
        g = rec["rows"].get("gross")
        if g and _norm(g["label"]) == "합계" and not any(x in rec["rows"] for x in ("ext", "int")):
            continue                               # '합 계' 줄뿐인 표(부문별 자산 · 부채)는 매출표가 아니다
        if rec["rows"]:
            res.append(rec)
    return res


# ---------------------------------------------------------------- 기간 가르기
def period_hint(raw, Y, q):
    """(당기인가, 기간 길이) — 글자만 보고. None = 모름.
    표 바로 앞의 짧은 머리('(당분기)' '2) 제 47(전) 기 1분기' '전반기')를 먼저 본다 — 그 앞 문장('당분기 및 전분기 중 …')은 둘 다 적는다."""
    head, _ = split_rows(raw["toks"])
    cands = [t for t in head if PERIOD_TOK.match(t.strip())][:2] + \
        [l for l in reversed(raw["ctx"]) if len(l) <= 40]
    lab = None
    for c in cands:
        t = re.sub(r"\s+", "", c)
        if re.search(r"\((?:당|전)\)|(?:당|전)(?:기|분기|반기|누적|[1-4]분기|년)|(?<!\d)20\d{2}", t):
            lab = t
            ys = [int(x) for x in re.findall(r"(?<!\d)(20\d{2})(?!\d)", re.sub(r"\s+", " ", c))]   # '2021 1분기'
            break
    is_cur, span = None, None
    if lab:
        if re.search(r"\(당\)|당(?:기|분기|반기|누적|[1-4]분기)", lab) or Y in ys:
            is_cur = True
        elif re.search(r"\(전\)|전(?:기|분기|반기|누적|[1-4]분기|년)|전전기", lab) or (Y - 1) in ys:
            is_cur = False
    if q == 1:
        span = "cum"
    elif q == 4:
        span = "cum"
    elif re.search(r"3개월|\(3개월\)|[당전][23]분기(?!누적)", lab or "") and "누적" not in (lab or ""):
        span = "3m"
    elif re.search(r"누적|반기", lab or "") or re.search(r"제\d+.*기.*[1-4]분기|[1-4]분기\(당기\)", lab or ""):
        span = "cum"                       # POSCO '제 52(당) 기 3분기' · '제56기 3분기(당기)' = 누적
    return is_cur, span


def _close(a, b, tol):
    return a is not None and b is not None and b != 0 and abs(a - b) / abs(b) <= tol


def _revrow(rec):
    """매출로 쓸 줄 — 외부매출 줄, 없으면 총매출 − 내부매출, 없으면 총매출. (줄, 'ext'|'gross')"""
    rows = rec["rows"]
    if rows.get("ext"):
        return rows["ext"], "ext"
    g, i = rows.get("gross"), rows.get("int")
    if g and rec.get("gross_is_ext"):
        return g, "ext"                    # '매출액' 줄이 이미 외부매출(현대차 2021 ~ 2022 — 내부매출액은 따로 적은 참고 줄)
    if g and i and any(v for v in i["seg"].values()):
        segv ={s: (x - abs(i["seg"][s]) if x is not None and i["seg"].get(s) is not None else x) for s, x in g["seg"].items()}
        tot = g.get("total")
        if tot is not None and i.get("total") is not None:
            tot = tot - abs(i["total"])
        return {"seg": segv, "total": tot, "elim": None, "label": "%s−%s" % (g["label"], i["label"])}, "ext"
    if g:
        return g, "gross"
    return None, None


def rev_total(rec):
    """표가 말하는 연결 매출 — 합계 칸(없으면 None)"""
    r, _ = _revrow(rec)
    return r.get("total") if r else None


def rev_sum(rec, adj=False):
    """매출 줄의 부문 합(하위 칸이 있는 부모 합계는 뺀다). adj=True 면 표의 조정 칸까지 더한다."""
    r, _ = _revrow(rec)
    if not r:
        return None
    vals = [x for s, x in r["seg"].items() if x is not None and not rec["parent"].get(s)]
    if not vals:
        return None
    return sum(vals) + ((r.get("elim") or 0) if adj else 0)


# ---------------------------------------------------------------- 원장(검산)
REV_IDS = ("ifrs-full_Revenue", "ifrs_Revenue")
OP_IDS = ("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities")
REV_NM = re.compile(r"^(?:매출액|매출|수익\(매출액\)|영업수익|매출및지분법손익)$")
OP_NM = re.compile(r"^영업(?:이익|손익|손실)(?:\(손실\))?$")


def _f(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "", "-") else None
    except ValueError:
        return None


def _ledger_one(corp, y, reprt):
    """원장 한 보고서 → (매출 3개월, 매출 누적, 영업이익 3개월, 영업이익 누적). 없으면 None"""
    p = os.path.join(FIN_DIR, "%s_%s_%s_CFS.json" % (corp, y, reprt))
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    rows = d.get("list") or []
    if not rows:
        return None
    has_is = any(r.get("sj_div") == "IS" for r in rows)
    rev = op = None
    for r in rows:
        if r.get("sj_div") not in ("IS", "CIS") or (r.get("sj_div") == "CIS" and has_is):
            continue
        aid = r.get("account_id") or ""
        nm = re.sub(r"\s+|^[IVX]+\.|^\d+\.", "", r.get("account_nm") or "")
        pair = (_f(r.get("thstrm_amount")), _f(r.get("thstrm_add_amount")))
        if rev is None and (aid in REV_IDS or REV_NM.match(nm)):
            rev = pair
            rev_nm = (r.get("account_nm") or "").strip()
        elif op is None and (aid in OP_IDS or OP_NM.match(nm)):
            op = pair
    if rev is None:
        return None
    rc = rev[1] if rev[1] is not None else rev[0]
    oc = (op[1] if op[1] is not None else op[0]) if op else None
    return {"rev3": rev[0], "revc": rc, "op3": op[0] if op else None, "opc": oc, "src": "원장", "rev_nm": rev_nm}


def _body_one(code, y, q):
    """원장이 없으면 보고서 본문 손익계산서 — 본문재무.py 의 표 읽기만 쓴다(캐시 안 씀)."""
    B = _body_mod()
    corp = CO[code]["corp"]
    reprt = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}[q]
    try:
        dirs = B.report_dirs(corp, y, reprt)
    except Exception:
        return None
    for d in dirs:
        try:
            sec = B._statement_lines(d, "CFS")
        except Exception:
            sec = None
        if not sec:
            continue
        for kind, ls in B._blocks(sec):
            if kind not in ("IS", "CIS"):
                continue
            t = B._parse_table(ls)
            if not t or not t["rows"] or not B._check(kind, t["rows"]):
                continue
            rev = op = None
            for r in t["rows"]:
                b = re.sub(r"\(.*?\)", "", B._bare(r["name"]))
                if rev is None and B.REVENUE_NAME.search(B._bare(r["name"])):
                    rev = r["vals"]
                elif op is None and re.match(r"^영업(?:이익|손익|손실)", b):
                    op = r["vals"]
            if rev is None:
                continue
            c3, cc = (1, 0) if t["cum_first"] else (0, 1)
            if q != 4 and t["has_3m"]:
                g = lambda v, i: v[i] if v and len(v) > i else None   # noqa: E731
                return {"rev3": g(rev, c3), "revc": g(rev, cc), "op3": g(op, c3), "opc": g(op, cc),
                        "src": "본문 " + os.path.basename(d)}
            v0 = rev[0] if rev else None
            o0 = op[0] if op else None
            if q in (1, 4):
                return {"rev3": v0, "revc": v0, "op3": o0, "opc": o0, "src": "본문 " + os.path.basename(d)}
            return {"rev3": None, "revc": v0, "op3": None, "opc": o0, "src": "본문 " + os.path.basename(d)}
    return None


def ledger(code):
    """{(Y, q): {rev3, revc, op3, opc, src}} — 4분기 3개월 = 연간 − 3분기 누적."""
    corp = CO[code]["corp"]
    out = {}
    for y in range(YEARS[0] - 1, YEARS[-1] + 1):        # 2014 — 2015 보고서의 전년 비교 숫자를 가르는 데 쓴다
        for q, reprt in ((1, "11013"), (2, "11012"), (3, "11014"), (4, "11011")):
            d = _ledger_one(corp, y, reprt)
            if d is None:
                d = _body_one(code, y, q)
            if d:
                out[(y, q)] = d
    for (y, q), d in out.items():
        if q == 1:
            d["rev3"] = d["rev3"] if d["rev3"] is not None else d["revc"]
            d["op3"] = d["op3"] if d["op3"] is not None else d["opc"]
            d["revc"] = d["revc"] if d["revc"] is not None else d["rev3"]
            d["opc"] = d["opc"] if d["opc"] is not None else d["op3"]
        if q == 4:
            p = out.get((y, 3))
            d["rev3"] = d["revc"] - p["revc"] if p and None not in (d["revc"], p.get("revc")) else None
            d["op3"] = d["opc"] - p["opc"] if p and None not in (d["opc"], p.get("opc")) else None
        elif q in (2, 3) and (d.get("rev3") is None or d.get("op3") is None):
            p = out.get((y, q - 1))
            if p:
                if d.get("rev3") is None and None not in (d.get("revc"), p.get("revc")):
                    d["rev3"] = d["revc"] - p["revc"]
                if d.get("op3") is None and None not in (d.get("opc"), p.get("opc")):
                    d["op3"] = d["opc"] - p["opc"]
    return out


# ---------------------------------------------------------------- 한 보고서 → 당기 부문표
def _cands(code, d, Y, q, which):
    cfg = CO[code]
    regs = note_regions(d) if which == "note" else biz_region(d)
    out = []
    for fname, lines in regs:
        for raw in raw_tables(lines, cfg.get("unit_line_max", 200)):
            for rec in interpret(raw, cfg):
                if not any(k in rec["rows"] for k in ("ext", "gross")) or len(rec["segs"] or []) < 2:
                    continue                       # 부문 둘 미만(종속회사 요약 재무 표 등)은 부문표가 아니다
                rec["src"] = "%s %s" % (os.path.basename(d).rsplit("_", 1)[-1], fname)
                rec["hint"] = period_hint(raw, Y, q)      # rec['span'] 은 '3개월 · 누적' 짝 칸 표만 미리 정해져 있다
                if rec.get("cp"):                          # '당기 · 전기' 짝 칸 표(풍산)는 칸이 당기 · 전기를 정한다
                    rec["hint"] = (rec["cp"] == "cur", rec["hint"][1])
                out.append(rec)
        if out and which == "note":
            break                          # 첨부 주석에서 읽었으면 III 는 안 본다
    return out


def _segkey(rec):
    return tuple(sorted(_canon(s) for s in rec["segs"] if not rec["parent"].get(s)))


def classify(cands, Y, q, L, prev_span=False):
    """후보 표들 → {('cur'|'prev', '3m'|'cum'): rec}.
    원장 연결 매출(당기 · 전년 같은 기간, 3개월 · 누적)과 가장 가까운 자리를 찾아 1.5% 안이면 그 자리로 본다.
    표 앞 글자(당기 · 전기)와 다르면 글자 쪽 자리가 3% 안일 때 글자를 따른다(매출이 전년과 비슷한 해 — LG화학 2026 1분기).
    원장과 안 맞는 표는 글자로만 자리를 정한다. 같은 자리 후보가 여럿이면 원장과 맞는 표 · 외부매출 줄 · 영업이익 줄이 있는 표를
    고르고, 고른 표에 영업이익 줄이 없으면 같은 부문 구성의 다른 표에서 빌려 온다.
    prev_span=True(2026-10 추가 회사): 원장과 안 맞고 기간 길이 글자도 없는 표(재작성으로 원장과 다른 SKC 2024 3분기의
    2023 비교 숫자 등)는 머리글이 같은 당기 표가 맞은 길이(누적 · 3개월)를 따른다."""
    lgs = {"cur": L.get((Y, q)) or {}, "prev": L.get((Y - 1, q)) or {}}
    slots = {}
    cur_span, defer = {}, []
    led = [lgs[w].get(kk) for w in ("cur", "prev") for kk in ("revc", "rev3") if lgs[w].get(kk)]
    for rec in cands:
        rw = rec["rows"]
        if "ext" not in rw and rw.get("gross") and rw.get("int") and not rec.get("gross_is_ext"):
            # '매출액' + '내부매출액' 표 — 매출액이 총매출(내부 포함)인지 외부매출인지는 원장으로 가린다:
            # 매출액 부문 합(또는 합계 칸)만 원장 매출과 0.5% 안이고 '매출액 − 내부매출액'은 안 맞으면 매출액 = 외부매출
            g = rw["gross"]
            gs = [x for s_, x in g["seg"].items() if x is not None and not rec["parent"].get(s_)]
            cand = ([sum(gs)] if gs else []) + ([g["total"]] if g.get("total") is not None else [])
            net = [x for x in (rev_total(rec), rev_sum(rec), rev_sum(rec, adj=True)) if x is not None]
            if any(_close(c, v, 0.005) for c in cand for v in led) and \
                    not any(_close(x, v, 0.005) for x in net for v in led):
                rec["gross_is_ext"] = True
        T, S, SA = rev_total(rec), rev_sum(rec), rev_sum(rec, adj=True)
        is_cur, span = rec["hint"]
        dist = {}
        for w in ("cur", "prev"):
            for s_, key in (("cum", "revc"), ("3m", "rev3")):
                v = lgs[w].get(key)
                if not v or (rec["span"] and rec["span"] != s_ and q != 1):
                    continue                       # '3개월 · 누적' 짝 칸 표는 칸이 기간을 정한다
                ds = [abs(x - v) / abs(v) for x in (S, T, SA) if x is not None]
                if ds:
                    dist[(w, s_)] = (min(ds), _close(S, v, 0.015))    # (거리, 부문 합 자체가 연결 매출 = 외부매출)
        best = min(dist.items(), key=lambda kv: kv[1][0]) if dist else None
        who = sp = None
        ext_ok = False
        if best and best[1][0] <= 0.015:
            (who, sp), (dd, ext_ok) = best
            if is_cur is not None and (who == "cur") != is_cur:
                alt = [(k, v) for k, v in dist.items() if (k[0] == "cur") == is_cur and v[0] <= 0.03]
                if alt:
                    (who, sp), (dd, ext_ok) = min(alt, key=lambda kv: kv[1][0])
                elif dd > 0.002:
                    who = sp = None                # 글자와 어긋나고 딱 맞지도 않는다 — 우연히 비슷한 숫자(삼성 2014 3분기 순매출액 합)
        matched = who is not None
        if not matched:
            if is_cur is None:
                continue
            who = "cur" if is_cur else "prev"
            sp = rec["span"] or span or ("cum" if q in (1, 4) else None)
            if sp is None:
                if prev_span:
                    defer.append((who, rec))
                continue
            dd = 0.0
        elif who == "cur":
            cur_span[tuple(rec["head"])] = sp
        rec["ext_ok"] = ext_ok
        rec["matched"] = matched
        score = (4 - 100 * dd if matched else 0) + (2 if ext_ok else 0) +             (1 if "ext" in rec["rows"] or "int" in rec["rows"] else 0) +             (1 if ("op" in rec["rows"] or "op_seg" in rec["rows"]) else 0) + (0.5 if rec.get("pos") else 0)
        spans = ("3m", "cum") if q == 1 else (sp,)
        for s_ in spans:
            slots.setdefault((who, s_), []).append((score, rec))
    one = set(cur_span.values())
    for who, rec in defer:
        # 머리글이 같은 당기 표의 길이, 없으면 이 보고서에서 맞은 당기 길이가 하나뿐일 때 그것(SKC: 순손익 줄이 있는 총매출액 표)
        sp = cur_span.get(tuple(rec["head"])) or (next(iter(one)) if len(one) == 1 else None)
        if sp:
            rec["ext_ok"], rec["matched"] = False, False
            slots.setdefault((who, sp), []).append((0, rec))
    out = {}
    for k, lst in slots.items():
        lst.sort(key=lambda x: -x[0])
        best = dict(lst[0][1])
        best["rows"] = dict(best["rows"])
        if "op" not in best["rows"] and "op_seg" not in best["rows"]:
            for _sc, other in lst[1:]:
                if _segkey(other) == _segkey(best) and ("op" in other["rows"] or "op_seg" in other["rows"]):
                    for kk in ("op", "op_seg"):
                        if kk in other["rows"]:
                            best["rows"][kk] = other["rows"][kk]
                    best["src"] += " (영업이익: 같은 주석의 다른 표)"
                    break
        if "ni" not in best["rows"]:
            # 부문 순손익 줄(SKC 2024 ~ — keep_ni 회사만 쓴다)도 같은 부문 구성의 다른 표(총매출액 표)에서 빌려 온다
            for _sc, other in lst[1:]:
                if _segkey(other) == _segkey(best) and "ni" in other["rows"]:
                    best["rows"]["ni"] = other["rows"]["ni"]
                    break
        out[k] = best
    return out


def pick(code, Y, q, L, which):
    """그 기간 보고서(정정본 포함 전부)의 표 {('cur'|'prev', span): rec}. 정정본이 XBRL 서식으로 칸이 밀린 경우가 있어
    (한화솔루션 2023 사업보고서 정정) 원본까지 같이 후보로 놓고 점수로 고른다."""
    dirs = reports(code).get((Y, q), [])
    cands = []
    for d in dirs:
        cands += _cands(code, d, Y, q, which)
    got = classify(cands, Y, q, L, prev_span=bool(CO[code].get("prev_span_from_cur")))
    if any(k[0] == "cur" for k in got):
        return got, dirs[0]
    return {}, None


# ---------------------------------------------------------------- 부문 레코드
def _sector(code, name, year):
    for rx, sec, since, until in SEC.SEGMENTS.get(code, []):
        if (since is None or year >= since) and (until is None or year <= until) and re.search(rx, name or ""):
            return sec
    return "skip"


ALIAS = {"이엔에스": "E&S", "이앤에스": "E&S", "E&P": "석유개발", "자원개발": "석유개발",
         "에너지/화학": "에너지및화학", "배터리/소재": "배터리및소재", "E&C": "건설",
         "에너지소재": "이차전지소재", "친환경미래소재": "이차전지소재", "Haman": "Harman",
         "자동차": "차량",                     # 현대차 2022 ~ 2023 주석은 '자동차' 부문
         # 삼성물산 2015: 합병(9-1) 전 제일모직 이름 → 합병 뒤 이름. 건설2 = 구 제일모직 건설(건설1 = 구 삼성물산 건설, 9월부터)
         "레져": "리조트", "급식/식자재유통": "식음", "건설2": "건설",
         "공통": "기타",                       # 풍산 사업보고서 '공통부문' = 분기보고서 '기타부문'(같은 칸)
         # 현대로템: 중기(~ 2016) = 방산, 2026 반기부터 AD&RH(방산) · RS(레일) · EP(에코플랜트)
         "중기": "방산", "AD&RH": "방산", "RS": "철도", "EP": "플랜트", "디펜스솔루션": "방산", "레일솔루션": "철도",
         "에코플랜트": "플랜트"}
# POSCO 친환경미래소재(2022 ~ 2024 1분기) → 이차전지소재(2024 반기 ~), 2025 1분기 보고서만 '에너지소재'


def _canon(name):
    """기간을 빼고 더할 때 쓰는 이름 키 — '석유사업' = '석유', 'CE 부문' = 'CE', '기 타' = '기타', '이엔에스' = 'E&S'"""
    n = _norm(name)
    n = re.sub(r"^(?:친환경)?인프라(?:부문)?\((.+?)(?:부문)?\)$", r"\1", n)   # POSCO II '인프라(무역부문)' = 주석 '무역'
    n = re.sub(r"(?:사업|부문)$", "", n)
    n = re.sub(r"^\(|\)$", "", n)
    return ALIAS.get(n, n) or name


def record(code, rec, Y):
    """해석된 표 → {segments, sum_rev, elim_rev, rev_total, basis, ...} (금액은 원)"""
    rows = rec["rows"]
    revrow, basis_hint = _revrow(rec)
    if revrow is None:
        return None
    if basis_hint == "gross" and rec.get("ext_ok"):
        basis_hint = "ext"                 # 이름은 '수익(매출액)'이지만 부문 합 = 연결 매출(SK 2025 '순매출액 공시' 표)
    oprow = rows.get("op") or rows.get("op_seg")
    op_basis = "영업이익" if rows.get("op") else ("부문이익(순이익 기준)" if rows.get("op_seg") else None)
    if oprow is None and CO[code].get("op_pti") and rows.get("pti"):
        oprow, op_basis = rows["pti"], "세전이익(부문 영업이익 미공시 — 법인세비용차감전순손익)"
    nirow = rows.get("ni") if (oprow is None and CO[code].get("keep_ni")) else None
    segs, parent = [], {}
    names = rec["segs"] or list(revrow["seg"].keys())
    for s in names:
        if rec["parent"].get(s):
            parent[s] = {"rev": revrow["seg"].get(s), "op": oprow["seg"].get(s) if oprow else None}
            continue
        x = {"name": s, "rev": revrow["seg"].get(s), "op": oprow["seg"].get(s) if oprow else None}
        # 저장 이름은 빈칸을 뺀다('석 유' → '석유', 'Industry 소재' → 'Industry소재') — 원문은 name_src
        nm = re.sub(r"\s+", "", s)
        nm = TYPO.get(nm, nm)
        if nm != s:
            x["name"], x["name_src"] = nm, s
        if nirow:
            x["ni"] = nirow["seg"].get(s)
        segs.append(x)
    # 같은 표에 짝이 없을 때만 바꾸는 이름(삼성물산 2016 사업보고서 '건설1' = 통합 건설 — 2015 는 건설1 · 건설2 가 함께 있다)
    for old, new in (CO[code].get("rename_solo") or {}).items():
        hit = [x for x in segs if x["name"] == old]
        if hit and not any(_canon(x["name"]) == new for x in segs if x is not hit[0]):
            hit[0].setdefault("name_src", old)
            hit[0]["name"] = new
    # 삼성 DS: 반도체 · DP 를 쓰고 DS 합계와의 차이는 'DS 내 잔여'(섹터 skip)
    for pname, pv in parent.items():
        kids = [x for x in segs if any(re.match(crx, _norm(x["name"])) for _p, crx, _k in CO[code]["kids"])]
        if pv["rev"] is not None and kids:
            r = pv["rev"] - sum(k["rev"] or 0 for k in kids)
            o = (pv["op"] - sum(k["op"] or 0 for k in kids)) if pv["op"] is not None else None
            segs.append({"name": "기타(%s내잔여)" % _canon(pname), "rev": r, "op": o})     # 저장 이름은 빈칸 없이
    sum_rev = sum(x["rev"] for x in segs if x["rev"] is not None)
    sum_op = sum(x["op"] for x in segs if x["op"] is not None) if oprow else None
    T = revrow.get("total")
    if T is None:
        T = sum_rev + (revrow.get("elim") or 0)
    elim = T - sum_rev
    if basis_hint == "ext" and abs(sum_rev - T) <= 0.02 * abs(T):
        basis = "외부매출"
    elif basis_hint == "ext":
        basis = "부문간 내부거래 포함"     # '순매출액'이 회사 안 부문간 매출을 품은 경우(삼성전자)
    else:
        basis = "외부매출" if abs(sum_rev - T) <= 0.005 * abs(T) and revrow.get("elim") in (None, 0) \
            else "부문간 내부거래 포함"
    op_tot = oprow.get("total") if oprow else None
    if oprow and op_tot is None and oprow.get("elim") is not None and sum_op is not None:
        op_tot = sum_op + oprow["elim"]
    op_elim = (op_tot - sum_op) if (op_tot is not None and sum_op is not None) else None
    for x in segs:
        x["sector"] = _sector(code, x["name"], Y)
    oth = rows.get("oth")
    other = None
    if oth:
        vals = [v for s_, v in oth["seg"].items() if v is not None and not rec["parent"].get(s_)]
        other = oth.get("total") if oth.get("total") is not None else (sum(vals) if vals else None)
    out = {"segments": segs, "sum_rev": sum_rev, "elim_rev": elim, "rev_total": T, "basis": basis, "other_rev": other,
           "sum_op": sum_op, "elim_op": op_elim, "op_total": op_tot, "op_basis": op_basis,
           "rev_label": revrow.get("label"), "op_label": oprow.get("label") if oprow else None}
    if nirow:
        out["ni_label"] = nirow.get("label")      # 부문 영업이익 없이 순손익만 있는 표(SKC 2023 ~) — 부문 'ni'
    return out


def _merge_op(rec, other):
    """rec(주석 매출표)의 영업이익 줄을 other(II 요약표)의 영업이익으로 바꾼다 — 부문 이름 키로. 둘 넘게 맞으면 True"""
    orow = other["rows"].get("op")
    if not orow:
        return False
    om = {_canon(s): v for s, v in orow["seg"].items()}
    names = rec["segs"] or []
    seg = {s: om.get(_canon(s)) for s in names}
    if sum(1 for v in seg.values() if v is not None) < 2:
        return False
    rec["rows"] = dict(rec["rows"])
    rec["rows"].pop("op_seg", None)
    rec["rows"]["op"] = {"seg": seg, "total": orow.get("total"), "elim": orow.get("elim"),
                         "label": "영업이익(II 사업부문별 요약 재무현황 %s)" % other["src"].split(" ")[0]}
    rec["op_from_biz"] = True
    miss = [s for s, v in seg.items() if v is None and not rec["parent"].get(s)]
    if miss:
        rec["op_miss"] = miss
    return True


def _merge_to(a_keys, bm):
    """b(직전 누적)의 부문을 a 의 이름으로 묶는다 — a 의 '석유및화학' = b 의 '석유' + '화학'.
    돌려주는 것: {a 키: [b 키들]}, 남는 b 키들"""
    used, out = set(), {}
    for k in a_keys:
        if k in bm:
            out[k] = [k]
            used.add(k)
    for k in a_keys:
        if k in out or "및" not in k:
            continue
        parts = [p for p in k.split("및") if p]
        if parts and all(p in bm and p not in used for p in parts):
            out[k] = parts
            used.update(parts)
    return out, [k for k in bm if k not in used]


def _minus(a, b, loose=False):
    """누적 a − 누적 b (부문 이름 키로). 맞출 수 없으면 (None, 이유).
    loose=True 면 b 에만 있는 부문(중단영업으로 빠진 부문 등)은 버리고 뺀다 — 이유에 적는다."""
    bm = {_canon(x["name"]): x for x in b["segments"]}
    akeys = [_canon(x["name"]) for x in a["segments"]]
    match, left = _merge_to(akeys, bm)
    left = [k for k in left if (bm[k]["rev"] or 0) != 0]
    if left and not loose:
        return None, "직전 누적에만 있는 부문 %s" % ",".join(left)
    segs = []
    for x, k in zip(a["segments"], akeys):
        ys = [bm[j] for j in match.get(k, [])]
        r = x["rev"] - sum(y["rev"] or 0 for y in ys) if x["rev"] is not None else None
        o = x["op"] - sum(y["op"] or 0 for y in ys) if x["op"] is not None else None
        y_ = {"name": x["name"], "rev": r, "op": o, "sector": x["sector"]}
        if x.get("name_src"):
            y_["name_src"] = x["name_src"]
        if "ni" in x:
            y_["ni"] = x["ni"] - sum(y.get("ni") or 0 for y in ys) if x["ni"] is not None else None
        segs.append(y_)
    out = {"segments": segs, "basis": a["basis"], "op_basis": a["op_basis"]}
    if a.get("ni_label"):
        out["ni_label"] = a["ni_label"]
    # 합계는 두 누적 표의 연결 합계 차이, 부문 합은 새로 더한다 — 조정(elim) = 합계 − 부문 합
    out["sum_rev"] = sum(x["rev"] for x in segs if x["rev"] is not None)
    out["other_rev"] = a["other_rev"] - (b.get("other_rev") or 0) if a.get("other_rev") is not None else None
    out["rev_total"] = a["rev_total"] - b["rev_total"] if None not in (a.get("rev_total"), b.get("rev_total")) else None
    out["elim_rev"] = out["rev_total"] - out["sum_rev"] if out["rev_total"] is not None else None
    have_op = any(x["op"] is not None for x in segs)
    out["sum_op"] = sum(x["op"] for x in segs if x["op"] is not None) if have_op else None
    out["op_total"] = a["op_total"] - b["op_total"] if None not in (a.get("op_total"), b.get("op_total")) else None
    out["elim_op"] = out["op_total"] - out["sum_op"] if None not in (out["op_total"], out["sum_op"]) else None
    notes = []
    new = [k for k in akeys if k not in match]
    if new:
        notes.append("새 부문 %s(직전 누적 0)" % ",".join(new))
    merged = ["%s=%s" % (k, "+".join(v)) for k, v in match.items() if v != [k]]
    if merged:
        notes.append("직전 누적을 묶음 %s" % ",".join(merged))
    if left:
        notes.append("직전 누적에만 있던 부문 %s 은 빼지 않음" % ",".join(left))
        # 그 부문 몫은 연결 합계에서도 빠졌다(중단영업 재분류) — 합계 차이는 검산에서 드러난다
    out["exact"] = not new and not merged and not left
    return out, "; ".join(notes) or None


def build_company(code, L=None):
    """한 회사 → {name, y, q, issues}. 단독 분기는 3개월 표 → 누적 차감 → (부문 구성이 바뀐 해) 다음 해 보고서의
    재작성 비교 숫자(전년 같은 기간)로 차감."""
    cfg = CO[code]
    L = L if L is not None else ledger(code)
    reps = reports(code)
    cum, three, rcum, r3 = {}, {}, {}, {}
    issues = []
    for (Y, q) in sorted(reps):
        if Y < 2015:
            continue
        got, d = {}, None
        for which in cfg["src"]:
            got, d = pick(code, Y, q, L, which)
            if got:
                break
        if not got:
            issues.append("%dQ%d 부문표를 못 읽음(%s)" % (Y, q, os.path.basename(reps[(Y, q)][0])))
            continue
        if cfg.get("op_from") and which != cfg["op_from"]:
            got_b, _d = pick(code, Y, q, L, cfg["op_from"])
            for slot, rec in got.items():
                if slot in got_b and not _merge_op(rec, got_b[slot]):
                    issues.append("%dQ%d %s 영업이익을 II 요약표와 못 맞춤" % (Y, q, "/".join(slot)))
        for (who, sp), rec in got.items():
            r = record(code, rec, Y if who == "cur" else Y - 1)
            if r is None:
                continue
            r["src"] = rec["src"]
            if rec.get("op_from_biz"):
                r["op_src"] = rec["rows"]["op"]["label"]
                if rec.get("op_miss"):
                    r["op_missing"] = rec["op_miss"]
            if who == "cur":
                (cum if sp == "cum" else three)[(Y, q)] = r
            else:
                r["src"] += " (전년 비교 숫자 — 재작성)"
                (rcum if sp == "cum" else r3)[(Y - 1, q)] = r
    for (Y, q), why in (cfg.get("skip_restated") or {}).items():
        rcum.pop((Y, q), None)              # 다음 해 보고서의 전년 비교 숫자가 재작성이 안 된(옛 구성) 경우 — 차감 후보에서 뺀다
        r3.pop((Y, q), None)
        issues.append("%dQ%d 다음 해 보고서의 전년 비교 숫자를 쓰지 않음 — %s" % (Y, q, why))
    for (Y, q), why in (cfg.get("prefer_restated") or {}).items():
        if (Y, q) in rcum:
            cum[(Y, q)] = dict(rcum[(Y, q)], restated=why)
            three.pop((Y, q), None)
            if (Y, q) in r3:
                three[(Y, q)] = dict(r3[(Y, q)], restated=why)
            issues.append("%dQ%d 재작성 숫자 사용 — %s" % (Y, q, why))
    Yd, Qd = {}, {}
    for (Y, q), r in sorted(cum.items()):
        if q == 4:
            Yd[str(Y)] = r
            if Y in (cfg.get("partial") or {}):
                r["partial"] = cfg["partial"][Y]
                issues.append("%d 연간 — %s" % (Y, cfg["partial"][Y]))
    hz = min(cfg.get("partial") or {0: 0})          # HD현대 설립 2017-04-01 — 그해 반기 누적 = 2분기
    for (Y, q) in sorted(set(cum) | set(three)):
        key = "%dQ%d" % (Y, q)
        if (Y, q) in three:
            Qd[key] = dict(three[(Y, q)], derived=None)
            continue
        if q == 1 and (Y, q) in cum:
            Qd[key] = dict(cum[(Y, q)], derived=None)
            continue
        a, b = cum.get((Y, q)), cum.get((Y, q - 1))
        if a is None:
            continue
        if b is None and Y == hz and q == 2:
            Qd[key] = dict(a, derived="설립 2017-04-01 — 반기 누적 = 2분기")
            continue
        # 후보: 같은 해 직전 누적 · 다음 해 보고서가 다시 쓴 직전 누적 · (안 되면) 직전 누적에만 있는 부문을 버린 차감
        tries = []
        if b is not None:
            tries.append((b, False, "누적 %dQ%d − 누적 %dQ%d" % (Y, q, Y, q - 1)))
        if rcum.get((Y, q - 1)) is not None:
            tries.append((rcum[(Y, q - 1)], False, "누적 %dQ%d − 누적 %dQ%d(다음 해 보고서의 재작성 숫자)" % (Y, q, Y, q - 1)))
        if b is not None:
            tries.append((b, True, "누적 %dQ%d − 누적 %dQ%d" % (Y, q, Y, q - 1)))
        if rcum.get((Y, q - 1)) is not None:
            tries.append((rcum[(Y, q - 1)], True, "누적 %dQ%d − 누적 %dQ%d(다음 해 보고서의 재작성 숫자)" % (Y, q, Y, q - 1)))
        lg = L.get((Y, q)) or {}
        best, whys, best_b = None, [], None
        for rank, (bb, loose, how) in enumerate(tries):
            m, why = _minus(a, bb, loose)
            if m is None:
                whys.append(why)
                continue
            s_ = (m.get("sum_rev") or 0) + (m.get("elim_rev") or 0)
            ok = _close(s_, lg.get("rev3"), 0.02)
            o_ = m.get("op_total") if m.get("op_total") is not None else m.get("sum_op")
            ok_op = _close(o_, lg.get("op3"), 0.05)
            neg = any((x["rev"] or 0) < 0 for x in m["segments"])
            score = (8 if ok else 0) + (4 if ok_op else 0) + (2 if m.get("exact") else 0) + (1 if not neg else 0) - rank * 0.1
            if best is None or score > best[0]:
                m["src"] = "%s − %s" % (a["src"], bb["src"])
                m["derived"] = how + ("; " + why if why else "")
                if a.get("op_src"):
                    m["op_src"] = a["op_src"]
                best = (score, m)
                best_b = bb
        if best is None:
            issues.append("%s 단독 분기를 못 만듦 — %s" % (key, " / ".join(whys) or "직전 누적 없음"))
            continue
        m = best[1]
        m.pop("exact", None)
        Qd[key] = m
        if (a.get("op_src") is None) != (best_b.get("op_src") is None) or a.get("op_basis") != best_b.get("op_basis"):
            issues.append("%s 의심 — 영업이익 기준이 다른 두 누적을 뺐다(%s − %s)" % (
                key, a.get("op_src") or a.get("op_basis"), best_b.get("op_src") or best_b.get("op_basis")))
        negs = [x["name"] for x in m["segments"] if (x["rev"] or 0) < 0 and "내잔여" not in x["name"]]
        if negs:
            issues.append("%s 의심 — 차감으로 만든 분기에 음수 매출 부문 %s (%s)" % (key, ",".join(negs), m["derived"]))
        if best_b is not None and best_b is rcum.get((Y, q - 1)):
            _restate_year(Y, q, rcum, Qd, issues)
    for key, why in (cfg.get("drop_q") or {}).items():
        if Qd.pop(key, None) is not None:   # 어느 차감으로도 같은 기준이 안 되는 분기 — 틀린 숫자를 남기지 않는다
            issues.append("%s 단독 분기를 뺌 — %s" % (key, why))
    if cfg.get("check_restated"):
        _restated_by_next(code, Yd, Qd, rcum, r3, issues)
    return {"name": cfg["name"], "y": Yd, "q": Qd, "issues": issues}


def _restated_by_next(code, Yd, Qd, rcum, r3, issues):
    """다음 해 보고서가 전년 비교 숫자를 다른 구성으로 다시 쓴 기간 — 섹터에 넣는 부문의 매출이 3% 넘게 다르면
    그 기간 레코드에 'restated_by_next'(다음 해 보고서 기준 부문 숫자)를 붙이고 issues 에 남긴다. 저장 숫자는 처음 보고 그대로
    (1 ~ 4분기 합 = 연간). 다음 해와 견주는 증가율은 이 숫자로 해야 같은 구성이다(LG생활건강 2026 HDB → Beauty 이동 등)."""
    def alt_of(Y, q):
        if q == 4:
            a, b = rcum.get((Y, 4)), rcum.get((Y, 3))
        elif (Y, q) in r3:
            return r3[(Y, q)]
        elif q == 1:
            return rcum.get((Y, 1))
        else:
            a, b = rcum.get((Y, q)), rcum.get((Y, q - 1))
        if a is None or b is None:
            return None
        m, _why = _minus(a, b)
        return m if m and m.get("exact") else None

    def diff(stored, alt):
        sm = {_canon(x["name"]): x for x in stored["segments"]}
        am = {_canon(x["name"]): x for x in alt["segments"]}
        out = []
        for k, x in sm.items():
            if x.get("sector", "skip") == "skip" or x.get("rev") is None:
                continue
            y = am.get(k)
            yr = y.get("rev") if y else None
            if yr is None or abs(yr - x["rev"]) > 0.03 * max(abs(x["rev"]), 1.0):
                out.append((x["name"], x["rev"], yr))
        return out

    for kind, store in (("y", Yd), ("q", Qd)):
        for p, r in sorted(store.items()):
            Y = int(p[:4])
            q = int(p[-1]) if kind == "q" else 4
            alt = rcum.get((Y, 4)) if kind == "y" else alt_of(Y, q)
            if not alt or r.get("restated") or (r.get("derived") or "").startswith("재작성"):
                continue
            s1, t1 = alt.get("sum_rev"), alt.get("rev_total")
            if s1 is None or not t1 or abs(s1) > 1.35 * abs(t1) or \
                    any((x.get("rev") or 0) > 1.001 * abs(t1) for x in alt["segments"]):
                continue                       # 부문 합이 연결 합계보다 훨씬 크거나 한 부문이 합계보다 크면 표를 잘못 읽은 것 — 쓰지 않는다
            d = diff(r, alt)
            if not d:
                continue
            r["restated_by_next"] = {"segments": [{"name": x["name"], "rev": x["rev"], "op": x["op"]}
                                                  for x in alt["segments"]],
                                     "src": alt.get("src")}
            issues.append("%s 다음 해 보고서가 전년 숫자를 다시 씀 — %s (restated_by_next 에 다음 해 기준 숫자)" % (
                p, ", ".join("%s %s → %s" % (n, _eok(a), _eok(b)) for n, a, b in d)))


def _restate_year(Y, k, rcum, Qd, issues):
    """k 분기를 다음 해 보고서의 재작성 누적(부문 구성 변경 · 중단영업 재분류 반영)으로 뺐으면, 같은 해 앞 분기들도
    재작성 누적으로 다시 만든다 — 그래야 1~4분기 합이 연간과 맞고 다음 해 같은 분기와 같은 기준으로 비교된다.
    재작성 누적이 다 있고 부문 이름이 정확히 맞을 때만 바꾸고, 못 바꾸면 issues 에 남긴다."""
    new = {}
    for j in range(1, k):
        cj = rcum.get((Y, j))
        if cj is None:
            break
        if j == 1:
            new[j] = dict(cj, derived="재작성(다음 해 1분기 보고서의 전년 숫자)")
            continue
        m, why = _minus(cj, rcum.get((Y, j - 1)) or {"segments": []})
        if m is None or not m.get("exact"):
            break
        m.pop("exact", None)
        m["src"] = "%s − %s" % (cj["src"], rcum[(Y, j - 1)]["src"])
        m["derived"] = "재작성 누적 %dQ%d − 재작성 누적 %dQ%d(다음 해 보고서의 전년 숫자)" % (Y, j, Y, j - 1)
        new[j] = m
    if len(new) != k - 1:
        issues.append("%dQ%d 를 재작성 누적으로 뺐지만 %d년 앞 분기는 처음 보고 숫자 그대로 — 분기 합이 연간과 다를 수 있다" % (Y, k, Y))
        return
    for j, rec in new.items():
        rec["restated"] = "%dQ%d 를 재작성 누적으로 만들어 같은 기준으로 다시 씀(원장의 처음 보고 숫자와 다를 수 있다)" % (Y, k)
        Qd["%dQ%d" % (Y, j)] = rec
    issues.append("%d년 1~%d분기를 재작성 숫자로 바꿈(%dQ%d 차감 기준과 맞춤)" % (Y, k - 1, Y, k))


# ---------------------------------------------------------------- 검산
def validate(code, comp, L):
    """기간마다 매출: |부문 합 + 조정 − 원장 연결 매출| / 원장 < 2%.
    영업이익: |부문 합 − 원장| / |원장| < 5%, 아니면 표에 적힌 연결조정까지 더해 5% 안이면 통과(이유를 남긴다).
    결과는 각 레코드의 cons_rev · cons_op · check 에 적고, 어긋난 기간은 issues 에 넣는다."""
    rows = []
    for kind in ("y", "q"):
        for p, r in sorted(comp[kind].items()):
            Y = int(p[:4])
            q = int(p[-1]) if "Q" in p else 4
            lg = L.get((Y, q)) or {}
            cr = lg.get("revc") if kind == "y" else lg.get("rev3")
            co = lg.get("opc") if kind == "y" else lg.get("op3")
            r["cons_rev"], r["cons_op"] = cr, co
            r["cons_src"] = lg.get("src")
            s = (r.get("sum_rev") or 0) + (r.get("elim_rev") or 0)
            gap = abs(s - cr) / abs(cr) if cr else None
            gap_o = abs(s + r["other_rev"] - cr) / abs(cr) if cr and r.get("other_rev") else None
            so = r.get("sum_op")
            og = abs(so - co) / abs(co) if (so is not None and co) else None
            so2 = so + (r.get("elim_op") or 0) if so is not None else None
            og2 = abs(so2 - co) / abs(co) if (so2 is not None and co) else None
            ok_r = (gap is not None and gap < 0.02) or (gap_o is not None and gap_o < 0.02)
            ok_o = (og is not None and og < 0.05) or (og2 is not None and og2 < 0.05)
            why = []
            if gap is None:
                why.append("원장 없음")
            elif gap >= 0.02 and ok_r:
                why.append("매출 부문 합은 %.1f%% 차이 — 표의 정부보조금(IRA AMPC) 등 기타영업수익 %s 를 더하면 원장 매출 줄과 맞음"
                           % (gap * 100, _eok(r.get("other_rev"))))
            elif not ok_r:
                why.append("매출 차이 %.1f%%" % (gap * 100))
                if CO[code].get("check_restated") and "직전 누적에만 있던 부문" in (r.get("derived") or ""):
                    why.append("직전 누적에만 있던 부문(중단영업으로 빠진 부문)은 빼지 않은 차감이라 합계가 원장 3개월과 다르다"
                               " — 남은 부문 값은 같은 기준")
                if r.get("restated"):
                    why.append("재작성 숫자라 원장(처음 보고)과 다름 — 중단영업 재분류 등")
                if "기타수익" in (lg.get("rev_nm") or ""):
                    why.append("원장 매출 줄이 '%s'(기타수익 포함 — 부문표는 매출만)" % lg["rev_nm"])
            if og is not None and og >= 0.05:
                if og2 is not None and og2 < 0.05:
                    why.append("영업이익 부문 합은 %.0f%% 차이 — 표의 연결조정 %s 를 더하면 맞음" % (og * 100, _eok(r.get("elim_op"))))
                else:
                    why.append("영업이익 차이 %.0f%%" % (og * 100) +
                               (" (op_basis %s)" % r.get("op_basis") if r.get("op_basis") != "영업이익" else ""))
                    if r.get("op_src") and CO[code].get("op_note"):
                        why.append(CO[code]["op_note"])
                    elif r.get("restated") and ok_r is False:
                        why.append("(재작성 숫자)")
            elif so is None:
                why.append("영업이익 줄 없음" + (" — 부문 영업이익 미공시, 부문 순손익('%s')만 있어 segments 의 ni 에 둠"
                                                % r["ni_label"] if r.get("ni_label") else ""))
            r["check"] = {"rev_gap": None if gap is None else round(gap, 4),
                          "rev_gap_other": None if gap_o is None else round(gap_o, 4),
                          "op_gap": None if og is None else round(og, 4),
                          "op_gap_adj": None if og2 is None else round(og2, 4),
                          "rev_ok": ok_r, "op_ok": ok_o, "why": "; ".join(why) or None}
            if not ok_r or not ok_o:
                comp["issues"].append("%s %s" % (p, "; ".join(why) or "영업이익 검산 불가"))
            rows.append((code, p))
    return rows


def _eok(v):
    return "-" if v is None else "{:,.0f}억".format(v / 1e8)


# 산업_섹터.SEGMENTS 정규식이 놓친(= 'skip' 이 된) 실제 부문 이름과 제안 — 산업_섹터.py 는 여기서 고치지 않는다
# (찾을 이름, 제안 섹터, 제안 정규식 — None 이면 누락이 아니라 '합쳐진 부문' 경고)
MISS_HINT = {
    "096770": [(r"에너지\s*(?:및|/)\s*화학", "정유", r"^석유(?!개발)|정유|윤활|^에너지\s*(?:및|/)\s*화학"),
               (r"^석유\s*및\s*화학", "정유(화학 포함 — 2024 사업보고서에서 합쳐짐)", None)],
    "009830": [(r"^원\s*료$", "석유화학", r"케미칼|기초소재|첨단소재|^원\s*료$|^가\s*공(?:소재)?$"),
               (r"^가\s*공(?:소재)?$", "석유화학", r"케미칼|기초소재|첨단소재|^원\s*료$|^가\s*공(?:소재)?$")],
    # ---- 2026-10-06 추가 회사
    "030200": [(r"Marketing|Customer", "통신(2015 ~ 2018 의 ICT 전신 — 유무선 통신)",
                r"^ICT|Marketing|Customer|^기업사업|통신|텔레콤|^유무선"),
               (r"^기업사업", "통신(2018 B2B 통신 — 2019 ICT 로 합쳐짐)", r"^ICT|Marketing|Customer|^기업사업|통신|텔레콤|^유무선")],
    "064350": [(r"^중기", "방산·항공우주(2015 ~ 2016 중기 = 방산)", r"디펜스|방산|방위|^중기|^AD&RH"),
               (r"^AD&RH", "방산·항공우주(2026 반기 ~ AD&RH = 방산)", r"디펜스|방산|방위|^중기|^AD&RH")],
    "051900": [(r"^Beautiful", "화장품(2015 ~ 2019 Beautiful = 2020 ~ Beauty)", r"Beaut|화장품|뷰티"),
               (r"^Refreshing", "음식료(2015 ~ 2019 Refreshing = 2020 ~ Refreshment)", r"Refresh|음료")],
    "011790": [(r"^Mobility", "2차전지(2020 ~ 2021 Mobility = SK넥실리스 동박, 2022 ~ 2차전지소재)",
                r"2차전지|이차전지|배터리|동박|모빌리티|Mobility")],
    # 합쳐진 부문 경고(정규식 누락 아님): 2015 ~ 2017 물류부문에 해운이 들어 있다(2018 은 2019 사업보고서의 재작성 숫자)
    "086280": [(r"^물류", "해운(물류부문 안에 해운 포함 — 2015 ~ 2017 은 해운을 따로 못 가른다)", None)],
}
# 'regex=None'(합쳐진 부문 경고)을 해당 연도에만 남기는 회사 — 그 밖의 해는 정상 부문
MISS_YEARS = {"086280": {"2015", "2016", "2017"}}


def _regex_misses(out):
    """[{code, name, years, sector_now, suggest, regex}] — 정규식이 놓친 부문(섹터에 넣어야 할 것)"""
    miss = {}
    for code, c in out.items():
        for kind in ("y", "q"):
            for p, r in c[kind].items():
                for s in r["segments"]:
                    for rx, sug, fix in MISS_HINT.get(code, []):
                        if code in MISS_YEARS and p[:4] not in MISS_YEARS[code]:
                            continue
                        if re.search(rx, s["name"]) and (s["sector"] == "skip" or fix is None):
                            if s["sector"] == "skip":
                                s["suggest"] = sug
                            m = miss.setdefault((code, s["name"]), {
                                "code": code, "name": s["name"], "years": set(), "sector_now": s["sector"],
                                "suggest": sug, "regex": fix})
                            m["years"].add(p[:4])
    res = []
    for m in miss.values():
        m["years"] = sorted(m["years"])
        res.append(m)
    return sorted(res, key=lambda m: (m["code"], m["name"]))


def _int(o):
    """금액(원)을 정수로 — 파일을 줄인다(비율은 check 안에만 있다)"""
    if isinstance(o, float):
        return int(round(o))
    if isinstance(o, dict):
        return {k: (v if k == "check" else _int(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [_int(x) for x in o]
    return o


# ---------------------------------------------------------------- 만들기
def build(codes=None, verbose=True):
    t0 = time.time()
    codes = codes or list(CO)
    out = {}
    for code in codes:
        L = ledger(code)
        comp = build_company(code, L)
        validate(code, comp, L)
        out[code] = _int(comp)
        if verbose:
            print("%s %s  연간 %d · 분기 %d · 문제 %d  (%.0fs)" % (code, comp["name"], len(comp["y"]), len(comp["q"]),
                                                             len(comp["issues"]), time.time() - t0))
    doc = {"v": VERSION, "built": dt.datetime.now().isoformat(timespec="seconds"), "companies": out,
           "regex_miss": _regex_misses(out)}
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    return doc


def print_table(doc):
    """검산표 — 기간마다 부문 합 + 조정 vs 원장 매출, 부문 영업이익 합 vs 원장 영업이익"""
    print("%-7s %-7s %14s %14s %7s | %11s %11s %7s %7s  %-6s %s" % (
        "code", "기간", "부문합+조정", "원장매출", "차이", "부문OP합", "원장OP", "차이", "조정후", "판정", "기준 · 비고"))
    n = nr = no = 0
    pct = lambda x: "-" if x is None else "%.2f%%" % (x * 100)     # noqa: E731
    for code, c in doc["companies"].items():
        for kind in ("y", "q"):
            for p, r in sorted(c[kind].items()):
                ck = r.get("check") or {}
                s = (r.get("sum_rev") or 0) + (r.get("elim_rev") or 0)
                n += 1
                nr += bool(ck.get("rev_ok"))
                no += bool(ck.get("op_ok"))
                verdict = "OK" if ck.get("rev_ok") and ck.get("op_ok") else \
                    ("rev" if not ck.get("rev_ok") else "") + ("op" if not ck.get("op_ok") else "")
                print("%-7s %-7s %14s %14s %7s | %11s %11s %7s %7s  %-6s %s%s" % (
                    code, p, _eok(s), _eok(r.get("cons_rev")), pct(ck.get("rev_gap")),
                    _eok(r.get("sum_op")), _eok(r.get("cons_op")), pct(ck.get("op_gap")), pct(ck.get("op_gap_adj")),
                    verdict, r.get("basis") or "", (" · " + ck["why"]) if ck.get("why") else ""))
    print("기간 %d · 매출 통과 %d (%.1f%%) · 영업이익 통과 %d (%.1f%%)" % (
        n, nr, 100.0 * nr / max(n, 1), no, 100.0 * no / max(n, 1)))
    for m in doc.get("regex_miss") or []:
        print("정규식 누락: %s %s (%s) 지금 %s → 제안 %s %s" % (
            m["code"], m["name"], ",".join(m["years"]), m["sector_now"], m["suggest"], m["regex"] or ""))


def main(argv):
    if len(argv) > 1 and argv[1] == "점검":
        try:
            with open(OUT, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            doc = build(verbose=False)
        print_table(doc)
        return
    doc = build()
    rows = [r for c in doc["companies"].values() for k in ("y", "q") for r in c[k].values()]
    print("저장 %s — 기간 %d, 매출 검산 통과 %d, 영업이익 검산 통과 %d" % (
        OUT, len(rows), sum(1 for r in rows if (r.get("check") or {}).get("rev_ok")),
        sum(1 for r in rows if (r.get("check") or {}).get("op_ok"))))


if __name__ == "__main__":
    main(sys.argv)
