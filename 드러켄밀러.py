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
import time
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("재무", os.path.join(BASE, "재무.py"))
FIN = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(FIN)

CACHE_DIR = os.path.join(BASE, ".cache", "druck")

VERSION = 2          # 2: 분기 키 조밀 격자 · Q4 기준/범위 검사 · 재작성 전년 비교(YoY_r) · 기준일 · 품질 표시 · 이상값 (2026-10-09). 계산을 바꾸면 올린다 — 캐시가 전부 다시 계산된다


def read_cache(path):
    """가속도 캐시 파일 → dict — v 가 지금 VERSION 일 때만. 없는 파일 · 깨진 JSON · 옛 버전은 None(다시 계산할 대상).
    서버 _druck_read 가 이것만 부른다 — 캐시를 읽는 곳은 모두 이 규칙을 거친다."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("v") == VERSION else None


def write_cache(path, obj, tries=5, wait=0.2):
    """캐시 원자 쓰기 — path.tmp 에 쓰고 os.replace. 읽는 쪽이 잠금 없이 파일을 열고 있으면 Windows 의 replace 가
    PermissionError(WinError 5)로 실패한다 — wait 초 쉬며 tries 번까지 다시 해 본다. 끝내 못 바꾸면 .tmp 를 지우고 False(캐시 안 됨)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            if i < tries - 1:
                time.sleep(wait)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


_Q_OF_MONTH = {"03": 1, "06": 2, "09": 3, "12": 4}
_FILED_OK = {("분기보고서", "03"), ("반기보고서", "06"), ("분기보고서", "09"), ("사업보고서", "12")}


def filed_meta(reports):
    """series() 의 meta — {filed: {n: 원본(정정 아닌) 보고서 접수일 YYYYMMDD — 여럿이면 가장 이른 날}, fy_bad: {연도}}.
    reports = [{stamp: 'YYYY-MM', label, tag, rcept}](서버 회사 색인의 보고서). 12월 결산 정기보고서(분기 03 · 반기 06 · 분기 09 · 사업 12)가
    아닌 보고서가 하나라도 있는 해는 fy_bad — 결산월이 달라 분기 키가 어긋나니 그해는 받지 않는다."""
    filed, fy_bad = {}, set()
    for r in reports:
        y, mth = r["stamp"].split("-")
        if (r["label"], mth) not in _FILED_OK:
            fy_bad.add(int(y))
            continue
        n = int(y) * 4 + _Q_OF_MONTH[mth] - 1
        if not r["tag"]:
            filed[n] = min(filed.get(n, "99999999"), r["rcept"][:8])
    return {"filed": filed, "fy_bad": fy_bad}


class _Last(threading.local):
    """series() 가 끝난 뒤 그 회사 결과 {transient: 일시 오류로 건너뛴 분기 수, fy_bad: [연도], error: 마지막 삼킨 예외 "종류: 내용" | None}.
    서버가 여러 회사를 스레드로 나눠 만들고 series() 직후 같은 스레드에서 읽으므로 스레드마다 따로 둔다 — dict 와 같은 쓰임(get · update · [k] · [k] += 1)."""

    def __init__(self):                    # 스레드가 처음 만질 때마다 불린다
        self._d = {"transient": 0, "fy_bad": [], "error": None}

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v

    def __contains__(self, k):
        return k in self._d

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)

    def __repr__(self):
        return "LAST(%r)" % (self._d,)

    def get(self, k, default=None):
        return self._d.get(k, default)

    def update(self, *args, **kw):
        self._d.update(*args, **kw)

    def keys(self):
        return self._d.keys()

    def items(self):
        return self._d.items()

    def values(self):
        return self._d.values()

    def copy(self):
        return dict(self._d)


LAST = _Last()
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


def _grab(rows, table, picks, field, meta=None):
    """원장에서 picks 의 항목을 골라 {키: 값}. meta 를 주면 고른 줄의 이름을 meta[키] 에 남긴다."""
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
                best = (score, v, nm)
        if best:
            out[key] = best[1]
            if meta is not None:
                meta[key] = best[2]
    return out


