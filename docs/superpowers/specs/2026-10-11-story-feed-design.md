# 내러티브 탭 — 이 종목 소식 피드 (2026-10-11)

## 목적

증권사 앱의 '소식' 탭처럼, 고른 종목에 대해 **대중이 접한 소식**(언론 기사 제목 · 증권사 리포트 · 공시)과
**회사의 공식 문서**(정기보고서)를 날짜순 한 줄로 세운다. 왼쪽 = 날짜별 목록, 오른쪽 = 고른 소식의 상세.

기업추적만 가진 자료를 붙여 다른 앱과 다르게 만든다.

- 기사에 나온 말(예: '데이터센터')을 **회사는 보고서에서 언제부터 썼나**(낱말 궤적 `.cache/vocab`)
- 공시 제목에 **호재 · 확인 · 악재 분류**(호재.classify)와 **계약 원문 칸**(금액 · 매출 대비 % · 상대, `.cache/시너지/계약`)
- 정기보고서에 **한 줄 요약**(궤도 brief_gist, 있을 때만)
- 소식이 나온 날 **주가 등락과 시장(전 종목 중앙) 등락**, 5거래일 뒤

점수 · 매수 신호는 내지 않는다(새 문장 기반 선행 점수는 표본 외 검증 실패 — README 252–271).

## 구성

| # | 어디 | 무엇 |
|---|---|---|
| 1 | Tech `chart_screener/data/kis_news.py` + `python -m chart_screener news` | KIS 뉴스 제목 받기(조회 전용) → `Tech/cache/kis/news/<code>.json` |
| 2 | 기업추적 `내러티브.py` (표준 라이브러리만, 32비트) | 뉴스 분류 · 공시 색인 · 합치기 · 주가 반응 · 낱말 잇기 (순수 함수 위주) |
| 3 | 기업추적 `서버.py` | `story_view(code)` · 뒤에서 만들기 · 뉴스 받기 하위 프로세스 · `GET /api/story` |
| 4 | 기업추적 `웹/index.html` | `viewStory` — 탭 '내러티브'(data-t="story", 풍경 다음) |

이름 충돌 주의: `/api/narrative` · `narrative_view` · `vcNarr` 는 키워드 추이 탭의 '말과 주가' 기능이다. 건드리지 않는다.
새 탭의 키는 `story`, 서버 함수 `story_view`, 캐시 `.cache/story/`, CSS 접두사 `.st`.

---

## 1. Tech — KIS 뉴스 제목 받기

KIS API '종합 시황/공시(제목)': `GET /uapi/domestic-stock/v1/quotations/news-title`, tr_id `FHKST01011800`.
**조회 전용 시세 API 만 쓴다. 주문 · 계좌 API 는 쓰지 않는다.** 설정 파일 · 토큰은 열거나 찍지 않는다(기존 `km.client_or_none()` 사용).

파라미터: `FID_NEWS_OFER_ENTP_CODE=''`, `FID_COND_MRKT_CLS_CODE=''`, `FID_INPUT_ISCD=<code>`, `FID_TITL_CNTT=''`,
`FID_INPUT_DATE_1`, `FID_INPUT_HOUR_1`, `FID_RANK_SORT_CLS_CODE=''`, `FID_INPUT_SRNO`.
응답 `output` 40행: `cntt_usiq_srno`(19자리, 앞 14자리 = 등록 시각), `data_dt`, `data_tm`, `dorg`(출처 이름),
`hts_pbnt_titl_cntt`(제목), `news_ofer_entp_code`(제공사 1글자), `news_lrdv_code`, `iscd1`/`kor_isnm1`(대표 종목; 2..10 은 늘 빈칸).

실측 사실(2026-10-10 조사):
- 행은 쪽 안에서 `cntt_usiq_srno` 내림차순. 다음 쪽 커서는 **`('00'+srno[:8], srno[8:14], srno)`** (마지막 행 srno 로). `data_tm` 으로 커서를 주면 수정된 기사 때문에 뒤로 밀린다.
- 쪽끼리 1행 겹침 — 중복은 반드시 srno 로 지운다(겹침 수를 가정하지 않는다).
- 언론 기사는 **약 1년만 보관**. 그 앞은 거래소 · 코스닥 공시 제목(제공사 F/G/I)만 남는다.
- 호출 한도: 실효 **초당 1회**(0.28초 간격이면 두 번에 한 번 EGW00201). 별도 `RateLimiter(1.0)` 를 두고 `client.limiter` 는 바꾸지 않는다.
- 중소형주는 하루 수 건, 005930 같은 초대형주는 하루 150행 이상.

