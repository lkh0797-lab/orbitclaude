## Task C — 변화 브리핑 output quality audit (live API, 2026-10-21)

**Method.** `/api/companies` → `/api/orbit` last non-정정 row → `/api/invest`. All 10 resolved to the **2026-06 반기보고서** (YoY base 2025-06 반기); none returned pending. Fetcher: `C:\Users\lkh07\AppData\Local\Temp\claude\G---------Claude---\b5129638-ac40-4e19-9ffc-34cb92b7a4dc\scratchpad\audit_invest.py` (raw dumps `inv_<code>.json`, summary `run.log` in the same folder). Staleness was checked objectively with `stale_check.py` (same folder): each top-12 `new`/`num` sentence was searched in the three intervening reports (2025-09 · 2025-12 · 2026-03) via `/api/company` + `/api/text`; "STALE" below means the sentence is verbatim in at least one of them. UI cards were reconstructed from `웹/index.html` `invOnePager` (lines 12725–12793) and `INV_MON` (12006).

Verdict key: **G**=GOOD · **B**=BOILERPLATE · **M**=MISCLASSIFIED · **S**=STALE · **N**=NOISE. Column `m/d/h` = mag/dir/hz. Top 8 = display order (`signals[0..7]`).

### Per-company top 8

**하이록코리아 013030** (8 signals: new 3 · fin 5; scale op 589억)
| # | src | label | size | m/d/h | tags | text (≤80) | V |
|---|---|---|---|---|---|---|---|
|1|new|주주환원 · 20%|금액 미상|.31/+.5/.4|—|배당 목표는 배당성향 기준… 최근 10년 20% 이상 유지|**S** (in 25-12, 26-03)|
|2|new|주주환원 · 배당|금액 미상|.30/+.5/.4|—|주1) 상기 결산배당횟수는 1991년부터 2025년까지의 횟수임|**B** footnote|
|3|fin|이익률 -1.6%p|—|.34/-.31/.35|—|영업이익률 28.7% (-1.6%p)|G|
|4|new|고객 · 10%|중요|.46/+.12/.5|고객·전방|주요 고객에 대한 의존도… 주요고객은 다음과 같음|**B** table header; size "중요" came from a merged 9,588백만원 customer share|
|5|fin|매출 +9%|—|.25/+.23/.1|—|매출액 +9.1%|G|
|6|fin|ROE +0.5%p|—|.25/+.1/.75|—|ROE 3.1% (+0.5%p)|N|
|7|fin|유보금 +7%|—|.25/+.1/.85|—|유보금 +6.9%|N|
|8|fin|영업이익 +3%|—|.25/+.07/.15|—|영업이익 +3.4%|N|

**삼성전기 009150** (17: fin 8 · new 7 · num 1 · gone 1)
| # | src | label | size | m/d/h | tags | text | V |
|---|---|---|---|---|---|---|---|
|1|fin|영업이익 +107%|—|1/+1/.15|—|영업이익 +106.7%|G|
|2|fin|이익률 +5.1%p|—|1/+1/.35|—|영업이익률 12.7%|G|
|3|new|수주 · 공급계약체결|금액 미상|.74/+1/.5|수주·계약|당사는 한국거래소 공시 규정에 따라 단일판매ㆍ공급계약체결 공시를… 현황은 아래와 같음|**B** table intro — the contract table (counterparty/amount) is dropped|
|4|num|차입금 +44%|금액 미상|.71/-.74/.6|자금조달|변동이자율 차입금 879,162,536천원(전기말 738,267,028천원)… 100bp|G (6,088억→8,792억 YoY)|
|5|fin|매출 +24%|—|.66/+.6/.1|—|매출액 +24.2%|G|
|6|fin|레버리지 4.4배|—|.66/+.6/.3|—|이익이 매출보다 4.4배 빨리 늘었다|G|
|7|new|수주 · FCBGA|금액 미상|.46/+1/.5|수주·계약|FCBGA는 고성장이 예상되는 서버 CPU와 AI가속기… 수주를 확대하고, Top Tier 고객과의 신뢰|**B** self-praise, 수주 dir 1.0|
|8|new|고객 · BGA|금액 미상|.46/+.72/.5|고객·전방|BGA는 High-end 스마트폰 AP, ARM CPU… 공급 확대를 추진|**B**|
Also #10 "매출 10% 이상 거래처 없음" scored dir **-0.6** (M); #12 PBR 10.8배 (+720%) is a price move, not a report fact.

