import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.credits import grant_credits
from app.extraction.deterministic import DeterministicExtractor
from app.extraction.schemas import ExtractionResult
from app.models import (
    CreditAccount,
    CreditLedgerEntry,
    CreditReservation,
    JobFailure,
    StructuredExtraction,
)
from app.workers.extraction import extract_version
from tests.extraction.test_persistence import seeded as _seeded

seeded = _seeded


@pytest.mark.asyncio
async def test_operator_cli_grant_is_idempotent_and_status_does_not_create_accounts(
    worker_session_factory,
    monkeypatch,
):
    from argparse import Namespace

    from app.ops.extraction_credits import run

    monkeypatch.setattr("app.ops.extraction_credits.SessionLocal", worker_session_factory)
    status = Namespace(command="status", account="pipeline-budget")
    assert await run(status) == {"exists": False}
    grant = Namespace(command="grant", account="pipeline-budget", units=5, request_id="fund-1")
    assert await run(grant) == {"applied": True, "available": 5}
    assert await run(grant) == {"applied": False, "available": 5}
    assert await run(status) == {
        "exists": True,
        "available": 5,
        "reserved": 0,
        "holds": [],
        "holds_limit": 100,
    }


@pytest.mark.asyncio
async def test_input_change_between_reservation_and_call_refunds_without_io(
    seeded,
    worker_session_factory,
    billing,
    monkeypatch,
):
    from app.credits.extraction import reserve_extraction
    from app.models import Attachment, DocumentParse

    await fund(worker_session_factory)

    async def change_after_reservation(session, version_id, key, policy):
        ticket = await reserve_extraction(session, version_id, key, policy)
        async with worker_session_factory() as other:
            rows = list(
                await other.scalars(
                    select(DocumentParse)
                    .join(Attachment)
                    .where(
                        Attachment.opportunity_version_id == version_id,
                    )
                )
            )
            for row in rows:
                row.status = "needs_ocr"
            await other.commit()
        return ticket

    monkeypatch.setattr("app.extraction.service.reserve_extraction", change_after_reservation)
    provider = ControlledProvider()
    result = await extract_version(
        {"session_factory": worker_session_factory, "extractor": provider}, str(seeded)
    )
    assert result["status"] == "stale"
    assert provider.calls == 0
    assert (await balances(worker_session_factory))[:4] == (5, 0, ["refunded"], 0)


@pytest.mark.asyncio
async def test_preexisting_unbilled_result_is_not_retroactively_charged(
    seeded,
    worker_session_factory,
    billing,
):
    await fund(worker_session_factory)
    billing.extraction_credits_enabled = False
    provider = ControlledProvider()
    ctx = {"session_factory": worker_session_factory, "extractor": provider}
    assert (await extract_version(ctx, str(seeded)))["status"] == "validated"
    billing.extraction_credits_enabled = True
    assert (await extract_version(ctx, str(seeded)))["status"] == "validated"
    assert provider.calls == 1
    assert (await balances(worker_session_factory))[:4] == (5, 0, [], 1)


@pytest.mark.asyncio
async def test_different_extractions_cannot_spend_the_same_budget(
    seeded,
    worker_session_factory,
    billing,
):
    await fund(worker_session_factory, 2)
    first, second = ControlledProvider(), ControlledProvider()
    second.model = "different-controlled-model"
    outcomes = await asyncio.gather(
        *[
            extract_version(
                {"session_factory": worker_session_factory, "extractor": provider}, str(seeded)
            )
            for provider in (first, second)
        ]
    )
    assert sorted(r["status"] for r in outcomes) == ["dead_lettered", "validated"]
    assert first.calls + second.calls == 1
    assert (await balances(worker_session_factory))[:4] == (0, 0, ["committed"], 1)


