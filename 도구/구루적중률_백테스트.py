# -*- coding: utf-8 -*-
"""
구루 다섯 명의 카드 판정을 분기 보고서마다 다시 매겨, 그 말대로 샀다면(또는 피했다면) 누가 더 자주 맞혔는지 잰다 (2026-10-03)

카드(변곡점.py lenses)의 배지를 그 보고서 공시일 시점 숫자(분기변화_백테스트.py 와 같은 시점 재구성 — 그때까지 나온 재무, 공시 다음 거래일 종가)로 다시 계산한다.
  켄 피셔      배지 = PSR 1.5배↓ · 매출 5년 연 15%↑ · 순이익률 5년 평균 5%↑ 가운데 몇 개(카드의 PRR 은 연구개발비 시점 자료가 없어 뺐다 — 분모는 카드처럼 4)
  드러켄밀러   배지 = 가속(B) +3%p↑ · 분기 영업이익률 직전 분기보다 ↑ · 재고일수 7분기 전보다 ↓ 가운데 몇 개(분모 3)
               가속(B)는 가속도 캐시(.cache/druck, 지금 VERSION 만)의 같은 분기 키 값(카드와 같은 B) — 캐시가 없는 회사 · 분기, B기준일이
               공시일 뒤인 B(그날엔 알 수 없던 값)는 판정 없음
  버핏         배지 = ROE 10년 평균 12%↑ · 최저 5%↑ · 영업이익률 변동계수 0.35↓ · 유보이익 1원 테스트 1원↑ 가운데 몇 개(분모 4)
               → 강함(75%↑) = 사라, 보통 = 판정 없음, 약함(45%↓) = 피하라
  린치         배지는 회사 종류라 방향이 없다 — 카드의 PEG(PER ÷ EPS 3년 연평균 성장)로 1 미만 = 사라, 2 이상 = 피하라(린치의 기준)
  멍거         배지 = 이상 없음 = 사라(통과), 경고 1개↑ = 피하라 — 경고 기준은 카드 그대로(현금화 3년 0.6 · 매출채권/재고일수 3년 +30% · 부채비율 200% · 자본금 증가 2회 · 3년 중 2년 적자)

적중 = 사라 판정 뒤 12개월 초과수익(전 종목 중앙값 대비) > 0, 피하라 판정 뒤 < 0. 3개월(다음 보고서까지)도 같이 잰다.
'동전' = 같은 표본에서 같은 수의 사라 · 피하라를 아무렇게나 냈을 때 맞을 확률. 적중률 − 동전 = 그 구루가 보탠 실력.
분기 승률 = 보고서 분기마다 '사라' 바구니 평균이 '피하라' 바구니 평균을 이긴 분기의 비율(3개월 보유, 다음 보고서에서 갈아탄다).

실행: python 도구/구루적중률_백테스트.py           결과: 표준출력 + .cache/inflect/guru_hit.json (+ guru_panel.json)
      python 도구/구루적중률_백테스트.py --report  패널을 다시 만들지 않고 집계만
"""
import os
import sys
import json
import statistics as st
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bt", os.path.join(HERE, "분기변화_백테스트.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)          # 재무 네트워크 차단 · 주가 캐시(W) · fmt
W, S, FIN = B.W, B.S, B.FIN
OUT = os.path.join(S.CACHE_DIR, "inflect")
YEARS = list(range(2012, 2027))
GURUS = [("f", "켄 피셔"), ("d", "스탠리 드러켄밀러"), ("b", "워런 버핏"), ("l", "피터 린치"), ("m", "찰리 멍거")]
RULE_TXT = {
    "f": ("배지 강함(PSR 1.5↓ · 매출 5년 15%↑ · 순이익률 5%↑ 중 3개)", "배지 약함(1개↓)"),
    "d": ("배지 강함(가속(B) +3%p↑ · 이익률↑ · 재고일수↓ 모두)", "배지 약함(1개↓)"),
    "b": ("배지 강함(ROE 평균 12%↑ · 최저 5%↑ · 이익률 안정 · 유보이익 1원 중 3개↑)", "배지 약함(1개↓)"),
    "l": ("PEG 1 미만", "PEG 2 이상"),
    "m": ("이상 없음(경고 0)", "경고 1개↑"),
}


