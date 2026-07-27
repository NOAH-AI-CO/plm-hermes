import asyncio
from utils.core.elasticsearch_client import ElasticsearchClientSingleton

index_name = "guidelines"

fields = [
    'id', 'pages', 'toc', 'title_cn'
]
# fields = [
#     'title_cn'
# ]
async def fetch_guideline_by_ids(ids: list):
    client = ElasticsearchClientSingleton.get_client()
    max_attempts = 3
    backoff = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.mget(
                index=index_name,
                ids=ids,
                _source=fields,
            )
            break
        except Exception as e:
            if attempt >= max_attempts:
                # re-raise the last exception after exhausting retries
                raise
            await asyncio.sleep(backoff)
            backoff *= 2
    else:
        # This block is executed if the loop completes without a break,
        # which should not happen due to the raise in the except block.
        return []

    results = []
    for doc in response.get('docs', []):
        if doc.get('found'):
            source = doc['_source']
            ret = {}
            print(f"Guideline ID: {doc['_id']}")
            for field in fields:
                if field in source:
                    ret[field] = source[field]
            results.append(ret)
        else:
            print(f"Guideline with ID '{doc['_id']}' not found")
    return results

if __name__ == "__main__":
    import asyncio

    async def main():
        ids = [50001, 50002, 50003]
        guidelines = await fetch_guideline_by_ids(ids)
        for guideline in guidelines:
            print(guideline)

    asyncio.run(main())
