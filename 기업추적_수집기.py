# -*- coding: utf-8 -*-
"""
기업추적 수집기
DART 전자공시에서 종목별 정기보고서(사업/반기/분기) 원문을 받아
섹션 단위 텍스트로 쪼개 저장한다.

사용법:
    python 기업추적_수집기.py                       # 종목.txt 전체, 최근 10년
    python 기업추적_수집기.py 403870 005930         # 종목코드 직접 지정
    python 기업추적_수집기.py 005930 --years 15     # 15년치
    python 기업추적_수집기.py 005930 --all          # DART 개시(1999)부터 전부
    python 기업추적_수집기.py 005930 --from 20100101
    python 기업추적_수집기.py 005930 --skip-amended # [기재정정] 건 제외
"""
import io
import os
import re
import sys
import csv
import time
import html
import zipfile
import datetime as dt

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "기업추적_수집")
CACHE_DIR = os.path.join(BASE, ".cache")
API = "https://opendart.fss.or.kr/api"

DEFAULT_YEARS = 10
DART_EPOCH = "19990101"          # DART 전자공시 개시. 이보다 앞은 조회 불가.

# DART 일일 한도는 20,000건. 다른 도구(Dart-alert-bot 등)가 같은 키를 쓰므로
# 여유를 두고 멈춘다. --max-calls 0 이면 무제한.
DEFAULT_MAX_CALLS = 18000

# DART 공통 응답코드 중 계속 진행해봐야 소용없는 것들
FATAL_STATUS = {
    "010": "등록되지 않은 키",
    "011": "사용할 수 없는 키",
    "012": "접근할 수 없는 IP",
    "020": "요청 제한 초과 (하루 20,000건)",
    "021": "조회 가능한 회사 개수 초과",
    "800": "DART 시스템 점검 중",
}


class Fatal(Exception):
    """더 돌려봐야 의미 없는 상황. 즉시 중단."""


class Budget(Exception):
    """오늘 쓰기로 한 DART 호출 수를 다 썼다. 내일 이어받는다."""


CALLS = 0           # 이번 실행에서 쓴 DART 호출 수
CALL_BUDGET = None  # None 이면 무제한


# ---------------------------------------------------------------- API key
sys.path.insert(0, BASE)
import 설정                                     # noqa: E402

API_KEY = 설정.dart_api_key()


