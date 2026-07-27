from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Union, Tuple
from pydantic import BaseModel, Field
from functools import partial
import json
import numpy as np

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import numpy as np
from typing import Optional, List, Dict, Any
from pydantic.dataclasses import dataclass
from pydantic import ConfigDict, Field


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Citation:
    bibtex_id: str
    title: str
    journal: str
    year: str
    query: str
    source: str = "unknown"
    search_rank: int = 0
    tldr: Optional[str] = None
    abstract: Optional[str] = None
    influence: int = 0
    embedding: Optional[Any] = None  # changed from np.ndarray
    scope: Optional[str] = None

    def pretty_repr(self) -> str:
        ref = f"{self.title}. *{self.journal}* ({self.year})"
        ref += f" Source: {self.source}"
        if self.tldr:
            ref += f" TLDR: {self.tldr}"
        if self.abstract:
            ref += f" Abstract: {self.abstract[:100]}..."
        ref += f" Query: '{self.query}'"
        return ref

    def get_similarity(self, target_embedding: np.ndarray) -> float:
        if self.embedding is None or target_embedding is None:
            return -1
        return float(np.dot(self.embedding, target_embedding) / (
            np.linalg.norm(self.embedding) * np.linalg.norm(target_embedding) + 1e-8))


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class CitationCollection:
    citations: List[Citation]

    def __iter__(self):
        return iter(self.citations)

    def deduplicate(self) -> 'CitationCollection':
        unique = {}
        for c in self.citations:
            if c.bibtex_id not in unique:
                unique[c.bibtex_id] = c
            else:
                unique[c.bibtex_id].query += f"; {c.query}"
                unique[c.bibtex_id].search_rank = min(unique[c.bibtex_id].search_rank, c.search_rank)
        return CitationCollection(list(unique.values()))

    def filter_by_influence(self, min_influence: int) -> 'CitationCollection':
        return CitationCollection([c for c in self.citations if c.influence >= min_influence])

    def sort_by_similarity(self, target_embedding: np.ndarray) -> 'CitationCollection':
        return CitationCollection(
            sorted(self.citations, key=lambda c: c.get_similarity(target_embedding), reverse=True)
        )

    def sort_by_rank(self) -> 'CitationCollection':
        return CitationCollection(sorted(self.citations, key=lambda c: c.search_rank))

    def truncate(self, total: int) -> 'CitationCollection':
        return CitationCollection(self.citations[:total])

    def pretty_print(self) -> str:
        return '\n\n'.join([c.pretty_repr() for c in self.citations])
    
    @classmethod
    def merge(cls, *collections: "CitationCollection") -> "CitationCollection":
        all_citations = []
        for c in collections:
            if isinstance(c, CitationCollection):
                all_citations.extend(c.citations)
            else:
                raise TypeError(f"Expected CitationCollection, got {type(c)}")
        return cls(all_citations)


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class MultiQueryCitationManager:
    scope_to_queries: Dict[str, Dict[str, CitationCollection]] = Field(default_factory=dict)

    def merge_scope(self, scope: str) -> CitationCollection:
        all_citations = []
        for query, coll in self.scope_to_queries.get(scope, {}).items():
            all_citations.extend(coll.citations)
        return CitationCollection(all_citations).deduplicate()

    def merge_all(self) -> CitationCollection:
        all_citations = []
        for scope in self.scope_to_queries:
            all_citations.extend(self.merge_scope(scope).citations)
        return CitationCollection(all_citations).deduplicate()

    def get_scope_queries(self) -> Dict[str, List[str]]:
        return {scope: list(queries.keys()) for scope, queries in self.scope_to_queries.items()}

    def get_sorted_filtered_citations(self, scope: Optional[str] = None, total: int = 10,
                                      sort_by_similarity: bool = False,
                                      embedding_target: Optional[np.ndarray] = None,
                                      min_influence: int = 0) -> CitationCollection:
        if scope:
            citations = self.merge_scope(scope)
        else:
            citations = self.merge_all()

        if min_influence:
            citations = citations.filter_by_influence(min_influence)

        if sort_by_similarity and embedding_target is not None:
            citations = citations.sort_by_similarity(embedding_target)
        else:
            citations = citations.sort_by_rank()

        return citations.truncate(total)

    def add_query_results(self, scope: str, query: str, citations: List[Citation]):
        if scope not in self.scope_to_queries:
            self.scope_to_queries[scope] = {}
        self.scope_to_queries[scope][query] = CitationCollection(citations)


def group_citations_by_scope(citations: List[Citation]) -> Dict[str, List[Citation]]:
    grouped = {}
    for c in citations:
        if c.scope:
            grouped.setdefault(c.scope, []).append(c)
    return grouped