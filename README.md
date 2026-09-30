# RAG Generator

Turn **any set of documents into a question-answering app at runtime**: upload files, get a named knowledge base, and ask questions that are answered **only from those documents, with citations**. There's no code to change between document sets. Each set is its own knowledge base.

```
python -m rag_generator create hr-policies ./my_hr_docs/
python -m rag_generator ask hr-policies "How many leave days carry over?"

Up to 5 unused annual leave days may be carried over into the next calendar year [1].
Sources:
  [1] leave_policy.md
```

Three interfaces share one core: a **CLI**, a **Streamlit web UI** (upload and chat), and a **REST API** (FastAPI).

---

## How the brief is met

| Requirement | How |
|---|---|
| Accepts documents at runtime | Upload in the web UI, `POST /kb/{name}/documents`, or `create`/`add` in the CLI. PDF, DOCX, TXT, MD, HTML, CSV and JSON are supported. |
| Creates a RAG application over them | Each upload builds a persisted **knowledge base**: load → chunk → index (BM25, plus dense embeddings when installed). It's ready to query immediately and survives restarts. |
| Grounded answers | Retrieved passages are numbered and sent to Claude with a strict "answer only from these passages, cite `[n]`" prompt. A relevance gate returns "not found" *without calling the LLM* when nothing relevant is retrieved. Sources are shown with every answer. |
| Works with different document sets without code changes | Knowledge bases are data, not code. The tests build two unrelated apps (an HR handbook and a product manual) with the same code and check that they stay isolated. |

## Architecture

```
            ┌──────────── ingestion (per knowledge base) ────────────┐
 files ──►  loaders.py ──► chunker.py ──► retriever.py ──► rag_data/<kb>/
 (pdf,docx, (text + page   (paragraph-    (BM25 index +     manifest.json
  md,html…)  provenance)    packed,        optional dense    chunks.json
                            overlapping)   embeddings)       embeddings.npy
            └────────────────────────────────────────────────────────┘

            ┌──────────────────── query ─────────────────────────────┐
 question ► hybrid search ─► relevance gate ─► generator.py ─► answer + [n] citations
            (BM25 ⊕ dense      (nothing relevant?  (Claude, or
             via Reciprocal     → "not found",      extractive
             Rank Fusion)       no LLM call)        fallback offline)
            └────────────────────────────────────────────────────────┘
```

```
rag-generator/
├── src/rag_generator/
│   ├── loaders.py         # file → pages (PDF page numbers kept for citations)
│   ├── chunker.py         # pages → overlapping chunks with provenance
│   ├── retriever.py       # BM25 + optional fastembed dense retrieval, RRF fusion
│   ├── generator.py       # grounded prompt, Claude call, extractive fallback
│   ├── knowledge_base.py  # create / add / remove / persist / ask
│   ├── security.py        # upload validation, filename sanitising, API-key check
│   ├── api.py             # FastAPI REST service
│   ├── ui.py              # Streamlit web UI
│   └── cli.py             # command-line interface
├── tests/                 # 32 tests: ingestion, retrieval, grounding, API, security
├── sample_docs/           # two unrelated document sets for the demo
├── transcripts/           # Claude Code session transcript
├── .github/workflows/ci.yml   # lint, tests (3.10 and 3.12), bandit, pip-audit
├── Dockerfile             # non-root image, API on :8000
├── SECURITY.md            # threat model and controls
└── pyproject.toml
```

### Design choices

- **Hybrid retrieval.** BM25 is pure Python with no heavy dependencies, and it's strong on exact terms such as error codes, figures and names. Adding `fastembed` (`bge-small-en-v1.5`, ONNX, CPU) adds semantic matching. For example, "my purifier smells weird" finds "Strange smell: … replace the filter". The two rankings are merged with Reciprocal Rank Fusion, so no score calibration is needed.
- **Claude for generation** (`claude-opus-5-5` by default, `effort=low` for fast Q&A, configurable). Server-side refusal fallback is enabled. Recent chat turns are passed along so follow-up questions work.
- **Runs without an API key.** Without credentials it falls back to extractive answers: the best-matching sentences, cited. The whole pipeline and test suite run offline.
- **Incremental ingestion.** Files are content-hashed. Re-uploading an unchanged file is skipped, and a changed file replaces its old chunks.
- **No vector database.** A knowledge base is a small folder of JSON plus a NumPy array. That's simple to inspect, back up and ship. Swapping in pgvector, Qdrant or Pinecone would only touch `retriever.py`.

