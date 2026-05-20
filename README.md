# SemTab 2025 — MammoTab CEA 시스템

SemTab 2025 챌린지의 **MammoTab 트랙 Cell Entity Annotation(CEA)** 태스크를 위한 시스템.
CSV 테이블의 각 셀을 Wikidata 엔티티 URI에 매핑하는 것이 목표.

## 목표

| 모델 | F1 |
|------|----|
| ADFr (1위) | 0.758 |
| RAGDify (2위) | 0.603 |
| ditlab (3위) | 0.549 |
| **우리 목표** | **≥ 0.758** |

---

## 태스크 정의

**입력**: CSV 테이블 + 어노테이션 대상 셀 목록 `(table_id, row_id, col_id)`

**출력**: `table_id, row_id, col_id, entity_id`

```
LYQZQ0T5,1,1,Q3576864
LYQZQ0T5,2,1,Q229390
```

NIL(KG에 없는 엔티티)은 해당 셀 생략.

---

## 데이터

### MammoTab 데이터셋
- **테이블**: 826개 CSV 파일 (`.data/mammotab_semtab_2025/tables/`)
- **타겟 셀**: 84,907개 (`target_mammotab_2025.csv`)
- **도메인**: 영화, 인물, 국가, 조약 등 다양

### Wikidata KG
- **버전**: v.20240720 (`latest-all.nt.bz2`, 163GB)
- **인덱싱**: Elasticsearch `wikidata_entities` 인덱스
  - 영어 레이블 보유 엔티티: **78,647,123개**
  - 필드: `qid`, `label`, `description`, `aliases`

---

## 시스템 파이프라인

```
CSV 테이블
    ↓
1. 전처리 (preprocessing.py)
   - 셀 값 정규화, HTML 제거
   - 숫자/날짜 컬럼 자동 감지 및 스킵
    ↓
2. 후보 검색 (retrieval.py)
   - BM25 (Elasticsearch) — 기본
   - Dense Hybrid (BM25 + 임베딩) — 개발 중
   - 후보 없을 시 row 컨텍스트 포함 재검색
    ↓
3. 후보 선택 (debate.py / reranker.py)
   - [API 키 없음] Cross-encoder 로컬 재순위 (reranker.py)
   - [API 키 있음] Claude Haiku Debate (debate.py)
    ↓
4. 검증 (verification.py) — API 키 있을 때
   - 셀·컬럼·테이블 수준 일관성 확인
   - NIL 명시 판단
    ↓
table_id, row_id, col_id, entity_id
```

---

## 실험 결과

| 실험 | 어노테이션 수 | 커버리지 | 공식 F1 |
|------|-------------|---------|---------|
| ES BM25 top-1 (826테이블) | 77,140 | 90.9% | 대기 중 |

결과 파일: `output/experiments/` / 실험 로그: `output/experiments.csv`

---

## 프로젝트 구조

```
SemTab/
├── src/cea/
│   ├── preprocessing.py   # 셀 정규화, 컬럼 타입 감지
│   ├── retrieval.py       # ES BM25 / Wikidata API / Hybrid 검색
│   ├── reranker.py        # 로컬 cross-encoder 재순위 (API 키 불필요)
│   ├── debate.py          # LLM 후보 선택 (API 키 필요)
│   ├── verification.py    # LLM 검증 (API 키 필요)
│   ├── query_rewriter.py  # LLM 쿼리 재작성 (API 키 필요)
│   └── pipeline.py        # end-to-end 파이프라인
├── scripts/
│   ├── run_baseline.py    # 실험 실행 CLI
│   ├── index_wikidata.py  # Wikidata KG → Elasticsearch 인덱싱
│   └── validate_submission.py
├── output/
│   ├── experiments/       # 실험별 결과 CSV
│   └── experiments.csv    # 실험 목록 및 F1 기록
└── .data/                 # 데이터셋 (git 제외)
```

---

## 실행 방법

### 환경 설정

```bash
pip install -r requirements.txt
cp .env.example .env  # API 키 설정 (없어도 동작)
docker compose up -d  # Elasticsearch 시작
```

### 실험 실행

```bash
# BM25 top-1 (API 키 불필요)
python3 scripts/run_baseline.py --backend elasticsearch --tables 826 --no-debate

# Cross-encoder 재순위 (API 키 불필요)
python3 scripts/run_baseline.py --backend elasticsearch --tables 826 --no-debate --rerank

# LLM Debate 포함 (Anthropic API 키 필요)
python3 scripts/run_baseline.py --backend elasticsearch --tables 826
```

### Wikidata 인덱싱 (최초 1회)

```bash
python3 scripts/index_wikidata.py --dump /path/to/latest-all.nt.bz2
```

---

## 기술 스택

| 구성 요소 | 사용 기술 |
|-----------|-----------|
| 검색 엔진 | Elasticsearch 8.13 (BM25) |
| 로컬 재순위 | sentence-transformers cross-encoder |
| LLM (선택) | Claude Haiku (Anthropic API) |
| 비동기 처리 | asyncio + aiohttp |
| 인프라 | Docker + Docker Compose |

---

## 참고

- [SemTab 2025 공식 사이트](https://sem-tab-challenge.github.io/2025/)
- [MammoTab 문서](https://unimib-datai.github.io/mammotab-docs/)
- [RAGDify 논문 (2위)](https://sem-tab-challenge.github.io/2025/papers/paper_1.pdf)
- [Iterative Refinement 논문](https://sem-tab-challenge.github.io/2025/papers/paper_2.pdf)
