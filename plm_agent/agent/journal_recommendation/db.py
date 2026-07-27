from utils.sql_client import get_connection_user, text
import logging
import json
import asyncio
logger = logging.getLogger(__name__)


async def write_journal_recommendation_context(ctx):
    sql = text("""UPDATE "Workflow_journalrecommendation"
                SET context = CAST(:context AS jsonb), time_updated = NOW()
                WHERE id = :abstract_id""")
    
    params = {
        "abstract_id": int(ctx.abstract_id),
        "context": json.dumps({
            "processing_status": ctx.processing_status,
            "content": ctx.content,
            "abstract": ctx.abstract,
            "abstract_summary": ctx.abstract_summary,
            "url": ctx.url,
            "progress": ctx.progress,
            "status": ctx.status,
            "language": ctx.language,
            "total_journals": ctx.total_journals,
            "stats": ctx.stats,
            "error_message": ctx.error_message,
            "query_params": ctx.query_params
        }, ensure_ascii=False),
    }
    
    logger.info(f"Writing journal recommendation context for abstract_id={ctx.abstract_id}, status={ctx.status}, progress={ctx.progress}")
    
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
        logger.error(f"Failed to write journal recommendation context: {str(e)}")
        raise