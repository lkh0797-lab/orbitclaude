# -*- coding: utf-8 -*-
"""
드러켄밀러 모드 — 분기 단독 실적의 '변화의 변화'를 본다.

드러켄밀러는 밸류에이션으로 타이밍을 잡지 않는다. 그가 보는 것은
18~24개월 뒤의 이익이고, 그 단서는 지금 수준(level)이 아니라
변화율의 변화(2차 미분)에 있다. 이 모듈은 그것만 만든다.

  1. 분기 단독 매출·영업이익 (누적치가 아니라 3개월 단독)
  2. 전년 동기 대비 증감률
  3. 가속도 = 증감률의 전분기 대비 변화 (%p)
  4. 꺾임 선행지표 — 재고일수, 매출채권회수일수, CAPEX 강도
  5. TTM 이익과 그 시점 주가로 계산한 PER

DART 분기보고서의 thstrm_amount 는 손익계산서 기준 '3개월 단독'이다.
사업보고서만 연간치라, 4분기는 연간 − 3분기누적으로 떼어낸다.
"""
import os
import re
import sys
import json
import math
import time
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("재무", os.path.join(BASE, "재무.py"))
FIN = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(FIN)

CACHE_DIR = os.path.join(BASE, ".cache", "druck")

VERSION = 5          # 5: 지배순이익 줄을 지배 + 비지배 = 당기순이익 검산으로 고름(총포괄 · 엉터리 태그 · 주당 · 계속/중단 귀속 줄 — SK 2023Q4 −17,257억 → −10,847억 · 위메이드 2017–23 6,455원, 2026-10-22). 4: 최종 검토 고침 — 변곡을 한 분기 부호 바뀜으로(사용자 결정) · 낡은 지금 PER 막기 · 거짓 분할(합병 창 정수 비율 · 한 분기 튐 · Q4 부호 어긋남) · 분할 뒤 PER 보류 · 매출 없는 분기 주식 수 · 최근 8분기로 금융 기준 · 새 공시 013 다시 받기 · Q2/Q3 누적이 3개월 칸에 · 보고서 단위 ×1e6 · 감사보고서는 결산월 판정에서 뺌 (2026-10-10). 3: 가속도 개편 계획 1 전체 — 정정 공시 원장 다시 받기(같은 날 포함 >=) · 분할 뒤 공시 split_after · 분할 보정 EPS/지금 PER · B(2분기 평균 YoY 의 변화) · 7국면 · 변곡 규칙 · 품질 표시 파이프라인 전부 (2026-10-10). 2: 분기 키 조밀 격자 · Q4 기준/범위 검사 · 재작성 전년 비교(YoY_r) · 기준일 · 품질 표시 · 이상값 (2026-10-09). 계산을 바꾸면 올린다 — 캐시가 전부 다시 계산된다


def read_cache(path):
    """가속도 캐시 파일 → dict — v 가 지금 VERSION 일 때만. 없는 파일 · 깨진 JSON · 옛 버전은 None(다시 계산할 대상).
    서버 _druck_read 가 이것만 부른다 — 캐시를 읽는 곳은 모두 이 규칙을 거친다."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("v") == VERSION else None


def write_cache(path, obj, tries=5, wait=0.2):
    """캐시 원자 쓰기 — path.tmp 에 쓰고 os.replace. 읽는 쪽이 잠금 없이 파일을 열고 있으면 Windows 의 replace 가
    PermissionError(WinError 5)로 실패한다 — wait 초 쉬며 tries 번까지 다시 해 본다. 끝내 못 바꾸면 .tmp 를 지우고 False(캐시 안 됨)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            if i < tries - 1:
                time.sleep(wait)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


_Q_OF_MONTH = {"03": 1, "06": 2, "09": 3, "12": 4}
_FILED_OK = {("분기보고서", "03"), ("반기보고서", "06"), ("분기보고서", "09"), ("사업보고서", "12")}
_PERIODIC = {"분기보고서", "반기보고서", "사업보고서"}


def filed_meta(reports):
    """series() 의 meta — {filed: {n: 원본(정정 아닌) 보고서 접수일 YYYYMMDD — 여럿이면 가장 이른 날}, fy_bad: {연도}}.
    reports = [{stamp: 'YYYY-MM', label, tag, rcept}](서버 회사 색인의 보고서). 12월 결산 정기보고서(분기 03 · 반기 06 · 분기 09 · 사업 12)가
    아닌 정기보고서가 하나라도 있는 해는 fy_bad — 결산월이 달라 분기 키가 어긋나니 그해는 받지 않는다.
    정기보고서가 아닌 것(감사보고서 등 — HPSP 상장 전 2018~2021)은 결산월 판정에서 뺀다(그 해를 fy_bad 로 만들지 않는다).
    amend = {(연도, 분기): 그 분기 정정(태그 달린) 보고서 가운데 가장 늦은 접수일} — 원장 캐시 날짜와 같거나 뒤면 series 가 그 분기를 다시 받는다."""
    filed, fy_bad, amend = {}, set(), {}
    for r in reports:
        y, mth = r["stamp"].split("-")
        if r["label"] not in _PERIODIC:
            continue
        if (r["label"], mth) not in _FILED_OK:
            fy_bad.add(int(y))
            continue
        n = int(y) * 4 + _Q_OF_MONTH[mth] - 1
        if not r["tag"]:
            filed[n] = min(filed.get(n, "99999999"), r["rcept"][:8])
        else:
            k = (int(y), _Q_OF_MONTH[mth])
            amend[k] = max(amend.get(k, ""), r["rcept"][:8])
    return {"filed": filed, "fy_bad": fy_bad, "amend": amend}


class _Last(threading.local):
    """series() 가 끝난 뒤 그 회사 결과 {transient: 일시 오류로 건너뛴 분기 수, fy_bad: [연도], error: 마지막 삼킨 예외 "종류: 내용" | None}.
    서버가 여러 회사를 스레드로 나눠 만들고 series() 직후 같은 스레드에서 읽으므로 스레드마다 따로 둔다 — dict 와 같은 쓰임(get · update · [k] · [k] += 1)."""

    def __init__(self):                    # 스레드가 처음 만질 때마다 불린다
        self._d = {"transient": 0, "fy_bad": [], "error": None}

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v

    def __contains__(self, k):
        return k in self._d

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)

    def __repr__(self):
        return "LAST(%r)" % (self._d,)

    def get(self, k, default=None):
        return self._d.get(k, default)

    def update(self, *args, **kw):
        self._d.update(*args, **kw)

    def keys(self):
        return self._d.keys()

    def items(self):
        return self._d.items()

    def values(self):
        return self._d.values()

    def copy(self):
        return dict(self._d)


LAST = _Last()
KEYS_IS = ("매출액", "영업이익", "당기순이익", "지배순이익", "EPS")

Q_BY_REPRT = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
REPRT_BY_Q = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}

# 손익계산서에서 '3개월 단독'으로 뽑을 항목
IS_PICK = {
    "매출액": (["ifrs-full_Revenue"], r"^(매출액|수익\(매출액\)|영업수익)$"),
    "영업이익": (["dart_OperatingIncomeLoss",
                "ifrs-full_ProfitLossFromOperatingActivities"], r"^영업(?:이익|손익|손실)"),
    "당기순이익": (["ifrs-full_ProfitLoss"], r"^당기순(?:이익|손익|손실)"),
    "지배순이익": (["ifrs-full_ProfitLossAttributableToOwnersOfParent"], r"^(지배기업\s*)?(소유주|지배주주|지배기업).*(지분|순이익|귀속)"),
    "EPS": (["ifrs-full_BasicEarningsLossPerShare",
             "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations"],
            r"^(?:보통주\s*)?(?:계속영업\s*)?기본\s*주당"),
}
IS_PICK_GRAB = {k: v for k, v in IS_PICK.items() if k != "지배순이익"}   # 지배순이익은 _owner_ni 가 검산으로 고른다
# 재무상태표에서 시점 잔액으로 뽑을 항목
BS_PICK = {
    "재고자산": (["ifrs-full_Inventories"], r"^재고자산$"),
    "매출채권": (["ifrs-full_TradeAndOtherCurrentReceivables"],
              r"^매출채권( 및 기타(유동)?채권)?$"),
    "유형자산": (["ifrs-full_PropertyPlantAndEquipment"], r"^유형자산$"),
    "자본총계": (["ifrs-full_Equity"], r"^자본총계$"),
}
CAPEX_RE = re.compile(r"유형자산의? ?(취득|증가)")


