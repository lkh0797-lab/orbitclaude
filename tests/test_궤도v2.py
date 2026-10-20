# -*- coding: utf-8 -*-
"""궤도v2.py — 국면 · 값 접기 · PER 자리(앞날 안 섞임) · 9칸 문장 · 다음 보고서 예상 · 사건 모으기 · 분기 표 (2026-10-21)."""
import os
import sys
import datetime as dt
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("궤도v2", os.path.join(BASE, "궤도v2.py"))
O2 = ilu.module_from_spec(_sp)
_sp.loader.exec_module(O2)


def _pts(pers):
    return [{"n": i, "label": "20%02dQ1" % i, "PER_TTM": v, "품질": []} for i, v in enumerate(pers)]


def test_biz_group_folds_seven_phases_into_three():
    assert O2.biz_group("확장 가속") == "up" and O2.biz_group("회복") == "up"
    assert O2.biz_group("확장 유지") == "flat" and O2.biz_group("정체") == "flat"
    assert O2.biz_group("둔화") == "down" and O2.biz_group("부진 지속") == "down" and O2.biz_group("수축 심화") == "down"
    assert O2.biz_group(None) is None and O2.biz_group("") is None and O2.biz_group("없는 국면") is None


def test_val_zone_thresholds_match_beads_and_value_backtest():
    assert O2.val_zone(30) == "cheap" and O2.val_zone(30.1) == "mid" and O2.val_zone(74.9) == "mid" and O2.val_zone(75) == "rich"
    assert O2.val_zone(None) is None and O2.VAL_CHEAP == 30 and O2.VAL_RICH == 75


def test_per_pct_uses_only_past_and_needs_eight():
    pts = _pts([10, 12, 14, 16, 18, 20, 22, 24, 5, 100])
    assert O2.per_pct_to(pts, 6) is None                                   # 7개 — 표본 부족
    assert abs(O2.per_pct_to(pts, 7) - 100) < 1e-9                        # 8개째, 지금까지 최고
    assert abs(O2.per_pct_to(pts, 8) - 100 / 9) < 1e-9                    # 5 는 아홉 중 가장 싸다 — 뒤의 100 은 안 본다
    pts[9]["품질"] = ["cut"]
    assert O2.per_pct_to(pts, 9) is None                                   # 분할 보정 못 한 분기
    assert O2.per_pct_to(pts, 99) is None and O2.per_pct_to(pts, -1) is None


def test_verdict_has_text_for_all_nine_cells_and_prefixes():
    for b in ("up", "flat", "down"):
        for v in ("cheap", "mid", "rich"):
            r = O2.verdict(b, v)
            assert r["cell"] == b + "·" + v and r["head"] and r["watch"] and r["partial"] is None
            # 머리말은 자리 서술 — 방향 주장(오른다 · 덜 반영 · 가장 나쁜 …)은 금지(기저율 줄이 숫자로 말한다)
            assert not any(w in r["head"] for w in O2.VERDICT_BANNED), r["head"]
    r = O2.verdict("up", "cheap", gap="blue", gates=[{"name": "희석", "why": "CB"}, "둔화"])
    assert r["gap_line"].startswith("엇갈림 파랑") and r["gate_line"] == "빨간불: 희석 — CB · 둔화"
    r = O2.verdict("up", None)
    assert r["cell"] is None and r["partial"] == "val" and "값 자리를 모른다" in r["head"]
    r = O2.verdict(None, "rich")
    assert r["partial"] == "biz" and "비싸다" in r["head"]
    assert O2.verdict(None, None)["partial"] == "both"


def test_next_filing_quarter_half_annual_and_overdue():
    r = O2.next_filing("2026-06", dt.date(2026, 10, 21))
    assert r["stamp"] == "2026-09" and r["label"] == "분기보고서" and r["due"] == "20261114" and r["days"] == 24 and not r["overdue"]
    r = O2.next_filing("2026-09", "20261201")
    assert r["stamp"] == "2026-12" and r["label"] == "사업보고서" and r["due"] == "20270331"
    r = O2.next_filing("2026-03", dt.date(2026, 8, 20))
    assert r["label"] == "반기보고서" and r["due"] == "20260814" and r["overdue"] and r["days"] == -6
    assert O2.next_filing("2026-05", dt.date(2026, 8, 20)) is None and O2.next_filing(None, dt.date(2026, 8, 20)) is None
    # 결산월이 다른 회사 — 그 회사의 달 → 라벨 지도
    r = O2.next_filing("2026-03", dt.date(2026, 4, 1), {"06": "분기보고서"})
    assert r["label"] == "분기보고서" and r["due"] == "20260814"


