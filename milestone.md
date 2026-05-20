# 📅 14주차 마일스톤 (SemTab CEA 시스템 개발)

---

## 🔵 Phase 1 — 기초 이해 & 환경 구축 (1~4주차)

### 1주차 — 챌린지 태스크 분석

- SemTab 2025 MammoTab 트랙 공식 문서 정독, CEA 태스크 정의 파악
- 리더보드 상위 팀 확인 (ADFr F1=0.758 / RAGDify F1=0.603 / ditlab F1=0.549) — ADFr 논문 미공개 확인
- 공개된 논문 2편 (RAGDify, Iterative Refinement) 확보 및 접근법 비교 정리
- MammoTab 데이터셋 870개 테이블 샘플 다운로드 및 구조 파악

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

### 5주차 — 검색 고도화 (Fuzzy + LLM 쿼리 재작성)

- Fuzzy match(≥75%) 폴백 검색 구현
- Claude Haiku 기반 LLM 쿼리 재작성 모듈 구현 (alias·약어 처리)
- 검색 모듈 통합 및 Recall 변화 측정

### 6주차 — Debate & Verification 프롬프트 구현

- 후보 순위 결정(Debate) 프롬프트 설계 및 테스트
- 검증(Verification) 프롬프트 구현, NIL 판단 로직 포함
- 50개 테이블 end-to-end 파이프라인 실험

### 7주차 — Dense Retrieval 하이브리드 검색

- E5 또는 BGE 임베딩 모델 세팅
- BM25 + Dense 하이브리드 검색 구현
- 하이브리드 vs BM25 단독 성능 비교 (Recall 변화 분석)

### 8주차 — Collective Inference 구현

- 같은 테이블 내 확정 어노테이션을 다음 셀 컨텍스트로 재활용하는 iterative 로직 구현
- Cross-column consistency 체크 추가
- 전체 파이프라인 통합 테스트 (200개 테이블)

### 9주차 — 중간 성능 평가 & 오류 분석

- 전체 870개 테이블 1차 추론 실행
- F1·Precision·Recall 측정, 오류 케이스 샘플링
- 오류 유형 분류 (Disambiguation / Alias 미처리 / NIL 오판 등)

---

## 🔴 Phase 3 — 최적화 & 마무리 (10~14주차)

### 10주차 — Disambiguation & Alias 집중 보강

- 오류 분석 결과 기반, 동명이인·약어 케이스 처리 강화
- 프롬프트 재설계 및 few-shot 예시 추가
- 보강 후 성능 재측정

### 11주차 — NIL 탐지 최적화

- NIL Confidence threshold 캘리브레이션
- NIL 오판 케이스 집중 분석 및 Verification 프롬프트 개선
- Precision vs Recall 트레이드오프 조정

### 12주차 — 앙상블 & 최종 튜닝

- 복수 retrieval 전략 결과 voting 앙상블 구현
- 전체 파이프라인 asyncio 병렬화로 속도 최적화
- 870개 테이블 최종 추론 실행

### 13주차 — 최종 성능 검증 & 제출 준비

- F1 목표치(≥0.758) 달성 여부 확인
- 제출 형식(filename, row_id, col_id, entity_id) 검증
- 미달 시 취약 구간 집중 보완

### 14주차 — 결과 정리 및 문서화

- 전체 시스템 구조 및 실험 결과 정리
- 제출 파일 최종 생성 및 Google Form 제출
- 연구 회고 및 향후 개선 방향 정리
