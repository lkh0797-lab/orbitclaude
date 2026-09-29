# -*- coding: utf-8 -*-
"""
변곡점 — 회사의 정체성·수익 모델·방향이 꺾인 자리를 모은다.

보고서를 분기마다 읽는 투자자가 실제로 짚는 곳을 규칙으로 옮겼다.

  숫자(연간·분기 원장)
    PSR·PRR·일시적 부진(글리치)       켄 피셔
    FCF 전환율·ROIC·주주환원         워런 버핏
    매출 가속·Capex 변곡·재고 주기    스탠리 드러켄밀러
    ROE 지속성·유보이익 1원 테스트    워런 버핏
    기업 유형·PEG                     피터 린치
    이익의 질·위험 신호(뒤집어 보기)   찰리 멍거
  문장(사업보고서 「사업의 내용」)
    사업 정의가 바뀐 해, 새로 들어온 말·사라진 말

모든 판단은 원장 숫자와 원문에서 나온다. 근거를 같이 돌려준다.
"""
import re
import math
import difflib
from collections import Counter

VERSION = 7


# ---------------------------------------------------------------- 연간 재무
CAPEX_TAG = ("PurchaseOfPropertyPlantAndEquipment", "PurchaseOfIntangibleAssets",
             "AcquisitionOfPropertyPlantAndEquipment", "AcquisitionOfIntangibleAssets")
CAPEX_NM = re.compile(r"^(?:유형자산|무형자산)(?:의)?(?:취득|증가|구입|매입)$")
BUYBACK_TAG = ("PaymentsToAcquireOrRedeemEntitysShares", "AcquisitionOfTreasuryShares")
BUYBACK_NM = re.compile(r"^자기주식(?:의)?(?:취득|매입)$")
DIV_TAG = ("DividendsPaid",)
DIV_NM = re.compile(r"^(?:현금)?배당금(?:의)?지급$")
DEBT_NM = re.compile(r"^(?:단기차입금|장기차입금|차입금|사채|유동성장기부채|유동성장기차입금|유동성사채|"
                     r"장기사채|단기사채|유동성장기사채)$")
CASH_NM = re.compile(r"^현금및현금성자산$")
INV_NM = re.compile(r"^재고자산$")
AR_NM = re.compile(r"^매출채권(?:및기타(?:유동)?채권)?$")


def _year_rows(FIN, corp, y):
    st = FIN.fetch_statement(corp, y, "11011")
    rows = st.get("list") or []
    if not rows:
        rows = FIN.fetch_statement(corp, y, "11011", "OFS").get("list") or []
    return rows


def _key(FIN, r):
    nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
    return FIN._row_key(r.get("account_id"), nm).split("|")[0], FIN._merge_name(nm)


def fundamentals(FIN, corp, years):
    out = []
    for y in years:
        try:
            rows = _year_rows(FIN, corp, y)
        except Exception:
            rows = []
        if not rows:
            continue
        a = FIN.pick_accounts(rows)
        d = {"year": y, "rev": a.get("매출액"), "op": a.get("영업이익"), "ni": a.get("당기순이익"),
             "eq": a.get("자본총계"), "liab": a.get("부채총계"), "assets": a.get("자산총계"),
             "re": a.get("이익잉여금"), "cap": a.get("자본금"), "eps": a.get("EPS")}
        cfo = capex = bb = div = debt = cash = inv = ar = tax = pbt = None
        seen_debt = set()
        for r in rows:
            sj = r.get("sj_div")
            v = FIN.num(r.get("thstrm_amount"))
            if v is None:
                continue
            k, mn = _key(FIN, r)
            tail = k[2:] if k.startswith("t:") else ""
            if sj == "CF":
                if k == "t:CashFlowsFromUsedInOperatingActivities" and cfo is None:
                    cfo = v
                elif (any(tail.startswith(t) for t in CAPEX_TAG) or CAPEX_NM.match(mn)) and "처분" not in mn:
                    capex = (capex or 0) + abs(v)
                elif any(tail.startswith(t) for t in BUYBACK_TAG) or BUYBACK_NM.match(mn):
                    bb = (bb or 0) + abs(v)
                elif (any(tail.startswith(t) for t in DIV_TAG) or DIV_NM.match(mn)) and "수취" not in mn:
                    div = (div or 0) + abs(v)
            elif sj == "BS":
                if DEBT_NM.match(mn) and (mn, v) not in seen_debt:
                    seen_debt.add((mn, v))
                    debt = (debt or 0) + abs(v)
                elif (k == "t:CashAndCashEquivalents" or CASH_NM.match(mn)) and cash is None:
                    cash = v
                elif (k == "t:Inventories" or INV_NM.match(mn)) and inv is None:
                    inv = v
                elif (tail.startswith("TradeAndOtherCurrentReceivables") or AR_NM.match(mn)) and ar is None:
                    ar = v
            elif sj in ("IS", "CIS"):
                if k == "t:IncomeTaxExpenseContinuingOperations" and tax is None:
                    tax = v
                elif k == "t:ProfitLossBeforeTax" and pbt is None:
                    pbt = v
        d.update(cfo=cfo, capex=capex, buyback=bb, div=div, debt=debt, cash=cash, inv=inv, ar=ar,
                 tax=tax, pbt=pbt)
        out.append(d)
    # 파생 — 전년 값이 필요한 것은 한 번 더 돈다
    prev = None
    for d in out:
        rev, op, ni, eq = d["rev"], d["op"], d["ni"], d["eq"]
        d["margin"] = op / rev * 100 if (rev and op is not None and rev > 0) else None
        d["fcf"] = (d["cfo"] - (d["capex"] or 0)) if d["cfo"] is not None else None
        d["fcf_conv"] = d["fcf"] / ni * 100 if (d["fcf"] is not None and ni and ni > 0) else None
        t = d["tax"] / d["pbt"] if (d["tax"] is not None and d["pbt"] and d["pbt"] > 0) else 0.22
        t = min(max(t, 0.0), 0.4)
        ic = (eq + (d["debt"] or 0) - (d["cash"] or 0)) if eq else None
        d["ic"] = ic
        ic_avg = (ic + prev["ic"]) / 2 if (ic and prev and prev.get("ic")) else ic
        d["roic"] = op * (1 - t) / ic_avg * 100 if (op is not None and ic_avg and ic_avg > 0) else None
        eq_avg = (eq + prev["eq"]) / 2 if (eq and prev and prev.get("eq")) else eq
        d["roe"] = ni / eq_avg * 100 if (ni is not None and eq_avg and eq_avg > 0) else None
        d["capex_int"] = d["capex"] / rev * 100 if (d["capex"] is not None and rev and rev > 0) else None
        d["de"] = d["debt"] / eq * 100 if (d["debt"] is not None and eq and eq > 0) else None
        d["liab_eq"] = d["liab"] / eq * 100 if (d["liab"] is not None and eq and eq > 0) else None
        ret = (d["div"] or 0) + (d["buyback"] or 0)
        d["payout"] = ret
        d["payout_fcf"] = ret / d["fcf"] * 100 if (d["fcf"] and d["fcf"] > 0) else None
        d["inv_days"] = d["inv"] / rev * 365 if (d["inv"] is not None and rev and rev > 0) else None
        d["ar_days"] = d["ar"] / rev * 365 if (d["ar"] is not None and rev and rev > 0) else None
        d["rev_yoy"] = (rev / prev["rev"] - 1) * 100 if (prev and rev and prev.get("rev") and prev["rev"] > 0) else None
        d["cfo_ni"] = d["cfo"] / ni if (d["cfo"] is not None and ni and ni > 0) else None
        prev = d
    return out


