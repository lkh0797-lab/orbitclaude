# -*- coding: utf-8 -*-
"""
'분기 변화' 파이프라인 판정 규칙이 과거에 맞았나 (2026-10-01)

보고서가 공시된 날(t)마다 그때까지 나온 숫자로 화면의 판정 규칙을 다시 세우고(서버._pipe_rows 를 그대로 부른다), 그 뒤를 잰다.
  (1) 주가 — t 다음 날부터 6·12개월 수익률 − 같은 기간 전 종목 수익률 중앙값(초과수익)
  (2) 매출 — 매출(최근 4분기 합) 전년 대비가 2·4분기 뒤 몇 %p 빨라졌나. 앞단 규칙(잔고 · 선수금 · 생산 · 설비가 매출보다 빠르면
      매출이 따라온다)의 '물리적 시차' 가설을 주가와 따로 직접 잰다.
규칙(화면과 같은 문턱)
  앞단  잔고 − 매출 ≥ +15%p(up) / ≤ −15%p(dn) · 선수금 − 매출 같은 문턱 · 재고+계약자산 − 매출 ≥ +20%p(앞단도 늘면 '생산', 아니면 '쌓임')
  설비  설비 투자(최근 4분기) +50%↑
  가격  순이익(최근 4분기) 전년 대비 − 주가 1년 수익률 ≥ +30%p(덜 따라옴) / ≤ −30%p(앞서 감) — 주가는 공시일까지
  값    공시일 PER(그날 종가 ÷ 최근 4분기 EPS)의 자기 역사 백분위(그 전 분기 말 PER 들, 최근 10년, 8개↑) × PEG(PER ÷ 순이익 성장률 1~100%)
        → 화면과 같은 묶음(둘 다 싸다 · 둘 다 비싸다 · 역사 비싸나 성장 대비 아님 · 싸지만 성장 약함 · 중간대), 이익률 꼭대기(상위 10%) 표시
통계 — 묶음 안/밖 12개월 초과수익 중앙값 차이와 회사 단위 부트스트랩 90% 구간, 앞(~2019)/뒤(2020~) 기간, 연속값은 달마다 순위상관(IC).

재무는 재무.py 캐시만 읽는다(네트워크 차단 — 캐시가 없는 분기는 비어 그 규칙에서 빠진다).
한계 — 지금 상장된 회사만(생존 편향), 재무는 나중 정정값일 수 있다, 주가 분할 보정은 하루 ±30% 넘는 움직임만 고친다.

실행: python 도구/분기변화_백테스트.py      결과: 표준출력 + .cache/quarter/bt_panel.json · bt_report.json
"""
import os
import sys
import json
import math
import bisect
import statistics as st
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("wb", os.path.join(HERE, "억울_백테스트.py"))
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)
S = W.S
FIN = S.FIN
OUT = os.path.join(S.CACHE_DIR, "quarter")
YEARS = list(range(2014, 2027))
LAST_T = "20250930"            # 12개월 뒤가 자료 안에 있어야 한다


# ---------------------------------------------------------------- 네트워크 차단 — 재무 응답은 캐시에 있는 것만
_orig_fetch = FIN.fetch_statement


def _cached_only(corp_code, year, reprt_code, fs_div="CFS"):
    path = os.path.join(FIN.FIN_DIR, "%s_%s_%s_%s.json" % (corp_code, year, reprt_code, fs_div))
    if not os.path.exists(path):
        return {"status": "013", "list": []}
    return _orig_fetch(corp_code, year, reprt_code, fs_div)


FIN.fetch_statement = _cached_only


def prices(code):
    ks, vs = W.PX.get(code, ((), ()))
    if not ks:
        return None
    pr = dict(zip(ks, vs))
    adj = S.SYN._adjusted(pr, list(ks)) if S.SYN is not None else list(vs)
    return {"d": [int(k) for k in ks], "p": adj, "r": list(vs)}


def adj_at(px, t):
    """공시일 보정 종가 — EPS 를 지금 주식 수 기준으로 맞췄으니 주가도 같은 기준(서버._pipe_rows 와 같다)."""
    i = bisect.bisect_right(px["d"], int(t)) - 1
    if i < 0 or int(W.shift(str(px["d"][i]), 10)) < int(t):
        return None
    return px["p"][i]


