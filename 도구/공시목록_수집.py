# -*- coding: utf-8 -*-
"""
공시 목록 받기 — 상장폐지 회사까지 들어간 '그 시점' 표본을 DART 만으로 만들기 위한 바닥 자료 (2026-10-05).

OpenDART 공시검색(list.json)을 분기마다 끝 쪽까지 받는다. 회사를 정하지 않고 받으므로 그 분기에 공시를 낸 모든 회사 —
지금은 상장폐지된 회사(corp_cls 가 'E' 로 바뀌었지만 stock_code 는 남는다)까지 — 가 들어간다.

  B  주요사항보고    — 전환사채 · 신주인수권부사채 · 유상증자 · 감자 · 회생절차 · 해산사유 · 영업정지 …
  I  거래소공시      — 관리종목 · 거래정지 · 상장폐지 · 투자주의 · 불성실공시 · 최대주주변경 · 횡령배임 · 감사의견 …
  A001 사업보고서    — 그해 상장사로 사업보고서를 냈나(그 시점 표본)

  python 도구/공시목록_수집.py                 # 2013Q1 ~ 지금, B · I · A001 (이미 받은 분기는 건너뜀)
  python 도구/공시목록_수집.py --from 2015 --types I
결과: .cache/공시목록/<종류>_<YYYY>Q<n>.jsonl (한 줄 = 공시 하나: rcept_no · rcept_dt · corp_code · corp_name · stock_code · corp_cls · report_nm · flr_nm)
API 키는 출력 · 로그에 찍지 않는다. 요청 사이 0.35초, 하루 한도(약 2만 건)를 넘지 않게 --max-calls 로 멈춘다.
"""
import datetime as dt
import json
import os
import sys
import time

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import 재무 as F  # noqa: E402

OUT = os.path.join(BASE, ".cache", "공시목록")
URL = "https://opendart.fss.or.kr/api/list.json"
KEEP = ("rcept_no", "rcept_dt", "corp_code", "corp_name", "stock_code", "corp_cls", "report_nm", "flr_nm")
TYPES = {"B": {"pblntf_ty": "B"}, "I": {"pblntf_ty": "I"}, "A001": {"pblntf_detail_ty": "A001"}}


def quarters(y0, today):
    y, q = y0, 1
    while dt.date(y, (q - 1) * 3 + 1, 1) <= today:
        a = dt.date(y, (q - 1) * 3 + 1, 1)
        b = (dt.date(y + (q == 4), (q % 4) * 3 + 1, 1) - dt.timedelta(days=1))
        yield "%dQ%d" % (y, q), a, min(b, today)
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)


def fetch(params, calls):
    for k in range(5):
        try:
            calls[0] += 1
            r = requests.get(URL, params=params, timeout=40)
            d = r.json()
            st = d.get("status")
            if st in ("000", "013"):          # 013 = 조회된 데이터 없음
                return d
            if st == "020":                   # 요청 제한 초과
                raise RuntimeError("DART 요청 한도 초과(020) — 내일 이어서")
            time.sleep(2 + k * 3)
        except RuntimeError:
            raise
        except Exception:
            time.sleep(2 + k * 3)
    raise RuntimeError("DART 응답 실패: %s" % params.get("bgn_de"))


def main(argv):
    y0 = int(argv[argv.index("--from") + 1]) if "--from" in argv else 2013
    types = argv[argv.index("--types") + 1].split(",") if "--types" in argv else ["I", "B", "A001"]
    max_calls = int(argv[argv.index("--max-calls") + 1]) if "--max-calls" in argv else 15000
    os.makedirs(OUT, exist_ok=True)
    today = dt.date.today()
    calls = [0]
    t0 = time.time()
    for ty in types:
        for lab, a, b in quarters(y0, today):
            path = os.path.join(OUT, "%s_%s.jsonl" % (ty, lab))
            done = path + ".done"
            current = b >= today - dt.timedelta(days=1)
            if os.path.exists(done) and not current:
                continue
            rows, page, total = [], 1, None
            while True:
                if calls[0] >= max_calls:
                    print("멈춤 — 호출 %d번(한도 %d). 다시 돌리면 이어서 받는다." % (calls[0], max_calls), flush=True)
                    return 0
                p = dict(TYPES[ty], crtfc_key=F.API_KEY, bgn_de=a.strftime("%Y%m%d"), end_de=b.strftime("%Y%m%d"),
                         page_no=page, page_count=100, last_reprt_at="N")
                d = fetch(p, calls)
                total = int(d.get("total_page") or 0)
                rows += [{k: x.get(k) for k in KEEP} for x in (d.get("list") or [])]
                time.sleep(0.35)
                if page >= total or not d.get("list"):
                    break
                page += 1
            with open(path, "w", encoding="utf-8") as fh:
                for x in rows:
                    fh.write(json.dumps(x, ensure_ascii=False) + "\n")
            if not current:
                open(done, "w").close()
            print("%s %s — %d건 · %d쪽 · 누적 호출 %d · %.0f초" % (ty, lab, len(rows), total, calls[0], time.time() - t0), flush=True)
    print("끝 — 호출 %d번, %.0f초" % (calls[0], time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
