# KRX v5 작업 종료 기록 — 003

- 기록일: 2026-11-18 (KST)
- 저장소: cks3210-spec/KRX-Public-Test
- 브랜치: main
- 저장 경로: docs/v5_progress/003_architecture_execution_audit_20261118.md
- 기준 문서: KRX_V5_MASTER.md (수정 금지)
- 이전 종료 기록: docs/v5_progress/002_work_checkpoint_20261118.md
- 상태: 구조 조사 진행 중 / 운영 코드 변경 전

## 1. 이번 작업 목표

기존 KRX v5 프로그램을 전수 조사하고, 최종 목표에 필요한 기능을 유지·통합·제거 후보로 분류한다.
새로운 Stage 개발보다 실제 운영 경로의 중복 제거, 공식 자료 검증, 안정적인 자동화를 우선한다.

## 2. 중요한 사용자 지시 및 합의

[사용자]
"득이가 판단해서 필요한파일 통합할파일 제거할파일 판단하면서 작업이어가자 우리가 최종목표로하는 프로그램 개발에 가장 최적회된 작업으로 진행하자"

[결정]
최종 프로그램 완성을 기준으로 파일을 판단한다.
기존 검증 자료를 보존하면서 중복 기능과 실행을 정리한다.
파일 삭제는 실제 호출·의존 관계와 대체 기능을 검증한 뒤 결정한다.

[사용자]
"계속 작업이어가자"
"시작"

[결정]
구조 조사와 실제 GitHub 워크플로 검증을 계속했다.
단순 파일명 추정이 아니라 GitHub에 존재하는 워크플로와 Python 코드를 직접 확인했다.

[사용자]
"여기까지 저장"

[결정]
현재까지 완료한 조사, 확인된 위험, 미완료 항목과 다음 작업 지점을 003 기록으로 보존한다.

## 3. 실제 확인한 파일과 실행 관계

### 3-1. 공식 데이터와 평가

- .github/workflows/v5-official-market-date-collector.yml
- .github/workflows/krx-r14-official-bridge.yml
- scripts/krx_official_r14_bridge.py
- scripts/krx_v5_r14_grade_engine.py
- data/v5_investment_r14/status.json
- data/v5_investment_r14_fundamental/status.json
- data/v5_investment_r14_research_k/status.json

R14에는 연구용 잠정 A/B 평가 기능이 존재한다.
공식 PER/PBR 검증 및 최종 매수 신호는 아직 완성되지 않았다.
자체 계산 PER/PBR을 공식 지표로 표시해서는 안 된다.

### 3-2. Stage 25~28

- v5_reports/stage25/status.json
- v5_reports/stage26/status.json
- v5_reports/stage27/status.json
- v5_reports/stage28/status.json
- v5_reports/stage27/signal_ledger.csv
- v5_reports/stage27/performance_5_10_20.csv

Stage25: 연구용 15종목 평가, B_RESEARCH 2종목.
Stage26: 연구 후보 2종목, 검증된 매수 신호 0건.
Stage27: 신호 기록 24건, 기간 도래 관찰 16건.
Stage28: 통합 결과가 있으나 최종 투자 판단 승인 상태는 아님.

Stage27의 MATURED 표시와 수익률 계산 완료는 구분해야 한다.
Stage25~28의 정확한 실행 스크립트·워크플로 경로는 아직 확정하지 못했다.

### 3-3. 주요 운영 워크플로

A. .github/workflows/v5-integrated-refresh-audit.yml
- 평일 20:20 KST 예약.
- Stage50~55를 순서대로 호출하고 결과를 검증.
- 실행 결과를 아티팩트로 업로드.
- 자체적으로 완성된 일일 재무 평가 엔진은 아님.

B. .github/workflows/v5-daily-integrated-operations.yml
- 평일 20:30 KST 예약.
- v5-integrated-refresh-audit.yml을 다시 workflow_dispatch로 호출.
- scripts/v5_daily_integrated.py 실행.
- data/v5_integrated/에 증거·성과 기록을 커밋하도록 구현.

확인된 위험:
A와 B가 각각 예약되어 있으므로 같은 날 Stage50~55가 중복 실행될 가능성이 있다.
실제 중복 실행 발생 여부는 Actions 실행 이력 검증 전이므로 미확정이다.

C. .github/workflows/v5-stage56-rolling-cohort-performance.yml
- 평일 18:55 KST 예약.
- Stage55 결과를 읽어 data/v5_tracking/에 추적 기록을 저장.
- git push 실패를 continue-on-error로 허용하므로 Actions 성공과 영구 저장 성공을 구분해야 한다.

D. .github/workflows/v5-stage57-daily-experimental-cohorts.yml
- 평일 19:10 KST 예약.
- Stage55 기준 자료와 기존 추적 자료를 사용.
- data/v5_tracking/에 기록하고 GitHub로 push하도록 구현.

확인된 위험:
Stage56과 Stage57이 동일한 data/v5_tracking/ 경로를 갱신한다.
실제 파일 충돌 발생 여부는 실행 이력과 커밋을 확인해야 한다.

