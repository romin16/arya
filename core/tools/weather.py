"""Open-Meteo geocoding and forecast client."""
from __future__ import annotations

from typing import Any

import httpx


class WeatherService:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def get_weather(self, location: str, days: int = 1) -> dict[str, Any]:
        location = location.strip()
        if not location:
            raise ValueError("Tell me a city or location so I can check the weather.")
        if not 1 <= int(days) <= 7:
            raise ValueError("Forecast length must be between 1 and 7 days.")
        geo = await self.client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"},
        )
        geo.raise_for_status()
        matches = geo.json().get("results", [])
        if not matches:
            return {"success": False, "error": f"I couldn't find a location matching {location!r}."}
        place = matches[0]
        forecast = await self.client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Asia/Kolkata",
                "forecast_days": int(days),
            },
        )
        forecast.raise_for_status()
        return {
            "success": True,
            "location": {key: place[key] for key in ("name", "admin1", "country") if key in place},
            "current": forecast.json().get("current", {}),
            "daily": forecast.json().get("daily", {}),
        }
