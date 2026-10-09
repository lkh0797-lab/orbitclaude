# -*- coding: utf-8 -*-
"""
매매 일지 — 실제로 한 매매를 '왜 샀는지'와 함께 적어 두고 돌아본다.

거래 한 건 = 매수 또는 매도 한 번. 매수 때 적은 출처(어느 탭에서 찾았나)·셋업·근거·
생각을 바꿀 조건·손절가는 그 매수분(로트)에 붙어 다닌다. 매도는 가장 오래된 로트부터
먹는다(FIFO). 그래서 청산 한 건 = 매수 로트 하나와 매도 하나가 맞물린 조각이고,
승률·손익비·출처별 성적은 이 조각들 위에서 낸다.

수수료·세금은 주당으로 나눠 붙인다. 매수 수수료는 그 로트 주식 수로, 매도 수수료는
판 주식 수로 나눈다. 일부만 팔아도 비용이 비율대로 따라간다.

개인 자료다. 저장소가 공개라 파일은 개인/ 아래(gitignore)에 둔다.
경로는 환경변수 ORBIT_TRADES_PATH 로 바꿀 수 있다.

저장은 임시 파일에 쓴 뒤 os.replace 로 바꿔 끼운다(쓰다 끊겨도 원본은 멀쩡).
덮어쓰기 전 하루 한 번 backup/매매일지_YYYYMMDD.json 으로 떠 두고 최근 30개만 남긴다.
깨진 파일은 읽지도 덮어쓰지도 않고 ValueError 를 낸다.

동시 접근 잠금은 부르는 쪽(서버)이 건다.
"""
import os
import re
import copy
import json
import math
import time
import uuid
import shutil
import tempfile
import statistics
import datetime as dt

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = "ORBIT_TRADES_PATH"
VER = 1
BACKUP_DIR = "backup"
BACKUP_PREFIX = "매매일지_"
BACKUP_KEEP = 30

# 아이디어가 나온 곳 — 화면 탭과 맞춘다. 순서가 곧 표시 순서다.
SOURCES = [
    ("val", "저평가"),
    ("dip", "억울한 낙폭"),
    ("syn", "시너지"),
    ("qtr", "분기 변화"),
    ("tech", "차트 발굴"),
    ("rep", "리포트"),
    ("exp", "수출 추적"),
    ("ind", "산업"),
    ("etc", "기타"),
]
SOURCE_LABEL = dict(SOURCES)
HORIZONS = {"short": "단기 (20~60거래일 · 손절)", "long": "장기 (~12개월)"}
HORIZON_NONE = "미지정"
# 달력일로 이만큼 넘게 들고 있으면 '기간 초과' — 단기는 60거래일에 여유, 장기는 12개월에 여유
HORIZON_DAYS = {"short": 90, "long": 400}
NEAR_STOP = 0.03          # 손절가 위 3% 안이면 '손절 근접'

MAX_MONEY = 1e9
MIN_PRICE = 0.01      # 가격 · 손절가 · 목표가 아래 한도 — 아주 작은 값이 수익률을 무한대로 만들지 않게
MAX_QTY = 10 ** 9
TEXT_MAX = {"name": 40, "setup": 60, "reason": 1000, "thesis_break": 1000, "memo": 2000}

LABEL = {
    "date": "날짜", "code": "종목코드", "name": "종목명", "side": "매수/매도",
    "price": "가격", "qty": "수량", "fee": "수수료·세금", "source": "출처",
    "setup": "셋업", "horizon": "기간", "reason": "근거", "thesis_break": "생각을 바꿀 조건",
    "stop": "손절가", "target": "목표가", "memo": "메모",
}
USER_FIELDS = ("date", "code", "name", "side", "price", "qty", "fee", "source", "setup",
               "horizon", "reason", "thesis_break", "stop", "target", "memo")
ORDER = ("id",) + USER_FIELDS + ("created", "updated")

_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BK_RE = re.compile(r"^" + BACKUP_PREFIX + r"(\d{8})\.json$")


# ---------------------------------------------------------------- 메타(화면용)
def sources_meta():
    return [{"key": k, "label": v} for k, v in SOURCES]


def horizons_meta():
    return [{"key": k, "label": v} for k, v in HORIZONS.items()]


