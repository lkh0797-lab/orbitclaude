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

V = 4                     # 2: 근거마다 출처 객체(ev) · 설명 문장(expl) · 과거 공급망 · 같은 고객 · 건전성 차감 · 트리거 문장 자르기(2026-10-13 2차 개선)
                          # 3: 설명 문장 손질 — 조사는 끝소리로(3으로 · MLCC를 · 나노엔텍과), 리포트 건수 되풀이 안 함, 주목 · 위험 문장에 서술어, 매입 · 매출 비중 말(2026-10-13 통합)
                          # 4: 비중은 무엇의 몫인지 표 꼴대로(부문 · 매입처마다 한 줄인 표), 과거 공급망 해 목록(2021 · 2024년), 같은 제품 비중은 표 값만(금액 비율은 '추정'),
                          #    목표가 출처는 증권사 곳 수, 매출처 줄에서 품목 뺌(2026-10-13 3차 손질)
NOTE = "규칙 점수 · 검증 전 — 예측 아님"
GROUP_NOTE = {"B": "연결 세고 점수 높음", "C": "연결 있으나 일부만 확인", "D": "테마 위주 · 근거 약함",
              "Fake": "위험 꼬리표 또는 급등 + 근거 약함 — 후속주로 보기 어려움"}
MAX_ROWS = 30             # 매트릭스 최대 줄(근거 많은 순)
MAX_TRIG = 4
REP_DF_MAX = 40          # 리포트 동시 언급 낱말이 180일 리포트에서 이만큼(종목 수) 넘게 걸리면 넓은 말 — 리포트 있는 곳 약 710 중.
                         # 2026-10-12 실측: MLCC 5 · FC-BGA 7 · DRAM 16 · 은행 20 · HBM 24 · 광고 26 / 기판 47 · 방산 55 · 플랫폼 83 · 제시 212.
                         # 40 을 넘는 업종 말(방산 · ESS · 임상)은 테마 쪽으로 이미 잡힌다
DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=%s"


def d8(s):
    """'2026-10-08 07:25' · '20261008' · 접수번호 → 'YYYYMMDD'(여덟 자리가 안 되면 None)."""
    t = re.sub(r"\D", "", (s or "")[:10])
    return t[:8] if len(t) >= 8 else None


def ev(t, src=None, date=None, url=None, go=None, **more):
    """근거 한 줄 — 화면 계약 {t, src, date, url, go}(없는 값은 키를 뺀다 — 화면 vbEv 는 없는 키를 비어 있다고 읽는다).
    숫자 · 문구는 모두 캐시 값에서 온 것이어야 한다(지어내지 않는다). go = {tab, code} 탭 이동."""
    d = {"t": t, "src": src}
    for k, v in (("date", d8(date) if date else None), ("url", url), ("go", go)):
        if v:
            d[k] = v
    d.update({k: v for k, v in more.items() if v})
    return d


def report_name(period):
    """period_label 꼴 → 보고서 이름: '2026 반기' → '2026 반기보고서', '2026 1분기' → '2026 1분기보고서', '2025' → '2025 사업보고서'."""
    p = (period or "").strip()
    if not p:
        return "보고서"
    return p + ("보고서" if re.search(r"(?:반기|분기)$", p) else " 사업보고서")


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
    if GEN_ITEM.match(item) and p.get("use") and not GEN_ITEM.match(p["use"].strip()) and not re.match(r"^기타", item):
        item = p["use"].strip()          # '기타제품 등'(용도 '후판,선재 등')은 용도로 바꾸지 않는다 — 제품 이름이 아니라 같은 제품 맞추기에 쓰면 안 된다(POSCO홀딩스 → 세아홀딩스 '선재')
    if not re.search(r"[가-힣A-Za-z]", item):
        return ""
    m = re.match(r"^(.*?)\(([^)]*,[^)]*)\)\s*$", item)
    if m:
        first = re.split(r"\s*,\s*", m.group(2))[0].strip()
        item = "%s(%s 등)" % (m.group(1).strip(), re.sub(r"\s*등$", "", first))
    return item[:40]


SUM_ROW = re.compile(r"합\s*계|소\s*계|총\s*계|매출\s*총계|내부\s*거래|연결\s*조정|단순\s*합계")       # 합계 · 조정 줄(품목 · 부문 · 용도 · 구분 칸 어디에 있든)


def products_of(prods, top=None):
    """밸류체인 제품 매출 구성 → [{item, seg, pct, use, c(, est)}] 비중 큰 순. 합계 · 기타 · 내부거래 · 단위 줄은 빼고 같은 이름은 합친다.
    비중이 없으면 금액으로 나눈다 — 그 줄은 est(금액 비율 추정, 표의 비중이 아니다). 합계 · 내부거래제거 · 연결조정 줄은 용도 · 구분 칸에 적혀 있어도 나누기 전에 뺀다
    (POSCO홀딩스 '물류등부문 단순합계' 가 분모에 들어 '후판,선재 등 9.8%' 가 나왔다). c = 부문 색 번호(부문 합 큰 순 0,1,2… — 부문이 없으면 품목마다)."""
    rows = []
    for p in prods or ():
        lab = product_label(p)
        seg = (p.get("segment") or "").strip() or None
        if not lab or GEN_ITEM.match(lab) or SUM_ROW.search(" ".join(x for x in (lab, seg, p.get("use"), p.get("kind")) if x)):
            continue
        if seg and GEN_ITEM.match(seg):
            seg = None
        rows.append({"item": lab, "seg": seg, "pct": p.get("pct"), "amt": p.get("amt"), "use": p.get("use")})
    if not rows:
        return []
    est = False
    if any(r["pct"] is None for r in rows) and all(isinstance(r["amt"], (int, float)) and r["amt"] > 0 for r in rows):
        tot = sum(r["amt"] for r in rows)
        est = True
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
    out = [dict({"item": r["item"], "seg": r["seg"], "pct": round(r["pct"], 1) if r["pct"] is not None else None, "raw": r["pct"],
                 "use": r["use"], "c": cmap[r["seg"] or "·" + r["item"]]}, **({"est": True} if est else {})) for r in rows]     # raw = 안 둥글린 값(pct0 가 두 번 둥글리지 않게)
    return out[:top] if top else out


def pct0(p):
    """비중을 정수 %로 — 반올림은 ROUND_HALF_UP(34.5 → 35. '%.0f' 는 짝수로 가 34.52(표) → 34.5 → '34' 였다)."""
    return "%d%%" % int(p + 0.5) if p >= 0 else "%d%%" % -int(-p + 0.5)


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


STRONG_B = re.compile(r"(?<=[.!?。:：])(?=\s|$)")     # 문장 경계 — 마침표 · 콜론 뒤에 공백(숫자 '4.27' 안의 점은 아니다)
WEAK_B = re.compile(r"(?<=[며고])(?=[,\s]|$)")         # 이음 경계 — '…하며,' · '…하고 ' 뒤


