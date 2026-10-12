# -*- coding: utf-8 -*-
"""밸류체인 한 장 — 주도주 머리 띠 · 그물망 · 후속주 매트릭스 (2026-10-12).
설계: docs/superpowers/specs/2026-10-12-valuechain-map-design.md. 표준 라이브러리 · 순수 함수만 — 캐시를 모아 넘기고 결과를 저장하는 일은
서버(서버.py vcmap_view · _vcmap_build)가 한다. 이 모듈은 파일 · 네트워크 · 키를 건드리지 않는다.
점수는 규칙 점수 · 검증 전 — 예측이 아니다(README 선행 점수 표본 외 실패, 국면 · 변곡 엣지 0 근처)."""
import re
import html
import bisect
import datetime as dt
from collections import Counter

V = 1
NOTE = "규칙 점수 · 검증 전 — 예측 아님"
MAX_ROWS = 30             # 매트릭스 최대 줄(근거 많은 순)
MAX_TRIG = 4
REP_DF_MAX = 40          # 리포트 동시 언급 낱말이 180일 리포트에서 이만큼(종목 수) 넘게 걸리면 넓은 말 — 리포트 있는 곳 약 710 중.
                         # 2026-10-12 실측: MLCC 5 · FC-BGA 7 · DRAM 16 · 은행 20 · HBM 24 · 광고 26 / 기판 47 · 방산 55 · 플랫폼 83 · 제시 212.
                         # 40 을 넘는 업종 말(방산 · ESS · 임상)은 테마 쪽으로 이미 잡힌다
DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=%s"


# ---------------------------------------------------------------- 1. 이름 → 종목코드
_LATIN_KO = {"a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프", "g": "지", "h": "에이치", "i": "아이",
             "j": "제이", "k": "케이", "l": "엘", "m": "엠", "n": "엔", "o": "오", "p": "피", "q": "큐", "r": "알",
             "s": "에스", "t": "티", "u": "유", "v": "브이", "w": "더블유", "x": "엑스", "y": "와이", "z": "지"}


def norm_ko(nm):
    """== 서버._norm_corp — (주) · 공백 · 구두점을 떼고 영문 글자를 한글 읽기로('삼성SDI' = '삼성에스디아이')."""
    n = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|\s+|[·ㆍ\.,&]", "", nm or "").lower()
    return re.sub(r"[a-z]", lambda m: _LATIN_KO[m.group(0)], n)


_OLD_RX = re.compile(r"\(\s*(?:구|舊|前|옛)\s*[,:：.]?\s*([^)]*)\)")
# 타법인출자 표 이름 꼬리 — 산업_패널.STAKE_TAIL 을 옮김(그 모듈은 import 하지 않는다 — 재무 · API 키를 불러온다)
STAKE_TAIL = re.compile(r"\s*[-–]\s*(?:종속|관계|공동)\s*(?:기업|회사)\s*$|\(\s*(?:연결|국내|해외)[^()]*\)"
                        r"|(?:\s*,?\s*주\s*\d+\s*\)\s*)+$|\(\s*(?:\*|주)\s*[\d,\s]*\)")


def clean(nm):
    """표 속 회사 이름 손질(산업_패널.clean) — 각주 '(*1)' '(주1)' '*2' · '(구, …)' · '과 그 종속기업' · '(상장)' '보통주' 꼬리를 뗀다."""
    n = html.unescape(nm or "")
    n = _OLD_RX.sub("", n)
    n = re.sub(r"\(\s*\*+\s*[\d,\s]*\)|\(\s*주\s*\d+(?:\s*[,~\-]\s*\d+)*\s*\)|\*+\s*\d*(?:\s*,\s*\d+)*|\(\s*\d{1,2}\s*\)"
               r"|\(\s*[a-z]\s*\)|\s주\s*\d+\)", "", n)
    n = re.sub(r"\s*(?:와|과|및)\s*(?:그\s*)?종속\s*(?:기업|회사)(?:들)?\s*$|\s*외\s*\d+\s*개사\s*$", "", n)
    n = re.sub(r"\(\s*(?:보통주|비?상장|(?:유가증권|코스닥|코넥스)\s*(?:시장)?\s*상장|KOSPI|KOSDAQ)\s*\)", "", n)
    n = re.sub(r"\s*보통주\s*$", "", n)
    return n.strip(" -:")


def stake_name(nm):
    """타법인출자 표 이름 → 머리글 조각('수량' · '금액')과 꼬리('-종속기업' · '(연결)' · '주1),주2)')를 뗀다(산업_패널.stake_name)."""
    parts = [p.strip() for p in (nm or "").split("\n") if p.strip() and p.strip() not in ("수량", "금액")]
    return "\n".join(STAKE_TAIL.sub("", p).strip() for p in parts if STAKE_TAIL.sub("", p).strip())


def short_name(nm):
    """화면 이름 — '삼성전자(주)' → '삼성전자', '뷰티라이프원(유)' → '뷰티라이프원'."""
    return re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)", "", clean(nm)).strip()


_EN_TAIL = re.compile(r"^(?:co|ltd|inc|corp|corporation|company|limited|plc|llc|gmbh|pte|sa|bv|ag|kk|the)$")


