from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.memory.repositories import MemoryRepositories

logger = logging.getLogger("arya.memory")


class MemoryService:
    def __init__(self, repositories: MemoryRepositories, vault, embed_query):
        self.repositories = repositories
        self.vault = vault
        self.embed_query = embed_query

    def safe_text(self, text: str) -> str:
        return self.vault.tokenise(text)

    async def always_context(self, user_id: str, *, token_budget: int = 600) -> str:
        text, _ = await self.always_context_and_procedures(user_id, token_budget=token_budget)
        return text

    async def always_context_and_procedures(self, user_id: str, *, token_budget: int = 600):
        user_id = self.safe_text(user_id)
        entities, procedures = await _parallel(
            self.repositories.current_entities(user_id),
            self.repositories.active_procedures(user_id),
        )
        rows = []
        for entity in entities:
            rows.append(f"Entity {entity['key']}: {json.dumps(entity['value'], ensure_ascii=False, default=str)}")
        for procedure in procedures:
            rows.append(
                f"{procedure['severity']} procedure [{procedure['scope']}]: {procedure['rule_text']} "
                f"(tool pattern: {procedure['tool_pattern'] or '*'})"
            )
        text = "\n".join(rows)
        return text[: token_budget * 4], procedures

    async def routed_reads(self, user_id: str, reads: list[Any]) -> str:
        user_id = self.safe_text(user_id)
        tasks = []
        labels = []
        for read in reads:
            store = getattr(read, "store", None) if not isinstance(read, dict) else read.get("store")
            query = getattr(read, "query", "") if not isinstance(read, dict) else read.get("query", "")
            date = getattr(read, "date", None) if not isinstance(read, dict) else read.get("date")
            if store not in {"episode", "knowledge", "pattern"} or not query:
                continue
            query = self.safe_text(query)
            vector = await self.embed_query(query)
            if store == "episode":
                task = self.repositories.search_episodes(user_id, query, vector, date=date)
            elif store == "knowledge":
                task = self.repositories.search_knowledge(user_id, query, vector)
            else:
                task = self.repositories.search_patterns(user_id, query, vector)
            tasks.append(task)
            labels.append(store)
        if not tasks:
            return ""
        results = await _gather(tasks)
        lines = []
        for store, rows in zip(labels, results):
            for row in rows:
                text = row.get("summary") or row.get("text") or ""
                if store == "episode":
                    text = (text + " " + (row.get("body") or "")).strip()
                if store == "pattern":
                    text = f"Possible tendency (confidence {row.get('confidence', 0):.2f}): {text}"
                lines.append(f"[{store} memory, {row.get('rrf_score', 0):.3f}] {text}")
        return "\n".join(lines)

    async def search(self, user_id: str, query: str, *, date: str | None = None) -> dict[str, Any]:
        user_id = self.safe_text(user_id)
        safe_query = self.safe_text(query)
        vector = await self.embed_query(safe_query)
        episodes, knowledge, patterns = await _parallel(
            self.repositories.search_episodes(user_id, safe_query, vector, date=date),
            self.repositories.search_knowledge(user_id, safe_query, vector),
            self.repositories.search_patterns(user_id, safe_query, vector),
        )
        return {"episodes": episodes, "knowledge": knowledge, "patterns": patterns}

    async def forget(self, user_id: str, query: str, *, confirm: bool = False) -> dict[str, Any]:
        user_id = self.safe_text(user_id)
        safe_query = self.safe_text(query)
        candidates = await self.repositories.search_forget_candidates(user_id, safe_query)
        return {
            "deleted": 0,
            "confirmation_required": bool(candidates),
            "will_delete": candidates,
            "message": "Review this list. Nothing has been deleted.",
        }

    async def write_records(self, user_id: str, thread_id: str, records: dict[str, Any]) -> None:
        user_id = self.safe_text(user_id)
        entity_count = 0
        for entity in records.get("entities", []):
            await self.repositories.upsert_entity(
                user_id,
                self.safe_text(str(entity["key"])),
                self._safe_value(entity.get("value")),
                source="conversation",
                confidence=float(entity.get("confidence", 1.0)),
            )
            entity_count += 1
        logger.info("memory_store_written store=entities count=%d", entity_count)
        procedure_count = 0
        for rule in records.get("procedures", []):
            tool_pattern = rule.get("tool_pattern")
            rule_text = self.safe_text(str(rule["rule_text"]))
            severity = str(rule.get("severity", "soft")).casefold()
            if re.match(r"\s*(?:never|do not|don't)\b", rule_text, re.I):
                severity = "hard"
            await self.repositories.add_procedure(
                user_id,
                rule_text,
                scope=self.safe_text(str(rule.get("scope", "global"))),
                tool_pattern=self.safe_text(str(tool_pattern)) if tool_pattern else None,
                severity=severity,
            )
            procedure_count += 1
        logger.info("memory_store_written store=procedures count=%d", procedure_count)
        episode = records.get("episode")
        if episode:
            body = self.safe_text(str(episode.get("body", "")))
            summary = self.safe_text(str(episode.get("summary", "")))
            vector = await self.embed_query(summary + " " + body)
            await self.repositories.add_episode(
                user_id, self.safe_text(thread_id), summary, body, vector,
                topics=[self.safe_text(str(item)) for item in episode.get("topics", [])],
                tools_used=[self.safe_text(str(item)) for item in episode.get("tools_used", [])],
            )
            logger.info("memory_store_written store=episodes count=1")
        else:
            logger.info("memory_store_written store=episodes count=0")
        pattern_count = 0
        for pattern in records.get("patterns", []):
            text = self.safe_text(str(pattern["text"]))
            vector = await self.embed_query(text)
            await self.repositories.add_pattern(
                user_id, text, vector,
                confidence=float(pattern.get("confidence", 0.5)),
                evidence_count=int(pattern.get("evidence_count", 1)),
            )
            pattern_count += 1
        logger.info("memory_store_written store=patterns count=%d", pattern_count)

    async def add_knowledge(self, user_id: str, title: str, source: str, text: str, *, chunk_idx: int = 0, metadata=None):
        user_id = self.safe_text(user_id)
        safe_title = self.safe_text(title)
        safe_source = self.safe_text(source)
        safe_body = self.safe_text(text)
        vector = await self.embed_query(safe_body)
        return await self.repositories.add_knowledge_chunk(
            user_id, safe_title, safe_source, safe_body, vector,
            chunk_idx=chunk_idx,
            metadata=self._safe_value(metadata or {}),
        )

    def _safe_value(self, value):
        if isinstance(value, str):
            return self.safe_text(value)
        if isinstance(value, list):
            return [self._safe_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._safe_value(item) for key, item in value.items()}
        return value


async def _parallel(*coroutines):
    import asyncio
    return await asyncio.gather(*coroutines)


async def _gather(coroutines):
    import asyncio
    return await asyncio.gather(*coroutines)