def clip_sent(line, m, n=60):
    """트리거 줄을 문장 경계에서 자른다 — 맞은 자리가 든 문장을 통째(앞 '…' 없이). n자를 넘으면 그 안의 마지막 경계(마침표 · '며' · '고' 뒤)까지,
    그래도 안 맞으면 앞 이음 경계부터. 경계가 아예 없으면 clip(맞은 자리 둘레 n자 · '…'). m 은 공백을 하나로 모은 줄(정규화한 꼴)에서 맞춘 것."""
    s = re.sub(r"\s+", " ", line or "").strip()
    if len(s) <= n + 16:
        return s
    strong = {0, len(s)} | {b.start() for b in STRONG_B.finditer(s)}
    weak = strong | {b.start() for b in WEAK_B.finditer(s)}
    st = max(b for b in strong if b <= m.start())
    en = min(b for b in strong if b >= m.end())
    if en - st > n:
        inner = [b for b in weak if m.end() <= b <= st + n]
        if inner:
            en = max(inner)
        else:
            back = [b for b in weak if b <= m.start() and en - b <= n]
            if back:
                st = max(back)
            else:
                st = max([b for b in weak if b <= m.start()] or [st])
                inner = [b for b in weak if m.end() <= b <= st + n]
                if inner:
                    en = max(inner)
                else:                                   # 뒤에 경계가 없다 — 앞은 경계부터('…' 없이), 뒤는 n자 안 마지막 낱말까지 + '…'
                    sp = s.rfind(" ", m.end(), st + n + 1)
                    if sp <= m.end():
                        return clip(s, m, n)
                    return s[st:sp].strip(" ,:") + "…"
    return s[st:en].strip(" ,:")


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
            ln = re.sub(r"\s+", " ", ln or "").strip()          # 공백을 하나로 — clip_sent 의 경계 자리와 맞춘다
            if not mine and not (nk and nk in _KW_STRIP.sub("", ln).lower()):
                continue
            for cat, rx in TRIG_RULES:
                m = rx.search(ln)
                if not m or (cat in ("order", "capex") and TRIG_SKIP.search(ln)) or (cat == "capex" and _not_capex(ln, m)):
                    continue
                hit = any(k in kw_norm(ln) for k in keys)
                rank = (d, hit)
                if cat not in best or rank > best[cat][0]:
                    best[cat] = (rank, {"kind": cat, "text": clip_sent(ln, m), "src": "리포트", "by": r.get("broker"), "date": d,
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


def rep_scan(rows, since, keys, skip=(), loose=None, refs=None):
    """한 종목 리포트 중 since 이후 · 키워드(kw_norm) 든 행 → 행마다 걸린 낱말(disp) 묶음 목록. skip = shared_rows 꼴의 열쇠.
    행 수 = 동시 언급 건수. 묶음으로 두는 것은 넓은 말(candidates 의 문서 빈도)을 빼고 다시 세기 위해서.
    loose(set)를 주면 두 글자 한글 말의 앞 글자 조건 없이 걸린 낱말도 모은다 — 넓은 말 셈은 느슨하게('비율'은 '자본비율'로 흔하다).
    refs(list)를 주면 걸린 행마다 출처 {date, by, url, title}를 같은 순서로 담는다(근거 줄의 '{증권사} {날짜} · t.me')."""
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
            if refs is not None:
                refs.append({"date": (r.get("date") or "")[:10], "by": r.get("broker"), "title": re.sub(r"\s+", " ", r.get("title") or "").strip()[:40],
                             "url": r.get("msg_url") or next(iter(r.get("urls") or []), None)})
    return out


def rep_hits(reps, since, keys, skip=(), codes=None, exclude=(), df=None, refs=None):
    """종목마다 rep_scan → {code: [행마다 걸린 낱말 묶음]}. codes = 볼 종목(수집 회사), exclude = 뺄 종목. 서버가 한 번 세서
    스토리 칩 거르기(broad_words)와 candidates(hits=)에 같이 쓴다 — 180일 리포트를 두 번 훑지 않게. df(Counter)를 주면 느슨한 문서 빈도를 센다.
    refs(dict)를 주면 {code: [행마다 출처]}를 같은 순서로 채운다."""
    mk = _key_rx(keys)
    out = {}
    for cd, rows in (reps or {}).items():
        if (codes is not None and cd not in codes) or cd in exclude:
            continue
        lo = set() if df is not None else None
        rf = [] if refs is not None else None
        hs = rep_scan(rows, since, mk, skip, lo, rf)
        if lo:
            df.update(lo)
        if hs:
            out[cd] = hs
            if refs is not None:
                refs[cd] = rf
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
    """다른 회사 제품 줄 [(item, seg, pct(, est))] 중 내 제품 낱말로 끝나는 제품 이름이 있는 것 → [(낱말, 품목, 비중, est)].
    est = 비중이 표 값이 아니라 금액 비율 추정(products_of). '끝나는' — 머리 낱말이 같아야 같은 제품('회로기판 소재'는 기판이 아니라 소재).
    비중 min_pct 미만 · 장비 · 검사 품목(내 제품도 장비가 아니면)은 뺀다."""
    out = []
    for it in items or ():
        if isinstance(it, (list, tuple)):
            item, pct, est = it[0], it[2] if len(it) > 2 else None, bool(it[3]) if len(it) > 3 else False
        else:
            item, pct, est = it.get("item"), it.get("pct"), bool(it.get("est"))
        if not item or GEN_ITEM.match(item.strip()) or (EQUIP_RX.search(item) and not lead_equip) or (pct is not None and pct < min_pct):
            continue
        ends = [e for e in (kw_norm(p) for p in _phrases(item)) if not REV_TAIL.search(e)]      # '상품매출(의류 등)'은 제품이 아니다
        hit = next((disp for disp, kk in keys if kk and any(e.endswith(kk) for e in ends)), None)
        if hit:
            out.append((hit, item, pct, est))
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
               prod_index=None, prod_keys=(), lead_equip=False, exclude=(), rep_df_max=None, hits=None, shared=None, broad=None,
               rep_refs=None, hist=None, samecust=None, lead_name=""):
    """후속주 후보 — {code: {themes, st, nth, n180, rep_n, rep_by, rep_refs, supply, prod}}. 고른 회사 · exclude(모회사 · 계열 · 큰 지분)는 뺀다. 수집 회사(univ) 안만.
    1 스토리 테마(주도주 테마 중 맞는 것, 주도주 테마가 없으면 전체 테마에서) · 2 리포트 키워드 동시 언급(180일) · 3 공급망(지금 · 과거 · 같은 고객) · 4 같은 제품.
    맞는 테마가 없거나 후보가 FILL_MIN 곳 미만이면 주도주의 좁은 테마(NARROW_THEME 곳 이하, 작은 것부터 둘)로 채운다(손해보험 · 조선기자재 · MLCC).
    st = 스토리 낱말(story_keys)로 맞은 테마 수 — 제품 낱말로만 맞은 테마(PCB · 유리 기판)보다 앞에 세운다. nth = 주도주 테마(META 빼고) 중 같이 든 수,
    n180 = 180일 리포트 수 — 30줄 자르기의 동점 가르기(evidence_rank). hits · broad = rep_hits 결과와 넓은 말(서버가 미리 센 것 — 없으면 여기서 센다).
    rep_refs = rep_hits(refs=) 결과(행마다 출처) — 걸린 행 중 최신 둘을 rep_refs 로 남긴다. hist = {code: [공급망 근거 dict]} 과거 공급망(지금 칸엔 없고 과거 칸에 있는 것 — 연결 3),
    samecust = {code: {cust, pct, lead_pct, name}} 같은 고객에 파는 회사 — 주도주와 맞는 테마 · 제품 낱말을 함께 가질 때만 후보(연결 3). 같은 고객만으로는 아니다."""
    rep_df_max = REP_DF_MAX if rep_df_max is None else rep_df_max
    skip = set(exclude) | {lead}
    out = {}

    def row(cd):
        return out.setdefault(cd, {"themes": [], "st": 0, "rep_n": 0, "rep_by": Counter(), "rep_refs": [], "supply": [], "prod": []})
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
            rep_refs = {} if rep_refs is None else rep_refs
            hits = rep_hits(reps, since180, rep_keys, shared_rows(reps, since180) if shared is None else shared, univ, skip, df=df, refs=rep_refs)
            broad = broad_words(None, rep_df_max, df)
        want = {disp for disp, _ in rep_keys}
        refs = rep_refs or {}
        pairs = {}                                                 # 종목 → [(맞은 행의 낱말 묶음, 그 행 출처)]
        for cd, hs in hits.items():
            if cd not in univ or cd in skip:
                continue
            rf = refs.get(cd) or []
            ps = [(h & want, rf[i] if i < len(rf) else None) for i, h in enumerate(hs) if h & want]
            if ps:
                pairs[cd] = ps
        # 넓은 말 — 180일 리포트에서 rep_df_max 곳 넘게 걸리는 낱말('제시' 212곳 · '플랫폼' 83곳 — 바이오 '기술 플랫폼'까지)은 동시 언급에 쓰지 않는다
        broad = broad if broad is not None else broad_words({cd: [h for h, _ in ps] for cd, ps in pairs.items()}, rep_df_max)
        for cd, ps in pairs.items():
            ps = [(h - broad, rf) for h, rf in ps if h - broad]
            if ps:
                r = row(cd)
                r["rep_n"], r["rep_by"] = len(ps), Counter(w for h, _ in ps for w in h)
                r["rep_refs"] = sorted((rf for _, rf in ps if rf), key=lambda x: x.get("date") or "", reverse=True)[:2]
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
    # 과거 공급망(연결 3) — 지금 칸엔 없고 과거 칸에 있는 매입처 · 매출처(주도주 쪽 · 후보 쪽). 서버가 근거 dict(w · s · k · src · date · url · d)로 넘긴다
    for cd, ws in (hist or {}).items():
        if cd in univ and cd not in skip and ws:
            r = row(cd)
            have = {x["w"] for x in r["supply"] if isinstance(x, dict)}
            r["supply"] += [dict(w, weak=True, k=w.get("k") or "hist") for w in ws if w.get("w") and w["w"] not in have]
    # 같은 고객 + 같은 테마 · 제품(연결 3) — 같은 고객만으로는 후보가 아니다(삼성전자에 파는 반도체 장비사가 끌려오지 않게)
    for cd, sc in (samecust or {}).items():
        r = out.get(cd)
        if cd not in univ or cd in skip or not r or not (r["themes"] or r["prod"]):
            continue
        tag = (re.sub(r"\(.*$", "", r["themes"][0]).strip() + " 테마") if r["themes"] else "%s 동종" % r["prod"][0][0]
        w = "%s에 매출 %s (%s도 %s) · %s" % (sc.get("cust"), pct_s(sc.get("pct")), lead_name or "주도주", pct_s(sc.get("lead_pct")), tag)
        if w not in {x["w"] for x in r["supply"] if isinstance(x, dict)}:
            r["supply"].append({"w": w, "s": "같은 고객 %s · %s" % (sc.get("cust"), tag), "k": "same", "weak": True, "d": dict(sc, tag=tag)})
    core = {t for t in mine if not META_THEME.search(t)}
    for cd, r in out.items():
        r["nth"] = len(core & set(info(cd).get("themes") or ()))
        r["n180"] = sum(1 for x in (reps or {}).get(cd) or () if (x.get("date") or "")[:10] >= since180)
    return out


def pct_s(p):
    return ("%.0f%%" % p) if isinstance(p, (int, float)) else "비중 미기재"


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


WARN_PEN = {"횡령배임": 3, "보고서지연": 2, "투자주의환기": 2, "불성실_지정": 1}      # 2026-10-13: 꼬리표만 붙고 안 깎이던 것(삼영전자공업 · 영풍 · 이수페타시스)


def risk_items(risk, kis_bad=(), kis_tags=(), opm=None, kis_date=None, risk_date=None, druck_src=None):
    """건전성 칸 — (점수, [근거 객체 ev]). 5에서: 작전주 꼴 · 상폐 절차 · 보고서 없음 · 감사 비적정 · 자본잠식(그 밖 상폐 사유) −5, 관리 · 정지 · 투자위험 −5,
    투자경고 −3 · 횡령 · 배임 혐의 −3, 투자주의 · 단기과열 · 자금조달 잦음 · 자금 거래(사채 풋 · 금전대여만으로 선 작전주 꼴) · 보고서 지연 · 투자주의 환기 −2,
    불성실공시 −1, 적자(OPM<0) −1. 최저 0. 출처: 공시위험(기준일 — 맞은 공시 제목 · 날짜 · DART 링크), KIS 종목 상태(스냅샷 날짜), 적자는 가속도 분기 재무."""
    rk = risk or {}
    pen, out = 0, []
    dsrc = ("공시위험 %s" % risk_date) if risk_date else "공시위험"
    ksrc = ("KIS 종목 상태 %s" % kis_date) if kis_date else "KIS 종목 상태"
    hits = rk.get("hits") or []

    def disc(t, rows=None):
        r = next((x for x in rows or () if x and len(x) >= 3), None)          # [날짜, 제목, 접수번호]
        return ev(t, "%s — %s %s" % (dsrc, r[1], r[0]), r[0], DART % r[2]) if r else ev(t, dsrc)

    def rows_of(cats):
        return next((h.get("rows") for h in hits if h.get("cat") in cats and h.get("rows")), None)
    light = rk.get("level") == "작전주 꼴" and bool(hits) and all(h.get("cat") in LIGHT_CATS for h in hits)
    if rk.get("level") in SEVERE_LEVEL and not light:
        pen += 5
        out.append(disc(rk["level"], rows_of({h.get("cat") for h in hits})))
    sev = [r for r in rk.get("ref") or () if r.get("cat") in SEVERE_REF]
    if sev:
        pen += 5
        out += [disc(SEVERE_REF[r["cat"]], r.get("rows")) for r in sev]
    for r in rk.get("ref") or ():
        if r.get("cat") in WARN_REF:
            pen += WARN_PEN.get(r["cat"], 0)
            out.append(disc(WARN_REF[r["cat"]], r.get("rows")))
    bad = [b for b in kis_bad or () if b in KIS_SEVERE]
    if bad:
        pen += 5
        out += [ev(b, ksrc, kis_date) for b in bad]
    tags = list(kis_tags or ())
    if "투자경고" in tags:
        pen += 3
        out.append(ev("투자경고", ksrc, kis_date))
    soft = [t for t in tags if t in ("투자주의", "단기과열")]
    fund = rk.get("level") == "자금조달 잦음" or len([h for h in hits if h.get("cat") in FUND_CATS and (h.get("days") or 0) >= 2]) > 0
    if soft or fund or light:
        pen += 2
        out += [ev(t, ksrc, kis_date) for t in soft]
        if fund:
            out.append(disc("자금조달 잦음", rows_of(FUND_CATS)))
        if light:
            out.append(disc("자금 거래", rows_of(LIGHT_CATS)))
    if opm is not None and opm < 0:
        pen += 1
        out.append(ev("적자", druck_src or "가속도 분기 재무"))
    seen, uniq = set(), []
    for x in out:
        if x["t"] not in seen:
            seen.add(x["t"])
            uniq.append(x)
    return max(0, 5 - pen), uniq


def risk_flags(risk, kis_bad=(), kis_tags=(), opm=None):
    """(점수, [꼬리표 이름]) — risk_items 의 이름만(심층 칸 flags · 옛 호출)."""
    s, items = risk_items(risk, kis_bad, kis_tags, opm)
    return s, [x["t"] for x in items]


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
            "yoy": r1(p.get("매출YoY")), "old": cur_v is not None and druck.get("v") != cur_v, "v": druck.get("v"), "asof": p.get("기준일")}


