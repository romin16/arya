import json
from pathlib import Path

import httpx
import pytest
import yaml
import logging

from core.tools.calculator import calculate
from core.tools.search import SearchError, SearchService
from core.tools.weather import WeatherService


def test_default_search_provider_is_tavily():
    settings = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config" / "search.yaml").read_text(encoding="utf-8")
    )["search"]
    assert settings["provider"] == "tavily"


@pytest.mark.asyncio
async def test_tavily_without_key_falls_back_to_configured_google_cse(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "mock-cse-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "mock-engine")

    async def handler(request: httpx.Request):
        assert request.url.host == "www.googleapis.com"
        return httpx.Response(200, json={"items": [
            {"title": "Example result", "link": "https://example.org", "snippet": "A snippet"},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SearchService(
            client, {"provider": "tavily", "fallback_providers": []},
        ).search("query")

    assert result["provider"] == "google_cse"
    assert "TAVILY_API_KEY" in result["message"]
    assert result["results"] == [{
        "title": "Example result", "url": "https://example.org", "snippet": "A snippet",
    }]


@pytest.mark.asyncio
async def test_search_provider_env_selects_and_logs_only_provider_key_presence(monkeypatch, caplog):
    for name in ("TAVILY_API_KEY", "GOOGLE_SEARCH_API_KEY", "GOOGLE_SEARCH_ENGINE_ID", "BRAVE_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SEARCH_PROVIDER", "brave")
    caplog.set_level(logging.INFO, logger="arya.search")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: pytest.fail("no key; no request"))) as client:
        service = SearchService(client)
        assert service.settings["provider"] == "brave"
        with pytest.raises(SearchError, match="BRAVE_SEARCH_API_KEY"):
            await service.search("query")
    assert "web_search_config provider=brave key_present=False" in caplog.text
    assert "mock" not in caplog.text


def test_calculator_evaluates_arithmetic_without_python_eval():
    assert calculate("(2 + 3) * 4 ** 2") == 80
    assert calculate("-8 / 2") == -4
    with pytest.raises(ValueError, match="safely"):
        calculate("__import__('os').system('echo unsafe')")
    with pytest.raises(ValueError, match="Exponents"):
        calculate("2 ** 1000")
    with pytest.raises(ValueError, match="safely"):
        calculate("1 / 0")


@pytest.mark.asyncio
async def test_google_cse_returns_at_most_five_compact_results(monkeypatch):
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "mock-cse-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "mock-engine")

    async def handler(request: httpx.Request):
        assert request.url.params["num"] == "5"
        return httpx.Response(200, json={"items": [
            {"title": f"Title {i}", "link": f"https://example.test/{i}", "snippet": "short", "htmlTitle": "ignored"}
            for i in range(8)
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SearchService(client, {"provider": "google_cse", "fallback_providers": []}).search("query", 9)
    assert result["provider"] == "google_cse"
    assert len(result["results"]) == 5
    assert set(result["results"][0]) == {"title", "url", "snippet"}


@pytest.mark.asyncio
async def test_google_quota_error_falls_back_to_tavily_when_key_is_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "mock-cse-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "mock-engine")
    monkeypatch.setenv("TAVILY_API_KEY", "mock-tavily-key")
    requests = []

    async def handler(request: httpx.Request):
        requests.append(request)
        if "googleapis.com" in request.url.host:
            return httpx.Response(429, json={"error": {"message": "quota"}})
        assert request.headers["authorization"] == "Bearer mock-tavily-key"
        assert json.loads(request.content)["query"] == "latest Python"
        return httpx.Response(200, json={"results": [
            {"title": "Python", "url": "https://example.test/python", "content": "A result", "score": 0.9}
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SearchService(client, {"provider": "google_cse", "fallback_providers": ["tavily", "brave"]})
        result = await service.search("latest Python")
    assert [request.url.host for request in requests] == ["www.googleapis.com", "api.tavily.com"]
    assert result["provider"] == "tavily"
    assert result["message"] == "Google CSE returned HTTP 429; showing tavily results instead."
    assert result["results"] == [{"title": "Python", "url": "https://example.test/python", "snippet": "A result"}]


@pytest.mark.asyncio
async def test_google_permission_error_without_fallback_has_clear_message(monkeypatch):
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "mock-cse-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "mock-engine")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    async def handler(request: httpx.Request):
        return httpx.Response(403, json={"error": {"message": "permission"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = SearchService(client, {"provider": "google_cse", "fallback_providers": ["tavily", "brave"]})
        with pytest.raises(SearchError, match="HTTP 403.*TAVILY_API_KEY or BRAVE_SEARCH_API_KEY"):
            await service.search("query")


@pytest.mark.asyncio
async def test_brave_provider_is_enabled_only_with_key_and_uses_mocked_api(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "mock-brave-key")

    async def handler(request: httpx.Request):
        assert request.headers["x-subscription-token"] == "mock-brave-key"
        assert request.url.params["count"] == "2"
        return httpx.Response(200, json={"web": {"results": [
            {"title": "One", "url": "https://example.test/1", "description": "Snippet"}
        ]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SearchService(client, {"provider": "brave"}).search("query", 2)
    assert result["results"] == [{"title": "One", "url": "https://example.test/1", "snippet": "Snippet"}]


@pytest.mark.asyncio
async def test_tavily_direct_provider_is_mocked(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "mock-tavily-key")

    async def handler(request: httpx.Request):
        assert request.url.host == "api.tavily.com"
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SearchService(client, {"provider": "tavily"}).search("query")
    assert result == {"provider": "tavily", "results": []}


@pytest.mark.asyncio
async def test_weather_geocodes_then_fetches_forecast_using_mocked_http(monkeypatch):
    calls = []

    async def handler(request: httpx.Request):
        calls.append(request)
        if request.url.host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json={"results": [{"name": "Pune", "admin1": "Maharashtra", "country": "India", "latitude": 18.5, "longitude": 73.8}]})
        assert request.url.params["timezone"] == "Asia/Kolkata"
        return httpx.Response(200, json={"current": {"temperature_2m": 29}, "daily": {"temperature_2m_max": [31]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WeatherService(client).get_weather("Pune", 2)
    assert [call.url.host for call in calls] == ["geocoding-api.open-meteo.com", "api.open-meteo.com"]
    assert result["location"] == {"name": "Pune", "admin1": "Maharashtra", "country": "India"}
    assert result["current"]["temperature_2m"] == 29


@pytest.mark.asyncio
async def test_weather_requires_a_location_instead_of_guessing():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("network must not be called"))) as client:
        with pytest.raises(ValueError, match="Tell me a city or location"):
            await WeatherService(client).get_weather(" ")
