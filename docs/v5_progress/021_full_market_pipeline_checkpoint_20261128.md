# KRX v5 작업기록 021 — 2026-11-28 (KST)

## 1. 저장소 및 재개 지점
- 저장소: cks3210-spec/KRX-Public-Test / main
- 마스터: KRX_V5_MASTER.md (변경하지 않음)
- 이전 기록: docs/v5_progress/020_stage6_1_growth_quality_checkpoint_20261127.md
- 다음 작업: 2026-11-30 실제 거래일 자동 운영 및 통합평가 검증. 중간 개발, 수동 재실행, 반복 파일 교체 금지.

## 2. 직접 확인된 자료 및 등록 상태
- data/summary.json: 20261126, KOSPI 935 + KOSDAQ 1837 = 2772종목.
- data/v5_kis_valuation/sessions/20261127/status.json: KIS_BROKER_COLLECTION_COMPLETE, 시장 2772종목, 성공 2676종목. 수집 완료 표시이며 회계 기준 또는 공식 PER/PBR 검증을 의미하지 않는다.
- KRX와 KIS 기준일 불일치. 11/30 오전 KRX 20261127 자료 확보 후 동일일 검증.
- data/v5_full_research/latest_status.json: 11/28 조회 시 404(미생성).
- 최종 교체 파일 5개 GitHub main 등록 확인: scripts/v5_full_decision.py, scripts/v5_full_sector_valuation.py, scripts/v5_full_performance_briefing.py, scripts/v5_full_pipeline.py, .github/workflows/v5-full-research-pipeline.yml.
- 이전 모듈: v5_evaluation_scope.py, v5_full_financial_evaluation.py, v5_full_kis_evaluation.py, v5_full_share_evidence.py, v5_full_ratio_evidence.py, v5_full_grade_strategy.py, v5_valuation_crosscheck.py.
- .github/workflows/v5-full-share-evidence.yml의 09:20 예약 확인.
- 기존 Stage7 및 Research Chain Recovery 비활성화는 사용자 완료 보고에 근거. API 권한 제한으로 직접 확인 불가. 기존 소스 삭제 금지(신규 모듈 일부 기능 재사용).
- 오전 09:00 및 오후 14:00 ChatGPT 예약 브리핑 활성화 및 신규 통합 status.json 참조 변경을 예약 설정 조회로 직접 확인.

## 3. 개발 범위 및 미완료 사항
- 전체 평가 범위, 재무/성장성/건전성, KIS 연결, 주식수 수집/암호화 캐시, EPS/BPS 수치 대조, 업종별 연구용 가격 범위, 연구 등급, 매매 모의전략, 5/10/20거래일 성과, 통합 실행/중복 방지 구현 파일 등록 완료.
- 이전 개발 응답의 모의검증 132/132는 당시 보고값이며 이 기록 작성 시 재실행하지 않았다. 실제 통합 성공으로 해석 금지.
- 독립적인 KIS 회계 기준, 보통주 귀속 순이익/자기자본, 가중평균 주식수, 기업행위 및 시점 검증 미완료. 검토 근거 확보 및 최종 등급 공개 경로 미완료. 확정 적정주가와 최종 투자등급/매매 승인 보류. 수치 일치만으로 승격 금지.
- 공개 저장소에는 집계 상태와 암호화 원본만 사용. 키나 복호화 원본 공개 금지. 실제 검증자료 없는 최종 후보 생성 금지.

## 4. 11월 30일 자동 운영 검증 계획 (KST)
| 예정 | 작업 | 확인 |
|---|---|---|
| 08:30 | KRX 전 거래일 자료 수집 | 20261127 공식 자료 확보/게시, 실제 시작/완료 시각 |
| 08:50 | 신규 전체 통합평가 | 기준일, 범위 해시, 재무/KIS 연결, 실행 및 상태 저장 |
| 09:00 | 오전 브리핑 | 최신 통합 상태 참조, 보류/실패 구분 |
| 09:20 | 주식수 수집 | 캐시 재사용, 누락/변경만 수집, 최대 200 API 호출, 후속 평가 |
| 13:40 | 통합평가 보완 | 지연 자료 반영, 동일 입력 중복 평가 방지 |
| 14:00 | 오후 브리핑 | 최신 결과 및 오전 대비 변화 |
| 16:50 | KIS 수집 | 20261130 세션 수집/암호화 저장, 다음 거래일용 |

- 08:50/13:40은 GitHub 예약으로 실제 실행 시각 검증 필요. 08:30/16:50 외부 무료 예약 서비스 기존 설정 유지. 성공 배지만으로 실제 수집 성공 판정 금지.
- 신규 통합 결과: data/v5_full_research/latest_status.json. Actions run_id, source_commit, market_date, scope_sha256, input_fingerprint, 집계, blockers, 실제 평가/저장 단계 대조.
- 전환 전 실행은 신규 자동 운영 검증으로 계산하지 않는다. 연속 정상 2거래일은 안정성 판정 기준일 뿐 개발 지연 조건이 아니다.

## 5. 확정 개발 및 운영 원칙
- 스마트폰 전용, 전체 파일 교체, 다운로드/업로드 바로가기. 중간 수정파일 반복 업로드 금지. 개발 → 통합 → 자체검증 → 최종 변경 파일 일괄 업로드 → 실제 검증. 정상 프로그램은 수정하지 않고 실제 오류만 모아 한꺼번에 수정.
- 시가총액 1000억원 이상 보통주, 전 적격 종목 동일 조건, 임의 후보 수 제한 금지, 최종 A/B만 표시. 자료 누락 사유 보존 및 보류. 골든크로스 사용 중단.
- 기존 자료 최대 재사용, 불필요한 금융 API 호출 금지. KRX 08:30, 휴장일 차단, 최대 3회/60초 간격 기존 원칙 유지. 무료 운영, 사용자 ID/비밀번호 저장 금지.
- 11/28 최종 일괄 교체 완료 후 추가 프로그램 업로드/실행 불필요. 1=진행, 완=사용자 작업 완료.

## 6. 다음 채팅 재개 문구
득이야, KRX v5 마스터와 docs/v5_progress/021_full_market_pipeline_checkpoint_20261128.md를 확인하고 이어서 진행하자. 11월 28일 최종 파일 5개 등록 완료. 11월 30일 실제 자동 운영부터 검증하고, 오류는 모아서 한 번에 수정하자. 이미 개발된 모듈을 반복 제작하거나 수동 실행하지 말자.
