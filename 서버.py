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
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(b, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
    return g


def inflect(code, force=False):
    """변곡점 — 정체성·수익 모델·방향이 꺾인 자리와 구루 렌즈. 변곡점.py 참조."""
    c = company_by_code(code)
    if not c:
        return {"error": "회사 없음"}
    corp = corp_code_of(code)
    if not corp or FIN is None:
        return {"error": "DART 고유번호를 찾지 못했습니다."}
    sig = (c["reports"][-1]["rcept"] if c["reports"] else "") + "_v%d" % INF.VERSION
    cache = os.path.join(CACHE_DIR, "inflect", code + ".json")
    if not force and os.path.exists(cache):
        try:
            old = json.load(open(cache, encoding="utf-8"))
            if old.get("sig") == sig:
                return old
        except Exception:
            pass
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

    # 가격 — 버핏의 유보이익 1원 테스트, 린치의 PEG
    price_info = {}
    try:
        prices = FIN.fetch_prices(code)
        F = [d for d in funds if d.get("re") is not None]
        if len(F) >= 6:
            a, b = F[-6], F[-1]
            sa = FIN.fetch_shares(corp, a["year"], "11011").get("shares")
            sb = FIN.fetch_shares(corp, b["year"], "11011").get("shares")
            pa, _ = FIN.price_on(prices, "%d1230" % a["year"])
            pb, _ = FIN.price_on(prices, "%d1230" % b["year"])
            dre = b["re"] - a["re"]
            if sa and sb and pa and pb and dre > 0:
                dcap = pb * sb - pa * sa
                price_info["retained_test"] = {
                    "ratio": dcap / dre,
                    "note": "%d~%d년 유보이익 %s 늘 때 시가총액 %s 변했다 → 1원당 %.1f원" % (
                        a["year"], b["year"], _won_txt(dre), _won_txt(dcap), dcap / dre)}
        lastq = next((q for q in reversed(quarters) if q.get("PER_TTM")), None)
        eg = INF._cagr(funds, "eps", 3)
        if lastq and lastq["PER_TTM"] > 0 and eg and eg > 0:
            price_info["peg"] = lastq["PER_TTM"] / eg
        # 켄 피셔 — 해마다 연말 시가총액(그날 실제 종가 × 그해 말 유통주식수)과 PSR·PRR
        rnd = {f["year"]: f.get("rnd_pct") for f in feats}
        for d in funds:
            y = d["year"]
            sh = FIN.fetch_shares(corp, y, "11011").get("shares")
            px, _ = FIN.price_on(prices, "%d1230" % y)
            d["mcap"] = sh * px if (sh and px) else None
            d["psr"] = d["mcap"] / d["rev"] if (d["mcap"] and d.get("rev") and d["rev"] > 0) else None
            d["rnd_pct"] = rnd.get(y)
            d["rnd"] = d["rev"] * d["rnd_pct"] / 100 if (d.get("rev") and d["rnd_pct"]) else None
            d["prr"] = d["mcap"] / d["rnd"] if (d["mcap"] and d["rnd"]) else None
        # 지금 — 오늘 주가 × 최근 유통주식수 ÷ 최근 4분기 매출
        lastT = next((q for q in reversed(quarters) if q.get("매출_TTM")), None)
        shn = next((FIN.fetch_shares(corp, d["year"], "11011").get("shares") for d in reversed(funds)
                    if FIN.fetch_shares(corp, d["year"], "11011").get("shares")), None)
        if prices and shn and lastT:
            dlast = max(prices)
            mc = prices[dlast] * shn
            price_info["psr_now"] = {"psr": mc / lastT["매출_TTM"], "mcap": mc, "date": dlast,
                                     "sales": lastT["매출_TTM"], "label": lastT.get("label")}
            lr = next((d for d in reversed(funds) if d.get("rnd")), None)
            if lr:
                price_info["prr_now"] = {"prr": mc / lr["rnd"], "year": lr["year"], "rnd": lr["rnd"]}
    except Exception as e:
        print("변곡점 가격 %s: %s" % (code, e), flush=True)

    ev = INF.events(funds, quarters, feats, came, gone, rcept_of)
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
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return out


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
    # 4분기 합 순이익 — 연속된 네 분기일 때만
    w4 = pts[-4:]
    ni_ttm = (sum(x["당기순이익"] for x in w4)
              if len(w4) == 4 and all(x.get("당기순이익") is not None for x in w4)
              and all(b["year"] * 4 + b["q"] - a["year"] * 4 - a["q"] == 1 for a, b in zip(w4, w4[1:])) else None)
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
        "PER_TTM": cur.get("PER_TTM"), "순이익_TTM": ni_ttm,
        "매출_TTM_1년전": pts[-5].get("매출_TTM") if len(pts) >= 5 else None,
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
    수집 대상 이름과 DART 고유번호 목록(상장사만)의 공식 이름을 둘 다 넣는다."""
    if _NAMES:
        return _NAMES
    for c in INDEX["companies"]:
        _NAMES[_norm_corp(c["name"])] = c["code"]
    path = os.path.join(CACHE_DIR, "CORPCODE.xml")
    if os.path.exists(path):
        text = open(path, "rb").read().decode("utf-8", errors="replace")
        for m in re.finditer(r"<list>(.*?)</list>", text, re.S):
            blob = m.group(1)
            s = re.search(r"<stock_code>(.*?)</stock_code>", blob, re.S)
            n = re.search(r"<corp_name>(.*?)</corp_name>", blob, re.S)
            if s and n and s.group(1).strip():
                _NAMES.setdefault(_norm_corp(html.unescape(n.group(1))), s.group(1).strip())
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
        for x in d.get("items", []):     # 같은 (시군구 × 품목)을 쓰는 다른 회사 — 지주·자회사, 같은 동네 경쟁사
            sh = set()
            for ch in (x.get("channels") or [])[:3]:
                sh |= set(users.get((ch["sgg"], ch["hs"]), [])) - {x["name"]}
            x["shared_with"] = sorted(sh)[:4]
        _EXP.update(mt=mt, d=d)
    return _EXP["d"]


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
    # 요약은 잠깐만 여기서 뽑고 나머지는 뒤에서 — 첫 화면이 오래 멈추지 않게
    deadline = time.time() + 1.0
    for rep in c["reports"]:
        p = brief_path(code, rep["rcept"])
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    b = json.load(fh)
                have += 1
                secs = b["sections"]
                top = secs[0]["section"] if secs else ""
                rows.append({
                    "stamp": rep["stamp"], "label": rep["label"],
                    "tag": rep["tag"], "rcept": rep["rcept"],
                    "score": b["score"], "kind": b["kind"],
                    "top": top, "tags": b["tags"],
                    "changed": len(secs),
                    "first": b.get("first", False),
                    # 중요도를 곱한 '새로 쓴 분량'(글자). 점수는 이것의 섹션별 제곱근 합이다.
                    "vol": round(sum(s["weight"] * (s["added_chars"] + 0.6 * s["removed_chars"])
                                     for s in secs)),
                    "add_chars": sum(s["added_chars"] for s in secs),
                    "rem_chars": sum(s["removed_chars"] for s in secs),
                    "numeric": sum(s.get("numeric", 0) for s in secs),
                    "gist": _gist_of(c, rep, b, p, time.time() < deadline),
                })
                continue
            except Exception:
                pass
        rows.append({"stamp": rep["stamp"], "label": rep["label"],
                     "tag": rep["tag"], "rcept": rep["rcept"],
                     "score": None, "kind": "", "top": "", "tags": {},
                     "changed": 0, "first": False, "vol": None, "gist": []})
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
INV_V = 8
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
                     r"기재함|산식|종가|대손|제각|미지급수량|신탁계약|(변경|변동)\s*사항\S*\s*없|해당\s*없")
INV_DONE = re.compile(r"준공|완료|인도|종결|만기|상환|지급\s*완료")      # 끝난 일이 문장에서 빠지는 건 악재가 아니다
INV_HOLDER = re.compile(r"배당|자기주식|자사주|소각|주주환원")
INV_LABEL_STOP = {"연결실체", "당사", "회사", "주주총회", "임시주주총회", "연결회사", "지배기업"}


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
    """지도에 붙일 짧은 이름 — '수주 · 200MWh' 처럼 범주 + 금액/약어/새 낱말."""
    head = INV_TAG_SHORT.get(tags[0], tags[0]) if tags else ""
    tok = ""
    m = INV_UNIT.search(raw)
    if m and not m.group(0).rstrip().endswith("%"):     # '100%' 같은 지분율보다 고유명사가 낫다
        tok = re.sub(r"\s+", "", m.group(0))
    if not tok:
        for a in INV_ACRO.findall(raw):
            if INF is None or a not in INF.FX:
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
              and not GIST_TERM_SKIP.search(t)]
        tok = max(ts, key=len) if ts else ""
    if not head and INV_HOLDER.search(raw):
        head = "주주환원"
    return (head + " · " + tok) if head and tok else (head or tok or raw[:10])


def _inv_text(src, text, raw, section, v):
    tags = classify(raw)
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
        add("매출 %+.0f%%" % rev, rev / 40, .1, ["드러켄밀러", "린치"], "매출액이 직전 같은 종류 보고서보다 %+.1f%%." % rev, "매출액", rev)
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


def _inv_ttm(code, stamp):
    """가속도 캐시가 있으면 이 분기의 TTM 성장률·가속(2분기 평균). 없으면 None — 여기서 새로 쌓지 않는다."""
    path = os.path.join(CACHE_DIR, "druck", code + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            pts = json.load(fh).get("points") or []
    except Exception:
        return None
    y, m = stamp.split("-")
    lab = "%sQ%d" % (y, Q_OF_MONTH.get(m, 0))
    idx = next((i for i, p in enumerate(pts) if p.get("label") == lab), None)
    if idx is None:
        return None

    def g(i):
        if i < 4 or i >= len(pts):
            return None
        a, b = pts[i].get("매출_TTM"), pts[i - 4].get("매출_TTM")
        return (a / b - 1) * 100 if a and b and b > 0 else None
    gi, g2 = g(idx), g(idx - 2)
    acc = (gi - g2) / 2 if gi is not None and g2 is not None else None
    reg = None
    if gi is not None and acc is not None:
        reg = ("가속 성장" if acc > 0 else "감속 성장") if gi > 0 else ("바닥 통과" if acc > 0 else "역성장 심화")
    # 자기 역사 대비 PER 백분위 — 이 분기까지의 과거만 본다(앞날 자료 없음)
    per = pts[idx].get("PER_TTM")
    hist = [p.get("PER_TTM") for p in pts[:idx + 1] if p.get("PER_TTM") and p.get("PER_TTM") > 0]
    per_pct = (sum(1 for v in hist if v <= per) / len(hist) * 100) if per and per > 0 and len(hist) >= 8 else None
    return {"label": lab, "g": gi, "a": acc, "reg": reg, "price": pts[idx].get("주가"), "per": per, "per_pct": per_pct}


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


def invest_view(c, rep, lite=False):
    """lite=True 면 주가·궤도·국면을 빼고 신호·재무만 — 여러 보고서를 한꺼번에 돌리는 성적표용."""
    b = build_brief(c, rep)
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
        sigs, came, gone, seen, kept = [], [], [], set(), []
        ryear = int(rep["stamp"][:4])
        for s in [x for x in b["sections"] if x.get("weight", 0) >= 0.3][:7]:
            bf = s.get("base_file") or s["file"]
            nc = _novel_cands(c, base, rep, bf, s["file"], s["section"])
            k = 0
            for v, sent, j in nc["cands"]:
                if k >= 3:
                    break
                if INV_GOV.search(sent) or _inv_dup(sent, kept) or _inv_old(sent, ryear):
                    continue
                # 범주도 주주환원도 아닌 문장은 금액과 방향 낱말이 둘 다 있어야 신호로 친다
                if not classify(sent) and not INV_HOLDER.search(sent) and not (
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
            for v, sent, j in dc["cands"][:1]:
                t = _short(sent, 110)
                key = SKEL_RE.sub("", t)[:24]
                if (key in seen or not classify(sent) or INV_GOV.search(sent) or _inv_dup(sent, kept)
                        or _inv_old(sent, ryear)):
                    continue      # 범주 없는 사라진 문장은 대개 서식 정리다
                seen.add(key)
                kept.append(_tokset(sent))
                sigs.append(_inv_text("gone", t, sent, s["section"], v))
        fin = financials(c, rep)
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
    out["series"] = _inv_prices(c["code"])
    return out


def _inv_prices(code):
    """일별 종가(액면분할·병합 보정)를 [날짜들], [종가들] 두 줄로. 없으면 None."""
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
    return {"d": [int(d) for d in ds], "p": [round(v, 1) for v in adj], "r": [pr[d] for d in ds]}


def _inv_regimes(code):
    """가속도 캐시로 분기별 TTM 국면. 캐시가 없으면 빈 목록."""
    path = os.path.join(CACHE_DIR, "druck", code + ".json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            pts = json.load(fh).get("points") or []
    except Exception:
        return []
    g = []
    for i, p in enumerate(pts):
        a, b = p.get("매출_TTM"), (pts[i - 4].get("매출_TTM") if i >= 4 else None)
        g.append((a / b - 1) * 100 if a and b and b > 0 else None)
    out = []
    for i, p in enumerate(pts):
        acc = (g[i] - g[i - 2]) / 2 if i >= 2 and g[i] is not None and g[i - 2] is not None else None
        reg = None
        if g[i] is not None and acc is not None:
            reg = ("가속 성장" if acc > 0 else "감속 성장") if g[i] > 0 else ("바닥 통과" if acc > 0 else "역성장 심화")
        out.append({"label": p.get("label"), "g": g[i], "reg": reg})
    return out


# ---------------------------------------------------------------- 전문검색: 무엇을 물어야 할지 모를 때
# 초일류 투자자가 정기보고서에 던지는 질문 24개를 회사마다 미리 돌려 둔다(질문 지도).
# 찾은 문장은 '족보'로 묶는다 — 같은 말이 언제 태어나, 어떻게 고쳐지고, 언제 사라졌나.
# 원탁 백테스트에서 공시 뒤에도 값에 덜 든 채 남은 건 '새 문장'뿐이었다. 질문 지도는 그 새 문장을 질문별로 가른다.
ASK_V = 4
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
        item = {"id": q["id"], "status": st, "score": round(sc, 2), "counts": cnt, "marks": marks,
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
    return {"v": ASK_V, "reports": [_ask_rep(reps, i) for i in range(n)], "recent_from": recent,
            "base_end": base_end, "questions": out, "came": came,
            "spotlight": [{"id": i, "score": round(s, 2), "ev": e} for s, i, e in spot[:5]]}


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
LAND_V = 7
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


def _land_shares(F, corp, latest=None):
    """연말 주식 수를 오늘 기준으로 — 한 해에 1.8배 넘게(또는 0.55배 아래로) 바뀌면 분할·무상증자로 보고
    그 앞 해들에 비율을 곱한다. 2015년 이전(DART 에 없음)은 알려진 가장 이른 해 값으로 채운다."""
    raw = {}
    for d in F:
        try:
            raw[d["year"]] = FIN.fetch_shares(corp, d["year"], "11011").get("shares")
        except Exception:
            raw[d["year"]] = None
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
        try:
            now = FIN.fetch_shares(corp, latest[0], latest[1]).get("shares")
        except Exception:
            now = None
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
    n = i - j
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


def landscape_build(c, prog=None):
    code = c["code"]
    corp = corp_code_of(code)
    if not corp or FIN is None or INF is None:
        return {"error": "DART 고유번호나 재무 모듈이 없습니다."}
    this = dt.date.today().year
    funds = INF.fundamentals(FIN, corp, list(range(this - 15, this + 1)))
    F = [d for d in funds if d.get("rev") is not None or d.get("ni") is not None]
    if len(F) < 4:
        return {"error": "연간 재무가 4년 치도 안 됩니다."}
    if prog is not None:
        prog["step"] = "주식 수·주가"
    rc_of = {"03": "11013", "06": "11012", "09": "11014", "12": "11011"}
    lrep = max((r for r in c["reports"] if r["stamp"][5:7] in rc_of), key=lambda r: r["stamp"], default=None)
    latest = (int(lrep["stamp"][:4]), rc_of[lrep["stamp"][5:7]]) if lrep else None
    S_adj, splits, S_raw = _land_shares(F, corp, latest)
    prices = FIN.fetch_prices(code) or {}
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

    # ── 분기 — 최근 4분기 순이익으로 주당이익, 보고서 접수일 주가로 PER
    if prog is not None:
        prog["step"] = "분기 이익선"
    try:
        dk = druck(code) or {}
    except Exception:
        dk = {}
    P = [p for p in dk.get("points", []) if p.get("year")]
    qs = []
    for k, p in enumerate(P):
        win = P[k - 3:k + 1] if k >= 3 else []
        ni4 = sum(x["당기순이익"] for x in win) if len(win) == 4 and all(x.get("당기순이익") is not None for x in win) else None
        op4 = p.get("영업이익_TTM")
        sa = S_adj.get(p["year"]) or S_adj.get(min(S_adj, key=lambda y: abs(y - p["year"]))) if S_adj else None
        eps = ni4 / sa if (ni4 is not None and sa) else None
        qd = "%d%s" % (p["year"], LAND_Q_END[p["q"]])
        dd = p.get("주가일")                   # 보고서 접수일(그날 알 수 있던 값) — 결단 시점에 쓴다
        qs.append({"label": p["label"], "year": p["year"], "q": p["q"], "end": qd, "filed": dd,
                   "ni4": ni4, "op4": op4, "eps": eps, "rev4": p.get("매출_TTM"),
                   "inv_days": p.get("재고일수"), "px_end": px_on(qd), "px_filed": prices.get(dd) if dd else None})
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
    ytype = {r["year"]: r["type"] for r in rows}
    yrow = {r["year"]: r for r in rows}
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
        prev4 = qs[k - 4] if k >= 4 else None
        g = (q["eps"] / prev4["eps"] - 1) * 100 if (prev4 and prev4.get("eps") and prev4["eps"] > 0 and q["eps"] > 0) else None
        if typ == "고성장" and g and g >= 20 and per_f and per_f / g <= 1.0:
            hits.append(("린치", "고성장주가 PEG 1 아래", "주당이익 1년 %+.0f%%, PER %.1f → PEG %.2f" % (g, per_f, per_f / g)))
        if typ in ("경기순환", "적자", "회생") and k >= 3:
            o = [x.get("op4") for x in qs[k - 3:k + 1]]
            # 순환주는 이익 바닥에서 PER이 가장 비싸 보인다(린치) — 그래서 PER 대신 5년 평균 이익으로 그은 선의 두 배를
            # 넘었는지로 과열을 본다. 넘었으면 회복이 이미 값에 든 것으로 보고 세지 않는다
            e5 = [yrow[y]["eps"] for y in range(q["year"] - 5, q["year"]) if y in yrow and yrow[y].get("eps") is not None]
            med = _land_q(prior, .5) if len(prior) >= 8 else band["mid"]
            ne = sum(e5) / len(e5) if len(e5) >= 3 else None
            hot = bool(ne and ne > 0 and med and prices[d] >= 2 * ne * med)
            if None not in o and o[0] > o[1] > o[2] and o[3] > o[2] and not hot:
                hits.append(("린치", "순환주 이익 바닥 통과" if o[3] > 0 else "회생 — 적자가 줄기 시작",
                             "4분기 영업이익이 두 분기 줄다가 %s → %s 로 돌아섰다" % (_won_txt(o[2]), _won_txt(o[3]))))
        if k >= 2 and q["ni4"] is not None and q["ni4"] > 0 and all(
                x["ni4"] is not None and x["ni4"] < 0 for x in qs[k - 2:k]):
            hits.append(("린치", "회생 — 흑자 전환", "4분기 순이익 %s → %s" % (_won_txt(qs[k - 1]["ni4"]), _won_txt(q["ni4"]))))
        if typ in ("대형우량", "저성장") and pct is not None and pct <= 15 and not quality:
            hits.append(("린치", "우량주가 이익선 아래", "PER 자기 역사 하위 %.0f%%" % pct))
        for who, what, why in hits:
            if last_at.get(who) is not None and k - last_at[who] < 4:      # 같은 구루는 1년에 한 번
                continue
            last_at[who] = k
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
    for ch in merged:
        rr = [yrow[y] for y in range(ch["y0"], ch["y1"] + 1) if y in yrow]
        r0, r1 = rr[0], rr[-1]
        pre = yrow.get(ch["y0"] - 1)
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
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a.get("op") and b.get("op") is not None and a["op"] > 0:
            ch = (b["op"] / a["op"] - 1) * 100
            if worst is None or ch < worst[0]:
                worst = (ch, b)
    if worst and worst[0] < -20:
        ch, b = worst
        prev_peak = max((r["op"] for r in rows if r["year"] < b["year"] and r.get("op")), default=None)
        back = next((r["year"] for r in rows if r["year"] > b["year"] and prev_peak and (r.get("op") or 0) >= prev_peak), None)
        lessons.append({"k": "worst", "who": "버핏", "title": "가장 나빴던 해에 어떻게 버텼나",
                        "text": "%d년 영업이익 %+.0f%%, 매출 %s, 순이익 %s." % (
                            b["year"], ch, ("%+.0f%%" % b["rev_yoy"]) if b.get("rev_yoy") is not None else "—",
                            "흑자를 지켰다" if (b.get("ni") or 0) > 0 else "적자") +
                        (" 이전 정점을 %d년에 되찾았다(%d년 걸림)." % (back, back - b["year"]) if back else " 아직 이전 정점을 되찾지 못했다.") +
                        (" 불황에도 돈을 번 회사는 버핏의 '경제적 해자' 후보다." if (b.get("ni") or 0) > 0 else " 불황에 적자가 나는 회사는 빚이 치명상이 된다(멍거)."),
                        "v": round(ch)})
    # 3. 자본 배분 — 15년 번 돈이 어디로 갔나
    cfo = sum(r["cfo"] for r in rows if r.get("cfo"))
    if cfo > 0:
        cap = sum(r["capex"] for r in rows if r.get("capex"))
        dv = sum(r["div"] for r in rows if r.get("div"))
        bb = sum(r["buyback"] for r in rows if r.get("buyback"))
        s0 = next((r["shares"] for r in rows if r.get("shares")), None)
        s1 = next((r["shares"] for r in reversed(rows) if r.get("shares")), None)
        ny = rows[-1]["year"] - rows[0]["year"]
        sh_cagr = ((s1 / s0) ** (1 / ny) - 1) * 100 if (s0 and s1 and ny) else None
        lessons.append({"k": "alloc", "who": "버핏", "title": "번 돈이 어디로 갔나",
                        "text": "%d–%d년 영업으로 번 현금 %s 가운데 설비·무형 투자 %.0f%%, 배당 %.0f%%, 자사주 %.0f%%." % (
                            rows[0]["year"], rows[-1]["year"], _won_txt(cfo), cap / cfo * 100, dv / cfo * 100, bb / cfo * 100) +
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
    roes = [(r["year"], r["roe"]) for r in rows if r.get("roe") is not None]
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
    last_type = next((r["type"] for r in reversed(rows) if r.get("type")), None)
    y4 = next((q for q in qs if lastq and q["year"] == lastq["year"] - 1 and q["q"] == lastq["q"]), None)
    g_now = (eps_now / y4["eps"] - 1) * 100 if (y4 and y4.get("eps") and y4["eps"] > 0 and eps_now and eps_now > 0) else None
    lr = rows[-1]
    rr5 = [r for r in rows[-5:] if r.get("roe") is not None]
    idv = next((l["v"] for l in lessons if l["k"] == "identity"), None)
    checks = [
        {"who": "버핏", "q": "이해할 수 있는 사업인가 (15년 설명의 닮음 0.5↑)", "ok": (idv >= 0.5) if idv is not None else None,
         "why": ("사업의 내용 낱말 닮음 %.2f" % idv) if idv is not None else "자료 없음"},
        {"who": "버핏", "q": "꾸준히 버는가 (최근 5년 ROE 15%↑)", "ok": len(rr5) >= 3 and sum(1 for r in rr5 if r["roe"] >= 15) >= 4,
         "why": "최근 5년 ROE %s" % " · ".join("%.0f" % r["roe"] for r in rr5)},
        {"who": "버핏", "q": "빚이 가벼운가 (차입/자본 50%↓)", "ok": (lr["de"] <= 50) if lr.get("de") is not None else
         ((lr.get("liab") or 0) <= (lr.get("eq") or 0) if lr.get("eq") else None),
         "why": ("차입금/자본 %.0f%%" % lr["de"]) if lr.get("de") is not None else "차입금 줄 없음 — 부채/자본으로 봄"},
        {"who": "버핏", "q": "이익이 현금으로 들어오는가 (FCF 흑자 해 ≥ 절반)",
         "ok": sum(1 for r in rows if (r.get("fcf") or 0) > 0) >= 0.5 * max(1, sum(1 for r in rows if r.get("fcf") is not None)),
         "why": "FCF 흑자 %d/%d년" % (sum(1 for r in rows if (r.get("fcf") or 0) > 0), sum(1 for r in rows if r.get("fcf") is not None))},
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
    e5 = [r["eps"] for r in rows[-5:] if r.get("eps") is not None]
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
    o4 = [q.get("op4") for q in qs[-4:]]
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
    return {"v": LAND_V, "code": code, "name": c["name"], "rows": rows, "quarters": qs, "line": line, "band": band,
            "monthly": monthly, "splits": splits, "corr": corr, "gaps": gaps, "moments": moments,
            "stats": {"버핏": summ("버핏"), "린치": summ("린치"), "base": base}, "chapters": merged,
            "lessons": lessons, "decide": decide, "types": {k: list(v) for k, v in LAND_TYPES.items()},
            "price_date": now_d}


LANDING = {}
LAND_LOCK = threading.Lock()


def _land_path(code):
    return os.path.join(CACHE_DIR, "landscape", code + ".json")


def _land_sig(c):
    return "%s:%d:%s:%d" % (c["reports"][-1]["rcept"] if c["reports"] else "", len(c["reports"]),
                            dt.date.today().isoformat(), LAND_V)


def _run_land(code):
    st = LANDING[code]
    try:
        c = company_by_code(code)
        d = landscape_build(c, st)
        d["sig"] = _land_sig(c)
        if not d.get("error"):
            os.makedirs(os.path.dirname(_land_path(code)), exist_ok=True)
            with open(_land_path(code), "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
        else:
            st["error"] = d["error"]
            return
    except Exception as e:
        import traceback
        traceback.print_exc()
        st["error"] = "%s: %s" % (type(e).__name__, e)
        return
    with LAND_LOCK:
        LANDING.pop(code, None)


def landscape_view(code):
    c = company_by_code(code)
    if not c:
        return None
    p = _land_path(code)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("sig") == _land_sig(c):
                return d
        except Exception:
            pass
    with LAND_LOCK:
        st = LANDING.get(code)
        if st and st.get("error"):
            if time.time() - st.get("at", 0) < 30:
                return {"error": st["error"]}
            st = None
        if st is None:
            st = LANDING[code] = {"step": "연간 재무", "at": time.time()}
            threading.Thread(target=_run_land, args=(code,), daemon=True).start()
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
        P = [p for p in dk.get("points", []) if p.get("주가일")]
        ni = {}
        for k, p in enumerate(P):
            w4 = P[k - 3:k + 1] if k >= 3 else []
            ni[k] = sum(x["당기순이익"] for x in w4) if len(w4) == 4 and all(x.get("당기순이익") is not None for x in w4) else None
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
DIP_V = 6
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
    corp = corp_code_of(c["code"])
    if not corp or DRK is None:
        return []
    cached = os.path.join(CACHE_DIR, "druck", c["code"] + ".json")
    if os.path.exists(cached):
        try:
            with open(cached, "r", encoding="utf-8") as fh:
                pts = json.load(fh).get("points") or []
            if pts:
                return [p for p in pts if p.get("year")]
        except Exception:
            pass
    this_year = dt.date.today().year
    pts = [p for p in DRK.series(corp, c["code"], list(range(this_year - SCREEN_YEARS, this_year + 1))) if p.get("매출액")]
    dates = {}
    for r in c["reports"]:
        y, mth = r["stamp"].split("-")
        q = Q_OF_MONTH.get(mth)
        if q and (not r["tag"] or (int(y), q) not in dates):
            dates[(int(y), q)] = rcept_dt_of(r)
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
    ni4 = []
    for k, p in enumerate(P):
        w4 = P[k - 3:k + 1] if k >= 3 else []
        ni4.append(sum(x["당기순이익"] for x in w4) if len(w4) == 4 and all(x.get("당기순이익") is not None for x in w4) else None)
    op_now = P[-1].get("영업이익_TTM") if P else None
    ni_now = ni4[-1] if ni4 else None
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
    if len(P) >= 5:
        a0 = (P[-5].get("매출채권일수") or 0) + (P[-5].get("재고일수") or 0)
        a1 = (P[-1].get("매출채권일수") or 0) + (P[-1].get("재고일수") or 0)
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
        k0 = max((k for k, p in enumerate(P) if (p.get("주가일") or "") <= hi_d), default=None)
        if k0 is not None:
            e0, e1 = ni4[k0], ni_now
            if e0 and e1 and e0 > 0 and e1 > 0:
                e_chg = (e1 / e0 - 1) * 100
            else:
                o0 = P[k0].get("영업이익_TTM")
                if o0 and op_now and o0 > 0 and op_now > 0:
                    e_chg = (op_now / o0 - 1) * 100
    if e_chg is not None and dd is not None:
        rerate = ((1 + dd / 100) / (1 + e_chg / 100) - 1) * 100
    add(5, "그 사이 이익은 버텼다(-5% 이내)", e_chg is not None and e_chg >= -5,
        "고점 무렵 대비 이익(4분기 합) %s" % ("%+.0f%%" % e_chg if e_chg is not None else "—"))
    add(5, "값 매김만 줄었다(PER 15%↑ 하락)", rerate is not None and rerate <= -15,
        "값 매김 %s" % ("%+.0f%%" % rerate if rerate is not None else "—"), hard=False)
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
                    lv = landscape_view(code)
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


DIP_PRICEY = 80      # 자기 15년 PER 중 상위 20% 안이면 아직 비싸다 — 거품이 빠지는 중일 수 있다


def _dip_rank(row):
    """등급과 점수. 억울 = 시장·업종이 함께 빠졌고, 회사만 유독 더 빠지지 않았고, 자기 역사로도 비싸지 않다."""
    why = []
    if not row.get("macro"):
        why.append("시장·업종은 크게 안 빠졌다 — 회사 고유 원인일 수 있다")
    if row.get("worse"):
        why.append("시장·업종보다 25%p 넘게 더 빠졌다")
    if row.get("pct") is not None and row["pct"] >= DIP_PRICEY:
        why.append("빠진 뒤에도 PER이 자기 역사 상위 %d%%" % max(1, round(100 - row["pct"])))
    row["tier"] = "관찰" if why else "억울"
    row["tier_why"] = why
    _dip_score(row)


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
            if path == "/api/inflect":
                if INF is None:
                    return self._send(500, {"error": "변곡점 모듈 없음"})
                return self._send(200, inflect(q.get("code", ""), q.get("force") == "1"))
            if path == "/api/export":
                return self._send(200, export_view())
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
