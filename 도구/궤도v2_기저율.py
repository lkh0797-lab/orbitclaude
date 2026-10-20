# -*- coding: utf-8 -*-
"""
궤도 v2 기저율 — (사업 묶음 × 값 자리) 9칸의 과거 12개월 초과수익 (2026-10-21, 스펙 §3 — 미리 정한 규칙, 결과를 보고 바꾸지 않는다)
  격자 = .cache/value/bt_panel.json(저평가 패널 — 2014~2025 보고서 접수일마다 961곳, ex12m = 다음 거래일 진입 · 전 종목 중앙 대비 12개월 초과수익,
         per_pct = 그 접수일까지의 PER 자기 역사 자리). 접수일(date)에 알 수 있던 것만.
  사업 = 가속도 캐시(.cache/druck/{code}.json) 같은 분기 점(label = lab)의 국면 — B기준일 ≤ date(접수일) 인 것만(접수일에 알 수 있던 국면, 리뷰 2026-10-21: 5일 여유를 뺐다) → 궤도v2.biz_group(up · flat · down)
  값   = 궤도v2.val_zone(per_pct) (cheap ≤ 30 · rich ≥ 75 · mid)
  칸마다 n · 회사 수 · 중앙 · 회사 재표본 90%(800회) · 해 재표본 90% · 이긴 비율 · −30%↓ 비율 · ~2019 / 2020~.
  주 지표(돌리기 전에 정함): up·cheap 중앙 − down·rich 중앙. 회사 · 해 재표본 하한이 모두 > 0 이면 "칸이 갈린다", 아니면 "갈리지 않는다".
  한계: 지금 상장사만(생존 편향) · 가속도 캐시 없는 회사 제외 · 국면 없는 행(자료 품질 · 첫 분기) 제외.
실행: py -3.13 -X utf8 도구/궤도v2_기저율.py        결과: .cache/궤도v2/cells.json(화면이 읽는다) · cells.md
"""
import os
import sys
import json
import time
import random
import datetime as dt
import statistics as st
import importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)


def _load(name, path):
    sp = ilu.spec_from_file_location(name, path)
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


O2 = _load("궤도v2", os.path.join(BASE, "궤도v2.py"))
DRK = _load("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
CACHE = os.path.join(BASE, ".cache")
PANEL = os.path.join(CACHE, "value", "bt_panel.json")
DRUCK_DIR = os.path.join(CACHE, "druck")
OUT = os.path.join(CACHE, "궤도v2")
SPLIT = "20200101"
DRK_LAG = 0          # 접수일보다 뒤에 굳은 국면은 안 쓴다(진입이 다음 거래일이라 하루 여유도 두지 않는다)
MIN_SIDE = 20
PRIMARY = ("up·cheap", "down·rich")


def _shift(d, days):
    return (dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(days=days)).strftime("%Y%m%d")


_DRK = {}


def phase_of(code, lab, date):
    """그 분기 점의 국면 — 접수일(date)에 알 수 있던 것(B기준일 ≤ date)만. 없으면 None."""
    if code not in _DRK:
        d = DRK.read_cache(os.path.join(DRUCK_DIR, code + ".json"))
        _DRK[code] = {p.get("label"): p for p in (d or {}).get("points") or [] if p.get("label")}
    p = _DRK[code].get(lab)
    if not p or not p.get("국면"):
        return None
    asb = str(p.get("B기준일") or p.get("기준일") or "")
    if asb and asb > _shift(date, DRK_LAG):
        return None
    return p["국면"]


def build(limit=None):
    with open(PANEL, encoding="utf-8") as fh:
        panel = json.load(fh)
    rows, n_in, n_phase = [], 0, 0
    codes = set()
    for r in panel:
        if r.get("ex12m") is None or not r.get("date") or not r.get("lab"):
            continue
        n_in += 1
        if limit and len(codes) >= limit and r["code"] not in codes:
            continue
        codes.add(r["code"])
        ph = phase_of(r["code"], r["lab"], r["date"])
        if ph is None:
            continue
        n_phase += 1
        biz, val = O2.biz_group(ph), O2.val_zone(r.get("per_pct"))
        rows.append({"code": r["code"], "t": r["date"], "lab": r["lab"], "y": r["ex12m"], "biz": biz, "val": val, "cell": O2.cell(biz, val), "phase": ph})
    return rows, {"panel": len(panel), "with_ex12m": n_in, "with_phase": n_phase, "firms": len({r["code"] for r in rows})}


def _med(xs):
    return st.median(xs) if xs else None


def grp(rows):
    ys = [r["y"] for r in rows]
    return {"n": len(rows), "firms": len({r["code"] for r in rows}), "med": _med(ys),
            "hit": (sum(1 for y in ys if y > 0) / len(ys) * 100) if ys else None, "crash": (sum(1 for y in ys if y <= -30) / len(ys) * 100) if ys else None,
            "early": _med([r["y"] for r in rows if r["t"] < SPLIT]), "late": _med([r["y"] for r in rows if r["t"] >= SPLIT])}


def boot(rows, fn, key, n=800, seed=7):
    """key 단위(회사 · 해) 재표본 90% 구간."""
    by = {}
    for r in rows:
        by.setdefault(key(r), []).append(r)
    ks = sorted(by)
    rnd = random.Random(seed)
    vals = sorted(v for v in (fn([x for k in (rnd.choice(ks) for _ in ks) for x in by[k]]) for _ in range(n)) if v is not None)
    return [vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]] if vals else [None, None]