def test_merge_events_sorts_desc_and_filters_since_and_limit():
    a = [{"d": "20260101", "kind": "보고서"}, {"d": "20250101", "kind": "보고서"}]
    b = [{"d": "20260301", "kind": "수주"}, {"d": "bad", "kind": "수주"}]
    ev = O2.merge_events(a, b, since="20251231")
    assert [e["d"] for e in ev] == ["20260301", "20260101"]
    assert len(O2.merge_events(a, b, limit=1)) == 1 and O2.merge_events(None, []) == []


def test_filing_order_risk_flag_report_events():
    rows = [{"rcept": "20260814000001", "stamp": "2026-06", "label": "반기보고서", "x": 2.5, "tier": "격변", "tag": "", "gist": [{"text": "북미 수주"}]},
            {"rcept": "20260514000001", "stamp": "2026-03", "label": "분기보고서", "x": 0.9, "tier": "평소", "tag": ""},
            {"rcept": "20260820000001", "stamp": "2026-06", "label": "반기보고서", "x": 3.0, "tier": "격변", "tag": "[기재정정]"}]
    fe = O2.filing_events(rows)
    assert len(fe) == 1 and fe[0]["d"] == "20260814" and fe[0]["sub"] == "북미 수주" and fe[0]["strip"]
    oe = O2.order_events([{"date": "20261019", "rcept": "r1", "kind": "체결", "amount": 1.7e11, "party": "A", "title": "T", "start": "2026-10-16", "end": "2027-12-31"},
                          {"date": "20261001", "rcept": "r2", "kind": "체결", "amount": 1e9},
                          {"date": "20260901", "rcept": "r3", "kind": "해지", "amount": None}], 5.7e12)
    assert abs(oe[0]["pct"] - 1.7e11 / 5.7e12 * 100) < 1e-9 and oe[0]["strip"] and oe[0]["tone"] == 1
    assert oe[1]["strip"] is False and oe[2]["kind"] == "수주 해지" and oe[2]["strip"] and oe[2]["tone"] == -1
    # 날짜별 매출(callable) — 옛 계약은 그때 매출로
    oe2 = O2.order_events([{"date": "20160301", "kind": "체결", "amount": 1e10}, {"date": "20261019", "kind": "체결", "amount": 1e10}], lambda d: 1e11 if d < "2020" else 1e12)
    assert abs(oe2[0]["pct"] - 10) < 1e-9 and abs(oe2[1]["pct"] - 1) < 1e-9
    re_ = O2.risk_events({"ref": [{"cat": "회생절차", "rows": [["20260406", "회생절차개시결정", "x1"], ["20260406", "같은 것", "x1"]]}],
                          "hits": [{"cat": "CB발행", "rows": [["20260713", "전환사채권발행결정", "h1"]]}]},
                         {"유상증자": {"n": 2, "last": "20260610"}, "회생절차": {"n": 1, "last": "20260406"}})
    assert [e["d"] for e in re_] == ["20260713", "20260406", "20260610"] and re_[0]["sub"] == "CB발행" and re_[2]["title"] == "유상증자 ×2" and all(e["tone"] == -1 for e in re_)
    assert O2.risk_events(None, None) == [] and O2.risk_events({"ref": [{"cat": "a", "rows": [["20200101", "t", "r"]]}]}, None, since="20240101") == []
    pts = [{"n": 1, "label": "2025Q2", "기준일": "20250814", "영업이익": -1, "영업이익_전": 2, "변곡": None},
           {"n": 2, "label": "2025Q3", "기준일": "20251114", "영업이익": 3, "영업이익_전": -4, "변곡": "▲"}]
    fl = O2.flag_events(pts)
    assert [(e["d"], e["kind"], e["tone"]) for e in fl] == [("20250814", "전환", -1), ("20251114", "전환", 1), ("20251114", "변곡", 1)]
    rp = O2.report_events([{"type": "report", "d": "20261007", "title": "실적 서프라이즈", "opinion": "Buy", "tp": 300000, "price_at": 217500, "re": {"chg": -5.75}},
                           {"type": "disc", "d": "20261001"}, {"type": "report", "d": "20200101", "hide": True}], since="20250101")
    assert len(rp) == 1 and "목표가 300,000" in rp[0]["sub"] and "상승여력 +38%" in rp[0]["sub"] and rp[0]["re"] == -5.75


