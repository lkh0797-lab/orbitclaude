# -*- coding: utf-8 -*-
"""도구/가속기준_백테스트.py --from-cache 의 순수 부분 — 패널 행(filed0 · lag · dG2/dG4) · 표본 규칙 · 보고서 구간 · 헛신호 · bt_accel.json 키.
주가 세계(억울_백테스트 W)는 가짜로 — 서버 · 전 종목 주가를 올리지 않는다."""
import os, sys, json, datetime as dt, importlib.util as ilu
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("가속기준_백테스트_시험", os.path.join(BASE, "도구", "가속기준_백테스트.py"))
BT = ilu.module_from_spec(_sp); _sp.loader.exec_module(BT)


def _shift(d, days):
    return (dt.datetime.strptime(d, "%Y%m%d") + dt.timedelta(days=days)).strftime("%Y%m%d")


class FakeW:
    """종목마다 [첫 날, 마지막 날] 사이 매일 시세가 있고 값 = 100 + (2025-01-01 부터 날 수). 전 종목 중앙값은 0(초과수익 = 수익률)."""
    SPLIT = "20200101"

    def __init__(self, span):
        self.span = span                                   # code → (첫 날, 마지막 날)
        self.PX = {c: ([a, b], [0, 0]) for c, (a, b) in span.items()}

    shift = staticmethod(_shift)

    def _p(self, d):
        return 100 + (dt.datetime.strptime(d, "%Y%m%d") - dt.datetime(2025, 1, 1)).days

    def next_day(self, code, d):
        a, b = self.span[code]
        n = _shift(d, 1)
        return n if a <= d and n <= b else None

    def ret(self, code, d0, d1):
        a, b = self.span[code]
        if not (a <= d0 <= b):
            return None
        return (self._p(min(d1, b)) / self._p(d0) - 1) * 100

    def grp_ret(self, g, d0, d1):
        return 0.0

    def boot(self, rows, fn, n=500):
        v = fn(rows)
        return v, v

    def ic_stats(self, rows, fx, y, overlap):
        return None


# ---------------------------------------------------------------- 패널 행
def _pts():
    """TTM 매출 — n 109 는 점이 아예 없다(키로 찾아야 맞는다. 순번으로 찾으면 110 을 109 로 읽는다)."""
    ttm = {100: 100, 101: 100, 102: 100, 103: 100, 104: 110, 105: 120, 106: 130, 107: 140, 108: 121, 110: 156, 111: 168}
    pts = [{"n": n, "매출_TTM": v, "가속B": None, "품질": []} for n, v in sorted(ttm.items())]
    by = {p["n"]: p for p in pts}
    by[104].update({"가속B": 4.0, "속도": 10.0, "국면": "확장 가속", "변곡": "▲", "B기준일": "20250515"})
    by[105].update({"가속B": 1.0, "속도": 12.0, "국면": "확장 유지", "B기준일": "20250901"})
    by[106].update({"가속B": -5.0, "속도": 8.0, "국면": "둔화", "변곡": "▼", "B기준일": "20260301", "품질": ["amended"]})
    by[108].update({"가속B": 2.0, "속도": 1.0, "국면": "정체", "B기준일": "20260515", "품질": ["asfiled"]})
    by[110].update({"가속B": 3.5, "속도": 5.0, "국면": "확장 가속", "기준일": "20261114"})         # B기준일 없음 → 기준일
    by[111].update({"가속B": 0.5, "속도": 5.0, "국면": "확장 유지", "B기준일": "20270301", "품질": ["mix"]})
    return pts


FILED = {104: "20250515", 105: "20250814", 106: "20251114", 108: "20260515", 111: "20270301"}


def test_point_rows_dg_by_quarter_key_and_lag():
    rows = {r["n"]: r for r in BT.point_rows(_pts(), FILED)}
    assert sorted(rows) == [104, 105, 106, 108, 110, 111]                 # 가속B 없는 점(100~103 · 107)은 뺀다
    r = rows[104]
    assert abs(r["g"] - 10) < 1e-9 and abs(r["dG2"] - 20) < 1e-9 and abs(r["dG4"] - 0) < 1e-9     # g(106)=30 · g(108)=10
    assert rows[105]["dG4"] is None                                       # g(109) — 점 없음
    assert abs(rows[106]["dG2"] - (-20)) < 1e-9 and abs(rows[106]["dG4"] - (-10)) < 1e-9          # g(108)=10 · g(110)=156/130−1=20
    assert r["filed0"] == "20250515" and r["lag"] == 0 and r["date"] == "20250515" and r["t"] == "20250515"
    assert rows[105]["lag"] == 18                                         # 08-14 → 09-01
    assert rows[106]["lag"] == 107 and rows[106]["turn"] == "▼"
    assert rows[110]["date"] == "20261114" and rows[110]["filed0"] is None and rows[110]["lag"] is None
    assert rows[108]["asfiled"] and rows[111]["asfiled"] and not r["asfiled"]
    assert r["phase"] == "확장 가속" and r["B"] == 4.0 and r["s"] == 10.0


def test_in_sample_excludes_asfiled_late_and_unknown_filing():
    rows = {r["n"]: r for r in BT.point_rows(_pts(), FILED)}
    assert [n for n in sorted(rows) if BT.in_sample(rows[n])] == [104, 105]
    edge = dict(rows[104], lag=BT.LAG_MAX)
    assert BT.in_sample(edge) and not BT.in_sample(dict(edge, lag=BT.LAG_MAX + 1))


