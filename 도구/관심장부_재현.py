# -*- coding: utf-8 -*-
"""
관심 장부 알림량 재현 (2026-10-17) — 만들기 전 관문: 장부에 넣은 종목 하나가 한 달에 알림을 몇 건 받나.

30곳(가속도 캐시가 있는 회사에서 코드 순서로 고르게 뽑음)을 2019-01 ~ 마지막 달까지 달마다 다시 돌린다.
달 끝(그달 마지막 날)에 그때 알 수 있던 사실만 만든다:
  - 가속도: points 중 기준일 · B기준일 ≤ 그날(관심장부.druck_facts cut) — 값은 지금 정정본 기준(공시 당시 숫자 그대로는 아님)
  - 수주잔고: .cache/수주 의 보고서별 값 중 접수일 ≤ 그날, 최근 12개 → 수주.trend
  - PER 자리: 풍경 quarters 의 per 중 filed ≤ 그날(8개↑) 대비 그날 종가 ÷ 그때 알던 마지막 EPS
  - 수출: series_long 중 그날 전달까지(관세청은 다음 달 15일께 낸다), 마지막 공시 분기 = 그날까지 낸 마지막 정기보고서
  - 새 정기보고서: 수집 폴더 이름의 접수번호(정정 빼고)
  - 공시 위험: 과거 판이 없어 뺀다(매일 덮어쓴다) — 실제 알림은 이보다 조금 많다
가설은 틀 9개를 모두 기본 문턱으로 단다(가장 시끄러운 경우). 숫자 = 회사 · 달마다 알림 수.
관문(검증 에이전트 제안): 회사 · 달 중앙값이 2건을 넘으면 범위를 줄인다.
가짜 변화(식 버전 · 정정 · 013 · 관세청 다시 쓰기)는 이 재현에 나오지 않는다 — 지금 값으로 다시 만들었기 때문. 그 몫은 실제 운영 4주로 잰다.

캐시만 읽는다(네트워크 0). 결과 → .cache/관심장부/재현.json
실행: python 도구/관심장부_재현.py [--n 30]
"""
import os, sys, json, glob, re, bisect, statistics as st, datetime as dt, importlib.util as ilu
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
CACHE = os.path.join(BASE, ".cache")


def _mod(name, file):
    sp = ilu.spec_from_file_location(name, os.path.join(BASE, file))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


W = _mod("관심장부", "관심장부.py")
DRK = _mod("드러켄밀러", "드러켄밀러.py")
BACK = _mod("수주", "수주.py")
EXPM = _mod("수출추적", "수출추적.py")
LAND_V = 10
REG = ("사업보고서", "반기보고서", "분기보고서")


def reports_of(code):
    """수집 폴더 이름 → [{stamp, label, rcept, tag}] (접수 순). '[정정]' 은 tag."""
    ds = glob.glob(os.path.join(BASE, "기업추적_수집", "*_" + code))
    if not ds:
        return []
    out = []
    for n in os.listdir(ds[0]):
        m = re.match(r"^(\[[^\]]+\])?_?(\d{4}-\d{2})_(.+?)_(\d{14})$", n)
        if not m:
            continue
        out.append({"tag": m.group(1) or "", "stamp": m.group(2), "label": m.group(3), "rcept": m.group(4)})
    return sorted(out, key=lambda r: r["rcept"])


def month_ends(a, b):
    y, m = a
    while (y, m) <= b:
        nx = dt.date(y + (m == 12), m % 12 + 1, 1)
        yield (nx - dt.timedelta(days=1)).strftime("%Y%m%d")
        y, m = nx.year, nx.month


