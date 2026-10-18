# -*- coding: utf-8 -*-
"""
제품 믹스 — 이번 성장을 어느 부문 · 제품이 끌었나 (2026-10-17).

재료: 밸류체인 캐시(.cache/밸류체인/{code}.json)가 해마다 사업보고서 「주요 제품 등의 현황」 표에서 뽑아 둔
years[YYYY].products = [{segment, kind, item, use, amt, pct}] — 금액 단위 줄은 읽지 않았다(삼성전자 억원 · 대부분 백만원 · 천원).
원장: 풍경 캐시(.cache/landscape/{code}.json) rows[].rev — 연결 연간 매출(원). TTM 줄은 뺀다.

검산 관문(도구/제품믹스_점검.py): 표 금액 합계 × 단위 가 원장 매출 ±10% 안인 회사-연도만 숫자를 쓴다.
  단위는 회사마다 하나(company_unit): 해마다 10의 거듭제곱(원 · 천원 · 백만원 · 억원) 중 원장에 가장 가까운 것을 고르고, 맞은 해들의 가장 흔한 단위로 다시 잰다.
  해마다 따로 고르면 1% 조각 표 · 비율 칸이 큰 단위로 우연히 맞았다(리뷰 2026-10-17 — 십억원으로만 맞은 해가 전부 가짜라 십억원은 뺐다).
  금액 비중이 표의 비율 칸과 5%p 넘게 어긋나면 탈락 · 금액 칸에 비율이 든 표는 비율표로 · 소계 후보 줄은 원장으로 확인한 뒤에만 지운다.
  표가 일부 부문만 적었거나(별도 기준 · 주력만) 내부거래를 안 뺀 해는 관문에서 떨어진다 — 그런 해는 비중(%)만 보인다.
같은 사업보고서에 원장과 표가 함께 실리므로 그 해 숫자는 접수일에 이미 알 수 있던 값이다(시점 문제 없음).
부문 재편 · 이름 바뀜이 있으면 이어지지 않는다 — 열쇠가 바뀐 품목은 '새로 생김 · 사라짐'으로 보인다(기여도에 넣지 않는다).

이해 도구다 — 신호 · 점수가 아니다. 검증 전에 필터나 점수에 넣지 않는다.
서버(서버._mix_of — 밸류체인 응답의 mix)와 점검 도구가 이 파일을 같이 쓴다. 규칙을 바꾸면 MIX_V 를 올린다.
"""
import os, re, json, math

