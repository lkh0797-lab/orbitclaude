import json
import re
from datetime import date, datetime

import pytest

from export_overlay import build, config, customs, main, page
from export_overlay.config import Company, Sector, View
from export_overlay.customs import ItemExports
from export_overlay.dart import Figure, ReportFigures

SECTOR = Sector(
    key="semi", name="반도체 장비", noun="장비사", hs=("8486",),
    views=(View("8486", "8486 전체", ("8486",)), View("848620", "본체", ("848620",)), View("848690", "부품", ("848690",))),
    companies=(Company("000001", "가"), Company("000002", "나")),
    caveat="해외로 나간 장비만.",
)


def months_by_sub(start="201601", n=36):
    out, ym = {}, start
    for i in range(n):
        out[ym] = {"848620": 100.0 + i, "848690": 50.0}
        ym = f"{int(ym[:4]) + (ym[4:] == '12')}{int(ym[4:]) % 12 + 1:02d}"
    return out


def exports(n=36):
    months = months_by_sub(n=n)
    return ItemExports(months, {ym: {"848620": {"중국": 60.0, "대만": 40.0 + i}} for i, ym in enumerate(months)})


def reports(base):
    out = {}
    for y in (2016, 2017, 2018):
        for q in (1, 2, 3):
            v = base * (1 + 0.1 * (y - 2016)) + q
            prev = base * (1 + 0.1 * (y - 2017)) + q
            out[(y, q)] = ReportFigures("CFS", Figure(v, None, prev), Figure(v / 10, None, prev / 10))
        out[(y, 4)] = None
    return out


def payload(companies=None, fx=None, sector=SECTOR):
    companies = companies or [build.CompanyInput(Company("000001", "가"), reports(100)),
                              build.CompanyInput(Company("000002", "나"), error="DART 고유번호 없음")]
    return build.build_payload(sector, exports(), fx if fx is not None else {}, companies, "2026-10-21 09:00")


def embedded(html):
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


def test_payload_shapes_and_alignment():
    p = payload()
    assert p["months"][0] == "201701" and p["months"][-1] == "201812"     # first YoY-able month onward
    assert [c["key"] for c in p["codes"]] == ["8486", "848620", "848690"]
    total12 = sum(124 + i for i in range(12)) + 600
    assert [c["share"] for c in p["codes"]] == [100.0, round(1554 / total12 * 100, 1), round(600 / total12 * 100, 1)]
    assert p["sector"]["name"] == "반도체 장비" and p["sector"]["noun"] == "장비사" and p["sector"]["hs"] == ["8486"]
    assert p["currencies"] == ["USD"]
    ex = p["exports"]["8486|USD"]
    assert len(ex["value"]) == len(ex["yoy"]) == len(ex["yoy3"]) == len(p["months"]) == len(p["fx"])
    assert ex["quarters"]["2017Q1"]["yoy"] == round(((112 + 113 + 114 + 150) / (100 + 101 + 102 + 150) - 1) * 100, 1)
    assert set(ex["lags"]) == {"basket", "000001"}
    assert [d["lag"] for d in ex["lags"]["basket"]] == [-1, 0, 1, 2]
    assert p["reported"] == "2018Q3"
    assert p["warnings"] == ["나: DART 고유번호 없음"]
    first = next(c for c in p["companies"] if c["code"] == "000001")
    assert first["quarters"]["2017Q1"]["revenue_yoy"] == round((111 / 101 - 1) * 100, 1)
    assert first["first_yoy"] == "2016Q1"                    # base from the report's own comparative column
    assert p["basket"]["2017Q1"]["matched"] == 1
    assert p["basket"]["2017Q1"]["top"] == {"name": "가", "share": 100}
    assert p["destinations"]["848620"][0]["name"] == "대만"
    assert p["destinations_span"] == ["201801", "201812"]


def test_main_view_need_not_be_every_queried_code():
    # e.g. 2차전지 = lithium-ion + parts only, though the query returns lead-acid too
    sector = Sector(key="b", name="2차전지", noun="배터리사", hs=("8486",),
                    views=(View("main", "본체만", ("848620",)), View("parts", "부품", ("848690",))),
                    companies=(Company("000001", "가"),), caveat="")
    p = payload([build.CompanyInput(Company("000001", "가"), reports(100))], sector=sector)
    assert p["exports"]["main|USD"]["value"][0] == 112.0
    assert p["codes"][1]["share"] == round(600 / 1554 * 100, 1)              # relative to the main view


