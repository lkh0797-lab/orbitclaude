# -*- coding: utf-8 -*-
"""
공시 제목 분류 · 사망(비자발 상장폐지) 정의 — 2026-10-05

바닥 자료: .cache/공시목록/{I,B,A001}_YYYYQn.jsonl  (도구/공시목록_수집.py 가 OpenDART list.json 에서 받은 것)
  I    거래소공시   — 회사가 낸 수시공시 + 거래소(유가증권시장본부 · 코스닥시장본부 · 코넥스시장)가 낸 시장조치 안내
  B    주요사항보고서
  A001 사업보고서
DART API 는 쓰지 않는다(이미 받은 파일만 읽는다).

이 모듈이 주는 것
  CATEGORIES                     범주 목록 [{id, 군, 설명, 정규식, 제외, 제출자}]
                                   군: 위험(사망을 미리 알릴 후보 신호) · 사망(D_ 비자발 상장폐지 표지) · 퇴장(X_ 사망 아닌 상장 종료 표지)
                                       · 해소(R_) · 대조(건전 기업에도 흔한 공시) · 기타
  RISK                           위험 범주 id 목록(신호 연구용)
  norm(report_nm)                → (깨끗한 제목, 머리말 목록)   '[기재정정]' · '[첨부추가]' 등을 뗀다(정정 재제출을 셀지 말지는 머리말로)
  classify(report_nm, flr_nm)    → 범주 id 튜플(여러 개일 수 있다). 자회사 · 종속회사 사항은 ('자회사사항',) 만.
  halt_reason(report_nm)         → 매매거래정지 사유 묶음(상장폐지사유 · 실질심사 · 관리종목 · 불성실공시 · 풍문 · 회생 · 구조변경 · 기술적 …)
  market_of(rcept_no)            → '유가' · '코스닥' · '코넥스' · '채권' · None  (거래소공시 접수번호 9번째 자리)
  death_of(rows)                 → 회사 하나의 사망 판정 dict (아래 death_of 설명)
  judge_all(rows)                → {corp_code: death_of 결과} (종목코드 + 거래소공시가 있는 회사 3,448곳)
  load_rows()                    → {corp_code: [row dict …]} (rcept_dt 순, row 에 kind=I/B/A001 을 더함)

신호 연구에서 쓸 때 주의
  * 사망일은 '사슬의 첫 결정적 사건' 이다(정리매매보다 중앙값 173일 앞). 그 날 이후의 공시는 '이미 죽는 중' 이므로
    예측 신호로 쓰지 말 것. 정리매매일 · 상장종료 · 최종정지일 · 첫사유일도 같이 준다.
  * 상폐절차중(지금 상장이지만 상장폐지 사유 · 결정 · 정리매매 보류 중) 은 사망=None — 2025~2026 을 셀 때 따로 더할지 정할 것.
  * 사망(추정)은 제목에 상장폐지가 직접 안 나온 2013~2018 유가 · 코넥스 퇴출(16곳) — 엄격히 하려면 빼고 센다.
  * 시장 필드로 코넥스를 거를 수 있다.

중요한 사실(자료에서 확인, 분류_점검.json 에 근거 숫자)
  * corp_cls 는 '지금' 분류다. 지금 Y/K/N 인 회사는 2026-03 이후에도 모두 거래소공시가 있다 → 상장 중.
    지금 E 이면서 종목코드가 있고 거래소공시(I)가 있는 회사 = 2013-01 이후 어느 시점에 상장이 끝난 회사.
  * 그 시점의 시장은 corp_cls 가 아니라 거래소공시 접수번호(rcept_no) 9번째 자리로 안다:
    8 = 유가증권, 9 = 코스닥, 6 = 코넥스, 7 = 채권시장.  B · A001 은 9번째 자리가 0(금감원 접수).
  * 상장폐지 뒤에는 거래소공시가 끊긴다(비상장이라 수시공시 의무가 없다). 사업보고서(A001) · 주요사항보고서(B)는
    주주 500명 이상이면 계속 낸다(웅진에너지 2021 · 2022 사업보고서) → '끊김' 은 거래소공시만으로 잰다.
  * DART 거래소공시에는 KIND 의 시장조치 원문(관리종목 지정 · 투자경고 지정 · '상장폐지' 그 자체)이 거의 없다.
    대신 거래소가 낸 '주권매매거래정지(…사유)' · '기타시장안내(…)' · '주권매매거래정지해제(상장폐지에 따른 정리매매 개시)'
    와 회사가 낸 '내부결산시점관리종목지정ㆍ형식적상장폐지ㆍ상장적격성실질심사사유발생' 등이 있다.
  * 회사가 직접 낸 '상장폐지결정' 은 자진 상장폐지 · 이전상장(셀트리온 2018 · 카카오 2017) · 선박펀드 해산이다 — 사망 아님.

실행(DART 호출 0)
  python 도구/공시분류.py            # .cache/공시목록/분류_점검.json 을 다시 만든다 (빈도 · 예시 · 연도별 사망 수 · 점검 기록, 약 30초)
  python 도구/공시분류.py 117930     # 종목코드(또는 corp_code · 회사명) 하나의 판정 · 근거 · 마지막 제목 흐름을 찍는다

결과(2026-10-05 실행, 자료끝 2026-10-02): 판정 대상 3,448곳 = 상장중 2,656 · 상폐절차중 80 · 사망 290 · 사망(추정) 16 · 사망(약) 4
  · 스팩 176 · 합병소멸 100 · 리츠펀드 45 · 자진상폐 41 · 주식교환 37 · 이전상장 2 · 불명 1.
  연도별 사망(사망일 기준, 유가+코스닥+코넥스): 2013 33 · 2014 18 · 2015 21 · 2016 10 · 2017 19 · 2018 28 · 2019 20 · 2020 27
  · 2021 24 · 2022 18 · 2023 28 · 2024 36 · 2025 21(+상폐절차중 29) · 2026 7(+상폐절차중 49).
"""
import collections
import datetime as dt
import functools
import glob
import json
import os
import random
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(BASE, ".cache", "공시목록")
OUT = os.path.join(DIR, "분류_점검.json")
KINDS = ("I", "B", "A001")

EXCH = ("코스닥시장본부", "유가증권시장본부", "코넥스시장", "채권시장")
MARKET = {"8": "유가", "9": "코스닥", "6": "코넥스", "7": "채권"}

PREFIX_RE = re.compile(r"^(\s*\[(기재정정|첨부정정|첨부추가|연장결정|정정명령부과|발행조건확정)\]\s*)+")
PREFIX_ONE = re.compile(r"\[([^\]]*)\]")
WS = re.compile(r"\s+")
SUB_RE = re.compile(r"\((자회사|종속회사)의?주요경영사항\)")

SPAC_NAME = re.compile(r"스팩|기업인수목적|SPAC", re.I)
FUND_NAME = re.compile(r"투자회사|해외자원개발|특별자산|리츠$|맥쿼리인프라|발해인프라|인프라투융자")


# ───────────────────────── 제목 정리 ─────────────────────────
def norm(report_nm):
    """'[기재정정]주요사항보고서(유상증자결정)' → ('주요사항보고서(유상증자결정)', ['기재정정'])"""
    s = report_nm or ""
    m = PREFIX_RE.match(s)
    pre = PREFIX_ONE.findall(m.group(0)) if m else []
    s = PREFIX_RE.sub("", s)
    return WS.sub(" ", s).strip(), pre


def key(report_nm):
    """매칭용 열쇠: 머리말을 떼고 공백을 모두 지운 제목."""
    return WS.sub("", norm(report_nm)[0])


def market_of(rcept_no):
    """거래소공시 접수번호 9번째 자리 → 시장. B · A001(금감원 접수, 0) 은 None."""
    return MARKET.get((rcept_no or "         ")[8])


def is_exchange(flr_nm):
    return (flr_nm or "") in EXCH


