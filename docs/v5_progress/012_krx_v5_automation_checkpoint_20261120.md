# KRX v5 개발 작업 기록 012 — 2026-11-20 KST

## 재개 기준
- 저장소: https://github.com/cks3210-spec/KRX-Public-Test (main)
- 마스터: `KRX_V5_MASTER.md` / SHA `52a5c615a4214de54157a4bc5252bf0c01fe27ea`
- 이전 기록: `docs/v5_progress/011_stage27_forward_validation_verified_20261120.md` / SHA `b88345ae2acd8571ed1ce976e4a8f6427aa475de`
- 이번 012 문서는 대화 종료 시점에 로컬 생성함. GitHub 업로드/커밋은 별도 확인이 필요하며, 업로드 전에는 GitHub에 저장됐다고 주장하지 않는다.

## 이번에 완료·확인한 기능과 파일 버전
1. 공식 KRX 수집기 `.github/workflows/v5-official-market-date-collector.yml` / SHA `451affc4292a0dd244f84a374d5bc540b15dd3f8`. 08:30/10:30/17:40 KST 재시도 예약, 수동·자동 트리거 기록, 네트워크 오류 재시도, 원본 시장일자와 실수집일 구분. 실제 성공 수집 run #13 `44643777151`: `workflow_dispatch`, `2026-11-19` 공식 시장자료 2,771행(KOSPI 936, KOSDAQ 1835), 2026-11-20 09:11 KST 검증; 시세 공식 API 응답 해시 보존. 재시도 자체는 해당 성공 실행에서 발생하지 않아 실서버 재시도 복구 검증은 별도.
2. 공식자료→운영 통합기 `.github/workflows/v5-krx-official-promotion-gate.yml` / 최신 SHA `7a1a39f536589ec5b5841fd816bb275412dc7f25`. 기존 워크플로 재사용. `workflow_run`으로 공식 수집 완료 시 자동 실행 설정, 수동 실행도 가능, 날짜 중복 시 건너뛰기, 검증된 자료만 `data/latest.csv`, `data/daily_70d.csv.gz`, `data/summary.json`으로 안전 통합. v4·골든크로스 파일을 통합기가 직접 수정하지 않음. **수동 통합 실증 성공** run #6 `44656003915` (2026-11-20): `20261118` → `20261119`, 공식 2,771행, 70거래일 193,541 → 193,549행, 커밋 성공. **새 workflow_run 자동 트리거의 실제 성공은 아직 별도 검증되지 않음.**
3. R14 수집·연구 `.github/workflows/krx-v5-r14-dart-auto-continue.yml` / SHA `022e396f7670816b6f479ddf660e6c26073c5144`. run #11 `44662978522` 성공. `data/v5_financial_m/status.json` SHA `d2acd7ec6466bbd2b3056acd4521ceed2209c1de`: cache 4,320, annual verified rows 2,495, TTM 666, disclosure evidence 750, financial source snapshot market_date `20261116`, point-in-time financials UNVERIFIED, official PER/PBR 아직 검증 전, final buy signals 0.
4. Stage27 `.github/workflows/v5-stage27-performance.yml` / 최신 SHA `d7574d91572fcc07c15e6aaf9a9b26f494c3ccdb`. R14 성공 시 `workflow_run`으로 자동 실행; 평일 23:40 KST 보완 예약, KRX 거래일/장마감/자료 날짜·재무 갱신 안전 조건, 기존 V/G/VG 과거 기록 유지, R14 연구 후보는 평가일(소급 아님)로 기록하고 원본 시장일을 별도 기록. **R14→Stage27 실제 자동 트리거 검증** run #2 `44669061522` 성공, event=`workflow_run`, status `v5_reports/stage27/status.json` SHA `38efcab863422c9a6b31972c57ea1a60535be7e4`: market_date `20261119`, evaluation_date_kst `20261120`, legacy events 25 보존, matured 32, R14 새 cohort 0, 상태 `WAIT_FOR_EVALUATION_DAY_CLOSE`, 매수 신호 0. **23:40 예약 보완과 신규 연구 cohort 생성의 실제 검증은 아직 안 됨.**
5. **저장 직전 새로 확인된 중요 변경**: 이후 별도 자동 작업 `V5 Stage60 Morning Collection R3`가 `2026-11-20T04:10:40Z` (KST 13:10) 성공했으며, 현재 main에 `data/daily_indicators.csv` SHA `d64a1662ac13903217c014d9ed31e7e82571c03c`, `data/v4_indicators.csv` SHA `b2a14b10a7b24e56eb2f009d5b1c4696bb8867e2`가 모두 `20261119` 기준으로 갱신되어 있음. `data/summary.json` SHA `7f808749e7783826c368f635e126d58083490d9e`: latest_trading_date `20261119`, sessions_stored 70, total_rows_stored 193549, marketcap_1000uk_screened 1272, golden_cross_eligible 1267, golden_cross_3d 136, uptrend_maintained 385. 따라서 기존 11/18 기술지표가 계속 낡았다는 이전 진술을 그대로 반복하지 말고 **현 시점 최신 자료와 실행 이력 기준으로 판단**할 것. `data/latest.csv` 현재 SHA `7d02861f05daf5f8cf733bba599717a8665dbe0c`, `20261119` 기준. 새 지표의 산식·실제 사용 적합성은 아직 별도 검증 대상.

