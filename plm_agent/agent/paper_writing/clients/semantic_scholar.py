import time
import numpy as np
import requests
import re
import uuid
from uuid import uuid4
from typing import List, Dict, Optional, Tuple, Iterator
from dataclasses import dataclass

from ..schema.citation import Citation

PAPER_SEARCH_URL = 'https://api.semanticscholar.org/graph/v1/paper/search'
EMBEDDING_URL = 'https://model-apis.semanticscholar.org/specter/v1/invoke'


def remove_word(string, word):
    pattern = re.compile(pattern=r'\b{}\b\s*'.format(re.escape(word)), flags=re.IGNORECASE)
    return re.sub(pattern, '', string)


def get_bibtex_id_from_bibtex(bibtex: str) -> str:
    return bibtex.split('{', 1)[1].split(',\n', 1)[0] if '{' in bibtex and ',\n' in bibtex else "None"


@dataclass
class SemanticCitation:
    data: dict
    search_rank: int = 0
    query: str = ""

    @property
    def bibtex(self) -> str:
        bibtex = self.data.get('citationStyles', {}).get('bibtex', '')
        bibtex = bibtex.encode('ascii', 'ignore').decode('utf-8')
        bibtex_id = get_bibtex_id_from_bibtex(bibtex)
        bibtex_id = re.sub(r'[{}(),\\\"-#~^:\'`\u02b9_]', '-', bibtex_id)
        bibtex = bibtex.split('{', 1)[0] + '{' + bibtex_id + ',\n' + bibtex.split(',\n', 1)[1] if ',\n' in bibtex else bibtex
        return bibtex

    @property
    def bibtex_id(self) -> str:
        return get_bibtex_id_from_bibtex(self.bibtex)

    @property
    def title(self) -> Optional[str]:
        return self.data.get('title')

    @property
    def abstract(self) -> Optional[str]:
        return self.data.get('abstract')

    @property
    def journal(self) -> Optional[str]:
        return self.data.get('journal', {}).get('name')

    @property
    def year(self) -> Optional[str]:
        return self.data.get('year')

    @property
    def influence(self) -> int:
        return self.data.get('influentialCitationCount', 0)

    @property
    def embedding(self) -> Optional[np.ndarray]:
        return self.data.get('embedding')
    
    @property
    def tldr(self) -> Optional[str]:
        tldr_data = self.data.get('tldr')
        if isinstance(tldr_data, dict):
            return tldr_data.get('text')
        return None

class SemanticScholarClient:
    def __init__(self, api_key: Optional[str] = None, top_k: int = 5, auto_embed: bool = True):
        self.api_key = api_key
        self.top_k = top_k
        self.auto_embed = auto_embed
        self.embedding_client = SemanticScholarEmbeddingClient()

    def lazy_search(self, query: str) -> Iterator[dict]:
        headers = {'x-api-key': self.api_key} if self.api_key else {}
        words_to_remove = (
            'the', 'of', 'in', 'and', 'or', 'a', 'an', 'to', 'for', 'on', 'at', 'by', 'with', 'from', 'as', 'into',
            'through', 'effect')

        while True:
            params = {
                "query": query,
                "limit": min(self.top_k * 2, 100),
                "fields": "title,url,abstract,tldr,journal,year,citationStyles,embedding,influentialCitationCount",
            }
            for attempt in range(5):
                print(f"Attempt {attempt + 1} for query: {query}")
                response = requests.get(PAPER_SEARCH_URL, headers=headers, params=params)
                if response.status_code not in (504, 429):
                    break
                time.sleep(3 ** attempt)
            else:
                raise Exception("Semantic Scholar request failed after retries.")

            if response.status_code != 200:
                raise Exception(f"Semantic Scholar API Error: {response.status_code} {response.reason}")

            papers = response.json().get("data", [])
            if papers:
                for paper in papers[:self.top_k]:
                    bib_id = get_bibtex_id_from_bibtex(paper.get('citationStyles', {}).get('bibtex', ''))
                    if bib_id == 'None':
                        continue
                    
                    if paper.get("embedding") is None and self.auto_embed:
                        try:
                            paper["embedding"] = self.embedding_client.embed({
                                "paper_id": paper.get("paperId", ""),
                                "title": paper.get("title", ""),
                                "abstract": paper.get("abstract", "")}).tolist()  # 注意：转换为 list 以保持 JSON 兼容
                        except Exception as e:
                            print(f"Failed to embed paper {paper.get('title', '')}: {e}")
                            paper["embedding"] = None
                            
                        yield {"uid": paper.get("paperId", ""), "metadata": SemanticCitation(data=paper).data}
                return

            for word in words_to_remove:
                redacted_query = remove_word(query, word)
                if redacted_query != query:
                    query = redacted_query
                    break
            else:
                return

    def get_metadata(self, uid: str, metadata: dict) -> dict:
        citation = SemanticCitation(data=metadata)
        return {
            "uid": uid,
            "title": citation.title,
            "abstract": citation.abstract,
            "journal": citation.journal,
            "year": citation.year,
            "bibtex": citation.bibtex,
            "bibtex_id": citation.bibtex_id,
            "tldr": citation.tldr,
            "influence": citation.influence,
            "embedding": citation.embedding
        }

    def build_reference(self, metadata: dict) -> str:
        title = metadata.get("title", "No Title")
        journal = metadata.get("journal", "Unknown Journal")
        year = metadata.get("year", "n.d.")
        return f"{title}. *{journal}* ({year})"
    
    def metadata_to_citation(self, metadata: dict, query: str, search_rank: int = 0) -> Citation:
        return Citation(
            bibtex_id = metadata.get("bibtex_id") or str(uuid4()),
            title = metadata.get("title", ""),
            journal = metadata.get("journal", "Semantic Scholar"),
            year = str(metadata.get("year", "n.d.")),
            query = query,
            source = "semantic_scholar",
            search_rank = search_rank,
            tldr = metadata.get("tldr"),
            abstract = metadata.get("abstract", ""),
            influence = metadata.get("influence", 0),
            embedding = np.array(metadata["embedding"]) if metadata.get("embedding") is not None else None
        )


class SemanticScholarEmbeddingClient:
    def embed(self, paper: Dict[str, str]) -> np.ndarray:
        if not all(k in paper for k in ["paper_id", "title", "abstract"]):
            raise ValueError("Paper must have 'paper_id', 'title', and 'abstract'.")
        response = requests.post(EMBEDDING_URL, json=[paper])
        if response.status_code != 200:
            raise Exception(f"Embedding API Error: {response.status_code}")
        return np.array(response.json()["preds"][0]["embedding"])
    
    
# Example usage
if __name__ == "__main__":
    client = SemanticScholarClient()

    for item in client.lazy_search("RSV vaccine efficacy in older adults"):
        meta = client.get_metadata(item["uid"], item["metadata"])
        print("📄", client.build_reference(meta))