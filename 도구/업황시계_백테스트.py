# -*- coding: utf-8 -*-
"""
업황 시계 라벨의 뒤 성적 — '그 라벨을 알게 된 날' 섹터 바구니를 샀다면 3 · 6 · 12개월 뒤 시장보다 얼마나 벌었나 (2026-10-08)

질문
  산업 성장률 탭의 '업황 시계'는 섹터마다 라벨을 붙인다(산업.py _phase 와 같은 식).
    속도 = 최근 2분기 섹터 매출 증가율(같은 표본 전년 대비)의 평균, 가속 = 속도 − 바로 앞 2분기 평균
    라벨 = 정체(|속도|<2 · |가속|<3) / 속도>0: 확장 가속(가속≥3) · 확장 유지 · 둔화(가속≤−3) / 속도≤0: 회복(가속≥3) · 부진 지속 · 수축 심화(가속≤−3)
  "분기 q 에 어떤 라벨이던 섹터를, 그 라벨을 알 수 있게 된 날(보고서 마감 다음 거래일) 샀다면 3 · 6 · 12개월 뒤 시장 대비 얼마나 벌었나?"
  라벨마다 · 섹터마다 센다. 라벨이 주가를 앞서는 신호인지, 이미 지난 일을 적은 꼬리표인지 가린다.

방법
  라벨    .cache/산업/_result.json 의 sectors[].quarters_all(2016Q1~2026Q2, rev_yoy = 같은 표본 전년 대비)을 분기 i 까지 잘라
          산업.py _phase 로 다시 센다. 4분기가 쌓여야 라벨이 나오니 2016Q4 부터. 산업.py 를 그대로 불러 쓴다(식이 어긋나지 않게).
  진입일  분기 보고서 마감 다음 거래일 — Q1 5/15 · Q2 8/14 · Q3 11/14 · Q4 다음 해 3/31 뒤 첫 거래일.
          거래일 달력 = 시세 캐시(.cache/price, 988곳)에서 100곳 이상 시세가 있는 날.
  바구니  panel.json 의 회사를 산업_섹터.sector_of 로 섹터에 붙인다. 부문 회사(산업_섹터.SEGMENTS, 삼성전자 등 14곳)는
          여러 섹터에 걸쳐 있어 회사 전체 주가를 한 섹터에 못 붙이니 뺀다. 그날 종가가 있는 회사만(상장 전이면 뺀다). 5곳 이상일 때만.
  수익    회사마다 r = 분할 보정 종가(진입일 + 91 · 182 · 365일 뒤 첫 거래일) ÷ 종가(진입일) − 1.
          동일 가중 = 평균, 시총 가중 = Σw·r ÷ Σw(w = 2026-10-01 시총 스냅샷 × 그날 주가 ÷ 스냅샷 날 주가 — 주식 수 고정 근사).
  기준    같은 날 시세 캐시 전 종목(988곳)의 같은 통계 — 동일 가중 바구니는 전 종목 평균, 시총 가중 바구니는 전 종목 시총 가중 평균.
          초과수익 = 바구니 − 기준(%p). (처음엔 평균에서 중앙값을 빼서 모든 라벨이 +10%p 안팎 양수로 떠 보였다 — 2026-10-08 고침)
  통계    라벨 × 기간 × 가중마다 n(섹터-분기) · 중앙값 · 이긴 비율(>0) · 90% 구간 · 2020 앞/뒤 중앙값.
          90% 구간 = 섹터를 통째로 복원추출하는 부트스트랩 500회(시드 고정) — 한 섹터의 분기들은 서로 닮아 있어
          섹터 단위로 뽑아야 구간이 덜 좁아진다.
          대조 = '확장(가속+유지)' 대 '그 밖', '확장 가속' 대 '둔화' 의 중앙값 차이와 같은 부트스트랩 구간.
          전이표 = 라벨(t) → 라벨(t+2분기) 건수와 행 비율.
          보수 판 = 라벨을 한 분기 늦게 안다고 보고(진입 = 다음 분기 마감 다음 거래일) 라벨 표를 다시.
          쏠림 = 20섹터 중 15개 이상이 같은 라벨인 분기(지금 2026Q2 가 그렇다)의 성적을 따로.

한계
  · 지금 상장된 회사만(생존 편향) — 수익률 수준은 부풀고, 라벨끼리 견주는 차이는 덜 휜다
  · 재무는 정정 뒤 값(그때 알 수 있던 값과 다를 수 있다) · 시총은 주식 수 고정 근사 · 12개월 구간이 분기마다 겹쳐 표본이 독립이 아니다
  · 2016~2026 은 경기 사이클 2~3번뿐 — 라벨당 수십 건이라 구간이 넓다

실행: PYTHONIOENCODING=utf-8 python 도구/업황시계_백테스트.py        (네트워크 없음, 캐시만 — 1~2분)
결과: 표준출력 + .cache/산업/clock_bt.json
"""
import bisect
import collections
import datetime as dt
import importlib.util as ilu
import json
import os
import random
import statistics as st
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
DIR = os.path.join(BASE, ".cache", "산업")
PRICE_DIR = os.path.join(BASE, ".cache", "price")
OUT = os.path.join(DIR, "clock_bt.json")

