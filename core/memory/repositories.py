from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb


def reciprocal_rank_fusion(*ranked_lists: list[dict[str, Any]], k: int = 60) -> list[dict[str, Any]]:
    """Merge independent ranked result sets with reciprocal rank fusion."""
    scores: dict[tuple[str, str], float] = defaultdict(float)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for result_list in ranked_lists:
        for rank, row in enumerate(result_list, start=1):
            identity = (str(row.get("store", "")), str(row.get("id", "")))
            rows[identity] = row
            scores[identity] += 1.0 / (k + rank)
    return [
        {**rows[key], "rrf_score": score}
        for key, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]


class MemoryRepositories:
    """Async PostgreSQL repositories. Callers pass PII-tokenized text only."""

    def __init__(self, pool):
        self.pool = pool

    async def current_entities(self, user_id: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id,key,value,confidence,source FROM entities WHERE user_id=%s AND valid_to IS NULL ORDER BY key",
                (user_id,),
            )
            return list(await cur.fetchall())

    async def upsert_entity(self, user_id: str, key: str, value: Any, *, source: str = "conversation", confidence: float = 1.0):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id FROM entities WHERE user_id=%s AND key=%s AND valid_to IS NULL",
                (user_id, key),
            )
            old = await cur.fetchone()
            if old:
                cur = await conn.execute(
                    "INSERT INTO entities(user_id,key,value,confidence,source) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                    (user_id, key, Jsonb(value), confidence, source),
                )
                new = await cur.fetchone()
                await conn.execute(
                    "UPDATE entities SET valid_to=now(),superseded_by=%s WHERE id=%s",
                    (new["id"], old["id"]),
                )
                return new["id"]
            cur = await conn.execute(
                "INSERT INTO entities(user_id,key,value,confidence,source) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (user_id, key, Jsonb(value), confidence, source),
            )
            return (await cur.fetchone())["id"]

    async def active_procedures(self, user_id: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id,rule_text,scope,tool_pattern,severity FROM procedures WHERE user_id=%s AND active=true ORDER BY severity DESC,created_at",
                (user_id,),
            )
            return list(await cur.fetchall())

    async def add_procedure(self, user_id: str, rule_text: str, *, scope: str = "global", tool_pattern: str | None = None, severity: str = "soft") -> int:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO procedures(user_id,rule_text,scope,tool_pattern,severity) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (user_id, rule_text, scope, tool_pattern, severity),
            )
            return (await cur.fetchone())["id"]

    async def add_episode(self, user_id: str, thread_id: str, summary: str, body: str, embedding: list[float], *, topics=None, tools_used=None):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO episodes(user_id,thread_id,summary,body,embedding,topics,tools_used) VALUES(%s,%s,%s,%s,%s::vector,%s,%s) RETURNING id",
                (user_id, thread_id, summary, body, _vector(embedding), topics or [], tools_used or []),
            )
            return (await cur.fetchone())["id"]

    async def add_knowledge_chunk(self, user_id: str, title: str, source: str, text: str, embedding: list[float], *, chunk_idx: int = 0, metadata=None):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO knowledge_docs(user_id,title,source) VALUES(%s,%s,%s) RETURNING id",
                (user_id, title, source),
            )
            doc_id = (await cur.fetchone())["id"]
            cur = await conn.execute(
                "INSERT INTO knowledge_chunks(user_id,doc_id,chunk_idx,text,embedding,metadata) VALUES(%s,%s,%s,%s,%s::vector,%s) RETURNING id",
                (user_id, doc_id, chunk_idx, text, _vector(embedding), Jsonb(metadata or {})),
            )
            return (await cur.fetchone())["id"]

    async def add_pattern(self, user_id: str, text: str, embedding: list[float], *, confidence: float, evidence_count: int = 1):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO patterns(user_id,text,embedding,confidence,evidence_count) VALUES(%s,%s,%s::vector,%s,%s) RETURNING id",
                (user_id, text, _vector(embedding), confidence, evidence_count),
            )
            return (await cur.fetchone())["id"]

    async def search_episodes(self, user_id: str, query: str, embedding: list[float], *, date: str | None = None, limit: int = 5):
        vector = _vector(embedding)
        async with self.pool.connection() as conn:
            vec = await conn.execute(
                """SELECT id,summary,body,ts,1-(embedding <=> %s::vector) AS score FROM episodes
                   WHERE user_id=%s AND embedding IS NOT NULL AND (%s::date IS NULL OR ts::date=%s::date)
                   ORDER BY embedding <=> %s::vector LIMIT %s""",
                (vector,user_id,date,date,vector,limit),
            )
            text = await conn.execute(
                """SELECT id,summary,body,ts,ts_rank(tsv,plainto_tsquery('english',%s)) AS score FROM episodes
                   WHERE user_id=%s AND tsv @@ plainto_tsquery('english',%s) AND (%s::date IS NULL OR ts::date=%s::date)
                   ORDER BY score DESC LIMIT %s""",
                (query,user_id,query,date,date,limit),
            )
            return reciprocal_rank_fusion(
                [_tag("episode", row) for row in await vec.fetchall()],
                [_tag("episode", row) for row in await text.fetchall()],
            )[:limit]

    async def search_knowledge(self, user_id: str, query: str, embedding: list[float], *, limit: int = 5):
        vector = _vector(embedding)
        async with self.pool.connection() as conn:
            vec = await conn.execute(
                """SELECT id,title,text,1-(embedding <=> %s::vector) AS score FROM knowledge_chunks
                   WHERE user_id=%s AND embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s""",
                (vector,user_id,vector,limit),
            )
            text = await conn.execute(
                """SELECT id,title,text,ts_rank(tsv,plainto_tsquery('english',%s)) AS score FROM knowledge_chunks
                   WHERE user_id=%s AND tsv @@ plainto_tsquery('english',%s) ORDER BY score DESC LIMIT %s""",
                (query,user_id,query,limit),
            )
            return reciprocal_rank_fusion(
                [_tag("knowledge", row) for row in await vec.fetchall()],
                [_tag("knowledge", row) for row in await text.fetchall()],
            )[:limit]

    async def search_patterns(self, user_id: str, query: str, embedding: list[float], *, limit: int = 5):
        vector = _vector(embedding)
        async with self.pool.connection() as conn:
            vec = await conn.execute(
                """SELECT id,text,confidence,evidence_count,1-(embedding <=> %s::vector) AS score FROM patterns
                   WHERE user_id=%s AND status='active' AND embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector LIMIT %s""",
                (vector,user_id,vector,limit),
            )
            text = await conn.execute(
                """SELECT id,text,confidence,evidence_count,ts_rank(to_tsvector('english',text),plainto_tsquery('english',%s)) AS score
                   FROM patterns WHERE user_id=%s AND status='active' AND to_tsvector('english',text) @@ plainto_tsquery('english',%s)
                   ORDER BY score DESC LIMIT %s""",
                (query,user_id,query,limit),
            )
            return reciprocal_rank_fusion(
                [_tag("pattern", row) for row in await vec.fetchall()],
                [_tag("pattern", row) for row in await text.fetchall()],
            )[:limit]

    async def search_forget_candidates(self, user_id: str, query: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            results = []
            for table, text_field, where in (
                ("entities", "key", "valid_to IS NULL"),
                ("procedures", "rule_text", "active=true"),
                ("patterns", "text", "status='active'"),
                ("episodes", "summary", "true"),
            ):
                cur = await conn.execute(
                    f"SELECT id,{text_field} AS preview FROM {table} WHERE user_id=%s AND {where} AND {text_field} ILIKE %s ORDER BY id LIMIT 50",
                    (user_id, f"%{query}%"),
                )
                results.extend({"store": table, **row} for row in await cur.fetchall())
            return results

    async def delete_candidates(self, user_id: str, candidates: list[dict[str, Any]]) -> int:
        allowed = {"entities", "procedures", "patterns", "episodes"}
        deleted = 0
        async with self.pool.connection() as conn:
            for item in candidates:
                table = item.get("store")
                if table not in allowed:
                    continue
                if table == "entities":
                    cur = await conn.execute(
                        "UPDATE entities SET valid_to=now() WHERE user_id=%s AND id=%s AND valid_to IS NULL",
                        (user_id, item["id"]),
                    )
                elif table == "procedures":
                    cur = await conn.execute("UPDATE procedures SET active=false WHERE user_id=%s AND id=%s", (user_id,item["id"]))
                elif table == "patterns":
                    cur = await conn.execute("UPDATE patterns SET status='deleted' WHERE user_id=%s AND id=%s", (user_id,item["id"]))
                else:
                    cur = await conn.execute("DELETE FROM episodes WHERE user_id=%s AND id=%s", (user_id,item["id"]))
                deleted += cur.rowcount
        return deleted

    async def consolidate(self, user_id: str):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE patterns SET confidence=GREATEST(0.05,confidence*0.98) WHERE user_id=%s AND status='active' AND last_seen < now()-interval '30 days'",
                (user_id,),
            )
            await conn.execute(
                "UPDATE patterns SET status='stale' WHERE user_id=%s AND status='active' AND confidence < 0.15",
                (user_id,),
            )


def _vector(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def _tag(store: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"store": store, **row}
