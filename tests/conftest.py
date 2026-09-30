from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[1] / "sample_docs"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own data dir and runs offline (no Claude credentials, BM25 only)."""
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path / "rag_data"))
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "RAG_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def samples() -> Path:
    return SAMPLES
