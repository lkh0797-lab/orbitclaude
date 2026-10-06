# -*- coding: utf-8 -*-
"""
기술 신호 — 저평가V2(서버 value2_view)와 도구/저평가V2_백테스트.py 가 같이 쓴다 (2026-10-03).
슈퍼개미가 흔히 쓰는 차트 지침을 숫자로 고정한 것(맞추지 않았다). 봉 = 재무.fetch_ohlcv 의 {날짜: [시가, 고가, 저가, 종가, 거래량]}.

차트 셋업(2026-10-07) — 아래 setup() · PRESETS. 오닐(컵위드핸들 · 평평한 바닥 · 박스 돌파 · RS), 미너비니(추세 템플릿 · VCP),
와인스타인(1→2단계 바닥 탈출)의 정의를 책에 적힌 문턱 그대로 숫자로 옮겼다(맞추지 않았다). 서버(저평가V2)와
도구/차트셋업_백테스트.py 가 같은 함수를 부른다 — 화면과 검증의 정의가 어긋나지 않게.
"""
import bisect


def bars_from(d, min_n=260):
    """{날짜: [o, h, l, c, v]} → 배열 묶음. 봉이 모자라면 None."""
    if not d:
        return None
    ks = sorted(d)
    if len(ks) < min_n:
        return None
    return {"d": [int(k) for k in ks], "o": [d[k][0] for k in ks], "h": [d[k][1] for k in ks], "l": [d[k][2] for k in ks],
            "c": [d[k][3] for k in ks], "v": [d[k][4] for k in ks]}


def _ma(a, i, n):
    return sum(a[i - n + 1:i + 1]) / n if i + 1 >= n else None


def _avg(a, i0, i1):
    seg = a[max(0, i0):i1]
    return sum(seg) / len(seg) if seg else None


