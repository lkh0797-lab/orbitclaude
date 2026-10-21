import io
import json
import zipfile
from datetime import date

import pytest

from export_overlay import dart
from export_overlay.cache import JsonCache


def row(div, tag, name, cur, cum=None):
    return {"sj_div": div, "account_id": tag, "account_nm": name, "thstrm_amount": cur, "thstrm_add_amount": cum}


def test_num_handles_korean_negative_notations():
    assert dart.num("1,234") == 1234.0
    assert dart.num("(1,234)") == -1234.0
    assert dart.num("△500") == -500.0
    assert dart.num("-") is None and dart.num(None) is None and dart.num("") is None


def test_pick_prefers_tag_then_is_over_cis():
    rows = [
        row("CIS", "ifrs-full_Revenue", "수익(매출액)", "100", "300"),
        row("IS", "ifrs-full_Revenue", "매출액", "110", "310"),
        row("IS", "-표준계정코드 미사용-", "매출액", "999"),
        row("IS", "dart_OperatingIncomeLoss", "영업이익(손실)", "(20)", "15"),
        row("BS", "ifrs-full_Revenue", "매출액", "777"),
    ]
    assert dart.pick(rows, "revenue") == dart.Figure(110.0, 310.0)
    assert dart.pick(rows, "operating") == dart.Figure(-20.0, 15.0)


def test_pick_falls_back_to_names_and_strips_numbering():
    rows = [row("CIS", "-표준계정코드 미사용-", "Ⅰ. 영업수익", "50"),
            row("CIS", "-표준계정코드 미사용-", "Ⅳ. 영업손실", "(5)")]
    assert dart.pick(rows, "revenue") == dart.Figure(50.0, None)
    assert dart.pick(rows, "operating") == dart.Figure(-5.0, None)
    assert dart.pick([row("IS", "x", "영업외수익", "1")], "operating") is None


def test_due_date_rolls_weekend_to_monday():
    assert dart.due_date(2026, 3) == date(2026, 11, 16)      # 11-14 is a Saturday
    assert dart.due_date(2025, 4) == date(2026, 3, 31)


class FakeDart:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url.rsplit("/", 1)[-1], params.get("fs_div")))
        return self.responses[(url.rsplit("/", 1)[-1], params.get("fs_div"))]


def test_report_falls_back_to_separate_statements_and_caches(tmp_path):
    fake = FakeDart({
        ("fnlttSinglAcntAll.json", "CFS"): {"status": "013", "message": "조회된 데이타가 없습니다."},
        ("fnlttSinglAcntAll.json", "OFS"): {"status": "000", "list": [row("IS", "ifrs-full_Revenue", "매출액", "70", "70")]},
    })
    client = dart.DartClient("SECRET", JsonCache(tmp_path), get_json=fake, today=date(2026, 10, 21))
    got = client.report("00000001", 2025, 1)
    assert got == dart.ReportFigures("OFS", dart.Figure(70.0, 70.0), None)
    client.report("00000001", 2025, 1)
    assert len(fake.calls) == 2
    assert all("SECRET" not in p.read_text(encoding="utf-8") for p in tmp_path.iterdir())


def test_transient_errors_raise_and_are_not_cached(tmp_path):
    fake = FakeDart({("fnlttSinglAcntAll.json", "CFS"): {"status": "020", "message": "요청 제한"}})
    client = dart.DartClient("K", JsonCache(tmp_path), get_json=fake, today=date(2026, 10, 21))
    with pytest.raises(dart.DartError, match="020"):
        client.report("00000001", 2025, 1)
    assert list(tmp_path.iterdir()) == []


def test_not_filed_yet_is_rechecked_daily_after_deadline_monthly(tmp_path):
    client = dart.DartClient("K", JsonCache(tmp_path), get_json=lambda u, p: {}, today=date(2026, 10, 21))
    assert client._ttl(2026, 3, "013") == dart.DAY
    assert client._ttl(2024, 3, "013") == 30 * dart.DAY
    assert client._ttl(2024, 3, "000") == 90 * dart.DAY
    assert client._ttl(2026, 2, "000") == 7 * dart.DAY


def test_old_ifrs_prefix_and_extra_names_are_recognised():
    assert dart.pick([row("CIS", "ifrs_Revenue", "매출", "70")], "revenue") == dart.Figure(70.0, None)
    for name in ("수익", "고객과의 계약에서 생기는 수익"):
        assert dart.pick([row("CIS", "-표준계정코드 미사용-", name, "5")], "revenue").cur == 5.0
    assert dart.pick([row("CIS", "-표준계정코드 미사용-", "영업순손익", "3")], "operating").cur == 3.0
    # HPSP 2024 annual: untagged rows with 매출원가 before 매출액 — revenue names are exact, not prefixes
    hpsp = [row("CIS", "", "매출원가", "40"), row("CIS", "", "매출총이익", "60"), row("CIS", "", "매출액", "100")]
    assert dart.pick(hpsp, "revenue").cur == 100.0
    assert dart.pick([row("CIS", "", "영업외손익", "9")], "operating") is None


def test_comparative_columns_quarterly_vs_annual():
    q = {"sj_div": "CIS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": "432",
         "thstrm_add_amount": "948", "frmtrm_q_amount": "287", "frmtrm_amount": "583", "frmtrm_add_amount": "583"}
    # 2016 quarterly reports put the prior-year cumulative in frmtrm_amount; it must not be read as 3 months
    assert dart.pick([q], "revenue") == dart.Figure(432.0, 948.0, 287.0, 583.0)
    a = dict(q, thstrm_add_amount="", frmtrm_q_amount=None, frmtrm_add_amount=None)
    assert dart.pick([a], "revenue", annual=True) == dart.Figure(432.0, None, 583.0, None)


