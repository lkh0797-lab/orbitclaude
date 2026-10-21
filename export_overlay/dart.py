"""DART OpenAPI: corp codes, company info and full financial statements. HTTP getters are injectable.

Only status 000 (정상) and 013 (데이터 없음) responses are cached; rate limits (020),
maintenance (800) and network errors raise DartError and are retried on the next run.
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from export_overlay.cache import JsonCache

API = "https://opendart.fss.or.kr/api"
REPORT_CODES = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
PERIOD_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
DUE_DAYS = {1: 45, 2: 45, 3: 45, 4: 90}
DAY = 86400

GetJson = Callable[[str, dict], dict]
GetBytes = Callable[[str, dict], bytes]


class DartError(RuntimeError):
    pass


def _requests_get(url: str, params: dict):
    import requests

    try:
        resp = requests.get(url, params=params, timeout=90)
    except requests.RequestException as exc:
        raise DartError(f"연결 실패: {type(exc).__name__}") from None   # message may echo the key
    if resp.status_code != 200:
        raise DartError(f"HTTP {resp.status_code}")
    return resp


def http_json(url: str, params: dict) -> dict:
    try:
        return _requests_get(url, params).json()
    except ValueError:
        raise DartError("JSON 이 아닌 응답") from None


def http_bytes(url: str, params: dict) -> bytes:
    return _requests_get(url, params).content


def num(value) -> float | None:
    """'1,234' / '(1,234)' / '△1,234' / '-' → float or None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace(" ", "")
    if not s or s in ("-", "--"):
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("△", "-").replace("▲", "-")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if negative else x


def due_date(year: int, quarter: int) -> date:
    """Filing deadline: quarter end + 45 days (Q1-Q3) or + 90 days (annual); weekends roll to Monday."""
    month, day = PERIOD_END[quarter]
    due = date(year, month, day) + timedelta(days=DUE_DAYS[quarter])
    while due.weekday() >= 5:
        due += timedelta(days=1)
    return due


# (standard tags in priority order, name pattern). Revenue names are exact (HPSP's untagged 2024
# annual lists 매출원가 before 매출액); operating-profit names are prefixes that exclude 영업외….
ACCOUNTS = {
    "revenue": (("ifrs-full_Revenue",),
                re.compile(r"^(매출액|수익\(매출액\)|영업수익|매출|수익|고객과의계약에서생기는수익)$")),
    "operating": (("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"),
                  re.compile(r"^영업(이익|손익|손실|순손익)")),
}
NUM_PREFIX = re.compile(r"^\s*(?:(?:[IVXⅠ-Ⅻ]+|\d{1,2}|[가-하])\s*[.．)]|\(\d{1,2}\))\s*")


def norm_tag(tag: str) -> str:
    """Reports up to 2019 H1 tag with the old 'ifrs_' prefix."""
    tag = (tag or "").strip()
    return "ifrs-full_" + tag[5:] if tag.startswith("ifrs_") else tag


@dataclass(frozen=True)
class Figure:
    cur: float | None              # thstrm_amount: this quarter's 3 months (annual report: full year)
    cum: float | None              # thstrm_add_amount: year to date (quarterly reports only)
    prev: float | None = None      # same report's prior-year column: frmtrm_q_amount (3 months) or,
                                   # in the annual report, frmtrm_amount (full year) — restated if restated
    prev_cum: float | None = None  # frmtrm_add_amount: prior-year year to date (quarterly reports only)


@dataclass(frozen=True)
class ReportFigures:
    basis: str          # "CFS" (연결) or "OFS" (별도)
    revenue: Figure | None
    operating: Figure | None
    rcept_no: str = ""


def _figure(row: dict, annual: bool) -> Figure:
    if annual:
        return Figure(num(row.get("thstrm_amount")), None, num(row.get("frmtrm_amount")), None)
    # frmtrm_amount is not used in quarterly reports: 2016 filings put the prior-year cumulative there.
    return Figure(num(row.get("thstrm_amount")), num(row.get("thstrm_add_amount")),
                  num(row.get("frmtrm_q_amount")), num(row.get("frmtrm_add_amount")))


KEEP_FIELDS = ("sj_div", "account_id", "account_nm", "thstrm_amount", "thstrm_add_amount",
               "frmtrm_q_amount", "frmtrm_amount", "frmtrm_add_amount", "rcept_no")


def compact(rows: list[dict]) -> list[dict]:
    """Only income-statement rows and the fields `pick` reads — a full statement is ~15× larger
    and the cache lives in a synced Google Drive folder. The first row keeps rcept_no."""
    out = [{k: r.get(k) for k in KEEP_FIELDS if r.get(k) not in (None, "")} for r in rows if r.get("sj_div") in ("IS", "CIS")]
    if rows and not out:
        out = [{"sj_div": "-", "rcept_no": rows[0].get("rcept_no")}]    # filed, but no income statement rows
    return out


def pick(rows: list[dict], which: str, annual: bool = False) -> Figure | None:
    """The income-statement row for `which`. Standard tags beat name matches; IS beats CIS."""
    tags, pattern = ACCOUNTS[which]
    best = None
    for order, row in enumerate(rows):
        div = row.get("sj_div")
        if div not in ("IS", "CIS"):
            continue
        name = NUM_PREFIX.sub("", (row.get("account_nm") or "").strip()).replace(" ", "")
        tag = norm_tag(row.get("account_id"))
        if tag in tags:
            score = 10 - tags.index(tag)
        elif pattern.search(name):
            score = 1
        else:
            continue
        figure = _figure(row, annual)
        if figure.cur is None and figure.cum is None:
            continue
        rank = (score, div == "IS", -order)
        if best is None or rank > best[0]:
            best = (rank, figure)
    return best[1] if best else None


