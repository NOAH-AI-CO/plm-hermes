from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Union, Any
from pydantic import BaseModel, Field
from functools import partial
import json
import numpy as np

import logging
logging.basicConfig(level=logging.INFO)

from llm.azure_models import GPT4o
from ..clients.pubmed import PubMedClient
from ..clients.semantic_scholar import SemanticScholarClient
from ..schema.citation import CitationCollection, MultiQueryCitationManager
from ..utils.statistical_analysis import NiceList



SCOPE_DEFINITIONS_AND_EXAMPLES = {
    'dataset': {
        'definition': 'papers that use the same or similar datasets as in our study',
        'examples': ['The UK-NCD dataset', 'covid-19 vaccine efficacy dataset']
    },
    'questions': {
        'definition': 'papers that ask questions similar to our study',
        'examples': ['covid-19 vaccine efficacy over time', 'covid-19 vaccine waning']
    },
    'background': {
        'definition': 'papers that provide background on the overall subject of our study',
        'examples': ["SARS-CoV2 spread", "covid-19 global impact", "covid-19 vaccine"],
    },
    'methods': {
        'definition': 'papers that use the same or similar methods as in our study',
        'examples': ["covid-19 vaccine efficacy analysis", "kaplan-meier survival analysis"],
    },
    'results': {
        'definition': 'papers that report results similar to our study',
        'examples': ["covid-19 vaccine efficacy", "covid-19 vaccine efficacy over time", "covid-19 vaccine waning"],
    }
}


class LiteratureSearchQuery(BaseModel):
    scope: Literal["background", "methods", "results", "dataset", "questions"] = Field(description="The scope of the literature search query")
    queries: List[str] = Field(description="List of search queries for literature retrieval.")
    
class LiteratureSearchQueryList(BaseModel):
    queries: List[LiteratureSearchQuery] = Field(description="List of literature search queries.")
    
    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:
        return {item.scope: item.queries for item in self.queries}
    
    def pretty_print(self) -> str:
        return json.dumps(self.model_dump(), indent=2, ensure_ascii=False)
    

class LiteratureSearchQueryRewriter:
    """
    A class to handle literature search queries based on the user's study.
    """
    def __init__(self, target_scopes=['background'], llm=None):
        
        self.llm = llm or GPT4o()
        
        self.scopes_to_definitions_and_examples = SCOPE_DEFINITIONS_AND_EXAMPLES
        self.target_scopes = target_scopes or list(self.scopes_to_definitions_and_examples.keys())
        self.value_type = dict
        self.goal_noun = 'literature search queries'
        self.goal_verb = 'write'
        self.mission_prompt = """
        Please write literature-search queries that we can use to search for papers related to our study.

        You would need to compose search queries to identify prior papers covering these {num_scopes} scopes:
        {pretty_scopes_to_definitions}

        Return your answer as {your_response_should_be_formatted_as}, \t
        where the keys MUST be exactly the {num_scopes} scopes noted above (and ONLY these), \t
        and the values are lists of query string.

        Each individual query should be a string with up to 5-10 words. 

        For example, for a study reporting waning of the efficacy of the covid-19 BNT162b2 vaccine based on analysis \t
        of the "United Kingdom National Core Data (UK-NCD)", the queries could be:
        ```{python_or_json}
        {pretty_scopes_to_examples}
        ```

        Your response should be formatted as {your_response_should_be_formatted_as}  
        """
        
   
    def chosen_scopes_to_definitions_and_examples(self) -> Dict[str, Dict[str, str]]:
        return {key: self.scopes_to_definitions_and_examples[key] for key in self.target_scopes}

    def pretty_scopes_to_definitions(self) -> str:
        return '\n'.join([f'"{scope}": {definition_and_examples["definition"]}'
                          for scope, definition_and_examples
                          in self.chosen_scopes_to_definitions_and_examples().items()])
        
    def pretty_scopes_to_examples(self) -> str:
        nice = partial(NiceList, wrap_with='"', prefix='[', suffix=']', separator=', ')
        return ('{\n' +
                '\n'.join([f'    "{scope}": {nice(definition_and_examples["examples"])}'
                           for scope, definition_and_examples
                           in self.chosen_scopes_to_definitions_and_examples().items()]) +
                '\n}')

    def num_scopes(self) -> int:
        return len(self.target_scopes)
        
    def pretty_scope_contexts(self, context_inputs: Union[str, List[str], Dict[str, str]]) -> str:
        """
        Format user-provided inputs into LLM-friendly context string.

        - Dict[str, str]: labeled by scope (adds [SCOPE] headers)
        - List[str]: merged as plain multi-paragraph text
        - str: returned as-is
        """
        if isinstance(context_inputs, dict):
            return '\n'.join([
                f"[{scope.upper()}]\n{(context_inputs.get(scope) or '(no content provided)').strip()}\n"
                for scope in self.target_scopes
            ])
    
        elif isinstance(context_inputs, list):
            # merge as plain paragraphs, no [SCOPE_n]
            return '\n\n'.join([
                text.strip() for text in context_inputs if isinstance(text, str) and text.strip()
            ])

        elif isinstance(context_inputs, str):
            return context_inputs.strip()

        else:
            return '(no content provided)'
    
    async def run(self, context_inputs: Dict[str, str], **kwargs) -> LiteratureSearchQuery:
        
        context_inputs_text = self.pretty_scope_contexts(context_inputs)

    
        user_prompt = f"""Below is the context of our study:\n\n{context_inputs_text}\n\n---\n\n{self.mission_prompt.format(
            num_scopes=self.num_scopes(),
            pretty_scopes_to_definitions=self.pretty_scopes_to_definitions(),
            pretty_scopes_to_examples=self.pretty_scopes_to_examples(),
            your_response_should_be_formatted_as='a JSON object',
            python_or_json='JSON object'
        )}"""
        
        response = await self.llm.client.beta.chat.completions.parse(
            model = self.llm.model,
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful assistant that writes literature search queries."
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            response_format=LiteratureSearchQueryList,
            max_tokens=1024)
        
        response = response.choices[0].message.parsed

        return response
    