# ---------------------------------------------------------------- 문장
STOP = set("""
당사 회사 사업 연결 종속 종속회사 종속기업 기업 부문 시장 제품 경우 관련 주요 대한 위한 통한 따른 등의 기준 현재
전년 당기 전기 당분기 매출 매출액 영업 이익 비용 기타 합계 단위 백만원 천원 억원 사업보고서 보고서 내용 현황 개요
구분 항목 비율 수준 규모 증가 감소 확대 강화 지속 계획 예정 가능 필요 이상 이하 최근 향후 주식회사 해당 다음 아래
통해 따라 또한 이러한 그리고 모든 다양한 새로운 국내 해외 세계 고객 서비스 기술 개발 생산 판매 제조 공급 사용
업체 업계 산업 분야 사업부 영역 부분 제공 확보 운영 추진 진행 위해 대해 있는 있으며 있습니다 합니다 됩니다 입니다
하고 하여 하며 되어 되는 있고 없는 같은 대부분 주로 기간 연도 년도 분기 반기 기말 기초 원재료 가격 변동 영향
참고 바랍니다 상기 하기 아래와 다음과 같습니다 등을 등이 등은 등에 대하여 관하여 의하여 인하여 경우에 경쟁
관한 목적 의무 계약 매도 매수 지분 자가 향상 사양 발전 사람 개입 이후 이전 당시 동안 기존 신규 전체 일부 각각
내역 금액 수량 수익 손익 자산 부채 자본 비중 점유율 추이 전망 효과 결과 방법 방식 부문별 지역 법인 본사 공장 백만 천만 기초금액 기말금액 소재지 국가 보호 핵심 대형 분할
포함 하는 경향 대비 기반 중심 측면 수행 활용 적용 대응 관리 구축 보유 형태 구조 특성 요인 니다 영위
""".split())
# 표에만 나오는 통화 기호 — 들어온 말로 잡히면 잡음이다
FX = set("USD EUR JPY CNY RMB GBP PLN HKD SGD VND INR BRL MXN CAD AUD CHF TWD THB IDR MYR KRW".split())
# 부사·관형형 어미로 끝나는 말(빠르게, 특히, 보유한, 강화해)은 명사가 아니다
NOT_NOUN = re.compile(r"(?:게|히|한|해|된|될|할|적인|하게|으며|하는|되어|하여|이며|니다|습니|하고|나가고)$|및|백만|천만")
JOSA = sorted("""으로서 으로써 에서는 에서도 에게서 으로는 으로도 이라는 이라고 에서의 으로의 에서 에게 으로 까지 부터
보다 처럼 이며 이고 이나 라는 라고 하는 하여 하고 하며 되는 되어 에는 에도 과의 와의 의 를 을 은 는 이 가 와 과 에 로 도 만""".split(),
              key=len, reverse=True)
TOK = re.compile(r"[A-Za-z][A-Za-z0-9\-\+&]{1,20}|[가-힣]{2,14}")


def _norm_tok(t):
    if re.match(r"[A-Za-z]", t):
        # 영문은 약어(AI, HBM, EUV, SMR)만 센다. 소문자 낱말은 인용·출처(techinsights)가 많다.
        return t if re.fullmatch(r"[A-Z][A-Z0-9&\+\-]{1,7}", t) and t not in FX else None
    for j in JOSA:
        if t.endswith(j) and len(t) - len(j) >= 2:
            t = t[:-len(j)]
            break
    if len(t) >= 3 and NOT_NOUN.search(t):
        return None
    return t


def tokens(text):
    out = []
    for t in TOK.findall(text):
        n = _norm_tok(t)
        if not n or n in STOP or len(n) < 2 or n.isdigit():
            continue
        out.append(n)
    return out


OVERVIEW_START = re.compile(r"(?m)^\s*(?:1\s*\.|가\s*\.)\s*(?:사업의\s*개요|업계의\s*현황|산업의\s*특성|회사의\s*현황)")
OVERVIEW_END = re.compile(r"(?m)^\s*(?:2\s*\.|나\s*\.)\s*\S")