상수: `PATH_NEWS`, `TR_NEWS="FHKST01011800"`, `PAGE=40`, `NEWS_PER_SEC=1.0`, `FIRST_PAGES=60`, `NEWS_DAYS=400`, `CACHE_V=1`.

캐시 `Tech/cache/kis/news/<code>.json` (원자적 쓰기 — `chart_history._write` 와 같은 재시도 판):

```json
{"v":1,"code":"010170","at":"2026-10-11T09:00:00+09:00",
 "newest":"2026100817060166277","oldest":"2025092509082812345",
 "complete":true,"capped":false,"floor":"20250906","pages":44,
 "rows":[{"id":"2026100817060166277","d":"20261008","t":"170601","src":"인포스탁","pc":"7","lc":"02",
          "title":"…","c1":"397030","n1":"에이프릴바이오"}]}
```

- `rows` 는 id(srno) 내림차순, id 유일. 분류는 하지 않는다(원자료 보관 — 분류 규칙은 기업추적이 읽을 때 매긴다).
- **행을 지우지 않는다.** KIS 가 1년 지난 기사를 지우므로 이 캐시가 보관소다.

갱신 알고리즘 `update(client, code, cache, *, pages, floor, deadline, limiter)`:
1. 머리: 커서 없이 받는다. id 로 넣거나 덮어쓴다(수정 제목 반영). 쪽에 `id <= newest` 인 행이 있거나 행이 40 미만이면 멈춘다. `newest` = 받은 것 중 최대 id.
2. 꼬리(`complete` 가 False 일 때): `oldest` 커서로 더 오래된 쪽을 받는다. 다음이면 `complete=True`:
   행 40 미만 · 새 행 0 · 쪽 마지막 날짜 < `floor` · **쪽 전체가 공시 제공사(pc ∈ F,G,I)**.
3. 쪽 수 한도(`pages`) · 시간 한도(`deadline`)에 걸리면 `capped=True`, `complete` 는 그대로 두고 다음 실행에서 이어 받는다. 받은 데까지는 늘 저장.
4. 쪽 하나 실패: 치명 오류(`km.is_fatal`)가 아니면 `1+k` 초 쉬고 3번까지. 치명이면 전체 멈춤.

CLI (`__main__.py` 하위 명령, 고유 확인 문자열 `add_parser("news"`):

```
python -m chart_screener news --codes 010170,005930 [--pages 60] [--days 400] [--budget 120] [--per-sec 1.0] [--out DIR]
```

- 종료 코드 0 정상 · 1 클라이언트 없음 / 치명 오류 · 2 인자 오류. 끝에 한 줄 요약
  (`뉴스 제목: 2종목 · 새 412건 · 호출 23 · 12.3초 · 이어 받기 남음 1`).
- 테스트 `tests/test_kis_news.py`: 가짜 `get(path, tr_id, params)` 클라이언트(srno 커서 흉내, 1행 겹침), 증분 멈춤 · 꼬리 이어 받기 ·
  공시만 있는 쪽에서 끝 · floor · 중복 · EGW00201 재시도 · 치명 오류 중단 · 원자적 쓰기 · CLI 종료 코드.

---

## 2. 기업추적 `내러티브.py`

표준 라이브러리만(뷰어는 32비트 Python 3.11). 서버 전역에 기대지 않는 순수 함수 위주 — 서버가 자료와 함수를 넘긴다.

### 2.1 뉴스 분류 `classify_news(row, code, name) -> str` · `NEWS_RULE_V = 2`

