# -*- coding: utf-8 -*-
"""
보컬(김형준) 매매 순서를 일봉으로 — 거래대금 상위 → 강한 테마 → 테마 대장주 → 큰 상승 → 눌림 → 지지선에서 거래량 감소 →
거래대금 재유입 + 양봉 → 진입 (2026-10-08, docs/superpowers/specs/2026-10-08-vocal-design.md).

서버(/api/vocal)와 도구/보컬_백테스트.py 가 같은 함수를 부른다 — 화면과 검증의 정의가 어긋나지 않게.
유니버스 = 전 시장 보통주(네이버 시총 API 목록, 우선주 · ETF · ETN · 스팩 · 거래정지 제외). 시세 = 재무.fetch_ohlcv 일봉.
테마 = 업종.py 분류표(네이버 테마 264개). 숫자 문턱은 보컬 강의 통설로 먼저 고정했고 결과에 맞춰 바꾸지 않았다(MODES).
"""
import os
import re
import json
import time
import bisect
import statistics as st
import importlib.util as ilu

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache", "vocal")
LISTING = os.path.join(CACHE, "listing.json")
NAVER_MV = "https://m.stock.naver.com/api/stocks/marketValue/%s"
HEAD = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
CODE_RE = re.compile(r"^[0-9][0-9A-Z]{5}$")
PREF_RE = re.compile(r"\d*우B?$")

# 모드 — 단기(거래대금 50위) / 눌림목(150위). 괄호 안 설명은 설계 문서와 같다.
MODES = {
    "short": {"name": "단기", "top": 50, "gain": 0.40, "pull_lo": 0.05, "pull_hi": 0.25, "days_lo": 1, "days_hi": 7, "hold": 5},
    "pull": {"name": "눌림목", "top": 150, "gain": 0.30, "pull_lo": 0.08, "pull_hi": 0.35, "days_lo": 2, "days_hi": 15, "hold": 10},
}
POOL_DAYS = 30          # 풀 = 최근 30일 안 하루라도 순위 안
RALLY_WIN = 40          # 고점을 찾는 창
BASE_WIN = 60           # 고점 앞 바닥을 찾는 창
RISE_MAX = 20           # 바닥 마지막 터치 → 고점 봉 수
RETRACE_MAX = 0.80      # 상승 폭의 80% 넘게 되돌리면 눌림이 아니라 끝
TOUCH = 0.02            # 지지선 ±2% 안이면 닿음
HOLD_BELOW = 0.03       # 신호봉 저가가 지지선 −3% 안
DRY_PEAK = 0.40         # 앞 3봉 평균 거래량 ≤ 급등 최대봉의 40%
DRY_RALLY = 0.70        # … 이면서 상승 구간 평균의 70%
REFLOW = 1.5            # 거래대금이 앞 3봉 평균의 1.5배↑
BODY = 0.01             # 양봉 몸통 1%↑
RR_MIN = 1.5            # 손익비
GAP_SKIP = 0.15         # 다음 날 시가가 +15% 넘게 뜨면 못 산 것으로
THEME_RATIO = 2.0       # 테마 점유율이 20일 평균의 2배↑
THEME_MIN = 3           # 풀 안 멤버 3곳↑
THEME_TOP = 10          # 강한 테마 = 상위 10


