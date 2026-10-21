# -*- coding: utf-8 -*-
import os, sys, json, time, importlib.util as ilu
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("드러켄밀러", os.path.join(BASE, "드러켄밀러.py"))
DRK = ilu.module_from_spec(_sp); _sp.loader.exec_module(DRK)
FIN = DRK.FIN
NO_TAG = FIN.NO_TAG
OWNER = "ifrs-full_ProfitLossAttributableToOwnersOfParent"
NCI = "ifrs-full_ProfitLossAttributableToNoncontrollingInterests"


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


# ------------------------------------------------------------------ period_data 보강
def test_period_data_ofs_transient(monkeypatch):
    """CFS 는 013(없음) · OFS 는 일시 오류 — 그 분기는 '아직 모름'(transient)이지 '없음'(None)이 아니다."""
    def f(corp, year, reprt, fs_div="CFS"):
        if fs_div == "CFS":
            return {"status": "013", "list": []}
        return {"status": "020", "list": [], "transient": True}
    monkeypatch.setattr(DRK.FIN, "fetch_statement", f)
    assert DRK.period_data("C", 2024, 1) == {"_transient": True}


def test_period_data_both_013_is_none(monkeypatch):
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({}))
    assert DRK.period_data("C", 2024, 1) is None


def test_period_data_transient_result_rows_are_ignored(monkeypatch):
    """transient 결과에 본문 대체 줄이 실려 와도 드러켄밀러는 쓰지 않는다."""
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=10)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement",
                        lambda *a, **k: {"status": "body", "list": rows, "transient": True})
    assert DRK.period_data("C", 2024, 1) == {"_transient": True}


def test_period_data_drops_frmtrm_for_non_annual(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=1200, frmtrm_amount=9999, frmtrm_q_amount=1000)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11012", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 2)
    assert "매출액_전연" not in d and d["매출액_전"] == 1000


def test_period_data_q1_frmtrm_q_wins_over_frmtrm_add(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=500, thstrm_add_amount=500,
                frmtrm_q_amount=470, frmtrm_add_amount=450)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 1)
    assert d["매출액_전"] == 470 and d["매출액_전누적"] == 450


def test_period_data_body_source_is_marked(monkeypatch):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=10)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows, status="body")}))
    d = DRK.period_data("C", 2024, 1)
    assert d["_src"] == "body" and d["_transient"] is False


def test_period_data_rcept_none_without_rcept_no(monkeypatch):
    r = row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=10)
    del r["rcept_no"]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt([r])}))
    assert DRK.period_data("C", 2024, 1)["_rcept"] is None


def test_period_data_rows_without_data_keys_is_none(monkeypatch):
    rows = [row("IS", "ifrs-full_Unrelated", "기타", thstrm_amount=10)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1) is None


# ------------------------------------------------------------------ 지배순이익
def test_owner_profit_read_from_tagged_row(monkeypatch):
    """지배기업 귀속 줄이 있으면 대체 계산을 하지 않고 그 값을 쓴다."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=100),
            row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=70),
            row("IS", NCI, "비지배지분", thstrm_amount=30)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["지배순이익"] == 70


def test_owner_profit_fallback_subtracts_nci_in_every_field(monkeypatch):
    """지배 줄이 없으면 당기순이익 − 비지배 몫. 값 · 누적 · 전년 같은 분기 · 전년 같은 누적 · 전년 연간 모두."""
    amt = dict(thstrm_amount=100, thstrm_add_amount=300, frmtrm_q_amount=80, frmtrm_add_amount=250, frmtrm_amount=900)
    nci = dict(thstrm_amount=-10, thstrm_add_amount=20, frmtrm_q_amount=5, frmtrm_add_amount=15, frmtrm_amount=40)
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", **amt),
            row("IS", NCI, "비지배지분", **nci)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11011", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 4)
    assert d["지배순이익"] == 110 and d["지배순이익_누적"] == 280
    assert d["지배순이익_전"] == 75 and d["지배순이익_전누적"] == 235 and d["지배순이익_전연"] == 860


def test_owner_profit_fallback_nci_matched_by_name_when_untagged(monkeypatch):
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=100),
            row("IS", NO_TAG, "비지배지분", thstrm_amount=-30)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["지배순이익"] == 130


def test_owner_profit_fallback_without_nci_row_equals_net_income(monkeypatch):
    amt = dict(thstrm_amount=100, thstrm_add_amount=300, frmtrm_q_amount=80, frmtrm_add_amount=250)
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", **amt)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11012", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 2)
    assert (d["지배순이익"], d["지배순이익_누적"], d["지배순이익_전"], d["지배순이익_전누적"]) == (100, 300, 80, 250)
    assert "지배순이익_전연" not in d                    # 반기 보고서의 전년 연간 칸은 쓰지 않는다


def test_owner_profit_fallback_skipped_when_nci_exists_but_field_is_empty(monkeypatch):
    """비지배 줄은 있는데 그 칸만 비면 모르는 값이다 — 당기순이익을 그대로 쓰면 틀린다."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=100, frmtrm_q_amount=80),
            row("IS", NCI, "비지배지분", thstrm_amount=10)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11012", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 2)
    assert d["지배순이익"] == 90 and "지배순이익_전" not in d


def test_owner_profit_ignores_comprehensive_income_rows(monkeypatch):
    """실제 원장 모양(00100601 2024Q1): 총포괄손익 귀속 줄(태그 있음)이 먼저 오고, 당기순이익 귀속 줄은 태그가 없다."""
    rows = [row("CIS", "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent", "지배기업지분", thstrm_amount=-1125),
            row("CIS", "ifrs-full_ComprehensiveIncomeAttributableToNoncontrollingInterests", "비지배지분", thstrm_amount=-282),
            row("CIS", "ifrs-full_ProfitLoss", "당기순이익(손실)", thstrm_amount=-1412),
            row("CIS", NO_TAG, "지배기업지분", thstrm_amount=-1130),
            row("CIS", NO_TAG, "비지배지분", thstrm_amount=-282)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["지배순이익"] == -1130


def test_owner_profit_fallback_ignores_comprehensive_nci(monkeypatch):
    """당기순이익 귀속 줄이 없고 총포괄 귀속 줄만 있으면 그 비지배 몫은 빼지 않는다(비지배 줄 없음 = 당기순이익)."""
    rows = [row("CIS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=100),
            row("CIS", "ifrs-full_ComprehensiveIncomeAttributableToNoncontrollingInterests", "비지배지분", thstrm_amount=7)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["지배순이익"] == 100


def test_owner_profit_q1_prev_falls_back_to_prev_cumulative(monkeypatch):
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=100, frmtrm_add_amount=80)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["지배순이익_전"] == 80


# ------------------------------------------------------------------ 지배순이익 — 지배 + 비지배 = 당기순이익 검산으로 고르기
def _pd(monkeypatch, rows, year=2023, q=3):
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(year, DRK.REPRT_BY_Q[q], "CFS"): stmt(rows)}))
    return DRK.period_data("C", year, q)


def test_owner_profit_skips_untagged_comprehensive_split_listed_first(monkeypatch):
    """SK(034730) 2023 3분기 원장 모양: 총포괄 귀속 줄(태그 없음, ord 14)이 당기순이익 귀속 줄(태그 없음, ord 37)보다 먼저 온다 —
    이름이 똑같아 예전엔 총포괄 4,757억을 집었다. 지배 + 비지배 = 분기순이익인 줄은 3,267억 쪽."""
    rows = [row("CIS", "ifrs-full_ComprehensiveIncome", "분기연결총포괄이익(손실)", thstrm_amount=1879819e6, thstrm_add_amount=2810226e6),
            row("CIS", NO_TAG, "비지배지분", thstrm_amount=1404154e6, thstrm_add_amount=1861293e6),
            row("CIS", NO_TAG, "지배기업소유주지분", thstrm_amount=475665e6, thstrm_add_amount=948933e6),
            row("CIS", "ifrs-full_ProfitLoss", "분기순이익(손실)", thstrm_amount=1379684e6, thstrm_add_amount=1172106e6),
            row("CIS", NO_TAG, "비지배지분", thstrm_amount=1052995e6, thstrm_add_amount=864233e6),
            row("CIS", NO_TAG, "지배기업소유주지분", thstrm_amount=326689e6, thstrm_add_amount=307873e6)]
    d = _pd(monkeypatch, rows)
    assert d["지배순이익"] == 326689e6 and d["지배순이익_누적"] == 307873e6


def test_owner_profit_name_row_beats_junk_tagged_row(monkeypatch):
    """위메이드(112040) 2021 3분기: 지배 태그 줄 값이 6,455원(엉터리) — 이름 줄 168.8억이 검산에 맞는다."""
    rows = [row("CIS", "ifrs-full_ProfitLoss", "당기순이익(손실)", thstrm_amount=17865650805, thstrm_add_amount=60461676043),
            row("CIS", NO_TAG, "지배기업의 소유주에 귀속될 당기순이익", thstrm_amount=16883112501, thstrm_add_amount=58466432823),
            row("CIS", NO_TAG, "비지배지분에 귀속될 당기순이익", thstrm_amount=982538304, thstrm_add_amount=1995243220),
            row("CIS", OWNER, "지배기업의 소유주에게 귀속되는 당기순이익(손실)", thstrm_amount=6455, thstrm_add_amount=6455)]
    d = _pd(monkeypatch, rows)
    assert d["지배순이익"] == 16883112501 and d["지배순이익_누적"] == 58466432823


def test_owner_profit_untagged_total_beats_tagged_continuing_value(monkeypatch):
    """삼성전기(009150) 2020 3분기: 지배 태그 줄 값은 계속영업 몫(지배 + 비지배 = 계속영업분기순이익) — 태그 없는 줄이 분기순이익과 맞는다."""
    rows = [row("CIS", NO_TAG, "계속영업분기순이익", thstrm_amount=236542486498),
            row("CIS", "ifrs-full_ProfitLoss", "분기순이익", thstrm_amount=239996465840),
            row("CIS", OWNER, "지배기업 소유주지분", thstrm_amount=226748617120),
            row("CIS", NCI, "비지배지분", thstrm_amount=9793869378),
            row("CIS", NO_TAG, "지배기업 소유주지분", thstrm_amount=230202596462),
            row("CIS", NO_TAG, "비지배지분", thstrm_amount=9793869378),
            row("CIS", "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent", "지배기업 소유주지분", thstrm_amount=218335585023)]
    assert _pd(monkeypatch, rows)["지배순이익"] == 230202596462


def test_owner_profit_skips_discontinued_attributable_row(monkeypatch):
    """한미반도체(042700) 2016 3분기: '지배기업지분중단영업순손실' 0 이 먼저 와서 지배순이익 = 0 이었다."""
    rows = [row("CIS", "ifrs_ProfitLossFromDiscontinuedOperations", "중단영업순손실", thstrm_amount=0),
            row("CIS", NO_TAG, "지배기업지분중단영업순손실", thstrm_amount=0),
            row("CIS", NO_TAG, "비지배지분중단영업순손실", thstrm_amount=0),
            row("CIS", "ifrs_ProfitLoss", "당기순이익", thstrm_amount=4145045099),
            row("CIS", NO_TAG, "지배기업지분순이익", thstrm_amount=4145045099),
            row("CIS", NO_TAG, "비지배지분순손실", thstrm_amount=0)]
    assert _pd(monkeypatch, rows, 2016)["지배순이익"] == 4145045099


def test_owner_profit_skips_per_share_row(monkeypatch):
    """AJ네트웍스(095570) 2026 반기: '지배기업지분에 대한 주당순손익' 632원이 이름 정규식에 걸렸다.
    지배 귀속은 계속 + 중단 태그 줄로만 나뉘어 있다 — 둘의 합(검산 맞음)."""
    rows = [row("CIS", "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent", "지배기업소유주지분", thstrm_amount=30274988000),
            row("CIS", "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations", "지배기업지분에 대한 주당순손익", thstrm_amount=632),
            row("CIS", "ifrs-full_ProfitLoss", "반기순이익", thstrm_amount=28331292000),
            row("CIS", NCI, "비지배지분 귀속 반기순이익(손실)", thstrm_amount=34037000),
            row("CIS", "ifrs-full_IncomeFromContinuingOperationsAttributableToOwnersOfParent", "계속영업반기순이익", thstrm_amount=28297673000),
            row("CIS", "ifrs-full_IncomeFromDiscontinuedOperationsAttributableToOwnersOfParent", "중단영업반기순이익", thstrm_amount=-416000)]
    assert _pd(monkeypatch, rows, 2026, 2)["지배순이익"] == 28297257000


def test_owner_profit_keeps_controlling_shareholder_name_with_dang(monkeypatch):
    """'지배주주당기순이익' 은 지배주주 + 당기 — '주당' 이 끼어 있어도 주당이익 줄이 아니다."""
    for nm in ("지배주주당기순이익(손실)", "지배기업주주당기순이익"):
        rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=500e8),
                row("IS", NO_TAG, nm, thstrm_amount=470e8),
                row("IS", NO_TAG, "지배주주 기본주당순이익", thstrm_amount=1234),
                row("IS", NCI, "비지배주주당기순이익", thstrm_amount=30e8)]
        assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 470e8, nm


