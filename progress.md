# Progress Tracker — SemTab CEA 시스템

마지막 업데이트: 2026-06-11

---

## 🔵 Phase 1 — 기초 이해 & 환경 구축 (1~4주차)

### 1주차 — 챌린지 태스크 분석
- ✅ SemTab 2025 MammoTab 트랙 공식 문서 정독, CEA 태스크 정의 파악
- ✅ 리더보드 상위 팀 확인 (ADFr F1=0.758 / RAGDify F1=0.603 / ditlab F1=0.549) — ADFr 논문 미공개 확인
- ✅ 공개된 논문 2편 (RAGDify, Iterative Refinement) 확보 및 접근법 비교 정리
- ✅ MammoTab 데이터셋 826개 테이블 샘플 다운로드 및 구조 파악

### 2주차 — 선행 연구 심화 분석
- ✅ RAGDify 논문 심화 분석: 4단계 파이프라인(전처리→후보검색→Debate→Verification) 구조 및 Elasticsearch 기반 검색 전략 정리
- ✅ Iterative Refinement 논문 심화 분석: CTA-CEA 반복 구조, 전치 테이블 전략, 비지도 일관성 스코어(Consistency/Entropy) 개념 정리
- ✅ Collective Inference 개념 정리 및 우리 시스템 적용 방안 검토
- ✅ Wikidata KG v.20240720 데이터 포맷 및 규모 파악 (엔티티 수, 필드 구조)

### 3주차 — 개발 환경 구축
- ✅ Docker + Elasticsearch 환경 구축 및 동작 확인
  - `docker-compose.yml` 작성 완료 (ES 8.13.4 + Kibana), WSL2 통합 활성화 완료
- ✅ Wikidata KG 인덱싱 설계 (레이블·설명·alias 필드 구성)
  - `scripts/index_wikidata.py` 구현 완료 — SQLite 중간 저장, 체크포인트, ES 재시도 포함
- ✅ 인덱싱 파이프라인 구현 및 동작 검증

### 4주차 — KG 전체 인덱싱 & Exact match 구현
- ✅ Wikidata KG v.20240720 전체 인덱싱 완료 (2026-05-17)
  - latest-all.nt.bz2 (163GB) 파싱, Phase 1 ~21시간 + Phase 2 86분
  - ES `wikidata_entities` 인덱스: **78,647,123개** 엔티티 (label + description + aliases)
  - 중간 bz2 멀티스트림 오류 해결 (bzcat subprocess 방식으로 전환)
- ✅ Exact match 검색 모듈 구현 완료 (`src/cea/retrieval.py`)
- ✅ 전체 826개 테이블 베이스라인 실행 완료 (ES BM25 top-1, no-debate)
  - 77,140개 어노테이션 제출 / 90.9% 커버리지 (`output/baseline_no_debate_full.csv`)
  - asyncio 이벤트 루프 캐싱 버그 발견 및 수정 (단일 루프로 전체 처리)
  - 제출 파일 형식 검증 완료 (valid rows: 77,140 / Format OK)
  - ✅ Google Form 제출 완료 (2026-05-18)
  - ✅ 공식 F1: **0.242**, P: 0.254, R: 0.231 (2026-06-12)
- ✅ Ollama Debate 결과 Google Form 제출 완료 (2026-05-26)
  - `output/experiments/ollama_debate_826t_full.csv`, 51,894개 어노테이션, 61.1% 제출률
  - ✅ 공식 F1: **0.489**, P: 0.645, R: 0.394 (2026-06-12, **전체 최고**)

---

## 🟡 Phase 2 — 파이프라인 구현 (5~9주차)

> **전략 변경 (2026-05-17)**: LLM API 키 없는 방향으로 전환.
> Debate/Verification/QueryRewriting은 코드 완성 상태로 보존하되, 당장 실험은 로컬 모델 우선.

### 5주차 — 검색 고도화
- ✅ Fuzzy match(≥75%) 폴백 검색 구현 (`retrieval.py` — ES fuzziness AUTO + match 75%)
- ✅ LLM 쿼리 재작성 모듈 구현 (`src/cea/query_rewriter.py`) — API 키 없이 비활성화
- ✅ **Cross-encoder 재순위** 구현 (`src/cea/reranker.py`) — API 키 불필요, 로컬 실행
  - 모델: `cross-encoder/ms-marco-MiniLM-L-6-v2`
  - 실행: `--rerank` 플래그
- ✅ BM25 vs Reranker 전체 826테이블 실행 완료 (2026-06-01)
  - `output/experiments/es_rerank_826t.csv`, 76,797개 어노테이션, 90.4% 커버리지, 소요 19분
  - ✅ Google Form 제출 완료 → **F1: 0.344, P: 0.362, R: 0.328** (공식 결과 2026-06-06)

