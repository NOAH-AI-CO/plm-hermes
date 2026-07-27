import os
import aiohttp
import aiofiles
import asyncio
import logging

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from utils.document.download_helper import DownloaderHelper
from config import settings

logger = logging.getLogger(__name__)


class SciHubClient:
    def __init__(self, mirrors=None):
        self.scihub_mirrors = mirrors or [
            "https://sci-hub.ru",
            "https://sci-hub.se",
            "https://sci-hub.st",
            "https://sci-hub.box",
            "https://sci-hub.red",
            "https://sci-hub.al",
            "https://sci-hub.ee",
            "https://sci-hub.lu",
            "https://sci-hub.ren",
            "https://sci-hub.shop",
            "https://sci-hub.vg",
        ]

    async def fetch_pdf_url(self, doi, session):
        for base_url in self.scihub_mirrors:
            try:
                url = f"{base_url}/{doi}"
                async with session.get(url, timeout=10) as res:
                    html = await res.text()
                soup = BeautifulSoup(html, 'html.parser')
                iframe = soup.find("iframe")
                if not iframe:
                    continue

                pdf_url = iframe.get("src")
                if not pdf_url.startswith("http"):
                    pdf_url = urljoin(base_url, pdf_url)
                return pdf_url
            except Exception as e:
                logging.warning(f"Mirror failed {base_url}: {e}")
                continue
        return None


class SciHubDownloader:

    def __init__(self):
        self._client = SciHubClient()
        self._cache_dir = settings.PDF_CACHE
        self._helper = DownloaderHelper()
        os.makedirs(self._cache_dir, exist_ok=True)

    async def doi(self, doi: str):
        async with aiohttp.ClientSession() as session:
            pdf_url = await self._client.fetch_pdf_url(doi, session)
            if not pdf_url:
                logger.warning(f"No PDF found for DOI: {doi}")
                return {"error": "No PDF found."}

            filename = self._helper.doi_to_filename(doi)
            path = os.path.join(self._cache_dir, filename)

            if not os.path.exists(path):
                try:
                    async with session.get(pdf_url, timeout=20) as res:
                        async with aiofiles.open(path, 'wb') as f:
                            await f.write(await res.read())
                    logger.info(f"PDF downloaded: {path}")
                except Exception as e:
                    logger.error(f"Failed to download PDF: {e}")
                    return {"error": f"Failed to download PDF: {e}"}
            else:
                logger.info(f"Using cached PDF: {path}")

            return {
                "filename": filename,
                "pdf_path": path,
                "source": "scihub-direct"
            }


# Test the UnpaywallDownloader class

async def test_unpaywall_downloader():
    downloader = SciHubDownloader()
    doi = "10.1038/s41586-020-2649-2"  # Example DOI
    result = await downloader.doi(doi)
    print(result)


if __name__ == "__main__":
    asyncio.run(test_unpaywall_downloader())