def _fin():
    sp = ilu.spec_from_file_location("재무", os.path.join(BASE, "재무.py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- 전 시장 목록
def fetch_listing():
    """네이버 시총 API — KOSPI · KOSDAQ 전 종목. 보통주만 남긴다. {code: {name, market, cap(원), tv(원, 당일 거래대금), close, stop}}"""
    import requests
    out = {}
    for mk in ("KOSPI", "KOSDAQ"):
        page = 1
        while page < 60:
            r = requests.get(NAVER_MV % mk, timeout=30, headers=HEAD, params={"page": page, "pageSize": 100})
            r.raise_for_status()
            got = r.json().get("stocks") or []
            if not got:
                break
            for s in got:
                code = (s.get("itemCode") or "").strip().upper()
                name = (s.get("stockName") or "").strip()
                if not CODE_RE.match(code) or not name or s.get("stockEndType") != "stock":
                    continue
                if "스팩" in name or (PREF_RE.search(name) and not code.endswith("0")):
                    continue
                num = lambda k, mul: float(re.sub(r"[^\d.]", "", str(s.get(k) or "0")) or 0) * mul
                out[code] = {"name": name, "market": mk, "cap": num("marketValue", 1e8), "tv": num("accumulatedTradingValue", 1e6),
                             "close": num("closePrice", 1), "stop": (s.get("tradableStatus") or "") != "tradable"}
            if len(got) < 100:
                break
            page += 1
            time.sleep(0.12)
    if len(out) < 1500:
        raise RuntimeError("목록이 너무 적다 %d" % len(out))
    os.makedirs(CACHE, exist_ok=True)
    data = {"at": time.time(), "date": time.strftime("%Y%m%d"), "stocks": out}
    with open(LISTING, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return data


def load_listing(max_age=20 * 3600):
    try:
        with open(LISTING, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if time.time() - d.get("at", 0) < max_age:
            return d
    except Exception:
        pass
    try:
        return fetch_listing()
    except Exception:
        try:
            with open(LISTING, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None


def fetch_all_bars(codes, workers=4, progress=None, max_age=86400):
    """전 종목 일봉을 받아 둔다(재무.fetch_ohlcv 캐시). 처음 한 번 ~2,700곳 · 10~15분."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    F = _fin()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(F.fetch_ohlcv, c, "20100101", max_age): c for c in codes}
        for f in as_completed(futs):
            done += 1
            if progress and done % 100 == 0:
                progress(done, len(codes))


# ================================================================ 패널 — 전 종목 일봉 · 날짜별 거래대금 순위
def bars_from(d, min_n=60):
    if not d:
        return None
    ks = sorted(d)
    if len(ks) < min_n:
        return None
    B = {"d": [int(k) for k in ks], "o": [d[k][0] for k in ks], "h": [d[k][1] for k in ks], "l": [d[k][2] for k in ks],
         "c": [d[k][3] for k in ks], "v": [d[k][4] for k in ks]}
    B["tv"] = [c_ * v_ for c_, v_ in zip(B["c"], B["v"])]
    cs, vs, ts = [0.0], [0.0], [0.0]
    for c_, v_, t_ in zip(B["c"], B["v"], B["tv"]):
        cs.append(cs[-1] + c_)
        vs.append(vs[-1] + v_)
        ts.append(ts[-1] + t_)
    B["_cs"], B["_vs"], B["_ts"] = cs, vs, ts
    return B


def ma(B, j, n):
    return (B["_cs"][j + 1] - B["_cs"][j + 1 - n]) / n if j + 1 >= n else None


def _mean(a):
    return sum(a) / len(a) if a else None


class Panel:
    """전 종목 일봉. gd = 거래일(전 종목 합집합) 오름차순, gi = 그 안의 번호. 종목 안 번호(j)는 loc() 로 바꾼다."""

    def __init__(self, bars, names=None, themes=None):
        self.bars = {k: b for k, b in bars.items() if b}
        self.names = names or {}
        ds = set()
        for b in self.bars.values():
            ds.update(b["d"])
        self.gd = sorted(ds)
        self.gpos = {d: i for i, d in enumerate(self.gd)}
        self._tv = {}
        self._rank = {}
        # 테마 → 패널 안 멤버
        self.theme_of = {}
        self.members = {}
        for code, ths in (themes or {}).items():
            if code in self.bars and ths:
                self.theme_of[code] = list(ths)
                for t in ths:
                    self.members.setdefault(t, []).append(code)

    def precompute(self, top_max=150, progress=None):
        """검증용 — 날짜마다 테마 거래대금 합 · 시장 합 · 상위 top_max 순위를 한 번에 만든다(하루씩 bisect 하면 수천 번 × 2,600곳이라)."""
        D = len(self.gd)
        self._tsum = {t: [0.0] * D for t in self.members}
        self._tot = [0.0] * D
        for code, B in self.bars.items():
            ths = self.theme_of.get(code) or ()
            arrs = [self._tsum[t] for t in ths]
            gp = self.gpos
            for d, tv in zip(B["d"], B["tv"]):
                gi = gp[d]
                self._tot[gi] += tv
                for a in arrs:
                    a[gi] += tv
        self._top = [None] * D
        for gi in range(D):
            tv = self.tv_day(gi)
            order = sorted(tv, key=lambda k: -tv[k])[:top_max]
            self._top[gi] = {k: n + 1 for n, k in enumerate(order)}
            self._tv.pop(gi, None)
            if progress and gi % 500 == 0:
                progress(gi, D)
        self._top_max = top_max

    def loc(self, code, gi):
        """gi(전체 날짜 번호) → 그 종목의 봉 번호. 그날 봉이 없으면 None."""
        B = self.bars.get(code)
        if not B:
            return None
        d = self.gd[gi]
        j = bisect.bisect_left(B["d"], d)
        return j if j < len(B["d"]) and B["d"][j] == d else None

    def tv_day(self, gi):
        """그날 거래대금 {code: 원}."""
        if gi in self._tv:
            return self._tv[gi]
        d = self.gd[gi]
        out = {}
        for code, B in self.bars.items():
            j = bisect.bisect_left(B["d"], d)
            if j < len(B["d"]) and B["d"][j] == d:
                out[code] = B["tv"][j]
        if len(self._tv) > 400:
            self._tv.clear()
        self._tv[gi] = out
        return out

    def ranks(self, gi):
        """그날 거래대금 순위 {code: 1..}. precompute 뒤엔 상위 top_max 까지만(그 밖은 없음 = 순위 밖)."""
        if getattr(self, "_top", None) is not None:
            return self._top[gi]
        if gi in self._rank:
            return self._rank[gi]
        tv = self.tv_day(gi)
        order = sorted(tv, key=lambda k: -tv[k])
        r = {k: n + 1 for n, k in enumerate(order)}
        if len(self._rank) > 400:
            self._rank.clear()
        self._rank[gi] = r
        return r

    def pool(self, gi, top, days=POOL_DAYS):
        """최근 days 거래일 안 하루라도 top 안에 든 종목 → {code: 든 날 수}."""
        out = {}
        for k in range(max(0, gi - days + 1), gi + 1):
            for code, r in self.ranks(k).items():
                if r <= top:
                    out[code] = out.get(code, 0) + 1
        return out

    def in_rank(self, code, top):
        """code 가 어느 날짜에 top 안이었나 → 함수 date→bool (④ '상승 중 순위 안 2일↑')."""
        def f(d):
            gi = self.gpos.get(d)
            if gi is None:
                return False
            return self.ranks(gi).get(code, 10 ** 6) <= top
        return f

    # ---- 테마 거래대금 합(점유율) — 하루씩 미리 더해 둔다
    def theme_share(self, theme, gi):
        """테마 점유율(테마 거래대금 합 ÷ 시장 합) — precompute 가 있으면 배열에서, 없으면 그날 합을 세어서."""
        if getattr(self, "_tot", None) is not None:
            tot = self._tot[gi]
            return (self._tsum[theme][gi] / tot) if tot else 0.0
        sums, tot = self.theme_sums(gi)
        return (sums.get(theme, 0.0) / tot) if tot else 0.0

    def theme_sums(self, gi):
        """{theme: 거래대금 합}, 시장 합."""
        if gi in getattr(self, "_tsc", {}):
            return self._tsc[gi]
        tv = self.tv_day(gi)
        tot = sum(tv.values())
        out = {}
        for t, ms in self.members.items():
            s = 0.0
            for m in ms:
                x = tv.get(m)
                if x:
                    s += x
            out[t] = s
        if not hasattr(self, "_tsc"):
            self._tsc = {}
        if len(self._tsc) > 80:
            self._tsc.clear()
        self._tsc[gi] = (out, tot)
        return out, tot

    def ratio(self, theme, gi, n=20):
        """점유율 배수 — 오늘 ÷ 앞 n일 평균. 앞 n일이 없으면 None."""
        if gi < n:
            return None
        base = _mean([self.theme_share(theme, k) for k in range(gi - n, gi)])
        return (self.theme_share(theme, gi) / base) if base else None


# ================================================================ ② 강한 테마 · ③ 대장주
def theme_strength(P, gi, mode, pool=None):
    """테마마다 점유율 배수(오늘 ÷ 앞 20일 평균) · 멤버 5일 수익 중앙값 · 60일 신고가 멤버 수 → 순위 합. 상위 THEME_TOP = 강한 테마.
    돌려주는 것: [{theme, ratio, r5, nh, n, n_pool, score, start(gi)}] 강한 순."""
    M = MODES[mode]
    if pool is None:
        pool = P.pool(gi, M["top"])
    if gi < 20:
        return [], []
    rows = []
    for t, ms in P.members.items():
        if len(ms) < 2:
            continue
        ratio = P.ratio(t, gi)
        if ratio is None:
            continue
        n_pool = sum(1 for m in ms if m in pool)
        row = {"theme": t, "ratio": ratio, "n_pool": n_pool, "n": len(ms), "share": P.theme_share(t, gi) * 100, "r5": None, "nh": 0}
        row["strong"] = ratio >= THEME_RATIO and n_pool >= THEME_MIN
        rows.append(row)
        if not row["strong"]:
            continue                                  # 수익 · 신고가는 문턱을 넘은 테마만 센다(순위 합도 그들끼리)
        r5, nh, n = [], 0, 0
        for m in ms:
            j = P.loc(m, gi)
            B = P.bars[m]
            if j is None or j < 60:
                continue
            n += 1
            if m in pool:
                n_pool += 1
            if B["c"][j - 5] > 0:
                r5.append(B["c"][j] / B["c"][j - 5] - 1)
            if B["c"][j] >= max(B["h"][j - 59:j]):       # 오늘 고가를 넣으면 '고가 = 종가'인 날만 세게 된다
                nh += 1
        row.update(r5=st.median(r5) * 100 if r5 else None, nh=nh, n=n)
        if n < 2:
            row["strong"] = False
    # 순위 합(각 항목 큰 쪽이 1위) — 문턱을 넘은 테마끼리
    cand = [r for r in rows if r["strong"]]
    for key in ("ratio", "r5", "nh"):
        order = sorted((r for r in cand if r.get(key) is not None), key=lambda r: -r[key])
        rank, prev = 0, None
        for k, r in enumerate(order):                 # 같은 값은 같은 순위(신고가 0곳이 흔하다)
            if r[key] != prev:
                rank, prev = k + 1, r[key]
            r["_" + key] = rank
    for r in cand:
        r["score"] = sum(r.get("_" + k, len(cand)) for k in ("ratio", "r5", "nh"))
    rows.sort(key=lambda r: (not r["strong"], r.get("score", 10 ** 6), -r["ratio"]))
    strong = cand[:0] + sorted(cand, key=lambda r: r["score"])[:THEME_TOP]
    for r in strong:
        r["start"] = theme_start(P, r["theme"], gi)
    return strong, rows


def theme_start(P, theme, gi, days=POOL_DAYS):
    """테마가 움직이기 시작한 날(gi) — 오늘부터 거슬러 점유율 배수가 1.2 밑으로 식지 않은 구간 안에서 2배를 처음 넘은 날."""
    ratios = []
    for k in range(gi, max(0, gi - days) - 1, -1):
        r = P.ratio(theme, k)
        if r is None:
            break
        ratios.append((k, r))
    start = gi
    for k, r in ratios:
        if r < 1.2:
            break
        if r >= THEME_RATIO:
            start = k
    return start


def leaders(P, theme, start, gi):
    """테마 시작일부터 거래대금 합 1 · 2위 가운데 수익률도 테마 안 2위 안인 종목 → [대장, 부대장] (없으면 짧게)."""
    rows = []
    for m in P.members.get(theme, []):
        j, j0 = P.loc(m, gi), None
        B = P.bars[m]
        if j is None:
            continue
        s = bisect.bisect_left(B["d"], P.gd[start])
        if s >= len(B["d"]) or s > j:
            continue
        j0 = max(0, s - 1)
        tvs = B["_ts"][j + 1] - B["_ts"][s]
        ret = (B["c"][j] / B["c"][j0] - 1) * 100 if B["c"][j0] else None
        rows.append({"code": m, "tv_sum": tvs, "ret": ret, "tv": B["tv"][j]})
    if not rows:
        return []
    by_ret = sorted((r for r in rows if r["ret"] is not None), key=lambda r: -r["ret"])
    rank_ret = {r["code"]: k + 1 for k, r in enumerate(by_ret)}
    by_tv = sorted(rows, key=lambda r: -r["tv_sum"])
    out = []
    for r in by_tv[:2]:                              # 거래대금 합 1 · 2위만 — 돈이 안 몰린 종목은 수익률이 높아도 대장이 아니다
        r["ret_rank"] = rank_ret.get(r["code"])
        if r["ret_rank"] is not None and r["ret_rank"] <= 2:
            r["role"] = "대장" if not out else "부대장"
            out.append(r)
    return out


# ================================================================ ④~⑧ 종목 깔때기
def funnel(B, j, in_rank, mode):
    """j 번째 봉까지로 본 한 종목의 단계. in_rank(date)→bool 은 그날 거래대금 순위 안이었나(④).
    stage: 0 해당 없음 · 4 큰 상승 뒤 · 5 눌림 중 · 6 지지선에 닿고 거래량 마름 · 7 신호(재유입 + 양봉). 나머지는 근거 숫자."""
    M = MODES[mode]
    if j < BASE_WIN + 5:
        return None
    o, h, l, c, v, tv, d = B["o"], B["h"], B["l"], B["c"], B["v"], B["tv"], B["d"]
    w0 = max(0, j - RALLY_WIN + 1)
    seg = h[w0:j + 1]
    H = max(seg)
    hk = w0 + len(seg) - 1 - seg[::-1].index(H)
    if hk < BASE_WIN or H <= 0:                       # 고점 앞 60봉이 다 있어야 '바닥'을 잴 수 있다(상장 초엔 None)
        return None
    b0 = max(0, hk - BASE_WIN)
    base_lo = min(l[b0:hk]) if hk > b0 else None
    if not base_lo or base_lo <= 0:
        return None
    gain = H / base_lo - 1
    lk = max(k for k in range(b0, hk) if l[k] <= base_lo * 1.05)
    rise = hk - lk
    n_rank = sum(1 for k in range(lk, hk + 1) if in_rank(d[k]))
    out = {"H": H, "hk": str(d[hk]), "base_lo": base_lo, "lk": str(d[lk]), "gain": gain * 100, "rise": rise, "n_rank": n_rank,
           "stage": 0, "why": None}
    if gain < M["gain"]:
        out["why"] = "상승 %.0f%% < %.0f%%" % (gain * 100, M["gain"] * 100)
        return out
    if rise > RISE_MAX:
        out["why"] = "상승에 %d봉 — 급등 아님" % rise
        return out
    if n_rank < 2:
        out["why"] = "상승 중 거래대금 %d위 안 %d일" % (M["top"], n_rank)
        return out
    bk = lk + max(range(hk - lk + 1), key=lambda k: v[lk + k])
    out.update(bk=str(d[bk]), v_peak=v[bk], v_rally=_mean(v[lk:hk + 1]), stage=4)
    # ⑤ 눌림
    days = j - hk
    depth = 1 - c[j] / H
    depth_min = 1 - min(c[hk + 1:j + 1]) / H if j > hk else None     # 눌림 중 가장 낮은 종가 기준
    pl = min(l[hk + 1:j + 1]) if j > hk else None
    plk = hk + 1 + l[hk + 1:j + 1].index(pl) if pl is not None else None
    retrace = (H - pl) / (H - base_lo) if pl is not None and H > base_lo else None
    out.update(days=days, depth=depth * 100, depth_min=depth_min * 100 if depth_min is not None else None, pl=pl,
               pl_d=str(d[plk]) if plk is not None else None, retrace=retrace * 100 if retrace is not None else None)
    if days == 0:
        out["why"] = "오늘이 고점"
        return out
    if days > M["days_hi"]:
        out["stage"], out["why"] = 0, "고점 뒤 %d봉 — 눌림 기간 지남" % days
        return out
    if retrace is not None and retrace > RETRACE_MAX:
        out["stage"], out["why"] = 0, "상승 폭의 %.0f%% 되돌림 — 끝난 상승" % (retrace * 100)
        return out
    if depth > M["pull_hi"]:
        out["stage"], out["why"] = 0, "고점 대비 −%.0f%% — 눌림 넘어 하락" % (depth * 100)
        return out
    if days < M["days_lo"] or depth_min < M["pull_lo"]:
        out["why"] = "눌림 기다리는 중(%d봉 · −%.1f%%)" % (days, depth_min * 100)
        return out
    out["stage"] = 5
    # ⑥ 지지선 · 거래량 감소
    ma5, ma10, ma20 = ma(B, j, 5), ma(B, j, 10), ma(B, j, 20)
    box_hi = max(h[max(0, lk - BASE_WIN):lk]) if lk > 0 else None
    static = [("전고점", box_hi if box_hi and box_hi < H * 0.97 and box_hi > base_lo else None),
              ("급등봉 시가", o[bk]), ("급등봉 중간", (o[bk] + c[bk]) / 2), ("50% 되돌림", H - 0.5 * (H - base_lo))]
    levels = [("5일선", ma5), ("10일선", ma10), ("20일선", ma20)] + static
    levels = [(nm, lv) for nm, lv in levels if lv and lv > 0 and lv < H * 0.99]
    # '닿음'은 눌림 저점이 생긴 날의 선과 견준다(며칠 뒤 선이 움직여 있다) · '지킴'(⑦)은 오늘 선과
    at_pl = [("5일선", ma(B, plk, 5)), ("10일선", ma(B, plk, 10)), ("20일선", ma(B, plk, 20))] + static
    touched = [(nm, lv) for nm, lv in at_pl if lv and lv > 0 and lv < H * 0.99 and abs(pl / lv - 1) <= TOUCH]
    hold_lv = [lv for nm, lv in levels if nm in {t for t, _ in touched} and lv]
    prev3 = v[j - 3:j]                               # 앞 3봉(급등 봉이 섞이면 말랐을 리 없다 — 그게 맞다)
    now3 = v[j - 2:j + 1]
    dry = lambda seg_: bool(seg_) and _mean(seg_) <= DRY_PEAK * v[bk] and _mean(seg_) <= DRY_RALLY * out["v_rally"]
    dry_prev, dry_now = dry(prev3), dry(now3)
    out.update(levels=[(nm, lv, (pl / lv - 1) * 100) for nm, lv in levels], touched=[nm for nm, _ in touched],
               v_prev3=_mean(prev3), v_now3=_mean(now3), dry_prev=dry_prev, dry_now=dry_now,
               v_ratio_peak=(_mean(now3) / v[bk]) if now3 and v[bk] else None,
               v_ratio_rally=(_mean(now3) / out["v_rally"]) if now3 and out["v_rally"] else None)
    if touched and (dry_now or dry_prev):
        out["stage"] = 6
    # ⑦ 재유입 + 양봉
    tv_prev = _mean(tv[j - 3:j])
    reflow = tv_prev is not None and tv_prev > 0 and tv[j] >= REFLOW * tv_prev
    bull = c[j] > o[j] and (c[j] - o[j]) / o[j] >= BODY and c[j] >= c[j - 1]
    hold = any(l[j] >= lv * (1 - HOLD_BELOW) for lv in hold_lv)
    above5 = ma5 is not None and c[j] > ma5
    out.update(reflow=reflow, reflow_x=(tv[j] / tv_prev) if tv_prev else None, bull=bull, hold=hold, above5=above5)
    out["sig_nodry"] = bool(out["stage"] >= 5 and touched and reflow and bull and hold and above5)   # 검증용 — ⑥ 거래량 감소를 뺀 신호
    if out["sig_nodry"] and dry_prev:
        out["stage"] = 7
    # ⑧ 진입 · 손절 · 목표
    entry = c[j]
    out.update(entry=entry, stop=pl, target=H,
               rr=((H - entry) / (entry - pl)) if pl and entry > pl else None,
               stop_pct=(pl / entry - 1) * 100 if pl else None, target_pct=(H / entry - 1) * 100)
    if out["stage"] == 5:
        out["why"] = "지지선 " + ("닿음 · 거래량 아직" if touched else "아직 안 닿음(%s)" % ", ".join(nm for nm, _ in levels[:3]))
    elif out["stage"] == 6:
        miss = [k for k, ok in (("재유입", reflow), ("양봉", bull), ("지지 지킴", hold), ("5일선 위", above5), ("앞 3봉 마름", dry_prev)) if not ok]
        out["why"] = "신호 대기 — " + ("아직: " + " · ".join(miss) if miss else "")
    elif out["stage"] == 7:
        out["why"] = "신호 — " + ", ".join(out["touched"]) + " 지지 · 거래대금 %.1f배" % (out["reflow_x"] or 0)
    return out


# ================================================================ 하루치 계산(화면)
def day_leaders(P, gi, mode, pool=None):
    """그날 강한 테마와 대장주. → (strong, all_themes, lead_rows, lead_of{code: [(theme, role)]}, strong_set)"""
    strong, all_themes = theme_strength(P, gi, mode, pool)
    lead_rows, lead_of = [], {}
    for t in strong:
        for r in leaders(P, t["theme"], t["start"], gi):
            r.update(theme=t["theme"], start=str(P.gd[t["start"]]), name=P.names.get(r["code"], r["code"]))
            lead_rows.append(r)
            lead_of.setdefault(r["code"], []).append((t["theme"], r["role"]))
    for t in strong:
        t["start"] = str(P.gd[t["start"]])
    return strong, all_themes, lead_rows, lead_of, {t["theme"] for t in strong}


class LeadHistory:
    """날짜별 대장주 · 강한 테마를 기억한다 — 눌림 중엔 테마가 식어 '오늘 대장'일 수 없으니, 급등 구간(바닥~고점)에 대장이었나로 본다."""

    def __init__(self, P, mode):
        self.P, self.mode, self.cache = P, mode, {}

    def at(self, gi):
        if gi not in self.cache:
            if len(self.cache) > 200:
                self.cache.clear()
            _, _, _, lead_of, strong_set = day_leaders(self.P, gi, self.mode)
            self.cache[gi] = (lead_of, strong_set)
        return self.cache[gi]

    def during(self, code, d0, d1, themes):
        """d0~d1(날짜 정수) 사이 — [(theme, role, date)] 대장이었던 날들, 강한 테마 멤버였던 날 수."""
        g0, g1 = self.P.gpos.get(d0), self.P.gpos.get(d1)
        if g0 is None or g1 is None:
            return [], 0
        lead, n_theme = [], 0
        for k in range(g0, g1 + 1):
            lead_of, strong_set = self.at(k)
            for t, role in lead_of.get(code, ()):
                lead.append((t, role, str(self.P.gd[k])))
            if any(t in strong_set for t in themes):
                n_theme += 1
        return lead, n_theme


def run_day(P, gi, mode, listing=None, hist=None):
    M = MODES[mode]
    top = M["top"]
    ranks = P.ranks(gi)
    tv = P.tv_day(gi)
    pool = P.pool(gi, top)
    strong, all_themes, lead_rows, lead_of, strong_set = day_leaders(P, gi, mode, pool)
    hist = hist or LeadHistory(P, mode)
    hist.cache[gi] = (lead_of, strong_set)
    # ④~⑧ — 풀 전체를 재되, 급등 구간(바닥~오늘)에 강한 테마의 대장이었나를 붙인다
    fun = []
    for code in pool:
        j = P.loc(code, gi)
        if j is None:
            continue
        f = funnel(P.bars[code], j, P.in_rank(code, top), mode)
        if not f or f["stage"] < 4:
            continue
        ths = P.theme_of.get(code, [])
        lead, n_theme = hist.during(code, int(f["lk"]), P.gd[gi], ths)
        seen, lead_u = set(), []
        for t, role, d in lead:                     # 테마마다 처음 대장이 된 날 하나씩
            if (t, role) not in seen:
                seen.add((t, role))
                lead_u.append([t, role, d])
        f.update(code=code, name=P.names.get(code, code), rank=ranks.get(code), tv=tv.get(code), pool_days=pool[code],
                 themes=ths, lead=lead_u, lead_now=lead_of.get(code, []), n_theme_days=n_theme)
        fun.append(f)
    fun.sort(key=lambda f: (-f["stage"], not f["lead"], -(f.get("rr") or 0)))
    entries = [f for f in fun if f["stage"] == 7 and f["lead"] and (f.get("rr") or 0) >= RR_MIN]
    # ① 거래대금 상위 표
    stage_of = {f["code"]: f["stage"] for f in fun}
    top_rows = []
    for code, r in sorted(ranks.items(), key=lambda kv: kv[1])[:top]:
        B = P.bars[code]
        j = P.loc(code, gi)
        avg20 = (B["_ts"][j + 1] - B["_ts"][max(0, j - 19)]) / min(20, j + 1)
        top_rows.append({"rank": r, "code": code, "name": P.names.get(code, code), "tv": tv[code], "x20": tv[code] / avg20 if avg20 else None,
                         "chg": (B["c"][j] / B["c"][j - 1] - 1) * 100 if j and B["c"][j - 1] else None, "c": B["c"][j],
                         "themes": P.theme_of.get(code, []), "stage": stage_of.get(code, 0), "lead": lead_of.get(code, [])})
    return {"date": str(P.gd[gi]), "mode": mode, "top": top_rows, "themes": strong, "themes_all": all_themes[:40], "leaders": lead_rows,
            "funnel": fun, "entries": entries, "n_pool": len(pool), "n_univ": len(tv)}


def load_panel(codes, names=None, themes=None, min_n=60, drop=None, progress=None):
    """캐시된 일봉으로 패널. 네트워크 없음. drop = 뺄 날짜(장중에 받은 오늘 반쪽 봉)."""
    F = _fin()
    bars = {}
    for k, c in enumerate(codes, 1):
        p = os.path.join(F.OHLCV_DIR, c + ".json")
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if drop and drop in d:
                d = {kk: vv for kk, vv in d.items() if kk != drop}
            bars[c] = bars_from(d, min_n)
        except Exception:
            continue
        if progress and k % 200 == 0:
            progress(k, len(codes))
    return Panel(bars, names, themes)


# ================================================================ 잡주 거르기 — 재무(네이버 분기 요약) · 공시 위험(공시위험.json) (2026-10-08)
# 유니버스가 전 시장이라 DART 캐시(색인 988곳)로는 모자란다. 네이버 금융 분기 요약(ROE · 부채비율 · 분기 순이익, 종목당 호출 1번, 7일 캐시)과
# 공시위험.json(전 시장 — 도구/공시위험.py 가 매일 만든다)으로 거른다. 과거 검증에는 못 붙인다(그 시점 재무 · 공시 상태를 다시 세지 않았다).
FIN_DIR = os.path.join(CACHE, "fin")
NAVER_FIN = "https://m.stock.naver.com/api/stock/%s/finance/quarter"
DEBT_MAX = 200.0            # 부채비율 200%↑ 제외(저평가 등급과 같은 문턱)
LOSS_ROE = -10.0            # 최근 4분기 순손실이면서 ROE −10%↓ → 큰 적자
FUND_MIN = 2                # 24개월 안 CB · BW · 유상증자 · 제3자배정 공시가 서로 다른 날 2번↑ → 자금조달 잦음(공시위험의 '작전주 꼴' 3번보다 낮춘 문턱)
RISK_RED = ("상폐 절차", "보고서 없음", "작전주 꼴", "자금조달 잦음")
JUNK_REF = {"회생절차": "회생절차", "파산신청": "파산신청", "감사의견비적정": "감사의견 비적정", "관리종목_사유": "관리종목 지정 사유",
            "관리종목_우려": "관리종목 우려", "실질심사": "상장적격성 실질심사", "상폐우려": "상장폐지 우려", "자본잠식": "자본잠식"}
WARN_REF = {"횡령배임": "횡령 · 배임 혐의", "불성실_지정": "불성실공시", "보고서지연": "보고서 지연", "투자주의환기": "투자주의 환기"}
FUND_CATS = {"CB발행": "CB 발행", "BW발행": "BW 발행", "유상증자": "유상증자", "제3자배정": "제3자배정"}


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_fin(code, max_age=7 * 86400):
    """네이버 분기 재무 요약 → {q(마지막 실적 분기), roe(%, 최근 4분기 기준), debt(부채비율 %), ni4(최근 4분기 순이익 합, 억원), ni_q[4]}. 못 받으면 None."""
    os.makedirs(FIN_DIR, exist_ok=True)
    p = os.path.join(FIN_DIR, code + ".json")
    try:
        if time.time() - os.path.getmtime(p) < max_age:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except OSError:
        pass
    except Exception:
        pass
    try:
        import requests
        r = requests.get(NAVER_FIN % code, headers=HEAD, timeout=30)
        r.raise_for_status()
        fi = r.json().get("financeInfo") or {}
    except Exception:
        return None
    keys = [t["key"] for t in (fi.get("trTitleList") or []) if t.get("key") and t.get("isConsensus") != "Y"]
    rows = {(row.get("title") or "").strip(): row.get("columns") or {} for row in (fi.get("rowList") or [])}

    def col(title, k):
        return _num(((rows.get(title) or {}).get(k) or {}).get("value"))
    # 값이 있는 마지막 실적 분기
    last = None
    for k in reversed(keys):
        if col("당기순이익", k) is not None or col("ROE", k) is not None:
            last = k
            break
    out = {"q": None, "roe": None, "debt": None, "ni4": None, "ni_q": [], "at": time.time()}
    if last:
        i = keys.index(last)
        qs = keys[max(0, i - 3):i + 1]
        ni = [col("당기순이익", k) for k in qs]
        out.update(q=last[:4] + "." + last[4:], roe=col("ROE", last), debt=col("부채비율", last),
                   ni4=sum(x for x in ni if x is not None) if len(qs) == 4 and all(x is not None for x in ni) else None, ni_q=ni)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    time.sleep(0.1)
    return out


def fetch_fins(codes, workers=4, progress=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out, done = {}, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_fin, c): c for c in codes}
        for f in as_completed(futs):
            done += 1
            try:
                out[futs[f]] = f.result()
            except Exception:
                out[futs[f]] = None
            if progress and done % 50 == 0:
                progress(done, len(codes))
    return out


def junk_flags(code, fin, risk):
    """(제외 사유 목록, 참고 표시 목록). fin = fetch_fin 결과, risk = 공시위험.json 의 codes[code]."""
    junk, warn = [], []
    rk = risk or {}
    if rk.get("level") in RISK_RED:
        junk.append("공시 위험: " + rk["level"])
    fund = [(FUND_CATS[h["cat"]], h["days"]) for h in (rk.get("hits") or []) if h.get("cat") in FUND_CATS and (h.get("days") or 0) >= FUND_MIN]
    if fund and not any(j.startswith("공시 위험") for j in junk):
        junk.append("자금조달 잦음: " + " · ".join("%s %d번" % kv for kv in fund))
    for r in rk.get("ref") or []:
        c = r.get("cat")
        if c in JUNK_REF:
            junk.append(JUNK_REF[c])
        elif c in WARN_REF:
            warn.append(WARN_REF[c])
    f = fin or {}
    if f.get("debt") is not None and f["debt"] >= DEBT_MAX:
        junk.append("부채비율 %.0f%%" % f["debt"])
    if f.get("debt") is not None and f["debt"] < 0:
        junk.append("자본잠식(부채비율 음수)")
    if f.get("ni4") is not None and f["ni4"] < 0:
        if f.get("roe") is not None and f["roe"] <= LOSS_ROE:
            junk.append("큰 적자: 4분기 순이익 %s억 · ROE %.1f%%" % (format(int(round(f["ni4"])), ","), f["roe"]))
        else:
            warn.append("적자: 4분기 순이익 %s억" % format(int(round(f["ni4"])), ","))
    if not f:
        warn.append("재무 요약 없음")
    return junk, warn


def annotate(R, fins, risk):
    """run_day 결과에 재무 · 잡주 표시를 붙인다. ⑧ 후보에서 잡주를 뺀다(④~⑦ 표엔 남기고 표시 — 화면이 가린다)."""
    def mark(r):
        f = (fins or {}).get(r["code"])
        r["fin"] = {k: (f or {}).get(k) for k in ("q", "roe", "debt", "ni4")} if f else None
        r["junk"], r["warn_j"] = junk_flags(r["code"], f, (risk or {}).get(r["code"]))
    for key in ("top", "leaders", "funnel"):
        for r in R.get(key) or []:
            mark(r)
    R["n_junk_entries"] = sum(1 for f in R.get("entries") or [] if (f.get("junk") or []))
    R["entries"] = [f for f in R.get("entries") or [] if not f.get("junk")]
    return R


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if "--listing" in sys.argv:
        d = fetch_listing()
        print("목록 %d곳 (%s)" % (len(d["stocks"]), d["date"]))
    if "--fetch" in sys.argv:
        d = load_listing()
        fetch_all_bars(sorted(d["stocks"]), progress=lambda a, b: print("  일봉 %d/%d" % (a, b), flush=True))
        print("끝")