# ───────────────────────── 범주 ─────────────────────────
# (id, 군, 설명, 포함 정규식, 제외 정규식, 누가 낸 것만: None|'회사'|'거래소')
#   정규식은 key()(공백 없는 제목)에 건다.
#   군: 위험 = 사망을 미리 알릴 후보 신호 / 사망 = 비자발 상장폐지 표지 / 퇴장 = 사망 아닌 상장 종료 표지
#       해소 = 상장폐지 사유 해소 · 거래 재개 / 대조 = 건전 기업에도 흔한 공시(비교용) / 기타 = 방향이 섞인 구조 · 실적 공시
_C = [
    # ── 자금 조달 · 희석
    ("CB발행", "위험", "전환사채 발행결정", r"전환사채(권)?발행결[정의]", r"매수선택권|만기전|발행후|철회|취소|부결", None),
    ("BW발행", "위험", "신주인수권부사채 발행결정", r"신주인수권부사채(권)?발행결정", r"매수선택권|만기전|발행후|철회|취소|부결", None),
    ("EB발행", "위험", "교환사채 발행결정", r"교환사채(권)?발행결정", r"매수선택권|만기전|발행후|철회|취소|부결", None),
    ("사채재매각", "위험", "자기 CB · BW 매도(재매각)", r"자기(전환|신주인수권부|교환)사채매도결정", None, None),
    ("사채조기상환", "위험", "CB · BW 만기 전 취득(풋 행사 등)", r"발행후만기전사채취득|자기(전환|신주인수권부|교환)사채만기전취득", None, None),
    ("전환가액조정", "위험", "전환가액 · 행사가액 조정(리픽싱)", r"(전환|행사|교환)가액(ㆍ신주인수권행사가액ㆍ교환가액)?의조정", None, None),
    ("전환청구", "위험", "전환청구 · 신주인수권 · 교환청구 행사", r"(전환청구권|신주인수권|교환청구권)(ㆍ신주인수권ㆍ교환청구권)?행사(?!가액|기간|자)", r"매수선택권", None),
    ("유상증자", "위험", "유상증자결정(유무상 포함)", r"(?<!무상증자및)유(무)?상증자결정", r"철회|취소|부결|최종발행가액|발행가액결정", None),
    ("증자철회", "위험", "유상증자 · 사채발행 결정 철회 · 미발행", r"(유상증자|전환사채|신주인수권부사채|사채).*(철회|미발행)", None, None),
    ("감자", "위험", "감자결정", r"감자결정|자본감소결정", r"철회|취소|부결", "회사"),
    ("주식병합", "위험", "주식병합(액면병합) 결정", r"주식병합결정|액면병합결정", r"철회|취소|부결", None),
    ("무상증자", "위험", "무상증자결정", r"(?<!유)무상증자결정", r"철회|취소|부결", "회사"),
    # ── 지배구조
    ("최대주주변경", "위험", "최대주주변경", r"^최대주주변경(?!을수반)|최대주주등소유주식변동신고서\(최대주주변경시\)", None, None),
    ("경영권양수도", "위험", "최대주주변경을 수반하는 주식양수도 · 경영권 변경 계약", r"최대주주변경을수반하는주식양수도계약|경영권변경등에관한계약", r"해제|취소", None),
    ("주식담보_최대주주변경", "위험", "최대주주변경을 수반하는 주식담보제공 계약", r"최대주주변경을수반하는주식담보제공계약체결", None, None),
    ("대표이사변경", "위험", "대표이사(대표집행임원) 변경", r"대표이사변경|대표이사\(대표집행임원\)변경|대표집행임원변경", None, None),
    ("상호변경", "위험", "상호변경", r"상호변경", None, None),
    ("감사중도퇴임", "위험", "감사 · 감사위원 중도퇴임", r"감사ㆍ감사위원회위원중도퇴임|감사.{0,6}중도퇴임", None, None),
    ("본점이전", "위험", "본점소재지 변경", r"본점소재지변경", None, None),
    # ── 법률 · 사고
    ("횡령배임", "위험", "횡령 · 배임 혐의 발생 · 사실확인 · 진행 · 풍문", r"횡령|배임", None, None),
    ("회계위반", "위험", "회계처리기준 위반 · 분식 · 검찰고발", r"회계처리기준위반|분식", None, None),
    ("소송", "위험", "소송 등의 제기 · 판결(경영권분쟁 · 집단소송 포함)", r"소송등의(제기|판결)|증권관련집단소송", None, None),
    ("경영권분쟁", "위험", "경영권분쟁 소송", r"경영권분쟁", None, None),
    ("벌금제재", "위험", "벌금 · 제재금 · 가중벌점", r"벌금등의부과|제재금|가중벌점", None, None),
    # ── 부실
    ("회생절차", "위험", "회생절차 · 채권은행 관리절차(신청 · 개시 · 인가 · 폐지 · 종결)", r"회생절차|회생계획|채권은행등의관리절차|은행관리", None, None),
    ("파산신청", "위험", "파산신청(기각 · 취하 포함)", r"파산(선고)?신청", None, None),
    ("부도연체", "위험", "부도 · 대출원리금 연체 · 사채원리금 미지급", r"부도|원리금연체|원리금미지급|당좌거래정지", r"출자법인|피보증|계약회사", None),
    ("영업정지", "위험", "영업정지 · 생산중단 · 거래처와의 거래중단", r"영업정지|생산중단|거래중단", None, None),
    ("자본잠식", "위험", "자본잠식(50% · 전액) 사실 · 풍문", r"자본잠식|자본전액잠식", None, None),
    ("매출액미달", "위험", "매출액 미달(유가 50억 · 코스닥 30억 · 분기 3억 등)", r"매출액미달|매출액\d+억원?미만|매출액\d+억", None, None),
    ("감사의견비적정", "위험", "감사(검토)의견 부적정 · 의견거절 · 한정 · 비적정설", r"감사의견|검토의견부적정|검토\(감사\)의견부적정|의견거절|감사범위제한|외부감사의견", r"해소", None),
    ("보고서지연", "위험", "감사보고서 · 사업보고서 제출 지연 · 미제출 · 기한연장", r"감사보고서제출지연|감사보고서.{0,4}지연|보고서미제출|제출기한연장|외부감사인미선임", r"해소", None),
    ("손실상각", "위험", "파생상품 거래손실 · 채권 손상차손", r"파생상품거래손실|손상차손", None, None),
    # ── 거래소 조치(거래소 · 회사 모두)
    ("관리종목_사유", "위험", "관리종목 지정 사유 발생(회사 내부결산 자진신고 포함)", r"관리종목지정사유발생|내부결산시점관리종목지정|관리종목지정사유추가(?!우려)", r"우선주|해소|해제", None),
    ("관리종목_우려", "위험", "관리종목 지정 우려 · 예고(시총 · 주가 · 거래량 · 분산 미달 등)", r"관리종목.{0,6}우려|관리종목지정우려", r"우선주", None),
    ("투자주의환기", "위험", "투자주의 환기종목", r"투자주의환기종목", None, None),
    ("불성실_예고", "위험", "불성실공시법인 지정예고", r"불성실공시법인지정예고", None, None),
    ("불성실_지정", "위험", "불성실공시법인 지정(미지정 제외)", r"불성실공시법인지정(?!예고)", r"미지정", None),
    ("실질심사", "위험", "상장적격성 실질심사(사유발생 · 대상결정 · 추가)", r"상장적격성실질심사|상장폐지실질심사|실질심사", r"대상제외|미해당|사유해소|미진행", None),
    ("개선기간", "위험", "개선기간 부여 · 연장 · 개선계획", r"개선기간|개선계획", None, None),
    ("상폐우려", "위험", "상장폐지 우려 예고(시총 · SPAC 기한 등)", r"상장폐지.{0,4}우려|상장폐지사유발생우려", r"우선주|신주인수권", None),
    ("매매정지", "위험", "매매거래정지(사유별은 halt_reason)", r"매매거래정지(?!해제)(?!기간)|^매매거래정지및정지해제", r"정리매매", "거래소"),
    ("매매정지연장", "위험", "매매거래정지 기간변경(연장)", r"매매거래정지기간변경", None, "거래소"),
    ("조회공시_시황", "위험", "조회공시요구(현저한 시황변동 · 주가급등락)", r"^조회공시요구\(현저한시황변동\)(\(주가급[등락]\))?$", None, None),
    ("조회공시_풍문", "위험", "조회공시요구(풍문 또는 보도)", r"^조회공시요구\(풍문또는보도\)", r"에대한답변", None),
    ("시장경보", "위험", "투자주의 · 투자경고 · 투자위험 · 단기과열(DART 에는 드묾)", r"투자주의(?!환기)|투자경고|투자위험|단기과열", None, None),
    ("투자유의", "위험", "투자유의안내(거래소)", r"^투자유의안내", r"우선주|신주인수권", "거래소"),
    ("우회상장", "위험", "우회상장 심사 · 해당 여부", r"우회상장", None, None),
    # ── 돈의 흐름(작전주 꼴)
    ("타법인주식취득", "위험", "타법인 주식 및 출자증권 취득 · 양수 결정", r"타법인주식및출자증권(취득|양수)결정", None, None),
    ("금전대여", "위험", "금전대여결정", r"금전대여결정", None, None),
    ("채무보증", "위험", "타인에 대한 채무보증", r"타인(에대한|을위한)채무보증결정", None, None),
    ("담보제공", "위험", "타인에 대한 담보제공", r"타인(에대한|을위한)담보제공결정", None, None),
    ("단기차입", "위험", "단기차입금 증가결정", r"단기차입금증가결정", None, None),
    ("자산양수도", "위험", "유형 · 비유동자산 · 영업 양수도 · 중요한 자산양수도", r"(유형|비유동)자산(양수|양도|취득|처분)결정|영업(양수|양도)결정|중요한(자산|영업)양수도", None, None),
    ("풍문해명", "위험", "풍문 · 보도에 대한 해명(미확정 · 부인 …) · 최대주주 지분매각 추진설", r"풍문또는보도에대한해명|지분매각추진설", None, None),
    ("제3자배정", "위험", "제3자배정 유상증자 · CB 발행결과(제목에 제3자배정이 드러난 것만)", r"제3자배정", r"철회|미발행", None),
    ("임시주총", "위험", "임시주주총회 소집 · 결과", r"임시주주총회", None, None),
    ("공급계약해지", "위험", "단일판매 · 공급계약 해지", r"공급계약해지", None, None),
    ("지정자문인해지", "위험", "코넥스 지정자문인 선임계약 해지", r"지정자문인.{0,6}해지", None, None),
    ("유동성공급해지", "위험", "유동성공급계약 해지(코넥스)", r"유동성공급계약의?해지", None, None),
    # ── 사망 표지(비자발 상장폐지) — death_of 에서 사슬로 판정
    ("D_정리매매", "사망", "정리매매 개시 · 재개 · 보류(상장폐지 확정 뒤 마지막 매매)", r"정리매매", r"우선주|신주인수권|ELW|미진행", None),
    ("D_상폐결정", "사망", "거래소의 상장폐지 결정 안내(상장위원회 · 기업심사위원회 · 코스닥시장위원회)", r"상장폐지결정", r"우선주|신주인수권|이전상장|미진행", "거래소"),
    ("D_상폐사유", "사망", "거래소의 상장폐지 사유 발생 안내 · 매매정지(상장폐지사유발생) · 이의신청 접수", r"상장폐지사유발생|상장페지사유발생|^기타시장안내\(상장폐지관련|상장폐지기준해당|상장폐지절차|상장폐지.{0,6}이의신청|상장폐지사유발생및|코넥스주권상장폐지사유", r"우려|해소|미해당|미진행|우선주|신주인수권|자진|상장유예", "거래소"),
    ("D_가처분", "사망", "상장폐지결정 효력정지 · 금지 가처분(회사 · 거래소)", r"상장폐지.{0,8}(효력정지|가처분|무효)|상장폐지금지", None, None),
    ("D_파산선고", "사망", "파산선고", r"파산선고(?!신청)", r"취하|기각", None),
    ("D_해산", "사망", "그 회사 자신의 해산사유발생(B 주요사항보고서; SPAC · 펀드 이름이면 퇴장으로 본다)", r"^(주요사항보고서\()?해산사유발생", r"출자법인|피보증|계약회사|철회", None),
    ("D_심의결과", "사망", "(옛 서식) 상장위원회 · 상장공시위원회 개최 결과 · 개선기간 종료 뒤 상장폐지 여부 결정 안내", r"상장위원회개최결과|상장공시위원회.{0,6}결과|개선기간종료에따른상장폐지", None, "거래소"),
    ("D_회생폐지", "사망", "회생절차 폐지결정 · 신청", r"회생절차폐지", r"미진행", None),
    # ── 사망 아닌 퇴장 표지
    ("X_자진상폐", "퇴장", "자진 상장폐지(공개매수 · 상장폐지 승인 의안 · 상장폐지 신청서 · 장외매수 보호대책)", r"자진.{0,2}상장폐지|상장폐지승인을위한의안|상장폐지신청서|공개매수|상장폐지후투자자보호|주식분산미달에의한상장폐지", None, None),
    ("X_회사상폐결정", "퇴장", "회사가 직접 낸 '상장폐지결정'(자진 · 이전상장 · 펀드 해산)", r"^상장폐지결정", None, "회사"),
    ("X_이전상장", "퇴장", "이전상장(코넥스→코스닥 · 코스닥→유가)", r"이전상장결정|상장폐지결정\(.{0,8}이전상장|이전상장승인|이전상장을위한", r"철회|추진설|추진보도|유보|검토", None),
    ("X_합병", "퇴장", "회사합병결정 · 합병 매매정지 · 피흡수합병", r"합병결정|주권매매거래정지\((흡수|피흡수)?합병|피흡수합병|SPAC소멸합병", r"철회|분할합병|취소|부인", None),
    ("X_주식교환", "퇴장", "주식의 포괄적 교환 · 이전(완전자회사)", r"주식(의포괄적)?교환ㆍ이전결정|주식교환,이전|주식교환ㆍ이전|포괄적(주식)?교환|\(주식교환\)", r"철회", None),
    ("X_스팩", "퇴장", "기업인수목적회사(SPAC) 고유 공시", r"기업인수목적회사|SPAC", None, None),
    ("X_말소", "퇴장", "매매정지(주식의 병합 · 분할 등 전자등록 변경 · 말소)", r"전자등록변경,말소", None, "거래소"),
    # ── 해소 · 재개
    ("R_해소", "해소", "상장폐지 사유 해소 · 상장유지 결정 · 실질심사 대상 제외 · 기준 미해당", r"사유해소|사유미해당|상장유지|기준미해당|실질심사대상제외|실질심사미해당|사유일부해소", r"미해소", None),
    ("R_거래재개", "해소", "매매거래정지 해제(정리매매 · 상장폐지 관련 제외; 옛 서식 '정지및정지해제' 는 정지인지 해제인지 몰라 제외)", r"매매거래정지해제", r"정리매매|상장폐지(?!사유해소|기준미해당|사유미해당)", "거래소"),
    # ── 대조군(건전 기업에도 흔함)
    ("현금배당", "대조", "현금 · 현물 배당결정", r"현금ㆍ현물배당결정", None, None),
    ("자사주취득", "대조", "자기주식 취득 · 취득신탁 결정", r"자기주식취득(신탁계약체결)?결정", None, None),
    ("주식소각", "대조", "주식소각결정", r"주식소각결정", None, None),
    ("IR개최", "대조", "기업설명회(IR) 개최", r"기업설명회\(IR\)개최", None, None),
    ("공급계약", "대조", "단일판매 · 공급계약 체결", r"단일판매ㆍ공급계약체결", None, None),
    ("실적공정공시", "대조", "영업(잠정)실적 공정공시", r"영업\(잠정\)실적", None, None),
    ("사업보고서", "대조", "사업보고서(A001)", r"^사업보고서\(", None, None),
    ("지배구조보고서", "대조", "기업지배구조보고서 · 지속가능경영보고서 · 기업가치제고계획 · 공정거래 자율준수(큰 회사 공시)", r"기업지배구조보고서|지속가능경영보고서|기업가치제고계획|공정거래자율준수", None, None),
    ("신규시설투자", "대조", "신규시설투자", r"신규시설투자", None, None),
    # ── 기타(방향이 섞인 구조 · 실적 공시)
    ("손익구조변동", "기타", "매출액 또는 손익구조 30%(대규모 15%) 이상 변동", r"매출액또는손익구조\d+%", r"미만", None),
    ("자사주처분", "기타", "자기주식 처분결정", r"자기주식처분결정", None, None),
    ("회사분할", "기타", "회사분할 · 분할합병 결정", r"회사분할(합병)?결정|분할\(분할합병\)결정", None, None),
    ("소속부변경", "기타", "코스닥 소속부 변경(거래소)", r"^소속부변경", None, None),
    ("타법인주식처분", "기타", "타법인 주식 처분 · 양도", r"타법인주식및출자증권(처분|양도)결정", None, None),
]
CATEGORIES = [
    {"id": c[0], "군": c[1], "설명": c[2], "정규식": c[3], "제외": c[4], "제출자": c[5]} for c in _C
]
_RX = [(c[0], re.compile(c[3]), re.compile(c[4]) if c[4] else None, c[5]) for c in _C]
CAT_GROUP = {c[0]: c[1] for c in _C}
RISK = [c[0] for c in _C if c[1] == "위험"]