def overview(text):
    """「사업의 내용」 첫 소절(사업의 개요)의 앞부분. 회사가 스스로를 뭐라고 정의하는지."""
    m = OVERVIEW_START.search(text)
    body = text[m.end():] if m else text
    e = OVERVIEW_END.search(body)
    if e and e.start() > 200:
        body = body[:e.start()]
    body = re.sub(r"\s+", " ", body).strip()
    # 표 숫자가 섞인 줄은 버리고 문장만
    sents = [s.strip() for s in re.split(r"(?<=[다요\.])\s+", body) if len(s.strip()) > 25
             and len(re.findall(r"\d", s)) < len(s) * 0.25]
    # 회사가 자기를 정의하는 문장부터 — '당사는 … 사업을 영위' 같은 문장. 앞에 영업이익 주석이나
    # 산업 일반론이 먼저 나오는 보고서가 있다(한화에어로스페이스 2025).
    SELF = re.compile(r"(?:당사|회사|연결실체|연결회사)(?:와\s*\S+)?(?:는|은|가|의)")
    WHAT = re.compile(r"영위|주된\s*사업|주요\s*사업|사업부문|사업을|제조|생산|판매|서비스|개발")
    k = next((i for i, s in enumerate(sents[:25]) if SELF.search(s) and WHAT.search(s)), 0)
    txt = " ".join(sents[k:k + 4])
    return txt[:700]


RND_LINE = re.compile(r"연구\s*개발\s*비\s*(?:용)?\s*/\s*매출액\s*비율")
RND_PCT = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2})?)\s*%")


def rnd_ratio(text):
    """「연구개발비 / 매출액 비율」 표의 당기 값(%). 표 단위가 회사마다 달라(백만원·천원) 금액 대신 비율을 읽고
    매출액을 곱해 쓴다. 비율이 별도 기준인 회사도 있어 근삿값이다. 없으면 None."""
    m = RND_LINE.search(text or "")
    if not m:
        return None
    p = RND_PCT.search(text[m.end():m.end() + 300])
    if not p:
        return None
    v = float(p.group(1))
    return v if 0 < v < 60 else None


def text_features(docs):
    """docs = [(year, stamp, rcept, text)] 오름차순. 연도별 개요와 낱말 수, 연구개발비 비율."""
    feats = []
    for y, stamp, rcept, text in docs:
        body = text[:150000]
        toks = tokens(body)
        feats.append({"year": y, "stamp": stamp, "rcept": rcept, "overview": overview(text),
                      "counts": Counter(toks), "n": max(len(toks), 1), "rnd_pct": rnd_ratio(text)})
    return feats


def term_shifts(feats, top=10):
    """들어온 말 / 나간 말. 최근 2개 보고서와 4~6년 전 보고서를 견준다."""
    if len(feats) < 4:
        return [], []
    recent = feats[-2:]
    base = feats[max(0, len(feats) - 7):max(1, len(feats) - 4)] or feats[:1]
    rc = Counter()
    for f in recent:
        rc.update(f["counts"])
    bc = Counter()
    for f in base:
        bc.update(f["counts"])
    rn = sum(f["n"] for f in recent)
    bn = sum(f["n"] for f in base)
    ys = [f["year"] for f in feats]

    def series(t):
        return [f["counts"].get(t, 0) for f in feats]

    came, gone = [], []
    for t, c in rc.items():
        per = c / len(recent)
        b = bc.get(t, 0) / max(len(base), 1)
        if per >= 4 and b <= 1 and (c / rn) >= 3 * ((bc.get(t, 0) + 0.5) / bn):
            s = series(t)
            # 비교 기준 구간 뒤에 다시(또는 처음) 본격 등장한 해. 옛날에 잠깐 쓰였다 사라진 말이
            # 돌아온 경우 '처음'이 10년 전으로 찍히지 않게.
            start = ys.index(base[-1]["year"]) + 1 if base else 0
            first = next((ys[i] for i in range(start, len(s)) if s[i] >= 2), None)
            came.append({"term": t, "recent": round(per, 1), "base": round(b, 1), "first": first,
                         "series": s})
    for t, c in bc.items():
        per = c / max(len(base), 1)
        now = rc.get(t, 0) / len(recent)
        if per >= 4 and now <= 0.5:
            s = series(t)
            last = next((ys[i] for i in range(len(s) - 1, -1, -1) if s[i] >= 2), None)
            gone.append({"term": t, "recent": round(now, 1), "base": round(per, 1), "last": last,
                         "series": s})
    came.sort(key=lambda x: -x["recent"])
    gone.sort(key=lambda x: -x["base"])
    return came[:top], gone[:top]


def _words(txt):
    return set(tokens(txt))


