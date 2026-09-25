# -*- coding: utf-8 -*-
"""
기업추적 뷰어 — 수집한 정기보고서를 브라우저에서 읽는 로컬 서버.

    python 서버.py              # http://127.0.0.1:8765 열림
    python 서버.py --port 9000
    python 서버.py --no-browser

수집 폴더(기업추적_수집)를 그대로 읽는다. 별도 DB 없음.
색인은 .cache/색인.json 에 저장하고, 수집 폴더가 바뀌면 자동으로 다시 만든다.
"""
import os
import re
import io
import csv
import sys
import json
import time
import html
import datetime as dt
import difflib
import threading
import webbrowser
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "기업추적_수집")
CACHE_DIR = os.path.join(BASE, ".cache")
INDEX_PATH = os.path.join(CACHE_DIR, "색인.json")
WEB_DIR = os.path.join(BASE, "웹")

INDEX = {"companies": [], "built": 0}
INDEX_LOCK = threading.Lock()

sys.path.insert(0, BASE)
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("재무", os.path.join(BASE, "재무.py"))
    FIN = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(FIN)
except Exception as _e:        # 재무 모듈이 없어도 나머지는 돌아가야 한다
    FIN = None
    print("재무 모듈 로드 실패:", _e)

_CORP = {}


def corp_code_of(stock_code):
    """종목코드 -> DART 고유번호. 수집기가 받아둔 CORPCODE.xml 을 재사용."""
    global _CORP
    if not _CORP:
        path = os.path.join(CACHE_DIR, "CORPCODE.xml")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8", errors="replace")
        for m in re.finditer(r"<list>(.*?)</list>", text, re.S):
            blob = m.group(1)
            s = re.search(r"<stock_code>(.*?)</stock_code>", blob, re.S)
            c = re.search(r"<corp_code>(.*?)</corp_code>", blob, re.S)
            if s and c and s.group(1).strip():
                _CORP[s.group(1).strip()] = c.group(1).strip()
    return _CORP.get(stock_code)


# ---------------------------------------------------------------- 섹션 이름
# 로마숫자 번호는 해가 바뀌면 밀린다(2011년 'V. 경영진단' -> 2026년 'IV. 경영진단').
# 번호를 떼고 이름만으로 같은 섹션을 잇는다.
ALIASES = [
    (r"대표이사 등의 확인", "대표이사 등의 확인"),
    (r"회사의 개요", "회사의 개요"),
    (r"사업의 내용", "사업의 내용"),
    (r"재무에 관한 사항", "재무에 관한 사항"),
    (r"경영진단 및 분석의견", "이사의 경영진단 및 분석의견"),
    (r"감사의견", "감사인의 감사의견 등"),
    (r"이사회 등 회사의 기관", "이사회 등 회사의 기관"),
    (r"주주에 관한 사항", "주주에 관한 사항"),
    (r"임원 및 직원", "임원 및 직원 등에 관한 사항"),
    (r"계열회사", "계열회사 등에 관한 사항"),
    (r"대주주 등과의 거래|이해관계자와의 거래", "대주주 등과의 거래내용"),
    (r"투자자 보호", "그 밖에 투자자 보호를 위하여 필요한 사항"),
    (r"재 *무 *제 *표", "재무제표 등"),
    (r"부속명세서", "부속명세서"),
    (r"상세표", "상세표"),
    (r"전문가의 확인", "전문가의 확인"),
    (r"외부감사인의 감사보고서", "감사인의 감사의견 등"),
    (r"외부감사 실시내용", "외부감사 실시내용"),
]

# 이 순서대로 화면에 세운다. 목록에 없는 섹션은 뒤에 붙는다.
SECTION_ORDER = [
    "사업의 내용", "이사의 경영진단 및 분석의견", "재무에 관한 사항",
    "회사의 개요", "그 밖에 투자자 보호를 위하여 필요한 사항",
    "임원 및 직원 등에 관한 사항", "주주에 관한 사항",
    "이사회 등 회사의 기관", "계열회사 등에 관한 사항",
    "대주주 등과의 거래내용", "감사인의 감사의견 등", "외부감사 실시내용",
    "재무제표 등", "부속명세서", "상세표",
    "대표이사 등의 확인", "전문가의 확인",
]


# 섹션별 투자 중요도. 변화 점수에 곱한다.
# 부속명세서·상세표는 분기마다 숫자가 통째로 바뀌지만 읽을 가치가 없다.
SECTION_WEIGHT = {
    "사업의 내용": 1.00,
    "이사의 경영진단 및 분석의견": 0.95,
    "그 밖에 투자자 보호를 위하여 필요한 사항": 0.85,
    "주주에 관한 사항": 0.70,
    "재무에 관한 사항": 0.70,
    "계열회사 등에 관한 사항": 0.60,
    "임원 및 직원 등에 관한 사항": 0.55,
    "대주주 등과의 거래내용": 0.50,
    "감사인의 감사의견 등": 0.50,
    "회사의 개요": 0.40,
    "이사회 등 회사의 기관": 0.30,
    "재무제표 등": 0.25,
    "외부감사 실시내용": 0.20,
    "부속명세서": 0.05,
    "상세표": 0.05,
    "대표이사 등의 확인": 0.0,
    "전문가의 확인": 0.0,
}
DEFAULT_WEIGHT = 0.35

# 바뀐 문단이 무엇을 말하는지. 헷지펀드가 실제로 보는 범주로만 끊었다.
TAGS = [
    ("수주·계약", r"수주|공급 ?계약|계약 ?체결|납품|수주잔고|수주총액"),
    ("설비·증설", r"증설|설비 ?투자|생산 ?능력|가동률|신규 ?공장|양산|CAPEX|생산라인"),
    ("신사업·신제품", r"신규 ?사업|신 ?제품|상용화|출시|개발 ?완료|사업 ?진출|신규 ?시장"),
    ("고객·전방", r"매출 ?비중|주요 ?고객|주요 ?매출처|주요 ?거래처|단일 ?고객|전방 ?산업"),
    ("리스크·소송", r"소송|분쟁|제재|과징금|손해배상|압수|리콜|조사를 받|계속기업|영업정지"),
    ("지배구조·M&A", r"최대주주|경영권|지분 ?(매각|취득|처분)|인수|합병|분할|종속회사 (편입|제외)"),
    ("자금조달", r"유상증자|무상증자|전환사채|신주인수권부사채|교환사채|차입금|사채 ?발행|담보 ?제공"),
    ("인력", r"직원 ?수|임원의 ?(선임|사임|해임)|평균 ?근속|1인 ?평균 ?급여|인력 ?(충원|감축)"),
    ("연구개발", r"연구 ?개발|R&D|특허|임상 ?\d|품목 ?허가|승인 ?(획득|신청)"),
    ("실적·수익성", r"영업 ?(이익|손실)|매출 ?(액|증가|감소)|영업 ?이익률|원가 ?(상승|절감)|환율"),
]
TAGS = [(n, re.compile(p)) for n, p in TAGS]

NOISE_RE = re.compile(r"^[\d\s.,%()\-~\t원주개년월일第제기()]+$")
HANGUL_RE = re.compile(r"[가-힣]")


def is_noise(par):
    """숫자만 있는 표 행은 분기마다 통째로 바뀐다. 읽을 게 없으니 뺀다."""
    p = par.strip()
    if len(p) < 18:
        return True
    if NOISE_RE.match(p):
        return True
    hangul = len(HANGUL_RE.findall(p))
    if hangul < 10:
        return True
    # 탭이 많고 한글 비중이 낮으면 표의 숫자 행
    if p.count("\t") >= 3 and hangul / max(len(p), 1) < 0.25:
        return True
    return False


def classify(par):
    return [name for name, rx in TAGS if rx.search(par)]


def norm_section(title):
    t = re.sub(r"^\d+_", "", title.strip())
    t = t.replace("【", "").replace("】", "")
    t = re.sub(r"\.txt$", "", t)
    t = re.sub(r"^\(첨부\)\s*", "", t)
    t = re.sub(r"^[IVXLCivxlc]+\s*\.\s*", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    for pat, canon in ALIASES:
        if re.search(pat, t):
            return canon
    return t


def section_rank(name):
    try:
        return SECTION_ORDER.index(name)
    except ValueError:
        return len(SECTION_ORDER) + 1


# ---------------------------------------------------------------- 색인
DIR_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2})_(?P<label>[^_\[]+)(?P<tag>\[[^\]]*\])?_(?P<rcept>\d{14})$")


def company_sig(cpath):
    """회사 폴더 하나의 지문. 보고서 폴더 수와 이름만 본다."""
    try:
        names = sorted(os.listdir(cpath))
    except OSError:
        return ""
    return "%d:%s" % (len(names), names[-1] if names else "")


