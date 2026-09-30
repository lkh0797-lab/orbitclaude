# -*- coding: utf-8 -*-
"""
시너지 발굴 — 수주가 실적과 주가로 넘어가는 길목을 잡는다.

따로 놓고 보면 흔한 신호 넷을 한 줄에 세운다.

  선행   매출로 빠져나가는 속도보다 빨리 쌓이나(북투빌), 잔고가 연매출의 몇 배인지가 1년 새 늘었나(배수 변화)
  전환   4분기 합 영업이익률이 아직 낮아 늘어날 여지가 있나
  확인   마지막 정기보고서 이후 새로 공시된 수주 계약(단일판매·공급계약)이 있나
  가격   주가가 1년 동안 수주 증가만큼 올랐나 — 덜 올랐으면 '반영 갭'

부분 안의 항목은 과거 검증(도구/시너지_백테스트.py, 2013~2025 매달 6,823건·122곳)으로 골랐다.
  - 매출 가속은 12개월 초과수익과 관계가 없었다(IC 0.00). 전환 부분에서 뺐다.
  - 영업이익률은 낮을수록 뒤 수익률이 좋았다. 한 분기 값(−6%p)보다 4분기 합(−8%p, 앞 −7 / 뒤 −10)이 더 강하고 고르다.
    전환 부분은 4분기 합 이익률 하나만 쓴다(IC 0.095, t 2.4). 직전 분기 대비 변화는 큰 적자 분기 뒤 본전만 돼도
    '개선'으로 잡혀(가온칩스 −19% → +1.5%) 뺐다. 적자는 0%로 묶어, 적자가 깊을수록 점수가 오르지 않게 한다.
  - 4분기 합 적자인 회사는 뒤 수익률이 오히려 좋았다(둔화 뺀 중앙 +13% vs 흑자 +7%, 앞뒤 기간·조선 뺀 표본 모두 같은 방향).
    다만 지금 상장된 회사만 있어 망해서 사라진 적자 회사가 빠졌고, 1년 뒤 −30%↓ 비율도 12% vs 9%로 높다.
    그래서 감점하지 않되 화면에 '4분기 적자 — 턴어라운드 베팅'으로 따로 표시하고 흑자만 보는 거름을 둔다.
  - 북투빌이 잔고 증가율보다 강했다(+14%p vs +11%p).
  - 기간은 1년이 가장 좋았다. 잔고 변화 IC 3개월 .036 · 6개월 .056 · 1년 .069 · 2년 .029 · 3년 .041,
    북투빌 1분기 .030 · 2분기 .072 · 1년 .075 · 2년 .023. 짧으면 분기 잡음, 길면 이미 반영된 옛 이야기다.
  - 형태로는 '잔고/연매출 배수의 1년 변화'가 가장 고르다(IC .074, 앞 .080 / 뒤 .067). 다른 잔고 지표는 2019년 전엔 약했다.
    잔고 증가율은 둔화 판정(잔고 감소)에 이미 쓰이고, 둔화를 뺀 나머지 안에서는 힘이 없었다.
    그래서 선행 = 북투빌 .5 + 배수 변화 .5 (점수 IC .095 → .100, 날짜마다 상위 20% 12개월 초과수익 중앙: 둔화 뺀 +12% → +15%).
  - PER 은 관계가 없었다. 가격 부분은 반영 갭만 쓴다.
  - 확인(수주 공시)과 악재 감점은 과거 공시 목록이 없어 검증하지 못했다. 그대로 둔다.
  - 점수 예측력의 대부분은 '둔화'(잔고 감소·북투빌 0.9 미만)를 가르는 데서 나온다. 둔화를 뺀 나머지 안에서는
    상위⅓−하위⅓ +4.6%p(90% 구간 −1.6 ~ +10.8)로 작고 불확실하다.

수주잔고는 분기 보고서에만 나와 최대 석 달 늦다. 그 사이 새 계약은 거래소
공시(단일판매·공급계약체결)로 먼저 나온다. 이 공시 원문에는 계약금액과
'최근 매출액 대비 %'가 정형 칸으로 들어 있어 바로 읽힌다.

단계:
  잠복   수주는 쌓이는데 매출·주가는 아직 — 가장 이른 자리
  점화   쌓인 수주가 매출 가속·이익률 개선으로 넘어오는 중
  반영   주가가 수주보다 앞서 갔다 — 늦게 따라붙는 자리
  둔화   잔고가 줄거나 들어오는 수주가 매출보다 적다
  관찰   뚜렷하지 않음
"""
import os
import re
import io
import json
import html
import time
import zipfile
import datetime as dt

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache", "시너지", "계약")
DART = "https://opendart.fss.or.kr/api"


