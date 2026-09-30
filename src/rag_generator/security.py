"""Input validation shared by the API and web UI: upload limits, filename sanitising,
and constant-time API key checks."""

from __future__ import annotations

import hmac
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .loaders import SUPPORTED_EXTENSIONS

MAX_UPLOAD_MB = float(os.getenv("RAG_MAX_UPLOAD_MB", 25))
MAX_FILES_PER_REQUEST = int(os.getenv("RAG_MAX_FILES", 20))
MAX_QUESTION_CHARS = int(os.getenv("RAG_MAX_QUESTION_CHARS", 2000))


class UploadError(ValueError):
    pass


def safe_filename(name: str) -> str:
    """Strip directories and unusual characters so an upload can't escape its temp dir."""
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" .")
    if not base:
        raise UploadError("Invalid file name")
    return base[:150]


def validate_upload(name: str, size: int) -> str:
    clean = safe_filename(name)
    ext = Path(clean).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UploadError(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise UploadError(f"{clean} is larger than the {MAX_UPLOAD_MB:g} MB limit")
    if size == 0:
        raise UploadError(f"{clean} is empty")
    return clean


def validate_question(question: str) -> str:
    q = (question or "").strip()
    if not q:
        raise ValueError("Question must not be empty")
    if len(q) > MAX_QUESTION_CHARS:
        raise ValueError(f"Question is longer than {MAX_QUESTION_CHARS} characters")
    return q


@contextmanager
def staged_uploads(files: list[tuple[str, bytes]]):
    """Write validated uploads to a private temp dir; yields (paths, display_names) and cleans up."""
    if not files:
        raise UploadError("No files uploaded")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise UploadError(f"At most {MAX_FILES_PER_REQUEST} files per upload")
    with tempfile.TemporaryDirectory(prefix="rag_upload_") as tmp:
        paths, names = [], {}
        for i, (name, data) in enumerate(files):
            clean = validate_upload(name, len(data))
            # prefix with an index so two uploads with the same name can't overwrite each other
            path = Path(tmp) / f"{i}_{clean}"
            path.write_bytes(data)
            paths.append(path)
            names[str(path)] = clean
        yield paths, names


def check_api_key(provided: str | None) -> bool:
    """True when no key is configured (local dev) or the provided key matches."""
    expected = os.getenv("RAG_API_KEY")
    if not expected:
        return True
    return bool(provided) and hmac.compare_digest(provided.encode(), expected.encode())
