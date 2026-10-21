# -*- coding: utf-8 -*-
"""풍경 주당 값의 지배주주 기준(2026-10-22, LAND_V 12) — 변곡점.owner_parts(연간)와 _landscape_build own()(분기) 규칙.
원장 조각은 실제 캐시 원장에서 본 꼴을 줄여 옮겼다(값은 억 단위로 단순화)."""
import os
import sys
import importlib.util as ilu

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("변곡점", os.path.join(BASE, "변곡점.py"))
V = ilu.module_from_spec(_sp)
_sp.loader.exec_module(V)
FIN = sys.modules["드러켄밀러"].FIN
NO_TAG = FIN.NO_TAG
T = "ifrs-full_"
E = 100000000      # 1억


def row(sj, acc_id, name, v):
    return {"sj_div": sj, "account_id": acc_id, "account_nm": name, "thstrm_amount": str(int(v))}


def parts(rows):
    a = FIN.pick_accounts(rows)
    return V.owner_parts(FIN, rows, a.get("당기순이익"), a.get("자본총계"))


def base(ni=3675, owner=963, nci=2712, eqt=30335, eq_own=10116, eq_nci=20219):
    """HD현대 2025 꼴 — 지배 줄 · 비지배 줄 · 지배자본 · 비지배지분 모두 태그."""
    return [row("IS", T + "ProfitLoss", "당기순이익", ni * E),
            row("IS", T + "ProfitLossAttributableToOwnersOfParent", "지배기업소유주지분순이익", owner * E),
            row("IS", T + "ProfitLossAttributableToNoncontrollingInterests", "비지배지분순이익", nci * E),
            row("BS", T + "Equity", "자본총계", eqt * E),
            row("BS", T + "EquityAttributableToOwnersOfParent", "지배기업소유주지분", eq_own * E),
            row("BS", T + "NoncontrollingInterests", "비지배지분", eq_nci * E)]


def test_tagged_owner_lines():
    o = parts(base())
    assert o["ni_ctrl"] == 963 * E and o["ni_ctrl_src"] == "지배 줄" and o["ctrl_chk"] is True
    assert o["eq_ctrl"] == 10116 * E and o["eq_ctrl_src"] == "지배자본 줄"


def test_continuing_plus_discontinued_owner_tags():
    # 솔브레인홀딩스 2025 꼴 — 지배 귀속이 계속 · 중단영업으로만 나뉨(계속 421억만 집으면 실제 4,874억을 놓친다)
    rows = [row("IS", T + "ProfitLoss", "당기순이익", 4956 * E),
            row("IS", T + "IncomeFromContinuingOperationsAttributableToOwnersOfParent", "지배기업 소유주 귀속 계속영업손익", 421 * E),
            row("IS", T + "IncomeFromDiscontinuedOperationsAttributableToOwnersOfParent", "지배기업 소유주 귀속 중단영업손익", 4453 * E),
            row("IS", T + "ProfitLossAttributableToNoncontrollingInterests", "비지배지분", 82 * E)]
    o = parts(rows)
    assert o["ni_ctrl"] == 4874 * E and o["ni_ctrl_src"] == "계속 + 중단 지배 귀속"


def test_check_failure_falls_back_to_total_minus_nci():
    # 위메이드 2021 꼴 — 지배 태그 줄이 엉터리(6,455원), 지배 + 비지배 ≠ 당기순이익
    rows = base(ni=3081, owner=0, nci=14)
    rows[1]["thstrm_amount"] = "6455"
    o = parts(rows)
    assert o["ni_ctrl"] == (3081 - 14) * E and o["ctrl_chk"] is False and "검산 어긋남" in o["ni_ctrl_src"]
    # 삼성전기 2021 꼴 — 태그가 계속영업 귀속 줄(1% 를 넘는 값)이어도 검산이 어긋나면 당기순이익 − 비지배
    o = parts(base(ni=9154, owner=10554, nci=222))
    assert o["ni_ctrl"] == (9154 - 222) * E


def test_name_candidates_prefer_the_one_that_checks():
    # 태그 없는 '지배기업소유주지분' 두 줄 — 앞이 총포괄(1,099억), 뒤가 순이익 귀속(203억) — DB 2023 꼴
    rows = [row("IS", T + "ProfitLoss", "당기순이익", 300 * E),
            row("CIS", NO_TAG, "지배기업소유주지분", 1099 * E),
            row("IS", NO_TAG, "지배기업소유주지분", 203 * E),
            row("IS", T + "ProfitLossAttributableToNoncontrollingInterests", "비지배지분", 97 * E)]
    assert parts(rows)["ni_ctrl"] == 203 * E