**HD현대중공업 329180** (17: fin 8 · new 8 · num 1)
| # | src | label | size | m/d/h | text | V |
|---|---|---|---|---|---|---|
|1|fin|매출 +53%|—|1/+1/.1|매출액 +52.7%|G (but HD현대미포 합병 2025-12 inflates YoY)|
|2|fin|영업이익 +121%|—|1/+1/.15|영업이익 +120.6%|G|
|3|fin|이익률 +5.1%p|—|1/+1/.35|영업이익률 16.4%|G|
|4|fin|부채비율 -41%p|—|1/+1/.6|부채비율 179%|**M** merger artefact|
|5|fin|유보금 +84%|—|1/+1/.85|유보금 +84.3%|**M** merger artefact|
|6|fin|ROE +4.4%p|—|.97/+.88/.75|ROE 7.8%|G|
|7|new|수주 · 65%|금액 미상|.54/+1/.5|친환경 엔진 비중이 전체 수주의 65% 이상|**S** (26-03)|
|8|fin|레버리지 2.3배|—|.66/+.6/.3|—|G|
#9 리스크·Shadow "미국-이란 종전… 그림자 선대 퇴출 가속" dir **-1.0** (M: positive replacement-demand prose); #10 신사업·HD "대기배출시설… 폐쇄신고 완료" +.92 (M, S) merged with the stale 합병 sentences; #12 특수관계·군산조선소 자산양수도 (2026-06-26 이사회) is the one genuinely new fact (G) but is labelled as a related-party risk.

**아바코 083930** (17: fin 5 · new 9 · num 1 · gone 2)
| # | src | label | size | m/d/h | tags | text | V |
|---|---|---|---|---|---|---|---|
|1–5|fin|매출 -90% · 이익률 -79.1%p · ROE -7.1%p · 부채비율 +30%p · 적자 전환|—|~1/-1|—|—|G ×5|
|6|new|수주 · R&D|금액 미상|.78/+.91/.73|수주·계약,연구개발,설비·증설|PlasmaLine… R&D용 장비 납품, 양산 테스트 진행|**S** (25-12, 26-03), triple-tagged|
|7|new|신사업 · 웨이퍼|금액 미상|.61/+.92/.82|신사업,설비|웨이퍼 데모 테스트가 완료될 경우… 공급할 계획|**S** + hypothetical|
|8|new|리스크 · 손해배상청구소송|금액 미상|.39/-1/.45|리스크·소송|회사는 일부 공급자를 상대로… 소송을 제기|**S**; company is plaintiff, dir -1|
#9 "재무상태에 중요한 영향 미치지 않을 것" (B); #10 신사업·AI industry prose stale in all 3; #12 num 배당 +26% = dividend-year count 19→24 (N, garbage).

**파마리서치 214450** (10: fin 6 · new 3 · gone 1)
| # | src | label | size | m/d/h | text | V |
|---|---|---|---|---|---|---|
|1|fin|매출 +27%|—|.75/+.68/.1|—|G|
|2|fin|이익률 -2.5%p|—|.56/-.51/.35|37.2%|G|
|3|fin|영업이익 +19%|—|.42/+.38/.15|—|G|
|4|fin|PBR 5.2배 (-53%)|—|.39/+.35/.05|—|G (valuation, not a report fact)|
|5|new|주주환원 · 25%|금액 미상|.32/+.5/.4|2025 사업연도부터 현금배당총액을 순이익 대비 25% 이상|**S** (25-12, 26-03)|
|6|fin|유보금 +23%|—|.38/+.35/.85|—|G|
|7|new|주주환원 · 배당|금액 미상|.25/+.5/.4|향후에도 주주가치 제고… 배당 정책을 중심으로 운영할 예정|**B** + S|
|8|new|실적 · 영업이익|금액 미상|.45/+.08/.15|전사 성과급 기준… 실근무일 일할반영하여 지급|**B** (임원·직원 section, tagged 실적)|
Zero story-worthy sentences; card ① would show only the number line.