def qn(lab):
    return int(lab[:4]) * 4 + int(lab[5])


def grade(ok, total):
    r = ok / total
    return 1 if r >= 0.75 else 0 if r >= 0.45 else -1


def one(c):
    code = c["code"]
    corp = S.corp_code_of(code)
    px = B.prices(code)
    if not corp or not px:
        return []
    try:
        mi = FIN.statement_matrix(corp, YEARS, "IS", "q")
        mb = FIN.statement_matrix(corp, YEARS, "BS", "q")
        mc = FIN.statement_matrix(corp, YEARS, "CF", "q")
    except Exception:
        return []
    pr = S._pipe_rows(c, mi, mb, mc, px=px, blog_pts=[])
    if not pr:
        return []
    labs, R = pr["labs"], pr["rows"]
    by_q = {qn(l): l for l in labs}
    get = lambda lab, k, back=0: (R.get(by_q.get(qn(lab) - back)) or {}).get(k)
    # 분기 하나짜리 매출 · 영업이익(드러켄밀러 카드는 분기 숫자로 읽는다), 이익잉여금 · 자본금(버핏 · 멍거)
    rq = S._mseries(mi, S._mrow(mi, ("t:Revenue",), r"^(매출액|수익\(매출액\)|영업수익|매출)$"))
    oq = S._mseries(mi, S._mrow(mi, ("t:OperatingIncomeLoss",), r"^영업(이익|손익|손실)"))
    rete = S._mseries(mb, S._mrow(mb, ("t:RetainedEarnings",), r"^이익\s*잉여금"))
    capi = S._mseries(mb, S._mrow(mb, ("t:IssuedCapital",), r"^자본금$"))
    sh = lambda lab, k: S._qshift(lab, k)

    def q_opm(lab):
        a, b = oq.get(lab), rq.get(lab)
        v = a / b * 100 if a is not None and b and b > 0 else None
        return v if v is not None and abs(v) <= 100 else None

    filed = {}
    for r in c["reports"]:
        y, m = r["stamp"].split("-")
        if not r["tag"] and m in S.Q_OF_MONTH:
            lab = "%sQ%d" % (y, S.Q_OF_MONTH[m])
            filed[lab] = min(filed.get(lab, "99999999"), r["rcept"][:8])
    # 가속(B) — 가속도 캐시(S._druck_read: v 가 지금 DRK.VERSION 일 때만)의 분기 키 n(= qn − 1) 값과 B기준일. 다시 계산하지 않는다.
    # 공시일 t 에는 B기준일 ≤ t 인 B 만 쓴다(S.DRK.b_known) — 그 뒤에 나온 자료로 셈한 B 는 그날 카드에 없던 값이다
    dk = S._druck_read(code)
    acc_b = S.DRK.b_lookup((dk or {}).get("points"))
    out = []
    for lab in labs:
        t = filed.get(lab)
        if not t or t < "20150101" or t > B.LAST_T:
            continue
        r = R[lab]
        p = B.adj_at(px, t)
        shs, rt, nt = r.get("shares"), r.get("rev_ttm"), r.get("ni_ttm")
        mcap = p * shs if p and shs else None
        psr = mcap / rt if mcap and rt and rt > 0 else None

        def cagr(k, n):
            a, b = r.get(k), get(lab, k, n * 4)
            return ((a / b) ** (1 / n) - 1) * 100 if a and b and a > 0 and b > 0 else None
        # ---- 켄 피셔
        g5 = cagr("rev_ttm", 5)
        if g5 is None:
            g5 = cagr("rev_ttm", 3)
        nims = [get(lab, "ni_ttm", k) / get(lab, "rev_ttm", k) * 100 for k in (0, 4, 8, 12, 16)
                if get(lab, "ni_ttm", k) is not None and get(lab, "rev_ttm", k)]
        nim5 = sum(nims) / len(nims) if nims else None
        f_ok = (psr is not None and psr <= 1.5) + (g5 is not None and g5 >= 15) + (nim5 is not None and nim5 >= 5)
        f_call = grade(f_ok, 4) if psr is not None else None
        # ---- 드러켄밀러(분기 숫자) — 가속은 같은 시점(이 공시의 분기 키) 가속도 캐시의 가속(B), 카드와 같은 문턱(+3%p)
        acc = S.DRK.b_known(acc_b, qn(lab) - 1, t)
        m0, m1 = q_opm(lab), q_opm(sh(lab, 1))
        mchg = m0 - m1 if m0 is not None and m1 is not None else None
        invd = lambda L: (R[L]["inv"] / R[L]["rev_ttm"] * 365) if L in R and R[L].get("inv") and R[L].get("rev_ttm") else None
        i0 = invd(lab)
        i7 = next((invd(sh(lab, k)) for k in (7, 6, 5, 4) if invd(sh(lab, k)) is not None), None)
        d_ok = (acc is not None and acc >= 3) + (mchg is not None and mchg > 0) + (i0 is not None and i7 is not None and i0 <= i7)
        d_call = grade(d_ok, 3) if acc is not None else None
        # ---- 버핏
        roes = [get(lab, "roe", k) for k in range(0, 40, 4) if get(lab, "roe", k) is not None]
        mg = [get(lab, "opm_ttm", k) for k in range(0, 40, 4) if get(lab, "opm_ttm", k) is not None]
        cv = (st.pstdev(mg) / abs(st.mean(mg))) if len(mg) >= 3 and st.mean(mg) else None
        re0, re5 = rete.get(lab), rete.get(sh(lab, 20))
        p5 = B.adj_at(px, "%d%s" % (int(t[:4]) - 5, t[4:]))
        sh5 = get(lab, "shares", 20)
        rt_ratio = ((mcap - p5 * sh5) / (re0 - re5)) if mcap and p5 and sh5 and re0 is not None and re5 is not None and re0 - re5 > 0 else None
        b_ok = (bool(roes) and st.mean(roes) >= 12) + (bool(roes) and min(roes) > 5) + (cv is not None and cv < 0.35) + (rt_ratio is not None and rt_ratio >= 1)
        b_call = grade(b_ok, 4) if len(roes) >= 3 else None
        # ---- 린치 — 종류(카드 _lynch_kind)와 PEG(PER ÷ EPS 3년 연평균)
        g3 = cagr("rev_ttm", 3)
        mg8 = [get(lab, "opm_ttm", k) for k in range(0, 32, 4) if get(lab, "opm_ttm", k) is not None]
        cv8 = (st.pstdev(mg8) / abs(st.mean(mg8))) if len(mg8) >= 4 and st.mean(mg8) else None
        n8 = get(lab, "ni_ttm", 8)
        if n8 is not None and nt is not None and n8 < 0 < nt:
            kind = "회생주"
        elif g3 is None:
            kind = None
        elif cv8 is not None and cv8 >= 0.5:
            kind = "경기순환주"
        else:
            kind = "고성장주" if g3 >= 20 else "대형우량주" if g3 >= 8 else "저성장주"
        et = r.get("eps_ttm")
        per = p / et if p and et and et > 0 else None
        e3 = cagr("eps_ttm", 3)
        peg = per / e3 if per and e3 and e3 > 0 else None
        l_call = None if peg is None else 1 if peg < 1 else -1 if peg >= 2 else 0
        # ---- 멍거(카드 기준 그대로)
        cf3 = [get(lab, "cfo_ttm", k) for k in (0, 4, 8)]
        ni3 = [get(lab, "ni_ttm", k) for k in (0, 4, 8)]
        cash_ok = all(v is not None for v in cf3 + ni3) and sum(ni3) > 0
        days = lambda key, k: (get(lab, key, k) / get(lab, "rev_ttm", k) * 365) if get(lab, key, k) and get(lab, "rev_ttm", k) else None
        gr = lambda key: (days(key, 0) / days(key, 12) - 1) * 100 if days(key, 0) and days(key, 12) else None
        ar, iv = gr("recv"), gr("inv")
        debt, eq = r.get("debt"), r.get("eq_total")
        le = debt / eq * 100 if debt is not None and eq and eq > 0 else None
        caps = [capi.get(sh(lab, k)) for k in (12, 8, 4, 0)]
        caps = [v for v in caps if v]
        raises = sum(1 for a, b in zip(caps, caps[1:]) if b > a * 1.02)
        losses = sum(1 for v in ni3 if v is not None and v < 0)
        fl = {"cash": cash_ok and sum(cf3) < 0.6 * sum(ni3), "recv": ar is not None and ar >= 30, "inv": iv is not None and iv >= 30,
              "debt": le is not None and le >= 200, "issue": raises >= 2, "loss": losses >= 2}
        nfl = sum(1 for v in fl.values() if v)
        m_call = (1 if nfl == 0 else -1) if (cash_ok or le is not None) else None
        t1 = W.next_day(code, t)           # 공시 다음 거래일 종가(달력 +1일이면 금요일 공시가 그날 종가로 샀다)
        a12 = b12 = a3 = b3 = None
        if t1:
            a12, b12 = W.ret(code, t1, W.shift(t1, 365)), W.grp_ret("__all__", t1, W.shift(t1, 365))
            a3, b3 = W.ret(code, t1, W.shift(t1, 91)), W.grp_ret("__all__", t1, W.shift(t1, 91))
        out.append({"code": code, "lab": lab, "t": t[:6] + "15", "date": t,
                    "c": {"f": f_call, "d": d_call, "b": b_call, "l": l_call, "m": m_call},
                    "ok": {"f": f_ok, "d": d_ok, "b": b_ok, "m": nfl}, "kind": kind, "peg": peg, "psr": psr,
                    "fl": [k for k, v in fl.items() if v],
                    "ex12m": (a12 - b12) if a12 is not None and b12 is not None else None, "ret12": a12,
                    "ex3m": (a3 - b3) if a3 is not None and b3 is not None else None})
    return out


