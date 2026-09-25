# -*- coding: utf-8 -*-
"""
수주잔고 추출 — 정기보고서 본문에서 기말 수주잔고 총액을 꺼내 시계열로 만든다.

DART 재무제표 API 에는 수주잔고가 없다. 「II. 사업의 내용 → 매출 및 수주상황
→ 수주상황」 표나 본문 문장에만 있다. 이미 수집해 둔 보고서 본문을 읽는다.

표는 셀마다 한 줄로 펴져 있어 열 구조를 믿고 읽을 수 없다. 그래서 두 경로로
찾고, 찾은 근거 줄을 같이 돌려준다.

  1) 문장  "수주잔고는 304,046억원을 확보"  같은 서술. 단위가 문장에 붙어 있어
           가장 믿을 만하다.
  2) 표    '수주상황' 소절 안의 '합계/총계' 행. 수주잔고는 대개 마지막 열이라
           합계 행 숫자 묶음의 마지막 값을 쓴다. 소계가 여러 개면 가장 큰 값
           (전체 합계는 모든 소계보다 크거나 같다).

주의 — '4. 매출 및 수주상황' 제목에 걸리면 매출 표의 합계를 잡는다. 반드시
'수주상황' 소절(가./나./다. …)부터 읽는다.
"""
import os
import re
import json
import time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "기업추적_수집")
CACHE_DIR = os.path.join(BASE, ".cache", "수주")

# 추출 규칙이 바뀌면 올린다. 캐시의 옛 결과(특히 실패)를 다시 뽑는다.
VERSION = 2

UNIT_WON = {"원": 1, "천원": 1e3, "만원": 1e4, "백만원": 1e6, "천만원": 1e7,
            "억원": 1e8, "십억원": 1e9, "조원": 1e12}

# 소절 제목: '다. 수주상황', '나. 진행률적용 수주 상황', '(2) 수주현황' 등
# 두산에너빌리티 2026 반기는 '다. 당반기말 현재 주요사업부문별 수주상황' (16자 수식어)
SEC_START = re.compile(
    r"^(?:[가-하]\.|\(?\d+\)|[①-⑩])\s*(?:[^\n]{0,24})?수\s*주\s*(?:상\s*황|현\s*황|잔\s*고)")
# 다음 소절/항목 제목에서 끊는다
SEC_END = re.compile(r"^(?:[가-하]\.\s|\d+\.\s|[IVX]+\.\s)")
UNIT_RE = re.compile(r"단\s*위\s*[:：]?\s*([가-힣A-Za-z$￦₩]+)")
TOTAL_RE = re.compile(r"^(?:합\s*계|총\s*계|합\s*산|계)$")
SUBTOTAL_RE = re.compile(r"^(?:소\s*계|.{1,8}\s+계)$")    # '소계', '국내 계' 같은 중간 합
NUM_LINE = re.compile(r"^[△▲\-\(]?[\d,]+(?:\.\d+)?\)?$")

# 서술형: '수주잔고는 304,046억원', '수주잔고 약 2.3조원', '수주잔고 12,345백만원'
SENT_RE = re.compile(
    r"수주\s*잔고[는은가이\s]*(?:약\s*|총\s*)?([\d,]+(?:\.\d+)?)\s*(조|억|백만|천만|천|만)?\s*원")


