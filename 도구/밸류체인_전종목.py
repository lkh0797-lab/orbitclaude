# -*- coding: utf-8 -*-
"""
밸류체인 캐시를 전 종목에 미리 만든다 (2026-10-04) — 그물망(같은 고객을 적은 회사 · 나를 매입처로 적은 회사)은 모든 회사의 캐시가 있어야 보인다.
서버._vc_company 를 그대로 부른다(.cache/밸류체인/{코드}.json, 최신 접수번호로 묶음). 사업보고서 「사업의 내용」을 회사당 8~15건 읽는다.

실행: python 도구/밸류체인_전종목.py        (처음 30분 안팎 — Google Drive 입출력)
"""
import os
import sys
import time
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("srv", os.path.join(os.path.dirname(HERE), "서버.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def main():
    S.build_index()
    cos = list(S.INDEX["companies"])
    t0, done, ok = time.time(), 0, 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(S._vc_company, c): c for c in cos}
        for f in as_completed(futs):
            done += 1
            try:
                d = f.result()
                ok += bool(d and d.get("years"))
            except Exception as e:
                print("  실패 %s: %s" % (futs[f]["name"], e), flush=True)
            if done % 50 == 0:
                print("  %d/%d 회사 · 뽑힘 %d · %.0f초" % (done, len(cos), ok, time.time() - t0), flush=True)
    print("끝 — %d곳 중 %d곳 뽑힘, %.0f초" % (len(cos), ok, time.time() - t0))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
