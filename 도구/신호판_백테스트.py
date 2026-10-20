# -*- coding: utf-8 -*-
"""
신호판 백테스트 — 근거 신호가 2개↑ 켜진 회사가 1개만 켜진 회사보다 12개월 뒤 나았나 (2026-10-20, 스펙 §3 — 미리 정한 규칙, 결과를 보고 바꾸지 않는다)
  탭 하나하나는 이미 쟀다. 여기서 새로 재는 건 **겹침이 보태는 몫**이다.
격자   = .cache/value/bt_panel.json(저평가 패널 — 2014-04~2025-09 보고서 접수일마다 961곳, ex12m = 다음 거래일 진입 · 전 종목 중앙 대비). 접수일(date)에 알 수 있던 것만.
신호   = 신호판.string — 서버와 같은 함수. 재료 시점 재현:
  값    행 per_pct(분기 패널 자기 역사 백분위) · 눌림 행의 저평가 후보 · 빨간불 · 부채 · 점수(value/score.json 가중 · 분포 — 분포는 표본 전체 것, 표본 안 재현)
  엇갈림 · 자홍  .cache/druck 같은 분기 점(label = lab, 기준일 ≤ date+5일): TTM 영업이익률 − 4분기 전, 분기 말 주가 1년 변화(네이버 수정주가)
  수주 · 둔화    .cache/시너지/bt_panel.json 월말 행(date 이전 45일 안) — 그 월말 믿을 수 있는 행끼리 시너지.score → 수주 부분
  사슬  .cache/밸류체인 date 에 접수된 마지막 보고서 매출처 표(비중 10%↑ · 수집 회사로 이어지는 이름) 중 3개월 수익률 전 종목 상위 10% 고객
  위험  시너지_백테스트.risk_s12(12개월 희석 · 부실, 2013-12-31 이후) — 작전주 꼴 · KIS 는 시점 재현 없음(못 넣는다)
  참고  실적 A = 행 op_yoy ≥ 20 & rev_yoy ≥ 5, B = druck 영업이익_TTM 이 앞 12분기↑ 최대보다 큼 · 수출 = 수출선행/bt_rows 단서(date 이전 45일) · 글 = 궤도 요약 그 보고서 배수 ≥ 1.5
주 지표 M1 = 빨간불 없는 행에서 K ≥ 2 중앙 − K = 1 중앙. 회사 재표본 90%(W.boot) · 해 재표본 90%(boot_year) · ~2019 / 2020~.
  라벨: 넷(회사 하한 · 해 하한 · 앞 · 뒤) 모두 > 0 '근거 있음' · 모두 < 0 '반대' · 그 밖 '근거 약함'.
보조(결론엔 안 씀): K 묶음표 · M2(눌림 켜진 행 안 둘째 신호) · 수주 관측 가능한 행 안 M1 · 신호 쌍 10 · 참고 보태는 몫 · 빨간불 확인 · 겹침(자카드) · 덮임.
실행: py -3.13 도구/신호판_백테스트.py        결과: .cache/신호판/bt.json(화면이 읽는다) · bt.md
"""
import os
import sys
import json
import bisect
import time
import datetime as dt
import statistics as st
import importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("시너지_백테스트", os.path.join(HERE, "시너지_백테스트.py"))
SB = ilu.module_from_spec(_sp)
_sp.loader.exec_module(SB)
W, S, SYN = SB.W, SB.S, SB.SYN
_kp = ilu.spec_from_file_location("신호판", os.path.join(BASE, "신호판.py"))
KM = ilu.module_from_spec(_kp)
_kp.loader.exec_module(KM)

OUT = os.path.join(S.CACHE_DIR, "신호판")
VAL_PANEL = os.path.join(S.CACHE_DIR, "value", "bt_panel.json")
VAL_SCORE = os.path.join(S.CACHE_DIR, "value", "score.json")
SYN_PANEL = os.path.join(S.CACHE_DIR, "시너지", "bt_panel.json")
EXL_ROWS = os.path.join(S.CACHE_DIR, "수출선행", "bt_rows.json")
VC_DIR = os.path.join(S.CACHE_DIR, "밸류체인")
SYN_LAG, EXL_LAG, DRK_LAG = 45, 45, 5
EXL_FROM = "20220801"
MIN_SIDE = 6


