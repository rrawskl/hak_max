from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import select

from .config import settings
from .db import BusinessProfile, SessionLocal, SupportProgram, User


class SeedProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1)
    purpose_code: str = Field(min_length=1)
    benefit_type: str = Field(min_length=1)
    amount_text: str | None
    deadline_days: StrictInt | None
    state: Literal["open", "closed"]
    description: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)
    rules: list[dict] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9-]+", value):
            raise ValueError("Program id must use lowercase ASCII, digits or hyphens")
        return value

    @field_validator("documents")
    @classmethod
    def valid_documents(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("Documents must be nonempty strings")
        return value

    @field_validator("rules")
    @classmethod
    def valid_rules(cls, value: list[dict]) -> list[dict]:
        for rule in value:
            validate_rule(rule)
        return value


def validate_rule(rule: dict) -> None:
    if not isinstance(rule, dict) or not isinstance(rule.get("explanation"), str) or not rule["explanation"].strip():
        raise ValueError("Every rule needs an explanation")
    if not isinstance(rule.get("required"), bool):
        raise ValueError("Every rule needs a boolean required flag")
    if "group" in rule:
        children = rule.get("rules")
        if rule["group"] not in {"all", "any"} or not isinstance(children, list) or not children:
            raise ValueError("Rule group must be all/any with children")
        if set(rule) - {"group", "rules", "required", "explanation", "source_ref"}:
            raise ValueError("Unexpected group rule field")
        for child in children:
            validate_rule(child)
        return
    if set(rule) - {"field", "operator", "expected", "required", "explanation", "source_ref", "when"}:
        raise ValueError("Unexpected rule field")
    if not isinstance(rule.get("field"), str) or rule["field"] not in {
        "region_code", "legal_form", "industry_code", "employee_count", "business_age_months", "tax_debt", "revenue"
    }:
        raise ValueError("Unsupported rule field")
    operator = rule.get("operator")
    expected = rule.get("expected")
    if operator not in {"eq", "in", "gte", "lte", "exists"}:
        raise ValueError("Unsupported rule operator")
    if operator == "in" and (not isinstance(expected, list) or not expected):
        raise ValueError("in needs a nonempty expected list")
    if operator in {"gte", "lte"} and (not isinstance(expected, (int, float)) or isinstance(expected, bool)):
        raise ValueError("gte/lte need a numeric expected value")
    if operator == "exists" and not isinstance(expected, bool):
        raise ValueError("exists needs a boolean expected value")
    if operator == "eq" and expected is None:
        raise ValueError("eq needs an expected value")
    if "when" in rule:
        validate_rule({**rule["when"], "required": False, "explanation": rule["explanation"]})


def seed_demo() -> int:
    if settings.app_env == "production" or not settings.seed_demo:
        raise RuntimeError("Demo seed requires SEED_DEMO=true outside production")
    path = Path(__file__).resolve().parents[2] / "data" / "programs.json"
    if not path.exists():
        path = Path("/app/data-source/programs.json")
    raw_rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_rows, list) or not 8 <= len(raw_rows) <= 12:
        raise ValueError("Demo catalogue must contain 8–12 programs")
    rows = [SeedProgram.model_validate(item) for item in raw_rows]
    if len({item.id for item in rows}) != len(rows):
        raise ValueError("Duplicate program id")
    base = date.fromisoformat(settings.demo_base_date) if settings.demo_base_date else date.today()
    with SessionLocal.begin() as session:
        for item in rows:
            if session.get(SupportProgram, item.id):
                continue
            rules = [
                {"field": "region_code", "operator": "eq", "expected": "spb", "required": True, "explanation": "Бизнес зарегистрирован в Санкт-Петербурге", "source_ref": "demo:region"},
                {"field": "legal_form", "operator": "in", "expected": ["ip", "ooo"], "required": True, "explanation": "Форма ИП или ООО", "source_ref": "demo:form"},
            ] + item.rules
            for index, rule in enumerate(rules):
                rule.setdefault("source_ref", f"demo:{item.id}:{index}")
            session.add(SupportProgram(
                id=item.id, title=item.title, operator_name="Учебный набор ДЕЛО",
                purpose_code=item.purpose_code, region_code="spb", benefit_type=item.benefit_type,
                amount_text=item.amount_text, deadline=base + timedelta(days=item.deadline_days) if item.deadline_days is not None else None,
                state=item.state, description=item.description, rules=rules,
                document_template=item.documents, provenance={"data_kind": "synthetic", "source_title": "Учебный набор ДЕЛО", "source_url": None, "checked_at": None, "refresh_due_at": None},
            ))
        user = session.scalar(select(User).where(User.max_user_id == "demo"))
        if not user:
            user = User(max_user_id="demo", display_name="Демо", bot_started=True)
            session.add(user)
            session.flush()
        if not session.get(BusinessProfile, user.id):
            session.add(BusinessProfile(
                user_id=user.id, business_name="Мастерская ДЕЛО", legal_form="ip", region_code="spb",
                industry_code="services", employee_count=3, registration_date=base - timedelta(days=600),
                purpose_code="equipment", tax_debt="unknown", revenue=None,
            ))
    return len(rows)


if __name__ == "__main__":
    print(f"Seeded {seed_demo()} demo programs")
