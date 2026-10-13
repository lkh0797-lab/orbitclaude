# -*- coding: utf-8 -*-
"""리포트(텔레그램 증권사 글 읽기) — 목표가 숫자 · 단위 · 낱말 경계 · 다른 종목 머리 · 주가 대비 상한(sanitize_tp) · 증권사별 합의(consensus).
글은 2026-10-13 실측 글의 꼴(머리말 · 구분자 · 단위 표기 · 카드 줄)만 본떠 지어낸 것 — 회사(가나전자 999990 · 다라전자 999991 · 마바바이오 999992) ·
문장 · 숫자는 가짜(실제 리포트 제목 · 본문은 증권사 저작물이라 옮기지 않는다). 쌓인 글은 tmp_path 의 가짜 jsonl 로만 잰다(실제 캐시는 건드리지 않는다)."""
import os, sys, importlib.util as ilu
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("리포트", os.path.join(BASE, "리포트.py"))
R = ilu.module_from_spec(_sp); _sp.loader.exec_module(R)
sys.modules.setdefault("리포트", R)          # 밸류체인_지도.upside_detail 이 import 리포트 로 같은 모듈을 쓰게

NAMES = {"가나전자": "999990", "다라전자": "999991", "마바바이오": "999992"}
CODES = {v: k for k, v in NAMES.items()}
CH = "하나증권 리서치"                        # 증권사 공식 채널 꼴(채널 제목에 증권사 이름)


def firms(text, ch=CH):
    return [r for r in R.parse(text, ch, NAMES, CODES) if r["kind"] == "기업"]


def pair(text, code="999990"):
    nmap, nrx = R._name_index(NAMES)
    return R._tp_pair(text, code, nmap, nrx)


# ---------------------------------------------------------------- 1. 목표가 숫자 · 단위 · 낱말 경계
@pytest.mark.parametrize("text, want", [
    ("목표주가 1,500,000원 유지", (None, 1500000)),
    ("목표주가 130만원으로 상향", (None, 1300000)),                        # 만원
    ("TP 4.5만원", (None, 45000)),                                          # 소수 만원
    ("목표주가 1,300천원", (None, 1300000)),                                # 천원 — 1,300 이 아니다
    ("BUY/TP 19만원(하향)", (None, 190000)),                                # 'BUY/TP …' 꼴
    ("BUY/6,900 (유지/유지)", (None, 6900)),
    ("목표주가 1,200,000원에서 1,300,000원으로 상향", (1200000, 1300000)),  # 이전 → 새
    ("목표주가 120만원 → 130만원", (1200000, 1300000)),                     # 단위 섞인 이전 → 새
    ("STP0404(에이즈) 파이프라인 진행", (None, None)),                       # 'STP0404' 의 TP 는 낱말이 아니다
    ("상용화 목표가 2028년으로 지연", (None, None)),                        # 해(年)
    ("공급 증설 목표: 머신 1,360→1,610대, 테이블 200→250대", (None, None)),  # 대수 — 이전 → 새 가 아니다
    ("달러-원 환율은 1,386원에서 1,380원으로", (None, None)),               # 목표 낱말 없는 '에서'
    ("3분기 영업이익 1,024억원 전망", (None, None)),
])
def test_tp_pair_units_and_boundaries(text, want):
    assert pair(text) == want


def test_tp_move_needs_sane_ratio():
    assert pair("목표주가 150,000원에서 1,500,000원으로") == (None, 150000)      # 10배 '이전 → 새' 는 믿지 않고 첫 목표가만


# ---------------------------------------------------------------- 2. 다른 종목 머리 뒤의 목표가
def test_tp_owner_other_subject_line_skipped():
    t = ("가나전자(999990): 3Q26 Pre: 숫자보다 방향\n"
         "다라전자(BUY, TP 21만원(상향)): 같은 업종 비교 메모\n"
         "가나전자 목표주가 50,000원 유지, 투자의견 BUY")
    assert pair(t) == (None, 50000)                                         # 21만원은 다라전자 것


def test_tp_owner_two_subjects_one_line_takes_mine():
    t = "금주 선호 종목으로 다라전자(매수/TP 43,000원)과 가나전자(매수/TP 60,000원)을 제시"
    assert pair(t, "999990") == (None, 60000)
    assert pair(t, "999991") == (None, 43000)


def test_tp_owner_customer_mention_is_not_subject():
    t = "다라전자향 매출 확대를 반영해 목표주가 150,000원으로 상향"
    assert pair(t) == (None, 150000)


def test_tp_owner_headline_subject_at_line_start():
    t = "2026년 06월 10일(수) Daily\n가나전자, 3분기 영업익 100조원 웃돌 것\n다라전자, 열관리 기술 車 넘어 로봇으로...목표가 5500원 상향-가나증권"
    assert pair(t) == (None, None)                                          # 5500원은 줄 머리 다라전자 것


