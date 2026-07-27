# -*- coding: utf-8 -*-
import asyncio
import logging
import alibabacloud_oss_v2 as oss

from typing import List, Dict
from utils.core.aliyun_oss_client import AliyunOSSClientSingleton
from utils.pubmed_opt.pmc_xml_parser import PMCXMLParser

logger = logging.getLogger(__name__)


class PubMedReader:

    oss_client: oss.Client = None
    oss_bucket: str = ''

    def __init__(self):
        self.oss_client = AliyunOSSClientSingleton.get_client()

    def read_pmc(self, pmcid: str) -> str:
        r"""
        Read PMC xml from Aliyun OSS and simple parse.
        """
        try:
            result = self.oss_client.get_object(oss.GetObjectRequest(
                bucket='noah-data-source-archive',
                key=f"pmc_xml/{pmcid}.xml"
            ))
            
            xml_content = result.body.read().decode('utf-8')
            parsed_text = PMCXMLParser.parse(xml_content)
            
            return parsed_text
            
        except Exception as e:
            logger.error(f"Read and parse PMC XML failed: {e}")
            return ""
    
    async def read_pmc_batch(
        self, 
        pmcids: List[str], 
        max_concurrent: int = 10
    ) -> Dict[str, str]:
        r"""
        Concurrently read multiple PMC xml files from Aliyun OSS and parse them.
        
        Args:
            pmcids: List of PMC IDs to read
            max_concurrent: Maximum number of concurrent requests (default: 10)
            
        Returns:
            Dictionary mapping pmcid to parsed text
            Failed items will have empty string as value
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def read_with_semaphore(pmcid: str) -> tuple[str, str]:
            """Read single file with semaphore control"""
            async with semaphore:
                try:
                    parsed_text = await asyncio.to_thread(self.read_pmc, pmcid)
                    logger.info(f"Successfully parsed {pmcid}")
                    return pmcid, parsed_text
                except Exception as e:
                    logger.warning(f"Failed to parse {pmcid}: {e}")
                    return pmcid, ""
        
        # Create tasks for all pmcids
        tasks = [read_with_semaphore(pmcid) for pmcid in pmcids]
        
        # Execute concurrently and gather results
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Convert to dictionary
        result_dict = dict(results)
        
        # Log summary
        success_count = sum(1 for v in result_dict.values() if v)
        logger.info(f"Batch read completed: {success_count}/{len(pmcids)} succeeded")
        
        return result_dict


# test
def test_fetch_read_pmc():
    reader = PubMedReader()

    result = reader.read_pmc('PMC176545')
    print(result)


if __name__ == "__main__":
    test_fetch_read_pmc()


