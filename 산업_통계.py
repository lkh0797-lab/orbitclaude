# -*- coding: utf-8 -*-
"""
산업 성장률 — 섹터별 공개 통계 모으기 (2026-10-06)

산업_섹터.STATS 가 섹터마다 가리키는 공개 통계를 받아 .cache/산업/통계.json 하나로 묶는다.
회사 매출 합(산업.py)과 나란히 놓고 '업종 전체가 같은 방향으로 움직이나'를 보는 비교선이다.

  kosis     통계청 KOSIS 101/DT_1F02001 광공업생산지수 전국 · 업종별 원지수(2020=100) — 생산 T10 · 출하 T11 · 재고 T12
            101/DT_1F32001 제조업 생산능력지수 T10 · 가동률지수 원지수 T20. 'C' 제조업 전체를 같이 받는다
  util_mfg  101/DT_1F32002 제조업 평균가동률 T50(%)
  ecos      한국은행 ECOS 402Y014 수출물가지수(원화 기준 W) · 403Y002 수출물량지수 — STATS 'ecos' 품목
  item      402Y016 수출물가 품목별(STATS 'item' — 달러 D) + 401Y015 원유 수입물가(원화 W) → 'crude_import'
  bsi       512Y008 매출 전망 BSI('BB') · 512Y007 매출 실적 BSI('AB'). 주소는 BSI 코드 다음 업종 코드 순서(거꾸로면 빈 결과)
  gva       200Y104 실질 부가가치(계절조정) · 200Y105 명목 부가가치(원계열), 분기. 1103 제조업을 같이 받는다
  phys      물리량 — KOSIS DT_1F02012 품목 생산 T40(자동차용 엔진 · 에틸렌 · 경유), 363/TX_36301_A000 조강(철강협회),
            101/DT_1F48 기계수주 경상 해외수요(7) × 선박(92), 101/DT_1F48005 기계수주 불변 선박 제외(T4) 국내수요(1) × 계(0),
            101/DT_1G1B002 건설수주 경상 총액(발주자 0 × 공종 0)
  exports   관세청 품목국가별(관세청.품목국가별) — STATS 'hs' · 'hs_extra'(예: 8486 반도체 장비) 질의마다
            월별 수출 USD · kg, 최근 12개월 하위 HS 상위 5 · 수출국 상위 5
  exports6  STATS 'hs6'(6단위 — 850760 리튬이온 축전지 · 850790 축전지 부분품 · 284190 양극재)마다 월별 USD · kg.
            4단위 질의 응답의 6단위 행을 그대로 골라 쓴다(새 호출 없음). 4단위 부모가 질의 목록에 없으면 그것만 받는다(100회 한도)
  exports_total  관세청 수출입총괄(관세청.총괄) 월별 전체 수출 USD

기간: KOSIS · ECOS 월별 2010-01부터, 분기 2010Q1부터, 관세청 2015-01부터 나온 달까지.

통계.json: {v, built, latest: {kosis, ecos, customs, customs_total: 'YYYYMM', gva: 'YYYYQn'},
            kosis: {C261: {name, prod, ship, inv, capa, util}}, util_mfg, ecos: {코드: {name, xp, xv}},
            item: {코드 | 'crude_import': {name, cur, unit, v}}, bsi: {업종: {name, fc, act}}, gva: {항목: {name, real, nom}},
            phys: {키: {name, unit, v}}, exports: {HS: {name, usd, kg, sub12: [[hs, 이름, USD]], dest12: [[국가, 이름, %]]}},
            exports6: {HS6: {name, parent: 4단위 HS, usd, kg}},
            exports_total, fail: [..], empty: [..], calls: {kosis, ecos, customs}(이번 실행의 실제 호출 수)}
            시계열은 모두 {'YYYYMM' 또는 'YYYYQn': 값}. sub12 · dest12 는 품목국가별 마지막 달(latest.customs)까지 12개월 합.
            exports6 는 그 6단위 행이 처음 · 마지막으로 나온 달 사이, 부모(exports[parent])에 있는 달마다 값이 있다
            (사이에 행이 없는 달은 0, 처음 나오기 전 · 마지막 뒤는 비움 — HS 개정으로 생기거나 없어진 호를 0 으로 잇지 않게).
            국가 · 하위 HS 상위 목록(sub12 · dest12)은 없다(줄여 둔 저장분은 국가를 6단위로 나누지 않는다).

캐시: 원본 응답을 .cache/산업/raw/ 에 둔다(관세청 원본은 관세청.py 가 .cache/관세청 에).
      끝난 달만 담은 구간은 30일, 최근 달(이번 달 − 4개월 이후)이 들어간 구간은 2일. 다시 돌려도 싸다.
      관세청은 HS 질의 × 달력 연도마다 (월 × 하위 HS → [USD, kg], 월 × 국가 → USD)로 줄여 두고,
      이어 붙인 것을 raw/관세_{HS}.json(총괄은 관세_총괄.json)에 둔다 — 갱신은 여기에 최근 달만 덮어쓴다.
      KOSIS 는 한 번에 4만 셀까지라 업종을 나눠 부르고, 그래도 넘으면(err 31) 기간을 반으로 나눈다.
      받기가 실패하면 낡은 캐시를 쓰고, 그래도 비면 지난 통계.json 값을 쓰고 'fail' 에 적는다.
      표에 원래 값이 없는 시계열(C21 · C252 가동률, C311 · C313 재고 등)은 'empty' 에 적는다.

실행:
  python 산업_통계.py        전체(신선한 캐시는 건너뛴다)
  python 산업_통계.py 갱신   최근 석 달(월) · 두 분기만 다시 받고 나머지는 캐시(나이 무관)를 쓴다
  python 산업_통계.py 점검   만들어 둔 통계.json 으로 알려진 값 대조표만 찍는다
  python 산업_통계.py 범위   시계열마다 시작 ~ 끝 달과 개수

한계:
  - KOSIS 지수는 원지수(계절조정 아님) — 전년 같은 달 대비로 본다. C252(무기 · 총포탄)는 2020-01부터.
  - 디스플레이는 C262(전자부품) 안, 화장품은 C204(기타 화학제품) 안 — 섹터보다 넓은 업종 지수다.
  - 선박에는 ECOS 수출물가 · 물량 지수가 없다(척마다 값이 달라 지수를 안 낸다). 조선은 생산지수 · 수주액 · 통관 수출로 본다.
  - 수출물가는 원화 기준이라 환율 효과가 섞인다. 품목 가격(item)은 달러 기준.
  - 관세청 총괄은 품목국가별보다 한 달 먼저 나올 수 있다(2026-10-06 현재 총괄 2026-09, 품목국가별 2026-08 — latest.customs_total).
    먼저 나온 달은 15일경 정정될 수 있다.
  - 관세청은 통관(FOB, 신고) 기준. HS 2022 개정으로 8524(평판디스플레이 모듈)는 2022년부터, 그 전은 9013 에 있다.
    항공기 부품도 8807 은 2022년부터, 그 전은 8803. 이어 붙이기는 쓰는 쪽(산업.py)에서 한다.
  - 8541(개별 반도체 소자)에는 태양전지 · LED 가 들어 있다. 2022 개정 전 854140(감광성 소자 — 태양전지 · LED · 광센서)이
    2022년부터 854141 LED · 854142/854143 태양전지(셀/모듈) · 854149 기타 감광성으로 나뉘었다.
    2025 비중: 854129 트랜지스터(1W 이상) 31.3% · 854149 기타 감광성 17.9% · 854142+854143 태양전지 14.8% · 854141 LED 8.6% ·
    854110 다이오드 8.5% · 854121 트랜지스터(1W 미만) 7.8% · 854159 기타 5.2% · 나머지 6%. 8541 은 8541+8542 의 2.4%(2025).
  - exports6 검증(2026-10-06): 2025 연간을 6단위 직접 질의(hsSgn=850760 · 850790 · 284190, 10단위 행 합)와 대조해
    USD 가 1달러까지 같다(kg 은 반올림 ±5). 8507 은 6단위 8개 합 = 4단위 합(매달). 284190 은 니켈코발트망간 · 니켈코발트알루미늄
    산화물의 리튬염이 2025 의 97%(나머지 티탄산바륨 등), 850760 은 ESS용 56% · 전기차용 20% · 기타 24%.
  - 기계수주(선박 제외)는 불변 · 국내수요, 선박 수주는 경상 · 해외수요, 건설수주는 경상이다.
  - 자동차 생산 대수 · 조선 CGT · 해운 운임은 공개 API 가 없어 빠진다(엔진 대수 · 선박 수주액이 대신).

고친 것(2026-10-06 r2 — 리뷰 지적):
  - STATS 'hs6' 를 받아 exports6 를 만든다(전에는 6단위가 통계.json 에 없어 2차전지 수출에 납축전지 · 니켈 축전지가 섞였다 —
    2025 8507+2841 $12.27B 가운데 hs6 셋이 $9.98B, 81%).
  - STATS 'hs_extra'(8486 반도체 장비) 도 exports 에 넣는다 — 8486 이 'hs' 에서 빠지며 exports 에서 사라지지 않게.
    STATS 에서 빠진 9013 은 exports 에서도 빠진다(raw/관세_9013.json 저장분은 남는다).
  - 지난 통계.json 값으로 채우기(_fill)에 exports6 를 넣었다. 범위 · 점검 표에 exports6 줄을 더했다.

인증키는 .env 의 KOSIS_API_KEY · ECOS_API_KEY · DATA_GO_KR_KEY(설정.get) — 키와 키가 든 요청 주소는 화면 · 로그 · 캐시에 남기지 않는다.
"""
import os
import re
import sys
import json
import time
import hashlib
import datetime as dt