def test_digest_item_with_many_companies_takes_only_own_line():
    # 스몰캡 채널의 아침 뉴스 묶음 — 머리기사마다 다른 종목. 가나전자 항목에 다라전자 머리기사의 380만원이 붙으면 안 된다
    t = ("2026년 06월 09일(화) Daily News\n"
         "\"가나전자, AI 팩토리 사업으로 성장 동력 확보…목표가↑\"-가나증권\n"
         "\"마바바이오, 목표가 180만→230만원…이익 추정 추가 상향 가능\"-iM\n"
         "\"조정은 매수 기회\"…다라전자, 목표가 380만원 유지-KB\n"
         "가나전자, 엔비디아 손잡고 네오클라우드 진출…목표가 40만원↑-하나\n"
         "https://example.com/news/1")
    rows = firms(t, "한양증권 리서치(스몰캡)")
    assert [(r["code"], r["tp"]) for r in rows] == [("999990", 400000)]
    # 종목 하나만 적힌 항목은 예전처럼 — 줄에 이름이 없어도 목표가를 읽는다
    assert pair("가나전자(999990) 3Q26 Preview 리포트\n목표주가 50,000원 유지") == (None, 50000)


def test_whole_post_uses_owner_guard_and_units():
    t = ("[가나전자(999990)/BUY(유지)/TP 19만원(하향)/ 하나 제약 홍길동]\n"
         "▶ 2Q26 매출 1,085억원(+58.9% YoY)으로 컨센서스 하회\n"
         "▶ STP0404(에이즈) 등 R&D 모멘텀 유효. 실적 추정치 조정을 반영해 적정주가 19만원으로 하향")
    rows = firms(t)
    assert len(rows) == 1 and rows[0]["code"] == "999990" and rows[0]["tp"] == 190000 and rows[0]["change"] == "하향"


# ---------------------------------------------------------------- 3. 카드 글(신한 꼴) — '이전 → 새' 도 목표 낱말 · 비율 검사
def test_card_shinhan_style_move_guard():
    t = ("[기업][가나전자] 가나전자; 방어주 성격, 탑라인 회복 지켜볼 필요\n"
         "하나생각: 비용 역기저로 순이익은 기대치 대비 10% 상회 예상. 장기적으로는 주주환원과 공급증설(머신 1,360→1,610대, 테이블 200→250대)이 핵심\n"
         "Valuation & Risk: 목표주가 18,000원 유지. 투자의견 매수")
    rows = [r for r in R.parse(t, "[주식] 증권사 리포트", NAMES, CODES) if r["kind"] == "기업"]
    assert len(rows) == 1 and rows[0]["tp"] == 18000 and rows[0]["tp_prev"] is None


def test_card_stock_line_price_and_tp():
    t = ("[기업][가나전자] 3Q26 Pre: 잠시 흐린 렌즈\n"
         "📌 종목: 가나전자 (999990) | BUY | 현재가 644,000원 | 목표주가 1,200,000원\n"
         "📊 핵심 투자포인트\n- 환율 충격은 일시적, 4분기부터 원가 부담 완화 전망\n🔗 원문보기 https://example.com/r/1")
    rows = [r for r in R.parse(t, "[주식] 증권사 리포트", NAMES, CODES) if r["kind"] == "기업"]
    assert rows[0]["tp"] == 1200000 and rows[0]["price_at"] == 644000 and rows[0]["src"] == "card"


# ---------------------------------------------------------------- 4. build — 주가 대비 상한(sanitize_tp)
def _msg(i, date, ch, text, url=None):
    return {"id": i, "date": date, "channel": ch.split()[0], "channel_title": ch, "url": url or ("https://t.me/x/%d" % i), "text": text}


