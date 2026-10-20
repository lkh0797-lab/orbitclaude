# -*- coding: utf-8 -*-
"""궤도 v2 — 한 회사의 사업 궤도와 주가 궤도를 한 장에 (2026-10-21, docs/superpowers/specs/2026-10-21-orbit-v2-design.md).

순수 모듈: 서버 `orbit2_view` · 기저율 도구 `도구/궤도v2_기저율.py` · 시험이 **같은 함수**를 부른다.
새 점수 · 새 예측 없음 — 가속도 7국면을 셋(up · flat · down)으로 접고, PER 자기 역사 자리를 셋(cheap · mid · rich)으로 접어
9칸의 고정 문장(VERDICT)과 그 칸의 과거 기저율(cells.json, 미리 센 것)을 붙인다. 문장은 규칙 표의 글이지 생성이 아니다.
"""
import datetime as dt

VERSION = 1

# ---------------------------------------------------------------- 국면 → 셋 · 값 → 셋
BIZ_GROUP = {"확장 가속": "up", "회복": "up", "확장 유지": "flat", "정체": "flat",
             "둔화": "down", "부진 지속": "down", "수축 심화": "down"}
BIZ_NAME = {"up": "오름", "flat": "멈춤", "down": "꺾임"}
VAL_CHEAP, VAL_RICH = 30.0, 75.0        # 신호판 '값' 문턱(하위 30%) · 보통값 백테스트 '비싼' 경계(상위 25%)
VAL_NAME = {"cheap": "싸다", "mid": "보통", "rich": "비싸다"}
PER_MIN_N = 8                           # PER 자기 역사 표본 하한(_inv_ttm · drkValPit 과 같다)
ORDER_STRIP_PCT = 1.0                   # 사건 띠에 올리는 수주 공시 — TTM 매출 대비 %
DUE_Q, DUE_A = 45, 90                   # 분기 · 반기 = 분기 말 + 45일, 사업보고서 = 결산 + 90일
LABEL_OF_MONTH = {"03": "분기보고서", "06": "반기보고서", "09": "분기보고서", "12": "사업보고서"}


def biz_group(phase):
    """가속도 국면(7) → up / flat / down. 모르면 None."""
    return BIZ_GROUP.get(phase or "")


def val_zone(pct):
    """PER 자기 역사 자리(0~100, 작을수록 싸다) → cheap / mid / rich. 없으면 None."""
    if pct is None:
        return None
    return "cheap" if pct <= VAL_CHEAP else "rich" if pct >= VAL_RICH else "mid"


def per_pct_to(points, i):
    """points[i] 까지의 PER_TTM 기록(0 < PER < 300 · 분할 보정 못 한 'cut' 제외)에서 points[i] 의 자리(%). 표본 8 미만이면 None.
    앞날 자료는 안 섞는다(풍경 lsPitLine · 가속도 drkValPit · _inv_ttm 과 같은 생각)."""
    if i is None or i < 0 or i >= len(points):
        return None
    p = points[i]
    per = p.get("PER_TTM")
    if per is None or not (0 < per < 300) or "cut" in (p.get("품질") or []):
        return None
    hist = [x.get("PER_TTM") for x in points[:i + 1]
            if x.get("PER_TTM") is not None and 0 < x["PER_TTM"] < 300 and "cut" not in (x.get("품질") or [])]
    if len(hist) < PER_MIN_N:
        return None
    return sum(1 for v in hist if v <= per) / len(hist) * 100


def cell(biz, val):
    return ("%s·%s" % (biz, val)) if (biz and val) else None