EPS_DISC_TAG = "ifrs-full_BasicEarningsLossPerShareFromDiscontinuedOperations"


def _cont_only(nm):
    """'계속영업 기본주당이익' 처럼 계속영업만 센 줄인가 — '계속영업과 중단영업 …' 은 합계 줄이다(서버 _pipe_rows 의 cont 와 같은 판정)."""
    return "계속영업" in nm and "계속영업과" not in nm


def _disc_eps(rows, field):
    """중단영업 기본주당이익 줄의 값(없으면 None) — 태그 BasicEarningsLossPerShareFromDiscontinuedOperations 이거나,
    이름에 '중단영업'이 있고 '계속영업'은 없으며 '기본 … 주당'이 든 줄. 칸마다 값이 있는 첫 줄(서버 _pipe_rows 의 disc 와 같은 규칙)."""
    for r in rows:
        if r.get("sj_div") not in ("IS", "CIS"):
            continue
        nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
        if "우선주" in nm:
            continue
        if not (FIN.norm_tag(r.get("account_id")) == EPS_DISC_TAG
                or ("중단영업" in nm and "계속영업" not in nm and re.search(r"기본.*주당|주당.*기본", nm))):
            continue
        v = FIN.num(r.get(field))
        if v is not None:
            return v
    return None


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
        meta = {}
        got = _grab(rows, ("IS", "CIS"), IS_PICK, fld, meta)
        # EPS 는 합계(계속 + 중단영업) 기준으로 — 계속영업 줄만 골랐고 중단영업 줄이 따로 있으면 더한다. 순이익(중단영업 포함)과 기준을 맞춘다
        # (카카오 2026Q2: 계속영업 EPS 431원 × 순이익 164억(중단 −1,560억 포함)이면 주식 수가 10배 줄어 '병합'으로 읽힌다 — 합계 41원)
        if got.get("EPS") is not None and _cont_only(meta.get("EPS", "")):
            dv = _disc_eps(rows, fld)
            if dv is not None:
                got["EPS"] += dv
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


