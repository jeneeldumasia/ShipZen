"""
Auth0 JWT authentication for the DeployHub API.

Validates Bearer tokens from the Authorization header against Auth0's JWKS endpoint.
Falls back to a permissive stub when AUTH0_DOMAIN is not set (local dev / CI).
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

AUTH0_DOMAIN   = os.getenv("AUTH0_DOMAIN", "")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "")
ALGORITHM      = "RS256"

# FastAPI security scheme — extracts Bearer token from Authorization header
_bearer = HTTPBearer(auto_error=False)

# Simple in-memory JWKS cache so we don't hit Auth0 on every request
_jwks_cache: Optional[dict] = None


def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch JWKS from {url}: {e}")
        raise HTTPException(status_code=503, detail="Auth service unavailable")


@dataclass
class User:
    user_id: str
    is_admin: bool = False


def get_current_user_from_token(token: str) -> User:
    """Helper to validate a token string directly (useful for WebSockets)."""
    return get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    """
    FastAPI dependency — validates the JWT and returns the current user.

    If AUTH0_DOMAIN is not configured (local dev), returns a stub admin user
    so the API works without Auth0 set up.
    """
    # ── Local dev stub ────────────────────────────────────────────────────────
    if not AUTH0_DOMAIN:
        logger.warning("AUTH0_DOMAIN not set — using stub user for local dev")
        return User(user_id="local-dev-user", is_admin=True)

    # ── Require Bearer token ──────────────────────────────────────────────────
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # ── Decode and validate ───────────────────────────────────────────────────
    try:
        jwks = _get_jwks()
        unverified_header = jwt.get_unverified_header(token)

        # Find the matching key in JWKS
        rsa_key = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == unverified_header.get("kid"):
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n":   key["n"],
                    "e":   key["e"],
                }
                break

        if not rsa_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: no matching key found",
            )

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=[ALGORITHM],
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/",
        )

        user_id: str = payload.get("sub", "")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing sub claim",
            )

        # Check for admin role in custom claim
        # Set this up in Auth0 Actions: event.user.app_metadata.roles
        roles = payload.get("https://deployhub.jeneeldumasia.codes/roles", [])
        is_admin = "admin" in roles

        return User(user_id=user_id, is_admin=is_admin)

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
