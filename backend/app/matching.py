from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


MOSCOW = ZoneInfo("Europe/Moscow")
RANK = {"preliminary_match": 0, "check_needed": 1, "not_eligible": 2, "closed": 3}


def age_months(registered: date, today: date) -> int:
    return (today.year - registered.year) * 12 + today.month - registered.month - (today.day < registered.day)


def profile_values(profile: dict[str, Any] | None, today: date) -> dict[str, Any]:
    if not profile:
        return {}
    values = dict(profile)
    registered = values.get("registration_date")
    if isinstance(registered, str):
        registered = date.fromisoformat(registered)
    if registered:
        values["business_age_months"] = age_months(registered, today)
    if values.get("tax_debt") == "unknown":
        values["tax_debt"] = None
    return values


def rule_result(rule: dict, values: dict) -> dict:
    if "group" in rule:
        children = [rule_result(child, values) for child in rule.get("rules", [])]
        outcomes = [child["outcome"] for child in children if child["outcome"] != "not_applicable"]
        group = rule["group"]
        if not outcomes:
            outcome = "not_applicable" if children else "unknown"
        elif group == "all":
            outcome = "fail" if "fail" in outcomes else "unknown" if "unknown" in outcomes else "pass"
        elif group == "any":
            outcome = "pass" if "pass" in outcomes else "unknown" if "unknown" in outcomes else "fail"
        else:
            outcome = "unknown"
        return {"outcome": outcome, "required": rule.get("required", True), "explanation": rule.get("explanation", ""), "source_ref": rule.get("source_ref"), "children": children}
    condition = rule.get("when")
    if condition:
        conditional = rule_result({**condition, "required": False}, values)["outcome"]
        if conditional == "fail":
            return {"field": rule.get("field"), "outcome": "not_applicable", "required": rule.get("required", True), "explanation": rule.get("explanation", ""), "source_ref": rule.get("source_ref")}
        if conditional != "pass":
            return {"field": rule.get("field"), "outcome": "unknown", "required": rule.get("required", True), "explanation": rule.get("explanation", ""), "source_ref": rule.get("source_ref")}
    field = rule.get("field")
    actual = values.get(field)
    expected = rule.get("expected", rule.get("value"))
    operator = rule.get("operator")
    if operator == "exists" and isinstance(expected, bool):
        outcome = "pass" if (actual is not None and actual != "") == expected else "fail"
    elif actual is None or actual == "":
        outcome = "unknown"
    else:
        try:
            passed = {
                "eq": lambda: actual == expected,
                "in": lambda: actual in expected,
                "gte": lambda: actual >= expected,
                "lte": lambda: actual <= expected,
            }[operator]()
            outcome = "pass" if passed else "fail"
        except (KeyError, TypeError, ValueError):
            outcome = "unknown"
    return {"field": field, "outcome": outcome, "required": rule.get("required", True), "explanation": rule.get("explanation", ""), "source_ref": rule.get("source_ref")}


def evaluate(program: Any, profile: dict | None, *, today: date | None = None, demo_rules: bool = False) -> dict:
    today = today or datetime.now(MOSCOW).date()
    data = program if isinstance(program, dict) else {key: getattr(program, key) for key in ("id", "state", "deadline", "rules", "provenance", "version")}
    deadline = data.get("deadline")
    if isinstance(deadline, str):
        deadline = date.fromisoformat(deadline)
    results = [rule_result(rule, profile_values(profile, today)) for rule in data.get("rules", [])]
    required = [r for r in results if r["required"] and r["outcome"] != "not_applicable"]
    provenance = data.get("provenance") or {}
    refresh_due = provenance.get("refresh_due_at")
    stale = not provenance.get("checked_at") or bool(refresh_due and date.fromisoformat(refresh_due) < today)
    if provenance.get("data_kind") == "synthetic" and demo_rules:
        stale = False
    if data.get("state") == "closed" or (deadline is not None and deadline < today):
        status = "closed"
    elif any(r["outcome"] == "fail" for r in required):
        status = "not_eligible"
    elif not required or stale or any(r["outcome"] == "unknown" for r in required):
        status = "check_needed"
    else:
        status = "preliminary_match"
    return {
        "status": status,
        "rules": results,
        "checked_count": sum(r["outcome"] in ("pass", "fail") for r in required),
        "required_count": len(required),
        "source_stale": stale,
        "profile_version": profile.get("version") if profile else None,
        "program_version": data.get("version", 1),
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def sort_key(program: dict, purpose: str | None) -> tuple:
    match = program["match"]
    deadline = program.get("deadline")
    return (RANK[match["status"]], program.get("purpose_code") != purpose, deadline is None, deadline or "9999-12-31", program["id"])