def series(corp_code, stock_code, years, prices=None, meta=None, offline=False, progress=None):
    """분기 시계열 v2 — n 오름차순 조밀 격자(첫 자료 분기 ~ 끝 자료 분기, 빈 분기 포함).
    meta = {filed: {n: 원본 공시일}, fy_bad: {연도}, fin: bool}. fy_bad 연도는 받지 않고 'fy' 빈 칸으로만 낸다.
    progress(done, total) 가 있으면 분기 하나를 받을 때마다 부른다(total = 연도 수 × 4, fy_bad 연도는 네 칸을 한 번에 센다) — 서버 진행률.
    끝나면 LAST(스레드별)에 transient · fy_bad · error 를 남긴다 — transient > 0 이면 일시 오류로 빠진 분기가 있다는 뜻이다."""
    meta = meta or {}
    filed, fy_bad = meta.get("filed") or {}, set(meta.get("fy_bad") or ())
    LAST.update(transient=0, fy_bad=sorted(fy_bad), error=None)
    raw = {}
    total, done = len(years) * 4, 0
    for y in years:
        if y in fy_bad:
            done += 4
            if progress is not None:
                progress(done, total)
            continue
        for q in (1, 2, 3, 4):
            try:
                d = period_data(corp_code, y, q, offline=offline)
            except Exception as e:
                LAST["error"] = "%s: %s" % (type(e).__name__, e)
                d = {"_transient": True}
            done += 1
            if progress is not None:
                progress(done, total)
            if d and d.get("_transient"):
                LAST["transient"] += 1
                continue
            if d:
                raw[_n(y, q)] = d
    fy_ns = [_n(y, q) for y in years if y in fy_bad for q in (1, 2, 3, 4)]
    if not raw and not fy_ns:
        return []
    n0, n1 = min(list(raw) + fy_ns), max(list(raw) + fy_ns)
    pts = []
    for n in range(n0, n1 + 1):
        y, q = n // 4, n % 4 + 1
        p = {"year": y, "q": q, "label": "%dQ%d" % (y, q), "n": n, "품질": []}
        d = raw.get(n)
        if d is None:
            p["품질"].append("fy" if y in fy_bad else "gap")
            pts.append(p)
            continue
        p["fs"] = d.get("_fs")
        q3, capex_ok = {}, True
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
                # 3분기 누적이 없으면 4분기 단독은 모른다 — 연간치를 대신 넣으면 4분기 합 · 전년 대비가 연간과 분기를 섞어 부푼다(EPS 로 겪음, 2026-10-07)
                ann, cum9 = d.get(k), q3.get(k + "_누적")
                ok = same_fs and scope_ok and ann is not None and cum9 is not None
                p[k] = (ann - cum9) if ok else None
                pa_, pc_ = d.get(k + "_전연"), q3.get(k + "_전누적")
                p[k + "_전"] = (pa_ - pc_) if (ok and pa_ is not None and pc_ is not None) else None
            capex_ok = same_fs and scope_ok         # CAPEX 의 연간 − 3분기 누적도 같은 기준 · 범위일 때만
            if d.get("매출액") is not None and p.get("매출액") is None:
                # 자료가 모자라면(3분기 없음 · 누적 없음) gap, 기준(CFS/OFS) · 범위가 어긋나면 basis
                p["품질"].append("gap" if q3.get("매출액_누적") is None else "basis")
        for k in ("재고자산", "매출채권", "유형자산", "자본총계"):
            p[k] = d.get(k)
        cx = d.get("CAPEX")
        cx_prev = 0 if q == 1 else (raw.get(n - 1) or {}).get("CAPEX")      # 현금흐름표는 누적 — 분기 값은 앞 누적과의 차
        p["CAPEX"] = (cx - cx_prev) if (capex_ok and cx is not None and cx_prev is not None) else None
        f0 = filed.get(n)
        rcs = [x for x in (d.get("_rcept"), q3.get("_rcept")) if x]       # 4분기는 3분기 누적 줄도 쓴다 — 그쪽 정정도 기준일에 든다
        cand = [x for x in [f0] + rcs if x]
        p["기준일"] = max(cand) if cand else None
        if f0 and any(x > f0 for x in rcs):
            p["품질"].append("amended")
        pts.append(p)
    by = {p["n"]: p for p in pts}
    # 이상값 — 그 분기와 바로 앞 분기(지우기 전 값)만 본다. 뒤 분기는 보지 않는다
    rev0 = {p["n"]: p.get("매출액") for p in pts}
    for p in pts:
        v = p.get("매출액")
        if v is None:
            continue
        if v <= 0:
            p["매출액"] = None; p["품질"].append("neg")
        elif rev0.get(p["n"] - 1) == v:
            p["매출액"] = None; p["품질"].append("dup")
    # 전년 대비 — 공시 당시(매출YoY) · 재작성(YoY_r)
    for p in pts:
        b = by.get(p["n"] - 4) or {}
        for k, tag in (("매출액", "매출"), ("영업이익", "영업이익")):
            a, v = b.get(k), p.get(k)
            p[tag + "YoY"] = None
            if a is not None and v is not None and a > 0:
                # 기저가 거의 0이면 증감률은 의미가 없다. 적자에서 흑자로 돌면 수천 %가 찍히는데 차트도 판단도 망가진다.
                # 이익은 매출의 1% 미만 기저를 버리고, 대신 영업이익률 변화(%p)로 본다.
                if tag == "영업이익" and b.get("매출액") and a < b["매출액"] * 0.01:
                    p[tag + "YoY_무의미"] = True
                else:
                    p[tag + "YoY"] = (v - a) / abs(a) * 100
            pr = p.get(k + "_전")
            key_r = "YoY_r" if tag == "매출" else "영업이익YoY_r"
            p[key_r] = (v - pr) / abs(pr) * 100 if (v is not None and pr is not None and pr > 0) else None
        if p.get("매출액") and p.get("영업이익") is not None:
            p["영업이익률"] = p["영업이익"] / p["매출액"] * 100
            # 지주회사는 영업이익에 지분법이익이 잡히는데 매출은 지주사 자체 매출뿐이라 비율이 수천 %로 튄다. 순위에 넣으면 안 되는 값이다.
            if abs(p["영업이익률"]) > 100:
                p["이익률_비정상"] = True
    for p in pts:
        prev = by.get(p["n"] - 1) or {}
        for tag in ("매출", "영업이익"):
            a, b_ = p.get(tag + "YoY"), prev.get(tag + "YoY")
            p[tag + "가속"] = (a - b_) if (a is not None and b_ is not None) else None
        p["이익률변화"] = (p["영업이익률"] - prev["영업이익률"]) if (p.get("영업이익률") is not None and prev.get("영업이익률") is not None) else None
    # TTM · 회전일수 — 연속 네 분기(키)일 때만. 회전일수의 분모는 TTM 매출이다.
    # 단일 분기 매출로 나누면 매출이 출렁이는 회사에서 지표가 망가진다.
    # (한미반도체 2026Q1 매출 509억 -> Q2 2,512억. 재고는 그대로인데 재고일수가 309일 -> 52일로 찍힌다. 재고가 준 게 아니라 분모가 커진 것.)
    for p in pts:
        win = [by.get(m) or {} for m in range(p["n"] - 3, p["n"] + 1)]
        p["매출_TTM"] = sum(w["매출액"] for w in win) if all(w.get("매출액") for w in win) else None
        p["영업이익_TTM"] = sum(w["영업이익"] for w in win) if all(w.get("영업이익") is not None for w in win) else None
        if p["매출_TTM"] and len({w.get("fs") for w in win}) > 1:
            p["품질"].append("basis")
        daily = p["매출_TTM"] / 365.0 if p["매출_TTM"] else None
        p["재고일수"] = (p["재고자산"] / daily) if (daily and p.get("재고자산")) else None
        p["매출채권일수"] = (p["매출채권"] / daily) if (daily and p.get("매출채권")) else None
        # CAPEX 강도 = 그 분기 CAPEX ÷ 그 분기 매출 × 100 (TTM 이 아니다) — 하나라도 없으면 None
        p["CAPEX강도"] = (p["CAPEX"] / p["매출액"] * 100) if (p.get("CAPEX") is not None and p.get("매출액")) else None
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


