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
