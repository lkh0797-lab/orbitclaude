# -*- coding: utf-8 -*-
"""
산업 성장률 — 섹터별 매출 · 이익 · 생산 · 수출 · 가격 · 시장규모 · 시가총액 · 전망을 한 표로 (2026-10-06)

"산업의 성장률을 추적하는 것 자체가 그 산업을 이해하는 핵심이다." 섹터(산업_섹터.SECTORS)마다 이미 모아 둔 자료를 합친다.

  상장사 실적   .cache/산업/panel.json (산업_패널.py — DART 원장, 분기 단독) + 부문.json (산업_부문.py — 섞인 회사의 부문)
                회사 기여 = 부문 회사는 섹터에 맞는 부문만, 나머지는 '연결 − 연결하는 상장 자회사'(잔여). 그래서 두 번 세지 않는다.
                증가율은 '같은 회사 · 같은 구조' 표본으로 잰다 — 두 기간 모두 숫자가 있고, 그 해의 자회사 구조를 두 기간에 똑같이 적용하고,
                첫 해(분할 · 설립으로 12개월이 안 되는 해) · 연결/별도가 바뀐 해는 뺀다. 수준(조 원)과 증가율의 표본이 다를 수 있다.
  생산 · 가격   .cache/산업/통계.json (산업_통계.py — KOSIS 광공업생산 · 가동률 · 품목 생산, ECOS 수출물가 · 물량 · BSI · 부가가치)
  수출          같은 파일의 관세청 품목(HS)별 전국 월별 수출(달러)
  시장 규모 · 전망  산업_외부자료.json — 세계 시장 · 한국 점유율 · 기관 전망(WSTS · KIET 등), 숫자마다 출처 · 날짜, 이 세션에서 원문 확인한 것만
  시가총액      종목.txt 시총 스냅샷 × 그 뒤 주가 변화(.cache/price). 자회사 지분 가치는 모회사 시총에서 뺀다(지분율 × 자회사 시총).
                부문 회사(삼성전자 등)는 최근 4분기 부문 영업이익(플러스만) 비중으로 시총을 나눈다 — 근사.
  컨센서스      .cache/consensus(네이버, 화면을 열 때 쌓인 것만 — 새로 부르지 않는다). 개인 열람용.

결과: .cache/산업/_result.json — 서버 industry_view 가 읽는다. 실행: python 산업.py
"""
import datetime as dt
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import 산업_섹터 as SEC  # noqa: E402

CACHE = os.path.join(BASE, ".cache")
DIR = os.path.join(CACHE, "산업")
OUT = os.path.join(DIR, "_result.json")
EXT_PATH = os.path.join(BASE, "산업_외부자료.json")
V = 2          # 2: 하위탭 — members_all(섹터 안 전 종목 업황) · exports.q/fit(수출 분기) · backlog.rows (2026-10-08)
FIRST_Y = 2015


def _load(p, d=None):
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return d


def _qs(a, b):
    """'2016Q1' ~ '2026Q2' 분기 목록."""
    y, q = int(a[:4]), int(a[5])
    out = []
    while True:
        k = "%dQ%d" % (y, q)
        out.append(k)
        if k == b:
            return out
        q += 1
        if q > 4:
            y, q = y + 1, 1


def _qprev(k, n=4):
    y, q = int(k[:4]), int(k[5]) - n
    while q <= 0:
        y, q = y - 1, q + 4
    return "%dQ%d" % (y, q)


def _yoy(a, b):
    if a is None or b is None or b <= 0:
        return None
    return (a / b - 1) * 100


def _r1(v, d=1):
    return None if v is None else round(v, d)


def _gb(it):
    """외부 숫자의 증감 기준 — 'cagr'(연평균) · 'real'(실질) · 'yoy'(전년 대비). 화면 표시에 쓴다."""
    t = "%s %s %s" % (it.get("metric") or "", it.get("note") or "", it.get("unit") or "")
    b = "cagr" if re.search(r"연평균|CAGR", t, re.I) else "real" if "실질" in t else "yoy"
    return dict(it, g_basis=b)


# 섹터마다 화면에 붙일 주의(연도별 수준이 구조 변화로 튀는 곳 등)
SECTOR_NOTES = {
    "조선": ["2015~2016 수준에는 분할 전 현대중공업의 정유 · 전기 · 건설기계 매출이 섞여 있다(2017-04 분할 — 증가율 표본에서는 2017 · 2018 을 뺐다)."],
    "전력기기": ["2015~2020 두산에너빌리티 잔여에 두산인프라코어 · 두산건설(비상장 · 상장폐지라 못 뺐다)이 섞여 수준이 크다 — 2021 · 2022 증가율 표본에서는 뺐다."],
    "반도체": ["삼성전자 DS 부문 매출은 부문 간 내부거래(DX 로 파는 메모리)를 포함한다 — 회사가 부문 외부매출을 공개하지 않는다.",
             "시가총액은 보통주만(우선주 제외) — 삼성전자 우선주가 빠져 실제보다 작다."],
    "자동차·부품": ["현대차는 차량 부문만(금융 부문 제외). 기아 → 현대모비스(18%)처럼 5% 넘는 상장사 지분은 시총에서 뺐다."],
    "방산·항공우주": ["풍산은 방산 부문만, 현대로템은 디펜스 부문만 넣었다. 풍산 부문 이익은 세전이익이다(부문 영업이익을 공시하지 않는다)."],
    "해운": ["현대글로비스 해운 부문은 2018년부터만 있다(그 전에는 물류 부문 안) — 2018 이전 수준에는 없다."],
    "건설": ["삼성물산은 건설 부문만 넣었다(2015 제일모직 합병으로 2015 · 2016 증가율 표본에서는 뺐다)."],
    "통신": ["KT 는 통신(ICT) 부문만(BC카드 금융 · 부동산 제외). KT 부문 매출은 부문 간 거래를 포함한다."],
}


# KOSIS 업종 지수를 두 섹터가 같이 쓰거나 섹터보다 넓은 곳 — 신호 설명에 붙인다
KOSIS_SHARED = {"C262": " — 전자부품 전체(디스플레이 포함) 지수라 디스플레이 · 전자부품 섹터가 같은 값을 쓴다",
                "C204": " — 기타 화학제품 전체(도료 · 접착제 등 포함, 화장품은 그 일부)",
                "C252": " — 무기 · 총포탄(2020년부터)"}


def _full_year(it):
    """외부 숫자가 한 해 전체인가('2025' — '2026 H1' · '2Q26' · '2026-09' 는 아니다)."""
    return bool(re.fullmatch(r"\d{4}", str(it.get("year") or "").strip()))


