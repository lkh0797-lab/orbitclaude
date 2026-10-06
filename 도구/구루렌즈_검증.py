# -*- coding: utf-8 -*-
"""
구루의 렌즈(변경점 비교 → 변곡점 · 구루 렌즈)가 '가치 대비 싼 회사를 사게 돕는가'를 큰 표본으로 다시 잰다 (2026-10-02)

예전 검증(도구/반영속도_검증.py)은 14종목 · 515건이라 카드의 '우리 데이터 12개월' 숫자를 믿기 어렵다.
분기변화_백테스트.py 와 같은 시점 재구성(공시일 t, 그때까지 나온 숫자, 재무는 캐시만)으로 렌즈 지표를 다시 세우고
t 다음 거래일 종가부터 12개월 초과수익(전 종목 중앙값 대비, 2026-10-07 고침)과 '가치 함정'(12개월 −30% 이하) 비율을 본다.
  피셔   PSR(시총 ÷ 매출 4분기) 절대 0.75 · 3배, PSR 자기 역사 백분위, 슈퍼 컴퍼니(매출 5년 연 15%↑ · 순이익률 5년 평균 5%↑), 글리치
  드러켄밀러  매출 증가율 · 가속 · 설비투자 강도 · 재고일수
  버핏   ROE · ROE 10년 평균/최저 · 영업이익률 흔들림
  린치   PEG · 성장 분류
  멍거   영업CF ÷ 순이익 < 0.6 · 매출채권일수 3년 +20% · 재고일수 3년 +20% · 부채비율 200%↑ · 3년 안 증자 · 3년 중 2년 적자
그리고 '싸다'가 품질 · 안전과 겹칠 때(퀄리티 + 합리적 가격)를 따로 잰다 — 렌즈가 저평가 매수 단서가 되는지는 여기서 갈린다.

실행: python 도구/구루렌즈_검증.py        결과: 표준출력 + .cache/inflect/lens_bt.json
"""
import os
import sys
import json
import math
import bisect
import statistics as st
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bt", os.path.join(HERE, "분기변화_백테스트.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)          # 재무 네트워크 차단 · 주가 캐시(W) · rule_test · fmt
W, S, FIN = B.W, B.S, B.FIN
OUT = os.path.join(S.CACHE_DIR, "inflect")
YEARS = list(range(2012, 2027))


