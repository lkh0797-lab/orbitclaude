# -*- coding: utf-8 -*-
"""
호재 탐지 — DART 전체 공시를 훑어 보고서명으로 호재를 분류한다.

원리는 단순하다. 한국 공시는 보고서명이 규격화돼 있어서 이름만으로도
무슨 일이 벌어졌는지 대부분 판별된다. 본문을 열지 않아도 된다는 뜻이고,
그래서 전 종목을 실시간에 가깝게 훑을 수 있다.

주의해서 만든 것 하나 — 이름만으로는 방향을 알 수 없는 공시가 있다.
  * 유상증자결정: 제3자배정이면 전략적 투자 유치(호재), 주주배정이면 희석(악재)
  * 매출액또는손익구조 30% 이상 변동: 증가인지 감소인지 이름에 없다
  * 최대주주변경: 인수인이 누구냐에 따라 갈린다
이런 건 '확인필요'로 따로 묶는다. 호재로 단정하면 그게 더 해롭다.
악재 공시도 같이 분류해 호재와 섞이지 않게 한다.
"""
import os
import re
import json
import time
import datetime as dt

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE, ".cache", "호재")
API = "https://opendart.fss.or.kr/api/list.json"

# (범주, 패턴, 강도 1~3, 설명)
# 강도는 주가에 미치는 통상적 크기가 아니라 '신호가 얼마나 분명한가'다.
GOOD = [
    ("설비투자", r"신규시설투자등|유형자산\s*취득\s*결정|시설투자", 3,
     "증설·신규 라인. 회사가 수요를 확신할 때만 돈을 묻는다"),
    ("대형수주", r"단일판매.?공급계약\s*체결|수주\s*계약|공급계약\s*체결", 3,
     "매출로 직결되는 계약. 매출 대비 비중을 꼭 확인할 것"),
    ("자사주매입", r"자기주식\s*취득\s*결정|자기주식취득\s*신탁계약\s*체결", 2,
     "유통 주식 감소. 경영진이 저평가로 판단했다는 신호"),
    ("자사주소각", r"자기주식\s*소각\s*결정", 3,
     "소각은 되돌릴 수 없다. 매입보다 강한 주주환원"),
    ("배당확대", r"현금.?현물배당\s*결정|배당\s*결정", 1,
     "배당 정책 변화. 금액을 직접 비교해야 의미가 있다"),
    ("무상증자", r"무상증자\s*결정", 2, "주주가치 제고 목적의 신주 발행"),
    ("M&A·지분투자", r"타법인\s*주식\s*및\s*출자증권\s*취득\s*결정|영업양수|회사합병\s*결정|"
     r"주식교환|포괄적\s*주식", 2, "인수·합병. 대상과 가격을 봐야 한다"),
    ("메자닌 소각", r"전환사채\s*(취득|소각)|신주인수권부사채\s*(취득|소각)|"
     r"사채\s*조기\s*상환", 3, "잠재 물량(오버행) 해소"),
    ("내부자 매수", r"임원.?주요주주\s*특정증권등\s*소유상황보고서", 1,
     "내부자 지분 변동. 매수인지 매도인지는 내용을 봐야 한다"),
    ("대량보유 변동", r"주식등의\s*대량보유상황보고서", 1,
     "5% 룰. 신규 취득인지 처분인지 내용 확인 필요"),
    ("기술·지식재산", r"특허권\s*취득|기술\s*(도입|이전|제휴)|라이선스|기술수출", 2,
     "기술 자산 확보 또는 수출"),
    ("임상·인허가", r"임상시험|품목\s*허가|허가\s*취득|승인\s*획득|FDA", 2,
     "바이오·제약의 가치 변곡점"),
    ("국책과제", r"국책과제|국가연구개발|정부\s*과제\s*선정", 2,
     "정부 과제 선정. 기술력 검증과 자금 유입"),
    ("실적 공시", r"영업\(잠정\)실적|연결재무제표기준\s*영업\(잠정\)실적", 2,
     "잠정 실적. 컨센서스와 대조할 것"),
    ("거래재개", r"거래\s*재개|매매거래\s*정지\s*해제", 3, "정지 사유 해소"),
    ("채무구조 개선", r"채무\s*면제|출자전환|채무\s*재조정", 2, "재무 부담 경감"),
    ("투자판단 주요사항", r"투자판단\s*관련\s*주요경영사항", 1,
     "규격 외 중요 사안이 여기로 들어온다. 내용을 직접 봐야 한다"),
]