def test_quarters_table_last_eight_with_yoy_margin_and_per_pct():
    pts = []
    for i in range(14):
        pts.append({"n": i, "label": "2020Q%d" % (i % 4 + 1), "fs": "CFS", "기준일": "2020%02d14" % (i % 12 + 1), "매출액": 100 + i, "매출YoY": 5.0, "영업이익": 10 + i, "영업이익YoY": 7.0,
                    "매출_TTM": 400 + 10 * i, "영업이익_TTM": 40 + 2 * i, "가속B": 1.0, "국면": "확장 유지", "주가": 1000 + i, "PER_TTM": 10 + i, "품질": [], "변곡": None})
    rows = O2.quarters_table(pts, {"2020Q2": 5e11}, {"2020Q2": 1.2})
    assert len(rows) == 8 and rows[-1]["label"] == "2020Q2" and rows[-1]["backlog"] == 5e11 and rows[-1]["x"] == 1.2
    last = rows[-1]
    assert abs(last["m"] - (40 + 26) / (400 + 130) * 100) < 1e-9 and last["dm"] is not None and abs(last["ttm_g"] - ((530 / 490) - 1) * 100) < 1e-9
    assert last["per_pct"] == 100.0 and rows[0]["per_pct"] is None     # 6번째 점(인덱스 6) 은 표본 7개 — 아직 자리 없음
    assert O2.quarters_table([], None, None) == []


def test_lines_and_base_line():
    assert O2.biz_line(None) == "가속도 자료 없음"
    s = O2.biz_line({"phase": "확장 가속", "ttm_g": 40.1, "b": 17.2, "m": 9.4, "dm": 1.1, "label": "2026Q2"}, {"blog_yoy": 82, "btb": 1.55, "ok": True})
    assert s.startswith("국면 확장 가속 · 최근 4분기 매출 +40% · 가속 B +17.2%p · 영업이익률 9.4% (1년 +1.1%p) · 수주잔고 1년 +82% · 북투빌 1.55 (2026Q2)")
    s = O2.biz_line({"phase": "둔화", "label": "2026Q2"}, {"blog_yoy": 300, "btb": 2.0, "ok": False, "why": "5배 넘게 튐"})
    assert "수주잔고 못 믿음(5배 넘게 튐)" in s and "+300%" not in s
    s = O2.px_line({"r12": 298, "dd": -50.1, "r3": -16.3, "px": 166600}, {"per": 79.0, "pct": 93.3, "label": "2026Q2"}, 44764, {"med": 18.2, "n": 30}, {"per": 64.5, "pct": 98.3, "date": "20261019"})
    assert "공시일 PER 79배 = 자기 역사 비싸다(93% 자리, 2026Q2)" in s and "지금 PER 64배 · 98% 자리(풍경 10-19)" in s
    assert "이익선(자기 PER 중앙 × TTM EPS) 대비 +272%" in s and "업종 PER 중앙 18배(30곳)" in s
    assert O2.px_line({}, {}) == "주가 자료 없음"
    cells = {"cells": {"up·cheap": {"n": 120, "firms": 40, "med": 3.2, "ci": [1.1, 5.0], "hit": 56.2, "early": 2.0, "late": 4.1},
                       "flat·mid": {"n": 5}}}
    assert "뚜렷하다" in O2.base_line(cells, "up·cheap") and "120회(40곳)" in O2.base_line(cells, "up·cheap")
    assert "표본이 적다(5행)" in O2.base_line(cells, "flat·mid") and O2.base_line(cells, None) is None and O2.base_line(None, "up·cheap") is None
    assert "0 을 걸친다" in O2.base_line({"cells": {"k": {"n": 30, "firms": 9, "med": 1.0, "ci": [-1.0, 2.0], "hit": 50}}}, "k")
