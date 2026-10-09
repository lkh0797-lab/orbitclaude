# -*- coding: utf-8 -*-
import os, sys, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
DRK = ilu.module_from_spec(_sp); _sp.loader.exec_module(DRK)


def row(sj, acc_id, name, **amt):
    r = {"sj_div": sj, "account_id": acc_id, "account_nm": name, "rcept_no": amt.pop("rcept", "20240514000123")}
    r.update({k: str(v) for k, v in amt.items()})
    return r


def stmt(rows, status="000"):
    return {"status": status, "list": rows}


def fake_fetch(table):
    """table: {(year, reprt, fs): stmt} — 없으면 013."""
    def f(corp, year, reprt, fs_div="CFS"):
        return table.get((int(year), str(reprt), fs_div), {"status": "013", "list": []})
    return f


def test_period_data_reads_comparatives(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=1200, thstrm_add_amount=2300,
                frmtrm_q_amount=1000, frmtrm_add_amount=1900, rcept="20240814000555"),
            row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent", "지배기업 소유주지분", thstrm_amount=90, thstrm_add_amount=170,
                frmtrm_q_amount=80, frmtrm_add_amount=150)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11012", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 2)
    assert d["매출액"] == 1200 and d["매출액_누적"] == 2300
    assert d["매출액_전"] == 1000 and d["매출액_전누적"] == 1900
    assert d["지배순이익"] == 90 and d["_fs"] == "CFS" and d["_src"] == "api"
    assert d["_rcept"] == "20240814" and d["_transient"] is False


def test_period_data_q1_comparative_falls_back_to_add(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=500, thstrm_add_amount=500, frmtrm_add_amount=450)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["매출액_전"] == 450


def test_period_data_annual_reads_frmtrm(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=5000, frmtrm_amount=4200)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11011", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 4)
    assert d["매출액"] == 5000 and d["매출액_전연"] == 4200


def test_period_data_ofs_fallback_marks_fs(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=10)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "OFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["_fs"] == "OFS"


def test_period_data_transient(monkeypatch):
    monkeypatch.setattr(DRK.FIN, "fetch_statement",
                        lambda *a, **k: {"status": "020", "list": [], "transient": True})
    d = DRK.period_data("C", 2024, 1)
    assert d == {"_transient": True}
