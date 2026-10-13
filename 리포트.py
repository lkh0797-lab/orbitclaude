# -*- coding: utf-8 -*-
"""
증권사 리포트 — 텔레그램 증권사 채널(내 계정으로 구독한 공개 채널)의 글을 받아 기업 · 산업 리포트로 정리한다 (2026-10-04).

  · 받기: Telethon 으로 내 계정에 로그인해, 구독 중인 채널 가운데 증권사 · 리서치 채널만 읽는다.
          채널을 고르는 법 — .env 의 TELEGRAM_CHANNELS(쉼표로 @이름 · 채널 제목)가 있으면 그것만,
          없으면 제목에 증권사 이름 · '리서치' · 'Research' 가 든 구독 채널 전부.
  · 읽기: 글 하나를 '항목'으로 나눠(하루치 요약 글에는 종목이 여럿) 항목마다
          증권사 · 종목(6자리 코드 또는 수집한 회사 이름) · 투자의견 · 목표주가(이전 → 새) · 상향/하향 · 제목 · 요약 줄 · 링크를 뽑는다.
          종목이 없고 산업 낱말이 있으면 산업 리포트.
  · 쌓기: .cache/리포트/YYYY-MM.jsonl (글 원문 앞부분도 같이 — 읽는 규칙을 고치면 다시 읽는다), 채널별 마지막 글 번호는 _state.json.

비밀값: TELEGRAM_API_ID · TELEGRAM_API_HASH 는 .env 에만(git 에 올리지 않는다). 출력 · 로그에 찍지 않는다.
로그인 세션 파일은 내 계정 전체 권한이라 구글 드라이브(이 폴더) 밖 %LOCALAPPDATA%\\기업추적\\ 에 둔다.
처음 한 번은 사람이 터미널에서 `python 도구/텔레그램_로그인.py` 로 전화번호 · 인증번호를 넣어 로그인한다.
"""
import os
import re
import json
import time
import bisect
import statistics
import datetime as dt

BASE = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(BASE, ".cache", "리포트")
STATE_PATH = os.path.join(STORE_DIR, "_state.json")
SESSION_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "기업추적")
SESSION = os.path.join(SESSION_DIR, "telegram")          # Telethon 이 .session 을 붙인다
RULE_V = 10                                              # 읽는 규칙이 바뀌면 올린다 — 쌓아 둔 원문을 다시 읽는다. 10: 목표가 단위(만원) · 낱말 경계 · 다른 회사 줄 · 주가 대비 상한(2026-10-13)

BROKERS = [
    ("미래에셋증권", r"미래에셋"), ("삼성증권", r"삼성증권|SAMSUNG\s*SEC|삼성\s*리서치|\[SAMSUNG\]"), ("한국투자증권", r"한국투자|한투증권|KIS\b"),
    ("NH투자증권", r"NH투자|NH\s*리서치|NH증권"), ("KB증권", r"KB증권|KB\s*리서치"), ("키움증권", r"키움"), ("신한투자증권", r"신한투자|신한금융투자|신한\s*리서치|신한생각"),
    ("하나증권", r"하나증권|하나금융투자|하나\s*리서치"), ("메리츠증권", r"메리츠"), ("대신증권", r"대신증권|대신\s*리서치"), ("유안타증권", r"유안타"),
    ("교보증권", r"교보증권"), ("IBK투자증권", r"IBK투자|IBK\s*리서치"), ("iM증권", r"iM증권|하이투자"), ("DB증권", r"DB금융투자|DB증권"),
    ("SK증권", r"SK증권"), ("유진투자증권", r"유진투자"), ("LS증권", r"LS증권|이베스트"), ("한화투자증권", r"한화투자"), ("현대차증권", r"현대차증권"),
    ("BNK투자증권", r"BNK투자"), ("상상인증권", r"상상인"), ("다올투자증권", r"다올투자"), ("한양증권", r"한양증권"), ("부국증권", r"부국증권"),
    ("신영증권", r"신영증권"), ("케이프투자증권", r"케이프"), ("흥국증권", r"흥국증권"), ("DS투자증권", r"DS투자"), ("리딩투자증권", r"리딩투자"),
    ("CLSA", r"CLSA"), ("JP모건", r"JP\s*Morgan|JP모건"), ("모건스탠리", r"Morgan\s*Stanley|모건스탠리"), ("골드만삭스", r"Goldman|골드만"),
]
BROKER_RX = [(n, re.compile(rx, re.I)) for n, rx in BROKERS]
CHANNEL_HINT = re.compile(r"증권|리서치|Research|리포트|Report|투자전략|애널리스트", re.I)
# 증권사 이름 없이 시리즈 이름만 적힌 머리('[IBKS Daily]' · '[HANA US Weekly]') · 채널 제목('대신 전략. 돌직구') — 본문에는 쓰지 않는다('~ 대신 전략을' 같은 말)
SERIES = [(re.compile(rx), n) for rx, n in [
    (r"\bIBKS\b", "IBK투자증권"), (r"\bDS\s+(?:Defense|시황)", "DS투자증권"),
    (r"(?:HANA|Hana)\s+(?:US|China|Macro|Global|Strategy|Japan)|하나\s*채권|Wedbush\s*X\s*HANA", "하나증권"), (r"대신\s*전략", "대신증권"),
]]


def series_broker(s):
    for rx, n in SERIES:
        if rx.search(s or ""):
            return n
    return None

OPINION = re.compile(r"(?<![A-Za-z])(Strong\s*Buy|Trading\s*Buy|Buy|Outperform|Overweight|Hold|Neutral|Marketperform|Market\s*Perform|"
                     r"Underperform|Underweight|Reduce|Sell|Not\s*Rated|NR)(?![A-Za-z])|(?<![가-힣])(매수|중립|매도)(?![가-힣])", re.I)   # '순매수' · '매수세' 는 의견이 아니다
OP_NORM = [("Buy", r"strong\s*buy|^buy$|매수|outperform|overweight"), ("Trading Buy", r"trading\s*buy"), ("Hold", r"hold|중립|neutral|market\s*perform|marketperform"),
           ("Sell", r"sell|매도|underperform|underweight|reduce"), ("NR", r"not\s*rated|^nr$")]
NUM = r"(\d{1,3}(?:,\d{3})+|\d{4,7})"
# 목표가 숫자(세 그룹: 원 · 만원 · 천원) — '1,300,000원' · '130만원' · '4.5만원' · '1,300천원'. 뒤에 년 · 대 · 개 · % 가 붙은 수('2028년' · '머신 1,610대')는 목표가가 아니다
TPNUM = (r"(?:(\d{1,3}(?:,\d{3})+|\d{4,7})(?![\d,.])(?!\s*(?:년|대|개|명|%|천|만|억|조|달러|\$|bp|배))"
         r"|(\d{1,4}(?:\.\d{1,2})?)\s*만\s*원?|(\d{1,3}(?:,\d{3})?)\s*천\s*원)")
# 'TP' 는 낱말로만 — 'STP0404(에이즈)' 의 TP 가 아니다
TP_HEAD = r"(?<![A-Za-z0-9])(?:목표\s*주?\s*가|적정\s*주가|TP|T\.P\.?|Target\s*Price|목표가)(?![A-Za-z])"
TP_RX = re.compile(TP_HEAD + r"\s*(?:\(\s*원\s*\))?\s*[:：]?\s*(?:₩|KRW\s*)?" + TPNUM + r"\s*(?:원|KRW)?", re.I)
TP_MOVE = re.compile(TPNUM + r"\s*원?\s*(?:→|->|⇒|에서)\s*" + TPNUM + r"\s*원?")
TP_BAND = (0.2, 5.0)        # 목표가 ÷ 주가(카드 현재가 · 없으면 그날 종가) 가 이 밖이면 다른 종목 목표가 · 자릿수 오류 · 분할 전 값 — 비운다(tp_raw 에 남김). 통신장비 담당의 4~5배 목표가는 안
OUTLIER_X = 3.0             # 증권사별 최신 목표가 중앙값의 3배 밖(⅓ 아래)은 평균에서 뺀다(3곳 이상일 때)
CHANGE = re.compile(r"(상향|하향|유지|신규|커버리지\s*개시|Initiat|Upgrade|Downgrade|Maintain)", re.I)
CODE_RX = re.compile(r"(?<![\d])A?(\d{6})(?![\d])")
URL_RX = re.compile(r"https?://\S+")
INDUSTRY = re.compile(r"반도체|디스플레이|2차\s*전지|이차전지|배터리|자동차|조선|해운|철강|화학|정유|건설|기계|방산|원전|전력|유틸리티|통신|인터넷|게임|엔터|미디어|"
                      r"화장품|음식료|유통|은행|보험|증권|지주|제약|바이오|헬스케어|의료기기|항공|운송|소프트웨어|(?-i:(?<![A-Za-z])AI(?![A-Za-z]))|로봇|우주|섬유|의류|"   # 'Chain' · 'Taiwan' 속 ai 는 아니다
                      r"산업|섹터|Sector|Industry|업종|전략|매크로|Macro|시황|채권|퀀트", re.I)


