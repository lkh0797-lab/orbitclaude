# -*- coding: utf-8 -*-
"""
탑픽 — 과거 검증 · 민감도 · 최신 후보 (2026-10-20). 신호 정의 · 문턱은 탑픽.py(TH, 고정).

사전 등록(돌리기 전에 정한 주 지표 — 결과를 보고 고르지 않는다)
  주 지표 = 사건 패널 · 12개월 초과수익 · 같은 철(같은 분기 보고서) 저PER 하위 30% 와의 철별 중앙 차이 · 철 단위 부트스트랩 90% 구간.
  판정: 구간이 0 위면 '저PER 보다 나았다', 0 아래면 '못했다', 걸치면 '차이를 확신할 수 없다'. 나머지 표는 모두 보조.

시점 규칙(사용자): 어떤 날 s 의 신호든 s−1 까지 접수된 보고서와 s−1 종가 시가총액만. 들어가는 날 = s 종가(그 회사 시세의 다음 거래일 — 기존 도구들과 같은 규칙).
  (1) 사건 패널  회사마다 분기 보고서가 접수된 날 f 마다: f 까지 알게 된 분기(그 보고서 포함) · f 종가 → 신호, s = f 다음 거래일.
      기준선 = 같은 철(같은 분기 n 의 보고서들) 적격 회사 가운데 저PER 하위 30%(PER = f 종가 ÷ 알던 EPS 4분기 합 > 0, 탑픽은 뺀다).
  (2) 월말 패널  매달 말 m 마다 적격 전 종목: m 까지 알게 된 분기 · m 종가 → 신호, s = m 다음 거래일. 가격이 내려서 생기는 진입도 잡는다.
      같은 날 기준선(같은 적격 집합 안): 저PER 하위 30% · 저PER 탑픽 수만큼 · 저POR 하위 30% · '실적만(A 또는 B)' · 'A1 · A2 · B · A와 B' · '가격만(C1 · C2)' ·
      '(A 또는 B) 그리고 저PER'(C 가 저PER 위에 무엇을 더하나) · 적격 전 종목. 행마다 kind — new(이 분기 신호가 이번 달 처음) · held(지난달도 후보) · price(가격이 빠져 통과).
  잰다: 3 · 6 · 12개월 수익률 − 같은 기간 전 종목 수익률 중앙값(초과수익). 이긴 비율(12개월 초과 > 0), −30% 넘게 진 비율, 앞(~2019) · 뒤(2020~),
  회사 단위 부트스트랩 90% 구간과 철(연도-분기) 블록 부트스트랩 90% 구간 — 둘 중 넓은 쪽을 결론에 쓴다.
  나눠 보기: 그때 시가총액 3분위 · 2026 시총 순위(300 안/밖) · 이익률 고점 꼬리표 · 먼저 알려진 날(잠정실적) 있음/없음 · 신호 분기(Q1~Q4) · 경로(A1 · A2 · B).
  (3) 민감도  문턱마다 ×0.5 · ×1.5 하나씩(탑픽.sens_variants) + 규칙 변형(C1 상한 · 기저 1% 규칙 없이 · 적격 없이 · 정정 분기 제외 · 사건 신호일 하루 뒤).
      후보 수 · 중앙 초과수익 · 이긴 비율만(구간 없음). 문턱은 바꾸지 않는다, 표만 낸다.
  (4) 최신 후보  오늘 s: 어제(마지막 시세일)까지 알게 된 분기 · 어제 종가 → 후보 · 순위 · 아깝게 빠진 회사 · 금융 · 지주(참고) · 못 본 회사와 까닭.
재료 — 캐시만(네트워크 없음): .cache/druck · .cache/색인.json(원본 접수일) · .cache/price · .cache/ohlcv · 종목.txt · .cache/거시/induty.json(KSIC) ·
  .cache/공시목록/I_*.jsonl(잠정실적 · 손익구조변동 — 먼저 알려진 날) · .cache/공시목록/공시위험.json(최신 후보 표시만).
한계 — 지금 상장된 회사만(생존 편향) · 분기 값은 마지막으로 받은 원장(정정값일 수 있다 — 전년 비교값만 공시 당시 그대로) · 주식 수는 순이익 ÷ EPS 역산(우선주 포함 가중평균) ·
  월말 표본은 12개월 창이 겹친다 · 2011~2013 은 이력이 짧아 신호가 거의 없다 · 잠정실적은 신호에 안 쓴다(사용자 규칙 — 보고서 접수일).

실행: py -3.13 -X utf8 도구/탑픽_백테스트.py            (전부 — 5분 안팎)
      py -3.13 -X utf8 도구/탑픽_백테스트.py --latest   (최신 후보만 — 1분 안팎)
      --asof YYYYMMDD(최신 후보의 s−1 을 이 날로) · --boot N(부트스트랩 횟수, 기본 600) · --out 폴더 · --codes 쉼표(시험용)
결과: .cache/toppick/bt.json(검증 전체 · 화면이 읽는다) · bt.md(사람이 읽는 표) · latest.json(최신 후보) · panel_cand.json(후보 행 — 감사용) · splits.json(분할 날짜)
"""
import os, sys, re, json, time, math, random, argparse, bisect, glob, datetime as dt, statistics as st, importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
CACHE = os.path.join(BASE, ".cache")
OUT = os.path.join(CACHE, "toppick")
H = {"3m": 91, "6m": 182, "12m": 365}
SPLIT = "20200101"
START = "20140101"
PRIMARY = "사건 패널 · 12개월 · 같은 철 저PER 하위 30% 와의 철별 중앙 차이 · 철 단위 부트스트랩 90% 구간"
PRELIM_RE = re.compile(r"영업\(잠정\)실적|잠정실적")                                   # 분기마다 — '영업실적등에대한전망'(전망 공시)은 아니다
PRELIM_Q4_RE = re.compile(r"매출액또는손익구조")                                          # 연간 변동 공시 — 4분기(사업보고서) 앞에만
SHEV_RE = re.compile(r"주식분할결정|무상증자결정|유무상증자결정|주식병합결정|감자결정")       # 주가 자료(수정주가)도 같이 보정되는 주식 수 사건 — 드러켄밀러.SHEV_ADJ
FIN_KSIC = ("641", "65", "6612")       # 은행 · 보험 · 증권(선물) 중개 — 64992 지주회사는 금융이 아니다(HD현대 · LG 같은 사업 지주)
HOLDCO_KSIC = "64992"


def _load(name, file):
    sp = ilu.spec_from_file_location(name, os.path.join(BASE, file))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


T = _load("탑픽", "탑픽.py")
DRK = _load("드러켄밀러", "드러켄밀러.py")


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 재료
def load_universe():
    """종목.txt → {code: {rank, market, cap}} · 스냅샷 날짜."""
    rows, snap = {}, None
    p = os.path.join(BASE, "종목.txt")
    for ln in open(p, encoding="utf-8", errors="replace"):
        m = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", ln)
        if ln.startswith("#") and m and not snap:
            snap = "".join(m.groups())
        m = re.match(r"^([0-9][0-9A-Z]{5})\s*#\s*(\d+)위\s+.*\((KOSPI|KOSDAQ),\s*시총\s*([\d,]+)억\)", ln)
        if m:
            rows[m.group(1)] = {"rank": int(m.group(2)), "market": m.group(3), "cap": float(m.group(4).replace(",", "")) * 1e8}
        elif re.match(r"^[0-9][0-9A-Z]{5}", ln):
            rows[ln.split()[0]] = {}
    return rows, snap


