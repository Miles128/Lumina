"""Tests for reverse geocoding."""

from __future__ import annotations

from unittest.mock import patch

from secretary.services.geolocation import reverse_geocode_city


def test_reverse_geocode_city_parses_chinese_city() -> None:
    payload = {
        "address": {
            "city": "杭州市",
            "state": "浙江省",
        }
    }
    with patch("secretary.services.geolocation.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        response = client.get.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        city = reverse_geocode_city(30.27, 120.15)
    assert city == "杭州"


def test_reverse_geocode_city_returns_none_on_failure() -> None:
    with patch("secretary.services.geolocation.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.side_effect = OSError("network down")
        assert reverse_geocode_city(30.27, 120.15) is None
