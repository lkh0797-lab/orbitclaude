# -*- coding: utf-8 -*-
"""
재무지표 — 보고서 시점마다 자산·자본·부채·유보·수익성·밸류에이션을 뽑는다.

출처 두 곳:
  * DART 전체재무제표 API (fnlttSinglAcntAll) — 재무상태표·손익계산서 원장
  * 네이버 시세 (api.finance.naver.com) — 일별 종가. PER/PBR 계산에만 쓴다.

DART 만으로 나오는 것: 자산총계·부채총계·자본총계·자본금·유보금·유보율·
부채비율·매출액·영업이익·당기순이익·영업이익률·EPS·ROE·BPS
주가가 있어야 나오는 것: PER·PBR
"""
import os
import re
import sys
import json
import time
import datetime as dt

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE, ".cache")
FIN_DIR = os.path.join(CACHE_DIR, "fin")
PRICE_DIR = os.path.join(CACHE_DIR, "price")
DART = "https://opendart.fss.or.kr/api"
NAVER = "https://api.finance.naver.com/siseJson.naver"

# 보고서 기준월 -> DART 보고서 코드
REPRT_BY_MONTH = {"03": "11013", "06": "11012", "09": "11014", "12": "11011"}
ANNUAL = "11011"


sys.path.insert(0, BASE)
import 설정                                     # noqa: E402

API_KEY = 설정.dart_api_key()

try:
    import importlib.util as _ilu
    _sp = _ilu.spec_from_file_location("본문재무", os.path.join(BASE, "본문재무.py"))
    BODY = _ilu.module_from_spec(_sp)
    _sp.loader.exec_module(BODY)
except Exception:                                   # 본문 파서가 없어도 API 만으로 돈다
    BODY = None


