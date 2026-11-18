# KRX v5 개발 진행 기록 — 007

기록일: 2026-11-19 (KST)
저장소: cks3210-spec/KRX-Public-Test / main
기준: KRX_V5_MASTER.md
이전: docs/v5_progress/006_official_krx_r14_bridge_verified_20261118.md

## 대화에서 확정한 운영 원칙
- 사용자가 '1'을 입력하면 마스터, 최신 진행 기록, GitHub main을 확인하고 마지막 작업부터 이어간다.
- 득이는 중요 기능 완료·오류 해결·방향 변경·다음 단계 전 저장 시점을 먼저 알린다. 실제 GitHub 등록 확인 전에는 저장 완료라고 하지 않는다.
- 스마트폰 전용: 수정 파일은 GitHub에 올릴 최종 파일명 그대로 다운로드 제공. 긴 코드 복사 대신 파일 다운로드→기존 파일 교체→커밋→Actions 실행→결과 확인. 변경 불필요한 워크플로는 재사용한다.
- 기존 코드·검증 캐시·001~006 기록은 보존하며 중복 Stage 개발 금지.
- 이 기록은 대화 원문 전체가 아니라 중요한 결정, 오류, 실제 검증 결과, 다음 작업을 요약한 것이다.

## KRX 공식 거래일·공개시각 통일
- 사용자 제공 KRX Open API 공식 FAQ: 전일 거래자료는 다음 영업일 08:00 KST 공개. 금요일 거래자료는 다음 영업일 월요일 08:00 공개.
- 공식 KRX 수집 시각은 영업일 08:30 KST, XKRX 거래일 달력으로 직전 실제 거래일 조회. 휴장일 신규 자료 건너뜀.
- 시장자료(종가·거래량·시가총액)와 R14 **평가 기준일**은 공식 KRX 거래일로 통일한다.
- OpenDART 재무제표의 회계기간, 실제 공시일, 수집일, 기존 재무 캐시 기준일은 별도 보존한다. 날짜 문자열을 임의로 바꾸지 않는다.
- 과거 시점 평가에서는 그날 실제 공개되어 있던 재무정보만 사용한다. 현재 R14 재무 인덱스에는 공시일 정보가 없으므로 시점 적합성 검증 미완료.
- 공식 PER/PBR과 계산 지표를 구분하고, 미검증 매수 신호는 차단. 5/10/20일 성과는 실제 KRX 거래일 기준.

## 날짜 불일치 오류 해결
- 최초 원클릭 실행 실패: FINANCIAL_MARKET_DATE_MISMATCH, KRX=20261117, R14 재무 캐시=20261116.
- 동일 날짜 강제 또는 단순 7일 제한만으로 공시 유효성을 판단하지 않는다.
- 수정 파일: scripts/krx_r14_official_financial_join.py. 공식 KRX 시장일을 evaluation_market_date로 사용, 기존 financial_market_date는 별도 보존. 미래 캐시는 차단하고 과거 캐시는 **연구용**으로만 연결.
- financial_disclosure_asof_verified=false, point_in_time_financials_authorized=false, official_per_pbr_verified=false, investment_decisions_authorized=false.
- 기존 .github/workflows/krx_r14_official_financial_oneclick.yml 재사용, 운영 데이터·캐시 수정 없음.
- GitHub 직접 쓰기 권한 403으로 사용자가 스마트폰에서 파일 교체 후 실행.

## GitHub 실데이터 검증 완료
- Workflow: KRX R14 Official Financial One-Click Audit #2
- Run ID: 44405087049
- Commit: 4fd83d0813d35b133191c8583a33086db66eff13
- audit Success, Artifact 1개, 로그 직접 확인.
- state=READ_ONLY_EVIDENCE_JOIN_COMPLETE
- market_date=evaluation_market_date=20261117
- financial_market_date=20261116, financial_snapshot_lag_days=1
- 공식 시장 2771종목, 재무 인덱스 2675행.
- MARKET_FINANCIAL_EVIDENCE_JOINED=193
- TTM_NOT_VERIFIED=924
- FINANCIAL_SOURCE_UNVERIFIED=1556
- FINANCIAL_NOT_FOUND=97
- EQUITY_NON_POSITIVE=1
- 합계 2771, production_modified=false.
- 공식 PER/PBR, 실제 공시 시점, 최종 투자 추천은 **미검증**. 193종목은 연구용 근거 결합 성공이지 최종 A/B 추천이 아님.

## 다음 작업
1. 마스터·007·GitHub 최신 main·run #2 확인.
2. 기존 R14 N/M OpenDART 수집·캐시 재사용해 출처 미검증 1556, TTM 미검증 924, 자료 미존재 97의 원인 및 복구 개선.
3. 실제 공시일과 회계기간을 평가일 기준으로 검증하는 point-in-time 연결.
4. Stage56 공식 PER/PBR, 최종 A/B 평가, 적정 매수가·분할매수 구간 연결.
5. 공식 KRX 수집→R14→평가→5/10/20거래일 성과→보고 자동화와 실데이터 검증.
6. 시총 1000억원 이상, 우선주 제외, 최종 A/B(B+)만 표시. Stage25/26 재개발 금지, Stage57 수동 유지, v4·골든크로스 독립 유지.

## 저장 상태
본 파일은 다운로드용 기록이다. GitHub `docs/v5_progress/`에 신규 업로드하고 main 등록 확인 후에만 '저장 완료'로 판단한다. 기존 기록은 삭제·덮어쓰기 금지.
