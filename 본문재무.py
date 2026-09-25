# -*- coding: utf-8 -*-
"""
보고서 본문에서 재무제표를 읽는다.

DART 재무제표 API(fnlttSinglAcntAll)에 원장이 없는 해가 있다.
  * 금융업(은행·보험·증권·카드·금융지주)은 2022년까지 전부 status 013
    KB금융·삼성화재·NH투자증권 등 40여 곳이 2023년부터만 나온다.
  * 전 종목 공통으로 연간 2014년 이전, 분기 2015년 이전은 013.
그런데 수집해 둔 보고서 본문 「III. 재무에 관한 사항 > 2. 연결재무제표」에는
재무상태표·손익계산서·현금흐름표가 표로 그대로 들어 있다.
표를 읽어 API 원장과 같은 모양({sj_div, account_id, account_nm,
thstrm_amount, thstrm_add_amount})으로 돌려준다. 태그는 없다.

본문 텍스트는 표의 칸이 한 줄씩 풀려 있다.
    Ⅰ. 현금 및 예치금      <- 계정명
    20,274,490            <- 당기
    19,817,825            <- 전기
    17,884,863            <- 전전기
검산(자산 = 부채 + 자본, 기말현금 = 기초 + 증감)이 안 맞는 표는 버린다.
틀린 숫자를 보여주느니 비워 두는 편이 낫다.
"""
import os
import re
import json
import glob
import html
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "기업추적_수집")
CACHE = os.path.join(BASE, ".cache", "본문재무")
VERSION = 21                       # 파서가 바뀌면 올린다. 캐시를 새로 만든다.

MONTH = {"11013": "03", "11012": "06", "11014": "09", "11011": "12"}
KIND_OF = {"11013": "분기보고서", "11012": "반기보고서", "11014": "분기보고서", "11011": "사업보고서"}

NUM_RE = re.compile(r"^\(?\s*[-−△▲]?\s*[\d,]+(?:\.\d+)?\s*\)?원?$")
DASH_RE = re.compile(r"^[-−–—]$")
NOTE_RE = re.compile(r"^(?:주\s*)?\d{1,2}(?:\s*[,.·~]\s*\d{1,2})*$")
UNIT_RE = re.compile(r"단위\s*[:：]?\s*(원|천원|백만원|억원)")
FX_UNIT_RE = re.compile(r"단위[^)\n]*(?:달러|USD|US\$|EUR|유로|JPY|엔화|위안|CNY|RMB)")
UNIT_MUL = {"원": 1, "천원": 1e3, "백만원": 1e6, "억원": 1e8}
HEAD_RE = re.compile(r"^(?:과\s*목|계\s*정\s*과\s*목|구\s*분)$")
# 기간 칸 머리글: '제11기' '제 33 기 3분기' '당기말' '전분기' '3개월' '누적' '주석'
HEADCOL_RE = re.compile(r"^(?:제\s*\d+\s*(?:\(당\)|\(전\))?\s*(?:기|期).*"
                        r"|(?:당|전전|전)\s*(?:기|분기|반기)\s*(?:말|초)?(?:\s*\d.*)?"   # '전전기'(NH투자증권 2021)
                        r"|3\s*개\s*월|누\s*적|주\s*석|금\s*액|\d{4}[\.\s년/-].*|FY.*|\(.*\))$")

KIND_RULES = [
    ("SCE", re.compile(r"자본\s*변동\s*표")),
    ("CF", re.compile(r"현금\s*흐름\s*표")),
    ("BS", re.compile(r"재무\s*상태\s*표|대차\s*대조\s*표")),
    ("IS", re.compile(r"손익\s*계산서")),
]


def _corp_to_stock():
    p = os.path.join(BASE, ".cache", "CORPCODE.xml")
    data = open(p, "rb").read().decode("utf-8", errors="replace")
    out = {}
    for m in re.finditer(r"<list>(.*?)</list>", data, re.S):
        b = m.group(1)
        s = re.search(r"<stock_code>(.*?)</stock_code>", b, re.S)
        c = re.search(r"<corp_code>(.*?)</corp_code>", b, re.S)
        if s and s.group(1).strip():
            out[c.group(1).strip()] = s.group(1).strip()
    return out


