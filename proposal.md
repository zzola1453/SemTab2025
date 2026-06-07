# Proposal: Agentic LLM 기반 CEA 시스템

**작성일**: 2026-06-05  
**과제**: MammoTab SemTab 2025 — Cell Entity Annotation (CEA)  
**목표**: ReAct 패턴 Agentic LLM으로 기존 단일 호출 방식의 한계 극복

---

## 1. 배경 및 문제 인식

### 현재 시스템의 한계

기존 파이프라인은 LLM을 단일 호출(single-turn) 판단자로만 사용한다.

```
BM25 검색 → top-N 후보 전달 → LLM이 QID 하나 선택 (끝)
```

**실험에서 드러난 문제**:
- Ollama Debate 적용 시 커버리지 90.9% → 61.1%로 급감 (LLM 응답 형식 오류)
- 초기 검색이 실패하면 LLM이 개입할 기회 없이 NIL 처리
- 모호한 경우(Brazil = 국가? 영화?) LLM이 추가 정보를 스스로 구할 수 없음

### Agentic이 필요한 이유

CEA의 핵심 난제인 Disambiguation·Alias Resolution은 단일 턴으로 해결이 어렵다.  
**"Brazil"이 국가인지 영화인지는 검색을 더 해봐야 알 수 있는 경우가 많다.**

---

## 2. 제안 방법: ReAct 기반 Agentic CEA

### 2.1 핵심 아이디어

LLM이 Think → Act → Observe → Revise 루프를 자율적으로 수행하여  
셀 하나를 어노테이션하는 **micro-agent**를 구성한다.

```
[셀: "Brazil", col="Films", row="1985, Adventure"]

Think:  "Brazil은 국가(Q155)일 수도, 1985년 Terry Gilliam 영화(Q105512)일 수도 있다.
         row 컨텍스트에 '1985, Adventure'가 있으니 영화 쪽을 먼저 검색해야 한다."
  ↓
Act:    search_entities("Brazil film 1985")
  ↓
Observe: [Q155: 나라 브라질, Q105512: 1985 Terry Gilliam 영화 Brazil, ...]
  ↓
Think:  "Q105512가 유력하다. 설명을 더 확인해보자."
  ↓
Act:    get_entity_details("Q105512")
  ↓
Observe: {label: "Brazil", description: "1985 dystopian film directed by Terry Gilliam"}
  ↓
Think:  "row 컨텍스트와 일치. 확정."
  ↓
Act:    submit_answer("Q105512")   ← 루프 종료
```

### 2.2 제공 도구 (Tools)

| 도구 | 설명 | 기존 구현 활용 |
|------|------|--------------|
| `search_entities(query, limit)` | ES BM25로 후보 검색 | `ElasticsearchRetriever.search()` |
| `search_fuzzy(query)` | 유사 표기 폴백 검색 | `ElasticsearchRetriever.search_fuzzy()` |
| `get_entity_details(qid)` | 엔티티 상세 정보 조회 | Wikidata API 추가 |
| `submit_answer(qid_or_NIL)` | 최종 답변 제출, 루프 종료 | 신규 |

### 2.3 루프 제어

- **최대 반복**: 셀당 5회 (무한 루프 방지)
- **종료 조건**: `submit_answer` 호출 또는 최대 반복 도달 (→ top-1 fallback)
- **Collective Inference 유지**: 확정된 어노테이션은 다음 셀의 시스템 컨텍스트로 주입

---

## 3. 현재 시스템과 비교

| 항목 | 현재 (단일 호출) | 제안 (Agentic) |
|------|----------------|---------------|
| 검색 횟수 | 1회 고정 | 필요 시 추가 검색 |
| 쿼리 전략 | 사전 정의된 fallback 체인 | LLM이 상황 보고 스스로 결정 |
| 실패 처리 | 정해진 순서로 fallback | 에이전트가 전략 변경 |
| 추가 정보 조회 | 불가 | `get_entity_details` 호출 가능 |
| Alias 처리 | query_rewriter 별도 모듈 | LLM이 쿼리 변형을 자율 생성 |

---

## 4. 코드 구조 변경 계획

### 신규 파일

```
src/cea/agent.py          # ReAct 루프 핵심 로직
src/cea/tools.py          # 도구 정의 및 스키마 (OpenAI function calling 형식)
```

### 수정 파일

```
src/cea/pipeline.py       # use_debate → use_agent 플래그 추가
                          # _annotate_cell_async에서 agent 호출 분기
scripts/run_baseline.py   # --agent 플래그 추가
```

### agent.py 핵심 구조

```python
class CeaAgent:
    def __init__(self, retriever, client, model, max_steps=5):
        self.tools = [search_entities, search_fuzzy,
                      get_entity_details, submit_answer]

    def annotate(self, ctx: CellContext) -> str:
        messages = [system_prompt(ctx)]
        for _ in range(self.max_steps):
            response = call_llm_with_tools(self.client, self.model, messages)
            if response.tool == "submit_answer":
                return response.args["qid"]
            result = self._execute_tool(response.tool, response.args)
            messages.append(tool_result(result))
        return fallback_top1(ctx)  # 최대 반복 초과 시
```

---

## 5. LLM 선택

### 로컬 (RTX 4080 Super, 16GB VRAM)

| 모델 | VRAM | Agentic 안정성 | 비고 |
|------|------|--------------|------|
| qwen2.5:14b (현재) | ~9GB | ★★☆ | tool calling 지원, 불안정 |
| llama3.1:8b | ~5GB | ★★☆ | 빠르지만 품질 낮음 |

**결론**: 14B 이하 로컬 모델은 multi-step tool calling에서 형식 오류 빈발 → 권장하지 않음

### 권장: 외부 API

| 옵션 | 모델 | 비용 | Tool Calling |
|------|------|------|-------------|
| **Groq API** | llama-3.3-70b | 무료 티어 | ★★★★ |
| **Anthropic** | claude-haiku-4-5 | 유료 (저렴) | ★★★★★ |

**Groq 무료 API가 현실적 최선**: llama-3.3-70b 수준에서 tool calling 안정적, 초당 수백 토큰

---

## 6. 기대 효과

| CEA 난제 | 현재 | Agentic 후 |
|---------|------|-----------|
| Disambiguation | 단일 검색 결과만 보고 판단 | 추가 검색·상세 조회로 확인 |
| Alias Resolution | query_rewriter 별도 활성화 필요 | LLM이 자율적으로 변형 쿼리 생성 |
| 검색 실패 케이스 | NIL 처리 | 다른 쿼리로 재시도 |
| NIL 탐지 | Verification 모듈 별도 | 에이전트가 루프 안에서 판단 |

---

## 7. 구현 순서

1. `src/cea/tools.py` — 도구 4개 정의 (function calling 스키마)
2. `src/cea/agent.py` — ReAct 루프 구현 (Groq API 우선)
3. `src/cea/pipeline.py` — `--agent` 플래그 추가
4. 소규모 테스트 (10개 테이블) → BM25 / Reranker / Agentic 비교
5. 전체 826개 테이블 실행 → 공식 F1 비교 제출
