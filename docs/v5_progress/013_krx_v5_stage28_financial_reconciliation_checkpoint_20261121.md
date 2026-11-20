# KRX v5 개발 작업 기록 013 — 2026-11-21 07:55 KST

## 목적·재개 위치
- 저장소: <https://github.com/cks3210-spec/KRX-Public-Test> (`main`)
- 기준 마스터: `KRX_V5_MASTER.md` — Git blob SHA `52a5c615a4214de54157a4bc5252bf0c01fe27ea`
- 직전 작업 기록: `docs/v5_progress/012_krx_v5_automation_checkpoint_20261120.md` — Git blob SHA `ccd0dd97757e993433c5839c90b6cd78cd3a1336`
- **이 문서는 013 인계·작업 기록으로 현 대화에서 생성했다.** GitHub 저장소에 업로드 전까지 원격 저장 완료로 간주하지 않는다.

## 최신 실행 검증: Stage28 #20
- GitHub Actions 실행: <https://github.com/cks3210-spec/KRX-Public-Test/actions/runs/44831681707>
- 실행 ID: `44831681707`; 실행번호 `#20`, 이벤트 `workflow_dispatch`, 상태 `completed / success`.
- 시작: 2026-11-20 22:46:33 UTC (2026-11-21 07:46:33 KST).
- `v5_reports/stage28/status.json` 생성 시각: `2026-11-21T07:48:46.805801+09:00`.
- GitHub job 단계: 공식 운영자료·70거래일 검증, R14 전체시장 연구, 공식 PER/PBR 출처 감사, OpenDART 공시 접수번호·정정 이력, **계정별 재무 금액·접수번호 대조**, 기존 Stage25·26 연구, Stage27 읽기 전용, 요약 저장, Git 커밋, 아티팩트 업로드 **모두 `success`**.
- 워크플로: `.github/workflows/v5-stage28-final-orchestrator.yml`, Git blob SHA `0ab46c8436a11f4bf31ab6402c2987cf8f8002db`. 기존 파일 하나를 전체 교체하는 방식으로 관리.
- 이번 실행 성공은 실사용 가능한 투자 추천 검증 완료를 뜻하지 않음.

## 운영시장·R14 연구 범위
- `data/summary.json`: 공식 운영 시장일 `20261119`, 70거래일, 역사 데이터 193,549행, KOSPI 936 / KOSDAQ 1,835, 시장자료 합계 2,771.
- R14 숫자형 종목코드 연구 대상: 2,675개 (공식 시장 원본 2,771개와 96개 차이는 코드 규칙으로 구분; *보통주 검증 완료*를 뜻하지 않음).
- Stage28 당시 R14 연구 후보: **128개, A 24 / B 104** (`v5_reports/stage28/r14_full_market_grade_research.json`, 시장 기준일 `20261119`). 매수 승인 0.
- R14 재무 캐시: `data/v5_financial_m/status.json`, `cache_records=4720`, `annual_verified_rows=2564`, 재무 공시 point-in-time 미검증, 최종 매수신호 0.

## 이번에 실전 검증한 OpenDART 공시·재무 대조
- `v5_reports/stage28/r14_filing_receipt_audit.json`:
  - 공시 메타데이터 실제 조회 완료 회사 누적 **48 / 128**, 미조회 **80**.
  - 이번 #20에서 신규 조회 **24**개 회사.
  - 필수 공시기간의 평가일 이전 접수증거 51개 회사(완전한 금융 수치 검증과는 별개), 정정/복수 접수 기록 25개 회사, 평가일 이후 공시 포착은 현 보고 기준 0.
  - 원본 결과 캐시: `v5_reports/stage28/r14_filing_receipt_cache.json`, 128개 후보 상태 중 `COMPLETE_DART_API=48`, `PENDING_LIVE_DART_API=80`.
- **신규 실전 검증 단계** `v5_reports/stage28/r14_financial_value_reconciliation.json`:
  - 이번 실행 **6개 회사**, OpenDART 계정별 재무 API 요청 **18회**.
  - 기존 캐시와 현재 API 응답의 접수번호·계정 값이 일치한 회사 **6개** (`CURRENT_ACCOUNT_VALUES_MATCHED=6`).
  - 공시 실조회 48개 중 나머지 42개 회사는 이번 배치 상한 때문에 대기. 미조회 공시 80개 회사 역시 대기.
  - 비교 결과 캐시: `v5_reports/stage28/r14_financial_value_reconciliation_cache.json`, 회사별 6개 결과 저장.
  - 공식 PER/PBR 검증 **0**, 과거 평가 당시 재무값의 point-in-time 검증 **0**. 현재 API와 과거 시점 자료가 동일했다는 보장이 없으므로 6개를 최종 재무 검증 완료라고 부르지 말 것.
  - `investment_decisions_authorized=false`, `final_buy_signals=0`, 기존 `data/v5_financial_m`와 Stage27 파일 변경 없음.

