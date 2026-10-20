# -*- coding: utf-8 -*-
"""꿰미 — 흩어진 탭의 신호를 회사마다 구슬 한 줄로 꿴다 (2026-10-20, docs/superpowers/specs/2026-10-20-beads-design.md).

구슬 열 개(정보가 들어오는 순서) + 가림 셋 + 내 기록. 문턱은 **그 탭 것 그대로** — 여기서 새로 맞추지 않는다.
  근거 구슬(K 에 센다 — 그 탭 과거 검증에서 12개월 초과수익 90% 구간이 0 을 비켰다): 수주 · 엇갈림 · 값 · 눌림 · 사슬
  참고 구슬(보이지만 K 밖 — 검증이 없거나 실패했거나 주가 신호가 아니었다): 수출 · 실적 · 글 · 차트 · 리포트
  가림(하나라도 있으면 줄을 어둡게): 위험(공시 위험 · 12개월 희석 · 부실 · KIS) · 둔화(시너지 단계) · 자홍(이익률↓ · 주가↑)
순위 = K → 참고 구슬 수 → 시가총액 순. 점수를 합치지 않는다.

서버(`beads_view`)와 백테스트(`도구/꿰미_백테스트.py`)가 **같은 함수**(`string`)를 부른다 — 입력은 정규화한 dict 하나(아래 `string` 설명).
켜짐 · 꺼짐 · 빈(그 회사엔 그 자료가 없다)을 가른다: 빈 구슬은 K 에서 꺼짐으로 센다(해석 줄에는 '빈'으로).
"""
VERSION = 1

# ---------------------------------------------------------------- 문턱(그 탭 것을 복사 — tests/test_꿰미.py 가 같음을 고정한다)
TH = {
    "su": 200.0 / 3,     # 수주 — 시너지 수주 부분 점수(그날 믿을 수 있는 회사끼리 북투빌 · 잔고/매출 변화 백분위 평균) 상⅓
    "op_yoy": 20.0,      # 실적 A — 탑픽.TH["op_yoy"]
    "rev_yoy": 5.0,      # 실적 A — 탑픽.TH["rev_yoy"]
    "text_x": 1.5,       # 글 — 궤도 ORBIT_TIERS '큼' 경계(평소 대비 배수)
    "gap_m": 0.5,        # 엇갈림 · 자홍 — TTM 영업이익률 1년 변화 %p (도구/엇갈림_백테스트 M_TH)
    "gap_p": 5.0,        # 엇갈림 · 자홍 — 1년 주가 변화 % (P_TH)
    "val_pct": 30.0,     # 값 — PER 자기 역사 하위 30%(시너지 '싸다' · 분기 변화 · 저평가 깃발이 쓰는 수)
    "val_n": 8,          # 값 — PER 자기 역사 표본 8분기↑(수출 선행과 같다)
    "dd": -25.0,         # 눌림 — 서버 VAL_DD
    "ni": -5.0,          # 눌림 — 서버 VAL_NI
    "score": 50.0,       # 눌림 — 서버 VAL_MIN
    "chain_pct": 10.0,   # 사슬 — 매출처 비중 10%↑
    "chain_p3": 90.0,    # 사슬 — 고객 3개월 수익률 전 종목 상위 10%(밸류체인 후속주 백테스트의 주도주 정의)
    "chart_days": 7,     # 차트 — 최근 스캔 7일 안
    "rep_up": 20.0,      # 리포트 — 180일 목표가 평균 상승여력 %
    "rep_n": 2,          # 리포트 — 증권사 2곳↑
}
STAGE_SLOW = "둔화"
RISK_RED = ("상폐 절차", "보고서 없음", "작전주 꼴")      # 공시위험 level — 저평가 DRISK_RED 와 같다