def _num(s):
    s = s.strip().replace(",", "")
    neg = s.startswith(("△", "▲", "-", "(")) and s not in ("-",)
    s = s.strip("△▲-()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _unit_mult(u):
    if not u:
        return None, None
    u = u.strip()
    if re.search(r"USD|US\$|\$|달러|EUR|유로|JPY|엔화|CNY|위안", u, re.I):
        return None, u                 # 외화 — 원화 환산하지 않는다
    for k in sorted(UNIT_WON, key=len, reverse=True):
        if u.startswith(k):
            return UNIT_WON[k], k
    return None, u


def from_sentence(text):
    best = None
    for m in SENT_RE.finditer(text):
        v = _num(m.group(1))
        if v is None or v <= 0:
            continue
        mult = {"조": 1e12, "억": 1e8, "백만": 1e6, "천만": 1e7,
                "천": 1e3, "만": 1e4, None: 1}[m.group(2)]
        won = v * mult
        a = max(0, m.start() - 40)
        line = text[a:m.end() + 20].replace("\n", " ")
        cand = {"value": won, "method": "문장", "unit": (m.group(2) or "") + "원",
                "source": line.strip()}
        if best is None or won > best["value"]:
            best = cand
    return best


# 표 머리글의 '잔고' 칸. 소절 제목이 없는 회사(한화오션)도 머리글은 있다.
ANCHOR_RE = re.compile(r"^(?:기말\s*)?(?:수주|계약)\s*잔\s*(?:고|액|량)(?:\s*\(.{0,10}\))?$")
PCT_LIKE = re.compile(r"^\d{1,3}\.\d+$")


def _runs(lines, a, b):
    """[a, b) 구간의 숫자 묶음. 각 묶음 앞 줄이 합계면 total=True."""
    runs, k = [], a
    while k < b:
        if NUM_LINE.match(lines[k]) and not PCT_LIKE.match(lines[k]):
            start, nums = k, []
            while k < b and (lines[k] in ("", "-", "〃") or NUM_LINE.match(lines[k])):
                if NUM_LINE.match(lines[k]) and not PCT_LIKE.match(lines[k]):
                    v = _num(lines[k])
                    if v is not None:
                        nums.append(v)
                k += 1
            prev = start - 1
            while prev >= a and lines[prev] in ("", "-", "〃"):
                prev -= 1
            label = lines[prev] if prev >= a else ""
            kind = ("total" if TOTAL_RE.match(label) else
                    "sub" if SUBTOTAL_RE.match(label) else "row")
            if nums:
                runs.append({"nums": nums, "total": kind == "total", "kind": kind,
                             "at": start})
            continue
        k += 1
    return runs


def _backlog_of(nums):
    """숫자 묶음에서 잔고를 고른다. 검산이 되면 그 값을 믿는다.

    수주 표는 산술 관계가 성립한다.
      [총액, 납품, 잔고]        잔고 = 총액 − 납품
      [기초, 신규, 납품, 기말]   기말 = 기초 + 신규 − 납품
    (한화오션 41,675,211 − 8,666,801 = 33,008,410 이 정확히 맞는다)
    검산이 맞으면 제대로 잡았다는 강한 증거다.
    """
    pos = [v for v in nums if v > 0]
    if not pos:
        return None, False
    ab = [abs(v) for v in nums]
    for i in range(len(ab) - 1, 1, -1):
        c = ab[i]
        if c <= 0:
            continue
        a, b = ab[i - 2], ab[i - 1]
        if abs((a - b) - c) <= max(2, c * 0.002):
            return c, True
        if i >= 3:
            a0 = ab[i - 3]
            if abs((a0 + a - b) - c) <= max(2, c * 0.002):
                return c, True
    # 검산이 안 되면 마지막 양수. 잔고는 대개 마지막 열이다.
    return pos[-1], False


def from_table(text):
    lines = [ln.strip() for ln in text.split("\n")]
    n = len(lines)
    anchors = [i for i, s in enumerate(lines) if len(s) < 24 and ANCHOR_RE.match(s)]
    # 소절 제목도 기준점으로 쓴다 (표 머리글이 '잔고' 대신 다른 말인 회사)
    anchors += [i for i, s in enumerate(lines)
                if len(s) < 40 and SEC_START.search(s) and "매출" not in s]
    anchors = sorted(set(anchors))

    cands, last_end = [], -1
    for i in anchors:
        if i < last_end:                      # 같은 표 안의 두 번째 머리글
            continue
        # 표의 끝 — 다음 번호 제목에서 끊는다. 안 끊으면 아래 '5. 위험관리'
        # 금융자산 표의 합계를 잡는다 (HD현대일렉트릭이 그랬다).
        end = min(n, i + 500)
        for j in range(i + 1, end):
            if SEC_END.match(lines[j]) and not ANCHOR_RE.match(lines[j]):
                end = j
                break
        last_end = end
        runs = _runs(lines, i + 1, end)
        if not runs:
            continue
        # 단위 — 첫 숫자 바로 위에서 가장 가까운 것.
        # 소절 제목을 기준점으로 잡으면 '(단위 : 백만원)'이 제목 '아래'에 있다.
        # 위쪽만 찾으면 단위를 못 찾고 원화가 아닌 것으로 버려진다
        # (HD현대중공업·한화에어로·엘에스일렉트릭이 그랬다).
        unit_mult, unit_raw = None, None
        for j in range(runs[0]["at"], max(-1, runs[0]["at"] - 45), -1):
            um = UNIT_RE.search(lines[j])
            if um:
                unit_mult, unit_raw = _unit_mult(um.group(1))
                break
        totals = [r for r in runs if r["total"]]
        if totals:
            picks, how = totals, "합계"
        elif len(runs) == 1:
            picks, how = runs, "단일행"
        else:
            picks, how = None, "행합산"
        if picks:
            best = None
            for r in picks:
                v, ok = _backlog_of(r["nums"])
                if v is None:
                    continue
                if best is None or (ok, v) > (best[1], best[0]):
                    best = (v, ok, r)
            if not best:
                continue
            v, ok, r = best
            nums_show = r["nums"][-4:]
        else:
            # 합계 없이 부문이 여러 줄 — 줄마다 잔고를 뽑아 더한다.
            # '소계' 줄은 빼야 한다. 넣으면 같은 금액이 두 번 들어간다.
            vals, oks = [], 0
            for r in [x for x in runs if x["kind"] == "row"]:
                x, ok = _backlog_of(r["nums"])
                if x:
                    vals.append(x)
                    oks += ok
            if not vals:
                continue
            v, ok = sum(vals), oks == len(vals)
            nums_show = vals[-4:]
        cands.append({"raw": v, "ok": ok, "how": how, "unit_mult": unit_mult,
                      "unit": unit_raw, "head": lines[i], "nums": nums_show})

    if not cands:
        return None
    won = [c for c in cands if c["unit_mult"]]
    if not won:
        fx = [c for c in cands if c["unit"]]
        if fx:
            c = max(fx, key=lambda c: (c["ok"], c["raw"]))
            return {"value": None, "fx_value": c["raw"], "method": "표(외화)",
                    "unit": c["unit"], "source": c["head"]}
        return None
    # 검산 맞은 것 > 합계 > 큰 값
    rank = {"합계": 2, "단일행": 1, "행합산": 0}
    c = max(won, key=lambda c: (c["ok"], rank[c["how"]], c["raw"] * c["unit_mult"]))
    return {"value": c["raw"] * c["unit_mult"], "method": "표·" + c["how"],
            "verified": c["ok"], "unit": c["unit"],
            "source": "%s … %s  [%s]" % (
                c["head"], " · ".join("{:,.0f}".format(x) for x in c["nums"]),
                "검산 일치" if c["ok"] else "검산 불가")}


def extract(text):
    """표와 문장을 둘 다 보고 대조한다.

      비슷하면(0.5~2배)     표. 문장과 교차 확인됨.
      20배 넘게 차이        단위 착오다. 단위가 숫자에 붙어 있는 문장을 믿는다.
      그 사이로 차이        큰 쪽. 전체 잔고는 어느 부문 잔고보다 크거나 같고,
                            추출이 틀릴 때는 대개 일부(한 자회사·한 부문)를 잡는다.
    """
    t = from_table(text)
    s = from_sentence(text)
    if t and t.get("value") and s:
        ratio = t["value"] / s["value"]
        if 0.5 <= ratio <= 2.0:
            t["check"] = "문장과 일치"
            return t
        if ratio > 20 or ratio < 0.05:
            s["check"] = "표와 %.0f배 차이 — 단위 착오로 보고 문장 채택" % ratio
            return s
        pick = t if t["value"] > s["value"] else s
        pick["check"] = "표 %s / 문장 %s — 큰 쪽 채택" % (
            "{:,.0f}억".format(t["value"] / 1e8), "{:,.0f}억".format(s["value"] / 1e8))
        return pick
    return t if (t and t.get("value")) else (s or t)


# ---------------------------------------------------------------- 시계열
def _cache_path(code):
    return os.path.join(CACHE_DIR, code + ".json")


def company_series(company, read_section, max_reports=16):
    """회사 하나의 수주잔고 시계열. 보고서별로 캐시한다(접수번호 키)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(company["code"])
    cache = {}
    if os.path.exists(path):
        try:
            cache = json.load(open(path, encoding="utf-8"))
        except Exception:
            cache = {}
    reps = [r for r in company["reports"] if not r["tag"]
            and r["label"] in ("사업보고서", "반기보고서", "분기보고서")]
    reps = reps[-max_reports:]
    changed = False
    pts = []
    for r in reps:
        hit = cache.get(r["rcept"])
        if hit is not None and hit.get("v") != VERSION:
            hit = None
        if hit is None:
            sec = next((s for s in r["sections"] if s["norm"] == "사업의 내용"), None)
            text = read_section(company, r, sec["file"]) if sec else ""
            if "수주" not in text:
                hit = {"none": True}
            else:
                hit = extract(text) or {"none": True}
            hit["v"] = VERSION
            cache[r["rcept"]] = hit
            changed = True
        if hit.get("value"):
            pts.append({"stamp": r["stamp"], "label": r["label"], "rcept": r["rcept"],
                        "value": hit["value"], "method": hit.get("method"),
                        "verified": hit.get("verified"),
                        "source": hit.get("source"), "check": hit.get("check")})
    if changed:
        json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return _drop_outliers(pts)


def _drop_outliers(pts):
    """검산이 안 된 값이 검산된 값들의 중앙값과 5배 넘게 어긋나면 뺀다.
    삼성에스디에스 2024 반기: 다른 표의 '344 · 15,344 · 9 · 0' 을 잡아 0.0조가 됐다."""
    good = sorted(x["value"] for x in pts if x.get("verified"))
    if len(good) < 3:
        return pts
    med = good[len(good) // 2]
    return [x for x in pts if x.get("verified") or x.get("method") == "문장"
            or 0.2 <= x["value"] / med <= 5]


def trend(pts, window=8):
    """꾸준히 늘었는가.

    최근 window 개 보고서만 본다. 판정은 네 가지를 같이 본다.
      증가 비율   직전 보고서 대비 늘어난 횟수 / 비교 횟수
      최대 낙폭   구간 안에서 직전 대비 가장 크게 줄어든 폭
      전년 대비   최신값 vs 4개 보고서 전(=1년 전) 값
      연율 성장   구간 처음과 끝의 연율 환산 증가율
    추출이 한 번 틀리면 값이 튀는데, 튀는 시계열은 '꾸준히' 조건을 못 넘는다.
    """
    p = [x for x in pts if x.get("value")][-window:]
    if len(p) < 4:
        return None
    vals = [x["value"] for x in p]
    ups = sum(1 for a, b in zip(vals, vals[1:]) if b > a)
    comps = len(vals) - 1
    drops = [(b - a) / a for a, b in zip(vals, vals[1:]) if a > 0]
    worst = min(drops) if drops else 0
    yoy = (vals[-1] / vals[-5] - 1) * 100 if len(vals) >= 5 and vals[-5] > 0 else None
    years = max((len(vals) - 1) / 4.0, 0.25)
    cagr = ((vals[-1] / vals[0]) ** (1 / years) - 1) * 100 if vals[0] > 0 else None
    # 비정상 급변(추출 오류 의심): 한 번에 5배 이상 뛰거나 1/5 로 줄면 신뢰도 낮음
    jumps = sum(1 for a, b in zip(vals, vals[1:]) if a > 0 and (b / a > 5 or b / a < 0.2))
    steady = (ups / comps >= 0.7 and worst > -0.15 and (yoy is None or yoy > 5)
              and jumps == 0 and vals[-1] > vals[0])
    return {"n": len(vals), "ups": ups, "comps": comps, "up_ratio": ups / comps,
            "worst_drop": worst * 100, "yoy": yoy, "cagr": cagr,
            "first": vals[0], "last": vals[-1], "jumps": jumps,
            "steady": steady, "from": p[0]["stamp"], "to": p[-1]["stamp"]}
