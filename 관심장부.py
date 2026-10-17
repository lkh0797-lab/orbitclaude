# -*- coding: utf-8 -*-
"""
관심 종목 성장 장부 (2026-10-17) — 한 회사를 몇 년 동안 같은 잣대로 본다.

종목을 장부에 넣으면 그날의 사실(가속 B · 국면 · 매출 증가율 · 수주잔고 · 북투빌 · PER 자기 역사 자리 · 수출 · 공시 위험)을
사진처럼 남긴다. 가설은 정해진 틀(TEMPLATES)에서 고른다 — 틀마다 기존 백테스트 숫자와 '검증됨 · 관계 없음 · 반박됨' 표시를 붙인다.
새 숫자가 들어올 때마다(밤 가속도 계산 · 공시목록 · 월간 통관 · 주가) 가설을 다시 따지고, 전날과 달라진 것만 알림함에 올린다.
새 신호를 만들지 않는다 — 이미 검증한 사실을 제때 보게 할 뿐이다.

가짜 변화 막기(이것이 이 장부의 핵심 — 가짜 '깨짐'이 나가면 도구를 못 믿게 된다):
  - 식 버전(ver)이 바뀌면 조용히 다시 기준을 잡는다(가속도 VERSION · 풍경 LAND_V · 수주 VERSION · 수출 통로)
  - 값이 비거나 '모름'(ok=False: 자료 품질 · 늦은 국면 · 못 믿을 잔고 · 낡은 판)은 변화가 아니다 — 마지막으로 믿을 만했던 값을 쥐고 있는다
  - 기준(as_of)이 뒤로 가면(공시 당일 DART 빈 원장 013 으로 분기가 빠짐) 대기 — 변화로 내지 않는다
  - 같은 기준인데 입력 지문(fp)이 바뀌면 정정 재계산 — 숫자 알림은 내지 않고, 가설이 뒤집히면 '정정 반영'으로만(경고 아님)
  - 주가가 든 사실(PER 자리)과 문턱 근처 값은 히스테리시스(문턱 ± hyst 를 넘어야 뒤집힘)
  - 공시 위험은 기준일이 뒤로 가면 비교하지 않는다(그날 013 이 오면 열린 분기 파일이 비어 등급이 내려갔다 돌아온다)

순수 함수 — 파일 읽기는 부르는 쪽(서버 _watch_facts · 도구/관심장부_재현.py)이 하고 여기에는 dict 만 들어온다.
개인 자료라 파일은 개인/관심장부.json(gitignore). 경로는 환경변수 ORBIT_WATCH_PATH 로 바꿀 수 있다.
저장 = 임시 파일 → os.replace, 하루 한 번 backup/관심장부_YYYYMMDD.json(30개). 깨진 파일은 읽지도 덮어쓰지도 않는다.
동시 접근 잠금은 부르는 쪽(서버)이 건다. 규칙을 바꾸면 FACT_V 를 올린다(올리면 모든 사실이 조용히 다시 기준을 잡는다).
"""
import os
import re
import copy
import json
import math
import time
import uuid
import shutil
import zlib
import tempfile
import datetime as dt

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = "ORBIT_WATCH_PATH"
VER = 1
FACT_V = 1
BACKUP_DIR = "backup"
BACKUP_PREFIX = "관심장부_"
BACKUP_KEEP = 30
INBOX_MAX = 400          # 알림함 — 넘으면 읽은 것부터 오래된 순으로 버린다
LOG_MAX = 40             # 회사마다 남기는 판정 기록(편입 이후 궤적)
TEXT_MAX = {"why": 1000, "note": 300, "close_why": 300}
_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BK_RE = re.compile(r"^" + BACKUP_PREFIX + r"(\d{8})\.json$")

# 가속도 창에 이 표시가 있으면 B · 국면을 믿지 않는다(README '데이터 품질': Q4 단독 못 뗌 · 빈 분기 · 결산월 · 재작성 · 혼합)
DRK_BAD = ("gap", "fy", "basis", "mix", "asfiled")
WEAK_PHASES = ("정체", "부진 지속", "수축 심화")
RISK_RED = ("상폐 절차", "보고서 없음", "작전주 꼴")