# 이름만으로 방향을 못 정하는 것들. 호재로 단정하지 않는다.
CHECK = [
    ("유상증자(배정방식 확인)", r"유상증자\s*결정",
     "제3자배정이면 전략적 투자 유치, 주주배정·일반공모면 희석이다"),
    ("손익구조 변동", r"매출액\s*또는\s*손익구조\s*\d+%|손익구조\s*변동",
     "증가인지 감소인지 보고서명에 없다"),
    ("최대주주 변경", r"최대주주\s*변경",
     "인수인이 누구냐에 따라 호재도 악재도 된다"),
    ("조회공시 답변", r"조회공시\s*(요구|답변)|풍문\s*또는\s*보도",
     "'사실' 답변이면 호재 확정, '사실무근'이면 반대"),
]

# 호재 목록에 섞이면 안 되는 것들
BAD = [
    ("유동성 위험", r"횡령|배임|부도|당좌거래\s*정지|회생절차|파산"),
    ("감사 문제", r"감사의견\s*(거절|한정|부적정)|감사보고서\s*제출\s*지연"),
    ("상장 위험", r"관리종목|상장폐지|투자주의환기|매매거래\s*정지"),
    ("희석", r"전환사채권\s*발행\s*결정|신주인수권부사채권\s*발행\s*결정|교환사채권\s*발행"),
    ("소송·제재", r"소송\s*등의\s*제기|벌금|과징금|제재"),
]

GOOD = [(n, re.compile(p), w, d) for n, p, w, d in GOOD]
CHECK = [(n, re.compile(p), d) for n, p, d in CHECK]
BAD = [(n, re.compile(p)) for n, p in BAD]

AMEND_RE = re.compile(r"^\[(기재정정|첨부정정|첨부추가|정정)\]")


def classify(report_nm):
    """보고서명 -> (구분, 범주, 강도, 설명). 구분은 good/check/bad/None."""
    nm = report_nm.strip()
    for name, rx in BAD:
        if rx.search(nm):
            return ("bad", name, 0, "")
    for name, rx, w, desc in GOOD:
        if rx.search(nm):
            return ("good", name, w, desc)
    for name, rx, desc in CHECK:
        if rx.search(nm):
            return ("check", name, 1, desc)
    return (None, None, 0, "")


def fetch_recent(api_key, days=3, markets=("Y", "K"), max_pages=120):
    """최근 N일 전체 공시. corp_cls Y=유가증권 K=코스닥."""
    end = dt.date.today()
    bgn = end - dt.timedelta(days=days)
    out, calls = [], 0
    for mk in markets:
        page = 1
        while page <= max_pages:
            try:
                r = requests.get(API, timeout=60, params={
                    "crtfc_key": api_key, "bgn_de": bgn.strftime("%Y%m%d"),
                    "end_de": end.strftime("%Y%m%d"), "corp_cls": mk,
                    "page_no": page, "page_count": 100})
                js = r.json()
            except Exception:
                break
            calls += 1
            st = js.get("status")
            if st == "013":
                break
            if st != "000":
                break
            out.extend(js.get("list") or [])
            if page >= int(js.get("total_page", 1)):
                break
            page += 1
            time.sleep(0.15)
    return out, calls


def scan(api_key, days=3, include_amend=False, ttl=300):
    """최근 공시를 훑어 호재/확인필요/악재로 나눈다. ttl 초 동안 캐시."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "scan_%dd.json" % days)
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < ttl:
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass

    rows, calls = fetch_recent(api_key, days)
    good, check, bad = [], [], []
    for x in rows:
        nm = (x.get("report_nm") or "").strip()
        if not include_amend and AMEND_RE.match(nm):
            continue
        kind, cat, w, desc = classify(nm)
        if not kind:
            continue
        item = {
            "corp": x.get("corp_name"), "code": (x.get("stock_code") or "").strip(),
            "corp_code": x.get("corp_code"), "rcept": x.get("rcept_no"),
            "date": x.get("rcept_dt"), "report": nm,
            "market": x.get("corp_cls"), "category": cat, "weight": w,
            "why": desc,
            "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + (x.get("rcept_no") or ""),
        }
        (good if kind == "good" else check if kind == "check" else bad).append(item)

    # 강도를 날짜보다 먼저 본다.
    # 내부자 매수·대량보유 보고서는 매일 수백 건씩 나와서, 날짜순으로 세우면
    # 정작 드문 신호(설비투자 2건, 대형수주 25건)가 그 밑에 깔려 안 보인다.
    for lst in (good, check, bad):
        lst.sort(key=lambda r: (r["weight"], r["date"]), reverse=True)

    cats = {}
    for r in good:
        cats[r["category"]] = cats.get(r["category"], 0) + 1

    out = {"days": days, "at": time.time(), "calls": calls,
           "scanned": len(rows), "good": good, "check": check, "bad": bad,
           "categories": sorted(cats.items(), key=lambda kv: -kv[1])}
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out
