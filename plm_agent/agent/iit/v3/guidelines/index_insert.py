from agent.iit.v3.guidelines.es_indexing import client
from agent.iit.utils.guidelines.embedding import get_embedding

def insert_index(pages, id, title):
    data = {
        "id": id,
        "title_cn": title,
        "cn_file_flg": "Y",
        "pages": pages
    }
    doc = {
        **data,
        "title_cn_vector": get_embedding(data["title_cn"]),  # Replace with actual embedding vector
    }
    resp = client.index(index='guidelines', id=data["id"], document=doc)
    print(f"Indexed document ID {data['id']}: {resp['result']}")