def _grab(rows, table, picks, field, meta=None):
    """원장에서 picks 의 항목을 골라 {키: 값}. meta 를 주면 고른 줄의 이름을 meta[키] 에 남긴다."""
    out = {}
    for key, (ids, name_re) in picks.items():
        rx = re.compile(name_re)
        best = None
        for r in rows:
            if r.get("sj_div") not in table:
                continue
            nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
            if "우선주" in nm:
                continue
            # 총포괄손익 귀속 줄('지배기업지분' · '비지배지분' — ComprehensiveIncomeAttributableTo…)은 이름이 같아도
            # 당기순이익 귀속 줄이 아니다(2024 00100601: 이름만 맞춰 총포괄 쪽 -1,125,449,589 를 집었다)
            if FIN.norm_tag(r.get("account_id")).startswith("ifrs-full_ComprehensiveIncome"):
                continue
            # 재무.py 와 같은 판정 — 본문 줄('Ⅲ.영업손실')과 잘못 붙은 태그(롯데렌탈)를 가린다
            hit, aid = FIN._account_hit(r, nm, ids, rx)
            if not hit:
                continue
            v = FIN.num(r.get(field))
            if v is None:
                continue
            score = FIN._tag_score(aid, ids)
            if best is None or score > best[0]:
                best = (score, v, nm)
        if best:
            out[key] = best[1]
            if meta is not None:
                meta[key] = best[2]
    return out


EPS_DISC_TAG = "ifrs-full_BasicEarningsLossPerShareFromDiscontinuedOperations"


def _cont_only(nm):
    """'계속영업 기본주당이익' 처럼 계속영업만 센 줄인가 — '계속영업과 중단영업 …' 은 합계 줄이다(서버 _pipe_rows 의 cont 와 같은 판정)."""
    return "계속영업" in nm and "계속영업과" not in nm


def _disc_eps(rows, field):
    """중단영업 기본주당이익 줄의 값(없으면 None) — 태그 BasicEarningsLossPerShareFromDiscontinuedOperations 이거나,
    이름에 '중단영업'이 있고 '계속영업'은 없으며 '기본 … 주당'이 든 줄. 칸마다 값이 있는 첫 줄(서버 _pipe_rows 의 disc 와 같은 규칙)."""
    for r in rows:
        if r.get("sj_div") not in ("IS", "CIS"):
            continue
        nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
        if "우선주" in nm:
            continue
        if not (FIN.norm_tag(r.get("account_id")) == EPS_DISC_TAG
                or ("중단영업" in nm and "계속영업" not in nm and re.search(r"기본.*주당|주당.*기본", nm))):
            continue
        v = FIN.num(r.get(field))
        if v is not None:
            return v
    return None


def _capex(rows):
    """현금흐름표의 유형자산 취득액. 음수로 찍히는 곳이 많아 절대값."""
    for r in rows:
        if r.get("sj_div") != "CF":
            continue
        if CAPEX_RE.search((r.get("account_nm") or "")):
            v = FIN.num(r.get("thstrm_amount"))
            if v is not None:
                return abs(v)
    return None


# 지배순이익 대체용 — 당기순이익에서 뺄 비지배 몫(당기순이익 귀속 줄). 태그가 없는 줄은 이름('비지배지분')으로 잡는다
NCI_PICK = {"비지배순이익": ([FIN.NI_PARTS["nci"]], r"^비지배")}

# 지배순이익 줄 고르기(2026-10-22) — 후보 줄 가운데 지배 + 비지배 = 당기순이익(±0.2%, 작은 값은 ±1억)인 줄을 고른다. 태그 점수는 검산이
# 같을 때만 가른다. 분기 원장 함정: 총포괄 귀속 줄이 태그 없이 같은 이름으로 먼저 온다(SK 2023 3분기 — 총포괄 4,757억을 집어 2023Q4 = −17,257억,
# 맞는 값 −10,847억 · 거꾸로 낸 주식 수까지 흐림) · 엉터리 태그 줄이 이름 줄을 이긴다(위메이드 2017Q3–2023Q4 태그 줄 6,455원 · 삼성전기 2019–21
# 태그 줄 = 계속영업 몫) · 이름 정규식이 중단영업 · 주당 줄을 잡는다(한미반도체 2015–16 '지배기업지분중단영업순손실' 0 · AJ네트웍스 2026Q2 주당 632원).
# 뺄 이름 · 계속 + 중단 귀속 태그 합 · 1% 문턱은 연간 규칙(변곡점.owner_parts)과 같다. 주당 줄은 '주당(순)이익 · 손실 · 손익'만 —
# 맨 '주당'은 '지배주주당기순이익'(지배주주 + 당기, 감사에서 태그 줄 42개)까지 뺀다
OWN_SKIP = re.compile(r"계속영업|중단영업|포괄|주당\s*순?(?:이익|손실|손익)")
NCI_SKIP = re.compile(r"부채|금융|계속영업|중단영업|포괄|주당\s*순?(?:이익|손실|손익)")
OWN_CD = ("ifrs-full_IncomeFromContinuingOperationsAttributableToOwnersOfParent",
          "ifrs-full_IncomeFromDiscontinuedOperationsAttributableToOwnersOfParent")
NCI_CD = ("ifrs-full_ProfitLossFromContinuingOperationsAttributableToNoncontrollingInterests",
          "ifrs-full_ProfitLossFromDiscontinuedOperationsAttributableToNoncontrollingInterests")
CD_SCORE = 5          # 계속 + 중단 귀속 태그 합 — 귀속 태그 줄(10)과 이름 줄(1) 사이(owner_parts 순서: 태그 → 계속 + 중단 → 이름)
OWN_TOL, OWN_TOL_MIN = 0.002, 1e8   # 검산 허용 — 당기순이익의 0.2%, 작은 값은 1억
OWN_ERR_TIE = 1e6     # 검산 어긋남이 100만 원 아래면 같은 것으로 보고 태그 점수로 가른다(백만 원 단위 반올림)


def _owner_cands(rows, pick, skip, cd, field):
    """귀속 순이익 후보 [(태그 점수, 값)] — 원장 순서대로. 우선주 · 총포괄 태그 줄은 뺀다. skip 이름 줄은 이름으로만 맞았으면 빼고,
    귀속 태그로 맞았으면 점수 0(가장 약한 후보 — 검산에 맞거나 다른 후보가 없을 때만. JW중외제약 2024 연간: 지배 태그 줄 이름이
    '지배기업지분포괄이익'인데 값은 당기순이익). cd = (계속, 중단) 귀속 태그 — 계속 줄이 있으면 둘의 합을 CD_SCORE 후보로 붙인다(중단 줄이 없으면 0)."""
    ids, name_re = pick
    rx = re.compile(name_re)
    out, part = [], {}
    for r in rows:
        if r.get("sj_div") not in ("IS", "CIS"):
            continue
        aid = FIN.norm_tag(r.get("account_id"))
        v = FIN.num(r.get(field))
        if aid in cd:
            if v is not None:
                part.setdefault(aid, v)
            continue
        nm = FIN.NUM_PREFIX.sub("", (r.get("account_nm") or "").strip())
        if "우선주" in nm or aid.startswith("ifrs-full_ComprehensiveIncome"):
            continue
        hit, tag = FIN._account_hit(r, nm, ids, rx)
        if not hit or v is None:
            continue
        s = FIN._tag_score(tag, ids)
        if skip.search(nm):
            if s < 2:
                continue
            s = 0
        out.append((s, v))
    if cd[0] in part:
        out.append((CD_SCORE, part[cd[0]] + part.get(cd[1], 0)))
    return out


def _top(cands):
    """태그 점수가 가장 높은 후보의 값 — 같으면 원장에서 먼저 온 줄(_grab 과 같은 규칙)."""
    return max(enumerate(cands), key=lambda t: (t[1][0], -t[0]))[1][1]


def _owner_ni(rows, field, ni, has_nci):
    """그 칸의 지배순이익 — 고르지 못하면 None(부른 쪽이 당기순이익 − 비지배로). ni = 그 칸의 당기순이익,
    has_nci = 원장 어느 칸에든 비지배 줄이 있는가(없는 회사는 지배 = 당기순이익으로 검산한다)."""
    own = _owner_cands(rows, IS_PICK["지배순이익"], OWN_SKIP, OWN_CD, field)
    if not own:
        return None
    if ni is None:
        return _top(own)                     # 검산할 당기순이익이 없다 — 태그 점수
    nci = [v for _, v in _owner_cands(rows, NCI_PICK["비지배순이익"], NCI_SKIP, NCI_CD, field)] or ([] if has_nci else [0])
    tol = max(abs(ni) * OWN_TOL, OWN_TOL_MIN)
    best = None
    for i, (s, v) in enumerate(own):
        err = min((abs(v + n - ni) for n in nci), default=None)
        if err is not None and err <= tol:
            key = (max(err, OWN_ERR_TIE), -s, i)
            if best is None or key < best[0]:
                best = (key, v)
    if best:
        return best[1]
    v = _top(own)
    # 검산에 맞는 줄이 없고 값이 당기순이익의 1%도 안 되면 엉터리 태그 줄(위메이드: 6,455원) — 버린다. 1%를 넘으면 지배 줄을 믿는다
    # (당기순이익 줄 쪽이 틀렸을 수 있다 — owner_parts 와 같은 문턱)
    return None if abs(v) < abs(ni) * 0.01 else v