def upside_detail(rows, px, since):
    """증권사마다 최신 목표가(since 이후)의 평균 vs 지금 주가 → {up: 상승여력 %, n: 증권사 수, reps: 목표가 적힌 글 수, avg: 목표가 평균}
    (reports_view 와 같은 식, 주가만 단면에서). n 은 증권사 곳 수(증권사 미표기 글은 글마다 하나) — 리포트 건수가 아니다. 없으면 None."""
    latest, reps = {}, 0
    for r in rows or ():
        if (r.get("date") or "")[:10] < since or not r.get("tp"):
            continue
        reps += 1
        b = r.get("broker") or ("미표기 · %s %s" % ((r.get("date") or "")[5:10], (r.get("title") or "")[:14]))
        latest.setdefault(b, r["tp"])
    if not latest or not px:
        return None
    avg = sum(latest.values()) / len(latest)
    return {"up": round((avg / px - 1) * 100, 1), "n": len(latest), "reps": reps, "avg": int(round(avg))}


def upside(rows, px, since):
    """상승여력 % 만(upside_detail 의 up)."""
    d = upside_detail(rows, px, since)
    return d["up"] if d else None


def _eun(nm):
    """조사 '은/는'."""
    return "은" if _ga(nm) == "이" else "는"


def _yrs(a, b):
    """'2020'–'2022' → '2020–2022년', 같으면 '2020년'. 분기 칸('2026-06')은 해만. (처음 · 마지막만 알 때 — 사이 해가 다 있다는 뜻은 아니다. 해 목록이 있으면 yrs_of)"""
    a, b = (a or "")[:4], (b or "")[:4]
    return ("%s년" % a) if a == b or not b else "%s–%s년" % (a, b)