# 구슬 정의 — key · 이름 · 출처 탭(data-t) · 종류(근거 base / 참고 ref) · 문턱 글 · 과거 검증 한 줄(그 탭 README 숫자, 2026-10-20)
BEADS = [
    {"key": "exp", "name": "수출", "tab": "exp", "tab_name": "수출 추적", "kind": "ref",
     "rule": "수출 선행 단서 A·B — 아직 공시 안 된 분기 통관 +20%↑ · 덩어리 아님",
     "ev": "다음 분기 매출을 먼저 읽는다(순위상관 0.37) — 주가 신호는 아니었다(90일 t 1.0~1.7)"},
    {"key": "su", "name": "수주", "tab": "cat", "tab_name": "호재기업", "kind": "base",
     "rule": "시너지 수주 부분 ≥ 67(그날 믿을 수 있는 회사끼리 북투빌 · 잔고/매출 1년 변화 백분위 평균 상⅓) · 단계 둔화 아님",
     "ev": "v3 상⅓−하⅓ +10.6 [+4.4, +16.7](표본 안) · 북투빌 ≥1 +10.7 [+6.0, +15.7] · 둔화 단계만 뒤처짐 −1.4"},
    {"key": "earn", "name": "실적", "tab": "top", "tab_name": "탑픽", "kind": "ref",
     "rule": "탑픽 A(영업이익 YoY ≥ +20% & 매출 ≥ +5%, 또는 흑자 전환 · 기저 1% 규칙) 또는 B(TTM 영업이익 12분기↑ 신고점)",
     "ev": "저PER 과 차이를 확신할 수 없다 +1.1 [−0.3, +5.5] · 실적 조건만 −0.8 — 우위는 '자기 역사로 싸다'에서 왔다"},
    {"key": "text", "name": "글", "tab": "orbit", "tab_name": "궤도", "kind": "ref",
     "rule": "최근 정기보고서가 평소 대비 1.5×↑ 새로 씀(큼 · 격변)",
     "ev": "선행 점수 표본 밖 실패(Q5−Q1 3개월 −1.9%p) · 문장 변화량 우리 표본 확인 안 됨"},
    {"key": "gap", "name": "엇갈림", "tab": "druck", "tab_name": "가속도", "kind": "base",
     "rule": "TTM 영업이익률 1년 변화 ≥ +0.5%p 이고 1년 주가 ≤ −5%(한눈에 판 파랑)",
     "ev": "파랑 +2.6 [+1.1, +4.7] (3,537번, 이긴 53.5%) · 생존 맞춤 +2.3 (앞 기간 +0.2 약함)"},
    {"key": "val", "name": "값", "tab": "land", "tab_name": "풍경", "kind": "base",
     "rule": "PER 자기 역사(최근 40분기) 하위 30% · 표본 8분기↑ · 흑자",
     "ev": "싼 수주 +10.9 [+6.2, +17.3] · PSR 자기 역사 하위 30% +2.2 · 분기 변화 PER 하위 30% +1.4 [−0.1, +3.0](약함) · 저평가 안에서는 반대(−9.5)"},
    {"key": "dip", "name": "눌림", "tab": "val", "tab_name": "저평가", "kind": "base",
     "rule": "저평가 등급(공시 위험 · KIS 반영 뒤) — 이익 지킴(순이익 1년 ≥ −5%) · 52주 −25%↓ · 빨간불 없음 · 점수 50↑",
     "ev": "저평가 − 관찰 +4.3 [+1.8, +6.9] · 중앙 +3.3 · 54% 이김 · 점수 구성은 표본 안"},
    {"key": "chain", "name": "사슬", "tab": "tl", "tab_name": "밸류체인", "kind": "base",
     "rule": "최신 매출처 표의 상장 고객(비중 10%↑ · 같은 그룹 아님) 중 3개월 수익률 전 종목 상위 10% 인 곳이 있다",
     "ev": "공급망 후속 6개월 백분위 +3.25 [+1.93, +4.62] — 같은 업종 아무 종목 +1.92 와 구간 겹침"},
    {"key": "chart", "name": "차트", "tab": "tech", "tab_name": "차트 발굴", "kind": "ref",
     "rule": "최근 7일 스캔 일지(지금 식 규칙)에 들어 있다",
     "ev": "저평가 위에 보태는 몫 확인 안 됨(12개월 −1.0 [−6.4, +3.4]) · 박스 돌파 +2.7(6개월)"},
    {"key": "rep", "name": "리포트", "tab": "rep", "tab_name": "리포트", "kind": "ref",
     "rule": "180일 증권사 2곳↑ 목표가 평균 상승여력 ≥ +20%",
     "ev": "검증 없음(늦은 신호)"},
]
GATES = [
    {"key": "risk", "name": "위험", "tab": "val", "rule": "공시위험 상폐 절차 · 보고서 없음 · 작전주 꼴 / 12개월 희석(CB · BW · EB · 유상증자 · 3자배정) · 부실 / KIS 관리 · 정지 · 정리매매 · 투자위험",
     "ev": "작전주 꼴 + 배당 없음: 상폐 24개월 재현율 64% · 걸러낸 비율 8.2% · 부실 공시 12개월 −4.7"},
    {"key": "slow", "name": "둔화", "tab": "cat", "rule": "시너지 단계 둔화(잔고 감소 · 북투빌 < 1)", "ev": "과거에 유일하게 뒤처진 무리 −1.4"},
    {"key": "magenta", "name": "자홍", "tab": "druck", "rule": "TTM 영업이익률 1년 −0.5%p↓ 이고 1년 주가 +5%↑", "ev": "−3.5 [−4.5, −2.3] · 생존 맞춤 −3.0 [−4.4, −1.2]"},
]
BASE_KEYS = [b["key"] for b in BEADS if b["kind"] == "base"]
REF_KEYS = [b["key"] for b in BEADS if b["kind"] == "ref"]
BEAD_BY = {b["key"]: b for b in BEADS}


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _bead(on, known=True, **val):
    """구슬 하나 {on, known, …재료}. known=False 면 on 은 늘 False."""
    d = {"on": bool(on) and bool(known), "known": bool(known)}
    d.update(val)
    return d


