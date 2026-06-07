"""NUMA Capture Web — Google OAuth2 authentication module.

Provides OAuth login, session management (JWT cookies), and protected route middleware.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger("numa-auth")

# ─── Config from env ─────────────────────────────────────────────────────────

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
NUMA_SESSION_SECRET = os.environ.get("NUMA_SESSION_SECRET", "")
NUMA_BASE_URL = os.environ.get("NUMA_BASE_URL", "http://localhost:8765")

SCOPE = "openid email profile https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.labels"

# ─── JWT helper (pure Python, no jose dependency needed) ─────────────────────


def _b64encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    import base64
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _create_jwt(payload: dict, secret: str, expiry_seconds: int = 86400 * 7) -> str:
    """Create a signed JWT (HS256). 7-day expiry by default."""
    import hashlib
    import hmac

    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    token_payload = {
        **payload,
        "iat": now,
        "exp": now + expiry_seconds,
    }
    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64encode(json.dumps(token_payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    sig_b64 = _b64encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _verify_jwt(token: str, secret: str) -> dict | None:
    """Verify and decode a JWT. Returns payload dict or None if invalid/expired."""
    import hashlib
    import hmac

    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(
        secret.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    actual_sig = _b64decode(sig_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ─── Router ──────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth: OAuth | None = None


def setup_auth(app) -> None:
    """Mount the auth router and configure OAuth. Call after app creation."""
    global _oauth

    # Refuse to boot without a real session secret. Unsigned cookies = trivial
    # session forgery; better to fail loud at startup than silently insecure.
    if not NUMA_SESSION_SECRET or not NUMA_SESSION_SECRET.strip():
        raise RuntimeError(
            "NUMA_SESSION_SECRET must be set to a non-empty value. "
            "Refusing to start with unsigned session cookies."
        )

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.warning("Google OAuth not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
        app.include_router(router)
        return

    _oauth = OAuth()
    _oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        authorize_url="https://accounts.google.com/o/oauth2/auth",
        authorize_params=None,
        access_token_url="https://oauth2.googleapis.com/token",
        access_token_params=None,
        client_kwargs={
            "scope": SCOPE,
            "prompt": "consent",
            "access_type": "offline",
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    app.include_router(router)
    logger.info("Google OAuth configured for %s", NUMA_BASE_URL)


# ─── Cookie helpers ──────────────────────────────────────────────────────────


def _set_session_cookie(response: Response, payload: dict) -> None:
    if not NUMA_SESSION_SECRET:
        # setup_auth() refuses to boot without a secret, so this should be
        # unreachable. Guard anyway in case something bypassed startup.
        raise RuntimeError("NUMA_SESSION_SECRET is not set; refusing to issue unsigned cookie")
    token = _create_jwt(payload, NUMA_SESSION_SECRET)
    response.set_cookie(
        key="numa_session",
        value=token,
        httponly=True,
        secure=NUMA_BASE_URL.startswith("https"),
        samesite="lax",
        max_age=86400 * 7,  # 7 days
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        key="numa_session",
        value="",
        httponly=True,
        secure=NUMA_BASE_URL.startswith("https"),
        samesite="lax",
        max_age=0,
        path="/",
    )


def get_session_user(request: Request) -> dict | None:
    """Extract user info from session cookie. Returns None if not authenticated."""
    token = request.cookies.get("numa_session", "")
    if not token:
        return None
    if not NUMA_SESSION_SECRET:
        # Never trust an unsigned cookie. setup_auth() should have prevented
        # boot, but a missing secret at request time is treated as "no auth".
        return None
    payload = _verify_jwt(token, NUMA_SESSION_SECRET)
    if not payload or "sub" not in payload:
        return None
    return payload


def require_auth(request: Request) -> dict:
    """Use as dependency: `Depends(require_auth)`. Raises 401 if not logged in."""
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/google/login")
async def login_google(request: Request):
    """Redirect to Google consent screen."""
    if not _oauth:
        return HTMLResponse("<h2>OAuth not configured</h2><p>Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET</p>")
    redirect_uri = f"{NUMA_BASE_URL}/auth/google/callback"
    return await _oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def callback_google(request: Request):
    """Handle OAuth callback — exchange code for tokens, create session."""
    if not _oauth:
        raise HTTPException(500, "OAuth not configured")
    try:
        token = await _oauth.google.authorize_access_token(request)
    except OAuthError as e:
        logger.error("OAuth callback error: %s", e)
        return HTMLResponse(f"<h2>Auth Error</h2><p>{e.error}</p>")

    userinfo = token.get("userinfo")
    if not userinfo:
        # Fetch userinfo if not in token
        resp = await _oauth.google.get("https://www.googleapis.com/oauth2/v3/userinfo", token=token)
        if resp.ok:
            userinfo = resp.json()
        else:
            raise HTTPException(500, "Failed to fetch user info")

    sub = userinfo.get("sub", "")
    email = userinfo.get("email", "")
    name = userinfo.get("name", email)
    picture = userinfo.get("picture", "")

    # Store token info for Gmail API calls
    gmail_token = {
        "access_token": token.get("access_token", ""),
        "refresh_token": token.get("refresh_token", ""),
        "expiry": None,
        "token_type": token.get("token_type", "Bearer"),
        "scope": token.get("scope", ""),
    }
    if token.get("expires_at"):
        gmail_token["expiry"] = token["expires_at"]
    if token.get("expires_in"):
        gmail_token["expiry"] = int(time.time()) + token["expires_in"]

    session_payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "picture": picture,
        "gmail_token": gmail_token,
    }

    response = RedirectResponse(url="/capture", status_code=302)
    _set_session_cookie(response, session_payload)
    logger.info("User logged in: %s (%s)", name, email)
    return response


@router.get("/me")
async def get_me(request: Request):
    """Return current user info or 401."""
    user = get_session_user(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "sub": user.get("sub"),
        "email": user.get("email"),
        "name": user.get("name"),
        "picture": user.get("picture"),
    }


@router.post("/logout")
async def logout():
    """Clear session cookie."""
    response = Response(
        content='{"status": "ok"}',
        media_type="application/json",
    )
    _clear_session_cookie(response)
    return response