_STOCK = None


def stock_of(corp_code):
    global _STOCK
    if _STOCK is None:
        _STOCK = _corp_to_stock()
    return _STOCK.get(corp_code)


def report_dirs(corp_code, year, reprt):
    """그 기간 보고서 폴더들. 정정본이 최신이라 먼저 준다."""
    stock = stock_of(corp_code)
    if not stock:
        return []
    comp = glob.glob(os.path.join(DATA, "*_" + stock))
    if not comp:
        return []
    stamp = "%s-%s_" % (year, MONTH[reprt])
    # 결산월이 12월이 아닌 회사(비츠로셀: 6월)는 '2016-12' 가 반기보고서다. 종류까지 맞춘다.
    dirs = [d for d in glob.glob(os.path.join(comp[0], stamp + "*"))
            if os.path.isdir(d) and KIND_OF[reprt] in os.path.basename(d)]
    return sorted(dirs, key=lambda d: d.rsplit("_", 1)[-1], reverse=True)


# ---------------------------------------------------------------- 구간 찾기
SEC_START = {
    "CFS": re.compile(r"^\s*\d+\s*\.\s*연\s*결\s*재\s*무\s*제\s*표\s*$"),
    "OFS": re.compile(r"^\s*\d+\s*\.\s*(?:별\s*도\s*)?재\s*무\s*제\s*표\s*$"),
}
SEC_END = re.compile(r"^\s*\d+\s*\.\s*(?:연\s*결\s*|별\s*도\s*)?재\s*무\s*제\s*표\s*주\s*석"
                     r"|^\s*\d+\s*\.\s*(?:별\s*도\s*)?재\s*무\s*제\s*표\s*$"
                     r"|^\s*\d+\s*\.\s*(?:기\s*타\s*)?재\s*무\s*에\s*관한")


def _section(lines, div):
    start = None
    for i, ln in enumerate(lines):
        if SEC_START[div].match(ln):
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if SEC_END.match(lines[j]) and not SEC_START[div].match(lines[j]):
            return lines[start + 1:j]
    return lines[start + 1:]


def _attached(d, div):
    """감사보고서 첨부 재무제표. 사업보고서에만 있다. 주석 앞까지."""
    want = "연결재무제표" if div == "CFS" else "재무제표"
    for fn in sorted(os.listdir(d)):
        bare = re.sub(r"^\d+_|\.txt$|\(첨부\)|\s+", "", fn)
        if bare == want:
            lines = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read().splitlines()
            for i, ln in enumerate(lines):
                if re.match(r"^\s*(?:\d+\s*\.\s*)?주\s*석\s*$", ln) or re.match(r"^\s*1\s*\.\s*(?:일반사항|회사의\s*개요)", ln):
                    return lines[:i]
            return lines
    return None


def _by_heading(lines, div):
    """번호 제목 없이 표 제목만 있는 구간. 2011~2015 분기보고서의 「XI. 재무제표 등」은
    '연결 재무상태표 … 연결 현금흐름표' 다음에 곧바로 '재무상태표 …'(별도)가 온다."""
    heads = [(i, _kind(ln), "연결" in ln.replace(" ", "")) for i, ln in enumerate(lines)]
    heads = [h for h in heads if h[1] == "BS"]
    if div == "CFS":
        st = next((i for i, k, c in heads if c), None)
        if st is None:
            return None
        en = next((i for i, k, c in heads if i > st and not c), len(lines))
        return lines[st:en]
    st = next((i for i, k, c in heads if not c), None)
    return lines[st:] if st is not None else None


