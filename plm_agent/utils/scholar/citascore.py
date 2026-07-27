import requests
import logging
import json
from typing import List, Callable, Any

from impact_factor.core import Factor
from cachetools import TTLCache

from config import api_config
from utils.redis_client import get_connection

_request_cache = TTLCache(maxsize=10, ttl=60)  # 1 minute cache time out


class Scopus:
    r"""
    http://dev.elsevier.com
    """

    def __init__(self):
        self.api_key = "fa4c40d33defadb5eb3ba4cbbbac6be1"
        self.search_url = "https://api.elsevier.com/content/serial/title"
        self._global_cache_key = 'scopus-flag'

    def _format_cache_key(self, issn: str) -> str:
        return f"scopus-{issn}"

    def search_by_issn(self, issn: str) -> dict:
        try:
            cached_key = self._format_cache_key(issn=issn)
            conn = get_connection()
            if conn is not None:
                data = conn.get(cached_key)
                if data :
                    return json.loads(data)
            
            # avoid too frequent
            if self._global_cache_key in _request_cache:
                return {}

            headers = {
                "X-ELS-APIKey": self.api_key,
            }
            params = {
                "issn": issn,
                "view": "STANDARD"
            }
            response = requests.get(self.search_url, headers=headers, params=params)
            data = response.json()

            if conn is not None:
                conn.set(cached_key, json.dumps(data), ex=60*60*24*120)
            return data
        except requests.exceptions.SSLError as exc:
            #logger.warn(f"query cita scores issn {issn} failed for {exc}")
            _request_cache[self._global_cache_key] = True
            return {}
        except Exception as exc:
            #logger.warn(f"query scopus cita issn {issn} scores failed", exc)
            _request_cache[self._global_cache_key] = True
            return {}
        

class SCIIF:

    def __init__(self) -> None:
        self.fa = Factor()

    def search_by_issn(self, value: str):
        try:
            data = self.fa.search(value)
            if isinstance(data, list):
                return data[0]
            return data
        except Exception as exc:
            return {}