# ---------------------------------------------------------------- 구슬 함수 — 정규화한 재료 → 구슬
def bead_exp(x):
    """수출 — x = {clue, tier, cur, months_label, cur_q, grade} (수출 선행 행) · None 이면 통로 없음(빈)."""
    if not x:
        return _bead(False, False)
    return _bead(bool(x.get("clue")), True, tier=x.get("tier"), cur=_f(x.get("cur")), months=x.get("months_label"), q=x.get("cur_q"), grade=x.get("grade"))


def bead_su(x):
    """수주 — x = {reliable, p_su, stage, btb, cover_chg, score}. 믿을 수 없는 행 · 행 없음 → 빈."""
    if not x or not x.get("reliable") or _f(x.get("p_su")) is None:
        return _bead(False, False, stage=(x or {}).get("stage"))
    p = _f(x["p_su"])
    return _bead(p >= TH["su"] and x.get("stage") != STAGE_SLOW, True, p=p, stage=x.get("stage"), btb=_f(x.get("btb")), cover_chg=_f(x.get("cover_chg")), score=_f(x.get("score")))


def bead_earn(x):
    """실적 — x = 탑픽 판정 {A, B, op_yoy, rev_yoy, turn, ttm_g, label, known, fin, hold}. 금융 · 지주 · 판정 없음 → 빈."""
    if not x or x.get("fin") or x.get("hold"):
        return _bead(False, False)
    return _bead(bool(x.get("A")) or bool(x.get("B")), True, A=bool(x.get("A")), B=bool(x.get("B")), op_yoy=_f(x.get("op_yoy")), rev_yoy=_f(x.get("rev_yoy")),
                 turn=bool(x.get("turn")), ttm_g=_f(x.get("ttm_g")), label=x.get("label"), d=x.get("known"))


def bead_text(x):
    """글 — x = 최근 정기보고서 궤도 행 {x(배수), tier, label, stamp, gist}. 배수 없음(첫 보고서 · 정정) → 빈."""
    if not x or _f(x.get("x")) is None:
        return _bead(False, False)
    return _bead(_f(x["x"]) >= TH["text_x"], True, x=_f(x["x"]), tier=x.get("tier"), label=x.get("label"), stamp=x.get("stamp"), gist=x.get("gist"))


def gap_of(dm, dp):
    """엇갈림 칸 색 — (TTM 영업이익률 1년 변화 %p, 1년 주가 %) → 'blue' · 'magenta' · None. 화면 drkGapOf · 도구/엇갈림_백테스트 와 같은 문턱."""
    dm, dp = _f(dm), _f(dp)
    if dm is None or dp is None:
        return None
    if dm >= TH["gap_m"] and dp <= -TH["gap_p"]:
        return "blue"
    if dm <= -TH["gap_m"] and dp >= TH["gap_p"]:
        return "magenta"
    return None


def bead_gap(x):
    """엇갈림 — x = {dm, dp, label, d}. 둘 중 하나라도 없으면 빈. 자홍은 가림(gates)에서 같은 재료로 본다."""
    if not x:
        return _bead(False, False)
    c = gap_of(x.get("dm"), x.get("dp"))
    if _f(x.get("dm")) is None or _f(x.get("dp")) is None:
        return _bead(False, False)
    return _bead(c == "blue", True, dm=_f(x["dm"]), dp=_f(x["dp"]), color=c, label=x.get("label"), d=x.get("d"))