### 6주차 — 후보 선택 & 검증
- ✅ LLM Debate 프롬프트 구현 (`src/cea/debate.py`) — API 키 시 활성화
- ✅ LLM Verification 프롬프트 구현 (`src/cea/verification.py`) — API 키 시 활성화
- ✅ Collective Inference iterative 구조 구현 (`pipeline.py`)
- ✅ 실험 추적 시스템 구현 (`output/experiments.csv` + 메타데이터 JSON)
- ✅ 전체 826개 테이블 Reranker 실행 완료 (2026-06-01)

### 7주차 — Dense Retrieval 하이브리드 검색
- ✅ Bi-encoder Dense Reranker 구현 (`src/cea/reranker.py` — `BiEncoderReranker`)
  - 모델: `intfloat/e5-large-v2` (이미 캐시됨)
  - BM25 top-10 후보 → E5 dense 점수 계산 → BM25(30%) + Dense(70%) 혼합
  - 실행: `--dense-rerank` 플래그
- ✅ Ensemble Reranker 구현 (`EnsembleReranker`)
  - Cross-encoder + Bi-encoder 정규화 앙상블 (cross_weight=0.6)
  - 실행: `--rerank --dense-rerank` 플래그
- ✅ 전체 826테이블 Dense 실행 완료 (2026-06-01)
  - `output/experiments/es_dense_826t.csv`, 76,974개 어노테이션, 90.7%, 92분
  - ✅ Google Form 제출 완료 → **F1: 0.344, P: 0.362, R: 0.328** (공식 결과 2026-06-06)
- ✅ 전체 826테이블 Ensemble 실행 완료 (2026-06-01)
  - `output/experiments/es_ensemble_826t.csv`, 76,974개 어노테이션, 90.7%, 104분
  - ✅ Google Form 제출 완료 → **F1: 0.378, P: 0.398, R: 0.360** (공식 결과 2026-06-06)
- 비교: Cross-encoder vs Dense 51.3% 다른 예측 → 앙상블 효과 기대

### 8주차 — Agentic LLM 전략 전환 & 실험
- ✅ ReAct-style Agentic CEA 구현 완료 (`src/cea/agent.py`, `src/cea/tools.py`)
  - 도구: `search_entities`, `search_fuzzy`, `get_entity_details`, `submit_answer`
  - pipeline.py `--agent` 플래그 통합, run_baseline.py `--agent-model`, `--agent-max-steps` 추가
- ✅ Agent 10테이블 소규모 실험 완료 (2026-06-06~07)

  | 실험 | 모델 | steps | 제출 | 커버리지 | 소요 | 비고 |
  |------|------|-------|------|---------|------|------|
  | elasticsearch_agent_10t | llama3.1:8b | 5 | 615 | 72.0% | 25분 | 형식 오류 다수 |
  | agent_llama31_v2_10t | llama3.1:8b | 5 | 679 | 79.5% | 20분 | Q42→Eat My Dust! 오판 |
  | agent_qwen25_14b_10t | qwen2.5:14b | 5 | 679 | 79.5% | 67분 | 품질 향상 확인 |
  | agent_qwen25_14b_step2_10t | qwen2.5:14b | 2 | 679 | 79.5% | 36분 | 속도↑ 품질 71.4% 동일 |
  | agent_qwen25_step2_nofilter_10t | qwen2.5:14b | 2 | **854** | **100%** | 47분 | 숫자/날짜 필터 제거 후 |
  | agent_qwen25_step2_fixed_10t | qwen2.5:14b | 2 | **854** | **100%** | 47분 | P-prefix QID 검증 추가 |

- ✅ 핵심 발견 — 커버리지 79.5% 원인 분석:
  - `is_numeric_column` / `is_date_column` 필터가 타겟 연도 셀(1976, 1981 등)을 잘못 스킵
  - 타겟 파일이 어노테이션 대상을 이미 지정하므로 필터 불필요 → **제거** (`pipeline.py`)
  - P-prefix property ID(P1907 등) 제출 버그 발견 → `^Q\d+$` 정규식 검증 추가
  - 수정 후 커버리지 **100%** 달성, 비정상 QID 0개
- ✅ **826t qwen step2 전체 실행 완료 (2026-06-11 05:17)**
  - `output/experiments/agent_qwen25_step2_fixed_826t.csv` — 826/826 테이블, **84,512개 어노테이션**, 99.5% 커버리지
  - 총 소요 시간: 약 40시간 (2026-06-07 시작 → 2026-06-11 완료)
  - 누락 395셀(19개 테이블) → NIL 처리(제출 생략)
  - 제출 파일: `output/submission_agent_qwen25_826t.zip` (492 KB)
  - ✅ **Google Form 제출 완료 (2026-06-11)** — 공식 F1: **0.332**, P: 0.332, R: 0.331 (2026-06-12)

