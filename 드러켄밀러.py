# -*- coding: utf-8 -*-
"""
드러켄밀러 모드 — 분기 단독 실적의 '변화의 변화'를 본다.

드러켄밀러는 밸류에이션으로 타이밍을 잡지 않는다. 그가 보는 것은
18~24개월 뒤의 이익이고, 그 단서는 지금 수준(level)이 아니라
변화율의 변화(2차 미분)에 있다. 이 모듈은 그것만 만든다.

  1. 분기 단독 매출·영업이익 (누적치가 아니라 3개월 단독)
  2. 전년 동기 대비 증감률
  3. 가속도 = 증감률의 전분기 대비 변화 (%p)
  4. 꺾임 선행지표 — 재고일수, 매출채권회수일수, CAPEX 강도
  5. TTM 이익과 그 시점 주가로 계산한 PER

DART 분기보고서의 thstrm_amount 는 손익계산서 기준 '3개월 단독'이다.
사업보고서만 연간치라, 4분기는 연간 − 3분기누적으로 떼어낸다.
"""
import os
import re
import sys
import json

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("재무", os.path.join(BASE, "재무.py"))
FIN = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(FIN)

CACHE_DIR = os.path.join(BASE, ".cache", "druck")

Q_BY_REPRT = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
REPRT_BY_Q = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}

# 손익계산서에서 '3개월 단독'으로 뽑을 항목
IS_PICK = {
    "매출액": (["ifrs-full_Revenue"], r"^(매출액|수익\(매출액\)|영업수익)$"),
    "영업이익": (["dart_OperatingIncomeLoss",
                "ifrs-full_ProfitLossFromOperatingActivities"], r"^영업(?:이익|손익|손실)"),
    "당기순이익": (["ifrs-full_ProfitLoss"], r"^당기순(?:이익|손익|손실)"),
    "EPS": (["ifrs-full_BasicEarningsLossPerShare",
             "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations"],
            r"^(?:보통주\s*)?(?:계속영업\s*)?기본\s*주당"),
}
# 재무상태표에서 시점 잔액으로 뽑을 항목
BS_PICK = {
    "재고자산": (["ifrs-full_Inventories"], r"^재고자산$"),
    "매출채권": (["ifrs-full_TradeAndOtherCurrentReceivables"],
              r"^매출채권( 및 기타(유동)?채권)?$"),
    "유형자산": (["ifrs-full_PropertyPlantAndEquipment"], r"^유형자산$"),
    "자본총계": (["ifrs-full_Equity"], r"^자본총계$"),
}
CAPEX_RE = re.compile(r"유형자산의? ?(취득|증가)")


def _grab(rows, table, picks, field):
    out = {}
    for key, (ids, name_re) in picks.items():
        rx = re.compile(name_re)
        best = None
        for r in rows:
            if r.get("sj_div") not in table:
                continue
            nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
            if "우선주" in nm:
                continue
            # 재무.py 와 같은 판정 — 본문 줄('Ⅲ.영업손실')과 잘못 붙은 태그(롯데렌탈)를 가린다
            hit, aid = FIN._account_hit(r, nm, ids, rx)
            if not hit:
                continue
            v = FIN.num(r.get(field))
            if v is None:
                continue
            score = FIN._tag_score(aid, ids)
            if best is None or score > best[0]:
                best = (score, v)
        if best:
            out[key] = best[1]
    return out


def _capex(rows):
    """현금흐름표의 유형자산 취득액. 음수로 찍히는 곳이 많아 절대값."""
    for r in rows:
        if r.get("sj_div") != "CF":
            continue
        if CAPEX_RE.search((r.get("account_nm") or "")):
            v = FIN.num(r.get("thstrm_amount"))
            if v is not None:
                return abs(v)
    return None


