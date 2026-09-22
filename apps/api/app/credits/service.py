from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditAccount, CreditLedgerEntry, CreditReservation

CreditOperation = Literal["grant", "reserve", "commit", "refund"]


class CreditError(ValueError):
    pass


class InsufficientCredits(CreditError):
    pass


class CreditIdempotencyConflict(CreditError):
    pass


class CreditReservationNotFound(CreditError):
    pass


class CreditReservationStateError(CreditError):
    pass


@dataclass(slots=True)
class CreditMutation:
    account: CreditAccount
    ledger: CreditLedgerEntry
    reservation: CreditReservation | None
    applied: bool


async def _locked_account(session: AsyncSession, owner_user_id: str) -> CreditAccount:
    await session.execute(
        pg_insert(CreditAccount)
        .values(owner_user_id=owner_user_id, available_credits=0, reserved_credits=0)
        .on_conflict_do_nothing(index_elements=[CreditAccount.owner_user_id])
    )
    account = await session.scalar(
        select(CreditAccount)
        .where(CreditAccount.owner_user_id == owner_user_id)
        .with_for_update()
    )
    if account is None:
        raise RuntimeError("credit account could not be created")
    return account


async def _idempotent_result(
    session: AsyncSession,
    account: CreditAccount,
    *,
    idempotency_key: str,
    operation: CreditOperation,
    amount: int,
    reference_type: str,
    reference_key: str,
) -> CreditMutation | None:
    existing = await session.scalar(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.account_id == account.id,
            CreditLedgerEntry.idempotency_key == idempotency_key,
        )
    )
    if existing is None:
        return None
    if (
        existing.operation != operation
        or existing.amount != amount
        or existing.reference_type != reference_type
        or existing.reference_key != reference_key
    ):
        raise CreditIdempotencyConflict("idempotency key was reused with different credit input")
    reservation = (
        await session.get(CreditReservation, existing.reservation_id)
        if existing.reservation_id
        else None
    )
    return CreditMutation(account=account, ledger=existing, reservation=reservation, applied=False)


def _require_amount(amount: int) -> None:
    if isinstance(amount, bool) or amount < 1:
        raise CreditError("credit amount must be a positive integer")


def _entry(
    *,
    account: CreditAccount,
    reservation: CreditReservation | None,
    operation: CreditOperation,
    amount: int,
    idempotency_key: str,
    reference_type: str,
    reference_key: str,
    metadata: dict[str, Any] | None,
) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        account_id=account.id,
        reservation_id=reservation.id if reservation else None,
        operation=operation,
        amount=amount,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_key=reference_key,
        available_after=account.available_credits,
        reserved_after=account.reserved_credits,
        metadata_json=dict(metadata or {}),
    )


async def grant_credits(
    session: AsyncSession,
    *,
    owner_user_id: str,
    amount: int,
    idempotency_key: str,
    reference_type: str,
    reference_key: str,
    metadata: dict[str, Any] | None = None,
) -> CreditMutation:
    _require_amount(amount)
    account = await _locked_account(session, owner_user_id)
    duplicate = await _idempotent_result(
        session,
        account,
        idempotency_key=idempotency_key,
        operation="grant",
        amount=amount,
        reference_type=reference_type,
        reference_key=reference_key,
    )
    if duplicate:
        return duplicate
    account.available_credits += amount
    account.updated_at = datetime.now(UTC)
    ledger = _entry(
        account=account,
        reservation=None,
        operation="grant",
        amount=amount,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_key=reference_key,
        metadata=metadata,
    )
    session.add(ledger)
    await session.flush()
    return CreditMutation(account=account, ledger=ledger, reservation=None, applied=True)


