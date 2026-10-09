# -*- coding: utf-8 -*-
"""매매일지 — 저장·검증·변경·FIFO 장부·통계. 실제 개인/ 폴더는 건드리지 않고 tmp_path 만 쓴다."""
import os, sys, json, copy, datetime as dt, importlib.util as ilu
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("매매일지", os.path.join(BASE, "매매일지.py"))
MJ = ilu.module_from_spec(_sp); _sp.loader.exec_module(MJ)

TODAY = "2026-10-10"


def T(**kw):
    t = {"date": "2026-01-05", "code": "000010", "name": "가나전자", "side": "buy", "price": 10000, "qty": 10}
    t.update(kw)
    return t


def build(*payloads):
    """add 를 차례로 — created 를 1초씩 늘려 같은 날 거래의 순서를 고정한다."""
    data = MJ.empty()
    for i, p in enumerate(payloads):
        data = MJ.apply(data, "add", p, TODAY, "2026-10-10T09:%02d:%02d" % (i // 60, i % 60))
    return data


def prices(table):
    return lambda code: table.get(code, (None, None))


# ---------------------------------------------------------------- 경로
def test_default_path_and_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("ORBIT_TRADES_PATH", raising=False)
    p = MJ.default_path()
    assert p == os.path.join(BASE, "개인", "매매일지.json")
    want = str(tmp_path / "다른곳" / "일지.json")
    monkeypatch.setenv("ORBIT_TRADES_PATH", want)
    assert MJ.default_path() == os.path.abspath(want)
    # 경로 인자 없이 불러도 환경변수 경로를 쓴다
    MJ.save(None, build(T()))
    assert os.path.exists(want)
    assert len(MJ.load()["trades"]) == 1


# ---------------------------------------------------------------- 저장
def test_load_missing_is_empty_and_roundtrip(tmp_path):
    path = str(tmp_path / "일지.json")
    assert MJ.load(path) == {"ver": 1, "trades": []}
    assert not os.path.exists(path)                      # 읽기만으로 파일을 만들지 않는다
    data = build(T(reason="300억 눌림목에서 거래량 마름", setup="300억 눌림목"),
                 T(side="sell", date="2026-02-02", qty=4, price=11000, reason="목표 일부"))
    MJ.save(path, data, today=dt.date(2026, 10, 1))
    back = MJ.load(path)
    assert back == data
    with open(path, encoding="utf-8") as fh:
        assert "눌림목" in fh.read()                        # 한글을 \u 로 바꾸지 않는다
    assert not os.path.exists(tmp_path / "backup")        # 처음 저장은 덮어쓸 게 없어 백업도 없다


def test_backup_once_per_day(tmp_path):
    path = str(tmp_path / "일지.json")
    bdir = tmp_path / "backup"
    d1 = build(T(qty=1))
    d2 = build(T(qty=2))
    d3 = build(T(qty=3))
    MJ.save(path, d1, today=dt.date(2026, 10, 1))
    MJ.save(path, d2, today=dt.date(2026, 10, 1))
    MJ.save(path, d3, today=dt.date(2026, 10, 1))
    files = sorted(os.listdir(bdir))
    assert files == ["매매일지_20261001.json"]
    # 그날 첫 덮어쓰기 직전 상태(d1)가 남는다
    assert json.loads((bdir / files[0]).read_text(encoding="utf-8")) == d1
    MJ.save(path, d1, today=dt.date(2026, 10, 2))
    assert sorted(os.listdir(bdir)) == ["매매일지_20261001.json", "매매일지_20261002.json"]
    assert json.loads((bdir / "매매일지_20261002.json").read_text(encoding="utf-8")) == d3
    assert MJ.load(path) == d1
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]


def test_backup_prunes_to_30(tmp_path):
    path = str(tmp_path / "일지.json")
    bdir = tmp_path / "backup"
    bdir.mkdir()
    start = dt.date(2026, 1, 1)
    for i in range(35):
        (bdir / ("매매일지_%s.json" % (start + dt.timedelta(days=i)).strftime("%Y%m%d"))).write_text("{}", encoding="utf-8")
    (bdir / "메모.txt").write_text("남겨 둔다", encoding="utf-8")
    MJ.save(path, build(T()), today=dt.date(2026, 10, 9))
    MJ.save(path, build(T(qty=5)), today=dt.date(2026, 10, 10))
    names = sorted(n for n in os.listdir(bdir) if n.startswith("매매일지_"))
    assert len(names) == 30
    assert names[-1] == "매매일지_20261010.json"
    # 36개(옛 35 + 오늘) → 가장 오래된 6개가 지워진다
    assert names[0] == "매매일지_20260107.json"
    assert (bdir / "메모.txt").exists()


def test_corrupt_file_raises_and_is_untouched(tmp_path):
    path = tmp_path / "일지.json"
    bad = b'{"ver": 1, "trades": [ {"id": '
    path.write_bytes(bad)
    with pytest.raises(ValueError, match="깨져"):
        MJ.load(str(path))
    with pytest.raises(ValueError, match="깨져"):
        MJ.save(str(path), build(T()), today=dt.date(2026, 10, 1))
    assert path.read_bytes() == bad
    assert not (tmp_path / "backup").exists()
    assert os.listdir(tmp_path) == ["일지.json"]
    # 형식이 틀린 JSON 도 덮어쓰지 않는다
    path.write_text('{"ver": 1, "trades": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        MJ.save(str(path), build(T()))
    assert path.read_text(encoding="utf-8") == '{"ver": 1, "trades": {}}'


def test_save_failure_leaves_original(tmp_path, monkeypatch):
    path = str(tmp_path / "일지.json")
    d1 = build(T(qty=1))
    MJ.save(path, d1, today=dt.date(2026, 10, 1))
    MJ.save(path, d1, today=dt.date(2026, 10, 1))        # 오늘 백업은 이미 떠 둠 → 아래 실패는 본 파일 쓰기에서

    def boom(src, dst):
        raise OSError("디스크 끊김")
    monkeypatch.setattr(MJ, "_replace", boom)
    with pytest.raises(OSError):
        MJ.save(path, build(T(qty=2)), today=dt.date(2026, 10, 1))
    assert MJ.load(path) == d1
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    # 백업을 뜨다 실패해도 본 파일은 그대로, 임시 파일은 남지 않는다
    with pytest.raises(OSError):
        MJ.save(path, build(T(qty=3)), today=dt.date(2026, 10, 2))
    assert MJ.load(path) == d1
    assert sorted(os.listdir(tmp_path / "backup")) == ["매매일지_20261001.json"]
    # NaN 같은 값은 직렬화 단계에서 막혀 디스크를 건드리지 않는다
    monkeypatch.undo()
    bad = build(T(qty=1))
    bad["trades"][0]["price"] = float("nan")
    with pytest.raises(ValueError):
        MJ.save(path, bad)
    assert MJ.load(path) == d1


# ---------------------------------------------------------------- 검증
def test_validate_clean_and_defaults():
    c, errs = MJ.validate(T(code=" a00001 ", source="", horizon=None, stop="", fee=None,
                            junk="버린다", name="  가나전자 "), TODAY)
    assert errs == []
    assert c["code"] == "A00001" and c["name"] == "가나전자"
    assert c["fee"] == 0.0 and c["source"] == "etc" and c["horizon"] == ""
    assert c["stop"] is None and c["target"] is None
    assert c["price"] == 10000.0 and isinstance(c["qty"], int)
    assert "junk" not in c and c["memo"] == "" and c["reason"] == ""


@pytest.mark.parametrize("patch, word", [
    ({"code": "5930"}, "종목코드"),
    ({"code": "00593@"}, "종목코드"),
    ({"code": 5930}, "종목코드"),
    ({"date": "2026-10-11"}, "오늘"),
    ({"date": "2026-02-30"}, "없는 날짜"),
    ({"date": "2026/01/05"}, "날짜"),
    ({"qty": 1.5}, "수량"),
    ({"qty": 10.0}, "수량"),
    ({"qty": "10"}, "수량"),
    ({"qty": True}, "수량"),
    ({"qty": 0}, "수량"),
    ({"qty": 10 ** 9 + 1}, "수량"),
    ({"price": -1}, "가격"),
    ({"price": 0}, "가격"),
    ({"price": float("nan")}, "가격"),
    ({"price": 2e9}, "가격"),
    ({"price": "10000"}, "가격"),
    ({"fee": -1}, "수수료"),
    ({"stop": -5}, "손절가"),
    ({"target": 0}, "목표가"),
    ({"side": "hold"}, "매수/매도"),
    ({"source": "naver"}, "출처"),
    ({"horizon": "mid"}, "기간"),
    ({"name": "가" * 41}, "종목명"),
    ({"setup": "가" * 61}, "셋업"),
    ({"reason": "가" * 1001}, "근거"),
    ({"thesis_break": "가" * 1001}, "생각을 바꿀 조건"),
    ({"memo": "가" * 2001}, "메모"),
    ({"memo": 123}, "메모"),
])
def test_validate_errors(patch, word):
    c, errs = MJ.validate(T(**patch), TODAY)
    assert len(errs) == 1 and word in errs[0], errs


def test_validate_text_limits_inclusive():
    c, errs = MJ.validate(T(setup="가" * 60, reason="가" * 1000, memo="가" * 2000, name="가" * 40), TODAY)
    assert errs == []
    assert MJ.validate("문자열", TODAY)[1]


# ---------------------------------------------------------------- 변경
def test_apply_add_update_delete():
    d0 = MJ.empty()
    d1 = MJ.apply(d0, "add", T(memo="첫 매수"), TODAY, "2026-10-10T09:00:00")
    assert d0 == {"ver": 1, "trades": []}                  # 입력은 그대로
    t = d1["trades"][0]
    assert len(t["id"]) == 32 and int(t["id"], 16) >= 0
    assert t["created"] == t["updated"] == "2026-10-10T09:00:00"
    assert list(t) == list(MJ.ORDER)

    snap = copy.deepcopy(d1)
    d2 = MJ.apply(d1, "update", {"id": t["id"], "memo": "고침", "stop": 9000, "created": "무시"},
                  TODAY, "2026-10-10T10:00:00")
    assert d1 == snap
    u = d2["trades"][0]
    assert u["memo"] == "고침" and u["stop"] == 9000.0
    assert u["created"] == "2026-10-10T09:00:00" and u["updated"] == "2026-10-10T10:00:00"
    assert u["price"] == 10000.0 and u["id"] == t["id"]

    with pytest.raises(ValueError, match="가격"):
        MJ.apply(d2, "update", {"id": t["id"], "price": -3}, TODAY, "x")
    with pytest.raises(ValueError, match="없다"):
        MJ.apply(d2, "update", {"id": "없는id", "memo": "x"}, TODAY, "x")
    with pytest.raises(ValueError, match="종목코드"):
        MJ.apply(d2, "add", T(code="12"), TODAY, "x")
    with pytest.raises(ValueError, match="모르는 동작"):
        MJ.apply(d2, "merge", {}, TODAY, "x")

    d3 = MJ.apply(d2, "delete", {"id": t["id"]}, TODAY, "x")
    assert d3["trades"] == [] and len(d2["trades"]) == 1


def test_oversell_rejected():
    data = build(T(qty=100))
    with pytest.raises(ValueError, match="보유 수량보다 많이 판다"):
        MJ.apply(data, "add", T(side="sell", date="2026-02-01", qty=101), TODAY, "z")
    # 매수보다 이른 날 매도
    with pytest.raises(ValueError, match="보유 수량보다 많이 판다"):
        MJ.apply(data, "add", T(side="sell", date="2026-01-04", qty=1), TODAY, "z")
    # 다른 종목은 보유가 없다
    with pytest.raises(ValueError, match="보유 수량보다 많이 판다"):
        MJ.apply(data, "add", T(side="sell", code="000020", date="2026-02-01", qty=1), TODAY, "z")
    ok = MJ.apply(data, "add", T(side="sell", date="2026-02-01", qty=100), TODAY, "z")
    assert len(ok["trades"]) == 2


def test_oversell_when_update_moves_buy_after_sell():
    data = build(T(qty=100), T(side="sell", date="2026-02-01", qty=50))
    buy, sell = data["trades"]
    snap = copy.deepcopy(data)
    with pytest.raises(ValueError, match="보유 수량보다 많이 판다"):
        MJ.apply(data, "update", {"id": buy["id"], "date": "2026-03-01"}, TODAY, "z")
    with pytest.raises(ValueError, match="보유 수량보다 많이 판다"):
        MJ.apply(data, "update", {"id": sell["id"], "qty": 150}, TODAY, "z")
    with pytest.raises(ValueError, match="보유 수량보다 많이 판다"):
        MJ.apply(data, "update", {"id": buy["id"], "qty": 40}, TODAY, "z")
    with pytest.raises(ValueError, match="보유 수량보다 많이 판다"):
        MJ.apply(data, "delete", {"id": buy["id"]}, TODAY, "z")
    assert data == snap
    # 매도를 지우는 건 괜찮다
    assert len(MJ.apply(data, "delete", {"id": sell["id"]}, TODAY, "z")["trades"]) == 1


def test_same_day_order_follows_created():
    # 같은 날 사고 판 단타 — 입력 순서(created)대로 다시 돌린다
    data = build(T(date="2026-03-03", qty=10), T(side="sell", date="2026-03-03", qty=10, price=10500))
    b = MJ.book(data["trades"], prices({}), today=TODAY)
    assert b["totals"]["n_closed"] == 1 and b["closed"][0]["days"] == 0


# ---------------------------------------------------------------- 장부
def test_fifo_partial_sells_across_two_lots_with_fees():
    data = build(
        T(date="2026-01-05", qty=100, price=10000, fee=1000, source="val", setup="300억 눌림목",
          horizon="short", reason="A 근거", thesis_break="A 깨짐", stop=9000),
        T(date="2026-02-02", qty=50, price=12000, fee=600, source="tech", setup="돌파",
          horizon="long", reason="B 근거", thesis_break="B 깨짐", target=15000),
        T(side="sell", date="2026-03-02", qty=120, price=13000, fee=2400, reason="목표 도달", memo="분할"),
    )
    a, b_, s = data["trades"]
    bk = MJ.book(data["trades"], prices({"000010": (11000, "20261008")}), today=TODAY)

    c1, c2 = bk["closed"]
    assert (c1["buy_id"], c1["sell_id"], c1["qty"]) == (a["id"], s["id"], 100)
    assert c1["cost"] == 1001000 and c1["proceeds"] == 1298000 and c1["pnl"] == 297000
    assert c1["ret"] == 29.67 and c1["days"] == 56
    assert c1["source"] == "val" and c1["source_label"] == "저평가" and c1["setup"] == "300억 눌림목"
    assert c1["reason"] == "A 근거" and c1["thesis_break"] == "A 깨짐"
    assert c1["sell_reason"] == "목표 도달" and c1["sell_memo"] == "분할"
    assert c1["buy_date"] == "2026-01-05" and c1["sell_date"] == "2026-03-02"
    assert c1["buy_price"] == 10000.0 and c1["sell_price"] == 13000.0
    assert c1["bench"] is None and c1["excess"] is None

    assert (c2["buy_id"], c2["qty"]) == (b_["id"], 20)
    assert c2["cost"] == 240240 and c2["proceeds"] == 259600 and c2["pnl"] == 19360
    assert c2["ret"] == 8.06 and c2["days"] == 28 and c2["source"] == "tech"

    (o,) = bk["open"]
    assert o["lot_id"] == b_["id"] and o["qty"] == 30 and o["price"] == 12000.0
    assert o["cost"] == 360360 and o["last"] == 11000.0 and o["last_date"] == "2026-10-08"
    assert o["value"] == 330000 and o["pnl"] == -30360 and o["ret"] == -8.42
    assert o["days"] == (dt.date(2026, 10, 10) - dt.date(2026, 2, 2)).days
    assert o["setup"] == "돌파" and o["horizon"] == "long" and o["target"] == 15000.0 and o["stop"] is None
    assert o["reason"] == "B 근거" and o["thesis_break"] == "B 깨짐"

    t = bk["totals"]
    assert t == {"cost": 360360, "priced_cost": 360360, "value": 330000, "unreal": -30360, "unreal_pct": -8.42,
                 "realized": 316360, "n_open": 1, "n_closed": 2, "n_no_price": 0,
                 "price_asof": "2026-10-08"}
    assert bk["warnings"] == []


def test_open_lot_flags():
    data = build(
        T(code="000001", date="2026-09-01", stop=9000, horizon="short"),
        T(code="000002", date="2026-09-01", stop=10000, horizon="long"),
        T(code="000003", date="2026-06-01", horizon="short"),
        T(code="000004", date="2025-08-01", horizon="long"),
        T(code="000005", date="2026-09-01", stop=9000, horizon="short"),
        T(code="000006", date="2026-09-01", stop=10000),
    )
    table = {"000001": (8900, "20261008"), "000002": (10200, "20261009"),
             "000003": (12000, "20261009"), "000004": (10000, "20261009"),
             "000006": (10400, "20261009")}
    bk = MJ.book(data["trades"], prices(table), today=TODAY)
    by = {o["code"]: o for o in bk["open"]}
    assert by["000001"]["stop_broken"] and not by["000001"]["near_stop"]
    assert by["000001"]["flags"] == ["stop_broken"] and by["000001"]["days"] == 39
    assert by["000002"]["near_stop"] and not by["000002"]["stop_broken"]
    assert by["000002"]["flags"] == ["near_stop"]
    assert by["000003"]["over_horizon"] and by["000003"]["days"] == 131
    assert by["000004"]["over_horizon"] and by["000004"]["days"] == 435
    assert by["000006"]["flags"] == []                          # 손절가 위 4% — 근접 아님
    nop = by["000005"]
    assert nop["no_price"] and nop["flags"] == ["no_price"]
    assert nop["last"] is None and nop["value"] is None and nop["pnl"] is None and nop["ret"] is None
    assert not nop["stop_broken"] and not nop["near_stop"]
    t = bk["totals"]
    assert t["n_open"] == 6 and t["n_no_price"] == 1 and t["price_asof"] == "2026-10-08"
    assert t["cost"] == 600000 and t["value"] == 8900 * 10 + 10200 * 10 + 12000 * 10 + 10000 * 10 + 10400 * 10
    assert t["unreal"] == t["value"] - 500000


def test_price_of_errors_become_no_price():
    def bad(code):
        raise RuntimeError("시세 서버 꺼짐")
    bk = MJ.book(build(T())["trades"], bad, today=TODAY)
    assert bk["open"][0]["no_price"]
    assert bk["totals"]["value"] is None and bk["totals"]["unreal_pct"] is None


def _four_round_trips():
    return build(
        T(code="000011", date="2026-01-05", price=100, qty=10, source="val", horizon="short"),
        T(code="000011", date="2026-01-15", price=120, qty=10, side="sell"),
        T(code="000012", date="2026-02-02", price=100, qty=10, source="val", horizon="short"),
        T(code="000012", date="2026-02-22", price=90, qty=10, side="sell"),
        T(code="000013", date="2026-03-02", price=100, qty=10, source="tech", horizon="long"),
        T(code="000013", date="2026-04-01", price=130, qty=10, side="sell"),
        T(code="000014", date="2026-05-04", price=100, qty=20, source="tech", horizon="long"),
        T(code="000014", date="2026-06-13", price=95, qty=20, side="sell"),
    )


def test_stats_math():
    calls = []

    def bench(d0, d1):
        calls.append((d0, d1))
        return 5.0
    bk = MJ.book(_four_round_trips()["trades"], prices({}), bench_of=bench, today=TODAY)
    assert ("20260105", "20260115") in calls
    assert [c["ret"] for c in bk["closed"]] == [20.0, -10.0, 30.0, -5.0]
    assert [c["excess"] for c in bk["closed"]] == [15.0, -15.0, 25.0, -10.0]
    s = bk["stats"]["all"]
    assert s == {"n": 4, "wins": 2, "losses": 2, "win_rate": 50.0, "avg_win": 25.0, "avg_loss": -7.5,
                 "payoff": 3.33, "profit_factor": 2.5, "pnl": 300, "avg_days": 25.0,
                 "ex_median": 2.5, "beat": 50.0}

    src = bk["stats"]["by_source"]
    assert [(g["key"], g["label"]) for g in src] == [("val", "저평가"), ("tech", "차트 발굴")]
    val, tech = src
    assert (val["n"], val["win_rate"], val["avg_win"], val["avg_loss"], val["payoff"],
            val["profit_factor"], val["pnl"]) == (2, 50.0, 20.0, -10.0, 2.0, 2.0, 100)
    assert (tech["payoff"], tech["profit_factor"], tech["pnl"], tech["ex_median"], tech["avg_days"]) == \
        (6.0, 3.0, 200, 7.5, 35.0)

    hz = bk["stats"]["by_horizon"]
    assert [g["key"] for g in hz] == ["short", "long"]
    assert hz[0]["label"] == MJ.HORIZONS["short"]
    assert hz[0]["pnl"] == 100 and hz[1]["pnl"] == 200 and hz[1]["avg_win"] == 30.0
    assert bk["totals"]["realized"] == 300 and bk["totals"]["n_open"] == 0
    assert bk["totals"]["value"] == 0 and bk["totals"]["unreal_pct"] is None


def test_stats_undefined_are_none():
    empty = MJ.book([], prices({}), today=TODAY)
    s = empty["stats"]["all"]
    assert s["n"] == 0 and s["win_rate"] is None and s["avg_days"] is None and s["pnl"] == 0
    assert empty["stats"]["by_source"] == [] and empty["totals"]["price_asof"] is None
    # 이기기만 했으면 손실 쪽은 정의가 안 된다
    data = build(T(price=100), T(side="sell", date="2026-02-01", price=110))
    s = MJ.book(data["trades"], prices({}), today=TODAY)["stats"]["all"]
    assert s["win_rate"] == 100.0 and s["avg_loss"] is None and s["payoff"] is None
    assert s["profit_factor"] is None and s["ex_median"] is None and s["beat"] is None


def test_book_output_is_json_safe():
    data = _four_round_trips()
    data = MJ.apply(data, "add", T(code="000099", date="2026-09-01", stop=90, price=100, qty=3, fee=1),
                    TODAY, "2026-10-10T11:00:00")
    data = MJ.apply(data, "add", T(code="000098", date="2026-09-01"), TODAY, "2026-10-10T11:00:01")
    bk = MJ.book(data["trades"], prices({"000099": (91, "20261009")}),
                 bench_of=lambda d0, d1: float("nan") if d0 > "20260900" else 1.25, today=TODAY)
    txt = json.dumps(bk, ensure_ascii=False, allow_nan=False)
    assert json.loads(txt) == bk
    assert set(bk) >= {"open", "closed", "stats", "totals"}


def test_book_skips_unreadable_and_oversold_rows():
    rows = build(T(qty=5))["trades"]
    rows.append({"id": "x1", "date": "엉망", "code": "000010", "side": "buy", "price": 1, "qty": 1})
    rows.append({"id": "x2", "date": "2026-03-01", "code": "000010", "side": "sell", "price": 11000.0,
                 "qty": 8, "fee": 0, "created": "2026-10-10T12:00:00"})
    bk = MJ.book(rows, prices({}), today=TODAY)
    assert bk["totals"]["n_closed"] == 1 and bk["closed"][0]["qty"] == 5
    assert len(bk["warnings"]) == 2


def test_meta():
    assert MJ.sources_meta()[0] == {"key": "val", "label": "저평가"}
    assert [m["key"] for m in MJ.sources_meta()] == [k for k, _ in MJ.SOURCES]
    assert MJ.horizons_meta() == [{"key": "short", "label": "단기 (20~60거래일 · 손절)"},
                                  {"key": "long", "label": "장기 (~12개월)"}]


def test_totals_priced_cost_matches_value_when_a_price_is_missing():
    data = build(T(code="000001", qty=10, price=10000), T(code="000002", qty=10, price=10000))
    px = {"000001": (10000.0, "20261008")}
    bk = MJ.book(data["trades"], lambda c: px.get(c, (None, None)), today="2026-10-10")
    t = bk["totals"]
    assert t["cost"] == 200000 and t["priced_cost"] == 100000 and t["value"] == 100000 and t["unreal"] == 0
    assert t["n_no_price"] == 1


def test_tiny_price_rejected_and_huge_close_ignored():
    c, errs = MJ.validate(T(price=5e-324), "2026-10-10")
    assert any("너무 작다" in e for e in errs)
    data = build(T(code="000001", qty=10, price=10000))
    bk = MJ.book(data["trades"], lambda c: (1e308, "20261008"), today="2026-10-10")
    assert bk["open"][0]["no_price"] is True
    json.dumps(bk, allow_nan=False)


def test_broken_surrogate_text_rejected():
    c, errs = MJ.validate(T(memo="\ud800"), "2026-10-10")
    assert any("깨진 글자" in e for e in errs)


def test_replay_order_uses_real_dates():
    rows = [{"id": "b1", "date": "20260105", "side": "buy", "qty": 10, "price": 100.0, "code": "000010", "created": "1"},
            {"id": "s1", "date": "2026-03-01", "side": "sell", "qty": 10, "price": 150.0, "code": "000010", "created": "2"}]
    bk = MJ.book(rows, lambda c: (None, None), today="2026-10-10")
    assert len(bk["closed"]) == 1 and bk["warnings"] == []
    MJ._feasible(rows)                                    # 날짜 형식이 섞여도 순서가 맞다
    bad = rows + [{"id": "x", "date": "2026-01-05", "code": "000010", "side": "buy", "price": 1.0, "qty": "10"}]
    MJ._feasible(bad)                                     # 손으로 고친 이상한 행은 건너뛴다 (TypeError 아님)
