"""End-to-end tests: the same code builds working Q&A apps over two unrelated document sets."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rag_generator import KnowledgeBase, list_knowledge_bases
from rag_generator.generator import NOT_FOUND, SYSTEM_PROMPT, Generator
from rag_generator.retriever import BM25


def offline_kb(name):
    return KnowledgeBase(name, dense=False, generator=Generator(use_llm=False))


@pytest.fixture
def hr(samples):
    kb = offline_kb("HR Handbook")
    kb.add_documents([samples / "hr_handbook"])
    return kb


@pytest.fixture
def manual(samples):
    kb = offline_kb("nimbus")
    kb.add_documents([samples / "product_manual"])
    return kb


def test_bm25_prefers_relevant_document():
    bm = BM25(["the cat sat on the mat", "annual leave carry over rules", "filters and fans"])
    s = bm.scores("how many leave days carry over?")
    assert s.index(max(s)) == 1


def test_name_is_slugified(hr):
    assert hr.name == "hr-handbook"
    assert hr.exists


@pytest.mark.parametrize(
    "question, expected, source",
    [
        ("How many days of annual leave do full-time employees get?", "24 days", "leave_policy.md"),
        ("How much is the home office allowance?", "USD 600", "remote_work.txt"),
        ("When is a medical certificate required for sick leave?", "3 consecutive", "leave_policy.md"),
    ],
)
def test_hr_answers_are_grounded(hr, question, expected, source):
    ans = hr.ask(question)
    assert expected in ans.text
    assert ans.sources[0].chunk.source == source
    assert "[1]" in ans.text


@pytest.mark.parametrize(
    "question, expected",
    [
        ("How often should I replace the HEPA filter?", "6 months"),
        ("What does error E1 mean?", "front cover"),
        ("How long is the warranty?", "2-year"),
    ],
)
def test_same_code_works_on_a_different_document_set(manual, question, expected):
    assert expected in manual.ask(question).text


def test_unrelated_question_is_refused(manual):
    ans = manual.ask("Who won the football world cup?")
    assert ans.text == NOT_FOUND
    assert ans.mode == "no-context"


def test_knowledge_bases_are_isolated(hr, manual):
    assert all(h.chunk.source == "nimbus_x2_manual.md" for h in manual.search("annual leave filter"))
    assert all(h.chunk.source != "nimbus_x2_manual.md" for h in hr.search("annual leave filter"))
    assert {m["name"] for m in list_knowledge_bases()} == {"hr-handbook", "nimbus"}


def test_persistence_and_reload(hr):
    reopened = offline_kb("hr-handbook")
    assert len(reopened.chunks) == len(hr.chunks)
    assert "24 days" in reopened.ask("annual leave for full-time employees").text


def test_readding_unchanged_file_is_skipped_and_changed_file_replaced(tmp_path):
    doc = tmp_path / "faq.txt"
    doc.write_text("The cafeteria opens at 9am.")
    kb = offline_kb("faq")
    assert kb.add_documents([doc])["added"] == ["faq.txt"]
    assert kb.add_documents([doc])["skipped"] == ["faq.txt"]

    doc.write_text("The cafeteria opens at 11am.")
    kb.add_documents([doc])
    assert len(kb.chunks) == 1
    assert "11am" in kb.ask("When does the cafeteria open?").text


def test_remove_document_and_delete(hr):
    assert hr.remove_document("remote_work.txt")
    assert all(c.source != "remote_work.txt" for c in hr.chunks)
    assert not hr.remove_document("nope.txt")
    hr.delete()
    assert not hr.exists


def test_ask_on_empty_kb_raises():
    with pytest.raises(ValueError):
        offline_kb("empty").ask("anything")


def test_llm_request_is_grounded_and_cited(manual):
    """With credentials the generator sends retrieved passages to Claude; mock the API call."""
    fake = MagicMock()
    fake.beta.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text="Replace it every 6 months [1].")],
    )
    gen = Generator(model="claude-opus-5-5", use_llm=True)
    gen._client = fake
    manual.generator = gen

    ans = manual.ask("How often should I replace the filter?")

    kwargs = fake.beta.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["system"] == SYSTEM_PROMPT
    user_msg = kwargs["messages"][-1]["content"]
    assert "[1] (source: nimbus_x2_manual.md)" in user_msg and "6 months" in user_msg
    assert ans.text == "Replace it every 6 months [1]." and ans.mode == "llm"
    assert [n for n, _ in ans.cited_sources] == [1]


def test_llm_refusal_is_handled(manual):
    fake = MagicMock()
    fake.beta.messages.create.return_value = SimpleNamespace(stop_reason="refusal", content=[])
    gen = Generator(use_llm=True)
    gen._client = fake
    manual.generator = gen
    assert "declined" in manual.ask("filter replacement").text


def test_llm_not_called_when_nothing_relevant(manual):
    fake = MagicMock()
    gen = Generator(use_llm=True)
    gen._client = fake
    manual.generator = gen
    assert manual.ask("quantum chromodynamics lagrangian").text == NOT_FOUND
    fake.beta.messages.create.assert_not_called()
