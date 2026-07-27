from typing import Union, Optional, List
from pymilvus import AnnSearchRequest, WeightedRanker, RRFRanker

class MilvusRetriever:
    def __init__(self, client, collection_name, limit):
        self.client = client
        self.collection_name = collection_name
        self.limit = limit
    
    def basic_search(self,
                     query_vector: Union[List[list], list], 
                     output_fields: Optional[List[str]] = None,
                     search_params: Optional[dict] = None,
                     partition_names: Optional[List[str]] = None,
                     ):
        
        results = self.client.search(collection_name=self.collection_name,
                                     data=query_vector,
                                     limit=self.limit,
                                     output_fields=output_fields,
                                     search_params=search_params,
                                     partition_names=partition_names)
        return results
    
    def range_search(self,
                     query_vector: Union[List[list], list], 
                     output_fields: Optional[List[str]] = None,
                     radius: float = 0.1,
                     range_filter: float = 1.0,
                     metric_type: str = "L2",
                     **kwargs):
        
        if metric_type in ["L2", "JACCARD", "HAMMING"]:
            if range_filter > radius:
                raise ValueError(f"For {metric_type}, range_filter must be <= radius.")
            
        elif metric_type in ["IP", "COSINE"]:
            if radius > range_filter:
                raise ValueError(f"For {metric_type}, radius must be < range_filter.")
        else:
            raise ValueError(f"Unsupported metric type: {metric_type}")
        
        search_params = {
            "metric_type": metric_type,
            "params": {
                "radius": radius,
                "range_filter": range_filter
            }
        }
        
        results = self.client.search(collection_name=self.collection_name,
                                     data=query_vector,
                                     limit=self.limit,
                                     output_fields=output_fields,
                                     search_params=search_params,
                                     **kwargs)
        
        return results
    
    def group_search(self,
                     query_vector: Union[List[list], list], 
                     group_by_field: str,
                     group_size: int,
                     group_strict_size: bool = True,
                     **kwargs):
        
        # Currently, grouping search allows only for a single column. 
        # You cannot specify multiple field names in the group_by_field config. 
        # Additionally, grouping search is incompatible with data types of JSON, FLOAT, DOUBLE, ARRAY, or vector fields.
        
        results = self.client.search(collection_name=self.collection_name,
                                     data=query_vector,
                                     group_by_field=group_by_field,
                                     group_size=group_size,
                                     group_strict_size=group_strict_size,
                                     limit=self.limit,
                                     **kwargs)    
        return results
    
    def ann_search(self,
                   query_vector: List,
                   anns_field: str,
                   search_params: dict,
                   **kwargs):
        
        
        
        results = AnnSearchRequest(query_vector, anns_field, param=search_params, limit=self.limit)
        
        return results
    
    def habrid_search(self,
                      query_vector: List,
                      anns_fields: List[str],
                      search_params: dict,
                      ranker_type: str = "weighted",
                      weights: tuple[float] = None,
                      **kwargs):
        # Before conducting hybrid search, load the collection into memory.
        self.client.load_collection(self.collection_name)
        
        reqs = []
        
        for anns_field in anns_fields:
            req = self.ann_search(query_vector, anns_field, search_params, limit=self.limit)
            reqs.append(req)
        
        if ranker_type == "weighted":
            if weights is None or len(weights) != len(anns_fields):
                raise ValueError("Weights must be provided and must match the number of search_requests for WeightedRanker.")
            rerank_strategy = WeightedRanker(*weights)
        elif ranker_type == "rff":
            rerank_strategy = RRFRanker()
        else:
            raise ValueError("Unsupported ranker_type. Use 'weighted' for WeightedRanker or 'rff' for RRFRanker.")
        
        result = self.client.hybrid_search(query_vector, reqs, rerank_strategy, limit=self.limit)
        return result