# ---------------------------------------------------------------- 가설 틀
# fact = 사실 열쇠, op = 'ge'(값 ≥ 문턱이면 지킴) · 'le'(값 ≤ 문턱) · 'not_in'(값이 목록 밖) · 'none'(값이 없음 = 지킴)
# ev = 근거(기존 백테스트, 12개월 초과수익 중앙 [90% 구간]) · grade = 검증됨 | 약함 | 관계 없음 | 반박됨 | 검증 안 됨
TEMPLATES = [
    {"key": "blog_gap", "label": "수주잔고 증가율이 매출 증가율보다 크게 뒤처지지 않는다", "fact": "blog_gap", "op": "ge",
     "th": -15.0, "unit": "%p", "hyst": 3.0, "grade": "검증됨",
     "ev": "잔고 < 매출 −15%p 는 12개월 −4.1%p [−6.3, −1.6] · 잔고 > 매출 +15%p 는 +3.6 [+1.3, +6.1], 4분기 뒤 매출 +13.8%p (분기 변화 백테스트 29,660건)"},
    {"key": "btb", "label": "북투빌(잔고 1년 증가분 ÷ 매출 + 1) ≥ 1 — 들어오는 일이 나가는 일보다 많다", "fact": "btb", "op": "ge",
     "th": 1.0, "unit": "", "hyst": 0.05, "grade": "검증됨",
     "ev": "북투빌 위 − 아래 +10.7%p [+6.0, +15.7], 앞 +6.0 · 뒤 +14.0 (시너지 백테스트 169곳 — 표본 작음)"},
    {"key": "per_zone", "label": "PER 이 자기 역사에서 비싼 자리(상위 25%)로 가지 않는다", "fact": "per_pct", "op": "le",
     "th": 75.0, "unit": "%", "hyst": 3.0, "grade": "검증됨",
     "ev": "비싼 구간 1년 초과수익 −3.4%p, 30% 넘게 뒤처진 비율 15.0% vs 보통 10.3% (보통값 백테스트 11,949건) · PER 상위 30% −5.0 [−6.5, −3.6]"},
    {"key": "risk_none", "label": "공시 위험(상폐 절차 · 보고서 없음 · 작전주 꼴)에 들지 않는다", "fact": "risk", "op": "not_in",
     "th": list(RISK_RED), "unit": "", "hyst": 0, "grade": "검증됨",
     "ev": "작전주 꼴은 상장사 8.2% 를 거르고 24개월 사망의 64% [56, 72] 를 피했다(걸린 쪽 14.1% vs 남은 쪽 0.72%, 2019~2024 표본 밖)"},
    {"key": "phase_ok", "label": "매출 국면이 정체 · 부진 지속 · 수축 심화로 가지 않는다", "fact": "phase", "op": "not_in",
     "th": list(WEAK_PHASES), "unit": "", "hyst": 0, "grade": "약함",
     "ev": "정체만 −4.7%p [−8.1, −0.6] 로 뚜렷하다. 부진 지속 −0.8 [−3.1, +2.3] · 수축 심화 +0.3 [−1.0, +1.8] 은 0 을 걸친다 (가속도 기저율 23,478건)"},
    {"key": "rev_up", "label": "최근 4분기 매출이 1년 전보다 늘어 있다", "fact": "rev_yoy", "op": "ge",
     "th": 0.0, "unit": "%", "hyst": 1.0, "grade": "검증 안 됨",
     "ev": "매출 증가율 수준만으로는 12개월 초과수익과 관계가 없었다(시너지 rev4_yoy IC −0.003) — 성장 자체를 지켜보는 줄"},
    {"key": "accel_pos", "label": "가속 B ≥ 0 — 매출 증가율이 느려지지 않는다", "fact": "accel_b", "op": "ge",
     "th": 0.0, "unit": "%p", "hyst": 1.0, "grade": "관계 없음",
     "ev": "'B ≥ 0' 상태는 12개월 초과수익과 관계가 없었다(IC −0.002, 23,478건) — 관찰용. 변곡 ▲ 는 +1.9 [+0.6, +3.5] 이지만 엄격 표본은 0 을 걸친다"},
    {"key": "export_up", "label": "분기 맞춤 수출 통관이 1년 전보다 늘어 있다", "fact": "export", "op": "ge",
     "th": 0.0, "unit": "%", "hyst": 2.0, "grade": "약함",
     "ev": "통관 증가율은 그 분기 매출 증가율을 미리 읽는다(순위상관 0.37, t 12) — 주가 신호는 아니다(90일 0.05, 뚜렷하지 않음)"},
    {"key": "inv_ok", "label": "재고일수가 1년 전보다 15일 넘게 늘지 않는다", "fact": "inv_d4", "op": "le",
     "th": 15.0, "unit": "일", "hyst": 3.0, "grade": "반박됨",
     "ev": "재고 쌓임 경고는 검증에서 수익을 가르지 못해 판정에서 뺐다 — 사실 확인용으로만 둔다"},
]
TPL = {t["key"]: t for t in TEMPLATES}
FACT_LABEL = {"accel_b": "가속 B", "phase": "국면", "turn": "변곡", "rev_yoy": "매출 1년(최근 4분기)", "inv_d4": "재고일수 1년 변화",
              "blog_yoy": "수주잔고 1년", "btb": "북투빌", "blog_gap": "잔고 − 매출", "per_pct": "PER 자기 역사 자리",
              "export": "수출 통관(분기 맞춤)", "risk": "공시 위험", "filing": "마지막 정기보고서", "price": "주가"}


