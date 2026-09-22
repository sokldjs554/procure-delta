"""Exercise the real PostgreSQL credit ledger inside the isolated benchmark database."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))


async def measure(url: str) -> dict[str, object]:
    from app.credits import (
        InsufficientCredits,
        commit_credits,
        grant_credits,
        refund_credits,
        reserve_credits,
    )
    from app.evaluation.performance import require_benchmark_database
    from app.models import CreditAccount, CreditLedgerEntry, CreditReservation

    require_benchmark_database(url)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner = "synthetic-credit-evidence-" + uuid4().hex
    started = time.perf_counter()
    try:
        async with factory() as session:
            first = await grant_credits(
                session,
                owner_user_id=owner,
                amount=5,
                idempotency_key="grant-initial",
                reference_type="synthetic_verification",
                reference_key="trial",
            )
            await session.commit()
            grant_applied = first.applied

        async with factory() as session:
            duplicate = await grant_credits(
                session,
                owner_user_id=owner,
                amount=5,
                idempotency_key="grant-initial",
                reference_type="synthetic_verification",
                reference_key="trial",
            )
            await session.commit()
            duplicate_suppressed = duplicate.applied is False

        async def attempt(key: str) -> tuple[str, str]:
            async with factory() as session:
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
                    return ("reserved", key)
                except InsufficientCredits:
                    await session.rollback()
                    return ("insufficient", key)

        attempts = await asyncio.gather(attempt("doc-a"), attempt("doc-b"))
        winners = [key for status, key in attempts if status == "reserved"]
        insufficient = sum(status == "insufficient" for status, _ in attempts)
        if len(winners) != 1:
            raise RuntimeError("credit concurrency drill did not produce exactly one reservation")

        async with factory() as session:
            refunded = await refund_credits(
                session,
                owner_user_id=owner,
                reservation_key=winners[0],
                idempotency_key="refund-concurrent-winner",
            )
            await session.commit()
            refund_restored = (
                refunded.account.available_credits == 5
                and refunded.account.reserved_credits == 0
            )

        async with factory() as session:
            await reserve_credits(
                session,
                owner_user_id=owner,
                amount=2,
                reservation_key="commit-path",
                idempotency_key="reserve-commit-path",
                reference_type="ocr",
                reference_key="scan-1",
            )
            committed = await commit_credits(
                session,
                owner_user_id=owner,
                reservation_key="commit-path",
                idempotency_key="commit-path",
            )
            await session.commit()
            commit_finalized = (
                committed.reservation is not None
                and committed.reservation.status == "committed"
            )

        async with factory() as session:
            account = await session.scalar(
                select(CreditAccount).where(CreditAccount.owner_user_id == owner)
            )
            if account is None:
                raise RuntimeError("credit account disappeared during verification")
            ledger_entries = int(
                await session.scalar(
                    select(func.count())
                    .select_from(CreditLedgerEntry)
                    .where(CreditLedgerEntry.account_id == account.id)
                )
                or 0
            )
            reservations = int(
                await session.scalar(
                    select(func.count())
                    .select_from(CreditReservation)
                    .where(CreditReservation.account_id == account.id)
                )
                or 0
            )
            ledger_id = await session.scalar(
                select(CreditLedgerEntry.id)
                .where(CreditLedgerEntry.account_id == account.id)
                .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
                .limit(1)
            )
            if ledger_id is None:
                raise RuntimeError("credit ledger evidence row is missing")
            available_after = account.available_credits
            reserved_after = account.reserved_credits

        async def update_rejected() -> bool:
            async with factory() as session:
                try:
                    await session.execute(
                        update(CreditLedgerEntry)
                        .where(CreditLedgerEntry.id == ledger_id)
                        .values(amount=99)
                    )
                    await session.commit()
                    return False
                except DBAPIError as exc:
                    await session.rollback()
                    return "credit ledger entries are immutable" in str(exc).lower()

        async def delete_rejected() -> bool:
            async with factory() as session:
                try:
                    await session.execute(
                        delete(CreditLedgerEntry).where(CreditLedgerEntry.id == ledger_id)
                    )
                    await session.commit()
                    return False
                except DBAPIError as exc:
                    await session.rollback()
                    return "credit ledger entries are immutable" in str(exc).lower()

        immutable_update = await update_rejected()
        immutable_delete = await delete_rejected()
        overspend_prevented = (
            sum(status == "reserved" for status, _ in attempts) == 1
            and insufficient == 1
        )
        successful = all(
            (
                grant_applied,
                duplicate_suppressed,
                overspend_prevented,
                refund_restored,
                commit_finalized,
                immutable_update,
                immutable_delete,
                available_after == 3,
                reserved_after == 0,
                ledger_entries == 5,
                reservations == 2,
            )
        )
        return {
            "scope": "real_postgresql_credit_ledger",
            "synthetic": True,
            "concurrent_requests": 2,
            "successful_reservations": 1,
            "insufficient_rejections": insufficient,
            "overspend_prevented": overspend_prevented,
            "duplicate_request_suppressed": duplicate_suppressed,
            "refund_restored": refund_restored,
            "commit_finalized": commit_finalized,
            "immutable_update_rejected": immutable_update,
            "immutable_delete_rejected": immutable_delete,
            "ledger_entries": ledger_entries,
            "reservations": reservations,
            "available_after": available_after,
            "reserved_after": reserved_after,
            "elapsed_seconds": time.perf_counter() - started,
            "successful": successful,
            "limitation": (
                "Synthetic isolated PostgreSQL ledger drill; no external PG, "
                "subscription webhook, or production billing traffic."
            ),
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/performance/credit.json",
    )
    args = parser.parse_args()
    from app.evaluation.provenance import write_artifact

    result = asyncio.run(measure(os.environ["BENCH_DATABASE_URL"]))
    write_artifact(args.output, result, "Transactional credit ledger verification")
    if result["successful"] is not True:
        raise SystemExit("credit ledger verification failed; inspect the artifact")
    print(args.output)


if __name__ == "__main__":
    main()
