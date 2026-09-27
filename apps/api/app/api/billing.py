"""Disabled-by-default raw-body sandbox webhook; no cookie or demo identity."""
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.contract import MAX_BODY_BYTES, BillingInputError, parse_event, verify_signature
from app.billing.service import BillingConflict, process_event
from app.config import Settings, get_settings
from app.db import get_session

router = APIRouter(prefix="/api/v1/billing", tags=["sandbox billing"])


@router.post("/stripe")
async def stripe_sandbox(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    if not settings.billing_sandbox_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if settings.billing_sandbox_scope is None or settings.billing_stripe_webhook_secret is None:
        raise HTTPException(status_code=503, detail="Sandbox billing is unavailable")
    # Reject repeated headers instead of allowing a proxy/framework to choose one.
    signatures = request.headers.getlist("stripe-signature")
    if len(signatures) != 1:
        raise HTTPException(status_code=400, detail="Invalid sandbox billing input")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Sandbox billing request is too large")
        body.extend(chunk)
    try:
        raw = bytes(body)
        verify_signature(
            raw, signatures[0], settings.billing_stripe_webhook_secret.get_secret_value()
        )
        event = parse_event(raw)
        result = await process_event(session, scope=settings.billing_sandbox_scope, event=event)
        await session.commit()
    except BillingInputError:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Invalid sandbox billing input") from None
    except BillingConflict:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Sandbox billing replay conflicts") from None
    return asdict(result)