# ---------------------------------------------------------------- 결론 문장 — 9칸 고정 표(회사마다 숫자만 다르다)
# 머리말은 자리 서술이다 — 오른다 · 내린다 · 덜 반영됐다 같은 방향 주장은 넣지 않는다(기저율 줄이 숫자로 말한다; 리뷰 2026-10-21:
# cells.json 에서 꺾임·보통 +3.8 이 오름·싸다 +1.9 보다 나았고, 가른 것은 값 자리였다). tests/test_궤도v2.py 가 금지 낱말을 고정한다.
VERDICT = {
    "up·cheap": {"head": "사업은 오르는데 값은 자기 역사 아래 — 사업과 값이 어긋난 자리",
                 "watch": "다음 보고서 영업이익률 · 수주잔고가 꺾이지 않는지"},
    "up·mid": {"head": "사업이 오르고 값은 자기 역사 가운데",
               "watch": "가속 B 가 띠(±3%p) 안으로 들어오는지"},
    "up·rich": {"head": "사업은 오르지만 값은 이미 자기 역사 위 — 이익이 값을 따라잡아야 하는 자리",
                "watch": "컨센서스 진도 · 영업이익률"},
    "flat·cheap": {"head": "사업은 멈췄고 값은 자기 역사 아래",
                   "watch": "변곡 ▲ · 수주"},
    "flat·mid": {"head": "사업도 값도 자기 역사 가운데",
                 "watch": "변곡"},
    "flat·rich": {"head": "사업은 멈췄는데 값은 자기 역사 위 — 기대가 사업보다 앞선 자리",
                  "watch": "영업이익률 1년 변화가 음으로 가는지(자홍)"},
    "down·cheap": {"head": "사업이 꺾였고 값은 자기 역사 아래",
                   "watch": "가속 B 부호 전환(▲) · 재고일수"},
    "down·mid": {"head": "사업이 꺾였고 값은 자기 역사 가운데",
                 "watch": "둔화가 정체로 가는지"},
    "down·rich": {"head": "사업이 꺾였는데 값은 자기 역사 위",
                  "watch": "빨간불 · 희석"},
}
VERDICT_BANNED = ("오른다", "내린다", "덜 반영", "가장 나쁜", "가장 좋은", "좋은 자리", "나쁜 자리", "뒤처졌다", "앞섰다", "사야", "팔아야", "안 믿는다")
GAP_LINE = {"blue": "엇갈림 파랑 — 이익률은 오르는데 주가는 빠졌다(과거 +2.6%p)",
            "magenta": "엇갈림 자홍 — 이익률은 내리는데 주가는 올랐다(과거 −3.5%p)"}


def verdict(biz, val, gap=None, gates=None):
    """{cell, head, watch, gap_line, gate_line, partial} — 칸이 없으면(국면 · 값 중 하나 모름) 있는 쪽만 적는다."""
    k = cell(biz, val)
    v = VERDICT.get(k) or {}
    head = v.get("head")
    partial = None
    if not head:
        if biz and not val:
            head = "사업은 %s(가속도 국면) — PER 자기 역사가 없어 값 자리를 모른다" % BIZ_NAME[biz]
            partial = "val"
        elif val and not biz:
            head = "값은 자기 역사에서 %s — 가속도 국면이 없어 사업 궤도를 모른다" % VAL_NAME[val]
            partial = "biz"
        else:
            head = "가속도 · PER 자료가 없어 궤도를 못 읽는다"
            partial = "both"
    gl = [(g.get("name") or "") + ((" — " + g["why"]) if g.get("why") else "") if isinstance(g, dict) else str(g) for g in (gates or [])]
    return {"cell": k, "head": head, "watch": v.get("watch") or "다음 보고서의 매출 · 영업이익률 방향",
            "gap_line": GAP_LINE.get(gap or ""), "gate_line": ("빨간불: " + " · ".join(gl)) if gl else None, "partial": partial}


