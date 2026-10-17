from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from app.indicators import calculate_indicators
from app.strategy import evaluate_trend

BASE_URL = "https://api.kraken.com/0/public"
DEFAULT_SYMBOLS = ["XBT/USD", "ETH/USD", "FET/USD", "RENDER/USD", "NEAR/USD", "SUI/USD", "AKT/USD"]
INTERVALS = {"1h": 60, "4h": 240}


def _validate_pair(pair: str) -> str:
    value = pair.strip().upper().replace("-", "/")
    if "/" not in value:
        raise ValueError(f"Use Kraken pair format BASE/QUOTE, e.g. XBT/USD: {pair!r}.")
    parts = value.split("/")
    if len(parts) != 2 or not all(parts) or any(not part.isalnum() for part in parts):
        raise ValueError(f"Invalid Kraken pair: {pair!r}.")
    return value


def _parse_ohlc(payload: dict[str, Any], interval: str) -> list[dict[str, Any]]:
    if interval not in INTERVALS:
        raise ValueError("Only 1h and 4h intervals are supported.")
    if payload.get("error"):
        raise ValueError("Kraken OHLC API returned an error.")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("Unexpected Kraken OHLC response.")
    pair_keys = [key for key in result if key != "last"]
    if len(pair_keys) != 1 or not isinstance(result[pair_keys[0]], list):
        raise ValueError("Kraken OHLC response did not contain one pair's candles.")
    candles = []
    for row in result[pair_keys[0]]:
        if not isinstance(row, list) or len(row) < 7:
            raise ValueError("Kraken returned a malformed OHLC candle.")
        try:
            candle = {
                "timestamp": datetime.fromtimestamp(int(row[0]), tz=timezone.utc).isoformat(),
                "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
                "close": float(row[4]), "volume": float(row[6]),
            }
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Kraken returned a malformed OHLC candle.") from exc
        if min(candle["open"], candle["high"], candle["low"], candle["close"]) <= 0 or candle["volume"] < 0:
            raise ValueError("Kraken returned invalid OHLC values.")
        if candle["low"] > min(candle["open"], candle["close"]) or candle["high"] < max(candle["open"], candle["close"]) or candle["low"] > candle["high"]:
            raise ValueError("Kraken returned invalid OHLC values.")
        candles.append(candle)
    candles.sort(key=lambda item: item["timestamp"])
    duration = INTERVALS[interval] * 60
    now = datetime.now(timezone.utc).timestamp()
    return [c for c in candles if datetime.fromisoformat(c["timestamp"]).timestamp() + duration <= now]


async def _fetch_pair(client: httpx.AsyncClient, pair: str, interval: str) -> list[dict[str, Any]]:
    response = await client.get(f"{BASE_URL}/OHLC", params={"pair": pair, "interval": INTERVALS[interval]})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Kraken OHLC response.")
    candles = _parse_ohlc(payload, interval)
    if len(candles) < 220:
        raise ValueError(f"Only {len(candles)} completed candles for {pair} {interval}; 220 required.")
    return candles


async def scan_kraken_spot(symbols: list[str] | None = None) -> dict[str, Any]:
    """Read-only public Kraken Spot scanner; never authenticates or places orders."""
    requested = symbols or DEFAULT_SYMBOLS
    normalized = list(dict.fromkeys(_validate_pair(symbol) for symbol in requested))
    if not normalized or len(normalized) > 20:
        raise ValueError("Supply between 1 and 20 Kraken pairs.")
    results, errors = [], []
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "MPV-PRO-V5-research-scanner/1.0"}) as client:
        for pair in normalized:
            try:
                hourly, four_hour = await asyncio.gather(
                    _fetch_pair(client, pair, "1h"),
                    _fetch_pair(client, pair, "4h"),
                )
                h, h4 = calculate_indicators(hourly), calculate_indicators(four_hour)
                sig1, sig4 = evaluate_trend(h), evaluate_trend(h4)
                change_24h = (hourly[-1]["close"] / hourly[-25]["close"] - 1) * 100
                average_volume_20h = sum(item["volume"] for item in hourly[-21:-1]) / 20
                volume_ratio = hourly[-1]["volume"] / average_volume_20h if average_volume_20h > 0 else None
                aligned = sig1["action"] == sig4["action"] and sig1["action"] in ("BUY", "SELL")
                score = (2 if aligned and sig1["action"] == "BUY" else -2 if aligned and sig1["action"] == "SELL" else 0) + (1 if h.close > h.ema200 else -1) + max(-1, min(1, change_24h / 10))
                results.append({
                    "symbol": pair, "price": h.close, "change_24h_percent": round(change_24h, 3),
                    "last_completed_1h_volume": hourly[-1]["volume"],
                    "volume_vs_previous_20h_average": round(volume_ratio, 3) if volume_ratio is not None else None,
                    "rsi14_1h": round(h.rsi14, 2), "adx14_1h": round(h.adx14, 2),
                    "signal_1h": sig1["action"], "signal_4h": sig4["action"],
                    "signal": sig1["action"] if aligned else "HOLD", "rotation_score": round(score, 3),
                    "last_completed_1h_candle": hourly[-1]["timestamp"],
                    "last_completed_4h_candle": four_hour[-1]["timestamp"],
                })
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                errors.append({"symbol": pair, "error": str(exc)[:240]})
    results.sort(key=lambda item: item["rotation_score"], reverse=True)
    return {
        "provider": "Kraken public Spot market data", "mode": "READ_ONLY_RESEARCH",
        "symbols_requested": normalized, "results": results, "errors": errors,
        "authenticated": False, "live_execution_enabled": False,
        "warning": "Public Spot market data only. This is not a derivatives demo account and does not place orders. Kraken pair availability varies; verify the exact pair identifiers before relying on a scan. Signals are research only.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
