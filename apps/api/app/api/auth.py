"""Synthetic demo identity only; not a production identity provider."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Awaitable
from typing import Annotated, Literal, cast
from uuid import uuid4

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.models import CompanyProfile

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
COOKIE = "procure_delta_session"
PREFIX = "procure-delta:api:"


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: str
    role: Literal["user", "operator"]
    csrf_token: str
    synthetic_demo: Literal[True] = True


class DemoLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator_secret: SecretStr | None = None


async def get_redis() -> AsyncIterator[ArqRedis]:
    redis = ArqRedis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        yield redis
    except RedisError as exc:
        raise HTTPException(503, "Session or queue service unavailable") from exc
    finally:
        await redis.aclose()


Redis = Annotated[ArqRedis, Depends(get_redis)]
Session = Annotated[AsyncSession, Depends(get_session)]


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in get_settings().cors_origins:
        raise HTTPException(403, "Origin is not allowed")


async def rate_limit(redis: ArqRedis, scope: str, actor: str, maximum: int) -> None:
    digest = hashlib.sha256(actor.encode()).hexdigest()
    # Increment and expiry are atomic, including the first request after restart.
    count = await cast(
        Awaitable[int],
        redis.eval(
            "local n=redis.call('INCR',KEYS[1]); "
            "if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            1,
            f"{PREFIX}rate:{scope}:{digest}",
        ),
    )
    if int(count) > maximum:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})


def session_key(token: str) -> str:
    return PREFIX + "session:" + hashlib.sha256(token.encode()).hexdigest()


async def current_actor(request: Request, redis: Redis) -> Actor:
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        raise HTTPException(401, "Demo login required")
    saved = await redis.get(session_key(token))
    if saved is None:
        raise HTTPException(401, "Session expired")
    actor = Actor.model_validate_json(saved)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), actor.csrf_token):
            raise HTTPException(403, "Valid CSRF token required")
    return actor


CurrentActor = Annotated[Actor, Depends(current_actor)]


async def get_current_owner_id(actor: CurrentActor) -> str:
    return actor.owner_id


Owner = Annotated[str, Depends(get_current_owner_id)]


async def require_operator(actor: CurrentActor) -> Actor:
    if actor.role != "operator":
        raise HTTPException(403, "Operator role required")
    return actor


Operator = Annotated[Actor, Depends(require_operator)]


@router.post("/demo-login", response_model=Actor)
async def demo_login(
    payload: DemoLogin, request: Request, response: Response, redis: Redis, session: Session
) -> Actor:
    settings = get_settings()
    if not settings.demo_auth_enabled:
        raise HTTPException(404, "Demo authentication disabled")
    check_origin(request)
    await rate_limit(redis, "login", request.client.host if request.client else "unknown", 10)
    role: Literal["user", "operator"] = "user"
    if payload.operator_secret is not None:
        expected = settings.demo_operator_secret
        if (
            not expected
            or not expected.get_secret_value()
            or not secrets.compare_digest(
                expected.get_secret_value(), payload.operator_secret.get_secret_value()
            )
        ):
            raise HTTPException(401, "Invalid operator credential")
        role = "operator"
    old_token = request.cookies.get(COOKIE)
    old = await redis.get(session_key(old_token)) if old_token and len(old_token) <= 128 else None
    if old is not None:
        previous = Actor.model_validate_json(old)
        if previous.role == role:
            return previous
    actor = Actor(
        owner_id="synthetic-session-" + uuid4().hex, role=role, csrf_token=secrets.token_urlsafe(32)
    )
    session.add(
        CompanyProfile(
            owner_user_id=actor.owner_id,
            display_name="Synthetic Demo Company",
            synthetic_demo=True,
            regions=["Seoul", "Gyeonggi"],
            industries=["services"],
            capabilities=["cloud migration", "document processing"],
            certifications=["ISO 27001"],
            contract_currency="KRW",
        )
    )
    await session.commit()
    token = secrets.token_urlsafe(32)
    await redis.set(session_key(token), actor.model_dump_json(), ex=settings.session_ttl_seconds)
    if old_token:
        await redis.delete(session_key(old_token))
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return actor


@router.get("/session", response_model=Actor)
async def session_info(actor: CurrentActor, response: Response) -> Actor:
    response.headers["Cache-Control"] = "no-store"
    return actor


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, actor: CurrentActor, redis: Redis) -> None:
    await redis.delete(session_key(request.cookies[COOKIE]))
    response.delete_cookie(
        COOKIE, path="/", secure=get_settings().session_cookie_secure, httponly=True, samesite="lax"
    )