# ---------------------------------------------------------------- 가속(B) · 국면 — 산업 업황 시계와 같은 식 · 같은 이름(2026-10-09)
PHASE_BAND = 3.0      # %p — 가속이 이 안이면 '유지'
PHASE_FLAT = 2.0      # % — 속도가 이 안이고 가속도 '유지'면 '정체'
PHASE_NAME = {(True, 1): "확장 가속", (True, 0): "확장 유지", (True, -1): "둔화",
              (False, 1): "회복", (False, 0): "부진 지속", (False, -1): "수축 심화"}


def phase_label(speed, acc):
    band = 1 if acc >= PHASE_BAND else -1 if acc <= -PHASE_BAND else 0
    if band == 0 and abs(speed) < PHASE_FLAT:
        return "정체"
    return PHASE_NAME[(speed > 0, band)]


def _turns(pts):
    """|B(n)| ≥ 띠 이고, n 앞 가장 가까운 |B| ≥ 띠 분기 m 이 반대 부호 · n − m ≤ 4 이면 ▲/▼."""
    last = None                      # (n, sign) — 가장 최근 띠 밖 분기
    for p in pts:
        b = p.get("가속B")
        p["변곡"] = None
        if b is None or abs(b) < PHASE_BAND:
            continue
        s = 1 if b > 0 else -1
        if last and last[1] != s and p["n"] - last[0] <= 4:
            p["변곡"] = "▲" if s > 0 else "▼"
        last = (p["n"], s)
    return pts


