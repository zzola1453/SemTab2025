# CLAUDE.md — SemTab MammoTab CEA 시스템 개발 가이드

## 목표

**Cell Entity Annotation(CEA)** 시스템을 개발해 MammoTab 리더보드 1위(ADFr, F1=0.758)를 초과한다.

| 모델 | F1 |
|------|----|
| ADFr (1위) | 0.758 |
| RAGDify (2위) | 0.603 |
| ditlab (3위) | 0.549 |

**목표: F1 ≥ 0.758**

---

## 태스크 정의

CSV 테이블의 각 셀을 **Wikidata KG(v.20240720)** 엔티티 URI에 매핑한다.

- **입력**: CSV 테이블 + `(row_id, col_id, cell_value)` 리스트
- **출력**: `filename, row_id, col_id, entity_id` (예: `LYQZQ0T5,1,1,Q3576864`)
- **데이터셋**: 826개 테이블, 84,907개 셀 어노테이션
- **제약**: LLM 기반(Fine-tuning 또는 RAG)만 허용

### 평가 지표

```
Precision = correct / submitted
Recall    = correct / ground_truth
F1        = 2PR / (P+R)   ← 1차 기준 / 동점 시 Precision이 2차 기준
```

### 데이터 형식

입력:
```csv
col0,col1,col2
1976,Eat My Dust!,Charles Byron Griffith
1976,Hollywood Boulevard,Joe Dante
```

출력:
```
LYQZQ0T5,1,1,Q3576864
LYQZQ0T5,2,1,Q229390
```

NIL(KG에 없는 엔티티)은 해당 셀을 제출 생략하거나 명시적 마킹.

---

## 핵심 난제 및 대응 전략

| 난제 | 설명 | 대응 |
|------|------|------|
| Disambiguation | 같은 표면형 → 다른 엔티티 | 테이블 컨텍스트 기반 재순위 |
| Homonymy | 동일·유사 이름 엔티티 다수 | Debate + 검증 단계 |
| Alias Resolution | 약어·닉네임·이명 | LLM 쿼리 재작성 |
| NIL Detection | KG에 없는 엔티티 | 명시적 NIL 옵션 포함 검증 |
| Noise Robustness | 오탈자·불완전 컨텍스트 | 전처리 정규화 |
| Collective Inference | 셀 간·컬럼 간 일관성 | 테이블 단위 배치 어노테이션 |

---

## 시스템 파이프라인

```
[CSV 테이블 입력]
      ↓
1. 전처리
   - 오탈자 교정, HTML 제거, 셀 값 정규화
      ↓
2. 후보 검색 (Candidate Retrieval)
   - Exact match  →  Elasticsearch/BM25
   - LLM 쿼리 재작성  →  컨텍스트·alias 반영 재검색
   - Fuzzy match (≥75%)  →  폴백
   - [고도화] Dense Embedding 하이브리드 검색 추가
      ↓
3. 후보 순위 결정 (Debate)
   - 상위 후보 비교, 3가지 근거 포함 논증
   - 출력: URI + Arguments
      ↓
4. 검증 (Verification)
   - 셀·컬럼·테이블 수준 일관성 확인
   - NIL 명시 판단
   - 출력: Verification yes/no + Winning URI or NIL
      ↓
[filename, row_id, col_id, entity_id 출력]
```

### ADFr(1위) 초과를 위한 차별화 포인트

1. **Dense Retrieval 하이브리드**: BM25 + E5/BGE 임베딩 → Recall 향상
2. **Collective Inference**: 같은 테이블 내 확정 어노테이션을 다음 셀 컨텍스트로 재활용 (iterative)
3. **Cross-column consistency**: 동일 컬럼 엔티티 타입 일관성 강제
4. **앙상블**: 복수 retrieval 전략 결과를 voting으로 통합
5. **Fine-tuning** (선택): MammoTab 학습 데이터로 소형 LLM 특화 학습

---

## 프롬프트 템플릿

