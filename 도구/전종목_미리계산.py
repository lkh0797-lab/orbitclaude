# -*- coding: utf-8 -*-
"""
전 종목 미리 계산 (2026-10-11) — 풍경 · 궤도 캐시를 뷰어 밖에서 쌓아 탭을 열 때 기다리지 않게 한다.
설계: docs/superpowers/specs/2026-10-11-prebuild-all-design.md

    py -3.13 도구/전종목_미리계산.py                                   # 전부 — 1단계 풍경 → 2단계 궤도
    py -3.13 도구/전종목_미리계산.py --codes 005930,105560 --dart-cap 50 --workers 4
    python  도구/전종목_미리계산.py --phase orbit                       # 32비트 서버 파이썬도 된다(색인만 300MB)
    py -3.13 도구/전종목_미리계산.py --codes 005930 --anytime            # 밤에 손으로 — 풍경 시간 창(07:00–23:30)을 안 본다

뷰어의 '전 종목 미리 계산' 단추(/api/prebuild?run=1)가 이 파일을 창 없이 띄운다. 서버.py 를 모듈로 불러 함수만 쓴다(main 은 돌지 않음).
  · 색인은 .cache/색인.json 을 읽기만 — build_index 를 부르지 않는다(133MB 파일을 뷰어와 동시에 다시 쓰지 않게). JSON 오류면 몇 번 다시 읽는다.
  · 1단계 풍경: 캐시가 없거나 LAND_V 가 다른 회사만(날짜 지난 판은 뷰어가 지난 판을 먼저 보이고 뒤에서 새로 그린다). 순서는 _druck_order.
    이 도구가 부른 opendart 호출을 센다(requests 를 감싸 URL 로) — 달력 날짜별 상한 --dart-cap(기본 3000, 같은 날 다시 켜면 이어 센다,
    자정을 넘기면 그날 몫을 새로 센다). 회사 하나를 반쯤 하다 상한에 막히지 않게 여유가 --dart-reserve(기본 80 · 상한의 1/4 까지)보다
    적으면 그 회사부터 미룬다. 상한 · DART 020(한도) · 800(점검) · 키 오류 = 풍경을 멈추고(남은 곳 = 미룸, 날짜가 바뀐 뒤 이어 한다) 궤도로.
    풍경(DART 쓰는 단계)은 07:00–23:30(서버 PREBUILD_AUTO_FROM/TO)에만 — 밖이면 남은 곳을 미루고(land.stop "time") 궤도로 넘어간다
    (밤 수집 00:10 · 02:00 druck · 06:30 공시목록과 하루 한도를 겹쳐 쓰지 않게). --anytime 이면 시각을 안 본다.
  · 2단계 궤도: 요약(.cache/orbit/{code}.json)이 안 맞는 회사만, 보고서 적은 회사 먼저. 회사 안에서 보고서마다 brief → gist 를
    스레드 --workers 개로(드라이브 읽기가 겹쳐 약 3배), 마지막에 요약 파일.
  · 상태 PREBUILD_DIR/state.json(회사 하나 끝날 때마다 원자적으로) · 로그 run.log(일한 회사 한 줄) · 멈춤 = stop 파일(회사 사이 ·
    궤도는 보고서 5건마다 본다, 끝나면 지운다). 이어 하기 = 다시 실행 — 이미 된 것은 건너뛴다.
  · 시험용: --codes 대신 환경변수 PREBUILD_CODES(쉼표) · PREBUILD_DART_CAP · PREBUILD_DIR 도 듣는다(뷰어가 띄울 때 넘어온다).
"""
import os
import re
import sys
import json
import time
import struct
import argparse
import threading
import datetime as dt
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
STATE_V = 1
DART_HOST = "opendart.fss.or.kr"
DART_HALT = {"010", "011", "012", "020", "021", "800", "901"}     # 키 · 한도 · 점검 — 더 불러도 같은 답이다
DART_DAILY = {"cap", "020"}         # 날짜가 바뀌면 풀리는 멈춤(이 도구 상한 · DART 하루 한도). 점검 · 키 오류는 그대로
DART_RESERVE = 80                   # 회사 하나 풍경에 드는 DART 넉넉히(보통 10–20 · 원장 캐시 없는 회사는 더) — 이만큼 안 남으면 그 회사부터 미룸
LAND_HOURS = ((7, 0), (23, 30))     # 풍경을 하는 때 — 서버 PREBUILD_AUTO_FROM/TO 가 있으면 그것
LOG_MAX = 2 * 1024 * 1024


