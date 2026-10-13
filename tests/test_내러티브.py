# -*- coding: utf-8 -*-
"""내러티브(이 종목 소식 피드). 분류 시험 제목은 2026-10-10 KIS 실측 제목의 꼴(규칙에 걸리는 머리말 · 틀)만 본떠
지어낸 것이다 — 회사(가나광섬유 999990 · 다라전자 999991) · 출처 · 숫자는 가짜(KIS 제목은 언론사 저작물이라 옮기지 않는다).
공시 색인 · 주가 · 낱말은 tmp_path 의 가짜 파일로만 잰다(실제 캐시는 건드리지 않는다)."""
import os, sys, json, time, threading, datetime as dt, importlib.util as ilu
import pytest
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_sp = ilu.spec_from_file_location("내러티브", os.path.join(BASE, "내러티브.py"))
N = ilu.module_from_spec(_sp); _sp.loader.exec_module(N)

CO, NAME = "999990", "가나광섬유"
CO2, NAME2 = "999991", "다라전자"


def row(title, src="가상통신", pc="9", lc="01", d="20261002", t="091500", c1=CO, id_=None):
    return {"id": id_ or (d + t + "%05d" % (abs(hash(title + src + t)) % 100000)), "d": d, "t": t, "src": src,
            "pc": pc, "lc": lc, "title": title, "c1": c1, "n1": ""}


# ---------------------------------------------------------------- 2.1 뉴스 분류 (실측 꼴 · 지어낸 제목)
CASES = [
    # (기대 k, 제목, 출처, 제공사, 분류 코드)
    ("alert", "가나광섬유(주) [투자주의]투자경고종목 지정예고", "코스닥 공시", "G", "03"),
    ("alert", "가나광섬유(주) 매매거래정지 예고", "코스닥 공시", "G", "03"),
    ("alert", "가나광섬유(주) 공매도 과열종목 지정(공매도 거래 금지 적용)", "코스닥 공시", "G", "03"),
    ("alert", "가나광섬유(주) 시장안내(기타)", "코스닥 공시", "G", "03"),                  # 모르는 lc 03 조치는 경보로 둔다
    ("alert", "다라전자(주) 주식선물ㆍ주식옵션 3단계 가격제한폭 확대요건 도달(하락)", "공시", "I", "12"),
    ("disc", "가나광섬유(주) (정정)유상증자결정(주주배정후 실권주 일반공모)", "코스닥 공시", "G", "01"),
    ("disc", "다라전자(주) 연결재무제표기준영업(잠정)실적(공정공시)", "거래소 공시", "F", "02"),
    ("disc", "가나광섬유(주) 추가상장(국내사모 전환사채 전환)", "코스닥 공시", "G", "03"),     # 상장 · 권리 안내는 시장조치 아님
    ("disc", "가나광섬유(주) 권리락(유상증자)", "코스닥 공시", "G", "03"),
    ("disc", "가나광섬유(주) 신주인수권증서 신규상장(가나광섬유 9R)", "코스닥 공시", "G", "03"),
    ("ad", "기회는 지금뿐, 이 정보 하나로 판이 바뀝니다!!", "딜사이트", "f", "15"),
    ("ad", "보유 자산 최대 3배로 키워 오늘 상승장을 잡으세요?!", "가상경제", "2", "01"),
    ("ad", "연 4%대 갈아타기 대환 상품 출시!! 한도 걱정 끝 스탁론", "가상경제", "2", "01"),
    ("ad", "[MBN골드] 다음 주 서울에서 재테크 강연회", "가상일보", "A", "17"),
    ("ad", "투자정보 서비스 한경유레카 새 판 기념 20% 할인이벤트", "가상경제", "2", "01"),
    ("ad", "AI 퀀트 서비스 론칭 기념 40% 할인마감 D-2", "가상경제", "2", "01"),
    ("robot", "28일, 외국인 코스닥에서 가나광섬유(-3.10%), 마바테크(-4.20%) 등 순매도", "가상경제", "2", "01"),
    ("robot", "<코>가나광섬유, 상한가 진입.. +29.90% ↑", "가상일보", "U", "31"),
    ("robot", "오전 10:30 현재 코스닥은 45:55로 매수우위, 매수강세 업종은 기타서비스업(0.21%↑)", "가상일보", "U", "31"),
    ("robot", "[장중수급포착] 가나광섬유, 외국인/기관 동시 순매수… 주가 +4.10%", "가상통신", "9", "10"),
    ("robot", "'가나광섬유' 52주 신고가 경신, 광케이블 수요 수혜 - 가상증권, None", "가상경제", "2", "01"),
    ("robot", "가나광섬유, 상한가 기록", "가상경제", "2", "01"),
    ("info_list", "1억원 이상 매도체결 상위 20 종목(코스닥)", "인포스탁", "7", "02"),
    ("info_list", "외국계 순매수,도 상위종목(코스닥) 수량기준", "인포스탁", "7", "02"),
    ("info_list", "증시요약(10) - 기술적 분석 특징주 B(코스닥)", "인포스탁", "7", "02"),
    ("info_list", "인기검색 20종목", "인포스탁", "7", "01"),
    ("info_list", "개장전★주요이슈 점검", "인포스탁", "7", "01"),
    ("info_list", "가나ETF(999992) - 인포스탁 모닝 브리핑", "인포스탁", "7", "01"),
    ("info_list", "[1008주요일정]", "인포스탁", "7", "01"),
    ("info_list", "증권사 신규추천 종목", "인포스탁", "7", "01"),
    ("info_move", "마바테크(999993)  +5.10%, 사아소재 +3.20%, 가나광섬유 +3.00%, 자차정밀 +2.90%", "인포스탁", "7", "02"),
    ("info_move", "가나광섬유(999990) 소폭 상승세 +2.80%", "인포스탁", "7", "02"),
    ("info_echo", "가나광섬유, 임원ㆍ주요주주 특정증권등 소유주식수 변동", "인포스탁", "7", "02"),
    ("roundup", "[증시키워드] 반도체 실적 대기…신약 모멘텀에 관심도↑", "가상투데이", "D", "21"),
    ("roundup", "코스피, 외인 매도에 이틀째 하락…6800선 마감", "가상일보", "A", "18"),
    ("roundup", "[급등락주 짚어보기] 광통신주 강세", "가상경제", "2", "01"),
    ("roundup", "[전날 애프터마켓] 반도체 약세", "가상투데이", "D", "21"),
    ("art", "가나광섬유, 美 AI 데이터센터에 300억 규모 광케이블 추가 공급", "가상데일리", "4", "S5"),
    ("art", "[특징주] 마바테크·가나광섬유 등 광통신株 장 초반 급등", "가상투데이", "D", "21"),
    ("art", "가나광섬유, 300억 규모 美 데이터센터向 광케이블 2차 공급물량 확보", "인포스탁", "7", "02"),
    ("art", "[리포트 브리핑]가나광섬유, '광섬유 레버리지 본격화' Not Rated - 가상증권", "가상통신", "9", "01"),
    ("art", "'AI 수혜주' 가나광섬유, 3개월 새 4배", "가상경제", "2", "01"),
    ("art", "[급등락주 짚어보기] 가나광섬유 강세", "가상경제", "2", "01"),                       # 이름이 있으면 시황 머리말보다 먼저
    ("mention", "[특징주] 광통신주, 美광통신 강세 등에 줄상승(종합)", "가상뉴스", "6", "03"),
    ("mention", "통신장비株 강세…AI 데이터센터 초고속망 수요 증가 효과", "가상투데이", "5", "F01"),
    ("mention", "[테마시황] 가상칩-가상유리, 4조원 '빛의 동맹'... 국내 광통신주 일제히 급등", "인포스탁", "7", "01"),
]


@pytest.mark.parametrize("k,title,src,pc,lc", CASES)
def test_classify_news_titles(k, title, src, pc, lc):
    assert N.classify_news(row(title, src, pc, lc), CO, NAME) == k


