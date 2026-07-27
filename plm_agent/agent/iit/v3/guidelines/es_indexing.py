from datetime import datetime
from elasticsearch import Elasticsearch

from agent.iit.utils.guidelines.embedding import get_embedding
import json
from config import settings
client = Elasticsearch(hosts=settings.NOAH_ELASTICSEARCH_URL, basic_auth=(settings.NOAH_ELASTICSEARCH_USERNAME, settings.NOAH_ELASTICSEARCH_PASSWORD))

# First, create the index with proper mappings
def index_doc(doc_path):
    index_name = "guidelines"
    mappings = {
        "_id": {"path": "id"},
        "properties": {
            "id": {"type": "long"},
            "sub_type": {"type": "integer"},
            "content": {"type": "text"},
            "reference": {"type": "text"},
            "publish_date": {"type": "date", "format": "yyyy-MM-dd", "ignore_malformed": True},
            "reply_count": {"type": "integer"},
            "download_count": {"type": "integer"},
            "copyright_method": {"type": "integer"},
            "copyright_name": {"type": "keyword"},
            "file_id": {"type": "keyword"},
            "file_size": {"type": "keyword"},
            "file_url": {"type": "keyword"},
            "file_name": {"type": "text"},
            "web_file_id": {"type": "keyword"},
            "web_file_name": {"type": "text"},
            "web_file_size": {"type": "keyword"},
            "web_file_url": {"type": "keyword"},
            "branch_id": {"type": "integer"},
            "branch_name": {"type": "keyword"},
            "pay_money": {"type": "keyword"},
            "download_flg": {"type": "keyword"},
            "pdf_review_flg": {"type": "keyword"},
            "pdf_review_id": {"type": "keyword"},
            "cn_file_flg": {"type": "keyword"},
            "relate_cms_flg": {"type": "keyword"},
            "has_txt_flg": {"type": "keyword"},
            "species": {"type": "keyword"},
            "interspecial_id": {"type": "integer"},
            "title_cn": {"type": "text"},
            "title_en": {"type": "text"},
            "author": {"type": "text"},
            # "author_list": {"type": "nested"},
            # "has_sub_info": {"type": "keyword"},
            # "has_inter": {"type": "keyword"},
            # "has_trans": {"type": "keyword"},
            # "has_back_ver": {"type": "keyword"},
            # "has_relate": {"type": "keyword"},
            # "back_ver": {"type": "nested"},
            "title_cn_vector": {
                "type": "dense_vector",
                "dims": 1024,
                "index": True,
                "similarity": "cosine"
            },
            "title_en_vector": {
                "type": "dense_vector",
                "dims": 1024,
                "index": True,
                "similarity": "cosine"
            },
            "toc": {"type": "text"},
            "summary": {"type": "text"},
            "parsing_method": {"type": "keyword"},
            "toc_vector": {
                "type": "dense_vector",
                "dims": 1024,
                "index": True,
                "similarity": "cosine"
            },
            "summary_vector": {
                "type": "dense_vector",
                "dims": 1024,
                "index": True,
                "similarity": "cosine"
            },
        }
    }
    # Check if index exists, if not create it with mappings
    if not client.indices.exists(index=index_name):
        client.indices.create(index=index_name, mappings=mappings)

    guideline = None
    with open(doc_path, 'r') as f:
        guideline = json.load(f)
    
    # Filter out fields that could cause excessive field count (like sub_info with dynamic keys)
    data = guideline["data"]

    keys = list(guideline["data"].keys())
    included = mappings["properties"].keys()
    for field in keys:
        if field not in included:
            data.pop(field, None)
        
    doc = {
        **data,
        "title_cn_vector": get_embedding(guideline["data"]["title_cn"]) if guideline["data"]["title_cn"] else None,  # Replace with actual embedding vector
        "title_en_vector": get_embedding(guideline["data"]["title_en"]) if guideline["data"]["title_en"] else None,  # Replace with actual embedding vector
    }

    resp = client.index(index=index_name, id=data['id'], document=doc, refresh=True)
    # print(resp['result'])


def ensure_guidelines_index():
    """Create the guidelines index with proper mappings if it does not exist."""
    index_name = "guidelines"
    if not client.indices.exists(index=index_name):
        mappings = {
            "properties": {
                "id": {"type": "long"},
                "sub_type": {"type": "integer"},
                "content": {"type": "text"},
                "reference": {"type": "text"},
                "publish_date": {"type": "date", "format": "yyyy-MM-dd", "ignore_malformed": True},
                "reply_count": {"type": "integer"},
                "download_count": {"type": "integer"},
                "copyright_method": {"type": "integer"},
                "copyright_name": {"type": "keyword"},
                "file_id": {"type": "keyword"},
                "file_size": {"type": "keyword"},
                "file_url": {"type": "keyword"},
                "file_name": {"type": "text"},
                "web_file_id": {"type": "keyword"},
                "web_file_name": {"type": "text"},
                "web_file_size": {"type": "keyword"},
                "web_file_url": {"type": "keyword"},
                "branch_id": {"type": "integer"},
                "branch_name": {"type": "keyword"},
                "pay_money": {"type": "keyword"},
                "download_flg": {"type": "keyword"},
                "pdf_review_flg": {"type": "keyword"},
                "pdf_review_id": {"type": "keyword"},
                "cn_file_flg": {"type": "keyword"},
                "relate_cms_flg": {"type": "keyword"},
                "has_txt_flg": {"type": "keyword"},
                "species": {"type": "keyword"},
                "interspecial_id": {"type": "integer"},
                "title_cn": {"type": "text"},
                "title_en": {"type": "text"},
                "author": {"type": "text"},
                "title_cn_vector": {"type": "dense_vector", "dims": 1024, "index": True, "similarity": "cosine"},
                "title_en_vector": {"type": "dense_vector", "dims": 1024, "index": True, "similarity": "cosine"},
                "toc": {"type": "text"},
                "summary": {"type": "text"},
                "parsing_method": {"type": "keyword"},
                "toc_vector": {"type": "dense_vector", "dims": 1024, "index": True, "similarity": "cosine"},
                "summary_vector": {"type": "dense_vector", "dims": 1024, "index": True, "similarity": "cosine"},
            }
        }
        client.indices.create(index=index_name, mappings=mappings)
        print(f"Created index '{index_name}'.")
    else:
        print(f"Index '{index_name}' already exists.")
