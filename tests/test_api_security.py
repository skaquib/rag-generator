import pytest
from fastapi.testclient import TestClient

from rag_generator import api
from rag_generator.knowledge_base import KnowledgeBase
from rag_generator.security import UploadError, check_api_key, safe_filename, staged_uploads, validate_upload


@pytest.fixture
def client():
    return TestClient(api.app)


def test_safe_filename_blocks_path_traversal():
    assert safe_filename("../../etc/passwd.txt") == "passwd.txt"
    assert safe_filename("..\\..\\windows\\evil.pdf") == "evil.pdf"
    assert safe_filename("rep<o>rt?.md") == "rep_o_rt_.md"
    with pytest.raises(UploadError):
        safe_filename("../..")


def test_validate_upload_limits():
    with pytest.raises(UploadError):
        validate_upload("x.exe", 10)
    with pytest.raises(UploadError):
        validate_upload("x.pdf", 0)
    with pytest.raises(UploadError):
        validate_upload("x.pdf", 10**10)
    assert validate_upload("ok.PDF", 100) == "ok.PDF"


def test_staged_uploads_cleans_up():
    with staged_uploads([("a.txt", b"hello"), ("a.txt", b"world")]) as (paths, names):
        assert len({p for p in paths}) == 2  # same name doesn't overwrite
        assert set(names.values()) == {"a.txt"}
        tmp = paths[0].parent
    assert not tmp.exists()


def test_kb_name_cannot_escape_data_dir(tmp_path):
    kb = KnowledgeBase("../../outside")
    assert kb.dir.parent.resolve() == (tmp_path / "rag_data").resolve()


def test_api_key_check(monkeypatch):
    assert check_api_key(None)  # no key configured -> open (local dev)
    monkeypatch.setenv("RAG_API_KEY", "s3cret")
    assert not check_api_key(None)
    assert not check_api_key("wrong")
    assert check_api_key("s3cret")


def test_api_end_to_end(client, samples):
    files = [("files", (p.name, p.read_bytes(), "text/plain")) for p in (samples / "product_manual").iterdir()]
    r = client.post("/kb/nimbus/documents", files=files)
    assert r.status_code == 201, r.text
    assert r.json()["added"] == ["nimbus_x2_manual.md"]

    r = client.post("/kb/nimbus/ask", json={"question": "What does error E2 mean?"})
    assert r.status_code == 200
    body = r.json()
    assert "fan motor" in body["answer"]
    assert body["sources"][0]["citation"] == "nimbus_x2_manual.md"

    assert client.get("/kb").json()[0]["name"] == "nimbus"
    assert client.delete("/kb/nimbus").status_code == 200
    assert client.post("/kb/nimbus/ask", json={"question": "x"}).status_code == 404


def test_api_rejects_bad_input(client):
    r = client.post("/kb/demo/documents", files=[("files", ("evil.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 400
    r = client.post("/kb/demo/ask", json={"question": ""})
    assert r.status_code in (404, 422)
    r = client.post("/kb/!!!/ask", json={"question": "hi"})
    assert r.status_code == 400


def test_api_requires_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("RAG_API_KEY", "s3cret")
    assert client.get("/kb").status_code == 401
    assert client.get("/kb", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays public
