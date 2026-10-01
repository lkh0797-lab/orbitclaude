# -*- coding: utf-8 -*-
"""
업황 자료 — 회사 공시보다 먼저 움직이는 업종 단위 숫자 (2026-10-01)

  제품 가격  한국은행 ECOS 수출물가지수(기본분류, 원화기준, 402Y014) — 업종 제품의 수출 단가. 이익률을 먼저 움직인다.
  재고 순환  통계청 KOSIS 시도/산업별 광공업생산지수(DT_1F02001) 전국 · 업종별 생산자제품 출하지수(T11) · 재고지수(T12) 원지수.
             출하 증가율 − 재고 증가율 = 재고 순환. 플러스로 돌면 재고가 줄며 출하가 늘어 업황이 살아나는 쪽(고전적 선행 신호).
  업종       DART 기업개황(company.json)의 업종코드(한국표준산업분류). 앞 3자리로 KOSIS 업종, 앞 4·3·2자리 순으로 ECOS 품목을 고른다.

인증키는 .env 의 ECOS_API_KEY · KOSIS_API_KEY · (DART) — 화면 · 로그에 남기지 않는다.
캐시 .cache/거시/ — 월별 자료 3일, 업종코드는 영구.
"""
import os
import json
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache", "거시")
TTL = 3 * 86400

try:
    import importlib.util as _ilu
    _s = _ilu.spec_from_file_location("설정", os.path.join(BASE, "설정.py"))
    _cfg = _ilu.module_from_spec(_s)
    _s.loader.exec_module(_cfg)
    _get = _cfg.get
except Exception:          # 설정.py 가 없으면 환경변수만
    _get = lambda k, d=None: os.environ.get(k, d)

