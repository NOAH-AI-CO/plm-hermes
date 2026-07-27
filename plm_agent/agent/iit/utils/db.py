from utils.sql_client import get_connection_user, text
import logging
import json
import asyncio

logger = logging.getLogger(__name__)

async def write_iit_context(ctx):
    sql = text("""UPDATE "Workflow_iitreview"
                SET context = CAST(:context AS jsonb), time_updated = NOW()
                WHERE id = :iit_id""")
    params = {
        "iit_id": int(ctx.iit_id),
        "context": json.dumps({
            "processing_status": ctx.processing_status,
            "content": ctx.content,
            "queries": ctx.queries,
            "html": ctx.queries,
            "url": ctx.url,
            "title": ctx.title,
            "category": ctx.category,
            "progress": ctx.progress,
            "status": ctx.status
        }, ensure_ascii=False),
    }
    # logger.info("params", params)
    def _write():
        with get_connection_user() as conn:
            conn.execute(sql, params)
            conn.commit()

    try:
        await asyncio.to_thread(_write)
    except (OSError, IOError) as e:
        logger.warning(f"Database write failed with I/O error: {str(e)}, will retry")
        await asyncio.sleep(0.5)
        await asyncio.to_thread(_write)
    except Exception as e:
        logger.error(f"Failed to write IIT context: {str(e)}")
        raise