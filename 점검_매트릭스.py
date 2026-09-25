# -*- coding: utf-8 -*-
"""
변화 브리핑 재무 매트릭스 공백 점검.

같은 계정이 여러 줄로 갈라지거나(키 표류), 중간 연도가 비거나, 핵심 계정이
통째로 없는 경우를 전 종목(또는 표본)에서 찾아 원인별로 묶는다.

    python 점검_매트릭스.py                # 업종별 층화 표본 200곳
    python 점검_매트릭스.py --all          # 수집된 전 종목
    python 점검_매트릭스.py --n 60         # 표본 크기

찾는 것
  split   같은 개념인데 두 줄로 갈라짐. 한 줄이 끝나는 해에 다른 줄이 시작.
          (삼성전기 매출액: ifrs_Revenue 2017~18 / ifrs-full_Revenue 2019~)
  hole    값 - 빈칸 - 값. 그 해 재무제표는 있는데 이 계정만 빔.
  core    그 해 재무제표는 있는데 매출·영업이익·자산총계 같은 핵심 계정이 없음.
  metric  변화 브리핑 재무지표 15종 중 비는 항목.
"""
import os
import re
import sys
import json
import time
import random
import difflib
import importlib.util as ilu
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def load(name):
    spec = ilu.spec_from_file_location(name, os.path.join(BASE, name + ".py"))
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


FIN = load("재무")
YEARS = list(range(2011, 2026))
OUT = os.path.join(BASE, ".cache", "점검")

# 핵심 계정은 태그로 먼저 찾고, 없으면 이름으로 찾는다.
# 이름만으로 찾았더니 '당기순손익'(원익IPS 2023~) 을 못 알아보고 없다고 했다.
CORE = {
    "IS": [("매출", {"t:Revenue"}, r"^(매출액|수익\(매출액\)|영업수익|매출|수익)$"),
           ("영업이익", {"t:OperatingIncomeLoss", "t:ProfitLossFromOperatingActivities"},
            r"^영업(이익|손익|손실)"),
           ("당기순이익", {"t:ProfitLoss"}, r"^(연결)?당기(연결)?순(이익|손익|손실)")],
    "BS": [("자산총계", {"t:Assets"}, r"^자산총계$"),
           ("부채총계", {"t:Liabilities"}, r"^부채총계$"),
           ("자본총계", {"t:Equity"}, r"^자본총계$")],
    "CF": [("영업활동현금흐름", {"t:CashFlowsFromUsedInOperatingActivities"}, r"영업활동")],
}
CORE = {k: [(n, tags, re.compile(p)) for n, tags, p in v] for k, v in CORE.items()}


def corp_map():
    import html
    data = open(os.path.join(BASE, ".cache", "CORPCODE.xml"), "rb").read() \
        .decode("utf-8", errors="replace")
    out = {}
    for m in re.finditer(r"<list>(.*?)</list>", data, re.S):
        b = m.group(1)
        s = re.search(r"<stock_code>(.*?)</stock_code>", b, re.S)
        c = re.search(r"<corp_code>(.*?)</corp_code>", b, re.S)
        n = re.search(r"<corp_name>(.*?)</corp_name>", b, re.S)
        if s and s.group(1).strip():
            out[s.group(1).strip()] = (c.group(1).strip(), html.unescape(n.group(1)).strip())
    return out


def collected_codes():
    d = os.path.join(BASE, "기업추적_수집")
    out = []
    for nm in os.listdir(d):
        m = re.match(r"^(.+)_([0-9][0-9A-Z]{5})$", nm)
        if m:
            out.append(m.group(2))
    return out


