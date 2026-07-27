import time
import logging

from typing import Optional
from enum import Enum
from datetime import datetime, timedelta

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton

# https://r0i378zfk2i.feishu.cn/wiki/DEcJwy4yciO1yKkyPDJcO0EXnsh?table=tblf8T8Q4hmrEavC&view=vew5gpx9C2

logger = logging.getLogger(__name__)

class StandardizeProtocol(str, Enum):
    r"""Standardizing protocal"""
    NOAH = 'noah'
    BMT = 'bmt'


class DatabaseToolStandardizer:

    def __init__(self):
        self.base_url = api_config.STANDARDIZER_BASE_URL
        self._max_retries = 1
        self._timeout = 10  # seconds
        self._retry_delay = 1  # seconds

    def _call(
        self,
        uri: str,
        params: dict) -> dict:
        for attempt in range(self._max_retries):
            nparams = {
                "query": params['query'],
                "protocol": params["protocol"].value
            }
            if params["verbose"] is not None:
                nparams['verbose'] = 't' if params["verbose"] else 'f'
            url = f"{self.base_url}/{uri}/"
            try:
                client = HttpxClientSingleton.get_client()
                response = client.get(url, params=nparams, timeout=self._timeout)
                response.raise_for_status()  # Raise an exception for bad status codes
                return response.json()
            except Exception as e:
                if attempt == self._max_retries - 1:  # Last attempt
                    #raise Exception(f"Failed to fetch data after {self._max_retries} attempts: {str(e)}")
                    logger.warning(f"Failed to fetch data after {self._max_retries} attempts: {str(e)}")
                    if params["verbose"] is not None:   
                        return {}
                    else:
                        return ''
                time.sleep(self._retry_delay)
                continue
 
    def drug_name(
        self,
        query: str,
        protocol: StandardizeProtocol = StandardizeProtocol.NOAH,
        verbose: Optional[bool] = None,
    ):
        params = locals().copy()
        params.pop('self')
        return self._call('drug_name', params)

    def drug_modality(
        self,
        query: str,
        protocol: StandardizeProtocol = StandardizeProtocol.NOAH, 
        verbose: Optional[bool] = None,
    ):
        params = locals().copy()
        params.pop('self')
        return self._call('drug_modality', params)
    
    def drug_feature(
        self,
        query: str,
        protocol: StandardizeProtocol = StandardizeProtocol.NOAH, 
        verbose: Optional[bool] = None,
    ):
        params = locals().copy()
        params.pop('self')
        return self._call('drug_feature', params)

    def administration_route(
        self,
        query: str,
        protocol: StandardizeProtocol = StandardizeProtocol.NOAH, 
        verbose: Optional[bool] = None,
    ):
        params = locals().copy()
        params.pop('self')
        return self._call('administration_route', params)
    
    def company(
        self,
        query: str,
        protocol: StandardizeProtocol = StandardizeProtocol.NOAH, 
        verbose: Optional[bool] = None,
    ):
        params = locals().copy()
        params.pop('self')
        return self._call('company', params)

    def indication(
        self,
        query: str,
        protocol: StandardizeProtocol = StandardizeProtocol.NOAH, 
        verbose: Optional[bool] = None,
    ):
        params = locals().copy()
        params.pop('self')
        return self._call('indication', params)

    def target(
        self,
        query: str,
        protocol: StandardizeProtocol = StandardizeProtocol.NOAH, 
        verbose: Optional[bool] = None,
    ):
        params = locals().copy()
        params.pop('self')
        return self._call('target', params)
    