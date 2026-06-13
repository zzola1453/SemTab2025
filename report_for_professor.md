# SemTab 2025 MammoTab CEA 시스템 — 기술 보고서

**과제**: Cell Entity Annotation (CEA)  
**목표**: CSV 테이블의 각 셀 값을 Wikidata 지식 그래프(KG) 엔티티 URI(QID)에 매핑  
**데이터셋**: 826개 테이블, 84,907개 셀  
**목표 점수**: F1 ≥ 0.758 (1위 ADFr)

---

## 문제 정의

| 입력 | 출력 |
|------|------|
| CSV 테이블 + 어노테이션 대상 셀 목록 `(table_id, row_id, col_id)` | `table_id, row_id, col_id, Wikidata_QID` |

**핵심 난제:**

| 난제 | 예시 |
|------|------|
| **동음이의어(Disambiguation)** | "Brazil" → 국가(Q155)? 영화(Q105512)? |
| **이명·약어(Alias)** | "The Beatles" → Q1299, "Beatles"도 같은 엔티티 |
| **KG 미등재(NIL)** | KG에 없는 엔티티는 제출 생략 |
| **노이즈** | 오탈자, 불완전한 표기 |

---

## 전체 파이프라인

```
셀 값
  │
  ▼
[1. 전처리]  날짜·숫자 컬럼 스킵, 셀 컨텍스트(행·열·테이블) 생성
  │
  ▼
[2. 후보 검색]  BM25(ES) → row hint 폴백 → Fuzzy 폴백
  │
  ▼
[3. 후보 선택]  아래 기법 중 하나 적용
  │  ├─ BM25 top-1 (베이스라인)
  │  ├─ Cross-encoder Reranker
  │  ├─ Dense(E5) Reranker
  │  ├─ Ensemble (Cross + Dense)
  │  └─ ReAct Agent (완료, F1=0.332)
  │
  ▼
출력: table_id, row_id, col_id, QID
```

---

## 기법별 설명 — 문제와 해결

---

### 기법 1: Wikidata KG 로컬 인덱싱

**문제**: Wikidata 공개 API는 레이턴시가 높아 84,907개 셀을 실시간으로 검색하면 수백 시간 소요.

**해결**: Wikidata KG v.20240720 덤프(163GB, 7,800만 엔티티)를 Elasticsearch에 직접 적재.

- NTriples 덤프 → SQLite 중간 저장 → ES Bulk Upload
- 인덱스 필드: `qid`, `label`, `description`, `aliases`
- 검색 레이턴시: 평균 50ms 이하

---

### 기법 2: BM25 검색 + 폴백 체인 (베이스라인)

**문제**: 단순 키워드 검색만으로는 약어·이명·오탈자가 있는 셀을 못 찾음.

**해결**: 3단계 폴백 체인 구성.

```
① BM25 검색 (label.keyword 완전일치 우선)
        ↓ 후보 없으면
② Row hint 재검색 (같은 행 이웃 셀 값을 쿼리에 추가)
        ↓ 후보 없으면
③ Fuzzy 검색 (ES fuzziness=AUTO + 75% 토큰 매칭)
        ↓ 모두 실패하면
④ NIL (제출 생략)
```

**결과**: 84,907셀 중 77,140개 제출 (커버리지 **90.9%**)  
공식 F1: **0.242**, Precision: 0.254, Recall: 0.231 (공식 결과 2026-06-12)

---

### 기법 3: LLM Debate (로컬 LLM 기반 동음이의어 처리)

**문제**: BM25 top-1은 동음이의어를 구분하지 못함. "Brazil"이 영화 테이블에 있어도 국가 Q155를 반환.

**해결**: BM25 상위 5개 후보를 LLM(`qwen2.5:14b`, Ollama 로컬)이 테이블 컨텍스트를 보고 최적 후보를 선택.