def yrs_of(ys):
    """캐시에 적힌 해 목록 → 글. 이어지면 '2014–2022년', 끊기면 그대로 '2021 · 2024년', 네 토막 넘게 끊기면 '2012–2022년 중 6개 해(2012 · 2015 · 2018 · 2020–2022)'
    — 처음–마지막만 적으면 캐시에 없는 해(코리아써키트 2022 · 2023)까지 적은 셈이 된다."""
    yy = sorted({int(str(y)[:4]) for y in ys or () if str(y)[:4].isdigit()})
    if not yy:
        return ""
    runs = []
    for y in yy:
        if runs and y == runs[-1][1] + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    txt = " · ".join(("%d–%d" % (a, b)) if a != b else str(a) for a, b in runs)
    if len(runs) <= 3:
        return txt + "년"
    return "%d–%d년 중 %d개 해(%s)" % (yy[0], yy[-1], len(yy), txt)


def _hist_yrs(d):
    """과거 공급망 근거의 해 — 해 목록(ys)이 있으면 그대로, 없으면 처음 · 마지막(y1 · y2)."""
    return yrs_of(d.get("ys")) if d.get("ys") else _yrs(d.get("y1"), d.get("y2"))


_LETTER_BATCHIM = set("LMNR")       # 영문 글자 이름이 받침으로 끝나는 것 — 엘 · 엠 · 엔 · 알
_DIGIT_BATCHIM = set("013678")      # 영 · 일 · 삼 · 육 · 칠 · 팔
# 제품 표 · 매입 줄에 흔한 영문 낱말의 우리말 소리 끝 받침 — True 을(디램 · 필름), False 를(플래시 · 웨이퍼). 표에 없는 낱말은 모른다('을(를)')
_ENG_BATCHIM = {"DRAM": True, "NAND": True, "FLASH": False, "FILM": True, "WAFER": False, "PASTE": False, "POWDER": False, "MODULE": True, "PANEL": True,
                "CELL": True, "BASE": False, "GLASS": False, "RESIN": True, "TAPE": False, "MASK": False, "FRAME": True, "CABLE": True, "SENSOR": False,
                "MOTOR": False, "CAMERA": False, "FOIL": True, "INK": False, "SUBSTRATE": False, "PACKAGE": False, "CHIP": True, "BOARD": False,
                "DISPLAY": False, "BATTERY": False, "STEEL": True, "COIL": True, "PLATE": False, "FIBER": False, "SHEET": False, "LENS": False}


def _batchim(w):
    """끝소리 받침 — 한글은 받침 글자, 영문 낱말은 표(_ENG_BATCHIM — 디램 · 플래시), 대문자 약어(MLCC · PCB · FC-BGA: 3자 이하거나 모음 글자 없음)는 끝 글자 이름(씨 · 비 · 에이),
    숫자는 읽는 소리(삼 · 육). 그 밖의 영문 낱말(Camera Module)은 소리를 모르니 None."""
    w = (w or "").rstrip()
    ch = w[-1:]
    if not ch:
        return None
    if "가" <= ch <= "힣":
        return bool((ord(ch) - 0xAC00) % 28)
    if ch.isdigit():
        return ch in _DIGIT_BATCHIM
    m = re.search(r"[A-Za-z]+$", w)
    if m and m.group().upper() in _ENG_BATCHIM:
        return _ENG_BATCHIM[m.group().upper()]
    if m and m.group().isupper() and (len(m.group()) <= 3 or not re.search(r"[AEIOU]", m.group())):
        return ch in _LETTER_BATCHIM
    return None


def _eul(w):
    """목적격 조사 — 받침 있으면 '을', 없으면 '를'(MLCC를 · HBM을), 소리를 모르면(영문 낱말) '을(를)'."""
    b = _batchim(w)
    return "을(를)" if b is None else ("을" if b else "를")


def _wa(w):
    """조사 '와/과' — 받침 있으면 '과'(나노엔텍과), 없으면 '와'(삼성전기와), 소리를 모르면 '와(과)'."""
    b = _batchim(w)
    return "와(과)" if b is None else ("과" if b else "와")


def _ro(n):
    """숫자 뒤 '로/으로' — 끝자리 소리가 영 · 삼 · 육이면 '으로', ㄹ받침(일 · 칠 · 팔)과 받침 없음은 '로'(백분위 3으로 · 87로)."""
    return "으로" if str(n)[-1:] in ("0", "3", "6") else "로"


def short_src(src):
    """설명 문장 안의 출처 — 회사 이름 · 「사업의 내용」을 떼고 '2026 반기보고서 원재료 매입처 표'만(문장의 주어가 이미 그 회사다). 연도가 없으면 그대로."""
    s = re.sub(r"\s*「사업의 내용」\s*", " ", src or "").strip()
    m = re.search(r"\d{4} (?:반기|[1-4]분기|사업)보고서", s)
    return s[m.start():].strip() if m else s


