"""
Microsoft Graph authentication using MSAL with a persistent token cache.

Uses the Device Code Flow so the user authenticates once in a browser,
then the token is cached locally for subsequent runs — no web server needed.

OneNote via Microsoft Graph requires delegated auth (no app-only support).
"""

import json
import os
import msal

import config


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if os.path.exists(config.TOKEN_CACHE_PATH):
        with open(config.TOKEN_CACHE_PATH, "r") as f:
            cache.deserialize(f.read())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        with open(config.TOKEN_CACHE_PATH, "w") as f:
            f.write(cache.serialize())


def _build_app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        client_id=config.AZURE_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}",
        token_cache=cache,
    )


def get_access_token() -> str:
    """
    Return a valid access token for Microsoft Graph.
    Attempts silent refresh first; falls back to interactive Device Code Flow.
    """
    if not config.AZURE_CLIENT_ID:
        raise RuntimeError(
            "AZURE_CLIENT_ID is not set.\n"
            "Set it as a Windows environment variable, then restart your terminal.\n"
            "For testing without OneNote, use --dry-run."
        )

    cache = _load_cache()
    app = _build_app(cache)

    accounts = app.get_accounts()
    result = None

    if accounts:
        result = app.acquire_token_silent(config.GRAPH_SCOPES, account=accounts[0])

    if not result:
        # Device Code Flow — user visits a URL and enters a short code
        flow = app.initiate_device_flow(scopes=config.GRAPH_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to create device flow: {flow.get('error_description')}")

        print("\n" + "=" * 60)
        print("ACTION REQUIRED: Sign in to Microsoft")
        print("=" * 60)
        print(flow["message"])
        print("=" * 60 + "\n")

        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Authentication failed: {error}")

    return result["access_token"]
