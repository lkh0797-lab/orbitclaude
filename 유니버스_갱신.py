# -*- coding: utf-8 -*-
"""
유니버스 갱신 — 시총 스크리닝 엑셀을 읽어 종목.txt 를 다시 쓴다.

기본 소스: G:\\내 드라이브\\Claude\\수출입통계트래킹\\개별종목_시총1500억이상_TOP500_*.xlsx
(가장 최신 날짜 파일을 자동으로 고른다)

사용법:
    python 유니버스_갱신.py                 # 전체
    python 유니버스_갱신.py --top 100       # 시총 상위 100만
    python 유니버스_갱신.py --market KOSPI  # 시장 필터
    python 유니버스_갱신.py --xlsx "경로.xlsx"

종목.txt 는 시총 큰 순으로 쓴다. 수집 도중 한도가 걸려도
중요한 종목부터 확보되도록.
"""
import os
import re
import sys
import glob

import openpyxl

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import 설정                                     # noqa: E402

# 소스 엑셀 경로는 사람마다 다르다. 환경변수 UNIVERSE_XLSX 또는
# 경로설정.txt 에서 읽는다 (둘 다 git 에 올리지 않는다).
DEFAULT_GLOB = 설정.get("UNIVERSE_XLSX",
                        os.path.join(BASE, "개별종목_시총*.xlsx"))


def pick_source():
    hits = sorted(glob.glob(DEFAULT_GLOB))
    if not hits:
        return None
    return hits[-1]          # 파일명이 _YYYYMMDD 로 끝나 사전순 = 최신순


PREF_NAME_RE = re.compile(r"\d*우B?$")


def is_preferred(name, code):
    """우선주 판별. 이름이 '…우' / '…우B' / '…2우B' 로 끝나고
    종목코드 끝자리가 0이 아니면 우선주로 본다. 둘 다 맞아야 한다 —
    이름만 보면 보통주 상호를 잘못 걸러낼 수 있다."""
    return bool(PREF_NAME_RE.search(name.strip())) and not code.endswith("0")


def read_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows, header_seen = [], False
    for row in ws.iter_rows(values_only=True):
        cells = ["" if c is None else str(c).strip() for c in row]
        if not header_seen:
            if "종목코드" in cells:
                header_seen = True
                cols = {name: i for i, name in enumerate(cells)}
            continue
        def get(name):
            i = cols.get(name)
            return cells[i] if i is not None and i < len(cells) else ""
        code = re.sub(r"\D", "", get("종목코드")).zfill(6)
        if len(code) != 6 or code == "000000":
            continue
        try:
            cap = float(re.sub(r"[^\d.]", "", get("시총(억원)") or "0") or 0)
        except ValueError:
            cap = 0.0
        rows.append({"code": code, "name": get("종목명"),
                     "market": get("시장"), "cap": cap})
    wb.close()
    return rows


def main():
    args = list(sys.argv[1:])

    def pop(flag, cast=str, default=None):
        if flag not in args:
            return default
        k = args.index(flag)
        v = args[k + 1]
        del args[k:k + 2]
        return cast(v)

    top = pop("--top", int)
    market = pop("--market")
    keep_pref = "--keep-preferred" in args
    if keep_pref:
        args.remove("--keep-preferred")
    xlsx = pop("--xlsx") or pick_source()

    if not xlsx or not os.path.exists(xlsx):
        print("소스 엑셀을 찾지 못했습니다. --xlsx 로 경로를 지정하세요.")
        print("찾아본 곳: " + DEFAULT_GLOB)
        return 1

    rows = read_rows(xlsx)
    if market:
        rows = [r for r in rows if r["market"].upper() == market.upper()]

    # 우선주는 DART 에 별도 고유번호가 없다. 공시 주체가 보통주와 같은 법인이라
    # 받아봐야 같은 보고서고, 종목코드로는 조회 자체가 안 된다. 기본으로 뺀다.
    dropped_pref = []
    if not keep_pref:
        keep = []
        for r in rows:
            if is_preferred(r["name"], r["code"]):
                dropped_pref.append(r)
            else:
                keep.append(r)
        rows = keep

    rows.sort(key=lambda r: -r["cap"])

    # 같은 종목코드가 두 번 나오면 첫 번째(시총 큰 쪽)만
    seen, uniq = set(), []
    for r in rows:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        uniq.append(r)
    if top:
        uniq = uniq[:top]

    out = os.path.join(BASE, "종목.txt")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# 기업추적 대상 종목 — 6자리 종목코드, 한 줄에 하나. '#' 뒤는 메모.\n")
        fh.write("# 자동 생성: 유니버스_갱신.py\n")
        fh.write("# 소스: %s\n" % os.path.basename(xlsx))
        if market:
            fh.write("# 시장 필터: %s\n" % market)
        fh.write("# 시총 큰 순. 수집 한도가 걸려도 위쪽부터 확보된다.\n")
        fh.write("#\n")
        fh.write("# 기본 수집기간 10년. 늘리려면: 기업추적_실행.bat --years 15\n\n")
        for i, r in enumerate(uniq, 1):
            fh.write("%s   # %3d위 %s (%s, 시총 %s억)\n"
                     % (r["code"], i, r["name"], r["market"],
                        format(int(r["cap"]), ",")))

    print("소스: %s" % xlsx)
    if dropped_pref:
        names = ", ".join(r["name"] for r in dropped_pref[:5])
        more = " 외 %d" % (len(dropped_pref) - 5) if len(dropped_pref) > 5 else ""
        print("우선주 %d종목 제외 (DART 고유번호 없음): %s%s"
              % (len(dropped_pref), names, more))
    print("종목.txt 갱신 — %d종목" % len(uniq))
    if uniq:
        print("  1위 %s (%s)  ...  %d위 %s (%s)"
              % (uniq[0]["name"], uniq[0]["code"],
                 len(uniq), uniq[-1]["name"], uniq[-1]["code"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
