from elasticsearch import Elasticsearch
from sqlalchemy import create_engine
from llama_index import SQLDatabase, ServiceContext, StorageContext, VectorStoreIndex
from llama_index import PromptTemplate as li_PromptTemplate
from llama_index.indices.struct_store import NLSQLTableQueryEngine
from llama_index.vector_stores import ElasticsearchStore
from llama_index.retrievers import VectorIndexRetriever, NLSQLRetriever

# Constants
MAX_LENGTH = 30 * 1000 # Maximum length of the text to return.
CHUNK_SIZE = 2048 # Chunk size for the vector database.
CHUNK_OVERLAP = 64 # Chunk overlap for the vector database.
# INCLUDE_TABLES = ["pi_clinical_trials_20240221"] # Tables to include in the vector database.
INCLUDE_TABLES = ['cn_clinical_pi_info']

# Classes
class ESRetriever:
    """
    Document retriever based on Elastic Search
    """
    def __init__(self, es, index_name, similarity_top_k=20):
        """
        Args:
            es: Elastic Search instance
            index_name: Index name of ES
            similarity_top_k: Number of results to return
        """
        self.es = es
        self.index_name = index_name
        self.similarity_top_k = similarity_top_k

    def retrieve(self, query):
        """
        Retrieve documents based on the query. Using full text search (BM25) to retrieve documents.

        Args:
            query: Query string

        Returns:
            List of documents with their IDs, scores and text
        """
        try:
            res = self.es.search(
                index=self.index_name, 
                body={
                    "query": {"match": {"content": query}},
                    "size": self.similarity_top_k
                }
            )
            return [{'id': hit['_id'], 'score': hit['_score'], 'text': hit['_source']['content']} for hit in res['hits']['hits']]
        except Exception as e:
            print(f"Error retrieving documents: {e}")
            return None
        

class HybridRetriver:
    """Hybid Retriever that combines the results from ES full text search (BM25) and vector retrievers."""
    def __init__(self, es_retriever, vdb_retriever, similarity_top_k=10):
        """
        Args:
            es_retriever: ESRetriever instance
            vdb_retriever: VectorIndexRetriever instance (Llama_index retriever)
            similarity_top_k: Number of results to return
        """
        self.es_retriever = es_retriever
        self.vdb_retriever = vdb_retriever
        self.similarity_top_k = similarity_top_k

    def _retrieve(self, query):
        es_res = self.es_retriever.retrieve(query)
        vdb_res = self.vdb_retriever.retrieve(query)
        return es_res, vdb_res
    
    def _calculate_rrf(self, scores, k=60):
        """
        Calculate Reciprocal Rank Fusion scores.
        
        :param scores: A list of lists, where each sublist contains ranked document IDs.
        :param k: The RRF parameter, controlling fusion behavior.
        :return: A sorted list of documents based on RRF scores.
        """
        rrf_scores = {}
        
        # Calculate RRF score for each document in each list
        for score_list in scores:
            for rank, doc_id in enumerate(score_list, start=1):
                rrf_score = 1 / (k + rank)
                if doc_id in rrf_scores:
                    rrf_scores[doc_id] += rrf_score
                else:
                    rrf_scores[doc_id] = rrf_score
        
        # Sort documents by their RRF score in descending order
        sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        
        # Return sorted document IDs
        return [doc_id for doc_id, _ in sorted_docs]
    
    def retrieve(self, query):
        """
        Retrieve documents based on the query. Combining the results from ES and vector retrievers. Then calculate RRF scores to fuse the results.
        """
        es_res, vdb_res = self._retrieve(query)
        es_ids = [hit['id'] for hit in es_res] 
        vdb_ids = [hit.id_ for hit in vdb_res]
        fused_ids = self._calculate_rrf([es_ids, vdb_ids])

        searched_results = []
        for doc_id in fused_ids:
            if doc_id in es_ids:
                searched_results.append([x['text'] for x in es_res if x['id'] == doc_id][0])
            else:
                searched_results.append([x.text for x in vdb_res if x.id_ == doc_id][0])
        return searched_results[:self.similarity_top_k]
    



# Functions
def build_index(vector_store, service_context):
    """Build the vector index.

    Args:
        vector_store: Chroma collection or ElasticsearchStore.
        service_context (ServiceContext): Service context.

    Returns:
        VectorStoreIndex: Vector index.
    """
    # vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(
        vector_store,
        storage_context=storage_context,
        service_context=service_context
    )
    return index


def update_prompts(query_engine, prompt, prompt_name):
    """Update prompts in the query engine."""
    new_prompt = {prompt_name: li_PromptTemplate(prompt)}
    query_engine.update_prompts(new_prompt)
    return query_engine


def build_fusion_retriever_from_zero(sql_db_uri,
                                     chunk_size,
                                     chunk_overlap,
                                     llm,
                                     embedding_model,
                                     include_tables,
                                     es_url,
                                     es_username,
                                     es_password,
                                     update_prompt):
    """Build a fusion retriever from zero."""
    # Setup the SQL engine for BD deals
    engine = create_engine(sql_db_uri)

    # Setup the service context
    service_context = ServiceContext.from_defaults(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        llm=llm,
        embed_model=embedding_model,
    )

    # Setup the SQL database
    sql_database = SQLDatabase(engine, include_tables=include_tables)

    # Build the retriever and query engine
    es = Elasticsearch(
        hosts=es_url,
        basic_auth=(es_username, es_password)
    )
    es_vector_store = ElasticsearchStore(
        es_url=es_url,
        es_user=es_username,
        es_password=es_password,
        index_name=include_tables[0]
    )
    index = build_index(es_vector_store, service_context)

    # retrievers
    vdb_retriever = VectorIndexRetriever(index=index, similarity_top_k=10)
    es_retriver = ESRetriever(es, include_tables[0], similarity_top_k=10)
    hybrid_retriver = HybridRetriver(es_retriver, vdb_retriever, similarity_top_k=6)

    sql_retriever = NLSQLRetriever(
        sql_database=sql_database,
        tables=include_tables,
        return_raw=True,
        service_context=service_context,
    )
    sql_retriever = update_prompts(sql_retriever,
                                   update_prompt,
                                   'text_to_sql_prompt') # Update prompts

    return sql_retriever, hybrid_retriver


def length_checker(text: str) -> str:
    """
    Checks if the length of the text is greater than the maximum length. 
    If it is, it will return the first MAX_LENGTH characters of the text.

    Args:
        text (str): Text to check.

    Returns:
        str: Text that is less than or equal to MAX_LENGTH characters.
    """
    if len(text) > MAX_LENGTH:
        return text[:MAX_LENGTH]
    else:
        return text

