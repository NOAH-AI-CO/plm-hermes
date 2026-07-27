import os
import asyncio
import random
import requests
import logging

from unpywall import Unpywall
from unpywall.utils import UnpywallCredentials
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from config import api_config, settings
from utils.document.download_helper import DownloaderHelper

logger = logging.getLogger(__name__)


class UnpaywallClient:

    def __init__(self, email: str):
        self.email = email
        UnpywallCredentials(email)

    def get_metadata(self, doi: str) -> dict:
        try:
            return Unpywall.get_json(doi)
        except Exception as e:
            logger.warning(f"[ERROR] Failed to get JSON for {doi}: {e}")
            return {}

    def get_pdf_link(self, doi: str) -> str:
        return Unpywall.get_pdf_link(doi)
    
    def get_json(self, doi: str) -> dict:
        return Unpywall.get_json(doi)

    def build_reference(self, doi: str) -> str:
        data = Unpywall.get_json(doi)
        authors = data.get("z_authors", [])
        author_strs = []
        for a in authors:
            given = a.get("given", "").strip()
            family = a.get("family", "").strip()
            if given and family:
                author_strs.append(f"{family}, {given}")
        if len(author_strs) > 5:
            authors_text = ", ".join(author_strs[:5]) + ", et al."
        elif len(author_strs) > 1:
            authors_text = ", ".join(author_strs[:-1]) + ", & " + author_strs[-1]
        else:
            authors_text = author_strs[0] if author_strs else ""

        year = data.get("year", "")
        title = data.get("title", "").strip()
        journal = data.get("journal_name", "").strip()
        doi_url = data.get("doi_url") or f"https://doi.org/{data.get('doi')}"

        return f"{authors_text} ({year}). {title}. *{journal}*. {doi_url}"

    def sanitize_filename(self, filename: str) -> str:
        # Remove any characters that are not alphanumeric, spaces, or underscores
        sanitized = "".join(c if c.isalnum() or c in [" ", "_"] else "_" for c in filename)
        # Replace spaces with underscores
        sanitized = sanitized.replace(" ", "_")
        return sanitized


class UnpaywallDownloader:

    _user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.1 Safari/605.1.15",
        "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.101 Mobile Safari/537.36",
    ]

    def __init__(self):
        self._clients = [UnpaywallClient(email) for email in api_config.UNPAYWALL_EMAILS.split(',')]
        self._save_dir = settings.PDF_CACHE
        self._helper = DownloaderHelper()

        # remote chrome docker
        self._remote_chrome_url = f"http://{settings.CHROME_HOST}:{settings.CHROME_PORT}/wd/hub"

        # local dir
        os.makedirs(self._save_dir, exist_ok=True)
        logger.info(f"Unpaywall client initialized with email: {api_config.UNPAYWALL_EMAILS} {self._remote_chrome_url}")

    def _get_headers(self):
        return {
            "User-Agent": random.choice(self._user_agents),
            "Accept": "application/pdf",
            "Referer": "https://academic.oup.com/",
        }

    def _is_valid_pdf_response(self, response):
        return (
            response.status_code == 200 and
            "pdf" in response.headers.get("Content-Type", "").lower()
        )

    def _selenium_get_pdf_url(self, article_url: str) -> str:
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--headless=new") # Uncomment for headless mode
        options.add_argument("--disable-gpu")
        if settings.ENV == 'local':
            driver = webdriver.Chrome(options=options)
        else:
            driver = webdriver.Remote(command_executor=self._remote_chrome_url, options=options)     
        try:
            driver.get(article_url)
            WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
            url = driver.current_url
            if url.endswith(".pdf") or ".pdf?" in url:
                return url
            try:
                link = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '.pdf')]"))
                )
                return link.get_attribute("href")
            except: pass
            try:
                iframe = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, '.pdf')]"))
                )
                return iframe.get_attribute("src")
            except: pass
            return ""
        finally:
            driver.quit()

    async def doi(self, doi: str):
        client = random.choice(self._clients)
        #reference = client.build_reference(doi)
        #filename = client.sanitize_filename(reference) + ".pdf"
        filename = self._helper.doi_to_filename(doi)
        save_path = os.path.join(self._save_dir, filename)

        try:
            url = client.get_pdf_link(doi)
            if not url:
                raise ValueError("No direct PDF link found.")
            logger.info(f"Direct download: {url}")
            r = requests.get(url, headers=self._get_headers(), stream=True, timeout=20)
            if self._is_valid_pdf_response(r):
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                return {
                    "filename": filename,
                    "pdf_path": save_path,
                    "source": "unpaywall-direct"
                }
        except Exception as e:
            logger.warning(f"Unpaywall Direct failed: {e}")

        try:
            #article_url = meta.get("best_oa_location", {}).get("url")
            data = client.get_json(doi)
            article_url = data.get("best_oa_location", {}).get("url")
            logger.info(f"Unpaywall doi_url {article_url}")
            if article_url:
                pdf_url = self._selenium_get_pdf_url(article_url)
                if pdf_url:
                    r = requests.get(pdf_url, headers=self._get_headers(), stream=True, timeout=20)
                    if self._is_valid_pdf_response(r):
                        with open(save_path, "wb") as f:
                            for chunk in r.iter_content(1024):
                                f.write(chunk)
                        logger.info("Unpaywall selenium download success")
                        return {
                            "pdf_path": save_path,
                            "source": "selenium-redirect"
                        }
            else:
                logger.info(f"Unpaywall get json failed, response {data}")
        except Exception as e:
            logger.warning(f"Unpaywall Selenium fallback failed: {e}")

        return {
            "pdf_path": "",
            "error": f"Failed to download PDF for {doi}"
        }


# Test the UnpaywallDownloader class

async def test_unpaywall_downloader():
    downloader = UnpaywallDownloader()
    #doi = "10.1038/s41586-020-2649-2"  # Example DOI
    #doi = "10.1016/j.apsb.2025.01.021"
    doi = "10.3390/ph15101292"
    result = await downloader.doi(doi)
    print(result)


if __name__ == "__main__":
    asyncio.run(test_unpaywall_downloader())