### 9주차 — 중간 성능 평가
- ✅ 전체 826개 테이블 1차 추론 완료 (BM25 top-1)
- ✅ Google Form 제출 완료 (2026-05-18) — 공식 F1: **0.242**, P: 0.254, R: 0.231 (2026-06-12)
- ✅ 공식 F1 수신 (2026-06-06): Rerank=0.344 / Dense=0.344 / Ensemble=0.378
- ✅ 전체 최종 결과: **Debate F1=0.489**(최고) / Ensemble=0.378 / Agent=0.332 — 목표(0.758) 대비 0.269 격차
- ✅ F1 기반 오류 분석 → Agentic LLM 전략으로 전환 (`proposal.md`)

---

## 2026-05-17 작업 내역

**오늘 완료한 작업**

- Wikidata KG v.20240720 전체 인덱싱 완료
  - bz2 멀티스트림 오류 발생 → bzcat subprocess 방식으로 해결
  - SQLite 중간 저장 + 라인/QID 체크포인트 + ES 재시도 로직 추가
  - Phase 1 (NT→SQLite): ~21시간, 78,647,123 엔티티 파싱
  - Phase 2 (SQLite→ES): 86분, 전체 인덱싱 완료
- `scripts/index_wikidata.py` 전면 재작성 (재시도·체크포인트·알림 강화)
- asyncio 이벤트 루프 캐싱 버그 발견 및 수정
  - ES 클라이언트가 첫 번째 테이블 처리 후 폐기된 루프에 바인딩 → 2번째 테이블부터 silently 실패
  - `run_on_target_file`을 단일 `asyncio.run()` 내에서 전체 테이블 처리하도록 수정
- 전체 826개 테이블 베이스라인 실행 (ES BM25 top-1, no-debate)
  - 총 84,907개 타겟 셀 → 77,140개 어노테이션 제출 (90.9% 커버리지)
  - 제출 파일: `output/baseline_no_debate_full.csv` (형식 검증 완료)

**다음 단계**

1. `output/experiments/es_bm25_826t_full.csv` → Google Form 제출 → 공식 F1 확인
2. F1 확인 후 Reranker 전체 826테이블 실행 → 비교
3. Dense Hybrid 검색 구현 (로컬 임베딩, API 키 불필요)
4. Collective Inference 실험

---

## 2026-05-14 작업 내역

**오늘 완료한 작업 (3주차 집중)**

- 프로젝트 구조 생성: `src/cea/`, `scripts/`, `tests/`
- `.gitignore` 생성 (KG dump, ES 데이터, 모델 가중치 등 제외)
- `docker-compose.yml` 작성 (ES 8.13.4 + Kibana, ES 메모리 2~4GB 설정)
- `requirements.txt` 작성 (anthropic, elasticsearch, aiohttp, tqdm, tenacity 등)
- `.env.example` 작성 (API key, 경로, 파이프라인 설정 템플릿)
- **파이프라인 전체 구현**:
  - `src/cea/preprocessing.py` — 셀 정규화, 테이블 로딩, 날짜·숫자 컬럼 자동 감지
  - `src/cea/retrieval.py` — Wikidata API / ES 추상화 레이어 (`BaseRetriever`)
  - `src/cea/debate.py` — Claude Haiku 기반 후보 선택 (top-5 candidates)
  - `src/cea/verification.py` — Claude Haiku 기반 어노테이션 검증 (NIL 판단 포함)
  - `src/cea/pipeline.py` — 비동기 end-to-end 파이프라인 (`CeaPipeline`)
- `scripts/explore_data.py` — 데이터셋 통계 분석
- `scripts/index_wikidata.py` — KG 인덱싱 스크립트 (KG 도착 즉시 실행 가능)
- `scripts/run_baseline.py` — CLI 실행 도구 (테이블 수, 백엔드 선택 가능)
- `tests/test_preprocessing.py` — 전처리 단위 테스트 7개 (전부 통과)
- **데이터 탐색 결과**:
  - 826개 테이블에 84,907개 타겟 셀, 테이블당 평균 102.8개
  - 타겟 셀 94.7%가 텍스트(엔티티) 컬럼 — 날짜/숫자 필터링 유효
  - col0(28.5%), col1(27.6%)에 집중 — 영화·인물·국가·조약 등 다양한 도메인
- **Wikidata API 기반 미니 baseline 실행**:
  - 3개 테이블, 304개 타겟 셀 처리
  - 247개 어노테이션 제출 (제출률 81.2%)
  - 샘플 품질 검증 4/4 정확 (Cameroon=Q1009, Eat My Dust!=Q3576864 등)
  - 출력 형식 정상: `filename,row_id,col_id,entity_id`

**다음 단계**

1. Docker Desktop WSL2 통합 활성화 → ES 컨테이너 시작
2. KG 다운로드 완료 후 `python3 scripts/index_wikidata.py --dump <경로>` 실행
3. ES 인덱싱 완료 후 `--backend elasticsearch`로 전환해 성능 측정
