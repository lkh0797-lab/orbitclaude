# -*- coding: utf-8 -*-
"""
증권사 리포트 채널 받기 — 뷰어가 하루 몇 번 부르고, 손으로도 돌린다.

  python 도구/리포트_수집.py            # 채널마다 지난번 뒤의 새 글(처음이면 최근 180일)
  python 도구/리포트_수집.py --list     # 읽을 채널 목록만
  python 도구/리포트_수집.py --days 365 # 처음 받을 때 더 오래 전까지

로그인(도구/텔레그램_로그인.py)이 먼저다. 받은 글은 .cache/리포트/YYYY-MM.jsonl.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import 리포트 as R  # noqa: E402


def main(argv):
    days = 180
    if "--days" in argv:
        days = int(argv[argv.index("--days") + 1])
    if not R.session_exists():
        print("텔레그램 로그인 세션이 없습니다 — 터미널에서 python 도구/텔레그램_로그인.py 를 먼저 한 번 돌리세요.")
        return 2
    t0 = time.time()
    n = R.collect(days=days, list_only="--list" in argv)
    if "--list" not in argv:
        print("끝 — 새 글 %d건, %.0f초" % (n, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
