# 전 종목 미리 계산 — 궤도 · 풍경 로딩 없애기 (2026-10-11)

## 문제

궤도 · 풍경 탭은 회사를 처음 열 때(풍경은 날마다) 계산하느라 기다리게 한다. 사용자 요청: '색인 갱신' 옆 단추 하나로 등록된 회사를 한 번에 미리 계산.

조사(2026-10-11, 32비트 · 실측):

- 궤도: 보고서마다 brief(직전 같은 종류 보고서와 섹션 diff) + gist(한 줄 요약). 네트워크 없음, **구글 드라이브 읽기가 87%**.
  988곳 중 102곳만 완성 · 879곳 없음 — 남은 보고서 45,380건, 순차 25–63시간, 프로세스/스레드 4개면 약 15시간.
  캐시가 다 있어도 `/api/orbit` 이 매번 brief JSON 을 전부 읽어 **5초 안팎**(KB금융 103건 5.0초).
- 풍경: 회사당 첫 빌드 20–45초(druck · matrix · DART 주식 수 · 연간 원장), 하루 지난 뒤 다시 7–10초.
  `_land_sig` 에 날짜가 들어 있어 **모든 풍경 캐시가 자정에 무효** — 미리 계산해도 다음 날이면 다시 로딩.
  첫 한 바퀴 DART 8–15천 건(하루 한도 20,000 을 수집기 · 공시목록 · druck 와 나눠 씀). 2015년 전 주식 수 호출은 늘 빈값.
- 32비트 뷰어는 이미 500–600MB, "can't start new thread" 기록 있음 — 일괄 계산을 뷰어 안에서 돌리면 안 된다.

## 해법 — 세 갈래

### A. 풍경: 지난 판을 먼저 보이고 뒤에서 새로 (stale-while-revalidate)

- `landscape_view`: 캐시 파일이 있고 `LAND_V` 가 같으면 sig(날짜 · 새 보고서)가 달라도 **그 판을 바로 돌려주고** `"stale": true`,
  뒤에서 `_run_land` 를 돌린다(이미 돌고 있으면 그대로). `LAND_V` 가 다르면 지금처럼 pending.
- 짧은 이력 오류('연간 재무가 4년 치도 안 됩니다')는 **부정 캐시**로 남긴다 — sig 에서 날짜를 뺀 `rcept:len:LAND_V` 가 같으면 바로 오류.
- 오류 30초 창이 빌드 시작 시각(`st["at"]`)에서 재지던 버그: 오류 난 시각을 따로 둔다.
- `_run_land` 쓰기를 원자적으로(고유 tmp → `os.replace`, PermissionError 재시도).
- 가격이 비었거나(`fetch_prices` 실패) 주식 수 호출이 일시 오류면 그 판은 저장하지 않는다(하루 동안 망가진 판이 남지 않게).
- `_land_shares`: **2015년 전 연도는 묻지 않는다**(DART 주식 수 API 범위 밖 — 늘 빈값). 회사당 DART 약 4–5건 절약.
- 화면 `viewLand`: `stale` 이면 판을 그리고 위에 '지난 판(YYYY-MM-DD) — 새로 그리는 중, 다 되면 바뀐다', 2초마다 물어 새 판이 오면 다시 그린다.

### B. 궤도: 회사별 요약 캐시

- `.cache/orbit/{code}.json` = `{"v": ORBIT_SUM_V, "sig": …, "rows": [...]}` — `orbit()` 이 brief 들을 읽어 만든 행(점수 · 분량 · gist 등, `orbit_scale` 전 값).
  sig = `ORBIT_SUM_V | GIST_V | 보고서 rcept 목록의 해시`. 모든 보고서에 brief 와 지금 판 gist 가 있을 때만 쓴다.
- `orbit()` 은 요약이 맞으면 brief 파일을 하나도 열지 않고 행을 쓰고 `orbit_scale` 만 다시 한다(5초 → 0.1초 안팎). 안 맞으면 지금처럼.
- `build_brief` 쓰기를 원자적으로, `_gist_of` tmp 이름을 프로세스 · 스레드마다 다르게(`path + ".%d.%d.tmp"`).
  뷰어와 미리 계산 프로세스가 같은 파일을 써도 결과가 같고(결정적) 반쯤 쓴 파일을 읽지 않는다.

