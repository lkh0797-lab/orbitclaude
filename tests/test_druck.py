# -*- coding: utf-8 -*-
import os, sys, json, importlib.util as ilu
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
    monkeypatch.setattr(DRK, "period_data", lambda corp, y, q, offline=False: table.get((y, q)))
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


def test_version_is_2():
    assert DRK.VERSION == 2


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


def test_turn_through_flat_band():
    # 삼성 모양: B ... −6.2 → +10.9(▲) → +41.7(같은 쪽 — 변곡 아님)
    pts = grid([0] * 8)
    Bs = [None, None, None, -9.2, -6.2, 10.9, 41.7, 1.0]
    for p, b in zip(pts, Bs):
        p["가속B"] = b
    DRK._turns(pts)
    assert [p["변곡"] for p in pts][4:7] == [None, "▲", None]


def test_turn_needs_within_4():
    pts = grid([0] * 8)
    for p, b in zip(pts, [-5, 1, 1, 1, 1, 6, None, None]):
        p["가속B"] = b
    DRK._turns(pts)
    assert pts[5]["변곡"] is None        # 반대쪽 띠 밖 값이 5분기 앞 — 변곡 아님


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
                                                   row("IS", EPS_DISC, "중단영업 기본주당이익", thstrm_amount=-390)])
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
def per_pts(pers, last=None):
    pts = [{"PER_TTM": v, "품질": []} for v in pers]
    if last is not None:
        pts.append(dict(last, 품질=last.get("품질", [])))
    return pts


def test_now_per_k1():
    pts = per_pts([10.0] * 7, {"EPS_TTM": 1000.0, "주가": 12000.0, "주가일": "20260814", "PER_TTM": 12.0})
    now = DRK.now_per(pts, {"20260814": 12000.0, "20261008": 15000.0})
    assert now == {"px": 15000.0, "date": "20261008", "per": 15.0, "k": 1.0, "pct": 100.0, "stale": False, "split_after": []}


def test_now_per_k_after_split_rescales_eps_and_is_stale():
    pts = per_pts([], {"EPS_TTM": 5000.0, "주가": 100000.0, "주가일": "20260814", "PER_TTM": 20.0})
    now = DRK.now_per(pts, {"20260814": 20000.0, "20261008": 21000.0})     # 캐시 뒤 5:1 분할 — 수정주가는 옛 날짜도 1/5
    assert now["k"] == 5.0 and now["per"] == pytest.approx(21000 / 1000) and now["stale"] is True


def test_now_per_k_from_last_point_with_eps_price_and_date():
    pts = [{"EPS_TTM": 900.0, "주가": 30000.0, "주가일": "20260514", "품질": []},
           {"EPS_TTM": 1000.0, "품질": []}]                                   # 최신 분기는 주가가 아직 없다
    now = DRK.now_per(pts, {"20260514": 20000.0, "20261008": 30000.0})
    assert now["k"] == 1.5 and now["per"] == pytest.approx(30000 / (1000 / 1.5)) and now["stale"] is False


@pytest.mark.parametrize("cached,stale", [(11000.0, True), (11200.0, False), (20000.0, False), (35800.0, False), (36000.0, True)])
def test_now_per_stale_thresholds(cached, stale):
    """k = 0.55 · 1.8 은 낡음(경계 포함), 0.56 · 1.79 는 아님."""
    pts = per_pts([], {"EPS_TTM": 1000.0, "주가": cached, "주가일": "20260814"})
    now = DRK.now_per(pts, {"20260814": 20000.0, "20261008": 20000.0})
    assert now["k"] == round(cached / 20000.0, 3) and now["stale"] is stale


def test_now_per_split_after_is_stale_even_with_k1():
    sa = [{"date": "20260901", "title": "주식분할결정"}]
    pts = per_pts([], {"EPS_TTM": 1000.0, "주가": 10000.0, "주가일": "20260814"})
    now = DRK.now_per(pts, {"20260814": 10000.0, "20261008": 10000.0}, sa)
    assert now["k"] == 1.0 and now["stale"] is True and now["split_after"] == sa


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
    assert DRK.now_per(per_pts([10.0] * 9), {"20261008": 1.0}) is None                 # EPS_TTM 없음
    assert DRK.now_per(pts, {}) is None                                               # 주가 못 받음
    neg = DRK.now_per(per_pts([10.0] * 9, {"EPS_TTM": -50.0}), {"20261008": 9000.0})
    assert neg["per"] is None and neg["pct"] is None