def test_owner_name_with_jibaejuju_dangi_is_not_skipped_as_per_share():
    # '지배주주당기순이익' 은 '주당' 을 품지만 주당이익 줄이 아니다
    assert V.OWN_SKIP.search("지배주주당기순이익") is None
    assert V.OWN_SKIP.search("지배기업지분에 대한 주당순손익") is not None


def test_no_nci_and_name_line_differs_uses_total():
    # 제주은행 2016 꼴 — 비지배 줄이 없는데 이름으로 고른 지배 줄이 당기순이익과 다르다
    rows = [row("IS", T + "ProfitLoss", "당기순이익", 252 * E),
            row("IS", NO_TAG, "지배기업 소유주지분 순이익", 200 * E)]
    o = parts(rows)
    assert o["ni_ctrl"] == 252 * E and "이름 줄 값 이상" in o["ni_ctrl_src"]


def test_no_nci_line_at_all_means_owner_equals_total():
    rows = [row("IS", T + "ProfitLoss", "당기순이익", 100 * E), row("BS", T + "Equity", "자본총계", 900 * E)]
    o = parts(rows)
    assert o["ni_ctrl"] == 100 * E and o["eq_ctrl"] == 900 * E and o["nci_ni"] is None


def test_owner_equity_tag_on_paid_in_capital_is_rejected():
    # 현대백화점 2021 꼴 — 지배자본 태그가 '납입자본' 줄(1,170억)에 붙었다 → 자본총계 − 비지배
    rows = base(ni=2334, owner=1894, nci=440, eqt=52256, eq_own=1170, eq_nci=8047)
    o = parts(rows)
    assert o["eq_ctrl"] == (52256 - 8047) * E and "검산 어긋남" in o["eq_ctrl_src"]


def test_glued_capital_line_is_not_owner_equity():
    # 본문 원장(위메이드 2011 꼴) — 머리 줄과 첫 자식 줄이 붙은 '지배기업소유지분자본금' 은 지배자본이 아니다
    rows = [row("IS", NO_TAG, "당기순이익", 261 * E),
            row("BS", NO_TAG, "1.지배기업소유지분자본금", 45 * E),
            row("BS", NO_TAG, "비지배지분", 607 * E),
            row("BS", NO_TAG, "자본총계", 3305 * E)]
    o = parts(rows)
    assert o["eq_ctrl"] == (3305 - 607) * E


def test_fund_liability_nci_is_not_noncontrolling_equity():
    # 미래에셋벤처투자 꼴 — '비지배지분부채'(펀드 몫, 부채)는 비지배지분(자본)이 아니다
    rows = [row("IS", T + "ProfitLoss", "당기순이익", 309 * E),
            row("BS", T + "Equity", "자본총계", 3783 * E),
            row("BS", NO_TAG, "비지배지분부채", 6796 * E)]
    o = parts(rows)
    assert o["eq_ctrl"] == 3783 * E and o["nci_ni"] is None


def test_nci_name_variants():
    for nm in ("비지배지분", "비지배주주지분", "비지배 지분", "비지배분"):
        rows = [row("IS", T + "ProfitLoss", "당기순이익", 100 * E),
                row("BS", T + "Equity", "자본총계", 1000 * E),
                row("BS", NO_TAG, nm, 300 * E)]
        assert parts(rows)["eq_ctrl"] == 700 * E, nm


def test_roe_ctrl_uses_prior_year_only_when_adjacent():
    seq = []

    def fake(corp, y, reprt, fs="CFS"):
        r = base(eq_own={2023: 9000, 2024: 10000, 2025: 11000}.get(y, 10000), eq_nci=20000,
                 eqt={2023: 29000, 2024: 30000, 2025: 31000}.get(y, 30000))
        seq.append(y)
        return {"status": "000", "list": r} if y != 2024 else {"status": "013", "list": []}

    class F:
        def __getattr__(self, k):
            return getattr(FIN, k)
    f = F()
    f.fetch_statement = fake
    out = {d["year"]: d for d in V.fundamentals(f, "00000000", [2023, 2024, 2025])}
    assert set(out) == {2023, 2025}
    # 2025 의 앞 원소는 2023 — 바로 앞 해가 아니니 평균 없이 그해 말 지배자본 하나로
    assert abs(out[2025]["roe_ctrl"] - 963 / 11000 * 100) < 1e-9