def buy_share(d, who):
    """매입 비중 구절 — 표 꼴대로 무엇의 몫인지. 매입처마다 한 줄인 표(per_sup — 영풍 BASE 줄 일곱)면 그 줄 비중은 그 매입처가 그 품목 매입에서 차지하는 몫
    → 'FPCB, PCB 부문 BASE 매입 중 삼성전기 31.5%'. 품목마다 한 줄인 표면 그 품목이 (부문) 매입에서 차지하는 몫 → '전자부품 매입 중 수동소자 10.4%'.
    부문이 있으면 늘 적는다(두 부문 표의 10.4% 는 전자부품 매입의 몫이지 솔루엠 전체 매입의 몫이 아니다)."""
    seg = ((d.get("seg") or "").strip() + " ") if d.get("seg") else ""
    it, pct = (d.get("item") or "그 품목"), d.get("pct")
    if d.get("per_sup"):
        return "%s%s 매입 중 %s %.1f%%" % (seg, it, who, pct)
    return "%s매입 중 %s %.1f%%" % (seg, it, pct)


def sell_share(d, lead):
    """매출 비중 구절 — 주도주가 그 회사 매출에서 차지하는 몫 '삼성전자가 매출의 96.0%'. 부문별 매출처 표(basis 부문)면 그 부문 매출의 몫 'IT부문 매출 중 삼성전자 96.0%'."""
    seg = (d.get("seg") or "").strip()
    if d.get("basis") == "부문" and seg:
        return "%s 매출 중 %s %.1f%%" % (seg, lead, d.get("pct"))
    return "%s%s 매출의 %.1f%%" % (lead, _ga(lead), d.get("pct"))


def _sup_phrase(w, lead, subj=""):
    """공급망 근거 dict → 설명 문장 구절(동사 꼴). d(세부 — name · item · seg · pct · as · y1 · y2 · cust · sub …)로 짓고, 모르는 꼴이면 근거 문구 그대로.
    출처는 괄호 안에 짧게(short_src — 문장 주어가 그 회사니 이름을 되풀이하지 않는다) — 숫자 · 보고서 이름은 모두 서버가 캐시에서 읽어 넣은 것.
    subj = 문장 주어(후보 이름) — 근거의 회사가 주어와 같으면('코스모신소재는 코스모신소재가 …') 이름을 뺀다."""
    if not isinstance(w, dict):
        return str(w)
    d, k = w.get("d") or {}, w.get("k") or ""
    src = short_src(w.get("src"))
    nm, item = d.get("name") or "", d.get("item") or ""
    who = "" if nm == subj or not nm else "%s%s " % (nm, _ga(nm))
    tail = lambda *xs: ("(%s)" % " · ".join(x for x in (src,) + xs if x)) if (src or any(xs)) else ""     # noqa: E731
    pct = d.get("pct") if isinstance(d.get("pct"), (int, float)) else None
    L = lead + _eul(lead)                                  # '삼성전기를' · '현대제철을'
    seg = (d.get("seg") or "").strip()
    ht = d.get("tail") or "지금은 빠짐"                     # 과거 줄 꼬리 — 서버가 그 회사의 더 새 표를 보고 정한 말('지금은 빠짐' · '최신 2026 반기보고서엔 매출처 표 없음')
    if k == "buyer":
        via = "연결 자회사(%s) 매입으로 " % d["sub"] if d.get("sub") else ""
        return "%s%s%s %s매입처로 적었다%s" % (who, via, L, (item + " ") if item else "", tail(buy_share(d, lead) if pct is not None else ""))
    if k == "line":
        return "%s의 %s 매입처에 %s%s 함께 적혔다%s" % (nm, item or "같은 줄", lead, _wa(lead), tail())
    if k == "seller":                                      # 비중은 주도주가 그 회사 매출에서 차지하는 몫(부문 표면 그 부문 매출의 몫). 품목은 주도주 원재료 표의 것이라 여기 안 적는다(mine 줄)
        return "%s%s 매출처로 적었다%s" % (who, L, tail(sell_share(d, lead) if pct is not None else ""))
    if k == "mine":
        return "%s의 %s 매입처다%s" % (lead, item or "원재료", tail(buy_share(d, d.get("as") or "그 매입처") if pct is not None else "",
                                                                 "보고서 표기 '%s'" % d["as"] if d.get("as") else ""))
    if k == "cust":                                        # 비중 없이 이름만 적힌 매출처(HLB생명과학 'SD BIOSENSOR')는 '매출 비중 미기재'
        return "%s의 매출처다%s" % (lead, tail(("%s %s 매출의 %.1f%%" % (lead, seg, pct) if d.get("basis") == "부문" and seg else "%s 매출의 %.1f%%" % (lead, pct)) if pct is not None else "매출 비중 미기재"))
    if k == "hist_sup":
        return "%s %s의 %s 매입처였다(%s%s)" % (_hist_yrs(d), lead, item or "원재료", ht, (" · " + src) if src else "")
    if k == "hist_cust":
        return "%s %s의 매출처였다(%s%s%s)" % (_hist_yrs(d), lead, ht, " · 마지막 해 %.1f%%" % pct if pct is not None else "", (" · " + src) if src else "")
    if k == "hist_buyer":
        return "%s %s %s매입처로 적었다(%s%s)" % (_hist_yrs(d), L, (item + " ") if item else "", ht, (" · " + src) if src else "")
    if k == "hist_seller":
        return "%s %s 매출처로 적었다(%s%s)" % (_hist_yrs(d), L, ht, (" · " + src) if src else "")
    if k == "same":                                        # 같은 고객 + 테마 · 제품 — 꼬리표를 서술어 뒤에 매달지 않고 한 구절로
        tag = d.get("tag") or ""
        also = ("네이버 테마 '%s'에도 같이 들었다" % tag[:-3]) if tag.endswith(" 테마") else ("같은 제품(%s)도 만든다" % tag[:-3]) if tag.endswith(" 동종") else ""
        return "%s%s 같은 고객 %s에 %s(매출 %s, %s도 %s%s)%s" % (lead, _wa(lead), d.get("cust"), "팔고" if also else "판다", pct_s(d.get("pct")), lead, pct_s(d.get("lead_pct")),
                                                           (" · " + src) if src else "", (" " + also) if also else "")
    return w.get("w") or ""


