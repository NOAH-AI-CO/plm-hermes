import asyncio

from config import settings
from utils.document.scihub_downloader import SciHubDownloader
from utils.document.unpaywall_downloader import UnpaywallDownloader
from utils.document.download_helper import DownloaderHelper


class Downloader:

    def __init__(self):
        self._unpaywall_downloader = UnpaywallDownloader()
        self._scihub_downloader = SciHubDownloader()
        self._download_helper = DownloaderHelper()

    def _check_local_file(self, fileid: str, idtype: str) -> str:

        if idtype == "doi":
            filename = self._download_helper.doi_to_filename(fileid)
            filepath = f"{settings.PDF_CACHE}/{filename}"
            if self._download_helper.check_local_file(filepath):
                return filepath

        return None


    async def doi(self,
                  doi: str,
                  force_download: bool = False) -> dict:
        """
        1. Check local file exist.
        2. Download the PDF using Unpaywall or SciHub.
        """
        if not force_download:
            filepath = self._check_local_file(doi, "doi")
            if filepath:
                return {
                    "file_path": filepath,
                    "source": "local"
                }

        result = await self._unpaywall_downloader.doi(doi)
        if "error" in result:
            result = await self._scihub_downloader.doi(doi)

        if 'error' not in result:
            result['file_path'] = result['pdf_path']

        return result



# Test the UnpaywallDownloader class

async def test_paper_downloader():
    downloader = Downloader()
    #doi = "10.1038/s41586-020-2649-2"  # Example DOI
    doi = "10.1186/s40658-025-00727-6"
    result = await downloader.doi(doi)
    print(result)


if __name__ == "__main__":
    asyncio.run(test_paper_downloader())