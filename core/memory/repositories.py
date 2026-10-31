from __future__ import annotations

from collections import defaultdict
import json
import logging
from typing import Any

from psycopg.types.json import Jsonb
from core.memory.normalization import fingerprint, normalize_text, parse_explicit_rule

logger = logging.getLogger("arya.memory")


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
            async with conn.transaction():
                cur = await conn.execute(
                    "SELECT id FROM entities WHERE user_id=%s AND key=%s AND valid_to IS NULL FOR UPDATE",
                    (user_id, key),
                )
                old = await cur.fetchone()
                if old:
                    # Close the current version before inserting to satisfy the
                    # partial unique index; link it after the new id is known.
                    await conn.execute(
                        "UPDATE entities SET valid_to=now(),superseded_by=NULL WHERE id=%s",
                        (old["id"],),
                    )
                cur = await conn.execute(
                    "INSERT INTO entities(user_id,key,value,confidence,source) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                    (user_id, key, Jsonb(value), confidence, source),
                )
                new = await cur.fetchone()
                if old:
                    await conn.execute(
                        "UPDATE entities SET superseded_by=%s WHERE id=%s",
                        (new["id"], old["id"]),
                    )
                return new["id"]

    async def active_procedures(self, user_id: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id,rule_text,scope,tool_pattern,severity,confidence,argument_constraints FROM procedures WHERE user_id=%s AND active=true ORDER BY severity DESC,created_at",
                (user_id,),
            )
            rows = list(await cur.fetchall())
            for row in rows:
                if not row.get("tool_pattern"):
                    derived = parse_explicit_rule(row["rule_text"])
                    if derived and (derived.get("tool_pattern") or derived.get("argument_constraints")):
                        row["tool_pattern"] = derived.get("tool_pattern")
                        row["argument_constraints"] = derived.get("argument_constraints", [])
                        await conn.execute(
                            "UPDATE procedures SET tool_pattern=%s,argument_constraints=%s WHERE id=%s",
                            (row["tool_pattern"], Jsonb(row["argument_constraints"]), row["id"]),
                        )
            return rows

    async def add_procedure(
        self,
        user_id: str,
        rule_text: str,
        *,
        scope: str = "global",
        tool_pattern: str | None = None,
        severity: str = "soft",
        confidence: float = 0.3,
        argument_constraints: list[dict[str, str]] | None = None,
    ) -> int:
        normalized_rule = normalize_text(rule_text)
        normalized_pattern = normalize_text(tool_pattern or "")
        normalized_scope = normalize_text(scope or "global")
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))",
                    (user_id, normalized_rule + "|" + normalized_pattern + "|" + normalized_scope),
                )
                cur = await conn.execute(
                    """SELECT id,severity,confidence,argument_constraints FROM procedures
                       WHERE user_id=%s AND active=true
                         AND lower(btrim(regexp_replace(regexp_replace(btrim(rule_text),'[^[:alnum:]_]+',' ','g'),'\\s+',' ','g')))=%s
                         AND lower(coalesce(tool_pattern,''))=%s AND lower(btrim(coalesce(scope,'global')) )=%s
                       FOR UPDATE""",
                    (user_id, normalized_rule, normalized_pattern, normalized_scope),
                )
                existing = await cur.fetchone()
                constraints = argument_constraints or []
                if existing:
                    merged = list(existing.get("argument_constraints") or [])
                    known = {json.dumps(item, sort_keys=True) for item in merged}
                    merged.extend(item for item in constraints if json.dumps(item, sort_keys=True) not in known)
                    chosen_severity = "hard" if "hard" in {severity, existing["severity"]} else "soft"
                    await conn.execute(
                        """UPDATE procedures SET severity=%s,confidence=GREATEST(confidence,%s),argument_constraints=%s
                           WHERE id=%s""",
                        (chosen_severity, confidence, Jsonb(merged), existing["id"]),
                    )
                    return existing["id"]
                cur = await conn.execute(
                    """INSERT INTO procedures(user_id,rule_text,scope,tool_pattern,severity,confidence,argument_constraints)
                       VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (user_id, rule_text, scope, tool_pattern, severity, confidence, Jsonb(constraints)),
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
                if table == "entities":
                    cur = await conn.execute(
                        """SELECT id,key AS preview FROM entities WHERE user_id=%s AND valid_to IS NULL
                           AND (key ILIKE %s OR value::text ILIKE %s) ORDER BY id LIMIT 50""",
                        (user_id, f"%{query}%", f"%{query}%"),
                    )
                else:
                    cur = await conn.execute(
                        f"SELECT id,{text_field} AS preview FROM {table} WHERE user_id=%s AND {where} AND {text_field} ILIKE %s ORDER BY id LIMIT 50",
                        (user_id, f"%{query}%"),
                    )
                results.extend({"store": table, **row} for row in await cur.fetchall())
            return results

    async def is_suppressed(self, user_id: str, store: str, item_fingerprint: str) -> bool:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM memory_tombstones WHERE user_id=%s AND store=%s AND fingerprint=%s AND suppressed_until>now()",
                (user_id, store, item_fingerprint),
            )
            return await cur.fetchone() is not None

    async def delete_candidates(self, user_id: str, candidates: list[dict[str, Any]], *, suppression_days: int = 90) -> dict[str, Any]:
        allowed = {"entities", "procedures", "patterns", "episodes"}
        deleted_items: list[dict[str, Any]] = []
        failed_items: list[dict[str, Any]] = []
        counts: dict[str, int] = defaultdict(int)
        async with self.pool.connection() as conn:
            for item in candidates:
                table = item.get("store")
                if table not in allowed:
                    failed_items.append({**item, "reason": "unsupported memory store"})
                    continue
                try:
                    async with conn.transaction():
                        if table == "entities":
                            cur = await conn.execute(
                                "SELECT key,value FROM entities WHERE user_id=%s AND id=%s AND valid_to IS NULL FOR UPDATE",
                                (user_id, item["id"]),
                            )
                        elif table == "procedures":
                            cur = await conn.execute(
                                "SELECT rule_text,scope,tool_pattern,argument_constraints FROM procedures WHERE user_id=%s AND id=%s AND active=true FOR UPDATE",
                                (user_id, item["id"]),
                            )
                        elif table == "patterns":
                            cur = await conn.execute(
                                "SELECT text FROM patterns WHERE user_id=%s AND id=%s AND status='active' FOR UPDATE",
                                (user_id, item["id"]),
                            )
                        else:
                            cur = await conn.execute(
                                "SELECT summary,body FROM episodes WHERE user_id=%s AND id=%s FOR UPDATE",
                                (user_id, item["id"]),
                            )
                        record = await cur.fetchone()
                        if record is None:
                            failed_items.append({**item, "reason": "item no longer exists"})
                            continue
                        singular = {"entities": "entity", "procedures": "procedure", "patterns": "pattern", "episodes": "episode"}[table]
                        if table == "entities":
                            payload = {"key": record["key"], "value": record["value"]}
                            normalized_content = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                        elif table == "procedures":
                            payload = {key: record[key] for key in ("rule_text", "scope", "tool_pattern", "argument_constraints")}
                            normalized_content = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                        elif table == "patterns":
                            payload = record["text"]
                            normalized_content = payload
                        else:
                            payload = {"summary": record["summary"], "body": record["body"]}
                            normalized_content = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                        item_fingerprint = fingerprint(singular, payload)
                        await conn.execute(
                            """INSERT INTO memory_tombstones(user_id,store,fingerprint,normalized_content,suppressed_until)
                               VALUES(%s,%s,%s,%s,now()+(%s*interval '1 day'))
                               ON CONFLICT(user_id,store,fingerprint) DO UPDATE
                               SET normalized_content=EXCLUDED.normalized_content,
                                   suppressed_until=GREATEST(memory_tombstones.suppressed_until,EXCLUDED.suppressed_until)""",
                            (user_id, singular, item_fingerprint, normalized_content, suppression_days),
                        )
                        if table == "entities":
                            cur = await conn.execute("UPDATE entities SET valid_to=now() WHERE user_id=%s AND id=%s AND valid_to IS NULL", (user_id, item["id"]))
                        elif table == "procedures":
                            cur = await conn.execute("UPDATE procedures SET active=false WHERE user_id=%s AND id=%s AND active=true", (user_id, item["id"]))
                        elif table == "patterns":
                            cur = await conn.execute("UPDATE patterns SET status='deleted' WHERE user_id=%s AND id=%s AND status='active'", (user_id, item["id"]))
                        else:
                            cur = await conn.execute("DELETE FROM episodes WHERE user_id=%s AND id=%s", (user_id, item["id"]))
                        if cur.rowcount != 1:
                            raise RuntimeError("delete did not affect exactly one row")
                    deleted_items.append(item)
                    counts[table] += 1
                except Exception as exc:
                    logger.exception("memory_forget_delete_failed store=%s id=%s", table, item.get("id"))
                    failed_items.append({**item, "reason": f"delete failed ({type(exc).__name__})"})
        return {
            "found_count": len(candidates),
            "found_items": candidates,
            "deleted_count": len(deleted_items),
            "deleted_items": deleted_items,
            "failed_count": len(failed_items),
            "failed_items": failed_items,
            "counts_by_store": dict(counts),
        }

    async def consolidate(self, user_id: str):
        async with self.pool.connection() as conn:
            await conn.execute(
                """WITH ranked AS (
                     SELECT id, first_value(id) OVER (PARTITION BY lower(trim(key)) ORDER BY valid_from DESC,id DESC) AS keeper
                     FROM entities WHERE user_id=%s AND valid_to IS NULL
                   )
                   UPDATE entities AS e SET valid_to=now(),superseded_by=r.keeper
                   FROM ranked r WHERE e.id=r.id AND r.id<>r.keeper""",
                (user_id,),
            )
            # Keep the strongest active representative for duplicate patterns and
            # fold the duplicate evidence into it before marking the rest merged.
            await conn.execute(
                """WITH ranked AS (
                     SELECT id, first_value(id) OVER (PARTITION BY lower(trim(text)) ORDER BY confidence DESC, evidence_count DESC, id) AS keeper,
                            sum(evidence_count) OVER (PARTITION BY lower(trim(text))) AS evidence,
                            max(confidence) OVER (PARTITION BY lower(trim(text))) AS confidence
                     FROM patterns WHERE user_id=%s AND status='active'
                   ), keepers AS (
                     UPDATE patterns AS p SET evidence_count=r.evidence, confidence=r.confidence, last_seen=now()
                     FROM ranked r WHERE p.id=r.keeper AND p.status='active' RETURNING p.id
                   )
                   UPDATE patterns AS p SET status='merged'
                   FROM ranked r WHERE p.id=r.id AND r.id<>r.keeper""",
                (user_id,),
            )
            await conn.execute(
                "UPDATE patterns SET confidence=GREATEST(0.05,confidence*0.98) WHERE user_id=%s AND status='active' AND last_seen < now()-interval '30 days'",
                (user_id,),
            )
            await conn.execute(
                "UPDATE patterns SET status='stale' WHERE user_id=%s AND status='active' AND confidence < 0.15",
                (user_id,),
            )
            # Compact older episodic threads into a stable summary column before
            # keeping their full body available for hybrid retrieval.
            await conn.execute(
                """UPDATE episodes SET summary=left(coalesce(nullif(summary,''),body,''),1200)
                   WHERE user_id=%s AND ts < now()-interval '90 days'
                     AND coalesce(summary,'')='' AND coalesce(body,'')<>''""",
                (user_id,),
            )
            await conn.execute(
                """WITH thread_summaries AS (
                     SELECT thread_id, max(id) AS latest_id,
                            left(string_agg(coalesce(nullif(summary,''),body,''), E'\\n' ORDER BY ts),1200) AS summary
                     FROM episodes WHERE user_id=%s AND thread_id IS NOT NULL
                       AND ts < now()-interval '90 days'
                     GROUP BY thread_id
                   )
                   UPDATE episodes AS e SET summary=s.summary
                   FROM thread_summaries s WHERE e.id=s.latest_id""",
                (user_id,),
            )


def _vector(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def _tag(store: str, row: dict[str, Any]) -> dict[str, Any]:
    return {"store": store, **row}
