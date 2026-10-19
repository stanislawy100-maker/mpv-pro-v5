from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException

from app.config import settings

router = APIRouter(prefix="/ctrader", tags=["cTrader"])


@router.get("/status")
def ctrader_status() -> dict:
    """Report setup state without connecting to an account or placing orders."""
    credentials_configured = bool(settings.ctrader_client_id and settings.ctrader_client_secret)
    redirect_configured = bool(settings.ctrader_redirect_uri)
    return {
        "provider": "cTrader Open API",
        "environment": "demo",
        "mode": "read_only_setup",
        "client_credentials_configured": credentials_configured,
        "redirect_uri_configured": redirect_configured,
        "authorization_ready": credentials_configured and redirect_configured,
        "account_connected": False,
        "market_data_connected": False,
        "live_execution_enabled": False,
        "next_step": (
            "Open /ctrader/authorize-url and approve the accounts-only permission."
            if credentials_configured and redirect_configured
            else "Register a cTrader Open API application and configure CTRADER_CLIENT_ID, "
                 "CTRADER_CLIENT_SECRET, and CTRADER_REDIRECT_URI."
        ),
        "limitations": [
            "This endpoint reports configuration only; it does not verify broker connectivity.",
            "No orders are sent and no trading permission is requested.",
        ],
    }


@router.get("/authorize-url")
def ctrader_authorize_url() -> dict:
    """Build the official cTrader OAuth URL with accounts-only (read-only) scope."""
    client_id = settings.ctrader_client_id.strip()
    redirect_uri = settings.ctrader_redirect_uri.strip()
    if not client_id or not settings.ctrader_client_secret.strip() or not redirect_uri:
        raise HTTPException(
            status_code=503,
            detail="Configure CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, and CTRADER_REDIRECT_URI first.",
        )

    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "accounts",
        "product": "web",
    })
    return {
        "authorization_url": f"https://id.ctrader.com/my/settings/openapi/grantingaccess/?{query}",
        "scope": "accounts",
        "permission_level": "read_only",
        "environment": "demo",
        "live_execution_enabled": False,
        "note": "Only approve this URL if you recognise your own cTrader application and redirect URI.",
    }