MIX_V = 3                # 3: 띄어 쓴 칸('연 결 조 정' · '총 매 출 액')도 공백을 지우고 맞춘다 · 순매출 · 내부매출 줄 (2026-10-19 밸류체인 리뷰). 2: 회사 단위 고정 · 십억원 뺌 · 비율 칸 대조 · 금액 칸에 든 비율표 · 소계 지우기는 원장으로 확인 · 조정 줄 정규식 좁힘 · use 칸 조정 · 금액 해 비중 = 금액만 (2026-10-17 리뷰)
GATE = 0.60              # 단위를 고른 뒤 ±10% 통과율이 이만큼은 돼야 전 종목 시계열로 연다(점검.json gate)
TOL = 0.10
# 십억원은 뺀다 — 리뷰(2026-10-17)에서 십억원으로만 맞은 10건이 전부 비율 칸 · 1% 조각 표가 우연히 맞은 것이었다
UNITS = [(1.0, "원"), (1e3, "천원"), (1e6, "백만원"), (1e8, "억원")]
# 조정 줄 — 문맥이 붙은 말만(맨 '상계' · '제거' 는 '가상계좌' · '공기제거기' · '노폐물 제거' 같은 제품 이름에 걸렸다)
ADJ = re.compile(r"연결\s*조정|내부\s*(?:거래|매출)|부문\s*간\s*(?:내부\s*)?거래|조정\s*및\s*제거|(?:내부|채권\s*채무|매출)\s*상계|consolidat|eliminat", re.I)
USE_ADJ = re.compile(r"연결\s*조정|내부\s*(?:거래|매출)(?:액)?\s*제거|조정\s*및\s*제거|부문\s*간", re.I)   # 용도 칸은 고정 문구만
OTHER = re.compile(r"^\s*(?:기\s*타|그\s*밖)", re.I)
PCT_TOL = 5.0            # 금액으로 낸 비중과 표의 비율 칸이 이만큼(%p, 중앙값) 넘게 어긋나면 금액 칸을 못 믿는다


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def ledger_revenue(code, cache):
    """원장 연간 매출 {year: 원} — 풍경 캐시 rows(연결). TTM 줄 · 0 이하는 뺀다. 캐시가 없으면 {}."""
    try:
        d = json.load(open(os.path.join(cache, "landscape", code + ".json"), encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for r in d.get("rows") or []:
        v = _num(r.get("rev"))
        if r.get("ttm") or not v or v <= 0 or not r.get("year"):
            continue
        out[int(r["year"])] = v
    return out


def _norm(s):
    return re.sub(r"[\s·・,.()\[\]（）/\\\-_'\"]+", "", (s or "")).lower()


ADJ_C = re.compile(r"연결조정|내부(?:거래|매출)|부문간(?:내부)?거래|조정및제거|(?:내부|채권채무|매출)상계|consolidat|eliminat", re.I)
USE_ADJ_C = re.compile(r"연결조정|내부(?:거래|매출)(?:액)?제거|조정및제거|부문간", re.I)


def _c(v):
    return re.sub(r"\s+", "", str(v or ""))


def is_adj(p):
    """조정 · 내부거래 줄 — 칸마다 공백을 지우고 맞춘다(띄어 쓴 '연 결 조 정', 리뷰 2026-10-19)."""
    return bool(any(ADJ_C.search(_c(p.get(k))) for k in ("segment", "kind", "item")) or USE_ADJ_C.search(_c(p.get("use"))))


def item_key(p):
    """품목 열쇠 — 부문 + 품목(공백 · 기호 뺌). 품목이 비면 부문만, 둘 다 비면 매출유형."""
    seg, it = _norm(p.get("segment")), _norm(p.get("item"))
    return (seg + "|" + it) if (seg or it) else _norm(p.get("kind"))


def label_of(p):
    seg, it = (p.get("segment") or "").strip(), (p.get("item") or "").strip()
    if seg and it and _norm(seg) != _norm(it):
        return seg + " · " + it
    return seg or it or (p.get("kind") or "").strip() or "?"


TOTAL = re.compile(r"(?:매출|제품|상품|부문|사업)?\s*(?:총\s*계|합\s*계|소\s*계|매출\s*계|^\s*계\s*$|^\s*합\s*$)|^\s*total\s*$|sub\s*total", re.I)
TOTAL_C = re.compile(r"총계|합계|소계|매출계$|^계$|^합$|^total$|subtotal|^총매출|^순매출", re.I)       # 공백을 지운 칸에
BLEED = re.compile(r"^\s*제\s*\d+\s*기|^\s*(?:품\s*목|구\s*분|기\s*간|단\s*위)\s*$")


def clean(prods):
    """표 뒤처리 → (줄, 소계 후보 번호 집합). 밸류체인.products 가 넘긴 줄에서 합계 줄과 옆 표가 흘러든 줄을 뺀다.
    1) 기수 · '품목' · '구분' 머리가 칸에 나오면(세아제강지주 '품목 / 제65기' — 가격표가 이어 붙음) 그 줄부터 버린다
    2) 칸 어디든 '매출총계 · 합계 · 소계 · 매출계'가 든 줄을 뺀다(메카로 '매출총계', 유니드 '제품매출계')
    3) 금액이 바로 앞 연속 둘 이상 줄의 합과 1.5% 안에서 같으면 소계 '후보'(한세실업 '원단 1,918,829 (100%)') — 지우지는 않는다.
       진짜 최대 품목도 걸릴 수 있어(S-Oil 경유, 서흥 건강기능식품) check_year 가 원장 매출로 둘 중 맞는 쪽을 고른다. 조정 줄은 후보가 아니다"""
    out, cands = [], set()
    for p in prods or []:
        cells = [str(p.get(k) or "") for k in ("segment", "kind", "item", "use")]
        if any(BLEED.search(c) for c in cells[:3]):
            break
        if any(TOTAL.search(c) or TOTAL_C.search(_c(c)) for c in cells):
            continue
        a = _num(p.get("amt"))
        if a is not None and a > 0 and not is_adj(p):
            s, k = 0.0, 0
            for j in range(len(out) - 1, -1, -1):
                if j in cands or is_adj(out[j]):
                    continue
                b = _num(out[j].get("amt"))
                if b is None:
                    break
                s += b
                k += 1
                if k >= 2 and abs(s - a) <= a * 0.015:
                    cands.add(len(out))
                    break
        out.append(p)
    return out, cands


def _signed(p):
    a = _num(p.get("amt"))
    if a is None:
        return None
    return -abs(a) if is_adj(p) else a     # 조정 줄은 빼는 금액(괄호 음수가 표 읽기에서 부호를 잃은 해가 많다 — 피엔티 '내부거래 제거')


def _pct_gap(rows):
    """금액으로 낸 비중과 표의 비율 칸 차이(중앙값, %p) — 금액 · 비율이 둘 다 있는 줄 2개 이상일 때만. 없으면 None."""
    pos = sum(_num(p.get("amt")) for p in rows if not is_adj(p) and (_num(p.get("amt")) or 0) > 0)
    d = sorted(abs(_num(p.get("amt")) / pos * 100 - _num(p.get("pct"))) for p in rows
               if pos > 0 and not is_adj(p) and (_num(p.get("amt")) or 0) > 0 and _num(p.get("pct")) is not None)
    return d[len(d) // 2] if len(d) >= 2 else None


def check_year(prods, rev, unit=None):
    """한 해 표의 검산. unit = 회사 단위(원 배수)를 주면 그것으로만 잰다(series 가 회사 단위를 정한 뒤 다시 부른다).
    금액이 하나도 없거나 금액 칸이 비율표(모두 100 이하 · 합 100±5)면 kind='pct'(비율 합 100±5 → pct_ok). 쓸 것이 없으면 None.
    돌려주는 것: kind, unit · unit_name, ratio(= 합계 × 단위 ÷ 원장), raw_ratio(백만원으로 본 비율), pass5 · pass10, keys, rev, rows(고른 줄), why."""
    rows, cands = clean(prods)
    if not rows:
        return None
    amts = [_num(p.get("amt")) for p in rows]
    have = [a for a in amts if a is not None]
    as_pct = len(have) >= 2 and all(0 <= a <= 100 for a in have) and abs(sum(have) - 100) <= 5
    if have and not as_pct:
        variants = [[p for i, p in enumerate(rows) if i not in cands]]
        if cands:
            variants.append(rows)
        best = None
        for vr in variants:
            s = sum(_signed(p) for p in vr if _signed(p) is not None)
            ck = {"kind": "amt", "sum": s, "rev": rev, "rows": vr, "unit": None, "unit_name": None,
                  "ratio": None, "raw_ratio": None, "pass5": False, "pass10": False, "why": None}
            if rev and s > 0:
                u, nm = next(((u_, n_) for u_, n_ in UNITS if u_ == unit), None) if unit else \
                    min(UNITS, key=lambda x: abs(math.log(s * x[0] / rev)))
                r = s * u / rev
                ck.update(unit=u, unit_name=nm, ratio=round(r, 4), raw_ratio=round(s * 1e6 / rev, 4),
                          pass5=abs(r - 1) <= .05, pass10=abs(r - 1) <= TOL)
            if best is None or (ck["ratio"] is not None and (best["ratio"] is None or abs(ck["ratio"] - 1) < abs(best["ratio"] - 1))):
                best = ck
        if not rev:                       # 원장 없이는 소계 후보를 지우지 않는다
            best = dict(best, rows=rows, sum=sum(_signed(p) for p in rows if _signed(p) is not None))
        g = _pct_gap(best["rows"])
        if best["pass10"] and g is not None and g > PCT_TOL:
            best.update(pass5=False, pass10=False, why="금액으로 낸 비중이 표의 비율 칸과 %.0f%%p 어긋남" % g)
        best["keys"] = [item_key(p) for p in best["rows"] if not is_adj(p) and item_key(p)]
        return best
    src = [(p, (_num(p.get("amt")) if as_pct else _num(p.get("pct")))) for p in rows if not is_adj(p)]
    pcts = [x for _, x in src if x is not None]
    if not pcts:
        return None
    sp = sum(pcts)
    return {"kind": "pct", "sum": sp, "rev": rev, "rows": rows, "as_pct": as_pct,
            "keys": [item_key(p) for p in rows if not is_adj(p) and item_key(p)], "unit": None, "unit_name": None,
            "ratio": None, "raw_ratio": None, "pass5": abs(sp - 100) <= 2.5, "pass10": abs(sp - 100) <= 5,
            "why": "금액 칸에 비율이 들었다" if as_pct else None}


def company_unit(vc, rev):
    """회사 단위 — 해마다 따로 골라 원장과 맞은 해들의 가장 흔한 단위(같으면 많은 해 · 큰 단위). 맞은 해가 없으면 None.
    해마다 따로 고르면 단위가 다른 해끼리 기여도를 이어 버리고, 1% 조각 표가 큰 단위로 우연히 맞는다(리뷰 2026-10-17)."""
    from collections import Counter
    c = Counter()
    for y, v in (vc.get("years") or {}).items():
        if not re.fullmatch(r"\d{4}", y):
            continue
        ck = check_year(v.get("products") or [], rev.get(int(y)))
        if ck and ck["kind"] == "amt" and ck["pass10"]:
            c[ck["unit"]] += 1
    if not c:
        return None
    return max(c.items(), key=lambda kv: (kv[1], kv[0]))[0]


def series(vc, rev):
    """회사 하나의 연간 제품 믹스 시계열 — 회사 단위로 고정해 잰다.
    years: [{year, pass(금액표 · 원장 ±10%), pct_ok(비율표 합 100±5 | None), kind, unit_name, ratio, total, rev, items:[{key, label, amt, share}], keys, why}]
    share: 금액표 해 = 그 해 양수 금액 합 대비(금액 없는 줄의 비율 칸은 섞지 않는다) · 비율표 해 = 표의 비율. 조정 줄은 items 에서 뺀다(합계 검산에는 넣었다)."""
    unit = company_unit(vc, rev)
    out = []
    for y, v in sorted((vc.get("years") or {}).items()):
        if not re.fullmatch(r"\d{4}", y):
            continue
        ck = check_year(v.get("products") or [], rev.get(int(y)), unit=unit) if unit else check_year(v.get("products") or [], rev.get(int(y)))
        if ck is None:
            continue
        ok = bool(ck["pass10"] and ck["kind"] == "amt" and unit)
        rows = ck["rows"]
        amt_kind = ck["kind"] == "amt"
        acc = {}
        order = []
        for p in rows:
            if is_adj(p):
                continue
            k = item_key(p)
            if not k:
                continue
            if k not in acc:
                acc[k] = {"key": k, "label": label_of(p), "raw": None, "pct": None,
                          "other": bool(OTHER.match(p.get("item") or p.get("segment") or ""))}
                order.append(k)
            it = acc[k]
            a = _num(p.get("amt"))
            if amt_kind:
                if a is not None:
                    it["raw"] = (it["raw"] or 0) + a
            else:
                x = a if ck.get("as_pct") else _num(p.get("pct"))
                if x is not None:
                    it["pct"] = (it["pct"] or 0) + x
        pos = sum(i["raw"] for i in acc.values() if i["raw"] is not None and i["raw"] > 0)
        items = []
        for k in order:
            i = acc[k]
            sh = (i["raw"] / pos * 100) if (amt_kind and i["raw"] is not None and pos > 0) else (i["pct"] if not amt_kind else None)
            items.append({"key": k, "label": i["label"], "amt": (i["raw"] * unit) if (ok and i["raw"] is not None) else None,
                          "share": round(sh, 2) if sh is not None else None, "other": i["other"]})
        out.append({"year": int(y), "pass": ok, "pct_ok": (ck["pass10"] if ck["kind"] == "pct" else None), "kind": ck["kind"],
                    "unit_name": ck["unit_name"] if amt_kind else None, "ratio": ck["ratio"] if amt_kind else None,
                    "total": (ck["sum"] * unit) if ok else None, "rev": ck["rev"], "rcept": v.get("rcept"), "items": items,
                    "keys": ck["keys"], "why": ck.get("why")})
    return out


def contribution(a, b):
    """두 해(a → b, 둘 다 검산 통과 · 금액표)의 기여도. 같은 열쇠 품목만 잇는다.
    contrib = 품목 증가분 ÷ 이어진 품목 증가분 합(성장의 몇 %를 끌었나 — 합이 0 근처면 None), share_pp = 비중 변화(%p).
    new · gone = 한쪽 해에만 있는 열쇠(이름 바뀜일 수 있다)."""
    if not (a and b and a["pass"] and b["pass"] and a["kind"] == "amt" and b["kind"] == "amt"):
        return None
    A = {i["key"]: i for i in a["items"] if i["amt"] is not None}
    B = {i["key"]: i for i in b["items"] if i["amt"] is not None}
    both = [k for k in B if k in A]
    d_tot = sum(B[k]["amt"] - A[k]["amt"] for k in both)
    gross = sum(abs(B[k]["amt"] - A[k]["amt"]) for k in both)
    rows = []
    for k in both:
        dlt = B[k]["amt"] - A[k]["amt"]
        rows.append({"key": k, "label": B[k]["label"], "a": A[k]["amt"], "b": B[k]["amt"], "delta": dlt,
                     "yoy": (dlt / A[k]["amt"] * 100) if A[k]["amt"] > 0 else None,
                     "contrib": (dlt / d_tot * 100) if (gross and abs(d_tot) >= gross * 0.05) else None,
                     "share_pp": (B[k]["share"] - A[k]["share"]) if (B[k]["share"] is not None and A[k]["share"] is not None) else None})
    rows.sort(key=lambda r: -abs(r["delta"]))
    matched = (sum(B[k]["amt"] for k in both) / sum(i["amt"] for i in B.values())) if B and sum(i["amt"] for i in B.values()) > 0 else 0
    return {"a": a["year"], "b": b["year"], "d_total": d_tot, "rows": rows,
            "new": [B[k]["label"] for k in B if k not in A], "gone": [A[k]["label"] for k in A if k not in B],
            "matched": round(matched, 3)}


def view(vc, rev):
    """화면용 — 시계열, 마지막 두 통과 해의 기여도, 검산 요약. 표가 없으면 None."""
    ys = series(vc, rev)
    if not ys:
        return None
    ok = [y for y in ys if y["pass"] and y["kind"] == "amt"]
    con = None
    for i in range(len(ok) - 1, 0, -1):
        if ok[i]["year"] - ok[i - 1]["year"] == 1:
            con = contribution(ok[i - 1], ok[i])
            break
    return {"v": MIX_V, "years": ys, "contrib": con, "n_years": len(ys), "n_pass": len(ok),
            "units": sorted({y["unit_name"] for y in ok if y["unit_name"]})}