# ---------------------------------------------------------------- 회사 기여(부문 · 잔여)
class Panel:
    def __init__(self, panel, seg):
        self.co = panel.get("companies") or {}
        self.edges = {y: [tuple(e) for e in v] for y, v in (panel.get("edges") or {}).items()}
        self.hold = panel.get("holdings") or {}
        self.seg = (seg or {}).get("companies") or {}
        self._cc = {}
        self._kids = {}
        self._per = {}
        self.notes = []

    def kids(self, code, sy):
        k = (code, sy)
        if k not in self._kids:
            self._kids[k] = sorted(c for p, c in self.edges.get(str(sy), []) if p == code)
        return self._kids[k]

    def stake(self, p, c):
        h = self.hold.get("%s>%s" % (p, c)) or {}
        s = h.get("stake")
        return s / 100.0 if isinstance(s, (int, float)) and 0 < s <= 100 else 0.6

    def per(self, code, p):
        """회사 기간 숫자. 12월 결산이 아닌 회사(분기 이름이 회계연도 기준)는 넣지 않는다.
        분기 매출이 그해 연간 ÷ 4 의 3배를 넘으면 단위 오류로 보고 버린다."""
        k = (code, p)
        if k in self._per:
            return self._per[k]
        co = self.co.get(code) or {}
        v = None
        if (co.get("fy_end_month") or 12) == 12:
            v = (co.get("q" if "Q" in p else "y") or {}).get(p)
            if v and "Q" in p and v.get("rev") is not None:
                ann = ((co.get("y") or {}).get(p[:4]) or {}).get("rev")
                if ann and ann > 0 and abs(v["rev"]) > 3 * ann / 4:
                    v = None
        self._per[k] = v
        return v

    def partial(self, code, p):
        return int(p[:4]) in set((self.co.get(code) or {}).get("partial_years") or [])

    @staticmethod
    def seg_sector(code, name, year):
        nm = re.sub(r"\s+", "", name or "")
        for rx, sec, since, until in SEC.SEGMENTS.get(code, []):
            if (since is None or year >= since) and (until is None or year <= until) and re.search(rx, nm):
                return sec
        return "skip"

    def _seg_year(self, code, y):
        s = self.seg.get(code) or {}
        return bool(((s.get("y") or {}).get(y) or {}).get("segments")) or \
            any(((s.get("q") or {}).get("%sQ%d" % (y, k)) or {}).get("segments") for k in (1, 2, 3, 4))

    def segs(self, code, p):
        return ((((self.seg.get(code) or {}).get("q" if "Q" in p else "y") or {}).get(p)) or {}).get("segments") or []

    def _residual(self, code, p, sec):
        per = self.per(code, p)
        if not per or per.get("rev") is None:
            return None, ()
        rev, op, ni = per["rev"], per.get("op"), per.get("ni_own")
        kk = []
        for c in self.kids(code, int(p[:4])):
            cp = self.per(c, p)
            if cp and cp.get("rev") is not None:
                kk.append(c)
                rev -= cp["rev"]
                if op is not None:
                    op -= cp.get("op") or 0
                if ni is not None:
                    ni -= self.stake(code, c) * (cp.get("ni_own") or 0)
        return ({sec: [rev, op, ni]} if rev > 0 else None), tuple(kk)

    def contrib(self, code, p, sy):
        """기간 p 의 섹터별 기여 {섹터: [매출, 영업이익, 지배순이익]}와 방식.
        잔여 회사는 그 기간 해의 연결 구조(edges[p 의 해])로 상장 자회사를 뺀다 — 인수 전 분기에서 나중에 산 자회사를 빼지 않게.
        부문 회사는 구조 연도 sy 의 부문 → 섹터 규칙을 쓰고(두 기간을 같은 규칙으로 견주려고), 부문 안의 상장 자회사(SEG_CHILD_IN)를 뺀다.
        부문 회사의 순이익은 부문으로 나누지 않는다(None) — 그룹 손실 · 영업외 손익이 엉뚱한 부문에 붙기 때문.
        부문 자료가 없는 기간은 SEG_FALLBACK 회사만 회사 전체를 대표 섹터에 넣는다."""
        key = (code, p, sy)
        if key in self._cc:
            return self._cc[key]
        out, mode = None, None
        if code in SEC.SEGMENTS:
            segs = self.segs(code, p)
            if segs:
                out = {}
                for s in segs:
                    sec = self.seg_sector(code, s.get("name"), sy)
                    if sec == "skip" or s.get("rev") is None:
                        continue
                    a = out.setdefault(sec, [0.0, 0.0, None])
                    a[0] += s["rev"]
                    if a[1] is not None:
                        a[1] = None if s.get("op") is None else a[1] + s["op"]     # 부문 영업이익 미공시(SKC 2024~)면 비운다
                q4 = p if "Q" in p else p + "Q4"
                for ch, sec, a0, a1 in SEC.SEG_CHILD_IN.get(code, []):
                    if sec in out and (a0 is None or q4 >= a0) and (a1 is None or q4 <= a1):
                        cp = self.per(ch, p)
                        if cp and cp.get("rev") is not None:
                            out[sec][0] -= cp["rev"]
                            if out[sec][1] is not None:
                                out[sec][1] -= cp.get("op") or 0
                out = {k: v for k, v in out.items() if v[0] > 0} or None
                mode = ("seg",)
            elif code in SEC.SEG_FALLBACK and not self._seg_year(code, p[:4]):
                # 부문 자료가 아예 없는 해(부문 공시 전)만 회사 전체 — 한 분기만 빠진 해(KT 2019Q4 등)는 비운다
                sec = SEC.OVERRIDE[code][0]
                out, kk = self._residual(code, p, sec)
                mode = ("whole",) + kk
        else:
            sec, _ = SEC.sector_of(code, (self.co.get(code) or {}).get("ksic"))
            if sec != "제외":
                out, kk = self._residual(code, p, sec)
                mode = ("res",) + kk
        self._cc[key] = (out, mode)
        return out, mode

    def comparable(self, code, p, b, sec):
        """두 기간의 기여가 같은 사업인가.
        - 부문 회사: 두 기간 모두 부문(또는 모두 회사 전체)으로 잡혀야 한다.
        - 잔여 회사: 그 해 연결 자회사 가운데 한 기간에만 숫자가 있는 회사가 있으면 아니다(분할 · 신규 상장 · 흡수합병한 해).
          두 기간 모두 숫자가 있는 자회사인데 연결 목록만 바뀐 경우(인수 · 처분 · 목록을 못 읽은 해)는 잔여가 0.6 ~ 1.67배 안일 때만 같다고 본다."""
        cp, mp = self.contrib(code, p, int(p[:4]))
        cb, mb = self.contrib(code, b, int(p[:4]))
        if not mp or not mb or mp[0] != mb[0]:
            return False
        if mp[0] == "seg":
            return True
        kp, kb = set(self.kids(code, int(p[:4]))), set(self.kids(code, int(b[:4])))
        for c in kp | kb:
            hp = bool((self.per(c, p) or {}).get("rev") is not None)
            hb = bool((self.per(c, b) or {}).get("rev") is not None)
            if hp != hb:
                return False
        if kp != kb:
            a = (cp or {}).get(sec, [None])[0]
            z = (cb or {}).get(sec, [None])[0]
            if not a or not z or not (0.6 <= a / z <= 1.67):
                return False
        return True

    def src(self, code, p):
        """연결(CFS · 본문 = 보고서 본문의 연결 표) / 별도(OFS) — 기준이 바뀐 해는 증가율에서 뺀다."""
        s = (self.per(code, p) or {}).get("src") or ""
        return "별도" if s.startswith("OFS") else "연결" if s else ""

    @staticmethod
    def skip_growth(code, p, b, sec):
        """GROWTH_SKIP — 견주는 두 기간 가운데 하나라도 그해면 뺀다(섹터가 적혀 있으면 그 섹터만)."""
        g = SEC.GROWTH_SKIP.get(code)
        if not g:
            return False
        if len(g) > 2 and g[2] and g[2] != sec:
            return False
        return int(p[:4]) in g[0] or int(b[:4]) in g[0]


def _members(P):
    """섹터 → 기여할 수 있는 종목코드들."""
    m = {k: set() for k in SEC.SECTOR_KEYS}
    for code, co in P.co.items():
        if code in SEC.SEGMENTS:
            for _, sec, _, _ in SEC.SEGMENTS[code]:
                if sec in m:
                    m[sec].add(code)
        else:
            sec, _ = SEC.sector_of(code, co.get("ksic"))
            if sec in m:
                m[sec].add(code)
    return m


def _level(P, codes, sec, p):
    """기간 p 수준 — 그 기간 구조로 기여가 있는 회사 모두. 순이익은 부문 회사를 뺀 합(부문으로 못 나눈다)."""
    sy = int(p[:4])
    r = o = n_ = 0.0
    no_op = False
    n = 0
    for c in codes:
        out, _ = P.contrib(c, p, sy)
        if out and sec in out:
            a = out[sec]
            r += a[0]
            if a[1] is None:
                no_op = True
            else:
                o += a[1]
            n_ += a[2] or 0
            n += 1
    return (r, None if no_op and not o else o, n_, n) if n else (None, None, None, 0)