def _stats(rows, g, y):
    """한 구루 · 한 기간(y) — 사라 · 피하라 적중률, 동전, 실력, 초과수익, 함정."""
    rs = [r for r in rows if r["c"].get(g) is not None and r.get(y) is not None]
    if len(rs) < 40:
        return None
    buy = [r for r in rs if r["c"][g] == 1]
    avo = [r for r in rs if r["c"][g] == -1]
    up = sum(1 for r in rs if r[y] > 0) / len(rs)

    def edge(sub):
        b = [r for r in sub if r["c"][g] == 1]
        a = [r for r in sub if r["c"][g] == -1]
        s = [r for r in sub if r["c"][g] is not None]
        if len(b) + len(a) < 20 or not s:
            return None
        u = sum(1 for r in s if r[y] > 0) / len(s)
        hit = (sum(1 for r in b if r[y] > 0) + sum(1 for r in a if r[y] < 0)) / (len(b) + len(a))
        coin = (len(b) * u + len(a) * (1 - u)) / (len(b) + len(a))
        return (hit - coin) * 100
    tr = lambda sub: (sum(1 for r in sub if (r.get("ret12") or 0) <= -30 and r.get("ret12") is not None) /
                      max(1, sum(1 for r in sub if r.get("ret12") is not None)) * 100) if sub else None
    md = lambda sub: st.median([r[y] for r in sub]) if len(sub) >= 8 else None
    n_call = len(buy) + len(avo)
    hit = (sum(1 for r in buy if r[y] > 0) + sum(1 for r in avo if r[y] < 0)) / n_call * 100 if n_call else None
    coin = (len(buy) * up + len(avo) * (1 - up)) / n_call * 100 if n_call else None
    lo, hi = W.boot(rs, edge, n=400)
    return {"n": len(rs), "firms": len({r["code"] for r in rs}), "n_buy": len(buy), "n_avoid": len(avo),
            "buy_hit": sum(1 for r in buy if r[y] > 0) / len(buy) * 100 if buy else None, "buy_base": up * 100,
            "avoid_hit": sum(1 for r in avo if r[y] < 0) / len(avo) * 100 if avo else None, "avoid_base": (1 - up) * 100,
            "hit": hit, "coin": coin, "edge": (hit - coin) if hit is not None else None, "ci": [lo, hi],
            "early": edge([r for r in rs if r["t"] < W.SPLIT]), "late": edge([r for r in rs if r["t"] >= W.SPLIT]),
            "buy_med": md(buy), "avoid_med": md(avo), "all_med": md(rs),
            "buy_trap": tr(buy), "avoid_trap": tr(avo)}


