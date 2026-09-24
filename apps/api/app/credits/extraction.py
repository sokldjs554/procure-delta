"""Durable credit fence for operator-funded shared extraction jobs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.credits.service import commit_credits, refund_credits, reserve_credits
from app.models import CreditAccount, CreditReservation, OpportunityVersion

REFERENCE_TYPE = "pipeline_hosted_extraction_v1"


class ExtractionCreditReviewRequired(RuntimeError):
    """An earlier durable attempt cannot be automatically repeated or refunded."""


@dataclass(frozen=True)
class ExtractionCreditPolicy:
    account: str
    units: int

    @classmethod
    def from_settings(cls, settings: Settings) -> ExtractionCreditPolicy | None:
        if not settings.extraction_credits_enabled:
            return None
        if settings.extraction_mode != "hosted" or not settings.extraction_credit_account:
            raise ValueError("hosted credit policy is incomplete")
        return cls(settings.extraction_credit_account, settings.extraction_credit_units)


def reservation_key(version_id: UUID, extraction_key: str) -> str:
    return "extraction:" + hashlib.sha256(f"{version_id}:{extraction_key}".encode()).hexdigest()


async def assert_no_prior_attempt(
    session: AsyncSession,
    version_id: UUID,
    extraction_key: str,
) -> None:
    # Caller holds the version lock. Account changes cannot evade this global fence.
    prior = await session.scalar(
        select(CreditReservation.id).where(
            CreditReservation.reference_type == REFERENCE_TYPE,
            CreditReservation.reservation_key == reservation_key(version_id, extraction_key),
        )
    )
    if prior is not None:
        raise ExtractionCreditReviewRequired("earlier extraction attempt requires review")


async def reserve_extraction(
    session: AsyncSession,
    version_id: UUID,
    extraction_key: str,
    policy: ExtractionCreditPolicy,
) -> str:
    key = reservation_key(version_id, extraction_key)
    await reserve_credits(
        session,
        owner_user_id=policy.account,
        amount=policy.units,
        reservation_key=key,
        idempotency_key=key + ":reserve",
        reference_type=REFERENCE_TYPE,
        reference_key=str(version_id),
        metadata={"extraction_key": extraction_key, "policy": "flat-logical-extraction-v1"},
    )
    # This must precede any provider I/O and survive the later transaction's rollback.
    await session.commit()
    return key


async def assert_open_reservation(session: AsyncSession, account: str, key: str) -> None:
    status = await session.scalar(
        select(CreditReservation.status)
        .join(CreditAccount)
        .where(
            CreditAccount.owner_user_id == account,
            CreditReservation.reservation_key == key,
            CreditReservation.reference_type == REFERENCE_TYPE,
        )
    )
    if status != "reserved":
        raise ExtractionCreditReviewRequired("extraction reservation is no longer open")


async def settle_extraction(
    session: AsyncSession,
    account: str,
    key: str,
    decision: Literal["commit", "refund"],
) -> None:
    settle = commit_credits if decision == "commit" else refund_credits
    await settle(
        session,
        owner_user_id=account,
        reservation_key=key,
        idempotency_key=key + ":" + decision,
        metadata={
            "reason": "result_persisted" if decision == "commit" else "input_changed_before_call"
        },
    )


async def resolve_extraction_reservation(
    session: AsyncSession,
    account: str,
    key: str,
    decision: Literal["commit", "refund"],
) -> str:
    if decision not in {"commit", "refund"}:
        raise ValueError("unsupported settlement decision")
    reservation = await session.scalar(
        select(CreditReservation)
        .join(CreditAccount)
        .where(
            CreditAccount.owner_user_id == account,
            CreditReservation.reservation_key == key,
            CreditReservation.reference_type == REFERENCE_TYPE,
        )
    )
    if reservation is None:
        raise ValueError("extraction reservation not found")
    # Same lock order as the worker: version then account. Never resolve an active call.
    await session.scalar(
        select(OpportunityVersion.id)
        .where(
            OpportunityVersion.id == UUID(reservation.reference_key),
        )
        .with_for_update()
    )
    await session.refresh(reservation)
    if reservation.created_at > datetime.now(UTC) - timedelta(seconds=120):
        raise ValueError("extraction reservation is too recent for manual resolution")
    settle = commit_credits if decision == "commit" else refund_credits
    await settle(
        session,
        owner_user_id=account,
        reservation_key=key,
        idempotency_key=key + ":operator:" + decision,
        metadata={"reason": "operator_confirmed_" + decision},
    )
    return "committed" if decision == "commit" else "refunded"
