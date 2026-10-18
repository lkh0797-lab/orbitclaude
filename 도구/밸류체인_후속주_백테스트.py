# -*- coding: utf-8 -*-
"""
밸류체인 후속주 — 주도주가 오르면 밸류체인으로 이어진 회사가 뒤따라 오르나 (2026-10-19).
검토 스크래치 .cache/밸류체인_검토/vcbt/(load · edges · test · analyze1~4, 2026-10-18)를 한 파일로 모은 것 — 설계는 스크래치 그대로.

주장: 월말 t 에 3개월 수익률이 전 종목 상위 10%(주도주)면, 그와 밸류체인으로 이어진 회사(후속주)가 그 뒤 1 · 3 · 6개월에 더 오른다.
시점: 2012-01 ~ 마지막 달의 월말. 종가 = 그 달 마지막 거래일 종가(그 날이 18일 전이면 그 달은 모름 — 2월은 16일).
연결(시점 자르기): .cache/밸류체인/<code>.json years[] 중 접수일(rcept) ≤ t 이고 t 에서 24개월(744일) 안인, 그 칸이 빈 것 아닌 마지막 표.
  · 공급망(sc) — 매출처(customers 'named' + subs 의 customers · final) · 매입처(materials suppliers), 두 방향 다. 이름 → 종목은
    스크래치 load.key(별칭 · CORPCODE 한글/영문 이름, 지금 색인 988곳만). 강한 연결 = 그 줄 비중(매출처 몫 · 매입 몫) 20% 이상.
  · 같은 제품(sp) — 주도주 제품 낱말(밸류체인_지도.product_words)로 끝나는 남의 제품 이름(products_of top 12 · 5% 이상 · 장비 규칙 —
    prod_hits 와 같은 끝맞춤). 밸류체인_지도 는 지금 모습 그대로 쓴다(2026-10-19 합계 · 조정 띄어쓰기 줄 빼기 포함).
잰다: 후속주의 앞 h개월 수익률 전 종목 백분위(0~100) − 대조 평균 = 초과 백분위 점.
  대조 = 같은 달 · 같은 자기 3개월 모멘텀 10분위 · 주도주 아님 · 어떤 주도주와도 안 이어짐 · 주도주 업종(지금 업종 map) 밖(칸에 5곳 이상).
  묶음은 겹치지 않게 sc > sp > 같은 업종(ind = 주도주와 같은 업종 · 안 이어짐 — 위약). 같은 칸으로 P(앞 h개월 상위 10%) 초과(%p)도.
  덧붙임: 같은 업종 안 대조(같은 달 · 후속주 업종 · 같은 10분위의 안 이어진 비주도주), 같은 재벌끼리만 이어진 짝 빼기, sp 갈래(같은/다른 업종 ·
  두 줄 다 20% 이상), '덜 오름'(주도주보다 3개월 백분위 30점 넘게 뒤처진 후속주 vs 나머지), 주도주 문턱 상위 5% · 2%.
  부트스트랩 1000번 — 회사 단위 · 달 단위, 90%(스크래치는 95% — 견주려고 95% 도 같이). 앞(2012~18) · 뒤(2019~26).
  '덜 오름' 은 스크래치 analyze.py 식(시장 중앙값 대비 수익률, 위아래 자름, 짝 단위)으로도 다시 재 스크래치 −4.06%p 와 견준다.
한계(bt.json caveats): 지금 상장사만 · 업종은 지금 분류 · 이름 맞추기 오결합 · 겹치는 창 · 여러 갈래를 본 것(다중 비교).

캐시만 읽는다(네트워크 · 키 없음): 색인.json · CORPCODE.xml · price/ · 밸류체인/ · 업종/map.json. 쓴다: .cache/vcmap/bt.json · bt.md.
실행: python -X utf8 도구/밸류체인_후속주_백테스트.py             (읽기 포함 2~4분)
      python -X utf8 도구/밸류체인_후속주_백테스트.py --boot 200   (빠른 확인 — 구간만 거칠어진다)
"""
import os, sys, re, json, html, time, zlib, random, bisect, argparse, collections, datetime as dt, statistics as st, importlib.util

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
C = os.path.join(BASE, ".cache")
OUT = os.path.join(C, "vcmap")
_spec = importlib.util.spec_from_file_location("밸류체인_지도", os.path.join(BASE, "밸류체인_지도.py"))
VMAP = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(VMAP)

START, SPLIT = "201201", "201901"     # 첫 시점 · 앞(~2018)/뒤(2019~)
MAXAGE = 24 * 31                      # 일 — 시점에서 이보다 오래된 표는 안 쓴다
H = (1, 3, 6)
THRS = (90, 95, 98)                   # 주도주 = 3개월 백분위 이 이상(본 결과 90, 나머지는 민감도)
LAG = 30                              # '덜 오름' = 주도주 p3 − 후속주 p3 ≥ 이것
STRONG = 20.0                         # 강한 연결(%)
MIN_CELL, MIN_XS = 5, 300             # 대조 칸 최소 · 단면 최소 종목 수
PERIODS = (("all", lambda ym: True), ("early", lambda ym: ym < SPLIT), ("late", lambda ym: ym >= SPLIT))

# 스크래치 결과(vcbt/out1~4.txt, 2026-10-18 — 95% 구간)
SCRATCH = {
    "sc_6m": ("out3 top10% 6m sc", 3.24, [1.64, 4.93], 4190, 326),
    "sp_6m": ("out3 top10% 6m sp", -0.32, [-1.64, 1.01], 5094, 414),
    "ind_6m": ("out3 top10% 6m ind", 1.90, [1.45, 2.36], 69167, 956),
    "sc_3m": ("out3 top10% 3m sc", 2.08, [0.89, 3.25], 4359, 336),
    "sp_3m": ("out3 top10% 3m sp", -0.07, [-1.16, 1.15], 5253, 421),
    "ind_3m": ("out3 top10% 3m ind", 1.08, [0.76, 1.41], 70356, 963),
    "sc_6m_top10": ("out3 top10% 6m sc P(top10%) 초과", 1.87, [0.38, 3.57], 4190, 326),
    "sp_6m_top10": ("out3 top10% 6m sp P(top10%) 초과", 0.96, [-0.15, 2.13], 5094, 414),
    "ind_6m_top10": ("out3 top10% 6m ind P(top10%) 초과", 2.94, [2.44, 3.44], 69167, 956),
    "sc_6m_within_ind": ("out2 6m sc vs 같은 업종 · 10분위 비연결", 3.05, [-0.18, 6.08], 720, 133),
    "lag_raw_sc_6m": ("out1 6m sc '덜 오름' − 나머지(수익률 %p)", -4.06, [-7.54, -0.62], 2652, 302),
    "lag_raw_sp_6m": ("out1 6m sp '덜 오름' − 나머지(수익률 %p)", -4.39, [-7.02, -1.97], 3662, 394),
}