class ControlledProvider(DeterministicExtractor):
    provider = "synthetic-provider"
    model = "controlled-response"

    def __init__(self, before_response=None, invalid=False):
        self.calls = 0
        self.before_response = before_response
        self.invalid = invalid

    async def extract(self, document):
        self.calls += 1
        if self.before_response:
            await self.before_response()
        if self.invalid:
            return ExtractionResult(output={"title": "ungrounded"})
        return await super().extract(document)


@pytest.fixture
def billing(monkeypatch):
    settings = Settings(
        _env_file=None,
        extraction_mode="hosted",
        extraction_credits_enabled=True,
        extraction_credit_account="pipeline-budget",
        extraction_credit_units=2,
    )
    monkeypatch.setattr("app.workers.extraction.get_settings", lambda: settings)
    return settings


async def fund(factory, amount=5):
    async with factory() as session:
        await grant_credits(
            session,
            owner_user_id="pipeline-budget",
            amount=amount,
            idempotency_key="grant",
            reference_type="test",
            reference_key="budget",
        )
        await session.commit()


async def balances(factory):
    async with factory() as session:
        account = await session.scalar(select(CreditAccount))
        reservations = list(await session.scalars(select(CreditReservation)))
        results = await session.scalar(select(func.count()).select_from(StructuredExtraction))
        operations = list(await session.scalars(select(CreditLedgerEntry.operation)))
        return (
            account.available_credits,
            account.reserved_credits,
            [r.status for r in reservations],
            results,
            operations,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_worker_reserves_before_io_and_settles_result_once(
    seeded,
    worker_session_factory,
    billing,
    invalid,
):
    await fund(worker_session_factory)

    async def inspect_committed_reservation():
        available, reserved, states, count, _ = await balances(worker_session_factory)
        assert (available, reserved, states, count) == (3, 2, ["reserved"], 0)

    provider = ControlledProvider(inspect_committed_reservation, invalid)
    ctx = {"session_factory": worker_session_factory, "extractor": provider}
    first = await extract_version(ctx, str(seeded))
    assert first["status"] == ("rejected" if invalid else "validated")
    assert (await extract_version(ctx, str(seeded)))["status"] == first["status"]
    assert provider.calls == 1
    available, reserved, states, count, ops = await balances(worker_session_factory)
    assert (available, reserved, states, count) == (3, 0, ["committed"], 1)
    assert sorted(ops) == ["commit", "grant", "reserve"]


@pytest.mark.asyncio
async def test_insufficient_balance_blocks_provider(seeded, worker_session_factory, billing):
    await fund(worker_session_factory, 1)
    provider = ControlledProvider()
    result = await extract_version(
        {"session_factory": worker_session_factory, "extractor": provider}, str(seeded)
    )
    assert result["status"] == "dead_lettered"
    assert provider.calls == 0
    assert (await balances(worker_session_factory))[:4] == (1, 0, [], 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "disable", "account"])
async def test_ambiguous_call_never_automatically_replays_or_refunds(
    seeded,
    worker_session_factory,
    billing,
    change,
):
    await fund(worker_session_factory)

    async def timeout():
        raise TimeoutError("provider response lost; private data must not persist")

    provider = ControlledProvider(timeout)
    ctx = {"session_factory": worker_session_factory, "extractor": provider}
    assert (await extract_version(ctx, str(seeded)))["status"] == "dead_lettered"
    async with worker_session_factory() as session:
        failure = await session.scalar(select(JobFailure))
        assert failure.error_class == "ExtractionCreditReviewRequired"
        assert "private" not in failure.error_message
        # Operator retry alone is not permission for another provider call.
        failure.attempts, failure.dead_lettered = 0, False
        await session.commit()
    if change == "disable":
        billing.extraction_credits_enabled = False
    elif change == "account":
        billing.extraction_credit_account = "different-account"
    await extract_version(ctx, str(seeded))
    assert provider.calls == 1
    assert (await balances(worker_session_factory))[:4] == (3, 2, ["reserved"], 0)