def J(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- 재료 시점 재현
def _load_syn():
    """시너지 월말 패널 → {code: [(t, row) …]} — 월말마다 믿을 수 있는 행끼리 시너지.score 를 돌려 수주 부분을 붙인다(서버 _run_synergy 와 같은 함수)."""
    rows = J(SYN_PANEL)
    by_t = {}
    for r in rows:
        r.setdefault("flags", [])
        r.setdefault("reliable", False)          # 옛 패널 행엔 키가 없다(= 믿을 수 없음)
        by_t.setdefault(r["t"], []).append(r)
    for t, g in by_t.items():
        SYN.score(g)
    by = {}
    for r in rows:
        by.setdefault(r["code"], []).append((r["t"], r))
    for v in by.values():
        v.sort(key=lambda x: x[0])
    return by


def _asof(lst, d, lag):
    """[(날짜, x) …] 오름차순에서 날짜 ≤ d 이고 d − 날짜 ≤ lag 일인 마지막 x."""
    if not lst:
        return None
    i = bisect.bisect_right([x[0] for x in lst], d) - 1
    if i < 0:
        return None
    t, x = lst[i]
    return x if W.shift(t, lag) >= d else None


def _qend(label):
    y, q = int(label[:4]), int(label[5:])
    return "%04d%02d%02d" % (y, 3 * q, (31, 30, 30, 31)[q - 1])


_DRK = {}


def _druck(code):
    """{label: {dm, dp, ttm_hi, op_yoy_f, rev_yoy_f, known, n}} — 분기마다 엇갈림 재료 · TTM 신고점 여부."""
    if code in _DRK:
        return _DRK[code]
    d = S._druck_read(code)
    out = {}
    pts = sorted((p for p in (d or {}).get("points") or [] if p.get("n") is not None), key=lambda p: p["n"])
    by_n = {p["n"]: p for p in pts}

    def m_of(p):
        a, b = p.get("영업이익_TTM"), p.get("매출_TTM")
        return a / b * 100 if (a is not None and b) and b > 0 else None
    for p in pts:
        n, lab = p["n"], p.get("label")
        if not lab:
            continue
        m0, p4 = m_of(p), by_n.get(n - 4)
        m4 = m_of(p4) if p4 else None
        qe = _qend(lab)
        dp = W.ret(code, W.shift(qe, -365), qe)
        prev = [q.get("영업이익_TTM") for q in pts if q["n"] < n and q.get("영업이익_TTM") is not None]
        ttm = p.get("영업이익_TTM")
        out[lab] = {"dm": (m0 - m4) if (m0 is not None and m4 is not None) else None, "dp": dp, "known": str(p.get("기준일") or ""),
                    "B": bool(ttm is not None and len(prev) >= 12 and ttm > max(prev)), "label": lab}
    _DRK[code] = out
    return out


_ORB = {}


def _orbit(code):
    """{접수일: (x, tier, label, stamp)} — 궤도 요약 캐시(평소 대비 배수)."""
    if code in _ORB:
        return _ORB[code]
    c = S.company_by_code(code)
    rows = S._orbit_sum_rows(c) if c else None
    out = {}
    if rows:
        S.orbit_scale(rows)
        for r in rows:
            if r.get("x") is not None and not r.get("tag"):
                out[r["rcept"][:8]] = (r["x"], r.get("tier"), r.get("label"), r.get("stamp"))
    _ORB[code] = out
    return out


_NAMES = {"d": None}


def _names():
    if _NAMES["d"] is None:
        _NAMES["d"] = S._listed_names()
    return _NAMES["d"]


def _link(nm):
    """매출처 이름 → 수집 회사 코드(서버 valuechain_view.link 의 한글 쪽만 — 영문 별명 색인은 안 쓴다)."""
    import re
    cn = S._vc_canon(nm)
    names = _names()
    for cand in (cn, re.sub(r"\(\*+\)|\s*본사$|\(주\)|㈜|주식회사", "", nm or "").strip()):
        cd = names.get(S._norm_corp(cand))
        if cd and cd in W.PX:
            return cd
    return None


_VC = {}


def _vc(code):
    """[(접수일, [(고객코드, 이름, 비중) …], 해) …] 접수일 순 — 밸류체인 캐시 해마다 매출처 표."""
    if code in _VC:
        return _VC[code]
    out = []
    try:
        d = J(os.path.join(VC_DIR, code + ".json"))
    except Exception:
        d = {}
    for y, dy in (d.get("years") or {}).items():
        rc = str(dy.get("rcept") or "")
        if len(rc) < 8:
            continue
        custs = []
        for x in dy.get("customers") or []:
            if x.get("kind") != "named" or (x.get("pct") or 0) < KM.TH["chain_pct"]:
                continue
            cd = _link(x["name"])
            if cd and cd != code:
                custs.append((cd, x["name"], x["pct"]))
        out.append((rc[:8], custs, y))
    out.sort(key=lambda x: x[0])
    _VC[code] = out
    return out


_P3 = {}


def _p3(date):
    """date 기준 3개월 수익률 전 종목 백분위 {code: pct}."""
    if date in _P3:
        return _P3[date]
    rs = {c: v for c in W.PX for v in [W.ret(c, W.shift(date, -91), date)] if v is not None}
    f = SYN._pct_rank(list(rs.values()))
    _P3[date] = {c: f(v) for c, v in rs.items()}
    return _P3[date]


def _val_tier(r, spec, fin):
    """저평가 등급 재현 — 후보(PER ≤ 200 · 순이익 1년 ≥ −5 · 52주 −25%↓) · 빨간불 없음 · 부채 < 200(비금융) · 점수 ≥ 50 → 저평가, 후보인데 못 넘으면 관찰, 후보 아니면 None."""
    dd, ni, per = r.get("dd"), r.get("ni_yoy"), r.get("per")
    if dd is None or dd > KM.TH["dd"]:
        return None, None, []
    cand = per is not None and per <= 200 and ni is not None and ni >= KM.TH["ni"]
    if not cand:
        return "후보 밖", None, []
    red = []
    bg = (r.get("blog_yoy") - r["rev_yoy"]) if (r.get("blog_yoy") is not None and r.get("rev_yoy") is not None) else None
    lg = (r.get("liab_yoy") - r["rev_yoy"]) if (r.get("liab_yoy") is not None and r.get("rev_yoy") is not None) else None
    if bg is not None and bg <= -15:
        red.append("잔고가 매출보다 느리다")
    if lg is not None and lg <= -15:
        red.append("선수금이 매출보다 느리다")
    if r.get("mp_yoy") is not None and r["mp_yoy"] <= -10:
        red.append("업종 제품 가격 하락")
    if r.get("cyc") is not None and r.get("rev_yoy") is not None and r["cyc"] <= -10 and r["rev_yoy"] > 5:
        red.append("업종 재고 쌓임")
    if r.get("debt_eq") is not None and r["debt_eq"] >= 200 and not fin:
        red.append("부채비율 200%↑")
    tot = wsum = 0.0
    for wt in spec.get("weights") or []:
        k = wt["key"]
        if fin and k in ("debt_eq", "rev_yoy"):
            continue
        sv, v = spec["dist"].get(k) or [], r.get(k)
        if v is None or not sv:
            continue
        pc = (bisect.bisect_left(sv, v) + bisect.bisect_right(sv, v)) / 2 / len(sv) * 100
        tot += (pc if wt["dir"] > 0 else 100 - pc) * wt["w"]
        wsum += wt["w"]
    score = tot / wsum if wsum >= 2 else None
    tier = "저평가" if (not red and not fin and score is not None and score >= KM.TH["score"]) else "관찰"
    return tier, score, red


def build(limit=None):
    t0 = time.time()
    VP = [r for r in J(VAL_PANEL) if r.get("ex12m") is not None and r.get("date") and r.get("lab")]
    VP.sort(key=lambda r: (r["date"], r["code"]))
    if limit:
        VP = VP[:limit]
    spec = J(VAL_SCORE)
    SPB = _load_syn()
    EX = {}
    try:
        for x in J(EXL_ROWS):
            EX.setdefault(x["code"], []).append((x["d"], x))
        for v in EX.values():
            v.sort(key=lambda x: x[0])
    except Exception:
        EX = {}
    print("격자 %d행 · 시너지 %d곳 · 수출 %d곳 — %.0f초" % (len(VP), len(SPB), len(EX), time.time() - t0), flush=True)
    rows = []
    for i, r in enumerate(VP):
        code, date, lab = r["code"], r["date"], r["lab"]
        if date < SB._RISK_FROM:
            continue
        fin = bool(S.VAL_FIN.search(W.IND.get(code) or ""))
        # 수주 · 둔화
        sr = _asof(SPB.get(code, []), date, SYN_LAG)
        syn = None
        if sr is not None:
            syn = {"reliable": bool(sr.get("reliable")), "p_su": (sr.get("parts") or {}).get("수주"), "stage": sr.get("stage"), "btb": sr.get("btb"), "cover_chg": sr.get("cover_chg")}
        # 엇갈림 · 자홍 · 실적 B
        dk = _druck(code).get(lab)
        gap = None
        if dk and dk["known"] and dk["known"] <= W.shift(date, DRK_LAG):
            gap = {"dm": dk["dm"], "dp": dk["dp"], "label": lab}
        # 값 · 눌림
        val = {"per": r.get("per"), "pct": r.get("per_pct"), "n": None}
        tier, score, red = _val_tier(r, spec, fin)
        dip = None if tier is None else {"tier": tier, "score": score, "dd": r.get("dd"), "ni_yoy": r.get("ni_yoy"), "red": red, "fell": True}
        # 사슬
        vc = _vc(code)
        chain = None
        hit = [x for x in vc if x[0] <= date]
        if hit:
            _, custs, y = hit[-1]
            if custs:
                p3 = _p3(date)
                chain = {"custs": [{"code": cd, "name": nm, "pct": pct, "p3": p3.get(cd)} for cd, nm, pct in custs], "year": y}
        # 참고 — 실적 · 수출 · 글
        earn = None
        if r.get("op_yoy") is not None or (dk and dk.get("B")):
            earn = {"A": bool(r.get("op_yoy") is not None and r.get("rev_yoy") is not None and r["op_yoy"] >= KM.TH["op_yoy"] and r["rev_yoy"] >= KM.TH["rev_yoy"]),
                    "B": bool(dk and dk.get("B")), "op_yoy": r.get("op_yoy"), "rev_yoy": r.get("rev_yoy"), "fin": fin}
        exp = None
        if code in EX and date >= EXL_FROM:
            ex = _asof(EX[code], date, EXL_LAG)
            exp = {"clue": bool(ex), "grade": (ex or {}).get("grade"), "cur": (ex or {}).get("cur")}
        ob = _orbit(code)
        text = None
        for dd_ in (date, W.shift(date, -1), W.shift(date, 1), W.shift(date, -2), W.shift(date, 2), W.shift(date, -3), W.shift(date, 3)):
            if dd_ in ob:
                x, tier_t, label_t, stamp = ob[dd_]
                text = {"x": x, "tier": tier_t, "label": label_t, "stamp": stamp}
                break
        flags = SYN.risk_flags(SB.risk_s12(code, date))
        inp = {"code": code, "syn": syn, "gap": gap, "val": val, "dip": dip, "chain": chain, "earn": earn, "exp": exp, "text": text,
               "risk": {"level": None, "flags": flags, "kis": []}}
        s = KM.string(inp)
        rows.append({"code": code, "t": r["t"], "date": date, "y": r["ex12m"], "k": s["k"], "k_ref": s["k_ref"], "n_known": s["n_known"],
                     "on": {k: b["on"] for k, b in s["beads"].items()}, "known": {k: b["known"] for k, b in s["beads"].items()},
                     "gated": s["gated"], "gates": [g["key"] for g in s["gates"]]})
        if i % 3000 == 0:
            print("  %d/%d — %.0f초" % (i, len(VP), time.time() - t0), flush=True)
    print("신호 줄 %d행 · 회사 %d곳 — %.0f초" % (len(rows), len({r["code"] for r in rows}), time.time() - t0), flush=True)
    return rows


# ---------------------------------------------------------------- 재기
def _med(xs):
    return st.median(xs) if xs else None


def _diff_fn(fa, fb):
    def f(sub):
        a = [r["y"] for r in sub if fa(r)]
        b = [r["y"] for r in sub if fb(r)]
        return (st.median(a) - st.median(b)) if (len(a) >= MIN_SIDE and len(b) >= MIN_SIDE) else None
    return f


def grp(rows):
    ys = [r["y"] for r in rows]
    return {"n": len(rows), "firms": len({r["code"] for r in rows}), "med": _med(ys), "mean": (sum(ys) / len(ys)) if ys else None,
            "hit": (sum(1 for y in ys if y > 0) / len(ys) * 100) if ys else None, "crash": (sum(1 for y in ys if y <= -30) / len(ys) * 100) if ys else None,
            "early": _med([r["y"] for r in rows if r["t"] < W.SPLIT]), "late": _med([r["y"] for r in rows if r["t"] >= W.SPLIT])}


def test(rows, fa, fb, label=True):
    """fa 묶음 중앙 − fb 묶음 중앙 · 회사 · 해 재표본 90% · 앞/뒤 · 라벨."""
    f = _diff_fn(fa, fb)
    sub = [r for r in rows if fa(r) or fb(r)]
    if sum(1 for r in sub if fa(r)) < MIN_SIDE or sum(1 for r in sub if fb(r)) < MIN_SIDE:
        return None
    c, yr = W.boot(sub, f), SB.boot_year(sub, f)
    e, l = f([r for r in sub if r["t"] < W.SPLIT]), f([r for r in sub if r["t"] >= W.SPLIT])
    four = (c[0], yr[0], e, l)
    four_hi = (c[1], yr[1], e, l)
    lab = None
    if label:
        if all(x is not None and x > 0 for x in four):
            lab = "근거 있음"
        elif all(x is not None and x < 0 for x in four_hi):
            lab = "반대"
        else:
            lab = "근거 약함"
    return {"diff": f(sub), "ci": list(c), "ci_year": list(yr), "early": e, "late": l, "a": grp([r for r in sub if fa(r)]), "b": grp([r for r in sub if fb(r)]), "label": lab}


def jaccard(rows, a, b):
    x = sum(1 for r in rows if r["on"][a] and r["on"][b])
    u = sum(1 for r in rows if r["on"][a] or r["on"][b])
    return (x / u) if u else None


def report(rows):
    clear = [r for r in rows if not r["gated"]]
    rep = {"v": KM.VERSION, "at": dt.datetime.now().isoformat(timespec="seconds"), "grid": "value/bt_panel.json 보고서 접수일",
           "dates": [min(r["date"] for r in rows), max(r["date"] for r in rows)], "n": len(rows), "firms": len({r["code"] for r in rows}),
           "n_clear": len(clear), "risk_from": SB._RISK_FROM, "base_keys": KM.BASE_KEYS, "ref_keys": KM.REF_KEYS,
           "primary_def": "빨간불(12개월 희석 · 부실 · 둔화 · 자홍) 없는 행에서 근거 신호(수주 · 엇갈림 · 값 · 눌림 · 사슬) 2개↑ 켜진 묶음의 12개월 초과수익 중앙 − 1개 켜진 묶음의 중앙. "
                          "회사 · 해 재표본 90% 하한 > 0 이고 ~2019 · 2020~ 둘 다 > 0 이면 '근거 있음', 넷 다 < 0 이면 '반대', 그 밖은 '근거 약함'. 자료 없는 신호는 꺼짐으로 센다."}
    k2, k1, k0 = (lambda r: r["k"] >= 2), (lambda r: r["k"] == 1), (lambda r: r["k"] == 0)
    rep["primary"] = test(clear, k2, k1)
    rep["k_groups"] = {("K=%d" % k if k < 3 else "K≥3"): grp([r for r in clear if (r["k"] == k if k < 3 else r["k"] >= 3)]) for k in (0, 1, 2, 3)}
    rep["k2_vs_k0"] = test(clear, k2, k0, label=False)
    rep["k1_vs_k0"] = test(clear, k1, k0, label=False)
    dipon = [r for r in clear if r["on"]["dip"]]
    rep["m2_dip_second"] = test(dipon, lambda r: r["k"] >= 2, lambda r: r["k"] == 1, label=False)
    rep["su_known"] = test([r for r in clear if r["known"]["su"]], k2, k1, label=False)
    rep["all_known"] = test([r for r in clear if r["n_known"] >= 4], k2, k1, label=False)
    pairs = {}
    for i, a in enumerate(KM.BASE_KEYS):
        for b in KM.BASE_KEYS[i + 1:]:
            both = lambda r, a=a, b=b: r["on"][a] and r["on"][b]
            only = lambda r, a=a, b=b: r["on"][a] != r["on"][b]
            pairs["%s+%s" % (a, b)] = {"test": test(clear, both, only, label=False), "jaccard": jaccard(clear, a, b),
                                       "n_both": sum(1 for r in clear if both(r))}
    rep["pairs"] = pairs
    ref = {}
    k1p = [r for r in clear if r["k"] >= 1]
    for key in KM.REF_KEYS:
        sub = [r for r in k1p if r["known"][key]]
        ref[key] = test(sub, lambda r, key=key: r["on"][key], lambda r, key=key: not r["on"][key], label=False)
    rep["ref_addon"] = ref
    base_addon = {}
    for key in KM.BASE_KEYS:
        sub = [r for r in clear if r["known"][key] and (r["k"] - (1 if r["on"][key] else 0)) >= 1]
        base_addon[key] = test(sub, lambda r, key=key: r["on"][key], lambda r, key=key: not r["on"][key], label=False)
    rep["base_addon"] = base_addon
    k1all = [r for r in rows if r["k"] >= 1]
    rep["gate_check"] = {"all": test(k1all, lambda r: r["gated"], lambda r: not r["gated"], label=False)}
    for g in KM.GATES:
        rep["gate_check"][g["key"]] = test(k1all, lambda r, g=g: g["key"] in r["gates"], lambda r: not r["gated"], label=False)
    cov = {}
    for key in [b["key"] for b in KM.BEADS]:
        cov[key] = {"known": sum(1 for r in rows if r["known"][key]), "on": sum(1 for r in rows if r["on"][key]),
                    "by_year": {y: [sum(1 for r in rows if r["t"][:4] == y and r["known"][key]), sum(1 for r in rows if r["t"][:4] == y and r["on"][key])]
                                for y in sorted({r["t"][:4] for r in rows})}}
    rep["coverage"] = cov
    rep["gates_n"] = {g["key"]: sum(1 for r in rows if g["key"] in r["gates"]) for g in KM.GATES}
    rep["limits"] = [
        "지금 상장된 회사만(생존 편향) — 수준이 부풀어 있다. 묶음끼리 차이로만 읽는다",
        "눌림 점수 분포(value/score.json)와 시너지 수주 부분은 표본 전체에서 고른 것 — 표본 안 재현",
        "작전주 꼴 · KIS 상태 · 차트 · 리포트는 과거 시점 재현이 없어 빨간불 · 참고에 못 넣었다(빨간불은 12개월 희석 · 부실 · 둔화 · 자홍만)",
        "값 신호는 2017년 전 거의 빈칸(PER 자기 역사 8분기↑), 수출은 2022-08 뒤만, 사슬은 지금 파서 · 지금 이름 잇기(영문 별명 없음)",
        "보고서 접수일 격자라 같은 회사가 해마다 4번 겹친다 — 회사 · 해 재표본으로 감안. 자료 없는 신호는 꺼짐으로 세므로 자료가 많은 회사가 K 가 높기 쉽다(수주 관측 행 · 넷↑ 관측 행 표로 확인)",
    ]
    return rep


def _p(v, d=1):
    return "—" if v is None else ("%+." + str(d) + "f") % v


def _ci(c):
    return "—" if not c or c[0] is None else "[%s, %s]" % (_p(c[0]), _p(c[1]))


def _tline(name, t):
    if not t:
        return "| %s | — | | | | | |\n" % name
    return "| %s | %s | %s | %s | %s | %s | %d / %d | %s |\n" % (name, _p(t["diff"]), _ci(t["ci"]), _ci(t["ci_year"]), _p(t["early"]), _p(t["late"]), t["a"]["n"], t["b"]["n"], t.get("label") or "")


def md(rep):
    o = ["# 신호판 백테스트 — %s\n\n" % rep["at"][:16].replace("T", " "),
         "격자 %s %s~%s · %d행 · %d곳 · 빨간불 없는 행 %d. 주 지표: %s\n\n" % (rep["grid"], rep["dates"][0], rep["dates"][1], rep["n"], rep["firms"], rep["n_clear"], rep["primary_def"]),
         "| 비교 | 차이(%p) | 90% 회사 | 90% 해 | ~2019 | 2020~ | 행 a / b | 라벨 |\n|---|---|---|---|---|---|---|---|\n",
         _tline("**M1 K≥2 − K=1**", rep["primary"]), _tline("K≥2 − K=0", rep["k2_vs_k0"]), _tline("K=1 − K=0", rep["k1_vs_k0"]),
         _tline("M2 눌림 켜진 행 안 K≥2 − K=1", rep["m2_dip_second"]), _tline("수주 관측 행 안 K≥2 − K=1", rep["su_known"]), _tline("넷↑ 관측 행 안 K≥2 − K=1", rep["all_known"]),
         "\n## K 묶음(빨간불 없음)\n\n| 묶음 | 행 | 회사 | 중앙 | 이긴 % | −30%↓ % | ~2019 | 2020~ |\n|---|---|---|---|---|---|---|---|\n"]
    for k, g in rep["k_groups"].items():
        o.append("| %s | %d | %d | %s | %s | %s | %s | %s |\n" % (k, g["n"], g["firms"], _p(g["med"]), _p(g["hit"], 0), _p(g["crash"], 0), _p(g["early"]), _p(g["late"])))
    o.append("\n## 신호 쌍 — 둘 다 켜짐 − 하나만 켜짐 (빨간불 없음)\n\n| 쌍 | 둘 다 행 | 차이 | 90% 회사 | ~2019 | 2020~ | 자카드 |\n|---|---|---|---|---|---|---|\n")
    for k, p in rep["pairs"].items():
        t = p["test"]
        o.append("| %s | %d | %s | %s | %s | %s | %s |\n" % (k, p["n_both"], _p(t["diff"]) if t else "—", _ci(t["ci"]) if t else "—", _p(t["early"]) if t else "—", _p(t["late"]) if t else "—", "—" if p["jaccard"] is None else "%.2f" % p["jaccard"]))
    o.append("\n## 신호 하나가 보태는 몫 — 다른 근거 신호 1개↑ 켜진 행 안에서 켜짐 − 꺼짐\n\n| 신호 | 차이 | 90% 회사 | 90% 해 | ~2019 | 2020~ | 행 |\n|---|---|---|---|---|---|---|\n")
    for key in KM.BASE_KEYS + KM.REF_KEYS:
        t = (rep["base_addon"] if key in rep["base_addon"] else rep["ref_addon"]).get(key)
        o.append("| %s%s | %s | %s | %s | %s | %s | %s |\n" % (KM.BEAD_BY[key]["name"], "" if key in KM.BASE_KEYS else "(참고)", _p(t["diff"]) if t else "—", _ci(t["ci"]) if t else "—", _ci(t["ci_year"]) if t else "—", _p(t["early"]) if t else "—", _p(t["late"]) if t else "—", ("%d / %d" % (t["a"]["n"], t["b"]["n"])) if t else "—"))
    o.append("\n## 빨간불 확인 — K≥1 행에서 빨간불 있음 − 없음(음수여야)\n\n| 빨간불 | 차이 | 90% 회사 | ~2019 | 2020~ | 행 |\n|---|---|---|---|---|---|\n")
    for k, t in rep["gate_check"].items():
        o.append("| %s | %s | %s | %s | %s | %s |\n" % (k, _p(t["diff"]) if t else "—", _ci(t["ci"]) if t else "—", _p(t["early"]) if t else "—", _p(t["late"]) if t else "—", ("%d / %d" % (t["a"]["n"], t["b"]["n"])) if t else "—"))
    o.append("\n## 덮임 — 신호마다 관측 가능 / 켜짐 행\n\n| 신호 | 관측 | 켜짐 |\n|---|---|---|\n")
    for key, c in rep["coverage"].items():
        o.append("| %s | %d | %d |\n" % (KM.BEAD_BY[key]["name"], c["known"], c["on"]))
    o.append("\n## 한계\n\n" + "".join("- %s\n" % x for x in rep["limits"]))
    return "".join(o)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    rows = build(a.limit)
    rep = report(rows)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False)
    with open(os.path.join(a.out, "bt_rows.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    text = md(rep)
    with open(os.path.join(a.out, "bt.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