| k | 뜻 | 기본 화면 |
|---|---|---|
| `art` | 이 종목 기사(제목에 회사 이름 또는 별칭 `ALIAS` — 005930 '삼전' · 000660 '하이닉스' · '하닉' · 005380 '현대차') | 보임 |
| `mention` | 테마 · 업종 기사(이 종목이 대표 종목으로 붙었지만 이름은 없음) | 보임 |
| `disc` | 거래소 · 코스닥 공시 제목(pc F/G/I). lc 03 이라도 상장 · 권리 안내(추가상장 · 변경상장 · 신규상장 · 재상장 · 권리락 · 배당락 · 액면분할 — `LISTING_RX`)는 여기 | 보임(DART 공시와 겹치면 지움 — 2.6) |
| `alert` | 시장조치(`ALERT_RX` — 투자주의 · 경고 · 매매정지 예고 · 공매도 과열 · 단일계좌 …, 또는 pc F/G lc 03 중 상장 · 권리 안내가 아닌 것) | 보임 |
| `info_list` | 인포스탁 자동 목록('상위 20 종목', '인기검색', '기술적 분석 특징주', '증시요약', '대차거래', '순매수,도 상위', '개장전★', '모닝 브리핑', '[MMDD주요일정]', '신규추천 종목') | 숨김 |
| `info_move` | 인포스탁 시세 띠 · 급등락 속보('X(069540) +5.91%, Y +3.43%' · '소폭 상승세') | 숨김 |
| `info_echo` | 인포스탁 공시 되풀이('소유주식수 변동' 등) | 숨김 |
| `robot` | 로봇 기사('NN일, 외국인 코스닥에서 …', '<코>X, 상한가 진입', 'HH:MM 현재 코스닥은 …', '[장중수급포착] …', "'X' 52주 신고가 경신, …", 'X, 상한가 기록') — 오른 날에만 나오는 틀 기사는 관심도 띠가 주가를 다시 그리게 한다 | 숨김 |
| `roundup` | 이 종목 이름 없는 시황('[증시키워드]', '[마감시황]', '코스피 … 마감', '[급등락주 짚어보기]', '[베스트&워스트]', '[특징주 & 리포트]', '[전날 애프터마켓]') | 숨김 |
| `ad` | 광고(딜사이트 lc 15, 스탁론, '최대 4배', 이벤트 · 강연회, 베스트 전문가, 투자지원금, MBN골드, 한경유레카, '론칭 기념' · '할인마감') | 숨김 |

규칙 순서: 공시(F/G/I) → 광고 → 로봇 → 인포스탁(lc 02 목록 · 시세 띠 · 되풀이; lc 01 작성 기사는 이름 있으면 art 아니면 mention)
→ 시황(이름 없을 때) → 이름 있음 `art` → 나머지 `mention`.
이름 비교는 '(주)' · 공백 · 가운뎃점을 지운 뒤. **숨김도 지우지 않는다** — 화면의 '잡음 n건 보기'로 펼친다.
같은 날 같은 제목(공백 · 기호 정규화)은 하나로 접고 `n`(건수)을 단다(가장 이른 시각 유지).

규칙은 2026-10-10 실측 제목의 꼴로 테스트한다(010170: 1,561행 중 약 75% 가 잡음, 005930: 대부분 쓸 만함).
테스트 제목은 실측 꼴(머리말 · 틀)만 본뜬 지어낸 제목 · 가짜 회사(가나광섬유 999990 · 다라전자 999991)다 — KIS 제목은 언론사 저작물이라
공개 저장소에 옮기지 않는다(5절).

### 2.2 공시 색인 (`.cache/공시목록` → 회사별)

원본: `{A001|B|I}_{YYYY}Q{n}.jsonl`, 닫힌 분기는 옆에 `….jsonl.done` 표지(내용이 다시 바뀌지 않음). 열린 분기(표지 없음)는 매일 06:30 통째로 다시 받는다.
줄 = `{"rcept_no","rcept_dt","corp_code","corp_name","stock_code","corp_cls","report_nm","flr_nm"}`.

- 색인 `.cache/공시목록/_by_code/b{00..63}.jsonl`, 버킷 = `zlib.crc32(code.encode()) % 64`.
  줄 = `[code, rcept_dt, rcept_no, kind, report_nm(공백 정리), flr_nm(회사 이름과 다를 때만, 아니면 "")]`.
- `_by_code/_manifest.json` = `{"v":1,"files":{파일명:[size, mtime]}}`. 닫힌 파일만 넣는다.
- `disc_index_update(disc_dir) -> dict`: 처음엔 `_by_code.tmp/` 에 다 만든 뒤 이름 바꿈. 이후엔 manifest 에 없는 닫힌 파일만 버킷에 덧붙인다.
  manifest 의 파일 크기 · mtime 이 바뀌었으면 처음부터 다시. **원본은 한 번에 한 파일만 메모리에**(최대 약 6MB).