def _growth(P, codes, sec, ps, bs):
    """같은 회사 · 같은 구조 증가율. ps / bs = 기간 목록(TTM 은 4개씩). 부문 규칙의 구조 연도 = ps[0] 의 해."""
    sy = int(ps[0][:4])
    rp = rb = op_ = ob = 0.0
    n = 0
    for c in codes:
        ok = True
        ap = [0.0, 0.0]
        ab = [0.0, 0.0]
        for p, b in zip(ps, bs):
            cp, _ = P.contrib(c, p, sy)
            cb, _ = P.contrib(c, b, sy)
            if not cp or not cb or sec not in cp or sec not in cb or not P.comparable(c, p, b, sec):
                ok = False
                break
            if P.partial(c, p) or P.partial(c, b) or P.skip_growth(c, p, b, sec) or \
                    (c not in SEC.SEGMENTS and P.src(c, p) != P.src(c, b)):
                ok = False
                break
            if cp[sec][1] is None or cb[sec][1] is None:
                ok = False
                break
            ap[0] += cp[sec][0]
            ap[1] += cp[sec][1]
            ab[0] += cb[sec][0]
            ab[1] += cb[sec][1]
        if not ok:
            continue
        rp += ap[0]
        rb += ab[0]
        op_ += ap[1]
        ob += ab[1]
        n += 1
    if not n:
        return None
    return {"rev_g": _yoy(rp, rb), "op_g": _yoy(op_, ob) if ob > 0 and op_ > 0 else None,
            "op_turn": ("흑자 전환" if ob <= 0 < op_ else "적자 전환" if op_ <= 0 < ob else
                        ("적자 축소" if op_ > ob else "적자 확대") if op_ <= 0 and ob <= 0 else None),
            "n": n, "rev_same": rp, "rev_base": rb, "opm_p": op_ / rp * 100 if rp else None, "opm_b": ob / rb * 100 if rb else None}


# ---------------------------------------------------------------- 시세 · 시총
def _prices(code):
    d = _load(os.path.join(CACHE, "price", code + ".json")) or {}
    ks = sorted(d)
    if not ks:
        return [], []
    vs = [float(d[k]) for k in ks]
    # 하루 ±30% 가 상한 — 그보다 큰 점프는 분할 · 병합으로 보고 앞쪽을 맞춘다
    f = 1.0
    adj = [0.0] * len(vs)
    adj[-1] = vs[-1]
    for i in range(len(vs) - 2, -1, -1):
        r = vs[i + 1] / vs[i] if vs[i] else 1
        if r > 1.45 or r < 0.55:
            f *= r
        adj[i] = vs[i] * f
    return ks, adj


def _px_at(ks, vs, ymd):
    lo, hi = 0, len(ks) - 1
    if not ks or ks[0] > ymd:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ks[mid] <= ymd:
            lo = mid
        else:
            hi = mid - 1
    return vs[lo]


def _universe():
    rows, snap = {}, None
    p = os.path.join(BASE, "종목.txt")
    for ln in open(p, encoding="utf-8", errors="replace"):
        m = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", ln)
        if ln.startswith("#") and m and not snap:
            snap = "".join(m.groups())
        m = re.match(r"^([0-9][0-9A-Z]{5})\s*#\s*(\d+)위\s+(.*?)\s+\((KOSPI|KOSDAQ),\s*시총\s*([\d,]+)억\)", ln)
        if m:
            rows[m.group(1)] = {"rank": int(m.group(2)), "name": m.group(3), "market": m.group(4),
                                "cap": float(m.group(5).replace(",", "")) * 1e8}
    return rows, snap


def _caps(univ, snap):
    """{code: {cap, px_date, ret1y}} — 스냅샷 시총 × (지금 주가 ÷ 스냅샷 날 주가), 분할 보정 주가."""
    out = {}
    for code, u in univ.items():
        ks, vs = _prices(code)
        if not ks:
            out[code] = {"cap": u["cap"], "px_date": None, "ret1y": None}
            continue
        p0 = _px_at(ks, vs, snap) if snap else None
        now = vs[-1]
        cap = u["cap"] * now / p0 if p0 else u["cap"]
        d1 = (dt.datetime.strptime(ks[-1], "%Y%m%d") - dt.timedelta(days=365)).strftime("%Y%m%d")
        p1 = _px_at(ks, vs, d1)
        out[code] = {"cap": cap, "px_date": ks[-1], "ret1y": (now / p1 - 1) * 100 if p1 and ks[0] <= d1 else None}
    return out


# ---------------------------------------------------------------- 월별 · 분기 통계
def _mkeys(series):
    return sorted(k for k, v in (series or {}).items() if v is not None)


def _mshift(k, d):
    y, m = int(k[:4]), int(k[4:]) - d
    while m <= 0:
        y, m = y - 1, m + 12
    return "%d%02d" % (y, m)


def _m3_yoy(series, last=None, avg=True):
    """최근 3개월(평균 또는 합)의 전년 같은 3개월 대비 %."""
    ks = _mkeys(series)
    if not ks:
        return None, None
    last = last or ks[-1]
    a = [series.get(_mshift(last, i)) for i in range(3)]
    b = [series.get(_mshift(last, i + 12)) for i in range(3)]
    if any(v is None for v in a + b):
        return None, last
    return _yoy(sum(a), sum(b)), last


def _year_agg(series, y, how="avg", upto=None):
    vs = []
    for m in range(1, 13):
        k = "%d%02d" % (y, m)
        if upto and k > upto:
            break
        if series.get(k) is None:
            return None
        vs.append(series[k])
    if not vs:
        return None
    return sum(vs) / len(vs) if how == "avg" else sum(vs)


def _sum_series(lst):
    out = {}
    for s in lst:
        for k, v in (s or {}).items():
            if v is not None:
                out[k] = out.get(k, 0) + v
    return out


