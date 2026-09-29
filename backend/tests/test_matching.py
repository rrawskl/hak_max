from datetime import date

from app.matching import age_months, evaluate, rule_result


def test_month_boundary_and_zero():
    assert age_months(date(2025, 1, 31), date(2025, 2, 28)) == 0
    assert age_months(date(2025, 1, 31), date(2025, 3, 31)) == 2
    assert rule_result({"field": "employee_count", "operator": "lte", "expected": 0}, {"employee_count": 0})["outcome"] == "pass"
    assert rule_result({"field": "tax_debt", "operator": "eq", "expected": False}, {"tax_debt": False})["outcome"] == "pass"
    assert rule_result({"field": "revenue", "operator": "exists", "expected": False}, {"revenue": None})["outcome"] == "pass"
    assert rule_result({"field": "revenue", "operator": "exists", "expected": True}, {"revenue": None})["outcome"] == "fail"


def test_required_unknown_overrides_known_passes():
    rules = [{"field": f"f{i}", "operator": "eq", "expected": i, "required": True} for i in range(5)]
    program = {"state": "open", "deadline": None, "rules": rules, "provenance": {"data_kind": "synthetic"}, "version": 1}
    result = evaluate(program, {f"f{i}": i for i in range(4)}, demo_rules=True)
    assert result["status"] == "check_needed"
    assert result["checked_count"] == 4
    assert evaluate(program, {**{f"f{i}": i for i in range(4)}, "f4": 99}, demo_rules=True)["status"] == "not_eligible"


def test_groups_not_applicable_and_stale():
    rule = {"group": "any", "required": True, "rules": [
        {"field": "legal_form", "operator": "eq", "expected": "ip"},
        {"field": "legal_form", "operator": "eq", "expected": "ooo"},
    ]}
    assert rule_result(rule, {"legal_form": "ooo"})["outcome"] == "pass"
    conditional = {"field": "revenue", "operator": "gte", "expected": 100, "when": {"field": "legal_form", "operator": "eq", "expected": "ooo"}}
    assert rule_result(conditional, {"legal_form": "ip"})["outcome"] == "not_applicable"
    program = {"state": "open", "deadline": None, "rules": [rule], "provenance": {"data_kind": "curated_official", "checked_at": None}}
    assert evaluate(program, {"legal_form": "ooo"})["status"] == "check_needed"
    assert evaluate({**program, "rules": []}, {"legal_form": "ooo"})["status"] == "check_needed"
    assert evaluate({**program, "state": "closed"}, {"legal_form": "ooo"})["status"] == "closed"