def load_index():
    """색인 → {code: {name, filed: {n: 원본 접수일}}} (드러켄밀러.filed_meta)."""
    with open(os.path.join(CACHE, "색인.json"), encoding="utf-8") as fh:
        idx = json.load(fh)
    out = {}
    for c in idx.get("companies") or []:
        code = c.get("code")
        if not code:
            continue
        try:
            filed = DRK.filed_meta(c.get("reports") or []).get("filed") or {}
        except Exception:
            filed = {}
        out[code] = {"name": c.get("name") or code, "filed": {int(k): v for k, v in filed.items()}}
    return out


def load_corp_map():
    path = os.path.join(CACHE, "CORPCODE.xml")
    out = {}
    if not os.path.exists(path):
        return out
    text = open(path, "rb").read().decode("utf-8", errors="replace")
    for m in re.finditer(r"<list>(.*?)</list>", text, re.S):
        blob = m.group(1)
        s = re.search(r"<stock_code>(.*?)</stock_code>", blob, re.S)
        c = re.search(r"<corp_code>(.*?)</corp_code>", blob, re.S)
        if s and c and s.group(1).strip():
            out[s.group(1).strip()] = c.group(1).strip()
    return out


def load_ksic(corp_of):
    try:
        with open(os.path.join(CACHE, "거시", "induty.json"), encoding="utf-8") as fh:
            k = json.load(fh)
    except Exception:
        return {}
    return {code: str(k.get(corp) or "") for code, corp in corp_of.items()}


def _json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def load_disclosures(codes):
    """공시목록 I_*.jsonl → (prelim {code: {"q": [잠정실적 접수일], "y": [손익구조변동 접수일]}}, shev {code: [주식분할 · 무상증자 · 병합 · 감자 결정 접수일]}) — 정렬 · 중복 제거.
    철회 공시('철회' 가 제목에 든 것)는 뺀다."""
    want = set(codes)
    pre, sh = {}, {}
    for p in glob.glob(os.path.join(CACHE, "공시목록", "I_*.jsonl")):
        try:
            with open(p, encoding="utf-8") as fh:
                for ln in fh:
                    try:
                        d = json.loads(ln)
                    except Exception:
                        continue
                    code = d.get("stock_code")
                    if code not in want:
                        continue
                    t = d.get("report_nm") or ""
                    dt_ = str(d.get("rcept_dt") or "")[:8]
                    if PRELIM_RE.search(t):
                        pre.setdefault(code, {"q": [], "y": []})["q"].append(dt_)
                    elif PRELIM_Q4_RE.search(t):
                        pre.setdefault(code, {"q": [], "y": []})["y"].append(dt_)
                    elif SHEV_RE.search(t) and "철회" not in t:
                        sh.setdefault(code, []).append(dt_)
        except Exception:
            continue
    return ({c: {k: sorted(set(x for x in v if x)) for k, v in m.items()} for c, m in pre.items()},
            {c: sorted(set(x for x in v if x)) for c, v in sh.items()})


def first_map(filed, prelim):
    """회사 하나 — {n: 먼저 알려진 날} = (분기 말, 원본 접수일) 사이 가장 이른 잠정실적 공시일(4분기는 손익구조변동 공시도)."""
    out = {}
    if not prelim:
        return out
    for n, f0 in (filed or {}).items():
        n = int(n)
        lo = T.qend(n)
        cands = []
        for lst in ([prelim.get("q") or []] + ([prelim.get("y") or []] if n % 4 == 3 else [])):
            i = bisect.bisect_right(lst, lo)
            if i < len(lst) and lst[i] < str(f0):
                cands.append(lst[i])
        if cands:
            out[n] = min(cands)
    return out


RISK_OUT = ("상폐 절차",)                                   # 최신 후보에서 빼는 공시 위험 수준(공시위험.json level) — 실질심사 · 회생 · 감사의견 등
DILUTE_CATS = ("유상증자", "CB발행", "BW발행", "제3자배정")   # 희석 공시 꼬리표 — 24개월 안
DILUTE_DAYS = 730


def load_risk():
    """공시위험.json → {code: {level, proc, dilute: [날짜들]}} · 기준일."""
    d = _json(os.path.join(CACHE, "공시목록", "공시위험.json")) or {}
    out = {}
    for code, x in (d.get("codes") or {}).items():
        dil = sorted({str(row[0])[:8] for h in (x.get("hits") or []) if h.get("cat") in DILUTE_CATS for row in (h.get("rows") or []) if row})
        out[code] = {"level": x.get("level"), "proc": x.get("proc"), "dilute": dil}
    return out, d.get("기준일")


def load_series(codes, idx, prelim, strict=True):
    """{code: 분기 줄들} — druck v4 캐시만. (시리즈, 버전 달라 건너뛴 수, basis=영업이익, 결산월 다른 회사 코드들). strict=False 는 느슨한 시점(민감도)."""
    ser, skipped, fin, fy = {}, 0, {}, []
    for code in codes:
        p = os.path.join(CACHE, "druck", code + ".json")
        if not os.path.exists(p):
            continue
        d = DRK.read_cache(p)
        if d is None:
            skipped += 1
            continue
        filed = (idx.get(code) or {}).get("filed") or {}
        s = T.series_of(d, filed, first_map(filed, prelim.get(code)), strict=strict)
        if s:
            ser[code] = s
            fin[code] = d.get("basis") == "영업이익"
        elif d.get("fy"):
            fy.append(code)
    return ser, skipped, fin, fy


def load_prices(codes):
    data = {}
    for code in codes:
        s = _json(os.path.join(CACHE, "price", code + ".json"))
        if s:
            data[code] = s
    return T.Prices(data)


def load_turnover(codes, ser, shev):
    data, splits = {}, {}
    for code in codes:
        s = _json(os.path.join(CACHE, "ohlcv", code + ".json"))
        if s:
            data[code] = s
            sp = T.split_days(ser.get(code) or [], s, shev.get(code) or [])
            if sp:
                splits[code] = sp
    return T.Turnover(data, splits), splits


def month_ends(a, b):
    out = []
    y, m = int(a[:4]), int(a[4:6])
    while True:
        nx = dt.date(y + (m == 12), m % 12 + 1, 1)
        e = (nx - dt.timedelta(days=1)).strftime("%Y%m%d")
        if e > b:
            break
        if e >= a:
            out.append(e)
        y, m = nx.year, nx.month
    return out


# ---------------------------------------------------------------- 행 하나(얇게)
SLIM = ("op_yoy", "rev_yoy", "turn", "tiny", "thin", "no_rev", "ttm", "ttm_max", "n_hist", "ttm_g", "ttm_turn", "mcap", "mcap_g", "px_g",
        "gap", "gap_rank", "por", "per", "tv", "fin", "hold", "elig", "first", "px_since_first", "rev_ttm_g")


def slim_row(code, d, s, m):
    r = {"code": code, "date": d, "s": s, "n": m["n"], "lab": m["label"], "known": m["known"]}
    for k in SLIM:
        r[k] = m.get(k)
    r["pct"] = {str(w): m["por_pct"].get(w) for w in T.POR_WINS}
    r["pn"] = {str(w): m["por_n"].get(w) for w in T.POR_WINS}
    r["flags"] = m.get("flags") or []
    r["why_not"] = m.get("why_not") or []
    return r


def m_of(r):
    """slim 행 → judge · rank 가 쓰는 m 모양."""
    return {"op_yoy": r["op_yoy"], "rev_yoy": r["rev_yoy"], "turn": r["turn"], "tiny": r["tiny"], "thin": r["thin"], "no_rev": r["no_rev"], "fin": r["fin"],
            "ttm": r["ttm"], "ttm_max": r["ttm_max"], "n_hist": r["n_hist"], "gap": r["gap"], "gap_rank": r["gap_rank"],
            "por_pct": {int(k): v for k, v in r["pct"].items()}, "por_n": {int(k): v for k, v in r["pn"].items()}, "tv": r["tv"], "elig": r["elig"]}