## Stage27·기존 성과 기록 보존
- `v5_reports/stage27/status.json` Git blob SHA `66684d508ff988d6ee63efad873338d3f4ae094d`.
- 기존 V/G/VG **25건**, R14 동결 후보 **114건**, 전체 ledger **139건**, 성숙된 관측치 **32건**.
- Stage27 연구 후보 114건은 **11월 20일 당시 최초 동결된 집단**이며 현재 Stage28 A/B 연구 128개와 다르다. 새 14개를 과거에 추천한 것으로 소급 기록하지 않는다.
- Stage27 이번 최신 상태: 11월 21일 토요일 KRX 휴장으로 `SKIPPED_NON_KRX_SESSION`; 신규 후보 0, 첫 미래 기준가격 고정 0.
- 최초 기준가격 확정 대상: 11월 20일 연구 평가일의 다음 정규 KRX 거래일인 **11월 23일** 종가. 통상 다음 영업일인 11월 24일 오전 공식자료 확보 이후 실데이터 검증 가능.
- 기존 V/G/VG 원장 및 R14 A/B 연구 원장을 혼동하지 말 것. 장외일 투자 신호 생성 금지.

## 남은 과제 및 권장 순서
1. **중복 조사 없이 기존 Stage28 자동 공시 조회를 사용**하여 남은 공시 80개 회사의 접수번호를 24개/회 배치 방식으로 채운다. 자동 예약에 의한 실제 누적 건수 확인.
2. 이미 공시 실조회 완료한 **48개 중 재무 대조 완료 6개를 제외한 42개 회사**부터, 기존 6개/회 분할 대조를 진행한다. 새 공시 조회 대상이 늘면 그 회사도 이후 대조한다. 오류 이유는 `status_counts_this_run` 및 캐시의 회사별 상태로 확인.
3. 계정 수치가 일치해도 **공시 원본 문서·수정본 및 제출 당시 버전**을 독립적으로 검증하기 전에는 `point_in_time_financials_verified=false` 유지.
4. 공식 PER/PBR 원천 데이터와 기준시각·공시 버전의 신뢰 가능한 경로를 확보하여 독립 검증. 미확인 추정값을 공식 검증값으로 승격 금지.
5. Stage27은 11월 23일 공식 종가 확보 후 114개 기존 동결 후보의 최초 관측 가격과 5·10·20 거래일 미래 성과를 실데이터로 검증. 기존 원장 유지.
6. Stage28/Stage27/공식자료 수집이 자동으로 이어지는 완결성 확인 후 최종 투자 판단 기능 개발. 현재 매수 신호 0, 연구용만.

## 스마트폰 전용 작업 방식 (유지)
- GitHub 저장소 `cks3210-spec/KRX-Public-Test`, 브랜치 `main`.
- 기존 파일 분석 → 수정된 **같은 파일명 전체 교체본 하나** 제공 → 다운로드 → 기존 GitHub `.github/workflows/`에 같은 이름 업로드/커밋 → 업로드 확인 → 실제 Actions 실행 결과 검증.
- 기존 파일 삭제, 코드 전체 수작업 복사 붙여넣기, 다수 중복 워크플로 생성은 원칙적으로 피한다.
- 매번 파일명·다운로드·GitHub 편집 또는 업로드·워크플로 실행 바로가기를 명확히 제시.
- 자동화 개발 우선, 불필요한 재검증·중복 수집·사소한 문제 추적은 최소화. 거래일·수집시각·연구 평가일은 분리.
- 주식 최종 A/B 표에서 C 이하 제외; 시가총액 1,000억원 이상 원칙, 우선주 제외 원칙. 5·10·20거래일 사후 성과 측정.

## 다음 대화에서 재개할 문장
> 득이야, KRX v5 마스터와 작업 기록 013을 확인하고 이어서 개발하자. Stage28 #20 성공, 공시 실조회 48/128, 현재 OpenDART-캐시 계정 금액 일치 6/128, Stage27 139건 보존을 기준으로, 재무 수치 대조 자동화의 남은 회사를 누적 검증하고 공식 PER/PBR·과거 공시 시점 검증을 고도화하자. 기존 기능은 반복 개발하지 말고 스마트폰용 기존 파일 전체 교체 방식으로 진행하자.
