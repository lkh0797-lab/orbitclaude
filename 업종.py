# -*- coding: utf-8 -*-
"""
업종·테마 분류 — 종목코드를 대분류 / 업종 / 테마에 붙인다.

출처는 네이버 금융.
  업종(industry) 79개 : 종목당 하나. 깔끔하지만 '반도체와반도체장비' 처럼 넓다.
  테마(theme)   264개 : 종목당 여러 개. HBM, 원자력발전, 로봇, 조선기자재 처럼
                        투자자가 실제로 쓰는 단위다.
  대분류 ~16개         : 업종 79개를 여기서 직접 묶은 것. 네이버에는 없다.

DART 에는 표준산업분류(KSIC)만 있다. '전자부품 제조업' 같은 통계 분류라
투자 판단에는 거의 쓸모가 없어서 쓰지 않았다.

분류표는 하루 단위로 캐시한다. 처음 한 번은 업종 79 + 테마 264 = 343번
호출해야 해서 1~2분 걸린다. DART 한도와는 무관하다.
"""
import os
import json
import time

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE, ".cache", "업종")
MAP_PATH = os.path.join(CACHE_DIR, "map.json")
NAVER = "https://m.stock.naver.com/api/stocks/%s"
HEAD = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}

# 네이버 업종 79개 -> 대분류. 투자자가 섹터를 말할 때 쓰는 단위로 묶었다.
SECTOR_OF = {
    "반도체와반도체장비": "반도체",
    "디스플레이장비및부품": "디스플레이/전자부품", "디스플레이패널": "디스플레이/전자부품",
    "전자장비와기기": "디스플레이/전자부품", "전자제품": "디스플레이/전자부품",
    "핸드셋": "디스플레이/전자부품", "컴퓨터와주변기기": "디스플레이/전자부품",
    "사무용전자제품": "디스플레이/전자부품", "통신장비": "디스플레이/전자부품",
    "전기제품": "2차전지/전기장비", "전기장비": "2차전지/전기장비",
    "전기유틸리티": "전력/에너지", "가스유틸리티": "전력/에너지",
    "복합유틸리티": "전력/에너지", "에너지장비및서비스": "전력/에너지",
    "석유와가스": "전력/에너지",
    "제약": "바이오/헬스케어", "생물공학": "바이오/헬스케어",
    "생명과학도구및서비스": "바이오/헬스케어", "건강관리장비와용품": "바이오/헬스케어",
    "건강관리업체및서비스": "바이오/헬스케어", "건강관리기술": "바이오/헬스케어",
    "자동차": "자동차", "자동차부품": "자동차",
    "조선": "조선/해운/운송", "해운사": "조선/해운/운송", "항공사": "조선/해운/운송",
    "항공화물운송과물류": "조선/해운/운송", "운송인프라": "조선/해운/운송",
    "도로와철도운송": "조선/해운/운송",
    "우주항공과국방": "방산/우주",
    "기계": "기계/산업재", "복합기업": "기계/산업재",
    "상업서비스와공급품": "기계/산업재", "무역회사와판매업체": "기계/산업재",
    "화학": "화학/소재", "철강": "화학/소재", "비철금속": "화학/소재",
    "포장재": "화학/소재", "종이와목재": "화학/소재",
    "건설": "건설/부동산", "건축자재": "건설/부동산", "건축제품": "건설/부동산",
    "부동산": "건설/부동산",
    "은행": "금융", "증권": "금융", "손해보험": "금융", "생명보험": "금융",
    "카드": "금융", "기타금융": "금융", "창업투자": "금융",
    "IT서비스": "IT/SW/플랫폼", "소프트웨어": "IT/SW/플랫폼",
    "양방향미디어와서비스": "IT/SW/플랫폼", "게임엔터테인먼트": "IT/SW/플랫폼",
    "무선통신서비스": "통신", "다각화된통신서비스": "통신",
    "방송과엔터테인먼트": "엔터/미디어", "광고": "엔터/미디어",
    "출판": "엔터/미디어", "교육서비스": "엔터/미디어",
    "화장품": "소비재", "식품": "소비재", "음료": "소비재",
    "섬유,의류,신발,호화품": "소비재", "가정용기기와용품": "소비재",
    "가정용품": "소비재", "가구": "소비재", "레저용장비와제품": "소비재",
    "담배": "소비재", "문구류": "소비재", "식품과기본식료품소매": "소비재",
    "백화점과일반상점": "소비재", "판매업체": "소비재",
    "인터넷과카탈로그소매": "소비재", "전문소매": "소비재",
    "호텔,레스토랑,레저": "소비재", "다각화된소비자서비스": "소비재",
}


def _get(path, params=None):
    r = requests.get(NAVER % path, params=params or {}, headers=HEAD, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_groups(kind):
    """kind: industry | theme -> [{no, name, total}]"""
    out, page = [], 1
    while page < 20:
        js = _get(kind, {"page": page, "pageSize": 100})
        g = js.get("groups") or []
        if not g:
            break
        out += [{"no": x.get("no"), "name": (x.get("name") or "").strip(),
                 "total": x.get("totalCount") or 0} for x in g]
        if len(g) < 100:
            break
        page += 1
        time.sleep(0.12)
    return out


def fetch_members(kind, no):
    codes, page = [], 1
    while page < 30:
        js = _get("%s/%s" % (kind, no), {"page": page, "pageSize": 100})
        st = js.get("stocks") or []
        if not st:
            break
        codes += [(s.get("itemCode") or "").strip().upper() for s in st if s.get("itemCode")]
        if len(st) < 100:
            break
        page += 1
        time.sleep(0.1)
    return codes


def build(progress=None):
    """전체 분류표를 새로 만든다. 1~2분."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    stocks = {}
    ind = fetch_groups("industry")
    thm = fetch_groups("theme")
    total = len(ind) + len(thm)
    done = 0
    for g in ind:
        try:
            for code in fetch_members("industry", g["no"]):
                s = stocks.setdefault(code, {"themes": []})
                s["industry"] = g["name"]
                s["sector"] = SECTOR_OF.get(g["name"], "기타")
        except Exception:
            pass
        done += 1
        if progress:
            progress(done, total)
        time.sleep(0.1)
    for g in thm:
        try:
            for code in fetch_members("theme", g["no"]):
                stocks.setdefault(code, {"themes": []})["themes"].append(g["name"])
        except Exception:
            pass
        done += 1
        if progress:
            progress(done, total)
        time.sleep(0.1)
    out = {"built": time.time(), "stocks": stocks,
           "industries": {g["name"]: g["total"] for g in ind},
           "themes": {g["name"]: g["total"] for g in thm}}
    with open(MAP_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


def load(max_age=86400):
    """캐시가 있으면 쓴다. 없거나 오래됐으면 None — 빌드는 호출 측이 뒤에서 돌린다."""
    if not os.path.exists(MAP_PATH):
        return None
    try:
        with open(MAP_PATH, "r", encoding="utf-8") as fh:
            m = json.load(fh)
    except Exception:
        return None
    m["stale"] = time.time() - m.get("built", 0) > max_age
    return m