def qn(lab):
    return int(lab[:4]) * 4 + int(lab[5])


def one(c):
    code = c["code"]
    corp = S.corp_code_of(code)
    px = prices(code)
    if not corp or not px:
        return []
    try:
        mi = FIN.statement_matrix(corp, YEARS, "IS", "q")
        mb = FIN.statement_matrix(corp, YEARS, "BS", "q")
        mc = FIN.statement_matrix(corp, YEARS, "CF", "q")
    except Exception:
        return []
    try:
        blog = S.BACK.company_series(c, S.read_section, max_reports=80) if S.BACK is not None else []
    except Exception:
        blog = []
    macro = None
    if S.MACRO is not None:
        try:
            macro = S.MACRO.for_company(corp, FIN.API_KEY)      # 업종코드(DART) · 수출물가(ECOS) · 출하 · 재고(KOSIS)
        except Exception:
            macro = None
    pr = S._pipe_rows(c, mi, mb, mc, px=px, blog_pts=blog, macro=macro)
    if not pr:
        return []
    labs, R = pr["labs"], pr["rows"]
    filed = {}
    for r in c["reports"]:
        y, m = r["stamp"].split("-")
        if not r["tag"] and m in S.Q_OF_MONTH:
            lab = "%sQ%d" % (y, S.Q_OF_MONTH[m])
            filed[lab] = min(filed.get(lab, "99999999"), r["rcept"][:8])
    by_q = {qn(l): l for l in labs}
    out = []
    for lab in labs:
        t = filed.get(lab)
        if not t or t < "20140101" or t > LAST_T:
            continue
        r = R[lab]
        ry = r.get("rev_yoy")
        # 공시일 값 — 그날 실제 종가 ÷ 최근 4분기 EPS, 그 전 분기 말 PER 들과 견준다
        p_adj = adj_at(px, t)
        et = r.get("eps_ttm")
        per = p_adj / et if p_adj and et and et > 0 else None
        hist = [R[l]["per"] for l in labs if qn(l) < qn(lab) and qn(l) >= qn(lab) - 40 and (R[l].get("per") or 0) > 0]
        per_pct = (sum(1 for v in hist + [per] if v <= per) / (len(hist) + 1) * 100) if per and len(hist) >= 8 else None
        g = r.get("ni_yoy")
        peg = per / min(max(g, 1.0), 100.0) if per and g is not None and g > 0 else None
        px_yoy = W.ret(code, W.shift(t, -365), t)
        t1 = W.shift(t, 1)

        def ex(days):
            a = W.ret(code, t1, W.shift(t1, days))
            b = W.grp_ret("__all__", t1, W.shift(t1, days))
            return a - b if a is not None and b is not None else None

        def fwd(k, key="rev_yoy"):
            l2 = by_q.get(qn(lab) + k)
            v = R[l2].get(key) if l2 else None
            v0 = r.get(key)
            return v - v0 if v is not None and v0 is not None else None
        row = {"code": code, "lab": lab, "t": t[:6] + "15", "date": t,
               "rev_yoy": ry, "blog_yoy": r.get("blog_yoy"), "liab_yoy": r.get("liab_yoy"), "wip_yoy": r.get("wip_yoy"),
               "capex_yoy": r.get("capex_yoy"), "ni_yoy": g, "px_yoy": px_yoy, "per": per, "per_pct": per_pct, "peg": peg,
               "opm_pct": r.get("opm_pct"), "ex6m": ex(182), "ex12m": ex(365), "drev2": fwd(2), "drev4": fwd(4),
               "mp_yoy": r.get("mp_yoy"), "cyc": r.get("cyc"), "dopm4": fwd(4, "opm_ttm")}
        out.append(row)
    return out


# ---------------------------------------------------------------- 규칙 — 화면(_qtr_pipe)과 같은 문턱
def gap(r, k):
    return r[k] - r["rev_yoy"] if r.get(k) is not None and r.get("rev_yoy") is not None else None