# ---------------------------------------------------------------- 보고서 구간
def test_periods_pairs_done_and_live():
    W = FakeW({"A": ("20250101", "20251120")})
    filed = {8100: "20250515", 8101: "20250814", 8102: "20251114"}
    ps = BT.periods(W, "A", filed, today="20251120")
    assert [(p["d"], p["d2"], p["state"]) for p in ps] == [("20250515", "20250814", "done"), ("20250814", "20251114", "done"),
                                                          ("20251114", None, "진행 중")]
    p0 = ps[0]
    assert abs(p0["ex"] - (W._p("20250815") / W._p("20250516") - 1) * 100) < 1e-9 and p0["n"] == 8100
    assert abs(ps[2]["ex"] - (W._p("20251120") / W._p("20251115") - 1) * 100) < 1e-9      # 진행 중 — 오늘(마지막 시세)까지


def test_periods_next_report_without_price_yet_is_live_but_old_gaps_are_done():
    W = FakeW({"A": ("20250601", "20251120")})
    filed = {8099: "20250315", 8100: "20250515", 8101: "20250814", 8102: "20251120"}
    ps = {p["d"]: p for p in BT.periods(W, "A", filed, today="20251121")}
    assert ps["20250315"]["state"] == "done" and ps["20250315"]["ex"] is None        # 상장 전 — 못 잰 지난 구간
    assert ps["20250515"]["ex"] is None                                               # 들어갈 날 시세 없음
    assert ps["20250814"]["state"] == "진행 중"                                       # 다음 보고서(11-20) 다음 거래일 시세가 아직 없다
    assert ps["20251120"]["state"] == "진행 중" and ps["20251120"]["ex"] is None


# ---------------------------------------------------------------- 헛신호 · bt_accel.json
def _row(code, n, turn=None, ex12=1.0, asfiled=False, lag=0, phase="확장 가속", order=False):
    return {"code": code, "n": n, "t": "20230115", "date": "20230110", "turn": turn, "phase": phase, "order": order, "B": 4.0,
            "asfiled": asfiled, "lag": lag, "ex6": ex12 / 2, "ex12": ex12, "dG2": 1.0, "dG4": 2.0}


def test_whip_counts_reversal_within_two_quarters_even_outside_sample():
    rows = [_row("A", 10, "▲"), _row("A", 12, "▼", asfiled=True), _row("B", 10, "▲"), _row("B", 13, "▼"), _row("C", 10, "▼"), _row("C", 11, "▲")]
    sample = [r for r in rows if BT.in_sample(r)]
    pct, tot = BT.whip_turns(rows, sample)
    # 표본 변곡 A10▲(12▼ — 표본 밖이어도 뒤집힘) · B10▲(3분기 뒤 — 아님) · B13▼ · C10▼(11▲) · C11▲
    assert tot == 5 and abs(pct - 2 / 5 * 100) < 1e-9


def test_report_cache_keeps_excluded_rows_out_of_base_rates(tmp_path, monkeypatch):
    monkeypatch.setattr(BT, "OUT", str(tmp_path))
    rows = []
    for i in range(20):
        rows.append(_row("S%02d" % i, 40, "▲", ex12=1.0, phase="회복", order=i < 16))
        rows.append(_row("S%02d" % i, 50, "▼", ex12=-1.0, phase="수축 심화"))
        rows.append(_row("X%02d" % i, 40, "▲", ex12=100.0, asfiled=True))
        rows.append(_row("L%02d" % i, 40, "▲", ex12=200.0, lag=60))
    rep = BT.report_cache(FakeW({}), rows)
    assert rep["n"] == 40 and rep["firms"] == 20
    assert rep["ev_all"]["B_up"]["med"] == 1.0 and rep["ev_all"]["B_dn"]["med"] == -1.0
    assert rep["ev_order"]["B_up"]["n"] == 16 and set(rep["ev_order"]) >= {"B_up", "B_dn"}
    assert rep["base"] == {"ex12": 0.0, "ex6": 0.0} and rep["base_any"] == 0.0
    assert list(rep["regime"]["B"]) == list(BT.PHASES) and rep["regime"]["B"]["회복"]["med"] == 1.0
    assert set(rep["regime"]["B"]["회복"]) >= {"n", "med", "dG4", "ci", "hit"}
    assert rep["phase7"]["labels"] == list(BT.PHASES) and rep["phase7"]["order"]["회복"]["n"] == 16
    assert rep["whip"]["B"] == {"pct": 0.0, "n": 40}
    a = rep["asfiled"]
    assert a["n"] == 40 and a["why"] == {"asfiled": 20, "lag": 20, "nofiled": 0} and a["B_up"]["med"] == 150.0
    assert rep["turn"]["up"] == rep["ev_all"]["B_up"]
    with open(os.path.join(str(tmp_path), "bt_accel.json"), encoding="utf-8") as fh:
        disk = json.load(fh)
    assert {"ev_all", "ev_order", "regime", "whip", "n", "firms", "base", "phase7", "turn", "asfiled", "base_any"} <= set(disk)
    assert not os.path.exists(os.path.join(str(tmp_path), "bt_accel.json.tmp"))
