import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class Candidate:
    qid: str
    label: str
    description: str
    score: float = 0.0
    source: str = ""


class BaseRetriever(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[Candidate]:
        ...

    def search_sync(self, query: str, limit: int = 10) -> list[Candidate]:
        return asyncio.run(self.search(query, limit))


class WikidataAPIRetriever(BaseRetriever):
    _API_URL = "https://www.wikidata.org/w/api.php"
    _LABELS_URL = "https://www.wikidata.org/w/api.php"
    _last_call: float = 0.0
    _min_interval: float = 0.1  # 10 req/s max

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def search(self, query: str, limit: int = 10) -> list[Candidate]:
        if not query or not query.strip():
            return []

        elapsed = time.monotonic() - WikidataAPIRetriever._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)

        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": "en",
            "limit": limit,
            "format": "json",
            "uselang": "en",
        }

        headers = {"User-Agent": "SemTabCEA/1.0 (seongtaek0408@gmail.com)"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self._API_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                data = await resp.json()

        WikidataAPIRetriever._last_call = time.monotonic()

        results = []
        for item in data.get("search", []):
            results.append(Candidate(
                qid=item.get("id", ""),
                label=item.get("label", ""),
                description=item.get("description", ""),
                score=item.get("score", 0.0),
                source="wikidata_api",
            ))
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def search_multi(self, queries: list[str], limit: int = 10) -> list[list[Candidate]]:
        tasks = [self.search(q, limit) for q in queries]
        return await asyncio.gather(*tasks)


class ElasticsearchRetriever(BaseRetriever):
    """BM25 retrieval against local Wikidata KG index. Available after indexing."""

    def __init__(self, host: str = "http://localhost:9200", index: str = "wikidata_entities"):
        self.host = host
        self.index = index
        self._client = None

    def _get_client(self):
        if self._client is None:
            from elasticsearch import AsyncElasticsearch
            self._client = AsyncElasticsearch(hosts=[self.host])
        return self._client

    async def search(self, query: str, limit: int = 10) -> list[Candidate]:
        client = self._get_client()
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term":         {"label.keyword": {"value": query, "boost": 20}}},
                        {"match_phrase": {"label":         {"query": query, "boost": 10}}},
                        {"match_phrase": {"aliases":       {"query": query, "boost": 8}}},
                        {"multi_match":  {
                            "query": query,
                            "fields": ["label^3", "aliases^2", "description"],
                            "type": "best_fields",
                        }},
                    ]
                }
            },
            "size": limit,
        }
        try:
            resp = await client.search(index=self.index, body=body)
        except Exception:
            return []

        results = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            results.append(Candidate(
                qid=src.get("qid", ""),
                label=src.get("label", ""),
                description=src.get("description", ""),
                score=hit["_score"],
                source="elasticsearch",
            ))
        return results

    async def close(self):
        if self._client:
            await self._client.close()


class HybridRetriever(BaseRetriever):
    """BM25 + dense kNN hybrid search via Elasticsearch.

    Falls back to BM25-only if the index does not contain 'embedding' vectors.
    Dense vectors are generated with sentence-transformers (e5-large-v2 by default).
    """

    _DENSE_DIMS = {"intfloat/e5-large-v2": 1024, "BAAI/bge-large-en-v1.5": 1024}

    def __init__(
        self,
        host: str = "http://localhost:9200",
        index: str = "wikidata_entities",
        model_name: str = "intfloat/e5-large-v2",
        bm25_weight: float = 0.5,
    ):
        self.host = host
        self.index = index
        self.model_name = model_name
        self.bm25_weight = bm25_weight
        self._client = None
        self._encoder = None
        self._has_dense: bool | None = None  # cached after first check

    def _get_client(self):
        if self._client is None:
            from elasticsearch import AsyncElasticsearch
            self._client = AsyncElasticsearch(hosts=[self.host])
        return self._client

    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(self.model_name)
        return self._encoder

    def _encode(self, text: str) -> list[float]:
        prefix = "query: " if "e5" in self.model_name.lower() else ""
        return self._get_encoder().encode(prefix + text, normalize_embeddings=True).tolist()

    async def _check_dense(self) -> bool:
        if self._has_dense is not None:
            return self._has_dense
        try:
            client = self._get_client()
            mapping = await client.indices.get_mapping(index=self.index)
            props = list(mapping.values())[0]["mappings"].get("properties", {})
            self._has_dense = "embedding" in props
        except Exception:
            self._has_dense = False
        return self._has_dense

    async def search(self, query: str, limit: int = 10) -> list[Candidate]:
        client = self._get_client()
        has_dense = await self._check_dense()

        if has_dense:
            vector = await asyncio.to_thread(self._encode, query)
            body = {
                "query": {
                    "bool": {
                        "should": [{
                            "multi_match": {
                                "query": query,
                                "fields": ["label^3", "aliases^2", "description"],
                                "boost": self.bm25_weight,
                            }
                        }]
                    }
                },
                "knn": {
                    "field": "embedding",
                    "query_vector": vector,
                    "k": limit,
                    "num_candidates": limit * 5,
                    "boost": 1.0 - self.bm25_weight,
                },
                "size": limit,
            }
            source_tag = "hybrid"
        else:
            body = {
                "query": {
                    "bool": {
                        "should": [
                            {"term":         {"label.keyword": {"value": query, "boost": 20}}},
                            {"match_phrase": {"label":         {"query": query, "boost": 10}}},
                            {"match_phrase": {"aliases":       {"query": query, "boost": 8}}},
                            {"multi_match":  {
                                "query": query,
                                "fields": ["label^3", "aliases^2", "description"],
                                "type": "best_fields",
                            }},
                        ]
                    }
                },
                "size": limit,
            }
            source_tag = "bm25"

        try:
            resp = await client.search(index=self.index, body=body)
        except Exception:
            return []

        results = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            results.append(Candidate(
                qid=src.get("qid", ""),
                label=src.get("label", ""),
                description=src.get("description", ""),
                score=hit["_score"],
                source=source_tag,
            ))
        return results

    async def close(self):
        if self._client:
            await self._client.close()


def get_retriever(backend: str = "wikidata_api", **kwargs) -> BaseRetriever:
    if backend == "elasticsearch":
        return ElasticsearchRetriever(**kwargs)
    if backend == "hybrid":
        return HybridRetriever(**kwargs)
    return WikidataAPIRetriever()