@pytest.mark.asyncio
async def test_cancelled_call_keeps_durable_hold(seeded, worker_session_factory, billing):
    await fund(worker_session_factory)
    started = asyncio.Event()

    async def wait_forever():
        started.set()
        await asyncio.Event().wait()

    provider = ControlledProvider(wait_forever)
    ctx = {"session_factory": worker_session_factory, "extractor": provider}
    task = asyncio.create_task(extract_version(ctx, str(seeded)))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await extract_version(ctx, str(seeded)))["status"] == "dead_lettered"
    assert provider.calls == 1
    assert (await balances(worker_session_factory))[:4] == (3, 2, ["reserved"], 0)


@pytest.mark.asyncio
async def test_concurrent_workers_share_result_and_one_debit(
    seeded,
    worker_session_factory,
    billing,
):
    await fund(worker_session_factory)
    started, release = asyncio.Event(), asyncio.Event()

    async def pause():
        started.set()
        await release.wait()

    provider = ControlledProvider(pause)
    ctx = {"session_factory": worker_session_factory, "extractor": provider}
    first = asyncio.create_task(extract_version(ctx, str(seeded)))
    await asyncio.wait_for(started.wait(), 5)
    second = asyncio.create_task(extract_version(ctx, str(seeded)))
    release.set()
    outcomes = await asyncio.wait_for(asyncio.gather(first, second), 10)
    assert {r["status"] for r in outcomes} == {"validated"}
    assert provider.calls == 1
    assert (await balances(worker_session_factory))[:4] == (3, 0, ["committed"], 1)


@pytest.mark.asyncio
async def test_result_and_debit_roll_back_together_on_settlement_failure(
    seeded,
    worker_session_factory,
    billing,
):
    await fund(worker_session_factory)

    def fail_settlement(session, context, instances):
        if any(
            isinstance(row, CreditLedgerEntry) and row.operation == "commit" for row in session.new
        ):
            raise RuntimeError("injected persistence failure")

    provider = ControlledProvider()
    event.listen(Session, "before_flush", fail_settlement)
    try:
        result = await extract_version(
            {"session_factory": worker_session_factory, "extractor": provider}, str(seeded)
        )
    finally:
        event.remove(Session, "before_flush", fail_settlement)
    assert result["status"] == "dead_lettered"
    assert provider.calls == 1
    assert (await balances(worker_session_factory))[:4] == (3, 2, ["reserved"], 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["commit", "refund"])
async def test_operator_settlement_requires_aged_hold_and_does_not_enable_recall(
    seeded,
    worker_session_factory,
    billing,
    decision,
):
    from app.credits.extraction import resolve_extraction_reservation

    await fund(worker_session_factory)

    async def timeout():
        raise TimeoutError()

    provider = ControlledProvider(timeout)
    ctx = {"session_factory": worker_session_factory, "extractor": provider}
    await extract_version(ctx, str(seeded))
    async with worker_session_factory() as session:
        reservation = await session.scalar(select(CreditReservation))
        key = reservation.reservation_key
        with pytest.raises(ValueError, match="recent"):
            await resolve_extraction_reservation(session, "pipeline-budget", key, decision)
        await session.rollback()
        reservation = await session.scalar(select(CreditReservation))
        reservation.created_at = datetime.now(UTC) - timedelta(minutes=5)
        await session.commit()
        await resolve_extraction_reservation(session, "pipeline-budget", key, decision)
        await session.commit()
        await resolve_extraction_reservation(session, "pipeline-budget", key, decision)
        await session.commit()
        failure = await session.scalar(select(JobFailure))
        failure.attempts, failure.dead_lettered = 0, False
        await session.commit()
    await extract_version(ctx, str(seeded))
    assert provider.calls == 1
    expected = (3, 0, ["committed"], 0) if decision == "commit" else (5, 0, ["refunded"], 0)
    assert (await balances(worker_session_factory))[:4] == expected
