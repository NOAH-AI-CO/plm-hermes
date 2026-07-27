# -*- coding: utf-8 -*-
from typing import Any

class AsyncLlmSDKSingleton:

    _instances: dict[Any, Any] = dict()

    @classmethod
    def make_key(cls, client, **kwargs):
        return client.__name__, tuple(sorted(kwargs.items()))

    @classmethod
    def get_client(cls, client, **kwargs):
        key = cls.make_key(client=client, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = cls.initialize(client=client, **kwargs)
        return cls._instances[key]
    
    @classmethod
    def initialize(cls, client, **kwargs):
        key = cls.make_key(client=client, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = client(**kwargs)
        return cls._instances[key]

    @classmethod
    async def cleanup(cls, client, **kwargs) -> None:
        key = cls.make_key(client=client, **kwargs)
        if key in cls._instances:
            cls._instances[key].close()
            del cls._instances[key]

    @classmethod
    async def cleanup_all(cls) -> None:
        """Clean up all singleton instances. Call once during shutdown."""
        for key in list(cls._instances.keys()):
            try:
                await cls._instances[key].close()
            except Exception:
                pass
        cls._instances.clear()