def cell_stat(rows):
    g = grp(rows)
    if g["n"] >= MIN_SIDE:
        g["ci"] = boot(rows, lambda s: _med([r["y"] for r in s]), lambda r: r["code"])
        g["ci_year"] = boot(rows, lambda s: _med([r["y"] for r in s]), lambda r: r["t"][:4], seed=11)
    else:
        g["ci"] = g["ci_year"] = [None, None]
    return g


def diff_test(rows, a, b):
    sub = [r for r in rows if r["cell"] in (a, b)]
    f = lambda s: (_med([r["y"] for r in s if r["cell"] == a]) - _med([r["y"] for r in s if r["cell"] == b])) if (sum(1 for r in s if r["cell"] == a) >= MIN_SIDE and sum(1 for r in s if r["cell"] == b) >= MIN_SIDE) else None  # noqa: E731
    d = f(sub)
    if d is None:
        return None
    ci, ciy = boot(sub, f, lambda r: r["code"]), boot(sub, f, lambda r: r["t"][:4], seed=11)
    e, l = f([r for r in sub if r["t"] < SPLIT]), f([r for r in sub if r["t"] >= SPLIT])
    four = (ci[0], ciy[0], e, l)
    label = "칸이 갈린다" if all(x is not None and x > 0 for x in four) else ("반대" if all(x is not None and x < 0 for x in (ci[1], ciy[1], e, l)) else "갈리지 않는다")
    return {"a": a, "b": b, "diff": d, "ci": ci, "ci_year": ciy, "early": e, "late": l, "label": label}


def report(rows, meta, secs):
    cells = {}
    for k in [c for c in O2.VERDICT]:
        cells[k] = cell_stat([r for r in rows if r["cell"] == k])
    biz = {b: cell_stat([r for r in rows if r["biz"] == b]) for b in ("up", "flat", "down")}
    val = {v: cell_stat([r for r in rows if r["val"] == v]) for v in ("cheap", "mid", "rich")}
    phases = {p: grp([r for r in rows if r["phase"] == p]) for p in sorted({r["phase"] for r in rows})}
    return {"v": O2.VERSION, "at": time.time(), "secs": round(secs, 1), "rule": __doc__.strip().split("\n")[0],
            "primary_def": "up·cheap 중앙 − down·rich 중앙(12개월 초과수익 %p). 회사 · 해 재표본 90% 하한이 모두 > 0 이고 앞 · 뒤 기간 모두 > 0 이면 '칸이 갈린다'.",
            "primary": diff_test(rows, *PRIMARY), "cells": cells, "biz": biz, "val": val, "phases": phases,
            "n": len(rows), "firms": meta["firms"], "dates": [min(r["t"] for r in rows), max(r["t"] for r in rows)] if rows else None, "meta": meta,
            "limits": ["지금 상장사만(생존 편향) — 상장폐지된 회사의 칸은 없다", "가속도 캐시가 없는 회사 · 국면이 없는 분기(자료 품질 · 첫 분기)는 뺐다",
                       "국면은 접수일에 알 수 있던 것(B기준일 ≤ 접수일)만 · PER 자리는 그 접수일까지의 자기 역사",
                       "국면 · 가속 B 는 지금 캐시의 숫자(뒤에 정정된 재무가 섞였을 수 있다)로 다시 계산한 것",
                       "초과수익 = 전 종목 중앙 대비(같은 날) · 같은 회사가 여러 분기 겹쳐 들어간다(회사 재표본이 이를 감안)",
                       "칸은 지도다 — 어느 칸에 있다는 것이 오른다는 뜻이 아니다"]}


