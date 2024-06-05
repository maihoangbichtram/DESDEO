"""This module contains the functions for user authentication."""
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from desdeo.api.db import get_db
from desdeo.api.db_models import User as UserModel
from desdeo.api.schema import User
from desdeo.api.utils.database import (
    database_dependency,
    select,
    filter_by
)

router = APIRouter()

# to get a string like this run:
# openssl rand -hex 32
SECRET_KEY = "36b96a23d24cebdeadce6d98fa53356111e6f3e85b8144d7273dcba230b9eb18"  # NOQA:S105 # TODO: How to handle this?
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10000
SALT = bcrypt.gensalt()


class Token(BaseModel):
    """A model for the authentication token."""

    access_token: str
    token_type: str


# OAuth2PasswordBearer is a class that creates a dependency that will be used to get the token from the request.
# The token will be used to authenticate the user.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_password(plain_password, hashed_password):
    """Check if a password matches a hash."""
    password_byte_enc = plain_password.encode("utf-8")
    return bcrypt.checkpw(password=password_byte_enc, hashed_password=hashed_password.encode("utf-8"))


def get_password_hash(password):
    """Hash a password."""
    pwd_bytes = password.encode("utf-8")
    return bcrypt.hashpw(password=pwd_bytes, salt=SALT).decode("utf-8")


def get_user(db: Session, username: str):
    """Get a user from the database."""
    return db.query(UserModel).filter(UserModel.username == username).first()

async def get_user_by_id(db: database_dependency, id: int):
    """Get a user from the database by id."""
    return await db.first(select(UserModel).filter_by(id=id))

def authenticate_user(db: Session, username: str, password: str):
    """Check if a user exists and the password is correct."""
    user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.password_hash):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=2)) -> str:
    """Create an JWT access token.

    The token will expire after a certain amount of time. If no expiration time is given,
        the token will expire after 2 hours.

    Args:
        data (dict): The data to encode in the token.
        expires_delta (timedelta | None, optional): The time after which the token will expire. Defaults to 2 hours.

    Returns:
        str: _description_
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + expires_delta
    to_encode.update({"exp": expire.timestamp()})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[Session, Depends(get_db)]
) -> UserModel:
    """Get the current user. This function is a dependency for other functions that need to get the current user.

    Args:
        token (Annotated[str, Depends(oauth2_scheme)]): The authentication token.
        db (Annotated[Session, Depends(get_db)]): A database session.

    Returns:
        User: The current user.

    Raises:
        HTTPException: If the token is invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        expire_time: datetime = payload.get("exp")
        if username is None or expire_time is None or expire_time < datetime.now(UTC).timestamp():
            raise credentials_exception
    except JWTError:
        raise credentials_exception from JWTError
    user = get_user(db, username=username)
    if user is None:
        raise credentials_exception
    return User(
        username=user.username,
        index=user.id,
        role=user.role,
        user_group=user.user_group if user.user_group else "",
        privilages=user.privilages,
        password_hash=user.password_hash,
    )


@router.post("/token")
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: Annotated[Session, Depends(get_db)]
) -> Token:
    """Login to get an authentication token.

    Args:
        form_data (Annotated[OAuth2PasswordRequestForm, Depends()]): The form data to authenticate the user.
        db (Annotated[Session, Depends(get_db)]): The database session.

    Returns:
        Token: The authentication token.
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    return Token(access_token=access_token, token_type="bearer")  # NOQA:S106

@router.post("/login-with-invite")
async def loginWithInvite(
    data: dict,
    db: Annotated[database_dependency, Depends()]
) -> dict:
    try:
        invite = await db.first(select(Invite).filter_by(code=data['code']))
        user = await get_user_by_id(db, invite.invitee)
        username: str = user.username
        tokens = dict(await generate_tokens({"id": user.id, "sub": user.username}))
        tokens.update({"username": username, "problem_id": invite.problem_id})
    except JWTError:
        raise credentials_exception from JWTError
    return tokens