def _norm_op(s):
    s = (s or "").strip()
    for name, rx in OP_NORM:
        if re.search(rx, s, re.I):
            return name
    return s or None


def _num(s):
    try:
        return int(s.replace(",", ""))
    except Exception:
        return None


def _tp_val(m, base=0):
    """TPNUM 짝(세 그룹: 원 · 만원 · 천원) → 원 단위 정수. base = 짝의 첫 그룹 번호 − 1 (TP_MOVE 의 뒤 짝은 3)."""
    a, b, c = m.group(base + 1), m.group(base + 2), m.group(base + 3)
    if a:
        return _num(a)
    if b:
        try:
            return int(round(float(b) * 10000))
        except ValueError:
            return None
    if c:
        v = _num(c)
        return v * 1000 if v else None
    return None


def _line_of(text, pos):
    """pos 가 든 줄과 그 줄의 시작 위치."""
    a = text.rfind("\n", 0, pos) + 1
    b = text.find("\n", pos)
    return text[a:b if b >= 0 else len(text)], a


_SUBJ_TAIL = re.compile(r"\s*\(\s*(?:A?\d{6}|[A-Za-z]{2,}|매수|중립|매도|TP|목표)")      # '우리금융(매수/TP …' · 'KT&G(BUY, TP' · '한섬(278470.KS'
_LEAD_JUNK = " \t*•·-▶■◆●□▣◇►✅📌🔹🔸[『「<《\"'"


def _tp_owner_ok(line, pos, code, nmap, nrx):
    """줄 속 목표가(pos)가 이 종목 것인가. 줄에서 '종목 머리'로 적힌 이름 — 'KT&G(BUY, TP 21만원)' · '우리금융(매수/TP 43,000)' · 줄 머리의 '한온시스템, …' — 을 찾아,
    목표가 바로 앞 종목 머리가 다른 회사면 아니다. 본문 속 고객 언급('삼성전자향 매출 … 목표주가 150,000원')은 종목 머리가 아니라 상관없다.
    종목 코드가 줄에 있거나 어느 종목인지 모르면(code · 이름 색인 없음) 그대로 받는다."""
    if not code or not nrx or not nmap:
        return True
    if re.search(r"(?<!\d)A?" + re.escape(code) + r"(?!\d)", line):
        return True
    subs = []
    for m in nrx.finditer(line):
        tail = line[m.end():m.end() + 16]
        if _SUBJ_TAIL.match(tail) or (not line[:m.start()].strip(_LEAD_JUNK) and re.match(r"\s*[,:：;/]", tail)):
            subs.append((m.start(), nmap.get(m.group(1))))
    before = [c for p, c in subs if p < pos]
    if before:
        return before[-1] == code
    return not subs or any(c == code for _, c in subs)


def _tp_pair(text, code=None, nmap=None, nrx=None, strict=False):
    """글(항목) 속 목표가 → (이전, 새). '이전 → 새' 는 바로 앞 40자에 목표 · TP 낱말이 있고 비율이 0.3~3 안일 때만
    ('달러-원 환율은 1,386원에서 1,380원' · '머신 1,360→1,610대' 는 아니다). 다른 종목 머리 뒤의 목표가(_tp_owner_ok)는 건너뛰고 다음 것을 본다.
    strict(종목이 여럿 적힌 뉴스 묶음 항목)면 우리 이름 · 코드가 적힌 줄의 목표가만 — '"SK하이닉스, 목표가 380만원 유지"' 줄이 NAVER 항목에 붙지 않게. 없으면 (None, None)."""
    mine = None
    if strict and code and nmap:
        own = [re.escape(n) for n, c in nmap.items() if c == code]
        mine = re.compile(r"(?<!\d)A?" + re.escape(code) + r"(?!\d)" + (("|" + "|".join(own)) if own else ""))

    def ok(pos):
        line, a = _line_of(text, pos)
        if mine is not None and not mine.search(line):
            return False
        return _tp_owner_ok(line, pos - a, code, nmap, nrx)
    for mv in TP_MOVE.finditer(text):
        if not re.search(r"목표|TP|Target|적정", text[max(0, mv.start() - 40):mv.start()], re.I):
            continue
        a, b = _tp_val(mv, 0), _tp_val(mv, 3)
        if a and b and 0.3 < b / a < 3 and ok(mv.start()):
            return a, b
    hits = sorted([(m.start(), m) for m in TP_RX.finditer(text)] + [(m.start(), m) for m in TP_ALT.finditer(text)], key=lambda x: x[0])
    for pos, m in hits:
        v = _tp_val(m)
        if v and ok(pos):
            return None, v
    return None, None


def broker_of(text, channel_title=""):
    """글 앞부분('[하나증권]', '삼성증권 리서치') → 채널 제목 순으로 증권사 이름."""
    head = (text or "")[:200]
    for name, rx in BROKER_RX:
        if rx.search(head):
            return name
    for name, rx in BROKER_RX:
        if rx.search(channel_title or ""):
            return name
    return None


def _items(text):
    """글을 항목으로 — 빈 줄 · 구분선 · '■ ▶ ◆ ●' 머리 · '[종목]' 줄로 가른다. 하루치 요약 글 하나에 종목이 여럿."""
    t = (text or "").replace("\r", "")
    parts = re.split(r"\n\s*(?:[-=─━_]{3,}|\*{3,})\s*\n|\n\s*\n(?=\s*(?:[■▶◆●□▣◇►✅📌🔹🔸]|\[|【|\d+\.\s))", t)
    out = [p.strip() for p in parts if p and p.strip()]
    return out or [t.strip()]


_NI = {"key": None, "val": None}


def _name_index(names):
    """수집한 회사 이름 → 코드. 긴 이름부터 맞춰야 'LG' 가 'LG에너지솔루션' 을 먹지 않는다. 두 글자 이름은 앞뒤가 글자가 아닐 때만.
    build 는 같은 dict 로 글 수만 번 부른다 — 같은 dict(·크기)면 만들어 둔 것을 쓴다."""
    key = (id(names), len(names))
    if _NI["key"] == key:
        return _NI["val"]
    pairs = sorted(((n, c) for n, c in names.items() if len(n) >= 2), key=lambda x: -len(x[0]))
    alt = "|".join(re.escape(n) for n, _ in pairs)
    val = dict(pairs), (re.compile(r"(?<![가-힣A-Za-z0-9])(" + alt + r")(?![가-힣A-Za-z0-9])") if alt else None)
    _NI.update(key=key, val=val)
    return val


CARD_SKIP = re.compile(r"^\s*\[(?:단독|속보|특징주|공시|주식뉴스!?|리포트|뉴스|일정)\]")
CARD_STOCK = re.compile(r"([^\n|:：]{1,40}?)\s*\(\s*A?(\d{6}(?:\.K[SQ])?|[0-9A-Z]{3,8}\.[A-Z]{1,3}|[A-Z]{1,6})\s*\)\s*\|\s*([^|\n]*?)\s*\|\s*현재가\s*([\d,.]+|-)\s*(원|[A-Z]{3})?[^|\n]{0,30}\|\s*"
                        r"목표\s*주?가\s*([\d,.]+|-|미정|미제시|없음)\s*(원|[A-Z]{3})?")       # '현재가 274,000원(보통주 기준, 9월21일) | 목표주가 미제시'
CARD_PICK = re.compile(r"([^\n|:：]{1,40}?)\s*\(\s*A?(\d{6})(?:\.K[SQ])?\s*\)\s*\|\s*([^|\n]*?)\s*\|\s*기준가\s*([\d,]+)\s*원?")    # 투자유망 포트폴리오 줄
CARD_SEC = re.compile(r"^\s*\[?\s*(?:📌|📊|📈|💡|🔗|⚠️|🎯)?\s*\[?\s*(종목\s*(?:정보|및\s*투자\s*의견)?|핵심\s*투자\s*(?:포인트|전략)|실적\s*전망|결론|원문\s*보기|주요\s*리스크\s*요인|투자\s*포인트)\s*\]?\s*[:：]?", re.M)