- `disc_rows(code, disc_dir) -> list[dict] | None`: 버킷 줄 중 그 코드 + 열린 분기 파일을 bytes 로 읽어 `stock_code` 가 맞는 줄.
  `rcept_no` 로 중복 제거, 날짜 내림차순. 색인이 없으면 `None`(서버가 만들기 시작하고 '준비 중').
  돌려주는 꼴: `{"d","rcept","kind","title","flr"}`.
- 실측: 첫 빌드 약 20초(스트리밍), 조회 0.1초 안팎.

### 2.3 주가

- `adjusted(px: dict) -> list[(d, close)]`: 날짜순, 하루 ±30% 를 넘는 움직임(가격제한폭 밖 = 분할 · 병합)은 앞쪽을 비율로 맞춘다
  (`기록채점._adjusted` 와 같은 규칙).
- `day_moves(series, mkt=None) -> dict`: `{YYYYMMDD: {"chg": 그날 등락 %, "mkt": 그날 시장 중앙 % 또는 None}}` (거래일만).
- `reaction(series, d, after_close=False, mkt=None, untimed=False) -> dict`: 소식 날짜(휴장이면 다음 거래일, 장 마감 뒤 기사면 다음 거래일)를 반응일로 잡고
  `{"day": 반응일, "chg", "mkt", "d5": 5거래일 뒤 누적 %, "d5m": 같은 기간 시장 중앙 누적 % 또는 None}`.
  `untimed`(시각 모름)이고 d 가 거래일이면 **공시일 앞 종가 → 다음 거래일 종가(이틀)** 로 잰다: `day` = 다음 거래일, `"from"` = 공시일,
  `"timed": false`, `chg` · `mkt` 는 이틀 누적, `d5` · `d5m` 은 같은 앞 종가부터 다음 거래일 포함 5거래일째까지. 다음 거래일이 아직 없으면 None.
  쉬는 날 소식은 다음 거래일 하루(그 전에 나왔으니). 시각이 있는 DART 공시는 대부분 15:30 뒤(010170 26건 중 21건)라
  시각 모르는 공시(DART 줄 대부분 · 정기보고서 전부)를 공시일 하루로 재면 '공시 전날' 움직임이 된다.
- `build_mkt_med(read_px, codes, since) -> dict`: `{YYYYMMDD: 그날 전 종목 등락 중앙값 %}`. 서버가 하루 한 번 뒤에서 만든다
  (`.cache/story/_mkt_med.json`, since = 오늘 − 800일, 표본 20종목 미만인 날은 뺌).

### 2.4 낱말 잇기 (DART 와의 시너지)

- `vocab_links(vocab) -> list[dict]`: `.cache/vocab/{code}.json` 의 `tracks` 에서
  `{"term","first":YYYYMMDD,"first_label":"2022-12 사업보고서","from_start":bool,"take":YYYYMMDD|None,"now":단계|None,"snip":snip_first}`.
  `from_start` = 첫 언급이 모은 자료의 첫 보고서(track first == 0) — 그 앞은 자료가 없으니 화면은 '보고서 첫 언급' 대신 '자료 처음부터 있음'.
  개명(`renamed_from`)은 같은 줄에 둔다. 토큰 찌꺼기(2자 미만 · snip 없음)는 뺀다.
- `match_terms(title, links) -> list[str]`: 회사마다 한 번 만든 정규식. 한글은 띄어쓰기 무시 부분 일치,
  4자 이하 영문 · 숫자 말은 `(?<![A-Za-z0-9])…(?![A-Za-z0-9])` 경계.
- `hot_words(items, since, name, links, top=12, code="") -> list[dict]`: 기간 안 보이는 뉴스(art · mention) · 리포트 제목에서
  `[가-힣A-Za-z0-9]{2,}` 낱말을 소식 수로 센다. 회사 이름 · 별칭(`ALIAS[code]`가 든 말 — '삼전' · '삼전닉스') · 불용어(특징주 · 주가 · 상승 · 하락 · 강세 ·
  급등 · 목표가 · 코스피 · 외국인 · 협력 …) · 숫자 빼고, '株' 꼬리 정리(겹친 꼬리는 되풀이 — '광통신주도' → 광통신).
  `{"w","n","vocab":link|None}` — 회사 보고서 낱말과 맞으면 vocab 을 붙인다.