def accel(pts, basis="매출"):
    by = {p["n"]: p for p in pts}
    for p in pts:
        p.setdefault("품질", [])
        if basis == "영업이익":
            hist = [abs(by[m]["영업이익"]) for m in range(p["n"] - 4, p["n"]) if m in by and by[m].get("영업이익") is not None]
            base = (by.get(p["n"] - 4) or {}).get("영업이익")
            ok = base is not None and base > 0 and hist and base >= 0.2 * (sum(hist) / len(hist))
            r, a = (p.get("영업이익YoY_r"), p.get("영업이익YoY")) if ok else (None, None)
        else:
            r, a = p.get("YoY_r"), p.get("매출YoY")
        p["Y_asfiled"] = a
        if r is not None:
            p["Y"] = r
        else:
            p["Y"] = a
            if a is not None:
                p["품질"].append("asfiled")
    for p in pts:
        n = p["n"]
        w = [by.get(m) for m in range(n - 3, n + 1)]
        p["속도"] = p["가속B"] = p["C"] = p["국면"] = p["B기준일"] = None
        p["엇갈림"] = False
        if all(x is not None for x in w) and all(x.get("Y") is not None for x in w):
            ys = [x["Y"] for x in w]
            kinds = {"asfiled" in x["품질"] for x in w}
            if len(kinds) > 1:
                alt = [x.get("Y_asfiled") for x in w]
                if all(v is not None for v in alt):
                    ys = alt
                    p["품질"].append("mix")
                else:
                    ys = None
            if ys:
                s, s2 = (ys[3] + ys[2]) / 2, (ys[1] + ys[0]) / 2
                p["속도"], p["가속B"] = s, s - s2
                p["국면"] = phase_label(s, s - s2)
                dates = [x.get("기준일") for x in w if x.get("기준일")]
                p["B기준일"] = max(dates) if dates else None
        prev = by.get(n - 1)
        if prev and p.get("Y") is not None and prev.get("Y") is not None:
            p["C"] = p["Y"] - prev["Y"]
        b, c = p.get("가속B"), p.get("C")
        p["엇갈림"] = bool(b is not None and c is not None and abs(b) >= PHASE_BAND and abs(c) >= 5 and (b > 0) != (c > 0))
    _turns(pts)
    for p in pts:
        p["품질"] = sorted(set(p["품질"]))
    return pts



# ---------------------------------------------------------------- 분기 주식 수 · 분할 보정 EPS
# 분기별 주식 수(지배순이익 ÷ EPS)를 거꾸로 구해, 한 분기에 1.8배 넘게 뛰거나 0.56배 밑으로 줄면 분할 · 병합으로 보고
# 그 전 분기를 지금 주식 수 기준으로 맞춘다(LS일렉트릭 2026.2분기 5:1 — 주가 자료는 이미 지금 기준이라 EPS 만 옛 기준으로 남아 PER 이 5배 작게 나왔다).
# 서버 _pipe_rows 와 가속도(per_share)가 같이 쓴다.
import datetime as _dt
SHEV_ADJ = re.compile(r"무상증자결정|유무상증자결정|주식분할결정|주식병합결정|감자결정")     # 주가 자료(수정주가)도 같이 보정되는 사건
SHEV_MIX = re.compile(r"회사합병결정|유상증자결정|주식교환|분할합병")                      # 주가 보정 없이 주식 수만 바뀌는 사건


def _qn(k):
    """분기 이름 → 연도×4 + 분기. 5번째 글자가 분기 숫자인 이름이면 된다('2026Q2' · '2026.2Q' 둘 다)."""
    return int(k[:4]) * 4 + int(k[5])


