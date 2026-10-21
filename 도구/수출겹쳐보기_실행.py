# -*- coding: utf-8 -*-
"""수출 겹쳐보기 · 변곡점 레이더 만들기 — 뷰어가 자식 프로세스(64비트 BT_PY)로 부른다(2026-10-21, 주식3 max20 에서 옮김).

    py -3.13 -X utf8 도구/수출겹쳐보기_실행.py [--sector KEY ...] [--no-prices]

export_overlay.main 그대로 — 관세청 품목 수출 × DART 분기 실적 × 환율 × 주가(FinanceDataReader) → .cache/수출겹쳐보기/*.html.
캐시 .cache/export_overlay/(관세청 창 · DART 원장 · 주가 하루). 키: DATA_GO_KR_KEY = 기업추적 .env, DART = 설정.dart_api_key().
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from export_overlay import main as _main  # noqa: E402

if __name__ == "__main__":
    sys.exit(_main.main(sys.argv[1:]))
