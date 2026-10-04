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
import datetime as dt

BASE = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(BASE, ".cache", "리포트")
STATE_PATH = os.path.join(STORE_DIR, "_state.json")
SESSION_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "기업추적")
SESSION = os.path.join(SESSION_DIR, "telegram")          # Telethon 이 .session 을 붙인다
RULE_V = 1                                                # 읽는 규칙이 바뀌면 올린다 — 쌓아 둔 원문을 다시 읽는다

BROKERS = [
    ("미래에셋증권", r"미래에셋"), ("삼성증권", r"삼성증권|SAMSUNG\s*SEC|삼성\s*리서치|\[SAMSUNG\]"), ("한국투자증권", r"한국투자|한투증권|KIS\b"),
    ("NH투자증권", r"NH투자|NH\s*리서치|NH증권"), ("KB증권", r"KB증권|KB\s*리서치"), ("키움증권", r"키움"), ("신한투자증권", r"신한투자|신한금융투자|신한\s*리서치"),
    ("하나증권", r"하나증권|하나금융투자|하나\s*리서치"), ("메리츠증권", r"메리츠"), ("대신증권", r"대신증권|대신\s*리서치"), ("유안타증권", r"유안타"),
    ("교보증권", r"교보증권"), ("IBK투자증권", r"IBK투자|IBK\s*리서치"), ("iM증권", r"iM증권|하이투자"), ("DB증권", r"DB금융투자|DB증권"),
    ("SK증권", r"SK증권"), ("유진투자증권", r"유진투자"), ("LS증권", r"LS증권|이베스트"), ("한화투자증권", r"한화투자"), ("현대차증권", r"현대차증권"),
    ("BNK투자증권", r"BNK투자"), ("상상인증권", r"상상인"), ("다올투자증권", r"다올투자"), ("한양증권", r"한양증권"), ("부국증권", r"부국증권"),
    ("신영증권", r"신영증권"), ("케이프투자증권", r"케이프"), ("흥국증권", r"흥국증권"), ("DS투자증권", r"DS투자"), ("리딩투자증권", r"리딩투자"),
    ("CLSA", r"CLSA"), ("JP모건", r"JP\s*Morgan|JP모건"), ("모건스탠리", r"Morgan\s*Stanley|모건스탠리"), ("골드만삭스", r"Goldman|골드만"),
]
BROKER_RX = [(n, re.compile(rx, re.I)) for n, rx in BROKERS]
CHANNEL_HINT = re.compile(r"증권|리서치|Research|리포트|Report|투자전략|애널리스트", re.I)

OPINION = re.compile(r"(?<![A-Za-z])(Strong\s*Buy|Trading\s*Buy|Buy|Outperform|Overweight|Hold|Neutral|Marketperform|Market\s*Perform|"
                     r"Underperform|Underweight|Reduce|Sell|Not\s*Rated|NR)(?![A-Za-z])|(?<![가-힣])(매수|중립|매도)(?![가-힣])", re.I)   # '순매수' · '매수세' 는 의견이 아니다
OP_NORM = [("Buy", r"strong\s*buy|^buy$|매수|outperform|overweight"), ("Trading Buy", r"trading\s*buy"), ("Hold", r"hold|중립|neutral|market\s*perform|marketperform"),
           ("Sell", r"sell|매도|underperform|underweight|reduce"), ("NR", r"not\s*rated|^nr$")]