import requests

import 설정
import 관세청 as K
import 산업_섹터 as S

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache", "산업")
RAW = os.path.join(CACHE, "raw")
OUT = os.path.join(CACHE, "통계.json")
VER = 1

START_M = "201001"           # KOSIS · ECOS 월별
START_Q = "2010Q1"           # ECOS 분기
CUSTOMS_START = "201501"     # 관세청
TTL_OLD = 30 * 86400         # 끝난 달만 담은 구간
TTL_NEW = 2 * 86400          # 최근 달이 들어간 구간
RECENT_M = 4                 # '최근' = 이번 달 − 4개월부터(발표가 한 달 반 늦어 나온 달 기준 석 달)
RECENT_Q = 3                 # 분기는 이번 분기 − 3부터(나온 분기 기준 두 분기)
KOSIS_CELLS = 36000          # 4만 셀 한도에 여유
CUSTOMS_BUDGET = 1000        # 관세청 한 번 돌릴 때 실제 호출 상한(개발계정 하루 10,000회)
PARENT_BUDGET = 100          # 'hs6' 의 4단위 부모가 질의 목록에 없어 따로 받을 때 쓰는 호출 상한(부모 전부 합)

KOSIS_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/10000/%s"

# 물리량 — (키, 이름, 단위, orgId, tblId, 항목, {objL: 코드})
PHYS = [
    ("engine", "자동차용 엔진 생산", "대", "101", "DT_1F02012", "T40", {"objL1": "30130101"}),
    ("ethylene", "에틸렌 생산", "톤", "101", "DT_1F02012", "T40", {"objL1": "20120102"}),
    ("diesel", "경유 생산", "㎘", "101", "DT_1F02012", "T40", {"objL1": "19219204"}),
    ("crude_steel", "조강 생산", "천톤", "363", "TX_36301_A000", "16363AAA0", {"objL1": "15363AA1AA"}),
    ("ship_orders", "선박 수주(해외수요 · 경상)", "백만원", "101", "DT_1F48", "T1", {"objL1": "7", "objL2": "92"}),
    ("machine_orders", "기계수주(국내수요 · 선박 제외 · 불변)", "백만원", "101", "DT_1F48005", "T4", {"objL1": "1", "objL2": "0"}),
    ("construction_orders", "건설수주(총액 · 경상)", "백만원", "101", "DT_1G1B002", "T10", {"objL1": "0", "objL2": "0"}),
]

# STATS 'hs' 질의의 이름(응답 행은 한 단계 아래 HS 라 질의 자체의 이름은 응답에 없다)
HS_NAME = {
    "8542": "전자집적회로", "8541": "개별 반도체 소자(다이오드 · 트랜지스터 · 태양전지)", "8486": "반도체 · 디스플레이 제조장비",
    "8524": "평판디스플레이 모듈(2022~)", "9013": "액정 디바이스 · 광학기기(~2021 디스플레이 패널)",
    "8532": "축전기(MLCC 등)", "8534": "인쇄회로기판",
    "8507": "축전지", "2841": "옥소금속산염(양극재 등)",
    "8504": "변압기 · 정지형 변환기", "8535": "개폐 · 보호기기(1,000V 초과)", "8536": "개폐 · 보호 · 접속기기(1,000V 이하)",
    "8537": "배전반 · 제어반", "8544": "절연 전선 · 케이블",
    "8517": "전화기 · 통신기기", "8418": "냉장고 · 냉동고", "8450": "세탁기", "8415": "에어컨",
    "8703": "승용차", "8704": "화물자동차", "8708": "자동차 부품", "4011": "고무 타이어",
    "89": "선박 · 수상 구조물", "8408": "디젤 엔진(압축점화)",
    "9301": "군용 무기", "9306": "폭탄 · 탄약 · 미사일", "8710": "전차 · 장갑차", "8802": "항공기 · 우주선",
    "8803": "항공기 부품(~2021)", "8807": "항공기 부품(2022~)", "8411": "터보제트 · 가스터빈",
    "8429": "불도저 · 굴착기", "8427": "지게차", "8428": "기타 하역 · 운반 기계", "8457": "머시닝센터",
    "8458": "선반(금속 가공)", "8479": "기타 고유기능 기계",
    "72": "철강", "73": "철강 제품", "29": "유기화학품", "39": "플라스틱", "2710": "석유제품",
    "3002": "백신 · 혈액제제(바이오의약품)", "3004": "의약품(투여량)", "3304": "화장품",
    "1902": "면류(라면 등)", "2106": "기타 조제 식료품", "2202": "음료", "1905": "빵 · 과자", "2402": "담배",
}

