# -*- coding: utf-8 -*-
"""수출 선행 발굴 — 순수 함수(2026-10-14). 스펙 docs/superpowers/specs/2026-10-14-export-lead-value-design.md 1 · 2절."""
import os, sys, datetime as dt, importlib.util as ilu
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("수출선행_시험", os.path.join(BASE, "수출선행.py"))
X = ilu.module_from_spec(_sp); _sp.loader.exec_module(X)
D = dt.date


def test_quarter_end_and_due_date():
    assert X.quarter_end("2026Q3") == D(2026, 9, 30)
    assert X.quarter_end("2026Q4") == D(2026, 12, 31)
    assert X.quarter_end("2024Q1") == D(2024, 3, 31)
    assert X.due_date("2026Q3") == D(2026, 11, 16)          # 9/30 + 45 = 11/14(토) → 11/16(월)
    assert X.due_date("2026Q2") == D(2026, 8, 14)           # 6/30 + 45 = 8/14(금)
    assert X.due_date("2025Q4") == D(2026, 3, 31)           # 12/31 + 90 = 3/31(화)
    assert X.due_date("2024Q4") == D(2025, 3, 31)           # 윤년 거침


def test_due_label_before_and_after():
    assert X.due_label("2026Q3", D(2026, 10, 14)) == {"due": "2026-11-16", "days": 33, "text": "D-33 · 11-16까지(≈)"}
    assert X.due_label("2026Q2", D(2026, 8, 19))["text"] == "D+5 · 08-14 지남"


def test_hit_rate_counts_only_comparable_pairs():
    pairs = [{"x": 10, "r": 5}, {"x": -3, "r": -1}, {"x": 8, "r": -2}, {"x": None, "r": 4}, {"x": 2, "r": None}, {"x": 0, "r": 0}]
    assert X.hit_rate(pairs) == (3, 4)
    assert X.hit_rate([]) == (0, 0)


def test_gap_and_pearson():
    assert X.gap(40.0, -20.0) == 60.0
    assert X.gap(None, -20.0) is None and X.gap(40.0, None) is None
    assert X.pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert X.pearson([1, 2, None, 3], [2, 4, 9, 6]) == pytest.approx(1.0)       # None 쌍 제외
    assert X.pearson([1, 2], [2, 4]) is None
    assert X.pearson([1, 1, 1], [2, 4, 6]) is None                                # 분산 0


def _pairs(n, r=1.0):
    return [{"x": float(i), "r": float(i) * r} for i in range(n)]


def test_pit_grade_thresholds():
    assert X.pit_grade(_pairs(5), 30.0) == "C"                     # 쌍 부족
    assert X.pit_grade(_pairs(8), None) == "C"                     # 비중 모름
    assert X.pit_grade(_pairs(8), 4.9) == "C" and X.pit_grade(_pairs(8), 150.1) == "C"
    assert X.pit_grade(_pairs(8), 5.0) == "A" and X.pit_grade(_pairs(8), 150.0) == "A"
    assert X.pit_grade(_pairs(7), 30.0) == "B"                     # 상관 1 이지만 8쌍 미만 → B
    mixed = [{"x": 0, "r": 0}, {"x": 1, "r": 3}, {"x": 2, "r": 1}, {"x": 3, "r": 4}, {"x": 4, "r": 2}, {"x": 5, "r": 6}, {"x": 6, "r": 3}, {"x": 7, "r": 7}]
    g = X.pit_grade(mixed, 30.0)
    assert g in ("A", "B")                                          # 상관 0.3 ↑
    anti = [{"x": i, "r": -i} for i in range(8)]
    assert X.pit_grade(anti, 30.0) == "C"


