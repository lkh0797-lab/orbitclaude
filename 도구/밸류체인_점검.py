# -*- coding: utf-8 -*-
"""
밸류체인 자료 점검 (2026-10-19) — 파서(밸류체인.py) · 제품 정리(밸류체인_지도.products_of) · 서버 표시 규칙을 고친 뒤 같은 잣대로 다시 재는 도구.
2026-10-18 리뷰 때 흩어져 있던 스크래치(.cache/밸류체인_검토/audit/vc_audit*.py · prod_adj.py)를 한 파일로 모았다.

무엇을 재나(지금 칸 = 회사 · 칸(매출처 cust · 종속회사 고객 subcust · 매입처 supp)마다 이름 적힌 줄이 있는 마지막 해 — 서버 _vc_tab_last 의 cn · sn 과 같은 생각):
  (1) 자기 줄    — 회사가 자기 자신을 매출처 · 매입처로 적은 줄(국문 키 _vc_key · CORPCODE corp_eng_name 영문 · 이름이 내 코드로 이어짐).
                   그중 서버 규칙(own_keys = 내 키 + 영문 자기 이름, 내 코드로 이어지면 자기)이 '자기'로 못 잡는 줄 = 표시 누락.
  (2) 같은 그룹  — 그룹 판정은 서버와 따로 둔 이름 목록(GROUP_RX, 2026-10-18 리뷰 vc_audit4 의 27개 그룹)으로 하고, 표시는 서버 규칙을 그대로 흉내 낸다:
                   own(내 키 · 종속회사 · 부문 범위) 또는 grp(.cache/own/{코드}.json 계열 이름 · 계열 코드 · 최대주주 · 20%↑/경영참여 지분, 그리고 두 글자 어간 규칙).
                   잰다: 같은 그룹 줄 중 표시 안 된 비율. 거꾸로 서버만 같은 그룹이라 한 줄(어간 규칙 오탐 후보)도 센다.
                   소유 캐시가 없는 회사는 서버가 화면을 열 때 보고서에서 만든다 — 여기선 캐시만 읽으니 어간 규칙만 쓴다(전체 비율은 상한, 캐시 있는 회사 비율을 따로 낸다).
  (3) 제품 줄    — 회사마다 제품 표가 있는 마지막 해를 products_of 로 정리한 뒤 비중 > 100% 줄(0 이어야), 합계 · 조정 · 손익 줄(0 이어야 — 공백 지우고 별도 정규식으로).
                   참고: 표는 있는데 products_of 가 다 지운 회사, 비중 합 > 110% 회사.
  (4) 스토리 칩  — 지금 판(VCMAP_V) 지도 판(.cache/vcmap/{코드}.json head.story.words) 중 자기 이름 낱말(밸류체인_지도.self_words)과 같은 칩.
  (5) 붙은 이름  — 한 칸에 회사 둘(법인 꼬리 둘 · 한글+영문 붙음 · 상장사 이름 둘 · 구분자) — vc_audit3 휴리스틱 그대로.
  (6) 잡이름     — 단위 · '등/외' 꼬리 · 각주 · 숫자 · 괄호 짝 · 문장 조각 · 회사 아닌 말 · 제품 꼴 — vc_audit3 그대로.
  (7) 잇기       — 지금 칸 이름 줄 중 상장사로 이어지는 비율(서버 link 흉내 · 밸류체인_지도.Linker · 둘 중 하나).
  (8) 지도 판    — 지금 판 B · C · D · Fake 수, B 인데 공급망 직접 연결이 없는 줄(parts.link < 5 — 2026-10-19 규칙: B = 공급망 직접만),
                   그중 연결 근거가 같은 제품뿐인 줄(0 이어야). 참고: 상류 매입처 칸에 주도주 자신.
지도 판은 sig 머리 'VCMAP_V.VMAP.V' 의 VCMAP_V 가 서버.py 의 지금 값과 같은 것만 잰다(옛 판은 판 수만 세고 (4) · (8) 은 참고 줄로).

서버.py 는 import 하지 않는다(API 키 · 스레드를 띄운다) — 글을 읽어 VCMAP_V 숫자와 순수 도우미(_norm_corp · VC_ALIAS · _vc_strip · _vc_key · _vc_canon ·
valuechain_view 안의 _stem · common)만 꺼내 실행한다. 그래서 그 도우미가 바뀌면 이 도구도 따라간다(꺼내지 못하면 멈추고 알린다 · 어간 규칙만 사본으로).
단 표시 규칙 몸통(own_of · same_group — 아래 Ctx)과 B 규칙(parts.link < 5)은 2026-10-19 서버 · 밸류체인_지도 를 옮긴 사본이다 — 서버 쪽을 바꾸면 여기도 맞춘다.
캐시만 읽는다(네트워크 0). 결과 → .cache/밸류체인/_점검.json {made, src, counts, rates, examples(항목마다 ≤5)}, 화면에 표.
실행: python -X utf8 도구/밸류체인_점검.py        (CORPCODE 30MB 풀기 포함 1분 안팎)
"""
import os, sys, re, json, glob, html, ast, time, datetime as dt, importlib.util
from collections import Counter, defaultdict

sys.dont_write_bytecode = True       # 모듈을 읽기만 — __pycache__ 를 건드리지 않는다
HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
CACHE = os.path.join(BASE, ".cache")
OUT = os.path.join(CACHE, "밸류체인", "_점검.json")
NEX = 5                 # 항목마다 예시 수