def _parse_card(text, codes, names=None):
    """정형 카드 글 — 텔레그램 '[주식] 증권사 리포트'(t.me/companyreport, stockinfo7) 꼴.
      [기업][켐트로스] 반도체 소재 매출 비중 50% 상회
      📌 종목: 코스메카코리아 (241710) | BUY | 현재가 127,300원 | 목표주가 150,000원
      📊 핵심 투자포인트 / - … · 📈 실적 전망 / 2026년 매출액 … · 💡 결론 / … · 🔗 원문보기 링크
    [시장][중국 반도체] … 는 산업 · 시장 리포트(종목 줄에 우리 종목이 있으면 기업 항목도). [단독] · [속보] · [특징주] · [공시] 는 뉴스 묶음이라 버린다.
    → 항목 목록, 카드 꼴이 아니면 None."""
    t = (text or "").replace("\r", "")
    if CARD_SKIP.match(t):
        return []
    mh = re.match(r"\s*\[(기업|시장|산업|전략|투자|채권|경제)\]\s*(?:\[([^\]]{1,40})\])?\s*([^\n]*)", t)
    if not mh:
        return None
    names = names or {}
    plain = not (CARD_STOCK.search(t) or CARD_PICK.search(t) or "📌" in t or "핵심 투자" in t or "[핵심" in t)
    if plain and not (mh.group(1) == "기업" and mh.group(2) and (mh.group(2).strip() in names)):
        return None
    tag, tag2, title = mh.group(1), (mh.group(2) or "").strip(), mh.group(3).strip()
    # 구역 나누기
    secs, cur = {}, "head"
    for line in t.split("\n"):
        ms = CARD_SEC.match(line)
        if ms:
            k = re.sub(r"\s+", "", ms.group(1))
            cur = "종목" if k.startswith("종목") else ("핵심" if "핵심" in k or "투자포인트" in k else ("실적" if "실적" in k else ("결론" if "결론" in k else (
                "링크" if "원문" in k else ("위험" if "리스크" in k else "기타")))))
            rest = line[ms.end():].strip()
            secs.setdefault(cur, [])
            if rest:
                secs[cur].append(rest)
            continue
        if line.strip():
            secs.setdefault(cur, []).append(line.strip())
    bullets = [re.sub(r"^[-•·*▶]\s*", "", l) for l in secs.get("핵심", []) if len(l) >= 6][:10]
    est = [l for l in secs.get("실적", []) if re.search(r"\d", l)][:8]
    concl = " ".join(secs.get("결론", []))[:1500]
    risks = [re.sub(r"^[-•·*▶]\s*", "", l) for l in secs.get("위험", []) if len(l) >= 6][:6]
    urls = [u for u in URL_RX.findall(t) if "stockinfo7.com/" in u and not u.rstrip("/").endswith("stockinfo7.com")][:2] or URL_RX.findall(t)[:1]
    bt = t[:600]
    for nm in ([tag2] if tag == "기업" and tag2 else []) + [m.group(1).strip() for m in CARD_STOCK.finditer(t)]:
        if nm:
            bt = bt.replace(nm, " ")
    broker = broker_of(bt, "") or (broker_of(tag2, "") if tag != "기업" else None) or series_broker(tag2 + " " + title)
    out = []
    # 제목 속 의견 — '[웹젠/매수]' · 'KT&G(033780.KS/매수):'
    mto = re.search(r"/\s*(매수|중립|매도|보유|Buy|BUY|Hold|HOLD|Sell|Trading\s*Buy|Outperform|Marketperform)\s*[\])]", title)
    title = re.sub(r"^\[[^\]/]{1,30}/[^\]]{1,20}\]\s*", "", title)                       # 앞의 '[웹젠/매수]'
    title = re.sub(r"\(\s*A?\d{6}(?:\.K[SQ])?(?:\s*/[^)]*)?\)\s*[:：]?\s*", " ", title).strip()  # 'KT&G(033780.KS/매수):'
    for m in CARD_STOCK.finditer(t):
        code = m.group(2).split(".")[0] if re.match(r"\d{6}", m.group(2)) else m.group(2)
        if code not in codes:
            continue                      # 해외 종목('002371.CH') · 수집 밖 종목
        op_raw = m.group(3)
        if not re.search(r"[A-Za-z]{2,}|매수|매도|중립|보유|비중", op_raw) and mto:
            op_raw = (op_raw + " " + mto.group(1)).strip()      # 의견 칸에 '유지' 만 — 제목의 '/매수' 를 쓴다
        tp = _num(m.group(6)) if re.fullmatch(r"[\d,]+", m.group(6) or "") else None
        px = _num(m.group(4)) if re.fullmatch(r"[\d,]+", m.group(4) or "") else None
        opm = OPINION.search(op_raw) or re.search(r"(강력\s*매수|보유|비중\s*확대|비중\s*축소)", op_raw)
        opv = (opm.group(1) or (opm.group(2) if opm.lastindex and opm.lastindex >= 2 else None)) if opm else op_raw
        opn = "Buy" if re.search(r"강력\s*매수|비중\s*확대", op_raw) else ("Hold" if re.search(r"보유", op_raw) else ("Sell" if re.search(r"비중\s*축소", op_raw) else _norm_op(opv)))
        ch = re.search(r"상향|하향|유지|신규", op_raw + " " + title)
        mv = re.search(r"목표\s*주?가[^\n.]{0,20}?" + NUM + r"\s*원?\s*(?:→|->|에서)\s*" + NUM, t)
        tp_prev = _num(mv.group(1)) if mv and _num(mv.group(2)) == tp else None
        change = ("상향" if tp_prev and tp and tp > tp_prev else "하향" if tp_prev and tp and tp < tp_prev else (ch.group(0) if ch else None))
        out.append({"kind": "기업", "code": code, "name": codes[code], "broker": broker, "opinion": ("NR" if opn and re.fullmatch(r"N\.?\s*R\.?", opn.strip(), re.I) else opn) if opn and (opn in ("Buy", "Hold", "Sell", "NR", "Trading Buy") or re.fullmatch(r"N\.?\s*R\.?", opn.strip(), re.I)) else None,
                    "tp": tp, "tp_prev": tp_prev, "change": change, "price_at": px, "title": title[:120], "lines": bullets,
                    "est": est, "concl": concl, "risks": risks, "urls": urls, "sector": None})
    # 투자유망 포트폴리오 — '삼성전자 (005930.KS) | 신규 | 기준가 276,000원' + 아래 '-' 줄
    for m in CARD_PICK.finditer(t):
        code = m.group(2)
        if code not in codes or any(o["code"] == code for o in out):
            continue
        after = t[m.end():m.end() + 600].split("\n\n")[0]
        why = [re.sub(r"^[-•·*]\s*", "", l.strip()) for l in after.split("\n") if l.strip().startswith(("-", "•", "·"))][:3]
        out.append({"kind": "기업", "code": code, "name": codes[code], "broker": broker, "opinion": "Buy", "tp": None, "tp_prev": None,
                    "change": (m.group(3).strip() or None), "price_at": _num(m.group(4)), "title": "[%s] %s" % (title[:60], m.group(3).strip() or "편입"),
                    "lines": why, "est": [], "concl": "", "urls": urls, "sector": None, "pick": True})
    # 신한 꼴 — '[기업][대한항공] 대한항공; 난기류를 헤치고 27년으로' + '신한생각: …' 소제목 · 문단(종목 줄 없음)
    if tag == "기업" and not out and tag2 and tag2 in names and names[tag2] in codes:
        code = names[tag2]
        body = [l.strip() for l in t.split("\n")[1:] if l.strip() and not URL_RX.search(l) and "원문" not in l]
        heads = list(dict.fromkeys(l for l in body if len(l) <= 60 and re.search(r"[:：]", l)))[:4]
        # 소제목 · 문단 짝(신한생각: … / 3Q26 Preview: … / Valuation & Risk: …) — 앞쪽 목차 줄은 문단이 없어 빠진다
        sections, i = [], 0
        while i < len(body):
            l = body[i]
            if len(l) <= 60 and re.search(r"[:：]", l) and i + 1 < len(body) and len(body[i + 1]) > 60:
                sections.append({"h": l, "p": body[i + 1][:900]})
                i += 2
                continue
            i += 1
        nmap0, nrx0 = _name_index(names) if names else ({}, None)
        tp_prev, tp = _tp_pair(t, code, nmap0, nrx0)
        op = OPINION.search(t)
        chm = re.search(r"목표\s*주?가\s*(상향|하향|유지)|(상향|하향)\s*조정", t)
        if re.search(r"신한생각", t):
            broker = broker or "신한투자증권"
        out.append({"kind": "기업", "code": code, "name": codes[code], "broker": broker, "opinion": _norm_op(op.group(1) or op.group(2)) if op else None,
                    "tp": tp, "tp_prev": tp_prev, "change": (chm.group(1) or chm.group(2)) if chm else None, "price_at": None,
                    "title": re.sub(r"^\s*" + re.escape(tag2) + r"\s*[;:：]\s*", "", title)[:120], "lines": heads or body[:3],
                    "est": [], "concl": "", "urls": urls, "sector": None, "sections": sections[:5]})
    if tag in ("시장", "산업", "전략", "투자", "채권", "경제") or not out:
        if tag == "기업" and not out:
            return []                     # 우리 수집 밖 종목의 기업 리포트
        ind = INDUSTRY.search(tag2 + " " + title)
        out.append({"kind": "산업", "code": None, "name": None, "broker": broker, "opinion": None, "tp": None, "tp_prev": None, "change": None,
                    "price_at": None, "title": (("[" + tag2 + "] ") if tag2 else "") + title[:110], "lines": bullets, "est": est, "concl": concl, "risks": risks,
                    "urls": urls, "sector": ind.group(0) if ind else (tag2 or tag)})
    return out