## Setup

Requires Python 3.10+.

```bash
git clone https://github.com/skaquib/rag-generator.git
cd rag-generator
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"            # add ,dense for semantic retrieval: ".[dev,dense]"
cp .env.example .env               # then put your ANTHROPIC_API_KEY in .env
```

Without `ANTHROPIC_API_KEY` everything still works, but answers are extractive instead of generated.

## Usage

### Web UI

```bash
python -m rag_generator ui          # opens http://localhost:8501
```

Name a knowledge base, upload files, click **Build / update index**, then chat. Each answer has expandable source passages.

### CLI

```bash
python -m rag_generator create hr sample_docs/hr_handbook          # files or folders
python -m rag_generator create nimbus sample_docs/product_manual   # a different set, same code
python -m rag_generator ask nimbus "What does error E2 mean?"
python -m rag_generator chat hr                                    # multi-turn
python -m rag_generator add hr new_policy.pdf
python -m rag_generator list
python -m rag_generator delete hr
# --dense / --no-dense (before the command) forces or disables embeddings
```

### REST API

```bash
python -m rag_generator serve       # http://127.0.0.1:8000/docs for interactive docs
```

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness (always public) |
| GET | `/kb` | list knowledge bases |
| POST | `/kb/{name}/documents` | upload files (multipart `files`), creating the KB if needed |
| POST | `/kb/{name}/ask` | `{"question": "...", "k": 5, "history": []}` → answer, mode, sources |
| DELETE | `/kb/{name}/documents/{doc}` | remove one document |
| DELETE | `/kb/{name}` | delete the knowledge base |

```bash
curl -F "files=@sample_docs/product_manual/nimbus_x2_manual.md" http://127.0.0.1:8000/kb/nimbus/documents
curl -H "Content-Type: application/json" -d '{"question":"How long is the warranty?"}' http://127.0.0.1:8000/kb/nimbus/ask
```

If `RAG_API_KEY` is set, send it as an `X-API-Key` header.

### Docker

```bash
docker build -t rag-generator .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -v rag_data:/data rag-generator            # API
docker run -p 8501:8501 -e ANTHROPIC_API_KEY=... -v rag_data:/data rag-generator rag-generator ui   # UI
```

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)):

| Variable | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | enables generated answers |
| `RAG_MODEL` / `RAG_EFFORT` | `claude-opus-5-5` / `low` | generation model and effort |
| `RAG_DATA_DIR` | `rag_data` | where knowledge bases are stored |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `1000` / `150` | characters |
| `RAG_API_KEY` | – | require `X-API-Key` on the REST API |
| `RAG_MAX_UPLOAD_MB` / `RAG_MAX_FILES` | `25` / `20` | upload limits |

## Testing and quality

```bash
pytest -q                 # 32 tests, run fully offline (the Claude call is mocked)
ruff check src tests      # lint, including security rules
bandit -q -r src          # static security analysis
pip-audit -r requirements.txt
```

CI runs all four on every push. The tests cover chunking, every loader, BM25 ranking, grounded answers on two different document sets, refusal on unrelated questions, knowledge-base isolation, persistence and reload, re-ingestion, the Claude request shape and refusal handling, the REST API end to end, and the upload and auth security controls.

## Security

See [SECURITY.md](SECURITY.md) for the threat model. In short: no secrets in code, optional API-key auth with constant-time comparison, sanitised filenames and KB names (no path traversal), upload type, size and count limits, prompt-injection-aware prompting, a non-root container, and bandit plus pip-audit in CI.

## Limitations and next steps

- Scanned (image-only) PDFs need OCR, which isn't included.
- No rate limiting or multi-user auth. Deploy behind a gateway for public use.
- Retrieval quality could be improved with a cross-encoder reranker and an evaluation set (recall@k, faithfulness).
- Large corpora (100k+ chunks) should move to a vector database.

## AI usage

Built with **Claude Code** (Claude Opus 5.5). The full transcript is in [`transcripts/`](transcripts/).