def _statement_lines(d, div):
    for fn in sorted(os.listdir(d)):
        if "재무에 관한 사항" in fn or "재무제표 등" in fn:
            lines = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read().splitlines()
            sec = _section(lines, div)
            if sec and len(sec) > 40:
                return sec
            if "재무제표 등" in fn:
                sec = _by_heading(lines, div)
                if sec and len(sec) > 40:
                    return sec
    return _attached(d, div)


# ---------------------------------------------------------------- 표 읽기
def _kind(line):
    # 제목을 한 글자씩 띄어 쓰는 회사가 있다: '연 결 재 무 상 태 표' (신한지주·삼성화재)
    s = re.sub(r"\s+", "", line)
    if len(s) > 40:
        return None
    for k, rx in KIND_RULES:
        if rx.search(s):
            if k == "IS" and "포괄손익계산서" in s \
                    and not re.search(r"(?<!포괄)손익계산서", s):
                return "CIS"
            return k
    return None


def _blocks(sec):
    """구간을 표 단위로 자른다. [(kind, lines)]"""
    out, cur, kind = [], [], None
    i = 0
    while i < len(sec):
        ln = sec[i]
        k, used = _kind(ln), i
        if not k and ln.strip() and len(ln.strip()) <= 8 and not _is_cell(ln):
            # 제목이 칸 너비에 잘려 여러 줄로 온다: '연 결 포' '괄 손' '익 계' '산 서' (삼성화재)
            frag, j = ln.strip(), i + 1
            while j < len(sec) and j < i + 12 and not k:
                t = sec[j].strip()
                j += 1
                if not t:
                    continue
                if len(t) > 8 or _is_cell(t):
                    break
                frag += t
                k, used = _kind(frag), j - 1
        if k:
            if kind and cur:
                out.append((kind, cur))
            kind, cur = k, []
            i = used + 1
            continue
        if kind:
            cur.append(ln)
        i += 1
    if kind and cur:
        out.append((kind, cur))
    # 같은 종류가 연달아 나오면(제목이 두 줄로 쪼개진 경우) 뒤를 앞에 붙인다
    merged = []
    for k, ls in out:
        if merged and merged[-1][0] == k and len(merged[-1][1]) < 15:
            merged[-1] = (k, merged[-1][1] + ls)
        else:
            merged.append((k, ls))
    return merged


def _num(tok):
    t = tok.strip().replace(" ", "")
    if DASH_RE.match(t):
        return None
    neg = t.startswith("(") and t.endswith(")")
    if t.endswith("원"):
        t = t[:-1]
        neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").replace("−", "-").replace("△", "-").replace("▲", "-")
    try:
        x = float(t)
    except ValueError:
        return None
    return -x if neg else x


def _is_cell(tok):
    t = tok.strip()
    return bool(NUM_RE.match(t.replace(" ", ""))) or bool(DASH_RE.match(t))


END_RE = re.compile(r"^(?:당|당분|당반|[1-4]?분|반)?기말(?:의)?현금및현금성자산|현금및현금성자산의?기말(?:잔액)?$")
CONT_RE = re.compile(r"(?:및|인한|으로|로|의|에|와|과|,|-|·|측정|순|전|차감|관련)$")
PREFIX_RE = re.compile(r"^\s*(?:(?:[IVXlⅠ-Ⅻ]+|\d{1,2}|[가나다라마바사아자차카타파하])\s*[\.\．)]|\(\d{1,2}\))\s*")
SECTION_RE = re.compile(r"^(?:자\s*산|부\s*채|자\s*본|부\s*채\s*(?:및|와)\s*자\s*본|수\s*익|비\s*용)$")


def _bare(name):
    return re.sub(r"\s+", "", PREFIX_RE.sub("", name))


