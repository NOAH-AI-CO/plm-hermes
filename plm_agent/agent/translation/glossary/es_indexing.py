from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import json
import uuid

from agent.translation.glossary.embedding import get_embeddings_batch
from config import api_config

client = Elasticsearch(hosts=api_config.ES_HOST, basic_auth=(api_config.ES_USERNAME, api_config.ES_PASSWORD))

index_name = "glossary"

mappings = {
    "properties": {
        "id": {"type": "keyword"},
        "en_term": {"type": "text"},
        "cn_term": {"type": "text"},
        "en_term_vector": {
            "type": "dense_vector",
            "dims": 1024,
            "index": True,
            "similarity": "cosine"
        },
        "cn_term_vector": {
            "type": "dense_vector",
            "dims": 1024,
            "index": True,
            "similarity": "cosine"
        },
        "category": {"type": "keyword"},
        "source": {"type": "text"},
    }
}

# Delete and recreate index to avoid duplicates on reindex
if client.indices.exists(index=index_name):
    print(f"Deleting existing index '{index_name}'...")
    client.indices.delete(index=index_name)
client.indices.create(index=index_name, mappings=mappings)
print(f"Created index '{index_name}'")

with open('agent/translation/glossary/glossary.json', 'r') as f:
    glossary = json.load(f)

# Collect all terms
all_terms = []
for category, terms in glossary.items():
    for term in terms:
        all_terms.append({
            "en_term": term.get("EN Term", ""),
            "cn_term": term.get("CN Term", ""),
            "category": category,
            "source": term.get("Source"),
        })

print(f"Total terms to index: {len(all_terms)}")

# Batch embed all EN and CN terms
print("Embedding EN terms...")
en_texts = [t["en_term"] for t in all_terms]
en_vectors = get_embeddings_batch(en_texts)

print("Embedding CN terms...")
cn_texts = [t["cn_term"] for t in all_terms]
cn_vectors = get_embeddings_batch(cn_texts)

# Bulk index
actions = []
for i, term in enumerate(all_terms):
    doc = {
        "_index": index_name,
        "_source": {
            "id": str(uuid.uuid4()),
            "en_term": term["en_term"],
            "cn_term": term["cn_term"],
            "en_term_vector": en_vectors[i] if term["en_term"] else None,
            "cn_term_vector": cn_vectors[i] if term["cn_term"] else None,
            "category": term["category"],
            "source": term["source"],
        }
    }
    actions.append(doc)

success, failed = bulk(client, actions)
print(f"Indexed {success} documents, {failed} failed")