from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from core.memory.normalization import (
    canonical_entity_key,
    explicit_user_rules,
    fingerprint,
    is_recurring_first_person,
    normalize_text,
    pattern_identity,
    split_sentences,
    soft_user_rules,
)
from core.memory.repositories import MemoryRepositories

logger = logging.getLogger("arya.memory")
_FIRST_PERSON = re.compile(r"\b(?:i|i['’]m|my|we|our)\b", re.I)
_FACT_PREDICATE = re.compile(
    r"\b(?:am|is|are|was|were|work|worked|live|lived|earn|earned|have|had|prefer|like|love|hate|dislike|changed|joined|left|moved|own|use|usually|often)\b",
    re.I,
)
_LOOKUP_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:find|look\s+up|search|show|tell\s+me|get|fetch|lookup)\b",
    re.I,
)


def _personal_fact_sentences(user_texts: list[str]) -> list[str]:
    facts = []
    for text in user_texts:
        for sentence in split_sentences(text):
            if (
                not _LOOKUP_REQUEST.search(sentence)
                and "?" not in sentence
                and _FIRST_PERSON.search(sentence)
                and _FACT_PREDICATE.search(sentence)
            ):
                facts.append(normalize_text(sentence))
    return facts


class MemoryService:
    def __init__(self, repositories: MemoryRepositories, vault, embed_query, *, tombstone_suppression_days: int = 90,
                 inactive_procedure_retention_days: int = 90, pattern_min_observations: int = 3,
                 pattern_min_distinct_days: int = 2):
        self.repositories = repositories
        self.vault = vault
        self.embed_query = embed_query
        self.tombstone_suppression_days = max(0, int(tombstone_suppression_days))
        self.inactive_procedure_retention_days = max(0, int(inactive_procedure_retention_days))
        self.pattern_min_observations = max(1, int(pattern_min_observations))
        self.pattern_min_distinct_days = max(1, int(pattern_min_distinct_days))

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
                f"(tool pattern: {procedure['tool_pattern'] or '*'}; "
                f"argument constraints: {json.dumps(procedure.get('argument_constraints') or [], ensure_ascii=False)})"
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
            "found_count": len(candidates),
            "found_items": candidates,
            "deleted_count": 0,
            "deleted_items": [],
            "failed_count": 0,
            "failed_items": [],
            "confirmation_required": bool(candidates),
            "will_delete": candidates,
            "message": "Review this list. Nothing has been deleted.",
        }

    async def delete_candidates(self, user_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.repositories.delete_candidates(
            self.safe_text(user_id), candidates, suppression_days=self.tombstone_suppression_days,
        )

    async def write_records(
        self,
        user_id: str,
        thread_id: str,
        records: dict[str, Any],
        *,
        user_texts: list[str] | None = None,
        override_suppression: bool = False,
        memory_management_turn: bool = False,
        observation_day: date | None = None,
    ) -> dict[str, int]:
        user_id = self.safe_text(user_id)
        user_texts = [self.safe_text(text) for text in (user_texts or [])]
        personal_fact_sentences = _personal_fact_sentences(user_texts)
        rule_records = explicit_user_rules(user_texts) + soft_user_rules(user_texts)
        entity_count = 0
        for entity in records.get("entities", []):
            key = canonical_entity_key(str(entity["key"]))
            if not key or re.search(r"(?:^|_)(?:rule|procedure|policy)(?:_|$)", key):
                continue
            value = self._safe_value(entity.get("value"))
            # Entity rows are reserved for explicit first-person facts. A lookup
            # request or returned contact detail must never become user memory.
            value_text = normalize_text(str(value)) if isinstance(value, str) else ""
            if not value_text or not any(value_text in sentence for sentence in personal_fact_sentences):
                continue
            item_fingerprint = fingerprint("entity", {"key": key, "value": value})
            if await self._is_suppressed(user_id, "entity", item_fingerprint):
                logger.info("memory_store_suppressed store=entity key=%s", key)
                continue
            await self.repositories.upsert_entity(
                user_id,
                key,
                value,
                source="conversation",
                confidence=float(entity.get("confidence", 1.0)),
            )
            entity_count += 1
        logger.info("memory_store_written store=entities count=%d", entity_count)
        procedure_count = 0
        for rule in rule_records:
            tool_pattern = rule.get("tool_pattern")
            rule_text = self.safe_text(str(rule["rule_text"]))
            severity = rule["severity"]
            constraints = self._safe_value(rule.get("argument_constraints", []))
            item_fingerprint = fingerprint("procedure", {
                "rule_text": rule_text, "tool_pattern": tool_pattern, "scope": rule.get("scope", "global"),
            })
            if not override_suppression and await self._is_suppressed(user_id, "procedure", item_fingerprint):
                logger.info("memory_store_suppressed store=procedure fingerprint=%s", item_fingerprint[:10])
                continue
            await self.repositories.add_procedure(
                user_id,
                rule_text,
                scope=str(rule.get("scope", "global")),
                tool_pattern=self.safe_text(str(tool_pattern)) if tool_pattern else None,
                severity=severity,
                confidence=float(rule.get("confidence", 1.0 if severity == "hard" else 0.3)),
                argument_constraints=constraints,
            )
            procedure_count += 1
        logger.info("memory_store_written store=procedures count=%d", procedure_count)
        episode = records.get("episode")
        episode_count = 0
        if episode:
            body = self.safe_text(str(episode.get("body", "")))
            summary = self.safe_text(str(episode.get("summary", "")))
            episode_value = {"summary": summary, "body": body}
            item_fingerprint = fingerprint("episode", episode_value)
            if await self._is_suppressed(user_id, "episode", item_fingerprint):
                logger.info("memory_store_suppressed store=episode fingerprint=%s", item_fingerprint[:10])
            else:
                vector = await self.embed_query(summary + " " + body)
                await self.repositories.add_episode(
                    user_id, self.safe_text(thread_id), summary, body, vector,
                    topics=[self.safe_text(str(item)) for item in episode.get("topics", [])],
                    tools_used=[self.safe_text(str(item)) for item in episode.get("tools_used", [])],
                )
                logger.info("memory_store_written store=episodes count=1")
                episode_count = 1
        else:
            logger.info("memory_store_written store=episodes count=0")
        pattern_count = 0
        management_text = re.compile(
            r"\b(?:forget|delete|remove|clear|erase)\b.{0,100}\b(?:memory|memories|rule|fact|pattern|preference)\b|"
            r"\b(?:remember\s+(?:this|that|it)|what\s+do\s+you\s+remember)\b",
            re.I,
        )
        may_observe_pattern = (
            not memory_management_turn
            and not rule_records
            and not any(management_text.search(text) for text in user_texts)
            and (not user_texts or any(is_recurring_first_person(text) for text in user_texts))
        )
        for pattern in records.get("patterns", []) if may_observe_pattern else []:
            text = self.safe_text(str(pattern["text"]))
            item_fingerprint = fingerprint("pattern", text)
            if await self._is_suppressed(user_id, "pattern", item_fingerprint):
                logger.info("memory_store_suppressed store=pattern fingerprint=%s", item_fingerprint[:10])
                continue
            identity = pattern_identity(text)
            observation = await self.repositories.record_pattern_observation(
                user_id, identity, text, observed_on=observation_day,
            )
            if (observation["observations"] < self.pattern_min_observations
                    or observation["days"] < self.pattern_min_distinct_days):
                logger.info(
                    "memory_pattern_observed count=%d days=%d required_count=%d required_days=%d",
                    observation["observations"], observation["days"],
                    self.pattern_min_observations, self.pattern_min_distinct_days,
                )
                continue
            vector = await self.embed_query(text)
            await self.repositories.add_pattern(
                user_id, text, vector,
                confidence=float(pattern.get("confidence", 0.5)),
                evidence_count=observation["observations"],
            )
            pattern_count += 1
        logger.info("memory_store_written store=patterns count=%d", pattern_count)
        return {
            "entities": entity_count,
            "procedures": procedure_count,
            "episodes": episode_count,
            "patterns": pattern_count,
        }

    async def _is_suppressed(self, user_id: str, store: str, item_fingerprint: str) -> bool:
        method = getattr(self.repositories, "is_suppressed", None)
        return bool(await method(user_id, store, item_fingerprint)) if method else False

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