def _joins(name, t):
    """칸 너비 때문에 계정명이 여러 줄로 쪼개진다.
        'X. 영업' '이' '익'            -> X. 영업이익
        'X' 'IV' '.' '당기순이익'       -> XIV.당기순이익
    이어 붙일지, 앞 줄은 숫자 없는 제목('자 산')이고 새 계정이 시작하는지 가른다."""
    if SECTION_RE.match(name.strip()) or name.strip().endswith(":"):
        return False                  # '계속영업:' 같은 소제목 (금호건설 2011)
    if PREFIX_RE.match(t) and len(PREFIX_RE.sub("", t).strip()) > 0:
        return False                  # 'Ⅰ. 현금 및 예치금' 처럼 번호로 새 줄이 시작
    if len(t) <= 3 or len(_bare(name)) <= 3:
        return True
    if re.match(r"^(?:및|과|와|의|에|으로|로)\s", t):
        return True
    return bool(CONT_RE.search(name.strip()))


def _mend_split_numbers(cells, ncol):
    """칸 너비에 잘린 숫자를 붙인다: '2' '8' '6,763,456,363' → '286,763,456,363'
    (현대해상 2020 영업이익). 붙인 결과가 정상 자릿수(1~3자리 + ,000 묶음)일 때만,
    그리고 칸 수가 정확히 맞아질 때만 받아들인다."""
    out = list(cells)
    i = 0
    while len(out) > ncol and i < len(out) - 1:
        j = i
        while j < len(out) - 1 and re.match(r"^\(?\d{1,2}$", out[j].strip()):
            j += 1                     # 한두 자리 조각들 뒤에 콤마 숫자가 오는가
        # 조각이 둘 이상일 때만. 한 조각('5' '1,234')은 주석 번호 칸일 수 있다.
        if j - i >= 2 and re.match(r"^\d{1,3}(?:,\d{3})+\)?$", out[j].strip()):
            joined = "".join(x.strip() for x in out[i:j + 1])
            if re.match(r"^\(?\d{1,3}(?:,\d{3})+\)?$", joined) and len(out) - (j - i) >= ncol:
                out[i:j + 1] = [joined]
                continue
        i += 1
    return out if len(out) == ncol else cells


def _drop_notes(toks):
    """계정명 칸 안의 괄호 설명을 걷어낸다. 설명 속 숫자가 칸으로 잡히면 행이 통째로 틀어진다.
        'X. 연결당기순이익' '(대손준비금 반영후 조정이익' '당기:' '736,801,555,452' '원' … ')'
    (삼성화재 2019~2021). 닫는 괄호가 나올 때까지(최대 12조각) 버린다."""
    out, skip = [], 0
    for t in toks:
        if re.match(r"^\(\s*주\s*석?\s*[\d,\s]+\)$", t):
            continue                   # 'VIII. 영업' '이' '익' '(주석5)' — 주석 번호 칸
        if skip:
            skip -= 1
            if t.endswith(")"):
                skip = 0
            continue
        if t.startswith("(") and ")" not in t and len(t) > 4 and not _is_cell(t):
            skip = 12
            continue
        out.append(t)
    return out


