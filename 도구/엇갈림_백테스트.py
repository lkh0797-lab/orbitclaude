# -*- coding: utf-8 -*-
"""
엇갈림 백테스트 — 가속도 탭 '한눈에' 판이 칠하는 칸이 뒤 주가를 갈랐나 (2026-10-20, 사용자: "엇갈림 백테스트 돌려줘")

규칙(화면과 같게 미리 고정, 결과를 본 뒤 바꾸지 않는다)
  U  이익률↑ · 주가↓   TTM 영업이익률(영업이익_TTM ÷ 매출_TTM) 1년 변화 ≥ +0.5%p 이고 분기 말 주가 1년 변화 ≤ −5%   (화면 파랑)
  D  이익률↓ · 주가↑   1년 변화 ≤ −0.5%p 이고 주가 ≥ +5%                                                         (화면 자홍)
  견줄 묶음  UU 이익률↑ · 주가↑ · DD 이익률↓ · 주가↓ · 나머지 전부(rest) · 전체(ALL)
  주가 = 그 분기 말(마지막 거래일, 10일 안) 종가 — 네이버 수정주가(.cache/price). 화면은 증권사 주간 주가지만 같은 뜻.
  들어가는 날 = 그 분기 보고서 공시일(기준일) 다음 거래일 종가. 분기 말 주가는 공시 전에 알고, TTM 이익률은 공시일에 안다 — 앞날 정보 없음.
  결과 = 6 · 12개월 수익률 − 같은 기간 전 종목 수익률 중앙값(억울_백테스트 W.grp_ret('__all__'), 가속기준 백테스트와 같은 정의).

통과 기준(가속도 렌즈와 같은 막대) — 묶음 차이(U − UU, U − rest, D − DD, D − rest)의 회사 단위 부트스트랩 90% 구간이 0 을 걸치지 않고,
  앞(~2019) · 뒤(2020~) 기간 차이가 같은 방향. 덧붙여 '같은 분기 안' 차이(분기마다 묶음 중앙값 차이의 중앙값 · 같은 쪽 비율)로 시기 쏠림을 본다.
한계 — 지금 상장된 회사만(생존 편향), 금융 · 지주(영업이익 기준 · KSIC 64~66)는 이익률이 없어 뺀다, 공시가 분기 말 120일보다 늦은 행은 뺀다.

실행: py -3.13 도구/엇갈림_백테스트.py     (64비트 — 서버 모듈과 전 종목 주가를 한 번에 올린다)
결과: 표준출력 + .cache/druck_bt/gap_bt.json (가속도 탭 한눈에 판의 '칠한 칸' 설명이 읽는다)
"""
import os
import sys
import json
import time
import datetime as dt
import statistics as st
import importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
OUT = os.path.join(BASE, ".cache", "druck_bt", "gap_bt.json")
T1 = dt.date.today().strftime("%Y%m%d")
M_TH, P_TH = 0.5, 5.0          # 화면 문턱(드러켄밀러 화면 drkGapOf · drkGlance)
LAG_MAX = 120                  # 분기 말 → 공시일 일수 상한


def qend(n):
    y, q = n // 4, n % 4 + 1
    return dt.date(y, 3 * q, (31, 30, 30, 31)[q - 1]).strftime("%Y%m%d")


def days(a, b):
    return (dt.datetime.strptime(b, "%Y%m%d") - dt.datetime.strptime(a, "%Y%m%d")).days


def margin(p):
    mt, ot = (p or {}).get("매출_TTM"), (p or {}).get("영업이익_TTM")
    return ot / mt * 100 if isinstance(mt, (int, float)) and mt > 0 and isinstance(ot, (int, float)) else None


def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def fmt(v, d=1):
    return "—" if v is None else "%+.*f" % (d, v)


def group(r, m_th=M_TH, p_th=P_TH):
    up, dn = r["dm"] >= m_th, r["dm"] <= -m_th
    pu, pd = r["dy"] >= p_th, r["dy"] <= -p_th
    return "U" if up and pd else "D" if dn and pu else "UU" if up and pu else "DD" if dn and pd else "N"


def ex(W, code, t1, d):
    if t1 is None or W.shift(t1, d) > T1:
        return None
    a, b = W.ret(code, t1, W.shift(t1, d)), W.grp_ret("__all__", t1, W.shift(t1, d))
    return a - b if a is not None and b is not None else None


