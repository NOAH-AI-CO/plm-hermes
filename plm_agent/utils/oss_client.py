"""
阿里云 OSS (Object Storage Service) 客户端单例类
使用 oss2 包进行文件上传、下载和获取URL
"""

import oss2
import os
from typing import Optional

from config import api_config

class OSSClient:
    """
    阿里云 OSS 客户端单例类
    提供文件上传、下载、获取URL等功能
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls, access_key_id: str = None, access_key_secret: str = None, 
                endpoint: str = None, bucket_name: str = None):
        """
        单例模式实现
        
        Args:
            access_key_id: AccessKey ID（首次调用时必填）
            access_key_secret: AccessKey Secret（首次调用时必填）
            endpoint: OSS 服务端点（首次调用时必填）
            bucket_name: 存储桶名称（首次调用时必填）
        """
        if cls._instance is None:
            cls._instance = super(OSSClient, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, access_key_id: str = None, access_key_secret: str = None,
                 endpoint: str = None, bucket_name: str = None):
        """
        初始化 OSS 客户端（只初始化一次）
        
        Args:
            access_key_id: AccessKey ID
            access_key_secret: AccessKey Secret
            endpoint: OSS 服务端点（如：oss-cn-hangzhou.aliyuncs.com）
            bucket_name: 存储桶名称
        """
        if not self._initialized:
            if not all([access_key_id, access_key_secret, endpoint, bucket_name]):
                raise ValueError("首次初始化时必须提供所有参数：access_key_id, access_key_secret, endpoint, bucket_name")
            
            self.access_key_id = access_key_id
            self.access_key_secret = access_key_secret
            self.endpoint = endpoint
            self.bucket_name = bucket_name
            
            # 创建认证对象
            auth = oss2.Auth(access_key_id, access_key_secret)
            
            # 创建 Bucket 对象
            self.bucket = oss2.Bucket(auth, f'https://{endpoint}', bucket_name)
            
            self._initialized = True
    
    # ========== 1. 上传文件 ==========
    def upload_file(self, local_file_path: str, oss_object_key: str) -> bool:
        """
        上传本地文件到 OSS
        
        Args:
            local_file_path: 本地文件路径
            oss_object_key: OSS 中的对象键（文件路径）
        
        Returns:
            bool: 上传是否成功
        """
        try:
            # 检查本地文件是否存在
            if not os.path.exists(local_file_path):
                print(f"错误：本地文件不存在: {local_file_path}")
                return False
            
            # 上传文件
            with open(local_file_path, 'rb') as file_obj:
                result = self.bucket.put_object(oss_object_key, file_obj)
            
            if result.status == 200:
                print(f"✓ 文件上传成功: {oss_object_key}")
                return True
            else:
                print(f"✗ 文件上传失败，状态码: {result.status}")
                return False
                
        except Exception as e:
            print(f"✗ 上传文件时发生错误: {str(e)}")
            return False
    
    def upload_file_with_progress(self, local_file_path: str, oss_object_key: str):
        """
        上传文件（带进度显示）
        
        Args:
            local_file_path: 本地文件路径
            oss_object_key: OSS 中的对象键
        """
        try:
            # 使用分片上传（适合大文件）
            total_size = os.path.getsize(local_file_path)
            
            def progress_callback(consumed_bytes, total_bytes):
                if total_bytes:
                    percent = int(100 * consumed_bytes / total_bytes)
                    print(f'\r上传进度: {percent}% ({consumed_bytes}/{total_bytes} bytes)', end='', flush=True)
            
            # 分片上传
            oss2.resumable_upload(
                self.bucket, 
                oss_object_key, 
                local_file_path,
                progress_callback=progress_callback,
                num_threads=4  # 并发线程数
            )
            print(f"\n✓ 文件上传成功: {oss_object_key}")
            
        except Exception as e:
            print(f"\n✗ 上传文件时发生错误: {str(e)}")
    
    # ========== 2. 下载文件 ==========
    def download_file(self, oss_object_key: str, local_file_path: str) -> bool:
        """
        从 OSS 下载文件到本地
        
        Args:
            oss_object_key: OSS 中的对象键
            local_file_path: 本地保存路径
        
        Returns:
            bool: 下载是否成功
        """
        try:
            # 检查 OSS 对象是否存在
            if not self.bucket.object_exists(oss_object_key):
                print(f"错误：OSS 对象不存在: {oss_object_key}")
                return False
            
            # 创建本地目录（如果不存在）
            local_dir = os.path.dirname(local_file_path)
            if local_dir and not os.path.exists(local_dir):
                os.makedirs(local_dir, exist_ok=True)
            
            # 下载文件
            self.bucket.get_object_to_file(oss_object_key, local_file_path)
            
            print(f"✓ 文件下载成功: {local_file_path}")
            return True
            
        except Exception as e:
            print(f"✗ 下载文件时发生错误: {str(e)}")
            return False
    
    def download_file_stream(self, oss_object_key: str) -> bytes:
        """
        从 OSS 下载文件到内存（返回字节流）
        
        Args:
            oss_object_key: OSS 中的对象键
        
        Returns:
            bytes: 文件内容（字节流）
        """
        try:
            result = self.bucket.get_object(oss_object_key)
            content = result.read()
            print(f"✓ 文件读取成功: {oss_object_key}, 大小: {len(content)} bytes")
            return content
        except Exception as e:
            print(f"✗ 读取文件时发生错误: {str(e)}")
            return b''
    
    # ========== 3. 上传文件并获取 URL ==========
    def upload_file_and_get_url(self, local_file_path: str, oss_object_key: str, 
                                expires: int = 3600) -> Optional[str]:
        """
        上传文件并获取访问 URL
        
        Args:
            local_file_path: 本地文件路径
            oss_object_key: OSS 中的对象键
            expires: URL 过期时间（秒），默认 3600 秒（1小时）
                    如果设置为 None，则返回永久 URL（需要设置 Bucket 为公共读）
        
        Returns:
            str: 文件的访问 URL，失败返回 None
        """
        try:
            # 先上传文件
            if not self.upload_file(local_file_path, oss_object_key):
                return None
            
            # 获取文件的访问 URL
            if expires:
                # 生成带签名的临时 URL（推荐，更安全）
                url = self.bucket.sign_url('GET', oss_object_key, expires)
                print(f"✓ 临时访问 URL（有效期 {expires} 秒）: {url}")
            else:
                # 生成永久 URL（需要 Bucket 设置为公共读）
                url = f"https://{self.bucket_name}.{self.endpoint}/{oss_object_key}"
                print(f"✓ 永久访问 URL: {url}")
            
            return url
            
        except Exception as e:
            print(f"✗ 获取 URL 时发生错误: {str(e)}")
            return None

    def upload_string(self, content: str, oss_object_key: str, encoding: str = 'utf-8', content_type: str = '') -> bool:
        """
        将字符串内容上传到 OSS
        
        Args:
            content: 要上传的字符串内容
            oss_object_key: OSS 中的对象键（文件路径）
            encoding: 字符串编码方式，默认 'utf-8'
            content_type: 内容类型，默认 '', 可选 'text/plain', 'text/markdown', 'text/html', 'application/pdf', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        Returns:
            bool: 上传是否成功
        """
        try:
            # 将字符串转换为字节流
            content_bytes = content.encode(encoding)

            if content_type:
                headers = {}
                if 'charset=' not in content_type.lower():
                    content_type = f'{content_type}; charset={encoding}'
                    headers['Content-Type'] = content_type
                result = self.bucket.put_object(oss_object_key, content_bytes, headers=headers)
            else:
                result = self.bucket.put_object(oss_object_key, content_bytes)
            
            if result.status == 200:
                print(f"✓ 字符串上传成功: {oss_object_key} (大小: {len(content_bytes)} bytes)")
                return True
            else:
                print(f"✗ 字符串上传失败，状态码: {result.status}")
                return False
                
        except Exception as e:
            print(f"✗ 上传字符串时发生错误: {str(e)}")
            return False
    
    def get_file_url(self, oss_object_key: str, expires: int = 3600) -> Optional[str]:
        """
        获取已存在文件的访问 URL（不上传）
        
        Args:
            oss_object_key: OSS 中的对象键
            expires: URL 过期时间（秒），默认 3600 秒
        
        Returns:
            str: 文件的访问 URL，失败返回 None
        """
        try:
            # 检查文件是否存在
            if not self.bucket.object_exists(oss_object_key):
                print(f"错误：OSS 对象不存在: {oss_object_key}")
                return None
            
            # 生成带签名的临时 URL
            url = self.bucket.sign_url('GET', oss_object_key, expires)
            print(f"✓ 临时访问 URL（有效期 {expires} 秒）: {url}")
            return url
            
        except Exception as e:
            print(f"✗ 获取 URL 时发生错误: {str(e)}")
            return None

    
    def list_files(self, prefix: str = '', max_keys: int = 100):
        """
        列出 OSS 中的文件
        
        Args:
            prefix: 文件前缀（可选，用于过滤）
            max_keys: 最大返回数量
        """
        try:
            print(f"\n列出文件（前缀: '{prefix}'）:")
            for obj in oss2.ObjectIterator(self.bucket, prefix=prefix, max_keys=max_keys):
                print(f"  - {obj.key} ({obj.size} bytes, {obj.last_modified})")
        except Exception as e:
            print(f"✗ 列出文件时发生错误: {str(e)}")
    
    def delete_file(self, oss_object_key: str) -> bool:
        """
        删除 OSS 中的文件
        
        Args:
            oss_object_key: OSS 中的对象键
        
        Returns:
            bool: 删除是否成功
        """
        try:
            self.bucket.delete_object(oss_object_key)
            print(f"✓ 文件删除成功: {oss_object_key}")
            return True
        except Exception as e:
            print(f"✗ 删除文件时发生错误: {str(e)}")
            return False
    
    def check_file_exists(self, oss_object_key: str) -> bool:
        """
        检查文件是否存在
        
        Args:
            oss_object_key: OSS 中的对象键
        
        Returns:
            bool: 文件是否存在
        """
        exists = self.bucket.object_exists(oss_object_key)
        print(f"文件 '{oss_object_key}' {'存在' if exists else '不存在'}")
        return exists


oss_singleton_client = OSSClient(access_key_id=api_config.KYBK_ACCESS_KEY_ID, access_key_secret=api_config.KYBK_ACCESS_KEY_SECRET, endpoint=api_config.KYBK_ENDPOINT, bucket_name=api_config.KYBK_BUCKET_NAME)