def judge_row(r, th, opts=None):
    return T.judge(m_of(r), th, opts)


def attach_returns(P, r, codes_all, T1):
    code, s = r["code"], r["s"]
    for k, h in H.items():
        e = T.shift(s, h) if s else None
        if not s or e > T1:
            r["ex" + k] = None
            if k == "12m":
                r["ret12m"] = None
            continue
        a, b = P.ret(code, s, e), P.grp_ret(s, e, codes_all)
        r["ex" + k] = (a - b) if (a is not None and b is not None) else None
        if k == "12m":
            r["ret12m"] = a


# ---------------------------------------------------------------- 패널
def monthly_panel(codes, ser, P, TV, T1, dates, fin, hold, th):
    rows, prev = [], {}
    t0 = time.time()
    for i, m in enumerate(dates):
        cur = {}
        for code in codes:
            s_ = ser.get(code)
            if not s_:
                continue
            px_fn = lambda d, c=code: P.at(c, d)[0]
            mt = T.metrics(s_, m, px_fn, tv=TV.tv(code, m), th=th, fin=fin.get(code, False), hold=hold.get(code))
            if mt is None:
                continue
            s = P.next_day(code, m)
            r = slim_row(code, m, s, mt)
            attach_returns(P, r, codes, T1)
            j = judge_row(r, th)
            pv = prev.get(code)
            if j["cand"]:
                if pv and pv[1]:
                    r["kind"] = "held"
                elif pv and pv[0] == r["n"]:
                    r["kind"] = "price"            # 같은 분기 신호인데 지난달엔 후보가 아니었다 — 가격이 빠져 통과
                else:
                    r["kind"] = "new"
            cur[code] = (r["n"], j["cand"])
            rows.append(r)
        prev = cur
        if (i + 1) % 24 == 0:
            log("  월말 %d/%d  행 %d  %.0f초" % (i + 1, len(dates), len(rows), time.time() - t0))
    return rows


def event_panel(codes, ser, P, TV, T1, fin, hold, th, delay=0, dropped=None):
    """사건일 f = 그 분기를 알린 날(원본 접수일). 엄격 시점에선 그날 아직 모르는(정정 뒤에야 아는) 분기면 사건을 버린다(dropped['amend'] 에 센다).
    delay=1 이면 신호일을 하루 늦춘다(s−1 = 접수일 다음 거래일 — 그날이 첫 온전한 반응일). 민감도용. react = f 종가 → 다음 거래일 종가(공시 반응)."""
    rows = []
    for code in codes:
        s_ = ser.get(code)
        if not s_:
            continue
        px_fn = lambda d, c=code: P.at(c, d)[0]
        for q in s_:
            f = q["filed0"] or q["known"]
            if not f or f < START or f > T1:
                continue
            d = f
            if delay:
                d = P.next_day(code, f)
                if not d:
                    continue
            mt = T.metrics(s_, d, px_fn, tv=TV.tv(code, d), th=th, fin=fin.get(code, False), hold=hold.get(code))
            if mt is None or mt["n"] != q["n"]:
                if dropped is not None and q["known"] and q["known"] > d:
                    dropped["amend"] = dropped.get("amend", 0) + 1       # 원본 날엔 아직 모르는 값(정정 뒤에야 안다) — 엄격 시점의 비용
                continue                                  # 그날 알게 된 최신 분기가 이 분기가 아니면 건너뛴다
            s = P.next_day(code, d)
            r = slim_row(code, f, s, mt)
            r["q"] = q["n"] % 4 + 1
            r["react"] = P.ret(code, f, P.next_day(code, f)) if P.next_day(code, f) else None
            attach_returns(P, r, codes, T1)
            rows.append(r)
    return rows


# ---------------------------------------------------------------- 통계
def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def _boot(rows, fn, key, n, seed):
    """key(row) 단위 블록 부트스트랩 90% 구간."""
    blocks = sorted({key(r) for r in rows})
    if not blocks:
        return (None, None)
    by = {}
    for r in rows:
        by.setdefault(key(r), []).append(r)
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        v = fn([x for b in (rnd.choice(blocks) for _ in blocks) for x in by[b]])
        if v is not None:
            vals.append(v)
    vals.sort()
    return (vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]) if vals else (None, None)


def boot(rows, fn, n=600, seed=7):
    return _boot(rows, fn, lambda r: r["code"], n, seed)


def boot_season(rows, fn, n=600, seed=11):
    return _boot(rows, fn, lambda r: r["n"], n, seed)


def stats(rows, nboot=600, ci=True):
    done = [r for r in rows if r.get("ex12m") is not None]
    out = {"n": len(rows), "n12": len(done), "firms": len({r["code"] for r in rows}), "dates": len({r["date"] for r in rows})}
    for k in H:
        out["med" + k] = med([r.get("ex" + k) for r in rows])
        out["avg" + k] = mean([r.get("ex" + k) for r in rows])
    out["hit"] = (sum(1 for r in done if r["ex12m"] > 0) / len(done) * 100) if done else None
    cr = [r for r in done if r.get("ret12m") is not None]
    out["crash"] = (sum(1 for r in cr if r["ret12m"] <= -30) / len(cr) * 100) if cr else None
    out["early"] = med([r["ex12m"] for r in done if r["date"] < SPLIT])
    out["late"] = med([r["ex12m"] for r in done if r["date"] >= SPLIT])
    out["n_early"] = sum(1 for r in done if r["date"] < SPLIT)
    out["n_late"] = len(done) - out["n_early"]
    if ci and done:
        f = lambda rs: med([r["ex12m"] for r in rs])            # noqa: E731
        out["ci12"] = list(boot(done, f, nboot))
        out["ci12_season"] = list(boot_season(done, f, nboot))
    else:
        out["ci12"] = out["ci12_season"] = [None, None]
    return out


def diff_stats(a, b, nboot=600, key="ex12m"):
    """두 묶음의 중앙 초과수익 차이(a − b) — 회사 단위 · 철 단위 부트스트랩 90% 구간(두 묶음을 함께 다시 뽑는다)."""
    A = [r for r in a if r.get(key) is not None]
    B = [r for r in b if r.get(key) is not None]
    if not A or not B:
        return {"diff": None, "ci": [None, None], "ci_season": [None, None], "early": None, "late": None}

    def ci_by(kf, seed):
        blocks = sorted({kf(r) for r in A} | {kf(r) for r in B})
        ba, bb = {}, {}
        for r in A:
            ba.setdefault(kf(r), []).append(r[key])
        for r in B:
            bb.setdefault(kf(r), []).append(r[key])
        rnd = random.Random(seed)
        vals = []
        for _ in range(nboot):
            pick = [rnd.choice(blocks) for _ in blocks]
            xa = [v for f in pick for v in ba.get(f, ())]
            xb = [v for f in pick for v in bb.get(f, ())]
            if xa and xb:
                vals.append(st.median(xa) - st.median(xb))
        vals.sort()
        return [vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]] if vals else [None, None]
    e = lambda rs, lo, hi: med([r[key] for r in rs if lo <= r["date"] < hi])      # noqa: E731
    ea, eb, la, lb = e(A, "0", SPLIT), e(B, "0", SPLIT), e(A, SPLIT, "9"), e(B, SPLIT, "9")
    return {"diff": st.median([r[key] for r in A]) - st.median([r[key] for r in B]),
            "ci": ci_by(lambda r: r["code"], 11), "ci_season": ci_by(lambda r: r["n"], 13),
            "early": (ea - eb) if (ea is not None and eb is not None) else None, "late": (la - lb) if (la is not None and lb is not None) else None}