def _load(name):
    spec = importlib.util.spec_from_file_location(name + "_점검", os.path.join(BASE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


VCM = _load("밸류체인")
VMAP = _load("밸류체인_지도")

# ---------------------------------------------------------------- 서버.py 글에서 규칙 꺼내기(import 하지 않는다)
SRV_SRC = open(os.path.join(BASE, "서버.py"), encoding="utf-8").read()
_m = re.search(r"^VCMAP_V\s*=\s*(\d+)", SRV_SRC, re.M)
if not _m:
    sys.exit("서버.py 에서 VCMAP_V 를 못 찾았다 — 이름이 바뀌었으면 이 도구를 고친다")
VCMAP_V = int(_m.group(1))


def _srv_chunk(name):
    """서버.py 맨 바깥 'def name(' 또는 'name = ' 덩어리 글 — 다음 맨 바깥 문장(들여쓰기 없는 줄, 닫는 괄호 · 주석 빼고) 앞까지."""
    lines = SRV_SRC.split("\n")
    rx = re.compile(r"^(?:def %s\(|%s\s*=)" % (re.escape(name), re.escape(name)))
    for i, ln in enumerate(lines):
        if rx.match(ln):
            j = i + 1
            while j < len(lines) and (not lines[j] or lines[j][0] in " \t#)}]"):
                j += 1
            return "\n".join(lines[i:j])
    return None


NS = {"re": re, "html": html, "VCM": VCM}
for _nm in ("_LATIN_KO", "_norm_corp", "VC_ALIAS", "_vc_strip", "_vc_key", "_vc_canon"):
    _src = _srv_chunk(_nm)
    if not _src:
        sys.exit("서버.py 에서 %s 를 못 찾았다 — 이름이 바뀌었으면 이 도구를 고친다" % _nm)
    exec(compile(_src, "서버.py:" + _nm, "exec"), NS)
_norm_corp, _vc_key, _vc_canon = NS["_norm_corp"], NS["_vc_key"], NS["_vc_canon"]
RULE_SRC = "서버.py 글"
_ms = re.search(r"\n    def _stem\(nm\):\n((?:        .*\n)+)", SRV_SRC)
_mc = re.search(r"\n    common = (\{[^\n]*\})", SRV_SRC)
if _ms and _mc:
    exec(compile("def _stem(nm):\n" + re.sub(r"(?m)^    ", "", _ms.group(1)), "서버.py:_stem", "exec"), NS)
    _stem, COMMON = NS["_stem"], ast.literal_eval(_mc.group(1))
else:                    # 사본(2026-10-19 서버.valuechain_view) — 서버 글에서 못 꺼냈을 때만
    RULE_SRC = "사본(서버 글에서 _stem · common 을 못 꺼냄)"

    def _stem(nm):
        s = re.sub(r"\(주\)|㈜|주식회사|홀딩스|지주|그룹|^HS|^HD|^HL", "", nm or "").strip()
        m_ = re.match(r"^[A-Za-z가-힣]{2}", s)
        return m_.group(0) if m_ else s[:2]
    COMMON = {"한국", "대한", "국제", "동양", "서울", "신한", "제일", "태양", "세계"}

# ---------------------------------------------------------------- 수집 목록 · CORPCODE · 이름 잇기
INDEX = json.load(open(os.path.join(CACHE, "색인.json"), encoding="utf-8"))["companies"]
UNIV = {c["code"]: c for c in INDEX}
_t = open(os.path.join(CACHE, "CORPCODE.xml"), "rb").read().decode("utf-8", errors="replace")
CORPS = []
for _mm in re.finditer(r"<list>(.*?)</list>", _t, re.S):
    _b = _mm.group(1)
    _g = lambda k: html.unescape((re.search(r"<%s>(.*?)</%s>" % (k, k), _b, re.S) or [None, ""])[1].strip())     # noqa: E731
    if _g("stock_code"):
        CORPS.append((_g("stock_code"), _g("corp_name"), _g("corp_eng_name"), _g("modify_date")))
del _t
ENG_OF = {}
for _sc, _nm, _en, _md in sorted(CORPS, key=lambda r: r[3] or "", reverse=True):
    ENG_OF.setdefault(_sc, _en)
NAMES = {_norm_corp(c["name"]): c["code"] for c in INDEX}            # == 서버._listed_names
for _sc, _nm, _en, _md in sorted(CORPS, key=lambda r: r[3] or "", reverse=True):
    NAMES.setdefault(_norm_corp(_nm), _sc)
EN = VCM.EnNames(CORPS)
LK = VMAP.Linker(CORPS, {c["code"]: c["name"] for c in INDEX})       # == 서버._vcmap_linker
NAME_OF = dict(LK.name_of)


def srv_link(nm, prefer=()):
    """== 서버.valuechain_view 안 link() — 별명 표 → 정규화 이름 색인, 영문만이면 EnNames(4자 미만 안 잇기)."""
    cn = _vc_canon(nm)
    if not re.search(r"[가-힣]", nm or "") and cn == nm:
        return EN.code(nm, UNIV, prefer)
    for cand in (cn, re.sub(r"\(\*+\)|\s*본사$|\(주\)|㈜|주식회사", "", nm or "").strip()):
        cd = NAMES.get(_norm_corp(cand))
        if cd:
            return cd
    return None


def map_link(nm):
    try:
        return LK.code(_vc_canon(nm))
    except Exception:
        return None


def en_full(s):
    return "".join(VMAP.en_words(s))


# ---------------------------------------------------------------- 줄 모으기
def entries(d, y, seg_names):
    """(칸, 이름, 비중, 덧붙임) — 서버 valuechain_view 와 같은 거름(부문 이름 · 수주잔고 · '-' · 합계 원재료 줄 뺌)."""
    L = d["years"][y]
    out = []
    for x in L.get("customers") or []:
        if x.get("kind") != "named" or not x.get("name") or re.sub(r"\s+", "", x["name"]) in seg_names or re.search(r"수주\s*잔|잔고|매출액|당기말|전기말", x["name"]):
            continue
        out.append(("cust", x["name"], x.get("pct"), {"seg": x.get("seg")}))
    for s in L.get("subs") or []:
        for nm, pct in (s.get("final") or s.get("customers") or []):
            if nm:
                out.append(("subcust", nm, pct, {"sub": s.get("sub")}))
    for mt in L.get("materials") or []:
        if not mt.get("item") or mt.get("item") == "-" or re.search(r"합\s*계", (mt.get("item") or "") + " " + (mt.get("segment") or "")):
            continue
        for sp in mt.get("suppliers") or []:
            if sp.get("name"):
                out.append(("supp", sp["name"], mt.get("pct"), {"item": mt.get("item")}))
    return out


def load_own(code):
    try:
        return json.load(open(os.path.join(CACHE, "own", code + ".json"), encoding="utf-8"))
    except Exception:
        return None


class Ctx:
    """회사 하나의 서버 표시 규칙 흉내 — own_of(자기 · 종속회사 · 부문 범위) · same_group(어간 · 계열 이름 · 계열 코드). 서버는 마지막 칸(years[-1])으로 짠다."""

    def __init__(self, code, name, d):
        last = d["years"][sorted(d["years"])[-1]]
        self.code, self.name = code, name
        self.me_k = _vc_key(name)
        ok = {self.me_k} | {_vc_key(s["sub"]) for s in last.get("subs") or [] if s.get("sub")}
        ok |= {_vc_key(x["scope"]) for x in last.get("customers") or [] if x.get("basis") == "부문" and x.get("scope")}
        ok = {k for k in ok if len(k) >= 4}
        ok.add(self.me_k)
        self.en_self = "".join(LK.en_of.get(code) or [])
        if len(self.en_self) >= 2:
            ok.add(self.en_self[:24])
        self.own_keys = ok
        ow = load_own(code) or {}
        self.has_own = bool(ow)
        names = (ow.get("group") or {}).get("names") or ()
        gc = {cd for _, cd in names if cd} - {code}
        if (ow.get("owner") or {}).get("code"):
            gc.add(ow["owner"]["code"])
        gc |= {h["code"] for h in ow.get("holdings") or () if h.get("code") and ((h.get("pct") or 0) >= 20 or "경영" in (h.get("purpose") or ""))}
        self.grp_codes = gc
        self.grp_keys = {_vc_key(nm) for nm, _ in names if nm} - {self.me_k}
        self.stem = _stem(name)

    def own_of(self, nm, lk):
        k = _vc_key(nm)
        if k in self.own_keys:
            return self.me_k if (self.en_self and k == self.en_self[:24]) else k
        if lk == self.code:
            return self.me_k
        hits = [o for o in self.own_keys if len(o) >= 6 and (k.startswith(o) or (o.startswith(k) and len(k) >= 6))]
        return max(hits, key=len) if hits else None

    def same_group(self, nm, lk):
        if bool(self.stem) and self.stem not in COMMON and _stem(nm) == self.stem:
            return "stem"
        if _vc_key(nm) in self.grp_keys:
            return "own_name"
        if lk and lk in self.grp_codes:
            return "own_code"
        return None


def collect():
    rows, ctxs, n_files, n_years = [], {}, 0, 0
    for f in sorted(glob.glob(os.path.join(CACHE, "밸류체인", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        n_files += 1
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not d.get("years"):
            continue
        n_years += 1
        code = d.get("code") or os.path.basename(f)[:6]
        name = (UNIV.get(code) or {}).get("name") or d.get("name") or code
        ys = sorted(d["years"])
        seg_names = set()
        for y in ys:
            dy = d["years"][y]
            seg_names |= {re.sub(r"\s+", "", v) for v in [x.get("seg") for x in dy.get("customers") or []] + [m.get("segment") for m in dy.get("materials") or []] +
                          [g.get("segment") for g in dy.get("segments") or []] + [p.get("segment") for p in dy.get("products") or []] if v}
        by = defaultdict(list)
        for y in ys:
            for e in entries(d, y, seg_names):
                by[(e[0], y)].append(e)
        cur_y = {}
        for (fld, y) in by:
            cur_y[fld] = max(cur_y.get(fld, ""), y)
        got = [e + (y,) for (fld, y), es in by.items() if cur_y[fld] == y for e in es]
        if not got:
            continue
        ctx = ctxs[code] = Ctx(code, name, d)
        for fld, nm, pct, extra, y in got:
            srv, mp = srv_link(nm), map_link(nm)
            lk = srv or mp
            o = ctx.own_of(nm, srv)
            rows.append({"code": code, "co": name, "y": y, "field": fld, "ent": nm, "pct": pct, "srv": srv, "map": mp, "lk": lk,
                         "own": bool(o), "self_mark": o == ctx.me_k, "grp": (not o) and ctx.same_group(nm, srv),
                         "ctx": extra.get("item") or extra.get("sub") or extra.get("seg") or ""})
    return rows, ctxs, n_files, n_years


def fmt(r, more=""):
    p = (" %s%%" % r["pct"]) if isinstance(r.get("pct"), (int, float)) else ""
    lk = (" → %s %s" % (r["lk"], NAME_OF.get(r["lk"], ""))) if r.get("lk") else ""
    c = (" (%s)" % str(r["ctx"])[:24]) if r.get("ctx") else ""
    return ("%s %s [%s %s] '%s'%s%s%s%s" % (r["code"], r["co"], r["y"], r["field"], r["ent"], p, c, lk, (" " + more) if more else "")).strip()


# ---------------------------------------------------------------- (1) 자기 줄
SELF_WORD = re.compile(r"^(?:당사|지배회사|모회사|본사|자사|당사\s*본사)$")


def self_how(r):
    if _vc_key(r["ent"]) == _vc_key(r["co"]):
        return "key"
    e = en_full(ENG_OF.get(r["code"], ""))
    if e and len(e) >= 2 and not re.search(r"[가-힣]", r["ent"]) and en_full(r["ent"]) == e:
        return "eng"
    if r["srv"] == r["code"] or r["map"] == r["code"]:
        return "link"
    if SELF_WORD.match(r["ent"].strip()):
        return "word"
    return None


# ---------------------------------------------------------------- (2) 같은 그룹 — 서버와 따로 둔 그룹 이름 목록(vc_audit4)
GROUP_RX = {
    "삼성": r"^(?:삼성|SAMSUNG|에스원|제일기획|호텔신라|Samsung)", "LG": r"^(?:LG|엘지|L\.G\.)", "SK": r"^(?:SK|에스케이|에스케이씨|SKC)",
    "LS": r"^(?:LS|엘에스|가온전선|E1|INVENI|예스코|락성)", "롯데": r"^(?:롯데|LOTTE|Lotte)", "한화": r"^(?:한화|HANWHA|Hanwha)",
    "효성": r"^(?:효성|HYOSUNG|Hyosung|HS\s*효성|HS\s*HYOSUNG|HS\s*Hyosung)", "두산": r"^(?:두산|DOOSAN|Doosan)", "CJ": r"^(?:CJ|씨제이)",
    "GS": r"^(?:GS|지에스)(?!\s*건설기계)", "포스코": r"^(?:포스코|POSCO|Posco)", "코오롱": r"^(?:코오롱|KOLON|Kolon)", "세아": r"^(?:세아|SeAH|SEAH)",
    "HL": r"^(?:HL|에이치엘|만도|Mando|MANDO)", "DB": r"^(?:DB|디비)", "OCI": r"^(?:OCI|오씨아이)", "KCC": r"^(?:KCC|케이씨씨)",
    "한진": r"^(?:한진|대한항공|HANJIN|Hanjin)", "영풍": r"^(?:영풍|고려아연|YOUNGPOONG|코리아써키트|인터플렉스)",
    "아모레": r"^(?:아모레|AMOREPACIFIC|Amorepacific|에뛰드|이니스프리)", "셀트리온": r"^(?:셀트리온|CELLTRION|Celltrion)", "카카오": r"^(?:카카오|KAKAO|Kakao)",
    "한솔": r"^(?:한솔|HANSOL|Hansol)", "동국": r"^(?:동국|DONGKUK|Dongkuk)",
    "현대차": r"^(?:현대자동차|현대차|기아|KIA|Kia|현대모비스|Hyundai\s*Mobis|HYUNDAI\s*MOBIS|현대위아|현대제철|현대글로비스|현대건설(?!기계)|현대로템|현대오토에버|현대트랜시스|"
             r"현대케피코|현대엔지니어링|HYUNDAI\s*MOTOR|Hyundai\s*Motor|HMMA|HMMC|HMI\b|KMMG|현대비앤지스틸|현대머티리얼|현대아이에이치엘|현대IHL)",
    "HD현대": r"^(?:HD\s*현대|HD\s*HYUNDAI|HD\s*Hyundai|현대중공업|현대미포|한국조선해양|현대일렉트릭|현대건설기계|현대오일뱅크|현대삼호|현대두산인프라코어|현대에너지솔루션|현대힘스|현대케미칼|HHI\b)",
}     # '현대' 홀로(현대백화점 · 현대해상 · 현대엘리베이터 · HDC)는 그룹이 갈려 판정에서 뺀다
GRX = {g: re.compile(p) for g, p in GROUP_RX.items()}


def group_of(nm):
    nm = re.sub(r"^\s*(?:\(주\)|㈜|주식회사)\s*", "", nm or "").strip()
    hits = [g for g, rx in GRX.items() if rx.search(nm)]
    if "GS" in hits and "LG" in hits:
        hits.remove("LG")
    if "HD현대" in hits and "현대차" in hits:
        hits.remove("현대차")
    return hits[0] if hits else None


# ---------------------------------------------------------------- (5) 붙은 이름 · (6) 잡이름 — vc_audit3 그대로
CORP_MARK = re.compile(r"㈜|\(주\)|주식회사|유한\s*공사|유한\s*회사|\bCo\.?,?\s*Ltd\b|\bInc\b|\bLLC\b|\bLimited\b|\bCorp(?:oration)?\b|\bGmbH\b", re.I)
G_HAN_LAT = re.compile(r"[가-힣)][A-Z][a-z]{2,}")
G_LAT_HAN = re.compile(r"[a-z]{3,}[가-힣]")
LISTED_KO = sorted({_norm_corp(c["name"]) for c in INDEX if len(_norm_corp(c["name"])) >= 3 and re.search(r"[가-힣]", c["name"])}, key=len, reverse=True)
NONCO = re.compile(r"(?:제조|판매|부품|장비|용역|보수|개선|향상|사업|가전|증권|코스닥|패턴|Pattern|및\s|을|를|통한|위한|원재료|제품|상품)")


def two_listed(nm):
    if not re.search(r"[가-힣]", nm):
        return None
    k = _norm_corp(nm)
    found, used = [], [False] * len(k)
    for ln in LISTED_KO:
        i = k.find(ln)
        while i >= 0:
            if not any(used[i:i + len(ln)]):
                found.append(ln)
                for j in range(i, i + len(ln)):
                    used[j] = True
                break
            i = k.find(ln, i + 1)
        if len(found) >= 2:
            return found
    return None


def glued(nm):
    s = nm.strip()
    why = []
    paren_alias = re.search(r"\([A-Za-z][^)]*\)$|^[^(]*\([가-힣][^)]*\)$", s)       # '아이요봇(AIYOUBOT Co., Ltd.)' = 별칭
    if len(CORP_MARK.findall(s)) >= 2 and not paren_alias and not re.search(r"Chevron|U\.S\.A", s):
        why.append("2corp")
    if G_HAN_LAT.search(s):
        why.append("han+Lat")
    if G_LAT_HAN.search(s):
        why.append("lat+han")
    if two_listed(s):
        why.append("2listed")
    if re.search(r"[가-힣A-Za-z)]{2,}\s*(?:,|/|、|;|\s-\s|\s및\s|와\s|과\s)\s*[가-힣A-Za-z(]{2,}",
                 re.sub(r",\s*(?:Ltd|Inc|LLC|Limited|Co|Corp)\b\.?", "", s, flags=re.I)) and not NONCO.search(s):
        why.append("sep")
    return why


JUNK = [("unit", re.compile(r"백만\s*원|천\s*원|억\s*원|\d\s*원\b|\d\s*(?:톤|ton|kg|㎏|MT)\b|\d\s*%|USD|\$", re.I)),
        ("tail_등외", re.compile(r"(?:\s|[가-힣)])(?:등|외|外)(?:\s*\d+\s*(?:개사|곳|社))?\s*$|외\s*\d+\s*(?:개사|곳|社)")),
        ("footnote", re.compile(r"\(\s*주\s*\d+\s*\)|\(\s*\*+\s*\d*\s*\)|\*\s*\d|주\s*\d\)|※|^\*|\*$")),
        ("number", re.compile(r"^\s*\d|\d[\d,]{3,}|\b\d+(?:\.\d+)?\s*$")),
        ("paren_unbal", None),
        ("sentence", re.compile(r"(?:입니다|있습니다|합니다|됩니다|하였|으로서|에게|에서|하는|되는|위한|통한|사용되며|사용되고|이며|이고)\s*$|(?:을|를)\s")),
        ("nonco", re.compile(r"^(?:기타|합계|소계|국내|해외|수출|내수|당사|관계사|계열사|특수관계자|종속회사|대리점|고객|거래처|매출처|매입처|협력사|외주|자체|수입|직수입|"
                             r"현대/기아자동차|국내\s*업체|해외\s*업체|다수|불특정\s*다수|개인|일반|정부|조달청)$")),
        ("product_like", re.compile(r"(?:제조|판매|부품|장비|용역|보수|개선|향상|사업|가전|유지|원재료|패턴)(?:\s|$)|및\s"))]


def junk(nm):
    s = nm.strip()
    out = []
    for k, rx in JUNK:
        if k == "paren_unbal":
            if s.count("(") != s.count(")"):
                out.append(k)
        elif rx.search(s):
            if k == "number" and re.fullmatch(r"\s*\d[A-Za-z].*|.*[A-Za-z]\d+\s*", s) and not re.search(r"\d{3,}", s):
                continue          # '3M' · 'A1' 같은 이름 속 숫자
            out.append(k)
    return out


# ---------------------------------------------------------------- (3) 제품 줄 — products_of 뒤, 별도 정규식(공백 지우고)
ADJ_ALL = re.compile(r"합계|소계|총계|총매출|순매출|매출총계|매출계$|^계$|내부거래|내부매출|매출제거|연결제거|부문간|연결조정|조정및제거|연결실체내|단순합계|"
                     r"영업이익|영업손실|영업손익|매출원가|매출총이익|당기순")


def audit_products():
    n_co, over, sumr, emptied, oversum = 0, [], [], [], []
    n_rows = 0
    for f in sorted(glob.glob(os.path.join(CACHE, "밸류체인", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        ys = sorted(d.get("years") or {})
        py = next((y for y in reversed(ys) if d["years"][y].get("products")), None)
        if not py:
            continue
        n_co += 1
        code = d.get("code") or os.path.basename(f)[:6]
        name = (UNIV.get(code) or {}).get("name") or d.get("name")
        pr = d["years"][py]["products"]
        out = VMAP.products_of(pr)
        n_rows += len(out)
        tag = "%s %s [%s]" % (code, name, py)
        if not out:
            emptied.append("%s 표 %d줄 → 0줄 (첫 줄 '%s' / 부문 '%s')" % (tag, len(pr), (pr[0].get("item") or "")[:20], (pr[0].get("segment") or "")[:12]))
        for p in out:
            if (p.get("raw") if p.get("raw") is not None else (p.get("pct") or 0)) > 100.5:
                over.append("%s '%s' %.1f%%%s" % (tag, p["item"], p["pct"], " (금액 추정)" if p.get("est") else ""))
            # 밸류체인_지도.is_sum_row 와 같은 기준 — 부문 칸이 통째로 '총매출액' · '순매출액'(머리 칸 밀림)인 표는 품목 줄이라 합계 줄이 아니다
            if VMAP.is_sum_row({"item": p.get("item"), "segment": p.get("seg"), "use": p.get("use")}):
                sumr.append("%s '%s' 부문 '%s' %s%%" % (tag, p["item"], p.get("seg") or "", p.get("pct")))
        tot = sum(p.get("raw") or 0 for p in out if not p.get("est"))
        if tot > 110:
            oversum.append("%s 비중 합 %.0f%% (%d줄)" % (tag, tot, len(out)))
    return {"n_co": n_co, "n_rows": n_rows, "over": over, "sumr": sumr, "emptied": emptied, "oversum": oversum}


# ---------------------------------------------------------------- (4) · (8) 지도 판
def board_ver(d):
    s = d.get("sig")
    try:
        return int(str(s).split("|")[0].split(".")[0])
    except (TypeError, ValueError):
        return None


def ev_kind(t):
    t = t or ""
    if t.startswith("같은 제품"):
        return "prod"
    if re.search(r"리포트\s*\d+건\s*\(180일\)", t):
        return "rep"
    if "에 매출" not in t and (t.startswith("네이버 테마") or re.search(r"테마$|같이 소속$", t)):
        return "theme"
    return "supply"


def chip_own(w, sw):
    lw = w.lower()
    if lw in sw or (w[-1:] in VMAP.JOSA and lw[:-1] in sw):
        return "exact"
    if any(len(s) >= 2 and (lw.startswith(s) or lw.endswith(s)) and len(lw) - len(s) <= 1 for s in sw):
        return "near"
    return None


def audit_boards():
    vers, per = Counter(), {"cur": defaultdict(list), "all": defaultdict(list)}
    groups = {"cur": Counter(), "all": Counter()}
    n = {"cur": Counter(), "all": Counter()}
    cur_codes = []
    for f in sorted(glob.glob(os.path.join(CACHE, "vcmap", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or not (d.get("head") or d.get("matrix")):
            continue                     # 판이 아닌 파일(bt.json — 후속주 백테스트 결과)
        v = board_ver(d)
        vers[str(v)] += 1
        code, name = d.get("code") or os.path.basename(f)[:6], d.get("name") or ""
        scopes = ("all", "cur") if v == VCMAP_V else ("all",)
        if v == VCMAP_V:
            cur_codes.append("%s %s (%s)" % (code, name, (d.get("built") or "")[:16]))
        sw = VMAP.self_words(name, LK.en_of.get(code) or ())
        words = ((d.get("head") or {}).get("story") or {}).get("words") or []
        for sc in scopes:
            n[sc]["boards"] += 1
            n[sc]["chips"] += len(words)
            for w in words:
                k = chip_own(w, sw)
                if k:
                    per[sc]["chip_" + k].append("%s %s: '%s' (자기 낱말 %s)" % (code, name, w, sorted(sw)[:6]))
            for g in (d.get("net") or {}).get("up") or []:
                for it in g.get("items") or []:
                    for sp in it.get("sup") or []:
                        n[sc]["up_sup"] += 1
                        if sp.get("code") == code:
                            per[sc]["up_self"].append("%s %s: '%s' (%s)" % (code, name, sp.get("name"), it.get("item")))
            for r in d.get("matrix") or []:
                grp = r.get("group") or "?"
                groups[sc][grp] += 1
                n[sc]["rows"] += 1
                if grp != "B":
                    continue
                kinds = [ev_kind(e.get("t") if isinstance(e, dict) else str(e)) for e in (r.get("ev") or {}).get("link") or []]
                lnk = (r.get("parts") or {}).get("link")
                tag = "%s %s → %s %s (link %s · %s)" % (code, name, r.get("code"), r.get("name"), lnk, "+".join(dict.fromkeys(kinds)) or "근거 없음")
                if lnk is not None and lnk < 5:
                    per[sc]["b_nodirect"].append(tag)
                if "supply" not in kinds and "prod" in kinds:
                    per[sc]["b_prod_only"].append(tag)
    return {"vers": vers, "cur_codes": cur_codes, "groups": groups, "n": n, "per": per}


# ---------------------------------------------------------------- 모아 재기
def rate(a, b):
    return round(100.0 * a / b, 2) if b else None


def ex(xs):
    return list(xs)[:NEX]


def main():
    t0 = time.time()
    rows, ctxs, n_files, n_years = collect()
    N = len(rows)
    cos = {r["code"] for r in rows}
    # (1)
    selfr = [(r, self_how(r)) for r in rows]
    selfr = [(r, h) for r, h in selfr if h]
    self_un = [(r, h) for r, h in selfr if not r["self_mark"]]
    # (2)
    co_grp = {cd: group_of(ctxs[cd].name) for cd in ctxs}
    grows = [r for r in rows if co_grp.get(r["code"]) and not self_how(r)]
    same = []
    for r in grows:
        g0 = co_grp[r["code"]]
        lk = r["lk"]
        if group_of(r["ent"]) == g0 or (lk and (co_grp.get(lk) == g0 or group_of(NAME_OF.get(lk, "")) == g0)):
            same.append(r)
    sg_un = [r for r in same if not (r["own"] or r["grp"])]
    sg_ids = {id(r) for r in same}
    srv_only = [r for r in rows if r["grp"] and id(r) not in sg_ids and not self_how(r)]

    def ent_group(r):
        return group_of(r["ent"]) or (group_of(NAME_OF.get(r["lk"], "")) if r["lk"] else None) or (co_grp.get(r["lk"]) if r["lk"] else None)
    srv_conflict = [r for r in srv_only if co_grp.get(r["code"]) and ent_group(r) and ent_group(r) != co_grp[r["code"]]]     # 목록상 다른 그룹 — 어간 규칙 오탐
    grp_by = Counter(r["grp"] for r in rows if r["grp"])
    own_cos = sum(1 for cd in cos if ctxs[cd].has_own)
    # (3)
    P = audit_products()
    # (5) · (6)
    gl = [(r, glued(r["ent"])) for r in rows]
    gl = [(r, w) for r, w in gl if w]
    jk = [(r, junk(r["ent"])) for r in rows]
    jk = [(r, w) for r, w in jk if w]
    # (7)
    n_srv = sum(1 for r in rows if r["srv"])
    n_map = sum(1 for r in rows if r["map"])
    n_any = sum(1 for r in rows if r["srv"] or r["map"])
    diff = [r for r in rows if r["srv"] and r["map"] and r["srv"] != r["map"]]
    n_ext = sum(1 for r in rows if r["lk"] and r["lk"] != r["code"])
    asc = [r for r in rows if not re.search(r"[가-힣]", r["ent"])]
    asc_l = sum(1 for r in asc if r["srv"] or r["map"])
    # (4) · (8)
    B = audit_boards()
    pc, pa = B["per"]["cur"], B["per"]["all"]
    nb_cur = B["n"]["cur"]["boards"]

    counts = {
        "files": n_files, "companies_with_years": n_years, "companies_with_rows": len(cos), "rows_current": N,
        "rows_by_field": dict(Counter(r["field"] for r in rows)),
        "self_rows": len(selfr), "self_companies": len({r["code"] for r, _ in selfr}), "self_by_how": dict(Counter(h for _, h in selfr)),
        "self_by_field": dict(Counter(r["field"] for r, _ in selfr)), "self_unmarked": len(self_un),
        "group_companies": sum(1 for cd in cos if co_grp.get(cd)), "group_company_rows": len(grows),
        "same_group_rows": len(same), "same_group_marked_own": sum(1 for r in same if r["own"]),
        "same_group_marked_grp": sum(1 for r in same if not r["own"] and r["grp"]), "same_group_unmarked": len(sg_un),
        "same_group_unmarked_companies": len({r["code"] for r in sg_un}),
        "same_group_unmarked_no_own_cache": sum(1 for r in sg_un if not ctxs[r["code"]].has_own),
        "same_group_rows_own_cache": sum(1 for r in same if ctxs[r["code"]].has_own),
        "same_group_unmarked_own_cache": sum(1 for r in sg_un if ctxs[r["code"]].has_own),
        "server_grp_rows": sum(grp_by.values()), "server_grp_by_rule": dict(grp_by), "server_grp_not_in_list": len(srv_only),
        "server_grp_other_group": len(srv_conflict), "own_cache_companies": own_cos,
        "product_companies": P["n_co"], "product_rows": P["n_rows"], "product_over100": len(P["over"]),
        "product_over100_companies": len({x[:6] for x in P["over"]}), "product_sum_rows": len(P["sumr"]),
        "product_emptied": len(P["emptied"]), "product_sum_over110": len(P["oversum"]),
        "glued_rows": len(gl), "glued_by_reason": dict(Counter(x for _, w in gl for x in w)),
        "junk_rows": len(jk), "junk_by_kind": dict(Counter(x for _, w in jk for x in w)), "junk_linked": sum(1 for r, _ in jk if r["lk"]),
        "linked_srv": n_srv, "linked_map": n_map, "linked_any": n_any, "linked_other_company": n_ext, "link_disagree": len(diff),
        "ascii_rows": len(asc), "ascii_linked": asc_l,
        "boards_total": B["n"]["all"]["boards"], "boards_current": nb_cur, "boards_by_version": dict(B["vers"]),
        "board_groups": dict(B["groups"]["cur"]), "board_groups_all": dict(B["groups"]["all"]),
        "story_chips": B["n"]["cur"]["chips"], "story_chip_own": len(pc["chip_exact"]), "story_chip_own_near": len(pc["chip_near"]),
        "story_chips_all": B["n"]["all"]["chips"], "story_chip_own_all": len(pa["chip_exact"]), "story_chip_own_near_all": len(pa["chip_near"]),
        "b_rows": B["groups"]["cur"].get("B", 0), "b_no_direct": len(pc["b_nodirect"]), "b_prod_only": len(pc["b_prod_only"]),
        "b_rows_all": B["groups"]["all"].get("B", 0), "b_no_direct_all": len(pa["b_nodirect"]), "b_prod_only_all": len(pa["b_prod_only"]),
        "up_self": len(pc["up_self"]), "up_self_all": len(pa["up_self"]),
    }
    rates = {
        "self": rate(len(selfr), N), "self_unmarked_of_self": rate(len(self_un), len(selfr)),
        "same_group_of_group_rows": rate(len(same), len(grows)), "same_group_unmarked": rate(len(sg_un), len(same)),
        "same_group_unmarked_own_cache": rate(sum(1 for r in sg_un if ctxs[r["code"]].has_own), sum(1 for r in same if ctxs[r["code"]].has_own)),
        "product_over100": rate(len(P["over"]), P["n_rows"]), "product_sum_rows": rate(len(P["sumr"]), P["n_rows"]),
        "story_chip_own": rate(len(pc["chip_exact"]), B["n"]["cur"]["chips"]), "story_chip_own_all": rate(len(pa["chip_exact"]), B["n"]["all"]["chips"]),
        "glued": rate(len(gl), N), "junk": rate(len(jk), N),
        "linked_srv": rate(n_srv, N), "linked_map": rate(n_map, N), "linked_any": rate(n_any, N), "ascii_linked": rate(asc_l, len(asc)),
        "b_no_direct": rate(len(pc["b_nodirect"]), B["groups"]["cur"].get("B", 0)), "b_prod_only": rate(len(pc["b_prod_only"]), B["groups"]["cur"].get("B", 0)),
        "boards_current": rate(nb_cur, B["n"]["all"]["boards"]),
    }
    examples = {
        "self_unmarked": ex(fmt(r, "how=" + h) for r, h in self_un),
        "self": ex(fmt(r, "how=" + h) for r, h in sorted(selfr, key=lambda x: -(x[0]["pct"] or 0))),
        "same_group_unmarked": ex(fmt(r, "그룹=" + co_grp[r["code"]]) for r in sorted(sg_un, key=lambda r: -(r["pct"] or 0))),
        "server_grp_not_in_list": ex(fmt(r, "rule=" + str(r["grp"])) for r in sorted(srv_only, key=lambda r: -(r["pct"] or 0))),
        "server_grp_other_group": ex(fmt(r, "rule=%s · %s≠%s" % (r["grp"], co_grp[r["code"]], ent_group(r))) for r in sorted(srv_conflict, key=lambda r: -(r["pct"] or 0))),
        "product_over100": ex(P["over"]), "product_sum_rows": ex(P["sumr"]), "product_emptied": ex(P["emptied"]), "product_sum_over110": ex(P["oversum"]),
        "story_chip_own": ex(pc["chip_exact"]), "story_chip_own_near": ex(pc["chip_near"]), "story_chip_own_all": ex(pa["chip_exact"]),
        "glued": ex(fmt(r, "+".join(w)) for r, w in sorted(gl, key=lambda x: -(x[0]["pct"] or 0))),
        "junk": ex(fmt(r, "+".join(w)) for r, w in sorted(jk, key=lambda x: -(x[0]["pct"] or 0))),
        "link_disagree": ex("%s 서버=%s(%s) 지도=%s(%s)" % (fmt(dict(r, lk=None)), r["srv"], NAME_OF.get(r["srv"]), r["map"], NAME_OF.get(r["map"])) for r in diff),
        "b_no_direct": ex(pc["b_nodirect"]), "b_prod_only": ex(pc["b_prod_only"]), "b_prod_only_all": ex(pa["b_prod_only"]),
        "up_self": ex(pc["up_self"]), "up_self_all": ex(pa["up_self"]), "boards_current": B["cur_codes"][:NEX],
    }
    rep = {"made": dt.datetime.now().isoformat(timespec="seconds"),
           "src": {"VCMAP_V": VCMAP_V, "VMAP_V": VMAP.V, "server_rules": RULE_SRC, "secs": round(time.time() - t0, 1),
                   "current": "회사 · 칸(cust/subcust/supp)마다 이름 적힌 줄이 있는 마지막 해", "boards": "sig 머리 VCMAP_V 가 서버.py 와 같은 판만(counts *_all = 옛 판 포함 참고)"},
           "counts": counts, "rates": rates, "examples": examples}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)

    # ---------------- 표
    def pr(label, val, pct=None, want=""):
        print("  %-40s %12s %9s   %s" % (label, val, ("%.2f%%" % pct) if pct is not None else "", want))
    print("밸류체인 점검 %s — VCMAP_V %d · VMAP.V %d · 서버 규칙 %s · %.0f초" % (rep["made"], VCMAP_V, VMAP.V, RULE_SRC, time.time() - t0))
    print("  지금 칸 이름 줄 %d (회사 %d / 캐시 %d · %s)" % (N, len(cos), n_files, dict(Counter(r["field"] for r in rows))))
    print("  %-40s %12s %9s   %s" % ("항목", "수", "비율", "기대 · 비고"))
    pr("(1) 자기 줄", "%d (%d사)" % (len(selfr), counts["self_companies"]), rates["self"], "how %s" % counts["self_by_how"])
    pr("    └ 서버 규칙이 '자기'로 못 잡음", len(self_un), rates["self_unmarked_of_self"], "0 이어야")
    pr("(2) 같은 그룹 줄(독립 목록)", "%d/%d" % (len(same), len(grows)), rates["same_group_of_group_rows"], "그룹 회사 %d사의 줄 중" % counts["group_companies"])
    pr("    └ 표시 안 됨(own · grp 둘 다 아님)", "%d (%d사)" % (len(sg_un), counts["same_group_unmarked_companies"]), rates["same_group_unmarked"],
       "표시 own %d · grp %d | 안 됨 중 소유 캐시 없는 회사 줄 %d" % (counts["same_group_marked_own"], counts["same_group_marked_grp"], counts["same_group_unmarked_no_own_cache"]))
    pr("    └ 소유 캐시 있는 회사만", "%d/%d" % (counts["same_group_unmarked_own_cache"], counts["same_group_rows_own_cache"]),
       rates["same_group_unmarked_own_cache"], "캐시 없는 회사는 서버가 화면 열 때 만든다 — 여기선 어간 규칙만(위 비율은 상한)")
    pr("    └ 서버만 같은 그룹(목록 밖)", len(srv_only), None, "그중 목록상 다른 그룹 %d · 규칙별 grp %s" % (len(srv_conflict), dict(grp_by)))
    pr("(3) 제품 비중 > 100% 줄", "%d/%d" % (len(P["over"]), P["n_rows"]), rates["product_over100"],
       "0 이어야 · %d사 (제품 표 %d사)" % (counts["product_over100_companies"], P["n_co"]))
    pr("    └ 합계 · 조정 · 손익 줄", len(P["sumr"]), rates["product_sum_rows"], "0 이어야")
    pr("    └ (참고) 다 지워진 표 · 합 > 110%", "%d · %d" % (len(P["emptied"]), len(P["oversum"])), None, "")
    pr("(4) 스토리 칩 = 자기 이름 낱말", "%d/%d" % (len(pc["chip_exact"]), B["n"]["cur"]["chips"]), rates["story_chip_own"],
       "0 이어야 · 비슷 %d | 옛 판 포함 %d/%d" % (len(pc["chip_near"]), len(pa["chip_exact"]), B["n"]["all"]["chips"]))
    pr("(5) 붙은 이름", len(gl), rates["glued"], str(counts["glued_by_reason"]))
    pr("(6) 잡이름", len(jk), rates["junk"], "이어진 잡이름 %d" % counts["junk_linked"])
    pr("(7) 상장사로 이어짐(둘 중 하나)", n_any, rates["linked_any"], "서버 %d(%.1f%%) · 지도 %d(%.1f%%) · 어긋남 %d" % (
        n_srv, rates["linked_srv"] or 0, n_map, rates["linked_map"] or 0, len(diff)))
    pr("    └ 영문만 이름 이어짐", "%d/%d" % (asc_l, len(asc)), rates["ascii_linked"], "")
    pr("(8) 지도 판 지금 판 / 전체", "%d/%d" % (nb_cur, B["n"]["all"]["boards"]), rates["boards_current"], "판별 %s" % dict(sorted(B["vers"].items())))
    pr("    └ 군 B · C · D · Fake", " · ".join(str(B["groups"]["cur"].get(g, 0)) for g in ("B", "C", "D", "Fake")), None,
       "옛 판 포함 %s" % " · ".join(str(B["groups"]["all"].get(g, 0)) for g in ("B", "C", "D", "Fake")))
    pr("    └ B 인데 공급망 직접 없음(link<5)", "%d/%d" % (len(pc["b_nodirect"]), B["groups"]["cur"].get("B", 0)), rates["b_no_direct"],
       "0 이어야 | 옛 판 포함 %d" % len(pa["b_nodirect"]))
    pr("    └ B 인데 같은 제품뿐", len(pc["b_prod_only"]), rates["b_prod_only"], "0 이어야 | 옛 판 포함 %d" % len(pa["b_prod_only"]))
    pr("    └ (참고) 상류 매입처 = 주도주 자신", len(pc["up_self"]), None, "옛 판 포함 %d" % len(pa["up_self"]))
    for k in ("self_unmarked", "same_group_unmarked", "server_grp_not_in_list", "product_over100", "product_sum_rows", "story_chip_own", "b_prod_only", "glued", "junk"):
        if examples[k]:
            print("  예) %s" % k)
            for x in examples[k][:3]:
                print("      " + x)
    print("결과 → %s" % os.path.relpath(OUT, BASE))


if __name__ == "__main__":
    main()