# ---------------------------------------------------------------- 사실 만들기(순수 — 이미 읽은 dict 를 받는다)
def F(v, as_of=None, ver="", fp="", ok=True, why=None, extra=None):
    f = {"v": v, "as_of": as_of, "ver": str(ver), "fp": str(fp), "ok": bool(ok and v is not None)}
    if why or (v is None):
        f["why"] = why or "값 없음"
    if extra:
        f["x"] = extra
    return f


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def druck_facts(d, cut=None):
    """가속도 캐시(.cache/druck/{code}.json, 드러켄밀러.read_cache 를 거친 dict) → 가속 B · 국면 · 변곡 · 매출 1년 · 재고일수 1년 변화.
    '지금 점' = 국면이 있는 마지막 점(화면 drkCalc 와 같은 정의). cut('YYYYMMDD')을 주면 그날 알 수 있던 점만(B기준일 ≤ cut) — 재현용.
    창(n−3..n)에 DRK_BAD 표시가 있거나 국면이 원장보다 2분기 넘게 늦으면 ok=False(값은 남겨 보인다)."""
    if not d or not d.get("points"):
        return {}
    pts = d["points"]
    if cut:
        pts = [p for p in pts if (p.get("기준일") or "99999999") <= cut]
    ver = "d%s.%s" % (d.get("v"), d.get("basis") or "")
    by_n = {p.get("n"): p for p in pts if p.get("n") is not None}
    V = [p for p in pts if p.get("국면") and (not cut or (p.get("B기준일") or "99999999") <= cut)]
    if not V:
        return {}
    now = V[-1]
    n = now.get("n")
    lastD = next((p for p in reversed(pts) if p.get("fs")), now)
    win = [by_n.get(k) for k in range(n - 3, n + 1)] if n is not None else [now]
    flags = sorted({q for p in win if p for q in (p.get("품질") or [])})
    bad = [q for q in flags if q in DRK_BAD]
    late = (lastD.get("n") or n) - n >= 2
    fp = "|".join("%s" % ((p or {}).get("기준일") or "-") for p in win) + ("|amended" if "amended" in flags else "")
    ok, why = True, None
    if bad:
        ok, why = False, "자료 품질: " + ", ".join(bad)
    elif late:
        ok, why = False, "국면이 원장보다 %d분기 늦음" % ((lastD.get("n") or n) - n)
    as_of = "%06d" % n if n is not None else (now.get("label") or "")    # 분기 키 — 글자 비교가 시간 순서와 같게
    lab = now.get("label") or str(n)
    asb = now.get("B기준일")
    out = {
        "accel_b": F(_num(now.get("가속B")), as_of, ver, fp, ok, why, {"asb": asb, "speed": _num(now.get("속도")), "label": lab}),
        "phase": F(now.get("국면"), as_of, ver, fp, ok, why, {"label": lab}),
        "turn": F(now.get("변곡") or "", as_of, ver, fp, ok, why, {"label": lab}),
    }
    p4 = by_n.get(n - 4) if n is not None else None
    t0, t4 = _num(now.get("매출_TTM")), _num((p4 or {}).get("매출_TTM"))
    g = (t0 / t4 - 1) * 100 if (t0 and t4 and t0 > 0 and t4 > 0) else None
    out["rev_yoy"] = F(round(g, 2) if g is not None else None, as_of, ver, fp, ok and g is not None, why, {"ttm": t0, "label": lab})
    i0, i4 = _num(now.get("재고일수")), _num((p4 or {}).get("재고일수"))
    di = (i0 - i4) if (i0 is not None and i4 is not None) else None
    out["inv_d4"] = F(round(di, 1) if di is not None else None, as_of, ver, fp, ok and di is not None, why, {"days": i0})
    return out


