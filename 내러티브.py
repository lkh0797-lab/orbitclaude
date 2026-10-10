# -*- coding: utf-8 -*-
"""
내러티브 — 이 종목 소식 피드. 대중이 접한 소식(언론 기사 제목 · 증권사 리포트 · 공시)과
회사의 공식 문서(정기보고서)를 날짜순 한 줄로 세운다(설계: docs/superpowers/specs/2026-10-11-story-feed-design.md 2절).

  classify_news(row, code, name)        KIS 뉴스 제목 한 줄 → 분류(art · mention · disc · alert · 잡음 여섯)
  disc_index_update(disc_dir)           .cache/공시목록 닫힌 분기 → 회사별 버킷 색인 _by_code/b00..63.jsonl
  disc_rows(code, disc_dir)             색인 + 색인에 아직 없는 파일(열린 분기) → 그 회사 공시
  adjusted · day_moves · reaction       분할 보정 종가 · 그날 등락 · 소식 반응(당일 · 5거래일, 시장 중앙 대비)
  build_mkt_med(read_px, codes, since)  전 종목 일간 등락 중앙값(시장)
  vocab_links · match_terms · hot_words 회사 보고서 낱말 궤적(.cache/vocab)과 기사 제목을 잇는다
  build_feed(...)                       합쳐서 화면 자료(2.6 응답 꼴)

표준 라이브러리만(뷰어는 32비트 Python 3.11). 서버 전역에 기대지 않는다 — 서버가 자료와 함수를 넘긴다.
점수 · 매수 신호는 내지 않는다(새 문장 기반 선행 점수는 표본 외 검증 실패 — README '선행 점수').
KIS 뉴스 제목은 언론사 저작물이고 증권사 계정으로 받은 자료 — 이 PC 의 본인 분석용(유료 상품에 넣지 않는다).
기사 본문은 받지 않는다. 'search' 는 사용자가 누를 때 브라우저가 여는 네이버 뉴스 검색 링크일 뿐이다.
"""
import bisect
import datetime as dt
import json
import os
import re
import shutil
import time
import urllib.parse
import zlib
from array import array
from collections import Counter

FEED_V = 2                # 2 — 시각 모르는 공시 이틀 반응 · 공시 분류 보탬 · 크기 덜기 순서 · gist []/first
NEWS_RULE_V = 2           # 2 — 로봇(장중수급포착 · 52주 신고가 경신) · 상장 안내는 경보 아님 · 별칭 · 목록 · 광고 · 시황 보탬
INDEX_V = 1
BUCKETS = 64
MKT_MIN = 20              # 시장 중앙값을 세우는 최소 종목 수(그보다 적은 날은 뺀다)
REACT_GAP = 10            # 소식 날짜와 반응일이 달력으로 이보다 멀면(거래 정지 · 상장 전) 반응을 안 잰다
HOT_DAYS = 90             # 요즘 이야기 — 최근 며칠 제목에서 낱말을 센다
PX_DAYS = 365             # 관심도 띠 · px.series 기간
MAX_HIDDEN = 1500         # 숨김(잡음) 뉴스는 최근 것만 — 005930 처럼 하루 150건 넘는 종목의 응답 크기
MAX_NEWS = 2500           # 보이는 뉴스도 최근 것만(캐시는 지우지 않고 계속 쌓이므로)
MAX_BYTES = 1000000       # 응답 크기 한도 — 넘으면 숨김 → 옛 리포트 머리만 → 옛 공시 → 보이는 뉴스 순으로 덜어 낸다
REPORT_FULL_DAYS = 90     # 크기를 덜 때 이보다 오래된 리포트는 머리만(lines · est · risks · concl · sections 를 비우고 slim)
DISC_KEEP_YEARS = 3       # 크기를 덜 때 이보다 오래된 공시부터(분류 없는 것 먼저) 뺀다
NEWS_KEEP_DAYS = 30       # 보이는 뉴스는 최근 이만큼을 마지막까지 지킨다(그래도 넘으면 그때 덜어 낸다)
AFTER_CLOSE = "1530"      # 이 시각(HHMM) 뒤 소식은 다음 거래일에 반응

DART_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=%s"
NAVER_NEWS = "https://search.naver.com/search.naver?where=news&query="

DISC_PC = ("F", "G", "I")           # 거래소 공시 · 코스닥 공시 · 공시(파생 시장조치)
HIDE_K = ("info_list", "info_move", "info_echo", "robot", "roundup", "ad")     # 잡음 — 숨김(지우지 않는다)

# ---------------------------------------------------------------- 2.1 뉴스 분류 (2026-10-10 실측 제목 — 010170 1,561행 · 005930 151행)
ALERT_RX = re.compile(r"투자\s?(?:주의|경고|위험)|매매\s?거래\s?정지|거래\s?정지|공매도\s?과열|단기\s?과열|단일\s?계좌|소수\s?계좌|"
                      r"가격제한폭\s?확대|관리\s?종목|불성실\s?공시|상장\s?적격성|정리\s?매매|시장\s?경보|VI\s?발동")
AD_RX = re.compile(r"스탁론|최대\s?\d+\s?배|\d\s?배\s?(?:레버리지|부스터)|레버리지\s?(?:충전|선점)|대환|신용\s?담보|"
                   r"무료\s?(?:공개|강연|추천)|강연회|이벤트|경품|룰렛|한경\s?유레카|MBN\s?골드|"
                   r"(?:베스트|최우수)\s?전문가|전문가가\s?(?:엄선|직접)|전문가의\s?인사이트|이 정보 하나로|"
                   r"딜사이트\s?(?:S|에스)\b|평생\s?(?:연금|무료)|투자\s?지원금|주식투자\s?아카데미|온라인\s?특강|"
                   r"론칭\s?기념|할인\s?마감")
ROBOT_RX = re.compile(r"^\d{1,2}일, (?:외국인|기관) (?:코스닥|코스피|거래소|유가)에서|^\d{1,2}일, (?:거래소|코스닥) (?:외국인|기관)|"
                      r"<코>|<유>|상한가 진입|하한가 진입|현재 코스(?:닥|피)은 \d+:\d+|\[(?:개장|정오|마감) 시황\]|"
                      r"^\[장중수급포착\]|^'[^']+'\s?52주 신고가 경신|^\S+, 상한가 기록$")   # 오른 날에만 나오는 틀 기사 — 띠가 주가를 다시 그리지 않게