def _p(v, d=1):
    return "—" if v is None else ("%+." + str(d) + "f") % v


def md(rep):
    L = ["# 궤도 v2 기저율 — 9칸 (%s)\n" % dt.datetime.fromtimestamp(rep["at"]).strftime("%Y-%m-%d %H:%M"),
         "%s · 행 %d · 회사 %d · %s~%s · %.0f초\n" % (rep["rule"], rep["n"], rep["firms"], (rep["dates"] or ["", ""])[0], (rep["dates"] or ["", ""])[1], rep["secs"]),
         "\n## 주 지표\n\n%s\n" % rep["primary_def"]]
    p = rep["primary"]
    if p:
        L.append("\n**%s − %s = %s%%p** 회사 90%% [%s, %s] · 해 90%% [%s, %s] · ~2019 %s · 2020~ %s → **%s**\n" % (
            p["a"], p["b"], _p(p["diff"]), _p(p["ci"][0]), _p(p["ci"][1]), _p(p["ci_year"][0]), _p(p["ci_year"][1]), _p(p["early"]), _p(p["late"]), p["label"]))
    else:
        L.append("\n표본 부족\n")
    L.append("\n## 9칸\n\n| 칸 | 행 | 회사 | 중앙 | 90% 회사 | 90% 해 | 이긴 % | −30%↓ % | ~2019 | 2020~ |\n|---|---|---|---|---|---|---|---|---|---|\n")
    for k, c in rep["cells"].items():
        L.append("| %s | %d | %d | %s | [%s, %s] | [%s, %s] | %s | %s | %s | %s |\n" % (
            k, c["n"], c["firms"], _p(c["med"]), _p(c["ci"][0]), _p(c["ci"][1]), _p(c["ci_year"][0]), _p(c["ci_year"][1]),
            "—" if c["hit"] is None else "%.0f" % c["hit"], "—" if c["crash"] is None else "%.0f" % c["crash"], _p(c["early"]), _p(c["late"])))
    for name, key in (("사업 묶음", "biz"), ("값 자리", "val")):
        L.append("\n## %s\n\n| 묶음 | 행 | 회사 | 중앙 | 90%% 회사 | 이긴 %% | ~2019 | 2020~ |\n|---|---|---|---|---|---|---|---|\n" % name)
        for k, c in rep[key].items():
            L.append("| %s | %d | %d | %s | [%s, %s] | %s | %s | %s |\n" % (k, c["n"], c["firms"], _p(c["med"]), _p(c["ci"][0]), _p(c["ci"][1]),
                                                                        "—" if c["hit"] is None else "%.0f" % c["hit"], _p(c["early"]), _p(c["late"])))
    L.append("\n## 국면 7(참고)\n\n| 국면 | 행 | 중앙 | 이긴 % |\n|---|---|---|---|\n")
    for k, c in rep["phases"].items():
        L.append("| %s | %d | %s | %s |\n" % (k, c["n"], _p(c["med"]), "—" if c["hit"] is None else "%.0f" % c["hit"]))
    L.append("\n## 한계\n\n" + "".join("- %s\n" % x for x in rep["limits"]))
    return "".join(L)


def main():
    t0 = time.time()
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    rows, meta = build(limit)
    print("행 %d · 회사 %d (패널 %d · ex12m %d · 국면 %d) %.0f초" % (len(rows), meta["firms"], meta["panel"], meta["with_ex12m"], meta["with_phase"], time.time() - t0), flush=True)
    rep = report(rows, meta, time.time() - t0)
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, "cells.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False)
    os.replace(tmp, os.path.join(OUT, "cells.json"))
    with open(os.path.join(OUT, "cells.md"), "w", encoding="utf-8") as fh:
        fh.write(md(rep))
    p = rep["primary"]
    print("주 지표 %s" % (("%s %+.1f [%+.1f, %+.1f] → %s" % (p["a"] + " − " + p["b"], p["diff"], p["ci"][0], p["ci"][1], p["label"])) if p else "표본 부족"), flush=True)
    for k, c in rep["cells"].items():
        print("  %-11s n %5d  firms %4d  med %s  ci [%s, %s]  hit %s" % (k, c["n"], c["firms"], _p(c["med"]), _p(c["ci"][0]), _p(c["ci"][1]), "—" if c["hit"] is None else "%.0f" % c["hit"]), flush=True)
    print("%.0f초" % (time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