def test_krw_is_offered_only_with_fx():
    fx = {ym: 1000.0 for ym in months_by_sub()}
    p = payload(fx=fx)
    assert p["currencies"] == ["KRW", "USD"]
    assert p["exports"]["8486|KRW"]["value"][0] == p["exports"]["8486|USD"]["value"][0] * 1000
    assert p["fx"][0] == 1000.0


def test_pending_quarters_and_quarter_in_progress():
    companies = [build.CompanyInput(Company("000001", "가"),
                                    {k: v for k, v in reports(100).items() if k < (2018, 3)})]
    p = payload(companies)
    assert p["reported"] == "2018Q2"
    assert p["pending"] == [{"q": "2018Q3", "kind": "disclosure", "due": "2018-11-14", "filed": 0, "of": 1},
                            {"q": "2018Q4", "kind": "disclosure", "due": "2019-04-01", "filed": 0, "of": 1}]
    ex = p["exports"]["8486|USD"]
    assert ex["analog"]["band"] and ex["qtd"] is None
    p = build.build_payload(SECTOR, exports(n=34), {}, companies, "x")          # ends 201810
    assert p["pending"][-1] == {"q": "2018Q4", "kind": "progress", "months": 1}
    assert p["exports"]["8486|USD"]["qtd"]["q"] == "2018Q4"


def test_break_windows_leave_basket_and_correlations():
    co = Company("000001", "가", breaks=(("2017Q1", "2017Q4", "분할"),))
    p = payload([build.CompanyInput(co, reports(100))])
    q = p["companies"][0]["quarters"]
    assert q["2017Q2"]["excluded"] and q["2017Q2"]["revenue_yoy"] is None
    assert p["basket"]["2017Q2"]["matched"] == 0 and p["basket"]["2017Q2"]["revenue_yoy"] is None
    assert p["companies"][0]["breaks"] == [{"from": "2017Q1", "to": "2017Q4", "reason": "분할"}]


def test_quarter_filed_by_only_some_companies_feeds_no_statistics():
    early = dict(reports(100))
    early[(2018, 3)] = None
    late = build.CompanyInput(Company("000002", "나"), early)
    first = build.CompanyInput(Company("000001", "가"), reports(200))      # files 2018Q3 early
    p = build.build_payload(SECTOR, exports(), {}, [first, late], "x")
    assert p["reported"] == "2018Q2"
    assert p["basket"]["2018Q3"]["reported"] == 1                          # still drawn (dashed)
    assert p["pending"][0] == {"q": "2018Q3", "kind": "disclosure", "due": "2018-11-14", "filed": 1, "of": 2}
    ex = p["exports"]["8486|USD"]
    assert all(a["q"] <= "2018Q2" for a in ex["analog"]["quarters"])
    # span names the export quarter; the revenue quarter paired with it is span + lag
    from export_overlay.series import quarter_shift
    assert all(d["span"] is None or quarter_shift(d["span"][1], d["lag"]) <= "2018Q2" for d in ex["lags"]["basket"])


def test_no_company_data_marks_nothing_as_pending():
    p = build.build_payload(SECTOR, exports(), {}, [build.CompanyInput(Company("000001", "가"), error="x")], "x")
    assert p["reported"] is None and p["pending"] == []


def test_summary_for_the_overview():
    companies = [build.CompanyInput(Company("000001", "가"), {k: v for k, v in reports(100).items() if k < (2018, 3)})]
    sm = build.summary(build.build_payload(SECTOR, exports(), {}, companies, "x"))
    assert sm["key"] == "semi" and sm["companies"] == 1 and sm["currency"] == "USD" and sm["view"] == "8486 전체"
    assert sm["reported"] == "2018Q2" and sm["pending"]["q"] == "2018Q4"
    assert sm["revenue_yoy"] == round(((100 * 1.2 + 2) / (100 * 1.1 + 2) - 1) * 100, 1)
    assert len(sm["months"]) == len(sm["yoy3"]) == 24
    assert max(sm["basket_yoy"]) == "2018Q2"                               # nothing past the reported quarter
    assert sm["pending_qs"] == ["2018Q3", "2018Q4"]


