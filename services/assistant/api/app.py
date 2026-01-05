import os
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, MatchValue, FieldCondition
from sentence_transformers import SentenceTransformer


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=6, ge=1, le=20)
    explain: bool = False


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


APP_TITLE = "Homeauto Local Assistant"

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "homeauto-assistant")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
LLM_URL = os.getenv("LLM_URL", "http://llama-server:8080/v1/chat/completions")
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "orin-assistant")
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a local, on-device assistant. Be concise, cite sources by filename, and do not guess.",
)

app = FastAPI(title=APP_TITLE)
client = QdrantClient(url=QDRANT_URL)
embedder = SentenceTransformer(EMBED_MODEL)


def _build_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
    context_blocks = []
    for chunk in chunks:
        payload = chunk.get("payload", {})
        snippet = payload.get("text", "")
        source = payload.get("source", "unknown")
        context_blocks.append(f"Source: {source}\n{snippet}")
    context = "\n\n".join(context_blocks)
    return (
        "You are a local, on-device assistant. Answer using the provided context only.\n"
        "If the answer is not in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "assistant": ASSISTANT_NAME}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    embedding = embedder.encode(request.question).tolist()

    conditions = []
    collection_tag = os.getenv("COLLECTION_TAG")
    if collection_tag:
        conditions.append(
            FieldCondition(key="collection_tag", match=MatchValue(value=collection_tag))
        )
    search_filter = Filter(must=conditions) if conditions else None

    results = client.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=embedding,
        limit=request.top_k,
        query_filter=search_filter,
        with_payload=True,
    )

    chunks = [result.model_dump() for result in results]
    prompt = _build_prompt(request.question, chunks)

    payload = {
        "model": "local",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    with httpx.Client(timeout=120.0) as session:
        response = session.post(LLM_URL, json=payload)
        response.raise_for_status()
        data = response.json()

    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")

    sources = []
    for chunk in chunks:
        payload = chunk.get("payload", {})
        sources.append(
            {
                "source": payload.get("source", "unknown"),
                "chunk": payload.get("chunk", 0),
                "score": chunk.get("score", 0),
                "snippet": payload.get("text", "") if request.explain else "",
            }
        )

    return QueryResponse(answer=answer, sources=sources)
