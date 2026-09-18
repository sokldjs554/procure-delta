from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_owner_id
from app.db import get_session
from app.models import CompanyProfile

router = APIRouter(prefix="/api/v1/company-profile", tags=["company-profile"])
Session = Annotated[AsyncSession, Depends(get_session)]


Owner = Annotated[str, Depends(get_current_owner_id)]


class ProfileValues(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    display_name: str = Field(min_length=1, max_length=255)
    synthetic_demo: Literal[True] = True
    regions: list[str] = Field(default_factory=list, max_length=100)
    industries: list[str] = Field(default_factory=list, max_length=100)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    certifications: list[str] = Field(default_factory=list, max_length=100)
    employee_band: str | None = Field(default=None, max_length=100)
    min_contract_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    max_contract_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    contract_currency: str | None = Field(default=None, min_length=3, max_length=3)
    excluded_keywords: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("regions", "industries", "capabilities", "certifications", "excluded_keywords")
    @classmethod
    def validate_lists(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(item.split()) for item in value]
        if any(not item for item in cleaned):
            raise ValueError("list values must not be blank")
        if len({item.casefold() for item in cleaned}) != len(cleaned):
            raise ValueError("list values must be unique")
        return cleaned

    @field_validator("contract_currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isalpha():
            raise ValueError("contract currency must be an ISO-3 alphabetic code")
        return value.upper()

    @model_validator(mode="after")
    def validate_amounts(self) -> ProfileValues:
        if (
            self.min_contract_amount is not None
            and self.max_contract_amount is not None
            and self.min_contract_amount > self.max_contract_amount
        ):
            raise ValueError("minimum contract amount cannot exceed maximum")
        if (
            self.min_contract_amount is not None or self.max_contract_amount is not None
        ) and self.contract_currency is None:
            raise ValueError("contract currency is required with amount bounds")
        return self


class ProfileCreate(ProfileValues):
    pass


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    synthetic_demo: Literal[True] | None = None
    regions: list[str] | None = Field(default=None, max_length=100)
    industries: list[str] | None = Field(default=None, max_length=100)
    capabilities: list[str] | None = Field(default=None, max_length=100)
    certifications: list[str] | None = Field(default=None, max_length=100)
    employee_band: str | None = Field(default=None, max_length=100)
    min_contract_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    max_contract_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    contract_currency: str | None = Field(default=None, min_length=3, max_length=3)
    excluded_keywords: list[str] | None = Field(default=None, max_length=100)


class ProfileResponse(ProfileValues):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_user_id: str


async def _owned(session: AsyncSession, owner: str) -> CompanyProfile | None:
    rows = await session.scalars(
        select(CompanyProfile).where(CompanyProfile.owner_user_id == owner)
    )
    return rows.one_or_none()


@router.get("", response_model=ProfileResponse)
async def get_profile(session: Session, owner: Owner) -> CompanyProfile:
    row = await _owned(session, owner)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company profile not found")
    return row


@router.post("", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(payload: ProfileCreate, session: Session, owner: Owner) -> CompanyProfile:
    if await _owned(session, owner) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Company profile already exists")
    row = CompanyProfile(owner_user_id=owner, **payload.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Company profile already exists") from exc
    await session.refresh(row)
    return row


@router.patch("", response_model=ProfileResponse)
async def patch_profile(payload: ProfilePatch, session: Session, owner: Owner) -> CompanyProfile:
    row = await _owned(session, owner)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company profile not found")
    merged = {name: getattr(row, name) for name in ProfileValues.model_fields}
    merged.update(payload.model_dump(exclude_unset=True))
    try:
        validated = ProfileValues.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid profile values"
        ) from exc
    for name, value in validated.model_dump().items():
        setattr(row, name, value)
    await session.commit()
    await session.refresh(row)
    return row


async def ensure_synthetic_demo_profile(session: AsyncSession) -> CompanyProfile:
    owner = "synthetic-demo-owner"
    existing = await _owned(session, owner)
    if existing is not None:
        return existing
    row = CompanyProfile(
        owner_user_id=owner,
        display_name="ProcureDelta Synthetic Demo Company",
        synthetic_demo=True,
        regions=["Seoul", "Gyeonggi"],
        industries=["information-technology"],
        capabilities=["cloud migration", "document processing"],
        certifications=["ISO 27001"],
        min_contract_amount=Decimal("10000000"),
        max_contract_amount=Decimal("500000000"),
        contract_currency="KRW",
        excluded_keywords=["classified"],
    )
    session.add(row)
    await session.flush()
    return row
