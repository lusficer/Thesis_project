"""
Auth utilities — JWT tokens + password hashing.
Simple implementation suitable for a thesis project.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from passlib.context import CryptContext
import jwt

from app.database import get_db
from app.models import User, UserRole
from app.schemas import UserLogin, UserRegister, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger(__name__)

# Config
SECRET_KEY = os.getenv("JWT_SECRET", "thesis-dss-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Dependency to get current user from JWT. Returns None if no token."""
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user



@router.post("/register", response_model=UserResponse, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db)):
    identity_email = (data.email or data.username or "").strip().lower()
    if not identity_email:
        raise HTTPException(status_code=400, detail="Email or username is required")

    try:
        existing = db.query(User).filter(User.email == identity_email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        user = User(
            email=identity_email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.MANAGER,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return UserResponse(
            id=user.id, email=user.email, full_name=user.full_name,
            role=user.role.value, is_active=user.is_active,
        )
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Auth register DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Registration failed")
    except Exception as exc:
        db.rollback()
        logger.exception("Auth register unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    identity = (data.email or data.username or "").strip().lower()
    try:
        user = db.query(User).filter(User.email == identity).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is inactive")

        try:
            valid_password = verify_password(data.password, user.password_hash)
        except Exception as exc:
            logger.exception("Auth login password verify error for user=%s: %s", identity, exc)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if not valid_password:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_token(user.id, user.role.value)
        return TokenResponse(access_token=token)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.exception("Auth login DB error: %s", exc)
        raise HTTPException(status_code=500, detail="Login failed")
    except Exception as exc:
        logger.exception("Auth login unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Login failed")


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserResponse(
        id=user.id, email=user.email, full_name=user.full_name,
        role=user.role.value, is_active=user.is_active,
    )
