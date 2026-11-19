# KRX v5 작업 기록 010 — R14 #8 검증 및 개발 우선순위 확정

기록일: 2026-11-19 (KST)
저장소: cks3210-spec/KRX-Public-Test / main
기준 문서: KRX_V5_MASTER.md, docs/v5_progress/009_mobile_workflow_agreement_20261119.md

## 1. 적용 확인
- scripts/krx_v5_r14_financial_pipeline_n.py: GitHub main SHA 50bd69c051553f71abeeebd9b4da5667969e5f82
- .github/workflows/krx-v5-r14-dart-auto-continue.yml: GitHub main SHA 52d5d663ec3f823b966975e3be10cf52a8242c49
- 공시 목록 페이지 처리, 미검증 증거 재시도, 증거 병합 개선을 위한 수정 파일 2개가 GitHub에 반영됨.

## 2. R14 Actions #8 검증
- 사용자 제공 GitHub Actions 화면: 실행 #8, main, Success, 43분 43초, artifact 1개, annotation warning 1건.
- GitHub main data/v5_financial_m/status.json 재확인: generated_utc 2026-11-19T09:34:31.157372+00:00, market_date 20261116.
- 재무 캐시 3,120건(직전 2,720건 대비 +400), 연간 재무자료 확보 1,901종목(+190), TTM 계산 472건(+72).
- 공시 증거 300건(직전 150건 대비 +150): FILING_CANDIDATES_FOUND 219, PAGINATED_UNVERIFIED 78, FILING_NOT_FOUND 3.
- financial_disclosure_asof_verified=false, point_in_time_financials_authorized=false, investment_decisions_authorized=false, final_buy_signals=0.
- 주의: 초록색 Actions 성공만으로 공시 수치 일치나 투자 판단의 정확성이 증명되지는 않음. warning 1건의 상세 원인은 확인하지 못함.

## 3. 사용자 결정: 공시 미검증 상세 분석 보류
- PAGINATED_UNVERIFIED 78건의 개별 원인 분석은 현재 개발의 우선순위에서 제외.
- 78건은 공시 증거 300건의 26%로, 전체 종목 대비 비율로 단순 해석하지 않음.
- 기존 미검증 표기, 자동 재시도, 재무 캐시 및 공시 증거 보존 유지.
- 검증되지 않은 자료를 검증 완료로 표시하거나 이를 근거로 매수 신호를 허용하지 않음.
- 최종 A/B 후보 평가에 중대한 왜곡 또는 허위 매수 신호 위험이 확인될 경우에만 해당 원인을 우선 점검.

## 4. 다음 개발 작업
1. 기존 R14 및 Stage25~28 평가 기능의 실제 입출력을 확인하고 중복 구현을 피함.
2. A/B(B+) 등급 평가와 적정 매수가 산출 기능 완성.
3. 매매 판단과 5·10·20거래일 성과 추적 연결.
4. 공식 수집→재무→평가→성과→보고 자동화 및 전체 시장 실데이터 검증.
5. 공식 PER/PBR과 자체 계산 지표 구분, 미검증 공시·시점 정보는 투자 신호에서 차단.

## 5. 스마트폰 표준 작업 방식
- 각 변경 파일의 정확한 파일명과 폴더 경로, 복사 기능, 다운로드, 기존 파일 편집 링크, 새 파일 업로드 링크 제공.
- GitHub 실제 파일과 비교하여 변경 필요성이 확인된 경우에만 교체 요청.
- 작업 완료 후 main 반영 및 Actions 실제 데이터 검증.

## 6. 저장 상태
- 이 문서는 사용자가 다운로드하여 GitHub docs/v5_progress/ 폴더에 업로드할 기록본.
- **GitHub 업로드 및 반영 확인은 아직 완료되지 않음.**
