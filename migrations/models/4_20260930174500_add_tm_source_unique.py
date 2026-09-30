from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
DELETE FROM translation_memory_entry_sources a
USING translation_memory_entry_sources b
WHERE a.id > b.id
  AND a.entry_id = b.entry_id
  AND a.user_id IS NOT DISTINCT FROM b.user_id
  AND a.project_id IS NOT DISTINCT FROM b.project_id
  AND a.document_id IS NOT DISTINCT FROM b.document_id
  AND a.segment_id IS NOT DISTINCT FROM b.segment_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tm_source_provenance
ON translation_memory_entry_sources (entry_id, user_id, project_id, document_id, segment_id);
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return "DROP INDEX IF EXISTS uq_tm_source_provenance;"