def val_cat(r):
    pp, pg = r.get("per_pct"), r.get("peg")
    if pp is None:
        return None
    band = "비싸다" if pp >= 70 else "싸다" if pp <= 30 else "보통"
    gb = None if pg is None else ("싸다" if pg < 1 else "비싸다" if pg > 2 else "보통")
    if band == "비싸다" and gb in ("비싸다", None):
        return "역사·성장 모두 비싸다"
    if band == "비싸다":
        return "역사 비싸나 성장 대비 아님"
    if band == "싸다" and gb == "싸다":
        return "역사·성장 모두 싸다"
    if band == "싸다":
        return "싸지만 성장 약함"
    return "중간대 · PEG " + (gb or "없음")


RULES = [   # (이름, 표본에 해당하나 — True/False/None(판정 불가))
    ("잔고 > 매출 +15%p", lambda r: None if gap(r, "blog_yoy") is None else gap(r, "blog_yoy") >= 15),
    ("잔고 < 매출 −15%p", lambda r: None if gap(r, "blog_yoy") is None else gap(r, "blog_yoy") <= -15),
    ("선수금 > 매출 +15%p", lambda r: None if gap(r, "liab_yoy") is None else gap(r, "liab_yoy") >= 15),
    ("선수금 < 매출 −15%p", lambda r: None if gap(r, "liab_yoy") is None else gap(r, "liab_yoy") <= -15),
    ("재고+계약자산 > 매출 +20%p · 앞단도 늘음",
     lambda r: None if gap(r, "wip_yoy") is None else (gap(r, "wip_yoy") >= 20 and any((gap(r, k) or -1e9) >= 0 for k in ("blog_yoy", "liab_yoy")))),
    ("재고+계약자산 > 매출 +20%p · 앞단은 안 늘음",
     lambda r: None if gap(r, "wip_yoy") is None else (gap(r, "wip_yoy") >= 20 and not any((gap(r, k) or -1e9) >= 0 for k in ("blog_yoy", "liab_yoy")))),
    ("설비 투자 +50%↑", lambda r: None if r.get("capex_yoy") is None else r["capex_yoy"] >= 50),
    ("순이익 − 주가 ≥ +30%p (덜 따라옴)", lambda r: None if r.get("ni_yoy") is None or r.get("px_yoy") is None else r["ni_yoy"] - r["px_yoy"] >= 30),
    ("순이익 − 주가 ≤ −30%p (앞서 감)", lambda r: None if r.get("ni_yoy") is None or r.get("px_yoy") is None else r["ni_yoy"] - r["px_yoy"] <= -30),
    ("PER 자기 역사 하위 30%", lambda r: None if r.get("per_pct") is None else r["per_pct"] <= 30),
    ("PER 자기 역사 상위 30%", lambda r: None if r.get("per_pct") is None else r["per_pct"] >= 70),
    ("PEG < 1", lambda r: None if r.get("per") is None else (r.get("peg") is not None and r["peg"] < 1)),
    ("PEG > 2", lambda r: None if r.get("per") is None else (r.get("peg") is not None and r["peg"] > 2)),
    ("이익률 자기 역사 상위 10%", lambda r: None if r.get("opm_pct") is None else r["opm_pct"] >= 90),
    ("제품 가격(수출물가) +10%↑", lambda r: None if r.get("mp_yoy") is None else r["mp_yoy"] >= 10),
    ("제품 가격(수출물가) −10%↓", lambda r: None if r.get("mp_yoy") is None else r["mp_yoy"] <= -10),
    ("업종 재고 순환 +10%p↑", lambda r: None if r.get("cyc") is None else r["cyc"] >= 10),
    ("업종 재고 순환 −10%p↓", lambda r: None if r.get("cyc") is None else r["cyc"] <= -10),
]
# 업황 × 회사 매출 — 같은 매출 묶음 안에서 업황만 다른 회사와 견준다(매출이 낮던 회사는 원래 반등하기 쉬워 — 평균 회귀를 빼려고).
# (이름, 견줄 묶음, 해당 조건). 화면 판정 줄의 이름과 같다. 업황 숫자 하나만 붙이면 소음이 크고(회사 매출과의 연동도 중앙 0.02~0.18),
# '업종은 움직였는데 회사 매출은 아직'일 때 정보가 있다(도구/업황연결_분석.py).
LOW = lambda r: r.get("rev_yoy") is not None and r["rev_yoy"] <= 5
HIGH = lambda r: r.get("rev_yoy") is not None and r["rev_yoy"] > 5
RULES_IN = [
    ("업황 회복 · 회사 매출 아직(재고 순환 +10%p↑ · 매출 +5%↓)", LOW, lambda r: None if r.get("cyc") is None else r["cyc"] >= 10),
    ("업황 회복 · 회사 매출 이미(재고 순환 +10%p↑ · 매출 +5%↑)", HIGH, lambda r: None if r.get("cyc") is None else r["cyc"] >= 10),
    ("업종 재고 쌓임 · 회사 매출 아직 좋음(재고 순환 −10%p↓ · 매출 +5%↑)", HIGH, lambda r: None if r.get("cyc") is None else r["cyc"] <= -10),
    ("업종 재고 쌓임 · 회사 매출도 약함(재고 순환 −10%p↓ · 매출 +5%↓)", LOW, lambda r: None if r.get("cyc") is None else r["cyc"] <= -10),
    ("업종 가격 상승 · 회사 매출 아직(수출물가 +10%↑ · 매출 +5%↓)", LOW, lambda r: None if r.get("mp_yoy") is None else r["mp_yoy"] >= 10),
    ("업종 가격 상승 · 회사 매출 이미(수출물가 +10%↑ · 매출 +5%↑)", HIGH, lambda r: None if r.get("mp_yoy") is None else r["mp_yoy"] >= 10),
    ("업종 가격 하락 · 회사 매출 아직 좋음(수출물가 −10%↓ · 매출 +5%↑)", HIGH, lambda r: None if r.get("mp_yoy") is None else r["mp_yoy"] <= -10),
]