def _cohorts(rows, g):
    """보고서 분기마다 사라 · 피하라 바구니의 3개월(다음 보고서까지) 수익 — 분기 승률과 누적 곡선.
    바구니는 같은 비중 평균이라, 같은 분기 전 표본의 같은 비중 평균을 빼야 몇 종목 급등에 끌려 둘 다 크게 오른 것처럼 보이지 않는다."""
    by, uni = {}, {}
    for r in rows:
        if r.get("ex3m") is None:
            continue
        v = max(-90.0, min(300.0, r["ex3m"]))
        uni.setdefault(r["lab"], []).append(v)
        if r["c"].get(g) in (1, -1):
            by.setdefault(r["lab"], {1: [], -1: []})[r["c"][g]].append(v)
    path, cb, ca, wins, n = [], 1.0, 1.0, 0, 0
    for lab in sorted(by):
        b, a = by[lab][1], by[lab][-1]
        if len(b) < 5 or len(a) < 5:
            continue
        mu = sum(uni[lab]) / len(uni[lab])
        mb, ma = sum(b) / len(b) - mu, sum(a) / len(a) - mu
        cb *= 1 + mb / 100
        ca *= 1 + ma / 100
        n += 1
        wins += mb > ma
        path.append([lab, round((cb - 1) * 100, 1), round((ca - 1) * 100, 1), len(b), len(a)])
    return {"n": n, "win": wins / n * 100 if n else None, "path": path,
            "buy_cum": (cb - 1) * 100 if n else None, "avoid_cum": (ca - 1) * 100 if n else None}