def sample(codes, n):
    """업종 대분류별로 고르게 뽑는다. 금융은 재무제표 구조가 달라 넉넉히 넣는다."""
    smap_p = os.path.join(BASE, ".cache", "업종", "map.json")
    try:
        stocks = json.load(open(smap_p, encoding="utf-8"))["stocks"]
    except Exception:
        random.seed(7)
        return random.sample(codes, min(n, len(codes)))
    by = defaultdict(list)
    for c in codes:
        by[stocks.get(c, {}).get("sector", "기타")].append(c)
    random.seed(7)
    picked = []
    per = max(4, n // max(len(by), 1))
    for sec, lst in by.items():
        k = per * 2 if sec == "금융" else per
        picked += random.sample(lst, min(k, len(lst)))
    return picked[:max(n, len(picked))]


def norm(nm):
    n = re.sub(r"\((손실|순손실|이익|포괄손익)\)", "", nm)
    n = re.sub(r"계속영업|중단영업|연결|별도|지배기업|의\s", "", n)
    return re.sub(r"\s+", "", n)


def tag_tail(key):
    if key.startswith("t:"):
        return key[2:]
    return None


def same_concept(a, b):
    """같은 계정인가. 이름 유사도는 쓰지 않는다 — 0.75 기준이 '자본금'과
    '자본잉여금'을 같다고 봐서 오탐이 수천 건 나왔다. 병합 규칙과 같은
    기준(정규화 이름이 같거나 태그 이름이 같음)만 본다."""
    if FIN._merge_name(a["name"]) == FIN._merge_name(b["name"]):
        return "이름"
    ta, tb = tag_tail(a["key"]), tag_tail(b["key"])
    if ta and tb and ta == tb:
        return "태그"
    return None


def cover(row):
    return [i for i, x in enumerate(row["values"]) if x["v"] is not None]


def audit_company(code, corp, name):
    res = {"code": code, "name": name, "split": [], "hole": [], "core": [], "metric": []}
    for stmt in ("IS", "BS", "CF"):
        try:
            m = FIN.statement_matrix(corp, YEARS, stmt, "y")
        except Exception as e:
            res.setdefault("error", []).append("%s %s" % (stmt, e))
            continue
        labels = [p["label"] for p in m["periods"]]
        rows = m["rows"]
        if not labels:
            continue
        live = set()                   # 이 재무제표가 존재하는 연도
        for r in rows:
            live.update(cover(r))

        # split
        cov = [(r, cover(r)) for r in rows]
        for i, (a, ca) in enumerate(cov):
            if not ca:
                continue
            for b, cb in cov[i + 1:]:
                if not cb or set(ca) & set(cb):
                    continue
                first, second = (a, b) if max(ca) < min(cb) else (b, a)
                f_cov = cover(first)
                s_cov = cover(second)
                if max(f_cov) >= min(s_cov):
                    continue
                if min(s_cov) - max(f_cov) > 2:
                    continue
                why = same_concept(first, second)
                if why:
                    res["split"].append({
                        "stmt": stmt, "why": why,
                        "a": first["name"], "ak": first["key"],
                        "a_to": labels[max(f_cov)],
                        "b": second["name"], "bk": second["key"],
                        "b_from": labels[min(s_cov)]})
        # hole
        for r in rows:
            c = cover(r)
            if len(c) < 2:
                continue
            gaps = [j for j in range(min(c), max(c)) if j not in c and j in live]
            if gaps:
                res["hole"].append({"stmt": stmt, "name": r["name"], "key": r["key"],
                                    "years": [labels[j] for j in gaps]})
        # core
        for cname, tags, rx in CORE[stmt]:
            have = set()
            for r in rows:
                if r["key"].split("|")[0] in tags or rx.search(FIN._merge_name(r["name"])):
                    have.update(cover(r))
            miss = sorted(live - have)
            if miss and not have:
                # 한 해도 없으면 구멍이 아니라 구조다(금융업의 매출액). 따로 센다.
                res.setdefault("absent", []).append({"stmt": stmt, "account": cname})
                continue
            if miss:
                res["core"].append({"stmt": stmt, "account": cname,
                                    "years": [labels[j] for j in miss]})
    # metric — 최신 사업보고서의 재무지표 15종
    try:
        now = FIN.metrics_for(corp, code, "2025-12", "20260320", prices={})
    except Exception:
        now = None
    if now:
        for k in ("매출액", "영업이익", "당기순이익", "자산총계", "부채총계",
                  "자본총계", "자본금", "유보금", "EPS", "BPS"):
            if now.get(k) is None:
                res["metric"].append(k)
    else:
        res["metric"].append("(전체)")
    return res


def main():
    args = sys.argv[1:]
    if sys.stdout is None:             # pythonw(작업 스케줄러)로 돌 때 — 창이 없으니 파일로 남긴다
        sys.stdout = open(os.path.join(BASE, ".cache", "점검_전종목.log"), "a", encoding="utf-8")
        sys.stderr = open(os.path.join(BASE, ".cache", "점검_전종목.err"), "a", encoding="utf-8")
    cmap = corp_map()
    codes = [c for c in collected_codes() if c in cmap]
    n = int(args[args.index("--n") + 1]) if "--n" in args else 200
    target = codes if "--all" in args else sample(codes, n)
    os.makedirs(OUT, exist_ok=True)
    print("점검 대상 %d곳 (전체 수집 %d곳), 연도 %d~%d" %
          (len(target), len(codes), YEARS[0], YEARS[-1]), flush=True)

    # 이어받기: 회사마다 결과를 따로 저장해 두고, --resume 이면 있는 회사는 건너뛴다.
    # 전 종목은 한 시간 가까이 걸려 중간에 PC 절전·세션 종료로 끊기곤 했다.
    part_dir = os.path.join(OUT, "부분")
    os.makedirs(part_dir, exist_ok=True)
    resume = "--resume" in args
    results = []
    t0 = time.time()
    for i, code in enumerate(target, 1):
        corp, name = cmap[code]
        pp = os.path.join(part_dir, code + ".json")
        if resume and os.path.exists(pp):
            try:
                results.append(json.load(open(pp, encoding="utf-8")))
                continue
            except Exception:
                pass
        try:
            res = audit_company(code, corp, name)
        except Exception as e:
            res = {"code": code, "name": name, "error": [str(e)],
                   "split": [], "hole": [], "core": [], "metric": []}
        results.append(res)
        json.dump(res, open(pp, "w", encoding="utf-8"), ensure_ascii=False)
        if i % 10 == 0 or i == len(target):
            print("  %d/%d  (%.0f초)" % (i, len(target), time.time() - t0), flush=True)

    json.dump(results, open(os.path.join(OUT, "결과.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ---- 요약
    n_co = len(results)
    split_co = [r for r in results if r["split"]]
    hole_co = [r for r in results if r["hole"]]
    core_co = [r for r in results if r["core"]]
    met_co = [r for r in results if r["metric"]]
    print()
    print("=" * 60)
    print("점검 %d곳" % n_co)
    print("  줄 갈라짐(split)   %3d곳  %d건" % (len(split_co), sum(len(r["split"]) for r in results)))
    print("  중간 빈칸(hole)    %3d곳  %d건" % (len(hole_co), sum(len(r["hole"]) for r in results)))
    print("  핵심계정 없음(core) %3d곳  %d건" % (len(core_co), sum(len(r["core"]) for r in results)))
    print("  재무지표 빈칸      %3d곳" % len(met_co))
    ab = Counter("%s:%s" % (a["stmt"], a["account"]) for r in results for a in r.get("absent", []))
    if ab:
        print("  (구조상 없음: %s)" % ", ".join("%s %d곳" % kv for kv in ab.most_common()))

    print()
    print("[split] 키 표류 유형 (앞키 -> 뒤키)")
    pat = Counter()
    ex = {}
    for r in results:
        for s in r["split"]:
            kind = lambda k: "태그" if k.startswith("t:") else "이름"
            k = "%s | %s->%s | 같은 %s" % (s["stmt"], kind(s["ak"]), kind(s["bk"]), s["why"])
            pat[k] += 1
            ex.setdefault(k, "%s: %s[%s ~%s] / %s[%s %s~]" % (
                r["name"], s["a"], s["ak"], s["a_to"], s["b"], s["bk"], s["b_from"]))
    for k, v in pat.most_common(15):
        print("  %4d  %s" % (v, k))
        print("        예) %s" % ex[k][:150])

    print()
    print("[split] 계정별 상위")
    acc = Counter("%s:%s" % (s["stmt"], norm(s["b"])) for r in results for s in r["split"])
    for k, v in acc.most_common(15):
        print("  %4d  %s" % (v, k))

    print()
    print("[hole] 계정별 상위")
    hc = Counter("%s:%s" % (h["stmt"], h["name"]) for r in results for h in r["hole"])
    for k, v in hc.most_common(12):
        print("  %4d  %s" % (v, k))

    print()
    print("[core] 없는 핵심계정")
    cc = Counter("%s:%s" % (c["stmt"], c["account"]) for r in results for c in r["core"])
    for k, v in cc.most_common(12):
        print("  %4d  %s" % (v, k))
    for k, _ in cc.most_common(4):
        who = [r["name"] for r in results for c in r["core"]
               if "%s:%s" % (c["stmt"], c["account"]) == k][:8]
        print("        %s: %s" % (k, ", ".join(who)))

    print()
    print("[metric] 비는 지표")
    mc = Counter(m for r in results for m in r["metric"])
    for k, v in mc.most_common(12):
        print("  %4d  %s" % (v, k))


if __name__ == "__main__":
    main()
