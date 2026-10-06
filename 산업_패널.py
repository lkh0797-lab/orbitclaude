# -*- coding: utf-8 -*-
"""
산업 성장률 — 회사별 실적 패널과 연결 구조 (2026-10-06)

섹터 합계(산업.py)가 쓰는 회사 단위 자료를 .cache/산업/panel.json 한 파일로 만든다.

  실적      .cache/fin 의 DART 전체재무제표 원장(fnlttSinglAcntAll)을 직접 읽는다. 연결(CFS) → 별도(OFS) →
            .cache/본문재무(보고서 본문 표, 본문재무.VERSION 이 맞을 때만). 매출 · 영업이익 · 지배순이익
            (지배 귀속 줄이 없으면 당기순이익 − 비지배). 줄 키는 재무.py 의 _row_key · NUM_PREFIX · num 그대로.
            분기는 3개월 단독. 4분기 = 사업보고서 연간 − 3분기 누적(같은 연결/별도끼리, 누적 칸이 비면 1~3분기 단독 합).
            연결 회사인데 1~3분기 원장이 없거나 별도(OFS)뿐이면 수집 보고서 본문의 연결 손익 표를 본문재무의 표 읽기로
            읽는다(src '본문', .cache/산업/_parse/body/). 그 분기 보고서가 연결 재무제표를 내지 않았으면(종속회사 없음)
            별도 원장을 그대로 쓰고(src '단독'), 둘 다 아니면 그 분기는 내지 않는다(별도 분기는 기준이 다르다).
            외화로 낸 원장(두산밥캣 2023~ USD, 중국 · 일본 상장사)은 ECOS 731Y004 월평균 매매기준율로 원화 환산
            (.cache/산업/fx_monthly.json, 2026-06 이 빠졌을 때만 통화마다 1콜).
  짧은 해   (첨부) 재무제표 머리의 '제 N 기 YYYY년 MM월 DD일부터 … 까지'가 12개월이 안 되는 해(분할 · 설립 첫해 ·
            결산월 변경). 본문이 없으면 원장 기수 '제 1 기' + 1분기 보고서 없음.
  연결 구조 상장 모회사가 상장 자회사를 연결하는가 — 수집해 둔 보고서 본문(기업추적_수집)만 읽는다(네트워크 없음).
            2021 사업보고서부터 「XII. 상세표 > 1. 연결대상 종속회사 현황(상세)」, 그 앞은 「I. 회사의 개요 >
            연결대상 종속회사 개황」(같은 7칸 표). 둘 다 없으면 연결재무제표 주석의 종속기업 표.
            2026 은 2026-06 반기보고서 상세표. 이름 → 종목코드는 '(329180)' 직접 표기, 그해 각 상장사 재무제표 머리의
            국문 명칭(대우조선해양 → 한화오션 같은 옛 이름), 지금 이름(종목.txt · CORPCODE.xml), 별칭표(ALIAS) 순.
            edges[Y] = Y−1 말과 Y 말 둘 다 연결(한 해 내내 연결)인 (모회사, 자회사). 맨 위 상장 자회사만 남긴다
            (P → C → G 면 P → G 는 C 안에 들어 있으므로 뺀다). 자회사 매출 > 모회사 매출 × 1.02 인 해와
            모회사 실적이 별도(OFS)인 해는 뺀다(뺄 것이 없거나 어긋남). 한 기말만 목록을 못 읽었거나 이름을 놓쳤는데
            앞뒤 기말이 연결이면 메운다. 이름만 같은 다른 회사(두산의 광고회사 '㈜한컴' ≠ 상장사 한컴)는 표의 자산총액과
            상장사 자산, 타법인출자 표의 상장 여부와 첫 거래일로 걸러 낸다(notes '이름 충돌').
  지분      최근 사업보고서 「XII. 상세표 > 3. 타법인출자 현황(상세)」의 기말 지분율 — 상장 종속 전부와 20% 이상 관계사,
            그리고 비금융 사업회사가 가진 5~20% 상장 지분(kind 관계 — 기아 > 현대모비스 17%; 산업.py 가 시총에서 뺀다).
            edges 쌍인데 직접 지분 행이 없으면 간선 마지막 해 보고서의 타법인출자 표 전체(상장여부 칸 없는 '종속기업
            투자내역' 표 포함, 이름 앞부분 일치)를 다시 보고, 그래도 없으면 간접 보유(indirect) — 연결 주석 종속기업 표의
            보유 회사(via)가 P 의 직접 출자 회사면 실효 지분 = P→보유 × 보유→자식, 아니면 stake null.

2026-10-06 검토 반영(리뷰가 찾은 다섯 가지)
  1. 매출 별칭 — Revenue 태그 줄이 없는 비금융 회사는 이름이 매출 총액인 줄('영업수익' · '매출액' · '수익' · '수익(매출액)')을
     매출로 본다(카카오 · 스카이라이프 · 사람인 · 칩스앤미디어 · 대웅은 '영업수익'에 GrossProfit 태그, 티엘비 2025 는
     RevenueFromSaleOfGoodsProduct, 동진쎄미켐 본문 표는 '수익'). 금융업 KSIC 회사는 이자 · 보험 · 수수료 수익 줄이 없을 때만.
     그래도 영업이익만 있고 매출이 없는 섹터 관련 회사-기간은 notes 에 적는다.
  2. 단위 오기 — 1~3분기 보고서 하나가 통째로 천 · 백만 배 어긋나면(누적 매출이 연간 비례의 30배 밖, 영업이익도 같은 배수)
     그 보고서 값을 고친다(동성케미컬 2017 반기 ×10^-6, JW생명과학 2021 반기 ×10^-3, SK네트웍스 2017 3분기 ×10^6). 도출한
     분기 매출이 연간/4 의 3배를 넘거나 네 분기 합이 연간과 50% 넘게 다르면 천 · 백만 배로 맞춰 보고, 안 맞으면 연간보다 큰
     분기(분할 · 재작성 전 기준)거나 합이 어긋날 때만 뺀다 — 연간 안에 드는 몰린 매출(바이오 기술료)은 남긴다.
     3개월 칸에 누적을 적은 반기 · 3분기(DL 2024)는 '누적 − 직전 누적'으로 뗀다.
  3. 연결 재무제표가 없던 분기 — 연결 회사의 1~3분기에 별도(OFS) 원장만 있고 본문 연결 표도 없을 때, 그 분기 보고서가
     '연결재무제표 해당사항 없음'(종속회사 없음)이면 별도 원장을 그대로 쓴다 — src '단독'(범위가 연결과 같아 연결로 본다,
     4분기 = 연간 연결 − 단독 9개월). 한화엔진 2025 1~3분기(2025-12-16 첫 종속회사).
  4. 지분 — 위 '지분' 참조. 타법인출자 이름 꼬리('-종속기업' · '(연결)' · '(국내 - 상장)' · '주1),주2)')를 떼어 코스모화학 >
     코스모신소재 · 미코 > 코미코 · 후성 > 한텍 · 뉴파워프라즈마 > 도우인시스가, 상장여부 칸 없는 표로 한국알콜 > 퓨릿이,
     별도 주석 종속기업 투자 표로 드림텍 > 나무가가, 실효 지분으로 LS > 가온전선(LS전선 경유)이 잡힌다. 지분을 못 찾는
     간선 쌍(NHN > NHN KCP · HD현대 > HD건설기계 · POSCO홀딩스 > 포스코엠텍 등 — 보고서가 지분을 행렬표로만 적음)은
     stake null · indirect.
  5. 재작성된 앞 분기 — Y 사업보고서가 Y−1 연간을 3% 넘게 재작성했는데 Y 3분기 보고서는 재작성 전 기준이면 4분기 =
     연간 − 재작성 9개월(Y+1 3분기 보고서의 전기 누적). 그 보고서가 아직 없으면 Y+1 1분기 · 반기 보고서의 전기 값을 보고,
     처음 낸 Y 분기 값과 같으면(전기 연간만 고친 오류 수정 등) 4분기를 그대로 두고, 다르면 4분기 매출 · 영업이익을 비운다
     (삼성바이오로직스 2025 4분기 — 연간은 바이오에피스 제외, 1~3분기는 포함; CJ제일제당 · 삼양홀딩스 2025 도 같은 사정).
     지배순이익은 자기 전기 값이 고쳐졌을 때만 같은 규칙. 손본 4분기는 notes '재작성 … 4분기' 에 적는다.

한계
  · 연결 여부는 연말(2026 은 6월 말) 목록으로만 본다. 해 중간에 편입 · 제외된 해는 그해 간선에서 빠진다
    (그해에는 모회사 안에 몇 달치가 겹친다). 예외는 근거를 본문으로 확인한 FULL_YEAR 표뿐(한국타이어앤테크놀로지 →
    한온시스템 2025: 2025-01-03 지배력 획득).
  · 비12월 결산 회사의 'YYYYQn' 은 회계연도 기준 분기다(fy_end_month 참조). 연결 구조는 12월 결산 모회사만 본다.
  · 짧은 해(partial_years)의 분기도 첫 분기는 3개월이 안 될 수 있다 — 그해 분기는 증가율 비교에서 빼는 것이 맞다.
  · 원장이 없는 2015~2021 기간은 '채우기' 명령으로만 DART 를 부른다(상한 5,000콜, 한도 초과 020 이면 멈춘다).
    2026-10-06 첫 채우기(5,000콜)는 분기 · 반기를 별도(OFS) 먼저 물어 연결 회사의 2015~2021 분기 다수가 OFS 원장으로만
    받혔다 — 빌드는 그 분기를 본문 연결 손익으로 바꾸거나 빼고, 다음 '채우기'는 연결 회사면 CFS 를 먼저 묻고
    OFS 만 있는 기간의 CFS 도 받는다.
    기본 빌드는 캐시만 읽는다(환율 캐시가 모자랄 때의 ECOS 몇 콜만 예외). 인증키와 키가 든 주소는 화면 · 로그 · 파일에 남기지 않는다.
  · 분기 값은 그 분기 보고서에 처음 낸 값이다. 뒤에 재작성(중단영업 재분류 등)되면 1~3분기와 3분기 누적의 기준이
    달라 4분기가 차이를 떠안는다(notes 에 1% 넘게 어긋나는 회사-연도 목록). 연간 보고서가 재작성 기준인데 3분기 누적이
    재작성 전이면 4분기는 재작성 9개월로 떼거나 비운다(위 5). 1~3분기 자체는 재작성 전 값 그대로다.

  python 산업_패널.py              빌드(.cache/산업/panel.json)
  python 산업_패널.py 점검         검증표 · 연도별 커버리지(만들어 둔 panel.json 으로)
  python 산업_패널.py 채우기 [N]   빠진 2015~2021 원장을 DART 에서 받는다(N 콜까지, 기본 5000)
"""
import os
import re
import sys
import json
import html
import time
import hashlib
import threading
import collections
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import 재무 as FIN                                  # noqa: E402  순수 함수(_row_key · NUM_PREFIX · num)와 fetch_statement

CACHE = os.path.join(BASE, ".cache")
FIN_DIR = os.path.join(CACHE, "fin")
BODY_DIR = os.path.join(CACHE, "본문재무")
DATA = os.path.join(BASE, "기업추적_수집")
OUT_DIR = os.path.join(CACHE, "산업")
PARSE_DIR = os.path.join(OUT_DIR, "_parse")
PANEL = os.path.join(OUT_DIR, "panel.json")
FIN_SIG = os.path.join(PARSE_DIR, "_fin_sig.json")      # 회사별 원장 파일 서명(이름 · 크기 · 수정시각)
FIN_CACHE = os.path.join(PARSE_DIR, "_fin.json")         # 회사별 원장 읽은 결과 — 서명이 같으면 다시 읽지 않는다

V = 1                     # panel.json 형식
PARSE_V = 5               # 보고서 본문 파서가 바뀌면 올린다(rcept 캐시를 새로 만든다)
FIN_V = 9                 # 원장 읽기 규칙이 바뀌면 올린다(회사별 실적을 다시 읽는다)
YEARS = list(range(2015, 2027))
LAST = (2026, 2)          # 마지막 분기 — 12월 결산은 이 뒤 기간을 읽지도 묻지도 않는다
REPRT = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
ENDS = ["%d-12" % y for y in range(2014, 2026)] + ["2026-06"]      # 연결 목록을 보는 기말
THREADS = 16
FILL_CAP = 5000           # 채우기 DART 호출 상한
FILL_YEARS = range(2015, 2022)