STRIP_RX = re.compile(r"^\S+\(\d{6}\)\s+[+-]?\d")                       # 'X(069540)  +5.91%, Y +3.43%, …' 테마 시세 띠
MOVE_RX = re.compile(r"\(\d{6}\)\s*(?:소폭|상승폭|하락폭|급등|급락|상승 출발|하락 출발|강세|약세|낙폭|상한가|하한가)")
ECHO_RX = re.compile(r"소유주식수 변동|대량보유자|특정증권등")
LIST_RX = re.compile(r"상위\s?\d*\s?종목|상위종목|인기검색|증시요약|특징주\s?[AB]\b|특징주★|테마동향|스케줄|변동성완화장치|"
                     r"신고가 종목|수익률 상위|순매수,도|매수체결|매도체결|주식대차거래|하락률 상위|상승률 상위|특이\s?종목|"
                     r"거래량 증가 종목|매수/매도 상위|개장전★|주요 종목 공시|모닝 브리핑|신규추천 종목|^\[\d{4}주요일정\]")
ROUNDUP_RX = re.compile(r"\[증시키워드\]|마감시황|주요공시\]|코스피|코스닥|증시|\[시황|\[(?:개장|정오|마감|오전|오후)\s?시황\]|국장|\[투자360\]|"
                        r"\[주식 초고수는 지금\]|시황레이더\]|마감체크\]|오늘의 메모|기업공시 \[|증시일정|^\[표\]|"
                        r"\[(?:급등락주 짚어보기|베스트&워스트|특징주 & 리포트|전날 애프터마켓)\]")
# pc F/G lc 03 이라도 상장 · 권리 안내(추가상장 · 권리락 …)는 시장조치가 아니다 — 거래소 공시(disc)로 두어 DART 와 겹침을 지운다
LISTING_RX = re.compile(r"추가\s?상장|변경\s?상장|신규\s?상장|재\s?상장|권리락|배당락|권배락|액면\s?(?:분할|병합)")
# 회사 별칭 — 제목에 이 말이 있으면 이름이 있는 것으로(분류) · 요즘 이야기 낱말에서는 뺀다
ALIAS = {"005930": ("삼전",), "000660": ("하이닉스", "하닉"), "005380": ("현대차",)}


def _nm(s):
    """이름 비교용 — '(주)' · 공백 · 가운뎃점을 지운다."""
    return re.sub(r"\(주\)|㈜|[\s·ㆍ]", "", s or "")


def _norm(s):
    """접기 · 겹침 비교용 — 공백 · 기호를 지운 소문자."""
    return re.sub(r"[\W_]+", "", s or "").lower()


def classify_news(row, code, name):
    """뉴스 한 줄(Tech 캐시 rows 꼴) → 분류 k. 순서: 공시(F/G/I) → 광고 → 로봇 → 인포스탁(목록 · 시세 띠 · 되풀이)
    → 시황(이름 없을 때) → 이름 있음 art → 나머지 mention. 인포스탁은 lc 01/02 가 섞여 있어 제목 꼴로 가른다."""
    t = row.get("title") or ""
    pc, lc, src = row.get("pc") or "", row.get("lc") or "", row.get("src") or ""
    if pc in DISC_PC:
        return "alert" if ALERT_RX.search(t) or (pc in ("F", "G") and lc == "03" and not LISTING_RX.search(t)) else "disc"
    if AD_RX.search(t) or ("딜사이트" in src and lc == "15"):
        return "ad"
    if ROBOT_RX.search(t):
        return "robot"
    has = bool(_nm(name)) and (_nm(name) in _nm(t) or any(a in t for a in ALIAS.get(code, ())))
    if src == "인포스탁" or pc == "7":
        if STRIP_RX.search(t) or MOVE_RX.search(t):
            return "info_move"
        if ECHO_RX.search(t):
            return "info_echo"
        if LIST_RX.search(t):
            return "info_list"
    if not has and ROUNDUP_RX.search(t):
        return "roundup"
    return "art" if has else "mention"


# ---------------------------------------------------------------- 2.2 공시 색인 (.cache/공시목록 → 회사별 버킷)
DISC_FILE_RX = re.compile(r"^(A001|B|I)_(\d{4})Q([1-4])\.jsonl$")


def _bucket(code):
    return zlib.crc32(code.encode("utf-8")) % BUCKETS


def _disc_files(disc_dir):
    """[(파일명, 종류, 닫힘)] — 닫힌 분기는 옆에 .done 표지(내용이 다시 바뀌지 않음)."""
    try:
        names = set(os.listdir(disc_dir))
    except OSError:
        return []
    out = []
    for f in sorted(names):
        m = DISC_FILE_RX.match(f)
        if m:
            out.append((f, m.group(1), (f + ".done") in names))
    return out


def _stat(p):
    st = os.stat(p)
    return [st.st_size, int(st.st_mtime)]


def _read_manifest(idx):
    try:
        with open(os.path.join(idx, "_manifest.json"), "r", encoding="utf-8") as fh:
            m = json.load(fh)
        return m if isinstance(m, dict) and m.get("v") == INDEX_V and isinstance(m.get("files"), dict) else None
    except (OSError, ValueError):
        return None


def _write_json(p, d, tries=4):
    """원자적 쓰기 — 남이 읽는 중이면 Windows 가 교체를 거부하니 몇 번 다시."""
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    try:
        for k in range(tries):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if k == tries - 1:
                    raise
                time.sleep(0.2 * (k + 1))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _compact(r, kind):
    """원본 한 줄 → 색인 줄 [code, rcept_dt, rcept_no, kind, report_nm(공백 정리), flr_nm(회사 이름과 다를 때만)]."""
    code = (r.get("stock_code") or "").strip()
    if not code:
        return None, None
    flr = (r.get("flr_nm") or "").strip()
    if flr == (r.get("corp_name") or "").strip():
        flr = ""
    return code, [code, r.get("rcept_dt") or "", r.get("rcept_no") or "", kind,
                  " ".join((r.get("report_nm") or "").split()), flr]