def _gen_title(lines):
    """일반 글 항목의 제목 — 증권사 · 애널리스트 머리 줄, '종목(코드) BUY/TP …' 줄, 인사 · 링크 줄은 건너뛴다.
    '[넷마블 3분기 프리뷰, 하나증권 … 이준호]' 처럼 머리에 제목이 붙었으면 쉼표 앞을."""
    for l in lines:
        s = re.sub(r"^[^\w\[(『「<《]+", "", re.sub(r"\s+", " ", l).strip()).strip("『』「」《》<> '\"‘’“”")
        if len(s) < 6 or (URL_RX.search(s) and len(URL_RX.sub("", s).strip()) < 12) or re.fullmatch(r"[\d\s./:()\-년월일월화수목금토]+", s):
            continue                      # 링크 줄 · '채널: https://t.me/…' · 날짜만 있는 줄('2026.5.4(월)')
        mb = re.fullmatch(r"\[([^\]]*)\]", s)
        if mb:
            x, x0 = mb.group(1), mb.group(1).split(",")[0].strip()
            if "," in x and any(rx.search(x) for _, rx in BROKER_RX) and len(x0) >= 6 and not any(rx.search(x0) for _, rx in BROKER_RX):
                return x0                 # '[넷마블 3분기 프리뷰, 하나증권 …]' — '[키움 스몰캡 오현진, 이하곤]' 은 머리
            continue
        if any(rx.search(s) for _, rx in BROKER_RX) and len(s) <= 40 and not re.search(r"[:：]\s*\S", s):
            continue                      # 'IBK투자증권' · '하나증권 Global ETF 장치영(T.3771-3669)'
        if len(s) <= 70 and re.search(r"\(\s*(?:Analyst|애널리스트|연구원)\b", s, re.I):
            continue                      # '스몰캡/로봇/AI (Analyst 한유건, 권태우)'
        if re.match(r"(?:목표\s*주?가|투자\s*의견|TP\b|안녕하세요|보고서\s*링크|자료\s*[:：]|텔레그램|\*?텔레그램)", s, re.I):
            continue
        if len(s) <= 60 and re.search(r"(?:BUY|HOLD|SELL|Trading\s*Buy|매수|중립|OVERWEIGHT|NEUTRAL)\s*/\s*(?:TP\s*)?[\d,]+|(?:BUY|HOLD|SELL|OVERWEIGHT|NEUTRAL)\s*/\s*(?:유지|신규|상향|하향)", s, re.I):
            continue                      # '코스메카코리아(241710) BUY/140,000원 (유지/상향)' · '증권업(OVERWEIGHT/유지)'
        if re.fullmatch(r"[^()\n]{1,30}\(\s*A?\d{6}(?:\.K[SQ])?\s*\)\s*", s) or (len(s) <= 40 and re.search(r"\(\s*TP\b", s)):
            continue                      # '현대오토에버(307950)' · '천보 (TP 4.5만원)'
        if re.fullmatch(r"[A-Za-z가-힣·&\s]{1,12}(?:/[A-Za-z가-힣·&\s]{1,12})+", s) or re.fullmatch(r"[가-힣]{2,4}\s*(?:수석\s*)?(?:연구위원|연구원|애널리스트|리서치본부장|센터장|팀장|이사)", s):
            continue                      # 'IT/반도체' · '조선/기계/운송' 담당 줄, '김운호 연구위원'
        return s
    return lines[0] if lines else ""


TP_ALT = re.compile(r"(?<![A-Za-z])(?:BUY|HOLD|매수|중립|Trading\s*Buy)\s*/\s*(?:TP\s*)?" + TPNUM, re.I)      # 'BUY/140,000원' · 'BUY/TP 500,000' · 'BUY/TP 19만원'
COMPLIANCE = re.compile(r"컴플라이언스|법적\s*책임|증빙\s*자료|사전\s*공표|승인을\s*받아|투자\s*판단의\s*최종|당사는\s*(?:동\s*)?자료")
REPORT_WORD = re.compile(r"리포트|보고서|프리뷰|Preview|리뷰|Review|발간|코멘트|Comment|실적|투자\s*의견|목표\s*주?가|\bBUY\b|매수|\.pdf|자료\s*[:：]|원문", re.I)


def _whole_post(text, broker, nmap, nrx, codes):
    """증권사 공식 채널 글 — 글 하나가 리포트 하나. 앞 여섯 줄에 우리 종목(6자리 코드, 또는 '[삼성전자]' · '『POSCO홀딩스(' · '삼성E&A(' 꼴 이름)이 있고
    리포트 낱말 · 목표가가 있으면 글 전체를 기업 항목 하나로. 아니면 None(항목으로 쪼개 읽는다)."""
    lines = [l.strip(" \t•·-*▶■◆●□▣◇►✅📌🔹🔸") for l in text.split("\n") if l.strip()]
    top = "\n".join(l for l in lines[:6] if len(l) <= 100)     # 머리 · 제목 줄만 — 본문 문단 속 '삼성전자(+5%)' 같은 언급은 아니다
    if len(lines) <= 2 and re.search(r"\.pdf\b", text, re.I):
        return None                       # 앞 글에 붙은 첨부 파일만 있는 글
    if re.search(r"Daily|데일리|Weekly|위클리|Monthly|먼슬리|모닝|Morning|시황|Nowcast|마감|수급|모니터링|Calendar|캘린더|뉴스\s*\(|News|장\s*시작\s*전|주간|Quant의|퀀트|마켓\s*레이더|Market\s*Radar",
                 " ".join(lines[:2]), re.I):
        return None                       # 데일리 · 주간 · 시황 묶음 — 종목 이름이 나와도 그 종목 리포트가 아니다
    if len({m.group(1) for m in CODE_RX.finditer(text) if m.group(1) in codes}) >= 2:
        return None                       # 종목 여럿(산업 리포트의 관심종목 · 커버리지 표) — 항목으로 쪼개 읽는다
    if len({m.group(1) for m in re.finditer(r"(?m)^\s*[*\-•·▶►◆■]?\s*([^\s:：(\[\]]{2,20})\s*[:：(]", text) if m.group(1) in nmap}) >= 2:
        return None                       # '* 삼성전자: … / * SK하이닉스: …' 줄 머리에 종목이 여럿 — 퀀트 · 업종 묶음
    code = name = None
    for m in CODE_RX.finditer(top):
        if m.group(1) in codes:
            code, name = m.group(1), codes[m.group(1)]
            break
    if not code and (re.search(r"\(\s*A?\d{6}(?:\.K[SQ])?\s*[/)]", top) or re.search(r"\(\s*[0-9A-Z]{1,6}\.(?:HK|US|O|N|T|SS|SZ|TW|CH|JP)\s*[/)]", top)):
        return None                       # 수집 밖 종목('케이카 (381970.KS/…)') · 해외 종목('레노버(0992.HK)') 글 — 본문의 다른 이름을 종목으로 잡지 않게
    if not code and nrx:
        for m in nrx.finditer(top):
            nm = m.group(1)
            if any(rx.search(nm) for _, rx in BROKER_RX) or nm not in nmap or re.match(r"\s*(?:증권|투자증권|리서치)|\.[A-Z]{1,3}\b", top[m.end():m.end() + 6]):
                continue                  # '[SK 증권 조준기]' 의 SK, '골드만삭스 (GS.US)' 의 GS
            if re.search(r"[\[『「(]\s*$", top[max(0, m.start() - 2):m.start()]) or re.match(r"\s*(?:[\]』」:：]|\(\s*(?:A?\d{6}|[A-Za-z]{2,}|매수|중립|매도))", top[m.end():m.end() + 12]):
                code, name = nmap[nm], nm
                break
    if not code:
        return None
    if len({m.group(1) for m in nrx.finditer(text) if re.match(r"\s*\(\s*(?:매수|중립|매도|Buy|BUY|Hold|HOLD|A?\d{6})", text[m.end():m.end() + 12])} if nrx else set()) >= 2:
        return None                       # 'KB금융(매수/TP …)과 신한지주(매수/TP …)' — 선호 종목 묶음
    tp_prev, tp = _tp_pair(text, code, nmap, nrx)       # '이전 → 새' · '목표주가 1,300,000원' · 'TP 4.5만원' · 'BUY/140,000'
    if not (tp or REPORT_WORD.search(text)):
        return None
    op = OPINION.search(text)
    if op and op.group(2) and not re.search(r"(?:의견\s*[:：]?\s*|[(/\[]\s*)$", text[max(0, op.start() - 12):op.start()]):
        op = None
    mc = re.search(r"\((?:유지|신규|상향|하향)\s*/\s*(유지|신규|상향|하향)\)", text)         # '(유지/상향)' — 뒤가 목표가
    mtp = re.search(r"(?:목표\s*주?\s*가|적정\s*주가|(?<![A-Za-z])TP)[^\n]{0,30}?(상향|하향|유지|신규)|(상향|하향)\s*조정", text)   # 'TP 19만원(하향)' · '적정주가 …로 하향'
    change = ("상향" if tp > tp_prev else "하향" if tp < tp_prev else "유지") if (tp and tp_prev) else (
        mc.group(1) if mc else ((mtp.group(1) or mtp.group(2)) if mtp else None))
    title = _gen_title(lines)
    title = re.sub(r"^\[[^\]]{1,20}\]\s*", "", title)
    title = re.sub(r"^\s*" + re.escape(name) + r"\s*(?:\(\s*A?\d{6}(?:\.K[SQ])?(?:\s*/[^)]*)?\s*\))?\s*[:：\-—–;]\s*", "", title)[:120]
    body = [re.sub(r"^[-•·*»▶►]\s*", "", l.strip()) for l in text.split("\n") if re.match(r"\s*[-•·*»▶►]\s*\S", l)]
    body = [l for l in body if len(l) >= 8 and not URL_RX.search(l) and not COMPLIANCE.search(l)][:5] or \
        [l for l in lines[1:] if len(l) >= 20 and not URL_RX.search(l) and not COMPLIANCE.search(l)][:3]
    return {"kind": "기업", "code": code, "name": name, "broker": broker, "opinion": _norm_op(op.group(1) or op.group(2)) if op else None,
            "tp": tp, "tp_prev": tp_prev, "change": change, "title": title, "lines": body, "urls": URL_RX.findall(text)[:3],
            "src": "brk", "ref": False, "sector": None}


