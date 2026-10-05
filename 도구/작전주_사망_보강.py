# -*- coding: utf-8 -*-
"""
작전주 사망 검증 — 보강 (2026-10-06)

같은 폴더의 작전주_사망_검증.py(표본 · 신호 · 규칙)를 그대로 불러 쓰고, 반박 검증이 짚은 문제를 고쳐 숫자를 다시 낸다.
DART 호출 0 · 기존 파일 수정 0(작전주_사망_검증.py 의 FUND_RX 는 이 프로세스 안에서만 바꿔 끼운다).

고친 것
  [major] 구간이 회사 단위 재표본뿐이었다(해마다 기본 사망률 0.9~2.7% 출렁임 미반영)
          → 회사 · 해 · 회사×해(두 방향, 회사 무게 × 해 무게) 재표본 구간을 나란히 낸다. 헤드라인은 회사×해.
  [minor] FUND_RX 의 '리츠' 에 끝 고정이 없어 메리츠 3사 · 블리츠웨이가 리츠펀드로 빠졌다 → '리츠$' 로 고쳐 본표본을 다시 만든다.
  [minor] 상폐절차중(결론 안 남)을 사망으로 센 숫자뿐 → 보수판(절차중 = 생존) · 기대값판(절차중 × 결론 난 비슷한 사례의 사망 비율)
          · 엄격판(절차중 관측 제외)을 나란히.
  [minor] 관측(회사×기준일) 단위만 → 회사 단위 재현 · 사건까지 기간별(≤12개월 · 12~24개월) 재현.
  [minor] 해마다 재현을 규칙마다(최근 해에 약해지는지).
  [minor] '앞 · 뒤 lift 비슷' → 범주 전체 순위상관 · 1.5배 넘게 흔들린 범주 목록.
  [minor] '기준일 절차중 221 중 21%' → 기준일 공시로 절차중이 보이는 관측 전체(이미 사망 사슬에 든 172 포함)의 결말 · 거르기 전 전체 사망률 ·
          '사전 거르기 + 규칙' 전체 성적.
  [더함]  지금(자료끝) 규칙에 걸리는 회사 수 — 화면에 붙을 크기.

재현: python "G:/내 드라이브/Claude/주식/기업추적/도구/작전주_사망_보강.py"   (약 2~4분, seed 20261005 고정 → 매번 같은 숫자)
산출: .cache/공시목록/사망_검증_보강.json · 사망_검증_보강.md
"""
import collections
import datetime as dt
import json
import operator
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import 공시분류 as K  # noqa: E402
import 작전주_사망_검증 as S  # noqa: E402

FUND_OLD = S.FUND_RX
# '리츠' 끝 고정 + 이름 끝이 '리츠' 가 아닌 상장 리츠 둘(이리츠코크렙 · 맵스리얼티 — 옛 규칙은 앞의 것만 '리츠' 로 우연히 잡았다)
FUND_NEW = re.compile(FUND_OLD.pattern.replace("|리츠|", "|리츠$|이리츠코크렙|맵스리얼티|"))
assert FUND_NEW.pattern != FUND_OLD.pattern
S.FUND_RX = FUND_NEW                     # prepare() 가 모듈 전역으로 읽는다

OUT_JSON = os.path.join(K.DIR, "사망_검증_보강.json")
OUT_MD = os.path.join(K.DIR, "사망_검증_보강.md")
SELF = os.path.abspath(__file__).replace("\\", "/")
RUN = 'python "%s"' % SELF
SEED = S.SEED
NB = 1000
MODES = ("회사", "해", "회사×해")
PEND = "상폐절차중"
r4, div, pct, shift, ymd = S.r4, S.div, S.pct, S.shift, S.ymd


# ───────────────────────── 두 방향 재표본 ─────────────────────────
def _getter(idx):
    idx = list(idx)
    if not idx:
        return lambda w: 0
    if len(idx) == 1:
        i = idx[0]
        return lambda w: w[i]
    g = operator.itemgetter(*idx)
    return lambda w: sum(g(w))


def _vgetter(pairs):
    """[(회사 번호, 값)] → w ↦ Σ 값 × w[회사] (값이 0/1 이 아닌 기대값판도 받는다)"""
    by = collections.defaultdict(list)
    for i, v in pairs:
        if v:
            by[v].append(i)
    gs = [(v, _getter(ix)) for v, ix in by.items()]
    if not gs:
        return lambda w: 0
    return lambda w: sum(v * g(w) for v, g in gs)


class Boot2:
    """관측(회사 · 기준일) 재표본. 회사 무게(회사 복원추출 횟수) × 해 무게(기준일 복원추출 횟수).
    모드 '회사' = 해 무게 1(작전주_사망_검증.Boot 와 같은 뽑기 순서) · '해' = 회사 무게 1 · '회사×해' = 둘 다(pigeonhole bootstrap)."""

    def __init__(self, obs, ykey, B=NB, seed=SEED):
        self.ykey = ykey
        self.obs = [o for o in obs if o.get(ykey) is not None]
        ccs = sorted(set(o["cc"] for o in self.obs))
        self.ix = {c: i for i, c in enumerate(ccs)}
        self.ys = sorted(set(o["y"] for o in self.obs))
        NC, NY = len(ccs), len(self.ys)
        self.NC, self.NY = NC, NY
        rc = random.Random(seed)
        self.Wc = []
        for _ in range(B):
            w = [0] * NC
            for i in rc.choices(range(NC), k=NC):
                w[i] += 1
            self.Wc.append(w)
        ry = random.Random(seed + 1)
        self.Wy = []
        for _ in range(B):
            w = [0] * NY
            for i in ry.choices(range(NY), k=NY):
                w[i] += 1
            self.Wy.append(w)
        self.oc, self.oy = [1] * NC, [1] * NY
        self.byy = [[o for o in self.obs if o["y"] == y] for y in self.ys]
        self.g_all = [_getter(self.ix[o["cc"]] for o in L) for L in self.byy]
        self.g_dead = [_vgetter((self.ix[o["cc"]], o[ykey]) for o in L) for L in self.byy]
        self._base = {}

    def _w(self, mode, b):
        wc = self.Wc[b] if mode in ("회사", "회사×해") else self.oc
        wy = self.Wy[b] if mode in ("해", "회사×해") else self.oy
        return wc, wy

    def _bases(self, mode):
        if mode not in self._base:
            out = []
            for b in range(len(self.Wc)):
                wc, wy = self._w(mode, b)
                tn = sum(wy[j] * self.g_all[j](wc) for j in range(self.NY) if wy[j])
                td = sum(wy[j] * self.g_dead[j](wc) for j in range(self.NY) if wy[j])
                out.append((tn, td))
            self._base[mode] = out
        return self._base[mode]

    def run(self, flag=None):
        """flag 가 없으면 기본 사망률만. → {점추정 + 모드별 90% 구간}"""
        ky = self.ykey
        tn = len(self.obs)
        td = sum(o[ky] for o in self.obs)
        if flag is None:
            out = {"관측": tn, "사망": r4(td, 2), "회사": self.NC, "해": self.NY, "사망률": r4(div(td, tn), 5)}
            for mode in MODES:
                rs = [div(b, a) for a, b in self._bases(mode)]
                out["사망률_90_" + mode] = [r4(pct(rs, 0.05), 5), r4(pct(rs, 0.95), 5)]
            return out
        fl = [[o for o in L if flag(o)] for L in self.byy]
        g_fn = [_getter(self.ix[o["cc"]] for o in L) for L in fl]
        g_fd = [_vgetter((self.ix[o["cc"]], o[ky]) for o in L) for L in fl]
        Fn = sum(len(L) for L in fl)
        Fd = sum(o[ky] for L in fl for o in L)
        pt = S.metrics(Fn, Fd, tn, td)
        pt["걸린사망"] = r4(pt["걸린사망"], 2)
        pt["전체사망"] = r4(pt["전체사망"], 2)
        for mode in MODES:
            reps = []
            for b, (btn, btd) in enumerate(self._bases(mode)):
                wc, wy = self._w(mode, b)
                fn = sum(wy[j] * g_fn[j](wc) for j in range(self.NY) if wy[j])
                fd = sum(wy[j] * g_fd[j](wc) for j in range(self.NY) if wy[j])
                reps.append(S.metrics(fn, fd, btn, btd))
            for k in ("버리는비율", "재현율", "사망률", "lift", "남은사망률", "기본사망률"):
                pt[k + "_90_" + mode] = [r4(pct([r[k] for r in reps], 0.05), 5), r4(pct([r[k] for r in reps], 0.95), 5)]
        return pt