# 표준산업분류(앞자리) → ECOS 수출물가 기본분류 품목. 긴 앞자리부터 맞춘다. 선박 · 기타 운송장비는 수출물가에 없다(척마다 값이 달라 지수를 안 낸다)
KSIC_ECOS = {
    "2927": ("31124AA", "반도체·디스플레이 제조용 기계"), "2621": ("30921AA", "전자표시장치"),
    "2811": ("31011AA", "발전기 및 전동기"), "2812": ("31012AA", "전기 변환·공급 제어장치"),
    "2042": ("30562AA", "비누 및 화장품"),
    "192": ("3041AA", "석탄 및 석유제품"), "201": ("3051AA", "기초화학물질"), "202": ("3052AA", "합성수지 및 합성고무"),
    "203": ("3055AA", "비료 및 농약"), "204": ("3056AA", "기타 화학제품"), "205": ("3053AA", "화학섬유"),
    "211": ("3054AA", "의약품"), "212": ("3054AA", "의약품"), "213": ("3054AA", "의약품"),
    "221": ("3058AA", "고무제품"), "222": ("3057AA", "플라스틱제품"),
    "241": ("3071AA", "철강 1차제품"), "242": ("3072AA", "비철금속괴 및 1차제품"), "243": ("307AA", "1차 금속제품"),
    "261": ("30911AA", "반도체"), "262": ("3093AA", "기타 전자부품"), "263": ("3094AA", "컴퓨터 및 주변기기"),
    "264": ("30951AA", "통신 및 방송장비"), "265": ("30952AA", "영상 및 음향기기"), "271": ("30961AA", "의료 및 측정기기"),
    "272": ("30962AA", "기타 정밀기기"), "273": ("30962AA", "기타 정밀기기"),
    "281": ("31012AA", "전기 변환·공급 제어장치"), "282": ("31013AA", "전지"), "283": ("31014AA", "전선 및 케이블"),
    "284": ("31016AA", "기타 전기장비"), "285": ("31015AA", "가정용 전기기기"), "289": ("31016AA", "기타 전기장비"),
    "291": ("3111AA", "일반 목적용 기계"), "292": ("3112AA", "특수 목적용 기계"),
    "301": ("31211AA", "자동차"), "302": ("31212AA", "특장차 및 트레일러"), "303": ("31213AA", "자동차 부품"),
    "10": ("3011AA", "식료품"), "11": ("301AA", "음식료품"), "12": ("3013AA", "담배"), "13": ("3021AA", "섬유 및 의복"),
    "14": ("3021AA", "섬유 및 의복"), "15": ("3022AA", "가죽제품"), "17": ("3032AA", "펄프 및 종이제품"),
    "19": ("3041AA", "석탄 및 석유제품"), "20": ("305AA", "화학제품"), "21": ("3054AA", "의약품"), "22": ("3057AA", "플라스틱제품"),
    "23": ("3062AA", "기타 비금속광물제품"), "24": ("307AA", "1차 금속제품"), "25": ("3081AA", "금속가공제품"),
    "26": ("309AA", "컴퓨터·전자 및 광학기기"), "27": ("3096AA", "정밀기기"), "28": ("3101AA", "전기장비"),
    "29": ("311AA", "기계 및 장비"), "30": ("3121AA", "자동차 및 부품"), "33": ("3131AA", "기타 제조업제품"),
}


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _save(path, d):
    os.makedirs(CACHE, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    os.replace(tmp, path)


def ecos(item, table="402Y014", cur="W", start="200501", net=True):
    """ECOS 월별 지수 {YYYYMM: 값}. 원화기준(W)."""
    path = os.path.join(CACHE, "ecos_%s_%s_%s.json" % (table, item, cur))
    d = _load(path)
    if d and (not net or time.time() - d.get("ts", 0) < TTL):
        return d.get("v", {})
    key = _get("ECOS_API_KEY")
    if not key or not net:
        return (d or {}).get("v", {})
    end = time.strftime("%Y%m")
    try:
        js = requests.get("https://ecos.bok.or.kr/api/StatisticSearch/%s/json/kr/1/10000/%s/M/%s/%s/%s/%s"
                          % (key, table, start, end, item, cur), timeout=60).json()
        rows = (js.get("StatisticSearch") or {}).get("row") or []
    except Exception:
        return (d or {}).get("v", {})
    v = {}
    for x in rows:
        try:
            v[x["TIME"]] = float(x["DATA_VALUE"])
        except (KeyError, TypeError, ValueError):
            pass
    if v:
        _save(path, {"ts": time.time(), "v": v, "name": rows[0].get("ITEM_NAME1") if rows else ""})
    return v or (d or {}).get("v", {})


def kosis(ind, start="200501", net=True):
    """KOSIS 전국 · 업종 출하지수 · 재고지수(원지수) {'ship': {YYYYMM: 값}, 'inv': {...}, 'name': 업종 이름}."""
    path = os.path.join(CACHE, "kosis_%s.json" % ind)
    d = _load(path)
    if d and (not net or time.time() - d.get("ts", 0) < TTL):
        return d
    key = _get("KOSIS_API_KEY")
    if not key or not net:
        return d or {}
    end = time.strftime("%Y%m")
    try:
        js = requests.get("https://kosis.kr/openapi/Param/statisticsParameterData.do", timeout=90, params={
            "method": "getList", "apiKey": key, "itmId": "T11+T12+", "objL1": "00", "objL2": ind + "+",
            "format": "json", "jsonVD": "Y", "prdSe": "M", "startPrdDe": start, "endPrdDe": end,
            "orgId": "101", "tblId": "DT_1F02001"}).json()
    except Exception:
        return d or {}
    if not isinstance(js, list):
        return d or {}
    out = {"ts": time.time(), "ship": {}, "inv": {}, "name": ""}
    for x in js:
        try:
            v = float(x["DT"])
        except (KeyError, TypeError, ValueError):
            continue
        out["ship" if x.get("ITM_ID") == "T11" else "inv"][x["PRD_DE"]] = v
        out["name"] = x.get("C2_NM") or out["name"]
    if out["ship"]:
        _save(path, out)
        return out
    return d or {}


def induty(corp_code, api_key, net=True):
    """DART 기업개황의 업종코드(표준산업분류, 3~5자리). 영구 캐시."""
    path = os.path.join(CACHE, "induty.json")
    d = _load(path) or {}
    if corp_code in d:
        return d[corp_code]
    if not net or not api_key:
        return None
    try:
        js = requests.get("https://opendart.fss.or.kr/api/company.json", timeout=30,
                          params={"crtfc_key": api_key, "corp_code": corp_code}).json()
    except Exception:
        return None
    if js.get("status") != "000":
        return None
    d = _load(path) or {}
    d[corp_code] = (js.get("induty_code") or "").strip() or None
    _save(path, d)
    return d[corp_code]


KOSIS_CODES = None


def kosis_code(ksic):
    """업종코드 → KOSIS 업종(C + 3자리, 없으면 2자리)."""
    global KOSIS_CODES
    if KOSIS_CODES is None:
        KOSIS_CODES = set((_load(os.path.join(CACHE, "kosis_codes.json")) or []))
    if not ksic:
        return None
    for n in (3, 2):
        c = "C" + ksic[:n]
        if not KOSIS_CODES or c in KOSIS_CODES:
            return c
    return None


def ecos_item(ksic):
    if not ksic:
        return None
    for n in (4, 3, 2):
        hit = KSIC_ECOS.get(ksic[:n])
        if hit:
            return hit
    return None


def kosis_codes_refresh():
    """KOSIS 표에 있는 업종 코드 목록(한 번만)."""
    key = _get("KOSIS_API_KEY")
    if not key:
        return []
    m = requests.get("https://kosis.kr/openapi/statisticsData.do", timeout=60, params={
        "method": "getMeta", "type": "ITM", "apiKey": key, "orgId": "101", "tblId": "DT_1F02001",
        "format": "json", "jsonVD": "Y"}).json()
    codes = sorted({x.get("ITM_ID") for x in m if x.get("OBJ_ID") == "B"})
    _save(os.path.join(CACHE, "kosis_codes.json"), codes)
    return codes


def for_company(corp_code, dart_key, net=True):
    """회사 하나의 업황 자료 — {ksic, price: {월: 지수}, price_name, ship, inv, ind_name}."""
    ksic = induty(corp_code, dart_key, net=net)
    out = {"ksic": ksic}
    it = ecos_item(ksic)
    if it:
        out["price"] = ecos(it[0], net=net)
        out["price_name"] = it[1]
    kc = kosis_code(ksic)
    if kc:
        k = kosis(kc, net=net)
        out.update(ship=k.get("ship") or {}, inv=k.get("inv") or {}, ind_name=k.get("name") or kc, ind_code=kc)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("KOSIS 업종 코드", len(kosis_codes_refresh()))
    for code, (it, nm) in list(KSIC_ECOS.items())[:3]:
        v = ecos(it)
        print(code, nm, len(v), sorted(v)[-1] if v else None)
