from typing import Any

NAME = 'name'
BUDGET = 'daily_budget_minor'

def read(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        return [blank()]
    return [_one(item) for item in value]

def blank() -> dict[str, Any]:
    return {NAME: '', BUDGET: 0}

def _one(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return blank()
    return {NAME: str(item.get(NAME) or ''), BUDGET: max(0, int(item.get(BUDGET) or 0))}
