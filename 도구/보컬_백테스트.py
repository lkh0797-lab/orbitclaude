# -*- coding: utf-8 -*-
"""
보컬 깔때기(보컬.py)가 과거에 맞았나 (2026-10-08)

2013-01 ~ 마지막 봉 하루 전까지 **매 거래일**, 그날까지의 봉만으로 ①~⑦을 다시 돌린다(거래대금 순위 · 테마 점유율도 그날 전 시장 기준).
  신호(⑦) → 다음 날 시가 진입(시가가 전날 종가보다 +15% 넘게 뜨면 못 산 것으로) → 규칙 청산:
  종가가 눌림 저점(손절)을 깨면 다음 날 시가 · 고가가 직전 고점(목표)에 닿으면 그 값 · 보유 한도(눌림목 10봉 · 단기 5봉)면 종가.
  잰다 — 승률 · 평균 · 중앙 · 손익비(수익 팩터 = 이익 합 ÷ 손실 합) · 평균 이익 · 평균 손실 · 최대 연속 손실 · 청산 사유 ·
         5 · 10 · 20일 초과수익(진입가 대비, 같은 날 전 시장 중앙값 빼고) · 앞(~2019) / 뒤(2020~) · 해마다.
  단계별 기여 — 전체 규칙(대장 · 거래량 감소 · 손익비 1.5↑) / 테마 필터 없이(풀 전체) / 대장 조건 없이(강한 테마 멤버면) /
                거래량 감소 없이 / 손익비 조건 없이. 지지선 종류별.
  같은 종목이 보유 중에 다시 신호를 내면 '겹침'으로 빼고 센다(한 눌림에 거래 하나). 시가가 목표 위 · 손절 아래로 뜨면 못 산 것으로. 자료 끝에 걸려 보유 한도를 못 채우는 신호는 뺀다.
한계 — 오늘 테마 분류표를 과거에 적용(2015년엔 없던 테마가 과거에도 있는 셈) · 지금 상장사만(급등주 상폐 누락 → 실제보다 좋게) ·
       수수료 · 슬리피지 없음 · 일봉뿐. 숫자는 규칙끼리 견주는 용도.

실행: python 도구/보컬_백테스트.py            (패널 읽기 1분 · 계산 5~10분)
      python 도구/보컬_백테스트.py --report   (저장한 신호로 표만)
결과: .cache/vocal/bt_report.json(화면이 읽는다) · bt_signals.json
"""
import os
import sys
import json
import bisect
import datetime as dt
import statistics as st
import importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
OUT = os.path.join(BASE, ".cache", "vocal")
START = 20130101
SPLIT = 20200101
H = (5, 10, 20)


