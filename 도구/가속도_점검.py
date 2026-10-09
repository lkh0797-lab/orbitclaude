# -*- coding: utf-8 -*-
"""가속도 개편 점검 — (pipe) _pipe_rows 분할 보정이 리팩터 앞뒤로 같은가 · (def) accel 의 B 가 옛 백테스트 B 와 같은가 · (cases) 회귀 사례 · (api) 소비처 응답.
실행: python 도구/가속도_점검.py pipe --save before.json  /  python 도구/가속도_점검.py pipe --compare before.json  /  python 도구/가속도_점검.py def"""
import os, sys, json, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
CODES = ["005930", "010120", "035720", "035420", "003550", "036800", "000210", "042370", "403870", "105560"]


def load_server():
    """서버.py 를 불러오고 캐시된 색인(.cache/색인.json)만 읽어 S.INDEX 에 넣는다 — build_index 는 부르지 않는다(재스캔 · 색인 덮어쓰기 방지).
    서버.py 의 HTTP 서버는 __main__ 아래에 있어 import 로는 뜨지 않는다."""
    sp = ilu.spec_from_file_location("서버", os.path.join(BASE, "서버.py"))
    S = ilu.module_from_spec(sp); sp.loader.exec_module(S)
    with open(S.INDEX_PATH, "r", encoding="utf-8") as fh:
        S.INDEX = json.load(fh)
    return S


def pipe(S):
    out = {}
    for code in CODES:
        c = S.company_by_code(code); corp = S.corp_code_of(code)
        if not c or not corp:
            continue
        mi = S.matrix_cached(c, corp, "IS", "q", S.IS_YEARS); mb = S.matrix_cached(c, corp, "BS", "q", S.QTR_YEARS)
        mc = S.matrix_cached(c, corp, "CF", "q", S.QTR_YEARS)
        pr = S._pipe_rows(c, mi, mb, mc, blog_pts=[])
        if not pr:
            out[code] = None
            continue
        # 앞뒤 비교를 단단히 하려고 brief 의 splits · eps_ttm 에 주식 수(shares) 와 PER(per — cut 이 걸리면 None) 도 담는다
        out[code] = {"splits": pr.get("splits"),
                     "eps": {l: round((pr["rows"][l].get("eps_ttm") or 0), 4) for l in pr["labs"]},
                     "shares": {l: round((pr["rows"][l].get("shares") or 0), 2) for l in pr["labs"]},
                     "per": {l: (None if pr["rows"][l].get("per") is None else round(pr["rows"][l]["per"], 4)) for l in pr["labs"]}}
    return out


def defcheck():
    """품질 · 재작성 · 결산월을 끈 accel 의 B 가 옛 signals() 의 B 와 bt_series 전 회사 · 전 분기에서 같은가.
    입력을 같게 맞춘다 — 매출YoY 는 옛 yoy() 와 같은 식(기저 > 0, 이번 분기 값은 음수도 그대로), 재작성 값(YoY_r)은 없음."""
    sp = ilu.spec_from_file_location("bt", os.path.join(BASE, "도구", "가속기준_백테스트.py"))
    BT = ilu.module_from_spec(sp); sp.loader.exec_module(BT)
    sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
    DRK = ilu.module_from_spec(sp); sp.loader.exec_module(DRK)
    with open(os.path.join(BASE, ".cache", "druck_bt", "bt_series.json"), encoding="utf-8") as fh:
        ser = json.load(fh)
    bad = 0; tot = 0; firms = 0
    for code, co in ser.items():
        rev = {n: v for n, v, _ in co["pts"] if v is not None}
        if not rev:
            continue
        firms += 1
        old = BT.signals(co["pts"])
        pts = [{"n": n, "year": n // 4, "q": n % 4 + 1, "label": "%dQ%d" % (n // 4, n % 4 + 1), "품질": [], "YoY_r": None,
                "매출YoY": ((rev[n] / rev[n - 4] - 1) * 100 if rev.get(n - 4) and rev[n - 4] > 0 and n in rev else None)}
               for n in range(min(rev), max(rev) + 1)]
        DRK.accel(pts)
        for p in pts:
            b0 = (old.get(p["n"]) or {}).get("B")
            if b0 is None and p["가속B"] is None:
                continue
            tot += 1
            if b0 is None or p["가속B"] is None or abs(b0 - p["가속B"]) > 1e-9:
                bad += 1
                if bad <= 5:
                    print("  다름:", code, p["n"], b0, p["가속B"])
    print("회사 %d · B 대조 %d칸 중 다름 %d" % (firms, tot, bad))
    return bad


if __name__ == "__main__":
    if sys.argv[1] == "def":
        sys.exit(1 if defcheck() else 0)
    S = load_server()
    if sys.argv[1] == "pipe":
        res = pipe(S)
        if "--save" in sys.argv:
            path = sys.argv[sys.argv.index("--save") + 1]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False)
            print("저장:", path, len(res), "종목", {k: len(v["splits"]) if v else None for k, v in res.items()})
        else:
            with open(sys.argv[sys.argv.index("--compare") + 1], encoding="utf-8") as fh:
                old = json.load(fh)
            res = json.loads(json.dumps(res, ensure_ascii=False))
            bad = [k for k in sorted(set(res) | set(old)) if res.get(k) != old.get(k)]
            print("다름:", bad or "없음")
