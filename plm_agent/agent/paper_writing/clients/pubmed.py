import json
import time
import xmltodict
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterator, Optional
from uuid import uuid4

import numpy as np
import requests

import logging
logging.basicConfig(level=logging.INFO)
from ..schema.citation import Citation


EMBEDDING_URL = 'https://model-apis.semanticscholar.org/specter/v1/invoke'

class PubMedEmbeddingClient:
    """
    A simple wrapper for generating embedding vectors using the SPECTER API for PubMed papers.
    """
    def __init__(self, embedding_url: str = EMBEDDING_URL):
        self.embedding_url = embedding_url

    def embed(self, title: str, abstract: str) -> np.ndarray:
        """
        Generate an embedding for a PubMed paper using its title and abstract.

        Args:
            title (str): The paper's title.
            abstract (str): The paper's abstract.

        Returns:
            np.ndarray: The resulting embedding vector (typically 768-d).

        Raises:
            ValueError: If title or abstract is missing.
            RuntimeError: If the embedding API request fails.
        """
        if not title.strip() or not abstract.strip():
            raise ValueError("Both title and abstract are required for embedding.")

        payload = [{
            "paper_id": "",  # not used, but required by the API schema
            "title": title.strip(),
            "abstract": abstract.strip()
        }]

        response = requests.post(self.embedding_url, json=payload)

        if response.status_code != 200:
            raise RuntimeError(f"Embedding API error: {response.status_code} - {response.text}")

        try:
            return np.array(response.json()["preds"][0]["embedding"])
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Malformed embedding response: {e}")

class PubMedClient:
    def __init__(self,
                 top_k_results: int = 3,
                 email: str = 'yichen.li@noahai.co',
                 api_key: str = "",
                 auto_embed: bool = False,
                 embedding_client: Optional[PubMedEmbeddingClient] = None):
        
        self.base_url_esearch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        self.base_url_efetch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
        self.max_retry = 5
        self.sleep_time = 0.2
        self.top_k_results = top_k_results
        self.email = email
        self.api_key = api_key
        self.auto_embed = auto_embed
        self.embedding_client = embedding_client or PubMedEmbeddingClient()

    def lazy_search(self, query: str) -> Iterator[dict]:
        encoded_query = urllib.parse.quote(query)
        url = f"{self.base_url_esearch}db=pubmed&term={encoded_query}&retmode=json&retmax={self.top_k_results}&usehistory=y"
        if self.api_key:
            url += f"&api_key={self.api_key}"

        logging.info(f"PubMed query: {url}")
        result = urllib.request.urlopen(url)
        json_text = json.loads(result.read().decode("utf-8"))
        webenv = json_text["esearchresult"]["webenv"]

        for uid in json_text["esearchresult"]["idlist"]:
            yield {"uid": uid, "webenv": webenv}

    def get_metadata(self, uid: str, webenv: str) -> dict:
        url = f"{self.base_url_efetch}db=pubmed&retmode=xml&id={uid}&webenv={webenv}"
        if self.api_key:
            url += f"&api_key={self.api_key}"

        retry = 0
        while True:
            try:
                result = urllib.request.urlopen(url)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and retry < self.max_retry:
                    time.sleep(self.sleep_time)
                    self.sleep_time *= 2
                    retry += 1
                else:
                    raise e

        xml_text = result.read().decode("utf-8")
        text_dict = xmltodict.parse(xml_text)

        try:
            article = text_dict["PubmedArticleSet"]["PubmedArticle"]
            citation = article["MedlineCitation"]
            article_data = citation["Article"]
        except KeyError:
            return {"uid": uid, "error": "Invalid article structure"}

        # DOI
        doi = ""
        try:
            ids = article.get("PubmedData", {}).get("ArticleIdList", {}).get("ArticleId", [])
            if isinstance(ids, list):
                for id_entry in ids:
                    if id_entry.get("@IdType") == "doi":
                        doi = id_entry.get("#text")
            elif isinstance(ids, dict) and ids.get("@IdType") == "doi":
                doi = ids.get("#text")
        except Exception:
            pass

        # Authors
        authors = []
        for a in article_data.get("AuthorList", {}).get("Author", []):
            fore = a.get("ForeName", "") or a.get("Initials", "")
            last = a.get("LastName", "")
            if fore or last:
                authors.append(f"{fore} {last}".strip())

        # MeSH Terms
        mesh_terms = []
        for mesh in citation.get("MeshHeadingList", {}).get("MeshHeading", []):
            descriptor = mesh.get("DescriptorName", {}).get("#text") if isinstance(mesh, dict) else None
            if descriptor:
                mesh_terms.append(descriptor)

        pub_info = article_data.get("ArticleDate") or article_data.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
        pub_date = "-".join([pub_info.get("Year", ""), pub_info.get("Month", ""), pub_info.get("Day", "")]).strip("-")

        return {
            "uid": uid,
            "doi": doi,
            "title": article_data.get("ArticleTitle", ""),
            "journal": article_data.get("Journal", {}).get("Title", ""),
            "volume": article_data.get("Journal", {}).get("JournalIssue", {}).get("Volume", ""),
            "issue": article_data.get("Journal", {}).get("JournalIssue", {}).get("Issue", ""),
            "pub_date": pub_date,
            "authors": authors,
            "mesh_terms": mesh_terms,
            "abstract": article_data.get("Abstract", {}).get("AbstractText", "")
        }
        
    def metadata_to_citation(self, metadata: dict, query: str, search_rank: int = 0) -> Citation:
        embedding = None
        abstract = self._clean_text(metadata.get("abstract", ""))
        title = self._clean_text(metadata.get("title", ""))

        if self.auto_embed and title and abstract:
            try:
                embedding = self.embedding_client.embed(title, self._clean_text(abstract))
            except Exception as e:
                print(f"Embedding failed: {e}")

        return Citation(
            bibtex_id=str(uuid4()),
            title=title,
            journal=metadata.get("journal", "PubMed"),
            year=str(metadata.get("year", "n.d.")),
            query=query,
            source="pubmed",
            search_rank=search_rank,
            tldr=None,  # PubMed 没有 tldr
            abstract=abstract,
            influence=0,
            embedding=embedding
        )
        
    def _clean_text(self, text):
        if isinstance(text, list):
            parts = []
            for item in text:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "#text" in item:
                    parts.append(item["#text"])
            return " ".join(parts)
        if isinstance(text, dict) and "#text" in text:
            return text["#text"]
        if isinstance(text, str):
            return text
        return ""

