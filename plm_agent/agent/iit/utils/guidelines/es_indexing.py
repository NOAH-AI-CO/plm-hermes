from datetime import datetime
from elasticsearch import Elasticsearch

from agent.iit.utils.guidelines.embedding import get_embedding
import json
from config import api_config
client = Elasticsearch(hosts=api_config.ES_HOST, basic_auth=(api_config.ES_USERNAME, api_config.ES_PASSWORD))

# First, create the index with proper mappings
index_name = "guidelines"

# Check if index exists, if not create it with mappings
if not client.indices.exists(index=index_name):
    mappings = {
        "properties": {
            "id": {"type": "keyword"},
            "name": {"type": "text"},
            "name_vector": {
                "type": "dense_vector",
                "dims": 1024,  # Adjust based on your embedding model
                "index": True,
                "similarity": "cosine"
            },
            "description": {"type": "text"},
            "source": {"type": "keyword"},
            "version": {"type": "keyword"},
        }
    }
    client.indices.create(index=index_name, mappings=mappings)

guidelines = []
with open('agent/iit/utils/guidelines/guidelines_layer_1.json', 'r') as f:
    guidelines = json.load(f)
    
for doc_raw in guidelines:
# doc_raw = {
#     "id": "cdab8924-dda2-43b7-ab3d-44edf3bded88",
#     "name": "Early and locally advanced non-small-cell lung cancer (NSCLC): ESMO Clinical Practice Guidelines for diagnosis, treatment and follow-up",
#     "description": "The ESMO Clinical Practice Guidelines for early and locally advanced non-small-cell lung cancer (NSCLC) provide comprehensive recommendations for diagnosis, treatment, and follow-up. Key points include: the importance of accurate staging and molecular pathology to guide treatment decisions; surgical interventions as a primary treatment for early-stage NSCLC; the use of systemic therapies and radiotherapy as necessary; and specific strategies for managing locally advanced stages, including consideration of resectability. The guidelines also emphasize personalized treatment approaches, particularly the use of targeted therapies based on individual patient tumor profiles, and outline protocols for long-term follow-up and management of survivorship.",
#     "source": "ESMO",
#     "version": "8",
#     "publication_date": "December 2016"
# }
    doc = {
        **doc_raw,
        "name_vector": get_embedding(doc_raw["name"]),  # Replace with actual embedding vector
    }
    
    doc.pop("publication_date", None)  # Remove if exists

    resp = client.index(index=index_name, document=doc)
    print(resp['result'])