def test_render_escapes_script_breakers():
    p = payload()
    p["warnings"].append("</script><script>alert(1)</script>")
    html = page.render(p)
    assert embedded(html)["warnings"][-1] == "</script><script>alert(1)</script>"
    assert "{{DATA}}" not in html and "{{TITLE}}" not in html and "반도체 장비 수출 × 장비사 실적" in html


def test_render_survives_html_comment_markers():
    p = payload()
    p["warnings"].append("<html><!-- maintenance --></html>")
    html = page.render(p)
    blob = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    assert "<" not in blob
    assert json.loads(blob)["warnings"][-1] == "<html><!-- maintenance --></html>"


def test_render_index():
    sm = build.summary(payload())
    sm["name"] = "</script>"
    html = page.render_index([sm], "2026-10-21 09:00")
    assert embedded(html)["sectors"][0]["name"] == "</script>" and "{{DATA}}" not in html


def test_sector_presets_reject_double_counting_and_stray_views():
    with pytest.raises(ValueError, match="두 번"):
        Sector(key="x", name="x", noun="x", hs=("85", "8504"), views=(View("a", "a", ("85",)),), companies=(), caveat="")
    with pytest.raises(ValueError, match="질의 밖"):
        Sector(key="x", name="x", noun="x", hs=("8504",), views=(View("a", "a", ("8535",)),), companies=(), caveat="")


class FakeCustoms:
    def __init__(self, error=None):
        self.error = error

    def item_exports(self, hs, start):
        if self.error:
            raise customs.CustomsError(self.error)
        return exports()


class FakeDart:
    stale: list = []

    def corp_codes(self):
        return {"000001": {"corp_code": "C1", "corp_name": "가"}, "000003": {"corp_code": "C3", "corp_name": "다"}}

    def company(self, corp_code):
        return {"acc_mt": "12" if corp_code == "C1" else "03"}

    def report(self, corp_code, year, quarter):
        return reports(100).get((year, quarter))


def run(tmp_path, sectors, dart_client=None, customs_client=None, logs=None):
    return main.run(tmp_path, customs_client or FakeCustoms(), dart_client or FakeDart(), {}, date(2026, 10, 21),
                    datetime(2026, 10, 21, 9), sectors=sectors, log=(logs.append if logs is not None else lambda m: None),
                    workers=2)


def test_run_writes_sector_pages_overview_and_excluded_companies(tmp_path):
    sector = Sector(key="semi", name="반도체 장비", noun="장비사", hs=("8486",), views=SECTOR.views, caveat="",
                    companies=(Company("000001", "가"), Company("000002", "나"), Company("000003", "다")))
    written = run(tmp_path, [sector])
    assert [p.name for p in written] == [main.INDEX_NAME, "semi.html", main.SCREENER_NAME]
    radar = embedded((tmp_path / main.SCREENER_NAME).read_text(encoding="utf-8"))
    assert [c["code"] for c in radar["companies"]] == ["000001"] and radar["evidence"]["priced"] == 0   # no price fetch given
    assert radar["sectors"][0]["key"] == "semi" and "spread" in radar["evidence"]
    data = embedded((tmp_path / "semi.html").read_text(encoding="utf-8"))
    assert "나: DART 고유번호 없음" in data["warnings"] and "다: 03월 결산(12월 결산만 비교)" in data["warnings"]
    assert any("USD/KRW" in w for w in data["warnings"])
    assert data["nav"] == [{"key": "semi", "name": "반도체 장비"}]
    overview = embedded((tmp_path / main.INDEX_NAME).read_text(encoding="utf-8"))
    assert [s["key"] for s in overview["sectors"]] == ["semi"]


def test_subset_run_keeps_other_sectors_in_menu_and_overview(tmp_path, monkeypatch):
    a = Sector(key="a", name="가 섹터", noun="회사", hs=("8486",), views=SECTOR.views, caveat="", companies=(Company("000001", "가"),))
    b = Sector(key="b", name="나 섹터", noun="회사", hs=("8486",), views=SECTOR.views, caveat="", companies=(Company("000001", "가"),))
    monkeypatch.setattr(main, "SECTORS", (a, b))
    run(tmp_path, [a, b])
    run(tmp_path, [b])                                                    # only b rebuilt
    assert [s["key"] for s in embedded((tmp_path / main.INDEX_NAME).read_text(encoding="utf-8"))["sectors"]] == ["a", "b"]
    assert [n["key"] for n in embedded((tmp_path / "b.html").read_text(encoding="utf-8"))["nav"]] == ["a", "b"]


