"""REST API. Run with:  uvicorn rag_generator.api:app  (or `python -m rag_generator serve`)"""

from __future__ import annotations

from fastapi import Depends, FastAPI, File, HTTPException, Security, UploadFile
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from . import __version__
from .knowledge_base import KnowledgeBase, list_knowledge_bases
from .security import MAX_UPLOAD_MB, UploadError, check_api_key, staged_uploads, validate_question

app = FastAPI(title="RAG Generator", version=__version__,
              description="Upload documents to create a knowledge base, then ask grounded questions.")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_key(key: str | None = Security(_api_key_header)) -> None:
    if not check_api_key(key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(5, ge=1, le=20)
    history: list[dict] = Field(default_factory=list, max_length=20)


class Source(BaseModel):
    ref: int
    citation: str
    text: str


class AskResponse(BaseModel):
    answer: str
    mode: str
    sources: list[Source]


def _existing(name: str) -> KnowledgeBase:
    try:
        kb = KnowledgeBase(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not kb.exists:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{kb.name}' not found")
    return kb


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/kb", dependencies=[Depends(require_key)])
def list_kbs() -> list[dict]:
    return list_knowledge_bases()


@app.post("/kb/{name}/documents", dependencies=[Depends(require_key)], status_code=201)
async def upload(name: str, files: list[UploadFile] = File(...)) -> dict:
    """Create the knowledge base if needed and ingest the uploaded files."""
    limit = int(MAX_UPLOAD_MB * 1024 * 1024) + 1
    payload = [(f.filename or "upload", await f.read(limit)) for f in files]
    try:
        kb = KnowledgeBase(name)
        with staged_uploads(payload) as (paths, names):
            result = kb.add_documents(paths, display_names=names)
    except (UploadError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"knowledge_base": kb.name, "retrieval": kb.retriever.mode, **result}


@app.post("/kb/{name}/ask", response_model=AskResponse, dependencies=[Depends(require_key)])
def ask(name: str, req: AskRequest) -> AskResponse:
    kb = _existing(name)
    try:
        question = validate_question(req.question)
        history = [{"role": h["role"], "content": str(h["content"])} for h in req.history
                   if h.get("role") in {"user", "assistant"} and "content" in h]
        ans = kb.ask(question, k=req.k, history=history)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return AskResponse(
        answer=ans.text,
        mode=ans.mode,
        sources=[Source(ref=n, citation=h.chunk.citation, text=h.chunk.text) for n, h in ans.cited_sources]
        if ans.mode != "no-context" else [],
    )


@app.delete("/kb/{name}/documents/{doc}", dependencies=[Depends(require_key)])
def remove_document(name: str, doc: str) -> dict:
    kb = _existing(name)
    if not kb.remove_document(doc):
        raise HTTPException(status_code=404, detail=f"Document '{doc}' not found")
    return {"removed": doc}


@app.delete("/kb/{name}", dependencies=[Depends(require_key)])
def delete_kb(name: str) -> dict:
    _existing(name).delete()
    return {"deleted": name}