def tech(B, i):
    """i 번째 봉까지로 본 신호들. B = {"o","h","l","c","v"} 리스트. 250봉(1년)은 있어야 잰다."""
    if i < 250:
        return None
    o, h, l, c, v = B["o"], B["h"], B["l"], B["c"], B["v"]
    ma5, ma20, ma60, ma120 = _ma(c, i, 5), _ma(c, i, 20), _ma(c, i, 60), _ma(c, i, 120)
    ma20_5, ma20_10, ma60_10 = _ma(c, i - 5, 20), _ma(c, i - 10, 20), _ma(c, i - 10, 60)
    ma120_20 = _ma(c, i - 20, 120)
    hi52, lo52 = max(h[i - 249:i + 1]), min(l[i - 249:i + 1])
    v20, v120 = _avg(v, i - 19, i + 1), _avg(v, i - 119, i + 1)
    tv20 = _avg([c[k] * v[k] for k in range(i - 19, i + 1)], 0, 20)
    s = {}

    def spike(k, mult=3.0):
        base = _avg(v, k - 60, k)
        return base and v[k] >= mult * base

    # 바닥 횡보 뒤 대량 양봉 — 최근 20봉 안에 60봉 평균의 3배 넘는 양봉. 그 앞 60봉은 고저 30% 안 박스였고 박스 바닥이 52주 저점 15% 안.
    # 지금 종가가 그 양봉의 시가 위(양봉을 깨지 않았다)
    s["box_spike"] = False
    for k in range(i - 19, i + 1):
        if spike(k) and c[k] > o[k]:
            bh, bl = max(h[k - 60:k]), min(l[k - 60:k])
            lo52k = min(l[max(0, k - 249):k + 1])
            if bl > 0 and bh / bl - 1 <= 0.30 and bl <= lo52k * 1.15 and c[i] >= o[k]:
                s["box_spike"] = True
                break
    # 바닥 대량 아래꼬리 — 최근 60봉 안, 3배 거래량 · 그날 저가가 52주 저점 5% 안 · 종가가 그날 고저의 위 40% 안 · 그 뒤 그 저가를 안 깼다
    s["cap_tail"] = False
    for k in range(i - 59, i + 1):
        rng = h[k] - l[k]
        if rng > 0 and spike(k) and l[k] <= min(l[max(0, k - 249):k + 1]) * 1.05 and (c[k] - l[k]) / rng >= 0.6 \
                and min(l[k:i + 1]) >= l[k]:
            s["cap_tail"] = True
            break
    # 거래 말라붙은 횡보 — 20일 평균 거래량이 120일 평균의 60% 아래 · 최근 20봉 고저 15% 안
    s["dry_box"] = bool(v120 and v20 / v120 <= 0.6 and min(l[i - 19:i + 1]) > 0 and max(h[i - 19:i + 1]) / min(l[i - 19:i + 1]) - 1 <= 0.15)
    # 20일선 회복 — 지금 종가가 20일선 위, 최근 5봉 안에 20일선 아래였던 날이 있고, 20일선이 5봉 전보다 내려가지 않았다
    s["ma20_back"] = bool(c[i] > ma20 and any(c[k] < _ma(c, k, 20) for k in range(i - 5, i)) and ma20 >= ma20_5)
    # 골든크로스 — 20일선이 60일선 위, 10봉 전엔 아래였다
    s["golden"] = bool(ma20 > ma60 and ma20_10 is not None and ma60_10 is not None and ma20_10 <= ma60_10)
    # 정배열 시작 — 종가 > 5일 > 20일 > 60일
    s["aligned"] = bool(c[i] > ma5 > ma20 > ma60)
    # 저점 높이기(2차 바닥) — 최근 20봉 저점이 그 앞 60봉 저점보다 2%↑ 높고, 그 앞 저점은 52주 저점 10% 안
    p_lo = min(l[i - 79:i - 19])
    s["higher_low"] = bool(min(l[i - 19:i + 1]) > p_lo * 1.02 and p_lo <= lo52 * 1.10)
    # 120일선 위 — 하락 추세가 끝났나(120일선도 20봉 전보다 오르는 중)
    s["above120"] = bool(c[i] > ma120 and ma120_20 is not None and ma120 >= ma120_20)
    # 나쁜 자리 — 고점 대량 음봉(물량 넘김): 최근 120봉 안, 3배 거래량 · 52주 고점 10% 안 · 음봉이거나 윗꼬리가 고저의 절반↑
    s["top_dump"] = False
    for k in range(i - 119, i + 1):
        rng = h[k] - l[k]
        if rng > 0 and spike(k) and h[k] >= max(h[max(0, k - 249):k + 1]) * 0.9 and \
                (c[k] < o[k] or (h[k] - max(o[k], c[k])) / rng >= 0.5):
            s["top_dump"] = True
            break
    # 역배열 하락 중 — 종가 < 20일 < 60일 < 120일, 20일선이 내려가는 중
    s["down_aligned"] = bool(c[i] < ma20 < ma60 < ma120 and ma20 < ma20_5)
    # 거래대금 부족 — 20일 평균 하루 3억 미만(드나들기 어렵다)
    s["thin"] = bool(tv20 is not None and tv20 < 3e8)
    s["_tv20"] = tv20
    s["_v20_120"] = v20 / v120 if v120 else None
    s["_from_lo"] = (c[i] / lo52 - 1) * 100 if lo52 else None
    return s


SIGS = [   # (키, 이름, 좋은 자리 +1 / 나쁜 자리 −1)
    ("box_spike", "바닥 횡보 뒤 대량 양봉", 1),
    ("cap_tail", "바닥 대량 아래꼬리(투매 받아냄)", 1),
    ("dry_box", "거래 말라붙은 횡보(매도 소진)", 1),
    ("ma20_back", "20일선 회복", 1),
    ("golden", "골든크로스(20일 > 60일)", 1),
    ("aligned", "정배열 시작(종가 > 5 > 20 > 60)", 1),
    ("higher_low", "저점 높이기(2차 바닥)", 1),
    ("above120", "120일선 위(하락 추세 끝)", 1),
    ("top_dump", "고점 대량 음봉(물량 넘김)", -1),
    ("down_aligned", "역배열 하락 중", -1),
    ("thin", "거래대금 적음(하루 3억 미만)", 0),       # 참고 — 과거엔 오히려 더 올랐다(소형주 효과). 드나들기 어려운 것은 사실이라 표시만
]


# ================================================================ 차트 셋업 (2026-10-07)
# 한 종목의 i 번째 봉까지로 본 패턴 · 지표(setup) → 종목 사이 순위(RS) → 셋업 규칙(PRESETS).
# 거래일 기준: 1주 = 5봉, 1달 = 21봉, 1년 = 252봉. 미래 봉은 쓰지 않는다(고점 후보는 좌우 10봉으로 확인 — 쓰는 곳에서 i−35 앞만).

