# KRX v5 작업 기록 016 — Stage53 공식 종목기본정보 실제 확보 (2026-11-23)

## 기준
- 저장소: `cks3210-spec/KRX-Public-Test`, 브랜치 `main`
- 마스터: `KRX_V5_MASTER.md`
- 이전 기록: `docs/v5_progress/015_krx_v5_stage40_fast_validation_checkpoint_20261122.md`
- 운영 워크플로: `.github/workflows/v5-stage28-final-orchestrator.yml`
- 개발 원칙: 프로그램 우선, `push` 시 오프라인 빠른 검사만, 실시간 API는 독립 예약/승인된 신규 일자에만, 중복 호출 방지, 날짜별 공식 데이터 및 기존 원장 불변, 스마트폰에서 동일명 YAML 전체 교체.

## Stage41~53 진척
1. Stage41~52는 동결 코호트 253행과 성과 관측 759건을 보존하면서 보통주·공식 시가총액 근거를 단계별로 구분함. 시장자료 70거래일 아카이브와 DART 캐시를 재사용함.
2. Stage52 #59 (`45113231572`) 오프라인 456개 검사 통과. Stage53 #60 (`45115957649`) 오프라인 478개 검사 통과. push는 실제 KRX API와 긴 통합 프로세스를 실행하지 않았음.
3. Stage53에 독립 작업 `p3-basic-capture` 추가: KOSPI `stk_isu_base_info` 및 KOSDAQ `ksq_isu_base_info`, 기존 GitHub Secret `KRX_API_KEY`, 같은 날짜의 성공 원본은 읽기 전용 재사용.
4. 수동 실행 #61 (`45137550078`, 11/23 17:18 KST): 첫 KOSPI 기본정보 요청에서 HTTP 401, 1회 시도, `RETRY_ELIGIBLE`, 저장 없음. 원인은 KRX 계정의 별도 서비스 이용 승인 전 상태로 확인. **GitHub 녹색 완료가 데이터 수집 성공이라는 뜻은 아님.**
5. 서비스 승인 뒤 수동 실행 **#62** (`45146104516`, 11/23 18:20 KST): `STAGE53_OFFICIAL_BASIC_CAPTURE_SAVED`; KRX 공식 API **2회 성공**, KOSPI **935건**, KOSDAQ **1,836건**, 합계 **2,771건**. GitHub 아카이브에 실제 JSON 저장 완료.

## 현재 영구 자료와 검증 범위
- 파일: `data/v5_official_shareclass_archive/20261120.json`
- blob SHA: `db0b570c5ff1f6ef64fb513291821adce65eda35`
- `canonical_rows_sha256`: `0616be604ddfe5a3327088e0faf05bee2341fc6303ab60a8d3daad2d91b7f61e`
- 출처: `KRX_OFFICIAL_OPEN_API_STOCK_BASIC`, API 요청 횟수 2회, 인증키 로그 미기록.
- 전 시장 분류: 보통주·주식종류별 시총과 시장자료 결합 일치 **1,188건**, 시총 1천억 미만 **1,427건**, 비보통주/분류 불명 **109건**, 주권 외 그룹 **47건**. 합계 2,771건.
- 연구용 A/B 137건(**A 24 / B 113**)은 보통주·시총·종목코드와 시장자료 결합 **137건 전부 일치**. 253건 동결 연구 기록과 759건 5/10/20일 관측 결과 별도 보존.
- **주의:** KRX 종목기본정보 응답이 요청된 20261120의 독립적인 자료 기준일을 증명하지 못했음. `p3_independently_date_verified=false`, `p3_research_only_if_not_self_dated=true`. 137건은 **요청일 결합 연구 근거**일 뿐 엄격한 역사적 기준일 인증 완료 아님.
- P1 역사적 재무 사실 증명: 0건. P2 공식 일자별 PER/PBR 인증: 0건. 최종 매수 신호 0건. A/B 연구 등급을 실제 매수 승인으로 승격하지 않음.

## Stage54 작업 지시 및 변경 사항
1. Stage53 파일을 **새 API 요청 없이** 불변 입력으로 사용해 `v5_reports/stage28/r14_stage54_p3_cached_evidence_YYYYMMDD.json`에 A/B 연구 후보 일자별 P3 연결 상태 기록.
2. 전체 시장 2,771행 및 137후보의 종목코드/시장/종가/시가총액/보통주 정보, 날짜별 공식 파일과 SHA256·응답 출처/행수 점검.
3. `P3=REQUEST_BOUND_RESEARCH_ONLY`를 유지하고 `P1=P2=0`, 매수 신호 0. KRX 종목기본정보의 실제 기준일 자체 증명 누락을 가리지 않음.
4. `p3-basic-capture`에서 성공 JSON이 생성되지 않았는데도 green success가 뜨는 문제 수정: 예상 날짜 파일 누락 시 실패로 보고. 동일 날짜 이미 성공 파일이 있으면 조회 없이 재사용.
5. KRX Open API 상용 서비스 목록과 KRX Data Marketplace/KIND의 PER·PBR 제공 범위 및 산식 차이를 확인한 후 P2 공식 출처 수집에 착수. Open API 일별매매정보에 없는 PER/PBR을 임의 생성하지 말 것.
6. 반복적인 40~50분 통합 실행을 하지 않고 개발 변경분은 `quick-change-check`로 빠르게 확인. 캘린더 기준 08:30(KST) 전 거래일 방식 유지, 거래일이 아닌 날 투자 보고 생략.

## 스마트폰 작업 방법
- ZIP 없이 `.github/workflows/v5-stage28-final-orchestrator.yml` 전체 교체 파일 한 개 다운로드 후 기존 파일 교체.
- GitHub Actions는 push 오프라인 검사만. 실제 P3 수집은 기존 `p3-basic-capture` 예약/공식 시장자료 수집 후에 실행.
- 마스터에 이 기록 016 링크 추가. 이 문서와 마스터를 GitHub `main`에 업로드해야 지속 저장된 것임.
- 새 채팅 시작 시: **마스터 + 작업기록 016 + #62 공식 P3 데이터 + Stage54 실행 결과**부터 확인. 이전 검증 반복하지 않음.
