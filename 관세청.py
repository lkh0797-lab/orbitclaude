# -*- coding: utf-8 -*-
"""
관세청 수출입실적 OpenAPI 4종 (공공데이터포털, apis.data.go.kr/1220000).

  총괄(시작, 끝)                     수출입총괄(GW)            /Newtrade/getNewtradeList
  세관별(시작, 끝, 세관구분=None)      세관별 수출입실적(GW)      /customstrade/getCustomstradeList
  품목국가별(시작, 끝, hs=, 국가=)      품목별 국가별 수출입실적(GW) /nitemtrade/getNitemtradeList
  시군구품목별(시작, 끝, hs6, 시도)     시군구별 품목별 수출입실적  /sigunguperprlstperacrs/getSigunguPerPrlstPerAcrs

- 시작·끝은 'YYYYMM'. 한 번에 1년까지만 조회되므로 12개월씩 나눠 부르고 이어 붙인다.
- 금액은 미화(USD): 수출 = 신고 FOB, 수입 = 과세가격 CIF. 중량은 순중량(kg).
- 매월 15일경 전월까지 정정·취하를 반영해 다시 쓴다 — 캐시는 끝난 달 7일, 이번·지난달 12시간.
- 인증키는 .env 의 DATA_GO_KR_KEY (설정.get). 키와 전체 요청 주소는 화면·로그에 남기지 않는다.
- 시도코드: '26.7.1부터 전남광주통합특별시 = 12, 그 전 광주 29 · 전남 46 (관세청 공지).

점검: python 관세청.py 점검
"""
import os
import sys
import json
import time
import hashlib
import datetime as dt
import xml.etree.ElementTree as ET

import requests

import 설정

BASE = "https://apis.data.go.kr/1220000"
EP = {
    "총괄": "/Newtrade/getNewtradeList",
    "세관별": "/customstrade/getCustomstradeList",
    "품목국가별": "/nitemtrade/getNitemtradeList",
    "시군구품목별": "/sigunguperprlstperacrs/getSigunguPerPrlstPerAcrs",
}
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "관세청")
FRESH_AFTER = 0.0     # 이 시각 전에 받은 최근 달(캐시 7일 이하) 응답은 버린다 — 매달 갱신이 '새 달 나오기 전 응답'을 안 쓰게
NUM_KEYS = {"expDlr", "impDlr", "expWgt", "impWgt", "balPayments", "expCnt", "impCnt",
            "expUsdAmt", "impUsdAmt", "cmtrBlncAmt"}


class 관세청오류(RuntimeError):
    pass


def _key():
    k = 설정.get("DATA_GO_KR_KEY")
    if not k:
        raise 관세청오류("DATA_GO_KR_KEY 가 없다 — .env 에 넣는다")
    return k