def prep(B):
    """누적합(이동평균 · 거래량 평균을 O(1)로)과 고점 후보(좌우 10봉 안 최고)를 한 번만."""
    if "_cs" in B:
        return B
    cs, vs, ts = [0.0], [0.0], [0.0]
    for c_, v_ in zip(B["c"], B["v"]):
        cs.append(cs[-1] + c_)
        vs.append(vs[-1] + v_)
        ts.append(ts[-1] + c_ * v_)
    B["_cs"], B["_vs"], B["_ts"] = cs, vs, ts
    h, n, w = B["h"], len(B["h"]), 10
    B["_ph"] = [k for k in range(w, n - w) if h[k] >= max(h[k - w:k + w + 1])]
    return B


def ma(B, i, n):
    """i 번째 봉까지 n봉 종가 평균."""
    return (B["_cs"][i + 1] - B["_cs"][i + 1 - n]) / n if 0 <= i and i + 1 >= n else None


def vma(B, i, n):
    """i 번째 봉 '앞' n봉 거래량 평균(그날은 빼고 — 그날 거래량을 견줄 바탕)."""
    return (B["_vs"][i] - B["_vs"][i - n]) / n if i >= n else None


def tvma(B, i, n):
    """i 번째 봉까지 n봉 하루 거래대금 평균(원)."""
    return (B["_ts"][i + 1] - B["_ts"][i + 1 - n]) / n if i + 1 >= n else None


def _roc(c, i, n):
    return (c[i] / c[i - n] - 1) * 100 if i >= n and c[i - n] > 0 else None


def rs_raw(B, i):
    """IBD 식 상대강도 원점수 — 최근 3개월에 두 배 무게: 2×(63봉) + 126봉 + 189봉 + 252봉 수익률. 종목 사이 순위는 rank99."""
    c = B["c"]
    r = [_roc(c, i, n) for n in (63, 126, 189, 252)]
    return None if any(x is None for x in r) else 2 * r[0] + r[1] + r[2] + r[3]


def rank99(vals):
    """{코드: 원점수} → {코드: 1~99} 백분위(IBD RS 처럼 99가 가장 강하다)."""
    ks = sorted((k for k, v in vals.items() if v is not None), key=lambda k: vals[k])
    n = len(ks)
    return {k: (int(round(1 + 98 * j / (n - 1))) if n > 1 else 50) for j, k in enumerate(ks)}


def _last_idx(seg, v):
    return len(seg) - 1 - seg[::-1].index(v)


def trend_template(B, i):
    """미너비니 추세 템플릿 8개 중 가격으로 재는 7개(8번째 RS ≥ 70 은 순위를 낸 뒤 규칙에서). [참/거짓 7개]."""
    if i < 252 + 21:
        return None
    c, h, l = B["c"][i], B["h"], B["l"]
    m50, m150, m200, m200_1m = ma(B, i, 50), ma(B, i, 150), ma(B, i, 200), ma(B, i - 21, 200)
    hi52, lo52 = max(h[i - 251:i + 1]), min(l[i - 251:i + 1])
    return [c > m150 and c > m200,            # 1 종가 > 150일 · 200일선
            m150 > m200,                      # 2 150일선 > 200일선
            m200 > m200_1m,                   # 3 200일선이 한 달 넘게 오르는 중
            m50 > m150 and m50 > m200,        # 4 50일선 > 150 · 200일선
            c > m50,                          # 5 종가 > 50일선
            c >= 1.30 * lo52,                 # 6 52주 저점보다 30%↑
            c >= 0.75 * hi52]                 # 7 52주 고점에서 25% 안