# ---------------------------------------------------------------- 파일
def default_path():
    """환경변수 ORBIT_TRADES_PATH > 개인/매매일지.json. 폴더는 만들지 않는다."""
    p = os.environ.get(ENV_PATH, "").strip()
    if p:
        return os.path.abspath(os.path.expanduser(p))
    return os.path.join(BASE, "개인", "매매일지.json")


def empty():
    return {"ver": VER, "trades": []}


def _check_shape(data, what):
    if not isinstance(data, dict):
        raise ValueError("%s: 최상위가 객체가 아니다" % what)
    ver = data.get("ver", VER)
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1 or ver > VER:
        raise ValueError("%s: 모르는 형식 버전 %r (이 코드는 %d까지 읽는다)" % (what, ver, VER))
    trades = data.get("trades")
    if not isinstance(trades, list) or not all(isinstance(t, dict) for t in trades):
        raise ValueError("%s: trades 가 거래 목록이 아니다" % what)


def load(path=None):
    """{'ver':1,'trades':[...]}. 파일이 없으면 빈 일지, 깨졌으면 ValueError(파일은 그대로 둔다)."""
    path = path or default_path()
    if not os.path.exists(path):
        return empty()
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError as e:          # JSONDecodeError·UnicodeDecodeError 둘 다 ValueError
        raise ValueError("매매일지 파일이 깨져 있다 — 손대지 않았다: %s (%s)" % (path, e)) from None
    _check_shape(data, "매매일지 파일(%s)" % path)
    data.setdefault("ver", VER)
    return data


def _replace(src, dst):
    """os.replace — 드라이브 동기화가 잠깐 잡고 있으면 몇 번 다시 해 본다."""
    for i in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == 4:
                raise
            time.sleep(0.1 * (i + 1))


def _write_atomic(path, text):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _backup(path, day):
    """오늘 첫 저장이면 지금 파일을 backup/매매일지_YYYYMMDD.json 으로 떠 두고, 30개 넘는 옛것은 지운다."""
    bdir = os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, BACKUP_PREFIX + day.strftime("%Y%m%d") + ".json")
    if not os.path.exists(dst):
        fd, tmp = tempfile.mkstemp(prefix="." + BACKUP_PREFIX, suffix=".tmp", dir=bdir)
        os.close(fd)
        try:
            shutil.copyfile(path, tmp)
            _replace(tmp, dst)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    names = sorted((n for n in os.listdir(bdir) if _BK_RE.match(n)), reverse=True)
    for n in names[BACKUP_KEEP:]:
        try:
            os.remove(os.path.join(bdir, n))
        except OSError:
            pass


def save(path, data, today=None):
    """원자적 저장. 덮어쓰기 전 하루 한 번 백업. 기존 파일이 깨져 있으면 ValueError — 덮어쓰지 않는다."""
    path = path or default_path()
    _check_shape(data, "저장할 매매일지")
    out = dict(data)
    out["ver"] = VER
    # 직렬화부터 — NaN·이상한 값이면 여기서 터지고 디스크는 건드리지 않는다
    text = json.dumps(out, ensure_ascii=False, indent=1, allow_nan=False) + "\n"
    text.encode("utf-8")      # 깨진 글자(짝 없는 서로게이트)도 디스크를 건드리기 전에 터지게
    if os.path.exists(path):
        load(path)
        _backup(path, _as_date(today) or dt.date.today())
    _write_atomic(path, text)


