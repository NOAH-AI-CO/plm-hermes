"""
翻译任务 DB 写回（与 BP 一致：Agent 直连 Backend 同库，写 TranslationTask + API_attachment）。
供 process_translation_by_attachment_id 在翻译完成后调用，不依赖 HTTP 回调。
后续可在 context 中扩展已翻译页数等进度信息，前端用 task_id 查询。
"""
import json
import logging
import uuid

from utils.sql_client import get_connection_user, text

logger = logging.getLogger(__name__)


def read_translation_task(task_id: int) -> dict | None:
    """读取翻译任务，获取 owner_id 等，供写回译文时使用。"""
    sql = text(
        """SELECT id, owner_id, name, status, original_attachment_id, target_language, input_language, context
           FROM "Workflow_translationtask" WHERE id = :task_id"""
    )
    try:
        with get_connection_user() as conn:
            row = conn.execute(sql, {"task_id": task_id}).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "owner_id": row[1],
            "name": row[2],
            "status": row[3],
            "original_attachment_id": row[4],
            "target_language": row[5],
            "input_language": row[6],
            "context": row[7] or {},
        }
    except Exception as e:
        logger.error(f"read_translation_task failed: {e}")
        raise


def azure_blob_attachment_storage(container: str, blob: str) -> dict:
    """与 Backend API 上传一致，供 AttachmentSerializer 按 container/blob 刷新 SAS。"""
    return {
        "storage": "azure_blob",
        "container": container,
        "blob": blob,
    }


def create_attachment_for_translation(
    owner_id: int,
    name: str,
    url: str,
    *,
    storage: dict | None = None,
) -> str:
    """
    在 Backend 同库的 API_attachment 中插入译文记录，返回 attachment id (UUID)。
    与 BP 直写 DB 方式一致，不经过 HTTP。

    :param storage: 若为 Azure 译文，请传入 container/blob（见 azure_blob_attachment_storage），
        否则 AttachmentSerializer 只会返回写入时的 SAS，易过期。
    """
    attachment_id = str(uuid.uuid4())
    storage_payload = storage if storage is not None else {}
    sql = text(
        """INSERT INTO "API_attachment"
           (id, name, owner_id, hash, content, type, url, storage, parent_id, full_path, file_properties, is_delete, time_created, time_updated)
           VALUES (:id, :name, :owner_id, '', '{}'::jsonb, 'file', :url, CAST(:storage AS jsonb), NULL, :full_path, '{}'::jsonb, false, NOW(), NOW())"""
    )
    params = {
        "id": attachment_id,
        "name": name,
        "owner_id": owner_id,
        "url": url,
        "full_path": name,
        "storage": json.dumps(storage_payload, ensure_ascii=False),
    }
    try:
        with get_connection_user() as conn:
            conn.execute(sql, params)
            conn.commit()
        return attachment_id
    except Exception as e:
        logger.error(f"create_attachment_for_translation failed: {e}")
        raise


def write_translation_result(
    task_id: int,
    status: str,
    *,
    translated_attachment_id: str | None = None,
    context_extra: dict | None = None,
) -> None:
    """
    更新翻译任务状态与结果（与 write_bp_context 类似）。
    context_extra 会合并进 context，后续可在此扩展已翻译页数等进度。
    """
    updates = ["status = :status", "time_updated = NOW()"]
    params = {"task_id": task_id, "status": status}
    if translated_attachment_id is not None:
        updates.append("translated_attachment_id = :translated_attachment_id")
        params["translated_attachment_id"] = translated_attachment_id
    if context_extra is not None:
        # 合并到现有 context，与 BP 的 COALESCE(context,'{}') || CAST(:context AS jsonb) 一致
        updates.append("context = COALESCE(context, '{}'::jsonb) || CAST(:context_extra AS jsonb)")
        params["context_extra"] = json.dumps(context_extra, ensure_ascii=False)
    sql = text(
        f"""UPDATE "Workflow_translationtask" SET {', '.join(updates)} WHERE id = :task_id"""
    )
    try:
        with get_connection_user() as conn:
            conn.execute(sql, params)
            conn.commit()
    except Exception as e:
        logger.error(f"write_translation_result failed: {e}")
        raise


def write_original_pages_context(task_id: int, original_pages: list) -> None:
    """
    将已渲染完成的原文件逐页 JPG URL 列表写入 context.original_pages，不修改任务状态。
    每次调用传入当前已完成的完整列表（包含之前所有页），由调用方维护累积。
    """
    sql = text(
        """UPDATE "Workflow_translationtask"
           SET context = COALESCE(context, '{}'::jsonb) || CAST(:context_extra AS jsonb),
               time_updated = NOW()
           WHERE id = :task_id"""
    )
    try:
        with get_connection_user() as conn:
            conn.execute(sql, {
                "task_id": task_id,
                "context_extra": json.dumps({"original_pages": original_pages}, ensure_ascii=False),
            })
            conn.commit()
    except Exception as e:
        logger.warning(f"write_original_pages_context failed (task_id={task_id}): {e}")


def write_translation_task_page(task_id: int, page_index: int, url: str) -> None:
    """
    PDF 逐页渲染：每译完一页插入一条 TranslationTaskPage。
    Agent 直连 Backend 同库写入，仅 PDF 翻译流程调用。
    """
    select_sql = text(
        """SELECT url FROM "Workflow_translationtaskpage"
           WHERE task_id = :task_id AND page_index = :page_index"""
    )
    upsert_sql = text(
        """INSERT INTO "Workflow_translationtaskpage" (task_id, page_index, url, time_created)
           VALUES (:task_id, :page_index, :url, NOW())
           ON CONFLICT (task_id, page_index)
           DO UPDATE SET url = EXCLUDED.url"""
    )
    params = {"task_id": task_id, "page_index": page_index, "url": url}
    try:
        with get_connection_user() as conn:
            old_row = conn.execute(select_sql, params).fetchone()
            old_url = old_row[0] if old_row else None
            conn.execute(upsert_sql, params)
            conn.commit()
            if old_url and old_url != url:
                print(
                    f"[TranslationTaskPage] page url updated: task_id={task_id}, "
                    f"page={page_index}, old_url={old_url}, new_url={url}"
                )
    except Exception as e:
        logger.warning(f"write_translation_task_page failed (task_id={task_id}, page={page_index}): {e}")