def cup_handle(B, i):
    """오닐 컵위드핸들. 앞선 상승 30%↑ → 왼쪽 고점 → 12~35% 조정(U자: 내려가고 올라오는 데 각 10봉↑, 바닥 근처에 머문 날 4봉↑)
    → 오른쪽이 왼쪽 고점의 85~115%까지 회복(컵 7~65주) → 손잡이 1~8주 · 깊이 15% 안 · 컵 위쪽 절반에서.
    피봇(돌파가) = 손잡이 고점. 지금 종가가 피봇 −10% ~ +5%(사는 자리 — 5% 넘게 오르면 늦었다)."""
    if i < 200:
        return None
    h, l, c, v, d = B["h"], B["l"], B["c"], B["v"], B["d"]
    ph = B["_ph"]
    j = bisect.bisect_right(ph, i - 35)
    for lp in reversed(ph[:j]):
        if lp < i - 325:
            break
        if lp < 60:
            continue
        L = h[lp]
        if L < min(l[max(0, lp - 130):lp]) * 1.30:          # 앞선 상승 30%↑
            continue
        sl = l[lp + 1:i - 4]
        if len(sl) < 25:
            continue
        bot = min(sl)
        b = lp + 1 + sl.index(bot)
        depth = 1 - bot / L
        if not 0.12 <= depth <= 0.35:
            continue
        if max(h[lp:b + 1]) > L * 1.001:                    # 왼쪽 고점이 컵의 입술이어야
            continue
        sh = h[b:i - 4]
        R = max(sh)
        r = b + sh.index(R)
        rec = R / L
        if not 0.85 <= rec <= 1.15 or b - lp < 10 or r - b < 10 or r - lp < 35:
            continue
        if sum(1 for x in c[lp:r + 1] if x <= bot + 0.25 * (L - bot)) < 4:   # V자 반등이 아니라 U자 — 바닥 근처에 머문 날
            continue
        hlen = i - r
        if not 5 <= hlen <= 40:
            continue
        hl = min(l[r + 1:i + 1])
        hd = 1 - hl / R
        if not 0 < hd <= 0.15 or hl < bot + 0.5 * (L - bot):  # 손잡이 깊이 15% 안 · 컵 위쪽 절반
            continue
        gap = (c[i] / R - 1) * 100
        if not -10 <= gap <= 5:
            continue
        v50 = vma(B, r, 50)
        hv = (B["_vs"][i + 1] - B["_vs"][r + 1]) / hlen
        return {"depth": depth * 100, "rec": rec * 100, "pivot": R, "gap": gap, "hdepth": hd * 100, "weeks": (r - lp) / 5,
                "hweeks": hlen / 5, "hvol": hv / v50 if v50 else None,
                "pts": [[str(d[lp]), L, "왼쪽 고점"], [str(d[b]), bot, "컵 바닥"], [str(d[r]), R, "손잡이 시작"]], "line": R}
    return None


def vcp(B, i, thr=0.05):
    """미너비니 VCP — 최근 6달 안 고점에서 시작한 바닥에서 흔들림(고점→저점 폭)이 2~6번, 앞보다 커지지 않고(10% 여유)
    첫 흔들림 8~40% · 마지막 10% 안이면서 첫 흔들림의 60% 이하 · 저점은 높아지거나 같고 · 최근 10봉 거래량이 50봉 평균의
    85% 이하(마름). 피봇 = 마지막 흔들림이 시작한 고점. 지금 종가가 피봇 −7% ~ +5%. 흔들림 마디는 5% 되돌림으로 나눈다
    (지그재그 — 3.5%로 나누면 잔물결이 마디로 잡혀 '점점 작아짐'이 깨진다)."""
    if i < 160:
        return None
    h, l, c, d = B["h"], B["l"], B["c"], B["d"]
    s = i - 129
    seg = h[s:i - 4]
    H0 = max(seg)
    p0 = s + seg.index(H0)
    if i - p0 < 15:
        return None
    piv = [(p0, "H", H0)]
    want, ek, ev = "L", None, None
    for k in range(p0 + 1, i + 1):
        if want == "L":
            if ev is None or l[k] < ev:
                ek, ev = k, l[k]
            elif h[k] >= ev * (1 + thr):
                piv.append((ek, "L", ev))
                want, ek, ev = "H", k, h[k]
        else:
            if h[k] > ev:
                ek, ev = k, h[k]
            elif l[k] <= ev * (1 - thr):
                piv.append((ek, "H", ev))
                want, ek, ev = "L", k, l[k]
    deps, lows, last_h = [], [], H0
    for a, b_ in zip(piv, piv[1:]):
        if a[1] == "H" and b_[1] == "L":
            deps.append(1 - b_[2] / a[2])
            lows.append(b_[2])
            last_h = a[2]
        elif a[1] == "L" and b_[1] == "H":
            last_h = b_[2]
    if want == "L" and ev is not None and piv[-1][1] == "H":          # 지금 진행 중인 흔들림
        deps.append(1 - ev / piv[-1][2])
        lows.append(ev)
        last_h = piv[-1][2]
    if not 2 <= len(deps) <= 6 or not 0.08 <= deps[0] <= 0.40 or deps[-1] > 0.10 or deps[-1] > deps[0] * 0.6:
        return None
    if any(deps[k] > deps[k - 1] * 1.1 for k in range(1, len(deps))):
        return None
    if any(lows[k] < lows[k - 1] * 0.98 for k in range(1, len(lows))):
        return None
    v10 = (B["_vs"][i + 1] - B["_vs"][i - 9]) / 10
    v50 = vma(B, i + 1, 50)
    if not v50 or v10 / v50 > 0.85:
        return None
    gap = (c[i] / last_h - 1) * 100
    if not -7 <= gap <= 5:
        return None
    return {"n": len(deps), "deps": [round(x * 100, 1) for x in deps], "last": deps[-1] * 100, "pivot": last_h, "gap": gap,
            "vr": v10 / v50, "weeks": (i - p0) / 5, "pts": [[str(d[k]), val, t] for k, t, val in piv], "line": last_h}


