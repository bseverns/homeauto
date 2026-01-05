import hashlib
import os
from pathlib import Path
from typing import Iterable

import yaml
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct
from sentence_transformers import SentenceTransformer


CONFIG_PATH = Path(os.getenv("INGEST_CONFIG", "/config/assistant/ingest.yaml"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "homeauto-assistant")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
DEFAULT_ROOT = os.getenv("ASSISTANT_DATA_ROOTS", "")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    return {}


def resolve_roots(config: dict) -> list[Path]:
    roots = [Path(root) for root in config.get("roots", [])]
    if DEFAULT_ROOT:
        roots.extend([Path(root) for root in DEFAULT_ROOT.split(",") if root.strip()])
    return [root.expanduser() for root in roots]


def iter_files(roots: Iterable[Path], extensions: set[str]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions:
                yield path


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(text[start:end])
        start = end - overlap
        if start < 0:
            start = 0
        if start >= length:
            break
    return chunks


def file_id(path: Path, chunk_index: int, mtime: float) -> str:
    digest = hashlib.sha1(f"{path}|{chunk_index}|{mtime}".encode("utf-8")).hexdigest()
    return digest


def main() -> None:
    config = load_config()
    extensions = {ext.lower() for ext in config.get("extensions", [])}
    chunk_size = int(config.get("chunk_size", 1000))
    overlap = int(config.get("chunk_overlap", 150))
    max_bytes = int(config.get("max_bytes", 2_000_000))
    collection_tag = config.get("collection_tag", "")

    roots = resolve_roots(config)
    if not roots:
        raise SystemExit("No roots configured. Check config/assistant/ingest.yaml or ASSISTANT_DATA_ROOTS.")

    client = QdrantClient(url=QDRANT_URL)
    embedder = SentenceTransformer(EMBED_MODEL)

    vector_size = embedder.get_sentence_embedding_dimension()
    if not client.collection_exists(QDRANT_COLLECTION):
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    points = []
    for path in iter_files(roots, extensions):
        if path.stat().st_size > max_bytes:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        chunks = chunk_text(text, chunk_size, overlap)
        for index, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            embedding = embedder.encode(chunk).tolist()
            mtime = path.stat().st_mtime
            point_id = file_id(path, index, mtime)
            payload = {
                "source": str(path),
                "chunk": index,
                "text": chunk,
                "mtime": mtime,
                "collection_tag": collection_tag,
            }
            points.append(PointStruct(id=point_id, vector=embedding, payload=payload))

    if points:
        client.upsert(collection_name=QDRANT_COLLECTION, points=points)


if __name__ == "__main__":
    main()
