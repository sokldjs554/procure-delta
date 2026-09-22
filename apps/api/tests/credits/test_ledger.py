from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.credits import (
    CreditIdempotencyConflict,
    CreditReservationStateError,
    InsufficientCredits,
    commit_credits,
    grant_credits,
    refund_credits,
    reserve_credits,
)
from app.models import CreditAccount, CreditLedgerEntry, CreditReservation


@pytest.mark.asyncio
async def test_credit_lifecycle_is_balanced_and_append_only(session: AsyncSession) -> None:
    owner = "credit-owner"
    granted = await grant_credits(
        session,
        owner_user_id=owner,
        amount=10,
        idempotency_key="grant-1",
        reference_type="demo_plan",
        reference_key="trial",
    )
    assert granted.account.available_credits == 10
    assert granted.account.reserved_credits == 0

    reserved = await reserve_credits(
        session,
        owner_user_id=owner,
        amount=4,
        reservation_key="llm:doc-1",
        idempotency_key="reserve-1",
        reference_type="hosted_extraction",
        reference_key="doc-1",
    )
    assert reserved.account.available_credits == 6
    assert reserved.account.reserved_credits == 4

    committed = await commit_credits(
        session,
        owner_user_id=owner,
        reservation_key="llm:doc-1",
        idempotency_key="commit-1",
    )
    assert committed.account.available_credits == 6
    assert committed.account.reserved_credits == 0
    assert committed.reservation is not None
    assert committed.reservation.status == "committed"

    await reserve_credits(
        session,
        owner_user_id=owner,
        amount=3,
        reservation_key="ocr:doc-2",
        idempotency_key="reserve-2",
        reference_type="ocr",
        reference_key="doc-2",
    )
    refunded = await refund_credits(
        session,
        owner_user_id=owner,
        reservation_key="ocr:doc-2",
        idempotency_key="refund-1",
    )
    assert refunded.account.available_credits == 6
    assert refunded.account.reserved_credits == 0
    assert refunded.reservation is not None
    assert refunded.reservation.status == "refunded"

    assert await session.scalar(select(func.count()).select_from(CreditLedgerEntry)) == 5
    reservations = list(await session.scalars(select(CreditReservation)))
    assert {row.status for row in reservations} == {"committed", "refunded"}


@pytest.mark.asyncio
async def test_credit_idempotency_does_not_double_apply(session: AsyncSession) -> None:
    first = await grant_credits(
        session,
        owner_user_id="idem-owner",
        amount=5,
        idempotency_key="same-request",
        reference_type="plan",
        reference_key="starter",
    )
    second = await grant_credits(
        session,
        owner_user_id="idem-owner",
        amount=5,
        idempotency_key="same-request",
        reference_type="plan",
        reference_key="starter",
    )

    assert first.applied is True
    assert second.applied is False
    assert second.ledger.id == first.ledger.id
    assert second.account.available_credits == 5
    assert await session.scalar(select(func.count()).select_from(CreditLedgerEntry)) == 1

    with pytest.raises(CreditIdempotencyConflict):
        await grant_credits(
            session,
            owner_user_id="idem-owner",
            amount=6,
            idempotency_key="same-request",
            reference_type="plan",
            reference_key="starter",
        )


@pytest.mark.asyncio
async def test_credit_reservation_rejects_overspend_and_terminal_reuse(
    session: AsyncSession,
) -> None:
    owner = "guard-owner"
    await grant_credits(
        session,
        owner_user_id=owner,
        amount=3,
        idempotency_key="grant",
        reference_type="plan",
        reference_key="trial",
    )
    with pytest.raises(InsufficientCredits):
        await reserve_credits(
            session,
            owner_user_id=owner,
            amount=4,
            reservation_key="too-much",
            idempotency_key="reserve-too-much",
            reference_type="llm",
            reference_key="doc",
        )

    await reserve_credits(
        session,
        owner_user_id=owner,
        amount=2,
        reservation_key="valid",
        idempotency_key="reserve-valid",
        reference_type="llm",
        reference_key="doc",
    )
    await commit_credits(
        session,
        owner_user_id=owner,
        reservation_key="valid",
        idempotency_key="commit-valid",
    )
    with pytest.raises(CreditReservationStateError):
        await refund_credits(
            session,
            owner_user_id=owner,
            reservation_key="valid",
            idempotency_key="late-refund",
        )


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_overspend(
    worker_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = "concurrent-owner"
    async with worker_session_factory() as setup:
        await grant_credits(
            setup,
            owner_user_id=owner,
            amount=5,
            idempotency_key="initial-grant",
            reference_type="plan",
            reference_key="trial",
        )
        await setup.commit()

    async def attempt(key: str) -> str:
        async with worker_session_factory() as session:
            try:
                await reserve_credits(
                    session,
                    owner_user_id=owner,
                    amount=4,
                    reservation_key=key,
                    idempotency_key=f"reserve:{key}",
                    reference_type="hosted_extraction",
                    reference_key=key,
                )
                await session.commit()
                return "reserved"
            except InsufficientCredits:
                await session.rollback()
                return "insufficient"

    outcomes = await asyncio.gather(attempt("doc-a"), attempt("doc-b"))
    assert sorted(outcomes) == ["insufficient", "reserved"]

    async with worker_session_factory() as verify:
        account = await verify.scalar(
            select(CreditAccount).where(CreditAccount.owner_user_id == owner)
        )
        assert account is not None
        assert account.available_credits == 1
        assert account.reserved_credits == 4
        assert (
            await verify.scalar(
                select(func.count())
                .select_from(CreditReservation)
                .where(CreditReservation.account_id == account.id)
            )
            == 1
        )
