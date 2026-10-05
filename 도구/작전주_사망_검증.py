# -*- coding: utf-8 -*-
"""
작전주 사망 검증 — '그 시점' 표본으로 잰 공시 신호의 사망(비자발 상장폐지) 예측력 (2026-10-05)

질문
  기준일(해마다 4월 30일, 사업보고서 마감 뒤)까지 나온 공시 제목만 보고, 기준일 뒤 24개월(·12개월) 안의 사망을 미리 알 수
  있었나. 표본은 '그날 상장 중이던 회사' 전부다(지금 상장폐지된 회사 포함). 예전 백테스트 표본(종목.txt = 2026-10-01 시총 상위
  1000)은 결과로 고른 표본이라 사망 회사가 들어갈 수 없다 — 그 차이를 숫자로 잰다.

자료(DART API 호출 0, 이미 받은 파일만)
  .cache/공시목록/{I,B,A001}_YYYYQn.jsonl (2013Q1~2026Q3) — 도구/공시분류.py 의 load_rows · classify · halt_reason · judge_all ·
  _tag · _chain 을 그대로 쓴다(사망 정의 · 범주 정의는 그 모듈 것). 기존 파일은 고치지 않는다.

산출
  .cache/공시목록/사망_검증.json   전체 숫자(표본 · 범주표 · 해마다 · 규칙 · 표본 밖 · 예전 표본 비교 · 사망 목록)
  .cache/공시목록/사망_검증.md     요약
재현
  python "G:/내 드라이브/Claude/주식/기업추적/도구/작전주_사망_검증.py"      (약 2~4분. 재표본 seed 20261005 고정 → 매번 같은 숫자)

설계(과제 설계에서 바꾼 곳은 [바꿈] 으로 표시)
  기준일 D = YYYY-04-30, 2015~2024(24개월 결과) + 2025(12개월 결과만: D+24개월이 자료끝 2026-10-02 를 넘는다).
  그날 상장 중 = 종목코드가 있고
      ① D 전에 거래소공시(접수번호 9번째 자리 8/9/6 = 유가 · 코스닥 · 코넥스)가 있었고                       [바꿈: 아직 상장 전인 회사 빼기]
         — corp_name · stock_code 는 '지금' 값이라 상장 전 공시 목록에도 종목코드가 붙어 있다.
      ② 마지막 거래소공시(공시분류 '상장종료')가 D 이후이거나 지금 상장 중                               [바꿈: 합병 · 자진상폐로 이미 끝난 회사 빼기]
      ③ D 전 13개월 안(D-13개월 < 접수일 ≤ D)에 사업보고서(A001, 정정 포함)를 냈고                       (과제 설계)
      ④ 사망일(또는 상폐절차 시작일) ≤ D 가 아니고                                                      (과제 설계)
      ⑤ D 시점에 이미 상폐 절차 중이 아닌 회사: D 까지의 공시만으로 공시분류의 '상폐절차중' 규칙(3년 안 사슬에 거래소의
         상장폐지 사유 · 결정 · 정리매매 · 가처분 · 파산선고가 해소 없이 남음)을 돌려 걸리면 뺀다.                [바꿈: ④는 나중에
         살아난 회사를 못 거른다(오늘이엔엠 2018) — 그 시점에 이미 '죽는 중' 인 회사는 결과가 어떻든 뺀다]
  성격이 다른 곳은 본표본에서 빼고 따로 센다(이름은 '지금' 이름뿐이라 이름 + 공시로 가림):
      스팩     지금 이름이 스팩 · 기업인수목적 · SPAC, 또는 'X_스팩' 공시(기업인수목적회사의 …)가 D 이후에도 있는 회사
               (스팩 존속합병으로 이름이 바뀐 127곳은 마지막 X_스팩 공시 = 합병 완료 전까지만 스팩으로 본다)
      리츠펀드 이름에 선박투자 · 부동산투자회사 · 리츠 · 투자회사 · 해외자원개발 · 특별자산 · 맥쿼리인프라 · 발해인프라 · 인프라투융자
               (자기관리 리츠도 뺀다 — 스크리너 대상인 영업회사가 아니다)
      외국     종목코드가 9 로 시작(900xxx · 950xxx = 외국 기업 원주 · DR. 36곳 — 중국 기업 사망이 많아 따로 본다)
      코넥스   D 직전 거래소공시 5건의 시장(접수번호 9번째 자리) 다수결이 코넥스
  시장(유가 · 코스닥)은 거래소공시 접수번호 9번째 자리로 정한다. 거래소가 낸 공시의 제출자(flr_nm: 유가증권시장본부 · 코스닥시장본부 ·
  코넥스시장)와 33,572건 모두 일치했고(공시분류 점검), 회사가 낸 거래소공시에도 붙어 있어 제출자보다 촘촘하다. 표본 단위로 flr_nm 다수결과
  맞춰 본 일치율도 결과에 남긴다.

  신호 = D-24개월 < 접수일 ≤ D (또는 D-12개월) 안의 범주별 공시. 정정 · 첨부 머리말이 붙은 재제출은 빼고, 같은 범주는 같은 날 여러 건이어도
         1 로 센다(B 주요사항보고서와 I 거래소공시에 같은 사건이 겹쳐 나오는 것을 막는다) → '건수' = 그 범주가 나온 서로 다른 날 수.
         범주 = 공시분류 CATEGORIES 전부 + 매매거래정지의 사유 묶음('정지:상장폐지사유' · '정지:감사의견·보고서' …).
         D 뒤 공시는 쓰지 않는다(접수일 ≤ D 만).
  결과 = 사망 사건일 E 가 D < E ≤ D+24개월(·12개월).
         E = 공시분류의 사망일(사망 · 사망(약) · 사망(추정) — 마지막 사망 사슬의 첫 결정적 사건) 또는 상폐절차중(지금 상장이지만 상폐 결정 ·
         정리매매 보류 · 개선기간)의 절차 시작일.                                                          [바꿈: 상폐절차중을 사건에 넣는다 —
         빼면 2023 · 2024 기준일의 사망이 덜 잡힌다(상폐절차중 80곳 중 78곳이 2025~26 시작). 엄격판(사망만, 약 · 추정 · 절차중은 표본에서 뺌)을
         민감도로 따로 낸다]
  보고 = 기본 사망률 · 범주별 사망률 · lift(=걸린 쪽 사망률 / 전체 사망률) · RR(걸린 쪽 / 안 걸린 쪽) · 회사 단위 재표본(1,000번) 90% 구간 ·
         해마다 lift · 점수(고른 범주 몇 개가 걸렸나 0 · 1 · 2 · 3+)별 사망률 · 규칙의 정밀도 · 재현율 · 버리는 비율.
  앞 · 뒤 검증 = 2015~2018 기준일로 범주를 고르고(걸린 사망 ≥5 · lift ≥2 · 재표본 lift 5% 하한 >1) 점수 문턱을 정해(학습기간에서 버리는
         비율이 5% · 10% · 20% 를 넘지 않는 가장 낮은 문턱) 2019~2024(12개월판은 2019~2025)에 그대로 적용한다.
         두 묶음: A '전체 위험'(부실 · 거래소 조치 · 매매정지 사유 · 과거 사망 표지까지) / B '작전주 꼴'(돈 · 지배구조 공시만:
         CB · BW · 증자 · 감자 · 최대주주변경 · 대표이사변경 · 타법인취득 · 금전대여 … — 부실 표지가 나오기 전에 거를 수 있나).
         [더함] 짧은 규칙 C: 학습기간에서 (범주, 날수≥1·2·3) 조건을 OR 로 하나씩 더한다(새로 걸리는 관측의 사망 비율이 가장 높은 것,
         새 사망 ≥3, 학습 버림 10% 전까지, 최대 8개) — 사람이 읽을 수 있는 규칙. 점수 규칙과 같은 표본 밖에 그대로 적용.
         [더함] 24개월판의 학습 결과창(~2020-04-30)이 2019 기준일과 겹치므로 2020~2024 만의 표본 밖 성적도 따로 낸다.

결과(2026-10-05 실행): 본표본 24개월 사망률 1.66%(관측 20,362 · 사망 338 · 회사 2,595). 표본 밖(2019~2024) 짧은 규칙 C_B
  (BW≥3 · 제3자배정≥3 · 최대주주변경≥3 · 경영권양수도≥2 · 유상증자≥3 · 금전대여≥3 · 사채조기상환≥3 · CB≥3 날, OR):
  버림 9.2% · 사망 64% 피함 · 걸린 것 중 12.6% 사망 · 남은 쪽 사망률 0.71%(기본 1.81%). 예전 표본(종목.txt)에는 이 기간 사망 204곳 중
  5곳(모두 상폐절차중)만 있고 그 안의 사망률은 0.12%(밖 2.55%).
"""
import bisect
import calendar
import collections
import datetime as dt
import json
import math
import operator
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import 공시분류 as K  # noqa: E402

OUT_JSON = os.path.join(K.DIR, "사망_검증.json")
OUT_MD = os.path.join(K.DIR, "사망_검증.md")
OLD_LIST = os.path.join(K.BASE, "종목.txt")
SELF = os.path.abspath(__file__).replace("\\", "/")
RUN = 'python "%s"' % SELF

YEARS = list(range(2015, 2026))          # 2025 는 12개월 결과만
Y24 = list(range(2015, 2025))
TRAIN = [2015, 2016, 2017, 2018]
TEST24 = list(range(2019, 2025))
TEST12 = list(range(2019, 2026))
TEST24P = list(range(2020, 2025))       # 학습 결과창(2018-04-30 + 24개월 = 2020-04-30)과 겹치지 않는 표본 밖
SEED = 20261005
NBOOT = 1000
THRESH = (1, 2, 3)
BUDGETS = (0.05, 0.10, 0.20)
MAIN_BUDGET = 0.10