### C. 미리 계산 프로세스 + 단추

- 새 도구 `도구/전종목_미리계산.py` — **뷰어 밖 자식 프로세스**(64비트 `py -3.13` = `_bt_cmd()`, 안 되면 `sys.executable`).
  - `서버.py` 를 모듈로 불러 함수만 쓴다(`main()` 은 돌지 않음). 색인은 `.cache/색인.json` 을 **읽기만**(`build_index` 를 부르지 않는다 — 133MB 파일을 뷰어와 동시에 다시 쓰지 않게). JSON 오류면 몇 번 다시 읽는다.
  - 1단계 풍경: 캐시가 없거나 `LAND_V` 가 다른 회사만(오래된 날짜 판은 A 로 충분). 순서는 `_druck_order` 처럼.
    - DART 상한: 이 도구가 하루에 쓰는 opendart 호출을 센다(`requests` 를 감싸 URL 로). 기본 `--dart-cap 3000`. 날짜별로 state 에 남겨 같은 날 다시 켜도 이어 센다.
      상한에 닿거나 DART 상태 020(한도) · 800(점검)을 보면 풍경 단계를 멈추고(남은 곳 = 미룸) 궤도 단계로 넘어간다.
    - 짧은 이력 오류는 부정 캐시(A)를 남긴다.
  - 2단계 궤도: brief 가 모자라거나 gist 가 옛 판이거나 요약(B)이 안 맞는 회사만. 회사 안에서 보고서 brief 를 스레드 `--workers 4` 로(드라이브 읽기가 겹쳐 약 3배),
    그다음 gist, 마지막에 요약 파일. 순서는 보고서 수 적은 회사 먼저(빨리 많이 끝나게).
  - 상태 `.cache/prebuild/state.json`(회사 하나 끝날 때마다 원자적으로):
    `{"v":1,"pid","py","started","at","phase":"land|orbit|done","code","stopped":null|"user"|"dart"|"error","error",
      "land":{"total","done","fresh","built","short","failed","deferred"},"orbit":{"total","done","reports","gists","fresh"},
      "dart":{"date","used","cap"}}`
  - 멈춤: `.cache/prebuild/stop` 파일을 회사 사이(궤도는 보고서 몇 건마다)에서 본다. 끝나면 지운다.
  - 로그 `.cache/prebuild/run.log`(한 회사 한 줄).
  - 이어 하기 = 다시 실행. 이미 된 것은 건너뛴다.
- 서버 `GET /api/prebuild` → state + `alive`(pid 살아 있나) + 로그 꼬리 8줄. `?run=1` 시작 · `?stop=1` 멈춤 — 둘 다 `_local_host()` 확인.
  한 번에 하나(살아 있는 pid 가 있으면 시작 안 함). 창 숨김 · `cwd=BASE` · `PYTHONIOENCODING=utf-8`. 빨리 죽으면(20초 안 비정상 종료) `sys.executable` 로 한 번 더.
- 자동 이어 하기: 뷰어가 켜지고 10분 뒤부터 한 시간마다 — state 가 끝나지 않았고(`phase != done`) 사용자가 멈춘 게 아니고 프로세스가 없으면 다시 띄운다.
  DART 로 미룬 풍경은 날짜가 바뀐 뒤에 이어 한다. **07:00–23:30 에만** 띄운다(밤 수집 · 02:00 druck · 06:30 공시목록/가격과 겹치지 않게).
- 단추 `<button class="ghost" id="prebuild">전 종목 미리 계산</button>` — '색인 갱신' 다음.
  - 페이지 열 때 상태를 한 번 묻고, 돌고 있으면 5초마다. 이름: '미리 계산 · 풍경 123/988' / '미리 계산 · 궤도 45/988' / '미리 계산 끝'.
    진행은 단추 배경 그라데이션으로(머리줄이 흔들리지 않게). title 에 단계별 수 · DART 사용/상한 · 마지막 로그.
  - 누르면: 안 돌 때 = 확인창(무엇을 · 얼마나 걸리나 · 멈출 수 있음 · 드라이브 용량) 뒤 `?run=1`. 돌 때 = 멈출지 확인 뒤 `?stop=1`.