def _stamp_q(stamp):
    """'2026-06' → '2026Q2'."""
    try:
        return "%sQ%d" % (stamp[:4], (int(stamp[5:7]) - 1) // 3 + 1)
    except (TypeError, ValueError):
        return None


def backlog_facts(tr, ver, rev=None, as_of=None, reliable_why=None):
    """수주잔고 — 수주.trend(pts) 결과 tr(서버는 캐시만으로 pts 를 만든다). rev = 가속도의 rev_yoy 사실(최근 4분기 매출 · 그 1년 변화).
    btb = 1 + (잔고 − 1년 전 같은 방식 잔고) ÷ 최근 4분기 매출 · blog_gap = 잔고 1년 − 매출 1년(%p, 분기 변화 판정과 같은 꼴).
    못 믿음: 점 4개 미만 · 5배 튐 · 마지막에 읽는 방식이 바뀌며 튐 · (btb · blog_gap) 잔고 분기와 매출 분기가 다름.
    매출을 쓰는 두 사실은 가속도 쪽 기준 · 버전 · 지문을 같이 싣는다 — 가속도만 새 분기로 가거나 정정 · 버전이 바뀐 것을 잔고 변화로 읽지 않게
    (리뷰 2026-10-17: 잔고는 3분기, 가속도는 2분기인 판에서 어긋난 분기끼리 빼서 가짜 '가설 깨짐'이 나갔다)."""
    if not tr:
        return {}
    why = reliable_why
    if not why:
        if tr.get("n", 0) < 4:
            why = "잔고 점 %d개뿐" % tr.get("n", 0)
        elif tr.get("jumps"):
            why = "잔고가 한 번에 5배 넘게 튐"
        elif tr.get("last_switch"):
            why = "마지막에 읽는 방식이 바뀌며 튐(%s)" % (tr.get("last_method") or "")
    ok = why is None
    a = as_of or tr.get("to")
    fp = "%s|%s|%s" % (tr.get("last_method") or "", tr.get("b1") or "", tr.get("last") or "")
    ver = "b%s" % ver
    yoy = _num(tr.get("yoy"))
    out = {"blog_yoy": F(round(yoy, 2) if yoy is not None else None, a, ver, fp, ok, why, {"last": tr.get("last")})}
    rv = rev if (rev and rev.get("ok")) else None
    rev_ttm = _num(((rv or {}).get("x") or {}).get("ttm"))
    rev_yoy = _num((rv or {}).get("v"))
    rq, bq = ((rv or {}).get("x") or {}).get("label"), _stamp_q(a)
    why2 = why
    if not why2 and rv and rq and bq and rq != bq:
        why2 = "잔고(%s)와 매출(%s) 분기가 다름 — 한쪽이 아직 안 들어옴" % (bq, rq)
    ver2 = "%s+%s" % (ver, (rv or {}).get("ver") or "-")
    a2 = "%s|%s" % (a, (rv or {}).get("as_of") or "")
    fp2 = "%s|%s|%s|%s" % (fp, (rv or {}).get("fp") or "", rev_ttm, rev_yoy)
    b1, last = _num(tr.get("b1")), _num(tr.get("last"))
    btb = 1 + (last - b1) / rev_ttm if (b1 and last is not None and rev_ttm and rev_ttm > 0) else None
    out["btb"] = F(round(btb, 3) if btb is not None else None, a2, ver2, fp2, why2 is None, why2)
    gap = (yoy - rev_yoy) if (yoy is not None and rev_yoy is not None) else None
    out["blog_gap"] = F(round(gap, 2) if gap is not None else None, a2, ver2, fp2, why2 is None, why2)
    return out


def per_facts(land, land_v, latest_rcept=None):
    """풍경 판(.cache/landscape/{code}.json) decide.pct — PER 이 자기 역사 PER 기록 중 몇 % 보다 비싼 자리인가.
    판 버전이 다르거나 부정 캐시면 없음. 판이 마지막 보고서보다 옛것이면 ok=False('낡은 판')."""
    if not land or land.get("error") or land.get("v") != land_v:
        return {}
    dc = land.get("decide") or {}
    pct = _num(dc.get("pct"))
    sig0 = str(land.get("sig") or "").split(":")[0]
    stale = bool(latest_rcept and sig0 and sig0 < latest_rcept)
    band = land.get("band") or {}
    return {"per_pct": F(round(pct, 1) if pct is not None else None, dc.get("date"), "l%s" % land_v,
                         "%s|%s" % (sig0, band.get("n")), not stale, "풍경 판이 마지막 보고서보다 옛것" if stale else None,
                         {"per": _num(dc.get("per")), "n": band.get("n")})}


def export_facts(item, aligned, file_v=None):
    """수출 추적 — 분기 맞춤 통관 증가율(aligned.cur). 기준 = (분기, 들어간 달들) — 같은 분기에 달이 늘면 '새 달'.
    통로(시군구 · HS) 서명이 바뀌면 ver 가 바뀌어 다시 기준을 잡는다. 덩어리 수출 · 통로 없음은 ok=False."""
    if not item or item.get("status") != "ok" or not aligned:
        return {}
    cur = _num(aligned.get("cur"))
    chs = sorted("%s/%s" % (c.get("sgg") or c.get("sido") or "", c.get("hs") or "") for c in item.get("channels") or [])
    ver = "x%s.%08x" % (file_v, zlib.crc32("|".join(chs).encode("utf-8")))
    as_of = "%s:%s" % (aligned.get("cur_q") or "", ",".join(aligned.get("months") or []))
    why = "덩어리 수출(한 달 몰림)" if aligned.get("lumpy") else None
    return {"export": F(round(cur, 1) if cur is not None else None, as_of, ver, "", why is None, why,
                        {"grade": item.get("grade"), "state": aligned.get("state"), "cur_q": aligned.get("cur_q"),
                         "months": aligned.get("months"), "prev": _num(aligned.get("prev"))})}


def risk_facts(row, base_day=None):
    """공시 위험(.cache/공시목록/공시위험.json codes[code]). 값 = 등급(없으면 '').
    본표본이 아니면 '잣대 밖', codes 에 없으면 '판정 대상 아님'(ok=False).
    공시 당일 DART 013 이 오면 열린 분기 파일 하나만 비어 기준일은 그대로인 채 등급이 빠졌다 돌아온다 — step 이 등급 바뀜을
    다른 기준일에서 두 번 연속 볼 때만 받는다(디바운스, 리뷰 2026-10-17)."""
    if row is None:
        return {"risk": F(None, base_day, "r1", "", False, "판정 대상 아님")}
    if row.get("group") != "본표본":
        return {"risk": F(None, base_day, "r1", "", False, "잣대 밖(%s)" % (row.get("group") or "?"))}
    return {"risk": F(row.get("level") or "", base_day, "r1", "", True, None,
                      {"hits": [h.get("cat") for h in row.get("hits") or []]})}


def filing_fact(rep, tier=None):
    """마지막 정기보고서(정정 아닌 것) — 접수번호가 바뀌면 '새 보고서'. tier = 궤도 등급(그 보고서에서 처음 본 값으로 얼린다)."""
    if not rep:
        return {}
    return {"filing": F(rep.get("rcept"), rep.get("rcept", "")[:8], "f1", "", True, None,
                        {"label": rep.get("label"), "stamp": rep.get("stamp"), "tier": tier})}


def price_fact(px):
    """.cache/price/{code}.json {YYYYMMDD: 종가} → 마지막 종가. 알림에는 쓰지 않는다(편입 이후 수익률용)."""
    if not px:
        return {}
    k = max(px)
    return {"price": F(_num(px[k]), k, "p1", "", True)}


# ---------------------------------------------------------------- 가설 판정
def hyp_value(h, facts):
    t = TPL.get(h.get("tpl"))
    if not t:
        return None, None
    return t, (facts or {}).get(t["fact"])


def judge(h, fact, prev=None):
    """가설 하나 → 'ok' | 'broken' | 'unknown'. 히스테리시스: 앞 판정이 있으면 문턱 ± hyst 를 넘어야 뒤집힌다."""
    t = TPL.get(h.get("tpl"))
    if not t or not fact or not fact.get("ok"):
        return "unknown"
    v = fact.get("v")
    th = h.get("th", t["th"])
    if t["op"] in ("ge", "le"):
        v, th = _num(v), _num(th)
        if v is None or th is None:
            return "unknown"
        hy = float(t.get("hyst") or 0)
        if t["op"] == "ge":
            if prev == "broken":
                return "ok" if v >= th + hy else "broken"
            if prev == "ok":
                return "broken" if v < th - hy else "ok"
            return "ok" if v >= th else "broken"
        if prev == "broken":
            return "ok" if v <= th - hy else "broken"
        if prev == "ok":
            return "broken" if v > th + hy else "ok"
        return "ok" if v <= th else "broken"
    if t["op"] == "not_in":
        return "broken" if v in (th or []) else "ok"
    if t["op"] == "none":
        return "ok" if not v else "broken"
    return "unknown"


def fmt(key, v):
    if v is None or v == "":
        return "—" if key != "risk" else "없음"
    if key in ("accel_b", "blog_gap"):
        return "%+.1f%%p" % v
    if key in ("rev_yoy", "blog_yoy", "export"):
        return "%+.1f%%" % v
    if key == "per_pct":
        return "%.0f%%" % v
    if key == "btb":
        return "%.2f" % v
    if key == "inv_d4":
        return "%+.0f일" % v
    if key == "price":
        return "{:,.0f}".format(v)
    return str(v)


# ---------------------------------------------------------------- 비교 — 바뀐 것만, 가짜 변화는 막는다
def classify(prev, cur):
    """사실 하나의 바뀜 꼴: None(그대로 · 비교 안 함) | 'rebase'(식 버전) | 'wait'(기준이 뒤로) | 'amend'(같은 기준, 입력 바뀜) | 'new'(새 기준)."""
    if not cur or not cur.get("ok"):
        return None
    if not prev:
        return "first"
    if prev.get("ver") != cur.get("ver"):
        return "rebase"
    pa, ca = str(prev.get("as_of") or ""), str(cur.get("as_of") or "")
    if ca < pa:
        return "wait"
    if ca > pa:
        return "new"
    if prev.get("fp") != cur.get("fp") or prev.get("v") != cur.get("v"):
        return "amend"
    return None


DRK_KEYS = ("accel_b", "phase", "turn", "rev_yoy", "inv_d4")
BLOG_KEYS = ("blog_yoy", "btb", "blog_gap")


def step(st, facts, hyps, today, name="", code=""):
    """회사 하나 다시 따지기 — 순수. st = 지난 상태 {good:{key:fact}, hyp:{id:status}, log:[…]} 또는 None.
    돌려주는 것: (새 상태, 알림 목록). 알림 = {kind, level(warn|good|info), title, lines[]}.
    첫 판(편입 직후)은 알림 없이 기준만 잡는다."""
    st = copy.deepcopy(st) if st else {"good": {}, "hyp": {}, "log": []}
    good = st.setdefault("good", {})
    first_run = not good and not st.get("hyp")
    facts = dict(facts or {})
    # 공시 위험 등급 바뀜은 다른 기준일에서 두 번 연속 같을 때만 받는다 — 그 전에는 지난 등급을 그대로 쓴다(가설 판정도)
    rf, rg = facts.get("risk"), good.get("risk")
    if rf and rf.get("ok") and rg and (rf.get("v") or "") != (rg.get("v") or ""):
        pend = st.get("risk_pending")
        if pend and pend.get("v") == (rf.get("v") or "") and pend.get("as_of") != rf.get("as_of"):
            st.pop("risk_pending", None)
        else:
            if not pend or pend.get("v") != (rf.get("v") or ""):
                st["risk_pending"] = {"v": rf.get("v") or "", "as_of": rf.get("as_of")}
            facts["risk"] = dict(rg, as_of=rg.get("as_of"))
    elif rf and rf.get("ok"):
        st.pop("risk_pending", None)
    kinds = {}
    for k, f in (facts or {}).items():
        c = classify(good.get(k), f)
        kinds[k] = c
    ev = []

    def add(kind, level, title, lines=None):
        ev.append({"kind": kind, "level": level, "title": title, "lines": lines or []})

    # 1) 새 분기 숫자(가속도) — 한 알림으로 묶는다
    if not first_run and any(kinds.get(k) == "new" for k in DRK_KEYS):
        cur = {k: facts[k] for k in DRK_KEYS if k in facts and facts[k].get("ok")}
        lines, level = [], "info"
        for k in ("rev_yoy", "accel_b"):
            if k in cur:
                lines.append("%s %s → %s" % (FACT_LABEL[k], fmt(k, (good.get(k) or {}).get("v")), fmt(k, cur[k]["v"])))
        if "phase" in cur:
            p0, p1 = (good.get("phase") or {}).get("v"), cur["phase"]["v"]
            lines.append("국면 %s" % (p1 if p0 == p1 else "%s → %s" % (p0 or "—", p1)))
            if p1 in WEAK_PHASES and p0 != p1:
                level = "warn"
        tv = (cur.get("turn") or {}).get("v")
        if tv:
            lines.append("변곡 %s — 한 분기 만에 가속 부호가 바뀜(헛신호 약 23%%)" % tv)
            level = "good" if tv == "▲" and level != "warn" else ("warn" if tv == "▼" else level)
        add("quarter", level, "새 분기 숫자 %s" % (((facts.get("accel_b") or facts.get("phase") or {}).get("x") or {}).get("label") or ""), lines)
    # 2) 수주잔고 새 점
    if not first_run and any(kinds.get(k) == "new" for k in BLOG_KEYS):
        b = facts.get("blog_yoy") or {}
        lines = ["잔고 1년 %s → %s" % (fmt("blog_yoy", (good.get("blog_yoy") or {}).get("v")), fmt("blog_yoy", b.get("v")))]
        if (facts.get("btb") or {}).get("ok"):
            lines.append("북투빌 %s" % fmt("btb", facts["btb"]["v"]))
        if (facts.get("blog_gap") or {}).get("ok"):
            lines.append("잔고 − 매출 %s" % fmt("blog_gap", facts["blog_gap"]["v"]))
        add("backlog", "info", "수주잔고 새 점 %s" % (b.get("as_of") or ""), lines)
    # 3) 새 정기보고서 — 같은 판에 새 분기 숫자가 있으면 그 알림에 한 줄로 붙인다(따로 내면 분기마다 알림이 둘)
    if not first_run and kinds.get("filing") == "new":
        x = facts["filing"].get("x") or {}
        t = x.get("tier")
        line = "새 %s (%s)" % (x.get("label") or "보고서", x.get("stamp") or "") + (" — 궤도 '%s' · 평소보다 많이 고쳐 씀" % t if t in ("격변", "큼") else "")
        q = next((e for e in ev if e["kind"] == "quarter"), None)
        if q:
            q["lines"].insert(0, line)
            if t == "격변" and q["level"] == "info":
                q["level"] = "warn"
        else:
            add("filing", "warn" if t == "격변" else "info", line, [])
    # 4) 수출 — 상태 글이 바뀔 때만(달마다 숫자가 들어와도 같은 흐름이면 알리지 않는다)
    xf = facts.get("export")
    if not first_run and kinds.get("export") == "new" and xf:
        s0 = ((good.get("export") or {}).get("x") or {}).get("state")
        s1 = (xf.get("x") or {}).get("state")
        if s0 != s1:
            add("export", "info", "수출 흐름 %s → %s" % (s0 or "—", s1 or "—"),
                ["분기 맞춤 통관 %s (%s)" % (fmt("export", xf["v"]), xf.get("as_of"))])
    # 5) 공시 위험 등급
    rf = facts.get("risk")
    if not first_run and rf and rf.get("ok") and kinds.get("risk") in ("new", "amend"):
        r0, r1 = (good.get("risk") or {}).get("v") or "", rf.get("v") or ""
        if r0 != r1:
            if r1 in RISK_RED:
                add("risk", "warn", "공시 위험 '%s' 에 들어감" % r1, ["걸린 범주: " + ", ".join((rf.get("x") or {}).get("hits") or [])])
            elif r0 in RISK_RED:
                add("risk", "good", "공시 위험 '%s' 에서 빠짐" % r0, [])
    # 6) 가설
    hst = st.setdefault("hyp", {})
    for h in hyps or []:
        t, f = hyp_value(h, facts)
        if not t:
            continue
        p = hst.get(h["id"])
        cause = kinds.get(t["fact"])
        if cause == "wait":             # 기준이 뒤로 감(공시 당일 빈 원장) — 앞 판정을 쥐고 있는다
            continue
        if cause == "rebase":           # 식 버전이 바뀜 — 조용히 다시 기준
            s = judge(h, f, None)
            if s != "unknown":
                hst[h["id"]] = s
            continue
        s = judge(h, f, p if p in ("ok", "broken") else None)
        if s == "unknown":
            continue                    # 모름은 바뀜이 아니다 — 앞 판정을 쥐고 있는다
        if p in ("ok", "broken") and s != p and not first_run:
            val = fmt(t["fact"], f.get("v"))
            if cause == "amend":
                add("hyp", "info", "정정 반영 — 가설 '%s' %s" % (t["label"], "다시 지켜짐" if s == "ok" else "벗어남"),
                    ["%s %s (같은 분기 숫자가 정정 · 다시 계산됨)" % (FACT_LABEL.get(t["fact"], t["fact"]), val)])
            elif s == "broken":
                add("hyp", "warn", "가설 깨짐 — %s" % t["label"],
                    ["%s %s (문턱 %s)" % (FACT_LABEL.get(t["fact"], t["fact"]), val, _th_txt(t, h)), "근거: " + t["ev"]])
            else:
                add("hyp", "good", "가설 다시 지켜짐 — %s" % t["label"], ["%s %s" % (FACT_LABEL.get(t["fact"], t["fact"]), val)])
        hst[h["id"]] = s
    # 7) 믿을 만한 값만 기준으로 쥔다
    for k, f in (facts or {}).items():
        c = kinds.get(k)
        if c in ("first", "rebase", "new", "amend"):
            good[k] = f
    st["at"] = today
    for e in ev:
        st.setdefault("log", []).append({"d": today, "kind": e["kind"], "level": e["level"], "title": e["title"]})
    st["log"] = st.get("log", [])[-LOG_MAX:]
    for e in ev:
        e.update(code=code, name=name)
    return st, ev


def _th_txt(t, h):
    th = h.get("th", t["th"])
    if isinstance(th, list):
        return "‘" + " · ".join(th) + "’ 아님"
    return ("≥ " if t["op"] == "ge" else "≤ ") + fmt(t["fact"], _num(th)) if t["fact"] not in ("btb",) else ("≥ %.2f" % _num(th))


# ---------------------------------------------------------------- 파일
def default_path():
    p = os.environ.get(ENV_PATH, "").strip()
    if p:
        return os.path.abspath(os.path.expanduser(p))
    return os.path.join(BASE, "개인", "관심장부.json")


def empty():
    return {"ver": VER, "entries": [], "state": {}, "inbox": []}


def _check_shape(data, what):
    if not isinstance(data, dict):
        raise ValueError("%s: 최상위가 객체가 아니다" % what)
    ver = data.get("ver", VER)
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1 or ver > VER:
        raise ValueError("%s: 모르는 형식 버전 %r (이 코드는 %d까지 읽는다)" % (what, ver, VER))
    if not isinstance(data.get("entries"), list) or not all(isinstance(e, dict) for e in data["entries"]):
        raise ValueError("%s: entries 가 목록이 아니다" % what)
    if not isinstance(data.get("state", {}), dict) or not isinstance(data.get("inbox", []), list):
        raise ValueError("%s: state · inbox 꼴이 다르다" % what)


def load(path=None):
    path = path or default_path()
    if not os.path.exists(path):
        return empty()
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as e:
        raise ValueError("관심장부 파일이 깨져 있다 — 손대지 않았다: %s (%s)" % (path, e)) from None
    _check_shape(data, "관심장부 파일(%s)" % path)
    data.setdefault("state", {})
    data.setdefault("inbox", [])
    return data


def _replace(src, dst):
    for i in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == 4:
                raise
            time.sleep(0.1 * (i + 1))


def _write_atomic(path, text):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _backup(path, day):
    bdir = os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, BACKUP_PREFIX + day.strftime("%Y%m%d") + ".json")
    if not os.path.exists(dst):
        fd, tmp = tempfile.mkstemp(prefix="." + BACKUP_PREFIX, suffix=".tmp", dir=bdir)
        os.close(fd)
        try:
            shutil.copyfile(path, tmp)
            _replace(tmp, dst)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    for n in sorted((n for n in os.listdir(bdir) if _BK_RE.match(n)), reverse=True)[BACKUP_KEEP:]:
        try:
            os.remove(os.path.join(bdir, n))
        except OSError:
            pass