def season_pairs(cand, base, key="ex12m", min_n=5):
    """철(분기 n)마다 탑픽 중앙 − 기준선 중앙 — 주 지표. {n_seasons, wins, diff_med, diff_mean, ci(철 블록), seasons: [[n, diff, n_c, n_b]]}"""
    bc, bb = {}, {}
    for r in cand:
        if r.get(key) is not None:
            bc.setdefault(r["n"], []).append(r[key])
    for r in base:
        if r.get(key) is not None:
            bb.setdefault(r["n"], []).append(r[key])
    rows = []
    for n in sorted(set(bc) & set(bb)):
        if len(bc[n]) >= min_n and len(bb[n]) >= min_n:
            rows.append([n, st.median(bc[n]) - st.median(bb[n]), len(bc[n]), len(bb[n])])
    diffs = [x[1] for x in rows]
    if not diffs:
        return {"n_seasons": 0, "wins": 0, "diff_med": None, "diff_mean": None, "ci": [None, None], "seasons": rows}
    rnd = random.Random(17)
    vals = sorted(st.median([diffs[rnd.randrange(len(diffs))] for _ in diffs]) for _ in range(800))
    sd = st.pstdev(diffs) if len(diffs) > 1 else 0.0
    return {"n_seasons": len(diffs), "wins": sum(1 for v in diffs if v > 0), "diff_med": st.median(diffs), "diff_mean": mean(diffs),
            "ci": [vals[int(len(vals) * .05)], vals[int(len(vals) * .95)]], "mde": 1.65 * sd / math.sqrt(len(diffs)) if diffs else None,
            "seasons": [[n, round(v, 2), a, b] for n, v, a, b in rows]}


def spear(a, b):
    n = len(a)
    if n < 5:
        return None
    ra, rb = T.pct_rank(a), T.pct_rank(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in ra)) or 1
    sb = math.sqrt(sum((x - mb) ** 2 for x in rb)) or 1
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (sa * sb)


def ic_stats(rows, key="ex12m"):
    by = {}
    for r in rows:
        if r.get("score") is not None and r.get(key) is not None:
            by.setdefault(r["date"], []).append((r["score"], r[key]))
    ics, dates = [], []
    for d in sorted(by):
        v = spear([x[0] for x in by[d]], [x[1] for x in by[d]])
        if v is not None:
            ics.append(v)
            dates.append(d)
    return {"ic": mean(ics), "pos": (sum(1 for v in ics if v > 0) / len(ics) * 100) if ics else None, "dates": len(ics),
            "early": mean([v for v, d in zip(ics, dates) if d < SPLIT]), "late": mean([v for v, d in zip(ics, dates) if d >= SPLIT])}


def score_rows(rows, th):
    by = {}
    for r in rows:
        by.setdefault(r["date"], []).append(r)
    for d, rs in by.items():
        pack = [{"m": m_of(r), "j": judge_row(r, th)} for r in rs]
        T.rank(pack, th)
        for r, p in zip(rs, pack):
            r["score"], r["rank"], r["parts"] = p["score"], p["rank"], p["parts"]
    return rows


def tercile(rows, key="ex12m"):
    done = sorted([r for r in rows if r.get("score") is not None and r.get(key) is not None], key=lambda r: r["score"])
    if len(done) < 9:
        return None
    k = len(done) // 3
    return {"top": med([r[key] for r in done[-k:]]), "bot": med([r[key] for r in done[:k]]), "n": k}


def split_stats(rows, key_fn, nboot=0):
    """묶음을 key_fn(row) 값으로 나눠 통계(구간 없음)."""
    by = {}
    for r in rows:
        k = key_fn(r)
        if k is not None:
            by.setdefault(k, []).append(r)
    return {str(k): stats(v, nboot, ci=False) for k, v in sorted(by.items(), key=lambda x: str(x[0]))}


# ---------------------------------------------------------------- 월말 패널 — 묶음 · 기준선(적격 집합 안)
def groups_monthly(rows, th, nboot):
    U = [r for r in rows if r["elig"]]
    J = {id(r): judge_row(r, th) for r in U}
    liquid = [r for r in U if J[id(r)]["L"]]
    cand = [r for r in liquid if J[id(r)]["cand"]]
    by_date = {}
    for r in liquid:
        by_date.setdefault(r["date"], []).append(r)
    low30, lowN, por30, lowper_set = [], [], [], set()
    n_cand = {}
    for r in cand:
        n_cand[r["date"]] = n_cand.get(r["date"], 0) + 1
    for d, rs in by_date.items():
        pe = sorted([r for r in rs if r.get("per") is not None and r["per"] > 0], key=lambda r: r["per"])
        if pe:
            k = max(1, int(len(pe) * 0.3))
            low30.extend(pe[:k])
            lowper_set.update(id(r) for r in pe[:k])
            nc = n_cand.get(d, 0)
            if nc:
                lowN.extend(pe[:nc])
        po = sorted([r for r in rs if r.get("por") is not None and r["por"] > 0], key=lambda r: r["por"])
        if po:
            por30.extend(po[:max(1, int(len(po) * 0.3))])
    G = {"탑픽 후보": cand,
         "실적만(A 또는 B)": [r for r in liquid if J[id(r)]["A"] or J[id(r)]["B"]],
         "A1 실적 개선만": [r for r in liquid if J[id(r)]["A1"]],
         "A2 흑자 전환만": [r for r in liquid if J[id(r)]["A2"]],
         "B 실적 신고점만": [r for r in liquid if J[id(r)]["B"]],
         "A 와 B 둘 다": [r for r in liquid if J[id(r)]["A"] and J[id(r)]["B"]],
         "가격만(C1 · C2)": [r for r in liquid if J[id(r)]["C1"] and J[id(r)]["C2"]],
         "(A 또는 B) 그리고 저PER": [r for r in liquid if (J[id(r)]["A"] or J[id(r)]["B"]) and id(r) in lowper_set],
         "저PER 하위 30%": low30, "저PER 탑픽 수만큼": lowN, "저POR 하위 30%": por30, "적격 전 종목": liquid,
         "비적격(참고)": [r for r in rows if not r["elig"]]}
    CI = {"탑픽 후보", "저PER 하위 30%", "저PER 탑픽 수만큼", "저POR 하위 30%", "실적만(A 또는 B)", "가격만(C1 · C2)", "(A 또는 B) 그리고 저PER"}
    out = {k: stats(v, nboot, ci=(k in CI)) for k, v in G.items()}
    per_month = [n_cand.get(d, 0) for d in sorted(by_date)]
    cnt = {"avg": mean(per_month), "med": med(per_month), "max": max(per_month) if per_month else None,
           "zero": sum(1 for v in per_month if v == 0), "months": len(per_month)}
    return G, out, cnt


