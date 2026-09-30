"""A knowledge base is one generated RAG app: a named, persisted index over a document set.

Layout on disk (under RAG_DATA_DIR, default ./rag_data):
    <name>/manifest.json   settings + list of ingested documents
    <name>/chunks.json     chunk text and provenance
    <name>/embeddings.npy  dense vectors (only when fastembed is installed)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .chunker import Chunk, chunk_pages
from .generator import Answer, Generator
from .loaders import discover_files, load_file
from .retriever import DenseEncoder, Hit, Retriever

MIN_DENSE_SIMILARITY = 0.55  # below this a passage with no keyword overlap is treated as unrelated


def data_root() -> Path:
    return Path(os.getenv("RAG_DATA_DIR", "rag_data"))


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("Knowledge base name must contain letters or numbers")
    return slug


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def list_knowledge_bases() -> list[dict]:
    root = data_root()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        m = d / "manifest.json"
        if m.exists():
            out.append(json.loads(m.read_text(encoding="utf-8")))
    return out


class KnowledgeBase:
    def __init__(self, name: str, *, dense: bool | None = None, generator: Generator | None = None):
        self.name = _slug(name)
        self.dir = data_root() / self.name
        self.generator = generator or Generator()
        self._dense_pref = dense
        self._encoder: DenseEncoder | None = None
        self._retriever: Retriever | None = None
        self.manifest = self._read_json("manifest.json") or {
            "name": self.name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "documents": [],
            "chunk_size": int(os.getenv("RAG_CHUNK_SIZE", 1000)),
            "chunk_overlap": int(os.getenv("RAG_CHUNK_OVERLAP", 150)),
            "embedding_model": None,
        }
        self.chunks = [Chunk(**c) for c in (self._read_json("chunks.json") or [])]

    # ---------- persistence ----------
    @property
    def exists(self) -> bool:
        return (self.dir / "manifest.json").exists()

    def _read_json(self, name: str):
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _save(self, embeddings) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "chunks.json").write_text(
            json.dumps([c.to_dict() for c in self.chunks], ensure_ascii=False), encoding="utf-8"
        )
        emb_path = self.dir / "embeddings.npy"
        if embeddings is not None:
            import numpy as np

            np.save(emb_path, embeddings)
        elif emb_path.exists():
            emb_path.unlink()
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")

    def delete(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    # ---------- ingestion ----------
    def _encoder_or_none(self) -> DenseEncoder | None:
        if self._dense_pref is False:
            return None
        if self._encoder is None:
            self._encoder = DenseEncoder.load()
            if self._encoder is None and self._dense_pref:
                raise RuntimeError("Dense retrieval requested but fastembed is not installed (pip install fastembed)")
        return self._encoder

    def add_documents(self, paths: list[str | Path], display_names: dict[str, str] | None = None) -> dict:
        """Ingest files/folders. Re-adding a file with the same name replaces its old chunks."""
        files = discover_files(paths)
        if not files:
            raise ValueError("No supported documents found")
        display_names = display_names or {}

        added, skipped = [], []
        new_chunks: list[Chunk] = []
        docs = {d["name"]: d for d in self.manifest["documents"]}
        for f in files:
            name = display_names.get(str(f), f.name)
            digest = _sha(f)
            if docs.get(name, {}).get("sha") == digest:
                skipped.append(name)
                continue
            pages = load_file(f, display_name=name)
            chunks = chunk_pages(pages, self.manifest["chunk_size"], self.manifest["chunk_overlap"])
            if not chunks:
                skipped.append(f"{name} (no extractable text)")
                continue
            self.chunks = [c for c in self.chunks if c.source != name]
            new_chunks.extend(chunks)
            docs[name] = {"name": name, "sha": digest, "pages": len(pages), "chunks": len(chunks)}
            added.append(name)

        if added:
            self.chunks.extend(new_chunks)
            for i, c in enumerate(self.chunks):
                c.id = f"c{i}"
            self.manifest["documents"] = sorted(docs.values(), key=lambda d: d["name"])
            self._reindex()
        return {"added": added, "skipped": skipped, "total_chunks": len(self.chunks)}

    def remove_document(self, name: str) -> bool:
        before = len(self.chunks)
        self.chunks = [c for c in self.chunks if c.source != name]
        self.manifest["documents"] = [d for d in self.manifest["documents"] if d["name"] != name]
        if len(self.chunks) == before:
            return False
        for i, c in enumerate(self.chunks):
            c.id = f"c{i}"
        self._reindex()
        return True

    def _reindex(self) -> None:
        encoder = self._encoder_or_none()
        embeddings = encoder.embed([c.text for c in self.chunks]) if encoder and self.chunks else None
        self.manifest["embedding_model"] = DenseEncoder.MODEL if embeddings is not None else None
        self.manifest["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._save(embeddings)
        self._retriever = Retriever(self.chunks, embeddings, encoder)

    # ---------- querying ----------
    @property
    def retriever(self) -> Retriever:
        if self._retriever is None:
            embeddings, encoder = None, None
            emb_path = self.dir / "embeddings.npy"
            if self.manifest.get("embedding_model") and emb_path.exists():
                encoder = self._encoder_or_none()
                if encoder is not None:
                    import numpy as np

                    embeddings = np.load(emb_path)
            self._retriever = Retriever(self.chunks, embeddings, encoder)
        return self._retriever

    def search(self, question: str, k: int = 5) -> list[Hit]:
        hits = self.retriever.search(question, k=k)
        return [h for h in hits if h.lexical > 0 or (h.dense is not None and h.dense >= MIN_DENSE_SIMILARITY)]

    def ask(self, question: str, k: int = 5, history: list[dict] | None = None) -> Answer:
        if not self.chunks:
            raise ValueError(f"Knowledge base '{self.name}' has no documents yet")
        return self.generator.answer(question, self.search(question, k), history)