# ---------------------------------------------------------------- 공통
def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _save(path, obj, indent=None):
    """임시 파일에 쓰고 바꿔 끼운다(쓰다 끊겨도 앞 파일이 남는다)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":"))
    os.replace(tmp, path)


def _read(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit) if limit else fh.read()
    except Exception:
        return ""


def _int(v):
    return None if v is None else int(round(v))


def _sectors():
    """산업_섹터(섹터 정의 — 읽기만). 없으면 None(그때는 KSIC 로만 비금융을 가린다)."""
    try:
        import 산업_섹터
        return 산업_섹터
    except Exception:
        return None


# 회사 이름 맞추기 — 서버.py _norm_corp 와 같은 규칙(영문 글자 → 한글 읽기, (주) · 공백 · 구두점 제거)
_LATIN_KO = {"a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프", "g": "지", "h": "에이치", "i": "아이",
             "j": "제이", "k": "케이", "l": "엘", "m": "엠", "n": "엔", "o": "오", "p": "피", "q": "큐", "r": "알",
             "s": "에스", "t": "티", "u": "유", "v": "브이", "w": "더블유", "x": "엑스", "y": "와이", "z": "지"}


def norm(nm):
    n = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|\s+|[·ㆍ\.,&]", "", nm or "").lower()
    return re.sub(r"[a-z]", lambda m: _LATIN_KO[m.group(0)], n)


_OLD_RX = re.compile(r"\(\s*(?:구|舊|前|옛)\s*[,:：.]?\s*([^)]*)\)")


def clean(nm):
    """표 속 회사 이름 손질 — 각주 '(*1)' '(주1)' '*2' · '(구, …)' · 끝의 '과 그 종속기업'을 뗀다."""
    n = html.unescape(nm or "")
    n = _OLD_RX.sub("", n)
    n = re.sub(r"\(\s*\*+\s*[\d,\s]*\)|\(\s*주\s*\d+(?:\s*[,~\-]\s*\d+)*\s*\)|\*+\s*\d*(?:\s*,\s*\d+)*|\(\s*\d{1,2}\s*\)"
               r"|\(\s*[a-z]\s*\)|\s주\s*\d+\)", "", n)
    n = re.sub(r"\s*(?:와|과|및)\s*(?:그\s*)?종속\s*(?:기업|회사)(?:들)?\s*$|\s*외\s*\d+\s*개사\s*$", "", n)
    # 타법인출자 표의 꼬리 — '넥센타이어(상장)' 'JW중외제약보통주(유가증권시장상장)' '(주)아모레퍼시픽(보통주)'
    n = re.sub(r"\(\s*(?:보통주|비?상장|(?:유가증권|코스닥|코넥스)\s*(?:시장)?\s*상장|KOSPI|KOSDAQ)\s*\)", "", n)
    n = re.sub(r"\s*보통주\s*$", "", n)
    return n.strip(" -:")


# ---------------------------------------------------------------- 유니버스 · 식별자
def universe():
    """종목.txt → ([{code, rank, name, market, cap(원)}], 스냅샷 'YYYYMMDD')"""
    rows, snap = [], None
    for ln in open(os.path.join(BASE, "종목.txt"), encoding="utf-8"):
        m = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", ln)
        if ln.startswith("#") and m and not snap:
            snap = "".join(m.groups())
        m = re.match(r"^([0-9][0-9A-Z]{5})\s*#\s*(\d+)위\s+(.*?)\s+\((KOSPI|KOSDAQ),\s*시총\s*([\d,]+)억\)", ln)
        if m:
            rows.append({"code": m.group(1), "rank": int(m.group(2)), "name": m.group(3), "market": m.group(4),
                         "cap": float(m.group(5).replace(",", "")) * 1e8})
    return rows, snap


def corpcodes():
    """CORPCODE.xml 상장사 → {종목코드: (corp_code, 이름)}"""
    t = open(os.path.join(CACHE, "CORPCODE.xml"), "rb").read().decode("utf-8", "replace")
    out = {}
    for m in re.finditer(r"<list>(.*?)</list>", t, re.S):
        b = m.group(1)
        s = re.search(r"<stock_code>(.*?)</stock_code>", b, re.S)
        c = re.search(r"<corp_code>(.*?)</corp_code>", b, re.S)
        n = re.search(r"<corp_name>(.*?)</corp_name>", b, re.S)
        if s and c and s.group(1).strip():
            out[s.group(1).strip()] = (c.group(1).strip(), html.unescape(n.group(1).strip()) if n else "")
    return out


def report_index():
    """.cache/색인.json → {종목코드: {"dir": 회사 폴더, "reports": [{stamp, label, tag, rcept, dir, sections}]}}"""
    d = _load(os.path.join(CACHE, "색인.json")) or {}
    return {c["code"]: c for c in d.get("companies") or []}


def fy_month(ent):
    """사업보고서 기준월(가장 많은 달). 수집본이 없으면 12."""
    ms = collections.Counter(r["stamp"][5:7] for r in (ent or {}).get("reports") or [] if r["label"] == "사업보고서")
    return int(ms.most_common(1)[0][0]) if ms else 12


def _has_cfs(rep):
    """사업보고서에 연결재무제표가 붙어 있는가(색인의 장 제목으로). 분기 · 반기보고서는 감사보고서 첨부가 없어
    이 방법으로는 모른다 — cons_year 참조."""
    return any("연결재무제표" in re.sub(r"\s+", "", s["title"]) and "내부회계" not in s["title"] for s in rep["sections"])


def cons_year(ent, y):
    """그해(또는 앞뒤 해) 사업보고서에 연결재무제표가 붙어 있으면 연결 회사로 본다."""
    for yy in (y, y - 1, y + 1):
        for r in (ent or {}).get("reports") or []:
            if r["label"] == "사업보고서" and r["stamp"] == "%d-12" % yy and _has_cfs(r):
                return True
    return False


def qdirs(ent):
    """{(해, 보고서코드): [분기 · 반기보고서 폴더(최근 접수 먼저)]} — 본문 연결 손익을 읽을 때 쓴다(12월 결산)."""
    out = collections.defaultdict(list)
    kind = {"03": ("11013", "분기보고서"), "06": ("11012", "반기보고서"), "09": ("11014", "분기보고서")}
    for r in sorted((ent or {}).get("reports") or [], key=lambda r: r["rcept"], reverse=True):
        k = kind.get(r["stamp"][5:7])
        if k and r["label"] == k[1]:
            out[(int(r["stamp"][:4]), k[0])].append(os.path.join(DATA, ent["dir"], r["dir"]))
    return dict(out)


# ---------------------------------------------------------------- 실적(원장)
IS_KEYS = {"t:Revenue": "rev", "t:OperatingIncomeLoss": "op", "t:ProfitLossFromOperatingActivities": "op",
           "t:ProfitLoss": "ni", "t:ProfitLossAttributableToOwnersOfParent": "ni_own",
           "t:ProfitLossAttributableToNoncontrollingInterests": "ni_nci"}
OWN_NAME = re.compile(r"^지배(?:기업|회사)(?:의)?\s*(?:소유주|주주)(?:지분|귀속)?")
FIELDS = ("rev", "op", "ni_own")
FAM = {"CFS": "연결", "본문": "연결", "OFS": "별도", "단독": "연결"}   # 본문재무 캐시는 연결 재무제표만 읽는다(_CFS 파일)
# '단독' = 연결 회사(그해 사업보고서가 연결)인데 그 분기엔 종속회사가 없어 별도만 낸 분기의 별도 원장 — 범위가 연결과 같아
# 연결로 본다(산업.py src() 는 'OFS' 로 시작하는 것만 별도로 본다). 그해 네 분기가 한 기준(연결)이 된다.
# 매출 줄 별칭(비금융) — 태그가 Revenue 가 아니어도 이름이 매출 총액이면 매출로 본다. 카카오 · 스카이라이프 · 사람인 ·
# 칩스앤미디어 · 대웅은 '영업수익'에 ifrs-full_GrossProfit 을, 티엘비 2025 는 '매출액'에 dart_RevenueFromSaleOfGoodsProduct 를
# 붙였고, 동진쎄미켐 본문 표는 '수익' 한 줄이다(재무.py 이름 태그는 '수익'을 안 본다). _merge_name 을 거친 이름에 맞춘다.
REV_ALIAS = re.compile(r"^(?:계속영업)?(?:매출액?|영업수익|수익)(?:\((?:매출액?|영업수익|수익)\))?$|^수익\(매출액?\)$"
                       r"|^영업수익\([^()]{1,20}\)$|^[^()]{2,20}\(영업수익\)$|^매출액?및지분법손익$")
# 금융업(KSIC 64 · 65 · 66) 손익계산서 표지 — 이자 · 보험 · 수수료 수익 줄이 있으면 '영업수익'은 이자 · 평가이익까지 더한 총액이라
# 매출 별칭을 쓰지 않는다(지주 64992 가운데 사업 지주는 이 줄이 없어 별칭을 쓴다)
FIN_MARK_KEYS = {"t:RevenueFromInterest", "t:InterestRevenueExpense", "t:InsuranceRevenue", "t:OperatingIncomeInsurance",
                 "t:InsuranceRevenueExpense", "t:InvestmentIncome", "t:InterestRevenueCalculatedUsingEffectiveInterestMethod",
                 "t:FeeAndCommissionIncomeExpense", "t:RevenueFromFeeAndCommissionIncome", "t:FeeAndCommissionIncome"}
FIN_MARK_NAME = re.compile(r"^(?:순)?이자(?:수익|이익|손익)$|^보험(?:영업)?수익|^보험서비스|^(?:순)?수수료(?:수익|이익|손익)$|^순보험")


def _pick(rows, fin=False):
    """한 보고서 원장 → ({필드: (3개월 · 연간 값, 누적 값)}, 당기 기수 이름, 통화, {필드: (전기 값, 전기 누적)}, 매출 별칭 줄 이름).
    전기 값 = 사업보고서 frmtrm_amount(전기 연간) · 분기 frmtrm_q_amount(전년 같은 분기 3개월), 전기 누적 = frmtrm_add_amount
    — 뒤 보고서가 앞 기간을 재작성했는지(중단영업 등) 볼 때 쓴다. fin = 금융업 KSIC 회사(매출 별칭은 손익계산서에
    이자 · 보험 · 수수료 수익 줄이 없을 때만)."""
    out, nm_period, cur, prior = {}, None, None, {}
    alias, finmark, alias_nm = [], False, None
    has_is = any(r.get("sj_div") == "IS" for r in rows)
    for r in rows:
        sj = r.get("sj_div")
        if sj == "BS" and "assets" not in out:     # 자산총계 — 패널에는 안 넣고 이름 충돌 검사에만 쓴다
            nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
            if FIN._row_key(r.get("account_id"), nm).split("|")[0] == "t:Assets":
                out["assets"] = (FIN.num(r.get("thstrm_amount")), None)
            continue
        if sj not in ("IS", "CIS"):
            continue
        if sj == "CIS" and has_is:                  # 손익계산서가 따로 있으면 포괄손익 줄은 안 본다(총포괄 귀속분 섞임)
            continue
        nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
        if not nm or "우선주" in nm:
            continue
        if nm_period is None and r.get("thstrm_nm"):
            nm_period = r.get("thstrm_nm")
        if cur is None and r.get("currency"):
            cur = r.get("currency").strip().upper()
        key = FIN._row_key(r.get("account_id"), nm).split("|")[0]
        f = IS_KEYS.get(key)
        if f is None and key.startswith("nm:") and OWN_NAME.search(nm) and "포괄" not in nm:
            f = "ni_own"                            # 태그 없이 '지배기업 소유주지분'만 적은 줄
        mn = FIN._merge_name(nm)
        if fin and (key in FIN_MARK_KEYS or FIN_MARK_NAME.search(mn)):
            finmark = True
        if f is None and REV_ALIAS.search(mn):
            alias.append(r)
        if f and f not in out:
            out[f] = (FIN.num(r.get("thstrm_amount")), FIN.num(r.get("thstrm_add_amount")))
            prior[f] = (FIN.num(r.get("frmtrm_amount") if r.get("frmtrm_q_amount") is None else r.get("frmtrm_q_amount")),
                        FIN.num(r.get("frmtrm_add_amount")))
    if "rev" not in out and alias and not finmark:  # 매출 태그 줄이 없다 — 이름이 매출 총액인 줄 가운데 가장 큰 것
        best = None
        for r in alias:
            a, c = FIN.num(r.get("thstrm_amount")), FIN.num(r.get("thstrm_add_amount"))
            v = a if a is not None else c
            if v is not None and v >= 0 and (best is None or v > best[0]):
                best = (v, r, a, c)
        if best:
            r = best[1]
            out["rev"] = (best[2], best[3])
            prior["rev"] = (FIN.num(r.get("frmtrm_amount") if r.get("frmtrm_q_amount") is None else r.get("frmtrm_q_amount")),
                            FIN.num(r.get("frmtrm_add_amount")))
            alias_nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
    if "ni_own" not in out and "ni" in out:        # 지배 귀속 줄이 없다 — 당기순이익 − 비지배(별도는 비지배가 없다)
        n, nc = out["ni"], out.get("ni_nci", (None, None))
        out["ni_own"] = (None if n[0] is None else n[0] - (nc[0] or 0), None if n[1] is None else n[1] - (nc[1] or 0))
        pn, pc = prior.get("ni", (None, None)), prior.get("ni_nci", (None, None))
        prior["ni_own"] = (None if pn[0] is None else pn[0] - (pc[0] or 0), None if pn[1] is None else pn[1] - (pc[1] or 0))
    return out, nm_period, cur, prior, alias_nm


def _months(y, q, fy, cum=False):
    """회계연도 y 의 q 분기(3개월, cum=True 면 1분기부터 누적, q=4 는 연간 12개월)가 걸친 달 'YYYYMM' 목록."""
    a = 1 if (cum or q == 4) else q
    m0, y0 = fy % 12 + 1, (y if fy == 12 else y - 1)     # 회계연도 첫 달
    out = []
    for k in range((a - 1) * 3, q * 3):
        mm = m0 + k
        out.append("%d%02d" % (y0 + (mm - 1) // 12, (mm - 1) % 12 + 1))
    return out


def _to_krw(vals, cur, fx, y, q, fy):
    """외화로 낸 원장(두산밥캣 2023~ USD, 중국 · 일본 상장사) → 원화. 그 기간 월평균 매매기준율의 평균을 곱한다
    (손익은 평균환율로 환산하는 IFRS 표시통화 환산과 같은 방식). 환율이 없는 달이 있으면 그 값은 비운다."""
    rate = (fx or {}).get(cur) or {}

    def conv(v, months):
        rs = [rate.get(m) for m in months]
        return v * sum(rs) / len(rs) if v is not None and rs and None not in rs else None
    m3, mc = _months(y, q, fy), _months(y, q, fy, cum=True)
    return {f: (conv(a, m3), conv(c, mc)) for f, (a, c) in vals.items()}


def _ledger(corp, y, reprt, F, B):
    """(출처, 원장 줄) — CFS → OFS → 본문 캐시. 값이 있는 파일만. 없으면 (None, None) — 네트워크로 가지 않는다."""
    for div in ("CFS", "OFS"):
        fn = "%s_%s_%s_%s.json" % (corp, y, reprt, div)
        if fn in F:
            d = _load(os.path.join(FIN_DIR, fn))
            if d and d.get("list"):
                return div, d["list"]
    fn = "%s_%s_%s_CFS.json" % (corp, y, reprt)
    if fn in B and FIN.BODY is not None:
        b = _load(os.path.join(BODY_DIR, fn))
        if b and b.get("list") and b.get("v") == FIN.BODY.VERSION:
            return "본문", b["list"]
    return None, None


def _body_rows(d, reprt):
    """보고서 폴더 하나의 연결 재무제표 표 → 원장 모양 줄(손익 · 재무상태표). 본문재무.statement 와 같은 표 읽기를
    쓰되 .cache/본문재무 에는 쓰지 않는다(결과는 .cache/산업/_parse/body/ 에). 누적만 있는 반기 · 3분기 손익은
    3개월 칸을 비워 두고 fin_company 가 '누적 − 직전 누적'으로 뗀다."""
    Bm = FIN.BODY
    sec = Bm._statement_lines(d, "CFS")
    if not sec:
        return []
    out, seen = [], set()
    for kind, ls in Bm._blocks(sec):
        if kind == "SCE" or kind in seen:
            continue
        t = Bm._parse_table(ls)
        if not t or not t["rows"] or not Bm._check(kind, t["rows"]):
            continue
        seen.add(kind)
        if kind not in ("IS", "CIS", "BS"):
            continue
        flip = kind in ("IS", "CIS") and Bm._neg_expense(t["rows"])
        q_is = kind in ("IS", "CIS") and reprt != "11011" and t["has_3m"]
        top = Bm._top_line(t["rows"]) if kind in ("IS", "CIS") else None
        c3, cc = (1, 0) if t["cum_first"] else (0, 1)
        for r in t["rows"]:
            v = r["vals"]
            if flip and Bm._is_expense(r["name"]):
                v = [-x if x is not None else None for x in v]
            if q_is:
                cur, cum = (v[c3] if len(v) > c3 else None), (v[cc] if len(v) > cc else None)
            else:
                cur, cum = (v[0] if v else None), None
            if reprt != "11011" and kind in ("IS", "CIS") and not t["has_3m"]:
                cum = cur                            # 3개월 칸이 없다 — 1분기는 3개월 = 누적, 반기 · 3분기는 누적만
                if reprt != "11013":
                    cur = None
            out.append({"sj_div": kind, "account_id": "ifrs-full_Revenue" if r is top else "-표준계정코드 미사용-",
                        "account_nm": r["name"], "thstrm_amount": None if cur is None else "%.0f" % cur,
                        "thstrm_add_amount": None if cum is None else "%.0f" % cum})
    return out if out and "BS" in seen and seen & {"IS", "CIS"} else []


def body_quarter(corp, y, reprt, dirs, memo):
    """연결 재무제표를 내는 해인데 분기 원장이 없거나 별도(OFS)만 있을 때 — 수집 보고서 본문의 연결 손익을 읽는다.
    memo = 회사별 캐시 {"y_reprt": {"k": [본문재무 버전, 폴더들], "list": [...]}}(바뀌면 표시)."""
    if FIN.BODY is None or not dirs:
        return None
    key = [FIN.BODY.VERSION, [os.path.basename(d) for d in dirs]]
    mk = "%d_%s" % (y, reprt)
    c = memo.get(mk)
    if c and c.get("k") == key:
        return c.get("list") or None
    lst = []
    for d in dirs:
        try:
            lst = _body_rows(d, reprt)
        except Exception:
            lst = []
        if lst:
            break
    memo[mk] = {"k": key, "list": lst}
    memo["_changed"] = True
    return lst or None


# 종속회사가 없어 연결 재무제표를 내지 않은 분기 — 「III. 재무에 관한 사항」 '2. 연결재무제표' 아래 문구
SOLO_HEAD = re.compile(r"(?m)^[ \t]*\d\s*\.\s*연\s*결\s*재\s*무\s*제\s*표[ \t]*$")
SOLO_NONE = re.compile(r"해\s*당\s*(?:사\s*항)?\s*(?:이|은|는)?\s*없|해당\s*하지\s*않|작성\s*(?:대상\s*이\s*)?(?:하지\s*(?:않|아니)|아님)"
                       r"|관련\s*된\s*사항이\s*없|종속\s*(?:기업|회사)\s*(?:이|가)\s*존재하지\s*않"
                       r"|연결\s*대상\s*(?:주요\s*)?(?:종속\s*)?(?:회사|기업|법인)\s*(?:이|가)?\s*없|개별\s*재무제표\s*기준으로\s*(?:작성|공시)")
SOLO_ALT = re.compile(r"연결\s*재무\s*제표\s*(?:없이|를\s*작성하지\s*않)")


def solo_quarter(dirs):
    """그 분기 보고서가 연결 재무제표를 내지 않았는가(종속회사가 없던 분기 — 별도가 곧 회사 전체).
    「III. 재무에 관한 사항」의 '2. 연결재무제표' 아래가 '해당사항 없음'('본 보고서 제출일 현재 해당사항이 없습니다' ·
    '… 개별 재무제표 기준으로 작성') 이거나 '연결재무제표 없이'. 가장 최근 접수본 하나만 본다.
    한화엔진 2025 1~3분기: 2025-12-16 첫 종속회사(Hanwha Engine Investment Norway) 편입 — 사업보고서만 연결."""
    for d in dirs or []:
        try:
            fs = [f for f in os.listdir(d) if "재무에관한사항" in re.sub(r"\s+", "", f)]
        except OSError:
            fs = []
        if not fs:
            continue
        t = _read(os.path.join(d, fs[0]), 400000)
        for m in SOLO_HEAD.finditer(t):
            body = t[m.end(): m.end() + 700]
            nx = re.search(r"\n[ \t]*\d\s*[.\-]\s*\S", body)
            body = body[:nx.start()] if nx else body
            if re.search(r"재무상태표|\d{1,3},\d{3},\d{3}", body) or \
                    re.search(r"연\s*결\s*(?:재\s*무\s*상\s*태\s*표|손\s*익|포\s*괄)", t[m.end(): m.end() + 500]):
                continue                              # 연결 표가 있다('2-1. 연결재무상태표' 같은 아래 제목 포함)
            if SOLO_NONE.search(body) or not body.strip(" \t\n-–"):
                return True                           # 문구 또는 빈 칸('-') — 연결 재무제표를 내지 않았다
        return bool(SOLO_ALT.search(t[:30000]))
    return False


def _log10(x):
    import math
    return math.log10(x) if x and x > 0 else 0.0


def fin_company(corp, F, B, fy=12, fx=None, dirs=None, fin=False):
    """한 회사 → {"y": {"2025": {rev, op, ni_own, src}}, "q": {"2025Q3": {...}}, "first": [기수 '제 1 기'인 해],
    "q1": [1분기 원장 있는 해], "fx": {통화: [원화로 바꾼 기간]}, "assets": {해: 자산총계}, 그리고 손본 기록
    (ofs_dropped · bad_q · body_q · solo_q · alias · scaled · restated · big_q)}
    dirs = {(해, 보고서코드): [수집 보고서 폴더(최근 접수 먼저)]} — 연결 재무제표를 내는 해(사업보고서가 CFS · 본문)인데
    1~3분기 원장이 없거나 별도뿐이면 본문 연결 손익(src '본문')으로 바꾸고, 그 분기 보고서가 연결 재무제표를 내지 않았으면
    (종속회사 없음, solo_quarter) 별도 원장을 그대로 쓴다. fin = 금융업 KSIC(매출 별칭을 조건부로)."""
    raw, fxu, dropped = {}, collections.defaultdict(list), []
    prior, curr, solo, alias = {}, {}, set(), []
    memo_path = os.path.join(PARSE_DIR, "body", corp + ".json")
    memo = None
    for y in YEARS:
        cons_year = None
        for q in (4, 1, 2, 3):                      # 사업보고서를 먼저 봐서 그해가 연결인지 안다
            if fy == 12 and (y, q) > LAST:
                continue
            src, rows = _ledger(corp, y, REPRT[q], F, B)
            if q == 4:
                cons_year = FAM.get(src) == "연결"
            elif cons_year and fy == 12 and src not in ("CFS", "본문") and dirs and dirs.get((y, REPRT[q])):
                if memo is None:
                    memo = _load(memo_path) or {}
                bl = body_quarter(corp, y, REPRT[q], dirs[(y, REPRT[q])], memo)
                if bl:
                    src, rows = "본문", bl
            if q != 4 and cons_year and fy == 12 and src == "OFS":
                if dirs and solo_quarter(dirs.get((y, REPRT[q]))):
                    solo.add((y, q))                  # 그 분기엔 종속회사가 없었다 — 별도가 곧 전체
                else:
                    dropped.append("%dQ%d" % (y, q))  # 연결 회사의 별도 분기 — 기준이 달라 내지 않는다
                    continue
            if rows:
                vals, nmp, cur, pv, anm = _pick(rows, fin)
                if anm:
                    alias.append(("%dQ%d" % (y, q), anm))
                curr[(y, q)] = cur or "KRW"
                prior[(y, q)] = pv
                if cur and cur != "KRW":
                    vals = _to_krw(vals, cur, fx, y, q, fy)
                    fxu[cur].append("%dQ%d" % (y, q))
                raw[(y, q)] = (src, vals, nmp)
    if memo and memo.pop("_changed", None):
        _save(memo_path, memo)

    def fam_ok(y, q, div):
        r = raw.get((y, q))
        return bool(r) and (FAM[r[0]] == FAM[div] or (y, q) in solo)

    def rescale(y, q, m):
        src, vals, nmp = raw[(y, q)]
        raw[(y, q)] = (src, {f: (None if a is None else a * m, None if c is None else c * m)
                             for f, (a, c) in vals.items()}, nmp)

    # (가0) 3개월 칸에 누적을 적은 반기 · 3분기 보고서(DL 2024 반기 · 3분기: 3개월 = 누적 = 2.90조 · 4.32조) — 3개월 칸이
    #      누적 칸과 같고 직전 누적이 있으면 3개월 칸을 비워 '누적 − 직전 누적'으로 뗀다(직전 누적이 0 이어도 결과는 같다).
    cumfix = []
    for (y, q), (src, vals, nmp) in sorted(raw.items()):
        if q not in (2, 3):
            continue
        ch = []
        for f, (a, c) in list(vals.items()):
            if f == "assets" or a is None or c is None or abs(a - c) > 1e-3 * max(abs(c), 1):
                continue
            p = raw.get((y, q - 1))
            if not p or not fam_ok(y, q - 1, src):
                continue
            pa, pc = p[1].get(f, (None, None))
            pc = pc if pc is not None else (pa if q - 1 == 1 else None)
            if pc is not None and pc != 0:
                vals[f] = (None, c)
                ch.append(f)
        if "rev" in ch:
            cumfix.append("%dQ%d" % (y, q))

    # (가) 원장 단위 오기 — 1~3분기 보고서 하나가 통째로 천 · 백만 배(또는 1/천 · 1/백만) 어긋난 경우(동성케미컬 2017 반기 ×10^6,
    #     JW생명과학 2021 반기 ×10^3, SK네트웍스 2017 3분기 ×10^-6). 누적(없으면 3개월) 매출이 '연간 × 경과 분기/4' 의 30배 밖이고
    #     천 · 백만 배로 고치면 1/4~4배 안에 들며, 영업이익도 같은 배수로 어긋나 있을 때만(바이오 · 수주 회사의 몰린 매출은
    #     영업이익이 정상이라 걸리지 않는다) 그 보고서 값을 모두 고친다. 4분기(연간 − 3분기 누적)는 고친 누적으로 다시 뗀다.
    scaled = []
    for y in YEARS:
        a = raw.get((y, 4))
        if not a:
            continue
        A = a[1].get("rev", (None, None))[0]
        Aop = a[1].get("op", (None, None))[0]
        if not A or A <= 0:
            continue
        lim = 5 * max(abs(Aop or 0), 0.05 * A)
        for q in (1, 2, 3):
            r = raw.get((y, q))
            if not r:
                continue
            r3, rc = r[1].get("rev", (None, None))
            x, exp = (rc, A * q / 4) if rc is not None and rc > 0 else (r3, A / 4)
            if x is None or x <= 0 or 1 / 30 <= x / exp <= 30:
                continue
            best = None
            for m in (1e-3, 1e-6, 1e3, 1e6):
                k = x * m / exp
                if 0.25 <= k <= 4 and (best is None or abs(_log10(k)) < abs(_log10(best[1]))):
                    best = (m, k)
            if not best:
                continue
            m = best[0]
            o3, oc = r[1].get("op", (None, None))
            ox = oc if oc is not None else o3
            if ox is not None and Aop is not None and ox != 0:
                if abs(ox * m) > lim or (m < 1 and abs(ox) <= lim) or (m > 1 and abs(ox) > lim / 30):
                    continue                          # 영업이익은 정상 — 매출만 크거나 작은 진짜 분기일 수 있다
            before = x
            rescale(y, q, m)
            scaled.append("%dQ%d 보고서 값 ×%g (누적 매출 %.4g → %.4g, 연간 %.4g)" % (y, q, m, before, before * m, A))

    bad = []
    for y in YEARS:                                  # 본문 분기의 단위 검사 — 3분기 누적이 연간의 30~120% 밖이면 그해 본문 분기를 버린다
        a, r3 = raw.get((y, 4)), raw.get((y, 3))
        if not a or not r3 or "본문" not in [raw.get((y, k), (None,))[0] for k in (1, 2, 3)]:
            continue
        ar = a[1].get("rev", (None, None))[0]
        c9 = r3[1].get("rev", (None, None))[1]
        if FAM[a[0]] == FAM[r3[0]] and ar and ar > 0 and c9 is not None and not (0.3 <= c9 / ar <= 1.2):
            for k in (1, 2, 3):
                if raw.get((y, k), (None,))[0] == "본문":
                    raw.pop((y, k))
                    bad.append("%dQ%d" % (y, k))

    # (나) 재작성된 앞 분기 — Y 사업보고서가 전기(Y−1) 연간을 3% 넘게 고쳐 적었는데(중단영업 재분류 · 분할 등) Y 3분기 보고서의
    #     전년 9개월은 처음 낸 값 그대로면, 그 3분기 누적은 재작성 전 기준이라 '연간 − 3분기 누적'이 기준이 섞인다
    #     (삼성바이오로직스 2025: 연간은 바이오에피스를 뺐고 1~3분기는 넣었다 → 4분기 매출 0.31조). 그때 4분기 =
    #     연간 − 재작성 9개월(Y+1 3분기 보고서의 전기 누적)이고, 그 보고서가 아직 없으면 4분기를 비운다.
    #     매출 · 영업이익은 함께(계속영업 줄), 지배순이익은 자기 전기 값이 고쳐졌을 때만(중단영업 이익은 순이익에 남는다).
    q4fix, restated = {}, []
    for y in YEARS:
        a, a0, c3, c30 = raw.get((y, 4)), raw.get((y - 1, 4)), raw.get((y, 3)), raw.get((y - 1, 3))
        if not (a and a0 and c3 and c30) or fy != 12:
            continue
        if {curr.get(k) for k in ((y, 4), (y - 1, 4), (y, 3), (y - 1, 3))} != {"KRW"}:
            continue
        if FAM[a[0]] != FAM[a0[0]] or not fam_ok(y, 3, a[0]) or not fam_ok(y - 1, 3, a0[0]):
            continue
        A = a[1].get("rev", (None, None))[0] or 0
        hit = {}
        for f in FIELDS:
            pf = (prior.get((y, 4)) or {}).get(f, (None, None))[0]
            of = a0[1].get(f, (None, None))[0]
            if pf is not None and of is not None and abs(pf - of) > max(0.03 * abs(of), 0.005 * abs(A), 1e8):
                hit[f] = (of, pf)
        if not hit:
            continue
        old = None
        for f in ("rev", "op"):
            p9 = (prior.get((y, 3)) or {}).get(f, (None, None))[1]
            o9 = c30[1].get(f, (None, None))[1]
            if p9 is not None and o9:
                old = abs(p9 - o9) <= 0.005 * abs(o9)
                break
        if not old:
            continue                                  # 3분기 보고서도 이미 재작성 기준(또는 알 수 없음) — 그대로
        fs = (["rev", "op"] if {"rev", "op"} & set(hit) else []) + (["ni_own"] if "ni_own" in hit else [])
        nxt = raw.get((y + 1, 3))
        for f in fs:
            af = a[1].get(f, (None, None))[0]
            c9r = (prior.get((y + 1, 3)) or {}).get(f, (None, None))[1] \
                if nxt and curr.get((y + 1, 3)) == "KRW" and FAM[nxt[0]] == FAM[a[0]] else None
            if af is not None and c9r is not None and (f != "rev" or 0 < c9r <= 1.2 * af):
                q4fix[(y, f)] = af - c9r
                how = "연간 − 재작성 9개월(%d 3분기 보고서 전기 누적 %.4g)" % (y + 1, c9r)
            else:
                # 재작성 9개월이 없다 — Y+1 1분기 · 반기 보고서의 전기 값(Y 1분기 3개월 · Y 반기 누적)이 처음 낸 값과 같으면 Y 분기는
                # 재작성되지 않은 것(전기 연간만 고친 오류 수정 등)이라 4분기를 그대로 두고, 다르거나 볼 수 없으면 비운다.
                seen_q, moved = 0, []
                for qq, ix in ((1, 0), (2, 1)):
                    n_, o_ = raw.get((y + 1, qq)), raw.get((y, qq))
                    if not n_ or not o_ or curr.get((y + 1, qq)) != "KRW" or FAM[n_[0]] != FAM[o_[0]]:
                        continue
                    pv = (prior.get((y + 1, qq)) or {}).get(f, (None, None))[ix]
                    ov = o_[1].get(f, (None, None))
                    ov = ov[0] if qq == 1 else (ov[1] if ov[1] is not None else None)
                    if pv is None or ov is None:
                        continue
                    seen_q += 1
                    if abs(pv - ov) > max(0.01 * abs(ov), 0.002 * abs(A), 1e7):
                        moved.append("%dQ%d %.4g→%.4g" % (y, qq, ov, pv))
                if seen_q and not moved:
                    restated.append("%dQ4 %s: 그대로 둠 — %d 사업보고서가 %d 연간을 재작성했지만 %d 1분기 · 반기 보고서의 전기 값은 "
                                    "처음 낸 값과 같다(그해 분기는 재작성 안 됨)" % (y, f, y, y - 1, y + 1))
                    continue
                q4fix[(y, f)] = None
                how = ("재작성 9개월이 아직 없어 비움(%d 3분기 보고서 전%s)" % (
                    y + 1, ", %d 1분기 · 반기 보고서가 %s 로 재작성" % (y + 1, " · ".join(moved)) if moved else "")
                    if (y + 1, 3) > LAST else "%d 3분기 보고서에 재작성 9개월이 없거나 맞지 않아 비움" % (y + 1))
            hf = f if f in hit else ("rev" if "rev" in hit else "op")
            restated.append("%dQ4 %s: %s — %d 사업보고서가 %d 연간 %s 를 %.4g → %.4g 로 재작성, %d 3분기 누적은 재작성 전" % (
                y, f, how, y, y - 1, hf, hit[hf][0], hit[hf][1], y))

    def cum(y, q, f, div):
        r = raw.get((y, q))
        if not r or not fam_ok(y, q, div):
            return None
        cur, c = r[1].get(f, (None, None))
        return c if c is not None else (cur if q == 1 else None)

    def alone(y, q, f, div):
        """분기 단독 — 3개월 칸, 없으면 누적 − 직전 누적. 4분기는 연간 − 3분기 누적(연결은 연결끼리 · 별도는 별도끼리 —
        종속회사가 없던 분기(solo)는 어느 쪽과도 잇는다). 재작성으로 기준이 섞인 4분기는 q4fix 값."""
        r = raw.get((y, q))
        if not r or not fam_ok(y, q, div):
            return None
        cur, c = r[1].get(f, (None, None))
        if q == 4:
            if (y, f) in q4fix:
                return q4fix[(y, f)]
            if cur is None:
                return None
            c9 = cum(y, 3, f, div)
            if c9 is None:                          # 3분기 누적 칸이 비면 1~3분기 단독 합
                s = [alone(y, k, f, div) for k in (1, 2, 3)]
                c9 = sum(s) if None not in s else None
            return cur - c9 if c9 is not None else None
        if cur is not None:
            return cur
        if c is None:
            return None
        if q == 1:
            return c
        p = cum(y, q - 1, f, div)
        return c - p if p is not None else None

    Y, Q, first, assets = {}, {}, [], {}
    for (y, q), (src, vals, nmp) in sorted(raw.items()):
        if q == 4:
            a = vals.get("assets", (None, None))[0]
            if a:
                assets[str(y)] = _int(a)
            rec = {f: _int(vals.get(f, (None, None))[0]) for f in FIELDS}
            if any(v is not None for v in rec.values()):
                rec["src"] = src
                Y[str(y)] = rec
            if nmp and re.search(r"제\s*0*1\s*기", nmp):
                first.append(y)
        rec = {f: _int(alone(y, q, f, src)) for f in FIELDS}
        if rec["rev"] is not None and rec["rev"] < 0:
            bad.append("%dQ%d" % (y, q))             # 음수 매출 — 재작성 · 중단영업 재분류로 차감 기준이 어긋났다
            continue
        if any(v is not None for v in rec.values()):
            # 4분기(연간 − 3분기 누적)나 누적 차감에 본문 값이 섞이면 출처를 '본문'으로 적는다
            used = [raw.get((y, k), (None,))[0] for k in ((3, 4) if q == 4 else (q - 1, q) if q > 1 else (q,))]
            rec["src"] = "단독" if (y, q) in solo else "본문" if src != "OFS" and "본문" in used else src
            Q["%dQ%d" % (y, q)] = rec

    # (다) 분기 매출 점검(도출한 분기) — 한 분기 매출이 연간/4 의 3배를 넘거나, 네 분기 합이 연간과 50% 넘게 다르면
    #     천 · 백만 배로 고쳐 맞으면 고치고(매출, 그리고 같이 어긋난 영업이익 · 순이익), 아니면 그 분기가 연간보다 크거나
    #     네 분기 합이 어긋날 때만 뺀다. 연간 안에 드는 큰 분기(바이오 기술료 · 수주 인도처럼 몰린 매출)는 남기고 적어 둔다.
    big = []
    for y in YEARS:
        A = (Y.get(str(y)) or {}).get("rev")
        if not A or A <= 0:
            continue
        ks = ["%dQ%d" % (y, q) for q in (1, 2, 3, 4)]

        def s4():
            vs = [(Q.get(k) or {}).get("rev") for k in ks]
            return sum(vs) if None not in vs else None
        for k in ks:
            r = (Q.get(k) or {}).get("rev")
            if r is None or r <= 3 * A / 4:
                continue
            fixed = None
            for m in (1e-3, 1e-6):
                v = r * m
                if not (A / 16 <= v <= 3 * A / 4):
                    continue
                rest = [(Q.get(j) or {}).get("rev") for j in ks if j != k]
                if None in rest or abs(sum(rest) + v - A) <= 0.5 * A:
                    fixed = m
                    break
            if fixed:
                rec = Q[k]
                for f in FIELDS:
                    ann = abs((Y.get(str(y)) or {}).get(f) or 0)
                    if rec.get(f) is not None and (f == "rev" or abs(rec[f]) > 3 * max(ann, 0.05 * A)):
                        rec[f] = _int(rec[f] * fixed)
                scaled.append("%s 분기 값 ×%g (매출 %.4g → %.4g, 연간 %.4g)" % (k, fixed, r, rec["rev"], A))
                continue
            t = s4()
            if r > 1.05 * A or (t is not None and abs(t - A) > 0.5 * A):
                Q.pop(k)
                bad.append(k)
                big.append("%s 뺌(매출 %.4g, 연간 %.4g%s)" % (k, r, A, "" if t is None else ", 네 분기 합 %.4g" % t))
            else:
                big.append("%s 남김(매출 %.4g, 연간 %.4g — 연간 안에 드는 몰린 매출)" % (k, r, A))
        t = s4()
        if t is not None and abs(t - A) > 0.5 * A:     # 큰 분기 없이 합만 어긋남 — 한 분기만 천 · 백만 배 고쳐 맞으면 고친다
            done = False
            for k in ks:
                r = Q[k]["rev"]
                for m in (1e-3, 1e-6, 1e3, 1e6):
                    if r and r > 0 and abs(t - r + r * m - A) <= 0.1 * A:
                        Q[k]["rev"] = _int(r * m)
                        scaled.append("%s 분기 매출 ×%g (%.4g → %.4g, 네 분기 합이 연간 %.4g 에 맞음)" % (k, m, r, r * m, A))
                        done = True
                        break
                if done:
                    break
    return {"y": Y, "q": Q, "first": first, "q1": sorted({y for (y, q) in raw if q == 1}), "fx": dict(fxu),
            "assets": assets, "ofs_dropped": dropped, "bad_q": sorted(set(bad)),
            "body_q": sorted(k for k, v in Q.items() if v["src"] == "본문"),
            "solo_q": sorted("%dQ%d" % k for k in solo if "%dQ%d" % k in Q),
            "alias": [p for p, _ in alias], "alias_nm": sorted({n for _, n in alias}),
            "scaled": scaled, "restated": restated, "big_q": big, "cumfix": cumfix}


# ---------------------------------------------------------------- 환율(외화 원장 환산용)
FX_PATH = os.path.join(OUT_DIR, "fx_monthly.json")
FX_ITEM = {"USD": ("0000001", 1.0), "JPY": ("0000002", 0.01), "EUR": ("0000003", 1.0), "CNY": ("0000053", 1.0)}


def fx_monthly(net=True):
    """ECOS 731Y004 월평균 매매기준율 {통화: {YYYYMM: 원}} (JPY 는 1엔당). .cache/산업/fx_monthly.json 에 두고,
    마지막 분기 끝 달(2026-06)이 빠졌을 때만 다시 받는다(통화마다 1콜). 키는 거시._get 으로만 읽고 남기지 않는다."""
    d = _load(FX_PATH) or {}
    last = "%d%02d" % (LAST[0], LAST[1] * 3)
    miss = [c for c in FX_ITEM if last not in (d.get(c) or {})]
    if not miss or not net:
        return d
    try:
        import 거시
        key = 거시._get("ECOS_API_KEY")
    except Exception:
        key = None
    if not key:
        return d
    import requests
    calls = 0
    for c in miss:
        item, mul = FX_ITEM[c]
        try:
            calls += 1
            js = requests.get("https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/10000/731Y004/M/201401/%s/%s/0000100"
                              % (key, last, item), timeout=60).json()
            rows = (js.get("StatisticSearch") or {}).get("row") or []
        except Exception:                           # 메시지에 키가 든 주소가 있을 수 있다 — 버린다
            continue
        v = {}
        for r in rows:
            try:
                v[r["TIME"]] = float(r["DATA_VALUE"]) * mul
            except (KeyError, TypeError, ValueError):
                pass
        if v:
            d[c] = v
    d["ts"] = time.time()
    d["calls"] = (d.get("calls") or 0) + calls
    _save(FX_PATH, d)
    return d


def _scan(d):
    """폴더 → {파일명: (크기, 수정시각)} — scandir 한 번(G: 드라이브에서 파일마다 stat 하면 느리다)."""
    out = {}
    try:
        with os.scandir(d) as it:
            for e in it:
                try:
                    st = e.stat()
                    out[e.name] = (st.st_size, int(st.st_mtime))
                except OSError:
                    pass
    except OSError:
        pass
    return out


def _by_corp(files):
    """{파일명: …} → {corp_code: [파일명]} (원장 · 본문 파일명은 corp_code 로 시작한다)"""
    g = collections.defaultdict(list)
    for fn in files:
        if fn[:8].isdigit() and fn[8:9] == "_":
            g[fn[:8]].append(fn)
    return g


# ---------------------------------------------------------------- 보고서 본문 파싱(rcept 캐시)
SUB_START = re.compile(r"연\s*결\s*대\s*상\s*(?:종\s*속\s*)?(?:회\s*사|기\s*업|법\s*인)\s*(?:의\s*)?(?:개\s*황|현\s*황)")
SUB_STOP = re.compile(
    r"연\s*결\s*대\s*상\s*(?:회\s*사|법\s*인|종\s*속\s*(?:회\s*사|기\s*업))\s*(?:의\s*)?(?:변\s*동|변\s*경)"
    r"|(?:신규\s*연결|연결\s*제외)\s*(?:종속|회사|법인|기업|\n)"
    r"|\n[ \t]*(?:\d+\s*[-.]\s*)?(?:\d+\s*\.\s*)?(?:계\s*열\s*회\s*사|타\s*법\s*인\s*출\s*자|회\s*사\s*의\s*연\s*혁"
    r"|주요\s*종속\s*(?:회사|기업)\s*(?:의\s*)?연혁)"
    r"|\n[ \t]*(?:[나다라마바사아자차카타파하]|\d{1,2}(?:-\d{1,2})?)\s*[.)][ \t]+[가-힣]{2}")
DATE_CELL = re.compile(r"^'?(?:(?:19|20)\d{2}|\d{2})\s*[.\-/년]\s*\d{1,2}(?:\s*[.\-/월]\s*\d{0,2}\s*일?)?\s*\.?$"
                       r"|^(?:19|20)\d{2}\s*년?$")
HEAD_CELL = re.compile(r"^(?:상\s*호|설립일|주\s*소|주요사업|최근사업|연도말|자산총액|지배관계|근거|주요종속|회사\s*여부|기업\s*여부"
                       r"|법인명|\(단위|☞|※|-$|합\s*계|소\s*계|계$|국내|해외|\(\s*\*[\d,\s]*\)\s*\S|\*+\d*\s+\S)")
FOOT_CELL = re.compile(r"^(?:\(\s*\*+\s*[\d,\s~\-]*\)\s*)+$|^\*+\s*[\d,]*$|^\(\s*주\s*\d+(?:\s*[,~\-]\s*\d+)*\s*\)$|^\(\s*\d{1,2}\s*\)$")
NUM_CELL = re.compile(r"^[\d,.\-()%\s△]+$")
CODE_RX = re.compile(r"\(\s*([0-9][0-9A-Z]{5})\s*\)")
PERIOD_RX = re.compile(r"((?:19|20)\d{2})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?\s*부\s*터\s*"
                       r"((?:19|20)\d{2})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?\s*까\s*지")
INV_START = re.compile(r"타\s*법\s*인\s*출\s*자\s*현\s*황\s*\(\s*상\s*세\s*\)")
INV_STOP = re.compile(r"\n[ \t]*\d\s*\.\s*(?:국내\s*및|[가-힣 ]{2,20}현황\s*\(\s*상\s*세)")
NOTE_START = re.compile(r"(?:연결\s*대상\s*)?종\s*속\s*(?:기\s*업|회\s*사)\s*(?:의\s*)?(?:현\s*황|개\s*요|내\s*역|투\s*자\s*현\s*황)"
                        r"|연결\s*대상\s*(?:종속\s*)?(?:기업|회사)(?:의)?\s*(?:현황|내역)")
NOTE_STOP = re.compile(r"관\s*계\s*기\s*업|공\s*동\s*기\s*업|공\s*동\s*약\s*정|연결\s*대상\s*범위의\s*변동|요\s*약\s*재\s*무\s*정\s*보")


def _lines(sec):
    return [x.strip() for x in sec.split("\n") if x.strip()]


def _window(ls, i, k=3):
    """i 번째 줄(설립일 · 상장 여부 칸) 바로 위의 내용 줄 k 개를 먼 것부터 '\\n' 으로 이어 준다.
    각주 줄('(*9)')은 건너뛰고 머리글 · 날짜 · 숫자 칸에서 멈춘다. 상호가 여러 줄로 갈린 표('에코프로' + '비엠',
    '엘에스일렉트릭㈜' + '(*3)' + '(*9)')를 맞출 때 가까운 줄부터 하나 · 둘 · 셋을 이어 본다(resolve)."""
    got, j = [], i - 1
    while j >= 0 and len(got) < k:
        x = ls[j]
        j -= 1
        if FOOT_CELL.match(x):
            continue
        if HEAD_CELL.match(x) or DATE_CELL.match(x) or NUM_CELL.match(x) or x in ("상장", "비상장"):
            break
        got.append(x)
    return "\n".join(reversed(got))


UNIT = {"원": 1, "천원": 1e3, "백만원": 1e6, "억원": 1e8}
UNIT_RX = re.compile(r"\(\s*단\s*위\s*[:：]?\s*(백만원|천원|억원|원)")


def _names_before_dates(ls, unit=1e6):
    """7칸 종속회사 표 — 설립일 칸 바로 위 줄(들)이 상호. 빈 줄로 레코드가 갈려도, 상호가 여러 줄이어도 잡는다.
    → [[상호 줄들, 자산총액(원) | None]] — 자산총액은 설립일 뒤 첫 숫자 칸(주소 · 주요사업 다음). 이름이 같은 다른
    회사(두산의 광고회사 '㈜한컴' ≠ 상장사 한컴)를 상장사 자산과 견줘 걸러 내는 데 쓴다."""
    out = []
    for i, x in enumerate(ls):
        if not (i and DATE_CELL.match(x)):
            continue
        w = _window(ls, i)
        if not w:
            continue
        a = None
        for y in ls[i + 1: i + 10]:
            if DATE_CELL.match(y):
                break
            if re.fullmatch(r"-?[\d,]*\d", y):
                a = _num(y)
                a = a * unit if a is not None else None
                break
        out.append([w, a])
    return out


def subs_section(text):
    """연결대상 종속회사 표(가장 긴 것) → ([[상호, 자산]], 직접 적은 종목코드들). '(요약)' 표는 종목코드만 본다."""
    best, codes = [], []
    for m in SUB_START.finditer(text):
        sec = text[m.end(): m.end() + 600000]
        st = SUB_STOP.search(sec)
        if st:
            sec = sec[:st.start()]
        codes += CODE_RX.findall(sec)
        if re.match(r"\s*\(\s*요\s*약", sec):
            continue
        u = UNIT_RX.search(sec[:3000])
        names = _names_before_dates(_lines(sec), UNIT[u.group(1)] if u else 1e6)
        if len(names) > len(best):
            best = names
    return best, sorted(set(codes))


def _num(x):
    x = (x or "").replace(",", "").strip()
    try:
        return float(x)
    except ValueError:
        return None


def stakes_section(text):
    """타법인출자 현황(상세) 16칸 표 → [[법인명, 상장(bool), 기말 지분율, 기초 지분율]] — 상장이거나 지분 20% 이상만."""
    m = INV_START.search(text)
    if not m:
        return []
    sec = text[m.end():]
    st = INV_STOP.search(sec)
    if st:
        sec = sec[:st.start()]
    ls = _lines(sec)
    out = []
    for i, x in enumerate(ls):
        if x not in ("상장", "비상장") or i == 0 or i + 14 > len(ls) or ls[i + 1].startswith("여부"):
            continue
        nm = _window(ls, i)
        if not nm:
            continue
        f = ls[i + 1: i + 15]                     # 취득일 · 목적 · 최초금액 · 기초(수량 · 지분율 · 장부) · 증감 3 · 기말(수량 · 지분율 · 장부) · 총자산 · 순손익
        pe, pb = _num(f[10]), _num(f[4])
        pe = pe if pe is not None and 0 <= pe <= 100 else None
        pb = pb if pb is not None and 0 <= pb <= 100 else None
        if x == "상장" or (pe or 0) >= 20 or (pb or 0) >= 20:
            out.append([nm, x == "상장", pe, pb])
    return out


def fs_head(text):
    """(첨부) 재무제표 머리 → (국문 명칭, 옛 이름, [시작일, 종료일])"""
    head = text[:6000]
    ls = [x for x in _lines(head) if not x.startswith("#")]
    name = old = None
    for x in ls[1:6]:
        if re.search(r"제\s*\d+\s*기|^\d{4}|부\s*터|까\s*지|^\(|^\"", x):
            continue
        if re.search(r"회사|㈜|\(주\)|종속|[A-Za-z가-힣]{2,}", x):
            o = _OLD_RX.search(x)
            old = clean(o.group(1)) if o else None
            name = clean(x)
            break
    m = PERIOD_RX.search(head)
    per = None
    if m:
        g = [int(v) for v in m.groups()]
        try:
            per = [dt.date(g[0], g[1], g[2]).isoformat(), dt.date(g[3], g[4], g[5]).isoformat()]
        except ValueError:
            per = None
    return name, old, per


def notes_subs(text):
    """연결재무제표 주석의 종속기업 표 → 이름 후보 줄들(관계기업 · 공동기업 표 앞에서 자른다)."""
    out = []
    for m in NOTE_START.finditer(text):
        sec = text[m.end(): m.end() + 120000]
        st = NOTE_STOP.search(sec)
        if st:
            sec = sec[:st.start()]
        for x in _lines(sec):
            if 2 <= len(x) <= 60 and re.search(r"[가-힣A-Za-z]", x) and not re.search(r"\d{3}|%|원\)|단위", x):
                out.append(x)
    return out


def _sec_files(rep):
    return [(s["file"], re.sub(r"\s+", "", s["title"])) for s in rep["sections"]]


def parse_report(cdir, rep):
    """한 보고서 → {"subs": [상호], "codes": [종목코드], "src": 상세표|개요|주석|None, "stakes": [...],
    "name": 국문 명칭, "old": 옛 이름, "fs": [시작, 끝], "cons": 연결재무제표 여부, "notes": [주석 이름 후보]}"""
    d = os.path.join(DATA, cdir, rep["dir"])
    secs = _sec_files(rep)
    out = {"p": rep["stamp"], "k": rep["label"], "tag": rep["tag"], "cons": _has_cfs(rep),
           "subs": [], "codes": [], "src": None, "stakes": [], "name": None, "old": None, "fs": None}
    for f, t in secs:
        if "상세표" in t:
            tx = _read(os.path.join(d, f))
            names, codes = subs_section(tx)
            out["stakes"] = stakes_section(tx)
            out["codes"] += codes
            if names:
                out["subs"], out["src"] = names, "상세표"
    if not out["subs"]:
        for f, t in secs:
            if "회사의개요" in t:
                names, codes = subs_section(_read(os.path.join(d, f)))
                out["codes"] += codes
                if names:
                    out["subs"], out["src"] = names, "개요"
                break
    out["codes"] = sorted(set(out["codes"]))
    if rep["label"] == "사업보고서":
        fs = [f for f, t in secs if "재무제표" in t and not re.search(r"주석|내부회계|검토|감사|부속", t)]
        fs.sort(key=lambda f: 0 if "연결" in dict(secs)[f] else 1)
        for f in fs[:3]:
            name, old, per = fs_head(_read(os.path.join(d, f), 8000))
            out["name"] = out["name"] or name
            out["old"] = out["old"] or old
            out["fs"] = out["fs"] or per
            if out["name"] and out["fs"]:
                break
        if not out["subs"] and out["cons"] and int(rep["stamp"][:4]) <= 2020:
            for f, t in secs:                       # 표가 없는 해 — 연결재무제표 주석의 종속기업 표
                if "연결재무제표" in t and "내부회계" not in t:
                    nl = notes_subs(_read(os.path.join(d, f)))
                    if nl:
                        out["notes"] = nl
                        out["src"] = "주석"
                        break
    return out


def _wanted(reports):
    """파싱할 보고서 — 2014~2026 사업보고서(정정 포함), 2026-06 반기보고서."""
    for r in reports:
        y = int(r["stamp"][:4])
        if (r["label"] == "사업보고서" and 2014 <= y <= 2026) or (r["label"] == "반기보고서" and r["stamp"] == "2026-06"):
            yield r


def parse_company(code, ent):
    """회사 하나의 보고서 파싱 결과 {rcept: …} — .cache/산업/_parse/{code}.json 에 rcept 로 캐시한다."""
    path = os.path.join(PARSE_DIR, code + ".json")
    old = _load(path) or {}
    got = old.get("r") if old.get("v") == PARSE_V else None
    got = dict(got or {})
    changed = False
    for rep in _wanted(ent.get("reports") or []):
        if rep["rcept"] in got:
            continue
        try:
            got[rep["rcept"]] = parse_report(ent["dir"], rep)
        except Exception as e:                     # 한 보고서가 깨져도 나머지는 간다
            got[rep["rcept"]] = {"p": rep["stamp"], "k": rep["label"], "tag": rep["tag"], "err": type(e).__name__,
                                 "subs": [], "codes": [], "stakes": []}
        changed = True
    if changed:
        _save(path, {"v": PARSE_V, "r": got})
    return got


# ---------------------------------------------------------------- 이름 → 종목코드
# 그해 국문 명칭으로도 못 잇는 이름. (모회사, 정규화 이름) → 종목코드. '*' = 어느 모회사든.
ALIAS = {
    ("051910", "에너지솔루션"): "373220",          # LG화학 2021 상세표 '주식회사 에너지솔루션' = LG에너지솔루션
}

# 연말 목록 규칙의 예외 — 해 첫 며칠에 지배력을 얻어 그해 손익이 사실상 한 해 내내 연결된 경우(본문으로 근거를 확인한 것만).
# (모회사, 자식, 회계연도) → 근거. 그해 말 연결 목록에 자식이 있어야 쓴다.
FULL_YEAR = {
    ("161390", "018880", 2025): "2025-01-03 한앤코오토홀딩스 지분 양수로 지배력 획득(2025 1분기보고서 주석) — 그해 손익을 사실상 전부 연결",
}


def name_maps(U, CC, legal):
    """{연도: {정규화 이름: 종목코드}} — 우선순위: 그해 국문 명칭 > 다음 해 > 앞 해 > 지금 이름(종목.txt · CORPCODE).
    다음 해를 앞 해보다 먼저 보는 이유: 모회사의 Y 말 보고서는 Y+1 년 3월에 나와 새 이름을 쓴다.
    (2019 '현대중공업' = 분할 신설 329180. 앞 해 2018 의 '현대중공업' 은 지금의 HD한국조선해양 009540)"""
    base = {}
    for code, (_, nm) in CC.items():
        if nm:
            base.setdefault(norm(nm), code)
    for u in U:
        base[norm(u["name"])] = u["code"]
    out = {}
    for y in range(2014, 2027):
        m = dict(base)
        for dy in (-1, 1, 0):
            for code, (nm, old) in (legal.get(y + dy) or {}).items():
                if old and dy != 0:
                    m.setdefault(norm(old), code)
                if nm:
                    m[norm(nm)] = code
        out[y] = m
    return out


def _resolve1(parent, cand, nm):
    k = norm(clean(cand))
    if len(k) < 2:
        return None
    c = ALIAS.get((parent, k)) or ALIAS.get(("*", k)) or nm.get(k)
    if not c:
        k2 = re.sub(r"(?:보험|증권)$", "", k)        # '한화생명보험' → '한화생명'
        c = nm.get(k2) if k2 != k else None
    return c


def resolve(parent, raw, nm):
    """표에서 뗀 상호(여러 줄이면 '\\n' 으로 이어짐) → (종목코드, 맞춘 이름). 가까운 줄 하나 · 둘 · 셋 순으로 이어 본다."""
    parts = [p for p in (raw or "").split("\n") if p.strip()]
    for n in range(1, len(parts) + 1):
        cand = " ".join(parts[-n:])
        c = _resolve1(parent, cand, nm)
        if c:
            return c, cand
    return None, None


# ---------------------------------------------------------------- 연결 구조
def _period_reports(parsed, stamp, label):
    """그 기말의 보고서 파싱 결과들 — 원본 먼저, 그다음 정정본(최근 것부터)."""
    xs = [(r, x) for r, x in parsed.items() if x.get("p") == stamp and x.get("k") == label]
    xs.sort(key=lambda t: (1 if t[1].get("tag") else 0, -int(t[0]) if t[1].get("tag") else int(t[0])))
    return xs


_FIRST_PX = {}


def first_trade(code):
    """상장일 대용 — .cache/price/{code}.json 의 첫 거래일 'YYYYMMDD'(2010 이전 상장이면 2010 무렵). 없으면 None."""
    if code not in _FIRST_PX:
        d = _load(os.path.join(CACHE, "price", code + ".json")) or {}
        _FIRST_PX[code] = min(d) if d else None
    return _FIRST_PX[code]


def consolidated(U, PR, NM, fy, comp):
    """기말별 연결 상장 자회사 → ({(모회사, 기말): {"st": ok|none|missing, "kids": {자식: (맞춘 이름, 출처, rcept)}}},
    이름 충돌 {(모회사, 자식): 근거}).
    이름 충돌 = 자회사 표의 이름이 상장사와 같지만 다른 회사(두산의 광고회사 '㈜한컴', 대덕의 '주식회사 디아이티',
    DS단석의 '하이브 주식회사'). 그 기말 표의 자산총액이 상장사 자산(연결)과 10배 넘게 다르거나 — 상장 자회사를
    거느린 자식(다우기술 → 키움증권)은 별도 자산이 연결보다 훨씬 작아 이 검사를 건너뛴다 — 타법인출자 표에
    '비상장'으로 적혔는데 그 기말에 이미 상장(첫 거래일이 앞섬)이면 그 기말에서만 뺀다(이름이 나중에 상장사 것이
    되는 경우: KG스틸)."""
    Uset = {u["code"] for u in U}
    out, flags = {}, []                             # flags = [(P, E, c, 표 자산, 비상장 근거)]
    for P in Uset:
        parsed = PR.get(P) or {}
        if fy.get(P, 12) != 12:
            continue
        for E in ENDS:
            label = "반기보고서" if E.endswith("-06") else "사업보고서"
            reps = _period_reports(parsed, E, label)
            y = int(E[:4])
            nm = NM[y]
            res = {"st": "missing" if not reps else "none", "kids": {}}
            for rc, x in reps:
                kids = {}
                names = x.get("subs") or []
                src = x.get("src") or ""
                tab = {}
                for raw, a_t in names:
                    c, cand = resolve(P, raw, nm)
                    if not (c and c != P and c in Uset and c not in kids):
                        continue
                    kids[c] = (cand, src, rc)
                    tab[c] = a_t
                for c in x.get("codes") or []:
                    if c != P and c in Uset and c not in kids and names:
                        kids[c] = ("(%s)" % c, src + "·코드", rc)
                notes = x.get("notes") or []
                if not names and notes:            # 주석 표 — 한 줄(또는 이어진 두 줄)이 상장사 이름과 그대로 맞을 때만
                    for j in range(len(notes)):
                        for cand in (notes[j], " ".join(notes[j:j + 2]) if j + 1 < len(notes) else None):
                            c = _resolve1(P, cand, nm) if cand else None
                            if c and c != P and c in Uset and c not in kids:
                                kids[c] = (cand, "주석", rc)
                                break
                unl = {}
                for nm_, listed, pe, pb in x.get("stakes") or []:   # 타법인출자 '비상장'인데 그때 이미 상장 → 다른 회사
                    c, _ = resolve(P, nm_, nm)
                    if c and c in kids and not listed:
                        ft = first_trade(c)
                        if ft and ft <= E.replace("-", "") + "31":
                            unl[c] = "타법인출자에 비상장(%s, 첫 거래 %s)" % (nm_.split("\n")[-1], ft)
                for c in kids:
                    flags.append((P, E, c, tab.get(c), unl.get(c)))
                if names or x.get("notes"):
                    res = {"st": "ok", "kids": kids}
                    break
            out[(P, E)] = res
    # 자산 검사는 쌍마다 표를 모아 판정한다 — 확인한 기말의 60% 이상이 어긋나면(0.2~5배 밖) 이름만 같은 다른 회사로 보고
    # 모든 기말에서 뺀다. 한두 기말만 어긋나면 그 보고서의 단위 오기(한일홀딩스 2026 반기 '(단위 : 원)'인데 천원)로 본다.
    votes = collections.defaultdict(lambda: [0, 0, []])
    strong = collections.defaultdict(list)
    for P, E, c, a_t, why in flags:
        if why:
            strong[(P, c)].append((E, why))
            continue
        ca = ((comp.get(c) or {}).get("assets") or {})
        y = int(E[:4])
        a_c = ca.get(str(y)) or ca.get(str(y - 1)) or ca.get(str(y + 1))
        has_kids = bool((out.get((c, E)) or {}).get("kids"))
        if a_t and a_t > 0 and a_c and a_c > 0 and not has_kids:
            v = votes[(P, c)]
            v[0] += 1
            if not (0.2 <= a_t / a_c <= 5):
                v[1] += 1
                v[2].append("%s 표 자산 %.0f억 vs 상장사 %.0f억" % (E, a_t / 1e8, a_c / 1e8))
    clash = collections.defaultdict(list)
    for (P, c), (n, bad, why) in votes.items():
        if bad and bad >= 0.6 * n:
            clash[(P, c)] += ["%d/%d 기말 자산 어긋남: " % (bad, n) + "; ".join(why)]
            for E in ENDS:
                r = out.get((P, E))
                if r and c in r["kids"]:
                    del r["kids"][c]
    for (P, c), items in strong.items():
        for E, why in items:
            r = out.get((P, E))
            if r and c in r["kids"]:
                del r["kids"][c]
            clash[(P, c)].append("%s %s" % (E, why))
    return out, dict(clash)


def build_edges(U, S, comp):
    """edges[Y] · edge_ev · 메모 — Y−1 말과 Y 말 둘 다 연결, 맨 위 상장 자회사만, 매출 · 출처 검사."""
    Ucodes = [u["code"] for u in U]
    idx = {E: i for i, E in enumerate(ENDS)}

    def mem(P, i, c):
        r = S.get((P, ENDS[i]))
        return None if not r or r["st"] != "ok" else (c in r["kids"])

    def mem_eff(P, i, c):
        """그 기말 연결 여부. 목록을 못 읽었거나(None) 그 기말에만 이름을 못 찾았는데(False) 앞뒤 기말이 둘 다
        연결이면 연결로 메운다(한 해만 빠졌다 돌아오는 연결은 거의 없고, 표가 깨져 이름을 놓친 경우가 대부분)."""
        v = mem(P, i, c)
        if v:
            return v, None
        if 0 < i < len(ENDS) - 1 and mem(P, i - 1, c) and mem(P, i + 1, c):
            return True, ENDS[i] + ("(목록 없음)" if v is None else "(이름 못 찾음)")
        return v, None

    raw_edges, ev = {}, collections.defaultdict(lambda: {"years": [], "ends": {}, "names": set(), "interp": [], "drop": []})
    for Y in range(2015, 2027):
        i1, i2 = idx["%d-12" % (Y - 1)], idx["%d-12" % Y if Y <= 2025 else "2026-06"]
        es = set()
        for P in Ucodes:
            cands = set()
            for i in (i1, i2):
                r = S.get((P, ENDS[i]))
                if r and r["st"] == "ok":
                    cands |= set(r["kids"])
            for c in cands:
                a, ia = mem_eff(P, i1, c)
                b, ib = mem_eff(P, i2, c)
                note = None
                if Y == 2026 and a and b is None:      # 2026-06 반기 목록이 없다 — 2025 말 연결을 그대로
                    b, note = True, "2026-06 목록 없음 → 2025말 기준"
                if a and b:
                    es.add((P, c))
                    e = ev["%s>%s" % (P, c)]
                    for i in (i1, i2):
                        r = S.get((P, ENDS[i]))
                        if r and c in r.get("kids", {}):
                            raw, src, rc = r["kids"][c]
                            e["ends"][ENDS[i]] = src
                            e["names"].add(raw)
                    e["interp"] += [x for x in (ia, ib) if x]
                    if note:
                        e["interp"].append(note)
        for (P, c, fy_), why in FULL_YEAR.items():   # 해 첫 며칠에 지배력을 얻은 경우(근거 확인한 것만)
            if fy_ == Y and (P, c) not in es and mem(P, i2, c):
                es.add((P, c))
                e = ev["%s>%s" % (P, c)]
                e["interp"].append("%d 수동 예외: %s" % (Y, why))
                raw, src, rc = S[(P, ENDS[i2])]["kids"][c]
                e["ends"][ENDS[i2]] = src
                e["names"].add(raw)
        raw_edges[Y] = es

    edges, notes = {}, []
    for Y, es in raw_edges.items():
        keep = set(es)
        kids = collections.defaultdict(set)
        for p, c in es:
            kids[p].add(c)
        for p, c in es:                             # P → C → G 면 P → G 는 C 안에 들어 있다
            if any(c in kids[m] for m in kids[p] if m != c):
                keep.discard((p, c))
                ev["%s>%s" % (p, c)]["drop"].append("%d 손자(중간 상장사 안)" % Y)
        fin = set()
        for p, c in sorted(keep):
            pr, cr, ps = _rev(comp, p, Y), _rev(comp, c, Y), _src(comp, p, Y)
            if ps == "OFS":
                ev["%s>%s" % (p, c)]["drop"].append("%d 모회사 별도(OFS) 실적" % Y)
                continue
            if pr is not None and cr is not None and cr > abs(pr) * 1.02:
                ev["%s>%s" % (p, c)]["drop"].append("%d 자식 매출 %.1f조 > 모회사 %.1f조" % (Y, cr / 1e12, pr / 1e12))
                continue
            fin.add((p, c))
            ev["%s>%s" % (p, c)]["years"].append(Y)
        edges[str(Y)] = sorted([p, c] for p, c in fin)
    return edges, ev, notes


def _rev(comp, code, Y):
    co = comp.get(code) or {}
    if Y <= 2025:
        return ((co.get("y") or {}).get(str(Y)) or {}).get("rev")
    q = co.get("q") or {}
    a, b = (q.get("2026Q1") or {}).get("rev"), (q.get("2026Q2") or {}).get("rev")
    return a + b if a is not None and b is not None else None


def _src(comp, code, Y):
    co = comp.get(code) or {}
    if Y <= 2025:
        return ((co.get("y") or {}).get(str(Y)) or {}).get("src")
    return ((co.get("q") or {}).get("2026Q2") or {}).get("src")


def _span_q(ps):
    """['2017Q3', '2017Q4', …] → '2017Q3~2023Q4(26)'(셋 이상이면)"""
    ps = sorted(set(ps))
    return "%s~%s(%d)" % (ps[0], ps[-1], len(ps)) if len(ps) > 2 else " ".join(ps)


def _relevant(companies, edges, SEC):
    """섹터 관련 회사 — 섹터 합계에 들어가거나(OVERRIDE · KSIC · 부문 회사) 연결 간선의 모회사 · 자식."""
    out = {c for es in (edges or {}).values() for e in es for c in e}
    for code, co in companies.items():
        if SEC is None:
            out.add(code)
        elif code in SEC.SEGMENTS or SEC.sector_of(code, co.get("ksic"))[0] != "제외":
            out.add(code)
    return out


def _span(ys):
    """[2015, 2016, 2017, 2020] → '2015–2017 · 2020'"""
    ys = sorted(set(ys))
    out, s = [], None
    for i, y in enumerate(ys):
        if s is None:
            s = y
        if i == len(ys) - 1 or ys[i + 1] != y + 1:
            out.append(str(s) if s == y else "%d–%d" % (s, y))
            s = None
    return " · ".join(out)


# 타법인출자 표 이름 꼬리 — '코스모신소재(주)(상장)-종속기업' '(주)코미코(연결)' '(주)한텍(국내 - 상장)' '주식회사 도우인시스 주1),주2)'
STAKE_TAIL = re.compile(r"\s*[-–]\s*(?:종속|관계|공동)\s*(?:기업|회사)\s*$|\(\s*(?:연결|국내|해외)[^()]*\)"
                        r"|(?:\s*,?\s*주\s*\d+\s*\)\s*)+$|\(\s*(?:\*|주)\s*[\d,\s]*\)")
COMPANY = re.compile(r"㈜|\(주\)|주식회사|\b(?:Co|Ltd|Inc|LLC|Corp|Corporation|Limited|PLC|GmbH|Pte|B\.V|S\.A)\b|회사$", re.I)
PCT_CELL = re.compile(r"^(\d{1,3}(?:\.\d+)?)\s*%$")
COUNTRY = re.compile(r"^(?:대한민국|한국|국내|해외|미국|중국|일본|베트남|인도|독일|영국|프랑스|홍콩|싱가포르|대만|태국|멕시코|"
                     r"브라질|폴란드|헝가리|인도네시아|말레이시아|필리핀|캐나다|호주|러시아|튀르키예|터키|체코|슬로바키아)$")


def stake_name(nm):
    """타법인출자 표에서 뗀 이름 → 머리글 조각('수량' · '금액')과 꼬리('-종속기업' · '(연결)' · '(국내 - 상장)' · '주1),주2)')를 뗀다."""
    parts = [p.strip() for p in (nm or "").split("\n") if p.strip() and p.strip() not in ("수량", "금액")]
    return "\n".join(STAKE_TAIL.sub("", p).strip() for p in parts if STAKE_TAIL.sub("", p).strip())


def stakes_all(text):
    """타법인출자 현황(상세) 표의 모든 행 → [[법인명, 상장(True/False/None), 기말 지분율, 기초 지분율]].
    stakes_section 은 '상장 · 비상장' 칸을 닻으로 삼아 상장 · 20% 이상만 남기지만, 이 함수는 취득일 칸을 닻으로 삼아
    '상장여부' 칸이 없는 '종속기업 투자내역' 표(한국알콜 2025: '(주)퓨릿 / 2019-04-10 / 투자 / …')도 읽는다.
    취득일 뒤 13칸 = 목적 · 최초금액 · 기초(수량 · 지분율 · 장부) · 증감 3 · 기말(수량 · 지분율 · 장부) · 총자산 · 순손익."""
    m = INV_START.search(text or "")
    if not m:
        return []
    sec = text[m.end():]
    st = INV_STOP.search(sec)
    if st:
        sec = sec[:st.start()]
    ls = _lines(sec)
    out = []
    for i, x in enumerate(ls):
        if i == 0 or not DATE_CELL.match(x) or i + 13 > len(ls) or not re.search(r"\d{1,2}\s*[.\-/월]", x):
            continue
        listed, j = None, i
        if ls[i - 1] in ("상장", "비상장"):
            listed, j = ls[i - 1] == "상장", i - 1
        nm = _window(ls, j)
        if not nm:
            continue
        if listed is None:
            tail = nm.split("\n")[-1]
            listed = True if re.search(r"\(\s*상장\s*\)|-\s*상장\)", tail) else False if re.search(r"비상장", tail) else None
        f = ls[i + 1: i + 14]
        pe, pb = _num(f[9]), _num(f[3])
        out.append([nm, listed, pe if pe is not None and 0 <= pe <= 100 else None,
                    pb if pb is not None and 0 <= pb <= 100 else None])
    return out


def _report_dir(code, IX, stamp, label):
    """그 기말 보고서(원본 먼저) → (폴더, 보고서 색인 항목) | (None, None)"""
    ent = IX.get(code) or {}
    reps = [r for r in ent.get("reports") or [] if r["stamp"] == stamp and r["label"] == label]
    reps.sort(key=lambda r: (1 if r["tag"] else 0, r["rcept"]))
    return (os.path.join(DATA, ent["dir"], reps[0]["dir"]), reps[0]) if reps else (None, None)


def _name_keys(code, NMy, CC, U):
    """종목코드 → 그해 이름 사전에서 그 코드로 가는 정규화 이름들 + 지금 이름(종목.txt · CORPCODE)."""
    ks = {k for k, c in NMy.items() if c == code}
    ks |= {norm(u["name"]) for u in U if u["code"] == code}
    if CC.get(code):
        ks.add(norm(CC[code][1]))
    return {k for k in ks if len(k) >= 2}


def _match(raw, keys):
    """표 이름(여러 줄이면 가까운 줄부터 하나 · 둘 · 셋) ↔ 이름 키 — 같거나, 4자 이상이면서 한쪽이 다른 쪽으로 시작하고 길이 차가
    2자 이하(표에 '비지에프에코머티리얼'로 적힌 BGF에코머티리얼즈)."""
    parts = [p for p in stake_name(raw).split("\n") if p.strip()]
    for n in range(1, len(parts) + 1):
        k = norm(clean(" ".join(parts[-n:])))
        for t in keys:
            if k == t or (min(len(k), len(t)) >= 4 and abs(len(k) - len(t)) <= 2 and (k.startswith(t) or t.startswith(k))):
                return True
    return False


PCT_NUM = re.compile(r"^(\d{1,3}(?:\.\d{1,4})?)\s*%?$")


def _pct(x):
    m = PCT_NUM.match(x or "")
    v = float(m.group(1)) if m else None
    return v if v is not None and 0 < v <= 100 else None


def via_stake(d, rep, P, C, keys_c, keys_p, direct):
    """타법인출자 표에 없는 자식의 지분을 보고서 본문 표에서 찾는다 → {"stake", "via", "indirect", "how"} | None.
    순서: ① 연결 주석 · 상세표의 '자식 / 소재지 / 업종 / 보유 회사 / 지분율%' — 보유 회사가 P 면 직접 지분, P 의 직접 출자
    회사(타법인출자 표 direct)면 실효 = P→보유 × 보유→자식(LS > 가온전선 = LS전선 93% × 81.6%).
    ② 별도 재무제표 주석의 종속기업 투자 표 '자식 / 지분율 / 소재지' — P 의 직접 지분(드림텍 > 나무가 39.01%).
    ③ 연결 주석의 '자식 / … / 지배 지분율 / … / 비지배 지분율' 이 합해 100 이면 지배 지분율 = 실효 지분(두산 > 두산테스나
    38.9 / 비지배 61.1). ④ 보유 회사만 알고 실효를 못 셈하면 stake None(via 만). 보유 회사 칸도 비지배 칸도 없는
    '연결실체 지분율' 표(현대지에프홀딩스 > 한섬 42.3%)는 계열 합산일 수 있어 쓰지 않는다."""
    if not d:
        return None
    deep, sep_hit, nci_hit = None, None, None
    for s in rep["sections"]:
        t = re.sub(r"\s+", "", s["title"])
        sep = "재무제표" in t and "연결" not in t and t.startswith("(첨부)")
        if not ("연결재무제표" in t or "상세표" in t or "재무에관한사항" in t or sep):
            continue
        ls = _lines(_read(os.path.join(d, s["file"])))
        for i, x in enumerate(ls):
            if len(x) > 60 or not _match(x, keys_c):
                continue
            win = ls[i + 1: i + 9]
            if sep and len(win) >= 2 and _pct(win[0]) and COUNTRY.match(win[1]) and not sep_hit:
                sep_hit = {"stake": _pct(win[0]), "indirect": False, "via": None,
                           "how": "별도 재무제표 주석 종속기업 투자 표(직접 지분)"}
                continue
            for j in range(i + 1, min(i + 7, len(ls))):
                m = PCT_CELL.match(ls[j])
                if not m:
                    continue
                h = ls[j - 1]
                if j - 1 <= i + 1 or COUNTRY.match(h) or NUM_CELL.match(h) or PCT_CELL.match(h) or len(h) > 40:
                    break                              # 보유 회사 칸이 없는 표
                pct = float(m.group(1))
                if _match(h, keys_p):
                    return {"stake": pct, "indirect": False, "via": None, "how": "연결 주석 종속기업 표(보유 회사 = 모회사)"}
                for nm, dp in direct:
                    if dp and _match(h, {norm(clean(stake_name(nm).split("\n")[-1]))}):
                        return {"stake": round(dp * pct / 100, 2), "indirect": True,
                                "via": "%s %.2f%% (모회사 → %s %.2f%%)" % (stake_name(h), pct, stake_name(nm).split("\n")[-1], dp),
                                "how": "연결 주석 종속기업 표 — 실효 지분 = 모회사→보유 회사(타법인출자) × 보유 회사→자식"}
                if COMPANY.search(h) and not deep:
                    deep = {"stake": None, "indirect": True, "via": "%s %.2f%%" % (stake_name(h), pct),
                            "how": "연결 주석 종속기업 표 — 보유 회사가 모회사의 직접 출자 회사가 아니다(더 깊은 사슬)"}
                break
            if not sep and not nci_hit:
                nums = [v for v in (_pct(w) for w in win) if v is not None]
                if len(nums) >= 2 and nums[0] < 100:
                    for y in nums[1:4]:
                        if abs(nums[0] + y - 100) <= 0.2 and (y != nums[0] or nums[0] == 50):
                            nci_hit = {"stake": nums[0], "indirect": True, "via": None,
                                       "how": "연결 주석 종속기업 표 지배 지분율 %.2f%%(비지배 %.2f%% 와 합 100) = 실효 지분" % (nums[0], y)}
                            break
    return sep_hit or nci_hit or deep


def holdings(U, PR, NM, S, clash, edges=None, IX=None, CC=None, nonfin=None):
    """최근 사업보고서(2025 우선) 타법인출자 현황(상세) → {"P>C": {stake, year, kind, src[, indirect, via]}}.
    · '상장'으로 적힌 행(그 기말에 아직 상장 전이던 자회사는 '비상장'도) 가운데 그 기말 연결 자식(kind 종속) · 지분 20% 이상
      (관계) · 지분 5~20% 인데 보유 회사가 비금융 사업회사(nonfin)인 상장 관계(관계 — 기아 > 현대모비스 17%). 이름 충돌 쌍은 뺀다.
    · edges 의 (모회사, 자식)인데 위에서 못 찾은 쌍 — 간선 마지막 해(2026 만이면 2026-06 반기) 보고서의 타법인출자 표 전체
      (stakes_all: '상장여부' 칸 없는 종속기업 투자내역 표 포함)에서 이름 키(그해 국문 명칭 · 옛 이름 · 지금 이름, 앞부분 일치)로
      직접 지분을 찾고, 없으면 간접 보유로 보고 연결 주석 종속기업 표의 보유 회사 · 지분율로 실효 지분(P→보유 × 보유→자식)을
      셈한다. 그것도 못 셈하면 stake None(kind 종속, indirect True) — 산업.py 는 숫자 지분만 시총에서 뺀다."""
    Uset = {u["code"] for u in U}
    out = {}
    for P in sorted(Uset):
        parsed = PR.get(P) or {}
        best = None
        for y in range(2025, 2020, -1):
            for rc, x in _period_reports(parsed, "%d-12" % y, "사업보고서"):
                if x.get("stakes"):
                    best = (y, rc, x)
                    break
            if best:
                break
        if not best:
            continue
        y, rc, x = best
        kids = (S.get((P, "%d-12" % y)) or {}).get("kids") or {}
        seen = {}
        for nm, listed, pe, pb in x["stakes"]:
            if re.search(r"우선주|전환상환|신주인수권", nm.split("\n")[-1]):
                continue                               # 보통주 지분만
            c, _ = resolve(P, stake_name(nm), NM[y])
            if not c or c == P or c not in Uset or any(w.startswith("%d-12" % y) or re.match(r"\d+/\d+ 기말", w)
                                                       for w in clash.get((P, c), [])):
                continue                               # 이름 충돌(다른 회사)
            if not listed and (first_trade(c) or "0") <= "%d1231" % y:
                continue                               # 비상장으로 적혔는데 그때 이미 상장사 — 이름만 같은 다른 회사
            pct = pe if pe is not None else pb
            if pct is None:
                continue
            assoc = listed and 5 <= pct < 20 and (nonfin is None or nonfin(P))
            if c in kids or pct >= 20 or assoc:
                if c in seen and seen[c] >= pct:
                    continue
                seen[c] = pct
                out["%s>%s" % (P, c)] = {"stake": round(pct, 2), "year": y, "kind": "종속" if c in kids else "관계",
                                         "src": "%d 사업보고서 상세표 타법인출자(%s)" % (y, rc)}
    if not edges or IX is None:
        return out
    last = collections.defaultdict(list)
    for Y, es in edges.items():
        for p, c in es:
            last[(p, c)].append(int(Y))
    for (P, C), ys in sorted(last.items()):
        k = "%s>%s" % (P, C)
        if k in out:
            if out[k]["kind"] != "종속" and max(ys) >= out[k]["year"]:
                out[k]["kind"] = "종속"                # 그 기말 목록엔 없었지만 간선(한 해 내내 연결)인 쌍
            continue
        rec, ylist = None, [max(ys)] + ([2025] if max(ys) >= 2026 else [])
        for Y in ylist:                               # 간선 마지막 해(2026 만이면 2025 사업보고서도) — 옛 해 지분은 쓰지 않는다
            stamp, label = ("2026-06", "반기보고서") if Y >= 2026 else ("%d-12" % Y, "사업보고서")
            yy = min(Y, 2026)
            d, rep = _report_dir(P, IX, stamp, label)
            if not d:
                continue
            keys_c = _name_keys(C, NM[yy], CC or {}, U)
            keys_p = _name_keys(P, NM[yy], CC or {}, U)
            rows = []
            for s in rep["sections"]:
                if "상세표" in s["title"]:
                    rows = stakes_all(_read(os.path.join(d, s["file"])))
                    break
            hit = [(pe if pe is not None else pb) for nm, listed, pe, pb in rows
                   if not re.search(r"우선주|전환상환|신주인수권", nm) and _match(nm, keys_c)]
            hit = [v for v in hit if v]                # 0% = 그 기말엔 직접 보유가 없다(지주 분할로 넘김 등)
            if hit:
                rec = {"stake": round(max(hit), 2), "year": Y, "kind": "종속",
                       "src": "%s %s 상세표 타법인출자(%s, 이름 앞부분 · 상장여부 칸 없는 표 포함)" % (stamp, label, rep["rcept"])}
                break
            direct = [(nm, pe if pe is not None else pb) for nm, listed, pe, pb in rows]
            v = via_stake(d, rep, P, C, keys_c, keys_p, direct)
            if v:
                rec = {"stake": v["stake"], "year": Y, "kind": "종속",
                       "src": "%s %s %s(%s)" % (stamp, label, v["how"], rep["rcept"])}
                if v["indirect"]:
                    rec["indirect"] = True
                if v["via"]:
                    rec["via"] = v["via"]
                if v["stake"] is not None or Y == ylist[-1]:
                    break
        out[k] = rec or {"stake": None, "year": max(ys), "kind": "종속", "indirect": True,
                         "src": "타법인출자 표 · 연결 · 별도 주석에서 지분을 못 찾음 — 간접 보유(중간 회사 경유)로 봄"}
    return out


# ---------------------------------------------------------------- 짧은 해
def partial_years(code, parsed, finc, fy):
    """[(해, 근거)] — 재무제표 머리 기간이 355일이 안 되는 해. 본문이 없으면 원장 '제 1 기' + 1분기 원장 없음."""
    out, seen = [], set()
    for rc, x in parsed.items():
        if x.get("k") != "사업보고서" or not x.get("fs"):
            continue
        a, b = (dt.date.fromisoformat(v) for v in x["fs"])
        y = b.year
        if (b - a).days < 355 and 2015 <= y <= 2026 and y not in seen:
            seen.add(y)
            out.append((y, "재무제표 기간 %s~%s" % (x["fs"][0], x["fs"][1])))
        elif (b - a).days >= 355:
            seen.add(y)                              # 이 해는 본문으로 12개월 확인
    for y in finc.get("first") or []:
        if y not in seen and y not in (finc.get("q1") or []) and 2015 <= y <= 2026:
            seen.add(y)
            out.append((y, "원장 기수 '제 1 기' · 1분기 보고서 없음(본문 없음)"))
    return sorted(out)


# ---------------------------------------------------------------- 빌드
def build(verbose=True):
    t0 = time.time()
    say = print if verbose else (lambda *a, **k: None)
    os.makedirs(PARSE_DIR, exist_ok=True)
    U, snap = universe()
    CC = corpcodes()
    IX = report_index()
    ksic = _load(os.path.join(CACHE, "거시", "induty.json")) or {}
    fy = {u["code"]: fy_month(IX.get(u["code"])) for u in U}
    say("유니버스 %d곳 (종목.txt %s), 색인 %d곳" % (len(U), snap, len(IX)))

    # 1) 실적 — 원장 파일 목록을 한 번 읽고, 회사별 파일 서명이 같으면 앞 빌드 값을 그대로 쓴다
    t = time.time()
    F, B = _scan(FIN_DIR), _scan(BODY_DIR)
    FX = fx_monthly()
    Fc, Bc = _by_corp(F), _by_corp(B)
    prev = _load(FIN_CACHE) or {}
    sigs = _load(FIN_SIG) or {}
    if sigs.get("_v") != [FIN_V, getattr(FIN.BODY, "VERSION", None)]:
        sigs = {"_v": [FIN_V, getattr(FIN.BODY, "VERSION", None)]}
    jobs, comp, reused, QD, FINK = [], {}, 0, {}, {}
    for u in U:
        code = u["code"]
        corp = (CC.get(code) or (None,))[0]
        if not corp:
            continue
        QD[code] = qdirs(IX.get(code))
        FINK[code] = (ksic.get(corp) or "").startswith(("64", "65", "66"))
        h = hashlib.md5(repr((sorted((f, F[f]) for f in Fc.get(corp, [])),
                              sorted((f, B[f]) for f in Bc.get(corp, [])), fy[code],
                              sorted(QD[code].items()), FINK[code])).encode()).hexdigest()
        if sigs.get(code) == h and code in prev:
            comp[code] = prev[code]
            reused += 1
        else:
            jobs.append((code, corp, h))
    Fs, Bs = set(F), set(B)

    def work(j):
        code, corp, h = j
        return code, h, fin_company(corp, Fs, Bs, fy[code], FX, QD[code], FINK[code])

    with ThreadPoolExecutor(THREADS) as ex:
        for code, h, r in ex.map(work, jobs):
            comp[code] = r
            sigs[code] = h
    if jobs:                                        # 다음 빌드가 바뀌지 않은 회사의 원장을 다시 읽지 않게
        _save(FIN_CACHE, comp)
        _save(FIN_SIG, sigs)
    say("실적 %d곳 (새로 읽음 %d · 그대로 %d) %.0f초" % (len(comp), len(jobs), reused, time.time() - t))

    # 2) 보고서 본문 — rcept 캐시
    t = time.time()
    PR = {}

    def pwork(code):
        ent = IX.get(code)
        return code, (parse_company(code, ent) if ent else {})

    with ThreadPoolExecutor(THREADS) as ex:
        for code, r in ex.map(pwork, [u["code"] for u in U]):
            PR[code] = r
    say("보고서 본문 %d건 %.0f초" % (sum(len(v) for v in PR.values()), time.time() - t))

    # 3) 그해 국문 명칭 → 이름 사전 → 기말별 연결 자회사 → 간선
    t = time.time()
    legal = collections.defaultdict(dict)
    for code, parsed in PR.items():
        for rc, x in sorted(parsed.items(), key=lambda kv: (1 if kv[1].get("tag") else 0, kv[0])):
            if x.get("k") == "사업보고서" and x.get("name"):
                y = int(x["p"][:4])
                legal[y].setdefault(code, (x["name"], x.get("old")))
    NM = name_maps(U, CC, legal)
    S, clash = consolidated(U, PR, NM, fy, comp)
    edges, ev, enotes = build_edges(U, S, comp)
    SEC = _sectors()

    def nonfin(code):
        """비금융 사업회사 — 섹터 합계에 들어가는 회사이거나 KSIC 가 금융 · 보험 · 지주(64 · 65 · 66)가 아닌 회사."""
        k = ksic.get((CC.get(code) or (None,))[0]) or ""
        if SEC is not None and (code in SEC.SEGMENTS or SEC.sector_of(code, k)[0] != "제외"):
            return True
        return bool(k) and not k.startswith(("64", "65", "66"))
    hold = holdings(U, PR, NM, S, clash, edges, IX, CC, nonfin)
    say("연결 구조 %.0f초 — 간선 %s" % (time.time() - t, " ".join("%s:%d" % (y, len(v)) for y, v in sorted(edges.items()))))

    # 4) 합치기
    companies = {}
    pinfo = {}
    for u in U:
        code = u["code"]
        corp = (CC.get(code) or (None,))[0]
        fc = comp.get(code) or {"y": {}, "q": {}}
        py = partial_years(code, PR.get(code) or {}, fc, fy[code]) if corp else []
        pinfo[code] = py
        companies[code] = {"name": u["name"], "corp": corp, "ksic": ksic.get(corp) if corp else None,
                           "market": u["market"], "rank": u["rank"], "cap_snap": _int(u["cap"]),
                           "fy_end_month": fy[code], "partial_years": [y for y, _ in py],
                           "y": fc.get("y") or {}, "q": fc.get("q") or {}}
    edge_ev = {}
    for k, e in sorted(ev.items()):
        if not e["years"]:
            continue
        p, c = k.split(">")
        kinds = collections.defaultdict(list)
        for E, src in sorted(e["ends"].items()):
            kinds[src.split("·")[0]].append(E)
        src = " · ".join("%s %s" % (s, ",".join(sorted(v)) if len(v) <= 2 else "%s~%s" % (min(v), max(v)))
                         for s, v in sorted(kinds.items(), key=lambda kv: min(kv[1])))
        bits = ["이름 " + " / ".join(sorted(e["names"]))[:160]]
        h = hold.get(k)
        if h:
            bits.append(("%d 지분 %.2f%%" % (h["year"], h["stake"]) if h.get("stake") is not None else "%d 지분 모름" % h["year"])
                        + (" (간접%s)" % (" · " + h["via"] if h.get("via") else "") if h.get("indirect") else ""))
        if e["interp"]:
            bits.append("메움 · 예외: " + ", ".join(sorted(set(e["interp"]))))
        if e["drop"]:
            bits.append("뺀 해: " + "; ".join(e["drop"])[:300])
        edge_ev[k] = {"years": sorted(e["years"]), "src": src, "note": " · ".join(bits)}
    notes = [
        "y · q 값은 원(KRW). q 는 3개월 단독, 4분기 = 연간 − 3분기 누적(연결끼리 · 별도끼리). src = CFS(연결 원장) · "
        "OFS(별도 원장) · 본문(수집 보고서 본문의 연결 재무제표 표 — CFS 와 같은 연결 기준, 원장이 없는 기간) · 단독(연결 회사의 "
        "종속회사가 없던 분기의 별도 원장 — 범위가 연결과 같아 연결로 본다).",
        "연결 회사(그해 사업보고서가 CFS · 본문)의 1~3분기에 별도(OFS) 원장만 있으면 본문 연결 손익으로 바꾸고, 그 분기 보고서가 "
        "'연결재무제표 해당사항 없음'(종속회사가 없던 분기 — 별도가 곧 전체)이면 별도 원장을 그대로 쓰며(src 단독, 4분기는 연간 연결 − "
        "별도 9개월), 둘 다 아니면 그 분기를 내지 않는다(기준이 달라 4분기 · 증가율이 틀어진다).",
        "매출(rev)은 Revenue 태그 줄, 없으면(비금융) 이름이 매출 총액인 줄('영업수익' · '매출액' · '수익' · '수익(매출액)' — 태그가 "
        "GrossProfit · RevenueFromSaleOfGoodsProduct 여도). 금융업 KSIC 회사는 손익계산서에 이자 · 보험 · 수수료 수익 줄이 없을 때만.",
        "ni_own = 지배기업 소유주 귀속 순이익(그 줄이 없으면 당기순이익 − 비지배, 별도 재무는 당기순이익).",
        "partial_years = 회계연도가 12개월이 안 되는 해(분할 · 설립 첫해 · 결산월 변경). 그해 분기도 첫 분기는 3개월 미만일 수 있다.",
        "비12월 결산(fy_end_month ≠ 12) 회사의 'YYYYQn' 은 회계연도 기준. 연결 간선은 12월 결산 모회사만 본다.",
        "edges[Y] = Y−1 말과 Y 말(2026 은 2026-06 반기) 목록 둘 다에서 연결된 상장 자회사 — 맨 위 자식만. "
        "해 중간 편입 · 제외 해는 빠진다(그해 모회사 실적에 몇 달치가 겹친다).",
        "모회사 실적이 별도(OFS)인 해, 자식 매출이 모회사 × 1.02 를 넘는 해는 간선에서 뺐다(edge_ev note 참조). "
        "한 기말 목록만 못 읽었거나 그 기말에만 이름을 못 찾았는데 앞뒤 기말이 연결이면 연결로 메웠다(note '메움').",
        "수동 예외 FULL_YEAR: 한국타이어앤테크놀로지 > 한온시스템 2025(2025-01-03 지배력 획득 — 그해 손익 사실상 전부 연결).",
        "holdings = 최근 사업보고서 타법인출자 현황(상세)의 기말 지분율(직접 보유분). kind 종속 = 그 기말 연결 목록에 있거나 edges 의 "
        "쌍, 관계 = 지분 20% 이상, 또는 비금융 사업회사가 가진 5~20% 상장 지분(기아 > 현대모비스). edges 쌍인데 직접 지분이 없으면 "
        "indirect True — 연결 주석 종속기업 표의 보유 회사(via)가 P 의 직접 출자 회사면 stake = 실효 지분(P→보유 × 보유→자식), "
        "아니면 stake null(산업.py 는 숫자 지분만 시총에서 빼고, 순이익 몫은 0.6 으로 본다).",
        "합병 · 영업양수로 몸집이 바뀐 해(예: HD건설기계 2026 = HD현대건설기계 + HD현대인프라코어)는 표시하지 않는다.",
    ]
    for (p, c), why in sorted(clash.items()):
        notes.append("이름 충돌로 그 기말 연결 목록에서 뺀 %s>%s (%s 자회사 이름 = 상장사 %s): %s" % (
            p, c, companies[p]["name"], companies[c]["name"], "; ".join(why)[:400]))
    for code in sorted(comp):
        for cur, ps in sorted(((comp[code] or {}).get("fx") or {}).items()):
            notes.append("외화 원장 %s %s %s → 원화 환산(ECOS 731Y004 월평균 매매기준율): %s" % (
                code, companies.get(code, {}).get("name"), cur, ", ".join(ps)))
    od = ["%s:%s" % (c, q) for c in sorted(comp) for q in (comp[c] or {}).get("ofs_dropped") or []]
    bq = ["%s:%s" % (c, q) for c in sorted(comp) for q in (comp[c] or {}).get("bad_q") or []]
    notes.append("연결 회사의 별도(OFS) 분기라 뺀 분기 %d건: %s" % (len(od), " ".join(od)))
    notes.append("음수 매출(재작성 차감 어긋남) · 본문 단위 어긋남 · 연간보다 큰 분기(분할 · 재작성 전 기준)라 뺀 분기 %d건: %s"
                 % (len(bq), " ".join(bq)))

    def per_co(key, fmt="%s:%s"):
        return [fmt % (c, x) for c in sorted(comp) for x in (comp[c] or {}).get(key) or []]
    sq = per_co("solo_q")
    notes.append("연결 재무제표가 없던 분기(보고서 '연결재무제표 해당사항 없음' — 종속회사 없음)라 별도 원장을 그대로 쓴 분기 %d건: %s"
                 % (len(sq), " ".join(sq)))
    al = ["%s %s(%s: %s)" % (c, companies.get(c, {}).get("name"), "·".join((comp[c] or {}).get("alias_nm") or []),
                             _span_q((comp[c] or {}).get("alias") or []))
          for c in sorted(comp) if (comp[c] or {}).get("alias")]
    notes.append("매출 태그 줄이 없어 이름으로 매출을 잡은 회사 %d곳(보고서 기간): %s" % (len(al), "; ".join(al)))
    for key, what in (("scaled", "단위 오기를 천 · 백만 배로 고친 분기"), ("cumfix", "3개월 칸에 누적을 적어 '누적 − 직전 누적'으로 뗀 분기"),
                      ("restated", "재작성(중단영업 등)으로 기준이 섞인 4분기"), ("big_q", "연간/4 의 3배를 넘는 분기 매출")):
        xs = ["%s %s: %s" % (c, companies.get(c, {}).get("name"), "; ".join(v)) for c in sorted(comp)
              for v in [(comp[c] or {}).get(key) or []] if v]
        notes.append("%s — %d곳: %s" % (what, len(xs), " | ".join(xs)))
    rel = _relevant(companies, edges, SEC)
    gap = []
    for code in sorted(rel):
        co = companies[code]
        ks = [k for k, r in sorted(co["y"].items()) if r.get("op") is not None and r.get("rev") is None] + \
             [k for k, r in sorted(co["q"].items()) if r.get("op") is not None and r.get("rev") is None]
        if ks:
            gap.append("%s %s: %s" % (code, co["name"], " ".join(ks)))
    notes.append("영업이익은 있는데 매출이 없는 섹터 관련 회사-기간 %d곳(원장에 매출 줄이 아예 없다 — 매출 없는 바이오 · 리츠 등): %s"
                 % (len(gap), " | ".join(gap)))
    mism = []
    for code, co in companies.items():
        for y, a in co["y"].items():
            vs = [(co["q"].get("%sQ%d" % (y, q)) or {}).get("rev") for q in (1, 2, 3, 4)]
            if a.get("rev") and None not in vs and abs(sum(vs) - a["rev"]) > abs(a["rev"]) * 0.01:
                mism.append("%s:%s" % (code, y))
    notes.append("분기 매출 합이 연간과 1%%넘게 어긋나는 회사-연도 %d건(1~3분기는 처음 보고 값 그대로다 — 3분기 누적이 재작성 · "
                 "중단영업 재분류 기준이면 4분기가 차이를 떠안고, 4분기를 재작성 9개월로 뗀 해는 1~3분기가 재작성 전이라 합이 "
                 "어긋난다): %s" % (len(mism), " ".join(sorted(mism))))
    jumps = []                                      # 합병 · 분할 · 매각으로 몸집이 바뀐 해 후보(표시만 한다)
    for code, co in companies.items():
        pys = set(co["partial_years"])
        for y in range(2016, 2027):
            if y in pys or y - 1 in pys:
                continue
            if y <= 2025:
                a, b = co["y"].get(str(y - 1)) or {}, co["y"].get(str(y)) or {}
                ra, rb, sa, sb = a.get("rev"), b.get("rev"), a.get("src"), b.get("src")
            else:
                qa = [co["q"].get("2025Q%d" % k) or {} for k in (1, 2)]
                qb = [co["q"].get("2026Q%d" % k) or {} for k in (1, 2)]
                if any(x.get("rev") is None for x in qa + qb):
                    continue
                ra, rb = sum(x["rev"] for x in qa), sum(x["rev"] for x in qb)
                sa, sb = qa[1].get("src"), qb[1].get("src")
            if ra and rb and ra > 0 and max(ra, rb) >= 3e11 and FAM.get(sa) == FAM.get(sb) and not (0.5 <= rb / ra <= 2):
                jumps.append("%s:%d(×%.2f)" % (code, y, rb / ra))
    notes.append("매출이 한 해에 2배 넘게 늘거나 절반 아래로 준 회사-연도 %d건(3,000억 이상, 같은 연결/별도 기준 — 합병 · 분할 · "
                 "매각 · 사업 재분류 의심, 2026 은 상반기 대 상반기. 예: 267270 HD건설기계 2026 = HD현대인프라코어 합병): %s"
                 % (len(jumps), " ".join(sorted(jumps))))
    for code, py in sorted(pinfo.items()):
        for y, why in py:
            notes.append("짧은 해 %s %s %d: %s" % (code, companies[code]["name"], y, why))
    panel = {"v": V, "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "snap": snap,
             "companies": companies, "edges": edges, "edge_ev": edge_ev, "holdings": hold, "notes": notes}
    _save(PANEL, panel)
    say("저장 %s (%.1fMB) — 총 %.0f초" % (PANEL, os.path.getsize(PANEL) / 1e6, time.time() - t0))
    return panel


# ---------------------------------------------------------------- 점검
EXPECT = [
    # (모회사, 자식, 기대 연도(None = 있으면 됨), 메모)
    ("051910", "373220", list(range(2021, 2027)), "LG화학 > LG에너지솔루션"),
    ("009540", "329180", list(range(2020, 2027)), "HD한국조선해양 > HD현대중공업"),
    ("267250", "009540", None, "HD현대 > HD한국조선해양"),
    ("012450", "042660", [2025, 2026], "한화에어로스페이스 > 한화오션(2025~ 만)"),
    ("012450", "272210", None, "한화에어로스페이스 > 한화시스템"),
    ("005490", "003670", None, "POSCO홀딩스 > 포스코퓨처엠"),
    ("005490", "047050", None, "POSCO홀딩스 > 포스코인터내셔널"),
    ("034020", "241560", None, "두산에너빌리티 > 두산밥캣"),
    ("005380", "064350", None, "현대차 > 현대로템"),
    ("034730", "096770", None, "SK > SK이노베이션"),
    ("034730", "017670", None, "SK > SK텔레콤"),
    ("066570", "011070", None, "LG전자 > LG이노텍"),
    ("097950", "000120", None, "CJ제일제당 > CJ대한통운"),
    ("086520", "247540", None, "에코프로 > 에코프로비엠"),
    ("161390", "018880", None, "한국타이어앤테크놀로지 > 한온시스템(2025~ ?)"),
    ("006260", "010120", None, "LS > LS ELECTRIC"),
]
NON_EDGE = [
    ("005380", "000270", "현대차 > 기아(지분법)"),
    ("005930", "009150", "삼성전자 > 삼성전기(지분법)"),
    ("005930", "006400", "삼성전자 > 삼성SDI(지분법)"),
    ("402340", "000660", "SK스퀘어 > SK하이닉스(지분법)"),
    ("003550", "066570", "LG > LG전자(지분법)"),
    ("017670", "000660", "SK텔레콤 > SK하이닉스(2021 전 지분법)"),
]


def _hold_txt(h):
    if not h:
        return ""
    s = "지분 %.2f%% %s" % (h["stake"], h["kind"]) if h.get("stake") is not None else "지분 모름 %s" % h["kind"]
    return s + (" 간접" if h.get("indirect") else "")


def check(panel=None):
    panel = panel or _load(PANEL)
    if not panel:
        print("panel.json 이 없다 — python 산업_패널.py 먼저")
        return
    E = {y: {tuple(e) for e in v} for y, v in panel["edges"].items()}
    co = panel["companies"]
    yrs = list(range(2015, 2027))

    def found(p, c):
        return [y for y in yrs if (p, c) in E.get(str(y), set())]

    print("== 간선 검증 (기대 vs 찾음)")
    bad = 0
    for p, c, exp, memo in EXPECT:
        f = found(p, c)
        live = [y for y in yrs if str(y) in co.get(c, {}).get("y", {}) or "%dQ2" % y in co.get(c, {}).get("q", {})]
        if exp is None:                             # 있으면 됨 — 첫 해 뒤로 자식 실적이 있는 해마다 이어지는지
            gaps = [y for y in live if f and y >= min(f) and y not in f]
            ok = bool(f) and not gaps
        else:
            gaps = [y for y in exp if y not in f]
            extra = [y for y in f if y not in exp]
            ok = not gaps and not extra
            gaps = gaps + ["+%d" % y for y in extra]
        bad += 0 if ok else 1
        h = panel["holdings"].get("%s>%s" % (p, c)) or {}
        print("  %-4s %-44s 찾음 %-22s %s%s" % ("OK" if ok else "확인", memo, _span(f) or "-",
                                             ("빠짐/더: %s " % gaps) if gaps else "",
                                             _hold_txt(h)))
    for p, c, memo in NON_EDGE:
        f = found(p, c)
        h = panel["holdings"].get("%s>%s" % (p, c)) or {}
        bad += 1 if f else 0
        print("  %-4s %-44s 간선 %-22s %s" % ("OK" if not f else "틀림", memo, _span(f) or "없음",
                                           _hold_txt(h)))
    print("  확인할 것 %d건" % bad)
    print("== 연도별 커버리지 (연간 매출 · 지배순이익 / 연간 출처 CFS·OFS·본문 / 분기 매출 Q1·Q2·Q3·Q4 / 간선)")
    for y in yrs:
        ys = [c["y"].get(str(y)) for c in co.values()]
        ys = [r for r in ys if r]
        src = collections.Counter(r.get("src") for r in ys)
        qn = [sum(1 for c in co.values() if (c["q"].get("%dQ%d" % (y, q)) or {}).get("rev") is not None) for q in (1, 2, 3, 4)]
        print("  %d  연간 %4d · %4d  (%d/%d/%d)  분기 %s  간선 %d" % (
            y, sum(1 for r in ys if r.get("rev") is not None), sum(1 for r in ys if r.get("ni_own") is not None),
            src.get("CFS", 0), src.get("OFS", 0), src.get("본문", 0), "·".join("%d" % n for n in qn),
            len(panel["edges"].get(str(y), []))))
    ps = [(c, y) for c, v in co.items() for y in v.get("partial_years") or []]
    print("== 짧은 해 %d건: %s" % (len(ps), ", ".join("%s %s %d" % (c, co[c]["name"], y) for c, y in sorted(ps, key=lambda t: t[1]))))
    print("== 만든 때 %s · 스냅샷 %s · 회사 %d · holdings %d · edge_ev %d" % (
        panel.get("built"), panel.get("snap"), len(co), len(panel.get("holdings") or {}), len(panel.get("edge_ev") or {})))


# ---------------------------------------------------------------- 채우기(DART)
_TL = threading.local()


class _Counting:
    """재무.requests 자리에 잠깐 끼워 DART 응답 status 만 본다(주소 · 키는 어디에도 남기지 않는다)."""

    def __init__(self, real):
        self.real = real

    def get(self, url, **kw):
        _TL.status = None
        r = self.real.get(url, **kw)
        try:
            _TL.status = (r.json() or {}).get("status")
        except Exception:
            _TL.status = "?"
        return r

    def __getattr__(self, k):
        return getattr(self.real, k)


def fill(limit=FILL_CAP, threads=4, verbose=True):
    """원장 파일이 아예 없는 2015~2021 기간을 DART 에서 받는다(재무.fetch_statement — .cache/fin 에 쓴다).
    수집본에 그 보고서가 있는 기간만, 사업보고서 → 3분기 → 반기 → 1분기, 큰 회사부터. 연결 회사(그해 · 앞뒤 해
    사업보고서에 연결재무제표가 붙음)는 CFS 먼저(013 이면 OFS), 아니면 OFS 먼저. 원장이 아예 없는 기간을 다 돌면
    연결 회사인데 별도(OFS)만 받아 둔 기간의 CFS 를 받는다. 한도 초과(020)면 멈춘다."""
    limit = min(int(limit), FILL_CAP)
    U, _ = universe()
    CC = corpcodes()
    IX = report_index()
    F = set(os.listdir(FIN_DIR))
    want = {"11011": ("12", "사업보고서"), "11014": ("09", "분기보고서"), "11012": ("06", "반기보고서"), "11013": ("03", "분기보고서")}
    jobs, later = [], []
    for rp in ("11011", "11014", "11012", "11013"):
        mo, lab = want[rp]
        for y in sorted(FILL_YEARS, reverse=True):
            for u in U:
                code = u["code"]
                corp = (CC.get(code) or (None,))[0]
                ent = IX.get(code)
                if not corp or not ent or fy_month(ent) != 12:
                    continue
                reps = [r for r in ent["reports"] if r["stamp"] == "%d-%s" % (y, mo) and r["label"] == lab]
                if not reps:
                    continue
                cons = any(_has_cfs(r) for r in reps) if rp == "11011" else cons_year(ent, y)
                have = [d for d in ("CFS", "OFS") if ("%s_%d_%s_%s.json" % (corp, y, rp, d)) in F]
                if not have:
                    jobs.append((code, corp, y, rp, cons))
                elif have == ["OFS"] and cons:          # 연결 회사인데 별도만 받아 둔 기간 — 원장이 아예 없는 기간 다음에
                    later.append((code, corp, y, rp, True))
    jobs += later
    st = {"calls": 0, "stop": None, "status": collections.Counter(), "files": 0, "err": collections.Counter()}
    lock = threading.Lock()
    real = FIN.requests
    FIN.requests = _Counting(real)

    def one(job):
        code, corp, y, rp, cons = job
        for div in (("CFS", "OFS") if cons else ("OFS", "CFS")):
            if os.path.exists(os.path.join(FIN_DIR, "%s_%d_%s_%s.json" % (corp, y, rp, div))):
                continue                                # 이미 받은 쪽은 건너뛴다(부르는 것은 모두 네트워크 호출)
            with lock:
                if st["stop"] or st["calls"] >= limit:
                    st["stop"] = st["stop"] or "상한 %d콜" % limit
                    return
                st["calls"] += 1
            try:
                FIN.fetch_statement(corp, y, rp, div)
                s = getattr(_TL, "status", None)
            except Exception as e:                  # 메시지에 키가 든 주소가 들어 있을 수 있다 — 종류만 센다
                s = "예외:" + type(e).__name__
            with lock:
                st["status"][s] += 1
                if s == "020":
                    st["stop"] = "DART 한도 초과(020)"
                elif s not in ("000", "013"):
                    st["err"][s] += 1
                    if sum(st["err"].values()) >= 30:
                        st["stop"] = "오류 30건"
                if os.path.exists(os.path.join(FIN_DIR, "%s_%d_%s_%s.json" % (corp, y, rp, div))) and s == "000":
                    st["files"] += 1
                n = st["calls"]
            if verbose and n % 250 == 0:
                print("  … %d콜 %s" % (n, dict(st["status"])), flush=True)
            if s == "000":
                return
            if s != "013":
                return

    t = time.time()
    if verbose:
        need = collections.Counter(j[3] for j in jobs)
        print("채울 기간 %d (%s), 상한 %d콜" % (len(jobs), dict(need), limit), flush=True)
    try:
        with ThreadPoolExecutor(threads) as ex:
            list(ex.map(one, jobs))
    finally:
        FIN.requests = real
    if verbose:
        print("DART %d콜 · 응답 %s · 새 원장 %d · 멈춤 %s · %.0f초" % (
            st["calls"], dict(st["status"]), st["files"], st["stop"] or "-", time.time() - t))
    return st


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "빌드"
    if cmd == "점검":
        check()
    elif cmd == "채우기":
        fill(int(sys.argv[2]) if len(sys.argv) > 2 else FILL_CAP)
    else:
        check(build())
