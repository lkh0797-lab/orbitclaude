# -*- coding: utf-8 -*-
"""
사망_검증 독립 재계산(반박 검증용, 2026-10-06) — 작전주_사망_검증.py · 공시분류.py 의 표본 · 신호 코드를 쓰지 않고
jsonl 을 직접 읽어 핵심 숫자 셋(기본 사망률 · 강한 신호 배수 · 표본 밖 재현율)을 다시 낸다.
사망 사건일만 공시분류.py 의 판정 산출물(.cache/공시목록/분류_점검.json 의 사망목록 · 상폐절차중목록)을 쓴다.
DART 호출 0, 파일 쓰기 0(표준출력만).

재현: python "G:/내 드라이브/Claude/주식/기업추적/도구/사망_검증_독립재계산.py"      (약 1~2분)

독립 구현한 것
  그날 상장 중: D(04-30) 전 거래소공시(접수번호 9번째 8/9/6) 있음 · (지금 Y/K/N 이거나 마지막 거래소공시 ≥ D)
  시장: D 전 마지막 거래소공시 5건 접수번호 다수결 / 묶음: 스팩(이름 또는 D 이후 'SPAC·기업인수목적회사' 제목) · 펀드(이름) · 외국(9xxxxx) · 코넥스
  뺄 것: D-13개월<사업보고서≤D 없음 · 사건일≤D · D 까지의 거래소 '상장폐지 사유·결정·정리매매·가처분·파산선고' 가 해소 없이 540일 안
  신호: 머리말([기재정정] 등) 붙은 재제출 · 자회사 사항 제외, 같은 신호는 같은 날 1 → 24개월 안 서로 다른 날 수(제목 정규식은 이 파일 것)
"""
import bisect, calendar, collections, datetime as dt, glob, json, os, random, re

BASE = r"G:/내 드라이브/Claude/주식/기업추적"
DIR = BASE + "/.cache/공시목록"
EXCH = {"유가증권시장본부", "코스닥시장본부", "코넥스시장"}


def shift(s, m):
    y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    y2, m2 = divmod(y * 12 + mo - 1 + m, 12)
    m2 += 1
    return "%04d%02d%02d" % (y2, m2, min(d, calendar.monthrange(y2, m2)[1]))