# ---------------------------------------------------------------- 변곡점
def _avg(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def _pct(v, d=0):
    return "—" if v is None else ("%+." + str(d) + "f%%") % v


def _won(v):
    if v is None:
        return "—"
    a = abs(v)
    s = ("%.1f조" % (a / 1e12)) if a >= 1e12 else ("%.0f억" % (a / 1e8))
    return ("-" if v < 0 else "") + s


def events(funds, quarters, feats, came, gone, rcept_of):
    """변곡점 목록. lane: 정체성 / 수익모델 / 방향·투자 / 재무·주주 / 경고"""
    ev = []

    def add(year, lane, guru, tone, title, detail, stamp=None):
        rc = rcept_of.get(year)
        ev.append({"year": year, "stamp": stamp or ("%d-12" % year), "lane": lane, "guru": guru,
                   "tone": tone, "title": title, "detail": detail,
                   "rcept": rc[1] if rc else None, "prev_rcept": rc[0] if rc else None})

    F = {d["year"]: d for d in funds}
    ys = sorted(F)
    for i, y in enumerate(ys):
        d = F[y]
        p = F.get(y - 1)
        past = [F[k] for k in (y - 3, y - 2, y - 1) if k in F]
        # 성장 가속 / 급감
        if p and d["rev_yoy"] is not None and p.get("rev_yoy") is not None:
            if d["rev_yoy"] >= 15 and d["rev_yoy"] - p["rev_yoy"] >= 10 and p["rev_yoy"] < 10:
                add(y, "방향·투자", "드러켄밀러", "up", "매출 성장 가속",
                    "매출 증가율 %s → %s (%s)" % (_pct(p["rev_yoy"]), _pct(d["rev_yoy"]), _won(d["rev"])))
            elif d["rev_yoy"] <= 0 and p["rev_yoy"] >= 15:
                add(y, "방향·투자", "드러켄밀러", "down", "성장 급감",
                    "매출 증가율 %s → %s" % (_pct(p["rev_yoy"]), _pct(d["rev_yoy"])))
        # 수익성 레벨 이동
        pm = _avg([x.get("margin") for x in past])
        if d["margin"] is not None and pm is not None and len(past) >= 2:
            if d["margin"] - pm >= 4:
                add(y, "수익모델", "버핏·린치", "up", "영업이익률 한 단계 상승",
                    "직전 %d년 평균 %.1f%% → %.1f%%" % (len(past), pm, d["margin"]))
            elif d["margin"] - pm <= -4:
                add(y, "수익모델", "버핏·린치", "down", "영업이익률 한 단계 하락",
                    "직전 %d년 평균 %.1f%% → %.1f%%" % (len(past), pm, d["margin"]))
        # 흑자·적자 전환
        if p and p.get("ni") is not None and d["ni"] is not None:
            if p["ni"] < 0 < d["ni"]:
                add(y, "수익모델", "린치", "up", "흑자 전환", "당기순이익 %s → %s" % (_won(p["ni"]), _won(d["ni"])))
            elif p["ni"] > 0 > d["ni"]:
                add(y, "수익모델", "린치", "down", "적자 전환", "당기순이익 %s → %s" % (_won(p["ni"]), _won(d["ni"])))
        # ROIC 10% 교차
        if p and p.get("roic") is not None and d["roic"] is not None:
            if p["roic"] < 10 <= d["roic"]:
                add(y, "수익모델", "버핏", "up", "ROIC 10% 돌파",
                    "투하자본이익률 %.1f%% → %.1f%% — 자본비용을 넘기 시작" % (p["roic"], d["roic"]))
            elif p["roic"] >= 10 > d["roic"]:
                add(y, "수익모델", "버핏", "down", "ROIC 10% 이탈",
                    "투하자본이익률 %.1f%% → %.1f%%" % (p["roic"], d["roic"]))
        # FCF 전환
        f2 = [F[k].get("fcf") for k in (y - 2, y - 1) if k in F]
        if d["fcf"] is not None and len(f2) == 2 and None not in f2:
            if all(v < 0 for v in f2) and d["fcf"] > 0:
                add(y, "재무·주주", "버핏", "up", "잉여현금흐름 흑자 전환",
                    "FCF %s → %s (영업CF %s − 투자 %s)" % (_won(f2[-1]), _won(d["fcf"]), _won(d["cfo"]), _won(d["capex"])))
            elif all(v > 0 for v in f2) and d["fcf"] < 0:
                add(y, "재무·주주", "버핏", "down", "잉여현금흐름 적자 전환",
                    "FCF %s → %s — 투자 %s 가 영업CF %s 를 넘었다" % (_won(f2[-1]), _won(d["fcf"]), _won(d["capex"]), _won(d["cfo"])))
        # 투자 사이클
        pc = _avg([x.get("capex_int") for x in past])
        if d["capex_int"] is not None and pc is not None and d["capex_int"] >= 4 and \
                d["capex_int"] >= max(pc * 1.6, pc + 3):
            add(y, "방향·투자", "드러켄밀러", "up", "투자 사이클 진입",
                "매출 대비 설비투자 %.1f%% → %.1f%% (%s)" % (pc, d["capex_int"], _won(d["capex"])))
        # 이익의 질
        if p and d["cfo_ni"] is not None and p.get("cfo_ni") is not None and d["cfo_ni"] < 0.5 and p["cfo_ni"] < 0.5:
            add(y, "경고", "멍거", "warn", "이익이 현금으로 안 들어온다",
                "2년 연속 영업CF가 순이익의 절반 미만 (%.2f배, %.2f배)" % (p["cfo_ni"], d["cfo_ni"]))
        # 차입 확대
        if p and d["de"] is not None and p.get("de") is not None and d["de"] - p["de"] >= 50:
            add(y, "경고", "멍거", "warn", "차입 급증",
                "차입금/자본 %.0f%% → %.0f%%" % (p["de"], d["de"]))
        # 주주환원
        pr = _avg([x.get("payout") for x in past])
        if d["payout"] and d["ni"] and d["ni"] > 0 and d["payout"] >= 0.2 * d["ni"] and \
                (pr is None or pr == 0 or d["payout"] >= 2 * pr):
            add(y, "재무·주주", "버핏", "up", "주주환원 강화",
                "배당+자사주 %s (순이익의 %.0f%%)" % (_won(d["payout"]), d["payout"] / d["ni"] * 100))
        if d.get("buyback") and all(not F[k].get("buyback") for k in (y - 3, y - 2, y - 1) if k in F) and past:
            add(y, "재무·주주", "버핏", "up", "자사주 매입 시작", "자기주식 취득 %s" % _won(d["buyback"]))
        # 켄 피셔 — PSR 구간 진입, 일시적 부진(글리치)
        if p and d.get("psr") is not None and p.get("psr") is not None:
            if d["psr"] <= 0.75 < p["psr"]:
                add(y, "재무·주주", "피셔", "up", "PSR 0.75배 아래로",
                    "시가총액이 매출의 %.2f배 (전년 %.2f배) — 피셔가 '슈퍼 스톡'을 찾던 구간" % (d["psr"], p["psr"]))
            elif d["psr"] >= 3 > p["psr"]:
                add(y, "경고", "피셔", "warn", "PSR 3배 돌파",
                    "시가총액이 매출의 %.1f배 (전년 %.1f배) — 피셔는 3배 넘는 주식은 사지 말라고 했다" % (d["psr"], p["psr"]))
        nm_past = [x["ni"] / x["rev"] * 100 for x in past if x.get("ni") is not None and x.get("rev")]
        if d.get("rev_yoy") is not None and d["rev_yoy"] >= 5 and d.get("ni") is not None and d.get("rev")                 and len(nm_past) >= 2 and _avg(nm_past) >= 5 and d["ni"] / d["rev"] * 100 < _avg(nm_past) * 0.5:
            add(y, "수익모델", "피셔", "shift", "일시적 부진(글리치)?",
                "매출은 %s 늘었는데 순이익률 %.1f%% — 직전 평균 %.1f%%의 절반 아래. 피셔는 이런 '글리치'에서 PSR이 낮으면 샀다" % (
                    _pct(d["rev_yoy"]), d["ni"] / d["rev"] * 100, _avg(nm_past)))

    # 분기 — 최근 8개 분기의 가속 전환(드러켄밀러)
    qs = [q for q in quarters if q.get("매출가속") is not None][-8:]
    for a, b in zip(qs, qs[1:]):
        if a["매출가속"] <= 0 < b["매출가속"] and (b.get("매출YoY") or 0) > 0:
            y = b.get("year")
            ev.append({"year": y, "stamp": "%s-%02d" % (y, b.get("q", 4) * 3), "lane": "방향·투자",
                       "guru": "드러켄밀러", "tone": "up", "title": "분기 매출 가속 전환 (%s)" % b.get("label", ""),
                       "detail": "매출 증가율 %s, 가속 %+.1f%%p (직전 분기 %+.1f%%p)" % (
                           _pct(b.get("매출YoY")), b["매출가속"], a["매출가속"]),
                       "rcept": b.get("rcept"), "prev_rcept": a.get("rcept")})
    # 문장 — 사업 정의가 바뀐 해. 글자 배열이 아니라 '쓴 낱말'이 바뀌었는지 본다
    # (문단 순서·서식만 바뀐 해를 걸러낸다). 가장 크게 바뀐 3개 해만.
    shifts = []
    for a, b in zip(feats, feats[1:]):
        if not a["overview"] or not b["overview"]:
            continue
        wa, wb = _words(a["overview"]), _words(b["overview"])
        if len(wa) < 8 or len(wb) < 8:
            continue
        jac = len(wa & wb) / len(wa | wb)
        new = [w for w in tokens(b["overview"]) if w not in wa]
        old = [w for w in tokens(a["overview"]) if w not in wb]
        nw = [w for w, _ in Counter(new).most_common(6)]
        ow = [w for w, _ in Counter(old).most_common(4)]
        if jac < 0.3 and len(set(new)) >= 4:
            shifts.append((jac, a, b, nw, ow))
    for jac, a, b, nw, ow in sorted(shifts, key=lambda x: x[0])[:3]:
        ev.append({"year": b["year"], "stamp": b["stamp"], "lane": "정체성", "guru": "린치·피셔",
                   "tone": "shift", "title": "사업 정의가 바뀌었다",
                   "detail": "사업 개요에서 같은 낱말 %.0f%%. 새로 쓴 말: %s%s" % (
                       jac * 100, ", ".join(nw) or "—", (" · 뺀 말: " + ", ".join(ow)) if ow else ""),
                   "rcept": b["rcept"], "prev_rcept": a["rcept"]})
    # 들어온 말이 본격 등장한 해
    by_year = {f["year"]: f for f in feats}
    prev_of = {b["year"]: a for a, b in zip(feats, feats[1:])}
    for c in came[:5]:
        y = c["first"]
        if y and y in by_year and y != feats[0]["year"]:
            ev.append({"year": y, "stamp": by_year[y]["stamp"], "lane": "정체성", "guru": "피셔",
                       "tone": "shift", "title": "새 말 등장: ‘%s’" % c["term"],
                       "detail": "이 해 처음 2회 넘게 쓰였고, 최근엔 보고서당 %.0f회" % c["recent"],
                       "rcept": by_year[y]["rcept"], "prev_rcept": prev_of[y]["rcept"] if y in prev_of else None})
    ev.sort(key=lambda e: (e["stamp"] or ""), reverse=True)
    return ev


# ---------------------------------------------------------------- 구루 렌즈
def _grade(ok, total):
    r = ok / total if total else 0
    return "강함" if r >= 0.75 else "보통" if r >= 0.45 else "약함"


def lenses(funds, quarters, price_info):
    F = [d for d in funds if d.get("rev") is not None or d.get("ni") is not None]
    last5 = F[-5:]
    L = []

    def ser(k, n=10):
        return [{"y": d["year"], "v": d.get(k)} for d in F[-n:]]

    # 켄 피셔 — 매출 대비 값(PSR), 연구개발 대비 값(PRR), 일시적 부진(글리치)
    pn = price_info.get("psr_now") or {}
    # 자기 역사 대비 — 우리 데이터에선 절대 기준(0.75·3배)보다 이쪽이 이후 수익률을 설명했다(도구/반영속도_검증.py)
    ph = [d["psr"] for d in F if d.get("psr")]
    psr_pct = (sum(1 for v in ph if v <= pn["psr"]) / len(ph) * 100) if (pn.get("psr") and len(ph) >= 4) else None
    rn = price_info.get("prr_now") or {}
    psr = pn.get("psr")
    prr = rn.get("prr")
    g5 = _cagr(F, "rev", 5) if _cagr(F, "rev", 5) is not None else _cagr(F, "rev", 3)
    nm = [d["ni"] / d["rev"] * 100 for d in last5 if d.get("ni") is not None and d.get("rev")]
    glitch = _fisher_glitch(F)
    good = (1 if psr is not None and psr <= 1.5 else 0) + (1 if prr is not None and prr <= 15 else 0) +            (1 if g5 is not None and g5 >= 15 else 0) + (1 if nm and _avg(nm) >= 5 else 0)
    L.append({
        "guru": "켄 피셔", "en": "Ken Fisher", "tag": _fisher_tag(psr),
        "clock": {"speed": "slow", "h": "6–12개월", "key": "psr_pct",
                  "how": "절대 기준(0.75·3배)보다 자기 역사 안의 위치로 읽는다 — 자기 역사에서 비쌀 때 이후 6–12개월이 약했다."},
        "idea": "이익은 흔들려도 매출은 덜 흔들린다. 시가총액을 매출(PSR)과 연구개발비(PRR)에 견주고, "
                "좋은 회사가 잠깐 이익이 꺾인 '글리치'에서 싸게 산다.",
        "metrics": [
            {"k": "PSR 자기 역사 위치", "v": None if psr_pct is None else ("역대 최고" if psr_pct >= 100 else "역대 최저" if psr_pct <= 100 / max(len(ph), 1) else "상위 %.0f%%" % (100 - psr_pct) if psr_pct >= 50 else "하위 %.0f%%" % psr_pct),
             "note": "연말 PSR %d년치 가운데 · 느리게 반영되는 값 신호" % len(ph) if ph else "", "series": []},
            {"k": "PSR 지금", "v": None if psr is None else "%.2f배" % psr,
             "note": "시총 ÷ 최근 4분기 매출 · 0.75↓ 싸다, 3↑ 과열", "series": ser("psr")},
            {"k": "PRR", "v": None if prr is None else "%.1f배" % prr,
             "note": ("시총 ÷ %d년 연구개발비 · 15↓ 싸다" % rn["year"]) if rn else "연구개발비 비율을 못 읽었다",
             "series": ser("prr")},
            {"k": "매출 %s년 연평균" % (5 if _cagr(F, "rev", 5) is not None else 3),
             "v": None if g5 is None else "%+.1f%%" % g5, "note": "슈퍼 컴퍼니 기준 15%↑", "series": ser("rev")},
            {"k": "순이익률 5년 평균", "v": None if not nm else "%.1f%%" % _avg(nm),
             "note": "장기 5%%↑ 가 슈퍼 컴퍼니 · 최근 %s" % ("글리치" if glitch else "정상"),
             "series": [{"y": d["year"], "v": (d["ni"] / d["rev"] * 100) if (d.get("ni") is not None and d.get("rev")) else None}
                        for d in F[-10:]]},
        ],
        "grade": _grade(good, 4),
        "verdict": ("자기 역사로 보면 PSR 이 %s — %s. " % (
            "역대 최고" if psr_pct >= 100 else ("상위 %.0f%%" % (100 - psr_pct)) if psr_pct >= 50 else ("하위 %.0f%%" % psr_pct),
            "비싼 쪽이다" if psr_pct >= 80 else "싼 쪽이다" if psr_pct <= 30 else "가운데쯤이다") if psr_pct is not None else "") +
            _fisher_verdict(psr, prr, g5, nm, glitch, pn),
        "q": "남들이 틀리게 믿고 있는 것은 무엇인가? — 그리고 내 뇌는 지금 나를 속이고 있지 않은가?",
    })

    # 드러켄밀러 — 변화율의 변화
    qs = [q for q in quarters if q.get("매출YoY") is not None][-8:]
    last = qs[-1] if qs else {}
    acc = [q.get("매출가속") for q in qs if q.get("매출가속") is not None]
    capi = [d["capex_int"] for d in F[-4:] if d.get("capex_int") is not None]
    invd = [q.get("재고일수") for q in qs if q.get("재고일수") is not None]
    good = (1 if last.get("매출가속") and last["매출가속"] > 0 else 0) + \
           (1 if last.get("이익률변화") and last["이익률변화"] > 0 else 0) + \
           (1 if len(invd) >= 2 and invd[-1] <= invd[0] else 0)
    L.append({
        "guru": "스탠리 드러켄밀러", "en": "Stanley Druckenmiller", "tag": "변곡점",
        "clock": {"speed": "fast", "h": "공시 전", "key": "rev_yoy",
                  "how": "실적 가속은 잠정실적·업황 뉴스로 보고서보다 먼저 값에 든다. 보고서로는 늦다 — 주가 흐름과 같은 방향일 때 추세 확인용으로만."},
        "idea": "숫자의 수준보다 변화의 방향. 18~24개월 뒤 컨센서스를 앞지를 실적 가속, 설비투자 변곡, 재고 주기.",
        "metrics": [
            {"k": "최근 분기 매출", "v": None if last.get("매출YoY") is None else _pct(last["매출YoY"], 1),
             "note": last.get("label", ""), "series": [{"y": q.get("label"), "v": q.get("매출YoY")} for q in qs]},
            {"k": "매출 가속", "v": None if last.get("매출가속") is None else "%+.1f%%p" % last["매출가속"],
             "note": "전년 동기 증가율의 변화", "series": [{"y": q.get("label"), "v": q.get("매출가속")} for q in qs]},
            {"k": "설비투자 강도", "v": None if not capi else "%.1f%%" % capi[-1], "note": "CAPEX ÷ 매출(연간)",
             "series": ser("capex_int")},
            {"k": "재고일수", "v": None if not invd else "%.0f일" % invd[-1],
             "note": "8분기 전 %.0f일" % invd[0] if len(invd) >= 2 else "",
             "series": [{"y": q.get("label"), "v": q.get("재고일수")} for q in qs]},
        ],
        "grade": _grade(good, 3),
        "verdict": _druck_verdict(last, invd),
        "q": "매크로 사이클과 산업 패러다임(AI·전력·방산 등)의 최대 수혜 기업인가?",
    })

    # 버핏 — 오래가는 경제성
    roes = [d["roe"] for d in F[-10:] if d.get("roe") is not None]
    mg = [d["margin"] for d in F[-10:] if d.get("margin") is not None]
    cv = (_std(mg) / abs(_avg(mg))) if (len(mg) >= 3 and _avg(mg)) else None
    test = price_info.get("retained_test")
    good = (1 if roes and _avg(roes) >= 12 else 0) + (1 if roes and min(roes) > 5 else 0) + \
           (1 if cv is not None and cv < 0.35 else 0) + (1 if test and test.get("ratio", 0) >= 1 else 0)
    L.append({
        "guru": "워런 버핏", "en": "Warren Buffett", "tag": "해자",
        "clock": {"speed": "cross", "h": "3–12개월 · 종목 비교", "key": "roe",
                  "how": "같은 해 다른 회사보다 ROE 가 높은 회사가 이후 더 올랐다. 종목을 고를 때 쓰고, 같은 회사의 이익률이 역대 정점이면 오히려 경계."},
        "idea": "10년 뒤에도 가격을 올려도 고객이 남는가. 높은 ROE가 흔들림 없이 이어지고, 남긴 1원이 시장가치 1원 이상이 되는가.",
        "metrics": [
            {"k": "ROE %d년 평균" % len(roes) if roes else "ROE", "v": None if not roes else "%.1f%%" % _avg(roes),
             "note": "최저 %.1f%%" % min(roes) if roes else "", "series": ser("roe")},
            {"k": "영업이익률 흔들림", "v": None if cv is None else "%.2f" % cv,
             "note": "변동계수 — 낮을수록 안정", "series": ser("margin")},
            {"k": "유보이익 1원 테스트", "v": None if not test else "%.1f원" % test["ratio"],
             "note": test["note"] if test else "주가·주식수 자료 부족", "series": []},
        ],
        "grade": _grade(good, 4),
        "verdict": _buffett_verdict(roes, cv, test),
        "q": "가격을 올려도 고객이 떠나지 않을 만한 무엇(브랜드·전환비용·네트워크·원가)이 있나?",
    })

    # 린치 — 어떤 종류의 회사인가
    kind, why = _lynch_kind(F)
    peg = price_info.get("peg")
    L.append({
        "guru": "피터 린치", "en": "Peter Lynch", "tag": kind,
        "clock": {"speed": "type", "h": "사고파는 규칙", "key": None,
                  "how": "타이밍 신호가 아니라 회사의 종류를 정한다 — 종류가 정해지면 팔 때가 정해진다(경기순환주는 이익 정점, 고성장주는 성장 둔화)."},
        "idea": "먼저 회사의 종류를 정한다 — 저성장·대형우량·고성장·경기순환·자산·회생. 종류마다 사고파는 이유가 다르다.",
        "metrics": [
            {"k": "매출 3년 연평균", "v": None if _cagr(F, "rev", 3) is None else "%+.1f%%" % _cagr(F, "rev", 3),
             "note": "", "series": ser("rev")},
            {"k": "EPS 3년 연평균", "v": None if _cagr(F, "eps", 3) is None else "%+.1f%%" % _cagr(F, "eps", 3),
             "note": "", "series": ser("eps")},
            {"k": "PEG", "v": None if peg is None else "%.2f" % peg, "note": "PER ÷ EPS 성장률 (1 미만이면 싸다)",
             "series": []},
        ],
        "grade": kind,
        "verdict": why,
        "q": "이 종류의 회사에서 무엇이 바뀌면 이야기가 끝나나?",
    })

    # 멍거 — 뒤집어 보기
    flags = _munger_flags(F)
    L.append({
        "guru": "찰리 멍거", "en": "Charlie Munger", "tag": "뒤집어 보기",
        "clock": {"speed": "slow", "h": "12개월", "key": "cfo_ni",
                  "how": "이익이 현금으로 들어오는지는 천천히 값에 든다(발생액 이상현상). 영업CF 가 순이익을 못 따라오면 1년 안에 대가를 치르는 편."},
        "idea": "어떻게 하면 이 투자가 망하나를 먼저 묻는다. 이익의 질, 운전자본, 빚, 잦은 자본 조달.",
        "flags": flags,
        "grade": "경고 %d" % sum(1 for f in flags if f["bad"]) if any(f["bad"] for f in flags) else "이상 없음",
        "verdict": "걸린 신호가 없다." if not any(f["bad"] for f in flags) else
                   "걸린 신호: " + ", ".join(f["k"] for f in flags if f["bad"]),
        "q": "이 회사가 3년 뒤 망가져 있다면 무엇 때문일까?",
    })
    return L


def _std(v):
    m = _avg(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v)) if v and m is not None else None


