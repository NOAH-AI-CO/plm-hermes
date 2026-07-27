import os
import datetime
import logging
from urllib.parse import quote

from config import api_config
from azure.core.exceptions import AzureError, ServiceRequestError
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    UserDelegationKey,
    generate_blob_sas
)

logger = logging.getLogger(__name__)


class AzureBlobStorage:

    signed_expiry_days: int = 6
    user_delegation_key: UserDelegationKey = None

    def __init__(
        self,
        connection_string: str,
        *,
        read_url_expiry_days: int = 1,
    ):
        r"""
        https://learn.microsoft.com/zh-cn/azure/storage/blobs/storage-blob-user-delegation-sas-create-python?tabs=blob
        :param read_url_expiry_days: get_read_url() 生成的 SAS 有效天数，默认 1；公开桶可传 365 等。
        """
        self.blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        self.account_name = self._extract_account_name(connection_string)
        self.account_key = self._extract_account_key(connection_string)
        self._read_url_expiry_days = read_url_expiry_days

    def _extract_account_name(self, connection_string: str) -> str:
        for part in connection_string.split(';'):
            if part.startswith('AccountName='):
                return part.split('=', 1)[1]
        raise ValueError("AccountName not found in connection string")

    def _extract_account_key(self, connection_string: str) -> str:
        for part in connection_string.split(';'):
            if part.startswith('AccountKey='):
                return part.split('=', 1)[1]
        raise ValueError("AccountKey not found in connection string")

    def create_sas_token(
        self,
        container: str,
        blob: str,
        permission: BlobSasPermissions,
        time_delata: datetime.timedelta,
    ):
        start_time = datetime.datetime.now(datetime.timezone.utc)
        expiry_time = start_time + time_delata

        blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob)

        sas_token = generate_blob_sas(
            account_name=blob_client.account_name,
            container_name=blob_client.container_name,
            blob_name=blob_client.blob_name,
            account_key=self.account_key,
            permission=permission,
            expiry=expiry_time,
            start=start_time
        )

        return sas_token
    
    def get_blob_meta(
        self,
        container: str,
        blob: str,
    ):
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container,
                blob=blob
            )
            
            # Check if blob exists
            if not blob_client.exists():
                return None
            
            # Get blob properties
            properties = blob_client.get_blob_properties()
            
            return {
                'exists': True,
                'size': properties.size,
                'content_type': properties.content_settings.content_type if properties.content_settings else None,
                'last_modified': properties.last_modified,
                'etag': properties.etag,
                'metadata': properties.metadata if hasattr(properties, 'metadata') else {},
                'url': blob_client.url
            }
        except Exception as e:
            logger.error(f"Error getting blob metadata for {container}/{blob}: {e}")
            return None

    def upload_file(
        self,
        container: str,
        blob: str,
        file_obj,
        metadata: dict | None = None,
    ):
        try:
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob)

            # Upload content to block blob (metadata if provided, e.g. url for crawl cache)
            # URL-encode metadata values to handle non-ASCII characters (e.g. Chinese filenames)
            # Azure metadata is stored as HTTP headers which only support latin-1
            file_obj.seek(0)
            if metadata:
                safe_metadata = {k: quote(str(v), safe='') for k, v in metadata.items()}
                blob_client.upload_blob(file_obj, overwrite=True, metadata=safe_metadata)
            else:
                blob_client.upload_blob(file_obj, overwrite=True)

            # Return the blob URL
            return blob_client.url
        except Exception as e:
            logger.error(f"Error uploading file to {container}/{blob}: {e}")
            return None

    def load_file(
        self,
        container: str,
        blob: str,
    ):
        """
        Download a blob from Azure Blob Storage and return its content.

        Args:
            container: The name of the container.
            blob: The path/name of the blob within the container.

        Returns:
            The blob content as bytes if successful, otherwise None.
        """
        try:
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(
                container=container,
                blob=blob
            )

            # Check if blob exists
            if not blob_client.exists():
                logger.warning(f"Blob not found when loading file: {container}/{blob}")
                return None

            # Download and return content
            stream = blob_client.download_blob()
            return stream.readall()
        except Exception as e:
            logger.error(f"Error loading file from {container}/{blob}: {e}")
            return None

    def get_read_url(
        self,
        container: str,
        blob: str,
    ) -> str:
        """
        Generate a read-only URL with SAS token for the specified blob.
        
        Args:
            container: The name of the container.
            blob: The path/name of the blob within the container.
        
        Returns:
            A URL string with SAS token for reading the blob, or None if error occurs.
        """
        try:
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(
                container=container,
                blob=blob
            )
            
            # Check if blob exists
            #if not blob_client.exists():
            #    logger.warning(f"Blob not found when getting read URL: {container}/{blob}")
            #    return None
            
            # Generate SAS token with read permission
            # 有效期由 __init__ 的 read_url_expiry_days 决定，默认 1 天
            expiry_time = datetime.timedelta(days=self._read_url_expiry_days)
            sas_token = self.create_sas_token(
                container=container,
                blob=blob,
                permission=BlobSasPermissions(read=True),
                time_delata=expiry_time
            )
            
            # Construct the full URL with SAS token
            blob_url = blob_client.url
            if sas_token:
                return f"{blob_url}?{sas_token}"
            else:
                logger.error(f"Failed to generate SAS token for {container}/{blob}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting read URL for {container}/{blob}: {e}")
            return None