# ───────────────────────── 보조 ─────────────────────────
def add_variant_keys(obs, s_survive):
    """y24c/y12c = 보수판(절차중 = 생존 0), y24e/y12e = 기대값판(절차중 = 1 - 결론 난 비슷한 사례의 생존율)"""
    pe = round(1 - s_survive, 4)
    for o in obs:
        for k in ("y24", "y12"):
            v = o.get(k)
            if v is None:
                o[k + "c"] = None
                o[k + "e"] = None
                continue
            pend = bool(v) and o.get("Et") == PEND
            o[k + "c"] = 0 if pend else v
            o[k + "e"] = pe if pend else v
    return pe


def per_year(obs, years, flag, ky):
    out = {}
    for y in years:
        ty = [o for o in obs if o["y"] == y and o.get(ky) is not None]
        a = [o for o in ty if flag(o)]
        m = S.metrics(len(a), sum(o[ky] for o in a), len(ty), sum(o[ky] for o in ty))
        out[str(y)] = {k: (r4(v, 4) if isinstance(v, float) else v) for k, v in m.items()}
    return out


def unit_and_horizon(obs, years, flag, ky="y24"):
    """회사 단위 재현 · 사건까지 기간별 재현 · 걸린/놓친 사망의 사건까지 일수 중앙값"""
    te = [o for o in obs if o["y"] in years and o.get(ky)]
    by = collections.defaultdict(list)
    for o in te:
        by[o["cc"]].append(o)
    n = len(by)
    any_ = sum(1 for L in by.values() if any(flag(o) for o in L))
    last = sum(1 for L in by.values() if flag(max(L, key=lambda o: o["y"])))
    all_ = sum(1 for L in by.values() if all(flag(o) for o in L))
    conf = {cc: L for cc, L in by.items() if L[0]["Et"] != PEND}
    hz = {"≤12개월": [0, 0], "12~24개월": [0, 0]}
    dd_hit, dd_miss = [], []
    for o in te:
        days = (ymd(o["E"]) - ymd("%d0430" % o["y"])).days
        h = "≤12개월" if days <= 365 else "12~24개월"
        hz[h][0] += 1
        hz[h][1] += 1 if flag(o) else 0
        (dd_hit if flag(o) else dd_miss).append(days)
    return {
        "사망회사": n, "한번이라도걸림": any_, "한번이라도걸림_비율": r4(div(any_, n)),
        "마지막기준일에걸림": last, "마지막기준일에걸림_비율": r4(div(last, n)),
        "모든기준일에걸림": all_, "모든기준일에걸림_비율": r4(div(all_, n)),
        "확정사망회사만_한번이라도걸림_비율": r4(div(sum(1 for L in conf.values() if any(flag(o) for o in L)), len(conf))),
        "확정사망회사": len(conf),
        "사건까지기간별[사망관측,걸림,재현]": {k: [v[0], v[1], r4(div(v[1], v[0]))] for k, v in hz.items()},
        "사건까지일수_중앙값[걸린사망,놓친사망]": [pct(dd_hit, 0.5), pct(dd_miss, 0.5)],
    }


