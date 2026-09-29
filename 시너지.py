# -*- coding: utf-8 -*-
"""
시너지 발굴 — 수주가 실적과 주가로 넘어가는 길목을 잡는다.

따로 놓고 보면 흔한 신호 넷을 한 줄에 세운다.

  선행   수주잔고가 1년 새 얼마나 늘었나, 매출로 빠져나가는 속도보다 빨리 쌓이나(북투빌)
  전환   쌓인 수주가 매출 가속·이익률 개선으로 넘어오기 시작했나
  확인   마지막 정기보고서 이후 새로 공시된 수주 계약(단일판매·공급계약)이 있나
  가격   주가가 1년 동안 수주 증가만큼 올랐나 — 덜 올랐으면 '반영 갭'

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


def score(rows):
    """rows 는 build_row 결과. 신뢰할 수 있는 행끼리 백분위를 매긴다."""
    ok = [r for r in rows if r["reliable"]]
    R = {
        "yoy": _pct_rank([r["backlog_yoy"] for r in ok]),
        "btb": _pct_rank([r["btb"] for r in ok]),
        "acc": _pct_rank([r["rev_accel"] for r in ok]),
        "mgn": _pct_rank([r["margin_delta"] for r in ok]),
        "new": _pct_rank([r["new_pct"] for r in ok]),
        "gap": _pct_rank([r["gap"] for r in ok]),
        # PER 은 낮을수록 좋다. 적자(음수)는 순위에서 뺀다.
        "per": _pct_rank([-r["per"] if r["per"] and r["per"] > 0 else None for r in ok]),
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
        parts = {
            "선행": blend([(R["yoy"](r["backlog_yoy"]), 0.6), (R["btb"](r["btb"]), 0.4)]),
            "전환": blend([(R["acc"](r["rev_accel"]), 0.6), (R["mgn"](r["margin_delta"]), 0.4)]),
            # 최근 계약 공시가 없으면 0점이 아니라 '해당 없음'으로 두면 없는 회사가
            # 오히려 유리해진다. 없으면 0 으로 센다.
            "확인": R["new"](r["new_pct"]) if r["new_pct"] else 0.0,
            "가격": blend([(R["gap"](r["gap"]), 0.6),
                         (R["per"](-r["per"]) if r["per"] and r["per"] > 0 else None, 0.4)]),
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
