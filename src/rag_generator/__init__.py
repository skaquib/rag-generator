"""RAG Generator: turn any document set into a question-answering app at runtime."""

try:  # pick up settings from a local .env (CLI, API and UI all import this package)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from .generator import Answer, Generator
from .knowledge_base import KnowledgeBase, list_knowledge_bases

__all__ = ["Answer", "Generator", "KnowledgeBase", "list_knowledge_bases"]
__version__ = "0.1.0"
