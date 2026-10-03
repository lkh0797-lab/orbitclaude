# -*- coding: utf-8 -*-
"""
기술 신호 — 저평가V2(서버 value2_view)와 도구/저평가V2_백테스트.py 가 같이 쓴다 (2026-10-03).
슈퍼개미가 흔히 쓰는 차트 지침을 숫자로 고정한 것(맞추지 않았다). 봉 = 재무.fetch_ohlcv 의 {날짜: [시가, 고가, 저가, 종가, 거래량]}.
"""


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