class LiteratureSearchPipeline:
    def __init__(
        self,
        context_inputs: Dict[str, str],
        target_scopes: List[str],
        semantic_client: SemanticScholarClient,
        pubmed_client: PubMedClient,
        top_k: int = 5,
    ):
        self.context_inputs = context_inputs
        self.target_scopes = target_scopes
        self.semantic_client = semantic_client
        self.pubmed_client = pubmed_client
        self.top_k = top_k

        self.query_result = None
        self.embedding_target: Optional[np.ndarray] = None
        self.manager = MultiQueryCitationManager()

    async def generate_search_queries(self):
        rewriter = LiteratureSearchQueryRewriter(target_scopes=self.target_scopes)
        self.query_result = await rewriter.run(context_inputs=self.context_inputs)
        print(f"Generated queries:\n{self.query_result.pretty_print()}")
        return self.query_result

    async def retrieve_citations(self):
        queries_by_scope = self.query_result.model_dump()
        print(f"Queries by scope:\n{queries_by_scope}")
        print(type(queries_by_scope))

        for scope, queries in queries_by_scope.items():
            for query in queries:
                citations = []

                # Semantic Scholar
                try:
                    print(f"Searching Semantic Scholar for query '{query}' in scope '{scope}'")
                    for i, item in enumerate(self.semantic_client.lazy_search(query)):
                        metadata = self.semantic_client.get_metadata(item["uid"], item["metadata"])
                        citation = self.semantic_client.metadata_to_citation(metadata, query=query, search_rank=i)
                        citation.scope = scope  # 注入 scope
                        citations.append(citation)
                except Exception as e:
                    logging.error(f"Error during Semantic Scholar search: {e}")

                # PubMed
                try:
                    print(f"Searching PubMed for query '{query}' in scope '{scope}'")
                    for i, item in enumerate(self.pubmed_client.lazy_search(query)):
                        metadata = self.pubmed_client.get_metadata(item["uid"], item["webenv"])
                        citation = self.pubmed_client.metadata_to_citation(metadata, query=query, search_rank=i)
                        citation.scope = scope  # 注入 scope
                        citations.append(citation)
                except Exception as e:
                    logging.error(f"Error during PubMed search: {e}")
                    
                print(f"Found {len(citations)} citations for query '{query}' in scope '{scope}'")

                self.manager.add_query_results(scope, query, citations)

    def get_filtered_citations(
        self,
        total: Optional[int] = None,
        min_influence: int = 0,
        sort_by_similarity: bool = False
    ) -> CitationCollection:
        return self.manager.get_sorted_filtered_citations(
            total=total or 100_000,
            sort_by_similarity=sort_by_similarity,
            embedding_target=self.embedding_target,
            min_influence=min_influence
        )

    def save_filtered_citations(self, citations: CitationCollection, prefix: str = "filtered_citations"):
        self._save_citations_as_bibtex(citations, f"{prefix}.bib")
        self._save_citations_as_json(citations, f"{prefix}.json")
        print(f"Saved filtered results to {prefix}.json/.bib")

    def save_all_citations(self, prefix: str = "all_citations"):
        raw = self.manager.merge_all()
        self._save_citations_as_json(raw, f"{prefix}.json")
        self._save_citations_as_bibtex(raw, f"{prefix}.bib")
        print(f"Saved all unfiltered results to {prefix}.json/.bib")

    def _save_citations_as_bibtex(self, citations: CitationCollection, path: str):
        with open(path, "w", encoding="utf-8") as f:
            for c in citations:
                f.write(f"@article{{{c.bibtex_id},\n")
                f.write(f"  title={{ {c.title} }},\n")
                f.write(f"  journal={{ {c.journal} }},\n")
                f.write(f"  year={{ {c.year} }},\n")
                f.write(f"  note={{ Source: {c.source}, Query: {c.query} }}\n")
                f.write("}\n\n")
        logging.info(f"BibTeX saved to: {path}")

    def _save_citations_as_json(self, citations: CitationCollection, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([
                {
                    "bibtex_id": c.bibtex_id,
                    "title": c.title,
                    "journal": c.journal,
                    "year": c.year,
                    "query": c.query,
                    "source": c.source,
                    "search_rank": c.search_rank,
                    "tldr": c.tldr,
                    "abstract": c.abstract,                    
                    "scope": c.scope,                          
                    "influence": c.influence,
                    "embedding": c.embedding.tolist() if isinstance(c.embedding, np.ndarray) else None
                }
                for c in citations
            ], f, indent=2, ensure_ascii=False)
        logging.info(f"JSON saved to: {path}")
    
    
# test

import asyncio

TEST_SECTIONS = {
    "background": "RSV causes disease in older adults. Effective vaccination is critical to reduce morbidity.",
    "methods": "We used Kaplan-Meier analysis and randomized control trial design.",
    "results": "Efficacy of the SCB-1019 vaccine dropped significantly after 6 months."
}

async def test_pipeline():
    TEST_SECTIONS = {
        "background": "RSV causes disease in older adults. Effective vaccination is critical to reduce morbidity.",
        "methods": "We used Kaplan-Meier analysis and randomized control trial design.",
        "results": "Efficacy of the SCB-1019 vaccine dropped significantly after 6 months."
    }

    semantic_client = SemanticScholarClient(top_k=3)
    pubmed_client = PubMedClient(email='yichen.li@noahai.co', top_k_results=3)
    
    requested_keys = ['background', 'methods', 'results']

    pipeline = LiteratureSearchPipeline(
        study_sections=TEST_SECTIONS,
        requested_keys=requested_keys,
        semantic_client=semantic_client,
        pubmed_client=pubmed_client,
        top_k=1
    )

    print("⏳ Generating queries...")
    await pipeline.generate_queries()

    print("🔍 Running literature search across sources...")
    await pipeline.search_all_sources()

    print("📚 Getting final merged and sorted results...")
    results = pipeline.get_final_results(total=5, min_influence=0, sort_by_similarity=False)
    print("🖨️ Final Results:\n")
    print(results.pretty_print())

    print("📝 Saving results to file...")
    pipeline.save(results, prefix="test_literature_results")

    print("\n✅ Done! Sample citations:\n")
    print(results.pretty_print())

if __name__ == "__main__":
    asyncio.run(test_pipeline())