CONT = [   # 연속값 — 달마다 순위상관(부호로 방향을 읽는다)
    ("잔고 − 매출", lambda r: gap(r, "blog_yoy")), ("선수금 − 매출", lambda r: gap(r, "liab_yoy")),
    ("재고+계약자산 − 매출", lambda r: gap(r, "wip_yoy")), ("설비 투자 증가율", lambda r: r.get("capex_yoy")),
    ("순이익 − 주가", lambda r: (r["ni_yoy"] - r["px_yoy"]) if r.get("ni_yoy") is not None and r.get("px_yoy") is not None else None),
    ("PER 자기 역사 백분위", lambda r: r.get("per_pct")), ("PEG", lambda r: r.get("peg")),
    ("이익률 자기 역사 백분위", lambda r: r.get("opm_pct")),
    ("제품 가격 증가율", lambda r: r.get("mp_yoy")), ("업종 재고 순환", lambda r: r.get("cyc")),
]


def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def rule_test(rows, fn, y):
    rs = [dict(r, _f=fn(r)) for r in rows if r.get(y) is not None]
    rs = [r for r in rs if r["_f"] is not None]
    on = [r for r in rs if r["_f"]]
    off = [r for r in rs if not r["_f"]]
    if len(on) < 20 or len(off) < 20:
        return {"n_on": len(on)}

    def diff(sub):
        a = [r[y] for r in sub if r["_f"]]
        b = [r[y] for r in sub if not r["_f"]]
        return st.median(a) - st.median(b) if len(a) >= 8 and len(b) >= 8 else None
    lo, hi = W.boot(rs, diff, n=500)
    return {"n_on": len(on), "firms_on": len({r["code"] for r in on}), "n_off": len(off),
            "on": st.median([r[y] for r in on]), "off": st.median([r[y] for r in off]),
            "hit_on": sum(r[y] > 0 for r in on) / len(on) * 100, "diff": diff(rs), "ci": [lo, hi],
            "early": diff([r for r in rs if r["t"] < W.SPLIT]), "late": diff([r for r in rs if r["t"] >= W.SPLIT]),
            "n_early": sum(1 for r in on if r["t"] < W.SPLIT)}


