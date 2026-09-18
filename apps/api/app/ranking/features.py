from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class RankingProfile:
    industries: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    min_contract_amount: Decimal | None = None
    max_contract_amount: Decimal | None = None
    contract_currency: str | None = None


@dataclass(frozen=True)
class RankingOpportunity:
    title: str = ""
    body: str = ""
    category: str | None = None
    required_capabilities: tuple[str, ...] = ()
    estimated_amount: Decimal | None = None
    currency: str | None = None
    published_at: datetime | None = None
    deadline: datetime | None = None
    evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _tokens(*values: str) -> set[str]:
    return {token for value in values for token in re.findall(r"[\w]+", _norm(value))}


def lexical_score(profile: RankingProfile, opportunity: RankingOpportunity) -> Decimal:
    interests = _tokens(*profile.industries, *profile.capabilities)
    if not interests:
        return ZERO
    observed = _tokens(opportunity.title, opportunity.body, opportunity.category or "")
    return Decimal(len(interests & observed)) / Decimal(len(interests))


def capability_score(profile: RankingProfile, opportunity: RankingOpportunity) -> Decimal:
    wanted = {_norm(value) for value in opportunity.required_capabilities if _norm(value)}
    if not wanted:
        text = _norm(f"{opportunity.title} {opportunity.body}")
        wanted = {_norm(value) for value in profile.capabilities if _norm(value) in text}
    if not wanted:
        return ZERO
    owned = {_norm(value) for value in profile.capabilities}
    return Decimal(len(wanted & owned)) / Decimal(len(wanted))


def category_score(profile: RankingProfile, opportunity: RankingOpportunity) -> Decimal:
    if not opportunity.category or not profile.industries:
        return ZERO
    category = _norm(opportunity.category)
    return ONE if any(_norm(value) == category for value in profile.industries) else ZERO


def amount_score(profile: RankingProfile, opportunity: RankingOpportunity) -> tuple[Decimal, str]:
    if opportunity.estimated_amount is None or opportunity.currency is None:
        return ZERO, "amount_unknown"
    if profile.contract_currency is None:
        return ZERO, "profile_currency_unknown"
    if opportunity.currency.upper() != profile.contract_currency.upper():
        return ZERO, "currency_mismatch"
    amount = opportunity.estimated_amount
    lower, upper = profile.min_contract_amount, profile.max_contract_amount
    if lower is not None and amount < lower:
        return ZERO, "below_profile_range"
    if upper is not None and amount > upper:
        return ZERO, "above_profile_range"
    if lower is None or upper is None or upper <= lower:
        return ONE, "within_profile_range"
    midpoint = (lower + upper) / Decimal("2")
    half_range = (upper - lower) / Decimal("2")
    closeness = ONE - abs(amount - midpoint) / half_range
    return max(ZERO, closeness), "within_profile_range"


def recency_deadline_score(opportunity: RankingOpportunity, as_of: datetime) -> Decimal:
    if opportunity.published_at is not None and opportunity.published_at > as_of:
        raise ValueError("opportunity was published after as_of")
    if opportunity.deadline is not None and opportunity.deadline < as_of:
        return ZERO
    recency = ZERO
    if opportunity.published_at is not None:
        age = Decimal(str((as_of - opportunity.published_at).total_seconds() / 86400))
        recency = max(ZERO, ONE - age / Decimal("30"))
    deadline = ZERO
    if opportunity.deadline is not None:
        days = Decimal(str((opportunity.deadline - as_of).total_seconds() / 86400))
        deadline = max(ZERO, ONE - days / Decimal("45"))
    return (recency + deadline) / Decimal("2")