def load_server():
    sp = importlib.util.spec_from_file_location("서버", os.path.join(BASE, "서버.py"))
    S = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(S)
    return S


def load_index(S, tries=6, wait=10.0):
    """색인.json 을 읽기만 한다. 뷰어가 다시 쓰는 중(반쯤 쓴 파일)이면 JSON 오류 — 조금 쉬고 다시."""
    last = None
    for i in range(tries):
        try:
            with open(S.INDEX_PATH, "r", encoding="utf-8") as fh:
                idx = json.load(fh)
            if isinstance(idx, dict) and idx.get("companies"):
                return idx
            last = "회사가 없다"
        except (OSError, ValueError) as e:
            last = "%s: %s" % (type(e).__name__, e)
        if i + 1 < tries:
            time.sleep(wait)
    raise RuntimeError("색인을 읽지 못했습니다(%s)" % last)


class DartMeter:
    """이 프로세스가 부르는 opendart 호출을 센다 — requests.Session.request 를 감싼다(재무.py 는 requests.get → Session.request).
    상한(cap)에 닿았거나 halt(020 · 800 · 키 오류)를 본 뒤의 호출은 보내지 않고 ConnectionError — 부른 쪽(재무.fetch_*)은 일시 오류로 받아
    캐시하지 않는다. bad = 이번 회사에서 본 일시 오류(begin() 으로 비운다) — land_build 의 transient 로 넘긴다.
    used 는 달력 날짜(date)별 — 부를 때마다 today() 를 보고 날짜가 바뀌었으면 0 부터 다시 센다(시작한 날로 세면 자정을 넘겨 돈 판이
    다음 날 몫을 상한 넘게 쓴다). 그때 상한 · 020 멈춤은 풀리고 점검 · 키 오류는 그대로."""
    def __init__(self, cap, used=0, date=None, today=None):
        self.cap, self.used, self.halt, self.bad = int(cap), int(used), None, None
        self.today = today or (lambda: dt.date.today().isoformat())
        self.date = date or self.today()
        self.lock = threading.Lock()

    def _roll(self):
        """잠금 안에서 부른다."""
        d = self.today()
        if d != self.date:
            self.date, self.used = d, 0
            if self.halt in DART_DAILY:
                self.halt = None

    def halted(self):
        with self.lock:
            self._roll()
            return self.halt is not None or self.used >= self.cap

    def room(self, n):
        """오늘 몫이 n 건(적어도 1건) 남았나 — 모자라면 상한으로 멈춘다(회사 하나를 반쯤 하다 막혀 원장 · matrix 가 반쪽이 되지 않게)."""
        with self.lock:
            self._roll()
            if self.halt is None and self.cap - self.used < max(1, int(n)):
                self.halt = "cap"
            return self.halt is None

    def begin(self):
        self.bad = None

    def reason(self):
        return self.bad

    def _mark(self, why):
        if self.bad is None:
            self.bad = why

    def wrap(self, orig):
        meter = self

        def request(sess, method, url, *a, **kw):
            if DART_HOST not in str(url):
                return orig(sess, method, url, *a, **kw)
            with meter.lock:
                meter._roll()
                if meter.halt is None and meter.used >= meter.cap:
                    meter.halt = "cap"
                if meter.halt is not None:
                    meter._mark("DART %s" % ("상한" if meter.halt == "cap" else meter.halt))
                    import requests
                    raise requests.ConnectionError("미리 계산 DART 멈춤(%s)" % meter.halt)
                meter.used += 1
            try:
                r = orig(sess, method, url, *a, **kw)
            except Exception:
                meter._mark("DART 네트워크")
                raise
            st = None
            try:
                if getattr(r, "status_code", 200) >= 400:
                    st = "http%s" % r.status_code
                else:
                    js = r.json()
                    st = js.get("status") if isinstance(js, dict) else None
            except Exception:
                st = None                  # JSON 이 아닌 응답(zip 등) — 상태를 모른다
            if st is not None and st not in ("000", "013"):
                meter._mark("DART %s" % st)
                if st in DART_HALT:
                    with meter.lock:
                        meter.halt = meter.halt or st
            return r
        return request

    def install(self):
        import requests
        requests.sessions.Session.request = self.wrap(requests.sessions.Session.request)