def spearman(a, b):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = rank(a), rank(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else None


def front_back(obs):
    """2015~2018 vs 2019~2024 기준일, 신호 24개월 ≥1, 사망 24개월 — 범주별 lift. 두 기간 합쳐 걸린 사망 ≥10 인 범주."""
    halves = {"앞": set(S.TRAIN), "뒤": set(S.TEST24)}
    base, cnt = {}, collections.defaultdict(lambda: {"앞": [0, 0], "뒤": [0, 0]})
    for h, ys in halves.items():
        sub = [o for o in obs if o["y"] in ys and o.get("y24") is not None]
        base[h] = div(sum(o["y24"] for o in sub), len(sub))
        for o in sub:
            for sid, c in o["s24"].items():
                if c >= 1:
                    cnt[sid][h][0] += 1
                    cnt[sid][h][1] += o["y24"]
    rows = []
    for sid, v in cnt.items():
        if v["앞"][1] + v["뒤"][1] < 10 or not v["앞"][0] or not v["뒤"][0]:
            continue
        la = div(div(v["앞"][1], v["앞"][0]), base["앞"])
        lb = div(div(v["뒤"][1], v["뒤"][0]), base["뒤"])
        rows.append({"신호": sid, "작전주꼴": sid in S.FAM_B, "앞[걸림,사망,lift]": [v["앞"][0], v["앞"][1], r4(la, 2)],
                     "뒤[걸림,사망,lift]": [v["뒤"][0], v["뒤"][1], r4(lb, 2)], "뒤/앞": r4(div(lb, la), 2) if la else None})
    rho = spearman([r["앞[걸림,사망,lift]"][2] for r in rows], [r["뒤[걸림,사망,lift]"][2] for r in rows])
    big = [r for r in rows if r["뒤/앞"] is None or r["뒤/앞"] > 1.5 or r["뒤/앞"] < 1 / 1.5]
    fb = [r for r in rows if r["작전주꼴"]]
    big_b = [r for r in fb if r["뒤/앞"] is None or r["뒤/앞"] > 1.5 or r["뒤/앞"] < 1 / 1.5]
    return {"범주수": len(rows), "스피어만": r4(rho, 3), "뒤/앞_중앙값": r4(pct([r["뒤/앞"] for r in rows if r["뒤/앞"]], 0.5), 2),
            "1.5배넘게다름": len(big), "1.5배넘게다름_목록": sorted(big, key=lambda r: -(r["앞[걸림,사망,lift]"][1] + r["뒤[걸림,사망,lift]"][1])),
            "작전주꼴범주수": len(fb), "작전주꼴_스피어만": r4(spearman([r["앞[걸림,사망,lift]"][2] for r in fb], [r["뒤[걸림,사망,lift]"][2] for r in fb]), 3),
            "작전주꼴_1.5배넘게다름": [r["신호"] for r in big_b], "표": sorted(rows, key=lambda r: r["신호"])}


def market_before(f, D):
    i = __import__("bisect").bisect_right(f["Id"], D)
    if i == 0:
        return None
    return collections.Counter(f["Im"][max(0, i - 5):i]).most_common(1)[0][0]


def survival_after_reason(info):
    """2019~2023 에 거래소 '상장폐지 사유 발생'(D_상폐사유) 공시가 나온 유가 · 코스닥 영업회사의 지금 결말.
    결론 난 곳(지금 상장중 = 살아남음, 사망 · 사망(약) · 사망(추정) = 죽음) 가운데 살아남은 비율 → 상폐절차중의 기대값 가중."""
    res = collections.Counter()
    lst = collections.defaultdict(list)
    for cc, f in info.items():
        if not f["code"] or f["spac_name"] or f["fund"] or f["foreign"]:
            continue
        ds = [d for d, s in f["ev"] if "D_상폐사유" in s and "20190101" <= d <= "20231231"]
        if not ds:
            continue
        mk = market_before(f, ds[0])
        if mk not in ("유가", "코스닥"):
            continue
        t = f["유형"]
        k = "살아남음" if t == "상장중" else "죽음" if t in S.DEATH_TYPES else "결론안남" if t == PEND else "기타(" + t + ")"
        res[k] += 1
        lst[k].append(f["name"])
    s = div(res["살아남음"], res["살아남음"] + res["죽음"])
    return s, {"결말": dict(res), "결론난곳중_살아남은비율": r4(s), "살아남은곳_예": sorted(lst["살아남음"])[:40],
               "정의": "2019-01-01~2023-12-31 에 D_상폐사유(공시분류) 공시가 나온 회사, 첫 사유 공시 직전 거래소공시 5건 시장 다수결이 유가 · 코스닥, "
                       "스팩 · 리츠펀드(고친 이름 규칙) · 외국 제외. 결말 = 공시분류.py 의 지금 판정."}


# ───────────────────────── 메인 ─────────────────────────
def main():
    t0 = time.time()
    rows = K.load_rows()
    data_end = max(r["rcept_dt"] for v in rows.values() for r in v)
    V = K.judge_all(rows, data_end)
    info = S.prepare(rows, V)
    old = S.load_old()
    # in_process_at 호출을 기록해 둔다(기준일에 절차중으로 뺀 관측을 다시 찾으려고)
    id2cc = {id(f): cc for cc, f in info.items()}
    ipa_log = {}
    _ipa = S.in_process_at

    def ipa(f, D):
        r = _ipa(f, D)
        ipa_log[(id2cc[id(f)], D)] = r
        return r
    S.in_process_at = ipa
    panel, excl, _ = S.build_panel(info, old)
    S.in_process_at = _ipa
    print("표본 %.0fs  관측 %d" % (time.time() - t0, len(panel)))
    inc = [o for o in panel if not o["excluded"]]
    main_obs = [o for o in inc if o["grp"] == "본표본"]

    # 0) 리츠 이름 규칙 고친 효과
    mv = [o for o in main_obs if FUND_OLD.search(info[o["cc"]]["name"])]
    moved = sorted(set(info[o["cc"]]["name"] for o in mv))
    added = sorted(set(f["name"] for f in info.values() if FUND_NEW.search(f["name"]) and not FUND_OLD.search(f["name"])))
    fund_fix = {"옛 규칙": FUND_OLD.pattern, "고친 규칙": FUND_NEW.pattern, "리츠펀드에서_본표본으로_옮긴_회사": moved,
                "본표본에서_리츠펀드로_옮긴_회사": added,
                "옮긴_관측(본표본, 2015~2025)": len(mv), "그중_2015~2024": sum(1 for o in mv if o["y"] <= 2024),
                "그중_24개월사망": sum(o["y24"] or 0 for o in mv)}

    # 1) 상폐절차중 기대값 가중
    s_surv, surv = survival_after_reason(info)
    pe = add_variant_keys(main_obs, s_surv)

    # 2) 규칙 다시 고르기(학습 2015~2018) — 고친 표본에서도 같은 규칙이 나오는지
    r_cb24, ch_cb24 = S.greedy_rule(main_obs, S.FAM_B, "s24", "y24", S.TRAIN, S.TEST24, "C_B 24", info)
    r_ca24, ch_ca24 = S.greedy_rule(main_obs, S.FAM_A, "s24", "y24", S.TRAIN, S.TEST24, "C_A 24", info)
    r_cb12, ch_cb12 = S.greedy_rule(main_obs, S.FAM_B, "s12", "y12", S.TRAIN, S.TEST12, "C_B 12", info)
    chB24, _ = S.select_categories(main_obs, S.FAM_B, "s24", "y24")
    chA24, _ = S.select_categories(main_obs, S.FAM_A, "s24", "y24")
    rB24 = S.evaluate_rule(main_obs, chB24, "s24", "y24", S.TRAIN, S.TEST24, "B 24", info)
    rA24 = S.evaluate_rule(main_obs, chA24, "s24", "y24", S.TRAIN, S.TEST24, "A 24", info)
    kB = {op["예산(학습기간 버리는비율 상한)"]: op["문턱(점수≥)"] for op in rB24["운영점"]}
    kA = {op["예산(학습기간 버리는비율 상한)"]: op["문턱(점수≥)"] for op in rA24["운영점"]}
    print("규칙 %.0fs  C_B24=%s" % (time.time() - t0, ch_cb24))

    def orf(ch, sk):
        return lambda o: any(o[sk].get(s, 0) >= t for s, t in ch)

    def scf(ch, k, sk="s24"):
        return lambda o: S.score_of(o, ch, sk) >= k

    fCB24, fCA24, fCB12 = orf(ch_cb24, "s24"), orf(ch_ca24, "s24"), orf(ch_cb12, "s12")
    fCBn = lambda o: fCB24(o) and o["s24"].get("현금배당", 0) < 1
    rules = [
        ("C_B(짧은 규칙, 작전주 꼴 OR)", fCB24, "24", S.TEST24, "학습 2015~2018 탐욕 선택: " + " · ".join("%s ≥%d날" % x for x in ch_cb24)),
        ("C_B·배당없음(강)", fCBn, "24", S.TEST24, "C_B 에 걸리고 24개월 안 현금배당 공시가 없음 — 배당으로 나누기는 이번 보강에서 더함(학습기간에서도 같은 방향, 6절)"),
        ("B 점수≥%d(예산 10%%)" % kB[0.10], scf(chB24, kB[0.10]), "24", S.TEST24, "작전주 꼴 %d범주" % len(chB24)),
        ("B 점수≥%d(예산 20%%)" % kB[0.20], scf(chB24, kB[0.20]), "24", S.TEST24, "작전주 꼴 %d범주" % len(chB24)),
        ("B 점수≥%d(예산 5%%)" % kB[0.05], scf(chB24, kB[0.05]), "24", S.TEST24, "작전주 꼴 %d범주" % len(chB24)),
        ("A 점수≥%d(예산 10%%)" % kA[0.10], scf(chA24, kA[0.10]), "24", S.TEST24, "부실 · 거래소 조치 포함 %d범주" % len(chA24)),
        ("C_A(짧은 규칙, 부실 포함 OR)", fCA24, "24", S.TEST24, " · ".join("%s ≥%d날" % x for x in ch_ca24)),
        ("C_B ∪ C_A(참고: 표본 밖을 본 뒤 묶음)", lambda o: fCB24(o) or fCA24(o), "24", S.TEST24, "두 학습 규칙의 합집합"),
        ("C_B 12개월판", fCB12, "12", S.TEST12, " · ".join("%s ≥%d날" % x for x in ch_cb12)),
    ]

    # 3) 기본 사망률 — 세 가지 구간, 네 가지 사건 정의
    Y24 = S.Y24
    base = {}
    for nm, ky in (("기본(절차중=사망)", "y24"), ("보수(절차중=생존)", "y24c"), ("기대값(절차중×%.2f)" % pe, "y24e"), ("엄격(절차중·약·추정 관측 제외)", "y24s")):
        base["24개월 · " + nm] = Boot2([o for o in main_obs if o["y"] in Y24], ky).run()
        base["24개월 · " + nm]["표본밖(2019~2024)"] = Boot2([o for o in main_obs if o["y"] in S.TEST24], ky).run()
    base["12개월 · 기본(절차중=사망)"] = Boot2(main_obs, "y12").run()
    yrs = {}
    for y in S.YEARS:
        oy = [o for o in main_obs if o["y"] == y]
        yrs[str(y)] = {"관측": len(oy)}
        for ky in ("y24", "y24c", "y24e", "y12", "y12c"):
            ss = [o for o in oy if o.get(ky) is not None]
            yrs[str(y)][ky] = [r4(sum(o[ky] for o in ss), 2), r4(div(sum(o[ky] for o in ss), len(ss)), 5)] if ss else None
    chi = None
    ys = [o for o in main_obs if o["y"] in Y24]
    p0 = div(sum(o["y24"] for o in ys), len(ys))
    chi = 0.0
    for y in Y24:
        oy = [o for o in ys if o["y"] == y]
        n, d = len(oy), sum(o["y24"] for o in oy)
        e = n * p0
        chi += (d - e) ** 2 / e + ((n - d) - (n - e)) ** 2 / (n - e)
    print("기본 %.0fs" % (time.time() - t0))

    # 4) 규칙별 표본 밖 — 구간 3종 × 사건 정의 4종, 해마다
    R = {}
    for nm, flag, h, years, desc in rules:
        ky0 = "y" + h
        sub = [o for o in main_obs if o["y"] in years]
        x = {"설명": desc, "표본밖기간": "%d~%d" % (years[0], years[-1])}
        for vn, ky in (("기본", ky0), ("보수(절차중=생존)", ky0 + "c"), ("기대값", ky0 + "e"), ("엄격", ky0 + "s")):
            x[vn] = Boot2(sub, ky).run(flag)
        x["해마다_기본"] = per_year(sub, years, flag, ky0)
        x["해마다_보수"] = per_year(sub, years, flag, ky0 + "c")
        x["시장별_기본"] = {mk: S.metrics(sum(1 for o in sub if o["mk"] == mk and flag(o)),
                                        sum(o[ky0] for o in sub if o["mk"] == mk and flag(o)),
                                        sum(1 for o in sub if o["mk"] == mk), sum(o[ky0] for o in sub if o["mk"] == mk)) for mk in ("유가", "코스닥")}
        x["시장별_보수"] = {mk: S.metrics(sum(1 for o in sub if o["mk"] == mk and flag(o)),
                                        sum(o[ky0 + "c"] for o in sub if o["mk"] == mk and flag(o)),
                                        sum(1 for o in sub if o["mk"] == mk), sum(o[ky0 + "c"] for o in sub if o["mk"] == mk)) for mk in ("유가", "코스닥")}
        if h == "24":
            x["회사단위·기간별"] = unit_and_horizon(main_obs, years, flag)
            x["2020~2024만"] = Boot2([o for o in sub if o["y"] >= 2020], ky0).run(flag)
        R[nm] = x
        print("  %s %.0fs" % (nm, time.time() - t0))

    # 5) 앞 · 뒤 lift
    fb = front_back(main_obs)

    # 6) 기준일에 이미 '죽는 중' 인 관측 — 거르기 전 전체와 사전 거르기 + C_B
    pre = []
    for y in Y24:
        D = "%d0430" % y
        D24, Dm13 = shift(D, 24), shift(D, -13)
        for cc, f in info.items():
            if not f["code"]:
                continue
            iI = __import__("bisect").bisect_right(f["Id"], D)
            if iI == 0 or (f["end"] and f["end"] < D):
                continue
            mk = collections.Counter(f["Im"][max(0, iI - 5):iI]).most_common(1)[0][0]
            spac = f["spac_name"] or (f["spac_end"] is not None and D <= f["spac_end"])
            if spac or f["fund"] or f["foreign"] or mk == "코넥스":
                continue
            E = f["E"]
            a_ok = any(Dm13 < a <= D for a in f["A"])
            if not a_ok:
                why = "사업보고서없음"
                vis = None
            elif E and E <= D:
                why = "이미사망"
                vis = _ipa(f, D)
            else:
                p = ipa_log.get((cc, D), "없음")
                if p == "없음":
                    p = _ipa(f, D)
                if not p:
                    continue
                why, vis = "절차중", p
            y24 = 1 if (E and D < E <= D24) else 0
            pre.append({"cc": cc, "y": y, "why": why, "vis": bool(vis), "y24": y24, "유형": f["유형"], "E": E, "Et": f["Et"]})
    pc = collections.Counter((p["why"], p["vis"]) for p in pre)
    already = [p for p in pre if p["why"] == "이미사망"]
    proc = [p for p in pre if p["why"] == "절차중"]
    nobiz = [p for p in pre if p["why"] == "사업보고서없음"]
    seen = [p for p in already if p["vis"]] + proc
    seen_dead = sum(1 for p in already if p["vis"]) + sum(p["y24"] for p in proc)
    seen_dead_conf = sum(1 for p in already if p["vis"] and p["Et"] != PEND) + sum(1 for p in proc if p["y24"] and p["Et"] != PEND)
    nm24 = len([o for o in main_obs if o["y"] in Y24])
    dm24 = sum(o["y24"] for o in main_obs if o["y"] in Y24)
    alln = nm24 + len(pre)
    alld = dm24 + len(already) + sum(p["y24"] for p in proc) + sum(p["y24"] for p in nobiz)
    prefilter = {
        "정의": "2015~2024 기준일, 유가 · 코스닥 영업회사 후보 가운데 본표본에서 뺀 것. 이미사망 = 마지막 사망 사슬의 첫 결정적 사건이 기준일 전"
                "(그날은 아직 상장 중). 절차중 = 기준일까지의 공시만으로 상폐절차중 규칙에 걸림(그 뒤 해소된 곳 포함). 보임 = 기준일까지의 공시만으로 절차중이 보이나.",
        "이미사망[관측,기준일에보임]": [len(already), sum(1 for p in already if p["vis"])],
        "이미사망_지금판정": dict(collections.Counter(p["유형"] for p in already)),
        "절차중[관측,24개월안다시사망]": [len(proc), sum(p["y24"] for p in proc)],
        "절차중_지금판정": dict(collections.Counter(p["유형"] for p in proc)),
        "사업보고서없음[관측,24개월사망]": [len(nobiz), sum(p["y24"] for p in nobiz)],
        "기준일에_절차중으로_보이는_관측": len(seen),
        "그중_사망사슬로끝남(이미사망 보임 + 24개월안 사망)": seen_dead,
        "비율": r4(div(seen_dead, len(seen))),
        "비율_보수(결론안난 절차중 제외하고 확정 사망만)": r4(div(seen_dead_conf, len(seen))),
        "거르기전_전체_24개월사망률": r4(div(alld, alln), 5),
        "거르기전_전체[관측,사망]": [alln, alld],
        "본표본_24개월사망률": r4(div(dm24, nm24), 5),
    }
    # 사전 거르기(절차중 보임 · 사업보고서 없음) + C_B — 표본 밖 2019~2024, 거르기 전 전체 후보에서
    te_main = [o for o in main_obs if o["y"] in S.TEST24]
    te_pre = [p for p in pre if p["y"] in S.TEST24]
    U_n = len(te_main) + len(te_pre)
    pre_flag = [p for p in te_pre if p["why"] != "이미사망" or p["vis"]]
    pre_dead = lambda p, cons=False: (1 if p["why"] == "이미사망" else p["y24"]) * (0 if (cons and p["Et"] == PEND) else 1)
    for rn, rf in (("C_B", fCB24), ("C_B·배당없음", fCBn)):
        for cons in (False, True):
            key = "y24c" if cons else "y24"
            U_d = sum(o[key] for o in te_main) + sum(pre_dead(p, cons) for p in te_pre)
            F_n = len(pre_flag) + sum(1 for o in te_main if rf(o))
            F_d = sum(pre_dead(p, cons) for p in pre_flag) + sum(o[key] for o in te_main if rf(o))
            prefilter["사전거르기+%s_표본밖(2019~2024)" % rn + ("_보수" if cons else "")] = S.metrics(F_n, F_d, U_n, U_d)
    prefilter["사전거르기만_표본밖(2019~2024)[버림관측,그중사망]"] = [len(pre_flag), sum(pre_dead(p) for p in pre_flag), U_n]
    print("사전거르기 %.0fs" % (time.time() - t0))

    # 6-2) C_B 에 걸린 쪽 나누기 — 화면에서 '걸림' 을 한 묶음으로 말해도 되나(학습 · 표본 밖 둘 다)
    def nhit(o):
        return sum(1 for s_, t in ch_cb24 if o["s24"].get(s_, 0) >= t)

    def divi(o):
        return o["s24"].get("현금배당", 0) >= 1

    def cell(lst, ky):
        lst = [o for o in lst if o.get(ky) is not None]
        n, d = len(lst), sum(o[ky] for o in lst)
        return [n, r4(d, 2), r4(div(d, n), 4)]

    split = {"열": "[관측, 사망, 사망률]", "정의": "C_B 걸림 관측을 '24개월 안 현금배당 공시 있음/없음' · '걸린 조건 수' 로 나눔. 기본(절차중=사망) · 보수(절차중=생존)."}
    for per, ys_ in (("학습 2015~2018", S.TRAIN), ("표본밖 2019~2024", S.TEST24)):
        sub = [o for o in main_obs if o["y"] in ys_ and fCB24(o)]
        allsub = [o for o in main_obs if o["y"] in ys_]
        x = {}
        for ky, kn in (("y24", "기본"), ("y24c", "보수")):
            x[kn] = {
                "전체(기본률)": cell(allsub, ky),
                "C_B 걸림": cell(sub, ky),
                "걸림·배당없음": cell([o for o in sub if not divi(o)], ky),
                "걸림·배당있음": cell([o for o in sub if divi(o)], ky),
                "걸림·조건1개": cell([o for o in sub if nhit(o) == 1], ky),
                "걸림·조건2개+": cell([o for o in sub if nhit(o) >= 2], ky),
                "걸림·조건1개·배당있음": cell([o for o in sub if nhit(o) == 1 and divi(o)], ky),
                "걸림·배당없음·금전대여만": cell([o for o in sub if nhit(o) == 1 and not divi(o) and o["s24"].get("금전대여", 0) >= 3], ky),
                "걸림·배당없음·조건1개": cell([o for o in sub if nhit(o) == 1 and not divi(o)], ky),
                "걸림·배당없음·조건2개+": cell([o for o in sub if nhit(o) >= 2 and not divi(o)], ky),
                "안걸림·배당없음": cell([o for o in allsub if not fCB24(o) and not divi(o)], ky),
                "안걸림·배당있음": cell([o for o in allsub if not fCB24(o) and divi(o)], ky),
            }
            x[kn]["조건별(걸린 관측 · 사망 · 사망률 · 그 조건만 걸린 관측 · 사망)"] = {
                "%s ≥%d날" % (s_, t): cell([o for o in sub if o["s24"].get(s_, 0) >= t], ky)
                + cell([o for o in sub if o["s24"].get(s_, 0) >= t and nhit(o) == 1], ky)[:2] for s_, t in ch_cb24}
        split[per] = x
    # 배당 있음 쪽의 사망 수가 적어 구간이 넓으니 회사×해 재표본으로 사망률 구간
    te24 = [o for o in main_obs if o["y"] in S.TEST24]
    for nm, fl in (("걸림·배당없음", lambda o: fCB24(o) and not divi(o)), ("걸림·배당있음", lambda o: fCB24(o) and divi(o))):
        m = Boot2(te24, "y24").run(fl)
        split["표본밖 2019~2024"]["기본"][nm + "_사망률_90_회사×해"] = m["사망률_90_회사×해"]
        split["표본밖 2019~2024"]["기본"][nm + "_재현율"] = m["재현율"]
        split["표본밖 2019~2024"]["기본"][nm + "_버림"] = m["버리는비율"]
    print("나누기 %.0fs" % (time.time() - t0))

    # 7) 지금(자료끝) 걸리는 회사
    D = data_end
    Dm24, Dm13 = shift(D, -24), shift(D, -13)
    now = collections.Counter()
    now_old = collections.Counter()
    flagged_old = []
    for cc, f in info.items():
        if not f["code"] or f["유형"] not in ("상장중", PEND):
            continue
        mk = market_before(f, D)
        if mk is None:
            continue
        grp = ("스팩" if f["spac_name"] or (f["spac_end"] and D <= f["spac_end"]) else "리츠펀드" if f["fund"] else
               "외국" if f["foreign"] else "코넥스" if mk == "코넥스" else "본표본")
        isold = f["code"] in old
        if grp != "본표본":
            now[grp] += 1
            now_old[grp] += isold
            continue
        a_ok = any(Dm13 < a <= D for a in f["A"])
        if _ipa(f, D):
            st = "①상폐절차중(공시로 보임)"
        elif not a_ok:
            st = "②사업보고서 13개월 미제출"
        else:
            o = {"s24": S.count_signals(f, Dm24, D)}
            if fCB24(o):
                st = "③작전주 꼴(C_B)·" + ("배당있음" if divi(o) else "배당없음")
                if isold:
                    hit = [("%s ≥%d날(%d)" % (s, t, o["s24"].get(s, 0))) for s, t in ch_cb24 if o["s24"].get(s, 0) >= t]
                    flagged_old.append([f["name"], f["code"], mk, hit, "배당있음" if divi(o) else "배당없음"])
            else:
                st = "④걸리지 않음"
        now[st] += 1
        now[st + "·" + mk] += 1
        now_old[st] += isold
    nowres = {"기준일": D, "전체": dict(sorted(now.items())), "종목txt안": dict(sorted(now_old.items())),
              "종목txt안_C_B걸림_목록": sorted(flagged_old, key=lambda x: x[1])}
    print("지금 %.0fs" % (time.time() - t0))

    res = {
        "만든때": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "자료끝": data_end,
        "재현": RUN + "  (DART 호출 0, seed %d, 회사 · 해 재표본 %d번)" % (SEED, NB),
        "고친것": __doc__.split("고친 것")[1].split("재현:")[0].strip(),
        "리츠규칙": fund_fix,
        "상폐절차중_가중": {"기대값판_가중(1-생존율)": pe, **surv},
        "규칙_다시고르기": {"C_B_24": ["%s ≥%d날" % x for x in ch_cb24], "C_A_24": ["%s ≥%d날" % x for x in ch_ca24],
                       "C_B_12": ["%s ≥%d날" % x for x in ch_cb12], "B_범주": chB24, "B_문턱": {str(k): v for k, v in kB.items()},
                       "A_범주수": len(chA24), "A_문턱": {str(k): v for k, v in kA.items()},
                       "C_B_24_학습단계": r_cb24["학습단계"]},
        "기본사망률": base,
        "기본사망률_해마다[사망,사망률]": yrs,
        "해마다_이질성_카이제곱(df=9)": r4(chi, 1),
        "규칙_표본밖": R,
        "앞뒤_lift": fb,
        "사전거르기": prefilter,
        "C_B걸린쪽_나누기": split,
        "지금": nowres,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(render_md(res))
    print("저장 %s %s %.0fs" % (OUT_JSON, OUT_MD, time.time() - t0))
    return res


# ───────────────────────── 요약 MD ─────────────────────────
P, F = S.P, S.F


def ci(m, k, mode, d=1):
    v = m.get(k + "_90_" + mode)
    if not v or v[0] is None:
        return "–"
    if k == "lift":
        return "%.1f~%.1f" % (v[0], v[1])
    return "%s~%s" % (P(v[0], d), P(v[1], d))


def render_md(R):
    L = []
    a = L.append
    a("# 작전주 사망 검증 — 보강(구간 · 절차중 · 단위 · 사전 거르기)")
    a("")
    a("만든 때 %s · 자료끝 %s · DART 호출 0 · 재현: `%s`" % (R["만든때"], R["자료끝"], R["재현"]))
    a("")
    a("본 연구: `사망_검증.md`(작전주_사망_검증.py). 이 파일은 반박 검증이 짚은 것을 고쳐 다시 잰 숫자다. 고친 것:")
    a("")
    for line in R["고친것"].splitlines():
        a("    " + line.strip())
    a("")
    ff = R["리츠규칙"]
    a("## 1. 리츠 이름 규칙")
    a("")
    a("- '%s' → '%s'. 본표본으로 옮긴 회사: %s(관측 %d, 2015~2024 %d, 그중 24개월 사망 %d). 리츠펀드로 옮긴 회사: %s." % (
        ff["옛 규칙"], ff["고친 규칙"], ", ".join(ff["리츠펀드에서_본표본으로_옮긴_회사"]), ff["옮긴_관측(본표본, 2015~2025)"], ff["그중_2015~2024"], ff["그중_24개월사망"],
        ", ".join(ff["본표본에서_리츠펀드로_옮긴_회사"]) or "없음"))
    rg = R["규칙_다시고르기"]
    a("- 고친 표본으로 학습(2015~2018)을 다시 돌린 짧은 규칙 C_B: %s." % " · ".join(rg["C_B_24"]))
    a("- B 점수 범주 %d개, 문턱(예산 5 · 10 · 20%%) %s. A 범주 %d개, 문턱 %s." % (len(rg["B_범주"]), rg["B_문턱"], rg["A_범주수"], rg["A_문턱"]))
    a("")
    a("## 2. 기본 사망률 — 구간 세 가지")
    a("")
    a("회사 = 회사 복원추출(원래 구간), 해 = 기준일 복원추출, 회사×해 = 둘을 곱한 무게(두 방향). 해마다 사망률이 이항 하나로 설명되지 않는다"
      "(카이제곱 %s, df 9, 5%% 임계 16.9) — 헤드라인 구간은 회사×해다." % R["해마다_이질성_카이제곱(df=9)"])
    a("")
    a("| 정의(24개월, 2015~2024) | 관측 | 사망 | 사망률 | 90% 회사 | 90% 해 | 90% 회사×해 | 표본 밖 2019~2024 사망률 [회사×해] |")
    a("|---|---|---|---|---|---|---|---|")
    for nm, m in R["기본사망률"].items():
        t = m.get("표본밖(2019~2024)")
        a("| %s | %d | %s | %s | %s | %s | %s | %s |" % (
            nm, m["관측"], m["사망"], P(m["사망률"], 2), ci(m, "사망률", "회사", 2), ci(m, "사망률", "해", 2), ci(m, "사망률", "회사×해", 2),
            ("%s [%s]" % (P(t["사망률"], 2), ci(t, "사망률", "회사×해", 2))) if t else "–"))
    sv = R["상폐절차중_가중"]
    a("")
    a("기대값판 가중 = 1 − %s. %s 결말 %s → 결론 난 곳 중 살아남은 비율 %s." % (
        P(sv["결론난곳중_살아남은비율"], 0), sv["정의"], sv["결말"], P(sv["결론난곳중_살아남은비율"], 1)))
    a("")
    a("| 기준일 | 관측 | 24개월 사망률(기본) | 보수(절차중=생존) | 기대값 | 12개월(기본) |")
    a("|---|---|---|---|---|---|")
    for y, v in R["기본사망률_해마다[사망,사망률]"].items():
        a("| %s | %d | %s | %s | %s | %s |" % (y, v["관측"], P(v["y24"][1], 2) if v["y24"] else "–", P(v["y24c"][1], 2) if v["y24c"] else "–",
                                            P(v["y24e"][1], 2) if v["y24e"] else "–", P(v["y12"][1], 2) if v["y12"] else "–"))
    a("")
    a("## 3. 규칙별 표본 밖 성적 — 구간은 회사×해")
    a("")
    a("| 규칙 | 기간 | 사건 정의 | 버림 | 재현(피한 사망) | 정밀(걸린 것 중 사망) | lift | 남은 쪽 사망률 | 기본 |")
    a("|---|---|---|---|---|---|---|---|---|")
    for nm, x in R["규칙_표본밖"].items():
        for vn in ("기본", "보수(절차중=생존)", "기대값", "엄격"):
            m = x[vn]
            a("| %s | %s | %s | %s [%s] | %s [%s] | %s [%s] | %s | %s [%s] | %s |" % (
                nm if vn == "기본" else "", x["표본밖기간"] if vn == "기본" else "", vn,
                P(m["버리는비율"]), ci(m, "버리는비율", "회사×해"), P(m["재현율"], 0), ci(m, "재현율", "회사×해", 0),
                P(m["사망률"]), ci(m, "사망률", "회사×해"), F(m["lift"]), P(m["남은사망률"], 2), ci(m, "남은사망률", "회사×해", 2), P(m["기본사망률"], 2)))
    a("")
    cb = R["규칙_표본밖"]["C_B(짧은 규칙, 작전주 꼴 OR)"]
    m = cb["기본"]
    a("C_B 구간 비교(기본 정의): 재현 회사 [%s] · 해 [%s] · 회사×해 [%s] / 정밀 회사 [%s] · 회사×해 [%s] / 남은 쪽 회사 [%s] · 회사×해 [%s]." % (
        ci(m, "재현율", "회사", 0), ci(m, "재현율", "해", 0), ci(m, "재현율", "회사×해", 0), ci(m, "사망률", "회사"), ci(m, "사망률", "회사×해"),
        ci(m, "남은사망률", "회사", 2), ci(m, "남은사망률", "회사×해", 2)))
    a("")
    a("### 해마다 재현(기본 → 보수) · 남은 쪽 사망률(기본)")
    a("")
    ys = sorted(set(y for x in R["규칙_표본밖"].values() for y in x["해마다_기본"]))
    a("| 규칙 | " + " | ".join(ys) + " |")
    a("|---|" + "---|" * len(ys))
    for nm, x in R["규칙_표본밖"].items():
        cells = []
        for y in ys:
            b, c = x["해마다_기본"].get(y), x["해마다_보수"].get(y)
            cells.append("–" if not b else "%s→%s · %s" % (P(b["재현율"], 0), P(c["재현율"], 0), P(b["남은사망률"], 2)))
        a("| %s | %s |" % (nm, " | ".join(cells)))
    a("")
    a("### 단위 · 기간 · 시장")
    a("")
    for nm, x in R["규칙_표본밖"].items():
        if "회사단위·기간별" not in x:
            continue
        u = x["회사단위·기간별"]
        h = u["사건까지기간별[사망관측,걸림,재현]"]
        mk, mc = x["시장별_기본"], x["시장별_보수"]
        a("- %s: 사망 회사 %d곳 중 한 번이라도 걸림 %s · 마지막 기준일에 걸림 %s · 모든 기준일에 걸림 %s(확정 사망 %d곳만: 한 번이라도 %s). "
          "사건까지 12개월 안 재현 %s(%d) · 12~24개월 %s(%d). 사건까지 일수 중앙값 걸린 사망 %s · 놓친 사망 %s. "
          "유가 재현 %s(사망 %s, 보수 %s) · 코스닥 %s(사망 %s). 2020~2024만 재현 %s · 버림 %s." % (
              nm, u["사망회사"], P(u["한번이라도걸림_비율"], 0), P(u["마지막기준일에걸림_비율"], 0), P(u["모든기준일에걸림_비율"], 0),
              u["확정사망회사"], P(u["확정사망회사만_한번이라도걸림_비율"], 0),
              P(h["≤12개월"][2], 0), h["≤12개월"][0], P(h["12~24개월"][2], 0), h["12~24개월"][0],
              F(u["사건까지일수_중앙값[걸린사망,놓친사망]"][0], 0), F(u["사건까지일수_중앙값[걸린사망,놓친사망]"][1], 0),
              P(mk["유가"]["재현율"], 0), mk["유가"]["전체사망"], P(mc["유가"]["재현율"], 0), P(mk["코스닥"]["재현율"], 0), mk["코스닥"]["전체사망"],
              P(x["2020~2024만"]["재현율"], 0), P(x["2020~2024만"]["버리는비율"])))
    a("")
    fb = R["앞뒤_lift"]
    a("## 4. 앞(2015~2018) · 뒤(2019~2024) lift")
    a("")
    a("- 두 기간 합쳐 걸린 사망 10 이상인 %d범주: 순위상관(스피어만) %s, 뒤/앞 중앙값 %s. 1.5배 넘게 다른 범주 %d개. 작전주 꼴 %d범주만: 순위상관 %s, 1.5배 넘게 다른 것 %s." % (
        fb["범주수"], fb["스피어만"], fb["뒤/앞_중앙값"], fb["1.5배넘게다름"], fb["작전주꼴범주수"], fb["작전주꼴_스피어만"], ", ".join(fb["작전주꼴_1.5배넘게다름"]) or "없음"))
    a("- 1.5배 넘게 다른 범주(사망 많은 순): " + " · ".join("%s %s→%s(사망 %d·%d)" % (r["신호"], F(r["앞[걸림,사망,lift]"][2]), F(r["뒤[걸림,사망,lift]"][2]),
                                                                       r["앞[걸림,사망,lift]"][1], r["뒤[걸림,사망,lift]"][1]) for r in fb["1.5배넘게다름_목록"][:20]))
    a("")
    pf = R["사전거르기"]
    a("## 5. 기준일에 이미 '죽는 중' 인 관측 — 사전 거르기")
    a("")
    a("- %s" % pf["정의"])
    a("- 이미사망 %d관측(기준일 공시로 절차중이 보인 것 %d) · 지금 판정 %s." % (pf["이미사망[관측,기준일에보임]"][0], pf["이미사망[관측,기준일에보임]"][1], pf["이미사망_지금판정"]))
    a("- 절차중 %d관측 중 24개월 안에 (다시) 사망 사슬 %d · 지금 판정 %s." % (pf["절차중[관측,24개월안다시사망]"][0], pf["절차중[관측,24개월안다시사망]"][1], pf["절차중_지금판정"]))
    a("- **기준일 공시로 절차중이 보이는 관측 %d개 중 %d개(%s)가 그 사슬로 죽었거나 24개월 안에 다시 사망 사슬에 들었다**(결론 안 난 절차중을 빼면 %s). "
      "본 연구 요약의 '221 중 21%%' 는 이미 죽은 쪽을 먼저 뺀 나머지 비율이다." % (
          pf["기준일에_절차중으로_보이는_관측"], pf["그중_사망사슬로끝남(이미사망 보임 + 24개월안 사망)"], P(pf["비율"], 0), P(pf["비율_보수(결론안난 절차중 제외하고 확정 사망만)"], 0)))
    a("- 사업보고서 13개월 미제출 %d관측 중 24개월 사망 %d." % tuple(pf["사업보고서없음[관측,24개월사망]"]))
    a("- 거르기 전 전체(유가 · 코스닥 영업회사, 이미사망을 사망으로 셈) 24개월 사망률 %s(관측 %d · 사망 %d). 본표본 1.66%% 는 '그날 절차중이 아닌 회사' 조건부다." % (
        P(pf["거르기전_전체_24개월사망률"], 2), pf["거르기전_전체[관측,사망]"][0], pf["거르기전_전체[관측,사망]"][1]))
    for k in ("사전거르기+C_B_표본밖(2019~2024)", "사전거르기+C_B_표본밖(2019~2024)_보수",
              "사전거르기+C_B·배당없음_표본밖(2019~2024)", "사전거르기+C_B·배당없음_표본밖(2019~2024)_보수"):
        m = pf[k]
        a("- %s: 버림 %s · 재현 %s · 정밀 %s · 남은 쪽 사망률 %s(기본 %s, 관측 %d · 사망 %s)." % (
            k, P(m["버리는비율"]), P(m["재현율"], 0), P(m["사망률"]), P(m["남은사망률"], 2), P(m["기본사망률"], 2), m["전체"], F(m["전체사망"], 0)))
    a("")
    sp = R["C_B걸린쪽_나누기"]
    a("## 6. C_B 에 걸린 쪽 나누기 — 배당 · 걸린 조건 수")
    a("")
    a("%s 칸 = 관측 · 사망 · 사망률." % sp["정의"])
    a("")
    keys = ["전체(기본률)", "C_B 걸림", "걸림·배당없음", "걸림·배당있음", "걸림·조건1개", "걸림·조건2개+", "걸림·조건1개·배당있음",
            "걸림·배당없음·조건1개", "걸림·배당없음·조건2개+", "걸림·배당없음·금전대여만", "안걸림·배당없음", "안걸림·배당있음"]
    a("| 묶음 | 학습 2015~2018 기본 | 표본 밖 2019~2024 기본 | 표본 밖 보수(절차중=생존) |")
    a("|---|---|---|---|")
    for k in keys:
        c1, c2, c3 = sp["학습 2015~2018"]["기본"][k], sp["표본밖 2019~2024"]["기본"][k], sp["표본밖 2019~2024"]["보수"][k]
        a("| %s | %d · %s · %s | %d · %s · %s | %d · %s · %s |" % (k, c1[0], F(c1[1], 0), P(c1[2]), c2[0], F(c2[1], 0), P(c2[2]), c3[0], F(c3[1], 0), P(c3[2])))
    t2 = sp["표본밖 2019~2024"]["기본"]
    a("")
    a("- 표본 밖 회사×해 90%% 구간: 걸림·배당없음 사망률 [%s~%s](버림 %s · 재현 %s) · 걸림·배당있음 [%s~%s](버림 %s · 재현 %s)." % (
        P(t2["걸림·배당없음_사망률_90_회사×해"][0]), P(t2["걸림·배당없음_사망률_90_회사×해"][1]), P(t2["걸림·배당없음_버림"]), P(t2["걸림·배당없음_재현율"], 0),
        P(t2["걸림·배당있음_사망률_90_회사×해"][0]), P(t2["걸림·배당있음_사망률_90_회사×해"][1]), P(t2["걸림·배당있음_버림"]), P(t2["걸림·배당있음_재현율"], 0)))
    a("")
    a("| 조건 | 학습: 걸림 · 사망 · 사망률 · 이 조건만 걸림 · 사망 | 표본 밖: 같은 칸 |")
    a("|---|---|---|")
    for k, v in sp["학습 2015~2018"]["기본"]["조건별(걸린 관측 · 사망 · 사망률 · 그 조건만 걸린 관측 · 사망)"].items():
        w = sp["표본밖 2019~2024"]["기본"]["조건별(걸린 관측 · 사망 · 사망률 · 그 조건만 걸린 관측 · 사망)"][k]
        a("| %s | %d · %s · %s · %d · %s | %d · %s · %s · %d · %s |" % (k, v[0], F(v[1], 0), P(v[2]), v[3], F(v[4], 0), w[0], F(w[1], 0), P(w[2]), w[3], F(w[4], 0)))
    a("")
    nw = R["지금"]
    a("## 7. 지금(%s) 걸리는 회사" % nw["기준일"])
    a("")
    a("- 지금 상장 중(상폐절차중 포함) 회사: %s." % ", ".join("%s %d" % kv for kv in nw["전체"].items()))
    a("- 그중 종목.txt(지금 시총 상위 1000): %s." % ", ".join("%s %d" % kv for kv in nw["종목txt안"].items()))
    for dv in ("배당없음", "배당있음"):
        a("- 종목.txt 안에서 C_B 에 걸린 곳(%s): " % dv + " · ".join("%s(%s, %s)" % (x[0], x[1], ", ".join(x[3])) for x in nw["종목txt안_C_B걸림_목록"] if x[4] == dv))
    a("")
    a("## 8. 재현")
    a("")
    a("- `%s` → 이 파일과 사망_검증_보강.json. 작전주_사망_검증.py 의 prepare · build_panel · greedy_rule · select_categories · evaluate_rule 을 불러 쓴다." % RUN)
    a("- JSON 열쇠: 리츠규칙 · 상폐절차중_가중 · 규칙_다시고르기 · 기본사망률(구간 *_90_회사/해/회사×해) · 기본사망률_해마다 · 규칙_표본밖(규칙 → 기본/보수/기대값/엄격, 해마다, 시장별, 회사단위·기간별) · 앞뒤_lift · 사전거르기 · 지금.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
