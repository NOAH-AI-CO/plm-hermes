import time
import logging

from datetime import datetime, timedelta
from urllib.parse import quote

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton

# https://www.mairui.club/hsdata
logger = logging.getLogger(__name__)


class MaiRui:

    def __init__(self):
        self._api_key = api_config.MAIRUIFINANCE_API_KEY
        self._max_retries = 2
        self._timeout = 15  # seconds
        self._retry_delay = 1  # seconds

    def _call(
        self,
        url: str
    ) -> dict:
        for attempt in range(self._max_retries):
            try:
                client = HttpxClientSingleton.get_client()
                response = client.get(url, timeout=self._timeout)
                response.raise_for_status()  # Raise an exception for bad status codes
                return response.json()
            except Exception as e:
                if attempt == self._max_retries - 1:  # Last attempt
                    #raise Exception(f"Failed to fetch data after {self._max_retries} attempts: {str(e)}")
                    logger.warning(f"Failed to fetch data after {self._max_retries} attempts: {str(e)}")
                    return {}
                time.sleep(self._retry_delay)
                continue

    def balance_financial_statements(
        self,
        symbol: str,
        date_from: str = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d'),
        date_to: str = datetime.now().strftime('%Y%m%d'),
    ):
        url = f"http://api.mairuiapi.com/hsstock/financial/balance/{symbol}/{self._api_key}?st={date_from}&et={date_to}"
        return self._call(url)
    
    def income_financial_statements(
        self,
        symbol: str,
        date_from: str = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d'),
        date_to: str = datetime.now().strftime('%Y%m%d'),
    ):
        url = f"http://api.mairuiapi.com/hsstock/financial/income/{symbol}/{self._api_key}?st={date_from}&et={date_to}"
        return self._call(url)
    
    def cashflow_financial_statements(
        self,
        symbol: str,
        date_from: str = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d'),
        date_to: str = datetime.now().strftime('%Y%m%d'),
    ):
        url = f"http://api.mairuiapi.com/hsstock/financial/cashflow/{symbol}/{self._api_key}?st={date_from}&et={date_to}"
        return self._call(url)

    def financial_statements(
        self,
        symbol: str,
        date_from: str = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d'),
        date_to: str = datetime.now().strftime('%Y%m%d'),
    ):
        balance = self.balance_financial_statements(symbol, date_from, date_to)
        income = self.income_financial_statements(symbol, date_from, date_to)
        cashflow = self.cashflow_financial_statements(symbol, date_from, date_to)

        return {
            "balance": balance,
            "income": income,
            "cashflow": cashflow,
        }

    def daily_char_eod(
        self,
        symbol: str,
        date_from: str = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d'),
        date_to: str = datetime.now().strftime('%Y-%m-%d')) -> dict:
        
        url = f"https://api.mairuiapi.com/hsstock/history/{symbol}/d/n/{self._api_key}?st={date_from}&et={date_to}&lt=100"
        return self._call(url=url)