def score(c, *, lead_p3=None, px=None, ph=None, n_rep=0, up=None, risk=None, kis_bad=(), kis_tags=(), lead_name="", name="", srcs=None):
    """후보 한 곳 → {parts, ev, group, group_note, stars, why, flags, expl}. 칸마다 근거 객체(ev — {t, src, date, url, go})를 남긴다.
    25점 = 연결 · 실적 · 주목 · 덜 오름 · 건전성 × 5. srcs = 서버가 모은 출처 {theme, xs, xs_date, kis_date, risk_date, prod:(src, date, url)}.
    up 은 upside_detail 꼴 {up, n, avg} 또는 숫자. 모든 숫자는 캐시 값(근거에 적힌 출처)에서만 — 없으면 '없음'이라 적는다."""
    S = srcs or {}
    E = {"link": [], "fund": [], "attn": [], "lag": [], "safe": []}
    phr = []                                     # 설명 문장용 연결 근거 구절(센 것부터)
    link = link_score(c)
    sups = [w for w in c["supply"] if not _weak(w)][:3]
    for w in sups:                               # 공급망 직접(5)
        E["link"].append(ev(w["w"] if isinstance(w, dict) else w, *(_src3(w))))
        phr.append(_sup_phrase(w, lead_name, name))
    ps_, pd_, pu_ = S.get("prod") or (None, None, None)
    for p in c["prod"][:2]:                      # 같은 제품(4) — 비중은 표에 적힌 값만 '매출 비중', 금액으로 나눈 것(products_of est)은 '금액 비율 추정'
        kw, item, pct, est = p[0], p[1], p[2] if len(p) > 2 else None, bool(p[3]) if len(p) > 3 else False
        it = item if len(item) <= 30 else item[:29].rstrip(" ,") + "…"      # 자른 자리는 말줄임으로
        pt = ((" (금액 비율 추정 %s)" if est else " (매출 비중 %s)") % pct0(pct)) if isinstance(pct, (int, float)) else ""
        E["link"].append(ev("같은 제품 '%s'%s" % (it, pt), ps_, pd_, pu_))
        phr.append("%s%s 같은 %s%s 만든다(%s'%s'%s)" % (lead_name, _wa(lead_name), kw, _eul(kw), (short_src(ps_) + " ") if ps_ else "", it,
                                                    ((" 금액 비율 추정 %s" if est else " %s") % pct0(pct)) if isinstance(pct, (int, float)) else ""))
    for w in [w for w in c["supply"] if _weak(w)][:3]:        # 약한 공급망(3) — 연결 자회사 매입 · 과거 공급망 · 같은 고객
        E["link"].append(ev(w["w"], *(_src3(w))))
        phr.append(_sup_phrase(w, lead_name, name))
    if c["rep_n"]:                               # 리포트 동시 언급(3 · 2)
        kw = c["rep_by"].most_common(1)[0][0]
        refs = c.get("rep_refs") or []
        r0 = refs[0] if refs else {}
        more = {"src": "%s %s" % (refs[1].get("by") or "증권사 미표기", refs[1].get("date") or ""), "date": d8(refs[1].get("date")), "url": refs[1].get("url")} if len(refs) > 1 else None
        E["link"].append(ev("%s 리포트 %d건(180일)%s" % (kw, c["rep_n"], " — 최신 '%s'" % r0["title"] if r0.get("title") else ""),
                            ("%s %s" % (r0.get("by") or "증권사 미표기", r0.get("date") or "")) if r0 else "리포트 탭 — 180일 키워드 동시 언급",
                            r0.get("date"), r0.get("url"), {"tab": "rep"}, more=more))
        phr.append("최근 180일 %s 리포트 %d건에 함께 언급됐다%s" % (kw, c["rep_n"], "(최신 %s %s)" % (r0.get("by") or "증권사 미표기", r0.get("date") or "") if r0 else ""))
    if c["themes"]:                              # 테마(1) — 둘까지 한 줄에(출처가 같다)
        E["link"].append(ev("네이버 테마 %s 같이 소속" % " · ".join("'%s'" % t for t in c["themes"][:2]), S.get("theme") or "네이버 금융 테마 분류"))
    # 실적
    opm = ph.get("opm") if ph else None
    dsrc = ("가속도 탭 · DART 분기 재무 (druck v%s%s)" % (ph.get("v"), " · 옛 판" if ph.get("old") else "")) if ph else None
    go_d = {"tab": "druck"}
    if not ph:
        fund = 2
        E["fund"].append(ev("가속도 자료 없음", "분기 재무 캐시 없음(.cache/druck)"))
    elif opm is not None and opm < 0:
        fund = 0
        E["fund"].append(ev("적자 · OPM %.1f%% (%s)" % (opm, ph.get("label")), dsrc, ph.get("asof"), None, go_d))
    else:
        fund = PHASE_PTS.get(ph["phase"], 2)
        E["fund"].append(ev("%s%s%s (%s)" % (ph["phase"], " · 가속B %+.1f" % ph["B"] if ph.get("B") is not None else "",
                                               " · OPM %.1f%%" % opm if opm is not None else "", ph.get("label")), dsrc, ph.get("asof"), None, go_d))
    # 주목
    attn = 0 if not c["rep_n"] else 2 if c["rep_n"] <= 2 else 3 if c["rep_n"] <= 9 else 4
    if c["rep_n"]:
        r0 = (c.get("rep_refs") or [{}])[0]
        E["attn"].append(ev("%s 리포트 %d건(180일)" % (c["rep_by"].most_common(1)[0][0], c["rep_n"]),
                            ("최신 %s %s" % (r0.get("by") or "증권사 미표기", r0.get("date") or "")) if r0 else "리포트 탭", r0.get("date"), r0.get("url"), {"tab": "rep"}))
    else:
        E["attn"].append(ev("키워드 리포트 없음(180일)" + (" · 전체 %d건" % n_rep if n_rep else ""),
                            "리포트 탭 — 텔레그램 증권사 채널(180일)" if n_rep else "180일 리포트 캐시에 이 회사 글 없음", None, None, {"tab": "rep"} if n_rep else None))
    ud = up if isinstance(up, dict) else ({"up": up} if up is not None else None)
    if ud and ud.get("up") is not None:
        E["attn"].append(ev("리포트 목표가 평균%s → %+.0f%%" % (" {:,}원".format(ud["avg"]) if ud.get("avg") else "", ud["up"]),
                            "%s180일 증권사별 최신 목표가 평균" % ((("리포트 %d건 · " % ud["reps"]) if ud.get("reps") else "") + ("증권사 %d곳 " % ud["n"] if ud.get("n") else "")),
                            None, None, {"tab": "rep"}))         # n 은 증권사 곳 수 — '리포트 n건'이라 적으면 글 수(LG이노텍 30건 · 19곳)와 어긋난다
        if ud["up"] >= 30:
            attn = min(5, attn + 1)
    # 덜 오름
    p3, dd = (px or {}).get("p3"), (px or {}).get("dd")
    xsrc, xdate = S.get("xs") or "전 종목 주가 단면", S.get("xs_date")
    if p3 is None or lead_p3 is None:            # 단면 출처 줄(xsrc)에 날짜가 있어 date 는 따로 안 붙인다(판 크기)
        lag = 2
        E["lag"].append(ev("3개월 백분위 자료 없음" + (" · 52주 고점 대비 %.1f%%" % dd if dd is not None else ""), xsrc))
    else:
        d = lead_p3 - p3
        lag = 5 if d >= 30 else 4 if d >= 15 else 3 if d >= 0 else 1
        E["lag"].append(ev("3개월 수익률 백분위 %d (주도주 %d)" % (p3, lead_p3) + (" · 52주 고점 대비 %.1f%%" % dd if dd is not None else ""), xsrc))
    if dd is not None and dd < -50:
        lag = max(0, lag - 1)
        E["lag"].append(ev("52주 고점 대비 %.0f%% — 망가짐" % dd, xsrc))
    # 건전성
    safe, items = risk_items(risk, kis_bad, kis_tags, opm, S.get("kis_date"), S.get("risk_date"), dsrc)
    flags = [x["t"] for x in items]
    E["safe"] = items[:] or [ev("위험 꼬리표 없음", _none_src(S))]
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
    return {"score": tot, "parts": parts, "ev": E, "group": grp, "group_note": GROUP_NOTE[grp], "stars": max(1, link), "flags": flags,
            "why": why_line(c, ph, fund, grp, flags),
            "expl": explain(name or "이 회사", lead_name or "주도주", c, phr, ph, px, lead_p3, n_rep, ud, items, S)}


