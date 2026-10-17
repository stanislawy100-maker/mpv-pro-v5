from datetime import datetime, timezone, timedelta

import pytest

from app.kraken_scanner import _parse_ohlc, _validate_pair


def test_validate_pair_normalizes_and_rejects_invalid_pair():
    assert _validate_pair("xbt-usd") == "XBT/USD"
    with pytest.raises(ValueError, match="BASE/QUOTE"):
        _validate_pair("BTCUSDT")


def test_parse_ohlc_sorts_and_excludes_open_candle():
    now = datetime.now(timezone.utc)
    closed_ts = int((now - timedelta(hours=4)).timestamp())
    open_ts = int((now - timedelta(minutes=20)).timestamp())
    payload = {
        "error": [],
        "result": {
            "XXBTZUSD": [
                [open_ts, "100", "105", "95", "102", "101", "10", 5],
                [closed_ts, "90", "105", "89", "100", "95", "20", 6],
            ],
            "last": 123,
        },
    }
    candles = _parse_ohlc(payload, "1h")
    assert len(candles) == 1
    assert candles[0]["close"] == 100.0
    assert candles[0]["volume"] == 20.0


def test_parse_ohlc_rejects_bad_ohlc():
    ts = int((datetime.now(timezone.utc) - timedelta(hours=5)).timestamp())
    payload = {"error": [], "result": {"XXBTZUSD": [[ts, "100", "90", "95", "102", "101", "10", 5]], "last": 1}}
    with pytest.raises(ValueError, match="invalid OHLC"):
        _parse_ohlc(payload, "1h")


def test_parse_ohlc_rejects_kraken_api_errors():
    with pytest.raises(ValueError, match="returned an error"):
        _parse_ohlc({"error": ["EGeneral:Invalid arguments"], "result": {}}, "1h")