### 2.5 합치기 `build_feed(...) -> dict`

```
build_feed(code, name, *, today, news=None, news_meta=None, reports=(), discs=None, filings=(), gists=None,
           series=(), mkt=None, links=(), classify_disc=None, contracts=None) -> payload
```

- `news`: Tech 캐시 rows · `news_meta`: 캐시 머리(at · complete · capped · oldest) 또는 None(KIS 없음)
- `reports`: `_rep_rows()["by_code"][code]` 복사본 · `discs`: `disc_rows()` · `filings`: `S.co.reports` 꼴의 정기보고서 목록
- `gists`: `{rcept: {"gist": [gist 항목], "first": bool}}`(또는 `{rcept: [gist 항목]}`) — gist_v 가 지금 판인 brief 만, 빈 gist 도 ·
  `series`: `adjusted()` 결과 · `mkt`: `build_mkt_med` 결과 · `links`: `vocab_links()`
- `classify_disc(title) -> (g, cat, w, desc)` (호재.classify) · `contracts`: `{rcept: 계약 칸}`(캐시에 있는 것만)
- 공시 분류는 이 탭에서만 두 가지를 더한다(호재 탭 규칙은 그대로, `FEED_V` 가 sig 에 있어 바꾸면 캐시가 다시 만들어진다):
  - `DISC_EXTRA` — classify_disc 가 `(None, …)` 일 때만: 주식소각결정(호재 자사주소각) · 발행후만기전사채취득(호재 메자닌 소각) ·
    전환청구권 · 신주인수권 · 교환청구권 행사 / 전환 · 행사 · 교환가액 조정(악재 희석) · 불성실공시법인 지정(악재 상장 위험) · 소송등의판결(확인).
  - `GOOD_SOFT` — 제목만으론 방향을 모르는 '호재' 범주(실적 공시 · 배당확대 · 내부자 매수 · 대량보유 변동 · 투자판단 주요사항)는 `check` 로(범주 · 강도 · 설명은 그대로).

### 2.6 응답 꼴 (서버 ↔ 화면 계약)

```json
{"v":2,"code":"010170","name":"대한광통신","built":"2026-10-11 09:12",
 "px":{"last":16970,"date":"20261008","chg":-5.41,"series":[["20251010",12345.0]]},
 "src":{"news":{"ok":true,"at":"2026-10-11T09:00","complete":true,"capped":false,"oldest":"20250925","n":1561,"note":"",
                "shown":163,"cut":0,"cut_hidden":0},
        "reports":{"n":4,"from":"20251015","slim":0},
        "disc":{"n":248,"from":"20130104","index":"ready","cut":0},
        "filings":{"n":65}},
 "counts":{"news":163,"report":4,"disc":248,"filing":65,"alert":24,"hidden":1100},
 "hot":[{"w":"데이터센터","n":23,"vocab":{"term":"데이터센터","first":"20230315","first_label":"2022-12 사업보고서","now":"양산·출시","snip":"…"}}],
 "days":{"20261002":{"chg":5.24,"mkt":0.46,"news":7,"report":0,"disc":1,"filing":0,"alert":0}},
 "items":[ …최신 먼저… ]}
```

- `px.series`: 최근 1년 수정 종가(그림용). `days`: 최근 1년 거래일 전부 + 소식이 있는 날.
  `days[d].news` · `counts.news` 는 **크기로 덜어 내기 전** 보이는 뉴스 전부로 센다(관심도 띠가 1년 내내 맞게). 실제 items 에 실린 수는 `src.news.shown`.
- `src.news.ok=false` 면 `note` 에 사유('한국투자증권 연결 없음' · '받는 중' 등). 뉴스가 없어도 나머지는 그린다.
- `src.disc.index`: `"ready" | "building" | "missing"`. `src.news.cut` · `cut_hidden` · `src.reports.slim` · `src.disc.cut` = 크기로 덜어 낸 건수.

item 공통:

```json
{"id":"n:2026100817060166277","type":"news","d":"20261008","t":"1706","title":"…","src":"한국경제신문",
 "hide":false,"n":1,"tone":0,"terms":["데이터센터"],
 "re":{"day":"20261008","chg":-3.34,"mkt":-0.8,"d5":null,"d5m":null}}
```