def flat_base(B, i):
    """오닐 평평한 바닥 — 20% 넘게 오른 뒤 5~13주 동안 고저 15% 안에서 쉼. 바닥 고점이 52주 고점의 85%↑,
    지금 종가가 바닥 고점(피봇) −5% 안."""
    if i < 260:                                   # 52주(252봉)를 다 볼 수 있어야 — 모자라면 음수 첨자가 끝에서 감겨 미래 봉을 읽는다
        return None
    h, l, c, d = B["h"], B["l"], B["c"], B["d"]
    for n in range(65, 24, -1):
        s = i - n + 1
        hi, lo = max(h[s:i + 1]), min(l[s:i + 1])
        if lo > 0 and hi / lo - 1 <= 0.15:
            break
    else:
        return None
    if min(l[max(0, s - 120):s] or [lo]) * 1.20 > hi:          # 앞선 상승 20%↑
        return None
    if hi < 0.85 * max(h[i - 251:i + 1]):
        return None
    gap = (c[i] / hi - 1) * 100
    if gap < -5:
        return None
    return {"weeks": n / 5, "depth": (1 - lo / hi) * 100, "pivot": hi, "gap": gap, "line": hi,
            "pts": [[str(d[s]), hi, "바닥 시작"]]}


def pullback(B, i):
    """강세 눌림(숨 고르기) — 3~30봉 전에 52주 신고가, 그 고점이 앞 60봉 저점보다 25%↑(급등 뒤), 지금 고점에서 4~15% 쉼,
    종가가 20일선이나 50일선 3% 안(50일선 −3% 아래로는 안 깼다), 고점 뒤 거래량이 그 전 50봉 평균의 90% 이하."""
    if i < 260:
        return None
    h, l, c, d = B["h"], B["l"], B["c"], B["d"]
    seg = h[i - 251:i + 1]
    hi = max(seg)
    hk = i - 251 + _last_idx(seg, hi)
    age = i - hk
    if not 3 <= age <= 30 or hk < 60 or hi < min(l[hk - 60:hk]) * 1.25:
        return None
    p = (1 - c[i] / hi) * 100
    m20, m50 = ma(B, i, 20), ma(B, i, 50)
    if not 4 <= p <= 15 or c[i] < m50 * 0.97:
        return None
    n20, n50 = abs(c[i] / m20 - 1) <= 0.03, abs(c[i] / m50 - 1) <= 0.03
    if not (n20 or n50):
        return None
    v0 = vma(B, hk, 50)
    vr = (B["_vs"][i + 1] - B["_vs"][hk + 1]) / age / v0 if v0 else None
    if vr is None or vr > 0.9:
        return None
    return {"pull": p, "line_n": 20 if n20 else 50, "age": age, "vr": vr, "pivot": hi, "gap": -p, "line": hi,
            "pts": [[str(d[hk]), hi, "52주 신고가"]]}


