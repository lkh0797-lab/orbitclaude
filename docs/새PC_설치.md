# 새 PC 에서 쓰기 (2026-10-15)

기업추적(뷰어 · 수집)과 Tech(차트 발굴)를 다른 PC 에서 돌리는 순서. 점검 · 설치 · 예약 작업 등록은 `새PC_설치.ps1` 한 개가 한다.

## 무엇이 어디로 오나

| 것 | git | 구글 드라이브 | 직접 옮김 |
|---|---|---|---|
| 코드 (기업추적 · Tech) | ✓ | ✓ | |
| 수집 원문 `기업추적_수집/` (수십 GB) · 캐시 `.cache/` | — | ✓ | |
| `.env` · `경로설정.txt` · `종목.txt` · `개인/`(매매 일지) | — | ✓ | |
| KIS 키 `%USERPROFILE%\KIS\config\kis_devlp.yaml` | — | — | **USB 등으로 직접** |
| 텔레그램 로그인 `%LOCALAPPDATA%\기업추적\telegram.session` | — | — | 새로 로그인 |
| 파이썬 · Tech 가상환경 · 예약 작업 | — | — | 스크립트가 만든다 |
| Claude 메모리 `%USERPROFILE%\.claude\projects\G---------Claude---\memory\` | — | — | 폴더째 복사하면 이어서 기억 |

**같은 구글 계정의 드라이브로 쓰는 것을 권한다.** GitHub 에서 받으면 코드만 오고 수집 원문 · 캐시가 없어 처음부터 며칠 수집해야 한다.

## 순서

1. **구글 드라이브 데스크톱** 설치 · 로그인 → `G:\내 드라이브\Claude` 가 보이는지. 드라이브 문자가 G: 가 아니면 `기업추적\경로설정.txt` 의 `DART_ENV_PATH` · `UNIVERSE_XLSX` 를 이 PC 경로로 고친다.
   - `Claude` 폴더를 오른쪽 클릭 → **오프라인으로 사용 가능** 으로. 스트리밍 상태면 파일 수만 개를 열 때마다 내려받아 매우 느리다.
2. **파이썬** — python.org 에서 Python 3.13 (64비트, 설치 때 'py launcher' · 'Add to PATH' 체크). 기업추적은 3.11 이상이면 32 · 64비트 모두 되고, Tech 는 64비트가 필요하다. 하나(3.13 64비트)로 둘 다 된다.
3. **KIS 키** — 옛 PC 의 `C:\Users\<이름>\KIS\config\kis_devlp.yaml` 을 USB 로 새 PC 의 같은 자리에 복사(드라이브 · git · 메신저 금지). 없으면 차트 발굴이 네이버 시세만으로 돈다.
4. **점검 → 설치** — PowerShell 에서:
   ```
   cd "G:\내 드라이브\Claude\주식\기업추적"
   powershell -ExecutionPolicy Bypass -File .\새PC_설치.ps1 -CheckOnly
   powershell -ExecutionPolicy Bypass -File .\새PC_설치.ps1
   ```
   '할 일' 줄이 남으면 그것부터 처리하고 다시 `-CheckOnly`.
5. **자동 작업** — 이 PC 에서 뷰어 · 밤 수집을 매일 돌릴 거면:
   ```
   powershell -ExecutionPolicy Bypass -File .\새PC_설치.ps1 -Schedule
   ```
   예약 작업 셋을 만든다 — 뷰어(매일 00:05 + 로그인 1분 뒤), 수집(매일 00:10), 점검(손으로). 뷰어가 저평가(06:30) · 차트 발굴 스캔(평일 20:15) · 수출 추적 갱신을 알아서 띄운다. 브라우저로 `http://127.0.0.1:8765`.
6. **텔레그램**(리포트 탭, 필요할 때만) — 터미널에서 `python 도구\텔레그램_로그인.py`, 전화번호 · 코드는 직접 넣는다.

## 두 PC 를 같이 쓸 때 — 지킬 것

- **자동 작업(-Schedule)은 한 PC 에서만.** 두 PC 가 같은 드라이브 폴더에 캐시를 동시에 쓰면 서로 덮고(드라이브가 `파일 (1).json` 같은 충돌 사본을 만든다) DART 하루 한도(약 2만 건)를 둘이 나눠 쓴다.
  - 옮겨 가는 거라면 옛 PC 에서: `Disable-ScheduledTask GiupChujeok_Viewer; Disable-ScheduledTask GiupChujeok_Collect`
- **뷰어도 한 번에 한 PC.** 다른 PC 에서 잠깐 볼 때는 자동 작업이 도는 PC 를 쉬게 하거나, 보기만 하고 '다시 계산' · '전 종목 미리 계산' 을 누르지 않는다.
- **git 커밋 · 푸시도 한 PC 에서.** `.git` 폴더도 드라이브로 동기화되는데, 두 PC 가 동시에 건드리면 저장소가 깨질 수 있다. 다른 PC 에서 고쳤으면 동기화가 끝난 뒤(드라이브 아이콘 확인) 다른 PC 에서 이어 작업한다.
- 시험 서버는 `python -X utf8 서버.py --port 8766 --no-auto` (자동 작업 없이).

## 확인

- 뷰어: `http://127.0.0.1:8765` → 저평가 탭이 뜨고, 회사 검색이 된다.
- 테스트: `python -X utf8 -m pytest -q tests` (그냥 `pytest` 는 수집 폴더 5만 개를 훑어 20분 넘게 걸린다).
- Tech: `%USERPROFILE%\.venvs\chart_screener\Scripts\python.exe -m pytest -q` (Tech 폴더에서).