## 비용 · 주의

- 궤도 전체는 여러 밤에 걸친다(4스레드 약 15시간). 결과는 영구(새 보고서만 더 계산).
- brief 캐시가 약 45,000 파일 · 2.5–3.5GB 늘어 구글 드라이브가 올린다.
- 풍경 첫 한 바퀴 DART 약 5–10천 건 → 하루 3,000 상한이면 2–3일에 걸쳐 끝난다. 이후엔 새 보고서 때만.
- 네이버 가격은 기존 `fetch_prices`(24시간 캐시, 06:30 가치 계산이 매일 갱신) 그대로 — 새 긁기 없음.

## 테스트

- 풍경 SWR · 부정 캐시 · 오류 창 · 저장 거부(가격 빔), `_land_shares` 2015 전 생략.
- 궤도 요약 sig(보고서 추가 · GIST_V 바뀜 → 무효), 요약으로 만든 행 = 원래 행.
- 도구: DART 셈 · 상한 · 020/800 멈춤 · stop 파일 · state 쓰기 · 이미 된 회사 건너뜀 · 색인 읽기 전용(가짜 서버 모듈로).
- `/api/prebuild` 로컬 확인 · 한 번에 하나.

## 구현 메모 — 설계와 다른 점 (2026-10-11, A · B · C 서버 · 도구)

- `_land_shares` 2015 전: 네트워크만 묻지 않고 **캐시에 있으면 읽는다**(2014 사업보고서 캐시 87곳 중 3곳은 값이 있다).
- 저장 거부(일시 오류) 범위를 넓혔다: 가격 빔 · 주식 수 외에 **연간 원장** 일시 오류(`_FinWatch` — `변곡점.fundamentals` 에 넘기는 FIN 대리, 전역은 안 건드림).
  도구는 그 회사 빌드 중 본 DART 비정상 상태(000 · 013 밖) · 네트워크 오류 · 상한 막힘도 `transient()` 로 넘긴다.
  가격 빔은 주가 캐시가 24시간 안에 새로 받은 것이면 일시 오류가 아니다(상장 폐지 등 정말 빈 주가 — 저장한다).
- 뷰어에서 새로 그리기가 일시 오류면: 지난 판이 있으면 그 판 + `"stale_error"` · `"refreshing": false`(10분 뒤 다시, `LAND_RETRY`),
  지난 판이 없으면 그 판을 메모리로만 10분 돌려준다(`"transient"` 표시, 저장 안 함). stale 응답에는 늘 `"refreshing"` 이 붙는다.
- `landscape_view(code, stale_ok=False)` — ⑥ 싸다 게이트(`dip`)는 지난 판(어제 주가)을 받지 않고 오늘 판을 기다린다
  (stale 을 받으면 셋씩 돌던 게이트가 회사마다 뒤 빌드를 한꺼번에 띄운다).
- 부정 캐시는 같은 경로 `.cache/landscape/{code}.json` 에 `{"v","error","nsig","code","at"}`.
- DART 멈춤 상태에 키 오류(010 · 011 · 012 · 021 · 901)도 넣었다 — 더 불러도 같은 답.
- 궤도 단계는 보고서마다 brief → gist 를 한 작업으로(스레드 풀 한 번) — 결과는 같다. 멈출 때 돌던 작업도 끝까지 세어 넣는다.
- state 덧붙임: `codes`(골라 돌린 판 — 자동 이어 하기 안 함) · `land.stop`(cap · 020 …) · `orbit.written/failed/cur`(회사 안 진행) · `dart.halt`.
  풍경이 DART 로 미뤄진 채 끝나면 `phase: done` + `stopped: "dart"`. `/api/prebuild` 는 방금 띄워 아직 state 를 안 쓴 동안 `phase: "start"`,
  그리고 `stop_pending` · `launch_error` 를 덧붙인다. 상태 보기(GET)는 다른 GET 처럼 열려 있고 run · stop 만 로컬 확인.