def save(path, data, today=None):
    path = path or default_path()
    _check_shape(data, "저장할 관심장부")
    out = dict(data)
    out["ver"] = VER
    text = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False) + "\n"
    text.encode("utf-8")
    if os.path.exists(path):
        load(path)
        _backup(path, _as_date(today) or dt.date.today())
    _write_atomic(path, text)


# ---------------------------------------------------------------- 사용자 입력
def _as_date(v):
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and _DATE_RE.match(v):
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            return None
    return None


def _text(v, k):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError("%s 는 글자여야 한다" % k)
    v = v.strip()
    if len(v) > TEXT_MAX[k]:
        raise ValueError("%s 가 너무 길다(%d자까지)" % (k, TEXT_MAX[k]))
    return v


def clean_hyp(h):
    """가설 하나 검증 — 틀 열쇠 · 문턱(숫자 틀만, 틀 기본값 ±10배 안) · 메모."""
    if not isinstance(h, dict):
        raise ValueError("가설 꼴이 다르다")
    t = TPL.get(h.get("tpl"))
    if not t:
        raise ValueError("모르는 가설 틀: %r" % h.get("tpl"))
    out = {"id": h.get("id") if isinstance(h.get("id"), str) and re.fullmatch(r"[0-9a-f]{8,32}", h.get("id") or "") else uuid.uuid4().hex[:12],
           "tpl": t["key"]}
    if t["op"] in ("ge", "le"):
        th = h.get("th", t["th"])
        th = _num(th)
        if th is None:
            raise ValueError("'%s' 문턱이 숫자가 아니다" % t["label"])
        lim = max(abs(t["th"]) * 10, 100 if t["unit"] in ("%", "%p", "일") else 10)
        if abs(th) > lim:
            raise ValueError("'%s' 문턱이 너무 크다" % t["label"])
        out["th"] = th
    out["note"] = _text(h.get("note"), "note")
    return out


