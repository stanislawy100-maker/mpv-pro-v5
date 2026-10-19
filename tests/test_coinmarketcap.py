from fastapi.testclient import TestClient

import app.coinmarketcap as cmc
from app.main import app


def test_coinmarketcap_screener_filters_and_ranks(monkeypatch):
    async def fake_fetch_listings(limit=100):
        return {
            "provider": "CoinMarketCap",
            "mode": "READ_ONLY_RESEARCH",
            "source_timestamp": "2026-10-19T00:00:00.000Z",
            "credit_count": 1,
            "limit": limit,
            "live_execution_enabled": False,
            "authenticated_exchange": False,
            "results": [
                {"id": 1, "name": "Alpha", "symbol": "ALP", "cmc_rank": 1,
                 "quote": {"USD": {"price": 2, "market_cap": 1_000_000_000,
                 "volume_24h": 100_000_000, "percent_change_24h": 8, "percent_change_7d": 12}}},
                {"id": 2, "name": "Tether", "symbol": "USDT", "cmc_rank": 3,
                 "quote": {"USD": {"price": 1, "market_cap": 50_000_000_000,
                 "volume_24h": 2_000_000_000, "percent_change_24h": 0, "percent_change_7d": 0}}},
                {"id": 3, "name": "Tiny", "symbol": "TNY", "cmc_rank": 900,
                 "quote": {"USD": {"price": 0.01, "market_cap": 1_000_000,
                 "volume_24h": 100_000, "percent_change_24h": 2, "percent_change_7d": 3}}},
            ],
        }

    monkeypatch.setattr(cmc, "fetch_listings", fake_fetch_listings)
    with TestClient(app) as client:
        response = client.get("/coinmarketcap/market-screener")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "CoinMarketCap"
    assert body["live_execution_enabled"] is False
    assert body["count"] == 1
    assert body["results"][0]["symbol"] == "ALP"
    assert body["results"][0]["score_type"] == "heuristic_not_a_trading_signal"


def test_coinmarketcap_screener_can_include_stablecoins(monkeypatch):
    async def fake_fetch_listings(limit=100):
        return {
            "provider": "CoinMarketCap", "mode": "READ_ONLY_RESEARCH",
            "source_timestamp": None, "limit": limit,
            "live_execution_enabled": False, "authenticated_exchange": False,
            "results": [
                {"id": 2, "name": "Tether", "symbol": "USDT", "cmc_rank": 3,
                 "quote": {"USD": {"price": 1, "market_cap": 50_000_000_000,
                 "volume_24h": 2_000_000_000, "percent_change_24h": 0, "percent_change_7d": 0}}}
            ],
        }

    monkeypatch.setattr(cmc, "fetch_listings", fake_fetch_listings)
    with TestClient(app) as client:
        response = client.get(
            "/coinmarketcap/market-screener?min_market_cap_usd=0&min_volume_24h_usd=0&exclude_stablecoins=false"
        )
    assert response.status_code == 200
    assert response.json()["results"][0]["symbol"] == "USDT"