def _qend(lab):
    return int("%s%s" % (lab[:4], {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[int(lab[5])]))


def share_basis(sh, sev, cnt=None):
    """분기별 역산 주식 수 {label: 주식 수} → 지금 기준 주식 수. 서버 _pipe_rows 와 가속도가 같이 쓴다.
    sev = 그 회사의 주식 수 사건 공시 [(YYYYMMDD, 제목)], cnt(label) = 그 분기 보고서 개요의 분할 · 병합 · 무상증자 낱말 수(없으면 None — 정수 비율만 본다).
    {"now": {label: 지금 기준 주식 수}, "splits": [{after, at, ratio, kind}], "cut": 이 분기(_qn) 앞 기록은 지금 기준으로 맞출 수 없음 | None}"""
    sh = dict(sh)
    ks = sorted(sh, key=_qn)
    # 한 분기만 튀었다 바로 돌아온 값(HD현대일렉트릭 2018.4분기 21배 → 다음 분기 0.09배)은 자료 오류 — 버린다
    for i in range(1, len(ks) - 1):
        a_, b_, c_ = sh.get(ks[i - 1]), sh.get(ks[i]), sh.get(ks[i + 1])
        if a_ and b_ and c_ and not (0.56 < b_ / a_ < 1.8) and 0.8 <= c_ / a_ <= 1.25:
            sh.pop(ks[i], None)
    ks = [k for k in ks if k in sh]

    def events_between(after, at):
        """after 분기 말 90일 전 ~ at 분기 말 사이의 주식 수 사건 공시 — (주가 보정 사건, 주가 보정 없는 사건)"""
        lo = int((_dt.datetime.strptime(str(_qend(after)), "%Y%m%d") - _dt.timedelta(days=90)).strftime("%Y%m%d"))
        hi = _qend(at)
        ev = [nm for d_, nm in (sev or []) if d_ and lo <= int(d_) <= hi]
        return [x for x in ev if SHEV_ADJ.search(x)], [x for x in ev if SHEV_MIX.search(x)]

    def split_like(after, at, r_):
        """주식 수가 크게 바뀐 게 분할 · 병합 · 무상증자(주가 자료도 같이 보정됨)인가, 유상증자(주가는 그대로)인가.
        먼저 공시 목록(무상증자 · 주식분할 · 병합 · 감자 결정)으로 정하고(2026-10-05 — 1:1 · 1:2 무상증자 · 16:1 감자를 '증자 등'으로 잘못 보던 것),
        공시가 없을 때만 회사의 개요(자본금 변동 표) 낱말 · 정수 비율로 본다."""
        adj_, _mix = events_between(after, at)
        if adj_:
            return True
        if cnt is not None:
            a_n, b_n = cnt(after), cnt(at)
            if a_n is not None and b_n is not None and b_n > a_n:
                return True
        k = r_ if r_ >= 1 else 1 / r_
        return k >= 4.5 and abs(k - round(k)) <= 0.15
    fac = {k: 1.0 for k in ks}             # 이 분기 뒤에 일어난 분할 비율의 곱
    splits = []
    cut = None                              # 분할과 합병 신주가 겹친 곳 — 그 앞 PER 기록은 지금 기준으로 맞출 수 없어 자기 역사에서 뺀다
    for a, b in zip(ks, ks[1:]):
        r_ = sh[b] / sh[a]
        adj_, mix_ = events_between(a, b) if (r_ >= 1.25 or r_ <= 0.8) else ([], [])
        # 공시로 확인된 분할 · 무상증자는 1.25배(0.8배)부터 — 1:0.5 무상증자(헥토) · 두 분기에 걸친 100% 무상증자(노바렉스)
        if (r_ >= 1.8 or r_ <= 0.56) or adj_:
            kk = r_ if r_ >= 1 else 1 / r_
            if adj_:
                kind = "분할·병합"
                if mix_ and abs(kk - round(kk)) > 0.15:
                    # 분할 · 감자와 합병 신주 · 유상증자가 한 창에 겹쳤다(동원산업 5:1 분할 + 합병 = 10.6배, 미래산업 16:1 감자 + 증자) —
                    # 전체 비율로 보정하되, 그 앞 PER 기록은 정확히 맞출 수 없어 자기 역사에서 뺀다
                    kind = "분할·병합(증자 섞임 — 앞 기록 제외)"
                    cut = _qn(a) if cut is None else max(cut, _qn(a))
            else:
                kind = "분할·병합" if split_like(a, b, r_) else "증자 등(주가 보정 없음)"
            splits.append({"after": a, "at": b, "ratio": round(r_, 2), "kind": kind})
            if kind.startswith("분할·병합"):
                for k in ks:
                    if _qn(k) <= _qn(a):
                        fac[k] *= r_
    return {"now": {k: sh[k] * fac[k] for k in ks}, "splits": splits, "cut": cut}


def per_share(pts, sev, cnt=None):
    """분기 주식 수(지배순이익 ÷ EPS) → 지금 기준 EPS_adj · EPS_TTM(보정).
    EPS_TTM_raw = 네 분기 EPS 의 단순 합 — 분할 · 병합 보정은 안 한 합(전 · 후 기준이 섞임)이다. 공시 원값의 합이 아니라 아래 단위 보정을 거친 EPS 의 합이다
    (단위 오류를 고친 분기는 p["EPS"] 를 바로 고쳐 쓰고, 못 고친 분기는 EPS 를 그대로 둔다).
    EPS 가 원 대신 천 · 백만 원 단위로 적힌 분기는 EPS 를 고쳐 쓰고 품질에 'unit' 을 단다. 못 고치는 이상값은 주식 수 열에서 빼고(이웃 분기 주식 수로 EPS_adj) 'unit' 만 단다.
    분할과 합병 신주가 한 창에 겹쳐 지금 기준으로 맞출 수 없는 구간(share_basis 의 cut)은 그 분기까지 모두 품질 'cut' — 자기 역사 PER 에서 뺄 표시다.
    attach_prices 가 PER_TTM 을 EPS_TTM(보정)으로 계산하므로 순서는 series → per_share → accel → attach_prices."""
    by = {p["n"]: p for p in pts}
    imp = {}
    for p in pts:
        ni, e = p.get("지배순이익") if p.get("지배순이익") is not None else p.get("당기순이익"), p.get("EPS")
        if ni and e and p.get("매출액") and abs(ni) >= abs(p["매출액"]) * 0.005 and ni / e > 0:
            imp[p["label"]] = ni / e
    if imp:
        med = sorted(imp.values())[len(imp) // 2]
        for lab, s in list(imp.items()):
            if s < med / 300 or s > med * 300:
                p = next(x for x in pts if x["label"] == lab)
                for div in (1e3, 1e6):
                    if med / 1.8 <= s * div <= med * 1.8:
                        p["EPS"] = p["EPS"] / div
                        imp[lab] = s * div
                        break
                else:
                    imp.pop(lab)
                p["품질"] = sorted(set(p.get("품질", []) + ["unit"]))
    sb = share_basis(imp, sev, cnt) if imp else {"now": {}, "cut": None}
    now, cut = sb["now"], sb["cut"]
    for p in pts:
        if cut is not None and p["year"] * 4 + p["q"] <= cut:      # _qn 과 같은 척도 — cut 분기(포함) 앞 기록은 지금 기준으로 못 맞춘다
            p["품질"] = sorted(set(p.get("품질", []) + ["cut"]))
        ni = p.get("지배순이익") if p.get("지배순이익") is not None else p.get("당기순이익")
        s = now.get(p["label"])
        if s is None and now:
            qk = p["year"] * 4 + p["q"]                       # _qn 과 같은 척도(연도×4 + 분기)
            near = min(now, key=lambda k: abs(_qn(k) - qk))
            s = now[near] if abs(_qn(near) - qk) <= 4 else None
        p["주식수"] = s
        p["EPS_adj"] = (ni / s) if (ni is not None and s) else None
    for p in pts:
        w = [by.get(m) or {} for m in range(p["n"] - 3, p["n"] + 1)]
        p["EPS_TTM_raw"] = sum(x["EPS"] for x in w) if all(x.get("EPS") is not None for x in w) else None
        p["EPS_TTM"] = sum(x["EPS_adj"] for x in w) if all(x.get("EPS_adj") is not None for x in w) else None
    return pts


# ---------------------------------------------------------------- 지금 PER
NOW_K_LO, NOW_K_HI = 0.55, 1.8     # k 가 이 사이 밖이면 캐시 뒤 분할 · 병합으로 주가 자료가 다시 보정된 것 — 지금 PER 을 믿지 않는다(stale)
NOW_PCT_WIN, NOW_PCT_MIN = 40, 8   # 백분위 창 — 'cut' 아닌 양수 PER_TTM 의 마지막 40개, 8개 이상(서버 저평가 per_pct 의 hist_per[-40:] 와 같다)


def split_after(pts, sev):
    """마지막 자료 분기(원장이 있는 분기 — 끝의 빈 gap · fy 칸은 뺀다) 말 뒤에 난 주가 보정 사건(SHEV_ADJ: 분할 · 병합 · 무상증자 · 감자)
    공시 [{date, title}]. 그 분기 EPS 는 사건 전 주식 수 기준인데 주가 자료는 사건 뒤 기준으로 다시 보정돼 PER 이 비율만큼 틀린다 —
    공시 제목으로는 비율을 정확히 못 읽어 지금은 표시만 한다(now_per 의 stale). 정확한 보정은 계획 2(KIS 원 · 수정 주가 비)."""
    last = max((p["n"] for p in pts if p.get("fs")), default=None)
    if last is None:
        return []
    end = _qend("%dQ%d" % (last // 4, last % 4 + 1))
    return [{"date": str(d_), "title": nm} for d_, nm in (sev or [])
            if d_ and str(d_).isdigit() and int(d_) > end and SHEV_ADJ.search(nm or "")]


def now_per(points, prices, splits=None):
    """지금 PER(캐시하지 않는다) — 서버 _druck_now 가 지금 받은 수정주가 {YYYYMMDD: 종가} 로 부른다.
    per = 마지막 종가 ÷ (최신 EPS_TTM ÷ k). k = 캐시에 적힌 공시일 주가 ÷ 지금 받은 수정주가의 같은 날 종가 —
    EPS_TTM · 주가 · 주가일이 다 있는(그리고 그날 종가가 지금 자료에 있는) 마지막 분기로 잰다. 캐시 뒤 분할로 주가 자료가 다시 보정되면 ≠ 1.
    pct = 지금 PER 이하 비율 — 'cut' 아닌 양수 PER_TTM 의 마지막 40개, 8개 이상일 때만.
    stale = k 가 0.55~1.8 밖(경계 포함)이거나 splits(split_after() — 마지막 자료 분기 뒤 분할 · 병합 공시)가 있을 때."""
    eps_pts = [p for p in points if p.get("EPS_TTM")]
    if not eps_pts or not prices:
        return None
    last = eps_pts[-1]
    ds = sorted(prices)
    px, date = prices[ds[-1]], ds[-1]
    kp = next((p for p in reversed(points)
               if p.get("EPS_TTM") and p.get("주가") and p.get("주가일") and prices.get(p["주가일"])), None)
    k = kp["주가"] / prices[kp["주가일"]] if kp else 1.0
    eps = last["EPS_TTM"] / k
    per = px / eps if eps > 0 else None
    hist = [p["PER_TTM"] for p in points if (p.get("PER_TTM") or 0) > 0 and "cut" not in (p.get("품질") or [])][-NOW_PCT_WIN:]
    pct = (sum(1 for v in hist if v <= per) / len(hist) * 100) if per and len(hist) >= NOW_PCT_MIN else None
    sa = list(splits or [])
    return {"px": px, "date": date, "per": per, "k": round(k, 3), "pct": pct,
            "stale": bool(sa) or not (NOW_K_LO < k < NOW_K_HI), "split_after": sa}
