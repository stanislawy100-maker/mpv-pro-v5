from fastapi.testclient import TestClient

import app.main as main


def test_kraken_rotation_scan_is_read_only_and_returns_ranked_results(monkeypatch):
    async def fake_scan(symbols):
        return {
            "provider": "Kraken public Spot market data",
            "mode": "READ_ONLY_RESEARCH",
            "symbols_requested": symbols,
            "results": [{"symbol": "XBT/USD", "signal": "HOLD", "rotation_score": 0.1}],
            "errors": [],
            "live_execution_enabled": False,
            "authenticated": False,
        }

    monkeypatch.setattr(main, "scan_kraken_spot", fake_scan)
    with TestClient(main.app) as client:
        response = client.get("/kraken/rotation-scan?symbols=xbt/usd,FET/USD")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbols_requested"] == ["XBT/USD", "FET/USD"]
    assert payload["live_execution_enabled"] is False
    assert payload["authenticated"] is False
    assert payload["results"][0]["symbol"] == "XBT/USD"
