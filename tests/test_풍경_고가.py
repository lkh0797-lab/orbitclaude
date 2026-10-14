# -*- coding: utf-8 -*-
"""풍경 차트 달 점의 고가 · 저가(2026-10-14) — 월말 종가 선만 그리면 달 중간 꼭대기가 사라지던 것
(LG전자 2026-06-02 장중 438,000 · 종가 392,500 인데 차트 꼭대기 29만)."""
import os, sys, importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_풍경고가_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp); _sp.loader.exec_module(SRV)

# 5월 말 293,000 → 6월 2일 종가 392,500(장중 438,000) → 6월 말 203,000
PRICES = {"20260528": 225500.0, "20260529": 293000.0, "20260601": 380500.0, "20260602": 392500.0,
          "20260630": 203000.0, "20260701": 193300.0}
OHLC = {"20260528": [234500, 243000, 215000, 225500, 1], "20260529": [255500, 293000, 248500, 293000, 1],
        "20260601": [375000, 380500, 358500, 380500, 1], "20260602": [423000, 438000, 330000, 392500, 1],
        "20260630": [196000, 205000, 194000, 203000, 1], "20260701": [200000, 201000, 190000, 193300, 1]}


def test_month_keeps_mid_month_intraday_peak():
    M, ex = SRV._land_monthly(PRICES, OHLC)
    jun = [m for m in M if m["d"][:6] == "202606"][0]
    assert jun["p"] == 203000 and jun["d"] == "20260630"            # 선은 그대로 월말 종가
    assert jun["hi"] == 438000 and jun["hd"] == "20260602" and jun["ic"] is True
    assert jun["lo"] == 194000 and jun["ld"] == "20260630"
    assert ex["hi"] == {"d": "20260602", "v": 438000, "intraday": True, "close_d": "20260602", "close": 392500}


def test_mismatched_close_falls_back_to_close():
    # 확정 전(10-13 19:02, 넥스트레이드 시간외 중)에 받은 179,200 ≠ 다음 날 받은 일봉 종가 178,300 — 고가 · 저가를 지어 붙이지 않고 종가로
    pr = {"20261013": 179200.0}
    ov = {"20261013": [179300, 182000, 170800, 178300, 1]}
    assert SRV._land_hl(pr, ov, "20261013") == (179200.0, 179200.0, False)
    M, ex = SRV._land_monthly(pr, ov)
    assert M[0]["ic"] is False and M[0]["hi"] == M[0]["lo"] == 179200.0
    assert ex["hi"]["intraday"] is False


def test_no_ohlcv_is_close_basis_and_span_labels():
    assert SRV._land_monthly(PRICES, {})[1]["hi"]["v"] == 392500    # OHLCV 없으면 종가 최고
    assert SRV._land_hl_span(PRICES, OHLC, sorted(PRICES))[2] == "장중"
    assert SRV._land_hl_span(PRICES, {}, sorted(PRICES))[2] == "종가"
    part = dict(OHLC); part.pop("20260701")
    assert SRV._land_hl_span(PRICES, part, sorted(PRICES)) == (438000, 193300, "장중+종가")   # 07-01 은 종가로
    assert SRV._land_hl_span(PRICES, OHLC, []) == (None, None, None)


def test_start_filter_and_empty():
    M, ex = SRV._land_monthly(PRICES, OHLC, "20260601")
    assert [m["d"][:6] for m in M] == ["202606", "202607"] and ex["hi"]["v"] == 438000
    assert SRV._land_monthly({}, {}) == ([], None)


def test_land_day_is_last_market_close():
    # 판의 날 = 그날 값이 굳은 가장 최근 날(평일 20:10) — 확정 전에 그린 판은 그 뒤 다시 그린다
    assert SRV._land_day() == SRV.FIN.last_final().date().isoformat()
