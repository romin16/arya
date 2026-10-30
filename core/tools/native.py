from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from core.tools.calculator import calculate
from core.tools.search import SearchService
from core.tools.weather import WeatherService


def build_native_tools(search: SearchService, weather: WeatherService) -> dict[str, Any]:
    async def web_search(query: str, n: int = 5) -> dict[str, Any]:
        """Search the web and return up to five title, URL, and snippet entries."""
        return await search.search(query, n)

    async def get_weather(location: str, days: int = 1) -> dict[str, Any]:
        """Look up current conditions and a short forecast for a named location."""
        return await weather.get_weather(location, days)

    def calculator(expression: str) -> dict[str, int | float]:
        """Safely calculate an arithmetic expression."""
        return {"result": calculate(expression)}

    return {
        "web_search": StructuredTool.from_function(
            coroutine=web_search,
            name="web_search",
            description="Search current web pages. Returns at most five titles, URLs, and snippets.",
        ),
        "get_weather": StructuredTool.from_function(
            coroutine=get_weather,
            name="get_weather",
            description="Get weather for a named location. If the user did not give a location, ask them first.",
        ),
        "calculator": StructuredTool.from_function(
            func=calculator,
            name="calculator",
            description="Evaluate basic arithmetic with parentheses, powers, and standard operators.",
        ),
    }
