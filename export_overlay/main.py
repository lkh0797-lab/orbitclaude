"""Entry point: fetch customs exports, DART results and FX, then write one page per sector and an overview.

    py -3 -m export_overlay.main [--sector KEY ...] [--out-dir 경로] [--open]

Pages: <out-dir>/<sector key>.html for each sector, <out-dir>/수출겹쳐보기.html for the overview,
<out-dir>/변곡점레이더.html for the radar. In 기업추적 the default out-dir is .cache/수출겹쳐보기 (served at /overlay/).
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from export_overlay import build, config, customs, dart, fx, page, prices, screener
from export_overlay.cache import JsonCache
from export_overlay.sectors import BY_KEY, SECTORS

INDEX_NAME = "수출겹쳐보기.html"
SCREENER_NAME = "변곡점레이더.html"
SUMMARY_DIR = "_summary"     # one JSON per built sector, read back to build the overview and the menu
DART_WORKERS = 4             # companies fetched at once; DART allows 20,000 calls a day
PRICE_START = date(config.START_YEAR, 1, 1)


def collect_company(client: dart.DartClient, codes: dict, company: config.Company,
                    years: range, today: date) -> build.CompanyInput:
    info = codes.get(company.stock_code)
    if not info:
        return build.CompanyInput(company, error="DART 고유번호 없음")
    try:
        profile = client.company(info["corp_code"])
    except dart.DartError as exc:
        return build.CompanyInput(company, error=str(exc))
    if profile.get("acc_mt") != "12":
        return build.CompanyInput(company, error=f"{profile.get('acc_mt')}월 결산(12월 결산만 비교)")
    reports, missing = {}, []
    # The annual report first: a fresh one refreshes that year's Q3 report before Q3 is read.
    for y in years:
        for q in (4, 1, 2, 3):
            try:
                reports[(y, q)] = client.report(info["corp_code"], y, q)
            except dart.DartError:
                # Failed with nothing cached: before the deadline it is simply "not filed yet".
                reports[(y, q)] = None
                if dart.due_date(y, q) < today:
                    missing.append(f"{q}Q{y % 100:02d}")
    if not any(reports.values()):
        return build.CompanyInput(company, error="정기보고서 재무제표를 받지 못함" if missing else "정기보고서 재무제표 없음")
    return build.CompanyInput(company, reports, missing=missing)


def collect_all(dart_client: dart.DartClient, companies: Iterable[config.Company], today: date,
                warnings: list[str], workers: int = DART_WORKERS) -> dict[str, build.CompanyInput]:
    """Every distinct company once (a company may sit in several sectors), a few at a time."""
    try:
        codes = dart_client.corp_codes()
    except dart.DartError as exc:
        codes = {}
        warnings.append(f"DART 고유번호를 받지 못함: {exc}")
    unique = {c.stock_code: c for c in companies}
    years = range(config.START_YEAR, today.year + 1)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        got = pool.map(lambda c: collect_company(dart_client, codes, c, years, today), unique.values())
        return {ci.company.stock_code: ci for ci in got}


def sector_inputs(sector: config.Sector, collected: dict[str, build.CompanyInput]) -> list[build.CompanyInput]:
    # the sector's own Company carries its own break windows
    return [build.CompanyInput(c, collected[c.stock_code].reports, collected[c.stock_code].error,
                               collected[c.stock_code].missing) for c in sector.companies]


def build_sector(sector: config.Sector, exports: customs.ItemExports, inputs: list[build.CompanyInput],
                 fx_rates: dict[str, float], now: datetime, warnings: list[str], log: Callable) -> dict | None:
    if inputs and all(ci.error for ci in inputs):
        log(f"[{sector.name}] DART 실적을 한 곳도 받지 못해 이 섹터 화면은 새로 만들지 않습니다(이전 화면을 그대로 둡니다).")
        return None
    return build.build_payload(sector, exports, fx_rates, inputs, now.strftime("%Y-%m-%d %H:%M"), list(warnings))


def run(out_dir: Path, customs_client: customs.CustomsClient, dart_client: dart.DartClient,
        fx_rates: dict[str, float], today: date, now: datetime,
        sectors: Iterable[config.Sector] = SECTORS, log=print, workers: int = DART_WORKERS,
        price_fetch: Callable | None = None, cache: JsonCache | None = None) -> list[Path]:
    """Writes the sector pages, the overview and — over every sector built in this run — the
    inflection screener. Stock prices (for the screener's price columns) are only fetched when
    `price_fetch` is given."""
    sectors = list(sectors)
    start = f"{config.START_YEAR}01"
    exports = {}
    for sector in sectors:
        try:
            ex = customs_client.item_exports(sector.hs, start)
        except customs.CustomsError as exc:
            log(f"[{sector.name}] 관세청 수출 자료를 받지 못해 이 섹터는 건너뜁니다: {exc}")
            continue
        if not ex.months:
            log(f"[{sector.name}] 관세청 응답에 수출 행이 없습니다.")
            continue
        log(f"[{sector.name}] 관세청 {'+'.join(sector.hs)}: {min(ex.months)}~{max(ex.months)} ({len(ex.months)}개월)")
        exports[sector.key] = ex
    if not exports:
        return []
    warnings: list[str] = []
    wanted = [c for s in sectors if s.key in exports for c in s.companies]
    collected = collect_all(dart_client, wanted, today, warnings, workers)
    for ci in collected.values():
        log(f"DART {ci.company.name}: " + (ci.error or f"보고서 {sum(1 for r in ci.reports.values() if r)}건"
                                           + (f" (못 받음: {', '.join(ci.missing)})" if ci.missing else "")))
    if dart_client.stale:
        warnings.append(f"DART 응답 실패로 저장해 둔 자료 {len(dart_client.stale)}건을 그대로 썼습니다.")
    if not fx_rates:
        warnings.append("USD/KRW 환율을 받지 못해 달러 기준만 보여 줍니다.")

    payloads, screened = [], []
    for sector in sectors:
        if sector.key in exports:
            inputs = sector_inputs(sector, collected)
            p = build_sector(sector, exports[sector.key], inputs, fx_rates, now, warnings, log)
            if p:
                payloads.append(p)
                screened.append((sector, exports[sector.key], inputs))
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir = out_dir / SUMMARY_DIR
    summaries_dir.mkdir(exist_ok=True)
    for p in payloads:
        (summaries_dir / f"{p['sector']['key']}.json").write_text(
            json.dumps(build.summary(p), ensure_ascii=False), encoding="utf-8")
    # A run for some sectors keeps the others: the menu and the overview cover every sector with a page.
    built = [p["sector"]["key"] for p in payloads]
    summaries = []
    for key in [s.key for s in SECTORS] + [k for k in built if k not in {s.key for s in SECTORS}]:
        path = summaries_dir / f"{key}.json"
        if key in built or (path.exists() and (out_dir / f"{key}.html").exists()):
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
    nav = [{"key": x["key"], "name": x["name"]} for x in summaries]
    written = []
    for p in payloads:
        p["nav"] = nav
        path = out_dir / f"{p['sector']['key']}.html"
        path.write_text(page.render(p), encoding="utf-8")
        written.append(path)
        log(f"저장: {path}")
    if summaries:
        index = out_dir / INDEX_NAME
        index.write_text(page.render_index(summaries, now.strftime("%Y-%m-%d %H:%M")), encoding="utf-8")
        written.insert(0, index)
        log(f"저장: {index}")
    if screened:
        stock_prices, bench = {}, []
        if price_fetch is not None:
            codes = sorted({c.stock_code for _, _, inputs in screened for c in (ci.company for ci in inputs if not ci.error)})
            stock_prices, bench = prices.load_all(codes, PRICE_START, today, cache or JsonCache(config.CACHE_DIR), price_fetch, log)
        radar = screener.build_screener(screened, fx_rates, stock_prices, bench, today, now.strftime("%Y-%m-%d %H:%M"), warnings)
        path = out_dir / SCREENER_NAME
        path.write_text(page.render_screener(radar), encoding="utf-8")
        written.append(path)
        log(f"저장: {path}")
    return written


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="품목 수출 × 관련 기업 실적 겹쳐보기 (섹터별)")
    parser.add_argument("--sector", action="append", choices=sorted(BY_KEY), help="이 섹터만 (여러 번 줄 수 있음)")
    parser.add_argument("--out-dir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--open", action="store_true", help="다 만들면 개요 화면을 브라우저로 연다")
    parser.add_argument("--no-prices", action="store_true", help="주가를 받지 않는다(레이더의 주가 열이 빈다)")
    args = parser.parse_args(argv)
    try:
        customs_key, dart_key = config.resolve_key(config.CUSTOMS_KEY), config.resolve_key(config.DART_KEY)
    except config.KeyMissing as exc:
        print(exc)
        return 1
    today, now = date.today(), datetime.now()
    cache = JsonCache(config.CACHE_DIR)
    rates = fx.monthly_average(date(config.START_YEAR, 1, 1), today)
    sectors = [BY_KEY[k] for k in args.sector] if args.sector else SECTORS
    written = run(args.out_dir, customs.CustomsClient(customs_key, cache, today=today),
                  dart.DartClient(dart_key, cache, today=today), rates, today, now, sectors,
                  price_fetch=None if args.no_prices else fx.fdr_fetch, cache=cache)
    if not written:
        return 1
    if args.open:
        webbrowser.open(written[0].resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
