import os
import logging
import hashlib
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from cachetools import TTLCache

logger = logging.getLogger(__name__)

GITHUB_ENABLED = os.getenv("GITHUB_ENABLED", "false").lower() == "true"

_bearer = HTTPBearer(auto_error=False)

# Cache GitHub tokens for 5 minutes to avoid rate limits
_token_cache = TTLCache(maxsize=1000, ttl=300)

@dataclass
class User:
    user_id: str
    is_admin: bool = False

def get_current_user_from_token(token: str) -> User:
    return get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    if not GITHUB_ENABLED:
        logger.warning("GITHUB_ENABLED not true — using stub user for local dev")
        from database import get_or_create_user
        db_user = get_or_create_user("local-dev-user", "admin@shipzen.local")
        return User(user_id=db_user["id"], is_admin=(db_user["role"] == "admin"))

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Fix 12: Token cache key is the raw bearer token, hash it
    cache_key = hashlib.sha256(token.encode()).hexdigest()

    # Check cache
    if cache_key in _token_cache:
        user_info = _token_cache[cache_key]
    else:
        # Verify token with GitHub
        try:
            resp = httpx.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=5
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid GitHub token",
                )
            
            gh_user = resp.json()
            # Fetch emails because primary email might be private
            email_resp = httpx.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=5
            )
            email = None
            if email_resp.status_code == 200:
                for e in email_resp.json():
                    if e.get("primary"):
                        email = e.get("email")
                        break
            
            user_info = {
                "id": str(gh_user["id"]),
                "login": gh_user["login"],
                "email": email or gh_user.get("email")
            }
            _token_cache[cache_key] = user_info
        except httpx.RequestError as e:
            logger.error(f"GitHub API request failed: {e}")
            raise HTTPException(status_code=503, detail="Auth service unavailable")

    from database import get_or_create_user
    db_user = get_or_create_user(user_info["id"], user_info["email"])
    return User(user_id=user_info["id"], is_admin=(db_user["role"] == "admin"))
