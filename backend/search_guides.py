"""Local Chroma retrieval, optionally limited to one guide."""

import math
import re
from functools import lru_cache

import chromadb
from ollama import Client
from config import settings

DB_DIR = settings.db_dir
COLLECTION_NAME = settings.collection_name
EMBED_MODEL = settings.embed_model
# Tuned initially against representative questions from these six guides.
# This cosine threshold is a relevance heuristic, not an accuracy probability.
MIN_SIMILARITY = settings.min_similarity
ollama_client = Client(host=settings.ollama_url, timeout=settings.ollama_timeout)


class GuideIndexError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def database():
    return chromadb.PersistentClient(path=str(DB_DIR))


def cosine_similarity(left, right):
    if len(left) != len(right):
        return -1.0
    denominator = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    return float(sum(a * b for a, b in zip(left, right)) / denominator) if denominator else -1.0


def question_source(question):
    from source_pages import catalog
    patterns = {
        "ETL": r"\bvision\s*etl\b", "ST": r"\bvision\s*studio\b",
        "BI": r"\bvision\s*bi\b", "API": r"\b(?:vision\s*)?api\s*manager\b",
        "DQ": r"\b(?:vision\s*)?(?:ai\s*)?data\s*quality\b",
        "TAX": r"\b(?:vision\s*)?tax\s*assurance\b",
    }
    products = [short for short, pattern in patterns.items() if re.search(pattern, question, re.IGNORECASE)]
    if len(products) == 1:
        return next((doc["filename"] for doc in catalog().values() if doc["short"] == products[0]), None)
    return None


def search_guides(question: str, limit: int = 3, source=None):
    try:
        collection = database().get_collection(
            name=COLLECTION_NAME, embedding_function=None,
        )
    except chromadb.errors.NotFoundError as error:
        raise GuideIndexError("The guide index is missing. Run build_chroma.py first.") from error

    explicit_source = question_source(question)
    if source and explicit_source and source != explicit_source:
        return []
    source = source or explicit_source
    where = {"source": source} if source else None
    if collection.count() == 0:
        raise GuideIndexError("The guide index is empty. Run build_chroma.py first.")
    if where and not collection.get(where=where, limit=1, include=[])["ids"]:
        raise GuideIndexError("This guide is not indexed yet. Run prepare_chunks.py and build_chroma.py.")

    embedding = ollama_client.embed(
        model=EMBED_MODEL, input=f"search_query: {question}", truncate=False,
    )
    arguments = {
        "query_embeddings": embedding.embeddings,
        "n_results": min(limit, collection.count()),
        "include": ["documents", "metadatas", "embeddings"],
    }
    if where:
        arguments["where"] = where
    results = collection.query(**arguments)
    return [
        {"text": text, **metadata, "similarity": cosine_similarity(embedding.embeddings[0], vector)}
        for text, metadata, vector in zip(results["documents"][0], results["metadatas"][0], results["embeddings"][0])
        if text and metadata
    ]


if __name__ == "__main__":
    question = input("Ask about a guide: ").strip()
    if not question:
        raise SystemExit("Please enter a question.")
    for number, match in enumerate(search_guides(question), start=1):
        print(f"\n--- Match {number} ---")
        print(f"Source: {match['source']} | PDF page: {match['page']}")
        print(match["text"])