class Prebuild:
    def __init__(self, S, pre_dir, codes=None, dart_cap=3000, workers=4, phase="all", now=dt.datetime.now, echo=True,
                 dart_reserve=DART_RESERVE, anytime=False):
        self.S, self.dir, self.codes = S, pre_dir, codes
        self.workers, self.phase, self.now, self.echo = max(1, int(workers)), phase, now, echo
        self.cap = int(dart_cap)
        self.reserve = max(0, min(int(dart_reserve), self.cap // 4))      # 시험용 작은 상한(--dart-cap 50)에서도 몇 곳은 돈다
        self.anytime = anytime
        self.state, self.meter, self._last_write = {}, None, 0.0

    # ------------------------------------------------------------ 파일
    def path(self, name):
        return os.path.join(self.dir, name)

    def read_state(self):
        try:
            with open(self.path("state.json"), "r", encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_state(self, force=True):
        t = time.time()
        if not force and t - self._last_write < 2.0:
            return
        self._last_write = t
        self.state["at"] = self.now().isoformat(timespec="seconds")
        if self.meter is not None:
            self.state["dart"].update(date=self.meter.date, used=self.meter.used, halt=self.meter.halt)
        self.S._atomic_json(self.path("state.json"), self.state)

    def log(self, msg):
        line = "%s %s" % (self.now().strftime("%m-%d %H:%M:%S"), msg)
        if self.echo and sys.stdout is not None:          # pythonw(서버 파이썬 대체 실행)는 출력이 없을 수 있다
            print(line, flush=True)
        try:
            with open(self.path("run.log"), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def stop_requested(self):
        return os.path.exists(self.path("stop"))

    # ------------------------------------------------------------ 시작
    def other_alive(self):
        prev = self.read_state()
        pid = prev.get("pid")
        if not pid or pid == os.getpid():
            return None
        try:
            since = dt.datetime.fromisoformat(prev.get("started")).timestamp()
        except (TypeError, ValueError):
            since = None
        return pid if self.S._pid_alive(pid, since) else None

    def begin(self):
        os.makedirs(self.dir, exist_ok=True)
        try:
            if os.path.getsize(self.path("run.log")) > LOG_MAX:
                os.replace(self.path("run.log"), self.path("run.log.1"))
        except OSError:
            pass
        prev = self.read_state()
        today = self.now().date().isoformat()
        pd = prev.get("dart") or {}
        used = int(pd.get("used") or 0) if pd.get("date") == today else 0      # 같은 날 다시 켜면 이어 센다
        self.meter = DartMeter(self.cap, used, today, lambda: self.now().date().isoformat())
        self.state = {"v": STATE_V, "pid": os.getpid(),
                      "py": "%d비트 %s" % (struct.calcsize("P") * 8, sys.version.split()[0]),
                      "started": self.now().isoformat(timespec="seconds"), "at": None,
                      "phase": "land" if self.phase in ("all", "land") else "orbit", "code": None,
                      "codes": self.codes, "stopped": None, "error": None,
                      "land": {"total": 0, "done": 0, "fresh": 0, "built": 0, "short": 0, "failed": 0, "deferred": 0},
                      "orbit": {"total": 0, "done": 0, "reports": 0, "gists": 0, "fresh": 0, "written": 0, "failed": 0},
                      "dart": {"date": today, "used": used, "cap": self.cap, "halt": None}}
        self.write_state()

    # ------------------------------------------------------------ 1단계 풍경
    def land_status(self, c):
        """fresh(LAND_V 같은 판 — 날짜 지난 판도) · short(부정 캐시, 새 보고서 없음) · need. 머리 몇백 바이트만 읽는다."""
        S = self.S
        try:
            with open(S._land_path(c["code"]), "rb") as fh:
                head = fh.read(400).decode("utf-8", errors="replace")
        except OSError:
            return "need"
        m = re.match(r'\{"v":\s*(\d+),\s*("error")?', head)
        if m and not m.group(2):
            return "fresh" if int(m.group(1)) == S.LAND_V else "need"
        d = S._land_read(c["code"])
        if not d:
            return "need"
        if d.get("error"):
            return "short" if (d.get("v") == S.LAND_V and d.get("nsig") == S._land_nsig(c)) else "need"
        return "fresh" if S._land_v(d) == S.LAND_V else "need"

    def land_open(self):
        """풍경(DART 쓰는 단계)을 해도 되는 때인가 — 뷰어 자동 이어 하기와 같은 창(07:00–23:30). 띄울 때만 보던 것을 돌 때도 본다:
        22:00 에 누르거나 23:15 에 이어 붙은 판이 00:10 수집 · 02:00 druck 와 하루 한도를 겹쳐 쓰지 않게. --anytime 이면 언제나."""
        if self.anytime:
            return True
        lo, hi = self.land_hours()
        t = self.now()
        return lo <= (t.hour, t.minute) < hi

    def land_hours(self):
        return (tuple(getattr(self.S, "PREBUILD_AUTO_FROM", None) or LAND_HOURS[0]),
                tuple(getattr(self.S, "PREBUILD_AUTO_TO", None) or LAND_HOURS[1]))

    def _defer(self, L, why):
        """남은 풍경을 미루기 시작한 이유를 한 번 남긴다 — land.stop = cap · 020 · 800 · … (DART, 날짜가 바뀐 뒤) | time(창이 다시 열리면)."""
        L["deferred"] += 1
        if "stop" not in L:
            L["stop"] = why
            self.log("풍경 — 남은 곳은 미룸(%s)" % ("%02d:%02d–%02d:%02d 밖" % sum(self.land_hours(), ()) if why == "time" else
                                               "DART %s · 오늘 %d/%d" % ("상한" if why == "cap" else why, self.meter.used, self.cap)))

    def run_land(self, comps):
        S, L = self.S, self.state["land"]
        order = S._druck_order(comps, lambda code: bool(code) and os.path.exists(S._druck_path(code)))
        L["total"] = len(order)
        self.log("풍경 시작 — %d곳 · DART %d/%d" % (len(order), self.meter.used, self.cap))
        for c in order:
            if self.stop_requested():
                self.state["stopped"] = "user"
                self.log("풍경 — 멈춤(stop 파일) %d/%d" % (L["done"], L["total"]))
                return False
            code, name = c.get("code"), c.get("name")
            self.state["code"] = code
            how = self.land_status(c)
            worked = False
            if how in ("fresh", "short"):
                L[how] += 1
            elif not self.meter.room(self.reserve):
                self._defer(L, self.meter.halt or "cap")    # 상한(여유 모자람) · 한도 · 점검 뒤 — 날짜가 바뀐 뒤 이어 한다
            elif not self.land_open():
                self._defer(L, "time")                      # 07:00–23:30 밖 — 창이 다시 열리면 뷰어가 이어 붙인다
            else:
                worked = True
                self.meter.begin()
                used0, t0 = self.meter.used, time.time()
                why = ""
                try:
                    d, how = S.land_build(c, None, self.meter.reason)
                    why = (d or {}).get("transient") or (d or {}).get("error") or ""
                except Exception as e:
                    how, why = "error", S._no_secret("%s: %s" % (type(e).__name__, e))
                soft = getattr(S, "DRUCK_SOFT", None)
                if isinstance(soft, dict):
                    soft.pop(code, None)                # 미캐시 druck 결과 기억 — 988곳 몫이 쌓이지 않게
                if how in ("built", "short"):
                    L[how] += 1
                    msg = "새로 씀" if how == "built" else "짧은 이력(부정 캐시)"
                elif self.meter.halted():
                    self._defer(L, self.meter.halt or "cap")
                    how, msg = "deferred", "미룸(%s)" % why
                else:
                    L["failed"] += 1
                    how, msg = "failed", "실패: %s" % why
                self.log("풍경 %s %s — %s · %.1f초 · DART %d건" % (code, name, msg, time.time() - t0, self.meter.used - used0))
            L["done"] += 1
            self.write_state(force=worked)
        self.log("풍경 끝 — 새로 %(built)d · 이미 %(fresh)d · 짧은 이력 %(short)d · 실패 %(failed)d · 미룸 %(deferred)d" % L
                 + " · DART %d/%d%s" % (self.meter.used, self.cap, " (멈춤 %s)" % self.meter.halt if self.meter.halt else ""))
        return True

    # ------------------------------------------------------------ 2단계 궤도
    def orbit_company(self, c):
        """보고서마다 brief(없으면 만든다) → gist(옛 판이면 뽑는다) — 스레드 workers 개. 다 되면 요약 파일.
        돌려줌 (built, gists, failed, written, stopped, err)."""
        S, code, reps = self.S, c["code"], c["reports"]
        O = self.state["orbit"]

        def one(rep):
            p = S.brief_path(code, rep["rcept"])
            had = os.path.exists(p)
            b = S.build_brief(c, rep)
            g = False
            if b.get("gist_v") != S.GIST_V:
                S._gist_of(c, rep, b, p)
                g = b.get("gist_v") == S.GIST_V
            return b, not had, g

        got, built, gists, failed, stopped, err = {}, 0, 0, 0, False, None

        def take(f, rep):
            nonlocal built, gists, failed, err
            try:
                b, nb, g = f.result()
                got[rep["rcept"]] = b
                built += nb
                gists += g
            except Exception as e:
                failed += 1
                err = err or S._no_secret("%s: %s" % (type(e).__name__, e))
        ex = ThreadPoolExecutor(max_workers=self.workers)
        futs, seen = {}, set()
        try:
            futs = {ex.submit(one, rep): rep for rep in reps}
            for i, f in enumerate(as_completed(futs), 1):
                seen.add(f)
                take(f, futs[f])
                if i % 5 == 0:
                    O["cur"] = {"code": code, "done": i, "total": len(reps)}
                    self.write_state(force=False)
                    if self.stop_requested():
                        stopped = True
                        break
        finally:
            ex.shutdown(wait=True, cancel_futures=True)
        for f, rep in futs.items():         # 멈출 때 돌던 것들 — 끝까지 돌았으니 센다
            if f not in seen and f.done() and not f.cancelled():
                take(f, rep)
        O.pop("cur", None)
        written = False
        if not stopped and not failed:
            rows = []
            try:
                for rep in reps:
                    b = got[rep["rcept"]]
                    if b.get("gist_v") != S.GIST_V:
                        rows = None
                        break
                    rows.append(S._orbit_row(rep, b, b.get("gist") or []))
            except Exception as e:
                rows, err = None, S._no_secret("%s: %s" % (type(e).__name__, e))
            if rows is not None:
                written = bool(S._orbit_sum_write(c, rows))
        return built, gists, failed, written, stopped, err

    def run_orbit(self, comps):
        S, O = self.S, self.state["orbit"]
        order = sorted(comps, key=lambda c: len(c.get("reports") or []))      # 보고서 적은 회사 먼저 — 빨리 많이 끝나게
        O["total"] = len(order)
        self.state["phase"] = "orbit"
        self.log("궤도 시작 — %d곳 · 스레드 %d" % (len(order), self.workers))
        for c in order:
            if self.stop_requested():
                self.state["stopped"] = "user"
                self.log("궤도 — 멈춤(stop 파일) %d/%d" % (O["done"], O["total"]))
                return False
            code, name = c.get("code"), c.get("name")
            self.state["code"] = code
            worked = False
            if S._orbit_sum_rows(c) is not None:
                O["fresh"] += 1
            else:
                worked = True
                t0 = time.time()
                built, gists, failed, written, stopped, err = self.orbit_company(c)
                O["reports"] += built
                O["gists"] += gists
                O["written"] += written
                O["failed"] += bool(failed or not written) and not stopped
                self.log("궤도 %s %s — 보고서 %d건 · brief 새로 %d · gist %d%s · %.0f초" % (
                    code, name, len(c.get("reports") or []), built, gists,
                    " · 요약 씀" if written else (" · 멈춤" if stopped else " · 요약 못 씀(실패 %d%s)" % (failed, ": " + err if err else "")),
                    time.time() - t0))
                if stopped:
                    self.state["stopped"] = "user"
                    self.write_state()
                    return False
            O["done"] += 1
            self.write_state(force=worked)
        self.log("궤도 끝 — 요약 새로 %(written)d · 이미 %(fresh)d · brief 새로 %(reports)d · gist %(gists)d · 못 끝냄 %(failed)d" % O)
        return True

    # ------------------------------------------------------------ 전체
    def run(self):
        S = self.S
        other = self.other_alive()
        if other:
            if self.echo and sys.stdout is not None:
                print("이미 돌고 있습니다(pid %s) — 그대로 둔다" % other, flush=True)
            return 0
        self.begin()
        self.meter.install()
        rc = 0
        try:
            idx = load_index(S)
            S.INDEX = idx
            comps = [c for c in idx["companies"] if c.get("code")]
            if self.codes:
                want = set(self.codes)
                comps = [c for c in comps if c["code"] in want]
            self.log("시작 — %s · 회사 %d곳%s · DART 상한 %d(오늘 %d 씀 · 회사 여유 %d) · 스레드 %d%s" % (
                self.state["py"], len(comps), " (고름 %s)" % ",".join(self.codes) if self.codes else "",
                self.cap, self.meter.used, self.reserve, self.workers, " · 시각 무관" if self.anytime else ""))
            ok = True
            if self.phase in ("all", "land"):
                ok = self.run_land(comps)
            if ok and self.phase in ("all", "orbit"):
                ok = self.run_orbit(comps)
            if ok:
                L = self.state["land"]           # 미룬 이유가 DART(상한 · 한도 · 점검)면 "dart" — 시간 창(time)은 멈춤이 아니다
                self.state.update(phase="done", code=None,
                                  stopped="dart" if L.get("deferred") and L.get("stop") not in (None, "time") else None)
                self.log("끝")
        except KeyboardInterrupt:
            self.state["stopped"] = "user"
            self.log("멈춤(Ctrl+C)")
            rc = 130
        except Exception as e:
            if sys.stderr is not None:
                import traceback
                traceback.print_exc()
            self.state.update(stopped="error", error=S._no_secret("%s: %s" % (type(e).__name__, e)))
            self.log("오류로 멈춤 — %s" % self.state["error"])
            rc = 1
        finally:
            self.write_state()
            try:
                os.remove(self.path("stop"))
            except OSError:
                pass
        return rc


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="전 종목 풍경 · 궤도 미리 계산")
    ap.add_argument("--codes", default=os.environ.get("PREBUILD_CODES") or "", help="쉼표로 고른 종목코드만(시험용)")
    ap.add_argument("--dart-cap", type=int, default=int(os.environ.get("PREBUILD_DART_CAP") or 3000), help="하루 opendart 호출 상한")
    ap.add_argument("--dart-reserve", type=int, default=DART_RESERVE,
                    help="회사 하나에 남겨 둘 DART 여유(상한의 1/4 까지) — 이보다 적게 남으면 그 회사부터 미룬다")
    ap.add_argument("--anytime", action="store_true", help="풍경 시간 창(07:00–23:30)을 안 본다(밤에 손으로 돌릴 때)")
    ap.add_argument("--workers", type=int, default=4, help="궤도 — 회사 안 보고서 스레드 수")
    ap.add_argument("--phase", choices=("all", "land", "orbit"), default="all")
    ap.add_argument("--dir", default=None, help="상태 · 로그 폴더(기본 PREBUILD_DIR 또는 .cache/prebuild)")
    return ap.parse_args(argv)


def main(argv=None, S=None):
    a = parse_args(argv)
    if S is None:
        S = load_server()
    codes = [x.strip() for x in a.codes.split(",") if x.strip()] or None
    pre_dir = a.dir or getattr(S, "PREBUILD_DIR", None) or os.path.join(S.CACHE_DIR, "prebuild")
    return Prebuild(S, pre_dir, codes=codes, dart_cap=a.dart_cap, workers=a.workers, phase=a.phase,
                    dart_reserve=a.dart_reserve, anytime=a.anytime).run()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