def test_fresh_annual_report_refreshes_q3(tmp_path):
    served = {"v": "100"}

    def fake(url, params):
        if params["fs_div"] == "OFS":
            return {"status": "013"}
        amount = served["v"] if params["reprt_code"] == "11014" else "500"
        return {"status": "000", "list": [row("IS", "ifrs-full_Revenue", "매출액", amount, amount)]}

    client = dart.DartClient("K", JsonCache(tmp_path), get_json=fake, today=date(2026, 10, 21))
    assert client.report("C", 2024, 3).revenue.cur == 100.0
    served["v"] = "120"                                       # Q3 corrected after it was cached
    assert client.report("C", 2024, 3).revenue.cur == 100.0  # the cache still serves the old version
    client.report("C", 2024, 4)                               # annual fetched fresh → Q3 refetched
    assert client.report("C", 2024, 3).revenue.cur == 120.0


def test_corp_codes_reads_listed_companies_from_zip(tmp_path):
    xml = ("<result><list><corp_code>00123456</corp_code><corp_name>한미반도체</corp_name>"
           "<stock_code>042700</stock_code></list><list><corp_code>00999999</corp_code>"
           "<corp_name>비상장</corp_name><stock_code> </stock_code></list></result>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    client = dart.DartClient("K", JsonCache(tmp_path), get_bytes=lambda u, p: buf.getvalue())
    assert client.corp_codes() == {"042700": {"corp_code": "00123456", "corp_name": "한미반도체"}}


def test_outage_falls_back_to_expired_cache_and_records_it(tmp_path):
    now = [0.0]
    cache = JsonCache(tmp_path, clock=lambda: now[0])
    ok = {"status": "000", "list": [row("IS", "ifrs-full_Revenue", "매출액", "100", "100")]}
    calls = []

    def fake(url, params):
        calls.append(params["reprt_code"])
        if now[0] > 0:
            raise dart.DartError("연결 실패: ConnectionError")
        return ok

    client = dart.DartClient("K", cache, get_json=fake, today=date(2026, 10, 21))
    assert client.report("C", 2026, 2).revenue.cur == 100.0
    now[0] = max(f.stat().st_mtime for f in tmp_path.iterdir()) + 30 * dart.DAY    # past the 7-day TTL
    assert client.report("C", 2026, 2).revenue.cur == 100.0                          # served stale, not dropped
    assert len(client.stale) == 1 and "ConnectionError" in client.stale[0]
    with pytest.raises(dart.DartError):
        client.report("C", 2025, 2)                                                  # nothing cached to fall back on


def test_periods_that_have_not_ended_are_not_requested(tmp_path):
    def boom(url, params):
        raise AssertionError("must not be requested")

    client = dart.DartClient("K", JsonCache(tmp_path), get_json=boom, today=date(2026, 10, 21))
    assert client.report("C", 2026, 4) is None


def test_failed_q3_refresh_leaves_the_annual_uncached(tmp_path):
    state = {"fail_q3": False}

    def fake(url, params):
        if params["fs_div"] == "OFS":
            return {"status": "013"}
        if params["reprt_code"] == "11014" and state["fail_q3"]:
            raise dart.DartError("HTTP 500")
        return {"status": "000", "list": [row("IS", "ifrs-full_Revenue", "매출액", "100", "100")]}

    client = dart.DartClient("K", JsonCache(tmp_path), get_json=fake, today=date(2026, 10, 21))
    client.report("C", 2024, 3)
    state["fail_q3"] = True
    with pytest.raises(dart.DartError):
        client.report("C", 2024, 4)
    assert not any("11011" in p.name for p in tmp_path.iterdir())     # retried, with Q3, on the next run


def test_compact_keeps_only_what_pick_reads():
    full = [
        {"sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계", "thstrm_amount": "9", "rcept_no": "R1"},
        {"sj_div": "CIS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": "432", "thstrm_add_amount": "948",
         "frmtrm_q_amount": "287", "frmtrm_amount": "", "frmtrm_add_amount": "583", "rcept_no": "R1", "corp_code": "C", "currency": "KRW"},
        {"sj_div": "CIS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "thstrm_amount": "40", "rcept_no": "R1"},
    ]
    small = dart.compact(full)
    assert len(small) == 2 and "corp_code" not in small[0] and small[0]["rcept_no"] == "R1"
    for which in ("revenue", "operating"):
        assert dart.pick(small, which) == dart.pick(full, which)
    assert dart.compact([full[0]]) == [{"sj_div": "-", "rcept_no": "R1"}]     # filed, no income statement


def test_reports_are_cached_compacted(tmp_path):
    full = {"status": "000", "list": [row("BS", "x", "자산총계", "1"), row("IS", "ifrs-full_Revenue", "매출액", "70", "70")]}
    client = dart.DartClient("K", JsonCache(tmp_path), get_json=lambda u, p: full if p["fs_div"] == "CFS" else {"status": "013"},
                             today=date(2026, 10, 21))
    assert client.report("C", 2025, 1).revenue.cur == 70.0
    stored = json.loads(next(tmp_path.glob("dart_fs_*")).read_text(encoding="utf-8"))
    assert [r["sj_div"] for r in stored["list"]] == ["IS"]