def apply(data, action, payload, today, now_iso, name_of=None):
    """장부 바꾸기 — 순수(입력은 그대로, 바뀐 사본을 돌려준다). action:
    add {code, why, hyps:[{tpl, th?, note?}], snap?} · update {id, why?, hyps?} · delete {id} · close {id, why} · reopen {id}
    seen {ids:[…]} · seen_all {} · clear_seen {}"""
    d = copy.deepcopy(data)
    today = _as_date(today) or dt.date.today()
    if action == "add":
        code = str(payload.get("code") or "").strip().upper()
        if not _CODE_RE.match(code):
            raise ValueError("종목코드가 6자리가 아니다")
        if any(e["code"] == code and not e.get("closed") for e in d["entries"]):
            raise ValueError("이미 장부에 있는 종목이다")
        hyps = [clean_hyp(h) for h in payload.get("hyps") or []]
        if len(hyps) > 12:
            raise ValueError("가설은 12개까지")
        e = {"id": uuid.uuid4().hex[:12], "code": code, "name": (name_of(code) if name_of else "") or code,
             "added": today.isoformat(), "why": _text(payload.get("why"), "why"), "hyps": hyps,
             "snap": payload.get("snap") or {}, "closed": None, "created": now_iso, "updated": now_iso}
        d["entries"].append(e)
        d["state"].pop(code, None)          # 다시 넣은 종목은 새 기준에서 시작
        return d, e
    if action in ("seen", "seen_all", "clear_seen"):
        ids = set(payload.get("ids") or [])
        if action == "clear_seen":
            d["inbox"] = [m for m in d["inbox"] if not m.get("seen")]
        for m in d["inbox"]:
            if action == "seen_all" or m.get("id") in ids:
                m["seen"] = True
        return d, None
    e = next((x for x in d["entries"] if x.get("id") == payload.get("id")), None)
    if not e:
        raise ValueError("장부에 없는 항목이다")
    if action == "update":
        if "why" in payload:
            e["why"] = _text(payload.get("why"), "why")
        if "hyps" in payload:
            hyps = [clean_hyp(h) for h in payload.get("hyps") or []]
            if len(hyps) > 12:
                raise ValueError("가설은 12개까지")
            old = {h["id"]: h for h in e.get("hyps") or []}
            e["hyps"] = hyps
            st = d["state"].get(e["code"])
            if st:      # 같은 id 라도 틀 · 문턱이 바뀌면 옛 판정을 지운다(서버가 지금 값으로 앞 판정 없이 다시 잰다 — 다음 판의 가짜 '깨짐' 막기)
                keep = {h["id"] for h in hyps if h["id"] in old and old[h["id"]].get("tpl") == h["tpl"] and old[h["id"]].get("th") == h.get("th")}
                st["hyp"] = {k: v for k, v in (st.get("hyp") or {}).items() if k in keep}
        e["updated"] = now_iso
    elif action == "delete":
        d["entries"] = [x for x in d["entries"] if x is not e]
        if not any(x["code"] == e["code"] for x in d["entries"]):
            d["state"].pop(e["code"], None)
    elif action == "close":
        e["closed"] = {"date": today.isoformat(), "why": _text(payload.get("why"), "close_why")}
        e["updated"] = now_iso
    elif action == "reopen":
        if any(x["code"] == e["code"] and not x.get("closed") and x is not e for x in d["entries"]):
            raise ValueError("같은 종목이 이미 열려 있다")
        e["closed"] = None
        e["updated"] = now_iso
    else:
        raise ValueError("모르는 동작: %r" % action)
    return d, e


