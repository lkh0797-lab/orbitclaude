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

VERSION = 2          # 2: 분기 키 · 재작성 비교 · 기준일 · 품질 · 분할 보정 EPS · B(2026-10-09). 계산을 바꾸면 올린다 — 캐시가 전부 다시 계산된다
LAST = {"transient": 0, "fy_bad": []}
KEYS_IS = ("매출액", "영업이익", "당기순이익", "지배순이익", "EPS")

Q_BY_REPRT = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
REPRT_BY_Q = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}

# 손익계산서에서 '3개월 단독'으로 뽑을 항목
IS_PICK = {
    "매출액": (["ifrs-full_Revenue"], r"^(매출액|수익\(매출액\)|영업수익)$"),
    "영업이익": (["dart_OperatingIncomeLoss",
                "ifrs-full_ProfitLossFromOperatingActivities"], r"^영업(?:이익|손익|손실)"),
    "당기순이익": (["ifrs-full_ProfitLoss"], r"^당기순(?:이익|손익|손실)"),
    "지배순이익": (["ifrs-full_ProfitLossAttributableToOwnersOfParent"], r"^(지배기업\s*)?(소유주|지배주주|지배기업).*(지분|순이익|귀속)"),
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
            # 총포괄손익 귀속 줄('지배기업지분' · '비지배지분' — ComprehensiveIncomeAttributableTo…)은 이름이 같아도
            # 당기순이익 귀속 줄이 아니다(2024 00100601: 이름만 맞춰 총포괄 쪽 -1,125,449,589 를 집었다)
            if FIN.norm_tag(r.get("account_id")).startswith("ifrs-full_ComprehensiveIncome"):
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


# 지배순이익 대체용 — 당기순이익에서 뺄 비지배 몫(당기순이익 귀속 줄). 태그가 없는 줄은 이름('비지배지분')으로 잡는다
NCI_PICK = {"비지배순이익": ([FIN.NI_PARTS["nci"]], r"^비지배")}
# (원장 칸, 키 접미사) — 그 보고서의 값 · 누적 · 전년 같은 분기 · 전년 같은 누적 · 전년 연간
IS_FIELDS = (("thstrm_amount", ""), ("thstrm_add_amount", "_누적"), ("frmtrm_q_amount", "_전"),
             ("frmtrm_add_amount", "_전누적"), ("frmtrm_amount", "_전연"))

NET = {"budget": None, "used": 0}   # offline 빌드의 네트워크 예산 — 캐시 파일이 없을 때만 센다


def _fetch(corp_code, year, reprt, fs_div, offline):
    if offline:
        path = os.path.join(FIN.FIN_DIR, "%s_%s_%s_%s.json" % (corp_code, year, reprt, fs_div))
        if not os.path.exists(path):
            if NET["budget"] is not None and NET["used"] >= NET["budget"]:
                return {"status": "budget", "list": [], "transient": True}
            NET["used"] += 1
    return FIN.fetch_statement(corp_code, year, reprt, fs_div)


def period_data(corp_code, year, q, offline=False):
    """한 분기의 원장 — 그 보고서의 값(thstrm) · 누적(thstrm_add) · 비교기간(frmtrm_q · frmtrm_add · frmtrm) · 기준(CFS/OFS) · 출처 · rcept.
    4분기 단독은 series() 에서 연간 − 3분기 누적으로 뗀다."""
    reprt = REPRT_BY_Q[q]
    st = _fetch(corp_code, year, reprt, "CFS", offline)
    if st.get("transient"):
        return {"_transient": True}
    rows, fs = st.get("list") or [], "CFS"
    if not rows:
        st = _fetch(corp_code, year, reprt, "OFS", offline)
        if st.get("transient"):
            return {"_transient": True}
        rows, fs = st.get("list") or [], "OFS"
    if not rows:
        return None
    d = {}
    d.update(_grab(rows, ("BS",), BS_PICK, "thstrm_amount"))
    has_nci = any(_grab(rows, ("IS", "CIS"), NCI_PICK, fld) for fld, _ in IS_FIELDS)
    for fld, suf in IS_FIELDS:
        got = _grab(rows, ("IS", "CIS"), IS_PICK, fld)
        if "지배순이익" not in got and got.get("당기순이익") is not None:
            # 지배기업 귀속 줄이 없으면 당기순이익 − 비지배 몫(비지배 줄이 아예 없으면 당기순이익 그대로 — 재무._net_income_from 과 같은 규칙)
            nci = _grab(rows, ("IS", "CIS"), NCI_PICK, fld).get("비지배순이익")
            if nci is not None:
                got["지배순이익"] = got["당기순이익"] - nci
            elif not has_nci:
                got["지배순이익"] = got["당기순이익"]
        for k, v in got.items():
            d[k + suf] = v
    if q == 1:
        for k in IS_PICK:
            if d.get(k + "_전") is None and d.get(k + "_전누적") is not None:
                d[k + "_전"] = d[k + "_전누적"]
    if q != 4:                              # 분기 · 반기 보고서의 frmtrm_amount 는 대개 없고, 있으면 누적값이다 — 쓰지 않는다
        for k in IS_PICK:
            d.pop(k + "_전연", None)
    cx = _capex(rows)
    if cx is not None:
        d["CAPEX"] = cx
    if not any(not k.startswith("_") for k in d):
        return None
    rc = [str(r.get("rcept_no") or "")[:8] for r in rows if r.get("rcept_no")]
    d.update(_fs=fs, _src="body" if st.get("status") == "body" else "api", _rcept=max(rc) if rc else None, _transient=False)
    return d


def _n(y, q):
    return y * 4 + q - 1


def series(corp_code, stock_code, years, prices=None, meta=None, offline=False):
    """분기 시계열 v2 — n 오름차순 조밀 격자. meta = {filed: {n: 원본 공시일}, fy_bad: {연도}, fin: bool}."""
    meta = meta or {}
    filed, fy_bad = meta.get("filed") or {}, set(meta.get("fy_bad") or ())
    LAST.update(transient=0, fy_bad=sorted(fy_bad))
    raw = {}
    for y in years:
        for q in (1, 2, 3, 4):
            try:
                d = period_data(corp_code, y, q, offline=offline)
            except Exception:
                d = {"_transient": True}
            if d and d.get("_transient"):
                LAST["transient"] += 1
                continue
            if d:
                raw[_n(y, q)] = d
    if not raw:
        return []
    n0, n1 = min(raw), max(raw)
    pts = []
    for n in range(n0, n1 + 1):
        y, q = n // 4, n % 4 + 1
        p = {"year": y, "q": q, "label": "%dQ%d" % (y, q), "n": n, "품질": []}
        d = raw.get(n)
        if y in fy_bad:
            p["품질"].append("fy")
            d = None
        if d is None:
            if "fy" not in p["품질"]:
                p["품질"].append("gap")
            pts.append(p)
            continue
        p["fs"] = d.get("_fs")
        if q != 4:
            for k in KEYS_IS:
                p[k] = d.get(k)
                p[k + "_전"] = d.get(k + "_전")
        else:
            q3 = raw.get(n - 1) or {}
            same_fs = q3.get("_fs") == d.get("_fs")
            # 범위 검사 — 사업보고서 비교연도 ÷ 전년 사업보고서, Q3 비교 누적 ÷ 전년 Q3 누적 이 2% 넘게 다르면 연말 재작성
            pa, p3 = raw.get(n - 4) or {}, raw.get(n - 5) or {}
            scope_ok = True
            ra = (d.get("매출액_전연") / pa["매출액"]) if d.get("매출액_전연") and pa.get("매출액") else None
            r3 = (q3.get("매출액_전누적") / p3["매출액_누적"]) if q3.get("매출액_전누적") and p3.get("매출액_누적") else None
            if ra is not None and r3 is not None and abs(ra / r3 - 1) > 0.02:
                scope_ok = False
            for k in KEYS_IS:
                ann, cum9 = d.get(k), q3.get(k + "_누적")
                ok = same_fs and scope_ok and ann is not None and cum9 is not None
                p[k] = (ann - cum9) if ok else None
                pa_, pc_ = d.get(k + "_전연"), q3.get(k + "_전누적")
                p[k + "_전"] = (pa_ - pc_) if (ok and pa_ is not None and pc_ is not None) else None
            if d.get("매출액") is not None and p.get("매출액") is None:
                p["품질"].append("basis")
        for k in ("재고자산", "매출채권", "유형자산", "자본총계"):
            p[k] = d.get(k)
        cx, cx_prev = d.get("CAPEX"), (raw.get(n - 1) or {}).get("CAPEX") if q != 1 else 0
        p["CAPEX"] = (cx - cx_prev) if (cx is not None and cx_prev is not None) else None
        f0 = filed.get(n)
        rc = d.get("_rcept")
        p["기준일"] = max(x for x in (f0, rc) if x) if (f0 or rc) else None
        if f0 and rc and rc > f0:
            p["품질"].append("amended")
        pts.append(p)
    by = {p["n"]: p for p in pts}
    # 이상값 — 그 분기와 앞 분기들만 본다
    for p in pts:
        v = p.get("매출액")
        if v is None:
            continue
        prev = by.get(p["n"] - 1) or {}
        hist = [by[m]["매출액"] for m in range(p["n"] - 4, p["n"]) if m in by and by[m].get("매출액")]
        med = sorted(hist)[len(hist) // 2] if hist else None
        if v <= 0 or (med is not None and med > 0 and v < 0):
            p["매출액"] = None; p["품질"].append("neg")
        elif prev.get("매출액") is not None and prev["매출액"] == v:
            p["매출액"] = None; p["품질"].append("dup")
    # 전년 대비 — 공시 당시(매출YoY) · 재작성(YoY_r)
    for p in pts:
        b = by.get(p["n"] - 4) or {}
        for k, tag in (("매출액", "매출"), ("영업이익", "영업이익")):
            a, v = b.get(k), p.get(k)
            p[tag + "YoY"] = None
            if a is not None and v is not None and a > 0:
                if tag == "영업이익" and b.get("매출액") and a < b["매출액"] * 0.01:
                    p[tag + "YoY_무의미"] = True
                else:
                    p[tag + "YoY"] = (v - a) / abs(a) * 100
            pr = p.get(k + "_전")
            key_r = "YoY_r" if tag == "매출" else "영업이익YoY_r"
            p[key_r] = (v - pr) / abs(pr) * 100 if (v is not None and pr is not None and pr > 0) else None
        if p.get("매출액") and p.get("영업이익") is not None:
            p["영업이익률"] = p["영업이익"] / p["매출액"] * 100
            if abs(p["영업이익률"]) > 100:
                p["이익률_비정상"] = True
    for p in pts:
        prev = by.get(p["n"] - 1) or {}
        for tag in ("매출", "영업이익"):
            a, b_ = p.get(tag + "YoY"), prev.get(tag + "YoY")
            p[tag + "가속"] = (a - b_) if (a is not None and b_ is not None) else None
        p["이익률변화"] = (p["영업이익률"] - prev["영업이익률"]) if (p.get("영업이익률") is not None and prev.get("영업이익률") is not None) else None
    # TTM · 회전일수 · CAPEX 강도 — 연속 네 분기(키)일 때만
    for p in pts:
        win = [by.get(m) or {} for m in range(p["n"] - 3, p["n"] + 1)]
        p["매출_TTM"] = sum(w["매출액"] for w in win) if all(w.get("매출액") for w in win) else None
        p["영업이익_TTM"] = sum(w["영업이익"] for w in win) if all(w.get("영업이익") is not None for w in win) else None
        if p["매출_TTM"] and len({w.get("fs") for w in win}) > 1:
            p["품질"].append("basis")
        daily = p["매출_TTM"] / 365.0 if p["매출_TTM"] else None
        p["재고일수"] = (p["재고자산"] / daily) if (daily and p.get("재고자산")) else None
        p["매출채권일수"] = (p["매출채권"] / daily) if (daily and p.get("매출채권")) else None
        cw = [w.get("CAPEX") for w in win]
        p["CAPEX강도"] = (sum(cw) / p["매출_TTM"] * 100) if (p["매출_TTM"] and all(c is not None for c in cw)) else None
    for p in pts:
        p["품질"] = sorted(set(p["품질"]))
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
