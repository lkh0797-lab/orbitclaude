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


def scan():
    companies = []
    if not os.path.isdir(OUT_DIR):
        return {"companies": [], "built": time.time()}

    for cdir in sorted(os.listdir(OUT_DIR)):
        cpath = os.path.join(OUT_DIR, cdir)
        if not os.path.isdir(cpath):
            continue
        m = re.match(r"^(?P<name>.+)_(?P<code>\d{6})$", cdir)
        if not m:
            continue
        name, code = m.group("name"), m.group("code")

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
            "code": code, "name": name, "dir": cdir,
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


def build_index(force=False):
    global INDEX
    with INDEX_LOCK:
        sig = out_dir_signature()
        if not force and os.path.exists(INDEX_PATH):
            try:
                with open(INDEX_PATH, "r", encoding="utf-8") as fh:
                    cached = json.load(fh)
                if cached.get("sig") == sig:
                    INDEX = cached
                    return INDEX
            except Exception:
                pass
        idx = scan()
        idx["sig"] = sig
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(INDEX_PATH, "w", encoding="utf-8") as fh:
            json.dump(idx, fh, ensure_ascii=False)
        INDEX = idx
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


def rcept_dt_of(rep):
    return rep["rcept"][:8]


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

    print("색인 만드는 중...", flush=True)
    build_index()
    n = len(INDEX["companies"])
    tot = sum(c["count"] for c in INDEX["companies"])
    print("회사 %d곳 / 보고서 %d건" % (n, tot), flush=True)
    if n == 0:
        print("수집된 자료가 없습니다. 먼저 기업추적_실행.bat 을 돌리세요.")

    url = "http://127.0.0.1:%d/" % port
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("열림: " + url, flush=True)
    print("끄려면 이 창에서 Ctrl+C", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