def test_owner_profit_skip_named_tagged_row_is_last_resort(monkeypatch):
    """JW중외제약(001060) 2024 연간: 지배 태그 줄 이름이 '지배기업지분포괄이익'(값 = 당기순이익), 비지배 줄은 그 칸이 빔 —
    태그로 맞은 줄은 이름이 걸려도 마지막 후보로 남는다. 검산에 맞는 다른 줄이 있으면 그 줄이 이긴다."""
    rows = [row("CIS", "ifrs-full_ProfitLoss", "당기순이익(손실)", thstrm_amount=65040120873, frmtrm_amount=38430259560),
            row("CIS", NCI, "비지배지분순이익", frmtrm_amount=1423925565),
            row("CIS", OWNER, "지배기업지분포괄이익", thstrm_amount=65040120873, frmtrm_amount=37006333995)]
    d = _pd(monkeypatch, rows, 2024, 4)
    assert d["지배순이익"] == 65040120873 and d["지배순이익_전연"] == 37006333995
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=500e8),
            row("IS", OWNER, "지배기업 소유주지분(계속영업)", thstrm_amount=300e8),
            row("IS", NO_TAG, "지배기업 소유주지분", thstrm_amount=480e8),
            row("IS", NCI, "비지배지분", thstrm_amount=20e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 480e8


def test_owner_profit_skips_continuing_attributable_row(monkeypatch):
    """계속영업 귀속 줄만 이름에 걸리면 버리고 당기순이익 − 비지배로(중단영업 몫을 놓치지 않게)."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=500e8),
            row("IS", NO_TAG, "지배기업소유주지분 계속영업이익", thstrm_amount=300e8),
            row("IS", NCI, "비지배지분", thstrm_amount=20e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 480e8


def test_owner_profit_without_nci_rows_checks_against_net_income(monkeypatch):
    """비지배 줄이 아예 없으면 지배 = 당기순이익인 줄이 맞는 줄이다(태그 쪽 0 원은 엉터리)."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=50e8),
            row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=0),
            row("IS", NO_TAG, "지배기업 소유주지분 순이익", thstrm_amount=50e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 50e8


def test_owner_profit_junk_without_passing_row_falls_back_to_net_minus_nci(monkeypatch):
    """검산에 맞는 줄이 없고 고른 지배 값이 당기순이익의 1%도 안 되면 엉터리 — 당기순이익 − 비지배(변곡점.owner_parts 와 같은 문턱)."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=200e8),
            row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=6455),
            row("IS", NCI, "비지배지분", thstrm_amount=10e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 190e8


def test_owner_profit_keeps_tagged_row_when_check_fails_but_value_is_material(monkeypatch):
    """검산이 어긋나도 값이 당기순이익의 1%를 넘으면 태그 줄을 믿는다(당기순이익 줄 쪽이 틀렸을 수 있다)."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=200e8),
            row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=150e8),
            row("IS", NCI, "비지배지분", thstrm_amount=10e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 150e8


def test_owner_profit_tag_wins_when_net_income_missing(monkeypatch):
    """당기순이익이 없는 칸은 검산할 수 없다 — 예전대로 태그 점수."""
    rows = [row("IS", NO_TAG, "지배기업 소유주지분", thstrm_amount=70e8),
            row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=60e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 60e8


def test_owner_profit_check_tolerance(monkeypatch):
    """±0.2%(작으면 ±1억) 안이면 맞음 — 반올림 어긋남(천 원 단위)은 받아들이고, 그보다 크면 다음 후보로."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=1000e8),
            row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=890e8),           # 890 + 100 = 990 — 1% 어긋남(태그여도 진다)
            row("IS", NO_TAG, "지배기업 소유주지분", thstrm_amount=900.5e8),       # 900.5 + 100 = 1000.5 — 0.05%
            row("IS", NCI, "비지배지분", thstrm_amount=100e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 900.5e8
    small = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=10e8),     # 작은 값은 ±1억
             row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=7e8),
             row("IS", NO_TAG, "지배기업 소유주지분", thstrm_amount=8.5e8),
             row("IS", NCI, "비지배지분", thstrm_amount=2e8)]
    assert _pd(monkeypatch, small, 2024, 1)["지배순이익"] == 8.5e8


def test_owner_profit_nci_fallback_skips_comprehensive_named_row(monkeypatch):
    """지배 줄이 없을 때 빼는 비지배 몫도 포괄 · 주당 · 계속/중단 이름 줄은 쓰지 않는다."""
    rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm_amount=100e8),
            row("IS", NO_TAG, "비지배지분 포괄손익", thstrm_amount=40e8),
            row("IS", NO_TAG, "비지배지분", thstrm_amount=10e8)]
    assert _pd(monkeypatch, rows, 2024, 1)["지배순이익"] == 90e8


# ------------------------------------------------------------------ _fetch · NET 예산
@pytest.fixture
def fin_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(DRK.FIN, "FIN_DIR", str(tmp_path))
    monkeypatch.setitem(DRK.NET, "budget", None)
    monkeypatch.setitem(DRK.NET, "used", 0)
    return tmp_path


def _cache_file(dirpath, corp, year, reprt, fs="CFS"):
    p = dirpath / ("%s_%s_%s_%s.json" % (corp, year, reprt, fs))
    p.write_text("{}", encoding="utf-8")
    return p


def test_fetch_budget_charged_only_when_cache_file_missing(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a: calls.append(a) or stmt([]))
    _cache_file(fin_dir, "C", 2024, "11013")
    monkeypatch.setitem(DRK.NET, "budget", 1)
    DRK._fetch("C", 2024, "11013", "CFS", True)             # 캐시 파일이 있다 — 세지 않는다
    assert DRK.NET["used"] == 0 and len(calls) == 1
    DRK._fetch("C", 2024, "11012", "CFS", True)             # 없다 — 한 번 센다
    assert DRK.NET["used"] == 1 and len(calls) == 2
    DRK._fetch("C", 2024, "11013", "CFS", True)             # 캐시는 예산이 바닥나도 읽는다
    assert DRK.NET["used"] == 1 and len(calls) == 3


def test_fetch_over_budget_is_transient_and_skips_network(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a: calls.append(a) or stmt([]))
    monkeypatch.setitem(DRK.NET, "budget", 1)
    DRK._fetch("C", 2024, "11012", "CFS", True)
    out = DRK._fetch("C", 2024, "11014", "CFS", True)
    assert out == {"status": "budget", "list": [], "transient": True}
    assert len(calls) == 1 and DRK.NET["used"] == 1


def test_fetch_online_is_not_budgeted(monkeypatch, fin_dir):
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a: stmt([]))
    monkeypatch.setitem(DRK.NET, "budget", 0)
    out = DRK._fetch("C", 2024, "11012", "CFS", False)
    assert out == stmt([]) and DRK.NET["used"] == 0


def test_fetch_unlimited_budget_still_counts(monkeypatch, fin_dir):
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a: stmt([]))
    DRK._fetch("C", 2024, "11012", "CFS", True)
    DRK._fetch("C", 2024, "11014", "CFS", True)
    assert DRK.NET["used"] == 2


def test_period_data_offline_over_budget_is_transient(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a: calls.append(a) or stmt([]))
    monkeypatch.setitem(DRK.NET, "budget", 0)
    assert DRK.period_data("C", 2024, 1, offline=True) == {"_transient": True}
    assert calls == []


# ------------------------------------------------------------------ 재무.fetch_statement
class _Resp:
    def __init__(self, js=None, err=None):
        self._js, self._err = js, err

    def raise_for_status(self):
        if self._err:
            raise self._err

    def json(self):
        return self._js


class _Body:
    """본문 파서 자리 — 원장이 비면 이 줄을 돌려준다."""
    LIST = [{"sj_div": "IS", "account_id": "-", "account_nm": "매출액", "thstrm_amount": "5"}]

    @staticmethod
    def statement(corp, year, reprt, fs_div):
        return {"status": "body", "list": list(_Body.LIST)}


@pytest.fixture
def dart(monkeypatch, tmp_path):
    """DART 호출을 가로챈다: dart.reply = 응답 또는 예외, dart.calls = 부른 횟수, dart.sleeps = 쉰 횟수."""
    class Box:
        reply, calls, sleeps = None, 0, 0
    box = Box()
    box.dir = tmp_path
    monkeypatch.setattr(FIN, "FIN_DIR", str(tmp_path))
    monkeypatch.setattr(FIN, "BODY", None)

    def get(url, **kw):
        box.calls += 1
        if isinstance(box.reply, Exception):
            raise box.reply
        return box.reply
    monkeypatch.setattr(FIN.requests, "get", get)
    monkeypatch.setattr(FIN.time, "sleep", lambda s: setattr(box, "sleeps", box.sleeps + 1))
    return box


def _files(d):
    return sorted(p.name for p in d.iterdir())


def test_fetch_network_exception_is_transient_not_raised(dart):
    dart.reply = ConnectionError("down")
    out = FIN.fetch_statement("C", 2024, "11013")
    assert out["transient"] is True and out["list"] == [] and out["status"] == "net"
    assert _files(dart.dir) == [] and dart.sleeps == 0


def test_fetch_http_error_is_transient(dart):
    dart.reply = _Resp(err=FIN.requests.HTTPError("500"))
    out = FIN.fetch_statement("C", 2024, "11013")
    assert out["transient"] is True and out["list"] == []
    assert _files(dart.dir) == []


def test_fetch_network_exception_keeps_body_substitution(dart, monkeypatch):
    """기존 호출처(metrics_for · annual_actuals …)는 네트워크가 끊겨도 본문 대체를 그대로 받는다."""
    monkeypatch.setattr(FIN, "BODY", _Body)
    dart.reply = ConnectionError("down")
    out = FIN.fetch_statement("C", 2024, "11013")
    assert out["transient"] is True and out["status"] == "body" and out["list"] == _Body.LIST
    assert _files(dart.dir) == []


@pytest.mark.parametrize("status", ["020", "800"])
def test_fetch_transient_status_is_marked_and_not_cached(dart, status):
    dart.reply = _Resp({"status": status, "message": "x"})
    out = FIN.fetch_statement("C", 2024, "11013")
    assert out["transient"] is True and out["status"] == status and out["list"] == []
    assert _files(dart.dir) == []                           # 일시 오류는 캐시하지 않는다
    assert dart.sleeps == 1                                 # 쉬는 것은 한 번
    FIN.fetch_statement("C", 2024, "11013")
    assert dart.calls == 2                                  # 다음에 다시 묻는다


@pytest.mark.parametrize("status", ["020", "800"])
def test_fetch_transient_status_keeps_body_substitution(dart, monkeypatch, status):
    monkeypatch.setattr(FIN, "BODY", _Body)
    dart.reply = _Resp({"status": status})
    out = FIN.fetch_statement("C", 2024, "11013")
    assert out["transient"] is True and out["status"] == "body" and out["list"] == _Body.LIST
    assert _files(dart.dir) == []


def test_fetch_000_is_cached_and_not_transient(dart):
    lst = [{"sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": "7"},
           {"sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계", "thstrm_amount": "1"},
           {"sj_div": "CF", "account_id": "x", "account_nm": "현금흐름", "thstrm_amount": "1"}]
    dart.reply = _Resp({"status": "000", "list": lst})
    out = FIN.fetch_statement("C", 2024, "11013")
    assert "transient" not in out and out["list"] == lst and dart.sleeps == 1
    assert _files(dart.dir) == ["C_2024_11013_CFS.json"]
    dart.reply = ConnectionError("down")                    # 캐시가 있으면 네트워크를 건드리지 않는다
    again = FIN.fetch_statement("C", 2024, "11013")
    assert again["list"] == lst and "transient" not in again and dart.calls == 1


def test_fetch_013_is_cached_and_not_transient(dart):
    dart.reply = _Resp({"status": "013", "message": "no data"})
    out = FIN.fetch_statement("C", 2024, "11011", "OFS")
    assert "transient" not in out and out["status"] == "013" and out["list"] == []
    assert _files(dart.dir) == ["C_2024_11011_OFS.json"]
    dart.reply = ConnectionError("down")
    assert "transient" not in FIN.fetch_statement("C", 2024, "11011", "OFS") and dart.calls == 1


def test_fetch_013_still_uses_body_without_marking_transient(dart, monkeypatch):
    monkeypatch.setattr(FIN, "BODY", _Body)
    dart.reply = _Resp({"status": "013"})
    out = FIN.fetch_statement("C", 2024, "11013")
    assert out["status"] == "body" and out["list"] == _Body.LIST and "transient" not in out
    assert _files(dart.dir) == ["C_2024_11013_CFS.json"]


def test_period_data_over_fetch_statement_network_down(dart, monkeypatch):
    """끝에서 끝까지: 네트워크가 끊기고 본문 대체가 있어도 드러켄밀러는 그 분기를 만들지 않는다."""
    monkeypatch.setattr(FIN, "BODY", _Body)
    dart.reply = ConnectionError("down")
    assert DRK.period_data("C", 2024, 1) == {"_transient": True}



def mk_q(rev, cum=None, prev=None, prev_cum=None, prev_ann=None, rc="20240514", fs="CFS", src="api", op=None, ni=None,
         capex=None, **extra):
    d = {"매출액": rev, "_fs": fs, "_src": src, "_rcept": rc, "_transient": False}
    if capex is not None: d["CAPEX"] = capex
    d.update(extra)
    if cum is not None: d["매출액_누적"] = cum
    if prev is not None: d["매출액_전"] = prev
    if prev_cum is not None: d["매출액_전누적"] = prev_cum
    if prev_ann is not None: d["매출액_전연"] = prev_ann
    if op is not None: d["영업이익"] = op
    if ni is not None: d["지배순이익"] = ni
    return d


def run_series(monkeypatch, table, years, meta=None):
    monkeypatch.setattr(DRK, "period_data", lambda corp, y, q, offline=False, **kw: table.get((y, q)))
    return DRK.series("C", "000000", years, meta=meta or {})


def test_gap_quarter_dense_grid(monkeypatch):
    t = {(2023, 1): mk_q(100), (2023, 2): mk_q(110), (2023, 4): None, (2023, 3): mk_q(120), (2024, 1): mk_q(130, prev=100)}
    pts = run_series(monkeypatch, t, [2023, 2024])
    assert [p["label"] for p in pts] == ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1"]
    assert pts[3].get("매출액") is None and "gap" in pts[3]["품질"]
    assert pts[4]["매출_TTM"] is None             # 창 안에 빈 분기 — TTM 안 냄


def test_q4_basis_mismatch(monkeypatch):
    t = {(2020, 3): mk_q(70, cum=7233, fs="CFS"), (2020, 4): mk_q(1566, prev_ann=1660, fs="OFS")}
    pts = run_series(monkeypatch, t, [2020])
    q4 = [p for p in pts if p["q"] == 4][0]
    assert q4["매출액"] is None and "basis" in q4["품질"]


def test_q4_scope_restated(monkeypatch):
    # DL 2020: 사업보고서 frmtrm/전년 사업보고서 thstrm = 0.171, Q3 frmtrm_add/전년 Q3 thstrm_add = 0.978 → 범위가 다름
    t = {(2019, 3): mk_q(2400, cum=6956), (2019, 4): mk_q(9700),
         (2020, 3): mk_q(2300, cum=7233, prev_cum=6803), (2020, 4): mk_q(1566, prev_ann=1660)}
    pts = run_series(monkeypatch, t, [2019, 2020])
    q4 = [p for p in pts if p["label"] == "2020Q4"][0]
    assert q4["매출액"] is None and "basis" in q4["품질"]


def test_restated_yoy_and_amended(monkeypatch):
    t = {(2023, 2): mk_q(100), (2024, 2): mk_q(130, prev=104, rc="20241020")}
    pts = run_series(monkeypatch, t, [2023, 2024], meta={"filed": {2024 * 4 + 1: "20240814"}})
    p = [x for x in pts if x["label"] == "2024Q2"][0]
    assert round(p["YoY_r"], 4) == round((130 / 104 - 1) * 100, 4)
    assert round(p["매출YoY"], 4) == 30.0          # 공시 당시 값끼리(이름 · 뜻 유지)
    assert p["기준일"] == "20241020" and "amended" in p["품질"]


def test_negative_and_dup_past_only(monkeypatch):
    t = {(2024, 1): mk_q(100), (2024, 2): mk_q(100), (2024, 3): mk_q(-5)}
    pts = run_series(monkeypatch, t, [2024])
    q1 = [p for p in pts if p["label"] == "2024Q1"][0]
    q2 = [p for p in pts if p["label"] == "2024Q2"][0]; q3 = [p for p in pts if p["label"] == "2024Q3"][0]
    assert q1["매출액"] == 100 and q1["품질"] == []        # 앞쪽 분기는 뒤 분기 때문에 지워지지 않는다
    assert q2["매출액"] is None and "dup" in q2["품질"]
    assert q3["매출액"] is None and "neg" in q3["품질"]


def test_fy_bad_year_excluded(monkeypatch):
    t = {(2015, 1): mk_q(100), (2015, 2): mk_q(110)}
    calls = []
    monkeypatch.setattr(DRK, "period_data", lambda corp, y, q, offline=False: calls.append((y, q)) or t.get((y, q)))
    pts = DRK.series("C", "000000", [2015], meta={"fy_bad": {2015}})
    assert calls == []                                  # fy_bad 연도는 아예 받지 않는다
    assert [p["label"] for p in pts] == ["2015Q1", "2015Q2", "2015Q3", "2015Q4"]
    assert all(p.get("매출액") is None and p["품질"] == ["fy"] for p in pts)


def test_fy_bad_year_between_good_years(monkeypatch):
    t = {(2014, 4): mk_q(100), (2015, 1): mk_q(999), (2016, 1): mk_q(130)}
    calls = []
    monkeypatch.setattr(DRK, "period_data", lambda corp, y, q, offline=False: calls.append((y, q)) or t.get((y, q)))
    pts = DRK.series("C", "000000", [2014, 2015, 2016], meta={"fy_bad": {2015}})
    assert not [c for c in calls if c[0] == 2015]
    by = {p["label"]: p for p in pts}
    assert [p["q"] for p in pts if p["year"] == 2015] == [1, 2, 3, 4]
    assert all(by["2015Q%d" % q]["품질"] == ["fy"] and by["2015Q%d" % q].get("매출액") is None for q in (1, 2, 3, 4))
    assert by["2016Q1"]["매출액"] == 130 and DRK.LAST["fy_bad"] == [2015]


def test_latest_year_without_annual(monkeypatch):
    t = {(2025, 1): mk_q(100), (2025, 2): mk_q(105), (2025, 3): mk_q(95, cum=300), (2025, 4): mk_q(420),
         (2026, 1): mk_q(125, prev=100), (2026, 2): mk_q(130, prev=101)}
    pts = run_series(monkeypatch, t, [2025, 2026])
    by = {p["label"]: p for p in pts}
    assert by["2025Q4"]["매출액"] == 420 - 300 == 120        # 4분기 단독 = 연간 − 3분기 누적
    assert by["2026Q1"]["매출액"] == 125 and by["2026Q1"]["품질"] == []     # 앞 분기(4분기 단독 120)와 값이 달라 dup 이 아니다
    last = pts[-1]
    assert last["label"] == "2026Q2" and last["매출액"] == 130 and last["YoY_r"] is not None


# ---- series v2 고침 1 — 대표 동작 · 스레드별 LAST · CAPEX 강도 · 이상값 · 기준일

def year_table(fs_q1="CFS", fs_q4="CFS"):
    """2024 한 해 — 매출 100 · 110 · 120(3분기 누적 330) · 4분기 연간 460 → 4분기 단독 130. CAPEX 누적 3 · 7 · 12 · 20, 영업이익 분기 10."""
    return {(2024, 1): mk_q(100, op=10, capex=3, fs=fs_q1, 재고자산=460, 매출채권=230),
            (2024, 2): mk_q(110, op=10, capex=7),
            (2024, 3): mk_q(120, cum=330, op=10, capex=12, **{"영업이익_누적": 30}),
            (2024, 4): mk_q(460, op=40, capex=20, fs=fs_q4, 재고자산=460, 매출채권=230)}


def test_version_is_5():
    assert DRK.VERSION == 5


def test_q4_derived_value_and_restated_yoy(monkeypatch):
    t = {(2023, 3): mk_q(100, cum=270, op=9, **{"영업이익_누적": 27}),
         (2023, 4): mk_q(1290, op=38),
         (2024, 3): mk_q(120, cum=330, prev_cum=272, op=11, ni=7, **{"영업이익_누적": 33, "영업이익_전누적": 28, "지배순이익_누적": 18}),
         (2024, 4): mk_q(1500, prev_ann=1300, op=50, ni=30, **{"영업이익_전연": 40})}
    pts = run_series(monkeypatch, t, [2023, 2024])
    by = {p["label"]: p for p in pts}
    q4 = by["2024Q4"]
    assert by["2023Q4"]["매출액"] == 1290 - 270 and by["2023Q4"]["영업이익"] == 38 - 27
    assert q4["매출액"] == 1500 - 330 and q4["영업이익"] == 50 - 33 and q4["지배순이익"] == 30 - 18   # 연간 − 3분기 누적
    assert "basis" not in q4["품질"]                               # 범위 검사 통과 — 두 비율(전연/전년 연간 · 전누적/전년 누적)이 모두 있다
    assert round(q4["YoY_r"], 6) == round((1170 / (1300 - 272) - 1) * 100, 6)         # 재작성 비교 = (전연 − 전누적)
    assert round(q4["매출YoY"], 6) == round((1170 / (1290 - 270) - 1) * 100, 6)       # 공시 당시 = 전년 4분기 단독
    assert round(q4["영업이익YoY_r"], 6) == round((17 / (40 - 28) - 1) * 100, 6)


@pytest.mark.parametrize("prev_ann, scope_ok", [(1015, True), (1025, False)])
def test_q4_scope_tolerance(monkeypatch, prev_ann, scope_ok):
    # 전년 사업보고서 연간 1000 · Q3 누적 500, 올해 Q3 의 전년 누적 500 (r3 = 1.0). 올해 사업보고서의 전년 연간이 1.5% / 2.5% 어긋난다
    t = {(2023, 3): mk_q(250, cum=500), (2023, 4): mk_q(1000),
         (2024, 3): mk_q(260, cum=540, prev_cum=500), (2024, 4): mk_q(1100, prev_ann=prev_ann)}
    q4 = [p for p in run_series(monkeypatch, t, [2023, 2024]) if p["label"] == "2024Q4"][0]
    if scope_ok:
        assert q4["매출액"] == 1100 - 540 and "basis" not in q4["품질"]
    else:
        assert q4["매출액"] is None and "basis" in q4["품질"]


def test_q4_missing_q3_is_gap_not_basis(monkeypatch):
    q4 = run_series(monkeypatch, {(2024, 4): mk_q(460)}, [2024])[-1]
    assert q4["매출액"] is None and q4["품질"] == ["gap"]                  # 3분기가 없다
    q4 = run_series(monkeypatch, {(2024, 3): mk_q(120), (2024, 4): mk_q(460)}, [2024])[-1]
    assert q4["매출액"] is None and q4["품질"] == ["gap"]                  # 3분기에 누적이 없다


def test_ttm_and_turnover_days(monkeypatch):
    pts = run_series(monkeypatch, year_table(), [2024])
    q4 = pts[3]
    assert [p["매출액"] for p in pts] == [100, 110, 120, 130]
    assert q4["매출_TTM"] == 460 and q4["영업이익_TTM"] == 40 and "basis" not in q4["품질"]
    assert pts[2]["매출_TTM"] is None                                   # 창 앞쪽이 격자 밖
    assert round(q4["재고일수"], 6) == 365 and round(q4["매출채권일수"], 6) == 182.5   # 분모는 TTM 매출 / 365


def test_ttm_basis_on_mixed_fs(monkeypatch):
    q4 = run_series(monkeypatch, year_table(fs_q1="OFS"), [2024])[3]
    assert q4["매출_TTM"] == 460 and "basis" in q4["품질"]


def test_capex_quarterly_difference_and_intensity(monkeypatch):
    pts = run_series(monkeypatch, year_table(), [2024])
    assert [p["CAPEX"] for p in pts] == [3, 4, 5, 8]                       # 누적 차 — 1분기는 그대로, 4분기는 연간 − 3분기 누적
    want = [c / r * 100 for c, r in ((3, 100), (4, 110), (5, 120), (8, 130))]
    assert [round(p["CAPEX강도"], 6) for p in pts] == [round(w, 6) for w in want]    # 그 분기 CAPEX ÷ 그 분기 매출 (TTM ÷ TTM 아님)


def test_capex_intensity_none_when_missing(monkeypatch):
    t = year_table()
    t[(2024, 2)] = mk_q(110, op=10)                                       # 2분기 누적 CAPEX 없음
    pts = run_series(monkeypatch, t, [2024])
    assert pts[0]["CAPEX"] == 3
    assert pts[1]["CAPEX"] is None and pts[1]["CAPEX강도"] is None
    assert pts[2]["CAPEX"] is None and pts[2]["CAPEX강도"] is None        # 앞 누적이 없어 차를 못 뗀다


def test_q4_capex_guarded_like_other_q4_values(monkeypatch):
    pts = run_series(monkeypatch, year_table(fs_q4="OFS"), [2024])        # 3분기 CFS · 4분기 OFS
    q4 = pts[3]
    assert q4["매출액"] is None and "basis" in q4["품질"]
    assert q4["CAPEX"] is None and q4["CAPEX강도"] is None
    assert pts[2]["CAPEX"] == 5
    t = {(2019, 3): mk_q(2400, cum=6956, capex=50), (2019, 4): mk_q(9700, capex=90),     # 같은 기준이어도 범위가 다르면(test_q4_scope_restated)
         (2020, 3): mk_q(2300, cum=7233, prev_cum=6803, capex=60), (2020, 4): mk_q(1566, prev_ann=1660, capex=100)}
    q4 = [p for p in run_series(monkeypatch, t, [2019, 2020]) if p["label"] == "2020Q4"][0]
    assert q4["매출액"] is None and "basis" in q4["품질"] and q4["CAPEX"] is None


def test_dup_compares_raw_previous_quarter(monkeypatch):
    t = {(2024, 1): mk_q(100), (2024, 2): mk_q(100), (2024, 3): mk_q(100)}
    pts = run_series(monkeypatch, t, [2024])
    assert pts[0]["매출액"] == 100 and pts[0]["품질"] == []
    assert all(p["매출액"] is None and p["품질"] == ["dup"] for p in pts[1:])      # 2분기가 지워져도 3분기는 원래 값과 견준다
    t = year_table(); t[(2025, 1)] = mk_q(460)                                       # 1분기 값 460 은 전년 4분기 단독(130)이 아니라 연간(460)과 같다 — dup 아님
    p = run_series(monkeypatch, t, [2024, 2025])[-1]
    assert p["label"] == "2025Q1" and p["매출액"] == 460 and p["품질"] == []


def test_q4_reference_date_considers_q3_rcept(monkeypatch):
    meta = {"filed": {2024 * 4 + 3: "20250320"}}
    t = {(2024, 3): mk_q(120, cum=330, rc="20241114"), (2024, 4): mk_q(460, rc="20250320")}
    q4 = run_series(monkeypatch, t, [2024], meta=meta)[-1]
    assert q4["기준일"] == "20250320" and "amended" not in q4["품질"]
    t[(2024, 3)] = mk_q(120, cum=330, rc="20250401")                       # 3분기 정정이 사업보고서 뒤에 나왔다 — 4분기 값은 그 누적에 기대고 있다
    q4 = run_series(monkeypatch, t, [2024], meta=meta)[-1]
    assert q4["기준일"] == "20250401" and "amended" in q4["품질"]


def test_transient_skipped_counted_and_error_recorded(monkeypatch):
    t = {(2024, 1): {"_transient": True}, (2024, 2): mk_q(100), (2024, 3): RuntimeError("boom"), (2025, 1): mk_q(120)}

    def pd(corp, y, q, offline=False):
        v = t.get((y, q))
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(DRK, "period_data", pd)
    pts = DRK.series("C", "000000", [2024, 2025], meta={})
    assert DRK.LAST["transient"] == 2 and DRK.LAST["error"] == "RuntimeError: boom"
    assert [p["label"] for p in pts] == ["2024Q2", "2024Q3", "2024Q4", "2025Q1"]    # 일시 오류 분기는 원장에 없다 — 가운데면 빈 칸
    assert pts[0]["매출액"] == 100 and pts[1]["품질"] == ["gap"] and pts[1].get("매출액") is None
    run_series(monkeypatch, {(2024, 2): mk_q(100)}, [2024])                # 다음 호출은 처음부터 다시 센다
    assert DRK.LAST["transient"] == 0 and DRK.LAST["error"] is None


def test_last_dict_api():
    L = DRK.LAST
    L.update(transient=0, fy_bad=[], error=None)
    L["transient"] += 1
    L["error"] = "X: y"
    assert L["transient"] == 1 and L.get("transient", 9) == 1 and L.get("없는키", 9) == 9 and L["error"] == "X: y"


def test_last_is_thread_local(monkeypatch):
    import threading

    def pd(corp, y, q, offline=False):
        if corp == "A":
            return {"_transient": True} if q <= 3 else mk_q(100)
        return mk_q(100 + q)
    monkeypatch.setattr(DRK, "period_data", pd)
    DRK.LAST.update(transient=99, fy_bad=[7], error="main")
    gate, seen, errs = threading.Barrier(2, timeout=20), {}, []

    def work(corp):
        try:
            DRK.series(corp, "000000", [2024], meta={})
            gate.wait()                                                       # 두 스레드 모두 series() 를 끝낸 뒤 읽는다
            seen[corp] = (DRK.LAST["transient"], DRK.LAST["fy_bad"])
        except Exception as e:                                                # 스레드 안 실패는 pytest 가 못 잡는다
            errs.append(repr(e))
    ths = [threading.Thread(target=work, args=(c,)) for c in ("A", "B")]
    for th in ths: th.start()
    for th in ths: th.join(30)
    assert errs == [] and seen == {"A": (3, []), "B": (0, [])}
    assert DRK.LAST["transient"] == 99 and DRK.LAST["error"] == "main"        # 메인 스레드 값은 그대로


# ---------------------------------------------------------------- accel — B · 7국면 · 변곡 · 엇갈림 · mix (Task 3)
def grid(yoys, start=(2024, 1)):
    """yoys: 분기마다 (재작성 YoY_r, 공시 당시 매출YoY) — 하나만 주면 둘 다 같은 값."""
    y0, q0 = start; out = []
    for i, v in enumerate(yoys):
        n = y0 * 4 + q0 - 1 + i
        r, a = (v if isinstance(v, tuple) else (v, v))
        out.append({"n": n, "year": n // 4, "q": n % 4 + 1, "label": "%dQ%d" % (n // 4, n % 4 + 1), "YoY_r": r, "매출YoY": a, "품질": [], "기준일": "20240101"})
    return out


def test_b_definition():
    pts = DRK.accel(grid([10, 20, 30, 50]))
    # s(n) = (Y(n)+Y(n-1))/2 ; B(n) = s(n) - s(n-2)
    assert pts[3]["속도"] == 40 and pts[3]["가속B"] == 40 - 15


def test_phase_labels_and_flat():
    assert DRK.phase_label(10, 4) == "확장 가속" and DRK.phase_label(10, 0) == "확장 유지" and DRK.phase_label(10, -4) == "둔화"
    assert DRK.phase_label(-10, 4) == "회복" and DRK.phase_label(-10, 0) == "부진 지속" and DRK.phase_label(-10, -4) == "수축 심화"
    assert DRK.phase_label(1, 1) == "정체"


def _turn_marks(Bs, start=(2024, 1)):
    pts = grid([0] * len(Bs), start=start)
    for p, b in zip(pts, Bs):
        p["가속B"] = b
    DRK._turns(pts)
    return [p["변곡"] for p in pts]


def test_turn_one_quarter_flip_samsung_shape():
    """한 분기 부호 바뀜(2026-10-10 사용자 결정) — 삼성: B 2025Q2 −9.2 · 2025Q3 −6.2 → 2025Q4 +10.9 ▲ → 2026Q1 +41.7(같은 쪽 — 변곡 아님)."""
    marks = _turn_marks([-9.2, -6.2, 10.9, 41.7], start=(2025, 2))
    assert marks == [None, None, "▲", None]


def test_turn_needs_opposite_sign_in_previous_quarter():
    """앞 분기 B 가 띠 안이라도 부호만 본다 — 띠를 건넜는지(예전 규칙)는 보지 않는다."""
    assert _turn_marks([-5, 1, 6]) == [None, None, None]          # 앞 분기 +1 — 띠를 건넜지만(예전 ▲) 부호가 같다
    assert _turn_marks([5, -1, 1, 4]) == [None, None, None, None]  # 앞 분기 +1 이고 이번 +4 — 같은 쪽
    assert _turn_marks([5, -1, 4]) == [None, None, "▲"]            # 앞 분기 −1(띠 안) → +4 — ▲
    assert _turn_marks([1, 2, -4]) == [None, None, "▼"]            # 앞 분기 +2 → −4 — ▼
    assert _turn_marks([-2, 2.9, -2.9]) == [None, None, None]      # 이번 분기가 띠 안이면 변곡 아님


def test_turn_missing_or_zero_previous_quarter_is_no_turn():
    assert _turn_marks([-5, None, 6]) == [None, None, None]        # B(n−1) 없음
    assert _turn_marks([0, 6]) == [None, None] and _turn_marks([0, -6]) == [None, None]   # B(n−1) = 0 — 부등호가 엄격하다
    pts = grid([0, 0, 0])
    del pts[1]                                                     # n−1 점이 아예 없다(키로 찾는다 — 목록 순서가 아니라)
    pts[0]["가속B"], pts[1]["가속B"] = -5.0, 6.0
    DRK._turns(pts)
    assert [p["변곡"] for p in pts] == [None, None]


def test_divergence_only_outside_band():
    pts = DRK.accel(grid([0, 10, 20, 40, 15]))
    last = pts[-1]
    # B(last) = s(4) - s(2) = 27.5 - 15 = 12.5 > 3, C = 15 - 40 = -25 → 엇갈림
    assert last["가속B"] == 12.5 and last["C"] == -25 and last["엇갈림"] is True
    same = DRK.accel(grid([10, 10, 10, 10, 2]))
    assert same[-1]["가속B"] == -4 and same[-1]["C"] == -8 and same[-1]["엇갈림"] is False   # B · C 같은 부호
    inband = DRK.accel(grid([10, 10, 10, 12, 4]))
    assert abs(inband[-1]["가속B"]) < 3 and inband[-1]["엇갈림"] is False                  # 띠 안이면 방향이 없어 엇갈림도 없음


def test_mix_window_falls_back_to_asfiled():
    pts = DRK.accel(grid([(None, 5), (None, 6), (10, 7), (12, 8)]))
    last = pts[-1]
    assert "mix" in last["품질"] and last["가속B"] == ((8 + 7) / 2) - ((6 + 5) / 2)


def test_short_history_no_phase():
    pts = DRK.accel(grid([10, 12]))
    assert all(p["국면"] is None for p in pts)


def test_op_basis_small_base_skipped():
    pts = grid([0] * 6)
    ops = [2, 100, 100, 100, 50, 120]      # pts[4] 의 1년 전 기저 2 는 직전 4분기 평균 |영업이익| 75.5 의 20% 미만 — YoY 안 씀
    for p, o in zip(pts, ops):
        p["영업이익"] = o
    for p in pts:
        b = next((x for x in pts if x["n"] == p["n"] - 4), None)
        p["영업이익YoY_r"] = (p["영업이익"] / b["영업이익"] - 1) * 100 if b else None
        p["영업이익YoY"] = p["영업이익YoY_r"]
    DRK.accel(pts, basis="영업이익")
    assert pts[4]["Y"] is None
    assert round(pts[5]["Y"], 6) == 20.0


def test_share_basis_mid_year_split():
    # LS일렉트릭: 2026Q1 까지 약 2,940만 주, 2026Q2 부터 1.47억 주(5:1)
    sh = {"2025Q3": 29.4e6, "2025Q4": 29.4e6, "2026Q1": 29.4e6, "2026Q2": 147e6}
    out = DRK.share_basis(sh, [("20260410", "주식분할결정")])
    assert abs(out["now"]["2026Q1"] - 147e6) < 1 and abs(out["now"]["2026Q2"] - 147e6) < 1
    assert out["splits"][0]["kind"].startswith("분할")


def test_share_basis_one_quarter_spike_dropped():
    sh = {"2024Q1": 10e6, "2024Q2": 210e6, "2024Q3": 10e6}
    out = DRK.share_basis(sh, [])
    assert "2024Q2" not in out["now"] and not out["splits"]


def test_per_share_eps_ttm_same_basis():
    pts = grid([0] * 4, start=(2025, 3))
    ni = [131e8, 164e8, 1190e8, 1158e8]
    eps = [447, 560, 4052, 797]                  # 앞 세 분기는 분할 전 기준(약 2,930만 주), 2026Q2 만 새 기준(약 1.45억 주)
    for p, a, b in zip(pts, ni, eps):
        p["지배순이익"], p["EPS"], p["매출액"] = a, b, 1e12
    DRK.per_share(pts, [("20260410", "주식분할결정")])
    last = pts[-1]
    want = sum(p["지배순이익"] for p in pts) / 145.3e6      # 네 분기 모두 지금 주식 수로
    assert abs(last["EPS_TTM"] / want - 1) < 0.05
    assert last["EPS_TTM_raw"] == sum(eps)                  # 원래 합(기준 섞임)은 따로 남는다


def test_per_share_unit_error():
    pts = grid([0] * 5)
    for p in pts:
        p["지배순이익"], p["EPS"], p["매출액"] = 100e8, 1000, 1e12
    pts[2]["EPS"] = 1000 * 1e6
    DRK.per_share(pts, [])
    assert "unit" in pts[2]["품질"] and abs(pts[2]["EPS_adj"] - 1000) < 1


# ------------------------------------------------------------------ EPS 를 합계(계속 + 중단영업) 기준으로 — 서버 _pipe_rows 의 계속영업 EPS + 중단영업 EPS 규칙
EPS_TOT = "ifrs-full_BasicEarningsLossPerShare"
EPS_CONT = "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations"
EPS_DISC = "ifrs-full_BasicEarningsLossPerShareFromDiscontinuedOperations"


def test_period_data_eps_total_row_is_used_as_is(monkeypatch):
    """합계 기본주당이익 줄(태그 BasicEarningsLossPerShare)이 있으면 그 값 — 중단영업 줄이 같이 있어도 더하지 않는다."""
    amt = dict(thstrm_amount=40, thstrm_add_amount=800, frmtrm_q_amount=30, frmtrm_add_amount=700, frmtrm_amount=950)
    disc = dict(thstrm_amount=-350, thstrm_add_amount=-100, frmtrm_q_amount=-5, frmtrm_add_amount=-6, frmtrm_amount=-7)
    for with_disc in (False, True):
        rows = [row("IS", EPS_TOT, "기본주당이익", **amt)]
        if with_disc:
            rows.append(row("IS", EPS_DISC, "중단영업 기본주당이익", **disc))
        monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11011", "CFS"): stmt(rows)}))
        d = DRK.period_data("C", 2024, 4)
        assert (d["EPS"], d["EPS_누적"], d["EPS_전"], d["EPS_전누적"], d["EPS_전연"]) == (40, 800, 30, 700, 950)


def test_period_data_eps_continuing_plus_discontinued_in_every_field(monkeypatch):
    """계속영업 줄만 있고 중단영업 줄이 따로 있으면 둘을 더해 합계 기준으로 — 값 · 누적 · 전년 같은 분기 · 전년 같은 누적 · 전년 연간 모두."""
    cont = dict(thstrm_amount=390, thstrm_add_amount=900, frmtrm_q_amount=300, frmtrm_add_amount=800, frmtrm_amount=1000)
    disc = dict(thstrm_amount=-350, thstrm_add_amount=-100, frmtrm_q_amount=-20, frmtrm_add_amount=-30, frmtrm_amount=-40)
    rows = [row("IS", EPS_CONT, "계속영업 기본주당이익", **cont), row("IS", EPS_DISC, "중단영업 기본주당이익", **disc)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11011", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 4)
    assert (d["EPS"], d["EPS_누적"], d["EPS_전"], d["EPS_전누적"], d["EPS_전연"]) == (40, 800, 280, 770, 960)


def test_period_data_eps_continuing_plus_discontinued_untagged_names(monkeypatch):
    """태그가 없는 줄(본문 파서)도 이름으로 같은 규칙 — '중단영업' 이 든 기본 주당 줄을 더한다."""
    rows = [row("IS", NO_TAG, "계속영업 기본주당이익", thstrm_amount=390),
            row("IS", NO_TAG, "중단영업 기본주당손익", thstrm_amount=-350)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["EPS"] == 40


def test_period_data_eps_continuing_only_without_discontinued_row(monkeypatch):
    """중단영업 줄이 없으면 계속영업 값 그대로(더할 게 없다). 중단영업 줄의 한 칸만 비면 그 칸은 계속영업 그대로."""
    rows = [row("IS", EPS_CONT, "계속영업 기본주당이익", thstrm_amount=390, thstrm_add_amount=900)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11012", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 2)
    assert d["EPS"] == 390 and d["EPS_누적"] == 900
    rows.append(row("IS", EPS_DISC, "중단영업 기본주당이익", thstrm_amount=-350))        # 누적 칸은 빈 값
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11012", "CFS"): stmt(rows)}))
    d = DRK.period_data("C", 2024, 2)
    assert d["EPS"] == 40 and d["EPS_누적"] == 900


def test_period_data_eps_prefers_total_name_over_continuing_only_name(monkeypatch):
    """태그 없는 줄이 둘이면 계속영업만 센 줄보다 합계 줄을 먼저(서버 _pipe_rows 의 후보 순서) — 계속영업 줄이 앞에 와도 중단영업을 또 더하지 않는다."""
    rows = [row("IS", NO_TAG, "계속영업 기본주당이익", thstrm_amount=390),
            row("IS", NO_TAG, "기본주당이익", thstrm_amount=40),
            row("IS", NO_TAG, "중단영업 기본주당이익", thstrm_amount=-350)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["EPS"] == 40


def test_period_data_eps_combined_name_is_total(monkeypatch):
    """'계속영업과 중단영업 …' 이름의 줄은 합계 — 중단영업 줄이 따로 있어도 더하지 않는다(서버 cont 판정: '계속영업과' 는 계속영업만이 아니다)."""
    rows = [row("IS", EPS_TOT, "계속영업과 중단영업 기본주당이익", thstrm_amount=40),
            row("IS", EPS_DISC, "중단영업 기본주당이익", thstrm_amount=-350)]
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch({(2024, "11013", "CFS"): stmt(rows)}))
    assert DRK.period_data("C", 2024, 1)["EPS"] == 40


def kakao_table():
    """카카오 2026Q2 모양 — 약 4억 주. 2026Q2 는 계속영업 순이익 1,724억 − 중단영업 1,560억 = 지배순이익 164억이고,
    EPS 는 계속영업 431원 · 중단영업 −390원 두 줄뿐이다(합계 줄 없음). 앞 분기는 합계 EPS 줄."""
    E8 = 10 ** 8
    t = {}

    def rep(year, reprt, rev, ni, eps_rows, **add):
        rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=rev, thstrm_add_amount=add.get("rev_add", rev)),
                row("IS", OWNER, "지배기업 소유주지분", thstrm_amount=ni, thstrm_add_amount=add.get("ni_add", ni))] + eps_rows
        t[(year, reprt, "CFS")] = stmt(rows)
    rep(2025, "11014", 1_200 * 10 ** 9, 800 * E8, [row("IS", EPS_TOT, "기본주당이익", thstrm_amount=200, thstrm_add_amount=600)],
        rev_add=3_300 * 10 ** 9, ni_add=2400 * E8)
    rep(2025, "11011", 4_700 * 10 ** 9, 3000 * E8, [row("IS", EPS_TOT, "기본주당이익", thstrm_amount=750)])        # 연간 → 4분기 단독 = 연간 − 3분기 누적
    rep(2026, "11013", 1_500 * 10 ** 9, 1200 * E8, [row("IS", EPS_TOT, "기본주당이익", thstrm_amount=300)])
    rep(2026, "11012", 1_600 * 10 ** 9, 164 * E8, [row("IS", EPS_CONT, "계속영업 기본주당이익", thstrm_amount=431),
                                                   row("IS", EPS_DISC, "중단영업 기본주당이익", thstrm_amount=-390)],
        rev_add=3_100 * 10 ** 9, ni_add=1364 * E8)                  # 반기 보고서의 누적 칸은 반기 누적(3개월 칸과 다르다)
    return t


def test_per_share_continuing_plus_discontinued_eps_end_to_end(monkeypatch):
    """period_data → series → per_share. 계속영업 EPS 만 쓰면 2026Q2 주식 수가 4억 → 3,800만 주로 줄어(10배) 분할 · 병합으로 읽히고
    EPS 가 부푼다. 합계 기준(431 − 390 = 41원)이면 주식 수 4억 그대로, 분할 없음."""
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fake_fetch(kakao_table()))
    pts = DRK.series("C", "000000", [2025, 2026], meta={})
    by = {p["label"]: p for p in pts}
    assert by["2025Q4"]["EPS"] == 150 and by["2026Q2"]["EPS"] == 41            # 4분기 단독도 합계 기준끼리 뺀다
    DRK.per_share(pts, [])
    last = pts[-1]
    assert last["label"] == "2026Q2"
    assert abs(last["주식수"] / 400e6 - 1) < 0.01
    assert abs(last["EPS_adj"] - 41) < 0.5
    assert abs(last["EPS_TTM"] - (200 + 150 + 300 + 41)) < 1                    # 네 분기 모두 같은 주식 수 · 합계 기준
    assert last["EPS_TTM_raw"] == 200 + 150 + 300 + 41
    assert "cut" not in last["품질"]


def test_per_share_unfixable_unit_uses_neighbour_shares():
    """주식 수가 중앙값의 1/300 밑인데 ÷1e3 · ÷1e6 으로도 못 맞추는 분기는 주식 수 열에서 빠지고 'unit' 을 단다.
    EPS_adj 는 이웃 분기 주식 수로(EPS 자체는 그대로 둔다 — EPS_TTM_raw 에는 그 값이 들어간다)."""
    pts = grid([0] * 5)
    for p in pts:
        p["지배순이익"], p["EPS"], p["매출액"] = 100e8, 1000, 1e12
    pts[2]["EPS"] = 1000 * 1e4                                  # 구한 주식 수 = 1e3 — 중앙값 1e7 의 1/1e4 (×1e3 → 1e6, ×1e6 → 1e9: 둘 다 중앙값 ±1.8배 밖)
    DRK.per_share(pts, [])
    assert "unit" in pts[2]["품질"] and pts[2]["EPS"] == 1000 * 1e4
    assert abs(pts[2]["주식수"] - 1e7) < 1 and abs(pts[2]["EPS_adj"] - 1000) < 1e-6
    assert all("unit" not in p["품질"] for i, p in enumerate(pts) if i != 2)
    assert abs(pts[4]["EPS_TTM"] - 4000) < 1e-6                 # 보정 주식 수로 네 분기 합
    assert pts[4]["EPS_TTM_raw"] == 1000 * 3 + 1000 * 1e4       # 원래 합 — 못 고친 EPS 가 그대로 들어간다


def test_per_share_fixed_unit_eps_raw_sum_uses_corrected_eps():
    """EPS_TTM_raw 는 단위를 고친 EPS 의 단순 합이다(공시 원값이 아니다) — 분할 보정만 안 한 합."""
    pts = grid([0] * 5)
    for p in pts:
        p["지배순이익"], p["EPS"], p["매출액"] = 100e8, 1000, 1e12
    pts[3]["EPS"] = 1000 * 1e6
    DRK.per_share(pts, [])
    assert pts[3]["EPS"] == 1000 and pts[4]["EPS_TTM_raw"] == 4000


def test_per_share_tags_cut_quarters():
    """분할 + 합병(증자 섞임)이 한 창에 겹치면 share_basis 가 cut 을 낸다 — 그 분기(포함) 앞은 모두 품질 'cut' (자기 역사 PER 에서 뺄 표시)."""
    pts = grid([0] * 6, start=(2025, 2))                        # 2025Q2 … 2026Q3
    shares = [10e6, 10e6, 10e6, 106e6, 106e6, 106e6]            # 2026Q1 에 10.6배 — 정수 비율이 아니다
    for p, s in zip(pts, shares):
        p["지배순이익"], p["매출액"] = 100e8, 1e12
        p["EPS"] = 100e8 / s
    sev = [("20260110", "주식분할결정"), ("20260112", "회사합병결정")]
    assert DRK.share_basis({p["label"]: 100e8 / p["EPS"] for p in pts}, sev)["cut"] == 2025 * 4 + 4
    DRK.per_share(pts, sev)
    assert [p["label"] for p in pts if "cut" in p["품질"]] == ["2025Q2", "2025Q3", "2025Q4"]      # cut 분기(2025Q4) 포함, 그 뒤는 아님


def test_per_share_no_cut_tag_for_plain_split():
    pts = grid([0] * 4, start=(2025, 3))
    for p, s in zip(pts, [29.4e6, 29.4e6, 29.4e6, 147e6]):
        p["지배순이익"], p["매출액"] = 100e8, 1e12
        p["EPS"] = 100e8 / s
    DRK.per_share(pts, [("20260410", "주식분할결정")])
    assert all("cut" not in p["품질"] for p in pts)


# ---------------------------------------------------------------- 캐시 읽기(서버 _druck_read 가 이것만 부른다)
def test_read_cache_missing_file(tmp_path):
    assert DRK.read_cache(str(tmp_path / "없음.json")) is None


def test_read_cache_broken_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"v": 2, "points": [', encoding="utf-8")
    assert DRK.read_cache(str(p)) is None


def test_read_cache_old_version(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"sig": "20260814003699", "points": [{"n": 1}]}), encoding="utf-8")     # v1 — 버전 키 없음
    assert DRK.read_cache(str(p)) is None
    p.write_text(json.dumps({"v": DRK.VERSION - 1, "sig": "x", "points": []}), encoding="utf-8")
    assert DRK.read_cache(str(p)) is None


def test_read_cache_not_a_dict(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("[1, 2]", encoding="utf-8")
    assert DRK.read_cache(str(p)) is None


def test_read_cache_current_version(tmp_path):
    p = tmp_path / "x.json"
    d = {"v": DRK.VERSION, "sig": "v%d:abc" % DRK.VERSION, "points": [{"n": 1, "품질": ["gap"]}]}
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert DRK.read_cache(str(p)) == d


# ---------------------------------------------------------------- 캐시 쓰기 — 읽는 쪽이 파일을 열고 있으면 Windows replace 가 PermissionError
def test_write_cache_retries_permission_error(tmp_path, monkeypatch):
    real, calls, slept = os.replace, [], []

    def flaky(a, b):
        calls.append(a)
        if len(calls) <= 2:
            raise PermissionError(13, "WinError 5 액세스가 거부되었습니다")
        return real(a, b)
    monkeypatch.setattr(DRK.os, "replace", flaky)
    monkeypatch.setattr(DRK.time, "sleep", slept.append)
    path = str(tmp_path / "druck" / "x.json")
    obj = {"v": DRK.VERSION, "sig": "v2:a", "points": [{"n": 1, "품질": []}]}
    assert DRK.write_cache(path, obj) is True
    assert len(calls) == 3 and slept == [0.2, 0.2]
    assert not os.path.exists(path + ".tmp")
    monkeypatch.undo()
    assert DRK.read_cache(path) == obj


def test_write_cache_gives_up_after_five_tries_and_removes_tmp(tmp_path, monkeypatch):
    path = str(tmp_path / "x.json")
    old = {"v": DRK.VERSION, "sig": "v2:old", "points": []}
    assert DRK.write_cache(path, old) is True
    calls, slept = [], []

    def locked(a, b):
        calls.append(a)
        raise PermissionError(13, "locked")
    monkeypatch.setattr(DRK.os, "replace", locked)
    monkeypatch.setattr(DRK.time, "sleep", slept.append)
    assert DRK.write_cache(path, {"v": DRK.VERSION, "sig": "v2:new", "points": []}) is False
    assert len(calls) == 5 and len(slept) == 4                  # 마지막 실패 뒤에는 쉬지 않는다
    assert not os.path.exists(path + ".tmp")
    monkeypatch.undo()
    assert DRK.read_cache(path) == old                          # 예전 캐시는 그대로


# ---------------------------------------------------------------- 진행률
def test_series_progress_counts_every_period(monkeypatch):
    def fetch(corp, year, reprt, fs_div="CFS"):
        if int(year) == 2025 and reprt == "11013":
            return {"status": "err", "list": [], "transient": True}      # 일시 오류 분기도 센다
        return stmt([])
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fetch)
    seen = []
    DRK.series("C", "000000", [2023, 2024, 2025], meta={"fy_bad": {2024}}, progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 12), (2, 12), (3, 12), (4, 12), (8, 12), (9, 12), (10, 12), (11, 12), (12, 12)]
    assert DRK.LAST["transient"] == 1


def test_series_without_progress_still_works(monkeypatch):
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a: stmt([]))
    assert DRK.series("C", "000000", [2025]) == []


# ---------------------------------------------------------------- filed_meta(서버 _druck_meta)
def rep(stamp, label, rcept, tag=""):
    return {"stamp": stamp, "label": label, "tag": tag, "rcept": rcept}


def test_filed_meta_december_fy_uses_original_filing_dates():
    reps = [rep("2025-03", "분기보고서", "20250515000001"),
            rep("2025-06", "반기보고서", "20250814000002"),
            rep("2025-06", "반기보고서", "20251020000009", "[기재정정]"),     # 정정본 접수일은 filed 에 안 든다
            rep("2025-09", "분기보고서", "20251114000003"),
            rep("2025-12", "사업보고서", "20260310000004"),
            rep("2026-03", "분기보고서", "20260601000005", "[기재정정]")]     # 정정본만 있는 분기 — filed 없음
    m = DRK.filed_meta(reps)
    assert m["fy_bad"] == set()
    assert m["filed"] == {2025 * 4: "20250515", 2025 * 4 + 1: "20250814", 2025 * 4 + 2: "20251114", 2025 * 4 + 3: "20260310"}


def test_filed_meta_two_originals_keep_earliest():
    m = DRK.filed_meta([rep("2025-03", "분기보고서", "20250530000002"), rep("2025-03", "분기보고서", "20250515000001")])
    assert m["filed"] == {2025 * 4: "20250515"}


def test_filed_meta_non_december_fy_years_are_bad():
    """6월 결산 — 사업보고서가 06, 반기보고서가 12 에 나온다. 그런 보고서가 하나라도 있는 해는 fy_bad(분기 키가 어긋난다).
    모양만 12월 결산과 같은 분기보고서(09 · 03)는 filed 에 남지만 그해 전체를 series 가 fy 칸으로 뺀다."""
    reps = [rep("2024-06", "사업보고서", "20240920000001"), rep("2024-09", "분기보고서", "20241114000002"),
            rep("2024-12", "반기보고서", "20250214000003"), rep("2025-03", "분기보고서", "20250515000004"),
            rep("2025-06", "사업보고서", "20250920000005")]
    m = DRK.filed_meta(reps)
    assert m["fy_bad"] == {2024, 2025}
    assert m["filed"] == {2024 * 4 + 2: "20241114", 2025 * 4: "20250515"}


# ---------------------------------------------------------------- 마지막 자료 분기 뒤 분할 공시
def test_split_after_only_adjusting_events_after_last_data_quarter():
    pts = [{"n": 2026 * 4, "label": "2026Q1", "fs": "CFS", "품질": []},
           {"n": 2026 * 4 + 1, "label": "2026Q2", "fs": "CFS", "품질": []},
           {"n": 2026 * 4 + 2, "label": "2026Q3", "품질": ["gap"]}]          # 끝의 빈 칸은 자료 분기가 아니다
    sev = [("20260520", "주식분할결정"),          # 마지막 자료 분기(2026Q2, 6/30) 안 — 그 분기에 이미 반영
           ("20260630", "무상증자결정"),          # 분기 말 당일 — 뒤가 아니다
           ("20260715", "주식분할결정"),
           ("20260801", "유상증자결정"),          # 주가 보정 없는 사건은 안 든다
           ("20260901", "주식병합결정")]
    assert DRK.split_after(pts, sev) == [{"date": "20260715", "title": "주식분할결정"},
                                          {"date": "20260901", "title": "주식병합결정"}]


def test_split_after_without_data_points_is_empty():
    assert DRK.split_after([{"n": 1, "품질": ["gap"]}], [("20260715", "주식분할결정")]) == []
    assert DRK.split_after([{"n": 2026 * 4, "fs": "OFS", "품질": []}], None) == []


# ---------------------------------------------------------------- 지금 PER(서버 _druck_now)
def per_pts(pers, last=None, n0=2016 * 4):
    """자료 분기(fs 있음)가 분기 키 n0 부터 이어진 점 — 앞쪽은 PER_TTM 만, 끝 점(last)은 EPS_TTM 등."""
    def pt(i, **kw):
        n = n0 + i
        return dict({"n": n, "label": "%dQ%d" % (n // 4, n % 4 + 1), "fs": "CFS", "품질": []}, **kw)
    pts = [pt(i, PER_TTM=v) for i, v in enumerate(pers)]
    if last is not None:
        pts.append(pt(len(pers), **dict(last, 품질=last.get("품질", []))))
    return pts


def test_now_per_k1():
    pts = per_pts([10.0] * 7, {"EPS_TTM": 1000.0, "주가": 12000.0, "주가일": "20260814", "PER_TTM": 12.0})
    now = DRK.now_per(pts, {"20260814": 12000.0, "20261008": 15000.0})
    lab = pts[-1]["label"]
    assert now == {"px": 15000.0, "date": "20261008", "per": 15.0, "k": 1.0, "pct": 100.0, "stale": False, "split_after": [],
                   "reason": None, "eps_label": lab, "last": lab}


def test_now_per_k_after_split_rescales_eps_and_is_stale():
    pts = per_pts([], {"EPS_TTM": 5000.0, "주가": 100000.0, "주가일": "20260814", "PER_TTM": 20.0})
    now = DRK.now_per(pts, {"20260814": 20000.0, "20261008": 21000.0})     # 캐시 뒤 5:1 분할 — 수정주가는 옛 날짜도 1/5
    assert now["k"] == 5.0 and now["per"] == pytest.approx(21000 / 1000) and now["stale"] is True


def test_now_per_k_from_last_point_with_eps_price_and_date():
    pts = per_pts([], {"EPS_TTM": 900.0, "주가": 30000.0, "주가일": "20260514"})
    pts += per_pts([], {"EPS_TTM": 1000.0}, n0=pts[-1]["n"] + 1)              # 최신 분기는 주가가 아직 없다
    now = DRK.now_per(pts, {"20260514": 20000.0, "20261008": 30000.0})
    assert now["k"] == 1.5 and now["per"] == pytest.approx(30000 / (1000 / 1.5)) and now["stale"] is False


@pytest.mark.parametrize("cached,stale", [(11000.0, True), (11200.0, False), (20000.0, False), (35800.0, False), (36000.0, True)])
def test_now_per_stale_thresholds(cached, stale):
    """k = 0.55 · 1.8 은 낡음(경계 포함), 0.56 · 1.79 는 아님."""
    pts = per_pts([], {"EPS_TTM": 1000.0, "주가": cached, "주가일": "20260814"})
    now = DRK.now_per(pts, {"20260814": 20000.0, "20261008": 20000.0})
    assert now["k"] == round(cached / 20000.0, 3) and now["stale"] is stale


def test_now_per_split_after_holds_per_and_is_not_stale_by_itself():
    """마지막 자료 분기 뒤 분할 공시 — 지금 PER 을 내지 않고(분할 뒤 첫 보고서 전) 까닭을 적는다. k 가 1 이면 stale 이 아니다
    (stale 은 '주가 자료가 다시 보정됐다' = 서버가 다시 쌓는 조건 — split_after 만으로는 다시 쌓지 않는다)."""
    sa = [{"date": "20260901", "title": "주식분할결정"}]
    pts = per_pts([10.0] * 8, {"EPS_TTM": 1000.0, "주가": 10000.0, "주가일": "20260814"})
    now = DRK.now_per(pts, {"20260814": 10000.0, "20261008": 10000.0}, sa)
    assert now["k"] == 1.0 and now["stale"] is False and now["split_after"] == sa
    assert now["per"] is None and now["pct"] is None and now["reason"] == DRK.SPLIT_HOLD == "분할 뒤 첫 보고서 전 — PER 계산 보류"
    now = DRK.now_per(pts, {"20260814": 5000.0, "20261008": 5000.0}, sa)        # 네이버가 이미 보정 — k 2 → stale(한 번 다시 쌓는다), PER 은 여전히 보류
    assert now["stale"] is True and now["per"] is None


def test_now_per_only_from_latest_or_one_back_eps():
    """지금 PER 은 마지막 자료 분기(또는 한 분기 앞)의 EPS_TTM 으로만 — 흥국화재처럼 2015Q1 EPS_TTM 으로 '지금'을 내지 않는다."""
    prices = {"20150515": 10000.0, "20261008": 12000.0}
    base = per_pts([8.0] * 8, {"EPS_TTM": 1000.0, "주가": 10000.0, "주가일": "20150515", "PER_TTM": 10.0})
    one_back = base + per_pts([], {"EPS_adj": 50.0, "주식수": 1e6}, n0=base[-1]["n"] + 1)      # 최신 분기 EPS_TTM 없음 — 한 분기 앞은 쓴다
    now = DRK.now_per(one_back, prices)
    assert now["per"] == pytest.approx(12.0) and now["eps_label"] == base[-1]["label"] and now["reason"] is None
    two_back = one_back + per_pts([], {"EPS_adj": 50.0, "주식수": 1e6}, n0=one_back[-1]["n"] + 1)
    now = DRK.now_per(two_back, prices)
    assert now["per"] is None and now["pct"] is None and now["eps_label"] == base[-1]["label"] and now["last"] == two_back[-1]["label"]
    assert now["reason"].startswith("최근 EPS_TTM 은 %s — %s 는 " % (base[-1]["label"], two_back[-1]["label"]))
    gap_tail = one_back + [{"n": one_back[-1]["n"] + 1, "label": "x", "품질": ["gap"]}]       # 끝의 빈 칸(원장 없음)은 자료 분기가 아니다
    assert DRK.now_per(gap_tail, prices)["per"] == pytest.approx(12.0)


def test_now_per_reasons_without_eps_ttm():
    """EPS_TTM 이 없을 때 화면이 적을 까닭 — 금융사 주식 수 · 기준 다른 4분기 · 빠진 분기 · 적자."""
    bank = per_pts([None] * 3, {"지배순이익": 1e12})                       # 주식 수를 못 구함(주식수 없음)
    now = DRK.now_per(bank, {}, fin=True)
    assert now["per"] is None and now["eps_label"] is None and now["reason"].startswith("금융사 주식 수 산출 불가")
    assert DRK.now_per(bank, {})["reason"].startswith("주식 수 산출 불가")
    basis = per_pts([None] * 3, {})
    for i, p in enumerate(basis):
        p.update({"주식수": 1e6, "EPS_adj": None if i == 1 else 10.0})
    basis[1]["품질"] = ["basis"]                                          # Q4 기준이 달라 그 분기 EPS 없음
    assert DRK.now_per(basis, {})["reason"].startswith("기준 다른 4분기 포함")
    gapw = per_pts([None] * 3, {"EPS_adj": 10.0, "주식수": 1e6})
    del gapw[1]["fs"]
    assert DRK.now_per(gapw, {})["reason"].startswith("빠진 분기 포함")
    neg = per_pts([None] * 9, {"EPS_TTM": -50.0, "주가": 9000.0, "주가일": "20261008"})
    now = DRK.now_per(neg, {"20261008": 9000.0})
    assert now["per"] is None and now["pct"] is None and now["reason"].startswith("적자")
    assert DRK.now_per([{"n": 1, "품질": ["gap"]}], {"20261008": 1.0}) is None            # 자료 분기가 하나도 없다


def test_now_per_pct_needs_eight_values_and_skips_cut():
    last = {"EPS_TTM": 1000.0, "주가": 10000.0, "주가일": "20260814", "PER_TTM": 10.0}
    prices = {"20260814": 10000.0, "20261008": 10000.0}
    assert DRK.now_per(per_pts([5.0] * 7, last), prices)["pct"] == 100.0             # 정확히 8개
    assert DRK.now_per(per_pts([5.0] * 6, last), prices)["pct"] is None              # 7개
    pts = per_pts([5.0] * 7, last)
    pts[0]["품질"] = ["cut"]                                                           # cut 분기는 빠져 7개
    assert DRK.now_per(pts, prices)["pct"] is None
    pts = per_pts([5.0] * 7 + [-3.0, None], last)                                     # 음수 · None 은 세지 않는다
    assert DRK.now_per(pts, prices)["pct"] == 100.0


def test_now_per_pct_uses_last_40_valid_values():
    pts = per_pts([1.0] * 5 + [20.0] * 39, {"EPS_TTM": 1000.0, "주가": 20000.0, "주가일": "20260814", "PER_TTM": 20.0})
    pts += [{"품질": ["gap"]} for _ in range(3)]                                       # 끝의 빈 칸이 창을 줄이지 않는다
    now = DRK.now_per(pts, {"20260814": 20000.0, "20261008": 15000.0})
    assert now["per"] == 15.0 and now["pct"] == 0.0                                   # 앞의 싼 PER 5개는 창 밖


def test_now_per_none_cases():
    pts = per_pts([], {"EPS_TTM": 1000.0, "주가": 10000.0, "주가일": "20260814"})
    no_eps = DRK.now_per(per_pts([10.0] * 9), {"20261008": 1.0})                       # EPS_TTM 없음 — 값 없이 까닭만
    assert no_eps["per"] is None and no_eps["reason"] and no_eps["px"] == 1.0
    no_px = DRK.now_per(pts, {})                                                       # 주가 못 받음
    assert no_px["per"] is None and no_px["reason"] == "주가를 못 받음" and no_px["px"] is None
    neg = DRK.now_per(per_pts([10.0] * 9, {"EPS_TTM": -50.0}), {"20261008": 9000.0})
    assert neg["per"] is None and neg["pct"] is None and neg["reason"].startswith("적자")


# ---------------------------------------------------------------- 정정 공시 · 013 다시 묻기 — 원장 다시 받기와 NET 예산(Task 6 고침)
def _aged(p, ymd):
    t = time.mktime(time.strptime(ymd, "%Y%m%d"))
    os.utime(str(p), (t, t))
    return p


def test_filed_meta_amend_is_latest_tagged_rcept_per_quarter():
    reps = [rep("2025-06", "반기보고서", "20250814000002"),
            rep("2025-06", "반기보고서", "20251020000009", "[기재정정]"),
            rep("2025-06", "반기보고서", "20251105000010", "[기재정정]"),
            rep("2025-12", "사업보고서", "20260310000004")]
    assert DRK.filed_meta(reps)["amend"] == {(2025, 2): "20251105"}


def test_fetch_refetches_file_older_than_amendment_and_counts_it(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a, **kw: calls.append((a, kw)) or stmt([]))
    _aged(_cache_file(fin_dir, "C", 2025, "11012"), "20250820")
    monkeypatch.setitem(DRK.NET, "budget", 5)
    DRK._fetch("C", 2025, "11012", "CFS", True, amend="20251020")
    assert calls[-1][1] == {"force": True} and DRK.NET["used"] == 1
    DRK._fetch("C", 2025, "11012", "CFS", False, amend="20251020")        # online 도 다시 받되 예산엔 안 센다
    assert calls[-1][1] == {"force": True} and DRK.NET["used"] == 1


def test_fetch_keeps_cache_newer_than_amendment_or_without_one(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a, **kw: calls.append((a, kw)) or stmt([]))
    _aged(_cache_file(fin_dir, "C", 2025, "11012"), "20251021")
    DRK._fetch("C", 2025, "11012", "CFS", True, amend="20251020")         # 정정 다음 날 받은 파일
    DRK._fetch("C", 2025, "11012", "CFS", True)                           # 정정 없음
    assert [kw for _, kw in calls] == [{}, {}] and DRK.NET["used"] == 0


def test_fetch_refetches_when_amendment_is_same_day_as_file(monkeypatch, fin_dir):
    # 접수번호엔 시각이 없다 — 원장을 받은 그날 낮에 나온 기재정정도 다시 받아야 한다(같은 날 = 다시 받음, 예산에 센다)
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a, **kw: calls.append((a, kw)) or stmt([]))
    _aged(_cache_file(fin_dir, "C", 2025, "11012"), "20251021")
    monkeypatch.setitem(DRK.NET, "budget", 5)
    DRK._fetch("C", 2025, "11012", "CFS", True, amend="20251021")
    assert calls[-1][1] == {"force": True} and DRK.NET["used"] == 1


def test_fetch_amended_over_budget_is_transient(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a, **kw: calls.append((a, kw)) or stmt([]))
    _aged(_cache_file(fin_dir, "C", 2025, "11012"), "20250820")
    monkeypatch.setitem(DRK.NET, "budget", 0)
    out = DRK._fetch("C", 2025, "11012", "CFS", True, amend="20251020")
    assert out == {"status": "budget", "list": [], "transient": True} and calls == []


def test_fetch_stale_013_reask_is_charged_and_budgeted(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a, **kw: calls.append((a, kw)) or stmt([]))
    p = fin_dir / "C_2025_11014_CFS.json"
    p.write_text(json.dumps({"status": "013", "list": []}), encoding="utf-8")
    _aged(p, "20251001")                                  # 기한(9/30 + 100일) 전에 받은 013 — FIN 이 다시 묻는다
    q = fin_dir / "C_2025_11013_CFS.json"
    q.write_text(json.dumps({"status": "013", "list": []}), encoding="utf-8")
    _aged(q, "20250901")                                  # 1분기(3/31) + 100일 뒤에 받은 013 — 그대로 믿는다
    monkeypatch.setitem(DRK.NET, "budget", 1)
    DRK._fetch("C", 2025, "11013", "CFS", True)
    assert DRK.NET["used"] == 0
    DRK._fetch("C", 2025, "11014", "CFS", True)
    assert DRK.NET["used"] == 1 and len(calls) == 2
    assert DRK._fetch("C", 2025, "11014", "CFS", True)["status"] == "budget" and len(calls) == 2


def test_series_passes_amend_only_for_amended_quarters(monkeypatch):
    seen = []

    def pd(corp, y, q, offline=False, **kw):
        seen.append(((y, q), kw))
        return mk_q(100)
    monkeypatch.setattr(DRK, "period_data", pd)
    DRK.series("C", "000000", [2025], meta={"amend": {(2025, 2): "20251020"}})
    assert dict(seen) == {(2025, 1): {}, (2025, 2): {"amend": "20251020"}, (2025, 3): {}, (2025, 4): {}}


# ---------------------------------------------------------------- 검증 도구의 B 붙이기 — 공시일에 알 수 있던 B 만(Task 7 고침)
def test_b_lookup_joins_by_quarter_key_and_gates_on_b_date():
    pts = [{"n": 8063, "가속B": 4.0, "B기준일": "20160330"},
           {"n": 8064, "가속B": 5.0, "B기준일": "20160516"},          # 012450 2015Q4 꼴 — 공시 20160330, 앞 분기 정정으로 B기준일이 뒤
           {"n": 8065, "가속B": None, "B기준일": None}, {"품질": ["gap"]}]
    lk = DRK.b_lookup(pts)
    assert lk == {8063: (4.0, "20160330"), 8064: (5.0, "20160516"), 8065: (None, None)}
    assert DRK.b_known(lk, 8063, "20160330") == 4.0                 # 같은 날 — 그날 알 수 있다
    assert DRK.b_known(lk, 8064, "20160330") is None                # B기준일이 공시일 뒤 — 앞날 자료
    assert DRK.b_known(lk, 8064, "20160516") == 5.0
    assert DRK.b_known(lk, 8065, "20991231") is None and DRK.b_known(lk, 9999, "20991231") is None
    assert DRK.b_known(DRK.b_lookup([{"n": 1, "가속B": 3.0}]), 1, "20991231") is None     # 기준일 없음 — 알 수 있었는지 모른다


# ================================================================ 최종 검토 고침(2026-10-10)
# ---------------------------------------------------------------- F8 — 감사보고서는 결산월 판정에서 뺀다
def test_filed_meta_ignores_audit_reports_for_fy():
    """HPSP 상장 전 '감사보고서'(stamp 12) — 정기보고서가 아니니 그 해를 fy_bad('결산월 다름')로 만들지 않는다."""
    reps = [rep("2019-12", "감사보고서", "20200320000001"), rep("2020-12", "감사보고서", "20210320000002"),
            rep("2022-09", "분기보고서", "20221114000003"), rep("2022-12", "사업보고서", "20230320000004")]
    m = DRK.filed_meta(reps)
    assert m["fy_bad"] == set()
    assert m["filed"] == {2022 * 4 + 2: "20221114", 2022 * 4 + 3: "20230320"}
    assert DRK.filed_meta([rep("2024-06", "사업보고서", "20240920000001")])["fy_bad"] == {2024}    # 6월 결산 정기보고서는 그대로


# ---------------------------------------------------------------- 서버 S1 — 공시 전에(또는 공시 당일) 받아 둔 013 이 새 분기를 가리지 않게
def _ledger(dirpath, corp, year, reprt, fs="CFS", status="013", rows=None, ymd=None):
    p = dirpath / ("%s_%s_%s_%s.json" % (corp, year, reprt, fs))
    p.write_text(json.dumps({"status": status, "list": rows or []}), encoding="utf-8")
    return _aged(p, ymd) if ymd else p


def test_fetch_refetches_fresh_013_when_original_filing_is_today(monkeypatch, fin_dir):
    """오늘 아침(공시 전) 받아 둔 013 — 24시간이 안 돼 FIN 의 013 다시 묻기에도 안 걸린다. 원본 공시일이 파일 날짜와 같거나 뒤면
    force 로 다시 받는다(offline 은 예산에 센다, online 은 안 센다). 공시일이 없으면 예전처럼 그대로."""
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a, **kw: calls.append((a, kw)) or stmt([]))
    today = time.strftime("%Y%m%d")
    _ledger(fin_dir, "C", 2026, "11014")                                   # 지금 막 받은 013
    monkeypatch.setitem(DRK.NET, "budget", 5)
    DRK._fetch("C", 2026, "11014", "CFS", True)
    assert calls[-1][1] == {} and DRK.NET["used"] == 0
    DRK._fetch("C", 2026, "11014", "CFS", True, filed=today)
    assert calls[-1][1] == {"force": True} and DRK.NET["used"] == 1
    DRK._fetch("C", 2026, "11014", "CFS", False, filed=today)
    assert calls[-1][1] == {"force": True} and DRK.NET["used"] == 1
    monkeypatch.setitem(DRK.NET, "budget", 1)
    assert DRK._fetch("C", 2026, "11014", "CFS", True, filed=today)["status"] == "budget"     # 예산이 바닥나면 받지 않고 일시 오류


def test_fetch_keeps_ledger_with_data_or_fetched_after_filing(monkeypatch, fin_dir):
    calls = []
    monkeypatch.setattr(DRK.FIN, "fetch_statement", lambda *a, **kw: calls.append((a, kw)) or stmt([]))
    _ledger(fin_dir, "C", 2025, "11012", status="000", rows=[{"sj_div": "IS"}], ymd="20250814")   # 공시 당일 받았지만 자료가 있다
    _ledger(fin_dir, "C", 2025, "11014", ymd="20260120")                                         # 공시(2025-11-14) 뒤에 받은 013 — 믿는다
    DRK._fetch("C", 2025, "11012", "CFS", True, filed="20250814")
    DRK._fetch("C", 2025, "11014", "CFS", True, filed="20251114")
    assert [kw for _, kw in calls] == [{}, {}] and DRK.NET["used"] == 0


def test_series_passes_filed_date_per_quarter(monkeypatch):
    seen = []

    def pd(corp, y, q, offline=False, **kw):
        seen.append(((y, q), kw))
        return mk_q(100 + q)
    monkeypatch.setattr(DRK, "period_data", pd)
    DRK.series("C", "000000", [2025], meta={"filed": {2025 * 4 + 2: "20251114"}, "amend": {(2025, 2): "20251020"}})
    assert dict(seen) == {(2025, 1): {}, (2025, 2): {"amend": "20251020"}, (2025, 3): {"filed": "20251114"}, (2025, 4): {}}


def test_series_picks_up_quarter_filed_today_over_fresh_013(monkeypatch, fin_dir):
    """끝에서 끝까지 — 2026Q3 원장을 오늘 아침 013 으로 받아 뒀고 오늘 3분기보고서가 공시됐다. 밤 계산(offline)이 그 분기를 다시 받아 넣는다.
    공시일을 모르면(예전) 시리즈가 2026Q2 에서 끝나고, filed_missing 이 그 빌드를 캐시하지 말라고 알린다."""
    today = time.strftime("%Y%m%d")
    q3 = [row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=310, thstrm_add_amount=810)]
    table = {(2026, "11013"): stmt([row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=200, thstrm_add_amount=200)]),
             (2026, "11012"): stmt([row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=300, thstrm_add_amount=500)])}

    def fs(corp, year, reprt, fs_div="CFS", force=False):
        if (int(year), str(reprt)) == (2026, "11014") and force and fs_div == "CFS":
            return stmt(q3)                                                 # DART 는 이제 자료를 준다
        return table.get((int(year), str(reprt)), {"status": "013", "list": []}) if fs_div == "CFS" else {"status": "013", "list": []}
    monkeypatch.setattr(DRK.FIN, "fetch_statement", fs)
    for r in ("11013", "11012", "11011"):
        _ledger(fin_dir, "C", 2026, r, status="000", rows=[{"sj_div": "IS"}], ymd="20260901")
        _ledger(fin_dir, "C", 2026, r, fs="OFS", ymd="20260901")
    _ledger(fin_dir, "C", 2026, "11014")
    _ledger(fin_dir, "C", 2026, "11014", fs="OFS")
    meta = {"filed": {2026 * 4: "20260515", 2026 * 4 + 1: "20260814", 2026 * 4 + 2: today}, "fy_bad": set(), "amend": {}}
    pts = DRK.series("C", "000000", [2026], meta=meta, offline=True)
    assert [p["label"] for p in pts if p.get("fs")] == ["2026Q1", "2026Q2", "2026Q3"] and pts[-1]["매출액"] == 310
    assert DRK.filed_missing(pts, meta, today=today) is None
    old = DRK.series("C", "000000", [2026], meta=dict(meta, filed={}), offline=True)
    assert [p["label"] for p in old if p.get("fs")] == ["2026Q1", "2026Q2"]
    assert DRK.filed_missing(old, meta, today=today) == 2026 * 4 + 2


def test_filed_missing_newest_filed_quarter_without_ledger():
    pts = [{"n": 2026 * 4, "fs": "CFS"}, {"n": 2026 * 4 + 1, "fs": "CFS"}]
    meta = {"filed": {2026 * 4: "20260515", 2026 * 4 + 1: "20260814", 2026 * 4 + 2: "20261114"}, "fy_bad": set()}
    assert DRK.filed_missing(pts, meta, today="20261115") == 2026 * 4 + 2
    assert DRK.filed_missing(pts + [{"n": 2026 * 4 + 2, "fs": "OFS"}], meta, today="20261115") is None
    assert DRK.filed_missing(pts + [{"n": 2026 * 4 + 2, "품질": ["gap"]}], meta, today="20261115") == 2026 * 4 + 2   # 빈 칸은 자료가 아니다
    assert DRK.filed_missing(pts, meta, today="20261214") == 2026 * 4 + 2                  # 공시 뒤 30일까지는 일시 오류
    assert DRK.filed_missing(pts, meta, today="20261215") is None                          # 그 뒤엔 원장이 끝내 없는 분기로 본다
    assert DRK.filed_missing(pts, dict(meta, fy_bad={2026}), today="20261115") is None     # 결산월 다른 해는 보지 않는다
    assert DRK.filed_missing(pts, {}, today="20261115") is None


# ---------------------------------------------------------------- 서버 S2 — 예산이 끝난 뒤 '네트워크가 필요한 회사'만 건너뛰는 판정
def test_needs_net_mirrors_fetch_predicates(fin_dir):
    meta = {"filed": {2024 * 4 + 3: "20250310"}, "fy_bad": {2023}, "amend": {}}
    for r in ("11013", "11012", "11014", "11011"):
        _ledger(fin_dir, "C", 2024, r, status="000", rows=[{"sj_div": "IS"}], ymd="20250401")
    assert DRK.needs_net("C", [2023, 2024], meta) is False            # 2023 은 결산월 다른 해 — 안 본다. 2024 원장은 다 있다
    assert DRK.needs_net("C", [2024, 2025], meta) is True             # 2025 원장 파일이 없다
    assert DRK.needs_net("C", [2024], dict(meta, amend={(2024, 2): "20250402"})) is True    # 정정 공시가 파일보다 뒤
    _ledger(fin_dir, "C", 2024, "11011", ymd="20250310")              # 사업보고서 원장을 공시 당일 013 으로 받아 둠
    assert DRK.needs_net("C", [2024], meta) is True
    _ledger(fin_dir, "C", 2024, "11011", ymd="20250601")              # 공시 뒤에 받은 CFS 013(별도만 내는 회사) — OFS 를 본다
    assert DRK.needs_net("C", [2024], meta) is True                   # OFS 파일이 없다
    _ledger(fin_dir, "C", 2024, "11011", fs="OFS", status="000", rows=[{"sj_div": "IS"}], ymd="20250601")
    assert DRK.needs_net("C", [2024], meta) is False


# ---------------------------------------------------------------- F2 — 거짓 분할 · 병합
def test_share_basis_merger_window_does_not_guess_split_from_integer_ratio():
    """창에 합병 · 유상증자 공시만 있으면 정수 비율(5배)로 분할을 짐작하지 않는다 — 합병 신주는 주가를 보정하지 않는다.
    같은 모양에 공시가 없으면 새 수준이 두 분기 머문 뒤에 분할로 받는다."""
    sh = {"2025Q1": 10e6, "2025Q2": 10e6, "2025Q3": 50e6, "2025Q4": 50.5e6, "2026Q1": 49.8e6}
    out = DRK.share_basis(sh, [("20250820", "주요사항보고서(회사합병결정)")])
    assert [s["kind"] for s in out["splits"]] == ["증자 등(주가 보정 없음)"] and abs(out["now"]["2025Q1"] - 10e6) < 1
    out = DRK.share_basis(sh, [])
    assert [s["kind"] for s in out["splits"]] == ["분할·병합"] and abs(out["now"]["2025Q1"] - 50e6) < 1


def test_share_basis_undisclosed_split_needs_two_later_quarters():
    sh = {"2025Q1": 10e6, "2025Q2": 10e6, "2025Q3": 50e6}
    assert DRK.share_basis(sh, [])["splits"][0]["kind"] == "증자 등(주가 보정 없음)"           # 뒤 분기가 없다 — 아직 모름
    sh["2025Q4"] = 50.5e6
    assert DRK.share_basis(sh, [])["splits"][0]["kind"] == "증자 등(주가 보정 없음)"           # 하나뿐
    sh["2026Q1"] = 49.8e6
    assert DRK.share_basis(sh, [])["splits"][0]["kind"] == "분할·병합"
    out = DRK.share_basis({"2025Q1": 10e6, "2025Q2": 10e6, "2025Q3": 50e6}, [("20250820", "주식분할결정")])
    assert out["splits"][0]["kind"] == "분할·병합" and abs(out["now"]["2025Q2"] - 50e6) < 1   # 공시로 확인된 분할은 곧바로


def test_share_basis_posco_international_shape():
    """포스코인터내셔널 2022 — 틀린 4분기 역산 1,030만 주(0.084배, 12:1 꼴)가 합병 결정만 있는 창에 끼고, 다음 값은 합병 뒤 1.70억(×1.38 — 한 분기 튐
    거르기가 못 잡는다). 예전엔 '12:1 병합'으로 앞 기록 전부에 ×12 가 걸려 2019Q4 PER 이 6.6 대신 0.55 였다."""
    sh = {"2021Q4": 123.49e6, "2022Q1": 123.37e6, "2022Q2": 123.39e6, "2022Q4": 10.32e6,
          "2023Q2": 170.13e6, "2023Q3": 170.16e6, "2023Q4": 179.65e6, "2024Q1": 170.31e6}
    sev = [("20220812", "주요사항보고서(회사합병결정)"), ("20220817", "주요사항보고서(회사합병결정)"), ("20220926", "주요사항보고서(회사합병결정)")]
    out = DRK.share_basis(sh, sev)
    assert not [s for s in out["splits"] if s["kind"].startswith("분할")]
    assert abs(out["now"]["2021Q4"] - 123.49e6) < 1 and "2022Q4" not in out["now"]


def test_share_basis_sk_innovation_shape():
    """SK이노베이션 2023Q4 — 역산 7.6억 주(실제 약 0.97억)가 5.88배 · 0.126배 두 '분할'로 읽혀 그 앞 기록 전부에 ×0.743 이 걸렸다.
    공시 없는 큰 변화의 새 수준이 바로 되돌아가면(나가는 쪽도 공시 없음) 그 분기는 자료 오류로 버리고 앞뒤를 잇는다."""
    sh = {"2023Q1": 85.49e6, "2023Q2": 87.49e6, "2023Q3": 129.82e6, "2023Q4": 763.98e6, "2024Q2": 96.46e6,
          "2024Q3": 96.47e6, "2024Q4": 117.97e6, "2025Q1": 148.77e6, "2025Q2": 148.76e6}
    sev = [("20230623", "주요사항보고서(유상증자결정)"), ("20230802", "주요사항보고서(유상증자결정)"),
           ("20230907", "주요사항보고서(유상증자결정)"), ("20240717", "주요사항보고서(회사합병결정)")]
    out = DRK.share_basis(sh, sev)
    assert out["splits"] == [] and "2023Q4" not in out["now"]
    assert all(abs(out["now"][k] - v) < 1 for k, v in sh.items() if k != "2023Q4")      # 앞 기록에 비율이 걸리지 않는다
    sev_adj = sev + [("20240101", "주식병합결정")]                                       # 나가는 쪽에 병합 공시가 있으면 버리지 않는다
    assert "2023Q4" in DRK.share_basis(sh, sev_adj)["now"]


def test_share_basis_keeps_level_changed_by_merger_then_disclosed_consolidation():
    """코스텍시스 꼴 — 합병 신주로 주식 수가 4.9배(공시 없는 분할 아님), 두 분기 뒤 공시된 주식 병합으로 다시 0.35배.
    새 수준이 두 분기 머물지 못했지만 그 사이에 공시된 병합이 있으니 '튄 분기'로 버리지 않는다(합병 신주 → 증자 등, 병합 → 분할·병합)."""
    sh = {"2022Q3": 2.0e6, "2022Q4": 2.0e6, "2023Q1": 9.8e6, "2023Q2": 9.9e6, "2023Q4": 3.46e6, "2024Q1": 3.5e6}
    sev = [("20221228", "주요사항보고서(회사합병결정)"), ("20230105", "주요사항보고서(회사합병결정)"), ("20231026", "주식병합결정")]
    out = DRK.share_basis(sh, sev)
    assert "2023Q1" in out["now"]
    assert [(s["at"], s["kind"]) for s in out["splits"]] == [("2023Q1", "증자 등(주가 보정 없음)"), ("2023Q4", "분할·병합")]
    assert out["now"]["2022Q3"] == pytest.approx(2.0e6 * 3.46 / 9.9)                 # 앞 기록엔 병합 비율만 걸린다(합병 비율은 안 건다)


def test_q4_eps_with_opposite_sign_q3_cumulative_gives_no_share_count(monkeypatch):
    """포스코인터내셔널 2022 — 3분기 누적 EPS −4,042 · 누적 순이익 +4,987억. 연간 − 누적으로 뗀 4분기 EPS 8,822 는 틀린 값이라
    그 분기 주식 수(1,030만)를 쓰지 않는다. 4분기 EPS_adj 는 이웃 분기 주식 수로."""
    E8 = 1e8
    t = {(2022, 1): mk_q(9.9e12, ni=1605 * E8, EPS=1301.0),
         (2022, 2): mk_q(11.0e12, cum=20.9e12, ni=2289 * E8, EPS=1855.0, **{"지배순이익_누적": 3894 * E8, "EPS_누적": 3156.0}),
         (2022, 3): mk_q(9.0e12, cum=29.9e12, ni=1093 * E8, EPS=-886.0, **{"지배순이익_누적": 4987 * E8, "EPS_누적": -4042.0}),
         (2022, 4): mk_q(37.9e12, ni=5897 * E8, EPS=4780.0),
         (2023, 1): mk_q(8.3e12, ni=1807 * E8, EPS=1062.0),
         (2023, 2): mk_q(8.9e12, cum=17.2e12, ni=2237 * E8, EPS=1315.0),
         (2023, 3): mk_q(8.0e12, cum=25.2e12, ni=2006 * E8, EPS=1179.0)}
    pts = run_series(monkeypatch, t, [2022, 2023])
    by = {p["label"]: p for p in pts}
    assert by["2022Q4"]["EPS"] == 4780.0 + 4042.0 and by["2022Q4"].get("주식수_제외") is True
    assert not by["2022Q3"].get("주식수_제외") and not by["2023Q1"].get("주식수_제외")
    DRK.per_share(pts, [("20220812", "주요사항보고서(회사합병결정)")])
    assert abs(by["2022Q1"]["EPS_adj"] - 1301) < 1                                      # ×12 가 안 걸린다
    assert 500 < by["2022Q4"]["EPS_adj"] < 800 and by["2022Q3"]["EPS_adj"] > 0          # 4분기 · 3분기는 이웃 분기 주식 수로(부호도 순이익 쪽)


# ---------------------------------------------------------------- F5 — 매출 없는 분기도 주식 수
def test_per_share_without_revenue_still_gets_shares():
    """매출 줄이 없는 은행 · 지주(KB금융 꼴) — 순이익 ÷ EPS 로 주식 수와 EPS_TTM 을 낸다. 매출이 있는 분기의 0.5% 조건은 그대로."""
    pts = grid([0] * 6)
    for p in pts:
        p["지배순이익"], p["EPS"] = 1.4e12, 3600.0
    DRK.per_share(pts, [])
    assert pts[-1]["EPS_TTM"] == pytest.approx(4 * 3600.0) and pts[-1]["주식수"] == pytest.approx(1.4e12 / 3600)
    small = grid([0] * 6)
    for p in small:
        p["지배순이익"], p["EPS"], p["매출액"] = 1e8, 10.0, 1e12                 # 순이익이 매출의 0.01% — 반올림 EPS 로 주식 수가 흔들린다
    DRK.per_share(small, [])
    assert all(p["주식수"] is None and p["EPS_TTM"] is None for p in small)
    mixed = grid([0] * 6)                                                    # IFRS17 뒤 매출 줄이 끊긴 보험사 — 끊긴 뒤에도 EPS_adj 가 이어진다
    for i, p in enumerate(mixed):
        p["지배순이익"], p["EPS"] = 2e11, 4000.0
        if i < 2:
            p["매출액"] = 5e12
    DRK.per_share(mixed, [])
    assert all(p["EPS_adj"] == pytest.approx(4000.0) for p in mixed) and mixed[-1]["EPS_TTM"] == pytest.approx(16000.0)


# ---------------------------------------------------------------- F4 — 금융사 기준은 최근 8개 자료 분기로
def test_pick_basis_recent_eight_data_quarters():
    ins = [{"n": i, "fs": "CFS", "매출액": 1e12 if i < 30 else None} for i in range(40)]     # IFRS17 뒤 매출 줄이 끊긴 보험사(최근 10분기)
    assert DRK.pick_basis(ins, True) == "영업이익"
    assert DRK.pick_basis(ins, False) == "매출"                                             # 금융이 아니면 늘 매출
    ins[33]["매출액"] = 1e12                                                               # 최근 8분기 안에 매출이 한 분기라도 있으면 매출
    assert DRK.pick_basis(ins, True) == "매출"
    tail = [dict(p, 매출액=1e12) for p in ins[:30]] + [{"n": 30 + i, "품질": ["gap"]} for i in range(10)]   # 끝의 빈 칸은 자료 분기가 아니다
    assert DRK.pick_basis(tail, True) == "매출"
    assert DRK.pick_basis([], True) == "영업이익"


# ---------------------------------------------------------------- F3 — 마지막 자료 분기 뒤 분할이면 PER 을 비운다
def test_hold_per_blanks_every_per_while_split_after():
    pts = [{"PER_TTM": 10.0}, {"PER_TTM": 12.0, "EPS_TTM": 1000.0}]
    assert DRK.hold_per(pts, []) is False and pts[1]["PER_TTM"] == 12.0
    assert DRK.hold_per(pts, [{"date": "20260901", "title": "주식분할결정"}]) is True
    assert all("PER_TTM" not in p for p in pts) and pts[1]["EPS_TTM"] == 1000.0


# ---------------------------------------------------------------- F6 — 3개월 칸에 적힌 누적
def test_cumulative_written_in_quarter_column_is_differenced(monkeypatch):
    """DL 2024 — 반기 · 3분기 보고서가 3개월 칸에 누적을 적었다(2.90조 = 반기 누적, 4.32조 = 9개월; 비교 칸은 빔).
    같은 해 바로 앞 분기에 같은 기준 누적이 있으면 분기 단독 = 누적 − 앞 누적(EPS · 순이익도)."""
    E8 = 1e8
    t = {(2024, 1): mk_q(1.4029e12, cum=1.4029e12, ni=200 * E8, EPS=500.0, **{"지배순이익_누적": 200 * E8, "EPS_누적": 500.0}),
         (2024, 2): mk_q(2.8962e12, cum=2.8962e12, ni=399 * E8, EPS=998.0, **{"지배순이익_누적": 399 * E8, "EPS_누적": 998.0}),
         (2024, 3): mk_q(4.3185e12, cum=4.3185e12, ni=606 * E8, EPS=1516.0, **{"지배순이익_누적": 606 * E8, "EPS_누적": 1516.0})}
    by = {p["label"]: p for p in run_series(monkeypatch, t, [2024])}
    assert by["2024Q1"]["매출액"] == 1.4029e12
    assert by["2024Q2"]["매출액"] == pytest.approx(2.8962e12 - 1.4029e12) and by["2024Q2"]["EPS"] == pytest.approx(498.0)
    assert by["2024Q3"]["매출액"] == pytest.approx(4.3185e12 - 2.8962e12) and by["2024Q3"]["EPS"] == pytest.approx(518.0)
    assert by["2024Q3"]["지배순이익"] == pytest.approx(207 * E8) and by["2024Q2"]["품질"] == [] and by["2024Q3"]["품질"] == []
    assert t[(2024, 2)]["매출액"] == 2.8962e12                                          # 원장 사본만 고친다
    t[(2024, 2)] = mk_q(2.8962e12, cum=2.8962e12, fs="OFS")                             # 앞 분기와 기준(fs)이 다르면 비우고 basis
    q2 = {p["label"]: p for p in run_series(monkeypatch, t, [2024])}["2024Q2"]
    assert q2.get("매출액") is None and q2.get("EPS") is None and "basis" in q2["품질"]
    first = {(2018, 2): mk_q(9.0e11, cum=9.0e11), (2018, 3): mk_q(1.0e12, cum=1.9e12)}   # 분할 신설 회사의 첫 반기 — 앞 분기 원장이 없다
    pts = run_series(monkeypatch, first, [2018])
    assert pts[0]["label"] == "2018Q2" and pts[0]["매출액"] == 9.0e11 and pts[0]["품질"] == [] and pts[1]["매출액"] == 1.0e12


# ---------------------------------------------------------------- F7 — 보고서 하나가 통째로 ×1e6
def test_report_scaled_by_million_is_divided_and_tagged(monkeypatch):
    """동성케미컬 2017 반기 꼴 — 매출 · 순이익 · EPS 가 모두 ×1e6. 순이익 ÷ EPS 는 맞아 EPS 단위 검사로는 못 잡는다 —
    분기 매출이 앞뒤 분기 둘 다의 100배를 넘으면 그 보고서 손익(비교 칸 포함)을 ÷1e6(안 맞으면 ÷1e3)로 맞추고 unit."""
    E8 = 1e8
    t = {(2017, 1): mk_q(2.0e11, ni=40 * E8, EPS=90.0),
         (2017, 2): mk_q(2.1e17, prev=1.9e17, ni=45e14, EPS=51e6),
         (2017, 3): mk_q(2.2e11, cum=6.3e11, ni=42 * E8, EPS=95.0)}
    q2 = {p["label"]: p for p in run_series(monkeypatch, t, [2017])}["2017Q2"]
    assert q2["매출액"] == pytest.approx(2.1e11) and q2["매출액_전"] == pytest.approx(1.9e11) and q2["EPS"] == pytest.approx(51.0)
    assert q2["지배순이익"] == pytest.approx(45 * E8) and q2["품질"] == ["unit"] and q2["YoY_r"] == pytest.approx((2.1 / 1.9 - 1) * 100)
    t[(2017, 2)] = mk_q(2.1e14, ni=45e11, EPS=51e3)                                        # ×1e3
    q2 = {p["label"]: p for p in run_series(monkeypatch, t, [2017])}["2017Q2"]
    assert q2["매출액"] == pytest.approx(2.1e11) and q2["EPS"] == pytest.approx(51.0) and q2["품질"] == ["unit"]
    t[(2017, 2)] = mk_q(5.0e15, ni=1e12, EPS=10.0)                                         # ÷1e6 · ÷1e3 둘 다 앞뒤 평균의 0.2~5배 밖 — 비운다
    q2 = {p["label"]: p for p in run_series(monkeypatch, t, [2017])}["2017Q2"]
    assert q2.get("매출액") is None and q2.get("EPS") is None and q2["품질"] == ["unit"]
    t[(2017, 2)] = mk_q(1.2e13)                                                            # 60배 — 진짜 큰 분기일 수 있다(손대지 않음)
    q2 = {p["label"]: p for p in run_series(monkeypatch, t, [2017])}["2017Q2"]
    assert q2["매출액"] == 1.2e13 and "unit" not in q2["품질"]
    t4 = {(2017, 3): mk_q(2.2e11, cum=6.3e11), (2017, 4): mk_q(8.6e17), (2018, 1): mk_q(2.4e11)}   # 사업보고서가 ×1e6 — 연간 쪽을 나눈다
    q4 = {p["label"]: p for p in run_series(monkeypatch, t4, [2017, 2018])}["2017Q4"]
    assert q4["매출액"] == pytest.approx(8.6e11 - 6.3e11) and q4["품질"] == ["unit"]
