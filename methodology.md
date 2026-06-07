# CEA 시스템 방법론 정리

**작성일**: 2026-06-01 (최종 업데이트: 2026-06-08)  
**과제**: MammoTab SemTab 2025 — Cell Entity Annotation (CEA)  
**목표**: CSV 테이블 셀 값 → Wikidata 엔티티 URI(QID) 자동 매핑

---

## 전체 파이프라인 구조

```
셀 값 입력
    ↓
[전처리] 날짜/숫자 컬럼 스킵, 셀 컨텍스트 생성
    ↓
[후보 검색] BM25 → row hint 폴백 → Fuzzy 폴백 → LLM 쿼리 재작성
    ↓
[후보 선택] BM25 top-1 / Cross-encoder Reranker / LLM Debate
    ↓
[검증] LLM Verification (선택)
    ↓
[일관성] Collective Inference (선택)
    ↓
출력: filename, row_id, col_id, entity_id
```

---

## 방법론별 상세 설명

### 1. Wikidata KG 인덱싱

**목적**: 78,647,123개 엔티티를 로컬 Elasticsearch에 적재하여 오프라인 고속 검색 환경 구축

**방법**:
- 원본: `latest-all.nt.bz2` (163GB, NTriples 형식)
- 파싱: `bzcat subprocess` → SQLite 중간 저장 → ES 벌크 업로드
- 인덱스 필드: `qid`, `label`, `description`, `aliases`
- 소요: Phase 1 (NT→SQLite) ~21시간, Phase 2 (SQLite→ES) ~86분

**결과**: ES `wikidata_entities` 인덱스, BM25 검색 평균 레이턴시 50ms 미만

---

### 2. BM25 Baseline (ES top-1)

**목적**: 가장 단순한 베이스라인 — 셀 값으로 ES 검색 후 top-1 후보를 그대로 제출

**방법**:
```
쿼리 전략 (should 절 가중치 조합):
  - label.keyword 완전 일치 (boost 20)
  - label phrase match (boost 10)
  - aliases phrase match (boost 8)
  - label + aliases + description multi_match (boost 3/2/1)
```
후보가 없으면 row 내 이웃 셀 값을 합쳐 재검색 (row hint 폴백)

**실험 결과**:

| 실행 | 테이블 | 제출 | 커버리지 | 비고 |
|------|--------|------|---------|------|
| 소규모 테스트 | 3개 | 247개 | 81.2% | Wikidata API 백엔드 |
| 전체 실행 | 826개 | 77,140개 | 90.9% | **제출 완료 (2026-05-18)** |

**한계**:
- 오탈자·약어·이명에 취약 (키워드 빈도 기반)
- 동명이인 처리 불가 (컨텍스트 무시)
- 커버리지 90.9% → 나머지 9.1%는 KG 미매핑

---

### 3. LLM Debate (Ollama 로컬 LLM)

**목적**: BM25 상위 후보 5개를 LLM이 비교해 최적 QID 선택 → Disambiguation 해결

**방법**:
- 모델: `qwen2.5:14b` (Ollama 로컬 실행, API 키 불필요)
- 프롬프트 입력: 셀 값 + 컬럼 컨텍스트 + 테이블 샘플 + 후보 5개 (QID|레이블|설명)
- 출력: QID 단일 응답 (형식 오류 시 top-1 fallback)
- Collective Inference: 확정된 어노테이션(최대 8개)을 다음 셀 프롬프트에 주입

**프롬프트 핵심 구조**:
```
Table context (first rows): ...
Target cell: row=1, col=1, value="Brazil"
Same row values: 1985, Adventure
Candidates:
  1. Q155 | Brazil | Federative Republic of Brazil
  2. Q105512 | Brazil | 1985 film by Terry Gilliam
  ...
Select the best matching QID. Output only the QID.
```

**실험 결과**:

| 실행 | 테이블 | 제출 | 커버리지 | 비고 |
|------|--------|------|---------|------|
| 전체 실행 1차 | 826개 | 47,629개 | 56.1% | LLM 응답 형식 오류 다수 |
| 전체 실행 2차 | 826개 | 51,894개 | 61.1% | **제출 완료 (2026-05-26)** |

**한계**:
- 커버리지 급감 (90.9%→61.1%): LLM 응답 형식 오류, 확신 부족 시 응답 거부
- 로컬 14B 모델의 한계 — 더 큰 모델이나 API 모델 필요

---

### 4. Cross-encoder Reranker