def main():
    os.makedirs(OUT, exist_ok=True)
    comps = [c for c in S.INDEX["companies"] if c.get("code")]
    panel = []
    for i, c in enumerate(comps, 1):
        try:
            panel += one(c)
        except Exception as e:
            print("  %s 실패: %s" % (c["code"], e), flush=True)
        if i % 50 == 0:
            print("  %d/%d · 표본 %d" % (i, len(comps), len(panel)), flush=True)
    json.dump(panel, open(os.path.join(OUT, "bt_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)
    report(panel)


def fmt(v, d=1):
    return "—" if v is None else ("%+.*f" % (d, v))


def report(panel):
    print("\n표본 %d (회사 %d) · 공시일 %s ~ %s" % (len(panel), len({r["code"] for r in panel}),
                                              min(r["date"] for r in panel), max(r["date"] for r in panel)))
    rep = {"n": len(panel), "firms": len({r["code"] for r in panel}), "rules": {}, "cont": {}, "val": {}}
    for y, lab in (("ex12m", "12개월 초과수익(중앙값, %p)"), ("drev4", "4분기 뒤 매출 증가율 변화(중앙값, %p)"),
                   ("dopm4", "4분기 뒤 영업이익률 변화(중앙값, %p)")):
        print("\n== 규칙 · " + lab)
        print("%-34s %7s %6s %8s %8s %8s %16s %8s %8s" % ("규칙", "해당", "회사", "해당", "나머지", "차이", "90% 구간", "앞", "뒤"))
        for name, fn, base in [(n, f, None) for n, f in RULES] + [(n, f, b) for n, b, f in RULES_IN]:
            t = rule_test([r for r in panel if base is None or base(r)], fn, y)
            rep["rules"].setdefault(name, {})[y] = t
            if "diff" not in t:
                print("%-34s %7d  (표본 부족)" % (name, t["n_on"]))
                continue
            print("%-34s %7d %6d %8s %8s %8s %16s %8s %8s" % (name, t["n_on"], t["firms_on"], fmt(t["on"]), fmt(t["off"]), fmt(t["diff"]),
                                                          "[%s, %s]" % (fmt(t["ci"][0]), fmt(t["ci"][1])), fmt(t["early"]), fmt(t["late"])))
    print("\n== 연속값 순위상관(IC) — 12개월 초과수익")
    for name, fx in CONT:
        s = W.ic_stats(panel, fx, "ex12m", 12)
        rep["cont"][name] = s
        if s:
            print("%-22s IC %+.3f  t %+.2f  날짜 %d  양(+) %.0f%%  앞 %s  뒤 %s" % (name, s["ic"], s["t"], s["n_dates"], s["pos"] * 100,
                                                                         fmt(s["early"], 3), fmt(s["late"], 3)))
    print("\n== 값 묶음(화면 판정과 같은 규칙) — 12개월 초과수익")
    cats = {}
    for r in panel:
        k = val_cat(r)
        if k and r.get("ex12m") is not None:
            cats.setdefault(k, []).append(r)
    for k, rs in sorted(cats.items(), key=lambda kv: -len(kv[1])):
        v = [r["ex12m"] for r in rs]
        pk = [r["ex12m"] for r in rs if (r.get("opm_pct") or 0) >= 90]
        npk = [r["ex12m"] for r in rs if r.get("opm_pct") is not None and r["opm_pct"] < 90]
        lo, hi = W.boot(rs, lambda sub: med([x["ex12m"] for x in sub]), n=400)
        rep["val"][k] = {"n": len(v), "firms": len({r["code"] for r in rs}), "med": med(v), "ci": [lo, hi],
                         "hit": sum(x > 0 for x in v) / len(v) * 100, "peak_med": med(pk), "peak_n": len(pk), "nopeak_med": med(npk)}
        print("%-24s n %5d 회사 %4d  중앙 %6s [%s, %s]  이긴 비율 %4.0f%%  · 이익률 꼭대기 %s(n %d) / 아님 %s"
              % (k, len(v), len({r["code"] for r in rs}), fmt(med(v)), fmt(lo), fmt(hi), sum(x > 0 for x in v) / len(v) * 100,
                 fmt(med(pk)), len(pk), fmt(med(npk))))
    json.dump(rep, open(os.path.join(OUT, "bt_report.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        report(json.load(open(os.path.join(OUT, "bt_panel.json"), encoding="utf-8")))
    else:
        main()