# ---------------------------------------------------------------- 계약 공시 원문
def _num(s):
    s = (s or "").strip().replace(",", "")
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _field(t, label, pat=r"([^\n]+)"):
    m = re.search(label + r"\s*\n\s*" + pat, t)
    return m.group(1).strip() if m else None


def parse_contract(text):
    """단일판매ㆍ공급계약체결 원문에서 정형 칸을 읽는다."""
    t = re.sub(r"<[^>]+>", "\n", text)
    t = html.unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t)
    i = t.find("판매ㆍ공급계약 구분")
    if i < 0:
        i = t.find("판매·공급계약 구분")
    body = t[i:] if i >= 0 else t
    out = {
        "kind": _field(body, r"판매[ㆍ·]공급계약 구분"),
        "title": _field(body, r"- 체결계약명"),
        "amount": _num(_field(body, r"계약금액\(원\)", r"([\d,\-]+)")),
        "revenue": _num(_field(body, r"최근매출액\(원\)", r"([\d,\-]+)")),
        "pct": _num(_field(body, r"매출액대비\(%\)", r"([\d\.,\-]+)")),
        "party": _field(body, r"3\. 계약상대"),
        "region": _field(body, r"4\. 판매[ㆍ·]공급지역"),
        "start": _field(body, r"시작일", r"(\d{4}-\d{2}-\d{2}|-)"),
        "end": _field(body, r"종료일", r"(\d{4}-\d{2}-\d{2}|-)"),
        "signed": _field(body, r"계약\(수주\)일자", r"(\d{4}-\d{2}-\d{2}|-)"),
    }
    if out["pct"] is None and out["amount"] and out["revenue"]:
        out["pct"] = out["amount"] / out["revenue"] * 100
    # 자회사 공시(지주사가 대신 낸 것)는 '자회사의 주요경영사항'이 제목에 붙는다
    out["subsidiary"] = "자회사" in t[:600]
    return out