- 자동 이어 하기: state 가 없거나(한 번도 안 누름) `codes` 판이면 띄우지 않는다. 오류로 끝난 판은 3시간 뒤(`PREBUILD_ERR_WAIT`).
- 한 번에 하나: 뷰어는 Popen 손잡이 + state pid, 도구도 시작할 때 state pid 를 본다 — pid 재사용은 프로세스 생성 시각이 state `started` 보다 늦으면 남으로 본다(`_pid_alive`).
- 시험 · 손 실행용: 환경변수 `PREBUILD_DIR` · `PREBUILD_CODES` · `PREBUILD_DART_CAP`(뷰어가 띄울 때 그대로 넘어간다), 인자 `--dir` · `--phase`.
  자식 출력(import 실패 · 예외)은 `stdout.log`, `run.log` 는 2MB 넘으면 `run.log.1` 로 돌린다.

## 리뷰 고침 (2026-10-11, 서버 · 도구)

- **반쪽 원장이 캐시로 굳지 않게**(tool-1): 상한은 보통 어느 회사 빌드 한가운데서 닿는다. 그 뒤 막힌 `fetch_statement` 는 transient 를 달지만
  `matrix_cached` 는 그대로 `.cache/matrix/…json`(sig = 최신 접수번호)을 써서, 다음 날 이어 할 때 DART 를 묻지 않고 반쪽 판으로 풍경을 '새로 씀'했다.
  - `_fin_watch()` — `FIN.fetch_statement` 를 한 번 감싸(밖에서 부르면 그대로) 이 스레드가 그 안에서 받은 transient 를 모은다.
    `재무.statement_matrix` 는 fetch_statement 를 모듈 이름으로 불러 `_FinWatch` 대리를 넘길 수 없어서다.
  - `matrix_cached` · `inflect`(원장 + 주식 수 `sbad`) 는 그런 판을 돌려주기만 하고 쓰지 않는다(`"transient"` 표시). `landscape_build` 는 빌드 전체를
    감싸 분기 matrix · 변곡점 쪽 원장 일시 오류도 `"재무 원장 일시 오류"` 로 넘긴다(저장 안 함). matrix 쓰기는 원자적으로(`_atomic_json`).
  - 도구는 회사를 시작하기 전에 오늘 몫이 `--dart-reserve`(기본 80 · 상한의 1/4 까지) 넘게 남았는지 본다(`DartMeter.room`) — 모자라면 그 회사부터 미룸.
- **하루 상한은 달력 날짜로**(tool-2): `DartMeter` 가 부를 때마다 날짜를 보고 바뀌었으면 0 부터(상한 · 020 멈춤은 풀리고 점검 · 키 오류는 그대로),
  state 의 `dart.date` 도 그 날짜. 풍경 단계는 **07:00–23:30**(`PREBUILD_AUTO_FROM/TO`) 안에서만 — 밖이면 남은 곳을 미루고(`land.stop: "time"`,
  `stopped` 는 null) 궤도로. 자동 이어 하기는 `land.stop == "time"` 이면 같은 날에도 창 안에서 다시 띄운다. 손으로 밤에 돌릴 때 `--anytime`.
- **스레드를 못 띄우면**(correct-3): `landscape_view` 가 `LANDING` 칸을 만든 뒤 `Thread.start()` 가 'can't start new thread' 로 실패하면
  그 칸에 오류 · `err_at` 를 남긴다 — 지난 판이면 `stale_error`(10분 뒤 다시), 없으면 오류(30초 뒤 다시). 예전엔 오류 없는 칸이 남아 재시작까지 '그리는 중'.
- **run · stop 은 같은 출처만**(tool-4): Host 확인에 더해 `Sec-Fetch-Site` 는 same-origin · none, `Origin` · `Referer` 는 있으면 이 서버 주소여야 한다
  (`Handler._same_origin_get`). 다른 사이트의 `<img src>` · no-cors fetch 는 Host 가 맞아도 403. 셋 다 없으면(curl 같은 이 PC 의 도구) Host 만.
