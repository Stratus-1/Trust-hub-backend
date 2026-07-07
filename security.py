# security.py
import os
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
ALGORITHM = "HS256"
ISSUER = "myapp"
AUDIENCE = "myapp_users"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/bootstrap")

def create_token(user: str, expires_delta: timedelta = timedelta(minutes=15)):
    now = datetime.utcnow()
    payload = {
        "user": user,
        "exp": now + expires_delta,
        "iat": now,
        "iss": ISSUER,
        "aud": AUDIENCE,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token

def verify_token(token: str):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            audience=AUDIENCE,
        )
        return payload.get("user")
    except JWTError:
        return None

def get_current_user(token: str = Depends(oauth2_scheme)):
    user = verify_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