def _parse_table(lines):
    """계정명 뒤에 숫자 칸이 몇 개 오는지 세서 행을 만든다."""
    toks = _drop_notes([l.strip() for l in lines if l.strip()])
    mul, head_end, unit_at = 1, None, None
    for i, t in enumerate(toks[:60]):
        if FX_UNIT_RE.search(t):
            return None                # 외화 표시 재무제표(두산밥캣 USD). 원화 원장과 섞지 않는다.
        m = UNIT_RE.search(t)
        if m and unit_at is None:
            mul = UNIT_MUL[m.group(1)]
            unit_at = i
        if HEAD_RE.match(t) and head_end is None:
            head_end = i
    # 2019년 이후 XBRL 서식 표는 '과 목' 머리글이 없다. 단위 줄 뒤가 곧 기간 머리글이다.
    if head_end is None:
        head_end = unit_at
    if head_end is None:
        return None
    # 머리글: 과목 다음부터 첫 계정명 전까지
    i = head_end + 1
    head = []
    while i < len(toks) and not _is_cell(toks[i]) and len(head) < 14:
        t = toks[i]
        if len(t) <= 30 and HEADCOL_RE.match(t):
            head.append(t)
            i += 1
            continue
        break
    has_note = any(re.match(r"^주\s*석", h) for h in head)
    three = [k for k, h in enumerate(head) if re.match(r"^3\s*개\s*월", h)]
    cumul = [k for k, h in enumerate(head) if re.match(r"^누\s*적", h)]
    cum_first = bool(three and cumul and cumul[0] < three[0])

    rows, name, pend = [], None, []
    body = toks[i:]

    def flush():
        if name is not None and pend:
            rows.append((name, list(pend)))

    for t in body:
        if _is_cell(t):
            pend.append(t)
            continue
        if pend:
            flush()
            if name is not None and END_RE.search(_bare(name)):
                name, pend = None, []
                break                  # 기말 현금 줄이 현금흐름표의 끝이다
            name, pend = t, []
        elif name is not None and _joins(name, t):
            name = name + t if len(t) <= 3 or len(_bare(name)) <= 3 else name + " " + t
        else:
            name = t
    flush()
    if not rows:
        return None

    runs = [len(c) for _, c in rows]
    if has_note:
        plain = [len(c) for _, c in rows if not NOTE_RE.match(c[0].replace(" ", ""))]
        ncol = Counter(plain or runs).most_common(1)[0][0]
    else:
        ncol = Counter(runs).most_common(1)[0][0]
    # 옛 서식은 기간마다 '내역·금액' 두 칸을 쓴다 (예스티 2014: 제15기 · 제14기 머리글에
    # 숫자 칸 넷). 기간 머리글 수의 두 배면 짝 칸으로 보고 둘 중 값 있는 쪽을 쓴다.
    periods = [h for h in head if re.match(r"^제\s*\d+", h)]
    paired = bool(periods) and not (three and cumul) and ncol == 2 * len(periods)
    out = []
    for nm, cells in rows:
        if has_note and len(cells) == ncol + 1 and NOTE_RE.match(cells[0].replace(" ", "")):
            cells = cells[1:]
        if len(cells) > ncol:
            cells = _mend_split_numbers(cells, ncol)
        if len(cells) != ncol:
            continue                   # 빈 칸이 빠져 자리를 모른다. 버린다.
        vals = [_num(c) for c in cells]
        if paired:
            vals = [vals[k] if vals[k] is not None else vals[k + 1] for k in range(0, ncol, 2)]
        m = 1 if "주당" in nm else mul          # 주당이익은 표 단위와 무관하게 원
        vals = [v * m if v is not None else None for v in vals]
        nm = re.sub(r"\s*\(단위\s*[:：]?\s*원\)\s*$", "", nm)
        # 계정명에 붙은 긴 괄호 설명·닫히지 않은 괄호는 뗀다
        # 'X. 연결당기순이익 (대손준비금 반영후 조정이익 당기: …' (삼성화재)
        nm = re.sub(r"\s*\((?:[^)]{14,}\)?|[^)]*$)", "", nm)
        nm = re.sub(r"^\(\s*[-+]\s*\)\s*", "", nm)       # '(-)자 본 총 계' (제주은행 2011)
        nm = re.sub(r"^[-+]\s+", "", nm)                   # '- 기타수익' (금호건설 2011)
        out.append({"name": re.sub(r"\s*\(주석?\s*[\d,\s]+\)\s*$", "", nm).strip(),
                    "vals": vals})
    return {"ncol": ncol, "rows": out, "cum_first": cum_first,
            "has_3m": bool(three and cumul)}


# ---------------------------------------------------------------- 비용 부호
# 본문 손익계산서는 비용을 괄호로 적는 회사가 많다: 법인세비용 (1,106,239).
# DART API 원장은 같은 줄을 양수로 준다. 그대로 두면 2022→2023 사이에서
# 부호가 뒤집혀 증감률이 엉망이 된다. 표 단위로 판정해 비용 줄만 뒤집는다.
EXPENSE_RE = re.compile(r"(?:비용|원가|관리비|전입액|상각비)$")