HALT_BUCKETS = [
    ("자진상폐", r"자진"),
    ("상장폐지사유", r"상장폐지|상장페지"),
    ("실질심사", r"실질심사"),
    ("관리종목", r"관리종목"),
    ("감사의견·보고서", r"감사의견|감사보고서|사업보고서|반기감사|외부감사인|정기보고서"),
    ("회생·파산·부도", r"회생|파산|부도|채권은행|은행관리|자본전액잠식|자본잠식"),
    ("불성실공시", r"불성실|공시번복|조회공시신고시한"),
    ("풍문·조회", r"풍문|조회"),
    ("투자자보호", r"투자자보호"),
    ("지정자문인", r"지정자문인"),
    ("구조변경", r"합병|분할합병|주식교환|이전|SPAC|우회상장|영업양수|영업양도|피흡수|분할\)|회사분할"),
    ("기술적", r"무상증자|병합|분할|감자|자본감소|구주권|전자등록|주식배당|이익소각"),
    ("중요내용공시", r"중요내용공시|단일판매|중요한영업정지|영업정지"),
]
_HB = [(b, re.compile(p)) for b, p in HALT_BUCKETS]


def halt_reason(report_nm):
    """'주권매매거래정지(상장폐지 사유발생)' → '상장폐지사유'. 매매정지 제목이 아니면 None."""
    k = key(report_nm)
    if not re.search(r"매매거래정지(?!해제)", k) or "정리매매" in k:
        return None
    inner = k.split("매매거래정지", 1)[1]
    for b, rx in _HB:
        if rx.search(inner):
            return b
    return "기타·사유없음"


