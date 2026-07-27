# -*- coding: utf-8 -*-
import logging
import numpy as np

from typing import List
from httpx import HTTPError, ConnectError, TimeoutException

from config import settings
from utils.core.httpx_client import HttpxClientSingleton

log = logging.getLogger(__name__)


class MedCPTEncoder:
    r"""
    MedCPT encoders for query, article, and optional cross-encoder.
    """

    def query_encode(
        self,
        query_list: List[str],
    ) -> np.ndarray:
        client = HttpxClientSingleton.get_client()

        try:
            response = client.post(
                url=f"{settings.NOAH_EMBEDDING_URL}/embeddings",
                json={
                    "model": "ncbi/MedCPT-Query-Encoder",
                    "input": query_list,
                }
            )

            result = response.json()
            embeddings = [item["embedding"] for item in result["data"]] # List[List], i.e. [[0.043723, ...],[0.00013, ....]]
            arr = np.array(embeddings, dtype="float32") # List[List], i.e. [[0.043723, ...],[0.00013, ....]]
                
            return self._l2_normalize(arr)
        
        except (ConnectError, TimeoutException, HTTPError) as e:
            log.warning(f"Failed to connect encoding query {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error when encoding queries: {e}")
            return None

    def article_encode(
        self,
        article_list: List[str],
    ) -> np.ndarray:
        client = HttpxClientSingleton.get_client()

        try:
            response = client.post(
                url=f"{settings.NOAH_EMBEDDING_URL}/embeddings",
                json={
                    "model": "ncbi/MedCPT-Article-Encoder",
                    "input": article_list,
                }
            )
            
            result = response.json()
            embeddings = [item["embedding"] for item in result["data"]]
            arr = np.array(embeddings, dtype="float32")
            
            return self._l2_normalize(arr)

        except (ConnectError, TimeoutException, HTTPError) as e:
            log.warning(f"Failed to connect encoding query {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error when encoding queries: {e}")
            return None
    
    def cross_encode(
        self,
        queries: List[str],
    ) -> np.ndarray:
        client = HttpxClientSingleton.get_client()

        try:
            response = client.post(
                url=f"{settings.NOAH_EMBEDDING_URL}/embeddings",
                json={
                    "model": "ncbi/MedCPT-Cross-Encoder",
                    "input": queries,
                }
            )
            
            result = response.json()
            embeddings = [item["embedding"] for item in result["data"]]
            arr = np.array(embeddings, dtype="float32")
            
            return self._l2_normalize(arr)

        except (ConnectError, TimeoutException, HTTPError) as e:
            log.warning(f"Failed to connect encoding query {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error when encoding queries: {e}")
            return None        

    def _l2_normalize(
        self,
        x: np.ndarray,
        eps: float = 1e-12
    ) -> np.ndarray:
        r"""L2 normalize each line."""
        if x.size == 0:
            return x.astype("float32")
        n = np.linalg.norm(x, axis=1, keepdims=True)
        n = np.maximum(n, eps)
        return (x / n).astype("float32", copy=False)


def _test_pubmed_encoding():
    encoder = MedCPTEncoder()

    # query encoding
    query_result = encoder.query_encode(query_list=['hello world', 'RVS'])
    print(query_result)

    # article encoding
    article_result = encoder.article_encode(article_list=['hello world', 'RVS'])
    print(article_result)    

if __name__ == "__main__":
    _test_pubmed_encoding()