# ---------------------------------------------------------------- 검증
def _as_date(v):
    """date·datetime·'YYYY-MM-DD'·'YYYYMMDD' → date. 안 되면 None."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        s = v.strip()
        if len(s) == 8 and s.isdigit():
            s = s[:4] + "-" + s[4:6] + "-" + s[6:]
        if _DATE_RE.match(s):
            try:
                return dt.date.fromisoformat(s)
            except ValueError:
                return None
    return None


def _is_num(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and math.isfinite(v)


def _money(raw, key, errs, out, required=False, positive=True, default=None):
    """숫자 칸 하나. positive=True 면 >0, 아니면 >=0. 비었으면 default."""
    v = raw.get(key)
    if v is None or (v == "" and not required):
        if required:
            errs.append("%s: 비어 있다" % LABEL[key])
        else:
            out[key] = default
        return
    if not _is_num(v):
        errs.append("%s: 숫자여야 한다 (%r)" % (LABEL[key], v))
    elif positive and v <= 0:
        errs.append("%s: 0보다 커야 한다" % LABEL[key])
    elif not positive and v < 0:
        errs.append("%s: 0 이상이어야 한다" % LABEL[key])
    elif v > MAX_MONEY:
        errs.append("%s: 10억 이하여야 한다" % LABEL[key])
    elif positive and v < MIN_PRICE:
        errs.append("%s: 너무 작다 (%s 이상)" % (LABEL[key], MIN_PRICE))
    else:
        out[key] = float(v)


def _text(raw, key, errs, out):
    v = raw.get(key)
    if v is None:
        out[key] = ""
        return
    if not isinstance(v, str):
        errs.append("%s: 글자여야 한다" % LABEL[key])
        return
    s = v.replace("\r\n", "\n").strip()
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        errs.append("%s: 깨진 글자가 있다" % LABEL[key])
        return
    if len(s) > TEXT_MAX[key]:
        errs.append("%s: %d자 이하여야 한다 (지금 %d자)" % (LABEL[key], TEXT_MAX[key], len(s)))
        return
    out[key] = s


def validate(raw, today=None):
    """사용자 입력 → (clean, errors). errors 가 비어야 쓸 수 있다. 모르는 키는 버린다."""
    if not isinstance(raw, dict):
        return {}, ["입력이 객체가 아니다"]
    t_day = _as_date(today) or dt.date.today()
    c, errs = {}, []

    v = raw.get("date")
    if not isinstance(v, str) or not _DATE_RE.match(v.strip()):
        errs.append("날짜: YYYY-MM-DD 형식이어야 한다")
    else:
        d = _as_date(v)
        if d is None:
            errs.append("날짜: 없는 날짜다 (%s)" % v.strip())
        elif d > t_day:
            errs.append("날짜: 오늘(%s)보다 뒤일 수 없다" % t_day.isoformat())
        else:
            c["date"] = d.isoformat()

    v = raw.get("code")
    s = v.strip().upper() if isinstance(v, str) else None
    if s is None or not _CODE_RE.match(s):
        errs.append("종목코드: 숫자·영문 대문자 6자리여야 한다 (%r)" % (v,))
    else:
        c["code"] = s

    v = raw.get("side")
    s = v.strip().lower() if isinstance(v, str) else None
    if s not in ("buy", "sell"):
        errs.append("매수/매도: buy 또는 sell 이어야 한다")
    else:
        c["side"] = s

    _money(raw, "price", errs, c, required=True)

    v = raw.get("qty")
    if v is None or v == "":
        errs.append("수량: 비어 있다")
    elif isinstance(v, bool) or not isinstance(v, int):
        errs.append("수량: 정수여야 한다 (%r)" % (v,))
    elif v <= 0:
        errs.append("수량: 1 이상이어야 한다")
    elif v > MAX_QTY:
        errs.append("수량: 10억 이하여야 한다")
    else:
        c["qty"] = v

    _money(raw, "fee", errs, c, positive=False, default=0.0)
    _money(raw, "stop", errs, c)
    _money(raw, "target", errs, c)

    v = raw.get("source")
    if v is None or v == "":
        c["source"] = "etc"
    elif isinstance(v, str) and v.strip() in SOURCE_LABEL:
        c["source"] = v.strip()
    else:
        errs.append("출처: 모르는 값 %r (%s 중 하나)" % (v, "·".join(k for k, _ in SOURCES)))

    v = raw.get("horizon")
    s = "" if v is None else (v.strip() if isinstance(v, str) else None)
    if s not in ("", "short", "long"):
        errs.append("기간: short·long·빈칸 중 하나여야 한다")
    else:
        c["horizon"] = s

    for k in ("name", "setup", "reason", "thesis_break", "memo"):
        _text(raw, k, errs, c)
    return c, errs


# ---------------------------------------------------------------- 변경
def _ordered(t):
    return {k: t.get(k) for k in ORDER}


def _replay_order(trades):
    """(날짜, 입력 시각) 순. 같으면 목록 순서 그대로(안정 정렬)."""
    return sorted(trades, key=lambda t: (_as_date(t.get("date")) or dt.date.max, str(t.get("created") or "")))


def _who(t):
    return "%s(%s)" % (t.get("name"), t.get("code")) if t.get("name") else str(t.get("code"))


def _feasible(trades):
    """거래를 순서대로 다시 돌려, 어느 시점에도 가진 것보다 많이 팔지 않았는지."""
    held = {}
    for t in _replay_order(trades):
        code, q = t.get("code"), t.get("qty")
        if not (isinstance(q, int) and not isinstance(q, bool) and q > 0) or _as_date(t.get("date")) is None:
            continue                     # 읽을 수 없는 행(손으로 고친 파일) — book 과 같이 건너뛴다
        if t.get("side") == "buy":
            held[code] = held.get(code, 0) + q
        elif t.get("side") == "sell":
            h = held.get(code, 0)
            if q > h:
                raise ValueError("%s %s 매도 %s주 — 그 시점 보유 수량보다 많이 판다 (보유 %s주)"
                                 % (t.get("date"), _who(t), q, h))
            held[code] = h - q


def _find(trades, tid):
    if not isinstance(tid, str) or not tid:
        raise ValueError("거래 id 가 없다")
    for i, t in enumerate(trades):
        if t.get("id") == tid:
            return i
    raise ValueError("그런 거래가 없다: %s" % tid)


def apply(data, action, payload, today=None, now_iso=None):
    """add·update·delete 를 적용한 새 일지. 입력은 건드리지 않는다. 문제가 있으면 ValueError."""
    new = copy.deepcopy(data) if data else empty()
    _check_shape(new, "매매일지")
    new["ver"] = VER
    trades = new["trades"]
    now_iso = now_iso or dt.datetime.now().isoformat(timespec="seconds")
    if not isinstance(payload, dict):
        raise ValueError("입력이 객체가 아니다")

    if action == "add":
        clean, errs = validate(payload, today)
        if errs:
            raise ValueError("; ".join(errs))
        clean["id"] = uuid.uuid4().hex
        clean["created"] = clean["updated"] = now_iso
        trades.append(_ordered(clean))
    elif action == "update":
        i = _find(trades, payload.get("id"))
        old = trades[i]
        merged = {k: old.get(k) for k in USER_FIELDS}
        merged.update({k: payload[k] for k in USER_FIELDS if k in payload})
        clean, errs = validate(merged, today)
        if errs:
            raise ValueError("; ".join(errs))
        clean["id"] = old["id"]
        clean["created"] = old.get("created") or now_iso
        clean["updated"] = now_iso
        trades[i] = _ordered(clean)
    elif action == "delete":
        del trades[_find(trades, payload.get("id"))]
    else:
        raise ValueError("모르는 동작: %r (add·update·delete)" % (action,))

    _feasible(trades)
    return new


# ---------------------------------------------------------------- 장부
def _won(x):
    """원 단위 반올림(0.5 올림). 무한대 · NaN 은 None."""
    return None if x is None or not math.isfinite(x) else int(math.floor(x + 0.5))


def _r(x, nd=2):
    if x is None or not math.isfinite(x):
        return None
    v = round(x, nd)
    return v if v != 0 else 0.0


def _src_label(k):
    return SOURCE_LABEL.get(k, k or SOURCE_LABEL["etc"])


def _hz_label(k):
    return HORIZONS.get(k, HORIZON_NONE)


def _stats(recs):
    """청산 조각 목록 → 승률·손익비·수익 팩터 등. 정의가 안 되면 None."""
    n = len(recs)
    wins = [r for r in recs if r["pnl"] > 0]
    losses = [r for r in recs if r["pnl"] < 0]
    avg_win = statistics.fmean(r["ret"] for r in wins) if wins else None
    avg_loss = statistics.fmean(r["ret"] for r in losses) if losses else None
    gain = sum(r["pnl"] for r in wins)
    loss = sum(r["pnl"] for r in losses)
    ex = [r["excess"] for r in recs if r["excess"] is not None]
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _r(len(wins) / n * 100) if n else None,
        "avg_win": _r(avg_win),
        "avg_loss": _r(avg_loss),
        "payoff": _r(avg_win / abs(avg_loss)) if avg_win is not None and avg_loss else None,
        "profit_factor": _r(gain / abs(loss)) if loss < 0 else None,
        "pnl": _won(sum(r["pnl"] for r in recs)),
        "avg_days": _r(statistics.fmean(r["days"] for r in recs), 1) if n else None,
        "ex_median": _r(statistics.median(ex)) if ex else None,
        "beat": _r(sum(1 for x in ex if x > 0) / len(ex) * 100) if ex else None,
    }


def _groups(recs, field, keys, label):
    """keys 순서대로, 청산이 있는 무리만. 목록에 없는 키는 뒤에 붙인다."""
    seen = []
    for r in recs:
        if r[field] not in keys and r[field] not in seen:
            seen.append(r[field])
    out = []
    for k in list(keys) + seen:
        sub = [r for r in recs if r[field] == k]
        if sub:
            g = {"key": k, "label": label(k)}
            g.update(_stats(sub))
            out.append(g)
    return out


def book(trades, price_of, bench_of=None, today=None):
    """거래 → 열린 로트·청산 조각·통계·합계 (JSON 그대로 내보낼 수 있는 dict).

    price_of(code) -> (종가, 'YYYYMMDD') 또는 (None, None).
    bench_of(d0, d1) -> 같은 기간 유니버스 수익률 중앙값(%) 또는 None. 날짜는 'YYYYMMDD'.
    출력의 날짜는 모두 'YYYY-MM-DD'. 돈은 원 단위, %는 소수 둘째 자리.
    """
    t_day = _as_date(today) or dt.date.today()
    warns = []

    prices = {}

    def _price(code):
        if code not in prices:
            try:
                r = price_of(code)
            except Exception:
                r = None
            close, d = r if isinstance(r, (tuple, list)) and len(r) == 2 else (None, None)
            if _is_num(close) and 0 < close <= MAX_MONEY:
                prices[code] = (float(close), _as_date(d))
            else:
                prices[code] = (None, None)
        return prices[code]

    benches = {}

    def _bench(d0, d1):
        if bench_of is None or d0 is None or d1 is None or d1 <= d0:
            return None
        key = (d0.strftime("%Y%m%d"), d1.strftime("%Y%m%d"))
        if key not in benches:
            try:
                b = bench_of(*key)
            except Exception:
                b = None
            benches[key] = float(b) if _is_num(b) else None
        return benches[key]

    names = {}
    lots = {}          # code -> [로트, ...] 산 순서
    raw_closed = []
    for t in _replay_order(trades or []):
        d, q, p, side = _as_date(t.get("date")), t.get("qty"), t.get("price"), t.get("side")
        ok_q = isinstance(q, int) and not isinstance(q, bool) and q > 0
        if d is None or not ok_q or not _is_num(p) or p <= 0 or side not in ("buy", "sell"):
            warns.append("읽을 수 없는 거래를 건너뛰었다: %s" % t.get("id"))
            continue
        fee = t.get("fee")
        fee = fee if _is_num(fee) and fee > 0 else 0.0
        code = t.get("code")
        if t.get("name"):
            names[code] = t["name"]
        if side == "buy":
            lots.setdefault(code, []).append({"t": t, "d": d, "rem": q, "fee_ps": fee / q})
            continue
        rem, fee_ps = q, fee / q
        queue = lots.get(code, [])
        while rem > 0 and queue:
            lot = queue[0]
            m = min(lot["rem"], rem)
            b = lot["t"]
            cost = m * (float(b["price"]) + lot["fee_ps"])
            proceeds = m * (float(p) - fee_ps)
            pnl = proceeds - cost
            ret = pnl / cost * 100
            bench = _bench(lot["d"], d)
            raw_closed.append({
                "buy_id": b.get("id"), "sell_id": t.get("id"), "code": code,
                "name": b.get("name") or t.get("name") or "",
                "qty": m, "buy_date": lot["d"].isoformat(), "buy_price": float(b["price"]),
                "sell_date": d.isoformat(), "sell_price": float(p),
                "cost": cost, "proceeds": proceeds, "pnl": pnl, "ret": ret,
                "days": (d - lot["d"]).days,
                "source": b.get("source") or "etc", "horizon": b.get("horizon") or "",
                "setup": b.get("setup") or "", "reason": b.get("reason") or "",
                "thesis_break": b.get("thesis_break") or "",
                "sell_reason": t.get("reason") or "", "sell_memo": t.get("memo") or "",
                "bench": bench, "excess": ret - bench if bench is not None else None,
            })
            lot["rem"] -= m
            rem -= m
            if lot["rem"] == 0:
                queue.pop(0)
        if rem > 0:
            warns.append("%s %s 매도 %s주 — 보유 수량보다 많이 판다, 초과분은 뺐다" % (d.isoformat(), _who(t), rem))

    # 열린 로트
    open_out = []
    tot_cost = priced_cost = priced_value = 0.0
    n_priced = 0
    asof = None
    open_lots = [lot for code in lots for lot in lots[code]]
    open_lots.sort(key=lambda lot: (lot["d"], str(lot["t"].get("created") or "")))
    for lot in open_lots:
        b, q = lot["t"], lot["rem"]
        code = b.get("code")
        cost = q * (float(b["price"]) + lot["fee_ps"])
        last, last_d = _price(code)
        days = (t_day - lot["d"]).days
        stop, target = b.get("stop"), b.get("target")
        stop = float(stop) if _is_num(stop) and stop > 0 else None
        target = float(target) if _is_num(target) and target > 0 else None
        hz = b.get("horizon") or ""
        value = pnl = ret = bench = excess = None
        if last is not None:
            value = q * last
            pnl = value - cost
            ret = pnl / cost * 100
            bench = _bench(lot["d"], last_d)
            excess = ret - bench if bench is not None else None
            priced_cost += cost
            priced_value += value
            n_priced += 1
            if last_d is not None and (asof is None or last_d < asof):
                asof = last_d
        tot_cost += cost
        flags = {
            "stop_broken": bool(stop and last is not None and last <= stop),
            "near_stop": bool(stop and last is not None and stop < last <= stop * (1 + NEAR_STOP)),
            "over_horizon": hz in HORIZON_DAYS and days > HORIZON_DAYS[hz],
            "no_price": last is None,
        }
        src = b.get("source") or "etc"
        rec = {
            "lot_id": b.get("id"), "code": code, "name": b.get("name") or names.get(code, ""),
            "buy_date": lot["d"].isoformat(), "qty": q, "price": float(b["price"]),
            "cost": _won(cost), "last": last,
            "last_date": last_d.isoformat() if last_d else None,
            "value": _won(value), "pnl": _won(pnl), "ret": _r(ret), "days": days,
            "source": src, "source_label": _src_label(src),
            "setup": b.get("setup") or "", "horizon": hz, "horizon_label": _hz_label(hz),
            "reason": b.get("reason") or "", "thesis_break": b.get("thesis_break") or "",
            "stop": stop, "target": target, "memo": b.get("memo") or "",
            "bench": _r(bench), "excess": _r(excess),
            "flags": [k for k, v in flags.items() if v],
        }
        rec.update(flags)
        open_out.append(rec)

    closed_out = []
    for r in raw_closed:
        o = dict(r)
        o.update({
            "cost": _won(r["cost"]), "proceeds": _won(r["proceeds"]), "pnl": _won(r["pnl"]),
            "ret": _r(r["ret"]), "bench": _r(r["bench"]), "excess": _r(r["excess"]),
            "source_label": _src_label(r["source"]), "horizon_label": _hz_label(r["horizon"]),
        })
        closed_out.append(o)

    n_open = len(open_out)
    stats = {
        "all": _stats(raw_closed),
        "by_source": _groups(raw_closed, "source", [k for k, _ in SOURCES], _src_label),
        "by_horizon": _groups(raw_closed, "horizon", ["short", "long", ""], _hz_label),
    }
    totals = {
        "cost": _won(tot_cost),
        "priced_cost": _won(priced_cost) if n_priced else (0 if not n_open else None),   # value · unreal 의 기준
        "value": _won(priced_value) if n_priced else (0 if not n_open else None),
        "unreal": _won(priced_value - priced_cost) if n_priced else (0 if not n_open else None),
        "unreal_pct": _r((priced_value - priced_cost) / priced_cost * 100) if n_priced else None,
        "realized": _won(sum(r["pnl"] for r in raw_closed)),
        "n_open": n_open,
        "n_closed": len(raw_closed),
        "n_no_price": n_open - n_priced,
        "price_asof": asof.isoformat() if asof else None,
    }
    return {"open": open_out, "closed": closed_out, "stats": stats, "totals": totals, "warnings": warns}