def qn(lab):
    return int(lab[:4]) * 4 + int(lab[5])


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
    issue_q = {qn(x["at"]) for x in pr.get("splits") or [] if x.get("kind", "").startswith("증자")}
    filed = {}
    for r in c["reports"]:
        y, m = r["stamp"].split("-")
        if not r["tag"] and m in S.Q_OF_MONTH:
            lab = "%sQ%d" % (y, S.Q_OF_MONTH[m])
            filed[lab] = min(filed.get(lab, "99999999"), r["rcept"][:8])

    def qe_psr(lab):        # 분기 말 PSR — 자기 역사 백분위용
        r = R.get(lab) or {}
        return (r["px"] * r["shares"] / r["rev_ttm"]) if r.get("px") and r.get("shares") and r.get("rev_ttm") and r["rev_ttm"] > 0 else None
    out = []
    for lab in labs:
        t = filed.get(lab)
        if not t or t < "20150101" or t > B.LAST_T:
            continue
        r = R[lab]
        p = B.adj_at(px, t)
        sh, rt, nt = r.get("shares"), r.get("rev_ttm"), r.get("ni_ttm")
        mcap = p * sh if p and sh else None
        psr = mcap / rt if mcap and rt and rt > 0 else None
        hist = [v for v in (qe_psr(by_q[q]) for q in range(qn(lab) - 40, qn(lab)) if q in by_q) if v]
        psr_pct = (sum(1 for v in hist + [psr] if v <= psr) / (len(hist) + 1) * 100) if psr and len(hist) >= 8 else None
        et = r.get("eps_ttm")
        per = p / et if p and et and et > 0 else None
        ph = [R[by_q[q]]["per"] for q in range(qn(lab) - 40, qn(lab)) if q in by_q and (R[by_q[q]].get("per") or 0) > 0]
        per_pct = (sum(1 for v in ph + [per] if v <= per) / (len(ph) + 1) * 100) if per and len(ph) >= 8 else None
        g = r.get("ni_yoy")
        peg = per / min(max(g, 1.0), 100.0) if per and g is not None and g > 0 else None
        r5 = get(lab, "rev_ttm", 20)
        g5 = ((rt / r5) ** 0.2 - 1) * 100 if rt and r5 and r5 > 0 and rt > 0 else None
        nims = [(get(lab, "ni_ttm", k) / get(lab, "rev_ttm", k) * 100) for k in (0, 4, 8, 12, 16)
                if get(lab, "ni_ttm", k) is not None and get(lab, "rev_ttm", k)]
        nim5 = sum(nims) / len(nims) if len(nims) >= 4 else None
        nim_now = nt / rt * 100 if nt is not None and rt else None
        prev3 = [(get(lab, "ni_ttm", k) / get(lab, "rev_ttm", k) * 100) for k in (4, 8, 12) if get(lab, "ni_ttm", k) is not None and get(lab, "rev_ttm", k)]
        glitch = (r.get("rev_yoy") or 0) > 0 and nim_now is not None and len(prev3) == 3 and sum(prev3) / 3 > 0 and nim_now < 0.5 * sum(prev3) / 3
        roes = [get(lab, "roe", k) for k in range(0, 40, 4) if get(lab, "roe", k) is not None]
        opms = [get(lab, "opm_ttm", k) for k in range(0, 20, 4) if get(lab, "opm_ttm", k) is not None]
        opm_vol = (st.pstdev(opms) / abs(st.mean(opms))) if len(opms) >= 4 and st.mean(opms) else None
        cfo, debt, eq = r.get("cfo_ttm"), r.get("debt"), r.get("eq_total")
        cfo_ni = cfo / nt if cfo is not None and nt and nt > 0 else None
        rd0 = r.get("recv") / rt * 365 if r.get("recv") and rt else None
        rd3 = get(lab, "recv", 12) / get(lab, "rev_ttm", 12) * 365 if get(lab, "recv", 12) and get(lab, "rev_ttm", 12) else None
        id0 = r.get("inv") / rt * 365 if r.get("inv") and rt else None
        id3 = get(lab, "inv", 12) / get(lab, "rev_ttm", 12) * 365 if get(lab, "inv", 12) and get(lab, "rev_ttm", 12) else None
        losses = sum(1 for k in (0, 4, 8) if (get(lab, "ni_ttm", k) or 0) < 0)
        fl = {"cash": cfo_ni is not None and cfo_ni < 0.6,
              "recv": rd0 is not None and rd3 is not None and rd3 > 0 and rd0 > rd3 * 1.2,
              "inv": id0 is not None and id3 is not None and id3 > 0 and id0 > id3 * 1.2,
              "debt": debt is not None and eq and eq > 0 and debt / eq > 2,
              "issue": any(qn(lab) - 12 < q <= qn(lab) for q in issue_q),
              "loss": losses >= 2}
        t1 = W.next_day(code, t)           # 공시 다음 거래일 종가(달력 +1일이면 금요일 공시가 그날 종가로 샀다)
        a = W.ret(code, t1, W.shift(t1, 365)) if t1 else None
        b = W.grp_ret("__all__", t1, W.shift(t1, 365)) if t1 else None
        out.append({"code": code, "lab": lab, "t": t[:6] + "15", "date": t,
                    "psr": psr, "psr_pct": psr_pct, "per": per, "per_pct": per_pct, "peg": peg,
                    "g5": g5, "nim5": nim5, "glitch": glitch, "rev_yoy": r.get("rev_yoy"),
                    "acc": (r.get("rev_yoy") - get(lab, "rev_yoy", 1)) if r.get("rev_yoy") is not None and get(lab, "rev_yoy", 1) is not None else None,
                    "capex_int": (r.get("capex_ttm") / rt * 100) if r.get("capex_ttm") and rt else None, "inv_days": id0,
                    "roe": r.get("roe"), "roe_avg": (sum(roes) / len(roes)) if len(roes) >= 5 else None,
                    "roe_min": min(roes) if len(roes) >= 5 else None, "opm_vol": opm_vol, "cfo_ni": cfo_ni,
                    "munger": sum(1 for v in fl.values() if v), "fl": fl,
                    "ex12m": (a - b) if a is not None and b is not None else None, "ret12": a})
    return out