def parse(text, channel_title="", names=None, codes=None):
    """글 하나 → 리포트 항목들. names: {회사 이름: 코드}, codes: {코드: 회사 이름}(수집한 회사).
    → [{kind('기업'|'산업'), code, name, broker, opinion, tp, tp_prev, change, title, lines, urls}]
    정형 카드 글(_parse_card)이면 그 규칙으로, 아니면 아래 일반 규칙으로."""
    import html as _h
    names = names or {}
    codes = codes or {}
    text = _h.unescape(text or "")            # 미리보기 HTML 이 한 번 더 감싼 '&rarr;' · '&amp;' 같은 것
    card = _parse_card(text, codes, names)
    if card is not None:
        for r in card:
            r["src"] = "card"
        return card
    nmap, nrx = _name_index(names) if names else ({}, None)
    out = []
    # 증권사 공식 채널(제목에 증권사 이름)이면 그 증권사 — 글 속에 다른 증권사 이름('JP모건 보고서에 따르면')이 나와도
    chb = broker_of("", channel_title) or series_broker(channel_title)
    broker0 = chb or broker_of(text, "")
    if chb:
        one = _whole_post(text, chb, nmap, nrx, codes)
        if one:
            return [one]
    for it in _items(text):
        if len(it) < 12:
            continue
        lines = [l.strip(" \t•·-*▶■◆●□▣◇►✅📌🔹🔸") for l in it.split("\n") if l.strip()]
        head = " ".join(lines[:3])
        # 종목 — 6자리 코드(수집한 회사만)가 가장 확실하고, 없으면 앞 세 줄에서 수집한 회사 이름
        code = name = None
        for m in CODE_RX.finditer(head):
            if m.group(1) in codes:
                code, name = m.group(1), codes[m.group(1)]
                break
        if not code and nrx:
            m = nrx.search(head)
            if m:
                name = m.group(1)
                code = nmap.get(name)
                # 증권사가 곧 상장사인 이름('키움증권 리서치센터')은 리포트 대상이 아니다. 두 글자 이름('대상')은 괄호 · 코드와 붙어 있을 때만
                if any(rx.search(name) for _, rx in BROKER_RX) or (len(name) <= 2 and not re.search(r"[\[(]\s*" + re.escape(name) + r"\s*[\])/]|" + re.escape(name) + r"\s*\(\s*A?\d{6}", head)):
                    code = name = None
        # '이전 → 새' 는 바로 앞에 '목표' 낱말이 있을 때만 — '달러-원 환율은 1,386원에서 1,380원' 같은 숫자를 목표가로 읽지 않게(_tp_pair).
        # 항목에 수집 종목이 둘 넘게 적혔으면(뉴스 머리기사 묶음 · 선호 종목 줄) 우리 이름이 적힌 줄의 목표가만
        many = len({m.group(1) for m in CODE_RX.finditer(it) if m.group(1) in codes} | ({nmap[m.group(1)] for m in nrx.finditer(it)} if nrx else set())) >= 2
        tp_prev, tp = _tp_pair(it, code, nmap, nrx, strict=bool(code) and many)
        op = OPINION.search(it)
        # 한글 의견(매수 · 매도)은 '투자의견' · '(매수' · '/매수' 꼴일 때만 — 시황 글의 '매도 물량' · '매수 복귀' 는 의견이 아니다
        if op and op.group(2) and not re.search(r"(?:의견\s*[:：]?\s*|[(/\[]\s*)$", it[max(0, op.start() - 12):op.start()]):
            op = None
        broker = chb or broker_of(it, "") or broker0
        # 상향 · 하향 — 목표가가 '이전 → 새' 로 적혔으면 숫자로, 아니면 '목표' 낱말 가까이의 말로
        if tp_prev and tp:
            change = "상향" if tp > tp_prev else ("하향" if tp < tp_prev else "유지")
        else:
            mtp = re.search(r"(?:목표\s*주?\s*가|적정\s*주가|(?<![A-Za-z])TP)[^\n]{0,30}?(상향|하향|유지|신규)|(상향|하향)\s*조정", it)
            ch = CHANGE.search(it)
            change = (mtp.group(1) or mtp.group(2)) if mtp else (ch.group(1) if ch else None)
        title = _gen_title(lines)
        title = re.sub(r"^\[[^\]]{1,20}\]\s*", "", title)
        title = re.sub(r"\s*\((?=[^)]*(?:Buy|BUY|Hold|Sell|매수|중립|매도|TP|목표|NR))[^)]*\)?\s*$", "", title)   # 끝의 '(Buy, TP 112,000원)'
        if name:
            title = re.sub(r"^\s*" + re.escape(name) + r"\s*(?:\(\s*A?\d{6}(?:\.K[SQ])?(?:\s*/[^)]*)?\s*\))?\s*[:：\-—–]\s*", "", title)      # 앞의 '두산에너빌리티:' — 종목 칸이 따로 있다
        title = title[:120]
        body = [l for l in lines[1:] if len(l) >= 8 and not URL_RX.fullmatch(l)][:5]
        urls = URL_RX.findall(it)[:3]
        # 산업 낱말은 증권사 이름('삼성증권'의 '증권')을 빼고 찾는다. 데일리 머리 줄('삼성증권 리서치 10/2 데일리')은 항목이 아니다
        head_x = head
        for _, rx in BROKER_RX:
            head_x = rx.sub(" ", head_x)
        head_x = re.sub(r"리서치|Research|센터", " ", head_x, flags=re.I)
        ind = INDUSTRY.search(head_x)
        if code:
            kind = "기업"
        elif ind and (broker or urls) and not (len(lines) <= 1 and re.search(r"데일리|Daily|모닝|Morning|오늘의|\d{1,2}/\d{1,2}", head, re.I)):
            kind = "산업"
        else:
            continue
        if kind == "기업" and not (tp or re.search(r"리포트|Report|보고서|코멘트|Comment|프리뷰|Preview|리뷰|Review", lines[0] if lines else "", re.I)):
            continue
        if kind == "기업" and chb and not tp:
            continue                      # 증권사 채널 글을 쪼갠 기업 항목은 목표가가 있을 때만(글 하나 = 리포트 하나는 _whole_post 가 이미 봤다)                      # 종목 이름만 스친 글(시황 · 뉴스 · 일정)은 리포트가 아니다 — 목표가 · 의견이 있거나 첫 줄이 리포트 낱말일 때만
        if not title.strip():
            continue
        # src — 'brk': 증권사 공식 채널 글(증권사가 확실, 대조의 근거), 'agg': 모음 채널의 카드 아닌 글(대조로 증권사를 채울 대상).
        # 증권사 채널의 산업 항목은 목록에 내지 않고 대조에만 — 뉴스 묶음 · 데일리가 한 글에 수십 줄이라 산업 칸을 덮는다
        out.append({"kind": kind, "code": code, "name": name, "broker": broker, "opinion": _norm_op(op.group(1) or op.group(2)) if op else None,
                    "tp": tp, "tp_prev": tp_prev, "change": change, "title": title,
                    "lines": body, "urls": urls, "src": "brk" if chb else "agg", "ref": bool(chb) and kind == "산업",
                    "sector": (ind.group(0) if kind == "산업" else None)})
    return out


