# -*- coding: utf-8 -*-
"""
증권사 리포트 채널 받기 — 뷰어가 하루 몇 번 부르고, 손으로도 돌린다.

  python 도구/리포트_수집.py            # 채널마다 지난번 뒤의 새 글(처음이면 최근 1년 — 한 번에 다 못 받으면 다음 수집 때 거슬러 이어서)
  python 도구/리포트_수집.py --list     # 읽을 채널 목록만
  python 도구/리포트_수집.py --days 365 # 처음 받을 때 더 오래 전까지

로그인(도구/텔레그램_로그인.py)했으면 구독 채널 전부, 안 했으면 적어 둔 공개 채널을 웹 미리보기(t.me/s/이름)로. 받은 글은 .cache/리포트/YYYY-MM.jsonl.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import 리포트 as R  # noqa: E402


def main(argv):
    days = 365
    if "--days" in argv:
        days = int(argv[argv.index("--days") + 1])
    if not R.can_collect():
        print("받을 곳이 없습니다 — 로그인(python 도구/텔레그램_로그인.py)하거나, .env TELEGRAM_CHANNELS · 리포트_채널.txt 에 공개 채널 이름을 적으세요.")
        return 2
    t0 = time.time()
    n = R.collect(days=days, list_only="--list" in argv)
    if "--list" not in argv:
        print("끝 — 새 글 %d건, %.0f초" % (n, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
