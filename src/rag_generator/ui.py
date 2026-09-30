"""Streamlit web UI. Run with:  python -m rag_generator ui"""

from __future__ import annotations

import streamlit as st

from rag_generator.knowledge_base import KnowledgeBase, list_knowledge_bases
from rag_generator.security import MAX_UPLOAD_MB, UploadError, staged_uploads, validate_question

st.set_page_config(page_title="RAG Generator", page_icon="📚", layout="wide")

# ---------------- sidebar: build / pick a knowledge base ----------------
with st.sidebar:
    st.header("1. Knowledge base")
    existing = [m["name"] for m in list_knowledge_bases()]
    choice = st.selectbox("Open existing", ["➕ New knowledge base", *existing])
    if choice.startswith("➕"):
        kb_name = st.text_input("Name", placeholder="e.g. hr-policies")
    else:
        kb_name = choice

    st.header("2. Documents")
    uploads = st.file_uploader(
        f"Upload files (max {MAX_UPLOAD_MB:g} MB each)",
        type=["pdf", "txt", "md", "docx", "html", "htm", "csv", "json"],
        accept_multiple_files=True,
    )
    if st.button("Build / update index", type="primary", disabled=not (kb_name and uploads)):
        try:
            kb = KnowledgeBase(kb_name)
            with st.spinner("Reading, chunking and indexing…"), staged_uploads(
                [(f.name, f.getvalue()) for f in uploads]
            ) as (paths, names):
                result = kb.add_documents(paths, display_names=names)
            st.success(f"Indexed {len(result['added'])} file(s) → {result['total_chunks']} chunks")
            if result["skipped"]:
                st.info("Skipped (unchanged or empty): " + ", ".join(result["skipped"]))
            st.session_state.pop(f"history:{kb.name}", None)
        except (UploadError, ValueError, RuntimeError) as e:
            st.error(str(e))

# ---------------- main: chat ----------------
st.title("📚 RAG Generator")
if not kb_name:
    st.write("Create or pick a knowledge base in the sidebar, upload documents, then ask questions here.")
    st.stop()

try:
    kb = KnowledgeBase(kb_name)
except ValueError as e:
    st.error(str(e))
    st.stop()

if not kb.exists:
    st.info(f"'{kb.name}' is new. Upload documents in the sidebar to build it.")
    st.stop()

docs = kb.manifest["documents"]
answer_mode = f"Claude ({kb.generator.model})" if kb.generator.use_llm else "extractive (no API key set)"
st.caption(
    f"**{kb.name}** · {len(docs)} document(s) · {len(kb.chunks)} chunks · "
    f"retrieval: {kb.retriever.mode} · answers: {answer_mode}"
)
with st.expander("Documents in this knowledge base"):
    for d in docs:
        st.write(f"- {d['name']} ({d['chunks']} chunks)")

key = f"history:{kb.name}"
history = st.session_state.setdefault(key, [])
for turn in history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        for cite in turn.get("sources", []):
            st.caption(cite)

if question := st.chat_input("Ask a question about these documents"):
    try:
        question = validate_question(question)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"), st.spinner("Searching and answering…"):
        prior = [{"role": t["role"], "content": t["content"]} for t in history]
        ans = kb.ask(question, history=prior)
        st.markdown(ans.text)
        cites = []
        if ans.mode != "no-context":
            for n, h in ans.cited_sources:
                cites.append(f"[{n}] {h.chunk.citation}")
                with st.expander(f"[{n}] {h.chunk.citation}"):
                    st.text(h.chunk.text)
    history += [
        {"role": "user", "content": question},
        {"role": "assistant", "content": ans.text, "sources": cites},
    ]