FUND_RX = re.compile(r"선박투자|부동산투자회사|리츠|투자회사|해외자원개발|특별자산|맥쿼리인프라|발해인프라|인프라투융자")
DEATH_TYPES = ("사망", "사망(약)", "사망(추정)")
DEC = {"D_정리매매", "D_상폐결정", "D_상폐사유", "D_가처분", "D_파산선고"}
HALT_IDS = ["정지:" + b for b, _ in K.HALT_BUCKETS] + ["정지:기타·사유없음"]
D_IDS = [c["id"] for c in K.CATEGORIES if c["군"] == "사망"]

# 묶음 B '작전주 꼴' — 돈 · 지배구조 공시(부실 표지 · 거래소 조치 · 사고 공시는 넣지 않는다)
FAM_B = ["CB발행", "BW발행", "EB발행", "사채재매각", "사채조기상환", "전환가액조정", "전환청구", "유상증자", "증자철회",
         "감자", "주식병합", "무상증자", "최대주주변경", "경영권양수도", "주식담보_최대주주변경", "대표이사변경", "상호변경",
         "감사중도퇴임", "본점이전", "소송", "경영권분쟁", "우회상장", "타법인주식취득", "금전대여", "채무보증", "담보제공",
         "단기차입", "자산양수도", "풍문해명", "제3자배정", "임시주총", "공급계약해지"]
# 묶음 A '전체 위험' — 위험 범주 전부(일반 '매매정지' 대신 사유 묶음) + 매매정지 사유 묶음 + 과거(해소된) 사망 표지
FAM_A = [c for c in K.RISK if c != "매매정지"] + HALT_IDS + D_IDS
assert all(c in K.RISK for c in FAM_B)


# ───────────────────────── 날짜 ─────────────────────────
def shift(s, months):
    y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    t = y * 12 + (m - 1) + months
    y2, m2 = divmod(t, 12)
    m2 += 1
    return "%04d%02d%02d" % (y2, m2, min(d, calendar.monthrange(y2, m2)[1]))