def _src3(w):
    return (w.get("src"), w.get("date"), w.get("url")) if isinstance(w, dict) else (None, None, None)


def _none_src(S):
    """위험 꼬리표가 없을 때의 출처 — 두 기준일이 같으면 한 번만('공시위험 · KIS 종목 상태 20261013')."""
    rd, kd = S.get("risk_date"), S.get("kis_date")
    if rd and rd == kd:
        return "공시위험 · KIS 종목 상태 %s" % rd
    bits = [("공시위험 %s" % rd) if rd else None, ("KIS 종목 상태 %s" % kd) if kd else None]
    return " · ".join(b for b in bits if b) or "공시위험 · KIS 종목 상태 캐시"


def explain(name, lead, c, phr, ph, px, lead_p3, n_rep, ud, safe_items, S):
    """설명 문단(규칙 조립, LLM 없음) — {이름}은(는) {연결 근거}. {실적 · 주목}. {주가 위치 · 위험}. 연결 근거가 둘이면 '또 …' 한 문장 더.
    없는 건 없다고 쓴다(…근거는 찾지 못했다 · 자료는 없다). 숫자는 모두 근거 객체와 같은 캐시 값."""
    s = []
    if phr:
        s.append("%s%s %s." % (name, _eun(name), phr[0]))
        if len(phr) > 1:
            s.append("또 %s." % phr[1])
    elif c["themes"]:
        s.append("%s%s 네이버 테마 '%s' 소속 외에 보고서 · 리포트에서 %s%s의 직접 연결 근거는 찾지 못했다." % (name, _eun(name), re.sub(r"\(.*$", "", c["themes"][0]).strip(), lead, _wa(lead)))
    else:
        s.append("%s%s 보고서 · 리포트 · 테마 어디서도 %s%s의 연결 근거를 찾지 못했다." % (name, _eun(name), lead, _wa(lead)))
    # 둘째 — 실적 · 주목. 연결 문장에서 이미 말한 리포트 건수('…리포트 2건에 함께 언급됐다')는 되풀이하지 않는다
    opm = ph.get("opm") if ph else None
    if not ph:
        f, fe = "가속도 자료는 없고(분기 재무 캐시 없음)", "가속도 자료는 없다(분기 재무 캐시 없음)"
    else:
        core = ("실적은 적자(%s · OPM %.1f%%)" % (ph.get("label"), opm)) if opm is not None and opm < 0 else \
            "실적 국면은 %s(%s%s%s)" % (ph["phase"], ph.get("label"), " · 가속B %+.1f" % ph["B"] if ph.get("B") is not None else "", " · OPM %.1f%%" % opm if opm is not None else "")
        f, fe = core + "이고", core + "이다"
    upc = ""
    if ud and ud.get("up") is not None:
        upc = ("리포트 목표가 평균 {:,}원 기준 ".format(ud["avg"]) if ud.get("avg") else "리포트 목표가 평균 기준 ") + "상승여력은 %+.0f%%다" % ud["up"]
    said = any("함께 언급됐다" in p for p in phr[:2])
    glnote = ("180일 글 %d건 중" % n_rep) if n_rep else "180일 글 없음"
    if c["rep_n"] and not said:
        a = "최근 180일 %s 리포트 %d건이 있" % (c["rep_by"].most_common(1)[0][0], c["rep_n"]) + (("으며, " + upc) if upc else "다")
    elif c["rep_n"]:
        a = upc
    else:
        a = "키워드 리포트는 없" + (("으며(%s) " % glnote + upc) if upc else "다(%s)" % glnote)
    s.append(("%s %s." % (f, a)) if a else fe + ".")
    # 셋째 — 주가 위치 · 위험
    p3, dd = (px or {}).get("p3"), (px or {}).get("dd")
    if p3 is not None and lead_p3 is not None:
        cmp_ = "앞섰고" if p3 > lead_p3 else "뒤졌고" if p3 < lead_p3 else "같고"
        g = "주가는 3개월 수익률 백분위 %d%s 주도주(%d)보다 %s" % (p3, _ro(p3), lead_p3, cmp_)
    else:
        g = "주가는 3개월 백분위 자료가 없고"
    g += (" 52주 고점 대비 %.1f%%이며" % dd) if dd is not None else " 52주 고점 자료도 없으며"
    if safe_items:                               # 출처는 짧게(공시 날짜 · KIS 날짜 · 분기) — 긴 공시 제목 · 링크는 ev.safe 에
        def where(x):
            src = x.get("src") or ""
            if src.startswith("KIS"):
                return ("KIS %s" % x.get("date", "")).strip()
            if src.startswith("가속도"):           # 적자 — 가속도 분기 재무(druck 판 이름은 ev.safe 에)
                return "분기 재무%s" % ((" " + ph["label"]) if ph and ph.get("label") else "")
            return ("공시 %s" % x["date"]) if x.get("date") else src
        r = "위험 꼬리표는 " + " · ".join("%s(%s)" % (x["t"], where(x)) for x in safe_items) + "다"
    else:
        r = "위험 꼬리표는 없다(%s)" % _none_src(S).replace("KIS 종목 상태", "KIS")
    s.append("%s, %s." % (g, r))
    return " ".join(s)


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
    """조사 '이/가' — 끝소리 받침(_batchim: 한글 · 대문자 약어 · 숫자), 모르면 '가'."""
    return "이" if _batchim(nm) else "가"


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
            # 품목은 적지 않는다 — 그 회사 매출처 표가 아니라 주도주 원재료 표(그 묶음 줄)에 적힌 것이라 출처가 다르다
            why = "%s%s %s%s 매출처로 적음" % (s["name"], _ga(s["name"]), lead_name, _eul(lead_name))
            (home or out[0])["listed"].append(dict({"name": s["name"], "code": s["code"], "why": why}, **{k: s[k] for k in ("src", "date", "url") if s.get(k)}))
    return out


NOT_CO = re.compile(r"스왑|선도|옵션|파생|통화|이자율|주식$|자산$|소계|수익$|거래처$|^[A-Z]\s*거래처")   # 매출처 칸에 든 회사 아닌 줄(이자율스왑 · 카드론수익 · A 거래처)


