# -*- coding: utf-8 -*-
import os, sys, importlib.util as ilu
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
