# -*- coding: utf-8 -*-
"""
저평가V2 — 저평가 종목 가운데 차트로 유리한 자리(슈퍼개미가 흔히 쓰는 기술 지침)에 있는 것을 고르면 더 나았나 (2026-10-03)

표본: 도구/저평가_백테스트.py 가 만든 .cache/value/bt_panel.json(공시일마다 · 946곳) + score.json(점수) → 그 시점 등급(저평가 / 관찰).
시세: 재무.fetch_ohlcv(시가 · 고가 · 저가 · 종가 · 거래량, 2010~). 공시일까지의 봉만 쓴다.
필터(정의는 SIGS — 숫자로 고정, 맞추지 않았다):
  좋은 자리  바닥 횡보 뒤 대량 양봉 · 바닥 대량 아래꼬리(투매 받아냄) · 거래 말라붙은 횡보 · 20일선 회복 · 골든크로스(20>60) ·
             정배열 시작 · 저점 높이기(2차 바닥) · 120일선 위
  나쁜 자리  고점 대량 음봉(물량 넘김) · 역배열 하락 중 · 거래대금 부족(하루 3억 미만)
잰다 — 공시 다음 거래일 종가부터 12개월 초과수익(같은 기간 전 종목 중앙값 대비, 2026-10-07 고침 — 6 · 12개월은 저평가 표본 값을 그대로 쓴다). 등급 '저평가' 안 / 후보 전체 안에서 필터 켜짐 − 꺼짐,
회사 단위 부트스트랩 90% 구간, 앞(~2019) · 뒤(2020~). 결과 .cache/value/v2_report.json(서버 · 화면이 읽는다).

실행: python 도구/저평가V2_백테스트.py --fetch   (전 종목 시세 받기, 20~30분)
      python 도구/저평가V2_백테스트.py           (필터 붙이고 보고, 몇 분)
"""
import os
import sys
import json
import bisect
import statistics as st
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
_argv, sys.argv = sys.argv, ["x"]
_spec = importlib.util.spec_from_file_location("vb", os.path.join(HERE, "저평가_백테스트.py"))
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)
sys.argv = _argv
W, S = V.W, V.S
FIN = S.FIN
OUT = V.OUT


# ---------------------------------------------------------------- 기술 신호 — 기술.py(서버와 같은 정의)
_tspec = importlib.util.spec_from_file_location("기술", os.path.join(os.path.dirname(HERE), "기술.py"))
TECH = importlib.util.module_from_spec(_tspec)
_tspec.loader.exec_module(TECH)
tech, SIGS = TECH.tech, TECH.SIGS


def bars(code):
    p = os.path.join(FIN.OHLCV_DIR, code + ".json")
    try:
        return TECH.bars_from(json.load(open(p, encoding="utf-8")))
    except Exception:
        return None


def fetch_all():
    S.build_index() if not S.INDEX.get("companies") else None
    codes = sorted({c["code"] for c in S.INDEX["companies"]})
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(FIN.fetch_ohlcv, k) for k in codes]
        for f in as_completed(futs):
            done += 1
            if done % 100 == 0:
                print("  시세 %d/%d" % (done, len(codes)), flush=True)


def tier_of(r, spec):
    """그 시점 등급 — 저평가_백테스트의 점수 · 빨간불 · 부채 200%↑와 같다."""
    if not V.cand(r):
        return None
    sc = V.score(r, spec["dist"], V.SCORE)
    heavy = r.get("debt_eq") is not None and r["debt_eq"] >= 200
    return "저평가" if (sc is not None and sc >= 50 and not V.red(r) and not heavy) else "관찰"