def _cagr(F, k, n):
    v = [d.get(k) for d in F if d.get(k) is not None]
    if len(v) <= n or v[-1 - n] is None or v[-1 - n] <= 0 or v[-1] <= 0:
        return None
    return ((v[-1] / v[-1 - n]) ** (1 / n) - 1) * 100


def _fisher_tag(psr):
    if psr is None:
        return "PSR 없음"
    return "싸다" if psr <= 0.75 else "적정" if psr <= 1.5 else "비싸다" if psr <= 3 else "과열"


def _fisher_glitch(F):
    """최근 해 순이익률이 직전 3년 평균의 절반 아래인데 매출은 늘었다 — 피셔의 '글리치'."""
    if len(F) < 4:
        return False
    d = F[-1]
    past = [x["ni"] / x["rev"] * 100 for x in F[-4:-1] if x.get("ni") is not None and x.get("rev")]
    if not past or _avg(past) < 5 or d.get("ni") is None or not d.get("rev") or (d.get("rev_yoy") or 0) < 0:
        return False
    return d["ni"] / d["rev"] * 100 < _avg(past) * 0.5


def _fisher_verdict(psr, prr, g, nm, glitch, pn):
    if psr is None:
        return "PSR 을 계산할 주가·주식수·매출 자료가 부족하다."
    s = "시가총액이 최근 4분기 매출의 %.2f배(%s 기준)." % (psr, pn.get("label") or "")
    if psr <= 0.75:
        s += " 피셔가 '슈퍼 스톡'을 사던 구간이다."
    elif psr <= 1.5:
        s += " 싸지도 비싸지도 않다."
    elif psr <= 3:
        s += " 매출 대비 비싸다 — 이익률이 한참 더 올라가야 정당화된다."
    else:
        s += " 피셔라면 사지 않는다(3배↑). 기대가 매출을 크게 앞질렀다."
    if prr is not None:
        s += " 연구개발비의 %.0f배%s." % (prr, " — 기술 투자에 비해 싸다" if prr <= 15 else " — 기술 투자에 비해 비싸다")
    if g is not None and nm:
        sup = g >= 15 and _avg(nm) >= 5
        s += " 매출 연평균 %+.0f%%, 순이익률 평균 %.1f%% — %s." % (g, _avg(nm), "슈퍼 컴퍼니 조건에 든다" if sup else "슈퍼 컴퍼니 조건엔 못 미친다")
    if glitch:
        s += " 지금은 매출이 느는데 이익률만 꺾인 '글리치' — 원인이 일시적이면 피셔의 매수 자리다."
    return s