def breakout(B, i):
    """박스 돌파 — 최근 3봉 안에 종가가 앞 60봉 고점을 넘고, 그날 거래량이 50봉 평균의 1.5배↑. 그 박스는 고저 35% 안이고
    박스 고점이 52주 고점의 85%↑(하락 중 반등이 아니라 고점 근처 돌파). 지금 종가가 돌파가 −2% ~ +7%."""
    if i < 260:
        return None
    h, l, c, v, d = B["h"], B["l"], B["c"], B["v"], B["d"]
    for k in range(i, i - 3, -1):                 # 가장 최근의 '조건을 다 갖춘' 돌파일 — 돌파 다음 날 보통 거래량으로 더 오른 날은 건너뛴다
        bh, bl = max(h[k - 60:k]), min(l[k - 60:k])
        if c[k] <= bh:
            continue
        v50 = vma(B, k, 50)
        if not v50 or v[k] < 1.5 * v50 or bl <= 0 or bh / bl - 1 > 0.35 or bh < 0.85 * max(h[k - 251:k]):
            continue
        gap = (c[i] / bh - 1) * 100
        if not -2 <= gap <= 7:
            return None
        return {"ago": i - k, "vm": v[k] / v50, "box": (bh / bl - 1) * 100, "pivot": bh, "gap": gap, "line": bh,
                "pts": [[str(d[k]), c[k], "돌파"]]}
    return None


def stage2(B, i):
    """와인스타인 1→2단계 — 최근 10봉 안에 종가가 30주선(150일)을 위로 뚫었고 지금도 위, 그 앞 6달(130~10봉 전)은
    절반 넘게 30주선 아래에서 고저 60% 안 옆걸음(1단계 바닥), 30주선이 20봉 전보다 1% 넘게 내려가지 않았다(평평 · 오름),
    돌파 뒤 하루 거래량이 50봉 평균의 2배↑, 종가가 그 앞 석 달(60~10봉 전) 종가 고점 위."""
    if i < 320:
        return None
    h, l, c, v, d = B["h"], B["l"], B["c"], B["v"], B["d"]
    m = lambda k: ma(B, k, 150)
    if c[i] <= m(i):
        return None
    cross = next((k for k in range(i, i - 10, -1) if c[k] > m(k) and c[k - 1] <= m(k - 1)), None)
    if cross is None:
        return None
    below = sum(1 for k in range(i - 130, i - 10) if c[k] < m(k)) / 120
    rng = max(h[i - 130:i - 10]) / min(l[i - 130:i - 10]) - 1
    slope = (m(i) / m(i - 20) - 1) * 100
    v50 = vma(B, cross, 50)
    vm = max(v[cross:i + 1]) / v50 if v50 else 0
    if below < 0.5 or rng > 0.6 or slope < -1 or vm < 2 or c[i] <= max(c[i - 60:i - 10]):
        return None
    return {"ma150": (c[i] / m(i) - 1) * 100, "slope": slope, "below": below * 100, "vm": vm, "ago": i - cross,
            "pivot": m(i), "gap": (c[i] / m(i) - 1) * 100, "pts": [[str(d[cross]), c[cross], "30주선 돌파"]]}


def absorb(B, i):
    """바닥 투매 흡수 — 최근 60봉 안, 거래량이 60봉 평균의 3배↑ · 그날 저가가 52주 저점 5% 안 · 종가가 그날 고저의 위 40% 안
    (긴 아래꼬리) · 그 뒤 그 저가를 안 깼다. (저평가V2 첫 판의 '바닥 대량 아래꼬리' — 6개월 검증 통과한 신호)"""
    if i < 260:
        return None
    h, l, c, v, d = B["h"], B["l"], B["c"], B["v"], B["d"]
    for k in range(i, i - 60, -1):
        rng = h[k] - l[k]
        base = vma(B, k, 60)
        if rng > 0 and base and v[k] >= 3 * base and l[k] <= min(l[max(0, k - 249):k + 1]) * 1.05 \
                and (c[k] - l[k]) / rng >= 0.6 and min(l[k:i + 1]) >= l[k]:
            return {"ago": i - k, "vm": v[k] / base, "tail": (c[i] / l[k] - 1) * 100, "pivot": l[k], "gap": (c[i] / l[k] - 1) * 100,
                    "line": l[k], "pts": [[str(d[k]), l[k], "투매 흡수"]]}
    return None