def contract(api_key, rcept):
    """공시 한 건. 원문을 받아 읽고 캐시한다. 일시 오류는 캐시하지 않는다."""
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, rcept + ".json")
    if os.path.exists(cp):
        try:
            return json.load(open(cp, encoding="utf-8"))
        except Exception:
            pass
    try:
        r = requests.get(DART + "/document.xml", timeout=60,
                         params={"crtfc_key": api_key, "rcept_no": rcept})
    except Exception:
        return None
    if r.content[:2] != b"PK":
        return None
    text = ""
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            raw = z.read(name)
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    text += raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
    out = parse_contract(text)
    out["rcept"] = rcept
    with open(cp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    time.sleep(0.2)
    return out


# ---------------------------------------------------------------- 주가
def _adjusted(prices, ds):
    """액면분할·병합 보정. 하루 가격제한폭(±30%)을 넘는 움직임은 시장이 아니라
    주식 수가 바뀐 것이다. 그 앞의 가격을 비율만큼 고쳐 이어 붙인다.
    상장 직후 5거래일은 제한폭이 달라 건드리지 않는다."""
    adj = [prices[d] for d in ds]
    for i in range(len(ds) - 1, 5, -1):
        a, b = adj[i - 1], adj[i]
        if a and b and not (0.69 <= b / a <= 1.31):
            k = b / a
            for j in range(i):
                adj[j] *= k
    return adj


def price_stats(prices, snap_date=None):
    """주가 요약. 분할 보정한 종가로 1개월·3개월·1년 수익률, 52주 고점 대비,
    그리고 snap_date 이후 변화 배수(시가총액 스냅샷을 오늘로 옮길 때 쓴다)."""
    if not prices:
        return {}
    ds = sorted(prices)
    adj = _adjusted(prices, ds)
    last = dt.datetime.strptime(ds[-1], "%Y%m%d")

    def idx_before(days=None, date=None):
        ref = date or (last - dt.timedelta(days=days)).strftime("%Y%m%d")
        k = None
        for i, d in enumerate(ds):
            if d <= ref:
                k = i
            else:
                break
        return k

    out = {"now": prices[ds[-1]], "date": ds[-1]}
    for key, days in (("p1m", 30), ("p3m", 91), ("p1y", 365)):
        k = idx_before(days)
        out[key] = (adj[-1] / adj[k] - 1) * 100 if k is not None and adj[k] else None
    ref = (last - dt.timedelta(days=365)).strftime("%Y%m%d")
    win = [adj[i] for i, d in enumerate(ds) if d > ref] or adj[-1:]
    hi = max(win)
    out["dd52"] = (adj[-1] / hi - 1) * 100 if hi else None
    if snap_date:
        k = idx_before(date=snap_date)
        out["since_snap"] = adj[-1] / adj[k] if k is not None and adj[k] else None
    return out


def price_change(prices, days):
    """최근 종가 대비 days 일 전 종가의 변화율(%). prices = {'YYYYMMDD': 종가}"""
    if not prices:
        return None, None
    ds = sorted(prices)
    last = ds[-1]
    ref = (dt.datetime.strptime(last, "%Y%m%d") - dt.timedelta(days=days)).strftime("%Y%m%d")
    old = [i for i, d in enumerate(ds) if d <= ref]
    if not old:
        return None, prices[last]
    adj = _adjusted(prices, ds)
    p0 = adj[old[-1]]
    return ((adj[-1] / p0 - 1) * 100 if p0 else None), prices[last]


# ---------------------------------------------------------------- 점수·단계
def _pct_rank(vals):
    clean = sorted(v for v in vals if v is not None)
    n = len(clean)
    if n < 2:
        return lambda v: None
    def f(v):
        if v is None:
            return None
        lo = sum(1 for x in clean if x < v)
        eq = sum(1 for x in clean if x == v)
        return (lo + eq / 2.0) / n * 100
    return f


# 가중치. 수주가 먼저 움직이고(선행) 매출이 따라오며(전환) 주가가 마지막에 반영된다.
# 확인(최근 계약 공시)은 분기 보고서 사이의 공백을 메우는 보조 신호라 가볍게 둔다.
WEIGHTS = {"선행": 0.35, "전환": 0.25, "확인": 0.15, "가격": 0.25}


# ---------------------------------------------------------------- 추천필터
# 화면 오른쪽 '추천필터'. 한 번 누르면 아래 거름값이 '직접 설정 필터'에 채워진다.
# 키 이름은 화면(웹/index.html SYN_DEF)과 같다. 도구/시너지_백테스트.py 가 같은 정의로 과거 성과를 잰다.
# 기준값은 결과를 보고 맞춘 것이 아니라 먼저 정했다 — 과거 검증에서 예측력이 있던 신호만 쓴다.
_NOT_SLOW = ["잠복", "점화", "반영", "관찰"]
SYN_REC = [      # 순서: 과거 성과가 좋고 위험이 낮은 것부터, 공격적인 것은 뒤로
    {"id": "room", "name": "이익률 여지",
     "desc": "4분기 합 영업이익·순이익 모두 흑자지만 영업이익률 6% 이하 — 쌓인 수주가 매출로 넘어오면 이익률이 오를 자리",
     "f": {"stages": _NOT_SLOW, "btbMin": 1.1, "m4Min": 0, "m4Max": 6, "noLoss": True}},
    {"id": "outpace", "name": "잔고가 매출을 앞지름",
     "desc": "새 수주가 매출보다 1.3배 빨리 쌓이고, 잔고가 연매출의 몇 배인지가 1년 새 0.3년 넘게 늘었다",
     "f": {"stages": _NOT_SLOW, "btbMin": 1.3, "coverChgMin": 0.3}},
    {"id": "gap", "name": "덜 오른 수주",
     "desc": "잔고 증가가 주가 상승을 50%p 넘게 앞선다 — 수주는 쌓였는데 주가는 아직",
     "f": {"stages": _NOT_SLOW, "btbMin": 1.1, "gapMin": 50}},
    {"id": "safe", "name": "흑자·무사고",
     "desc": "4분기 흑자, 최근 악재 공시 없음, 잔고 소진 아님 — 턴어라운드 베팅을 뺀 보수적 목록",
     "f": {"stages": _NOT_SLOW, "btbMin": 1.0, "noLoss": True, "noFlags": True}},
    {"id": "turn", "name": "턴어라운드 베팅",
     "desc": "4분기 적자인데 수주가 빠르게 쌓인다 — 과거 수익률은 높았지만 크게 잃은 경우도 많다",
     "f": {"stages": _NOT_SLOW, "btbMin": 1.2, "onlyLoss": True}},
    {"id": "noslow", "name": "둔화 빼기",
     "desc": "잔고가 줄거나 소진 중인 곳만 뺀다 — 과거에 유일하게 확실히 뒤처진 무리. 가장 넓은 출발점",
     "f": {"stages": _NOT_SLOW}},
]


def rec_pass(r, f):
    """추천필터 거름 — 화면 synPass 의 같은 키만 옮겼다(백테스트용). 악재 공시(noFlags)는 과거 자료가 없어 보지 않는다."""
    def num(v):
        return None if v in (None, "") else float(v)

    def ge(v, m):
        return num(m) is None or (v is not None and v >= num(m))

    def le(v, m):
        return num(m) is None or (v is not None and v <= num(m))
    m4 = r.get("margin4")
    return ((not f.get("stages") or r.get("stage") in f["stages"])
            and ge(r.get("btb"), f.get("btbMin")) and ge(r.get("backlog_yoy"), f.get("yoyMin"))
            and ge(r.get("cover_chg"), f.get("coverChgMin")) and ge(r.get("gap"), f.get("gapMin"))
            and ge(m4, f.get("m4Min")) and le(m4, f.get("m4Max"))
            and not (f.get("noLoss") and r.get("loss4")) and not (f.get("onlyLoss") and not r.get("loss4")))


def _margin(r):
    """4분기 합 영업이익률. 지주사처럼 발산한 값은 뺀다."""
    m = r.get("margin4")
    return m if (m is not None and abs(m) <= 100) else None


def score(rows):
    """rows 는 build_row 결과. 신뢰할 수 있는 행끼리 백분위를 매긴다."""
    ok = [r for r in rows if r["reliable"]]
    R = {
        "btb": _pct_rank([r["btb"] for r in ok]),
        "cov": _pct_rank([r.get("cover_chg") for r in ok]),
        # 이익률은 낮을수록 좋다 — 늘어날 여지(수주 산업의 영업 레버리지). 지주사처럼 발산한 값은 뺀다.
        # 적자는 0%로 묶는다. 과거에 적자(+6%)는 0~3%(+5%)와 비슷했지 더 좋지 않았다 — 적자 폭이 클수록 점수가 오르면 안 된다.
        "low": _pct_rank([-max(_margin(r), 0) if _margin(r) is not None else None for r in ok]),
        "new": _pct_rank([r["new_pct"] for r in ok]),
        "gap": _pct_rank([r["gap"] for r in ok]),
    }

    def blend(parts):
        tot = wsum = 0.0
        for v, w in parts:
            if v is None:
                continue
            tot += v * w
            wsum += w
        return tot / wsum if wsum else None

    for r in rows:
        if not r["reliable"]:
            r["score"], r["parts"] = None, {}
            continue
        m = _margin(r)
        parts = {
            "선행": blend([(R["btb"](r["btb"]), 0.5), (R["cov"](r.get("cover_chg")), 0.5)]),
            "전환": R["low"](-max(m, 0)) if m is not None else None,
            # 최근 계약 공시가 없으면 0점이 아니라 '해당 없음'으로 두면 없는 회사가
            # 오히려 유리해진다. 없으면 0 으로 센다.
            "확인": R["new"](r["new_pct"]) if r["new_pct"] else 0.0,
            "가격": R["gap"](r["gap"]),
        }
        s = blend([(parts[k], WEIGHTS[k]) for k in WEIGHTS])
        if s is not None and r["flags"]:
            s -= 10 * len(r["flags"])          # 희석·소송 같은 최근 악재 공시
        r["parts"] = {k: (round(v) if v is not None else None) for k, v in parts.items()}
        r["score"] = round(max(s, 0), 1) if s is not None else None
    return rows


def stage(r):
    """단계와 그 이유 한 줄."""
    y, btb = r["backlog_yoy"], r["btb"]
    acc, mgn, yoyr = r["rev_accel"], r["margin_delta"], r["rev_yoy"]
    px, per = r["price_1y"], r["per"]
    if y is None:
        return "관찰", "1년 전 잔고가 없어 비교할 수 없다"
    if y < 0 or (btb is not None and btb < 0.9):
        return "둔화", "잔고가 줄거나, 들어오는 수주가 매출로 나가는 것보다 적다"
    if px is not None and px >= max(50.0, y * 1.5):
        return "반영", "주가가 수주보다 앞서 갔다 (주가 %+.0f%% vs 수주 %+.0f%%)" % (px, y)
    if per and per >= 40:
        return "반영", "PER %.0f배 — 이익에 비해 주가가 이미 높다" % per
    # 매출이 아직 역성장이면 가속이 붙어도 '덜 나빠진' 것이다 (엠앤씨솔루션 -4%). 점화로 보지 않는다.
    if y >= 10 and acc is not None and acc > 0 and (yoyr is None or yoyr > 0) \
            and (mgn is None or mgn >= 0):
        return "점화", "쌓인 수주가 매출 가속·이익률로 넘어오는 중"
    if y >= 15 and (btb is None or btb >= 1.1) and \
            (acc is None or acc <= 0 or (yoyr is not None and yoyr < y / 2)):
        # 주가가 수주 증가의 절반 넘게 이미 올랐으면 '아직'이 아니다 (자이에스앤디 +190% vs +201%)
        if px is None or px < y * 0.5:
            return "잠복", "수주는 쌓이는데 매출·주가는 아직 따라오지 않았다"
        return "관찰", "수주와 주가가 함께 올랐다 (주가 %+.0f%% vs 수주 %+.0f%%) — 상당 부분 반영" % (px, y)
    if y < 10:
        return "관찰", "잔고 증가가 10% 미만이라 선행 신호가 약하다"
    return "관찰", "수주는 늘었지만 매출 전환·주가 괴리 어느 쪽도 뚜렷하지 않다"


def questions(r, peers):
    """생각을 넓히는 질문. 숫자가 말해주지 않는 것을 다음에 확인하게 한다.
    peers 는 같은 업종에서 잔고를 믿을 수 있는 다른 회사들."""
    q = []
    y, btb, cov = r["backlog_yoy"], r["btb"], r["cover"]
    px, dd, mgn, acc = r["price_1y"], r.get("dd52"), r["margin_delta"], r["rev_accel"]
    if cov and cov >= 3 and px is not None and px < 0:
        q.append("연매출 %.1f년치 잔고가 있는데 주가는 1년 %+.0f%%. 시장은 무엇을 의심하나 — "
                 "수주 취소, 저가 수주에 따른 마진, 인도 지연, 운전자본·자금 조달?" % (cov, px))
    if btb and btb >= 2 and (acc is None or acc <= 0):
        q.append("수주가 매출보다 %.1f배 빨리 쌓인다. 매출은 언제부터 붙나 — 공정률·인도 일정, "
                 "그리고 생산능력(CAPA) 증설 공시가 뒤따르는지" % btb)
    if y is not None and y >= 30 and mgn is not None and mgn < 0:
        q.append("잔고는 %+.0f%% 늘었는데 영업이익률은 %+.1f%%p. 물량을 싸게 받은 것인가, "
                 "원가가 오른 것인가 — 수주 단가와 원재료 가격 추이" % (y, mgn))
    if dd is not None and dd <= -30 and y is not None and y >= 20:
        q.append("주가는 52주 고점 대비 %.0f%%인데 잔고는 %+.0f%%. 빠진 이유가 업황인가 "
                 "이 회사만의 문제인가 — 최근 악재 공시와 같은 업종 주가를 같이 볼 것" % (dd, y))
    if (not r["per"] or r["per"] <= 0) and y is not None and y >= 20:
        q.append("적자인데 잔고는 쌓인다. 잔고 × 목표 이익률로 흑자 전환 시점을 역산해 보자")
    for c in r.get("parties_listed", [])[:2]:
        q.append("거래상대 %s 은(는) 왜 발주를 늘리나? 그 회사의 설비투자·수주 사이클을 따라가면 "
                 "다음 수혜처가 보인다" % c["name"])
    for c in r.get("customer_of", [])[:1]:
        q.append("%s 이(가) 이 회사에 %s 규모를 발주했다. 발주가 느는 쪽은 투자를 늘리는 쪽이다 — "
                 "이 회사 자체의 수요 전망은?" % (c["supplier"], c["amount_txt"]))
    if r["same_as"]:
        q.append("같은 잔고를 %s 도 적는다. 지주사와 자회사 중 어느 쪽이 더 싸게 사는 길인가 — "
                 "지분율과 지주 할인율" % ", ".join(r["same_as"]))
    if peers:
        up = [p for p in peers if (p["backlog_yoy"] or 0) >= 15]
        if len(up) >= 2:
            names = ", ".join(p["name"] for p in up[:3])
            q.append("같은 업종 %s 도 잔고가 늘고 있다. 업종 전체의 사이클인가, 이 회사만의 이야기인가 — "
                     "업종 안에서 반영 갭이 가장 큰 곳은?" % names)
        elif r["backlog_yoy"] and r["backlog_yoy"] >= 20 and not up:
            q.append("같은 업종에서 잔고가 느는 곳이 이 회사뿐이다. 점유율을 빼앗는 것인가, "
                     "특정 고객 한 곳에 기대는 것인가")
    if r["stage"] == "반영":
        q.append("주가가 먼저 갔다. 다음 분기 잔고 증가율이 꺾이면 무엇이 남나 — 컨센서스가 이미 "
                 "무엇을 가정하는지")
    return q[:5]


def reasons(r):
    """사람이 읽는 근거 문장들."""
    out = []
    won = lambda v: ("%.1f조" % (v / 1e12)) if abs(v) >= 1e12 else ("%.0f억" % (v / 1e8))
    if r["backlog_yoy"] is not None:
        s = "수주잔고 1년 새 %+.0f%% (%s" % (r["backlog_yoy"], won(r["backlog"]))
        if r["cover"]:
            s += ", 연매출의 %.1f년치" % r["cover"]
        out.append(s + ")")
    if r["btb"] is not None:
        out.append("북투빌 %.2f — 1년간 들어온 수주가 매출로 나간 것의 %.2f배%s"
                   % (r["btb"], r["btb"], " (잔고가 쌓이는 중)" if r["btb"] > 1 else " (잔고 소진 중)"))
    if r["rev_accel"] is not None:
        s = "매출 증가율 %+.1f%% (직전 분기보다 %+.1f%%p)" % (r["rev_yoy"] or 0, r["rev_accel"])
        if r["margin_delta"] is not None:
            s += ", 영업이익률 %+.1f%%p" % r["margin_delta"]
        out.append(s)
    if r["new_contracts"]:
        tot = sum(c.get("amount") or 0 for c in r["new_contracts"])
        out.append("마지막 정기보고서 이후 수주 공시 %d건, %s%s"
                   % (len(r["new_contracts"]), won(tot),
                      (" — 연매출의 %.0f%%" % r["new_pct"]) if r["new_pct"] else ""))
    if r["price_1y"] is not None and r["backlog_yoy"] is not None:
        out.append("주가 1년 %+.0f%% vs 수주잔고 %+.0f%% → 반영 갭 %+.0f%%p%s"
                   % (r["price_1y"], r["backlog_yoy"], r["gap"],
                      " (잔고 증가율은 300%로 잘라 계산)" if r["backlog_yoy"] > 300 else ""))
    if r["per"]:
        out.append("PER(최근 4분기) %.1f배" % r["per"] if r["per"] > 0 else "최근 4분기 적자")
    for f in r["flags"]:
        out.append("주의: " + f)
    if r["same_as"]:
        out.append("같은 잔고를 적은 회사: %s (지주·자회사 중복)" % ", ".join(r["same_as"]))
    return out
