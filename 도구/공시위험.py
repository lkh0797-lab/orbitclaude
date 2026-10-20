# -*- coding: utf-8 -*-
"""
공시 위험 — 오늘 기준 '작전주 꼴' · 상장폐지 사슬 표지 (2026-10-06)

규칙은 도구/작전주_사망_검증.py · 작전주_사망_보강.py 가 2015~2018 기준일로 고르고 2019~2024 에 표본 밖으로 잰 것을 그대로 고정해 쓴다
(여기서 다시 고르지 않는다). 공시 목록 캐시(.cache/공시목록 — 도구/공시목록_수집.py)만 읽고 DART 를 부르지 않는다.

  ① 상폐 절차   오늘까지의 공시로 거래소의 상장폐지 사유 · 결정 · 정리매매 · 가처분 · 파산선고 사슬이 해소 없이 남아 있다(공시분류의 '상폐절차중' 규칙)
  ② 보고서 없음 13개월 안에 사업보고서(정정 포함)가 없다
  ③ 작전주 꼴   지난 24개월 안 서로 다른 날 수로 BW 발행 ≥3 · 제3자배정 ≥3 · 최대주주 변경 ≥3 · 경영권 양수도 ≥2 · 유상증자 ≥3 ·
                금전대여 ≥3 · 사채 조기상환 ≥3 · CB 발행 ≥3 가운데 하나에 걸리고, 24개월 안 현금배당 공시가 없다
  ③' 자금조달 잦음  ③ 조건에 걸렸지만 배당이 있다 — 과거 사망률이 상장사 평균 수준이라 참고만(거르지 않는다)
  묶음 표시     코넥스 · 외국 기업(종목코드 9xxxxx) · 스팩 · 리츠 · 펀드 — 같은 잣대로 재지 않았다

표본 밖 성적(2019~2024, 유가 · 코스닥 영업회사, 24개월 안 상장폐지 사슬 진입, 회사×해 재표본 90% 구간):
  아무것도 안 거름 1.81% [1.25, 2.37] · ③ 작전주 꼴은 상장사 8.2% 를 거르고 사망의 64% [56, 72] 를 피한다 — 걸린 쪽 14.1%, 남은 쪽 0.72%.
  ① 이 보이던 관측의 56% 가 그 사슬로 상장폐지되었거나 24개월 안에 다시 사슬에 들었다. ② 는 30관측 중 5. ③' 는 1.4%.
  한계: 주가(우하향)는 재지 않았다 · 유가 대형사의 갑작스런 감사의견 거절은 38% 만 잡는다 · 최근 해일수록 약하다.

실행: python 도구/공시위험.py      결과: .cache/공시목록/공시위험.json (약 1분)
"""
import bisect
import collections
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import 공시분류 as K  # noqa: E402
import 작전주_사망_검증 as S  # noqa: E402

# 리츠 이름 규칙 — 보강.py 와 같게('리츠' 끝 고정 + 이름 끝이 리츠가 아닌 상장 리츠 둘)
S.FUND_RX = re.compile(S.FUND_RX.pattern.replace("|리츠|", "|리츠$|이리츠코크렙|맵스리얼티|"))

RULE = [("BW발행", 3), ("제3자배정", 3), ("최대주주변경", 3), ("경영권양수도", 2),
        ("유상증자", 3), ("금전대여", 3), ("사채조기상환", 3), ("CB발행", 3)]
NAME = {"BW발행": "BW 발행", "제3자배정": "제3자배정", "최대주주변경": "최대주주 변경", "경영권양수도": "경영권 양수도",
        "유상증자": "유상증자", "금전대여": "금전대여", "사채조기상환": "사채 조기상환(풋)", "CB발행": "CB 발행"}
# 걸리지 않아도 펼침에 참고로 보일 부실 · 거래소 조치 표지(24개월 안)
REF = ["회생절차", "파산신청", "감사의견비적정", "관리종목_사유", "관리종목_우려", "실질심사", "상폐우려", "횡령배임",
       "불성실_지정", "자본잠식", "보고서지연", "투자주의환기"]
EVIDENCE = {
    "기간": "2019~2024 기준일(4월 30일) · 유가 · 코스닥 영업회사 · 24개월 안 상장폐지 사슬 진입 · 규칙은 2015~2018 로만 정함",
    "기본": 1.81, "작전주꼴": {"걸린쪽": 14.1, "남은쪽": 0.72, "거름": 8.2, "피함": 64},
    "상폐절차": 56, "보고서없음": "30관측 중 5", "자금조달잦음": 1.4, "코넥스": 8.9, "외국": 6.0,
    "한계": "주가(우하향)는 재지 않았다 · 유가 대형사의 갑작스런 감사의견 거절은 38% 만 잡는다 · 최근 해일수록 약하다(2023~24 재현 59~60%)",
}
OUT = os.path.join(K.DIR, "공시위험.json")


def market_before(f, D):
    i = bisect.bisect_right(f["Id"], D)
    if i == 0:
        return None
    return collections.Counter(f["Im"][max(0, i - 5):i]).most_common(1)[0][0]


