from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


client = TestClient(app)


def test_ctrader_status_is_read_only_and_demo():
    response = client.get("/ctrader/status")
    assert response.status_code == 200
    data = response.json()
    assert data["environment"] == "demo"
    assert data["mode"] == "read_only_setup"
    assert data["account_connected"] is False
    assert data["market_data_connected"] is False
    assert data["live_execution_enabled"] is False


def test_ctrader_authorize_url_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ctrader_client_id", "")
    monkeypatch.setattr(settings, "ctrader_client_secret", "")
    monkeypatch.setattr(settings, "ctrader_redirect_uri", "")
    response = client.get("/ctrader/authorize-url")
    assert response.status_code == 503


def test_ctrader_authorize_url_uses_accounts_scope(monkeypatch):
    monkeypatch.setattr(settings, "ctrader_client_id", "test-client-id")
    monkeypatch.setattr(settings, "ctrader_client_secret", "test-secret")
    monkeypatch.setattr(settings, "ctrader_redirect_uri", "https://example.com/callback")
    response = client.get("/ctrader/authorize-url")
    assert response.status_code == 200
    data = response.json()
    assert "scope=accounts" in data["authorization_url"]
    assert "client_id=test-client-id" in data["authorization_url"]
    assert data["permission_level"] == "read_only"
    assert data["live_execution_enabled"] is False
