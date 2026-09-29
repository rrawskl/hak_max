from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .matching import MOSCOW


class MaxAuthIn(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class ProfileIn(BaseModel):
    business_name: str = Field(min_length=1, max_length=120)
    legal_form: Literal["ip", "ooo"]
    region_code: str = Field(min_length=1, max_length=30)
    industry_code: str = Field(min_length=1, max_length=60)
    employee_count: int = Field(ge=0, le=30)
    registration_date: date
    purpose_code: str = Field(min_length=1, max_length=40)
    tax_debt: Literal["yes", "no", "unknown"] = "unknown"
    revenue: int | None = Field(default=None, ge=0)
    version: int | None = Field(default=None, ge=1)

    @field_validator("registration_date")
    @classmethod
    def not_future(cls, value: date) -> date:
        if value > datetime.now(MOSCOW).date():
            raise ValueError("Дата регистрации не может быть в будущем")
        return value


class PlanIn(BaseModel):
    program_id: str
    due_at: datetime
    reminders_enabled: bool = False
    reminder_at: datetime | None = None

    @field_validator("due_at", "reminder_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Укажите часовой пояс")
        return value


class PlanPatch(BaseModel):
    version: int = Field(ge=1)
    status: Literal["active", "completed", "cancelled"] | None = None
    due_at: datetime | None = None
    reminders_enabled: bool | None = None
    reminder_at: datetime | None = None

    @field_validator("due_at", "reminder_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Укажите часовой пояс")
        return value


class ItemPatch(BaseModel):
    version: int = Field(ge=1)
    status: Literal["todo", "done"]


class ItemCreate(BaseModel):
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)


class DemoReminderIn(BaseModel):
    plan_id: str
