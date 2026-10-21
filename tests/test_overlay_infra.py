import json
from datetime import date

import pytest

from export_overlay import config, customs, fx
from export_overlay.cache import JsonCache

XML_OK = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><items>
<item><year>총계</year><hsCd>-</hsCd><statCd>-</statCd><expDlr>350</expDlr><expWgt>9</expWgt></item>
<item><year>2026.08</year><hsCd>848620</hsCd><statCd>CN</statCd><expDlr>100</expDlr><expWgt>1</expWgt></item>
<item><year>2026.08</year><hsCd>848620</hsCd><statCd>TW</statCd><expDlr>50</expDlr><expWgt>1</expWgt></item>
<item><year>2026.08</year><hsCd>848690</hsCd><statCd>CN</statCd><expDlr>120</expDlr><expWgt>1</expWgt></item>
<item><year>2026.09</year><hsCd>848620</hsCd><statCd>CN</statCd><expDlr>80</expDlr><expWgt>1</expWgt></item>
</items></body></response>"""

XML_GATEWAY = """<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>
<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode>
</cmmMsgHeader></OpenAPI_ServiceResponse>"""


def test_cache_respects_ttl(tmp_path):
    now = [1_000_000.0]
    cache = JsonCache(tmp_path, clock=lambda: now[0])
    cache.put("a b/c", {"x": 1})
    now[0] =cache.path("a b/c").stat().st_mtime + 30
    assert cache.get("a b/c", ttl=60) == {"x": 1}
    now[0] += 60
    assert cache.get("a b/c", ttl=60) is None
    assert cache.get("missing", ttl=60) is None


def test_parse_reads_items_and_numbers():
    rows = customs.parse(XML_OK)
    assert len(rows) == 5
    assert rows[1] == {"year": "2026.08", "hsCd": "848620", "statCd": "CN", "expDlr": 100.0, "expWgt": 1.0}


def test_parse_raises_on_gateway_error():
    with pytest.raises(customs.CustomsError, match="게이트웨이"):
        customs.parse(XML_GATEWAY)


def test_aggregate_sums_countries_and_checks_total():
    months, countries = customs.aggregate(customs.parse(XML_OK))
    assert months == {"202608": {"848620": 150.0, "848690": 120.0}, "202609": {"848620": 80.0}}
    assert countries["202608"]["848620"] == {"CN": 100.0, "TW": 50.0}
    bad = customs.parse(XML_OK.replace("<expDlr>350</expDlr>", "<expDlr>360</expDlr>"))
    with pytest.raises(customs.CustomsError, match="행 합 350"):
        customs.aggregate(bad)
    no_total = [r for r in customs.parse(XML_OK) if r["year"] != "총계"]
    with pytest.raises(customs.CustomsError, match="총계"):
        customs.aggregate(no_total)
    assert customs.aggregate([]) == ({}, {})                 # nothing published yet: not an error, not zeros


def test_parse_rejects_non_00_result_codes():
    xml = XML_OK.replace("<resultCode>00</resultCode>", "<resultCode>99</resultCode>")
    with pytest.raises(customs.CustomsError, match="99"):
        customs.parse(xml)


def test_year_windows_and_last_closed_month():
    assert customs.year_windows("201503", "201702") == [("201503", "201512"), ("201601", "201612"),
                                                         ("201701", "201702")]
    assert customs.last_closed_month(date(2026, 10, 21)) == "202609"
    assert customs.last_closed_month(date(2026, 1, 5)) == "202512"


def test_client_splits_by_year_caches_and_hides_key(tmp_path):
    calls = []

    def fake_get(url, params):
        calls.append(dict(params))
        return XML_OK

    client = customs.CustomsClient("SECRET", JsonCache(tmp_path), get=fake_get, today=date(2026, 10, 21))
    got = client.item_exports("8486", "202511")
    assert [(c["strtYymm"], c["endYymm"]) for c in calls] == [("202511", "202512"), ("202601", "202609")]
    assert got.months["202608"] == {"848620": 150.0, "848690": 120.0}
    client.item_exports("8486", "202511")
    assert len(calls) == 2                                   # second run is served from cache
    assert all("SECRET" not in p.read_text(encoding="utf-8") and "SECRET" not in p.name
               for p in tmp_path.iterdir())


def test_recent_windows_expire_in_hours_older_ones_in_a_month(tmp_path):
    now = [0.0]
    cache = JsonCache(tmp_path, clock=lambda: now[0])
    calls = []
    client = customs.CustomsClient("K", cache, get=lambda u, p: calls.append(p) or XML_OK, today=date(2027, 1, 10))
    client.item_exports("8486", "202401")                    # windows 2024, 2025, 2026(through 202612)
    now[0] = max(f.stat().st_mtime for f in tmp_path.iterdir()) + 13 * 3600
    calls.clear()
    client.item_exports("8486", "202401")
    # 2025 ends 13 months before 202612 and 2026 is current: both refetched; 2024 stays cached.
    assert sorted(c["strtYymm"] for c in calls) == ["202501", "202601"]


def test_failed_total_check_is_not_cached(tmp_path):
    bad = XML_OK.replace("<expDlr>350</expDlr>", "<expDlr>999</expDlr>")
    client = customs.CustomsClient("K", JsonCache(tmp_path), get=lambda u, p: bad, today=date(2026, 10, 21))
    with pytest.raises(customs.CustomsError, match="8486 202601-202609"):
        client.item_exports("8486", "202601")
    assert list(tmp_path.iterdir()) == []


def test_api_key_lookup_order(tmp_path):
    keys = tmp_path / "keys.env"
    keys.write_text("# comment\nDART_API_KEY='from-file'\n", encoding="utf-8")
    local = tmp_path / ".env"
    local.write_text(f"KEY_FILES={tmp_path / 'nope.env'};{keys}\n", encoding="utf-8")
    assert config.api_key("DART_API_KEY", environ={}, local_env=local) == "from-file"
    assert config.api_key("DART_API_KEY", environ={"DART_API_KEY": "env"}, local_env=local) == "env"
    with pytest.raises(config.KeyMissing):
        config.api_key("DATA_GO_KR_KEY", environ={}, local_env=local)


def test_fx_monthly_average_skips_thin_months_and_bad_ticks():
    rows = [(date(2026, 8, d), 1400.0 + d) for d in range(1, 8)] + [(date(2026, 8, 9), 0.5)]
    rows += [(date(2026, 9, 1), 1500.0)]
    assert fx.monthly_average(date(2026, 8, 1), date(2026, 9, 30), fetch=lambda *a: rows) == {"202608": 1404.0}

    def boom(*a):
        raise RuntimeError("network")

    assert fx.monthly_average(date(2026, 8, 1), date(2026, 9, 30), fetch=boom) == {}


def test_several_query_codes_merge_and_windows_cache_aggregated(tmp_path):
    xml_b = XML_OK.replace("848620", "850760").replace("848690", "850790")
    calls = []

    def fake_get(url, params):
        calls.append(params["hsSgn"])
        return XML_OK if params["hsSgn"] == "8486" else xml_b

    client = customs.CustomsClient("K", JsonCache(tmp_path), get=fake_get, today=date(2026, 10, 21))
    got = client.item_exports(("8486", "8507"), "202601")
    assert got.months["202608"] == {"848620": 150.0, "848690": 120.0, "850760": 150.0, "850790": 120.0}
    assert got.countries["202608"]["850760"] == {"CN": 100.0, "TW": 50.0}
    stored = json.loads(next(tmp_path.glob("customs_agg_8486*")).read_text(encoding="utf-8"))
    assert set(stored) == {"months", "countries"}                         # rows are not kept
    client.item_exports(("8486", "8507"), "202601")
    assert calls == ["8486", "8507"]


def test_chapter_query_keys_stay_four_digit():
    xml = XML_OK.replace("848620", "8901").replace("848690", "8905")
    months, _ = customs.aggregate(customs.parse(xml))
    assert months["202608"] == {"8901": 150.0, "8905": 120.0}


def test_relative_key_files_are_read_from_the_env_folder(tmp_path):
    repo = tmp_path / "주식3 max20"
    repo.mkdir()
    (tmp_path / "기업추적").mkdir()
    (tmp_path / "기업추적" / ".env").write_text("DATA_GO_KR_KEY=k1\n", encoding="utf-8")
    (repo / ".env").write_text(r"KEY_FILES=..\기업추적\.env;../없음/.env", encoding="utf-8")
    assert config.api_key("DATA_GO_KR_KEY", environ={}, local_env=repo / ".env") == "k1"
