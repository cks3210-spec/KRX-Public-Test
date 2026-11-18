# KRX v5 작업 종료 기록 — 004

- 기록일: 2026-11-18 (KST)
- 저장소: cks3210-spec/KRX-Public-Test
- 브랜치: main
- 저장 경로: docs/v5_progress/004_workflow_stabilization_20261118.md
- 기준 문서: KRX_V5_MASTER.md
- 이전 기록: docs/v5_progress/003_architecture_execution_audit_20261118.md
- 현재 상태: Stage56 실행 성공 / Stage57 문법 수정 완료·재실행 대기

## 1. 이번 작업 목표

003 기록에서 발견한 Stage50~55 중복 예약과 Stage56·57의 성과 기록 충돌 가능성을 최소 수정으로 개선한다.
기존 데이터, 캐시, 마스터, v4, 골든크로스는 보존한다.

## 2. Stage50~55 중복 예약 제거

파일:
.github/workflows/v5-integrated-refresh-audit.yml

변경:
- 평일 20:20 KST 자동 예약 schedule 제거
- workflow_dispatch 수동 실행 유지
- Stage50~55 호출 로직 유지

검증:
- GitHub main에서 변경된 파일 직접 확인
- 예약 설정 없음
- 수동 실행 설정 유지
- Stage50과 Stage55 호출 코드 유지

목적:
20:30 KST의 v5-daily-integrated-operations.yml이 통합 감사 워크플로를 호출하는 구조를 유지하면서 독립 예약에 의한 중복 호출 가능성을 줄인다.

주의:
실제 향후 중복 실행 여부는 Actions 기록으로 추가 검증해야 한다.

## 3. Stage56·57 Git 저장 대상 분리

Stage56:
.github/workflows/v5-stage56-rolling-cohort-performance.yml

Git 커밋 대상:
- data/v5_tracking/episodes.csv
- data/v5_tracking/performance.csv
- data/v5_tracking/daily_prices.csv

Stage57:
.github/workflows/v5-stage57-daily-experimental-cohorts.yml

Git 커밋 대상:
- data/v5_tracking/candidate_changes.csv
- data/v5_tracking/daily_candidate_snapshots.csv

검증:
두 파일의 git add 명령이 변경된 사실을 GitHub main에서 직접 확인했다.

주의:
커밋 대상 분리는 실행 중 계산에 사용되는 공유 파일을 완전히 분리한다는 뜻은 아니다.

## 4. Stage56·57 동시 실행 방지

두 워크플로의 concurrency group을 다음으로 통일:
v5-stage56-tracking

cancel-in-progress: false 유지.

검증:
GitHub main에서 양쪽 워크플로 설정 확인.

한계:
GitHub Actions는 동일 그룹의 동시 실행을 제한하지만 대기 실행 순서를 보장하지 않는다.

## 5. Stage56 Git 저장 실패 감지 및 안정화

파일:
.github/workflows/v5-stage56-rolling-cohort-performance.yml

변경:
- Persist V5-only tracking files 단계의 continue-on-error: true 제거
- git pull --rebase origin main 추가
- git push origin HEAD:main 적용
- 실패 시 결과 아티팩트 업로드 if: always() 유지

검증:
GitHub main에서 실제 코드 변경 확인.

한계:
동시 변경에 의한 리베이스 충돌 가능성이 완전히 사라지는 것은 아니다.

## 6. Stage56 실제 실행 결과

사용자가 GitHub Actions 화면에서 수동 실행한 결과:
- 워크플로: KRX v5 Stage56 Rolling Cohort Performance
- 실행 번호: #9
- 브랜치: main
- 결과: 성공(초록색)
- 소요 시간: 24초

GitHub main에서 확인한 파일:
- data/v5_tracking/episodes.csv
- data/v5_tracking/performance.csv
- data/v5_tracking/daily_prices.csv

daily_prices.csv에 2026-11-17 종가 기록 존재 확인.

주의:
#9 실행 전후 파일 변경량과 모든 성과값의 정확성까지 검증한 것은 아니다.
초록색 Actions 성공과 최종 투자 신호 검증 완료를 혼동하지 않는다.

## 7. Stage57 실제 실행 실패와 원인

사용자가 Stage57을 수동 실행했을 때:
- 분석 및 후보 변화 계산 단계 성공
- Commit tracking state 단계 실패
- 결과 아티팩트 업로드 성공

오류:
error: cannot pull with rebase: You have unstaged changes.
error: Please commit or stash them.
Process completed with exit code 128.

원인:
연구용 2개 파일만 Git 커밋하도록 제한한 뒤 나머지 생성 파일이 미커밋 상태로 남아 git pull --rebase가 거부됨.

대응:
Stage57 커밋 단계에 git stash push --include-untracked를 추가하여 미커밋 생성 파일을 임시 보관하도록 수정.

## 8. Stage57 YAML 문법 오류 및 수정

stash 명령을 추가하는 과정에서 run: 문자열을 닫는 작은따옴표가 누락됨.

사용자가 제공한 GitHub Actions 화면:
- 워크플로 파일이 유효하지 않음
- YAML syntax error on line 115
- 실행 그래프 없음

조치:
Commit tracking state 단계 마지막 줄을 fi'로 마무리하여 누락된 작은따옴표 복구.

검증:
GitHub main의 파일을 다시 읽어 작은따옴표가 복구된 사실 확인.
파일 blob SHA: 7c4a6741fcdae435939a798c806bb24d58832f05

중요:
문법 수정 후 Stage57 재실행 성공 여부는 아직 확인하지 않았다.
최종 성공으로 기록하지 않는다.

## 9. 이번 작업에서 변경하지 않은 것

- KRX_V5_MASTER.md
- 기존 001~003 작업 기록
- 기존 KRX 원본 자료 및 OpenDART 캐시
- 기존 v4·골든크로스
- Stage50~55 내부 계산 로직
- 최종 투자 등급 및 매수 판단 엔진

기존 데이터 파일 삭제 없음.
이번 변경은 GitHub 워크플로 설정과 Git 저장 방식에 한정된다.

## 10. 다음 작업 시작 지점

최우선:
1. GitHub Actions에서 Stage57을 main 브랜치로 수동 실행한다.
2. 실행 성공 또는 실패 로그를 확인한다.
3. 성공 시 candidate_changes.csv 및 daily_candidate_snapshots.csv의 실제 GitHub 저장 여부를 확인한다.
4. episodes.csv, performance.csv, daily_prices.csv가 Stage57 실행으로 잘못 덮어써지지 않았는지 검증한다.
5. Stage56과 Stage57의 예약 실행이 실제로 안정적으로 동작하는지 확인한다.

이후:
6. 20:30 통합 운영 워크플로와 Stage50~55 실제 실행 결과 검증.
7. 공식 KRX 데이터 날짜·재무 검증·성과 기록의 연속성 확인.
8. R14와 Stage25~28 기능 통합 및 최종 A/B 투자 평가 엔진 개발.
9. 검증된 적정 매수가와 5·10·20거래일 성과 검증 완성.

## 11. 다음 채팅 재개 문구

"득이야, KRX v5 마스터와 마지막 004 작업 기록 확인하고 이어서 하자."

재개 시 GitHub main의 KRX_V5_MASTER.md와 004 기록, Stage57 워크플로를 먼저 읽고 Stage57 실제 재실행 검증부터 시작한다.

## 12. 이번 기록의 저장 상태

이 문서는 사용자가 GitHub에 추가해야 하는 004 종료 기록이다.
GitHub에 실제 업로드하고 재조회하기 전까지 저장 완료로 판단하지 않는다.