def _source_rows(path, kind):
    """원본 한 파일 → (code, 색인 줄) — 한 번에 한 파일만 메모리에(최대 약 6MB)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    for ln in raw.decode("utf-8", "replace").splitlines():
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        code, row = _compact(r, kind)
        if code:
            yield code, row


def _dump_row(row):
    return json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"


def disc_index_update(disc_dir):
    """색인을 맞춘다. 처음(또는 manifest 의 닫힌 파일 크기 · 시각이 바뀌었으면)은 _by_code.tmp/ 에 다 만든 뒤 이름 바꿈,
    그 밖엔 manifest 에 없는 닫힌 파일만 버킷에 덧붙인다. 반환 {"mode": full|add|none, "files", "rows", "secs"}."""
    t0 = time.time()
    idx = os.path.join(disc_dir, "_by_code")
    files = _disc_files(disc_dir)
    closed = [(f, k) for f, k, done in files if done]
    man = _read_manifest(idx)
    full = man is None
    if not full:
        for f, st in man["files"].items():
            p = os.path.join(disc_dir, f)
            try:
                if _stat(p) != list(st) or not os.path.exists(p + ".done"):
                    full = True
                    break
            except OSError:
                full = True
                break
    if full:
        tmp = idx + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        fhs = [open(os.path.join(tmp, "b%02d.jsonl" % b), "w", encoding="utf-8", newline="\n", buffering=1 << 18)
               for b in range(BUCKETS)]         # 큰 버퍼 — 구글 드라이브는 작은 쓰기가 느리다(버킷 64 × 256KB)
        n, mf = 0, {}
        try:
            for f, kind in closed:
                p = os.path.join(disc_dir, f)
                st = _stat(p)
                for code, row in _source_rows(p, kind):
                    fhs[_bucket(code)].write(_dump_row(row))
                    n += 1
                mf[f] = st
        finally:
            for fh in fhs:
                fh.close()
        _write_json(os.path.join(tmp, "_manifest.json"), {"v": INDEX_V, "files": mf, "at": int(time.time())})
        old = None
        if os.path.isdir(idx):
            old = "%s.old%d" % (idx, int(time.time()))
            os.replace(idx, old)
        os.replace(tmp, idx)
        if old:
            shutil.rmtree(old, ignore_errors=True)
        return {"mode": "full", "files": len(mf), "rows": n, "secs": round(time.time() - t0, 2)}
    new = [(f, k) for f, k in closed if f not in man["files"]]
    if not new:
        return {"mode": "none", "files": 0, "rows": 0, "secs": round(time.time() - t0, 2)}
    n = 0
    for f, kind in new:            # 덧붙인 뒤 manifest 를 못 쓰고 죽으면 다음에 또 덧붙는다 — disc_rows 가 rcept 로 겹침을 지운다
        p = os.path.join(disc_dir, f)
        st = _stat(p)
        by = {}
        for code, row in _source_rows(p, kind):
            by.setdefault(_bucket(code), []).append(_dump_row(row))
            n += 1
        for b, lines in by.items():
            with open(os.path.join(idx, "b%02d.jsonl" % b), "a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(lines))
        man["files"][f] = st
    man["at"] = int(time.time())
    _write_json(os.path.join(idx, "_manifest.json"), man)
    return {"mode": "add", "files": len(new), "rows": n, "secs": round(time.time() - t0, 2)}


def disc_index_ready(disc_dir):
    return _read_manifest(os.path.join(disc_dir, "_by_code")) is not None


def disc_sig(disc_dir):
    """색인 manifest 시각 + 열린 분기(.done 없는 파일) 크기 · 시각 — story 캐시 sig 한 조각."""
    parts = []
    try:
        parts.append("m%d" % int(os.path.getmtime(os.path.join(disc_dir, "_by_code", "_manifest.json"))))
    except OSError:
        parts.append("m0")
    for f, _, done in _disc_files(disc_dir):
        if not done:
            try:
                parts.append("%s:%d:%d" % tuple([f] + _stat(os.path.join(disc_dir, f))))
            except OSError:
                pass
    return ",".join(parts)


def disc_rows(code, disc_dir):
    """그 회사 공시 [{"d","rcept","kind","title","flr"}] 날짜 내림차순. 색인이 없으면 None(서버가 만들기 시작).
    색인 버킷 줄 중 그 코드 + 색인에 아직 없는 파일(열린 분기 · 덧붙이기 전 닫힌 분기)은 bytes 로 바로 훑는다."""
    idx = os.path.join(disc_dir, "_by_code")
    man = _read_manifest(idx)
    if man is None:
        return None
    out = {}
    pre = ('["%s",' % code).encode("utf-8")
    try:
        with open(os.path.join(idx, "b%02d.jsonl" % _bucket(code)), "rb") as fh:
            data = fh.read()
    except OSError:
        data = b""
    for ln in data.split(b"\n"):
        if ln.startswith(pre):
            try:
                _, d, rc, kind, title, flr = json.loads(ln.decode("utf-8"))
            except (ValueError, TypeError):
                continue
            out.setdefault(rc, {"d": d, "rcept": rc, "kind": kind, "title": title, "flr": flr})
    needles = [('"stock_code": "%s"' % code).encode("utf-8"), ('"stock_code":"%s"' % code).encode("utf-8")]
    for f, kind, _ in _disc_files(disc_dir):
        if f in man["files"]:
            continue
        try:
            with open(os.path.join(disc_dir, f), "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if not any(nd in raw for nd in needles):
            continue
        for ln in raw.split(b"\n"):
            if any(nd in ln for nd in needles):
                try:
                    _, row = _compact(json.loads(ln.decode("utf-8")), kind)
                except (ValueError, AttributeError):
                    continue
                if row:
                    out.setdefault(row[2], {"d": row[1], "rcept": row[2], "kind": kind, "title": row[4], "flr": row[5]})
    return sorted(out.values(), key=lambda r: (r["d"], r["rcept"]), reverse=True)


# ---------------------------------------------------------------- 2.3 주가
def _d8(x):
    if x is None:
        return None
    if isinstance(x, (dt.date, dt.datetime)):
        return x.strftime("%Y%m%d")
    s = re.sub(r"\D", "", str(x))[:8]
    return s if len(s) == 8 else None


def _ord(d):
    return dt.date(int(d[:4]), int(d[4:6]), int(d[6:8])).toordinal()


def _r2(x):
    return None if x is None else round(x, 2)


def adjusted(px):
    """{YYYYMMDD: 종가} → [(날짜, 보정 종가)] 날짜순. 하루 ±30% 를 넘는 움직임(가격제한폭 밖 = 분할 · 병합)은
    그 앞을 비율로 맞춘다(기록채점._adjusted 와 같은 규칙 — 상장 직후 5거래일은 건드리지 않는다)."""
    clean = {}
    for k, v in (px or {}).items():
        d = _d8(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if d and v > 0:
            clean[d] = v
    ds = sorted(clean)
    adj = [clean[d] for d in ds]
    for i in range(len(ds) - 1, 5, -1):
        a, b = adj[i - 1], adj[i]
        if a and b and not (0.69 <= b / a <= 1.31):
            k = b / a
            for j in range(i):
                adj[j] *= k
    return list(zip(ds, adj))


def day_moves(series, mkt=None):
    """{YYYYMMDD: {"chg": 그날 등락 %, "mkt": 그날 시장 중앙 % 또는 None}} — 거래일만."""
    out, prev = {}, None
    for d, c in series:
        out[d] = {"chg": _r2((c / prev - 1) * 100) if prev else None, "mkt": _r2((mkt or {}).get(d))}
        prev = c
    return out


def _cum(mkt, days):
    """그 거래일들 시장 중앙 누적 % — 하루라도 없으면 None."""
    ms = [mkt.get(x) for x in days]
    if not ms or any(m is None for m in ms):
        return None
    if len(ms) == 1:
        return _r2(ms[0])
    acc = 1.0
    for m in ms:
        acc *= 1 + m / 100.0
    return _r2((acc - 1) * 100)


def _react(ds, cs, d, after_close, mkt, untimed=False):
    i = bisect.bisect_left(ds, d)
    if after_close and i < len(ds) and ds[i] == d:
        i += 1
    if i >= len(ds) or _ord(ds[i]) - _ord(d) > REACT_GAP:
        return None
    # 시각 모르는 소식(DART 공시 · 정기보고서 대부분)이 거래일에 나왔으면 그날과 다음 거래일 이틀로 잰다 — 장중 · 장 마감 뒤 둘 다 덮는다.
    # 쉬는 날 소식은 다음 거래일 하루(그 전에 나왔으니)
    e = i + 1 if untimed and ds[i] == d else i
    if e >= len(ds):
        return None
    mkt = mkt or {}
    base = cs[i - 1] if i else None
    out = {"day": ds[e], "chg": _r2((cs[e] / base - 1) * 100) if base else None, "mkt": _cum(mkt, ds[i:e + 1]),
           "d5": None, "d5m": None}
    if e > i:
        out.update({"from": ds[i], "timed": False})
    j = e + 4                      # 반응일 포함 5거래일째
    if base and j < len(ds):
        out["d5"] = _r2((cs[j] / base - 1) * 100)
        out["d5m"] = _cum(mkt, ds[i:j + 1])
    return out


def reaction(series, d, after_close=False, mkt=None, untimed=False):
    """소식 날짜 d(휴장이면 다음 거래일, 장 마감 뒤 소식이면 다음 거래일)를 반응일로 잡는다.
    {"day": 반응일, "chg": 그날 등락 %, "mkt": 그날 시장 중앙 %, "d5": 반응일 앞 종가 → 반응일 포함 5거래일째 종가 %,
     "d5m": 같은 5거래일 시장 중앙 누적 %}. 반응일이 아직 없거나(오늘 · 주말 뒤) 너무 멀면 None.
    untimed(시각 모름)이고 d 가 거래일이면 d 앞 종가 → 다음 거래일 종가(이틀)로 재고 "from": d · "timed": False 를 단다
    (chg · mkt 는 이틀 누적, d5 · d5m 은 그 앞 종가부터 다음 거래일 포함 5거래일째까지)."""
    d = _d8(d)
    if not series or not d:
        return None
    return _react([x[0] for x in series], [x[1] for x in series], d, after_close, mkt, untimed)


def build_mkt_med(read_px, codes, since):
    """{YYYYMMDD: 그날 전 종목 등락 중앙값 %} — read_px(code) -> {YYYYMMDD: 종가}. 종목마다 분할 보정 뒤 등락을 모은다
    (한 번에 한 종목만 읽는다). 표본 MKT_MIN 종목 미만인 날 · 달력 10일 넘게 끊긴 뒤 첫 등락은 뺀다."""
    since = _d8(since) or "00000000"
    acc = {}
    for code in codes:
        try:
            s = adjusted(read_px(code))
        except Exception:
            continue
        for i in range(1, len(s)):
            d, c = s[i]
            if d < since:
                continue
            pd_, p = s[i - 1]
            if p > 0 and _ord(d) - _ord(pd_) <= REACT_GAP:
                a = acc.get(d)
                if a is None:
                    a = acc[d] = array("d")
                a.append(c / p - 1)
    out = {}
    for d in sorted(acc):
        xs = sorted(acc[d])
        n = len(xs)
        if n >= MKT_MIN:
            m = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0
            out[d] = round(m * 100, 3)
    return out


# ---------------------------------------------------------------- 2.4 낱말 잇기 (.cache/vocab 낱말 궤적)
def vocab_links(vocab):
    """vocab_view 캐시 → [{"term","first":YYYYMMDD,"first_label":"2022-12 사업보고서","from_start","take","now","snip"}].
    from_start = 첫 언급이 모은 자료의 첫 보고서(그 앞은 자료가 없어 '언제부터'를 모른다 — 화면은 '자료 처음부터 있음').
    개명은 새 이름 줄에 "was"(옛 이름)로 둔다. 토큰 찌꺼기(2자 미만 · 첫 문장 없음)는 뺀다."""
    if not isinstance(vocab, dict):
        return []
    reps = vocab.get("reports") or []
    tracks = vocab.get("tracks") or {}

    def rep(i):
        return reps[i] if isinstance(i, int) and 0 <= i < len(reps) else None
    out = []
    for term, tr in tracks.items():
        snip = " ".join((tr.get("snip_first") or "").split())
        if len(term) < 2 or not snip or (tr.get("renamed_to") or {}).get("t") in tracks:
            continue
        rf, rt = rep(tr.get("first")), rep(tr.get("take"))
        if rf is None:
            continue
        lk = {"term": term, "first": rf["rcept"][:8], "first_label": "%s %s" % (rf.get("stamp", ""), rf.get("label", "")),
              "from_start": tr.get("first") == 0, "take": rt["rcept"][:8] if rt else None, "now": tr.get("now"),
              "snip": snip if len(snip) <= 200 else snip[:199] + "…"}
        was = (tr.get("renamed_from") or {}).get("t")
        if was:
            lk["was"] = was
        out.append(lk)
    return out


_TERMS_RX = {}


def _terms_rx(links):
    key = tuple((lk["term"], lk.get("was") or "") for lk in links)
    hit = _TERMS_RX.get(key)
    if hit:
        return hit
    pats = []
    for lk in links:
        for w in (lk["term"], lk.get("was")):
            if w:
                pats.append((w, lk["term"]))
    pats.sort(key=lambda p: -len(p[0]))            # 긴 말 먼저(HBM4 가 HBM 보다 먼저)
    parts, owner = [], []
    for w, term in pats:
        if re.fullmatch(r"[A-Za-z0-9]{1,4}", w):    # 짧은 영문 · 숫자 말은 낱말 경계로
            p = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(w)
        else:                                        # 한글은 띄어쓰기 무시 부분 일치
            p = r"\s*".join(re.escape(ch) for ch in w if not ch.isspace())
        parts.append("(%s)" % p)
        owner.append(term)
    hit = (re.compile("|".join(parts)) if parts else None, owner)
    if len(_TERMS_RX) > 16:
        _TERMS_RX.clear()
    _TERMS_RX[key] = hit
    return hit


def match_terms(title, links):
    """제목에 걸린 회사 낱말(term) — 회사마다 한 번 만든 정규식."""
    if not title or not links:
        return []
    rx, owner = _terms_rx(links)
    out = []
    for m in rx.finditer(title):
        t = owner[m.lastindex - 1]
        if t not in out:
            out.append(t)
    return out


WORD_RX = re.compile(r"[가-힣A-Za-z0-9]{2,}")
TAG_RX = re.compile(r"\[[^\]]{0,16}\]|<[^>]{0,8}>|\s-\s.*$|-\s?[가-힣A-Za-z]{2,8}(?:증권|證)?\s*$")
NUM_RX = re.compile(r"\d+(?:[.,]\d+)*(?:[가-힣]{1,3}|Q\d*)?")          # 355억 · 2분기 · 52주 · 3Q26 (5G · 6G 는 둔다)
STEM_LONG = ("에서", "으로", "까지", "부터", "에도", "에는", "에게", "과의", "와의", "이다", "했다", "한다")
STEM_ONE = ("에", "의", "은", "는", "을", "를", "도", "향")
STOP = set("""특징주 주가 상승 하락 강세 약세 급등 급락 목표가 목표주가 코스피 코스닥 외국인 기관 개인 순매수 순매도 매수 매도
장중 장초반 초반 출발 마감 종합 투자 투자자 기대 기대감 전망 수혜 수혜주 관련주 테마 테마주 신고가 상한가 하한가 거래 거래량
증권 증권가 증권사 리포트 브리핑 리포트랩 투자의견 의견 유지 상향 하향 대비 올해 내년 작년 지난해 분기 실적 영업익 영업이익
순이익 순익 매출 매출액 연속 동시 증시 시장 업종 종목 주식 일제히 줄상승 동반 이날 오늘 전일 소식 확대 증가 감소 성장
본격화 가속 행진 수급 장중수급포착 수급포착 마감체크 시황 분석 이유 이번 최근 현재 이후 당일 단독 속보 뉴스 기업 회사 대표
한국 미국 국내 글로벌 세계 시대 다음 기록 돌파 최대 최고 사상 역대 경신 전년 반등 회복 하락세 상승세 주목 관심 부각 들썩
훈풍 효과 영향 우려 부담 가능성 위해 통해 대한 따른 관련 위한 이상 규모 억원 조원 만원 Not Rated Buy Hold Sell NR None
Preview Review 종목NOW 투자360 일부 반납 차익실현 두자릿수 연일 일제 동반강세 급상승 반짝 상한 하한 52주 개미 투심 매수세
매도세 외인 사자 팔자 기대에 공략 추진 진입 마련 발표 공개 선정 참여 체결 계약 결정 공시 제출 개최 예정 완료 착수
협력 만에 등에""".split())


def _stem1(w):
    for s in STEM_LONG:
        if w.endswith(s) and len(w) - len(s) >= 2:
            return w[:-len(s)]
    for s in STEM_ONE:
        if w.endswith(s) and len(w) - 1 >= 2:
            return w[:-1]
    if w.endswith("주") and len(w) >= 4:            # 광통신주 → 광통신 (수주 · 방산주 같은 짧은 말은 둔다)
        return w[:-1]
    return w


def _stem(w):
    for _ in range(3):                              # 광통신주도 → 광통신주 → 광통신 (꼬리가 겹쳐 붙은 말)
        s = _stem1(w)
        if s == w:
            break
        w = s
    return w


def _words(title, nm, alias=()):
    t = TAG_RX.sub(" ", title or "")
    out = set()
    for w in WORD_RX.findall(t):                    # '株' · '證' · '美' 같은 한자는 낱말 밖이라 꼬리가 저절로 떨어진다
        w = _stem(w)
        if len(w) < 2 or w in STOP or NUM_RX.fullmatch(w) or w.endswith("증권") or w.endswith("투자증권"):
            continue
        if nm and (nm in w or nm.startswith(w)):    # 회사 이름 · 앞 조각('삼성' · 'SK') — 뒤 조각인 '광통신' 같은 테마 말은 둔다
            continue
        if any(a in w for a in alias):              # 회사 별칭('삼전' · '삼전닉스')
            continue
        out.add(w)
    return out


def hot_words(items, since, name, links, top=12, code=""):
    """기간(since 이후) 보이는 뉴스(art · mention) · 리포트 제목에서 낱말을 소식 수로 센다(2건 이상만).
    회사 이름 · 별칭(ALIAS) · 불용어 · 숫자는 뺀다. [{"w","n","vocab": link | None}] — 회사 보고서 낱말과 맞으면 vocab 을 붙인다."""
    since = _d8(since) or ""
    nm = _nm(name)
    alias = ALIAS.get(code, ())
    cnt = Counter()
    for it in items:
        if it.get("d", "") < since or it.get("hide"):
            continue
        if it.get("type") == "news" and it.get("k") not in ("art", "mention"):
            continue
        if it.get("type") not in ("news", "report"):
            continue
        cnt.update(_words(it.get("title"), nm, alias))
    by = {lk["term"]: lk for lk in links or ()}
    out = []
    for w, n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < 2 or len(out) >= top:
            break
        lk = by.get(w)
        if lk is None:
            ts = match_terms(w, links)
            lk = by.get(ts[0]) if ts else None
        out.append({"w": w, "n": n, "vocab": lk})
    return out


# ---------------------------------------------------------------- 2.5 합치기
def _strip_co(t, name):
    """KIS 공시 제목 앞 '대한광통신(주) ' 를 뗀다(이 회사 화면이니)."""
    m = re.match(r"^\s*(\S+?)(?:\(주\)|㈜)?\s+(.+)$", t or "")
    if m and _nm(m.group(1)) == _nm(name):
        return m.group(2).strip()
    return (t or "").strip()


def _disc_key(t):
    """KIS '(정정)유상증자결정(주주배정후 …)' ↔ DART '[기재정정]주요사항보고서(유상증자결정)' 를 맞대는 꼴."""
    t = re.sub(r"^\s*(?:\((?:기재)?정정\)|\[(?:기재정정|첨부정정|첨부추가|정정|발행조건확정)\])\s*", "", t or "")
    t = re.sub(r"^주요사항보고서\s*\((.*)\)\s*$", r"\1", t)
    return _norm(t)


def _same_disc(a, b):
    if not a or not b:
        return False
    if a == b:
        return True
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    return len(s) >= 4 and l.startswith(s)


# 공시 분류 보탬 — 호재.classify 가 (None, …) 일 때만 이 탭에서 쓴다(호재 탭 규칙은 그대로). (g, cat, w, desc, 정규식)
DISC_EXTRA = [
    ("bad", "희석", 0, "", re.compile(r"(?:전환청구권|신주인수권|교환청구권)\s*행사(?!가액|기간|자)|(?:전환|행사|교환)가액의?\s*조정")),
    ("bad", "상장 위험", 0, "", re.compile(r"불성실\s*공시\s*법인\s*지정")),
    ("good", "자사주소각", 3, "소각은 되돌릴 수 없다. 매입보다 강한 주주환원", re.compile(r"주식\s*소각\s*결정")),
    ("good", "메자닌 소각", 3, "잠재 물량(오버행) 해소", re.compile(r"발행\s*후\s*만기\s*전\s*사채\s*취득")),
    ("check", "소송 판결", 1, "승소인지 패소인지는 본문을 봐야 한다", re.compile(r"소송\s*등의\s*판결")),
]
# 제목만으론 방향을 모르는 '호재' 범주 — 이 탭에선 확인으로(실적 미달 · 배당 축소 · 내부자 매도도 같은 제목이다)
GOOD_SOFT = ("실적 공시", "배당확대", "내부자 매수", "대량보유 변동", "투자판단 주요사항")


def _disc_extra(title):
    for g, cat, w, desc, rx in DISC_EXTRA:
        if rx.search(title or ""):
            return (g, cat, w, desc)
    return None


def _report_url(r):
    for u in r.get("urls") or ():
        if u and "t.me/" not in u:
            return u
    return None


def _search(title):
    """네이버 뉴스 검색 링크. 한글은 그대로 두고(IRI — 브라우저가 열 때 인코딩한다) ASCII 기호 · 공백만 % 인코딩
    — 다 인코딩하면 한 글자 9바이트라 005930 처럼 기사가 많은 종목은 응답이 1MB 를 넘는다."""
    return NAVER_NEWS + "".join(ch if ord(ch) > 127 else urllib.parse.quote(ch, safe="") for ch in (title or ""))


def _fold(rows):
    """같은 날 같은 제목(공백 · 기호 정규화)은 하나로 — 가장 이른 시각 행을 남기고 건수 n."""
    groups = {}
    for r in rows:
        k = (r.get("d") or "", _norm(r.get("title")))
        g = groups.get(k)
        if g is None:
            groups[k] = [r, 1]
        else:
            g[1] += 1
            if (r.get("t") or "", r.get("id") or "") < (g[0].get("t") or "", g[0].get("id") or ""):
                g[0] = r
    return list(groups.values())


def build_feed(code, name, *, today, news=None, news_meta=None, reports=(), discs=None, filings=(), gists=None,
               series=(), mkt=None, links=(), classify_disc=None, contracts=None,
               max_hidden=MAX_HIDDEN, max_news=MAX_NEWS, max_bytes=MAX_BYTES):
    """소식 피드(2.6 응답 꼴). news = Tech 캐시 rows(없으면 None) · news_meta = 캐시 머리 · reports = 리포트 항목 복사본 ·
    discs = disc_rows() · filings = 정기보고서 목록(S.co.reports 꼴) · series = adjusted() ·
    gists = {rcept: [gist 항목] 또는 {"gist": [...], "first": 첫 보고서인가}} — 지금 판 요약이 있는 것만(빈 [] = 요약할 변화 없음) ·
    mkt = build_mkt_med() · links = vocab_links() · classify_disc(title) -> (g, cat, w, desc) · contracts = {rcept: 계약 칸}."""
    today = _d8(today) or dt.date.today().strftime("%Y%m%d")
    series = list(series or ())
    ds, cs = [x[0] for x in series], [x[1] for x in series]
    mkt = mkt or {}
    links = list(links or ())
    gists, contracts = gists or {}, contracts or {}

    def react(d, t="", untimed=False):
        return _react(ds, cs, d, bool(t) and t >= AFTER_CLOSE, mkt, untimed) if ds and d else None

    def cls(title):
        g = classify_disc(title) if classify_disc else None
        g = tuple(g) if g else (None, None, 0, "")
        if g[0] is None:
            g = _disc_extra(title) or g
        if g[0] == "good" and g[1] in GOOD_SOFT:
            g = ("check",) + g[1:]
        return {"g": g[0], "cat": g[1], "w": g[2], "desc": g[3]}

    items = []

    # 뉴스 — 분류 · 접기. 공시 제공사(F/G/I)는 아래 공시 · 경보로
    news_items, krx, alerts = [], [], []
    for r in news or ():
        if len(r.get("d") or "") != 8:
            continue
        k = classify_news(r, code, name)
        row = {"id": r.get("id") or "", "d": r.get("d") or "", "t": (r.get("t") or "")[:4], "title": r.get("title") or "",
               "src": r.get("src") or "", "k": k, "c1": r.get("c1") or ""}
        (alerts if k == "alert" else krx if k == "disc" else news_items).append(row)
    vis, hid = [], []
    for r, n in _fold(news_items):
        hide = r["k"] in HIDE_K
        it = {"id": "n:" + r["id"], "type": "news", "d": r["d"], "t": r["t"], "title": r["title"], "src": r["src"],
              "hide": hide, "n": n, "tone": 0, "k": r["k"]}
        if not hide:
            it.update(c1=r["c1"], search=_search(r["title"]))
        (hid if hide else vis).append(it)
    key = lambda it: (it["d"], it["t"], it["id"])
    vis.sort(key=key, reverse=True)
    hid.sort(key=key, reverse=True)
    cut_news, cut_hidden = max(0, len(vis) - max_news), max(0, len(hid) - max_hidden)
    news_days = Counter(it["d"] for it in vis)      # 날짜별 보이는 뉴스 — 덜어 내기 전 전부로 센다(관심도 띠 · counts)
    items += vis[:max_news] + hid[:max_hidden]

    # 공시 — DART 색인 + KIS 쪽 거래소 공시(같은 날 DART 와 제목이 겹치면 버리고 그 시각만 빌린다).
    # 정기공시(A001)가 수집한 정기보고서와 같은 접수번호면 정기보고서 줄 하나로(요약 · 본문 열기가 있는 쪽)
    frc = {f.get("rcept") for f in filings or ()}
    dart = [x for x in discs or () if x["rcept"] not in frc]
    by_day = {}
    for x in dart:
        by_day.setdefault(x["d"], []).append(x)
    dart_t = {}

    def borrow(r, hit):
        if r["t"] and (hit["rcept"] not in dart_t or r["t"] < dart_t[hit["rcept"]]):
            dart_t[hit["rcept"]] = r["t"]

    # 경보 — 같은 날 시장본부(코스닥 · 유가증권)가 DART 에 낸 같은 안내가 있으면 DART 줄 하나로(시각만 빌린다)
    for r, n in _fold(alerts):
        title = _strip_co(r["title"], name)
        k = _disc_key(title)
        hit = next((x for x in by_day.get(r["d"], ())
                    if "시장본부" in (x.get("flr") or "") and _same_disc(k, _disc_key(x["title"]))), None)
        if hit is not None:
            borrow(r, hit)
            continue
        items.append({"id": "a:" + r["id"], "type": "alert", "d": r["d"], "t": r["t"], "title": title,
                      "src": r["src"], "hide": False, "n": n, "tone": 0})

    for r, n in _fold(krx):
        title = _strip_co(r["title"], name)
        k = _disc_key(title)
        hit = next((x for x in by_day.get(r["d"], ()) if _same_disc(k, _disc_key(x["title"]))), None)
        if hit is not None:
            borrow(r, hit)
            continue
        c = cls(title)
        items.append({"id": "d:k" + r["id"], "type": "disc", "d": r["d"], "t": r["t"], "title": title, "src": r["src"],
                      "hide": False, "n": n, "tone": 1 if c["g"] == "good" else -1 if c["g"] == "bad" else 0,
                      "kind": "KRX", "rcept": None, "url": None, "flr": r["src"], "cls": c, "contract": None})
    for x in dart:
        c = cls(x["title"])
        ct = contracts.get(x["rcept"])
        items.append({"id": "d:" + x["rcept"], "type": "disc", "d": x["d"], "t": dart_t.get(x["rcept"], ""),
                      "title": x["title"], "src": x.get("flr") or "DART", "hide": False, "n": 1,
                      "tone": 1 if c["g"] == "good" else -1 if c["g"] == "bad" else 0,
                      "kind": x.get("kind"), "rcept": x["rcept"], "url": DART_URL % x["rcept"], "flr": x.get("flr") or "",
                      "cls": c, "contract": {k: ct.get(k) for k in ("kind", "title", "amount", "revenue", "pct", "party",
                                                                   "region", "start", "end")} if ct else None})

    # 리포트 — 텔레그램 증권사 리포트 요약 그대로
    seen = set()
    for r in reports or ():
        d = (r.get("date") or "")[:10].replace("-", "")
        if len(d) != 8:
            continue
        if r.get("msg_url"):
            rid = "r:" + re.sub(r"^https?://t\.me/", "", r["msg_url"])
        else:
            rid = "r:%s:%08x" % (d, zlib.crc32((r.get("title") or "").encode("utf-8")))
        k, j = rid, 1
        while k in seen:
            j += 1
            k = "%s~%d" % (rid, j)
        seen.add(k)
        ch = r.get("change")
        items.append({"id": k, "type": "report", "d": d, "t": (r.get("date") or "")[11:16].replace(":", ""),
                      "title": r.get("title") or "", "src": r.get("broker") or r.get("channel") or "", "hide": False, "n": 1,
                      "tone": 1 if ch == "상향" else -1 if ch == "하향" else 0,
                      "broker": r.get("broker"), "opinion": r.get("opinion"), "tp": r.get("tp"), "tp_prev": r.get("tp_prev"),
                      "change": ch, "price_at": r.get("price_at"), "kind": r.get("kind"), "lines": r.get("lines") or [],
                      "est": r.get("est") or [], "risks": r.get("risks") or [], "concl": r.get("concl") or "",
                      "sections": r.get("sections") or [], "msg_url": r.get("msg_url"), "brk_url": r.get("brk_url"),
                      "url": _report_url(r)})

    # 정기보고서 — 한 줄 요약은 brief 캐시에 지금 판이 있을 때만(None = 아직 없음 · [] = 요약할 변화 없음 — first 면 견줄 앞 보고서가 없다).
    # 본문 탭으로 열 섹션은 「사업의 내용」(없으면 표지 다음 첫 섹션)
    for f in filings or ():
        rc = f.get("rcept") or ""
        if len(rc) < 8:
            continue
        secs = f.get("sections") or []
        secs = [s for s in secs if s.get("norm") == "사업의 내용"] + [s for s in secs if s.get("norm") != "대표이사 등의 확인"] + secs
        g, first = gists.get(rc), False
        if isinstance(g, dict):
            g, first = g.get("gist"), bool(g.get("first"))
        items.append({"id": "f:" + rc, "type": "filing", "d": rc[:8], "t": "",
                      "title": "%s%s (%s)" % (f.get("tag") or "", f.get("label") or "", f.get("stamp") or ""),
                      "src": "DART", "hide": False, "n": 1, "tone": 0, "rcept": rc, "label": f.get("label"),
                      "stamp": f.get("stamp"), "tag": f.get("tag") or "", "url": DART_URL % rc,
                      "file": secs[0].get("file") if secs else None,
                      "gist": [{"sec": x.get("short") or x.get("sec"), "text": x.get("text"), "tags": x.get("tags") or []}
                               for x in g if x.get("text")] if g is not None else None,
                      "first": first})

    # 공통 덧붙임 — 회사 낱말 · 반응
    used = set()
    for it in items:
        it["terms"] = match_terms(it["title"], links)
        used.update(it["terms"])
        # 시각 모르는 공시 · 정기보고서(KIS 에서 빌린 시각 없음 — 대부분 장 마감 뒤에 나온다)는 공시일 · 다음 거래일 이틀로
        it["re"] = react(it["d"], it["t"], it["type"] in ("disc", "filing") and not it["t"])
    rank = {"filing": 0, "disc": 1, "alert": 2, "report": 3, "news": 4}
    items.sort(key=lambda it: (it["d"], it["t"], rank.get(it["type"], 9), it["id"]), reverse=True)

    t0 = dt.date(int(today[:4]), int(today[4:6]), int(today[6:]))
    hot = hot_words(items, (t0 - dt.timedelta(days=HOT_DAYS)).strftime("%Y%m%d"), name, links, code=code)
    for h in hot:
        if h["vocab"]:
            used.add(h["vocab"]["term"])

    y1 = (t0 - dt.timedelta(days=PX_DAYS)).strftime("%Y%m%d")
    mv = day_moves(series, mkt)
    meta = news_meta or {}
    rep_ds = [it["d"] for it in items if it["type"] == "report"]
    disc_ds = [x["d"] for x in discs or () if x.get("d")]
    px = None
    if series:
        last = series[-1]
        px = {"last": round(last[1], 2), "date": last[0], "chg": mv.get(last[0], {}).get("chg"),
              "series": [[d, round(c, 2)] for d, c in series if d >= y1]}

    slim, cut_disc = 0, 0

    def pack(items):
        # 날짜별 — 최근 1년 거래일 전부 + 소식이 있는 날(보이는 것만 센다). 보이는 뉴스는 덜어 내기 전 전부(news_days)로
        days = {}
        zero = {"news": 0, "report": 0, "disc": 0, "filing": 0, "alert": 0}

        def day(d):
            x = days.get(d)
            if x is None:
                m = mv.get(d) or {}
                x = days[d] = dict({"chg": m.get("chg"), "mkt": m.get("mkt")}, **zero)
            return x
        for d in ds:
            if d >= y1:
                day(d)
        counts = dict(zero, hidden=0)
        shown = 0
        for it in items:
            if it["hide"]:
                counts["hidden"] += 1
            elif it["type"] == "news":
                shown += 1
                day(it["d"])
            else:
                day(it["d"])[it["type"]] += 1
                counts[it["type"]] += 1
        for d, n in news_days.items():
            if d >= y1 or d in days:
                day(d)["news"] = n
        counts["news"] = len(vis)
        days = dict(sorted(days.items()))
        if news is None:
            src_news = {"ok": False, "at": None, "complete": False, "capped": False, "oldest": None, "n": 0, "note": "뉴스 없음"}
        else:
            olds = [r.get("d") for r in news if r.get("d")]
            src_news = {"ok": True, "at": (meta.get("at") or "")[:16] or None, "complete": bool(meta.get("complete")),
                        "capped": bool(meta.get("capped")),
                        "oldest": (meta.get("oldest") or "")[:8] or (min(olds) if olds else None),
                        "n": len(news), "note": "", "shown": shown, "cut": cut_news, "cut_hidden": cut_hidden}
        return {"v": FEED_V, "code": code, "name": name, "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "px": px,
                "src": {"news": src_news,
                        "reports": {"n": len(rep_ds), "from": min(rep_ds) if rep_ds else None, "slim": slim},
                        "disc": {"n": len(discs or ()), "from": min(disc_ds) if disc_ds else None,
                                 "index": "ready" if discs is not None else "missing", "cut": cut_disc},
                        "filings": {"n": counts["filing"]}},
                "counts": counts, "hot": hot, "days": days,
                "vocab": {lk["term"]: lk for lk in links if lk["term"] in used},
                "items": items}

    out = pack(items)
    if not max_bytes:
        return out
    # 크기 — 기사가 하루 150건 넘는 종목(005930) · 리포트 · 공시가 많은 종목은 응답이 커진다. 오래된 것부터, 이 순서로 덜어 낸다:
    # 숨김 뉴스 → 90일 넘은 리포트는 머리만(slim) → 3년 넘은 공시(분류 없는 것 먼저) → 30일 넘은 보이는 뉴스 → 그래도 넘으면 보이는 뉴스
    ago = lambda n: (t0 - dt.timedelta(days=n)).strftime("%Y%m%d")
    r_full, d_keep, n_keep = ago(REPORT_FULL_DAYS), ago(365 * DISC_KEEP_YEARS), ago(NEWS_KEEP_DAYS)
    drop = set()

    def take(ok, over, shrink=None):
        """오래된 것부터 ok(it) 인 항목을 뺀다(shrink 면 빼지 않고 줄인다). → (남은 over, 건수)."""
        k = 0
        for i in range(len(items) - 1, -1, -1):
            if over <= 0:
                break
            it = items[i]
            if i in drop or not ok(it):
                continue
            if shrink:
                b = jsize(it)
                shrink(it)
                over -= b - jsize(it)
            else:
                drop.add(i)
                over -= jsize(it) + 1
            k += 1
        return over, k

    def slimmed(it):
        for f in ("lines", "est", "risks", "concl", "sections"):
            it.pop(f, None)
        it["slim"] = True                           # 화면은 상세 대신 원문 · 텔레그램 링크

    for _ in range(3):                              # 덜어 낸 건수 숫자 · 날짜 칸 몫으로 조금 모자라면 한 번 더
        size = jsize(out)
        if size <= max_bytes:
            break
        over = size - max_bytes + 64
        over, k = take(lambda it: it["type"] == "news" and it["hide"], over)
        cut_hidden += k
        over, k = take(lambda it: it["type"] == "report" and it["d"] < r_full and not it.get("slim"), over, slimmed)
        slim += k
        over, k = take(lambda it: it["type"] == "disc" and it["d"] < d_keep and not it["cls"]["g"], over)
        cut_disc += k
        over, k = take(lambda it: it["type"] == "disc" and it["d"] < d_keep, over)
        cut_disc += k
        over, k = take(lambda it: it["type"] == "news" and not it["hide"] and it["d"] < n_keep, over)
        cut_news += k
        over, k = take(lambda it: it["type"] == "news" and not it["hide"], over)
        cut_news += k
        out = pack([it for i, it in enumerate(items) if i not in drop])
    return out


def jsize(x):
    """응답 바이트 수(서버가 보내는 꼴 — 한글 그대로 · 빈칸 없는 구분자)."""
    return len(json.dumps(x, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