**디어유 376300** (23: fin 9 · new 10 · gone 4)
| # | src | label | size | m/d/h | tags | text | V |
|---|---|---|---|---|---|---|---|
|1|fin|ROE +5.5%p|—|1/+1/.75|—|ROE 2.1%|G|
|2|new|M&A · JAPAN|금액 미상|.8/+.72/.55|지배구조·M&A|지분 10,108,159주(42.58%)… 2026-07-29 SM이 계열회사 EVERYSING JAPAN·SMEJ…|G (new, specific; label useless)|
|3|fin|이익률 +3.4%p|—|.75/+.68/.35|—|40.3%|G|
|4|new|신사업 · AI|금액 미상|.51/+.92/.85|신사업|2025년 2월… 'AI 펫 버블' 런칭|**S** (all 3)|
|5|fin|레버리지 1.7배|—|.66/+.6/.3|—|—|G|
|6|new|수주 · IP|금액 미상|.48/+.96/.68|수주,신사업|커머스 채널 구축, 버블 연계, IP 상품 출시 추진… 계약 체결|**B** + M (수주)|
|7|new|실적 · E&M|금액 미상|.58/+.68/.15|실적·수익성|글로벌 E&M 산업 매출 CAGR 3.7%… 2029년 3.5조 달러|**S** industry stat|
|8|fin|영업이익 +26%|—|.58/+.53/.15|—|—|G|
#10/#11 "국내 콘텐츠산업 매출 157조/161조" tagged company 실적 (M); #12 "2025-07 구독권 가격 11~12% 인상" is the best fact but has no category label; #15 (IFRS 18 "손익계산서… 5가지 범주") lands in **크기로 본 위험** — same defect class as the user's 2022 example.