- `type`: `news | report | disc | filing | alert`. `id` 접두사 `n: r: d: f: a:`. `t` 는 'HHMM' 또는 ''.
- `hide`: 잡음 분류(2.1)면 true. `tone`: 공시 good=1 · bad=−1 · 나머지 0, 리포트 목표가 상향=1 · 하향=−1.
- `terms`: 제목에 걸린 회사 낱말(2.4). `re`: 반응(2.3), 가격 없으면 null.
  시각 모르는 `disc` · `filing`(t 빈칸)이 거래일에 나왔으면 `re` 에 `"from"`(공시일) · `"timed":false` 가 붙고 `day` 는 다음 거래일(이틀 누적 — 2.3).
  화면은 그때 '공시일~다음 거래일'로 적고 '공시 시각을 몰라 공시일 앞 종가 → 다음 거래일 종가(이틀)로 잰다'를 단다.

type 별 덧붙임:
- `news`: `"k"`(2.1 분류), `"c1"`(대표 종목 코드), `"search"`(네이버 뉴스 검색 링크 `https://search.naver.com/search.naver?where=news&query=<제목 URL 인코딩>` — 사용자가 누를 때만 브라우저가 연다. 서버는 기사를 긁지 않는다).
- `report`: `"broker","opinion","tp","tp_prev","change","price_at","kind"(기업|산업),"lines","est","risks","concl","sections","msg_url","brk_url","url"(원문 — t.me 아닌 첫 URL)`.
  크기로 덜어 낸 옛 리포트는 `"slim":true` 이고 `lines · est · risks · concl · sections` 가 없다(화면은 상세 대신 원문 · 텔레그램 링크).
- `disc`: `"kind"(A001|B|I|KRX),"rcept","url"(DART),"flr","cls":{"g":"good|check|bad"|null,"cat","w","desc"},"contract":{kind,title,amount,revenue,pct,party,region,start,end}|null`.
  KIS 쪽 공시 제목(pc F/G/I, alert 아님)은 같은 날 DART 공시와 제목이 겹치면 버리고, 안 겹치면(오늘 · 어제처럼 DART 색인이 아직 없는 공시) `kind:"KRX"` 로 둔다.
  KIS 시장조치(alert)도 같은 날 시장본부(flr 에 '시장본부')가 DART 에 낸 같은 안내가 있으면 버리고 DART 줄에 시각만 빌려 준다.
- `filing`: `"rcept","label","stamp","tag","url","file"(본문 탭으로 열 첫 섹션 파일),"gist":[{"sec","text","tags"}]|null,"first":bool`.
  `gist` null = 아직 요약 없음(궤도 탭을 열면 만든다) · `[]` = 지금 판인데 요약할 변화가 없다(글 빈 항목은 뺀다) — `first` 면 견줄 앞 보고서가 없는 첫 보고서.
  `[]` 는 궤도 탭을 열어도 안 채워지니 화면은 '궤도 탭 열기'를 달지 않는다.
- `alert`: 추가 없음.

크기: 1MB 이하(`MAX_BYTES`). 숨김 항목도 싣는다(필드는 공통만). 넘으면 오래된 것부터 이 순서로 덜어 낸다:
숨김 뉴스 → 90일 넘은 리포트 머리만(`slim`) → 3년 넘은 공시(분류 없는 것 먼저) → 30일 넘은 보이는 뉴스 → 그래도 넘으면 보이는 뉴스.
리포트 · 공시가 많은 종목(005930 — 리포트 217KB · 공시 343KB)에서 뉴스만 덜면 보이는 뉴스가 며칠치로 줄고 띠가 비기 때문이다.
005930 실제 리포트 · 공시 + 1년 × 하루 150행 뉴스: 969KB · 보이는 뉴스 1,252건(12일치) · 리포트 156건 slim · 공시 588건 뺌 · 띠 365일 모두 건수 있음.

---

## 3. 서버 `story_view`

- 캐시 `.cache/story/{code}.json`(payload + `sig`). sig = `STORY_V.FEED_V.NEWS_RULE_V | 뉴스 파일 mtime | 리포트 sig | 공시 manifest mtime + 열린 분기 mtime |
  보고서 max(rcept).개수 | vocab 파일 mtime | brief 폴더 mtime | 시너지/계약 폴더 mtime | mkt_med 날짜 | price · ohlcv 파일 mtime | 오늘`.
  보고서 목록은 기간순이라 `[-1]` 은 옛 기간 [기재정정]을 놓친다 — max(rcept). 계약 폴더 시각은 시너지 탭이 계약을 새로 읽으면 바뀐다.
