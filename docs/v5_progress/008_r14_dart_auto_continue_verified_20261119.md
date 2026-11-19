# KRX v5 개발 진행 기록 — 008

기록일: 2026-11-19 (KST)
저장소: cks3210-spec/KRX-Public-Test / main
기준 문서: KRX_V5_MASTER.md
이전 기록: docs/v5_progress/007_krx_r14_common_date_financial_join_verified_20261119.md

## 사용자와 합의한 스마트폰 운영 방식
- 사용자가 `1`이라고 입력하면 마스터, 최신 기록, GitHub main, 마지막 Actions 결과를 확인하고 개발을 이어간다.
- 득이는 **기존 파일명과 동일한 다운로드용 파일**을 준비하고, 사용자는 스마트폰에서 기존 GitHub 파일을 교체한다.
- 긴 코드 직접 붙여넣기, 줄별 수동 편집, 불필요한 신규 워크플로 및 반복 스크린샷을 피한다.
- 다운로드·업로드·커밋·Actions·로그 검증을 구분하며, 성공한 기록만 확정한다.
- 001~007 기록과 기존 캐시, v4, 골든크로스는 보존한다.

## R14 수집 파일 교체 검증
- 경로: scripts/krx_v5_r14_financial_pipeline_n.py
- GitHub main에서 교체 확인: blob SHA fc7a9ec75ed30f10ac2aa687643c86a646f745d4 (검증 시점)
- 날짜 역행 차단, 날짜 출처 및 공시일 검증 미완료 상태를 기록하는 코드 확인.
- 재무 snapshot 날짜를 공식 KRX 평가일로 무조건 덮어쓰지 않는다.

## 실제 Actions 실행 검증
- 워크플로: KRX v5 R14 OpenDART Auto Continue #5
- Run ID: 44430572451
- 시작: 2026-11-19 00:38:06 UTC
- 결론: success, 38분 47초, artifact 1개
- 실행 로그의 배치별 병합 확인: conflicts_seen=0
- GitHub main의 data/v5_financial_m/status.json 확인:
  - market_date: 20261116
  - base_rows: 2675
  - cache_records: 1920 (기존 1520 대비 +400)
  - annual_verified_rows: 1318 (기존 1119 대비 +199)
  - ttm_calculated: 278 (기존 194 대비 +84)
  - ttm_period: q3
  - financial_snapshot_date_source: EXISTING_FINANCIAL_STATUS
  - financial_disclosure_asof_verified: false
  - point_in_time_financials_authorized: false
  - final_buy_signals: 0
  - investment_decisions_authorized: false
- GitHub Actions 경고는 Node.js 20 지원 종료 관련 의존 Actions 경고로, 이번 수집은 정상 종료.

## 남은 핵심 문제
1. 재무 snapshot 날짜 20261116은 data/v5_investment_r14_research_k/status.json의 날짜에 의존하며, 공식 KRX 시장 평가일과 자동 연결되지 않음.
2. 공식 KRX 거래일 평가 날짜는 기존 R14 공식 브리지에서 별도로 취급해야 하며 재무 회계기간, 실제 공시일, 수집일을 강제로 통일하면 안 됨.
3. OpenDART 실제 공시일을 기준으로 과거 평가 시점에 공개되어 있던 정보만 사용하도록 point-in-time 검증이 필요.
4. 공식 PER/PBR과 자체 계산 지표 구분 및 최종 A/B·매수가·성과 검증은 아직 미완료.

## 다음 개발 순서
1. 공식 KRX 시장 기준일과 재무 캐시 기준일을 안전하게 연결하는 기존 코드 경로 확인 및 최소 수정.
2. 실제 공시일 검증 추가. 공시일 미확인 자료는 연구용으로만 유지.
3. 기존 워크플로 재사용, 실데이터 재실행 및 status/log/artifact 검증.
4. 공식 PER/PBR 검증, A/B 재평가, 적정 매수가 및 5·10·20거래일 검증 연결.

## 저장 상태
이 문서는 GitHub 업로드 전 다운로드용 기록이다. `docs/v5_progress/`에 업로드하고 main에서 확인하기 전에는 저장 완료로 표시하지 않는다.