# ---------------------------------------------------------------- 이름 → 종목(스크래치 load.py 그대로)
LAT = VMAP._LATIN_KO
GROUP_TAIL = re.compile(r"\s*(?:및|와|과)\s*(?:그\s*|[가-힣A-Za-z0-9&]+의\s*)?(?:해외\s*|국내\s*)?(?:종속|계열|관계)\s*(?:기업|회사)들?\s*$")
ALIAS = {"포스코": "POSCO홀딩스", "posco": "POSCO홀딩스", "포스코홀딩스": "POSCO홀딩스", "한국전력": "한국전력공사", "한전": "한국전력공사",
         "한국전력공사본사": "한국전력공사", "현대차": "현대자동차", "기아차": "기아", "기아자동차": "기아", "lg전자": "LG전자", "sk하이닉스": "SK하이닉스",
         "현대중공업": "HD현대중공업", "hd현대중공업": "HD현대중공업", "대우조선해양": "한화오션", "두산중공업": "두산에너빌리티", "현대미포조선": "HD현대미포",
         "한국조선해양": "HD한국조선해양", "삼성에스디아이": "삼성SDI", "엘지에너지솔루션": "LG에너지솔루션", "lg에너지솔루션": "LG에너지솔루션",
         "한화큐셀": "한화솔루션", "엘지화학": "LG화학", "에스케이하이닉스": "SK하이닉스", "네이버": "NAVER", "lg디스플레이": "LG디스플레이",
         "엘지디스플레이": "LG디스플레이", "엘지전자": "LG전자", "엘지이노텍": "LG이노텍", "삼성전기": "삼성전기", "ls산전": "엘에스일렉트릭",
         "lselectric": "엘에스일렉트릭", "samsungelectronics": "삼성전자", "skhynix": "SK하이닉스", "hynix": "SK하이닉스", "lgdisplay": "LG디스플레이",
         "lgelectronics": "LG전자", "hyundaimotor": "현대자동차", "hyundaimotorcompany": "현대자동차", "kiamotors": "기아", "kia": "기아"}


def norm_corp(nm):
    n = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|\s+|[·ㆍ\.,&]", "", nm or "").lower()
    return re.sub(r"[a-z]", lambda m: LAT[m.group(0)], n)


def strip_name(nm):
    nm = re.sub(r"\s*\(?\d[\d,]*\s*(?:백만\s*원|억\s*원|천\s*원|원)\)?\s*$", "", nm or "").strip()
    n = re.sub(r"\(\*+\d*\)|\(주\d*\)|\(주\)|㈜|주식회사|\s*본사$|\s*등$", "", nm or "").strip()
    return GROUP_TAIL.sub("", n).strip()


def key(nm):
    n = strip_name(nm)
    n = re.sub(r"\b(?:co|ltd|inc|corp|corporation|company|limited|pvt|llc|gmbh|sa|plc)\b\.?", "", n, flags=re.I)
    n = re.sub(r"[\s.,'’&\-·ㆍ/()]", "", n).lower()
    a = ALIAS.get(n)
    if a:
        n = re.sub(r"[\s.,'’&\-·ㆍ/()]", "", a).lower()
    return n[:24] if re.fullmatch(r"[a-z0-9]+", n) else norm_corp(n)


def build_names(univ):
    names = {key(nm): cd for cd, nm in univ.items()}
    with open(os.path.join(C, "CORPCODE.xml"), "rb") as fh:
        t = fh.read().decode("utf-8", errors="replace")
    eng = {}
    for m in re.finditer(r"<list>(.*?)</list>", t, re.S):
        b = m.group(1)
        g = lambda k: html.unescape((re.search(r"<%s>(.*?)</%s>" % (k, k), b, re.S) or [None, ""])[1].strip())   # noqa: E731
        sc = g("stock_code")
        if sc in univ:
            names.setdefault(key(g("corp_name")), sc)
            ek = key(g("corp_eng_name"))
            if len(ek) >= 4:
                eng.setdefault(ek, sc)
    for ek, sc in eng.items():
        names.setdefault(ek, sc)
    return names


# 같은 재벌(이름 머리) — 스크래치 edges.py 그대로
GROUPS = ["삼성", "LG", "엘지", "SK", "에스케이", "현대", "HD", "기아", "롯데", "한화", "포스코", "POSCO", "LS", "엘에스", "GS", "CJ", "두산", "효성", "코오롱",
          "금호", "한진", "신세계", "이마트", "카카오", "KT", "DB", "HL", "OCI", "SKC", "아모레", "농심", "오리온", "대상", "동원", "한솔", "태광", "세아", "영풍", "고려아연", "현대백화점"]
GN = {"엘지": "LG", "에스케이": "SK", "SKC": "SK", "HD": "현대", "기아": "현대", "POSCO": "포스코", "엘에스": "LS", "이마트": "신세계", "고려아연": "영풍"}


def group_of(nm):
    for g in sorted(GROUPS, key=len, reverse=True):
        if (nm or "").upper().startswith(g.upper()):
            return GN.get(g, g)
    return None