**목적**: BM25 상위 10개 후보를 의미적 유사도로 재순위 → LLM 없이 Disambiguation 보완

**방법**:
- 모델: `cross-encoder/ms-marco-MiniLM-L-6-v2` (로컬 실행, GPU 활용)
- 입력 쌍: `(셀값 + 컬럼헤더 + row컨텍스트, 후보 레이블 + 설명)`
- 구분자: `[SEP]` 토큰으로 쿼리와 문서를 연결
- 재순위 후 최고 점수 후보를 선택 (nil_threshold 미설정 → 항상 반환)

**쿼리 포맷**:
```
Brazil [SEP] column: Films [SEP] row: 1985 | Adventure
```

**실험 결과**:

| 실행 | 테이블 | 제출 | 커버리지 | 소요 |
|------|--------|------|---------|------|
| 전체 실행 | 826개 | 76,797개 | 90.4% | 19분 |

**특징**:
- BM25 대비 커버리지 소폭 감소 (-343개): 재순위 과정에서 일부 후보 재정렬
- QID 선택의 질적 차이는 공식 F1로만 확인 가능
- API 키 불필요, RTX 4080 Super 기준 빠른 처리

---

### 5. Fuzzy Match 폴백

**목적**: BM25 + row hint 이후에도 후보가 없는 셀 커버 → 오탈자·유사 표기 처리

**방법**:
- ES `fuzzy` 쿼리 (`fuzziness: AUTO`) — 문자열 길이별 허용 편집 거리 자동 조정
  - 1~2자: 0회, 3~5자: 1회, 6자+: 2회 편집 허용
- ES `match` 쿼리 (`minimum_should_match: 75%`) — 토큰 레벨 75% 이상 일치
- 적용 시점: BM25 검색 실패 → row hint 검색 실패 → Fuzzy 검색

**폴백 체인**:
```
BM25 검색 → 실패 시 row hint 재검색 → 실패 시 Fuzzy 검색 → 실패 시 NIL
```

**실험 결과**:

| 실행 | 테이블 | 제출 | 커버리지 | 소요 |
|------|--------|------|---------|------|
| Reranker + Fuzzy | 826개 | 76,974개 | 90.7% | 19분 |

**효과**: Reranker 단독(76,797개) 대비 **+177개** 추가 커버

---

### 6. Collective Inference

**목적**: 같은 테이블 내 확정 어노테이션을 다음 셀 컨텍스트로 재활용 → 컬럼 일관성 향상

**방법**:
- 테이블 내 셀을 순차 처리 (병렬 처리 대신 sequential)
- 신뢰도 이상 확정된 어노테이션(최대 8개)을 Debate 프롬프트에 주입
- 예: "Already confirmed: row=1,col=1→Q155(Brazil, country)"

**실험 결과**:

| 실행 | 테이블 | 제출 | 커버리지 | 소요 |
|------|--------|------|---------|------|
| Reranker + Collective | 826개 | 76,797개 | 90.4% | 40분 |

**특징**:
- 어노테이션 수는 Reranker와 동일 — 커버리지가 아닌 QID 선택의 질에 영향
- 순차 처리로 소요 시간 2배 증가 (19분→40분)
- 오류 전파 위험: 초기 잘못된 어노테이션이 후속 셀에 영향

---

## 실험 결과 종합

| 방법론 | 어노테이션 | 커버리지 | F1 | Precision | Recall | 상태 |
|--------|-----------|---------|-----|-----------|--------|------|
| BM25 top-1 | 77,140개 | 90.9% | — | — | — | ✅ 제출 완료 (2026-05-18), 결과 미수신 |
| LLM Debate (Ollama) | 51,894개 | 61.1% | — | — | — | ✅ 제출 완료 (2026-05-26), 결과 미수신 |
| Cross-encoder Reranker | 76,797개 | 90.4% | **0.344** | 0.362 | 0.328 | ✅ 공식 결과 수신 (2026-06-06) |
| Dense (E5) Reranker | 76,974개 | 90.7% | **0.344** | 0.362 | 0.328 | ✅ 공식 결과 수신 (2026-06-06) |
| Ensemble (Cross+Dense) | 76,974개 | 90.7% | **0.378** | 0.398 | 0.360 | ✅ 공식 결과 수신 (2026-06-06) **현재 최고** |
| Agent qwen2.5:14b step2 (826t) | 진행 중 | **100% 예상** | 미측정 | — | — | 🔄 실행 중 (2026-06-07~, 완료 6월 11일 예정) |