def scan(prev=None):
    """수집 폴더를 훑어 색인을 만든다.

    prev 가 있으면 지문이 그대로인 회사는 통째로 재사용한다.
    구글 드라이브 위에 25,000개가 넘는 보고서 폴더가 있고 수집기가 동시에
    쓰고 있어서, 매번 전부 훑으면 색인에만 몇 분씩 걸린다.
    """
    old = {}
    if prev:
        for c in prev.get("companies", []):
            if c.get("sig"):
                old[c["dir"]] = c

    companies = []
    if not os.path.isdir(OUT_DIR):
        return {"companies": [], "built": time.time()}

    for cdir in sorted(os.listdir(OUT_DIR)):
        cpath = os.path.join(OUT_DIR, cdir)
        if not os.path.isdir(cpath):
            continue
        m = re.match(r"^(?P<name>.+)_(?P<code>[0-9][0-9A-Z]{5})$", cdir)
        if not m:
            continue
        name, code = m.group("name"), m.group("code")

        sig = company_sig(cpath)
        hit = old.get(cdir)
        if hit and hit.get("sig") == sig:
            companies.append(hit)          # 지문 같으면 그대로 재사용
            continue

        reports = []
        for rdir in sorted(os.listdir(cpath)):
            rpath = os.path.join(cpath, rdir)
            if not os.path.isdir(rpath):
                continue
            rm = DIR_RE.match(rdir)
            if not rm:
                continue
            if not os.path.exists(os.path.join(rpath, "_완료.txt")):
                continue          # 받다 만 보고서는 숨긴다

            sections = []
            for fn in sorted(os.listdir(rpath)):
                if not fn.endswith(".txt") or fn == "_완료.txt":
                    continue
                title = re.sub(r"^\d+_", "", fn[:-4])
                sections.append({
                    "file": fn,
                    "title": title,
                    "norm": norm_section(fn),
                    "bytes": os.path.getsize(os.path.join(rpath, fn)),
                })
            if not sections:
                continue

            reports.append({
                "stamp": rm.group("stamp"),
                "label": rm.group("label"),
                "tag": rm.group("tag") or "",
                "rcept": rm.group("rcept"),
                "dir": rdir,
                "sections": sections,
                "bytes": sum(s["bytes"] for s in sections),
            })

        if not reports:
            continue
        reports.sort(key=lambda r: (r["stamp"], r["rcept"]))
        companies.append({
            "code": code, "name": name, "dir": cdir, "sig": sig,
            "reports": reports,
            "from": reports[0]["stamp"], "to": reports[-1]["stamp"],
            "count": len(reports),
            "bytes": sum(r["bytes"] for r in reports),
        })

    companies.sort(key=lambda c: c["name"])
    return {"companies": companies, "built": time.time()}


def out_dir_signature():
    """수집 폴더가 바뀌었는지 싸게 확인 — 회사 폴더별 mtime 합."""
    if not os.path.isdir(OUT_DIR):
        return "none"
    parts = []
    for cdir in sorted(os.listdir(OUT_DIR)):
        p = os.path.join(OUT_DIR, cdir)
        if os.path.isdir(p):
            parts.append("%s:%d:%d" % (cdir, os.path.getmtime(p),
                                       len(os.listdir(p))))
    return "|".join(parts)


INDEX_STATE = {"ready": False, "building": False, "error": None, "at": 0}


def build_index(force=False):
    global INDEX
    with INDEX_LOCK:
        INDEX_STATE["building"] = True
        sig = out_dir_signature()
        cached = None
        if os.path.exists(INDEX_PATH):
            try:
                with open(INDEX_PATH, "r", encoding="utf-8") as fh:
                    cached = json.load(fh)
            except Exception:
                cached = None
        if not force and cached and cached.get("sig") == sig:
            INDEX = cached
            INDEX_STATE.update(ready=True, building=False, at=time.time())
            return INDEX
        # 지문이 달라도 이전 색인을 넘겨준다. 바뀐 회사만 다시 읽으면 된다.
        idx = scan(cached)
        idx["sig"] = sig
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(INDEX_PATH, "w", encoding="utf-8") as fh:
            json.dump(idx, fh, ensure_ascii=False)
        INDEX = idx
        INDEX_STATE.update(ready=True, building=False, at=time.time())
        return INDEX


def company_by_code(code):
    for c in INDEX["companies"]:
        if c["code"] == code:
            return c
    return None


def report_of(c, rcept):
    for r in c["reports"]:
        if r["rcept"] == rcept:
            return r
    return None


def read_section(c, r, fn):
    path = os.path.join(OUT_DIR, c["dir"], r["dir"], fn)
    if not os.path.abspath(path).startswith(os.path.abspath(OUT_DIR)):
        return ""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    # 앞 두 줄은 출처 헤더. 본문만 돌려준다.
    lines = text.split("\n")
    while lines and lines[0].startswith("#"):
        lines.pop(0)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- 기능
def section_history(c, norm, labels=None):
    out = []
    for r in c["reports"]:
        if labels and r["label"] not in labels:
            continue
        for s in r["sections"]:
            if s["norm"] == norm:
                out.append({"stamp": r["stamp"], "label": r["label"],
                            "tag": r["tag"], "rcept": r["rcept"],
                            "file": s["file"], "title": s["title"],
                            "bytes": s["bytes"]})
                break
    return out


def blocks(text):
    """문단 단위로 쪼갠다. 표는 탭이 섞인 한 줄로 들어온다."""
    return [b.strip() for b in text.split("\n") if b.strip()]


def diff_sections(a_text, b_text, context=1):
    A, B = blocks(a_text), blocks(b_text)
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    out = []
    ops = sm.get_opcodes()
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            keep = A[i1:i2]
            if len(keep) <= context * 2:
                for t in keep:
                    out.append({"t": "same", "x": t})
            else:
                head = keep[:context] if n > 0 else []
                tail = keep[-context:] if n < len(ops) - 1 else []
                for t in head:
                    out.append({"t": "same", "x": t})
                out.append({"t": "gap", "x": "··· 같은 내용 %d문단 ···"
                            % (len(keep) - len(head) - len(tail))})
                for t in tail:
                    out.append({"t": "same", "x": t})
        elif tag == "delete":
            for t in A[i1:i2]:
                out.append({"t": "del", "x": t})
        elif tag == "insert":
            for t in B[j1:j2]:
                out.append({"t": "add", "x": t})
        else:
            for t in A[i1:i2]:
                out.append({"t": "del", "x": t})
            for t in B[j1:j2]:
                out.append({"t": "add", "x": t})

    added = sum(1 for d in out if d["t"] == "add")
    removed = sum(1 for d in out if d["t"] == "del")
    ratio = sm.ratio()
    return {"diff": out, "added": added, "removed": removed,
            "similarity": round(ratio * 100, 1)}


def search_company(c, query, labels=None, section=None, limit=400):
    """회사 한 곳 안에서 전문 검색. 대소문자 무시."""
    q = query.strip()
    if not q:
        return []
    rx = re.compile(re.escape(q), re.I)
    hits = []
    for r in c["reports"]:
        if labels and r["label"] not in labels:
            continue
        for s in r["sections"]:
            if section and s["norm"] != section:
                continue
            text = read_section(c, r, s["file"])
            if not text:
                continue
            n = 0
            for m in rx.finditer(text):
                n += 1
                if len(hits) < limit:
                    a = max(0, m.start() - 90)
                    b = min(len(text), m.end() + 90)
                    hits.append({
                        "stamp": r["stamp"], "label": r["label"],
                        "tag": r["tag"], "rcept": r["rcept"],
                        "file": s["file"], "section": s["norm"],
                        "before": text[a:m.start()],
                        "match": text[m.start():m.end()],
                        "after": text[m.end():b],
                    })
            if n:
                pass
    return hits


def trend_company(c, terms, labels=None, section=None):
    """보고서별 용어 등장 횟수. 성장 궤적을 눈으로 보는 용도."""
    series = {t: [] for t in terms}
    points = []
    for r in c["reports"]:
        if labels and r["label"] not in labels:
            continue
        texts = []
        for s in r["sections"]:
            if section and s["norm"] != section:
                continue
            texts.append(read_section(c, r, s["file"]))
        blob = "\n".join(texts)
        total = max(len(blob), 1)
        points.append({"stamp": r["stamp"], "label": r["label"],
                       "rcept": r["rcept"], "chars": len(blob)})
        for t in terms:
            cnt = len(re.findall(re.escape(t), blob, re.I))
            series[t].append({"n": cnt,
                              "per10k": round(cnt / total * 10000, 2)})
    return {"points": points, "series": series}


# ---------------------------------------------------------------- 변화 브리핑
NUM_RE = re.compile(r"[-△▲]?\d[\d,]*(?:\.\d+)?")


def skel(par):
    """숫자를 지운 뼈대. 같은 문장에서 수치만 바뀐 경우를 잡아내는 열쇠."""
    return NUM_RE.sub("#", re.sub(r"\s+", "", par))