# Deprecate
def upload_file(bucket, object_key, file_path, timeout=300):
    """
    Upload a file to Azure Blob Storage with proper error handling.
    
    Args:
        object_key: The blob name/path in the container
        file_path: Local file path to upload
        timeout: Timeout in seconds for the upload operation
    
    Returns:
        bool: True if upload successful, False otherwise
    """
    # Instantiate a new BlobServiceClient using a connection string
    connection_string = api_config.get('AZURE_STORAGE_CONNECTION_STRING')

    if not connection_string:
        logger.error("AZURE_STORAGE_CONNECTION_STRING not found in api_config")
        return False
    
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string,
            connection_timeout=timeout,
            read_timeout=timeout
        )
    except Exception as e:
        logger.error(f"Failed to create BlobServiceClient: {e}")
        return False

    # Instantiate a new ContainerClient
    container_client = blob_service_client.get_container_client("nudata")

    try:
        # Instantiate a new BlobClient
        blob_client = container_client.get_blob_client(object_key)

        # Upload content to block blob with proper file handling
        with open(file_path, "rb") as source:
            # Read file content to avoid blocking I/O issues during upload
            file_content = source.read()
            
        # Upload with proper error handling
        blob_client.upload_blob(
            file_content, 
            blob_type="BlockBlob",
            overwrite=True,
            timeout=timeout
        )
        
        logger.info(f"Successfully uploaded {file_path} to {object_key}")
        return True
        
    except (OSError, IOError, BlockingIOError) as e:
        logger.error(f"I/O error during blob upload: {e}, file: {file_path}")
        return False
    except (AzureError, ServiceRequestError) as e:
        logger.error(f"Azure service error during blob upload: {e}, file: {file_path}")
        return False
    except Exception as e:
        logger.error(f"Unexpected exception during blob upload: {e}, file: {file_path}")
        return False
    finally:
        # Ensure client is properly closed
        try:
            blob_service_client.close()
        except:
            pass


def test_azure_blob():
    azure_blob = AzureBlobStorage(connection_string=api_config.AZURE_PRIVATE_STORAGE_CONNECTION_STRING)

    user_key = azure_blob.get_user_delegation_key()

    # https://noahdevuser.blob.core.windows.net/nudata/attachments/123@qq.com/1766218396-paper.pdf
    container = 'nudata'
    blob = 'attachments/123@qq.com/1766218396-paper.pdf'

    #read_url = azure_blob.get_read_url(container=container, blob=blob)

    #read = azure_blob.load_file(container=container, blob=blob)

if __name__ == '__main__':
    test_azure_blob()