def test_build_sanitize_tp_against_close_and_card_price(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "STORE_DIR", str(tmp_path / "rep"))
    monkeypatch.setattr(R, "STATE_PATH", str(tmp_path / "rep" / "_state.json"))
    R.append([
        # 다른 회사 리포트에 마바바이오가 머리 줄에 스쳐 적힌 꼴 — 종가 4,000원인데 65,000원(16배)
        _msg(1, "2026-10-01 08:21", CH, "▶ 재무 건전성 우려 해소, 2026년 마바바이오 영업 성과 확인 필요\n- PER 밴드 상단 적용하여, 적정주가 65,000원으로 상향. 리포트"),
        # 카드 — 현재가 10,000원 · 목표주가 1,200원(자릿수 오류)
        _msg(2, "2026-10-02 07:55", "[주식] 증권사 리포트", "[기업][가나전자] 눈높이 조정\n📌 종목: 가나전자 (999990) | BUY | 현재가 10,000원 | 목표주가 1,200원\n📊 핵심 투자포인트\n- 포인트 하나 둘 셋 넷\n🔗 원문보기 https://example.com/r/2"),
        # 정상 — 종가 10,000원 · 목표주가 15,000원
        _msg(3, "2026-10-03 08:00", CH, "[가나전자(999990)/BUY/TP 15,000원]\n▶ 3Q26 Preview: 실적 개선 지속"),
        # 통신장비 담당 꼴 4배 목표가 — 상한 5배 안이라 둔다
        _msg(4, "2026-10-04 08:00", CH, "[다라전자(999991)/BUY/TP 40,000원]\n▶ 2027년 이익 급증 전망 리포트"),
    ])
    closes = {"999992": {"20260930": 4000.0, "20261001": 4100.0}, "999990": {"20260930": 10000.0, "20261002": 10200.0, "20261003": 10100.0},
              "999991": {"20261002": 10000.0, "20261003": 10000.0}}
    rows = {r["msg_id"]: r for r in R.build(NAMES, CODES, px_of=lambda c: closes.get(c))}
    assert rows[1]["tp"] is None and rows[1]["tp_raw"] == 65000
    assert rows[2]["tp"] is None and rows[2]["tp_raw"] == 1200 and rows[2]["price_at"] == 10000
    assert rows[3]["tp"] == 15000 and "tp_raw" not in rows[3]
    assert rows[4]["tp"] == 40000
    # px_of 없이는 카드 현재가로만 — 증권사 글은 그대로
    rows = {r["msg_id"]: r for r in R.build(NAMES, CODES)}
    assert rows[1]["tp"] == 65000 and rows[2]["tp"] is None


def test_close_at_pre_market_uses_previous_close():
    closes = {"20260727": 614000.0, "20260728": 514000.0}
    ks = sorted(closes)
    assert R._close_at(closes, ks, "2026-07-28 07:55") == 614000.0      # 장 시작 전 글 — 전날 종가
    assert R._close_at(closes, ks, "2026-07-28 10:55") == 514000.0      # 장중 · 장 뒤 글 — 그날 종가
    assert R._close_at(closes, ks, "2026-07-26 10:00") is None


# ---------------------------------------------------------------- 5. consensus — 증권사별 최신 · 미표기 중복 · 3배 밖 · 리포트 당시 주가
ROWS = [
    {"date": "2026-10-08 07:20", "broker": None, "tp": 1200000, "price_at": 644000, "title": "a", "msg_url": "u1"},
    {"date": "2026-10-07 08:00", "broker": None, "tp": 1030000, "price_at": 644000, "title": "b", "msg_url": "u2"},
    {"date": "2026-09-30 07:55", "broker": "다올투자증권", "tp": 1000000, "title": "c", "msg_url": "u3"},
    {"date": "2026-08-31 08:00", "broker": None, "tp": 1030000, "price_at": 611000, "title": "d", "msg_url": "u4"},     # b 와 같은 값 — 같은 집
    {"date": "2026-07-28 07:55", "broker": "교보증권", "tp": 1300000, "title": "e", "msg_url": "u5"},
    {"date": "2026-07-28 10:55", "broker": None, "tp": 1300000, "price_at": 614000, "title": "f", "msg_url": "u6"},    # 교보와 같은 값 — 교보 것
    {"date": "2026-07-28 09:00", "broker": "하나증권", "tp": 99000000, "title": "g", "msg_url": "u7"},                 # 중앙값 3배 밖
    {"date": "2026-07-01 08:00", "broker": "다올투자증권", "tp": 1300000, "title": "old", "msg_url": "u8"},            # 다올 옛 것 — 최신이 이긴다
    {"date": "2026-03-01 08:00", "broker": "IBK투자증권", "tp": 700000, "title": "out", "msg_url": "u9"},              # 180일 밖
    {"date": "2026-10-09 08:00", "broker": "메리츠증권", "tp": None, "title": "no tp", "msg_url": "u10"},
]
CLOSES = {"20260929": 564000.0, "20260930": 570000.0, "20260727": 614000.0, "20260728": 514000.0}


