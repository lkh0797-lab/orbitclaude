"""관세청 품목별 국가별 수출입실적 (apis.data.go.kr/1220000/nitemtrade). The HTTP getter is injectable for tests.

Asking for a 4-digit HS returns one row per 6-digit sub-HS × country × month plus one `총계`
row (first item) for the whole window. One request covers at most 12 months (13 → resultCode 99),
so windows are split by calendar year. Months not yet published are simply absent (a window
with nothing published is resultCode 00 with no rows and no 총계). Amounts are US dollars
(exports = FOB). Around the 15th the previous month appears and earlier months — observed six
or more months back — receive small corrections.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from export_overlay.cache import JsonCache

URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
NUM_FIELDS = {"expDlr", "impDlr", "expWgt", "impWgt", "balPayments"}
OK_CODES = {"00"}
PAST_TTL = 30 * 86400
RECENT_TTL = 12 * 3600
RECENT_MONTHS = 13      # windows ending this recently can still be revised or extended

Get = Callable[[str, dict], str]


class CustomsError(RuntimeError):
    pass


def http_get(url: str, params: dict) -> str:
    import requests

    try:
        resp = requests.get(url, params=params, timeout=40)
    except requests.RequestException as exc:
        # The exception text can echo the request URL, which carries the key.
        raise CustomsError(f"연결 실패: {type(exc).__name__}") from None
    if resp.status_code != 200:
        raise CustomsError(f"HTTP {resp.status_code}")
    return resp.text


def parse(text: str) -> list[dict]:
    """XML → item dicts. Gateway and result-code errors raise CustomsError."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise CustomsError("XML 이 아닌 응답: " + text[:80].replace("\n", " ")) from None
    if root.tag == "OpenAPI_ServiceResponse":
        head = root.find(".//cmmMsgHeader")
        reason = "" if head is None else " ".join(
            (head.findtext(t) or "").strip() for t in ("returnReasonCode", "returnAuthMsg", "errMsg"))
        raise CustomsError("게이트웨이 오류 " + reason.strip())
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in OK_CODES:
        raise CustomsError(f"결과코드 {code} {(root.findtext('.//resultMsg') or '').strip()}")
    items = []
    for node in root.iter("item"):
        row: dict = {}
        for child in node:
            value = (child.text or "").strip()
            if child.tag in NUM_FIELDS:
                try:
                    row[child.tag] = float(value.replace(",", "")) if value else None
                except ValueError:
                    row[child.tag] = None
            else:
                row[child.tag] = value
        items.append(row)
    return items


def year_windows(start_ym: str, end_ym: str) -> list[tuple[str, str]]:
    """Calendar-year windows covering [start_ym, end_ym] ('YYYYMM')."""
    windows = []
    for year in range(int(start_ym[:4]), int(end_ym[:4]) + 1):
        a = max(start_ym, f"{year}01")
        b = min(end_ym, f"{year}12")
        if a <= b:
            windows.append((a, b))
    return windows


def last_closed_month(today: date) -> str:
    first = today.replace(day=1)
    return f"{first.year - (first.month == 1)}{(first.month - 2) % 12 + 1:02d}"


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[4:]) - int(a[4:])


@dataclass
class ItemExports:
    # Sub-HS keys are the returned codes cut to 6 digits: 6-digit for a 4-digit query, 4-digit for a
    # chapter (2-digit) query, the 6-digit code itself for a 6-digit query.
    months: dict[str, dict[str, float]] = field(default_factory=dict)                  # ym → sub-HS → USD
    countries: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)    # ym → sub-HS → 국가 → USD

    def merge(self, other: "ItemExports") -> None:
        for ym, subs in other.months.items():
            self.months.setdefault(ym, {}).update(subs)
        for ym, subs in other.countries.items():
            self.countries.setdefault(ym, {}).update(subs)
        self.months = dict(sorted(self.months.items()))


class CustomsClient:
    def __init__(self, key: str, cache: JsonCache, get: Get = http_get, today: date | None = None):
        self._key = key
        self._cache = cache
        self._get = get
        self._today = today or date.today()

    def item_exports(self, hs: str | tuple[str, ...] | list[str], start_ym: str, end_ym: str | None = None) -> ItemExports:
        """Monthly exports of every sub-HS of one or more query codes (and by destination).
        Unpublished months are absent."""
        end_ym = min(end_ym or "999912", last_closed_month(self._today))
        out = ItemExports()
        for code in ([hs] if isinstance(hs, str) else hs):
            for a, b in year_windows(start_ym, end_ym):
                months, countries = self._window(code, a, b)
                out.merge(ItemExports(months, countries))
        return out

    def _window(self, hs: str, a: str, b: str) -> tuple[dict, dict]:
        # Cached already aggregated: a chapter query (29, 39, 72 …) returns tens of thousands of rows.
        cache_key = f"customs_agg_{hs}_{a}_{b}"
        recent = _months_between(b, last_closed_month(self._today)) <= RECENT_MONTHS
        cached = self._cache.get(cache_key, RECENT_TTL if recent else PAST_TTL)
        if cached is not None:
            return cached["months"], cached["countries"]
        params = {"serviceKey": self._key, "strtYymm": a, "endYymm": b, "hsSgn": hs}
        rows = parse(self._get(URL, params))
        try:
            months, countries = aggregate(rows)  # never cache a window that fails the 총계 check
        except CustomsError as exc:
            raise CustomsError(f"{hs} {a}-{b}: {exc}") from None
        self._cache.put(cache_key, {"months": months, "countries": countries})
        return months, countries


def aggregate(rows: list[dict]) -> tuple[dict, dict]:
    """Rows of one window → ({ym: {sub-HS: usd}}, {ym: {sub-HS: {국가: usd}}}).

    The rows must add up to the window's 총계 row (to the dollar, allowing $1 rounding per
    row); otherwise CustomsError — a dropped sub-HS month must not pass as a small dip.
    """
    months: dict[str, dict[str, float]] = {}
    countries: dict[str, dict[str, dict[str, float]]] = {}
    total_row = None
    row_sum = 0.0
    counted = 0
    for row in rows:
        if row.get("year") == "총계":
            total_row = row.get("expDlr")
            continue
        hs_code = row.get("hsCd") or ""
        ym = (row.get("year") or "").replace(".", "")
        if hs_code in ("", "-") or len(ym) != 6 or not ym.isdigit():
            continue
        usd = row.get("expDlr") or 0.0
        hs6 = hs_code[:6]
        sub = months.setdefault(ym, {})
        sub[hs6] = sub.get(hs6, 0.0) + usd
        if usd:
            dest = countries.setdefault(ym, {}).setdefault(hs6, {})
            name = row.get("statCdCntnKor1") or row.get("statCd") or "-"
            dest[name] = dest.get(name, 0.0) + usd
        row_sum += usd
        counted += 1
    if rows and total_row is None:
        raise CustomsError("총계 행이 없는 응답")
    if total_row is not None and abs(row_sum - total_row) > max(1.0, float(counted)):
        raise CustomsError(f"행 합 {row_sum:,.0f} ≠ 총계 {total_row:,.0f}")
    return months, countries