**펄어비스 263750** (17: fin 8 · new 9)
| # | src | label | size | m/d/h | text | V |
|---|---|---|---|---|---|---|
|1–5|fin|매출 +142% · 이익률 +49.9%p · ROE +12.4%p · 흑자 전환 · 부채비율 -18%p|—|~1/+1|—|G ×5 (매출 +142% is vs. restated continuing ops after CCP 매각 — see #11)|
|6|new|신사업 · Steam|실적 문장|.51/+.92/.85|2026-03-20 출시 직후 Steam 매출 1위, 동접 24만, 트위치 50만|G|
|7|fin|레버리지 4.7배|—|.66/+.6/.3|"고정비가 깔린 뒤…" — from a loss base|G (text misleading)|
|8|new|실적 · 2조|실적 문장|.54/+.68/.15|PC방 매출액 2조 2,556억 +12.8%|**M** industry stat as 실적, S (26-03)|
#11 "종속기업 지분매각으로 매출액은 중단영업손익으로 분류" dir -0.5 (M) — this is the caveat that should sit next to #1.

**KB금융 105560** (15: fin 3 · new 10 · gone 2; scale has cap only)
| # | src | label | size | m/d/h | tags | text | V |
|---|---|---|---|---|---|---|---|
|1|fin|부채비율 +102%p|—|1/-1/.6|—|부채비율 1283%|**M** (bank)|
|2|new|수주 · Exit|금액 미상|.62/+.66/.68|수주,신사업|정비사업부문… 신규사업 수주하고 기 수주사업장 Exit Plan 추진|**B** + M|
|3|new|주주환원 · 100%|중요|.46/+1/.4|—|2026-04-24 자기주식 직접 취득(예정 6,000억) 2026-07-16 100% 완료|G|
|4|new|리스크 · KB|금액 미상|.42/-1/.45|리스크|국민은행·KB라이프·KB증권 검사결과 통보… 제재 추가 통보 예정|G|
|5|fin|영업이익 +27%|—|.6/+.54/.15|—|—|G|
|6|new|리스크 · 소송사건|금액 미상|.38/-1/.45|리스크|피고 소송 1건, 관리활동 관련 단순 손해배상|N|
|7|new|리스크 · 패소하더라|금액 미상|.42/-.8/.45|리스크|과징금 납부 완료… 패소하더라도 재무 영향 크지 않음|**S** (26-03) + B|
|8|new|리스크 · 50억원|금액 미상|.5/-.6/.45|리스크|시공사로 선정된 원고… 경관상세계획 심의…|N (50억 vs cap 59조; amount in label but size=금액 미상 → treated as nonSmall)|
#10 M&A·KB "2020.05 인도네시아 법인 85% 취득 - 2021.05 법인장 취임" (S, 6-year-old history list); #9 환율 commentary tagged 실적 (M).

**코나아이 052400** (19: new 9 · fin 6 · num 2 · gone 2)
| # | src | label | size | m/d/h | tags | text | V |
|---|---|---|---|---|---|---|---|
|1|new|수주 · OPEN|금액 미상|.62/+.96/.68|수주,신사업|코나플레이트는 리테일·커머스·핀테크 기업이 자체 선불카드 발행 지원|**B** + S (25-12, 26-03) + M|
|2|new|수주 · 100%|금액 미상|.6/+1/.5|수주|2025년 기존 운영 지역 100% 재수주, 세종·충주·진천·상주 신규|**S** (25-12, 26-03)|
|3|fin|매출 +26%|—|.71/+.65/.1|—|—|G|
|4|num|소송가액 -33%|금액 미상|.56/+.55/.45|리스크|피고 소송 4건, 소송가액 15,055,622천원|**M** diff is 건수 6→4, label says 소송가액|
|5|new|리스크|금액 미상|.38/-1/.45|리스크|이외 소송 사건에 대하여 전망을 예측할 수 없음|**B**|
|6|new|리스크 · 손해배상|금액 미상|.5/-.6/.45|리스크|항소심 1건(소송가액 약 72,761천원)… 항소 기각(회사 승소)|**M** company won, 7천만원|
|7|fin|영업이익 +24%|—|.54/+.49/.15|—|—|G|
|8|fin|유보금 +32%|—|.52/+.48/.85|—|—|G|
#16 num "수주 -12%" = 구주권 미제출 주식 7,926→6,965주 (N, garbage).

**영풍 000670** (17: fin 6 · new 11)
| # | src | label | size | m/d/h | tags | text | V |
|---|---|---|---|---|---|---|---|
|1|fin|매출 +42%|—|1/+1/.1|—|—|G|
|2|fin|이익률 +15.9%p|—|1/+1/.35|—|영업이익률 0.2%|G|
|3|fin|ROE +9.2%p|—|1/+1/.75|—|ROE 8.7% — 순이익 3,862억 vs 영업이익 15억; '영업외 이익' rule did not fire (op pct 101% > 30 guard)|G (missing caveat)|
|4|fin|흑자 전환|—|.99/+.9/.15|—|영업이익 15억 (0.2%)|G (mag overstated)|
|5|new|리스크 · 205억원|중요|.72/-1/.45|리스크|잡손실 중 증선위 감리결과 과징금 205억원|G|
|6|new|수주 · 정화명령|금액 미상|.52/+1/.5|수주·계약|정화명령을 받지 않은 건축물 하부토양… 정화를 실시할 예정|**M** (soil remediation → 수주 +1.0) + S|
|7|new|증설 · NVIDIA|금액 미상|.51/+.92/.8|설비·증설|NVIDIA Vera SOCAMM2… 2026년부터 양산 본격화|**S** (26-03), industry outlook as 증설|
|8|new|증설 · LPCAMM|금액 미상|.51/+.92/.8|설비·증설|LPCAMM 2024년부터 Sample… CXL 2026 양산 예상|**S**|
The one 감리 case is split into six signals (#5, #9, #10, #13, #14, #15); #16 "50%+1주 옵션대상주식" is a real governance fact but labelled 특수관계 거래 · 50%.

**User's cited case confirmed** — 하이록코리아 2022-09 분기보고서 (rcept 20221114000327, base 2021-09): #5 `R&D · 프로젝트` "현재 국내/외 대기업 등에서 좋은 평가를 받고 있고… 수많은 프로젝트에 참여" (B), #6 `주주환원 · 배당` "이익배당은 주주총회의 결의로 정한다" (B, 정관), #7 `M&A · 의무발생사건` "개정사항은 사업결합 시… 기준서 제1037호" (B, K-IFRS 1103 amendment) — and #7 is the **only** negative non-small signal, so it is the card-③ "biggest risk" and the 뒤집어 보기 lens evidence.

### Counts (80 judged = 10 × top 8)

| verdict | fin (45) | text: new/num/gone (35) | total |
|---|---|---|---|
| GOOD | 39 | **6** | 45 |
| BOILERPLATE | 0 | 10 | 10 |
| STALE | 0 | 13 | 13 |
| MISCLASSIFIED | 3 | 4 | 7 |
| NOISE | 3 | 2 | 5 |

Only **6 of 35 text signals (17%)** in the top 8 are new, specific company facts (삼성전기 변동금리 차입 +44%, 디어유 SM 지분 이전, 펄어비스 Steam 1위, KB 자사주 6,000억 완료, KB 검사결과 제재, 영풍 과징금 205억). Of 35 text signals, 29 are `size=금액 미상`, so card ③ "크기로 본 위험" has nothing to rank by.

### Top 6 recurring failure patterns

1. **"New" is measured only against the YoY base** — `invest_view` calls `_inv_collect(c, base, rep, b, year)` without `known`, so anything first written in 2025-09/12 or 2026-03 reads as new (13/35). E.g. 디어유 "2025년 2월 'AI 펫 버블' 런칭" (present in all three intervening reports), KB "2020.05 인도네시아 법인 85% 지분 취득".
2. **Table captions, footnotes and intros pass as facts while the table is dropped.** 삼성전기 #3 "단일판매ㆍ공급계약체결 공시를 진행하였으며 계약 진행 현황은 아래와 같음" (dir +1.0, the actual counterparty/amount never surfaces); 하이록 "주요고객은 다음과 같음", "주1) 결산배당횟수는 1991년부터…"; 아바코 "주1) 연속 배당횟수 제24기~제26기".
3. **Self-praise and industry prose survive `INV_GENERIC`** because `_inv_info` accepts any acronym/code as "붙잡을 것": 삼성전기 "FCBGA… 수주를 확대하고 Top Tier 고객과의 신뢰 관계", 코나아이 "코나플레이트는… 지원하고 있으며", 디어유 "글로벌 E&M 산업 CAGR 3.7%", 펄어비스 "PC방 매출액 2조 2,556억" (tagged company 실적).
4. **Keyword tagging flips meaning/direction.** 영풍 "정화명령… 정화를 실시할 예정" → 수주 +1.0; HD "Shadow Fleet 시장 퇴출 가속" → 리스크 -1.0 (it is replacement demand); 삼성전기 "10% 이상 거래처 없음" → -0.6; 코나아이 "항소 기각(회사 승소)" → 리스크 -0.6; 아바코 company-as-plaintiff suit → -1.0; KB 환율 commentary → 실적.
5. **Size and grouping fail.** Amount parsing hits the wrong number (하이록 customer share 9,588백만원 → "중요"; KB "50억원" in label but size unknown → shown as a non-small risk; HD "소송 36건 734억" diff computed on 건수). One event splinters into many signals (영풍 감리 ×6, 코나 소송 ×4) because grouping keys on the label's last token.
6. **fin YoY ignores scope changes and sign flips.** HD현대중공업 유보금 +84% / 부채비율 -41%p (HD현대미포 합병), 펄어비스 매출 +142% (CCP 매각 → 중단영업 재분류, the caveat sits at #11 with dir -0.5), KB 부채비율 1283% as the #1 risk of a bank, 영풍 ROE +9.2%p driven by 영업외 with no flag, "레버리지 4.7배" text ("고정비가 깔린 뒤…") emitted from a loss base, "흑자 전환" mag .99 at 0.2% margin.

### `fin` and `num` signals

- **fin**: numerically correct and the only consistently specific content, but they crowd the top 8 (45/80) and duplicate card ①'s first bullet. Tiny deltas still get rows (하이록 ROE +0.5%p, 영업이익 +3%, 유보금 +7%, all mag .25). PBR ±% rows are price moves (삼성전기 +720%), not report facts. The `expect` block (consensus progress, 선행 PER) was present for 6/10 and is the most company-specific thing in the whole payload, but only card ② uses it.
- **num**: 5 fired across 10 companies; **1 useful** (삼성전기 변동금리 차입금 6,088억→8,792억). The other four mislabel: the label takes the first `INV_NUM` keyword in the sentence while the diff is the first ≥10% number change — HD "소송가액 +16%" (actually 건수 31→36), 코나 "소송가액 -33%" (건수 6→4), 아바코 "배당 +26%" (연속 배당횟수 19→24), 코나 "수주 -12%" (구주권 미제출 주식 7,926→6,965주).

### 생각을 바꿀 조건 (card ④) — specificity

The API exposes no dedicated field; `lead_sigs` is just the pre-refine copy of `signals` (same order, used by `invArgs` for the checklist). Card ④ is built in the UI from three generators:

1. **"더 믿게 될 때"** = `INV_MON[label-head]` — a fixed string per category ("수주가 매출로 넘어오는 속도 — 다음 두 분기 매출 증가율", "신사업 매출이 따로 공시되기 시작하는지"…), identical across companies; only the `#id` anchor differs, and the anchor was wrong or stale in 8/10 companies (영풍 정화명령→수주, HD 폐쇄신고→신사업, 코나 코나플레이트→수주, KB 2020 인도네시아→M&A, 하이록 "주요고객은 다음과 같음"→고객, 아바코 stale PlasmaLine→수주).
2. **ttm.a line** — "매출 가속이 다음 분기에도 이어진다 (B +7.2%p)" or "매출 감속이 멈추고 가속으로 돈다": company-agnostic template with one number.
3. **"접게 될 때 — 매출이 늘어도 영업이익률이 뒷걸음친다"** fired in **10/10** companies, because `sigs.some(s=>s.key==='레버리지'||s.key==='영업이익률')` is true whenever an 영업이익률 delta exists — even for 아바코 (already -79%p) and 파마리서치 (margin already falling).
4. **"접게 될 때"** from 리스크/gov signals: KB 4 lines (incl. "단순 손해배상 1건", "패소하더라도 영향 크지 않음"), 코나 3 (two are the company *winning*), 영풍 7 (six on one 감리 case), 아바코 2 (company is plaintiff; "중요한 영향 없을 것"); the UI template appends "충당부채·판결·제재 범위가 커진다" regardless of content. 삼성전기/파마리서치/디어유/펄어비스/하이록 got none.

Net: of ~38 rendered card-④ lines across the 10 companies, roughly 8 are tied to a company-specific, current fact (영풍 과징금 205억 · 50%+1 옵션, HD 군산조선소 자산양수도, KB 검사결과 제재 · 자사주 6,000억, 디어유 SM 지분, 펄어비스 CCP 매각, 삼성전기 2027-01 시작 공급계약); the rest are category templates anchored to stale, boilerplate or mis-tagged sentences. The 관점 체크리스트 "이야기" lens inherits the same anchors (하이록 → stale 배당성향 20%, 코나 → 코나플레이트 description, 영풍 → 정화명령 as 수주).