# -*- coding: utf-8 -*-
"""서버 기본적분석 배선 — fundamental_view(원문 두 절 + 캐시만 · 네트워크 없음 · 결과 캐시 sig) · 라우트 · 모듈 없을 때 500."""
import os
import sys
import json
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("서버_기본분석_시험", os.path.join(BASE, "서버.py"))
SRV = ilu.module_from_spec(_sp)
_sp.loader.exec_module(SRV)

BIZ = """1. 사업의 개요
당사는 아웃도어 의류를 해외 바이어에게 주문 생산으로 공급하는 회사입니다.
사업부문
주요사업영역
매출비중
제조 사업부문
의류 생산 수출
90%
유통 사업부문
브랜드 유통
10%
3. 원재료 및 생산설비
나. 주요 해외 생산설비 현황
소 재 지
베트남
4. 매출 및 수주상황
수 출
9,000
내 수
1,000
5. 위험관리 및 파생거래
환율이 오르면 수익성에 긍정적인 영향이 있습니다.
"""
FIN = "(단위 : 천원)\n환율이 10% 상승할 경우\n1,000\n2,000\n"


def _src():
    with open(os.path.join(BASE, "서버.py"), "r", encoding="utf-8") as fh:
        return fh.read()


def _company(tmp_path, monkeypatch, with_cache=True):
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "FUND_DIR", str(tmp_path / "기본분석"))
    monkeypatch.setattr(SRV, "IND_DIR", str(tmp_path / "산업"))
    c = {"code": "000001", "name": "시험회사", "count": 2, "reports": [
        {"stamp": "2025-12", "label": "사업보고서", "tag": "", "rcept": "20260319000001", "sections": []},
        {"stamp": "2026-06", "label": "반기보고서", "tag": "", "rcept": "20260814000001", "sections": []}]}
    monkeypatch.setattr(SRV, "INDEX", {"companies": [c], "built": 0})
    monkeypatch.setattr(SRV, "_sec_text", lambda c_, r, norm: (BIZ if norm == "사업의 내용" else FIN) if r["label"] == "사업보고서" else "")
    monkeypatch.setattr(SRV, "_fund_vc", lambda code: ({}, {}, None))
    monkeypatch.setattr(SRV, "_watch_export", lambda code: {})
    pts = [{"n": 8090 + i, "label": "%dQ%d" % (2022 + i // 4, i % 4 + 1), "기준일": "2026%02d14" % (i % 12 + 1), "매출_TTM": 1e12 * (1 + 0.05 * i),
            "영업이익_TTM": 1e11 * (1 + 0.04 * i), "EPS_TTM": 1000 + 50 * i, "국면": "확장 유지", "속도": 10.0, "가속B": 1.0, "매출YoY": 12.0} for i in range(14)]
    monkeypatch.setattr(SRV, "_fund_druck", lambda code: ({"points": pts, "basis": "매출"}, False) if with_cache else (None, False))
    monkeypatch.setattr(SRV, "_land_read", lambda code: {"rows": [{"year": 2025, "rev": 1e12, "debt": 1e11, "cash": 5e11, "roe": 10.0}], "decide": {"per": 8.0, "pct": 20.0, "zone": "싸다", "date": "20261021"}} if with_cache else None)
    monkeypatch.setattr(SRV, "_orb2_backlog", lambda c_: ({}, []))
    monkeypatch.setattr(SRV, "MACRO", None)
    monkeypatch.setattr(SRV, "_fund_fx", lambda: {})
    px = {}
    for i in range(14):
        px["%d%02d28" % (2022 + i // 4, (i % 4) * 3 + 3)] = 10000 * (1 + 0.05 * i)
    monkeypatch.setattr(SRV, "_px_file", lambda code: px if with_cache else {})
    monkeypatch.setattr(SRV, "_fund_reports", lambda code, name, px_: None)
    monkeypatch.setattr(SRV, "_disc_risk", lambda: {})
    monkeypatch.setattr(SRV, "_fund_sector", lambda code: None)
    def _no_net(*a, **k):
        raise AssertionError("요청 경로에서 네트워크 함수가 불렸다")
    monkeypatch.setattr(SRV, "invest_view", _no_net)
    monkeypatch.setattr(SRV, "reports_view", _no_net)
    return c


def test_view_assembles_from_text_and_caches(monkeypatch, tmp_path):
    _company(tmp_path, monkeypatch)
    v = SRV.fundamental_view("000001")
    assert v["code"] == "000001" and v["report"]["rcept"] == "20260319000001" and not v.get("error")
    assert [(s["name"], s["pct"]) for s in v["segs"]] == [("제조 사업부문", 90.0), ("유통 사업부문", 10.0)]
    assert v["export"]["export_pct"] == 90.0 and v["plants"] == ["베트남"]
    assert v["line"].startswith("시험회사는 제조 사업부문 90% · 유통 사업부문 10%로 매출을 올린다. 수출 90%. 공장 베트남.")
    fx = next(r for r in v["drivers"] if r["factor"].startswith("원/달러"))
    assert fx["up"] == 1 and fx["basis"] == "공시 숫자" and "90%" in fx["why"]
    rate = next(r for r in v["drivers"] if r["factor"] == "금리 ↑")
    assert rate["up"] == 1                                                    # 현금 > 빚(−40%)
    assert v["profit"]["rev_ttm"] == pts_last(v) and v["profit"]["margin"] is not None and v["balance"]["nd_ratio"] < 0
    assert v["fx_sens"] and v["fx_sens"][0]["nums"] == [1000.0, 2000.0] and v["fx_sens"][0]["unit"] == "천원"
    names = [f["name"] for f in v["followers"]]
    assert "매출(최근 4분기 합)" in names and all(f["n"] >= 8 for f in v["followers"] if f["r"] is not None)
    # 캐시 파일이 생기고, 같은 sig 면 다시 조립하지 않는다
    p = os.path.join(str(tmp_path / "기본분석"), "000001.json")
    assert os.path.exists(p) and json.load(open(p, encoding="utf-8"))["sig"] == v["sig"]
    monkeypatch.setattr(SRV, "_fund_build", lambda *a: (_ for _ in ()).throw(AssertionError("다시 조립하면 안 된다")))
    assert SRV.fundamental_view("000001")["line"] == v["line"]
    assert SRV.fundamental_view("없는코드") is None


def pts_last(v):
    return v["profit"]["rev_ttm"]


def test_view_without_caches_still_answers(monkeypatch, tmp_path):
    _company(tmp_path, monkeypatch, with_cache=False)
    v = SRV.fundamental_view("000001")
    assert not v.get("error") and v["segs"] and v["profit"]["rev_ttm"] is None and v["followers"] == [] and v["px"] is None
    assert v["balance"]["nd_ratio"] is None and v["value"]["zone"] is None


def test_route_and_module_guard(monkeypatch, tmp_path):
    s = _src()
    assert 'if path == "/api/fundamental":' in s and "fundamental_view(q.get(\"code\", \"\"), refresh=refresh)" in s
    assert "refresh and not self._same_origin_get()" in s                   # 다시 조립은 이 PC 화면에서만
    _company(tmp_path, monkeypatch)
    monkeypatch.setattr(SRV, "FUND", None)
    v = SRV.fundamental_view("000001")
    assert v.get("module") and "기본분석.py" in v["error"]