def trap(rows):
    v = [r["ret12"] for r in rows if r.get("ret12") is not None]
    return (sum(1 for x in v if x <= -30) / len(v) * 100) if v else None


RULES = [
    ("피셔 · PSR 0.75배↓(절대)", lambda r: None if r["psr"] is None else r["psr"] <= 0.75),
    ("피셔 · PSR 3배↑(절대)", lambda r: None if r["psr"] is None else r["psr"] >= 3),
    ("피셔 · PSR 자기 역사 하위 30%", lambda r: None if r["psr_pct"] is None else r["psr_pct"] <= 30),
    ("피셔 · PSR 자기 역사 상위 30%", lambda r: None if r["psr_pct"] is None else r["psr_pct"] >= 70),
    ("피셔 · 슈퍼 컴퍼니", lambda r: None if r["g5"] is None or r["nim5"] is None else (r["g5"] >= 15 and r["nim5"] >= 5)),
    ("피셔 · 글리치", lambda r: r["glitch"]),
    ("드러켄밀러 · 매출 +20%↑", lambda r: None if r["rev_yoy"] is None else r["rev_yoy"] >= 20),
    ("드러켄밀러 · 가속 +5%p↑", lambda r: None if r["acc"] is None else r["acc"] >= 5),
    ("드러켄밀러 · 설비투자 강도 10%↑", lambda r: None if r["capex_int"] is None else r["capex_int"] >= 10),
    ("버핏 · ROE 15%↑", lambda r: None if r["roe"] is None else r["roe"] >= 15),
    ("버핏 · ROE 10년 평균 15%↑ · 최저 10%↑", lambda r: None if r["roe_avg"] is None else (r["roe_avg"] >= 15 and r["roe_min"] >= 10)),
    ("버핏 · 이익률 흔들림 낮음(0.2↓)", lambda r: None if r["opm_vol"] is None else r["opm_vol"] <= 0.2),
    ("린치 · PEG < 1", lambda r: None if r["per"] is None else (r["peg"] is not None and r["peg"] < 1)),
    ("린치 · 고성장(매출 5년 20%↑)", lambda r: None if r["g5"] is None else r["g5"] >= 20),
    ("멍거 · 경고 2개↑", lambda r: r["munger"] >= 2),
    ("멍거 · 이익의 현금화 < 0.6", lambda r: r["fl"]["cash"]),
    ("멍거 · 매출채권일수 3년 +20%", lambda r: r["fl"]["recv"]),
    ("멍거 · 재고일수 3년 +20%", lambda r: r["fl"]["inv"]),
    ("멍거 · 부채비율 200%↑", lambda r: r["fl"]["debt"]),
    ("멍거 · 3년 안 증자", lambda r: r["fl"]["issue"]),
    ("멍거 · 3년 중 2년 적자", lambda r: r["fl"]["loss"]),
]
CHEAP = lambda r: (r["per_pct"] is not None and r["per_pct"] <= 30) or (r["psr_pct"] is not None and r["psr_pct"] <= 30)
QUAL = lambda r: (r["roe"] or 0) >= 10 and (r["cfo_ni"] or 0) >= 0.8
SAFE = lambda r: r["munger"] == 0
COMBO = [   # (이름, 해당 조건) — 전체 표본에서 해당 vs 나머지
    ("싸다(자기 역사 PER 또는 PSR 하위 30%)", CHEAP),
    ("싸다 + 품질(ROE 10%↑ · 현금화 0.8↑)", lambda r: CHEAP(r) and QUAL(r)),
    ("싸다 + 품질 + 멍거 경고 0", lambda r: CHEAP(r) and QUAL(r) and SAFE(r)),
    ("싸다 + 멍거 경고 2개↑(함정 후보)", lambda r: CHEAP(r) and r["munger"] >= 2),
    ("합리적 가격 + 품질 + 안전(PEG<1 · ROE 15%↑ · 경고 0)", lambda r: r["peg"] is not None and r["peg"] < 1 and (r["roe"] or 0) >= 15 and SAFE(r)),
]