def accumulation(B, i):
    """조용한 매집(거래량 흔적) — 최근 50봉 오른 날 거래량 ÷ 내린 날 거래량 1.3↑, OBV(거래량 누적)가 60봉 고점을 새로 썼는데
    종가는 60봉 종가 고점보다 3%↑ 아래(거래량이 주가보다 먼저), 최근 20봉 고저 15% 안(조용), 종가 > 50일선.
    기관 · 외국인 수급 자료가 없어 누가 샀는지는 모른다 — 거래량으로 본 흔적만."""
    if i < 260:
        return None
    h, l, c, v = B["h"], B["l"], B["c"], B["v"]
    if c[i] <= ma(B, i, 50):
        return None
    up = sum(v[k] for k in range(i - 49, i + 1) if c[k] > c[k - 1])
    dn = sum(v[k] for k in range(i - 49, i + 1) if c[k] < c[k - 1])
    if not dn or up / dn < 1.3:
        return None
    o, arr = 0.0, []
    for k in range(i - 59, i + 1):
        o += v[k] if c[k] > c[k - 1] else -v[k] if c[k] < c[k - 1] else 0
        arr.append(o)
    if max(arr[-3:]) < max(arr[:-3]):
        return None
    gap = (c[i] / max(c[i - 59:i + 1]) - 1) * 100
    rng = (max(h[i - 19:i + 1]) / min(l[i - 19:i + 1]) - 1) * 100
    if gap > -3 or rng > 15:
        return None
    return {"ud": up / dn, "gap": gap, "rng": rng}


def ipo_setup(B, i):
    """IPO 셋업 — 상장 3년 안(봉 750개 안 · 시세 첫날이 2010-01 수집 시작보다 뒤), 상장 20봉↑, 상장 뒤 첫날 시가에서
    15% 넘게 벌어졌다가(위든 아래든) 지금 그 시가 −10% ~ +5%로 돌아옴."""
    d = B["d"]
    if d[0] <= 20100111 or i > 750 or i < 20:
        return None
    o0, c = B["o"][0], B["c"][i]
    hi, lo = max(B["h"][:i + 1]), min(B["l"][:i + 1])
    gap = (c / o0 - 1) * 100
    if not -10 <= gap <= 5 or not (hi >= o0 * 1.15 or lo <= o0 * 0.85):
        return None
    return {"listed": str(d[0]), "days": i, "open0": o0, "gap": gap, "hi": (hi / o0 - 1) * 100, "pivot": o0, "line": o0,
            "pts": [[str(d[0]), o0, "상장 첫날 시가"]]}


def warn_flags(B, i):
    """경고 — 고점 대량 음봉(물량 넘김) · 역배열 하락 · 거래대금 부족 · 50일선보다 25%↑(추격 위험)."""
    if i < 260:
        return []
    o, h, c, v = B["o"], B["h"], B["c"], B["v"]
    out = []
    for k in range(i, i - 120, -1):
        rng = h[k] - B["l"][k]
        base = vma(B, k, 60)
        if rng > 0 and base and v[k] >= 3 * base and h[k] >= max(h[max(0, k - 249):k + 1]) * 0.9 and \
                (c[k] < o[k] or (h[k] - max(o[k], c[k])) / rng >= 0.5):
            out.append("top_dump")
            break
    m20, m60, m120, m20_5 = ma(B, i, 20), ma(B, i, 60), ma(B, i, 120), ma(B, i - 5, 20)
    if c[i] < m20 < m60 < m120 and m20 < m20_5:
        out.append("down_aligned")
    tv = tvma(B, i, 20)
    if tv is not None and tv < 3e8:
        out.append("thin")
    if c[i] >= ma(B, i, 50) * 1.25:
        out.append("ext")
    return out


WARN = {"top_dump": "고점 대량 음봉(물량 넘김)", "down_aligned": "역배열 하락 중", "thin": "거래대금 적음(하루 3억↓)",
        "ext": "50일선보다 25%↑(추격 위험)"}

PATTERNS = (("cup", cup_handle), ("vcp", vcp), ("flat", flat_base), ("pull", pullback), ("brk", breakout),
            ("stage2", stage2), ("absorb", absorb), ("accum", accumulation), ("ipo", ipo_setup))


