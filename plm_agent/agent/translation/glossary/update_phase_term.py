from elasticsearch import Elasticsearch
from agent.translation.glossary.embedding import get_embeddings_batch
from config import api_config

client = Elasticsearch(hosts=api_config.ES_HOST, basic_auth=(api_config.ES_USERNAME, api_config.ES_PASSWORD))

index_name = "glossary"
old_en_term = "bayesian optimal phase 2 (BOP2)"
new_en_term = "bayesian optimal phase 2 (BOP2)"

# Find the document
resp = client.search(
    index=index_name,
    query={
        "bool": {
            "should": [
                {"term": {"en_term.keyword": old_en_term}},
                {"match_phrase": {"en_term": old_en_term}},
            ],
            "minimum_should_match": 1,
        }
    },
)
hits = resp["hits"]["hits"]

if not hits:
    print(f"No document found with EN Term: '{old_en_term}'")
else:
    doc_id = hits[0]["_id"]
    print(f"Found document id={doc_id}, updating EN term and re-embedding...")

    new_vector = get_embeddings_batch([new_en_term])[0]

    client.update(index=index_name, id=doc_id, doc={
        "en_term": new_en_term,
        "en_term_vector": new_vector,
    })
    print(f"Updated: '{old_en_term}' -> '{new_en_term}'")
