# -*- coding: utf-8 -*-
"""
제품 믹스 점검 (2026-10-17) — 밸류체인 캐시의 '주요 제품 등의 현황' 표(years[y].products)를 15년 시계열로 열어도 되나.

관문: 원장 연간 매출과 제품 표 합계가 맞는 회사-연도만 숫자 · 기여도를 화면에 낸다(제품믹스.series 와 같은 규칙 — 이 도구는 그것을 그대로 부른다).
  - 원장 = .cache/landscape/{code}.json rows[].rev (연결, 원). TTM 줄(2026 등)은 뺀다
  - 표 금액은 단위 줄 없이 저장돼 있다(삼성전자 억원 · 대부분 백만원 · 천원). 단위 = 회사마다 하나 — 해마다 따로 골라 원장과 맞은 해들의
    가장 흔한 단위(제품믹스.company_unit). 그 단위로 다시 재서 ±10% 안인 해만 통과. 십억원은 후보에서 뺐다(리뷰 2026-10-17: 십억원으로만 맞은 해가 전부 가짜)
  - 소계 후보 줄은 원장으로 확인한 뒤에만 지운다 · 조정 줄은 음수 · 금액 칸에 비율이 든 표는 비율표 · 금액 비중이 표의 비율 칸과 5%p 넘게 어긋나면 탈락
  - 판정: 통과율이 60% 이상이면 전 종목 시계열로 연다. 아니면 통과 회사-연도만 '검산 통과'로 낸다
이름 이어짐: 이웃한 두 해의 품목 열쇠(부문 + 품목 · 공백 · 기호 뺀 것) 겹침 비율.

캐시만 읽는다(네트워크 0). 결과 → .cache/제품믹스/점검.json, 화면 출력.
실행: python 도구/제품믹스_점검.py
"""
import os, sys, json, glob, re, statistics as st, datetime as dt
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, BASE)
import 제품믹스 as MIX     # noqa: E402

CACHE = os.path.join(BASE, ".cache")
OUT = os.path.join(CACHE, "제품믹스", "점검.json")


def main():
    rows, cont, by_year = [], [], defaultdict(lambda: [0, 0])
    units, why, n_co, cos_pass = Counter(), Counter(), 0, 0
    for f in sorted(glob.glob(os.path.join(CACHE, "밸류체인", "*.json"))):
        code = os.path.basename(f)[:6]
        try:
            vc = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rev = MIX.ledger_revenue(code, CACHE)
        ys = MIX.series(vc, rev)
        if not ys:
            continue
        n_co += 1
        for y in ys:
            rows.append({"code": code, "year": y["year"], "kind": y["kind"], "unit": y["unit_name"], "ratio": y["ratio"],
                         "pass10": y["pass"], "pct_ok": y["pct_ok"], "why": y["why"]})
            if y["kind"] == "amt" and y["rev"]:
                by_year[y["year"]][0] += 1
                by_year[y["year"]][1] += y["pass"]
                if y["pass"]:
                    units[y["unit_name"]] += 1
            if y["why"]:
                why[re.sub(r"\d+", "n", y["why"])] += 1
        if sum(1 for y in ys if y["pass"]) >= 5:
            cos_pass += 1
        for a, b in zip(ys, ys[1:]):
            if b["year"] == a["year"] + 1 and a["keys"] and b["keys"]:
                cont.append(len(set(a["keys"]) & set(b["keys"])) / max(len(a["keys"]), len(b["keys"])))
    amt = [r for r in rows if r["kind"] == "amt"]
    ok_rev = [r for r in amt if r["ratio"] is not None or r["pass10"]]
    led = sum(v[0] for v in by_year.values())
    p10 = sum(v[1] for v in by_year.values())
    res = {
        "made": dt.datetime.now().isoformat(timespec="seconds"), "mix_v": MIX.MIX_V,
        "company_years": len(rows), "amt_tables": len(amt), "with_ledger": led,
        "pass10": p10, "pass10_rate": round(p10 / led, 4) if led else None,
        "pass10_by_year": {y: round(v[1] / v[0], 3) for y, v in sorted(by_year.items()) if v[0]},
        "partial_0.03_0.5": sum(1 for r in ok_rev if r["ratio"] and .03 <= r["ratio"] <= .5),
        "over_1.1": sum(1 for r in ok_rev if r["ratio"] and r["ratio"] > 1.1),
        "units_of_pass": dict(units), "fail_why": dict(why),
        "pct_only": sum(1 for r in rows if r["kind"] == "pct"),
        "pct_only_ok": sum(1 for r in rows if r["kind"] == "pct" and r["pct_ok"]),
        "continuity_median": round(st.median(cont), 3) if cont else None, "continuity_n": len(cont),
        "companies": n_co, "companies_5y_pass": cos_pass,
        "gate": "open" if led and p10 / led >= MIX.GATE else "pass_only",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"summary": res, "rows": rows}, fh, ensure_ascii=False)
    for k, v in res.items():
        print("%-20s %s" % (k, v))


if __name__ == "__main__":
    main()