def _druck_verdict(last, invd):
    if not last:
        return "분기 실적 자료가 부족하다."
    s = "최근 분기(%s) 매출 %s, 가속 %s." % (last.get("label", ""), _pct(last.get("매출YoY"), 1),
                                        "—" if last.get("매출가속") is None else "%+.1f%%p" % last["매출가속"])
    if last.get("매출가속") is not None:
        s += " 변화의 방향이 위를 향한다." if last["매출가속"] > 0 else " 변화의 방향이 꺾였다."
    if len(invd) >= 2:
        s += " 재고일수 %.0f일 → %.0f일%s." % (invd[0], invd[-1], " (재고가 가벼워짐)" if invd[-1] < invd[0] else " (재고가 쌓임)")
    return s


def _buffett_verdict(roes, cv, test):
    if not roes:
        return "ROE를 계산할 자료가 부족하다."
    s = "ROE %d년 평균 %.1f%% (최저 %.1f%%)." % (len(roes), _avg(roes), min(roes))
    if cv is not None:
        s += " 이익률 변동계수 %.2f — %s." % (cv, "안정적" if cv < 0.35 else "경기에 따라 크게 흔들림")
    if test:
        s += " " + test["note"] + "."
    return s


def _lynch_kind(F):
    g = _cagr(F, "rev", 3)
    ni = [d.get("ni") for d in F[-4:]]
    mg = [d.get("margin") for d in F[-8:] if d.get("margin") is not None]
    cv = (_std(mg) / abs(_avg(mg))) if (len(mg) >= 4 and _avg(mg)) else None
    if len(ni) >= 3 and ni[-3] is not None and ni[-1] is not None and ni[-3] < 0 < ni[-1]:
        return "회생주", "최근 3년 안에 적자에서 흑자로 돌아섰다. 회생이 끝까지 가는지 — 부채와 현금이 버티는지 본다."
    if g is None:
        return "판단 보류", "매출 성장률을 계산할 자료가 부족하다."
    if cv is not None and cv >= 0.5:
        return "경기순환주", "이익률이 크게 출렁인다(변동계수 %.2f). 사이클의 어디쯤인지가 전부다 — 이익이 최고일 때 PER이 가장 낮아 보인다." % cv
    if g >= 20:
        return "고성장주", "매출이 3년 연평균 %.0f%% 자란다. 성장이 어디서 멈출지, 확장이 반복 가능한지 본다." % g
    if g >= 8:
        return "대형우량주", "매출이 3년 연평균 %.0f%% 자란다. 30~50%% 오르면 비싸졌는지 다시 본다." % g
    return "저성장주", "매출이 3년 연평균 %.0f%% 자란다. 배당과 자사주가 수익의 대부분이다." % g


