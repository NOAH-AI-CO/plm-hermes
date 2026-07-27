import os
import redis

from config import settings

# 允许用环境变量覆盖 Redis 地址(不改 setting_test.json 里的远端配置):
# 本地启动时设 PLM_REDIS_HOST=127.0.0.1 即用本机 redis; 不设则仍走原远端配置。
def _redis_conf():
    return (
        os.getenv("PLM_REDIS_HOST", settings.REDIS_HOST),
        int(os.getenv("PLM_REDIS_PORT", settings.REDIS_PORT)),
        int(os.getenv("PLM_REDIS_DB", settings.REDIS_ACTIVE_TASK_DB)),
    )


def get_connection(debug=False):
    global engine
    try:
        engine.ping()
        if debug: print('redis using main engine')
        return engine
    except Exception as exc:
        if debug: print('redis connect failed {exc}')
    return None


def create_engines(decode_responses=True):
    host, port, db = _redis_conf()
    engine = redis.Redis(
        host=host,
        port=port,
        db=db,
        decode_responses=decode_responses,
        socket_timeout=5,          # Socket timeout in seconds
        socket_connect_timeout=5,  # Connect timeout
        socket_keepalive=True,     # Keep connections alive
        health_check_interval=30   # Periodic health checks
    )
    return engine

engine = create_engines()
get_connection(debug=True)
print('---redis engine ready')