**프롬프트 핵심 구조:**
```
테이블 미리보기: [1976, Eat My Dust!, Charles Byron Griffith ...]
대상 셀: row=1, col=1, value="Brazil"
같은 행: 1985, Adventure
후보:
  Q155   | Brazil         | 남아메리카 연방 공화국
  Q105512| Brazil         | 테리 길리엄 감독 1985년 영화
→ 최적 QID를 선택하세요
```

**결과**: 826개 테이블, 제출 51,894개 (커버리지 **61.1%**)  
커버리지 급감 원인: 로컬 14B 모델의 응답 형식 오류 및 확신 부족 시 거부  
공식 F1: **0.489**, Precision: **0.645**, Recall: 0.394 (공식 결과 2026-06-12, **전체 최고**)

---

### 기법 4: Cross-encoder Reranker

**문제**: BM25는 키워드 빈도 기반이므로 의미적으로 더 적합한 후보를 낮게 순위 매김.  
LLM Debate는 로컬 모델 한계로 커버리지 손실.

**해결**: `cross-encoder/ms-marco-MiniLM-L-6-v2` 모델로 BM25 top-10 후보를 의미 기반으로 재순위.

- 입력 쌍: `(셀값 + 컬럼헤더 + 행컨텍스트) [SEP] (후보 레이블 + 설명)`
- Cross-encoder는 쿼리-문서 쌍을 동시에 인코딩 → 정밀한 관련도 점수
- API 키 불필요, GPU 로컬 실행 (RTX 4080 Super 기준 19분/826테이블)

**결과:**

| 지표 | 값 |
|------|----|
| 제출 셀 | 76,797개 (90.4%) |
| F1 | **0.344** |
| Precision | 0.362 |
| Recall | 0.328 |

---

### 기법 5: Dense Reranker (Bi-encoder, E5-large-v2)

**문제**: Cross-encoder는 정확하지만, 표기가 다른 유의어나 alias에는 여전히 취약.

**해결**: `intfloat/e5-large-v2` Dense 임베딩으로 BM25 후보를 재순위.

| 항목 | BM25 | Dense(E5) |
|------|------|-----------|
| 기반 | 키워드 빈도(TF-IDF) | 의미 임베딩 벡터 |
| 강점 | 정확한 표기 일치 | 유의어·문맥 이해 |
| 약점 | 동음이의어 구분 불가 | 처음 보는 고유명사 |

- 쿼리 인코딩: `"query: {셀값} column: {헤더} row: {이웃셀}"`
- 문서 인코딩: `"passage: {레이블} {설명}"`
- BM25 점수 30% + Dense 점수 70% 가중 혼합

**결과:**

| 지표 | 값 |
|------|----|
| 제출 셀 | 76,974개 (90.7%) |
| F1 | **0.344** |
| Precision | 0.362 |
| Recall | 0.328 |

*Cross-encoder와 F1 동일하나 예측 QID의 51.3%가 다름 → 앙상블 가능성 확인*

---

### 기법 6: Ensemble Reranker (Cross-encoder + Dense 결합)

**문제**: Cross-encoder와 Dense가 각자 다른 케이스에서 강점을 가짐. 단독 사용 시 상대방의 약점을 보완 불가.

**해결**: 두 점수를 min-max 정규화 후 가중 합산.

```
score_final = 0.6 × score_cross_encoder + 0.4 × score_dense
```

- Cross-encoder 우세 케이스: 정확한 표기 일치, 짧은 레이블
- Dense 우세 케이스: 문맥 의존적 disambiguation, alias

**결과:**

| 지표 | 값 | Cross-encoder 단독 대비 |
|------|----|------------------------|
| 제출 셀 | 76,974개 (90.7%) | 동일 |
| F1 | **0.378** | **+0.034** |
| Precision | 0.398 | +0.036 |
| Recall | 0.360 | +0.032 |

*Ollama 미사용 방법 중 최고 성능 — 전체 최고는 Ollama Debate (F1=0.489)*

---