# (원장 칸, 키 접미사) — 그 보고서의 값 · 누적 · 전년 같은 분기 · 전년 같은 누적 · 전년 연간
IS_FIELDS = (("thstrm_amount", ""), ("thstrm_add_amount", "_누적"), ("frmtrm_q_amount", "_전"),
             ("frmtrm_add_amount", "_전누적"), ("frmtrm_amount", "_전연"))

NET = {"budget": None, "used": 0}   # offline 빌드의 네트워크 예산 — 캐시 파일이 없을 때 · 정정 공시로 다시 받을 때 · 013 다시 묻기를 센다(_fetch)


def _ymd(ts):
    return time.strftime("%Y%m%d", time.localtime(ts))


def _will_reask_013(path, year, reprt, mt):
    """FIN.fetch_statement 가 이 캐시(013 '데이터 없음')를 다시 물을까 — FIN._stale_013 과 같은 판정. 파일은 mtime 조건이 맞을 때만 연다
    (기한 지나 받은 파일이 대부분이라 드라이브 읽기를 한 번 더 하지 않게)."""
    try:
        mo, dy = FIN._PERIOD_END[str(reprt)]
        end = time.mktime((int(year), mo, dy, 0, 0, 0, 0, 0, -1))
    except Exception:
        return False
    now = time.time()
    if not (mt < end + 100 * 86400 and now > end + 14 * 86400 and now - mt > 86400):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return bool(FIN._stale_013(json.load(fh), path, year, reprt))
    except Exception:
        return False


