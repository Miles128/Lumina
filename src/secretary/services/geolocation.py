"""Reverse geocoding for desktop location → city name."""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "Lumina/0.1.0 (personal assistant; contact: myx28@qq.com)"
_TIMEOUT = 12.0

_CITY_SUFFIX_RE = re.compile(r"(.+?)(?:市|地区|自治州|盟)$")


def reverse_geocode_city(latitude: float, longitude: float) -> str | None:
    """Resolve coordinates to a Chinese-friendly city name."""
    params = {
        "lat": str(latitude),
        "lon": str(longitude),
        "format": "jsonv2",
        "accept-language": "zh-CN,zh,en",
        "zoom": "10",
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = client.get(NOMINATIM_URL, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("reverse geocode failed: %s", error)
        return None

    address = payload.get("address")
    if not isinstance(address, dict):
        return None

    for key in ("city", "town", "county", "state_district", "municipality", "state"):
        raw = address.get(key)
        if not isinstance(raw, str):
            continue
        city = _normalize_city_name(raw)
        if city:
            return city
    return None


def _normalize_city_name(raw: str) -> str | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    match = _CITY_SUFFIX_RE.match(cleaned)
    if match:
        cleaned = match.group(1)
    cleaned = cleaned.strip().rstrip("市")
    if len(cleaned) < 2 or len(cleaned) > 12:
        return None
    return cleaned