@functools.lru_cache(maxsize=None)
def _classify_key(k, who):
    if SUB_RE.search(k):
        return ("자회사사항",)
    out = []
    for cid, rx, ex, need in _RX:
        if need and need != who:
            continue
        if rx.search(k) and not (ex and ex.search(k)):
            out.append(cid)
    return tuple(out)


def classify(report_nm, flr_nm=None, corp_name=None):
    """제목 하나 → 범주 id 튜플. flr_nm 이 거래소면 '거래소', 아니면 '회사' 로 본다(제출자 조건이 있는 범주용).
    자회사 · 종속회사의 주요경영사항은 ('자회사사항',) 하나만 돌려준다(그 회사 자신의 사건이 아니다)."""
    who = "거래소" if is_exchange(flr_nm) else "회사"
    return _classify_key(key(report_nm), who)


# ───────────────────────── 읽기 ─────────────────────────
def load_rows(kinds=KINDS, directory=DIR):
    """{corp_code: [row …]} — row 는 jsonl 한 줄 dict 에 'kind'(I · B · A001) 를 더한 것. rcept_dt · rcept_no 순."""
    rows = collections.defaultdict(list)
    seen = set()
    it = sys.intern
    for kd in kinds:
        for p in sorted(glob.glob(os.path.join(directory, "%s_*.jsonl" % kd))):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    x = json.loads(line)
                    if x["rcept_no"] in seen:
                        continue
                    seen.add(x["rcept_no"])
                    for f in ("corp_code", "corp_name", "stock_code", "corp_cls", "flr_nm", "report_nm", "rcept_dt"):
                        x[f] = it(x.get(f) or "")
                    x["kind"] = kd
                    rows[x["corp_code"]].append(x)
    for v in rows.values():
        v.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]))
    return dict(rows)