def ymd(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def r4(x, n=4):
    return None if x is None else round(x, n)


def pct(vals, p):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * p
    f = int(math.floor(k))
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def div(a, b):
    return a / b if b else None


# ───────────────────────── 회사 준비 ─────────────────────────
def prepare(rows, V):
    info = {}
    for cc, d in V.items():
        v = rows[cc]
        name, code = v[-1]["corp_name"], (v[-1]["stock_code"] or "").strip()
        I = [(r["rcept_dt"], K.market_of(r["rcept_no"]), r["flr_nm"]) for r in v if r["kind"] == "I"
             and K.market_of(r["rcept_no"]) in ("유가", "코스닥", "코넥스")]
        A = sorted(r["rcept_dt"] for r in v if r["kind"] == "A001")
        spac_x = [r["rcept_dt"] for r in v if "X_스팩" in K.classify(r["report_nm"], r["flr_nm"])]
        ev = []
        for r in v:
            if K.norm(r["report_nm"])[1]:          # 정정 · 첨부 재제출은 신호로 세지 않는다
                continue
            cs = K.classify(r["report_nm"], r["flr_nm"])
            if not cs or cs == ("자회사사항",):
                continue
            s = set(cs)
            if "매매정지" in s:
                hb = K.halt_reason(r["report_nm"])
                if hb:
                    s.add("정지:" + hb)
            ev.append((r["rcept_dt"], frozenset(s)))
        E = Et = None
        if d["사망"] and d["유형"] in DEATH_TYPES:
            E, Et = d["사망일"], d["유형"]
        elif d["유형"] == "상폐절차중":
            E, Et = d["사망일"], "상폐절차중"
        info[cc] = {
            "name": name, "code": code, "cls": v[-1]["corp_cls"], "유형": d["유형"], "end": d["상장종료"],
            "Id": [x[0] for x in I], "Im": [x[1] for x in I], "If": [x[2] for x in I],
            "A": A, "spac_name": bool(K.SPAC_NAME.search(name)), "spac_end": max(spac_x) if spac_x else None,
            "fund": bool(FUND_RX.search(name)), "foreign": code.startswith("9"),
            "ev": ev, "evd": [e[0] for e in ev], "rows": v, "rd": [r["rcept_dt"] for r in v],
            "E": E, "Et": Et,
        }
    return info


def in_process_at(f, D):
    """D 까지의 공시만으로 공시분류의 '상폐절차중' 규칙 — 걸리면 절차 시작일, 아니면 None."""
    hi = bisect.bisect_right(f["rd"], D)
    lo = bisect.bisect_left(f["rd"], shift(D, -38))
    tg = K._tag(f["rows"][lo:hi], ymd(D), K.CHAIN_YEARS * 366, 0)
    chain, _ = K._chain(tg, 0)
    dec = [r for r, c, dd in chain if set(c) & DEC]
    return dec[0]["rcept_dt"] if dec else None


def count_signals(f, lo_date, D):
    lo = bisect.bisect_right(f["evd"], lo_date)
    hi = bisect.bisect_right(f["evd"], D)
    days = collections.defaultdict(set)
    for i in range(lo, hi):
        dte, s = f["ev"][i]
        for sid in s:
            days[sid].add(dte)
    return {k: len(v) for k, v in days.items()}


def load_old():
    codes = set()
    if os.path.exists(OLD_LIST):
        with open(OLD_LIST, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*([0-9A-Z]{6})\b", line)
                if m:
                    codes.add(m.group(1))
    return codes


def build_panel(info, old):
    panel, excl = [], collections.defaultdict(collections.Counter)
    mk_agree = collections.Counter()
    for y in YEARS:
        D = "%d0430" % y
        D12, D24, Dm12, Dm13, Dm24 = shift(D, 12), shift(D, 24), shift(D, -12), shift(D, -13), shift(D, -24)
        for cc, f in info.items():
            if not f["code"]:
                continue
            iI = bisect.bisect_right(f["Id"], D)
            if iI == 0:
                continue                                   # 아직 상장 전
            if f["end"] and f["end"] < D:
                continue                                   # 이미 상장 종료(사망이든 합병 · 자진이든)
            mk = collections.Counter(f["Im"][max(0, iI - 5):iI]).most_common(1)[0][0]
            exf = [x for x in f["If"][:iI] if x in ("유가증권시장본부", "코스닥시장본부", "코넥스시장")][-5:]
            if exf:
                fm = {"유가증권시장본부": "유가", "코스닥시장본부": "코스닥", "코넥스시장": "코넥스"}[collections.Counter(exf).most_common(1)[0][0]]
                mk_agree["일치" if fm == mk else "불일치"] += 1
            else:
                mk_agree["거래소제출공시없음"] += 1
            spac = f["spac_name"] or (f["spac_end"] is not None and D <= f["spac_end"])
            grp = ("스팩" if spac else "리츠펀드" if f["fund"] else "외국" if f["foreign"] else
                   "코넥스" if mk == "코넥스" else "본표본")
            E = f["E"]
            y24 = (1 if (E and D < E <= D24) else 0) if y <= 2024 else None
            y12 = 1 if (E and D < E <= D12) else 0
            a_ok = any(Dm13 < a <= D for a in f["A"])
            reason = None
            if not a_ok:
                reason = "사업보고서없음(13개월)"
            elif E and E <= D:
                reason = "이미사망(사건일≤기준일)"
            else:
                p = in_process_at(f, D)
                if p:
                    reason = "기준일에상폐절차중"
            if reason:
                excl[y][(grp, reason)] += 1
                excl[y][(grp, reason, "그뒤24개월사망")] += (y24 or 0)
                excl[y][(grp, reason, "그뒤12개월사망")] += y12
                if reason == "사업보고서없음(13개월)":
                    panel.append({"cc": cc, "y": y, "grp": grp, "mk": mk, "excluded": reason, "y24": y24, "y12": y12,
                                  "E": E, "Et": Et_of(f, E, D, D24)})
                continue
            et = Et_of(f, E, D, D24 if y <= 2024 else D12)
            y24s = None if y24 is None else (1 if (y24 and f["Et"] == "사망") else (None if y24 else 0))
            y12s = 1 if (y12 and f["Et"] == "사망") else (None if y12 else 0)
            panel.append({"cc": cc, "y": y, "grp": grp, "mk": mk, "excluded": None,
                          "y24": y24, "y12": y12, "y24s": y24s, "y12s": y12s, "E": E, "Et": et,
                          "old": f["code"] in old,
                          "s24": count_signals(f, Dm24, D), "s12": count_signals(f, Dm12, D)})
    return panel, excl, mk_agree


def Et_of(f, E, D, Dend):
    return f["Et"] if (E and D < E <= Dend) else None


# ───────────────────────── 재표본(회사 단위) ─────────────────────────
class Boot:
    """회사 단위 재표본. 관측(회사 · 기준일)을 회사별로 묶어 회사를 복원 추출한다(같은 회사의 여러 해는 함께 뽑힌다)."""

    def __init__(self, obs, ykey, B=NBOOT, seed=SEED):
        self.ykey = ykey
        self.obs = [o for o in obs if o.get(ykey) is not None]
        ccs = sorted(set(o["cc"] for o in self.obs))
        self.ix = {c: i for i, c in enumerate(ccs)}
        N = len(ccs)
        self.N = N
        n, d = [0] * N, [0] * N
        for o in self.obs:
            i = self.ix[o["cc"]]
            n[i] += 1
            d[i] += o[ykey]
        self.n, self.d = n, d
        self.tn, self.td = sum(n), sum(d)
        rnd = random.Random(seed)
        self.W = []
        rng = range(N)
        for _ in range(B):
            w = [0] * N
            for i in rnd.choices(rng, k=N):
                w[i] += 1
            self.W.append(w)
        mul = operator.mul
        self.base = [(sum(map(mul, w, n)), sum(map(mul, w, d))) for w in self.W]

    def agg(self, flag):
        fn, fd = collections.defaultdict(int), collections.defaultdict(int)
        for o in self.obs:
            if flag(o):
                i = self.ix[o["cc"]]
                fn[i] += 1
                fd[i] += o[self.ykey]
        return fn, fd

    def run(self, fn, fd):
        """→ 점추정 dict + 재표본 90% 구간"""
        idx = sorted(fn)
        Fn, Fd = sum(fn.values()), sum(fd.values())
        pt = metrics(Fn, Fd, self.tn, self.td)
        pt["걸린회사"] = len(idx)
        if not idx:
            return pt
        a = [fn[i] for i in idx]
        b = [fd[i] for i in idx]
        get = operator.itemgetter(*idx)
        mul = operator.mul
        reps = []
        for w, (tn, td) in zip(self.W, self.base):
            ws = get(w)
            if len(idx) == 1:
                ws = (ws,)
            reps.append(metrics(sum(map(mul, ws, a)), sum(map(mul, ws, b)), tn, td))
        for k in ("사망률", "lift", "RR", "재현율", "버리는비율", "남은사망률"):
            pt[k + "_90"] = [r4(pct([r[k] for r in reps], 0.05)), r4(pct([r[k] for r in reps], 0.95))]
        return pt

    def base_ci(self):
        rs = [div(td, tn) for tn, td in self.base]
        return [r4(pct(rs, 0.05), 5), r4(pct(rs, 0.95), 5)]


def metrics(Fn, Fd, tn, td):
    rate = div(Fd, Fn)
    base = div(td, tn)
    rest = div(td - Fd, tn - Fn)
    return {"걸린수": Fn, "걸린사망": Fd, "사망률": r4(rate, 5), "lift": r4(div(rate, base) if rate is not None else None, 3),
            "RR": r4(div(rate, rest) if (rate is not None and rest) else None, 3),
            "재현율": r4(div(Fd, td)), "버리는비율": r4(div(Fn, tn)), "남은사망률": r4(rest, 5), "기본사망률": r4(base, 5),
            "전체": tn, "전체사망": td}


# ───────────────────────── 범주표 ─────────────────────────
def sig_group(sid):
    if sid.startswith("정지:"):
        return "매매정지사유"
    return K.CAT_GROUP.get(sid, "?")


def category_table(obs, years, skey, ykey, boot_years_label):
    """범주 × 문턱(≥1 · ≥2 · ≥3) → 사망률 · lift · RR · 90% 구간 · 해마다 lift · 앞/뒤 기간 lift"""
    sub = [o for o in obs if o["y"] in years and o.get(ykey) is not None]
    bt = Boot(sub, ykey)
    per = collections.defaultdict(lambda: (collections.defaultdict(int), collections.defaultdict(int)))
    yr = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    ybase = collections.defaultdict(lambda: [0, 0])
    for o in sub:
        i = bt.ix[o["cc"]]
        yv = o[ykey]
        ybase[o["y"]][0] += 1
        ybase[o["y"]][1] += yv
        for sid, c in o[skey].items():
            for t in THRESH:
                if c >= t:
                    fn, fd = per[(sid, t)]
                    fn[i] += 1
                    fd[i] += yv
                    z = yr[(sid, t)][o["y"]]
                    z[0] += 1
                    z[1] += yv
    out = []
    half = {"앞(2015~2018)": set(TRAIN), "뒤(2019~)": set(y for y in years if y >= 2019)}
    for (sid, t), (fn, fd) in sorted(per.items()):
        if sum(fn.values()) < 10:
            continue
        row = {"신호": sid, "군": sig_group(sid), "작전주꼴": sid in FAM_B, "문턱": t}
        row.update(bt.run(fn, fd))
        ys = {}
        lifts = []
        for y in years:
            n, d = ybase[y]
            fnn, fdd = yr[(sid, t)].get(y, [0, 0])
            l = div(div(fdd, fnn), div(d, n)) if (fnn and d) else None
            ys[str(y)] = [fnn, fdd, r4(l, 2)]
            if fnn >= 20 and l is not None:
                lifts.append(l)
        row["해마다[걸린수,걸린사망,lift]"] = ys
        row["해마다_lift>1(걸린수≥20인 해)"] = "%d/%d" % (sum(1 for l in lifts if l > 1), len(lifts))
        row["해마다_lift_최소·중앙·최대"] = [r4(min(lifts), 2), r4(pct(lifts, 0.5), 2), r4(max(lifts), 2)] if lifts else None
        for hn, hs in half.items():
            n = sum(ybase[y][0] for y in hs if y in ybase)
            d = sum(ybase[y][1] for y in hs if y in ybase)
            fnn = sum(yr[(sid, t)].get(y, [0, 0])[0] for y in hs)
            fdd = sum(yr[(sid, t)].get(y, [0, 0])[1] for y in hs)
            row["lift_" + hn] = r4(div(div(fdd, fnn), div(d, n)) if fnn and d else None, 2)
        out.append(row)
    out.sort(key=lambda r: (-(r["lift"] or 0)))
    return {"기간": boot_years_label, "관측수": bt.tn, "사망": bt.td, "기본사망률": r4(div(bt.td, bt.tn), 5),
            "기본사망률_90": bt.base_ci(), "회사수": bt.N, "표": out}


# ───────────────────────── 규칙: 앞 기간에서 고르고 뒤 기간에 적용 ─────────────────────────
def select_categories(obs, cand, skey, ykey):
    sub = [o for o in obs if o["y"] in TRAIN and o.get(ykey) is not None]
    bt = Boot(sub, ykey)
    rows, chosen = [], []
    for sid in cand:
        fn, fd = bt.agg(lambda o, s=sid: o[skey].get(s, 0) >= 1)
        if not fn:
            continue
        m = bt.run(fn, fd)
        ok = m["걸린사망"] >= 5 and (m["lift"] or 0) >= 2 and (m["lift_90"][0] or 0) > 1
        rows.append({"신호": sid, "걸린수": m["걸린수"], "걸린사망": m["걸린사망"], "사망률": m["사망률"], "lift": m["lift"],
                     "lift_90": m["lift_90"], "뽑힘": ok})
        if ok:
            chosen.append(sid)
    rows.sort(key=lambda r: -(r["lift"] or 0))
    return chosen, rows


def score_of(o, chosen, skey):
    s = o[skey]
    return sum(1 for c in chosen if s.get(c, 0) >= 1)


BUCKETS = (("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3+", 3, 999))
FINE = (("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3-4", 3, 4), ("5-7", 5, 7), ("8-10", 8, 10), ("11+", 11, 999))


def score_buckets(obs, years, scorefn, ykey, buckets=BUCKETS):
    sub = [o for o in obs if o["y"] in years and o.get(ykey) is not None]
    tn = len(sub)
    td = sum(o[ykey] for o in sub)
    out = {}
    for nm, lo, hi in buckets:
        g = [o for o in sub if lo <= scorefn(o) <= hi]
        n, d = len(g), sum(o[ykey] for o in g)
        out[nm] = {"관측": n, "사망": d, "사망률": r4(div(d, n), 5), "lift": r4(div(div(d, n), div(td, tn)), 2) if n else None,
                   "관측비율": r4(div(n, tn)), "사망비율": r4(div(d, td))}
    return out


def strict_key(ykey):
    return ykey + "s"


def eval_flag(obs, test_years, flag, ykey, info, label_years=True):
    """표본 밖 성적: 재표본 90% 구간 · 해마다 · 시장별 · 엄격판(사망만) · 놓친 사망 목록"""
    te = [o for o in obs if o["y"] in test_years and o.get(ykey) is not None]
    bt = Boot(te, ykey)
    fn, fd = bt.agg(flag)
    m = bt.run(fn, fd)
    by_year = {}
    for y in test_years:
        ty = [o for o in te if o["y"] == y]
        a = [o for o in ty if flag(o)]
        by_year[str(y)] = metrics(len(a), sum(o[ykey] for o in a), len(ty), sum(o[ykey] for o in ty))
    by_mk = {}
    for mk in ("유가", "코스닥"):
        tm = [o for o in te if o["mk"] == mk]
        a = [o for o in tm if flag(o)]
        by_mk[mk] = metrics(len(a), sum(o[ykey] for o in a), len(tm), sum(o[ykey] for o in tm))
    sk = strict_key(ykey)
    ts = [o for o in obs if o["y"] in test_years and o.get(sk) is not None]
    a = [o for o in ts if flag(o)]
    strict = metrics(len(a), sum(o[sk] for o in a), len(ts), sum(o[sk] for o in ts))
    skey = "s24" if ykey == "y24" else "s12"
    missed = []
    for o in te:
        if o[ykey] and not flag(o):
            f = info[o["cc"]]
            risk = sorted(((c, n) for c, n in o[skey].items() if c in K.RISK or c.startswith("정지:")), key=lambda x: -x[1])
            missed.append([o["y"], f["name"], f["code"], o["mk"], o["Et"], o["E"], len(risk), ["%s×%d" % x for x in risk[:8]]])
    return {"표본밖": m, "표본밖_해마다": by_year, "표본밖_시장별": by_mk, "표본밖_엄격(사망만)": strict,
            "놓친사망_열": ["기준일연도", "회사", "종목코드", "시장", "사건유형", "사건일", "걸린위험범주수", "위험범주×날수(상위8)"],
            "놓친사망": missed}


def evaluate_rule(obs, chosen, skey, ykey, train_years, test_years, label, info):
    tr = [o for o in obs if o["y"] in train_years and o.get(ykey) is not None]
    te = [o for o in obs if o["y"] in test_years and o.get(ykey) is not None]
    sc = lambda o: score_of(o, chosen, skey)
    mx = max([sc(o) for o in tr] + [1])
    curve_tr, curve_te = [], []
    tn_tr, td_tr = len(tr), sum(o[ykey] for o in tr)
    tn_te, td_te = len(te), sum(o[ykey] for o in te)
    for k in range(1, min(mx, 30) + 1):
        a = [o for o in tr if sc(o) >= k]
        b = [o for o in te if sc(o) >= k]
        curve_tr.append(dict(문턱=k, **metrics(len(a), sum(o[ykey] for o in a), tn_tr, td_tr)))
        curve_te.append(dict(문턱=k, **metrics(len(b), sum(o[ykey] for o in b), tn_te, td_te)))
    ops = []
    for bud in BUDGETS:
        ks = [c["문턱"] for c in curve_tr if c["버리는비율"] is not None and c["버리는비율"] <= bud]
        if not ks:
            continue
        k = min(ks)
        ev = eval_flag(obs, test_years, lambda o, k=k: sc(o) >= k, ykey, info)
        trm = [c for c in curve_tr if c["문턱"] == k][0]
        op = {"예산(학습기간 버리는비율 상한)": bud, "문턱(점수≥)": k,
              "학습": {x: trm[x] for x in ("걸린수", "걸린사망", "사망률", "lift", "재현율", "버리는비율", "남은사망률")}}
        op.update(ev)
        if bud != MAIN_BUDGET:
            op.pop("놓친사망")
            op.pop("놓친사망_열")
        ops.append(op)
    return {"이름": label, "고른범주": chosen, "학습기간": list(train_years), "표본밖기간": list(test_years),
            "점수별_학습": score_buckets(obs, set(train_years), sc, ykey),
            "점수별_표본밖": score_buckets(obs, set(test_years), sc, ykey),
            "점수별_세분_학습": score_buckets(obs, set(train_years), sc, ykey, FINE),
            "점수별_세분_표본밖": score_buckets(obs, set(test_years), sc, ykey, FINE),
            "문턱곡선_학습": curve_tr, "문턱곡선_표본밖": curve_te, "운영점": ops}


def greedy_rule(obs, cand, skey, ykey, train_years, test_years, label, info, budget=MAIN_BUDGET, max_items=8, min_new=3):
    """짧은 규칙: 학습기간에서 (범주, 날수 문턱) 조건을 하나씩 더하는 OR 규칙. 매 단계 '새로 걸리는 관측 중 사망 비율'이
    가장 높은 조건(새로 걸리는 사망 ≥ min_new)을 고르고, 학습기간 버리는 비율이 budget 을 넘으면 멈춘다."""
    tr = [o for o in obs if o["y"] in train_years and o.get(ykey) is not None]
    N = len(tr)
    deaths = set(i for i, o in enumerate(tr) if o[ykey])
    items = [(sid, t) for sid in cand for t in THRESH]
    flags = {it: set(i for i, o in enumerate(tr) if o[skey].get(it[0], 0) >= it[1]) for it in items}
    covered, chosen, steps = set(), [], []
    while len(chosen) < max_items:
        best = None
        for it, fs in flags.items():
            if it in chosen:
                continue
            new = fs - covered
            nd = len(new & deaths)
            if nd < min_new or (len(covered) + len(new)) / N > budget:
                continue
            p = nd / len(new)
            if best is None or p > best[0] or (p == best[0] and nd > best[3]):
                best = (p, it, new, nd)
        if not best:
            break
        p, it, new, nd = best
        chosen.append(it)
        covered |= new
        steps.append({"조건": "%s ≥%d날" % it, "새로걸린": len(new), "새로걸린사망": nd, "새로걸린사망률": r4(p),
                      "누적버림": r4(len(covered) / N), "누적재현": r4(len(covered & deaths) / len(deaths))})
    flag = lambda o: any(o[skey].get(s, 0) >= t for s, t in chosen)
    ev = eval_flag(obs, test_years, flag, ykey, info)
    return {"이름": label, "조건(OR)": ["%s ≥%d날" % it for it in chosen], "학습단계": steps,
            "학습기간": list(train_years), "표본밖기간": list(test_years), **ev}, chosen


# ───────────────────────── 메인 ─────────────────────────
def main():
    t0 = time.time()
    rows = K.load_rows()
    data_end = max(r["rcept_dt"] for v in rows.values() for r in v)
    V = K.judge_all(rows, data_end)
    print("읽기 · 판정 %.0fs  회사 %d  자료끝 %s" % (time.time() - t0, len(V), data_end))
    info = prepare(rows, V)
    old = load_old()
    panel, excl, mk_agree = build_panel(info, old)
    print("표본 %.0fs  관측 %d" % (time.time() - t0, len(panel)))

    inc = [o for o in panel if not o["excluded"]]
    main_obs = [o for o in inc if o["grp"] == "본표본"]

    # 1) 표본 · 기본 사망률(해마다)
    per_year = {}
    for y in YEARS:
        oy = [o for o in main_obs if o["y"] == y]
        e24 = collections.Counter(o["Et"] for o in oy if o["y24"])
        e12 = collections.Counter(o["Et"] for o in oy if o["y12"])
        side = {}
        for g in ("코넥스", "외국", "스팩", "리츠펀드"):
            og = [o for o in inc if o["y"] == y and o["grp"] == g]
            side[g] = [len(og), sum(o["y24"] or 0 for o in og), sum(o["y12"] for o in og)]
        ex = {}
        for (k, v) in excl[y].items():
            if k[0] == "본표본":
                ex[" · ".join(k[1:])] = v
        per_year[str(y)] = {
            "본표본": len(oy), "유가": sum(1 for o in oy if o["mk"] == "유가"), "코스닥": sum(1 for o in oy if o["mk"] == "코스닥"),
            "24개월사망": sum(o["y24"] or 0 for o in oy) if y <= 2024 else None,
            "24개월사망률": r4(div(sum(o["y24"] or 0 for o in oy), len(oy)), 5) if y <= 2024 else None,
            "24개월사망_유형": dict(e24) if y <= 2024 else None,
            "12개월사망": sum(o["y12"] for o in oy), "12개월사망률": r4(div(sum(o["y12"] for o in oy), len(oy)), 5),
            "12개월사망_유형": dict(e12),
            "24개월사망률_유가": r4(div(sum(o["y24"] or 0 for o in oy if o["mk"] == "유가"), sum(1 for o in oy if o["mk"] == "유가")), 5) if y <= 2024 else None,
            "24개월사망률_코스닥": r4(div(sum(o["y24"] or 0 for o in oy if o["mk"] == "코스닥"), sum(1 for o in oy if o["mk"] == "코스닥")), 5) if y <= 2024 else None,
            "종목txt에든비율": r4(div(sum(1 for o in oy if o["old"]), len(oy))),
            "따로센곳[관측,24개월사망,12개월사망]": side,
            "본표본에서뺀것": ex,
        }
    b24 = Boot([o for o in main_obs if o["y"] in Y24], "y24")
    b12 = Boot(main_obs, "y12")
    base = {"24개월": {"기간": "2015~2024", "관측": b24.tn, "사망": b24.td, "회사": b24.N, "사망률": r4(div(b24.td, b24.tn), 5),
                       "사망률_90": b24.base_ci()},
            "12개월": {"기간": "2015~2025", "관측": b12.tn, "사망": b12.td, "회사": b12.N, "사망률": r4(div(b12.td, b12.tn), 5),
                       "사망률_90": b12.base_ci()}}
    for nm, ky, ys in (("24개월_엄격(사망만)", "y24s", Y24), ("12개월_엄격(사망만)", "y12s", YEARS)):
        s = [o for o in main_obs if o["y"] in ys and o.get(ky) is not None]
        base[nm] = {"관측": len(s), "사망": sum(o[ky] for o in s), "사망률": r4(div(sum(o[ky] for o in s), len(s)), 5)}
    del b24, b12
    print("기본 %.0fs" % (time.time() - t0))

    # 2) 범주표(전 기간 2015~2024, 24→24) · (2015~2025, 12→12)
    cat24 = category_table(main_obs, Y24, "s24", "y24", "2015~2024 기준일, 신호 24개월 → 사망 24개월")
    print("범주표24 %.0fs" % (time.time() - t0))
    cat12 = category_table(main_obs, YEARS, "s12", "y12", "2015~2025 기준일, 신호 12개월 → 사망 12개월")
    print("범주표12 %.0fs" % (time.time() - t0))

    # 3) 앞 · 뒤 검증
    rules = {}
    sel = {}
    greedy_ch = {}
    for fam, cand in (("A_전체위험", FAM_A), ("B_작전주꼴", FAM_B)):
        ch24, tab24 = select_categories(main_obs, cand, "s24", "y24")
        ch12, tab12 = select_categories(main_obs, cand, "s12", "y12")
        sel[fam] = {"24개월": tab24, "12개월": tab12}
        rules[fam + "_24개월"] = evaluate_rule(main_obs, ch24, "s24", "y24", TRAIN, TEST24, fam + " 점수 · 신호24→사망24", info)
        rules[fam + "_12개월"] = evaluate_rule(main_obs, ch12, "s12", "y12", TRAIN, TEST12, fam + " 점수 · 신호12→사망12", info)
        short = "C_짧은규칙_" + fam[0]
        rules[short + "_24개월"], greedy_ch[short] = greedy_rule(main_obs, cand, "s24", "y24", TRAIN, TEST24, short + " OR 규칙 · 신호24→사망24", info)
        rules[short + "_12개월"], _ = greedy_rule(main_obs, cand, "s12", "y12", TRAIN, TEST12, short + " OR 규칙 · 신호12→사망12", info)
        print("규칙 %s %.0fs" % (fam, time.time() - t0))
    # 24개월판은 학습(2015~2018) 결과창이 2020-04-30 까지라 2019 기준일과 겹친다 → 겹치지 않는 2020~2024 만으로도 따로
    for key, r in rules.items():
        if not key.endswith("_24개월"):
            continue
        if "운영점" in r:
            for op in r["운영점"]:
                k, ch = op["문턱(점수≥)"], r["고른범주"]
                op["표본밖_겹침없음(2020~2024)"] = eval_flag(main_obs, TEST24P, lambda o, k=k, ch=ch: score_of(o, ch, "s24") >= k,
                                                       "y24", info)["표본밖"]
        else:
            ch = greedy_ch[key[:-len("_24개월")]]
            r["표본밖_겹침없음(2020~2024)"] = eval_flag(main_obs, TEST24P, lambda o, ch=ch: any(o["s24"].get(s, 0) >= t for s, t in ch),
                                                  "y24", info)["표본밖"]

    # 4) 예전 표본(종목.txt)과의 차이
    chA = rules["A_전체위험_24개월"]["고른범주"]
    chB = rules["B_작전주꼴_24개월"]["고른범주"]
    kA = [x for x in rules["A_전체위험_24개월"]["운영점"] if x["예산(학습기간 버리는비율 상한)"] == MAIN_BUDGET]
    kB = [x for x in rules["B_작전주꼴_24개월"]["운영점"] if x["예산(학습기간 버리는비율 상한)"] == MAIN_BUDGET]
    kA = kA[0]["문턱(점수≥)"] if kA else 1
    kB = kB[0]["문턱(점수≥)"] if kB else 1
    s24 = [o for o in main_obs if o["y"] in Y24]
    dead_cc = sorted(set(o["cc"] for o in s24 if o["y24"]))
    old_in = [o for o in s24 if o["old"]]
    old_out = [o for o in s24 if not o["old"]]

    def grp_rate(lst, flag=None):
        l2 = [o for o in lst if (flag is None or flag(o))]
        return {"관측": len(l2), "사망": sum(o["y24"] for o in l2), "사망률": r4(div(sum(o["y24"] for o in l2), len(l2)), 5)}

    fA = lambda o: score_of(o, chA, "s24") >= kA
    fB = lambda o: score_of(o, chB, "s24") >= kB
    fCB = lambda o: any(o["s24"].get(s, 0) >= t for s, t in greedy_ch["C_짧은규칙_B"])
    allV = collections.Counter(info[cc]["유형"] for cc in info if info[cc]["code"] in old)
    allV["판정대상아님(거래소공시 없음 등)"] = len(old) - sum(allV.values())
    oldgap = {
        "종목txt_종목수": len(old),
        "종목txt_공시분류판정분포(지금)": dict(allV.most_common()),
        "본표본_24개월사망회사(2015~2024기준일)": len(dead_cc),
        "그중_종목txt에든곳": sum(1 for cc in dead_cc if info[cc]["code"] in old),
        "그중_종목txt에든곳_목록": [[info[cc]["name"], info[cc]["code"], info[cc]["Et"], info[cc]["E"]] for cc in dead_cc if info[cc]["code"] in old],
        "사망사건_유형(종목txt안)": dict(collections.Counter(o["Et"] for o in old_in if o["y24"])),
        "본표본_전체": grp_rate(s24),
        "종목txt_안": grp_rate(old_in),
        "종목txt_밖": grp_rate(old_out),
        "규칙A(예산10%)_걸린것": {"전체": grp_rate(s24, fA), "종목txt_안": grp_rate(old_in, fA), "종목txt_밖": grp_rate(old_out, fA)},
        "규칙B(예산10%)_걸린것": {"전체": grp_rate(s24, fB), "종목txt_안": grp_rate(old_in, fB), "종목txt_밖": grp_rate(old_out, fB)},
        "짧은규칙C_B_걸린것": {k: grp_rate(lst, fCB) for k, lst in (("전체", s24), ("종목txt_안", old_in), ("종목txt_밖", old_out))},
        "기준일별_본표본중_종목txt비율": {str(y): r4(div(sum(1 for o in s24 if o["y"] == y and o["old"]), sum(1 for o in s24 if o["y"] == y))) for y in Y24},
        "규칙A문턱": kA, "규칙B문턱": kB,
    }
    # 신호별: 종목txt 안에서 본 사망률 vs 전체(예전 백테스트가 본 위험 vs 실제)
    sig_old = []
    for sid in ["CB발행", "BW발행", "유상증자", "최대주주변경", "제3자배정", "감자", "상호변경", "타법인주식취득",
                "관리종목_사유", "감사의견비적정", "자본잠식", "횡령배임", "불성실_지정", "실질심사"]:
        f = lambda o, s=sid: o["s24"].get(s, 0) >= 1
        sig_old.append({"신호": sid, "전체": grp_rate(s24, f), "종목txt_안": grp_rate(old_in, f)})
    oldgap["신호별_전체vs종목txt안"] = sig_old

    # 5) 사망 목록(본표본, 24개월) — 어떤 신호가 걸렸나
    dl = []
    for o in sorted(s24, key=lambda o: (o["y"], o["cc"])):
        if not o["y24"]:
            continue
        f = info[o["cc"]]
        dl.append([o["y"], f["name"], f["code"], o["mk"], o["Et"], o["E"], (ymd(o["E"]) - ymd("%d0430" % o["y"])).days,
                   score_of(o, chA, "s24"), score_of(o, chB, "s24"),
                   [c for c in chA if o["s24"].get(c, 0)], [c for c in chB if o["s24"].get(c, 0)], o["old"]])

    # 6) 따로 센 묶음(코넥스 · 외국 · 스팩 · 리츠펀드) · 뺀 것
    side = {}
    for g in ("본표본", "코넥스", "외국", "스팩", "리츠펀드"):
        og = [o for o in inc if o["grp"] == g and o["y"] in Y24]
        side[g] = {"관측": len(og), "회사": len(set(o["cc"] for o in og)), "24개월사망": sum(o["y24"] for o in og),
                   "사망률": r4(div(sum(o["y24"] for o in og), len(og)), 5)}
    exsum = collections.defaultdict(lambda: {"관측": 0, "그뒤24개월사망": 0, "그뒤12개월사망": 0})
    for y in Y24:
        for k, v in excl[y].items():
            if k[0] == "본표본":
                exsum[k[1]]["관측" if len(k) == 2 else k[2]] += v
    exsum = dict(exsum)

    res = {
        "만든때": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "재현": {"전체": RUN + "   — 이 JSON · MD 를 다시 만든다(DART 호출 0, 약 2~4분, seed %d)" % SEED,
                 "사망 정의 · 범주": 'python "G:/내 드라이브/Claude/주식/기업추적/도구/공시분류.py" 117930   — 회사 하나의 판정 · 근거',
                 "파이썬에서": "import 작전주_사망_검증 as S; import 공시분류 as K; rows=K.load_rows(); V=K.judge_all(rows); info=S.prepare(rows,V); panel,excl,_=S.build_panel(info,S.load_old())"},
        "설계": {
            "기준일": "해마다 04-30, 2015~2024(24개월 결과) + 2025(12개월 결과만)",
            "그날 상장 중": "종목코드 · D 전 거래소공시 있음 · 상장종료(마지막 거래소공시) ≥ D · D-13개월<사업보고서≤D · 사망(절차)일 > D · D 시점 상폐절차중 아님",
            "본표본": "유가 · 코스닥(D 직전 거래소공시 5건 접수번호 시장 다수결), 스팩 · 리츠펀드 · 외국(종목코드 9xxxxx) · 코넥스는 따로",
            "신호": "D-24(·12)개월 < 접수일 ≤ D, 정정 · 첨부 재제출 제외, 범주별 서로 다른 날 수",
            "결과": "D < 사망 사건일 ≤ D+24(·12)개월. 사망 사건 = 사망 · 사망(약) · 사망(추정)의 사망일 + 상폐절차중의 절차 시작일",
            "재표본": "회사 단위 복원추출 %d번, 90%% 구간 = 5%% · 95%% 분위" % NBOOT,
            "범주 고르기(학습 2015~2018)": "걸린 사망 ≥5 · lift ≥2 · 재표본 lift 5% 하한 >1",
            "문턱": "학습기간 버리는 비율이 5% · 10% · 20% 이하인 가장 낮은 점수 문턱 → 표본 밖(2019~2024 · 12개월판 2019~2025)에 그대로",
            "짧은규칙(C)": "학습기간에서 (범주, 날수≥1·2·3) 조건을 OR 로 하나씩 더함: 매 단계 새로 걸리는 관측의 사망 비율이 가장 높은 조건"
                         "(새로 걸리는 사망 ≥3), 학습기간 버리는 비율 10% 넘기 전까지 · 최대 8개 → 표본 밖에 그대로",
            "묶음A_후보": FAM_A, "묶음B_후보(작전주 꼴)": FAM_B,
        },
        "자료": {"자료끝": data_end, "판정대상회사": len(V), "관측(전체, 뺀 것 포함 안 함)": len(inc),
                 "시장추정_flr_nm다수결과_일치": dict(mk_agree)},
        "기본사망률": base,
        "해마다": per_year,
        "묶음별(2015~2024, 24개월)": side,
        "본표본에서뺀것_합계(2015~2024)": dict(exsum),
        "범주표_24개월": cat24,
        "범주표_12개월": cat12,
        "범주고르기_학습": sel,
        "규칙": rules,
        "예전표본과의차이": oldgap,
        "사망목록_열": ["기준일연도", "회사", "종목코드", "시장", "사건유형", "사건일", "기준일→사건일수", "점수A", "점수B",
                   "걸린A범주", "걸린B범주", "종목txt에있나"],
        "사망목록(본표본,24개월)": dl,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    md = render_md(res)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(md)
    print("저장", OUT_JSON, OUT_MD, "%.0fs" % (time.time() - t0))
    return res


# ───────────────────────── 요약 MD ─────────────────────────
def P(x, d=1):
    return "–" if x is None else ("%." + str(d) + "f%%") % (x * 100)


def CI(v, d=1, pctg=True):
    if not v or v[0] is None:
        return ""
    if pctg:
        return " [%s~%s]" % (P(v[0], d), P(v[1], d))
    return " [%.1f~%.1f]" % (v[0], v[1])


def F(x, d=1):
    return "–" if x is None else ("%." + str(d) + "f") % x


KEY_SIGNALS = ["CB발행", "유상증자", "제3자배정", "최대주주변경", "경영권양수도", "사채조기상환", "전환가액조정", "상호변경", "감자",
               "불성실_지정", "관리종목_사유", "실질심사", "감사의견비적정", "횡령배임", "현금배당"]


def op_of(r, bud=MAIN_BUDGET):
    x = [o for o in r.get("운영점", []) if o["예산(학습기간 버리는비율 상한)"] == bud]
    return x[0] if x else None


def oos_line(m):
    return ("버림 %s%s · 피한 사망(재현) %s%s · 걸린 것 중 사망(정밀) %s%s · lift %s · 남은 쪽 사망률 %s%s (기본 %s)" % (
        P(m["버리는비율"]), CI(m.get("버리는비율_90")), P(m["재현율"], 0), CI(m.get("재현율_90"), 0), P(m["사망률"]), CI(m.get("사망률_90")),
        F(m["lift"]), P(m["남은사망률"], 2), CI(m.get("남은사망률_90"), 2), P(m["기본사망률"], 2)))


def render_md(R):
    L = []
    a = L.append
    b24, b12 = R["기본사망률"]["24개월"], R["기본사망률"]["12개월"]
    RU = R["규칙"]
    cb, ca = RU["C_짧은규칙_B_24개월"], RU["C_짧은규칙_A_24개월"]
    sb, sa = op_of(RU["B_작전주꼴_24개월"]), op_of(RU["A_전체위험_24개월"])
    g = R["예전표본과의차이"]
    a("# 작전주 사망 검증 — '그 시점' 표본(상장폐지 회사 포함)")
    a("")
    a("만든 때 %s · 자료끝 %s · DART 호출 0 · 재현: `%s` (seed %d, 약 2~4분)" % (R["만든때"], R["자료"]["자료끝"], RUN, SEED))
    a("")
    a("## 0. 답")
    a("")
    a("- **기본 사망률**: 4월 30일에 상장 중인 유가 · 코스닥 영업회사가 24개월 안에 비자발 상장폐지 사슬에 들어갈 확률 %s%s"
      " (2015~2024 기준일, 관측 %d · 사망 %d · 회사 %d). 12개월은 %s." % (P(b24["사망률"], 2), CI(b24["사망률_90"], 2), b24["관측"], b24["사망"], b24["회사"], P(b12["사망률"], 2)))
    m = cb["표본밖"]
    a("- **표본 밖 핵심(2019~2024)** — 2015~2018 에서 고른 짧은 규칙 C_B(작전주 꼴 공시만, 조건 %d개 OR: %s): %s." % (
        len(cb["조건(OR)"]), " · ".join(cb["조건(OR)"]), oos_line(m)))
    if sb:
        a("- 같은 기간 점수 규칙 B(작전주 꼴 %d범주 중 %d개 이상 걸림): %s." % (len(RU["B_작전주꼴_24개월"]["고른범주"]), sb["문턱(점수≥)"], oos_line(sb["표본밖"])))
    if sa:
        a("- 부실 · 거래소 조치 공시까지 넣은 점수 규칙 A(%d범주 중 %d개 이상): %s." % (len(RU["A_전체위험_24개월"]["고른범주"]), sa["문턱(점수≥)"], oos_line(sa["표본밖"])))
    c12 = RU["C_짧은규칙_B_12개월"]
    a("- 12개월판(신호 12개월 → 사망 12개월, 표본 밖 2019~2025) 짧은 규칙 C_B: %s." % oos_line(c12["표본밖"]))
    s20 = op_of(RU["B_작전주꼴_24개월"], 0.20)
    if s20:
        a("- 더 많이 버리면: 규칙 B 점수≥%d 는 표본 밖에서 %s 버리고 사망 %s 를 피했다(남은 쪽 사망률 %s)." % (
            s20["문턱(점수≥)"], P(s20["표본밖"]["버리는비율"]), P(s20["표본밖"]["재현율"], 0), P(s20["표본밖"]["남은사망률"], 2)))
    mk = cb["표본밖_시장별"]
    a("- **못 잡는 쪽**: 유가 사망은 C_B 가 %s(사망 %d곳 중), 코스닥은 %s 를 잡았다. 걸린 것 중 사망은 %s 뿐이라 걸린 종목의 대부분(약 %s)은 24개월 안에 죽지 않는다 — '사망' 이 아닌 '우하향' 은 이 연구가 재지 못했다(주가 없음)." % (
        P(mk["유가"]["재현율"], 0), mk["유가"]["전체사망"], P(mk["코스닥"]["재현율"], 0), P(m["사망률"], 0), P(1 - (m["사망률"] or 0), 0)))
    a("- **예전 표본이 못 본 것**: 2015~2024 기준일 뒤 24개월 안에 죽은 본표본 회사 %d곳 가운데 종목.txt(지금 시총 상위 1000)에 든 곳은 %d곳(%s, 모두 아직 결론 안 난 상폐절차중). "
      "같은 관측의 24개월 사망률은 종목.txt 안 %s · 밖 %s. C_B 에 걸린 관측(2015~2024 전체)의 사망률도 전체 %s 인데 종목.txt 안에서는 %s(관측 %d) — 예전 백테스트로는 이 위험이 거의 0 으로 보인다." % (
        g["본표본_24개월사망회사(2015~2024기준일)"], g["그중_종목txt에든곳"], P(div(g["그중_종목txt에든곳"], g["본표본_24개월사망회사(2015~2024기준일)"])),
        P(g["종목txt_안"]["사망률"], 2), P(g["종목txt_밖"]["사망률"], 2), P(g["짧은규칙C_B_걸린것"]["전체"]["사망률"]),
        P(g["짧은규칙C_B_걸린것"]["종목txt_안"]["사망률"]), g["짧은규칙C_B_걸린것"]["종목txt_안"]["관측"]))
    ex = R["본표본에서뺀것_합계(2015~2024)"]
    e2 = ex.get("기준일에상폐절차중", {})
    a("- **규칙 전에 거를 것**: 기준일에 이미 상폐 절차 중(거래소 상장폐지 사유 · 결정 · 정리매매 · 가처분이 해소 없이 남음)인 관측 %d 은 본표본에서 뺐는데, 그중 %d(%s)가 24개월 안에 (새로) 사망 사슬에 들어갔다. 사업보고서를 13개월 안에 안 낸 관측 %d 중 %d 사망. 스크리너는 이 둘을 먼저 거른다." % (
        e2.get("관측", 0), e2.get("그뒤24개월사망", 0), P(div(e2.get("그뒤24개월사망", 0), e2.get("관측", 0)), 0),
        ex.get("사업보고서없음(13개월)", {}).get("관측", 0), ex.get("사업보고서없음(13개월)", {}).get("그뒤24개월사망", 0)))
    a("")
    a("## 1. 표본과 기본 사망률")
    a("")
    a("- 기준일 D = 해마다 4월 30일(2015~2024; 2025 는 D+24개월이 자료끝을 넘어 12개월 결과만).")
    a("- 그날 상장 중 = 종목코드 · D 전 거래소공시 · 마지막 거래소공시 ≥ D(또는 지금 상장) · D-13개월 < 사업보고서 ≤ D · 사망(절차)일 > D · D 시점의 공시만으로 상폐절차중이 아님.")
    a("- 본표본 = 유가 · 코스닥(D 직전 거래소공시 5건의 접수번호 시장 다수결). 스팩 · 리츠펀드 · 외국(종목코드 9xxxxx) · 코넥스는 따로 셌다.")
    agree = R["자료"]["시장추정_flr_nm다수결과_일치"]
    a("- 시장 추정 점검: 거래소가 낸 공시의 제출자(flr_nm) 다수결과 맞춰 보면 일치 %d · 불일치 %d(이전상장 직후 등) · 거래소 제출 공시 없음 %d." % (
        agree.get("일치", 0), agree.get("불일치", 0), agree.get("거래소제출공시없음", 0)))
    a("- 사망 사건 = 공시분류.py 의 사망 · 사망(약) · 사망(추정)의 사망일(마지막 사망 사슬의 첫 결정적 사건 — 정리매매보다 중앙값 173일 앞) + 지금 상폐절차중(정리매매 보류 · 가처분 · 개선기간)인 회사의 절차 시작일.")
    s = R["기본사망률"]["24개월_엄격(사망만)"]
    a("- 엄격판(사망만; 사망(약) · 사망(추정) · 상폐절차중이 사건인 관측은 뺌): 24개월 %s (관측 %d · 사망 %d)." % (P(s["사망률"], 2), s["관측"], s["사망"]))
    a("")
    a("| 기준일 | 본표본 | 유가 | 코스닥 | 24개월 사망 | 사망률 | 유가 | 코스닥 | 그중 상폐절차중 | 12개월 사망 | 사망률 | 종목.txt 비율 |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for y, v in R["해마다"].items():
        pend = (v["24개월사망_유형"] or {}).get("상폐절차중", 0) if v["24개월사망_유형"] is not None else None
        a("| %s | %d | %d | %d | %s | %s | %s | %s | %s | %d | %s | %s |" % (
            y, v["본표본"], v["유가"], v["코스닥"], "–" if v["24개월사망"] is None else v["24개월사망"], P(v["24개월사망률"], 2),
            P(v["24개월사망률_유가"], 2), P(v["24개월사망률_코스닥"], 2), "–" if pend is None else pend, v["12개월사망"], P(v["12개월사망률"], 2),
            P(v["종목txt에든비율"], 0)))
    a("")
    a("| 묶음(2015~2024) | 관측 | 회사 | 24개월 사망 | 사망률 |")
    a("|---|---|---|---|---|")
    for gname, v in R["묶음별(2015~2024, 24개월)"].items():
        a("| %s | %d | %d | %d | %s |" % (gname, v["관측"], v["회사"], v["24개월사망"], P(v["사망률"], 2)))
    a("")
    a("| 본표본 후보에서 뺀 것(2015~2024 합) | 관측 | 그 뒤 24개월 사망 | 그 뒤 12개월 사망 |")
    a("|---|---|---|---|")
    for k, v in ex.items():
        a("| %s | %d | %d | %d |" % (k, v["관측"], v["그뒤24개월사망"], v["그뒤12개월사망"]))
    a("")
    a("## 2. 범주별 사망률과 배수(lift) — 2015~2024, 신호 24개월 → 사망 24개월")
    a("")
    c24 = R["범주표_24개월"]
    a("기본 %s%s. lift = 걸린 쪽 사망률 / 기본, RR = 걸린 쪽 / 안 걸린 쪽, [ ] = 회사 단위 재표본 %d번 90%% 구간, 재현율 = 전체 사망 중 그 신호가 걸린 몫. "
      "'해마다' = 걸린 관측 20 이상인 해 중 lift>1 인 해. 앞 · 뒤 = 2015~2018 · 2019~2024 기준일 lift. 문턱 ≥1(24개월 안에 한 번이라도), 걸린 사망 3 이상." % (
          P(c24["기본사망률"], 2), CI(c24["기본사망률_90"], 2), NBOOT))
    a("")
    a("| 신호 | 군 | 걸린 관측 | 걸린 사망 | 사망률 | lift [90%] | RR | 재현율 | 해마다 | 앞 · 뒤 |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    tab = [r for r in c24["표"] if r["문턱"] == 1 and r["걸린사망"] >= 3 and r["군"] not in ("대조",)]
    for r in tab[:50]:
        a("| %s | %s%s | %d | %d | %s | %s%s | %s | %s | %s | %s · %s |" % (
            r["신호"], r["군"], "·작전" if r["작전주꼴"] else "", r["걸린수"], r["걸린사망"], P(r["사망률"], 1), F(r["lift"]),
            CI(r.get("lift_90"), pctg=False), F(r["RR"]), P(r["재현율"], 0), r["해마다_lift>1(걸린수≥20인 해)"],
            F(r["lift_앞(2015~2018)"]), F(r["lift_뒤(2019~)"])))
    a("")
    a("대조(건전 기업에도 흔한 공시) — 신호가 아니라 '건강' 쪽이어야 정상:")
    a("")
    for r in c24["표"]:
        if r["문턱"] == 1 and r["군"] == "대조":
            a("- %s: 걸린 %d · 사망 %d · 사망률 %s · lift %s%s" % (r["신호"], r["걸린수"], r["걸린사망"], P(r["사망률"], 2), F(r["lift"], 2), CI(r.get("lift_90"), pctg=False)))
    a("")
    a("작전주 꼴 범주는 '잦을수록' 세진다(24개월 안 서로 다른 날 수 ≥2 · ≥3):")
    a("")
    a("| 신호 | ≥1 사망률 · lift | ≥2 사망률 · lift | ≥3 사망률 · lift [90%] · 걸린 관측 |")
    a("|---|---|---|---|")
    idx = {(r["신호"], r["문턱"]): r for r in c24["표"]}
    for sid in ("CB발행", "BW발행", "유상증자", "제3자배정", "최대주주변경", "경영권양수도", "사채조기상환", "전환가액조정", "대표이사변경", "상호변경", "타법인주식취득", "금전대여"):
        cells = []
        for t in (1, 2, 3):
            r = idx.get((sid, t))
            if not r:
                cells.append("–")
            elif t < 3:
                cells.append("%s · %s" % (P(r["사망률"]), F(r["lift"])))
            else:
                cells.append("%s · %s%s · %d" % (P(r["사망률"]), F(r["lift"]), CI(r.get("lift_90"), pctg=False), r["걸린수"]))
        a("| %s | %s |" % (sid, " | ".join(cells)))
    a("")
    a("해마다 안정성(문턱 ≥1, 기준일별 lift; 걸린 관측이 20 미만이면 괄호):")
    a("")
    a("| 신호 | " + " | ".join(str(y) for y in Y24) + " |")
    a("|---|" + "---|" * len(Y24))
    for sid in KEY_SIGNALS:
        r = idx.get((sid, 1))
        if not r:
            continue
        cells = []
        for y in Y24:
            n, d, l = r["해마다[걸린수,걸린사망,lift]"][str(y)]
            cells.append("–" if l is None else ("%.1f" % l if n >= 20 else "(%.1f)" % l))
        a("| %s | %s |" % (sid, " | ".join(cells)))
    a("")
    a("## 3. 앞 · 뒤 기간 검증 — 2015~2018 기준일로 정하고 2019~ 에 그대로")
    a("")
    a("범주 고르기(학습): 걸린 사망 ≥5 · lift ≥2 · 재표본 lift 5% 하한 >1. 점수 = 고른 범주 중 24(·12)개월 안에 한 번이라도 나온 범주 수. "
      "문턱 = 학습기간 버리는 비율이 5% · 10% · 20% 이하인 가장 낮은 점수. 짧은 규칙 C = 학습기간에서 (범주, 날수) 조건을 하나씩 OR 로 더함(새로 걸리는 관측의 사망 비율이 가장 높은 것, 새 사망 ≥3, 버림 10% 전까지, 최대 8개). "
      "표본 밖 숫자의 [ ] 는 표본 밖 관측의 회사 단위 재표본 90% 구간이다(규칙은 고정).")
    a("")
    a("### 3-1. 짧은 규칙(조건 OR) — 표본 밖 성적")
    a("")
    a("| 규칙 | 조건 | 표본밖 기간 | 버리는 비율 | 재현율(피한 사망) | 정밀도(걸린 것 중 사망) | lift | 남은 쪽 사망률(기본) | 엄격판 재현 · 정밀 | 2020~ 만 재현 · 버림 |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for key in ("C_짧은규칙_B_24개월", "C_짧은규칙_A_24개월", "C_짧은규칙_B_12개월", "C_짧은규칙_A_12개월"):
        r = RU[key]
        m, st = r["표본밖"], r["표본밖_엄격(사망만)"]
        pg = r.get("표본밖_겹침없음(2020~2024)")
        a("| %s | %s | %s~%s | %s%s | %s%s | %s%s | %s | %s (%s) | %s · %s | %s |" % (
            key, " · ".join(r["조건(OR)"]), r["표본밖기간"][0], r["표본밖기간"][-1], P(m["버리는비율"]), CI(m.get("버리는비율_90")),
            P(m["재현율"], 0), CI(m.get("재현율_90"), 0), P(m["사망률"]), CI(m.get("사망률_90")), F(m["lift"]),
            P(m["남은사망률"], 2), P(m["기본사망률"], 2), P(st["재현율"], 0), P(st["사망률"]),
            ("%s · %s" % (P(pg["재현율"], 0), P(pg["버리는비율"]))) if pg else "–"))
    a("")
    for key in ("C_짧은규칙_B_24개월",):
        r = RU[key]
        a("%s 학습 단계(2015~2018):" % key)
        a("")
        a("| 더한 조건 | 새로 걸린 관측 | 새로 걸린 사망 | 그 사망률 | 누적 버림 | 누적 재현 |")
        a("|---|---|---|---|---|---|")
        for s_ in r["학습단계"]:
            a("| %s | %d | %d | %s | %s | %s |" % (s_["조건"], s_["새로걸린"], s_["새로걸린사망"], P(s_["새로걸린사망률"]), P(s_["누적버림"]), P(s_["누적재현"], 0)))
        a("")
        a("표본 밖 해마다: " + " · ".join("%s 재현 %s(사망 %d) 버림 %s 정밀 %s" % (y, P(v["재현율"], 0), v["전체사망"], P(v["버리는비율"], 0), P(v["사망률"], 0))
                                       for y, v in r["표본밖_해마다"].items()))
        a("")
        a("표본 밖 시장별: " + " · ".join("%s 재현 %s(사망 %d) 버림 %s 정밀 %s" % (k, P(v["재현율"], 0), v["전체사망"], P(v["버리는비율"]), P(v["사망률"]))
                                       for k, v in r["표본밖_시장별"].items()))
        a("")
        miss = r["놓친사망"]
        z = sum(1 for x in miss if x[6] == 0)
        a("놓친 사망 %d건(관측) — 위험 범주가 하나도 없던 것 %d건, 사건유형 %s. 예: %s" % (
            len(miss), z, dict(collections.Counter(x[4] for x in miss)),
            " / ".join("%s %s(%s, %s %s)" % (x[0], x[1], x[3], x[4], x[5]) for x in miss[:12])))
        a("")
    a("### 3-2. 점수 규칙")
    a("")
    for key in ("B_작전주꼴_24개월", "A_전체위험_24개월", "B_작전주꼴_12개월", "A_전체위험_12개월"):
        r = RU[key]
        a("#### %s" % r["이름"])
        a("")
        a("고른 범주(%d): %s" % (len(r["고른범주"]), ", ".join(r["고른범주"])))
        a("")
        a("| 점수 | 학습 관측 | 학습 사망률 | 표본밖 관측 | 표본밖 사망 | 표본밖 사망률 | lift | 표본밖 사망 몫 |")
        a("|---|---|---|---|---|---|---|---|")
        for k in ("0", "1", "2", "3+"):
            x, z = r["점수별_학습"][k], r["점수별_표본밖"][k]
            a("| %s | %d | %s | %d | %d | %s | %s | %s |" % (k, x["관측"], P(x["사망률"], 2), z["관측"], z["사망"], P(z["사망률"], 2), F(z["lift"]), P(z["사망비율"], 0)))
        a("")
        a("세분(표본밖): " + " · ".join("%s점 %d관측 사망 %d(%s)" % (k, v["관측"], v["사망"], P(v["사망률"])) for k, v in r["점수별_세분_표본밖"].items()))
        a("")
        a("| 예산 | 문턱 | 학습 버림 · 재현 | 표본밖 버림 | 재현율 | 정밀도 | lift | 남은 쪽 사망률 | 엄격판 재현 · 정밀 | 2020~ 만 재현 · 버림 |")
        a("|---|---|---|---|---|---|---|---|---|---|")
        for op in r["운영점"]:
            m, t, st = op["표본밖"], op["학습"], op["표본밖_엄격(사망만)"]
            pg = op.get("표본밖_겹침없음(2020~2024)")
            a("| ≤%s | 점수≥%d | %s · %s | %s%s | %s%s | %s%s | %s%s | %s | %s · %s | %s |" % (
                P(op["예산(학습기간 버리는비율 상한)"], 0), op["문턱(점수≥)"], P(t["버리는비율"]), P(t["재현율"], 0),
                P(m["버리는비율"]), CI(m.get("버리는비율_90")), P(m["재현율"], 0), CI(m.get("재현율_90"), 0),
                P(m["사망률"]), CI(m.get("사망률_90")), F(m["lift"]), CI(m.get("lift_90"), pctg=False), P(m["남은사망률"], 2),
                P(st["재현율"], 0), P(st["사망률"]), ("%s · %s" % (P(pg["재현율"], 0), P(pg["버리는비율"]))) if pg else "–"))
        o10 = op_of(r)
        if o10:
            a("")
            a("예산 10% 표본 밖 해마다: " + " · ".join("%s 재현 %s 버림 %s" % (y, P(v["재현율"], 0), P(v["버리는비율"], 0)) for y, v in o10["표본밖_해마다"].items())
              + " / 시장별: " + " · ".join("%s 재현 %s 정밀 %s 버림 %s(사망 %d)" % (k, P(v["재현율"], 0), P(v["사망률"]), P(v["버리는비율"]), v["전체사망"])
                                          for k, v in o10["표본밖_시장별"].items()))
        a("")
    a("## 4. 예전 표본(종목.txt = 2026-10-01 시총 상위 1000)과의 차이")
    a("")
    a("- 종목.txt %d종목의 지금 판정: %s." % (g["종목txt_종목수"], ", ".join("%s %d" % kv for kv in g["종목txt_공시분류판정분포(지금)"].items())))
    a("- 2015~2024 기준일 뒤 24개월 안에 죽은 본표본 회사 %d곳 중 종목.txt 에 든 곳 %d곳(%s): %s." % (
        g["본표본_24개월사망회사(2015~2024기준일)"], g["그중_종목txt에든곳"], P(div(g["그중_종목txt에든곳"], g["본표본_24개월사망회사(2015~2024기준일)"])),
        ", ".join("%s(%s %s)" % (x[0], x[2], x[3]) for x in g["그중_종목txt에든곳_목록"]) or "없음"))
    a("- 24개월 사망률(같은 관측): 전체 %s(관측 %d) · 종목.txt 안 %s(관측 %d · 사망 %d) · 밖 %s(관측 %d · 사망 %d). 사망 관측의 %s 가 종목.txt 밖에 있다 — 안쪽 사망률은 전체의 1/%d 이다." % (
        P(g["본표본_전체"]["사망률"], 2), g["본표본_전체"]["관측"], P(g["종목txt_안"]["사망률"], 2), g["종목txt_안"]["관측"], g["종목txt_안"]["사망"],
        P(g["종목txt_밖"]["사망률"], 2), g["종목txt_밖"]["관측"], g["종목txt_밖"]["사망"],
        P(div(g["종목txt_밖"]["사망"], g["본표본_전체"]["사망"]), 0),
        round(div(g["본표본_전체"]["사망률"], g["종목txt_안"]["사망률"]) or 0)))
    for nm, kk in (("짧은 규칙 C_B", "짧은규칙C_B_걸린것"), ("점수 규칙 B(점수≥%d)" % g["규칙B문턱"], "규칙B(예산10%)_걸린것"),
                   ("점수 규칙 A(점수≥%d)" % g["규칙A문턱"], "규칙A(예산10%)_걸린것")):
        x = g[kk]
        a("- %s 에 걸린 관측의 24개월 사망률: 전체 %s(관측 %d) · 종목.txt 안 %s(관측 %d · 사망 %d) · 밖 %s(관측 %d)." % (
            nm, P(x["전체"]["사망률"]), x["전체"]["관측"], P(x["종목txt_안"]["사망률"]), x["종목txt_안"]["관측"], x["종목txt_안"]["사망"],
            P(x["종목txt_밖"]["사망률"]), x["종목txt_밖"]["관측"]))
    a("- 기준일별 본표본 중 종목.txt 에 든 비율: " + " · ".join("%s %s" % (y, P(v, 0)) for y, v in g["기준일별_본표본중_종목txt비율"].items()) + " — 예전 표본은 그 시점 상장사의 1/3 남짓만 본다.")
    a("")
    a("| 신호(24개월 ≥1) | 전체 관측 · 사망 · 사망률 | 종목.txt 안 관측 · 사망 · 사망률 |")
    a("|---|---|---|")
    for x in g["신호별_전체vs종목txt안"]:
        a("| %s | %d · %d · %s | %d · %d · %s |" % (x["신호"], x["전체"]["관측"], x["전체"]["사망"], P(x["전체"]["사망률"], 2),
                                                   x["종목txt_안"]["관측"], x["종목txt_안"]["사망"], P(x["종목txt_안"]["사망률"], 2)))
    a("")
    a("## 5. 주의")
    a("")
    for c in CAVEATS:
        a("- " + c)
    a("")
    a("## 6. 재현")
    a("")
    a("- 전체: `%s` → 이 파일과 사망_검증.json 을 다시 만든다(DART 호출 0, 이미 받은 .cache/공시목록/*.jsonl 만 읽음, 재표본 seed %d)." % (RUN, SEED))
    a("- 사망 정의 · 회사 하나 판정: `python \"G:/내 드라이브/Claude/주식/기업추적/도구/공시분류.py\" 117930`")
    a("- JSON 열쇠: 기본사망률 · 해마다 · 범주표_24개월/12개월(표: 신호 × 문턱, 해마다 lift) · 범주고르기_학습 · 규칙(A/B 점수 · C 짧은 규칙, 운영점 · 놓친사망) · 예전표본과의차이 · 사망목록(본표본,24개월).")
    return "\n".join(L) + "\n"


CAVEATS = [
    "주가를 쓰지 않았다. 잰 것은 '사망(비자발 상장폐지 사슬에 들어감)' 뿐이고, 90% 빠지고도 상장을 유지한 작전주(약속의 '우하향')는 사망으로 안 잡힌다. 걸린 종목의 사망률(정밀도)이 10%대라는 것은 '나머지 90%는 멀쩡하다' 가 아니라 '24개월 안에 상폐되지는 않았다' 는 뜻이다.",
    "사망 사건일은 사슬의 첫 결정적 사건(대개 감사의견 거절 · 자본잠식에 따른 거래소 '상장폐지 사유 발생')이다. 사건일 뒤 공시는 신호로 쓰지 않았고, 기준일에 이미 절차 중인 회사는 표본에서 뺐다(따로 셈).",
    "상폐절차중(지금 상장이지만 상폐 결정 · 정리매매 보류 · 개선기간, 80곳 중 78곳이 2025~26 시작)을 사망 사건에 넣었다. 2023 · 2024 기준일 사망의 상당수가 이것이라 나중에 살아나면 그 해 숫자가 줄어든다. 엄격판(사망만) 숫자를 함께 냈다.",
    "사망(추정) 16곳은 사망일이 몇 주~몇 달 틀릴 수 있다(제목에 상장폐지가 직접 안 나온 2013~2018 유가 퇴출).",
    "이름(corp_name)과 종목코드는 '지금' 값이다. 스팩은 이름 + '기업인수목적회사…' 공시로, 리츠 · 펀드는 이름으로 가렸다. 스팩 존속합병으로 이름이 바뀐 회사는 합병 완료 공시(마지막 X_스팩) 전까지 스팩으로 본다.",
    "신호는 제목 정규식 분류(공시분류.py)다. DART 에는 KIND 시장조치 원문(관리종목 지정 · 투자경고 그 자체)이 없어 '사유 발생 · 우려' 제목으로만 잡힌다. 제3자배정은 거래소 '증권발행결과' 제목에 드러난 것만이다.",
    "정정 · 첨부 재제출은 세지 않았고, 같은 범주는 같은 날 여러 건이어도 1 로 셌다(B 와 I 에 같은 사건이 겹치는 것을 막으려고).",
    "점수 규칙은 범주를 많이 고른다(학습 기준이 느슨함: 사망 ≥5 · lift ≥2 · 하한 >1). 표본 밖 성적이 이 느슨함의 값을 치른 뒤의 숫자다. 문턱은 학습기간 버리는 비율로만 정했고 표본 밖을 보고 고치지 않았다.",
    "24개월판의 학습 결과창(2018-04-30 + 24개월)은 2019 기준일과 1년 겹친다. 겹치지 않는 2020~2024 만의 성적('2020~ 만')도 냈다. 같은 회사가 학습 · 표본 밖 양쪽에 다른 해로 나온다(시간 일반화 검증이지 회사 일반화 검증이 아니다).",
    "재표본 구간은 회사 단위 복원추출(같은 회사의 여러 해를 함께 뽑음)이고, 규칙을 고르는 과정의 불확실성은 들어 있지 않다.",
    "유가 사망은 이 공시 신호로 덜 잡힌다(큰 회사의 갑작스런 감사의견 거절 · 건설사 부실 · 상폐절차중). 재무 자료(자본잠식률 · 영업손실 연속)를 더해야 할 쪽이다.",
    "코넥스(24개월 사망률 약 9%) · 외국 기업(약 6%)은 본표본보다 훨씬 위험하다. 스크리너가 이들을 다룬다면 따로 거를 것.",
]


if __name__ == "__main__":
    main()
