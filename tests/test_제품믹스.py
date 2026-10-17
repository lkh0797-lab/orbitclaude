# -*- coding: utf-8 -*-
"""제품 믹스 — 표 뒤처리 · 검산 · 기여도 순수 함수(2026-10-17, 리뷰 반영 MIX_V 2)."""
import os, sys, json, importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("제품믹스_시험", os.path.join(BASE, "제품믹스.py"))
M = ilu.module_from_spec(_sp); _sp.loader.exec_module(M)


def P(item, amt=None, pct=None, seg=None, kind=None, use=None):
    return {"segment": seg, "kind": kind, "item": item, "use": use, "amt": amt, "pct": pct}


def test_clean_drops_total_rows_and_bleed():
    rows, c = M.clean([P("히터블럭", 476, 88.2), P("상품", 47, 8.8), P("매출총계", 539, 100.0)])
    assert [r["item"] for r in rows] == ["히터블럭", "상품"] and not c
    rows, _ = M.clean([P("강관", 4900, seg="강관"), P("판재", 461, seg="강관"), P("강관", 1389, seg="품목", kind="제65기")])
    assert len(rows) == 2


def test_subtotal_candidate_removed_only_when_ledger_agrees():
    rows = [P("의류", 1725726, 89.9), P("원단", 193103, 10.1), P("원단", 1918829, 100.0), P("기타", 121)]
    got, cands = M.clean(rows)
    assert cands == {2}
    ck = M.check_year(rows, rev=1918950e6)                # 소계를 빼야 원장과 맞는다
    assert ck["pass10"] and [r["amt"] for r in ck["rows"]] == [1725726, 193103, 121]
    # 진짜 최대 품목이 앞 두 줄 합과 같은 꼴(S-Oil 경유) — 원장이 '둔다'를 고르면 지우지 않는다
    rows2 = [P("휘발유", 300), P("등유", 200), P("경유", 500)]
    ck2 = M.check_year(rows2, rev=1000e6)
    assert ck2["pass10"] and len(ck2["rows"]) == 3
    assert len(M.check_year(rows2, rev=None)["rows"]) == 3    # 원장 없이는 지우지 않는다


def test_adjustment_regex_narrow_and_use_column():
    for name in ("가상계좌, 펌뱅킹", "공기제거기", "유해가스 제거", "모공 속 노폐물 제거"):
        assert not M.is_adj(P(name)), name
    assert M.is_adj(P("연결조정 및 기타종속회사"))
    assert M.is_adj(P("부동산임대업", 97920, seg="철강", use="연결조정"))
    assert not M.is_adj(P("세정제", 10, use="불순물 제거"))
    ck = M.check_year([P("2차전지", 312605), P("소재", 97513), P("내부거래 제거", 11604)], rev=398514e6)
    assert ck["unit_name"] == "백만원" and ck["pass5"]


def test_check_year_unit_and_pct_consistency():
    rows = [P("DX", 1006771), P("DS", 2092317)]          # 억원 표
    ck = M.check_year(rows, rev=3.1e14)
    assert ck["unit_name"] == "억원" and ck["pass10"]
    assert not M.check_year(rows, rev=6.0e14)["pass10"]   # 절반만 적은 표
    assert not M.check_year(rows, rev=3.1e14, unit=1e6)["pass10"]   # 회사 단위가 백만원이면 이 해는 안 맞는다
    bad = [P("A", 600, pct=20), P("B", 400, pct=80)]       # 금액 비중 60:40 vs 비율 칸 20:80
    ck = M.check_year(bad, rev=1000e6)
    assert not ck["pass10"] and "비율 칸" in ck["why"]


def test_amount_column_holding_percentages_is_pct_table():
    ck = M.check_year([P("A", 60.0), P("B", 39.5)], rev=1e12)
    assert ck["kind"] == "pct" and ck["as_pct"] and ck["pass10"]


def test_series_pct_year_never_passes_and_share_uses_amounts_only():
    vc = {"years": {
        "2023": {"products": [P("A", pct=60), P("B", pct=40)]},
        "2024": {"products": [P("A", 600, seg="X"), P("B", 400, seg="X"), P("B", None, 100.0, seg="X")]},
    }}
    ys = M.series(vc, {2023: 1e9, 2024: 1000e6})
    y23, y24 = ys
    assert y23["kind"] == "pct" and y23["pass"] is False and y23["pct_ok"] is True
    assert y24["pass"] and sum(i["share"] for i in y24["items"]) <= 100.01
    assert max(i["share"] for i in y24["items"]) == 60.0


def test_company_unit_fixed_across_years():
    vc = {"years": {
        "2022": {"products": [P("A", 600), P("B", 400)]},          # 백만원으로 맞음
        "2023": {"products": [P("A", 650), P("B", 450)]},
        "2024": {"products": [P("A", 6.5), P("B", 4.4)]},          # 십억원이어야 맞는 해 — 회사 단위(백만원)로는 탈락
    }}
    rev = {2022: 1000e6, 2023: 1100e6, 2024: 1090e6 * 10}
    assert M.company_unit(vc, rev) == 1e6
    ys = {y["year"]: y for y in M.series(vc, rev)}
    assert ys[2022]["pass"] and ys[2023]["pass"] and not ys[2024]["pass"]


def test_contribution_matches_keys_and_flags_new():
    vc = {"years": {
        "2024": {"products": [P("A", 600, seg="X"), P("B", 400, seg="X")]},
        "2025": {"products": [P("A", 900, seg="X"), P("B", 380, seg="X"), P("C", 120, seg="X")]},
        "2025-06": {"products": [P("A", 1)]},
    }}
    v = M.view(vc, {2024: 1000e6, 2025: 1400e6})
    assert [y["year"] for y in v["years"]] == [2024, 2025] and v["n_pass"] == 2
    C = v["contrib"]
    assert C["a"] == 2024 and C["b"] == 2025 and C["new"] == ["X · C"]
    a = next(r for r in C["rows"] if r["label"] == "X · A")
    assert round(a["contrib"]) == round(300 / 280 * 100) and round(a["yoy"]) == 50


def test_failed_year_hides_amounts():
    vc = {"years": {"2025": {"products": [P("A", 600), P("B", 400)]}}}
    v = M.view(vc, {2025: 5000e6})
    y = v["years"][0]
    assert not y["pass"] and y["total"] is None and all(i["amt"] is None for i in y["items"])
    assert y["items"][0]["share"] == 60.0 and v["contrib"] is None


def test_ledger_revenue_skips_ttm(tmp_path):
    (tmp_path / "landscape").mkdir()
    (tmp_path / "landscape" / "000001.json").write_text(json.dumps({"rows": [
        {"year": 2024, "rev": 1e12}, {"year": 2025, "rev": 2e12}, {"year": 2026, "rev": 3e12, "ttm": "2026.2Q"}]}), encoding="utf-8")
    assert M.ledger_revenue("000001", str(tmp_path)) == {2024: 1e12, 2025: 2e12}
    assert M.ledger_revenue("999999", str(tmp_path)) == {}