def load_vocal():
    sp = ilu.spec_from_file_location("보컬", os.path.join(BASE, "보컬.py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def panel(V):
    L = json.load(open(os.path.join(OUT, "listing.json"), encoding="utf-8"))["stocks"]
    M = json.load(open(os.path.join(BASE, ".cache", "업종", "map.json"), encoding="utf-8"))["stocks"]
    print("패널 읽는 중 — %d곳" % len(L), flush=True)
    P = V.load_panel(sorted(L), {k: v["name"] for k, v in L.items()}, {k: (M.get(k) or {}).get("themes") for k in L},
                     progress=lambda a, b: print("  %d/%d" % (a, b), flush=True))
    print("미리 더하는 중", flush=True)
    P.precompute(top_max=max(m["top"] for m in V.MODES.values()))
    return P


def trade(B, j, stop, target, hold, gap_skip):
    """신호봉 j → 다음 날 시가 진입, 규칙 청산. skip = 못 샀다 — gap(시가 +15%↑) · above_target(시가가 목표 위) · below_stop(시가가 손절 아래) ·
    partial(보유 한도까지 봉이 없다 — 자료 끝). 청산 순서: 보유 한도(종가) → 시가가 목표 위면 시가 → 고가가 목표에 닿으면 목표 → 종가가 손절 아래면 다음 날 시가."""
    o, h, c = B["o"], B["h"], B["c"]
    if j + 1 + hold > len(c) - 1:
        return {"skip": "partial"}
    entry = o[j + 1]
    if not entry:
        return {"skip": "partial"}
    if entry / c[j] - 1 > gap_skip:
        return {"skip": "gap", "gap": (entry / c[j] - 1) * 100}
    if entry >= target:
        return {"skip": "above_target"}
    if entry < stop:
        return {"skip": "below_stop"}
    for k in range(j + 1, j + hold + 1):
        if k - j >= hold:
            return {"entry": entry, "exit": c[k], "days": k - j, "why": "time"}
        if k > j + 1 and o[k] >= target:
            return {"entry": entry, "exit": o[k], "days": k - j, "why": "target"}
        if h[k] >= target:
            return {"entry": entry, "exit": target, "days": k - j, "why": "target"}
        if c[k] < stop:
            return {"entry": entry, "exit": o[k + 1], "days": k - j + 1, "why": "stop"}
    return {"entry": entry, "exit": c[j + hold], "days": hold, "why": "time"}


_MKT = {}


def market_fwd(P, gi, h):
    """그날 다음 날 시가 → h 봉 뒤 종가, 전 시장 중앙값(%)."""
    key = (gi, h)
    if key in _MKT:
        return _MKT[key]
    rets = []
    d = P.gd[gi]
    for B in P.bars.values():
        j = bisect.bisect_left(B["d"], d)
        if j < len(B["d"]) and B["d"][j] == d and j + 1 + h < len(B["c"]) and B["o"][j + 1]:
            rets.append(B["c"][j + 1 + h] / B["o"][j + 1] - 1)
    v = st.median(rets) * 100 if len(rets) >= 50 else None
    _MKT[key] = v
    return v


def build(V, P):
    D = len(P.gd)
    g0 = bisect.bisect_left(P.gd, START)
    sigs = []
    t0 = dt.datetime.now()
    hist = {mode: V.LeadHistory(P, mode) for mode in V.MODES}
    open_until = {}                                   # (mode, code) → 보유가 끝나는 gi. 보유 중 다시 나온 신호는 '겹침'으로 빼고 센다
    for gi in range(g0, D - 1):
        for mode, M in V.MODES.items():
            pool = P.pool(gi, M["top"])
            hist[mode].at(gi)
            if gi - g0 == 0:
                for k in range(max(0, gi - 60), gi):   # 첫날 앞 급등 구간의 대장 이력
                    hist[mode].at(k)
            for code in pool:
                j = P.loc(code, gi)
                if j is None:
                    continue
                B = P.bars[code]
                f = V.funnel(B, j, P.in_rank(code, M["top"]), mode)
                if not f or not f.get("sig_nodry"):
                    continue
                tr = trade(B, j, f["stop"], f["target"], M["hold"], V.GAP_SKIP)
                if gi <= open_until.get((mode, code), -1):
                    tr = {"skip": "open"}
                elif tr and "entry" in tr:
                    open_until[(mode, code)] = gi + tr["days"]
                lead, n_theme = hist[mode].during(code, int(f["lk"]), P.gd[gi], P.theme_of.get(code, ()))
                row = {"mode": mode, "code": code, "gi": gi, "date": str(P.gd[gi]), "lead": bool(lead), "lead_days": len(lead),
                       "in_theme": n_theme > 0, "theme_days": n_theme, "dry": bool(f["dry_prev"]),
                       "rr": f.get("rr"), "support": (f.get("touched") or ["?"])[0], "gain": f["gain"], "depth": f["depth"], "days": f["days"],
                       "reflow_x": f.get("reflow_x"), "trade": tr}
                if tr and "entry" in tr:
                    row["ret"] = (tr["exit"] / tr["entry"] - 1) * 100
                    for h in H:
                        if j + 1 + h < len(B["c"]):
                            mk = market_fwd(P, gi, h)
                            row["ex%d" % h] = (B["c"][j + 1 + h] / tr["entry"] - 1) * 100 - mk if mk is not None else None
                sigs.append(row)
        if (gi - g0) % 250 == 0:
            print("  %s 신호 %d · %s" % (P.gd[gi], len(sigs), str(dt.datetime.now() - t0).split(".")[0]), flush=True)
    json.dump(sigs, open(os.path.join(OUT, "bt_signals.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return sigs


# ---------------------------------------------------------------- 통계
def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def fmt(v, d=1):
    return "—" if v is None else "%+.*f" % (d, v)


def fpf(x):
    """손익비 — 손실이 하나도 없으면 ∞."""
    return "∞" if x.get("pf") is None and x.get("n") and not x.get("n_loss") else fmt(x.get("pf"), 2)


def stats(rows):
    tr = [r for r in rows if r.get("ret") is not None]
    sk = [(r.get("trade") or {}).get("skip") for r in rows]
    out = {"n_signals": len(rows), "n_filled": len(tr), "n_skipped_gap": sk.count("gap"),
           "skipped": {k: sk.count(k) for k in ("gap", "above_target", "below_stop", "partial", "open")}}
    if not tr:
        out["trades"] = {"n": 0}
        return out
    rets = [r["ret"] for r in tr]
    wins = [x for x in rets if x > 0]
    loss = [x for x in rets if x <= 0]
    streak = best = 0
    for r in sorted(tr, key=lambda r: r["date"]):
        streak = streak + 1 if r["ret"] <= 0 else 0
        best = max(best, streak)
    sub = lambda rs: {"n": len(rs), "win": sum(1 for r in rs if r["ret"] > 0) / len(rs) * 100 if rs else None,
                      "avg": sum(r["ret"] for r in rs) / len(rs) if rs else None}
    out["trades"] = {"n": len(tr), "win": len(wins) / len(tr) * 100, "avg": sum(rets) / len(rets), "med": st.median(rets),
                     "pf": (sum(wins) / -sum(loss)) if loss and sum(loss) < 0 else None, "n_loss": len(loss),
                     "avg_win": sum(wins) / len(wins) if wins else None, "avg_loss": sum(loss) / len(loss) if loss else None,
                     "max_loss_streak": best, "avg_days": sum(r["trade"]["days"] for r in tr) / len(tr),
                     "exit": {k: sum(1 for r in tr if r["trade"]["why"] == k) for k in ("stop", "target", "time")},
                     "early": sub([r for r in tr if int(r["date"]) < SPLIT]), "late": sub([r for r in tr if int(r["date"]) >= SPLIT])}
    out["fwd"] = {}
    for h in H:
        v = [r.get("ex%d" % h) for r in tr if r.get("ex%d" % h) is not None]
        out["fwd"][str(h)] = {"ex": med(v), "hit": sum(1 for x in v if x > 0) / len(v) * 100 if v else None, "n": len(v)}
    return out


def small(rows):
    tr = [r for r in rows if r.get("ret") is not None]
    if not tr:
        return {"n": 0}
    rets = [r["ret"] for r in tr]
    wins, loss = [x for x in rets if x > 0], [x for x in rets if x <= 0]
    return {"n": len(tr), "win": len(wins) / len(tr) * 100, "avg": sum(rets) / len(rets), "med": st.median(rets),
            "pf": (sum(wins) / -sum(loss)) if loss and sum(loss) < 0 else None, "n_loss": len(loss)}


def report(V, sigs, P=None):
    rep = {"made": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "dates": [min(r["date"] for r in sigs), max(r["date"] for r in sigs)] if sigs else None,
           "n_days": len({r["date"] for r in sigs}), "modes": {}}
    for mode, M in V.MODES.items():
        rows = [r for r in sigs if r["mode"] == mode]
        full = [r for r in rows if r["lead"] and r["dry"] and (r.get("rr") or 0) >= V.RR_MIN]
        S = stats(full)
        S["variants"] = {
            "전체 규칙(대장 · 거래량 감소 · 손익비 1.5↑)": small(full),
            "테마 필터 없이(풀 전체)": small([r for r in rows if r["dry"] and (r.get("rr") or 0) >= V.RR_MIN]),
            "대장 조건 없이(강한 테마 멤버)": small([r for r in rows if r["in_theme"] and r["dry"] and (r.get("rr") or 0) >= V.RR_MIN]),
            "거래량 감소 없이": small([r for r in rows if r["lead"] and (r.get("rr") or 0) >= V.RR_MIN]),
            "손익비 조건 없이": small([r for r in rows if r["lead"] and r["dry"]]),
        }
        sup = {}
        for r in full:
            sup.setdefault(r["support"], []).append(r)
        S["by_support"] = {k: small(v) for k, v in sorted(sup.items(), key=lambda kv: -len(kv[1]))}
        yrs = {}
        for r in full:
            yrs.setdefault(r["date"][:4], []).append(r)
        S["by_year"] = {k: small(v) for k, v in sorted(yrs.items())}
        rep["modes"][mode] = S
        T = S.get("trades") or {}
        print("\n== %s(거래대금 %d위) — 신호 %d · 체결 %d · 못 삼 %s" % (M["name"], M["top"], S["n_signals"], S["n_filled"],
                                                            " ".join("%s %d" % kv for kv in S["skipped"].items())))
        if T.get("n"):
            print("  승률 %.0f%% · 평균 %s · 중앙 %s · 손익비 %s · 평균 이익 %s · 평균 손실 %s · 최대 연속 손실 %d · 평균 %.1f봉 · 청산 손절 %d / 목표 %d / 시간 %d"
                  % (T["win"], fmt(T["avg"]), fmt(T["med"]), fpf(T), fmt(T["avg_win"]), fmt(T["avg_loss"]), T["max_loss_streak"], T["avg_days"],
                     T["exit"]["stop"], T["exit"]["target"], T["exit"]["time"]))
            print("  앞(~2019) n %d 승률 %s 평균 %s · 뒤(2020~) n %d 승률 %s 평균 %s" % (
                T["early"]["n"], fmt(T["early"]["win"], 0), fmt(T["early"]["avg"]), T["late"]["n"], fmt(T["late"]["win"], 0), fmt(T["late"]["avg"])))
            print("  초과수익 중앙(진입가 대비 − 전 시장): " + " · ".join("%d일 %s(이긴 %s)" % (int(h), fmt(x["ex"]), fmt(x["hit"], 0)) for h, x in S["fwd"].items()))
        print("  단계별:")
        for k, v in S["variants"].items():
            print("    %-34s n %5d · 승률 %s · 평균 %s · 중앙 %s · 손익비 %s" % (k, v["n"], fmt(v.get("win"), 0), fmt(v.get("avg")), fmt(v.get("med")), fpf(v)))
        print("  지지선별:")
        for k, v in S["by_support"].items():
            print("    %-12s n %5d · 승률 %s · 평균 %s · 손익비 %s" % (k, v["n"], fmt(v.get("win"), 0), fmt(v.get("avg")), fpf(v)))
        print("  해마다: " + " · ".join("%s n %d %s" % (k, v["n"], fmt(v.get("avg"))) for k, v in S["by_year"].items()))
    json.dump(rep, open(os.path.join(OUT, "bt_report.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)
    return rep


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    V = load_vocal()
    os.makedirs(OUT, exist_ok=True)
    if "--report" in sys.argv:
        sigs = json.load(open(os.path.join(OUT, "bt_signals.json"), encoding="utf-8"))
    else:
        P = panel(V)
        sigs = build(V, P)
    report(V, sigs)