def report(panel):
    print("\n표본 %d (회사 %d) · 공시일 %s ~ %s · 가치 함정(12개월 −30%%↓) 전체 %.1f%%"
          % (len(panel), len({r["code"] for r in panel}), min(r["date"] for r in panel), max(r["date"] for r in panel), trap(panel)))
    rep = {"n": len(panel), "rules": {}, "combo": {}, "ic": {}, "base_trap": trap(panel)}
    print("\n%-38s %6s %5s %7s %7s %7s %16s %7s %7s %7s" % ("규칙 — 12개월 초과수익", "해당", "회사", "해당", "나머지", "차이", "90% 구간", "앞", "뒤", "함정%"))
    for name, fn, in [(n, f) for n, f in RULES] + [(n, f) for n, f in COMBO]:
        t = B.rule_test(panel, fn, "ex12m")
        on = [r for r in panel if fn(r)]
        t["trap"] = trap(on)
        (rep["combo"] if name in dict(COMBO) else rep["rules"])[name] = t
        if "diff" not in t:
            print("%-38s %6d  (표본 부족)" % (name, t["n_on"]))
            continue
        print("%-38s %6d %5d %7s %7s %7s %16s %7s %7s %6.1f" % (name, t["n_on"], t["firms_on"], B.fmt(t["on"]), B.fmt(t["off"]), B.fmt(t["diff"]),
                                                              "[%s, %s]" % (B.fmt(t["ci"][0]), B.fmt(t["ci"][1])), B.fmt(t["early"]), B.fmt(t["late"]), t["trap"] or 0))
    print("\n연속값 순위상관(IC) — 12개월 초과수익(달마다 회사끼리)")
    for k, nm in (("psr", "PSR"), ("psr_pct", "PSR 자기 역사"), ("per_pct", "PER 자기 역사"), ("peg", "PEG"), ("roe", "ROE"),
                  ("roe_avg", "ROE 10년 평균"), ("opm_vol", "이익률 흔들림"), ("cfo_ni", "이익의 현금화"), ("munger", "멍거 경고 수"),
                  ("rev_yoy", "매출 증가율"), ("acc", "매출 가속"), ("g5", "매출 5년 연평균")):
        s = W.ic_stats(panel, lambda r, k=k: r.get(k), "ex12m", 12)
        rep["ic"][k] = s
        if s:
            print("  %-14s IC %+.3f  t %+.2f  양(+) %.0f%%  앞 %s  뒤 %s" % (nm, s["ic"], s["t"], s["pos"] * 100, B.fmt(s["early"], 3), B.fmt(s["late"], 3)))
    json.dump(rep, open(os.path.join(OUT, "lens_bt.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


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
    json.dump(panel, open(os.path.join(OUT, "lens_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)
    report(panel)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        report(json.load(open(os.path.join(OUT, "lens_panel.json"), encoding="utf-8")))
    else:
        main()
