from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationPreference

Channel = Literal["local", "webhook", "email"]
Trigger = Literal[
    "new_high_relevance",
    "watched_material_change",
    "deadline_changed",
    "eligibility_changed",
    "outcome_published",
]


class PreferenceValues(BaseModel):
    """Owned API contract: actor ID comes from authentication, never this payload."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    channels: list[Channel] = Field(default=["local"], max_length=3)
    triggers: list[Trigger] = Field(
        default=[
            "new_high_relevance",
            "watched_material_change",
            "deadline_changed",
            "eligibility_changed",
            "outcome_published",
        ],
        max_length=5,
    )

    def allows(self, channel: str, trigger: str) -> bool:
        return self.enabled and channel in self.channels and trigger in self.triggers


async def get_preferences(session: AsyncSession, owner_id: str) -> PreferenceValues:
    row = await session.scalar(
        select(NotificationPreference).where(NotificationPreference.user_id == owner_id)
    )
    if row is None:
        return PreferenceValues()
    return PreferenceValues.model_validate(
        {
            "enabled": row.enabled,
            "channels": row.channels,
            "triggers": row.triggers,
        }
    )


async def set_preferences(
    session: AsyncSession, owner_id: str, values: PreferenceValues
) -> PreferenceValues:
    data = values.model_dump()
    await session.execute(
        insert(NotificationPreference)
        .values(user_id=owner_id, **data)
        .on_conflict_do_update(index_elements=["user_id"], set_=data)
    )
    return values