# ---------------------------------------------------------------- 계정 집계
def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace(" ", "")
    if not s or s in ("-", "--"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("△", "-").replace("▲", "-")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


# account_id(IFRS 표준태그)를 먼저 보고, 없으면 계정명으로 잡는다.
# 회사마다 계정명 표기가 갈려서 둘 다 필요하다.
PICK = {
    "자산총계":   (["ifrs-full_Assets"], r"^자산총계$"),
    "부채총계":   (["ifrs-full_Liabilities"], r"^부채총계$"),
    "자본총계":   (["ifrs-full_Equity"], r"^자본총계$"),
    # '자본금, 보통주'(케이티알파) — 합계 줄이 없을 때만 쓰인다(점수가 낮다)
    "자본금":     (["ifrs-full_IssuedCapital", "ifrs-full_IssuedCapitalOrdinaryShares"], r"^자본금$"),
    "이익잉여금": (["ifrs-full_RetainedEarnings"],
                  r"^이익잉여금|^결손금"),
    "주식발행초과금": (["ifrs-full_SharePremium"], r"^주식발행초과금$"),
    "자본잉여금": ([], r"^자본잉여금$"),
    "매출액":     (["ifrs-full_Revenue"], r"^(매출액|수익\(매출액\)|영업수익)$"),
    "영업이익":   (["dart_OperatingIncomeLoss",
                   "ifrs-full_ProfitLossFromOperatingActivities"],
                  r"^영업(?:이익|손익|손실)"),
    "당기순이익": (["ifrs-full_ProfitLoss"], r"^(?:연결)?당기(?:연결)?순(?:이익|손익|손실)"),
    # 희석 EPS 는 기본 EPS 가 없을 때만 (에스바이오메딕스 2025: 희석만 냄. 적자면 둘이 같다)
    "EPS":       (["ifrs-full_BasicEarningsLossPerShare",
                   "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
                   "ifrs-full_DilutedEarningsLossPerShare"],
                  r"^(?:보통주\s*)?(?:계속영업\s*)?기본\s*(?:/\s*희석\s*)?주당"),
}


def _tag_score(aid, ids):
    """태그로 맞으면 이름보다 우선. 태그끼리는 목록 앞쪽이 우선이다.
    평이한 EPS 가 있으면 계속영업 EPS 보다 먼저 쓴다."""
    if aid in ids:
        return 10 - ids.index(aid)
    return 1


def pick_accounts(rows):
    """재무상태표(BS)·손익계산서(IS/CIS)만 본다. 자본변동표(SCE)는
    '자본총계'라는 같은 이름이 여러 줄 나와서 섞이면 값이 망가진다."""
    out = {}
    for key, (ids, name_re) in PICK.items():
        rx = re.compile(name_re)
        best = None
        for r in rows:
            if r.get("sj_div") not in ("BS", "IS", "CIS"):
                continue
            nm = NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
            if "우선주" in nm:              # 한화솔루션·대덕: 우선주 EPS 줄이 따로 있다
                continue
            hit, aid = _account_hit(r, nm, ids, rx)
            if not hit:
                continue
            v = num(r.get("thstrm_amount"))
            if v is None:
                continue
            # 표준태그로 맞은 것을 이름으로 맞은 것보다 우선
            score = _tag_score(aid, ids)
            if best is None or score > best[0]:
                best = (score, v)
        if best:
            out[key] = best[1]
    if out.get("당기순이익") is None:
        v = _ni_fallback(rows)
        if v is not None:
            out["당기순이익"] = v
    return out


def _account_hit(r, nm, ids, rx):
    """이 줄이 찾는 계정인가. (맞음, 점수용 태그)를 돌려준다.
    태그·이름을 행 키와 같은 규칙으로 본다. 롯데렌탈 2021~22 처럼 매출('영업수익')에
    영업이익 태그를 붙인 줄은 행 키가 Revenue 로 바뀌어 영업이익으로 잡히지 않는다."""
    aid = norm_tag(r.get("account_id"))
    eff = _row_key(r.get("account_id"), nm).split("|")[0]
    tails = {"t:" + re.sub(r"^(?:ifrs-full|ifrs|dart)_", "", i): i for i in ids}
    if eff in tails:
        return True, (aid if aid in ids else tails[eff])
    if rx.search(nm) and not (eff.startswith("t:") and eff[2:] in CORE_GROUP):
        return True, aid
    return False, aid


def _alias_tag(account_id, nm, ids):
    """태그 없는 줄(본문 파서 등)을 NAME_TAG 로 태그에 대 본다.
    '분기순이익' → ProfitLoss. ids 에서 같은 태그를 찾아 그대로 돌려준다."""
    k = _row_key(account_id, nm)
    if not k.startswith("t:"):
        return None
    for i in ids:
        if k == "t:" + re.sub(r"^(?:ifrs-full|ifrs|dart)_", "", i):
            return i
    return None


NI_PARTS = {"bt": "ifrs-full_ProfitLossBeforeTax",
            "tax": "ifrs-full_IncomeTaxExpenseContinuingOperations",
            "owner": "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "nci": "ifrs-full_ProfitLossAttributableToNoncontrollingInterests"}


def _ni_fallback(rows, field="thstrm_amount"):
    """당기순이익 줄이 없는 원장에서 산출한다(_net_income_from 참조)."""
    got, has_nci = {}, False
    for r in rows:
        if r.get("sj_div") not in ("IS", "CIS"):
            continue
        # 태그 없는 본문 줄('지배기업주주지분순이익')도 이름 태그로 맞춘다
        rk = _row_key(r.get("account_id"), NUM_PREFIX.sub("", (r.get("account_nm") or "").strip()))
        for k, t in NI_PARTS.items():
            if rk.split("|")[0] != "t:" + t.split("_", 1)[1]:
                continue
            if k == "nci":
                has_nci = True
            v = num(r.get(field))
            if k not in got and v is not None:
                got[k] = v
    v, _ = _net_income_from(got.get("bt"), got.get("tax"), got.get("owner"),
                            got.get("nci"), has_nci)
    return v


# ---------------------------------------------------------------- DART
def fetch_statement(corp_code, year, reprt_code, fs_div="CFS"):
    os.makedirs(FIN_DIR, exist_ok=True)
    cache = os.path.join(FIN_DIR, "%s_%s_%s_%s.json"
                         % (corp_code, year, reprt_code, fs_div))
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                return _or_body(json.load(fh), corp_code, year, reprt_code, fs_div)
        except Exception:
            pass
    r = requests.get(DART + "/fnlttSinglAcntAll.json", timeout=90, params={
        "crtfc_key": API_KEY, "corp_code": corp_code, "bsns_year": str(year),
        "reprt_code": reprt_code, "fs_div": fs_div})
    r.raise_for_status()
    js = r.json()
    data = {"status": js.get("status"), "list": js.get("list") or []}
    # 정상(000)과 '데이터 없음'(013)만 캐시한다. 한도 초과(020)·점검중(800) 같은
    # 일시 오류를 캐시하면 그 해는 영영 빈 채로 남는다.
    if data["status"] in ("000", "013"):
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    time.sleep(0.25)
    return _or_body(data, corp_code, year, reprt_code, fs_div)


def _or_body(data, corp_code, year, reprt_code, fs_div):
    """API 원장이 없으면(013) 보고서 본문 재무제표로 대신한다.
    금융업 2015~2022, 전 종목 2011~2014 가 여기로 온다. 본문재무.py 참조.
    원장은 있는데 표 하나가 통째로 빠진 해(에프에스티 2015~17 현금흐름표)는
    빠진 표만 본문에서 보탠다."""
    if BODY is None:
        return data
    lst = data.get("list") or []
    if lst:
        kinds = {r.get("sj_div") for r in lst}
        missing = {k for k in ("BS", "CF") if k not in kinds}
        if not (kinds & {"IS", "CIS"}):
            missing |= {"IS", "CIS"}
        if not missing:
            return data
        try:
            b = BODY.statement(corp_code, year, reprt_code, fs_div)
        except Exception:
            return data
        add = [r for r in (b.get("list") or []) if r.get("sj_div") in missing]
        return dict(data, list=lst + add) if add else data
    try:
        b = BODY.statement(corp_code, year, reprt_code, fs_div)
    except Exception:
        return data
    return b if b.get("list") else data


def fetch_shares(corp_code, year, reprt_code):
    """보통주 발행주식총수 - 자기주식. BPS 계산에 쓴다."""
    os.makedirs(FIN_DIR, exist_ok=True)
    cache = os.path.join(FIN_DIR, "shares_%s_%s_%s.json"
                         % (corp_code, year, reprt_code))
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    try:
        r = requests.get(DART + "/stockTotqySttus.json", timeout=60, params={
            "crtfc_key": API_KEY, "corp_code": corp_code,
            "bsns_year": str(year), "reprt_code": reprt_code})
        js = r.json()
    except Exception:
        js = {}
    out = {"shares": None}
    for x in (js.get("list") or []):
        se = (x.get("se") or "").strip()
        if "보통주" not in se and se not in ("합계",):
            continue
        issued = num(x.get("istc_totqy"))
        treasury = num(x.get("tesstk_co")) or 0
        if issued:
            out = {"shares": issued - treasury, "se": se}
            if "보통주" in se:
                break
    if js.get("status") in ("000", "013"):     # 한도 초과·네트워크 오류는 캐시하지 않는다
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
    time.sleep(0.25)
    return out


# ---------------------------------------------------------------- 주가
def fetch_prices(stock_code, start="20100101"):
    """네이버 일별 시세. 하루 단위로 캐시."""
    os.makedirs(PRICE_DIR, exist_ok=True)
    cache = os.path.join(PRICE_DIR, stock_code + ".json")
    if os.path.exists(cache) and \
            time.time() - os.path.getmtime(cache) < 86400:
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    end = dt.date.today().strftime("%Y%m%d")
    try:
        r = requests.get(NAVER, timeout=60,
                         headers={"User-Agent": "Mozilla/5.0"},
                         params={"symbol": stock_code, "requestType": "1",
                                 "startTime": start, "endTime": end,
                                 "timeframe": "day"})
        r.raise_for_status()
        txt = r.text
    except Exception:
        return {}
    # 응답이 파이썬 리터럴에 가까운 형태라 따옴표를 맞춰 JSON 으로 읽는다
    txt = txt.replace("'", '"')
    try:
        rows = json.loads(txt)
    except Exception:
        return {}
    out = {}
    for row in rows[1:]:
        if not row or len(row) < 5:
            continue
        d = str(row[0]).strip()
        c = num(row[4])
        if re.fullmatch(r"\d{8}", d) and c:
            out[d] = c
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


def price_on(prices, yyyymmdd, back=12):
    """그 날 종가. 휴장이면 직전 영업일로 최대 back 일 거슬러 올라간다."""
    if not prices:
        return None, None
    d = dt.datetime.strptime(yyyymmdd, "%Y%m%d").date()
    for i in range(back):
        k = (d - dt.timedelta(days=i)).strftime("%Y%m%d")
        if k in prices:
            return prices[k], k
    return None, None


# ---------------------------------------------------------------- 지표
def metrics_for(corp_code, stock_code, stamp, rcept_dt, prices=None):
    """보고서 한 건의 지표 묶음."""
    year, month = stamp.split("-")
    reprt = REPRT_BY_MONTH.get(month)
    if not reprt:
        return None
    st = fetch_statement(corp_code, year, reprt)
    rows = st.get("list") or []
    if not rows:                       # 연결 없으면 별도로
        st = fetch_statement(corp_code, year, reprt, "OFS")
        rows = st.get("list") or []
    if not rows:
        return None
    a = pick_accounts(rows)
    if not a.get("자본총계"):
        return None

    m = {"stamp": stamp, "annual": reprt == ANNUAL}
    for k in ("자산총계", "부채총계", "자본총계", "자본금",
              "매출액", "영업이익", "당기순이익"):
        m[k] = a.get(k)

    cap = a.get("자본금") or 0
    surplus = a.get("자본잉여금")
    if surplus is None:
        surplus = a.get("주식발행초과금")
    retained = a.get("이익잉여금")
    if surplus is not None or retained is not None:
        m["유보금"] = (surplus or 0) + (retained or 0)
        if cap:
            m["유보율"] = m["유보금"] / cap * 100

    if a.get("자본총계"):
        if a.get("부채총계") is not None:
            m["부채비율"] = a["부채총계"] / a["자본총계"] * 100
        if a.get("당기순이익") is not None:
            m["ROE"] = a["당기순이익"] / a["자본총계"] * 100
    if a.get("매출액") and a.get("영업이익") is not None:
        m["영업이익률"] = a["영업이익"] / a["매출액"] * 100
    if a.get("EPS") is not None:
        m["EPS"] = a["EPS"]

    sh = fetch_shares(corp_code, year, reprt).get("shares")
    if sh:
        m["발행주식수"] = sh
        m["BPS"] = a["자본총계"] / sh

    if prices is None:
        prices = fetch_prices(stock_code)
    px, pxd = price_on(prices, rcept_dt) if rcept_dt else (None, None)
    if px:
        m["주가"] = px
        m["주가일"] = pxd
        if m.get("BPS"):
            m["PBR"] = px / m["BPS"]
        # 분기·반기 EPS 는 누적치라 그대로 PER 을 내면 과대평가된다.
        # 사업보고서(연간 EPS)일 때만 낸다.
        if m.get("EPS") and reprt == ANNUAL and m["EPS"] > 0:
            m["PER"] = px / m["EPS"]
    return m


# ---------------------------------------------------------------- 과거 역산
# DART 재무제표 API 는 2015년이 바닥이다(그 앞은 status 013).
# 그런데 보고서마다 전기·전전기 비교 수치가 같이 들어 있다.
#   2015 사업보고서 = 제68기 2015 / 제67기 2014 / 제66기 2013
# 새 API 없이 이것만 꺼내도 2년을 더 내려갈 수 있다.
BACKFILL_PICK = {
    "매출액": (["ifrs-full_Revenue"], r"^(매출액|수익\(매출액\)|영업수익)$"),
    "영업이익": (["dart_OperatingIncomeLoss",
                "ifrs-full_ProfitLossFromOperatingActivities"], r"^영업(?:이익|손익|손실)"),
    "당기순이익": (["ifrs-full_ProfitLoss"], r"^(?:연결)?당기(?:연결)?순(?:이익|손익|손실)"),
    "EPS": (["ifrs-full_BasicEarningsLossPerShare",
             "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations"],
            r"^(?:보통주\s*)?(?:계속영업\s*)?기본\s*주당"),
}


def _pick_field(rows, field):
    out = {}
    for key, (ids, name_re) in BACKFILL_PICK.items():
        rx = re.compile(name_re)
        best = None
        for r in rows:
            if r.get("sj_div") not in ("IS", "CIS"):
                continue
            nm = NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
            if "우선주" in nm:
                continue
            hit, aid = _account_hit(r, nm, ids, rx)
            if not hit:
                continue
            v = num(r.get(field))
            if v is None:
                continue
            score = _tag_score(aid, ids)
            if best is None or score > best[0]:
                best = (score, v)
        if best:
            out[key] = best[1]
    if out.get("당기순이익") is None:
        v = _ni_fallback(rows, field)
        if v is not None:
            out["당기순이익"] = v
    return out


def annual_actuals(corp_code, years):
    """사업보고서의 연간 수치를 직접 읽는다.

    분기 4개를 더해서 연간을 만들면 분기 데이터가 없는 해(2015)가 통째로
    빠진다. 사업보고서에는 연간 값이 그대로 들어 있으니 그걸 쓴다.
    """
    out = {}
    for y in years:
        st = fetch_statement(corp_code, y, "11011")
        rows = st.get("list") or []
        if not rows:
            st = fetch_statement(corp_code, y, "11011", "OFS")
            rows = st.get("list") or []
        if not rows:
            continue
        vals = _pick_field(rows, "thstrm_amount")
        if vals.get("매출액") is not None:
            out[y] = vals
    return out


def annual_backfill(corp_code, earliest_year, reprt="11011"):
    """가장 오래된 사업보고서의 전기·전전기 칸으로 그 앞 2년을 만든다."""
    st = fetch_statement(corp_code, earliest_year, reprt)
    rows = st.get("list") or []
    if not rows:
        st = fetch_statement(corp_code, earliest_year, reprt, "OFS")
        rows = st.get("list") or []
    if not rows:
        return {}
    out = {}
    prev = _pick_field(rows, "frmtrm_amount")
    if prev:
        out[earliest_year - 1] = prev
    prev2 = _pick_field(rows, "bfefrmtrm_amount")
    if prev2:
        out[earliest_year - 2] = prev2
    return out


# ---------------------------------------------------------------- 컨센서스
# DART 에는 애널리스트 추정치가 없다. 네이버 금융이 '다음 분기' 컨센서스를
# 한 칸 준다 (isConsensus=Y). 값은 억원 단위이고 DART 실적과 일치하는 것을
# 삼성전자·LG이노텍으로 대조해 확인했다.
NAVER_FIN = "https://m.stock.naver.com/api/stock/%s/finance/%s"
CONSENSUS_DIR = os.path.join(CACHE_DIR, "consensus")
CONSENSUS_ROWS = ("매출액", "영업이익", "당기순이익", "EPS", "영업이익률", "ROE")


def fetch_consensus(stock_code, period="quarter"):
    """네이버 금융 재무 요약. period: quarter | annual.
    반환: {"cols":[{key,title,consensus}], "rows":{행이름:{key:값(원)}}}"""
    os.makedirs(CONSENSUS_DIR, exist_ok=True)
    cache = os.path.join(CONSENSUS_DIR, "%s_%s.json" % (stock_code, period))
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 21600:
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    try:
        r = requests.get(NAVER_FIN % (stock_code, period), timeout=30,
                         headers={"User-Agent": "Mozilla/5.0",
                                  "Referer": "https://m.stock.naver.com/"})
        r.raise_for_status()
        fi = r.json().get("financeInfo") or {}
    except Exception:
        return {"cols": [], "rows": {}}

    cols = [{"key": t.get("key"), "title": t.get("title"),
             "consensus": t.get("isConsensus") == "Y"}
            for t in (fi.get("trTitleList") or []) if t.get("key")]
    rows = {}
    for row in (fi.get("rowList") or []):
        title = (row.get("title") or "").strip()
        if title not in CONSENSUS_ROWS:
            continue
        vals = {}
        for k, v in (row.get("columns") or {}).items():
            x = num((v or {}).get("value"))
            if x is None:
                continue
            # 금액 행은 억원 단위. 비율(%)과 주당금액(원)은 그대로 둔다.
            if title in ("매출액", "영업이익", "당기순이익"):
                x *= 1e8
            vals[k] = x
        rows[title] = vals

    out = {"cols": cols, "rows": rows, "fetched": time.time()}
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    record_consensus(stock_code, period, out)
    return out


def record_consensus(stock_code, period, data):
    """컨센서스 스냅샷을 쌓아둔다.

    네이버는 '지금 시점의' 다음 분기 추정치만 준다. 과거에 무엇을 기대했는지는
    아무도 돌려주지 않는다. 그래서 볼 때마다 적어둔다. 나중에 그 분기 실적이
    나오면 이 기록과 대조해 서프라이즈를 낼 수 있다. 지금은 못 내고,
    기록이 쌓이는 만큼 생긴다.
    """
    os.makedirs(CONSENSUS_DIR, exist_ok=True)
    path = os.path.join(CONSENSUS_DIR, "%s_%s_기록.json" % (stock_code, period))
    hist = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                hist = json.load(fh)
        except Exception:
            hist = {}
    today = dt.date.today().isoformat()
    changed = False
    for c in data.get("cols", []):
        if not c.get("consensus"):
            continue
        key = c["key"]
        snap = {r: data["rows"].get(r, {}).get(key)
                for r in CONSENSUS_ROWS if data["rows"].get(r, {}).get(key) is not None}
        if not snap:
            continue
        snap["기록일"] = today
        prev = hist.get(key)
        if prev is None or {k: v for k, v in prev.items() if k != "기록일"} != \
                {k: v for k, v in snap.items() if k != "기록일"}:
            hist.setdefault("_이력", []).append(dict(snap, 분기=key))
            changed = True
        hist[key] = snap
    if changed:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(hist, fh, ensure_ascii=False)
    return hist


def consensus_history(stock_code, period="quarter"):
    path = os.path.join(CONSENSUS_DIR, "%s_%s_기록.json" % (stock_code, period))
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


# ---------------------------------------------------------------- 재무 매트릭스
# 계정을 행, 분기·연도를 열로 세운 표.
#
# 보고서 종류마다 thstrm_amount 의 의미가 다르다. 이걸 뭉개면 값이 전부 틀린다.
#   손익계산서(IS/CIS) : 분기보고서는 '3개월 단독'. 사업보고서만 연간.
#                        따라서 4분기 단독 = 연간 − 3분기 누적.
#   현금흐름표(CF)     : 분기보고서도 '누적'. 분기 단독 = 당기 누적 − 전분기 누적.
#   재무상태표(BS)     : 시점 잔액. 차감할 것이 없다.
STMT_DIV = {"IS": ("IS", "CIS"), "BS": ("BS",), "CF": ("CF",)}
STMT_NAME = {"IS": "손익계산서", "BS": "재무상태표", "CF": "현금흐름표"}
Q_REPRT = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}

# DART 의 ord 필드는 재무제표 줄 순서가 아니다.
# (삼성전자 2025 사업보고서: 영업이익 ord=6, 매출원가 11, 매출총이익 17)
# 그래서 표준 재무제표 순서를 직접 세운다. 앞에서부터 처음 맞는 패턴의 위치가 순서.
ORDER_PATTERNS = {
    "IS": [r"^(매출액|수익\(매출액\)|영업수익|매출)$", r"매출원가", r"매출총(이익|손익)",
           r"판매비와관리비", r"^영업(이익|손익|손실)", r"기타수익", r"기타이익", r"기타비용",
           r"기타손실", r"금융수익", r"금융비용", r"지분법", r"관계기업",
           r"법인세(비용)?차감전", r"법인세비용", r"^당기순(이익|손익|손실)", r"계속영업",
           r"중단영업", r"지배(기업|회사)", r"비지배", r"주당이익", r"주당순",
           r"기본주당", r"희석주당", r"^총포괄", r"포괄손익", r"기타포괄"],
    "BS": [r"^유동자산", r"^비유동자산", r"^자산총계", r"^유동부채", r"^비유동부채",
           r"^부채총계", r"^자본금", r"자본잉여금", r"주식발행초과금", r"기타자본",
           r"기타포괄손익누계", r"이익잉여금", r"결손금", r"지배(기업|회사)",
           r"비지배지분", r"^자본총계", r"부채와자본총계"],
    "CF": [r"영업활동", r"투자활동", r"재무활동", r"환율변동", r"현금.*증가",
           r"현금.*감소", r"기초.*현금", r"기말.*현금"],
}


# 현금흐름표에서 기초·기말 현금은 '흐름'이 아니라 '잔액'이다.
# 누적에서 전분기 누적을 빼는 처리를 하면 0 또는 엉뚱한 값이 된다.
CF_BALANCE_RE = re.compile(r"기초|기말|초의 현금|말의 현금|期初|期末")


# 줄 순서는 태그로 먼저 정한다. 이름은 회사마다 끝없이 갈린다
# (원익IPS 는 영업이익을 '영업순손익' 이라고 적었다). 태그는 이름과 무관하게 같다.
# 숫자는 ORDER_PATTERNS 의 위치와 맞췄다.
TAG_ORDER = {
    "IS": {"Revenue": 0, "CostOfSales": 1, "GrossProfit": 2,
           "SellingGeneralAndAdministrativeExpense": 3,
           "OperatingIncomeLoss": 4, "ProfitLossFromOperatingActivities": 4,
           "OtherIncome": 5, "OtherGains": 6, "OtherExpense": 7, "OtherLosses": 8,
           "FinanceIncome": 9, "FinanceCosts": 10,
           "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod": 11,
           "ProfitLossBeforeTax": 13, "IncomeTaxExpenseContinuingOperations": 14,
           "ProfitLoss": 15, "ProfitLossFromContinuingOperations": 16,
           "ProfitLossFromDiscontinuedOperations": 17,
           "ProfitLossAttributableToOwnersOfParent": 18,
           "ProfitLossAttributableToNoncontrollingInterests": 19,
           "BasicEarningsLossPerShare": 20, "DilutedEarningsLossPerShare": 23,
           "ComprehensiveIncome": 24, "OtherComprehensiveIncome": 26},
    "BS": {"CurrentAssets": 0, "NoncurrentAssets": 1, "Assets": 2,
           "CurrentLiabilities": 3, "NoncurrentLiabilities": 4, "Liabilities": 5,
           "IssuedCapital": 6, "SharePremium": 8, "OtherEquityInterest": 9,
           "RetainedEarnings": 11, "EquityAttributableToOwnersOfParent": 13,
           "NoncontrollingInterests": 14, "Equity": 15, "EquityAndLiabilities": 16},
    "CF": {"CashFlowsFromUsedInOperatingActivities": 0,
           "CashFlowsFromUsedInInvestingActivities": 1,
           "CashFlowsFromUsedInFinancingActivities": 2,
           "EffectOfExchangeRateChangesOnCashAndCashEquivalents": 3,
           "IncreaseDecreaseInCashAndCashEquivalents": 4},
}


def _order_key(stmt, name, key=None):
    if key and key.startswith("t:"):
        i = TAG_ORDER.get(stmt, {}).get(key[2:].split("|")[0])
        if i is not None:
            return i
    for i, pat in enumerate(ORDER_PATTERNS.get(stmt, [])):
        if re.search(pat, name):
            return i
    return 900          # 못 맞춘 계정은 뒤로

# 주당 금액은 억·조로 뭉개면 안 된다. 화면에서 원 단위로 쓰도록 표시만 남긴다.
PERSHARE_RE = re.compile(r"주당")

# 계정명은 해마다 바뀐다. LG이노텍 실측:
#   2023 법인세차감전순이익 / 2025 법인세비용차감전순이익  (태그는 둘 다 ProfitLossBeforeTax)
#   2023 계속영업기본주당이익 / 2025 기본주당이익
# 이름으로 줄을 이으면 끊긴다. IFRS 표준태그를 우선 키로 쓴다.
NO_TAG = "-표준계정코드 미사용-"

# 중단영업이 없어지면 회사가 '계속영업 주당이익'에서 평이한 '주당이익'으로
# 줄을 갈아탄다. 읽는 사람에게는 같은 줄이라 하나로 묶는다.
TAG_ALIAS = {
    "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations":
        "ifrs-full_BasicEarningsLossPerShare",
    "ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations":
        "ifrs-full_DilutedEarningsLossPerShare",
}

# 태그 없이 낸 줄 중 핵심 계정은 이름으로 태그를 붙여 준다. 다른 해에 태그로
# 낸 같은 계정과 한 줄로 잇기 위해서다. _merge_name 을 거친 이름에 맞춘다.
#   SK텔레콤 2015  '연결당기순이익'            (태그 없음)
#   아스트   2015  '영업활등으로부터의 순현금유입(유출)'  (오타까지 원문 그대로)
# '영업활동에서 창출된 현금'은 이자·법인세 전 소계라 영업활동현금흐름이 아니다.
NAME_TAG = [
    (re.compile(r"^총?당기순이익$"), "ProfitLoss"),                 # NH투자증권 2014 '총당기순이익'
    # '계속사업순이익(손실)'(대한광통신 2014) — 2011~2014 옛 표기
    (re.compile(r"^계속(?:영업|사업)(?:당기)?순이익$"), "ProfitLossFromContinuingOperations"),
    (re.compile(r"^(?:지배기업(?:의)?(?:주주|소유주)(?:지분|에게귀속되는)?|주주지분)(?:당기)?순이익$"),
     "ProfitLossAttributableToOwnersOfParent"),
    (re.compile(r"^비지배지분(?:에귀속되는)?(?:당기)?순이익$"),
     "ProfitLossAttributableToNoncontrollingInterests"),
    # '계속영업매출액'(LG이노텍 2012) '매출액(수익)'(휴메딕스 2014)
    # '매출과지분법손익(영업수익)'(한국앤컴퍼니) — 지주사는 괄호 안에 영업수익이라 적는다
    (re.compile(r"^(?:계속영업)?(?:매출액|영업수익|매출)(?:\((?:매출액|영업수익|수익)\))?$"
                r"|^수익\(매출액\)$|^[^()]{2,20}\(영업수익\)$"),
     "Revenue"),
    (re.compile(r"^법인세(?:비용)?차감전(?:계속(?:영업|사업))?(?:당기)?(?:순)?이익$"), "ProfitLossBeforeTax"),
    # '법인세수익(비용)'은 부호가 반대라 넣지 않는다 (순이익 산출에 쓰면 틀린다)
    (re.compile(r"^(?:계속영업)?법인세비용(?:\((?:수익|이익)\))?$"), "IncomeTaxExpenseContinuingOperations"),
    # '영업의이익'(서희건설 2013) 'Ⅲ.영업손실'(적자 해에 줄 이름을 바꾸는 회사)
    (re.compile(r"^영업(?:의)?(?:이익|손실)$"), "OperatingIncomeLoss"),
    (re.compile(r"^(?:지배기업(?:의)?소유주(?:지분)?)?(?:보통주)?기본(?:및희석|/희석)?(?:보통)?주당(?:순)?(?:이익|손실|손익)$"),
     "BasicEarningsLossPerShare"),
    (re.compile(r"^(?:지배기업(?:의)?소유주(?:지분)?)?(?:보통주)?희석(?:보통)?주당(?:순)?(?:이익|손실|손익)$"),
     "DilutedEarningsLossPerShare"),
    (re.compile(r"^순이자(?:이익|손익)$"), "InterestRevenueExpense"),
    (re.compile(r"^순수수료(?:이익|손익)$"), "FeeAndCommissionIncomeExpense"),
    (re.compile(r"^자산총계$"), "Assets"),
    (re.compile(r"^부채총계$"), "Liabilities"),
    (re.compile(r"^자본총계$"), "Equity"),
    # '영업으로부터의 순현금유입'(에프에스티 2016) — '영업활동현금흐름'은 숫자 없는 제목이고 합계는 이 줄
    (re.compile(r"^영업활[동등](?!.*창출).*현금|^영업(?:으로부터|에서)의?순현금(?:유입|유출|흐름)"),
     "CashFlowsFromUsedInOperatingActivities"),
    (re.compile(r"^투자활동.*현금"), "CashFlowsFromUsedInInvestingActivities"),
    (re.compile(r"^재무활동.*현금"), "CashFlowsFromUsedInFinancingActivities"),
    (re.compile(r"^현금및현금성자산(?:에대한|의)환율변동효과$"),
     "EffectOfExchangeRateChangesOnCashAndCashEquivalents"),
]

# 줄 이름 앞의 목차 번호. 'III. 영업이익' 'VI. 당기순이익' '1. 영업외수익' '가. 매출'
NUM_PREFIX = re.compile(r"^\s*(?:(?:[IVXlⅠ-Ⅻ]+|\d{1,2}|[가나다라마바사아자차카타파하])\s*[\.\．)]|\(\d{1,2}\))\s*")


def norm_tag(aid):
    """IFRS 태그 접두어를 통일한다.

    DART XBRL 택소노미가 2019년에 바뀌면서 접두어가 달라졌다.
      2017~2018  ifrs_Revenue       ifrs_CostOfSales
      2019~      ifrs-full_Revenue  ifrs-full_CostOfSales
    같은 계정인데 태그로 행을 이으면 2018/2019 사이에서 두 줄로 갈라진다
    (삼성전기 매출액이 그랬다). dart_ 접두어는 그대로 유지돼 영향이 없었다.
    """
    aid = (aid or "").strip()
    if aid.startswith("ifrs_"):
        return "ifrs-full_" + aid[5:]
    return aid


def _norm_name(nm):
    n = re.sub(r"\((손실|순손실|이익)\)", "", nm)
    return re.sub(r"\s+", "", n)


def _merge_name(nm):
    """행 병합용 이름. '당기순이익(손실)' '당기순이익' '당기순손익' 은 한 계정이다.
    원익IPS 는 11년 동안 이 셋을 차례로 썼다 (태그는 ProfitLoss 로 그대로)."""
    n = NUM_PREFIX.sub("", nm)
    n = re.sub(r"\((?:손실|이익|순손실|순이익|손익)\)", "", n)
    n = re.sub(r"\s+", "", n)
    # 연결재무제표 안에서 '연결'은 수식어일 뿐이다. SK텔레콤·에스티큐브는 2015년에
    # 태그 없이 '연결당기순이익'이라 적고 이후엔 '당기순이익'으로 적었다.
    n = re.sub(r"^연결", "", n)
    n = n.replace("당기연결순", "당기순").replace("기연결순", "기순").replace("당기의순", "당기순")
    # 본문 표기: '기본주당이익(원)', '당기말 현금및현금성자산', '기말의 현금…'
    n = re.sub(r"\((?:단위:?)?원\)$", "", n)
    n = re.sub(r"^(?:당|당분|당반|[1-4]?분|반)?(기말|기초)의?(?=현금)", lambda m: m.group(1), n)
    # 분기·반기 보고서는 같은 줄을 '분기순이익' '반기순이익' '분(당)기순이익' 으로 적는다
    n = re.sub(r"(?:당|분|반)?(?:\((?:당|분|반)\))?(?:분|반)?기순(?:이익|손실|손익)", "당기순이익", n)
    n = n.replace("순손익", "순이익").replace("영업손익", "영업이익")
    n = re.sub(r"[\.．,\s]+$", "", n)            # 'I.영업수익.'(영원무역홀딩스 2014) 끝 마침표
    return n


# 핵심 계정은 회사가 태그를 잘못 붙이기도 한다. 롯데렌탈 2021~22 는 '영업수익'(매출)에
# dart_OperatingIncomeLoss 를 붙였다. 태그만 믿으면 매출이 다른 해의 영업이익 줄에 섞인다.
# 이름이 다른 핵심 개념을 또렷이 가리키면 이름을 따른다.
CORE_GROUP = {"Revenue": "매출",
              "OperatingIncomeLoss": "영업이익", "ProfitLossFromOperatingActivities": "영업이익",
              "ProfitLossBeforeTax": "세전이익", "ProfitLoss": "순이익"}


def _name_tag(name):
    mn = _merge_name(name)
    for rx, tag in NAME_TAG:
        if rx.search(mn):
            return tag
    return None


def _row_key(account_id, name):
    """행 키. 태그가 있으면 접두어를 뗀 태그 이름을 쓴다.

    접두어는 택소노미 개정 때마다 바뀌었다.
      2019  ifrs_Revenue            → ifrs-full_Revenue
      2023  dart_OtherCurrentLiabilities → ifrs-full_OtherCurrentLiabilities
    뒤쪽 이름은 그대로라, 접두어를 떼면 같은 계정이 한 줄로 이어진다.
    """
    aid = norm_tag(account_id)
    if aid and aid != NO_TAG and not aid.startswith("-"):
        aid = TAG_ALIAS.get(aid, aid)
        tail = re.sub(r"^(?:ifrs-full|ifrs|dart)_", "", aid)
        if tail in CORE_GROUP:
            nt = _name_tag(name)
            if nt in CORE_GROUP and CORE_GROUP[nt] != CORE_GROUP[tail]:
                return "t:" + nt              # 태그가 이름과 다른 핵심 개념을 가리킨다
        return "t:" + tail
    nt = _name_tag(name)
    if nt:
        return "t:" + nt
    return "nm:" + _norm_name(name)


def _rows_of(corp_code, year, reprt, divs):
    st = fetch_statement(corp_code, year, reprt)
    rows = st.get("list") or []
    if not rows:
        st = fetch_statement(corp_code, year, reprt, "OFS")
        rows = st.get("list") or []
    out, order = {}, []
    sel = [r for r in rows if r.get("sj_div") in divs
           and (r.get("account_nm") or "").strip()]
    # 한 해 보고서 안에서 한 태그를 서로 다른 계정이 같이 쓰는 경우가 있다.
    #   dart_DecreaseInLoans           단기대여금의 감소 / 장기대여금의 감소
    #   dart_RepaymentsOfLongTermBorr… 장기차입금의 상환 / 유동성장기차입금의 상환
    # 태그로만 묶으면 둘이 한 칸에 부딪혀 먼저 온 값만 남는다(점검한 빈칸의
    # 10%가 이것). 그런 해에는 태그에 이름을 붙여 키를 나눈다. 연도를 건너
    # 같은 계정을 잇는 것은 statement_matrix 의 이름 병합이 맡는다.
    # 이름으로 태그를 붙인 줄(NAME_TAG)은 진짜 태그 줄에 양보한다.
    # 아스트 2019 는 '재무활동현금흐름'(태그)과 '재무활동 순현금유입(유출)'(태그 없음)을
    # 같은 금액으로 두 번 적었다. 금액이 같으면 버리고, 다르면 이름 키로 둔다.
    tagged = {}
    for r in sel:
        aid = norm_tag(r.get("account_id"))
        if aid and aid != NO_TAG and not aid.startswith("-"):
            k = _row_key(aid, r["account_nm"].strip())
            tagged.setdefault(k, num(r.get("thstrm_amount")))
    keys = []
    for r in sel:
        nm = r["account_nm"].strip()
        aid = norm_tag(r.get("account_id"))
        key = _row_key(aid, nm)
        real = aid and aid != NO_TAG and not aid.startswith("-")
        if not real and key.startswith("t:") and key in tagged:
            if tagged[key] == num(r.get("thstrm_amount")):
                key = None
            else:
                key = "nm:" + _norm_name(nm)
        keys.append(key)
    sel, keys = [r for r, k in zip(sel, keys) if k], [k for k in keys if k]

    names_of = {}
    for r, key in zip(sel, keys):
        names_of.setdefault(key, set()).add(_merge_name(r["account_nm"].strip()))
    for r, key in zip(sel, keys):
        nm = r["account_nm"].strip()
        if key.startswith("t:") and len(names_of.get(key, ())) > 1:
            key = key + "|" + _merge_name(nm)
        if key not in out:
            order.append({"key": key, "name": nm,
                          "ord": int(r.get("ord") or 9999),
                          "div": r.get("sj_div")})
        cur = num(r.get("thstrm_amount"))
        cum = num(r.get("thstrm_add_amount"))
        if key not in out:
            out[key] = {}
        # 같은 이름이 여러 줄이면 먼저 나온 값을 지킨다(연결/별도 중복 방지)
        if "cur" not in out[key] and cur is not None:
            out[key]["cur"] = cur
        if "cum" not in out[key] and cum is not None:
            out[key]["cum"] = cum
    return out, order


def _net_income_from(bt, tax, owner, nci, has_nci):
    """당기순이익을 다른 줄로 산출한다. 두 길이 있다.
         법인세비용차감전순이익 − 법인세비용
         지배기업 소유주 귀속 + 비지배지분 귀속   (비지배지분이 없는 회사는 지배분 = 전체)
    둘 다 되면 맞는지 검산하고, 어긋나면 내지 않는다. 반환 (값, 산출 근거)."""
    a = bt - tax if bt is not None and tax is not None else None
    b = None
    if owner is not None:
        if nci is not None:
            b = owner + nci
        elif not has_nci:
            b = owner
    tol = lambda x: max(1e6, abs(x) * 0.005)
    if a is not None and b is not None:
        if abs(a - b) <= tol(a):
            return a, "법인세비용차감전순이익 − 법인세비용 (지배+비지배 귀속분과 검산 일치)"
        # 귀속분 합계는 정의상 당기순이익이다. 세전−법인세가 어긋나는 건 중단영업
        # (대한제당 2016)이나 법인세 부호를 반대로 낸 회사(레인보우로보틱스 2024) 때문이다.
        return b, "지배기업 소유주 귀속 + 비지배지분 귀속 (세전−법인세와 차이: 중단영업·법인세 부호)"
    if a is not None:
        return a, "법인세비용차감전순이익 − 법인세비용"
    if b is not None:
        return b, "지배기업 소유주 귀속 + 비지배지분 귀속"
    return None, None


def _fill_net_income(rows, n):
    """원장에 당기순이익 줄이 아예 없는 해가 있다. 귀속분(지배/비지배)만 적고
    합계 줄을 빼먹은 경우다. 남해화학 2022, 미래에셋벤처투자 2023,
    이지스밸류플러스리츠 2023 이 그랬다. 비워 두지 않고 산출해 채우되,
    산출한 칸이라고 표시한다(values[i]['d'] 에 근거)."""
    def find(tag):
        return next((r for r in rows if r["key"].split("|")[0] == "t:" + tag), None)

    bt = find("ProfitLossBeforeTax")
    tx = find("IncomeTaxExpenseContinuingOperations")
    ow = find("ProfitLossAttributableToOwnersOfParent")
    nc = find("ProfitLossAttributableToNoncontrollingInterests")
    co = find("ProfitLossFromContinuingOperations")
    dc = find("ProfitLossFromDiscontinuedOperations")
    if not ((bt and tx) or ow or co):
        return
    pl = find("ProfitLoss")
    new = pl is None
    if new:
        src = bt or ow
        pl = {"key": "t:ProfitLoss", "name": "당기순이익", "div": src["div"], "v": [None] * n}
    got = {}
    g = lambda r, i: r["v"][i] if r else None
    for i in range(n):
        if pl["v"][i] is not None:
            continue
        v, why = _net_income_from(g(bt, i), g(tx, i), g(ow, i), g(nc, i), nc is not None)
        if v is None and g(co, i) is not None and g(dc, i) is None:
            # 중단영업이 없는 해는 계속사업이익이 곧 당기순이익이다 (대한광통신 2014)
            v, why = g(co, i), "계속사업이익 (중단영업 없음)"
        if v is not None:
            pl["v"][i] = v
            got[i] = why
    if got:
        pl["derived"] = {**(pl.get("derived") or {}), **got}
        if new:
            rows.append(pl)


def _fill_liabilities(rows, n):
    """부채총계 줄을 못 읽은 해(CJ대한통운 2014 본문)는 자산총계 − 자본총계로 채운다.
    재무상태표 항등식이라 틀릴 여지가 없다. 산출 칸으로 표시한다."""
    def find(tag):
        return next((r for r in rows if r["key"].split("|")[0] == "t:" + tag), None)
    a, e, l = find("Assets"), find("Equity"), find("Liabilities")
    if not (a and e):
        return
    new = l is None
    if new:
        l = {"key": "t:Liabilities", "name": "부채총계", "div": a["div"], "v": [None] * n}
    got = {}
    for i in range(n):
        if l["v"][i] is None and a["v"][i] is not None and e["v"][i] is not None:
            l["v"][i] = a["v"][i] - e["v"][i]
            got[i] = "자산총계 − 자본총계"
    if got:
        l["derived"] = {**(l.get("derived") or {}), **got}
        if new:
            rows.append(l)


def statement_matrix(corp_code, years, stmt="IS", mode="q"):
    """stmt: IS|BS|CF, mode: q(분기 단독) | y(연간)"""
    divs = STMT_DIV.get(stmt, ("IS", "CIS"))
    periods, cells = [], {}
    # 계정 목록은 전 기간에서 모은다. 최신 보고서에만 있는 줄로 한정하면
    # 과거에만 있던 계정(중단영업 등)이 통째로 사라진다.
    # 표시 이름은 연도를 오름차순으로 돌며 덮으므로 가장 최근 표기가 남는다.
    order_map = {}

    def merge(order):
        for o in order:
            order_map[o["key"]] = o

    for y in sorted(years):
        if mode == "y":
            got, order = _rows_of(corp_code, y, "11011", divs)
            if not got:
                continue
            label = "%d" % y
            periods.append({"label": label, "year": y, "q": None})
            for k, v in got.items():
                cells.setdefault(k, {})[label] = v.get("cur")
            merge(order)
            continue

        per_q = {}
        for q in (1, 2, 3, 4):
            got, order = _rows_of(corp_code, y, Q_REPRT[q], divs)
            if got:
                per_q[q] = got
                merge(order)
        for q in (1, 2, 3, 4):
            if q not in per_q:
                continue
            label = "%dQ%d" % (y, q)
            periods.append({"label": label, "year": y, "q": q})
            for k, v in per_q[q].items():
                val = v.get("cur")
                if val is None and stmt == "IS" and q < 4 and v.get("cum") is not None:
                    # 3개월 칸이 비고 누적만 있는 줄(KB금융 2014 반기 순이익)
                    pc = 0 if q == 1 else per_q.get(q - 1, {}).get(k, {}).get("cum")
                    if pc is not None:
                        val = v["cum"] - pc
                nm_k = order_map.get(k, {}).get("name", "")
                if stmt == "CF" and not CF_BALANCE_RE.search(nm_k):
                    # 누적에서 전분기 누적을 뺀다. 잔액 계정(기초·기말 현금)은 제외.
                    prev = per_q.get(q - 1, {}).get(k, {}).get("cur") if q > 1 else 0
                    val = (val - prev) if (val is not None and prev is not None) else None
                elif stmt in ("IS",) and q == 4:
                    cum9 = per_q.get(3, {}).get(k, {}).get("cum")
                    if cum9 is None:
                        cum9 = per_q.get(3, {}).get(k, {}).get("cur")
                        cum9 = None          # 3분기 누적을 모르면 4분기를 못 뗀다
                    val = (val - cum9) if (val is not None and cum9 is not None) else None
                cells.setdefault(k, {})[label] = val

    periods.sort(key=lambda p: (p["year"], p["q"] or 0))
    labels = [p["label"] for p in periods]
    idx = {l: i for i, l in enumerate(labels)}

    # 1) 값만으로 행을 만든다
    raw = []
    for k, o in order_map.items():
        if k not in cells:
            continue
        v = [cells[k].get(l) for l in labels]
        if all(x is None for x in v):
            continue
        raw.append({"key": k, "name": o["name"], "div": o["div"], "v": v})

    # 2) 이름이 같고 연도가 겹치지 않는 행은 같은 계정이다. 합친다.
    #    키(태그)가 중간에 바뀌면 한 계정이 두 줄로 갈라진다. 원인이 셋이었다.
    #      택소노미 변경      dart_OtherCurrentLiabilities → ifrs-full_OtherCurrentLiabilities (2023)
    #      태그를 새로 붙임   '-표준계정코드 미사용-' → dart_NonCurrentFairValueFinancialAsset
    #      태그를 갈아탐      ifrs-full_ContractAssets → ifrs-full_CurrentContractAssets
    #    연도가 겹치면 합치지 않는다. 같은 해에 둘 다 있으면 진짜 다른 계정이다.
    groups = {}
    for r in raw:
        groups.setdefault(_merge_name(r["name"]), []).append(r)
    merged = []
    for grp in groups.values():
        grp.sort(key=lambda r: next(i for i, x in enumerate(r["v"]) if x is not None))
        acc = []
        for r in grp:
            cov = {i for i, x in enumerate(r["v"]) if x is not None}
            host = next((a for a in acc if not (a["cov"] & cov)), None)
            if host is None:
                acc.append(dict(r, cov=cov))
                continue
            for i in cov:
                host["v"][i] = r["v"][i]
            host["cov"] |= cov
            # 이름·표 구분은 더 최근 구간을 따른다
            if max(cov) > max(host["cov"] - cov, default=-1):
                host["name"], host["div"] = r["name"], r["div"]
            # 키는 태그 쪽을 쓴다. 앞 구간이 태그 없이 냈으면 합친 줄의 키가
            # 'nm:연결당기순이익' 으로 남아 태그 기준 줄 순서를 못 받는다
            # (SK: 2015~17 태그 없음, 2018~ ProfitLoss).
            if host["key"].startswith("nm:") and r["key"].startswith("t:"):
                host["key"] = r["key"]
        merged.extend(acc)

    if stmt == "IS":
        _fill_net_income(merged, len(labels))
    elif stmt == "BS":
        _fill_liabilities(merged, len(labels))

    # 3) 재무제표 순서
    merged.sort(key=lambda r: (_order_key(stmt, r["name"], r["key"]), r["name"]))

    # 4) 합친 뒤에 전년 대비를 계산한다. 먼저 계산하면 두 번째 구간 첫해는
    #    비교 기준이 없어서 증감률이 빈다.
    back = 4 if mode == "q" else 1
    out_rows = []
    for r in merged:
        vals = []
        for i, v in enumerate(r["v"]):
            base = r["v"][i - back] if i - back >= 0 else None
            yoy = None
            # 적자 기저에서의 증감률은 방향이 헷갈린다. 내지 않는다.
            if v is not None and base not in (None, 0) and base > 0:
                yoy = (v - base) / abs(base) * 100
            cell = {"v": v, "yoy": yoy}
            if i in r.get("derived", ()):
                cell["d"] = r["derived"][i]
            vals.append(cell)
        out_rows.append({"name": r["name"], "div": r["div"], "values": vals,
                         "key": r["key"],
                         "pershare": bool(PERSHARE_RE.search(r["name"]))})

    # 손익계산서(IS)와 포괄손익계산서(CIS)에 같은 이름의 계정이 따로 있다.
    # ('지배기업의 소유주지분' — 하나는 당기순이익 귀속, 하나는 총포괄손익 귀속)
    # 이름만 보면 중복으로 보이니 어느 표에서 온 줄인지 붙여준다.
    # DART 는 기말 잔액 줄 이름에 보고 주기를 박아 넣는다
    # (반기말의 현금및현금성자산 / 3분기말의 ... / 기말의 ...).
    # 태그로 묶어 한 줄이 됐으니 주기 표기를 떼서 '기말'로 통일한다.
    for r in out_rows:
        r["name"] = NUM_PREFIX.sub("", r["name"])      # 'VII. 당기순이익' → '당기순이익'
        r["name"] = re.sub(r"^(반기말|[1-4]분기말|분기말)의", "기말의", r["name"])
        # 분기 매트릭스는 마지막 보고서(반기보고서 등)의 줄 이름을 받는다. '반기순이익'
        # '분기연결순이익' 은 여러 분기를 잇는 줄에서 '당기순이익'으로 적는다.
        r["name"] = re.sub(r"^(?:당|분|반|[1-4]분)?(?:\((?:당|분|반)\))?(?:분|반)?기(?:연결)?순(이익|손실|손익)",
                           lambda m: "당기순" + m.group(1), r["name"])

    # 같은 이름이 손익계산서(IS)와 포괄손익계산서(CIS) 양쪽에 있을 때만 구분한다.
    # 삼성전기처럼 손익을 포괄손익계산서 하나로만 내는 회사는 전부 CIS 라서,
    # 'CIS 면 붙인다' 로 하면 모든 줄에 (포괄손익)이 붙는다.
    # 포괄손익계산서 하나로 내는 회사(남해화학)는 '지배기업의 소유주지분'이 두 번 나온다.
    # 하나는 당기순이익 귀속, 하나는 총포괄손익 귀속. 태그로 가려 뒤쪽에 표시한다.
    for r in out_rows:
        if r["key"].startswith("t:ComprehensiveIncomeAttributable") and "포괄" not in r["name"]:
            r["name"] = r["name"] + " (총포괄)"
    divs_of = {}
    for r in out_rows:
        divs_of.setdefault(r["name"], set()).add(r.get("div"))
    for r in out_rows:
        if r.get("div") == "CIS" and "IS" in divs_of.get(r["name"], ()):
            r["name"] = r["name"] + " (포괄손익)"

    return {"stmt": stmt, "stmt_name": STMT_NAME.get(stmt, stmt),
            "mode": mode, "periods": periods, "rows": out_rows}


# 화면에 세우는 순서와 표기
SPEC = [
    ("PER", "PER", "배", 2),
    ("PBR", "PBR", "배", 2),
    ("ROE", "ROE", "%", 2),
    ("EPS", "EPS", "원/주", 0),
    ("BPS", "BPS", "원/주", 0),
    ("자산총계", "자산", "원", 0),
    ("자본총계", "자본", "원", 0),
    ("부채총계", "부채", "원", 0),
    ("유보금", "유보금", "원", 0),
    ("유보율", "유보율", "%", 1),
    ("부채비율", "부채비율", "%", 1),
    ("매출액", "매출액", "원", 0),
    ("영업이익", "영업이익", "원", 0),
    ("당기순이익", "당기순이익", "원", 0),
    ("영업이익률", "영업이익률", "%", 2),
]


def compare(now, prev):
    """지표별 현재값 / 변화량 / 변화율. prev 가 없으면 변화는 비운다."""
    out = []
    for key, label, unit, digits in SPEC:
        cur = (now or {}).get(key)
        old = (prev or {}).get(key)
        row = {"key": key, "label": label, "unit": unit, "digits": digits,
               "value": cur, "prev": old, "delta": None, "pct": None}
        if cur is not None and old is not None:
            row["delta"] = cur - old
            if old != 0:
                row["pct"] = (cur - old) / abs(old) * 100
        out.append(row)
    return out