def test_consensus_dedup_outlier_and_up_at():
    cs = R.consensus(ROWS, 455500.0, "2026-04-16", CLOSES)
    assert cs["n"] == 4 and cs["reps"] == 8
    assert [h["tp"] for h in cs["houses"]] == [1200000, 1030000, 1000000, 1300000]
    assert cs["houses"][2]["broker"] == "다올투자증권" and cs["houses"][2]["date"].startswith("2026-09-30")
    assert cs["dropped"] == [{"broker": "하나증권", "tp": 99000000, "date": "2026-07-28 09:00", "url": "u7"}]
    assert round(cs["avg"]) == 1132500 and cs["med"] == 1115000 and cs["tp_max"] == 1300000 and cs["tp_min"] == 1000000
    assert abs(cs["up"] - 148.6) < 0.1
    # 리포트 당시: 카드는 현재가, 증권사 글은 그날(장 시작 전이면 전날) 종가 — 1.2M/644k · 1.03M/644k · 1.0M/564k · 1.3M/614k
    assert [h["px_at"] for h in cs["houses"]] == [644000, 644000, 564000.0, 614000.0]
    assert abs(cs["up_at"] - 83.8) < 0.2 and cs["asof"] == "2026-10-08"


def test_consensus_small_n_keeps_all_and_none_without_tp():
    cs = R.consensus(ROWS[2:3] + ROWS[6:7], 100000.0, "2026-04-16")
    assert cs["n"] == 2 and cs["dropped"] == [] and cs["up_at"] is None       # 3곳 미만 — 3배 규칙 없음 · 주가 자료 없으면 up_at None
    assert R.consensus(ROWS[9:], 100000.0, "2026-04-16") is None
    assert R.consensus(ROWS, None, "2026-04-16")["up"] is None


def test_vcmap_upside_detail_delegates_to_consensus():
    sp = ilu.spec_from_file_location("밸류체인_지도_rep", os.path.join(BASE, "밸류체인_지도.py"))
    M = ilu.module_from_spec(sp); sp.loader.exec_module(M)
    d = M.upside_detail(ROWS, 455500.0, "2026-04-16", CLOSES)
    assert d == {"up": 148.6, "n": 4, "reps": 8, "avg": 1132500, "med": 1115000, "up_at": 83.8, "asof": "2026-10-08"}
    assert M.upside_detail(ROWS, None, "2026-04-16") is None and M.upside(ROWS, 455500.0, "2026-04-16") == 148.6
    # 상승여력 문장 · 근거에 '리포트 당시' 가 붙는다(15p 넘게 벌어졌을 때)
    from collections import Counter
    s = M.score({"prod": [], "supply": [], "themes": [], "rep_n": 3, "rep_by": Counter({"기판": 3}), "rep_refs": [], "hist": [], "cust": [], "rep_df": {}},
                lead_p3=50, px={"p1": 50, "p3": 40, "dd": -70.2}, ph=None, n_rep=30, up=d, name="가나전자", lead_name="다라전자")
    attn = [e["t"] for e in s["ev"]["attn"] if "목표가" in e["t"]][0]
    assert attn == "리포트 목표가 평균 1,132,500원 → +149% (리포트 당시 주가 대비 +84%)"
    assert "상승여력은 +149%(리포트 당시 주가 대비는 +84% — 목표가 뒤 주가가 내렸다)" in s["expl"]


# ---------------------------------------------------------------- 6. 서버 reports_view 배선(서버를 띄우지 않고 모듈만)
@pytest.fixture(scope="module")
def SRV():
    sp = ilu.spec_from_file_location("서버_리포트_시험", os.path.join(BASE, "서버.py"))
    m = ilu.module_from_spec(sp); sp.loader.exec_module(m)
    return m


def test_reports_view_consensus_fields(SRV, monkeypatch):
    co = {"code": "999990", "name": "가나전자"}
    monkeypatch.setattr(SRV, "company_by_code", lambda c: co if c == "999990" else None)
    monkeypatch.setattr(SRV, "_rep_rows", lambda: {"by_code": {"999990": ROWS}})
    monkeypatch.setattr(SRV, "REP", R)
    monkeypatch.setattr(SRV, "reports_status", lambda: {"ready": False})

    class _Fin:
        @staticmethod
        def fetch_prices(code):
            return dict(CLOSES, **{"20261013": 455500.0})
    monkeypatch.setattr(SRV, "FIN", _Fin)
    import datetime, types
    fake_date = type("D", (), {"today": staticmethod(lambda: datetime.date(2026, 10, 13))})
    monkeypatch.setattr(SRV, "dt", types.SimpleNamespace(date=fake_date, timedelta=datetime.timedelta, datetime=datetime.datetime))
    d = SRV.reports_view("999990")
    assert d["price"] == 455500.0 and round(d["tp_avg"]) == 1132500 and d["tp_med"] == 1115000 and d["tp_n"] == 4
    assert abs(d["upside"] - 148.6) < 0.1 and abs(d["upside_at"] - 83.8) < 0.2 and d["tp_asof"] == "2026-10-08"
    assert [h["tp"] for h in d["latest"]] == [1200000, 1030000, 1000000, 1300000] and d["tp_dropped"][0]["broker"] == "하나증권"
    assert d["n180"] == 9 and d["tp_max"] == 1300000 and d["tp_min"] == 1000000
