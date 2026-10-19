"""CoinMarketCap market-data adapter for research-only crypto screening.

Uses CoinMarketCap's keyless public API by default. Set COINMARKETCAP_API_KEY
for authenticated access. This module never places or signs exchange orders.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["CoinMarketCap"])
BASE_URL = "https://pro-api.coinmarketcap.com"
PUBLIC_BASE_URL = f"{BASE_URL}/public-api"
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _api_base_and_headers() -> tuple[str, dict[str, str]]:
    api_key = os.getenv("COINMARKETCAP_API_KEY", "").strip()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-CMC_PRO_API_KEY"] = api_key
        return BASE_URL, headers
    return PUBLIC_BASE_URL, headers


def _rotation_score(item: dict[str, Any]) -> float:
    """Transparent ranking heuristic, not a prediction or trading signal."""
    quote = (item.get("quote") or {}).get("USD") or {}
    change_24h = float(quote.get("percent_change_24h") or 0.0)
    change_7d = float(quote.get("percent_change_7d") or 0.0)
    volume = float(quote.get("volume_24h") or 0.0)
    market_cap = float(quote.get("market_cap") or 0.0)
    volume_ratio = volume / market_cap if market_cap > 0 else 0.0
    # Capped components prevent a single extreme reading dominating the score.
    return round(
        max(-20.0, min(20.0, change_24h)) * 0.45
        + max(-30.0, min(30.0, change_7d)) * 0.35
        + max(0.0, min(1.0, volume_ratio)) * 10.0,
        4,
    )


async def fetch_listings(limit: int = 100) -> dict[str, Any]:
    """Fetch ranked listings; cache briefly to respect provider update cadence."""
    base, headers = _api_base_and_headers()
    cache_key = f"{base}:{limit}"
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{base}/v3/cryptocurrency/listings/latest"
    params = {"start": 1, "limit": limit, "convert": "USD", "sort": "market_cap"}
    timeout = httpx.Timeout(12.0, connect=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 429:
            raise HTTPException(status_code=503, detail="CoinMarketCap rate limit reached; retry later.") from exc
        raise HTTPException(status_code=502, detail=f"CoinMarketCap returned HTTP {status}.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Could not retrieve valid data from CoinMarketCap.") from exc

    status_data = payload.get("status") or {}
    if status_data.get("error_code", 0):
        message = status_data.get("error_message") or "CoinMarketCap API error."
        raise HTTPException(status_code=502, detail=message)
    data = payload.get("data")
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="CoinMarketCap response did not contain a listings array.")
    result = {
        "provider": "CoinMarketCap",
        "mode": "READ_ONLY_RESEARCH",
        "source_timestamp": status_data.get("timestamp"),
        "credit_count": status_data.get("credit_count"),
        "limit": limit,
        "results": data,
        "live_execution_enabled": False,
        "authenticated_exchange": False,
    }
    _cache[cache_key] = (now, result)
    return result


@router.get("/coinmarketcap/market-screener")
async def coinmarketcap_market_screener(
    limit: int = Query(default=100, ge=10, le=500),
    min_market_cap_usd: float = Query(default=50_000_000, ge=0),
    min_volume_24h_usd: float = Query(default=5_000_000, ge=0),
    exclude_stablecoins: bool = Query(default=True),
) -> dict[str, Any]:
    """Rank CMC-listed assets by simple momentum/volume proxy for further research."""
    payload = await fetch_listings(limit=limit)
    results = []
    for item in payload["results"]:
        quote = (item.get("quote") or {}).get("USD") or {}
        market_cap = float(quote.get("market_cap") or 0.0)
        volume = float(quote.get("volume_24h") or 0.0)
        symbol = str(item.get("symbol") or "").upper()
        name = str(item.get("name") or "")
        if market_cap < min_market_cap_usd or volume < min_volume_24h_usd:
            continue
        if exclude_stablecoins and (symbol in {"USDT", "USDC", "DAI", "FDUSD", "USDE", "USDS", "TUSD", "USDP", "PYUSD", "USDD"}):
            continue
        results.append({
            "cmc_id": item.get("id"),
            "name": name,
            "symbol": symbol,
            "cmc_rank": item.get("cmc_rank"),
            "price_usd": quote.get("price"),
            "market_cap_usd": market_cap,
            "volume_24h_usd": volume,
            "volume_market_cap_ratio": round(volume / market_cap, 6) if market_cap else None,
            "percent_change_24h": quote.get("percent_change_24h"),
            "percent_change_7d": quote.get("percent_change_7d"),
            "rotation_score": _rotation_score(item),
            "score_type": "heuristic_not_a_trading_signal",
        })
    results.sort(key=lambda row: row["rotation_score"], reverse=True)
    return {
        "provider": payload["provider"],
        "mode": payload["mode"],
        "source_timestamp": payload["source_timestamp"],
        "count": len(results),
        "filters": {
            "limit": limit,
            "min_market_cap_usd": min_market_cap_usd,
            "min_volume_24h_usd": min_volume_24h_usd,
            "exclude_stablecoins": exclude_stablecoins,
        },
        "results": results,
        "live_execution_enabled": False,
        "authenticated_exchange": False,
        "disclaimer": "CoinMarketCap aggregates market data; it is not an exchange execution API. Scores are heuristic research rankings, not predictions or buy/sell advice.",
    }
