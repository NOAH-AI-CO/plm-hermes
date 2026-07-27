import asyncio
import logging

from sqlalchemy import create_engine, text, Connection

from config import settings

logger = logging.getLogger(__name__)

def get_connection(debug=False):
    global engine, backup_engine
    try:
        conn = engine.connect()
        if debug: print('pgtable using main engine')
    except Exception as e:
        logger.warning(f'Main engine connection failed, falling back to backup: {e}')
        conn = backup_engine.connect()
        if debug: print('pgtable using backup engine')
    return conn

def get_connection_golden():
    global golden_engine
    conn = golden_engine.connect()
    return conn

def get_connection_user():
    global user_engine
    conn = user_engine.connect()
    return conn

def create_engines():
    engine_settings = {
        'pool_size': 5,
        'max_overflow': 10,
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_timeout': 3,
        'connect_args': {"options": "-c statement_timeout=5000 -c idle_in_transaction_session_timeout=5000"}
        }
    engine = create_engine(
        settings.SQL_DB_URI,
        **engine_settings
    )
    backup_engine = create_engine(
        settings.BACKUP_DB_URI,
        **engine_settings
    )
    golden_engine = create_engine(
        settings.SQL_DB_URI_GOLDEN,
        **engine_settings
    )
    user_engine = create_engine(
        settings.SQL_DB_URI_USER,
        **engine_settings
    )
    return engine, backup_engine, golden_engine, user_engine

engine, backup_engine, golden_engine, user_engine = create_engines()
# get_connection_golden()
# print('---golden engine ready')
with get_connection(debug=True) as conn:
    pass
print('---pgtable engine ready')


async def execute_sql(sql: str, params: dict = {}):
    def _run():
        with get_connection() as conn:
            return conn.execute(text(sql), params).fetchall()
    return await asyncio.to_thread(_run)
