import os
from typing import Optional
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, jwk
from jose.utils import base64url_decode
import httpx
from pydantic import BaseModel
import logging

logger = logging.getLogger("auth")

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE")
ALGORITHMS = ["RS256"]

security = HTTPBearer()

class User(BaseModel):
    user_id: str
    is_admin: bool

# Cache JWKS
_jwks_cache = None

def get_jwks():
    global _jwks_cache
    if _jwks_cache is None:
        try:
            jwks_url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
            response = httpx.get(jwks_url)
            response.raise_for_status()
            _jwks_cache = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from Auth0: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch JWKS")
    return _jwks_cache

def verify_token(token: str) -> dict:
    if not AUTH0_DOMAIN or not AUTH0_AUDIENCE:
        # If Auth0 is not configured, we should reject. But for dev, we might mock it.
        # Let's enforce auth
        logger.error("AUTH0_DOMAIN or AUTH0_AUDIENCE not set")
        raise HTTPException(status_code=500, detail="Auth configuration missing")

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid header. Use an RS256 signed JWT Access Token")
    
    if unverified_header["alg"] != "RS256":
        raise HTTPException(status_code=401, detail="Invalid algorithm. Use an RS256 signed JWT Access Token")
    
    jwks = get_jwks()
    rsa_key = {}
    for key in jwks["keys"]:
        if key["kid"] == unverified_header["kid"]:
            rsa_key = {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"]
            }
            break
            
    if not rsa_key:
        raise HTTPException(status_code=401, detail="Unable to find appropriate key")
        
    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=ALGORITHMS,
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/"
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token is expired")
    except jwt.JWTClaimsError:
        raise HTTPException(status_code=401, detail="Incorrect claims, please check the audience and issuer")
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        raise HTTPException(status_code=401, detail="Unable to parse authentication token.")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    token = credentials.credentials
    payload = verify_token(token)
    
    # Extract roles to check if admin
    roles = payload.get("https://deployhub.jeneeldumasia.codes/roles", [])
    is_admin = "admin" in roles
    
    return User(
        user_id=payload["sub"],
        is_admin=is_admin
    )
