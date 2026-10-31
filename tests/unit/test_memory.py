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
