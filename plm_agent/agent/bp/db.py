from utils.sql_client import get_connection_user, text
import logging
import json
import asyncio

logger = logging.getLogger(__name__)

async def write_bp_context(ctx, bp_id):
    ctx.pop('company_name', None)
    sql = text("""UPDATE "Workflow_bptask"
                SET context = COALESCE(context, '{}'::jsonb) || CAST(:context AS jsonb), time_updated = NOW()
                WHERE id = :bp_id""")
    params = {
        "bp_id": int(bp_id),
        "context": json.dumps(ctx, ensure_ascii=False),
    }
    # logger.info("params", params)

    def do_write():
        with get_connection_user() as conn:
            conn.execute(sql, params)
            conn.commit()

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, do_write)
    except (OSError, IOError) as e:
        logger.warning(f"Database write failed with I/O error: {str(e)}, will retry")
        await asyncio.sleep(0.5)
        await loop.run_in_executor(None, do_write)
    except Exception as e:
        logger.error(f"Failed to write BP context: {str(e)}")
        raise


async def read_bp_context(bp_id):
    sql = text("""SELECT context FROM "Workflow_bptask"
                WHERE id = :bp_id""")
    params = {"bp_id": int(bp_id)}
    
    def do_read():
        with get_connection_user() as conn:
            result = conn.execute(sql, params)
            row = result.fetchone()
            if row and row[0]:
                return row[0]
            return {}

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, do_read)
    except (OSError, IOError) as e:
        logger.warning(f"Database read failed with I/O error: {str(e)}, will retry")
        await asyncio.sleep(0.5)
        return await loop.run_in_executor(None, do_read)
    except Exception as e:
        logger.error(f"Failed to read BP context: {str(e)}")
        raise
    