def test_cut_series_and_rev_quarters():
    mon = {"202501": 10, "202502": 10, "202503": 10, "202504": 12, "202505": 12, "202506": 12, "202507": 9,
           "202601": 15, "202602": 15, "202603": 15, "202604": 18, "202605": 18}
    cut = X.cut_series(mon, "202604")
    assert max(cut) == "202604" and "202605" not in cut
    rq = X.rev_quarters(cut, {"2026Q1": 20.0, "2025Q1": None})
    assert rq == [{"q": "2026Q1", "x": 50.0, "r": 20.0}]           # 2026Q1 만 완성 + 작년 분기 합 있음(2025Q1 30 → 45)
    # 미래 달을 더해도 잘라 낸 결과는 같다(앞부분 불변)
    mon2 = dict(mon, **{"202606": 99, "202607": 99})
    assert X.cut_series(mon2, "202604") == cut


def _inp(**kw):
    base = {"grade": "A", "lumpy": False, "reported": False, "cur": 35.0, "months": ["202607", "202608"],
            "ret3m": -4.0, "univ3m": 2.0, "dd52": -10.0, "per_pct": 30.0, "red": [], "risk": [], "fin": False}
    base.update(kw)
    return base


def test_judge_found():
    j = X.judge(_inp())
    assert j["tier"] == "발굴" and j["why"] == [] and j["checks"] == {"clue": True, "price": True, "value": True, "red": False}


def test_judge_no_clue_cases():
    assert X.judge(_inp(reported=True))["tier"] is None            # 이미 공시된 분기 값뿐 — 공시보다 먼저가 아님
    assert X.judge(_inp(cur=19.9))["tier"] is None
    assert X.judge(_inp(cur=None))["tier"] is None
    assert X.judge(_inp(grade="C"))["tier"] is None
    assert X.judge(_inp(lumpy=True))["tier"] is None


def test_judge_watch_reasons():
    j = X.judge(_inp(ret3m=18.0, univ3m=2.0, dd52=-5.0))
    assert j["tier"] == "관찰" and j["checks"]["price"] is False and "주가 3개월 +18%" in j["why"][0]
    j = X.judge(_inp(ret3m=18.0, univ3m=2.0, dd52=-30.0))          # 3개월은 올랐어도 고점 대비 −30% 면 통과
    assert j["tier"] == "발굴"
    j = X.judge(_inp(ret3m=None, dd52=None))
    assert j["tier"] == "관찰" and j["checks"]["price"] is None and any("주가 모름" in w for w in j["why"])
    j = X.judge(_inp(per_pct=72.0))
    assert j["tier"] == "관찰" and j["checks"]["value"] is False and any("상위 28%" in w for w in j["why"])
    j = X.judge(_inp(per_pct=None))
    assert j["tier"] == "관찰" and j["checks"]["value"] is None and any("값 모름" in w for w in j["why"])
    j = X.judge(_inp(red=["부채비율 240% — 200% 넘는 빚"]))
    assert j["tier"] == "관찰" and j["checks"]["red"] is True and j["why"] == ["빨간불: 부채비율 240% — 200% 넘는 빚"]
    j = X.judge(_inp(risk=["공시 위험: 빨강", "증권사 상태: 관리종목"]))
    assert j["tier"] == "관찰" and j["why"] == ["공시 위험: 빨강", "증권사 상태: 관리종목"]


def test_judge_price_unknown_when_history_short_even_if_dd_deep():
    # 이력 91일 미만(ret3m 모름)이면 짧은 창의 고점 대비 −30% 라도 '주가는 아직'을 단정하지 않는다(설계 1절: 모름 → 관찰) — 2026-10-14 리뷰 T2
    j = X.judge(_inp(ret3m=None, dd52=-30.0))
    assert j["tier"] == "관찰" and j["checks"]["price"] is None and j["why"] == ["주가 모름 — 이력 91일 미만"]
    j = X.judge(_inp(ret3m=1.0, univ3m=None, dd52=-5.0))          # 전 종목 중앙값을 모르면 3개월 비교를 못 한다
    assert j["tier"] == "관찰" and j["checks"]["price"] is None and any("중앙값 모름" in w for w in j["why"])
    assert X.judge(_inp(ret3m=1.0, univ3m=None, dd52=-30.0))["tier"] == "발굴"     # 중앙값 몰라도 고점 −30% 면 통과