def _q_of_month(k):
    return "%sQ%d" % (k[:4], (int(k[4:]) - 1) // 3 + 1)


# ---------------------------------------------------------------- 수출 분기 ↔ 섹터 매출(하위탭 '수출 먼저')
def _rank(v):
    s = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    for k, i in enumerate(s):
        r[i] = k + 1.0
    return r


def _spear(a, b):
    if len(a) < 6:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    sa = sum((x - ma) ** 2 for x in ra) ** 0.5
    sb = sum((x - mb) ** 2 for x in rb) ** 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (sa * sb) if sa and sb else None


def _q_months(q):
    y, k = int(q[:4]), int(q[5])
    return ["%d%02d" % (y, (k - 1) * 3 + m) for m in (1, 2, 3)]


def _exports_q(exp_series, qrows, latest_q, since):
    """{q: [{q, g, m}], now_q: {q, months, g}, fit: {...}} — 분기 수출 전년 대비(석 달 합), 다음 분기(나온 달만),
    그리고 수출(t) ↔ 섹터 매출 증가율(t) 의 순위상관 · 방향 적중(앞 분기 대비 오르내림이 같은가) · 직선 추정."""
    ks = set(_mkeys(exp_series))
    out = []
    for r in qrows:
        ms = _q_months(r["q"])
        if not all(m in ks for m in ms) or not all(_mshift(m, 12) in ks for m in ms) or not since(_mshift(ms[0], 12)):
            out.append({"q": r["q"], "g": None, "m": 0})
            continue
        a = sum(exp_series[m] for m in ms)
        b = sum(exp_series.get(_mshift(m, 12), 0) for m in ms)
        out.append({"q": r["q"], "g": _r1(_yoy(a, b)), "m": 3})
    nq = "%dQ1" % (int(latest_q[:4]) + 1) if latest_q[5] == "4" else "%sQ%d" % (latest_q[:4], int(latest_q[5]) + 1)
    ms = [m for m in _q_months(nq) if m in ks]
    now_q = None
    if ms and all(_mshift(m, 12) in ks for m in ms) and since(_mshift(ms[0], 12)):
        a = sum(exp_series[m] for m in ms)
        b = sum(exp_series.get(_mshift(m, 12), 0) for m in ms)
        now_q = {"q": nq, "months": ms, "g": _r1(_yoy(a, b))}
    # 맞대기 — 두 값이 다 있는 분기만, 같은 분기(시차 0)와 수출이 한 분기 앞선 것(시차 1)
    rv = {r["q"]: r.get("rev_yoy") for r in qrows}
    ex = {o["q"]: o["g"] for o in out}
    qs = [r["q"] for r in qrows]
    p0 = [(ex[q], rv[q]) for q in qs if ex.get(q) is not None and rv.get(q) is not None]
    p1 = [(ex[qs[i - 1]], rv[q]) for i, q in enumerate(qs) if i and ex.get(qs[i - 1]) is not None and rv.get(q) is not None]
    hit = tot = 0
    for i in range(1, len(qs)):
        a, b = qs[i - 1], qs[i]
        if all(v is not None for v in (ex.get(a), ex.get(b), rv.get(a), rv.get(b))):
            tot += 1
            hit += (ex[b] - ex[a] > 0) == (rv[b] - rv[a] > 0)
    fit = {"n": len(p0), "corr0": _r1(_spear([x for x, _ in p0], [y for _, y in p0]), 2) if len(p0) >= 6 else None,
           "corr1": _r1(_spear([x for x, _ in p1], [y for _, y in p1]), 2) if len(p1) >= 6 else None,
           "hit": _r1(hit / tot * 100, 0) if tot >= 8 else None, "n_hit": tot}
    if len(p0) >= 12:
        xs, ys = [x for x, _ in p0], [y for _, y in p0]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        vx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else 0.0
        a = my - b * mx
        res = [abs(y - (a + b * x)) for x, y in zip(xs, ys)]
        fit.update(a=_r1(a, 2), b=_r1(b, 3), mae=_r1(sorted(res)[len(res) // 2]))
        last_rev = next((rv[q] for q in reversed(qs) if rv.get(q) is not None), None)
        if now_q and now_q["g"] is not None:
            est = a + b * now_q["g"]
            fit["est"] = _r1(est)
            fit["last_rev"] = last_rev
            d = est - last_rev if last_rev is not None else None
            ok = (fit["hit"] or 0) >= 55 and (fit["corr0"] or 0) >= 0.3
            fit["dir"] = ("수출이 매출을 말해 주지 않는 섹터" if not ok else "가속" if d is not None and d >= 3 else "둔화" if d is not None and d <= -3 else "비슷")
    return {"q": out, "now_q": now_q, "fit": fit}


# ---------------------------------------------------------------- 업황 시계
# 띠 · 정체 · 라벨 이름과 판정(phase_label)은 드러켄밀러(가속도 탭)와 한 곳 — 두 화면의 국면이 같은 식으로 정해진다(2026-10-09)
from 드러켄밀러 import PHASE_BAND, PHASE_FLAT, PHASE_NAME, phase_label  # noqa: E402,F401


def _phase(qrows):
    """분기 행(rev_yoy = 같은 표본 전년 대비) → {label, speed, prev, accel, qs, prev_qs, trail}.
    speed = 최근 2분기 증가율 평균, prev = 그 앞 2분기 평균, accel = speed − prev. trail = 분기마다 같은 계산(최근 8개)."""
    ys = [(r["q"], r.get("rev_yoy")) for r in qrows]

    def at(i):
        if i < 3 or ys[i][1] is None or ys[i - 1][1] is None or ys[i - 2][1] is None or ys[i - 3][1] is None:
            return None
        sp = (ys[i][1] + ys[i - 1][1]) / 2
        pv = (ys[i - 2][1] + ys[i - 3][1]) / 2
        return sp, pv, sp - pv

    trail = []
    for i in range(max(0, len(ys) - 8), len(ys)):
        v = at(i)
        if v:
            trail.append({"q": ys[i][0], "speed": _r1(v[0]), "accel": _r1(v[2])})
    v = at(len(ys) - 1)
    if not v:
        return None
    sp, pv, ac = v
    n = len(ys)
    label = phase_label(sp, ac)
    return {"label": label, "speed": _r1(sp), "prev": _r1(pv), "accel": _r1(ac), "band": PHASE_BAND,
            "qs": [ys[n - 2][0], ys[n - 1][0]], "prev_qs": [ys[n - 4][0], ys[n - 3][0]], "trail": trail,
            "g": _r1(ys[-1][1]), "dg": _r1(ac)}


# ---------------------------------------------------------------- 섹터 하나
def _sector(key, desc, P, mem, caps, univ, ST, EXT, idx_stamp, blog, latest_q):
    codes = sorted(mem.get(key) or [])
    stc = SEC.STATS.get(key, {})
    notes = []
    years = list(range(FIRST_Y, int(latest_q[:4])))           # 마감된 해(2015 ~ 2025)
    quarters = _qs("2016Q1", latest_q)

    # 1) 연간 · 분기 상장사 실적
    annual = []
    idx = 100.0
    for y in years:
        p = str(y)
        rev, op, ni, n = _level(P, codes, key, p)
        g = _growth(P, codes, key, [p], [str(y - 1)]) if y > FIRST_Y else None
        if g and g.get("rev_g") is not None and y > FIRST_Y:
            idx *= 1 + g["rev_g"] / 100
        annual.append({"y": y, "rev": rev, "op": op, "ni": ni, "n": n,
                       "opm": _r1(op / rev * 100) if rev and op is not None else None,
                       "rev_g": _r1((g or {}).get("rev_g")), "op_g": _r1((g or {}).get("op_g")), "op_turn": (g or {}).get("op_turn"),
                       "n_same": (g or {}).get("n"), "cov": _r1((g or {}).get("rev_same", 0) / rev * 100, 0) if g and rev else None,
                       "idx": _r1(idx) if y > FIRST_Y and g else (100.0 if y == FIRST_Y else None)})
    qrows = []
    for q in quarters:
        rev, op, ni, n = _level(P, codes, key, q)
        g = _growth(P, codes, key, [q], [_qprev(q)])
        qrows.append({"q": q, "rev": rev, "op": op, "n": n, "opm": _r1(op / rev * 100) if rev and op is not None else None,
                      "rev_yoy": _r1((g or {}).get("rev_g")), "op_yoy": _r1((g or {}).get("op_g")), "n_same": (g or {}).get("n")})
    for i, r in enumerate(qrows):
        b = qrows[i - 1] if i else None
        r["rev_qoq"] = _r1(_yoy(r["rev"], b["rev"])) if b else None
        r["op_qoq"] = _r1(_yoy(r["op"], b["op"])) if b and b["op"] and r["op"] and b["op"] > 0 and r["op"] > 0 else None
        r["opm_qoq"] = _r1(r["opm"] - b["opm"]) if b and r["opm"] is not None and b["opm"] is not None else None
        r["label"] = "상장사 %d곳" % r["n"]

    # TTM · 상반기
    t4 = _qs(_qprev(latest_q, 3), latest_q)
    b4 = [_qprev(q) for q in t4]
    lv = [_level(P, codes, key, q) for q in t4]
    ttm = {"rev": sum(x[0] or 0 for x in lv) if all(x[0] is not None for x in lv) else None,
           "op": sum(x[1] or 0 for x in lv) if all(x[1] is not None for x in lv) else None,
           "ni": sum(x[2] or 0 for x in lv) if all(x[2] is not None for x in lv) else None}
    gt = _growth(P, codes, key, t4, b4) or {}
    ttm.update(rev_g=_r1(gt.get("rev_g")), op_g=_r1(gt.get("op_g")), op_turn=gt.get("op_turn"), n_same=gt.get("n"),
               opm=_r1(ttm["op"] / ttm["rev"] * 100) if ttm["rev"] and ttm["op"] is not None else None,
               opm_b=_r1(gt.get("opm_b")), q0=t4[0], q1=t4[-1])
    y_now = latest_q[:4]
    h_now = [q for q in t4 if q.startswith(y_now)]
    gh = _growth(P, codes, key, h_now, [_qprev(q) for q in h_now]) if h_now else None
    ytd = {"qs": h_now, "rev_g": _r1((gh or {}).get("rev_g")), "op_g": _r1((gh or {}).get("op_g")), "op_turn": (gh or {}).get("op_turn")}

    # 업황 단계(업황 시계) — 속도 = 최근 2분기 매출 증가율(같은 표본) 평균, 가속 = 그 속도 − 바로 앞 2분기 평균.
    # 한 분기 출렁임에 라벨이 뒤집히지 않게 2분기씩 묶고, 가속이 ±PHASE_BAND %p 안이면 '유지'로 본다.
    phase = _phase(qrows)

    # 2) 생산 · 가동 · 재고 · 가격 · 수출 · BSI · 부가가치
    kos = ST.get("kosis") or {}
    sig = []
    prod_series = None
    for j, kc in enumerate(stc.get("kosis") or []):
        kd = kos.get(kc) or {}
        nm = kd.get("name") or kc
        if not kd.get("prod"):
            continue
        g, last = _m3_yoy(kd["prod"])
        if j:
            sig.append({"k": "생산 · " + nm, "v": _r1(g), "unit": "%", "at": last,
                        "note": "%s 생산지수(KOSIS), 최근 3개월 평균의 전년 대비 — 보조 지수" % nm})
            continue
        prod_series = kd["prod"]
        sig.append({"k": "생산", "v": _r1(g), "unit": "%", "at": last,
                    "note": "%s 생산지수(KOSIS), 최근 3개월 평균의 전년 대비%s" % (nm, KOSIS_SHARED.get(kc, ""))})
        if kd.get("util"):
            gu, lu = _m3_yoy(kd["util"])
            if gu is not None:
                sig.append({"k": "가동률", "v": _r1(gu), "unit": "%", "at": lu,
                            "note": "%s 가동률지수, 최근 3개월 평균의 전년 대비(%s 원지수 %.1f)" % (nm, lu, kd["util"][lu])})
        if kd.get("ship") and kd.get("inv"):
            gs, last2 = _m3_yoy(kd["ship"])
            gi, _ = _m3_yoy(kd["inv"])
            if gs is not None and gi is not None:
                sig.append({"k": "재고 순환", "v": _r1(gs - gi), "unit": "%p", "at": last2,
                            "note": "출하 증가율 %+.1f%% − 재고 증가율 %+.1f%% (3개월 평균, 전년 대비) — 플러스면 재고가 줄며 출하가 는다" % (gs, gi)})
    ec = ST.get("ecos") or {}
    xp_series = None
    for j, e0 in enumerate(stc.get("ecos") or []):
        ed = ec.get(e0) or {}
        nm = ed.get("name") or e0
        if ed.get("xp"):
            g, last = _m3_yoy(ed["xp"])
            if j == 0:
                xp_series = ed["xp"]
            sig.append({"k": "수출물가" if j == 0 else "수출물가 · " + nm, "v": _r1(g), "unit": "%", "at": last,
                        "note": "%s 수출물가지수(원화, 한국은행), 3개월 평균 전년 대비" % nm})
        if ed.get("xv") and j == 0:
            g, last = _m3_yoy(ed["xv"])
            sig.append({"k": "수출물량", "v": _r1(g), "unit": "%", "at": last, "note": "%s 수출물량지수(한국은행), 3개월 평균 전년 대비" % nm})
    items = []
    for it in stc.get("item") or []:
        d = (ST.get("item") or {}).get(it[0]) or {}
        g, last = _m3_yoy(d.get("v") or {})
        if g is not None:
            items.append({"name": it[2], "v": _r1(g), "at": last, "lvl": _r1((d.get("v") or {}).get(last), 2)})
    # 수출(관세청) — HS 질의 합(hs6 가 있으면 6단위 합). 묶음 안 품목이 모두 있던 때부터만 증가율을 낸다(HS 개정으로 새로 생긴 호 등)
    ex = ST.get("exports") or {}
    ex6 = ST.get("exports6") or {}
    if stc.get("hs6") and all(h in ex6 for h in stc["hs6"]):
        src_ex, hs_list = ex6, list(stc["hs6"])
    else:
        src_ex, hs_list = ex, [h for h in stc.get("hs") or [] if h in ex]
    first = {h: (_mkeys((src_ex.get(h) or {}).get("usd") or {}) or [None])[0] for h in hs_list}

    def since(ym):
        return bool(first) and all(f and f <= ym for f in first.values())
    exp_series = _sum_series([(src_ex.get(h) or {}).get("usd") for h in hs_list]) if hs_list else {}
    exp_info = None
    if exp_series:
        ks = _mkeys(exp_series)
        last = ks[-1]
        g3, _ = _m3_yoy(exp_series, last)
        m12 = sum(exp_series.get(_mshift(last, i), 0) for i in range(12))
        p12 = sum(exp_series.get(_mshift(last, i + 12), 0) for i in range(12))
        ytd_k = [k for k in ks if k[:4] == last[:4]]
        e_ytd = sum(exp_series[k] for k in ytd_k)
        e_ytd_b = sum(exp_series.get(_mshift(k, 12), 0) for k in ytd_k)
        tot = ST.get("exports_total") or {}
        t12 = sum(tot.get(_mshift(last, i), 0) for i in range(12))
        main = src_ex.get(hs_list[0]) or {}
        par = ex.get(hs_list[0][:4]) or main
        kg = main.get("kg") or {}
        up = None
        if kg:
            a = sum((main.get("usd") or {}).get(_mshift(last, i), 0) for i in range(3))
            ak = sum(kg.get(_mshift(last, i), 0) for i in range(3))
            b = sum((main.get("usd") or {}).get(_mshift(last, i + 12), 0) for i in range(3))
            bk = sum(kg.get(_mshift(last, i + 12), 0) for i in range(3))
            if ak and bk and a and b:
                up = _yoy(a / ak, b / bk)
        exp_info = {"last": last, "m3_g": _r1(g3) if since(_mshift(last, 14)) else None, "m12": m12,
                    "m12_g": _r1(_yoy(m12, p12)) if since(_mshift(last, 23)) else None,
                    "ytd": e_ytd, "ytd_g": _r1(_yoy(e_ytd, e_ytd_b)) if since("%d01" % (int(last[:4]) - 1)) else None,
                    "ytd_months": len(ytd_k), "share": _r1(m12 / t12 * 100) if t12 else None, "unit_price_g": _r1(up),
                    "hs": [{"hs": h, "name": (src_ex.get(h) or {}).get("name"),
                            "m12": sum(((src_ex.get(h) or {}).get("usd") or {}).get(_mshift(last, i), 0) for i in range(12))} for h in hs_list],
                    "sub12": par.get("sub12") or [], "dest12": par.get("dest12") or []}
        sig.append({"k": "수출", "v": exp_info["m3_g"], "unit": "%", "at": last, "note": "관세청 통관 수출(HS %s), 최근 3개월 합의 전년 대비" % " · ".join(hs_list)})
        # 하위탭 '수출 먼저' — 분기 수출(석 달 합)의 전년 대비를 섹터 매출 증가율(같은 표본)과 분기마다 맞대고,
        # 아직 공시 안 된 다음 분기는 나온 달만으로 수출을 내어 과거 직선(수출 → 매출)으로 매출 방향을 짚는다.
        exp_info.update(_exports_q(exp_series, qrows, latest_q, since))
        if up is not None:
            sig.append({"k": "수출 단가", "v": _r1(up), "unit": "%", "at": last, "note": "HS %s 달러/kg, 3개월 전년 대비" % hs_list[0]})
    for h, nm in stc.get("hs_extra") or []:
        s2 = (ex.get(h) or {}).get("usd") or {}
        g, last = _m3_yoy(s2)
        if g is not None:
            sig.append({"k": nm, "v": _r1(g), "unit": "%", "at": last,
                        "note": "관세청 통관 HS %s, 최근 3개월 합의 전년 대비 · 12개월 %.0f억 달러 — 섹터 수출 합에는 넣지 않은 보조 줄" % (
                            h, sum(s2.get(_mshift(last, i), 0) for i in range(12)) / 1e8)})
    for pk in stc.get("phys") or []:
        d = (ST.get("phys") or {}).get(pk) or {}
        g, last = _m3_yoy(d.get("v") or {})
        if g is not None:
            sig.append({"k": d.get("name") or pk, "v": _r1(g), "unit": "%", "at": last, "note": "%s(%s), 3개월 전년 대비" % (d.get("name") or pk, d.get("unit") or "")})
    bsi = None
    bd = (ST.get("bsi") or {}).get(stc.get("bsi")) or {}
    fk = _mkeys(bd.get("fc") or {})
    if fk:
        ak = _mkeys(bd.get("act") or {})
        bsi = {"name": bd.get("name"), "fc": bd["fc"][fk[-1]], "fc_at": fk[-1], "fc_prev": bd["fc"].get(_mshift(fk[-1], 3)),
               "act": bd["act"][ak[-1]] if ak else None}
    gva = None
    gd = (ST.get("gva") or {}).get(stc.get("gva")) or {}
    if gd.get("real"):
        ks = sorted(k for k, v in gd["real"].items() if v is not None)
        last = ks[-1]
        prev = "%dQ%s" % (int(last[:4]) - 1, last[5:])
        gva = {"name": gd.get("name"), "at": last, "real_g": _r1(_yoy(gd["real"].get(last), gd["real"].get(prev))),
               "nom_g": _r1(_yoy((gd.get("nom") or {}).get(last), (gd.get("nom") or {}).get(prev)))}
        sig.append({"k": "부가가치", "v": gva["real_g"], "unit": "%", "at": last, "note": "%s 실질 부가가치(한국은행, 계절조정), 전년 같은 분기 대비" % (gd.get("name") or "")})

    # 연간 표에 생산 · 수출 · 수출물가 붙이기
    for a in annual:
        y = a["y"]
        if prod_series:
            a["prod_g"] = _r1(_yoy(_year_agg(prod_series, y), _year_agg(prod_series, y - 1)))
        if exp_series and since("%d01" % y):
            a["exp"] = _year_agg(exp_series, y, "sum")
            a["exp_g"] = _r1(_yoy(a["exp"], _year_agg(exp_series, y - 1, "sum"))) if since("%d01" % (y - 1)) else None
        if xp_series:
            a["xp_g"] = _r1(_yoy(_year_agg(xp_series, y), _year_agg(xp_series, y - 1)))

    # 3) 시가총액 · 주축 기업
    def look_through(c, raw):
        """회사 시총 − Σ 지분율 × 상장 자회사 · 관계회사 시총(0 아래는 0) — 자회사 가치는 자회사 섹터에서 센다."""
        adj = raw
        for k2, h in P.hold.items():
            pa, ch = k2.split(">")
            if pa == c and ch in caps and isinstance(h.get("stake"), (int, float)):
                adj -= h["stake"] / 100.0 * (caps[ch].get("cap") or 0)
        return max(adj, 0.0)

    def assoc_ni(c):
        """지분법 관계회사 순이익 몫(최근 4분기) — 시총에서 그 가치를 뺐으니 순이익에서도 뺀다."""
        s = 0.0
        for k2, h in P.hold.items():
            pa, ch = k2.split(">")
            if pa == c and h.get("kind") == "관계" and isinstance(h.get("stake"), (int, float)) and ch in caps:
                v = [P.per(ch, q) for q in t4]
                if all(x and x.get("ni_own") is not None for x in v):
                    s += h["stake"] / 100.0 * sum(x["ni_own"] for x in v)
        return s

    sy_now = int(latest_q[:4])
    mem_rows = []
    for c in codes:
        cp = caps.get(c) or {}
        u = univ.get(c) or {}
        raw = cp.get("cap")
        if raw is None:
            continue
        seg_name = None
        lvq = [P.contrib(c, q, sy_now) for q in t4]
        modes = {(m or ("",))[0] for _, m in lvq}
        if not all(x and key in x for x, _ in lvq):
            rev_t = op_t = ni_t = None
        else:
            rev_t = sum(x[key][0] for x, _ in lvq)
            op_t = sum((x[key][1] or 0) for x, _ in lvq) if all(x[key][1] is not None for x, _ in lvq) else None
            ni_t = sum((x[key][2] or 0) for x, _ in lvq) if all(x[key][2] is not None for x, _ in lvq) else None
        if c in SEC.SEGMENTS and modes != {"seg"} and not (c in SEC.SEG_FALLBACK and modes == {"whole"}):
            continue                     # 부문 자료가 없는 부문 회사 — 회사 전체 시총을 이 섹터에 얹지 않는다
        if c in SEC.SEGMENTS and modes == {"seg"}:
            # 지분 가치를 뺀 시총을 최근 4분기 부문 영업이익(플러스) 비중으로 나눈다 — 근사
            pos_all = pos_sec = 0.0
            names = set()
            for q in t4:
                for s in P.segs(c, q):
                    o = max(s.get("op") or 0, 0)
                    pos_all += o
                    if P.seg_sector(c, s.get("name"), sy_now) == key:
                        pos_sec += o
                        names.add(re.sub(r"\s+", "", s.get("name") or ""))
            if not rev_t:
                continue
            adj = look_through(c, raw) * (pos_sec / pos_all) if pos_all > 0 else 0.0
            seg_name = " · ".join(sorted(n for n in names if n))
            ni_adj = None
        else:
            adj = look_through(c, raw)
            ni_adj = (ni_t - assoc_ni(c)) if ni_t is not None else None
        g1 = _growth(P, [c], key, t4, b4) or {}
        own_ni = None
        lvo = [P.per(c, q) for q in t4]
        if all(x and x.get("ni_own") is not None for x in lvo):
            own_ni = sum(x["ni_own"] for x in lvo)
        cons = None
        cs = _load(os.path.join(CACHE, "consensus", c + "_annual.json")) or {}
        if c not in SEC.SEGMENTS and cs.get("rows"):
            ck = [col["key"] for col in cs.get("cols") or [] if col.get("consensus")]
            if ck and ck[0].startswith(y_now):
                b_key = str(int(y_now) - 1) + ck[0][4:]
                rr, oo = cs["rows"].get("매출액") or {}, cs["rows"].get("영업이익") or {}
                if rr.get(ck[0]) and rr.get(b_key):
                    cons = {"rev_e": rr[ck[0]], "rev_a": rr[b_key], "op_e": oo.get(ck[0]), "op_a": oo.get(b_key),
                            "rev_g": _r1(_yoy(rr[ck[0]], rr[b_key])), "op_g": _r1(_yoy(oo.get(ck[0]), oo.get(b_key))) if (oo.get(b_key) or 0) > 0 else None,
                            "at": dt.datetime.fromtimestamp(cs.get("fetched") or 0).strftime("%Y-%m-%d") if cs.get("fetched") else None}
        mem_rows.append({"code": c, "name": u.get("name") or (P.co.get(c) or {}).get("name"), "seg": seg_name,
                         "cap": raw, "adj": adj, "rev_ttm": rev_t, "op_ttm": op_t, "_ni": ni_adj,
                         "opm": _r1(op_t / rev_t * 100) if rev_t and op_t is not None else None,
                         "rev_g": _r1(g1.get("rev_g")), "op_g": _r1(g1.get("op_g")), "op_turn": g1.get("op_turn"), "opm_b": _r1(g1.get("opm_b")),
                         "per": _r1(raw / own_ni) if own_ni and own_ni > 0 and not seg_name else None,
                         "ret1y": _r1(cp.get("ret1y")), "cons": cons,
                         "note": SEC.MEMBER_NOTE.get(c) or ("상장 자회사 · 관계회사 지분 가치가 시가총액보다 커서 자기 몫 시총이 0 으로 잡힌다(지주 할인)"
                                                            if raw and not adj else None)})
    capsum = sum(m["adj"] or 0 for m in mem_rows)
    raw_sum = sum(m["cap"] for m in mem_rows if not m["seg"])
    mem_rows.sort(key=lambda m: -(m["adj"] or 0))
    for m in mem_rows:
        m["share"] = _r1((m["adj"] or 0) / capsum * 100) if capsum else None
    base1y = sum((m["adj"] or 0) / (1 + m["ret1y"] / 100) for m in mem_rows if m["ret1y"] is not None and m["ret1y"] > -99)
    cur1y = sum((m["adj"] or 0) for m in mem_rows if m["ret1y"] is not None and m["ret1y"] > -99)
    cap = {"adj": capsum, "raw": raw_sum, "ret1y": _r1(_yoy(cur1y, base1y)), "n": len(mem_rows),
           "top3": _r1(sum(m["share"] or 0 for m in mem_rows[:3]))}
    # 값 매기기 — 부문 회사(순이익을 부문으로 못 나눈다)와 자기 몫 시총이 0 인 지주는 빼고, 같은 회사들의 시총 · 순이익 · 매출 · 영업이익으로
    vm = [m for m in mem_rows if not m["seg"] and (m["adj"] or 0) > 0 and m["rev_ttm"]]
    v_cap = sum(m["adj"] for m in vm)
    v_ni = sum(m["_ni"] for m in vm if m["_ni"] is not None)
    v_rev = sum(m["rev_ttm"] for m in vm)
    v_op = sum(m["op_ttm"] for m in vm if m["op_ttm"] is not None)
    val = {"per": _r1(v_cap / v_ni) if v_ni > 0 else None,
           "per_op": _r1(v_cap / (v_op * 0.76)) if v_op > 0 else None,
           "psr": _r1(v_cap / v_rev, 2) if v_rev else None, "n": len(vm),
           "cov": _r1(v_cap / capsum * 100, 0) if capsum else None,
           "seg_out": [m["name"] for m in mem_rows if m["seg"]]}
    for m in mem_rows:
        m.pop("_ni", None)
    rev_tot = ttm.get("rev") or 0
    top = mem_rows[:12] + [m for m in mem_rows[12:] if rev_tot and (m["rev_ttm"] or 0) >= 0.05 * rev_tot]
    # 섹터 안 전 종목 업황(하위탭 '섹터 안 종목') — 회사마다 섹터와 같은 식(속도 = 최근 2분기 분기 매출 전년 대비 평균, 가속 = 앞 2분기 대비)
    # 분기 전년 대비는 섹터 증가율과 같은 '같은 구조' 기준(_growth, 한 회사). 라벨은 _phase 그대로.
    members_all = []
    q12 = quarters[-12:]
    for m in mem_rows:
        c = m["code"]
        rows_c = [{"q": q, "rev_yoy": _r1((_growth(P, [c], key, [q], [_qprev(q)]) or {}).get("rev_g"))} for q in q12]
        ph = _phase(rows_c)
        members_all.append({k: m.get(k) for k in ("code", "name", "seg", "cap", "adj", "share", "rev_ttm", "op_ttm", "opm", "opm_b",
                                                   "rev_g", "op_g", "op_turn", "per", "ret1y", "note")}
                           | {"speed": ph and ph["speed"], "accel": ph and ph["accel"], "label": ph and ph["label"],
                              "trail": (ph or {}).get("trail") or [], "yq": [r["rev_yoy"] for r in rows_c[-4:]]})

    # 컨센서스 합(주축 기업 중 캐시가 있는 곳만)
    cc = [m for m in mem_rows if m.get("cons")]
    cons = None
    if cc:
        ra, re_ = sum(m["cons"]["rev_a"] for m in cc), sum(m["cons"]["rev_e"] for m in cc)
        oa = sum(m["cons"]["op_a"] or 0 for m in cc)
        oe = sum(m["cons"]["op_e"] or 0 for m in cc)
        cons = {"n": len(cc), "cov": _r1(sum(m["adj"] or 0 for m in cc) / capsum * 100, 0) if capsum else None,
                "rev_g": _r1(_yoy(re_, ra)), "op_g": _r1(_yoy(oe, oa)) if oa > 0 else None, "year": y_now,
                "names": [m["name"] for m in cc[:6]]}

    # 4) 수주잔고(수주로 매출이 정해지는 섹터)
    backlog = None
    if key in SEC.ORDER_DRIVEN:
        tot = tot_b = tot_w = rev_cov = 0.0
        n = n_b = 0
        blog_rows = []
        for m in mem_rows:
            c = m["code"]
            pts = blog.get(c) or {}
            if not pts or not m["rev_ttm"]:
                continue
            st = max(pts)
            if st < latest_q[:4] + "-01":
                continue
            v = pts[st]
            v_b = pts.get(str(int(st[:4]) - 1) + st[4:])
            for ch in P.kids(c, int(latest_q[:4])):
                cpts = blog.get(ch) or {}
                if st in cpts:
                    v -= cpts[st]
                    if v_b is not None and (str(int(st[:4]) - 1) + st[4:]) in cpts:
                        v_b -= cpts[str(int(st[:4]) - 1) + st[4:]]
            if v <= 0:
                continue
            tot += v
            n += 1
            if v_b and v_b > 0:
                tot_b += v_b
                tot_w += v            # 섹터 1년 변화는 전년 점이 있는 회사끼리(같은 표본) — 안 그러면 전년 점이 없는 큰 회사가 증가율을 부풀린다
                n_b += 1
            # 부문 회사 가운데 잔고가 회사 전체 값인 곳(SEC.BACKLOG_WHOLE, 현대로템)은 분모 · 기준도 회사 전체 매출로 — 부문 매출로 나누면 년수 · 차이가 부푼다.
            # 삼성물산처럼 잔고 표가 부문(건설)만의 값이면 부문 매출 그대로.
            whole = bool(m["seg"]) and c in SEC.BACKLOG_WHOLE
            if whole:
                rc = sum(((P.per(c, q) or {}).get("rev") or 0) for q in t4)
                rcb = sum(((P.per(c, q) or {}).get("rev") or 0) for q in b4)
                rev_c, rev_gc = (rc or None), (_r1(_yoy(rc, rcb)) if rc and rcb else None)
            else:
                rev_c, rev_gc = m["rev_ttm"], m["rev_g"]
            if rev_c:
                rev_cov += rev_c
            b_yoy = _r1(_yoy(v, v_b)) if v_b and v_b > 0 else None
            blog_rows.append({"code": c, "name": m["name"], "seg": m["seg"], "whole": whole, "value": v, "at": st, "yoy": b_yoy,
                              "years": _r1(v / rev_c, 1) if rev_c else None, "rev_g": rev_gc,
                              "gap": _r1(b_yoy - rev_gc) if b_yoy is not None and rev_gc is not None else None,
                              "ret1y": m["ret1y"], "adj": m["adj"]})
        if n:
            backlog = {"value": tot, "n": n, "years": _r1(tot / rev_cov, 1) if rev_cov else None,
                       "yoy": _r1(_yoy(tot_w, tot_b)) if tot_b else None, "n_b": n_b,
                       "rows": sorted(blog_rows, key=lambda r: -(r["value"] or 0))}

    # 5) 외부 자료(시장 규모 · 전망 · 동인)
    ex_s = ((EXT or {}).get("sectors") or {}).get(key) or {}
    kiet = None
    kn = stc.get("kiet")
    if kn:
        kiet = (((EXT or {}).get("kiet") or {}).get("industries") or {}).get(kn)

    # 6) 예상치 줄
    fc = []
    for it in ex_s.get("world") or []:
        if it.get("kind") == "forecast" and _full_year(it) and str(it.get("year")) in (y_now, str(int(y_now) + 1)):
            fc.append({"what": it.get("metric"), "year": it.get("year"), "value": it.get("value"), "unit": it.get("unit"),
                       "g": it.get("growth_pct"), "src": it.get("source"), "url": it.get("url"), "at": it.get("published"), "kind": "세계"})
    if kiet:
        fy = y_now + "F"
        for lab, kk, gk in (("한국 수출", "export_usd_mn", "export_g"), ("한국 생산", "prod", "prod_g"), ("한국 내수", None, "dom_g")):
            g = (kiet.get(gk) or {}).get(fy)
            if g is not None:
                fc.append({"what": lab + "(산업연구원)", "year": y_now, "g": g,
                           "value": ((kiet.get(kk) or {}).get(fy) if kk else None),
                           "unit": ("USD mn" if kk == "export_usd_mn" else (kiet.get("prod") or {}).get("unit") if kk == "prod" else None),
                           "src": "산업연구원 %s" % ((EXT.get("kiet") or {}).get("published") or ""), "url": (EXT.get("kiet") or {}).get("url"), "kind": "한국"})
    for it in ex_s.get("korea") or []:
        if it.get("kind") == "forecast" and _full_year(it) and str(it.get("year")) in (y_now, str(int(y_now) + 1)) \
                and "산업연구원" not in (it.get("source") or ""):
            fc.append({"what": it.get("metric"), "year": it.get("year"), "value": it.get("value"), "unit": it.get("unit"),
                       "g": it.get("growth_pct"), "src": it.get("source"), "url": it.get("url"), "at": it.get("published"), "kind": "한국"})
    if cons:
        fc.append({"what": "주축 기업 매출(컨센서스, %d곳)" % cons["n"], "year": y_now, "g": cons["rev_g"], "kind": "상장사",
                   "src": "네이버 금융 컨센서스(개인 열람용) · 시총 %s%% 덮음" % (cons["cov"] if cons["cov"] is not None else "—")})
        if cons.get("op_g") is not None:
            fc.append({"what": "주축 기업 영업이익(컨센서스, %d곳)" % cons["n"], "year": y_now, "g": cons["op_g"], "kind": "상장사", "src": "네이버 금융 컨센서스(개인 열람용)"})
    if bsi:
        fc.append({"what": "매출 전망 BSI(%s)" % (bsi.get("name") or ""), "year": bsi["fc_at"][:4] + "." + bsi["fc_at"][4:], "value": bsi["fc"],
                   "unit": "기준 100", "kind": "체감", "src": "한국은행 기업경기조사"})

    # 7) 세계 시장 규모 한 줄(가장 최근 실제)
    # 대표 지표(산업_섹터.WORLD_MAIN) 한 계열 — 가장 최근 해의 실제 · 추정, 없으면 올해부터 가장 가까운 전망
    pat = SEC.WORLD_MAIN.get(key)
    main = [_gb(i) for i in ex_s.get("world") or [] if pat and pat in (i.get("metric") or "") and _full_year(i)
            and "직전판" not in (i.get("metric") or "")]
    act = sorted([i for i in main if i.get("kind") in ("actual", "estimate")], key=lambda i: (str(i.get("year")), i.get("kind") == "actual"))
    fut = sorted([i for i in main if i.get("kind") == "forecast" and str(i.get("year")) >= y_now], key=lambda i: str(i.get("year")))
    world_now = act[-1] if act else fut[0] if fut else None
    if world_now:
        main = [i for i in main if i.get("unit") == world_now.get("unit")]          # 한 줄에 단위가 다른 값을 섞지 않는다
    # 요약표 '전망' 한 칸 — 세계 시장 같은 계열의 올해 전망, 없으면 산업연구원 한국 수출, 없으면 컨센서스
    fc_main = None
    for i in main:
        if i.get("kind") == "forecast" and str(i.get("year")) == y_now and i.get("growth_pct") is not None:
            fc_main = {"g": i["growth_pct"], "year": y_now, "what": i.get("metric"), "src": i.get("source"), "kind": "세계", "basis": i.get("g_basis")}
            break
    if not fc_main:
        f2 = next((f for f in fc if "산업연구원" in (f.get("what") or "") and "수출" in f["what"] and f.get("g") is not None), None) or             next((f for f in fc if f.get("kind") == "상장사" and f.get("g") is not None and (cons or {}).get("cov") and cons["cov"] >= 30), None)
        if f2:
            fc_main = {"g": f2["g"], "year": f2["year"], "what": f2["what"], "src": f2.get("src"), "kind": f2.get("kind")}

    return {"key": key, "desc": desc, "n": len(codes), "annual": annual, "quarters": qrows[-12:], "quarters_all": qrows,
            "ttm": ttm, "ytd": ytd, "phase": phase, "signals": sig, "items": items, "exports": exp_info, "bsi": bsi, "gva": gva,
            "monthly": {"prod": {k: v for k, v in (prod_series or {}).items() if k >= "2019"},
                        "exp": {k: v for k, v in exp_series.items() if k >= "2019"},
                        "xp": {k: v for k, v in (xp_series or {}).items() if k >= "2019"}},
            "cap": cap, "val": val, "members": top, "members_all": members_all, "n_members_cap": len(mem_rows), "cons": cons, "backlog": backlog,
            "world_now": world_now, "world_main": main, "fc_main": fc_main,
            "world": [_gb(i) for i in ex_s.get("world") or []], "korea": [_gb(i) for i in ex_s.get("korea") or []], "leaders": ex_s.get("leaders") or [],
            "definition": ex_s.get("definition"), "drivers": ex_s.get("drivers"), "watch": ex_s.get("watch") or [],
            "kiet": kiet, "forecast": fc, "notes": notes + SECTOR_NOTES.get(key, [])}


def _backlog_points(index=None):
    """{code: {'YYYY-MM': 잔고(원)}} — .cache/수주 의 접수번호를 색인으로 시점에 잇는다.
    index = 서버가 이미 가진 색인(dict). 없으면 .cache/색인.json(133MB)을 읽는데, 32비트 파이썬 서버 안에서는 그것을 한 번 더 올리다
    MemoryError 가 나서 잔고가 전부 비던 문제(2026-10-08)가 있었다 — 서버는 꼭 넘긴다. 못 읽으면 ({}, 사유)."""
    ix = index if isinstance(index, dict) and index.get("companies") else None
    if ix is None:
        try:
            with open(os.path.join(CACHE, "색인.json"), "r", encoding="utf-8") as fh:
                ix = json.load(fh)
        except Exception as e:
            return {}, "색인을 못 읽어 수주잔고를 잇지 못했다(%s: %s)" % (type(e).__name__, e)
    stamp = {}
    for c in ix.get("companies") or []:
        for r in c.get("reports") or []:
            stamp[r.get("rcept")] = r.get("stamp")
    out = {}
    d = os.path.join(CACHE, "수주")
    for f in os.listdir(d) if os.path.isdir(d) else []:
        if not f.endswith(".json"):
            continue
        js = _load(os.path.join(d, f)) or {}
        pts = {}
        for rc, v in js.items():
            if isinstance(v, dict) and v.get("value") and stamp.get(rc):
                pts[stamp[rc]] = v["value"]
        if pts:
            out[f[:-5]] = pts
    return out, None


def build(progress=None, index=None):
    t0 = time.time()
    say = progress or (lambda *_: None)
    panel = _load(os.path.join(DIR, "panel.json"))
    if not panel or not panel.get("companies"):
        raise RuntimeError("panel.json 이 없다 — python 산업_패널.py 먼저")
    seg = _load(os.path.join(DIR, "부문.json")) or {}
    ST = _load(os.path.join(DIR, "통계.json")) or {}
    EXT = _load(EXT_PATH) or {}
    P = Panel(panel, seg)
    say("시세 읽는 중")
    univ, snap = _universe()
    caps = _caps(univ, snap)
    say("수주잔고 읽는 중")
    blog, blog_err = _backlog_points(index)
    if blog_err:
        P.notes.append(blog_err)
    mem = _members(P)
    # 가장 최근 분기 — 12월 결산 회사의 80%↑가 그 분기를 보고했고, 바로 앞 분기에 보고한 회사 수의 80%↑인 분기
    cnt = {}
    for code, co in P.co.items():
        if (co.get("fy_end_month") or 12) != 12:
            continue
        for q, v in (co.get("q") or {}).items():
            if v and v.get("rev") is not None:
                cnt[q] = cnt.get(q, 0) + 1
    qs = sorted(cnt)
    latest_q = None
    for q in reversed(qs):
        if cnt.get(_qprev(q, 1)) and cnt[q] >= 0.8 * cnt[_qprev(q, 1)]:
            latest_q = q
            break
    latest_q = latest_q or (qs[-1] if qs else "%dQ4" % (dt.date.today().year - 1))
    rows = []
    for i, (k, desc) in enumerate(SEC.SECTORS):
        say("섹터 %s" % k, i, len(SEC.SECTORS))
        rows.append(_sector(k, desc, P, mem, caps, univ, ST, EXT, None, blog, latest_q))
    # 제외(금융 · 지주 · 목록 밖)
    ex = []
    for code, u in univ.items():
        if code in SEC.SEGMENTS:
            continue
        sec, why = SEC.sector_of(code, (P.co.get(code) or {}).get("ksic"))
        if sec == "제외":
            ex.append((caps.get(code, {}).get("cap") or u["cap"], u["name"], why))
    ex.sort(reverse=True)
    lat = ST.get("latest") or {}
    res = {"v": V, "at": time.time(), "latest_q": latest_q, "y_now": latest_q[:4],
           "as_of": {"fin": latest_q, "price": max((c.get("px_date") or "" for c in caps.values()), default=None),
                     "kosis": lat.get("kosis"), "ecos": lat.get("ecos"), "customs": lat.get("customs"), "gva": lat.get("gva"),
                     "ext": EXT.get("as_of"), "panel": panel.get("built"), "seg": seg.get("built"), "stats": ST.get("built")},
           "sectors": rows,
           "excluded": {"n": len(ex), "cap": sum(e[0] for e in ex), "top": [{"name": e[1], "cap": e[0], "why": e[2]} for e in ex[:15]]},
           "macro": EXT.get("macro") or [], "util_mfg": ST.get("util_mfg") and {k: v for k, v in ST["util_mfg"].items() if k >= "2019"},
           "notes": P.notes, "secs": round(time.time() - t0, 1)}
    os.makedirs(DIR, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)
    os.replace(tmp, OUT)
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = build(lambda *a: print(*a, flush=True))
    f = lambda v, d=1: "—" if v is None else ("%+." + str(d) + "f") % v
    print("최근 분기 %s · %.0f초" % (r["latest_q"], r["secs"]))
    print("%-10s %8s %7s %7s %7s %6s %7s %7s %5s" % ("섹터", "시총(조)", "매출TTM", "매출g", "영익g", "OPM", "생산", "수출3M", "단계"))
    for s in r["sectors"]:
        t = s["ttm"]
        sg = {x["k"]: x["v"] for x in s["signals"]}
        print("%-10s %8.1f %7.1f %7s %7s %6s %7s %7s %5s" % (
            s["key"], (s["cap"]["adj"] or 0) / 1e12, (t["rev"] or 0) / 1e12, f(t["rev_g"]), f(t["op_g"]),
            "—" if t["opm"] is None else "%.1f" % t["opm"], f(sg.get("생산")), f(sg.get("수출")), (s["phase"] or {}).get("label") or "—"))