def build(W, DRK, SEC):
    with open(os.path.join(BASE, ".cache", "거시", "induty.json"), encoding="utf-8") as fh:
        ksic = json.load(fh)
    rows = []
    for c in W.S.INDEX["companies"]:
        code = c.get("code")
        path = os.path.join(BASE, ".cache", "druck", "%s.json" % code)
        d = DRK.read_cache(path) if code and os.path.exists(path) else None
        if not d:
            continue
        k = str(ksic.get(W.S.corp_code_of(code)) or "")
        if d.get("basis") == "영업이익" or (k.startswith(SEC.FIN_KSIC) and code not in SEC.OVERRIDE):
            continue
        sec = SEC.sector_of(code, k)[0]
        by = {p["n"]: p for p in d.get("points") or [] if p.get("n") is not None}
        for n, p in by.items():
            date = p.get("기준일") or p.get("B기준일")
            m, m4 = margin(p), margin(by.get(n - 4))
            if not date or m is None or m4 is None:
                continue
            qe = qend(n)
            lag = days(qe, date[:8])
            if lag < 0 or lag > LAG_MAX:
                continue
            a, _ = W.px_at(code, qe)
            b, _ = W.px_at(code, qend(n - 4))
            if not a or not b:
                continue
            t1 = W.next_day(code, date[:8])
            rows.append({"code": code, "n": n, "t": date[:8], "sec": sec, "dm": m - m4, "dy": (a / b - 1) * 100,
                         "ex6": ex(W, code, t1, 182), "ex12": ex(W, code, t1, 365)})
    return rows


def stats(W, rs, y="ex12"):
    v = [r for r in rs if r.get(y) is not None]
    if len(v) < 15:
        return {"n": len(v)}
    lo, hi = W.boot(v, lambda sub: med([x[y] for x in sub]), n=500)
    xs = [r[y] for r in v]
    return {"n": len(v), "firms": len({r["code"] for r in v}), "med": med(xs), "ci": [lo, hi],
            "hit": sum(x > 0 for x in xs) / len(xs) * 100, "ex6": med([r["ex6"] for r in rs]),
            "early": med([r[y] for r in v if r["t"] < W.SPLIT]), "late": med([r[y] for r in v if r["t"] >= W.SPLIT])}


def spread(W, rs, fa, fb, y="ex12"):
    """묶음 a − 묶음 b 중앙값 차이 · 회사 단위 부트스트랩 90% 구간 · 앞/뒤 기간 차이 · 같은 분기 안 차이."""
    sub = [r for r in rs if r.get(y) is not None and (fa(r) or fb(r))]

    def diff(x):
        a = [r[y] for r in x if fa(r)]
        b = [r[y] for r in x if fb(r)]
        return st.median(a) - st.median(b) if len(a) >= 8 and len(b) >= 8 else None
    if len(sub) < 30:
        return None
    ci = W.boot(sub, diff, n=500)
    early = diff([r for r in sub if r["t"] < W.SPLIT])
    late = diff([r for r in sub if r["t"] >= W.SPLIT])
    qs = {}
    for r in sub:
        qs.setdefault(r["n"], []).append(r)
    within = [x for x in (diff_q(v, fa, fb, y) for v in qs.values()) if x is not None]
    d = diff(sub)
    ok = (d is not None and ci[0] is not None and (ci[0] > 0 or ci[1] < 0)
          and early is not None and late is not None and (early > 0) == (late > 0) == (d > 0))
    return {"diff": d, "ci": list(ci), "early": early, "late": late, "na": sum(1 for r in sub if fa(r)), "nb": sum(1 for r in sub if fb(r)),
            "within_med": med(within), "within_n": len(within),
            "within_same": (sum(1 for x in within if (x > 0) == ((d or 0) > 0)) / len(within) * 100) if within else None,
            "pass": ok}


def diff_q(v, fa, fb, y):
    a = [r[y] for r in v if fa(r)]
    b = [r[y] for r in v if fb(r)]
    return st.median(a) - st.median(b) if len(a) >= 5 and len(b) >= 5 else None


