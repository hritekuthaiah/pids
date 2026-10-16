"""Site procedures as a retrieval index (AIL-07).

Markdown SOPs are split at ``##`` headings (one self-contained section per chunk),
embedded locally with a small sentence-embedding model (ONNX via fastembed — works
air-gapped once the model is baked into the image), and searched two ways at once:

* dense: pgvector cosine distance — finds sections that *mean* the same thing;
* sparse: PostgreSQL full-text rank — finds exact terms ("spoofing", "crate");

fused by reciprocal rank (RRF, k=60), which needs no score calibration between the two.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pids_server.db import models as m

if TYPE_CHECKING:
    from fastembed import TextEmbedding

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RRF_K = 60


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    doc: str
    title: str
    heading: str
    body: str


def split_sections(doc: str, text: str) -> list[Section]:
    """``# Title`` then ``## Heading`` blocks -> sections (text before the first ## is skipped)."""
    title_match = re.search(r"^# (.+)$", text, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else doc
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    out: list[Section] = []
    for i in range(1, len(parts) - 1, 2):
        heading, body = parts[i].strip(), " ".join(parts[i + 1].split())
        if body:
            out.append(Section(f"{doc}#{len(out) + 1}", doc, title, heading, body))
    return out


def load_sections(folder: Path) -> list[Section]:
    sections: list[Section] = []
    for path in sorted(folder.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        sections.extend(split_sections(path.stem, path.read_text(encoding="utf-8")))
    return sections


@lru_cache(maxsize=1)
def _embedder() -> TextEmbedding:
    from fastembed import TextEmbedding

    return TextEmbedding(EMBED_MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    return [vec.tolist() for vec in _embedder().embed(texts)]


def embed_query(text: str) -> list[float]:
    # bge models are trained with a retrieval instruction on the query side
    vec: list[float] = next(iter(_embedder().query_embed(text))).tolist()
    return vec


async def index(session: AsyncSession, folder: Path) -> int:
    """Replace the procedure index with the documents in ``folder``."""
    sections = load_sections(folder)
    vectors = embed([f"{s.title}. {s.heading}. {s.body}" for s in sections]) if sections else []
    await session.execute(delete(m.ProcedureChunk))
    for s, v in zip(sections, vectors, strict=True):
        session.add(
            m.ProcedureChunk(
                id=s.id, doc=s.doc, title=s.title, heading=s.heading, body=s.body, embedding=v
            )
        )
    return len(sections)


async def search(session: AsyncSession, query: str, k: int = 4) -> list[dict[str, Any]]:
    """Hybrid dense + full-text search, fused by reciprocal rank."""
    vec = embed_query(query)
    dense = (
        await session.scalars(
            select(m.ProcedureChunk.id)
            .order_by(m.ProcedureChunk.embedding.cosine_distance(vec))
            .limit(10)
        )
    ).all()
    tsq = func.websearch_to_tsquery("english", query)
    sparse = (
        await session.scalars(
            select(m.ProcedureChunk.id)
            .where(m.ProcedureChunk.tsv.op("@@")(tsq))
            .order_by(func.ts_rank_cd(m.ProcedureChunk.tsv, tsq).desc())
            .limit(10)
        )
    ).all()
    fused: dict[str, float] = {}
    for ranking in (dense, sparse):
        for rank, cid in enumerate(ranking):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    top = sorted(fused, key=lambda c: fused[c], reverse=True)[:k]
    if not top:
        return []
    rows = {
        r.id: r
        for r in (
            await session.scalars(select(m.ProcedureChunk).where(m.ProcedureChunk.id.in_(top)))
        ).all()
    }
    return [
        {"id": c, "procedure": rows[c].title, "section": rows[c].heading, "text": rows[c].body}
        for c in top
        if c in rows
    ]