async def reserve_credits(
    session: AsyncSession,
    *,
    owner_user_id: str,
    amount: int,
    reservation_key: str,
    idempotency_key: str,
    reference_type: str,
    reference_key: str,
    metadata: dict[str, Any] | None = None,
) -> CreditMutation:
    _require_amount(amount)
    account = await _locked_account(session, owner_user_id)
    duplicate = await _idempotent_result(
        session,
        account,
        idempotency_key=idempotency_key,
        operation="reserve",
        amount=amount,
        reference_type=reference_type,
        reference_key=reference_key,
    )
    if duplicate:
        return duplicate

    existing_reservation = await session.scalar(
        select(CreditReservation).where(
            CreditReservation.account_id == account.id,
            CreditReservation.reservation_key == reservation_key,
        )
    )
    if existing_reservation is not None:
        raise CreditIdempotencyConflict("reservation key already exists")
    if account.available_credits < amount:
        raise InsufficientCredits("insufficient available credits")

    account.available_credits -= amount
    account.reserved_credits += amount
    account.updated_at = datetime.now(UTC)
    reservation = CreditReservation(
        account_id=account.id,
        reservation_key=reservation_key,
        amount=amount,
        status="reserved",
        reference_type=reference_type,
        reference_key=reference_key,
        metadata_json=dict(metadata or {}),
    )
    session.add(reservation)
    await session.flush()
    ledger = _entry(
        account=account,
        reservation=reservation,
        operation="reserve",
        amount=amount,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_key=reference_key,
        metadata=metadata,
    )
    session.add(ledger)
    await session.flush()
    return CreditMutation(account=account, ledger=ledger, reservation=reservation, applied=True)


async def _settle(
    session: AsyncSession,
    *,
    owner_user_id: str,
    reservation_key: str,
    idempotency_key: str,
    operation: Literal["commit", "refund"],
    metadata: dict[str, Any] | None = None,
) -> CreditMutation:
    account = await _locked_account(session, owner_user_id)
    reservation = await session.scalar(
        select(CreditReservation)
        .where(
            CreditReservation.account_id == account.id,
            CreditReservation.reservation_key == reservation_key,
        )
        .with_for_update()
    )
    if reservation is None:
        raise CreditReservationNotFound("credit reservation was not found")

    duplicate = await _idempotent_result(
        session,
        account,
        idempotency_key=idempotency_key,
        operation=operation,
        amount=reservation.amount,
        reference_type=reservation.reference_type,
        reference_key=reservation.reference_key,
    )
    if duplicate:
        return duplicate
    if reservation.status != "reserved":
        raise CreditReservationStateError(
            f"reservation is already terminal: {reservation.status}"
        )
    if account.reserved_credits < reservation.amount:
        raise CreditReservationStateError("reserved credit balance is inconsistent")

    account.reserved_credits -= reservation.amount
    if operation == "refund":
        account.available_credits += reservation.amount
    account.updated_at = datetime.now(UTC)
    reservation.status = "committed" if operation == "commit" else "refunded"
    reservation.settled_at = datetime.now(UTC)

    ledger = _entry(
        account=account,
        reservation=reservation,
        operation=operation,
        amount=reservation.amount,
        idempotency_key=idempotency_key,
        reference_type=reservation.reference_type,
        reference_key=reservation.reference_key,
        metadata=metadata,
    )
    session.add(ledger)
    await session.flush()
    return CreditMutation(account=account, ledger=ledger, reservation=reservation, applied=True)


async def commit_credits(
    session: AsyncSession,
    *,
    owner_user_id: str,
    reservation_key: str,
    idempotency_key: str,
    metadata: dict[str, Any] | None = None,
) -> CreditMutation:
    return await _settle(
        session,
        owner_user_id=owner_user_id,
        reservation_key=reservation_key,
        idempotency_key=idempotency_key,
        operation="commit",
        metadata=metadata,
    )


async def refund_credits(
    session: AsyncSession,
    *,
    owner_user_id: str,
    reservation_key: str,
    idempotency_key: str,
    metadata: dict[str, Any] | None = None,
) -> CreditMutation:
    return await _settle(
        session,
        owner_user_id=owner_user_id,
        reservation_key=reservation_key,
        idempotency_key=idempotency_key,
        operation="refund",
        metadata=metadata,
    )
