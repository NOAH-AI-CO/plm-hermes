import time
import logging

from datetime import datetime, timedelta
from urllib.parse import quote

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton

# https://site.financialmodelingprep.com/developer/docs

logger = logging.getLogger(__name__)


class FinancialModelinGprep:

    def __init__(self):
        self._api_key = api_config.FINANCIALMODELINGPREP_API_KEY
        self._max_retries = 2
        self._timeout = 15  # seconds
        self._retry_delay = 1  # seconds

    def _call(
        self,
        url: str) -> dict:
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

    def general_search(
        self,
        query: str) -> dict:
        query = quote(query)
        url = f"https://financialmodelingprep.com/api/v3/search?query={query}&apikey={self._api_key}"
        return self._call(url=url)
    
    def name_search(
        self,
        query: str,
        limit: int = 10) -> dict:
        url = f"https://financialmodelingprep.com/api/v3/search-name?query={query}&limit={limit}&apikey={self._api_key}"
        return self._call(url=url)

    def daily_char_eod(
        self,
        symbol: str,
        date_from: str = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d'),
        date_to: str = datetime.now().strftime('%Y-%m-%d')) -> dict:
        
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?from={date_from}&to={date_to}&apikey={self._api_key}"
        return self._call(url=url)

    def stock_news(
        self,
        tickers: list[str], # stock symbol, i.e. AAPL, FB
        page: int = 0,
        date_from: str = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d'),
        date_to: str = datetime.now().strftime('%Y-%m-%d'),
        limit: int = 50) -> dict:

        tickers = ','.join(tickers)
        url = f"https://financialmodelingprep.com/api/v3/stock_news?tickers={tickers}&page={page}&from={date_from}&to={date_to}&limit={limit}&apikey={self._api_key}"
        return self._call(url=url)

    def press_releases(
        self,
        symbol: str,
        page: int = 0) -> dict:

        url = f"https://financialmodelingprep.com/api/v3/press-releases/{symbol}?page={page}&apikey={self._api_key}"
        return self._call(url=url)

    def company_profile(
        self,
        symbol: str) -> dict:

        url = f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={self._api_key}"
        return self._call(url=url)

    def financial_statements_as_reported(
        self,
        symbol: str,
        period: str = 'annual',
        limit: int = 1) -> dict:

        url = f"https://financialmodelingprep.com/api/v3/financial-statement-full-as-reported/{symbol}?period={period}&limit={limit}&apikey={self._api_key}"
        return self._call(url=url)

if __name__ == "__main__":
    fmp = FinancialModelinGprep()

    print(fmp.general_search(query='apple'))

    #print(fmp.daily_char_eod(symbol='AAPL'))

    #print(fmp.stock_news(tickers=['AAPL']))

    #print(fmp.financial_statements_as_reported(symbol='AAPL'))
