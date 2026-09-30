import json

import pytest

from rag_generator.chunker import chunk_pages
from rag_generator.loaders import Page, discover_files, load_file


def test_chunks_respect_size_and_keep_provenance():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
    chunks = chunk_pages([Page(text, "doc.txt", 3)], size=500, overlap=80)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 + 80 + 2 for c in chunks)
    assert all(c.source == "doc.txt" and c.page == 3 for c in chunks)
    assert chunks[0].citation == "doc.txt, p.3"
    assert [c.id for c in chunks] == [f"c{i}" for i in range(len(chunks))]


def test_consecutive_chunks_overlap():
    text = "\n\n".join(f"Sentence number {i} has some unique content here." for i in range(60))
    a, b = chunk_pages([Page(text, "d")], size=300, overlap=100)[:2]
    assert b.text.split("\n\n")[0] in a.text  # b starts with the tail of a


def test_very_long_paragraph_is_split():
    chunks = chunk_pages([Page("x" * 5000, "d")], size=1000, overlap=0)
    assert len(chunks) == 5


def test_empty_pages_are_skipped():
    assert chunk_pages([Page("   \n ", "d")]) == []


def test_loaders_for_text_formats(tmp_path):
    (tmp_path / "a.html").write_text("<html><script>evil()</script><p>Hello &amp; welcome</p></html>")
    (tmp_path / "b.csv").write_text("name,price\nWidget,10\n")
    (tmp_path / "c.json").write_text(json.dumps({"k": "value"}))

    assert "Hello & welcome" in load_file(tmp_path / "a.html")[0].text
    assert "evil" not in load_file(tmp_path / "a.html")[0].text
    assert "name: Widget; price: 10" in load_file(tmp_path / "b.csv")[0].text
    assert '"k": "value"' in load_file(tmp_path / "c.json")[0].text


def test_docx_loader(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("The office opens at 8am.")
    d.save(tmp_path / "x.docx")
    assert "opens at 8am" in load_file(tmp_path / "x.docx")[0].text


def test_discover_files_walks_folders_and_rejects_unknown(tmp_path, samples):
    found = discover_files([samples])
    assert {f.name for f in found} == {"leave_policy.md", "remote_work.txt", "nimbus_x2_manual.md"}

    bad = tmp_path / "malware.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(ValueError):
        discover_files([bad])
    with pytest.raises(FileNotFoundError):
        discover_files([tmp_path / "missing.pdf"])
