# Security

## Threat model and controls

| Risk | Control | Where |
|---|---|---|
| Leaked API keys | Keys are read from environment / `.env` only; `.env` is git-ignored; nothing is hard-coded. | `.gitignore`, `.env.example` |
| Unauthorised API use | Optional `X-API-Key` auth on every endpoint except `/health`, compared in constant time (`hmac.compare_digest`). | `security.check_api_key`, `api.require_key` |
| Path traversal via upload names or knowledge-base names | Upload names are reduced to a base name with a safe character set; KB names are slugified to `[a-z0-9_-]`, so they can't leave `RAG_DATA_DIR`. | `security.safe_filename`, `knowledge_base._slug` |
| Malicious / oversized uploads | Extension allow-list, per-file size cap (`RAG_MAX_UPLOAD_MB`), file-count cap, empty-file rejection. Uploads go to a private temp dir that is always deleted. Files are parsed as data only, never executed. | `security.staged_uploads` |
| Prompt injection inside documents | Retrieved text is passed as numbered *source passages*; the system prompt tells the model that passages are content, not instructions, and to answer only from them. | `generator.SYSTEM_PROMPT` |
| Hallucinated answers | Relevance gate: if nothing lexically or semantically relevant is retrieved the LLM is not called and a fixed "not found" answer is returned. Answers must cite passages, and citations are shown to the user. | `knowledge_base.search`, `generator` |
| Oversized requests | Question length cap, `k` capped at 20, chat history capped at 20 turns (only the last 6 are sent to the model). | `api.AskRequest`, `security.validate_question` |
| Script injection in HTML uploads | `<script>`/`<style>` blocks are stripped before indexing; the UI renders answers as Markdown, never raw HTML. | `loaders.load_file` |
| Container escape / privilege | Docker image runs as an unprivileged user; data on a separate volume. | `Dockerfile` |
| Vulnerable code or dependencies | `ruff` (incl. flake8-bandit rules), `bandit` and `pip-audit` run in CI. | `.github/workflows/ci.yml` |

## Known limitations

- The API has no built-in rate limiting or multi-tenant isolation. Put it behind a gateway / reverse proxy (with TLS) for public deployment.
- Knowledge bases are stored as plain files. Use disk encryption if documents are sensitive.
- Concurrent writes to the *same* knowledge base are not locked; ingest from one process at a time.

## Reporting a vulnerability

Please open a private security advisory on GitHub rather than a public issue.
