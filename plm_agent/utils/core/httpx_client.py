import asyncio
import httpx
from typing import Optional

class HttpxClientSingleton:
    _async_instance: Optional[httpx.AsyncClient] = None
    _instance: Optional[httpx.Client] = None
    _initialized: bool = False

    @classmethod
    def get_client(cls) -> httpx.Client:
        if cls._instance is None:
            cls.initialize()
        return cls._instance

    @classmethod
    def get_asynclient(cls) -> httpx.AsyncClient:
        if cls._async_instance is None:
            cls.initialize()
        return cls._async_instance
    
    @classmethod
    def initialize(cls) -> None:
        # Configure timeout with separate connect and read timeouts
        timeout = httpx.Timeout(
            connect=10.0,  # Connection timeout
            read=120.0,     # Read timeout
            write=10.0,    # Write timeout
            pool=30.0      # Pool timeout
        )
            
        # Configure limits for connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
            keepalive_expiry=30.0
        )
        if not cls._initialized:            
            cls._async_instance = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                follow_redirects=True,
                max_redirects=5
            )
            cls._initialized = True
        
        if not cls._instance:
            cls._instance = httpx.Client(
                timeout=timeout,
                limits=limits,
                follow_redirects=True,
                max_redirects=5
            )

    @classmethod
    async def cleanup(cls) -> None:
        if cls._async_instance:
            await cls._async_instance.aclose()
            cls._async_instance = None
        cls._initialized = False

    @classmethod
    def reset(cls) -> None:
        """Reset the client singleton, forcing recreation on next get_asynclient() call"""
        cls.cleanup()
        cls._initialized = False