- sig 가 같으면 그대로. 다르면 **뒤 스레드 하나**(전역 `STORY_LOCK` · 한 번에 한 회사)가 다시 만들고, 그동안 있던 payload 를 `"stale":true` 로 준다. 없으면 `{"pending":true,"step":"…"}`.
- 다시 만들기가 실패하면 같은 sig 로 10분은 다시 안 만든다. 그때 있던 payload 가 있으면 `"build_error"` 를 실어 그대로 주고,
  없을 때만 `{"error"}` — 화면이 있던 피드를 버리지 않게.
- 리포트: `_rep_rows()` 는 콜드 74초 · 338MB 라 **뒤 스레드에서만** 부른다. 요청 스레드에서 부르지 않는다.
  `_rep_rows` 다시 읽기는 한 번에 하나(`REP_BUILD_LOCK`) — 리포트 탭 · 산업 리포트가 같은 때 불러도 기다렸다 그 결과를 쓴다(32비트에서 두 벌이면 메모리가 모자란다).
- vocab · brief · invest · 계약은 **캐시 파일만 읽는다**(만들지 않음 — `vocab_view` · `orbit` · `invest_view` · `SYN.contract` 를 부르지 않는다).
- 주가: `_px_file(code)` 만(네트워크 없음).
- 공시 색인: 없으면 뒤에서 한 번 만든다(전역 하나). 10분에 한 번까지 증분 확인.
- 시장 중앙: 하루 한 번 뒤에서 `build_mkt_med` (전 종목 `.cache/price` 읽기 약 100초, since = 오늘 − 800일). 준비 전엔 `mkt` 없이.
- 뉴스: Tech 하위 프로세스.
  - 조건: `TECH_PY` 가 있고 `_tech_supports('add_parser("news"')`.
  - 뉴스 파일이 없거나 30분보다 오래면(또는 `refresh=1`) 뒤 스레드에서
    `[TECH_PY, "-m", "chart_screener", "news", "--codes", code, "--pages", 60|10, "--budget", 100|30]`
    (첫 받기 60쪽/100초, 이후 10쪽/30초). 창 숨김 · `cwd=TECH_DIR` · `PYTHONIOENCODING=utf-8` · timeout 180초 · 전역 하나씩.
  - 차례 `STORY_NEWS["queue"] = {code: 마지막으로 물은 때}` — **가장 최근에 물은 회사부터**, `STORY_WANT_TTL`(120초) 동안 다시 안 물은 회사는
    빼고(화면이 3초마다 묻으니 떠난 회사다) `tried` 에 남기지 않는다(다시 오면 다시 줄 선다). 화면에 띄운 회사가 지나친 회사들 뒤에서 기다리지 않는다.
  - 끝나면 파일 mtime 이 바뀌어 sig 가 달라진다 → 다음 요청이 다시 만든다.
  - payload 에 `"news_running":true` 를 실어 화면이 3초마다 다시 묻게 한다.
- 라우트: `GET /api/story?code=X[&refresh=1]`. POST 없음.

## 4. 화면 `viewStory`

- 탭 단추 `<button data-t="story">내러티브</button>` 를 '풍경' 다음에, `show()` 맵에 `story:viewStory`.
- 머리: 회사 이름 · 코드 · 마지막 종가 · 전일 대비(한국식 빨강 오름 `--up` · 파랑 내림 `--dn` 새 토큰, 밝음 · 어두움 둘 다) · 자료 범위 한 줄
  (뉴스 2025.09.25~ · 리포트 4건 · 공시 2013~ · 정기보고서 65건).