def test_classify_name_ignores_spacing_and_corp_mark():
    r = row("가나 광섬유(주), 2분기 흑자 전환")
    assert N.classify_news(r, CO, "가나광섬유(주)") == "art"
    assert N.classify_news(row("마바 이어 가상칩도 ‘깜짝 실적’?AI 반도체 호황 지속", c1=CO2), CO2, NAME2) == "mention"


def test_classify_name_present_beats_roundup():
    """시황 머리말이 있어도 회사 이름이 있으면 이 종목 기사(규칙 순서: 시황은 이름 없을 때만)."""
    r = row("[증시키워드] ‘30만 전자·200만 닉스’ 신고가…자동차·가나광섬유도 관심", "가상투데이", "D", "21")
    assert N.classify_news(r, CO, NAME) == "art"


def test_classify_alias_counts_as_name(monkeypatch):
    """별칭(ALIAS)이 제목에 있으면 이름이 있는 것 — 표기만 다른 같은 소식이 보였다 숨었다 하지 않게."""
    monkeypatch.setitem(N.ALIAS, CO2, ("다전",))
    roundup = row("코스피, 다전 영업익 100조에도 2% 급락(종합)", "가상일보", "A", "18", c1=CO2)
    assert N.classify_news(roundup, CO2, NAME2) == "art"
    assert N.classify_news(row("다전닉스 지금 팔면 후회한다", c1=CO2), CO2, NAME2) == "art"
    assert N.classify_news(roundup, CO, NAME) == "roundup"                     # 별칭은 그 회사에만
    assert N.ALIAS["005930"] == ("삼전",)


# ---------------------------------------------------------------- 접기 · 숨김
def _feed(**kw):
    kw.setdefault("today", "20261011")
    return N.build_feed(kw.pop("code", CO), kw.pop("name", NAME), **kw)


def test_fold_same_day_same_title_keeps_earliest():
    news = [row("가나광섬유, 美 가상아메리카 인수 완료", "가상통신", t="150000", id_="2026100215000000001"),
            row("가나광섬유,  美 가상아메리카 인수 완료!", "가상데일리", t="093000", id_="2026100209300000002"),
            row("가나광섬유, 美 가상아메리카 인수 완료", "가상통신", d="20261005", t="080000", id_="2026100508000000003")]
    its = [it for it in _feed(news=news)["items"] if it["type"] == "news"]
    assert [(it["d"], it["n"], it["t"], it["src"]) for it in its] == [("20261005", 1, "0800", "가상통신"),
                                                                     ("20261002", 2, "0930", "가상데일리")]
    assert its[1]["id"] == "n:2026100209300000002"


def test_hidden_items_kept_with_common_fields_only():
    news = [row("1억원 이상 매도체결 상위 20 종목(코스닥)", "인포스탁", "7", "02"),
            row("가나광섬유, 미국 수주잔고 1000억원 돌파")]
    d = _feed(news=news)
    hid = [it for it in d["items"] if it["hide"]]
    vis = [it for it in d["items"] if it["type"] == "news" and not it["hide"]]
    assert len(hid) == 1 and hid[0]["k"] == "info_list" and "search" not in hid[0] and "c1" not in hid[0]
    assert vis[0]["k"] == "art" and vis[0]["c1"] == CO
    assert vis[0]["search"].startswith("https://search.naver.com/search.naver?where=news&query=")
    assert "%20" in vis[0]["search"] and "가나광섬유" in vis[0]["search"]      # 한글은 그대로(IRI), 공백 · 기호만 인코딩
    assert d["counts"]["news"] == 1 and d["counts"]["hidden"] == 1


def test_hidden_cap_keeps_newest():
    news = [row("인기검색 20종목", "인포스탁", "7", "01", d="202609%02d" % (k + 1), id_="202609%02d0900000000%d" % (k + 1, k))
            for k in range(5)]
    d = _feed(news=news, max_hidden=2)
    assert [it["d"] for it in d["items"] if it["hide"]] == ["20260905", "20260904"]
    assert d["src"]["news"]["cut_hidden"] == 3


def test_byte_budget_drops_old_hidden_then_old_visible():
    news = [row("인기검색 20종목 %d" % k, "인포스탁", "7", "01", d="202609%02d" % (k + 1), id_="1%02d" % k) for k in range(20)]
    news += [row("가나광섬유 기사 %d" % k, d="202609%02d" % (k + 1), id_="2%02d" % k) for k in range(20)]
    full = _feed(news=news, max_bytes=0)
    small = _feed(news=news, max_bytes=N.jsize(full) - 3000)
    assert N.jsize(small) <= N.jsize(full) - 3000
    assert small["counts"]["hidden"] < full["counts"]["hidden"]
    kept = [it["d"] for it in small["items"] if it["hide"]]
    assert kept == sorted(kept, reverse=True) and (not kept or kept[0] == "20260920")     # 오래된 것부터 덜어 냄
    assert small["src"]["news"]["cut_hidden"] == full["counts"]["hidden"] - small["counts"]["hidden"]


def _big_report(k, d):
    return {"kind": "기업", "code": CO, "broker": "가상증권", "title": "리포트 %d" % k, "date": d[:4] + "-" + d[4:6] + "-" + d[6:] + " 08:00",
            "msg_url": "https://t.me/examplereport/%d" % k, "lines": ["투자포인트 %d %s" % (j, "가" * 60) for j in range(6)],
            "est": ["전망 " + "나" * 80], "risks": ["위험 " + "다" * 80], "concl": "결론 " + "라" * 80,
            "sections": [{"h": "요약", "p": "마" * 200}]}