### 기법 7: ReAct Agentic CEA

**문제**: 사전 정의된 파이프라인은 검색 실패 시 대안 전략을 자율적으로 선택하지 못함.  
예: "Eat My Dust!" 검색 실패 시 관사를 제거하거나 다른 쿼리를 시도하는 로직이 없음.

**해결**: LLM이 Think→Act→Observe 루프로 검색 전략을 스스로 결정하는 ReAct Agent 적용.

**사용 가능한 도구:**
| 도구 | 설명 |
|------|------|
| `search_entities(query, limit)` | ES BM25 검색 |
| `search_fuzzy(query, limit)` | ES Fuzzy 검색 |
| `get_entity_details(qid)` | Wikidata API로 QID 상세 조회 |
| `submit_answer(qid)` | 최종 QID 제출 |

**실행 예시:**
```
[Think] "Eat My Dust!"를 검색하겠다
[Act]   search_entities("Eat My Dust!")
[Obs]   후보: Q1234567 | Eat My Dust! | 1976년 미국 영화
[Act]   submit_answer("Q1234567")
```

**모델 선택 근거 (10테이블 비교):**

| 모델 | steps | 커버리지 | 정확도 | 소요 |
|------|-------|---------|--------|------|
| llama3.1:8b | 5 | 79.5% | 낮음 (잘못된 QID 다수) | 20분 |
| qwen2.5:14b | 5 | 79.5% | 높음 | 67분 |
| **qwen2.5:14b** | **2** | **79.5%** | **높음** | **36분** |

→ `qwen2.5:14b`, `max_steps=2` 채택: 품질 유지 + 속도 1.85배 향상

**커버리지 100% 달성 방법**: Agent가 NIL 반환 시 BM25 top-1으로 자동 fallback → 구조적으로 미제출 없음

**결과**: 826개 테이블, 84,512개 어노테이션 (99.5% 커버리지)  
공식 F1: **0.332**, Precision: 0.332, Recall: 0.331 (공식 결과 2026-06-12)

---

## 실험 결과 요약

| 기법 | 커버리지 | F1 | Precision | Recall | 비고 |
|------|---------|-----|-----------|--------|------|
| BM25 top-1 | 90.9% | 0.242 | 0.254 | 0.231 | 베이스라인 |
| **LLM Debate** | **61.1%** | **0.489** | **0.645** | **0.394** | **현재 최고** |
| Cross-encoder | 90.4% | 0.344 | 0.362 | 0.328 | — |
| Dense (E5) | 90.7% | 0.344 | 0.362 | 0.328 | — |
| Ensemble | 90.7% | 0.378 | 0.398 | 0.360 | Ollama 미사용 중 최고 |
| ReAct Agent | 99.5% | 0.332 | 0.332 | 0.331 | 커버리지↑ 정확도↓ |
| **1위 ADFr** | — | **0.758** | — | — | **목표** |

---

## 주요 설계 결정 및 교훈

| 결정 | 이유 및 결과 |
|------|-------------|
| 숫자·날짜 컬럼 필터 제거 | 타겟 파일이 이미 대상 셀을 지정 → 필터가 연도 엔티티(1976→Q2002 등)를 잘못 스킵. 제거 후 커버리지 +20% |
| Agent NIL → BM25 fallback | LLM이 NIL 반환해도 커버리지 보호. 구조적 미제출(ES 후보 없음)만 스킵 |
| Fuzzy를 폴백 마지막 단계로 | Precision 보호 — Fuzzy 단독은 노이즈 많음. 폴백 위치에서만 +177개 추가 |
| max_steps=2 채택 | step5 대비 QID 71.4% 동일, 속도 1.85배 향상 → 허용 가능한 품질 손실로 전체 실행 시간 단축 |
| Agent LLM 호출 async + 120초 타임아웃 | 동기 blocking 호출로 이벤트 루프 전체 멈춤 버그 수정. 타임아웃으로 무한 대기 방지 |