# ---------------------------------------------------------------- 읽기
def months(a, b):
    y, m = int(a[:4]), int(a[4:])
    out = []
    while "%04d%02d" % (y, m) <= b:
        out.append("%04d%02d" % (y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def mend(ym):
    y, m = int(ym[:4]), int(ym[4:])
    return dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)


def ordn(d8):
    return dt.date(int(d8[:4]), int(d8[4:6]), int(d8[6:8])).toordinal()


def load():
    with open(os.path.join(C, "색인.json"), encoding="utf-8") as fh:
        univ = {c["code"]: c["name"] for c in json.load(fh)["companies"]}
    names = build_names(univ)
    with open(os.path.join(C, "업종", "map.json"), encoding="utf-8") as fh:
        im = json.load(fh)
    ind = {cd: (im["stocks"].get(cd) or {}).get("industry") for cd in univ}
    # 월말 종가 — 그 달 마지막 거래일이 18일(2월 16일) 전이면 모름(끊긴 종목 · 아직 안 끝난 달)
    cl = {}
    for cd in univ:
        p = os.path.join(C, "price", cd + ".json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        me = {}
        for k in sorted(d):
            v = d[k]
            if isinstance(v, (int, float)) and v > 0:
                me[k[:6]] = (k, float(v))
        cl[cd] = {ym: (v if int(k[6:]) >= 18 or (ym[4:] == "02" and int(k[6:]) >= 16) else None) for ym, (k, v) in me.items()}
    vc = {}
    for cd in univ:
        p = os.path.join(C, "밸류체인", cd + ".json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        rows = []
        for y, v in (d.get("years") or {}).items():
            rc = (v.get("rcept") or "")[:8]
            if not re.fullmatch(r"\d{8}", rc):
                continue
            cust = [(x.get("name"), x.get("pct")) for x in v.get("customers") or [] if x.get("kind") == "named"]
            for s in v.get("subs") or []:
                cust += [(nm, pc) for nm, pc in (s.get("customers") or []) + (s.get("final") or [])]
            sup = [(sp["name"], mt.get("item"), mt.get("pct")) for mt in v.get("materials") or [] for sp in mt.get("suppliers") or [] if sp.get("name")]
            rows.append({"y": y, "filed": rc, "fo": ordn(rc), "cust": cust, "sup": sup, "prod": v.get("products") or []})
        rows.sort(key=lambda r: r["filed"])
        vc[cd] = rows
    return {"univ": univ, "names": names, "ind": ind, "ind_built": im.get("built"), "cl": cl, "vc": vc,
            "grp": {cd: group_of(nm) for cd, nm in univ.items()}}


def prep(D):
    """표마다 한 번 — 이어진 종목(공급망) · 제품 줄 · 끝맞춤 꼬리(스크래치 edges.py 그대로, 밸류체인_지도 는 지금 것)."""
    names, cl = D["names"], D["cl"]
    link = lambda nm: names.get(key(nm))     # noqa: E731
    for cd, rows in D["vc"].items():
        for r in rows:
            r["cust_c"] = [(c2, pc, nm) for nm, pc in r["cust"] for c2 in [link(nm)] if c2 and c2 != cd and c2 in cl]
            r["sup_c"] = [(c2, pc, nm, it) for nm, it, pc in r["sup"] for c2 in [link(nm)] if c2 and c2 != cd and c2 in cl]
            items = VMAP.products_of(r["prod"], top=12) if r["prod"] else []
            pwords = VMAP.product_words(r["prod"]) if r["prod"] else []
            r["pkeys"] = [(w, VMAP.kw_norm(w)) for w in pwords]
            r["equip"] = any(VMAP.EQUIP_RX.search(p["item"]) and (p["pct"] or 0) >= 30 for p in items)
            r["items"] = [(x["item"], x["seg"], x.get("raw", x["pct"]), bool(x.get("est"))) for x in items]
            suf_all, suf_ne = [], []
            for item, seg, pct, est in r["items"]:
                if not item or VMAP.GEN_ITEM.match(item.strip()) or (pct is not None and pct < 5.0):
                    continue
                es = [e for e in (VMAP.kw_norm(p) for p in VMAP._phrases(item)) if e and not VMAP.REV_TAIL.search(e)]
                ne = not VMAP.EQUIP_RX.search(item)
                for e in es:
                    for i in range(len(e)):
                        suf_all.append((e[i:], item, pct))
                        if ne:
                            suf_ne.append(e[i:])
            r["suf_all"], r["suf_ne"] = suf_all, suf_ne
    # 칸마다 '비지 않은 표' 목록(접수일 순) — 시점의 마지막 표를 bisect 로
    D["act"] = {f: {cd: ([r["fo"] for r in rows if r[f]], [r for r in rows if r[f]]) for cd, rows in D["vc"].items()}
                for f in ("cust_c", "sup_c", "items")}


def active(D, field, cd, to):
    fo, rs = D["act"][field].get(cd) or ((), ())
    i = bisect.bisect_right(fo, to) - 1
    if i < 0:
        return None
    r = rs[i]
    return r if to - r["fo"] <= MAXAGE else None


def graph_sc(D, to):
    """공급망 그래프 — sc[a][b] = [종류 set, 최대 비중(없으면 -1)]. 매출처 · 매입처 두 방향."""
    sc = collections.defaultdict(dict)

    def put(a, b, kind, pc):
        e = sc[a].setdefault(b, [set(), -1.0])
        e[0].add(kind)
        if pc is not None and pc > e[1]:
            e[1] = pc
    for cd in D["vc"]:
        r = active(D, "cust_c", cd, to)
        if r:
            for c2, pc, nm in r["cust_c"]:
                put(cd, c2, "my_cust", pc)
                put(c2, cd, "lists_me_cust", pc)
        r = active(D, "sup_c", cd, to)
        if r:
            for c2, pc, nm, it in r["sup_c"]:
                put(cd, c2, "my_sup", pc)
                put(c2, cd, "lists_me_sup", pc)
    return sc


_SPX = {"sig": None, "ix": None}


def graph_sp(D, to, leaders):
    """같은 제품 — sp[L] = {짝: (낱말, 짝 품목, 짝 비중)}(주도주 L 의 제품 낱말로 끝나는 짝 제품). act = 시점의 제품 표."""
    act = {cd: active(D, "items", cd, to) for cd in D["vc"]}
    sig = tuple(id(r) if r else 0 for r in act.values())
    if sig != _SPX["sig"]:
        idx_all, idx_ne, meta = collections.defaultdict(set), collections.defaultdict(set), {}
        for cd, r in act.items():
            if not r:
                continue
            for s, item, pct in r["suf_all"]:
                idx_all[s].add(cd)
                meta.setdefault((cd, s), (item, pct))
            for s in r["suf_ne"]:
                idx_ne[s].add(cd)
        _SPX.update(sig=sig, ix=(idx_all, idx_ne, meta))
    idx_all, idx_ne, meta = _SPX["ix"]
    sp = {}
    for cd in leaders:
        r = act.get(cd)
        if not r or not r["pkeys"]:
            continue
        ix = idx_all if r["equip"] else idx_ne
        hit = {}
        for disp, kk in r["pkeys"]:
            if not kk:
                continue
            for c2 in ix.get(kk, ()):
                if c2 != cd and c2 not in hit:
                    hit[c2] = (disp,) + meta.get((c2, kk), (None, None))
        sp[cd] = hit
    return sp, act


def lead_line_pct(r, kw):
    """주도주 제품 줄 중 맞은 낱말이 든 줄의 최대 비중(스크래치 analyze4)."""
    if not r:
        return None
    kk = VMAP.kw_norm(kw)
    ps = [it[2] for it in r["items"] if kk and kk in VMAP.kw_norm(it[0]) and it[2] is not None]
    return max(ps) if ps else None


def pctl(d):
    ks = sorted(d, key=lambda c: d[c])
    n = len(ks)
    return {c: 100.0 * i / (n - 1) for i, c in enumerate(ks)} if n > 1 else {}


# ---------------------------------------------------------------- 사건 줄
def build(D):
    cl, IND, GRP = D["cl"], D["ind"], D["grp"]
    today = dt.date.today()
    MONTHS = months("201101", "%04d%02d" % (today.year, today.month))
    pos = {ym: i for i, ym in enumerate(MONTHS)}

    def add(ym, k):
        i = pos[ym] + k
        return MONTHS[i] if 0 <= i < len(MONTHS) else None

    def ret(c, a, b):
        if a is None or b is None:
            return None
        x = cl[c]
        p0, p1 = x.get(a), x.get(b)
        return (p1 / p0 - 1) if p0 and p1 else None

    R = collections.defaultdict(list)       # (thr, h, 묶음) → [(회사, 달, 초과, 상위10%초과, 백분위, 자기p3, 덜오름점)]
    WI = collections.defaultdict(list)      # (h, 묶음) → 같은 업종 안 대조
    RAW = collections.defaultdict(dict)     # (종류, 덜오름?, h) → {(달, 후속주): 수익률 − 중앙값}  (스크래치 analyze.py)
    cov = {}
    used = []
    for ym in MONTHS:
        if ym < START or add(ym, 1) is None:
            continue
        a3 = add(ym, -3)
        r3 = {}
        for c in cl:
            v = ret(c, a3, ym)
            if v is not None:
                r3[c] = v
        if len(r3) < MIN_XS:
            continue
        p3 = pctl(r3)
        dec = {c: min(9, int(p3[c] // 10)) for c in p3}
        fp, raw = {}, {}
        for h in H:
            b = add(ym, h)
            if b is None:
                continue
            rr = {}
            for c in r3:
                v = ret(c, ym, b)
                if v is not None:
                    rr[c] = v
            if len(rr) >= MIN_XS:
                fp[h] = pctl(rr)
                cap = {c: max(-0.95, min(v, 3.0)) for c, v in rr.items()}
                med = st.median(cap.values())
                raw[h] = {c: v - med for c, v in cap.items()}
        if not fp:
            continue
        used.append(ym)
        to = mend(ym).toordinal()
        srt = sorted(r3.values())
        q90 = srt[int(0.9 * len(srt))]
        lead90 = {c for c in r3 if p3[c] >= 90}
        lead_raw = {c for c, v in r3.items() if v >= q90}
        sc = graph_sc(D, to)
        sp, act = graph_sp(D, to, lead90 | lead_raw)
        if ym[4:] == "06":
            cov[ym[:4]] = {"priced": len(r3), "sc_nodes": sum(1 for c in r3 if sc.get(c)), "sc_pairs": sum(1 for c in r3 for f in sc.get(c, ()) if f in r3) // 2,
                           "prod_tables": sum(1 for c in r3 if act.get(c)), "leaders": len(lead90),
                           "leaders_with_sc": sum(1 for L in lead90 if sc.get(L)), "leaders_with_sp": sum(1 for L in lead90 if sp.get(L))}
        # 스크래치 analyze.py — 짝(주도주, 후속주) 단위, 시장 중앙값 대비 수익률, '덜 오름' 과 나머지가 겹칠 수 있다
        for L in lead_raw:
            links = {f: "sc" for f in sc.get(L, {})}
            for f in sp.get(L, {}):
                links.setdefault(f, "sp")
            for f, typ in links.items():
                if f == L or f not in r3:
                    continue
                lg = p3[L] - p3[f] >= LAG
                for h in raw:
                    x = raw[h].get(f)
                    if x is not None:
                        RAW[(typ, lg, h)].setdefault((ym, f), x)
        for thr in THRS:
            leaders = lead90 if thr == 90 else {c for c in lead90 if p3[c] >= thr}
            lsc, lsp = collections.defaultdict(dict), collections.defaultdict(dict)
            for L in leaders:
                for f, (kinds, pc) in sc.get(L, {}).items():
                    lsc[f][L] = pc
                for f, info in sp.get(L, {}).items():
                    lsp[f][L] = info
            lind = {IND[L] for L in leaders if IND.get(L)}
            for h in fp:
                if thr != 90 and h == 1:
                    continue
                F = fp[h]
                cells = collections.defaultdict(lambda: [0.0, 0.0, 0])
                cells2 = collections.defaultdict(lambda: [0.0, 0.0, 0])
                for c in r3:
                    if c in leaders or c in lsc or c in lsp or c not in F:
                        continue
                    y = F[c]
                    if thr == 90 and IND.get(c):
                        e = cells2[(IND[c], dec[c])]
                        e[0] += y; e[1] += y >= 90; e[2] += 1
                    if IND.get(c) in lind:
                        continue
                    e = cells[dec[c]]
                    e[0] += y; e[1] += y >= 90; e[2] += 1
                cm = {k: (s / n, w / n) for k, (s, w, n) in cells.items() if n >= MIN_CELL}
                cm2 = {k: (s / n, w / n) for k, (s, w, n) in cells2.items() if n >= MIN_CELL}
                for c in r3:
                    if c in leaders or c not in F or dec[c] not in cm:
                        continue
                    if c in lsc:
                        g, Ls = "sc", lsc[c]
                    elif c in lsp:
                        g, Ls = "sp", lsp[c]
                    elif IND.get(c) in lind:
                        g, Ls = "ind", None
                    else:
                        continue
                    y = F[c]
                    m, w = cm[dec[c]]
                    lag = max(p3[L] - p3[c] for L in Ls) if Ls else None
                    row = (c, ym, y - m, 100.0 * ((y >= 90) - w), y, p3[c], lag)
                    R[(thr, h, g)].append(row)
                    if thr != 90 or g == "ind":
                        continue
                    if g == "sc":
                        if any(not (GRP.get(c) and GRP.get(c) == GRP.get(L)) for L in Ls):
                            R[(90, h, "sc_xgrp")].append(row)
                        R[(90, h, "sc_strong" if any(pc >= STRONG for pc in Ls.values()) else "sc_weak")].append(row)
                    else:
                        tags = set()
                        for L, (kw, item, pct) in Ls.items():
                            si = IND.get(c) is not None and IND.get(c) == IND.get(L)
                            strong = (pct or 0) >= STRONG and (lead_line_pct(act.get(L), kw) or 0) >= STRONG
                            tags |= {"sp_same_ind" if si else "sp_cross_ind", "sp_strong" if strong else "sp_weak"}
                            if si and strong:
                                tags.add("sp_same_ind_strong")
                        for t in tags:
                            R[(90, h, t)].append(row)
                    k2 = (IND.get(c), dec[c])
                    if IND.get(c) and k2 in cm2:
                        m2, w2 = cm2[k2]
                        WI[(h, g)].append((c, ym, y - m2, 100.0 * ((y >= 90) - w2), y, p3[c], lag))
    return {"R": R, "WI": WI, "RAW": RAW, "cov": cov, "months": used}


# ---------------------------------------------------------------- 묶기 · 부트스트랩
def _q(xs, a):
    return round(xs[min(len(xs) - 1, int(a * len(xs)))], 2)


def boot(rows, ci, B, rng):
    """cluster(ci = 0 회사, 1 달) 부트스트랩 — 초과 · 상위10%초과 평균의 90% · 95% 구간."""
    g = {}
    for r in rows:
        s = g.setdefault(r[ci], [0.0, 0.0, 0])
        s[0] += r[2]; s[1] += r[3]; s[2] += 1
    ks = sorted(g)
    SE, SW, SN = [g[k][0] for k in ks], [g[k][1] for k in ks], [g[k][2] for k in ks]
    K, ix = len(ks), range(len(ks))
    oe, ow = [], []
    for _ in range(B):
        p = rng.choices(ix, k=K)
        n = sum(map(SN.__getitem__, p))
        oe.append(sum(map(SE.__getitem__, p)) / n)
        ow.append(sum(map(SW.__getitem__, p)) / n)
    oe.sort(); ow.sort()
    return ([_q(oe, .05), _q(oe, .95)], [_q(oe, .025), _q(oe, .975)]), ([_q(ow, .05), _q(ow, .95)], [_q(ow, .025), _q(ow, .975)])


def summ(rows, B, label, ci=True):
    if not rows:
        return {"n": 0}
    n = len(rows)
    o = {"n": n, "co": len({r[0] for r in rows}), "mo": len({r[1] for r in rows}),
         "ex": round(sum(r[2] for r in rows) / n, 2), "top10_ex": round(sum(r[3] for r in rows) / n, 2),
         "top10": round(100.0 * sum(r[4] >= 90 for r in rows) / n, 1), "own_p3": round(sum(r[5] for r in rows) / n, 1)}
    if ci:
        rng = random.Random(zlib.crc32(label.encode("utf-8")))
        (e90, e95), (w90, w95) = boot(rows, 0, B, rng)
        (m90, m95), (v90, v95) = boot(rows, 1, B, rng)
        o.update(ex_ci90_co=e90, ex_ci90_mo=m90, ex_ci95_co=e95, ex_ci95_mo=m95,
                 top10_ci90_co=w90, top10_ci90_mo=v90, top10_ci95_co=w95, top10_ci95_mo=v95)
    return o


def boot_diff(A, Bb, ci, B, rng):
    ga, gb = collections.defaultdict(lambda: [0.0, 0]), collections.defaultdict(lambda: [0.0, 0])
    for r in A:
        ga[r[ci]][0] += r[2]; ga[r[ci]][1] += 1
    for r in Bb:
        gb[r[ci]][0] += r[2]; gb[r[ci]][1] += 1
    ks = sorted(set(ga) | set(gb))
    A1, A2 = [ga[k][0] if k in ga else 0.0 for k in ks], [ga[k][1] if k in ga else 0 for k in ks]
    B1, B2 = [gb[k][0] if k in gb else 0.0 for k in ks], [gb[k][1] if k in gb else 0 for k in ks]
    K, ix = len(ks), range(len(ks))
    out = []
    for _ in range(B):
        p = rng.choices(ix, k=K)
        n1, n2 = sum(map(A2.__getitem__, p)), sum(map(B2.__getitem__, p))
        if n1 and n2:
            out.append(sum(map(A1.__getitem__, p)) / n1 - sum(map(B1.__getitem__, p)) / n2)
    out.sort()
    return [_q(out, .05), _q(out, .95)], [_q(out, .025), _q(out, .975)]


def diff(A, Bb, B, label, scale=1.0):
    if not A or not Bb:
        return {"n_a": len(A), "n_b": len(Bb)}
    rng = random.Random(zlib.crc32(label.encode("utf-8")))
    s = lambda xs: [(r[0], r[1], r[2] * scale) for r in xs]    # noqa: E731
    A, Bb = s(A), s(Bb)
    c90, c95 = boot_diff(A, Bb, 0, B, rng)
    m90, m95 = boot_diff(A, Bb, 1, B, rng)
    ma, mb = sum(r[2] for r in A) / len(A), sum(r[2] for r in Bb) / len(Bb)
    return {"n_a": len(A), "co_a": len({r[0] for r in A}), "n_b": len(Bb), "co_b": len({r[0] for r in Bb}),
            "a": round(ma, 2), "b": round(mb, 2), "diff": round(ma - mb, 2),
            "ci90_co": c90, "ci90_mo": m90, "ci95_co": c95, "ci95_mo": m95}


def report(X, B):
    R, WI, RAW = X["R"], X["WI"], X["RAW"]
    per = lambda rows, f: [r for r in rows if f(r[1])]    # noqa: E731
    res = {"main_top10": {}, "within_industry": {}, "sp_variants": {}, "sc_split": {}, "lag": {}, "lag_scratch_raw": {}, "thresholds": {}}
    for h in H:
        hk = "%dm" % h
        res["main_top10"][hk] = {p: {g: summ(per(R[(90, h, g)], f), B, "m|%s|%s|%s" % (hk, p, g)) for g in ("sc", "sp", "ind")} for p, f in PERIODS}
        res["sc_split"][hk] = {p: {g: summ(per(R[(90, h, g)], f), B, "s|%s|%s|%s" % (hk, p, g)) for g in ("sc_xgrp", "sc_strong", "sc_weak")} for p, f in PERIODS}
        res["within_industry"][hk] = {p: {g: summ(per(WI[(h, g)], f), B, "w|%s|%s|%s" % (hk, p, g)) for g in ("sc", "sp")} for p, f in PERIODS}
        res["sp_variants"][hk] = {}
        for g in ("sp_same_ind", "sp_cross_ind", "sp_strong", "sp_weak", "sp_same_ind_strong"):
            o = summ(R[(90, h, g)], B, "v|%s|%s" % (hk, g))
            for p, f in PERIODS[1:]:
                rs = per(R[(90, h, g)], f)
                o[p] = {"n": len(rs), "ex": round(sum(r[2] for r in rs) / len(rs), 2) if rs else None}
            res["sp_variants"][hk][g] = o
        res["lag"][hk] = {}
        res["lag_scratch_raw"][hk] = {}
        for g in ("sc", "sp"):
            res["lag"][hk][g] = {}
            for p, f in PERIODS:
                rs = per(R[(90, h, g)], f)
                A, Bb = [r for r in rs if r[6] >= LAG], [r for r in rs if r[6] < LAG]
                res["lag"][hk][g][p] = {"lag": summ(A, B, "l|%s|%s|%s|a" % (hk, g, p)), "rest": summ(Bb, B, "l|%s|%s|%s|b" % (hk, g, p)),
                                        "diff": diff(A, Bb, B, "l|%s|%s|%s|d" % (hk, g, p))}
            res["lag_scratch_raw"][hk][g] = {}
            for p, f in PERIODS:
                A = [(c, ym, x) for (ym, c), x in RAW[(g, True, h)].items() if f(ym)]
                Bb = [(c, ym, x) for (ym, c), x in RAW[(g, False, h)].items() if f(ym)]
                res["lag_scratch_raw"][hk][g][p] = diff(A, Bb, B, "r|%s|%s|%s" % (hk, g, p), scale=100.0)
    for thr in THRS[1:]:
        tk = "top%d" % (100 - thr)
        res["thresholds"][tk] = {"%dm" % h: {g: summ(R[(thr, h, g)], B, "t|%s|%d|%s" % (tk, h, g)) for g in ("sc", "sp", "ind")} for h in (3, 6)}
    res["coverage"] = X["cov"]
    res["months"] = {"n": len(X["months"]), "first": X["months"][0] if X["months"] else None, "last": X["months"][-1] if X["months"] else None}
    # 스크래치와 견주기(95% 구간 · 회사 단위)
    M, L = res["main_top10"], res["lag_scratch_raw"]
    now = {"sc_6m": M["6m"]["all"]["sc"], "sp_6m": M["6m"]["all"]["sp"], "ind_6m": M["6m"]["all"]["ind"],
           "sc_3m": M["3m"]["all"]["sc"], "sp_3m": M["3m"]["all"]["sp"], "ind_3m": M["3m"]["all"]["ind"]}
    vs = []
    for k, (lab, v, ci, n, co) in SCRATCH.items():
        if k in now:
            o = now[k]
            cur = (o.get("ex"), o.get("ex_ci95_co"), o.get("n"), o.get("co"))
        elif k.endswith("_top10"):
            o = now[k[:-6]]
            cur = (o.get("top10_ex"), o.get("top10_ci95_co"), o.get("n"), o.get("co"))
        elif k == "sc_6m_within_ind":
            o = res["within_industry"]["6m"]["all"]["sc"]
            cur = (o.get("ex"), o.get("ex_ci95_co"), o.get("n"), o.get("co"))
        else:
            o = L["6m"]["sc" if "_sc_" in k else "sp"]["all"]
            cur = (o.get("diff"), o.get("ci95_co"), o.get("n_a"), o.get("co_a"))
        vs.append({"key": k, "what": lab, "scratch": v, "scratch_ci95_co": ci, "scratch_n": n, "scratch_co": co,
                   "now": cur[0], "now_ci95_co": cur[1], "now_n": cur[2], "now_co": cur[3],
                   "delta": round(cur[0] - v, 2) if cur[0] is not None else None})
    res["vs_scratch"] = vs
    return res


# ---------------------------------------------------------------- 쓰기
def _ci(c):
    return "[%+.2f, %+.2f]" % tuple(c) if c else "[—]"


def _ex0(c):
    return bool(c) and (c[0] > 0 or c[1] < 0)


def md(res, design, caveats, made):
    M = res["main_top10"]
    L = []
    L.append("# 밸류체인 후속주 백테스트 (%s)" % made)
    L.append("")
    L.append("주장: 주도주(월말 3개월 수익률 상위 10%%)와 밸류체인으로 이어진 회사가 그 뒤 더 오른다. 시점 %s ~ %s · %d달 · 지금 상장 %s곳."
             % (res["months"]["first"], res["months"]["last"], res["months"]["n"], design["universe"]))
    L.append("값 = 앞 h개월 수익률 백분위 − 대조(같은 달 · 같은 자기 모멘텀 10분위 · 안 이어진 비주도주 · 주도주 업종 밖) 평균, 백분위 점. 괄호 = 90% 구간(회사 단위 / 달 단위).")
    L.append("")
    L.append("| 묶음 | 1개월 | 3개월 | 6개월 | 6개월 n · 회사 |")
    L.append("|---|---|---|---|---|")
    lab = {"sc": "공급망 후속주", "sp": "같은 제품 후속주", "ind": "같은 업종 · 안 이어짐(위약)"}
    for g in ("sc", "sp", "ind"):
        cells = []
        for hk in ("1m", "3m", "6m"):
            o = M[hk]["all"][g]
            cells.append("%+.2f %s / %s" % (o["ex"], _ci(o.get("ex_ci90_co")), _ci(o.get("ex_ci90_mo"))))
        o6 = M["6m"]["all"][g]
        L.append("| %s | %s | %d · %d |" % (lab[g], " | ".join(cells), o6["n"], o6["co"]))
    W = res["within_industry"]["6m"]["all"]
    for g in ("sc", "sp"):
        o = W[g]
        if o.get("n"):
            L.append("| %s vs 같은 업종 안 대조 | | | %+.2f %s / %s | %d · %d |" % (lab[g], o["ex"], _ci(o.get("ex_ci90_co")), _ci(o.get("ex_ci90_mo")), o["n"], o["co"]))
    L.append("")
    L.append("앞(2012~18) / 뒤(2019~26), 6개월:")
    for g in ("sc", "sp", "ind"):
        e, l = M["6m"]["early"][g], M["6m"]["late"][g]
        L.append("- %s: 앞 %+.2f %s (n %d) · 뒤 %+.2f %s (n %d)" % (lab[g], e["ex"], _ci(e.get("ex_ci90_co")), e["n"], l["ex"], _ci(l.get("ex_ci90_co")), l["n"]))
    L.append("")
    L.append("P(앞 6개월 상위 10%) − 대조, %p (실제 비율):")
    for g in ("sc", "sp", "ind"):
        o = M["6m"]["all"][g]
        L.append("- %s: %+.2f %s / %s (%.1f%%)" % (lab[g], o["top10_ex"], _ci(o.get("top10_ci90_co")), _ci(o.get("top10_ci90_mo")), o["top10"]))
    L.append("")
    L.append("'덜 오름'(주도주보다 3개월 백분위 %d점 넘게 뒤처짐) − 나머지, 6개월:" % LAG)
    for g in ("sc", "sp"):
        d = res["lag"]["6m"][g]["all"]["diff"]
        r = res["lag_scratch_raw"]["6m"][g]["all"]
        L.append("- %s: 백분위 %+.2f점 %s / %s (덜 오름 n %d · 나머지 n %d) · 수익률(스크래치 식) %+.2f%%p %s"
                 % (lab[g], d["diff"], _ci(d.get("ci90_co")), _ci(d.get("ci90_mo")), d["n_a"], d["n_b"], r["diff"], _ci(r.get("ci90_co"))))
    L.append("")
    sc6, sp6, in6 = M["6m"]["all"]["sc"], M["6m"]["all"]["sp"], M["6m"]["all"]["ind"]
    wsc = W["sc"]
    side = lambda o, k="ex_ci90": "회사 단위 %s · 달 단위 %s" % tuple("벗어남" if _ex0(o.get(k + s)) else "품음" for s in ("_co", "_mo"))   # noqa: E731
    S = res["sc_split"]["6m"]["all"]
    L.append("읽기(90% 구간이 0 을 벗어나나):")
    L.append("- 공급망 6개월 %+.2f — %s. 같은 업종 위약 %+.2f 와의 단순 차 %+.2f · 같은 업종 안 대조로는 %+.2f(%s)."
             % (sc6["ex"], side(sc6), in6["ex"], sc6["ex"] - in6["ex"], wsc.get("ex", float("nan")), side(wsc)))
    L.append("- 공급망 갈래 6개월: 같은 재벌끼리만인 짝 빼면 %+.2f · 강한(비중 ≥ %.0f%%) %+.2f (n %d) · 약한/비중 모름 %+.2f (n %d) — 연결 세기로 갈리지 않는다."
             % (S["sc_xgrp"]["ex"], STRONG, S["sc_strong"]["ex"], S["sc_strong"]["n"], S["sc_weak"]["ex"], S["sc_weak"]["n"])
             if S.get("sc_strong", {}).get("n") and S.get("sc_weak", {}).get("n") else "- 공급망 갈래: 표본 없음.")
    L.append("- 같은 제품 6개월 %+.2f — %s. P(상위 10%%) 초과 %+.2f%%p — 같은 업종 위약 %+.2f%%p 보다 %s."
             % (sp6["ex"], side(sp6), sp6["top10_ex"], in6["top10_ex"], "낮다" if sp6["top10_ex"] < in6["top10_ex"] else "높다"))
    lg = res["lag"]["6m"]["sc"]
    if lg["all"]["diff"].get("diff") is not None:
        L.append("- '덜 오름' 공급망 후속주 − 나머지 %+.2f점(%s) — 앞 %+.2f · 뒤 %+.2f. %s"
                 % (lg["all"]["diff"]["diff"], side(lg["all"]["diff"], "ci90"), lg["early"]["diff"].get("diff", float("nan")), lg["late"]["diff"].get("diff", float("nan")),
                    "덜 오른 쪽이 더 오르지 않는다." if lg["all"]["diff"]["diff"] < 0 else "덜 오른 쪽이 더 오른다."))
    L.append("")
    L.append("스크래치(vcbt/out1~4, 95% 회사 단위)와 견주기:")
    L.append("")
    L.append("| 항목 | 스크래치 | 지금 | 차이 |")
    L.append("|---|---|---|---|")
    for v in res["vs_scratch"]:
        L.append("| %s | %+.2f %s n %d | %s %s n %s | %s |" % (v["what"], v["scratch"], _ci(v["scratch_ci95_co"]), v["scratch_n"],
                                                       "%+.2f" % v["now"] if v["now"] is not None else "—", _ci(v["now_ci95_co"]), v["now_n"],
                                                       "%+.2f" % v["delta"] if v["delta"] is not None else "—"))
    L.append("")
    L.append("한계:")
    L += ["- " + c for c in caveats]
    L.append("")
    L.append("전체 값: .cache/vcmap/bt.json · 도구: 도구/밸류체인_후속주_백테스트.py")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=1000)
    a = ap.parse_args()
    t0 = time.time()
    D = load()
    prep(D)
    t1 = time.time()
    print("읽기 %.0f초 · 색인 %d · 주가 %d · 밸류체인 %d · 이름 %d" % (t1 - t0, len(D["univ"]), len(D["cl"]), len(D["vc"]), len(D["names"])))
    X = build(D)
    t2 = time.time()
    print("사건 줄 %.0f초 · 달 %d (%s~%s)" % (t2 - t1, len(X["months"]), X["months"][0], X["months"][-1]))
    res = report(X, a.boot)
    t3 = time.time()
    made = dt.datetime.now().isoformat(timespec="seconds")
    design = {
        "claim": "월말 3개월 수익률 상위 10% 주도주와 밸류체인으로 이어진 회사(후속주)가 그 뒤 1 · 3 · 6개월에 더 오른다",
        "events": "월말 %s ~ %s, 종가 = 그 달 마지막 거래일(18일 · 2월 16일 전이면 모름), 단면 %d곳 이상" % (X["months"][0], X["months"][-1], MIN_XS),
        "universe": len(D["univ"]),
        "leader": "3개월 수익률 백분위 ≥ 90(민감도 95 · 98)",
        "links": {"pit": "밸류체인 years[] 접수일 ≤ t · %d일 안 · 칸이 비지 않은 마지막 표" % MAXAGE,
                  "sc": "매출처(named + subs) · 매입처(materials suppliers) 두 방향, 이름 맞추기 = 스크래치 load.key(별칭 + CORPCODE), 강한 = 비중 ≥ %.0f%%" % STRONG,
                  "sp": "주도주 product_words 로 끝나는 짝 제품 이름(products_of top12 · 5%% 이상 · 장비 규칙), 밸류체인_지도 V=%s 지금 모습" % getattr(VMAP, "V", "?"),
                  "sp_strong": "짝 줄 · 주도주 줄 비중 둘 다 ≥ %.0f%%" % STRONG},
        "groups": "겹치지 않게 sc > sp > ind(주도주와 같은 지금 업종 · 안 이어짐), 주도주 자신은 뺀다",
        "control": "같은 달 · 같은 자기 3개월 10분위 · 주도주 아님 · 어떤 주도주와도 안 이어짐 · 주도주 업종 밖, 칸 %d곳 이상" % MIN_CELL,
        "within_industry_control": "같은 달 · 후속주 업종 · 같은 10분위의 안 이어진 비주도주(스크래치 analyze2, 여기선 sc/sp 겹치지 않게)",
        "outcome": "앞 h개월 수익률 전 종목 백분위 − 대조 칸 평균(백분위 점) · P(백분위 ≥ 90) − 대조 칸 비율(%p)",
        "lag": "'덜 오름' = 이어진 주도주 중 최대 (주도주 p3 − 후속주 p3) ≥ %d — 나머지와 차이(백분위). 스크래치 식(수익률 − 단면 중앙값, −95%%~+300%% 자름, 짝 단위 · 겹침 허용)도 같이" % LAG,
        "bootstrap": "%d번, 회사 단위 · 달 단위, 90%%(+95%%)" % a.boot,
        "periods": "앞 < %s ≤ 뒤" % SPLIT,
        "scratch": ".cache/밸류체인_검토/vcbt/ (2026-10-18)",
        "industry_map_built": D["ind_built"],
    }
    caveats = [
        "지금 상장된 %d곳만(색인) — 상장폐지 · 합병으로 사라진 회사는 주도주로도 후속주로도 없다(생존 편향)" % len(D["univ"]),
        "업종은 지금 분류(.cache/업종/map.json) — 과거 시점의 업종이 아니고, 같은 업종 위약 · 대조 제외도 이 분류로 했다",
        "이름 → 종목 맞추기는 스크래치 규칙(별칭 · CORPCODE 이름) — 서버 linker 와 다를 수 있고, 짧은 · 가려진 이름은 잘못 이을 수 있다(audit)",
        "밸류체인 표는 지금 파서 · 지금 밸류체인_지도 규칙으로 뽑은 값 — 내용은 그때 공시에 있던 것이지만 뽑는 규칙은 오늘 것",
        "매달 사건 · 3 · 6개월 창이 겹친다 — 회사 단위 구간은 같은 회사의 겹침을, 달 단위 구간은 같은 달의 동시 움직임을 잡지만 둘을 한꺼번에는 아니다",
        "주가 = 네이버 수정주가 월말 종가, 수수료 · 슬리피지 없음, 결과는 수익률이 아니라 백분위",
        "여러 갈래(묶음 · 지평 · 반 · 문턱)를 봤다 — 미리 정한 머리 결과는 6개월 sc · sp · ind 뿐, 나머지 구간은 다중 비교를 감안해 읽는다",
        "매출처 비중이 빈 줄이 많다(강한/약한 공급망 갈래는 비중이 적힌 것만 강한 쪽으로 간다)",
    ]
    rep = {"made": made, "design": design, "results": res, "caveats": caveats}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "bt.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "bt.md"), "w", encoding="utf-8") as fh:
        fh.write(md(res, design, caveats, made[:10]))
    # 요약
    M = res["main_top10"]
    print("집계 %.0f초 · 부트스트랩 %d" % (t3 - t2, a.boot))
    for hk in ("1m", "3m", "6m"):
        for g in ("sc", "sp", "ind"):
            o = M[hk]["all"][g]
            print("%s %-3s n %6d 회사 %3d 달 %3d  초과 %+5.2f  90%% 회사 %s 달 %s  · 상위10%% %+5.2f%%p %s  · 앞 %+5.2f 뒤 %+5.2f" % (
                hk, g, o["n"], o["co"], o["mo"], o["ex"], _ci(o["ex_ci90_co"]), _ci(o["ex_ci90_mo"]), o["top10_ex"], _ci(o["top10_ci90_co"]),
                M[hk]["early"][g]["ex"], M[hk]["late"][g]["ex"]))
    for g in ("sc", "sp"):
        w = res["within_industry"]["6m"]["all"][g]
        d = res["lag"]["6m"][g]["all"]["diff"]
        print("6m %s 같은 업종 안 대조 %+5.2f %s n %d · 덜 오름 − 나머지 %+5.2f %s" % (g, w["ex"], _ci(w["ex_ci90_co"]), w["n"], d["diff"], _ci(d["ci90_co"])))
    print("스크래치와(95% 회사 단위):")
    for v in res["vs_scratch"]:
        print("  %-40s 스크래치 %+5.2f %s n %5d → 지금 %+5.2f %s n %5s (차이 %+5.2f)" % (
            v["what"], v["scratch"], _ci(v["scratch_ci95_co"]), v["scratch_n"], v["now"], _ci(v["now_ci95_co"]), v["now_n"], v["delta"]))
    print("저장:", os.path.join(OUT, "bt.json"), "·", os.path.join(OUT, "bt.md"), "· 전체 %.0f초" % (time.time() - t0))


if __name__ == "__main__":
    main()
