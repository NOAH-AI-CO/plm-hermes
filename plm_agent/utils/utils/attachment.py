import time
import base64
import json
import logging
import io
import os
import traceback
import requests

from typing import List, Optional, Union
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import api_config
from utils.azure.blob_client import AzureBlobStorage
from utils.utils.image_compressor import ImageCompressor
from utils.sql_client import get_connection_user, text

logger = logging.getLogger(__name__)


class Storage(Enum):
    UNKNOWN = 'unknow'
    AZURE_BLOB = 'azure_blob'


class AttachmentManager:

    def __init__(self, public=False) -> None:
        if public:
            self.azure_blob = AzureBlobStorage(connection_string=api_config.AZURE_STORAGE_CONNECTION_STRING)
        else:
            self.azure_blob = AzureBlobStorage(connection_string=api_config.AZURE_PRIVATE_STORAGE_CONNECTION_STRING)

    def get_read_url(
        self,
        storage_meta: dict,
    ) -> str:
        storage = storage_meta.get('storage', '')

        if Storage.AZURE_BLOB.value == storage:

            container = storage_meta.get("container")
            blob = storage_meta.get("blob")

            return self.azure_blob.get_read_url(container, blob)
        
        return ''

    def fetch_content(
        self,
        file_name: str,
        content_meta: dict
    ):
       
        storage = content_meta.get("storage")

        # so far only support Azure Blob
        if Storage.AZURE_BLOB.value == storage:

            container = content_meta.get("container")
            blob = content_meta.get("blob")

            if not (container and blob):
                logger.warning(
                    f"Invalid azure_blob meta for attachment {file_name}: "
                    f"container={container}, blob={blob}"
                )
                return file_name, content_meta
            
            try:
                data = self.azure_blob.load_file(
                    container=container,
                    blob=blob,
                )
                
                if isinstance(data, bytes):
                    try:
                        text_content = data.decode("utf-8")
                    except UnicodeDecodeError:
                        text_content = data.decode("utf-8", errors="ignore")
                    else:
                        text_content = data or ""

                    # Try to parse as JSON if it's a JSON string
                    try:
                        parsed_json = json.loads(text_content)
                        # If parsed JSON is a dict with 'content' key, use that value; otherwise use the whole parsed JSON
                        if isinstance(parsed_json, dict) and 'content' in parsed_json:
                            content_meta["raw_content"] = parsed_json['content']
                        else:
                            content_meta["raw_content"] = parsed_json
                    except (json.JSONDecodeError, TypeError, ValueError):
                        # If parsing fails, keep the original text content
                        content_meta["raw_content"] = text_content
            except Exception as e:
                logger.warning(f"Load attachment from azure blob failed for {file_name}: {e}")
        
        return file_name, content_meta

    def fetch_images(
        self,
        storage_meta: dict,
        enable_base64: bool = True,
        max_size: tuple = (1024, 1024),
        quality: int = 85,
    ) -> Optional[Union[str, bytes]]:
        """
        Fetch images from Azure Blob Storage, compress them, and return as base64.
        
        Args:
            storage_meta: Dictionary containing storage metadata with 'storage', 'container', and 'blob' keys
            enable_base64: If True, return base64 encoded string; otherwise return compressed image bytes
            max_size: Maximum size (width, height) for image compression, default (1920, 1920)
            quality: JPEG quality for compression (1-100), default 85
            
        Returns:
            Base64 encoded string if enable_base64=True, otherwise compressed image bytes, or None if failed
        """
        image_data = None
        storage = storage_meta.get('storage', '')
        
        # Only support Azure Blob for now
        if Storage.AZURE_BLOB.value == storage:
            container = storage_meta.get("container")
            blob = storage_meta.get("blob")
        
            if not (container and blob):
                logger.warning(
                    f"Invalid azure_blob meta for image: "
                    f"container={container}, blob={blob}"
                )
                return None

            try:
                # Download image from Azure Blob
                image_data = self.azure_blob.load_file(
                    container=container,
                    blob=blob,
                )
            
                if not image_data or not isinstance(image_data, bytes):
                    logger.warning(f"Failed to load image data from {container}/{blob}")
                    return None
            
                # Check image data size (basic sanity check)
                if len(image_data) == 0:
                    logger.warning(f"Empty image data from {container}/{blob}")
                    return None

            except Exception as e:
                logger.warning(f"Load attachment from azure blob failed for {storage_meta}: {e}")
                return None
        
        if not image_data:
            return None
        
        compressor = ImageCompressor(
            max_size=max_size,
            quality=quality,
            # 如果你希望限制二进制体积，比如 1.5MB（base64 会更大）
            max_bytes=1_500_000,
            prefer_format="auto",
            alpha_mode="flatten",  # 透明 PNG 铺白底转 JPEG（通常更小）
        )

        res = compressor.compress(
            image_data,
            enable_base64=enable_base64,
            return_result=True,
        )

        if res is None:
            return None

        logger.info(
            f"Image {blob}: {res.width}x{res.height}, "
            f"{res.original_bytes//1024}KB -> {res.compressed_bytes//1024}KB "
            f"({res.ratio_percent:.1f}%), format: {res.format}"
        )

        if enable_base64:
            return base64.b64encode(res.data).decode("utf-8")
        return res.data

    def fetch_attachments(
        self,
        ids: List[str],
        fetch_content: bool = False,
        mode: str = 'sql',
        base_url: str = api_config.get("YH_BACKEND_URL", "http://localhost"),
        timeout: int = 30,
    ):
        ids = self._sanitize_ids(ids)
        if not ids:
            return []

        mode = self._normalize_fetch_mode(mode)
        
        try:
            if mode == 'api':
                token = api_config.get("YH_BACKEND_TOKEN", "")
                if not token:
                    logger.error("YH_BACKEND_TOKEN is empty, cannot call attachment content API")
                    return []

                headers = {
                    "Authorization": f"Token {token}",
                }

                res = []
                with ThreadPoolExecutor(max_workers=min(len(ids), 8)) as executor:
                    future_to_attachment_id = {
                        executor.submit(
                            self._fetch_attachment_record_api,
                            attachment_id=str(attachment_id),
                            base_url=base_url,
                            headers=headers,
                            timeout=timeout,
                        ): str(attachment_id)
                        for attachment_id in ids
                    }

                    for future in as_completed(future_to_attachment_id):
                        attachment_id = future_to_attachment_id[future]
                        try:
                            attachment_record = future.result()
                            if attachment_record:
                                res.append(attachment_record)
                        except Exception as e:
                            logger.warning(f"Failed to fetch attachment {attachment_id} via API: {e}")

                if not res:
                    raise Exception('no attachment records found')

                # keep order consistent with input ids
                order_map = {str(v): idx for idx, v in enumerate(ids)}
                res.sort(key=lambda item: order_map.get(str(item.get('id', '')), len(order_map)))
            else:
                with get_connection_user() as conn:
                    records = conn.execute(
                        text(
                            """SELECT id, name, url, content, storage, type
                               FROM "API_attachment" 
                               WHERE id = ANY(ARRAY[:ids]::uuid[])"""
                        ),
                        {"ids": [f for f in ids]},
                    )
                    records = records.fetchall()

                if not records:
                    raise Exception('no attachment records found')

                res = [self._build_attachment_record_from_sql_row(record) for record in records]

            if fetch_content:
                # Create a dict for O(1) lookup by id
                res_dict = {record['id']: record for record in res}
                
                with ThreadPoolExecutor(max_workers=min(len(res), 5)) as executor:
                    future_to_attachment = {
                        executor.submit(self.fetch_content, value['name'], value['content']): value['id']
                        for value in res
                        if isinstance(value.get('content'), dict)
                    }
                        
                    for future in as_completed(future_to_attachment):
                        attachment_id = future_to_attachment[future]
                        try:
                            _, updated_content_meta = future.result()
                            res_dict[attachment_id]['content'] = updated_content_meta
                        except Exception as e:
                            logger.warning(f"Failed to fetch content for attachment {attachment_id} : {e}")

            return res
        except Exception as e:
            logger.error(f"Failed to fetch attachments: {e}")
            return []

    def fetch_folders(
        self,
        ids: List[str]):

        ids = self._sanitize_ids(ids)
        if not ids:
            return []

        try:
            with get_connection_user() as conn:
                records = conn.execute(
                    text(
                        """SELECT id, name, type, full_path
                            FROM "API_attachment" 
                            WHERE id = ANY(ARRAY[:ids]::uuid[])"""
                    ),
                    {"ids": [f for f in ids]},
                )
                records = records.fetchall()

            if not records:
                raise Exception('no attachment records found')

            res = [
                {
                    "id": str(record[0]),
                    "name": str(record[1]),
                    "type": str(record[2]),
                    "full_path": str(record[3]),
                }
                for record in records
            ]
            
            return res
        except Exception as e:
            logger.error(f"Failed to fetch knowledge bases: {e}")
            return []

    @staticmethod
    def _sanitize_ids(ids: list) -> List[str]:
        """Filter out invalid IDs (empty strings, None, etc.) to prevent PostgreSQL UUID cast errors."""
        return [str(i) for i in ids if i and str(i).strip()] if ids else []

    def _normalize_fetch_mode(self, mode: str) -> str:
        normalized_mode = str(mode or 'sql').strip().lower()
        if normalized_mode not in {'sql', 'api'}:
            logger.warning(f"Unknown fetch mode '{mode}', fallback to 'sql'")
            return 'sql'
        return normalized_mode

    def _infer_attachment_type(self, file_name: str) -> str:
        extension = os.path.splitext(str(file_name or '').lower())[1]
        image_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tif', '.tiff', '.svg'
        }
        if extension in image_extensions:
            return 'image'
        return 'file'

    def _build_attachment_record_from_sql_row(self, record) -> dict:
        url = record[2] or ''
        storage = record[4]

        # For compatibility with public buckets: if storage exists, generate a signed URL.
        if storage and not str(url).startswith("https://noahdata.blob"):
            url = self.get_read_url(storage)

        return {
            "id": str(record[0]),
            "name": str(record[1]),
            "url": str(url or ''),
            "content": record[3] if isinstance(record[3], dict) else {},
            "storage": storage if isinstance(storage, dict) else {},
            "type": str(record[5]),
        }

    def _fetch_attachment_record_api(
        self,
        attachment_id: str,
        base_url: str,
        headers: dict,
        timeout: int = 30
    ):
        url = f"{base_url.rstrip('/')}/api/filesystem/content/"
        try:
            response = requests.get(
                url,
                headers=headers,
                params={"attachment_id": attachment_id},
                timeout=timeout,
            )
            response.raise_for_status()

            data = response.json() or {}
            attachment_type = str(data.get('type', '') or '').strip()
            if not attachment_type:
                attachment_type = self._infer_attachment_type(data.get('name', ''))

            record = {
                "id": str(data.get('attachment_id') or attachment_id),
                "name": str(data.get('name') or ''),
                "url": str(data.get('url') or ''),
                "content": data.get('content') if isinstance(data.get('content'), dict) else {},
                "storage": data.get('storage') if isinstance(data.get('storage'), dict) else {},
                "type": attachment_type,
            }

            if not record['url'] and record['storage']:
                record['url'] = self.get_read_url(record['storage'])

            return record
        except requests.RequestException:
            logger.warning(
                f"Failed to fetch attachment {attachment_id} from API: {traceback.format_exc()}"
            )
            return None

    def fetch_attachments_by_floder(
        self,
        floder_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> List[dict]:
        if not floder_id:
            return []
        
        try:
            page = max(1, int(page))
            page_size = max(1, int(page_size))
            offset = (page - 1) * page_size

            with get_connection_user() as conn:
                records = conn.execute(
                    text(
                        """SELECT id, name, url, content, storage, type
                            FROM "API_attachment"
                            WHERE parent_id = :parent_id
                              AND (is_delete = false OR is_delete IS NULL)
                            ORDER BY time_created DESC
                            LIMIT :limit OFFSET :offset"""
                    ),
                    {
                        "parent_id": floder_id,
                        "limit": page_size,
                        "offset": offset,
                    }
                ).fetchall()
            
            if not records:
                logger.info(f"No attachments found in folder {floder_id}")
                return []

            res = [self._build_attachment_record_from_sql_row(record) for record in records]
            return res
        except Exception as e:
            logger.error(f"Failed to fetch attachments by floder {floder_id}: {e}")
            return []

    def save_image(
        self,
        storage_meta: dict,
        base64_data: bytes,
    ):
        if not base64_data:
            return None
        
        storage = storage_meta.get('storage', '')

        # Only support Azure Blob for now
        if Storage.AZURE_BLOB.value == storage:
            container = storage_meta.get("container")
            blob = storage_meta.get("blob")
        
            if not (container and blob):
                logger.warning(
                    f"Invalid azure_blob meta for image: "
                    f"container={container}, blob={blob}"
                )
                return None
            
            try:
                # `upload_file` expects a file-like object with `seek`, so wrap bytes in BytesIO
                file_obj = io.BytesIO(base64_data)
                url = self.azure_blob.upload_file(
                    container=container,
                    blob=blob,
                    file_obj=file_obj,
                )
                return url

            except Exception as e:
                logger.error(f"Failed to save image: {e}")
                return None

        return None
