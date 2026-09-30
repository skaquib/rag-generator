"""Split pages into overlapping chunks sized for retrieval."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .loaders import Page


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    page: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def citation(self) -> str:
        return f"{self.source}, p.{self.page}" if self.page else self.source


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_long(unit: str, size: int) -> list[str]:
    """Break a paragraph longer than `size` on sentence boundaries, then hard-wrap."""
    sentences = re.split(r"(?<=[.!?])\s+", unit)
    out, buf = [], ""
    for s in sentences:
        while len(s) > size:
            out.append(s[:size])
            s = s[size:]
        if len(buf) + len(s) + 1 > size and buf:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        out.append(buf)
    return out


def chunk_pages(pages: list[Page], size: int = 1000, overlap: int = 150) -> list[Chunk]:
    """Greedy paragraph packing with a character-level tail overlap between chunks."""
    chunks: list[Chunk] = []
    for page in pages:
        text = _normalise(page.text)
        if not text:
            continue
        units: list[str] = []
        for para in text.split("\n\n"):
            units.extend(_split_long(para, size) if len(para) > size else [para])

        buf = ""
        for unit in units:
            if buf and len(buf) + len(unit) + 2 > size:
                chunks.append(Chunk("", buf, page.source, page.page))
                tail = buf[-overlap:] if overlap else ""
                # start the overlap on a word boundary
                tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
                buf = f"{tail}\n\n{unit}" if tail else unit
            else:
                buf = f"{buf}\n\n{unit}" if buf else unit
        if buf:
            chunks.append(Chunk("", buf, page.source, page.page))

    for i, c in enumerate(chunks):
        c.id = f"c{i}"
    return chunks
