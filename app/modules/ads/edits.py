from collections.abc import Callable
from typing import Any, Final

EDITS_KEY: Final = 'edits'
Snapshot = dict[str, list[str]]

def baselines(draft: dict[str, Any]) -> Snapshot:
    found = draft.get(EDITS_KEY)
    if not isinstance(found, dict):
        return {}
    return {str(key): [str(item) for item in value] for key, value in found.items() if isinstance(value, list)}

def record(draft: dict[str, Any], *, before: Snapshot, after: Snapshot, same: Callable[[str, list[str], list[str]], bool]) -> None:
    kept = baselines(draft)
    for key, value in after.items():
        old = before.get(key, [])
        if key not in kept and (not same(key, old, value)):
            kept[key] = old
        if key in kept and same(key, kept[key], value):
            del kept[key]
    draft[EDITS_KEY] = kept