E. .github/workflows/v5-daily-discovery.yml
- 평일 19:30 KST 예약.
- Stage12~16 재무 수집과 별도 발굴·평가 스크립트 실행.
- 기존 Stage50~55 및 R14와 기능 중복 여부를 추가 검토해야 한다.

## 4. 실제 확인한 성과 데이터

- data/v5_tracking/episodes.csv
- data/v5_tracking/performance.csv
- data/v5_tracking/daily_prices.csv
- data/v5_forward_validation/status.json
- data/v5_forward_validation/market_closes.csv
- data/v5_investment_r14_research_i/status.json

기존 성과 기록은 보존한다.
forward_validation은 검증된 입력 자료 부족으로 WAITING_FOR_VERIFIED_FEATURES 상태다.
미래 수익률을 과거 수익률로 대신하거나, 잠정 후보를 실제 매수 신호로 표시하지 않는다.

## 5. 유지·통합·제거 판단

[유지]
- 공식 KRX 원본 및 검증된 시장 자료
- OpenDART 재무 캐시
- 검증된 재무·성장 계산
- 기존 성과 기록과 일별 종가 기록
- v4와 골든크로스 독립 운영
- KRX_V5_MASTER.md 및 기존 종료 기록

[통합 후보]
- Stage25/26과 R14의 평가·판단 기능
- Stage27과 Stage56/57, R14 성과 추적 기능
- Stage50~55 중복 실행 예약
- 별도 일일 발굴·평가 경로

[제거 후보]
- 실행 경로에서 미사용이며 검증된 대체 기능이 있는 코드
- 중복 자동 실행 예약
단, 삭제·비활성화 대상 파일은 아직 확정하지 않았다.

## 6. 추가 확인한 위험

1. 일부 공식 KRX 수집 경로는 영문 포함 6자리 코드를 허용하지만, 일부 R14 검증 경로는 숫자 6자리만 허용한다. 누락 가능성 검증 필요.
2. GitHub Actions 실행 성공이 데이터 검증 성공이나 git push 성공을 보장하지 않는다.
3. 연구 등급과 최종 투자 등급을 혼동하면 안 된다.
4. 과거 기록과 최신 시장 자료는 날짜·출처를 분리해야 한다.
5. 현재 여러 워크플로가 별도로 실행되므로 단일 운영 흐름 확정 전에는 삭제 금지.

## 7. 최종 목표 구조

공식 KRX 데이터 수집·복구
→ OpenDART 재무·성장성 검증
→ 통합 A/B 평가
→ 적정 매수가 및 투자 판단
→ 5·10·20거래일 성과 검증
→ 자동 보고 및 영구 기록

시가총액 1,000억원 이상, 우선주 제외, 최종 A/B만 표시한다.
공식 자료와 계산값을 구분한다.
검증되지 않은 매수 신호는 발행하지 않는다.
기존 v4·골든크로스는 독립 유지한다.
스마트폰만으로 운영 가능해야 한다.

## 8. 이번 작업에서 실제 변경한 사항

- GitHub 파일 읽기 및 커밋 비교 수행.
- 주요 워크플로·상태 파일 확인.
- 기존 프로그램·워크플로·데이터 변경 없음.
- 삭제 확정 파일 0개.
- 실제 통합 코드 적용 0건.
- 신규 프로그램 실행 0건.

## 9. 정확한 작업 중단 지점

완료:
- 주요 Stage와 R14 상태 비교
- Stage50~55 통합 호출 구조 확인
- Stage56/57 동일 추적 폴더 갱신 확인
- 중복 자동 실행 가능성 확인
- 보존·통합 원칙 수립

미완료:
- GitHub 전체 파일 목록 전수 조사
- 실제 Actions 실행 이력 및 성공·실패 검증
- 활성·비활성 워크플로 구분
- Stage25~28 실제 실행 코드 확인
- 중복 실행 제거를 위한 안전한 최소 변경안
- 변경 전후 비교 테스트
- 파일 단위 최종 삭제·통합 확정

## 10. 다음 작업에서 가장 먼저 할 일

1. GitHub main의 마스터와 최신 종료 기록을 다시 읽는다.
2. v5-integrated-refresh-audit.yml과 v5-daily-integrated-operations.yml의 최근 Actions 실행 이력을 조사한다.
3. Stage56과 Stage57의 실행 시간·커밋·추적 파일 변경 충돌 여부를 확인한다.
4. 확인된 사실을 기준으로 주 운영 워크플로 하나와 보조 워크플로의 역할을 확정한다.
5. 중복 예약을 제거하는 최소 변경안을 준비한다.
6. 검증 전에는 기존 운영 코드를 삭제·비활성화하지 않는다.

## 11. 다음 채팅 시작 문구

"득이야, KRX v5 마스터와 마지막 003 작업 기록 확인하고 이어서 하자."

마스터와 001~003 기록을 읽고 위 10번의 첫 작업부터 재개한다.