def _munger_flags(F):
    out = []
    r3 = F[-3:]
    cfo = sum(d["cfo"] for d in r3 if d.get("cfo") is not None)
    ni = sum(d["ni"] for d in r3 if d.get("ni") is not None)
    ok = all(d.get("cfo") is not None and d.get("ni") is not None for d in r3) and ni > 0
    out.append({"k": "이익의 현금화", "bad": bool(ok and cfo < 0.6 * ni),
                "v": ("최근 3년 영업CF ÷ 순이익 %.2f배" % (cfo / ni)) if ok else "자료 부족"})

    def growth(k):
        a = F[-4] if len(F) >= 4 else None
        b = F[-1] if F else None
        if a and b and a.get(k) and b.get(k):
            return (b[k] / a[k] - 1) * 100
        return None
    ar = growth("ar_days")
    out.append({"k": "매출채권 회수 지연", "bad": bool(ar is not None and ar >= 30),
                "v": "매출채권일수 3년 %s" % _pct(ar) if ar is not None else "자료 부족"})
    iv = growth("inv_days")
    out.append({"k": "재고 누적", "bad": bool(iv is not None and iv >= 30),
                "v": "재고일수 3년 %s" % _pct(iv) if iv is not None else "자료 부족"})
    le = F[-1].get("liab_eq") if F else None
    out.append({"k": "과도한 부채", "bad": bool(le is not None and le >= 200),
                "v": "부채비율 %.0f%%" % le if le is not None else "자료 부족"})
    caps = [d.get("cap") for d in F[-4:] if d.get("cap")]
    raises = sum(1 for a, b in zip(caps, caps[1:]) if b > a * 1.02)
    out.append({"k": "잦은 자본 조달", "bad": raises >= 2,
                "v": "최근 3년 자본금 증가 %d회" % raises})
    losses = sum(1 for d in F[-3:] if d.get("ni") is not None and d["ni"] < 0)
    out.append({"k": "적자 지속", "bad": losses >= 2, "v": "최근 3년 적자 %d회" % losses})
    return out