def _is_expense(name):
    b = re.sub(r"\(.*?\)", "", _bare(name))
    return bool(EXPENSE_RE.search(b)) and not re.search(r"이익|손익|수익|차감", b)


def _neg_expense(rows):
    """세전이익 + 법인세비용 = 당기순이익 이면 비용을 음수로 적은 표다."""
    tax = _find(rows, r"^법인세비용$")
    bt = _find(rows, r"^법인세(?:비용)?차감전")
    ni = _find(rows, r"^(?:연결)?(?:당|분|반)?(?:\((?:당|분|반)\))?(?:분|반)?기순(?:이익|손실|손익)")
    if None in (tax, bt, ni) or tax >= 0:
        return False
    return abs(bt + tax - ni) <= max(abs(ni) * 0.005, 1e6)


# ---------------------------------------------------------------- 검산
def _find(rows, pat):
    rx = re.compile(pat)
    for r in rows:
        n = re.sub(r"\(.*?\)", "", _bare(r["name"]))
        if rx.search(n) and r["vals"] and r["vals"][0] is not None:
            return r["vals"][0]
    return None


REVENUE_NAME = re.compile(r"^(?:계속영업)?(?:매출액|영업수익|매출)|수익\(매출액\)|\(영업수익\)$")


def _top_line(rows):
    """매출이라는 이름의 줄이 없는 손익계산서에서 첫 'I.' 수익 줄을 매출로 본다.
    인카금융서비스 2018~2020: 'I.보험판매수입수수료'가 매출이다(2021~ API 는 이 줄에
    ifrs-full_Revenue 를 붙였다). '순이자이익'·'순수수료손익' 같은 순액 줄은 매출이 아니다."""
    if any(REVENUE_NAME.search(_bare(r["name"])) for r in rows):
        return None
    for r in rows[:3]:
        if not re.match(r"^\s*[IⅠ]\s*[\.．]", r["name"]):
            continue
        b = re.sub(r"\(.*?\)", "", _bare(r["name"]))
        if re.search(r"(?:수익|수수료|수입|매출액?)$", b) and not re.search(r"순|손익|이익|비용", b) \
                and r["vals"] and r["vals"][0] is not None:
            return r
    return None


def _check(kind, rows):
    if kind == "BS":
        a = _find(rows, r"^자산총계$")
        l = _find(rows, r"^부채총계$")
        e = _find(rows, r"^자본총계$")
        if a is None or e is None:
            return False
        if l is not None and abs(a - (l + e)) > max(abs(a) * 0.005, 1e6):
            return False
        return True
    if kind in ("IS", "CIS"):
        # 제목만 보고 엉뚱한 표(주석의 대손충당금 명세 등)를 잡지 않도록 이익 줄을 요구한다
        return any(_find([r], r"순이익|순손실|순손익|영업이익|영업손실|영업손익|법인세") is not None
                   or re.search(r"순이익|순손실|영업이익|법인세", _bare(r["name"])) for r in rows)
    if kind == "CF":
        # 종근당 2013: 현금흐름표 자리에 대손충당금 표를 잡았다. 영업활동 줄이 없으면 버린다.
        if not any(re.search(r"영업활[동등]|^영업(?:으로부터|에서)의?순현금", _bare(r["name"])) for r in rows):
            return False
        b = _find(rows, r"^기초.*현금|현금.*기초")
        e = _find(rows, r"^기말.*현금|현금.*기말")
        d = _find(rows, r"^(?!.*반영전).*현금.*(?:순)?(?:증가|증감|감소)")
        if None not in (b, e, d):
            fx = _find(rows, r"^(?!.*(?:증가|증감|감소)).*환율변동") or 0
            gap = abs(e - (b + d))
            gap2 = abs(e - (b + d + fx))
            return min(gap, gap2) <= max(abs(e) * 0.01, 1e6)
        return True
    return True


PREV_Q = {"11012": "11013", "11014": "11012"}


def _key(nm):
    return re.sub(r"\s+", "", PREFIX_RE.sub("", nm))