def _d(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _is_I(r):
    """거래소공시(I) 인가 — kind 가 있으면 그것, 없으면 접수번호 9번째 자리(0 이 아니면 거래소 접수)."""
    k = r.get("kind")
    if k:
        return k == "I"
    return (r.get("rcept_no") or "000000000")[8] != "0"


# ───────────────────────── 사망 판정 ─────────────────────────
DEATH_STRONG = ("D_정리매매", "D_상폐결정", "D_상폐사유", "D_가처분", "D_파산선고", "D_해산")
DEATH_WEAK = ("D_심의결과", "D_회생폐지")
EXIT_VOL = ("X_자진상폐", "X_회사상폐결정")
EXIT_MERGE = ("X_합병", "X_주식교환")
# 부실 표지 — 자진상폐 · 합병 표지가 있어도 이것이 함께 있으면 부실 퇴출로 본다
DISTRESS = ("감사의견비적정", "자본잠식", "회생절차", "부도연체", "파산신청", "D_파산선고", "횡령배임")
# 넓은 부실 표지 — 사망 표지 없이 끊긴 회사를 사망(추정)으로 볼 근거
DISTRESS_WIDE = DISTRESS + ("상폐우려", "실질심사", "개선기간", "관리종목_사유", "영업정지", "보고서지연", "매출액미달")
# 사슬이 이어지고 있다는 표지(사망 표지 + 개선기간 + 매매정지 기간 연장)
CONT = DEATH_STRONG + DEATH_WEAK + ("개선기간", "매매정지연장")
CHAIN_YEARS = 3          # 상장 종료 전 몇 해까지 사망 사슬을 거슬러 보나(개선기간 · 가처분 다툼이 2년을 넘기도 한다)
EPISODE_GAP = 540        # 사슬 표지 사이가 이만큼 넘게 비면 앞 사슬은 끝난(해소된) 것으로 보고 뒤 사슬만 센다
RESET_MIN = 60           # 상장 종료 전 이 날수 안의 '거래재개'는 정리매매 재개(옛 서식은 사유 없이 '정지해제')로 보고 해소로 치지 않는다
NEAR_DAYS = 400          # 합병 · 교환 · 이전상장 표지와 부실 표지를 찾는 범위(상장 종료 전)
VOL_DAYS = 3 * 366       # 자진상폐 표지를 찾는 범위(공개매수 → 분산 미달 → 상장폐지가 2년 넘게 걸리기도 한다: 알보젠코리아)
AFTER_DAYS = 120         # 상장 종료 뒤 몇 날까지의 공시를 함께 보나(정리매매 · 해산 · 파산선고가 뒤따른다)
STALE_DAYS = 200         # corp_cls 가 없을 때: 자료 끝보다 이만큼 앞서 거래소공시가 끊겼으면 상장 종료로 본다
GUESS_DAYS = 180         # 사망(추정)의 사망일 = 상장 종료 전 이 날수 안의 가장 이른 부실 표지
LEFT_EDGE = "20130401"   # 첫사유일이 이보다 이르면 좌측절단(2012 년 이전에 시작된 사슬일 수 있다)


def _tag(rows, ref, back_days, after_days):
    """ref 날짜 기준 [ref-back, ref+after] 의 공시에 범주를 붙인다 → [(row, cats, ref-날짜 일수)]"""
    out = []
    for r in rows:
        dd = (ref - _d(r["rcept_dt"])).days
        if dd > back_days or dd < -after_days:
            continue
        c = classify(r["report_nm"], r.get("flr_nm"))
        if c and c != ("자회사사항",):
            out.append((r, c, dd))
    return out


def _chain(tagged, reset_min):
    """마지막 사망 사슬: ① 마지막 해소 · 거래재개(ref 전 reset_min 일 넘게 앞선 것) 뒤만,
    ② 사슬 표지(CONT) 사이가 EPISODE_GAP 넘게 빈 곳에서 끊어 마지막 토막만, ③ 마지막 표지가 ref 보다 EPISODE_GAP 넘게
    앞서면 사슬 없음.  돌려줌: (마지막 토막, 해소 뒤 전체)"""
    reset_i = -1
    for i, (r, c, dd) in enumerate(tagged):
        if dd >= reset_min and ("R_해소" in c or "R_거래재개" in c):
            reset_i = i
    after = tagged[reset_i + 1:]
    cont = [(i, r, dd) for i, (r, c, dd) in enumerate(after) if set(c) & set(CONT)]
    if not cont:
        return [], after
    start = cont[0][0]
    for (i0, r0, d0), (i1, r1, d1) in zip(cont, cont[1:]):
        if d0 - d1 > EPISODE_GAP:
            start = i1
    if cont[-1][2] > EPISODE_GAP:
        return [], after
    return after[start:], after


def _ev(r, c):
    return "%s %s %s" % (r["rcept_dt"], "/".join(c), norm(r["report_nm"])[0][:60])


def death_of(rows, data_end=None):
    """회사 하나의 공시 rows(rcept_dt 순, jsonl dict 에 kind 가 있으면 쓰고 없으면 접수번호로 거래소공시를 가린다) → 사망 판정.

    돌려주는 dict
      사망       True(사망 · 사망(약) · 사망(추정)) / False / None(불명 · 상폐절차중 · 자료없음)
      사망일     'YYYYMMDD' — 마지막 사망 사슬에서 가장 이른 결정적 사건(거래소의 상장폐지 사유 발생 · 상장폐지 결정 ·
                  정리매매 · 상장폐지 가처분 · 파산선고 · 해산)의 rcept_dt.  해소 · 거래재개 뒤, 그리고 EPISODE_GAP 넘게
                  빈 곳 뒤의 마지막 토막만 본다(한 번 살아난 상장폐지 사유는 세지 않는다).
      첫사유일   해소 뒤 CHAIN_YEARS 안의 가장 이른 사망 표지(토막을 나누지 않은 것) — 참고용
      유형       상장중 · 상폐절차중 · 사망 · 사망(약) · 사망(추정) · 합병소멸 · 주식교환 · 자진상폐 · 이전상장 · 스팩 · 리츠펀드 · 불명 · 자료없음
      상장종료   마지막 거래소공시(I) 날짜(지금 상장 중이면 None)
      시장       상장 종료 직전(또는 지금) 거래소공시 접수번호로 본 시장(유가 · 코스닥 · 코넥스)
      정리매매일 · 최종정지일(사망 사슬 안의 첫 매매거래정지) · 근거(판정에 쓴 공시 몇 개)

    규칙(순서대로)
      0. 거래소공시(유가 · 코스닥 · 코넥스 접수)가 없으면 자료없음.
      1. 상장 중인가: corp_cls 가 Y/K/N 이면 상장 중(지금 상장사는 모두 2026-03 이후 거래소공시가 있다).
         corp_cls 가 비었으면 보조 규칙 '공시 끊김': 마지막 거래소공시가 자료 끝보다 STALE_DAYS 넘게 앞서면 상장 종료.
         상장 중이어도 자료 끝 기준 사슬에 거래소의 상장폐지 사유 · 결정 · 정리매매 · 가처분이 해소 없이 남아 있으면 상폐절차중
         (정리매매 보류 · 개선기간 · 이의신청 — 사망=None, 사망일 자리에 절차 시작일).
      2. 이름이 SPAC → 스팩(사망 아님: 합병이든 기한 만료 해산이든 신탁금이 돌아간다).
      3. 상장 종료 전 VOL_DAYS 안에 자진상폐 표지(자진 상장폐지 · 공개매수 · 상장폐지 승인 의안 · 상장폐지 신청서 ·
         장외매수 보호대책 · 회사가 낸 상장폐지결정)가 있고, 그 뒤로 부실 표지(DISTRESS)가 없으면 자진상폐(펀드 이름이면 리츠펀드).
      4. 이전상장 표지만 있고 사망 표지가 없으면 이전상장.
      5. 마지막 사망 사슬에 강한 표지가 있으면 사망. 다만
         - 펀드 이름: 정리매매 · 거래소 상장폐지 사유/결정이 있고 부실 표지도 있어야 사망, 아니면 리츠펀드(만기 · 해산).
         - 합병 · 교환 표지가 NEAR_DAYS 안에 있고 정리매매도 부실 표지도 없거나, 강한 표지가 해산뿐이면 합병소멸/주식교환.
      6. 합병 · 주식교환 표지 → 합병소멸 / 주식교환.  7. 펀드 이름 → 리츠펀드.
      8. 약한 표지(옛 서식 상장위원회 결과 · 개선기간 종료 뒤 결정 안내 · 회생절차 폐지)만 있으면 사망(약).
      9. 보조 규칙: 표지 없이 끊겼지만 NEAR_DAYS 안에 넓은 부실 표지(DISTRESS_WIDE)가 있으면 사망(추정),
         사망일 = 상장 종료 전 GUESS_DAYS 안의 가장 이른 부실 표지(없으면 상장 종료일).
         (2013~2016 유가증권시장 퇴출은 거래소가 '투자유의안내' 로만 알려 강한 표지가 없다: 한일건설 · 경남기업 · 삼환기업 …)
     10. 그 밖에는 불명(끊겼지만 제목만으로 까닭을 모름) — 사망으로 세지 않는다.
    """
    res = {"사망": None, "사망일": None, "첫사유일": None, "유형": "자료없음", "상장종료": None, "시장": None,
           "정리매매일": None, "최종정지일": None, "좌측절단": False, "근거": []}
    if not rows:
        return res
    name = rows[-1].get("corp_name") or ""
    cls = rows[-1].get("corp_cls")
    eqI = [r for r in rows if _is_I(r) and market_of(r.get("rcept_no")) in ("유가", "코스닥", "코넥스")]
    if not eqI:
        return res
    last = eqI[-1]["rcept_dt"]
    res["시장"] = collections.Counter(market_of(r["rcept_no"]) for r in eqI[-15:]).most_common(1)[0][0]
    if data_end is None:
        data_end = max(r["rcept_dt"] for r in rows)
    if cls in ("Y", "K", "N"):
        listed = True
    elif cls == "E":
        listed = False
    else:
        listed = (_d(data_end) - _d(last)).days <= STALE_DAYS
    spac = bool(SPAC_NAME.search(name))
    fund = bool(FUND_NAME.search(name)) and "자기관리" not in name   # 자기관리 리츠는 영업회사처럼 죽는다

    if listed:
        res.update(사망=False, 유형="상장중")
        if spac:
            return res
        tg = _tag(rows, _d(data_end), CHAIN_YEARS * 366, 0)
        chain, _ = _chain(tg, 0)
        dec = [(r, c) for r, c, dd in chain
               if set(c) & {"D_정리매매", "D_상폐결정", "D_상폐사유", "D_가처분", "D_파산선고"}]
        if dec:
            res.update(사망=None, 유형="상폐절차중", 사망일=dec[0][0]["rcept_dt"], 근거=[_ev(r, c) for r, c in dec[:5]])
        return res

    res["상장종료"] = last
    L = _d(last)
    tagged = _tag(rows, L, CHAIN_YEARS * 366, AFTER_DAYS)

    if spac:
        sub = "합병" if any(set(c) & set(EXIT_MERGE) for r, c, dd in tagged if dd <= NEAR_DAYS) else "해산·기타"
        res.update(사망=False, 유형="스팩", 근거=["SPAC 이름 · 끝: " + sub])
        return res

    chain, after_reset = _chain(tagged, RESET_MIN)
    strong = [(r, c) for r, c, dd in chain if set(c) & set(DEATH_STRONG)]
    weak = [(r, c) for r, c, dd in chain if set(c) & set(DEATH_WEAK)]
    allmark = [(r, c) for r, c, dd in after_reset if set(c) & (set(DEATH_STRONG) | set(DEATH_WEAK))]
    vol = [(r, c) for r, c, dd in tagged if dd <= VOL_DAYS and set(c) & set(EXIT_VOL)
           and not ("X_회사상폐결정" in c and "X_이전상장" in c)]
    trans = [(r, c) for r, c, dd in tagged if dd <= NEAR_DAYS and "X_이전상장" in c]
    merge = [(r, c) for r, c, dd in tagged if dd <= NEAR_DAYS and set(c) & set(EXIT_MERGE)]
    distress_near = [(r, c) for r, c, dd in tagged if 0 <= dd <= NEAR_DAYS and set(c) & set(DISTRESS)
                     and not (fund and set(c) <= {"자본잠식", "매출액미달"})]

    def done(kind, dead, evs, date=None):
        res.update(사망=dead, 유형=kind, 근거=[_ev(r, c) for r, c in evs[:6]])
        if dead:
            first = min(evs, key=lambda x: x[0]["rcept_dt"])
            res["사망일"] = date or first[0]["rcept_dt"]
            res["첫사유일"] = min([r["rcept_dt"] for r, c in allmark] + [res["사망일"]])
            jm = [r for r, c, dd in tagged if "D_정리매매" in c and dd <= 366]
            res["정리매매일"] = jm[0]["rcept_dt"] if jm else None
            # 최종정지일: 사망일 전 120일 ~ 사망일 사이의 거래소 매매거래정지(뒤에 거래재개가 없던 것) 가운데 가장 이른 것,
            # 없으면 사슬 안 첫 정지. 옛 서식 '매매거래정지및정지해제' 는 정지인지 몰라 쓰지 않는다.
            D0 = _d(res["사망일"])
            hs = [(r, c) for r, c, dd in tagged if set(c) & {"매매정지", "매매정지연장"}
                  and not key(r["report_nm"]).startswith("매매거래정지및정지해제") and 0 <= (D0 - _d(r["rcept_dt"])).days <= 120]
            res_after = [r["rcept_dt"] for r, c, dd in tagged if "R_거래재개" in c and r["rcept_dt"] <= res["사망일"]]
            hs = [r for r, c in hs if not any(x > r["rcept_dt"] for x in res_after)]
            hs = hs or [r for r, c, dd in chain if set(c) & {"매매정지", "매매정지연장"}
                        and not key(r["report_nm"]).startswith("매매거래정지및정지해제")]
            res["최종정지일"] = hs[0]["rcept_dt"] if hs else None
            res["좌측절단"] = res["첫사유일"] < LEFT_EDGE      # 사슬이 자료 시작(2013-01) 무렵에 걸려 그 앞을 못 본다
        return res

    if vol:
        v0 = min(r["rcept_dt"] for r, c in vol)
        bad = [(r, c) for r, c, dd in tagged if r["rcept_dt"] >= v0 and set(c) & set(DISTRESS)
               and not (fund and set(c) <= {"자본잠식", "매출액미달"})]
        if not bad:
            return done("리츠펀드" if fund else "자진상폐", False, vol)
    if trans and not strong:
        return done("이전상장", False, trans)
    if strong:
        cats = set().union(*[set(c) for r, c in strong]) & set(DEATH_STRONG)
        exch_death = bool(cats & {"D_정리매매", "D_상폐사유", "D_상폐결정"})
        if fund and not (exch_death and distress_near):
            return done("리츠펀드", False, strong)
        if merge and (cats <= {"D_해산"} or (not distress_near and not exch_death)):
            kind = "주식교환" if all("X_합병" not in c for r, c in merge) else "합병소멸"
            return done(kind, False, merge)
        return done("사망", True, strong + weak)
    if merge:
        kind = "주식교환" if all("X_합병" not in c for r, c in merge) else "합병소멸"
        return done(kind, False, merge)
    if fund:
        return done("리츠펀드", False, [(r, c) for r, c, dd in tagged[-3:]])
    if weak:
        return done("사망(약)", True, weak)
    guess = [(r, c, dd) for r, c, dd in tagged if 0 <= dd <= NEAR_DAYS and set(c) & set(DISTRESS_WIDE)]
    if guess:
        g2 = [(r, c) for r, c, dd in guess if dd <= GUESS_DAYS]
        date = g2[0][0]["rcept_dt"] if g2 else last
        return done("사망(추정)", True, [(r, c) for r, c, dd in guess][-6:], date=date)
    return done("불명", None, [(r, c) for r, c, dd in tagged[-5:]])


# ───────────────────────── 점검 · 출력 ─────────────────────────
def judge_all(rows=None, data_end=None):
    """{corp_code: death_of 결과} — 종목코드가 있고 거래소공시가 있는 회사만."""
    if rows is None:
        rows = load_rows()
    if data_end is None:
        data_end = max(r["rcept_dt"] for v in rows.values() for r in v)
    out = {}
    for cc, v in rows.items():
        if not (v[-1].get("stock_code") or "").strip():
            continue
        d = death_of(v, data_end)
        if d["유형"] != "자료없음":
            out[cc] = d
    return out


def timeline(rows, end=None, n=25, after=5):
    """사람이 읽을 제목 흐름: end(기본 마지막 거래소공시) 앞 n 개 + 뒤 after 개."""
    if end is None:
        eqI = [r for r in rows if _is_I(r)]
        end = eqI[-1]["rcept_dt"] if eqI else rows[-1]["rcept_dt"]
    before = [r for r in rows if r["rcept_dt"] <= end][-n:]
    aft = [r for r in rows if r["rcept_dt"] > end][:after]
    out = []
    for r in before + aft:
        c = classify(r["report_nm"], r.get("flr_nm"))
        who = "거" if is_exchange(r.get("flr_nm")) else "회"
        out.append("%s %-4s %s %s  {%s}" % (r["rcept_dt"], r.get("kind", ""), who, norm(r["report_nm"])[0][:70],
                                             ",".join(c)))
    return out


def _risk_count(rows, upto=None):
    """위험 범주 건수(정정 · 첨부 머리말이 붙은 재제출은 뺀다)."""
    c = collections.Counter()
    for r in rows:
        if upto and r["rcept_dt"] > upto:
            break
        if norm(r["report_nm"])[1]:
            continue
        for cid in classify(r["report_nm"], r.get("flr_nm")):
            if CAT_GROUP.get(cid) == "위험":
                c[cid] += 1
    return c


HEAVY = ("횡령배임", "관리종목_사유", "실질심사", "불성실_지정", "감사의견비적정", "자본잠식", "회생절차",
         "최대주주변경", "CB발행", "BW발행", "유상증자", "감자", "개선기간", "매매정지")

# 사람이 표본을 읽고 남긴 오분류 점검 기록(2026-10-05). 고친 것은 위 규칙에 반영돼 있다.
CHECKS = {
    "표본_사망30": "build_report 의 seed=20261005 무작위 30곳(점검표본_사망30)의 제목 흐름을 읽음. 30곳 모두 비자발 상장폐지 흐름"
                 "(감사의견 거절 · 자본잠식 → 거래소 '상장폐지 사유 발생' → 이의신청 · 개선기간 → 상장폐지 결정 → 정리매매 · 가처분 기각, "
                 "또는 코넥스 지정자문인 계약 해지 → 상장폐지 절차). 오분류 0. 사망일은 사슬의 첫 결정적 사건이라 정리매매보다 늦지 않다.",
    "표본_비사망위험30": "상장이 끝난 비사망 15곳(위험 신호 상위 40 중 무작위): 합병 · 주식교환(에이치디현대인프라코어 · 루트로닉 · 코오롱머티리얼 · "
                     "녹십자셀 · 메리츠증권 · 우리종합금융 · 롯데푸드 · 코리아센터 · 카이노스메드(코넥스→스팩합병)), 자진상폐(오스템임플란트 · "
                     "맘스터치앤컴퍼니 · 케이씨더블류), 펀드(코리아퍼시픽01호 · 하이골드오션12호 · 코크렙15호) — 제목 흐름과 판정이 맞음. "
                     "지금 상장 중 15곳(CSA 코스믹 · 케이에스피 · 국일제지 · 에이전트AI · 딥커머스 · 대산F&B · 우리로 · 이엠앤아이 · 오늘이엔엠 · "
                     "KS인더스트리 · 디모아 · 에코글로우 · THE E&M · 한국정밀기계 · 상지건설)은 모두 지금 K 이고 CB · 유상증자 · 임시주총 · 주식병합이 "
                     "잦은 '작전주 꼴' 이지만 사망 사슬이 없거나 해소됨(대산F&B 2026-07 기업심사위원회 상장유지 결정 → 거래재개, 오늘이엔엠 2018 정리매매 → "
                     "가처분으로 생존). 오분류 0, 단 펀드 3곳은 남은 애매함 참조.",
    "고친것": [
        "회사가 직접 낸 '상장폐지결정'(셀트리온 2018 · 카카오 2017 이전상장, 자진 상장폐지, 선박펀드 해산)을 사망 표지에서 뺌 → 거래소(유가증권시장본부 · 코스닥시장본부 · 코넥스시장)가 낸 것만 D_상폐결정.",
        "옛 서식 '매매거래정지및정지해제(…)' 를 거래재개(해소)로 세어 한진해운 사슬이 끊겼다 → 해소에서 뺌(정지인지 해제인지 제목만으로 모름).",
        "상장 종료 직전의 사유 없는 '주권매매거래정지해제' 는 정리매매 재개인데 해소로 세어 제이앤유글로벌 · 우성아이비 · 에스와이이노베이션이 불명이었다 → 상장 종료 전 60일 안의 거래재개는 해소로 안 침(RESET_MIN).",
        "'개선기간 종료에 따른 상장폐지 여부 결정 안내' 가 강한 표지(D_상폐결정)에 걸렸다(에스비엠) → 결과가 상장유지일 수도 있어 약한 표지(D_심의결과)로.",
        "자진 상장폐지 뒤 거래소가 내는 '상장폐지결정 · 정리매매' 안내 때문에 SBI핀테크솔루션즈가 사망 → 자진 표지가 있으면 그 뒤 부실 표지(감사의견 · 자본잠식 · 회생 · 부도 · 파산 · 횡령)가 있을 때만 사망.",
        "공개매수(2017) → 분산 미달 → 주식교환 → '투자유의안내(상장폐지기준 해당)'(2019) 인 알보젠코리아가 사망 → 자진 표지를 찾는 범위를 상장 종료 전 3년으로(VOL_DAYS).",
        "인수자 쪽 합병결정이 있던 헬스커넥트(2024 코스닥시장위원회 상장폐지 결정)가 합병소멸로 → 거래소 상장폐지 사유 · 결정 · 정리매매가 있으면 합병보다 사망 우선.",
        "2013~2018 유가증권시장 퇴출(한일건설 · 다함이텍 · 케이조선 · 화인자산관리 · 동양건설산업 · 삼환기업 · 경남기업 · 플랜텍 · 넥솔론 · 중국원양자원 · 성지건설 · 현대페인트)과 코넥스 부도 퇴출(에이치앤아이 · 금오하이텍), 조은저축은행은 거래소가 '투자유의안내 · 기타시장안내' 로만 알려 강한 표지가 없어 불명 → 보조 규칙 사망(추정): 끊기기 전 400일 안 넓은 부실 표지, 사망일 = 끊기기 전 180일 안 첫 부실 표지.",
        "해외자원개발 · 특별자산 투자회사(투자유의안내 뒤 끊김)가 불명 → 펀드 이름 규칙에 '투자회사|해외자원개발|특별자산' 추가. 자기관리 리츠(에프지엔개발전문 · 이코리아 · 에이 · 제이케이리버스톤)는 영업회사처럼 상장폐지되므로 펀드 예외에서 뺌(사망).",
        "레드로버 · 아리온테크놀로지 · 신일건업처럼 상장폐지 사유가 해소된 뒤 몇 해 지나 다시 죽은 회사의 사망일이 옛 사유로 잡혔다 → 사슬 표지(사망 표지 · 개선기간 · 정지기간 변경) 사이가 540일 넘게 비면 뒤 토막만(EPISODE_GAP). 아리온 2021→2024-04-01, 신일건업 2013→2015(사망(추정)). 첫사유일 필드에 옛 날짜를 남김.",
        "'상장폐지 및 정리매매 절차 미진행'(신라에스지 2026-09 코넥스 이전) 이 D_정리매매에 걸림 → '미진행' 제외.",
        "지금 상장 중인데 상장폐지 결정 · 정리매매 보류(가처분) · 이의신청 · 개선기간 중인 80곳을 '상폐절차중'(사망=None)으로 따로 둠 — 2025~2026 사망 수가 낮아 보이는 까닭.",
    ],
    "알려진사례": "한진해운(117930) 사망 2017-02-02(회생절차폐지결정 → 02-17 파산선고 → 02-20 해산사유발생 → 02-22 거래소 투자유의안내). "
              "웅진에너지(103130) 사망 2020-03-30(거래소 '상장폐지관련' → 04-21 이의신청 → 05-15 상장공시위원회 결과; 그 뒤 사업보고서는 2022 까지 계속 — 거래소공시만으로 끊김을 잰 까닭). "
              "금빛(045890) 사망 2021-03-23(상장폐지 사유 발생 → 이의신청 · 개선기간 → 횡령 · 회생 → 12-07 파산선고 · 해산 · 정리매매).",
    "이전상장": "셀트리온(068270, 2018-02 회사 상장폐지결정 = 코스닥→유가) · 카카오(035720, 2017-07) 는 지금 Y → 상장중. "
            "이전상장 표지가 있는 회사 95곳: 상장중 74 · 상폐절차중 5 · 자진상폐 2 · 이전상장 2 · 합병소멸 1 · 사망 11. 사망 11곳은 모두 "
            "이전 표지 3년 이상 뒤 이전한 시장(또는 이전을 못 한 코넥스)에서 따로 죽은 것(테라셈 2014 이전 → 2022 사망 등) — 이전상장이 사망으로 잡힌 것은 0.",
    "연도별_상식선": "사망일 기준 2013~2025 해마다 10~36곳(유가+코스닥만 8~33곳, 코넥스 0~9곳) — '해마다 수십 곳' 범위. 상장종료 기준으로 보면 2019 년이 7곳(유가+코스닥 3곳)으로 낮은데, "
                "2019-03 부터 감사의견 거절에 개선기간 1년을 주는 규정이 시행돼 2019 사유 회사들이 2020 에 퇴출됐기 때문(사망일 기준 2019 은 20곳). "
                "2025~2026 은 정리매매 보류 · 가처분 · 개선기간으로 아직 상장(Y/K/N) 인 상폐절차중 78곳(2025 시작 29 · 2026 시작 49)을 더해야 실제 규모(2025 50 · 2026 56)에 가깝다. "
                "2013 은 2012 년에 시작된 사슬이 섞여(좌측절단 25곳) 조금 부풀었다.",
    "남은애매함": [
        "펀드 부실: 코리아퍼시픽01~04호(2017, 한진해운 용선 부도 → 자본잠식 → 상장폐지 → 2020 해산) · 코리아퍼시픽05~07호(2013) · 하이골드오션12호(2021 반기 의견거절) · 코크렙15호 리츠는 '만기'가 아니라 부실로 끝났지만 펀드라 리츠펀드(비사망)로 둠.",
        "사망일은 '사슬의 첫 결정적 사건' 이라 거래정지가 2~3년 이어진 회사(광림 · 케이에이치 계열 · 에스에이치엔엘 · 레드로버 · 유한코스메틱 …)는 정리매매보다 2년 넘게 앞선다(사망일→상장종료 중앙값 173일, 90% 728일, 최대 1091일). 정리매매일 · 상장종료 · 최종정지일 · 첫사유일을 함께 남겼다.",
        "레드로버: 2019-11 상폐 사유 → 개선기간(2020-11 이행내역서) → 2022-05 다시 상폐 사유. 사이가 529일이라 한 사슬(사망일 2019-11-04)로 남았는데 2020~2021 에 거래가 재개됐는지 제목만으로 모름.",
        "좌측절단: 자료가 2013-01 부터라 그 전에 시작된 사슬(중국고섬 2011 거래정지 → 2013 상장폐지, 2013 초 사망 33곳 다수)은 사망일이 실제보다 늦다 — 좌측절단=True 로 표시.",
        "케이씨더블류(2015): 최대주주 공개매수 → 영업양도 → 실질심사 → 기업심사위원회 상장폐지 결정 → 장외매수. 사실상 자진 퇴장이라 자진상폐로 둠.",
        "코넥스 사망(지정자문인 계약 해지 · 감사의견 거절)을 사망에 넣었다. 유가 · 코스닥만 보려면 시장 필드로 거른다.",
        "사망(추정) 16곳은 제목에 상장폐지가 직접 안 나온다(2013~2018 유가 · 코넥스). 사망일은 끊기기 전 180일 안 첫 부실 표지라 몇 주~몇 달 오차가 있다(현대페인트 2016-06-22 등).",
        "일정실업(008500, 2026-06): 거래소 '투자유의안내' 두 번 뒤 끊김, 부실 표지 없음 → 불명(사망으로 안 셈).",
        "DART 거래소공시에는 KIND 시장조치 원문(관리종목 지정 · 투자경고/위험 지정 · '상장폐지' 그 자체)이 없다. 관리종목은 '관리종목지정사유발생 · 우려' 와 회사의 '내부결산시점…사유발생' 으로만, 시장경보(투자주의 · 경고 · 위험 · 단기과열)는 34건뿐이라 신호로 쓰기 어렵다.",
        "B(주요사항보고서)에는 '유상증자결정' 이 제3자배정인지 드러나지 않는다 — '제3자배정' 범주는 I 의 '증권발행결과(…제3자배정…)' 제목에서만 잡힌다.",
    ],
}


def build_report(seed=20261005):
    t0 = dt.datetime.now()
    rows = load_rows()
    data_end = max(r["rcept_dt"] for v in rows.values() for r in v)

    # 1) 빈도표 — 종류별 · 머리말 뗀 제목
    freq = {k: collections.Counter() for k in KINDS}
    prefix = collections.Counter()
    cat_rows = collections.Counter()
    cat_rows_orig = collections.Counter()
    cat_corps = collections.defaultdict(set)
    cat_titles = collections.defaultdict(collections.Counter)
    halt = collections.Counter()
    halt_ex = collections.defaultdict(collections.Counter)
    n_rows = 0
    for cc, v in rows.items():
        for r in v:
            n_rows += 1
            t, pre = norm(r["report_nm"])
            for p in pre:
                prefix[p] += 1
            freq[r["kind"]][t] += 1
            cs = classify(r["report_nm"], r.get("flr_nm"))
            for cid in cs:
                cat_rows[cid] += 1
                if not pre:
                    cat_rows_orig[cid] += 1
                if r.get("stock_code", "").strip():
                    cat_corps[cid].add(cc)
                cat_titles[cid][t] += 1
            hb = halt_reason(r["report_nm"]) if "매매정지" in cs else None
            if hb:
                halt[hb] += 1
                halt_ex[hb][WS.sub("", t)] += 1
    unclassified = collections.Counter()
    for kd in KINDS:
        for t, n in freq[kd].items():
            if not _classify_key(WS.sub("", t), "회사") and not _classify_key(WS.sub("", t), "거래소"):
                unclassified[t] += n

    # 2) 회사별 사망 판정 — 종목코드가 있고 거래소공시가 있는 회사
    verdict = judge_all(rows, data_end)
    by_type = collections.Counter(d["유형"] for d in verdict.values())
    deaths = {cc: d for cc, d in verdict.items() if d["사망"]}
    pending = {cc: d for cc, d in verdict.items() if d["유형"] == "상폐절차중"}
    per_year = collections.Counter(d["사망일"][:4] for d in deaths.values())
    per_year_mk = collections.defaultdict(collections.Counter)
    per_year_kind = collections.defaultdict(collections.Counter)
    per_end_mk = collections.defaultdict(collections.Counter)
    for d in deaths.values():
        per_year_mk[d["사망일"][:4]][d["시장"]] += 1
        per_year_kind[d["사망일"][:4]][d["유형"]] += 1
        per_end_mk[d["상장종료"][:4]][d["시장"]] += 1
    pend_year = collections.defaultdict(collections.Counter)
    for d in pending.values():
        pend_year[d["사망일"][:4]][d["시장"]] += 1
    exits_year = collections.defaultdict(collections.Counter)
    for d in verdict.values():
        if d["상장종료"]:
            exits_year[d["상장종료"][:4]][d["유형"]] += 1
    lags = sorted((_d(d["상장종료"]) - _d(d["사망일"])).days for d in deaths.values())
    q = lambda p: lags[min(len(lags) - 1, int(len(lags) * p))] if lags else None

    # 3) 점검 표본
    rnd = random.Random(seed)
    dead_list = sorted(deaths)
    sample_dead = rnd.sample(dead_list, min(30, len(dead_list)))
    ended_risky, listed_risky = [], []
    for cc, d in verdict.items():
        if d["사망"] or d["유형"] in ("상폐절차중", "스팩"):
            continue
        rc = _risk_count(rows[cc])
        score = sum(rc[k] for k in HEAVY if k not in ("CB발행", "BW발행", "유상증자", "최대주주변경", "매매정지")) * 3 + \
            sum(rc[k] for k in ("CB발행", "BW발행", "유상증자", "최대주주변경", "매매정지"))
        (ended_risky if d["상장종료"] else listed_risky).append((score, cc))
    ended_risky.sort(reverse=True)
    listed_risky.sort(reverse=True)
    # 상장이 끝났는데 사망이 아닌 회사(합병 · 자진 · 펀드 · 불명) 중 위험 신호 상위 40 에서 15, 지금 상장 중 상위 100 에서 15
    sample_alive = rnd.sample([cc for s, cc in ended_risky[:40]], min(15, len(ended_risky))) + \
        rnd.sample([cc for s, cc in listed_risky[:100]], min(15, len(listed_risky)))

    FIELDS = ("사망", "유형", "사망일", "첫사유일", "상장종료", "시장", "정리매매일", "최종정지일", "좌측절단")

    def card(cc):
        v = rows[cc]
        d = verdict[cc]
        return {"corp_code": cc, "회사": v[-1]["corp_name"], "종목코드": v[-1]["stock_code"], "지금분류": v[-1]["corp_cls"],
                "판정": {k: d[k] for k in FIELDS}, "근거": d["근거"], "위험신호수": dict(_risk_count(v).most_common(8)),
                "제목흐름": timeline(v, d["상장종료"], n=18, after=3)}

    known = {}
    for sc, nm in (("117930", "한진해운"), ("103130", "웅진에너지"), ("045890", "금빛"),
                   ("068270", "셀트리온"), ("035720", "카카오")):
        for cc, v in rows.items():
            if v[-1].get("stock_code") == sc:
                known[nm] = card(cc) if cc in verdict else {"없음": True}

    # 이전상장 표지가 한 번이라도 있는 회사(코넥스→코스닥 · 코스닥→유가) — 사망으로 잡히면 안 된다
    trans_last = {}
    for cc in verdict:
        ds = [r["rcept_dt"] for r in rows[cc] if "X_이전상장" in classify(r["report_nm"], r.get("flr_nm"))]
        if ds:
            trans_last[cc] = ds[-1]
    trans_cc = sorted(trans_last)
    trans_types = collections.Counter(verdict[cc]["유형"] for cc in trans_cc)
    # 이전상장 뒤 몇 해 지나 이전한 시장에서 죽은 것은 정상. 이전상장 표지 1년 안의 사망만 의심으로 본다.
    trans_dead = [[rows[cc][-1]["corp_name"], verdict[cc]["유형"], "이전표지 " + trans_last[cc], "사망일 " + verdict[cc]["사망일"],
                   "의심" if (_d(verdict[cc]["사망일"]) - _d(trans_last[cc])).days < 365 else "이전 뒤 따로 사망"]
                  for cc in trans_cc if verdict[cc]["사망"]]

    # 예전 표본(2026-10-01 시총 상위 1000, 종목.txt)과 비교 — 결과로 고른 표본이라 사망이 하나도 없어야 한다
    old_codes = set()
    old_path = os.path.join(BASE, "종목.txt")
    if os.path.exists(old_path):
        with open(old_path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*([0-9A-Z]{6})\b", line)
                if m:
                    old_codes.add(m.group(1))
    sc2cc = {rows[cc][-1]["stock_code"]: cc for cc in verdict}
    old_types = collections.Counter(verdict[sc2cc[s]]["유형"] if s in sc2cc else "판정대상아님" for s in old_codes)
    old_pending = [rows[sc2cc[s]][-1]["corp_name"] for s in sorted(old_codes) if s in sc2cc and verdict[sc2cc[s]]["유형"] == "상폐절차중"]

    def row_of(cc, d):
        v = rows[cc]
        return [d["사망일"], cc, v[-1]["corp_name"], v[-1]["stock_code"], d["시장"], d["유형"], d["첫사유일"],
                d["정리매매일"], d["최종정지일"], d["상장종료"], d["좌측절단"]]

    rep = {
        "만든때": t0.strftime("%Y-%m-%d %H:%M"),
        "재현": {
            "전체": "python \"G:/내 드라이브/Claude/주식/기업추적/도구/공시분류.py\"   — 이 파일을 다시 만든다(DART 호출 0, 이미 받은 jsonl 만 읽음, 약 30초)",
            "한 회사": "python \"G:/내 드라이브/Claude/주식/기업추적/도구/공시분류.py\" 117930 103130 045890 068270 035720   — 판정 · 근거 · 제목 흐름",
            "파이썬에서": "import 공시분류 as K; rows = K.load_rows(); V = K.judge_all(rows); K.classify('[기재정정]주요사항보고서(전환사채권발행결정)')",
            "표본": "점검표본 두 묶음은 random.Random(20261005) 로 뽑는다 — 다시 돌려도 같은 회사",
        },
        "자료": {"행수(접수번호 중복 제거)": n_rows, "회사수(corp_code)": len(rows), "자료끝": data_end,
                 "종류별 행수": {k: sum(freq[k].values()) for k in KINDS},
                 "종류별 서로 다른 제목수(머리말 뗀 뒤)": {k: len(freq[k]) for k in KINDS},
                 "머리말 건수": dict(prefix.most_common()),
                 "판정 대상(종목코드 + 유가·코스닥·코넥스 거래소공시가 있는 회사)": len(verdict),
                 "시장 구분": "거래소공시 접수번호 9번째 자리 8=유가 9=코스닥 6=코넥스 7=채권 — 거래소 제출자(유가증권시장본부 5,436 · 코스닥시장본부 26,387 · 코넥스시장 1,749건)와 100% 일치"},
        "빈도표_상위": {k: freq[k].most_common(150 if k == "I" else 120) for k in KINDS},
        "범주": [dict(c, 행수=cat_rows[c["id"]], 행수_원본만=cat_rows_orig[c["id"]], 회사수=len(cat_corps[c["id"]]),
                     예시=cat_titles[c["id"]].most_common(8)) for c in CATEGORIES],
        "매매정지_사유별": [{"묶음": b, "행수": halt[b], "예시": halt_ex[b].most_common(6)} for b, _ in HALT_BUCKETS + [("기타·사유없음", "")]],
        "분류안된제목_상위": unclassified.most_common(60),
        "분류안된_행비율": round(sum(unclassified.values()) / n_rows, 4),
        "판정": {"유형별 회사수": dict(by_type.most_common()),
                 "사망 회사수(사망+사망(약)+사망(추정))": len(deaths),
                 "연도별 사망수(사망일 기준)": dict(sorted(per_year.items())),
                 "연도별 사망수_시장별(사망일 기준)": {y: dict(c) for y, c in sorted(per_year_mk.items())},
                 "연도별 사망수_유형별(사망일 기준)": {y: dict(c) for y, c in sorted(per_year_kind.items())},
                 "연도별 사망수_시장별(상장종료 기준)": {y: dict(c) for y, c in sorted(per_end_mk.items())},
                 "상폐절차중_시작연도별(지금 상장 중)": {y: dict(c) for y, c in sorted(pend_year.items())},
                 "연도별 상장종료_유형별": {y: dict(c) for y, c in sorted(exits_year.items())},
                 "사망일→상장종료 일수": {"10%": q(0.1), "25%": q(0.25), "중앙값": q(0.5), "75%": q(0.75), "90%": q(0.9),
                                     "최대": lags[-1] if lags else None},
                 "좌측절단 사망수": sum(1 for d in deaths.values() if d["좌측절단"])},
        "자동점검": {"이전상장표지_회사수": len(trans_cc), "이전상장표지_회사판정": dict(trans_types.most_common()),
                   "이전상장표지인데_사망": trans_dead,
                   "예전표본(종목.txt)_판정분포": dict(old_types.most_common()),
                   "예전표본에 든 상폐절차중": old_pending,
                   "예전표본이 놓친 사망": "%d곳 전부(상장이 끝난 회사는 2026-10-01 시총 순위에 없다)" % len(deaths)},
        "알려진사례": known,
        "오분류점검": CHECKS,
        "점검표본_사망30": [card(cc) for cc in sample_dead],
        "점검표본_비사망위험30": [card(cc) for cc in sample_alive],
        "사망목록_열": ["사망일", "corp_code", "회사", "종목코드", "시장", "유형", "첫사유일", "정리매매일", "최종정지일", "상장종료", "좌측절단"],
        "사망목록": sorted(row_of(cc, d) for cc, d in deaths.items()),
        "상폐절차중목록": sorted(row_of(cc, d) for cc, d in pending.items()),
        "비사망_상장종료목록": sorted([[d["상장종료"], cc, rows[cc][-1]["corp_name"], rows[cc][-1]["stock_code"], d["시장"], d["유형"]]
                                for cc, d in verdict.items() if d["상장종료"] and not d["사망"]]),
    }
    return rep, rows, verdict


def main(argv):
    if argv:
        rows = load_rows()
        data_end = max(r["rcept_dt"] for v in rows.values() for r in v)
        for q in argv:
            ccs = [cc for cc, v in rows.items() if v[-1].get("stock_code") == q or cc == q or v[-1].get("corp_name") == q]
            for cc in ccs:
                d = death_of(rows[cc], data_end)
                print("=====", cc, rows[cc][-1]["corp_name"], rows[cc][-1]["stock_code"], rows[cc][-1]["corp_cls"])
                print({k: d[k] for k in ("사망", "유형", "사망일", "첫사유일", "상장종료", "시장", "정리매매일", "최종정지일", "좌측절단")})
                for e in d["근거"]:
                    print("  근거:", e)
                for line in timeline(rows[cc], d["상장종료"], n=30):
                    print("  ", line)
        return 0
    rep, rows, verdict = build_report()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    print("저장:", OUT)
    print("유형별:", rep["판정"]["유형별 회사수"])
    print("연도별 사망(사망일):", rep["판정"]["연도별 사망수(사망일 기준)"])
    print("상폐절차중(시작연도):", rep["판정"]["상폐절차중_시작연도별(지금 상장 중)"])
    print("이전상장 표지 회사 판정:", rep["자동점검"]["이전상장표지_회사판정"], "사망:", rep["자동점검"]["이전상장표지인데_사망"])
    print("분류안된 행비율:", rep["분류안된_행비율"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
