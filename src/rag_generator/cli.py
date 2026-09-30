"""Command-line interface: `python -m rag_generator <command> ...`"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404 - only used to launch streamlit with a fixed argument list
import sys
from pathlib import Path

from .knowledge_base import KnowledgeBase, list_knowledge_bases


def _print_answer(ans) -> None:
    print(f"\n{ans.text}\n")
    if ans.sources and ans.mode != "no-context":
        print("Sources:")
        for n, h in ans.cited_sources:
            print(f"  [{n}] {h.chunk.citation}")
    print(f"(answer mode: {ans.mode})\n")


def _open(name: str, args) -> KnowledgeBase:
    kb = KnowledgeBase(name, dense=args.dense)
    if not kb.exists:
        sys.exit(f"No knowledge base named '{kb.name}'. Create one with: python -m rag_generator create {name} <docs>")
    return kb


def cmd_create(args) -> None:
    kb = KnowledgeBase(args.name, dense=args.dense)
    if kb.exists and not args.append:
        sys.exit(f"'{kb.name}' already exists. Use `add` to add documents or `delete` first.")
    result = kb.add_documents(args.paths)
    print(f"Knowledge base '{kb.name}' ready ({kb.retriever.mode} retrieval).")
    print(f"  added:   {', '.join(result['added']) or '-'}")
    if result["skipped"]:
        print(f"  skipped: {', '.join(result['skipped'])}")
    print(f"  chunks:  {result['total_chunks']}")
    print(f'\nAsk it something:  python -m rag_generator ask {kb.name} "your question"')


def cmd_add(args) -> None:
    kb = _open(args.name, args)
    result = kb.add_documents(args.paths)
    print(f"added: {', '.join(result['added']) or '-'}; skipped: {', '.join(result['skipped']) or '-'}; "
          f"chunks: {result['total_chunks']}")


def cmd_ask(args) -> None:
    kb = _open(args.name, args)
    _print_answer(kb.ask(args.question, k=args.k))


def cmd_chat(args) -> None:
    kb = _open(args.name, args)
    docs = ", ".join(d["name"] for d in kb.manifest["documents"])
    print(f"Chatting with '{kb.name}' ({docs}). Type 'exit' to quit.\n")
    history: list[dict] = []
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in {"exit", "quit", ":q"}:
            break
        if not q:
            continue
        ans = kb.ask(q, k=args.k, history=history)
        _print_answer(ans)
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": ans.text}]


def cmd_list(args) -> None:
    kbs = list_knowledge_bases()
    if not kbs:
        print("No knowledge bases yet.")
    for m in kbs:
        docs = m["documents"]
        print(f"{m['name']}: {len(docs)} document(s), {sum(d['chunks'] for d in docs)} chunks")
        for d in docs:
            print(f"    - {d['name']}")


def cmd_delete(args) -> None:
    kb = _open(args.name, args)
    kb.delete()
    print(f"Deleted '{kb.name}'.")


def cmd_ui(args) -> None:
    ui = Path(__file__).with_name("ui.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ui)], check=False)  # nosec B603 - no user input


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("rag_generator.api:app", host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="rag_generator", description="Generate a RAG app over any documents.")
    dense = p.add_mutually_exclusive_group()
    dense.add_argument("--dense", dest="dense", action="store_true", default=None,
                       help="require dense embeddings (needs fastembed)")
    dense.add_argument("--no-dense", dest="dense", action="store_false", help="BM25 only")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("create", help="create a knowledge base from files/folders")
    s.add_argument("name")
    s.add_argument("paths", nargs="+")
    s.add_argument("--append", action="store_true", help="add to it if it already exists")
    s.set_defaults(func=cmd_create)

    s = sub.add_parser("add", help="add documents to an existing knowledge base")
    s.add_argument("name")
    s.add_argument("paths", nargs="+")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("ask", help="ask a single question")
    s.add_argument("name")
    s.add_argument("question")
    s.add_argument("-k", type=int, default=5, help="passages to retrieve")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("chat", help="interactive multi-turn Q&A")
    s.add_argument("name")
    s.add_argument("-k", type=int, default=5)
    s.set_defaults(func=cmd_chat)

    sub.add_parser("list", help="list knowledge bases").set_defaults(func=cmd_list)

    s = sub.add_parser("delete", help="delete a knowledge base")
    s.add_argument("name")
    s.set_defaults(func=cmd_delete)

    sub.add_parser("ui", help="launch the Streamlit web UI").set_defaults(func=cmd_ui)

    s = sub.add_parser("serve", help="run the REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
