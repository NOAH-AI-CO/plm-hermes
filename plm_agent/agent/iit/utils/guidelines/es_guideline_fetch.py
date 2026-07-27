from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from config import api_config
import asyncio
from elasticsearch import NotFoundError

index_name = "clinical_guidelines"

subtree_index = "clinical_guidelines_subtree"

fields = [
'id', 'sub_tree_ids', 'source', 'publication_date', 'source_url', 'doc_url'
]
sub_tree_fields =[
    'id', 'description', 'name', 'disease', 'keywords', 'raw_text'
] 
id = "cdab8924-dda2-43b7-ab3d-44edf3bded88"
async def fetch_guideline_by_id(id: str):
    client = ElasticsearchClientSingleton.get_client()
    max_attempts = 3
    backoff = 1.0
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(
                index=index_name,
                id=id,
                _source=fields
            )
            break
        except NotFoundError:
            # Document doesn't exist — emulate ES response shape
            response = {'found': False}
            break
        except Exception as e:
            last_exc = e
            if attempt == max_attempts:
                # re-raise the last exception after exhausting retries
                raise
            await asyncio.sleep(backoff)
            backoff *= 2  
    ret = {}
    if response['found']:
        source = response['_source']
        print(f"Guideline ID: {response['_id']}")
        for field in fields:
            if field in source:
                ret[field] = source[field]
    else:
        print(f"Guideline with ID '{id}' not found")
        return 
    
    sub_tree_ids = ret.pop('sub_tree_ids', [])
    ret['choosen_subtree'] = False
    subtrees = []
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.search(
                index=subtree_index,
                size=100,
                query={
                    "terms": {
                        "id": sub_tree_ids
                    }
                },
                _source=sub_tree_fields
            )
            subtrees = response.get('hits', {}).get('hits', [])
            break
        except Exception as e:
            last_exc = e
            if attempt == max_attempts:
                raise
            await asyncio.sleep(backoff)
            backoff *= 2  
    ret['sub_tree'] = [
        {
            'id' : subtree['_source']['id'],
            'name' : subtree['_source']['name'],
            'description' : subtree['_source']['description'],
            'raw_text' : subtree['_source']['raw_text'],
            'disease': list(subtree['_source'].get('disease', [])) if subtree['_source'].get('disease') else [],
            'keywords': list(subtree['_source'].get('keywords', [])) if subtree['_source'].get('keywords') else [],
        }
        for subtree in subtrees
    ]
    return ret