# STATS 'hs6' 이름 — 응답의 6단위 이름은 '기타' · '부분품'처럼 부모 없이는 뜻이 안 서는 것이 있다
HS6_NAME = {
    "850760": "리튬이온 축전지",
    "850790": "축전지 부분품",
    "284190": "양극재(옥소금속산염 기타 — NCM · NCA 리튬염)",
}

CALLS = {"kosis": 0, "ecos": 0, "customs": 0}      # 실제 네트워크 호출 수
HITS = {"kosis": 0, "ecos": 0, "customs": 0}       # 캐시로 끝난 수
FAIL = []                                          # 받기 실패(낡은 캐시를 썼거나 못 받음)
EMPTY = []                                         # 표에 값이 없는 시계열(예: C21 가동률, C311 재고)


class 통계오류(RuntimeError):
    pass


# ───────────────────────── 공통

def _keys():
    return [v for v in (설정.get("KOSIS_API_KEY"), 설정.get("ECOS_API_KEY"), 설정.get("DATA_GO_KR_KEY")) if v]


def _scrub(t):
    """오류 문구에서 키를 지운다(requests 예외 문구에는 요청 주소가 통째로 들어간다)."""
    t = str(t)
    for v in _keys():
        t = t.replace(v, "***")
    return re.sub(r"(apiKey|serviceKey|crtfc_key)=[^&\s]+", r"\1=***", t)


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _save(path, d, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        if compact:
            json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _cached(kind, tag, ttl, fetch):
    """원본 캐시 .cache/산업/raw/{kind}_{해시}.json. ttl 안이면 캐시, 아니면 fetch(). fetch 가 실패하면 낡은 캐시."""
    path = os.path.join(RAW, "%s_%s.json" % (kind, hashlib.md5(tag.encode("utf-8")).hexdigest()[:16]))
    d = _load(path)
    if d is not None and time.time() - d.get("ts", 0) < ttl:
        HITS[kind] += 1
        return d["d"]
    try:
        data = fetch()
    except 통계오류 as e:
        if d is not None:
            FAIL.append("%s — 받기 실패, %s 캐시를 씀: %s" % (tag, time.strftime("%Y-%m-%d", time.localtime(d.get("ts", 0))), e))
            return d["d"]
        raise
    _save(path, {"ts": time.time(), "tag": tag, "d": data}, compact=True)
    return data


def _ym_add(ym, k):
    i = int(ym[:4]) * 12 + int(ym[4:6]) - 1 + k
    return "%04d%02d" % (i // 12, i % 12 + 1)


def _yq_add(yq, k):
    i = int(yq[:4]) * 4 + int(yq[5]) - 1 + k
    return "%04dQ%d" % (i // 4, i % 4 + 1)


def _n_months(a, b):
    return (int(b[:4]) * 12 + int(b[4:6])) - (int(a[:4]) * 12 + int(a[4:6])) + 1


def _now_m():
    return dt.date.today().strftime("%Y%m")


def _now_q():
    t = dt.date.today()
    return "%dQ%d" % (t.year, (t.month - 1) // 3 + 1)


def _windows(mode, cyc="M", start=None, end=None):
    """(시작, 끝, ttl) 구간들 — 앞 것부터 덮어쓴다.
    전체: 지난해까지(끝난 달이면 30일) + 올해(2일). 갱신: 그 둘은 캐시(나이 무관, 없으면 받는다) + 최근 구간(2일)."""
    inf = float("inf")
    if cyc == "Q":
        cur = _now_q()
        start = start or START_Q
        end = end or "%sQ4" % cur[:4]
        hist = (start, "%dQ4" % (int(cur[:4]) - 1))
        ytd = ("%sQ1" % cur[:4], end)
        rec = (_yq_add(cur, -RECENT_Q), end)
        cut = _yq_add(cur, -RECENT_Q)
    else:
        cur = _now_m()
        start = start or START_M
        end = end or cur
        hist = (start, "%d12" % (int(cur[:4]) - 1))
        ytd = (cur[:4] + "01", max(end, cur[:4] + "12"))         # 그해 12월로 고정 — 캐시 키가 한 해 동안 같다
        rec = (_ym_add(cur, -RECENT_M), end)
        cut = _ym_add(cur, -RECENT_M)
    old_ttl = TTL_NEW if hist[1] >= cut else TTL_OLD
    if mode == "갱신":
        return [(hist[0], hist[1], inf), (ytd[0], ytd[1], inf), (rec[0], rec[1], TTL_NEW)]
    return [(hist[0], hist[1], old_ttl), (ytd[0], ytd[1], TTL_NEW)]


def _num(x):
    try:
        v = float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return int(v) if v.is_integer() and abs(v) >= 1000 else v


# ───────────────────────── KOSIS

class _셀초과(Exception):
    """KOSIS err 31 — 캐시에 남기지 않고 기간을 나눠 다시 부른다."""


def _kosis_get(params, ttl):
    """KOSIS 한 번(캐시 거침). 행 = [C1, C2, ITM_ID, PRD_DE, DT, C1_NM, C2_NM, UNIT_NM]. 4만 셀 초과(err 31)면 기간을 반으로."""
    tag = "kosis|" + json.dumps(sorted(params.items()), ensure_ascii=False)

    def fetch():
        key = 설정.get("KOSIS_API_KEY")
        if not key:
            raise 통계오류("KOSIS_API_KEY 가 없다")
        js, last = None, None
        for k in range(3):
            CALLS["kosis"] += 1
            try:
                r = requests.get(KOSIS_URL, params=dict(params, apiKey=key, format="json", jsonVD="Y"), timeout=120)
                js = r.json()
                break
            except Exception as e:
                last = "%s %s" % (type(e).__name__, _scrub(e)[:160])
                time.sleep(2 + 3 * k)
        if js is None:
            raise 통계오류("KOSIS %s 연결 실패: %s" % (params.get("tblId"), last))
        if isinstance(js, dict):
            err = str(js.get("err") or "")
            if err == "30":                    # 데이터가 없다
                return []
            if err == "31":                    # 4만 셀 초과 — 기간을 나눈다
                raise _셀초과()
            raise 통계오류("KOSIS %s err %s %s" % (params.get("tblId"), err, _scrub(js.get("errMsg") or "")[:120]))
        return [[x.get("C1"), x.get("C2"), x.get("ITM_ID"), x.get("PRD_DE"), x.get("DT"),
                 x.get("C1_NM"), x.get("C2_NM"), x.get("UNIT_NM")] for x in js]

    try:
        return _cached("kosis", tag, ttl, fetch) or []
    except _셀초과:
        a, b = params["startPrdDe"], params["endPrdDe"]
        n = _n_months(a, b)
        if n < 2:
            raise 통계오류("KOSIS %s 한 달도 4만 셀을 넘는다" % params.get("tblId"))
        mid = _ym_add(a, n // 2 - 1)
        return (_kosis_get(dict(params, endPrdDe=mid), ttl)
                + _kosis_get(dict(params, startPrdDe=_ym_add(mid, 1)), ttl))


def _kosis_series(org, tbl, itms, codes, axis, mode, fixed=None):
    """여러 업종 · 항목을 구간마다 받아 {(코드, 항목): {YYYYMM: 값}}, {코드: 이름}, 단위."""
    out, names, unit = {}, {}, {}
    for a, b, ttl in _windows(mode):
        if a > b:
            continue
        per = max(1, KOSIS_CELLS // (len(itms) * max(1, _n_months(a, b))))
        for i in range(0, len(codes), per):
            grp = codes[i:i + per]
            p = {"method": "getList", "orgId": org, "tblId": tbl, "itmId": "+".join(itms) + "+",
                 "prdSe": "M", "startPrdDe": a, "endPrdDe": b, axis: "+".join(grp) + "+"}
            p.update(fixed or {})
            for c1, c2, itm, prd, v, n1, n2, u in _kosis_get(p, ttl):
                code = c2 if axis == "objL2" else c1
                x = _num(v)
                if x is None or not prd:
                    continue
                out.setdefault((code, itm), {})[prd] = x
                names[code] = (n2 if axis == "objL2" else n1) or names.get(code, "")
                if u:
                    unit[code] = u
    for k in out:
        out[k] = dict(sorted(out[k].items()))
    return out, names, unit


def build_kosis(mode):
    codes = ["C"] + sorted({c for st in S.STATS.values() for c in st.get("kosis", [])} - {"C"})
    kosis = {c: {"name": "", "prod": {}, "ship": {}, "inv": {}, "capa": {}, "util": {}} for c in codes}
    try:
        ser, names, _ = _kosis_series("101", "DT_1F02001", ["T10", "T11", "T12"], codes, "objL2", mode, {"objL1": "00+"})
        for (c, itm), v in ser.items():
            if c in kosis:
                kosis[c][{"T10": "prod", "T11": "ship", "T12": "inv"}[itm]] = v
        for c, n in names.items():
            if c in kosis:
                kosis[c]["name"] = n
    except 통계오류 as e:
        FAIL.append("KOSIS DT_1F02001 생산 · 출하 · 재고: %s" % e)
    try:
        ser, names, _ = _kosis_series("101", "DT_1F32001", ["T10", "T20"], codes, "objL1", mode)
        for (c, itm), v in ser.items():
            if c in kosis:
                kosis[c]["capa" if itm == "T10" else "util"] = v
                kosis[c]["name"] = kosis[c]["name"] or names.get(c, "")
    except 통계오류 as e:
        FAIL.append("KOSIS DT_1F32001 생산능력 · 가동률: %s" % e)
    util_mfg = {}
    try:
        ser, _, _ = _kosis_series("101", "DT_1F32002", ["T50"], ["C"], "objL1", mode)
        util_mfg = ser.get(("C", "T50"), {})
    except 통계오류 as e:
        FAIL.append("KOSIS DT_1F32002 평균가동률: %s" % e)
    for c, d in kosis.items():
        for k in ("prod", "ship", "inv", "capa", "util"):
            if not d[k]:
                EMPTY.append("kosis.%s.%s" % (c, k))
    return kosis, util_mfg


def build_phys(mode):
    phys = {}
    for key, name, unit, org, tbl, itm, objs in PHYS:
        axis = "objL1"
        code = objs["objL1"]
        fixed = {k: v + "+" for k, v in objs.items() if k != "objL1"}
        v = {}
        try:
            ser, _, _ = _kosis_series(org, tbl, [itm], [code], axis, mode, fixed)
            v = ser.get((code, itm), {})
        except 통계오류 as e:
            FAIL.append("KOSIS %s %s: %s" % (tbl, key, e))
        if not v:
            EMPTY.append("phys.%s" % key)
        phys[key] = {"name": name, "unit": unit, "v": v}
    return phys


# ───────────────────────── ECOS

def _ecos_get(tbl, cyc, a, b, codes, ttl):
    """ECOS StatisticSearch 한 번(캐시 거침) → {'name', 'unit', 'v': {TIME: 값}}. 데이터 없음(INFO-200)은 빈 v."""
    tag = "ecos|%s|%s|%s|%s|%s" % (tbl, cyc, a, b, "/".join(codes))

    def fetch():
        key = 설정.get("ECOS_API_KEY")
        if not key:
            raise 통계오류("ECOS_API_KEY 가 없다")
        js, last = None, None
        for k in range(3):
            CALLS["ecos"] += 1
            try:
                js = requests.get(ECOS_URL % (key, "/".join([tbl, cyc, a, b] + list(codes))), timeout=60).json()
                break
            except Exception as e:
                last = "%s %s" % (type(e).__name__, _scrub(e)[:160])
                time.sleep(2 + 3 * k)
        if js is None:
            raise 통계오류("ECOS %s %s 연결 실패: %s" % (tbl, "/".join(codes), last))
        if "StatisticSearch" not in js:
            res = js.get("RESULT") or {}
            if res.get("CODE") == "INFO-200":
                return {"name": "", "unit": "", "v": {}}
            raise 통계오류("ECOS %s %s %s %s" % (tbl, "/".join(codes), res.get("CODE"), _scrub(res.get("MESSAGE") or "")[:120]))
        rows = js["StatisticSearch"].get("row") or []
        v = {}
        for x in rows:
            n = _num(x.get("DATA_VALUE"))
            if n is not None and x.get("TIME"):
                v[x["TIME"]] = n
        r0 = rows[-1] if rows else {}
        nm = [(r0.get("ITEM_NAME%d" % i) or "").strip() for i in (1, 2, 3)]
        return {"name": " / ".join(n for n in nm if n), "unit": r0.get("UNIT_NAME") or "", "v": v}

    return _cached("ecos", tag, ttl, fetch)


def _ecos_series(tbl, cyc, codes, mode, label):
    """구간을 이어 붙인 한 시계열 → (이름, 단위, {TIME: 값}). 실패 · 빈 결과는 FAIL 에."""
    name, unit, v = "", "", {}
    end = _ym_add(_now_m(), 1) if cyc == "M" else None       # BSI 전망은 다음 달 것이 이번 달 말에 나온다
    for a, b, ttl in _windows(mode, cyc, end=end):
        if a > b:
            continue
        try:
            d = _ecos_get(tbl, cyc, a, b, codes, ttl)
        except 통계오류 as e:
            FAIL.append("%s: %s" % (label, e))
            continue
        v.update(d["v"])
        name = d["name"] or name
        unit = d["unit"] or unit
    if not v:
        EMPTY.append(label)
    return name, unit, dict(sorted(v.items()))


def build_ecos(mode):
    codes, items, bsis, gvas = [], [], [], ["1103"]
    for st in S.STATS.values():
        codes += [c for c in st.get("ecos", []) if c not in codes]
        items += [t for t in st.get("item", []) if t[0] not in [i[0] for i in items]]
        if st.get("bsi") and st["bsi"] not in bsis:
            bsis.append(st["bsi"])
        if st.get("gva") and st["gva"] not in gvas:
            gvas.append(st["gva"])

    ecos = {}
    for c in codes:
        n1, _, xp = _ecos_series("402Y014", "M", [c, "W"], mode, "ECOS 402Y014 %s" % c)
        n2, _, xv = _ecos_series("403Y002", "M", [c], mode, "ECOS 403Y002 %s" % c)
        ecos[c] = {"name": (n1 or n2).split(" / ")[0], "xp": xp, "xv": xv}

    item = {}
    for c, cur, label in items:
        _, unit, v = _ecos_series("402Y016", "M", [c, cur], mode, "ECOS 402Y016 %s" % c)
        item[c] = {"name": label, "cur": cur, "unit": unit, "v": v}
    _, unit, v = _ecos_series("401Y015", "M", ["201121AA", "W"], mode, "ECOS 401Y015 원유")
    item["crude_import"] = {"name": "원유 수입물가", "cur": "W", "unit": unit, "v": v}

    bsi = {}
    for c in bsis:
        n1, _, fc = _ecos_series("512Y008", "M", ["BB", c], mode, "ECOS 512Y008 BB %s" % c)
        n2, _, act = _ecos_series("512Y007", "M", ["AB", c], mode, "ECOS 512Y007 AB %s" % c)
        nm = (n1 or n2).split(" / ")
        bsi[c] = {"name": nm[1] if len(nm) > 1 else nm[0], "fc": fc, "act": act}

    gva = {}
    for c in gvas:
        n1, _, real = _ecos_series("200Y104", "Q", [c], mode, "ECOS 200Y104 %s" % c)
        n2, _, nom = _ecos_series("200Y105", "Q", [c], mode, "ECOS 200Y105 %s" % c)
        gva[c] = {"name": (n1 or n2).split(" / ")[0], "real": real, "nom": nom}
    return ecos, item, bsi, gva


# ───────────────────────── 관세청

def _k_path(name, params):
    """관세청.py 가 응답을 두는 캐시 파일 경로(같은 규칙) — 실제 호출이 일어났는지 세는 데만 쓴다."""
    tag = hashlib.md5(json.dumps([name, sorted(params.items())], ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return os.path.join(K.CACHE, "%s_%s.json" % (name, tag))


def _k_called(name, params, t0):
    p = _k_path(name, params)
    return os.path.exists(p) and os.path.getmtime(p) >= t0 - 1


def _customs_chunks():
    """달력 연도 구간(2015-01 ~ 지난달). (시작, 끝, ttl) — 끝난 달만이면 30일, 최근 달이 들면 2일."""
    end = _ym_add(_now_m(), -1)
    cut = _ym_add(_now_m(), -RECENT_M)
    out = []
    for y in range(int(CUSTOMS_START[:4]), int(end[:4]) + 1):
        a = max("%d01" % y, CUSTOMS_START)
        b = min("%d12" % y, end)
        out.append((a, b, TTL_NEW if b >= cut else TTL_OLD))
    return out


def _customs_recent():
    """갱신 구간 — 이번 달 − 4개월 ~ 지난달(나온 달 기준 석 달)."""
    return [(_ym_add(_now_m(), -RECENT_M), _ym_add(_now_m(), -1), TTL_NEW)]


def _store(name):
    """HS 질의마다 이어 붙인 월별 자료(.cache/산업/raw/관세_{HS}.json) — 갱신은 여기에 최근 달만 덮어쓴다."""
    return os.path.join(RAW, "관세_%s.json" % name)


def _clean(s):
    s = re.sub(r"\[[^\]]*\]", "", s or "").strip()
    return s if len(s) <= 40 else s[:39] + "…"


def _customs_hs(hs, mode, cap=None):
    """HS 질의 하나 → {'m': {YYYYMM: {'sub': {하위HS: [USD, kg]}, 'cty': {국가: USD}}}, 'sn': 하위HS 이름, 'cn': 국가 이름}.
    cap = 이 질의에서 CALLS['customs'] 가 넘지 말아야 할 값(없으면 CUSTOMS_BUDGET)."""
    cap = min(CUSTOMS_BUDGET, CUSTOMS_BUDGET if cap is None else cap)
    store = _load(_store(hs)) if mode == "갱신" else None
    merged = store or {"m": {}, "sn": {}, "cn": {}}
    for a, b, ttl in (_customs_recent() if store else _customs_chunks()):
        tag = "customs|%s|%s|%s" % (hs, a, b)

        def fetch(a=a, b=b):
            if CALLS["customs"] >= cap:
                raise 통계오류("관세청 호출 예산을 다 썼다(%s — 상한 %d)" % (hs, cap))
            t0 = time.time()
            try:
                rows = K.품목국가별(a, b, hs=hs)
            except K.관세청오류 as e:
                CALLS["customs"] += 1                # 관세청오류는 요청을 보낸 뒤에 난다(키 없음 제외)
                raise 통계오류("관세청 %s %s-%s: %s" % (hs, a, b, _scrub(e)[:160]))
            if _k_called("품목국가별", {"strtYymm": a, "endYymm": b, "hsSgn": hs}, t0):
                CALLS["customs"] += 1
            m, sn, cn, tot, ssum = {}, {}, {}, None, 0.0
            for r in rows:
                if r.get("year") == "총계" or r.get("hsCd") in (None, "", "-"):
                    if r.get("year") == "총계":
                        tot = r.get("expDlr")
                    continue
                ym = (r.get("year") or "").replace(".", "")
                if not re.fullmatch(r"\d{6}", ym):
                    continue
                usd, kg = r.get("expDlr") or 0, r.get("expWgt") or 0
                d = m.setdefault(ym, {"sub": {}, "cty": {}})
                c = d["sub"].setdefault(r["hsCd"], [0, 0])
                c[0] += usd
                c[1] += kg
                cc = r.get("statCd") or "-"
                d["cty"][cc] = d["cty"].get(cc, 0) + usd
                sn[r["hsCd"]] = _clean(r.get("statKor"))
                cn[cc] = r.get("statCdCntnKor1") or cc
                ssum += usd
            for d in m.values():                      # 정수로 줄인다(캐시 크기)
                d["sub"] = {k: [int(round(x[0])), int(round(x[1]))] for k, x in d["sub"].items()}
                d["cty"] = {k: int(round(x)) for k, x in d["cty"].items() if x}
            return {"m": m, "sn": sn, "cn": cn, "tot": tot, "sum": int(round(ssum))}

        try:
            red = _cached("customs", tag, ttl, fetch)
        except 통계오류 as e:
            FAIL.append(str(e))
            continue
        if red.get("tot") is not None and abs((red.get("sum") or 0) - red["tot"]) > max(1.0, 0.001 * abs(red["tot"])):
            FAIL.append("관세청 %s %s-%s 행 합 %s ≠ 총계 %s" % (hs, a, b, red.get("sum"), red["tot"]))
        merged["m"].update(red["m"])
        merged["sn"].update(red["sn"])
        merged["cn"].update(red["cn"])
    if merged["m"]:
        merged["m"] = dict(sorted(merged["m"].items()))
        _save(_store(hs), merged, compact=True)
    return merged


def _customs_total(mode):
    """관세청 총괄 월별 전체 수출 USD {YYYYMM: USD}."""
    store = _load(_store("총괄")) if mode == "갱신" else None
    out = store or {}
    for a, b, ttl in (_customs_recent() if store else _customs_chunks()):
        tag = "customs_total|%s|%s" % (a, b)

        def fetch(a=a, b=b):
            t0 = time.time()
            try:
                rows = K.총괄(a, b)
            except K.관세청오류 as e:
                CALLS["customs"] += 1
                raise 통계오류("관세청 총괄 %s-%s: %s" % (a, b, _scrub(e)[:160]))
            if _k_called("총괄", {"strtYymm": a, "endYymm": b}, t0):
                CALLS["customs"] += 1
            v = {}
            for r in rows:
                ym = (r.get("year") or "").replace(".", "")
                if re.fullmatch(r"\d{6}", ym) and r.get("expDlr") is not None:
                    v[ym] = int(round(r["expDlr"]))
            return v

        try:
            out.update(_cached("customs", tag, ttl, fetch))
        except 통계오류 as e:
            FAIL.append(str(e))
    out = dict(sorted(out.items()))
    if out:
        _save(_store("총괄"), out, compact=True)
    return out


def _hs_lists():
    """(4 · 2단위 질의 목록, 'hs6' 목록, 'hs6' 때문에 따로 받아야 할 4단위 부모, hs_extra 이름).
    질의 목록 = STATS 'hs' + 'hs_extra'. 6단위의 부모는 앞 네 자리(4단위 질의의 응답 행이 6단위라서)."""
    hss, hs6, extra = [], [], {}
    for st in S.STATS.values():
        hss += [h for h in st.get("hs", []) if h not in hss]
        for t in st.get("hs_extra", []):
            extra.setdefault(t[0], t[1])
            if t[0] not in hss:
                hss.append(t[0])
        hs6 += [h for h in st.get("hs6", []) if h not in hs6]
    parents = []
    for c in hs6:
        if len(c) != 6 or not c.isdigit():
            raise 통계오류("STATS hs6 %r 는 6자리 숫자가 아니다" % c)
        if c[:4] not in hss and c[:4] not in parents:
            parents.append(c[:4])
    return hss, hs6, parents, extra


def build_exports6(hs6, got):
    """'hs6' 마다 4단위 부모 저장분의 6단위 행 → {HS6: {name, parent, usd, kg}}.
    그 6단위 행이 처음 나온 달 ~ 마지막 달 사이 부모의 달마다 값(사이에 행이 없는 달은 0). 처음 나오기 전은 비워 둔다 —
    HS 개정으로 새로 생긴 호(예: 854142)가 앞을 0 으로 채워 증가율이 부풀지 않게(산업.py 는 첫 달로 증가율 시작을 정한다)."""
    out = {}
    for c in hs6:
        p = c[:4]
        mm = got.get(p) or {"m": {}, "sn": {}}
        seen = [ym for ym, d in mm["m"].items() if c in d["sub"]]
        usd, kg = {}, {}
        for ym, d in sorted(mm["m"].items()):
            if not seen or not min(seen) <= ym <= max(seen):
                continue
            x = d["sub"].get(c) or [0, 0]
            usd[ym], kg[ym] = x[0], x[1]
        sn = mm["sn"].get(c) or ""
        out[c] = {"name": HS6_NAME.get(c) or ("%s — %s" % (HS_NAME.get(p, p), sn) if sn else c),
                  "parent": p, "usd": usd, "kg": kg}
        if not any(usd.values()):
            EMPTY.append("exports6.%s" % c)
    return out


def build_customs(mode, log=print):
    """→ (exports, exports6, exports_total, 품목 최신 달). 총괄은 품목국가별보다 한 달 먼저 나올 수 있어
    최근 12개월 창은 품목국가별에 실제로 있는 마지막 달로 잡는다."""
    hss, hs6, parents, extra = _hs_lists()
    total = _customs_total(mode)
    got = {}
    p0 = None
    todo = hss + parents
    for i, hs in enumerate(todo, 1):
        t = time.time()
        c0 = CALLS["customs"]
        cap = None
        if hs in parents:                                   # 'hs6' 때문에만 받는 부모 — 따로 100회 한도
            p0 = c0 if p0 is None else p0
            cap = p0 + PARENT_BUDGET
        got[hs] = _customs_hs(hs, mode, cap)
        log("  관세청 %2d/%d %-6s %3d개월  호출 %d  %.1fs%s" % (i, len(todo), hs, len(got[hs]["m"]), CALLS["customs"] - c0,
                                                       time.time() - t, "  (hs6 부모)" if hs in parents else ""))
    months = [ym for mm in got.values() for ym, d in mm["m"].items() if any(x[0] for x in d["sub"].values())]
    latest = max(months) if months else None
    exports = {}
    for hs, mm in got.items():
        usd = {ym: sum(x[0] for x in d["sub"].values()) for ym, d in sorted(mm["m"].items())}
        kg = {ym: sum(x[1] for x in d["sub"].values()) for ym, d in sorted(mm["m"].items())}
        sub, cty = {}, {}
        if latest:
            win = {_ym_add(latest, -k) for k in range(12)}
            for ym, d in mm["m"].items():
                if ym in win:
                    for h, x in d["sub"].items():
                        sub[h] = sub.get(h, 0) + x[0]
                    for c, x in d["cty"].items():
                        cty[c] = cty.get(c, 0) + x
        tot12 = sum(cty.values()) or 1
        top = lambda d: [kv for kv in sorted(d.items(), key=lambda kv: -kv[1]) if kv[1] > 0][:5]
        exports[hs] = {
            "name": HS_NAME.get(hs) or extra.get(hs) or hs,
            "usd": usd, "kg": kg,
            "sub12": [[h, mm["sn"].get(h, h), int(v)] for h, v in top(sub)],
            "dest12": [[c, mm["cn"].get(c, c), round(100.0 * v / tot12, 1)] for c, v in top(cty)],
        }
        if not usd:
            EMPTY.append("exports.%s" % hs)
    return exports, build_exports6(hs6, got), total, latest


# ───────────────────────── 조립

_PERIOD = re.compile(r"^\d{6}$|^\d{4}Q\d$")


def _fill(new, old, path=""):
    """이번에 비어 버린 시계열은 지난 통계.json 값으로 채운다(받기 실패로 화면이 비지 않게)."""
    if not isinstance(new, dict) or not isinstance(old, dict):
        return
    for k, ov in old.items():
        if not isinstance(ov, dict) or not ov:
            continue
        nv = new.get(k)
        if all(_PERIOD.match(str(x)) for x in ov):
            if not nv:
                new[k] = ov
                FAIL.append("%s%s — 이번에 비어 지난 통계.json 값을 씀" % (path, k))
        elif isinstance(nv, dict):
            _fill(nv, ov, path + k + ".")


def _prune(days=90):
    """전체 실행 끝에 오래된 원본 캐시를 지운다 — 갱신 구간은 달마다 새 키라 쌓인다.
    전체 실행이 쓰는 파일은 30일 안에 다시 쓰이므로 90일 넘은 것은 안 쓰는 것. 이어 붙인 관세_*.json 은 남긴다."""
    n, cut = 0, time.time() - days * 86400
    for f in os.listdir(RAW) if os.path.isdir(RAW) else []:
        p = os.path.join(RAW, f)
        if f.startswith(("kosis_", "ecos_", "customs_")) and os.path.getmtime(p) < cut:
            os.remove(p)
            n += 1
    return n


def build(mode="전체", log=print):
    """통계.json 을 만든다. mode = '전체' | '갱신'. 돌려주는 값은 쓴 dict."""
    if mode == "갱신" and not os.path.exists(OUT):
        mode = "전체"
    for d in (CALLS, HITS):
        for k in d:
            d[k] = 0
    del FAIL[:]
    del EMPTY[:]
    t0 = time.time()
    log("산업 통계 — %s" % mode)
    kosis, util_mfg = build_kosis(mode)
    phys = build_phys(mode)
    log("  KOSIS 끝 — 호출 %d · 캐시 %d (%.0fs)" % (CALLS["kosis"], HITS["kosis"], time.time() - t0))
    ecos, item, bsi, gva = build_ecos(mode)
    log("  ECOS 끝 — 호출 %d · 캐시 %d (%.0fs)" % (CALLS["ecos"], HITS["ecos"], time.time() - t0))
    exports, exports6, total, c_latest = build_customs(mode, log)
    log("  관세청 끝 — 호출 %d · 캐시 %d (%.0fs)" % (CALLS["customs"], HITS["customs"], time.time() - t0))

    def mx(series_list):
        ks = [max(s) for s in series_list if s]
        return max(ks) if ks else None

    out = {
        "v": VER,
        "built": time.strftime("%Y-%m-%d %H:%M"),
        "latest": {
            "kosis": mx([kosis.get("C", {}).get("prod", {})] + [d["prod"] for d in kosis.values()]),
            "ecos": mx([d["xp"] for d in ecos.values()] + [d["xv"] for d in ecos.values()]),
            "customs": c_latest,                                   # 품목국가별(exports) 마지막 달
            "customs_total": max(total) if total else None,         # 총괄(exports_total) 마지막 달 — 잠정치로 한 달 앞설 수 있다
            "gva": mx([d["real"] for d in gva.values()]),
        },
        "kosis": kosis,
        "util_mfg": util_mfg,
        "ecos": ecos,
        "item": item,
        "bsi": bsi,
        "gva": gva,
        "phys": phys,
        "exports": exports,
        "exports6": exports6,                                      # STATS 'hs6' — 4단위 부모 응답의 6단위 행
        "exports_total": total,
        "fail": list(FAIL),
        "empty": list(EMPTY),
        "calls": dict(CALLS),                                      # 이번 실행의 실제 호출 수
    }
    old = load()
    if old and old.get("v") == VER:
        for k in ("kosis", "util_mfg", "ecos", "item", "bsi", "gva", "phys", "exports", "exports6", "exports_total"):
            if k in ("util_mfg", "exports_total"):
                _fill(out, {k: old.get(k) or {}})
            else:
                _fill(out[k], old.get(k) or {}, k + ".")
        out["fail"] = list(FAIL)
    _save(OUT, out, compact=True)
    if mode == "전체" and not FAIL:                     # 실패가 있으면 낡은 캐시가 대신 쓰였을 수 있어 안 지운다
        n = _prune()
        if n:
            log("  오래된 원본 캐시 %d개 지움" % n)
    log("  저장 %s (%.0f KB, %.0fs)" % (os.path.relpath(OUT, BASE), os.path.getsize(OUT) / 1024, time.time() - t0))
    return out


def load():
    """통계.json (없으면 None)."""
    return _load(OUT)


# ───────────────────────── 대조

def _yoy(s, ym):
    p = _ym_add(ym, -12)
    if not s or ym not in s or p not in s or not s[p]:
        return None
    return (s[ym] / s[p] - 1) * 100


def _ysum(s, y):
    ks = [k for k in (s or {}) if k[:4] == str(y)]
    return sum(s[k] for k in ks) if len(ks) == 12 else None


def 점검(d=None, log=print):
    """2026-10-06 점검 메모(r3)의 알려진 값과 대조. [(항목, 기대, 실제, 맞나)]."""
    d = d or load() or {}
    g = lambda *ks: _dig(d, ks)
    rows = []

    def chk(label, want, got, tol, fmt="%.1f"):
        ok = got is not None and abs(got - want) <= tol
        rows.append((label, fmt % want, "-" if got is None else fmt % got, ok))

    c261 = g("kosis", "C261", "prod") or {}
    chk("KOSIS C261 생산 T10 2026-08", 187.8, c261.get("202608"), 0.05)
    chk("KOSIS C261 생산 전년비 % 2026-08", 1.4, _yoy(c261, "202608"), 0.15)
    c301 = g("kosis", "C301", "prod") or {}
    chk("KOSIS C301 생산 T10 2026-08", 70.7, c301.get("202608"), 0.05)
    chk("KOSIS C301 생산 전년비 % 2026-08", -35.3, _yoy(c301, "202608"), 0.15)
    chk("KOSIS C 제조업 생산 T10 2026-08", 110.0, (g("kosis", "C", "prod") or {}).get("202608"), 0.05)
    chk("KOSIS C261 생산능력 T10 2026-08", 196.7, (g("kosis", "C261", "capa") or {}).get("202608"), 0.05)
    chk("KOSIS C261 가동률지수 T20 2026-08", 93.3, (g("kosis", "C261", "util") or {}).get("202608"), 0.05)
    chk("KOSIS 평균가동률 % 2026-08", 70.8, (d.get("util_mfg") or {}).get("202608"), 0.05)
    ex = d.get("exports") or {}
    for hs, want in (("8542", 142.83), ("89", 29.87), ("2710", 44.56), ("8703", 68.55), ("72", 22.79), ("39", 33.84)):
        s = _ysum((ex.get(hs) or {}).get("usd"), 2025)
        chk("관세청 %s 2025 수출 $B" % hs, want, None if s is None else s / 1e9, 0.005 * want + 0.01, "%.2f")
    # 6단위 — 기대값은 6단위 직접 질의(hsSgn=6자리, 10단위 행 합, 2026-10-06)로 받은 2025 연간
    ex6 = d.get("exports6") or {}
    for hs, want in (("850760", 4.2863), ("850790", 0.6907), ("284190", 5.0030)):
        s = _ysum((ex6.get(hs) or {}).get("usd"), 2025)
        chk("관세청 %s 2025 수출 $B(6단위)" % hs, want, None if s is None else s / 1e9, 0.0005, "%.4f")
    bad = n = 0
    for hs, x in ex6.items():                          # 6단위 ≤ 부모 4단위, 처음 ~ 마지막 달 사이 부모 달이 다 있다
        pu = (ex.get(x.get("parent")) or {}).get("usd") or {}
        u = x.get("usd") or {}
        n += len(u)
        bad += sum(1 for ym, v in u.items() if ym not in pu or v > pu[ym])
        if u:
            bad += sum(1 for ym in pu if min(u) <= ym <= max(u) and ym not in u)
    chk("exports6 가 부모를 넘거나 달이 빈 칸(%d칸 중)" % n, 0, bad if ex6 else None, 0, "%.0f")
    xv = g("ecos", "30911AA", "xv") or {}
    chk("ECOS 403Y002 30911AA 전년비 % 2026-08", 11.2, _yoy(xv, "202608"), 0.15)
    chk("ECOS 403Y002 31211AA 전년비 % 2026-08", -28.2, _yoy(g("ecos", "31211AA", "xv") or {}, "202608"), 0.15)
    chk("ECOS 402Y016 DRAM(D) 전년비 % 2026-08", 249.0, _yoy(g("item", "30911201AA", "v") or {}, "202608"), 1.0, "%.0f")
    chk("ECOS 401Y015 원유(W) 전년비 % 2026-08", 28.3, _yoy(g("item", "crude_import", "v") or {}, "202608"), 0.15)
    chk("ECOS 512Y008 BB C2600 2026-10", 113, (g("bsi", "C2600", "fc") or {}).get("202610"), 0.5, "%.0f")
    r = g("gva", "110309", "real") or {}
    q = r.get("2026Q2"), r.get("2025Q2")
    chk("ECOS 200Y104 110309 전년비 % 2026Q2", 20.6, (q[0] / q[1] - 1) * 100 if all(q) else None, 0.15)
    ph = d.get("phys") or {}
    chk("조강 2026-08 천톤", 5353, ((ph.get("crude_steel") or {}).get("v") or {}).get("202608"), 0.5, "%.0f")
    chk("조강 전년비 % 2026-08", 2.6, _yoy((ph.get("crude_steel") or {}).get("v"), "202608"), 0.15)
    chk("에틸렌 2026-08 톤", 717280, ((ph.get("ethylene") or {}).get("v") or {}).get("202608"), 0.5, "%.0f")
    chk("자동차용 엔진 2026-08 대", 275979, ((ph.get("engine") or {}).get("v") or {}).get("202608"), 0.5, "%.0f")
    chk("경유 생산 전년비 % 2026-08", -6.1, _yoy((ph.get("diesel") or {}).get("v"), "202608"), 0.15)
    s = _ysum((ph.get("ship_orders") or {}).get("v"), 2025)
    chk("해외 선박 수주 2025 조원", 52.0, None if s is None else s / 1e6, 0.05)
    co = (ph.get("construction_orders") or {}).get("v") or {}
    chk("건설수주 2026-08 조원", 14.39, co["202608"] / 1e6 if "202608" in co else None, 0.005, "%.2f")
    chk("건설수주 전년비 % 2026-08", -10.6, _yoy(co, "202608"), 0.15)

    w = max(len(r[0]) for r in rows) if rows else 10
    log("%-*s %12s %12s  판정" % (w, "항목", "기대", "실제"))
    for lab, want, got, ok in rows:
        log("%-*s %12s %12s  %s" % (w, lab, want, got, "OK" if ok else "X"))
    log("맞음 %d / %d" % (sum(1 for r in rows if r[3]), len(rows)))
    return rows


def _dig(d, ks):
    for k in ks:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def 범위(d=None, log=print):
    """시계열마다 (시작, 끝, 개수) — 보고용."""
    d = d or load() or {}
    out = []

    def add(name, s):
        out.append((name, min(s) if s else "-", max(s) if s else "-", len(s or {})))

    for c, x in (d.get("kosis") or {}).items():
        for k in ("prod", "ship", "inv", "capa", "util"):
            add("kosis.%s.%s" % (c, k), x.get(k))
    add("util_mfg", d.get("util_mfg"))
    for c, x in (d.get("ecos") or {}).items():
        add("ecos.%s.xp" % c, x.get("xp"))
        add("ecos.%s.xv" % c, x.get("xv"))
    for c, x in (d.get("item") or {}).items():
        add("item.%s" % c, x.get("v"))
    for c, x in (d.get("bsi") or {}).items():
        add("bsi.%s.fc" % c, x.get("fc"))
        add("bsi.%s.act" % c, x.get("act"))
    for c, x in (d.get("gva") or {}).items():
        add("gva.%s.real" % c, x.get("real"))
        add("gva.%s.nom" % c, x.get("nom"))
    for c, x in (d.get("phys") or {}).items():
        add("phys.%s" % c, x.get("v"))
    for c, x in (d.get("exports") or {}).items():
        add("exports.%s.usd" % c, x.get("usd"))
    for c, x in (d.get("exports6") or {}).items():
        add("exports6.%s.usd" % c, x.get("usd"))
    add("exports_total", d.get("exports_total"))
    for r in out:
        log("  %-28s %s ~ %s  (%d)" % r)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    arg = sys.argv[1] if len(sys.argv) > 1 else "전체"
    if arg == "점검":
        점검()
        sys.exit(0)
    if arg == "범위":
        범위()
        sys.exit(0)
    t = time.time()
    res = build("갱신" if arg == "갱신" else "전체")
    print()
    점검(res)
    print("호출: KOSIS %(kosis)d · ECOS %(ecos)d · 관세청 %(customs)d" % CALLS,
          "| 캐시: KOSIS %(kosis)d · ECOS %(ecos)d · 관세청 %(customs)d" % HITS)
    print("빈 시계열 %d건: %s" % (len(res["empty"]), ", ".join(res["empty"])))
    print("실패 %d건" % len(res["fail"]))
    for f in res["fail"]:
        print("  -", f)
    print("걸린 시간 %.0f초" % (time.time() - t))