def _cum_only_to_quarter(lst, corp_code, year, reprt, div):
    """누적만 있는 반기·3분기 손익: 직전 분기 누적을 빼서 3개월을 만든다.
    직전 분기를 못 읽으면 3개월 칸은 비운다(누적은 남긴다)."""
    todo = [x for x in lst if x["thstrm_amount"] == "cum-only"]
    if not todo:
        return
    prev = statement(corp_code, year, PREV_Q[reprt], div).get("list") or []
    pc = {}
    for x in prev:
        if x["sj_div"] in ("IS", "CIS") and x.get("thstrm_add_amount") not in (None, "cum-only"):
            pc.setdefault((x["sj_div"], _key(x["account_nm"])), float(x["thstrm_add_amount"]))
    for x in todo:
        cum = x.get("thstrm_add_amount")
        p = pc.get((x["sj_div"], _key(x["account_nm"])))
        x["thstrm_amount"] = "%.0f" % (float(cum) - p) if cum is not None and p is not None else None


# ---------------------------------------------------------------- 공개 함수
def statement(corp_code, year, reprt, div="CFS"):
    """API 원장 모양으로 돌려준다. 못 읽으면 {"status": "none", "list": []}."""
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, "%s_%s_%s_%s.json" % (corp_code, year, reprt, div))
    if os.path.exists(cp):
        try:
            js = json.load(open(cp, encoding="utf-8"))
            if js.get("v") == VERSION:
                return js
        except Exception:
            pass
    res = {"v": VERSION, "status": "none", "list": [], "src": None, "dropped": []}
    for d in report_dirs(corp_code, year, reprt):
        try:
            sec = _statement_lines(d, div)
        except Exception:
            sec = None
        if not sec:
            continue
        lst, seen, dropped = [], set(), []
        for kind, ls in _blocks(sec):
            if kind == "SCE" or kind in seen:
                continue
            t = _parse_table(ls)
            if not t or not t["rows"]:
                continue
            if not _check(kind, t["rows"]):
                dropped.append(kind)
                continue
            seen.add(kind)
            flip = kind in ("IS", "CIS") and _neg_expense(t["rows"])
            quarter_is = kind in ("IS", "CIS") and reprt != "11011" and t["has_3m"]
            top = _top_line(t["rows"]) if kind in ("IS", "CIS") else None
            for r in t["rows"]:
                v = r["vals"]
                if flip and _is_expense(r["name"]):
                    v = [-x if x is not None else None for x in v]
                c3, cc = (1, 0) if t["cum_first"] else (0, 1)
                if quarter_is:
                    cur, cum = v[c3], (v[cc] if len(v) > cc else None)
                elif kind == "CF" and reprt != "11011" and t["has_3m"] and len(v) > cc:
                    # 3개월·누적 칸이 다 있는 현금흐름표(삼성전자 2011). API 원장처럼 누적을 쓴다.
                    cur, cum = v[cc], None
                else:
                    cur, cum = v[0], None
                if reprt != "11011" and kind in ("IS", "CIS") and not t["has_3m"]:
                    # 3개월 칸이 없다. 1분기는 3개월 = 누적이고, 반기·3분기는
                    # 누적만 있는 것이다(KB금융 정정본). 3개월은 뒤에서 뺀다.
                    cum = cur
                    if reprt != "11013":
                        cur = "cum-only"
                lst.append({"sj_div": kind,
                            "account_id": "ifrs-full_Revenue" if r is top else "-표준계정코드 미사용-",
                            "account_nm": r["name"],
                            "thstrm_amount": cur if cur in (None, "cum-only") else "%.0f" % cur,
                            "thstrm_add_amount": None if cum is None else "%.0f" % cum,
                            "src": "본문"})
        if lst and "BS" in seen:
            _cum_only_to_quarter(lst, corp_code, year, reprt, div)
            res = {"v": VERSION, "status": "body", "list": lst,
                   "src": os.path.basename(d), "dropped": dropped}
            break
        res["dropped"] = dropped
    with open(cp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)
    return res