# ---------------------------------------------------------------- 쌓기 · 읽기
def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"channels": {}, "at": 0}


def _save_state(st):
    os.makedirs(STORE_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def append(msgs):
    """[{id, date(YYYY-MM-DD HH:MM), channel, channel_title, url, text}] — 달마다 jsonl 에 덧붙인다."""
    by = {}
    for m in msgs:
        by.setdefault(m["date"][:7], []).append(m)
    os.makedirs(STORE_DIR, exist_ok=True)
    for ym, ms in by.items():
        with open(os.path.join(STORE_DIR, ym + ".jsonl"), "a", encoding="utf-8") as fh:
            for m in ms:
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")


def raw_messages():
    """쌓아 둔 글 전부(같은 글 번호는 하나)."""
    out, seen = [], set()
    if not os.path.isdir(STORE_DIR):
        return out
    for f in sorted(os.listdir(STORE_DIR)):
        if not f.endswith(".jsonl"):
            continue
        with open(os.path.join(STORE_DIR, f), "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if m.get("id") in seen:
                    continue
                seen.add(m.get("id"))
                out.append(m)
    return out


def store_sig():
    """쌓인 파일들의 크기 · 시각 — 서버가 다시 읽을지 정한다."""
    if not os.path.isdir(STORE_DIR):
        return "none:%d" % RULE_V
    parts = []
    for f in sorted(os.listdir(STORE_DIR)):
        if f.endswith(".jsonl"):
            st = os.stat(os.path.join(STORE_DIR, f))
            parts.append("%s:%d:%d" % (f, st.st_size, int(st.st_mtime)))
    return "|".join(parts) + ":%d" % RULE_V


GENERIC = re.compile(r"daily|weekly|monthly|데일리|위클리|먼슬리|시황|모닝|morning|브리프|brief|코멘트|comment|review|리뷰|preview|프리뷰|"
                     r"채권|전략|매크로|macro|증시|마감|주간|월간|일일|update|업데이트|global|글로벌|강세|약세|코스피|코스닥|kospi|kosdaq|나스닥|nasdaq|"
                     r"s&p|미국|국내|기준금리|금리|인상|인하|동결|환율|유가|\d+", re.I)


def _bigrams(s, drop=(), generic=False):
    """낱자 짝 집합. generic=True 면 어느 증권사나 쓰는 말('채권 Daily' · 날짜 · 숫자)을 빼고 — 산업 글은 제목만으로 맞추니 흔한 말로 엮이지 않게."""
    s = (s or "").lower()
    for d in drop:
        if d:
            s = s.replace(d.lower(), " ")
    s = re.sub(r"\[[^\]]{0,30}\]", " ", s)
    if generic:
        s = GENERIC.sub(" ", s)
    s = re.sub(r"[\W_]+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _day(d):
    try:
        return dt.date.fromisoformat(d[:10]).toordinal()
    except Exception:
        return 0


MATCH_DAYS = (-5, 2)          # 증권사 채널 글 날짜 - 카드 날짜. 카드는 보통 같은 날 ~ 며칠 뒤에 올라온다


def _attribute(cards, gens):
    """증권사 이름이 없는 카드(companyreport) ↔ 증권사 공식 채널 글 대조.
    기업: 같은 종목 · 날짜 차 MATCH_DAYS 안 · (목표가 같음 또는 카드 제목 낱자 짝의 60% 이상이 채널 글 제목 · 첫 줄들에 있음).
    산업: 날짜 차 안 · 카드 제목 낱자 짝의 80% 이상(흔한 말 · 숫자를 뺀 제목 8짝 이상). 맞으면 카드에 증권사 · 채널 글 링크를 채우고(빈 목표가 · 의견 · 요약도),
    맞은 채널 기업 글은 목록에서 뺀다(같은 리포트가 두 번 나오지 않게). 이미 증권사가 있는 카드는 같은 증권사 글과만 맞춰 중복만 걷어낸다.
    다른 증권사 글도 거의 같은 점수면(기준금리 결정 · 같은 날 실적 리뷰 — 여러 곳이 같은 제목을 쓴다) 어느 쪽인지 모르니 채우지 않는다."""
    by_code, by_day = {}, {}
    for g in gens:
        if not g.get("broker"):
            continue
        g["_d"] = _day(g["date"])
        if g["kind"] == "기업" and g.get("code"):
            g["_bg"] = _bigrams(" ".join([g.get("title") or ""] + (g.get("lines") or [])[:3]), (g.get("name"),))
            by_code.setdefault(g["code"], []).append(g)
        elif g["kind"] == "산업":
            g["_bg"] = _bigrams(" ".join([g.get("title") or ""] + (g.get("lines") or [])[:2]), generic=True)
            by_day.setdefault(g["_d"], []).append(g)
    lo, hi = MATCH_DAYS
    n = 0
    for c in cards:
        cd = _day(c["date"])
        cand = []                                              # (점수, 채널 글)
        if c["kind"] == "기업" and c.get("code"):
            a = _bigrams(c.get("title"), (c.get("name"),))
            for g in by_code.get(c["code"], ()):
                if not (lo <= g["_d"] - cd <= hi) or (c.get("broker") and g["broker"] != c["broker"]):
                    continue
                s = (len(a & g["_bg"]) / len(a)) if len(a) >= 4 else 0.0
                if c.get("tp") and g.get("tp") == c["tp"]:
                    s = max(s, 0.9) + 0.05                     # 목표가까지 같으면 더 확실
                if s >= 0.6:
                    cand.append((s, g))
        elif c["kind"] == "산업" and not c.get("broker"):
            a = _bigrams(c.get("title"), generic=True)
            if len(a) >= 8:
                for dd in range(cd + lo, cd + hi + 1):        # 날짜 창 안의 증권사 채널 산업 글만(하루 수십 건)
                    for g in by_day.get(dd, ()):
                        s = len(a & g["_bg"]) / len(a)
                        if s >= 0.8:
                            cand.append((s, g))
        if not cand:
            continue
        score, best = max(cand, key=lambda x: x[0])
        if any(g["broker"] != best["broker"] and s >= score - 0.1 for s, g in cand):
            continue                                           # 다른 증권사도 거의 같은 점수 — 모른다
        best["_used"] = True
        if not c.get("broker"):
            c["broker"], c["broker_via"] = best["broker"], best.get("channel")
            n += 1
        c["brk_url"] = best.get("msg_url")
        for k in ("tp", "tp_prev", "opinion", "change"):
            if not c.get(k) and best.get(k):
                c[k] = best[k]
        if not c.get("lines") and best.get("lines"):
            c["lines"] = best["lines"][:5]
    return n


def _close_at(closes, ks, date):
    """{YYYYMMDD: 종가} · 정렬한 날짜들 → 글 날짜(ISO, 'YYYY-MM-DD HH:MM')의 '리포트 당시' 종가.
    장 시작 전(09:00 전) 글은 전 거래일 종가(애널리스트가 본 값), 그 뒤는 그날 종가. 없으면 None."""
    if not ks:
        return None
    k = (date or "")[:10].replace("-", "")
    if not k:
        return None
    i = (bisect.bisect_left(ks, k) if (date or "")[11:16] < "09:00" else bisect.bisect_right(ks, k)) - 1
    return closes[ks[i]] if i >= 0 else None


def sanitize_tp(rows, px_of=None):
    """목표가 ÷ 주가가 TP_BAND 밖인 글의 목표가를 비운다(tp_raw 에 남김) — 다른 종목 목표가('KT&G … TP 21만원' 이 디바이스에) · 자릿수('STP0404' 의 404 ·
    '2028년') · 증권사가 적은 코드 오류('한섬(278470.KS)') · 분할 전 값. 주가는 카드의 현재가, 없으면 px_of(code) → {YYYYMMDD: 종가} 의 그날 종가. → 뺀 수."""
    memo, n = {}, 0
    for r in rows:
        tp, code = r.get("tp"), r.get("code")
        if not tp or not code:
            continue
        px = r.get("price_at")
        if not px and px_of is not None:
            if code not in memo:
                s = px_of(code) or {}
                memo[code] = (sorted(s), s)
            ks, s = memo[code]
            px = _close_at(s, ks, r.get("date"))
        if px and not (TP_BAND[0] <= tp / px <= TP_BAND[1]):
            r["tp_raw"], r["tp"], r["tp_prev"] = tp, None, None
            n += 1
    return n


def consensus(rows, px, since, closes=None):
    """한 종목 글들 → 증권사별 최신 목표가(since 이후)의 평균 · 중앙 · 상승여력. 없으면 None.
      · 증권사마다 가장 최신 글 하나. 증권사 미표기 글(요약 채널 카드)은 같은 목표가면 같은 집(채널 둘이 같은 리포트를 올린 것 · 증권사 글과 같은 값이면 그 증권사)
      · 3곳 이상이면 중앙값의 OUTLIER_X 배 밖 · ⅓ 아래는 뺀다(dropped — 다른 종목 목표가 · 오타)
      · up = 평균 ÷ 지금 주가 − 1 (%). up_at = 집마다 '리포트 당시 주가'(카드 현재가 · 없으면 closes 의 그날 종가) 대비 상승여력의 평균 —
        목표가가 나온 뒤 주가가 크게 움직였으면(LG이노텍 2026-10: 급락 뒤 +141% vs 당시 +80%대) 둘이 벌어진다. asof = 가장 최신 목표가 날짜.
      closes = {YYYYMMDD: 종가}(캐시, 네트워크 없이)."""
    rs = sorted((r for r in rows or () if r.get("tp") and (r.get("date") or "")[:10] >= since), key=lambda r: r["date"], reverse=True)
    houses, seen = [], set()
    for r in rs:                                   # 증권사 적힌 글 먼저 — 미표기 카드가 같은 값이면 그 증권사 것
        if r.get("broker") and r["broker"] not in seen:
            seen.add(r["broker"])
            houses.append(r)
    known = {h["tp"] for h in houses}
    for r in rs:
        if not r.get("broker") and r["tp"] not in known:
            known.add(r["tp"])
            houses.append(r)
    if not houses:
        return None
    houses.sort(key=lambda r: r["date"], reverse=True)
    tps = [h["tp"] for h in houses]
    med = statistics.median(tps)
    dropped = []
    if len(houses) >= 3:
        keep = [h for h in houses if med / OUTLIER_X <= h["tp"] <= med * OUTLIER_X]
        dropped = [h for h in houses if h["tp"] < med / OUTLIER_X or h["tp"] > med * OUTLIER_X]
        houses, tps = keep, [h["tp"] for h in keep]
        med = statistics.median(tps)
    avg = sum(tps) / len(tps)
    ks = sorted(closes) if closes else []
    out, ups = [], []
    for h in houses:
        p0 = h.get("price_at") or _close_at(closes, ks, h.get("date"))
        if p0:
            ups.append((h["tp"] / p0 - 1) * 100)
        out.append({"broker": h.get("broker"), "tp": h["tp"], "tp_prev": h.get("tp_prev"), "date": h["date"], "opinion": h.get("opinion"),
                    "px_at": p0, "url": h.get("msg_url"), "title": (h.get("title") or "")[:40]})
    return {"avg": avg, "med": med, "n": len(out), "reps": len(rs), "tp_max": max(tps), "tp_min": min(tps),
            "up": (avg / px - 1) * 100 if px else None, "up_at": (sum(ups) / len(ups)) if ups else None,
            "asof": out[0]["date"][:10], "houses": out,
            "dropped": [{"broker": h.get("broker"), "tp": h["tp"], "date": h["date"], "url": h.get("msg_url")} for h in dropped]}


def build(names, codes, px_of=None):
    """쌓인 글 → 리포트 항목(글마다 parse). 카드 ↔ 증권사 채널 대조(_attribute)로 증권사를 채운 뒤,
    같은 증권사 · 종목 · 날짜 · 목표가는 하나로(채널 둘이 같은 리포트를 올린 것). 증권사 없는 카드끼리는 제목도 봐야 다른 리포트를 합치지 않는다.
    px_of(code) → {YYYYMMDD: 종가} 를 주면 주가 대비 TP_BAND 밖 목표가를 비운다(sanitize_tp)."""
    cards, gens = [], []
    for m in raw_messages():
        for r in parse(m.get("text", ""), m.get("channel_title", ""), names, codes):
            r.update(date=m["date"], channel=m.get("channel_title"), msg_url=m.get("url"), msg_id=m.get("id"))
            (gens if r.get("src") == "brk" else cards).append(r)
    _attribute(cards, gens)
    rows, seen, gen_at = [], set(), {}
    for r in cards + [g for g in gens if not g.get("ref") and not g.get("_used")]:
        k = (r["broker"], r["code"] or r["title"][:30], r["date"][:10], r["tp"]) + (() if r["broker"] else (r["title"][:20],))
        if k in seen:
            continue
        if r.get("src") == "brk" and r["kind"] == "기업":
            k2 = (r["broker"], r["code"], r["date"][:10])       # 한 글에 같은 종목 두 줄('3Q26 Preview' · '삼성E&A(028050): …') — 목표가 있는 쪽
            if k2 in gen_at:
                old = gen_at[k2]
                if r.get("tp") and not old.get("tp"):
                    rows[rows.index(old)] = r
                    gen_at[k2] = r
                continue
            gen_at[k2] = r
        seen.add(k)
        rows.append(r)
    for r in rows:
        for k in ("_d", "_bg", "_used", "ref"):
            r.pop(k, None)
    sanitize_tp(rows, px_of)                   # 대조로 채운 목표가까지 포함해 — 카드에 증권사 글의 틀린 목표가가 옮겨 붙은 것도 비운다
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


# ---------------------------------------------------------------- 텔레그램
def _creds():
    import 설정
    api_id, api_hash = 설정.get("TELEGRAM_API_ID"), 설정.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError(".env 에 TELEGRAM_API_ID · TELEGRAM_API_HASH 가 없습니다 — my.telegram.org 에서 받아 넣으세요.")
    return int(api_id), api_hash


def session_exists():
    return os.path.exists(SESSION + ".session")


def web_channels():
    """웹 미리보기로 읽을 공개 채널 이름 — .env TELEGRAM_CHANNELS('@이름' · 't.me/이름' · '이름', 쉼표) 또는 이 폴더의 리포트_채널.txt(한 줄에 하나)."""
    import 설정
    raw = (설정.get("TELEGRAM_CHANNELS") or "").replace("\n", ",").split(",")
    p = os.path.join(BASE, "리포트_채널.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8-sig") as fh:
            raw += [l.split("#")[0] for l in fh]
    out = []
    for x in raw:
        x = re.sub(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?", "", x.strip()).lstrip("@").split("/")[0].split("?")[0]
        if re.fullmatch(r"[A-Za-z0-9_]{4,64}", x) and x not in out:
            out.append(x)
    return out


def can_collect():
    """로그인 세션(Telethon)이 있거나, 웹 미리보기로 읽을 공개 채널 이름이 적혀 있으면 받을 수 있다."""
    return session_exists() or bool(web_channels())


# ---------------------------------------------------------------- 웹 미리보기 — 로그인 · API 키 없이 공개 채널을 t.me/s/이름 으로 읽는다
WEB = "https://t.me/s/%s"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept-Language": "ko,en;q=0.8"}


def _html_text(h):
    import html as _h
    h = re.sub(r"<br\s*/?>", "\n", h or "")
    h = re.sub(r"</(?:p|div)>", "\n", h)
    return _h.unescape(re.sub(r"<[^>]+>", "", h)).strip()


def _web_parse(page, name):
    """t.me/s/이름 한 쪽 → [{id, date, text, links, doc}] (오래된 것부터). 채널 제목도."""
    import html as _h
    mt = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    title = _h.unescape(mt.group(1)) if mt else name
    out = []
    for blk in page.split('data-post="')[1:]:
        mi = re.match(r"([^\"/]+)/(\d+)\"", blk)
        if not mi:
            continue
        body = blk.split('class="tgme_widget_message_wrap')[0]
        md = re.search(r'<time[^>]*datetime="([^"]+)"', body)
        mx = re.search(r'tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', body, re.S)
        mdoc = re.search(r'tgme_widget_message_document_title[^>]*>(.*?)</div>', body, re.S)
        links = re.findall(r'href="(https?://[^"]+)"', mx.group(1) if mx else "")
        out.append({"id": int(mi.group(2)), "date": md.group(1) if md else None, "text": _html_text(mx.group(1)) if mx else "",
                    "doc": _html_text(mdoc.group(1)) if mdoc else None, "links": links})
    return title, sorted(out, key=lambda m: m["id"])


def _collect_web(days=365, log=print, max_pages=120):
    """공개 채널마다 (1) 지난번 뒤의 새 글 — 최신 쪽부터 '?before=' 로 마지막 글 번호까지,
    (2) 남은 쪽수로 거슬러 채우기 — 받아 둔 가장 오래된 글 앞쪽을 days 일 전까지(한 번에 다 못 받으면 다음 수집 때 이어서). 요청 사이 1초."""
    import requests
    st = _load_state()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    got = 0
    names = web_channels()
    log("웹 미리보기 채널 %d곳: %s" % (len(names), ", ".join(names)))
    for name in names:
        key = "web:" + name.lower()
        cs = st["channels"].get(key, {})
        last, oldest_id, oldest_dt = int(cs.get("last", 0)), int(cs.get("oldest", 0)), cs.get("oldest_date")
        if last and not oldest_id:        # 예전 상태(가장 오래된 글을 적기 전) — 쌓인 글에서 찾는다
            mine = [m for m in raw_messages() if str(m.get("id", "")).startswith(key + ":")]
            if mine:
                oldest_id = min(int(m["id"].rsplit(":", 1)[1]) for m in mine)
                oldest_dt = min(m["date"] for m in mine)
        msgs, title, pages = {}, cs.get("title") or name, 0

        def walk(before, stop_id, until):
            """before 앞쪽을 거슬러 — stop_id 이하 · until 이전에 닿으면 멈춤. 닿았으면 True."""
            nonlocal pages, title
            while pages < max_pages:
                try:
                    r = requests.get(WEB % name, params={"before": before} if before else None, headers=UA, timeout=25)
                except Exception as e:
                    log("  %s — 못 읽음: %s" % (name, e))
                    return False
                pages += 1
                if r.status_code != 200 or "tgme_widget_message" not in r.text:
                    if pages == 1:
                        log("  %s — 공개 채널 미리보기가 없다(비공개 · 이름 틀림 · 미리보기 막힘)" % name)
                    return True
                title, ms = _web_parse(r.text, name)
                if not ms:
                    return True
                for m in ms:
                    if m["id"] > stop_id and (not m["date"] or m["date"] >= until):
                        msgs[m["id"]] = m
                first = ms[0]
                if first["id"] <= stop_id or (first["date"] and first["date"] < until) or first["id"] <= 1:
                    return True
                before = first["id"]
                time.sleep(1.0)
            return False
        # (1) 새 글 — 처음이면 since 까지
        walk(None, last, since if not last else "")
        # (2) 거슬러 채우기 — 받아 둔 가장 오래된 글이 since 보다 뒤면 그 앞쪽을
        lo = min([i for i in msgs] + ([oldest_id] if oldest_id else []), default=0)
        lo_dt = min([m["date"] for m in msgs.values() if m.get("date")] + ([oldest_dt] if oldest_dt else []), default=None)
        done = cs.get("backfill_done", False)
        if lo and lo_dt and lo_dt > since and not done and pages < max_pages:
            done = walk(lo, 0, since)
            lo = min([i for i in msgs] + [lo])
            lo_dt = min([m["date"] for m in msgs.values() if m.get("date")] + [lo_dt])
        rows = []
        for i in sorted(msgs):
            m = msgs[i]
            txt = (m["text"] + ("\n" + m["doc"] if m.get("doc") else "") + ("\n" + "\n".join(m["links"]) if m["links"] else "")).strip()
            if len(txt) < 12:
                continue
            d = dt.datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone() if m["date"] else dt.datetime.now()
            rows.append({"id": "%s:%d" % (key, i), "date": d.strftime("%Y-%m-%d %H:%M"), "channel": name, "channel_title": title,
                         "url": "https://t.me/%s/%d" % (name, i), "text": txt[:4000]})
        if rows:
            append(rows)
            got += len(rows)
        st["channels"][key] = {"title": title, "last": max([last] + list(msgs)), "oldest": lo, "oldest_date": lo_dt,
                               "backfill_done": bool(done or (lo_dt and lo_dt <= since)), "at": time.time(), "via": "web"}
        log("  %s(%s) — 새 글 %d, %d쪽, 가장 오래된 글 %s%s" % (title[:24], name, len(rows), pages, (lo_dt or "")[:10],
                                                     "" if st["channels"][key]["backfill_done"] else " — 다음 수집 때 더 거슬러 받는다"))
        time.sleep(1.0)
    st["at"] = time.time()
    _save_state(st)
    return got


def _wanted(entity, explicit):
    title = getattr(entity, "title", "") or ""
    uname = (getattr(entity, "username", "") or "").lower()
    if explicit:
        return any(e.lower().lstrip("@") in (uname, title.lower()) or (e and e.lower() in title.lower()) for e in explicit)
    return bool(CHANNEL_HINT.search(title) or broker_of("", title))


async def _collect(days=180, per_channel=3000, list_only=False, log=print):
    from telethon import TelegramClient
    from telethon.tl.types import Channel
    import 설정
    api_id, api_hash = _creds()
    explicit = [x.strip() for x in (설정.get("TELEGRAM_CHANNELS") or "").split(",") if x.strip()]
    os.makedirs(SESSION_DIR, exist_ok=True)
    st = _load_state()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    got = 0
    async with TelegramClient(SESSION, api_id, api_hash, flood_sleep_threshold=120) as client:
        if not await client.is_user_authorized():
            raise RuntimeError("텔레그램 로그인이 안 돼 있습니다 — 터미널에서 python 도구/텔레그램_로그인.py 를 먼저 한 번 돌리세요.")
        chans = []
        async for d in client.iter_dialogs():
            e = d.entity
            if isinstance(e, Channel) and getattr(e, "broadcast", False) and _wanted(e, explicit):
                chans.append(e)
        log("리포트 채널 %d곳: %s" % (len(chans), ", ".join((c.title or "")[:20] for c in chans)))
        if list_only:
            return 0
        for e in chans:
            key = str(e.id)
            last = int(st["channels"].get(key, {}).get("last", 0))
            msgs = []
            kw = {"min_id": last} if last else {}
            async for m in client.iter_messages(e, limit=per_channel, **kw):
                if not last and m.date and m.date < since:
                    break
                txt = m.message or ""
                doc = getattr(getattr(m, "document", None), "attributes", None) or []
                fname = next((getattr(a, "file_name", None) for a in doc if getattr(a, "file_name", None)), None)
                if fname:
                    txt = (txt + "\n" + fname).strip()
                if len(txt) < 12:
                    continue
                uname = getattr(e, "username", None)
                msgs.append({"id": "%s:%d" % (e.id, m.id), "date": m.date.astimezone().strftime("%Y-%m-%d %H:%M"),
                             "channel": uname or key, "channel_title": e.title,
                             "url": ("https://t.me/%s/%d" % (uname, m.id)) if uname else None, "text": txt[:4000]})
            if msgs:
                append(msgs)
                got += len(msgs)
            mx = max([int(x["id"].split(":")[1]) for x in msgs] + [last])
            st["channels"][key] = {"title": e.title, "last": mx, "at": time.time()}
            log("  %s — 새 글 %d" % ((e.title or "")[:24], len(msgs)))
    st["at"] = time.time()
    _save_state(st)
    return got


def collect(days=365, per_channel=3000, list_only=False, log=print):
    """로그인 세션이 있으면 Telethon(구독 채널 전부), 없으면 웹 미리보기(적어 둔 공개 채널)."""
    if not session_exists():
        if list_only:
            log("웹 미리보기 채널: %s" % (", ".join(web_channels()) or "(없음 — .env TELEGRAM_CHANNELS 또는 리포트_채널.txt 에 적는다)"))
            return 0
        return _collect_web(days, log)
    import asyncio
    return asyncio.run(_collect(days, per_channel, list_only, log))