def hit_rows(f, cats, lo, D):
    """창 안에서 그 범주로 분류된 원본 공시(정정 · 첨부 재제출 제외) — [날짜, 제목, 접수번호]"""
    out = collections.defaultdict(list)
    for r in f["rows"]:
        d = r["rcept_dt"]
        if not (lo < d <= D) or K.norm(r["report_nm"])[1]:
            continue
        cs = set(K.classify(r["report_nm"], r["flr_nm"]) or ())
        for c in cats & cs:
            out[c].append([d, K.norm(r["report_nm"])[0], r["rcept_no"]])
    for v in out.values():
        v.sort(reverse=True)
    return out


# 호재기업 점수 v3 의 희석 · 부실 범주(시너지.RISK_DIL · RISK_BAD 와 같다 — tests/test_시너지_서버.py 가 맞춰 본다)
S12_CATS = ("CB발행", "BW발행", "EB발행", "유상증자", "제3자배정",
            "회생절차", "파산신청", "감사의견비적정", "관리종목_사유", "관리종목_우려", "실질심사", "상폐우려", "횡령배임",
            "불성실_지정", "자본잠식", "보고서지연", "투자주의환기")


def last_signals(f, lo_date, D, cats):
    """(lo_date, D] 안 원본 공시의 범주별 {"n": 서로 다른 날 수, "last": 마지막 날} — cats 만(S.count_signals 와 같은 창 · 같은 셈)."""
    lo = bisect.bisect_right(f["evd"], lo_date)
    hi = bisect.bisect_right(f["evd"], D)
    days = collections.defaultdict(set)
    for i in range(lo, hi):
        dte, s = f["ev"][i]
        for c in s:
            if c in cats:
                days[c].add(dte)
    return {c: {"n": len(v), "last": max(v)} for c, v in days.items()}


def s12_all(rows, D):
    """{종목코드: {범주: {"n", "last"}}} — 2026-10-20 호재기업 점수 v3 위험 표지(시너지.risk_flags)용 12개월 셈(D−12개월, D].
    judge_all · 묶음과 상관없이 종목코드가 있는 모든 공시를 센다 — 도구/시너지_백테스트._risk_info 와 같은 규칙(접수번호 중복 제거 ·
    정정 · 첨부 재제출 제외 · '자회사사항'만인 공시 제외). codes 에 안 넣는 까닭: codes 는 '본표본을 잰 회사' 목록이라 다른 화면이 그렇게 읽는다."""
    ev = collections.defaultdict(list)
    for v in rows.values():
        for r in v:
            sc = (r.get("stock_code") or "").strip()
            if not sc or K.norm(r["report_nm"])[1]:
                continue
            cs = K.classify(r["report_nm"], r.get("flr_nm"))
            if not cs or cs == ("자회사사항",):
                continue
            ev[sc].append((r["rcept_dt"], frozenset(cs)))
    lo, out = S.shift(D, -12), {}
    for sc, v in ev.items():
        v.sort(key=lambda e: e[0])
        x = last_signals({"ev": v, "evd": [e[0] for e in v]}, lo, D, S12_CATS)
        if x:
            out[sc] = x
    return out


def main():
    t0 = time.time()
    rows = K.load_rows()
    D = max(r["rcept_dt"] for v in rows.values() for r in v)
    V = K.judge_all(rows, D)
    info = S.prepare(rows, V)
    Dm24, Dm13 = S.shift(D, -24), S.shift(D, -13)
    codes, cnt = {}, collections.Counter()
    for cc, f in info.items():
        code = f["code"]
        if not code or f["유형"] not in ("상장중", "상폐절차중"):
            continue
        mk = market_before(f, D)
        grp = ("스팩" if f["spac_name"] or (f["spac_end"] and D <= f["spac_end"]) else "리츠펀드" if f["fund"] else
               "외국" if f["foreign"] else "코넥스" if mk == "코넥스" else "본표본" if mk else "시장 불명")
        rec = {"name": f["name"], "market": mk, "group": grp, "level": None}
        if grp == "본표본":
            proc = S.in_process_at(f, D)
            last_a = max((a for a in f["A"] if a <= D), default=None)
            s24 = S.count_signals(f, Dm24, D)
            hits = [(c, s24.get(c, 0), t) for c, t in RULE if s24.get(c, 0) >= t]
            div = s24.get("현금배당", 0) > 0
            ref = [(c, s24.get(c, 0)) for c in REF if s24.get(c, 0) > 0]
            rows_ = hit_rows(f, set(c for c, _, _ in hits) | set(c for c, _ in ref), Dm24, D)
            level = ("상폐 절차" if proc else "보고서 없음" if not (last_a and last_a > Dm13) else
                     ("작전주 꼴" if not div else "자금조달 잦음") if hits else None)
            rec.update(level=level, proc=proc, last_a=last_a, div=div,
                       hits=[{"cat": c, "name": NAME[c], "days": n, "need": t, "rows": rows_.get(c, [])[:8]} for c, n, t in hits],
                       ref=[{"cat": c, "days": n, "rows": rows_.get(c, [])[:4]} for c, n in ref])
        cnt[rec["level"] or (grp if grp != "본표본" else "해당 없음")] += 1
        codes[code] = rec
    res = {"기준일": D, "만든때": time.strftime("%Y-%m-%d %H:%M"), "규칙": [[c, NAME[c], t] for c, t in RULE],
           "evidence": EVIDENCE, "수": dict(cnt), "codes": codes,
           "s12": s12_all(rows, D)}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)
    os.replace(tmp, OUT)
    print("공시위험 — 기준일 %s · %s · %.0f초" % (D, dict(cnt), time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
