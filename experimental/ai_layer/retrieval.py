"""Local keyword/TF-IDF retrieval over explicitly configured safe text sources.

Input: the allowlisted documents read through ArtifactResolver, split into heading-scoped chunks.
Output: up to top_k scored passages, each with provenance including section and chunk id.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .artifacts import ArtifactResolver, TextSource

_TOKEN = re.compile(r"[a-zA-Z0-9]+(?:[._'-][a-zA-Z0-9]+)*")
_HEADING = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Z0-9 /&()_-]{5,})$")


@dataclass(frozen=True)
class RetrievalHit:
    """One retrieved passage with its cosine score and provenance."""
    text: str
    score: float
    provenance: dict

    def to_dict(self) -> dict:
        """JSON-ready copy."""
        return {"text": self.text, "score": self.score, "provenance": dict(self.provenance)}


@dataclass(frozen=True)
class _Document:
    text: str
    tokens: tuple[str, ...]
    provenance: dict


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN.findall(text))


def _split_source(source: TextSource, chunk_chars: int = 1200) -> list[_Document]:
    lines = source.text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    heading = "Document"
    content: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _HEADING.match(stripped) and content:
            sections.append((heading, content))
            content = []
        if _HEADING.match(stripped):
            heading = stripped.lstrip("# ").strip()
        else:
            content.append(line)
    if content:
        sections.append((heading, content))

    documents: list[_Document] = []
    chunk_id = 0
    for section, section_lines in sections:
        paragraph = ""
        for line in section_lines:
            candidate = f"{paragraph}\n{line}" if paragraph else line
            if len(candidate) > chunk_chars and paragraph:
                text = f"{section}\n{paragraph}".strip()
                documents.append(_Document(
                    text, _tokens(text),
                    {**source.provenance.to_dict(), "section": section, "chunk_id": chunk_id},
                ))
                chunk_id += 1
                paragraph = line
            else:
                paragraph = candidate
            if not line.strip():
                if paragraph.strip():
                    text = f"{section}\n{paragraph}".strip()
                    documents.append(_Document(
                        text, _tokens(text),
                        {**source.provenance.to_dict(), "section": section, "chunk_id": chunk_id},
                    ))
                    chunk_id += 1
                paragraph = ""
        if paragraph.strip():
            text = f"{section}\n{paragraph}".strip()
            documents.append(_Document(
                text, _tokens(text),
                {**source.provenance.to_dict(), "section": section, "chunk_id": chunk_id},
            ))
            chunk_id += 1
    return [document for document in documents if document.tokens]


class KeywordIndex:
    """Small deterministic TF-IDF index with no external embedding dependency."""

    def __init__(self, resolver: ArtifactResolver):
        sources = resolver.read_configured_text_sources()
        documents: list[_Document] = []
        for source in sources:
            documents.extend(_split_source(source))
        self.documents = tuple(documents)
        self.document_frequency: Counter[str] = Counter()
        for document in self.documents:
            self.document_frequency.update(set(document.tokens))

    @classmethod
    def from_resolver(cls, resolver: ArtifactResolver) -> "KeywordIndex":
        """Build the index from every configured text source."""
        return cls(resolver)

    def search(self, query: str, top_k: int = 5) -> list[RetrievalHit]:
        """Rank chunks by TF-IDF cosine similarity to the query; ties break on file and chunk."""
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("query must contain 1 to 500 characters")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise ValueError("top_k must be an integer from 1 to 20")
        terms = _tokens(query)
        if not terms or not self.documents:
            return []
        query_counts = Counter(terms)
        document_count = len(self.documents)
        # Smoothed IDF: a query term absent from every chunk still gets a finite weight.
        idf = {
            term: math.log((1 + document_count) / (1 + self.document_frequency.get(term, 0))) + 1
            for term in query_counts
        }
        query_weights = {term: (1 + math.log(count)) * idf[term] for term, count in query_counts.items()}
        query_norm = math.sqrt(sum(weight * weight for weight in query_weights.values())) or 1.0
        hits: list[RetrievalHit] = []
        for document in self.documents:
            counts = Counter(document.tokens)
            weights = {term: (1 + math.log(count)) * idf[term]
                       for term, count in counts.items() if term in idf}
            numerator = sum(query_weights[term] * weights.get(term, 0.0) for term in query_weights)
            document_norm = math.sqrt(sum(weight * weight for weight in weights.values())) or 1.0
            score = numerator / (query_norm * document_norm)
            if score > 0:
                hits.append(RetrievalHit(document.text, score, document.provenance))
        hits.sort(key=lambda hit: (-hit.score, hit.provenance["source_file"], hit.provenance["chunk_id"]))
        return hits[:top_k]