def period_data(corp_code, year, q):
    """한 분기의 원장. 사업보고서는 연간치라 여기서는 그대로 두고,
    4분기 단독은 series() 에서 연간 − 3분기누적으로 뗀다."""
    reprt = REPRT_BY_Q[q]
    st = FIN.fetch_statement(corp_code, year, reprt)
    rows = st.get("list") or []
    if not rows:
        st = FIN.fetch_statement(corp_code, year, reprt, "OFS")
        rows = st.get("list") or []
    if not rows:
        return None
    d = {}
    d.update(_grab(rows, ("IS", "CIS"), IS_PICK, "thstrm_amount"))
    d.update(_grab(rows, ("BS",), BS_PICK, "thstrm_amount"))
    cum = _grab(rows, ("IS", "CIS"), IS_PICK, "thstrm_add_amount")
    for k, v in cum.items():
        d[k + "_누적"] = v
    cx = _capex(rows)
    if cx is not None:
        d["CAPEX"] = cx
    return d or None


def series(corp_code, stock_code, years, prices=None):
    """분기 시계열. years 는 [2011, ... 2026] 같은 오름차순 연도 목록."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    pts = []
    for y in years:
        for q in (1, 2, 3, 4):
            try:
                d = period_data(corp_code, y, q)
            except Exception:
                d = None
            if not d:
                continue
            pts.append({"year": y, "q": q, "label": "%dQ%d" % (y, q), "raw": d})

    # 4분기 단독 = 연간 − 3분기 누적
    by_key = {(p["year"], p["q"]): p for p in pts}
    for p in pts:
        raw = p["raw"]
        if p["q"] != 4:
            for k in ("매출액", "영업이익", "당기순이익", "EPS"):
                p[k] = raw.get(k)
            continue
        q3 = by_key.get((p["year"], 3), {}).get("raw", {})
        for k in ("매출액", "영업이익", "당기순이익"):
            ann, cum9 = raw.get(k), q3.get(k + "_누적")
            p[k] = (ann - cum9) if (ann is not None and cum9 is not None) else None
        eps_a, eps_c = raw.get("EPS"), q3.get("EPS_누적")
        p["EPS"] = (eps_a - eps_c) if (eps_a is not None and eps_c is not None) \
            else raw.get("EPS")
    for p in pts:
        for k in ("재고자산", "매출채권", "유형자산", "자본총계", "CAPEX"):
            p[k] = p["raw"].get(k)
        del p["raw"]

    pts.sort(key=lambda p: (p["year"], p["q"]))

    # 전년 동기 대비 증감률 -> 가속도
    idx = {(p["year"], p["q"]): i for i, p in enumerate(pts)}
    for i, p in enumerate(pts):
        j = idx.get((p["year"] - 1, p["q"]))
        for k, tag in (("매출액", "매출"), ("영업이익", "영업이익")):
            p[tag + "YoY"] = None
            if j is None:
                continue
            a, b = pts[j].get(k), p.get(k)
            if a is None or b is None or a <= 0:
                continue
            # 기저가 거의 0이면 증감률은 의미가 없다. 적자에서 흑자로 돌면
            # 수천 %가 찍히는데 차트도 판단도 망가진다. 이익은 매출의 1% 미만
            # 기저를 버리고, 대신 영업이익률 변화(%p)로 본다.
            if tag == "영업이익":
                base_rev = pts[j].get("매출액")
                if base_rev and a < base_rev * 0.01:
                    p[tag + "YoY_무의미"] = True
                    continue
            p[tag + "YoY"] = (b - a) / abs(a) * 100
        if p.get("매출액") and p.get("영업이익") is not None:
            p["영업이익률"] = p["영업이익"] / p["매출액"] * 100
            # 지주회사는 영업이익에 지분법이익이 잡히는데 매출은 지주사 자체
            # 매출뿐이라 비율이 수천 %로 튄다. 순위에 넣으면 안 되는 값이다.
            if abs(p["영업이익률"]) > 100:
                p["이익률_비정상"] = True

    for i, p in enumerate(pts):
        prev = pts[i - 1] if i else None
        for tag in ("매출", "영업이익"):
            p[tag + "가속"] = None
            if prev and p.get(tag + "YoY") is not None \
                    and prev.get(tag + "YoY") is not None:
                p[tag + "가속"] = p[tag + "YoY"] - prev[tag + "YoY"]
        p["이익률변화"] = None
        if prev and p.get("영업이익률") is not None \
                and prev.get("영업이익률") is not None:
            p["이익률변화"] = p["영업이익률"] - prev["영업이익률"]

    # 회전일수 — 분모는 TTM 매출이다.
    # 단일 분기 매출로 나누면 매출이 출렁이는 회사에서 지표가 망가진다.
    # (한미반도체 2026Q1 매출 509억 -> Q2 2,512억. 재고는 그대로인데
    #  재고일수가 309일 -> 52일로 찍힌다. 재고가 준 게 아니라 분모가 커진 것.)
    for i, p in enumerate(pts):
        win = pts[max(0, i - 3):i + 1]
        p["매출_TTM"] = (sum(w["매출액"] for w in win)
                       if len(win) == 4 and all(w.get("매출액") for w in win) else None)
        daily = (p["매출_TTM"] / 365.0) if p["매출_TTM"] else None
        p["재고일수"] = (p["재고자산"] / daily) if (daily and p.get("재고자산")) else None
        p["매출채권일수"] = (p["매출채권"] / daily) if (daily and p.get("매출채권")) else None
        rev = p.get("매출액")
        p["CAPEX강도"] = (p["CAPEX"] / rev * 100) if (rev and p.get("CAPEX")) else None

    # TTM 과 그 시점 PER
    for i, p in enumerate(pts):
        win = pts[max(0, i - 3):i + 1]
        if len(win) == 4 and all(w.get("EPS") is not None for w in win):
            p["EPS_TTM"] = sum(w["EPS"] for w in win)
        else:
            p["EPS_TTM"] = None
        if len(win) == 4 and all(w.get("영업이익") is not None for w in win):
            p["영업이익_TTM"] = sum(w["영업이익"] for w in win)
        else:
            p["영업이익_TTM"] = None
    return pts


def attach_prices(pts, stock_code, dates):
    """분기말 근처 주가로 PER. dates 는 {(year,q): 'YYYYMMDD'} (보고서 접수일)."""
    prices = FIN.fetch_prices(stock_code)
    for p in pts:
        d = dates.get((p["year"], p["q"]))
        if not d:
            continue
        px, pxd = FIN.price_on(prices, d)
        if not px:
            continue
        p["주가"] = px
        p["주가일"] = pxd
        if p.get("EPS_TTM") and p["EPS_TTM"] > 0:
            p["PER_TTM"] = px / p["EPS_TTM"]
    return pts


# ---------------------------------------------------------------- 본문 지표
# 표 안의 수치는 형식이 제각각이라, 뽑은 값과 함께 원문 줄을 같이 돌려준다.
# 숫자를 믿고 쓰기 전에 근거를 눈으로 확인할 수 있어야 한다.
TEXT_METRICS = [
    ("가동률", re.compile(r"가동률"), re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")),
    ("수주잔고", re.compile(r"수주\s?잔고|수주잔액"), re.compile(r"([\d,]{4,})")),
    ("생산능력", re.compile(r"생산\s?능력"), re.compile(r"([\d,]{3,})")),
]


def scan_text_metrics(text, limit=4):
    out = {}
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for name, key_rx, val_rx in TEXT_METRICS:
        hits = []
        for ln in lines:
            if not key_rx.search(ln):
                continue
            vals = val_rx.findall(ln)
            if not vals:
                continue
            nums = []
            for v in vals[:6]:
                x = FIN.num(v)
                if x is None:
                    continue
                if name == "가동률" and not (0 < x <= 100):
                    continue
                nums.append(x)
            if nums:
                hits.append({"line": ln[:400], "values": nums})
            if len(hits) >= limit:
                break
        if hits:
            out[name] = hits
    return out