def dedupe(pars):
    seen, out = set(), []
    for p in pars:
        k = re.sub(r"\s+", "", p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def number_diff(before, after):
    """같은 문장 안에서 실제로 바뀐 숫자쌍만 뽑는다."""
    a, b = NUM_RE.findall(before), NUM_RE.findall(after)
    out = []
    for x, y in zip(a, b):
        if x == y:
            continue
        try:
            fx = float(x.replace(",", "").replace("△", "-").replace("▲", ""))
            fy = float(y.replace(",", "").replace("△", "-").replace("▲", ""))
            pct = round((fy - fx) / abs(fx) * 100, 1) if fx else None
        except ValueError:
            pct = None
        out.append({"from": x, "to": y, "pct": pct})
        if len(out) >= 6:
            break
    return out


def baseline_for(c, rep):
    """이 보고서를 무엇과 비교할지 고른다.

    [정정] 건은 같은 기간의 원본과 비교한다 — 회사가 무엇을 고쳤는지가 신호다.
    나머지는 같은 종류의 직전 보고서와 비교한다. 분기를 사업보고서와 맞대면
    서식이 달라 전부 바뀐 것처럼 나오기 때문이다.
    """
    if rep["tag"]:
        same = [r for r in c["reports"]
                if r["stamp"] == rep["stamp"] and not r["tag"]
                and r["rcept"] < rep["rcept"]]
        if same:
            return same[-1], "정정 전 원본"
        prior = [r for r in c["reports"]
                 if r["rcept"] < rep["rcept"] and r["tag"]
                 and r["label"] == rep["label"]]
        if prior:
            return prior[-1], "직전 " + rep["label"] + "[정정]"
        return None, ""

    same = [r for r in c["reports"]
            if r["label"] == rep["label"] and not r["tag"]
            and r["rcept"] < rep["rcept"]]
    if same:
        return same[-1], "직전 " + rep["label"]
    any_prior = [r for r in c["reports"]
                 if not r["tag"] and r["rcept"] < rep["rcept"]]
    if any_prior:
        return any_prior[-1], "직전 보고서(" + any_prior[-1]["label"] + ")"
    return None, ""


def brief_path(code, rcept):
    return os.path.join(CACHE_DIR, "brief", code, rcept + ".json")


def build_brief(c, rep, force=False):
    path = brief_path(c["code"], rep["rcept"])
    if not force and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass

    base, kind = baseline_for(c, rep)
    out = {
        "code": c["code"], "name": c["name"],
        "report": {k: rep[k] for k in ("stamp", "label", "tag", "rcept")},
        "base": ({k: base[k] for k in ("stamp", "label", "tag", "rcept")}
                 if base else None),
        "kind": kind, "sections": [], "score": 0.0, "tags": {},
        "first": base is None,
    }

    if base is not None:
        by_norm_b = {}
        for s in base["sections"]:
            by_norm_b.setdefault(s["norm"], s)

        for s in rep["sections"]:
            w = SECTION_WEIGHT.get(s["norm"], DEFAULT_WEIGHT)
            if w <= 0:
                continue
            bs = by_norm_b.get(s["norm"])
            if not bs:
                continue
            a_text = read_section(c, base, bs["file"])
            b_text = read_section(c, rep, s["file"])
            if not a_text and not b_text:
                continue
            A, B = blocks(a_text), blocks(b_text)
            sm = difflib.SequenceMatcher(None, A, B, autojunk=False)

            added, removed = [], []
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag in ("insert", "replace"):
                    added.extend(B[j1:j2])
                if tag in ("delete", "replace"):
                    removed.extend(A[i1:i2])

            add_keep = dedupe([p for p in added if not is_noise(p)])
            rem_keep = dedupe([p for p in removed if not is_noise(p)])

            # 같은 문장인데 숫자만 바뀐 것은 '새로 쓴 말'이 아니다.
            # 회계 상용구가 상위를 먹지 않게 따로 뺀다 — 대신 숫자 변화로 보여준다.
            rem_by_skel = {}
            for p in rem_keep:
                rem_by_skel.setdefault(skel(p), p)
            fresh, numeric = [], []
            for p in add_keep:
                twin = rem_by_skel.get(skel(p))
                if twin is None:
                    fresh.append(p)
                elif twin != p:
                    numeric.append((twin, p))
            rem_fresh = [p for p in rem_keep if skel(p) not in
                         {skel(x) for x in add_keep}]

            add_chars = sum(len(p) for p in fresh)
            rem_chars = sum(len(p) for p in rem_fresh)
            if not fresh and not rem_fresh and not numeric:
                continue

            tag_count = {}
            for p in fresh:
                for t in classify(p):
                    tag_count[t] = tag_count.get(t, 0) + 1

            def rank(p):
                return (len(classify(p)) * 500 + min(len(p), 800))

            hi = sorted(fresh, key=rank, reverse=True)[:8]
            lo = sorted(rem_fresh, key=rank, reverse=True)[:5]
            num_hi = sorted(numeric, key=lambda ab: rank(ab[1]),
                            reverse=True)[:6]
            score = w * ((add_chars + rem_chars * 0.6) ** 0.5)

            out["sections"].append({
                "section": s["norm"], "title": s["title"], "file": s["file"],
                "base_file": bs["file"], "weight": w,
                "similarity": round(sm.ratio() * 100, 1),
                "added": len(fresh), "removed": len(rem_fresh),
                "numeric": len(numeric),
                "added_chars": add_chars, "removed_chars": rem_chars,
                "score": round(score, 1),
                "tags": tag_count,
                "highlights": [{"text": p[:1200], "tags": classify(p)} for p in hi],
                "dropped": [{"text": p[:600], "tags": classify(p)} for p in lo],
                "numbers": [{"before": a[:500], "after": b[:500],
                             "diff": number_diff(a, b), "tags": classify(b)}
                            for a, b in num_hi],
            })
            for t, n in tag_count.items():
                out["tags"][t] = out["tags"].get(t, 0) + n

        out["sections"].sort(key=lambda x: -x["score"])
        out["score"] = round(sum(x["score"] for x in out["sections"]), 1)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


try:
    _uspec = _ilu.spec_from_file_location("업종", os.path.join(BASE, "업종.py"))
    SECT = _ilu.module_from_spec(_uspec)
    _uspec.loader.exec_module(SECT)
except Exception as _e:
    SECT = None
    print("업종 모듈 로드 실패:", _e)

SECT_STATE = {"building": False, "done": 0, "total": 0, "map": None}

try:
    _jspec = _ilu.spec_from_file_location("수주", os.path.join(BASE, "수주.py"))
    BACK = _ilu.module_from_spec(_jspec)
    _jspec.loader.exec_module(BACK)
except Exception as _e:
    BACK = None
    print("수주 모듈 로드 실패:", _e)

BACKLOG = {"running": False, "done": 0, "total": 0, "rows": [], "at": 0,
           "skipped": 0}
BACKLOG_LOCK = threading.Lock()
# '수주상황'은 넣으면 안 된다. 사업보고서 표준 목차가 '4. 매출 및 수주상황'이라
# 거의 모든 회사에 있다. 실제 잔고 칸이 있는 회사만 골라야 건너뛰기가 먹는다.
HAS_BACKLOG_RE = re.compile(r"수\s*주\s*잔\s*[고액량]|계약\s*잔액")


def _latest_biz_text(c):
    for r in reversed(c["reports"]):
        if r["tag"]:
            continue
        sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
        if sec:
            return read_section(c, r, sec["file"])
    return ""


def _run_backlog():
    """전 종목 수주잔고 시계열. 보고서 본문을 읽으니 처음 한 번은 오래 걸린다.
    최신 보고서에 수주 표가 없는 회사(소비재·바이오 대부분)는 통째로 건너뛴다."""
    try:
        cos = list(INDEX["companies"])
        smap = sector_map() or {}
        stocks = smap.get("stocks", {})
        with BACKLOG_LOCK:
            BACKLOG.update(done=0, total=len(cos), skipped=0)
        rows, skipped = [], 0
        for i, c in enumerate(cos, 1):
            try:
                # 건너뛰기 조건을 두지 않는다. '수주잔고' 단어로 거르면 표 머리글이
                # 다른 말인 회사 22곳이 통째로 빠졌다. 보고서별 결과가 캐시돼
                # 있어서 두 번째 실행부터는 새 보고서만 읽는다.
                pts = BACK.company_series(c, read_section, max_reports=12)
                if not pts:
                    skipped += 1
                    continue
                tr = BACK.trend(pts)
                if not tr:
                    continue
                info = stocks.get(c["code"].upper(), {})
                verified = sum(1 for p in pts[-8:] if "검산 일치" in (p.get("source") or ""))
                # 회사가 문장으로 직접 밝힌 값('수주잔고는 약 1,023억원')은 표 검산과
                # 별개로 믿을 만하다. 따로 센다.
                explicit = sum(1 for p in pts[-8:] if p.get("method") == "문장")
                rows.append({
                    "code": c["code"], "name": c["name"],
                    "sector": info.get("sector", "분류없음"),
                    "industry": info.get("industry", "분류없음"),
                    "points": pts[-12:], "trend": tr,
                    "verified": verified, "explicit": explicit,
                    "n_pts": len(pts[-8:]),
                })
            except Exception as e:
                print("수주 %s 실패: %s" % (c["code"], e), flush=True)
            finally:
                with BACKLOG_LOCK:
                    BACKLOG["done"] = i
                    BACKLOG["skipped"] = skipped
                    if i % 20 == 0:
                        BACKLOG["rows"] = list(rows)
        with BACKLOG_LOCK:
            BACKLOG["rows"] = rows
            BACKLOG["at"] = time.time()
    finally:
        with BACKLOG_LOCK:
            BACKLOG["running"] = False


def backlog_view(force=False, steady_only=True):
    with BACKLOG_LOCK:
        stale = force or (not BACKLOG["rows"] and not BACKLOG["running"]) or \
            (BACKLOG["at"] and time.time() - BACKLOG["at"] > 6 * 3600)
        if stale and not BACKLOG["running"] and BACK is not None:
            BACKLOG["running"] = True
            threading.Thread(target=_run_backlog, daemon=True).start()
        rows = list(BACKLOG["rows"])
        st = {k: BACKLOG[k] for k in ("running", "done", "total", "skipped", "at")}
    # 연매출 대비 배수 — 잔고가 몇 년치 매출을 이미 확보했나
    for r in rows:
        rev = None
        corp = corp_code_of(r["code"])
        if corp and FIN is not None:
            try:
                ann = FIN.annual_actuals(corp, [dt.date.today().year - 1])
                rev = (ann.get(dt.date.today().year - 1) or {}).get("매출액")
            except Exception:
                rev = None
        r["revenue"] = rev
        r["cover"] = (r["trend"]["last"] / rev) if rev else None
    # 지주사와 자회사가 같은 수주잔고를 적는다. 지주사 사업보고서가 자회사
    # 잔고를 연결 기준으로 그대로 옮기기 때문이다 (HD현대 = HD한국조선해양
    # 98.81조, LG = LG씨엔에스, HDC = IPARK현대산업개발). 추출은 맞지만
    # 목록에서는 같은 사업이 두 번 세어지니 서로를 표시한다.
    # 원 단위까지 같아야 같은 숫자로 본다. 0.1% 오차를 허용했더니
    # 파크시스템스(문장 '약 1,023억원')와 유니슨(표 102,291백만원)이
    # 우연히 같다고 잡혔다. 지주사·자회사는 같은 원장 숫자를 옮기므로 정확히 같다.
    for r in rows:
        v = r["trend"]["last"]
        twins = [o["name"] for o in rows if o is not r
                 and abs(o["trend"]["last"] - v) <= 1.0]
        r["same_as"] = twins
    shown = [r for r in rows if r["trend"]["steady"]] if steady_only else rows
    shown.sort(key=lambda r: ((r["trend"]["yoy"] or -999), r["trend"]["up_ratio"]),
               reverse=True)
    st.update(rows=shown, total_found=len(rows),
              steady=sum(1 for r in rows if r["trend"]["steady"]))
    return st


def sector_map():
    """분류표. 없거나 하루 지났으면 뒤에서 새로 만들고, 있는 건 일단 쓴다."""
    if SECT is None:
        return None
    if SECT_STATE["map"] is None:
        SECT_STATE["map"] = SECT.load()
    m = SECT_STATE["map"]
    if (m is None or m.get("stale")) and not SECT_STATE["building"]:
        SECT_STATE["building"] = True

        def _run():
            try:
                def prog(d, t):
                    SECT_STATE["done"], SECT_STATE["total"] = d, t
                SECT_STATE["map"] = SECT.build(prog)
            except Exception as e:
                print("업종 분류 빌드 실패:", e, flush=True)
            finally:
                SECT_STATE["building"] = False
        threading.Thread(target=_run, daemon=True).start()
    return m


try:
    _gspec = _ilu.spec_from_file_location("호재", os.path.join(BASE, "호재.py"))
    GOOD = _ilu.module_from_spec(_gspec)
    _gspec.loader.exec_module(GOOD)
except Exception as _e:
    GOOD = None
    print("호재 모듈 로드 실패:", _e)

try:
    _dspec = _ilu.spec_from_file_location("드러켄밀러",
                                          os.path.join(BASE, "드러켄밀러.py"))
    DRK = _ilu.module_from_spec(_dspec)
    _dspec.loader.exec_module(DRK)
except Exception as _e:
    DRK = None
    print("드러켄밀러 모듈 로드 실패:", _e)

try:
    _yspec = _ilu.spec_from_file_location("시너지", os.path.join(BASE, "시너지.py"))
    SYN = _ilu.module_from_spec(_yspec)
    _yspec.loader.exec_module(SYN)
except Exception as _e:
    SYN = None
    print("시너지 모듈 로드 실패:", _e)


def rcept_dt_of(rep):
    return rep["rcept"][:8]


Q_OF_MONTH = {"03": 1, "06": 2, "09": 3, "12": 4}


def druck(code, force=False):
    """분기 단독 실적 시계열 + 본문에서 긁은 가동률·수주잔고."""
    c = company_by_code(code)
    if not c:
        return None
    if DRK is None:
        return {"error": "드러켄밀러 모듈을 불러오지 못했습니다."}
    corp = corp_code_of(code)
    if not corp:
        return {"error": "DART 고유번호를 찾지 못했습니다."}

    cache = os.path.join(CACHE_DIR, "druck", code + ".json")
    sig = c["reports"][-1]["rcept"] if c["reports"] else ""
    if not force and os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                old = json.load(fh)
            if old.get("sig") == sig:
                return old
        except Exception:
            pass

    years, dates = set(), {}
    for r in c["reports"]:
        y, mth = r["stamp"].split("-")
        q = Q_OF_MONTH.get(mth)
        if not q:
            continue
        years.add(int(y))
        key = (int(y), q)
        # 같은 분기에 정정본이 있으면 원본 접수일을 쓴다
        if key not in dates or not r["tag"]:
            dates[key] = rcept_dt_of(r)

    pts = DRK.series(corp, code, sorted(years))
    DRK.attach_prices(pts, code, dates)

    # 본문 지표 — 사업의 내용에서만 긁는다
    text_rows = []
    for r in c["reports"]:
        if r["tag"]:
            continue
        sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
        if not sec:
            continue
        found = DRK.scan_text_metrics(read_section(c, r, sec["file"]))
        if found:
            text_rows.append({"stamp": r["stamp"], "label": r["label"],
                              "rcept": r["rcept"], "found": found})

    out = {"sig": sig, "code": code, "name": c["name"],
           "points": pts, "text": text_rows}
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


def catalyst_view(days, level="sector", force=False, minw=2):
    """호재 공시 + 업종별 집계.

    그룹 점수는 주가가 아니라 공시에서 나온다. 샘플 화면의 점수는 시세
    모멘텀이지만 이 도구에는 시세 흐름이 없고, 있는 척하지 않는다. 대신
    '그 업종에 호재 공시가 얼마나 몰리고 있나'를 잰다.
      강도합   : 기간 내 호재 공시 강도(●)의 합
      밀도     : 강도합 / sqrt(업종 종목 수)  — 큰 업종이 숫자만으로 이기지 않게
      점수     : 밀도의 업종 간 백분위 (0~100)
      변화     : 같은 길이의 직전 기간 대비 강도합 증감
    """
    # 변화율 비교용 직전 기간과 스파크라인 14칸을 위해 넉넉히 훑는다.
    # 다만 40일을 넘기면 전 종목 공시가 수백 페이지라 끊는다. 그때는 직전
    # 기간이 온전하지 않으니 변화율을 내지 않는다.
    span = min(max(days * 2, 14), 40)
    prev_complete = days * 2 <= span
    ttl = 0 if force else 300
    raw = GOOD.scan(FIN.API_KEY, span, False, ttl)

    end = dt.date.today()
    cur_from = (end - dt.timedelta(days=days)).strftime("%Y%m%d")
    prev_from = (end - dt.timedelta(days=days * 2)).strftime("%Y%m%d")

    known = {c["code"] for c in INDEX["companies"]}
    smap = sector_map()
    stocks = (smap or {}).get("stocks", {})

    def tag(r):
        info = stocks.get((r.get("code") or "").upper(), {})
        r["sector"] = info.get("sector") or "분류없음"
        r["industry"] = info.get("industry") or "분류없음"
        r["themes"] = info.get("themes") or []
        r["collected"] = r.get("code") in known
        return r

    cur = {"good": [], "check": [], "bad": []}
    prev_good = []
    for grp in ("good", "check", "bad"):
        for r in raw.get(grp, []):
            tag(r)
            d = r.get("date") or ""
            if d >= cur_from:
                cur[grp].append(r)
            elif d >= prev_from and grp == "good":
                prev_good.append(r)

    def keys_of(r):
        if level == "theme":
            return r["themes"] or ["테마없음"]
        return [r["industry"] if level == "industry" else r["sector"]]

    # 업종 크기 — 밀도 계산의 분모
    if level == "theme":
        sizes = (smap or {}).get("themes", {})
    elif level == "industry":
        sizes = (smap or {}).get("industries", {})
    else:
        sizes = {}
        for ind, n in (smap or {}).get("industries", {}).items():
            sec = SECT.SECTOR_OF.get(ind, "기타") if SECT else "기타"
            sizes[sec] = sizes.get(sec, 0) + n

    spark_days = [(end - dt.timedelta(days=i)).strftime("%Y%m%d")
                  for i in range(min(span, 30) - 1, -1, -1)]
    groups = {}

    def g(name):
        return groups.setdefault(name, {
            "name": name, "size": sizes.get(name, 0),
            "good": 0, "check": 0, "bad": 0,
            "cw": {}, "pcw": {},               # 회사별 최대 강도 (당기 / 직전)
            "spark": {d: 0 for d in spark_days}, "top": {}})

    # 업종 점수는 목록과 같은 강도 기준으로 센다.
    # 내부자 매수·대량보유 보고서(●)는 호재의 80% 이상인데 지분이 조금만
    # 바뀌어도 나오는 정형 보고서라, 이걸 세면 점수가 사실상 '지분 보고서
    # 밀도'가 된다.
    #
    # 그리고 공시 건수가 아니라 '회사 수'로 센다. 업종 추세는 여러 회사에서
    # 동시에 일어나는 것이다. 건수로 세면 한 회사가 두 번 공시해도 두 배가
    # 되고, 그 회사가 속한 테마 여러 개가 한꺼번에 뜬다 (HDC 수주 한 건이
    # 면세점·호텔·지주사 테마를 동시에 띄웠다). 회사마다 가장 강한 공시
    # 하나만 센다.
    for r in cur["good"]:
        if r["weight"] < minw:
            continue
        for k in keys_of(r):
            x = g(k)
            x["good"] += 1
            c = r["corp"]
            x["cw"][c] = max(x["cw"].get(c, 0), r["weight"])
            old = x["top"].get(c)
            if old is None or (r["weight"], r["date"]) > (old["weight"], old["date"]):
                x["top"][c] = r
    for r in prev_good:
        if r["weight"] < minw:
            continue
        for k in keys_of(r):
            x = g(k)
            c = r["corp"]
            x["pcw"][c] = max(x["pcw"].get(c, 0), r["weight"])
    for grp in ("check", "bad"):
        for r in cur[grp]:
            for k in keys_of(r):
                g(k)[grp] += 1
    # 스파크라인은 전 기간 호재 강도를 날짜별로
    for r in raw.get("good", []):
        if r["weight"] < minw:
            continue
        d = r.get("date") or ""
        for k in keys_of(r):
            x = g(k)
            if d in x["spark"]:
                x["spark"][d] += r["weight"]

    rows = []
    for x in groups.values():
        if x["good"] == 0 and x["check"] == 0 and x["bad"] == 0:
            continue
        x["w"] = sum(x.pop("cw").values())
        x["prev_w"] = sum(x.pop("pcw").values())
        x["corps"] = sum(1 for _ in x["top"])
        size = max(x["size"], 1)
        x["density"] = x["w"] / (size ** 0.5)
        # 한 회사만으로 뜬 그룹은 추세가 아니라 개별 이벤트다
        x["single"] = x["corps"] == 1
        if prev_complete:
            x["change"] = ((x["w"] - x["prev_w"]) / x["prev_w"] * 100) if x["prev_w"] else None
            x["new"] = x["prev_w"] == 0 and x["w"] > 0
        else:
            x["change"], x["new"] = None, False
        x["spark"] = [x["spark"][d] for d in spark_days]
        x["top"] = sorted(x["top"].values(), key=lambda r: (r["weight"], r["date"]),
                          reverse=True)[:8]
        rows.append(x)

    # 점수 — 밀도의 교차 백분위.
    # 종목 3개 미만 그룹과 한 회사만으로 뜬 그룹은 한 건으로 튀므로 순위에서 뺀다.
    def eligible(x):
        return x["size"] >= 3 and not x["single"]

    ranked = sorted(x["density"] for x in rows if eligible(x))
    n = len(ranked)
    for x in rows:
        if not eligible(x) or n < 2:
            x["score"] = None
            continue
        lo = sum(1 for v in ranked if v < x["density"])
        x["score"] = round(lo / (n - 1) * 100)
    # 순위 있는 그룹 먼저, 그 안에서 점수순. 단일 회사 그룹은 뒤로.
    rows.sort(key=lambda x: (x["score"] is not None,
                             x["score"] if x["score"] is not None else -1,
                             x["corps"], x["w"]),
              reverse=True)

    out = {
        "days": days, "level": level, "at": raw.get("at"), "calls": raw.get("calls"),
        "scanned": raw.get("scanned"),
        "good": cur["good"], "check": cur["check"], "bad": cur["bad"],
        "categories": sorted(
            {c: sum(1 for r in cur["good"] if r["category"] == c)
             for c in {r["category"] for r in cur["good"]}}.items(),
            key=lambda kv: -kv[1]),
        "groups": rows, "spark_days": spark_days,
        "sector_ready": smap is not None,
        "sector_building": SECT_STATE["building"],
        "sector_progress": [SECT_STATE["done"], SECT_STATE["total"]],
    }
    return out


def earnings(c, mode="q", span=10):
    """실적 — 분기(또는 연간) 실적과 컨센서스를 한 줄에 세운다.

    실적은 DART, 컨센서스는 네이버. 네이버는 '다음 한 칸'만 주고 과거에
    무엇을 기대했는지는 돌려주지 않으므로, 서프라이즈는 이 도구가 기록해 둔
    스냅샷이 있는 분기에만 낼 수 있다.
    """
    if FIN is None or DRK is None:
        return {"error": "재무 모듈 없음"}
    corp = corp_code_of(c["code"])
    if not corp:
        return {"error": "DART 고유번호 없음"}

    period = "annual" if mode == "y" else "quarter"
    cons = FIN.fetch_consensus(c["code"], period)
    hist = FIN.consensus_history(c["code"], period)

    # 네이버는 실적 3년 + 추정 1년만 준다. 그 앞 구간은 DART 원장으로 채운다.
    this = dt.date.today().year
    years = list(range(this - span + 1, this + 1))
    pts = [p for p in DRK.series(corp, c["code"], years) if p.get("매출액")]

    def key_of(p):
        return "%d%02d" % (p["year"], p["q"] * 3) if mode == "q" else "%d12" % p["year"]

    actual = {}
    if mode == "q":
        for p in pts:
            actual[key_of(p)] = {"매출액": p.get("매출액"),
                                 "영업이익": p.get("영업이익"),
                                 "EPS": p.get("EPS")}
    else:
        # 사업보고서의 연간 값을 직접 읽는다. 분기 4개를 더하면 분기 데이터가
        # 없는 해(2015)가 통째로 빠진다.
        try:
            ann = FIN.annual_actuals(corp, years)
        except Exception:
            ann = {}
        for y, vals in ann.items():
            actual["%d12" % y] = {"매출액": vals.get("매출액"),
                                  "영업이익": vals.get("영업이익"),
                                  "EPS": vals.get("EPS")}
        # API 하한 앞 2년은 가장 오래된 사업보고서의 전기·전전기 칸에서 꺼낸다
        if ann:
            oldest = min(ann)
            try:
                back = FIN.annual_backfill(corp, oldest)
            except Exception:
                back = {}
            for y, vals in back.items():
                k = "%d12" % y
                if k not in actual and vals.get("매출액"):
                    actual[k] = {"매출액": vals.get("매출액"),
                                 "영업이익": vals.get("영업이익"),
                                 "EPS": vals.get("EPS"),
                                 "backfill": True}

    keys = sorted(set(list(actual.keys()) +
                      [col["key"] for col in cons.get("cols", [])]))
    keys = keys[-(span * 4 + 1):] if mode == "q" else keys[-(span + 1):]
    cons_keys = {col["key"] for col in cons.get("cols", []) if col.get("consensus")}

    rows = []
    for k in keys:
        # 네이버의 비컨센서스 칼럼은 추정치가 아니라 '이미 발표된 실적'이다.
        # 그대로 평가 행에 넣으면 실적과 같은 값이 찍혀 서프라이즈가 0인 것처럼
        # 보인다. 추정치는 isConsensus=Y 인 칸과, 우리가 기록해 둔 스냅샷뿐이다.
        if k in cons_keys:
            est = {r: cons.get("rows", {}).get(r, {}).get(k)
                   for r in ("매출액", "영업이익", "EPS")}
        else:
            rec0 = hist.get(k) or {}
            est = {r: rec0.get(r) for r in ("매출액", "영업이익", "EPS")}
        rec = hist.get(k) or {}
        act = actual.get(k)
        sur = {}
        for r in ("매출액", "영업이익", "EPS"):
            # 서프라이즈는 '그 분기 발표 전에 기록해 둔' 추정치와만 비교한다
            base = rec.get(r)
            a = (act or {}).get(r)
            if a is not None and base not in (None, 0):
                sur[r] = (a - base) / abs(base) * 100
        rows.append({
            "key": k,
            "label": (k[:4] + "Q" + str(int(k[4:6]) // 3)) if mode == "q" else k[:4],
            "actual": act,
            "estimate": est if any(v is not None for v in est.values()) else None,
            "recorded": {r: rec.get(r) for r in ("매출액", "영업이익", "EPS")}
                        if rec else None,
            "recorded_at": rec.get("기록일"),
            "surprise": sur or None,
            "is_estimate": k in cons_keys and act is None,
        })

    # 지표별 전년 대비 증감률. 차트에서 수준과 변화를 같이 보여주려고 붙인다.
    # 분기는 4칸 전(전년 동기), 연간은 1칸 전이 기준이다.
    back = 4 if mode == "q" else 1
    for i, r in enumerate(rows):
        yy = {}
        for k in ("매출액", "영업이익", "EPS"):
            cur = (r["actual"] or {}).get(k)
            if cur is None:
                cur = (r["estimate"] or {}).get(k)
            j = i - back
            if cur is None or j < 0:
                continue
            prev_r = rows[j]
            base = (prev_r["actual"] or {}).get(k)
            if base is None:
                base = (prev_r["estimate"] or {}).get(k)
            # 적자 기저에서의 증감률은 방향을 못 읽는다. 내지 않는다.
            if base is None or base <= 0:
                continue
            yy[k] = (cur - base) / abs(base) * 100
        r["yoy"] = yy or None

    nxt = next((r for r in reversed(rows) if r["is_estimate"]), None)

    # DART 재무제표 API(fnlttSinglAcntAll)는 연간 2015년, 분기 2016년이
    # 시작점이다. 그 앞은 status 013(데이터 없음)이 돌아온다. 보고서 본문은
    # 2011년까지 있지만 구조화된 재무 원장은 없다. 요청 기간이 그보다 길면
    # 조용히 적게 보여주지 말고 왜 짧은지 말해준다.
    floor = 2016 if mode == "q" else 2015
    asked_from = this - span + 1
    short = None
    if asked_from < floor:
        have = [r["label"][:4] for r in rows if r["actual"]]
        first = have[0] if have else str(floor)
        short = ("DART 재무제표 API는 %s %d년이 하한입니다(그 앞은 데이터 없음). "
                 "%s년까지는 가장 오래된 사업보고서에 실린 전기·전전기 비교 수치로 "
                 "역산해 채웠습니다. 그보다 앞은 구조화된 재무 원장이 없습니다 — "
                 "보고서 본문은 2011년까지 있으니 본문·궤도·전문검색 탭에서 볼 수 있습니다."
                 % ("분기" if mode == "q" else "연간", floor, first))

    return {"code": c["code"], "name": c["name"], "mode": mode,
            "rows": rows, "next": nxt, "span": span, "floor": floor,
            "short": short,
            "has_surprise": any(r["surprise"] for r in rows),
            "note": "컨센서스는 네이버 금융, 실적은 DART 원장입니다."}


DRUCK_BUILDING = {}

# ---------------------------------------------------------------- 스크리닝
SCREEN_YEARS = 4          # 가속도는 전년 동기가 필요하다. 4년이면 충분.
SCREEN = {"rows": [], "done": 0, "total": 0, "running": False,
          "years": SCREEN_YEARS, "built": 0}
SCREEN_LOCK = threading.Lock()


def screen_row(c):
    """회사 한 곳의 최신 분기 스크리닝 값. 데이터가 모자라면 None."""
    corp = corp_code_of(c["code"])
    if not corp or DRK is None:
        return None
    this_year = dt.date.today().year
    years = list(range(this_year - SCREEN_YEARS, this_year + 1))
    pts = DRK.series(corp, c["code"], years)
    pts = [p for p in pts if p.get("매출액")]
    if len(pts) < 2:
        return None

    dates = {}
    for r in c["reports"]:
        y, mth = r["stamp"].split("-")
        q = Q_OF_MONTH.get(mth)
        if q and (not r["tag"] or (int(y), q) not in dates):
            dates[(int(y), q)] = rcept_dt_of(r)
    DRK.attach_prices(pts, c["code"], dates)

    cur, prev = pts[-1], pts[-2]
    inv_delta = None
    if cur.get("재고일수") is not None and prev.get("재고일수") is not None:
        inv_delta = cur["재고일수"] - prev["재고일수"]

    turned = (cur.get("매출가속") is not None
              and prev.get("매출가속") is not None
              and prev["매출가속"] < 0 <= cur["매출가속"])
    # 가속 전환은 '덜 나빠짐'도 잡는다. 역성장 중인 회사와 성장 회사가
    # 같은 배지를 달면 오해하니 갈라놓는다.
    kind = None
    if turned:
        kind = "성장" if (cur.get("매출YoY") or 0) >= 0 else "역성장완화"

    # 이익률이 무의미해지는 경우가 둘이다. 이유가 다르니 구분해서 알려준다.
    #   1) 지주회사 — 영업이익에 지분법이익이 잡히는데 매출은 지주사 자체 매출뿐
    #   2) 매출이 거의 없는 회사(임상 단계 바이오 등) — 분모가 작아 비율이 발산
    bad, why = False, None
    if cur.get("이익률_비정상") or prev.get("이익률_비정상"):
        bad = True
        rev = cur.get("매출액") or 0
        why = ("분기 매출이 작아 이익률이 발산합니다 (매출 %s)"
               % ("%.0f억" % (rev / 1e8)) if rev < 1e10 else
               "영업이익이 매출을 크게 넘습니다. 지주회사의 지분법이익 등")
    return {
        "전환종류": kind,
        "이익률_사유": why,
        "code": c["code"], "name": c["name"], "quarter": cur["label"],
        "매출액": cur.get("매출액"),
        "매출YoY": cur.get("매출YoY"), "매출가속": cur.get("매출가속"),
        "전분기가속": prev.get("매출가속"),
        "영업이익률": cur.get("영업이익률"), "마진변화": cur.get("이익률변화"),
        "이익률_비정상": bad,
        "재고일수": cur.get("재고일수"), "재고일수변화": inv_delta,
        "PER_TTM": cur.get("PER_TTM"),
        "매출_TTM": cur.get("매출_TTM"), "영업이익_TTM": cur.get("영업이익_TTM"),
        "전환": turned,
    }


def _pct_rank(vals):
    """교차 순위 백분위. 지표마다 단위가 달라 값을 그대로 더할 수 없다."""
    clean = sorted(v for v in vals if v is not None)
    n = len(clean)
    if n < 2:
        return {}
    out = {}
    for v in set(clean):
        lo = sum(1 for x in clean if x < v)
        eq = sum(1 for x in clean if x == v)
        out[v] = (lo + eq / 2.0) / n * 100
    return out


def score_rows(rows):
    """매출가속 / 마진변화 / 재고일수 감소를 백분위로 환산해 가중합."""
    if len(rows) < 3:
        for r in rows:
            r["score"] = None
        return rows
    # 지주회사처럼 이익률이 의미 없는 곳은 마진 항목만 빼고 순위를 매긴다
    def margin_of(r):
        return None if r.get("이익률_비정상") else r.get("마진변화")

    ranks = {
        "매출가속": _pct_rank([r.get("매출가속") for r in rows]),
        "마진변화": _pct_rank([margin_of(r) for r in rows]),
        # 재고일수는 줄어드는 쪽이 좋다. 부호를 뒤집어 순위를 매긴다.
        "재고감소": _pct_rank([(-r["재고일수변화"])
                            if r.get("재고일수변화") is not None else None
                            for r in rows]),
    }
    W = {"매출가속": 0.50, "마진변화": 0.30, "재고감소": 0.20}
    for r in rows:
        tot, wsum = 0.0, 0.0
        for key, w in W.items():
            if key == "재고감소":
                v = r.get("재고일수변화")
                v = -v if v is not None else None
            elif key == "마진변화":
                v = margin_of(r)
            else:
                v = r.get(key)
            if v is None:
                continue
            pr = ranks[key].get(v)
            if pr is None:
                continue
            tot += pr * w
            wsum += w
        r["score"] = round(tot / wsum, 1) if wsum >= 0.5 else None
    return rows


def _run_screen():
    try:
        cos = list(INDEX["companies"])
        with SCREEN_LOCK:
            SCREEN["total"] = len(cos)
            SCREEN["done"] = 0
            SCREEN["rows"] = []
        rows = []
        for i, c in enumerate(cos, 1):
            try:
                r = screen_row(c)
                if r:
                    rows.append(r)
            except Exception:
                pass
            with SCREEN_LOCK:
                SCREEN["done"] = i
                SCREEN["rows"] = score_rows(list(rows))
        with SCREEN_LOCK:
            SCREEN["built"] = time.time()
    finally:
        with SCREEN_LOCK:
            SCREEN["running"] = False


def screen(force=False):
    with SCREEN_LOCK:
        stale = force or (not SCREEN["rows"] and not SCREEN["running"])
        if stale and not SCREEN["running"]:
            SCREEN["running"] = True
            threading.Thread(target=_run_screen, daemon=True).start()
        return {"rows": SCREEN["rows"], "done": SCREEN["done"],
                "total": SCREEN["total"] or len(INDEX["companies"]),
                "running": SCREEN["running"], "years": SCREEN_YEARS}


# ---------------------------------------------------------------- 시너지 발굴
# 수주잔고(선행) · 매출 가속(전환) · 최근 수주 공시(확인) · 주가 반영도(가격)를
# 한 줄에 세운다. 시너지.py 참조.
SYNERGY = {"running": False, "done": 0, "total": 0, "rows": [], "at": 0,
           "phase": "", "window": 0}
SYNERGY_LOCK = threading.Lock()
SYN_WINDOW = 40           # 최근 수주 공시를 훑는 기간(일). 전 종목 공시라 더 길면 느리다.
BAD_FLAG = {"희석": "전환사채·신주인수권부사채 발행", "유동성 위험": "유동성 위험 공시",
            "감사 문제": "감사의견 문제", "상장 위험": "상장 관련 위험", "소송·제재": "소송·제재"}


def _syn_row(b, good_by, bad_by, twins):
    c = company_by_code(b["code"])
    if not c:
        return None
    try:
        sr = screen_row(c) or {}
    except Exception:
        sr = {}
    tr = b["trend"]
    last, yoy = tr["last"], tr.get("yoy")
    rev = sr.get("매출_TTM")
    rev = rev if rev and rev > 0 else None
    b1 = last / (1 + yoy / 100) if (yoy is not None and yoy > -100) else None
    prices = FIN.fetch_prices(b["code"]) if FIN else {}
    p1y, pnow = SYN.price_change(prices, 365)
    p3m, _ = SYN.price_change(prices, 91)

    # 마지막 정기보고서 이후 새로 공시된 수주 계약
    last_rep = (b["points"][-1].get("rcept") or "")[:8]
    news = []
    for x in good_by.get(b["code"], []):
        if x["date"] <= last_rep:
            continue
        ci = SYN.contract(FIN.API_KEY, x["rcept"]) or {}
        news.append(dict(ci, date=x["date"], report=x["report"], url=x["url"],
                         subsidiary="자회사" in x["report"]))
    news.sort(key=lambda z: z["date"], reverse=True)
    # 자회사 대리 공시는 금액·비율이 자회사 기준이라 합계에서 뺀다
    own = [z for z in news if not z["subsidiary"] and z.get("amount")]
    new_amt = sum(z["amount"] for z in own)
    new_pct = (new_amt / rev * 100) if (rev and new_amt) else \
        (sum(z.get("pct") or 0 for z in own) or None)

    flags = []
    for x in bad_by.get(b["code"], []):
        f = BAD_FLAG.get(x["category"])
        if f and f not in [g.split(" (")[0] for g in flags]:
            flags.append("%s (%s-%s-%s)" % (f, x["date"][:4], x["date"][4:6], x["date"][6:]))

    sure = b["verified"] + b.get("explicit", 0)
    cover = (last / rev) if rev else None
    # 순위에서 빼는 이유. 잔고 값을 못 믿거나, 믿어도 회사 전체를 대표하지 않는 경우.
    why_not = None
    if tr["n"] < 4:
        why_not = "잔고 보고서가 %d개뿐" % tr["n"]
    elif tr.get("jumps", 0):
        why_not = "한 번에 5배 넘게 튄 값이 있다 (추출 오류 의심)"
    elif sure < (b["n_pts"] + 1) // 2:
        why_not = "검산·명시된 값이 %d/%d 로 절반이 안 된다" % (sure, b["n_pts"])
    elif cover is not None and cover < 0.15:
        # 세아제강지주: 잔고가 연매출의 10% — 일부 사업부 표라 작은 기저에서 +1387% 가 나온다
        why_not = "잔고가 연매출의 %.0f%% 뿐이라 사업 전체를 대표하지 않는다" % (cover * 100)
    reliable = why_not is None
    yoy_c = min(yoy, 300.0) if yoy is not None else None     # 반영 갭 계산용 (작은 기저 폭주 방지)
    r = {
        "code": b["code"], "name": b["name"], "sector": b["sector"], "industry": b["industry"],
        "backlog": last, "backlog_yoy": yoy,
        "btb": (1 + (last - b1) / rev) if (b1 is not None and rev) else None,
        "cover": cover, "why_not": why_not,
        "rev_ttm": rev, "rev_yoy": sr.get("매출YoY"), "rev_accel": sr.get("매출가속"),
        "margin": sr.get("영업이익률"),
        "margin_delta": None if sr.get("이익률_비정상") else sr.get("마진변화"),
        "per": sr.get("PER_TTM"), "quarter": sr.get("quarter"),
        "price": pnow, "price_1y": p1y, "price_3m": p3m,
        "gap": (yoy_c - p1y) if (yoy_c is not None and p1y is not None) else None,
        "new_contracts": news[:8], "new_pct": new_pct,
        "flags": flags, "reliable": reliable,
        "verified": b["verified"], "explicit": b.get("explicit", 0), "n_pts": b["n_pts"],
        "same_as": twins.get(b["code"], []),
        "spark": [p["value"] for p in b["points"][-12:]],
        "last_report": b["points"][-1].get("stamp"),
    }
    return r


def _run_synergy():
    try:
        # 1) 수주잔고 — 아직 없으면 먼저 만든다
        backlog_view()
        while True:
            with BACKLOG_LOCK:
                if not BACKLOG["running"] and BACKLOG["rows"]:
                    bl = list(BACKLOG["rows"])
                    break
                d, t = BACKLOG["done"], BACKLOG["total"]
            with SYNERGY_LOCK:
                SYNERGY["phase"] = "수주잔고 읽는 중 %d/%d" % (d, t)
            time.sleep(3)
        # 2) 최근 수주·악재 공시
        with SYNERGY_LOCK:
            SYNERGY["phase"] = "최근 %d일 공시 훑는 중" % SYN_WINDOW
        raw = GOOD.scan(FIN.API_KEY, SYN_WINDOW, False, 3600) if GOOD else {}
        good_by, bad_by = {}, {}
        for x in raw.get("good", []):
            if x.get("category") == "대형수주" and x.get("code"):
                good_by.setdefault(x["code"], []).append(x)
        for x in raw.get("bad", []):
            if x.get("code"):
                bad_by.setdefault(x["code"], []).append(x)
        # 지주사·자회사가 같은 잔고를 적은 쌍 (원 단위까지 같을 때만)
        twins = {}
        for b in bl:
            v = b["trend"]["last"]
            twins[b["code"]] = [o["name"] for o in bl if o is not b
                                and abs(o["trend"]["last"] - v) <= 1.0]
        # 3) 회사별
        with SYNERGY_LOCK:
            SYNERGY.update(total=len(bl), done=0, phase="회사별 실적·주가·계약 맞추는 중")
        rows = []
        for i, b in enumerate(bl, 1):
            try:
                r = _syn_row(b, good_by, bad_by, twins)
                if r:
                    rows.append(r)
            except Exception as e:
                print("시너지 %s 실패: %s" % (b.get("code"), e), flush=True)
            with SYNERGY_LOCK:
                SYNERGY["done"] = i
        SYN.score(rows)
        for r in rows:
            r["stage"], r["stage_why"] = SYN.stage(r)
            r["reasons"] = SYN.reasons(r)
        rows.sort(key=lambda r: (r["reliable"], r["score"] if r["score"] is not None else -1),
                  reverse=True)
        with SYNERGY_LOCK:
            SYNERGY.update(rows=rows, at=time.time(), phase="", window=SYN_WINDOW,
                           scanned=raw.get("scanned"))
    finally:
        with SYNERGY_LOCK:
            SYNERGY["running"] = False


def synergy_view(force=False):
    with SYNERGY_LOCK:
        stale = force or (not SYNERGY["rows"]) or time.time() - SYNERGY["at"] > 3 * 3600
        if stale and not SYNERGY["running"] and SYN is not None:
            SYNERGY["running"] = True
            threading.Thread(target=_run_synergy, daemon=True).start()
        out = {k: SYNERGY.get(k) for k in ("running", "done", "total", "phase", "at",
                                           "window", "scanned")}
        rows = list(SYNERGY["rows"])
    stages = {}
    for r in rows:
        if r["reliable"]:
            stages[r["stage"]] = stages.get(r["stage"], 0) + 1
    out.update(rows=rows, stages=stages,
               reliable=sum(1 for r in rows if r["reliable"]))
    return out


def financials(c, rep):
    """이 보고서 시점의 재무지표와 직전 대비 변화.

    비교 기준은 '직전 같은 종류'다. 분기를 사업보고서와 맞대면 누적 기간이
    달라 매출·이익이 엉뚱하게 튄다.
    """
    if FIN is None:
        return {"error": "재무 모듈을 불러오지 못했습니다."}
    corp = corp_code_of(c["code"])
    if not corp:
        return {"error": "DART 고유번호를 찾지 못했습니다. 수집기를 한 번 돌려주세요."}
    if rep["stamp"].split("-")[1] not in FIN.REPRT_BY_MONTH:
        return {"rows": [], "note": "정기보고서가 아니라 재무지표를 내지 않습니다."}

    base, kind = baseline_for(c, rep)
    if base is not None and base["tag"] and rep["tag"]:
        pass
    if base is not None and base["stamp"] == rep["stamp"]:
        # 정정 건은 같은 기간 원본과 비교하므로 재무는 직전 회차로 다시 잡는다
        prior = [r for r in c["reports"]
                 if r["label"] == rep["label"] and not r["tag"]
                 and r["stamp"] < rep["stamp"]]
        base = prior[-1] if prior else None
        kind = ("직전 " + rep["label"]) if base else ""

    prices = FIN.fetch_prices(c["code"])
    try:
        now = FIN.metrics_for(corp, c["code"], rep["stamp"],
                              rcept_dt_of(rep), prices)
    except Exception as e:
        return {"error": "재무 조회 실패: %s" % e}
    prev = None
    if base is not None and base["stamp"].split("-")[1] in FIN.REPRT_BY_MONTH:
        try:
            prev = FIN.metrics_for(corp, c["code"], base["stamp"],
                                   rcept_dt_of(base), prices)
        except Exception:
            prev = None
    if now is None:
        return {"rows": [],
                "note": "이 시점 재무제표가 DART API 에 없습니다 (구 회계기준 등)."}
    return {
        "rows": FIN.compare(now, prev),
        "now": {"stamp": rep["stamp"], "label": rep["label"] + rep["tag"],
                "price": now.get("주가"), "price_date": now.get("주가일"),
                "annual": now.get("annual")},
        "prev": ({"stamp": base["stamp"], "label": base["label"] + base["tag"]}
                 if (base is not None and prev) else None),
        "kind": kind,
    }


BUILDING = {}


def orbit_worker(code):
    c = company_by_code(code)
    if not c:
        return
    total = len(c["reports"])
    for i, rep in enumerate(c["reports"], 1):
        if BUILDING.get(code, {}).get("stop"):
            break
        try:
            build_brief(c, rep)
        except Exception:
            pass
        BUILDING.setdefault(code, {})["done"] = i
        BUILDING[code]["total"] = total
    BUILDING.setdefault(code, {})["finished"] = True


def orbit(code):
    """보고서별 변화 점수 시계열. 캐시된 것만 모아 준다."""
    c = company_by_code(code)
    if not c:
        return None
    rows, have = [], 0
    for rep in c["reports"]:
        p = brief_path(code, rep["rcept"])
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    b = json.load(fh)
                have += 1
                top = b["sections"][0]["section"] if b["sections"] else ""
                rows.append({
                    "stamp": rep["stamp"], "label": rep["label"],
                    "tag": rep["tag"], "rcept": rep["rcept"],
                    "score": b["score"], "kind": b["kind"],
                    "top": top, "tags": b["tags"],
                    "changed": len(b["sections"]),
                    "first": b.get("first", False),
                })
                continue
            except Exception:
                pass
        rows.append({"stamp": rep["stamp"], "label": rep["label"],
                     "tag": rep["tag"], "rcept": rep["rcept"],
                     "score": None, "kind": "", "top": "", "tags": {},
                     "changed": 0, "first": False})

    st = BUILDING.get(code, {})
    if have < len(c["reports"]) and not st.get("running"):
        BUILDING[code] = {"running": True, "done": have,
                          "total": len(c["reports"])}
        t = threading.Thread(target=_run_orbit, args=(code,), daemon=True)
        t.start()
    return {"rows": rows,
            "done": max(have, st.get("done", 0)),
            "total": len(c["reports"]),
            "finished": have >= len(c["reports"])}


def _run_orbit(code):
    try:
        orbit_worker(code)
    finally:
        BUILDING.setdefault(code, {})["running"] = False


def similarity_timeline(c, norm, labels=None):
    """연속한 두 보고서의 같은 섹션끼리 유사도. 낮을수록 말이 크게 바뀐 해."""
    hist = section_history(c, norm, labels)
    out = []
    prev_text, prev = None, None
    for h in hist:
        r = report_of(c, h["rcept"])
        text = read_section(c, r, h["file"])
        if prev_text is not None:
            sm = difflib.SequenceMatcher(None, blocks(prev_text), blocks(text),
                                         autojunk=False)
            out.append({
                "from": prev["stamp"], "to": h["stamp"],
                "from_rcept": prev["rcept"], "to_rcept": h["rcept"],
                "similarity": round(sm.ratio() * 100, 1),
                "chars_from": len(prev_text), "chars_to": len(text),
            })
        prev_text, prev = text, h
    return out


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "GiupChujeok/1.0"

    def log_message(self, fmt, *a):
        pass                      # 콘솔 조용히

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path

        try:
            if path in ("/", "/index.html"):
                return self._file("index.html", "text/html; charset=utf-8")
            if path == "/api/status":
                return self._send(200, {
                    "ready": INDEX_STATE["ready"],
                    "building": INDEX_STATE["building"],
                    "companies": len(INDEX["companies"]),
                    "reports": sum(c["count"] for c in INDEX["companies"]),
                })
            if path == "/api/companies":
                return self._send(200, [
                    {k: c[k] for k in ("code", "name", "from", "to",
                                       "count", "bytes")}
                    for c in INDEX["companies"]])
            if path == "/api/reindex":
                build_index(force=True)
                return self._send(200, {"ok": True,
                                        "companies": len(INDEX["companies"])})
            if path == "/api/company":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사를 찾을 수 없음"})
                secs = {}
                for r in c["reports"]:
                    for s in r["sections"]:
                        secs.setdefault(s["norm"], 0)
                        secs[s["norm"]] += 1
                sections = sorted(
                    ({"norm": k, "count": v} for k, v in secs.items()),
                    key=lambda s: (section_rank(s["norm"]), s["norm"]))
                labels = sorted({r["label"] for r in c["reports"]})
                return self._send(200, {
                    "code": c["code"], "name": c["name"],
                    "from": c["from"], "to": c["to"],
                    "count": c["count"], "bytes": c["bytes"],
                    "labels": labels, "sections": sections,
                    "reports": [{k: r[k] for k in
                                 ("stamp", "label", "tag", "rcept", "bytes")}
                                | {"sections": [
                                    {"file": s["file"], "title": s["title"],
                                     "norm": s["norm"], "bytes": s["bytes"]}
                                    for s in r["sections"]]}
                                for r in c["reports"]],
                })
            if path == "/api/text":
                c = company_by_code(q.get("code", ""))
                r = report_of(c, q.get("rcept", "")) if c else None
                if not r:
                    return self._send(404, {"error": "보고서 없음"})
                return self._send(200, {
                    "text": read_section(c, r, q.get("file", "")),
                    "stamp": r["stamp"], "label": r["label"],
                    "rcept": r["rcept"]})
            if path == "/api/history":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                labels = _labels(q)
                return self._send(200, section_history(
                    c, q.get("section", ""), labels))
            if path == "/api/diff":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                ra, rb = report_of(c, q.get("a", "")), report_of(c, q.get("b", ""))
                if not ra or not rb:
                    return self._send(404, {"error": "보고서 없음"})
                norm = q.get("section", "")
                fa = next((s["file"] for s in ra["sections"] if s["norm"] == norm), None)
                fb = next((s["file"] for s in rb["sections"] if s["norm"] == norm), None)
                if not fa or not fb:
                    return self._send(404, {"error": "양쪽에 같은 섹션이 없음"})
                res = diff_sections(read_section(c, ra, fa),
                                    read_section(c, rb, fb))
                res["a"] = {"stamp": ra["stamp"], "label": ra["label"]}
                res["b"] = {"stamp": rb["stamp"], "label": rb["label"]}
                return self._send(200, res)
            if path == "/api/brief":
                c = company_by_code(q.get("code", ""))
                r = report_of(c, q.get("rcept", "")) if c else None
                if not r:
                    return self._send(404, {"error": "보고서 없음"})
                return self._send(200, build_brief(c, r))
            if path == "/api/financials":
                c = company_by_code(q.get("code", ""))
                r = report_of(c, q.get("rcept", "")) if c else None
                if not r:
                    return self._send(404, {"error": "보고서 없음"})
                return self._send(200, financials(c, r))
            if path == "/api/backlog":
                if BACK is None:
                    return self._send(500, {"error": "수주 모듈 없음"})
                return self._send(200, backlog_view(
                    q.get("force") == "1", q.get("all") != "1"))
            if path == "/api/catalyst":
                if GOOD is None or FIN is None:
                    return self._send(500, {"error": "호재 모듈 없음"})
                days = max(1, min(int(q.get("days", 3)), 30))
                minw = max(1, min(int(q.get("minw", 2)), 3))
                return self._send(200, catalyst_view(
                    days, q.get("level", "sector"), q.get("force") == "1", minw))
            if path == "/api/earnings":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                yrs = max(3, min(int(q.get("years", 10)), 16))
                return self._send(200, earnings(c, q.get("mode", "q"), yrs))
            if path == "/api/matrix":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                if FIN is None:
                    return self._send(500, {"error": "재무 모듈 없음"})
                corp = corp_code_of(c["code"])
                if not corp:
                    return self._send(404, {"error": "DART 고유번호 없음"})
                stmt = q.get("stmt", "IS")
                mode = q.get("mode", "q")
                n = max(2, min(int(q.get("years", 4)), 16))
                this = dt.date.today().year
                years = list(range(this - n + 1, this + 1))
                key = "%s_%s_%s_%d" % (c["code"], stmt, mode, n)
                cache = os.path.join(CACHE_DIR, "matrix", key + ".json")
                sig = c["reports"][-1]["rcept"] if c["reports"] else ""
                if os.path.exists(cache) and q.get("force") != "1":
                    try:
                        with open(cache, "r", encoding="utf-8") as fh:
                            old = json.load(fh)
                        if old.get("sig") == sig:
                            return self._send(200, old)
                    except Exception:
                        pass
                res = FIN.statement_matrix(corp, years, stmt, mode)
                res["sig"] = sig
                res["name"] = c["name"]
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fh:
                    json.dump(res, fh, ensure_ascii=False)
                return self._send(200, res)
            if path == "/api/screen":
                return self._send(200, screen(q.get("force") == "1"))
            if path == "/api/synergy":
                if SYN is None or FIN is None or BACK is None:
                    return self._send(500, {"error": "시너지 모듈 없음"})
                return self._send(200, synergy_view(q.get("force") == "1"))
            if path == "/api/druck":
                res = druck(q.get("code", ""), q.get("force") == "1")
                if res is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, res)
            if path == "/api/orbit":
                res = orbit(q.get("code", ""))
                if res is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, res)
            if path == "/api/similarity":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, similarity_timeline(
                    c, q.get("section", ""), _labels(q)))
            if path == "/api/search":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, search_company(
                    c, q.get("q", ""), _labels(q),
                    q.get("section") or None))
            if path == "/api/trend":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                terms = [t.strip() for t in q.get("terms", "").split(",")
                         if t.strip()][:8]
                if not terms:
                    return self._send(400, {"error": "용어를 입력하세요"})
                return self._send(200, trend_company(
                    c, terms, _labels(q), q.get("section") or None))
        except Exception as e:
            return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

        return self._send(404, {"error": "no route"})

    def _file(self, name, ctype):
        path = os.path.join(WEB_DIR, name)
        if not os.path.exists(path):
            return self._send(404, "웹/index.html 이 없습니다.", "text/plain; charset=utf-8")
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _labels(q):
    v = q.get("labels", "").strip()
    return [x for x in v.split(",") if x] if v else None