NUM = r"(\d{1,3}(?:,\d{3})+|\d{4,7})"
TP_RX = re.compile(r"(?:목표\s*주?\s*가|적정\s*주가|TP|T\.P\.?|Target\s*Price|목표가)\s*(?:\(\s*원\s*\))?\s*[:：]?\s*(?:₩|KRW\s*)?" + NUM + r"\s*(?:원|KRW)?", re.I)
TP_MOVE = re.compile(NUM + r"\s*원?\s*(?:→|->|⇒|에서)\s*" + NUM + r"\s*원?")
CHANGE = re.compile(r"(상향|하향|유지|신규|커버리지\s*개시|Initiat|Upgrade|Downgrade|Maintain)", re.I)
CODE_RX = re.compile(r"(?<![\d])A?(\d{6})(?![\d])")
URL_RX = re.compile(r"https?://\S+")
INDUSTRY = re.compile(r"반도체|디스플레이|2차\s*전지|이차전지|배터리|자동차|조선|해운|철강|화학|정유|건설|기계|방산|원전|전력|유틸리티|통신|인터넷|게임|엔터|미디어|"
                      r"화장품|음식료|유통|은행|보험|증권|지주|제약|바이오|헬스케어|의료기기|항공|운송|소프트웨어|AI|로봇|우주|섬유|의류|"
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


def _name_index(names):
    """수집한 회사 이름 → 코드. 긴 이름부터 맞춰야 'LG' 가 'LG에너지솔루션' 을 먹지 않는다. 두 글자 이름은 앞뒤가 글자가 아닐 때만."""
    pairs = sorted(((n, c) for n, c in names.items() if len(n) >= 2), key=lambda x: -len(x[0]))
    alt = "|".join(re.escape(n) for n, _ in pairs)
    return dict(pairs), (re.compile(r"(?<![가-힣A-Za-z0-9])(" + alt + r")(?![가-힣A-Za-z0-9])") if alt else None)


def parse(text, channel_title="", names=None, codes=None):
    """글 하나 → 리포트 항목들. names: {회사 이름: 코드}, codes: {코드: 회사 이름}(수집한 회사).
    → [{kind('기업'|'산업'), code, name, broker, opinion, tp, tp_prev, change, title, lines, urls}]"""
    names = names or {}
    codes = codes or {}
    nmap, nrx = _name_index(names) if names else ({}, None)
    out = []
    broker0 = broker_of(text, channel_title)
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
        tps = [_num(x) for x in TP_RX.findall(it)]
        mv = TP_MOVE.search(it)
        tp_prev = tp = None
        if mv:
            a, b = _num(mv.group(1)), _num(mv.group(2))
            if a and b and 0.3 < b / a < 3:
                tp_prev, tp = a, b
        if tp is None and tps:
            tp = tps[0]
        op = OPINION.search(it)
        broker = broker_of(it, "") or broker0
        # 상향 · 하향 — 목표가가 '이전 → 새' 로 적혔으면 숫자로, 아니면 '목표' 낱말 가까이의 말로
        if tp_prev and tp:
            change = "상향" if tp > tp_prev else ("하향" if tp < tp_prev else "유지")
        else:
            mtp = re.search(r"목표\s*주?\s*가[^\n]{0,30}?(상향|하향|유지|신규)|(상향|하향)\s*조정", it)
            ch = CHANGE.search(it)
            change = (mtp.group(1) or mtp.group(2)) if mtp else (ch.group(1) if ch else None)
        title = next((l for l in lines if not re.fullmatch(r"\[?[^\]]{0,12}\]?", l) and len(l) >= 6), lines[0] if lines else "")
        title = re.sub(r"^\[[^\]]{1,20}\]\s*", "", title)
        title = re.sub(r"\s*\((?=[^)]*(?:Buy|BUY|Hold|Sell|매수|중립|매도|TP|목표|NR))[^)]*\)?\s*$", "", title)   # 끝의 '(Buy, TP 112,000원)'
        if name:
            title = re.sub(r"^\s*" + re.escape(name) + r"\s*(?:\(\s*A?\d{6}\s*\))?\s*[:：\-—–]\s*", "", title)      # 앞의 '두산에너빌리티:' — 종목 칸이 따로 있다
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
        if kind == "기업" and not (tp or op or re.search(r"리포트|Report|보고서|코멘트|Comment|프리뷰|Preview|리뷰|Review|실적|분석", it, re.I)):
            continue                      # 종목 이름만 스친 글(시황 · 뉴스 링크)은 리포트가 아니다
        out.append({"kind": kind, "code": code, "name": name, "broker": broker, "opinion": _norm_op(op.group(1) or op.group(2)) if op else None,
                    "tp": tp, "tp_prev": tp_prev, "change": change, "title": title,
                    "lines": body, "urls": urls,
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


def build(names, codes):
    """쌓인 글 → 리포트 항목(글마다 parse). 같은 증권사 · 종목 · 날짜 · 목표가는 하나로(채널 둘이 같은 리포트를 올린 것)."""
    rows, seen = [], set()
    for m in raw_messages():
        for r in parse(m.get("text", ""), m.get("channel_title", ""), names, codes):
            k = (r["broker"], r["code"] or r["title"][:30], m["date"][:10], r["tp"])
            if k in seen:
                continue
            seen.add(k)
            r.update(date=m["date"], channel=m.get("channel_title"), msg_url=m.get("url"), msg_id=m.get("id"))
            rows.append(r)
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


def _collect_web(days=180, log=print, max_pages=80):
    """공개 채널마다 지난번 뒤의 새 글 — 최신 쪽부터 '?before=' 로 거슬러 올라간다(처음이면 days 일 전까지). 요청 사이 1초."""
    import requests
    st = _load_state()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    got = 0
    names = web_channels()
    log("웹 미리보기 채널 %d곳: %s" % (len(names), ", ".join(names)))
    for name in names:
        key = "web:" + name.lower()
        last = int(st["channels"].get(key, {}).get("last", 0))
        before, msgs, title, pages = None, {}, name, 0
        while pages < max_pages:
            try:
                r = requests.get(WEB % name, params={"before": before} if before else None, headers=UA, timeout=25)
            except Exception as e:
                log("  %s — 못 읽음: %s" % (name, e))
                break
            pages += 1
            if r.status_code != 200 or "tgme_widget_message" not in r.text:
                if pages == 1:
                    log("  %s — 공개 채널 미리보기가 없다(비공개 · 이름 틀림 · 미리보기 막힘)" % name)
                break
            title, ms = _web_parse(r.text, name)
            if not ms:
                break
            for m in ms:
                if m["id"] > last and (last or not m["date"] or m["date"] >= since):
                    msgs[m["id"]] = m
            oldest = ms[0]
            if oldest["id"] <= last or (not last and oldest["date"] and oldest["date"] < since) or oldest["id"] <= 1:
                break
            before = oldest["id"]
            time.sleep(1.0)
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
        st["channels"][key] = {"title": title, "last": max([last] + list(msgs)), "at": time.time(), "via": "web"}
        log("  %s(%s) — 새 글 %d, %d쪽" % (title[:24], name, len(rows), pages))
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


def collect(days=180, per_channel=3000, list_only=False, log=print):
    """로그인 세션이 있으면 Telethon(구독 채널 전부), 없으면 웹 미리보기(적어 둔 공개 채널)."""
    if not session_exists():
        if list_only:
            log("웹 미리보기 채널: %s" % (", ".join(web_channels()) or "(없음 — .env TELEGRAM_CHANNELS 또는 리포트_채널.txt 에 적는다)"))
            return 0
        return _collect_web(days, log)
    import asyncio
    return asyncio.run(_collect(days, per_channel, list_only, log))
