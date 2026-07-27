"""
Test script for Azure Blob Storage crawler cache methods.
Tests _save_to_blob and _fetch_from_blob functionality.

Note: In production, fetch() uses _fetch_from_azure_blob (Azure Table) for reading,
and saves to both _save_azure_blob (Table) and _save_to_blob (Blob Storage) when writing.
This test directly tests the blob storage methods.

Run from noah_agent directory:
    cd /Users/w/Documents/code/NoahAgent/noah_agent
    python -m utils.web_search.test_crawler
"""
import sys
import os

# Get noah_agent directory path
noah_agent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Add noah_agent to path for imports

sys.path.insert(0, noah_agent_dir)

# Change working directory to noah_agent so config files can be found
os.chdir(noah_agent_dir)

from utils.web_search.crawler import ContentFetcherBase, CacheResultEnum


def test_blob_storage():
    """Test save and fetch from Azure Blob Storage"""
    
    fetcher = ContentFetcherBase()
    
    # Test data
    test_url = "https://example.com/test-page"
    test_content = "This is a test content for Azure Blob Storage. " * 100  # ~5KB content
    
    print(f"Testing with URL: {test_url}")
    print(f"Content length: {len(test_content)} characters")
    
    # Test 1: Save to blob
    print("\n[Test 1] Saving content to Azure Blob Storage...")
    fetcher._save_to_blob(test_url, test_content)
    print("Save completed.")
    
    # Test 2: Fetch from blob
    print("\n[Test 2] Fetching content from Azure Blob Storage...")
    result_status, result_content = fetcher._fetch_from_blob(test_url)
    print(f"Fetch status: {result_status}")
    print(f"Content length: {len(result_content)} characters")
    
    # Verify content matches
    if result_status == CacheResultEnum.FETCHED:
        if result_content == test_content:
            print("Content verification: PASSED")
        else:
            print("Content verification: FAILED - content mismatch")
    else:
        print(f"Fetch failed with status: {result_status}")
    
    # Test 3: Test with large content (> 32KB to verify no size limit)
    print("\n[Test 3] Testing with large content (> 32KB)...")
    large_content = "Large content test. " * 5000  # ~40KB content
    large_url = "https://example.com/large-test-page"
    
    print(f"Large content length: {len(large_content)} characters ({len(large_content.encode('utf-8'))} bytes)")
    
    fetcher._save_to_blob(large_url, large_content)
    result_status, result_content = fetcher._fetch_from_blob(large_url)
    
    if result_status == CacheResultEnum.FETCHED and result_content == large_content:
        print("Large content test: PASSED")
    else:
        print("Large content test: FAILED")
    
    print("\n=== All tests completed ===")


if __name__ == "__main__":
    test_blob_storage()