def bead_val(x):
    """값 — x = 풍경 decide {per, pct, n, date}. PER 없음(적자) · 표본 < 8 → 빈."""
    if not x or _f(x.get("pct")) is None or (_f(x.get("per")) or 0) <= 0 or (x.get("n") is not None and int(x["n"]) < TH["val_n"]):
        return _bead(False, False, per=_f((x or {}).get("per")))
    return _bead(_f(x["pct"]) <= TH["val_pct"], True, per=_f(x.get("per")), pct=_f(x["pct"]), n=x.get("n"), date=x.get("date"), zone=x.get("zone"))


def bead_dip(x):
    """눌림 — x = 저평가 행 {tier, score, dd, ni_yoy, red, lab, fell} · None = 52주 −25% 안 빠짐(꺼짐, 안 빈 — 전 종목을 본 결과다)."""
    if not x:
        return _bead(False, True, fell=False)
    return _bead(x.get("tier") == "저평가", True, fell=bool(x.get("fell", True)), tier=x.get("tier"), score=_f(x.get("score")), dd=_f(x.get("dd")),
                 ni_yoy=_f(x.get("ni_yoy")), red=list(x.get("red") or []), why=list(x.get("tier_why") or [])[:2], lab=x.get("lab"))


def bead_chain(x):
    """사슬 — x = {custs: [{code, name, pct, p3}], year}. 이어지는 상장 고객(비중 10%↑)이 없으면 빈."""
    custs = [c for c in ((x or {}).get("custs") or []) if c.get("code") and (_f(c.get("pct")) or 0) >= TH["chain_pct"]]
    if not custs:
        return _bead(False, False, n=0)
    hits = [c for c in custs if _f(c.get("p3")) is not None and _f(c["p3"]) >= TH["chain_p3"]]
    return _bead(bool(hits), True, n=len(custs), hits=[{"code": c["code"], "name": c.get("name"), "pct": _f(c.get("pct")), "p3": _f(c.get("p3"))} for c in hits],
                 custs=[{"code": c["code"], "name": c.get("name"), "pct": _f(c.get("pct")), "p3": _f(c.get("p3"))} for c in custs][:6], year=(x or {}).get("year"))


def bead_chart(x):
    """차트 — x = {rows: [{pattern, stage, asof}], has_journal}. 일지 자체가 없으면 빈."""
    if not x or not x.get("has_journal"):
        return _bead(False, False)
    rows = list(x.get("rows") or [])
    return _bead(bool(rows), True, rows=rows[:4])


def bead_rep(x):
    """리포트 — x = {up, n, n180, tp_avg, price}. 리포트 모음이 데워져 있지 않으면 빈."""
    if not x or not x.get("warm"):
        return _bead(False, False)
    up, n = _f(x.get("up")), int(x.get("n") or 0)
    return _bead(up is not None and n >= TH["rep_n"] and up >= TH["rep_up"], True, up=up, n=n, n180=x.get("n180"), tp=_f(x.get("tp_avg")))


def gates_of(inp):
    """가림 [{key, name, why}] — 위험(공시 level · 12개월 표지 · KIS) · 둔화 · 자홍."""
    out = []
    rk = inp.get("risk") or {}
    why = []
    if rk.get("level") in RISK_RED:
        why.append("공시 위험 " + rk["level"])
    why += [x.replace(" — ", ": ", 1) for x in (rk.get("flags") or [])]
    why += ["증권사 상태 " + x for x in (rk.get("kis") or [])]
    if why:
        out.append({"key": "risk", "name": "위험", "why": " · ".join(why)})
    syn = inp.get("syn") or {}
    if syn.get("reliable") and syn.get("stage") == STAGE_SLOW:
        out.append({"key": "slow", "name": "둔화", "why": "시너지 단계 둔화 — 잔고가 줄거나 들어오는 수주가 매출보다 적다"})
    g = inp.get("gap") or {}
    if gap_of(g.get("dm"), g.get("dp")) == "magenta":
        out.append({"key": "magenta", "name": "자홍", "why": "이익률 1년 %+.1f%%p 인데 주가 1년 %+.0f%%" % (_f(g["dm"]), _f(g["dp"]))})
    return out


