from utils.retrievers.typesense_retriever import get_client, search


def search_conference_papers(keyword: str="", phase: str="", conference: str="ash_papers", num_typos: int=2):
    client = get_client()
    results_keyword = search(client=client, collection=conference, query=keyword, query_by="keywords", filter_value=phase, filter_by="phase", num_typos=num_typos)
    for result in results_keyword:
        if "keywords" in result:
            del result["keywords"]
    return results_keyword