# ---------------------------------------------------------------- 다음 정기보고서 예상일
def _qend(y, m):
    return dt.date(y, m, (31, 30, 30, 31)[m // 3 - 1])


def next_filing(last_stamp, today, label_of_month=None):
    """마지막 정기보고서 stamp('2026-06') → 다음 기(분기 말 + 3개월)의 예상 접수일 · D−n.
    분기 · 반기 = 분기 말 + 45일, 사업보고서(12월) = + 90일. 예상이지 공시 일정이 아니다(주말 · 연장 모름).
    예상일이 오늘보다 앞이면 지났다(overdue=True) — 색인에 아직 안 들어온 것."""
    try:
        y, m = int(last_stamp[:4]), int(last_stamp[5:7])
    except (TypeError, ValueError):
        return None
    if m not in (3, 6, 9, 12):
        return None
    lom = dict(LABEL_OF_MONTH)
    lom.update(label_of_month or {})
    ny, nm = (y + 1, 3) if m == 12 else (y, m + 3)
    lab = lom.get("%02d" % nm) or LABEL_OF_MONTH["%02d" % nm]
    due = _qend(ny, nm) + dt.timedelta(days=DUE_A if lab == "사업보고서" else DUE_Q)
    td = today if isinstance(today, dt.date) else dt.datetime.strptime(str(today), "%Y%m%d").date()
    days = (due - td).days
    return {"stamp": "%04d-%02d" % (ny, nm), "label": lab, "due": due.strftime("%Y%m%d"), "days": days, "overdue": days < 0}


# ---------------------------------------------------------------- 사건 — 한 줄 모양으로 모아 날짜 내림차순
def size_pct(amount, rev_ttm):
    return (amount / rev_ttm * 100) if (amount and rev_ttm and rev_ttm > 0) else None


def merge_events(*lists, since=None, limit=None):
    """[{d:'YYYYMMDD', kind, title, sub?, amt?, pct?, link?, tone?, strip?}] 여러 묶음 → 날짜 내림차순 하나. since 이후만, limit 개까지."""
    out = []
    for lst in lists:
        for e in lst or []:
            d = str(e.get("d") or "")
            if len(d) < 8 or (since and d < since):
                continue
            out.append(e)
    out.sort(key=lambda e: (e["d"], e.get("kind") or ""), reverse=True)
    return out[:limit] if limit else out


def filing_events(orbit_rows, min_x=1.5):
    """궤도 요약 행 → 큼 · 격변 보고서만 사건으로(정정은 뺀다). sub = 첫 요약 줄."""
    ev = []
    for r in orbit_rows or []:
        if r.get("tag") or r.get("x") is None or r["x"] < min_x:
            continue
        g = r.get("gist") or []
        g0 = g[0] if g and isinstance(g[0], dict) else {}
        ev.append({"d": (r.get("rcept") or "")[:8], "kind": "보고서", "rcept": r.get("rcept"),
                   "title": "%s %s 평소 대비 %.2f× (%s)" % (r.get("stamp"), r.get("label"), r["x"], r.get("tier") or ""),
                   "sub": g0.get("text") or ("문구 · 서식 손질 위주" if g0.get("polish") else None), "tone": 0, "strip": True, "x": r["x"], "tier": r.get("tier")})
    return ev


def order_events(orders, rev_ttm):
    """수주 공시(_ord_series) → 사건. 해지는 음. strip = 매출 대비 1%↑(해지는 늘).
    rev_ttm 은 숫자(한 값) 또는 callable(공시일 → 그때 TTM 매출) — 옛 계약을 지금 매출로 재지 않게."""
    ev = []
    for o in orders or []:
        amt = o.get("amount")
        pct = size_pct(amt, rev_ttm(o.get("date")) if callable(rev_ttm) else rev_ttm)
        cancel = o.get("kind") == "해지"
        ev.append({"d": o.get("date"), "kind": "수주 해지" if cancel else "수주", "rcept": o.get("rcept"),
                   "title": (o.get("title") or ("단일판매 · 공급계약 해지" if cancel else "단일판매 · 공급계약")) + (" (자회사)" if o.get("sub") else ""),
                   "sub": (o.get("party") or "") + ((" · %s~%s" % (o.get("start"), o.get("end"))) if o.get("start") else ""),
                   "amt": amt, "pct": pct, "tone": -1 if cancel else 1,
                   "strip": bool(cancel or (pct is not None and pct >= ORDER_STRIP_PCT)), "link": "dart"})
    return ev


def risk_events(risk_row, s12_row, since=None):
    """공시 위험 행(hits: 걸린 규칙 범주(유상증자 · CB · BW · 3자배정 · 최대주주 변경 …) · ref: 참고 범주(회생 · 감사의견 · 실질심사 …), 각 [{cat, rows: [[date, title, rcept]]}])
    + 12개월 요약(s12: {cat: {n, last}}) → 사건(음). 같은 rcept 는 한 번. hits 는 ref 와 겹치지 않으므로 둘 다 본다(리뷰 2026-10-21)."""
    ev, seen = [], set()
    for grp in ((risk_row or {}).get("hits") or []) + ((risk_row or {}).get("ref") or []):
        for row in grp.get("rows") or []:
            if len(row) < 3 or row[2] in seen:
                continue
            seen.add(row[2])
            ev.append({"d": row[0], "kind": "위험", "rcept": row[2], "title": row[1], "sub": grp.get("cat"), "tone": -1, "strip": True, "link": "dart"})
    for cat, x in (s12_row or {}).items():
        last = (x or {}).get("last")
        if not last or any(e["d"] == last and e.get("sub") == cat for e in ev):
            continue
        ev.append({"d": last, "kind": "위험", "title": cat + ((" ×%d" % x["n"]) if (x.get("n") or 0) > 1 else ""), "sub": "12개월 안 공시", "tone": -1, "strip": True})
    return [e for e in ev if not since or (e.get("d") or "") >= since]


def flag_events(points):
    """가속도 분기 점 → 흑자 · 적자 전환(분기 영업이익 부호가 전년 동기와 다름) · 변곡 ▲▼. 날짜 = 기준일(공시일)."""
    ev = []
    for p in sorted((p for p in points or [] if p.get("n") is not None), key=lambda p: p["n"]):
        d = str(p.get("기준일") or "")
        if len(d) < 8:
            continue
        op, op0 = p.get("영업이익"), p.get("영업이익_전")
        if op is not None and op0 is not None and (op > 0) != (op0 > 0):
            ev.append({"d": d, "kind": "전환", "title": ("흑자 전환" if op > 0 else "적자 전환") + " (%s 분기 영업이익)" % p.get("label"), "tone": 1 if op > 0 else -1, "strip": True})
        if p.get("변곡") in ("▲", "▼"):
            ev.append({"d": d, "kind": "변곡", "title": "가속 B 변곡 %s (%s)" % (p["변곡"], p.get("label")), "tone": 1 if p["변곡"] == "▲" else -1, "strip": True})
    return ev


def report_events(items, since=None):
    """내러티브 캐시 항목(type report) → 증권사 리포트 사건(목표가 · 의견). 주가 반응(re.chg)을 달아 둔다."""
    ev = []
    for it in items or []:
        if it.get("type") != "report" or it.get("hide"):
            continue
        d = str(it.get("d") or "")
        if since and d < since:
            continue
        tp = it.get("tp")
        up = ((tp / it["price_at"] - 1) * 100) if (tp and it.get("price_at")) else None
        ev.append({"d": d, "kind": "리포트", "title": it.get("title") or "", "sub": " · ".join(x for x in ((it.get("opinion") or ""), ("목표가 %s" % format(int(tp), ",")) if tp else "", ("상승여력 %+.0f%%" % up) if up is not None else "") if x),
                   "tone": 0, "strip": False, "re": (it.get("re") or {}).get("chg"), "link": "rep"})
    return ev


# ---------------------------------------------------------------- 분기 궤적 표
def _ratio(a, b):
    return (a / b - 1) * 100 if (a is not None and b is not None and a > 0 and b > 0) else None


def quarters_table(points, backlog_by_label=None, text_by_label=None, n=8):
    """최근 n 분기 — 분기 · 매출(YoY) · 영업이익(YoY) · 이익률(1년 변화) · TTM 매출 성장 · 가속 B · 국면 · 분기말 주가 · PER 자리(그때까지) · 잔고 · 글 배수."""
    pts = sorted((p for p in points or [] if p.get("n") is not None and p.get("label")), key=lambda p: p["n"])
    by = {p["n"]: p for p in pts}
    rows = []
    for i, p in enumerate(pts):
        if not p.get("fs") and p.get("매출액") is None:
            continue
        p4 = by.get(p["n"] - 4)
        m = (p["영업이익_TTM"] / p["매출_TTM"] * 100) if (p.get("영업이익_TTM") is not None and (p.get("매출_TTM") or 0) > 0) else None
        m4 = (p4["영업이익_TTM"] / p4["매출_TTM"] * 100) if (p4 and p4.get("영업이익_TTM") is not None and (p4.get("매출_TTM") or 0) > 0) else None
        rows.append({"label": p["label"], "d": str(p.get("기준일") or ""), "rev": p.get("매출액"), "rev_yoy": p.get("매출YoY"),
                     "op": p.get("영업이익"), "op_yoy": p.get("영업이익YoY"), "m": m, "dm": (m - m4) if (m is not None and m4 is not None) else None,
                     "ttm_g": _ratio(p.get("매출_TTM"), (p4 or {}).get("매출_TTM")), "b": p.get("가속B"), "phase": p.get("국면"), "turn": p.get("변곡"),
                     "px": p.get("주가"), "per": p.get("PER_TTM"), "per_pct": per_pct_to(pts, i),
                     "backlog": (backlog_by_label or {}).get(p["label"]), "x": (text_by_label or {}).get(p["label"]), "q": list(p.get("품질") or [])})
    return rows[-n:]


def biz_line(p, facts=None):
    """사업 궤도 한 줄 — 국면 · TTM 매출 성장 · 가속 B · 영업이익률(1년) · 잔고(있으면)."""
    if not p:
        return "가속도 자료 없음"
    bits = []
    if p.get("phase"):
        bits.append("국면 " + p["phase"])
    if p.get("ttm_g") is not None:
        bits.append("최근 4분기 매출 %+.0f%%" % p["ttm_g"])
    if p.get("b") is not None:
        bits.append("가속 B %+.1f%%p" % p["b"])
    if p.get("m") is not None:
        bits.append("영업이익률 %.1f%%" % p["m"] + ((" (1년 %+.1f%%p)" % p["dm"]) if p.get("dm") is not None else ""))
    f = facts or {}
    if f.get("blog_yoy") is not None:
        if f.get("ok", True):
            bits.append("수주잔고 1년 %+.0f%%" % f["blog_yoy"] + ((" · 북투빌 %.2f" % f["btb"]) if f.get("btb") is not None else ""))
        else:
            bits.append("수주잔고 못 믿음(%s)" % (f.get("why") or "표본 · 방법 바뀜"))
    return " · ".join(bits) + ((" (%s)" % p["label"]) if p.get("label") else "")


def px_line(px, val, line_now=None, ind_per=None, val_now=None):
    """주가 궤도 한 줄 — 1년 · 52주 · 공시일 PER(자리, 칸 기준) · 지금 PER(풍경) · 이익선 대비 · 업종 PER 중앙."""
    px = px or {}
    bits = []
    if px.get("r12") is not None:
        bits.append("1년 %+.0f%%" % px["r12"])
    if px.get("dd") is not None:
        bits.append("52주 고점 대비 %+.0f%%" % px["dd"])
    if px.get("r3") is not None:
        bits.append("3개월 %+.0f%%" % px["r3"])
    v = val or {}
    if v.get("per") is not None:
        bits.append("공시일 PER %.0f배" % v["per"] + ((" = 자기 역사 %s(%d%% 자리%s)" % (VAL_NAME.get(val_zone(v.get("pct")), "—"), round(v["pct"]), (", " + v["label"]) if v.get("label") else "")) if v.get("pct") is not None else ""))
    n_ = val_now or {}
    if n_.get("per") is not None and n_.get("pct") is not None:
        bits.append("지금 PER %.0f배 · %d%% 자리(풍경 %s)" % (n_["per"], round(n_["pct"]), (n_.get("date") or "")[4:6] + "-" + (n_.get("date") or "")[6:8] if len(n_.get("date") or "") >= 8 else ""))
    if line_now and px.get("px"):
        bits.append("이익선(자기 PER 중앙 × TTM EPS) 대비 %+.0f%%" % ((px["px"] / line_now - 1) * 100))
    if ind_per and ind_per.get("med") is not None:
        bits.append("업종 PER 중앙 %.0f배(%d곳)" % (ind_per["med"], ind_per.get("n") or 0))
    return " · ".join(bits) if bits else "주가 자료 없음"


def base_line(cells, key):
    """cells.json 의 칸 → 한 줄. 없으면 '아직 안 셈'. 구간이 0 을 걸치면 그렇게 적는다."""
    if not cells or not key:
        return None
    c = (cells.get("cells") or {}).get(key)
    if not c or c.get("n", 0) < 20:
        return "이 칸(%s)은 과거 표본이 적다(%d행)" % (key, (c or {}).get("n", 0))
    ci = c.get("ci") or [None, None]
    clear = ci[0] is not None and (ci[0] > 0 or ci[1] < 0)
    return "%d회(%d곳) 12개월 초과수익 중앙 %+.1f%%p [%+.1f, %+.1f] · 이긴 %d%% · ~2019 %s · 2020~ %s — %s" % (
        c["n"], c.get("firms") or 0, c.get("med") or 0, ci[0] or 0, ci[1] or 0, round(c.get("hit") or 0),
        ("%+.1f" % c["early"]) if c.get("early") is not None else "—", ("%+.1f" % c["late"]) if c.get("late") is not None else "—",
        ("뚜렷하다" if clear else "0 을 걸친다(차이를 확신할 수 없다)"))
