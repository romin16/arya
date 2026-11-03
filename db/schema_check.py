"""Plan every repository read once at startup to catch schema drift early."""
from __future__ import annotations

import re

import psycopg

from db.schema_version import MIGRATION_COMMAND

_VECTOR = "[" + ",".join("0" for _ in range(1536)) + "]"
_QUERIES: tuple[tuple[str, str, tuple], ...] = (
    ("schema version", "SELECT max(version) FROM schema_migrations", ()),
    ("PII vault lookup", "SELECT kind,value_enc FROM pii_vault WHERE token=%s", ("schema-check",)),
    ("entity read", "SELECT id,key,value,confidence,source FROM entities WHERE user_id=%s AND valid_to IS NULL ORDER BY key", ("schema-check",)),
    ("entity version lookup", "SELECT id FROM entities WHERE user_id=%s AND key=%s AND valid_to IS NULL FOR UPDATE", ("schema-check", "key")),
    ("procedure read", "SELECT id,rule_text,scope,tool_pattern,severity,confidence,argument_constraints FROM procedures WHERE user_id=%s AND active=true ORDER BY severity DESC,created_at", ("schema-check",)),
    ("procedure deduplication read", "SELECT id,severity,confidence,argument_constraints FROM procedures WHERE user_id=%s AND active=true AND lower(btrim(regexp_replace(regexp_replace(btrim(rule_text),'[^[:alnum:]_]+',' ','g'),'\\s+',' ','g')))=%s AND lower(coalesce(tool_pattern,''))=%s AND lower(btrim(coalesce(scope,'global')) )=%s FOR UPDATE", ("schema-check", "rule", "", "global")),
    ("episode vector read", "SELECT id,summary,body,ts,1-(embedding <=> %s::vector) AS score FROM episodes WHERE user_id=%s AND embedding IS NOT NULL AND (%s::date IS NULL OR ts::date=%s::date) ORDER BY embedding <=> %s::vector LIMIT %s", (_VECTOR, "schema-check", None, None, _VECTOR, 1)),
    ("episode full-text read", "SELECT id,summary,body,ts,ts_rank(tsv,plainto_tsquery('english',%s)) AS score FROM episodes WHERE user_id=%s AND tsv @@ plainto_tsquery('english',%s) AND (%s::date IS NULL OR ts::date=%s::date) ORDER BY score DESC LIMIT %s", ("query", "schema-check", "query", None, None, 1)),
    ("knowledge vector read", "SELECT id,title,text,1-(embedding <=> %s::vector) AS score FROM knowledge_chunks WHERE user_id=%s AND embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s", (_VECTOR, "schema-check", _VECTOR, 1)),
    ("knowledge full-text read", "SELECT id,title,text,ts_rank(tsv,plainto_tsquery('english',%s)) AS score FROM knowledge_chunks WHERE user_id=%s AND tsv @@ plainto_tsquery('english',%s) ORDER BY score DESC LIMIT %s", ("query", "schema-check", "query", 1)),
    ("pattern observation read", "SELECT sum(observation_count)::integer AS observations,count(*)::integer AS days FROM pattern_observations WHERE user_id=%s AND pattern_key=%s", ("schema-check", "pattern")),
    ("pattern vector read", "SELECT id,text,confidence,evidence_count,1-(embedding <=> %s::vector) AS score FROM patterns WHERE user_id=%s AND status='active' AND embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s", (_VECTOR, "schema-check", _VECTOR, 1)),
    ("pattern full-text read", "SELECT id,text,confidence,evidence_count,ts_rank(to_tsvector('english',text),plainto_tsquery('english',%s)) AS score FROM patterns WHERE user_id=%s AND status='active' AND to_tsvector('english',text) @@ plainto_tsquery('english',%s) ORDER BY score DESC LIMIT %s", ("query", "schema-check", "query", 1)),
    ("entity forget preview", "SELECT id,key AS preview FROM entities WHERE user_id=%s AND valid_to IS NULL AND (key ILIKE %s OR value::text ILIKE %s) ORDER BY id LIMIT 50", ("schema-check", "%x%", "%x%")),
    ("procedure forget preview", "SELECT id,rule_text AS preview FROM procedures WHERE user_id=%s AND active=true AND rule_text ILIKE %s ORDER BY id LIMIT 50", ("schema-check", "%x%")),
    ("pattern forget preview", "SELECT id,text AS preview FROM patterns WHERE user_id=%s AND status='active' AND text ILIKE %s ORDER BY id LIMIT 50", ("schema-check", "%x%")),
    ("episode forget preview", "SELECT id,summary AS preview FROM episodes WHERE user_id=%s AND true AND summary ILIKE %s ORDER BY id LIMIT 50", ("schema-check", "%x%")),
    ("tombstone read", "SELECT 1 FROM memory_tombstones WHERE user_id=%s AND store=%s AND fingerprint=%s AND suppressed_until>now()", ("schema-check", "entity", "fingerprint")),
    ("pending operation read", "SELECT id,user_id,thread_id,operation_type,payload,created_at,expires_at FROM pending_operations WHERE user_id=%s AND thread_id=%s", ("schema-check", "thread")),
    ("entity forget lock", "SELECT key,value FROM entities WHERE user_id=%s AND id=%s AND valid_to IS NULL FOR UPDATE", ("schema-check", 0)),
    ("procedure forget lock", "SELECT rule_text,scope,tool_pattern,argument_constraints FROM procedures WHERE user_id=%s AND id=%s AND active=true FOR UPDATE", ("schema-check", 0)),
    ("pattern forget lock", "SELECT text FROM patterns WHERE user_id=%s AND id=%s AND status='active' FOR UPDATE", ("schema-check", 0)),
    ("episode forget lock", "SELECT summary,body FROM episodes WHERE user_id=%s AND id=%s FOR UPDATE", ("schema-check", 0)),
)


async def validate_schema_reads(pool) -> None:
    """Use EXPLAIN to parse every read path without reading or changing row data."""
    try:
        async with pool.connection() as connection:
            for label, query, parameters in _QUERIES:
                await connection.execute("EXPLAIN " + query, parameters)
    except (psycopg.errors.UndefinedColumn, psycopg.errors.UndefinedTable) as exc:
        table = getattr(exc.diag, "table_name", None)
        column = getattr(exc.diag, "column_name", None)
        primary = getattr(exc.diag, "message_primary", None) or str(exc)
        relation_match = re.search(r"\bFROM\s+([a-z_][a-z0-9_]*)", query, re.IGNORECASE)
        column_match = re.search(r'column "([^"]+)" does not exist', primary)
        table = table or (relation_match.group(1) if relation_match else None)
        column = column or (column_match.group(1) if column_match else None)
        if isinstance(exc, psycopg.errors.UndefinedColumn) and table and column:
            detail = f"missing column {table}.{column}"
        elif isinstance(exc, psycopg.errors.UndefinedTable) and table:
            detail = f"missing table {table}"
        else:
            detail = primary
        raise RuntimeError(
            f"Database schema self-check failed during {label}: {detail}. "
            f"Apply database migrations with `{MIGRATION_COMMAND}` before starting core."
        ) from exc