## 시점과 거래 신호 안전 원칙
- `market_date` = KRX 실제 데이터의 BAS_DD, `collected_at_kst` = 수집 시각, `evaluation_date_kst` = 연구평가 시각, 재무 공시/취득 시각은 각기 구분.
- 한국 증시 휴장일에는 종목 후보 기록·브리핑 금지. KRX API 자료 공개 지연이 정상적일 수 있으므로 초록색 Actions와 자료 성공을 혼동하지 말 것.
- 임의로 지난 날짜에 신규 추천 신호를 생성/소급하지 말 것. 동일 날짜 후보 중복 등록 금지. V/G/VG와 R14_A/B 성과는 별도 유지.
- 추정 PER/PBR, 연구용 적정가/매수 구간을 공식 검증/실제 매수 권고로 혼동하지 말 것. final_buy_signals 0 유지.
- v4·골든크로스 코드 및 원본 캐시를 검증 없이 덮어쓰지 말 것.

## 다음 작업 (중복 작업 없이)
1. 가장 먼저 **현재 GitHub main 상태를 한번만** 확인해, 공식 collector → promotion의 자동 `workflow_run` 이벤트 실행 성공이 실제로 발생했는지 확인. 동일 시장일 중복 자동 실행은 SKIPPED로 안전 종료해야 함.
2. Stage60에서 이미 `20261119`로 재생성된 v4·daily_indicators 확인 결과를 재사용하고, 산식 적합성/지표 생성 일자를 짧게 검증. 이미 해결된 기술지표 날짜 문제를 다시 개발하지 말 것.
3. 기존 공식 수집→운영 통합→R14 grade→Stage27 체인의 날짜 갱신·동기화 상태를 진단하고 **중복 워크플로 없이 기존 파일만 교체**. R14 현재 21:30 KST, Stage27 `workflow_run` 및 23:40 KST. R14의 재무 캐시 `market_date=20261116`은 재무자료 취득 기준이므로 시장가격 당일 기준과 무조건 같게 만들지 말 것.
4. Stage27 신규 R14_A/B 연구 cohort는 당일 장마감 및 시점 안전조건 충족 시에만 동결, 그 후 5·10·20 거래일 성과 검증. 공식 PER/PBR 및 공시 point-in-time 증거가 확보되기 전 매수 신호 금지.
5. 전체시장 실데이터로 자동화 반복 실행 및 장애 복구 확인 후 완료 판정.

## 사용자 운영 원칙
- 스마트폰만 사용. 다운로드는 단일 파일 선호, 기존 파일명 전체 교체, GitHub 편집/업로드/Actions 바로가기 제공.
- 반복 확인/설명 최소화, 프로그램 실제 구현 우선. 일괄 수정·테스트 및 정확한 상태 기록.
- `1` = 다음 개발 작업 실제 진행, `완` = 사용자가 파일 업로드 완료, `실행완` = 워크플로 수동 실행, `여기까지 저장` = 복사 가능한 작업 기록과 다운로드 파일 생성.
- GitHub API를 통한 자동 코드 수정은 종전 403 FORBIDDEN으로 거절된 이력이 있어, 업로드가 필요한 경우 사용자 스마트폰 GitHub 교체 방식 사용.
