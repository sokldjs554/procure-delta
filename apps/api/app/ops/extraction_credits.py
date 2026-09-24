"""Trusted operator CLI. No account funding or settlement endpoint is exposed."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import cast

from sqlalchemy import select

from app.credits import grant_credits
from app.credits.extraction import REFERENCE_TYPE, resolve_extraction_reservation
from app.db import SessionLocal
from app.models import CreditAccount, CreditReservation


async def run(args: argparse.Namespace) -> dict[str, object]:
    async with SessionLocal() as session:
        if args.command == "grant":
            result = await grant_credits(
                session,
                owner_user_id=args.account,
                amount=args.units,
                idempotency_key=args.request_id,
                reference_type="operator_budget",
                reference_key=args.request_id,
                metadata={"reason": "explicit_operator_funding"},
            )
            await session.commit()
            return {"applied": result.applied, "available": result.account.available_credits}
        if args.command == "resolve":
            from typing import Literal

            state = await resolve_extraction_reservation(
                session,
                args.account,
                args.reservation,
                cast(Literal["commit", "refund"], args.decision),
            )
            await session.commit()
            return {"status": state, "provider_replay_authorized": False}
        account = await session.scalar(
            select(CreditAccount).where(
                CreditAccount.owner_user_id == args.account,
            )
        )
        if account is None:
            return {"exists": False}
        rows = list(
            await session.scalars(
                select(CreditReservation)
                .where(
                    CreditReservation.account_id == account.id,
                    CreditReservation.reference_type == REFERENCE_TYPE,
                    CreditReservation.status == "reserved",
                )
                .order_by(CreditReservation.created_at)
                .limit(100)
            )
        )
        return {
            "exists": True,
            "available": account.available_credits,
            "reserved": account.reserved_credits,
            "holds": [
                {
                    "reservation": row.reservation_key,
                    "units": row.amount,
                    "version_id": row.reference_key,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
            "holds_limit": 100,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "grant", "resolve"):
        command = commands.add_parser(name)
        command.add_argument("--account", required=True)
        if name == "grant":
            command.add_argument("--units", type=int, required=True)
            command.add_argument("--request-id", required=True)
        elif name == "resolve":
            command.add_argument("--reservation", required=True)
            command.add_argument("--decision", choices=("commit", "refund"), required=True)
    args = parser.parse_args()
    if not args.account.strip() or len(args.account) > 255:
        parser.error("account must contain 1..255 characters")
    if args.command == "grant" and (
        not 1 <= args.units <= 1_000_000 or not 1 <= len(args.request_id) <= 255
    ):
        parser.error("grant requires positive bounded units and a 1..255 character request ID")
    try:
        print(json.dumps(asyncio.run(run(args))))
    except Exception as error:
        # Operator output is safe to retain; DB URLs and provider text never print.
        print(json.dumps({"error": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