def string(inp):
    """회사 하나의 구슬 줄. inp = {code, name, exp, syn, earn, text, gap, val, dip, chain, chart, rep, risk, mine, …} — 키마다 위 bead_* 의 재료(없으면 None).
    돌려줌 {beads{key: 구슬}, k(근거 켜짐 수), k_ref(참고 켜짐 수), n_known(근거 관측 가능 수), gates[], gated(bool), rank_key}."""
    beads = {
        "exp": bead_exp(inp.get("exp")), "su": bead_su(inp.get("syn")), "earn": bead_earn(inp.get("earn")), "text": bead_text(inp.get("text")),
        "gap": bead_gap(inp.get("gap")), "val": bead_val(inp.get("val")), "dip": bead_dip(inp.get("dip")), "chain": bead_chain(inp.get("chain")),
        "chart": bead_chart(inp.get("chart")), "rep": bead_rep(inp.get("rep")),
    }
    k = sum(1 for key in BASE_KEYS if beads[key]["on"])
    k_ref = sum(1 for key in REF_KEYS if beads[key]["on"])
    n_known = sum(1 for key in BASE_KEYS if beads[key]["known"])
    gates = gates_of(inp)
    cap_rank = inp.get("cap_rank")
    return {"beads": beads, "k": k, "k_ref": k_ref, "n_known": n_known, "gates": gates, "gated": bool(gates),
            "rank_key": (bool(gates), -k, -k_ref, cap_rank if isinstance(cap_rank, int) else 10 ** 6, str(inp.get("code") or ""))}


# ---------------------------------------------------------------- 해석 — 구슬마다 숫자 한 줄
def _pct_txt(v, d=0):
    return "—" if v is None else ("%+." + str(d) + "f%%") % v


def _line(key, b, inp):
    nm = BEAD_BY[key]["name"]
    mark = "●" if b["on"] else ("◌" if not b["known"] else "○")
    if key == "exp":
        if not b["known"]:
            body = "통관 통로 없음(공장 · 품목이 관세청 집계와 안 맞음)"
        else:
            body = "%s단서%s — 아직 공시 안 된 %s 통관 %s(%s)" % (b.get("grade") or "", "" if b["on"] else " 아님", b.get("q") or "분기", _pct_txt(b.get("cur")), b.get("months") or "")
            if b.get("tier"):
                body += " · 수출 선행 " + b["tier"]
    elif key == "su":
        if not b["known"]:
            body = "잔고를 믿을 수 없거나 없다" + ((" · 단계 " + b["stage"]) if b.get("stage") else "")
        else:
            body = "수주 부분 %d점(상⅓ = 67↑)" % round(b["p"])
            if b.get("btb") is not None:
                body += " — 북투빌 %.1f배" % b["btb"]
            if b.get("cover_chg") is not None:
                body += " · 잔고/연매출 1년 %+.1f년" % b["cover_chg"]
            body += " · 단계 %s" % (b.get("stage") or "—")
            if b.get("stage") == STAGE_SLOW:
                body += "(둔화라 켜지 않음)"
    elif key == "earn":
        if not b["known"]:
            body = "금융 · 지주이거나 분기 숫자가 없다(탑픽 적격 밖)"
        else:
            parts = []
            if b.get("A"):
                parts.append("흑자 전환" if b.get("turn") and (b.get("op_yoy") is None) else "영업이익 YoY %s · 매출 %s" % (_pct_txt(b.get("op_yoy")), _pct_txt(b.get("rev_yoy"))))
            if b.get("B"):
                parts.append("TTM 영업이익 신고점" + ((" (%+.0f%%)" % b["ttm_g"]) if b.get("ttm_g") is not None else ""))
            if not parts:
                parts.append("영업이익 YoY %s · 매출 %s — A(+20 · +5) 도 B(신고점) 도 아님" % (_pct_txt(b.get("op_yoy")), _pct_txt(b.get("rev_yoy"))))
            body = " · ".join(parts) + ((" (%s)" % b["label"]) if b.get("label") else "")
    elif key == "text":
        if not b["known"]:
            body = "견줄 직전 보고서가 없다"
        else:
            body = "%s %s 평소 대비 %.1f× (%s)" % (b.get("stamp") or "", b.get("label") or "보고서", b["x"], b.get("tier") or "—")
            if b.get("gist"):
                body += " — " + b["gist"]
    elif key == "gap":
        if not b["known"]:
            body = "TTM 이익률 1년 변화 또는 1년 주가를 모른다"
        else:
            body = "이익률 1년 %+.1f%%p · 주가 1년 %+.0f%% (%s)" % (b["dm"], b["dp"], b.get("label") or "")
            body += {"blue": " — 파랑(이익률↑ · 주가↓)", "magenta": " — 자홍(이익률↓ · 주가↑, 가림)"}.get(b.get("color"), " — 엇갈리지 않음")
    elif key == "val":
        if not b["known"]:
            body = "PER 자기 역사 없음(적자 · 표본 8분기 미만 · 풍경 없음)"
        else:
            body = "PER %.1f배 — 자기 과거 PER 가운데 %d%% 자리(30 이하 = 싸다)" % (b["per"], round(b["pct"]))
    elif key == "dip":
        if not b.get("fell", True):
            body = "52주 고점 −25% 안 빠짐(저평가 후보 밖)"
        else:
            body = "저평가 %s" % (b.get("tier") or "—")
            if b.get("score") is not None:
                body += " 점수 %d" % round(b["score"])
            if b.get("dd") is not None:
                body += " · 52주 고점 대비 %+.0f%%" % b["dd"]
            if b.get("ni_yoy") is not None:
                body += " · 순이익 1년 %+.0f%%" % b["ni_yoy"]
            if b.get("red"):
                body += " · 빨간불: " + " · ".join(b["red"][:2])
            elif b.get("why") and b.get("tier") != "저평가":
                body += " · " + " · ".join(b["why"])
    elif key == "chain":
        if not b["known"]:
            body = "매출처 표에 이어지는 상장 고객(비중 10%↑)이 없다"
        else:
            if b["on"]:
                body = "고객 " + " · ".join("%s(매출의 %.0f%%, 3개월 상위 %d%%)" % (h.get("name") or h["code"], h["pct"] or 0, max(1, round(100 - (h["p3"] or 0)))) for h in b["hits"][:3]) + " 가 올랐다"
            else:
                body = "상장 고객 " + " · ".join("%s(%.0f%%%s)" % (c.get("name") or c["code"], c["pct"] or 0, (", 3개월 자리 %d" % round(c["p3"])) if c.get("p3") is not None else "") for c in b["custs"][:3]) + " — 아직 안 올랐다"
            if b.get("year"):
                body += " (%s 매출처 표)" % b["year"]
    elif key == "chart":
        body = "스캔 일지 없음" if not b["known"] else (("최근 스캔: " + " · ".join("%s%s(%s)" % (r.get("pattern") or "", (" " + r["stage"]) if r.get("stage") else "", r.get("asof") or "") for r in b["rows"])) if b["on"] else "최근 7일 스캔에 없음")
    elif key == "rep":
        body = "리포트 모음이 아직 안 데워졌다" if not b["known"] else ("증권사 %d곳 목표가 평균 상승여력 %s" % (b["n"], _pct_txt(b.get("up"))) if b.get("n") else "180일 안 목표가 낸 증권사 없음")
    else:
        body = ""
    return [mark + " " + nm, body + " [%s]" % BEAD_BY[key]["tab_name"]]