def _empty_ledger(path):
    """원장 캐시 파일이 '없음'(013 · 빈 목록)인가 — 읽지 못하면 False(있는 것으로 본다)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return False
    return isinstance(d, dict) and (d.get("status") == "013" or not d.get("list"))


def _ledger_path(corp_code, year, reprt, fs_div):
    return os.path.join(FIN.FIN_DIR, "%s_%s_%s_%s.json" % (corp_code, year, reprt, fs_div))


def _net_need(path, year, reprt, amend=None, filed=None, stat=True):
    """_fetch 가 이 원장 파일 때문에 DART 를 부를까 — (exists, mt, force, net). stat=False 면(online · 정정도 공시일도 없음) 파일을 보지 않는다.
    force = 정정 공시(amend)가 캐시 파일 날짜와 같거나 뒤 · 또는 원본 공시(filed)가 캐시 파일 날짜와 같거나 뒤인데 파일이 '없음'(013 · 빈 목록) —
    공시 전에(또는 공시 당일 DART 반영 전에) 받아 둔 013 이 새 분기를 가리지 않게(2026-10-10 최종 검토). net = 파일 없음 · force · 013 다시 묻기.
    밤 미리 계산의 '네트워크가 필요한 회사' 판정(needs_net)도 이 함수 하나를 쓴다."""
    if not stat:
        return True, None, False, False
    exists = os.path.exists(path)
    mt = os.path.getmtime(path) if exists else None
    force = False
    if mt is not None:
        day = _ymd(mt)
        force = bool(amend and amend >= day) or bool(filed and filed >= day and _empty_ledger(path))
    net = not exists or force or (mt is not None and _will_reask_013(path, year, reprt, mt))
    return exists, mt, force, net


def _fetch(corp_code, year, reprt, fs_div, offline, amend=None, filed=None):
    """원장 한 장. 네트워크를 쓰는 경우 — 캐시 파일이 없다 · 정정 공시(amend, YYYYMMDD)가 캐시 파일 날짜와 같거나 뒤다(force 로 다시 받음, online 도) ·
    원본 공시일(filed)이 캐시 파일 날짜와 같거나 뒤인데 그 파일이 013 · 빈 목록이다(force) · 013 캐시를 FIN 이 다시 물을 때.
    offline 이면 그 넷을 NET 예산에 세고, 바닥나면 받지 않고 일시 오류(transient)로 돌려준다.
    같은 날도 다시 받는다 — 접수번호엔 시각이 없어, 원장을 받은 그날 낮에 나온 기재정정 · 원본 공시를 '뒤'로 못 가른다(그날은 한 번 더 받을 수 있다)."""
    path = _ledger_path(corp_code, year, reprt, fs_div)
    exists, mt, force, net = _net_need(path, year, reprt, amend, filed, stat=bool(offline or amend or filed))
    if offline:
        if net:
            if NET["budget"] is not None and NET["used"] >= NET["budget"]:
                return {"status": "budget", "list": [], "transient": True}
            NET["used"] += 1
    if force:
        return FIN.fetch_statement(corp_code, year, reprt, fs_div, force=True)
    return FIN.fetch_statement(corp_code, year, reprt, fs_div)


def period_data(corp_code, year, q, offline=False, amend=None, filed=None):
    """한 분기의 원장 — 그 보고서의 값(thstrm) · 누적(thstrm_add) · 비교기간(frmtrm_q · frmtrm_add · frmtrm) · 기준(CFS/OFS) · 출처 · rcept.
    4분기 단독은 series() 에서 연간 − 3분기 누적으로 뗀다. filed = 그 분기 원본 공시일(있으면 '공시 전에 받아 둔 013' 을 다시 받는다 — _fetch)."""
    reprt = REPRT_BY_Q[q]
    st = _fetch(corp_code, year, reprt, "CFS", offline, amend, filed)
    if st.get("transient"):
        return {"_transient": True}
    rows, fs = st.get("list") or [], "CFS"
    if not rows:
        st = _fetch(corp_code, year, reprt, "OFS", offline, amend, filed)
        if st.get("transient"):
            return {"_transient": True}
        rows, fs = st.get("list") or [], "OFS"
    if not rows:
        return None
    d = {}
    d.update(_grab(rows, ("BS",), BS_PICK, "thstrm_amount"))
    nci_args = (NCI_PICK["비지배순이익"], NCI_SKIP, NCI_CD)
    has_nci = any(_owner_cands(rows, *nci_args, fld) for fld, _ in IS_FIELDS)
    for fld, suf in IS_FIELDS:
        meta = {}
        got = _grab(rows, ("IS", "CIS"), IS_PICK_GRAB, fld, meta)
        # EPS 는 합계(계속 + 중단영업) 기준으로 — 계속영업 줄만 골랐고 중단영업 줄이 따로 있으면 더한다. 순이익(중단영업 포함)과 기준을 맞춘다
        # (카카오 2026Q2: 계속영업 EPS 431원 × 순이익 164억(중단 −1,560억 포함)이면 주식 수가 10배 줄어 '병합'으로 읽힌다 — 합계 41원)
        if got.get("EPS") is not None and _cont_only(meta.get("EPS", "")):
            dv = _disc_eps(rows, fld)
            if dv is not None:
                got["EPS"] += dv
        own = _owner_ni(rows, fld, got.get("당기순이익"), has_nci)
        if own is not None:
            got["지배순이익"] = own
        elif got.get("당기순이익") is not None:
            # 지배기업 귀속 줄이 없으면 당기순이익 − 비지배 몫(비지배 줄이 아예 없으면 당기순이익 그대로 — 재무._net_income_from 과 같은 규칙)
            nci = _owner_cands(rows, *nci_args, fld)
            if nci:
                got["지배순이익"] = got["당기순이익"] - _top(nci)
            elif not has_nci:
                got["지배순이익"] = got["당기순이익"]
        for k, v in got.items():
            d[k + suf] = v
    if q == 1:
        for k in IS_PICK:
            if d.get(k + "_전") is None and d.get(k + "_전누적") is not None:
                d[k + "_전"] = d[k + "_전누적"]
    if q != 4:                              # 분기 · 반기 보고서의 frmtrm_amount 는 대개 없고, 있으면 누적값이다 — 쓰지 않는다
        for k in IS_PICK:
            d.pop(k + "_전연", None)
    cx = _capex(rows)
    if cx is not None:
        d["CAPEX"] = cx
    if not any(not k.startswith("_") for k in d):
        return None
    rc = [str(r.get("rcept_no") or "")[:8] for r in rows if r.get("rcept_no")]
    d.update(_fs=fs, _src="body" if st.get("status") == "body" else "api", _rcept=max(rc) if rc else None, _transient=False)
    return d


def _n(y, q):
    return y * 4 + q - 1


_IS_SUFS = ("", "_누적", "_전", "_전누적", "_전연")


def _ni_of(d, suf=""):
    """주식 수 · 부호 판정에 쓰는 순이익 — 지배순이익, 없으면 당기순이익."""
    v = d.get("지배순이익" + suf)
    return v if v is not None else d.get("당기순이익" + suf)


def _fix_cum_in_quarter(raw):
    """반기 · 3분기 보고서가 3개월 칸(thstrm)에 누적(thstrm_add)과 같은 값을 적은 경우(DL 2024 반기 2.90조 · 3분기 4.32조, 비교 칸은 빔) —
    같은 해 바로 앞 분기에 같은 기준(fs)의 누적이 있으면 분기 단독 = 누적 − 앞 분기 누적(EPS 등 손익 다섯 항목 모두, 1분기는 그 값이 곧 누적).
    앞 분기 기준이 다르면 손익 칸을 비우고 품질 basis. 그해 첫 보고서(분할 신설 회사의 첫 반기 등 — 앞 분기 원장 없음)는 그대로 둔다.
    raw 의 해당 칸을 고친 사본으로 바꾸고 {n: [품질]} 을 돌려준다."""
    tags = {}
    for n in sorted(raw):
        d, q = raw[n], n % 4 + 1
        if q not in (2, 3):
            continue
        v, c = d.get("매출액"), d.get("매출액_누적")
        if v is None or c is None or v != c:
            continue
        pv = raw.get(n - 1)
        if pv is None:
            continue
        pq = q - 1

        def pcum(k, prev=False):
            """앞 분기의 누적 — prev 면 비교 칸(전년 같은 누적). 1분기는 그 값이 곧 누적이다."""
            got = pv.get(k + ("_전누적" if prev else "_누적"))
            if got is None and pq == 1:
                got = pv.get(k + ("_전" if prev else ""))
            return got
        nd = dict(d)
        if pv.get("_fs") != d.get("_fs"):
            for k in KEYS_IS:
                nd[k] = nd[k + "_전"] = None
            tags[n] = ["basis"]
            raw[n] = nd
            continue
        if pcum("매출액") is None:
            continue
        for k in KEYS_IS:
            c_, p_ = d.get(k + "_누적"), pcum(k)
            nd[k] = (c_ - p_) if (c_ is not None and p_ is not None) else None
            e_, ec_ = d.get(k + "_전"), d.get(k + "_전누적")
            if e_ is not None and ec_ is not None and e_ == ec_:      # 비교 칸에도 누적이 적혔으면 같은 식으로
                pp = pcum(k, prev=True)
                nd[k + "_전"] = (ec_ - pp) if pp is not None else None
        raw[n] = nd
    return tags


UNIT_JUMP = 100       # 한 분기 매출이 앞뒤 분기 둘 다의 이 배수를 넘으면 그 보고서 전체가 원 대신 천 · 백만 원 배수로 적힌 것(동성케미컬 2017 반기 ×1e6)


def _fix_report_unit(raw):
    """보고서 단위 오류 — 분기 매출이 앞뒤 분기 매출 둘 다의 100배를 넘으면 그 보고서의 손익 값(값 · 누적 · 비교 칸 모두)을 ÷1e6, 안 맞으면 ÷1e3
    (나눈 매출이 앞뒤 평균의 0.2~5배 안이면 맞음). 둘 다 안 맞으면 손익 칸을 비운다. 둘 다 품질 unit. 4분기는 연간 − 3분기 누적으로 견준다
    (사업보고서가 배수로 적혔으면 연간 쪽을 나눈다). per_share 의 EPS 단위 검사는 순이익 ÷ EPS 가 같은 배수면 못 잡는다 — 그래서 매출 수준으로 본다.
    raw 를 고친 사본으로 바꾸고 {n: [품질]} 을 돌려준다."""
    def qrev(m, src=None):
        d = src if src is not None else raw.get(m)
        if not d:
            return None
        if m % 4 + 1 != 4:
            return d.get("매출액")
        q3 = raw.get(m - 1) or {}
        a, c = d.get("매출액"), q3.get("매출액_누적")
        return (a - c) if (a is not None and c is not None and q3.get("_fs") == d.get("_fs")) else None
    tags = {}
    for n in sorted(raw):
        v, a, b = qrev(n), qrev(n - 1), qrev(n + 1)
        if not (v and a and b and a > 0 and b > 0 and v > UNIT_JUMP * a and v > UNIT_JUMP * b):
            continue
        d, mid = raw[n], (a + b) / 2
        fixed = None
        for div in (1e6, 1e3):
            nd = dict(d)
            for k in KEYS_IS:
                for suf in _IS_SUFS:
                    if nd.get(k + suf) is not None:
                        nd[k + suf] = nd[k + suf] / div
            v2 = qrev(n, nd)
            if v2 and 0.2 <= v2 / mid <= 5:
                fixed = nd
                break
        if fixed is None:
            fixed = dict(d)
            for k in KEYS_IS:
                for suf in _IS_SUFS:
                    fixed.pop(k + suf, None)
        raw[n] = fixed
        tags[n] = ["unit"]
    return tags


def series(corp_code, stock_code, years, prices=None, meta=None, offline=False, progress=None):
    """분기 시계열 v2 — n 오름차순 조밀 격자(첫 자료 분기 ~ 끝 자료 분기, 빈 분기 포함).
    meta = {filed: {n: 원본 공시일}, fy_bad: {연도}, amend: {(연도, 분기): 마지막 정정 공시일}, fin: bool}. fy_bad 연도는 받지 않고 'fy' 빈 칸으로만 낸다.
    amend 의 날짜가 원장 캐시 파일 날짜와 같거나 뒤면 그 분기 원장을 다시 받는다(_fetch).
    progress(done, total) 가 있으면 분기 하나를 받을 때마다 부른다(total = 연도 수 × 4, fy_bad 연도는 네 칸을 한 번에 센다) — 서버 진행률.
    끝나면 LAST(스레드별)에 transient · fy_bad · error 를 남긴다 — transient > 0 이면 일시 오류로 빠진 분기가 있다는 뜻이다."""
    meta = meta or {}
    filed, fy_bad = meta.get("filed") or {}, set(meta.get("fy_bad") or ())
    amend = meta.get("amend") or {}
    LAST.update(transient=0, fy_bad=sorted(fy_bad), error=None)
    raw = {}
    total, done = len(years) * 4, 0
    for y in years:
        if y in fy_bad:
            done += 4
            if progress is not None:
                progress(done, total)
            continue
        for q in (1, 2, 3, 4):
            try:
                kw = {"amend": amend[(y, q)]} if amend.get((y, q)) else {}      # 정정 없는 분기는 예전 호출 그대로
                if filed.get(_n(y, q)):
                    kw["filed"] = filed[_n(y, q)]                                 # 공시 전에 받아 둔 013 을 다시 받게(_fetch)
                d = period_data(corp_code, y, q, offline=offline, **kw)
            except Exception as e:
                LAST["error"] = "%s: %s" % (type(e).__name__, e)
                d = {"_transient": True}
            done += 1
            if progress is not None:
                progress(done, total)
            if d and d.get("_transient"):
                LAST["transient"] += 1
                continue
            if d:
                raw[_n(y, q)] = d
    fy_ns = [_n(y, q) for y in years if y in fy_bad for q in (1, 2, 3, 4)]
    if not raw and not fy_ns:
        return []
    raw_tags = {}
    for tg in (_fix_cum_in_quarter(raw), _fix_report_unit(raw)):     # 원장 단계 고침 — 3개월 칸의 누적 · 보고서 단위 배수
        for n_, t_ in tg.items():
            raw_tags.setdefault(n_, []).extend(t_)
    n0, n1 = min(list(raw) + fy_ns), max(list(raw) + fy_ns)
    pts = []
    for n in range(n0, n1 + 1):
        y, q = n // 4, n % 4 + 1
        p = {"year": y, "q": q, "label": "%dQ%d" % (y, q), "n": n, "품질": list(raw_tags.get(n, []))}
        d = raw.get(n)
        if d is None:
            p["품질"].append("fy" if y in fy_bad else "gap")
            pts.append(p)
            continue
        p["fs"] = d.get("_fs")
        q3, capex_ok = {}, True
        if q != 4:
            for k in KEYS_IS:
                p[k] = d.get(k)
                p[k + "_전"] = d.get(k + "_전")
        else:
            q3 = raw.get(n - 1) or {}
            same_fs = q3.get("_fs") == d.get("_fs")
            # 범위 검사 — 사업보고서 비교연도 ÷ 전년 사업보고서, Q3 비교 누적 ÷ 전년 Q3 누적 이 2% 넘게 다르면 연말 재작성
            pa, p3 = raw.get(n - 4) or {}, raw.get(n - 5) or {}
            scope_ok = True
            ra = (d.get("매출액_전연") / pa["매출액"]) if d.get("매출액_전연") and pa.get("매출액") else None
            r3 = (q3.get("매출액_전누적") / p3["매출액_누적"]) if q3.get("매출액_전누적") and p3.get("매출액_누적") else None
            if ra is not None and r3 is not None and abs(ra / r3 - 1) > 0.02:
                scope_ok = False
            for k in KEYS_IS:
                # 3분기 누적이 없으면 4분기 단독은 모른다 — 연간치를 대신 넣으면 4분기 합 · 전년 대비가 연간과 분기를 섞어 부푼다(EPS 로 겪음, 2026-10-07)
                ann, cum9 = d.get(k), q3.get(k + "_누적")
                ok = same_fs and scope_ok and ann is not None and cum9 is not None
                p[k] = (ann - cum9) if ok else None
                pa_, pc_ = d.get(k + "_전연"), q3.get(k + "_전누적")
                p[k + "_전"] = (pa_ - pc_) if (ok and pa_ is not None and pc_ is not None) else None
            capex_ok = same_fs and scope_ok         # CAPEX 의 연간 − 3분기 누적도 같은 기준 · 범위일 때만
            e9, n9 = q3.get("EPS_누적"), _ni_of(q3, "_누적")
            if e9 is not None and n9 is not None and e9 * n9 < 0:
                # 3분기 누적 EPS 와 누적 순이익의 부호가 반대(포스코인터내셔널 2022: EPS 누적 −4,042 · 순이익 +) — 연간 − 누적으로 뗀 4분기 EPS(8,822)가
                # 틀려 그 분기 역산 주식 수(1,030만 주 · 실제 1.23억)가 '12:1 병합'으로 읽혔다. 4분기 EPS 로 주식 수를 구하지 않는다(per_share)
                p["주식수_제외"] = True
            if d.get("매출액") is not None and p.get("매출액") is None:
                # 자료가 모자라면(3분기 없음 · 누적 없음) gap, 기준(CFS/OFS) · 범위가 어긋나면 basis
                p["품질"].append("gap" if q3.get("매출액_누적") is None else "basis")
        for k in ("재고자산", "매출채권", "유형자산", "자본총계"):
            p[k] = d.get(k)
        cx = d.get("CAPEX")
        cx_prev = 0 if q == 1 else (raw.get(n - 1) or {}).get("CAPEX")      # 현금흐름표는 누적 — 분기 값은 앞 누적과의 차
        p["CAPEX"] = (cx - cx_prev) if (capex_ok and cx is not None and cx_prev is not None) else None
        f0 = filed.get(n)
        rcs = [x for x in (d.get("_rcept"), q3.get("_rcept")) if x]       # 4분기는 3분기 누적 줄도 쓴다 — 그쪽 정정도 기준일에 든다
        cand = [x for x in [f0] + rcs if x]
        p["기준일"] = max(cand) if cand else None
        if f0 and any(x > f0 for x in rcs):
            p["품질"].append("amended")
        pts.append(p)
    by = {p["n"]: p for p in pts}
    # 이상값 — 그 분기와 바로 앞 분기(지우기 전 값)만 본다. 뒤 분기는 보지 않는다
    rev0 = {p["n"]: p.get("매출액") for p in pts}
    for p in pts:
        v = p.get("매출액")
        if v is None:
            continue
        if v <= 0:
            p["매출액"] = None; p["품질"].append("neg")
        elif rev0.get(p["n"] - 1) == v:
            p["매출액"] = None; p["품질"].append("dup")
    # 전년 대비 — 공시 당시(매출YoY) · 재작성(YoY_r)
    for p in pts:
        b = by.get(p["n"] - 4) or {}
        for k, tag in (("매출액", "매출"), ("영업이익", "영업이익")):
            a, v = b.get(k), p.get(k)
            p[tag + "YoY"] = None
            if a is not None and v is not None and a > 0:
                # 기저가 거의 0이면 증감률은 의미가 없다. 적자에서 흑자로 돌면 수천 %가 찍히는데 차트도 판단도 망가진다.
                # 이익은 매출의 1% 미만 기저를 버리고, 대신 영업이익률 변화(%p)로 본다.
                if tag == "영업이익" and b.get("매출액") and a < b["매출액"] * 0.01:
                    p[tag + "YoY_무의미"] = True
                else:
                    p[tag + "YoY"] = (v - a) / abs(a) * 100
            pr = p.get(k + "_전")
            key_r = "YoY_r" if tag == "매출" else "영업이익YoY_r"
            p[key_r] = (v - pr) / abs(pr) * 100 if (v is not None and pr is not None and pr > 0) else None
        if p.get("매출액") and p.get("영업이익") is not None:
            p["영업이익률"] = p["영업이익"] / p["매출액"] * 100
            # 지주회사는 영업이익에 지분법이익이 잡히는데 매출은 지주사 자체 매출뿐이라 비율이 수천 %로 튄다. 순위에 넣으면 안 되는 값이다.
            if abs(p["영업이익률"]) > 100:
                p["이익률_비정상"] = True
    for p in pts:
        prev = by.get(p["n"] - 1) or {}
        for tag in ("매출", "영업이익"):
            a, b_ = p.get(tag + "YoY"), prev.get(tag + "YoY")
            p[tag + "가속"] = (a - b_) if (a is not None and b_ is not None) else None
        p["이익률변화"] = (p["영업이익률"] - prev["영업이익률"]) if (p.get("영업이익률") is not None and prev.get("영업이익률") is not None) else None
    # TTM · 회전일수 — 연속 네 분기(키)일 때만. 회전일수의 분모는 TTM 매출이다.
    # 단일 분기 매출로 나누면 매출이 출렁이는 회사에서 지표가 망가진다.
    # (한미반도체 2026Q1 매출 509억 -> Q2 2,512억. 재고는 그대로인데 재고일수가 309일 -> 52일로 찍힌다. 재고가 준 게 아니라 분모가 커진 것.)
    for p in pts:
        win = [by.get(m) or {} for m in range(p["n"] - 3, p["n"] + 1)]
        p["매출_TTM"] = sum(w["매출액"] for w in win) if all(w.get("매출액") for w in win) else None
        p["영업이익_TTM"] = sum(w["영업이익"] for w in win) if all(w.get("영업이익") is not None for w in win) else None
        if p["매출_TTM"] and len({w.get("fs") for w in win}) > 1:
            p["품질"].append("basis")
        daily = p["매출_TTM"] / 365.0 if p["매출_TTM"] else None
        p["재고일수"] = (p["재고자산"] / daily) if (daily and p.get("재고자산")) else None
        p["매출채권일수"] = (p["매출채권"] / daily) if (daily and p.get("매출채권")) else None
        # CAPEX 강도 = 그 분기 CAPEX ÷ 그 분기 매출 × 100 (TTM 이 아니다) — 하나라도 없으면 None
        p["CAPEX강도"] = (p["CAPEX"] / p["매출액"] * 100) if (p.get("CAPEX") is not None and p.get("매출액")) else None
    for p in pts:
        p["품질"] = sorted(set(p["품질"]))
    return pts


def attach_prices(pts, stock_code, dates):
    """분기말 근처 주가로 PER. dates 는 {(year,q): 'YYYYMMDD'} (보고서 접수일)."""
    prices = FIN.fetch_prices(stock_code)
    for p in pts:
        d = dates.get((p["year"], p["q"]))
        if not d:
            continue
        px, pxd = FIN.price_on(prices, d)
        if not px:
            continue
        p["주가"] = px
        p["주가일"] = pxd
        if p.get("EPS_TTM") and p["EPS_TTM"] > 0:
            p["PER_TTM"] = px / p["EPS_TTM"]
    return pts


# ---------------------------------------------------------------- 본문 지표
# 표 안의 수치는 형식이 제각각이라, 뽑은 값과 함께 원문 줄을 같이 돌려준다.
# 숫자를 믿고 쓰기 전에 근거를 눈으로 확인할 수 있어야 한다.
TEXT_METRICS = [
    ("가동률", re.compile(r"가동률"), re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")),
    ("수주잔고", re.compile(r"수주\s?잔고|수주잔액"), re.compile(r"([\d,]{4,})")),
    ("생산능력", re.compile(r"생산\s?능력"), re.compile(r"([\d,]{3,})")),
]


def scan_text_metrics(text, limit=4):
    out = {}
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for name, key_rx, val_rx in TEXT_METRICS:
        hits = []
        for ln in lines:
            if not key_rx.search(ln):
                continue
            vals = val_rx.findall(ln)
            if not vals:
                continue
            nums = []
            for v in vals[:6]:
                x = FIN.num(v)
                if x is None:
                    continue
                if name == "가동률" and not (0 < x <= 100):
                    continue
                nums.append(x)
            if nums:
                hits.append({"line": ln[:400], "values": nums})
            if len(hits) >= limit:
                break
        if hits:
            out[name] = hits
    return out


# ---------------------------------------------------------------- 가속(B) · 국면 — 산업 업황 시계와 같은 식 · 같은 이름(2026-10-09)
PHASE_BAND = 3.0      # %p — 가속이 이 안이면 '유지'
PHASE_FLAT = 2.0      # % — 속도가 이 안이고 가속도 '유지'면 '정체'
PHASE_NAME = {(True, 1): "확장 가속", (True, 0): "확장 유지", (True, -1): "둔화",
              (False, 1): "회복", (False, 0): "부진 지속", (False, -1): "수축 심화"}


def phase_label(speed, acc):
    band = 1 if acc >= PHASE_BAND else -1 if acc <= -PHASE_BAND else 0
    if band == 0 and abs(speed) < PHASE_FLAT:
        return "정체"
    return PHASE_NAME[(speed > 0, band)]


def _turns(pts):
    """한 분기 부호 바뀜 — ▲ = B(n) ≥ +띠(3%p) 이고 B(n−1) < 0, ▼ = B(n) ≤ −띠 이고 B(n−1) > 0. n−1 은 분기 키로 찾고,
    B(n−1) 이 없으면(빈 분기 · 결산월 다른 해 · 값 없음) 변곡이 아니다. 부등호는 엄격하다(B(n−1) = 0 이면 변곡 아님).
    2026-10-10 사용자 결정으로 '띠를 건너는 규칙'(n 앞 가장 가까운 |B| ≥ 띠 분기가 4분기 안에 반대 부호)에서 되돌렸다 — 전 종목 엄격 표본에서
    한 분기 규칙 ▲−▼ +1.6 [−0.3, +3.6], 띠 규칙 +0.6 [−0.8, +2.4], 짝지은 차이(한 분기 − 띠) +0.97 [+0.09, +2.13](둘 다 통과 기준엔 못 미침)."""
    by = {p.get("n"): p for p in pts if p.get("n") is not None}
    for p in pts:
        b = p.get("가속B")
        p["변곡"] = None
        if b is None or abs(b) < PHASE_BAND:
            continue
        b1 = (by.get(p["n"] - 1) or {}).get("가속B")
        if b1 is None:
            continue
        if b > 0 and b1 < 0:
            p["변곡"] = "▲"
        elif b < 0 and b1 > 0:
            p["변곡"] = "▼"
    return pts


def accel(pts, basis="매출"):
    by = {p["n"]: p for p in pts}
    for p in pts:
        p.setdefault("품질", [])
        if basis == "영업이익":
            hist = [abs(by[m]["영업이익"]) for m in range(p["n"] - 4, p["n"]) if m in by and by[m].get("영업이익") is not None]
            base = (by.get(p["n"] - 4) or {}).get("영업이익")
            ok = base is not None and base > 0 and hist and base >= 0.2 * (sum(hist) / len(hist))
            r, a = (p.get("영업이익YoY_r"), p.get("영업이익YoY")) if ok else (None, None)
        else:
            r, a = p.get("YoY_r"), p.get("매출YoY")
        p["Y_asfiled"] = a
        if r is not None:
            p["Y"] = r
        else:
            p["Y"] = a
            if a is not None:
                p["품질"].append("asfiled")
    for p in pts:
        n = p["n"]
        w = [by.get(m) for m in range(n - 3, n + 1)]
        p["속도"] = p["가속B"] = p["C"] = p["국면"] = p["B기준일"] = None
        p["엇갈림"] = False
        if all(x is not None for x in w) and all(x.get("Y") is not None for x in w):
            ys = [x["Y"] for x in w]
            kinds = {"asfiled" in x["품질"] for x in w}
            if len(kinds) > 1:
                alt = [x.get("Y_asfiled") for x in w]
                if all(v is not None for v in alt):
                    ys = alt
                    p["품질"].append("mix")
                else:
                    ys = None
            if ys:
                s, s2 = (ys[3] + ys[2]) / 2, (ys[1] + ys[0]) / 2
                p["속도"], p["가속B"] = s, s - s2
                p["국면"] = phase_label(s, s - s2)
                dates = [x.get("기준일") for x in w if x.get("기준일")]
                p["B기준일"] = max(dates) if dates else None
        prev = by.get(n - 1)
        if prev and p.get("Y") is not None and prev.get("Y") is not None:
            p["C"] = p["Y"] - prev["Y"]
        b, c = p.get("가속B"), p.get("C")
        p["엇갈림"] = bool(b is not None and c is not None and abs(b) >= PHASE_BAND and abs(c) >= 5 and (b > 0) != (c > 0))
    _turns(pts)
    for p in pts:
        p["품질"] = sorted(set(p["품질"]))
    return pts


def b_lookup(points):
    """캐시 점 → {분기 키 n: (가속B, B기준일)} — 검증 도구가 공시마다 붙일 B 와, 그 B 를 셈한 자료가 다 나온 날."""
    return {p["n"]: (p.get("가속B"), p.get("B기준일")) for p in points or [] if p.get("n") is not None}


def b_known(lookup, n, t):
    """공시일 t(YYYYMMDD)에 알 수 있던 분기 n 의 가속(B) — B기준일 ≤ t 일 때만(엄격). 기준일이 t 뒤(뒤 정정 · 늦게 나온 앞 분기)이거나
    없으면 None. (구루렌즈_검증 · 구루적중률_백테스트 가 쓴다 — 가속기준_백테스트의 '공시 당시 알 수 있던 것만'과 같은 뜻)"""
    b, d = lookup.get(n, (None, None))
    if b is None or not d or str(d) > str(t):
        return None
    return b



# ---------------------------------------------------------------- 분기 주식 수 · 분할 보정 EPS
# 분기별 주식 수(지배순이익 ÷ EPS)를 거꾸로 구해, 한 분기에 1.8배 넘게 뛰거나 0.56배 밑으로 줄면 분할 · 병합으로 보고
# 그 전 분기를 지금 주식 수 기준으로 맞춘다(LS일렉트릭 2026.2분기 5:1 — 주가 자료는 이미 지금 기준이라 EPS 만 옛 기준으로 남아 PER 이 5배 작게 나왔다).
# 서버 _pipe_rows 와 가속도(per_share)가 같이 쓴다.
import datetime as _dt
SHEV_ADJ = re.compile(r"무상증자결정|유무상증자결정|주식분할결정|주식병합결정|감자결정")     # 주가 자료(수정주가)도 같이 보정되는 사건
SHEV_MIX = re.compile(r"회사합병결정|유상증자결정|주식교환|분할합병")                      # 주가 보정 없이 주식 수만 바뀌는 사건


def _qn(k):
    """분기 이름 → 연도×4 + 분기. 5번째 글자가 분기 숫자인 이름이면 된다('2026Q2' · '2026.2Q' 둘 다)."""
    return int(k[:4]) * 4 + int(k[5])


def _qend(lab):
    return int("%s%s" % (lab[:4], {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[int(lab[5])]))


def share_basis(sh, sev, cnt=None):
    """분기별 역산 주식 수 {label: 주식 수} → 지금 기준 주식 수. 서버 _pipe_rows 와 가속도가 같이 쓴다.
    sev = 그 회사의 주식 수 사건 공시 [(YYYYMMDD, 제목)], cnt(label) = 그 분기 보고서 개요의 분할 · 병합 · 무상증자 낱말 수(없으면 None — 정수 비율만 본다).
    {"now": {label: 지금 기준 주식 수}, "splits": [{after, at, ratio, kind}], "cut": 이 분기(_qn) 앞 기록은 지금 기준으로 맞출 수 없음 | None}"""
    sh = dict(sh)
    ks = sorted(sh, key=_qn)
    # 한 분기만 튀었다 바로 돌아온 값(HD현대일렉트릭 2018.4분기 21배 → 다음 분기 0.09배)은 자료 오류 — 버린다
    for i in range(1, len(ks) - 1):
        a_, b_, c_ = sh.get(ks[i - 1]), sh.get(ks[i]), sh.get(ks[i + 1])
        if a_ and b_ and c_ and not (0.56 < b_ / a_ < 1.8) and 0.8 <= c_ / a_ <= 1.25:
            sh.pop(ks[i], None)
    ks = [k for k in ks if k in sh]

    def events_between(after, at):
        """after 분기 말 90일 전 ~ at 분기 말 사이의 주식 수 사건 공시 — (주가 보정 사건, 주가 보정 없는 사건)"""
        lo = int((_dt.datetime.strptime(str(_qend(after)), "%Y%m%d") - _dt.timedelta(days=90)).strftime("%Y%m%d"))
        hi = _qend(at)
        ev = [nm for d_, nm in (sev or []) if d_ and lo <= int(d_) <= hi]
        return [x for x in ev if SHEV_ADJ.search(x)], [x for x in ev if SHEV_MIX.search(x)]

    def split_like(after, at, r_):
        """주식 수가 크게 바뀐 게 분할 · 병합 · 무상증자(주가 자료도 같이 보정됨)인가, 유상증자(주가는 그대로)인가.
        먼저 공시 목록(무상증자 · 주식분할 · 병합 · 감자 결정)으로 정하고(2026-10-05 — 1:1 · 1:2 무상증자 · 16:1 감자를 '증자 등'으로 잘못 보던 것),
        공시가 없을 때만 회사의 개요(자본금 변동 표) 낱말 · 정수 비율로 본다. 창에 합병 · 유상증자 공시만 있으면 정수 비율로 짐작하지 않는다
        (포스코인터내셔널 2022: 합병 결정만 있는 창에서 틀린 역산 주식 수 0.084배를 '12:1 병합'으로 읽었다)."""
        adj_, mix_ = events_between(after, at)
        if adj_:
            return True
        if cnt is not None:
            a_n, b_n = cnt(after), cnt(at)
            if a_n is not None and b_n is not None and b_n > a_n:
                return True
        if mix_:
            return False
        k = r_ if r_ >= 1 else 1 / r_
        return k >= 4.5 and abs(k - round(k)) <= 0.15

    def holds(j, chain):
        """chain[j] 의 주식 수 수준이 그 뒤 두 분기(chain 순서)에서 ±25% 안에 머무는가 → (판정, 처음 벗어난 분기).
        하나라도 벗어나면 False, 다 머물지만 뒤 분기가 둘이 안 되면 None(아직 모름), 둘 다 머물면 True."""
        base, later = sh[chain[j]], chain[j + 1:j + 3]
        bad = next((k for k in later if not (0.8 <= sh[k] / base <= 1.25)), None)
        if bad is not None:
            return False, bad
        return (True if len(later) >= 2 else None), None
    fac = {k: 1.0 for k in ks}             # 이 분기 뒤에 일어난 분할 비율의 곱
    splits = []
    cut = None                              # 분할과 합병 신주가 겹친 곳 — 그 앞 PER 기록은 지금 기준으로 맞출 수 없어 자기 역사에서 뺀다
    chain, j = list(ks), 1
    while j < len(chain):
        a, b = chain[j - 1], chain[j]
        r_ = sh[b] / sh[a]
        adj_, mix_ = events_between(a, b) if (r_ >= 1.25 or r_ <= 0.8) else ([], [])
        # 공시로 확인된 분할 · 무상증자는 1.25배(0.8배)부터 — 1:0.5 무상증자(헥토) · 두 분기에 걸친 100% 무상증자(노바렉스)
        if (r_ >= 1.8 or r_ <= 0.56) or adj_:
            kk = r_ if r_ >= 1 else 1 / r_
            if adj_:
                kind = "분할·병합"
                if mix_ and abs(kk - round(kk)) > 0.15:
                    # 분할 · 감자와 합병 신주 · 유상증자가 한 창에 겹쳤다(동원산업 5:1 분할 + 합병 = 10.6배, 미래산업 16:1 감자 + 증자) —
                    # 전체 비율로 보정하되, 그 앞 PER 기록은 정확히 맞출 수 없어 자기 역사에서 뺀다
                    kind = "분할·병합(증자 섞임 — 앞 기록 제외)"
                    cut = _qn(a) if cut is None else max(cut, _qn(a))
            else:
                # 공시 없는 분할은 새 주식 수가 뒤 두 분기 동안 ±25% 안에 머물러야 받는다. 머물지 않고 앞 수준 쪽으로 되돌아가면(그 사이에 공시된
                # 분할 · 병합이 없을 때) 그 분기는 자료 오류로 버리고 앞 분기와 다음 분기를 잇는다 — SK이노베이션 2023Q4 역산 7.6억 주가 5.88배 · 0.126배
                # '분할' 둘로 읽혀 그 앞 기록 전부에 ×0.743 이 걸렸다(2026-10-10 최종 검토). 다른 수준으로 가거나(합병 · 증자가 잇따름) 공시된 분할 ·
                # 병합 뒤에 바뀐 것이면(코스텍시스: 합병 뒤 주식 병합) 버리지 않는다
                h, c_ = holds(j, chain)
                if (h is False and abs(math.log(sh[c_] / sh[a])) < abs(math.log(sh[c_] / sh[b]))
                        and not events_between(b, c_)[0]):
                    chain.pop(j)
                    continue
                kind = "분할·병합" if (h and split_like(a, b, r_)) else "증자 등(주가 보정 없음)"
            splits.append({"after": a, "at": b, "ratio": round(r_, 2), "kind": kind})
            if kind.startswith("분할·병합"):
                for k in ks:
                    if _qn(k) <= _qn(a):
                        fac[k] *= r_
        j += 1
    return {"now": {k: sh[k] * fac[k] for k in chain}, "splits": splits, "cut": cut}


def per_share(pts, sev, cnt=None):
    """분기 주식 수(지배순이익 ÷ EPS) → 지금 기준 EPS_adj · EPS_TTM(보정).
    EPS_TTM_raw = 네 분기 EPS 의 단순 합 — 분할 · 병합 보정은 안 한 합(전 · 후 기준이 섞임)이다. 공시 원값의 합이 아니라 아래 단위 보정을 거친 EPS 의 합이다
    (단위 오류를 고친 분기는 p["EPS"] 를 바로 고쳐 쓰고, 못 고친 분기는 EPS 를 그대로 둔다).
    EPS 가 원 대신 천 · 백만 원 단위로 적힌 분기는 EPS 를 고쳐 쓰고 품질에 'unit' 을 단다. 못 고치는 이상값은 주식 수 열에서 빼고(이웃 분기 주식 수로 EPS_adj) 'unit' 만 단다.
    분할과 합병 신주가 한 창에 겹쳐 지금 기준으로 맞출 수 없는 구간(share_basis 의 cut)은 그 분기까지 모두 품질 'cut' — 자기 역사 PER 에서 뺄 표시다.
    역산 주식 수는 순이익 · EPS 부호가 같은 분기만. |순이익| ≥ 매출의 0.5% 조건은 그 분기에 매출액이 있을 때만 건다 — 매출 줄이 없는 은행 · 지주 ·
    IFRS17 뒤 보험사도 주식 수와 EPS_adj 를 낸다(2026-10-10 최종 검토; 한 분기 튐 · 단위 검사는 그대로). 3분기 누적 EPS 와 누적 순이익의 부호가 반대인
    해의 4분기(series 의 '주식수_제외')는 주식 수를 구하지 않는다.
    attach_prices 가 PER_TTM 을 EPS_TTM(보정)으로 계산하므로 순서는 series → per_share → accel → attach_prices."""
    by = {p["n"]: p for p in pts}
    imp = {}
    for p in pts:
        ni, e = _ni_of(p), p.get("EPS")
        if not (ni and e and ni / e > 0) or p.get("주식수_제외"):
            continue
        rev = p.get("매출액")
        if rev and abs(ni) < abs(rev) * 0.005:
            continue
        imp[p["label"]] = ni / e
    if imp:
        med = sorted(imp.values())[len(imp) // 2]
        for lab, s in list(imp.items()):
            if s < med / 300 or s > med * 300:
                p = next(x for x in pts if x["label"] == lab)
                for div in (1e3, 1e6):
                    if med / 1.8 <= s * div <= med * 1.8:
                        p["EPS"] = p["EPS"] / div
                        imp[lab] = s * div
                        break
                else:
                    imp.pop(lab)
                p["품질"] = sorted(set(p.get("품질", []) + ["unit"]))
    sb = share_basis(imp, sev, cnt) if imp else {"now": {}, "cut": None}
    now, cut = sb["now"], sb["cut"]
    for p in pts:
        if cut is not None and p["year"] * 4 + p["q"] <= cut:      # _qn 과 같은 척도 — cut 분기(포함) 앞 기록은 지금 기준으로 못 맞춘다
            p["품질"] = sorted(set(p.get("품질", []) + ["cut"]))
        ni = _ni_of(p)
        s = now.get(p["label"])
        if s is None and now:
            qk = p["year"] * 4 + p["q"]                       # _qn 과 같은 척도(연도×4 + 분기)
            near = min(now, key=lambda k: abs(_qn(k) - qk))
            s = now[near] if abs(_qn(near) - qk) <= 4 else None
        p["주식수"] = s
        p["EPS_adj"] = (ni / s) if (ni is not None and s) else None
    for p in pts:
        w = [by.get(m) or {} for m in range(p["n"] - 3, p["n"] + 1)]
        p["EPS_TTM_raw"] = sum(x["EPS"] for x in w) if all(x.get("EPS") is not None for x in w) else None
        p["EPS_TTM"] = sum(x["EPS_adj"] for x in w) if all(x.get("EPS_adj") is not None for x in w) else None
    return pts


# ---------------------------------------------------------------- 지금 PER
NOW_K_LO, NOW_K_HI = 0.55, 1.8     # k 가 이 사이 밖이면 캐시 뒤 분할 · 병합으로 주가 자료가 다시 보정된 것 — 지금 PER 을 믿지 않는다(stale)
NOW_PCT_WIN, NOW_PCT_MIN = 40, 8   # 백분위 창 — 'cut' 아닌 양수 PER_TTM 의 마지막 40개, 8개 이상(서버 저평가 per_pct 의 hist_per[-40:] 와 같다)


def split_after(pts, sev):
    """마지막 자료 분기(원장이 있는 분기 — 끝의 빈 gap · fy 칸은 뺀다) 말 뒤에 난 주가 보정 사건(SHEV_ADJ: 분할 · 병합 · 무상증자 · 감자)
    공시 [{date, title}]. 그 분기 EPS 는 사건 전 주식 수 기준인데 주가 자료는 사건 뒤 기준으로 다시 보정돼 PER 이 비율만큼 틀린다 —
    공시 제목으로는 비율을 정확히 못 읽어 분할 뒤 첫 보고서까지 PER 을 비운다(hold_per · now_per 의 reason). 정확한 보정은 계획 2(KIS 원 · 수정 주가 비)."""
    last = max((p["n"] for p in pts if p.get("fs")), default=None)
    if last is None:
        return []
    end = _qend("%dQ%d" % (last // 4, last % 4 + 1))
    return [{"date": str(d_), "title": nm} for d_, nm in (sev or [])
            if d_ and str(d_).isdigit() and int(d_) > end and SHEV_ADJ.search(nm or "")]


SPLIT_HOLD = "분할 뒤 첫 보고서 전 — PER 계산 보류"


def hold_per(pts, sa):
    """split_after(마지막 자료 분기 뒤 분할 · 병합 공시)가 있으면 모든 분기의 PER_TTM 을 비운다 — 주가 자료가 사건 뒤 기준으로 다시 보정되면
    분할 전 기준 EPS 와 짝이 맞지 않아 PER 이 비율만큼 틀린다(코나아이 재현: 다시 쌓으면 역사 PER 전부가 ÷2). 분할 뒤 첫 보고서가 나오면
    그 분기가 마지막 자료 분기가 되어 split_after 가 비고 PER 이 돌아온다. 비웠으면 True."""
    if not sa:
        return False
    for p in pts:
        p.pop("PER_TTM", None)
    return True


def pick_basis(pts, fin):
    """기준 지표 — 금융(KSIC 64~66)이고 최근 8개 자료 분기(원장이 있는 분기)에 매출액이 하나도 없으면 영업이익, 아니면 매출.
    역사 전체가 아니라 최근으로 본다 — IFRS17 뒤 매출 줄이 끊긴 보험사 · 증권사가 2016~2023 의 국면을 '지금'으로 들고 있었다(2026-10-10 최종 검토)."""
    if not fin:
        return "매출"
    recent = [p for p in pts if p.get("fs")][-8:]
    return "영업이익" if not any(p.get("매출액") for p in recent) else "매출"


FILED_WAIT = 30       # 일 — 원본 공시 뒤 이 날 수까지는 그 분기 원장이 비어 있으면 일시 오류로 본다(DART 반영 지연 · 공시 전에 받아 둔 013)


def _days(a, b):
    """YYYYMMDD 두 날의 차(b − a, 일)."""
    f = lambda s: _dt.datetime.strptime(str(s)[:8], "%Y%m%d")     # noqa: E731
    return (f(b) - f(a)).days


def filed_missing(pts, meta, today=None, wait=FILED_WAIT):
    """가장 최근에 원본 공시된 분기(결산월 다른 해 제외)의 원장이 시리즈에 없으면 그 분기 키 n — 서버 druck() 이 그 빌드를 캐시하지 않는다
    (공시 당일 DART 가 아직 013 을 주거나, 공시 전에 받아 둔 013 이 남은 채 새 서명으로 굳으면 다음 보고서까지 석 달을 한 분기 늦은 채로 보인다).
    공시일이 wait 일보다 오래됐으면 None — 원장이 끝내 없는 분기 때문에 회사가 영영 캐시되지 않는 일은 막는다."""
    meta = meta or {}
    filed, fy_bad = meta.get("filed") or {}, set(meta.get("fy_bad") or ())
    ns = [n for n in filed if n // 4 not in fy_bad]
    if not ns:
        return None
    n = max(ns)
    if any(p.get("n") == n and p.get("fs") for p in pts):
        return None
    today = today or time.strftime("%Y%m%d")
    try:
        if _days(filed[n], today) > wait:
            return None
    except ValueError:
        return None
    return n


def needs_net(corp_code, years, meta):
    """series(offline=True) 가 이 회사에서 DART 를 부를까 — _fetch 와 같은 판정(_net_need: 파일 없음 · 정정 공시 ≥ 파일 날짜 ·
    원본 공시 ≥ 파일 날짜인 013 · 013 다시 묻기). CFS 파일이 '없음'(013 · 빈 목록)이면 OFS 도 본다(본문 대체로 CFS 줄이 생기면 실제로는 안 볼 수도 있다 —
    그 경우 '필요하다'로 세어 건너뛰는 쪽으로 틀린다). 밤 미리 계산이 DART 예산을 다 쓴 뒤 네트워크 없이 쌓을 수 있는 회사만 계속 쌓을 때 쓴다."""
    meta = meta or {}
    filed, fy_bad, amend = meta.get("filed") or {}, set(meta.get("fy_bad") or ()), meta.get("amend") or {}
    for y in years:
        if y in fy_bad:
            continue
        for q in (1, 2, 3, 4):
            reprt, am, fl = REPRT_BY_Q[q], amend.get((y, q)), filed.get(_n(y, q))
            path = _ledger_path(corp_code, y, reprt, "CFS")
            if _net_need(path, y, reprt, am, fl)[3]:
                return True
            if _empty_ledger(path) and _net_need(_ledger_path(corp_code, y, reprt, "OFS"), y, reprt, am, fl)[3]:
                return True
    return False


def _no_eps_reason(points, last, fin=False):
    """최근 자료 분기 last 의 EPS_TTM 이 없거나 0 이하인 까닭 — 화면 KPI 문장."""
    by = {p.get("n"): p for p in points if p.get("n") is not None}
    if last.get("n") is None:
        return "최근 4분기 EPS 없음"
    w = [by.get(m) or {} for m in range(last["n"] - 3, last["n"] + 1)]
    if (last.get("EPS_TTM") or 0) < 0 or (last.get("EPS_TTM") == 0 and all(x.get("EPS_adj") is not None for x in w)):
        return "적자(최근 4분기 EPS 합 ≤ 0)"
    if any(not x.get("fs") for x in w):
        return "빠진 분기 포함(최근 4분기 EPS 합을 못 냄)"
    if any("basis" in (x.get("품질") or []) and x.get("EPS_adj") is None for x in w):
        return "기준 다른 4분기 포함(연결/별도 · 범위가 맞지 않는 Q4 — 그 분기 EPS 없음)"
    if all(x.get("주식수") is None for x in w):
        return ("금융사 " if fin else "") + "주식 수 산출 불가(순이익 ÷ EPS 를 못 구함)"
    return "EPS · 순이익이 빈 분기 포함"


def now_per(points, prices, splits=None, fin=False):
    """지금 PER(캐시하지 않는다) — 서버 _druck_now 가 지금 받은 수정주가 {YYYYMMDD: 종가} 로 부른다. 자료 분기가 하나도 없으면 None.
    per = 마지막 종가 ÷ (최신 EPS_TTM ÷ k) — 그 EPS_TTM 분기가 마지막 자료 분기(원장이 있는 마지막 분기)이거나 한 분기 앞일 때만.
    더 오래된 EPS_TTM(보험사 2024Q2 · 흥국화재 2015Q1 등)으로 '지금' PER 을 내지 않는다 — per None, reason 에 까닭, eps_label 에 마지막 EPS_TTM 분기.
    k = 캐시에 적힌 공시일 주가 ÷ 지금 받은 수정주가의 같은 날 종가 — EPS_TTM · 주가 · 주가일이 다 있는(그리고 그날 종가가 지금 자료에 있는) 마지막 분기로 잰다.
    stale = k 가 0.55~1.8 밖(경계 포함) — 캐시 뒤 주가 자료가 다시 보정됐다(서버가 한 번 다시 쌓는다).
    splits(split_after — 마지막 자료 분기 뒤 분할 · 병합 공시)가 있으면 per None · reason SPLIT_HOLD(PER_TTM 도 hold_per 가 비운다).
    pct = 지금 PER 이하 비율 — 'cut' 아닌 양수 PER_TTM 의 마지막 40개, 8개 이상일 때만. fin = 금융사(문장에 '금융사')."""
    data = [p for p in points if p.get("fs")]
    if not data:
        return None
    last_d = data[-1]
    sa = list(splits or [])
    eps_pts = [p for p in points if p.get("EPS_TTM")]
    ep = eps_pts[-1] if eps_pts else None
    out = {"px": None, "date": None, "per": None, "k": None, "pct": None, "stale": False, "split_after": sa,
           "reason": None, "eps_label": ep.get("label") if ep else None, "last": last_d.get("label")}
    k = 1.0
    if prices:
        ds = sorted(prices)
        out.update(px=prices[ds[-1]], date=ds[-1])
        kp = next((p for p in reversed(points)
                   if p.get("EPS_TTM") and p.get("주가") and p.get("주가일") and prices.get(p["주가일"])), None)
        k = kp["주가"] / prices[kp["주가일"]] if kp else 1.0
        out.update(k=round(k, 3), stale=not (NOW_K_LO < k < NOW_K_HI))
    behind = (last_d["n"] - ep["n"]) if (ep and ep.get("n") is not None and last_d.get("n") is not None) else 0
    if sa:
        out["reason"] = SPLIT_HOLD
    elif ep is None or behind >= 2:
        why = _no_eps_reason(points, last_d, fin)
        out["reason"] = ("최근 EPS_TTM 은 %s — %s 는 %s" % (ep["label"], last_d.get("label"), why)) if ep else why
    elif not prices:
        out["reason"] = "주가를 못 받음"
    else:
        eps = ep["EPS_TTM"] / k
        if eps <= 0:
            out["reason"] = "적자(최근 4분기 EPS 합 ≤ 0)"
        else:
            per = out["px"] / eps
            hist = [p["PER_TTM"] for p in points if (p.get("PER_TTM") or 0) > 0 and "cut" not in (p.get("품질") or [])][-NOW_PCT_WIN:]
            out.update(per=per, pct=(sum(1 for v in hist if v <= per) / len(hist) * 100) if len(hist) >= NOW_PCT_MIN else None)
    return out