def setup(B, i):
    """i 번째 봉까지로 본 패턴 · 지표 묶음. 순위(RS)와 실적 · 리포트는 밖에서 붙인다(rule 이 읽는다)."""
    if i < 20:
        return None
    prep(B)
    c, h, l = B["c"], B["h"], B["l"]
    f = {"d": str(B["d"][i]), "c": c[i], "chg": (c[i] / c[i - 1] - 1) * 100 if c[i - 1] else None,
         "rs_raw": rs_raw(B, i) if i >= 252 else None, "rs1_raw": _roc(c, i, 21), "tv20": tvma(B, i, 20)}
    if i >= 252:
        hi52, lo52 = max(h[i - 251:i + 1]), min(l[i - 251:i + 1])
        m50, m200 = ma(B, i, 50), ma(B, i, 200)
        f.update(hi52=(c[i] / hi52 - 1) * 100, lo52=(c[i] / lo52 - 1) * 100, ma50=(c[i] / m50 - 1) * 100, ma200=(c[i] / m200 - 1) * 100)
    tt = trend_template(B, i)
    f["tt"] = tt
    f["tt7"] = bool(tt) and all(tt)
    for k, fn in PATTERNS:
        try:
            f[k] = fn(B, i)
        except (ValueError, ZeroDivisionError, IndexError, TypeError):
            f[k] = None
    f["warn"] = warn_flags(B, i)
    return f


# 셋업 규칙 — x = setup() 결과 + rs · rs1(순위) · fund(확정 실적) · rep(증권사 리포트). 화면 카드 순서.
#   (키, 이름, 한 줄 설명, 규칙, 출처)
def _earn(x):
    fd = x.get("fund") or {}
    return fd.get("eps_yoy") is not None and fd["eps_yoy"] >= 25 and (x.get("rs") or 0) >= 80 and (x.get("ma50") or -1) > 0


def _tp(x):
    rp = x.get("rep") or {}
    return bool(rp.get("up")) and rp.get("move") is not None and rp["move"] <= 5 and (rp.get("room") or 0) >= 15


PRESETS = [
    ("cup", "컵위드핸들", "U자로 회복한 뒤 손잡이에서 숨 고르는 종목 — 손잡이 고점이 돌파가",
     lambda x: bool(x.get("cup")), "오닐"),
    ("vcp", "변동성 수축(VCP)", "상승 추세 안에서 흔들림이 점점 작아지고 거래가 마르는 종목",
     lambda x: bool(x.get("vcp")) and x.get("tt7") and (x.get("rs") or 0) >= 70, "미너비니"),
    ("pull", "강세 눌림", "신고가 뒤 거래 줄이며 20·50일선까지 숨 고르는 주도주",
     lambda x: bool(x.get("pull")) and (x.get("rs") or 0) >= 80, "오닐 · 미너비니"),
    ("brk", "박스 돌파", "거래량 1.5배 이상 실어 석 달 박스 고점을 넘은 종목",
     lambda x: bool(x.get("brk")) and (x.get("rs") or 0) >= 70, "오닐"),
    ("flat", "평평한 바닥", "오른 뒤 15% 안에서 5주 넘게 쉬며 고점에 붙은 종목",
     lambda x: bool(x.get("flat")), "오닐"),
    ("tt", "2단계 상승", "미너비니 추세 템플릿 8개 조건을 모두 통과한 종목",
     lambda x: x.get("tt7") and (x.get("rs") or 0) >= 70, "미너비니"),
    ("stage2", "바닥 탈출", "긴 옆걸음 끝에 30주선을 거래량 실어 넘은 종목(1→2단계)",
     lambda x: bool(x.get("stage2")), "와인스타인"),
    ("absorb", "바닥 투매 흡수", "52주 저점에서 대량 아래꼬리로 투매를 받아내고 그 저가를 지키는 종목",
     lambda x: bool(x.get("absorb")), "저평가V2 검증 신호"),
    ("earn", "실적 모멘텀", "확정 분기 EPS가 25% 넘게 늘고 주가도 강한 종목(RS 80↑)",
     _earn, "오닐 CAN SLIM"),
    ("tp", "목표가 상향", "증권사가 목표가를 올렸는데 주가는 아직 덜 움직인 종목",
     _tp, "증권사 리포트"),
    ("accum", "조용한 매집", "주가는 조용한데 오르는 날 거래가 더 많고 OBV가 먼저 고점",
     lambda x: bool(x.get("accum")), "거래량(OBV)"),
    ("ipo", "IPO 셋업", "상장 3년 안 · 상장 첫날 시가 근처로 돌아온 종목",
     lambda x: bool(x.get("ipo")), "오닐"),
]


def presets_of(x):
    return [k for k, _, _, fn, _ in PRESETS if fn(x)]
