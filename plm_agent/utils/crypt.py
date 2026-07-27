from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag
from config import api_config
import os

SECRET_KEY_STR = api_config.get("KYBK_SECRET_KEY")

# 转换为bytes并确保32字节
SECRET_KEY = SECRET_KEY_STR.encode('utf-8')[:32].ljust(32, b'0')
assert len(SECRET_KEY) == 32, "密钥长度必须为 32 字节"


def encrypt_string(plaintext: str, key: bytes=SECRET_KEY) -> str:
    """
    加密一个字符串，并返回一个包含 Nonce, Tag, 和 Ciphertext 的单一十六进制字符串。
    """
    # 生成一个 12 字节的随机 Nonce
    nonce = os.urandom(12)
    
    # 创建 AES-GCM Cipher 对象
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    
    # 加密数据
    ciphertext = encryptor.update(plaintext.encode('utf-8')) + encryptor.finalize()
    
    # Nonce (12 bytes) + Tag (16 bytes) + Ciphertext (variable)
    encrypted_data = nonce + encryptor.tag + ciphertext
    return encrypted_data.hex()

def decrypt_string(encrypted_hex: str, key: bytes=SECRET_KEY) -> str:
    """
    从一个十六进制字符串中解密出原始字符串。
    """
    try:
        encrypted_data = bytes.fromhex(encrypted_hex)
        
        nonce = encrypted_data[:12]
        tag = encrypted_data[12:28] # 12 + 16 = 28
        ciphertext = encrypted_data[28:]
        
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        
        # 解密数据
        decrypted_bytes = decryptor.update(ciphertext) + decryptor.finalize()
        return decrypted_bytes.decode('utf-8')
        
    except (ValueError, InvalidTag, TypeError):
        return None
