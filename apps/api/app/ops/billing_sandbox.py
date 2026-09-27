"""Operator-only sandbox bindings; no payment or subscription API is called."""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import func, select

from app.billing.contract import require_scope
from app.billing.service import register_customer, register_price
from app.db import SessionLocal
from app.models import BillingEventObservation, BillingInvoiceApplication


async def run(args: argparse.Namespace) -> dict[str, object]:
    require_scope(args.scope)
    async with SessionLocal() as session:
        if args.command == "customer":
            mapping = await register_customer(session, scope=args.scope, customer_id=args.customer)
            await session.commit()
            return {"account_kind": "billing_sandbox", "account_id": str(mapping.account_id)}
        if args.command == "price":
            policy = await register_price(
                session, scope=args.scope, price_id=args.price,
                currency=args.currency, amount=args.amount, units=args.units
            )
            await session.commit()
            return {"policy_id": str(policy.id), "credit_units": policy.credit_units}
        return {
            "scope": args.scope,
            "observations": await session.scalar(select(func.count()).select_from(
                BillingEventObservation).where(BillingEventObservation.scope == args.scope)),
            "applications": await session.scalar(select(func.count()).select_from(
                BillingInvoiceApplication).where(BillingInvoiceApplication.scope == args.scope)),
            "review_required": await session.scalar(select(func.count()).select_from(
                BillingEventObservation).where(BillingEventObservation.scope == args.scope,
                                              BillingEventObservation.outcome == "review")),
            "evidence": "synthetic_sandbox_contract_only",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("customer", "price", "status"):
        command = commands.add_parser(name)
        command.add_argument("--scope", required=True)
        if name == "customer":
            command.add_argument("--customer", required=True)
        elif name == "price":
            command.add_argument("--price", required=True)
            command.add_argument("--currency", required=True)
            command.add_argument("--amount", type=int, required=True)
            command.add_argument("--units", type=int, required=True)
    try:
        print(json.dumps(asyncio.run(run(parser.parse_args()))))
    except Exception as error:
        print(json.dumps({"error": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