class DartClient:
    def __init__(self, key: str, cache: JsonCache, get_json: GetJson = http_json,
                 get_bytes: GetBytes = http_bytes, today: date | None = None):
        self._key = key
        self._cache = cache
        self._get_json = get_json
        self._get_bytes = get_bytes
        self._today = today or date.today()
        self.stale: list[str] = []      # cache keys served past their TTL because DART failed

    def _or_stale(self, key: str, fetch):
        """Run `fetch`; when DART fails (network, 020 한도, 800 점검) fall back to the expired cache
        entry, so a short outage never throws away history that was downloaded before."""
        try:
            return fetch()
        except DartError as exc:
            stale = self._cache.get(key, float("inf"))
            if stale is None:
                raise
            self.stale.append(f"{key}: {exc}")
            return stale

    def corp_codes(self) -> dict[str, dict]:
        """Listed companies: {stock_code: {corp_code, corp_name}}."""
        cached = self._cache.get("dart_corpcodes", 30 * DAY)
        return cached if cached is not None else self._or_stale("dart_corpcodes", self._fetch_corp_codes)

    def _fetch_corp_codes(self) -> dict[str, dict]:
        blob = self._get_bytes(f"{API}/corpCode.xml", {"crtfc_key": self._key})
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                xml = zf.read(zf.namelist()[0])
        except zipfile.BadZipFile:
            raise DartError("고유번호 파일이 zip 이 아님: " + blob[:80].decode("utf-8", "replace")) from None
        out = {}
        for node in ET.fromstring(xml).iter("list"):
            stock = (node.findtext("stock_code") or "").strip()
            if stock:
                out[stock] = {"corp_code": (node.findtext("corp_code") or "").strip(),
                              "corp_name": (node.findtext("corp_name") or "").strip()}
        if not out:
            raise DartError("고유번호 파일에 상장사가 없음")
        self._cache.put("dart_corpcodes", out)
        return out

    def company(self, corp_code: str) -> dict:
        key = f"dart_company_{corp_code}"
        cached = self._cache.get(key, 30 * DAY)
        if cached is not None:
            return cached

        def fetch():
            js = self._get_json(f"{API}/company.json", {"crtfc_key": self._key, "corp_code": corp_code})
            if js.get("status") != "000":
                raise DartError(f"기업개황 {corp_code}: {js.get('status')} {js.get('message', '')}")
            info = {k: js.get(k) for k in ("corp_name", "stock_code", "acc_mt")}
            self._cache.put(key, info)
            return info

        return self._or_stale(key, fetch)

    def report(self, corp_code: str, year: int, quarter: int) -> ReportFigures | None:
        """Revenue/operating figures of one periodic report, 연결 first then 별도.
        None = not filed, or the period has not ended yet (nothing is requested then)."""
        month, day = PERIOD_END[quarter]
        if date(year, month, day) > self._today:
            return None
        for basis in ("CFS", "OFS"):
            rows = self._statement(corp_code, year, quarter, basis)
            if rows:
                annual = quarter == 4
                return ReportFigures(basis, pick(rows, "revenue", annual), pick(rows, "operating", annual),
                                     str(rows[0].get("rcept_no") or ""))
        return None

    def _statement(self, corp_code: str, year: int, quarter: int, basis: str, force: bool = False) -> list[dict]:
        key = f"dart_fs_{corp_code}_{year}_{REPORT_CODES[quarter]}_{basis}"
        if not force:
            cached = self._cache.get(key, self._ttl(year, quarter, self._cache_status(key) or "000"))
            if cached is not None:
                return cached["list"]

        def fetch():
            js = self._get_json(f"{API}/fnlttSinglAcntAll.json", {
                "crtfc_key": self._key, "corp_code": corp_code, "bsns_year": str(year),
                "reprt_code": REPORT_CODES[quarter], "fs_div": basis})
            status = js.get("status")
            if status not in ("000", "013"):
                raise DartError(f"재무제표 {corp_code} {year}Q{quarter} {basis}: {status} {js.get('message', '')}")
            data = {"status": status, "list": compact(js.get("list") or []) if status == "000" else []}
            if quarter == 4 and data["list"]:
                # Q4 = annual − Q3 year to date, so the Q3 report must be the same (possibly corrected)
                # version. Refresh it first; if that fails the annual is not cached and both retry next run.
                for b in ("CFS", "OFS"):
                    self._statement(corp_code, year, 3, b, force=True)
            self._cache.put(key, data)
            return data

        # A forced refresh must not quietly fall back to the old version it was meant to replace.
        return (fetch() if force else self._or_stale(key, fetch))["list"]

    def _cache_status(self, key: str) -> str | None:
        stored = self._cache.get(key, float("inf"))
        return stored.get("status") if isinstance(stored, dict) else None

    def _ttl(self, year: int, quarter: int, status: str) -> float:
        month, day = PERIOD_END[quarter]
        end = date(year, month, day)
        if status == "013":
            # "No data" can mean "not filed yet" or "never exists" (HPSP has no 연결 at all). Until
            # period end + 100 days — past every deadline, with slack for late filers — re-ask daily.
            return DAY if self._today <= end + timedelta(days=100) else 30 * DAY
        return 90 * DAY if (self._today - end).days > 365 else 7 * DAY
