import pytest
from cryptography.fernet import Fernet

from core.memory.repositories import reciprocal_rank_fusion
from core.memory.service import MemoryService
from core.pii.vault import PIIVault


def test_reciprocal_rank_fusion_merges_vector_and_full_text_rankings():
    merged = reciprocal_rank_fusion(
        [{"store": "episode", "id": 1, "summary": "same"}, {"store": "episode", "id": 2}],
        [{"store": "episode", "id": 1, "summary": "same"}, {"store": "episode", "id": 3}],
    )
    assert merged[0]["id"] == 1
    assert merged[0]["rrf_score"] > merged[1]["rrf_score"]
    assert {row["id"] for row in merged} == {1, 2, 3}


@pytest.mark.asyncio
async def test_memory_search_tokenizes_before_embedding():
    class Repo:
        async def search_episodes(self, *args, **kwargs):
            return []

        async def search_knowledge(self, *args, **kwargs):
            return []

        async def search_patterns(self, *args, **kwargs):
            return []

    raw = "person@arya.dev"
    vault = PIIVault(b"memory-test-hmac", Fernet.generate_key())
    embedded = []

    async def embed_query(text):
        embedded.append(text)
        return [0.0, 1.0]

    memory = MemoryService(Repo(), vault, embed_query)
    await memory.search("user", raw)
    assert raw not in embedded[0]
    assert "[EMAIL_" in embedded[0]


@pytest.mark.asyncio
async def test_memory_write_tokenizes_user_thread_and_every_value_before_storage_or_embedding():
    raw = "person@arya.dev"
    vault = PIIVault(b"memory-write-hmac", Fernet.generate_key())
    calls = []
    embedded = []

    class Repo:
        async def upsert_entity(self, *args, **kwargs):
            calls.append(("entity", args, kwargs))

        async def add_procedure(self, *args, **kwargs):
            calls.append(("procedure", args, kwargs))

        async def add_episode(self, *args, **kwargs):
            calls.append(("episode", args, kwargs))

        async def add_pattern(self, *args, **kwargs):
            calls.append(("pattern", args, kwargs))

    async def embed_query(text):
        embedded.append(text)
        return [0.0, 1.0]

    memory = MemoryService(Repo(), vault, embed_query)
    await memory.write_records(raw, f"thread-{raw}", {
        "entities": [{"key": "contact", "value": raw}],
        "procedures": [{"rule_text": f"Never email {raw}", "scope": "global"}],
        "episode": {"summary": f"Met {raw}", "body": f"Contact: {raw}", "topics": [raw]},
        "patterns": [{"text": f"Often contacts {raw}"}],
    }, user_texts=[f"My contact email is {raw}.", f"Never email {raw}."])
    assert len(calls) == 3
    assert raw not in repr(calls)
    assert raw not in repr(embedded)
    assert "[EMAIL_" in repr(calls)
    assert "[EMAIL_" in repr(embedded)
    assert calls[2][1][1].startswith("[EMAIL_")
    assert calls[1][2]["severity"] == "hard"


@pytest.mark.asyncio
async def test_memory_forget_only_previews_and_never_deletes():
    class Repo:
        def __init__(self):
            self.deleted = False

        async def search_forget_candidates(self, user_id, query):
            return [{"store": "entities", "id": 7, "preview": "job"}]

        async def delete_candidates(self, user_id, candidates):
            self.deleted = True
            return len(candidates)

    repo = Repo()
    memory = MemoryService(repo, PIIVault(b"forget-hmac", Fernet.generate_key()), lambda text: None)
    preview = await memory.forget("user", "job", confirm=True)
    assert preview["will_delete"] == [{"store": "entities", "id": 7, "preview": "job"}]
    assert preview["deleted_count"] == 0
    assert not repo.deleted


@pytest.mark.asyncio
async def test_casual_chat_does_not_become_a_hard_procedure():
    class Repo:
        def __init__(self):
            self.procedures = []

        async def add_procedure(self, *args, **kwargs):
            self.procedures.append((args, kwargs))

        async def upsert_entity(self, *args, **kwargs):
            return None

    repo = Repo()
    memory = MemoryService(repo, PIIVault(b"casual-rule-hmac", Fernet.generate_key()), lambda text: None)
    await memory.write_records("user", "thread", {
        "procedures": [{"rule_text": "Never run out of tech talk at the water cooler", "severity": "hard"}],
    }, user_texts=["Never run out of tech talk at the water cooler."])
    assert repo.procedures == []

    await memory.write_records("user", "thread", {}, user_texts=["I prefer you to keep replies brief."])
    assert len(repo.procedures) == 1
    assert repo.procedures[0][1]["severity"] == "soft"
    assert repo.procedures[0][1]["confidence"] == 0.3
    assert repo.procedures[0][1]["tool_pattern"] == "*"