def test_byte_budget_order_keeps_news_counts_and_takes_reports_discs_first():
    """덜기 순서: 숨김 → 90일 넘은 리포트 머리만 → 3년 넘은 공시(분류 없는 것 먼저) → 30일 넘은 보이는 뉴스 → 보이는 뉴스.
    days · counts 의 뉴스 건수는 덜기 전 전부로 센다(관심도 띠가 1년 내내 맞게)."""
    today = dt.date(2026, 10, 11)
    news, reps, discs = [], [], []
    for k in range(120):                                             # 120일 × 하루 3건 보이는 뉴스 + 1건 숨김
        d = (today - dt.timedelta(days=k + 1)).strftime("%Y%m%d")
        news += [row("가나광섬유 소식 %d-%d" % (k, j), d=d, t="1%d0000" % j, id_="%s1%d%03d" % (d, j, k)) for j in range(3)]
        news.append(row("인기검색 20종목 %d" % k, "인포스탁", "7", "01", d=d, id_="%s9%03d" % (d, k)))
    for k in range(40):
        reps.append(_big_report(k, (today - dt.timedelta(days=10 + 5 * k)).strftime("%Y%m%d")))
    for k in range(200):                                             # 2018~2019 옛 공시 — 분류 없음 · 호재 반반
        d = (dt.date(2018, 1, 2) + dt.timedelta(days=3 * k)).strftime("%Y%m%d")
        discs.append({"d": d, "rcept": d + "%06d" % k, "kind": "I", "title": ("주식소각결정 %d" if k % 2 else "기타공시 %d") % k,
                      "flr": ""})
    discs.sort(key=lambda x: x["d"], reverse=True)
    full = _feed(news=news, reports=reps, discs=discs, max_bytes=0)
    vis_n = sum(1 for it in full["items"] if it["type"] == "news" and not it["hide"])
    assert vis_n == 360 and full["counts"]["news"] == 360 and full["src"]["news"]["shown"] == 360
    news_days = {d: x["news"] for d, x in full["days"].items() if x["news"]}

    # 1) 숨김 · 옛 리포트 머리만 · 옛 공시 일부만 덜어도 맞는 한도 — 보이는 뉴스는 그대로
    hid_b = sum(N.jsize(it) + 1 for it in full["items"] if it["hide"])
    disc_b = sum(N.jsize(it) + 1 for it in full["items"] if it["type"] == "disc")
    head = lambda it: dict({k: v for k, v in it.items() if k not in ("lines", "est", "risks", "concl", "sections")}, slim=True)
    rep_b = sum(N.jsize(it) - N.jsize(head(it)) for it in full["items"] if it["type"] == "report" and it["d"] < "20260713")
    cap = N.jsize(full) - hid_b - rep_b - disc_b // 3
    mid = _feed(news=news, reports=reps, discs=discs, max_bytes=cap)
    assert N.jsize(mid) <= cap
    assert mid["counts"]["hidden"] == 0 and mid["src"]["news"]["cut"] == 0 and mid["src"]["news"]["shown"] == 360
    rs = [it for it in mid["items"] if it["type"] == "report"]
    slim = [r for r in rs if r.get("slim")]
    assert slim and mid["src"]["reports"]["slim"] == len(slim) == sum(1 for r in reps if r["date"] < "2026-07-13")
    assert all(r["d"] < "20260713" and "lines" not in r and "sections" not in r and r["msg_url"] for r in slim)
    assert all(r.get("lines") for r in rs if r["d"] >= "20260713")         # 최근 90일 리포트는 그대로
    left = [it for it in mid["items"] if it["type"] == "disc"]
    cut = mid["src"]["disc"]["cut"]
    assert cut == 200 - len(left) > 0 and mid["src"]["disc"]["n"] == 200
    assert sum(1 for it in left if it["cls"]["g"]) == 100 and sum(1 for it in left if not it["cls"]["g"]) == 100 - cut   # 분류 없는 것 먼저

    # 2) 보이는 뉴스까지 덜어야 하는 한도 — 오래된 것부터, 최근 30일은 지키고, 날짜별 건수 · counts 는 그대로
    news_b = sum(N.jsize(it) + 1 for it in full["items"] if it["type"] == "news" and not it["hide"])
    cap = N.jsize(full) - hid_b - rep_b - disc_b - news_b // 2
    low = _feed(news=news, reports=reps, discs=discs, max_bytes=cap)
    assert N.jsize(low) <= cap
    kept = sorted(it["d"] for it in low["items"] if it["type"] == "news" and not it["hide"])
    every = sorted(it["d"] for it in full["items"] if it["type"] == "news" and not it["hide"])
    assert low["src"]["news"]["cut"] == 360 - len(kept) > 0 and low["src"]["news"]["shown"] == len(kept)
    assert kept == every[-len(kept):]                                      # 오래된 것부터 뺐다
    assert sum(1 for d in kept if d >= "20260911") == 90                   # 최근 30일(하루 3건)은 그대로
    assert low["src"]["disc"]["cut"] == 200 and low["counts"]["disc"] == 0
    assert low["counts"]["news"] == 360
    assert {d: x["news"] for d, x in low["days"].items() if x["news"]} == news_days

    # 3) 30일치도 못 지키는 한도면 그때는 그것도 덜어 낸다(한도가 먼저)
    tiny = _feed(news=news, reports=reps, discs=discs, max_bytes=cap - news_b // 3)
    assert N.jsize(tiny) <= cap - news_b // 3
    assert sum(1 for it in tiny["items"] if it["type"] == "news" and not it["hide"]) < 90


# ---------------------------------------------------------------- 2.2 공시 색인
def _disc_line(rc, d, code, name, nm, flr=None):
    return json.dumps({"rcept_no": rc, "rcept_dt": d, "corp_code": "0", "corp_name": name, "stock_code": code,
                       "corp_cls": "K", "report_nm": nm, "flr_nm": flr or name}, ensure_ascii=False)


def _write_disc(dirp, fname, lines, done=True):
    (dirp / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if done:
        (dirp / (fname + ".done")).write_text("", encoding="utf-8")


@pytest.fixture
def disc_dir(tmp_path):
    d = tmp_path / "공시목록"
    d.mkdir()
    _write_disc(d, "I_2026Q1.jsonl", [
        _disc_line("20260212900001", "20260212", CO, NAME, "소송등의판결ㆍ결정    (일정금액 이상의 청구)"),
        _disc_line("20260213900002", "20260213", CO2, NAME2, "기업설명회(IR)개최(안내공시)"),
        _disc_line("20260214900003", "20260214", "", "비상장", "무엇"),
        _disc_line("20260215900004", "20260215", CO, NAME, "투자경고종목지정", "코스닥시장본부")])
    _write_disc(d, "B_2026Q1.jsonl", [_disc_line("20260212900001", "20260212", CO, NAME,
                                                 "소송등의판결ㆍ결정 (일정금액 이상의 청구)")])   # I 와 같은 접수번호
    _write_disc(d, "A001_2026Q4.jsonl", [_disc_line("20261008000001", "20261008", CO, NAME, "반기보고서 (2026.06)")],
                done=False)
    (d / "공시위험.json").write_text("{}", encoding="utf-8")
    return d


def test_disc_rows_none_without_index(disc_dir):
    assert N.disc_rows(CO, str(disc_dir)) is None
    assert not N.disc_index_ready(str(disc_dir))


def test_disc_index_build_and_lookup(disc_dir):
    r = N.disc_index_update(str(disc_dir))
    assert r["mode"] == "full" and r["files"] == 2 and r["rows"] == 4            # 열린 분기 · 비상장 줄은 안 넣는다
    idx = disc_dir / "_by_code"
    assert sorted(p.name for p in idx.iterdir() if p.name.startswith("b")) == ["b%02d.jsonl" % b for b in range(64)]
    man = json.loads((idx / "_manifest.json").read_text(encoding="utf-8"))
    assert man["v"] == 1 and set(man["files"]) == {"I_2026Q1.jsonl", "B_2026Q1.jsonl"}
    assert not (disc_dir / "_by_code.tmp").exists()
    rows = N.disc_rows(CO, str(disc_dir))
    assert [x["rcept"] for x in rows] == ["20261008000001", "20260215900004", "20260212900001"]   # 열린 분기도 · 날짜 내림차순 · 중복 하나
    assert rows[0] == {"d": "20261008", "rcept": "20261008000001", "kind": "A001", "title": "반기보고서 (2026.06)", "flr": ""}
    assert rows[1]["flr"] == "코스닥시장본부"
    assert rows[2]["title"] == "소송등의판결ㆍ결정 (일정금액 이상의 청구)" and rows[2]["kind"] == "B"       # 공백 정리 · 먼저 본 파일
    assert [x["rcept"] for x in N.disc_rows(CO2, str(disc_dir))] == ["20260213900002"]
    assert N.disc_rows("999999", str(disc_dir)) == []
    assert N.disc_index_update(str(disc_dir))["mode"] == "none"


def test_disc_index_incremental_and_rebuild(disc_dir):
    N.disc_index_update(str(disc_dir))
    sig0 = N.disc_sig(str(disc_dir))
    _write_disc(disc_dir, "I_2026Q2.jsonl", [_disc_line("20260512900009", "20260512", CO, NAME, "투자경고종목지정")])
    assert [x["rcept"] for x in N.disc_rows(CO, str(disc_dir))][:2] == ["20261008000001", "20260512900009"]  # 색인 전에도 보인다
    time.sleep(1.1)
    r = N.disc_index_update(str(disc_dir))
    assert r["mode"] == "add" and r["files"] == 1 and r["rows"] == 1
    assert "I_2026Q2.jsonl" in json.loads((disc_dir / "_by_code" / "_manifest.json").read_text(encoding="utf-8"))["files"]
    assert N.disc_sig(str(disc_dir)) != sig0
    assert len(N.disc_rows(CO, str(disc_dir))) == 4
    # 닫힌 파일 내용이 바뀌면(크기 · 시각) 처음부터 다시
    _write_disc(disc_dir, "B_2026Q1.jsonl", [_disc_line("20260301900010", "20260301", CO, NAME, "새 줄")])
    r = N.disc_index_update(str(disc_dir))
    assert r["mode"] == "full" and r["files"] == 3
    rc = [x["rcept"] for x in N.disc_rows(CO, str(disc_dir))]
    assert "20260301900010" in rc and len(rc) == len(set(rc))


def test_disc_sig_tracks_open_quarter(disc_dir):
    N.disc_index_update(str(disc_dir))
    s0 = N.disc_sig(str(disc_dir))
    assert "A001_2026Q4.jsonl" in s0 and "I_2026Q1" not in s0
    time.sleep(1.1)
    _write_disc(disc_dir, "A001_2026Q4.jsonl", [_disc_line("20261009000002", "20261009", CO, NAME, "x"),
                                                _disc_line("20261008000001", "20261008", CO, NAME, "y")], done=False)
    assert N.disc_sig(str(disc_dir)) != s0


# ---------------------------------------------------------------- DART ↔ KIS 공시 겹침 · 정기보고서
def _dart(rc, d, title, kind="I", flr=""):
    return {"d": d, "rcept": rc, "kind": kind, "title": title, "flr": flr}


def test_krx_disc_dropped_when_dart_has_it_and_time_borrowed():
    news = [row("가나광섬유(주) (정정)유상증자결정(주주배정후 실권주 일반공모)", "코스닥 공시", "G", "01", d="20260223", t="143000"),
            row("가나광섬유(주) 매출액 또는 손익구조 30%(대규모법인은 15%)이상 변동", "코스닥 공시", "G", "01", d="20260223", t="174900"),
            row("가나광섬유(주) 정기주주총회결과", "코스닥 공시", "G", "01", d="20261008", t="160500"),
            row("가나광섬유(주) [투자주의]투자경고종목 지정예고", "코스닥 공시", "G", "03", d="20260805", t="200100")]
    discs = [_dart("20260223900002", "20260223", "[기재정정]주요사항보고서(유상증자결정)", "B"),
             _dart("20260223900001", "20260223", "매출액또는손익구조30%(대규모법인은15%)이상변동")]
    d = _feed(news=news, discs=discs, classify_disc=lambda t: ("check", "x", 1, "") if "유상증자" in t else (None, None, 0, ""))
    ds = {it["id"]: it for it in d["items"] if it["type"] == "disc"}
    assert set(ds) == {"d:20260223900002", "d:20260223900001", "d:k" + news[2]["id"]}
    assert ds["d:20260223900002"]["t"] == "1430" and ds["d:20260223900001"]["t"] == "1749"
    assert ds["d:20260223900002"]["url"] == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260223900002"
    assert ds["d:20260223900002"]["cls"] == {"g": "check", "cat": "x", "w": 1, "desc": ""}
    krx = ds["d:k" + news[2]["id"]]
    assert krx["kind"] == "KRX" and krx["rcept"] is None and krx["url"] is None and krx["title"] == "정기주주총회결과"
    al = [it for it in d["items"] if it["type"] == "alert"]
    assert len(al) == 1 and al[0]["title"] == "[투자주의]투자경고종목 지정예고" and al[0]["id"].startswith("a:")
    assert d["counts"]["alert"] == 1 and d["counts"]["disc"] == 3


def test_listing_notice_and_market_alert_merge_with_dart_market_office_row():
    """KIS 상장 · 권리 안내(lc 03)는 거래소 공시로 DART 와 겹침을 지우고, 진짜 경보도 같은 날 시장본부가 DART 에 낸
    같은 안내가 있으면 DART 줄 하나로(시각만 빌린다). 회사가 낸 같은 제목 공시와는 합치지 않는다."""
    news = [row("가나광섬유(주) 권리락(유상증자)", "코스닥 공시", "G", "03", d="20260107", t="165300"),
            row("가나광섬유(주) 투자경고종목지정", "코스닥 공시", "G", "03", d="20260215", t="171000"),
            row("가나광섬유(주) 단기과열종목 지정", "코스닥 공시", "G", "03", d="20260301", t="180000")]
    discs = [_dart("20260107900001", "20260107", "권리락 (유상증자)", flr="코스닥시장본부"),
             _dart("20260215900004", "20260215", "투자경고종목지정", flr="코스닥시장본부"),
             _dart("20260301900001", "20260301", "단기과열종목지정")]                  # 회사 이름으로 낸 줄(flr 빈칸)
    d = _feed(news=news, discs=discs)
    by = {it["id"]: it for it in d["items"]}
    assert by["d:20260107900001"]["t"] == "1653" and by["d:20260215900004"]["t"] == "1710"
    al = [it for it in d["items"] if it["type"] == "alert"]
    assert [a["title"] for a in al] == ["단기과열종목 지정"] and by["d:20260301900001"]["t"] == ""
    assert d["counts"]["alert"] == 1 and d["counts"]["disc"] == 3
    assert not any(it["type"] == "disc" and it["kind"] == "KRX" for it in d["items"])


def test_disc_tone_contract_and_a001_folded_into_filing():
    discs = [_dart("20260616900001", "20260616", "단일판매ㆍ공급계약체결"),
             _dart("20260319000854", "20260319", "사업보고서 (2025.12)", "A001"),
             _dart("20260210900001", "20260210", "횡령ㆍ배임혐의발생")]
    filings = [{"stamp": "2025-12", "label": "사업보고서", "tag": "", "rcept": "20260319000854",
                "sections": [{"file": "01_표지.txt", "title": "【 대표이사 등의 확인 】", "norm": "대표이사 등의 확인", "bytes": 1},
                             {"file": "02_회사의 개요.txt", "title": "I. 회사의 개요", "norm": "회사의 개요", "bytes": 1},
                             {"file": "03_사업의 내용.txt", "title": "II. 사업의 내용", "norm": "사업의 내용", "bytes": 1}]},
               {"stamp": "2026-06", "label": "반기보고서", "tag": "[기재정정]", "rcept": "20260814000123", "sections": []},
               {"stamp": "2026-03", "label": "분기보고서", "tag": "", "rcept": "20260515000123",
                "sections": [{"file": "01_표지.txt", "norm": "대표이사 등의 확인"}, {"file": "02_회사의 개요.txt", "norm": "회사의 개요"}]}]
    ct = {"20260616900001": {"kind": "공사수주", "title": "광케이블 공급", "amount": 30e9, "revenue": 1e11, "pct": 30.0,
                             "party": "미국 고객", "region": "미국", "start": "2026-06-16", "end": "2026-12-31", "signed": "x"}}
    gists = {"20260319000854": [{"sec": "사업의 내용", "short": "사업", "tags": ["수주·계약"], "text": "북미 광케이블 …", "came": []}]}
    d = _feed(discs=discs, filings=filings, gists=gists, contracts=ct,
              classify_disc=lambda t: ("good", "대형수주", 3, "d") if "공급계약" in t else ("bad", "유동성 위험", 0, "") if "횡령" in t
              else (None, None, 0, ""))
    by = {it["id"]: it for it in d["items"]}
    assert "d:20260319000854" not in by and d["src"]["disc"]["n"] == 3          # 정기보고서와 같은 접수번호는 한 줄
    assert by["d:20260616900001"]["tone"] == 1 and by["d:20260210900001"]["tone"] == -1
    assert by["d:20260616900001"]["contract"]["pct"] == 30.0 and "signed" not in by["d:20260616900001"]["contract"]
    f = by["f:20260319000854"]
    assert f["type"] == "filing" and f["title"] == "사업보고서 (2025-12)" and f["file"] == "03_사업의 내용.txt"
    assert f["gist"] == [{"sec": "사업", "text": "북미 광케이블 …", "tags": ["수주·계약"]}] and f["first"] is False
    assert by["f:20260814000123"]["gist"] is None and by["f:20260814000123"]["tag"] == "[기재정정]"
    assert by["f:20260814000123"]["file"] is None and by["f:20260515000123"]["file"] == "02_회사의 개요.txt"   # 표지는 건너뜀
    assert d["counts"]["filing"] == 3


def test_filing_gist_empty_vs_missing_and_first():
    """지금 판 요약이 있는데 비었으면 [](첫 보고서 · 바뀐 것 없음 — 궤도 탭을 열어도 안 채워진다), 아예 없으면 None.
    글이 빈 항목(문구 손질)은 뺀다."""
    filings = [{"stamp": "2011-06", "label": "반기보고서", "rcept": "20110829000001", "sections": []},
               {"stamp": "2011-09", "label": "분기보고서", "rcept": "20111114000002", "sections": []},
               {"stamp": "2011-12", "label": "사업보고서", "rcept": "20120330000003", "sections": []}]
    gists = {"20110829000001": {"gist": [], "first": True},
             "20111114000002": {"gist": [{"sec": "주주에 관한 사항", "short": "주주", "text": "", "polish": True},
                                         {"sec": "사업의 내용", "short": "사업", "text": "", "tags": []}], "first": False}}
    by = {it["id"]: it for it in _feed(filings=filings, gists=gists)["items"]}
    assert by["f:20110829000001"]["gist"] == [] and by["f:20110829000001"]["first"] is True
    assert by["f:20111114000002"]["gist"] == [] and by["f:20111114000002"]["first"] is False
    assert by["f:20120330000003"]["gist"] is None and by["f:20120330000003"]["first"] is False


def test_disc_cls_extra_rules_and_soft_good(SRV):
    """호재.classify 가 못 잡는 제목은 이 탭 보탬 규칙으로, 제목만으론 방향을 모르는 '호재'(실적 · 배당 …)는 확인으로."""
    if SRV.GOOD is None:
        pytest.skip("호재.py 를 못 읽음")
    titles = {"20260101000001": "연결재무제표기준영업(잠정)실적(공정공시)",
              "20260101000002": "현금ㆍ현물배당결정",
              "20260101000003": "주요사항보고서(자기주식취득결정)",
              "20260101000004": "[기재정정]주식소각결정",
              "20260101000005": "전환사채(해외전환사채포함)발행후만기전사채취득",
              "20260101000006": "[기재정정]전환가액의조정",
              "20260101000007": "전환청구권행사",
              "20260101000008": "신주인수권행사가액의조정",
              "20260101000009": "소송등의판결ㆍ결정(일정금액 이상의 청구)",
              "20260101000010": "불성실공시법인지정예고",
              "20260101000011": "임원ㆍ주요주주특정증권등소유상황보고서",
              "20260101000012": "기업설명회(IR)개최(안내공시)"}
    discs = [_dart(rc, "20260101", t) for rc, t in titles.items()]
    by = {it["rcept"]: it["cls"] for it in _feed(discs=discs, classify_disc=SRV.GOOD.classify)["items"]}
    g = {rc: (c["g"], c["cat"]) for rc, c in by.items()}
    assert g["20260101000001"] == ("check", "실적 공시") and by["20260101000001"]["w"] == 2
    assert g["20260101000002"] == ("check", "배당확대") and g["20260101000011"] == ("check", "내부자 매수")
    assert g["20260101000003"] == ("good", "자사주매입")
    assert g["20260101000004"] == ("good", "자사주소각") and g["20260101000005"] == ("good", "메자닌 소각")
    assert g["20260101000006"] == ("bad", "희석") and g["20260101000007"] == ("bad", "희석") and g["20260101000008"] == ("bad", "희석")
    assert g["20260101000009"] == ("check", "소송 판결") and g["20260101000010"] == ("bad", "상장 위험")
    assert g["20260101000012"] == (None, None)
    its = {it["rcept"]: it for it in _feed(discs=discs, classify_disc=SRV.GOOD.classify)["items"]}
    assert its["20260101000001"]["tone"] == 0 and its["20260101000004"]["tone"] == 1 and its["20260101000006"]["tone"] == -1
    # 보탬 규칙은 호재.classify 가 이미 분류한 제목을 덮지 않는다
    d = _feed(discs=[_dart("20260101000013", "20260101", "전환청구권행사")], classify_disc=lambda t: ("check", "x", 1, ""))
    assert d["items"][0]["cls"]["g"] == "check"


def test_report_items():
    reps = [{"kind": "기업", "code": CO, "broker": "가상증권", "opinion": "NR", "tp": None, "tp_prev": None, "change": None,
             "title": "광섬유 판가 오름 효과", "lines": ["광섬유 판가 상승"], "urls": ["https://t.me/x/1", "https://example.com/r.pdf"],
             "date": "2026-07-13 18:10", "msg_url": "https://t.me/examplereport/1001", "brk_url": None, "price_at": 9000},
            {"kind": "기업", "code": CO, "broker": "나다증권", "tp": 20000, "tp_prev": 15000, "change": "상향",
             "title": "목표가 상향", "date": "2026-07-13 08:00", "msg_url": "https://t.me/examplereport/1001"}]
    d = _feed(reports=reps)
    its = [it for it in d["items"] if it["type"] == "report"]
    assert [it["id"] for it in its] == ["r:examplereport/1001", "r:examplereport/1001~2"]
    a = its[0]
    assert (a["d"], a["t"], a["src"], a["url"], a["price_at"], a["tone"]) == ("20260713", "1810", "가상증권", "https://example.com/r.pdf", 9000, 0)
    for k in ("broker", "opinion", "tp", "tp_prev", "change", "kind", "lines", "est", "risks", "concl", "sections", "msg_url", "brk_url"):
        assert k in a
    assert its[1]["tone"] == 1 and d["src"]["reports"] == {"n": 2, "from": "20260713", "slim": 0}


# ---------------------------------------------------------------- 2.3 주가
def bdays(n, start=dt.date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += dt.timedelta(days=1)
    return out


def test_adjusted_split_like_record_scoring():
    ds = bdays(12)
    px = {d: (50000.0 if i < 9 else 1000.0) for i, d in enumerate(ds)}       # 1:50 분할
    px["bad"] = 1
    px[ds[3]] = "x"
    s = N.adjusted(px)
    assert [d for d, _ in s] == [d for d in ds if d != ds[3]]
    assert all(abs(c - 1000.0) < 1e-6 for _, c in s)


def test_reaction_trading_day_after_close_and_d5():
    ds = bdays(12)                                   # 2026-01-05(월)부터
    s = [(d, 100.0 + i) for i, d in enumerate(ds)]
    mkt = {d: 1.0 for d in ds}
    r = N.reaction(s, "20260110", mkt=mkt)           # 토요일 → 월요일 반응
    assert r["day"] == "20260112" and r["chg"] == round((105 / 104 - 1) * 100, 2) and r["mkt"] == 1.0
    assert r["d5"] == round((109 / 104 - 1) * 100, 2) and r["d5m"] == round((1.01 ** 5 - 1) * 100, 2)
    assert "from" not in r and "timed" not in r
    assert N.reaction(s, "20260112", after_close=True)["day"] == "20260113"
    assert N.reaction(s, "20260112")["day"] == "20260112"
    assert N.reaction(s, ds[-1])["d5"] is None and N.reaction(s, ds[-1])["day"] == ds[-1]
    assert N.reaction(s, ds[-1], after_close=True) is None          # 아직 반응일 없음
    assert N.reaction(s, "20251201") is None                         # 반응일이 달력 10일 넘게 멂(상장 전)
    assert N.reaction(s, ds[0])["chg"] is None
    assert N.reaction(s, "20260112", mkt={})["d5m"] is None
    assert N.reaction([], "20260112") is None


def test_reaction_untimed_spans_filing_day_and_next():
    """시각 모르는 소식이 거래일에 나왔으면 그 앞 종가 → 다음 거래일 종가(이틀) — 장중 · 장 마감 뒤 둘 다 덮는다."""
    ds = bdays(12)
    s = [(d, 100.0 + i) for i, d in enumerate(ds)]
    mkt = {d: 1.0 for d in ds}
    r = N.reaction(s, "20260112", mkt=mkt, untimed=True)          # 월요일(ds[5]) 공시 · 시각 모름
    assert r["from"] == "20260112" and r["day"] == "20260113" and r["timed"] is False
    assert r["chg"] == round((106 / 104 - 1) * 100, 2) and r["mkt"] == round((1.01 ** 2 - 1) * 100, 2)
    assert r["d5"] == round((110 / 104 - 1) * 100, 2) and r["d5m"] == round((1.01 ** 6 - 1) * 100, 2)
    w = N.reaction(s, "20260110", mkt=mkt, untimed=True)          # 토요일 — 다음 거래일 하루(그 전에 나왔다)
    assert w["day"] == "20260112" and "from" not in w and w["chg"] == round((105 / 104 - 1) * 100, 2)
    assert N.reaction(s, ds[-1], untimed=True) is None             # 다음 거래일이 아직 없다
    assert N.reaction(s, ds[-2], untimed=True)["day"] == ds[-1]


def test_feed_untimed_disc_and_filing_span_two_days_timed_disc_next_day():
    ds = bdays(30, dt.date(2026, 3, 2))
    series = [(d, 1000.0 + 10 * i) for i, d in enumerate(ds)]
    day0 = ds[10]
    news = [row("가나광섬유(주) 감사보고서제출", "코스닥 공시", "G", "01", d=day0, t="160500")]
    discs = [_dart(day0 + "900001", day0, "감사보고서제출"), _dart(day0 + "900002", day0, "기업설명회(IR)개최(안내공시)")]
    filings = [{"stamp": "2025-12", "label": "사업보고서", "rcept": day0 + "000854", "sections": []}]
    by = {it["id"]: it for it in _feed(news=news, discs=discs, filings=filings, series=series)["items"]}
    timed = by["d:" + day0 + "900001"]
    assert timed["t"] == "1605" and timed["re"]["day"] == ds[11] and "from" not in timed["re"]
    assert timed["re"]["chg"] == round((1110 / 1100 - 1) * 100, 2)
    for k in ("d:" + day0 + "900002", "f:" + day0 + "000854"):
        re_ = by[k]["re"]
        assert (re_["from"], re_["day"], re_["timed"]) == (day0, ds[11], False)
        assert re_["chg"] == round((1110 / 1090 - 1) * 100, 2)


def test_day_moves():
    s = [("20260105", 100.0), ("20260106", 110.0)]
    assert N.day_moves(s, {"20260106": 0.4567}) == {"20260105": {"chg": None, "mkt": None},
                                                    "20260106": {"chg": 10.0, "mkt": 0.46}}


def test_build_mkt_med_median_min_sample_and_since():
    ds = bdays(9)
    table = {"U%02d" % k: {d: 100.0 * (1 + 0.01 * k) ** i for i, d in enumerate(ds)} for k in range(20)}   # 종목 k 는 날마다 +k%
    table["U00"][ds[8]] = None
    table["U01"][ds[8]] = None
    table["SPLIT"] = {d: (5000.0 if i < 8 else 100.0) for i, d in enumerate(ds)}   # 1:50 분할 — 보정 뒤 0%
    m = N.build_mkt_med(lambda c: table.get(c), sorted(table) + ["NONE"], ds[7])
    assert m == {ds[7]: 9.0}                                         # 21종목 [0,0,1..19] 중앙 · ds[8] 은 19종목 → 뺌 · since 앞은 뺌
    assert N.build_mkt_med(lambda c: table.get(c), sorted(table), ds[8]) == {}


# ---------------------------------------------------------------- 2.4 낱말 잇기
VOCAB = {"reports": [{"stamp": "2022-12", "label": "사업보고서", "rcept": "20230315000111"},
                     {"stamp": "2023-06", "label": "반기보고서", "rcept": "20230814000222"},
                     {"stamp": "2024-12", "label": "사업보고서", "rcept": "20250320000333"}],
         "tracks": {"데이터센터": {"first": 0, "take": 1, "now": "양산·출시", "snip_first": " 데이터센터향  광케이블 공급 "},
                    "HBM": {"first": 1, "take": None, "now": "확대", "snip_first": "HBM 양산"},
                    "HBM4": {"first": 2, "take": 2, "now": None, "snip_first": "HBM4 샘플"},
                    "광학솔루션": {"first": 2, "now": None, "snip_first": "광학솔루션 사업",
                              "renamed_from": {"t": "광학통신솔루션", "last": 1, "first": 0, "peak": 3.0}},
                    "광학통신솔루션": {"first": 0, "now": None, "snip_first": "옛 이름", "renamed_to": {"t": "광학솔루션", "first": 2}},
                    "디": {"first": 0, "snip_first": "x"}, "찌꺼기": {"first": 0, "snip_first": ""}}}


def test_vocab_links_fields_and_residue():
    ls = {lk["term"]: lk for lk in N.vocab_links(VOCAB)}
    assert set(ls) == {"데이터센터", "HBM", "HBM4", "광학솔루션"}
    assert ls["데이터센터"] == {"term": "데이터센터", "first": "20230315", "first_label": "2022-12 사업보고서", "from_start": True,
                           "take": "20230814", "now": "양산·출시", "snip": "데이터센터향 광케이블 공급"}
    assert ls["HBM"]["from_start"] is False                                # 첫 보고서(자료 처음)에 있으면 '언제부터'를 모른다
    assert ls["광학솔루션"]["was"] == "광학통신솔루션" and ls["HBM"]["take"] is None
    assert N.vocab_links(None) == [] and N.vocab_links({}) == []


def test_match_terms_spacing_boundary_longest_and_rename():
    links = N.vocab_links(VOCAB)
    assert N.match_terms("美 데이터 센터에 광케이블", links) == ["데이터센터"]
    assert N.match_terms("HBM4 양산 임박…HBM 공급 부족", links) == ["HBM4", "HBM"]
    assert N.match_terms("XHBM 그리고 HBMX", links) == []
    assert N.match_terms("광학통신솔루션 부문 매각", links) == ["광학솔루션"]
    assert N.match_terms("", links) == [] and N.match_terms("데이터센터", []) == []


def test_hot_words_counts_items_and_links_vocab():
    links = N.vocab_links(VOCAB)
    its = [{"type": "news", "k": "art", "hide": False, "d": "20261001", "title": "가나광섬유, 데이터센터향 광케이블 수주 - 가상증권"},
           {"type": "news", "k": "mention", "hide": False, "d": "20261002", "title": "광통신株 강세…데이터센터 데이터센터 수요"},
           {"type": "report", "hide": False, "d": "20261003", "title": "데이터센터 광케이블 [특징주]"},
           {"type": "news", "k": "info_list", "hide": True, "d": "20261003", "title": "데이터센터 광케이블"},
           {"type": "disc", "hide": False, "d": "20261003", "title": "데이터센터 광케이블"},
           {"type": "news", "k": "art", "hide": False, "d": "20250101", "title": "데이터센터 광케이블"},
           {"type": "news", "k": "art", "hide": False, "d": "20261004", "title": "광통신주 355억 2분기 52주 신고가 상승"}]
    h = N.hot_words(its, "20260901", NAME, links)
    assert h[0] == {"w": "데이터센터", "n": 3, "vocab": links[0]}
    assert {"w": "광케이블", "n": 2, "vocab": None} in h
    assert {"w": "광통신", "n": 2, "vocab": None} in h                    # '株' · '주' 꼬리 정리, 회사 이름 조각은 둔다
    ws = {x["w"] for x in h}
    assert not ws & {"가나광섬유", "가상증권", "355억", "2분기", "52주", "신고가", "상승", "특징주", "수주"}


def test_hot_words_skip_alias_generic_and_stack_tails(monkeypatch):
    monkeypatch.setitem(N.ALIAS, CO2, ("다전",))
    its = [{"type": "news", "k": "art", "hide": False, "d": "20261001", "title": "다전 성과급 협력 광통신주도"},
           {"type": "news", "k": "art", "hide": False, "d": "20261002", "title": "다전닉스 다전 성과급 협력 광통신"}]
    ws = {x["w"]: x["n"] for x in N.hot_words(its, "20260901", NAME2, [], code=CO2)}
    assert ws == {"성과급": 2, "광통신": 2}                                 # 별칭 · 별칭 붙은 말 · '협력' 은 빼고, '광통신주도' → 광통신
    assert "다전" in {x["w"] for x in N.hot_words(its, "20260901", NAME2, [])}   # 코드 없으면 별칭을 모른다


# ---------------------------------------------------------------- 2.5 · 2.6 응답 꼴
def test_build_feed_shape_and_days():
    ds = bdays(300, dt.date(2025, 9, 1))
    series = [(d, 1000.0 + i) for i, d in enumerate(ds)]
    news = [row("가나광섬유, 美 데이터센터 광케이블 수주", d=ds[-3], t="170000"),
            row("인기검색 20종목", "인포스탁", "7", "01", d=ds[-3])]
    d = N.build_feed(CO, NAME, today=ds[-1], news=news,
                     news_meta={"at": "2026-10-11T09:00:00+09:00", "complete": True, "capped": False,
                                "oldest": "2025092509082812345"},
                     series=series, mkt={ds[-2]: 0.5}, links=N.vocab_links(VOCAB), discs=[])
    assert set(d) == {"v", "code", "name", "built", "px", "src", "counts", "hot", "days", "vocab", "items"}
    assert d["v"] == N.FEED_V == 2 and d["code"] == CO and len(d["built"]) == 19
    assert d["px"]["last"] == 1299.0 and d["px"]["date"] == ds[-1] and d["px"]["chg"] == round((1299 / 1298 - 1) * 100, 2)
    assert d["px"]["series"][-1] == [ds[-1], 1299.0] and d["px"]["series"][0][0] >= "20251010"
    assert d["src"]["news"] == {"ok": True, "at": "2026-10-11T09:00", "complete": True, "capped": False, "oldest": "20250925",
                                "n": 2, "note": "", "shown": 1, "cut": 0, "cut_hidden": 0}
    assert d["src"]["disc"] == {"n": 0, "from": None, "index": "ready", "cut": 0} and d["src"]["filings"] == {"n": 0}
    it = next(x for x in d["items"] if x["type"] == "news" and not x["hide"])
    for k in ("id", "type", "d", "t", "title", "src", "hide", "n", "tone", "terms", "re", "k", "c1", "search"):
        assert k in it
    assert it["id"].startswith("n:") and it["t"] == "1700" and it["terms"] == ["데이터센터"]
    assert it["re"]["day"] == ds[-2] and it["re"]["mkt"] == 0.5            # 17:00 기사 → 다음 거래일 반응
    assert d["vocab"] == {"데이터센터": N.vocab_links(VOCAB)[0]}
    y1 = (dt.date(int(ds[-1][:4]), int(ds[-1][4:6]), int(ds[-1][6:])) - dt.timedelta(days=365)).strftime("%Y%m%d")
    assert sorted(d["days"]) == [dd for dd in ds if dd >= y1]                     # 최근 1년 거래일 전부(소식 날도 그 안)
    assert d["days"][ds[-3]]["news"] == 1 and d["days"][ds[-2]] == {"chg": round((1298 / 1297 - 1) * 100, 2), "mkt": 0.5,
                                                                      "news": 0, "report": 0, "disc": 0, "filing": 0, "alert": 0}
    assert d["counts"] == {"news": 1, "report": 0, "disc": 0, "filing": 0, "alert": 0, "hidden": 1}
    json.dumps(d, ensure_ascii=False)


def test_build_feed_without_news_or_index():
    d = _feed(news=None, discs=None)
    assert d["src"]["news"]["ok"] is False and d["src"]["news"]["note"]
    assert d["src"]["disc"]["index"] == "missing" and d["px"] is None and d["items"] == []
    assert d["counts"] == {"news": 0, "report": 0, "disc": 0, "filing": 0, "alert": 0, "hidden": 0}


def test_items_newest_first_with_type_rank():
    news = [row("가나광섬유 기사", d="20261002", t="090000")]
    discs = [_dart("20261002900001", "20261002", "기업설명회(IR)개최(안내공시)"), _dart("20261005900001", "20261005", "x")]
    d = _feed(news=news, discs=discs)
    assert [it["id"][:2] for it in d["items"]] == ["d:", "n:", "d:"]
    assert d["items"][0]["d"] == "20261005"


# ---------------------------------------------------------------- 3. 서버 story_view 배선(서버를 띄우지 않고 모듈만)
@pytest.fixture(scope="module")
def SRV():
    sp = ilu.spec_from_file_location("서버_내러티브_시험", os.path.join(BASE, "서버.py"))
    m = ilu.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


@pytest.fixture
def srv(SRV, monkeypatch, tmp_path):
    co = {"code": CO, "name": NAME, "reports": [{"stamp": "2026-06", "label": "반기보고서", "tag": "",
                                                "rcept": "20260814000123", "sections": []}]}
    monkeypatch.setattr(SRV, "company_by_code", lambda c: co if c == CO else None)
    monkeypatch.setattr(SRV, "STORY_DIR", str(tmp_path / "story"))
    monkeypatch.setattr(SRV, "STORY_DISC_DIR", str(tmp_path / "공시목록"))
    monkeypatch.setattr(SRV, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(SRV, "TECH_DIR", str(tmp_path / "Tech"))
    monkeypatch.setattr(SRV, "STORY", {"running": False, "code": None, "step": "", "want": {}, "err": {}, "memo": {}})
    monkeypatch.setattr(SRV, "STORY_NEWS", {"running": False, "code": None, "queue": {}, "tried": {}, "sup": (0.0, False)})
    monkeypatch.setattr(SRV, "STORY_MKT", {"building": False, "med": {}, "built": "2099-01-01 07:00", "mtime": 0})
    monkeypatch.setattr(SRV, "STORY_DISC", {"building": False, "checked": time.time(), "error": None})
    monkeypatch.setattr(SRV, "_story_mkt", lambda: SRV.STORY_MKT["med"])
    monkeypatch.setattr(SRV, "_story_mkt_stale", lambda built: False)
    monkeypatch.setattr(SRV, "_rep_rows", lambda: {"by_code": {CO: [{"date": "2026-07-13 18:10", "title": "r", "broker": "b",
                                                                     "msg_url": "https://t.me/c/1"}]}})
    monkeypatch.setattr(SRV, "_px_file", lambda c: {"20261006": 100.0, "20261007": 101.0})
    monkeypatch.setattr(SRV, "_tech_supports", lambda flag: False)
    (tmp_path / "공시목록").mkdir()
    return SRV


def _wait(SRV, sec=20):
    t = time.time()
    while (SRV.STORY["running"] or SRV.STORY_NEWS["running"]) and time.time() - t < sec:
        time.sleep(0.05)


def test_story_view_pending_then_built_then_fresh(srv):
    assert srv.story_view("999999") is None
    p = srv.story_view(CO)
    assert p["pending"] is True and "step" in p and p["news_running"] is False
    _wait(srv)
    d = srv.story_view(CO)
    assert d.get("pending") is None and d["stale"] is False and d["news_running"] is False
    assert "sig" not in d and d["code"] == CO and d["counts"]["report"] == 1 and d["counts"]["filing"] == 1
    assert d["src"]["news"]["ok"] is False and d["src"]["news"]["note"]            # 뉴스가 없어도 나머지는 그린다
    assert d["src"]["disc"]["index"] == "ready"                                    # 빈 공시목록 → 빈 색인
    assert os.path.exists(os.path.join(srv.STORY_DIR, CO + ".json"))
    assert srv.story_view(CO)["built"] == d["built"]                               # 같은 sig → 다시 안 만든다


def test_story_view_stale_while_rebuilding(srv, monkeypatch):
    srv.story_view(CO)
    _wait(srv)
    first = srv.story_view(CO)["built"]
    gate = threading.Event()
    real = srv.NAR.build_feed
    monkeypatch.setattr(srv.NAR, "build_feed", lambda *a, **kw: (gate.wait(5), real(*a, **kw))[1])
    os.makedirs(os.path.join(srv.CACHE_DIR, "vocab"), exist_ok=True)
    with open(os.path.join(srv.CACHE_DIR, "vocab", CO + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"reports": [], "tracks": {}}, fh)                               # vocab 파일 시각 → sig 바뀜
    d = srv.story_view(CO)
    assert d["stale"] is True and d["built"] == first
    gate.set()
    _wait(srv)
    d2 = srv.story_view(CO)
    assert d2["stale"] is False and d2["built"] >= first


def test_story_view_error_not_retried_in_loop(srv, monkeypatch):
    calls = []

    def boom(*a, **kw):
        calls.append(1)
        raise RuntimeError("시험 실패")
    monkeypatch.setattr(srv.NAR, "build_feed", boom)
    srv.story_view(CO)
    _wait(srv)
    d = srv.story_view(CO)
    assert d == {"error": "RuntimeError: 시험 실패", "news_running": False}
    _wait(srv)
    srv.story_view(CO)
    _wait(srv)
    assert len(calls) == 1


def test_story_view_failed_rebuild_keeps_payload(srv, monkeypatch):
    """있던 payload 가 있으면 다시 만들기 실패는 build_error 로 — 'error' 를 실으면 화면이 payload 를 버린다."""
    srv.story_view(CO)
    _wait(srv)
    first = srv.story_view(CO)["built"]

    def boom(*a, **kw):
        raise RuntimeError("시험 실패")
    monkeypatch.setattr(srv.NAR, "build_feed", boom)
    os.makedirs(os.path.join(srv.CACHE_DIR, "vocab"), exist_ok=True)
    with open(os.path.join(srv.CACHE_DIR, "vocab", CO + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"reports": [], "tracks": {}}, fh)
    srv.story_view(CO)
    _wait(srv)
    d = srv.story_view(CO)
    assert "error" not in d and d["build_error"] == "RuntimeError: 시험 실패"
    assert d["built"] == first and d["items"] is not None and d["stale"] is False


def test_story_sig_sees_older_period_amendment_and_contract_cache(srv, tmp_path):
    c = {"code": CO, "name": NAME, "reports": [{"stamp": "2024-12", "rcept": "20250320000001"},
                                               {"stamp": "2025-12", "rcept": "20260319000001"}]}
    s0 = srv._story_sig(c)
    c2 = dict(c, reports=[{"stamp": "2024-12", "rcept": "20250320000001"}, {"stamp": "2024-12", "rcept": "20261001000009"},
                          {"stamp": "2025-12", "rcept": "20260319000001"}])          # 옛 기간 [기재정정] — 기간순이라 [-1] 은 그대로
    assert srv._story_sig(c2) != s0
    os.makedirs(os.path.join(srv.CACHE_DIR, "시너지", "계약"), exist_ok=True)
    s1 = srv._story_sig(c)
    time.sleep(1.1)
    with open(os.path.join(srv.CACHE_DIR, "시너지", "계약", "20260616900001.json"), "w", encoding="utf-8") as fh:
        json.dump({"kind": "x"}, fh)
    assert srv._story_sig(c) != s1                                                 # 계약 칸이 새로 생기면 다시 만든다


def test_story_gists_keeps_empty_current_gist_and_first(srv):
    c = {"code": CO, "reports": [{"rcept": "20110829000001"}, {"rcept": "20111114000002"}, {"rcept": "20120330000003"}]}
    os.makedirs(os.path.join(srv.CACHE_DIR, "brief", CO), exist_ok=True)
    for rc, b in (("20110829000001", {"first": True, "gist_v": srv.GIST_V, "gist": []}),
                  ("20111114000002", {"first": False, "gist_v": srv.GIST_V, "gist": [{"text": "x"}]}),
                  ("20120330000003", {"first": False, "gist_v": srv.GIST_V - 1, "gist": [{"text": "옛 판"}]})):
        with open(srv.brief_path(CO, rc), "w", encoding="utf-8") as fh:
            json.dump(b, fh)
    assert srv._story_gists(c) == {"20110829000001": {"gist": [], "first": True},
                                   "20111114000002": {"gist": [{"text": "x"}], "first": False}}


def test_news_kick_once_per_ttl_and_note(srv, monkeypatch):
    runs = []
    monkeypatch.setattr(srv, "_story_news_ok", lambda: True)
    monkeypatch.setattr(srv, "TECH_PY", __file__)

    class R:
        returncode, stdout = 1, "한국투자증권 설정 없음: 시험\n".encode("utf-8")
    monkeypatch.setattr(srv.subprocess, "run", lambda cmd, **kw: (runs.append((cmd, kw)), R())[1])
    assert srv._story_news_kick(CO) is True
    _wait(srv)
    cmd, kw = runs[0]
    assert cmd[1:] == ["-m", "chart_screener", "news", "--codes", CO, "--pages", "60", "--budget", "100"]
    assert kw["cwd"] == srv.TECH_DIR and kw["timeout"] == 180 and kw["env"]["PYTHONIOENCODING"] == "utf-8"
    assert srv._story_news_kick(CO) is False                          # 실패 뒤 30분은 다시 안 띄운다
    assert srv._story_news_note(CO, False, False) == "한국투자증권 설정 없음: 시험"
    srv.STORY_NEWS["tried"][CO] = (time.time() - 61, 1, "x")
    assert srv._story_news_kick(CO, refresh=True) is True             # refresh 는 1분 뒤면
    _wait(srv)
    assert len(runs) == 2


def test_news_queue_most_recent_first_and_drops_left_companies(srv, monkeypatch):
    """뉴스 받기 차례 — 가장 최근에 물은 회사부터, STORY_WANT_TTL 동안 다시 안 물은(화면을 떠난) 회사는 뺀다."""
    runs, gate = [], threading.Event()
    monkeypatch.setattr(srv, "_story_news_ok", lambda: True)
    monkeypatch.setattr(srv, "TECH_PY", __file__)

    class R:
        returncode, stdout = 0, b""

    def run(cmd, **kw):
        runs.append(cmd[cmd.index("--codes") + 1])
        if len(runs) == 1:
            gate.wait(5)
        return R()
    monkeypatch.setattr(srv.subprocess, "run", run)
    assert srv._story_news_kick("A00000") is True
    t = time.time()
    while not runs and time.time() - t < 5:
        time.sleep(0.02)
    for c in ("A00001", "A00002", "A00003"):
        assert srv._story_news_kick(c) is True
        time.sleep(0.02)
    srv.STORY_NEWS["queue"]["A00001"] = time.time() - srv.STORY_WANT_TTL - 1   # 떠난 회사
    assert srv._story_news_kick("A00002") is True                             # 다시 물음 → 가장 최근
    assert set(srv.STORY_NEWS["queue"]) == {"A00001", "A00002", "A00003"}
    gate.set()
    _wait(srv)
    assert runs == ["A00000", "A00002", "A00003"]
    assert "A00001" not in srv.STORY_NEWS["tried"] and srv.STORY_NEWS["queue"] == {}
    assert srv._story_news_kick("A00001") is True                             # 다시 오면 다시 줄 선다
    _wait(srv)
    assert runs[-1] == "A00001"


def test_rep_rows_single_flight(SRV, monkeypatch):
    """리포트 다시 읽기(콜드 74초 · 338MB)는 한 번에 하나 — 뒤에 온 호출은 기다렸다가 그 결과를 쓴다."""
    calls, gate = [], threading.Event()

    class FakeRep:
        @staticmethod
        def store_sig():
            return "sig-1"

        @staticmethod
        def build(names, codes, px_of=None):
            calls.append(1)
            gate.wait(5)
            return [{"code": CO, "title": "r"}]
    monkeypatch.setattr(SRV, "REP", FakeRep)
    monkeypatch.setattr(SRV, "_REP", {"sig": None, "rows": [], "by_code": {}})
    out = []
    ths = [threading.Thread(target=lambda: out.append(SRV._rep_rows())) for _ in range(3)]
    for th in ths:
        th.start()
    time.sleep(0.3)
    gate.set()
    for th in ths:
        th.join(5)
    assert len(calls) == 1 and len(out) == 3 and all(o["by_code"] == {CO: [{"code": CO, "title": "r"}]} for o in out)