def main():
    args = sys.argv[1:]
    port = 8765
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    open_browser = "--no-browser" not in args

    # 포트를 먼저 연다.
    # 색인은 수집 폴더(구글 드라이브, 보고서 25,000건 이상)를 훑는 작업이라
    # 수집기가 같은 드라이브를 쓰는 동안에는 몇 분씩 걸린다. 그동안 포트를
    # 안 열면 브라우저에는 ERR_CONNECTION_REFUSED 만 보인다.
    url = "http://127.0.0.1:%d/" % port
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("열림: " + url, flush=True)
    print("끄려면 이 창에서 Ctrl+C", flush=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def _index():
        print("색인 만드는 중...", flush=True)
        t0 = time.time()
        try:
            build_index()
        except Exception as e:
            INDEX_STATE.update(building=False, error=str(e))
            print("색인 실패: %s" % e, flush=True)
            return
        n = len(INDEX["companies"])
        tot = sum(c["count"] for c in INDEX["companies"])
        print("회사 %d곳 / 보고서 %d건 (색인 %.1f초)"
              % (n, tot, time.time() - t0), flush=True)
        if n == 0:
            print("수집된 자료가 없습니다. 먼저 기업추적_실행.bat 을 돌리세요.")

    threading.Thread(target=_index, daemon=True).start()
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
