import typesense

from config import settings


def get_client():
    client = typesense.Client({
        'api_key': settings.TYPESENSE_API_KEY,
        'nodes': [{
            'host': settings.TYPESENSE_HOST,
            'port': settings.TYPESENSE_PORT,
            'protocol': 'http'
        }],
        'connection_timeout_seconds': 10
    })
    return client

def search(client, collection, query, query_by, filter_value, filter_by, num_typos=0):
    search_params = {
        'q': query,
        'query_by': query_by,
        'num_typos': num_typos,
        'per_page': 30
    }
    if filter_value:
        search_params['filter_by'] = f"{filter_by}:={filter_value}"
    results = client.collections[collection].documents.search(search_params)
    return [result['document'] for result in results['hits']]

def search_one_column(client, name, query, num_typos=1, per_page=5):
    search_parameters = {
        'q': query,
        'query_by': 'name',
        'num_typos': num_typos,
        'per_page': per_page
    }
    results = client.collections[name].documents.search(search_parameters)
    if results['hits']:
        return results['hits'][0]['document']['name']
    else:
        return None