def test_run_skips_a_sector_without_customs_data(tmp_path):
    logs = []
    assert run(tmp_path, [SECTOR], customs_client=FakeCustoms("HTTP 500"), logs=logs) == []
    assert not (tmp_path / "semi.html").exists() and "HTTP 500" in logs[0]


class FailingDart(FakeDart):
    def report(self, corp_code, year, quarter):
        if (year, quarter) == (2017, 2):
            raise main.dart.DartError("HTTP 500")
        return super().report(corp_code, year, quarter)


def test_one_failed_report_keeps_the_rest_and_is_listed(tmp_path):
    one = Sector(key="semi", name="x", noun="x", hs=("8486",), views=SECTOR.views, caveat="", companies=(Company("000001", "가"),))
    run(tmp_path, [one], dart_client=FailingDart())
    data = embedded((tmp_path / "semi.html").read_text(encoding="utf-8"))
    quarters = data["companies"][0]["quarters"]
    assert "2017Q1" in quarters and "2017Q2" not in quarters
    assert "가: 보고서 못 받음 2Q17" in data["warnings"]


def test_sector_page_is_not_overwritten_when_every_company_fails(tmp_path):
    (tmp_path / "semi.html").write_text("old", encoding="utf-8")
    none = Sector(key="semi", name="x", noun="x", hs=("8486",), views=SECTOR.views, caveat="", companies=(Company("000009", "없음"),))
    logs = []
    assert run(tmp_path, [none], logs=logs) == []
    assert (tmp_path / "semi.html").read_text(encoding="utf-8") == "old" and any("이전 화면" in m for m in logs)


def test_every_preset_is_valid_and_unique():
    from export_overlay import sectors
    keys = [s.key for s in sectors.SECTORS]
    assert len(keys) == len(set(keys)) and all(re.fullmatch(r"[a-z0-9-]+", k) for k in keys)
    for s in sectors.SECTORS:
        codes = [c.stock_code for c in s.companies]
        assert len(codes) == len(set(codes)) and all(re.fullmatch(r"\d{6}", c) for c in codes), s.key
        assert s.views and s.caveat, s.key
        for c in s.companies:
            for a, b, why in c.breaks:
                assert re.fullmatch(r"\d{4}Q[1-4]", a) and re.fullmatch(r"\d{4}Q[1-4]", b) and a <= b and why, (s.key, c.name)


def test_company_notes_reach_the_payload():
    p = payload([build.CompanyInput(Company("000001", "가", note="메모"), reports(100))])
    assert p["companies"][0]["note"] == "메모"


def test_view_breaks_leave_statistics_but_not_the_chart():
    sector = Sector(key="v", name="x", noun="x", hs=("8486",), caveat="", companies=(Company("000001", "가"),),
                    views=(View("8486", "전체", ("8486",), breaks=(("2017Q1", "2017Q4", "새 코드"),)), View("848620", "본체", ("848620",))))
    p = payload([build.CompanyInput(Company("000001", "가"), reports(100))], sector=sector)
    full, part = p["exports"]["8486|USD"], p["exports"]["848620|USD"]
    assert full["quarters"]["2017Q2"]["yoy"] is not None                       # still drawn
    n_full = next(d["n"] for d in full["lags"]["basket"] if d["lag"] == 0)
    n_part = next(d["n"] for d in part["lags"]["basket"] if d["lag"] == 0)
    assert n_part - n_full == 3                    # 2017Q1-Q3 left out (the fixture has no Q4 revenue anyway)
    assert p["codes"][0]["breaks"] == [{"from": "2017Q1", "to": "2017Q4", "reason": "새 코드"}]
    assert p["codes"][1]["inside"] is True


def test_absorbed_company_gives_a_pro_forma_line_flagged_in_the_payload():
    target = {k: v for k, v in reports(50).items() if k < (2018, 1)}
    acq = Company("000001", "가", absorbed=(("000002", "2018Q1"),))
    p = payload([build.CompanyInput(acq, reports(100)), build.CompanyInput(Company("000002", "나"), target)])
    q = p["companies"][0]["quarters"]["2018Q1"]
    assert q["proforma"] and not q["restated"]
    assert q["revenue_yoy"] == round((121 / (111 + 56) - 1) * 100, 1)        # base = own 2017Q1 + target's 2017Q1
