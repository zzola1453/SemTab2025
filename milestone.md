# 📅 15주차 마일스톤 (SemTab CEA 시스템 개발)

---

## 🔵 Phase 1 — 기초 이해 & 환경 구축 (1~4주차)

### 1주차 — 챌린지 태스크 분석

- SemTab 2025 MammoTab 트랙 공식 문서 정독, CEA 태스크 정의 파악
- 리더보드 상위 팀 확인 (ADFr F1=0.758 / RAGDify F1=0.603 / ditlab F1=0.549) — ADFr 논문 미공개 확인
- 공개된 논문 2편 (RAGDify, Iterative Refinement) 확보 및 접근법 비교 정리
- MammoTab 데이터셋 826개 테이블 샘플 다운로드 및 구조 파악

### 2주차 — 선행 연구 심화 분석

- RAGDify 논문 심화 분석: 4단계 파이프라인(전처리→후보검색→Debate→Verification) 구조 및 Elasticsearch 기반 검색 전략 정리
- Iterative Refinement 논문 심화 분석: CTA-CEA 반복 구조, 전치 테이블 전략, 비지도 일관성 스코어(Consistency/Entropy) 개념 정리
- Collective Inference 개념 정리 및 우리 시스템 적용 방안 검토
- Wikidata KG v.20240720 데이터 포맷 및 규모 파악 (엔티티 수, 필드 구조)

### 3주차 — 개발 환경 구축

- Docker + Elasticsearch 환경 구축 및 동작 확인
- Wikidata KG 인덱싱 설계 (레이블·설명·alias 필드 구성)
- 인덱싱 파이프라인 구현 및 소규모 샘플(10만 엔티티) 테스트 인덱싱

### 4주차 — KG 전체 인덱싱 & Exact match 구현

- Wikidata KG 전체 인덱싱 완료
- Exact match 검색 모듈 구현 및 동작 검증
- 샘플 테이블 20개로 Exact match 단독 성능 측정 (베이스라인 수립)

---

## 🟡 Phase 2 — 파이프라인 구현 (5~9주차)

### 5주차 — 검색 고도화 (Fuzzy + LLM 쿼리 재작성) ✅

- ✅ Fuzzy match(≥75%) 폴백 검색 구현
- ✅ LLM 쿼리 재작성 모듈 구현 (alias·약어 처리, API 키 없어 비활성화 — 코드만 존재)
- ✅ Cross-encoder Reranker 구현 및 826t 실행 완료 (F1=0.344, 2026-06-01)

### 6주차 — Debate & Verification 프롬프트 구현 ✅

- ✅ 후보 순위 결정(Debate) 프롬프트 설계 및 테스트
- ✅ 검증(Verification) 프롬프트 구현, NIL 판단 로직 포함
- ✅ Collective Inference 구현, 20개 테이블 end-to-end 파이프라인 실험

### 7주차 — Dense Retrieval 재순위 검색 ✅

- ✅ E5 임베딩 모델(`intfloat/e5-large-v2`) 세팅 및 Dense Reranker 구현
- ✅ Ensemble Reranker 구현 (Cross-encoder 60% + Dense 40% 가중 혼합)
- ✅ Dense 826t 실행 (F1=0.344) / Ensemble 826t 실행 (F1=0.378) 완료 (2026-06-01)

### 8주차 — Agentic LLM 전략 전환 & 전체 실행 ✅

- ✅ ReAct-style Agent 구현 (`src/cea/agent.py`, `src/cea/tools.py`)
- ✅ 커버리지 100% 달성 (숫자/날짜 필터 제거, P-prefix QID 검증 추가)
- ✅ 826개 테이블 전체 실행 완료 (qwen2.5:14b, step=2, 약 40시간)
  - 84,512개 어노테이션 / 99.5% 커버리지
  - ✅ Google Form 제출 완료 (2026-06-11) — 공식 F1: **0.332**, P: 0.332, R: 0.331 (수신 2026-06-12)

### 9주차 — 중간 성능 평가 & 오류 분석 ✅

- ✅ 전체 826개 테이블 1차 추론 실행 완료 (BM25 top-1, 2026-05-18 제출)
- ✅ 공식 F1 수신 (2026-06-06): Rerank=0.344 / Dense=0.344 / Ensemble=0.378
- ✅ 최종 확인: **Debate F1=0.489** (최고) / Ensemble=0.378 / Agent=0.332 — 목표(0.758) 대비 0.269 격차
- ✅ 오류 분석 → Agentic LLM 전략 채택

---

## 🔴 Phase 3 — 최적화 & 마무리 (10~15주차)

### 10주차 — 공식 결과 수신 ✅

- ✅ 전체 제출 공식 F1 수신 (2026-06-12): Debate=0.489(최고), Ensemble=0.378, Agent=0.332, Rerank=0.344, BM25=0.242
- ✅ 목표 미달 원인 확정: BM25 Recall 병목 > 로컬 LLM 한계 > KG 커버리지 부족

### 11주차 — 원인 분석 & 개선 방향 도출 ✅

- ✅ BM25 Recall 병목 심층 분석: 검색 범위(Recall@10) vs Reranker 품질 분리
- ✅ Debate 고Precision/저Recall 원인 파악: LLM이 불확실 셀을 기권 → 커버리지 61%로 제한
- ✅ Agent 저Precision 원인 파악: 커버리지 100% 달성 과정에서 오답 포함 → Precision 하락
- ✅ 향후 개선 방향 3가지 확정: Dense 전체 인덱스 / 강력한 LLM / Collective+Agent 결합

### 12주차 — 최종 제출 전략 확정 ✅

- ✅ Agent 결과(F1=0.332) 제출 완료 — 전체 최고는 Debate(F1=0.489)
- ✅ 제출 파일 전수 검증: 형식·QID·중복 모두 이상 없음 (84,512개 어노테이션)
- ✅ 처리 성능 지표 정리: Ensemble 104분 vs Agent 40시간 비교
- ✅ 실험 추적 9개 최종 완성 (`output/experiments.csv`)

### 13주차 — 시스템 성능 종합 평가 ✅

- ✅ CEA 난제별 현재 시스템 대응 수준 평가 완료
- ✅ 목표 미달 원인 및 향후 개선 방향 3가지 우선순위 도출
- ✅ 최종 성과 정리: Agent F1=0.332 / 전체 최고 Debate F1=0.489 (목표 0.758 대비 0.269 격차)

### 14주차 — 코드 정리 & 문서화 ✅

- ✅ 코드 정리 완료: 임시 스크립트 제거, 모듈 독립성 강화
- ✅ README 최신화: 실험 결과 9개, Agent 포함 파이프라인 설명
- ✅ GitHub 업로드 준비 완료

### 15주차 — 전체 프로젝트 소감문 ✅

- ✅ 14주간 프로젝트 전체 회고 작성 (소감문 형태)
- ✅ 핵심 교훈 정리: 실험 추적, silent 버그 주의, 검색 Recall이 성능 상한 결정
- ✅ 향후 연구 방향 제시 (Dense 전체 인덱스·강력한 LLM·Collective+Agent 결합)
