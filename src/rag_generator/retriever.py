"""Hybrid retrieval: BM25 (always on) + dense embeddings (when fastembed is installed),
merged with Reciprocal Rank Fusion."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .chunker import Chunk

_STOPWORDS = set(
    "a an and are as at be but by for from has have how i if in into is it its me my of on or our "
    "so that the their them then there these they this to was we were what when where which who why "
    "will with you your do does did can could should would about".split()
)


def _stem(t: str) -> str:
    """Very light plural folding so 'smells'/'smell' and 'filters'/'filter' match."""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avgdl = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, dl in zip(self.tfs, self.lens, strict=False):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    norm = self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out


class DenseEncoder:
    """Thin wrapper around fastembed. Returns None from `load()` if it isn't installed."""

    MODEL = "BAAI/bge-small-en-v1.5"

    def __init__(self, model):
        self._model = model

    @classmethod
    def load(cls) -> DenseEncoder | None:
        try:
            from fastembed import TextEmbedding
        except ImportError:
            return None
        return cls(TextEmbedding(cls.MODEL))

    def embed(self, texts: list[str]):
        import numpy as np

        vecs = np.array(list(self._model.embed(texts)), dtype="float32")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.clip(norms, 1e-12, None)


@dataclass
class Hit:
    chunk: Chunk
    score: float  # fused RRF score
    lexical: float  # raw BM25 score, used to detect "nothing relevant"
    dense: float | None = None  # cosine similarity when dense retrieval is on


def _ranks(scores: list[float]) -> dict[int, int]:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return {idx: rank for rank, idx in enumerate(order)}


class Retriever:
    def __init__(self, chunks: list[Chunk], embeddings=None, encoder: DenseEncoder | None = None):
        self.chunks = chunks
        self.bm25 = BM25([c.text for c in chunks])
        self.embeddings = embeddings
        self.encoder = encoder

    @property
    def mode(self) -> str:
        return "hybrid (BM25 + dense)" if self._dense_ready else "BM25"

    @property
    def _dense_ready(self) -> bool:
        return self.embeddings is not None and self.encoder is not None and len(self.embeddings) == len(self.chunks)

    def search(self, query: str, k: int = 5, rrf_k: int = 60) -> list[Hit]:
        if not self.chunks:
            return []
        lex = self.bm25.scores(query)
        fused = {i: 1 / (rrf_k + r) for i, r in _ranks(lex).items() if lex[i] > 0}

        dense_scores = None
        if self._dense_ready:
            q = self.encoder.embed([query])[0]
            dense_scores = (self.embeddings @ q).tolist()
            for i, r in _ranks(dense_scores).items():
                fused[i] = fused.get(i, 0.0) + 1 / (rrf_k + r)

        top = sorted(fused, key=fused.get, reverse=True)[:k]
        return [
            Hit(self.chunks[i], fused[i], lex[i], dense_scores[i] if dense_scores else None)
            for i in top
        ]
