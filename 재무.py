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
    "자본금":     (["ifrs-full_IssuedCapital"], r"^자본금$"),
    "이익잉여금": (["ifrs-full_RetainedEarnings"],
                  r"^이익잉여금|^결손금"),
    "주식발행초과금": (["ifrs-full_SharePremium"], r"^주식발행초과금$"),
    "자본잉여금": ([], r"^자본잉여금$"),
    "매출액":     (["ifrs-full_Revenue"], r"^(매출액|수익\(매출액\)|영업수익)$"),
    "영업이익":   (["dart_OperatingIncomeLoss",
                   "ifrs-full_ProfitLossFromOperatingActivities"],
                  r"^영업이익"),
    "당기순이익": (["ifrs-full_ProfitLoss"], r"^당기순이익"),
    "EPS":       (["ifrs-full_BasicEarningsLossPerShare"], r"^기본주당"),
}


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
            nm = (r.get("account_nm") or "").strip()
            aid = (r.get("account_id") or "").strip()
            hit = (aid in ids) if ids else False
            if not hit and rx.search(nm):
                hit = True
            if not hit:
                continue
            v = num(r.get("thstrm_amount"))
            if v is None:
                continue
            # 표준태그로 맞은 것을 이름으로 맞은 것보다 우선
            score = (2 if aid in ids else 1)
            if best is None or score > best[0]:
                best = (score, v)
        if best:
            out[key] = best[1]
    return out


# ---------------------------------------------------------------- DART
def fetch_statement(corp_code, year, reprt_code, fs_div="CFS"):
    os.makedirs(FIN_DIR, exist_ok=True)
    cache = os.path.join(FIN_DIR, "%s_%s_%s_%s.json"
                         % (corp_code, year, reprt_code, fs_div))
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    r = requests.get(DART + "/fnlttSinglAcntAll.json", timeout=90, params={
        "crtfc_key": API_KEY, "corp_code": corp_code, "bsns_year": str(year),
        "reprt_code": reprt_code, "fs_div": fs_div})
    r.raise_for_status()
    js = r.json()
    data = {"status": js.get("status"), "list": js.get("list") or []}
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    time.sleep(0.25)
    return data


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