**목표**: F1 ≥ 0.758 (ADFr 1위) — 현재 최고 0.378, 격차 **0.380**

---

## 7. ReAct Agentic CEA (qwen2.5:14b 로컬)

**목적**: LLM이 Think→Act→Observe 루프를 돌며 검색 전략을 자율 결정 → Disambiguation·Alias 해결

**방법**:
- 도구 4개: `search_entities`(BM25), `search_fuzzy`(ES fuzziness), `get_entity_details`(Wikidata API), `submit_answer`
- max_steps=2: 1회 검색 → 결과 확인 → submit_answer (속도·품질 균형)
- NIL 반환 시 파이프라인이 BM25 top-1으로 자동 fallback

**실험 결과 (10테이블)**:

| 모델 | steps | 제출 | 커버리지 | 소요 | 품질 |
|------|-------|------|---------|------|------|
| llama3.1:8b | 5 | 679 | 79.5% | 20분 | LYQZQ0T5,1,1=Q42 ❌ |
| qwen2.5:14b | 5 | 679 | 79.5% | 67분 | LYQZQ0T5,1,1=Q3576864 ✅ |
| qwen2.5:14b | 2 | 679 | 79.5% | 36분 | LYQZQ0T5,1,1=Q3576864 ✅ |

**커버리지 분석**: 79.5%는 ES 후보 자체가 없는 175개 셀 때문 (BM25·row_hint·fuzzy 3단계 모두 실패). 모델 교체로는 해결 불가.

**qwen step5 vs step2**: QID 28.6% 차이, 속도 1.85x — step2 채택 (826t 실행 ~49시간)

---

## 구현됐으나 미실험된 방법론

### Dense Retrieval 하이브리드 (HybridRetriever)
- **아이디어**: BM25(어휘 기반) + E5-large-v2 임베딩(의미 기반)을 RRF로 결합
- **상태**: 코드 완성, Dense 인덱스 미적재
- **예상 효과**: alias·오탈자·의미적 유사 케이스 Recall 향상
- **소요**: RTX 4080 Super 기준 임베딩 2~4시간 + ES 업로드 1~2시간

### LLM Verification
- **아이디어**: Debate 선택 후보를 LLM이 독립적으로 재평가, NIL 판단
- **상태**: 코드 완성, 전체 실험 미실행
- **예상 효과**: Precision 향상 (단 커버리지 감소 트레이드오프)

### LLM Query Rewriting
- **아이디어**: 셀 값의 약어·이명을 LLM이 대안 쿼리로 확장 후 재검색
- **상태**: 코드 완성, API 키 없이 비활성화 상태
- **예상 효과**: Alias Resolution 개선 → Recall 향상

---

## 핵심 설계 결정 및 교훈

| 결정 | 이유 | 결과 |
|------|------|------|
| asyncio 단일 루프로 전체 처리 | 이벤트 루프 캐싱 버그(silent failure) 해결 | 안정적 전체 실행 |
| SQLite 중간 저장 + 체크포인트 | 163GB 인덱싱 중 오류 시 재시작 방지 | 21시간 작업 안정 완료 |
| 검색 추상화 레이어 (BaseRetriever) | BM25/Dense/API 백엔드 교체 용이성 | HybridRetriever 추가 시 파이프라인 무수정 |
| Debate fallback to top-1 | LLM 형식 오류 시 커버리지 보호 | Recall 손실 최소화 |
| Fuzzy를 폴백 마지막 단계로 배치 | Precision 보호 (fuzzy 단독은 노이즈 많음) | +177개 추가 커버, Precision 유지 |
| Agent max_steps=2 채택 | step5 대비 1.85x 속도, 71.4% 동일 QID → 허용 가능한 품질 손실 | 826t 실행 가능한 시간으로 단축 |
| Agent NIL → BM25 fallback | LLM이 NIL 반환해도 커버리지 보호 | 구조적 미제출(ES 후보 없음)만 스킵 |
| 숫자/날짜 컬럼 필터 제거 | 타겟 파일이 대상 셀을 이미 지정 — 필터가 연도 엔티티(1976→Q2002 등)를 잘못 스킵 | 커버리지 79.5% → 100% |
| P-prefix QID 검증 추가 (`^Q\d+$`) | LLM이 Property ID(P1907 등)를 제출하는 버그 차단 | 비정상 QID 0개 보장 |