def groups_event(rows, th, nboot):
    """사건 패널 — 적격 · 유동 행 안에서 묶음과 같은 철 저PER 기준선."""
    U = [r for r in rows if r["elig"]]
    J = {id(r): judge_row(r, th) for r in U}
    liquid = [r for r in U if J[id(r)]["L"]]
    cand = [r for r in liquid if J[id(r)]["cand"]]
    cand_ids = {id(r) for r in cand}
    by_n = {}
    for r in liquid:
        by_n.setdefault(r["n"], []).append(r)
    low30 = []
    for n, rs in by_n.items():
        pe = sorted([r for r in rs if r.get("per") is not None and r["per"] > 0 and id(r) not in cand_ids], key=lambda r: r["per"])
        if pe:
            low30.extend(pe[:max(1, int(len(pe) * 0.3))])
    G = {"탑픽 후보": cand, "같은 철 저PER 하위 30%": low30,
         "실적만(A 또는 B)": [r for r in liquid if J[id(r)]["A"] or J[id(r)]["B"]],
         "가격만(C1 · C2)": [r for r in liquid if J[id(r)]["C1"] and J[id(r)]["C2"]], "적격 전 보고서": liquid}
    out = {k: stats(v, nboot, ci=(k != "적격 전 보고서")) for k, v in G.items()}
    return G, out


# ---------------------------------------------------------------- 민감도
def sensitivity(MR, ER, ER1, th, nboot):
    out = []
    for name, t, opts in T.sens_variants(th):
        cand = [r for r in MR if judge_row(r, t, opts)["cand"]]
        s = stats(cand, 0, ci=False)
        dates = sorted({r["date"] for r in MR})
        nd = {}
        for r in cand:
            nd[r["date"]] = nd.get(r["date"], 0) + 1
        s.update(name=name, kind="월말", th={k: t[k] for k in ("op_yoy", "rev_yoy", "cap", "hist_min", "c1", "c2", "por_win", "tv")}, opts=opts,
                 per_month=mean([nd.get(d, 0) for d in dates]))
        if cand:
            score_rows(cand, t)
            s["tercile"] = tercile(cand)
            s["ic"] = ic_stats(cand)["ic"]
        ec = [r for r in ER if judge_row(r, t, opts)["cand"]]
        es = stats(ec, 0, ci=False)
        s.update(ev_n12=es["n12"], ev_med12m=es["med12m"], ev_hit=es["hit"])
        out.append(s)
    # 규칙 변형 — 문턱이 아닌 것
    base_c = [r for r in MR if judge_row(r, th)["cand"]]
    noam = [r for r in base_c if not ({"late_amend", "q_amended"} & set(r["flags"]))]
    s = stats(noam, 0, ci=False)
    s.update(name="정정 분기 제외(월말)", kind="월말", th=dict(th), opts={"no_amend": True}, per_month=None,
             ev_n12=None, ev_med12m=None, ev_hit=None)
    ec = [r for r in ER if judge_row(r, th)["cand"] and not ({"late_amend", "q_amended"} & set(r["flags"]))]
    es = stats(ec, 0, ci=False)
    s.update(ev_n12=es["n12"], ev_med12m=es["med12m"], ev_hit=es["hit"])
    out.append(s)
    if ER1:
        ec = [r for r in ER1 if judge_row(r, th)["cand"]]
        es = stats(ec, 0, ci=False)
        es.update(name="사건 신호일 하루 뒤(반응일 종가로)", kind="사건", th=dict(th), opts={"delay": 1}, per_month=None,
                  ev_n12=es["n12"], ev_med12m=es["med12m"], ev_hit=es["hit"])
        out.append(es)
    return out


def loose_variant(MRL, ERL, th):
    """느슨한 시점(원본 접수일에 정정값을 안 것으로) 패널의 후보 통계 — 민감도 한 줄. 엄격 판과의 차이가 '정정 누출 크기'."""
    cand = [r for r in MRL if judge_row(r, th)["cand"]]
    s = stats(cand, 0, ci=False)
    dates = sorted({r["date"] for r in MRL})
    nd = {}
    for r in cand:
        nd[r["date"]] = nd.get(r["date"], 0) + 1
    ec = [r for r in ERL if judge_row(r, th)["cand"]]
    es = stats(ec, 0, ci=False)
    s.update(name="원본 접수일 기준(느슨 — 정정값을 원본 날에 안 것으로)", kind="월말", th=dict(th), opts={"strict": False},
             per_month=mean([nd.get(d, 0) for d in dates]), ev_n12=es["n12"], ev_med12m=es["med12m"], ev_hit=es["hit"])
    return s


