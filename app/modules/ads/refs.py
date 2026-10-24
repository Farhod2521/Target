from typing import Any

REPEATED_STEPS: frozenset[str] = frozenset({'adset', 'creative', 'ad'})

def ref_ids(created_refs: dict[str, Any], step: str) -> list[str]:
    value = created_refs.get(step)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)] if value else []

def first_id(created_refs: dict[str, Any], step: str) -> str:
    ids = ref_ids(created_refs, step)
    return ids[0] if ids else ''

def put(created_refs: dict[str, Any], step: str, external_id: str) -> None:
    if step not in REPEATED_STEPS:
        created_refs[step] = external_id
        return
    existing = ref_ids(created_refs, step)
    existing.append(external_id)
    created_refs[step] = existing

def clear(created_refs: dict[str, Any], step: str, external_id: str) -> None:
    remaining = [item for item in ref_ids(created_refs, step) if item != external_id]
    if not remaining:
        created_refs.pop(step, None)
    elif step in REPEATED_STEPS:
        created_refs[step] = remaining
    else:
        created_refs[step] = remaining[0]