def down_nodes(customers, buyers, orders, link=None, period="", max_cust=5, max_buy=5, max_ord=3, lead_name=""):
    """하류 — 매출처(비중) · 나를 매입처로 적은 회사(그 줄의 비중 — 표 꼴대로 무엇의 몫인지, buy_share) · 계약 상대(건수 · 합계).
    회사가 아닌 매출처 줄(NOT_CO)은 빼고, 같은 회사(코드)가 둘이면 한 노드로('매출처 26.0% · DX 부문 매입 중 Camera Module 7.9%').
    매입처 줄은 서버가 첫 줄(items[0])의 seg · pct · per_sup 를 붙여 보낸다 — 줄마다 다른 비중 중 큰 것을 고르지 않는다(영풍 BASE 31.5 와 BGA PCB 68.8 은 다른 줄).
    줄에 src · date · url 이 붙어 있으면(서버가 어느 보고서 · DART 링크를 적은 것) 노드에 그대로 옮긴다(심층 칸 근거 출처)."""
    srcs = lambda h: {k: h[k] for k in ("src", "date", "url") if h.get(k)}       # noqa: E731
    out = []
    for h in [h for h in customers or () if h.get("name") and not h.get("self") and not NOT_CO.search(re.sub(r"\s+", " ", h.get("name") or "").strip())][:max_cust]:
        cd = (h.get("link") or {}).get("code") or (link(h["name"]) if link else None)
        seg = (h.get("seg") or "").strip() if h.get("basis") == "부문" else ""
        pc = ("%.1f%%" % h["pct"]) if isinstance(h.get("pct"), (int, float)) and h["pct"] else "(비중 미기재)"       # 이름만 적힌 매출처도 그 표의 고객(HLB생명과학 'SD BIOSENSOR')
        out.append(dict({"kind": "customer", "name": h["name"], "code": cd, "pct": h.get("pct"),
                         "why": "%s매출처 %s" % ((seg + " ") if seg else "", pc) + (" (%s)" % period if period else "")}, **srcs(h)))
    by = {}
    for b in buyers or ():
        x = by.get(b["code"])
        if x is None:
            x = by[b["code"]] = dict({"kind": "buyer", "name": b["name"], "code": b["code"], "pct": b.get("pct"), "items": [],
                                      "seg": b.get("seg"), "per_sup": bool(b.get("per_sup"))}, **srcs(b))
        for it in b.get("items") or ():
            if it not in x["items"]:
                x["items"].append(it)
    for x in sorted(by.values(), key=lambda x: -(x["pct"] or 0))[:max_buy]:
        it0 = x["items"][0] if x["items"] else ""
        if x["pct"] is not None:
            w = buy_share({"item": it0, "seg": x["seg"], "pct": x["pct"], "per_sup": x["per_sup"]}, lead_name or "이 회사")
        else:
            w = "%s매입 중 %s(비중 미기재)" % (((x["seg"] or "") + " ") if x.get("seg") else "", (it0 + " ") if it0 else "")
        x["why"] = "%s %s%s" % (x["name"], w, (" · %s 줄에도" % x["items"][1]) if len(x["items"]) > 1 else "")
        out.append({k: x[k] for k in ("kind", "name", "code", "pct", "why", "src", "date", "url") if k in x})
    for o in (orders or ())[:max_ord]:
        cd = (o.get("link") or {}).get("code")
        out.append(dict({"kind": "contract", "name": o["party"], "code": cd, "n": o["n"], "amount": o.get("amount"),
                         "why": "공급계약 %d건 · %s" % (o["n"], won(o.get("amount")) if o.get("amount") else "금액 미확인")}, **srcs(o)))
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
    """지도 payload 에서 한 노드(code)에 걸린 근거 줄 — 심층 칸(/api/vcmap/node)이 쓴다. 매트릭스 ev 와 같은 객체 꼴 {t, src, date, url, go}.
    출처: 최대주주 · 상장 지분은 소유 캐시의 보고서(DART 접수번호), 원재료 · 매출처는 밸류체인 최신 칸(src.vc.rcept), 나를 적은 회사 줄은 서버가 붙인 src · url."""
    if not d or not code:
        return []
    out = []
    net = d.get("net") or {}
    ow = net.get("owner") or {}
    src = d.get("src") or {}
    me = d.get("name") or ""
    vcp = (src.get("vc") or {}).get("period") or ""                          # '2026 반기' — 어느 보고서 · 어느 표
    vrc = (src.get("vc") or {}).get("rcept")
    vsrc = "%s %s" % (me, report_name(vcp)) if vcp else "%s 보고서" % me               # 서버 공급망 근거(원재료 표 · 매출처 표)와 같은 출처 글 — 겹침 거르기
    mcp = (src.get("vc") or {}).get("mat_period") or vcp                     # 원재료 표를 쓴 칸 — 최신 칸에 표가 없으면(부분 반기) 그 앞 칸
    mrc = (src.get("vc") or {}).get("mat_rcept") or vrc
    msrc = "%s %s" % (me, report_name(mcp)) if mcp else vsrc
    osrc = ((src.get("own") or {}).get("src") or "").split(" · ")[0]          # '2026-06 반기보고서'
    orc = (src.get("own") or {}).get("rcept")
    if ow.get("code") == code:                  # 관계 칸('최대주주 본인' · '本人')은 그쪽 회사 기준 말이라 적지 않는다
        rc = ow.get("rcept")
        out.append(ev("%s 최대주주%s" % (me, " %.2f%%" % ow["pct"] if ow.get("pct") is not None else ""), ow.get("src") or None, rc, DART % rc if rc else None))
    for h in net.get("holdings") or ():
        if h.get("code") == code:
            out.append(ev("%s 보유 %.2f%%%s" % (me, h["pct"], " · " + h["purpose"] if h.get("purpose") else ""),
                          ("%s · 타법인출자 현황(상세)" % osrc) if osrc else None, orc, DART % orc if orc else None))
    for g in net.get("up") or ():
        for it in g.get("items") or ():
            for sp in it.get("sup") or ():
                if sp.get("code") == code:           # 비중은 품목 몫(매입처 몫이 아니다) — 적힌 이름이 상장 이름과 다르면 그대로 붙인다
                    out.append(ev("%s원재료 %s 매입처%s%s" % (g["seg"] + " " if g.get("seg") else "", it["item"],
                                                          " · 매입 비중 %.1f%%" % it["pct"] if it.get("pct") is not None else "",
                                                          " · 보고서 표기 '%s'" % sp["name"] if sp.get("co") else ""),
                                  msrc + " 원재료 표", mrc, DART % mrc if mrc else None))
        for x in g.get("listed") or ():
            if x.get("code") == code:
                out.append(ev(x["why"], x.get("src"), x.get("date"), x.get("url")))
    for x in net.get("down") or ():
        if x.get("code") == code:
            out.append(ev(x["why"], x.get("src") or (vsrc + " 매출처 표" if x.get("kind") == "customer" else None), x.get("date") or (vrc if x.get("kind") == "customer" else None),
                          x.get("url") or (DART % vrc if x.get("kind") == "customer" and vrc else None)))
    for r in d.get("matrix") or ():
        if r.get("code") == code:
            out.append(ev("후속주 %s군 %d점 — %s" % (r["group"], r["score"], r.get("why") or ""), NOTE))
            # 매트릭스 연결 근거 — 그림 줄과 같은 보고서 · 같은 링크(원재료 표의 매입처 = '삼성전기 FILM 매입처')면 겹쳐 적지 않는다
            had = {(x.get("src"), x.get("url")) for x in out if x.get("url")}
            out += [w for w in ((w if isinstance(w, dict) else ev(w)) for w in (r.get("ev") or {}).get("link") or ())
                    if not (w.get("url") and (w.get("src"), w.get("url")) in had)]
    seen, uniq = set(), []
    for x in out:
        if x["t"] not in seen:
            seen.add(x["t"])
            uniq.append(x)
    return uniq


# ---------------------------------------------------------------- 9. payload
def payload(*, code, name, built, leader, story, triggers, net, matrix, src):
    """서버 ↔ 화면 계약(설계 '응답 꼴'). pending · stale 은 서버가 응답 때 붙인다."""
    return {"v": V, "code": code, "name": name, "built": built,
            "head": {"leader": leader, "story": story, "triggers": triggers, "counts": counts(matrix)},
            "net": net, "matrix": matrix, "src": src, "note": NOTE}