def main():
    P = json.load(open(os.path.join(OUT, "bt_panel.json"), encoding="utf-8"))
    spec = json.load(open(os.path.join(OUT, "score.json"), encoding="utf-8"))
    by = {}
    for r in P:
        if r.get("ex12m") is not None and r.get("dd") is not None:
            by.setdefault(r["code"], []).append(r)
    rows = []
    for code, rs in by.items():
        B = bars(code)
        if not B:
            continue
        for r in rs:
            t = r.get("tier") or tier_of(r, spec)
            if t is None:
                continue
            i = bisect.bisect_right(B["d"], int(r["date"])) - 1
            if i < 0 or int(W.shift(str(B["d"][i]), 10)) < int(r["date"]):
                continue
            s = tech(B, i)
            if not s:
                continue
            t1 = W.next_day(code, r["date"])   # 공시 다음 거래일 종가(달력 +1일이면 금요일 공시가 그날 종가로 샀다)
            ex = {}
            for nm, days in (("ex1m", 30), ("ex3m", 91)):          # 차트 신호는 짧은 타이밍 도구 — 1 · 3개월도 잰다
                a_, b_ = (W.ret(code, t1, W.shift(t1, days)), W.grp_ret("__all__", t1, W.shift(t1, days))) if t1 else (None, None)
                ex[nm] = a_ - b_ if a_ is not None and b_ is not None else None
            rows.append(dict(r, tier=t, **s, **ex))
    T = [r for r in rows if r["tier"] == "저평가"]
    C = rows
    print("표본 — 후보 %d(%d곳) · 그중 저평가 %d(%d곳)" % (len(C), len({r["code"] for r in C}), len(T), len({r["code"] for r in T})))
    g = V.group(T)
    print("저평가 전체 12개월 초과 중앙 %s · 이긴 %.0f%% · −30%%↓ %.0f%% · 앞 %s 뒤 %s" % (V.fmt(g["median"]), g["hit"], g["crash"], V.fmt(g["early"]), V.fmt(g["late"])))
    rep = {"n_tier": len(T), "firms_tier": len({r["code"] for r in T}), "n_cand": len(C), "tier_all": g, "sigs": {}}
    for scope, rs in (("저평가", T), ("후보", C)):
        for y, ylab in (("ex1m", "1개월"), ("ex3m", "3개월"), ("ex6m", "6개월"), ("ex12m", "12개월")):
            print("\n== %s 안 — 필터 켜짐 − 꺼짐 (%s 초과수익)" % (scope, ylab))
            for k, nm, d in SIGS:
                t = V.test(rs, lambda r, k=k: r.get(k), y=y)
                share = sum(1 for r in rs if r.get(k)) / len(rs) * 100
                key = scope if y == "ex12m" else scope + "_" + y
                rep["sigs"].setdefault(k, {"name": nm, "dir": d})[key] = dict(t, share=share)
                if "diff" in t:
                    print("  %-30s %s %4d건(%4.1f%%) %s vs %s 차이 %s [%s, %s] 앞 %s 뒤 %s 이긴 %.0f%%" % (
                        nm, "+" if d > 0 else "−", t["n_on"], share, V.fmt(t["on"]), V.fmt(t["off"]), V.fmt(t["diff"]),
                        V.fmt(t["ci"][0]), V.fmt(t["ci"][1]), V.fmt(t["early"]), V.fmt(t["late"]), t["hit_on"]))
                else:
                    print("  %-30s 표본 모자람(켜짐 %d)" % (nm, t.get("n_on", 0)))
    for y in ("ex1m", "ex3m", "ex6m"):
        g_ = V.group(T, y)
        rep["tier_all_" + y] = g_
    # V2 규칙 — 6개월 기준 앞뒤 같은 방향인 좋은 신호 하나 이상 + 같은 기준의 나쁜 신호 없음(서버 value2_view 와 같다)
    ok = {}
    for k, nm, d in SIGS:
        t = rep["sigs"][k].get("저평가_ex6m") or {}
        df, e, l_ = t.get("diff"), t.get("early"), t.get("late")
        ok[k] = d != 0 and df is not None and e is not None and l_ is not None and df * d >= 1 and e * d > 0 and l_ * d > 0
    good = [k for k, _, d in SIGS if d > 0 and ok[k]]
    bad = [k for k, _, d in SIGS if d < 0 and ok[k]]
    rep["v2_rule"] = {"good": good, "bad": bad, "eval": {}}
    print("\n== V2 규칙(6개월 기준 검증된 신호) 좋은 %s · 나쁜 %s" % (good, bad))
    fn = lambda r: any(r.get(k) for k in good) and not any(r.get(k) for k in bad)
    for y, ylab in (("ex1m", "1개월"), ("ex3m", "3개월"), ("ex6m", "6개월"), ("ex12m", "12개월")):
        t = V.test(T, fn, y=y)
        rep["v2_rule"]["eval"][y] = t
        if "diff" in t:
            print("  %-6s V2 %4d건(%3d곳) %s vs 나머지 저평가 %s 차이 %s [%s, %s] 앞 %s 뒤 %s 이긴 %.0f%%" % (
                ylab, t["n_on"], t["firms_on"], V.fmt(t["on"]), V.fmt(t["off"]), V.fmt(t["diff"]), V.fmt(t["ci"][0]), V.fmt(t["ci"][1]),
                V.fmt(t["early"]), V.fmt(t["late"]), t["hit_on"]))
    json.dump(rep, open(os.path.join(OUT, "v2_report.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)
    json.dump([{k: r.get(k) for k in ["code", "date", "t", "tier", "ex1m", "ex3m", "ex6m", "ex12m"] + [s[0] for s in SIGS]} for r in rows],
              open(os.path.join(OUT, "v2_panel.json"), "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--fetch":
        fetch_all()
    else:
        main()