def _months(a, b):
    """'YYYYMM' 두 개 → 12개월 이하 구간들."""
    ya, ma, yb, mb = int(a[:4]), int(a[4:]), int(b[:4]), int(b[4:])
    i, j = ya * 12 + ma - 1, yb * 12 + mb - 1
    out = []
    while i <= j:
        k = min(j, i + 11)
        out.append(("%04d%02d" % (i // 12, i % 12 + 1), "%04d%02d" % (k // 12, k % 12 + 1)))
        i = k + 1
    return out


def _ttl(end):
    """지난달보다 석 달 넘게 지난 달은 180일(이미 확정 — 매달 자동 갱신 때 다시 안 부른다),
    끝난 달이면 7일, 이번 달·지난달이면 12시간(15일경 다시 쓴다)."""
    lc = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    last_closed = lc.strftime("%Y%m")
    i = lc.year * 12 + lc.month - 1 - 3
    if end <= "%04d%02d" % (i // 12, i % 12 + 1):
        return 180 * 86400
    return 7 * 86400 if end < last_closed else 12 * 3600


def _parse(text):
    """XML → (항목 목록, 오류 설명 또는 None). 게이트웨이 오류(OpenAPI_ServiceResponse)도 읽는다."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], "XML 이 아니다: " + text[:120].replace("\n", " ")
    if root.tag == "OpenAPI_ServiceResponse":
        h = root.find(".//cmmMsgHeader")
        g = lambda t: (h.findtext(t) or "").strip() if h is not None else ""
        return [], "게이트웨이 %s %s" % (g("returnReasonCode"), g("returnAuthMsg") or g("errMsg"))
    code = (root.findtext(".//header/resultCode") or root.findtext(".//resultCode") or "").strip()
    msg = (root.findtext(".//header/resultMsg") or root.findtext(".//resultMsg") or "").strip()
    if code and code not in ("00", "0", "000", "INFO-000"):
        return [], "결과코드 %s %s" % (code, msg)
    items = []
    for it in root.iter("item"):
        d = {}
        for ch in it:
            v = (ch.text or "").strip()
            if ch.tag in NUM_KEYS:
                try:
                    v = float(v.replace(",", "")) if v else None
                except ValueError:
                    pass
            d[ch.tag] = v
        items.append(d)
    return items, None


def _get(name, params, ttl):
    os.makedirs(CACHE, exist_ok=True)
    tag = hashlib.md5(json.dumps([name, sorted(params.items())], ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    path = os.path.join(CACHE, "%s_%s.json" % (name, tag))
    if (os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl
            and not (ttl <= 7 * 86400 and os.path.getmtime(path) < FRESH_AFTER)):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    q = dict(params, serviceKey=_key())
    try:
        r = requests.get(BASE + EP[name], params=q, timeout=40)
    except requests.RequestException as e:
        raise 관세청오류("%s 연결 실패: %s" % (name, type(e).__name__))
    if r.status_code != 200:
        raise 관세청오류("%s HTTP %d %s" % (name, r.status_code, r.text[:120].replace("\n", " ")))
    items, err = _parse(r.text)
    if err:
        raise 관세청오류("%s %s" % (name, err))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False)
    time.sleep(0.1)
    return items


def _span(name, a, b, **extra):
    out = []
    for s, e in _months(a, b):
        p = {"strtYymm": s, "endYymm": e}
        p.update({k: v for k, v in extra.items() if v not in (None, "")})
        out += _get(name, p, _ttl(e))
    return out


def 총괄(시작, 끝):
    """월별 전체 수출입: year(기간) · expCnt · expDlr · impCnt · impDlr · balPayments."""
    return _span("총괄", 시작, 끝)


def 세관별(시작, 끝, 세관구분=None):
    """세관별: year · cstm(세관코드) · statCdCntnKor(세관명) · center(본부세관) · 건수·금액·무역수지."""
    return _span("세관별", 시작, 끝, cstmSgnYn=세관구분)


def 품목국가별(시작, 끝, hs=None, 국가=None):
    """품목(HS 2·4·6·10단위) × 국가(ISO 2자리): year · statCd · statCdCntnKor1 · hsCd · statKor · 중량·금액·무역수지.
    hs 와 국가 중 하나는 있어야 한다."""
    if not hs and not 국가:
        raise 관세청오류("품목국가별은 hs 나 국가 중 하나가 있어야 한다")
    return _span("품목국가별", 시작, 끝, hsSgn=hs, cntyCd=국가)


def 시군구품목별(시작, 끝, hs6, 시도):
    """시군구 × HS 6단위: priodTitle · sggNm · hsSgn · korePrlstNm · expCnt · expUsdAmt · impCnt · impUsdAmt · cmtrBlncAmt."""
    return _span("시군구품목별", 시작, 끝, HsSgn=hs6, sidoCd=시도)


def 점검():
    """네 API를 작은 조회로 한 번씩 부른다. 키가 막 발급된 개발계정은 반영까지 한두 시간 걸릴 수 있다."""
    today = dt.date.today()
    last = (today.replace(day=1) - dt.timedelta(days=45)).strftime("%Y%m")
    tests = [
        ("총괄", lambda: 총괄(last, last)),
        ("세관별", lambda: 세관별(last, last)),
        ("품목국가별", lambda: 품목국가별(last, last, hs="8504", 국가="US")),       # 변압기 · 미국
        ("시군구품목별", lambda: 시군구품목별(last, last, "850423", "31")),         # 변압기(1만 kVA 초과) · 울산
    ]
    ok = True
    for nm, f in tests:
        try:
            rows = f()
            print("  %-8s OK  %d행  %s" % (nm, len(rows), json.dumps(rows[0], ensure_ascii=False)[:160] if rows else "(빈 결과)"))
        except 관세청오류 as e:
            ok = False
            print("  %-8s 실패  %s" % (nm, e))
    return ok


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "점검":
        sys.exit(0 if 점검() else 1)
    print(__doc__)