def q_of(stamp):
    y, mm = int(stamp[:4]), int(stamp[5:7])
    return "%dQ%d" % (y, (mm - 1) // 3 + 1)


def main():
    n_pick = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 30
    codes = sorted(os.path.basename(p)[:6] for p in glob.glob(os.path.join(CACHE, "druck", "*.json")))
    step = max(1, len(codes) // n_pick)
    pick = codes[::step][:n_pick]
    exp = {}
    try:
        exp = {x["code"]: x for x in json.load(open(os.path.join(CACHE, "수출추적", "result.json"), encoding="utf-8")).get("items", [])}
    except Exception:
        pass
    last_m = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    per_cm, kinds, levels, per_co = [], Counter(), Counter(), {}
    hyps = [{"id": "h_" + t["key"], "tpl": t["key"]} for t in W.TEMPLATES]
    for code in pick:
        d = DRK.read_cache(os.path.join(CACHE, "druck", code + ".json"))
        if not d:
            continue
        reps = reports_of(code)
        regs = [r for r in reps if not r["tag"] and r["label"] in REG]
        try:
            bcache = json.load(open(os.path.join(CACHE, "수주", code + ".json"), encoding="utf-8"))
        except Exception:
            bcache = {}
        try:
            land = json.load(open(os.path.join(CACHE, "landscape", code + ".json"), encoding="utf-8"))
        except Exception:
            land = {}
        qs = [q for q in (land.get("quarters") or []) if q.get("filed")]
        try:
            px = json.load(open(os.path.join(CACHE, "price", code + ".json"), encoding="utf-8"))
        except Exception:
            px = {}
        pk = sorted(px)
        x = exp.get(code)
        mon = (x or {}).get("series_long") or (x or {}).get("series") or {}
        stt, cnt = None, []
        for t in month_ends((2019, 1), (last_m.year, last_m.month)):
            facts = W.druck_facts(d, cut=t)
            # 수주잔고
            known = [r for r in regs if r["rcept"][:8] <= t][-12:]
            pts = []
            for r in known:
                h = bcache.get(r["rcept"])
                if h and h.get("v") == BACK.VERSION and h.get("value"):
                    pts.append({"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"], "value": h["value"],
                                "method": h.get("method"), "verified": h.get("verified"), "source": h.get("source")})
            if pts:
                tr = BACK.trend(BACK._drop_outliers(pts))
                facts.update(W.backlog_facts(tr, BACK.VERSION, facts.get("rev_yoy"), as_of=(tr or {}).get("to")))
            # PER 자리
            hist = [q["per"] for q in qs if q["filed"] <= t and q.get("per") is not None]
            lastq = next((q for q in reversed(qs) if q["filed"] <= t and q.get("eps") and q["eps"] > 0), None)
            i = bisect.bisect_right(pk, t) - 1
            if len(hist) >= 8 and lastq and i >= 0:
                per = px[pk[i]] / lastq["eps"]
                pct = sum(1 for v in hist if v <= per) / len(hist) * 100
                facts["per_pct"] = W.F(round(pct, 1), t, "l10", "", True)
            # 수출
            if x and x.get("status") == "ok" and mon:
                lim = (dt.datetime.strptime(t, "%Y%m%d").date().replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")
                cutm = {k: v for k, v in mon.items() if k <= lim}
                lrq = q_of(known[-1]["stamp"]) if known else None
                al = EXPM.aligned(cutm, lrq, None) if cutm else None
                facts.update(W.export_facts(x, al, 1))
            if known:
                facts.update(W.filing_fact(known[-1]))
            stt, ev = W.step(stt, facts, hyps, t)
            cnt.append(len(ev))
            for e in ev:
                kinds[e["kind"]] += 1
                levels[e["level"]] += 1
        per_cm.extend(cnt)
        per_co[code] = {"months": len(cnt), "events": sum(cnt), "per_month": round(sum(cnt) / max(1, len(cnt)), 2)}
    res = {"made": dt.datetime.now().isoformat(timespec="seconds"), "companies": len(per_co), "company_months": len(per_cm),
           "median_per_company_month": st.median(per_cm) if per_cm else None,
           "mean_per_company_month": round(sum(per_cm) / len(per_cm), 3) if per_cm else None,
           "p90_per_company_month": sorted(per_cm)[int(len(per_cm) * .9)] if per_cm else None,
           "max_per_company_month": max(per_cm) if per_cm else None,
           "share_months_over_2": round(sum(1 for c in per_cm if c > 2) / len(per_cm), 4) if per_cm else None,
           "by_kind": dict(kinds), "by_level": dict(levels), "per_company": per_co,
           "gate": "pass" if per_cm and st.median(per_cm) <= 2 else "fail",
           "caveats": ["공시 위험은 과거 판이 없어 뺐다", "가짜 변화(버전 · 정정 · 013 · 관세청 다시 쓰기)는 지금 값으로 다시 만들어 나오지 않는다 — 운영 4주로 잰다",
                       "가설 9개를 모두 단 가장 시끄러운 경우"]}
    os.makedirs(os.path.join(CACHE, "관심장부"), exist_ok=True)
    with open(os.path.join(CACHE, "관심장부", "재현.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    for k in ("companies", "company_months", "median_per_company_month", "mean_per_company_month", "p90_per_company_month",
              "max_per_company_month", "share_months_over_2", "by_kind", "by_level", "gate"):
        print("%-28s %s" % (k, res[k]))


if __name__ == "__main__":
    main()