def day(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


PFX = re.compile(r"^\s*(\[[^\]]*\]\s*)+")
SUB = re.compile(r"\((자회사|종속회사)의?주요경영사항\)")


def key(t):
    return re.sub(r"\s", "", PFX.sub("", t))


SIG = {k: (re.compile(a), re.compile(b) if b else None) for k, (a, b) in {
    "CB": (r"전환사채(권)?발행결정", r"철회|취소|부결|만기전|발행후|매수선택권"),
    "BW": (r"신주인수권부사채(권)?발행결정", r"철회|취소|부결|만기전|발행후|매수선택권"),
    "3자": (r"제3자배정", r"철회|미발행"),
    "최대주주": (r"^최대주주변경(?!을수반)|최대주주변경시\)", None),
    "경영권": (r"최대주주변경을수반하는주식양수도계약|경영권변경등에관한계약", r"해제|취소"),
    "유증": (r"유(무)?상증자결정", r"철회|취소|부결|최종발행가액|발행가액결정"),
    "대여": (r"금전대여결정", None),
    "풋": (r"발행후만기전사채취득|자기(전환|신주인수권부|교환)사채만기전취득", None),
    "관리": (r"관리종목지정사유발생|내부결산시점관리종목지정|관리종목지정사유추가", r"우선주|해소|해제|우려"),
    "파산신청": (r"파산(선고)?신청", r"출자법인|피보증"),
    "배당": (r"현금ㆍ현물배당결정", None),
}.items()}
DEC = re.compile(r"상장폐지사유발생|상장페지사유발생|상장폐지결정|정리매매|상장폐지.{0,6}이의신청|상장폐지관련|상장폐지기준해당|상장폐지.{0,8}(효력정지|가처분)|파산선고")
DEC_X = re.compile(r"우려|해소|미해당|미진행|우선주|신주인수권|자진|이전상장|기각|취하|파산선고신청|상장유예")
RESET = re.compile(r"사유해소|상장유지|매매거래정지해제|기준미해당|실질심사대상제외|사유미해당")
SPAC_N = re.compile(r"스팩|기업인수목적|SPAC", re.I)
SPAC_T = re.compile(r"기업인수목적회사|SPAC")
FUND_N = re.compile(r"선박투자|부동산투자회사|리츠|투자회사|해외자원개발|특별자산|맥쿼리인프라|발해인프라|인프라투융자")   # 연구와 같은 정규식(메리츠 · 블리츠도 걸린다)
CB_RULE = [("BW", 3), ("3자", 3), ("최대주주", 3), ("경영권", 2), ("유증", 3), ("대여", 3), ("풋", 3), ("CB", 3)]


def load():
    rows, seen = collections.defaultdict(list), set()
    for kd in ("I", "B", "A001"):
        for p in sorted(glob.glob(os.path.join(DIR, kd + "_*.jsonl"))):
            for line in open(p, encoding="utf-8"):
                x = json.loads(line)
                if x["rcept_no"] in seen:
                    continue
                seen.add(x["rcept_no"])
                rows[x["corp_code"]].append((x["rcept_dt"], x["rcept_no"], kd, x.get("report_nm") or "", x.get("flr_nm") or "",
                                             x.get("corp_name") or "", (x.get("stock_code") or "").strip(), x.get("corp_cls") or ""))
    for v in rows.values():
        v.sort()
    return rows


def build(rows):
    chk = json.load(open(DIR + "/분류_점검.json", encoding="utf-8"))
    death = {r[1]: (r[0], r[5]) for r in chk["사망목록"]}
    death.update({r[1]: (r[0], "상폐절차중") for r in chk["상폐절차중목록"]})
    old = set()
    for line in open(BASE + "/종목.txt", encoding="utf-8"):
        m = re.match(r"\s*([0-9A-Z]{6})\b", line)
        if m:
            old.add(m.group(1))
    comp = {}
    for cc, v in rows.items():
        code = v[-1][6]
        I = [r for r in v if r[2] == "I" and r[1][8] in "896"]
        if not code or not I:
            continue
        evl, decs, resets, spac_t = set(), [], [], []
        for r in v:
            k = key(r[3])
            if DEC.search(k) and not DEC_X.search(k) and not SUB.search(k) and (r[4] in EXCH or re.search(r"가처분|효력정지|파산선고", k)):
                decs.append(r[0])
            if r[4] in EXCH and RESET.search(k) and not re.search(r"정리매매|미해소", k):
                resets.append(r[0])
            if SPAC_T.search(k):
                spac_t.append(r[0])
            if PFX.match(r[3]) or SUB.search(k):
                continue
            for s, (a, b) in SIG.items():
                if a.search(k) and not (b and b.search(k)):
                    evl.add((r[0], s))
        evl = sorted(evl)
        E, Et = death.get(cc, (None, None))
        comp[cc] = dict(name=v[-1][5], code=code, listed=v[-1][7] in ("Y", "K", "N"), Id=[r[0] for r in I], Im=[r[1][8] for r in I],
                        A=sorted(r[0] for r in v if r[2] == "A001"), ev=evl, evd=[e[0] for e in evl], decs=sorted(decs),
                        resets=sorted(resets), spac_last=max(spac_t) if spac_t else None, E=E, Et=Et, old=code in old)
    return comp


def in_proc(f, D):
    ds = [d for d in f["decs"] if shift(D, -36) <= d <= D]
    if not ds:
        return False
    rs = [d for d in f["resets"] if shift(D, -36) <= d <= D]
    if rs and rs[-1] >= ds[-1]:
        return False
    return (day(D) - day(ds[-1])).days <= 540


def panel(comp):
    out = []
    for y in range(2015, 2026):
        D = "%d0430" % y
        for cc, f in comp.items():
            i = bisect.bisect_right(f["Id"], D)
            if i == 0 or (not f["listed"] and f["Id"][-1] < D):
                continue
            mk = collections.Counter(f["Im"][max(0, i - 5):i]).most_common(1)[0][0]
            spac = bool(SPAC_N.search(f["name"])) or (f["spac_last"] is not None and f["spac_last"] >= D)
            grp = "스팩" if spac else "펀드" if FUND_N.search(f["name"]) else "외국" if f["code"].startswith("9") else "코넥스" if mk == "6" else "본"
            E = f["E"]
            ex = None
            if not any(shift(D, -13) < a <= D for a in f["A"]):
                ex = "A없음"
            elif E and E <= D:
                ex = "이미"
            elif in_proc(f, D):
                ex = "절차중"
            a, b = bisect.bisect_right(f["evd"], shift(D, -24)), bisect.bisect_right(f["evd"], D)
            out.append(dict(cc=cc, y=y, grp=grp, mk=mk, ex=ex, E=E, Et=f["Et"], old=f["old"],
                            y24=(1 if (E and D < E <= shift(D, 24)) else 0) if y <= 2024 else None,
                            y12=1 if (E and D < E <= shift(D, 12)) else 0,
                            s24=collections.Counter(s for d, s in f["ev"][a:b])))
    return out


def rate(sub, flag, yk="y24"):
    N, Dd = len(sub), sum(o[yk] for o in sub)
    a = [o for o in sub if flag(o)]
    fn, fd = len(a), sum(o[yk] for o in a)
    return "걸린 %d · 걸린사망 %d · 정밀 %.2f%% · lift %.2f · 재현 %.1f%% · 버림 %.2f%% · 남은 사망률 %.2f%% (기본 %.2f%%, 관측 %d · 사망 %d)" % (
        fn, fd, 100 * fd / fn, (fd / fn) / (Dd / N), 100 * fd / Dd, 100 * fn / N, 100 * (Dd - fd) / (N - fn), 100 * Dd / N, N, Dd)


def main():
    rows = load()
    comp = build(rows)
    P = panel(comp)
    main_ = [o for o in P if o["grp"] == "본" and not o["ex"]]
    m24 = [o for o in main_ if o["y"] <= 2024]
    n, d = len(m24), sum(o["y24"] for o in m24)
    print("① 기본 사망률(본표본, 2015~2024, 24개월): 관측 %d · 사망 %d · 회사 %d → %.2f%%" % (n, d, len(set(o["cc"] for o in m24)), 100 * d / n))
    print("   12개월(2015~2025): %.2f%%" % (100 * sum(o["y12"] for o in main_) / len(main_)))
    print("   엄격(사망만):", "%.2f%%" % (100 * sum(o["y24"] for o in m24 if o["Et"] == "사망") / sum(1 for o in m24 if not (o["y24"] and o["Et"] != "사망"))))
    print("② 신호 배수(2015~2024, 24개월):")
    for s, t in (("파산신청", 1), ("3자", 3), ("관리", 1), ("CB", 3), ("유증", 3), ("CB", 1), ("배당", 1)):
        print("   %s≥%d: %s" % (s, t, rate(m24, lambda o: o["s24"].get(s, 0) >= t)))
    f = lambda o: any(o["s24"].get(s, 0) >= t for s, t in CB_RULE)
    te = [o for o in m24 if o["y"] >= 2019]
    print("③ C_B 표본 밖(2019~2024):", rate(te, f))
    print("   2020~2024:", rate([o for o in te if o["y"] >= 2020], f))
    print("   엄격(상폐절차중 · 약 · 추정 사건 뺌):", rate([o for o in te if not (o["y24"] and o["Et"] != "사망")], f))
    for mk, nm in (("8", "유가"), ("9", "코스닥")):
        print("   %s: %s" % (nm, rate([o for o in te if o["mk"] == mk], f)))
    near = [o for o in te if o["y24"] and (day(o["E"]) - day("%d0430" % o["y"])).days <= 365]
    far = [o for o in te if o["y24"] and (day(o["E"]) - day("%d0430" % o["y"])).days > 365]
    print("   앞섬별 재현: 1년 안 %d건 %.0f%% · 1~2년 %d건 %.0f%%" % (len(near), 100 * sum(map(f, near)) / len(near), len(far), 100 * sum(map(f, far)) / len(far)))
    dead = collections.defaultdict(list)
    for o in te:
        if o["y24"]:
            dead[o["cc"]].append(f(o))
    print("   회사 단위: 사망 %d곳 중 한 번이라도 걸림 %d · 모든 기준일에 걸림 %d" % (len(dead), sum(any(v) for v in dead.values()), sum(all(v) for v in dead.values())))
    by = collections.defaultdict(list)
    for o in te:
        by[o["cc"]].append(o)
    ccs, rnd, rec = sorted(by), random.Random(20261006), []
    for _ in range(1000):
        Dd = F = 0
        for c in rnd.choices(ccs, k=len(ccs)):
            for o in by[c]:
                if o["y24"]:
                    Dd += 1
                    F += f(o)
        rec.append(F / Dd)
    rec.sort()
    print("   재현 회사 단위 재표본 90%%: [%.1f%%, %.1f%%]" % (100 * rec[50], 100 * rec[949]))
    print("④ 뺀 것(본표본 후보, 2015~2024):", dict(collections.Counter(o["ex"] for o in P if o["grp"] == "본" and o["ex"] and o["y"] <= 2024)),
          "그중 24개월 사망:", dict(collections.Counter(o["ex"] for o in P if o["grp"] == "본" and o["ex"] and o["y"] <= 2024 and o["y24"])))
    im = [o for o in P if o["grp"] == "본" and o["ex"] == "이미" and o["y"] <= 2024]
    vis = sum(1 for o in im if in_proc(comp[o["cc"]], "%d0430" % o["y"]))
    pr = [o for o in P if o["grp"] == "본" and o["ex"] == "절차중" and o["y"] <= 2024]
    print("   '이미사망' %d 중 D 시점 공시로 절차중이 보이는 것 %d → D 에 절차중으로 보이는 관측의 사망 비율 ≈ (%d+%d)/(%d+%d) = %.0f%%" % (
        len(im), vis, vis, sum(o["y24"] for o in pr), vis, len(pr), 100 * (vis + sum(o["y24"] for o in pr)) / (vis + len(pr))))
    fund_bad = [o for o in P if o["grp"] == "펀드" and re.search(r"메리츠|블리츠", comp[o["cc"]]["name"])]
    print("⑤ 펀드 정규식 오탐(메리츠 · 블리츠웨이): 관측 %d · 사망 %d" % (len(fund_bad), sum(o["y24"] or 0 for o in fund_bad)))
    oi = [o for o in m24 if o["old"]]
    print("⑥ 종목.txt 안: 관측 %d · 사망 %d (%.2f%%) / 밖: 관측 %d · 사망 %d" % (len(oi), sum(o["y24"] for o in oi), 100 * sum(o["y24"] for o in oi) / len(oi),
                                                                   n - len(oi), d - sum(o["y24"] for o in oi)))
    # ⑦ 상폐절차중을 사망으로 센 것의 되돌림 위험: 2019~2023 에 거래소 '상장폐지 사유' 를 받은 유가 · 코스닥 영업회사(스팩 · 펀드 제외)의 지금 상태
    chk = json.load(open(DIR + "/분류_점검.json", encoding="utf-8"))
    typ = {r[1]: r[5] for r in chk["사망목록"]}
    typ.update({r[1]: "상폐절차중" for r in chk["상폐절차중목록"]})
    typ.update({r[1]: r[5] for r in chk["비사망_상장종료목록"]})
    rx = re.compile(r"상장폐지사유발생|상장폐지관련|상장폐지기준해당")
    rxx = re.compile(r"우려|해소|미해당|미진행|우선주|신주인수권|자진|상장유예")
    st = collections.Counter()
    for cc, f in comp.items():
        if SPAC_N.search(f["name"]) or FUND_N.search(f["name"]):
            continue
        ev = [r for r in rows[cc] if r[4] in ("유가증권시장본부", "코스닥시장본부") and "20190101" <= r[0] <= "20231231"
              and rx.search(key(r[3])) and not rxx.search(key(r[3]))]
        if ev:
            t = typ.get(cc, "상장중" if f["listed"] else "?")
            st["사망" if t.startswith("사망") else t] += 1
    print("⑦ 2019~2023 거래소 상장폐지 사유를 받은 영업회사의 지금 상태:", dict(st),
          "→ 결론 난 곳 중 생존 %.0f%%" % (100 * st["상장중"] / (st["상장중"] + st["사망"])))


if __name__ == "__main__":
    main()