- **요즘 이야기**: 최근 90일 `hot` 낱말 칩(건수, 회사 보고서와 맞으면 '보고서 첫 언급 2023.03 · 지금 양산·출시' — `from_start` 면 '자료 처음(2011-06 반기보고서)부터 있음'). 칩을 누르면 목록이 그 낱말로 걸러진다.
- **관심도 띠**(최근 1년): 날짜별 보이는 뉴스 건수 막대 + 주가 선 + 공시 표시(호재 ▲ / 악재 ▼) + 리포트 ◆. 마우스를 올리면 그날 숫자, 누르면 목록이 그날로 간다.
- 거르기: 전체 · 뉴스 · 리포트 · 공시 · 정기보고서 · 시장경보 칩 + '잡음 n건 보기' + 제목 검색.
- 두 칸(>1100px): 왼쪽 목록(자체 스크롤, `position:sticky`, 높이는 `main` 위치로 계산), 오른쪽 상세. ≤1100px 은 한 칸(목록 위, 상세 아래).
  - 날짜 머리 'YYYY.MM.DD (요일) · 주가 +5.24% (시장 +0.46%)'.
  - 줄: 종류 배지(뉴스 · 리포트 · 공시 · 보고서 · 경보) · 제목 두 줄 · '출처 · YYYY.MM.DD HH:MM' · `n>1` 이면 '×n'.
  - 처음 300줄, '더 보기'로 300씩.
- 상세:
  - 뉴스: 제목 · 출처 · 시각 · 분류 이름 · 반응(당일 / 5거래일, 시장 대비) · '이 말, 회사는 언제부터?'(terms → 첫 언급 보고서 · 지금 단계 · 첫 문장) · 같은 날 다른 소식 · '기사 찾아보기 ↗'(네이버 검색).
  - 리포트: 증권사 · 날짜 · 제목 · 투자의견 / 목표주가(이전 → 변경) / 당시 주가 / 상승여력 · 핵심 투자포인트 · 실적 전망 · 리스크 · 결론 · 원문 / 텔레그램 링크.
  - 공시: 제목 · 접수일 · 분류(호재 · 확인 · 악재 + 범주 · 설명) · 계약 칸(있으면) · 반응 · DART 링크.
  - 정기보고서: 이름 · 기간 · 접수일 · 한 줄 요약(있으면. null 이면 '요약 없음 — 궤도 탭을 열면 만든다' + '궤도 탭 열기', `[]` 면 `first` 에 따라 '첫 보고서 — 견줄 이전 보고서가 없다' · '요약할 변화가 없다'(궤도 단추 없음)) · '본문 열기'(`S.lastRead={rcept,file}; jump('read')`) · '변화 브리핑'(`S.briefRcept=rcept; jump('brief')`) · DART 링크.
  - 경보: 제목 · 날짜 · 반응.
- 폴링: `pending` · `stale` · `news_running` 이면 3초마다. `build_error`(있던 payload + 다시 만들기 실패)면 피드는 그대로 그리고 경고 한 줄. 리포트 `slim` 이면 상세 대신 링크만. 가드 `S.tab==='story' && S.co && S.co.code===code && box.isConnected`.
  새 payload 의 `built` 가 같으면 다시 그리지 않는다. 다시 그릴 때 고른 항목 · 거르기 · 스크롤을 지킨다.
- 외부 링크는 `target=_blank rel=noopener`.

## 5. 약관 · 자료 원칙

- KIS 뉴스 제목은 언론사 저작물이고 증권사 계정으로 받은 자료다 — **이 PC 의 본인 분석용**. 유료 상품(기업궤도추적 구독)에 넣지 않는다.
- 기사 본문은 받지 않는다. 화면의 '기사 찾아보기'는 사용자가 누를 때 브라우저가 네이버 뉴스 검색을 여는 링크일 뿐이다(서버가 긁지 않음).
- 리포트는 이미 모은 텔레그램 요약 그대로(원문 PDF 받지 않음).
- 개인 자료(`개인/`)는 쓰지 않는다.

## 6. 테스트

- Tech `tests/test_kis_news.py` (1절).
- 기업추적 `tests/test_내러티브.py`: 분류(실측 꼴 · 지어낸 제목) · 공시 색인 만들기 · 증분 · 조회(임시 폴더) · 접기 · DART/KRX 공시 겹침 ·
  상장 안내 · 시장본부 경보 합치기 · 공시 분류 보탬 · 주가 보정 · 반응(시각 모르는 공시 이틀) · 시장 중앙 · 낱말 잇기(from_start) · hot(별칭) ·
  크기 덜기 순서 · gist []/first · build_feed 꼴 · 서버 배선(build_error · sig · 뉴스 차례 · `_rep_rows` 한 번에 하나).