# ---------------------------------------------------------------- 최신 후보
def latest(codes, ser, P, TV, idx, univ, snap, fin, hold, ksic, risk, asof=None, th=T.TH, fy=()):
    last_px = max((P.last_date(c) for c in codes if P.last_date(c)), default=None)
    d = asof or last_px
    rows, near, ref, risky, excl = [], [], [], [], {}
    counts = {"metrics": 0, "elig": 0, "A": 0, "B": 0, "C1": 0, "C2": 0, "L": 0, "cand": 0}
    for code in fy:
        excl.setdefault("결산월 다름", []).append(code)
    for code in codes:
        s_ = ser.get(code)
        if not s_:
            if code not in fy:
                excl.setdefault("분기 자료 없음", []).append(code)
            continue
        px_fn = lambda x, c=code: P.at(c, x)[0]
        # 최신 후보만 거래량 봉 묵음을 20일까지 봐준다(ohlcv 는 차트 발굴 스캔이 받아 price 보다 1~2주 늦다) — 7일 넘으면 '묵은 거래 자료' 꼬리표
        m = T.metrics(s_, d, px_fn, tv=TV.tv(code, d, stale=20), th=th, fin=fin.get(code, False), hold=hold.get(code))
        if m is None:
            excl.setdefault("알게 된 분기 없음", []).append(code)
            continue
        counts["metrics"] += 1
        j = T.judge(m, th)
        jn = T.judge(m, th, {"no_elig": True})
        for k in ("A", "B", "C1", "C2", "L"):
            counts[k] += bool(j[k])
        u = univ.get(code) or {}
        cap_alt = None
        if u.get("cap") and snap:
            p0, _ = P.at(code, snap)
            if p0 and m["px"]:
                cap_alt = u["cap"] * m["px"] / p0
        lb = TV.last_bar(code, d)
        rk = risk.get(code) or {}
        dil = [x for x in (rk.get("dilute") or []) if x <= d and T.days_between(x, d) <= DILUTE_DAYS]
        tags = []
        if str(ksic.get(code) or "").startswith(HOLDCO_KSIC):
            tags.append("holdco")
        if dil:
            tags.append("dilution")
        row = {"code": code, "name": (idx.get(code) or {}).get("name") or code, "market": u.get("market"), "cap_rank": u.get("rank"),
               "m": m, "j": j, "cap_alt": cap_alt, "fin": bool(fin.get(code)), "hold": bool(hold.get(code)), "ksic": ksic.get(code) or "",
               "px_date": P.at(code, d)[1], "tv_date": lb, "tv_stale": bool(lb and T.days_between(lb, d) > 7),
               "risk": rk.get("level"), "risk_proc": rk.get("proc"), "dilute": dil[-3:], "tags": tags}
        if m["elig"]:
            counts["elig"] += 1
            if j["cand"] and (rk.get("level") in RISK_OUT or rk.get("proc")):
                counts["cand"] += 1
                risky.append(row)                         # 네 관문은 넘었지만 공시 위험(상폐 절차 · 실질심사 진행) — 따로
            elif j["cand"]:
                counts["cand"] += 1
                rows.append(row)
            else:
                miss = [k for k, ok in (("실적(A 또는 B)", j["A"] or j["B"]), ("C1", j["C1"]), ("C2", j["C2"]), ("유동성", j["L"])) if not ok]
                if len(miss) == 1:
                    row["miss"] = miss[0]
                    near.append(row)
        else:
            for w in m["why_not"]:
                excl.setdefault(w, []).append(code)
            if jn["cand"] and (m["fin"] or m["hold"]) and not ({"stale", "q_invalid"} & set(m["flags"])):
                ref.append(row)                           # 금융 · 지주 — 네 관문은 넘었지만 적격이 아니라 참고로만
    T.rank(rows, th)
    rows.sort(key=lambda r: r["rank"])
    near.sort(key=lambda r: -(r["m"]["tv"] or 0))
    ref.sort(key=lambda r: -(r["m"]["tv"] or 0))
    risky.sort(key=lambda r: -(r["m"]["tv"] or 0))
    names = lambda cs: [[c, (idx.get(c) or {}).get("name") or c] for c in cs]      # noqa: E731
    return {"v": T.VERSION, "asof": d, "today": dt.date.today().strftime("%Y%m%d"), "last_px": last_px, "n_univ": len(codes) + len(fy), "counts": counts,
            "th": dict(th), "rows": rows, "near": near[:60], "ref": ref[:30], "risky": risky[:30],
            "excluded": {k: {"n": len(v), "names": names(v[:40])} for k, v in sorted(excl.items(), key=lambda x: -len(x[1]))},
            "at": dt.datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- 보고
def fmt(v, d=1, s=""):
    if v is None:
        return "—"
    return ("%+." + str(d) + "f") % v + s


def pc(v):
    return "—" if v is None else "%d%%" % round(v)


def ci_s(ci):
    return ("%s ~ %s" % (fmt(ci[0]), fmt(ci[1]))) if (ci and ci[0] is not None) else "—"


def surv_note(e_splits, m_splits):
    """생존 편향 신호 한 줄 — 탑픽 후보의 12개월 중앙이 '2026 시총 300 안'과 '그때 시총 작음' 칸에 몰리는가(결과를 보고 적는 사실 문장)."""
    r = (e_splits.get("2026 시총 순위") or {})
    t = (m_splits.get("그때 시가총액 3분위") or {})
    a, b = (r.get("300 안") or {}).get("med12m"), (r.get("300 밖") or {}).get("med12m")
    s, l = (t.get("작음") or {}).get("med12m"), (t.get("큼") or {}).get("med12m")
    parts = []
    if a is not None and b is not None:
        parts.append("사건 후보 12개월 중앙: 2026 시총 300 안 %s · 300 밖 %s" % (fmt(a), fmt(b)))
    if s is not None and l is not None:
        parts.append("월말 후보: 그때 시총 작음 %s · 큼 %s" % (fmt(s), fmt(l)))
    if not parts:
        return ""
    tilt = (a is not None and b is not None and a - b >= 3) or (s is not None and l is not None and s - l >= 3)
    return "나눠 보면 — " + " / ".join(parts) + (". 우위가 '그때 작고 지금 큰' 칸에 몰려 있다 — 생존 편향이 결과에 들어 있다고 본다." if tilt else ".")


def verdict(pp):
    if not pp or pp.get("diff_med") is None:
        return "검증 전"
    lo, hi = pp["ci"]
    if lo is not None and lo > 0:
        return "저PER 보다 나았다"
    if hi is not None and hi < 0:
        return "저PER 보다 못했다"
    return "저PER 과 차이를 확신할 수 없다"


def md_report(R):
    L = []
    L.append("# 탑픽 과거 검증 (%s)\n" % R["at"][:10])
    L.append("사전 등록 주 지표: %s\n" % PRIMARY)
    pp = R["event"]["primary"]
    L.append("**판정: %s** — 철 %d개 가운데 탑픽이 이긴 철 %d개, 철별 차이 중앙 %s (90%% 구간 %s), 잡을 수 있는 최소 차이 ≈ %s\n" % (
        verdict(pp), pp["n_seasons"], pp["wins"], fmt(pp["diff_med"]), ci_s(pp["ci"]), fmt(pp.get("mde"))))
    L.append("월말 %s ~ %s · 회사 %d(적격 집합 안 %d) · 시세 마지막 %s · 신호 정의 탑픽.py v%d · 문턱 고정(TH)\n" % (
        R["dates"][0], R["dates"][-1], R["n_firms"], R["n_elig_firms"], R["T1"], T.VERSION))
    L.append("## 사건 패널 — 보고서 접수일마다 (주 증거)\n")
    L.append("| 묶음 | 행 | 회사 | 6개월 중앙 | 12개월 중앙 | 90% 구간(회사) | 90% 구간(철) | 이긴 비율 | ~2019 | 2020~ |")
    L.append("|---|---:|---:|---:|---:|---|---|---:|---:|---:|")
    for k, s in R["event"]["groups"].items():
        L.append("| %s | %d | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            k, s["n12"], s["firms"], fmt(s["med6m"]), fmt(s["med12m"]), ci_s(s.get("ci12")), ci_s(s.get("ci12_season")), pc(s["hit"]), fmt(s["early"]), fmt(s["late"])))
    L.append("\n탑픽 − 기준선(사건, 12개월 중앙 차이):\n")
    L.append("| 기준선 | 차이 | 90% 구간(회사) | 90% 구간(철) | ~2019 | 2020~ |")
    L.append("|---|---:|---|---|---:|---:|")
    for k, s in R["event"]["vs"].items():
        L.append("| %s | %s | %s | %s | %s | %s |" % (k, fmt(s["diff"]), ci_s(s["ci"]), ci_s(s["ci_season"]), fmt(s["early"]), fmt(s["late"])))
    L.append("\n나눠 보기(사건 탑픽 후보, 12개월 중앙 · 이긴 비율 · 행):\n")
    for name, sp in R["event"]["splits"].items():
        L.append("- %s: " % name + " · ".join("%s %s(%s, %d)" % (k, fmt(v["med12m"]), pc(v["hit"]), v["n12"]) for k, v in sp.items()))
    rc, ov = R["event"].get("react") or {}, R["event"].get("overlap_f1") or {}
    L.append("- 공시 반응(접수일 종가 → 다음 거래일 종가): 후보 중앙 %s · 적격 전체 중앙 %s · 후보 가운데 +5%% 넘게 뛴 비율 %s. 신호일 하루 뒤 판과 후보 겹침: 둘 다 %s · 접수일 판만 %s · 하루 뒤 판만 %s (자카드 %s)" % (
        fmt(rc.get("cand_med"), 2), fmt(rc.get("all_med"), 2), pc(rc.get("cand_up5")), ov.get("both"), ov.get("f_only"), ov.get("f1_only"),
        fmt(ov.get("jaccard"), 2).lstrip("+") if ov.get("jaccard") is not None else "—"))
    L.append("- 엄격 시점이라 버린 사건(원본 접수일엔 아직 모르는 정정값): %d" % (R["event"].get("amend_dropped") or 0))
    L.append("\n## 월말 패널 — 적격 집합 안 묶음별 (보조)\n")
    L.append("| 묶음 | 행 | 회사 | 3개월 | 6개월 | 12개월 중앙 | 90% 구간(회사) | 90% 구간(철) | 이긴 비율 | −30%↓ | ~2019 | 2020~ |")
    L.append("|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---:|")
    for k, s in R["monthly"]["groups"].items():
        L.append("| %s | %d | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k, s["n12"], s["firms"], fmt(s["med3m"]), fmt(s["med6m"]), fmt(s["med12m"]), ci_s(s.get("ci12")), ci_s(s.get("ci12_season")),
            pc(s["hit"]), pc(s["crash"]), fmt(s["early"]), fmt(s["late"])))
    c = R["monthly"]["count"]
    L.append("\n한 달 후보 수: 평균 %.1f · 중앙 %s · 최대 %s · 후보 0인 달 %d/%d\n" % (c["avg"] or 0, c["med"], c["max"], c["zero"], c["months"]))
    L.append("| 기준선 | 차이 | 90% 구간(회사) | 90% 구간(철) | ~2019 | 2020~ |")
    L.append("|---|---:|---|---|---:|---:|")
    for k, s in R["monthly"]["vs"].items():
        L.append("| %s | %s | %s | %s | %s | %s |" % (k, fmt(s["diff"]), ci_s(s["ci"]), ci_s(s["ci_season"]), fmt(s["early"]), fmt(s["late"])))
    L.append("\n월말 종류별(kind): " + " · ".join("%s %s(%s, %d)" % (k, fmt(v["med12m"]), pc(v["hit"]), v["n12"]) for k, v in R["monthly"]["kinds"].items()))
    for name, sp in R["monthly"]["splits"].items():
        L.append("- %s: " % name + " · ".join("%s %s(%s, %d)" % (k, fmt(v["med12m"]), pc(v["hit"]), v["n12"]) for k, v in sp.items()))
    ic, tc = R["monthly"]["ic"], R["monthly"]["tercile"]
    L.append("\n순위 점수(후보 안): 날짜별 순위상관 평균 %s (양수 %s · 날짜 %s) · 위⅓ %s vs 아래⅓ %s\n" % (
        fmt(ic["ic"], 3), pc(ic["pos"]), ic["dates"], fmt(tc["top"]) if tc else "—", fmt(tc["bot"]) if tc else "—"))
    L.append("## 민감도 — 문턱 하나씩 ×0.5 · ×1.5 + 규칙 변형 (문턱은 바꾸지 않는다)\n")
    L.append("| 변형 | 월말 행 | 달 평균 후보 | 월말 6개월 | 월말 12개월 | 월말 이긴 | 사건 행 | 사건 12개월 | 사건 이긴 |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in R["sens"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            s["name"], s["n12"] if s.get("kind") == "월말" else "—", fmt(s.get("per_month"), 1).lstrip("+") if s.get("per_month") is not None else "—",
            fmt(s["med6m"]) if s.get("kind") == "월말" else "—", fmt(s["med12m"]) if s.get("kind") == "월말" else "—", pc(s["hit"]) if s.get("kind") == "월말" else "—",
            s.get("ev_n12") if s.get("ev_n12") is not None else "—", fmt(s.get("ev_med12m")), pc(s.get("ev_hit"))))
    flips = sum(1 for s in R["sens"] if s.get("ev_med12m") is not None and (s["ev_med12m"] > 0) != ((R["sens"][0]["ev_med12m"] or 0) > 0))
    L.append("\n사건 12개월 중앙의 부호가 기본과 뒤집힌 변형: %d / %d\n" % (flips, len(R["sens"])))
    L.append("## 한계\n")
    for x in R["limits"]:
        L.append("- " + x)
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", action="store_true", help="최신 후보만")
    ap.add_argument("--asof", default=None)
    ap.add_argument("--boot", type=int, default=600)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--codes", default=None, help="쉼표 — 시험용 부분 집합")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    univ, snap = load_universe()
    idx = load_index()
    codes = [c for c in univ if c in idx] if univ else sorted(idx)
    if a.codes:
        want = set(a.codes.split(","))
        codes = [c for c in codes if c in want]
    corp_of = load_corp_map()
    ksic = load_ksic({c: corp_of.get(c) for c in codes if corp_of.get(c)})
    prelim, shev = load_disclosures(codes)
    ser, skipped, basis_op, fy = load_series(codes, idx, prelim)
    fin = {c: bool(basis_op.get(c)) or str(ksic.get(c) or "").startswith(FIN_KSIC) for c in codes}
    hold = {c: T.is_holding(ser[c]) for c in ser}
    risk, risk_at = load_risk()
    log("회사 %d · 분기 시리즈 %d (옛 버전 캐시 %d) · 금융 %d · 지주 %d · 잠정 공시 있는 회사 %d · %.0f초" % (
        len(codes), len(ser), skipped, sum(fin.values()), sum(hold.values()), len(prelim), time.time() - t0))
    P = load_prices(codes)
    TV, splits = load_turnover(codes, ser, shev)
    with open(os.path.join(a.out, "splits.json"), "w", encoding="utf-8") as fh:
        json.dump(splits, fh, ensure_ascii=False)
    T1 = max((P.last_date(c) for c in codes if P.last_date(c)), default=None)
    log("시세 %d · 거래량 %d · 분할 사건 %d곳 · 마지막 시세일 %s · %.0f초" % (len(P.codes()), len(TV.pre), len(splits), T1, time.time() - t0))
    codes = [c for c in codes if c in ser and c in P.ks]
    LT = latest(codes, ser, P, TV, idx, univ, snap, fin, hold, ksic, risk, asof=a.asof, fy=fy)
    LT["risk_at"] = risk_at
    with open(os.path.join(a.out, "latest.json"), "w", encoding="utf-8") as fh:
        json.dump(LT, fh, ensure_ascii=False)
    log("최신 후보 %d (s−1 = %s) · 적격 %d · 아깝게 빠짐 %d · 금융·지주 참고 %d · 공시 위험 %d · %.0f초" % (
        len(LT["rows"]), LT["asof"], LT["counts"]["elig"], len(LT["near"]), len(LT["ref"]), len(LT["risky"]), time.time() - t0))
    for r in LT["rows"][:15]:
        m = r["m"]
        log("  %2d %-12s %s %s 영업이익YoY %s 매출YoY %s TTM증가 %s 시총증가 %s 괴리 %s POR %s 자리 %s 거래대금 %.0f억 %s" % (
            r["rank"], r["name"], m["label"], "·".join(r["j"]["why"]), fmt(m["op_yoy"], 0), fmt(m["rev_yoy"], 0), fmt(m["ttm_g"], 0), fmt(m["mcap_g"], 0),
            fmt(m["gap"], 0), fmt(m["por"], 1).lstrip("+"), pc(r["j"]["pct"]), (m["tv"] or 0) / 1e8, ",".join(m["flags"])))
    if a.latest:
        return
    th = T.TH
    dates = [d for d in month_ends(START, T1) if d < T1]
    log("월말 패널 %d 달 …" % len(dates))
    MR = monthly_panel(codes, ser, P, TV, T1, dates, fin, hold, th)
    log("월말 행 %d · %.0f초" % (len(MR), time.time() - t0))
    G, GS, cnt = groups_monthly(MR, th, a.boot)
    cand = G["탑픽 후보"]
    score_rows(cand, th)
    vs = {k: diff_stats(cand, G[k], a.boot) for k in ("저PER 하위 30%", "저PER 탑픽 수만큼", "저POR 하위 30%", "(A 또는 B) 그리고 저PER", "실적만(A 또는 B)", "가격만(C1 · C2)", "적격 전 종목")}
    kinds = split_stats(cand, lambda r: r.get("kind"))
    terc = {}
    by_date = {}
    for r in [x for x in MR if x["elig"]]:
        by_date.setdefault(r["date"], []).append(r)
    for d, rs in by_date.items():
        caps = sorted([x["mcap"] for x in rs if x.get("mcap")])
        if len(caps) >= 9:
            q1, q2 = caps[len(caps) // 3], caps[2 * len(caps) // 3]
            for x in rs:
                if x.get("mcap"):
                    terc[id(x)] = "작음" if x["mcap"] < q1 else "중간" if x["mcap"] < q2 else "큼"
    m_splits = {"그때 시가총액 3분위": split_stats(cand, lambda r: terc.get(id(r))),
                "2026 시총 순위": split_stats(cand, lambda r: "300 안" if (univ.get(r["code"]) or {}).get("rank", 9999) <= 300 else "300 밖"),
                "이익률 고점 꼬리표": split_stats(cand, lambda r: "있음" if "opm_peak" in r["flags"] else "없음"),
                "먼저 알려진 날(잠정)": split_stats(cand, lambda r: "있음" if r.get("first") else "없음")}
    since = lambda r: ("0~30일" if T.days_between(r["known"], r["date"]) <= 30 else "31~60일" if T.days_between(r["known"], r["date"]) <= 60     # noqa: E731
                       else "61~90일" if T.days_between(r["known"], r["date"]) <= 90 else "90일 넘음")
    m_splits["신호 분기를 안 뒤 지난 날"] = split_stats(cand, since)
    log("사건 패널 …")
    dropped = {}
    ER = event_panel(codes, ser, P, TV, T1, fin, hold, th, dropped=dropped)
    EG, EGS = groups_event(ER, th, a.boot)
    ecand = EG["탑픽 후보"]
    score_rows(ecand, th)
    evs = {k: diff_stats(ecand, EG[k], a.boot) for k in ("같은 철 저PER 하위 30%", "실적만(A 또는 B)", "가격만(C1 · C2)", "적격 전 보고서")}
    primary = season_pairs(ecand, EG["같은 철 저PER 하위 30%"])
    JE = {id(r): judge_row(r, th) for r in ecand}
    path_of = lambda j: ("A1" if j["A1"] else "") + ("A2" if j["A2"] else "") + ("B" if j["B"] else "")      # noqa: E731
    e_splits = {"신호 분기": split_stats(ecand, lambda r: "Q%d" % r["q"]),
                "경로": split_stats(ecand, lambda r: path_of(JE[id(r)])),
                "먼저 알려진 날(잠정)": split_stats(ecand, lambda r: "있음" if r.get("first") else "없음"),
                "이익률 고점 꼬리표": split_stats(ecand, lambda r: "있음" if "opm_peak" in r["flags"] else "없음"),
                "2026 시총 순위": split_stats(ecand, lambda r: "300 안" if (univ.get(r["code"]) or {}).get("rank", 9999) <= 300 else "300 밖")}
    log("사건 행 %d · 후보 %d · 철 %d · %.0f초" % (len(ER), len(ecand), primary["n_seasons"], time.time() - t0))
    log("민감도 …")
    ER1 = event_panel(codes, ser, P, TV, T1, fin, hold, th, delay=1)
    SE = sensitivity(MR, ER, ER1, th, a.boot)
    c0 = {(r["code"], r["n"]) for r in ecand}
    c1 = {(r["code"], r["n"]) for r in ER1 if judge_row(r, th)["cand"]}
    overlap = {"both": len(c0 & c1), "f_only": len(c0 - c1), "f1_only": len(c1 - c0), "jaccard": (len(c0 & c1) / len(c0 | c1)) if (c0 | c1) else None}
    react = {"cand_med": med([r.get("react") for r in ecand]), "all_med": med([r.get("react") for r in ER if r["elig"]]),
             "cand_up5": (sum(1 for r in ecand if (r.get("react") or 0) >= 5) / len(ecand) * 100) if ecand else None}
    log("느슨한 시점 판(민감도) …")
    ser_l, _, _, _ = load_series(codes, idx, prelim, strict=False)
    MRL = monthly_panel(codes, ser_l, P, TV, T1, dates, fin, hold, th)
    ERL = event_panel(codes, ser_l, P, TV, T1, fin, hold, th)
    SE.append(loose_variant(MRL, ERL, th))
    n_elig_firms = len({r["code"] for r in MR if r["elig"]})
    R = {"v": T.VERSION, "at": dt.datetime.now().isoformat(timespec="seconds"), "T1": T1, "dates": [dates[0], dates[-1]], "n_firms": len(codes),
         "n_elig_firms": n_elig_firms, "primary_def": PRIMARY, "th": dict(T.TH), "th_name": T.TH_NAME,
         "event": {"groups": EGS, "vs": evs, "primary": primary, "verdict": verdict(primary), "splits": e_splits, "rows": len(ER),
                   "ic": ic_stats(ecand), "tercile": tercile(ecand), "amend_dropped": dropped.get("amend", 0), "react": react, "overlap_f1": overlap},
         "monthly": {"groups": GS, "count": cnt, "vs": vs, "kinds": kinds, "splits": m_splits, "ic": ic_stats(cand), "tercile": tercile(cand), "rows": len(MR)},
         "sens": SE,
         "limits": ["지금 상장된 회사만(생존 편향) — 수익률 수준이 부풀어 있고, '그때 작았는데 지금 큰 회사'가 남아 있어 탑픽 쪽에 유리하게 휠 수 있다(2015~2024 기준일 뒤 24개월 안에 죽은 204곳 중 5곳만 유니버스에 있다). "
                    + surv_note(e_splits, m_splits),
                    "분기 값은 마지막으로 받은 원장(정정이 있으면 정정값). 전년 비교값(_전)만 그 보고서에 적힌 그대로 — '정정 분기 제외' 민감도 줄이 그 크기를 보인다.",
                    "주식 수 = 지배순이익 ÷ EPS 역산(믿을 만한 가까운 4개 중앙값) — 우선주를 포함한 가중평균 주식 수에 가깝다. 시가총액 수준은 흔히 5~15% 크고 증가율 · 자기 역사 자리엔 영향이 작다.",
                    "큰 회사는 잠정실적 · 손익구조변동 공시로 2~7주 먼저 알려진다 — 이 표의 진입일은 그 뒤다(사용자 규칙: 보고서 접수일). '먼저 알려진 날' 나눠 보기가 그 차이를 보인다.",
                    "월말 표본은 12개월 창이 겹친다 — 회사 단위 · 철 단위 부트스트랩 가운데 넓은 쪽을 본다. 독립 표본은 사실상 철(분기) 수다.",
                    "기준선 저PER 은 같은 적격 집합 안 횡단 하위 30%(PER = 보정 종가 ÷ 알던 EPS 4분기 합 > 0). 사건 패널은 같은 철 보고서들 안에서.",
                    "금융(KSIC 641 은행 · 65 보험 · 6612 증권 · 매출 줄 없는 회사) · 순수 지주(영업이익 > 매출)는 적격이 아니다 — 최신 후보에 '참고' 로만 보인다. KSIC 64992 지주회사(HD현대 등)는 '지주회사' 꼬리표만.",
                    "거래대금 = 보정 종가 × 원주 거래량 × 분할 배수(거래량이 뛴 날짜로 찾음 — splits.json). 시장 달력에 봉이 없는 날은 0 — 정지 종목은 떨어진다."],
         "secs": round(time.time() - t0)}
    with open(os.path.join(a.out, "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(R, fh, ensure_ascii=False)
    with open(os.path.join(a.out, "bt.md"), "w", encoding="utf-8") as fh:
        fh.write(md_report(R))
    slim = [{k: v for k, v in r.items() if k not in ("parts",)} for r in cand]
    with open(os.path.join(a.out, "panel_cand.json"), "w", encoding="utf-8") as fh:
        json.dump({"monthly_cand": slim, "event_cand": [{k: v for k, v in r.items() if k != "parts"} for r in ecand],
                   "event_lowper": [{"code": r["code"], "date": r["date"], "n": r["n"], "per": r["per"], "ex12m": r.get("ex12m")} for r in EG["같은 철 저PER 하위 30%"]]},
                  fh, ensure_ascii=False)
    log(md_report(R))
    log("끝 %.0f초 → %s" % (time.time() - t0, a.out))


if __name__ == "__main__":
    main()