HS = {"h3": 91, "h6": 182, "h12": 365}       # 보유 기간(일)
MIN_MEMBERS = 5                                # 바구니 최소 구성원
BOOT_N = 500                                   # 부트스트랩 횟수
SEED = 20261008
SPLIT = "20200101"                             # 앞/뒤 나누는 날
CROWD = 15                                     # 쏠림 — 20섹터 중 이만큼 이상 같은 라벨
CAL_MIN = 100                                  # 거래일로 치는 최소 시세 종목 수

LABELS = ["확장 가속", "확장 유지", "둔화", "회복", "부진 지속", "수축 심화", "정체"]
SHORT = {"확장 가속": "가속", "확장 유지": "유지", "둔화": "둔화", "회복": "회복",
         "부진 지속": "부진", "수축 심화": "수축", "정체": "정체"}
EXPAND = {"확장 가속", "확장 유지"}


# ---------------------------------------------------------------- 산업.py 를 그대로 불러 쓴다
def _load_ind():
    sp = ilu.spec_from_file_location("산업", os.path.join(BASE, "산업.py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


IND = _load_ind()
SEC = IND.SEC


# ---------------------------------------------------------------- 작은 도우미
def r1(v, d=1):
    return None if v is None else round(v, d)


def fmt(v, d=1):
    return "—" if v is None else "%+.*f" % (d, v)


def fn(v, d=1):
    """부호 없는 숫자."""
    return "—" if v is None else "%.*f" % (d, v)


def wid(s):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in s)


def pad(s, w, right=False):
    s = str(s)
    g = max(0, w - wid(s))
    return (" " * g + s) if right else (s + " " * g)


def med(xs):
    return st.median(xs) if xs else None


def hit(xs):
    return 100.0 * sum(1 for x in xs if x > 0) / len(xs) if xs else None


def q_add(q, n):
    y, k = int(q[:4]), int(q[5]) - 1 + n
    return "%dQ%d" % (y + k // 4, k % 4 + 1)


def deadline(q):
    """분기 보고서 마감일 — Q1 5/15 · Q2 8/14 · Q3 11/14 · Q4 다음 해 3/31."""
    y, n = int(q[:4]), int(q[5])
    if n == 4:
        return "%d0331" % (y + 1)
    return "%d%s" % (y, {1: "0515", 2: "0814", 3: "1114"}[n])


def add_days(ymd, n):
    return (dt.datetime.strptime(ymd, "%Y%m%d") + dt.timedelta(days=n)).strftime("%Y%m%d")


# ---------------------------------------------------------------- 시세
class Px:
    __slots__ = ("ks", "adj", "idx")

    def __init__(self, ks, adj):
        self.ks, self.adj = ks, adj
        self.idx = {k: i for i, k in enumerate(ks)}

    def at(self, d):
        i = self.idx.get(d)
        return None if i is None else self.adj[i]

    def on_or_after(self, d):
        i = bisect.bisect_left(self.ks, d)
        return None if i >= len(self.ks) else self.adj[i]


def load_prices():
    out = {}
    for f in sorted(os.listdir(PRICE_DIR)):
        if not f.endswith(".json"):
            continue
        ks, adj = IND._prices(f[:-5])
        if ks:
            out[f[:-5]] = Px(ks, adj)
    return out


def calendar(PX):
    cnt = collections.Counter()
    for p in PX.values():
        cnt.update(p.ks)
    return sorted(k for k, c in cnt.items() if c >= CAL_MIN)


# ---------------------------------------------------------------- 라벨 · 바구니
def phases(R):
    """섹터 → {분기: (라벨, 속도, 가속)} — 분기 i 까지 잘라 _phase 로 다시 센다."""
    out = {}
    for s in R["sectors"]:
        rows = s["quarters_all"]
        d = {}
        for i in range(3, len(rows)):
            ph = IND._phase(rows[:i + 1])
            if ph:
                d[rows[i]["q"]] = (ph["label"], ph["speed"], ph["accel"])
        out[s["key"]] = d
    return out


def members(P):
    mem = {k: set() for k in SEC.SECTOR_KEYS}
    seg = []
    for code, co in P["companies"].items():
        if code in SEC.SEGMENTS:
            seg.append(code)
            continue
        sec, _ = SEC.sector_of(code, co.get("ksic"))
        if sec in mem:
            mem[sec].add(code)
    return mem, seg


class Engine:
    def __init__(self, PX, CAL, P):
        self.PX, self.CAL, self.LAST = PX, CAL, CAL[-1]
        snap = P["snap"]
        self.cap = {c: co["cap_snap"] for c, co in P["companies"].items()}
        self.snap_px = {c: IND._px_at(px.ks, px.adj, snap) for c, px in PX.items()}
        self.bench_cache = {}
        self.used = set()

    def entry_date(self, dl):
        i = bisect.bisect_right(self.CAL, dl)
        return self.CAL[i] if i < len(self.CAL) else None

    @staticmethod
    def ret(px, entry, tgt):
        p0 = px.at(entry)
        if not p0:
            return None
        p1 = px.on_or_after(tgt)
        return None if p1 is None else (p1 / p0 - 1) * 100

    def bench(self, entry, tgt):
        """같은 날 전 종목(시세 캐시 988곳)의 (중앙값, n, 평균, 시총 가중 평균). 바구니와 같은 통계끼리 빼야 한다 —
        바구니(평균)에서 시장 중앙값을 빼면 주가 수익의 오른쪽 꼬리 때문에 모든 라벨이 +10%p 안팎 양수로 떠 보였다(2026-10-08 고침)."""
        k = (entry, tgt)
        if k not in self.bench_cache:
            rs, wv = [], []
            for c, px in self.PX.items():
                r = self.ret(px, entry, tgt)
                if r is None:
                    continue
                rs.append(r)
                sp = self.snap_px.get(c)
                w = self.cap.get(c) * px.at(entry) / sp if sp and self.cap.get(c) else None
                if w:
                    wv.append((w, r))
            mean = sum(rs) / len(rs) if rs else None
            capw = sum(w * r for w, r in wv) / sum(w for w, _ in wv) if wv else None
            self.bench_cache[k] = (med(rs), len(rs), mean, capw)
        return self.bench_cache[k]

    def basket(self, codes, entry, tgt):
        rs, ws, used = [], [], []
        for c in codes:
            px = self.PX.get(c)
            if not px:
                continue
            r = self.ret(px, entry, tgt)
            if r is None:
                continue
            sp = self.snap_px.get(c)
            w = self.cap[c] * px.at(entry) / sp if sp else None
            rs.append(r)
            ws.append(w)
            used.append(c)
        if len(rs) < MIN_MEMBERS:
            return None
        self.used.update(used)
        wv = [(w, r) for w, r in zip(ws, rs) if w]
        cap = sum(w * r for w, r in wv) / sum(w for w, _ in wv) if wv else None
        return sum(rs) / len(rs), cap, len(rs)

    def run(self, PH, mem, lag=0):
        """섹터-분기마다 {sec, q, label, speed, accel, entry, h3/h6/h12: {eq, cap, n, mkt}}. lag = 라벨을 몇 분기 늦게 아는가."""
        recs = []
        for sec, d in PH.items():
            for q in sorted(d):
                label, sp, ac = d[q]
                entry = self.entry_date(deadline(q_add(q, lag)))
                if not entry:
                    continue
                rec = {"sec": sec, "q": q, "label": label, "speed": sp, "accel": ac, "entry": entry}
                for hk, h in HS.items():
                    tgt = add_days(entry, h)
                    if tgt > self.LAST:
                        continue
                    b, nb, bm, bc = self.bench(entry, tgt)
                    if b is None or bm is None:
                        continue
                    bk = self.basket(mem[sec], entry, tgt)
                    if not bk:
                        continue
                    # 동일 가중 바구니 − 동일 가중 시장(평균), 시총 가중 바구니 − 시총 가중 시장. mkt = 시장 중앙값(보통 종목 하나의 수익)
                    rec[hk] = {"eq": bk[0] - bm, "cap": None if bk[1] is None or bc is None else bk[1] - bc,
                               "n": bk[2], "mkt": b, "mkt_mean": bm, "mkt_cap": bc, "raw": bk[0]}
                recs.append(rec)
        return recs


# ---------------------------------------------------------------- 통계
def vals(recs, hk, w, pred=lambda r: True):
    return [(r["sec"], r["entry"], r[hk][w]) for r in recs if hk in r and r[hk][w] is not None and pred(r)]


def groups_of(xs):
    g = {}
    for s, _, v in xs:
        g.setdefault(s, []).append(v)
    return g


def boot_med(groups, rng):
    """섹터를 복원추출해 다시 모은 표본의 중앙값 분포 → 90% 구간."""
    keys = sorted(groups)
    if not keys:
        return None
    meds = []
    for _ in range(BOOT_N):
        pool = []
        for _ in keys:
            pool.extend(groups[rng.choice(keys)])
        if pool:
            meds.append(st.median(pool))
    if not meds:
        return None
    meds.sort()
    return [meds[int(0.05 * (len(meds) - 1))], meds[int(0.95 * (len(meds) - 1))]]


def boot_diff(ga, gb, rng):
    """두 묶음의 중앙값 차이 — 같은 섹터 복원추출을 두 묶음에 함께 적용."""
    keys = sorted(set(ga) | set(gb))
    if not keys:
        return None
    diffs, tries = [], 0
    while len(diffs) < BOOT_N and tries < BOOT_N * 4:
        tries += 1
        a, b = [], []
        for _ in keys:
            k = rng.choice(keys)
            a.extend(ga.get(k, []))
            b.extend(gb.get(k, []))
        if a and b:
            diffs.append(st.median(a) - st.median(b))
    if not diffs:
        return None
    diffs.sort()
    return [diffs[int(0.05 * (len(diffs) - 1))], diffs[int(0.95 * (len(diffs) - 1))]]


def stat_block(xs, rng):
    v = [x[2] for x in xs]
    early = [x[2] for x in xs if x[1] < SPLIT]
    late = [x[2] for x in xs if x[1] >= SPLIT]
    ci = boot_med(groups_of(xs), rng)
    return {"n": len(v), "med": r1(med(v)), "hit": r1(hit(v), 2), "ci": [r1(ci[0]), r1(ci[1])] if ci else None,
            "early": r1(med(early)), "late": r1(med(late)), "n_early": len(early), "n_late": len(late),
            "n_sec": len(set(x[0] for x in xs))}


def label_table(recs, rng, hs=None):
    out = {}
    for lab in LABELS:
        out[lab] = {}
        for hk in (hs or HS):
            out[lab][hk] = {}
            for w in ("eq", "cap"):
                out[lab][hk][w] = stat_block(vals(recs, hk, w, lambda r, L=lab: r["label"] == L), rng)
    return out


def contrast(recs, rng, a_set, b_set, hs=None):
    out = {}
    for hk in (hs or HS):
        out[hk] = {}
        for w in ("eq", "cap"):
            xa = vals(recs, hk, w, lambda r: r["label"] in a_set)
            xb = vals(recs, hk, w, lambda r: r["label"] in b_set)
            va, vb = [x[2] for x in xa], [x[2] for x in xb]
            ma, mb = med(va), med(vb)
            ci = boot_diff(groups_of(xa), groups_of(xb), rng)
            out[hk][w] = {"n_a": len(va), "n_b": len(vb), "med_a": r1(ma), "med_b": r1(mb),
                          "hit_a": r1(hit(va), 2), "hit_b": r1(hit(vb), 2),
                          "diff": None if ma is None or mb is None else r1(ma - mb),
                          "ci": [r1(ci[0]), r1(ci[1])] if ci else None}
    return out


def transition(PH):
    T = {a: {b: 0 for b in LABELS} for a in LABELS}
    for d in PH.values():
        for q, (lab, _, _) in d.items():
            q2 = q_add(q, 2)
            if q2 in d:
                T[lab][d[q2][0]] += 1
    out = {}
    for a in LABELS:
        tot = sum(T[a].values())
        out[a] = {"n": tot, "to": T[a], "pct": {b: (r1(100.0 * T[a][b] / tot) if tot else None) for b in LABELS}}
    return out


def sector_table(PH, recs, mem):
    by = {}
    for r in recs:
        by.setdefault(r["sec"], {})[r["q"]] = r
    out = {}
    for sec, d in PH.items():
        rs = by.get(sec, {})
        now_q = max(d)
        now_lab, now_sp, now_ac = d[now_q]
        by_label = {}
        for lab in LABELS:
            v = [r["h12"]["eq"] for r in rs.values() if r["label"] == lab and "h12" in r]
            vc = [r["h12"]["cap"] for r in rs.values() if r["label"] == lab and "h12" in r and r["h12"]["cap"] is not None]
            if v:
                by_label[lab] = {"n": len(v), "med": r1(med(v)), "med_cap": r1(med(vc)), "hit": r1(hit(v), 2)}
        band = []
        for q in sorted(d):
            lab, sp, ac = d[q]
            r = rs.get(q)
            row = {"q": q, "label": lab, "speed": sp, "accel": ac}
            for hk in HS:
                row["ex" + hk[1:]] = r1(r[hk]["eq"]) if r and hk in r else None
            row["ex12c"] = r1(r["h12"]["cap"]) if r and "h12" in r and r["h12"]["cap"] is not None else None
            band.append(row)
        out[sec] = {"now": {"q": now_q, "label": now_lab, "speed": now_sp, "accel": now_ac},
                    "now_hist": by_label.get(now_lab, {"n": 0, "med": None, "med_cap": None, "hit": None}),
                    "by_label": by_label, "members": len(mem[sec]), "band": band}
    return out


def crowded(PH, recs):
    """20섹터 중 CROWD 개 이상이 같은 라벨인 분기 — 그 라벨 섹터들의 성적."""
    idx = {(r["sec"], r["q"]): r for r in recs}
    qs = sorted(set(q for d in PH.values() for q in d))
    same, expand = [], []
    same_q, exp_q = set(), set()

    def row(q, secs, name, k, of):
        o = {"q": q, "label": name, "k": k, "of": of}
        for hk in HS:
            rr = [idx[(s, q)][hk] for s in secs if (s, q) in idx and hk in idx[(s, q)]]
            v = [x["eq"] for x in rr]
            vc = [x["cap"] for x in rr if x["cap"] is not None]
            o[hk] = {"n": len(v), "med": r1(med(v)), "med_cap": r1(med(vc)), "hit": r1(hit(v), 2),
                     "mkt": r1(rr[0]["mkt_mean"]) if rr else None, "mkt_cap": r1(rr[0]["mkt_cap"]) if rr else None,
                     "mkt_med": r1(rr[0]["mkt"]) if rr else None}
        return o

    for q in qs:
        labs = {s: PH[s][q][0] for s in PH if q in PH[s]}
        cnt = collections.Counter(labs.values())
        top, k = cnt.most_common(1)[0]
        if k >= CROWD:
            same_q.add(q)
            same.append(row(q, [s for s, l in labs.items() if l == top], top, k, len(labs)))
        ke = sum(1 for l in labs.values() if l in EXPAND)
        if ke >= CROWD:
            exp_q.add(q)
            expand.append(row(q, [s for s, l in labs.items() if l in EXPAND], "확장(가속+유지)", ke, len(labs)))

    def pooled(pred):
        o = {}
        for hk in HS:
            v = [r[hk]["eq"] for r in recs if hk in r and pred(r)]
            vc = [r[hk]["cap"] for r in recs if hk in r and r[hk]["cap"] is not None and pred(r)]
            o[hk] = {"n": len(v), "med": r1(med(v)), "med_cap": r1(med(vc)), "hit": r1(hit(v), 2)}
        return o

    crowd_lab = {x["q"]: x["label"] for x in same}
    pool = {
        "same_crowded": pooled(lambda r: r["q"] in same_q and r["label"] == crowd_lab[r["q"]]),
        "same_rest": pooled(lambda r: r["q"] not in same_q),
        "expand_crowded": pooled(lambda r: r["q"] in exp_q and r["label"] in EXPAND),
        "expand_scattered": pooled(lambda r: r["q"] not in exp_q and r["label"] in EXPAND),
    }
    last = qs[-1]
    now_labs = collections.Counter(PH[s][last][0] for s in PH if last in PH[s])
    now = {"q": last, "count": dict(now_labs), "expand": sum(v for l, v in now_labs.items() if l in EXPAND),
           "of": sum(now_labs.values())}
    return {"same": same, "expand": expand, "pooled": pool, "now": now}


# ---------------------------------------------------------------- 출력
def print_labels(T, title, hs=None):
    print("\n[%s]  n = 섹터-분기 · 중앙값 · 이긴%% · 90%% 구간(섹터 부트스트랩) · ~2019 / 2020~ 중앙값   (단위 %%p, 같은 가중의 시장 대비)" % title)
    head = pad("라벨", 10) + pad("기간", 5) + pad("n", 4, True) + "  " + pad("동일 중앙", 9, True) + pad("이긴%", 7, True) + pad("90% 구간", 16, True) + pad("~2019", 8, True) + pad("2020~", 8, True) + " | " + pad("시총 중앙", 9, True) + pad("이긴%", 7, True) + pad("90% 구간", 16, True) + pad("~2019", 8, True) + pad("2020~", 8, True)
    print(head)
    print("-" * wid(head))
    for lab in LABELS:
        for hk in (hs or HS):
            e, c = T[lab][hk]["eq"], T[lab][hk]["cap"]
            ci_e = "[%s, %s]" % (fmt(e["ci"][0]), fmt(e["ci"][1])) if e["ci"] else "—"
            ci_c = "[%s, %s]" % (fmt(c["ci"][0]), fmt(c["ci"][1])) if c["ci"] else "—"
            print(pad(lab if hk == (hs or list(HS))[0] else "", 10) + pad(hk[1:] + "개월", 5) + pad(e["n"], 4, True) + "  "
                  + pad(fmt(e["med"]), 9, True) + pad(fn(e["hit"], 0), 7, True) + pad(ci_e, 16, True) + pad(fmt(e["early"]), 8, True) + pad(fmt(e["late"]), 8, True)
                  + " | " + pad(fmt(c["med"]), 9, True) + pad(fn(c["hit"], 0), 7, True) + pad(ci_c, 16, True) + pad(fmt(c["early"]), 8, True) + pad(fmt(c["late"]), 8, True))


def print_contrast(C, name, hs=None):
    print("\n[대조] %s — 중앙값 차이(%%p)와 90%% 구간" % name)
    for hk in (hs or HS):
        for w in ("eq", "cap"):
            x = C[hk][w]
            ci = "[%s, %s]" % (fmt(x["ci"][0]), fmt(x["ci"][1])) if x["ci"] else "—"
            print("  %s %s  A n=%3d 중앙 %s 이긴 %s%%  B n=%3d 중앙 %s 이긴 %s%%  차이 %s  구간 %s"
                  % (pad(hk[1:] + "개월", 5), "동일" if w == "eq" else "시총", x["n_a"], fmt(x["med_a"]), fn(x["hit_a"], 0),
                     x["n_b"], fmt(x["med_b"]), fn(x["hit_b"], 0), fmt(x["diff"]), ci))


def print_transition(T):
    print("\n[전이표] 라벨(t) → 라벨(t+2분기)  건수(행 비율 %)")
    print(pad("t \\ t+2", 11) + "".join(pad(SHORT[b], 12, True) for b in LABELS) + pad("n", 6, True))
    for a in LABELS:
        r = T[a]
        print(pad(a, 11) + "".join(pad("%d(%s)" % (r["to"][b], fn(r["pct"][b], 0)), 12, True) for b in LABELS) + pad(r["n"], 6, True))


def print_sectors(S):
    print("\n[섹터] 지금 라벨(2026Q2 속도/가속) · 과거 그 라벨 n번의 12개월 초과수익 중앙값(동일 · 시총) · 라벨별 n/12개월 중앙값(동일)")
    head = pad("섹터", 12) + pad("지금", 10) + pad("속도", 8, True) + pad("가속", 8, True) + pad("n", 4, True) + pad("동일", 8, True) + pad("시총", 8, True) + " | " + "".join(pad(SHORT[l], 11, True) for l in LABELS)
    print(head)
    print("-" * wid(head))
    for sec, s in S.items():
        nh = s["now_hist"]
        cells = "".join(pad("%d/%s" % (s["by_label"][l]["n"], fmt(s["by_label"][l]["med"])) if l in s["by_label"] else "·", 11, True) for l in LABELS)
        print(pad(sec, 12) + pad(s["now"]["label"], 10) + pad(fmt(s["now"]["speed"]), 8, True) + pad(fmt(s["now"]["accel"]), 8, True)
              + pad(nh["n"], 4, True) + pad(fmt(nh["med"]), 8, True) + pad(fmt(nh.get("med_cap")), 8, True) + " | " + cells)


def print_crowded(C):
    now = C["now"]
    print("\n[쏠림] 20섹터 중 %d개 이상 같은 라벨인 분기 — 그 라벨 섹터들의 초과수익 중앙값(동일/시총, %%p) · 그날 시장 12개월 평균(동일 가중)" % CROWD)
    print("  지금 %s: %s → 확장(가속+유지) %d/%d" % (now["q"], ", ".join("%s %d" % (l, k) for l, k in sorted(now["count"].items(), key=lambda x: -x[1])), now["expand"], now["of"]))
    for name, rows in (("같은 라벨", C["same"]), ("확장 묶음", C["expand"])):
        print("  (%s)" % name)
        if not rows:
            print("    없음")
        for x in rows:
            print("    %s %s %2d/%d  3개월 %s/%s  6개월 %s/%s  12개월 %s/%s (n=%d, 시장 %s)"
                  % (x["q"], pad(x["label"], 12), x["k"], x["of"], fmt(x["h3"]["med"]), fmt(x["h3"]["med_cap"]), fmt(x["h6"]["med"]), fmt(x["h6"]["med_cap"]),
                     fmt(x["h12"]["med"]), fmt(x["h12"]["med_cap"]), x["h12"]["n"], fmt(x["h12"]["mkt"])))
    p = C["pooled"]
    print("  (모아서, 12개월 동일/시총 · 이긴%)")
    for k, nm in (("same_crowded", "같은 라벨 쏠린 분기의 그 라벨"), ("same_rest", "쏠리지 않은 분기 전부"),
                  ("expand_crowded", "확장 쏠린 분기의 확장"), ("expand_scattered", "확장 흩어진 분기의 확장")):
        x = p[k]["h12"]
        print("    %s n=%3d 중앙 %s / %s 이긴 %s%%" % (pad(nm, 28), x["n"], fmt(x["med"]), fmt(x["med_cap"]), fn(x["hit"], 0)))


def rounded(o):
    if isinstance(o, float):
        return round(o, 2)
    if isinstance(o, dict):
        return {k: rounded(v) for k, v in o.items()}
    if isinstance(o, list):
        return [rounded(v) for v in o]
    return o


# ---------------------------------------------------------------- 메인
def main():
    t0 = time.time()
    R = IND._load(os.path.join(DIR, "_result.json"))
    P = IND._load(os.path.join(DIR, "panel.json"))
    if not R or not P:
        print("_result.json / panel.json 이 없다 — 산업.py 를 먼저 돌려라")
        return 1
    PX = load_prices()
    CAL = calendar(PX)
    PH = phases(R)
    mem, seg = members(P)
    E = Engine(PX, CAL, P)
    print("시세 %d곳 · 거래일 %s~%s · 섹터 %d · 바구니 후보 %d곳(부문 회사 %d곳 제외) · %.0f초"
          % (len(PX), CAL[0], CAL[-1], len(PH), sum(len(v) for v in mem.values()), len(seg), time.time() - t0))

    recs = E.run(PH, mem, lag=0)
    firms_used = len(E.used)
    rng = random.Random(SEED)
    labels = label_table(recs, rng)
    contrasts = {
        "확장_vs_그밖": contrast(recs, rng, EXPAND, set(LABELS) - EXPAND),
        "확장가속_vs_둔화": contrast(recs, rng, {"확장 가속"}, {"둔화"}),
    }
    trans = transition(PH)
    secs = sector_table(PH, recs, mem)
    crowd = crowded(PH, recs)

    recs1 = E.run(PH, mem, lag=1)
    rng1 = random.Random(SEED)
    lag1 = {"labels": label_table(recs1, rng1),
            "contrasts": {"확장_vs_그밖": contrast(recs1, rng1, EXPAND, set(LABELS) - EXPAND),
                          "확장가속_vs_둔화": contrast(recs1, rng1, {"확장 가속"}, {"둔화"})},
            "n": {hk: sum(1 for r in recs1 if hk in r) for hk in HS},
            "to": {hk: max((r["q"] for r in recs1 if hk in r), default=None) for hk in HS}}

    n_by_h = {hk: sum(1 for r in recs if hk in r) for hk in HS}
    to = {hk: max((r["q"] for r in recs if hk in r), default=None) for hk in HS}
    qs_all = sorted(set(r["q"] for r in recs if any(hk in r for hk in HS)))
    out = {
        "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n": n_by_h["h12"], "n_by_h": n_by_h, "n_label_rows": sum(len(d) for d in PH.values()),
        "from": qs_all[0] if qs_all else None, "to": to,
        "firms_used": firms_used, "seg_excluded": len(seg), "seg_codes": seg,
        "members": {k: len(v) for k, v in mem.items()},
        "calendar": {"first": CAL[0], "last": CAL[-1], "n_price": len(PX)}, "snap": P["snap"],
        "params": {"h_days": HS, "min_members": MIN_MEMBERS, "boot": BOOT_N, "seed": SEED, "split": SPLIT, "crowd": CROWD,
                   "phase_band": IND.PHASE_BAND, "phase_flat": IND.PHASE_FLAT,
                   "deadline": {"Q1": "05-15", "Q2": "08-14", "Q3": "11-14", "Q4": "다음 해 03-31"}},
        "labels": labels, "contrasts": contrasts, "transition": trans, "sectors": secs,
        "lag1": lag1, "crowded": crowd,
        "notes": [
            "바구니도 기준도 지금 상장된 회사만(생존 편향) — 라벨끼리 견주는 차이는 덜 휜다",
            "재무는 정정 뒤 값 — 그때 알 수 있던 숫자와 다를 수 있다(라벨이 사후에 바뀌었을 수 있다)",
            "시총 가중은 2026-10-01 시총 스냅샷 × 주가 비(주식 수 고정 근사) — 증자 · 소각 · 상장폐지는 안 잡힌다",
            "12개월 구간이 분기마다 겹쳐 표본이 독립이 아니다 — 부트스트랩을 섹터 단위로 뽑아 일부만 보정",
            "2016~2026 은 경기 사이클 2~3번뿐 — 라벨당 수십 건이라 90% 구간이 넓다",
            "기준은 시세 캐시 988곳의 같은 통계(동일 가중 = 전 종목 평균, 시총 가중 = 전 종목 시총 가중 평균) — 코스피 지수와 다르다",
            "부문 회사(삼성전자 등 %d곳)는 바구니에서 뺐다 — 주가는 회사 전체라 부문 섹터에 못 붙인다" % len(seg),
            "구성원 5곳 미만인 섹터-분기는 뺐다(%s — 모든 분기에서 빠진다). 최근 분기(%s)는 보고서가 다 안 모였을 수 있다(_result.json 그대로)"
            % (" · ".join(k for k, v in mem.items() if len(v) < MIN_MEMBERS) or "없음", (crowd.get("now") or {}).get("q", "")),
        ],
    }
    os.makedirs(DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rounded(out), fh, ensure_ascii=False, indent=1)

    # ---- 표준출력
    print("라벨 행 %d(섹터-분기) · 수익 닫힌 표본 3개월 %d · 6개월 %d · 12개월 %d(~%s) · 바구니에 들어간 회사 %d곳"
          % (out["n_label_rows"], n_by_h["h3"], n_by_h["h6"], n_by_h["h12"], to["h12"], firms_used))
    print_labels(labels, "라벨 표 — 그 라벨을 알게 된 날 사서")
    print_contrast(contrasts["확장_vs_그밖"], "A 확장(가속+유지) vs B 그 밖")
    print_contrast(contrasts["확장가속_vs_둔화"], "A 확장 가속 vs B 둔화")
    print_transition(trans)
    print_sectors(secs)
    print_labels(lag1["labels"], "보수 판 — 라벨을 한 분기 늦게 안다고 보고(진입 = 다음 분기 마감 뒤)", hs=["h12"])
    print_contrast(lag1["contrasts"]["확장_vs_그밖"], "보수 판 · A 확장 vs B 그 밖", hs=["h12"])
    print_contrast(lag1["contrasts"]["확장가속_vs_둔화"], "보수 판 · A 확장 가속 vs B 둔화", hs=["h12"])
    print_crowded(crowd)
    print("\n[한계]")
    for s in out["notes"]:
        print("  · " + s)
    print("\n→ %s  (%.0f초)" % (OUT, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