# ---------------------------------------------------------------- HTTP
def http_get(path, params, timeout=180, tries=4):
    """네트워크 순간 장애로 15년치 수집이 통째로 죽지 않도록 재시도."""
    global CALLS
    if CALL_BUDGET is not None and CALLS >= CALL_BUDGET:
        raise Budget("호출 %s건 사용" % format(CALLS, ","))
    CALLS += 1
    last = None
    for n in range(1, tries + 1):
        try:
            r = requests.get(API + path, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if n < tries:
                wait = 2 ** n
                print("      (통신 오류, %d초 뒤 재시도 %d/%d) %s"
                      % (wait, n, tries - 1, str(e)[:80]), flush=True)
                time.sleep(wait)
    raise last


def check_status(js):
    st = js.get("status")
    if st in FATAL_STATUS:
        raise Fatal("DART %s — %s" % (st, FATAL_STATUS[st]))
    return st


# ---------------------------------------------------------------- corp code
def load_corp_map():
    """종목코드 -> (고유번호, 기업명) 매핑. corpCode.xml 은 하루 단위 캐시."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "CORPCODE.xml")
    stale = (not os.path.exists(cache)) or \
            (time.time() - os.path.getmtime(cache) > 86400)
    if stale:
        print("기업 고유번호 목록 내려받는 중...", flush=True)
        r = http_get("/corpCode.xml", {"crtfc_key": API_KEY}, timeout=120)
        if r.content[:2] != b"PK":
            raise Fatal("고유번호 목록 실패: " + r.text[:300])
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            data = z.read(z.namelist()[0])
        with open(cache, "wb") as fh:
            fh.write(data)
    else:
        with open(cache, "rb") as fh:
            data = fh.read()

    text = data.decode("utf-8", errors="replace")
    mapping = {}
    for m in re.finditer(r"<list>(.*?)</list>", text, re.S):
        blob = m.group(1)

        def tag(name):
            t = re.search("<" + name + ">(.*?)</" + name + ">", blob, re.S)
            return html.unescape(t.group(1)).strip() if t else ""

        stock = tag("stock_code")
        if stock and stock.strip():
            mapping[stock.strip()] = (tag("corp_code"), tag("corp_name"))
    return mapping


# ---------------------------------------------------------------- filings
def list_filings(corp_code, bgn_de, end_de, ty, keep_re):
    """공시 목록 조회. ty='A' 정기공시, 'F' 외부감사관련. 접수일 오름차순."""
    rows, page = [], 1
    while True:
        r = http_get("/list.json", timeout=60, params={
            "crtfc_key": API_KEY, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de,
            "pblntf_ty": ty, "page_no": page, "page_count": 100,
        })
        js = r.json()
        st = check_status(js)
        if st == "013":                      # 조회된 데이터 없음
            break
        if st != "000":
            raise Fatal("목록 조회 실패 %s: %s" % (st, js.get("message")))
        rows.extend(js.get("list", []))
        if page >= int(js.get("total_page", 1)):
            break
        page += 1
        time.sleep(0.2)

    keep = [x for x in rows if re.search(keep_re, x.get("report_nm", ""))]
    keep.sort(key=lambda x: x.get("rcept_dt", ""))
    return keep


PERIODIC_RE = r"(사업|반기|분기)보고서"
AUDIT_RE = r"감사보고서"


def label_of(nm):
    for key in ("사업보고서", "반기보고서", "분기보고서",
                "연결감사보고서", "감사보고서"):
        if key in nm:
            return key
    return "기타보고서"


def fetch_document(rcept_no):
    """원문 ZIP -> 텍스트. 원문 없는 건(첨부형/비공개)은 (None, 사유)."""
    r = http_get("/document.xml", {"crtfc_key": API_KEY, "rcept_no": rcept_no})
    if r.content[:2] != b"PK":
        head = r.content[:600].decode("utf-8", errors="replace")
        st = re.search(r"<status>(\d+)</status>", head)
        msg = re.search(r"<message>(.*?)</message>", head, re.S)
        code = st.group(1) if st else "?"
        if code in FATAL_STATUS:
            raise Fatal("DART %s — %s" % (code, FATAL_STATUS[code]))
        return None, (msg.group(1).strip() if msg else "원문 ZIP 아님")
    parts = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            raw = z.read(name)
            for enc in ("cp949", "utf-8", "euc-kr"):
                try:
                    parts.append(raw.decode(enc))
                    break
                except UnicodeDecodeError:
                    continue
    if not parts:
        return None, "ZIP 안에 읽을 수 있는 문서 없음"
    return "\n".join(parts), ""


# ---------------------------------------------------------------- parsing
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\u00a0]+")
NL_RE = re.compile(r"\n{3,}")

# DART \uad6c\ubc84\uc804(\ub300\ub7b5 2022\ub144 \uc774\uc804) \ubb38\uc11c\uac00 \uc4f0\ub294 \uc790\uccb4 \uc5d4\ud2f0\ud2f0. html.unescape \uac00 \ubaa8\ub978\ub2e4.
# \ubaa8\ub974\ub294 &xxx; \ub97c \uc2f8\uc7a1\uc544 \uc9c0\uc6b0\uba74 'AT&T;' \uac19\uc740 \ubcf8\ubb38\uae4c\uc9c0 \ub2e4\uce58\ubbc0\ub85c \uc544\ub294 \uac83\ub9cc \ubc14\uafbc\ub2e4.
DART_ENTITIES = {"&cr;": "\n"}


def strip_markup(chunk):
    for ent, rep in DART_ENTITIES.items():
        chunk = chunk.replace(ent, rep)
    chunk = re.sub(r"</(TR|P|TITLE|TABLE|SECTION-\d)>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"</TD>", "\t", chunk, flags=re.I)
    text = TAG_RE.sub("", chunk)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text)
    text = "\n".join(ln.strip() for ln in text.split("\n"))
    return NL_RE.sub("\n\n", text).strip()


def split_sections(doc):
    """SECTION-1 단위로 자른다. 없으면 통째로 한 섹션."""
    idx = [m.start() for m in re.finditer(r"<SECTION-1\b", doc, re.I)]
    if not idx:
        body = strip_markup(doc)
        return [("본문", body)] if body else []
    idx.append(len(doc))
    out = []
    for i in range(len(idx) - 1):
        chunk = doc[idx[i]:idx[i + 1]]
        t = re.search(r"<TITLE[^>]*>(.*?)</TITLE>", chunk, re.S | re.I)
        title = strip_markup(t.group(1)) if t else ""
        body = strip_markup(chunk)
        if body:
            out.append((title or ("섹션" + str(i + 1)), body))
    return out


def safe(name, limit=60):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" ._")
    return name[:limit] or "untitled"


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024.0


def hhmm(sec):
    sec = int(sec)
    return "%d분 %02d초" % (sec // 60, sec % 60)


# ---------------------------------------------------------------- collect
def collect(stock_code, corp_map, opt, pos=1, of=1):
    if stock_code not in corp_map:
        print("!! " + stock_code + ": 고유번호 없음 (상장 종목코드 확인)", flush=True)
        return 0, 0
    corp_code, corp_name = corp_map[stock_code]
    print("")
    print("== [%d/%d] %s (%s) 고유번호 %s ==   누적호출 %s"
          % (pos, of, corp_name, stock_code, corp_code, format(CALLS, ",")),
          flush=True)

    filings = list_filings(corp_code, opt["bgn_de"], opt["end_de"],
                           "A", PERIODIC_RE)
    n_periodic = len(filings)
    n_audit = 0
    if opt["with_audit"]:
        # 상장 전 기간은 정기보고서 의무가 없다. 외부감사 대상이었다면
        # 감사보고서(재무제표 포함)가 남아 있어 그만큼 이력이 더 소급된다.
        audit = list_filings(corp_code, opt["bgn_de"], opt["end_de"],
                             "F", AUDIT_RE)
        n_audit = len(audit)
        filings = sorted(filings + audit, key=lambda x: x.get("rcept_dt", ""))

    if opt["skip_amended"]:
        before = len(filings)
        filings = [f for f in filings if "정정" not in f.get("report_nm", "")]
        dropped = before - len(filings)
    else:
        dropped = 0

    if not filings:
        print("   해당 기간 정기보고서 없음 (상장 이전이거나 공시 없음)", flush=True)
        return 0, 0

    span = "%s ~ %s" % (filings[0]["rcept_dt"], filings[-1]["rcept_dt"])
    extra = ("  [정정 %d건 제외]" % dropped) if dropped else ""
    kinds = "정기보고서 %d건" % n_periodic
    if n_audit:
        kinds += " + 감사보고서 %d건" % n_audit
    print("   %s   접수 %s%s" % (kinds, span, extra), flush=True)

    company_dir = os.path.join(OUT_DIR, safe(corp_name) + "_" + stock_code)
    os.makedirs(company_dir, exist_ok=True)

    saved = 0
    total_chars = 0
    index_rows = []
    t0 = time.time()
    fetched = 0

    for i, f in enumerate(filings, 1):
        rcept = f["rcept_no"]
        nm = f.get("report_nm", "").strip()
        ym = re.search(r"\((\d{4})\.(\d{2})\)", nm)
        stamp = (ym.group(1) + "-" + ym.group(2)) if ym else f.get("rcept_dt", "")[:6]
        label = label_of(nm)
        tag = "[정정]" if "정정" in nm else ""
        head = "   [%3d/%d] %s %s%s" % (i, len(filings), stamp, label, tag)

        report_dir = os.path.join(company_dir,
                                  safe(stamp + "_" + label + tag + "_" + rcept))
        done = os.path.join(report_dir, "_완료.txt")

        if os.path.exists(done):
            with open(done, "r", encoding="utf-8") as fh:
                prev = fh.read()
            pc = re.search(r"섹션 (\d+)개 / (\d+)자", prev)
            nsec = int(pc.group(1)) if pc else 0
            nch = int(pc.group(2)) if pc else 0
            total_chars += nch
            saved += 1
            index_rows.append([stamp, label + tag, rcept, nsec, nch,
                               f.get("rcept_dt", ""), nm])
            print(head + "   (이미 수집됨, 건너뜀)", flush=True)
            continue

        try:
            doc, why = fetch_document(rcept)
        except Budget:
            # 오늘 한도 소진. 여기까지 받은 것 색인에 남기고 위로 넘긴다.
            write_index(company_dir, index_rows)
            raise
        fetched += 1
        if not doc:
            print(head + "   원문 없음 — " + why, flush=True)
            time.sleep(opt["sleep"])
            continue

        sections = split_sections(doc)
        os.makedirs(report_dir, exist_ok=True)
        chars = 0
        for n, (title, body) in enumerate(sections, 1):
            path = os.path.join(report_dir, "%02d_%s.txt" % (n, safe(title)))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# %s (%s) / %s\n" % (corp_name, stock_code, nm))
                fh.write("# 접수번호 %s / 섹션 %d: %s\n\n" % (rcept, n, title))
                fh.write(body)
            chars += len(body)

        with open(done, "w", encoding="utf-8") as fh:
            fh.write("%s\n접수번호 %s\n섹션 %d개 / %d자\n"
                     % (nm, rcept, len(sections), chars))

        total_chars += chars
        saved += 1
        index_rows.append([stamp, label + tag, rcept, len(sections), chars,
                           f.get("rcept_dt", ""), nm])

        # 남은 시간 추정은 실제로 받은 건 기준 (건너뛴 건 제외)
        eta = ""
        remain = len(filings) - i
        if fetched >= 2 and remain:
            per = (time.time() - t0) / fetched
            eta = "  남은시간 약 %s" % hhmm(per * remain)
        print(head + "   섹션 %d개 / %s자%s"
              % (len(sections), format(chars, ","), eta), flush=True)
        time.sleep(opt["sleep"])

    write_index(company_dir, index_rows)
    print("   -> %d건 / %s자, 목록.csv 갱신" % (saved, format(total_chars, ",")),
          flush=True)
    return saved, total_chars


def write_index(company_dir, index_rows):
    idx_path = os.path.join(company_dir, "목록.csv")
    with open(idx_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["기준연월", "보고서", "접수번호", "섹션수", "글자수", "접수일", "보고서명"])
        w.writerows(sorted(index_rows))


# ---------------------------------------------------------------- args
def read_targets():
    path = os.path.join(BASE, "종목.txt")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            m = re.match(r"^(\d{6})", line)
            if m:
                out.append(m.group(1))
    return out


def parse_args(argv):
    args = list(argv)
    opt = {"years": DEFAULT_YEARS, "all": False, "from": None,
           "skip_amended": False, "sleep": 0.8,
           "max_calls": DEFAULT_MAX_CALLS, "limit": None,
           "with_audit": False}

    def pop_val(flag):
        k = args.index(flag)
        v = args[k + 1]
        del args[k:k + 2]
        return v

    if "--all" in args:
        args.remove("--all")
        opt["all"] = True
    if "--skip-amended" in args:
        args.remove("--skip-amended")
        opt["skip_amended"] = True
    if "--with-audit" in args:
        args.remove("--with-audit")
        opt["with_audit"] = True
    if "--years" in args:
        opt["years"] = int(pop_val("--years"))
    if "--from" in args:
        opt["from"] = re.sub(r"\D", "", pop_val("--from"))
    if "--sleep" in args:
        opt["sleep"] = float(pop_val("--sleep"))
    if "--max-calls" in args:
        v = pop_val("--max-calls")
        opt["max_calls"] = None if v in ("0", "none", "무제한") else int(v)
    if "--limit" in args:
        opt["limit"] = int(pop_val("--limit"))

    end = dt.date.today()
    if opt["all"]:
        bgn = DART_EPOCH
    elif opt["from"]:
        bgn = opt["from"]
    else:
        bgn = (end - dt.timedelta(days=365 * opt["years"] + 30)).strftime("%Y%m%d")
    opt["bgn_de"] = max(bgn, DART_EPOCH)
    opt["end_de"] = end.strftime("%Y%m%d")

    codes = [a for a in args if re.fullmatch(r"\d{6}", a)]
    unknown = [a for a in args if a.startswith("-")]
    return codes, opt, unknown


def main():
    codes, opt, unknown = parse_args(sys.argv[1:])
    if unknown:
        print("모르는 옵션: " + " ".join(unknown))
        print(__doc__)
        return 2

    codes = codes or read_targets()
    if not codes:
        print("수집할 종목이 없습니다. 종목.txt 에 6자리 종목코드를 넣거나 인자로 넘기세요.")
        return 1
    if not API_KEY:
        print("DART_API_KEY 를 찾지 못했습니다. 같은 폴더에 .env 파일을 만들고")
        print("DART_API_KEY=발급받은키  한 줄을 넣어주세요.")
        return 1

    global CALL_BUDGET
    CALL_BUDGET = opt["max_calls"]

    if opt["limit"]:
        codes = codes[:opt["limit"]]

    os.makedirs(OUT_DIR, exist_ok=True)
    period = "%s ~ %s" % (opt["bgn_de"], opt["end_de"])
    budget = format(CALL_BUDGET, ",") if CALL_BUDGET else "무제한"
    print("기업추적 수집기 시작 — 종목 %d개 / 기간 %s / 호출한도 %s"
          % (len(codes), period, budget), flush=True)

    t0 = time.time()
    rc = 0
    total, chars = 0, 0
    try:
        corp_map = load_corp_map()
        print("고유번호 매핑 %s개 로드" % format(len(corp_map), ","), flush=True)

        for n, c in enumerate(codes, 1):
            try:
                s, ch = collect(c, corp_map, opt, n, len(codes))
                total += s
                chars += ch
            except (Fatal, Budget):
                raise
            except Exception as e:
                print("!! %s 처리 중 오류: %s" % (c, e), flush=True)
    except Budget as e:
        print("")
        print("!! 오늘 몫 소진 (%s). 종목 %d/%d 까지 처리." % (e, n, len(codes)))
        print("   DART 일일 한도는 자정에 초기화됩니다. 내일 같은 명령을 다시 실행하면")
        print("   받다 만 곳부터 정확히 이어받습니다.")
        rc = 3
    except Fatal as e:
        print("")
        print("!! 중단: %s" % e)
        print("   이미 받은 건은 남아 있습니다. 원인 해결 후 다시 실행하면 이어받습니다.")
        rc = 1
    except KeyboardInterrupt:
        print("")
        print("!! 사용자 중단. 다시 실행하면 받다 만 곳부터 이어받습니다.")
        rc = 130

    size = 0
    for root, _, files in os.walk(OUT_DIR):
        for f in files:
            size += os.path.getsize(os.path.join(root, f))

    print("")
    print("%s 보고서 %d건 / %s자 / 누적 %s  (소요 %s, DART호출 %s건)"
          % ("완료." if rc == 0 else "여기까지:",
             total, format(chars, ","), human(size),
             hhmm(time.time() - t0), format(CALLS, ",")))
    print("저장 위치: " + OUT_DIR)
    return rc


if __name__ == "__main__":
    sys.exit(main())