def test_judge_value_unknown_when_per_sample_small():
    # PER 자기 역사 표본 8분기 미만이면 백분위를 단정하지 않는다(펨트론 band.n 2 → '상위 0%' 아니라 모름) — 리뷰 T1, bt_panel 의 8분기 하한과 같은 조건
    j = X.judge(_inp(per_pct=100.0, per_n=2))
    assert j["tier"] == "관찰" and j["checks"]["value"] is None and j["why"] == ["값 모름 — PER 표본 2분기(8 미만)"]
    assert X.judge(_inp(per_pct=30.0, per_n=8))["tier"] == "발굴"
    assert X.judge(_inp(per_pct=30.0, per_n=None))["tier"] == "발굴"       # 표본 수를 모르면(백테스트 bt_panel 은 이미 8분기↑만) 그대로
    assert X.VALUE_MIN_N == 8


def test_last_final_day_is_median_of_last_bars():
    # 주가 캐시가 반쯤 새로 받아진 상태(718곳 10-13 · 270곳 10-14)면 과거 검증의 지평 끝 한계는 10-13 — 최대값이 아니라 중앙값
    assert X.last_final_day(["20261013"] * 718 + ["20261014"] * 270) == "20261013"
    assert X.last_final_day(["20261014"] * 3) == "20261014"
    assert X.last_final_day([]) is None and X.last_final_day([None, "20261010"]) == "20261010"


def test_index_series_rebased_and_missing_months():
    mon = {"2024%02d" % m: 10 for m in range(1, 13)}
    mon.update({"2025%02d" % m: 20 for m in range(1, 13)})
    px = {"2024%02d" % m: 100 for m in range(1, 13)}
    px.update({"2025%02d" % m: 80 for m in range(1, 13)})
    px.pop("202506")
    s = X.index_series(mon, px, n=24)
    assert len(s) == 24 and s[0]["ym"] == "202401" and s[-1]["ym"] == "202512"
    assert s[0]["p"] == 100.0 and s[-1]["p"] == 80.0
    assert s[5]["ym"] == "202406" and s[5]["x"] == 100.0           # 12개월 합이 처음 완성되는 달까지 100
    assert s[-1]["x"] == 200.0                                      # 2025 합 240 vs 2024 합 120
    assert s[17]["ym"] == "202506" and s[17]["p"] is None           # 빠진 달은 None(선이 끊긴다)


def test_pit_inputs_prefix_invariant():
    # 도구/수출선행_백테스트.pit_inputs 와 같은 재료로 — 미래 달 · 미래 접수일을 더해도 시점 d 의 판정 재료는 같다
    mon = {"2025%02d" % m: 100 for m in range(1, 13)}
    mon.update({"202601": 150, "202602": 150, "202603": 150, "202604": 160, "202605": 160})
    rev = {"2025Q1": 10.0, "2025Q2": 12.0, "2025Q3": 8.0, "2025Q4": 9.0, "2026Q1": 40.0}
    fd = {"2025Q1": "20250515", "2025Q2": "20250814", "2025Q3": "20251114", "2025Q4": "20260331", "2026Q1": "20260515"}
    a = X.pit_pairs(mon, rev, fd, m="202605", d="20260616")
    b = X.pit_pairs(dict(mon, **{"202606": 999, "202607": 999}), dict(rev, **{"2026Q2": 99.0}), dict(fd, **{"2026Q2": "20260814"}), m="202605", d="20260616")
    assert a == b
    assert [p["q"] for p in a] == ["2026Q1"]                        # 2025 분기는 2024 통관이 없어 x None → r 만 (r 도 없으면 빠짐) … 2026Q1 만 x · r 둘 다
    assert X.last_reported_q(fd, "20260616") == "2026Q1" and X.last_reported_q(fd, "20260514") == "2025Q4"