def explain(row):
    """[[구슬, 내용], …] — 머리 한 줄(근거 n/m · 참고 n · 가림) → 구슬 열 개(정보 순서) → 가림 → 내 기록. 숫자는 모두 입력 재료 값."""
    s = row.get("string") or string(row)
    B = s["beads"]
    head = "근거 구슬 %d개 켜짐(관측 가능 %d/%d) · 참고 %d개" % (s["k"], s["n_known"], len(BASE_KEYS), s["k_ref"])
    head += (" · 가림 " + " · ".join(g["name"] for g in s["gates"])) if s["gates"] else " · 가림 없음"
    out = [["꿰미", head]]
    for b in BEADS:
        out.append(_line(b["key"], B[b["key"]], row))
    for g in s["gates"]:
        out.append(["가림 " + g["name"], g["why"]])
    m = row.get("mine") or {}
    if m:
        bits = [t for ok, t in ((m.get("watch"), "관심 장부에 있다"), (m.get("hold"), "보유 중"), (m.get("n_judge"), "판정 기록 %s번" % m.get("n_judge"))) if ok]
        if bits:
            out.append(["내 기록", " · ".join(bits)])
    return out


def counts(rows):
    """구슬마다 {on, known} 수 · K 분포 — 화면 설명 띠."""
    per = {b["key"]: {"on": 0, "known": 0} for b in BEADS}
    gates = {g["key"]: 0 for g in GATES}
    kd = {}
    for r in rows:
        s = r["string"]
        for k, b in s["beads"].items():
            per[k]["on"] += b["on"]
            per[k]["known"] += b["known"]
        for g in s["gates"]:
            gates[g["key"]] += 1
        kd[s["k"]] = kd.get(s["k"], 0) + 1
    return {"beads": per, "gates": gates, "k": {str(k): v for k, v in sorted(kd.items())}}
