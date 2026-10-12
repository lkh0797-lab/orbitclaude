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
import subprocess
import shlex
import webbrowser
import urllib.parse
import zlib
import hashlib
from collections import Counter, defaultdict
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

    # 같은 종목코드 폴더가 둘이면(회사 이름이 바뀌어 수집기가 새 이름으로 다시 받은 경우 — 케이카 → KG모빌리티플랫폼)
    # 보고서가 더 최근까지 있는 쪽, 같으면 많은 쪽, 같으면 나중에 바뀐 폴더 하나만 남긴다
    best = {}
    for c in companies:
        k = (c["to"], c["count"], os.path.getmtime(os.path.join(OUT_DIR, c["dir"])))
        if c["code"] not in best or k > best[c["code"]][0]:
            best[c["code"]] = (k, c)
    companies = [v[1] for v in best.values()]
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


# ---------------------------------------------------------------- 문단 비교 — 교정지
# 문단(줄) 단위로 맞댄 뒤, 짝이 맞는 옛 문단·새 문단은 낱말 단위로 다시 맞대 '어느 말이 바뀌었나'만 보인다.
# 표는 칸마다 한 줄로 들어오므로 숫자 칸 변화는 표 하나로 묶는다.
DIFF_HEAD = re.compile(r"^\s*(?:[IVX]+\s*\.|\d{1,2}\s*\.|[가-하]\s*\.|\(\s*\d{1,2}\s*\)|\(\s*[가-하]\s*\)|[①-⑳]|\d{1,2}\))\s*\S")
DIFF_TABLE = re.compile(r"^\s*\[[^\]]{2,40}\]\s*$")
DIFF_TOK = re.compile(r"\d[\d,.]*%?|[A-Za-z]+|[가-힣]+|\s+|.", re.S)


def _cell(s):
    """표 칸 — 짧다. 숫자 칸이거나 머리글(제57기·과 목 같은)."""
    return len(s.strip()) <= 30


def _numcell(s):
    t = s.strip()
    return len(t) <= 30 and not HANGUL_RE.search(t) and re.search(r"\d", t) is not None


def _word_segs(a, b):
    ta, tb = DIFF_TOK.findall(a), DIFF_TOK.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    segs = []

    def push(t, x):
        if not x:
            return
        if segs and segs[-1][0] == t:
            segs[-1][1] += x
        else:
            segs.append([t, x])
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            push("eq", "".join(ta[i1:i2]))
        else:
            push("del", "".join(ta[i1:i2]))
            push("ins", "".join(tb[j1:j2]))
    return _semantic(segs), sm.ratio()


def _semantic(segs):
    """조각 정리 — 바뀐 곳 사이에 낀 짧은 공통부(띄어쓰기·조사·한두 글자)는 양쪽에 흡수해
    '뺀 구절 하나 → 넣은 구절 하나'로 읽히게 한다(diff-match-patch 의 semantic cleanup 과 같은 뜻)."""
    out = [list(s) for s in segs]
    changed = True
    while changed:
        changed = False
        for k in range(1, len(out) - 1):
            t, x = out[k]
            if t != "eq" or len(x.strip()) > 3:
                continue
            if out[k - 1][0] == "eq" or out[k + 1][0] == "eq":
                continue
            out[k] = ["del", x]
            out.insert(k + 1, ["ins", x])
            changed = True
            break
        # 붙어 있는 del·ins 묶음을 del 하나 + ins 하나로
        merged, run = [], []
        for t, x in out + [["eq", ""]]:
            if t == "eq":
                if run:
                    d = "".join(v for tt, v in run if tt == "del")
                    i = "".join(v for tt, v in run if tt == "ins")
                    if d:
                        merged.append(["del", d])
                    if i:
                        merged.append(["ins", i])
                    run = []
                if x:
                    if merged and merged[-1][0] == "eq":
                        merged[-1][1] += x
                    else:
                        merged.append(["eq", x])
            else:
                run.append([t, x])
        out = merged
    return out


def _heads(L):
    """줄마다 그 줄이 속한 소제목."""
    out, cur = [], ""
    for s in L:
        t = s.strip()
        if len(t) <= 70 and (DIFF_HEAD.match(t) or DIFF_TABLE.match(t)) and not _numcell(t):
            cur = t
        out.append(cur)
    return out


def _row_label(L, j):
    """표 숫자 칸의 행 이름 — 위로 올라가 처음 만나는 숫자 아닌 줄."""
    for k in range(j - 1, max(-1, j - 14), -1):
        t = L[k].strip()
        if t and not _numcell(t):
            return t[:40]
    return ""


def diff_changes(a_text, b_text):
    A, B = blocks(a_text), blocks(b_text)
    hA, hB = _heads(A), _heads(B)
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    cards, dels, adds = [], [], []      # dels/adds: (index, 기준 위치 j)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        dl = list(range(i1, i2)) if tag in ("delete", "replace") else []
        ad = list(range(j1, j2)) if tag in ("insert", "replace") else []
        # 같은 자리에서 바뀐 표 칸 — 차례로 짝
        dn = [i for i in dl if _cell(A[i])]
        an = [j for j in ad if _cell(B[j])]
        for i, j in zip(dn, an):
            cards.append({"k": "cell", "j": j, "a": A[i].strip(), "b": B[j].strip(), "lab": _row_label(B, j), "head": hB[j]})
        for i in dn[len(an):]:
            cards.append({"k": "cell", "j": j1, "a": A[i].strip(), "b": None, "lab": _row_label(A, i), "head": hA[i]})
        for j in an[len(dn):]:
            cards.append({"k": "cell", "j": j, "a": None, "b": B[j].strip(), "lab": _row_label(B, j), "head": hB[j]})
        dels += [(i, j1) for i in dl if not _cell(A[i])]
        adds += [j for j in ad if not _cell(B[j])]
    # 문단 짝짓기 — 문장이 절반 넘게 같으면 '고쳐 씀'. 순서가 바뀐 문단도 잡도록 섹션 전체에서 찾는다.
    norm = lambda s: re.sub(r"\s+", "", s)
    used_d, used_a = set(), set()
    by_norm, ref = {}, dict(dels)
    for i, _ in dels:
        by_norm.setdefault(norm(A[i]), []).append(i)
    ws = 0
    for j in adds:
        lst = by_norm.get(norm(B[j]))
        if lst:
            i = lst.pop(0)
            used_d.add(i)
            used_a.add(j)
            if abs(ref[i] - j) <= 3:      # 제자리에서 띄어쓰기만 고쳤다 — 보여줄 변화가 아니다
                ws += 1
                continue
            cards.append({"k": "move", "j": j, "text": B[j], "head": hB[j]})
    cand = []
    for j in adds:
        if j in used_a:
            continue
        for i, _ in dels:
            if i in used_d:
                continue
            m = difflib.SequenceMatcher(None, A[i], B[j], autojunk=False)
            if m.real_quick_ratio() < 0.5 or m.quick_ratio() < 0.5:
                continue
            r = m.ratio()
            if r >= 0.5:
                cand.append((r, i, j))
    for r, i, j in sorted(cand, reverse=True):
        if i in used_d or j in used_a:
            continue
        used_d.add(i)
        used_a.add(j)
        segs, _ = _word_segs(A[i], B[j])
        numeric = SKEL_RE.sub("", A[i]) == SKEL_RE.sub("", B[j])
        ins = "".join(x for t, x in segs if t == "ins")
        cards.append({"k": "num" if numeric else "mod", "j": j, "segs": segs, "keep": round(r * 100),
                      "tags": classify(ins) if not numeric else [], "head": hB[j], "ins": ins})
    for j in adds:
        if j not in used_a:
            cards.append({"k": "add", "j": j, "text": B[j], "tags": classify(B[j]), "head": hB[j]})
    for i, j in dels:
        if i not in used_d:
            cards.append({"k": "del", "j": j, "text": A[i], "tags": classify(A[i]), "head": hA[i]})
    cards.sort(key=lambda c: (c["j"], {"del": 0, "mod": 1, "num": 1, "add": 2, "move": 3, "cell": 4}[c["k"]]))
    # 표 칸은 소제목마다 한 장으로
    out, tbl = [], None
    for c in cards:
        if c["k"] == "cell":
            if tbl and tbl["head"] == c["head"] and c["j"] - tbl["j_end"] <= 40:
                tbl["items"].append({"lab": c["lab"], "a": c["a"], "b": c["b"]})
                tbl["j_end"] = c["j"]
                continue
            tbl = {"k": "table", "j": c["j"], "j_end": c["j"], "head": c["head"],
                   "items": [{"lab": c["lab"], "a": c["a"], "b": c["b"]}]}
            out.append(tbl)
            continue
        tbl = None if c["k"] != "move" else tbl
        out.append(c)
    n = max(len(B), 1)
    for k, c in enumerate(out):
        c["id"] = k
        c["pos"] = round(c["j"] / n, 4)
        if c["k"] == "table":
            c["n"] = len(c["items"])
            c["items"] = c["items"][:60]
    # 핵심 변화 — 새로 쓰거나 고쳐 쓴 말 가운데 범주·금액·길이로 무거운 것 셋
    def weight(c):
        t = c.get("ins") if c["k"] == "mod" else c.get("text", "")
        if not t or len(t.strip()) < 15 or BOILER.search(t):
            return -1
        return 3 * len(c.get("tags") or []) + (1.5 if AMOUNT_RE.search(t) else 0) + min(len(t), 400) / 150
    top = sorted([c for c in out if c["k"] in ("add", "mod")], key=weight, reverse=True)
    top = [c["id"] for c in top if weight(c) > 0][:3]
    for c in out:
        c.pop("ins", None)
    stats = {k: sum(1 for c in out if c["k"] == k) for k in ("add", "mod", "num", "del", "move", "table")}
    stats["cells"] = sum(c.get("n", 0) for c in out if c["k"] == "table")
    stats["ws"] = ws
    return {"cards": out, "stats": stats, "top": top, "lines": len(B),
            "similarity": round(sm.ratio() * 100, 1)}


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


def baseline_yoy(c, rep):
    """변화 브리핑용 비교 대상 — 전년 동기. '같은 종류 직전'이면 1분기·3분기가 같은 '분기보고서'라 반년 전 분기와
    맞대게 된다(1Q↔3Q). 작년 같은 달 보고서(1Q↔작년 1Q)가 있으면 그것과 견준다. 정정 · 첫 보고서는 baseline_for 그대로."""
    base, kind = baseline_for(c, rep)
    if rep["tag"] or base is None:
        return base, kind
    want = "%d-%s" % (int(rep["stamp"][:4]) - 1, rep["stamp"][5:])
    yoy = [r for r in c["reports"] if r["label"] == rep["label"] and not r["tag"] and r["stamp"] == want]
    if yoy:
        return yoy[-1], "전년 동기 " + rep["label"]
    return base, kind


def brief_pair(c, base, rep, kind):
    """build_brief 와 같은 모양이되 비교 대상을 직접 준다. baseline_for 와 같은 짝이면 build_brief 캐시를 쓴다
    (궤도 · 평소 분량은 계속 '같은 종류 직전' 짝으로 잰다)."""
    b0, _ = baseline_for(c, rep)
    if base is None or (b0 is not None and b0["rcept"] == base["rcept"]):
        return build_brief(c, rep)
    path = os.path.join(CACHE_DIR, "brief_pair", c["code"], base["rcept"] + "_" + rep["rcept"] + ".json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    out = {"code": c["code"], "name": c["name"],
           "report": {k: rep[k] for k in ("stamp", "label", "tag", "rcept")},
           "base": {k: base[k] for k in ("stamp", "label", "tag", "rcept")},
           "kind": kind, "first": False}
    out.update(_brief_core(c, base, rep))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
    except OSError:
        pass
    return out


def _atomic_json(path, obj, tries=6):
    """JSON 을 원자적으로 쓴다 — 프로세스 · 스레드마다 다른 tmp(path.pid.tid.tmp)에 쓰고 os.replace.
    뷰어와 미리 계산 프로세스(도구/전종목_미리계산.py)가 같은 파일을 써도 반쯤 쓴 파일을 읽지 않는다.
    대상 파일을 다른 쪽이 열고 있으면 Windows 가 PermissionError — 잠깐 쉬고 다시. 끝내 못 쓰면 tmp 를 지우고 False."""
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        for i in range(tries):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                if i + 1 >= tries:
                    raise
                time.sleep(0.2 * (i + 1))
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return False


def brief_path(code, rcept):
    return os.path.join(CACHE_DIR, "brief", code, rcept + ".json")


def _brief_core(c, base, rep):
    """base → rep 섹션별 비교(새로 쓴 문단·사라진 문단·숫자만 바뀐 문단). build_brief · brief_pair 가 같이 쓴다."""
    out = {"sections": [], "score": 0.0, "tags": {}}
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
    return out


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
        out.update(_brief_core(c, base, rep))

    _atomic_json(path, out)         # 원자적으로 — 미리 계산 프로세스와 같이 써도 결과가 같고(결정적) 반쯤 쓴 파일을 읽지 않는다
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


try:
    _ispec = _ilu.spec_from_file_location("변곡점", os.path.join(BASE, "변곡점.py"))
    INF = _ilu.module_from_spec(_ispec)
    _ispec.loader.exec_module(INF)
except Exception as _e:
    INF = None
    print("변곡점 모듈 로드 실패:", _e)


# ---------------------------------------------------------------- 궤도: 무엇이 바뀌었나 한 줄
# 요약 규칙을 바꾸면 올린다. 브리핑 캐시는 그대로 두고 요약만 다시 뽑는다.
GIST_V = 6
SEC_SHORT = {
    "사업의 내용": "사업", "이사의 경영진단 및 분석의견": "경영진단",
    "그 밖에 투자자 보호를 위하여 필요한 사항": "투자자 보호", "주주에 관한 사항": "주주",
    "재무에 관한 사항": "재무", "계열회사 등에 관한 사항": "계열사",
    "임원 및 직원 등에 관한 사항": "임원·직원", "대주주 등과의 거래내용": "대주주 거래",
    "감사인의 감사의견 등": "감사의견", "회사의 개요": "회사 개요",
    "이사회 등 회사의 기관": "이사회", "재무제표 등": "재무제표",
    "외부감사 실시내용": "외부감사",
}
# 문장 끝(…다. / …함.)이나 번호 매김 앞에서 끊는다
SENT_SPLIT = re.compile(r"(?<=[다음함됨임])\.\s*|(?<=[.;])\s+(?=[(\[①-⑳가-힣A-Z])|\s(?=\(\d{1,2}\)\s)|\s(?=[①-⑳])")
LEAD_RE = re.compile(r"^(?:[\s\-–—·•※*▶▷■□◆◇○●∙ㆍ]+|\(\*+\d*\)\s*|\(?\d{1,2}\)\s*|\d{1,2}\.\s*|[①-⑳]\s*|[가-하]\.\s*|\([가-하]\)\s*|\[[^\]]{1,20}\]\s*)+")
# 회계 상용구·서식 안내·정관 문구는 '새로 생긴 사실'이 아니다
BOILER = re.compile(r"기업회계기준서|회계정책|회계기준|주석\s*\d|참고하시기|참조하시기|작성기준일|해당\s*사항\s*(이\s*)?없|기재(를|는)?\s*(생략|하지)|재공시|영업비밀|"
                    r"상기\s*(표|내용)|공시서류|아래\s*표|단위\s*:|요약\s*재무|감사인|외부감사|전자공시|정관|제\d+기\s*(반기|분기)?\s*$|"
                    r"회피할\s*목적|위험\s*관리|수행의무|거래가격|재계산|계약잔액|자본전입|전환청구|신주인수권|주식배당|판매후리스|"
                    r"비유동성\s*대체|공정가치|당기손익|기타포괄|손상차손|이연법인세|할인율|측정\s*방법|인식\s*기준|현재가치|"
                    r"전환가격|행사가격|조정\s*후\s*가격|하회하는\s*경우|증분원가|(자산|비용)으로\s*(인식|상각)")
AMOUNT_RE = re.compile(r"\d[\d,.]*\s*(?:조|억|만\s*원|천|%|MW|GW|kV|MWh|GWh|톤|척|개국|배)")
DATE_RE = re.compile(r"20\d\d\s*년|’\d\d|'\d\d")
# 완결된 문장만 — 표 제목·목록 조각을 거른다
SENT_END = re.compile(r"(?:[다음함됨임]|니다)$")
SKEL_RE = re.compile(r"[\s\d,.()\[\]㈜·ㆍ\-~%]")
FRAG_RE = re.compile(r"^(?:의|을|를|은|는|이|가|에|와|과|로|및|등|중)\s|^[\"”’)\]]")
# 기간·서식 낱말은 '새 말'이 아니다
GIST_TERM_SKIP = re.compile(r"(?:당|전|전전)(?:분기|반기|기|해)|상반기|하반기|기말|기초|전년|정정|범주|공시금액|사항|제외|구속력|해당|현재")
ENDINGS = [("하였습니다", "함"), ("되었습니다", "됨"), ("했습니다", "함"), ("됐습니다", "됨"),
           ("있습니다", "있음"), ("없습니다", "없음"), ("입니다", "임"), ("합니다", "함"),
           ("됩니다", "됨"), ("습니다", "음")]


def _tokset(p):
    return set(INF.tokens(p)) if INF else set(re.findall(r"[가-힣]{2,}", p))


def _short(s, n=80):
    """문장을 한 줄로 — 번호·기호를 떼고 '~함'체로, 길면 절 경계에서 자른다."""
    s = LEAD_RE.sub("", re.sub(r"\s+", " ", s).strip()).strip(" .")
    # 표 제목이 문장 앞에 붙어 온 것(사업결합(1) 일반사항연결실체는…)
    s = re.sub(r"^[가-힣·]{2,12}\s*\(\d{1,2}\)\s*(?:일반\s*사항|개요)\s*", "", s)
    for a, b in ENDINGS:
        if s.endswith(a):
            s = s[:-len(a)] + b
            break
    if len(s) <= n:
        return s
    cut = s[:n]
    k = max(cut.rfind(", "), cut.rfind("며 "), cut.rfind("고 "), cut.rfind(" 및 "), cut.rfind("여 "))
    if k < n * 0.55:
        k = cut.rfind(" ")
    if k >= n * 0.55:
        cut = cut[:k]
    return cut.rstrip(" ,·") + "…"


def _section_line(c, base, rep, base_file, file, section, seen):
    """섹션 하나에서 직전 보고서에 없던 문장 한 줄과 새로 등장·사라진 낱말. 없으면 None.
    seen 은 이미 쓴 문장 뼈대 — 다른 섹션에 같은 문장이 또 실리면 다음 후보로 넘어간다."""
    nc = _novel_cands(c, base, rep, base_file, file, section)
    text = ""
    for v, sent, j in nc["cands"]:
        t = _short(sent)
        k = SKEL_RE.sub("", t)[:24]
        if k in seen:          # 다른 섹션에 같은 문장이 또 실리는 경우(소송 등)
            continue
        seen.add(k)
        text = t
        break
    if not text and not nc["came"]:
        return None
    return {"text": text, "came": nc["came"], "gone": nc["gone"],
            "novel": nc["novel"], "rephrased": nc["rephrased"]}


def _novel_cands(c, base, rep, base_file, file, section):
    """rep 의 섹션에서 base 에 없던 완결 문장 후보를 점수순으로. base·rep 를 뒤집어 부르면 '사라진 문장'.
    표현만 고친 문단(낱말 절반 이상 겹침)·회계 상용구·문장 조각·숫자만 바뀐 문장은 뺀다."""
    from collections import Counter, defaultdict
    a_text = read_section(c, base, base_file)
    b_text = read_section(c, rep, file)
    a_skel = SKEL_RE.sub("", a_text)
    A = [p for p in blocks(a_text) if not is_noise(p)]
    B = [p for p in blocks(b_text) if not is_noise(p)]
    a_keys = {re.sub(r"\s+", "", p) for p in A}
    a_sets = [_tokset(p) for p in A]
    inv = defaultdict(list)
    for i, ts in enumerate(a_sets):
        for t in ts:
            inv[t].append(i)
    novel, rephr = [], 0
    for p in B:
        if re.sub(r"\s+", "", p) in a_keys:
            continue
        ts = _tokset(p)
        if len(ts) < 4:
            continue
        hit = Counter()
        for t in ts:
            for i in inv.get(t, ()):
                hit[i] += 1
        best = 0.0
        for i, k in hit.most_common(6):
            j = k / (len(ts) + len(a_sets[i]) - k)
            best = max(best, j)
        if best >= 0.5:
            rephr += 1
        else:
            novel.append((p, best))
    # 재무 섹션의 새 낱말은 거의 회계 용어다 — 사업·경영진단·투자자 보호 쪽만 본다
    acct = section in ("재무에 관한 사항", "재무제표 등", "부속명세서")
    ca = Counter(INF.tokens(a_text)) if INF and not acct else Counter()
    cb = Counter(INF.tokens(b_text)) if INF and not acct else Counter()
    came = [t for t, n in cb.most_common(80)
            if t not in ca and n >= 2 and not GIST_TERM_SKIP.search(t)][:4]
    gone = [t for t, n in ca.most_common(80)
            if t not in cb and n >= 2 and not GIST_TERM_SKIP.search(t)][:3]

    cands = []
    for p, j in novel:
        for sent in SENT_SPLIT.split(p):
            sent = (sent or "").strip()
            if len(sent) < 18 or len(HANGUL_RE.findall(sent)) < 10:
                continue
            if sent.count("\t") >= 2 or BOILER.search(sent) or not SENT_END.search(sent):
                continue
            if FRAG_RE.match(sent):       # 문장 중간에서 잘린 조각(…의 분기배당을)
                continue
            # 문단은 새로 묶였어도 문장 자체는 전에도 있던 것 — 숫자만 바뀐 문장도 여기서 걸린다
            sk = SKEL_RE.sub("", sent)
            if len(sk) >= 20 and (sk[:22] in a_skel or sk[-22:] in a_skel):
                continue
            v = (3 * len(classify(sent)) + 2 * sum(1 for t in came if t in sent)
                 + (1.5 if AMOUNT_RE.search(sent) else 0) + (1 if DATE_RE.search(sent) else 0)
                 + (1 - j))
            if len(sent) > 220:
                v -= 1.5
            elif len(sent) < 30:
                v -= 1
            cands.append((v, sent, j))
    cands.sort(key=lambda x: -x[0])
    return {"cands": cands, "came": came, "gone": gone, "novel": len(novel), "rephrased": rephr}


def brief_gist(c, rep, b):
    """보고서 한 건에서 '무엇이 바뀌었나'를 섹션당 한 줄로.

    점수가 큰 섹션(1위, 그리고 1위의 45% 이상이면서 전체의 15% 이상인 곳, 최대 3곳)만 본다.
    직전 보고서의 어떤 문단과도 낱말이 절반 넘게 겹치면 표현만 고친 것으로 보고 뺀다.
    남은 '새 문단'에서 범주 낱말·새로 등장한 낱말·금액이 든 문장을 골라 줄인다.
    """
    secs = [s for s in b.get("sections", []) if s.get("score")]
    if not secs or not b.get("base"):
        return []
    base = next((r for r in c["reports"] if r["rcept"] == b["base"]["rcept"]), None)
    if base is None:
        return []
    top = secs[0]["score"]
    total = sum(s["score"] for s in secs) or 1.0
    pick = [s for i, s in enumerate(secs[:3])
            if i == 0 or (s["score"] >= top * 0.45 and s["score"] >= total * 0.15)]
    out, seen = [], set()
    for s in pick:
        ln = _section_line(c, base, rep, s.get("base_file") or s["file"], s["file"], s["section"], seen)
        if ln is None:
            continue
        text = ln["text"]
        out.append({
            "sec": s["section"], "short": SEC_SHORT.get(s["section"], s["section"]),
            "tags": classify(text)[:2] if text else [],
            "text": text, "came": ln["came"], "gone": ln["gone"],
            "novel": ln["novel"], "rephrased": ln["rephrased"], "numeric": s.get("numeric", 0),
            "share": round(s["score"] / total * 100),
        })
    if not out and secs:
        # 새 사실이 안 잡혔다 — 문구·서식을 손본 보고서
        s = secs[0]
        out.append({"sec": s["section"], "short": SEC_SHORT.get(s["section"], s["section"]),
                    "tags": [], "text": "", "came": [], "gone": [], "novel": 0,
                    "rephrased": 0, "numeric": s.get("numeric", 0),
                    "share": round(s["score"] / total * 100), "polish": True})
    return out


def _gist_of(c, rep, b, path, allow=True):
    """캐시된 브리핑에 요약이 없거나 낡았으면 뽑아 붙여 저장한다.
    allow=False 면 계산하지 않고 None(아직)을 돌려준다 — 한 요청이 오래 붙잡히지 않게."""
    if b.get("gist_v") == GIST_V:
        return b.get("gist") or []
    if not allow:
        return None
    try:
        g = brief_gist(c, rep, b)
    except Exception as e:
        print("요약 실패 %s %s: %s" % (c["code"], rep["rcept"], e), flush=True)
        return []
    b["gist"], b["gist_v"] = g, GIST_V
    _atomic_json(path, b)           # tmp 이름은 프로세스 · 스레드마다 다르게(뷰어 · 미리 계산이 같은 파일을 쓸 수 있다)
    return g


def inflect(code, force=False):
    """변곡점 — 정체성·수익 모델·방향이 꺾인 자리와 구루 렌즈. 변곡점.py 참조."""
    c = company_by_code(code)
    if not c:
        return {"error": "회사 없음"}
    corp = corp_code_of(code)
    if not corp or FIN is None:
        return {"error": "DART 고유번호를 찾지 못했습니다."}
    # 하루에 한 번 다시 — 카드의 '지금' 값(PSR · PEG · 경고)이 캐시 만든 날 가격에 묶이지 않게
    sig = (c["reports"][-1]["rcept"] if c["reports"] else "") + "_v%d_%s" % (INF.VERSION, dt.date.today().strftime("%Y%m%d"))
    sig = "%s:%d" % (sig, DRK.VERSION if DRK is not None else 0)     # 가속도 계산이 바뀌면(DRK.VERSION) 분기 사건 · 드러켄밀러 카드도 다시
    cache = os.path.join(CACHE_DIR, "inflect", code + ".json")
    if not force and os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as fh:
                old = json.load(fh)
            if old.get("sig") == sig:
                return old
        except Exception:
            pass
    sbad = []
    with _fin_watch() as bad:
        out = _inflect_build(c, code, corp, sig, sbad)
    if bad or sbad:
        # 원장 · 주식 수 일시 오류(한도 · 점검 · 네트워크 · 미리 계산 DART 막힘)가 낀 판 — sig 가 오늘 날짜라 쓰면 그날 내내 굳는다. 돌려주기만
        out["transient"] = "재무 원장 일시 오류" if bad else "주식 수 일시 오류"
        return out
    _atomic_json(cache, out)
    return out


def _inflect_build(c, code, corp, sig, sbad):
    """inflect 의 계산(캐시는 부른 쪽). sbad(list)에 주식 수 일시 오류를 담는다 — 원장은 부른 쪽 _fin_watch 가 본다."""
    this = dt.date.today().year
    funds = INF.fundamentals(FIN, corp, list(range(this - 15, this + 1)))

    # 분기 — 가속도 탭과 같은 계산. 보고서 접수번호를 붙여 문단 비교로 이어 준다.
    qrc = {}
    for r in c["reports"]:
        y, m = r["stamp"].split("-")
        q = Q_OF_MONTH.get(m)
        if q and (not r["tag"] or (int(y), q) not in qrc):
            qrc[(int(y), q)] = r["rcept"]
    try:
        dk = druck(code) or {}
    except Exception:
        dk = {}
    quarters = []
    for p in dk.get("points", []):
        quarters.append(dict(p, rcept=qrc.get((p["year"], p["q"]))))

    # 사업보고서 「사업의 내용」 — 해마다 마지막 접수본
    annual = {}
    for r in c["reports"]:
        if r["label"] != "사업보고서":
            continue
        y = int(r["stamp"][:4])
        if y not in annual or r["rcept"] > annual[y]["rcept"]:
            annual[y] = r
    docs = []
    for y in sorted(annual):
        r = annual[y]
        sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
        if not sec:
            continue
        try:
            docs.append((y, r["stamp"], r["rcept"], read_section(c, r, sec["file"])))
        except Exception:
            pass
    feats = INF.text_features(docs)
    came, gone = INF.term_shifts(feats)
    ys = [f["year"] for f in feats]
    rcept_of = {}
    prev = None
    for y in sorted(annual):
        rcept_of[y] = (prev, annual[y]["rcept"])
        prev = annual[y]["rcept"]

    # 가격 — 주가는 네이버 수정주가(오늘 주식 수 기준)라, 연말 주식 수도 분할 · 무상증자를 오늘 기준으로 맞춘 값(_land_shares)을 곱한다.
    # 예전엔 그해 실제 주식 수를 곱해 분할한 회사의 시가총액 · PSR 이 몇 배씩 틀렸다(엘에스일렉트릭 카드 1.08배 대 요약 5.51배, 2026-10-05 감사).
    price_info = {}
    lv = {}
    try:
        prices = FIN.fetch_prices(code)
        rc_of = {"03": "11013", "06": "11012", "09": "11014", "12": "11011"}
        lrep = max((r for r in c["reports"] if r["stamp"][5:7] in rc_of), key=lambda r: r["stamp"], default=None)
        latest = (int(lrep["stamp"][:4]), rc_of[lrep["stamp"][5:7]]) if lrep else None
        S_adj, _spl, _raw = _land_shares([d for d in funds if d.get("rev") is not None or d.get("ni") is not None], corp, latest, sbad)
        rnd = {f["year"]: f.get("rnd_pct") for f in feats}
        for d in funds:
            y = d["year"]
            sh = S_adj.get(y)
            px, _ = FIN.price_on(prices, "%d1230" % y)
            d["mcap"] = sh * px if (sh and px) else None
            d["psr"] = d["mcap"] / d["rev"] if (d["mcap"] and d.get("rev") and d["rev"] > 0) else None
            d["rnd_pct"] = rnd.get(y)
            d["rnd"] = d["rev"] * d["rnd_pct"] / 100 if (d.get("rev") and d["rnd_pct"]) else None
            d["prr"] = d["mcap"] / d["rnd"] if (d["mcap"] and d["rnd"]) else None
        # 버핏의 유보이익 1원 테스트 — 시작 · 끝 PSR 도 같이(시가총액 증가가 사업에서 왔나, 값의 재평가에서 왔나)
        F = [d for d in funds if d.get("re") is not None]
        if len(F) >= 6:
            a, b = F[-6], F[-1]
            dre = b["re"] - a["re"]
            if a.get("mcap") and b.get("mcap") and dre > 0:
                dcap = b["mcap"] - a["mcap"]
                rerate = (" · PSR %.2f배 → %.2f배" % (a["psr"], b["psr"]) + (" — 늘어난 시가총액의 상당 부분은 값의 재평가다" if b["psr"] >= a["psr"] * 2 else "")) \
                    if a.get("psr") and b.get("psr") else ""
                price_info["retained_test"] = {
                    "ratio": dcap / dre,
                    "note": "%d~%d년 유보이익 %s 늘 때 시가총액 %s 변했다 → 1원당 %.1f원%s" % (
                        a["year"], b["year"], _won_txt(dre), _won_txt(dcap), dcap / dre, rerate)}
        # 지금 — PSR · PEG 는 값 판단 요약(lens_value)과 같은 계산 하나로(최근 분기 주식 수 · 최근 4분기 매출 · 오늘 종가)
        lv = lens_value(code) or {}
        if lv.get("psr") and lv.get("mcap"):
            price_info["psr_now"] = {"psr": lv["psr"], "mcap": lv["mcap"], "date": lv.get("date"),
                                     "sales": lv.get("rev_ttm"), "label": lv.get("quarter")}
            lr = next((d for d in reversed(funds) if d.get("rnd")), None)
            if lr:
                price_info["prr_now"] = {"prr": lv["mcap"] / lr["rnd"], "year": lr["year"], "rnd": lr["rnd"], "rnd_pct": lr.get("rnd_pct")}
            elif any(d.get("rnd_pct") for d in funds):
                price_info["prr_now"] = {"rnd_pct": next(d["rnd_pct"] for d in reversed(funds) if d.get("rnd_pct"))}
        if lv.get("peg") is not None:
            price_info["peg"] = lv["peg"]
    except Exception as e:
        print("변곡점 가격 %s: %s" % (code, e), flush=True)

    price_info["druck_ev"] = _lens_ev(DRUCK_LENS)       # 드러켄밀러 카드의 '큰 표본' 문장 — 없으면 카드가 문장을 뺀다
    ev = INF.events(funds, quarters, feats, came, gone, rcept_of)
    # 지금 값의 경고 — 연말 PSR 만 보는 사건 규칙은 오늘의 PSR 3배↑를 놓친다('경고 0'으로 읽히던 것). 큰 표본에서 가장 단단했던 피할 신호.
    pn_ = price_info.get("psr_now") or {}
    if pn_.get("psr") and pn_["psr"] >= 3:
        e_ = _lens_ev("피셔 · PSR 3배↑(절대)") or {}
        dd_ = str(pn_.get("date") or "")
        ev.insert(0, {"year": int(dd_[:4]) if dd_[:4].isdigit() else dt.date.today().year, "stamp": "%s-%s" % (dd_[:4], dd_[4:6]) if len(dd_) >= 6 else None,
                      "lane": "경고", "guru": "피셔 1984", "tone": "warn", "title": "지금 PSR %.1f배 — 매출의 3배를 넘는 값" % pn_["psr"],
                      "detail": "시가총액이 최근 4분기 매출의 %.1f배(%s 종가)." % (pn_["psr"], dd_) +
                                (" 과거 같은 자리: 12개월 시장 대비 %+.1f%%p, 1년에 −30%% 넘게 빠진 비율 %.0f%% — 표본 편향이 있어 크기는 참고만." % (e_["diff"], e_["trap"])
                                 if e_.get("diff") is not None and e_.get("trap") is not None else ""),
                      "rcept": None, "prev_rcept": None})
    lens = INF.lenses(funds, quarters, price_info)
    lanes = {}
    for e in ev:
        lanes[e["lane"]] = lanes.get(e["lane"], 0) + 1
    ident = None
    good = [f for f in feats if f["overview"]]
    if len(good) >= 2:
        ident = {"then": {"year": good[0]["year"], "text": good[0]["overview"]},
                 "now": {"year": good[-1]["year"], "text": good[-1]["overview"]}}
    keep = ("year", "rev", "op", "ni", "margin", "fcf", "fcf_conv", "roic", "roe", "capex_int",
            "de", "payout", "cfo", "capex", "mcap", "psr", "rnd_pct", "prr")
    out = {"sig": sig, "code": code, "name": c["name"], "events": ev, "lanes": lanes,
           "lenses": lens, "identity": ident, "came": came, "gone": gone, "term_years": ys,
           "funds": [{k: d.get(k) for k in keep} for d in funds],
           "years": [funds[0]["year"], funds[-1]["year"]] if funds else None}
    return out


def rcept_dt_of(rep):
    return rep["rcept"][:8]


Q_OF_MONTH = {"03": 1, "06": 2, "09": 3, "12": 4}


DRUCK_BUILDING = {}           # code → {"done", "total"} — 백그라운드(bg=1) 계산 진행. 그 스레드가 끝나면(실패해도) 지운다
DRUCK_LOCKS = {}              # code → Lock — 한 회사를 두 스레드가 같이 쌓지 않게
DRUCK_LOCKS_G = threading.Lock()
DRUCK_SOFT = {}               # code → (시각, sig, 결과, 종류) — 디스크에 안 쓴 결과. 종류 "transient"(일시 오류가 낀 빌드) · "error"(백그라운드 실패)
DRUCK_SOFT_TTL = 600          # 초 — 이 동안은 같은 sig 로 다시 쌓지 않는다(백그라운드 폴링이 같은 빌드를 끝없이 다시 돌리지 않게)
DRUCK_STALE_KICKED = set()    # 지금 PER 이 낡아(분할 뒤) 뒤에서 force 로 다시 쌓기 시작한 회사 — 이 서버 프로세스에서 회사마다 한 번만(되풀이 없음)


def _druck_path(code):
    return os.path.join(CACHE_DIR, "druck", code + ".json")


def _druck_read(code):
    """가속도 캐시(지금 VERSION 만). 옛 버전 · 깨진 파일은 None — 다시 계산 대상. 규칙은 DRK.read_cache 하나에 둔다."""
    return DRK.read_cache(_druck_path(code)) if DRK is not None else None


def _druck_sig(c):
    rc = max((r["rcept"] for r in c["reports"]), default="")     # 정정 포함 — 옛 분기 정정도 다시 계산
    return "v%d:%s" % (DRK.VERSION, rc)


def _druck_fresh(code, sig, bg=False):
    """지금 sig 로 이미 있는 결과 — 디스크 캐시, 아니면 TTL 안의 미캐시 결과. 없으면 None.
    백그라운드 실패("error")는 bg 조회(wait=False 폴링)에만 준다 — 동기 호출(inflect 등)은 오류 기억에 막히지 않고 직접 쌓아 본다."""
    old = _druck_read(code)
    if old and old.get("sig") == sig:
        return old
    soft = DRUCK_SOFT.get(code)
    if soft and soft[1] == sig and time.time() - soft[0] < DRUCK_SOFT_TTL and (bg or soft[3] != "error"):
        return soft[2]
    return None


def _druck_meta(c):
    """DRK.series 의 meta {filed, fy_bad, amend} — 규칙은 DRK.filed_meta(서버 없이 시험한다). amend(분기별 마지막 정정 공시일)가
    원장 캐시 파일 날짜와 같거나 뒤면 그 분기만 다시 받는다."""
    return DRK.filed_meta(c["reports"])


_INDUTY = {}                  # corp_code → KSIC — .cache/거시/induty.json 을 처음 쓸 때 한 번 읽는다


def _ksic_of(corp):
    if not _INDUTY:
        try:
            with open(os.path.join(CACHE_DIR, "거시", "induty.json"), "r", encoding="utf-8") as fh:
                _INDUTY.update(json.load(fh) or {})
        except Exception:
            return ""
    return str(_INDUTY.get(corp) or "")


def _druck_fin(code):
    """KSIC 64~66(금융 · 보험 · 금융 지원)인가."""
    return _ksic_of(corp_code_of(code) or "").startswith(("64", "65", "66"))


def _druck_basis(code, pts=()):
    """기준 지표 — 금융(KSIC 64~66)이고 최근 8개 자료 분기에 매출액이 없으면 영업이익, 아니면 매출(규칙은 DRK.pick_basis)."""
    return DRK.pick_basis(pts, _druck_fin(code))


def _no_secret(msg):
    """로그 · 응답에 남길 예외 문장 — URL 쿼리의 키 값(crtfc_key 등)은 가리고, 한 줄 · 300자로."""
    msg = re.sub(r"(?i)((?:crtfc_key|api_?key|appkey|appsecret|secret|token)=)[^&\s'\"]+", r"\1***", str(msg))
    return " ".join(msg.split())[:300]


def _druck_bg(code, force, offline):
    """백그라운드 빌드. 실패하면 서버 로그에 한 줄 남기고, 오류를 TTL 동안 들고 있어(폴링이 같은 실패를 되풀이하지 않게) 다음 bg 요청이 받아 간다."""
    try:
        druck(code, force, offline, True)
    except Exception as e:
        msg = _no_secret("%s: %s" % (type(e).__name__, e))
        print("가속도 백그라운드 계산 실패:", code, msg)
        c = company_by_code(code)
        if c is not None and DRK is not None:
            DRUCK_SOFT[code] = (time.time(), _druck_sig(c), {"error": "가속도 계산 실패 — " + msg}, "error")
    finally:
        DRUCK_BUILDING.pop(code, None)


def druck(code, force=False, offline=False, wait=True):
    """분기 단독 실적 시계열 v2(series → per_share → accel → attach_prices) + 본문에서 긁은 가동률 · 수주잔고.
    캐시 {v, sig, code, name, basis, fy, points, text, split_after, transient}. wait=False 이고 지금 sig 의 결과가 없으면
    백그라운드로 쌓기 시작하고 {"building": True, "done", "total"} 를 바로 돌려준다(done · total = 받은 분기 수 · 받을 분기 수)."""
    c = company_by_code(code)
    if not c:
        return None
    if DRK is None:
        return {"error": "가속도 모듈을 불러오지 못했습니다."}
    corp = corp_code_of(code)
    if not corp:
        return {"error": "DART 고유번호를 찾지 못했습니다."}
    sig = _druck_sig(c)
    if not force:
        got = _druck_fresh(code, sig, bg=not wait)
        if got is not None:
            return got
    if not wait:
        with DRUCK_LOCKS_G:
            if code not in DRUCK_BUILDING:
                DRUCK_BUILDING[code] = {"done": 0, "total": 0}
                try:
                    threading.Thread(target=_druck_bg, args=(code, force, offline), daemon=True).start()
                except Exception:
                    DRUCK_BUILDING.pop(code, None)      # 스레드를 못 띄웠다(32비트 'can't start new thread') — 칸이 남으면 화면이 영영 '쌓는 중'
                    raise
        return {"building": True, **DRUCK_BUILDING.get(code, {})}
    with DRUCK_LOCKS_G:
        lk = DRUCK_LOCKS.setdefault(code, threading.Lock())
    with lk:
        if not force:
            got = _druck_fresh(code, sig)          # 잠금을 기다리는 동안 다른 스레드가 쌓았을 수 있다
            if got is not None:
                return got
        old = _druck_read(code)
        meta = _druck_meta(c)
        years = sorted({int(r["stamp"][:4]) for r in c["reports"]})

        def prog(done, total):                     # 백그라운드 진행률 — bg 요청이 걸어 둔 칸이 있을 때만
            st = DRUCK_BUILDING.get(code)
            if st is not None:
                st.update(done=done, total=total)
        pts = DRK.series(corp, code, years, meta=meta, offline=offline, progress=prog)
        transient = DRK.LAST.get("transient", 0)
        if DRK.filed_missing(pts, meta) is not None:
            transient += 1                 # 가장 최근에 공시된 분기 원장이 비었다(공시 당일 DART 013 등) — 새 서명으로 굳히지 않고 다음에 다시 받는다
        sev = _share_events(code)
        DRK.per_share(pts, sev)
        basis = _druck_basis(code, pts)
        DRK.accel(pts, basis=basis)
        dates = {(p["year"], p["q"]): meta["filed"][p["n"]] for p in pts if meta["filed"].get(p["n"])}
        DRK.attach_prices(pts, code, dates)
        if dates and not any(p.get("주가") for p in pts):
            transient += 1                 # 주가를 한 분기도 못 붙였다 — 네이버 일시 오류면 fetch_prices 가 {} 를 준다. 깨끗한 빌드로 캐시하지 않는다
        sa = DRK.split_after(pts, sev)
        DRK.hold_per(pts, sa)              # 마지막 자료 분기 뒤 분할 · 병합 — 분할 뒤 첫 보고서까지 PER_TTM 을 비운다(주가 · EPS 기준이 어긋난다)
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
                text_rows.append({"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"], "found": found})
        out = {"v": DRK.VERSION, "sig": sig, "code": code, "name": c["name"], "basis": basis,
               "fy": sorted(meta["fy_bad"]), "points": pts, "text": text_rows,
               "split_after": sa, "transient": transient}
        if transient:
            # 일시 오류가 낀 빌드는 디스크에 안 쓴다 — 예전 캐시를 주되 transient 를 달아 화면이 '새로 못 받았다'를 알게 한다. TTL 동안만 들고 있다
            res = dict(old, transient=transient) if old else out
            DRUCK_SOFT[code] = (time.time(), sig, res, "transient")
            return res
        DRUCK_SOFT.pop(code, None)
        if not DRK.write_cache(_druck_path(code), out):     # 원자 쓰기(.tmp → replace) — 읽는 쪽이 파일을 열고 있으면 몇 번 다시 해 본다
            print("가속도 캐시 못 씀(파일이 잠김 — 이번 결과는 캐시하지 않음):", code)
        return out


def _druck_now(code, d):
    """지금 PER — 규칙은 DRK.now_per(서버 없이 시험한다). EPS_TTM 이 있으면 네이버 수정주가(하루 캐시)를 받아 넘긴다. 캐시하지 않는다.
    EPS_TTM 이 하나도 없어도 부른다 — 화면이 '왜 없는지'(금융사 주식 수 · 기준 다른 4분기 · 적자)를 reason 으로 받는다."""
    pts = d.get("points") or []
    if DRK is None:
        return None
    pr = {}
    if FIN is not None and any(p.get("EPS_TTM") for p in pts):
        try:
            pr = FIN.fetch_prices(code) or {}
        except Exception:
            pr = {}
    return DRK.now_per(pts, pr, d.get("split_after"), fin=_druck_fin(code))


def _druck_kick_stale(code):
    """지금 PER 의 k 가 0.55~1.8 밖이다(캐시 뒤 주가 자료가 다시 보정됨) — 뒤에서 force 로 한 번 다시 쌓는다.
    split_after(마지막 분기 뒤 분할 공시)만으로는 다시 쌓지 않는다 — 분할 뒤 보고서 전에 다시 쌓으면 보정된 주가 ÷ 분할 전 EPS 로 역사 PER 이 틀어진다
    (그동안 PER 은 hold_per 가 비운다). 회사마다 이 서버 프로세스에서 한 번만(DRUCK_STALE_KICKED). 스레드를 못 띄우면 표시를 거두고 예외를 올린다."""
    with DRUCK_LOCKS_G:
        if code in DRUCK_STALE_KICKED:
            return False
        DRUCK_STALE_KICKED.add(code)
    try:
        druck(code, True, wait=False)
    except Exception:
        with DRUCK_LOCKS_G:
            DRUCK_STALE_KICKED.discard(code)
        raise
    return True


def _druck_bt_path(name):
    return os.path.join(CACHE_DIR, "druck_bt", name)


def druck_bt_view():
    """가속도 탭 기저율 줄 · 변곡 기록 위 두 칸 — 밤 64비트 백테스트의 bt_accel.json 에서 화면이 쓰는 칸만(mtime 캐시).
    regime = 7국면별 칸(regime.B), ev_all = ▲ · ▼ 변곡(B_up · B_dn), base_any = 같은 표본 아무 분기 12개월 시장 대비 중앙.
    회사 수 · 표본 수는 파일 값 그대로(고정 문구 없음). 파일이 없으면 값이 모두 None — 화면이 '계산 전'으로 읽는다."""
    acc = _ind_file("bt_accel", _druck_bt_path("bt_accel.json")) or {}
    return {"regime": (acc.get("regime") or {}).get("B"), "ev_all": acc.get("ev_all"), "base_any": acc.get("base_any"),
            "firms": acc.get("firms"), "n": acc.get("n"), "at": acc.get("at")}


def druck_events(code):
    """이 회사의 변곡 · 보고서 구간 시장 대비 수익률 — events.json 의 그 code 항목(mtime 캐시, 4MB 남짓이라 한 번만 올린다).
    {turns: [{n, dir, date, ex6, ex12, state}], periods: [{n, d, d2, ex, state}]}. 없으면 빈 목록."""
    ev = _ind_file("druck_events", _druck_bt_path("events.json")) or {}
    got = ev.get(code) if isinstance(ev, dict) else None
    return {"turns": (got or {}).get("turns") or [], "periods": (got or {}).get("periods") or []}


# ---------------------------------------------------------------- 가속도 밤 미리 계산 · 기저율(2026-10-10, 가속도 개편 6)
# 매일 02:00 전 종목 druck 를 캐시 우선(offline — 없는 원장 분기만 DART 에서 받되 한 번에 DRUCK_NET_BUDGET 까지)으로 쌓고, 끝나면
# 64비트 파이썬으로 도구/가속기준_백테스트.py --from-cache 를 돌려 .cache/druck_bt/bt_accel.json(기저율) · events.json(회사별 사건)을 다시 낸다.
# 06:00 이 되면 멈춘다(06:30 저평가 · DART 한도 보호) — 다음 밤에는 지금 sig 인 캐시를 바로 건너뛰므로 자연히 이어서 쌓는다.
DRUCK_PRE = {"at": None, "done": 0, "total": 0, "net": 0, "running": False}
DRUCK_PRE_LOCK = threading.Lock()
DRUCK_NET_BUDGET = 2000       # 한 번 돌 때 DART 원장 받기 상한(DRK.NET) — 캐시 파일이 없는 분기 · 정정 공시로 다시 받는 분기 · 013 다시 묻기를 센다
DRUCK_PRE_AT = (2, 0)         # 00:10 수집 뒤 · 06:30 저평가 전
DRUCK_PRE_STOP = 6            # 시 — 시작한 뒤 처음 오는 06:00 에 멈춘다
BT_PY = os.environ.get("ORBIT_BT_PY") or "py -3.13"     # 64비트 파이썬 실행기(명령 문자열) — 서버 모듈 + 전 종목 주가를 한 번에 올린다
BT_QUICK_FAIL = 20            # 초 — 64비트 실행기가 이보다 빨리 0 아닌 코드로 끝나면(런처 · import 실패) 서버 파이썬으로 다시


def _bt_cmd(spec=None):
    """실행기 명령 문자열('py -3.13' · '"C:\\Python313\\python.exe"') → argv 앞부분. Windows 경로의 \\ 를 지키려고 posix=False 로 쪼개고
    감싼 따옴표만 벗긴다. 비면 서버 자신의 파이썬."""
    parts = shlex.split(spec if spec is not None else BT_PY, posix=(os.name != "nt"))
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts] or [sys.executable]


def _druck_order(companies, has_cache):
    """밤 미리 계산 순서 — 캐시 파일이 이미 있는 회사(누가 연 적 있다) 먼저, 그 안팎에서 최근에 공시한 회사(마지막 rcept 내림차순) 먼저,
    보고서가 없는 회사는 끝. has_cache(code) → bool."""
    last = lambda c: max((r.get("rcept") or "" for r in c.get("reports") or []), default="")     # noqa: E731
    by_recent = sorted(companies, key=last, reverse=True)
    return sorted(by_recent, key=lambda c: 0 if has_cache(c.get("code")) else 1)       # 안정 정렬 — 최근 순서를 지킨다


def _druck_deadline(start, hour=DRUCK_PRE_STOP):
    """start 뒤 처음 오는 hour:00 — 밤 미리 계산을 멈출 때(02:00 시작이면 같은 날 06:00, 낮에 손으로 돌리면 다음 날 06:00)."""
    dl = start.replace(hour=hour, minute=0, second=0, microsecond=0)
    return dl if dl > start else dl + dt.timedelta(days=1)


def _druck_run_bt():
    """기저율 · 사건 파일 — BT_PY(ORBIT_BT_PY)로 도구/가속기준_백테스트.py --from-cache. 출력은 .cache/druck_bt/bt_run.log.
    실행기를 못 찾거나(FileNotFoundError) 곧바로(BT_QUICK_FAIL 초 안) 0 아닌 코드로 끝나면(py 런처 103 — 3.13 없음 · import 실패) 서버 자신의
    파이썬으로 다시 돈다 — 32비트면 메모리가 빠듯할 수 있다. 어느 실행기로 돌았는지 로그와 결과(py)에 남긴다."""
    script = os.path.join(BASE, "도구", "가속기준_백테스트.py")
    log = os.path.join(CACHE_DIR, "druck_bt", "bt_run.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    t0, res = time.time(), {"py": None, "rc": None}
    with open(log, "w", encoding="utf-8") as fh:
        fh.write("== %s\n" % dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        fh.flush()
        cmds = [_bt_cmd(), [sys.executable]]
        for i, cmd in enumerate(cmds):
            try:
                fh.write("실행: %s\n" % " ".join(cmd))
                fh.flush()
                t1 = time.time()
                p = subprocess.run(cmd + [script, "--from-cache"], cwd=BASE, stdout=fh, stderr=subprocess.STDOUT, env=env,
                                   timeout=3 * 3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                res = {"py": " ".join(cmd), "rc": p.returncode}
                quick = time.time() - t1 < BT_QUICK_FAIL
                if p.returncode != 0 and quick and i + 1 < len(cmds):
                    fh.write("\n%s 가 %.0f초 만에 코드 %s 로 끝남 — 서버 파이썬으로 다시\n" % (" ".join(cmd), time.time() - t1, p.returncode))
                    fh.flush()
                    continue
                break
            except FileNotFoundError as e:
                fh.write("실행기 없음 %s: %s — 서버 파이썬으로 다시\n" % (" ".join(cmd), e))
                fh.flush()
            except Exception as e:
                res = {"py": " ".join(cmd), "rc": None, "error": _no_secret("%s: %s" % (type(e).__name__, e))}
                break
    res.update(secs=round(time.time() - t0), at=dt.datetime.now().isoformat(timespec="seconds"))
    if res.get("rc") != 0:
        print("가속도 기저율 백테스트 실패:", res, "— 로그", log, flush=True)
    return res


def _druck_needs_net(c):
    """이 회사를 offline 으로 쌓을 때 DART 를 불러야 하나 — 원장 파일만 본다(DRK.needs_net: _fetch 와 같은 판정). 고유번호가 없으면 False(쌓으면 오류로 끝난다)."""
    corp = corp_code_of(c.get("code") or "")
    if not corp:
        return False
    years = sorted({int(r["stamp"][:4]) for r in c.get("reports") or []})
    return DRK.needs_net(corp, years, _druck_meta(c))


def _druck_prebuild(now=dt.datetime.now, run_bt=True):
    """전 종목 druck(offline) — _druck_order 순서로, 시작 뒤 처음 오는 06:00 에 멈춘다. 끝나면(멈춰도) 기저율 백테스트를 돌린다.
    DRUCK_PRE: done/total(회사) · fresh(이미 지금 sig) · built(새로 씀) · transient(일시 오류 · DART 예산 끝 — 안 씀) · failed · net(DART 받은 수)
    · skipped_budget(DART 예산이 바닥난 뒤, 원장을 새로 받아야 해서 건너뛴 회사 — 다음 밤. 받을 것이 없는 회사는 예산이 끝나도 계속 쌓는다)
    · per_co(새로 쌓은 회사당 초) · stopped('06:00' 이면 시간에 멈춤)
    · bt(백테스트 결과). 미캐시 결과는 DRUCK_SOFT 에 남기지 않는다. 이미 돌고 있으면 False."""
    with DRUCK_PRE_LOCK:
        if DRUCK_PRE["running"] or DRK is None:
            return False
        DRUCK_PRE["running"] = True
    t0, work = time.time(), 0.0
    try:
        start = now()
        stop = _druck_deadline(start)
        comps = list(INDEX["companies"])
        DRUCK_PRE.update(started=start.isoformat(timespec="seconds"), stop_at=stop.isoformat(timespec="seconds"), done=0, total=len(comps),
                         net=0, fresh=0, built=0, transient=0, failed=0, skipped_budget=0, per_co=None, stopped=None, bt=None, code=None)
        comps = _druck_order(comps, lambda code: bool(code) and os.path.exists(_druck_path(code)))     # 파일 확인 988번 — 드라이브라 몇 초 걸린다
        DRK.NET.update(budget=DRUCK_NET_BUDGET, used=0)
        for c in comps:
            if now() >= stop:
                DRUCK_PRE["stopped"] = "%02d:00" % DRUCK_PRE_STOP
                break
            code = c.get("code")
            DRUCK_PRE["code"] = code
            try:
                cur = _druck_read(code) if code else None
                if cur is not None and cur.get("sig") == _druck_sig(c):
                    DRUCK_PRE["fresh"] += 1
                elif DRK.NET["used"] >= DRUCK_NET_BUDGET and _druck_needs_net(c):
                    DRUCK_PRE["skipped_budget"] += 1      # DART 예산 끝 · 이 회사는 원장을 받아야 한다 — 쌓아도 transient(미캐시)라 다음 밤으로 미룬다
                else:
                    t1 = time.time()
                    res = druck(code, offline=True) if code else None
                    work += time.time() - t1
                    if not res or res.get("error"):
                        DRUCK_PRE["failed"] += 1
                    elif res.get("transient"):
                        DRUCK_PRE["transient"] += 1
                    else:
                        DRUCK_PRE["built"] += 1
                    if code and (not res or res.get("error") or res.get("transient")):
                        DRUCK_SOFT.pop(code, None)        # 미캐시 결과 기억은 화면 폴링용 — 밤새 988곳 몫이 32비트 뷰어 메모리에 쌓이지 않게
                    n = DRUCK_PRE["built"] + DRUCK_PRE["transient"] + DRUCK_PRE["failed"]
                    DRUCK_PRE["per_co"] = round(work / n, 2) if n else None
            except Exception as e:
                DRUCK_PRE["failed"] += 1
                print("가속도 밤 미리 계산 실패:", code, _no_secret("%s: %s" % (type(e).__name__, e)), flush=True)
            DRUCK_PRE["done"] += 1
            DRUCK_PRE["net"] = DRK.NET["used"]
        DRUCK_PRE["code"] = None
        if run_bt:
            DRUCK_PRE["bt"] = {"running": True}
            DRUCK_PRE["bt"] = _druck_run_bt()
    finally:
        DRK.NET.update(budget=None, used=0)
        DRUCK_PRE.update(running=False, at=now().isoformat(timespec="seconds"), secs=round(time.time() - t0))
    return True


def _druck_auto_loop():
    """매일 02:00(00:10 수집 뒤 · 06:30 저평가 전) — 색인을 새로 읽고(뷰어는 00:05 에 다시 켜져 수집 전 색인을 들고 있다)
    전 종목 가속도를 캐시 우선으로 미리 계산한 뒤 기저율 · 사건 파일을 다시 낸다."""
    while True:
        now = dt.datetime.now()
        nxt = now.replace(hour=DRUCK_PRE_AT[0], minute=DRUCK_PRE_AT[1], second=0, microsecond=0)
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        time.sleep(max(60, (nxt - now).total_seconds()))
        try:
            build_index()
        except Exception as e:
            print("가속도 밤 미리 계산 — 색인 실패(전 색인으로 돈다): %s" % e, flush=True)
        try:
            _druck_prebuild()
        except Exception as e:
            print("가속도 밤 미리 계산: %s" % e, flush=True)


# ---------------------------------------------------------------- 전 종목 미리 계산 — 풍경 · 궤도(2026-10-11)
# 도구/전종목_미리계산.py 를 뷰어 밖 자식 프로세스로(64비트 BT_PY, 안 되면 서버 파이썬) 창 없이 띄운다. 32비트 뷰어는 이미 500–600MB ·
# 'can't start new thread' 기록이 있어 안에서 돌리지 않는다. 상태는 그 프로세스가 쓰는 PREBUILD_DIR/state.json(뷰어를 다시 켜도 이어 본다),
# 회사 한 줄 로그는 run.log, 멈춤은 stop 파일(회사 사이 · 궤도는 보고서 몇 건마다 본다). 설계: docs/superpowers/specs/2026-10-11-prebuild-all-design.md
PREBUILD_DIR = os.environ.get("PREBUILD_DIR") or os.path.join(CACHE_DIR, "prebuild")
PREBUILD = {"proc": None, "py": None, "started": None, "error": None}
PREBUILD_LOCK = threading.Lock()
PREBUILD_AUTO_FROM, PREBUILD_AUTO_TO = (7, 0), (23, 30)    # 자동 이어 하기를 띄우는 때 — 밤 수집 · 02:00 druck · 06:30 공시목록/가격과 겹치지 않게
PREBUILD_ERR_WAIT = 3 * 3600    # 초 — 오류로 끝난 판은 이만큼 지난 뒤에만 자동으로 다시(한 시간마다 같은 오류로 뜨지 않게)


def _prebuild_path(name):
    return os.path.join(PREBUILD_DIR, name)


def _pid_alive(pid, since=None):
    """pid 프로세스가 살아 있나. since(에포크 초)를 주면 그보다 나중에 만들어진 프로세스(pid 재사용)는 남으로 본다."""
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)      # 전역 windll 의 argtypes 를 건드리지 않게 따로
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        rc = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(rc)) or rc.value != 259:    # STILL_ACTIVE
            return False
        if since:
            ft = [wintypes.FILETIME() for _ in range(4)]
            if k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
                made = ((ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime) / 1e7 - 11644473600
                if made > since + 5:
                    return False
        return True
    finally:
        k32.CloseHandle(h)


def _prebuild_state():
    """state.json — 없거나 깨졌으면 {}. 도구가 원자적으로 쓰지만 드라이브 동기화 중이면 한 번 더."""
    for i in range(2):
        try:
            with open(_prebuild_path("state.json"), "r", encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            time.sleep(0.2)
    return {}


def _iso_ts(s):
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _prebuild_alive(stt=None):
    """미리 계산 프로세스가 도나 — 이 뷰어가 띄운 손잡이(py 런처)가 살아 있거나, state 의 pid 가 그 시작 시각 전에 만든 프로세스로 살아 있다."""
    p = PREBUILD["proc"]
    if p is not None and p.poll() is None:
        return True
    stt = _prebuild_state() if stt is None else stt
    return _pid_alive(stt.get("pid"), _iso_ts(stt.get("started")))


def _prebuild_log_tail(n=8):
    try:
        with open(_prebuild_path("run.log"), "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 16384))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][-n:]


def prebuild_status():
    """GET /api/prebuild — state.json 그대로 + alive · running(프로세스가 도나) · log(run.log 꼬리 8줄) · stop_pending · launch_error.
    방금 띄워 아직 state 를 안 쓴 동안은 phase "start"."""
    stt = _prebuild_state()
    alive = _prebuild_alive(stt)
    out = dict(stt)
    p, t0 = PREBUILD["proc"], PREBUILD["started"]
    if alive and p is not None and p.poll() is None and t0 and (_iso_ts(stt.get("started")) or 0) < t0 - 2:
        out = {"v": 1, "phase": "start", "started": dt.datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
               "py": PREBUILD["py"], "land": {}, "orbit": {}, "dart": stt.get("dart") or {}}
    out.update(alive=alive, running=alive, log=_prebuild_log_tail(),
               stop_pending=os.path.exists(_prebuild_path("stop")), launch_error=PREBUILD["error"])
    return out


def _prebuild_spawn(cmd, first):
    """도구를 창 없이 띄운다. 실행기가 없으면(FileNotFoundError) False. 출력(import 실패 · 예외)은 stdout.log."""
    si = None
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0          # SW_HIDE
    os.makedirs(PREBUILD_DIR, exist_ok=True)
    with open(_prebuild_path("stdout.log"), "w" if first else "a", encoding="utf-8") as log:
        log.write("== %s 실행: %s\n" % (dt.datetime.now().isoformat(timespec="seconds"), " ".join(cmd)))
        log.flush()
        try:
            p = subprocess.Popen(
                cmd + [os.path.join(BASE, "도구", "전종목_미리계산.py")], cwd=BASE,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PREBUILD_DIR=PREBUILD_DIR), startupinfo=si,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError as e:
            log.write("실행기 없음: %s\n" % e)
            return False
    PREBUILD.update(proc=p, py=" ".join(cmd), started=time.time())
    return True


def _prebuild_watch(p):
    """64비트 실행기가 BT_QUICK_FAIL 초 안에 0 아닌 코드로 끝나면(py 런처 103 — 3.13 없음 · import 실패) 서버 파이썬으로 한 번 더."""
    try:
        rc = p.wait(timeout=BT_QUICK_FAIL)
    except subprocess.TimeoutExpired:
        return
    with PREBUILD_LOCK:
        if rc != 0 and PREBUILD["proc"] is p and not _prebuild_alive():
            try:
                if not _prebuild_spawn([sys.executable], False):
                    PREBUILD["error"] = "미리 계산을 띄우지 못했습니다(실행기 없음)"
            except Exception as e:
                PREBUILD["error"] = "미리 계산을 띄우지 못했습니다: %s" % e


def prebuild_run(auto=False):
    """미리 계산을 띄운다 — 이미 돌면 그대로(한 번에 하나). 반환: prebuild_status()."""
    with PREBUILD_LOCK:
        if _prebuild_alive():
            return prebuild_status()
        try:
            os.remove(_prebuild_path("stop"))
        except OSError:
            pass
        PREBUILD["error"] = None
        try:
            cmd = _bt_cmd()
            if _prebuild_spawn(cmd, True):
                if cmd != [sys.executable]:
                    threading.Thread(target=_prebuild_watch, args=(PREBUILD["proc"],), daemon=True).start()
            elif not _prebuild_spawn([sys.executable], False):
                PREBUILD["error"] = "미리 계산을 띄우지 못했습니다(실행기 없음)"
        except Exception as e:
            PREBUILD["error"] = "미리 계산을 띄우지 못했습니다: %s" % e
        if auto:
            print("전 종목 미리 계산 — 자동으로 이어 함(%s)" % PREBUILD["py"], flush=True)
    return prebuild_status()


def prebuild_stop():
    """돌고 있으면 stop 파일 — 도구가 회사 사이에서 보고 멈춘다. 안 돌면 state 에 stopped=user 만 남겨 자동 이어 하기를 막는다."""
    with PREBUILD_LOCK:
        stt = _prebuild_state()
        if _prebuild_alive(stt):
            os.makedirs(PREBUILD_DIR, exist_ok=True)
            with open(_prebuild_path("stop"), "w", encoding="utf-8") as fh:
                fh.write(dt.datetime.now().isoformat(timespec="seconds"))
        elif stt and stt.get("stopped") != "user":
            stt["stopped"] = "user"
            _atomic_json(_prebuild_path("state.json"), stt)
    return prebuild_status()


def _prebuild_should_resume(stt, now):
    """자동 이어 하기 — 끝나지 않았고(phase != done) 사용자가 멈춘 게 아니면. DART 상한으로 미룬 풍경(land.deferred)은 날짜가 바뀐 뒤에,
    07:00–23:30 밖이라 미룬 풍경(land.stop "time" — 도구가 창 밖에서는 DART 를 안 쓴다)은 창 안이면 같은 날에도.
    회사를 골라 돌린 판(codes) · state 가 없는 경우(한 번도 안 누름)는 띄우지 않는다. 오류로 끝난 판은 PREBUILD_ERR_WAIT 뒤에."""
    if not stt or stt.get("codes") or stt.get("stopped") == "user":
        return False
    if stt.get("stopped") == "error" and now.timestamp() - (_iso_ts(stt.get("at")) or 0) < PREBUILD_ERR_WAIT:
        return False
    if stt.get("phase") != "done":
        return True
    L = stt.get("land") or {}
    return bool(L.get("deferred")) and (L.get("stop") == "time" or (stt.get("dart") or {}).get("date") != now.date().isoformat())


def _prebuild_auto_loop():
    """뷰어가 켜지고 10분 뒤부터 한 시간마다 — 07:00–23:30 에만 띄운다."""
    time.sleep(600)
    while True:
        try:
            now = dt.datetime.now()
            if PREBUILD_AUTO_FROM <= (now.hour, now.minute) < PREBUILD_AUTO_TO:
                stt = _prebuild_state()
                if _prebuild_should_resume(stt, now) and not _prebuild_alive(stt):
                    prebuild_run(auto=True)
        except Exception as e:
            print("전 종목 미리 계산 자동 이어 하기: %s" % e, flush=True)
        time.sleep(3600)


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
    # 빈 분기 점도 그대로 받는다(분기 키 격자) — 값이 하나도 없는 분기만 실적 칸을 비운다
    pts = DRK.series(corp, c["code"], years, meta=_druck_meta(c), offline=True)

    def key_of(p):
        return "%d%02d" % (p["year"], p["q"] * 3) if mode == "q" else "%d12" % p["year"]

    actual = {}
    if mode == "q":
        for p in pts:
            vals = {"매출액": p.get("매출액"), "영업이익": p.get("영업이익"), "EPS": p.get("EPS")}
            if any(v is not None for v in vals.values()):
                actual[key_of(p)] = vals
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
    # 기준은 키로 찾는다 — 분기는 전년 같은 분기(YYYYMM 의 해 − 1), 연간은 전년. 칸 순번(4칸 전)은 빠진 분기가 있으면 다른 분기를 집는다.
    row_of = {r["key"]: r for r in rows}
    for r in rows:
        yy = {}
        prev_r = row_of.get("%d%s" % (int(r["key"][:4]) - 1, r["key"][4:]))
        for k in ("매출액", "영업이익", "EPS"):
            cur = (r["actual"] or {}).get(k)
            if cur is None:
                cur = (r["estimate"] or {}).get(k)
            if cur is None or prev_r is None:
                continue
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


# ---------------------------------------------------------------- 스크리닝
SCREEN_YEARS = 4          # 가속도는 전년 동기가 필요하다. 4년이면 충분.
SCREEN = {"rows": [], "done": 0, "total": 0, "running": False,
          "years": SCREEN_YEARS, "built": 0}
SCREEN_LOCK = threading.Lock()
SCORE_NOTE = "가중 50/30/20 — 검증 안 됨"     # score_rows 가중(가속(B) · 마진변화 · 재고감소)은 과거 성적으로 고른 값이 아니다


def screen_row(c):
    """회사 한 곳의 최신 분기 스크리닝 값. 데이터가 모자라면 None."""
    corp = corp_code_of(c["code"])
    if not corp or DRK is None:
        return None
    this_year = dt.date.today().year
    years = list(range(this_year - SCREEN_YEARS, this_year + 1))
    # 가속도 캐시(지금 버전)가 있으면 그것 — 가속(B) · 국면 · 변곡과 분할 보정 PER 이 가속도 탭과 같다.
    # 없으면 같은 순서(series → per_share → accel → attach_prices)로 여기서 짧게(최근 SCREEN_YEARS 년) 쌓는다. 캐시는 쓰지 않는다
    d_ = _druck_read(c["code"])
    if d_:
        pts = d_.get("points") or []
    else:
        meta = _druck_meta(c)
        pts = DRK.series(corp, c["code"], years, meta=meta, offline=True)
        sev = _share_events(c["code"])
        DRK.per_share(pts, sev)
        DRK.accel(pts)
        dates = {(p["year"], p["q"]): meta["filed"][p["n"]] for p in pts if meta["filed"].get(p["n"])}
        DRK.attach_prices(pts, c["code"], dates)
        DRK.hold_per(pts, DRK.split_after(pts, sev))        # 가속도 탭과 같이 — 마지막 분기 뒤 분할이면 PER 을 비운다
    # 순번이 아니라 분기 키(n)로 — 빈 분기 점(gap · fy)이 끼어도 '직전 분기' · '1년 전'이 다른 분기를 집지 않는다
    by = {p["n"]: p for p in pts if p.get("n") is not None}
    have = [p for p in pts if p.get("매출액") and p.get("n") is not None]
    if len(have) < 2:
        return None
    cur = have[-1]
    prev = by.get(cur["n"] - 1) or {}
    # 4분기 합 순이익 — 연속된 네 분기(키)일 때만
    w4 = [by.get(m) for m in range(cur["n"] - 3, cur["n"] + 1)]
    ni_ttm = (sum(x["당기순이익"] for x in w4)
              if all(x is not None and x.get("당기순이익") is not None for x in w4) else None)
    inv_delta = None
    if cur.get("재고일수") is not None and prev.get("재고일수") is not None:
        inv_delta = cur["재고일수"] - prev["재고일수"]

    # 가속 전환 = 가속(B)이 앞 분기 음(−)에서 이번 분기 +3%p 이상으로 바뀐 분기(변곡 ▲) — 가속도 탭과 같은 판정.
    # '덜 나빠짐'도 잡으니 역성장 중인 회사(속도 < 0)와 성장 회사는 갈라놓는다.
    turned = cur.get("변곡") == "▲"
    kind = ("성장" if (cur.get("속도") or 0) >= 0 else "역성장완화") if turned else None

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
        "매출YoY": cur.get("매출YoY"), "매출가속": cur.get("매출가속"),     # 매출가속 = 분기 YoY 의 전분기 차(C) — 시너지 rev_accel 이 읽는다
        "전분기가속": prev.get("매출가속"),
        "가속B": cur.get("가속B"), "속도": cur.get("속도"), "국면": cur.get("국면"), "변곡": cur.get("변곡"),
        "영업이익률": cur.get("영업이익률"), "마진변화": cur.get("이익률변화"),
        "이익률_비정상": bad,
        "재고일수": cur.get("재고일수"), "재고일수변화": inv_delta,
        "PER_TTM": cur.get("PER_TTM"), "순이익_TTM": ni_ttm,
        "매출_TTM_1년전": (by.get(cur["n"] - 4) or {}).get("매출_TTM"),
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
    """가속(B) / 마진변화 / 재고일수 감소를 백분위로 환산해 가중합(50/30/20 — 이 가중은 검증하지 않았다, SCORE_NOTE).
    행의 '매출가속'(C)은 순위에 쓰지 않는다(시너지용으로만 남는다)."""
    if len(rows) < 3:
        for r in rows:
            r["score"] = None
        return rows
    # 지주회사처럼 이익률이 의미 없는 곳은 마진 항목만 빼고 순위를 매긴다
    def margin_of(r):
        return None if r.get("이익률_비정상") else r.get("마진변화")

    ranks = {
        "가속B": _pct_rank([r.get("가속B") for r in rows]),
        "마진변화": _pct_rank([margin_of(r) for r in rows]),
        # 재고일수는 줄어드는 쪽이 좋다. 부호를 뒤집어 순위를 매긴다.
        "재고감소": _pct_rank([(-r["재고일수변화"])
                            if r.get("재고일수변화") is not None else None
                            for r in rows]),
    }
    W = {"가속B": 0.50, "마진변화": 0.30, "재고감소": 0.20}
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
                "running": SCREEN["running"], "years": SCREEN_YEARS,
                "score_note": SCORE_NOTE}


# ---------------------------------------------------------------- 시너지 발굴
# 수주잔고(선행) · 매출 가속(전환) · 최근 수주 공시(확인) · 주가 반영도(가격)를
# 한 줄에 세운다. 시너지.py 참조.
SYNERGY = {"running": False, "done": 0, "total": 0, "rows": [], "at": 0,
           "phase": "", "window": 0}
SYNERGY_LOCK = threading.Lock()
SYN_WINDOW = 40           # 최근 수주 공시를 훑는 기간(일). 전 종목 공시라 더 길면 느리다.
BAD_FLAG = {"희석": "전환사채·신주인수권부사채 발행", "유동성 위험": "유동성 위험 공시",
            "감사 문제": "감사의견 문제", "상장 위험": "상장 관련 위험", "소송·제재": "소송·제재"}


_UNIV = {}


def _universe_info():
    """종목.txt 주석에 적힌 시장·시가총액 스냅샷. ({code: {...}}, 'YYYYMMDD')
    '005930   #   1위 삼성전자 (KOSPI, 시총 16,077,266억)'"""
    p = os.path.join(BASE, "종목.txt")
    if _UNIV.get("mtime") == (os.path.getmtime(p) if os.path.exists(p) else None):
        return _UNIV["rows"], _UNIV["snap"]
    rows, snap = {}, None
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8", errors="replace"):
            m = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", ln)
            if ln.startswith("#") and m and not snap:
                snap = "".join(m.groups())
            m = re.match(r"^([0-9][0-9A-Z]{5})\s*#\s*(\d+)위\s+.*\((KOSPI|KOSDAQ),\s*시총\s*([\d,]+)억\)", ln)
            if m:
                rows[m.group(1)] = {"rank": int(m.group(2)), "market": m.group(3),
                                    "cap": float(m.group(4).replace(",", "")) * 1e8}
    _UNIV.update(mtime=os.path.getmtime(p) if os.path.exists(p) else None, rows=rows, snap=snap)
    return rows, snap


_NAMES = {}
_NAMES_EN = {}        # {"idx": 밸류체인.EnNames} — 영문만 적힌 매입처 · 고객을 상장사로(_listed_names 가 같이 채운다)


_LATIN_KO = {"a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프", "g": "지",
             "h": "에이치", "i": "아이", "j": "제이", "k": "케이", "l": "엘", "m": "엠", "n": "엔",
             "o": "오", "p": "피", "q": "큐", "r": "알", "s": "에스", "t": "티", "u": "유",
             "v": "브이", "w": "더블유", "x": "엑스", "y": "와이", "z": "지"}


def _norm_corp(nm):
    """회사명 맞추기용. 계약 공시는 상대방을 한글 법인명('엘아이지디펜스앤에어로스페이스(주)')
    으로, 상장사 목록은 영문 약자('LIG디펜스앤에어로스페이스')로 적는다. 영문 글자를 한글
    읽기로 바꿔 양쪽을 같은 모양으로 만든다."""
    n = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|\s+|[·ㆍ\.,&]", "", nm or "").lower()
    return re.sub(r"[a-z]", lambda m: _LATIN_KO[m.group(0)], n)


def _listed_names():
    """정규화한 회사명 → 종목코드. 계약 공시의 '계약상대'를 상장사로 이어 주는 데 쓴다.
    수집 대상 이름과 DART 고유번호 목록(상장사만)의 공식 이름을 둘 다 넣는다 — 같은 이름이 둘이면 modify_date 최신
    (옛 상폐 corp 이 종목코드를 단 채 남아 있다: 삼성물산 000830 · 028260). 영문 이름 색인(_NAMES_EN, 밸류체인 매입처)도 같이 짠다."""
    if _NAMES:
        return _NAMES
    for c in INDEX["companies"]:
        _NAMES[_norm_corp(c["name"])] = c["code"]
    path = os.path.join(CACHE_DIR, "CORPCODE.xml")
    rows = []
    if os.path.exists(path):
        text = open(path, "rb").read().decode("utf-8", errors="replace")
        for m in re.finditer(r"<list>(.*?)</list>", text, re.S):
            blob = m.group(1)
            g = lambda k: html.unescape((re.search(r"<%s>(.*?)</%s>" % (k, k), blob, re.S) or [None, ""])[1].strip())     # noqa: E731
            if g("stock_code"):
                rows.append((g("stock_code"), g("corp_name"), g("corp_eng_name"), g("modify_date")))
        del text
    for sc, nm, _en, _md in sorted(rows, key=lambda r: r[3] or "", reverse=True):
        _NAMES.setdefault(_norm_corp(nm), sc)
    if VCM is not None:
        _NAMES_EN["idx"] = VCM.EnNames(rows)
    return _NAMES


def _won_txt(v):
    return ("%.1f조" % (v / 1e12)) if abs(v) >= 1e12 else ("%.0f억" % (v / 1e8))


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
    univ, snap = _universe_info()
    u = univ.get(b["code"], {})
    ps = SYN.price_stats(prices, snap)
    p1y, p3m, pnow = ps.get("p1y"), ps.get("p3m"), ps.get("now")
    # 시가총액 = 종목.txt 의 네이버 시총 스냅샷 × 그 뒤 주가 변화(분할 보정)
    cap = u.get("cap")
    if cap and ps.get("since_snap"):
        cap = cap * ps["since_snap"]

    # 마지막 정기보고서 이후 새로 공시된 수주 계약
    last_rep = (b["points"][-1].get("rcept") or "")[:8]
    news = []
    for x in good_by.get(b["code"], []):
        if x["date"] <= last_rep:
            continue
        ci = SYN.contract(FIN.API_KEY, x["rcept"]) or {}
        # 계약상대가 상장사면 이어 준다 — 발주하는 쪽의 투자 사이클을 따라가기 위해
        pc = _listed_names().get(_norm_corp(ci.get("party") or ""))
        news.append(dict(ci, date=x["date"], report=x["report"], url=x["url"],
                         subsidiary="자회사" in x["report"],
                         party_code=pc if pc and pc != b["code"] else None))
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
    elif tr.get("last_switch"):
        why_not = "최신 잔고를 읽은 방식이 바뀌며(%s) 한 분기에 %.1f배가 됐다 (추출 오류 의심)" % (
            tr.get("last_method") or "?", last / tr["prev_value"] if tr.get("prev_value") else 0)
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
        # 잔고/연매출 배수의 1년 변화 — 잔고가 매출보다 빨리 불어나나. 잔고 지표 중 앞뒤 기간 모두 고르게 맞았다
        "cover_chg": (cover - b1 / sr["매출_TTM_1년전"]) if (cover is not None and b1 is not None and sr.get("매출_TTM_1년전")) else None,
        "rev_ttm": rev, "rev_yoy": sr.get("매출YoY"), "rev_accel": sr.get("매출가속"),
        "margin": sr.get("영업이익률"),
        # 4분기 합 — 한 분기 반짝 흑자·기저효과에 흔들리지 않는다(가온칩스 2026Q2: 분기 +1.5%, 4분기 합 영업손실 −91억)
        "op_ttm": sr.get("영업이익_TTM"), "ni_ttm": sr.get("순이익_TTM"),
        "margin4": (sr["영업이익_TTM"] / rev * 100) if (rev and sr.get("영업이익_TTM") is not None) else None,
        "loss4": bool((sr.get("영업이익_TTM") is not None and sr["영업이익_TTM"] <= 0)
                      or (sr.get("순이익_TTM") is not None and sr["순이익_TTM"] <= 0)),
        "margin_delta": None if sr.get("이익률_비정상") else sr.get("마진변화"),
        "per": sr.get("PER_TTM"), "quarter": sr.get("quarter"),
        "price": pnow, "price_1y": p1y, "price_3m": p3m, "price_1m": ps.get("p1m"),
        "dd52": ps.get("dd52"), "cap": cap, "market": u.get("market"), "cap_rank": u.get("rank"),
        "themes": ((sector_map() or {}).get("stocks", {}).get(b["code"].upper(), {})
                   .get("themes") or [])[:6],
        "parties_listed": [], "customer_of": [], "peers": [], "questions": [],
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
        # 연결 — 계약상대(발주처)가 상장사면 양쪽에 이어 준다
        by_code = {r["code"]: r for r in rows}
        name_of = {c["code"]: c["name"] for c in INDEX["companies"]}
        for r in rows:
            seen = set()
            for ct in r["new_contracts"]:
                pc = ct.get("party_code")
                if not pc or pc in seen:
                    continue
                seen.add(pc)
                r["parties_listed"].append({"code": pc, "name": name_of.get(pc) or ct.get("party"),
                                            "in_list": pc in by_code})
                if pc in by_code:
                    by_code[pc]["customer_of"].append({
                        "supplier": r["name"], "supplier_code": r["code"],
                        "title": ct.get("title"), "amount": ct.get("amount"),
                        "amount_txt": _won_txt(ct["amount"]) if ct.get("amount") else "?"})
        # 같은 업종 동료 — 잔고를 믿을 수 있는 곳끼리, 반영 갭 큰 순
        ind = {}
        for r in rows:
            if r["reliable"] and r["industry"] != "분류없음":
                ind.setdefault(r["industry"], []).append(r)
        for r in rows:
            peers = [p for p in ind.get(r["industry"], []) if p is not r]
            peers.sort(key=lambda p: (p["gap"] if p["gap"] is not None else -999), reverse=True)
            r["peers"] = [{"code": p["code"], "name": p["name"], "stage": p["stage"],
                           "backlog_yoy": p["backlog_yoy"], "price_1y": p["price_1y"],
                           "gap": p["gap"], "score": p["score"]} for p in peers[:5]]
            r["questions"] = SYN.questions(r, peers)
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
               reliable=sum(1 for r in rows if r["reliable"]),
               rec=getattr(SYN, "SYN_REC", []))       # 추천필터 — 정의는 시너지.py 한 곳
    bt = _syn_bt()
    if bt:          # 화면의 '과거 검증' 상자 — 도구/시너지_백테스트.py 결과
        out["bt"] = {k: bt.get(k) for k in ("dates", "stages", "no_slow", "n", "firms", "median", "at", "rec")}
        out["bt"]["factors"] = {k: v for k, v in (bt.get("terciles") or {}).items()}
    return out


_EXP = {"mt": None, "d": None}


def export_view():
    """수출 추적 — 수출추적.py 전체 실행이 남긴 결과를 그대로 낸다(관세청 호출은 서버가 하지 않는다)."""
    p = os.path.join(CACHE_DIR, "수출추적", "result.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {"error": "아직 결과가 없다 — python 수출추적.py 전체 (관세청 API, 1시간 안팎)"}
    if _EXP["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            return {"error": "결과 파일을 읽지 못했다(쓰는 중일 수 있다) — 잠시 뒤 다시"}
        smap = (sector_map() or {}).get("stocks", {})
        users = {}
        for x in d.get("items", []):
            x["industry"] = (smap.get(x["code"].upper(), {}) or {}).get("industry") or ""
            for ch in x.get("channels") or []:
                users.setdefault((ch["sgg"], ch["hs"]), []).append(x["name"])
            cov = (x.get("validation") or {}).get("coverage")
            if cov is not None and (cov < 5 or cov > 150):       # 수출추적._grade 와 같은 문턱 — 중간 결과에도 적용
                x["grade"] = "C"
            # 분기 맞춤(2026-10-02) — 상태 · '이번 분기' · '직전 분기' · 가속을 공시 분기에 맞춰 다시 낸다(예전 '최근 3개월'은 분기를 섞었다)
            if EXPM is not None and x.get("signals") and (x.get("series_long") or x.get("series")):
                v_ = x.get("validation") or {}
                al = EXPM.aligned(x.get("series_long") or x["series"], v_.get("last_rev_q"), v_.get("pairs"))
                if al:
                    x["signals_old"] = dict(x["signals"])
                    x["signals"].update(y3=al["cur"], y3p=al["prev"], acc=al["acc"], state=al["state"])
                    x["aligned"] = al
        for x in d.get("items", []):     # 같은 (시군구 × 품목)을 쓰는 다른 회사 — 지주·자회사, 같은 동네 경쟁사
            sh = set()
            for ch in (x.get("channels") or [])[:3]:
                sh |= set(users.get((ch["sgg"], ch["hs"]), [])) - {x["name"]}
            x["shared_with"] = sorted(sh)[:4]
        d["n_all"] = len(INDEX.get("companies", []))       # 화면 맨 위 단계 숫자(수집 전체 → 거점 → 통로 → 믿을 만함)
        _EXP.update(mt=mt, d=d)
    return _EXP["d"]


# ---------------------------------------------------------------- 수출 추적 매달 자동 갱신
# 관세청은 매달 15일께 지난달 치를 낸다. 켜 두면 매일 00:10(밤 공시 수집과 같은 때) 깨어나, 결과에 지난달 치가 없으면
# 큰 통로 몇 개로 '나왔나'를 떠보고(관세청 1~3건), 나왔으면 수출추적.py 갱신을 따로 띄운다.
# 상태는 .cache/수출추적/auto.json, 진행은 progress.json(수출추적.update 가 쓴다).
try:
    _xspec = _ilu.spec_from_file_location("수출추적", os.path.join(BASE, "수출추적.py"))
    EXPM = _ilu.module_from_spec(_xspec)
    _xspec.loader.exec_module(EXPM)
except Exception as _e:
    EXPM = None
    print("수출추적 모듈 로드 실패:", _e)

try:
    _mspec = _ilu.spec_from_file_location("거시", os.path.join(BASE, "거시.py"))
    MACRO = _ilu.module_from_spec(_mspec)
    _mspec.loader.exec_module(MACRO)
except Exception as _e:
    MACRO = None
    print("거시 모듈 로드 실패:", _e)

EXP_DIR = os.path.join(CACHE_DIR, "수출추적")
EXP_AUTO_PATH = os.path.join(EXP_DIR, "auto.json")
EXP_AUTO_LOCK = threading.Lock()
EXP_PROC = {"p": None}
EXP_CHECK_EVERY = 20 * 3600     # 하루 한 번(아래 EXP_DAILY_AT) 깨어날 때마다 묻도록 — 20시간이 지났으면 묻는다
EXP_DAILY_AT = (0, 10)          # 밤 공시 수집(작업 스케줄러 GiupChujeok_Collect 00:10)과 같은 때


def _exp_auto_load():
    try:
        with open(EXP_AUTO_PATH, "r", encoding="utf-8") as fh:
            a = json.load(fh)
    except Exception:
        a = {}
    a.setdefault("on", True)
    return a


def _exp_auto_save(a):
    os.makedirs(EXP_DIR, exist_ok=True)
    tmp = EXP_AUTO_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(a, fh, ensure_ascii=False)
    os.replace(tmp, EXP_AUTO_PATH)


def _exp_prog():
    p = os.path.join(EXP_DIR, "progress.json")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            g = json.load(fh)
        g["_age"] = time.time() - os.path.getmtime(p)
        return g
    except Exception:
        return {}


def _exp_running():
    p = EXP_PROC["p"]
    if p is not None and p.poll() is None:
        return True
    g = _exp_prog()     # 뷰어를 다시 켜 손잡이를 잃었어도 진행 파일이 15분 안에 바뀌었으면 도는 중
    return g.get("state") == "running" and g.get("_age", 1e9) < 900


def _exp_spawn(month):
    # 창 없이 — pythonw(콘솔 없는 파이썬) + CREATE_NO_WINDOW + 숨김 시작. 작업 중인 화면에 cmd 창이 뜨면 안 된다
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    si = None
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0          # SW_HIDE
    os.makedirs(EXP_DIR, exist_ok=True)
    with open(os.path.join(EXP_DIR, "run.log"), "a", encoding="utf-8") as log:
        log.write("\n== 자동 갱신 %s · %s치\n" % (dt.datetime.now().isoformat(timespec="minutes"), month))
        log.flush()
        EXP_PROC["p"] = subprocess.Popen(
            [exe, os.path.join(BASE, "수출추적.py"), "갱신", month], cwd=BASE,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"), startupinfo=si,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _exp_tick(force=False):
    """지난달 치가 결과에 없으면 관세청이 냈는지 떠보고, 나왔으면 갱신을 띄운다. force = '지금 확인' 단추."""
    if EXPM is None:
        return
    with EXP_AUTO_LOCK:
        a = _exp_auto_load()
        if not (a["on"] or force) or _exp_running():
            return
        g = _exp_prog()
        if g.get("state") in ("done", "quota", "error") and g.get("at") != a.get("seen"):     # 끝난 갱신은 한 번만 적는다
            a["seen"] = g["at"]
            a["last"] = {k: g.get(k) for k in ("state", "month", "want", "msg", "at", "started", "n", "ch")}
            if g["state"] == "quota":           # 하루 한도 — 자정 넘어 이어서(이미 부른 응답은 캐시)
                t = dt.datetime.now() + dt.timedelta(days=1)
                a["retry_after"] = t.replace(hour=0, minute=10, second=0).timestamp()
            elif g["state"] == "error" or (g.get("month") or "") < (g.get("want") or ""):
                a["retry_after"] = time.time() + 24 * 3600
            else:
                a.pop("retry_after", None)
        d = export_view()
        have = None if d.get("error") else EXPM.data_month(d)
        want = EXPM._months_back(1)
        a.update(have=have, want=want)
        now = time.time()
        if have and have >= want:
            a["check"] = "최신"
        elif force or (now >= (a.get("retry_after") or 0) and now - (a.get("checked_at") or 0) >= EXP_CHECK_EVERY):
            ok = EXPM.available(want, EXPM.probe_targets({} if d.get("error") else d))
            a.update(checked_at=now, check="나옴" if ok else "아직")
            if ok:
                a.pop("retry_after", None)
                _exp_spawn(want)
        _exp_auto_save(a)


def _exp_auto_loop():
    """뷰어가 켜질 때 한 번(PC 가 꺼져 있어 놓친 날을 채운다), 그 뒤로는 매일 00:10(밤 공시 수집과 같은 때) 한 번."""
    time.sleep(90)          # 색인이 먼저
    while True:
        try:
            _exp_tick()
        except Exception as e:
            print("수출 추적 자동 갱신: %s" % e, flush=True)
        n = dt.datetime.now()
        nxt = n.replace(hour=EXP_DAILY_AT[0], minute=EXP_DAILY_AT[1], second=0, microsecond=0)
        if nxt <= n:
            nxt += dt.timedelta(days=1)
        time.sleep(max(60, (nxt - n).total_seconds()))


def exp_auto_view():
    a = _exp_auto_load()
    run = _exp_running()
    d = export_view()
    out = {k: a.get(k) for k in ("on", "check", "checked_at", "retry_after", "last")}
    out.update(running=run, prog=_exp_prog() if run else None,
               have=None if d.get("error") or EXPM is None else EXPM.data_month(d),
               want=EXPM._months_back(1) if EXPM else None, every=EXP_CHECK_EVERY)
    return out


_SYN_BT = {"mt": None, "d": None}


def _syn_bt():
    p = os.path.join(CACHE_DIR, "시너지", "bt_report.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _SYN_BT["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _SYN_BT["d"] = json.load(fh)
            _SYN_BT["mt"] = mt
        except Exception:
            return None
    return _SYN_BT["d"]


def financials(c, rep, base_kind=None):
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

    base, kind = base_kind if base_kind else baseline_for(c, rep)
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


# ---------------------------------------------------------------- 궤도 요약 캐시(2026-10-11)
# brief 캐시가 다 있어도 /api/orbit 이 매번 brief JSON 을 전부 읽어 5초 안팎(KB금융 103건 · 구글 드라이브 읽기).
# 회사별로 행(orbit_scale 전 값)을 한 파일 .cache/orbit/{code}.json 에 모은다. sig = ORBIT_SUM_V | GIST_V | 보고서 rcept 목록 해시 —
# 새 보고서 · 요약 규칙(GIST_V)이 바뀌면 무효. 모든 보고서에 brief 와 지금 판 gist 가 있을 때만 쓴다(뷰어 · 미리 계산 도구).
ORBIT_SUM_V = 1
ORBIT_ROW_KEYS = ("score", "kind", "top", "tags", "changed", "first", "vol", "add_chars", "rem_chars", "numeric", "gist")


def _orbit_sum_path(code):
    return os.path.join(CACHE_DIR, "orbit", code + ".json")


def _orbit_sum_sig(c):
    h = hashlib.sha1("|".join(r["rcept"] for r in c["reports"]).encode("utf-8")).hexdigest()[:16]
    return "%d|%d|%d|%s" % (ORBIT_SUM_V, GIST_V, len(c["reports"]), h)


def _orbit_row(rep, b, gist=None):
    """brief 한 건 → 궤도 행(orbit_scale 전). b 가 깨졌으면 KeyError."""
    secs = b["sections"]
    return {
        "stamp": rep["stamp"], "label": rep["label"],
        "tag": rep["tag"], "rcept": rep["rcept"],
        "score": b["score"], "kind": b["kind"],
        "top": secs[0]["section"] if secs else "", "tags": b["tags"],
        "changed": len(secs),
        "first": b.get("first", False),
        # 중요도를 곱한 '새로 쓴 분량'(글자). 점수는 이것의 섹션별 제곱근 합이다.
        "vol": round(sum(s["weight"] * (s["added_chars"] + 0.6 * s["removed_chars"])
                         for s in secs)),
        "add_chars": sum(s["added_chars"] for s in secs),
        "rem_chars": sum(s["removed_chars"] for s in secs),
        "numeric": sum(s.get("numeric", 0) for s in secs),
        "gist": gist,
    }


def _orbit_sum_rows(c):
    """요약 파일이 지금 보고서 목록 · GIST_V 와 맞으면 행(orbit_scale 전, 보고서 순서), 아니면 None.
    stamp · label · tag 는 색인 값을 쓴다(요약에는 rcept 와 brief 에서 나온 값만)."""
    try:
        with open(_orbit_sum_path(c["code"]), "r", encoding="utf-8") as fh:
            s = json.load(fh)
    except (OSError, ValueError):
        return None
    got = s.get("rows") or []
    if s.get("v") != ORBIT_SUM_V or s.get("sig") != _orbit_sum_sig(c) or len(got) != len(c["reports"]):
        return None
    rows = []
    for rep, r in zip(c["reports"], got):
        if r.get("rcept") != rep["rcept"]:
            return None
        row = {"stamp": rep["stamp"], "label": rep["label"], "tag": rep["tag"], "rcept": rep["rcept"]}
        row.update((k, r.get(k)) for k in ORBIT_ROW_KEYS)
        rows.append(row)
    return rows


def _orbit_sum_write(c, rows):
    keep = [dict([("rcept", r["rcept"])] + [(k, r.get(k)) for k in ORBIT_ROW_KEYS]) for r in rows]
    return _atomic_json(_orbit_sum_path(c["code"]), {"v": ORBIT_SUM_V, "sig": _orbit_sum_sig(c), "code": c["code"], "rows": keep})


def _orbit_collect(c, deadline=None):
    """brief 들을 읽어 행(orbit_scale 전)을 만든다. gist 는 deadline(에포크 초) 전까지만 여기서 뽑는다(None = 끝까지).
    돌려줌 (rows, have, current) — current = 모든 보고서에 brief 와 지금 판 gist 가 있다(요약을 써도 된다)."""
    rows, have, current = [], 0, True
    for rep in c["reports"]:
        p = brief_path(c["code"], rep["rcept"])
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    b = json.load(fh)
                have += 1                   # 읽힌 파일은 센다(모양이 깨져도 — 예전 그대로, 화면이 '쌓는 중'에 갇히지 않게)
                row = _orbit_row(rep, b)
                row["gist"] = _gist_of(c, rep, b, p, deadline is None or time.time() < deadline)
                rows.append(row)
                if b.get("gist_v") != GIST_V:
                    current = False
                continue
            except Exception:
                pass
        current = False
        rows.append({"stamp": rep["stamp"], "label": rep["label"],
                     "tag": rep["tag"], "rcept": rep["rcept"],
                     "score": None, "kind": "", "top": "", "tags": {},
                     "changed": 0, "first": False, "vol": None, "gist": []})
    return rows, have, current


def orbit(code):
    """보고서별 변화 점수 시계열. 캐시된 것만 모아 준다. 요약(_orbit_sum_rows)이 맞으면 brief 파일을 하나도 열지 않는다."""
    c = company_by_code(code)
    if not c:
        return None
    rows = _orbit_sum_rows(c)
    if rows is not None:
        orbit_scale(rows)
        n = len(rows)
        return {"rows": rows, "done": n, "total": n, "finished": True, "gist_pending": 0}
    # 요약은 잠깐만 여기서 뽑고 나머지는 뒤에서 — 첫 화면이 오래 멈추지 않게
    rows, have, current = _orbit_collect(c, time.time() + 1.0)
    if current:
        _orbit_sum_write(c, rows)
    orbit_scale(rows)
    if (any(r.get("score") is not None and r.get("gist") is None for r in rows)
            and not GISTING.get(code)):
        GISTING[code] = True
        threading.Thread(target=_run_gists, args=(code,), daemon=True).start()

    st = BUILDING.get(code, {})
    if have < len(c["reports"]) and not st.get("running"):
        BUILDING[code] = {"running": True, "done": have,
                          "total": len(c["reports"])}
        t = threading.Thread(target=_run_orbit, args=(code,), daemon=True)
        t.start()
    return {"rows": rows,
            "done": max(have, st.get("done", 0)),
            "total": len(c["reports"]),
            "finished": have >= len(c["reports"]),
            "gist_pending": sum(1 for r in rows
                                if r.get("score") is not None and r.get("gist") is None)}


# 평소(같은 종류 보고서의 중앙값) 대비 몇 배를 새로 썼나. 경계는 보고서 728건 분포로 잡았다:
# 1.5배 이상이 상위 약 16%, 2배 이상이 상위 약 4%.
ORBIT_TIERS = [(2.0, "격변"), (1.5, "큼"), (0.6, "평소"), (0.0, "조용")]


def orbit_scale(rows):
    """사업보고서는 원래 분기보다 길어 늘 점수가 높다. 종류별 중앙값으로 나눠 '평소 대비 배수'로 맞춘다."""
    def med(v):
        v = sorted(v)
        if not v:
            return None
        m = len(v) // 2
        return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2

    ok = [r for r in rows if r.get("vol") and not r["tag"] and not r["first"]]
    overall = med([r["vol"] for r in ok])
    base = {}
    for lab in {r["label"] for r in rows}:
        v = [r["vol"] for r in ok if r["label"] == lab]
        base[lab] = med(v) if len(v) >= 3 else overall
    for r in rows:
        m = base.get(r["label"])
        r["norm"] = round(m) if m else None
        if r.get("vol") is None or r["first"] or not m:
            r["x"], r["tier"] = None, ("기준" if r["first"] else None)
            continue
        r["x"] = round(r["vol"] / m, 2)
        r["tier"] = next(n for t, n in ORBIT_TIERS if r["x"] >= t)


GISTING = {}


def _run_gists(code):
    """캐시된 브리핑마다 한 줄 요약을 뽑아 붙인다. 궤도 화면이 폴링하며 채워 간다."""
    try:
        c = company_by_code(code)
        for rep in (c["reports"] if c else []):
            p = brief_path(code, rep["rcept"])
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    b = json.load(fh)
            except Exception:
                continue
            if b.get("gist_v") != GIST_V:
                _gist_of(c, rep, b, p)
    finally:
        GISTING[code] = False


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


# ---------------------------------------------------------------- 섹션 궤적
# 같은 섹션을 '같은 종류 직전 보고서'와 견준다. 분기·반기·사업보고서는 서식이 달라
# 섞어서 이으면 변화가 부풀려진다. 유사도·분량·한 줄 요약을 .cache/traj/{code}.json 에 쌓는다.
TRAJ_V = 2
TRAJ_NUM = re.compile(r"[-△▲]?\d[\d,.]*")
TRAJ = {}
TRAJ_LOCK = threading.Lock()
TRAJING = {}


def _traj_path(code):
    return os.path.join(CACHE_DIR, "traj", code + ".json")


def _traj_cache(code):
    with TRAJ_LOCK:
        d = TRAJ.get(code)
        if d is None:
            try:
                with open(_traj_path(code), "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                if d.get("v") != TRAJ_V:
                    d = None
            except Exception:
                d = None
            d = d or {"v": TRAJ_V, "chars": {}, "sim": {}, "line": {}}
            TRAJ[code] = d
        return d


def _traj_save(code):
    with TRAJ_LOCK:
        d = TRAJ.get(code)
        if d is None:
            return
        path = _traj_path(code)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            pass


def traj_pairs(c, norm, labels=None):
    """(같은 종류 직전 보고서, 이 보고서) 쌍. 종류마다 첫 보고서는 견줄 짝이 없다. 정정 공시는 뺀다."""
    last, out = {}, []
    for h in section_history(c, norm, labels):
        if h["tag"]:
            continue
        out.append((last.get(h["label"]), h))
        last[h["label"]] = h
    return out


def _traj_fill(c, norm, pairs, d, deadline=None, lines=True):
    """빈 칸(분량·유사도, lines 면 한 줄 요약)을 채운다. (바뀐 게 있나, 다 채웠나)."""
    changed = False
    for b, h in pairs:
        if deadline and time.time() > deadline:
            return changed, False
        kc = norm + "|" + h["rcept"]
        if kc not in d["chars"]:
            n = len(read_section(c, report_of(c, h["rcept"]), h["file"]))
            with TRAJ_LOCK:
                d["chars"][kc] = n
            changed = True
        if b is None:
            continue
        kp = norm + "|" + b["rcept"] + "|" + h["rcept"]
        if kp not in d["sim"]:
            # 숫자는 가리고 견준다 — 금액·날짜만 갱신한 문단까지 '다시 썼다'고 세면 평소가 40%대로 부푼다
            A = [TRAJ_NUM.sub("#", x) for x in blocks(read_section(c, report_of(c, b["rcept"]), b["file"]))]
            B = [TRAJ_NUM.sub("#", x) for x in blocks(read_section(c, report_of(c, h["rcept"]), h["file"]))]
            v = round(difflib.SequenceMatcher(None, A, B, autojunk=False).ratio() * 100, 1)
            with TRAJ_LOCK:
                d["sim"][kp] = v
            changed = True
    if not lines:
        return changed, True
    for b, h in pairs:
        if b is None:
            continue
        if deadline and time.time() > deadline:
            return changed, False
        kp = norm + "|" + b["rcept"] + "|" + h["rcept"]
        if (d["line"].get(kp) or {}).get("v") != GIST_V:
            try:
                ln = _section_line(c, report_of(c, b["rcept"]), report_of(c, h["rcept"]),
                                   b["file"], h["file"], norm, set())
            except Exception as e:
                print("궤적 요약 실패 %s %s: %s" % (c["code"], kp, e), flush=True)
                ln = None
            with TRAJ_LOCK:
                d["line"][kp] = {"v": GIST_V, "ln": ln}
            changed = True
    return changed, True


def _run_traj(code, norm, labels):
    key = code + "|" + norm
    try:
        c = company_by_code(code)
        if c:
            d = _traj_cache(code)
            pairs = traj_pairs(c, norm, labels)
            # 분량·유사도 먼저 다 채우고(그림이 먼저 선다), 요약은 그다음
            _traj_fill(c, norm, pairs, d, lines=False)
            _traj_save(code)
            for i in range(0, len(pairs), 8):
                _traj_fill(c, norm, pairs[i:i + 8], d)
                _traj_save(code)
    finally:
        TRAJING[key] = False


def traj_view(code, norm, labels=None):
    c = company_by_code(code)
    if not c:
        return None
    pairs = traj_pairs(c, norm, labels)
    d = _traj_cache(code)
    key = code + "|" + norm
    if not TRAJING.get(key):
        changed, _ = _traj_fill(c, norm, pairs, d, deadline=time.time() + 1.2, lines=False)
        if changed:
            _traj_save(code)
    rows, pending = [], 0
    for b, h in pairs:
        row = {"stamp": h["stamp"], "label": h["label"], "rcept": h["rcept"],
               "chars": d["chars"].get(norm + "|" + h["rcept"]),
               "base_rcept": None, "sim": None, "rewrite": None, "line": None, "line_ready": False}
        if row["chars"] is None:
            pending += 1
        if b is not None:
            kp = norm + "|" + b["rcept"] + "|" + h["rcept"]
            sim = d["sim"].get(kp)
            ln = d["line"].get(kp) or {}
            ready = ln.get("v") == GIST_V
            row.update({"base_stamp": b["stamp"], "base_label": b["label"], "base_rcept": b["rcept"],
                        "base_chars": d["chars"].get(norm + "|" + b["rcept"]),
                        "sim": sim, "rewrite": round(100 - sim, 1) if sim is not None else None,
                        "line": ln.get("ln") if ready else None, "line_ready": ready})
            if sim is None or not ready:
                pending += 1
        rows.append(row)
    if pending and not TRAJING.get(key):
        TRAJING[key] = True
        threading.Thread(target=_run_traj, args=(code, norm, labels), daemon=True).start()
    return {"section": norm, "rows": rows, "pending": pending}


# ---------------------------------------------------------------- 투자 브리핑(테스트)
# 보고서 한 건의 변화를 '신호'로 바꾼다. 신호 = 방향(기회 +1 … 위험 −1) · 시간 지평(0 지금 … 1 구조)
# · 무게 · 근거 문장 · 그 신호를 가장 먼저 볼 구루. 화면이 지형도·원탁·메모로 엮는다.
INV_V = 11         # 11: 단서 조항 · 회계 표시 · 다짐 문장 거름 · 9: 분기보고서도 전년 동기와 견준다(1Q↔작년 1Q) · 10: 신호 전용 분류(classify_sig) · 상용구 거름
INV_POS = re.compile(r"증가|확대|수주|성공|최초|1위|선도|신규|진출|체결|준공|양산|인수|개선|성장|호조|흑자|상승|확보|출시|수출|"
                     r"돌파|최대|강화|회복|인상|승소|해소|종결|무혐의|취하|완료|선정|승인|획득")
INV_NEG = re.compile(r"감소|축소|중단|철수|손상|소송|제재|과징금|적자|부진|지연|취소|해지|하락|악화|분쟁|리콜|손실|위반|담합|"
                     r"압수|계속기업|불확실|둔화|연기|유예|파업|패소|부담|하회|미달|경쟁\s*심화|이탈")
INV_TAG = {   # 범주 → (방향 기울기, 시간 지평, 먼저 볼 구루)
    "실적·수익성": (.2, .15, ["드러켄밀러", "버핏"]),
    "자금조달": (-.6, .3, ["멍거", "버핏"]),
    "리스크·소송": (-1, .45, ["멍거"]),
    "수주·계약": (1, .5, ["드러켄밀러", "린치"]),
    "고객·전방": (.3, .5, ["버핏", "멍거"]),
    "지배구조·M&A": (.3, .55, ["버핏", "멍거"]),
    "인력": (0, .6, ["버핏"]),
    "설비·증설": (.8, .8, ["드러켄밀러", "버핏"]),
    "신사업·신제품": (.8, .85, ["린치", "드러켄밀러"]),
    "연구개발": (.5, .9, ["버핏", "린치"]),
}
INV_TAG_SHORT = {"수주·계약": "수주", "설비·증설": "증설", "신사업·신제품": "신사업", "연구개발": "R&D",
                 "고객·전방": "고객", "지배구조·M&A": "M&A", "자금조달": "자금조달", "리스크·소송": "리스크",
                 "실적·수익성": "실적", "인력": "인력"}
INV_NUM = [   # 숫자 문장 — (낱말, 커지면 좋은가, 지평, 구루)
    ("수주잔고", 1, .5, ["드러켄밀러", "린치"]), ("수주", 1, .5, ["드러켄밀러"]),
    ("생산능력", 1, .8, ["버핏", "드러켄밀러"]), ("CAPA", 1, .8, ["버핏"]), ("가동률", 1, .3, ["드러켄밀러"]),
    ("점유율", 1, .7, ["버핏"]), ("판매량", 1, .3, ["린치"]), ("배당", 1, .4, ["버핏"]),
    ("소송가액", -1, .45, ["멍거"]), ("과징금", -1, .45, ["멍거"]), ("차입금", -1, .6, ["멍거"]),
]
INV_ACRO = re.compile(r"(?<![A-Za-z])[A-Z][A-Z0-9&]{1,6}(?![A-Za-z])")
INV_PROPER = re.compile(r"(?<![A-Za-z])[A-Z][a-z]+[A-Z]?[A-Za-z]{2,}(?![A-Za-z])")   # FlaktGroup, Xealth, Masimo
INV_UNIT = re.compile(r"(?<![제\d,.])\d[\d,.]*\s*(?:조\s*원|억\s*원|조|억|MWh|GWh|kWh|MW|GW|kV|톤|척|%|배|개국)")
# 정관·상법 조문과 이사 선임·보수 절차 — 문장은 새로 들어와도 투자 신호가 아니다
INV_GOV = re.compile(r"제\s*\d+\s*[조항]|상법|의결권|발행주식\s*총수|주주총회\s*소집|주주제안|보수\s*(총액|한도|최고한도)|등기이사|"
                     r"독립이사|사외이사|감사위원|이사회\s*규정|정관|결의과정|안건|선임|경험과\s*역량|전문성|임기|위임장|대리인|"
                     r"기재함|산식|종가|대손|제각|미지급수량|신탁계약|(변경|변동)\s*사항\S*\s*없|해당\s*없|"
                     r"성과보수|임원\s*보상|보상\s*위원회|보수\s*위원회|평가\s*항목|특별\s*성과|성과\s*평가|미등기\s*임원|직책을\s*수행|성과\s*지표|조직\s*성과|장기\s*성과|기초주가")
# 신호 문장 전용 분류(2026-10-01) — classify(TAGS)는 궤도·변경점 카드가 그대로 쓰고, 변화 브리핑 · 분기 변화의 신호만 이것으로.
# 앞에 올수록 이름표 머리가 된다(구체적인 것 먼저). (범주, 잡는 말, 막는 말)
#  · '인수'는 인수인·인수대금 납입이 아닌 기업 인수만, 성과·보수 문장 속 '인수'(임원 성과 평가 사유)는 M&A 가 아니다
#  · 라이선스 · 기술이전 계약은 수주가 아니라 연구개발, '배당 목표에 EBITDA−CAPEX' 같은 문장은 증설이 아니다
SIG_TAGS = [(n, re.compile(a), re.compile(b) if b else None) for n, a, b in [
    ("리스크·소송", r"소송|분쟁|제재|과징금|손해배상|압수|리콜|조사를 받|계속기업|영업정지|횡령|배임", None),
    ("수주·계약", r"수주|공급 ?계약|판매 ?계약|납품|계약을? ?체결|수주잔고",
     r"라이선스|기술 ?(이전|도입)|임대차|근로 ?계약|보험 ?계약|파생|스왑|PRS|TRS|이자율|약정"),
    ("연구개발", r"연구 ?개발|R&D|특허|임상|품목 ?허가|판매 ?허가|허가를? ?(받|획득|신청)|승인을? ?(받|획득|신청)|"
     r"FDA|EMA|식약처|라이선스|기술 ?(이전|도입)|바이오시밀러", None),
    ("지배구조·M&A", r"인수(?!인|권|하여야|대금)|합병|사업 ?결합|영업 ?양수|지분 ?(매각|취득|처분|인수)|종속회사 ?(편입|제외)|"
     r"(물적|인적|회사|사업) ?분할|분할 ?(신설|존속|계획|결정)|최대주주 ?변경|경영권", r"성과|보수|평가"),
    ("신사업·신제품", r"신규 ?사업|신 ?제품|상용화|출시|개발 ?완료|사업 ?진출|신규 ?시장", None),
    ("설비·증설", r"증설|설비 ?투자|생산 ?능력|가동률|신규 ?공장|공장 ?(신설|건설|착공|준공|가동)|양산|CAPEX|생산 ?라인|CAPA",
     r"배당|자기주식|주주환원"),
    ("고객·전방", r"매출 ?비중|주요 ?고객|주요 ?매출처|주요 ?거래처|단일 ?고객|전방 ?산업", None),
    ("자금조달", r"유상증자|무상증자|전환사채|신주인수권부사채|교환사채|사채 ?발행|담보 ?제공|차입금? ?(증가|확대|조달|차환)|신규 ?차입",
     r"자본화|차입원가|피투자회사|관계기업|공동기업"),
    ("인력", r"직원 ?수|임원의 ?(선임|사임|해임)|평균 ?근속|1인 ?평균 ?급여|인력 ?(충원|감축)|구조조정|희망퇴직", None),
    ("실적·수익성", r"영업 ?(이익|손실)|매출 ?(액|증가|감소)|영업 ?이익률|원가 ?(상승|절감)|환율", None),
]]


def classify_sig(sent):
    return [n for n, rx, no in SIG_TAGS if rx.search(sent) and not (no and no.search(sent))]


# 신호로 치지 않는 문장 — 주석 · 보고서 안내, 회계 처리 설명, 자사주 처리 '할 수 있음' 같은 방침 문구
INV_BOIL = re.compile(r"참고하여\s*주시기|참고\s*바랍니다|주석을?\s*참고|감사보고서\s*내|이익소각으로\s*인하여|납입자본금과\s*상이|"
                      r"자본화(이자율|가능)|차입원가|배당금\s*수익|이자\s*수익|지분법\s*손익|출발점|으로\s*분류(함|하고|한다|하였)|"
                      r"표시하고\s*있|관계기업으로|손익계산서에|현금흐름(표|\s*산정)")
# 단서 조항 — '거래조건은 … 변동될 수 있음'은 사건이 아니다
INV_CAVEAT = re.compile(r"(변동|변경|조정)될\s*수\s*있|달라질\s*수\s*있")
# 숫자 · 날짜 · 이름(코드 · 약어 · 고유명사)이 하나도 없는 다짐 문장 — '지속적인 R&D 활동과 기술 영업을 추진'
INV_GENERIC = re.compile(r"지속적|노력하|추진하고|강화하고|바탕으로|수행하고\s*있|최선을|도모")
INV_PAYOUT = re.compile(r"배당 ?(목표|정책|성향|재원|가능 ?이익)|주주환원 ?(정책|계획)")     # 배당 방침 문장은 주주환원이 머리
INV_MAY = re.compile(r"할\s*수\s*있(음|습니다|다)")
INV_DONE = re.compile(r"준공|완료|인도|종결|만기|상환|지급\s*완료")      # 끝난 일이 문장에서 빠지는 건 악재가 아니다
INV_HOLDER = re.compile(r"배당|자기주식|자사주|소각|주주환원")
INV_LABEL_STOP = {"연결실체", "당사", "회사", "주주총회", "임시주주총회", "연결회사", "지배기업",
                  "연결감사보고서", "감사보고서", "납입자본금", "주주가치", "보고기간말", "평가항목", "운영규정"}
INV_ACRO_STOP = {"USA", "LLC", "INC", "LTD", "CO", "EC", "CT", "IR", "ESG", "CEO", "CFO", "CTO", "COO", "EBITDA", "CAPEX",
                 "OPEX", "IFRS", "DART", "KRX", "PER", "PBR", "ROE", "EPS", "BV", "GMBH", "PTE", "PLC", "SA", "AG"}
INV_CODE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]{1,5}-[A-Z]?\d{1,4}[A-Za-z]?|[A-Z]{2,5}\d{1,4}[A-Z]?)(?![A-Za-z0-9])")   # CT-P44, GLP-1, HBM3E
INV_VERBISH = re.compile(r"(하거나|하며|하여|하고|하는|하기|되어|되는|된다|했다|한다|으로|에서|에게|이며|이고|거나|이다|하였|되었|위하여|통하여|함|"
                         r"였고|였으며|시키기|키기|되며|위해|위한|하게|되고|하면서|였음|하였음|부터|상기)$")


def _inv_info(sent):
    """문장에 붙잡을 것(금액 · 날짜 · 제품 코드 · 약어 · 고유명사)이 있나."""
    if INV_UNIT.search(sent) or DATE_RE.search(sent) or INV_CODE.search(sent) or INV_PROPER.search(sent):
        return True
    return any(a.upper() not in INV_ACRO_STOP for a in INV_ACRO.findall(sent))


def _clip(v, lo=-1.0, hi=1.0):
    return max(lo, min(hi, v))


INV_YEAR = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)\s*[년.\-/]")


def _inv_old(sent, year):
    """문장에 나오는 연도가 전부 2년 넘게 지난 것이면 배경 설명(설립·분할 연혁)이다."""
    ys = [int(y) for y in INV_YEAR.findall(sent)]
    return bool(ys) and max(ys) < year - 1


def _inv_dup(sent, kept):
    """같은 사건을 섹션마다 조금씩 다르게 적은 문장(소송 경과 등)은 한 번만."""
    ts = _tokset(sent)
    for k in kept:
        inter = len(ts & k)
        if inter and inter / (len(ts) + len(k) - inter) >= 0.4:
            return True
    return False


def _inv_label(tags, raw):
    """지도에 붙일 짧은 이름 — '수주 · 200MWh' 처럼 범주 + 금액/제품 코드/약어/새 낱말."""
    head = INV_TAG_SHORT.get(tags[0], tags[0]) if tags else ""
    # 배당 · 자사주 문장은 수주 · R&D · 리스크 · 신사업이 함께 있지 않으면 주주환원이 머리
    if INV_PAYOUT.search(raw) or (INV_HOLDER.search(raw) and not (tags and tags[0] in ("리스크·소송", "수주·계약", "연구개발", "신사업·신제품"))):
        head = "주주환원"
    tok = ""
    m = INV_UNIT.search(raw)
    if m and not m.group(0).rstrip().endswith("%"):     # '100%' 같은 지분율보다 고유명사가 낫다
        tok = re.sub(r"\s+", "", m.group(0))
    if not tok:
        cm = INV_CODE.search(raw)
        if cm and cm.group(0).upper() not in INV_ACRO_STOP:
            tok = cm.group(0)
    if not tok:
        for a in INV_ACRO.findall(raw):
            if a.upper() not in INV_ACRO_STOP and (INF is None or a not in INF.FX):
                tok = a
                break
    if not tok:
        pn = INV_PROPER.search(raw)
        if pn:
            tok = pn.group(0)
    if not tok and m:
        tok = re.sub(r"\s+", "", m.group(0))
    if not tok and INF:
        ts = [t for t in INF.tokens(raw) if 3 <= len(t) <= 9 and t not in INV_LABEL_STOP
              and not GIST_TERM_SKIP.search(t) and not INV_VERBISH.search(t) and t.upper() not in INV_ACRO_STOP]
        tok = max(ts, key=len) if ts else ""
    if not head and INV_HOLDER.search(raw):
        head = "주주환원"
    if head == "주주환원" and not (m and tok == re.sub(r"\s+", "", m.group(0))):
        # 금액이 없으면 무엇을 하는지로 — 소각 · 자사주 매입 · 배당 · 자사주 처분
        tok = ("소각" if "소각" in raw else "자사주 매입" if re.search(r"(자기주식|자사주)\S*\s*(매입|취득)", raw)
               else "배당" if "배당" in raw else "자사주 처분" if "처분" in raw else tok)
    if not head and re.search(r"시장|수요|전망|성장률", raw):
        head = "시장"
    return (head + " · " + tok) if head and tok else (head or tok or raw[:10])


def _inv_text(src, text, raw, section, v):
    tags = classify_sig(raw)
    pos, neg = len(INV_POS.findall(raw)), len(INV_NEG.findall(raw))
    senti = (pos - neg) / max(1, pos + neg)
    prior = sum(INV_TAG[t][0] for t in tags) / len(tags) if tags else 0.0
    holder = bool(INV_HOLDER.search(raw))
    d = _clip(0.6 * senti + 0.4 * prior + (0.5 if holder else 0))
    w = SECTION_WEIGHT.get(section, DEFAULT_WEIGHT)
    mag = _clip((0.3 + 0.07 * max(0.0, v)) * (0.5 + 0.5 * w), 0.15, 1.0)
    if src == "gone":          # 사라진 좋은 말은 약한 악재, 사라진 나쁜 말은 약한 호재. 끝난 일은 중립
        d = 0.0 if INV_DONE.search(raw) else -0.45 * d
        mag *= 0.75
    hz = sum(INV_TAG[t][1] for t in tags) / len(tags) if tags else (0.4 if holder else 0.5)
    gurus = []
    for t in tags:
        for g in INV_TAG[t][2]:
            if g not in gurus:
                gurus.append(g)
    if holder and "버핏" not in gurus:
        gurus.insert(0, "버핏")
    return {"src": src, "label": _inv_label(tags, raw), "text": text, "section": section,
            "sec": SEC_SHORT.get(section, section), "tags": tags, "dir": round(d, 2),
            "hz": round(hz, 2), "mag": round(mag, 2), "gurus": gurus or ["린치"]}


def _inv_fin(rows):
    by = {r["key"]: r for r in rows or []}
    out = []

    def add(label, d, hz, gurus, text, key=None, value=None):
        out.append({"src": "fin", "label": label, "text": text, "section": "재무지표", "sec": "재무",
                    "tags": [], "dir": round(_clip(d), 2), "hz": hz, "mag": round(max(0.25, min(1, abs(d) * 1.1)), 2),
                    "gurus": gurus, "key": key, "value": value})

    def pct(k):
        r = by.get(k)
        return r["pct"] if r and r.get("pct") is not None else None

    def g(k, f="value"):
        r = by.get(k)
        return r.get(f) if r else None
    rev, op = pct("매출액"), pct("영업이익")
    if rev is not None:
        add("매출 %+.0f%%" % rev, rev / 40, .1, ["드러켄밀러", "린치"], "매출액이 비교 보고서(전년 동기)보다 %+.1f%%." % rev, "매출액", rev)
    opv, opp = g("영업이익"), g("영업이익", "prev")
    if opv is not None and opp is not None and (opv > 0) != (opp > 0):
        add("흑자 전환" if opv > 0 else "적자 전환", .9 if opv > 0 else -.9, .15, ["드러켄밀러", "버핏"],
            "영업이익이 %s로 돌아섰다." % ("흑자" if opv > 0 else "적자"), "영업이익", None)
    elif op is not None:
        add("영업이익 %+.0f%%" % op, op / 50, .15, ["드러켄밀러", "버핏"], "영업이익이 %+.1f%%." % op, "영업이익", op)
    if rev and op and rev > 0 and op > rev * 1.2:
        add("레버리지 %.1f배" % (op / rev), .6, .3, ["드러켄밀러"],
            "이익이 매출보다 %.1f배 빨리 늘었다 — 고정비가 깔린 뒤의 매출이 이익으로 떨어지고 있다." % (op / rev), "레버리지", op / rev)
    md = g("영업이익률", "delta")
    if md is not None:
        add("이익률 %+.1f%%p" % md, md / 5, .35, ["버핏", "드러켄밀러"],
            "영업이익률 %.1f%% (%+.1f%%p)." % (g("영업이익률") or 0, md), "영업이익률", md)
    rd = g("ROE", "delta")
    if rd is not None:
        add("ROE %+.1f%%p" % rd, rd / 5, .75, ["버핏"], "ROE %.1f%% (%+.1f%%p)." % (g("ROE") or 0, rd), "ROE", rd)
    dd = g("부채비율", "delta")
    if dd is not None and abs(dd) >= 5:
        add("부채비율 %+.0f%%p" % dd, -dd / 30, .6, ["멍거", "버핏"], "부채비율 %.0f%% (%+.0f%%p)." % (g("부채비율") or 0, dd), "부채비율", dd)
    rp = pct("유보금")
    if rp is not None and abs(rp) >= 5:
        add("유보금 %+.0f%%" % rp, rp / 40 * .6, .85, ["버핏"], "쌓인 이익(유보금) %+.1f%%." % rp, "유보금", rp)
    ep, per = pct("EPS"), g("PER")
    if ep is not None and ep > 0 and per and per > 0:
        peg = per / ep
        add("PEG %.1f" % peg, .6 if peg < 1 else (-.4 if peg > 2 else 0.1), .1, ["린치"],
            "PER %.1f배를 EPS 증가율 %.0f%%로 나누면 %.2f." % (per, ep, peg), "PEG", peg)
    pb, bp = pct("PBR"), pct("BPS")
    if pb is not None and abs(pb) >= 15:
        add("PBR %.1f배 (%+.0f%%)" % (g("PBR") or 0, pb), -.35 if pb > 0 else .35, .05, ["버핏", "린치"],
            ("주가가 장부가치보다 빨리 올라 PBR이 %+.0f%% 재평가됐다 — 기대가 값에 들어가는 중." if pb > 0
             else "PBR이 %+.0f%% 낮아졌다 — 장부가치 대비 싸졌다.") % pb, "PBR", pb)
    ni = pct("당기순이익")
    if ni is not None and op is not None and ni - op > 40 and op < 30:
        add("영업외 이익", -.35, .2, ["멍거"], "순이익(%+.0f%%)이 영업이익(%+.0f%%)보다 훨씬 빨리 늘었다 — 본업 밖의 이익." % (ni, op), "순이익", ni)
    return out


def _inv_nums(b):
    out, seen = [], set()
    for s in b.get("sections", [])[:8]:
        for nn in s.get("numbers", []):
            after = nn.get("after", "")
            hit = next((x for x in INV_NUM if x[0] in after), None)
            if not hit or BOILER.search(after):
                continue
            k = SKEL_RE.sub("", after)[:30]     # 같은 문장이 재무·재무제표 섹션에 두 번 실린다
            if k in seen:
                continue
            seen.add(k)
            dfs = [x for x in (nn.get("diff") or []) if x.get("pct") is not None and abs(x["pct"]) >= 10]
            if not dfs:
                continue
            x = dfs[0]
            d = _clip(hit[1] * (1 if x["pct"] > 0 else -1) * min(1, abs(x["pct"]) / 60))
            out.append({"src": "num", "label": "%s %+.0f%%" % (hit[0], x["pct"]), "text": _short(after, 110),
                        "section": s["section"], "sec": SEC_SHORT.get(s["section"], s["section"]), "tags": nn.get("tags") or [],
                        "dir": round(d, 2), "hz": hit[2], "mag": round(max(.25, min(1, abs(d) + .15)), 2),
                        "gurus": hit[3], "from": x["from"], "to": x["to"]})
            if len(out) >= 6:
                return out
    return out


def _ttm_growth(by, p):
    """분기 키 n 의 최근 4분기 매출 합이 1년 전(n − 4)보다 몇 % — 둘 중 하나라도 없으면 None."""
    b = by.get(p["n"] - 4) if p.get("n") is not None else None
    return (p["매출_TTM"] / b["매출_TTM"] - 1) * 100 if p.get("매출_TTM") and b and b.get("매출_TTM") and b["매출_TTM"] > 0 else None


def _inv_ttm(code, stamp):
    """가속도 캐시(지금 버전)로 이 분기의 TTM 성장률(g) · 속도(s) · 가속(B)(a) · 7국면(reg) · 변곡(turn). 없으면 None — 여기서 새로 쌓지 않는다."""
    d = _druck_read(code)
    if not d:
        return None
    pts = d.get("points") or []
    y, m = stamp.split("-")
    lab = "%sQ%d" % (y, Q_OF_MONTH.get(m, 0))
    idx = next((i for i, p in enumerate(pts) if p.get("label") == lab), None)
    if idx is None:
        return None
    p = pts[idx]
    by = {x["n"]: x for x in pts if x.get("n") is not None}
    # 자기 역사 대비 PER 백분위 — 이 분기까지의 과거만 본다(앞날 자료 없음). 분할 보정을 못 한 분기(cut)는 견주지 않는다
    per = p.get("PER_TTM")
    hist = [x.get("PER_TTM") for x in pts[:idx + 1] if (x.get("PER_TTM") or 0) > 0 and "cut" not in (x.get("품질") or [])]
    per_pct = (sum(1 for v in hist if v <= per) / len(hist) * 100) if per and per > 0 and len(hist) >= 8 else None
    return {"label": lab, "g": _ttm_growth(by, p), "s": p.get("속도"), "a": p.get("가속B"), "reg": p.get("국면"), "turn": p.get("변곡"),
            "price": p.get("주가"), "per": per, "per_pct": per_pct}


# ---- 중요도 · 같은 사건 묶기 · 지배구조 — 월가가 먼저 묻는 '그래서 얼마나 큰가' (2026-10-01)
# 과징금 67억이 시총 24조 회사의 '가장 무거운 위험'으로 올라가고, 같은 담합 건이 신호 세 개로 세어지던 것을 고친다.
INV_WON = re.compile(r"(?<![제\d.,])(\d[\d,]*(?:\.\d+)?)\s*조\s*(?:(\d[\d,]*(?:\.\d+)?)\s*억\s*)?원|(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*억\s*원|"
                     r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*백만\s*원|(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*천만\s*원|(?<![\d.,])(\d[\d,]{8,})\s*원")
INV_RELATED = re.compile(r"특수관계(?:인|자)|최대주주\s*(?:등)?\s*(?:과|와|에게|로부터|의\s*계열)|계열회사\s*(?:와|로부터|에게|간)|"
                         r"(?:자산|영업)\s*(?:양수|양도)|내부\s*거래|부당\s*지원|일감\s*몰아")
INV_ROUTINE = re.compile(r"(?:분기|중간|결산|현금|정기)\s*배당[^.]{0,40}(?:결의|지급)|배당금[^.]{0,20}지급\s*예정")
# 기준(감사 중요성 관행을 따름): 중요 = 연 영업이익 10%↑ 또는 매출 2%↑ 또는 시총 1%↑, 작음 = 모두 영업이익 2%·매출 0.5%·시총 0.2% 미만
INV_MAT = {"big": (10.0, 2.0, 1.0), "small": (2.0, 0.5, 0.2)}


# 실적 보고 문장('매출 552억원 달성') — 금액이 사건 크기가 아니라 실적 자체다. 크기를 매기지 않는다
INV_PERF = re.compile(r"(매출|영업이익|순이익|영업수익|이익)[^.]{0,50}(달성|기록|시현|실현)|(매출액|영업이익)(은|이)\s*[\d,.]+\s*(조|억|백만)")
INV_EVENT = re.compile(r"수주|계약|소송|과징금|투자|출자|인수|취득|차입|증자|사채|배당|손상|충당")
INV_OURS = re.compile(r"(그\s*중|중)\s*(당사|회사)|당사가?\s*(부담|출자|투자)")


def _inv_won(s):
    """문장 속 원화 금액 중 가장 큰 것(원). 1억 미만(주당 배당금 등)은 사건 크기로 보지 않는다.
    '총 750억원 규모, 그 중 당사 출자 50억원'처럼 회사 몫이 따로 적혀 있으면 그 뒤의 금액을 쓴다."""
    ours = INV_OURS.search(s or "")
    if ours:
        tail = _inv_won((s or "")[ours.end():]) if INV_WON.search((s or "")[ours.end():]) else None
        if tail:
            return tail
    best = None
    for m in INV_WON.finditer(s or ""):
        f = lambda x: float(x.replace(",", "")) if x else 0.0
        if m.group(1):
            v = f(m.group(1)) * 1e12 + f(m.group(2)) * 1e8
        elif m.group(3):
            v = f(m.group(3)) * 1e8
        elif m.group(4):
            v = f(m.group(4)) * 1e6
        elif m.group(5):
            v = f(m.group(5)) * 1e7
        else:
            v = f(m.group(6))
        if v >= 1e8 and (best is None or v > best):
            best = v
    return best


def _inv_scale(c, rep, filed):
    """이 보고서가 나온 때의 회사 크기 — 직전 사업보고서의 연 매출·영업이익, 공시일 시가총액."""
    out = {}
    corp = corp_code_of(c["code"])
    y = int(rep["stamp"][:4]) - (0 if rep["label"] == "사업보고서" else 1)
    try:
        F = [d for d in INF.fundamentals(FIN, corp, [y - 2, y - 1, y]) if d.get("rev")] if (INF and corp) else []
    except Exception:
        F = []
    F = [d for d in F if d["year"] <= y]
    if F:
        out.update(year=F[-1]["year"], rev=F[-1].get("rev"), op=F[-1].get("op"))
    try:
        univ, snap = _universe_info()
        u = univ.get(c["code"])
        pr = FIN.fetch_prices(c["code"]) if FIN else {}
        if u and snap and pr and filed:
            ds = sorted(pr)
            adj = SYN._adjusted(pr, ds) if SYN is not None else [pr[d] for d in ds]
            import bisect
            i0, i1 = bisect.bisect_right(ds, snap) - 1, bisect.bisect_right(ds, filed) - 1
            if i0 >= 0 and i1 >= 0 and adj[i0]:
                out["cap"] = u["cap"] * adj[i1] / adj[i0]
    except Exception:
        pass
    return out


def _inv_refine(sigs, scale):
    """신호마다 크기(회사 대비)를 달고, 같은 사건은 한 줄로 묶고, 특수관계 거래는 지배구조 질문으로 돌린다."""
    rev, op, cap = scale.get("rev"), scale.get("op"), scale.get("cap")
    out = []
    for s in sigs:
        s = dict(s)
        if s["src"] != "fin":
            txt = s.get("text") or ""
            perf = bool(INV_PERF.search(txt)) and not INV_EVENT.search(txt)
            amt = None if perf else _inv_won(txt)
            s["amt"] = amt
            if perf:
                s["size"] = "실적 문장"
            elif amt:
                p_op = amt / abs(op) * 100 if op else None
                p_rev = amt / rev * 100 if rev else None
                p_cap = amt / cap * 100 if cap else None
                s.update(p_op=p_op, p_rev=p_rev, p_cap=p_cap)
                vals = [(p_op, 0), (p_rev, 1), (p_cap, 2)]
                big = any(v is not None and v >= INV_MAT["big"][i] for v, i in vals)
                small = all(v is None or v < INV_MAT["small"][i] for v, i in vals) and any(v is not None for v, _ in vals)
                s["size"] = "중요" if big else "작음" if small else "보통"
            else:
                s["size"] = "금액 미상"
            if INV_RELATED.search(s.get("text", "")):
                s.update(gov=True, dir=round(min(s["dir"], 0) - 0.2, 2), label="특수관계 거래 · " + s["label"].split(" · ")[-1],
                         tags=["특수관계 거래"])
            if INV_ROUTINE.search(s.get("text", "")):
                s["routine"] = True
            f = {"중요": 1.25, "보통": 0.85, "작음": 0.35, "금액 미상": 0.8, "실적 문장": 0.8}[s["size"]] * (0.3 if s.get("routine") else 1)
            s["mag"] = round(max(0.08, min(1.0, s["mag"] * f)), 2)
        out.append(s)
    # 같은 사건 — 이름표의 고유 토막(170kV, 200MWh, 회사 이름 등)이 같은 새·사라진 문장은 한 줄로
    groups, merged = {}, []
    for s in out:
        tok = s["label"].split(" · ")[-1] if s["src"] in ("new", "gone") else None
        key = (tok, s["dir"] < -0.15) if tok and len(tok) >= 2 and not s.get("routine") else None
        if key and key in groups:
            g = groups[key]
            g.setdefault("related", []).append(s["text"])
            if (s.get("amt") or 0) > (g.get("amt") or 0):
                g.update({k: s.get(k) for k in ("amt", "p_op", "p_rev", "p_cap", "size")})
            continue
        if key:
            groups[key] = s
        merged.append(s)
    for s in merged:
        s["n_rel"] = len(s.get("related", []))
    return merged


def _inv_expect(c, rep):
    """시장 기대 대비 — 이 보고서 해의 연간 컨센서스(네이버 재무 요약)와 올해 누적 실적의 진도, 선행 PER.
    컨센서스 기록은 쌓기 시작한 뒤의 것만 있어, 그 해 컨센서스가 없으면 None(옛 보고서)."""
    if FIN is None or DRK is None:
        return None
    try:
        ann = FIN.fetch_consensus(c["code"], "annual") or {}
    except Exception:
        return None
    y, mth = rep["stamp"].split("-")
    key = y + "12"
    col = next((x for x in ann.get("cols", []) if x.get("key") == key), None)
    rows = ann.get("rows") or {}
    if not col or not col.get("consensus") or not rows.get("영업이익", {}).get(key):
        return {"none": True, "why": "이 보고서 해(%s년)의 컨센서스가 없다 — 컨센서스 기록은 쌓기 시작한 뒤의 해만 있다" % y}
    rq = Q_OF_MONTH.get(mth)
    out = {"year": int(y), "q": rq, "rev_e": rows.get("매출액", {}).get(key), "op_e": rows.get("영업이익", {}).get(key),
           "ni_e": rows.get("당기순이익", {}).get(key), "eps_e": rows.get("EPS", {}).get(key)}
    try:
        corp = corp_code_of(c["code"])
        pts = [p for p in DRK.series(corp, c["code"], [int(y)]) if p["year"] == int(y) and p["q"] <= (rq or 0)]
        if rq and len(pts) == rq and all(p.get("영업이익") is not None and p.get("매출액") for p in pts):
            out["ytd_rev"] = sum(p["매출액"] for p in pts)
            out["ytd_op"] = sum(p["영업이익"] for p in pts)
            out["share_rev"] = out["ytd_rev"] / out["rev_e"] * 100 if out.get("rev_e") else None
            out["share_op"] = out["ytd_op"] / out["op_e"] * 100 if out.get("op_e") else None
            out["par"] = rq / 4 * 100          # 계절성이 없다면 채웠어야 할 몫
            if rq < 4 and out.get("op_e"):
                out["need_rest"] = (out["op_e"] - out["ytd_op"]) / (4 - rq)      # 남은 분기 평균으로 벌어야 할 영업이익
                out["ytd_avg"] = out["ytd_op"] / rq
            # 이 회사가 지난 3년 같은 시점까지 연간 영업이익의 몇 %를 냈나(계절성)
            shares = []
            for yy in range(int(y) - 3, int(y)):
                qs = [p for p in DRK.series(corp, c["code"], [yy]) if p["year"] == yy]
                if len(qs) == 4 and all(p.get("영업이익") is not None for p in qs):
                    tot = sum(p["영업이익"] for p in qs)
                    part = sum(p["영업이익"] for p in qs if p["q"] <= rq)
                    if tot > 0 and part >= 0:
                        shares.append(part / tot * 100)
            if len(shares) >= 2:
                out["par_hist"] = sum(shares) / len(shares)
                out["par_n"] = len(shares)
    except Exception:
        pass
    try:
        pr = FIN.fetch_prices(c["code"]) or {}
        if pr and out.get("eps_e") and out["eps_e"] > 0:
            last = max(pr)
            out.update(fwd_per=pr[last] / out["eps_e"], price_date=last)
    except Exception:
        pass
    # 지난해 실적 대비 올해 기대 성장
    prev = str(int(y) - 1) + "12"
    for k, nm in (("매출액", "g_rev"), ("영업이익", "g_op")):
        a, e = rows.get(k, {}).get(prev), rows.get(k, {}).get(key)
        if a and e and a > 0:
            out[nm] = (e / a - 1) * 100
    try:
        hist = json.load(open(os.path.join(FIN.CONSENSUS_DIR, "%s_annual_기록.json" % c["code"]), encoding="utf-8"))
        h = [x for x in hist.get("_이력", []) if x.get("분기") == key and x.get("영업이익")]
        if len(h) >= 2:
            out["rev_since"] = h[0]["기록일"]
            out["op_rev_pct"] = (h[-1]["영업이익"] / h[0]["영업이익"] - 1) * 100
    except Exception:
        pass
    return out


def _inv_collect(c, base, rep, b, ryear, known=None, regular=None):
    """b(build_brief 모양)의 섹션에서 새 문장 · 사라진 문장 신호를 뽑는다. (신호들, 새 낱말, 사라진 낱말)
    known(보고서 목록)을 주면 새 문장은 그 보고서들에도 없던 것만 — 분기 변화에서 '지난 12개월 공시 어디에도 없던 말'.
    regular(같은 종류 직전 보고서)를 주면 사라진 문장은 거기에도 있던 것(그 종류 보고서에 늘 쓰던 말)만 —
    서식이 다른 두 보고서(사업보고서↔분기보고서)를 맞댈 때 사업보고서에만 있는 절이 '사라졌다'로 잡히지 않게."""
    sigs, came, gone, seen, kept = [], [], [], set(), []

    def sec_skel(r, norm):
        x = next((y for y in r["sections"] if y["norm"] == norm), None)
        return SKEL_RE.sub("", read_section(c, r, x["file"])) if x else ""

    def hit(sent, texts):
        sk = SKEL_RE.sub("", sent)
        return len(sk) >= 20 and any(sk[:22] in t or sk[-22:] in t for t in texts)
    for s in [x for x in b["sections"] if x.get("weight", 0) >= 0.3][:7]:
        bf = s.get("base_file") or s["file"]
        kn = [t for t in (sec_skel(r, s["section"]) for r in (known or [])) if t]
        rg = sec_skel(regular, s["section"]) if regular is not None else None
        nc = _novel_cands(c, base, rep, bf, s["file"], s["section"])
        k = 0
        for v, sent, j in nc["cands"]:
            if k >= 3:
                break
            if INV_GOV.search(sent) or _inv_dup(sent, kept) or _inv_old(sent, ryear):
                continue
            if INV_BOIL.search(sent) or INV_CAVEAT.search(sent) or (INV_HOLDER.search(sent) and INV_MAY.search(sent)):
                continue          # 주석 안내 · 회계 설명 · 단서 조항 · 자사주 처리 방침('할 수 있음')
            if INV_GENERIC.search(sent) and not _inv_info(sent):
                continue          # 붙잡을 숫자도 이름도 없는 다짐 문장
            if kn and hit(sent, kn):
                continue          # 지난 공시(사업보고서 등)에 이미 있던 말 — 시장이 읽은 것
            # 범주도 주주환원도 아닌 문장은 금액과 방향 낱말이 둘 다 있어야 신호로 친다
            if not classify_sig(sent) and not INV_HOLDER.search(sent) and not (
                    INV_UNIT.search(sent) and (INV_POS.search(sent) or INV_NEG.search(sent))):
                continue
            t = _short(sent, 110)
            key = SKEL_RE.sub("", t)[:24]
            if key in seen:
                continue
            seen.add(key)
            kept.append(_tokset(sent))
            k += 1
            sigs.append(_inv_text("new", t, sent, s["section"], v))
        came += [t for t in nc["came"] if t not in came]
        gone += [t for t in nc["gone"] if t not in gone]
        dc = _novel_cands(c, rep, base, s["file"], bf, s["section"])
        took = 0
        for v, sent, j in dc["cands"][:(4 if rg is not None else 1)]:
            if took:
                break
            t = _short(sent, 110)
            key = SKEL_RE.sub("", t)[:24]
            if (key in seen or not classify_sig(sent) or INV_GOV.search(sent) or _inv_dup(sent, kept)
                    or _inv_old(sent, ryear) or INV_BOIL.search(sent)):
                continue      # 범주 없는 사라진 문장은 대개 서식 정리다
            if rg is not None and not hit(sent, [rg]):
                continue      # 그 종류 보고서에 늘 쓰던 말이 아니면 서식 차이(사업보고서에만 있는 절)
            seen.add(key)
            kept.append(_tokset(sent))
            took += 1
            sigs.append(_inv_text("gone", t, sent, s["section"], v))
    return sigs, came, gone


def invest_view(c, rep, lite=False):
    """lite=True 면 주가·궤도·국면을 빼고 신호·재무만 — 여러 보고서를 한꺼번에 돌리는 성적표용."""
    ybase, ykind = baseline_yoy(c, rep)          # 전년 동기와 견준다(2026-10-01) — 직전 3개월 비교는 '분기 변화' 탭
    b = brief_pair(c, ybase, rep, ykind)
    out = {"code": c["code"], "name": c["name"], "report": b["report"], "base": b["base"],
           "kind": b["kind"], "score": b["score"], "first": bool(b.get("first") or not b.get("base"))}
    if out["first"]:
        return out
    path = os.path.join(CACHE_DIR, "invest", c["code"], rep["rcept"] + ".json")
    sig = "%d.%d" % (INV_V, GIST_V)
    cached = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            if cached.get("v") != sig:
                cached = None
        except Exception:
            cached = None
    if cached is None:
        base = report_of(c, b["base"]["rcept"])
        sigs, came, gone = _inv_collect(c, base, rep, b, int(rep["stamp"][:4]))
        fin = financials(c, rep, (base, b["kind"]))
        sigs += _inv_fin(fin.get("rows"))
        sigs += _inv_nums(b)
        cached = {"v": sig, "signals": sigs, "came": came[:8], "gone": gone[:6],
                  "fin": fin.get("rows") or [], "price": (fin.get("now") or {}).get("price"),
                  "price_date": (fin.get("now") or {}).get("price_date")}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cached, fh, ensure_ascii=False)
        except OSError:
            pass
    orig = rep
    if rep["tag"]:
        same = [r for r in c["reports"] if r["stamp"] == rep["stamp"] and r["label"] == rep["label"] and not r["tag"]]
        if same:
            orig = min(same, key=lambda r: r["rcept"])
    out["filed"] = orig["rcept"][:8]
    out["filed_doc"] = rep["rcept"][:8]
    wt = lambda s: -(s["mag"] * (0.4 + abs(s["dir"])))
    # 선행 점수는 보정할 때와 같은 신호로 잰다(lead_sigs). 화면에 보이는 신호는 크기를 달고 같은 사건을 묶은 것
    lead = sorted(cached["signals"], key=wt)[:24]
    for i, s in enumerate(lead, 1):
        s["id"] = i
    scale = _inv_scale(c, rep, out["filed"])
    sigs = sorted(_inv_refine(cached["signals"], scale), key=wt)[:24]
    for i, s in enumerate(sigs, 1):
        s["id"] = i
    out.update({"signals": sigs, "lead_sigs": lead, "scale": scale, "came": cached["came"], "gone": cached["gone"],
                "fin": cached["fin"], "price": cached.get("price"), "price_date": cached.get("price_date"),
                "ttm": _inv_ttm(c["code"], rep["stamp"])})
    if lite:
        return out
    try:
        out["expect"] = _inv_expect(c, rep)
    except Exception:
        out["expect"] = None
    # 값 — 가속도 캐시가 없어 PER 자기 역사가 없으면 풍경 탭의 계산(분할 보정)을 빌린다. 가장 최근 보고서에만 맞는 '지금' 값
    latest = [r for r in c["reports"] if not r["tag"]]
    if not (out.get("ttm") or {}).get("per_pct") and latest and latest[-1]["stamp"] == rep["stamp"]:
        try:
            lp = _land_path(c["code"])
            if os.path.exists(lp):
                with open(lp, "r", encoding="utf-8") as fh:
                    dc = (json.load(fh).get("decide") or {})
                if dc.get("pct") is not None:
                    out["val"] = {"per": dc.get("per"), "pct": dc.get("pct"), "src": "풍경"}
        except Exception:
            pass
    # 이 보고서가 평소보다 얼마나 많이 새로 썼나(궤도 탭과 같은 값)
    try:
        o = orbit(c["code"])
        row = next((r for r in o["rows"] if r["rcept"] == rep["rcept"]), None) if o else None
        if row:
            out["x"], out["tier"] = row.get("x"), row.get("tier")
        # 긴 궤도 — 이 보고서가 15년 흐름의 어디쯤인가
        out["arc"] = [{"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"], "x": r.get("x"),
                       "tier": r.get("tier"), "date": r["rcept"][:8]}
                      for r in (o["rows"] if o else []) if not r["tag"]]
    except Exception:
        out["arc"] = []
    out["regimes"] = _inv_regimes(c["code"])
    out["series"] = _inv_prices(c["code"], ohlc=True)
    return out


def matrix_cached(c, corp, stmt="IS", mode="q", n=4, force=False):
    """재무.statement_matrix 를 회사 · 표 · 주기 · 햇수별로 캐시(최신 보고서가 바뀌면 다시)."""
    this = dt.date.today().year
    years = list(range(this - n + 1, this + 1))
    key = "%s_%s_%s_%d" % (c["code"], stmt, mode, n)
    cache = os.path.join(CACHE_DIR, "matrix", key + ".json")
    sig = c["reports"][-1]["rcept"] if c["reports"] else ""
    if os.path.exists(cache) and not force:
        try:
            with open(cache, "r", encoding="utf-8") as fh:
                old = json.load(fh)
            if old.get("sig") == sig:
                return old
        except Exception:
            pass
    with _fin_watch() as bad:
        res = FIN.statement_matrix(corp, years, stmt, mode)
    res["sig"] = sig
    res["name"] = c["name"]
    if bad:
        # 원장 일시 오류(한도 · 점검 · 네트워크 · 미리 계산 DART 막힘)가 낀 판 — sig 가 최신 접수번호라 쓰면 새 보고서까지 빈 칸이 굳는다.
        # 이번 결과만 돌려주고 다음 부름에 다시 짠다(잘 받은 해는 재무.py 원장 캐시에 있어 다시 묻지 않는다)
        res["transient"] = len(bad)
        return res
    _atomic_json(cache, res)        # 뷰어 · 미리 계산 프로세스가 같은 파일을 쓸 수 있다
    return res


# ---------------------------------------------------------------- 분기 변화 — 3개월마다 나오는 보고서를 직전 공시와 맞댄다
# 변화 브리핑(전년 동기)과 짝. 보고서가 하나 나올 때마다 '직전 공시 대비 무엇이 바뀌었나'를 분기 단독 숫자와 함께
# 최근 8번 이어 본다. 새 문장은 직전 공시에도, 같은 종류 직전 보고서에도 없던 것(사업보고서↔분기보고서 서식 차이 막기).
QTR_V = 5          # 5: 이름표 동사 꼴 더 거름 · 4: 분류 다듬기 · 2: 새 문장 = 지난 12개월 공시 어디에도 없던 말 · 3: 신호 전용 분류
QTR_DIR = os.path.join(CACHE_DIR, "quarter")
QTR_LOCK = threading.Lock()
QTR_RUN = {}
QTR_LABELS = ("분기보고서", "반기보고서", "사업보고서")
QTR_YEARS = 6          # 재무상태표 · 현금흐름표 분기 매트릭스 햇수 — 시차 상관을 재려면 24분기는 있어야 한다
IS_YEARS = 10          # 손익계산서는 10년 — PER 이 자기 역사에서 어디쯤인지 재려고(재무 API 응답은 재무.py 가 캐시)


def _qtr_chain(c, n=9):
    """정정 빼고 분기 · 반기 · 사업보고서를 시점순으로, 같은 시점이면 나중 것 하나. 마지막 n개."""
    by = {}
    for r in c["reports"]:
        if not r["tag"] and r["label"] in QTR_LABELS and r["stamp"][5:] in Q_OF_MONTH:
            by[r["stamp"]] = r
    return [by[k] for k in sorted(by)][-n:]


def _qtr_pair(c, prev, rep):
    """직전 공시(prev) → 이번(rep)의 새 문장 · 사라진 문장 신호. 보고서마다 캐시."""
    path = os.path.join(QTR_DIR, c["code"], rep["rcept"] + ".json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("v") == QTR_V and d.get("prev") == prev["rcept"]:
                return d
        except Exception:
            pass
    alt = None
    if prev["label"] != rep["label"]:
        same = [r for r in c["reports"] if r["label"] == rep["label"] and not r["tag"] and r["stamp"] < rep["stamp"]]
        alt = same[-1] if same else None
    # 지난 12개월(작년 같은 분기 포함) 공시 — 시장이 이미 읽은 말. 직전 공시(prev)는 비교 대상이라 뺀다
    y, mth = int(rep["stamp"][:4]), rep["stamp"][5:]
    since = "%d-%s" % (y - 1, mth)
    known = [r for r in c["reports"] if not r["tag"] and r["label"] in QTR_LABELS
             and since <= r["stamp"] < rep["stamp"] and r["rcept"] != prev["rcept"]]
    b = {"sections": _brief_core(c, prev, rep)["sections"]}
    sigs, came, gone = _inv_collect(c, prev, rep, b, y, known, alt)
    d = {"v": QTR_V, "prev": prev["rcept"], "alt": alt["rcept"] if alt else None, "known": [r["rcept"] for r in known],
         "signals": sigs, "came": came[:8], "gone": gone[:6]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    return d


def _qtr_numbers(c):
    """분기 단독 매출 · 영업이익 · 순이익(실적 탭과 같은 재무 매트릭스 캐시). {'2026Q1': {...}}"""
    corp = corp_code_of(c["code"]) if FIN is not None else None
    if not corp:
        return {}
    m = matrix_cached(c, corp, "IS", "q", IS_YEARS)
    labs = [p["label"] for p in m.get("periods", [])]

    def row(keys, names):
        for r in m.get("rows", []):
            if r["key"] in keys:
                return r
        for r in m.get("rows", []):
            if re.match(names, r["name"]):
                return r
        return None
    rv = row(("t:Revenue",), r"^(매출액|수익\(매출액\)|영업수익|매출)$")
    op = row(("t:OperatingIncomeLoss",), r"^영업(이익|손익|손실)")
    ni = row(("t:ProfitLoss",), r"^당기순(이익|손익|손실)")
    out = {}
    for i, lab in enumerate(labs):
        g = lambda r: (r["values"][i]["v"] if r and i < len(r["values"]) else None)
        out[lab] = {"rev": g(rv), "op": g(op), "ni": g(ni)}
    return out


def _qtr_run(code):
    c = company_by_code(code)
    try:
        if not c:
            return
        chain = _qtr_chain(c)
        try:
            _qtr_numbers(c)
            corp = corp_code_of(c["code"])
            if corp:
                matrix_cached(c, corp, "BS", "q", QTR_YEARS)
                matrix_cached(c, corp, "CF", "q", QTR_YEARS)
        except Exception as e:
            QTR_RUN[code]["err"] = "재무 조회 실패: %s" % e
        if BACK is not None:
            try:
                BACK.company_series(c, read_section, max_reports=28)
            except Exception:
                pass
        try:
            _ord_series(c, budget=300)
        except Exception as e:
            print("수주 공시 %s: %s" % (code, e), flush=True)
        pairs = list(zip(chain[:-1], chain[1:]))[::-1]          # 최근 것부터
        QTR_RUN[code]["total"] = len(pairs)
        for k, (prev, rep) in enumerate(pairs, 1):
            try:
                _qtr_pair(c, prev, rep)
            except Exception as e:
                print("분기 변화 %s %s: %s" % (code, rep["stamp"], e), flush=True)
            QTR_RUN[code]["done"] = k
    finally:
        with QTR_LOCK:
            QTR_RUN[code]["running"] = False


def quarter_view(code):
    c = company_by_code(code)
    if not c:
        return {"error": "회사 없음"}
    chain = _qtr_chain(c)
    if len(chain) < 2:
        return {"error": "견줄 보고서가 둘 이상 없습니다."}
    pairs = list(zip(chain[:-1], chain[1:]))
    ready = {}
    for prev, rep in pairs:
        path = os.path.join(QTR_DIR, c["code"], rep["rcept"] + ".json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("v") == QTR_V and d.get("prev") == prev["rcept"]:
                ready[rep["rcept"]] = d
        except Exception:
            pass
    corp = corp_code_of(c["code"]) if FIN is not None else None
    m_ok = True
    for st_ in ("IS", "BS", "CF"):
        try:
            with open(os.path.join(CACHE_DIR, "matrix", "%s_%s_q_%d.json" % (c["code"], st_, IS_YEARS if st_ == "IS" else QTR_YEARS)),
                      "r", encoding="utf-8") as fh:
                m_ok = m_ok and json.load(fh).get("sig") == (c["reports"][-1]["rcept"] if c["reports"] else "")
        except Exception:
            m_ok = False
    with QTR_LOCK:
        st = QTR_RUN.setdefault(code, {"running": False, "done": 0, "total": 0})
        if (len(ready) < len(pairs) or (corp and not m_ok) or (corp and _ord_need(c) and not st.get("ord_tried"))) and not st["running"]:
            st["ord_tried"] = True          # 원문을 못 읽는 공시(양식 다름)가 있어도 매번 다시 돌지 않게 — 뷰어를 다시 켜면 한 번 더
            st.update(running=True, done=0, total=len(pairs))
            threading.Thread(target=_qtr_run, args=(code,), daemon=True).start()
        run = dict(st)
    nums = {}
    if m_ok:
        try:
            nums = _qtr_numbers(c)
        except Exception:
            nums = {}

    def qlab(stamp):
        return "%sQ%d" % (stamp[:4], Q_OF_MONTH[stamp[5:]])

    def prevq(lab, k):
        y, q = int(lab[:4]), int(lab[5]) - k
        while q <= 0:
            y, q = y - 1, q + 4
        return "%dQ%d" % (y, q)

    def pct(a, b):
        return (a / b - 1) * 100 if a is not None and b not in (None, 0) and b > 0 else None
    rows = []
    for r in chain:
        lab = qlab(r["stamp"])
        n0, n1, n4 = nums.get(lab, {}), nums.get(prevq(lab, 1), {}), nums.get(prevq(lab, 4), {})
        opm = lambda n: (n["op"] / n["rev"] * 100) if n.get("op") is not None and n.get("rev") else None
        m0, m1, m4 = opm(n0), opm(n1), opm(n4)
        rows.append({"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"], "q": lab,
                     "filed": r["rcept"][:8], "rev": n0.get("rev"), "op": n0.get("op"), "ni": n0.get("ni"),
                     "rev_qoq": pct(n0.get("rev"), n1.get("rev")), "rev_yoy": pct(n0.get("rev"), n4.get("rev")),
                     "op_qoq": pct(n0.get("op"), n1.get("op")), "op_yoy": pct(n0.get("op"), n4.get("op")),
                     "opm": m0, "opm_qoq": (m0 - m1) if m0 is not None and m1 is not None else None,
                     "opm_yoy": (m0 - m4) if m0 is not None and m4 is not None else None,
                     "op_prev": n1.get("op"), "op_ly": n4.get("op")})
    scale_cache = {}
    steps = []
    for prev, rep in pairs[::-1]:
        d = ready.get(rep["rcept"])
        step = {"rcept": rep["rcept"], "stamp": rep["stamp"], "label": rep["label"], "filed": rep["rcept"][:8],
                "prev": {"stamp": prev["stamp"], "label": prev["label"], "rcept": prev["rcept"]}, "ready": bool(d)}
        if d:
            try:
                sc = scale_cache.get(rep["rcept"]) or _inv_scale(c, rep, rep["rcept"][:8])
            except Exception:
                sc = {}
            wt = lambda x: -(x["mag"] * (0.4 + abs(x["dir"])))
            sigs = sorted(_inv_refine(d["signals"], sc or {}), key=wt)
            step.update(signals=sigs[:12], came=d.get("came", []), gone=d.get("gone", []),
                        alt=d.get("alt"))
        steps.append(step)
    pipe = None
    if m_ok:
        try:
            pipe = _qtr_pipe(c, steps)
        except Exception as e:
            pipe = {"error": "파이프라인 계산 실패: %s" % e}
    return {"code": c["code"], "name": c["name"], "rows": rows, "steps": steps, "pipe": pipe,
            "running": run["running"], "done": run.get("done", 0), "total": run.get("total", len(pairs)),
            "err": run.get("err")}


# ---------------------------------------------------------------- 파이프라인 — 수주가 매출 · 이익 · EPS 가 되기까지의 물리적 시간
# 주가는 결국 이익(EPS) 성장에 수렴한다. 그런데 공장에서 장비가 만들어지고 납품돼 매출 · 이익으로 찍히기까지 시간이 걸린다.
# 그 앞단(수주잔고 · 선수금(계약부채) · 만들고 있는 것(재고 + 계약자산) · 설비 투자)을 분기마다 같은 판에 놓고,
# 이 회사에서 앞단이 매출을 몇 분기 앞서 왔는지(시차 상관)를 지난 기록으로 잰다. 판정은 규칙이고, 숫자는 전부 보여 준다.
PIPE_SEED = ("신사업·신제품", "연구개발")
PIPE_ORDER = ("수주·계약",)
PIPE_CAPA = ("설비·증설",)


def _mrow(m, keys=(), names=None, prefix=()):
    """매트릭스에서 줄 하나(키 · 키 접두 · 이름 정규식 순). 없으면 None."""
    rows = m.get("rows", [])
    for r in rows:
        if r["key"] in keys:
            return r
    for r in rows:
        if any(r["key"].startswith(x) for x in prefix):
            return r
    if names:
        for r in rows:
            if re.search(names, r["name"]):
                return r
    return None


def _mseries(m, row):
    labs = [p["label"] for p in m.get("periods", [])]
    if not row:
        return {}
    return {lab: row["values"][i]["v"] for i, lab in enumerate(labs) if i < len(row["values"])}


def _mfill(m, *rows):
    """여러 줄을 우선순위대로 — 분기마다 앞 줄이 비었으면 다음 줄 값(2026-10-05 감사: 줄이 있으면 전부 비어도 그 줄만 쓰던 것 —
    지배 순이익 줄의 빈 분기 때문에 '지금' 값이 몇 년 전 분기로 계산되거나 회사가 후보에서 조용히 빠졌다)."""
    out = {}
    for row in rows:
        if not row:
            continue
        for lab, v in _mseries(m, row).items():
            if v is not None and out.get(lab) is None:
                out[lab] = v
    return out


_SHEV = {"mt": None, "d": None}
# 정의는 드러켄밀러.py(가속도와 같이 쓴다). 그 모듈이 안 뜬 때(DRK None)는 서버가 죽지 않게 아무것도 안 맞는 식을 둔다
SHEV_ADJ = DRK.SHEV_ADJ if DRK is not None else re.compile(r"(?!)")     # 주가 자료(수정주가)도 같이 보정되는 사건
SHEV_MIX = DRK.SHEV_MIX if DRK is not None else re.compile(r"(?!)")     # 주가 보정 없이 주식 수만 바뀌는 사건


def _share_events(code):
    """그 회사의 주식 수 사건 공시 [(YYYYMMDD, 제목)] — .cache/공시목록(B · I) 에서 한 번 모아 둔다(DART 호출 없음).
    종속회사 · 자회사 사건은 뺀다. 공시목록은 도구/공시목록_수집.py 가 분기마다 채운다."""
    base = os.path.join(CACHE_DIR, "공시목록")
    idx = os.path.join(base, "_주식수사건.json")
    try:
        files = [f for f in os.listdir(base) if f.endswith(".jsonl") and f[:2] in ("B_", "I_")]
    except OSError:
        return []
    mt = max((os.path.getmtime(os.path.join(base, f)) for f in files), default=0)
    if _SHEV["mt"] != mt:
        d = None
        try:
            if os.path.exists(idx) and os.path.getmtime(idx) >= mt:
                with open(idx, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
        except Exception:
            d = None
        if d is None:
            d = {}
            for f in files:
                with open(os.path.join(base, f), "r", encoding="utf-8") as fh:
                    for line in fh:
                        if not any(w in line for w in ("증자결정", "분할결정", "병합결정", "감자결정", "합병결정", "주식교환")):
                            continue
                        try:
                            x = json.loads(line)
                        except Exception:
                            continue
                        nm = re.sub(r"\[[^\]]*\]", "", x.get("report_nm") or "").strip()
                        sc = (x.get("stock_code") or "").strip()
                        if not sc or "종속회사" in nm or "자회사" in nm:
                            continue
                        if SHEV_ADJ.search(nm) or SHEV_MIX.search(nm):
                            d.setdefault(sc, []).append([x.get("rcept_dt"), nm])
            for v in d.values():
                v.sort()
            try:
                with open(idx, "w", encoding="utf-8") as fh:
                    json.dump(d, fh, ensure_ascii=False)
            except Exception:
                pass
        _SHEV.update(mt=mt, d=d)
    return [tuple(x) for x in (_SHEV["d"] or {}).get(code, [])]


def _qshift(lab, k):
    y, q = int(lab[:4]), int(lab[5]) - k
    while q <= 0:
        y, q = y - 1, q + 4
    while q > 4:
        y, q = y + 1, q - 4
    return "%dQ%d" % (y, q)


def _corr(a, b):
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** 0.5


# ---------------------------------------------------------------- 수주 공시 — 거래소 수시공시 '단일판매ㆍ공급계약체결'
# 분기보고서의 수주잔고는 최대 석 달 늦다. 그 사이 큰 계약(최근 매출의 5% · 대기업 2.5% 이상)은 계약일에 바로 공시된다.
# 목록은 DART list.json(회사 고유번호 · 거래소공시, 2014년부터, 12시간 캐시), 금액 · 상대 · 기간은 공시 원문(시너지.contract, 영구 캐시).
# 기재정정은 같은 계약의 나중 수정이라 흐름에서 뺀다. 해지는 건수만 센다(금액 칸 양식이 달라 아직 안 읽는다).
ORD_DIR = os.path.join(CACHE_DIR, "수주공시")
ORD_RX = re.compile(r"단일판매.?공급계약\s*(체결|해지)")


def _ord_list(c, ttl=12 * 3600, net=True):
    path = os.path.join(ORD_DIR, c["code"] + ".json")
    d = {"fetched": None, "ts": 0, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        pass
    if not net or (d.get("fetched") and time.time() - d.get("ts", 0) < ttl):
        return d.get("items", [])
    corp = corp_code_of(c["code"]) if FIN is not None else None
    if not corp:
        return d.get("items", [])
    import requests
    today = dt.date.today().strftime("%Y%m%d")
    bgn = (dt.datetime.strptime(d["fetched"], "%Y%m%d") - dt.timedelta(days=10)).strftime("%Y%m%d") if d.get("fetched") else "20140101"
    have = {x["rcept"] for x in d.get("items", [])}
    new = []
    try:
        for page in range(1, 80):
            js = requests.get("https://opendart.fss.or.kr/api/list.json", timeout=60, params={
                "crtfc_key": FIN.API_KEY, "corp_code": corp, "bgn_de": bgn, "end_de": today,
                "pblntf_ty": "I", "page_no": page, "page_count": 100}).json()
            if js.get("status") == "013":
                break
            if js.get("status") != "000":
                return d.get("items", [])          # 한도 · 점검 — 있던 것만
            for x in js.get("list") or []:
                nm = (x.get("report_nm") or "").strip()
                if ORD_RX.search(nm) and x.get("rcept_no") not in have:
                    new.append({"rcept": x["rcept_no"], "date": x["rcept_dt"], "nm": nm})
                    have.add(x["rcept_no"])
            if page >= int(js.get("total_page", 1)):
                break
            time.sleep(0.1)
    except Exception:
        return d.get("items", [])
    d["items"] = sorted(d.get("items", []) + new, key=lambda x: x["date"])
    d.update(fetched=today, ts=time.time())
    os.makedirs(ORD_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False)
    return d["items"]


def _ord_need(c):
    """수주 공시 목록을 아직 안 받았거나, 원문(금액)을 못 읽은 체결 공시가 남았나."""
    if not os.path.exists(os.path.join(ORD_DIR, c["code"] + ".json")):
        return True
    for it in _ord_list(c, net=False):
        if "정정" in it["nm"] or "해지" in it["nm"]:
            continue
        if not os.path.exists(os.path.join(CACHE_DIR, "시너지", "계약", it["rcept"] + ".json")):
            return True
    return False


def _ord_series(c, budget=0, net=True):
    """수주 공시 목록 + 원문 금액. budget = 이번에 새로 읽을 원문 수(나머지는 캐시에 있는 것만). [{date, kind, amount, …}]"""
    out = []
    for it in _ord_list(c, net=net):
        if "정정" in it["nm"]:
            continue
        kind = "해지" if "해지" in it["nm"] else "체결"
        det = None
        cp = os.path.join(CACHE_DIR, "시너지", "계약", it["rcept"] + ".json")
        if os.path.exists(cp):
            try:
                with open(cp, "r", encoding="utf-8") as fh:
                    det = json.load(fh)
            except Exception:
                det = None
        elif budget > 0 and kind == "체결" and SYN is not None and net:
            try:
                det = SYN.contract(FIN.API_KEY, it["rcept"])
            except Exception:
                det = None
            budget -= 1
        det = det or {}
        out.append({"date": it["date"], "rcept": it["rcept"], "kind": kind, "sub": "자회사" in it["nm"],
                    "amount": det.get("amount") if kind == "체결" else None, "read": bool(det),
                    "party": det.get("party"), "title": det.get("title"), "pct": det.get("pct"),
                    "start": det.get("start"), "end": det.get("end")})
    return out


BTB_QS = 12     # 북투빌 심화 — 최근 3년(12분기)


def btb_view(code):
    """북투빌 심화(2026-10-03) — 최근 3년 분기마다 신규수주(추정) = 잔고 증가 + 그 분기 매출, 북투빌 = 신규수주 ÷ 매출.
    한 분기 값은 대형 수주 한 건에 튀므로 4분기 합 북투빌 · 연속 분기 · 가장 큰 분기를 뺀 값 · 잔고 ÷ 연매출(몇 년 치 일감)을 같이 보고,
    잔고가 매출보다 더 줄어든 분기(취소 · 이연 · 환율 · 범위 조정)와 계약 해지 공시를 센다. 업종 간 비교는 하지 않고 같은 업종 안 위치만 적는다
    (회사마다 수주 인식 기준이 달라서)."""
    c = company_by_code(code)
    corp = corp_code_of(code) if c and FIN is not None else None
    if not c or not corp or BACK is None:
        return {"error": "회사 또는 수주잔고 자료가 없다"}
    try:
        pts = BACK.company_series(c, read_section, max_reports=20)
    except Exception:
        pts = []
    blog, meta = {}, {}
    for pt in pts:
        if pt["stamp"][5:] in Q_OF_MONTH:
            lab = "%sQ%d" % (pt["stamp"][:4], Q_OF_MONTH[pt["stamp"][5:]])
            blog[lab], meta[lab] = pt["value"], pt
    if len(blog) < 2:
        return {"error": "수주잔고를 읽은 보고서가 %d개뿐이다" % len(blog)}
    mi = matrix_cached(c, corp, "IS", "q", IS_YEARS)
    rev = {k: v for k, v in _mseries(mi, _mrow(mi, ("t:Revenue",), r"^(매출액|수익\(매출액\)|영업수익|매출)$")).items() if v}
    qn = lambda k: int(k[:4]) * 4 + int(k[5])
    last = max(blog, key=qn)
    labs = [_qshift(last, k) for k in range(BTB_QS - 1, -1, -1)]

    def rsum(a, k):   # a 분기를 끝으로 k 분기 매출 합(빠진 분기가 있으면 None)
        vs = [rev.get(_qshift(a, i)) for i in range(k)]
        return sum(vs) if all(v is not None for v in vs) else None
    qend = lambda lab: "%s%s" % (lab[:4], {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[int(lab[5])])
    ords = _ord_series(c, net=False)
    # 잔고를 읽은 방식 — 본문 문장('수주잔고는 약 18조원')과 표 합계는 범위가 다를 수 있다(현대로템: 문장 18.8조 · 표 11.3조).
    # 방식이 바뀐 두 분기 사이의 잔고 증가는 수주가 아니라 기준 변화라 북투빌에서 뺀다
    # 표 안에서도 '합계' 줄과 '행 합산'은 범위가 다르다(전 종목: 표·합계 → 표·행합산으로 바뀐 22번 중 16번이 1.8배 넘게 튐) — 방식 이름 전체로 가른다
    fam = lambda lab: None if lab not in meta else (meta[lab].get("method") or "")
    rows = []
    for lab in labs:
        b, r = blog.get(lab), rev.get(lab)
        x = {"q": lab, "rev": r, "blog": b, "new": None, "bb": None, "span": None, "bb4": None, "cover": None,
             "verified": bool(meta.get(lab, {}).get("verified")), "method": meta.get(lab, {}).get("method"),
             "basis": fam(lab), "brk": False}
        if b is not None:
            # 직전에 잔고를 읽은 분기(반기 · 사업보고서만 적는 회사는 2~4분기 건너뛴다) — 그 사이 매출을 다 더해 구간 북투빌
            k = next((k for k in range(1, 5) if blog.get(_qshift(lab, k)) is not None), None)
            rs = rsum(lab, k) if k else None
            if k and fam(_qshift(lab, k)) != fam(lab):
                x["brk"] = True
            elif k and rs:
                x.update(span=k, new=b - blog[_qshift(lab, k)] + rs, bb=(b - blog[_qshift(lab, k)] + rs) / rs)
            r4, b4 = rsum(lab, 4), blog.get(_qshift(lab, 4))
            if r4:
                x["cover"] = b / r4
                if b4 is not None and fam(_qshift(lab, 4)) == fam(lab):
                    x["bb4"] = (b - b4 + r4) / r4
        lo, hi = qend(_qshift(lab, 1)), qend(lab)
        inq = [o for o in ords if lo < o["date"] <= hi and not o["sub"]]
        x["ord_n"] = sum(1 for o in inq if o["kind"] == "체결")
        x["ord_amt"] = sum(o["amount"] or 0 for o in inq if o["kind"] == "체결") or None
        x["ord_big"] = max((o["amount"] or 0 for o in inq if o["kind"] == "체결"), default=0) or None
        x["cancel"] = [{"date": o["date"], "rcept": o["rcept"]} for o in inq if o["kind"] == "해지"]
        rows.append(x)
    # ---- 읽기 — 볼 때 주의할 점 네 가지에 맞춰
    q1 = [x for x in rows if x["bb"] is not None and x["span"] == 1]
    has4 = [x for x in rows if x["bb4"] is not None]
    st4 = 0
    for x in reversed(rows):
        if x["bb4"] is None or x["bb4"] < 1:
            break
        st4 += 1
    stq = 0
    for x in reversed([x for x in rows if x["bb"] is not None]):
        if x["bb"] < 1:
            break
        stq += 1
    newq = [x for x in rows if x["new"] is not None]
    pos_sum = sum(x["new"] for x in newq if x["new"] > 0)
    big = max(newq, key=lambda x: x["new"]) if newq else None
    last4 = [x for x in rows[-4:] if x["new"] is not None and x["span"] == 1 and x["rev"]]
    ex_big = None
    if len(last4) == 4:
        m = max(last4, key=lambda x: x["new"])
        rest = [x for x in last4 if x is not m]
        ex_big = {"q": m["q"], "bb": sum(x["new"] for x in rest) / sum(x["rev"] for x in rest)}
    neg = [x for x in newq if x["new"] < 0]
    cancels = [c_ for x in rows for c_ in x["cancel"]]
    srt = sorted(x["bb"] for x in newq)
    med = srt[len(srt) // 2] if srt else None
    cov = [x for x in rows if x["cover"] is not None]
    # 같은 업종 안 위치 — 시너지(수주잔고 증가) 목록의 1년 북투빌 · 잔고 ÷ 연매출, 믿을 만한 회사만
    with SYNERGY_LOCK:
        srows = list(SYNERGY["rows"])
    if not srows:
        synergy_view()          # 뷰어를 막 켰으면 목록이 비어 있다 — 모으기 시작만 하고 이번엔 업종 비교를 비운다
    me = next((r for r in srows if r["code"] == code), None)
    ind = (me or {}).get("industry") or ((sector_map() or {}).get("stocks", {}).get(code.upper(), {}) or {}).get("industry")
    peers = [r for r in srows if r.get("industry") == ind and not r.get("why_not") and r.get("btb") is not None]
    peer = None
    if ind and len(peers) >= 3:
        pb = sorted(peers, key=lambda r: -r["btb"])
        pc = sorted([r for r in peers if r.get("cover") is not None], key=lambda r: -r["cover"])
        peer = {"industry": ind, "n": len(peers),
                "rank_btb": next((i + 1 for i, r in enumerate(pb) if r["code"] == code), None),
                "rank_cover": next((i + 1 for i, r in enumerate(pc) if r["code"] == code), None),
                "med_btb": pb[len(pb) // 2]["btb"], "med_cover": pc[len(pc) // 2]["cover"] if pc else None,
                "list": [{"code": r["code"], "name": r["name"], "btb": r["btb"], "cover": r.get("cover")} for r in pb[:8]]}
    eok = lambda v: "{:,.0f}억".format(v / 1e8) if abs(v) < 1e12 else "{:.1f}조".format(v / 1e12)
    ql = lambda q: "%s.%sQ" % (q[2:4], q[5])
    notes = []
    # 1. 추세
    if has4:
        notes.append({"k": "추세", "t": "4분기 합 북투빌 %.2f(%s) — %s. 분기 단독은 %d분기 중 %d번 1 이상, 중앙값 %s."
                      % (has4[-1]["bb4"], ql(has4[-1]["q"]),
                         ("최근 %d분기 연속 1 이상" % st4) if st4 else "지금은 1 아래" if rows[-1]["bb4"] is not None else
                         "최근 분기는 잔고를 읽은 방식이 1년 전과 달라 못 잰다" if fam(_qshift(last, 4)) not in (None, fam(last)) else
                         "최근 분기는 못 잰다(%s)" % ("1년 전 잔고가 없다" if blog.get(_qshift(last, 4)) is None else "매출이 빈 분기가 있다"),
                         len(newq), sum(1 for x in newq if x["bb"] >= 1),
                         "—" if med is None else "%.2f" % med),
                      "ok": st4 >= 4})
    # 2. 덩어리
    if big and pos_sum > 0:
        sh = big["new"] / pos_sum * 100
        t = "가장 큰 분기 %s 신규수주 %s — 3년 합의 %.0f%%." % (ql(big["q"]), eok(big["new"]), sh)
        if big.get("ord_big"):
            t += " 그 분기 최대 단일 공시 %s." % eok(big["ord_big"])
        if ex_big:
            t += " 최근 4분기에서 가장 큰 분기(%s)를 빼면 북투빌 %.2f." % (ql(ex_big["q"]), ex_big["bb"])
        notes.append({"k": "덩어리", "t": t, "ok": sh < 30 and (ex_big is None or ex_big["bb"] >= 1)})
    # 3. 취소 · 이연
    t = ("잔고가 매출보다 더 줄어든 분기 %d번(%s) — 계약 취소 · 이연 · 환율 · 범위 조정일 수 있다. " % (
        len(neg), ", ".join("%s %s" % (ql(x["q"]), eok(x["new"])) for x in neg)) if neg else "잔고가 매출보다 더 줄어든 분기 없음. ")
    t += ("수주 계약 해지 공시 %d건(%s)." % (len(cancels), ", ".join(c_["date"][:4] + "." + c_["date"][4:6] for c_ in cancels))
          if cancels else "3년 안 수주 계약 해지 공시 없음.")
    notes.append({"k": "취소·이연", "t": t, "ok": not neg and not cancels})
    # 4. 일감(잔고 ÷ 연매출)
    if cov:
        a = cov[-1]["cover"]
        b1 = next((x["cover"] for x in cov if x["q"] == _qshift(cov[-1]["q"], 4)), None)
        b3 = cov[0]["cover"] if cov[0] is not cov[-1] else None
        notes.append({"k": "일감", "t": "잔고 = 연매출의 %.1f년 치%s%s." % (
            a, "" if b1 is None else " (1년 전 %.1f년" % b1 + (", %s %.1f년)" % (ql(cov[0]["q"]), b3) if b3 is not None else ")"),
            "" if b1 is None else (" — 일감이 늘고 있다" if a > b1 * 1.05 else " — 일감이 줄고 있다" if a < b1 * 0.95 else " — 일감이 제자리")),
            "ok": b1 is None or a >= b1 * 0.95})
    # 5. 같은 업종 안
    if peer:
        notes.append({"k": "업종 안", "t": "%s 수주 회사 %d곳 중 1년 북투빌 %s위(중앙 %.2f) · 잔고 ÷ 연매출 %s위(중앙 %s). 업종이 다르면 수주 인식 기준이 달라 견주지 않는다."
                      % (peer["industry"], peer["n"], peer["rank_btb"] or "—", peer["med_btb"], peer["rank_cover"] or "—",
                         "—" if peer["med_cover"] is None else "%.1f년" % peer["med_cover"]),
                      "ok": bool(peer["rank_btb"] and peer["rank_btb"] <= (peer["n"] + 1) // 2)})
    elif not srows:
        notes.append({"k": "업종 안", "t": "수주잔고 목록을 모으는 중 — 몇 분 뒤 다시 펼치면 같은 업종 안 위치가 나온다.", "ok": None})
    elif ind:
        notes.append({"k": "업종 안", "t": "%s에서 잔고를 믿을 만하게 읽은 회사가 %d곳뿐이라 견주지 않는다. 업종이 다르면 수주 인식 기준이 달라 견주지 않는다." % (ind, len(peers)), "ok": None})
    brk = [x for x in rows if x["brk"]]
    if brk:
        notes.append({"k": "기준 바뀜", "t": "잔고를 읽은 방식이 바뀐 분기 %d번(%s — 본문 문장 · 표 합계 줄 · 표 행 합산은 범위가 다를 수 있다). 그 사이 잔고 증가는 수주가 아니라 기준 변화라 북투빌에서 뺐다."
                      % (len(brk), ", ".join("%s %s" % (ql(x["q"]), x["basis"]) for x in brk)), "ok": False})
    # 목록 표의 '북투빌'(시너지 행 btb)은 '보고서 4개 전' 잔고와 비교한다 — 빠진 분기가 있으면 1년보다 긴 구간, 방식이 바뀌면 다른 기준끼리 비교가 된다
    rb, lb = (me or {}).get("btb"), rows[-1]["bb4"]
    if rb is not None and (lb is None or abs(rb - lb) >= 0.1):
        why = []
        ks = sorted(blog, key=qn)
        p4 = ks[-5] if len(ks) >= 5 else None
        if p4 and p4 != _qshift(last, 4):
            why.append("보고서 4개 전이 %s — 잔고를 못 읽은 분기가 있어 %d분기 구간을 쟀다" % (ql(p4), qn(last) - qn(p4)))
        if p4 and fam(p4) != fam(last):
            why.append("잔고를 읽은 방식이 다른 두 시점(%s %s · %s %s)을 비교했다" % (ql(p4), fam(p4), ql(last), fam(last)))
        mb_ = (me or {}).get("backlog")
        if mb_ and not any(abs(v / mb_ - 1) < 0.01 for v in blog.values() if v):
            why.append("목록이 쓰는 최신 잔고: %s(%s). 3년 치로 보면 검산이 안 된 데다 다른 분기와 크게 어긋나 여기선 뺐다 — 잔고를 잘못 읽었을 수 있다"
                       % (eok(mb_), (me or {}).get("quarter") or ""))
        r4l, rtl = rsum(last, 4), (me or {}).get("rev_ttm")
        if not why and r4l is None:
            why.append("여기선 최근 4분기 매출 중 빈 분기가 있어 못 잰다(분기 재무 미수집)")
        if not why and r4l and rtl and abs(r4l / rtl - 1) > 0.1:
            why.append("나누는 매출(최근 4분기 합)이 다르다 — 목록 %s · 여기 %s" % (eok(rtl), eok(r4l)))
        notes.append({"k": "표 값", "t": "목록의 북투빌(%.2f) — '보고서 4개 전' 잔고와 비교한 값%s. 같은 분기 · 같은 방식으로 맞춘 4분기 합: %s."
                      % (rb, (". " + " · ".join(why)) if why else "", "잴 수 없음" if lb is None else "%.2f" % lb), "ok": False})
    n_ver = sum(1 for x in rows if x["blog"] is not None and x["verified"])
    n_b = sum(1 for x in rows if x["blog"] is not None)
    fx = any((x["method"] or "").startswith("표(외화)") for x in rows)
    notes.append({"k": "자료", "t": "잔고 = 정기보고서 「사업의 내용」 수주상황(표 산술 검산 %d/%d 분기)%s. 신규수주는 공시값이 아니라 잔고 증가 + 매출로 거꾸로 구한 추정이다 — 환율 · 계약 변경도 섞인다."
                  % (n_ver, n_b, " · 외화 표 있음" if fx else "") + " 매출은 연결 전체라 수주 사업이 일부인 회사(지주사 등)는 북투빌이 1 쪽으로 눌린다." + (" 잔고를 반기·연 단위로만 적는 분기는 그 사이 매출을 묶어 잰다." if any((x["span"] or 1) > 1 for x in rows) else ""),
                  "ok": None})
    return {"code": code, "name": c["name"], "rows": rows, "notes": notes, "peer": peer, "peer_pending": not srows,
            "streak4": st4, "median": med}


def _pipe_rows(c, mi, mb, mc, px=None, blog_pts=None, orders=None, macro=None):
    """분기별 파이프라인 숫자 {labs, rows, px, hist_per}. 탭(_qtr_pipe)과 검증 도구(도구/분기변화_백테스트.py)가 같이 쓴다.
    px(주가 {d, p, r}) · blog_pts(수주잔고 시계열)를 주면 그것을 쓴다(검증 도구는 캐시만 읽는다)."""
    labs = [p["label"] for p in mi.get("periods", [])]
    if not labs:
        return None
    # 매출 — 회사가 태그를 바꿔 적는다(칩스앤미디어 2025.4Q~ '영업수익'을 GrossProfit 태그로). 분기마다 빈 곳을 이름 줄로 채운다
    rev = _mfill(mi, _mrow(mi, ("t:Revenue",), None),
                 *[r for r in mi.get("rows", []) if re.search(r"^(매출액|수익\(매출액\)|영업수익|매출)$", r["name"])])
    op = _mseries(mi, _mrow(mi, ("t:OperatingIncomeLoss",), r"^영업(이익|손익|손실)"))
    # 지배주주 순이익 — 분기마다: 지배 줄 → 없으면 (당기순이익 − 비지배 몫) (비츠로셀: 지배 줄이 2022Q3 뒤 비어 '지금'이 2022Q2 였다)
    ni = dict(_mseries(mi, _mrow(mi, ("t:ProfitLossAttributableToOwnersOfParent",), None)))
    tot_ = _mseries(mi, _mrow(mi, ("t:ProfitLoss",), r"^당기순(이익|손익|손실)"))
    nci_ = _mseries(mi, _mrow(mi, (), r"비지배", ("t:ProfitLossAttributableToNoncontrollingInterest",)))
    for lab_ in labs:
        if ni.get(lab_) is None and tot_.get(lab_) is not None:
            ni[lab_] = tot_[lab_] - (nci_.get(lab_) or 0)
    # EPS — 회사가 해마다 줄 이름을 바꿔 적는다(LS일렉트릭: '계속영업 기본 및 희석주당이익' · '계속영업과 중단영업 …').
    # 같은 뜻의 줄을 우선순위대로 훑어 분기마다 처음 나온 값을 쓴다(중단영업 줄은 뺀다)
    eps = {}
    cand = sorted([r for r in mi.get("rows", []) if (r["key"].startswith("t:BasicEarningsLossPerShare")
                   or re.search(r"기본.*주당.*(이익|손익|손실)", r["name"])) and "중단영업" not in r["name"]],
                  key=lambda r: (r["key"] != "t:BasicEarningsLossPerShare", "계속영업과" not in r["name"] and "계속영업" in r["name"]))
    cont = {}
    for r in cand:
        for lab, v in _mseries(mi, r).items():
            if v is not None and eps.get(lab) is None:
                eps[lab] = v
                cont[lab] = "계속영업" in r["name"] and "계속영업과" not in r["name"]
    # 계속영업 EPS 만 적힌 분기에 중단영업 EPS 가 있으면 더한다 — 순이익(중단영업 포함)과 기준을 맞춘다
    # (카카오 2026Q2: 계속영업 EPS 390원 × 순이익 163억(중단 −1,560억 포함)로 주식 수가 0.11배 → '9:1 병합'으로 오판, PER 4.3배 · 실제 약 42배)
    disc = {}
    for r in mi.get("rows", []):
        if "중단영업" in r["name"] and "계속영업" not in r["name"] and re.search(r"기본.*주당|주당.*기본", r["name"]):
            for lab, v in _mseries(mi, r).items():
                if v is not None:
                    disc.setdefault(lab, v)
    for lab, v in disc.items():
        if cont.get(lab) and eps.get(lab) is not None:
            eps[lab] += v
    # 액면분할 · 병합 — 분기마다 주식 수(지배주주 순이익 ÷ EPS)를 거꾸로 구해, 한 분기에 1.8배 넘게 뛰거나 0.56배 밑으로 줄면
    # 분할 · 병합으로 보고 그 전 EPS 를 지금 주식 수 기준으로 나눈다(LS일렉트릭 2026.2분기 5:1 — 주가 자료는 이미 지금 기준이라
    # EPS 만 옛 기준으로 남아 PER 이 5배 작게 나왔다). 빈 분기(4분기 단독을 못 뗀 해 등)는 순이익 ÷ 가까운 분기 주식 수로 채운다.
    sh = {lab: ni[lab] / eps[lab] for lab in labs if ni.get(lab) and eps.get(lab) and ni[lab] / eps[lab] > 0}
    # 규칙 본체(한 분기 튐 제거 · 1.8/0.56 · 공시 확인 시 1.25/0.8 · 증자 섞임 cut · 분할 같은가)는 DRK.share_basis — 가속도(DRK.per_share)와 같이 쓴다
    sev = _share_events(c["code"])
    rx_ = re.compile(r"액면\s*분할|주식\s*분할|액면\s*병합|주식\s*병합|무상\s*증자")

    def cnt(lab):
        """그 분기 보고서 개요(자본금 변동 표)의 분할 · 병합 · 무상증자 낱말 수 — 보고서가 없으면 None"""
        st_ = "%s-%02d" % (lab[:4], int(lab[5]) * 3)
        rep = next((r for r in c["reports"] if r["stamp"] == st_ and not r["tag"]), None)
        if not rep:
            return None
        return sum(len(rx_.findall(read_section(c, rep, sec["file"]))) for sec in rep["sections"] if "개요" in sec["title"])
    sb = DRK.share_basis(sh, sev, cnt)
    sh_now, splits, cut = sb["now"], sb["splits"], sb["cut"]      # 지금 기준 주식 수 · 분할 목록 · 앞 기록 제외 기준
    qn = lambda k: int(k[:4]) * 4 + int(k[5])
    for lab in labs:
        if ni.get(lab) is None:
            continue
        if lab in sh_now:
            eps[lab] = ni[lab] / sh_now[lab]
        elif sh_now:
            near = min(sh_now, key=lambda k: abs(qn(k) - qn(lab)))
            if abs(qn(near) - qn(lab)) <= 4:
                eps[lab] = ni[lab] / sh_now[near]
    # 계약부채(유동 + 비유동) — 없으면 선수금
    liab = {}
    for r in mb.get("rows", []):
        if "ContractLiabilit" in r["key"] or re.match(r"^(유동|비유동)?\s*계약부채$", r["name"]):
            for lab, v in _mseries(mb, r).items():
                if v is not None:
                    liab[lab] = liab.get(lab, 0) + v
    if not liab:
        liab = {k: v for k, v in _mseries(mb, _mrow(mb, (), r"^선수금$")).items() if v is not None}
    inv = _mseries(mb, _mrow(mb, ("t:Inventories",), r"^재고자산$"))
    # ROE 의 분모 — 지배기업 소유주 자본(없으면 자본총계)
    eq = _mfill(mb, _mrow(mb, ("t:EquityAttributableToOwnersOfParent",), r"지배기업.*(소유주|귀속)"),
                _mrow(mb, ("t:Equity",), r"^자본\s*총계$"))
    ca = {}
    for r in mb.get("rows", []):
        if "ContractAsset" in r["key"] or re.match(r"^(유동|비유동|장기)?\s*계약자산$|미청구공사", r["name"]):
            for lab, v in _mseries(mb, r).items():
                if v is not None:
                    ca[lab] = ca.get(lab, 0) + v
    wip = {lab: (inv.get(lab) or 0) + (ca.get(lab) or 0) for lab in labs if inv.get(lab) is not None or ca.get(lab) is not None}
    capex = _mseries(mc, _mrow(mc, (), None, ("t:PurchaseOfPropertyPlantAndEquipment",)))
    # 구루 렌즈 검증용 — 영업현금흐름(멍거 '이익의 현금화'), 부채 · 자본총계(부채비율), 매출채권(회수 지연)
    cfo = _mseries(mc, _mrow(mc, ("t:CashFlowsFromUsedInOperatingActivities",), r"^영업활동\s*(으로\s*인한\s*)?현금\s*흐름"))
    debt = _mseries(mb, _mrow(mb, ("t:Liabilities",), r"^부채\s*총계$"))
    eqt = _mseries(mb, _mrow(mb, ("t:Equity",), r"^자본\s*총계$"))
    recv = _mseries(mb, _mrow(mb, ("t:TradeAndOtherCurrentReceivables",), r"^매출채권"))
    # 수주잔고(본문) — 시점 → 분기
    blog, bmeth = {}, {}
    if blog_pts is None and BACK is not None:
        try:
            blog_pts = BACK.company_series(c, read_section, max_reports=28)
        except Exception:
            blog_pts = []
    if blog_pts:
        try:
            for pt in blog_pts:
                if pt["stamp"][5:] in Q_OF_MONTH:
                    k_ = "%sQ%d" % (pt["stamp"][:4], Q_OF_MONTH[pt["stamp"][5:]])
                    blog[k_], bmeth[k_] = pt["value"], pt.get("method") or ""
        except Exception:
            blog = {}
    # 주가 — 분기 말 종가(보정 p · 그날 실제 r)
    px = px if px is not None else (_inv_prices(c["code"]) or {})
    import bisect

    def price_at(lab, raw=False):
        if not px:
            return None
        y, q = int(lab[:4]), int(lab[5])
        d = int("%d%s" % (y, {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[q]))
        i = bisect.bisect_right(px["d"], d) - 1
        if i < 0 or d - px["d"][i] > 20:
            return None
        return (px["r"] if raw else px["p"])[i]

    def ttm(ser, lab):
        vs = [ser.get(_qshift(lab, k)) for k in range(4)]
        return sum(vs) if all(v is not None for v in vs) else None

    def yoy(a, b):
        return (a / b - 1) * 100 if a is not None and b is not None and b > 0 and a >= 0 else (
            (a - b) / abs(b) * 100 if a is not None and b not in (None, 0) and b < 0 else None)

    # 수주 공시 — 공시일이 속한 분기로 모은다(금액을 못 읽은 건은 건수만)
    oq, on, ou, otop = {}, {}, {}, {}
    for o in orders or []:
        if o["kind"] != "체결":
            continue
        lab_o = "%sQ%d" % (o["date"][:4], (int(o["date"][4:6]) - 1) // 3 + 1)
        on[lab_o] = on.get(lab_o, 0) + 1
        if o.get("amount"):
            oq[lab_o] = oq.get(lab_o, 0) + o["amount"]
            otop.setdefault(lab_o, []).append(o)
        elif not o.get("read"):
            ou[lab_o] = ou.get(lab_o, 0) + 1
    first_o = min((o["date"] for o in orders or []), default=None)
    rows = {}
    for lab in labs:
        rt, ot, nt, ct, et = ttm(rev, lab), ttm(op, lab), ttm(ni, lab), ttm(capex, lab), ttm(eps, lab)
        ly = _qshift(lab, 4)
        pr, pr_ly = price_at(lab), price_at(ly)
        # EPS 는 위에서 지금 주식 수 기준으로 맞췄다 — 증가율 · PER 모두 그 기준(주가도 보정 종가)
        et_ly = ttm(eps, ly)
        ea, eb = et, et_ly
        prr = price_at(lab, True)
        rows[lab] = {
            "rev_ttm": rt, "rev_yoy": yoy(rt, ttm(rev, ly)),
            "op_ttm": ot, "op_yoy": yoy(ot, ttm(op, ly)) if ot is not None and ot > 0 else None,
            "ni_ttm": nt, "ni_yoy": yoy(nt, ttm(ni, ly)) if nt is not None and nt > 0 else None,
            "eps_ttm": et, "per": (pr / et) if pr and et and et > 0 else None,
            "eps_ttm_ly": et_ly, "eps_yoy": yoy(ea, eb) if ea is not None and ea > 0 else None,
            # 1년 전과 읽은 방식(문장 · 표·합계 · 표·행합산 …)이 다르면 범위가 달라 증가율을 비운다(수주.py trend 와 같은 규칙)
            "blog": blog.get(lab), "blog_yoy": yoy(blog.get(lab), blog.get(ly)) if bmeth.get(lab) == bmeth.get(ly) else None,
            "cover": (blog.get(lab) / rt) if blog.get(lab) and rt else None,
            "liab": liab.get(lab), "liab_yoy": yoy(liab.get(lab), liab.get(ly)),
            "wip": wip.get(lab), "wip_yoy": yoy(wip.get(lab), wip.get(ly)),
            "capex_ttm": ct, "capex_yoy": yoy(ct, ttm(capex, ly)),
            "px": pr, "px_yoy": yoy(pr, pr_ly),
        }
        # ROE = 지배주주 순이익(최근 4분기) ÷ 지배주주 자본(지금 · 1년 전 분기 말 평균)
        e0, e1 = eq.get(lab), eq.get(ly)
        eav = (e0 + e1) / 2 if e0 and e1 and e0 > 0 and e1 > 0 else (e0 if e0 and e0 > 0 else None)
        rows[lab]["equity"] = e0
        rows[lab]["roe"] = (nt / eav * 100) if nt is not None and eav else None
        # 주식 수(지금 기준) — 가까운 분기의 순이익 ÷ EPS. 시가총액 · PSR 을 낼 때 쓴다
        if sh_now:
            near = min(sh_now, key=lambda k: abs(qn(k) - qn(lab)))
            rows[lab]["shares"] = sh_now[near] if abs(qn(near) - qn(lab)) <= 4 else None
        rows[lab].update(cfo_ttm=ttm(cfo, lab), debt=debt.get(lab), eq_total=eqt.get(lab), recv=recv.get(lab), inv=inv.get(lab))
        if orders is not None and first_o and lab >= "%sQ%d" % (first_o[:4], (int(first_o[4:6]) - 1) // 3 + 1):
            o4 = sum(oq.get(_qshift(lab, k), 0) for k in range(4))
            o4l = sum(oq.get(_qshift(ly, k), 0) for k in range(4))
            rows[lab].update(ord_q=oq.get(lab, 0), ord_n=on.get(lab, 0), ord_unread=ou.get(lab, 0), ord_ttm=o4,
                             ord_yoy=yoy(o4, o4l) if o4l > 0 else None, ord_cover=(o4 / rt * 100) if rt else None,
                             ord_top=[{k: x.get(k) for k in ("party", "title", "amount", "date")}
                                      for x in sorted(otop.get(lab, []), key=lambda z: -(z["amount"] or 0))[:2]])
    # 업황 — 업종 제품의 수출물가(ECOS) · 출하 · 재고 지수(KOSIS), 분기 석 달 평균의 전년 대비
    if macro:
        def qavg(ser, lab_):
            y_, q_ = int(lab_[:4]), int(lab_[5])
            vs = [ser.get("%d%02d" % (y_, (q_ - 1) * 3 + m)) for m in (1, 2, 3)]
            return sum(vs) / 3 if ser and all(v is not None for v in vs) else None
        pr_, sh_, iv_ = macro.get("price") or {}, macro.get("ship") or {}, macro.get("inv") or {}
        for lab in labs:
            ly_ = _qshift(lab, 4)
            a1, a0 = qavg(pr_, lab), qavg(pr_, ly_)
            s1, s0, i1, i0 = qavg(sh_, lab), qavg(sh_, ly_), qavg(iv_, lab), qavg(iv_, ly_)
            sy = (s1 / s0 - 1) * 100 if s1 and s0 else None
            iy = (i1 / i0 - 1) * 100 if i1 and i0 else None
            rows[lab].update(mp=a1, mp_yoy=(a1 / a0 - 1) * 100 if a1 and a0 else None, ship_yoy=sy, inv_yoy=iy,
                             cyc=(sy - iy) if sy is not None and iy is not None else None)
    for lab in labs:
        a_, b_ = rows[lab].get("roe"), rows.get(_qshift(lab, 4), {}).get("roe")
        rows[lab]["roe_chg"] = (a_ - b_) if a_ is not None and b_ is not None else None
    # 값 — 그 분기에 그 가격이 비쌌나. 자기 역사 PER 백분위(그 분기까지 최근 10년, 8분기↑), 성장 대비 PER(PEG = PER ÷ 순이익 성장률,
    # 성장률은 1~100% 로 묶는다), 영업이익률이 자기 역사 어디쯤인가(꼭대기면 낮은 PER 이 함정 — 경기 순환주)
    hist_per, hist_m = [], []
    for lab in labs:
        r = rows[lab]
        opm = r["op_ttm"] / r["rev_ttm"] * 100 if r.get("op_ttm") is not None and r.get("rev_ttm") else None
        r["opm_ttm"] = opm
        per = r.get("per") if (r.get("per") or 0) > 0 else None
        if per is not None and cut is not None and qn(lab) <= cut:
            r["per"], per = None, None
        if per is not None:
            med_ = sorted(hist_per[-8:])[len(hist_per[-8:]) // 2] if len(hist_per) >= 4 else None
            ok_ = per >= 1 and (med_ is None or 0.2 <= per / med_ <= 5)
            r["per_ok"] = ok_
            if ok_:
                hist_per.append(per)
        w = hist_per[-40:]
        r["per_pct"] = (sum(1 for v in w if v <= per) / len(w) * 100) if per and len(w) >= 8 else None
        r["per_med"] = sorted(w)[len(w) // 2] if len(w) >= 8 else None
        if opm is not None:
            hist_m.append(opm)
        wm = hist_m[-40:]
        r["opm_pct"] = (sum(1 for v in wm if v <= opm) / len(wm) * 100) if opm is not None and len(wm) >= 8 else None
        g = r.get("ni_yoy")
        r["peg"] = (per / min(max(g, 1.0), 100.0)) if per and g is not None and g > 0 else None
    return {"labs": labs, "rows": rows, "px": px, "hist_per": hist_per, "splits": splits}


_QBT = {"mt": None, "d": None}


def _qtr_bt():
    p = os.path.join(QTR_DIR, "bt_report.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _QBT["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _QBT.update(d=json.load(fh), mt=mt)
        except Exception:
            return None
    return _QBT["d"]


EV_PASS = "뚜렷 · 앞뒤 기간 같은 방향"     # 통과 문구 — 90% 구간이 0을 넘고 앞뒤 기간이 같은 방향. 화면(index.html EV_PASS)도 이 문구만 색칠한다


def _ev_word(diff, ci, early, late):
    if diff is None:
        return None
    sig = bool(ci) and ci[0] is not None and ci[1] is not None and (ci[0] > 0 or ci[1] < 0)
    same = early is not None and late is not None and (early > 0) == (late > 0) == (diff > 0)
    return EV_PASS if sig and same else "뚜렷하나 기간마다 달랐다" if sig else "통계적으로 뚜렷하지 않음"


def _qtr_ev(rule=None, cat=None):
    """규칙(또는 값 묶음)의 과거 성적 — 4분기 뒤 매출 증가율 변화와 12개월 초과수익(해당 − 나머지, 중앙값)."""
    d = _qtr_bt()
    if not d:
        return None
    if cat:
        v = (d.get("val") or {}).get(cat)
        if not v:
            return None
        return {"kind": "val", "cat": cat, "n": v.get("n"), "med": v.get("med"), "ci": v.get("ci"), "hit": v.get("hit"),
                "word": ("뚜렷" if (v.get("ci") and v["ci"][0] is not None and (v["ci"][0] > 0 or v["ci"][1] < 0))
                         else "통계적으로 뚜렷하지 않음")}
    r = (d.get("rules") or {}).get(rule) or {}
    px, rv, om = r.get("ex12m") or {}, r.get("drev4") or {}, r.get("dopm4") or {}
    if px.get("diff") is None and rv.get("diff") is None:
        return None
    return {"kind": "rule", "rule": rule, "n": px.get("n_on") or rv.get("n_on"),
            "px": px.get("diff"), "px_ci": px.get("ci"), "px_word": _ev_word(px.get("diff"), px.get("ci"), px.get("early"), px.get("late")),
            "rev": rv.get("diff"), "rev_ci": rv.get("ci"), "rev_word": _ev_word(rv.get("diff"), rv.get("ci"), rv.get("early"), rv.get("late")),
            "opm": om.get("diff"), "opm_ci": om.get("ci"), "opm_word": _ev_word(om.get("diff"), om.get("ci"), om.get("early"), om.get("late"))}


def _qtr_valcat(pp_, pg):
    """값 묶음 — 도구/분기변화_백테스트.py val_cat 과 같은 이름."""
    if pp_ is None:
        return None
    band = "비싸다" if pp_ >= 70 else "싸다" if pp_ <= 30 else "보통"
    gb = None if pg is None else ("싸다" if pg < 1 else "비싸다" if pg > 2 else "보통")
    if band == "비싸다":
        return "역사·성장 모두 비싸다" if gb in ("비싸다", None) else "역사 비싸나 성장 대비 아님"
    if band == "싸다":
        return "역사·성장 모두 싸다" if gb == "싸다" else "싸지만 성장 약함"
    return "중간대 · PEG " + (gb or "없음")


def _qtr_pipe(c, steps):
    corp = corp_code_of(c["code"])
    mi = matrix_cached(c, corp, "IS", "q", IS_YEARS)
    mb = matrix_cached(c, corp, "BS", "q", QTR_YEARS)
    mc = matrix_cached(c, corp, "CF", "q", QTR_YEARS)
    orders = _ord_series(c)
    macro = None
    if MACRO is not None:
        try:
            macro = MACRO.for_company(corp, FIN.API_KEY)
        except Exception:
            macro = None
    pr = _pipe_rows(c, mi, mb, mc, orders=orders, macro=macro)
    if not pr:
        return None
    labs, rows, px, hist_per = pr["labs"], pr["rows"], pr["px"], pr["hist_per"]
    # 지금 — 오늘 종가 ÷ 최근 4분기 EPS
    now = None
    if px and px.get("r"):
        last_lab = labs[-1]
        et = rows[last_lab].get("eps_ttm")
        pn = px["p"][-1]
        per_now = pn / et if et and et > 0 else None
        w = hist_per[-40:]
        now = {"date": str(px["d"][-1]), "price": pn, "per": per_now,
               "per_pct": (sum(1 for v in w if v <= per_now) / len(w) * 100) if per_now and len(w) >= 8 else None,
               "per_med": sorted(w)[len(w) // 2] if len(w) >= 8 else None,
               "peg": (per_now / min(max(rows[last_lab]["ni_yoy"], 1.0), 100.0))
               if per_now and rows[last_lab].get("ni_yoy") and rows[last_lab]["ni_yoy"] > 0 else None,
               "opm_pct": rows[last_lab].get("opm_pct")}
    # 문장 — 보고서 쌍마다 새로 쓴 씨앗(신사업 · R&D) · 수주 · 증설 문장 수
    for st in steps:
        if not st.get("ready"):
            continue
        lab = "%sQ%d" % (st["stamp"][:4], Q_OF_MONTH[st["stamp"][5:]])
        if lab not in rows:
            continue
        cnt = {"seed": [], "order": [], "capa": []}
        for sg in st.get("signals", []):
            if sg.get("src") != "new":
                continue
            t0 = (sg.get("tags") or [None])[0]
            k = "seed" if t0 in PIPE_SEED else "order" if t0 in PIPE_ORDER else "capa" if t0 in PIPE_CAPA else None
            if k:
                cnt[k].append(sg["label"])
        rows[lab]["txt"] = cnt
    # 시차 — 앞단 지표의 전년 대비가 몇 분기 뒤 매출(최근 4분기 합)의 전년 대비와 가장 같이 움직였나
    lags = {}
    for key in ("blog_yoy", "liab_yoy", "wip_yoy", "capex_yoy"):
        best = None
        for k in range(0, 5):
            xs, ys = [], []
            for lab in labs:
                a, b = rows.get(_qshift(lab, k), {}).get(key), rows[lab].get("rev_yoy")
                if a is not None and b is not None:
                    xs.append(max(-100, min(300, a)))
                    ys.append(max(-100, min(300, b)))
            r = _corr(xs, ys) if len(xs) >= 8 else None
            if r is not None and (best is None or r > best["r"]):
                best = {"k": k, "r": round(r, 2), "n": len(xs)}
        if best:
            lags[key] = best
    show = labs[-12:]
    last = rows[labs[-1]]
    prev4 = rows.get(_qshift(labs[-1], 4), {})
    # 판정 — 규칙(문턱은 화면에 같이 적는다)
    calls = []
    ry = last.get("rev_yoy")

    def lagtxt(key):
        L = lags.get(key)
        if not L or L["r"] < 0.4:
            return "이 회사에선 시차가 뚜렷하지 않았다"
        return "이 회사에선 대개 %d분기 뒤 매출이 따라왔다(상관 %.2f, %d분기)" % (L["k"], L["r"], L["n"]) if L["k"] else \
            "이 회사에선 매출과 같은 분기에 움직였다(상관 %.2f)" % L["r"]
    for key, name in (("blog_yoy", "수주잔고"), ("liab_yoy", "선수금(계약부채)")):
        v = last.get(key)
        if v is None or ry is None:
            continue
        gap = v - ry
        short = "잔고" if key == "blog_yoy" else "선수금"
        if gap >= 15:
            calls.append({"tone": "up", "stage": "앞단", "ev": _qtr_ev(short + " > 매출 +15%p"),
                          "text": "%s %+.0f%% > 매출 %+.0f%% — 앞단이 매출보다 %.0f%%p 빨리 늘었다. 매출이 따라올 여지. %s"
                          % (name, v, ry, gap, lagtxt(key))})
        elif gap <= -15:
            calls.append({"tone": "dn", "stage": "앞단", "ev": _qtr_ev(short + " < 매출 −15%p"),
                          "text": "%s %+.0f%% < 매출 %+.0f%% — 앞단이 매출보다 %.0f%%p 느리다. 매출 둔화가 먼저 보이는 자리. %s"
                          % (name, v, ry, -gap, lagtxt(key))})
    w = last.get("wip_yoy")
    if w is not None and ry is not None and w - ry >= 20:
        lead_ok = any((last.get(k) or -1e9) >= ry for k in ("blog_yoy", "liab_yoy"))
        calls.append({"tone": "up" if lead_ok else "nu", "stage": "생산",
                      "ev": _qtr_ev("재고+계약자산 > 매출 +20%p · " + ("앞단도 늘음" if lead_ok else "앞단은 안 늘음")),
                      "text": ("재고 + 계약자산 %+.0f%% > 매출 %+.0f%% — 잔고 · 선수금도 늘어 납품을 앞둔 생산으로 보인다" if lead_ok
                               else "재고 + 계약자산 %+.0f%% > 매출 %+.0f%% — 잔고 · 선수금은 그만큼 안 늘었다. 과거엔 그래도 매출이 뒤따른 편이었지만 주가엔 차이가 없었다")
                      % (w, ry)})
    cy = last.get("capex_yoy")
    if cy is not None and cy >= 50:
        calls.append({"tone": "nu", "stage": "설비", "ev": _qtr_ev("설비 투자 +50%↑"),
                      "text": "설비 투자(최근 4분기) %+.0f%% — 다만 과거엔 4분기 안에 매출 가속으로 이어지지 않았다(증설 효과는 더 늦게 온다). %s"
                      % (cy, lagtxt("capex_yoy"))})
    ny, py = last.get("ni_yoy"), last.get("px_yoy")
    ey = last.get("eps_yoy")
    epst = (" · EPS %+.0f%%" % ey) if ey is not None else ""
    if ny is not None and py is not None:
        if ny - py >= 30:
            calls.append({"tone": "up", "stage": "가격", "ev": _qtr_ev("순이익 − 주가 ≥ +30%p (덜 따라옴)"),
                          "text": "순이익(최근 4분기) %+.0f%%%s vs 주가 %+.0f%% — 이익이 주가보다 빨리 늘었다. 가격이 덜 따라왔다%s"
                          % (ny, epst, py, (" (PER %.0f배 → %.0f배)" % (prev4["per"], last["per"])) if prev4.get("per") and last.get("per") else "")})
        elif ny - py <= -30:
            calls.append({"tone": "warn", "stage": "가격", "ev": _qtr_ev("순이익 − 주가 ≤ −30%p (앞서 감)"),
                          "text": "주가 %+.0f%% vs 순이익(최근 4분기) %+.0f%%%s — 가격이 이익보다 앞서 갔다. 앞단이 이어 줘야 정당화된다%s"
                          % (py, ny, epst, (" (PER %.0f배 → %.0f배)" % (prev4["per"], last["per"])) if prev4.get("per") and last.get("per") else "")})
    # 업황 — 가장 최근 달(분기 말 뒤 나온 달 포함)의 제품 가격 · 재고 순환
    mac = None
    if macro:
        def last_yoy(ser, n=1):
            ks_ = sorted(ser or {})
            if len(ks_) < 13:
                return None, None
            k = ks_[-1]
            cur = [ser.get(x) for x in ks_[-n:]]
            prv = [ser.get("%d%s" % (int(x[:4]) - 1, x[4:])) for x in ks_[-n:]]
            if any(v is None for v in cur + prv):
                return None, k
            return (sum(cur) / sum(prv) - 1) * 100, k
        py_, pk = last_yoy(macro.get("price"))
        sy_, sk = last_yoy(macro.get("ship"), 3)
        iy_, _ = last_yoy(macro.get("inv"), 3)
        mac = {"price_name": macro.get("price_name"), "ind_name": macro.get("ind_name"), "ksic": macro.get("ksic"),
               "mp_yoy": py_, "mp_month": pk, "ship_yoy": sy_, "inv_yoy": iy_,
               "cyc": (sy_ - iy_) if sy_ is not None and iy_ is not None else None, "cyc_month": sk}
        if now is not None:
            now.update(mp_yoy=py_, mp_month=pk, cyc=mac["cyc"], ship_yoy=sy_, inv_yoy=iy_, cyc_month=sk)
        # 업황은 회사 매출과 견줘야 신호가 된다 — 업황 숫자 하나만으로는 소음(회사 매출과의 연동도 중앙 0.02~0.18).
        # 같은 매출 묶음 안에서 업황만 다른 회사와 견준 과거 성적이 아래 검증 줄(도구/분기변화_백테스트.py RULES_IN · 도구/업황연결_분석.py)
        ry_ = last.get("rev_yoy")
        cy_ = mac["cyc"]
        if cy_ is not None and ry_ is not None and abs(cy_) >= 10:
            up, lo = cy_ > 0, ry_ <= 5
            rule = ("업황 회복 · 회사 매출 아직(재고 순환 +10%p↑ · 매출 +5%↓)" if up and lo else
                    "업황 회복 · 회사 매출 이미(재고 순환 +10%p↑ · 매출 +5%↑)" if up else
                    "업종 재고 쌓임 · 회사 매출도 약함(재고 순환 −10%p↓ · 매출 +5%↓)" if lo else
                    "업종 재고 쌓임 · 회사 매출 아직 좋음(재고 순환 −10%p↓ · 매출 +5%↑)")
            head = "업종(%s) 최근 석 달 출하 %+.0f%% · 재고 %+.0f%%(재고 순환 %+.0f%%p) · 이 회사 매출(최근 4분기) %+.0f%% — " % (mac["ind_name"], sy_, iy_, cy_, ry_)
            tail = ("업황이 먼저 살아났는데 회사 매출은 아직이다. 회사 매출이 따라올 자리" if up and lo else
                    "업황 회복과 회사 매출이 같이 간다" if up else
                    "업종도 회사도 약하다. 과거엔 이 뒤 매출 · 이익률은 더 약했지만 주가는 오히려 시장보다 나은 편이었다(바닥 근처)" if lo else
                    "업종에 재고가 쌓이는데 회사 매출은 아직 좋다. 매출 · 이익률 둔화가 먼저 보이는 자리")
            calls.append({"tone": "up" if up else ("nu" if lo else "dn"), "stage": "업황", "ev": _qtr_ev(rule), "text": head + tail})
        if py_ is not None and ry_ is not None and abs(py_) >= 10 and not (py_ < 0 and ry_ <= 5):
            rule = ("업종 가격 상승 · 회사 매출 아직(수출물가 +10%↑ · 매출 +5%↓)" if py_ > 0 and ry_ <= 5 else
                    "업종 가격 상승 · 회사 매출 이미(수출물가 +10%↑ · 매출 +5%↑)" if py_ > 0 else
                    "업종 가격 하락 · 회사 매출 아직 좋음(수출물가 −10%↓ · 매출 +5%↑)")
            head = "업종 제품 가격(수출물가 · %s, %s.%s) 전년 대비 %+.0f%% · 이 회사 매출 %+.0f%% — " % (mac["price_name"], pk[:4], pk[4:], py_, ry_)
            tail = ("가격 바람이 불기 시작했는데 회사 매출은 아직이다. 과거엔 주가가 먼저 반응했고, 이익률로 이어진 증거는 약했다" if py_ > 0 and ry_ <= 5 else
                    "가격과 매출이 같이 올랐다. 과거엔 뚜렷한 추가 신호가 아니었다" if py_ > 0 else
                    "가격이 꺾였는데 회사 매출은 아직 좋다. 과거엔 그 뒤 매출 · 이익률이 둔화한 편(기간마다 달랐다)")
            calls.append({"tone": "up" if py_ > 0 and ry_ <= 5 else "nu" if py_ > 0 else "dn", "stage": "업황",
                          "ev": _qtr_ev(rule), "text": head + tail})
    # 수주 공시 — 최근 4분기 합의 전년 대비가 매출보다 빠른가(검증 전), 지난 분기 말 뒤 새로 들어온 계약
    oy = last.get("ord_yoy")
    if oy is not None and ry is not None and oy - ry >= 30:
        calls.append({"tone": "up", "stage": "수주 공시", "text": "공시된 수주(최근 4분기 합) %+.0f%% > 매출 %+.0f%% — 큰 계약이 매출보다 빨리 늘었다(과거 검증 전)" % (oy, ry)})
    elif oy is not None and ry is not None and oy - ry <= -30:
        calls.append({"tone": "dn", "stage": "수주 공시", "text": "공시된 수주(최근 4분기 합) %+.0f%% < 매출 %+.0f%% — 큰 계약이 줄었다(과거 검증 전)" % (oy, ry)})
    q_end = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[int(labs[-1][5])]
    since = labs[-1][:4] + q_end
    fresh = [o for o in orders if o["kind"] == "체결" and o["date"] > since]
    if now is not None:
        amt = sum(o["amount"] or 0 for o in fresh)
        rt_ = last.get("rev_ttm")
        now.update(ord_since=since, ord_since_n=len(fresh), ord_since_amt=amt,
                   ord_since_pct=(amt / rt_ * 100) if rt_ and amt else None,
                   ord_since_top=[{k: x.get(k) for k in ("party", "title", "amount", "date")}
                                  for x in sorted(fresh, key=lambda z: -(z["amount"] or 0))[:3]])
    if fresh:
        amt = sum(o["amount"] or 0 for o in fresh)
        rt_ = last.get("rev_ttm")
        big = max(fresh, key=lambda z: z["amount"] or 0)
        calls.append({"tone": "up" if rt_ and amt / rt_ >= 0.1 else "nu", "stage": "수주 공시",
                      "text": "지난 분기 말(%s.%s) 뒤 새 수주 공시 %d건 · %s%s — 가장 큰 것: %s%s. 다음 분기보고서의 잔고보다 먼저 보이는 숫자"
                      % (since[4:6], since[6:], len(fresh), _won_txt(amt) if amt else "금액 확인 중",
                         (" (최근 4분기 매출의 %.0f%%)" % (amt / rt_ * 100)) if rt_ and amt else "",
                         (big.get("party") or big.get("title") or "")[:30], (" " + _won_txt(big["amount"])) if big.get("amount") else "")})
    if not calls:
        calls.append({"tone": "nu", "stage": "", "text": "앞단(잔고 · 선수금 · 생산 · 설비)과 매출 · 이익 · 주가 사이에 문턱(15~30%p)을 넘는 어긋남이 없다."})
    # 값 판정 — 오늘 가격 기준. 자기 역사(하위 30% 싸다 · 상위 30% 비싸다) × 성장 대비(PEG 1 미만 싸다 · 2 초과 비싸다) × 이익률 꼭대기
    if now and now.get("per"):
        pp_, pg, mp = now.get("per_pct"), now.get("peg"), now.get("opm_pct")
        pos = lambda v: "최고" if v >= 99.5 else "최저" if v <= 0.5 else ("하위 %.0f%%" % v if v < 50 else "상위 %.0f%%" % (100 - v))
        hist = ("최근 10년 자기 역사 PER 중 %s(중앙값 %.0f배)" % (pos(pp_), now["per_med"])
                if pp_ is not None else "자기 역사가 짧아 견줄 수 없다")
        pegt = ("PEG %.1f" % pg) if pg is not None else "이익이 안 늘어 PEG 없음"
        band = None if pp_ is None else ("비싸다" if pp_ >= 70 else "싸다" if pp_ <= 30 else "보통")
        gb = None if pg is None else ("싸다" if pg < 1 else "비싸다" if pg > 2 else "보통")
        if band == "비싸다" and gb in ("비싸다", None):
            tone, msg = "dn", "역사 대비로도 성장 대비로도 비싸다 — 앞단이 꺾이면 내려올 자리"
        elif band == "비싸다":
            tone, msg = "warn", "역사 대비로는 비싸지만 성장 대비로는 %s — 앞단이 이어지는 동안만 정당화된다" % gb
        elif band == "싸다" and gb == "싸다":
            tone, msg = "up", "역사 대비로도 성장 대비로도 싸다"
        elif band == "싸다":
            tone, msg = "warn", "싸 보이지만 이익 성장이 약하다 — 싼 데는 이유가 있을 수 있다"
        elif band == "보통":
            tone, msg = ("up" if gb == "싸다" else "dn" if gb == "비싸다" else "nu"), "역사 중간대 — 성장 대비로는 %s" % (gb or "판단 불가")
        else:
            tone, msg = "nu", "역사 비교가 안 된다"
        cat = _qtr_valcat(pp_, pg)
        ev = _qtr_ev(cat=cat) if cat else None
        if ev and ev.get("ci") and ev["ci"][0] is not None:       # 색은 같은 묶음의 과거 성적으로 — 구간이 0을 넘으면 초록, 밑돌면 빨강
            tone = "up" if ev["ci"][0] > 0 else "dn" if ev["ci"][1] < 0 else "nu"
        calls.append({"tone": tone, "stage": "값", "ev": ev,
                      "text": "지금(%s.%s.%s) PER %.0f배 — %s, %s. %s" % (now["date"][:4], now["date"][4:6], now["date"][6:], now["per"], hist, pegt, msg)})
        if mp is not None and mp >= 90:
            calls.append({"tone": "nu", "stage": "이익률", "ev": _qtr_ev("이익률 자기 역사 상위 10%"),
                          "text": "영업이익률이 지난 10년 %s — 과거엔 이 뒤 매출 증가율이 대개 꺾였지만, 주가는 오히려 시장보다 나은 편이었다. "
                                  "이익 꼭대기라는 표시만으로 팔 근거는 약하다(경기 순환주는 앞단 줄이 꺾이는지 같이 볼 것)"
                                  % ("가운데 가장 높다" if mp >= 99.5 else "상위 %.0f%%" % (100 - mp))})
    have = {k: any(rows[l].get(k) is not None for l in show) for k in ("blog", "liab", "wip", "capex_ttm", "px", "ord_ttm", "roe", "mp_yoy", "cyc")}
    return {"labs": show, "rows": {l: rows[l] for l in show}, "lags": lags, "calls": calls, "have": have, "last": labs[-1], "now": now,
            "splits": pr.get("splits") or [], "macro": mac}


# ---------------------------------------------------------------- 값 판단 요약 — 구루 렌즈를 큰 표본 검증으로 다시 읽는다 (2026-10-02)
# 도구/구루렌즈_검증.py(공시 23,233건 · 946곳 · 2015~2025, 공시일 기준)에서 뚜렷했던 것만 판정에 쓰고, 나머지는 성적만 보인다.
#   맞았다  PSR · PER 자기 역사 하위 30%(+2.0~2.4%p, 가치 함정 10% — 전체 15%) · 상위 30%(−2.5%p, 함정 18%) · PSR 3배↑(−4.3%p, 함정 23%)
#   매출 가속(B) +3%p↑ — 가속도 탭과 같은 B(속도 2분기 평균의 변화) · 같은 띠. 성적은 lens_bt.json(가속도 캐시가 있는 공시만)
#   안 맞았다  ROE 15%↑ · 슈퍼 컴퍼니 · 글리치 · 고성장, 싸다 + 품질(ROE · 현금화) 조합
#   거꾸로   멍거 경고(현금화 · 매출채권 · 재고 · 부채) — 걸린 회사가 오히려 +3~5%p, 함정 비율도 평균 → 피할 신호로 쓰지 않는다
DRUCK_LENS = "드러켄밀러 · 가속(B) +3%p↑"      # 도구/구루렌즈_검증.py RULES 의 같은 이름 — 문턱은 DRK.PHASE_BAND
LENS_RULES = {   # 렌즈 → 성적을 보일 규칙(도구/구루렌즈_검증.py RULES 이름)
    "켄 피셔": ["피셔 · PSR 자기 역사 하위 30%", "피셔 · PSR 자기 역사 상위 30%", "피셔 · PSR 3배↑(절대)", "피셔 · 슈퍼 컴퍼니"],
    "스탠리 드러켄밀러": [DRUCK_LENS, "드러켄밀러 · 매출 +20%↑", "드러켄밀러 · 설비투자 강도 10%↑"],
    "워런 버핏": ["버핏 · ROE 15%↑", "버핏 · ROE 10년 평균 15%↑ · 최저 10%↑", "버핏 · 이익률 흔들림 낮음(0.2↓)"],
    "피터 린치": ["린치 · PEG < 1", "린치 · 고성장(매출 5년 20%↑)"],
    "찰리 멍거": ["멍거 · 경고 2개↑", "멍거 · 3년 안 증자", "멍거 · 3년 중 2년 적자"],
}
_LBT = {"mt": None, "d": None}


def _lens_bt():
    p = os.path.join(CACHE_DIR, "inflect", "lens_bt.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _LBT["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _LBT.update(d=json.load(fh), mt=mt)
        except Exception:
            return None
    return _LBT["d"]


def _lens_ev(name):
    d = _lens_bt() or {}
    t = (d.get("rules") or {}).get(name) or (d.get("combo") or {}).get(name)
    if not t or t.get("diff") is None:
        return None
    return {"rule": name, "n": t.get("n_on"), "diff": t["diff"], "ci": t.get("ci"), "early": t.get("early"), "late": t.get("late"),
            "trap": t.get("trap"), "word": _ev_word(t["diff"], t.get("ci"), t.get("early"), t.get("late"))}


def _checked_call(tone, text, ev):
    """과거 성적(ev)이 통과(EV_PASS)일 때만 방향 색(tone)을 단다. 아니면 'nu' + ' (검증 안 됨)' — 통과 못 한 규칙이 초록으로 보이지 않게."""
    if (ev or {}).get("word") == EV_PASS:
        return {"tone": tone, "text": text, "ev": ev}
    return {"tone": "nu", "text": text + " (검증 안 됨)", "ev": ev}


def lens_value(code):
    """지금 이 회사의 값 위치 · 가속 · 멍거 경고와, 그 판정의 과거 성적. 렌즈 카드마다 큰 표본 성적."""
    c = company_by_code(code)
    corp = corp_code_of(code) if c and FIN is not None else None
    out = {"code": code, "lens_ev": {g: [e for e in (_lens_ev(n) for n in names) if e] for g, names in LENS_RULES.items()},
           "base_trap": (_lens_bt() or {}).get("base_trap"), "guru_hit": _guru_hit_for(code)}
    if not corp:
        return out
    try:
        mi = matrix_cached(c, corp, "IS", "q", IS_YEARS)
        mb = matrix_cached(c, corp, "BS", "q", QTR_YEARS)
        mc = matrix_cached(c, corp, "CF", "q", QTR_YEARS)
        pr = _pipe_rows(c, mi, mb, mc, blog_pts=[])
    except Exception as e:
        out["error"] = "재무 조회 실패: %s" % e
        return out
    if not pr or not pr.get("px"):
        return out
    labs, R, px = pr["labs"], pr["rows"], pr["px"]
    last = R[labs[-1]]
    p, sh, rt = px["p"][-1], last.get("shares"), last.get("rev_ttm")
    psr = p * sh / rt if p and sh and rt and rt > 0 else None
    qn_ = lambda k: int(k[:4]) * 4 + int(k[5])
    ph = []
    for l in labs[-41:-1]:
        r = R[l]
        if r.get("px") and r.get("shares") and r.get("rev_ttm") and r["rev_ttm"] > 0:
            ph.append(r["px"] * r["shares"] / r["rev_ttm"])
    pct = lambda v, h: (sum(1 for x in h + [v] if x <= v) / (len(h) + 1) * 100) if v and len(h) >= 8 else None
    et = last.get("eps_ttm")
    per = p / et if p and et and et > 0 else None
    eh = [R[l]["per"] for l in labs[-41:-1] if (R[l].get("per") or 0) > 0]
    g = last.get("ni_yoy")
    peg = per / min(max(g, 1.0), 100.0) if per and g is not None and g > 0 else None
    # 가속은 가속도 탭과 같은 B — 캐시(지금 버전)의 가속(B)가 있는 마지막 분기. 캐시가 없으면 없음(여기서 쌓지 않는다)
    dk = _druck_read(code)
    lastp = next((q for q in reversed((dk or {}).get("points") or []) if q.get("가속B") is not None), None)
    acc = lastp.get("가속B") if lastp else None
    psr_pct, per_pct = pct(psr, ph), pct(per, eh)
    out.update(date=str(px["d"][-1]), psr=psr, psr_pct=psr_pct, per=per, per_pct=per_pct, peg=peg, acc=acc,
               rev_yoy=last.get("rev_yoy"), quarter=labs[-1], mcap=(p * sh) if p and sh else None, rev_ttm=rt)
    calls = []
    cheap = (psr_pct is not None and psr_pct <= 30) or (per_pct is not None and per_pct <= 30)
    dear = (psr_pct is not None and psr_pct >= 70)
    pos = lambda v: "최고" if v >= 99.5 else "최저" if v <= 0.5 else ("하위 %.0f%%" % v if v < 50 else "상위 %.0f%%" % (100 - v))
    where = "PSR %s(자기 역사 %s)" % ("%.2f배" % psr if psr else "—", pos(psr_pct) if psr_pct is not None else "견줄 기록 부족") + \
            (" · PER %.0f배(%s)" % (per, pos(per_pct)) if per and per_pct is not None else "")
    if dear:
        calls.append({"tone": "dn", "text": "비싼 쪽 — " + where, "ev": _lens_ev("피셔 · PSR 자기 역사 상위 30%")})
    elif cheap:
        calls.append({"tone": "up", "text": "싼 쪽 — " + where, "ev": _lens_ev("싸다(자기 역사 PER 또는 PSR 하위 30%)")})
    else:
        calls.append({"tone": "nu", "text": "중간 — " + where + ". 자기 역사 가운데라 값만으로는 기울지 않는다", "ev": None})
    if psr is not None and psr >= 3:
        calls.append({"tone": "dn", "text": "PSR %.1f배 — 매출의 3배를 넘는 값" % psr, "ev": _lens_ev("피셔 · PSR 3배↑(절대)")})
    if acc is not None and acc >= DRK.PHASE_BAND:
        calls.append(_checked_call("up", "매출 가속(B) %+.1f%%p(%s 속도 %+.0f%%, %s)" % (
                         acc, lastp.get("label", ""), lastp.get("속도") or 0, lastp.get("국면") or "국면 판단 전"), _lens_ev(DRUCK_LENS)))
    if peg is not None and peg < 1:
        calls.append({"tone": "nu", "text": "PEG %.1f — 성장 대비 싸다(2020년 뒤에만 통했다)" % peg, "ev": _lens_ev("린치 · PEG < 1")})
    out["calls"] = calls
    return out


# 구루 적중률 — 카드 배지를 분기 보고서마다 다시 매겨 그대로 샀다면 누가 맞혔나(도구/구루적중률_백테스트.py → .cache/inflect/guru_hit.json)
_GHT = {"mt": None, "d": None}


def _guru_hit_for(code):
    p = os.path.join(CACHE_DIR, "inflect", "guru_hit.json")
    try:
        mt = os.path.getmtime(p)
        if _GHT["mt"] != mt:
            with open(p, "r", encoding="utf-8") as fh:
                _GHT.update(d=json.load(fh), mt=mt)
    except Exception:
        return None
    d = _GHT["d"] or {}
    return {k: d.get(k) for k in ("n", "firms", "from", "to", "gurus", "kinds")} | {"mine": (d.get("by_code") or {}).get(code)}


def _inv_prices(code, ohlc=False):
    """일별 종가(액면분할·병합 보정)를 [날짜들], [종가들] 두 줄로. 없으면 None.
    ohlc=True 면 일봉 차트용 시가 · 고가 · 저가 · 거래량도 같은 비율로 보정해 붙인다(변화 브리핑 차트만 —
    전 종목을 도는 화면은 네이버를 한 번 더 부르지 않게 끈다)."""
    if FIN is None:
        return None
    try:
        pr = FIN.fetch_prices(code)
    except Exception:
        return None
    if not pr:
        return None
    ds = sorted(pr)
    adj = SYN._adjusted(pr, ds) if SYN is not None else [pr[d] for d in ds]
    # p = 보정 종가(선 그리기·수익률), r = 그날 실제 종가(화면에 적는 '그날 주가')
    out = {"d": [int(d) for d in ds], "p": [round(v, 1) for v in adj], "r": [pr[d] for d in ds]}
    if ohlc:
        try:
            ov = FIN.fetch_ohlcv(code) or {}
        except Exception:
            ov = {}
        if ov:
            o, h, lo, v = [], [], [], []
            for d, a in zip(ds, adj):
                row, raw = ov.get(d), pr[d]
                k = a / raw if raw else 1.0
                if row and row[3]:
                    # 종가가 시세 캐시와 다르면(하루 차이로 받은 캐시) 그날 종가에 맞춰 비율만 쓴다
                    s = a / row[3]
                    o.append(round(row[0] * s, 1)); h.append(round(max(row[1] * s, a), 1))
                    lo.append(round(min(row[2] * s, a), 1)); v.append(int(row[4] / k) if k else int(row[4]))
                else:
                    o.append(round(a, 1)); h.append(round(a, 1)); lo.append(round(a, 1)); v.append(0)
            out.update({"o": o, "h": h, "l": lo, "v": _inv_vol_splits(v)})
    return out


def _inv_vol_splits(v):
    """네이버 일봉은 가격만 분할 보정되고 거래량은 그때 주식 수 그대로다(삼성전자 2018 50:1 앞은 50분의 1).
    분할 · 병합은 거래 정지(거래량 0)가 2일 넘게 이어진 뒤 거래량 수준이 몇 배로 바뀌는 것으로 잡아
    그 앞 거래량에 같은 비율을 곱한다. 거래량만으로 비율이 분명한 큰 분할(10 · 20 · 25 · 50 · 100배, 1.25배 안)만 —
    2~5배는 거래량 자체가 그만큼 오르내려 비율을 못 정한다(LS일렉트릭 2026 5:1 이 2배로 잡혔다) → 원자료 그대로."""
    import math
    nice = [10, 20, 25, 50, 100]
    nice = nice + [1 / x for x in nice]
    v = list(v)
    n, i = len(v), 0
    while i < n:
        if v[i]:
            i += 1
            continue
        j = i
        while j < n and not v[j]:
            j += 1
        if j - i >= 2 and i >= 20 and j + 20 <= n:
            bef = sorted(x for x in v[max(0, i - 60):i] if x)
            aft = sorted(x for x in v[j:j + 60] if x)
            if len(bef) >= 15 and len(aft) >= 15:
                r = aft[len(aft) // 2] / bef[len(bef) // 2]
                f = min(nice, key=lambda x: abs(math.log(r / x)))
                if abs(math.log(r / f)) < math.log(1.25):   # NAVER 2018 5:1 은 7.4배 — 10배로 잘못 잡지 않게
                    v[:i] = [int(x * f) for x in v[:i]]
        i = j
    return v


def _inv_regimes(code):
    """가속도 캐시(지금 버전)로 분기별 7국면 — [{label, g(TTM 성장률), s(속도), a(가속(B)), reg}]. 캐시가 없으면 빈 목록."""
    pts = (_druck_read(code) or {}).get("points") or []
    by = {p["n"]: p for p in pts if p.get("n") is not None}
    return [{"label": p.get("label"), "g": _ttm_growth(by, p), "s": p.get("속도"), "a": p.get("가속B"), "reg": p.get("국면")}
            for p in pts]


# ---------------------------------------------------------------- 전문검색: 무엇을 물어야 할지 모를 때
# 초일류 투자자가 정기보고서에 던지는 질문 24개를 회사마다 미리 돌려 둔다(질문 지도).
# 찾은 문장은 '족보'로 묶는다 — 같은 말이 언제 태어나, 어떻게 고쳐지고, 언제 사라졌나.
# 원탁 백테스트에서 공시 뒤에도 값에 덜 든 채 남은 건 '새 문장'뿐이었다. 질문 지도는 그 새 문장을 질문별로 가른다.
ASK_V = 5            # 5: 주가에 닿을 줄(호재 · 악재 · 잠재, 2026-10-03)
ASK_MAT_MIN = 2.6    # 이만큼은 돼야 '주가에 닿을 줄' — 방향 낱말 하나만으론 모자라고 금액 · 실제로 일어난 일이 붙어야 한다
ASK_SIG = 2.8        # 이만큼 무거워야 '새 답'. 금액·범주 낱말·꼬리 위험 없이 문장만 새로 쓴 건 2.0
_AB, _AM, _AF, _AO = "사업의 내용", "이사의 경영진단 및 분석의견", "재무에 관한 사항", "회사의 개요"
_AP, _ASH, _AE = "그 밖에 투자자 보호를 위하여 필요한 사항", "주주에 관한 사항", "임원 및 직원 등에 관한 사항"
_ABD, _AAF, _ARP = "이사회 등 회사의 기관", "계열회사 등에 관한 사항", "대주주 등과의 거래내용"
_AAU = ["감사인의 감사의견 등", "독립된 감사인의 감사보고서"]
_AIC = ["내부회계관리제도 감사 또는 검토의견", "연결 내부회계관리제도 감사 또는 검토의견", "내부회계관리제도 검토의견"]
ASK_THEMES = [("demand", "수요", "더 팔릴까", "DEMAND"), ("margin", "마진", "더 남을까", "MARGIN"),
              ("capital", "자본", "내 몫이 커질까", "CAPITAL"), ("risk", "위험", "치명상은 없나", "TAIL RISK"),
              ("people", "사람", "누가 운전하나", "STEWARDSHIP")]
# clock: lead = 아직 숫자에 없는 이야기 · slow = 천천히 값에 든다 · risk = 꼬리 위험 · fast = 잠정실적으로 먼저 알려진다
ASK_Q = [
    dict(id="backlog", th="demand", who="드러켄밀러", clock="lead", q="수주잔고가 쌓이고 있나?",
         why="매출보다 6–24개월 앞서 움직이는 숫자. 잔고가 매출보다 빨리 늘면 다음 해 실적이 예약된 것이다.",
         good="잔고가 매출보다 빨리 늘고, 새 고객·새 지역 이름이 붙는다", bad="잔고 공시를 멈추거나 '영업기밀'로 가린다",
         rx=r"수\s*주\s*잔\s*[고액]|계약\s*잔액|수\s*주\s*총\s*액", secs=[_AB, _AM]),
    dict(id="util", th="demand", who="드러켄밀러", clock="lead", q="공장이 꽉 찼나?",
         why="가동률이 90%를 넘으면 다음은 증설이나 값 올리기 — 둘 다 이익이 커지는 길이다.",
         good="가동률이 오르고 계산 근거에 새 공장이 더해진다", bad="가동률이 떨어지는데 증설은 계속된다",
         rx=r"가동\s*[률율]", secs=[_AB]),
    dict(id="capex", th="demand", who="드러켄밀러", clock="lead", q="생산능력을 늘리나?",
         why="회사가 제 돈으로 거는 베팅. 수요를 가장 잘 아는 사람의 판단이다.",
         good="증설 금액·완공 시점이 구체적이고 수주잔고가 뒷받침한다", bad="잔고·가동률 근거 없이 빚으로 늘린다",
         rx=r"증\s*설|생산\s*능력\s*(?:확대|증대|확충)|신규\s*(?:공장|라인|생산\s*라인)|신\s*공장|(?:시설|설비)\s*투자\s*계획",
         secs=[_AB, _AM]),
    dict(id="newprod", th="demand", who="린치", clock="lead", q="새 매출원이 생기나?",
         why="새 제품·새 사업은 보고서에 먼저 나오고 실적에는 몇 분기 뒤에 나온다.",
         good="양산·출시·고객 인증처럼 돈이 되는 단계의 말", bad="'개발 중'만 해마다 되풀이된다",
         rx=r"양\s*산|상용화|(?<![배수진])출\s*시(?![설장])|개발\s*(?:완료|에\s*성공)|신\s*제품|신규\s*사업", secs=[_AB, _AM]),
    dict(id="purpose", th="demand", who="린치", clock="lead", q="정관에 새 사업을 넣었나?", raw=True,
         why="사업목적 추가는 3–5년 뒤 매출의 예고편이자, 테마에 올라타려는 흔적이기도 하다.",
         good="투자·인력·수주가 뒤따른다", bad="유행어만 넣고 아무것도 뒤따르지 않는다",
         rx=r"사업\s*목적\s*(?:을\s*|의\s*)?(?:추가|변경|신설)|목적\s*사업\s*(?:을\s*|의\s*)?(?:추가|변경)", secs=[_AO, _ABD]),
    dict(id="share", th="demand", who="린치", clock="slow", q="점유율이 오르나?",
         why="점유율은 경쟁의 성적표. 숫자를 공개하다 숨기기 시작하는 것도 신호다.",
         good="점유율 숫자가 오르고 경쟁사 이름이 줄어든다", bad="숫자 대신 '선도적 위치' 같은 말만 남는다",
         rx=r"점유율|(?<![A-Za-z])M/S(?![A-Za-z])", secs=[_AB]),
    dict(id="pricing", th="margin", who="버핏", clock="slow", q="값을 올릴 수 있나?",
         why="버핏이 꼽은 단 하나의 질문 — 값을 올려도 고객이 떠나지 않는가.",
         good="판매가격이 오르는데 물량도 유지된다", bad="'가격 경쟁 심화', '판가 하락'이 들어온다",
         rx=r"판매\s*가격|판\s*가(?![격치])|가격\s*(?:인상|인하|경쟁)|단가\s*(?:인상|상승|인하|하락)", secs=[_AB, _AM]),
    dict(id="input", th="margin", who="린치", clock="fast", q="원가가 짓누르나?",
         why="판가와 원가의 틈이 이익률이다. 원재료 가격표는 「사업의 내용」에 해마다 실린다.",
         good="원가 부담을 판가로 넘겼다는 말", bad="원재료 상승을 '흡수'했다는 말이 되풀이된다",
         rx=r"원재료\s*가격|원자재|원가\s*(?:상승|부담|절감|율)", secs=[_AB, _AM]),
    dict(id="customer", th="margin", who="버핏", clock="slow", q="고객 몇 곳에 기대나?",
         why="한 고객에 기대면 협상력이 약하다. 주요 매출처에 새 이름이 붙으면 저변이 넓어진 것이다.",
         good="주요 매출처에 새 이름이 붙고 한 곳 비중이 준다", bad="한 고객 비중이 커지거나 고객 이름을 감춘다",
         rx=r"주요\s*(?:매출처|고객|거래처)|매출\s*비중|단일\s*고객|상위\s*\d+\s*(?:개|대)?\s*(?:고객|거래처|매출처)", secs=[_AB, _AM]),
    dict(id="fx", th="margin", who="드러켄밀러", clock="fast", q="환율에 얼마나 흔들리나?",
         why="환율 민감도 문장은 이익이 회사 밖 변수에 얼마나 묶였는지를 숫자로 알려 준다.",
         good="헤지 정책이 구체적이고 손익 민감도가 작다", bad="파생상품 손실이 경영진단에 등장한다",
         rx=r"환율\s*(?:이|가)?\s*\d+\s*%|환율\s*변동\s*(?:위험|영향|시)|환\s*위험|환\s*헤지|환율\s*(?:상승|하락)", secs=[_AB, _AM]),
    dict(id="dilution", th="capital", who="멍거", clock="risk", q="주식 수가 늘어날 일이 있나?", raw=True,
         why="희석은 주당 가치를 깎는다. 전환가액을 거듭 낮추면(리픽싱) 주가가 눌린다.",
         good="메자닌을 상환하거나 전환권이 소멸한다", bad="전환사채·유상증자·제3자 배정이 새로 생긴다",
         rx=r"전환\s*사채|신주\s*인수권|교환\s*사채|유상\s*증자|전환\s*가액|제\s*3\s*자\s*배정|(?<![A-Za-z])(?:CB|BW|EB)(?![A-Za-z])",
         secs=[_AO, _AF, _AP, _ASH]),
    dict(id="buyback", th="capital", who="버핏", clock="slow", q="자사주를 사고 태우나?",
         why="소각은 남은 주주의 몫을 키운다. 사기만 하고 태우지 않으면 경영권 방어용일 수 있다.",
         good="소각 규모·일정이 구체적이다", bad="취득만 하고 '처분·소각 계획 없음'",
         rx=r"자기\s*주식|자\s*사\s*주|소\s*각", secs=[_ASH, _AO, _AF]),
    dict(id="dividend", th="capital", who="버핏", clock="slow", q="배당 정책이 바뀌나?",
         why="배당 정책 문장이 바뀌면 경영진이 보는 현금 전망이 바뀐 것이다.",
         good="배당성향 하한·분기배당처럼 약속이 구체화된다", bad="'경영 상황에 따라' 같은 빠져나갈 문구가 는다",
         rx=r"배당\s*성향|주당\s*배당|배당\s*정책|주주\s*환원|현금\s*배당", secs=[_AF, _ASH, _AO]),
    dict(id="pledge", th="capital", who="멍거", clock="risk", q="대주주 주식이 담보로 잡혔나?",
         why="오너 지분 담보는 주가가 빠질 때 반대매매 매물이 된다.",
         good="담보 계약이 풀린다", bad="담보·질권 설정이 새로 생기거나 늘어난다",
         rx=r"주식\s*담보|질\s*권|반대\s*매매|담보\s*(?:제공|계약)", secs=[_ASH, _AP]),
    dict(id="guarantee", th="capital", who="멍거", clock="risk", q="장부 밖 빚이 있나?",
         why="보증·자금보충·책임준공 약정은 재무제표 본문에 잘 안 보이는 빚이다.",
         good="보증 한도가 줄거나 끝난다", bad="PF·책임준공·자금보충 약정이 새로 생긴다",
         rx=r"지급\s*보증|채무\s*보증|우발\s*(?:부채|채무)|자금\s*보충|책임\s*준공", secs=[_AP, _AF, _ARP]),
    dict(id="going", th="risk", who="멍거", clock="risk", q="회사가 계속 갈 수 있나?", raw=True,
         why="감사인이 존속 능력에 의문을 적으면 그것만으로 치명적이다. '어디서 죽을지 알면 거기 안 간다.'",
         good="해당 문구가 없다", bad="'계속기업 가정에 중요한 불확실성'",
         rx=r"존속\s*(?:능력|가능성|여부)에\s*(?:대한\s*)?(?:유의적|중요한|중대한)\s*(?:의문|불확실성)|계속\s*기업\s*(?:가정|전제)에\s*(?:대한\s*)?(?:유의적|중요한|중대한)\s*(?:의문|불확실성)",
         secs=_AAU + [_AF, _AP]),
    dict(id="kam", th="risk", who="멍거", clock="risk", q="감사인은 어디를 콕 집었나?", raw=True,
         why="핵심감사사항은 감사인이 가장 오래 들여다본 곳. 항목이 바뀌면 위험의 자리가 바뀐 것이다.",
         good="같은 사항이 해마다 무난히 유지된다", bad="수익 인식·손상·재고처럼 이익을 흔드는 항목이 새로 지목된다",
         rx=r"핵심\s*감사\s*사항|강조\s*사항|한정\s*의견|의견\s*거절|부적정\s*의견", secs=_AAU),
    dict(id="lawsuit", th="risk", who="멍거", clock="risk", q="소송·제재가 걸려 있나?",
         why="소송은 끝나야 사라진다. 등장과 소멸을 이으면 회사가 겪은 분쟁의 지도가 나온다.",
         good="판결·화해로 끝났다는 말", bad="담합·손해배상·과징금이 새로 등장한다",
         rx=r"소\s*송|과징금|제\s*재(?!\s*현황)|행정\s*처분|기\s*소|손해\s*배상|공정\s*거래\s*위원회|영업\s*정지", secs=[_AP, _AF]),
    dict(id="related", th="risk", who="버핏", clock="risk", q="대주주와 거래가 많나?",
         why="대주주 쪽으로 이익이 새는 길. 거래가 커지면 소액주주 몫이 줄 수 있다.",
         good="거래가 줄거나 조건이 투명하게 공개된다", bad="대주주 회사와 자산 매매·자금 대여가 새로 생긴다",
         rx=r"특수\s*관계\s*(?:자|인)|내부\s*거래|일감\s*몰아", secs=[_ARP, _AB, _AP]),
    dict(id="icfr", th="risk", who="멍거", clock="risk", q="숫자를 믿을 수 있나?", raw=True,
         why="내부통제에 구멍이 나면 다른 모든 숫자가 의심받는다. 횡령·배임은 즉시 치명상이다.",
         good="적정 의견이 이어진다", bad="중요한 취약점·횡령·배임",
         rx=r"중요한\s*취약점|횡\s*령|배\s*임(?!\s*금)|비\s*적정", secs=_AAU + _AIC + [_AP]),
    dict(id="rnd", th="people", who="피셔", clock="lead", q="미래에 얼마를 거나?",
         why="성장이 꺾이기 전에 R&D가 먼저 꺾이는 회사가 많다. 피셔는 연구비 대비 시가총액(PRR)으로 값을 잰다.",
         good="연구 조직·과제가 늘고 상용화 이력이 쌓인다", bad="연구 실적 표가 해마다 같다",
         rx=r"연구\s*개발\s*(?:비|비용|인력|조직|실적)|연구\s*소|(?<![A-Za-z])R&D", secs=[_AB]),
    dict(id="incentive", th="people", who="멍거", clock="slow", q="경영진 보상이 주가와 묶였나?", raw=True,
         why="'보상 구조를 보여주면 결과를 알려주겠다'(멍거). 새로 생긴 주식 보상은 동기가 바뀐 신호다.",
         good="성과 조건이 붙은 주식 보상이 생긴다", bad="행사가 조정·조건 없는 지급",
         rx=r"주식\s*매수\s*선택권|스톡\s*옵션|양도\s*제한\s*조건부|(?<![A-Za-z])(?:RSU|PSU)(?![A-Za-z])|성과\s*조건부",
         secs=[_AE, _ABD, _AF, _AO]),
    dict(id="control", th="people", who="버핏", clock="risk", q="주인·운전자가 바뀌나?",
         why="주인이 바뀌면 전략도 바뀐다. 승계·매각·분쟁의 전조는 여기 먼저 찍힌다.",
         good="경영 체제가 오래 안정적이다", bad="최대주주 변경·경영권 분쟁",
         rx=r"최대\s*주주\s*(?:의\s*)?변경|경영권|대표\s*이사\s*(?:의\s*)?(?:변경|선임|사임|교체)|경영\s*승계|후계", secs=[_ASH, _AO, _AP]),
    dict(id="mna", th="people", who="린치", clock="slow", q="사고파는 회사가 있나?",
         why="린치의 경고 — 본업과 무관한 다각화는 이익을 흩는다(diworsification). 본업을 키우는 인수는 도약이다.",
         good="본업을 강하게 하는 인수, 비핵심 매각", bad="본업과 무관한 인수가 늘어난다",
         rx=r"(?<!신주)(?<!신 주)인\s*수(?!\s*권|인)|합\s*병|물적\s*분할|인적\s*분할|영업\s*양수|사업\s*양수|지분\s*(?:취득|인수|처분|매각)|종속\s*(?:회사|기업)\s*(?:로\s*)?(?:편입|제외|신규)",
         secs=[_AO, _AP, _AAF]),
]
for _q in ASK_Q:
    _q["_rx"] = re.compile(_q["rx"])
ASK_META = [{k: q[k] for k in ("id", "th", "who", "clock", "q", "why", "good", "bad")}
            | {"secs": [SEC_SHORT.get(s, s) for s in q["secs"]]} for q in ASK_Q]
# 정관·약관 조문체 — '~할 수 있다', '~준용한다'. 보고서 본문은 '~습니다/~함'으로 쓴다
ASK_STATUTE = re.compile(r"(?:준용한다|할\s*수\s*있다|아니한다|정한다|따른다|하여야\s*한다|로\s*한다|으로\s*한다)$|^이\s*회사는")
ASK_BOILER = re.compile(r"참[고조]하시길|바랍니다|감사\s*절차를\s*수행|핵심\s*감사\s*사항으로\s*결정|핵심\s*감사\s*사항에\s*대응|"
                        r"감사\s*의견을\s*(?:표명|형성)|기재\s*(?:하였|했|함|됨)")
ASK_ACCT = re.compile(r"공정\s*가치|당기\s*손익|기타\s*포괄|현재\s*가치|할인율|측정\s*방법|인식\s*기준|이연\s*법인세|손상\s*차손|회계\s*정책|기업\s*회계\s*기준서")
ASK_PERIOD = re.compile(r"(?:당|전|전전)?\s*(?:분기|반기|사업\s*연도|회계\s*연도|연도)(?:말|중|누적|기간)?|(?:당|전|전전)\s*기(?:말|중)?|상반기|하반기|제\s*\d+\s*기")
ASK_NUM = re.compile(r"(?<![\d.,])[-△▲]?\d[\d,]*(?:\.\d+)?\s*(?:%|조\s*원|억\s*원|백만\s*원|천\s*원|억|조|배|명|MW|GW|MWh|GWh|kV|톤|척|원)?")
ASK_SKIP_TOK = re.compile(r"^(?:당사|회사|연결|연결실체|연결회사|종속|분기|반기|사업|보고서|기준|현재|해당|내용|관련|주요|이상|이하|합계|금액|단위|"
                          r"한편|또한|이에|따라서|특히|다만|이와|같이|그러나|하지만|아울러|더불어)$")
ASK_JUNK_TOK = re.compile(r"^[가-힣][에의을를은는이가과와도로]$|^[가-힣]{1,2}(?:하|되|된|한)$")
# 동사·형용사 활용형(수주했고, 다변화되고, 신설하거나, 힘입어, 수준인) — 명사만 '처음 나온 말'로 친다
ASK_GLUE = re.compile(r"(?:하는|되는|하여|하고|으로|에서|하며)")    # 띄어쓰기가 빠져 붙은 말(실현하는융복합사업)
ASK_VERBISH = re.compile(r"(?:했고|하고|되고|였고|이고|하며|되며|거나|하여|되어|해서|입어|앞두고|인|은|는|을|를|던|시기|주시기|하기|되기|적인|적으로|"
                         r"하는|되는|하게|되게|하였|되었|했|됐|해|돼|운데|이며|면서|으나|었으나|았으나|해온|해 온|며|으로|로서|에서|부터|까지|"
                         r"시키|시키고|시키며|당분간|선제적|르고|하지|되지|않고|있고|없고|다고|라고|었다|였다)$")


def _ask_flat(s):
    return re.sub(r"\s+", "", s)


def _ask_glued(t, flat):
    """띄어쓰기가 빠져 두 낱말이 붙은 것(소송연결실체 = 소송 + 연결실체) — 두 쪽 다 이미 있던 말이면 새 말이 아니다."""
    if len(t) < 4:
        return False
    return any(t[:k] in flat and t[k:] in flat for k in range(2, len(t) - 1))


def _ask_clean(s):
    """문장 앞에 붙어 온 표 꼬리(구축물 포함※ …)와 번호를 뗀다."""
    s = re.sub(r"^[^.※]{0,24}※\s*", "", s.strip())
    return LEAD_RE.sub("", s).strip()


def _ask_skel(s):
    return SKEL_RE.sub("", ASK_PERIOD.sub("§", s))


def _ask_grams(sk):
    return {sk[i:i + 3] for i in range(len(sk) - 2)}


def _ask_sent_ok(sent, year, raw=False):
    if len(sent) < 20 or len(HANGUL_RE.findall(sent)) < 10 or sent.count("\t") >= 2:
        return False
    if not SENT_END.search(sent) or FRAG_RE.match(sent) or ASK_STATUTE.search(sent) or ASK_BOILER.search(sent):
        return False
    if (ASK_ACCT if raw else BOILER).search(sent):
        return False
    yrs = [int(y) for y in INV_YEAR.findall(sent)]
    # 연혁·옛 사건을 되풀이해 적은 문장은 새 말이 아니다
    return not (yrs and max(yrs) < year - 1)


def _ask_nums(sent):
    out = []
    for m in ASK_NUM.finditer(sent):
        v = m.group(0).strip()
        nx = sent[m.end():m.end() + 1]
        if nx and nx in "년월일호차조항기건회분시.":      # 날짜·조항·차수·번호
            continue
        digits = re.sub(r"[^\d]", "", v)
        if not digits or (re.fullmatch(r"(?:19|20)\d\d", digits) and v == digits):
            continue
        if len(digits) == 1 and v == digits:        # (1) 가. 같은 번호
            continue
        out.append(v)
        if len(out) >= 3:
            break
    return out


class _Lineage:
    """문장 족보. 숫자·기간 낱말·띄어쓰기를 지운 뼈대가 같거나, 글자 세 개짜리 조각이 절반 넘게 겹치면
    같은 말로 본다(표현을 고친 것). 같은 말은 한 족보에 쌓이고, 처음 나온 보고서가 '태어난 때'다."""

    def __init__(self):
        self.fams = []
        self.by_skel = {}
        self.grams = []
        self.gfam = []
        self.inv = defaultdict(list)

    def _match(self, g):
        hit = Counter()
        for t in g:
            lst = self.inv.get(t)
            if lst and len(lst) <= 400:          # 흔한 조각(당사는…)은 후보를 고르는 데 쓰지 않는다
                hit.update(lst)
        best, fid = 0.0, None
        for i, _ in hit.most_common(6):
            o = self.grams[i]
            k = len(g & o)
            j = k / (len(g) + len(o) - k)
            if (j >= 0.5 or k / len(g) >= 0.75) and j > best:
                best, fid = j, self.gfam[i]
        return fid

    def add(self, ri, sent, sec, fn):
        sk = _ask_skel(sent)
        fid = self.by_skel.get(sk)
        if fid is None:
            g = _ask_grams(sk)
            fid = self._match(g) if g else None
            if fid is None:
                fid = len(self.fams)
                self.fams.append({"born": ri, "occ": {}, "vers": []})
            self.by_skel[sk] = fid
            if g:
                gi = len(self.grams)
                self.grams.append(g)
                self.gfam.append(fid)
                for t in g:
                    self.inv[t].append(gi)
        f = self.fams[fid]
        if ri not in f["occ"]:                 # 한 보고서에 비슷한 문장이 둘이면 앞의 것만
            f["occ"][ri] = (sent, sec, fn)
            if not f["vers"] or f["vers"][-1][2] != sk:
                f["vers"].append((ri, sent, sk))
        return fid

    def edits(self, f):
        """고쳐 쓴 판마다 새로 들어온 낱말·빠진 낱말. [(ri, sent, add, rm)]"""
        out, seen = [], set()
        prev, prev_flat, flat_all = None, "", ""
        for ri, sent, sk in f["vers"]:
            toks = [t for t in (INF.tokens(sent) if INF else re.findall(r"[가-힣]{2,}", sent))
                    if not ASK_SKIP_TOK.match(t) and not ASK_JUNK_TOK.match(t)]
            ts = set(toks)
            flat = _ask_flat(sent)
            if prev is not None:
                # 띄어쓰기만 바꾼 것(스위스연구소 → 스위스 연구소)·같은 뜻 바꿔 쓰기(자사주 → 자기주식)는 새 말이 아니다
                add = [t for t in dict.fromkeys(toks) if t not in seen and t not in flat_all
                       and _ask_flat(ASK_SYN_MAP.get(t, t)) not in flat_all and not GIST_TERM_SKIP.search(t)
                       and not _ask_glued(t, flat_all)]
                rm = [t for t in dict.fromkeys(prev) if t not in ts and t not in flat
                      and _ask_flat(ASK_SYN_MAP.get(t, t)) not in flat and not GIST_TERM_SKIP.search(t)
                      and not _ask_glued(t, flat)]
                if add:
                    out.append((ri, sent, add[:5], rm[:4]))
            seen |= ts
            prev, prev_flat = toks, flat
            flat_all += "\n" + flat
        return out


def _ask_lines(text, rx):
    """정규식이 걸린 줄들과 걸린 횟수."""
    lines, n, last = [], 0, -1
    for m in rx.finditer(text):
        n += 1
        a = text.rfind("\n", 0, m.start()) + 1
        if a == last:
            continue
        b = text.find("\n", m.end())
        lines.append(text[a:b if b >= 0 else len(text)])
        last = a
    return n, lines


def _ask_sents(line, rx):
    for s in SENT_SPLIT.split(line):
        s = (s or "").strip()
        if s and rx.search(s):
            yield s


_CORPUS = {}
_CORPUS_ORDER = []
_CORPUS_LOCK = threading.Lock()


def corpus_text(c, r, fn):
    """최근 두 회사의 본문은 메모리에 둔다 — 질문 지도를 만든 뒤 전문검색이 곧바로 돈다."""
    code = c["code"]
    with _CORPUS_LOCK:
        d = _CORPUS.get(code)
        if d is None:
            d = _CORPUS[code] = {}
            _CORPUS_ORDER.append(code)
            while len(_CORPUS_ORDER) > 2:
                _CORPUS.pop(_CORPUS_ORDER.pop(0), None)
        t = d.get((r["rcept"], fn))
    if t is None:
        t = read_section(c, r, fn)
        with _CORPUS_LOCK:
            if code in _CORPUS:
                _CORPUS[code][(r["rcept"], fn)] = t
    return t


def _ask_score(sent, q, kind, n_add=0):
    """새 말 한 줄의 무게 — 금액·올해 날짜·범주 낱말이 있으면 무겁다. 꼬리 위험 질문은 더 무겁다."""
    v = {"born": 2.0, "edit": 1.0 + 0.3 * min(3, n_add), "gone": 1.2}[kind]
    if AMOUNT_RE.search(sent):
        v += 1.5
    if DATE_RE.search(sent):
        v += 0.5
    v += 0.8 * min(2, len(classify(sent)))
    if q["clock"] == "risk":
        v += 1.0 if kind != "gone" else 0.3
    if len(sent) > 260:
        v -= 1.0
    elif len(sent) < 35:
        v -= 0.8
    return round(v, 2)


def _ask_rep(reps, ri):
    r = reps[ri]
    return {"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"]}


# ── 주가에 닿을 줄(2026-10-03) — '무게'(금액 · 날짜 · 범주가 있나)는 구체성이지 중요도가 아니다.
# 주석 · 면책(차이가 있을 수 있음 · 단순 합산 금액)과 조직 설명이 위로 올라왔다(효성중공업 26.2Q).
# 그래서 새 말마다 방향(호재 · 악재 · 잠재)과 크기(금액 ÷ 매출 · 자본), 실제로 일어난 일인지를 다시 매긴다.
ASK_MAT_V = 1
MAT_BOIL = re.compile(r"있을\s*수\s*있|차이가\s*있을|단순\s*(?:가감|합산)|내부\s*거래가?\s*제거|기준으로\s*(?:작성|산정|기재)|"
                      r"다음과\s*같(?:습니다|음)|아래와\s*같(?:습니다|음)|참[고조]하시|바랍니다|이원화|으로\s*구성되어|를\s*의미|을\s*의미|"
                      r"을\s*말합니다|를\s*말합니다|정의(?:합니다|됨)|기재\s*단위|단위\s*:|^\(?\s*단위")
MAT_SOFT = re.compile(r"^\(?\s*주\s*\d*\)|^\(\*\d*\)|포함되어\s*있|지속적으로|추구하고|노력하고|노력할|최선을|강화하고\s*있|힘쓰고|대응하고\s*있|"
                      r"기여하고\s*있|추진하고\s*있습니다$|하고\s*있습니다$|예정입니다$")
MAT_BAD = re.compile(r"소송(?:을|이)?\s*(?:제기|접수|계류)|피소|패소|과징금|시정\s*명령|제재\s*(?:를|가|조치)|영업\s*정지|손해\s*배상\s*(?:청구|소송|의무)|리콜|"
                     r"화재|폭발|중대\s*재해|가동\s*(?:중단|중지)|조업\s*중단|계약\s*(?:이\s*)?(?:해지|취소|해제)|손상\s*차손\s*(?:을\s*)?(?:인식|계상)|"
                     r"적자\s*(?:로\s*)?전환|영업\s*손실|순\s*손실|유상\s*증자|전환\s*사채\s*(?:를\s*|을\s*)?발행|전환\s*가액\s*(?:의\s*)?(?:조정|하향)|리픽싱|"
                     r"주식\s*담보|반대\s*매매|횡령|배임|한정\s*의견|부적정|의견\s*거절|계속\s*기업|중요한\s*불확실성|책임\s*준공\s*(?:을\s*)?(?:미이행|기한)|"
                     r"준공이\s*완료되지|(?:채무|차입금|PF)[^.]{0,40}?인수(?:하였|했|함|하게)|자금\s*보충|최대\s*주주\s*(?:의\s*)?변경|경영권\s*분쟁|"
                     r"가격\s*경쟁\s*(?:이\s*)?(?:심화|격화)|(?<!구매)(?<!구매 )(?<!원재료)(?<!원재료 )(?<!원자재)(?<!원자재 )(?<!원료)(?<!원료 )(?:판매\s*)?(?:가격|판가|단가|시장\s*가격)\s*(?:의\s*)?(?:하락|인하)|"
                     r"수요\s*(?:가\s*)?(?:감소|둔화|부진|위축)|매출\s*(?:이\s*)?(?:감소|하락)|(?:납기|공사|준공)\s*(?:가\s*|이\s*)?지연|철회|감산|"
                     r"구조\s*조정|희망\s*퇴직|부도|회생\s*절차|파산|상장\s*폐지|관리\s*종목|불성실\s*공시|수출\s*규제|반덤핑|상계\s*관세")
MAT_GOOD = re.compile(r"수주\s*(?:를\s*|을\s*)?(?:달성|확보|성공|하였|했)|(?:공급|납품|판매)\s*계약\s*(?:을\s*)?체결|계약을\s*체결|낙찰|우선\s*협상|"
                      r"(?:공급사|업체|사업자)로\s*선정|양산(?:화)?\s*(?:를\s*|을\s*)?(?:개시|시작|돌입|완료)|양산화|인증\s*(?:을\s*)?(?:획득|취득|완료)|"
                      r"승인\s*(?:을\s*)?(?:획득|받)|상용화\s*(?:에\s*)?(?:완료|성공)|증설\s*(?:을\s*)?(?:완료|결정|착수)|신규\s*(?:고객|수주|거래처)\s*(?:를\s*|을\s*)?확보|"
                      r"점유율\s*(?:이\s*)?(?:상승|확대|증가|1위)|(?:판가|판매\s*가격|단가)\s*(?:를\s*|을\s*|가\s*|이\s*)?(?:인상|상승)|사상\s*최대|최대\s*(?:실적|매출|수주)|"
                      r"흑자\s*(?:로\s*)?전환|배당\s*(?:을\s*)?(?:확대|증가|상향)|분기\s*배당|(?:자기\s*주식|자사주)\s*(?:을\s*|를\s*)?소각|소각\s*(?:을\s*)?(?:결정|완료)|"
                      r"상환\s*(?:을\s*)?(?:완료|하였)|전환권\s*(?:이\s*)?소멸|담보\s*(?:가\s*)?해제|해소되|승소|무죄|소\s*취하|집행\s*정지\s*(?:신청\s*)?인용|"
                      r"수요\s*(?:가\s*|의\s*)?(?:증가|호조|확대|강세)|공급\s*부족|수급\s*(?:이\s*)?타이트|(?:공급|수급)\s*격차")
MAT_POT = re.compile(r"신규\s*사업|진출|(?:인수|합병|분할|매각)\s*(?:를\s*|을\s*)?(?:결정|추진|완료|예정|검토)|투자\s*(?:를\s*|을\s*)?(?:결정|계획|예정)|"
                     r"(?:공장|생산\s*시설|라인)\s*(?:을\s*|를\s*)?(?:건설|신설|착공)|착공|준공\s*예정|양해\s*각서|MOU|업무\s*협약|규제|관세|보조금|"
                     r"법\s*(?:개정|시행)|입찰\s*(?:참여|예정)|주주\s*가치\s*제고|밸류\s*업")
MAT_DONE = re.compile(r"(?:하였|되었|했|됐)(?:습니다|으며|고|음)|(?:체결|결정|완료|선고|확정|인수|접수|인용|획득|달성|선정)(?:함|됨|하였|되었|했|하고|하는|하여|$)")
MAT_QTY = re.compile(r"\d[\d,.]*\s*(?:MW|GW|MWh|GWh|kV|척|톤|만\s*대|기\b)")
_MAT_DT = re.compile(r"(20\d\d)\s*[.년]\s*(\d{1,2})")
MAT_NAME = re.compile(r"^(?:[A-Z][A-Za-z0-9&.\-]{1,}|[가-힣]{2,}(?:전자|전력|에너지|파워|중공업|건설|화학|오션|그룹))$")
_MAT_AMT = re.compile(r"(?<![제\d,.])(\d[\d,]*(?:\.\d+)?)\s*(조(?!\s*의\s*\d)(?!\s*제?\s*\d+\s*항)|억|백만|천)\s*(?:\d[\d,]*\s*억\s*)?(?:원|달러|USD|유로)?|"
                      r"(?:US\$|USD|\$)\s*(\d[\d,]*(?:\.\d+)?)\s*(billion|million|bn|mn)?|"
                      r"\b(EUR|JPY|CNY|RMB|VND|MXN|ARS|TND|INR|BRL|GBP|HKD|SGD|TWD|IDR|PLN|HUF|CZK|TRY)\s*(\d[\d,]*(?:\.\d+)?)|"
                      r"(\d[\d,]*(?:\.\d+)?)\s*(EUR|JPY|CNY|RMB|VND|MXN|ARS|TND|INR|BRL|GBP|HKD|SGD|TWD|IDR|PLN|HUF|CZK|TRY)\b")
_MAT_FX = {"EUR": 1500, "JPY": 9.5, "CNY": 195, "RMB": 195, "VND": 0.055, "MXN": 75, "ARS": 1.4, "TND": 450, "INR": 16, "BRL": 250,
           "GBP": 1800, "HKD": 180, "SGD": 1050, "TWD": 43, "IDR": 0.085, "PLN": 350, "HUF": 3.8, "CZK": 60, "TRY": 40}
MAT_PROCEEDS = re.compile(r"조달한\s*자금[^.]{0,80}사용|자금의\s*사용\s*(?:내역|실적)")
MAT_JOIN = re.compile(r"증자에\s*참여|출자하였|출자\s*건|출자를\s*완료|출자\s*금액|참여하여|(?:지분|주식|보통주)[^.]{0,30}취득|지분율이\s*(?:변동|상승|하락)")
MAT_OWN = re.compile(r"당사(?:는|가|의)|지배\s*(?:회사|기업)(?:는|가)|(?<![가-힣])회사는")
MAT_SUB = re.compile(r"종속\s*(?:회사|기업)|자회사|Inc\.?|LLC|Corporation|Ltd|㈜|\(주\)")
MAT_BS = re.compile(r"(?:유동|비유동)?\s*(?:부채|자산|자본)(?:총계)?\s*(?:는|은|이|가)\s*전년\s*(?:말\s*)?대비|(?:부채|자산|자본)(?:총계)?\s*(?:가|이)?\s*[\d,]+\s*(?:억|조|백만)")


def _won_amounts(sent):
    """문장 속 금액(원). 달러는 1,400원으로 어림한다."""
    out = []
    for m in _MAT_AMT.finditer(sent):
        try:
            if m.group(1):
                v = float(m.group(1).replace(",", ""))
                unit = {"조": 1e12, "억": 1e8, "백만": 1e6, "천": 1e3}[m.group(2)]
                tail = sent[m.end() - 4:m.end() + 2]
                fx = 1400 if ("달러" in tail or "USD" in tail) else 1
                out.append(v * unit * fx)
            elif m.group(3):
                v = float(m.group(3).replace(",", ""))
                unit = {"billion": 1e9, "bn": 1e9, "million": 1e6, "mn": 1e6}.get((m.group(4) or "").lower(), 1)
                out.append(v * unit * 1400)
            elif m.group(5):
                out.append(float(m.group(6).replace(",", "")) * _MAT_FX[m.group(5)])
            elif m.group(7):
                out.append(float(m.group(7).replace(",", "")) * _MAT_FX[m.group(8)])
        except ValueError:
            continue
    return out


def _ask_scale(c):
    """회사 규모 — 마지막 사업보고서의 매출 · 자본총계."""
    corp = corp_code_of(c["code"]) if FIN is not None else None
    if not corp:
        return {}
    this = dt.date.today().year
    try:
        a = FIN.annual_actuals(corp, [this - 1, this - 2])
    except Exception:
        return {}
    y = max(a) if a else None
    return {"rev": a[y].get("매출액"), "eq": a[y].get("자본총계"), "year": y} if y else {}


def _ask_material(e, q, scale):
    """새 말 하나가 주가에 닿을 만한가 — {tone, ms, why[], amt, pct} 또는 None."""
    sent = _ask_clean(e["text"])
    if MAT_BOIL.search(sent):
        return None
    bad, good, pot = MAT_BAD.search(sent), MAT_GOOD.search(sent), MAT_POT.search(sent)
    why, tone, ms = [], None, 0.0
    amts = _won_amounts(sent)
    amt = max(amts) if amts else None
    base = max(v for v in (scale.get("rev"), scale.get("eq")) if v) if (scale.get("rev") or scale.get("eq")) else None
    pct = amt / scale["rev"] * 100 if (amt and scale.get("rev")) else None
    pct_eq = amt / scale["eq"] * 100 if (amt and scale.get("eq")) else None
    big = max(x for x in (pct, pct_eq) if x is not None) if (pct is not None or pct_eq is not None) else None
    if e["k"] == "gone":
        if not (bad or good):
            return None
        tone, ms = "잠재", 1.2
        why.append(("위험 문장이 빠짐 — 끝났나, 실현됐나" if bad else "좋은 말이 빠짐 — 끝났나, 멈췄나"))
    elif bad and good:
        tone, ms = ("악재" if q["clock"] == "risk" else "잠재"), 1.8
        why += [bad.group(0).strip(), good.group(0).strip()]
    elif bad and re.search(r"유상\s*증자", bad.group(0)) and (MAT_JOIN.search(sent) or (MAT_SUB.search(sent) and not MAT_OWN.search(sent))):
        tone, ms = "잠재", 1.4
        why.append("자회사 · 투자처 증자 참여(희석 아님)")
    elif bad:
        tone, ms = "악재", 2.4
        why.append(bad.group(0).strip())
    elif good and q["id"] == "mna":
        tone, ms = "잠재", 1.8
        why.append(good.group(0).strip())
    elif good:
        tone, ms = "호재", 2.0
        why.append(good.group(0).strip())
    elif q["id"] == "customer" and e.get("add") and any(MAT_NAME.match(t) for t in e["add"]):
        tone, ms = "잠재", 1.6
        why.append("주요 매출처에 새 이름: " + ", ".join([t for t in e["add"] if MAT_NAME.match(t)][:4]))
    elif pot:
        tone, ms = "잠재", 1.3
        why.append(pot.group(0).strip())
    elif big is not None and big >= 5 and MAT_DONE.search(sent):
        tone, ms = "잠재", 1.2
    else:
        return None
    if big is not None:
        ms += 3.0 if big >= 15 else 2.0 if big >= 5 else 1.0 if big >= 1 else 0.0 if big >= 0.1 else -2.0
        if big >= 1:
            why.append("%s · %s의 %.0f%%" % (_won_txt(amt), "매출" if pct is not None and pct >= (pct_eq or 0) else "자본", big))
        elif big < 0.1:
            why.append("작은 금액(%s)" % _won_txt(amt))
    elif amt and base is None:
        ms += 0.5
    if MAT_QTY.search(sent):
        ms += 0.5
        why.append(MAT_QTY.search(sent).group(0).strip())
    if DATE_RE.search(sent):
        ms += 0.4
    done = MAT_DONE.search(sent)
    if done:
        ms += 0.6
    # 지난 일 — 문장 속 날짜가 모두 보고서 시점보다 9개월 넘게 앞이면 이미 알려진 일이다(소송 접수일을 되풀이해 적은 문장)
    dts = [int(a) * 12 + int(b) for a, b in _MAT_DT.findall(sent) if 1 <= int(b) <= 12]
    if dts:
        rep_m = int(e["stamp"][:4]) * 12 + int(e["stamp"][5:7])
        if rep_m - max(dts) > 9:
            ms -= 1.2
            why.append("%d개월 전 일" % (rep_m - max(dts)))
    else:
        yrs = [int(y) for y in re.findall(r"(20\d\d)\s*년", sent)]
        if yrs and max(yrs) < int(e["stamp"][:4]):
            ms -= 1.0
            why.append("%d년 일" % max(yrs))
    # 보고서 자체가 오래됐다 — 최근 네 건이 1년을 넘는 회사(정정 · 첨부 보고서가 섞임)
    if e.get("latest"):
        lag = (int(e["latest"][:4]) * 12 + int(e["latest"][5:7])) - (int(e["stamp"][:4]) * 12 + int(e["stamp"][5:7]))
        if lag > 9:
            ms -= 0.8
        elif lag > 6:
            ms -= 0.4
    if MAT_PROCEEDS.search(sent):
        ms -= 1.5
    if MAT_BS.search(sent):
        ms -= 1.5
    if q["clock"] == "risk" and tone == "악재":
        ms += 0.5
    if e["k"] == "born":
        ms += 0.3
    elif e["k"] == "edit":
        ms += 0.2 * min(3, len(e.get("add") or []))
    if MAT_SOFT.search(sent) and not done:
        ms -= 1.0
    if len(sent) > 300:
        ms -= 0.5
    def lab(t):          # 걸린 원문 → 짧은 이름표('PF) 차입금 346,300백만원을 인수하였' → 'PF 차입금 인수')
        if "·" in t or "%" in t or "전 일" in t or t.endswith("년 일") or len(t) > 40 or MAT_QTY.fullmatch(t.strip()):
            return t
        t = re.sub(r"[()\[\]]", " ", t)
        t = re.sub(r"[\d,.]+\s*(?:백만|억|조|천)?\s*원?\s*(?:을|를)?", " ", t)
        t = re.sub(r"\s*(?:을|를|이|가)\s+", " ", t)
        t = re.sub(r"(?:하였|했|함|하게|되었)$", "", re.sub(r"\s+", " ", t).strip())
        return t.strip() or "—"
    return {"tone": tone, "ms": round(ms, 2), "why": [lab(w) for w in why[:3]], "amt": amt,
            "pct": round(big, 1) if big is not None else None}


def ask_build(c, prog=None):
    reps = c["reports"]
    n = len(reps)
    need = set()
    for q in ASK_Q:
        need |= set(q["secs"])
    lin = {q["id"]: _Lineage() for q in ASK_Q}
    counts = {q["id"]: [0] * n for q in ASK_Q}
    base_end = min(4, max(1, n // 4))            # 첫 1년은 전부 '처음'이라 새 말로 치지 않는다
    recent = max(base_end, n - 4)                # 최근 네 건 ≈ 1년
    old_flat, new_toks, new_first = [], Counter(), {}
    for ri, r in enumerate(reps):
        if prog is not None:
            prog["done"] = ri
        texts = defaultdict(list)
        for s in r["sections"]:
            if s["norm"] in need:
                texts[s["norm"]].append((s["file"], corpus_text(c, r, s["file"])))
        # 처음 나온 말 — 사업의 내용·경영진단에서 최근 1년에 처음 쓰기 시작한 낱말
        story = "\n".join(t for sec in (_AB, _AM) for _, t in texts.get(sec, ()))
        if ri < recent:
            old_flat.append(_ask_flat(story))
        elif INF:
            for t in set(INF.tokens(story)):
                new_toks[t] += 1
                new_first.setdefault(t, ri)
        yr = int(r["stamp"][:4])
        for q in ASK_Q:
            for sec in q["secs"]:
                for fn, t in texts.get(sec, ()):
                    k, lines = _ask_lines(t, q["_rx"])
                    counts[q["id"]][ri] += k
                    for line in lines:
                        for sent in _ask_sents(line, q["_rx"]):
                            if _ask_sent_ok(sent, yr, q.get("raw")):
                                lin[q["id"]].add(ri, sent, sec, fn)
    old_blob = "\n".join(old_flat)
    came = []
    for t, k in sorted(new_toks.items(), key=lambda x: (-x[1], new_first[x[0]])):
        if k < 2 or len(t) < 2 or t in old_blob or GIST_TERM_SKIP.search(t) or ASK_SKIP_TOK.match(t) or ASK_JUNK_TOK.match(t):
            continue
        if HANGUL_RE.search(t) and (len(t) < 3 or len(t) > 7 or ASK_VERBISH.search(t) or ASK_GLUE.search(t)):
            continue
        came.append({"t": t, "n": k, "first": reps[new_first[t]]["stamp"]})
        if len(came) >= 14:
            break
    last_of = {}
    for i, r in enumerate(reps):
        last_of[r["label"]] = i
    nxt = [None] * n                             # 같은 종류의 다음 보고서
    seen_lab = {}
    for i in range(n - 1, -1, -1):
        nxt[i] = seen_lab.get(reps[i]["label"])
        seen_lab[reps[i]["label"]] = i
    out = []
    spot = []
    mats = []                                    # 주가에 닿을 줄 후보 (ms, 질문, 묶음)
    scale = _ask_scale(c)
    for q in ASK_Q:
        L, cnt = lin[q["id"]], counts[q["id"]]
        ev = []
        for f in L.fams:
            occ = sorted(f["occ"])
            if not occ:
                continue
            b = f["born"]
            if b >= base_end:
                sent, sec, fn = f["occ"][b]
                ev.append({"k": "born", "ri": b, "text": sent, "sec": sec, "file": fn,
                           "score": _ask_score(sent, q, "born")})
            for ri, sent, add, rm in L.edits(f):
                if ri >= base_end:
                    sec, fn = f["occ"][ri][1], f["occ"][ri][2]
                    ev.append({"k": "edit", "ri": ri, "text": sent, "sec": sec, "file": fn, "add": add, "rm": rm,
                               "score": _ask_score(sent, q, "edit", len(add))})
            lo = occ[-1]
            gone_at = nxt[lo]
            # 같은 종류 다음 보고서에 없으면 빠진 말. 그 보고서에 해당 섹션이 아예 없으면(서식 차이) 치지 않는다.
            # 한두 번 쓰고 만 업황 설명은 분기마다 갈아 끼우는 문장이라 '빠진 말'로 치지 않는다
            if gone_at is not None and gone_at >= base_end and len(occ) >= 3:
                secs_there = {s["norm"] for s in reps[gone_at]["sections"]}
                sent, sec, fn = f["occ"][lo]
                if sec in secs_there:
                    ev.append({"k": "gone", "ri": gone_at, "text": sent, "sec": sec, "file": fn, "from": lo,
                               "score": _ask_score(sent, q, "gone")})
        rec = [e for e in ev if e["ri"] >= recent]
        rec.sort(key=lambda e: (-e["score"], -e["ri"]))
        # 무게 있는 새 말 — 금액·범주 낱말·꼬리 위험 중 하나는 있어야 한다. 맨 문장 하나 새로 쓴 건 문구 손질
        sig = [e for e in rec if e["k"] != "gone" and e["score"] >= ASK_SIG]
        drop = [e for e in rec if e["k"] == "gone" and e["score"] >= ASK_SIG - 0.3]
        older = sorted([e for e in ev if e["ri"] < recent and e["k"] != "gone" and e["score"] >= ASK_SIG],
                       key=lambda e: (-e["ri"], -e["score"]))
        first = next((i for i, v in enumerate(cnt) if v), None)
        tot_recent = sum(cnt[recent:])
        tot_before = sum(cnt[:recent])
        # 평소 — 지난 해들(네 건씩 끊어)마다 무게 있는 새 말이 몇 개 나왔나의 중앙값. 해마다 업황 문장을 갈아 쓰는 회사는 높다
        per = [sum(1 for e in ev if e["k"] != "gone" and e["score"] >= ASK_SIG and w <= e["ri"] < w + 4)
               for w in range(base_end, recent - 3, 4)]
        usual = sorted(per)[len(per) // 2] if per else 0
        if first is None:
            st = "none"
        elif first >= recent and first >= base_end:
            st = "first"
        elif tot_recent == 0 and tot_before > 0:
            st = "gone"
        elif sig and len(sig) > usual:
            st = "new"
        elif sig:
            st = "usual"
        elif drop:
            st = "dropped"
        else:
            st = "quiet"
        lead = sig or drop
        sc = lead[0]["score"] + 0.4 * min(4, len(lead) - 1) if lead else 0.0
        if st == "first":
            sc += 3.0
        elif st == "usual":
            sc *= 0.7

        def pack(e):
            t = _ask_clean(e["text"])
            d = {"k": e["k"], "text": t[:420], "short": _short(t, 96), "sec": e["sec"],
                 "sec_s": SEC_SHORT.get(e["sec"], e["sec"]), "file": e["file"], "score": e["score"]}
            d.update(_ask_rep(reps, e["ri"]))
            if e.get("add"):
                d["add"], d["rm"] = e["add"], e["rm"]
            if e["k"] == "gone":
                d["from"] = _ask_rep(reps, e["from"])
            return d
        marks = [0] * n
        for e in ev:
            if e["k"] != "gone" and e["score"] >= ASK_SIG:
                marks[e["ri"]] += 1
        shown = sig + drop + [e for e in rec if e not in sig and e not in drop]
        mq = {"호재": 0, "악재": 0, "잠재": 0}
        for e in rec:
            m = _ask_material(dict(e, stamp=reps[e["ri"]]["stamp"], latest=reps[-1]["stamp"]), q, scale)
            if m and m["ms"] >= ASK_MAT_MIN:
                mq[m["tone"]] += 1
                mats.append((m["ms"], e["ri"], q["id"], dict(pack(e), **m)))
        item = {"id": q["id"], "status": st, "score": round(sc, 2), "counts": cnt, "marks": marks, "mat": mq,
                "first": _ask_rep(reps, first) if first is not None else None,
                "n_recent": len(sig), "n_drop": len(drop), "n_minor": len(rec) - len(sig) - len(drop), "usual": usual,
                "n_fams": len(L.fams),
                "recent": [pack(e) for e in shown[:6]],
                "older": [pack(e) for e in older[:3]],
                "last_sig": _ask_rep(reps, older[0]["ri"]) if older else None}
        out.append(item)
        if sig:
            spot.append((sc, q["id"], pack(sig[0])))
        elif st == "first" and rec:
            spot.append((sc, q["id"], pack(rec[0])))
    spot.sort(key=lambda x: -x[0])
    # 주가에 닿을 줄 — 같은 문장이 여러 질문에 걸리면 무거운 쪽 하나만
    mats.sort(key=lambda x: (-x[0], -x[1]))
    import math
    material, seen_sk = [], set()
    per_q = Counter()
    for ms, ri, qid, d in mats:
        if per_q[qid] >= 2:                      # 한 질문이 목록을 다 차지하지 않게
            continue
        sk = _ask_skel(d["text"])[:60]
        # 같은 사건을 보고서마다 되풀이해 적는다 — 같은 질문 안에서 금액(±25%)이나 날짜(연 · 월)가 같으면 하나만
        ak = (qid, round(math.log10(d["amt"]), 1)) if d.get("amt") else None
        dk = (qid, max(_MAT_DT.findall(d["text"]))) if _MAT_DT.findall(d["text"]) else None
        if sk in seen_sk or (ak and ak in seen_sk) or (dk and dk in seen_sk):
            continue
        seen_sk.update(x for x in (sk, ak, dk) if x)
        per_q[qid] += 1
        material.append(dict(d, q=qid))
        if len(material) >= 9:
            break
    # 지금 읽을 줄도 주가에 닿을 줄 순서로 — 없으면 예전 무게순
    spot_m = []
    for d in material:
        if d["q"] not in [x["id"] for x in spot_m]:
            spot_m.append({"id": d["q"], "score": d["ms"], "ev": d})
    return {"v": ASK_V, "reports": [_ask_rep(reps, i) for i in range(n)], "recent_from": recent,
            "base_end": base_end, "questions": out, "came": came, "material": material, "scale": scale,
            "spotlight": spot_m[:5] or [{"id": i, "score": round(s, 2), "ev": e} for s, i, e in spot[:5]]}


ASKING = {}
ASK_LOCK = threading.Lock()


def _ask_path(code):
    return os.path.join(CACHE_DIR, "ask", code + ".json")


def _ask_sig(c):
    return "%s:%d" % (c["reports"][-1]["rcept"] if c["reports"] else "", len(c["reports"]))


def _run_ask(code):
    st = ASKING[code]
    try:
        c = company_by_code(code)
        d = ask_build(c, st)
        d["sig"] = _ask_sig(c)
        d["built"] = time.time()
        os.makedirs(os.path.dirname(_ask_path(code)), exist_ok=True)
        with open(_ask_path(code), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
    except Exception as e:
        st["error"] = "%s: %s" % (type(e).__name__, e)
        return
    with ASK_LOCK:
        ASKING.pop(code, None)
    _warm_corpus(c)


def _warm_corpus(c):
    """나머지 섹션도 미리 읽어 둔다 — 첫 전문검색이 드라이브를 기다리지 않게."""
    try:
        for r in c["reports"]:
            for s in r["sections"]:
                corpus_text(c, r, s["file"])
            if c["code"] not in _CORPUS:        # 다른 두 회사가 들어와 밀려났다
                return
    except Exception:
        pass


def ask_view(code):
    c = company_by_code(code)
    if not c:
        return None
    p = _ask_path(code)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("v") == ASK_V and d.get("sig") == _ask_sig(c):
                d["meta"], d["themes"] = ASK_META, ASK_THEMES
                with _CORPUS_LOCK:
                    cold = code not in _CORPUS
                    if cold:
                        _CORPUS[code] = {}
                        _CORPUS_ORDER.append(code)
                        while len(_CORPUS_ORDER) > 2:
                            _CORPUS.pop(_CORPUS_ORDER.pop(0), None)
                if cold:
                    threading.Thread(target=_warm_corpus, args=(c,), daemon=True).start()
                return d
        except Exception:
            pass
    with ASK_LOCK:
        st = ASKING.get(code)
        if st is None or st.get("error"):
            if st and st.get("error") and time.time() - st.get("at", 0) < 30:
                return {"error": st["error"], "meta": ASK_META, "themes": ASK_THEMES}
            st = ASKING[code] = {"done": 0, "total": len(c["reports"]), "at": time.time()}
            threading.Thread(target=_run_ask, args=(code,), daemon=True).start()
    return {"pending": True, "done": st["done"], "total": st["total"], "meta": ASK_META, "themes": ASK_THEMES}


# 자주 갈라 쓰는 말 — 하나를 찾으면 나머지도 같이 찾는다
ASK_SYN = [("가동률", "가동율"), ("수주잔고", "수주잔액"), ("자사주", "자기주식"), ("R&D", "연구개발"),
           ("스톡옵션", "주식매수선택권"), ("CB", "전환사채"), ("BW", "신주인수권부사채"), ("M&A", "인수합병"),
           ("점유율", "M/S"), ("판가", "판매가격"), ("CAPEX", "설비투자"), ("EB", "교환사채"), ("RSU", "양도제한조건부")]
ASK_SYN_MAP = {a: b for a, b in ASK_SYN} | {b: a for a, b in ASK_SYN}


def ask_query_rx(query):
    """'수주 잔고, HBM' → 쉼표는 '또는'. 한글은 띄어쓰기를 무시하고, 짧은 영문 약어는 낱말 경계로 찾는다."""
    terms = [t.strip() for t in re.split(r"[,，]", query or "") if t.strip()][:6]
    extra = []
    for t in terms:
        k = re.sub(r"\s+", "", t).lower()
        for grp in ASK_SYN:
            if k in [g.lower() for g in grp]:
                extra += [g for g in grp if g.lower() != k and g not in terms and g not in extra]
    pats = []
    for t in terms + extra:
        if HANGUL_RE.search(t):
            pats.append(r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", t)))
        elif len(t) <= 4:
            pats.append(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])")
        else:
            pats.append(re.escape(t))
    if not pats:
        return None, [], []
    return re.compile("|".join("(?:%s)" % p for p in pats), re.I), terms, extra


def lineage(c, rx, secs=None, labels=None, raw=True, strict=False):
    """정규식이 걸린 문장을 족보로 묶어 네 갈래로 — 새로 생김 · 숫자가 움직임 · 사라짐 · 늘 있던 말.
    표 칸에 걸린 것은 뒤 칸 몇 개를 붙여 '표 조각'으로 따로 모은다."""
    reps = [r for r in c["reports"] if not labels or r["label"] in labels]
    n = len(reps)
    if not n:
        return {"reports": [], "families": [], "timeline": []}
    L, T = _Lineage(), _Lineage()
    tl = [0] * n
    recent_toks, old_toks = Counter(), Counter()
    base_end = min(4, max(1, n // 4))
    recent = max(base_end, n - 4)
    for ri, r in enumerate(reps):
        yr = int(r["stamp"][:4])
        for s in r["sections"]:
            if secs and s["norm"] not in secs:
                continue
            t = corpus_text(c, r, s["file"])
            if not t:
                continue
            k, lines = _ask_lines(t, rx)
            if not k:
                continue
            tl[ri] += k
            for line in lines:
                ls = line.strip()
                prose = len(ls) >= 40 or SENT_END.search(ls)
                if not prose:
                    # 표 칸 — 뒤 칸 네 개를 붙인다
                    pos = t.find(line)
                    tail = t[pos + len(line):pos + len(line) + 400].split("\n") if pos >= 0 else []
                    cells = [ls] + [x.strip() for x in tail if x.strip()][:4]
                    frag = " │ ".join(cells)[:220]
                    T.add(ri, frag, s["norm"], s["file"])
                    continue
                for sent in _ask_sents(line, rx):
                    if strict:
                        if not _ask_sent_ok(sent, yr, raw):
                            continue
                    elif len(sent) < 12 or sent.count("\t") >= 2:
                        continue
                    L.add(ri, sent, s["norm"], s["file"])
                    if INF:
                        (recent_toks if ri >= recent else old_toks).update(set(INF.tokens(sent)))
    nxt, seen_lab = [None] * n, {}
    for i in range(n - 1, -1, -1):
        nxt[i] = seen_lab.get(reps[i]["label"])
        seen_lab[reps[i]["label"]] = i

    def fam_out(f, table=False):
        occ = sorted(f["occ"])
        lo = occ[-1]
        sent, sec, fn = f["occ"][lo]
        nums = []
        for ri in occ:
            v = _ask_nums(f["occ"][ri][0])
            if v:
                nums.append([ri, v])
        distinct = len({tuple(v) for _, v in nums})
        gone_at = nxt[lo]
        dead = gone_at is not None and sec in {s["norm"] for s in reps[gone_at]["sections"]}
        d = {"born": f["born"], "last": lo, "n": len(occ), "occ": occ if len(occ) <= 80 else occ[-80:],
             "text": (sent if table else _ask_clean(sent))[:520], "sec": sec, "sec_s": SEC_SHORT.get(sec, sec), "file": fn,
             "first_text": _ask_clean(f["occ"][occ[0]][0])[:520] if len(f["vers"]) > 1 and not table else None,
             "dead": gone_at if dead else None, "table": table}
        if distinct >= 2:
            # 값이 바뀐 때만 남긴다
            keep, prev = [], None
            for ri, v in nums:
                if v != prev:
                    keep.append([ri, v])
                prev = v
            d["nums"] = keep[-12:]
        if not table:
            ed = L.edits(f)
            if ed:
                d["edits"] = [{"ri": ri, "add": a, "rm": b} for ri, _, a, b in ed[-4:]]
        if f["born"] >= recent and f["born"] >= base_end:
            d["g"] = "new"
        elif dead:
            d["g"] = "gone"
        elif distinct >= 2 or d.get("edits"):
            d["g"] = "moved"
        else:
            d["g"] = "steady"
        return d
    fams = [fam_out(f) for f in L.fams if f["occ"]]
    tabs = [fam_out(f, True) for f in T.fams if f["occ"]]
    order = {"new": 0, "moved": 1, "gone": 2, "steady": 3}
    fams.sort(key=lambda d: (order[d["g"]], -(d["born"] if d["g"] == "new" else d["dead"] if d["g"] == "gone" else d["last"] if d["g"] == "moved" else -d["born"]), -d["n"]))
    tabs.sort(key=lambda d: (-d["last"], -d["n"]))
    births = [0] * n
    for f in L.fams:
        if f["occ"] and f["born"] >= base_end:
            births[f["born"]] += 1
    came = []
    for t, k in recent_toks.most_common(200):
        if (k >= 2 and not old_toks.get(t) and not GIST_TERM_SKIP.search(t) and not rx.search(t)
                and not ASK_JUNK_TOK.match(t) and not ASK_SKIP_TOK.match(t)
                and not (HANGUL_RE.search(t) and (ASK_VERBISH.search(t) or ASK_GLUE.search(t)))):
            came.append({"t": t, "n": k})
        if len(came) >= 12:
            break
    first = next((i for i, v in enumerate(tl) if v), None)
    return {"rx": rx.pattern, "reports": [_ask_rep(reps, i) for i in range(n)], "timeline": tl, "births": births,
            "first": first, "recent_from": recent, "base_end": base_end,
            "families": fams[:160], "n_families": len(fams), "tables": tabs[:40], "n_tables": len(tabs),
            "came": came}


# ---------------------------------------------------------------- 풍경: 15년을 처음부터 끝까지 읽은 사람의 눈
# 버핏과 린치는 한 회사의 보고서를 수십 년치 처음부터 읽는다. 그렇게 해야 보이는 것 세 가지를 한 화면에 옮겼다.
#   풍경 — 회사가 어떤 유형으로 살아왔나(린치의 여섯 유형), 주가는 이익을 따라갔나(린치의 이익선)
#   안목 — 이 회사의 15년이 가르치는 규칙(불황 성적, 자본 배분, 유보이익 1원 테스트, 사업 정의의 일관성)
#   결단 — 그들의 조건이 과거 어느 때 맞았고 그 뒤 주가는 어땠나, 그리고 지금은(기다릴 가격)
# 주당 값은 액면분할·무상증자를 연말 주식 수로 역산해 오늘 주식 수 기준으로 맞춘다(네이버 수정주가와 같은 기준).
LAND_V = 9          # 8 · 9: 마지막 사업보고서 뒤 분기 · 반기가 있으면 최근 4분기 칸(2026-10-03, 9 = 배당은 마지막 결산 값)
LAND_Q_END = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}
LAND_TYPES = {   # 린치의 여섯 유형 + 적자기
    "고성장": ("FAST GROWER", "매출이 해마다 15% 넘게 늘었다", "성장률이 유지되는 동안 들고 간다. PER이 성장률을 넘으면(PEG>1) 조심, 성장이 꺾이는 첫 분기에 판다."),
    "대형우량": ("STALWART", "매출이 해마다 5–15% 늘며 흑자를 지켰다", "이익선보다 30~50% 싸게 살 기회를 기다린다. 30~50% 오르면 일부 판다."),
    "저성장": ("SLOW GROWER", "매출이 해마다 5% 안쪽으로 늘었다", "배당을 보고 산다. 배당을 끊거나 줄이면 판다."),
    "경기순환": ("CYCLICAL", "이익이 업황 따라 반토막 났다 두 배가 되기를 되풀이했다", "이익이 바닥이라 PER이 가장 비싸 보일 때 사고, 이익이 정점이라 PER이 가장 싸 보일 때 판다. 재고가 줄기 시작하는 게 신호."),
    "회생": ("TURNAROUND", "적자를 벗어나 흑자로 돌아섰다", "빚을 버틸 수 있는지부터 본다. 흑자가 두 해 이어지면 다른 유형으로 옮겨 간다."),
    "적자": ("LOSS-MAKING", "순손실을 냈다", "린치는 이때 회생 가능성(현금·차입·구조조정)을 본다. 흑자 전환 전에는 이야기만 있다."),
}


# 장(章)에 '들어온 말'에서 뺄 것 — 회계·위험관리 서식어, 조직명, 흔한 나라 약어
LAND_WORD_SKIP = re.compile(r"위험|회피|공정가치|매매목적|소유형태|변수|이사회|지분|특허법|누적|추가|필수|값임|쉽고|팀$|파생|금리|이자율|환율|"
                            r"회계|손익|채권|채무|평가|주식|소송|^(?:USA|US|EU|UK|HD|GE|SK|LG)$")


def _land_pct(vals, v):
    s = [x for x in vals if x is not None]
    if not s or v is None:
        return None
    return sum(1 for x in s if x <= v) / len(s) * 100


def _land_q(vals, q):
    s = sorted(x for x in vals if x is not None)
    if not s:
        return None
    k = (len(s) - 1) * q
    i = int(k)
    return s[i] + (s[min(i + 1, len(s) - 1)] - s[i]) * (k - i)


LAND_SHARES_FROM = 2015    # DART 주식 수 API(stockTotqySttus)는 2015 사업보고서부터 — 그 앞 해는 늘 빈값이라 묻지 않는다(캐시에 있으면 읽기만)


def _shares_cached(corp, year, reprt):
    return os.path.exists(os.path.join(FIN.FIN_DIR, "shares_%s_%s_%s.json" % (corp, year, reprt)))


def _land_shares(F, corp, latest=None, bad=None):
    """연말 주식 수를 오늘 기준으로 — 한 해에 1.8배 넘게(또는 0.55배 아래로) 바뀌면 분할·무상증자로 보고
    그 앞 해들에 비율을 곱한다. 2015년 이전(DART 에 없음)은 알려진 가장 이른 해 값으로 채운다.
    bad(list)를 주면 일시 오류(한도 · 점검 · 네트워크 — 빈값인데 캐시 파일이 안 생김)로 못 받은 (연도, 보고서 코드)를 담는다."""
    def get(y, reprt):
        try:
            v = FIN.fetch_shares(corp, y, reprt).get("shares")
        except Exception:
            v = None
        if v is None and bad is not None and not _shares_cached(corp, y, reprt):
            bad.append((y, reprt))
        return v
    raw = {}
    for d in F:
        y = d["year"]
        if y < LAND_SHARES_FROM and not _shares_cached(corp, y, "11011"):
            raw[y] = None                   # 회사당 DART 4–5건 절약(2011–14) — 2014 는 87곳 중 3곳만 값이 있어 캐시만 쓴다
            continue
        raw[y] = get(y, "11011")
    known = sorted(y for y, v in raw.items() if v)
    adj, splits = {}, []
    if not known:
        return adj, splits, raw
    factor = 1.0
    adj[known[-1]] = raw[known[-1]]
    for i in range(len(known) - 2, -1, -1):
        y, y2 = known[i], known[i + 1]
        r = raw[y2] / raw[y]
        if r >= 1.8 or r <= 0.55:
            factor *= r
            splits.append({"year": y2, "ratio": round(r, 2)})
        adj[y] = raw[y] * factor
    for d in F:
        y = d["year"]
        if y not in adj:
            near = min(known, key=lambda k: (abs(k - y), k))
            adj[y] = adj[near]
    # 마지막 사업보고서 뒤의 분할 — 네이버 수정주가는 이미 새 주식 수 기준이다(엘에스일렉트릭 2026 5:1).
    # 수집된 가장 최근 정기보고서(분기·반기)의 주식 수로 한 번 더 맞춘다
    if latest and latest[0] >= known[-1]:
        now = get(latest[0], latest[1])
        if now:
            r = now / raw[known[-1]]
            if r >= 1.8 or r <= 0.55:
                for y in adj:
                    adj[y] *= r
                splits.insert(0, {"year": latest[0], "ratio": round(r, 2), "after": known[-1]})
            if latest[0] not in adj:
                adj[latest[0]] = now
    return adj, splits, raw


def _land_type(F, i):
    """그해의 린치 유형 — 그해까지의 숫자로만."""
    d = F[i]
    ni = d.get("ni")
    if ni is not None and ni < 0:
        return "적자"
    p1 = F[i - 1].get("ni") if i >= 1 else None
    p2 = F[i - 2].get("ni") if i >= 2 else None
    if ni is not None and ni > 0 and ((p1 is not None and p1 < 0) or (p2 is not None and p2 < 0 and (p1 or 0) > 0)):
        return "회생"
    j = max(0, i - 3)
    r0, r1 = F[j].get("rev"), d.get("rev")
    # 최근 4분기 칸(26.2Q)은 마지막 연간보다 반년 뒤 — 실제 햇수로 연율화한다
    n = (i - j) - ((4 - d["q"]) / 4 if d.get("ttm") else 0)
    g = ((r1 / r0) ** (1 / n) - 1) * 100 if (n >= 2 and r0 and r1 and r0 > 0 and r1 > 0) else None
    # 순환 — 6년 안에 영업이익이 앞선 정점보다 40% 넘게 꺾였거나 흑자 뒤 적자가 났다. 성장만 한 회사는 꺾인 적이 없다
    def swung(k):
        win = [x for x in F[max(0, i - k + 1):i + 1] if x.get("op") is not None]
        sw, peak = False, None
        for x in win:
            v = x["op"]
            if peak is not None and peak[0] > 0 and peak[1] >= 4 and v <= peak[0] * 0.6:
                sw = True
            if x.get("rev_yoy") is not None and x["rev_yoy"] <= -10 and x is not win[0]:
                sw = True
            if peak is None or v > peak[0]:
                peak = (v, x.get("margin") or 0)
        return sw
    # 고성장은 최근 4년에 꺾인 적이 없어야 한다. 순환은 6년 안에 한 번이라도 크게 꺾였으면
    swing = swung(6)
    if g is not None and g >= 15 and not (swung(4) and g < 25):
        return "고성장"
    if swing:
        return "경기순환"
    if g is None:
        return None
    return "대형우량" if g >= 5 else "저성장"


def _land_ttm(c, corp, F):
    """마지막 사업보고서 뒤에 분기 · 반기 보고서가 나왔으면 최근 4분기 합으로 한 칸 더(2026-10-03).
    손익 · 현금흐름은 분기 단독 4개의 합, 재무상태는 그 분기 말 값 — 연간 칸(변곡점.fundamentals)과 같은 줄 이름 규칙으로."""
    try:
        mi = matrix_cached(c, corp, "IS", "q", IS_YEARS)
        mb = matrix_cached(c, corp, "BS", "q", QTR_YEARS)
        mc = matrix_cached(c, corp, "CF", "q", QTR_YEARS)
        pr = _pipe_rows(c, mi, mb, mc, blog_pts=[])
    except Exception:
        return None
    if not pr or not F:
        return None
    lab = next((l for l in reversed(pr["labs"]) if pr["rows"][l].get("rev_ttm") is not None
                and pr["rows"][l].get("ni_ttm") is not None), None)
    if not lab or int(lab[:4]) <= F[-1]["year"]:
        return None
    x, xl = pr["rows"][lab], pr["rows"].get(_qshift(lab, 4)) or {}

    def bs(key=None, rx=None):
        for r in mb.get("rows", []):
            if (key and r["key"] == key) or (rx and rx.match(r["name"])):
                v = _mseries(mb, r).get(lab)
                if v is not None:
                    return v
        return None
    debt, seen = None, set()
    for r in mb.get("rows", []):
        v = _mseries(mb, r).get(lab)
        if v is not None and INF.DEBT_NM.match(r["name"]) and (r["name"], v) not in seen:
            seen.add((r["name"], v))
            debt = (debt or 0) + abs(v)

    have = {p["label"] for p in mc.get("periods", [])}
    q4 = [_qshift(lab, k) for k in range(4)]

    def cf4(tags, rx, skip):
        """현금흐름 4분기 합. 배당 · 자사주처럼 하는 분기에만 값이 있는 줄은, 그 분기 표가 있으면 빈 칸을 0으로 본다."""
        if not all(q_ in have for q_ in q4):
            return None
        tot = None
        for r in mc.get("rows", []):
            tail = r["key"][2:] if r["key"].startswith("t:") else ""
            if (any(tail.startswith(t) for t in tags) or rx.match(r["name"])) and skip not in r["name"]:
                s = _mseries(mc, r)
                vs = [s.get(q_) for q_ in q4]
                if any(v is not None for v in vs):
                    tot = (tot or 0) + abs(sum(v or 0 for v in vs))
        return tot
    rev, op, ni, cfo = x.get("rev_ttm"), x.get("op_ttm"), x.get("ni_ttm"), x.get("cfo_ttm")
    eq = x.get("eq_total") or x.get("equity")
    eq_ly = xl.get("eq_total") or xl.get("equity")
    capex = cf4(INF.CAPEX_TAG, INF.CAPEX_NM, "처분")
    cash, inv, re_ = bs("t:CashAndCashEquivalents", INF.CASH_NM), bs("t:Inventories", INF.INV_NM), bs("t:RetainedEarnings", re.compile(r"^이익잉여금"))
    eav = (eq + eq_ly) / 2 if (eq and eq_ly) else eq
    ic = (eq + (debt or 0) - (cash or 0)) if eq else None
    return {"year": int(lab[:4]), "ttm": "%s.%sQ" % (lab[:4], lab[5]), "q": int(lab[5]),
            "end": "%s%s" % (lab[:4], LAND_Q_END[int(lab[5])]),
            "rev": rev, "op": op, "ni": ni, "eq": eq, "liab": x.get("debt"), "re": re_, "cfo": cfo, "capex": capex,
            # 배당은 분기 현금흐름표에서 지급 줄이 자주 빠진다(효성중공업 2026.1·2분기 빈 칸) — 1년에 한 번이니 마지막 결산 배당을 잇는다
            "div": F[-1].get("div"), "div_year": F[-1]["year"] if F[-1].get("div") else None,
            "buyback": cf4(INF.BUYBACK_TAG, INF.BUYBACK_NM, "처분"),
            "debt": debt, "cash": cash, "rev_yoy": x.get("rev_yoy"),
            "margin": op / rev * 100 if (rev and op is not None and rev > 0) else None,
            "roe": ni / eav * 100 if (ni is not None and eav and eav > 0) else None,
            "roic": op * 0.78 / ic * 100 if (op is not None and ic and ic > 0) else None,
            "fcf": (cfo - (capex or 0)) if cfo is not None else None,
            "capex_int": capex / rev * 100 if (capex is not None and rev and rev > 0) else None,
            "de": debt / eq * 100 if (debt is not None and eq and eq > 0) else None,
            "inv_days": inv / rev * 365 if (inv is not None and rev and rev > 0) else None}


class _FinWatch:
    """FIN 대리 — fetch_statement 가 일시 오류(transient: 한도 · 점검 · 네트워크)를 낸 (연도, 보고서, 구분)을 bad 에 모은다. 나머지는 FIN 그대로.
    변곡점.fundamentals 가 FIN 을 인자로 받으니 전역을 바꾸지 않고 이 빌드의 호출만 본다."""
    def __init__(self, fin):
        self._fin, self.bad = fin, []

    def __getattr__(self, k):
        return getattr(self._fin, k)

    def fetch_statement(self, corp, year, reprt_code, fs_div="CFS", force=False):
        out = self._fin.fetch_statement(corp, year, reprt_code, fs_div, force)
        if out.get("transient"):
            self.bad.append((year, reprt_code, fs_div))
        return out


# 원장 일시 오류 보기(2026-10-11) — matrix_cached 는 재무.statement_matrix 를 거치는데, 그 안은 fetch_statement 를 모듈 이름으로 불러
# _FinWatch 같은 대리를 넘길 수 없다. 그래서 FIN.fetch_statement 를 한 번 감싸, 이 스레드가 _fin_watch() 안이면 transient
# (한도 · 점검 · 네트워크 · 미리 계산 도구의 DART 상한 막힘) 결과를 그 목록에 남긴다. 밖에서 부르면 그대로다(결과도 같다).
# 그런 판을 디스크에 쓰면 sig(최신 접수번호 · 오늘 날짜)가 같아 새 보고서 · 다음 날까지 빈 칸이 굳는다 — matrix · 변곡점 · 풍경은 쓰지 않는다.
_FIN_TL = threading.local()
_FIN_WRAP_LOCK = threading.Lock()


def _fin_watch_install():
    fin = FIN
    if fin is None:
        return
    with _FIN_WRAP_LOCK:
        orig = getattr(fin, "fetch_statement", None)
        if orig is None or getattr(orig, "_fin_watch", False):
            return

        def fetch_statement(*a, **kw):
            out = orig(*a, **kw)
            st = getattr(_FIN_TL, "stack", None)
            if st and isinstance(out, dict) and out.get("transient"):
                for bad in st:
                    bad.append(tuple(a[1:3]))
            return out
        fetch_statement._fin_watch = True
        fetch_statement.__wrapped__ = orig
        try:
            fin.fetch_statement = fetch_statement
        except (AttributeError, TypeError):
            pass


class _fin_watch:
    """with _fin_watch() as bad: … — 그 안에서 이 스레드가 받은 FIN.fetch_statement 일시 오류(연도, 보고서)를 bad 에 모은다. 겹쳐 써도 된다(바깥에도 남는다)."""
    def __enter__(self):
        _fin_watch_install()
        self.bad = []
        st = getattr(_FIN_TL, "stack", None)
        if st is None:
            st = _FIN_TL.stack = []
        st.append(self.bad)
        return self.bad

    def __exit__(self, *exc):
        st = _FIN_TL.stack
        for i in range(len(st) - 1, -1, -1):
            if st[i] is self.bad:           # 빈 목록끼리는 == 가 같다 — 제 것만(is) 뺀다
                del st[i]
                break
        return False


LAND_SHORT = "연간 재무가 4년 치도 안 됩니다."


def _price_fresh(code):
    """주가 캐시가 24시간 안에 새로 받은 것인가 — 빈 주가({})가 네이버 일시 오류인지(캐시가 낡음) 정말 없는지(방금 받은 빈 캐시) 가른다."""
    try:
        return time.time() - os.path.getmtime(os.path.join(FIN.PRICE_DIR, code + ".json")) < 86400
    except (OSError, AttributeError):
        return False


def landscape_build(c, prog=None):
    """풍경 한 판. 일시 오류로 망가진 판이면 "_transient"(이유)를 단다 — 저장하지 않는다(land_build).
    짧은 이력 오류도 연간 원장 일시 오류 때문이면 "_transient" — 부정 캐시로 굳히지 않는다.
    빌드 전체(연간 원장 · 분기 matrix(_land_ttm) · 변곡점)의 원장 일시 오류를 _fin_watch 로 본다."""
    with _fin_watch() as bad:
        d = _landscape_build(c, prog)
    if bad and not d.get("_transient"):
        d["_transient"] = "재무 원장 일시 오류"
    return d


def _landscape_build(c, prog=None):
    code = c["code"]
    corp = corp_code_of(code)
    if not corp or FIN is None or INF is None:
        return {"error": "DART 고유번호나 재무 모듈이 없습니다."}
    this = dt.date.today().year
    fw = _FinWatch(FIN)
    funds = INF.fundamentals(fw, corp, list(range(this - 15, this + 1)))
    F = [d for d in funds if d.get("rev") is not None or d.get("ni") is not None]
    if len(F) < 4:
        return {"error": LAND_SHORT, "_transient": "연간 원장 일시 오류" if fw.bad else None}
    if prog is not None:
        prog["step"] = "주식 수·주가"
    rc_of = {"03": "11013", "06": "11012", "09": "11014", "12": "11011"}
    lrep = max((r for r in c["reports"] if r["stamp"][5:7] in rc_of), key=lambda r: r["stamp"], default=None)
    latest = (int(lrep["stamp"][:4]), rc_of[lrep["stamp"][5:7]]) if lrep else None
    sbad = []
    S_adj, splits, S_raw = _land_shares(F, corp, latest, sbad)
    prices = FIN.fetch_prices(code) or {}
    transient = ("연간 원장 일시 오류" if fw.bad else "주식 수 일시 오류" if sbad
                 else "주가 없음" if not prices and not _price_fresh(code) else None)
    ds = sorted(prices)

    def px_on(ymd):
        return FIN.price_on(prices, ymd)[0] if prices else None

    # ── 연간 원장(밸류라인 한 장)
    rows = []
    for i, d in enumerate(F):
        y = d["year"]
        sa = S_adj.get(y)
        pe = px_on("%d1230" % y)
        yr_px = [prices[k] for k in ds if k[:4] == str(y)]
        eps = d["ni"] / sa if (d.get("ni") is not None and sa) else None
        bps = d["eq"] / sa if (d.get("eq") and sa) else None
        dps = d["div"] / sa if (d.get("div") and sa) else None
        row = {k: d.get(k) for k in ("year", "rev", "op", "ni", "eq", "liab", "margin", "roe", "roic", "fcf", "cfo", "capex",
                                     "div", "buyback", "debt", "cash", "de", "capex_int", "rev_yoy", "inv_days", "re")}
        row.update(eps=eps, bps=bps, dps=dps, shares=sa, px=pe,
                   hi=max(yr_px) if yr_px else None, lo=min(yr_px) if yr_px else None,
                   per=pe / eps if (pe and eps and eps > 0) else None,
                   pbr=pe / bps if (pe and bps and bps > 0) else None,
                   dy=dps / pe * 100 if (dps and pe) else None,
                   payout=d["div"] / d["ni"] * 100 if (d.get("div") and d.get("ni") and d["ni"] > 0) else None,
                   mcap=pe * sa if (pe and sa) else None,
                   type=_land_type(F, i))
        rows.append(row)
    ann = list(rows)            # 연간 칸만 — 15년 합계 · 해마다 비교하는 안목은 이것으로(최근 4분기 칸은 겹치는 기간이 있다)
    if prog is not None:
        prog["step"] = "최근 4분기"
    tt = _land_ttm(c, corp, F)
    if tt:
        y, end = tt["year"], tt["end"]
        sa = S_adj.get(y) or (S_adj[max(S_adj)] if S_adj else None)
        pe = px_on(end)
        st_ = (dt.datetime.strptime(end, "%Y%m%d") - dt.timedelta(days=365)).strftime("%Y%m%d")
        win_px = [prices[k] for k in ds if st_ < k <= end]
        eps = tt["ni"] / sa if (tt.get("ni") is not None and sa) else None
        bps = tt["eq"] / sa if (tt.get("eq") and sa) else None
        dps = tt["div"] / sa if (tt.get("div") and sa) else None
        row = dict(tt)
        row.update(eps=eps, bps=bps, dps=dps, shares=sa, px=pe,
                   hi=max(win_px) if win_px else None, lo=min(win_px) if win_px else None,
                   per=pe / eps if (pe and eps and eps > 0) else None,
                   pbr=pe / bps if (pe and bps and bps > 0) else None,
                   dy=dps / pe * 100 if (dps and pe) else None,
                   payout=tt["div"] / tt["ni"] * 100 if (tt.get("div") and tt.get("ni") and tt["ni"] > 0) else None,
                   mcap=pe * sa if (pe and sa) else None,
                   type=_land_type(F + [tt], len(F)))
        rows.append(row)

    # ── 분기 — 최근 4분기 순이익으로 주당이익, 보고서 접수일 주가로 PER
    if prog is not None:
        prog["step"] = "분기 이익선"
    try:
        dk = druck(code) or {}
    except Exception:
        dk = {}
    P = [p for p in dk.get("points", []) if p.get("year")]
    # 4분기 창 · 1년 전 · 직전 분기는 순번이 아니라 분기 키(n = 연도×4 + 분기 − 1)로 — 빈 분기 점이 끼어도 다른 분기를 집지 않는다
    nkey = lambda p: p["year"] * 4 + p["q"] - 1      # noqa: E731
    Pby = {nkey(p): p for p in P}
    qs = []
    for p in P:
        n = nkey(p)
        win = [Pby.get(m) for m in range(n - 3, n + 1)]
        ni4 = sum(x["당기순이익"] for x in win) if all(x is not None and x.get("당기순이익") is not None for x in win) else None
        op4 = p.get("영업이익_TTM")
        sa = S_adj.get(p["year"]) or S_adj.get(min(S_adj, key=lambda y: abs(y - p["year"]))) if S_adj else None
        eps = ni4 / sa if (ni4 is not None and sa) else None
        qd = "%d%s" % (p["year"], LAND_Q_END[p["q"]])
        dd = p.get("주가일")                   # 보고서 접수일(그날 알 수 있던 값) — 결단 시점에 쓴다
        qs.append({"label": p["label"], "year": p["year"], "q": p["q"], "n": n, "end": qd, "filed": dd,
                   "ni4": ni4, "op4": op4, "eps": eps, "rev4": p.get("매출_TTM"),
                   "inv_days": p.get("재고일수"), "px_end": px_on(qd), "px_filed": prices.get(dd) if dd else None})
    qby = {q["n"]: q for q in qs}
    for q in qs:
        q["per"] = q["px_end"] / q["eps"] if (q["px_end"] and q["eps"] and q["eps"] > 0) else None
        if q["per"] is not None and not (0.5 <= q["per"] <= 300):
            q["per"] = None
    pers = [q["per"] for q in qs if q["per"] is not None]
    if len(pers) < 6:             # 분기가 모자라면 연말 PER 로
        pers = [r["per"] for r in rows if r.get("per") and 0.5 <= r["per"] <= 300]
    band = {"lo": _land_q(pers, .25), "mid": _land_q(pers, .5), "hi": _land_q(pers, .75), "n": len(pers)}
    line = []
    for q in qs:
        if q["eps"] and q["eps"] > 0 and band["mid"]:
            line.append({"d": q["end"], "lo": q["eps"] * band["lo"], "mid": q["eps"] * band["mid"], "hi": q["eps"] * band["hi"]})
        else:
            line.append({"d": q["end"], "loss": q["ni4"] is not None and q["ni4"] < 0})
    # 월말 주가(수정주가)
    monthly = []
    for k in ds:
        if monthly and monthly[-1]["d"][:6] == k[:6]:
            monthly[-1] = {"d": k, "p": prices[k]}
        else:
            monthly.append({"d": k, "p": prices[k]})
    if F:
        start = "%d0101" % F[0]["year"]
        monthly = [m for m in monthly if m["d"] >= start]

    # 주가와 이익선 — 벌어졌다 되돌아온 기록
    gaps = []
    for q, l in zip(qs, line):
        if q["px_end"] and l.get("mid"):
            gaps.append({"d": q["end"], "gap": (q["px_end"] / l["mid"] - 1) * 100})
    import math
    corr = None
    pairs = [(math.log(q["px_end"]), math.log(l["mid"])) for q, l in zip(qs, line) if q["px_end"] and l.get("mid")]
    if len(pairs) >= 8:
        xa = [a for a, _ in pairs]
        xb = [b for _, b in pairs]
        ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
        va = sum((a - ma) ** 2 for a in xa) ** .5
        vb = sum((b - mb) ** 2 for b in xb) ** .5
        corr = sum((a - ma) * (b - mb) for a, b in pairs) / (va * vb) if va and vb else None

    def fwd(d, days):
        """d 에 산 사람이 days 뒤 얻은 수익률(수정주가)."""
        if not d or d not in prices:
            return None
        t = (dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(days=days)).strftime("%Y%m%d")
        if t > ds[-1]:
            return None
        p1 = FIN.price_on(prices, t)[0]
        return (p1 / prices[d] - 1) * 100 if p1 else None

    # ── 결단 — 그 시점까지 알 수 있던 것만으로. 조건이 맞은 분기(접수일)에 샀다면
    if prog is not None:
        prog["step"] = "결단 시점"
    ytype = {r["year"]: r["type"] for r in ann}
    yrow = {r["year"]: r for r in ann}
    moments, last_at = [], {}
    base_fwd = [x for x in (fwd(q["filed"], 365) for q in qs if q.get("filed")) if x is not None]
    for k, q in enumerate(qs):
        d = q.get("filed")
        if not d or d not in prices or not q["eps"]:
            continue
        prior = [x["per"] for x in qs[:k] if x["per"] is not None]
        per_f = prices[d] / q["eps"] if q["eps"] > 0 else None
        pct = _land_pct(prior, per_f) if (per_f and len(prior) >= 8) else None
        past = [yrow[y] for y in yrow if y <= q["year"] - 1]
        roes = [r["roe"] for r in past if r.get("roe") is not None]
        quality = len(roes) >= 3 and sum(1 for v in roes if v >= 12) >= 0.7 * len(roes) and \
            all((r.get("ni") or 0) > 0 for r in past[-3:])
        typ = ytype.get(q["year"] - 1)
        hits = []
        if quality and pct is not None and pct <= 25:
            hits.append(("버핏", "좋은 회사가 싸다", "ROE 12%% 넘은 해가 %d/%d, PER이 그때까지 자기 역사 하위 %.0f%%" % (
                sum(1 for v in roes if v >= 12), len(roes), pct)))
        prev4 = qby.get(q["n"] - 4)
        g = (q["eps"] / prev4["eps"] - 1) * 100 if (prev4 and prev4.get("eps") and prev4["eps"] > 0 and q["eps"] > 0) else None
        if typ == "고성장" and g and g >= 20 and per_f and per_f / g <= 1.0:
            hits.append(("린치", "고성장주가 PEG 1 아래", "주당이익 1년 %+.0f%%, PER %.1f → PEG %.2f" % (g, per_f, per_f / g)))
        if typ in ("경기순환", "적자", "회생"):
            o = [(qby.get(m) or {}).get("op4") for m in range(q["n"] - 3, q["n"] + 1)]
            # 순환주는 이익 바닥에서 PER이 가장 비싸 보인다(린치) — 그래서 PER 대신 5년 평균 이익으로 그은 선의 두 배를
            # 넘었는지로 과열을 본다. 넘었으면 회복이 이미 값에 든 것으로 보고 세지 않는다
            e5 = [yrow[y]["eps"] for y in range(q["year"] - 5, q["year"]) if y in yrow and yrow[y].get("eps") is not None]
            med = _land_q(prior, .5) if len(prior) >= 8 else band["mid"]
            ne = sum(e5) / len(e5) if len(e5) >= 3 else None
            hot = bool(ne and ne > 0 and med and prices[d] >= 2 * ne * med)
            if None not in o and o[0] > o[1] > o[2] and o[3] > o[2] and not hot:
                hits.append(("린치", "순환주 이익 바닥 통과" if o[3] > 0 else "회생 — 적자가 줄기 시작",
                             "4분기 영업이익이 두 분기 줄다가 %s → %s 로 돌아섰다" % (_won_txt(o[2]), _won_txt(o[3]))))
        w2 = [qby.get(q["n"] - 2), qby.get(q["n"] - 1)]
        if q["ni4"] is not None and q["ni4"] > 0 and all(
                x is not None and x["ni4"] is not None and x["ni4"] < 0 for x in w2):
            hits.append(("린치", "회생 — 흑자 전환", "4분기 순이익 %s → %s" % (_won_txt(w2[-1]["ni4"]), _won_txt(q["ni4"]))))
        if typ in ("대형우량", "저성장") and pct is not None and pct <= 15 and not quality:
            hits.append(("린치", "우량주가 이익선 아래", "PER 자기 역사 하위 %.0f%%" % pct))
        for who, what, why in hits:
            if last_at.get(who) is not None and q["n"] - last_at[who] < 4:      # 같은 구루는 1년(네 분기)에 한 번
                continue
            last_at[who] = q["n"]
            moments.append({"who": who, "what": what, "why": why, "d": d, "label": q["label"], "px": prices[d],
                            "r1": fwd(d, 365), "r3": fwd(d, 365 * 3), "pct": round(pct, 1) if pct is not None else None})

    def summ(who):
        m = [x for x in moments if x["who"] == who and x["r1"] is not None]
        if not m:
            return None
        m3 = [x for x in moments if x["who"] == who and x["r3"] is not None]
        return {"n": len([x for x in moments if x["who"] == who]), "n1": len(m),
                "avg1": sum(x["r1"] for x in m) / len(m), "win1": sum(1 for x in m if x["r1"] > 0),
                "n3": len(m3), "avg3": sum(x["r3"] for x in m3) / len(m3) if m3 else None}
    base3 = [x for x in (fwd(q["filed"], 365 * 3) for q in qs if q.get("filed")) if x is not None]
    base = {"avg1": sum(base_fwd) / len(base_fwd), "n": len(base_fwd), "win1": sum(1 for x in base_fwd if x > 0),
            "avg3": sum(base3) / len(base3) if base3 else None, "n3": len(base3)} if base_fwd else None

    # ── 풍경 — 유형이 같은 해들을 한 장(章)으로
    if prog is not None:
        prog["step"] = "장(章)과 말"
    ov = {}
    annual = {}
    for r in c["reports"]:
        if r["label"] == "사업보고서":
            y = int(r["stamp"][:4])
            if y not in annual or r["rcept"] > annual[y]["rcept"]:
                annual[y] = r
    tc = {}
    for y, r in annual.items():
        sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
        if sec:
            try:
                t = corpus_text(c, r, sec["file"])
                ov[y] = INF.overview(t)
                tc[y] = Counter(INF.tokens(t[:150000]))
            except Exception:
                pass
    try:
        inf = inflect(code) or {}
    except Exception:
        inf = {}
    evs = inf.get("events") or []
    chapters = []
    for r in rows:
        t = r["type"]
        if t is None:
            continue
        if chapters and chapters[-1]["type"] == t:
            chapters[-1]["y1"] = r["year"]
        else:
            chapters.append({"type": t, "y0": r["year"], "y1": r["year"]})
    # 한 해짜리 장은 앞 장에 붙인다(첫 장·적자·회생은 그대로)
    merged = []
    for ch in chapters:
        if merged and ch["y0"] == ch["y1"] and ch["type"] not in ("적자", "회생") and merged[-1]["type"] not in ("적자",):
            merged[-1]["y1"] = ch["y1"]
            merged[-1].setdefault("also", []).append(ch["type"])
            continue
        if merged and merged[-1]["type"] == ch["type"]:      # 한 해짜리를 삼킨 뒤 같은 유형이 이어지면 한 장으로
            merged[-1]["y1"] = ch["y1"]
            continue
        merged.append(ch)
    yall = {r["year"]: r for r in rows}       # 장(章)은 최근 4분기 칸까지 — 지금의 유형
    for ch in merged:
        rr = [yall[y] for y in range(ch["y0"], ch["y1"] + 1) if y in yall]
        r0, r1 = rr[0], rr[-1]
        if r1.get("ttm"):
            ch["y1_label"] = r1["ttm"]
        pre = yall.get(ch["y0"] - 1)
        n = ch["y1"] - ch["y0"] + (1 if pre else 0)
        a, b = (pre or r0).get("rev"), r1.get("rev")
        ch["rev_cagr"] = ((b / a) ** (1 / n) - 1) * 100 if (n and a and b and a > 0 and b > 0) else None
        ms = [x["margin"] for x in rr if x.get("margin") is not None]
        ch["margin"] = sum(ms) / len(ms) if ms else None
        rs = [x["roe"] for x in rr if x.get("roe") is not None]
        ch["roe"] = sum(rs) / len(rs) if rs else None
        p0 = (pre or {}).get("px") or px_on("%d0102" % ch["y0"]) or (monthly[0]["p"] if monthly else None)
        p1 = r1.get("px")
        ch["px_ret"] = (p1 / p0 - 1) * 100 if (p0 and p1) else None
        e0, e1 = (pre or r0).get("eps"), r1.get("eps")
        ch["eps_ret"] = (e1 / e0 - 1) * 100 if (e0 and e1 and e0 > 0 and e1 > 0) else None
        # 이 장에 들어온 말 — 장 동안 보고서당 3번 넘게 쓰였고, 앞선 해들엔 거의 없던 낱말
        inn = [tc[y] for y in range(ch["y0"], ch["y1"] + 1) if y in tc]
        bef = [tc[y] for y in tc if y < ch["y0"]]
        words = []
        if inn and bef:
            tot = Counter()
            for x in inn:
                tot.update(x)
            for t, k in tot.most_common(400):
                per_in = k / len(inn)
                per_bef = sum(x.get(t, 0) for x in bef) / len(bef)
                bad = (HANGUL_RE.search(t) and (len(t) < 3 or ASK_VERBISH.search(t) or ASK_GLUE.search(t) or len(t) > 8)) \
                    or LAND_WORD_SKIP.search(t)
                if per_in >= 3 and per_bef <= 0.5 and not GIST_TERM_SKIP.search(t) and not ASK_SKIP_TOK.match(t) and not bad:
                    words.append(t)
                if len(words) >= 6:
                    break
        ch["words"] = words
        said = ov.get(ch["y0"]) or next((ov[y] for y in sorted(ov) if y >= ch["y0"]), "")
        ch["said"] = _short(said, 150) if said else ""
        ch["said_year"] = ch["y0"] if ov.get(ch["y0"]) else next((y for y in sorted(ov) if y >= ch["y0"]), None)
        ke = [e for e in evs if ch["y0"] <= e.get("year", 0) <= ch["y1"] and e.get("lane") != "정체성"]
        ke.sort(key=lambda e: ({"경고": 0, "수익모델": 1, "방향·투자": 2, "재무·주주": 3}.get(e.get("lane"), 4), e.get("year")))
        ch["events"] = [{"year": e["year"], "title": e["title"], "tone": e.get("tone"), "detail": e.get("detail")} for e in ke[:3]]

    # ── 안목 — 이 회사의 15년이 가르치는 규칙
    lessons = []
    # 1. 주가는 이익을 따라갔나
    if corr is not None:
        far = [g for g in gaps if abs(g["gap"]) >= 30]
        lessons.append({"k": "follow", "who": "린치", "title": "주가는 결국 이익을 따라간다" if corr >= 0.6 else "주가와 이익이 따로 놀았다",
                        "text": "로그 주가와 이익선의 상관 %.2f. 분기 %d개 중 이익선에서 30%% 넘게 벌어진 때가 %d개." % (corr, len(gaps), len(far)) +
                        (" 이 회사에선 이익을 읽는 것이 곧 주가를 읽는 것이었다." if corr >= 0.6 else
                         " 이익 말고 다른 것(기대·테마·자산 가치)이 값을 움직였다 — 이익선만 믿으면 안 되는 회사."),
                        "v": round(corr, 2)})
    # 2. 불황 성적표
    worst = None
    for i in range(1, len(ann)):
        a, b = ann[i - 1], ann[i]
        if a.get("op") and b.get("op") is not None and a["op"] > 0:
            ch = (b["op"] / a["op"] - 1) * 100
            if worst is None or ch < worst[0]:
                worst = (ch, b)
    if worst and worst[0] < -20:
        ch, b = worst
        prev_peak = max((r["op"] for r in ann if r["year"] < b["year"] and r.get("op")), default=None)
        back = next((r["year"] for r in ann if r["year"] > b["year"] and prev_peak and (r.get("op") or 0) >= prev_peak), None)
        lessons.append({"k": "worst", "who": "버핏", "title": "가장 나빴던 해에 어떻게 버텼나",
                        "text": "%d년 영업이익 %+.0f%%, 매출 %s, 순이익 %s." % (
                            b["year"], ch, ("%+.0f%%" % b["rev_yoy"]) if b.get("rev_yoy") is not None else "—",
                            "흑자를 지켰다" if (b.get("ni") or 0) > 0 else "적자") +
                        (" 이전 정점을 %d년에 되찾았다(%d년 걸림)." % (back, back - b["year"]) if back else " 아직 이전 정점을 되찾지 못했다.") +
                        (" 불황에도 돈을 번 회사는 버핏의 '경제적 해자' 후보다." if (b.get("ni") or 0) > 0 else " 불황에 적자가 나는 회사는 빚이 치명상이 된다(멍거)."),
                        "v": round(ch)})
    # 3. 자본 배분 — 15년 번 돈이 어디로 갔나
    cfo = sum(r["cfo"] for r in ann if r.get("cfo"))
    if cfo > 0:
        cap = sum(r["capex"] for r in ann if r.get("capex"))
        dv = sum(r["div"] for r in ann if r.get("div"))
        bb = sum(r["buyback"] for r in ann if r.get("buyback"))
        s0 = next((r["shares"] for r in ann if r.get("shares")), None)
        s1 = next((r["shares"] for r in reversed(ann) if r.get("shares")), None)
        ny = ann[-1]["year"] - ann[0]["year"]
        sh_cagr = ((s1 / s0) ** (1 / ny) - 1) * 100 if (s0 and s1 and ny) else None
        lessons.append({"k": "alloc", "who": "버핏", "title": "번 돈이 어디로 갔나",
                        "text": "%d–%d년 영업으로 번 현금 %s 가운데 설비·무형 투자 %.0f%%, 배당 %.0f%%, 자사주 %.0f%%." % (
                            ann[0]["year"], ann[-1]["year"], _won_txt(cfo), cap / cfo * 100, dv / cfo * 100, bb / cfo * 100) +
                        (" 주식 수는 해마다 %+.1f%% (분할 보정)." % sh_cagr if sh_cagr is not None else "") +
                        (" 주주 몫이 계속 희석됐다." if sh_cagr is not None and sh_cagr > 1.5 else
                         " 주식 수가 줄었다 — 남은 주주 몫이 커졌다." if sh_cagr is not None and sh_cagr < -0.5 else ""),
                        "v": {"capex": cap / cfo * 100, "div": dv / cfo * 100, "bb": bb / cfo * 100, "sh": sh_cagr}})
    # 4. 유보이익 1원 테스트
    wr = [r for r in rows if r.get("re") is not None and r.get("mcap")]
    if len(wr) >= 5:
        a, b = wr[0], wr[-1]
        dre, dcap = b["re"] - a["re"], b["mcap"] - a["mcap"]
        if dre > 0:
            ratio = dcap / dre
            lessons.append({"k": "retained", "who": "버핏", "title": "쌓아 둔 이익 1원이 시가총액 몇 원이 됐나",
                            "text": "%d–%d년 이익잉여금 %s 늘 때 시가총액 %s %s → 1원당 %.1f원. " % (
                                a["year"], b["year"], _won_txt(dre), _won_txt(abs(dcap)), "늘었다" if dcap >= 0 else "줄었다", ratio) +
                            ("1원을 넘으면 회사에 이익을 남겨 둔 것이 주주에게 이득이었다." if ratio >= 1 else
                             "1원에 못 미친다 — 이익을 쌓아 두기보다 돌려주는 편이 나았다."),
                            "v": round(ratio, 2)})
    # 5. 사업 정의의 일관성
    oy = sorted(y for y in ov if ov[y])
    ty = sorted(tc)
    if len(ty) >= 3:
        def top(cn, k=300):
            return dict(cn.most_common(k))
        a, b = top(tc[ty[0]]), top(tc[ty[-1]])
        num = sum(a[t] * b.get(t, 0) for t in a)
        cos = num / ((sum(v * v for v in a.values()) ** .5) * (sum(v * v for v in b.values()) ** .5) or 1)
        # 15년 내내 쓰인 말 — 이 회사가 무엇인지
        core = [t for t, _ in tc[ty[-1]].most_common(120)
                if sum(1 for y in ty if tc[y].get(t, 0) >= 2) >= 0.8 * len(ty) and not ASK_SKIP_TOK.match(t) and not ASK_JUNK_TOK.match(t)
                and not GIST_TERM_SKIP.search(t) and not (HANGUL_RE.search(t) and (ASK_VERBISH.search(t) or ASK_GLUE.search(t)))][:10]
        idn = [e for e in evs if e.get("lane") == "정체성"]
        lessons.append({"k": "identity", "who": "버핏", "title": "사업을 설명하는 말이 얼마나 그대로인가",
                        "text": "%d년과 %d년 「사업의 내용」 낱말 분포의 닮음 %.2f (1 = 같음)%s. " % (
                            ty[0], ty[-1], cos, " · 정체성이 꺾인 해 %d번" % len(idn) if idn else "") +
                        ("15년 내내 같은 말로 자기를 설명했다 — 버핏이 좋아하는 '10년 뒤에도 같은 일을 할 회사'." if cos >= 0.6 else
                         "뼈대는 남았지만 설명이 꽤 바뀌었다 — 어느 사업이 커졌는지 장(章)마다 들어온 말을 보라." if cos >= 0.4 else
                         "설명이 크게 바뀌었다 — 지금의 회사는 15년 전과 다른 회사다. 옛 숫자로 지금을 재면 안 된다."),
                        "v": round(cos, 2), "core": core,
                        "then": {"year": oy[0], "text": _short(ov[oy[0]], 170)} if oy else None,
                        "now": {"year": oy[-1], "text": _short(ov[oy[-1]], 170)} if oy else None})
    # 6. ROE 의 꾸준함
    roes = [(r["year"], r["roe"]) for r in ann if r.get("roe") is not None]
    if len(roes) >= 5:
        n15 = sum(1 for _, v in roes if v >= 15)
        lessons.append({"k": "roe", "who": "버핏", "title": "자기자본으로 꾸준히 벌었나",
                        "text": "ROE 15%%를 넘은 해 %d/%d, 가장 낮은 해 %d년 %.1f%%. " % (
                            n15, len(roes), min(roes, key=lambda x: x[1])[0], min(v for _, v in roes)) +
                        ("대부분의 해에 15%를 넘겼다 — 버핏이 찾는 '예측 가능한 수익 기계'에 가깝다." if n15 >= 0.7 * len(roes) else
                         "15%를 넘긴 해가 절반이 안 된다 — 좋은 해만 보고 판단하면 안 되는 회사." if n15 < 0.5 * len(roes) else
                         "좋은 해와 나쁜 해가 섞였다 — 평균보다 나쁜 해의 바닥을 보라."),
                        "v": [round(v, 1) for _, v in roes]})

    # ── 결단 — 지금
    now_d = ds[-1] if ds else None
    now_px = prices.get(now_d) if now_d else None
    lastq = next((q for q in reversed(qs) if q.get("eps") is not None), None)
    eps_now = lastq["eps"] if lastq else None
    per_now = now_px / eps_now if (now_px and eps_now and eps_now > 0) else None
    pct_now = _land_pct(pers, per_now) if per_now else None
    # 지금 유형 = 마지막 장(章)의 유형 — 한 해(또는 최근 4분기)만 다른 유형은 앞 장에 붙인다(삼성전자 26.2Q: 연간 경기순환 · 4분기만 고성장)
    last_type = merged[-1]["type"] if merged else next((r["type"] for r in reversed(rows) if r.get("type")), None)
    y4 = next((q for q in qs if lastq and q["year"] == lastq["year"] - 1 and q["q"] == lastq["q"]), None)
    g_now = (eps_now / y4["eps"] - 1) * 100 if (y4 and y4.get("eps") and y4["eps"] > 0 and eps_now and eps_now > 0) else None
    lr = rows[-1]
    rr5 = [r for r in ann[-5:] if r.get("roe") is not None]
    tr_ = rows[-1] if rows[-1].get("ttm") else None
    idv = next((l["v"] for l in lessons if l["k"] == "identity"), None)
    checks = [
        {"who": "버핏", "q": "이해할 수 있는 사업인가 (15년 설명의 닮음 0.5↑)", "ok": (idv >= 0.5) if idv is not None else None,
         "why": ("사업의 내용 낱말 닮음 %.2f" % idv) if idv is not None else "자료 없음"},
        {"who": "버핏", "q": "꾸준히 버는가 (최근 5년 ROE 15%↑)", "ok": len(rr5) >= 3 and sum(1 for r in rr5 if r["roe"] >= 15) >= 4,
         "why": "최근 5년 ROE %s" % " · ".join("%.0f" % r["roe"] for r in rr5) +
                (" · 최근 4분기(%s) %.0f" % (tr_["ttm"], tr_["roe"]) if tr_ and tr_.get("roe") is not None else "")},
        {"who": "버핏", "q": "빚이 가벼운가 (차입/자본 50%↓)", "ok": (lr["de"] <= 50) if lr.get("de") is not None else
         ((lr.get("liab") or 0) <= (lr.get("eq") or 0) if lr.get("eq") else None),
         "why": ("차입금/자본 %.0f%%" % lr["de"]) if lr.get("de") is not None else "차입금 줄 없음 — 부채/자본으로 봄"},
        {"who": "버핏", "q": "이익이 현금으로 들어오는가 (FCF 흑자 해 ≥ 절반)",
         "ok": sum(1 for r in ann if (r.get("fcf") or 0) > 0) >= 0.5 * max(1, sum(1 for r in ann if r.get("fcf") is not None)),
         "why": "FCF 흑자 %d/%d년" % (sum(1 for r in ann if (r.get("fcf") or 0) > 0), sum(1 for r in ann if r.get("fcf") is not None)) +
                (" · 최근 4분기 %s" % _won_txt(tr_["fcf"]) if tr_ and tr_.get("fcf") is not None else "")},
        {"who": "버핏", "q": "값이 합리적인가 (PER 자기 역사 하위 절반)", "ok": pct_now is not None and pct_now <= 50,
         "why": "지금 PER %s, 자기 역사 %s" % ("%.1f" % per_now if per_now else "—", "하위 %.0f%%" % pct_now if pct_now is not None else "—")},
    ]
    biz_ok = sum(1 for x in checks[:4] if x["ok"])
    biz_known = sum(1 for x in checks[:4] if x["ok"] is not None)
    good_biz = biz_ok >= 3 or (biz_known == 3 and biz_ok == 3)
    zone = None if pct_now is None else ("싸다" if pct_now <= 25 else "비싸다" if pct_now >= 75 else "보통")
    if not good_biz and last_type in ("고성장", "회생"):
        good_biz_note = "버핏의 잣대로는 모자라지만 린치의 %s 유형" % last_type
    else:
        good_biz_note = None
    quad = ("결단" if good_biz and zone == "싸다" else "기다림" if good_biz else
            "함정 주의" if zone == "싸다" else "피함")
    e5 = [r["eps"] for r in ann[-5:] if r.get("eps") is not None]
    norm_eps = sum(e5) / len(e5) if (last_type == "경기순환" and len(e5) >= 3) else None
    base_eps = norm_eps if (norm_eps and norm_eps > 0) else eps_now
    wait_px = base_eps * band["lo"] if (base_eps and base_eps > 0 and band["lo"]) else None
    # 버핏 — 이해할 수 있고 꾸준한 사업이 아니면 값을 보기 전에 '너무 어려움' 바구니로
    if checks[0]["ok"] is False and biz_ok < 3:
        bv = ("너무 어려움", "사업이 15년 사이 다른 회사가 됐고 수익도 들쭉날쭉하다 — 버핏은 이런 회사를 '너무 어려움' 바구니에 넣고 넘어간다.")
    elif good_biz and zone == "싸다":
        bv = ("결단", "좋은 사업이 자기 역사 하위 25% 값에 있다 — 버핏이 기다리는 순간.")
    elif good_biz:
        bv = ("기다림", "좋은 사업이지만 값이 싸지 않다. 기다릴 값을 정해 두고 기다린다.")
    else:
        bv = ("지나침", "사업 점검 %d/4 — 싸 보여도 버핏의 잣대로는 좋은 사업이 아니다." % biz_ok)
    # 린치 — 유형이 사고파는 규칙을 정한다
    eps_hist = [q["eps"] for q in qs if q.get("eps") is not None]
    eps_peak = bool(eps_now and eps_hist and eps_now >= max(eps_hist) * 0.95 and len(eps_hist) >= 8)
    lq4 = next((q for q in reversed(qs) if q.get("op4") is not None), None)     # 끝에 빈 분기 점(fy 등)이 붙어도 마지막 실적 분기에서 본다
    o4 = [(qby.get(m) or {}).get("op4") for m in range(lq4["n"] - 3, lq4["n"] + 1)] if lq4 else []
    turning = len(o4) == 4 and None not in o4 and o4[0] > o4[1] > o4[2] and o4[3] > o4[2]
    peg = per_now / g_now if (per_now and g_now and g_now > 0) else None
    if last_type == "고성장":
        if peg is not None and peg <= 1:
            lv = ("결단", "성장률보다 싼 PER(PEG %.2f)." % peg)
        else:
            lv = ("비쌈", "PER이 성장률을 넘는다(PEG %s) — 성장이 이어져야만 정당화된다." % ("%.2f" % peg if peg else "—"))
    elif last_type == "경기순환":
        if eps_peak:
            lv = ("정점 경계", "주당이익이 15년 최고 근처에서 PER이 낮아 보인다 — 순환주는 PER이 가장 쌀 때가 파는 때다.")
        elif turning and norm_eps and norm_eps > 0 and band["mid"] and now_px and now_px >= 2 * norm_eps * band["mid"]:
            lv = ("관찰", "이익은 바닥을 지나 돌아섰지만 주가가 5년 평균 이익으로 그은 이익선의 %.1f배 — 회복이 이미 값에 들어 있다." % (
                now_px / (norm_eps * band["mid"])))
        elif turning:
            lv = ("결단", "이익이 바닥을 지나 돌아섰다 — 순환주를 사는 때. PER %s(자기 역사 %s)." % (
                "%.1f" % per_now if per_now else "—", "상위 %.0f%%" % (100 - pct_now) if pct_now is not None else "—"))
        else:
            lv = ("관찰", "이익의 방향을 본다 — 재고가 줄고 이익이 바닥을 지날 때를 기다린다.")
    elif last_type in ("대형우량", "저성장"):
        gapn = (now_px / (eps_now * band["mid"]) - 1) * 100 if (now_px and eps_now and eps_now > 0 and band["mid"]) else None
        if gapn is not None and gapn <= -30:
            lv = ("결단", "이익선보다 %.0f%% 아래 — 우량주를 싸게 살 때." % -gapn)
        else:
            lv = ("기다림", "이익선 대비 %s — 30%% 넘게 싸질 때를 기다린다." % ("%+.0f%%" % gapn if gapn is not None else "—"))
    elif last_type == "회생":
        lv = ("결단" if (lr.get("de") or 0) <= 100 else "관찰",
              "흑자로 돌아섰다. 차입금/자본 %s — 빚을 버틸 수 있으면 린치는 여기서 산다." % ("%.0f%%" % lr["de"] if lr.get("de") is not None else "—"))
    else:
        lv = ("관찰", "적자 중 — 흑자 전환과 빚 감당 능력을 먼저 확인한다.")
    lynch_px = eps_now * g_now if (eps_now and eps_now > 0 and g_now and g_now > 0 and last_type == "고성장") else None
    decide = {"date": now_d, "px": now_px, "eps": eps_now, "per": per_now, "pct": pct_now, "zone": zone,
              "type": last_type, "g": g_now, "peg": peg if last_type in ("고성장", "대형우량") else None,
              "checks": checks, "biz_ok": biz_ok, "good_biz": good_biz, "note": good_biz_note, "quad": quad,
              "buffett": {"v": bv[0], "why": bv[1]}, "lynch": {"v": lv[0], "why": lv[1]}, "eps_peak": eps_peak, "turning": turning,
              "wait_px": wait_px, "lynch_px": lynch_px, "norm_eps": norm_eps,
              "line_now": eps_now * band["mid"] if (eps_now and eps_now > 0 and band["mid"]) else None,
              "line_px": base_eps * band["mid"] if (base_eps and base_eps > 0 and band["mid"]) else None,
              "playbook": LAND_TYPES.get(last_type, ("", "", ""))[2] if last_type else "",
              "story": _short(ov[oy[-1]], 200) if oy else ""}
    if prog is not None:
        prog["step"] = "마무리"
    out = {"v": LAND_V, "code": code, "name": c["name"], "rows": rows, "quarters": qs, "line": line, "band": band,
           "monthly": monthly, "splits": splits, "corr": corr, "gaps": gaps, "moments": moments,
           "stats": {"버핏": summ("버핏"), "린치": summ("린치"), "base": base}, "chapters": merged,
           "lessons": lessons, "decide": decide, "types": {k: list(v) for k, v in LAND_TYPES.items()},
           "price_date": now_d}
    if transient:
        out["_transient"] = transient
    return out


LANDING = {}
LAND_LOCK = threading.Lock()


def _land_path(code):
    return os.path.join(CACHE_DIR, "landscape", code + ".json")


def _land_sig(c):
    return "%s:%d:%s:%d" % (c["reports"][-1]["rcept"] if c["reports"] else "", len(c["reports"]),
                            dt.date.today().isoformat(), LAND_V)


def _land_nsig(c):
    """날짜를 뺀 sig — 짧은 이력 오류(부정 캐시)는 새 보고서가 올 때까지 그대로다."""
    return "%s:%d:%d" % (c["reports"][-1]["rcept"] if c["reports"] else "", len(c["reports"]), LAND_V)


# 풍경 캐시 정책(2026-10-11) — 지난 판을 먼저 보이고 뒤에서 새로(stale-while-revalidate)
#   · 캐시가 있고 LAND_V 가 같으면 날짜 · 새 보고서로 sig 가 달라도 그 판을 바로 돌려준다("stale": true, "stale_date") — 뒤에서 _run_land
#   · 짧은 이력('연간 재무가 4년 치도 안 됩니다')은 부정 캐시 {"v", "error", "nsig"} — nsig 가 같으면 바로 오류(매번 3초씩 다시 세지 않게)
#   · 일시 오류(가격 빔 · 주식 수 · 연간 원장 한도/점검)로 망가진 판은 저장하지 않는다 — 지난 판이 있으면 그것을, 없으면 그 판을 잠깐 메모리로만
LAND_ERR_HOLD = 30          # 초 — 오류를 그대로 돌려주는 창(오류 난 시각부터)
LAND_RETRY = 600            # 초 — 지난 판 · 메모리 판이 있을 때 새로 그리기에 실패하면 이만큼 뒤에 다시


def _land_read(code):
    try:
        with open(_land_path(code), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _land_v(d):
    """캐시의 LAND_V — 본문 v, 없으면 sig 끝자리."""
    v = d.get("v")
    if v is None:
        try:
            v = int(str(d.get("sig") or "").rsplit(":", 1)[-1])
        except ValueError:
            v = None
    return v


def land_build(c, prog=None, transient=None):
    """풍경 한 판을 만들고 저장할 만하면 저장한다(_run_land · 도구/전종목_미리계산.py 가 같이 쓴다).
    transient() → 이유|None: 부른 쪽이 따로 본 일시 오류(도구의 DART 셈 — 한도 · 점검 · 상한).
    돌려줌 (d, how) — built(저장) · short(짧은 이력, 부정 캐시 저장) · transient(일시 오류 — 안 씀, d["transient"] = 이유) · error(안 씀)."""
    d = landscape_build(c, prog)
    tr = d.pop("_transient", None) or (transient() if transient else None)
    if d.get("error"):
        if d["error"] == LAND_SHORT and not tr:
            _atomic_json(_land_path(c["code"]), {"v": LAND_V, "error": LAND_SHORT, "nsig": _land_nsig(c), "code": c["code"],
                                                 "at": dt.datetime.now().isoformat(timespec="seconds")})
            return d, "short"
        if tr:
            d["transient"] = tr
        return d, "error"
    if tr:
        d["transient"] = tr
        return d, "transient"
    d["sig"] = _land_sig(c)
    _atomic_json(_land_path(c["code"]), d)
    return d, "built"


def _run_land(code):
    st = LANDING[code]
    try:
        c = company_by_code(code)
        d, how = land_build(c, st)
        if how == "transient":
            st.update(error="새로 그리지 못했습니다(%s) — 잠시 뒤 다시" % d["transient"], soft=d, err_at=time.time())
            return
        if how != "built":           # short 는 부정 캐시를 썼다 — 못 썼을 때를 위해 오류 창도 남긴다
            st.update(error=d["error"], err_at=time.time())
            return
    except Exception as e:
        import traceback
        traceback.print_exc()
        st.update(error=_no_secret("%s: %s" % (type(e).__name__, e)), err_at=time.time())
        return
    with LAND_LOCK:
        LANDING.pop(code, None)


def _land_stale(d, err=None):
    """지난 판 + 표시 — stale_date = 그 판을 그린 날(sig 의 날짜). err = 새로 그리기 실패(그 뒤 LAND_RETRY 초 동안 다시 안 그린다)."""
    parts = str(d.get("sig") or "").split(":")
    out = dict(d, stale=True, stale_date=parts[2] if len(parts) == 4 else None, refreshing=err is None)
    if err:
        out["stale_error"] = err
    return out


def landscape_view(code, stale_ok=True):
    """stale_ok=False 면 지난 판을 주지 않고 지금 판이 될 때까지 pending(⑥ 싸다 게이트 — 셋씩 기다리며 돈다)."""
    c = company_by_code(code)
    if not c:
        return None
    d = _land_read(code)
    if d is not None:
        if d.get("error"):                  # 부정 캐시
            if d.get("v") == LAND_V and d.get("nsig") == _land_nsig(c):
                return {"error": d["error"]}
            d = None
        elif d.get("sig") == _land_sig(c):
            return d
        elif not stale_ok or _land_v(d) != LAND_V:
            d = None
    with LAND_LOCK:
        st = LANDING.get(code)
        if st and st.get("error"):
            age = time.time() - st.get("err_at", 0)
            if d is not None:
                if age < LAND_RETRY:
                    return _land_stale(d, st["error"])
            elif st.get("soft") is not None:
                if age < LAND_RETRY:
                    return dict(st["soft"], transient=st["error"])
            elif age < LAND_ERR_HOLD:
                return {"error": st["error"]}
            st = None
        if st is None:
            st = LANDING[code] = {"step": "연간 재무", "at": time.time()}
            try:
                threading.Thread(target=_run_land, args=(code,), daemon=True).start()
            except Exception as e:          # 32비트 뷰어 "can't start new thread" — 오류 없는 칸이 남으면 돌지 않는 빌드를 재시작까지 기다린다
                st.update(error="새로 그리지 못했습니다(%s) — 잠시 뒤 다시" % _no_secret("%s: %s" % (type(e).__name__, e)),
                          err_at=time.time())       # 오류 창(지난 판 LAND_RETRY · 없으면 LAND_ERR_HOLD) 뒤 다음 요청이 다시 띄운다
                return _land_stale(d, st["error"]) if d is not None else {"error": st["error"]}
    if d is not None:
        return _land_stale(d)
    return {"pending": True, "step": st.get("step")}


# ---------------------------------------------------------------- 말의 궤적: 키워드로 회사의 궤적을 쫓는다
# 「사업의 내용」에서 회사가 어떤 말에 지면을 쓰는지(1만 낱말당 몇 번)를 보고서마다 잰다. 말은 숫자보다 먼저 움직인다.
#   떠오른 말 — 2년 전보다 지면이 크게 늘었다: 회사가 돈을 거는 곳
#   주력 말   — 15년 내내 크게 쓰는 말: 정체성
#   저문 말   — 한때 크게 쓰다 사라졌다: 접은 사업·끝난 이야기
#   세대 교체 — 같은 약어의 세대(DDR3→DDR4→DDR5): 기술 사이클의 자리
#   단계 사다리 — 그 말 곁의 낱말로 개발→샘플·인증→양산·출시→확대, 그리고 둔화를 짚는다
# 어느 회사나 쓰는 말(수요·투자·글로벌)은 전 종목 최근 사업보고서의 낱말 빈도(DF)로 누른다.
VOC_V = 12
VOC_SKIP = re.compile(r"위험|회피|공정가치|매매목적|소유형태|변수|이사회|지분|특허법|누적|필수|값임|쉽고|팀$|파생|금리|이자율|환율|"
                      r"회계|손익|채권|채무|평가|주식|소송|기준서|재무|감사|공시|작성|기재|해당|현황|합계|단위|백만|천원|원화|보고|기간|"
                      r"전기|당기|옵션|행사|권리|대상회사|주주|계약|약정|의결|배당|자기주식|적$|^[가-힣][으음]$|"
                      r"개발|연구|양산|출시|상용화|확대|증가|감소|성장|둔화|인수가|복리|총수|종결|거래일|매수인|매도인|양수인|양도인|"
                      r"수주총액|기납품|납품액|정정|역대|즐길|종료일|통지|용$|[억조천만]대$|"
                      r"^(?:USA|US|EU|UK|KRW|USD|EUR|JPY|CNY|IFRS|K-IFRS|ESG|CEO|CFO|IR)$")
VOC_STAGES = [   # (이름, 정규식) — 사다리 순서
    ("개발", re.compile(r"개발|연구|설계|검증|기술\s*확보")),
    ("샘플·인증", re.compile(r"샘플|시제품|인증|퀄|평가\s*(?:중|진행)|테스트|승인")),
    ("양산·출시", re.compile(r"양산|출시|상용화|공급\s*(?:개시|시작)|판매\s*(?:개시|시작)|첫\s*(?:수주|납품|출하)|출하|수주")),
    ("확대", re.compile(r"확대|증설|본격|점유율|확산|증가|성장")),
]
VOC_DOWN = re.compile(r"둔화|감소|하락|축소|경쟁\s*심화|재고\s*조정|단종|철수|중단|종료")
VDF = {"state": None, "data": None, "done": 0, "total": 0}
VDF_LOCK = threading.Lock()


def _vdf_path():
    return os.path.join(CACHE_DIR, "vocab_df.json")


def _run_vdf():
    try:
        comps = list(INDEX["companies"])
        VDF["total"] = len(comps)
        df, n = Counter(), 0
        for i, c in enumerate(comps):
            VDF["done"] = i
            ann = [r for r in c["reports"] if r["label"] == "사업보고서"]
            if not ann:
                continue
            r = max(ann, key=lambda r: r["stamp"])
            sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
            if not sec:
                continue
            try:
                t = read_section(c, r, sec["file"])
            except Exception:
                continue
            df.update(set(INF.tokens(t[:200000])))
            n += 1
        d = {"n": n, "df": {k: v for k, v in df.items() if v >= 2}, "built": time.time()}
        with open(_vdf_path(), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        VDF.update(state="ready", data=d)
    except Exception as e:
        VDF.update(state="error", error=str(e))


def vocab_df():
    """전 종목 최근 사업보고서 「사업의 내용」의 낱말별 회사 수. 30일에 한 번 다시 만든다. 없으면 뒤에서 만들고 None."""
    if VDF["data"] is not None:
        return VDF["data"]
    p = _vdf_path()
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 30 * 86400:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                VDF["data"] = json.load(fh)
            VDF["state"] = "ready"
            return VDF["data"]
        except Exception:
            pass
    with VDF_LOCK:
        if VDF["state"] is None and INF is not None:
            VDF["state"] = "building"
            threading.Thread(target=_run_vdf, daemon=True).start()
    return None


def _voc_ok(t, dfr):
    if ASK_SKIP_TOK.match(t) or ASK_JUNK_TOK.match(t) or GIST_TERM_SKIP.search(t) or VOC_SKIP.search(t):
        return False
    if HANGUL_RE.search(t) and (len(t) < 2 or ASK_VERBISH.search(t) or ASK_GLUE.search(t) or len(t) > 8):
        return False
    return dfr is None or dfr < 0.8


def _voc_ctx(text, term, limit=40):
    """말이 든 문장들 — 단계 낱말은 이 문장 안에서만 찾는다(앞뒤 글자 창은 남의 문장까지 끌어온다)."""
    out, seen, i = [], set(), 0
    rx = term if hasattr(term, "finditer") else None
    spans = []
    if rx is not None:
        for m in rx.finditer(text):
            spans.append(m.start())
            if len(spans) >= limit:
                break
    else:
        while len(spans) < limit:
            i = text.find(term, i)
            if i < 0:
                break
            spans.append(i)
            i += len(term)
    for pos in spans:
        a = text.rfind("\n", 0, pos) + 1
        b = text.find("\n", pos)
        line = text[a:b if b >= 0 else len(text)]
        off = pos - a
        acc = 0
        for sent in SENT_SPLIT.split(line):
            sent = sent or ""
            k = line.find(sent, acc)
            if k < 0:
                continue
            if k <= off < k + len(sent) + 2:
                key = (a + k)
                if key not in seen:
                    seen.add(key)
                    out.append(sent.strip()[:400])
                break
            acc = k + len(sent)
    return out


def _voc_snip(ctx, term):
    """보여 줄 한 토막 — 문장 경계에서 자르고, 말이 든 문장을 고른다."""
    for w in ctx:
        for s in SENT_SPLIT.split(w):
            s = (s or "").strip()
            key = term if isinstance(term, str) else None
            if (key and key in s or not key and term.search(s)) and len(s) >= 25 and len(HANGUL_RE.findall(s)) >= 8:
                return _short(s, 130)
    return _short(ctx[0], 130) if ctx else ""


VOC_DATE = re.compile(r"(?<![\d.])((?:19|20)\d{2})\s*(?:[.\-/]|년)\s*(\d{1,2})(?!\d)(?!\s*(?:분기|반기|사분기|Q|차))\s*(?:[.\-/]|월)?(?:\s*(\d{1,2})\s*(?:일|\.(?!\d)))?|['’](\d{2})\s*\.\s*(\d{1,2})(?!\d)")
VOC_RESULT = re.compile(r"(?:누계|분기|반기|연간|당기|전기)?\s*매출(?:액)?\s*(?:은|이|는)\s|영업\s*(?:이익|손실)\s*(?:은|이|는)\s|실적\s*(?:은|이|는)\s")
VOC_SNAP = re.compile(r"기준일?|현재|작성|공시서류|보고기간|사업연도말|분기말|반기말|기말")
VOC_PLAN = re.compile(r"예정|계획|목표|추진\s*중|착공\s*예정|완공\s*예정")
VOC_AMT = re.compile(r"\d[\d,.]*\s*조\s*\d[\d,.]*\s*억\s*원|(?:USD|US\$|\$)\s*[\d,.]+\s*(?:억|백만|천만|million|billion)?|[\d,.]+\s*(?:조|억|백만|천만|천)?\s*(?:원|달러|불|유로)|[\d,.]+\s*(?:MWh|GWh|MW|GW|kV|톤|척)")


def _voc_dates(s):
    this = dt.date.today().year
    out = []
    for m in VOC_DATE.finditer(s):
        if m.group(1):
            y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None
        else:
            y, mo, dd = 2000 + int(m.group(4)), int(m.group(5)), None
        if not (2000 <= y <= this + 3 and 1 <= mo <= 12) or (dd is not None and not 1 <= dd <= 31):
            continue
        out.append((m.start(), m.end(), y, mo, dd))
    return out


VOC_BULLET_DATE = re.compile(r"(?:^|[-–·ㆍ•▶■□○●※]\s*)(?:19|20)\d{2}\s*(?:[.\-/]|년)")
VOC_SENT_END = re.compile(r"(?<=[다음함됨임])\.\s+")
VOC_NEAR_SNAP = re.compile(r"기준|현재|말\s*현재|까지의|작성")


def _voc_amt(s):
    """금액 한 개 — 원 단위 긴 숫자(57,824,000,000원)는 억·조로."""
    m = VOC_AMT.search(s)
    if not m:
        return None
    t = m.group(0).strip()
    mm = re.fullmatch(r"([\d,]+)\s*원", t)
    if mm:
        v = int(mm.group(1).replace(",", "") or 0)
        if v >= 1e12:
            return "%.1f조원" % (v / 1e12)
        if v >= 1e8:
            return "{:,}억원".format(round(v / 1e8))
    return t


def _voc_events(text, term, limit=12):
    """그 말이 든 줄에서 날짜 붙은 사건을 뽑는다.
    연혁 목록('- 2024. 5. KOC전기 인수- 2024. 11. 티라유텍 지분 인수- …')은 날짜마다 끊고(날짜 뒤가 사건),
    문장 속 날짜는 그 문장 전체를 사건으로 본다. 기간(2025.06.20 ~ 2026.11.30)은 하나로,
    '2025.12.31 현재'·'기준일' 같은 시점 표시는 사건이 아니다."""
    lines, seen = [], set()
    if hasattr(term, "finditer"):
        spans = [m.start() for m in term.finditer(text)][:limit * 3]
        has = lambda x: bool(term.search(x))
    else:
        spans, i = [], 0
        while len(spans) < limit * 3:
            i = text.find(term, i)
            if i < 0:
                break
            spans.append(i)
            i += len(term)
        has = lambda x: term in x
    for pos in spans:
        a = text.rfind("\n", 0, pos) + 1
        if a in seen:
            continue
        seen.add(a)
        b = text.find("\n", pos)
        lines.append(text[a:b if b >= 0 else len(text)])
        if len(lines) >= limit:
            break
    today = dt.date.today()
    ev = []
    for line in lines:
        if not _voc_dates(line):
            continue
        listy = len(VOC_BULLET_DATE.findall(line)) >= 2
        units = [line] if listy else [u for u in VOC_SENT_END.split(line) if u and u.strip()]
        for u in units:
            dd = _voc_dates(u)
            if not dd:
                continue
            merged, k = [], 0
            while k < len(dd):
                d = dd[k]
                if k + 1 < len(dd) and re.fullmatch(r"\s*[~\-–]\s*", u[d[1]:dd[k + 1][0]]):
                    merged.append((d, dd[k + 1]))
                    k += 2
                else:
                    merged.append((d, None))
                    k += 1
            segs = []
            if listy or len(merged) >= 2:
                for j, (d, until) in enumerate(merged):
                    st = (until or d)[1]
                    en = merged[j + 1][0][0] if j + 1 < len(merged) else len(u)
                    pre = u[:d[0]] if (j == 0 and not listy) else ""
                    segs.append((d, until, pre + " " + u[st:en]))
            else:
                d, until = merged[0]
                segs.append((d, until, u[:d[0]] + " " + u[(until or d)[1]:]))
            for d, until, body in segs:
                near = u[max(0, d[0] - 8):d[0]] + " " + u[(until or d)[1]:(until or d)[1] + 6]
                if VOC_NEAR_SNAP.search(near):
                    continue
                body = re.sub(r"\s+", " ", body)
                body = re.sub(r"^[\s\-–—·ㆍ•:)\].,]+|[\s\-–—·ㆍ•(\[,]+$", "", body).strip()
                if len(body) < 6 or len(HANGUL_RE.findall(body)) < 3 or VOC_RESULT.search(body):
                    continue
                fut = (d[2], d[3]) > (today.year, today.month)
                ev.append({"y": d[2], "m": d[3], "d": d[4], "text": _short(body, 90), "term": has(body),
                           "until": "%d.%02d" % (until[2], until[3]) if until else None,
                           "plan": fut or bool(VOC_PLAN.search(body[-24:])), "amt": _voc_amt(body)})
    return ev


def _voc_track(reps, texts, ns, term, first_hint=None):
    """한 말의 보고서별 지면(1만 낱말당), 단계, 첫·본격화 토막."""
    n = len(reps)
    if isinstance(term, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9&\+\-]*", term):
        # 약어는 낱말 경계로 — 'SI' 가 'LSI'·'ASIC' 안에서 세지지 않게
        term = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])")
    cnt, stages, snips, evmap = [0] * n, [None] * n, {}, {}
    for i in range(n):
        t = texts[i]
        if not t:
            continue
        if hasattr(term, "finditer"):
            cnt[i] = sum(1 for _ in term.finditer(t))
        else:
            cnt[i] = t.count(term)
        if not cnt[i]:
            continue
        ctx = _voc_ctx(t, term)
        st = [k for k, (nm, rx) in enumerate(VOC_STAGES) if any(rx.search(w) for w in ctx)]
        dn = sum(1 for w in ctx if VOC_DOWN.search(w))
        down = bool(ctx) and dn >= 2 and dn / len(ctx) >= 0.34        # 문장 셋 중 하나 넘게 둔화·감소를 말할 때만
        stages[i] = {"hi": max(st) if st else None, "down": down, "all": st}
        snips[i] = ctx
        # 사건 — 같은 사건은 여러 보고서에 되풀이 실린다. 처음 실린 보고서만 적는다
        for e in _voc_events(t, term):
            g = _ask_grams(SKEL_RE.sub("", re.sub(r"^(?:당사|회사|연결실체)(?:는|가|의)\s*", "", e["text"])))
            same = None
            for k, old in evmap.items():
                if k[0] != (e["y"], e["m"]):
                    continue
                if e["amt"] and e["amt"] == old["amt"]:      # 같은 달 같은 금액 = 같은 사건
                    same = k
                    break
                if old["_g"] and g:
                    inter = len(g & old["_g"])
                    if inter / (len(g) + len(old["_g"]) - inter) >= 0.45 or inter / min(len(g), len(old["_g"])) >= 0.7:
                        same = k
                        break
            if same:
                o = evmap[same]
                o["n"] += 1
                if e["term"] and not o["term"]:
                    o.update(term=True, text=e["text"], _g=g)
                elif len(e["text"]) > len(o["text"]) + 8 and e["term"] == o["term"]:   # 잘려 실린 판보다 긴 판을
                    o.update(text=e["text"], _g=g)
                continue
            evmap[((e["y"], e["m"]), len(evmap))] = dict(e, rep=i, n=1, _g=g)
    share = [cnt[i] / ns[i] * 1e4 if ns[i] else 0 for i in range(n)]
    roll = [sum(share[max(0, i - 3):i + 1]) / len(share[max(0, i - 3):i + 1]) for i in range(n)]
    first = next((i for i in range(n) if cnt[i] >= 1), None)
    mx = max(roll) if roll else 0
    take = None
    if first is not None and mx > 0:
        # 본격화 = 보고서 한 건의 값이 자기 정점(4건 평균 기준)의 30%에 닿고, 다음 보고서에서도 그 근처를 지킨 첫 보고서.
        # 4건 평균으로 재면 한 번에 크게 쓴 말(사업부 이름·인수한 회사)도 한두 칸 늦게 찍혀 '처음'과 '본격화'가 어긋난다
        # 본격화 = 이 말의 지면이 가장 크게 한 단계 뛴 보고서 — 직전 2건 평균 대비 그 보고서와 다음 보고서 평균이 가장 크게 오른 곳.
        # 사람이 선을 보고 '여기서 커졌다'고 읽는 자리다. 그 뜀이 자기 최고치의 30%도 안 되면 본격화가 없다고 본다
        pk_raw = max(share)
        best = None
        for i in range(first, n):
            aft = share[i:i + 2]
            bef = share[max(0, i - 2):i]
            shift = sum(aft) / len(aft) - (sum(bef) / len(bef) if bef else 0)
            if best is None or shift > best[0] + 1e-9:
                best = (shift, i)
        take = best[1] if best and best[0] >= max(1.0, 0.3 * pk_raw) else None
    base = min(4, max(1, n // 6))
    if take is not None and take < base:      # 처음부터 크게 쓰던 말 — 본격화 시점이 없다
        take = None
    ladder = {}
    for i in range(n):
        s = stages[i]
        if not s:
            continue
        for k in s["all"]:
            ladder.setdefault(VOC_STAGES[k][0], i)
    # 사다리는 뒤늦게 올라선 단만 — 처음 나온 보고서에서 이미 있던 단은 '처음부터'
    ladder = {k: v for k, v in ladder.items() if first is None or v > first or first >= base}
    last2 = [stages[i] for i in range(max(0, n - 2), n) if stages[i]]
    now = None
    if last2:
        his = [s["hi"] for s in last2 if s["hi"] is not None]
        hi = max(his) if his else None
        if any(s["down"] for s in last2) and (hi is None or hi < 3):
            now = "둔화"
        elif hi is not None:
            now = VOC_STAGES[hi][0]
    downs = [i for i in range(n) if stages[i] and stages[i]["down"]]
    last = next((i for i in range(n - 1, -1, -1) if cnt[i] >= 1), None)
    evs = sorted(({k: v for k, v in e.items() if k != "_g"} for e in evmap.values()), key=lambda e: (e["y"], e["m"], e["d"] or 0))
    # 그 말이 든 사건을 먼저, 같은 문단에 함께 적힌 사건은 뒤로 — 합쳐 14개까지
    keep = [e for e in evs if e["term"]][:10]
    keep += [e for e in evs if not e["term"]][:max(0, 14 - len(keep))]
    keep.sort(key=lambda e: (e["y"], e["m"], e["d"] or 0))
    return {"events": keep, "cnt": cnt, "share": [round(x, 2) for x in share], "roll": [round(x, 2) for x in roll], "first": first,
            "last": last, "take": take, "ladder": ladder, "now": now, "down_first": downs[0] if downs else None,
            "snip_first": _voc_snip(snips[first], term) if first is not None and first in snips else "",
            "snip_take": _voc_snip(snips[take], term) if take is not None and take in snips else "",
            "snip_last": _voc_snip(snips[last], term) if last is not None and last in snips else ""}


def _voc_texts(c):
    reps, texts = [], []
    for r in c["reports"]:
        sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
        if not sec:
            continue
        reps.append(r)
        texts.append(corpus_text(c, r, sec["file"]))
    return reps, texts


def vocab_build(c):
    reps, texts = _voc_texts(c)
    n = len(reps)
    if n < 6:
        return {"error": "「사업의 내용」이 있는 보고서가 6건도 안 됩니다."}
    cnts = [Counter(INF.tokens(t)) for t in texts]
    ns = [max(1, sum(x.values())) for x in cnts]
    D = vocab_df()
    N = (D or {}).get("n") or 0
    dfm = (D or {}).get("df") or {}
    vocab = Counter()
    for cn in cnts:
        vocab.update(cn.keys())
    import math
    rows = []
    for t, pres in vocab.items():
        if pres < 2 or max(cn.get(t, 0) for cn in cnts) < 3:
            continue
        dfr = dfm.get(t, 0) / N if N else None
        if not _voc_ok(t, dfr):
            continue
        s = [cnts[i].get(t, 0) / ns[i] * 1e4 for i in range(n)]
        past_w = s[max(0, n - 12):n - 4]
        rec = sum(s[-4:]) / 4
        past = sum(past_w) / len(past_w) if past_w else 0
        roll = [sum(s[max(0, i - 3):i + 1]) / len(s[max(0, i - 3):i + 1]) for i in range(n)]
        peak = max(roll)
        pk = roll.index(peak)
        idf = math.log((N + 1) / (dfm.get(t, 0) + 1)) if N else 2.0
        last = max(i for i in range(n) if cnts[i].get(t, 0) > 0)
        first = min(i for i in range(n) if cnts[i].get(t, 0) > 0)
        rows.append({"t": t, "rec": rec, "past": past, "peak": peak, "pk": pk, "pres": pres / n, "idf": idf, "last": last, "first": first,
                     "acr": bool(re.fullmatch(r"[A-Z][A-Z0-9&\+\-]{1,7}", t))})
    mom = lambda r: (r["rec"] + 0.5) / (r["past"] + 0.5)
    # 예전에 더 크게 쓰다 돌아온 말(모바일용 2014 정점)은 '떠오른 말'이 아니다
    rising = sorted([r for r in rows if r["rec"] >= 3 and mom(r) >= 2.5 and not (r["pk"] < n - 8 and r["peak"] >= 1.5 * r["rec"])],
                    key=lambda r: -r["rec"] * math.sqrt(mom(r)) * min(r["idf"], 5))[:10]
    fading = sorted([r for r in rows if r["peak"] >= 5 and r["rec"] <= 0.3 * r["peak"] and r["pk"] < n - 4],
                    key=lambda r: -r["peak"] * (1 - r["rec"] / r["peak"]) * min(r["idf"], 5))[:10]
    core = sorted([r for r in rows if r["pres"] >= 0.85 and r["rec"] >= 6 and 0.5 <= (r["rec"] + .5) / (r["past"] + .5) <= 2
                   and r not in rising], key=lambda r: -r["rec"] * min(r["idf"], 5))[:8]
    # 세대 교체 — 같은 약어 뿌리에 숫자 세대가 둘 넘게 붙은 것
    fams = defaultdict(list)
    for r in rows:
        m = re.fullmatch(r"([A-Z]{2,})(\d[A-Z0-9\+]*)?", r["t"])
        if m:
            fams[m.group(1)].append(r)
    families = []
    for root, L in fams.items():
        gens = [x for x in L if x["t"] != root]
        if len(gens) < 2:
            continue
        families.append({"root": root, "members": sorted(x["t"] for x in L)})
    families.sort(key=lambda f: -len(f["members"]))
    families = families[:4]
    # 고른 말마다 궤적 — 지면·단계·본격화·토막
    pick = []
    for grp, L in (("rising", rising), ("core", core), ("fading", fading)):
        for r in L:
            pick.append((grp, r))
    fam_terms = [t for f in families for t in f["members"]]
    tracks = {}
    for grp, r in pick:
        tracks[r["t"]] = dict(_voc_track(reps, texts, ns, r["t"]), grp=grp, rec=round(r["rec"], 1), past=round(r["past"], 1),
                              peak=round(r["peak"], 1), pk=r["pk"], idf=round(r["idf"], 2))
    for t in fam_terms:
        if t not in tracks:
            tracks[t] = dict(_voc_track(reps, texts, ns, t), grp="family")
    # 본격화 뒤 1년 주가(수정주가, 그 보고서 접수일 종가 기준)
    prices = {}
    try:
        prices = FIN.fetch_prices(c["code"]) or {}
    except Exception:
        prices = {}
    ds = sorted(prices)

    def fwd(i, days=365):
        if i is None or not ds:
            return None
        d0 = reps[i]["rcept"][:8]
        p0, d0 = FIN.price_on(prices, d0)
        if not p0:
            return None
        t1 = (dt.datetime.strptime(d0, "%Y%m%d") + dt.timedelta(days=days)).strftime("%Y%m%d")
        if t1 > ds[-1]:
            return None
        p1 = FIN.price_on(prices, t1)[0]
        return round((p1 / p0 - 1) * 100, 1) if p1 else None
    for t, tr in tracks.items():
        tr["take_r1"] = fwd(tr["take"])
        # 이 회사 「사업의 내용」에서 몇 번째로 많이 쓴 말인가(최근 보고서) — '1만 낱말당'보다 와닿는다
        k = tr["cnt"][-1] if tr["cnt"] else 0
        tr["n_last"] = k
        tr["rank"] = 1 + sum(1 for v in cnts[-1].values() if v > k) if k else None
    # 이름 바뀜 — 새 말이 나온 즈음 비슷한 이름의 말이 사라졌으면(광학통신솔루션 → 광학솔루션) 새 사업이 아니라 개명
    faded = [r for r in rows if r["peak"] >= 3 and r["rec"] <= 0.35 * r["peak"]]
    for r in rising:
        tr = tracks.get(r["t"])
        if not tr or tr["first"] is None:
            continue
        f0 = tr["first"]
        best = None
        for o in faded:
            if o["t"] == r["t"] or not (f0 - 2 <= o["last"] <= f0 + 1) or o["first"] >= f0:
                continue
            sm = difflib.SequenceMatcher(None, o["t"], r["t"])
            sim = sm.ratio()
            common = sm.find_longest_match(0, len(o["t"]), 0, len(r["t"])).size
            pre = len(os.path.commonprefix([o["t"], r["t"]]))
            suf = len(os.path.commonprefix([o["t"][::-1], r["t"][::-1]]))
            # 개명은 같은 자리의 앞말·뒷말을 남기고(광학'통신'솔루션 → 광학솔루션), 옛 이름의 분량을 곧바로 넘겨받는다.
            # 빅데이터 → 데이터센터처럼 겹치는 글자가 자리를 바꾼 것, 새 말이 작게 시작한 것은 개명이 아니다
            s_new = tr["share"][f0] if tr.get("share") else 0
            size_ok = o["peak"] > 0 and 0.4 <= s_new / o["peak"] <= 2.5
            if sim >= 0.5 and common >= 3 and (pre >= 2 or suf >= 3) and size_ok and (best is None or sim > best[0]):
                best = (sim, o)
        if best:
            o = best[1]
            tr["renamed_from"] = {"t": o["t"], "last": o["last"], "first": o["first"], "peak": round(o["peak"], 1)}
            if o["t"] in tracks:
                tracks[o["t"]]["renamed_to"] = {"t": r["t"], "first": f0}
    # 회사 매출 증가율(4분기 합, 전년 대비) — 말과 숫자를 나란히 보기 위해
    rev = []
    try:
        dk = druck(c["code"]) or {}
        pts = dk.get("points", [])
        # 분기 하나의 전년 대비(yoy)와 최근 4분기 합의 전년 대비(ttm) — 연말 쏠림·기준 효과는 4분기 합에서 지워진다
        ttm_of = {(p["year"], p["q"]): p.get("매출_TTM") for p in pts}
        for p in pts:
            a, b = p.get("매출_TTM"), ttm_of.get((p["year"] - 1, p["q"]))
            ttm = round((a / b - 1) * 100, 1) if (a and b and b > 0) else None
            if p.get("매출YoY") is not None or ttm is not None:
                rev.append({"label": p["label"], "y": p["year"], "q": p["q"],
                            "yoy": round(p["매출YoY"], 1) if p.get("매출YoY") is not None else None, "ttm": ttm})
    except Exception:
        pass
    return {"v": VOC_V, "code": c["code"], "name": c["name"], "df": bool(D), "df_n": N,
            "reports": [{"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"]} for r in reps], "ns": ns,
            "rising": [r["t"] for r in rising], "core": [r["t"] for r in core], "fading": [r["t"] for r in fading],
            "families": families, "tracks": tracks, "rev": rev}


def vocab_view(code, terms=None):
    c = company_by_code(code)
    if not c:
        return None
    if INF is None:
        return {"error": "변곡점 모듈이 없어 낱말을 셀 수 없습니다."}
    p = os.path.join(CACHE_DIR, "vocab", code + ".json")
    sig = "%s:%d:%d:%s" % (c["reports"][-1]["rcept"] if c["reports"] else "", len(c["reports"]), VOC_V, bool(vocab_df()))
    d = None
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("sig") != sig:
                d = None
        except Exception:
            d = None
    if d is None:
        d = vocab_build(c)
        if not d.get("error"):
            d["sig"] = sig
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
    if VDF["state"] == "building":
        d["df_building"] = {"done": VDF["done"], "total": VDF["total"]}
    if terms:
        reps, texts = _voc_texts(c)
        ns = d.get("ns") or []
        if len(ns) != len(reps):
            ns = [max(1, len(INF.tokens(t))) for t in texts]
        mine = {}
        for t in terms[:6]:
            rx, _, extra = ask_query_rx(t)
            if rx is None:
                continue
            mine[t] = dict(_voc_track(reps, texts, ns, rx), grp="mine", extra=extra)
            k = mine[t]["cnt"][-1] if mine[t]["cnt"] else 0
            if k:
                last_c = Counter(INF.tokens(texts[-1]))
                mine[t]["n_last"], mine[t]["rank"] = k, 1 + sum(1 for v in last_c.values() if v > k)
        d = dict(d, mine=mine)
    return d


# ---------------------------------------------------------------- 말과 주가: 이 말은 그때 주가를 움직인 이야기였나
# 뉴스는 없다. 대신 세 가지로 가린다.
#   시장 — 같은 해 사업보고서에서 이 말을 새로 쓰기 시작한 회사들의 주가가 시장보다 올랐나(그렇다면 시장의 테마)
#   시점 — 이 회사 주가가 첫 언급 전에 이미 올랐나(보고서가 뒤따름), 본격화 뒤에 올랐나(보고서가 앞섬)
#   값 매김 — 그 기간 주가 상승이 이익(또는 매출) 증가로 설명되나, 값을 더 쳐준(PER·PSR 상승) 몫이 크나
NARR_V = 2
THEME = {}
THEME_LOCK = threading.Lock()


def _px_cache(code):
    """가격 캐시를 그대로 읽는다 — 전 종목을 훑을 때 네이버를 다시 부르지 않게."""
    p = os.path.join(CACHE_DIR, "price", code + ".json")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _px_ret(prices, d0, d1):
    if not prices:
        return None
    p0 = FIN.price_on(prices, d0, 12)[0]
    p1 = FIN.price_on(prices, d1, 12)[0]
    return (p1 / p0 - 1) * 100 if (p0 and p1) else None


def _dshift(d, days):
    return (dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(days=days)).strftime("%Y%m%d")


def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def _theme_key(term, fy, d0, d1):
    import hashlib
    return hashlib.md5(("%s|%d|%s|%s|%d" % (term, fy, d0, d1, 1)).encode("utf-8")).hexdigest()[:16]


def _run_theme(key, term, fy, d0, d1):
    """전 종목 — 그해(fy)와 2년 전 사업보고서 「사업의 내용」에서 이 말을 몇 번 썼나, 그리고 창(d0~d1) 동안 주가."""
    st = THEME[key]
    try:
        rx, _, _ = ask_query_rx(term)
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9&\+\-]*", term):
            rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])")
        comps = list(INDEX["companies"])
        st["total"] = len(comps)
        rows = []
        for k, c in enumerate(comps):
            st["done"] = k
            ann = {}
            for r in c["reports"]:
                if r["label"] == "사업보고서":
                    y = int(r["stamp"][:4])
                    if y not in ann or r["rcept"] > ann[y]["rcept"]:
                        ann[y] = r
            r1 = ann.get(fy)
            if not r1:
                continue
            ret = _px_ret(_px_cache(c["code"]), d0, d1)
            if ret is None:
                continue

            def cnt(r):
                sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
                if not sec:
                    return None
                try:
                    t = read_section(c, r, sec["file"])
                except Exception:
                    return None
                return len(rx.findall(t)) if t else None
            c1 = cnt(r1)
            if c1 is None:
                continue
            r0 = ann.get(fy - 2)
            c0 = cnt(r0) if (r0 and c1 >= 3) else None
            rows.append({"code": c["code"], "name": c["name"], "c1": c1, "c0": c0, "ret": round(ret, 1)})
        allr = [r["ret"] for r in rows]
        users = [r for r in rows if r["c1"] >= 3]
        adopt = [r for r in users if r["c0"] is not None and r["c0"] == 0]
        out = {"v": NARR_V, "term": term, "fy": fy, "d0": d0, "d1": d1, "n_all": len(rows), "all_med": _median(allr),
               "n_users": len(users), "users_med": _median([r["ret"] for r in users]),
               "n_adopt": len(adopt), "adopt_med": _median([r["ret"] for r in adopt]),
               "adopt_top": sorted(adopt, key=lambda r: -r["c1"])[:12],
               "users_top": sorted(users, key=lambda r: -r["c1"])[:12],
               "rets": {r["code"]: r["ret"] for r in rows}}
        os.makedirs(os.path.join(CACHE_DIR, "theme"), exist_ok=True)
        with open(os.path.join(CACHE_DIR, "theme", key + ".json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
        st["data"] = out
    except Exception as e:
        import traceback
        traceback.print_exc()
        st["error"] = "%s: %s" % (type(e).__name__, e)


def _theme(term, fy, d0, d1):
    key = _theme_key(term, fy, d0, d1)
    p = os.path.join(CACHE_DIR, "theme", key + ".json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    with THEME_LOCK:
        st = THEME.get(key)
        if st and st.get("data"):
            return st["data"]
        if st and st.get("error"):
            return {"error": st["error"]}
        if st is None:
            st = THEME[key] = {"done": 0, "total": 0}
            threading.Thread(target=_run_theme, args=(key, term, fy, d0, d1), daemon=True).start()
    return {"pending": True, "done": st["done"], "total": st["total"]}


def narrative_view(code, term):
    c = company_by_code(code)
    if not c:
        return None
    d = vocab_view(code, None)
    if not d or d.get("error"):
        return {"error": (d or {}).get("error") or "낱말 자료가 없습니다."}
    tr = d["tracks"].get(term)
    reps = d["reports"]
    if tr is None:      # 직접 찾은 말
        rs, texts = _voc_texts(c)
        rx, _, _ = ask_query_rx(term)
        if rx is None:
            return {"error": "찾을 말이 없습니다."}
        tr = _voc_track(rs, texts, d.get("ns") or [max(1, len(INF.tokens(t))) for t in texts], rx)
    if tr.get("first") is None:
        return {"error": "이 말은 보고서에 나오지 않았습니다."}
    fi = tr["first"]
    ti = tr["take"] if tr.get("take") is not None else fi
    f_d, t_d = reps[fi]["rcept"][:8], reps[ti]["rcept"][:8]
    today = dt.date.today().strftime("%Y%m%d")
    prices = {}
    try:
        prices = FIN.fetch_prices(code) or {}
    except Exception:
        prices = _px_cache(code)

    def win(a, b):
        b2 = min(b, today)
        r = _px_ret(prices, a, b2)
        return {"d0": a, "d1": b2, "ret": round(r, 1) if r is not None else None, "partial": b > today}
    # 시점 — 첫 언급 전 6개월 · 첫 언급→본격화 · 본격화 뒤 1년
    timing = {"pre": win(_dshift(f_d, -182), f_d), "mid": win(f_d, t_d) if ti != fi else None, "post": win(t_d, _dshift(t_d, 365))}
    # 값 매김 — 창(본격화 1년 전 ~ 6개월 뒤) 동안 주가 = 이익(또는 매출) × 값 매김
    d0, d1 = _dshift(t_d, -365), min(_dshift(t_d, 182), today)
    pr = _px_ret(prices, d0, d1)
    rerate = None
    try:
        dk = druck(code) or {}
        allp = [p for p in dk.get("points", []) if p.get("year")]
        Pby = {p["year"] * 4 + p["q"] - 1: p for p in allp}
        P = [p for p in allp if p.get("주가일")]
        ni = {}
        for k, p in enumerate(P):
            # 4분기 합은 분기 키 창으로 — 주가일로 거른 목록의 순번 창은 주가를 못 붙인 분기를 건너뛰어 다른 네 분기를 더했다
            n = p["year"] * 4 + p["q"] - 1
            w4 = [Pby.get(m) for m in range(n - 3, n + 1)]
            ni[k] = sum(x["당기순이익"] for x in w4) if all(x is not None and x.get("당기순이익") is not None for x in w4) else None
        k0 = max((k for k, p in enumerate(P) if p["주가일"] <= d0), default=None)
        k1 = max((k for k, p in enumerate(P) if p["주가일"] <= d1), default=None)
        if pr is not None and k0 is not None and k1 is not None and k1 > k0:
            e0, e1 = ni.get(k0), ni.get(k1)
            if e0 and e1 and e0 > 0 and e1 > 0:
                base, g = "순이익(4분기 합)", (e1 / e0 - 1) * 100
            else:
                s0, s1 = P[k0].get("매출_TTM"), P[k1].get("매출_TTM")
                base, g = "매출(4분기 합)", ((s1 / s0 - 1) * 100 if (s0 and s1 and s0 > 0) else None)
            if g is not None:
                rr = ((1 + pr / 100) / (1 + g / 100) - 1) * 100
                rerate = {"base": base, "growth": round(g, 1), "price": round(pr, 1), "rerate": round(rr, 1),
                          "from": P[k0]["label"], "to": P[k1]["label"]}
    except Exception:
        pass
    # 시장 — 그해 사업보고서 기준
    # 본격화 보고서가 속한 해의 사업보고서가 이미 나왔으면 그해, 아니면 그 전 해
    ty = int(reps[ti]["stamp"][:4])
    fy = ty if any(r["label"] == "사업보고서" and int(r["stamp"][:4]) == ty for r in reps) else ty - 1
    th = _theme(term, fy, d0, d1)
    out = {"term": term, "first": reps[fi], "take": reps[ti], "same": ti == fi, "timing": timing, "rerate": rerate,
           "window": {"d0": d0, "d1": d1, "ret": round(pr, 1) if pr is not None else None}, "fy": fy}
    if th.get("pending"):
        out["theme_pending"] = {"done": th["done"], "total": th["total"]}
    elif th.get("error"):
        out["theme_error"] = th["error"]
    else:
        th = dict(th)
        rets = th.pop("rets", {})
        allv = sorted(rets.values())
        mine = rets.get(code, out["window"]["ret"])
        th["me"] = mine
        th["me_pct"] = round(sum(1 for v in allv if v <= mine) / len(allv) * 100) if (allv and mine is not None) else None
        out["theme"] = th
        out["verdict"] = _narr_verdict(out)
    return out


def _narr_verdict(o):
    """판정. 이 말만 따로 떼어 주가 효과를 잴 수는 없다 — 시장 비교(같은 말을 쓴 회사들)만이 말 자체에 대한 증거이고,
    회사만 쓰는 말이면 '그 무렵 이 회사 주가에 이야기 값이 붙었나'와 '시점이 겹치나'까지만 말한다."""
    th, tm, rr = o.get("theme") or {}, o.get("timing") or {}, o.get("rerate")
    mkt = th.get("all_med")
    ad_n, ad_m = th.get("n_adopt") or 0, th.get("adopt_med")
    us_n, us_m = th.get("n_users") or 0, th.get("users_med")
    others = max(ad_n, us_n) - 1          # 이 회사 빼고
    theme = (ad_n >= 8 and ad_m is not None and mkt is not None and ad_m - mkt >= 10) or             (us_n >= 15 and us_m is not None and mkt is not None and us_m - mkt >= 10)
    pct = th.get("me_pct")
    out_perf = pct is not None and pct >= 70
    under = pct is not None and pct <= 40
    re_up = rr is not None and rr["rerate"] >= 25
    pre = (tm.get("pre") or {}).get("ret")
    mid = (tm.get("mid") or {}).get("ret")
    post = (tm.get("post") or {}).get("ret")
    during = mid if mid is not None else post
    lines = []
    if theme:
        lines.append("같은 해 이 말을 쓴 회사 %d곳의 주가 중앙값이 시장보다 %d%%p 높았다 — 시장이 사던 이야기다." % (
            max(ad_n, us_n), round((ad_m if ad_n >= 8 else us_m) - mkt)))
    elif others >= 3:
        lines.append("이 말을 쓴 다른 회사 %d곳의 주가는 시장과 크게 다르지 않았다 — 시장 전체의 테마는 아니었다." % others)
    else:
        lines.append("다른 회사는 거의 쓰지 않는 이 회사만의 말이라 시장 비교로는 가릴 수 없다.")
    if out_perf:
        lines.append("이 회사 주가는 그 무렵 전 종목 상위 %d%%였다." % (100 - pct))
    elif under:
        lines.append("이 회사 주가는 그 무렵 시장보다 못했다(전 종목 하위 %d%%)." % pct)
    if re_up:
        lines.append("주가 상승의 상당 몫(값 매김 %+d%%)이 이익이 아니라 시장이 값을 더 쳐준 데서 왔다 — 이야기에 값이 붙은 시기다." % round(rr["rerate"]))
    elif rr is not None and out_perf:
        lines.append("주가는 이야기보다 %s 증가를 따라 올랐다." % rr["base"].split("(")[0])
    lead = pre is not None and pre >= 40 and (during is None or during < pre * 0.5)
    if lead:
        lines.append("주가는 첫 언급 전 6개월에 이미 %+d%% 올랐다 — 보고서는 시장이 먼저 본 이야기를 뒤따라 적었다." % round(pre))
    elif during is not None and during >= 30:
        lines.append("이 말이 커지는 동안 주가도 %+d%% 올랐다 — 시점이 겹친다." % round(during))
    if theme and out_perf:
        v = ("맞물림", "시장의 이야기와 함께 움직였다")
    elif theme:
        v = ("비껴감", "시장의 이야기였지만 이 회사 주가는 따라가지 못했다")
    elif out_perf and re_up and lead:
        v = ("뒤따름", "주가가 먼저 오르고, 이 말은 뒤따라 보고서에 커졌다")
    elif out_perf and re_up and during is not None and during >= 30:
        v = ("겹침", "이 회사 주가에 이야기 값이 붙던 때와 겹친다 — 이 말이 그 이야기였는지는 문장으로 확인")
    elif out_perf:
        v = ("부분", "주가는 올랐지만 이야기보다 이익이 끌었다")
    elif under:
        v = ("무관", "주가를 끌어올린 이야기는 아니었다")
    else:
        v = ("약함", "주가와 뚜렷한 관계가 없다")
    return {"k": v[0], "t": v[1], "lines": lines, "theme": theme}


# ---------------------------------------------------------------- 억울한 낙폭: 잔고는 쌓이는데 주가만 빠진 회사
# 수주잔고 증가 탭의 세 번째 칸. 여섯 관문을 차례로 통과해야 한다.
#   ① 잔고   — 수주잔고를 믿을 수 있고(검산) 늘고 있으며, 새 수주가 매출보다 빨리 들어온다(북투빌 ≥ 1)
#   ② 돈     — 최근 4분기 영업이익·순이익 흑자, 3년 누적 영업현금흐름 흑자, 순차입 과다 아님,
#              매출이 줄지 않고 이익률이 무너지지 않았다(저가 수주 아님), 매출채권·재고가 매출보다 빨리 불지 않았다
#   ③ 주주가치 — 2년 안에 희석 목적 유상증자·사모 전환사채(리픽싱)·물적분할·감자·관리종목·횡령·감사 문제가 없다
#   ④ 하락   — 52주 고점 대비 20% 넘게 빠졌다
#   ⑤ 억울함 — 그 사이 이익은 버텼다(값 매김만 줄었다), 그리고 시장·업종도 함께 빠졌다(매크로·심리)
#   ⑥ 싸다   — 자기 역사 대비 PER 위치(풍경 탭과 같은 계산)
DIP_V = 8          # 7: 앞단 · 빨간불(2026-10-02) · 8: 새 점수(업종 가격 · 북투빌 · 낙폭 · 이익률) · 등급 = 빨간불 없음 + 점수 50↑(도구/억울_새점수.py)
DIP = {"running": False, "done": 0, "total": 0, "rows": [], "at": 0, "phase": "", "funnel": {}, "drop": []}
DIP_LOCK = threading.Lock()
DIP_DIR = os.path.join(CACHE_DIR, "dip")
DIP_EVENTS = [   # (분류, 보고서명 정규식, 기간(년), 기본 판정 x=탈락 !=주의) — 세부 내용으로 다시 판정한다
    ("유상증자", re.compile(r"유상증자\s*결정"), 2, "x"),
    ("전환사채", re.compile(r"전환사채권\s*발행\s*결정"), 2, "x"),
    ("신주인수권부사채", re.compile(r"신주인수권부사채권\s*발행\s*결정"), 2, "x"),
    ("교환사채", re.compile(r"교환사채권\s*발행\s*결정"), 2, "!"),
    ("회사분할", re.compile(r"회사분할\s*결정|분할합병\s*결정"), 3, "x"),
    ("감자", re.compile(r"감자\s*결정"), 3, "x"),
    ("자기주식 처분", re.compile(r"자기주식\s*처분\s*결정"), 1, "!"),
    ("관리·불성실", re.compile(r"관리종목|투자주의환기|상장적격성|상장폐지|불성실공시법인"), 2, "x"),
    ("횡령·배임", re.compile(r"횡령|배임"), 3, "x"),
    ("감사 문제", re.compile(r"감사의견\s*(?:거절|한정|부적정)|감사보고서\s*제출\s*지연|계속기업"), 3, "x"),
    ("부도·회생", re.compile(r"부도|회생절차|파산|당좌거래\s*정지"), 3, "x"),
    ("최대주주 변경", re.compile(r"최대주주\s*변경"), 1, "!"),
]
DIP_WHY = {   # 세부 API가 없는 공시의 기본 설명
    "자기주식 처분": "갖고 있던 자사주를 내놨다 — 세부를 못 읽었다. 시장 매각·교환사채 담보면 물량 부담",
    "최대주주 변경": "주인이 바뀌었다 — 새 주인의 의도와 인수 자금(차입·주식담보)을 확인",
    "관리·불성실": "거래소 지정 — 공시·재무 신뢰에 금이 갔다",
    "감사 문제": "감사인이 재무제표를 믿기 어렵다고 봤다",
    "부도·회생": "빚을 제때 못 갚는 상태",
}
# 이름에 이 말이 있으면 나쁜 일이 아니다 — 미지정·해제·이전상장(코넥스→코스닥) 등
DIP_SKIP = re.compile(r"미지정|지정\s*유예|해제|미해당|이전\s*상장|지정\s*취소")
DIP_SOFT = re.compile(r"예고|우려")          # 아직 확정 전 — 주의로만
DIP_DETAIL = {"유상증자": "piicDecsn", "전환사채": "cvbdIsDecsn", "신주인수권부사채": "bdwtIsDecsn",
              "교환사채": "exbdIsDecsn", "회사분할": "cmpDvDecsn", "감자": "crDecsn", "자기주식 처분": "tsstkDpDecsn"}


def _dip_get(url, params, key, ttl=12 * 3600):
    """DART 호출 한 번 — 결과를 파일로 저장해 12시간 재사용. 키는 화면·로그에 남기지 않는다."""
    import requests
    os.makedirs(DIP_DIR, exist_ok=True)
    p = os.path.join(DIP_DIR, key + ".json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    try:
        js = requests.get(url, params=dict(params, crtfc_key=FIN.API_KEY), timeout=40).json()
    except Exception:
        return None
    if js.get("status") in ("000", "013"):
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(js, fh, ensure_ascii=False)
        time.sleep(0.12)
        return js
    return None


def _dip_disclosures(corp):
    """3년 치 공시 목록."""
    end = dt.date.today()
    bgn = end - dt.timedelta(days=365 * 3 + 5)
    out, page = [], 1
    while page <= 12:
        js = _dip_get(DART_API_LIST, {"corp_code": corp, "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
                                      "page_no": page, "page_count": 100}, "list_%s_%d" % (corp, page))
        if not js or js.get("status") != "000":
            break
        out.extend(js.get("list") or [])
        if page >= int(js.get("total_page", 1)):
            break
        page += 1
    return out


DART_API_LIST = "https://opendart.fss.or.kr/api/list.json"


def _dip_flat(item):
    return " ".join(str(v) for v in item.values() if v not in (None, "", "-"))


def _dip_num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def _dip_judge(kind, base, item, cap):
    """주요사항 세부로 다시 판정. (판정, 한 줄 근거)"""
    flat = _dip_flat(item)
    if kind == "유상증자":
        new = _dip_num(item.get("nstk_ostk_cnt")) or 0
        pre = _dip_num(item.get("bfic_tisstk_ostk"))
        dil = (new / pre * 100) if (pre and new) else None
        way = item.get("ic_mthn") or next((w for w in ("주주배정", "일반공모", "제3자배정") if w in flat), "")
        opx = (_dip_num(item.get("fdpp_op")) or 0) + (_dip_num(item.get("fdpp_dtrp")) or 0)
        fac = _dip_num(item.get("fdpp_fclt")) or 0
        why = "%s%s%s" % (way or "방식 미상", " · 희석 %.1f%%" % dil if dil is not None else "",
                          " · 운영·채무상환 자금" if opx > fac else (" · 시설자금" if fac else ""))
        if "제3자" in (way or ""):
            return ("x" if (dil or 0) >= 20 else "!", why + " — 누구에게 얼마에 배정했는지 확인")
        if opx > fac:
            return "x", why + " — 돈이 모자라 주주에게 손을 벌렸다"
        if "주주배정" not in (way or "") and (dil or 0) >= 10:
            return "x", why + " — 기존 주주에게 먼저 사게 하지 않고 대규모로 새 주식을 풀었다"
        if (dil or 0) >= 10:
            return "!", why + " — 증설 자금이지만 주당 몫이 크게 줄었다. 그 증설이 수주로 채워지는지 확인"
        return "!", why
    if kind in ("전환사채", "신주인수권부사채", "교환사채"):
        amt = _dip_num(item.get("bd_fta"))
        priv = "사모" in flat
        refix = any(k.startswith("act_mktprc") and k.endswith("lwtrsprc") and v not in (None, "", "-")
                    for k, v in item.items()) or "리픽싱" in flat
        pct = _dip_num(item.get("cvisstk_tisstk_vs") or item.get("nstk_isstk_tisstk_vs") or item.get("exisstk_tisstk_vs"))
        if pct is None and amt and cap:
            pct = amt / cap * 100
        why = "%s%s%s" % ("사모" if priv else "공모", " · 희석 %.1f%%" % pct if pct is not None else "",
                          " · 전환가액 하향 조정(리픽싱) 조항" if refix else " · 리픽싱 없음")
        if kind == "교환사채":
            tg = item.get("extg") or ""
            if not _dip_own(item.get("corp_name") or "", tg):
                return "ok", "다른 회사(%s) 주식으로 바꿔 주는 사채 — 이 회사 주식 수와 무관" % tg.strip()
            return "!", why + " — 자사주를 담보로 한 교환사채(물량 출회)"
        if priv and refix and (pct is None or pct >= 3):
            return "x", why + " — 주가가 빠질수록 주식 수가 불어나는 구조"
        if priv and (pct or 0) >= 10:
            return "x", why + " — 사모로 대규모 잠재 물량"
        return "!", why + (" — 가격 조정 없는 소규모 발행, 자금 용도 확인" if not refix else "")
    if kind == "회사분할":
        if "물적" in flat:
            return "x", "물적분할 — 알짜 사업을 자회사로 떼어 내 모회사 주주 몫이 줄 수 있다"
        if "인적" in flat:
            return "!", "인적분할 — 지배구조 개편. 주주 몫은 그대로지만 목적 확인"
        return base, "분할 방식 미상"
    if kind == "자기주식 처분":
        pp = re.sub(r"\s+", " ", item.get("dp_pp") or "")
        sell = any(item.get(k) not in (None, "", "-") for k in ("dp_m_mkt", "dp_m_ovtm"))
        if re.search(r"교환|재무|운영\s*자금|유동성|차입", pp) or sell:
            return "!", "%s%s — 자사주를 팔아 현금으로 바꿨다(물량)" % (pp or "목적 미상", " · 장내·시간외 매각" if sell else "")
        if re.search(r"임직원|임원|직원|이사|성과|보상|보수|RSU|RSA|양도\s*제한|Stock\s*Grant|상여|우리사주|주식\s*매수\s*선택권|스톡\s*옵션", pp, re.I):
            return "ok", pp
        return "!", pp or "목적 미상"
    if kind == "감자":
        how = "%s %s" % (item.get("cr_mth") or "", item.get("cr_rs") or "")
        if re.search(r"자기\s*주식|이익\s*소각", how):
            return "+", "자기주식 소각 — 주주 환원(주당 몫이 커진다)"
        if "유상" in flat:
            return "x", "유상감자 — 회사 돈이 (대)주주에게 빠져나간다"
        return "x", "무상감자 — 결손을 메우려는 자본 축소(재무 위기 신호)"
    return base, ""


def _dip_own(corp_name, target):
    """교환 대상이 이 회사 자기 주식인가. 영문 약자 이름은 한글 법인명으로도 맞춰 본다(HD→에이치디)."""
    norm = lambda t: re.sub(r"주식회사|\(주\)|㈜|\s", "", t or "")
    tg, nm = norm(target), norm(corp_name)
    if "자기주식" in tg or tg.startswith("당사") or not nm:
        return True
    alt = nm
    for a, b in (("HD", "에이치디"), ("LG", "엘지"), ("SK", "에스케이"), ("LS", "엘에스"), ("CJ", "씨제이"),
                 ("GS", "지에스"), ("DL", "디엘"), ("KT", "케이티"), ("HL", "에이치엘"), ("DN", "디엔")):
        alt = alt.replace(a, b)
    return any(re.match(re.escape(n) + r"(?:기명|무기명|보통|우선|발행|의|$)", tg) for n in (nm, alt))   # HD현대 ≠ 에이치디현대중공업


def _dip_doc(rcept):
    """공시 원문(본문 텍스트) — 세부 API가 없는 공시(횡령·배임 등)를 읽는다. 30일 캐시."""
    import requests, zipfile, io as _io
    p = os.path.join(DIP_DIR, "doc_%s.txt" % rcept)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as fh:
            return fh.read()
    try:
        r = requests.get("https://opendart.fss.or.kr/api/document.xml", params={"crtfc_key": FIN.API_KEY, "rcept_no": rcept}, timeout=60)
        if r.content[:2] != b"PK":
            return ""
        t = ""
        with zipfile.ZipFile(_io.BytesIO(r.content)) as z:
            for n in z.namelist():
                raw = z.read(n)
                for enc in ("utf-8", "cp949", "euc-kr"):
                    try:
                        t += raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
    except Exception:
        return ""
    t = re.sub(r"\s+", " ", re.sub(r"<style.*?</style>|<[^>]+>", " ", t, flags=re.S))[:8000]
    os.makedirs(DIP_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(t)
    time.sleep(0.2)
    return t


def _dip_embezzle(rcept):
    """횡령·배임 공시 본문으로 다시 판정 — 무죄·무혐의로 끝난 건과 자기자본 대비 작은 건을 가른다."""
    t = _dip_doc(rcept)
    if not t:
        return "x", "본문을 못 읽어 보수적으로 판정"
    if re.search(r"무죄|무혐의|혐의\s*없음|불기소|공소\s*기각", t):
        return "ok", "무죄·무혐의로 끝난 사안"
    m = re.search(r"자기자본\s*대비\s*\(%\)\s*([0-9.]+)", t)
    who = "전직 임원" if re.search(r"전직|前", t[:1500]) else ("직원" if "직원" in t[:1500] else "")
    if m:
        r = float(m.group(1))
        if r < 1:
            return "!", "자기자본의 %.2f%%%s — 작지만 내부통제 확인" % (r, " · " + who if who else "")
        return "x", "자기자본의 %.1f%%%s" % (r, " · " + who if who else "")
    return "x", who


def _dip_events(corp, cap, listed=None):
    """주주가치를 해칠 수 있는 공시 — 3년 치 목록을 이름으로 거르고, 증자·사채·분할·감자는 세부로 다시 판정."""
    rows = _dip_disclosures(corp)
    today = dt.date.today()
    out = []
    seen = set()
    for x in rows:
        nm = (x.get("report_nm") or "").strip()
        if re.match(r"^\[(?:기재정정|첨부정정|첨부추가|정정)\]", nm):
            continue
        if re.search(r"종속회사|자회사의\s*주요", nm):      # 자회사 일은 본사 주주 몫과 따로 본다
            continue
        d = x.get("rcept_dt") or ""
        if DIP_SKIP.search(nm):
            continue
        if "예고" in nm and any(re.search(r"미지정|지정\s*유예", y.get("report_nm") or "") and (y.get("rcept_dt") or "") >= d for y in rows):
            continue                                    # 예고 뒤 미지정으로 끝났다
        for kind, rx, yrs, base in DIP_EVENTS:
            if not rx.search(nm):
                continue
            if kind == "유상증자" and listed and d <= _dshift(listed, 30):
                break                                   # 상장 공모 — 상장 전 증자는 기존 주주를 해친 일이 아니다
            if d < (today - dt.timedelta(days=int(365 * yrs))).strftime("%Y%m%d"):
                break
            key = (kind, d)
            if key in seen:
                break
            seen.add(key)
            verdict, why = base, ""
            api = DIP_DETAIL.get(kind)
            if api:
                js = _dip_get("https://opendart.fss.or.kr/api/%s.json" % api,
                              {"corp_code": corp, "bgn_de": d, "end_de": d}, "%s_%s_%s" % (api, corp, d), ttl=30 * 86400)
                items = (js or {}).get("list") or []
                items = [i for i in items if i.get("rcept_no") == x.get("rcept_no")] or items   # 같은 날 여러 건이면 이 공시 것을
                if items:
                    verdict, why = _dip_judge(kind, base, items[0], cap)
                else:
                    why = "세부 내용을 못 읽어 보수적으로 판정"
            elif kind == "횡령·배임":
                verdict, why = _dip_embezzle(x.get("rcept_no") or "")
            why = why or DIP_WHY.get(kind, "")
            if DIP_SOFT.search(nm) and verdict == "x":
                verdict, why = "!", "거래소 지정 예고·우려 — 아직 확정 전"
            if verdict == "ok":
                break
            out.append({"kind": kind, "date": d, "report": nm, "v": verdict, "why": why,
                        "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + (x.get("rcept_no") or "")})
            break
    out.sort(key=lambda e: e["date"], reverse=True)
    return out


def _dip_index():
    """시장·업종 = 수집한 전 종목 수정주가. 기간 수익률은 그 기간 종목별 수익률의 중앙값으로 잰다.
    날마다 중앙값 수익률을 곱해 잇는 지수는 아래로 쏠린다(2025.11~2026.9 실제 종목 중앙값 +1%인데 이은 지수는 −47%)."""
    smap = (sector_map() or {}).get("stocks", {})
    series, ind_of = {}, {}
    pdir = os.path.join(CACHE_DIR, "price")
    for f in os.listdir(pdir):
        code = f[:-5]
        try:
            with open(os.path.join(pdir, f), "r", encoding="utf-8") as fh:
                s = json.load(fh)
        except Exception:
            continue
        if s:
            series[code] = (sorted(s), s)
        ind_of[code] = (smap.get(code.upper(), {}) or {}).get("industry") or "분류없음"
    groups = {"__all__": list(series)}
    for code, ind in ind_of.items():
        if ind != "분류없음" and code in series:
            groups.setdefault(ind, []).append(code)
    return {"series": series, "groups": groups}, ind_of


def _grp_ret(idx, g, d0, d1, skip=None):
    """그룹 g의 d0→d1 수익률 중앙값(%). 5종목 미만이면 None."""
    import bisect
    codes = idx["groups"].get(g) or []
    rs = []
    for c in codes:
        if c == skip:
            continue
        ks, s = idx["series"][c]
        i0, i1 = bisect.bisect_right(ks, d0) - 1, bisect.bisect_right(ks, d1) - 1
        if i0 < 0 or i1 <= i0 or _dshift(ks[-1], 10) < d1:     # 거래가 끊긴 종목은 뺀다
            continue
        a, b = s[ks[i0]], s[ks[i1]]
        if a and b:
            rs.append(b / a - 1)
    if len(rs) < 5:
        return None
    rs.sort()
    n = len(rs)
    return (rs[n // 2] if n % 2 else (rs[n // 2 - 1] + rs[n // 2]) / 2) * 100


def _dip_points(c):
    """저평가 관문 ②⑤의 분기 점 — 가속도 캐시(지금 버전), 없으면 최근 SCREEN_YEARS 년 series(빈 분기 점 포함 · 원본 공시일 주가).
    분기 키 격자 그대로 돌려준다 — 쓰는 쪽(_dip_company)은 n 으로 찾는다."""
    corp = corp_code_of(c["code"])
    if not corp or DRK is None:
        return []
    d = _druck_read(c["code"])
    if d and d.get("points"):
        return [p for p in d["points"] if p.get("year")]
    this_year = dt.date.today().year
    meta = _druck_meta(c)
    pts = DRK.series(corp, c["code"], list(range(this_year - SCREEN_YEARS, this_year + 1)), meta=meta, offline=True)
    dates = {(p["year"], p["q"]): meta["filed"][p["n"]] for p in pts if meta["filed"].get(p["n"])}
    try:
        DRK.attach_prices(pts, c["code"], dates)
    except Exception:
        pass
    return pts


def _dip_company(r, trend, idx, ind_of):
    """한 회사를 여섯 관문에 차례로 세운다. 통과 여부와 근거를 모두 돌려준다."""
    code = r["code"]
    c = company_by_code(code)
    corp = corp_code_of(code)
    chk, info = [], {}

    def add(gate, name, ok, why, hard=True):
        chk.append({"gate": gate, "name": name, "ok": ok, "why": why, "hard": hard})
    # ① 잔고
    steady = bool(trend and trend.get("steady"))
    yoy, btb = r.get("backlog_yoy"), r.get("btb")
    add(1, "수주잔고를 믿을 수 있다", r.get("reliable"), r.get("why_not") or "검산·명시된 값이 %d/%d" % (r.get("verified", 0) + r.get("explicit", 0), r.get("n_pts", 0)))
    add(1, "잔고가 꾸준히 늘거나 1년 +15%↑", steady or (yoy is not None and yoy >= 15),
        "1년 %s%s" % ("%+.0f%%" % yoy if yoy is not None else "—", " · 꾸준히 증가" if steady else ""))
    add(1, "새 수주가 매출보다 빨리 들어온다(북투빌 ≥ 1)", btb is not None and btb >= 1.0,
        "북투빌 %s" % ("%.2f" % btb if btb is not None else "—"))
    # ② 돈 — 분기 실적은 최근 4년만(스크리너와 같은 계산, 재무 캐시를 그대로 쓴다). 15년 가속도 캐시를 새로 만들면 회사당 30초가 넘는다
    P = _dip_points(c)
    # 분기 키(n)로 — 4분기 창 · 1년 전 · '지금'(매출이 있는 마지막 분기)이 빈 분기 점(gap · fy)에 밀려 다른 분기를 집지 않게
    Pby = {p["n"]: p for p in P if p.get("n") is not None}

    def ni4_at(p):
        w4 = [Pby.get(m) for m in range(p["n"] - 3, p["n"] + 1)] if p and p.get("n") is not None else [None]
        return sum(x["당기순이익"] for x in w4) if all(x is not None and x.get("당기순이익") is not None for x in w4) else None
    cur = next((p for p in reversed(P) if p.get("매출액") and p.get("n") is not None), None)
    op_now = cur.get("영업이익_TTM") if cur else None
    ni_now = ni4_at(cur)
    add(2, "최근 4분기 영업이익·순이익 흑자", bool(op_now and op_now > 0 and ni_now and ni_now > 0),
        "영업이익 %s · 순이익 %s" % (_won_txt(op_now) if op_now else "—", _won_txt(ni_now) if ni_now else "—"))
    fy = dt.date.today().year
    F = []
    try:
        F = [d for d in INF.fundamentals(FIN, corp, [fy - 3, fy - 2, fy - 1]) if d.get("rev") is not None] if (corp and INF) else []
    except Exception:
        F = []
    cfo3 = sum(d["cfo"] for d in F if d.get("cfo") is not None) if F else None
    cfo_last = F[-1].get("cfo") if F else None
    add(2, "3년 누적 영업현금흐름 흑자", cfo3 is not None and cfo3 > 0 and (cfo_last is None or cfo_last > -abs(cfo3)),
        "3년 누적 %s%s" % (_won_txt(cfo3) if cfo3 is not None else "—", " · 작년 %s" % _won_txt(cfo_last) if cfo_last is not None else ""))
    lf = F[-1] if F else {}
    netdebt = ((lf.get("debt") or 0) - (lf.get("cash") or 0)) if lf else None
    nd_eq = (netdebt / lf["eq"] * 100) if (lf.get("eq") and lf["eq"] > 0 and netdebt is not None) else None
    add(2, "순차입금이 자본의 100% 이하", nd_eq is None or nd_eq <= 100,
        "순차입/자본 %s" % ("%.0f%%" % nd_eq if nd_eq is not None else "자료 없음"), hard=nd_eq is not None)
    rev_yoy, md = r.get("rev_yoy"), r.get("margin_delta")
    add(2, "매출이 줄지 않았다(-5% 이내)", rev_yoy is None or rev_yoy >= -5, "매출 1년 %s" % ("%+.0f%%" % rev_yoy if rev_yoy is not None else "—"))
    add(2, "이익률이 무너지지 않았다(저가 수주 아님)", md is None or md >= -5, "영업이익률 1년 %s" % ("%+.1f%%p" % md if md is not None else "—"))
    ar_up = None
    p4 = Pby.get(cur["n"] - 4) if cur else None
    if p4:
        a0 = (p4.get("매출채권일수") or 0) + (p4.get("재고일수") or 0)
        a1 = (cur.get("매출채권일수") or 0) + (cur.get("재고일수") or 0)
        ar_up = (a1 / a0 - 1) * 100 if a0 > 0 and a1 > 0 else None
    add(2, "매출채권·재고가 매출보다 빨리 불지 않았다", ar_up is None or ar_up <= 35,
        "채권+재고 일수 1년 %s" % ("%+.0f%%" % ar_up if ar_up is not None else "자료 없음"), hard=False)
    # ③ 주주가치
    prices = FIN.fetch_prices(code) or {}
    evs = _dip_events(corp, r.get("cap"), listed=min(prices) if prices else None) if corp else []
    bad = [e for e in evs if e["v"] == "x"]
    warn = [e for e in evs if e["v"] == "!"]
    add(3, "주주가치를 해친 공시가 없다(2~3년)", not bad,
        "; ".join("%s %s.%s — %s" % (e["kind"], e["date"][:4], e["date"][4:6], e["why"]) for e in bad[:3]) or "없음")
    good = [e for e in evs if e["v"] == "+"]
    if good:
        add(3, "주주 환원", True, "자기주식 소각 " + ", ".join("%s.%s" % (e["date"][:4], e["date"][4:6]) for e in good[:4]), hard=False)
    add(3, "주의할 공시(교환사채·자사주 처분·최대주주 변경·인적분할 등)", not warn,
        "; ".join("%s %s.%s%s" % (e["kind"], e["date"][:4], e["date"][4:6], " — " + e["why"] if e["why"] else "") for e in warn[:3]) or "없음", hard=False)
    # ④ 하락
    ds = sorted(prices)
    last = ds[-1] if ds else None
    yr = [d for d in ds if d >= _dshift(last, -365)] if last else []
    hi_d = max(yr, key=lambda d: prices[d]) if yr else None
    dd = (prices[last] / prices[hi_d] - 1) * 100 if hi_d else None
    add(4, "52주 고점 대비 20% 넘게 빠졌다", dd is not None and dd <= -20,
        "고점 %s(%s) → 지금 %s%s" % (("{:,.0f}".format(prices[hi_d]) if hi_d else "—"), (hi_d[:4] + "." + hi_d[4:6] + "." + hi_d[6:]) if hi_d else "",
                                    "{:,.0f}".format(prices[last]) if last else "—", " (%+.0f%%)" % dd if dd is not None else ""))
    # ⑤ 억울함 — 하락 동안 이익은 버텼나, 시장·업종도 빠졌나
    e_chg = rerate = None
    if hi_d and P:
        # 고점 무렵 = 고점일까지 공시된(주가일 ≤ 고점일) 마지막 분기. 주가를 못 붙인 빈 분기 점은 고르지 않는다
        p0 = max((p for p in P if p.get("주가일") and p["주가일"] <= hi_d and p.get("n") is not None), key=lambda p: p["n"], default=None)
        if p0 is not None:
            e0, e1 = ni4_at(p0), ni_now
            if e0 and e1 and e0 > 0 and e1 > 0:
                e_chg = (e1 / e0 - 1) * 100
            else:
                o0 = p0.get("영업이익_TTM")
                if o0 and op_now and o0 > 0 and op_now > 0:
                    e_chg = (op_now / o0 - 1) * 100
    if e_chg is not None and dd is not None:
        rerate = ((1 + dd / 100) / (1 + e_chg / 100) - 1) * 100
    add(5, "그 사이 이익은 버텼다(-5% 이내)", e_chg is not None and e_chg >= -5,
        "고점 무렵 대비 이익(4분기 합) %s" % ("%+.0f%%" % e_chg if e_chg is not None else "—"))
    add(5, "PER만 낮아졌다(고점 때보다 15%↑)", rerate is not None and rerate <= -15,
        ("주가 %+.0f%% · 이익 %+.0f%% → 같은 이익에 매긴 값(PER) %+.0f%%" % (dd, e_chg, rerate)) if rerate is not None else "—", hard=False)
    m_ret = _grp_ret(idx, "__all__", hi_d, last) if hi_d else None
    ind = ind_of.get(code) or r.get("industry")
    i_ret = _grp_ret(idx, ind, hi_d, last, skip=code) if hi_d else None
    macro = (m_ret is not None and m_ret <= -8) or (i_ret is not None and i_ret <= -10)
    worse = dd is not None and min(x for x in (m_ret, i_ret, 0) if x is not None) - dd > 25
    add(5, "시장·업종도 함께 빠졌다(매크로·심리)", macro,
        "같은 기간 시장 %s · 업종(%s) %s" % ("%+.0f%%" % m_ret if m_ret is not None else "—", ind or "—", "%+.0f%%" % i_ret if i_ret is not None else "—"), hard=False)
    add(5, "업종보다 25%p 넘게 더 빠지진 않았다", not worse,
        "이 회사 %s vs 시장·업종 중 약한 쪽 %s" % ("%+.0f%%" % dd if dd is not None else "—",
                                          "%+.0f%%" % min(x for x in (m_ret, i_ret) if x is not None) if (m_ret is not None or i_ret is not None) else "—"), hard=False)
    info.update(dd=dd, hi_d=hi_d, e_chg=e_chg, rerate=rerate, m_ret=m_ret, i_ret=i_ret, events=evs, macro=macro, worse=worse,
                op_now=op_now, ni_now=ni_now, nd_eq=nd_eq, cfo3=cfo3, ar_up=ar_up)
    return chk, info


def _run_dip():
    try:
        with DIP_LOCK:
            DIP["phase"] = "수주잔고·시너지 자료 기다리는 중"
        synergy_view()
        while True:
            with SYNERGY_LOCK:
                if not SYNERGY["running"] and SYNERGY["rows"]:
                    srows = list(SYNERGY["rows"])
                    break
                ph = SYNERGY.get("phase") or ""
            with DIP_LOCK:
                DIP["phase"] = "시너지 계산 중 — " + ph
            time.sleep(3)
        with BACKLOG_LOCK:
            trends = {b["code"]: b["trend"] for b in BACKLOG["rows"]}
        with DIP_LOCK:
            DIP["phase"] = "시장·업종 지수 만드는 중"
        idx, ind_of = _dip_index()
        with DIP_LOCK:
            DIP.update(phase="회사별 여섯 관문", total=len(srows), done=0)
        funnel = {"all": len(srows), 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        rows, drop = [], []
        for i, r in enumerate(srows, 1):
            with DIP_LOCK:
                DIP["done"] = i
            try:
                tr = trends.get(r["code"])
                # 값싼 관문부터 — 잔고가 안 늘면 공시·지수까지 갈 필요가 없다
                yoy = r.get("backlog_yoy")
                if not (r.get("reliable") and ((tr and tr.get("steady")) or (yoy is not None and yoy >= 15))):
                    continue
                chk, info = _dip_company(r, tr, idx, ind_of)
                passed = 0
                for g in (1, 2, 3, 4):
                    if all(x["ok"] for x in chk if x["gate"] == g and x["hard"]):
                        passed = g
                    else:
                        break
                for g in range(1, passed + 1):
                    funnel[g] += 1
                hold5 = passed == 4 and next((x["ok"] for x in chk if x["name"].startswith("그 사이 이익")), False)
                if hold5:
                    funnel[5] += 1
                row = {"code": r["code"], "name": r["name"], "industry": r.get("industry"), "sector": r.get("sector"),
                       "market": r.get("market"), "cap": r.get("cap"), "backlog": r.get("backlog"), "backlog_yoy": yoy,
                       "btb": r.get("btb"), "cover": r.get("cover"), "rev_yoy": r.get("rev_yoy"), "margin": r.get("margin"),
                       "margin_delta": r.get("margin_delta"), "per": r.get("per"), "spark": r.get("spark"),
                       "checks": chk, "passed": passed, "hold": hold5,
                       **{k: info.get(k) for k in ("dd", "hi_d", "e_chg", "rerate", "m_ret", "i_ret", "macro", "worse",
                                                   "op_now", "ni_now", "nd_eq", "cfo3", "ar_up")},
                       "events": info.get("events", [])[:8]}
                if hold5:
                    row["pct"] = None
                    _dip_rank(row)
                    rows.append(row)
                else:
                    fail = next((x for x in chk if not x["ok"] and x["hard"]), None)
                    if passed >= 1:                     # 잔고는 느는데 막힌 곳 — 왜 막혔는지가 곧 공부거리다
                        row["fail"] = fail
                        row["n_fail"] = sum(1 for x in chk if not x["ok"] and x["hard"])
                        drop.append(row)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print("억울한 낙폭 %s 실패: %s" % (r.get("code"), e), flush=True)
            _dip_publish(rows, drop, funnel)
        # ⑥ 싸다 — 풍경 탭과 같은 자기 역사 PER 위치(분할 보정). 처음 만드는 풍경은 한 곳에 1분 가까이 걸려 셋씩 나란히 돌린다
        pend, live, done = list(rows), {}, 0
        with DIP_LOCK:
            DIP.update(phase="⑥ 싸다 — PER 자기 역사 위치", total=len(pend), done=0)
        while pend or live:
            while pend and len(live) < 3:
                row = pend.pop(0)
                live[row["code"]] = (row, time.time())
            for code, (row, t0) in list(live.items()):
                try:
                    lv = landscape_view(code, stale_ok=False)     # 지난 판(어제 주가)이 아니라 오늘 판을 기다린다 — 셋씩만 돌게
                except Exception:
                    lv = None
                if lv and lv.get("pending") and time.time() - t0 < 150:
                    continue
                dc = (lv or {}).get("decide") or {}
                row.update(pct=dc.get("pct"), per_now=dc.get("per"), px=dc.get("px"), ltype=dc.get("type"))
                _dip_rank(row)
                del live[code]
                done += 1
            with DIP_LOCK:
                DIP["done"] = done
            _dip_publish(rows, drop, funnel)
            if pend or live:
                time.sleep(1.5)
        _dip_publish(rows, drop, funnel)
        with DIP_LOCK:
            DIP.update(at=time.time(), phase="")
            snap = {k: DIP.get(k) for k in ("at", "rows", "drop", "funnel")}
        try:
            with open(os.path.join(DIP_DIR, "_result.json"), "w", encoding="utf-8") as fh:
                json.dump(dict(snap, v=DIP_V), fh, ensure_ascii=False)
        except Exception:
            pass
    finally:
        with DIP_LOCK:
            DIP["running"] = False


DIP_SCORE_MIN = 50   # 억울 등급 = 빨간불 없음 + 새 점수 50↑ — 과거 후보 안 +12.4%p [3.1, 21.7], 앞 +11.6 · 뒤 +15.6(도구/억울_새점수.py, 잔고 1년 비교 고친 뒤)
DIP_PRICEY = 80      # 자기 15년 PER 중 상위 20% 안이면 아직 비싸다 — 거품이 빠지는 중일 수 있다


def _dip_forward(code):
    """앞으로의 매출이 버티나 — 분기 변화 파이프라인의 마지막 분기 값(잔고 · 선수금 vs 매출, 업황). 없으면 None."""
    c = company_by_code(code)
    corp = corp_code_of(code) if c and FIN is not None else None
    if not corp:
        return None
    try:
        mi = matrix_cached(c, corp, "IS", "q", IS_YEARS)
        mb = matrix_cached(c, corp, "BS", "q", QTR_YEARS)
        mc = matrix_cached(c, corp, "CF", "q", QTR_YEARS)
        macro = MACRO.for_company(corp, FIN.API_KEY) if MACRO is not None else None
        pr = _pipe_rows(c, mi, mb, mc, macro=macro)
    except Exception:
        return None
    if not pr:
        return None
    lab = pr["labs"][-1]
    r = pr["rows"][lab]
    ry = r.get("rev_yoy")
    g = lambda k: (r[k] - ry) if r.get(k) is not None and ry is not None else None
    bg, lg = g("blog_yoy"), g("liab_yoy")
    red = []
    if bg is not None and bg <= -15:
        red.append("잔고가 매출보다 %.0f%%p 느리다" % -bg)
    if lg is not None and lg <= -15:
        red.append("선수금(계약부채)이 매출보다 %.0f%%p 느리다" % -lg)
    if r.get("mp_yoy") is not None and r["mp_yoy"] <= -10:
        red.append("업종 제품 가격(수출물가) %+.0f%%" % r["mp_yoy"])
    if r.get("cyc") is not None and ry is not None and r["cyc"] <= -10 and ry > 5:
        red.append("업종에 재고가 쌓이는데(재고 순환 %+.0f%%p) 회사 매출은 아직 %+.0f%%" % (r["cyc"], ry))
    strong = None if bg is None and lg is None else ((bg or -1e9) >= 15 or (lg or -1e9) >= 15)
    return {"lab": lab, "rev_yoy": ry, "blog_gap": bg, "liab_gap": lg, "cyc": r.get("cyc"), "mp_yoy": r.get("mp_yoy"),
            "strong": strong, "red": red}


def _dip_rank(row):
    """등급과 점수. 억울 = 앞단(잔고 또는 선수금)이 매출보다 +15%p↑ 빠르고, 빨간불(앞단 약함 · 업종 가격 하락 · 업종 재고 쌓임)이 없다.
    2026-10-02 재점검(도구/억울_재점검.py): 예전 등급(시장 · 업종 동반 · 혼자 더 안 빠짐 · 안 비쌈)은 후보 안에서 12개월 초과수익을
    오히려 −8.6%p 깎았다. 새 등급은 후보 안 +13.2%p, 넓은 표본 +12.3%p [6.7, 18.5] — 다만 대부분 2020년 뒤(앞 기간은 차이 없음).
    시장 · 업종 동반 · PER 자기 역사는 등급에서 빼고 참고로만 적는다."""
    f = _dip_forward(row["code"])
    row["fwd"] = f
    _dip_score(row)
    why = []
    if f is None:
        why.append("앞단 · 업황을 아직 못 읽었다 — 분기 재무를 받는 중이거나 없다")
    else:
        why += ["빨간불: " + x for x in f["red"]]
    if row.get("score") is None:
        why.append("점수를 낼 항목이 모자란다")
    elif row["score"] < DIP_SCORE_MIN and _dip_v2():
        why.append("새 점수 %.1f — %d 미만(업종 가격 · 북투빌 · 낙폭 · 이익률로 본 순서가 아래쪽)" % (row["score"], DIP_SCORE_MIN))
    notes = []
    if not row.get("macro"):
        notes.append("시장·업종은 크게 안 빠졌다(참고)")
    if row.get("worse"):
        notes.append("시장·업종보다 25%p 넘게 더 빠졌다(참고)")
    if row.get("pct") is not None and row["pct"] >= DIP_PRICEY:
        notes.append("PER이 자기 역사 상위 %d%%(참고)" % max(1, round(100 - row["pct"])))
    row["tier"] = "관찰" if why else "억울"
    row["tier_why"] = why
    row["tier_notes"] = notes


_DIP_BT = {"mt": None, "d": None}


def _dip_bt():
    """도구/억울_백테스트.py 가 남긴 검증 결과(항목·가중치·과거 후보 분포). 파일이 바뀌면 다시 읽는다."""
    p = os.path.join(DIP_DIR, "bt_report.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _DIP_BT["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _DIP_BT["d"] = json.load(fh)
            _DIP_BT["mt"] = mt
        except Exception:
            return None
    return _DIP_BT["d"]


def _dip_score(row):
    """점수 = 과거 '억울한 낙폭 후보'(2013~2025 매달) 안에서 이 회사 값이 어디쯤인지(백분위)의 가중평균, 0~100.
    항목과 가중치는 백테스트가 정한다 — 앞뒤 기간에서 방향이 같고 회사 단위 부트스트랩 구간이 대체로 0을 비켜 간 것만."""
    v2 = _dip_v2()
    if v2 and v2.get("weights"):
        return _dip_score_v2(row, v2)
    bt = _dip_bt()
    sc = (bt or {}).get("score") or {}
    if not sc.get("weights"):
        row.update(score=None, score_parts=[], score_note="백테스트 결과가 없어 점수를 매기지 않았다 — python 도구/억울_백테스트.py")
        return
    import bisect
    val = {"btb": row.get("btb"), "ind": row.get("i_ret") if row.get("i_ret") is not None else row.get("m_ret"),
           "dd": row.get("dd"), "cover": row.get("cover"), "nd_eq": row.get("nd_eq")}
    fmt = {"btb": lambda v: "%.2f" % v, "ind": lambda v: "%+.0f%%" % v, "dd": lambda v: "%+.0f%%" % v,
           "cover": lambda v: "%.1f년치" % v, "nd_eq": lambda v: "%.0f%%" % v}
    parts, tot, wsum = [], 0.0, 0.0
    for w in sc["weights"]:
        sv, v = sc["dist"].get(w["key"]) or [], val.get(w["key"])
        if v is None or not sv:
            continue
        p = (bisect.bisect_left(sv, v) + bisect.bisect_right(sv, v)) / 2 / len(sv) * 100
        good = p if w["dir"] > 0 else 100 - p
        parts.append({"key": w["key"], "label": w["name"], "w": w["w"], "good": good,
                      "val": "%s · 과거 후보 중 상위 %d%%" % (fmt.get(w["key"], str)(v), max(1, round(100 - good)))})
        tot += good * w["w"]
        wsum += w["w"]
    for x in parts:
        x["pts"] = round(x["good"] * x["w"] / wsum, 1)
    row["score"] = round(tot / wsum, 1) if wsum else None
    row["score_parts"] = parts
    n, ev, oos = bt.get("n_dip"), sc.get("new") or {}, sc.get("oos") or {}
    row["score_note"] = ("과거 억울한 낙폭 후보 %s건(%s~%s 매달, 주주가치 관문 제외)과 비교한 백분위의 가중평균. "
                         "그 기간 점수 상위⅓의 12개월 초과수익 중앙값 %+.0f%%, 하위⅓ %+.0f%%. "
                         "다만 표본이 %s곳뿐이고, 앞 기간 분포로 뒤 기간을 재면 차이가 %+.0f%%p로 줄어든다 — 순서를 정하는 참고일 뿐이다."
                         % (n, (bt.get("dates") or ["", ""])[0][:6], (bt.get("dates") or ["", ""])[1][:6],
                            ev.get("top") or 0, ev.get("bot") or 0, ev.get("firms"), oos.get("spread") or 0))


_DIP_V2 = {"mt": None, "d": None}


def _dip_v2():
    """도구/억울_새점수.py 가 남긴 새 점수(항목 · 가중치 · 과거 후보 분포 · 검증). 없으면 None — 예전 점수로."""
    p = os.path.join(DIP_DIR, "score_v2.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _DIP_V2["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _DIP_V2.update(d=json.load(fh), mt=mt)
        except Exception:
            return None
    return _DIP_V2["d"]


def _dip_score_v2(row, v2):
    """새 점수(2026-10-03) = 과거 억울한 낙폭 후보 안 백분위의 가중평균 — 업종 제품 가격 · 북투빌 · 낙폭(깊을수록) · 영업이익률(낮을수록) 1,
    잔고 − 매출 간극 · 업종 재고 순환 0.5. 가중치는 맞추지 않고 정했다. 과거 후보 위⅓ − 아래⅓ 12개월 초과수익 +20.8%p [14.4, 33.2] ·
    앞 기간 +20.3 · 뒤 +29.4(예전 점수 +7.0, 뒤 기간 −7.2). 요인을 같은 표본에서 골라 실제보다 좋아 보인다."""
    import bisect
    f = row.get("fwd") or {}
    val = {"mp": f.get("mp_yoy"), "btb": row.get("btb"), "dd": row.get("dd"), "margin": row.get("margin"),
           "bgap": f.get("blog_gap"), "cyc": f.get("cyc")}
    fmt = {"mp": lambda v: "%+.0f%%" % v, "btb": lambda v: "%.2f" % v, "dd": lambda v: "%+.0f%%" % v,
           "margin": lambda v: "%.1f%%" % v, "bgap": lambda v: "%+.0f%%p" % v, "cyc": lambda v: "%+.0f%%p" % v}
    parts, tot, wsum = [], 0.0, 0.0
    for w in v2["weights"]:
        sv, v = v2["dist"].get(w["key"]) or [], val.get(w["key"])
        if v is None or not sv:
            continue
        p = (bisect.bisect_left(sv, v) + bisect.bisect_right(sv, v)) / 2 / len(sv) * 100
        good = p if w["dir"] > 0 else 100 - p
        parts.append({"key": w["key"], "label": w["name"], "w": w["w"], "good": good,
                      "val": "%s · 과거 후보 중 %s %d%%" % (fmt.get(w["key"], str)(v), "좋은 쪽 상위", max(1, round(100 - good)))})
        tot += good * w["w"]
        wsum += w["w"]
    for x in parts:
        x["pts"] = round((x["good"] - 50) * x["w"] / wsum, 1) if wsum else 0     # 50 에서 얼마나 밀고 당겼나 — 합 + 50 = 점수
    row["score"] = round(tot / wsum, 1) if wsum >= 2 else None
    row["score_parts"] = parts
    ev = ((v2.get("eval") or {}).get("후보") or {}).get("새 점수") or {}
    row["score_note"] = ("과거 억울한 낙폭 후보 %s건(%s곳, %s~%s 매달)과 비교한 백분위의 가중평균. 업종 제품 가격 · 북투빌 · 낙폭(깊을수록) · "
                         "영업이익률(낮을수록) 1, 잔고 − 매출 간극 · 업종 재고 순환 0.5. 과거 위⅓ 12개월 초과수익 중앙값 %+.0f%%, 아래⅓ %+.0f%% "
                         "(위 − 아래: ~2019 %+.0f%%p · 2020~ %+.0f%%p). 요인을 같은 표본에서 골라 실제보다 좋아 보인다 — 순서를 정하는 참고."
                         % (v2.get("n_cand"), v2.get("firms"), (v2.get("dates") or ["", ""])[0][:6], (v2.get("dates") or ["", ""])[1][:6],
                            ev.get("top") or 0, ev.get("bot") or 0, ev.get("early") or 0, ev.get("late") or 0))


def _dip_publish(rows, drop, funnel):
    """계산하는 대로 화면에 보이게 — 정렬한 사본을 내건다."""
    rs = sorted(rows, key=lambda x: (x["tier"] == "억울", x["score"] if x.get("score") is not None else -1), reverse=True)
    ds = sorted(drop, key=lambda x: (-(x["fail"]["gate"] if x.get("fail") else 0), -(x.get("backlog_yoy") or 0)))[:80]
    with DIP_LOCK:
        DIP.update(rows=rs, drop=ds, funnel=dict(funnel))


def dip_view(force=False):
    with DIP_LOCK:
        if not DIP["at"] and not DIP["running"]:
            try:        # 뷰어를 다시 켜도 지난 결과를 바로 보여 준다
                with open(os.path.join(DIP_DIR, "_result.json"), "r", encoding="utf-8") as fh:
                    old = json.load(fh)
                if old.get("v") == DIP_V:
                    DIP.update({k: old.get(k) for k in ("at", "rows", "drop", "funnel")})
            except Exception:
                pass
        stale = force or (not DIP["rows"] and not DIP["at"]) or time.time() - DIP["at"] > 6 * 3600
        if stale and not DIP["running"] and SYN is not None and BACK is not None:
            DIP["running"] = True
            threading.Thread(target=_run_dip, daemon=True).start()
        out = {k: DIP.get(k) for k in ("running", "done", "total", "phase", "at", "rows", "drop", "funnel")}
    bt = _dip_bt() or {}
    if bt.get("score"):       # 화면의 '과거 검증' 상자 — 분포 배열은 빼고 요약만
        out["bt"] = {"dates": bt.get("dates"), "n_dip": bt.get("n_dip"), "tiers": bt.get("tiers"), "groups": bt.get("groups"),
                     "score": {k: v for k, v in bt["score"].items() if k != "dist"}, "factors": bt.get("factors_g2"), "at": bt.get("at")}
    v2 = _dip_v2()
    if v2 and out.get("bt"):  # 새 점수 · 새 등급 검증(도구/억울_새점수.py)
        out["bt"]["v2"] = {"eval": v2.get("eval"), "n_cand": v2.get("n_cand"), "firms": v2.get("firms"),
                           "weights": v2.get("weights")}
    return out


# ---------------------------------------------------------------- 저평가: 가치는 지켰는데 주가가 빠진 회사 (2026-10-03)
# 전 종목(수집한 회사 전부)에서 — 4분기 순이익 흑자 · 순이익 1년 −5% 이내(가치는 지켰다) · 52주 고점 대비 −25%↓(주가는 빠졌다).
# 그 안에서 과거에 되돌아온 쪽을 가른 항목으로 점수를 매기고(도구/저평가_백테스트.py → .cache/value/score.json),
# 억울한 낙폭과 같은 빨간불(앞단 약함 · 업종 가격 하락 · 업종 재고 쌓임) · 부채비율 200%↑가 없고 점수 50↑이면 '저평가', 아니면 '관찰'.
# 검증(2014~2025 공시일 · 후보 1,966건 · 498곳): 점수 위⅓ − 아래⅓ +13.6%p [9.3, 17.7] 앞 +15.4 · 뒤 +12.7,
# 등급 저평가 − 관찰 +10.0%p [6.4, 13.8] 앞 +12.4 · 뒤 +9.3. 후보 자체는 시장 수준(+0.9%) — 가르는 건 점수다.
VAL_V = 1
VAL_DIR = os.path.join(CACHE_DIR, "value")
VAL_DD = -25          # 52주 고점 대비 이만큼 빠져야 후보
VAL_NI = -5           # 순이익(최근 4분기) 1년 변화가 이 위면 '가치는 지켰다'
VAL_MIN = 50          # 저평가 = 빨간불 없음 + 점수 50↑
VAL_PER_MAX = 200     # PER 200배 넘으면 이익이 거의 0 — 값의 기준이 못 된다(엘브이엠씨 15,067배)
# 금융업 — 예수금 · 차입이 사업 자체라 부채비율 200% 잣대와 매출 계정이 맞지 않고, 과거 후보 표본에 1.6%뿐이라 검증 근거가 없다(2026-10-05 감사)
VAL_FIN = re.compile(r"은행|증권|보험|생명|화재|카드|캐피탈|기타금융|창업투자|신탁")
# 업종 수출물가가 이 회사 제품과 맞지 않는 곳 — 업종코드로 붙인 반도체 지수(메모리 비중 큼)가 IP · 태양광 · LED · 파운드리 회사에도 붙었다
VAL_MP_SKIP = {"094360": "반도체 IP(라이선스)", "322000": "태양광", "017900": "광센서 · LED", "092190": "UV LED",
               "000990": "파운드리(비메모리)", "200710": "반도체 설계 서비스"}
VAL = {"running": False, "done": 0, "total": 0, "phase": "", "at": 0, "rows": [], "n_fell": 0, "n_univ": 0}
VAL_LOCK = threading.Lock()
_VAL_SC = {"mt": None, "d": None}
# 점수 항목 값 — 도구/저평가_백테스트.py 의 FACT 와 같은 변환
VAL_FX = {
    "per_pct": lambda r: r.get("per_pct"), "per": lambda r: r.get("per"), "peg": lambda r: r.get("peg"),
    "comp": lambda r: r.get("comp"), "dd": lambda r: r.get("dd"), "px_yoy": lambda r: r.get("px_yoy"),
    "ret3m": lambda r: r.get("ret3m"), "ret1m": lambda r: r.get("ret1m"),
    "ni_yoy": lambda r: min(r["ni_yoy"], 300) if r.get("ni_yoy") is not None else None,
    "eps_yoy": lambda r: min(r["eps_yoy"], 300) if r.get("eps_yoy") is not None else None,
    "rev_yoy": lambda r: r.get("rev_yoy"), "opm": lambda r: r.get("opm"), "opm_pct": lambda r: r.get("opm_pct"),
    "roe": lambda r: r.get("roe"), "roe_chg": lambda r: r.get("roe_chg"), "debt_eq": lambda r: r.get("debt_eq"),
    "cfo_ni": lambda r: max(min(r["cfo_ni"], 5), -5) if r.get("cfo_ni") is not None else None,
    "mp_yoy": lambda r: r.get("mp_yoy"), "cyc": lambda r: r.get("cyc"),
    "bgap": lambda r: r.get("bgap"), "lgap": lambda r: r.get("lgap"), "wgap": lambda r: r.get("wgap"),
    "capex_yoy": lambda r: min(r["capex_yoy"], 300) if r.get("capex_yoy") is not None else None,
}
VAL_FMT = {"per_pct": "자기 역사 %.0f%%", "per": "%.1f배", "peg": "%.2f", "comp": "%+.0f%%", "dd": "%+.0f%%", "px_yoy": "%+.0f%%",
           "ret3m": "%+.0f%%", "ret1m": "%+.0f%%", "ni_yoy": "%+.0f%%", "eps_yoy": "%+.0f%%", "rev_yoy": "%+.0f%%", "opm": "%.1f%%",
           "opm_pct": "자기 역사 %.0f%%", "roe": "%.1f%%", "roe_chg": "%+.1f%%p", "debt_eq": "%.0f%%", "cfo_ni": "%.1f배",
           "mp_yoy": "%+.0f%%", "cyc": "%+.0f%%p", "bgap": "%+.0f%%p", "lgap": "%+.0f%%p", "wgap": "%+.0f%%p", "capex_yoy": "%+.0f%%"}


def _val_score_spec():
    p = os.path.join(VAL_DIR, "score.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _VAL_SC["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _VAL_SC.update(d=json.load(fh), mt=mt)
        except Exception:
            return None
    return _VAL_SC["d"]


def _val_one(c):
    """한 회사 — 주가가 25%↓ 빠졌고 이익을 지켰으면 지금 값들을, 아니면 None."""
    code = c["code"]
    corp = corp_code_of(code) if FIN is not None else None
    if not corp:
        return None
    px = _inv_prices(code) or {}
    if not px.get("p"):
        return None
    import bisect
    d, p = px["d"], px["p"]
    now, i = p[-1], len(p) - 1
    lo = bisect.bisect_left(d, int((dt.datetime.strptime(str(d[-1]), "%Y%m%d") - dt.timedelta(days=365)).strftime("%Y%m%d")))
    hi_i = max(range(lo, i + 1), key=lambda k: p[k]) if i >= lo else None
    if hi_i is None or not p[hi_i]:
        return {"fell": False}
    dd = (now / p[hi_i] - 1) * 100
    if dd > VAL_DD:
        return {"fell": False}

    def back(days):
        t = int((dt.datetime.strptime(str(d[-1]), "%Y%m%d") - dt.timedelta(days=days)).strftime("%Y%m%d"))
        k = bisect.bisect_right(d, t) - 1
        return (now / p[k] - 1) * 100 if k >= 0 and p[k] else None
    try:
        mi = matrix_cached(c, corp, "IS", "q", IS_YEARS)
        mb = matrix_cached(c, corp, "BS", "q", QTR_YEARS)
        mc = matrix_cached(c, corp, "CF", "q", QTR_YEARS)
        try:
            blog_pts = BACK.company_series(c, read_section, max_reports=12) if BACK is not None else []
        except Exception:
            blog_pts = []
        macro = None
        if MACRO is not None:
            try:
                macro = MACRO.for_company(corp, FIN.API_KEY)
            except Exception:
                macro = None
        pr = _pipe_rows(c, mi, mb, mc, px=px, blog_pts=blog_pts, macro=macro)
    except Exception:
        return {"fell": True}
    if not pr:
        return {"fell": True}
    R = pr["rows"]
    # 기준 분기 = 마지막으로 보고된 분기(또는 그 앞 하나) — 더 옛 분기로 물러나 '지금' 값을 계산하지 않는다(2026-10-05 감사)
    lab = next((l for l in reversed(pr["labs"][-2:]) if R[l].get("ni_ttm") is not None and R[l].get("eps_ttm") is not None), None)
    if not lab:
        return {"fell": True, "stale": pr["labs"][-1]}
    x = R[lab]
    et, ni, ry = x.get("eps_ttm"), x.get("ni_ttm"), x.get("rev_yoy")
    per = now / et if et and et > 0 else None
    w = (pr.get("hist_per") or [])[-40:]
    g = lambda k: (x[k] - ry) if x.get(k) is not None and ry is not None else None
    rev, op, cfo, eqt, debt = x.get("rev_ttm"), x.get("op_ttm"), x.get("cfo_ttm"), x.get("eq_total"), x.get("debt")
    pyoy = back(365)
    nyoy = x.get("ni_yoy")
    eyoy = x.get("eps_yoy")
    # 1년 전 4분기 합 순이익(· 주당순이익)이 0 이하면 'PER 이 몇 % 바뀌었다'가 성립하지 않는다(적자 → 흑자를 +339% 로 읽으면 PER −83% 같은 엉터리) — comp · per_then 을 비운다
    ni_ly = (R.get(_qshift(lab, 4)) or {}).get("ni_ttm")
    et_ly = x.get("eps_ttm_ly")
    base_ok = not (ni_ly is not None and ni_ly <= 0) and not (et_ly is not None and et_ly <= 0)
    mp_skip = VAL_MP_SKIP.get(code)
    r = {"fell": True, "code": code, "name": c["name"], "lab": lab, "price": now, "price_d": str(d[-1]),
         "hi": p[hi_i], "hi_d": str(d[hi_i]), "dd": dd, "px_yoy": pyoy, "ret3m": back(91), "ret1m": back(30),
         "per": per, "per_pct": (sum(1 for v in w if v <= per) / len(w) * 100) if per and len(w) >= 8 else None,
         "per_med": sorted(w)[len(w) // 2] if len(w) >= 8 else None,
         "peg": per / min(max(nyoy, 1.0), 100.0) if per and nyoy is not None and nyoy > 0 else None,
         "ni4": ni, "ni_yoy": nyoy, "eps_yoy": x.get("eps_yoy"), "rev_yoy": ry, "rev4": rev, "op4": op,
         "opm": op / rev * 100 if (rev and op is not None and rev > 0) else None, "opm_pct": x.get("opm_pct"),
         "roe": x.get("roe"), "roe_chg": x.get("roe_chg"),
         "debt_eq": debt / eqt * 100 if (debt is not None and eqt and eqt > 0) else None,
         "cfo_ni": cfo / ni if (cfo is not None and ni and ni > 0) else None,
         "mp_yoy": None if mp_skip else x.get("mp_yoy"), "cyc": None if mp_skip else x.get("cyc"), "mp_skip": mp_skip,
         "bgap": g("blog_yoy"), "lgap": g("liab_yoy"), "wgap": g("wip_yoy"),
         "capex_yoy": x.get("capex_yoy"),
         "ni_ly": ni_ly,
         # PER 변화 = (1 + 주가 1년) ÷ (1 + 주당순이익 1년) − 1 — PER 이 주가 ÷ EPS 라 주당 기준이 맞다(예전엔 순이익 기준이라 주식 수가 바뀐 회사에서
         # 가위 그림 · 문장(주당 기준)과 판정 알약이 반대 말을 했다 — 미래산업 · 코오롱인더)
         "comp": ((1 + pyoy / 100) / (1 + eyoy / 100) - 1) * 100 if (base_ok and pyoy is not None and eyoy is not None and eyoy > -100) else None}
    r["cand"] = bool(per and per <= VAL_PER_MAX and nyoy is not None and nyoy >= VAL_NI)
    if r["cand"]:
        # 그림 재료(점수에는 안 쓴다) — 분기별 PER 최근 10년(per_pct 와 같은 창) · 최근 9분기 EPS(4분기 합) · 최근 1년 주가(주 단위)
        labs = pr["labs"]
        r["per_hist"] = [[l, round(R[l]["per"], 2)] for l in labs if R[l].get("per") and R[l]["per"] > 0 and R[l].get("per_ok")][-40:]
        r["eps_q"] = [[l, R[l]["eps_ttm"]] for l in labs[-9:] if R[l].get("eps_ttm") is not None]
        t0 = int((dt.datetime.strptime(str(d[-1]), "%Y%m%d") - dt.timedelta(days=372)).strftime("%Y%m%d"))
        k0 = max(0, bisect.bisect_left(d, t0) - 1)
        r["px_w"] = [[str(d[k]), p[k]] for k in list(range(k0, i, 5)) + [i]]
    return r


def _val_red(r):
    out = []
    if r.get("bgap") is not None and r["bgap"] <= -15:
        out.append("잔고가 매출보다 %.0f%%p 느리다" % -r["bgap"])
    if r.get("lgap") is not None and r["lgap"] <= -15:
        out.append("선수금(계약부채)이 매출보다 %.0f%%p 느리다" % -r["lgap"])
    if r.get("mp_yoy") is not None and r["mp_yoy"] <= -10:
        out.append("업종 제품 가격(수출물가) %+.0f%%" % r["mp_yoy"])
    if r.get("cyc") is not None and r.get("rev_yoy") is not None and r["cyc"] <= -10 and r["rev_yoy"] > 5:
        out.append("업종에 재고가 쌓이는데(재고 순환 %+.0f%%p) 회사 매출은 아직 %+.0f%%" % (r["cyc"], r["rev_yoy"]))
    # 빚 — 과거 후보 안에서 부채비율 200%↑는 12개월 초과수익 −6.7%p [−11.5, −0.2], 앞뒤 모두 음(도구/저평가_백테스트.py). 금융업은 이 잣대가 맞지 않아 뺀다
    if r.get("debt_eq") is not None and r["debt_eq"] >= 200 and not r.get("fin"):
        out.append("부채비율 %.0f%% — 200%% 넘는 빚" % r["debt_eq"])
    return out


def _val_rank(r, spec):
    import bisect
    parts, tot, wsum = [], 0.0, 0.0
    r["fin"] = bool(VAL_FIN.search(r.get("industry") or ""))
    for wt in (spec or {}).get("weights") or []:
        k = wt["key"]
        if r["fin"] and k in ("debt_eq", "rev_yoy"):
            continue
        sv, v = spec["dist"].get(k) or [], VAL_FX[k](r) if k in VAL_FX else None
        if v is None or not sv:
            continue
        pc = (bisect.bisect_left(sv, v) + bisect.bisect_right(sv, v)) / 2 / len(sv) * 100
        good = pc if wt["dir"] > 0 else 100 - pc
        parts.append({"key": k, "label": wt["name"], "w": wt["w"], "good": good,
                      "val": "%s · 과거 후보 중 좋은 쪽 상위 %d%%" % (VAL_FMT.get(k, "%s") % v, max(1, round(100 - good)))})
        tot += good * wt["w"]
        wsum += wt["w"]
    for x in parts:
        x["pts"] = round((x["good"] - 50) * x["w"] / wsum, 1) if wsum else 0
    r["score"] = round(tot / wsum, 1) if wsum >= 2 else None
    r["score_parts"] = parts
    r["red"] = _val_red(r)
    why = list("빨간불: " + x for x in r["red"])
    if r["fin"]:
        why.append("금융업 — 부채비율 · 매출 잣대가 맞지 않고 과거 검증 표본에 거의 없어 등급을 내지 않는다")
    if r["score"] is None:
        why.append("점수를 낼 항목이 모자란다")
    elif r["score"] < VAL_MIN:
        why.append("점수 %.1f — %d 미만" % (r["score"], VAL_MIN))
    if r.get("per_pct") is None and r.get("px_yoy") is None:
        why.append("값을 잴 항목(PER 자기 역사 · 주가 1년)이 없다 — 상장 1년 미만 등")
    r["tier"] = "관찰" if why else "저평가"
    r["tier_why"] = why
    # PER 고점 → 지금 — 1년 전 PER = 지금 PER ÷ (1 + PER 변화)
    r["per_then"] = r["per"] / (1 + r["comp"] / 100) if (r.get("per") and r.get("comp") is not None and r["comp"] > -100) else None


def _run_value():
    try:
        cos = list(INDEX["companies"])
        if not cos:                       # 켜진 직후 색인이 아직 없다 — 빈 결과로 지난 결과를 덮어쓰지 않는다
            with VAL_LOCK:
                VAL["phase"] = "색인을 읽는 중 — 잠시 뒤 다시 계산"
            return
        with VAL_LOCK:
            VAL.update(done=0, total=len(cos), phase="전 종목 주가 · 재무 읽는 중")
        rows, fell = [], 0
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_val_one, c): c for c in cos}
            for k, f in enumerate(as_completed(futs), 1):
                try:
                    r = f.result()
                except Exception:
                    r = None
                if r and r.get("fell"):
                    fell += 1
                if r and r.get("cand"):
                    rows.append(r)
                with VAL_LOCK:
                    VAL["done"] = k
        spec = _val_score_spec()
        univ, _ = _universe_info()
        smap = (sector_map() or {}).get("stocks", {})
        for r in rows:
            u = univ.get(r["code"], {})
            r.update(cap_rank=u.get("rank"), market=u.get("market"),
                     industry=(smap.get(r["code"].upper(), {}) or {}).get("industry"))
            _val_rank(r, spec)          # 업종을 먼저 — 금융업 판정에 쓴다
        rows.sort(key=lambda r: (r["tier"] != "저평가", -(r.get("score") or -1)))
        with VAL_LOCK:
            VAL.update(rows=rows, n_fell=fell, n_univ=len(cos), at=time.time(), phase="")
        os.makedirs(VAL_DIR, exist_ok=True)
        with open(os.path.join(VAL_DIR, "_result.json"), "w", encoding="utf-8") as fh:
            json.dump({"v": VAL_V, "at": VAL["at"], "rows": rows, "n_fell": fell, "n_univ": len(cos)}, fh, ensure_ascii=False)
        # 실전 기록(2026-10-06~) — 그날의 저평가 · 관찰 목록을 남겨 두고 나중에 실제 수익률로 잰다(백테스트가 아닌 앞으로의 검증).
        # 같은 날은 덮어쓴다. 공시 위험으로 내린 등급까지 그대로(_val_apply_risk).
        try:
            fdir = os.path.join(VAL_DIR, "forward")
            os.makedirs(fdir, exist_ok=True)
            snap = [{k: r.get(k) for k in ("code", "name", "tier", "score", "price", "price_d", "per", "per_pct", "comp", "dd", "lab")} |
                    {"risk": (r.get("risk") or {}).get("level")} for r in _val_apply_risk(rows)]
            with open(os.path.join(fdir, dt.date.today().strftime("%Y%m%d") + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"at": VAL["at"], "score_spec": "score.json weights (2026-10-03, 6항목)", "rows": snap}, fh, ensure_ascii=False)
        except Exception as e:
            print("실전 기록 실패: %s" % e, flush=True)
        try:
            _val_export_tech(rows)
        except Exception as e:
            print("차트 발굴 내보내기 실패: %s" % e, flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        with VAL_LOCK:
            VAL["phase"] = "실패: %s" % e
    finally:
        with VAL_LOCK:
            VAL["running"] = False


# ---------------------------------------------------------------- 공시 위험(2026-10-06) — 도구/공시위험.py 가 공시 목록 캐시로 매일 센다(DART 호출 없음)
# 상폐 절차 · 보고서 없음 · 작전주 꼴(CB · BW · 유상증자 · 제3자배정 · 최대주주변경 잦음, 배당 없음)이면 저평가 등급을 주지 않는다.
# 근거: 2015~2018 로 고른 규칙을 2019~2024 표본 밖으로 — 상장사 8% 를 거르고 24개월 안 상장폐지 사슬의 64% 를 피함(README '공시 위험').
_DRISK = {"mt": None, "d": None}
DRISK_RED = ("상폐 절차", "보고서 없음", "작전주 꼴")


def _disc_risk():
    p = os.path.join(CACHE_DIR, "공시목록", "공시위험.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _DRISK["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _DRISK.update(d=json.load(fh), mt=mt)
        except Exception:
            return _DRISK["d"]
    return _DRISK["d"]


def _disc_refresh():
    """공시 목록(이번 해 분기만 — 끝난 분기는 건너뛴다) → 공시위험.json. 저평가 매일 계산 앞에 돈다."""
    import subprocess
    log = os.path.join(BASE, "공시위험_auto.log")
    y = dt.date.today().year
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("\n== %s\n" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        fh.flush()
        for cmd in ([sys.executable, os.path.join(BASE, "도구", "공시목록_수집.py"), "--from", str(y), "--max-calls", "3000"],
                    [sys.executable, os.path.join(BASE, "도구", "공시위험.py")]):
            try:
                subprocess.run(cmd, cwd=BASE, stdout=fh, stderr=subprocess.STDOUT, timeout=3 * 3600,
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            except Exception as e:
                fh.write("실패: %s\n" % e)


# 증권사(한국투자증권) 공식 종목 상태 — 차트 발굴(Tech) 스캔이 KIS 로 받아 남기는 스냅샷을 읽는다(이 서버는 32비트라 KIS 를 직접 부르지 않는다).
# 관리종목 · 거래정지 · 정리매매 · 투자위험이면 저평가 등급을 주지 않는다. 투자주의 · 투자경고 · 단기과열은 태그(kst)로 표시만.
# 스냅샷이 오래돼도(긴 연휴 · PC 꺼짐) 21일까지는 쓴다 — 관리 · 정지 지정은 보통 몇 달 가므로 묵은 상태로 내리는 편이
# 아무 확인 없이 '저평가'로 되돌리는 것보다 안전하다. 기준일 · 경과일은 화면(kis_meta)에 보인다.
_KSNAP = {"mt": None, "d": None}
KIS_SNAP_MAX_AGE = 21 * 86400
KIS_SNAP_WARN_DAYS = 5


def _kis_snapshot():
    p = os.path.join(TECH_DIR, "cache", "kis", "snapshot.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if time.time() - mt > KIS_SNAP_MAX_AGE:
        return None
    if _KSNAP["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _KSNAP.update(d=json.load(fh), mt=mt)
        except Exception:
            return _KSNAP["d"]
    return _KSNAP["d"]


def _kis_meta():
    """화면용 증권사 상태 스냅샷 정보 {date: 자료 기준일, at: 쓴 시각, age_days, old: 경고할 만큼 묵었나, n: 종목 수} 또는 None."""
    d = _kis_snapshot()
    if not d or not _KSNAP["mt"]:
        return None
    age = (time.time() - _KSNAP["mt"]) / 86400
    return {"date": d.get("date"), "at": d.get("at"), "age_days": round(age, 1), "old": age > KIS_SNAP_WARN_DAYS,
            "n": len(d.get("status") or {})}


def _kis_tags(st):
    """KIS 상태 한 종목(Tech 스냅샷 status[code] = {stat, tags, ex, marg, cap, …}) → (등급을 내릴 사유 목록, 표시 태그 목록).
    ex = Tech 의 스캔 제외 사유(거래정지 · 정리매매 · 관리종목 · 투자위험). 증거금 100%는 흔해서(전 종목 68%) 태그로 쓰지 않는다(옛 스냅샷에 있어도 뺀다)."""
    if not st:
        return [], []
    stat = str(st.get("stat") or "")
    tags = [t for t in (st.get("tags") or []) if t != "증거금100%"]
    bad = [st["ex"]] if st.get("ex") else []
    if not bad:                                   # 옛 스냅샷(ex 없음)이면 상태 코드로
        bad = [nm for code, nm in (("51", "관리종목"), ("58", "거래정지"), ("52", "투자위험")) if stat == code]
    return bad, list(dict.fromkeys(bad + tags))


def _val_apply_risk(rows):
    """행 복사본에 공시 위험 · 증권사 상태를 붙이고, 빨강 · 주황(공시)이거나 관리종목 · 거래정지 · 정리매매 · 투자위험(증권사)이면 저평가 → 관찰.
    보는 때마다 최신 공시위험.json · kis 스냅샷으로(계산 결과는 그대로 둔다)."""
    d = _disc_risk() or {}
    codes = d.get("codes") or {}
    ks = ((_kis_snapshot() or {}).get("status")) or {}
    out = []
    for r in rows:
        r = dict(r)
        rk = codes.get(r.get("code"))
        if rk:
            r["risk"] = {k: rk.get(k) for k in ("level", "group", "market", "proc", "last_a", "div", "hits", "ref")}
            if rk.get("level") in DRISK_RED and r.get("tier") == "저평가":
                r["tier"] = "관찰"
                what = " · ".join("%s %d날" % (h["name"], h["days"]) for h in rk.get("hits") or [])
                r["tier_why"] = list(r.get("tier_why") or []) + ["공시 위험: " + rk["level"] + ((" — " + what) if what else "")]
        bad, tags = _kis_tags(ks.get(r.get("code")))
        if tags:
            r["kst"] = tags
        if bad and r.get("tier") == "저평가":
            r["tier"] = "관찰"
            r["tier_why"] = list(r.get("tier_why") or []) + ["증권사 상태: " + " · ".join(bad)]
        out.append(r)
    out.sort(key=lambda r: (r.get("tier") != "저평가", -(r.get("score") or -1)))
    return out


VAL_TECH_EXPORT = os.path.join(VAL_DIR, "tech_export.json")


def _val_export_tech(rows=None):
    """차트 발굴(Tech) 리포트의 '저평가 종목' 칩 · 탭이 읽는 목록(Tech 의 CHART_SCREENER_VALUE_JSON, 스키마 v1). 저평가 계산이 끝날 때마다."""
    if rows is None:
        with VAL_LOCK:
            rows = list(VAL["rows"])
        at = VAL["at"]
    else:
        at = VAL["at"] or time.time()
    keep = ("code", "name", "tier", "score", "per", "per_then", "per_pct", "dd", "roe", "debt_eq", "ni_yoy", "px_yoy", "industry", "tier_why")
    out = []
    for r in _val_apply_risk(rows):
        if r.get("tier") not in ("저평가", "관찰"):
            continue
        x = {k: r.get(k) for k in keep}
        x["risk"] = (r.get("risk") or {}).get("level")
        x["kst"] = r.get("kst") or []
        out.append(x)
    data = {"v": 1, "at": at, "date": dt.datetime.fromtimestamp(at).strftime("%Y%m%d") if at else None,
            "source": "기업추적 저평가", "rows": out}
    tmp = VAL_TECH_EXPORT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, VAL_TECH_EXPORT)
    return len(out)


def value_view(force=False):
    with VAL_LOCK:
        if not VAL["rows"] and not VAL["at"]:
            try:
                with open(os.path.join(VAL_DIR, "_result.json"), "r", encoding="utf-8") as fh:
                    old = json.load(fh)
                if old.get("v") == VAL_V:
                    VAL.update(rows=old["rows"], at=old["at"], n_fell=old.get("n_fell", 0), n_univ=old.get("n_univ", 0))
            except Exception:
                pass
        stale = force or not VAL["at"] or time.time() - VAL["at"] > 26 * 3600     # 매일 06:30 _val_auto_loop 가 미리 센다
        if stale and not VAL["running"] and FIN is not None:
            VAL["running"] = True
            threading.Thread(target=_run_value, daemon=True).start()
        out = {k: VAL.get(k) for k in ("running", "done", "total", "phase", "at", "rows", "n_fell", "n_univ")}
    out["rows"] = _val_apply_risk(out.get("rows") or [])
    dr = _disc_risk() or {}
    out["risk_meta"] = {k: dr.get(k) for k in ("기준일", "evidence", "수", "규칙")} if dr else None
    out["kis_meta"] = _kis_meta()
    spec = _val_score_spec()
    if spec:
        out["bt"] = {k: spec.get(k) for k in ("eval", "n_cand", "firms", "dates", "weights", "groups")}
        # 점수 항목마다 지금 표본의 근거(위⅓ − 아래⅓) — 화면 '과거엔 이랬다'가 옛 숫자에 묶이지 않게
        try:
            with open(os.path.join(VAL_DIR, "bt_report.json"), "r", encoding="utf-8") as fh:
                fac_ = json.load(fh).get("factors") or {}
            out["bt"]["factors"] = {w["key"]: {k: fac_.get(w["key"], {}).get(k) for k in ("spread", "ci", "early", "late", "n")}
                                    for w in spec.get("weights") or [] if w["key"] in fac_}
        except Exception:
            pass
    out["rules"] = {"dd": VAL_DD, "ni": VAL_NI, "min": VAL_MIN}
    return out


# 저평가V2(차트 셋업 스크리너) 탭은 2026-10-09 에 걷어냈다 — 같은 형식이 차트 발굴(Tech) 리포트의 '저평가 종목' 칩 · 탭으로 옮겨 갔다.
# 엔진(기술.py) · 검증 도구(도구/차트셋업_백테스트.py · 저평가V2_백테스트.py) · 옛 결과 파일(.cache/value/v3_*)은 남긴다.


VAL_DAILY_AT = (6, 30)    # 밤 공시 수집(00:10) 뒤 · 장 열기 전 — 전 종목 주가를 받아 1시간 가까이 걸려 미리 돌린다


def _val_auto_loop():
    """저평가를 매일 06:30 미리 센다(끝에 차트 발굴용 tech_export.json 도 쓴다). 뷰어를 켰을 때 결과가 20시간 넘게 묵었으면 10분 뒤 한 번(색인 · 수출 추적이 먼저)."""
    time.sleep(600)
    first = True
    while True:
        try:
            p = os.path.join(VAL_DIR, "_result.json")
            old = (time.time() - os.path.getmtime(p)) if os.path.exists(p) else 1e9
            if not first or old > 20 * 3600:
                _disc_refresh()                   # 공시 목록 → 공시 위험 먼저(저평가 등급이 읽는다)
                value_view(True)
        except Exception as e:
            print("저평가 자동 갱신: %s" % e, flush=True)
        first = False
        n = dt.datetime.now()
        nxt = n.replace(hour=VAL_DAILY_AT[0], minute=VAL_DAILY_AT[1], second=0, microsecond=0)
        if nxt <= n:
            nxt += dt.timedelta(days=1)
        time.sleep(max(60, (nxt - n).total_seconds()))


# ---------------------------------------------------------------- 보컬: 거래대금 · 강한 테마 · 테마 대장주 · 눌림목 깔때기 (2026-10-08)
# 보컬.py 가 전부 센다(서버는 목록 · 일봉 · 분류표를 모아 넘기고 결과를 저장). 유니버스 = 전 시장 보통주(네이버 시총 API 목록).
# 매일 07:00(저평가 06:30 뒤) 목록 → 전 종목 일봉 → 두 모드 계산. 과거 검증은 도구/보컬_백테스트.py → .cache/vocal/bt_report.json.
try:
    _vspec = _ilu.spec_from_file_location("보컬", os.path.join(BASE, "보컬.py"))
    VOC = _ilu.module_from_spec(_vspec)
    _vspec.loader.exec_module(VOC)
except Exception as _e:
    VOC = None
    print("보컬 모듈 로드 실패:", _e)
VOCAL_V = 1
VOCAL_DIR = os.path.join(CACHE_DIR, "vocal")
VOCAL_PATH = os.path.join(VOCAL_DIR, "_result.json")
VOCAL = {"running": False, "done": 0, "total": 0, "phase": "", "at": 0, "date": None, "results": None, "n_univ": 0, "listing_date": None,
         "error": None, "_loaded": False}
VOCAL_LOCK = threading.Lock()
VOCAL_DAILY_AT = (7, 0)
_VBT = {"mt": None, "d": None}


def _vocal_bt():
    p = os.path.join(VOCAL_DIR, "bt_report.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    if _VBT["mt"] != mt:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                _VBT.update(d=json.load(fh), mt=mt)
        except Exception:
            return None
    return _VBT["d"]


def _run_vocal(refresh=True):
    try:
        with VOCAL_LOCK:
            VOCAL.update(done=0, total=0, phase="전 시장 목록", error=None)
        L = VOC.load_listing()
        if not L:
            with VOCAL_LOCK:
                VOCAL["error"] = "전 시장 목록을 받지 못했다(네이버 시총 API)"
            return
        codes = sorted(k for k, v in L["stocks"].items() if not v.get("stop"))     # 거래정지는 뺀다
        # 마지막 장 마감(평일 15:40) 뒤 받은 일봉만 믿는다 — 장중이면 오늘 반쪽 봉은 빼고 어제까지로 잰다(저평가V2 와 같다).
        # now 는 한 번만 잰다 — 받는 동안 15:40 을 넘겨도 받은 봉은 반쪽이다.
        now = dt.datetime.now()
        lc = now.replace(hour=15, minute=40, second=0, microsecond=0)
        while lc > now or lc.weekday() >= 5:
            lc -= dt.timedelta(days=1)
            lc = lc.replace(hour=15, minute=40)
        live = now.weekday() < 5 and (now.hour, now.minute) < (15, 40)
        if refresh:
            with VOCAL_LOCK:
                VOCAL.update(phase="전 종목 일봉", total=len(codes))

            def prog(a, b):
                with VOCAL_LOCK:
                    VOCAL.update(done=a, total=b)
            VOC.fetch_all_bars(codes, progress=prog, max_age=max(60, (now - lc).total_seconds()))
        with VOCAL_LOCK:
            VOCAL.update(phase="패널", done=0, total=len(codes))

        def prog2(a, b):
            with VOCAL_LOCK:
                VOCAL.update(done=a, total=b)
        smap = (sector_map() or {}).get("stocks", {})
        P = VOC.load_panel(codes, {k: v["name"] for k, v in L["stocks"].items()}, {k: (smap.get(k) or {}).get("themes") for k in codes},
                           drop=now.strftime("%Y%m%d") if live else None, progress=prog2)
        if len(P.bars) < 500:
            with VOCAL_LOCK:
                VOCAL["error"] = "일봉이 %d곳뿐 — 시세를 못 받았다" % len(P.bars)
            return
        gi = len(P.gd) - 1
        with VOCAL_LOCK:
            VOCAL.update(phase="거래대금 순위 · 테마 합")
        P.precompute(top_max=max(m["top"] for m in VOC.MODES.values()))     # 검증 도구와 같은 길 — 대장 이력(최근 30일)도 이걸로 빨리
        with VOCAL_LOCK:
            VOCAL.update(phase="깔때기")
        results = {}
        for mode in VOC.MODES:
            R = VOC.run_day(P, gi, mode)
            for f in R["funnel"]:
                B = P.bars[f["code"]]
                j = P.loc(f["code"], gi)
                n = j + 1
                f["spark"] = {"c": B["c"][max(0, n - 120):n], "v": B["v"][max(0, n - 120):n], "d": [str(x) for x in B["d"][max(0, n - 120):n]]}
            results[mode] = R
        # 잡주 거르기 — 표에 오르는 종목만 재무 요약(네이버, 7일 캐시)을 받고 공시 위험(공시위험.json)을 붙인다
        need = sorted({r["code"] for R in results.values() for key in ("top", "leaders", "funnel") for r in R.get(key) or []})
        with VOCAL_LOCK:
            VOCAL.update(phase="재무 요약(네이버)", done=0, total=len(need))

        def prog3(a, b):
            with VOCAL_LOCK:
                VOCAL.update(done=a, total=b)
        fins = VOC.fetch_fins(need, progress=prog3)
        risk = (_disc_risk() or {}).get("codes") or {}
        for R in results.values():
            VOC.annotate(R, fins, risk)
        at = time.time()
        data = {"v": VOCAL_V, "at": at, "date": str(P.gd[gi]), "results": results, "n_univ": len(P.bars), "listing_date": L.get("date")}
        with VOCAL_LOCK:
            VOCAL.update(at=at, date=data["date"], results=results, n_univ=len(P.bars), listing_date=L.get("date"))
        os.makedirs(VOCAL_DIR, exist_ok=True)
        with open(VOCAL_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except Exception as e:
        import traceback
        traceback.print_exc()
        with VOCAL_LOCK:
            VOCAL["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        with VOCAL_LOCK:
            VOCAL.update(running=False, phase="")


def vocal_view(force=False):
    if VOC is None or FIN is None:
        return {"error": "보컬 모듈이 없습니다."}
    with VOCAL_LOCK:
        if not VOCAL["_loaded"]:
            VOCAL["_loaded"] = True
            try:
                with open(VOCAL_PATH, "r", encoding="utf-8") as fh:
                    old = json.load(fh)
                if old.get("v") == VOCAL_V:
                    VOCAL.update(at=old["at"], date=old.get("date"), results=old.get("results"), n_univ=old.get("n_univ", 0),
                                 listing_date=old.get("listing_date"))
            except Exception:
                pass
        # 매일 07:00 _vocal_auto_loop 가 미리 센다. 실패한 뒤엔 '다시 계산'을 눌러야 다시 돈다(5초마다 다시 시작하지 않게)
        stale = force or (not VOCAL["results"] and not VOCAL["error"]) or (VOCAL["results"] and time.time() - VOCAL["at"] > 26 * 3600)
        if stale and not VOCAL["running"]:
            VOCAL.update(running=True, error=None)
            threading.Thread(target=_run_vocal, daemon=True).start()
        out = {k: VOCAL.get(k) for k in ("running", "done", "total", "phase", "at", "date", "results", "n_univ", "listing_date", "error")}
    out["bt"] = _vocal_bt()
    out["rules"] = {"modes": VOC.MODES, "consts": {k: getattr(VOC, k) for k in (
        "POOL_DAYS", "RALLY_WIN", "BASE_WIN", "RISE_MAX", "RETRACE_MAX", "TOUCH", "HOLD_BELOW", "DRY_PEAK", "DRY_RALLY", "REFLOW", "BODY",
        "RR_MIN", "GAP_SKIP", "THEME_RATIO", "THEME_MIN", "THEME_TOP")}}
    return out


def _vocal_auto_loop():
    """매일 07:00 — 저평가(06:30)가 988곳 일봉을 데운 뒤 나머지 전 시장 일봉을 받아 깔때기를 센다. 뷰어를 켰을 때 20시간 넘게 묵었으면 15분 뒤 한 번."""
    time.sleep(900)
    first = True
    while True:
        try:
            old = (time.time() - os.path.getmtime(VOCAL_PATH)) if os.path.exists(VOCAL_PATH) else 1e9
            if not first or old > 20 * 3600:
                for _ in range(240):                  # 저평가(06:30)가 주가를 받는 동안은 기다린다 — 같은 캐시 파일을 둘이 쓰지 않게(최대 2시간)
                    with VAL_LOCK:
                        busy = VAL["running"]
                    if not busy:
                        break
                    time.sleep(30)
                with VOCAL_LOCK:
                    go = not VOCAL["running"]
                    if go:
                        VOCAL.update(running=True, error=None)
                if go:
                    _run_vocal(True)
        except Exception as e:
            print("보컬 자동 갱신: %s" % e, flush=True)
        first = False
        n = dt.datetime.now()
        nxt = n.replace(hour=VOCAL_DAILY_AT[0], minute=VOCAL_DAILY_AT[1], second=0, microsecond=0)
        if nxt <= n:
            nxt += dt.timedelta(days=1)
        time.sleep(max(60, (nxt - n).total_seconds()))


# ---------------------------------------------------------------- 차트 발굴 — Tech(chart_screener) 리포트를 '보컬' 탭 자리에 (2026-10-09)
# 설계: docs/superpowers/specs/2026-10-09-tech-tab-design.md. Tech 는 pandas 2.x 가 필요해 64비트 venv 에서 돌고(이 서버는 32비트),
# 그래서 별도 프로세스로 `python -m chart_screener scan` 을 창 없이 띄우고, 나온 output/scan_*.html 을 iframe 으로 보인다.
# 보컬 규칙은 Tech 의 패턴 'vocal'(칩 '보컬')로 옮겼다 — 예전 보컬 탭 · /api/vocal 은 코드만 남고 자동 계산은 껐다.
TECH_DIR = os.environ.get("CHART_SCREENER_DIR") or os.path.normpath(os.path.join(BASE, "..", "..", "Tech"))
TECH_PY = os.environ.get("CHART_SCREENER_PY") or os.path.join(os.path.expanduser("~"), ".venvs", "chart_screener", "Scripts", "pythonw.exe")
TECH_OUT = os.path.join(TECH_DIR, "output", "viewer")   # 뷰어가 띄운 전 종목 스캔만(손으로 돌린 일부 패턴 스캔 · 조각과 섞이지 않게)
TECH_LOG = os.path.join(TECH_OUT, "viewer_scan.log")
TECH_RISK = os.path.join(CACHE_DIR, "공시목록", "공시위험.json")   # 보컬 잡주 거르기(작전주 꼴 · 상폐 절차 · 자금조달 잦음 …)
TECH = {"proc": None, "started": 0, "phase": "", "error": None}
TECH_LOCK = threading.Lock()
TECH_DAILY_AT = (16, 0)          # 평일 장 마감(15:30) · 일봉 확정(15:45) 뒤


def _tech_reports():
    """Tech output 의 스캔 리포트 [(mtime, 이름)] — 새것부터."""
    try:
        fs = [f for f in os.listdir(TECH_OUT) if f.startswith("scan_") and f.endswith(".html")]
    except OSError:
        return []
    return sorted(((os.path.getmtime(os.path.join(TECH_OUT, f)), f) for f in fs), reverse=True)


def _tech_running():
    p = TECH["proc"]
    return p is not None and p.poll() is None


def _tech_log_tail(n=12):
    try:
        with open(TECH_LOG, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    # 진행률(\r 로 덮어쓰는 줄)은 마지막 조각만
    return [ln.split("\r")[-1] for ln in lines[-n:] if ln.strip()]


def _tech_supports(flag):
    """Tech CLI 가 그 옵션을 아는가(저장소가 옛 판이면 모르는 옵션으로 스캔이 죽지 않게)."""
    try:
        with open(os.path.join(TECH_DIR, "chart_screener", "__main__.py"), "r", encoding="utf-8") as fh:
            return flag in fh.read()
    except OSError:
        return False


def tech_run(auto=False):
    """Tech 스캔을 창 없이 띄운다(이미 돌면 그대로). auto = 자동 실행(휴장일이면 Tech 가 스스로 건너뛴다). 반환: tech_status()."""
    with TECH_LOCK:
        if _tech_running():
            return tech_status()
        if not os.path.isdir(TECH_DIR):
            TECH["error"] = "Tech 폴더가 없습니다: %s (환경변수 CHART_SCREENER_DIR 로 바꿀 수 있다)" % TECH_DIR
            return tech_status()
        exe = TECH_PY if os.path.exists(TECH_PY) else None
        if exe is None:
            TECH["error"] = ("Tech 용 64비트 파이썬이 없습니다: %s — Tech 폴더에서 venv 를 만들고 "
                             "pip install -r requirements.txt (환경변수 CHART_SCREENER_PY 로 바꿀 수 있다)" % TECH_PY)
            return tech_status()
        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0          # SW_HIDE — 작업 중인 화면에 창이 뜨면 안 된다
        os.makedirs(TECH_OUT, exist_ok=True)
        log = open(TECH_LOG, "w", encoding="utf-8")
        log.write("== 차트 발굴 스캔 %s\n" % dt.datetime.now().isoformat(timespec="seconds"))
        log.flush()
        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            if os.path.exists(TECH_RISK):
                env.setdefault("CHART_SCREENER_RISK_JSON", TECH_RISK)
            if not os.path.exists(VAL_TECH_EXPORT) and VAL.get("rows"):
                try:
                    _val_export_tech()
                except Exception:
                    pass
            if os.path.exists(VAL_TECH_EXPORT):
                env.setdefault("CHART_SCREENER_VALUE_JSON", VAL_TECH_EXPORT)    # '저평가 종목' 칩 · 탭
            cmd = [exe, "-m", "chart_screener", "scan", "--out", TECH_OUT]
            if auto and _tech_supports("--skip-holiday"):
                cmd.append("--skip-holiday")
            if _tech_supports("--hist-budget"):      # 차트 '전체' 용 긴 이력(증권사 일봉) — 리포트 뒤 최대 10분, 남으면 다음 스캔
                cmd += ["--hist-budget", "600"]
            TECH["proc"] = subprocess.Popen(
                cmd, cwd=TECH_DIR,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env=env, startupinfo=si,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            log.close()
            TECH["error"] = "스캔을 띄우지 못했습니다: %s" % e
            return tech_status()
        log.close()                     # 자식 프로세스가 핸들을 물고 있다
        TECH.update(started=time.time(), error=None)
    return tech_status()


def tech_status():
    rep = _tech_reports()
    p = TECH["proc"]
    rc = p.poll() if p is not None else None
    out = {"running": _tech_running(), "started": TECH["started"], "error": TECH["error"],
           "exit": rc, "log": _tech_log_tail(), "dir": TECH_DIR,
           "report": {"name": rep[0][1], "at": rep[0][0]} if rep else None, "n_reports": len(rep)}
    if rc not in (None, 0) and not TECH["error"]:
        out["error"] = "스캔이 오류로 끝났습니다(종료 코드 %s) — 아래 기록을 보세요." % rc
    return out


def tech_report_html(name=""):
    """name 이 주어지면 그 리포트(output 안 scan_*.html 만), 아니면 가장 새것. 없으면 None."""
    rep = _tech_reports()
    names = {f for _, f in rep}
    f = name if name in names else (rep[0][1] if rep else None)
    if not f:
        return None
    with open(os.path.join(TECH_OUT, f), "rb") as fh:
        return fh.read()


def _tech_auto_loop():
    """평일 16:00 · 뷰어를 켰을 때(10분 뒤) — 마지막 리포트가 가장 최근 거래일 장 마감(15:45, 주말은 금요일) 전 것이면 한 번.
    16:00 를 뷰어가 꺼져 놓쳤으면 다음에 켤 때 따라잡는다. 휴장일(공휴일)은 Tech 가 증권사 휴장일 조회로 스스로 건너뛴다(--skip-holiday)."""
    time.sleep(600)
    while True:
        try:
            n = dt.datetime.now()
            lc = n.replace(hour=15, minute=45, second=0, microsecond=0)
            while lc > n or lc.weekday() >= 5:
                lc -= dt.timedelta(days=1)
            rep = _tech_reports()
            last = dt.datetime.fromtimestamp(rep[0][0]) if rep else None
            if last is None or last < lc:
                tech_run(auto=True)
        except Exception as e:
            print("차트 발굴 자동 스캔: %s" % e, flush=True)
        n = dt.datetime.now()
        nxt = n.replace(hour=TECH_DAILY_AT[0], minute=TECH_DAILY_AT[1], second=0, microsecond=0)
        if nxt <= n:
            nxt += dt.timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += dt.timedelta(days=1)
        time.sleep(max(60, (nxt - n).total_seconds()))


# ---------------------------------------------------------------- 산업 성장률 (2026-10-06)
# 섹터별 매출 · 영업이익(상장사, 자회사 중복 제거) · 생산 · 가동률 · 수출 · 가격 · 시장 규모 · 시가총액 · 전망을 한 표로.
# 계산은 산업.py → .cache/산업/_result.json. 재료는 산업_패널.py(회사 패널 · 연결 구조) · 산업_부문.py(섞인 회사의 부문) ·
# 산업_통계.py(KOSIS · ECOS · 관세청) · 산업_외부자료.json(세계 시장 · 기관 전망, 출처 확인한 숫자만). 매일 07:40 재료부터 다시.
IND_V = 2     # 2: 하위탭 자료(members_all · exports.q · backlog.rows) — 산업.py V 와 같이 올린다 (2026-10-08)
IND_DIR = os.path.join(CACHE_DIR, "산업")
IND = {"running": False, "done": 0, "total": 0, "phase": "", "at": 0, "data": None}
IND_LOCK = threading.Lock()
IND_DAILY_AT = (7, 40)    # 저평가(06:30) 뒤 — 시세 캐시가 데워진 다음


def _ind_mod():
    spec = _ilu.spec_from_file_location("산업", os.path.join(BASE, "산업.py"))
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _ind_refresh():
    """재료 갱신 — 통계(최근 달) · 패널(새 보고서) · 부문. 하나가 실패해도 나머지는 돈다(기록 산업_auto.log)."""
    import subprocess
    log = os.path.join(BASE, "산업_auto.log")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("\n== %s\n" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        fh.flush()
        for cmd in (["산업_통계.py", "갱신"], ["산업_패널.py"], ["산업_부문.py"]):
            try:
                subprocess.run([sys.executable, os.path.join(BASE, cmd[0])] + cmd[1:], cwd=BASE, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=3 * 3600, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            except Exception as e:
                fh.write("실패 %s: %s\n" % (cmd[0], e))


def _run_industry(refresh=False):
    try:
        if refresh:
            with IND_LOCK:
                IND.update(phase="재료 갱신 중(통계 · 패널 · 부문)", done=0, total=0)
            _ind_refresh()

        def prog(msg, i=None, n=None):
            with IND_LOCK:
                IND.update(phase=msg, done=i or 0, total=n or 0)
        # 색인은 서버가 이미 가진 것을 넘긴다 — 32비트 파이썬에서 133MB 를 한 번 더 올리면 MemoryError 로 수주잔고가 비었다(2026-10-08)
        res = _ind_mod().build(prog, index=INDEX)
        with IND_LOCK:
            IND.update(data=res, at=res.get("at") or time.time(), phase="")
    except Exception as e:
        import traceback
        traceback.print_exc()
        with IND_LOCK:
            IND["phase"] = "실패: %s" % e
    finally:
        with IND_LOCK:
            IND["running"] = False


def industry_view(force=False):
    with IND_LOCK:
        if IND["data"] is None:
            try:
                with open(os.path.join(IND_DIR, "_result.json"), "r", encoding="utf-8") as fh:
                    old = json.load(fh)
                if old.get("v") == IND_V:
                    IND.update(data=old, at=old.get("at") or 0)
            except Exception:
                pass
        stale = force or not IND["at"] or time.time() - IND["at"] > 26 * 3600     # 매일 07:40 _ind_auto_loop 가 미리 센다
        if stale and not IND["running"]:
            IND["running"] = True
            threading.Thread(target=_run_industry, daemon=True).start()
        out = {k: IND.get(k) for k in ("running", "done", "total", "phase", "at")}
        d = IND["data"] or {}
    for k, v in d.items():
        if k not in out:
            out[k] = v
    # 큰 칸(42분기 · 섹터 안 전 종목)은 하위탭 API 가 따로 준다 — 캐시 dict 를 직접 pop 하면 첫 호출 뒤 사라지므로(2026-10-08) 얕은 복사
    out["sectors"] = [{k: v for k, v in s.items() if k not in ("quarters_all", "members_all")} for s in out.get("sectors") or []]
    bt = _clock_bt()
    if bt:
        out["clock_bt"] = {"labels": {k: (v.get("h12") or {}).get("eq") for k, v in (bt.get("labels") or {}).items()}, "at": bt.get("at")}
    return out


# ---------------------------------------------------------------- 산업 성장률 하위탭 — 섹터 안 종목 · 시계 성적표 · 일감 · 수출 먼저 (2026-10-08)
# 설계: docs/superpowers/specs/2026-10-08-industry-subtabs-design.md. 요약 화면은 /api/industry, 섹터 상세는 /api/industry/sub?tab=&sector=
_INDF = {}


def _ind_file(name, path):
    """작은 결과 파일(백테스트 성적표 등)을 mtime 으로 캐시해 읽는다. 없으면 None."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    c = _INDF.get(name)
    if not c or c[0] != mt:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _INDF[name] = c = (mt, json.load(fh))
        except Exception:
            return None
    return c[1]


def _clock_bt():
    return _ind_file("clock_bt", os.path.join(IND_DIR, "clock_bt.json"))


def _ind_contract_counts(days=90):
    """최근 days 일 단일판매ㆍ공급계약체결 공시 건수 {종목코드: n} — .cache/공시목록/I_*.jsonl(거래소 공시 목록, 금액 없음), 기재정정은 뺀다."""
    base = os.path.join(CACHE_DIR, "공시목록")
    since = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")
    key = ("contract", since)
    c = _INDF.get(key)
    try:
        fs = sorted(f for f in os.listdir(base) if f.startswith("I_") and f.endswith(".jsonl"))[-3:]
        mt = max(os.path.getmtime(os.path.join(base, f)) for f in fs) if fs else 0
    except OSError:
        return {}
    if c and c[0] == mt:
        return c[1]
    out = {}
    for f in fs:
        try:
            with open(os.path.join(base, f), "r", encoding="utf-8") as fh:
                for ln in fh:
                    if "공급계약" not in ln or "기재정정" in ln:
                        continue
                    j = json.loads(ln)
                    nm = (j.get("report_nm") or "").strip()
                    # '단일판매ㆍ공급계약체결(자율공시)' 류만 — 해지 · 유동성공급계약 · 주권매매거래정지 안내 · [첨부정정] 재공시는 뺀다
                    if not nm.startswith("단일판매") or "체결" not in nm.split("(")[0]:
                        continue
                    if (j.get("rcept_dt") or "") >= since and j.get("stock_code"):
                        out[j["stock_code"]] = out.get(j["stock_code"], 0) + 1
        except Exception:
            continue
    _INDF[key] = (mt, out)
    return out


def industry_sub(tab, sector):
    """하위탭 자료. tab = stocks(섹터 안 종목) · clock(시계 성적표) · orders(일감) · exports(수출 먼저)."""
    with IND_LOCK:
        d = IND["data"]
    if d is None:
        industry_view()
        with IND_LOCK:
            d = IND["data"]
    secs = (d or {}).get("sectors") or []
    s = next((x for x in secs if x.get("key") == sector), None)
    # 낡은 localStorage(없어진 섹터 이름)면 전체 모드로 — 화면은 sector 가 비어 있을 때 전체 모드를 그린다
    out = {"tab": tab, "sector": sector if s else "", "latest_q": (d or {}).get("latest_q")}
    if tab == "clock":
        bt = _clock_bt()
        out["bt"] = bt
        if s:
            out["phase"] = s.get("phase")
        return out
    if tab == "stocks":
        acc = _ind_file("bt_accel", os.path.join(CACHE_DIR, "druck_bt", "bt_accel.json")) or {}
        ev = acc.get("ev_all") or {}
        out["bt"] = {"B_up": ev.get("B_up"), "B_dn": ev.get("B_dn"), "regime": (acc.get("regime") or {}).get("B"),
                     "whip": (acc.get("whip") or {}).get("B"), "order": {k: v for k, v in (acc.get("ev_order") or {}).items() if k in ("B_up", "B_dn", "B_spread")},
                     "n": acc.get("n"), "firms": acc.get("firms")}
        if s:
            out.update(phase=s.get("phase"), cap=s.get("cap"), val=s.get("val"), ttm=s.get("ttm"), ytd=s.get("ytd"), fc_main=s.get("fc_main"),
                       members=s.get("members_all") or [], desc=s.get("desc"))
        else:
            out["sectors"] = [{"key": x["key"], "phase": x.get("phase"), "cap": x.get("cap"), "ttm": x.get("ttm"), "n": x.get("n_members_cap")} for x in secs]
        return out
    if tab == "orders":
        rep = _ind_file("qtr_bt", os.path.join(CACHE_DIR, "quarter", "bt_report.json")) or {}
        rules = rep.get("rules") or {}
        syn = _ind_file("syn_bt", os.path.join(CACHE_DIR, "시너지", "bt_report.json")) or {}
        out["bt"] = {"up": (rules.get("잔고 > 매출 +15%p") or {}).get("ex12m"), "dn": (rules.get("잔고 < 매출 −15%p") or {}).get("ex12m"),
                     "stages": {k: v for k, v in (syn.get("stages") or {}).items()}}
        cnt = _ind_contract_counts()
        if s:
            b = dict(s.get("backlog") or {})
            rows = []
            for r in b.get("rows") or []:
                rows.append(dict(r, filings90=cnt.get(r["code"], 0)))
            b["rows"] = rows
            out.update(backlog=b, phase=s.get("phase"), ttm=s.get("ttm"), cap=s.get("cap"), ytd=s.get("ytd"), fc_main=s.get("fc_main"), desc=s.get("desc"),
                       order_driven=sector in ("조선", "방산·항공우주", "전력기기", "건설", "기계"))
        else:
            out["sectors"] = [{"key": x["key"], "phase": x.get("phase"), "backlog": {k: v for k, v in (x.get("backlog") or {}).items() if k != "rows"},
                               "ttm": x.get("ttm"), "filings90": sum(cnt.get(m["code"], 0) for m in x.get("members_all") or [])}
                              for x in secs if x["key"] in ("조선", "방산·항공우주", "전력기기", "건설", "기계")]
        return out
    if tab == "exports":
        xr = _ind_file("exp_track", os.path.join(CACHE_DIR, "수출추적", "result.json")) or {}
        items = {i["code"]: i for i in xr.get("items") or [] if i.get("status") == "ok"}
        val = _ind_file("exp_val", os.path.join(CACHE_DIR, "수출추적", "검증.json")) or {}
        out["bt"] = {"ic": val.get("ic") or val.get("summary") or None, "month": xr.get("month")}
        if s:
            E = s.get("exports") or None
            co = []
            for m in s.get("members_all") or []:
                it = items.get(m["code"])
                if not it:
                    continue
                sg, pt, vd = it.get("signals") or {}, it.get("partial") or {}, it.get("validation") or {}
                co.append({"code": m["code"], "name": m["name"], "grade": it.get("grade"), "state": sg.get("state"), "y3": sg.get("y3"), "acc": sg.get("acc"),
                           "partial": pt.get("yoy"), "p_months": pt.get("months") or [], "corr": vd.get("corr"), "cov": vd.get("coverage"),
                           "rev_g": m.get("rev_g"), "ret1y": m.get("ret1y"), "adj": m.get("adj"), "label": m.get("label")})
            co.sort(key=lambda r: ({"A": 0, "B": 1, "C": 2}.get(r["grade"], 3), -(r["adj"] or 0)))
            out.update(exports=E, monthly=(s.get("monthly") or {}).get("exp"), quarters=[{"q": r["q"], "rev_yoy": r.get("rev_yoy")} for r in s.get("quarters_all") or []],
                       phase=s.get("phase"), ttm=s.get("ttm"), cap=s.get("cap"), ytd=s.get("ytd"), fc_main=s.get("fc_main"), desc=s.get("desc"), companies=co)
        else:
            rows = []
            for x in secs:
                E = x.get("exports") or {}
                n_ok = sum(1 for m in x.get("members_all") or [] if m["code"] in items)
                n_ab = sum(1 for m in x.get("members_all") or [] if (items.get(m["code"]) or {}).get("grade") in ("A", "B"))
                last_rev = next((r.get("rev_yoy") for r in reversed(x.get("quarters_all") or []) if r.get("rev_yoy") is not None), None)
                rows.append({"key": x["key"], "phase": x.get("phase"), "exports": {k: E.get(k) for k in ("last", "m3_g", "m12_g", "unit_price_g", "now_q", "fit", "share")} if E else None,
                             "last_rev": last_rev, "n_ok": n_ok, "n_ab": n_ab})
            out["sectors"] = rows
        return out
    return out


def _ind_auto_loop():
    """산업 성장률 재료(통계 · 패널 · 부문) → 합산을 매일 07:40. 뷰어를 켰을 때 결과가 20시간 넘게 묵었으면 15분 뒤 한 번."""
    time.sleep(900)
    first = True
    while True:
        try:
            p = os.path.join(IND_DIR, "_result.json")
            old = (time.time() - os.path.getmtime(p)) if os.path.exists(p) else 1e9
            if not first or old > 20 * 3600:
                with IND_LOCK:
                    busy = IND["running"]
                    if not busy:
                        IND["running"] = True
                if not busy:
                    _run_industry(refresh=True)
        except Exception as e:
            print("산업 성장률 자동 갱신: %s" % e, flush=True)
        first = False
        n = dt.datetime.now()
        nxt = n.replace(hour=IND_DAILY_AT[0], minute=IND_DAILY_AT[1], second=0, microsecond=0)
        if nxt <= n:
            nxt += dt.timedelta(days=1)
        time.sleep(max(60, (nxt - n).total_seconds()))


# ---------------------------------------------------------------- 밸류체인: 누구에게 팔고 누구에게서 사나 (2026-10-04, 연혁 탭 자리)
# 사업보고서(15년)마다 「사업의 내용」에서 매출처 · 비중, 종속회사별 최종 고객, 원재료 · 매입처, 수출 · 내수, 경쟁 서술을 뽑고(밸류체인.py),
# 이름을 수집한 1,000곳 · 상장사 목록과 맞춰(_listed_names) 누르면 그 회사로 간다. 같은 고객 · 같은 매입처를 적은 다른 회사도 찾는다(그물망).
try:
    _vcspec = _ilu.spec_from_file_location("밸류체인", os.path.join(BASE, "밸류체인.py"))
    VCM = _ilu.module_from_spec(_vcspec)
    _vcspec.loader.exec_module(VCM)
except Exception as _e:
    VCM = None
    print("밸류체인 모듈 로드 실패:", _e)
VC_V = 17            # 2: 표 · 이름만 나열 · 쉼표 비중 양식, 매입처 정리(2026-10-04)
                     # 17: 줄 조각 난 매출처 문장 · '10% 이상인 거래처는 A 및 종속회사' · 표 칸 안 빈 줄 · 수출 합계 행 · 점유율 표(2026-10-12)
VC_DIR = os.path.join(CACHE_DIR, "밸류체인")
VC_LOCK = threading.Lock()
_VC_PEER = {"at": 0, "cust": {}, "supp": {}, "n": 0}


# 별명 — 보고서가 적는 이름 → 상장사 공식 이름(수집 목록 · DART). 같은 회사를 해마다 다르게 적는 것도 여기서 모은다
VC_ALIAS = {
    "포스코": "POSCO홀딩스", "posco": "POSCO홀딩스", "포스코홀딩스": "POSCO홀딩스", "한국전력": "한국전력공사", "한전": "한국전력공사",
    "한국전력공사본사": "한국전력공사", "hico": "HICO America Sales & Tech", "hicoamericasalestech": "HICO America Sales & Tech",
    "hicoamericasalestechin": "HICO America Sales & Tech", "hicoamericasalestechinc": "HICO America Sales & Tech",
    "aep": "American Electric Power", "americanelectricpower": "American Electric Power", "eversource": "Eversource Energy",
    "eversourceenergy": "Eversource Energy", "intersect": "Intersect Power", "intersectpower": "Intersect Power",
    "georgiapower": "Southern Company", "southern": "Southern Company", "pgcil": "Power Grid Corporation of India",
    "powergridcorporationofindia": "Power Grid Corporation of India", "삼성전자": "삼성전자", "현대차": "현대자동차", "기아차": "기아",
    "lg전자": "LG전자", "sk하이닉스": "SK하이닉스", "현대중공업": "HD현대중공업", "hd현대중공업": "HD현대중공업", "대우조선해양": "한화오션",
    "두산중공업": "두산에너빌리티", "삼성중공업": "삼성중공업", "현대미포조선": "HD현대미포", "한국조선해양": "HD한국조선해양",
    "삼성에스디아이": "삼성SDI", "엘지에너지솔루션": "LG에너지솔루션", "lg에너지솔루션": "LG에너지솔루션", "hanwhaqcells": "한화솔루션",
    "한화큐셀": "한화솔루션", "엘지화학": "LG화학", "에스케이하이닉스": "SK하이닉스", "기아자동차": "기아",
}


def _vc_strip(name):
    """'(주)' · '본사' · '등' 꼬리, 그리고 '및 종속회사' · '와 그 종속기업' · '및 삼성전자의 해외종속회사' 꼬리(같은 고객이다)를 뗀다."""
    n = re.sub(r"\(\*+\)|\(주\)|㈜|주식회사|\s*본사$|\s*등$", "", name or "").strip()
    return VCM.GROUP_TAIL.sub("", n).strip() if VCM is not None else n


VC_ETC = re.compile(r"^(?:기타|그\s*외|원재료\s*외|부재료\s*외|원부재료\s*외)(?:\s*(?:원재료|원자재|부재료|원부재료|재료|자재|매입|품목))?(?:\s*등)?$")


def _vc_etc(item, suppliers):
    """'기타' 원재료 줄 — 금액이 커도 지도 카드 뒤로. '기타 반도체'(매입처 있음)는 품목이다."""
    it = (item or "").strip()
    return bool(VC_ETC.match(it)) or (it.startswith("기타") and not suppliers)


def _vc_key(name):
    """회사 이름 맞추기 — 영문은 소문자 · 공백 · 구두점 제거, 한글은 _norm_corp. 'HICO America Sales & Tech, Inc.' ≈ 'HICO AMERICA SALES & TECH., IN'.
    별명(VC_ALIAS)이 있으면 그 공식 이름의 키로. '삼성전자 및 종속회사' = '삼성전자'."""
    n = _vc_strip(name)
    n = re.sub(r"\b(?:co|ltd|inc|corp|corporation|company|limited|pvt|llc|gmbh|sa|plc)\b\.?", "", n, flags=re.I)
    n = re.sub(r"[\s.,'’&\-·ㆍ/()]", "", n).lower()
    canon = VC_ALIAS.get(n)
    if canon:
        n = re.sub(r"[\s.,'’&\-·ㆍ/()]", "", canon).lower()
    return n[:24] if re.fullmatch(r"[a-z0-9]+", n) else _norm_corp(n)


def _vc_canon(name):
    """화면에 적을 이름 — 별명이면 공식 이름, 아니면 적힌 대로('및 종속회사' 꼬리만 뗀다)."""
    n = _vc_strip(name)
    k = re.sub(r"\b(?:co|ltd|inc|corp|corporation|company|limited|pvt|llc|gmbh|sa|plc)\b\.?", "", n, flags=re.I)
    k = re.sub(r"[\s.,'’&\-·ㆍ/()]", "", k).lower()
    return VC_ALIAS.get(k) or (VCM.GROUP_TAIL.sub("", name or "").strip() if VCM is not None else name)


def _vc_extract(c, r):
    sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
    if not sec or VCM is None:
        return None
    try:
        return VCM.extract(corpus_text(c, r, sec["file"]))
    except Exception:
        return None


def _vc_sig(c):
    return "%s:%d" % (max((r["rcept"] for r in c["reports"]), default=""), VC_V)


def _vc_amount(d):
    """뽑힌 양 — 이름 적힌 매출처 · 가려진 고객 · 종속법인 고객 · 원재료 줄 수."""
    if not d:
        return 0
    return (sum(1 for x in d.get("customers") or [] if x.get("kind") in ("named", "hidden")) +
            sum(len(s.get("customers") or []) for s in d.get("subs") or []) + len(d.get("materials") or []))


def _vc_company(c):
    """회사 하나의 밸류체인 — 해마다 사업보고서, 그리고 마지막 사업보고서 뒤에 나온 최신 분기 · 반기보고서 하나(지금 모습).
    분기 · 반기보고서 「사업의 내용」도 매출처 · 원재료 · 수출을 거의 같은 만큼 적는다(표본 60곳: 사업 14곳 · 분기 12곳에서 매출처).
    분기 칸 열쇠는 'YYYY-MM'(예: '2026-06') — 연도 열쇠('2025')보다 뒤로 정렬된다. 다음 사업보고서가 나오면 그 뒤 분기가 없으니 빠진다.
    분기 칸이 사업보고서보다 크게 덜 적었으면(절반 미만) 넣지 않는다 — 요약만 적은 분기를 '고객이 빠졌다'로 읽지 않게.
    캐시는 최신 접수번호 · VC_V 로 묶음 — 새 보고서(분기 포함)가 들어오면 다시 뽑는다."""
    p = os.path.join(VC_DIR, c["code"] + ".json")
    sig = _vc_sig(c)
    try:
        with open(p, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("sig") == sig:
            return d
    except Exception:
        pass
    ann = [r for r in c["reports"] if r["label"] == "사업보고서" and not r["tag"]]
    years = {}
    for r in ann:
        y = int(r["stamp"][:4])
        if y not in years or r["rcept"] > years[y]["rcept"]:
            years[y] = r
    out = {"sig": sig, "code": c["code"], "name": c["name"], "years": {}}
    for y in sorted(years):
        d = _vc_extract(c, years[y])
        if d:
            out["years"][str(y)] = dict(d, rcept=years[y]["rcept"], stamp=years[y]["stamp"], label="사업보고서")
    last_ann = max((r["stamp"] for r in ann), default="")
    qs = [r for r in c["reports"] if r["label"] in ("분기보고서", "반기보고서") and not r["tag"] and r["stamp"] > last_ann]
    if qs:
        q = max(qs, key=lambda r: (r["stamp"], r["rcept"]))
        dq = _vc_extract(c, q)
        prev = out["years"][max(out["years"])] if out["years"] else None
        if dq and _vc_amount(dq) > 0 and _vc_amount(dq) * 2 >= _vc_amount(prev):
            out["years"][q["stamp"][:7]] = dict(dq, rcept=q["rcept"], stamp=q["stamp"], label=q["label"], partial=True)
    os.makedirs(VC_DIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


VC_DAILY_AT = (6, 0)     # 밤 공시 수집(00:10, 보통 30~50분) 뒤 · 저평가 자동 갱신(06:30) 전
VC_REFRESH = {"running": False, "at": 0, "changed": 0, "n": 0}


def _vc_refresh_all():
    """새 보고서가 들어온 회사의 밸류체인 캐시를 다시 뽑고 그물망 색인을 비운다 — 다른 회사 그물망이 열 때까지 묵지 않게.
    바뀐 회사만 다시 뽑는다(서명 = 최신 접수번호). 아무것도 안 바뀌었으면 캐시 파일만 훑고 끝."""
    with VC_LOCK:
        if VC_REFRESH["running"] or VCM is None:
            return
        VC_REFRESH["running"] = True
    changed = n = 0
    try:
        for c in list(INDEX["companies"]):
            n += 1
            p = os.path.join(VC_DIR, c["code"] + ".json")
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    if json.load(fh).get("sig") == _vc_sig(c):
                        continue
            except Exception:
                pass
            try:
                _vc_company(c)
                changed += 1
            except Exception as e:
                print("밸류체인 갱신 %s: %s" % (c["code"], e), flush=True)
        if changed:
            with VC_LOCK:
                _VC_PEER["at"] = 0           # 그물망 색인은 다음 요청 때 새로
        print("밸류체인 갱신: %d곳 중 %d곳 다시 뽑음" % (n, changed), flush=True)
    finally:
        with VC_LOCK:
            VC_REFRESH.update(running=False, at=time.time(), changed=changed, n=n)


def _vc_auto_loop():
    """뷰어가 켜지면 색인이 선 뒤 한 번(꺼져 있던 동안 들어온 보고서), 그 뒤 매일 06:00 — 색인을 새로 읽고(밤 수집분) 밸류체인을 갱신."""
    time.sleep(300)
    while not INDEX_STATE.get("ready"):
        time.sleep(30)
    first = True
    while True:
        try:
            if not first:
                build_index()            # 밤 00:10 수집분 — 뷰어는 00:05 에 다시 켜져 수집 전 색인을 들고 있다
            _vc_refresh_all()
        except Exception as e:
            print("밸류체인 자동 갱신: %s" % e, flush=True)
        first = False
        n = dt.datetime.now()
        nxt = n.replace(hour=VC_DAILY_AT[0], minute=VC_DAILY_AT[1], second=0, microsecond=0)
        if nxt <= n:
            nxt += dt.timedelta(days=1)
        time.sleep(max(60, (nxt - n).total_seconds()))


def _vc_peers():
    """전 종목 최신 사업보고서의 매출처 · 매입처 이름 색인 — {이름키: [(코드, 이름, 비중)]}. 하루 한 번."""
    try:
        n_files = len([f for f in os.listdir(VC_DIR) if f.endswith(".json")])
    except OSError:
        n_files = 0
    with VC_LOCK:
        # 하루 한 번 — 다만 캐시 파일 수가 늘었으면(도구/밸류체인_전종목.py 가 돌아 채워진 것) 바로 다시 짠다
        if time.time() - _VC_PEER["at"] < 86400 and _VC_PEER["n"] and _VC_PEER.get("files") == n_files:
            return _VC_PEER
    cust, supp, n = {}, {}, 0
    for c in list(INDEX["companies"]):
        ann = [r for r in c["reports"] if r["label"] == "사업보고서" and not r["tag"]]
        if not ann:
            continue
        p = os.path.join(VC_DIR, c["code"] + ".json")
        d = None
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            d = None
        if not d or not d.get("years"):
            continue           # 아직 안 뽑은 회사는 건너뛴다 — 처음 여는 회사부터 차차 채워진다
        y = max(d["years"])
        n += 1
        for x in d["years"][y].get("customers") or []:
            if x.get("kind") == "named":
                nm_ = VCM._strip_amount(x["name"])
                cust.setdefault(_vc_key(nm_), []).append((c["code"], c["name"], x.get("pct"), nm_))
        for s in d["years"][y].get("subs") or []:
            for nm, pct in (s.get("customers") or []) + (s.get("final") or []):
                cust.setdefault(_vc_key(nm), []).append((c["code"], c["name"], pct, nm))
        for mt in d["years"][y].get("materials") or []:
            for sp in mt.get("suppliers") or []:
                supp.setdefault(_vc_key(sp["name"]), []).append((c["code"], c["name"], mt.get("pct"), sp["name"]))
    with VC_LOCK:
        _VC_PEER.update(at=time.time(), cust=cust, supp=supp, n=n, files=n_files)
    return _VC_PEER


def valuechain_view(code):
    c = company_by_code(code)
    if not c:
        return None
    if VCM is None:
        return {"error": "밸류체인 모듈이 없습니다."}
    d = _vc_company(c)
    years = sorted(d["years"])
    if not years:
        return {"error": "사업보고서 「사업의 내용」을 못 읽었습니다."}
    names = _listed_names()
    en_idx = _NAMES_EN.get("idx")
    univ = {x["code"]: x for x in INDEX["companies"]}
    peers = _vc_peers()
    me_k = _vc_key(c["name"])
    # 영문 한 낱말(COSMO)이 수집 회사 여럿과 맞으면 — 나를 고객으로 적은 회사(매입처 쪽) · 나를 매입처로 적은 회사(고객 쪽)로 좁힌다
    pref_supp = {t[0] for t in peers["cust"].get(me_k, [])}
    pref_cust = {t[0] for t in peers["supp"].get(me_k, [])}

    def link(nm, prefer=()):
        """이름 → 상장사 코드(수집했으면 collected). 별명 표를 거친다.
        영문만 적힌 이름은 별명 표, 그다음 DART 영문 이름(EnNames — DOOSAN → 두산, COSMO AMT → 코스모신소재)으로.
        4글자 미만 영문(KEC)은 잇지 않는다 — 인도 KEC 가 한국 상장사 KEC 로 이어지던 것."""
        cn = _vc_canon(nm)
        ascii_only = not re.search(r"[가-힣]", nm or "")
        if ascii_only and cn == nm:
            cd = en_idx.code(nm, univ, prefer) if en_idx is not None else None
            return {"code": cd, "collected": cd in univ, "name": None} if cd else None
        for cand in (cn, re.sub(r"\(\*+\)|\s*본사$|\(주\)|㈜|주식회사", "", nm or "").strip()):
            cd = names.get(_norm_corp(cand))
            if cd:
                return {"code": cd, "collected": cd in univ, "name": cn if cn != nm else None}
        return None
    last = d["years"][years[-1]]
    # 고객 — 해마다 비중의 변천 {이름키: {name, country, link, by_year:{y: pct}}}
    hist = {}
    seg_names = set()
    for y in years:
        dy = d["years"][y]
        seg_names |= {re.sub(r"\s+", "", v) for v in [x.get("seg") for x in dy.get("customers") or []] +
                      [m.get("segment") for m in dy.get("materials") or []] + [g.get("segment") for g in dy.get("segments") or []] +
                      [p_.get("segment") for p_ in dy.get("products") or []] if v}          # 부문 매출표 행('컴포넌트 49.32')은 고객이 아니다
    for y in years:
        for x in d["years"][y].get("customers") or []:
            if x.get("kind") != "named" or re.sub(r"\s+", "", x["name"]) in seg_names or re.search(r"수주\s*잔|잔고|매출액|당기말|전기말", x["name"]):
                continue
            k = _vc_key(x["name"])
            h = hist.setdefault(k, {"name": _vc_canon(x["name"]), "country": x.get("country"), "by_year": {}, "aka": set()})
            if y == years[-1]:
                h["seg"], h["basis"] = x.get("seg"), x.get("basis")
            if h["by_year"].get(y) is None or (x.get("pct") or 0) > (h["by_year"][y] or 0):
                h["by_year"][y] = x.get("pct")
            h["aka"].add(x["name"])
            h["name"] = _vc_canon(x["name"])
    for h in hist.values():
        h["link"] = link(h["name"], pref_cust)
        h["first"], h["last"] = min(h["by_year"]), max(h["by_year"])
        h["pct"] = h["by_year"].get(years[-1])
        h["aka"] = sorted(a for a in h["aka"] if a != h["name"])
        h["country"] = "한국" if h["link"] else (VCM._country(h["name"]) or h.get("country"))
    customers = sorted(hist.values(), key=lambda h: (h["last"] != years[-1], -(h["pct"] or 0), -(max(v or 0 for v in h["by_year"].values()))))
    hidden = [x for x in last.get("customers") or [] if x.get("kind") == "hidden"]
    no_major = any(x.get("kind") == "none" for x in last.get("customers") or [])      # 매출 10% 넘는 고객 없음(고루 퍼짐)
    types = [{"name": x["name"], "pct": x.get("pct"), "seg": x.get("seg")} for x in last.get("customers") or [] if x.get("kind") == "type"]
    # 같은 그룹 판정 — 내 이름 · 지배회사 법인 머리(LS ELECTRIC) · 종속회사 이름과 키가 겹치면 계열 내부 거래다
    own_keys = {_vc_key(c["name"])} | {_vc_key(s["sub"]) for s in last.get("subs") or []}
    own_keys |= {_vc_key(x["scope"]) for x in last.get("customers") or [] if x.get("basis") == "부문" and x.get("scope")}
    own_keys = {k for k in own_keys if len(k) >= 4}

    def own_of(nm):
        k = _vc_key(nm)
        if k in own_keys:
            return k
        hits = [o for o in own_keys if len(o) >= 6 and (k.startswith(o) or (o.startswith(k) and len(k) >= 6))]
        return max(hits, key=len) if hits else None
    sub_by_key = {_vc_key(s["sub"]): s["sub"] for s in last.get("subs") or []}
    # 종속회사 · 최종 고객
    subs = []
    for s in last.get("subs") or []:
        custs = s.get("final") or s.get("customers") or []
        subs.append({"sub": s["sub"], "customers": [{"name": nm, "pct": pct, "country": VCM._country(nm), "link": link(nm), "own": bool(own_of(nm))} for nm, pct in custs],
                     "types": [{"name": nm, "pct": pct} for nm, pct in s.get("types") or []], "segs": s.get("segs") or [],
                     "channels": s.get("channels") or []})
    # 매입처 — 최신 해, 그리고 15년 동안 적힌 적 있는 매입처
    mats = []
    for mt in last.get("materials") or []:
        if not mt.get("item") or mt.get("item") == "-" or re.search(r"합\s*계", (mt.get("item") or "") + " " + (mt.get("segment") or "")):
            continue
        sps = []
        for sp in mt.get("suppliers") or []:
            lk = link(sp["name"], pref_supp)
            sps.append(dict(sp, link=lk, country="한국" if lk else (VCM._country(sp["name"]) or sp.get("country"))))
        mats.append(dict(mt, suppliers=sps, etc=_vc_etc(mt.get("item"), sps)))
    mats.sort(key=lambda m: m["etc"])            # '기타' 원재료는 뒤로(안정 정렬) — 금액이 커서 지도 위 카드 여섯 자리를 둘 넘게 차지했다
    supp_hist = {}
    for y in years:
        for mt in d["years"][y].get("materials") or []:
            for sp in mt.get("suppliers") or []:
                k = _vc_key(sp["name"])
                h = supp_hist.setdefault(k, {"name": sp["name"], "years": [], "items": set()})
                h["years"].append(y)
                if mt.get("item"):
                    h["items"].add(mt["item"])
    supp_hist = [dict(h, items=sorted(h["items"]), first=min(h["years"]), last=max(h["years"]), link=link(h["name"], pref_supp))
                 for h in supp_hist.values()]
    for h in supp_hist:
        h["country"] = "한국" if h["link"] else VCM._country(h["name"])
    # 수출 비중 변천
    exp = {y: (d["years"][y].get("export") or {}).get("export_pct") for y in years if d["years"][y].get("export")}
    # 그물망 — 같은 고객을 적은 다른 회사(수혜 연대), 이 회사를 고객 · 매입처로 적은 회사(위 · 아래 이웃)
    # 같은 그룹(지주 ↔ 자회사: 효성 · 효성중공업 · 효성티앤씨)은 연결 보고로 서로의 고객을 베껴 적는다 — 그물망에서 뺀다
    def _stem(nm):
        s = re.sub(r"\(주\)|㈜|주식회사|홀딩스|지주|그룹|^HS|^HD|^HL", "", nm or "").strip()
        m_ = re.match(r"^[A-Za-z가-힣]{2}", s)
        return m_.group(0) if m_ else s[:2]
    me_stem = _stem(c["name"])
    # 같은 그룹 = 두 글자 어간이 같다(효성 · 효성중공업 · HS효성 · 효성티앤씨). 두 글자가 흔한 말(삼성 · 현대 · 한국)이면 세 글자로 본다
    common = {"한국", "대한", "국제", "동양", "서울", "신한", "제일", "태양", "세계"}
    same_group = lambda nm: bool(me_stem) and me_stem not in common and _stem(nm) == me_stem
    shared = {}
    for h in customers:
        o = own_of(h["name"])
        h["own"] = bool(o)
        h["self"] = o == me_k
        h["via_sub"] = sub_by_key.get(o) if o else None
    for s_ in subs:
        for x in s_["customers"]:
            x["self"] = own_of(x["name"]) == me_k
    my_names = [h["name"] for h in customers if not h["own"] and h["last"] == years[-1]] + \
               [nm for s_ in subs for nm in [x["name"] for x in s_["customers"] if not x["own"]]]
    overlap = {}
    for nm in set(my_names):
        for cd in {t[0] for t in peers["cust"].get(_vc_key(nm), [])}:
            overlap[cd] = overlap.get(cd, 0) + 1
    holders = {cd for cd, n in overlap.items() if cd != c["code"] and n >= 3 and n >= 0.4 * len(set(my_names))}
    _sg = same_group
    same_group = lambda nm, cd=None: _sg(nm) or (cd in holders)
    for h in customers[:12]:
        if h["own"]:
            continue
        for cd, nm, pct, raw in peers["cust"].get(_vc_key(h["name"]), []):
            if cd != c["code"] and not same_group(nm, cd):
                shared.setdefault(cd, {"code": cd, "name": nm, "via": []})["via"].append({"customer": h["name"], "pct": pct})
    # 고객마다 · 종속회사 고객마다 '같은 고객에 파는 다른 상장사' — 그림에서 고객 옆에 바로 붙인다
    def peers_of(nm):
        seen, out_ = set(), []
        for cd, pnm, pct, raw in peers["cust"].get(_vc_key(nm), []):
            if cd != c["code"] and not same_group(pnm, cd) and cd not in seen:
                seen.add(cd)
                out_.append({"code": cd, "name": pnm, "pct": pct})
        return sorted(out_, key=lambda x: -(x["pct"] or 0))
    # peer_n = 이 고객을 주요 매출처로 적은 다른 상장사 수 — 삼성전자 · 현대차처럼 많으면(공급사 17곳) 칩 대신 '공급 상장사 n곳'으로 묶고 역방향 보기로
    for h in customers[:30]:
        ps = [] if h["own"] else peers_of(h["name"])
        h["peers"], h["peer_n"], h["key"] = ps[:5], len(ps), _vc_key(h["name"])
    for s in subs:
        for x in s["customers"]:
            ps = [] if x["own"] else peers_of(x["name"])
            x["peers"], x["peer_n"], x["key"] = ps[:5], len(ps), _vc_key(x["name"])
    # 매입처마다 '같은 곳에서 사는 다른 상장사' — 공급사 쪽 그물망
    for mt in mats:
        for sp in mt["suppliers"]:
            seen, oth = set(), []
            for cd, pnm, pct, raw in peers["supp"].get(_vc_key(sp["name"]), []):
                if cd != c["code"] and not same_group(pnm, cd) and cd not in seen:
                    seen.add(cd)
                    oth.append({"code": cd, "name": pnm})
            sp["others"], sp["others_n"], sp["key"] = oth[:5], len(oth), _vc_key(sp["name"])
            o = own_of(sp["name"])
            sp["own"], sp["self"] = bool(o), o == me_k
    buyers = [{"code": cd, "name": nm, "pct": pct, "as": raw} for cd, nm, pct, raw in peers["supp"].get(me_k, []) if cd != c["code"]]       # 나를 매입처로 적은 회사 = 내 고객
    sellers = [{"code": cd, "name": nm, "pct": pct, "as": raw, "group": same_group(nm, cd)} for cd, nm, pct, raw in peers["cust"].get(me_k, []) if cd != c["code"]]      # 나를 매출처로 적은 회사 = 내 공급사(같은 그룹이면 표시)
    # 수주 공시 상대(최근 2년) — 공시로 드러난 고객
    orders = []
    try:
        since = (dt.date.today() - dt.timedelta(days=730)).strftime("%Y%m%d")
        agg = {}
        for o in _ord_series(c, net=False):
            if o["kind"] != "체결" or o["date"] < since or not o.get("party"):
                continue
            a = agg.setdefault(o["party"], {"party": o["party"], "n": 0, "amount": 0.0, "last": o["date"]})
            a["n"] += 1
            a["amount"] += o.get("amount") or 0
            a["last"] = max(a["last"], o["date"])
        orders = sorted(agg.values(), key=lambda a: -a["amount"])[:10]
        for a in orders:
            a["link"] = link(a["party"])
            # 계약상대 칸에 사업 · 조합 이름을 적는 공시(건설 수주 '답십리 자동차 부품상가 도시정비형 재개발')
            a["kind"] = "사업" if re.search(r"재개발|재건축|정비\s*사업|조합|프로젝트|PJT|현장|신축|구역|공사$|사업$", a["party"]) else "상대"
    except Exception:
        orders = []
    periods = {y: {"label": d["years"][y].get("label") or "사업보고서", "stamp": d["years"][y].get("stamp"),
                   "partial": bool(d["years"][y].get("partial"))} for y in years}
    # 매출처 이름을 적은 해 — 그해 표가 없었으면 다음 해 고객은 '새 고객'이 아니라 '그해부터 적힘'
    cust_years = [y for y in years if any(x.get("kind") == "named" for x in d["years"][y].get("customers") or [])]
    # 무엇을 파나(제품 매출 구성) · 판매경로 — 지금 모습 칸에 없으면 그 앞 해에서
    prods = next((d["years"][y].get("products") for y in reversed(years) if d["years"][y].get("products")), []) or []
    chans = next((d["years"][y].get("channels") for y in reversed(years) if d["years"][y].get("channels")), []) or []
    return {"v": VC_V, "code": c["code"], "name": c["name"], "years": years, "periods": periods, "stamp": last.get("stamp"),
            "customers": customers[:30], "cust_years": cust_years, "products": prods[:12], "channels": chans[:8],
            "hidden": hidden, "no_major": no_major, "types": types, "subs": subs, "materials": mats, "suppliers_hist": supp_hist,
            "export": exp, "segments": last.get("segments") or [], "competition": last.get("competitors") or [],
            "shared": sorted(shared.values(), key=lambda s: -len(s["via"]))[:20], "buyers": buyers, "sellers": sellers,
            "orders": orders, "peer_n": peers["n"]}


def vcbuyer_view(key, kind="cust"):
    """고객(kind='cust') 또는 매입처(kind='supp') 하나를 가운데 두고 — 그 이름을 적은 상장사 전부, 해마다의 비중, 무엇을 파는(사는)지.
    '삼성SDI에 파는 상장사 8곳' · '포스코에서 사는 상장사 10곳'처럼 산업 단위로 같이 움직일 회사를 본다."""
    if VCM is None or not key:
        return None
    peers = _vc_peers()
    rows0 = peers["supp" if kind == "supp" else "cust"].get(key) or []
    if not rows0:
        return {"key": key, "kind": kind, "name": key, "rows": [], "years": []}
    import collections
    names = collections.Counter(r[3] for r in rows0)
    disp = _vc_canon(names.most_common(1)[0][0])
    univ = {x["code"]: x for x in INDEX["companies"]}
    out, yrs = [], set()
    for cd in dict.fromkeys(r[0] for r in rows0):
        c = univ.get(cd)
        if not c:
            continue
        try:
            d = _vc_company(c)
        except Exception:
            continue
        ys = sorted(d["years"])
        by, seg, basis, item = {}, None, None, None
        for y in ys:
            L = d["years"][y]
            if kind == "supp":
                for mt in L.get("materials") or []:
                    if any(_vc_key(sp["name"]) == key for sp in mt.get("suppliers") or []):
                        by[y] = max(by.get(y) or 0, mt.get("pct") or 0) or by.get(y)
                        if y == ys[-1]:
                            item, seg = mt.get("item"), mt.get("segment")
            else:
                cands = [x for x in L.get("customers") or [] if x.get("kind") == "named" and _vc_key(x["name"]) == key]
                cands += [{"pct": p_} for s_ in L.get("subs") or [] for nm_, p_ in (s_.get("final") or s_.get("customers") or []) if _vc_key(nm_) == key]
                if cands:
                    by[y] = max((x.get("pct") or 0) for x in cands) or None
                    if y == ys[-1]:
                        seg, basis = cands[0].get("seg"), cands[0].get("basis")
        if not by:
            continue
        yrs |= set(by)
        L = d["years"][ys[-1]]
        prod = next((p_.get("item") for p_ in sorted(L.get("products") or [], key=lambda p_: -(p_.get("amt") or p_.get("pct") or 0))), None)
        last_y = max(by)
        out.append({"code": cd, "name": c["name"], "pct": by.get(ys[-1]), "last": last_y, "by_year": by, "seg": seg, "basis": basis,
                    "item": item, "product": prod, "periods": {y: bool(d["years"][y].get("partial")) for y in by}})
    out.sort(key=lambda r: (r["last"] != max(r["by_year"]), -(r["pct"] or 0)))
    # 지주가 연결로 자회사 숫자를 그대로 적은 것(효성 = 효성중공업, LS = 엘에스일렉트릭) — 두 해 넘게 같은 비중이면 짧게 적힌 쪽(지주)을 '연결' 로 표시
    for a in out:
        for b in out:
            if a is b or a.get("dup") or b.get("dup"):
                continue
            same = [y for y in a["by_year"] if a["by_year"][y] and b["by_year"].get(y) == a["by_year"][y]]
            if len(same) >= 2 and len(a["by_year"]) <= len(b["by_year"]) and (len(a["by_year"]) < len(b["by_year"]) or len(a["name"]) < len(b["name"])):
                a["dup"] = b["name"]
    lk = None
    cd = _listed_names().get(_norm_corp(disp))
    if cd:
        lk = {"code": cd, "collected": cd in univ}
    return {"key": key, "kind": kind, "name": disp, "aka": [n for n, _ in names.most_common(6) if n != disp], "link": lk,
            "rows": out, "years": sorted(yrs)}


# ---------------------------------------------------------------- 리포트: 증권사 텔레그램 채널의 기업 · 산업 리포트 (2026-10-04)
# 리포트.py 가 내 계정으로 구독한 증권사 채널 글을 받아 .cache/리포트/ 에 쌓고(도구/리포트_수집.py), 여기서 종목별로 묶는다.
# 처음 한 번은 사람이 터미널에서 도구/텔레그램_로그인.py 로 로그인한다. 뷰어는 그 세션으로 2시간마다(07~22시) 새 글만 받는다.
try:
    _repspec = _ilu.spec_from_file_location("리포트", os.path.join(BASE, "리포트.py"))
    REP = _ilu.module_from_spec(_repspec)
    _repspec.loader.exec_module(REP)
except Exception as _e:
    REP = None
    print("리포트 모듈 로드 실패:", _e)
REP_LOCK = threading.Lock()
REP_BUILD_LOCK = threading.Lock()   # 다시 읽기는 한 번에 하나(콜드 74초 · 338MB — 32비트에서 둘이 겹치면 메모리가 모자란다)
_REP = {"sig": None, "rows": [], "by_code": {}}
REP_RUN = {"running": False, "at": 0, "msg": ""}


def _rep_rows():
    """쌓인 글 → 리포트 항목(종목별 묶음). 쌓인 파일이 바뀌었을 때만 다시 읽는다.
    누가 이미 읽는 중이면 기다렸다가 그 결과를 쓴다(내러티브 뒤 스레드 · 리포트 탭이 같이 불러도 한 번만)."""
    if REP is None:
        return _REP
    sig = REP.store_sig()
    with REP_LOCK:
        if _REP["sig"] == sig:
            return _REP
    with REP_BUILD_LOCK:
        sig = REP.store_sig()
        with REP_LOCK:
            if _REP["sig"] == sig:
                return _REP
        names = {c["name"]: c["code"] for c in INDEX["companies"]}
        codes = {c["code"]: c["name"] for c in INDEX["companies"]}
        rows = REP.build(names, codes)
        by = {}
        for r in rows:
            if r.get("code"):
                by.setdefault(r["code"], []).append(r)
        with REP_LOCK:
            _REP.update(sig=sig, rows=rows, by_code=by)
    return _REP


def reports_status():
    if REP is None:
        return {"ready": False, "why": "리포트 모듈이 없습니다"}
    import 설정 as _cfg
    st = REP._load_state()
    return {"ready": REP.can_collect(), "creds": bool(_cfg.get("TELEGRAM_API_ID") and _cfg.get("TELEGRAM_API_HASH")),
            "session": REP.session_exists(), "web": REP.web_channels(), "channels": [v.get("title") for v in st.get("channels", {}).values()],
            "last": st.get("at") or 0, "running": REP_RUN["running"], "msg": REP_RUN["msg"]}


def reports_view(code):
    """한 종목의 리포트 — 최근 것부터, 증권사마다 최신 목표가 · 직전 목표가, 목표가 평균과 현재가 괴리, 의견 분포, 목표가 · 주가 그림."""
    c = company_by_code(code)
    if not c:
        return None
    R = _rep_rows()
    rows = R["by_code"].get(code, [])
    today = dt.date.today()
    recent = [r for r in rows if r["date"][:10] >= (today - dt.timedelta(days=180)).isoformat()]
    latest = {}
    for r in rows:                               # 최근 것부터 — 증권사마다 첫 목표가가 최신(증권사를 안 적은 요약 채널 글은 리포트마다 따로)
        b = r.get("broker") or ("미표기 · %s %s" % (r["date"][5:10], (r.get("title") or "")[:14]))
        if r.get("tp") and b not in latest:
            latest[b] = r
    tps = [r["tp"] for b, r in latest.items() if r["date"][:10] >= (today - dt.timedelta(days=180)).isoformat()]
    price = None
    series = []
    if FIN is not None:
        try:
            since_px = (today - dt.timedelta(days=760)).strftime("%Y%m%d")
            pr = FIN.fetch_prices(code)
            ks = [k for k in sorted(pr) if k >= since_px]      # 캐시는 2010년부터 — 그림은 최근 2년만
            if ks:
                price = pr[ks[-1]]
                series = [[k[:4] + "-" + k[4:6] + "-" + k[6:], pr[k]] for k in ks[::2]]
        except Exception:
            pass
    ops = {}
    for r in recent:
        if r.get("opinion"):
            ops[r["opinion"]] = ops.get(r["opinion"], 0) + 1
    avg = sum(tps) / len(tps) if tps else None
    return {"code": code, "name": c["name"], "rows": rows[:600], "n180": len(recent), "brokers": len({r.get("broker") for r in recent if r.get("broker")}), "no_broker": sum(1 for r in recent if not r.get("broker")),
            "tp_avg": avg, "tp_max": max(tps) if tps else None, "tp_min": min(tps) if tps else None, "price": price,
            "upside": (avg / price - 1) * 100 if avg and price else None, "opinions": ops,
            "latest": sorted(({"broker": b, "tp": r["tp"], "tp_prev": r.get("tp_prev"), "date": r["date"], "opinion": r.get("opinion")} for b, r in latest.items()),
                             key=lambda x: x["date"], reverse=True),
            "tp_points": [{"date": r["date"][:10], "tp": r["tp"], "broker": r.get("broker")} for r in rows if r.get("tp")],
            "series": series, "status": reports_status()}


def _rep_sector(r):
    k = r.get("sector") or "기타"
    return k.upper() if re.fullmatch(r"[A-Za-z&\s]+", k) else k          # 'ai' · 'AI' 를 하나로


def reports_recent(kind="", days=14, sector="", q="", mention="", offset=0, limit=60):
    """최근 리포트 — 산업 리포트 칸. 업종 · 찾는 말 · 종목 이름 언급으로 걸러 쪽(limit)만 준다(1년치는 1만 건이 넘는다). 업종별 건수는 거르기 전 기준."""
    R = _rep_rows()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    base = [r for r in R["rows"] if r["date"][:10] >= since and (not kind or r["kind"] == kind)]
    secs = {}
    for r in base:
        k = _rep_sector(r)
        secs[k] = secs.get(k, 0) + 1
    hay = lambda r: ((r.get("title") or "") + " " + " ".join(r.get("lines") or []) + " " + (r.get("concl") or "") + " " + (r.get("sector") or "")).lower()
    q, mention = (q or "").strip().lower(), (mention or "").strip().lower()
    rows = [r for r in base if (not sector or _rep_sector(r) == sector) and (not q or q in hay(r)) and (not mention or mention in hay(r))]
    return {"rows": rows[offset:offset + limit], "total": len(rows), "all": len(base), "oldest": base[-1]["date"][:10] if base else None,
            "sectors": sorted(secs.items(), key=lambda kv: -kv[1])[:24], "status": reports_status()}


def _rep_collect():
    """도구/리포트_수집.py 를 따로 띄워 새 글만 받는다(Telethon 은 자기 이벤트 루프를 쓴다 — 뷰어 실과 떼어 둔다)."""
    if REP is None or not REP.can_collect() or REP_RUN["running"]:
        return
    REP_RUN["running"] = True
    try:
        exe = sys.executable.replace("pythonw.exe", "python.exe")
        log = os.path.join(BASE, "리포트_auto.log")
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("\n== %s\n" % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
            fh.flush()
            r = subprocess.run([exe, os.path.join(BASE, "도구", "리포트_수집.py")], cwd=BASE, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=1200, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        REP_RUN["msg"] = "끝(%d)" % r.returncode
    except Exception as e:
        REP_RUN["msg"] = "실패: %s" % e
    finally:
        REP_RUN.update(running=False, at=time.time())


def _rep_auto_loop():
    """뷰어가 켜지고 3분 뒤 한 번, 그 뒤 07~22시에 2시간마다 — 로그인 세션이 있을 때만."""
    time.sleep(180)
    while True:
        try:
            h = dt.datetime.now().hour
            if REP is not None and REP.can_collect() and (7 <= h <= 22 or not REP_RUN["at"]):
                _rep_collect()
        except Exception as e:
            print("리포트 자동 수집: %s" % e, flush=True)
        time.sleep(7200)


# ---------------------------------------------------------------- HTTP
# ---------------------------------------------------------- 기록 채점 · 매매 일지 (2026-10-10)
# 기록 채점: 매일 남긴 판정(저평가 실전 기록 forward/*.json · 차트 발굴 일지 Tech/output/journal.csv)을
#   그 뒤 실제 주가로 잰다 — 백테스트가 아닌 진짜 표본 밖 성적. 계산은 기록채점.py(표준 라이브러리만).
# 매매 일지: 실제 매매와 산 이유 · 생각을 바꿀 조건을 적고, 보유 · 끝난 매매 · 도구별 성적을 본다. 계산은 매매일지.py.
#   개인 자료라 기업추적/개인/매매일지.json(.gitignore — 공개 저장소에 안 올라감, 구글 드라이브로 백업)에 둔다.
def _load_mod(name):
    try:
        sp = _ilu.spec_from_file_location(name, os.path.join(BASE, name + ".py"))
        m = _ilu.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m
    except Exception as e:
        print("%s 모듈 로드 실패: %s" % (name, e))
        return None


SCR = _load_mod("기록채점")
TRD = _load_mod("매매일지")
SCORE_DIR = os.path.join(CACHE_DIR, "score")
SCORE_FWD = os.path.join(VAL_DIR, "forward")
SCORE = {"running": False, "at": None, "result": None, "error": None}
SCORE_LOCK = threading.Lock()
SCORE_MAX_AGE = 6 * 3600          # 채점 결과가 이보다 묵으면 볼 때 다시 잰다(주가는 매일 06:30 새로)


def _score_journal_path():
    return os.path.join(TECH_DIR, "output", "journal.csv")


def _last_close():
    """(지금, 가장 최근 장 마감 15:40 시각, 지금 장중인가). 휴장일 달력은 모른다(주말만) — 넉넉한 쪽."""
    now = dt.datetime.now()
    lc = now.replace(hour=15, minute=40, second=0, microsecond=0)
    while lc > now or lc.weekday() >= 5:
        lc = (lc - dt.timedelta(days=1)).replace(hour=15, minute=40)
    live = now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) < (15, 40)
    return now, lc, live


def _px_file(code):
    """채점 · 벤치마크용 종가 {YYYYMMDD: 종가} — .cache/price(저평가가 매일 새로 받는 988곳),
    없으면 .cache/ohlcv 의 종가. 네트워크는 쓰지 않는다. 장중에 받은 오늘 봉(미완성)은 뺀다."""
    for sub, k in (("price", None), ("ohlcv", 3)):
        try:
            with open(os.path.join(CACHE_DIR, sub, code + ".json"), "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d:
            if k is not None:
                d = {dd: v[k] for dd, v in d.items() if isinstance(v, list) and len(v) > k}
            _, _, live = _last_close()
            if live:
                d.pop(dt.date.today().strftime("%Y%m%d"), None)
            return d
    return None


def _score_universe():
    """벤치마크 유니버스 = .cache/price 에 종가가 있는 회사(시총 상위 수집 대상)."""
    try:
        return sorted(f[:-5] for f in os.listdir(os.path.join(CACHE_DIR, "price")) if f.endswith(".json"))
    except OSError:
        return []


def _score_inputs_mtime():
    ts = [0.0]
    for p in [_score_journal_path()] + ([os.path.join(SCORE_FWD, f) for f in os.listdir(SCORE_FWD)]
                                         if os.path.isdir(SCORE_FWD) else []):
        try:
            ts.append(os.path.getmtime(p))
        except OSError:
            pass
    return max(ts)


def _run_score():
    try:
        jp = _score_journal_path()
        # 일지 종목 중 .cache/price 에 없는 것(시총 상위 밖)은 일봉 캐시를 하루 한 번 새로 받는다 — 24시간 캐시
        if FIN is not None and os.path.isfile(jp):
            try:
                codes = sorted({r["code"] for r in SCR.load_journal(jp)})
            except Exception:
                codes = []
            now, lc, _ = _last_close()
            age = max(60, (now - lc).total_seconds())     # 마지막 장 마감 전에 받은 캐시면 다시(장중 봉을 하루 들고 있지 않게)
            for c in codes:
                if not os.path.exists(os.path.join(CACHE_DIR, "price", c + ".json")):
                    try:
                        FIN.fetch_ohlcv(c, max_age=age)
                    except Exception:
                        pass
        mt = _score_inputs_mtime()
        res = SCR.run(SCORE_FWD, jp, _px_file, _score_universe())
        res["inputs_mtime"] = mt
        with SCORE_LOCK:                 # 화면에는 바로 — 파일 저장은 덤(드라이브가 잡고 있어도 결과는 안 버린다)
            SCORE.update(result=res, at=time.time(), error=None)
        try:
            import tempfile
            os.makedirs(SCORE_DIR, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="_result.", suffix=".tmp", dir=SCORE_DIR)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(res, fh, ensure_ascii=False)
                (TRD._replace if TRD is not None else os.replace)(tmp, os.path.join(SCORE_DIR, "_result.json"))
            except BaseException:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            print("기록 채점 결과 저장 실패(화면에는 보인다): %s" % type(e).__name__, flush=True)
    except Exception as e:
        with SCORE_LOCK:
            SCORE["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        with SCORE_LOCK:
            SCORE["running"] = False


def score_view(force=False):
    if SCR is None:
        return {"error": "기록채점.py 를 읽지 못했습니다"}
    with SCORE_LOCK:
        if SCORE["result"] is None and not SCORE["running"]:
            try:
                p = os.path.join(SCORE_DIR, "_result.json")
                with open(p, "r", encoding="utf-8") as fh:
                    SCORE.update(result=json.load(fh), at=os.path.getmtime(p))
            except (OSError, ValueError):
                pass
        res = SCORE["result"]
        stale = force or res is None or time.time() - (SCORE["at"] or 0) > SCORE_MAX_AGE \
            or _score_inputs_mtime() > (res or {}).get("inputs_mtime", 0)
        if stale and not SCORE["running"]:
            SCORE["running"] = True
            threading.Thread(target=_run_score, daemon=True).start()
        return {"running": SCORE["running"], "at": SCORE["at"], "error": SCORE["error"], "result": SCORE["result"]}


TRD_LOCK = threading.Lock()
_TRD_BENCH = {"at": 0.0, "since": None, "prices": None, "univ": None}
_TRD_BENCH_LOCK = threading.Lock()


def _trd_price(code):
    """보유 종목 현재가 = 마지막 종가(네이버 일별 시세, 하루 한 번 새로). 못 구하면 증권사 스냅샷 가격."""
    px = None
    try:
        if FIN is not None:
            if os.path.exists(os.path.join(CACHE_DIR, "price", code + ".json")):
                px = FIN.fetch_prices(code)          # 수집 회사(988곳) — 저평가가 매일 새로 받는 캐시
            else:                                     # 그 밖은 일봉 캐시로 — .cache/price 에 새 파일을 만들면
                ov = FIN.fetch_ohlcv(code) or {}      # 채점 유니버스 · 새로 받기 판단이 어긋난다
                px = {k: v[3] for k, v in ov.items() if isinstance(v, list) and len(v) > 3 and v[3]}
    except Exception:
        px = None
    if px:
        d = max(px)
        return float(px[d]), d
    snap = _kis_snapshot() or {}
    st = (snap.get("status") or {}).get(code) or {}
    if st.get("px"):
        return float(st["px"]), snap.get("date")
    return None, None


def _trd_warm(since):
    """벤치마크용 유니버스 주가(988곳 파일)를 미리 읽어 둔다 — 처음엔 드라이브에서 40초 안팎 걸려 화면을 막지 않게 따로."""
    try:
        P, U = SCR.Prices(_px_file, since=since), _score_universe()
        for c in U:
            P.series(c)
        with _TRD_BENCH_LOCK:
            _TRD_BENCH.update(prices=P, univ=U, since=since, at=time.time())
    except Exception as e:
        print("매매 일지 벤치마크 준비 실패: %s" % e, flush=True)
    finally:
        with _TRD_BENCH_LOCK:
            _TRD_BENCH["warming"] = False


def _trd_bench(trades):
    """같은 기간 유니버스 종목 수익률 중앙값(%) 함수 — 기록 채점과 같은 벤치마크. 주가는 한 시간 동안 들고 있는다.
    아직 준비 전이면 None 을 돌려주고 뒤에서 읽기 시작한다(화면에는 '계산 중')."""
    if SCR is None or not trades:
        return None
    ds = sorted(d for d in (TRD._as_date(t.get("date")) for t in trades) if d)   # 못 읽는 행은 장부처럼 건너뛴다
    if not ds:
        return None
    since = (ds[0] - dt.timedelta(days=15)).strftime("%Y%m%d")
    with _TRD_BENCH_LOCK:
        b = _TRD_BENCH
        have = b["prices"] is not None and since >= (b["since"] or since)
        if (not have or time.time() - b["at"] > 3600) and not b.get("warming"):
            b["warming"] = True          # 한 시간 지났으면 뒤에서 새로 읽고, 그동안은 들고 있던 값으로
            threading.Thread(target=_trd_warm, args=(since,), daemon=True).start()
        if not have:
            return None
        P, U = b["prices"], b["univ"]

    def f(d0, d1):
        with _TRD_BENCH_LOCK:
            v = SCR.bench(P, U, d0, d1)
        return None if v is None else v * 100.0
    return f


def _trd_path_label(path):
    try:
        rel = os.path.relpath(path, BASE)
        return rel if not rel.startswith("..") else os.path.basename(path)
    except ValueError:
        return os.path.basename(path)


def trades_view():
    if TRD is None:
        return {"error": "매매일지.py 를 읽지 못했습니다"}
    path = TRD.default_path()
    with TRD_LOCK:
        try:
            data = TRD.load(path)
        except ValueError as e:
            return {"error": str(e), "path": _trd_path_label(path)}
    trades = data.get("trades") or []
    bench = _trd_bench(trades)
    bk = TRD.book(trades, _trd_price, bench)
    trades = sorted(trades, key=lambda t: (str(t.get("date") or ""), str(t.get("created") or "")), reverse=True)
    return {"trades": trades, "book": bk, "sources": TRD.sources_meta(), "horizons": TRD.horizons_meta(),
            "path": _trd_path_label(path), "today": dt.date.today().isoformat(),
            "bench_pending": bool(trades) and bench is None and SCR is not None}


def trades_change(body):
    """POST /api/trades {action: add|update|delete, trade: {...} | id} → 바뀐 뒤 화면 자료. 문제가 있으면 ValueError."""
    if TRD is None:
        raise ValueError("매매일지.py 를 읽지 못했습니다")
    if not isinstance(body, dict):
        raise ValueError("입력이 객체가 아닙니다")
    action = body.get("action")
    payload = {"id": body.get("id")} if action == "delete" else body.get("trade")
    path = TRD.default_path()
    with TRD_LOCK:
        data = TRD.load(path)
        new = TRD.apply(data, action, payload)
        TRD.save(path, new)
    return trades_view()


# ---------------------------------------------------------- 내러티브 — 이 종목 소식 피드 (2026-10-11)
# 설계: docs/superpowers/specs/2026-10-11-story-feed-design.md 3절. 계산은 내러티브.py(표준 라이브러리만).
# 언론 기사 제목(Tech 하위 프로세스가 KIS 에서 받은 캐시) · 리포트 · 공시 · 정기보고서를 날짜순 한 줄로.
# 이름 주의: /api/narrative · narrative_view 는 키워드 추이 탭의 '말과 주가' — 이 탭은 story.
# 무거운 것(_rep_rows 콜드 74초 · 공시 색인 첫 빌드 · 시장 중앙)은 뒤 스레드에서만. vocab · brief · 계약은 캐시 파일만 읽는다.
NAR = _load_mod("내러티브")
STORY_V = 1
STORY_DIR = os.path.join(CACHE_DIR, "story")
STORY_LOCK = threading.Lock()
STORY = {"running": False, "code": None, "step": "", "want": {}, "err": {}, "memo": {}}
STORY_WANT_TTL = 120              # 이만큼(초) 다시 안 물은 회사는 만들 차례에서 뺀다(화면을 떠났다)
STORY_ERR_TTL = 600               # 같은 입력으로 실패했으면 이 동안 다시 만들지 않는다(폴링이 실패를 되풀이하지 않게)
STORY_DISC_DIR = os.path.join(CACHE_DIR, "공시목록")
STORY_DISC = {"building": False, "checked": 0.0, "error": None}
STORY_DISC_LOCK = threading.Lock()   # 공시 색인은 전역 하나
STORY_DISC_EVERY = 600            # 증분 확인 간격(초)
STORY_MKT = {"building": False, "med": None, "built": None, "mtime": 0}
STORY_MKT_DAYS = 800              # 시장 중앙값을 세는 기간(달력 일)
STORY_NEWS = {"running": False, "code": None, "queue": {}, "tried": {}, "sup": (0.0, False)}   # queue = {code: 마지막으로 물은 때}
STORY_NEWS_TTL = 1800             # 뉴스 파일이 이보다 묵으면 다시 받는다
STORY_NEWS_TIMEOUT = 180


def _story_path(code):
    return os.path.join(STORY_DIR, code + ".json")


def _story_news_path(code):
    return os.path.join(TECH_DIR, "cache", "kis", "news", code + ".json")


def _story_mtime(p):
    try:
        return int(os.path.getmtime(p))
    except OSError:
        return 0


def _story_brief_mtime(code):
    """brief 폴더와 그 안 파일들의 가장 늦은 시각(요약만 다시 써도 바뀌게)."""
    p = os.path.join(CACHE_DIR, "brief", code)
    try:
        m = os.path.getmtime(p)
        with os.scandir(p) as it:
            for e in it:
                m = max(m, e.stat().st_mtime)
        return int(m)
    except OSError:
        return 0


def _story_sig(c):
    """뉴스 파일 · 리포트 · 공시 색인 + 열린 분기 · 보고서(가장 늦은 접수번호 · 수) · vocab · brief · 계약 캐시 폴더 ·
    시장 중앙 · 주가 파일(price · ohlcv) · 오늘. c["reports"] 는 기간순이라 [-1] 은 옛 기간 [기재정정]을 놓친다 — max(rcept)."""
    code = c["code"]
    rep = "%08x" % (zlib.crc32(REP.store_sig().encode("utf-8")) & 0xffffffff) if REP is not None else "-"
    return "|".join(str(x) for x in (
        "%d.%d.%d" % (STORY_V, NAR.FEED_V, NAR.NEWS_RULE_V), _story_mtime(_story_news_path(code)), rep, NAR.disc_sig(STORY_DISC_DIR),
        "%s.%d" % (max((r["rcept"] for r in c["reports"]), default=""), len(c["reports"])),
        _story_mtime(os.path.join(CACHE_DIR, "vocab", code + ".json")), _story_brief_mtime(code),
        _story_mtime(os.path.join(CACHE_DIR, "시너지", "계약")), STORY_MKT["built"] or "-",
        _story_mtime(os.path.join(CACHE_DIR, "price", code + ".json")), _story_mtime(os.path.join(CACHE_DIR, "ohlcv", code + ".json")),
        dt.date.today().strftime("%Y%m%d")))


# ---- 공시 색인 · 시장 중앙 — 전역 하나씩, 뒤에서
def _story_disc():
    """공시 색인 — 없으면 만들고(전역 하나 · 처음 30초 안팎), 10분에 한 번까지 증분 확인. 뒤 스레드에서만 부른다."""
    with STORY_DISC_LOCK:
        ready = NAR.disc_index_ready(STORY_DISC_DIR)
        if ready and time.time() - STORY_DISC["checked"] < STORY_DISC_EVERY:
            return
        STORY_DISC["building"] = not ready
        try:
            r = NAR.disc_index_update(STORY_DISC_DIR)
            STORY_DISC["error"] = None
            if r["mode"] != "none":
                print("공시 색인(%s): 파일 %d · 줄 %d · %.1f초" % (r["mode"], r["files"], r["rows"], r["secs"]), flush=True)
        except Exception as e:
            STORY_DISC["error"] = "%s: %s" % (type(e).__name__, e)
            print("공시 색인 실패: %s" % STORY_DISC["error"], flush=True)
        finally:
            STORY_DISC.update(building=False, checked=time.time())


def _story_mkt_path():
    return os.path.join(STORY_DIR, "_mkt_med.json")


def _story_mkt_stale(built):
    """하루 한 번 — 오늘 만든 것이 아니거나, 06:40(주가 새로 받은 뒤) 전에 만든 것을 그 뒤에 보면 다시."""
    if not built:
        return True
    now = dt.datetime.now()
    if built[:10] != now.strftime("%Y-%m-%d"):
        return True
    return built[11:16] < "06:40" <= now.strftime("%H:%M")


def _story_mkt_run():
    try:
        since = (dt.date.today() - dt.timedelta(days=STORY_MKT_DAYS)).strftime("%Y%m%d")
        t0 = time.time()
        med = NAR.build_mkt_med(_px_file, _score_universe(), since)
        built = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        os.makedirs(STORY_DIR, exist_ok=True)
        NAR._write_json(_story_mkt_path(), {"v": 1, "built": built, "since": since, "n": len(med), "med": med})
        STORY_MKT.update(med=med, built=built, mtime=_story_mtime(_story_mkt_path()))
        print("시장 중앙(내러티브): %d일 · %.0f초" % (len(med), time.time() - t0), flush=True)
    except Exception as e:
        print("시장 중앙(내러티브) 실패: %s: %s" % (type(e).__name__, e), flush=True)
    finally:
        STORY_MKT["building"] = False


def _story_mkt():
    """{YYYYMMDD: 그날 전 종목 등락 중앙값 %} 또는 None(준비 전). 파일은 하루 한 번 뒤에서 다시 만든다."""
    p = _story_mkt_path()
    m = _story_mtime(p)
    if m and m != STORY_MKT["mtime"]:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            STORY_MKT.update(med=d.get("med") or {}, built=d.get("built"), mtime=m)
        except (OSError, ValueError):
            pass
    with STORY_LOCK:
        if _story_mkt_stale(STORY_MKT["built"]) and not STORY_MKT["building"]:
            STORY_MKT["building"] = True
            threading.Thread(target=_story_mkt_run, daemon=True).start()
    return STORY_MKT["med"]


# ---- 뉴스 — Tech 하위 프로세스(64비트 venv · KIS 조회 전용 시세 API), 전역 하나씩
def _story_news_ok():
    """뉴스를 받을 수 있나 — Tech 파이썬이 있고 Tech CLI 가 news 하위 명령을 안다(옛 판이면 안 띄운다). 1분 기억."""
    t, ok = STORY_NEWS["sup"]
    if time.time() - t > 60:
        ok = os.path.exists(TECH_PY) and _tech_supports('add_parser("news"')
        STORY_NEWS["sup"] = (time.time(), ok)
    return ok


def _story_news_age(code):
    try:
        return time.time() - os.path.getmtime(_story_news_path(code))
    except OSError:
        return None


def _story_news_kick(code, refresh=False):
    """뉴스 파일이 없거나 30분보다 묵었으면(또는 refresh) 뒤에서 받는다. 반환: 이 회사 뉴스를 받는 중(또는 차례 대기)인가.
    실패해도 30분(refresh 면 1분)은 다시 띄우지 않는다 — 폴링이 실패를 되풀이하지 않게.
    차례는 가장 최근에 물은 회사부터 · STORY_WANT_TTL 동안 다시 안 물은 회사는 뺀다(화면을 떠났다 — 화면이 3초마다 묻는다)."""
    if NAR is None or not _story_news_ok():
        return False
    with STORY_LOCK:
        N = STORY_NEWS
        if code == N["code"]:
            return True
        if code in N["queue"]:
            N["queue"][code] = time.time()
            return True
        age = _story_news_age(code)
        last = N["tried"].get(code)
        due = refresh or age is None or age > STORY_NEWS_TTL
        if last and time.time() - last[0] < (60 if refresh else STORY_NEWS_TTL):
            due = False
        if not due:
            return False
        N["queue"][code] = time.time()
        if not N["running"]:
            N["running"] = True
            threading.Thread(target=_story_news_loop, daemon=True).start()
    return True


def _story_news_loop():
    while True:
        with STORY_LOCK:
            N, now = STORY_NEWS, time.time()
            for k in [k for k, t in N["queue"].items() if now - t > STORY_WANT_TTL]:
                N["queue"].pop(k, None)             # 떠난 회사 — tried 에 안 남기니 다시 오면 다시 줄 선다
            if not N["queue"]:
                N.update(running=False, code=None)
                return
            code = max(N["queue"], key=N["queue"].get)     # 가장 최근에 물은 회사부터
            N["queue"].pop(code, None)
            N["code"] = code
        first = not os.path.exists(_story_news_path(code))      # 첫 받기 60쪽/100초, 이후 10쪽/30초
        cmd = [TECH_PY, "-m", "chart_screener", "news", "--codes", code,
               "--pages", "60" if first else "10", "--budget", "100" if first else "30"]
        rc, note = None, ""
        try:
            si = None
            if os.name == "nt":
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0          # SW_HIDE
            r = subprocess.run(cmd, cwd=TECH_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=STORY_NEWS_TIMEOUT, env=dict(os.environ, PYTHONIOENCODING="utf-8"), startupinfo=si,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            rc = r.returncode
            lines = [ln.split("\r")[-1].strip() for ln in (r.stdout or b"").decode("utf-8", "replace").splitlines()]
            lines = [ln for ln in lines if ln]
            if rc != 0:
                note = (lines[-1] if lines else "종료 코드 %s" % rc)[:120]
        except subprocess.TimeoutExpired:
            rc, note = -1, "뉴스 받기가 %d초를 넘었습니다" % STORY_NEWS_TIMEOUT
        except Exception as e:
            rc, note = -2, "뉴스 받기를 띄우지 못했습니다: %s" % type(e).__name__
        with STORY_LOCK:
            STORY_NEWS["tried"][code] = (time.time(), rc, note)
            STORY_NEWS["code"] = None


def _story_news_read(code):
    """Tech 뉴스 캐시 → (rows, 머리) 또는 (None, None)."""
    try:
        with open(_story_news_path(code), "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None, None
    if not isinstance(d, dict) or not isinstance(d.get("rows"), list):
        return None, None
    return d["rows"], {k: d.get(k) for k in ("at", "complete", "capped", "oldest", "newest", "floor", "pages")}


# ---- 회사 하나 만들기 — 뒤 스레드 하나(한 번에 한 회사)
def _story_gists(c):
    """{rcept: {"gist": [...], "first": 첫 보고서인가}} — brief 캐시에 있고 gist_v 가 지금 판(GIST_V)일 때만(빈 gist 도 —
    첫 보고서 · 바뀐 것 없음은 궤도 탭을 열어도 안 채워진다). 없는 요약을 만들지 않는다."""
    out = {}
    try:
        have = set(os.listdir(os.path.join(CACHE_DIR, "brief", c["code"])))
    except OSError:
        return out
    for r in c["reports"]:
        if r["rcept"] + ".json" not in have:
            continue
        try:
            with open(brief_path(c["code"], r["rcept"]), "r", encoding="utf-8") as fh:
                b = json.load(fh)
        except (OSError, ValueError):
            continue
        if b.get("gist_v") == GIST_V and isinstance(b.get("gist"), list):
            out[r["rcept"]] = {"gist": b["gist"], "first": bool(b.get("first"))}
    return out


def _story_contracts(discs):
    """{rcept: 계약 칸} — 단일판매 · 공급계약 공시 중 시너지 계약 캐시에 이미 있는 것만(DART 를 부르지 않는다)."""
    out = {}
    for x in discs or ():
        if ORD_RX.search(x["title"]):
            try:
                with open(os.path.join(CACHE_DIR, "시너지", "계약", x["rcept"] + ".json"), "r", encoding="utf-8") as fh:
                    out[x["rcept"]] = json.load(fh)
            except (OSError, ValueError):
                pass
    return out


def _story_build(code):
    c = company_by_code(code)
    if not c:
        return
    STORY["step"] = "공시 색인 확인"
    _story_disc()                   # 처음이면 색인을 만든다(manifest 시각이 sig 에 들어가니 sig 는 그 뒤에)
    sig = _story_sig(c)             # 읽기 전에 — 만드는 사이 입력이 바뀌면 다음 요청이 다시 만든다
    discs = NAR.disc_rows(code, STORY_DISC_DIR)
    STORY["step"] = "리포트 읽기"
    reps = [dict(r) for r in _rep_rows()["by_code"].get(code, [])] if REP is not None else []
    STORY["step"] = "뉴스 · 주가 · 보고서 요약 읽기"
    news, meta = _story_news_read(code)
    series = NAR.adjusted(_px_file(code) or {})
    vocab = None
    try:
        with open(os.path.join(CACHE_DIR, "vocab", code + ".json"), "r", encoding="utf-8") as fh:
            vocab = json.load(fh)
    except (OSError, ValueError):
        pass
    STORY["step"] = "합치기"
    d = NAR.build_feed(code, c["name"], today=dt.date.today(), news=news, news_meta=meta, reports=reps, discs=discs,
                       filings=c["reports"], gists=_story_gists(c), series=series, mkt=_story_mkt(),
                       links=NAR.vocab_links(vocab), classify_disc=GOOD.classify if GOOD is not None else None,
                       contracts=_story_contracts(discs))
    d["sig"] = sig
    os.makedirs(STORY_DIR, exist_ok=True)
    NAR._write_json(_story_path(code), d)


def _story_loop():
    while True:
        with STORY_LOCK:
            now = time.time()
            for k in [k for k, t in STORY["want"].items() if now - t > STORY_WANT_TTL]:
                STORY["want"].pop(k, None)
            if not STORY["want"]:
                STORY.update(running=False, code=None, step="")
                return
            code = max(STORY["want"], key=STORY["want"].get)     # 가장 최근에 물은 회사부터
            STORY["want"].pop(code, None)
            STORY.update(code=code, step="준비")
        try:
            _story_build(code)
            STORY["err"].pop(code, None)
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                sig = _story_sig(company_by_code(code))      # 같은 입력이면 STORY_ERR_TTL 동안 다시 안 만든다
            except Exception:
                sig = ""
            STORY["err"][code] = (time.time(), sig, "%s: %s" % (type(e).__name__, e))
        finally:
            with STORY_LOCK:
                STORY.update(code=None, step="")


def _story_kick(code):
    with STORY_LOCK:
        STORY["want"][code] = time.time()
        if not STORY["running"]:
            STORY["running"] = True
            threading.Thread(target=_story_loop, daemon=True).start()


def _story_read(code):
    """캐시 payload — 파일 시각으로 기억(최근 몇 곳만)."""
    p = _story_path(code)
    try:
        m = os.path.getmtime(p)
    except OSError:
        return None
    hit = STORY["memo"].get(code)
    if hit and hit[0] == m:
        return hit[1]
    try:
        with open(p, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    with STORY_LOCK:
        if len(STORY["memo"]) >= 3:
            STORY["memo"].clear()
        STORY["memo"][code] = (m, d)
    return d


def _story_news_note(code, running, has_news):
    if running:
        return "받는 중"
    if not os.path.exists(TECH_PY):
        return "Tech 파이썬이 없어 뉴스를 받지 못합니다"
    if not _story_news_ok():
        return "Tech 가 옛 판이라 뉴스 받기(news)를 모릅니다"
    last = STORY_NEWS["tried"].get(code)
    if last and last[1] not in (0, None):
        return ("새로 받기 실패: " if has_news else "") + (last[2] or "한국투자증권 연결 없음")
    return "" if has_news else "한국투자증권 연결 없음"


def story_view(code, refresh=False):
    """GET /api/story — 캐시가 입력(sig)과 같으면 그대로, 다르면 뒤에서 다시 만들고 그동안 있던 것을 stale 로.
    없으면 {"pending", "step"}. 뉴스를 받는 중이면 news_running(화면이 3초마다 다시 묻는다)."""
    c = company_by_code(code)
    if not c:
        return None
    if NAR is None:
        return {"error": "내러티브.py 를 읽지 못했습니다"}
    _story_mkt()                    # 시장 중앙 — 하루 한 번 뒤에서(sig 의 한 조각이라 먼저)
    sig = _story_sig(c)
    d = _story_read(code)
    running = _story_news_kick(code, refresh)
    err = STORY["err"].get(code)
    blocked = bool(err and err[1] == sig and time.time() - err[0] < STORY_ERR_TTL)
    fresh = d is not None and d.get("sig") == sig
    if not fresh and not blocked and STORY["code"] != code:     # 지금 만드는 중이면 그대로(끝난 뒤 sig 가 또 다르면 다음 요청이)
        _story_kick(code)
    if d is None:
        if blocked:
            return {"error": err[2], "news_running": running}
        step = STORY["step"] if STORY["code"] == code else "차례를 기다리는 중"
        if STORY_DISC["building"]:
            step = "공시 색인 만드는 중(처음 한 번 · 30초 안팎)"
        return {"pending": True, "step": step, "news_running": running}
    out = dict(d)
    out.pop("sig", None)
    src = dict(out.get("src") or {})
    sn = dict(src.get("news") or {})
    sn["note"] = _story_news_note(code, running, bool(sn.get("ok"))) or sn.get("note", "")
    src["news"] = sn
    if STORY_DISC["building"] and (src.get("disc") or {}).get("index") != "ready":
        src["disc"] = dict(src["disc"], index="building")
    out["src"] = src
    out["stale"] = not fresh and not blocked
    out["news_running"] = running
    if blocked:
        out["build_error"] = err[2]     # 다시 만들기 실패 — 있던 payload 는 그대로 보여 준다("error" 는 payload 없을 때만)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "GiupChujeok/1.0"

    def log_message(self, fmt, *a):
        pass                      # 콘솔 조용히

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        try:                             # 응답 쓰기 전체 — 브라우저가 먼저 끊으면(탭 닫기 · 새로 고침) 조용히 끝낸다
            self.send_response(code)     # (예외가 새면 오류 문구 · 매매 내용이 viewer_auto.log 에 찍힌다)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "SAMEORIGIN")          # 다른 사이트가 이 화면을 틀에 넣어
            self.send_header("Content-Security-Policy", "frame-ancestors 'self'")   # 누르게 하는 것 막기
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            self.close_connection = True

    def _local_host(self):
        """Host 가 이 서버 주소(127.0.0.1 · localhost + 포트)인가 — 다른 이름으로 돌려 오는 요청(DNS 리바인딩) 막기."""
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "").strip().lower() in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _same_origin_get(self):
        """일을 시키는 GET(미리 계산 run · stop)이 이 화면에서 왔나 — Host 만으로는 다른 사이트의 <img src=…> · no-cors fetch 도
        Host 127.0.0.1:포트 로 와서 통과한다. 브라우저가 붙이는 Sec-Fetch-Site 는 same-origin · none(주소창 · 즐겨찾기)만,
        Origin · Referer 는 붙어 있으면 이 서버 주소여야 한다. 셋 다 없으면(curl 같은 이 PC 의 도구) Host 만 본다."""
        if not self._local_host():
            return False
        port = self.server.server_address[1]
        mine = ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port)
        sfs = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if sfs and sfs not in ("same-origin", "none"):          # cross-site · same-site(같은 localhost 의 다른 포트)
            return False
        origin = (self.headers.get("Origin") or "").strip().lower()
        if origin and origin not in mine:                       # "null"(샌드박스 · file://) 도 막는다
            return False
        ref = (self.headers.get("Referer") or "").strip().lower()
        return not ref or any(ref == m or ref.startswith(m + "/") for m in mine)

    def do_POST(self):
        """쓰기 요청 — 지금은 매매 일지만. 같은 출처(이 PC 의 이 화면)에서 온 JSON 만 받는다:
        Host · Origin 확인, Content-Type application/json(다른 사이트에서는 사전 확인에 막힌다), 64KB 한도."""
        u = urllib.parse.urlparse(self.path)
        try:
            port = self.server.server_address[1]
            origin = (self.headers.get("Origin") or "").strip().lower()
            if not self._local_host() or origin not in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port):
                return self._send(403, {"error": "이 PC 의 화면에서 온 요청만 받습니다"})
            if u.path != "/api/trades":
                return self._send(404, {"error": "no route"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._send(415, {"error": "JSON 으로 보내야 합니다"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 65536:
                return self._send(413, {"error": "요청 크기가 맞지 않습니다"})
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            return self._send(200, trades_change(body))
        except ValueError as e:              # 입력 검증 · 보유 수량 초과 · 깨진 파일 · JSON 오류
            return self._send(400, {"error": str(e)})
        except Exception as e:
            return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

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
                threading.Thread(target=_vc_refresh_all, daemon=True).start()
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
                ta, tb = read_section(c, ra, fa), read_section(c, rb, fb)
                res = diff_changes(ta, tb) if q.get("v") == "2" else diff_sections(ta, tb)
                res["a"] = {"stamp": ra["stamp"], "label": ra["label"]}
                res["b"] = {"stamp": rb["stamp"], "label": rb["label"]}
                return self._send(200, res)
            if path == "/api/brief":
                c = company_by_code(q.get("code", ""))
                r = report_of(c, q.get("rcept", "")) if c else None
                if not r:
                    return self._send(404, {"error": "보고서 없음"})
                return self._send(200, build_brief(c, r))
            if path == "/api/pricing_clock":
                # 정보 종류별 공시 뒤 반영 속도 — 도구/반영속도_검증.py 가 만든 결과
                pc = os.path.join(CACHE_DIR, "반영속도.json")
                if not os.path.exists(pc):
                    return self._send(200, {"missing": True})
                with open(pc, "r", encoding="utf-8") as fh:
                    return self._send(200, json.load(fh))
            if path == "/api/invest":
                c = company_by_code(q.get("code", ""))
                r = report_of(c, q.get("rcept", "")) if c else None
                if not r:
                    return self._send(404, {"error": "보고서 없음"})
                return self._send(200, invest_view(c, r, q.get("lite") == "1"))
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
                n = max(2, min(int(q.get("years", 4)), 16))
                return self._send(200, matrix_cached(c, corp, q.get("stmt", "IS"), q.get("mode", "q"), n,
                                                     q.get("force") == "1"))
            if path == "/api/screen":
                return self._send(200, screen(q.get("force") == "1"))
            if path == "/api/inflect":
                if INF is None:
                    return self._send(500, {"error": "변곡점 모듈 없음"})
                return self._send(200, inflect(q.get("code", ""), q.get("force") == "1"))
            if path == "/api/lens_value":
                return self._send(200, lens_value(q.get("code", "")))
            if path == "/api/quarter":
                return self._send(200, quarter_view(q.get("code", "")))
            if path == "/api/btb":
                return self._send(200, btb_view(q.get("code", "")))
            if path == "/api/export":
                return self._send(200, export_view())
            if path == "/api/export/auto":
                if q.get("on") in ("0", "1"):
                    with EXP_AUTO_LOCK:
                        a = _exp_auto_load()
                        a["on"] = q["on"] == "1"
                        _exp_auto_save(a)
                    if a["on"]:
                        threading.Thread(target=_exp_tick, daemon=True).start()
                if q.get("check") == "1":
                    _exp_tick(True)
                return self._send(200, exp_auto_view())
            if path == "/api/synergy":
                if SYN is None or FIN is None or BACK is None:
                    return self._send(500, {"error": "시너지 모듈 없음"})
                return self._send(200, synergy_view(q.get("force") == "1"))
            if path == "/api/druck/pre":
                # 밤 미리 계산 상태. run=1 이면 지금 한 번 돌린다(이미 돌고 있으면 그대로)
                if q.get("run") == "1" and not DRUCK_PRE["running"]:
                    threading.Thread(target=_druck_prebuild, daemon=True).start()
                return self._send(200, dict(DRUCK_PRE))
            if path == "/api/prebuild":
                # 전 종목 미리 계산(풍경 · 궤도) 상태. run=1 시작(이미 돌면 그대로) · stop=1 멈춤 — 둘 다 이 PC 의 이 화면에서만(Host + 같은 출처)
                if q.get("run") == "1" or q.get("stop") == "1":
                    if not self._same_origin_get():
                        return self._send(403, {"error": "이 PC 의 화면에서 온 요청만 받습니다"})
                    return self._send(200, prebuild_stop() if q.get("stop") == "1" else prebuild_run())
                return self._send(200, prebuild_status())
            if path == "/api/druck/bt":
                return self._send(200, druck_bt_view())
            if path == "/api/druck/events":
                return self._send(200, druck_events(q.get("code", "")))
            if path == "/api/druck":
                # 기본은 지금처럼 다 쌓을 때까지 기다린다. bg=1 이면 없을 때 {building, done, total} 를 바로 주고 뒤에서 쌓는다
                code_ = q.get("code", "")
                res = druck(code_, q.get("force") == "1", wait=q.get("bg") != "1")
                if res is None:
                    return self._send(404, {"error": "회사 없음"})
                if res.get("points"):
                    now_ = _druck_now(code_, res)
                    res = dict(res, now=now_)                       # 지금 PER — 캐시하지 않는다
                    if now_ and now_.get("stale"):
                        _druck_kick_stale(code_)                    # k 가 범위 밖(주가 자료가 다시 보정됨) — 뒤에서 한 번만 force 로 다시 쌓는다
                return self._send(200, res)
            if path == "/api/orbit":
                res = orbit(q.get("code", ""))
                if res is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, res)
            if path == "/api/traj":
                d = traj_view(q.get("code", ""), q.get("section", ""), _labels(q))
                if d is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, d)
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
            if path == "/api/ask":
                d = ask_view(q.get("code", ""))
                if d is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, d)
            if path == "/api/dip":
                return self._send(200, dip_view(q.get("force") == "1"))
            if path == "/api/value":
                return self._send(200, value_view(q.get("force") == "1"))
            if path == "/api/score":
                return self._send(200, score_view(q.get("force") == "1"))
            if path == "/api/trades":           # 개인 매매 기록 — 이 PC 의 이 주소로 온 요청만
                if not self._local_host():
                    return self._send(403, {"error": "이 PC 의 주소로만 열 수 있습니다"})
                return self._send(200, trades_view())
            if path == "/api/vocal":
                return self._send(200, vocal_view(q.get("force") == "1"))
            if path == "/api/tech":
                return self._send(200, tech_run() if q.get("run") == "1" else tech_status())
            if path == "/tech/report":
                body = tech_report_html(q.get("f", ""))
                if body is None:
                    return self._send(404, "<p style='font:14px sans-serif;color:#888;padding:24px'>아직 차트 발굴 리포트가 없습니다 — '다시 계산'을 누르세요.</p>",
                                      "text/html; charset=utf-8")
                return self._send(200, body, "text/html; charset=utf-8")
            if path.startswith("/tech/hist/"):      # 리포트 차트의 긴 이력(Tech 가 리포트 옆 hist/<code>.json 에 쓴다)
                m = re.fullmatch(r"([0-9A-Z]{6})\.json", path[len("/tech/hist/"):])
                p = os.path.join(TECH_OUT, "hist", m.group(1) + ".json") if m else None
                if not p or not os.path.isfile(p):
                    return self._send(404, {"error": "이력 없음"})
                with open(p, "rb") as fh:
                    return self._send(200, fh.read())
            if path == "/api/industry":
                return self._send(200, industry_view(q.get("force") == "1"))
            if path == "/api/industry/sub":
                return self._send(200, industry_sub(q.get("tab", "stocks"), q.get("sector", "")))
            if path == "/api/reports":
                d = reports_view(q.get("code", ""))
                return self._send(200 if d else 404, d or {"error": "회사 없음"})
            if path == "/api/reports/recent":
                return self._send(200, reports_recent(q.get("kind", ""), int(q.get("days", "14") or 14), q.get("sector", ""), q.get("q", ""),
                                                      q.get("mention", ""), int(q.get("offset", "0") or 0), min(200, int(q.get("limit", "60") or 60))))
            if path == "/api/reports/collect":
                threading.Thread(target=_rep_collect, daemon=True).start()
                return self._send(200, reports_status())
            if path == "/api/vcbuyer":
                return self._send(200, vcbuyer_view(q.get("key", ""), q.get("kind", "cust")) or {"rows": []})
            if path == "/api/valuechain":
                d = valuechain_view(q.get("code", ""))
                if d is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, d)
            if path == "/api/ohlcv":
                # 저평가V2 큰 차트 — 마지막 n봉 + 이동평균(200일선까지)을 낼 앞 200봉
                code = q.get("code", "")
                n = min(max(int(q.get("n", "250") or 250), 20), 800)
                d = FIN.fetch_ohlcv(code) if FIN is not None and re.fullmatch(r"[0-9A-Z]{6}", code or "") else {}
                ks = sorted(d)[-(n + 200):]
                c = company_by_code(code)
                return self._send(200, {"code": code, "name": c["name"] if c else code, "n": n,
                                        "d": ks, "o": [d[k][0] for k in ks], "h": [d[k][1] for k in ks],
                                        "l": [d[k][2] for k in ks], "c": [d[k][3] for k in ks], "v": [d[k][4] for k in ks]})
            if path == "/api/narrative":
                d = narrative_view(q.get("code", ""), q.get("term", "").strip())
                if d is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, d)
            if path == "/api/vocab":
                terms = [t.strip() for t in q.get("terms", "").split(",") if t.strip()]
                d = vocab_view(q.get("code", ""), terms or None)
                if d is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, d)
            if path == "/api/landscape":
                d = landscape_view(q.get("code", ""))
                if d is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, d)
            if path == "/api/story":
                d = story_view(q.get("code", ""), q.get("refresh") == "1")
                if d is None:
                    return self._send(404, {"error": "회사 없음"})
                return self._send(200, json.dumps(d, ensure_ascii=False, separators=(",", ":")))   # 1MB 가까운 응답 — 빈칸 없이
            if path == "/api/lineage":
                c = company_by_code(q.get("code", ""))
                if not c:
                    return self._send(404, {"error": "회사 없음"})
                aq = next((x for x in ASK_Q if x["id"] == q.get("ask")), None)
                if aq:
                    res = lineage(c, aq["_rx"], set(aq["secs"]), _labels(q), bool(aq.get("raw")), strict=True)
                    res["ask"] = aq["id"]
                else:
                    rx, terms, extra = ask_query_rx(q.get("q", ""))
                    if rx is None:
                        return self._send(400, {"error": "찾을 말을 넣으세요"})
                    sec = q.get("section") or None
                    res = lineage(c, rx, {sec} if sec else None, _labels(q))
                    res["terms"], res["extra"] = terms, extra
                return self._send(200, res)
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
        return self._send(200, body, ctype)


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
    if "--no-auto" not in args:         # 시험용 포트(8766)는 --no-auto — 갱신을 두 번 띄우지 않게
        threading.Thread(target=_exp_auto_loop, daemon=True).start()
        threading.Thread(target=_val_auto_loop, daemon=True).start()
        threading.Thread(target=_vc_auto_loop, daemon=True).start()
        threading.Thread(target=_rep_auto_loop, daemon=True).start()
        threading.Thread(target=_ind_auto_loop, daemon=True).start()
        threading.Thread(target=_tech_auto_loop, daemon=True).start()
        threading.Thread(target=_druck_auto_loop, daemon=True).start()
        threading.Thread(target=_prebuild_auto_loop, daemon=True).start()
    # 예전 보컬 탭은 '차트 발굴'(Tech)로 바뀌어 매일 07:00 전 시장 일봉 · 깔때기 계산을 껐다(2026-10-09, 사용자 결정).
    # /api/vocal 은 그대로 살아 있다(부르면 그때 센다). 다시 켜려면 아래 줄을 되살린다.
    # if VOC is not None:
    #     threading.Thread(target=_vocal_auto_loop, daemon=True).start()
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
