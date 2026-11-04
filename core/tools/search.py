"""Provider-swappable web search with JSON-only compact results."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("arya.search")


class SearchService:
    def __init__(self, client: httpx.AsyncClient, settings: dict[str, Any] | None = None):
        self.client = client
        self.settings = dict(settings) if settings is not None else yaml.safe_load(
            (ROOT / "config" / "search.yaml").read_text(encoding="utf-8")
        )["search"]
        environment_provider = os.getenv("SEARCH_PROVIDER", "").strip().casefold()
        if settings is None and environment_provider:
            self.settings["provider"] = environment_provider
        selected = str(self.settings.get("provider", "tavily")).casefold()
        active = next((item for item in self._provider_order(selected) if self._has_key(item)), selected)
        logger.info("web_search_config provider=%s key_present=%s", active, self._has_key(active))

    async def search(self, query: str, n: int = 5) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise SearchError("Give me a search query first.")
        n = min(max(int(n), 1), 5)
        provider = str(self.settings.get("provider", "tavily")).casefold()
        if not self._has_key(provider):
            for fallback in self._provider_order(provider)[1:]:
                if self._has_key(fallback):
                    try:
                        results = await self._search_provider(fallback, query, n)
                        return {
                            "provider": fallback,
                            "message": (
                                f"{provider} is missing {self._missing_configuration(provider)}; "
                                f"using configured {fallback} instead."
                            ),
                            "results": results,
                        }
                    except SearchError:
                        continue
            raise SearchError(
                f"Web search is unavailable: {provider} requires {self._missing_configuration(provider)}. "
                "Set SEARCH_PROVIDER to a configured provider or add the named key(s) to .env."
            )
        try:
            results = await self._search_provider(provider, query, n)
            return {"provider": provider, "results": results}
        except SearchError as exc:
            if provider != "google_cse" or exc.status not in {401, 403, 429}:
                raise
            for fallback in self._provider_order(provider)[1:]:
                if not self._has_key(fallback):
                    continue
                try:
                    results = await self._search_provider(fallback, query, n)
                    return {
                        "provider": fallback,
                        "message": f"Google CSE returned HTTP {exc.status}; showing {fallback} results instead.",
                        "results": results,
                    }
                except SearchError:
                    continue
            raise SearchError(
                f"Google CSE returned HTTP {exc.status} (quota or permission). "
                "Configure TAVILY_API_KEY or BRAVE_SEARCH_API_KEY in .env."
            ) from None

    def _provider_order(self, selected: str) -> list[str]:
        configured = [str(item).casefold() for item in self.settings.get("fallback_providers", [])]
        return list(dict.fromkeys([selected, *configured, "tavily", "google_cse", "brave"]))

    @staticmethod
    def _missing_configuration(provider: str) -> str:
        required = {
            "google_cse": ["GOOGLE_SEARCH_API_KEY", "GOOGLE_SEARCH_ENGINE_ID"],
            "tavily": ["TAVILY_API_KEY"],
            "brave": ["BRAVE_SEARCH_API_KEY"],
        }.get(provider, ["SEARCH_PROVIDER"])
        missing = [name for name in required if not os.getenv(name)]
        return " and ".join(missing or required)

    async def _search_provider(self, provider: str, query: str, n: int) -> list[dict[str, str]]:
        if provider == "google_cse":
            return await self._google(query, n)
        if provider not in {"tavily", "brave"}:
            raise SearchError(f"Unsupported search.provider setting: {provider}.")
        return await self._provider(provider, query, n)

    def _has_key(self, provider: str) -> bool:
        import os

        return bool({
            "google_cse": os.getenv("GOOGLE_SEARCH_API_KEY") and os.getenv("GOOGLE_SEARCH_ENGINE_ID"),
            "tavily": os.getenv("TAVILY_API_KEY"),
            "brave": os.getenv("BRAVE_SEARCH_API_KEY"),
        }.get(provider))

    @staticmethod
    def _results(rows: Any, *, title: str, url: str, snippet: str, limit: int) -> list[dict[str, str]]:
        if not isinstance(rows, list):
            return []
        output = []
        for item in rows[:limit]:
            if not isinstance(item, dict):
                continue
            output.append({
                "title": str(item.get(title, ""))[:300],
                "url": str(item.get(url, ""))[:2048],
                "snippet": str(item.get(snippet, ""))[:1000],
            })
        return output

    async def _google(self, query: str, n: int) -> list[dict[str, str]]:
        import os

        key = os.getenv("GOOGLE_SEARCH_API_KEY", "")
        engine = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "")
        if not key or not engine:
            raise SearchError("Google CSE requires GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_ENGINE_ID.")
        response = await self.client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": key, "cx": engine, "q": query, "num": n},
        )
        if response.is_error:
            raise SearchError(f"Google CSE returned HTTP {response.status_code}.", status=response.status_code)
        return self._results(response.json().get("items", []), title="title", url="link", snippet="snippet", limit=n)

    async def _provider(self, provider: str, query: str, n: int) -> list[dict[str, str]]:
        import os

        if provider == "tavily":
            key = os.getenv("TAVILY_API_KEY", "")
            if not key:
                raise SearchError("Tavily is disabled until TAVILY_API_KEY is set.")
            response = await self.client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {key}"},
                json={"query": query, "max_results": n, "include_answer": False},
            )
            if response.is_error:
                raise SearchError(f"Tavily returned HTTP {response.status_code}.", status=response.status_code)
            return self._results(response.json().get("results", []), title="title", url="url", snippet="content", limit=n)
        if provider == "brave":
            key = os.getenv("BRAVE_SEARCH_API_KEY", "")
            if not key:
                raise SearchError("Brave Search is disabled until BRAVE_SEARCH_API_KEY is set.")
            response = await self.client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": key},
                params={"q": query, "count": n},
            )
            if response.is_error:
                raise SearchError(f"Brave Search returned HTTP {response.status_code}.", status=response.status_code)
            rows = response.json().get("web", {}).get("results", [])
            return self._results(rows, title="title", url="url", snippet="description", limit=n)
        raise SearchError(f"Unsupported search provider: {provider}.")


class SearchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status