### 후보 생성
```
주어진 CSV 테이블과 타겟 셀 ({row_id}, {col_id}, {value})에 대해
Wikidata 검색 쿼리를 생성하라.
약어, 동의어, 변형을 고려하라. few-shot 예시: {examples}
검색 텍스트만 출력하라.
```

### Debate & 선택
```
타겟 셀 ({row_id}, {col_id}, {value})과 후보 목록 {candidates}에 대해
최적 매칭을 선택하고 3가지 근거를 제시하라.
(셀 값 / 컬럼 컨텍스트 / 테이블 컨텍스트 참조)
출력: URI: <uri> / Arguments: <논거>
```

### 검증
```
선택된 후보를 재평가하라:
1. 셀 값과의 적합성
2. 컬럼 내 다른 값들과의 일관성
3. 테이블 전체 컨텍스트와의 일관성
4. NIL이 더 적절한지 여부
출력: Verification: yes/no / Winning URI: <uri or NIL>
```

---

## 기술 스택

| 구성 요소 | 사용 옵션 |
|-----------|-----------|
| LLM (경량) | Ollama llama3.1:8b |
| LLM (고품질) | Ollama qwen2.5:14b, qwen2.5:32b |
| 검색 엔진 | Elasticsearch (BM25) |
| Dense Embedding | `intfloat/e5-large-v2`, `BAAI/bge-large-en` |
| Reranker | CrossEncoder + BiEncoder(E5) + EnsembleReranker |
| 병렬 처리 | asyncio + aiohttp |
| 인프라 | Docker + Docker Compose |

> **제약**: 외부 LLM API(Anthropic, OpenAI, Gemini 등) 사용 금지. Ollama 로컬 모델 전용.

---

## 개발 단계

### Phase 1 — 베이스라인 (목표 F1 ≥ 0.55) ✅ 완료
- [x] Wikidata KG v.20240720 Elasticsearch 인덱싱 (78,647,123개 엔티티)
- [x] Exact match + LLM 쿼리 재작성 + Fuzzy 검색 구현
- [x] Debate + Verification 프롬프트 구현
- [x] 출력 형식 검증 및 제출 테스트

### Phase 2 — 고도화 (목표 F1 ≥ 0.70) ✅ 완료
- [x] Dense Retrieval 하이브리드 레이어 추가 (CrossEncoder + BiEncoder E5)
- [x] ReAct-style Agent 구현 (ES search, fuzzy, entity details)
- [ ] Collective Inference (iterative 테이블 단위 배치) 구현
- [ ] NIL Confidence threshold 캘리브레이션
- [ ] 오류 분석 → Disambiguation·Alias 처리 보강

### Phase 3 — 최적화 (목표 F1 ≥ 0.758) 🔄 진행 중
- [x] 앙상블 voting 구현 (ES Ensemble F1=0.378)
- [ ] Cross-column consistency 강제
- [ ] Collective Inference 강화
- [ ] 전체 826개 테이블 추론 및 최종 제출 파일 생성

### 제출 이력
| 실험 | 커버리지 | F1 |
|------|---------|-----|
| BM25 top-1 (no-debate) | 90.9% | - |
| Ollama Debate | 61.1% | - |
| ES Rerank | 90.4% | 0.344 |
| ES Dense | 90.7% | 0.344 |
| ES Ensemble | 90.7% | **0.378** |
| Agent qwen2.5:14b step=2 | 99.5% | 대기 중 |

---

## 참고

- 공식 사이트: https://sem-tab-challenge.github.io/2025/
- MammoTab 문서: https://unimib-datai.github.io/mammotab-docs/
- Wikidata KG 다운로드: https://drive.google.com/file/d/1jxj8Z9WNtAtho7QJHxXQicgOW4Q1NHmu/view
- 제출 폼: https://docs.google.com/forms/d/e/1FAIpQLSd7KVfTi9GrSqUsJTIvrerEDqkVG9A_cSxNoLGnqs-6B1ehxw/viewform
- RAGDify 논문 (2위): https://sem-tab-challenge.github.io/2025/papers/paper_1.pdf
- Iterative Refinement 논문 (Paper 2): https://sem-tab-challenge.github.io/2025/papers/paper_2.pdf