def report(W, rows):
    for r in rows:
        r["g"] = group(r)
    is_ = lambda g: (lambda r: r["g"] == g)
    G = {g: stats(W, [r for r in rows if r["g"] == g]) for g in ("U", "D", "UU", "DD", "N")}
    G["ALL"] = stats(W, rows)
    S_ = {
        "U_vs_UU": spread(W, rows, is_("U"), is_("UU")),
        "U_vs_rest": spread(W, rows, is_("U"), lambda r: r["g"] != "U"),
        "D_vs_DD": spread(W, rows, is_("D"), is_("DD")),
        "D_vs_rest": spread(W, rows, is_("D"), lambda r: r["g"] != "D"),
        # 생존 편향 맞춤 — 지금 상장사만이라 '주가가 내린' 묶음은 그 뒤 망한 회사가 빠져 성적이 부푼다. 주가 방향이 같은 묶음끼리 견주면
        # 그 부풂이 양쪽에 비슷하게 걸리고 이익률 방향만 남는다(U vs DD = 둘 다 주가↓, D vs UU = 둘 다 주가↑)
        "U_vs_DD": spread(W, rows, is_("U"), is_("DD")),
        "D_vs_UU": spread(W, rows, is_("D"), is_("UU")),
    }
    print("\n== 묶음별 — 공시 다음 거래일부터 12개월 시장(전 종목 중앙) 대비 · 중앙 [90% 구간] · 이긴 비율 · 6개월 · 앞/뒤")
    name = {"U": "U 이익률↑·주가↓(파랑)", "D": "D 이익률↓·주가↑(자홍)", "UU": "UU 둘 다 ↑", "DD": "DD 둘 다 ↓", "N": "N 그 밖", "ALL": "전체"}
    for g in ("U", "D", "UU", "DD", "N", "ALL"):
        s = G[g]
        if "med" not in s:
            print("  %-22s n=%d (적음)" % (name[g], s["n"]))
            continue
        print("  %-22s n=%6d 회사 %4d  %s [%s, %s]  이긴 %4.1f%%  6개월 %s  앞 %s / 뒤 %s" % (
            name[g], s["n"], s["firms"], fmt(s["med"]), fmt(s["ci"][0]), fmt(s["ci"][1]), s["hit"], fmt(s["ex6"]), fmt(s["early"]), fmt(s["late"])))
    print("\n== 묶음 차이(12개월 시장 대비 중앙의 차) — 통과 = 90% 구간이 0 을 안 걸치고 앞/뒤 같은 방향")
    for k, v in S_.items():
        if not v:
            print("  %-10s 표본 적음" % k)
            continue
        print("  %-10s %s [%s, %s]  앞 %s / 뒤 %s  같은 분기 안 중앙 %s (%d분기, 같은 쪽 %s%%)  → %s" % (
            k, fmt(v["diff"]), fmt(v["ci"][0]), fmt(v["ci"][1]), fmt(v["early"]), fmt(v["late"]), fmt(v["within_med"]), v["within_n"],
            "—" if v["within_same"] is None else "%.0f" % v["within_same"], "통과" if v["pass"] else "통과 못 함"))
    # 문턱 민감도 — 결과를 보고 고르지 않는다(표시만)
    sens = []
    print("\n== 문턱 민감도(U − UU, D − DD · 12개월) — 참고")
    for mt, pt in ((0.5, 5), (1.0, 10), (2.0, 20), (0.5, 20)):
        for r in rows:
            r["_g"] = group(r, mt, pt)
        a = spread(W, rows, lambda r: r["_g"] == "U", lambda r: r["_g"] == "UU")
        b = spread(W, rows, lambda r: r["_g"] == "D", lambda r: r["_g"] == "DD")
        sens.append({"m": mt, "p": pt, "U_vs_UU": a, "D_vs_DD": b})
        print("  이익률 ±%.1f%%p · 주가 ±%d%%   U−UU %s [%s, %s] (U %s)   D−DD %s [%s, %s] (D %s)" % (
            mt, pt, fmt(a and a["diff"]), fmt(a and a["ci"][0]), fmt(a and a["ci"][1]), a and a["na"],
            fmt(b and b["diff"]), fmt(b and b["ci"][0]), fmt(b and b["ci"][1]), b and b["na"]))
    rep = {"v": 1, "at": dt.datetime.now().isoformat(timespec="seconds"), "rule": {"m": M_TH, "p": P_TH, "lag_max": LAG_MAX, "split": W.SPLIT},
           "rows": len(rows), "firms": len({r["code"] for r in rows}), "groups": G, "spreads": S_, "sens": sens}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False)
    os.replace(tmp, OUT)
    return rep


if __name__ == "__main__":
    t0 = time.time()
    sp = ilu.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
    W = ilu.module_from_spec(sp)
    sp.loader.exec_module(W)
    sp = ilu.spec_from_file_location("산업_섹터", os.path.join(BASE, "산업_섹터.py"))
    SEC = ilu.module_from_spec(sp)
    sp.loader.exec_module(SEC)
    sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
    DRK = ilu.module_from_spec(sp)
    sp.loader.exec_module(DRK)
    print("파이썬 %s · 주가 %d 종목 · 색인 회사 %d" % (sys.version.split()[0], len(W.PX), len(W.S.INDEX["companies"])), flush=True)
    rows = build(W, DRK, SEC)
    print("행 %d · 회사 %d · 12개월 끝난 행 %d" % (len(rows), len({r["code"] for r in rows}), sum(r["ex12"] is not None for r in rows)), flush=True)
    report(W, rows)
    print("끝 %.0f초 → %s" % (time.time() - t0, OUT))