def report(panel):
    print("\n표본 %d (회사 %d) · 공시일 %s ~ %s" % (len(panel), len({r["code"] for r in panel}),
                                              min(r["date"] for r in panel), max(r["date"] for r in panel)))
    rep = {"n": len(panel), "firms": len({r["code"] for r in panel}), "from": min(r["date"] for r in panel),
           "to": max(r["date"] for r in panel), "gurus": {}, "kinds": {}, "by_code": {}}
    for y, nm in (("ex12m", "12개월"), ("ex3m", "3개월(다음 보고서까지)")):
        print("\n== %s 초과수익 기준 적중률" % nm)
        print("%-12s %6s %6s %6s %7s %7s %7s %7s %7s %14s %6s %6s" % ("구루", "판정", "사라", "피하라", "사라적중", "피하적중", "적중률", "동전", "실력", "90% 구간", "앞", "뒤"))
        for g, name in GURUS:
            s = _stats(panel, g, y)
            rep["gurus"].setdefault(g, {"name": name, "rule": RULE_TXT[g]})[y] = s
            if not s:
                continue
            print("%-12s %6d %6d %6d %7.1f %7.1f %7.1f %7.1f %+7.1f %14s %6s %6s" % (
                name, s["n"], s["n_buy"], s["n_avoid"], s["buy_hit"] or 0, s["avoid_hit"] or 0, s["hit"], s["coin"], s["edge"],
                "[%s, %s]" % (B.fmt(s["ci"][0]), B.fmt(s["ci"][1])), B.fmt(s["early"]), B.fmt(s["late"])))
    print("\n== 12개월 초과수익 중앙값 · 함정(1년 −30%↓) · 분기 승률(사라 바구니 > 피하라 바구니, 3개월 보유)")
    for g, name in GURUS:
        s = rep["gurus"][g].get("ex12m")
        co = _cohorts(panel, g)
        rep["gurus"][g]["cohort"] = co
        if s:
            print("%-12s 사라 %s · 피하라 %s · 전체 %s | 함정 사라 %.0f%% 피하라 %.0f%% | 분기 승률 %s (%d분기) 누적 사라 %s 피하라 %s" % (
                name, B.fmt(s["buy_med"]), B.fmt(s["avoid_med"]), B.fmt(s["all_med"]), s["buy_trap"] or 0, s["avoid_trap"] or 0,
                B.fmt(co["win"], 0), co["n"], B.fmt(co["buy_cum"], 0), B.fmt(co["avoid_cum"], 0)))
    # 린치 — 종류별 성적(종류는 방향이 없지만 종류마다 뒤 12개월이 달랐나)
    for k in ("고성장주", "대형우량주", "저성장주", "경기순환주", "회생주"):
        sub = [r for r in panel if r["kind"] == k and r.get("ex12m") is not None]
        if len(sub) >= 30:
            rep["kinds"][k] = {"n": len(sub), "med": st.median([r["ex12m"] for r in sub]),
                               "up": sum(1 for r in sub if r["ex12m"] > 0) / len(sub) * 100}
    print("\n린치 종류별 12개월:", ", ".join("%s %d건 %s(이긴 비율 %.0f%%)" % (k, v["n"], B.fmt(v["med"]), v["up"]) for k, v in rep["kinds"].items()))
    # 회사별 — 이 회사에서는 누구 말이 맞았나(카드 아래 칸에서 쓴다)
    by = {}
    for r in panel:
        by.setdefault(r["code"], []).append(r)
    for code, rs in by.items():
        rs.sort(key=lambda r: r["lab"])
        d = {}
        for g, _ in GURUS:
            b = [r for r in rs if r["c"].get(g) == 1 and r.get("ex12m") is not None]
            a = [r for r in rs if r["c"].get(g) == -1 and r.get("ex12m") is not None]
            d[g] = [len(b), sum(1 for r in b if r["ex12m"] > 0), len(a), sum(1 for r in a if r["ex12m"] < 0)]
        d["tl"] = [[r["lab"], "".join({1: "+", -1: "-", 0: "0", None: "."}[r["c"].get(g)] for g, _ in GURUS),
                    None if r.get("ex12m") is None else round(r["ex12m"], 1)] for r in rs]
        rep["by_code"][code] = d
    json.dump(rep, open(os.path.join(OUT, "guru_hit.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)
    print("\n→ %s" % os.path.join(OUT, "guru_hit.json"))


def main():
    os.makedirs(OUT, exist_ok=True)
    comps = [c for c in S.INDEX["companies"] if c.get("code")]
    panel = []
    for i, c in enumerate(comps, 1):
        try:
            panel += one(c)
        except Exception as e:
            print("  %s 실패: %s" % (c["code"], e), flush=True)
        if i % 100 == 0:
            print("  %d/%d · 표본 %d" % (i, len(comps), len(panel)), flush=True)
    json.dump(panel, open(os.path.join(OUT, "guru_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)
    report(panel)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        report(json.load(open(os.path.join(OUT, "guru_panel.json"), encoding="utf-8")))
    elif len(sys.argv) > 1 and sys.argv[1] == "--one":
        for r in one(S.company_by_code(sys.argv[2])):
            print(r["lab"], r["date"], r["c"], r["ok"], r["kind"], B.fmt(r["peg"], 2), r["fl"], B.fmt(r["ex12m"]), B.fmt(r["ex3m"]))
    else:
        main()