def push_inbox(data, events, today):
    """알림을 알림함 앞에 붙인다. 같은 날 같은 회사 · 같은 제목은 한 번만. 넘치면 읽은 것부터 버린다."""
    have = {(m.get("d"), m.get("code"), m.get("title")) for m in data["inbox"]}
    new = []
    for e in events:
        k = (today, e.get("code"), e.get("title"))
        if k in have:
            continue
        have.add(k)
        new.append(dict(e, id=uuid.uuid4().hex[:12], d=today, seen=False))
    data["inbox"] = new + data["inbox"]
    if len(data["inbox"]) > INBOX_MAX:
        keep = [m for m in data["inbox"] if not m.get("seen")]
        seen = [m for m in data["inbox"] if m.get("seen")]
        data["inbox"] = (keep + seen)[:INBOX_MAX]
        data["inbox"].sort(key=lambda m: m.get("d") or "", reverse=True)
    return new


def run_all(data, facts_of, today):
    """열린 항목 전부 다시 따지기. facts_of(code) → 사실 dict(부르는 쪽이 캐시만 읽는다). (새 data, 새 알림) 순수."""
    d = copy.deepcopy(data)
    allev = []
    by_code = {}
    for e in d["entries"]:
        if e.get("closed"):
            continue
        by_code.setdefault(e["code"], []).append(e)
    for code, es in by_code.items():
        err = None
        try:
            facts = facts_of(code) or {}
        except Exception as ex:          # 한 회사가 깨져도 나머지는 돈다
            facts, err = {}, "%s: %s" % (type(ex).__name__, ex)
        hyps = [h for e in es for h in e.get("hyps") or []]
        st, ev = step(d["state"].get(code), facts, hyps, today, es[0].get("name") or code, code)
        st["now"] = facts
        if err:
            st["err"] = err
        else:
            st.pop("err", None)
        d["state"][code] = st
        allev.extend(ev)
    push_inbox(d, allev, today)
    return d, allev


def snap_of(facts):
    """편입 때 사진 — 믿을 만한 값만 {key: {v, as_of}}."""
    return {k: {"v": f.get("v"), "as_of": f.get("as_of")} for k, f in (facts or {}).items() if f.get("ok")}


def templates_meta():
    return [{k: t[k] for k in ("key", "label", "fact", "op", "th", "unit", "grade", "ev")} for t in TEMPLATES]
