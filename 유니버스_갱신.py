# -*- coding: utf-8 -*-
"""
유니버스 갱신 — 시총 스크리닝 엑셀을 읽어 종목.txt 를 다시 쓴다.

기본 소스: G:\\내 드라이브\\Claude\\수출입통계트래킹\\개별종목_시총1500억이상_TOP500_*.xlsx
(가장 최신 날짜 파일을 자동으로 고른다)

소스 두 가지:
  naver (기본) — 네이버 시총 순위 API. 당일 시세 기준, 전 종목까지 받을 수 있다.
  xlsx         — 시총 스크리닝 엑셀 스냅샷.

사용법:
    python 유니버스_갱신.py --top 800        # 시총 상위 800 (기본 소스: naver)
    python 유니버스_갱신.py --market KOSPI   # 시장 필터
    python 유니버스_갱신.py --source xlsx    # 엑셀 스냅샷에서
    python 유니버스_갱신.py --source xlsx --xlsx "경로.xlsx"

우선주와 스팩은 기본으로 뺀다 (--keep-preferred / --keep-spac 로 유지).

종목.txt 는 시총 큰 순으로 쓴다. 수집 도중 한도가 걸려도
중요한 종목부터 확보되도록.
"""
import os
import re
import sys
import glob
import time
import datetime as dt

import openpyxl

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import 설정                                     # noqa: E402

# 소스 엑셀 경로는 사람마다 다르다. 환경변수 UNIVERSE_XLSX 또는
# 경로설정.txt 에서 읽는다 (둘 다 git 에 올리지 않는다).
DEFAULT_GLOB = 설정.get("UNIVERSE_XLSX",
                        os.path.join(BASE, "개별종목_시총*.xlsx"))


NAVER_MV = "https://m.stock.naver.com/api/stocks/marketValue/%s"
SPAC_RE = re.compile(r"스팩|기업인수목적")

# 종목코드는 6자리. 2025년 이후 신규 상장분은 영문이 섞인다(0126Z0 삼성에피스홀딩스).
CODE_RE = re.compile(r"^[0-9][0-9A-Z]{5}$")

# 시총 순위 API 에는 ETF·ETN 이 함께 들어온다. DART 정기보고서가 없으니 뺀다.
ETF_RE = re.compile(
    r"^(KODEX|TIGER|RISE|SOL|ACE|PLUS|KOSEF|ARIRANG|HANARO|KBSTAR|KIWOOM|"
    r"TIMEFOLIO|VITA|WOORI|FOCUS|마이티|히어로즈|파워|마이다스|에셋플러스|"
    r"BNK|UNICORN|삼성|미래에셋)?\s*.*"
    r"(레버리지|인버스|선물|채권혼합|액티브|머니마켓|TOP\d|커버드콜|"
    r"ETN|합성 ?H|단일종목)")
ETF_PREFIX = re.compile(
    r"^(KODEX|TIGER|RISE|SOL|ACE|PLUS|KOSEF|ARIRANG|HANARO|KBSTAR|KIWOOM|"
    r"TIMEFOLIO|VITA|UNICORN|히어로즈|마이다스|에셋플러스)\b")


def is_fund(name):
    return bool(ETF_PREFIX.match(name) or ETF_RE.match(name))


def pick_source():
    hits = sorted(glob.glob(DEFAULT_GLOB))
    if not hits:
        return None
    return hits[-1]          # 파일명이 _YYYYMMDD 로 끝나 사전순 = 최신순


def fetch_naver(markets=("KOSPI", "KOSDAQ"), need=800):
    """네이버 시총 순위 API. 엑셀 스냅샷과 달리 당일 시세 기준이다."""
    import requests
    head = {"User-Agent": "Mozilla/5.0", "Referer": "https://m.stock.naver.com/"}
    rows = []
    for mk in markets:
        page = 1
        while True:
            r = requests.get(NAVER_MV % mk, timeout=30, headers=head,
                             params={"page": page, "pageSize": 100})
            r.raise_for_status()
            js = r.json()
            got = js.get("stocks") or []
            if not got:
                break
            for s in got:
                code = (s.get("itemCode") or "").strip().upper()
                name = (s.get("stockName") or "").strip()
                cap = re.sub(r"[^\d]", "", str(s.get("marketValue") or ""))
                if not CODE_RE.match(code) or not name:
                    continue
                if is_fund(name):
                    continue
                rows.append({"code": code, "name": name,
                             "market": mk, "cap": float(cap or 0)})
            # 두 시장을 합쳐 자르므로 각 시장에서 넉넉히 받아둔다
            if len(got) < 100 or page * 100 >= need + 400:
                break
            page += 1
            time.sleep(0.15)
    return rows


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
        code = re.sub(r"[^0-9A-Za-z]", "", get("종목코드")).upper()
        if len(code) == 5:
            code = "0" + code
        if not CODE_RE.match(code) or code == "000000":
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
    source = pop("--source", str, "naver")
    keep_pref = "--keep-preferred" in args
    if keep_pref:
        args.remove("--keep-preferred")
    keep_spac = "--keep-spac" in args
    if keep_spac:
        args.remove("--keep-spac")

    if source == "naver":
        markets = (market.upper(),) if market else ("KOSPI", "KOSDAQ")
        rows = fetch_naver(markets, top or 800)
        xlsx = "네이버 시총 순위 API (%s)" % dt.date.today().isoformat()
    else:
        xlsx = pop("--xlsx") or pick_source()
        if not xlsx or not os.path.exists(xlsx):
            print("소스 엑셀을 찾지 못했습니다. --xlsx 로 경로를 지정하세요.")
            print("찾아본 곳: " + DEFAULT_GLOB)
            return 1
        rows = read_rows(xlsx)

    dropped_spac = []
    if not keep_spac:
        keep = []
        for r in rows:
            (dropped_spac if SPAC_RE.search(r["name"]) else keep).append(r)
        rows = keep
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
    if dropped_spac:
        print("스팩 %d종목 제외" % len(dropped_spac))
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