def en_words(nm):
    """영문 이름 → 낱말(소문자). 'DaejooElectronicMaterialsCo.,Ltd.' 처럼 붙여 쓴 것은 대소문자 경계로 쪼갠다. 법인 꼬리(co · ltd …)는 뗀다."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", html.unescape(nm or ""))
    return [w for w in re.split(r"[^A-Za-z0-9]+", s.lower()) if w and not _EN_TAIL.match(w)]


class Linker:
    """회사 이름 → 종목코드. 수집한 회사 이름이 먼저, 그다음 DART 상장사 목록 — 같은 이름이 둘이면 modify_date 최신 쪽
    (옛 상폐 corp 이 종목코드를 단 채 남아 있다: 삼성물산 000830 · SK 003600). '&' 는 '앤'으로도 맞춘다(삼성이앤에이 = 삼성E&A).
    영문만 적힌 이름은 corp_eng_name 으로 — 통째로 같거나 머리 낱말 + 머리글자(COSMO AMT)가 같으면, 한 낱말(COSMO · DAEJOO)은
    수집한 회사 중 그 낱말로 시작하는 곳이 하나일 때(여럿이면 prefer 로 하나가 될 때)만. 4글자 미만 영문(MEC · KEC)은 잇지 않는다."""

    def __init__(self, corps=(), collected=None):
        self.collected = dict(collected or {})          # {code: 이름}
        self.name_of = dict(self.collected)
        self.ko, self.en, self.acr, self.first = {}, {}, {}, {}
        for code, nm in self.collected.items():
            for k in self._ko_keys(nm):
                self.ko[k] = code
        for code, nm, en, mod in sorted(corps, key=lambda r: r[3] or "", reverse=True):     # 최신 먼저 → setdefault
            self.name_of.setdefault(code, nm)
            for k in self._ko_keys(nm):
                self.ko.setdefault(k, code)
            ws = en_words(en)
            if not ws:
                continue
            full = "".join(ws)
            self.en.setdefault(full, []).append(code)
            if len(ws) > 1:
                self.acr.setdefault(ws[0] + "".join(w[0] for w in ws[1:]), []).append(code)
            if len(ws[0]) >= 4:
                self.first.setdefault(ws[0], []).append(code)

    @staticmethod
    def _ko_keys(nm):
        a, b = norm_ko(nm), norm_ko((nm or "").replace("&", "앤"))
        return [k for k in dict.fromkeys((a, b)) if len(k) >= 2]

    def _pick(self, codes, prefer=()):
        if not codes:
            return None
        pref = [c for c in codes if c in prefer]
        if len(pref) == 1:
            return pref[0]
        col = [c for c in codes if c in self.collected]
        return (col or codes)[0]

    def code(self, nm, prefer=()):
        raw = clean(stake_name(nm).split("\n")[-1] if "\n" in (nm or "") else nm)
        if not raw:
            return None
        if re.search(r"[가-힣]", raw):
            for k in self._ko_keys(raw):
                if k in self.ko:
                    return self.ko[k]
                k2 = re.sub(r"(?:보험|증권)$", "", k)          # '삼성생명보험' → '삼성생명'
                if k2 != k and k2 in self.ko:
                    return self.ko[k2]
            return None
        ws = en_words(raw)
        full = "".join(ws)
        if len(full) < 4:
            return None
        k = norm_ko(raw)
        if len(re.sub(r"[^0-9A-Za-z]", "", raw)) >= 4 and k in self.ko:      # 상장 이름 자체가 영문(NAVER · iMBC) — 4자 이상만
            return self.ko[k]
        tables = (self.en, self.acr) if len(ws) > 1 else (self.en,)         # 머리글자는 여러 낱말일 때만('Micron' ≠ Micro-NX 의 micro+n)
        for table in tables:
            hit = [c for c in table.get(full, []) if c in self.collected]
            if hit:
                return self._pick(hit, prefer)
        if len(ws) == 1:
            cands = [c for c in self.first.get(full, []) if c in self.collected]
            if len(cands) == 1:
                return cands[0]
            pref = [c for c in cands if c in prefer]
            if len(pref) == 1:
                return pref[0]
        for table in tables:
            if table.get(full):
                return self._pick(table[full], prefer)
        return None

    def listed_code(self, nm):
        """상장사라고 이미 아는 이름(계열회사 현황 '상장' 블록)만 — 통째로 못 맞추면 그 이름이 상장 이름으로 시작하는지(4자↑, 가장 긴 것).
        '에이플러스에셋어드바이저' → 에이플러스에셋(244920). 아무 이름에나 쓰면 '삼성전자서비스' 가 삼성전자로 간다."""
        cd = self.code(nm)
        if cd:
            return cd
        k = norm_ko(short_name(nm))
        if k in self.ko:                       # 짧은 영문 상장 이름(SKC · ISC)도 — 상장이라고 아니 4자 문턱이 필요 없다
            return self.ko[k]
        if not re.search(r"[가-힣]", nm or ""):
            full = "".join(en_words(short_name(nm)))         # 영문만 — corp_eng_name 통째('DB Inc.' → DB 012030), 상장이라고 아니 4자 문턱 없이
            return self._pick(self.en[full]) if full and full in self.en else None
        # 머리 = 한글이 든 상장 이름, 정규화 5자↑('SK' = '에스케이' 4자는 'SK위탁관리부동산투자회사'를 SK 로 끌어온다)
        best = max((x for x in self.ko if len(x) >= 5 and k.startswith(x) and x != k and re.search(r"[가-힣]", self.name_of.get(self.ko[x]) or "")),
                   key=len, default=None)
        return self.ko[best] if best else None


# ---------------------------------------------------------------- 2. 소유 구조 — 수집 보고서 텍스트(시제품 own_probe.py, 959/967 통과)
PCT_RX = re.compile(r"^\d{1,3}(?:\.\d+)?$")
# 주식 종류 칸 — '보통주(식)' · '의결권 있는 주식' 말고도 '의결권 있는 주식(보통주)' 37 · '보통주 (의결권있는주식)' 26 · '의결권이 있는 주식' 20 ·
# '기명식 보통주' 6 · '보통주(의결권 있음)' 2(2026-10-12 전 종목 최신 표). 우선 · 없는 · 없음이 든 칸은 보통주가 아니다(_common)
KIND_RX = re.compile(r"^(?:기명식\s*)?(?:(?:의결권\s*이?\s*(?:있는|없는)\s*)?(?:보통주|우선주|종류주)(?:식)?|의결권\s*이?\s*(?:있는|없는)\s*주식)"
                     r"(?:\s*\(\s*[^()]{1,20}\))?$")
CORP_RX = re.compile(r"㈜|\(주\)|주식회사|\(유\)|유한회사|홀딩스|지주|Holdings|Inc|Ltd|LLC|Corp|재단|조합|공사|공단|기금|펀드|Fund|투자|은행|증권|보험|생명|"
                     r"화재|캐피탈|자산운용|파트너스|PEF|사모|정부|기획재정부|국민연금|산업은행|[A-Za-z]{3,}", re.I)
# 법인 이름 꼬리 — 2–4자 한글이라도 사람이 아니다('대명화학' · 폰드그룹 최대주주)
CO_TAIL = re.compile(r"(?:화학|산업|물산|건설|전자|전기|제약|약품|상사|실업|공업|제지|식품|해운|개발|기업|흥업|기계|정밀|통상|유통|무역|섬유|철강|"
                     r"금속|화성|문화|미디어|바이오|케미칼|케미컬|테크|정공|그룹|글로벌|코리아)$")
FOOT_RX = re.compile(r"\(?\s*(?:\*+|주)\s*\d*(?:\s*[,~\-]\s*\d+)*\s*\)|\*+\s*\d*(?:\s*,\s*\d+)*")      # 각주 칸 '(주1)' '주1)' '(*1)' '*2'
# 최대주주 행 관계 칸(공백 뗀 꼴) — '최대주주' · '최대주주본인' · '본인(최대주주)' · '최대주주(법인)'. '최대주주의…' · '최대주주친인척'은 아니다
TOP_REL = re.compile(r"최대주주(?:본인|本人)?(?:\([^()의]*\))?|최대주주(?:등|법인)|(?:본인|本人)\(?최대주주\)?")
SELF_REL = re.compile(r"(?:본인|本人)(?:\([^()]*\))?")


def _common(kind):
    return not re.search(r"우선|없는|없음", kind or "")


def _person(disp):
    """사람 이름 꼴이면 붙인 이름('이 재 용' → '이재용', '김종훈(등기)' → '김종훈'), 아니면 None."""
    n = re.sub(r"\s+", "", re.sub(r"\(\s*(?:미?등기(?:임원)?|대표이사|회장|사내이사|이사)\s*\)\s*$", "", disp or ""))
    return n if re.fullmatch(r"[가-힣]{2,4}", n) and not (len(n) >= 3 and CO_TAIL.search(n)) else None


def _lines(t):
    return [x.strip() for x in (t or "").split("\n") if x.strip()]


def _f(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def owner_of(texts, link=None):
    """「주주에 관한 사항」 첫 표(최대주주 및 특수관계인) → 최대주주 {name, code, pct, pct_sum, rel, kind, total}.
    표 머리 '성 명 / 관 계 / 주식의종류'를 닻으로(제목이 두 번 나오는 회사). 주식종류 칸 i 기준 관계 = 그 앞 칸, 이름 = 그 앞 칸(각주 칸
    '(주1)'은 건너뜀 — 성우하이텍), 기말 지분율 = i+4, 비고 = i+5.
    최대주주 = 보통주 행 중 기말 0%(기간 중 판 애경산업 · 국민연금공단) · 발행회사 자기주식 행(트리니티항공)을 빼고, 관계가 '최대주주'(본인)인 첫 행
    ('최대주주의최대주주' 방준혁 · 관계 '부' 임무현보다 넷마블 · 임중규), 없으면 '본인' 첫 행, 그것도 없으면 기말 지분율 가장 큰 행.
    같은 이름의 '(특별계정)' 행은 pct_sum 에 더한다. kind = listed(코드 풀림) · corp(법인 표지) · person('이 재 용' → 이재용)."""
    t = (texts or {}).get("sh") or ""
    m = re.search(r"성\s*명\s*\n+\s*관\s*계\s*\n+\s*주식의\s*종류", t)
    if not m:
        return None
    ls = _lines(t[m.end(): m.end() + 30000])
    stop = next((i for i, x in enumerate(ls) if re.match(r"^※|^\d\.\s|^[나다]\.\s", x)), len(ls))
    ls = ls[:stop]
    rows, total, ended = [], None, False
    for i, x in enumerate(ls):
        if i < 1 or not KIND_RX.match(x) or i + 4 >= len(ls) or not PCT_RX.match(ls[i + 4] or ""):
            continue
        if ls[i - 1] in ("계", "합계", "합 계"):
            ended = True                  # 계 행 뒤는 다른 표(최대주주의 최대주주 표 — CJ제일제당 '이재현 최대주주 본인 42.07')
            if _common(x) and total is None:
                total = float(ls[i + 4])
            continue
        if ended:
            continue
        j = i - 1
        while j > 0 and FOOT_RX.fullmatch(ls[j]):
            j -= 1
        rel, j = ls[j], j - 1
        while j > 0 and FOOT_RX.fullmatch(ls[j]):
            j -= 1
        if j < 0 or PCT_RX.match(ls[j]) or rel == "-":
            continue                      # 계 행의 우선주 줄 등
        rows.append({"name": ls[j], "rel": rel, "kind": x, "pct": float(ls[i + 4]), "note": ls[i + 5] if i + 5 < len(ls) else ""})
    common = [r for r in rows if _common(r["kind"])]
    # 비고의 '자기주식 소각에 따른 지분율 변동'(SK디스커버리 · 대한조선)은 빼는 까닭이 아니다 — 관계 '발행회사' · 이름 · 관계에 든 자기주식만
    live = [r for r in common if r["pct"] > 0 and not re.fullmatch(r"\s*발행\s*회사\s*", r["rel"]) and not re.search(r"자기\s*주식", r["rel"] + " " + r["name"])]
    # 관계 '최대주주' · '본인' 행 중 기말 지분율 큰 것 — 회사마다 둘을 거꾸로 적는다(셀트리온 '본인' 셀트리온홀딩스 25.85 · '최대주주' 서정진 4.20,
    # 성우하이텍 '최대주주' 성우홀딩스 32.74 · '본인' 이명근 5.80). 둘 다 없으면 기말 지분율 가장 큰 행
    top_rows = [r for r in live if TOP_REL.fullmatch(re.sub(r"\s+", "", r["rel"])) or SELF_REL.fullmatch(re.sub(r"\s+", "", r["rel"]))]
    if live:
        top = max(top_rows or live, key=lambda r: r["pct"])
    else:
        top = None if common else (rows[0] if rows else None)      # 보통주 행이 다 0% · 자기주식이면 앞 보고서로(서버가 셋까지 본다)
    if not top:
        return None
    base = re.sub(r"\(\s*특별계정\s*\)", "", top["name"]).strip()
    psum = round(sum(r["pct"] for r in common if re.sub(r"\(\s*특별계정\s*\)", "", r["name"]).strip() == base), 2)
    disp = short_name(base)
    code = link(base) if link else None
    person = None if code or CORP_RX.search(base) else _person(disp)
    kind = "listed" if code else ("person" if person else "corp")
    return {"name": person or disp, "code": code, "pct": top["pct"], "pct_sum": psum, "rel": top["rel"], "kind": kind, "total": total}


def listed_subs(texts):
    """「회사의 개요 › 연결대상 종속회사 현황(요약)」 '상장' 행 기말 수 → {n, note}. '-' 는 0. 표가 없으면 n None.
    주의: 이 수는 해외 상장 종속도 센다(LG전자 인도법인) — '상장 종속 없음'과 '상장 지분 있음'은 따로 보인다."""
    t = (texts or {}).get("ov") or ""
    m = re.search(r"연결\s*대상\s*종속\s*회사\s*(?:현황\s*\(\s*요\s*약\s*\)|개황)", t)
    if not m:
        return {"n": None, "note": None}
    seg = t[m.end(): m.end() + 4000]
    ls = _lines(seg)
    n = None
    for i, x in enumerate(ls):
        if x == "상장" and i + 4 < len(ls):
            v = ls[i + 4]              # 기초 · 증가 · 감소 · 기말
            n = 0 if v in ("-", "0") else (int(v.replace(",", "")) if re.fullmatch(r"[\d,]+", v) else None)
            break
    note = re.search(r"[^\n※]*국내\s*상장[^\n※]*", seg)
    return {"n": n, "note": note.group(0).strip() if note else None}


PREF_RX = re.compile(r"우선주|\(\s*우\s*\d*\s*\)|우\d*$|\d우|RCPS|상환\s*전환\s*우선|전환\s*우선")
STOCK_CODE_RX = re.compile(r"\(?\s*종목\s*코드\s*[:：]?\s*([0-9][0-9A-Z]{5})\s*\)?")


def holdings_of(texts, link=None):
    """「상세표 › 3. 타법인출자 현황(상세)」 '상장' 행(이름 다음 16칸) → [{name, code, pct, purpose, book}] 기말 지분율 큰 순.
    상장 칸 i 기준 f = ls[i+1:i+15] — f[1] 출자목적 · f[10] 기말 지분율 · f[11] 기말 장부가액(단위는 회사마다). 우선주 · 기말 0 행은 뺀다."""
    t = (texts or {}).get("dt") or ""
    m = re.search(r"타\s*법\s*인\s*출\s*자\s*현\s*황\s*\(\s*상\s*세\s*\)", t)
    if not m:
        return []
    sec = t[m.end():]
    st = re.search(r"\n[ \t]*\d\s*\.\s*(?:국내\s*및|[가-힣 ]{2,20}현황\s*\(\s*상\s*세)", sec)
    sec = sec[:st.start()] if st else sec
    ls = _lines(sec)
    out, seen = [], set()
    for i, x in enumerate(ls):
        if x != "상장" or i == 0 or i + 14 > len(ls) or ls[i + 1].startswith("여부"):
            continue
        f = ls[i + 1: i + 15]
        j = i - 1
        while j > 0 and re.fullmatch(r"\(\s*\*+\s*[\d,\s]*\)|\(\s*주\s*\d+\s*\)", ls[j]):
            j -= 1                     # 각주 칸 '(*3)' 건너뛰기
        raw = stake_name(ls[j])
        nm = short_name(raw)
        pct = _f(f[10])
        if not nm or pct is None or pct < 0.1 or PREF_RX.search(nm + " " + raw):
            continue                   # 우선주 · RCPS 행은 보통주 상장사에 잇지 않는다('솔루스첨단소재㈜(우1)' · '로킷헬스케어16 RCPS')
        code = link(raw) if link else None
        key = code or norm_ko(nm)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": nm, "code": code, "pct": pct, "purpose": f[1] if f[1] not in ("-", "") else None, "book": f[11]})
    return sorted(out, key=lambda h: -h["pct"])


def affiliates_listed(texts, link=None):
    """「상세표 › 2. 계열회사 현황(상세)」 '상장' 블록 → {n, names:[[이름, 코드]]}. 대기업집단이 아니면('-') n None.
    '씨제이씨지브이 (종목코드 079160)'처럼 코드가 적혀 있으면 그 코드(CJ 계열 · 제주은행)."""
    t = (texts or {}).get("dt") or ""
    m = re.search(r"계열회사\s*현황\s*\(\s*상\s*세\s*\)", t)
    if not m:
        return {"n": None, "names": []}
    ls = _lines(t[m.end(): m.end() + 30000])
    try:
        i = ls.index("상장")
    except ValueError:
        return {"n": None, "names": []}
    n = int(ls[i + 1].replace(",", "")) if i + 1 < len(ls) and re.fullmatch(r"[\d,]+", ls[i + 1]) else None
    names = []
    j = i + 2
    while n and j < len(ls) and ls[j] != "비상장" and len(names) < 120:
        if not re.fullmatch(r"[\d\-]{10,16}", ls[j]) and ls[j] != "-":
            sc = STOCK_CODE_RX.search(ls[j])
            raw = STOCK_CODE_RX.sub("", ls[j]).strip() if sc else ls[j]
            nm = short_name(raw)
            if nm and not re.search(r"해당\s*사항", nm):
                names.append([nm, sc.group(1) if sc else (link(raw) if link else None)])
        j += 1
    return {"n": n, "names": names}


def parse_own(texts, link=None):
    """보고서 텍스트 셋 {sh: 주주에 관한 사항, ov: 회사의 개요, dt: 상세표} → 소유 구조 한 덩어리."""
    ls = listed_subs(texts)
    return {"owner": owner_of(texts, link), "holdings": holdings_of(texts, link), "listed_subs": ls["n"], "subs_note": ls["note"],
            "group": affiliates_listed(texts, link)}


# ---------------------------------------------------------------- 3. 낱말 — 스토리 · 제품 · 키워드 맞추기
_KW_STRIP = re.compile(r"[^0-9A-Za-z가-힣]")
# 같은 것을 다르게 적는 제품 말 — 정규화한 뒤(소문자 · 기호 없음) 바꾼다. fpcb 를 pcb 보다 먼저(연성기판은 패키지 기판의 동종이 아니다)
SYN = (("적층세라믹콘덴서", "mlcc"), ("적층세라믹커패시터", "mlcc"), ("적층세라믹캐패시터", "mlcc"), ("cameramodule", "카메라모듈"),
       ("packagesubstrate", "패키지기판"), ("fpcb", "연성회로"), ("pcb", "기판"), ("substrate", "기판"), ("캐패시터", "커패시터"))
# 테마 · 리포트 · 제품 맞추기에서 빼는 넓은 말 — 'AI' 로 테마를 고르면 삼성전자 · SK하이닉스가 맨 위에 온다
GENERIC_KW = set("""ai 서버 반도체 메모리 스마트폰 전장 pc it 자동차 모바일 데이터센터 전력 에너지 바이오 소재 부품 장비 모듈 제품 상품 시스템
솔루션 서비스 기타 전자 전자부품 부품소재 산업 국내 해외 수출 내수 캐파 capa 통신 정보통신 유통 모터 센서 플랫폼""".split())
# 통신 · 모터 · 센서(LG이노텍 전장부품 줄 → 삼지전자 · SNT모티브) · 유통 · 플랫폼은 업종을 가로지르는 넓은 말이라 같은 제품 · 테마 맞추기에 안 쓴다
# 스토리 낱말에서 빼는 말(리포트 hot 낱말 중 업황 · 실적 일반어) — 내러티브.STOP 위에 덧붙인다
STORY_STOP = set(w.lower() for w in """가격 수요 공급 인상 인하 판가 단가 물량 증설 투자 업황 개선 둔화 호조 부진 컨센서스 상회 하회 추정 추정치 예상
하반기 상반기 수익성 마진 비중 점유율 고객 고객사 제품 사업 부문 실적 영업 이익 이익률 밸류에이션 목표 산업 수출 가동률 재고 출하 사이클
업사이클 모멘텀 프리미엄 리레이팅 연간 분기 컨콜 잠정 발표 하향 상향 성장 전망 강세 증가 감소 회복 축소 지속 본격 반영 달성 주주환원 배당
자사주 밸류업 적자 흑자 매출 영업이익 순이익 비용 환율 원가 판매 공장 생산 라인 신규 커버리지 개시 실적발표 시장점유율 주가 가이던스 수주
계약 공급계약 TP PER PBR EPS OPM ROE YoY QoQ Top Pick Pre Review Preview Comment Update Earnings Conference Call IR BUY Hold Target
Q1 Q2 Q3 Q4 1Q 2Q 3Q 4Q 1H 2H 핵심 요약 결론 포인트 투자포인트 리스크 체크 이슈 동향 현황 점검 기업 업종 대형 중소형 연결 별도
기준 대비 이상 이하 수준 정도 예정 계획 확인 가능 필요 효과 기여 부담 우려 기대 주목 캐파 CAPA 믹스 램프업 선수금 수급 공급부족
쇼티지 타이트 업체 경쟁사 선두 글로벌 중국 미국 일본 대만 고객향
신한생각 Overweight Underweight Neutral Risk Valuation 현재가 것으로 추가 확보 기반 강화 중장기 저평가 https http www
금주 전주 금일 전일 당일 익일 주간 이번 지난 올해 내년 작년 매년 매월 매분기 컴플라이언스 텔레그램""".split())
# 증권사 텔레그램 꼬리말('위 문자는 컴플라이언스의 승인을 득하였음') — KB금융 칩 '문자' · '득하였음'
BOILER_RX = re.compile(r"위\s*(?:문자|내용|자료)[는은][^.\n]{0,40}?(?:득하였음|득했습니다|받았습니다|승인[^\s.]*)|텔레그램\s*채널\S*")
JOSA = "이가은는을를의에도와과로"
VERB_TAIL = re.compile(r"(?:하였음|하였다|했음|했다|하였으며|되었음|되었다|됐다|합니다|입니다|습니다|있음|없음|예정임)$")    # '득하였음'(취득하였음 조각)
# 증권사 연재 이름(신한생각) · 의견 등급 · 상투어(추가 · 확보 · 강화 · 저평가)는 칩으로도 맞추기 말로도 쓰지 않는다(2026-10-12 KB금융 · 넥센타이어 판)
URL_RX = re.compile(r"h?ttps?://\S+|\b[\w.-]+\.(?:kr|com|net|me|ly|io|co)(?:/\S*)?\b", re.I)
# 조사 · 이음말 조각(hot 낱말의 꼬리 떼기가 남긴 '으로') — 스토리 낱말에도, 맞추기 말에도 쓰지 않는다
JUNK_WORDS = set("""으로 에서 하는 있는 되는 위한 통한 대한 따른 관련 함께 이후 이전 부터 까지 또는 그리고 하여 통해 위해 에도 에는 으며 이며 하며
에게 보다 처럼 만큼 정도 이상 이하 대비 기준 경우 때문 동안 가운데 속에서 중심""".split())
STORY_STOP |= JUNK_WORDS
GENERIC_KW |= JUNK_WORDS
PROD_HEADS = ("기판", "필름", "렌즈", "센서", "배터리", "케이블", "커넥터", "웨이퍼", "패널")
GEN_ITEM = re.compile(r"^(?:기타.*|합\s*계|소\s*계|총\s*계|계|내부\s*거래.*|연결\s*조정.*|매출\s*총계|내수|수출|평균|제품|상품|제품\s*상품|"
                      r"상품\s*제품|용역|임대\s*등?|-|\"|“|”|〃|품목)$")
# 매출 구분 · 조정 말(낱말 끝) — '상품매출' · '개발매출' · '임대료' · '배당금수익' · '부문간 내부거래 제거'는 제품이 아니다(광주신세계 · 펩트론이 엠씨넥스 '같은 제품'으로 왔다)
REV_TAIL = re.compile(r"(?:매출|수익|수수료|임대료?|용역|렌탈|임가공|내부\s*거래|제거|조정|배당금?|부산물|반제품|스크랩)$")    # 부산물(현대제철 → 화신 · 가온전선)
PROD_MIN_PCT = 5.0       # 제품 낱말은 이 비중 이상 줄에서만 — prod_hits(남의 줄) 문턱과 같게(DB하이텍 '건축/환경플랜드' 0.6% → 건설사)
EQUIP_RX = re.compile(r"장비|검사|설비|머신|machine|equipment|system|시스템", re.I)
HY_RX = re.compile(r"(?<![0-9A-Za-z])([A-Za-z][A-Za-z0-9]{0,9}(?:-[A-Za-z0-9]{1,10})+)(?![0-9A-Za-z])")


def kw_norm(s, syn=True):
    """맞추기용 — 기호 · 공백을 지운 소문자(FC-BGA = FCBGA = FC BGA), 같은 제품 말은 하나로(SYN)."""
    n = _KW_STRIP.sub("", s or "").lower()
    if syn:
        for a, b in SYN:
            if a in n:
                n = n.replace(a, b)
    return n


def specific(w):
    """테마 · 리포트 · 제품 맞추기에 쓸 만큼 좁은 말인가 — 영문은 3자 이상, 한글은 2자 이상, 넓은 말(GENERIC_KW) 아님."""
    k = kw_norm(w)
    if not k or k in GENERIC_KW or k.isdigit():
        return False
    return len(k) >= 3 if re.fullmatch(r"[0-9a-z]+", k) else len(k) >= 2


def join_hyphen(text, seen=None):
    """'FC-BGA' 같은 하이픈 영문 낱말을 붙인다(내러티브.WORD_RX 가 FC · BGA 로 쪼개지 않게). seen 에 원래 꼴을 센다."""
    def f(m):
        s = m.group(1)
        j = s.replace("-", "")
        if seen is not None:
            seen.setdefault(j.lower(), Counter())[s] += 1
        return j
    return HY_RX.sub(f, text or "")


def _hay(r):
    return " ".join([r.get("title") or ""] + list(r.get("lines") or []) + [r.get("concl") or ""])


def story_words(rows, since, name, hot, code="", top=4):
    """최근(since 'YYYY-MM-DD' 이후) 리포트 제목 + 줄의 hot 낱말(내러티브.hot_words) → [{"w","n"}] 상위 top. 하이픈 낱말은 한 낱말로,
    업황 · 실적 일반어(STORY_STOP)는 뺀다. hot 은 hot_words(items, since8, name, links, top=, code=) 꼴의 함수."""
    seen, items = {}, []
    for r in rows or ():
        d = (r.get("date") or "")[:10]
        if d < since:
            continue
        text = BOILER_RX.sub(" ", URL_RX.sub(" ", " ".join([r.get("title") or ""] + list(r.get("lines") or []))))   # 'buly.kr/…' · 꼬리말이 낱말로 오지 않게
        items.append({"type": "report", "d": d.replace("-", ""), "title": join_hyphen(text, seen)})
    if not items or hot is None:
        return []
    out = []
    for h in hot(items, since.replace("-", ""), name, (), top=80, code=code):
        w = h["w"]
        lw = w.lower()
        if lw in STORY_STOP or re.fullmatch(r"[\d.,]+[가-힣A-Za-z]{0,2}", w) or VERB_TAIL.search(w) or (w[-1:] in JOSA and lw[:-1] in STORY_STOP):
            continue                  # 조사 붙은 일반어('가동률이')도
        out.append({"w": seen[lw].most_common(1)[0][0] if lw in seen else w, "n": h["n"]})
        if len(out) >= top:
            break
    return out


def lead_line(rows):
    """최신 리포트 제목 한 줄 {text, by, date, url} — 가장 새 글, 같은 날 증권사가 적힌 글이 있으면 그쪽(카드 글은 증권사가 비기도 한다)."""
    rs = [r for r in rows or () if r.get("title")]
    if not rs:
        return None
    d0 = (rs[0].get("date") or "")[:10]
    r = next((x for x in rs if (x.get("date") or "")[:10] == d0 and x.get("broker")), rs[0])
    return {"text": r["title"], "by": r.get("broker"), "date": (r.get("date") or "")[:10],
            "url": r.get("msg_url") or next(iter(r.get("urls") or []), None)}


def product_label(p):
    """제품 줄 → 화면 이름. '수동소자(MLCC, Inductor, Chip Resistor 등)' → '수동소자(MLCC 등)', '제품상품'처럼 뭉뚱그린 품목이면 용도로.
    글자 없는 품목(날짜 조각 "('11.1.1~09.30)" — KB금융)은 빈 이름(products_of 가 뺀다)."""
    item = re.sub(r"\s+", " ", (p.get("item") or "").strip())
    if GEN_ITEM.match(item) and p.get("use") and not GEN_ITEM.match(p["use"].strip()):
        item = p["use"].strip()
    if not re.search(r"[가-힣A-Za-z]", item):
        return ""
    m = re.match(r"^(.*?)\(([^)]*,[^)]*)\)\s*$", item)
    if m:
        first = re.split(r"\s*,\s*", m.group(2))[0].strip()
        item = "%s(%s 등)" % (m.group(1).strip(), re.sub(r"\s*등$", "", first))
    return item[:40]


def products_of(prods, top=None):
    """밸류체인 제품 매출 구성 → [{item, seg, pct, use, c}] 비중 큰 순. 합계 · 기타 · 내부거래 · 단위 줄은 빼고 같은 이름은 합친다.
    비중이 없으면 금액으로 나눈다. c = 부문 색 번호(부문 합 큰 순 0,1,2… — 부문이 없으면 품목마다)."""
    rows = []
    for p in prods or ():
        lab = product_label(p)
        seg = (p.get("segment") or "").strip() or None
        if not lab or GEN_ITEM.match(lab) or re.search(r"합\s*계|소\s*계|총\s*계|매출\s*총계|내부\s*거래|연결\s*조정", lab + " " + (seg or "")):
            continue
        if seg and GEN_ITEM.match(seg):
            seg = None
        rows.append({"item": lab, "seg": seg, "pct": p.get("pct"), "amt": p.get("amt"), "use": p.get("use")})
    if not rows:
        return []
    if any(r["pct"] is None for r in rows) and all(isinstance(r["amt"], (int, float)) and r["amt"] > 0 for r in rows):
        tot = sum(r["amt"] for r in rows)
        for r in rows:
            r["pct"] = r["amt"] / tot * 100
    big = [r for r in rows if (r["pct"] or 0) >= 99.5]
    if big and len(rows) > len(big) and sum(r["pct"] or 0 for r in rows if (r["pct"] or 0) < 99.5) >= 90:
        rows = [r for r in rows if (r["pct"] or 0) < 99.5]        # 합계 행(100%) — 나머지가 100% 가까이 될 때만
    rows = [r for r in rows if r["pct"] is None or r["pct"] >= 0.05] or rows
    merged = {}
    for r in rows:
        k = (r["item"], r["seg"])
        if k in merged:
            m = merged[k]
            m["pct"] = (m["pct"] or 0) + (r["pct"] or 0) if (m["pct"] is not None or r["pct"] is not None) else None
            continue
        merged[k] = dict(r)
    rows = sorted(merged.values(), key=lambda r: -(r["pct"] or 0))
    segs = Counter()
    for r in rows:
        segs[r["seg"] or "·" + r["item"]] += r["pct"] or 0
    cmap = {s: i for i, (s, _) in enumerate(sorted(segs.items(), key=lambda kv: -kv[1]))}
    out = [{"item": r["item"], "seg": r["seg"], "pct": round(r["pct"], 1) if r["pct"] is not None else None,
            "use": r["use"], "c": cmap[r["seg"] or "·" + r["item"]]} for r in rows]
    return out[:top] if top else out


def big_lines(prods, min_pct=PROD_MIN_PCT):
    """제품 줄 중 비중 min_pct 이상(비중이 없으면 금액 몫으로, 둘 다 없으면 다). 합계 · 기타 줄은 몫 셈에서 뺀다."""
    rows = [p for p in prods or () if not GEN_ITEM.match((p.get("item") or "").strip())
            and not re.search(r"합\s*계|소\s*계|총\s*계", (p.get("item") or "") + " " + (p.get("segment") or ""))]
    if any(p.get("pct") is not None for p in rows):            # 한 자리로 반올림해 견준다(products_of 와 같은 꼴 — 생체인식 4.95% = 5.0%)
        return [p for p in prods or () if p.get("pct") is None or round(p["pct"], 1) >= min_pct]
    amt = [p.get("amt") for p in rows if isinstance(p.get("amt"), (int, float)) and p["amt"] > 0]
    tot = sum(amt)
    if not tot:
        return list(prods or ())
    return [p for p in prods or () if not isinstance(p.get("amt"), (int, float)) or p["amt"] / tot * 100 >= min_pct]


def product_words(prods, min_pct=PROD_MIN_PCT):
    """내 제품 낱말 — 품목 이름 · 괄호 안 목록 · 머리 낱말('반도체패키지기판' → '기판'). '카메라모듈'처럼 머리가 넓은 말(모듈)이면 통째로만.
    비중 min_pct 미만 줄(DB하이텍 '그린피, 자산관리 등' 1.7%)과 매출 구분 말(REV_TAIL — 상품매출 · 임대료)은 뺀다."""
    out = []
    for p in big_lines(prods, min_pct):
        item = re.sub(r"\(?\s*주\s*\d+(?:\s*,\s*\d+)*\s*\)|\(\s*\*+\s*\d*\s*\)", "", (p.get("item") or "")).strip()   # 각주 '여객주1)'
        if GEN_ITEM.match(item) and p.get("use"):
            item = p["use"].strip()          # '제품상품' → 용도('전도성 페이스트')
        base = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", item)
        toks = re.split(r"[,/·]", base) + [x for pp in re.findall(r"\(([^)]*)\)", item) for x in re.split(r"[,/·]", pp)]
        for t in toks:
            t = re.sub(r"\s*(?:등|외)\s*$", "", t).strip()
            if not t or GEN_ITEM.match(t) or not specific(t) or REV_TAIL.search(kw_norm(t)):
                continue
            out.append(t)
            k = kw_norm(t)
            for h in PROD_HEADS:
                if k.endswith(h) and len(k) > len(h) + 1 and specific(h):
                    out.append(h)
    return list(dict.fromkeys(out))


def segment_words(prods):
    """제품 부문 이름 중 좁은 말 — 테마 맞추기 말에 더한다('타이어' — 넥센타이어는 제품 줄이 임대 2.3%뿐이라 제품 낱말이 없다).
    큰 줄(big_lines)의 부문만, 큰 줄이 없으면 다."""
    rows = big_lines(prods) or list(prods or ())
    if not any((p.get("pct") or 0) >= PROD_MIN_PCT for p in rows):
        rows = list(prods or ())
    out = []
    for p in rows:
        s = re.sub(r"\s*(?:부문|사업부|사업)\s*$", "", (p.get("segment") or "").strip())
        if s and not GEN_ITEM.match(s) and specific(s) and s not in out:
            out.append(s)
    return out


def uses_of(prods, top=6):
    """제품 용도 칸 → 수요처 낱말('스마트폰용, 전장용, PC용 등' → 스마트폰 · 전장 · PC)."""
    out = []
    for p in prods or ():
        for w in re.split(r"[,/·및]|\s+및\s+", p.get("use") or ""):
            w = re.sub(r"(?:용|向)?\s*(?:등|외)?\s*$", "", w.strip()).strip()
            w = re.sub(r"용$", "", w).strip()
            if not w or len(w) > 10 or re.search(r"\d|㎡|kg|ton|^-$|\"|〃", w) or GEN_ITEM.match(w):
                continue
            if w not in out:
                out.append(w)
    return out[:top]


# ---------------------------------------------------------------- 4. 트리거 — 공시 · 리포트 줄
ORD_RX = re.compile(r"단일판매.?공급계약\s*체결")
_AMT = r"\d[\d,]*(?:\.\d+)?\s*조(?:\s*\d[\d,]*\s*억)?\s*원?|\d[\d,]*(?:\.\d+)?\s*억\s*원?"
_PCT = r"\d{1,3}(?:\.\d+)?\s*%"
_CAPEX = r"증설|CAPEX|CapEx|Capex|capex|설비\s*투자|시설\s*투자|신규\s*투자|신공장|공장|팹|Fab(?!less)|FAB|라인(?!업)|캐파|CAPA"
TRIG_RULES = [   # (범주, 정규식) — 리포트 줄 속 '말 + 숫자'(시제품 ff/p9.py)
    ("price", re.compile(r"(?:판가|가격|ASP|단가)[^.·\n]{0,40}?" + _PCT + r"\s*(?:이상|가량|내외|수준|대)?\s*(?:의\s*)?(?:인상|상승|올|↑)")),
    ("price", re.compile(r"(?:판가|가격|ASP|단가)\s*(?:인상|상승)(?:률|폭|분)?\s*(?:은|는|이|가|:)?[^.·\n(~]{0,8}?(?<![~\d.])" + _PCT)),
    ("price", re.compile(_PCT + r"\s*(?:이상|가량|내외|수준)?\s*(?:의\s*)?(?:판가|가격|ASP|단가)\s*(?:인상|상승)")),
    # 수주 — 말과 금액 사이에 CapEx · 투자 · 증설이 끼면 설비투자 줄이다('…계약 구체화 기대, 베트남 신공장 CapEx 2조원')
    ("order", re.compile(r"(?:LTA|수주|공급\s*계약|장기\s*공급|계약)(?:(?!CapEx|CAPEX|Capex|투자|증설)[^.·\n]){0,40}?(?:" + _AMT + ")")),
    ("order", re.compile(r"(?:" + _AMT + r")[^.·\n]{0,15}?(?:규모의?\s*)?(?:LTA|수주|공급\s*계약)")),
    # 설비투자 — 증설 · CAPEX · 설비 · 공장 · 라인 같은 말이 있어야(맨 '투자'는 현금성자산 · 기관 순매수 줄까지 끌어왔다)
    ("capex", re.compile(r"(?:" + _CAPEX + r")[^.·\n]{0,40}?(?:" + _AMT + ")")),
    ("capex", re.compile(r"(?:" + _AMT + r")[^.·\n]{0,20}?(?:" + _CAPEX + ")")),
    ("util", re.compile(r"(?:가동률|가동율)[^.·\n]{0,30}?" + _PCT)),
]
# 수주 · 설비투자 줄로 안 보는 줄 — 수급(기관 순매수) · 현금 · 주주환원 · 손실계약 · 투자수익
TRIG_SKIP = re.compile(r"순매수|순매도|현금성\s*자산|현금\s*보유|현금\s*흐름|FCF|자사주|배당|주주\s*환원|투자\s*수익|손실\s*(?:부담\s*)?계약|투자\s*주체")
# 외화 금액 설비투자는 남의 이야기(빅테크 CAPEX 1,300~1,450억달러 — SK하이닉스 신규시설투자 공시를 밀어냈다)
FX_AMT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:조|억|만)?\s*(?:달러|불(?![가-힣])|위안|엔(?![가-힣])|유로)")
PL_RX = re.compile(r"(?:영업\s*(?:이익|손실|적자)|매출액?|순이익|순손실|적자|흑자|손실|이익)\s*(?:은|는|이|가|도|약|:)?\s*$")
PL_AFTER = re.compile(r"^\s*(?:의\s*)?(?:매출|영업\s*(?:이익|손실)|순이익|이익|손실)")
AMT_RX = re.compile(_AMT)


def _not_capex(ln, m):
    """설비투자 줄로 걸렸지만 아닌 것 — 외화 금액(남의 설비투자) · 금액 앞뒤가 손익 말('테일러팹 가동 … 영업손실 1.5조원' · '공장 … 약 800억원 매출 추가')."""
    if FX_AMT.search(ln[m.start(): m.end() + 6]):
        return True
    a = AMT_RX.search(ln, m.start(), m.end())
    return bool(a and (PL_RX.search(ln[max(0, a.start() - 10): a.start()]) or PL_AFTER.search(ln[a.end(): a.end() + 8])))
TRIG_CAT ={"contract": "order", "order": "order", "capex": "capex", "price": "price", "util": "util"}
CAPEX_WORD = re.compile(r"증설|capex", re.I)      # 금액 없는 설비투자 공시를 리포트 줄로 갈음하는 것은 이 말이 든 줄만


def won(v):
    """원 → '3.66조' · '4,540억'."""
    if v is None:
        return "-"
    if abs(v) >= 1e12:
        return ("%.2f" % (v / 1e12)).rstrip("0").rstrip(".") + "조"
    return "{:,}억".format(int(round(v / 1e8)))


def clip(line, m, n=60):
    """줄을 맞은 자리 둘레 n자 안팎으로."""
    s = re.sub(r"\s+", " ", line or "").strip()
    if len(s) <= n + 16:
        return s
    a = max(0, min(m.start() - 18, len(s) - n))
    b = min(len(s), a + n)
    a2 = s.rfind(" ", 0, a + 1) if a else 0
    a = a2 + 1 if a and a2 >= 0 and a - a2 < 10 else a
    return ("…" if a else "") + s[a:b].strip() + ("…" if b < len(s) else "")


def disc_triggers(discs, contracts, classify, today):
    """공시 트리거 — 최근 1년 공급계약(계약 캐시 금액 합 · 매출 대비 % 합)과 설비투자 공시. discs = 내러티브.disc_rows 꼴(최신 먼저)."""
    since = (today - dt.timedelta(days=365)).strftime("%Y%m%d")
    out = []
    ords = [x for x in discs or () if x["d"] >= since and ORD_RX.search(x["title"] or "") and "정정" not in x["title"] and "해지" not in x["title"]]
    if ords:
        got = [(x, (contracts or {}).get(x["rcept"])) for x in ords]
        amt = [(x, c) for x, c in got if c and c.get("amount")]
        miss = len(ords) - len(amt)
        if amt:
            tot = sum(c["amount"] for _, c in amt)
            pct = sum(c.get("pct") or 0 for _, c in amt)
            text = "공급계약 %d건 · %s" % (len(amt), won(tot)) + (" (매출 대비 %.1f%%)" % pct if pct else "") + \
                   (" · 금액 미확인 %d건" % miss if miss else "")
            last = amt[0][0]
        else:
            text, last = "공급계약 공시 %d건(금액 미확인)" % len(ords), ords[0]
        out.append({"kind": "contract", "text": text, "src": "공시", "date": last["d"], "url": DART % last["rcept"],
                    "amount": sum(c["amount"] for _, c in amt) if amt else None})
    if classify is not None:
        cap = [x for x in discs or () if x["d"] >= since and (classify(x["title"] or "") or (None, None))[1] == "설비투자"
               and "정정" not in x["title"]]
        if cap:
            t0 = re.sub(r"\s+", " ", cap[0]["title"]).strip()
            text = ("설비투자 공시 %d건 · %s" % (len(cap), t0)) if len(cap) > 1 else "설비투자 공시 · %s" % t0
            out.append({"kind": "capex", "text": text, "src": "공시", "date": cap[0]["d"], "url": DART % cap[0]["rcept"], "amount": None})
    return out


def report_triggers(rows, since, words=(), skip=(), name=""):
    """리포트 트리거 — since 이후 줄(제목 · lines · concl) 중 숫자 + 트리거 낱말이 든 줄, 범주별 최신 1줄(같은 날이면 스토리 · 제품 낱말이 든 줄).
    skip = 여러 종목에 같은 글로 붙은 행(shared_rows 꼴, 업종 · 시장 카드) — 줄이나 제목에 내 이름(name)이 없으면 쓰지 않는다
    (SK그룹 '청주 100조원 투자' 줄이 삼성전자 설비투자로 · 기관 순매수 데일리가 증권사 넷의 설비투자로 왔다)."""
    keys = [kw_norm(w) for w in words or () if specific(w)]
    nk = _KW_STRIP.sub("", name or "").lower()
    best = {}
    for r in rows or ():
        d = (r.get("date") or "")[:10]
        if d < since:
            continue
        mine = not (skip and _rkey(r) in skip) or bool(nk and nk in _KW_STRIP.sub("", r.get("title") or "").lower())
        for ln in [r.get("title") or ""] + list(r.get("lines") or []) + [r.get("concl") or ""]:
            if not mine and not (nk and nk in _KW_STRIP.sub("", ln or "").lower()):
                continue
            for cat, rx in TRIG_RULES:
                m = rx.search(ln or "")
                if not m or (cat in ("order", "capex") and TRIG_SKIP.search(ln)) or (cat == "capex" and _not_capex(ln, m)):
                    continue
                hit = any(k in kw_norm(ln) for k in keys)
                rank = (d, hit)
                if cat not in best or rank > best[cat][0]:
                    best[cat] = (rank, {"kind": cat, "text": clip(ln, m), "src": "리포트", "by": r.get("broker"), "date": d,
                                        "url": r.get("msg_url") or next(iter(r.get("urls") or []), None)})
                break                 # 한 줄은 앞 범주 하나만 — 수주 줄('수주 5.4조원 … 반도체 팹')이 수주 공시에 밀려 설비투자로 오지 않게
    return {k: v[1] for k, v in best.items()}


def pick_triggers(disc, rep, n=MAX_TRIG):
    """같은 범주는 하나만 · 공시가 리포트보다 먼저. 단 설비투자 공시는 금액이 없으니 같은 범주 리포트 줄(금액 있음)이 증설 · CAPEX 를 말하면
    그 줄을 쓰고 공시는 note 로(아니면 공시 그대로 — SK하이닉스 '현금성자산 181조원' 줄이 신규시설투자 공시를 밀어냈다).
    한 리포트 줄이 두 범주에 걸리면(‘LTA 선수금 기반 캐파 증설 … 1.6조원’) 앞 범주만."""
    cap_d = any(t["kind"] == "capex" for t in disc)
    cats_d = {TRIG_CAT[t["kind"]] for t in disc if t["kind"] != "capex" or t.get("amount")}
    use, used = {}, set()
    for kind in ("price", "order", "capex", "util"):
        t = rep.get(kind)
        if kind == "capex" and t and cap_d and not CAPEX_WORD.search(t["text"]):
            continue
        if t and TRIG_CAT[kind] not in cats_d and t["text"] not in used:
            use[kind] = t
            used.add(t["text"])
    out, cats = [], set()
    for t in disc:
        if t["kind"] == "capex" and not t.get("amount") and use.get("capex"):
            continue
        out.append({k: v for k, v in t.items() if k != "amount"})
        cats.add(TRIG_CAT[t["kind"]])
    for kind in ("price", "order", "capex", "util"):
        t = use.get(kind)
        if not t or TRIG_CAT[kind] in cats:
            continue
        t = dict(t)
        if kind == "capex":
            d = next((x for x in disc if x["kind"] == "capex"), None)
            if d:
                t["note"] = "공시 %s.%s.%s %s" % (d["date"][:4], d["date"][4:6], d["date"][6:8], d["text"].split(" · ")[-1])
        out.append(t)
    return out[:n]


# ---------------------------------------------------------------- 5. 주가 단면 — 하루 한 번 988곳(서버가 파일을 하나씩 읽어 넘긴다)
def _shift(d8, days):
    return (dt.datetime.strptime(d8, "%Y%m%d") - dt.timedelta(days=days)).strftime("%Y%m%d")


def px_stats(series):
    """[(YYYYMMDD, 보정 종가)] 날짜순 → {d, px, hi, hd, dd, r1, r3, r6}. 52주 = 마지막 날부터 365일, n개월 = 30 · 91 · 182일 앞
    (그날 또는 그 앞 마지막 종가). 보정은 내러티브.adjusted — 마지막 값은 실제 종가 그대로다."""
    if not series:
        return None
    ds, cs = [x[0] for x in series], [x[1] for x in series]
    d = ds[-1]
    lo = bisect.bisect_left(ds, _shift(d, 365))
    hi_i = max(range(lo, len(cs)), key=lambda i: cs[i])
    out = {"d": d, "px": cs[-1], "hi": cs[hi_i], "hd": ds[hi_i], "dd": round((cs[-1] / cs[hi_i] - 1) * 100, 1)}
    for n, k in (("r1", 30), ("r3", 91), ("r6", 182)):
        i = bisect.bisect_right(ds, _shift(d, k)) - 1
        out[n] = round((cs[-1] / cs[i] - 1) * 100, 1) if i >= 0 and cs[i] else None
    return out


def xs_ranks(rows):
    """{code: px_stats} → 단면 날짜(가장 흔한 마지막 날)와 그날 종목들의 1 · 3 · 6개월 수익률 백분위(p1 · p3 · p6, 0–100)를 붙인다.
    그날 거래가 없던 종목(정지 · 늦은 파일)은 백분위 None. _mkt_med 누적은 쓰지 않는다(크게 틀린다)."""
    days = Counter(r["d"] for r in rows.values() if r)
    end = days.most_common(1)[0][0] if days else None
    for n in ("1", "3", "6"):
        vals = sorted(r["r" + n] for r in rows.values() if r and r["d"] == end and r.get("r" + n) is not None)
        for r in rows.values():
            if not r:
                continue
            v = r.get("r" + n)
            r["p" + n] = round(bisect.bisect_right(vals, v) / len(vals) * 100) if (vals and r["d"] == end and v is not None) else None
    return end


def px_out(x):
    """단면 한 줄 → 화면 주가 칸."""
    if not x:
        return None
    return {"px": x.get("px"), "date": x.get("d"), "hi52": x.get("hi"), "hi_date": x.get("hd"), "dd52": x.get("dd"),
            "r1m": x.get("r1"), "r3m": x.get("r3"), "r6m": x.get("r6"), "p1m": x.get("p1"), "p3m": x.get("p3"), "p6m": x.get("p6")}


# ---------------------------------------------------------------- 6. 후속주 후보
def phrase_tokens(prods):
    """제품 줄마다 낱말 집합 — '반도체 제조용 장비 外' → {반도체, 제조용, 장비}. 테마 이름 낱말이 다 들어 있으면 그 테마(match_themes)."""
    out = []
    for p in big_lines(prods):              # 작은 줄('건축/환경플랜드' 0.6%)로는 테마를 고르지 않는다
        for item in (p.get("item"), p.get("use")):
            toks = set(re.findall(r"[0-9a-z가-힣]{2,}", (item or "").lower()))
            if toks:
                out.append(toks)
    return out


def match_themes(themes, keys, phrases=()):
    """테마 이름 중 스토리 · 제품 낱말이 든 것(정규화 · 하이픈 무시, keys 는 kw_norm 한 말) — 또는 괄호 앞 이름이 두 낱말 이상이고
    그 낱말이 모두 한 제품 줄에 있는 것('반도체 장비' ← '반도체 제조용 장비 外')."""
    out = []
    for t in themes or ():
        k = kw_norm(t)
        if any(w and w in k for w in keys):
            out.append(t)
            continue
        toks = re.findall(r"[0-9a-z가-힣]{2,}", re.sub(r"\(.*$", "", t or "").lower())
        if len(toks) >= 2 and any(all(x in ph for x in toks) for ph in phrases or ()):
            out.append(t)
    return out


def _rkey(r):
    return ((r.get("date") or "")[:10], re.sub(r"\s+", "", r.get("title") or "")[:30])


def shared_rows(reps, since, k=3):
    """여러 종목에 같은 글로 붙은 행(중장기 투자유망 포트폴리오 · 데일리 카드) — (날짜, 제목 앞 30자)가 k 종목 이상.
    이런 글은 'MLCC' 한 줄이 SK하이닉스 · 신세계 · 삼양식품에 똑같이 붙어 동시 언급 잡음이 된다."""
    cnt = {}
    for cd, rows in (reps or {}).items():
        for r in rows or ():
            if (r.get("date") or "")[:10] >= since:
                cnt.setdefault(_rkey(r), set()).add(cd)
    return {key for key, v in cnt.items() if len(v) >= k}


def _key_rx(keys):
    """(disp, kw_norm) → (disp, k, rx). 두 글자 한글 말('은행')은 앞 글자가 한글이 아닐 때만 — '중앙은행' · '인터넷은행'은 은행 언급이 아니다."""
    return [k3 if len(k3) == 3 else (k3[0], k3[1], re.compile(r"(?<![가-힣])" + re.escape(k3[1])) if re.fullmatch(r"[가-힣]{2}", k3[1] or "") else None)
            for k3 in keys or ()]


def _low(s):
    """띄어쓰기는 두고 소문자 + 같은 제품 말(SYN)만 바꾼 꼴 — 두 글자 한글 말의 앞 글자를 보려고."""
    n = (s or "").lower()
    for a, b in SYN:
        n = n.replace(a, b)
    return n


def rep_scan(rows, since, keys, skip=(), loose=None):
    """한 종목 리포트 중 since 이후 · 키워드(kw_norm) 든 행 → 행마다 걸린 낱말(disp) 묶음 목록. skip = shared_rows 꼴의 열쇠.
    행 수 = 동시 언급 건수. 묶음으로 두는 것은 넓은 말(candidates 의 문서 빈도)을 빼고 다시 세기 위해서.
    loose(set)를 주면 두 글자 한글 말의 앞 글자 조건 없이 걸린 낱말도 모은다 — 넓은 말 셈은 느슨하게('비율'은 '자본비율'로 흔하다)."""
    mk = _key_rx(keys)
    out = []
    for r in rows or ():
        if (r.get("date") or "")[:10] < since or (skip and _rkey(r) in skip):
            continue
        hay = _hay(r)
        h, low = kw_norm(hay), None
        got = set()
        for disp, k, rx in mk:
            if k not in h:
                continue
            if loose is not None:
                loose.add(disp)
            if rx is not None:
                low = _low(hay) if low is None else low
                if not rx.search(low):
                    continue
            got.add(disp)
        if got:
            out.append(got)
    return out


def rep_hits(reps, since, keys, skip=(), codes=None, exclude=(), df=None):
    """종목마다 rep_scan → {code: [행마다 걸린 낱말 묶음]}. codes = 볼 종목(수집 회사), exclude = 뺄 종목. 서버가 한 번 세서
    스토리 칩 거르기(broad_words)와 candidates(hits=)에 같이 쓴다 — 180일 리포트를 두 번 훑지 않게. df(Counter)를 주면 느슨한 문서 빈도를 센다."""
    mk = _key_rx(keys)
    out = {}
    for cd, rows in (reps or {}).items():
        if (codes is not None and cd not in codes) or cd in exclude:
            continue
        lo = set() if df is not None else None
        hs = rep_scan(rows, since, mk, skip, lo)
        if lo:
            df.update(lo)
        if hs:
            out[cd] = hs
    return out


def broad_words(hits, df_max=None, df=None):
    """넓은 말 — 180일 리포트에서 df_max(REP_DF_MAX) 곳 넘게 걸리는 낱말('제시' 212곳 · '플랫폼' 83곳). df(느슨한 문서 빈도)가 있으면 그것으로."""
    df = df if df is not None else Counter(w for hs in (hits or {}).values() for w in set().union(*hs))
    return {w for w, n in df.items() if n > (REP_DF_MAX if df_max is None else df_max)}


def _phrases(item):
    """품목 칸 → 낱 제품 이름들('반도체기판, Tape Substrate, Photomask 등' → 셋). 괄호 안 목록도."""
    base = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", item or "")
    ps = re.split(r"[,/·]|\s및\s", base) + [x for pp in re.findall(r"\(([^)]*)\)", item or "") for x in re.split(r"[,/·]", pp)]
    return [p for p in (re.sub(r"\s*(?:등|외)\s*$", "", p).strip() for p in ps) if p]


def prod_hits(items, keys, lead_equip=False, min_pct=5.0):
    """다른 회사 제품 줄 [(item, seg, pct)] 중 내 제품 낱말로 끝나는 제품 이름이 있는 것 → [(낱말, 품목)].
    '끝나는' — 머리 낱말이 같아야 같은 제품('회로기판 소재'는 기판이 아니라 소재). 비중 min_pct 미만 · 장비 · 검사 품목(내 제품도 장비가 아니면)은 뺀다."""
    out = []
    for it in items or ():
        item, pct = (it[0], it[2] if len(it) > 2 else None) if isinstance(it, (list, tuple)) else (it.get("item"), it.get("pct"))
        if not item or GEN_ITEM.match(item.strip()) or (EQUIP_RX.search(item) and not lead_equip) or (pct is not None and pct < min_pct):
            continue
        ends = [e for e in (kw_norm(p) for p in _phrases(item)) if not REV_TAIL.search(e)]      # '상품매출(의류 등)'은 제품이 아니다
        hit = next((disp for disp, kk in keys if kk and any(e.endswith(kk) for e in ends)), None)
        if hit:
            out.append((hit, item))
    return out


# 묶음 매입 줄 — 품목 여럿을 한 줄로 적은 것('WAFER 외' · '강재, 기자재, 의장재 등')은 같은 줄 공급사가 서로 경쟁사가 아니다(서버 제품별 경쟁사 길)
BUNDLE_RX = re.compile(r"외\s*$|등\s*$|,|/|및|기타|\s외\s")
# 매입 줄 품목 → 그 품목을 만드는 회사의 제품 말(짧은 한글 매입처 이름을 이을 때 확인 — 솔루엠 '수동소자' 줄의 '삼영'은 삼영전자공업)
ITEM_FAMILY = {"수동소자": ("콘덴서", "커패시터", "mlcc", "인덕터", "칩저항", "저항기")}


def item_fit(item, prods):
    """매입 줄 품목(item)이 그 회사 제품 줄(prods — 제품 색인 [(item, seg, pct)])에 있나 — 한쪽이 다른 쪽을 품으면(정규화 · ITEM_FAMILY)."""
    keys = {k for k in (kw_norm(p) for p in _phrases(item)) if k}
    for k in list(keys):
        keys |= set(ITEM_FAMILY.get(k, ()))
    ends = [e for it in prods or () for e in (kw_norm(p) for p in _phrases(it[0] if isinstance(it, (list, tuple)) else it.get("item"))) if len(e) >= 2]
    return any(k in e or e in k for k in keys for e in ends)


def dedup_sellers(sellers, placed=()):
    """나를 매출처로 적은 회사 중 지주가 연결로 같은 내용을 적은 것(코스모화학 = 코스모신소재)을 뺀다 — 내 매입처로 잡힌 회사(placed)와
    이름 앞 세 글자가 같고 자기는 매입처로 안 잡혔으면 지주 쪽으로 본다."""
    keep = []
    for s in sellers or ():
        if s.get("code") not in placed and any(p.get("code") in placed and p is not s and len(s["name"]) >= 3 and p["name"][:3] == s["name"][:3]
                                             for p in sellers):
            continue
        keep.append(s)
    return keep


META_THEME = re.compile(r"밸류업|지주사|스페이스\s*X|SpaceX", re.I)     # 업종 · 제품이 아닌 테마(후보 · 순위에 안 쓴다)
NARROW_THEME = 40        # 주도주 좁은 테마(수집 회사 이만큼 이하) — 맞는 테마가 없거나 후보가 모자랄 때 채운다
FILL_MIN = 5


def candidates(lead, *, univ, stocks=None, theme_keys=(), story_keys=(), phrases=(), reps=None, since180="", rep_keys=(), supply=None,
               prod_index=None, prod_keys=(), lead_equip=False, exclude=(), rep_df_max=None, hits=None, shared=None, broad=None):
    """후속주 후보 — {code: {themes, st, nth, n180, rep_n, rep_by, supply, prod}}. 고른 회사 · exclude(모회사 · 계열 · 큰 지분)는 뺀다. 수집 회사(univ) 안만.
    1 스토리 테마(주도주 테마 중 맞는 것, 주도주 테마가 없으면 전체 테마에서) · 2 리포트 키워드 동시 언급(180일) · 3 공급망 · 4 같은 제품.
    맞는 테마가 없거나 후보가 FILL_MIN 곳 미만이면 주도주의 좁은 테마(NARROW_THEME 곳 이하, 작은 것부터 둘)로 채운다(손해보험 · 조선기자재 · MLCC).
    st = 스토리 낱말(story_keys)로 맞은 테마 수 — 제품 낱말로만 맞은 테마(PCB · 유리 기판)보다 앞에 세운다. nth = 주도주 테마(META 빼고) 중 같이 든 수,
    n180 = 180일 리포트 수 — 30줄 자르기의 동점 가르기(evidence_rank). hits · broad = rep_hits 결과와 넓은 말(서버가 미리 센 것 — 없으면 여기서 센다)."""
    rep_df_max = REP_DF_MAX if rep_df_max is None else rep_df_max
    skip = set(exclude) | {lead}
    out = {}

    def row(cd):
        return out.setdefault(cd, {"themes": [], "st": 0, "rep_n": 0, "rep_by": Counter(), "supply": [], "prod": []})
    stocks = stocks or {}
    mine = (stocks.get(lead) or {}).get("themes") or []
    th = match_themes(mine, theme_keys, phrases) if mine else []
    if not mine and (theme_keys or phrases):
        th = match_themes(sorted({t for v in stocks.values() for t in v.get("themes") or ()}), theme_keys, phrases)
    th = set(th)
    sth = set(match_themes(th, story_keys))
    if th:
        for cd, v in stocks.items():
            if cd in univ and cd not in skip:
                hit = sorted((t for t in v.get("themes") or () if t in th), key=lambda t: t not in sth)
                if hit:
                    r = row(cd)
                    r["themes"], r["st"] = hit, sum(1 for t in hit if t in sth)
    if rep_keys:
        if hits is None:
            df = Counter()
            hits = rep_hits(reps, since180, rep_keys, shared_rows(reps, since180) if shared is None else shared, univ, skip, df=df)
            broad = broad_words(None, rep_df_max, df)
        want = {disp for disp, _ in rep_keys}
        hits = {cd: [h & want for h in hs if h & want] for cd, hs in hits.items() if cd in univ and cd not in skip}
        hits = {cd: hs for cd, hs in hits.items() if hs}           # 종목 → 맞은 행마다 걸린 낱말 묶음
        # 넓은 말 — 180일 리포트에서 rep_df_max 곳 넘게 걸리는 낱말('제시' 212곳 · '플랫폼' 83곳 — 바이오 '기술 플랫폼'까지)은 동시 언급에 쓰지 않는다
        broad = broad if broad is not None else broad_words(hits, rep_df_max)
        for cd, hs in hits.items():
            hs = [h - broad for h in hs]
            hs = [h for h in hs if h]
            if hs:
                r = row(cd)
                r["rep_n"], r["rep_by"] = len(hs), Counter(w for h in hs for w in h)
    for cd, why in (supply or {}).items():
        if cd in univ and cd not in skip:
            row(cd)["supply"] = list(why)
    if prod_keys:
        for cd, items in (prod_index or {}).items():
            if cd in univ and cd not in skip:
                hit = prod_hits(items, prod_keys, lead_equip)
                if hit:
                    row(cd)["prod"] = hit
    # 리포트 동시 언급만 있는 후보는 업종(네이버 industry — 없으면 sector)이 주도주와 같을 때, 또는 공급망 · 같은 제품 후보의 업종이면서 동시 언급 2건↑일 때만
    # — 'MLB'(기판 · 야구 브랜드) 같은 동음 낱말, '반덤핑' 1건으로 넥센타이어에 온 철강, '스프레드'로 현대제철에 온 화학(sector '화학/소재'는 철강 · 화학을 다 덮는다)
    info = lambda cd: stocks.get(cd) or {}                                   # noqa: E731
    ind = lambda cd: info(cd).get("industry") or info(cd).get("sector")      # noqa: E731
    near = {ind(cd) for cd, r in out.items() if r["supply"] or r["prod"]}
    for cd in [cd for cd, r in out.items() if not (r["themes"] or r["supply"] or r["prod"])]:
        i = ind(cd)
        if i in (None, "기타") or i == ind(lead) or (i in near and out[cd]["rep_n"] >= 2):
            continue
        out.pop(cd)
    # 채우기 — 주도주 좁은 테마(META 빼고). '테마만'(연결 1)으로 든다
    if mine and (not th or len(out) < FILL_MIN):
        cnt = Counter(t for cd, v in stocks.items() if cd in univ for t in v.get("themes") or ())
        narrow = sorted((t for t in mine if t not in th and not META_THEME.search(t) and 1 < cnt[t] <= NARROW_THEME), key=lambda t: (cnt[t], t))[:2]
        for cd, v in stocks.items():
            if cd in univ and cd not in skip:
                hit = [t for t in v.get("themes") or () if t in narrow]
                if hit:
                    r = row(cd)
                    r["themes"] = r["themes"] + [t for t in hit if t not in r["themes"]]
    core = {t for t in mine if not META_THEME.search(t)}
    for cd, r in out.items():
        r["nth"] = len(core & set(info(cd).get("themes") or ()))
        r["n180"] = sum(1 for x in (reps or {}).get(cd) or () if (x.get("date") or "")[:10] >= since180)
    return out


def _weak(s):
    return isinstance(s, dict) and bool(s.get("weak"))


def link_score(c):
    """연결 칸 — 공급망 직접 5 · 같은 제품 4 · 리포트 동시 언급 3건↑ 또는 약한 공급망(지주가 연결 자회사 매입을 적은 것 — weak) 3 · 1–2건 2 · 테마만 1."""
    if any(not _weak(s) for s in c["supply"]):
        return 5
    if c["prod"]:
        return 4
    if c["rep_n"] >= 3 or c["supply"]:
        return 3
    if c["rep_n"]:
        return 2
    return 1 if c["themes"] else 0


def evidence_rank(c):
    """근거 많은 순 — 연결 칸, 키워드 리포트 수, 스토리 테마 수, 주도주 테마 중 같이 든 수, 테마 수, 180일 리포트 수.
    그래도 같으면 서버가 시가총액 큰 순(종목코드 순으로 자르면 테마만 걸린 판이 아무렇게나 잘렸다 — 한미반도체 '반도체 장비' 58곳)."""
    return (link_score(c), min(c["rep_n"], 30), c.get("st", 0), c.get("nth", 0), len(c["themes"]), min(c.get("n180", 0), 99))


# ---------------------------------------------------------------- 7. 점수 · 군
PHASE_PTS = {"확장 가속": 5, "확장 유지": 4, "확장": 4, "회복": 3, "정체": 2, "둔화": 2, "부진 지속": 1, "수축 심화": 1, "수축": 1}
SEVERE_LEVEL = ("작전주 꼴", "상폐 절차", "보고서 없음")
SEVERE_REF = {"감사의견비적정": "감사의견 비적정", "자본잠식": "자본잠식", "회생절차": "회생절차", "파산신청": "파산신청",
              "관리종목_사유": "관리종목 지정 사유", "관리종목_우려": "관리종목 우려", "실질심사": "상장적격성 실질심사", "상폐우려": "상장폐지 우려"}
WARN_REF = {"횡령배임": "횡령 · 배임 혐의", "불성실_지정": "불성실공시", "보고서지연": "보고서 지연", "투자주의환기": "투자주의 환기"}
FUND_CATS = ("CB발행", "BW발행", "유상증자", "제3자배정")      # 보컬.FUND_CATS · FUND_MIN=2 와 같은 문턱
LIGHT_CATS = ("사채조기상환", "금전대여")    # '작전주 꼴'이 이것만으로 섰으면 자금 거래(−2) — 2026-10-12 작전주 꼴 236곳 중 풋 97 · 금전대여 14곳이 이것만
KIS_SEVERE = ("관리종목", "거래정지", "정리매매", "투자위험")


def risk_flags(risk, kis_bad=(), kis_tags=(), opm=None):
    """건전성 칸 — 5에서: 작전주 꼴 · 상폐 절차 · 보고서 없음 · 감사 비적정 · 자본잠식(그 밖 상폐 사유) −5, 관리 · 정지 · 투자위험 −5,
    투자경고 −3, 투자주의 · 단기과열 · 자금조달 잦음 · 자금 거래(사채 풋 · 금전대여만으로 선 작전주 꼴) −2, 적자(OPM<0) −1. 최저 0. → (점수, [꼬리표])."""
    rk = risk or {}
    pen, flags = 0, []
    light = rk.get("level") == "작전주 꼴" and bool(rk.get("hits")) and all(h.get("cat") in LIGHT_CATS for h in rk["hits"])
    if rk.get("level") in SEVERE_LEVEL and not light:
        pen += 5
        flags.append(rk["level"])
    sev = [SEVERE_REF[r["cat"]] for r in rk.get("ref") or () if r.get("cat") in SEVERE_REF]
    if sev:
        pen += 5
        flags += sev
    flags += [WARN_REF[r["cat"]] for r in rk.get("ref") or () if r.get("cat") in WARN_REF]
    bad = [b for b in kis_bad or () if b in KIS_SEVERE]
    if bad:
        pen += 5
        flags += bad
    tags = list(kis_tags or ())
    if "투자경고" in tags:
        pen += 3
        flags.append("투자경고")
    soft = [t for t in tags if t in ("투자주의", "단기과열")]
    fund = rk.get("level") == "자금조달 잦음" or len([h for h in rk.get("hits") or () if h.get("cat") in FUND_CATS and (h.get("days") or 0) >= 2]) > 0
    if soft or fund or light:
        pen += 2
        flags += soft + (["자금조달 잦음"] if fund else []) + (["자금 거래"] if light else [])
    if opm is not None and opm < 0:
        pen += 1
        flags.append("적자")
    return max(0, 5 - pen), list(dict.fromkeys(flags))


def phase_of(druck, cur_v=None):
    """가속도 캐시(날것) → {label, phase, B, opm, yoy, old}. 국면 있는 마지막 점. v 가 지금 판이 아니면 old(화면 '옛 판')."""
    if not druck:
        return None
    pts = [p for p in druck.get("points") or () if p.get("국면")]
    if not pts:
        return None
    p = pts[-1]
    r1 = lambda v: None if v is None else round(v, 1)       # noqa: E731
    return {"label": p.get("label"), "phase": p.get("국면"), "B": r1(p.get("가속B")), "opm": r1(p.get("영업이익률")),
            "yoy": r1(p.get("매출YoY")), "old": cur_v is not None and druck.get("v") != cur_v}


def upside(rows, px, since):
    """증권사마다 최신 목표가(since 이후)의 평균 vs 지금 주가 → 상승여력 %(reports_view 와 같은 식, 주가만 단면에서)."""
    latest = {}
    for r in rows or ():
        if (r.get("date") or "")[:10] < since or not r.get("tp"):
            continue
        b = r.get("broker") or ("미표기 · %s %s" % ((r.get("date") or "")[5:10], (r.get("title") or "")[:14]))
        latest.setdefault(b, r["tp"])
    if not latest or not px:
        return None
    return round((sum(latest.values()) / len(latest) / px - 1) * 100, 1)


def score(c, *, lead_p3=None, px=None, ph=None, n_rep=0, up=None, risk=None, kis_bad=(), kis_tags=()):
    """후보 한 곳 → {parts, ev, group, stars, why, flags}. 칸마다 근거 줄을 남긴다. 25점 = 연결 · 실적 · 주목 · 덜 오름 · 건전성 × 5."""
    ev = {"link": [], "fund": [], "attn": [], "lag": [], "safe": []}
    link = link_score(c)
    for w in c["supply"][:3]:
        ev["link"].append(w["w"] if isinstance(w, dict) else w)
    for kw, item in c["prod"][:2]:
        ev["link"].append("같은 제품: %s" % (item if len(item) <= 30 else item[:29].rstrip(" ,") + "…"))     # 자른 자리는 말줄임으로
    if c["rep_n"]:
        kw = c["rep_by"].most_common(1)[0][0]
        ev["link"].append("%s 리포트 %d건(180일)" % (kw, c["rep_n"]))
    for t in c["themes"][:2]:
        ev["link"].append("%s 테마" % t)
    # 실적
    opm = ph.get("opm") if ph else None
    if not ph:
        fund = 2
        ev["fund"].append("국면 자료 없음")
    elif opm is not None and opm < 0:
        fund = 0
        ev["fund"].append("적자 · OPM %.1f%% (%s)" % (opm, ph.get("label")))
    else:
        fund = PHASE_PTS.get(ph["phase"], 2)
        ev["fund"].append("%s%s%s (%s)" % (ph["phase"], " · 가속B %+.1f" % ph["B"] if ph.get("B") is not None else "",
                                            " · OPM %.1f%%" % opm if opm is not None else "", ph.get("label")))
    # 주목
    attn = 0 if not c["rep_n"] else 2 if c["rep_n"] <= 2 else 3 if c["rep_n"] <= 9 else 4
    if c["rep_n"]:
        ev["attn"].append("%s 리포트 %d건(180일)" % (c["rep_by"].most_common(1)[0][0], c["rep_n"]))
    else:
        ev["attn"].append("키워드 리포트 없음(180일)" + (" · 전체 %d건" % n_rep if n_rep else ""))
    if up is not None:
        ev["attn"].append("상승여력 %+.0f%%" % up)
        if up >= 30:
            attn = min(5, attn + 1)
    # 덜 오름
    p3 = (px or {}).get("p3")
    if p3 is None or lead_p3 is None:
        lag = 2
        ev["lag"].append("3개월 백분위 자료 없음")
    else:
        d = lead_p3 - p3
        lag = 5 if d >= 30 else 4 if d >= 15 else 3 if d >= 0 else 1
        ev["lag"].append("3개월 백분위 %d vs 주도주 %d" % (p3, lead_p3))
    if (px or {}).get("dd") is not None and px["dd"] < -50:
        lag = max(0, lag - 1)
        ev["lag"].append("52주 고점 대비 %.0f%% — 망가짐" % px["dd"])
    # 건전성
    safe, flags = risk_flags(risk, kis_bad, kis_tags, opm)
    ev["safe"] = flags[:] or ["위험 꼬리표 없음"]
    parts = {"link": link, "fund": fund, "attn": attn, "lag": lag, "safe": safe}
    tot = sum(parts.values())
    p1 = (px or {}).get("p1")
    if safe <= 2 or (link <= 1 and p1 is not None and p1 >= 95 and fund <= 1):
        grp = "Fake"
    elif link >= 4 and tot >= 15:
        grp = "B"
    elif link >= 2 and tot >= 11:
        grp = "C"
    else:
        grp = "D"
    return {"score": tot, "parts": parts, "ev": ev, "group": grp, "stars": max(1, link), "flags": flags,
            "why": why_line(c, ph, fund, grp, flags)}


def _short_link(c):
    sup = sorted(c["supply"], key=_weak)           # 약한 공급망(연결 자회사 매입)은 같은 제품 뒤로
    if sup and not _weak(sup[0]):
        s = sup[0]
        return s["s"] if isinstance(s, dict) else s.split(" · ")[0][:24]
    if c["prod"]:
        return "%s 동종" % c["prod"][0][0]
    if sup:
        return sup[0]["s"]
    if c["themes"]:
        return re.sub(r"\(.*$", "", c["themes"][0]).strip() + " 테마"
    return None


def why_line(c, ph, fund, grp, flags):
    """한 줄 이유 — 가장 센 근거 둘(+ 국면): 'FC-BGA 동종 · 리포트 23건 · 확장 가속'. Fake 면 위험 꼬리표를 앞에.
    리포트 동시 언급만 있으면 낱말을 붙인다('DRAM 리포트 8건')."""
    parts = []
    if grp == "Fake" and flags:
        parts.append(flags[0])
    s = _short_link(c)
    if s:
        parts.append(s)
    if c["rep_n"]:
        parts.append("리포트 %d건" % c["rep_n"] if s else "%s 리포트 %d건" % (c["rep_by"].most_common(1)[0][0], c["rep_n"]))
    if ph and fund >= 3:
        parts.append(ph["phase"])
    elif ph and fund == 0:
        parts.append("적자")
    return " · ".join(parts[:3])


def counts(rows):
    cnt = Counter(r["group"] for r in rows)
    return {"total": len(rows), "B": cnt.get("B", 0), "C": cnt.get("C", 0), "D": cnt.get("D", 0), "Fake": cnt.get("Fake", 0)}


GROUP_ORDER = {"B": 0, "C": 1, "D": 2, "Fake": 3}


def sort_rows(rows):
    return sorted(rows, key=lambda r: (GROUP_ORDER[r["group"]], -r["score"], r["code"]))


# ---------------------------------------------------------------- 8. 그물망
def _ga(nm):
    """조사 '이/가' — 끝 글자 받침."""
    ch = (nm or "")[-1:]
    return "이" if ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "가"


def _seg_key(s):
    return re.sub(r"\s+|부문|사업부|사업", "", s or "")


def period_label(p):
    """밸류체인 칸 정보 → '2026 반기' · '2026 1분기' · '2025'."""
    if not p:
        return ""
    st, lb = p.get("stamp") or "", p.get("label") or ""
    if "반기" in lb:
        return "%s 반기" % st[:4]
    if "분기" in lb:
        return "%s %d분기" % (st[:4], {"03": 1, "09": 3}.get(st[5:7], 0))
    return st[:4]


def up_groups(materials, products, link, sellers=(), skip=(), lead_name="", max_groups=3, max_items=5, name_of=None):
    """원재료를 제품 부문별로 묶는다(금액 큰 부문부터 최대 3) — 묶음 = {seg, c, label, items:[{item, pct, sup:[{name, code, co}]}], listed}.
    co = 이은 상장사 이름(적힌 이름과 다를 때만 — 'COSMO' → 코스모신소재). '기타' 품목은 뒤로.
    나를 매출처로 적은 상장사(sellers)는 그 회사가 매입처로 잡힌 묶음에, 모르면 첫 묶음에."""
    cmap = {_seg_key(p["seg"]): p["c"] for p in products or () if p.get("seg")}
    nxt = max([p["c"] for p in products or ()] + [-1]) + 1
    groups = {}
    for mt in materials or ():
        item = (mt.get("item") or "").strip()
        if not item or item == "-" or re.search(r"합\s*계|소\s*계", item):
            continue
        seg = (mt.get("segment") or "").strip() or None
        g = groups.setdefault(seg, {"seg": seg, "items": [], "amt": 0.0, "pct": 0.0})
        g["amt"] += mt.get("amt") or 0
        g["pct"] += mt.get("pct") or 0
        sup, seen = [], set()
        for sp in mt.get("suppliers") or ():
            nm = (sp.get("name") or "").strip()
            if not nm:
                continue
            cd = link(nm) if link else None
            key = cd or norm_ko(short_name(nm) or nm)
            if key in seen:                  # 한 품목에 같은 회사 두 번('효성' · '효성' — 넥센타이어)
                continue
            seen.add(key)
            co = name_of(cd) if cd and name_of else None
            sup.append(dict({"name": short_name(nm) or nm, "code": cd}, **({"co": co} if co and norm_ko(co) != norm_ko(short_name(nm)) else {})))
        g["items"].append({"item": item, "pct": mt.get("pct"), "sup": sup})
    order = sorted(groups.values(), key=lambda g: (-(g["amt"] or 0), -(g["pct"] or 0)))[:max_groups]
    out = []
    for g in order:
        k = _seg_key(g["seg"])
        if g["seg"] and k in cmap:
            c = cmap[k]
        else:
            c, nxt = nxt, nxt + 1
        its = g["items"]
        if len(its) > 1:          # 합계 줄(100%)이 품목처럼 들어온 표 · 같은 이름 겹침
            its = [x for x in its if (x["pct"] or 0) < 99.5] or its
        seen_, its2 = set(), []
        for x in its:
            if (x["item"], tuple(sp["name"] for sp in x["sup"])) not in seen_:
                seen_.add((x["item"], tuple(sp["name"] for sp in x["sup"])))
                its2.append(x)
        items = sorted(its2, key=lambda x: (bool(re.match(r"^기타", x["item"])), -(x["pct"] or 0)))[:max_items]
        label = "상류 · %s 소재 · 장비" % g["seg"] if g["seg"] else "상류 · 원재료 · 장비"
        out.append({"seg": g["seg"], "c": c, "label": label, "items": items, "listed": []})
    if out:
        placed = {sp["code"] for g in out for it in g["items"] for sp in it["sup"] if sp["code"]}
        for s in dedup_sellers(sellers, placed):
            if not s.get("code") or s["code"] in skip or s.get("group"):
                continue
            home = next((g for g in out for it in g["items"] for sp in it["sup"] if sp["code"] == s["code"]), None)
            item = next((it["item"] for it in (home or {}).get("items", []) for sp in it["sup"] if sp["code"] == s["code"]), None)
            why = "%s%s %s를 매출처로 적음" % (s["name"], _ga(s["name"]), lead_name) + (" · %s" % item if item else "")
            (home or out[0])["listed"].append({"name": s["name"], "code": s["code"], "why": why})
    return out


NOT_CO = re.compile(r"스왑|선도|옵션|파생|통화|이자율|주식$|자산$|소계|수익$|거래처$|^[A-Z]\s*거래처")   # 매출처 칸에 든 회사 아닌 줄(이자율스왑 · 카드론수익 · A 거래처)


def down_nodes(customers, buyers, orders, link=None, period="", max_cust=5, max_buy=5, max_ord=3):
    """하류 — 매출처(비중) · 나를 매입처로 적은 회사(그쪽 매입 중 비중 · 품목) · 계약 상대(건수 · 합계).
    회사가 아닌 매출처 줄(NOT_CO)은 빼고, 같은 회사(코드)가 둘이면 한 노드로('매출처 26.0% · 매입 중 Camera Module 7.9%')."""
    out = []
    for h in [h for h in customers or () if h.get("pct") and not h.get("self") and not NOT_CO.search(re.sub(r"\s+", " ", h.get("name") or "").strip())][:max_cust]:
        cd = (h.get("link") or {}).get("code") or (link(h["name"]) if link else None)
        out.append({"kind": "customer", "name": h["name"], "code": cd, "pct": h["pct"],
                    "why": "매출처 %.1f%%" % h["pct"] + (" (%s)" % period if period else "")})
    by = {}
    for b in buyers or ():
        x = by.setdefault(b["code"], {"kind": "buyer", "name": b["name"], "code": b["code"], "pct": None, "items": []})
        if b.get("pct") is not None and (x["pct"] is None or b["pct"] > x["pct"]):
            x["pct"] = b["pct"]
        for it in b.get("items") or ():
            if it not in x["items"]:
                x["items"].append(it)
    for x in sorted(by.values(), key=lambda x: -(x["pct"] or 0))[:max_buy]:
        it = " · ".join(x["items"][:2])
        x["why"] = "%s 매입 중 %s%s" % (x["name"], (it + " ") if it else "", "%.1f%%" % x["pct"] if x["pct"] is not None else "(비중 미기재)")
        out.append({k: x[k] for k in ("kind", "name", "code", "pct", "why")})
    for o in (orders or ())[:max_ord]:
        cd = (o.get("link") or {}).get("code")
        out.append({"kind": "contract", "name": o["party"], "code": cd, "n": o["n"], "amount": o.get("amount"),
                    "why": "공급계약 %d건 · %s" % (o["n"], won(o.get("amount")) if o.get("amount") else "금액 미확인")})
    merged, at = [], {}
    for x in out:
        if x.get("code") and x["code"] in at:
            m = at[x["code"]]
            w = x["why"][len(x["name"]) + 1:] if x["why"].startswith(x["name"] + " ") else x["why"]
            m["why"] = "%s · %s" % (m["why"], w)
            continue
        if x.get("code"):
            at[x["code"]] = x
        merged.append(x)
    return merged


def node_name(d, code):
    """지도 payload 안에서 코드 하나의 이름 — 심층 칸이 Linker 를 다시 짓지 않고 이름을 찾는다."""
    net = (d or {}).get("net") or {}
    pool = [(r.get("code"), r.get("name")) for r in (d or {}).get("matrix") or ()]
    pool += [((net.get("owner") or {}).get("code"), (net.get("owner") or {}).get("name"))]
    pool += [(h.get("code"), h.get("name")) for h in net.get("holdings") or ()] + [(x.get("code"), x.get("name")) for x in net.get("down") or ()]
    pool += [(cd, nm) for nm, cd in (net.get("group") or {}).get("names") or ()] + [(p.get("code"), p.get("name")) for p in net.get("peers") or ()]
    for g in net.get("up") or ():
        pool += [(sp.get("code"), sp.get("co") or sp.get("name")) for it in g.get("items") or () for sp in it.get("sup") or ()]
        pool += [(x.get("code"), x.get("name")) for x in g.get("listed") or ()]
    return next((nm for cd, nm in pool if cd and cd == code and nm), None)


def peer_nodes(rows, up=(), down=(), n=6):
    """동종 후속주 칸 — 매트릭스 B · C 상위 n. 위 · 아래 칸에 이미 있는 공급망 회사(매입처 · 나를 매출처로 적은 곳 · 고객)는 뒤로
    (삼성전기: 코스모신소재 · 영풍이 동종 자리를 차지했다). 모자라면 그들로 채운다."""
    placed = {sp.get("code") for g in up or () for it in g.get("items") or () for sp in it.get("sup") or ()}
    placed |= {x.get("code") for g in up or () for x in g.get("listed") or ()} | {x.get("code") for x in down or ()}
    placed.discard(None)
    bc = [r for r in rows if r["group"] in ("B", "C")]
    return [{"code": r["code"], "name": r["name"], "group": r["group"]}
            for r in ([r for r in bc if r["code"] not in placed] + [r for r in bc if r["code"] in placed])[:n]]


def node_rel(d, code):
    """지도 payload 에서 한 노드(code)에 걸린 근거 줄 — 심층 칸(/api/vcmap/node)이 쓴다."""
    if not d or not code:
        return []
    out = []
    net = d.get("net") or {}
    ow = net.get("owner") or {}
    src = d.get("src") or {}
    vcp = (src.get("vc") or {}).get("period") or ""                          # '2026 반기' — 어느 보고서 · 어느 표
    osrc = ((src.get("own") or {}).get("src") or "").split(" · ")[0]          # '2026-06 반기보고서'
    if ow.get("code") == code:                  # 관계 칸('최대주주 본인' · '本人')은 그쪽 회사 기준 말이라 적지 않는다
        out.append("%s 최대주주%s%s" % (d.get("name") or "", " %.2f%%" % ow["pct"] if ow.get("pct") is not None else "",
                                       " (%s)" % ow["src"] if ow.get("src") else ""))
    for h in net.get("holdings") or ():
        if h.get("code") == code:
            out.append("%s 보유 %.2f%%%s%s" % (d.get("name"), h["pct"], " · " + h["purpose"] if h.get("purpose") else "",
                                               " (%s · 타법인출자 현황)" % osrc if osrc else ""))
    for g in net.get("up") or ():
        for it in g.get("items") or ():
            for sp in it.get("sup") or ():
                if sp.get("code") == code:           # 비중은 품목 몫(매입처 몫이 아니다) — 적힌 이름이 상장 이름과 다르면 그대로 붙인다
                    out.append("%s원재료 %s 매입처%s%s%s" % (g["seg"] + " " if g.get("seg") else "", it["item"],
                                                         " · 매입 비중 %.1f%%" % it["pct"] if it.get("pct") is not None else "",
                                                         " · 보고서 표기 '%s'" % sp["name"] if sp.get("co") else "",
                                                         " (%s · 주요 원재료)" % vcp if vcp else ""))
        for x in g.get("listed") or ():
            if x.get("code") == code:
                out.append(x["why"])
    for x in net.get("down") or ():
        if x.get("code") == code:
            out.append(x["why"])
    for r in d.get("matrix") or ():
        if r.get("code") == code:
            out.append("후속주 %s군 %d점 — %s" % (r["group"], r["score"], r.get("why") or ""))
            out += [w for w in (r.get("ev") or {}).get("link") or () if w not in out]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 9. payload
def payload(*, code, name, built, leader, story, triggers, net, matrix, src):
    """서버 ↔ 화면 계약(설계 '응답 꼴'). pending · stale 은 서버가 응답 때 붙인다."""
    return {"v": V, "code": code, "name": name, "built": built,
            "head": {"leader": leader, "story": story, "triggers": triggers, "counts": counts(matrix)},
            "net": net, "matrix": matrix, "src": src, "note": NOTE}
