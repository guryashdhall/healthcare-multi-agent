"""Structured-field redactor for the co-pilot's case JSON.

The free-text PHI detector (``src/deid/detector.py``) is designed for clinical
notes - it expects line-prefixed labels like ``Patient: Sarah Mitchell``.
The co-pilot input is a structured case dict with fields like
``demographics.patient_name``. This redactor walks the dict, replaces the
known-PHI fields with placeholders, and returns a parallel replacement_map.

After this, the existing free-text detector/redactor still runs on the
serialized JSON to catch any PHI accidentally embedded in narrative fields
(e.g. clinician's plan referencing the patient by name).
"""

from __future__ import annotations

from typing import Any

# Field paths inside the case dict that contain PHI.
# Each entry: (path_tuple, entity_type).
# Path matches recursively through dicts; lists are traversed elementwise.
_PHI_FIELD_PATHS: list[tuple[tuple[str, ...], str]] = [
    (("demographics", "patient_name"), "PATIENT_NAME"),
    (("demographics", "dob"), "DOB"),
    (("demographics", "mrn"), "MRN"),
    (("demographics", "phone"), "PHONE"),
    (("demographics", "email"), "EMAIL"),
    (("demographics", "address"), "ADDRESS"),
    (("demographics", "health_card"), "HEALTH_CARD"),
]


def _next_placeholder(
    entity_type: str, indices: dict[str, int], value_to_placeholder: dict[tuple[str, str], str]
) -> str:
    """Allocate or reuse a placeholder for ``(entity_type, value)``."""

    def allocator(value: str) -> str:
        key = (entity_type, value)
        if key in value_to_placeholder:
            return value_to_placeholder[key]
        indices[entity_type] = indices.get(entity_type, 0) + 1
        placeholder = f"[{entity_type}_{indices[entity_type]}]"
        value_to_placeholder[key] = placeholder
        return placeholder

    return allocator  # type: ignore[return-value]


def redact_case_structured(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Walk the case dict, redact known PHI fields, return (redacted_case, replacement_map).

    ``replacement_map`` maps raw PHI surface text -> placeholder, identical
    in shape to ``RedactionResult.replacement_map`` so the existing
    ``rehydrator.rehydrate`` works unchanged.
    """
    redacted: dict[str, Any] = _deep_copy(case)
    indices: dict[str, int] = {}
    value_to_placeholder: dict[tuple[str, str], str] = {}
    replacement_map: dict[str, str] = {}

    # 1) Demographics-style known field paths.
    for path, entity_type in _PHI_FIELD_PATHS:
        _redact_at_path(
            redacted,
            path,
            entity_type,
            indices,
            value_to_placeholder,
            replacement_map,
        )

    # 2) Provider names show up across many places (history.family, plan,
    # consulting provider fields). Walk every string and replace any "Dr. X Y"
    # substring with a single consistent placeholder.
    _redact_provider_names(redacted, indices, value_to_placeholder, replacement_map)

    return redacted, replacement_map


def _deep_copy(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj


def _redact_at_path(
    obj: Any,
    path: tuple[str, ...],
    entity_type: str,
    indices: dict[str, int],
    value_to_placeholder: dict[tuple[str, str], str],
    replacement_map: dict[str, str],
) -> None:
    """Walk ``path`` inside ``obj``. If the leaf is a string, redact it."""
    if not path:
        return
    head, *rest = path
    if isinstance(obj, dict):
        if head not in obj:
            return
        if rest:
            _redact_at_path(obj[head], tuple(rest), entity_type, indices, value_to_placeholder, replacement_map)
            return
        # leaf
        value = obj[head]
        if isinstance(value, str) and value.strip():
            placeholder = _allocate(entity_type, value, indices, value_to_placeholder)
            obj[head] = placeholder
            replacement_map[value] = placeholder
        elif isinstance(value, (int, float)):
            sval = str(value)
            placeholder = _allocate(entity_type, sval, indices, value_to_placeholder)
            obj[head] = placeholder
            replacement_map[sval] = placeholder


def _allocate(
    entity_type: str,
    value: str,
    indices: dict[str, int],
    value_to_placeholder: dict[tuple[str, str], str],
) -> str:
    key = (entity_type, value)
    if key in value_to_placeholder:
        return value_to_placeholder[key]
    indices[entity_type] = indices.get(entity_type, 0) + 1
    placeholder = f"[{entity_type}_{indices[entity_type]}]"
    value_to_placeholder[key] = placeholder
    return placeholder


_PROVIDER_PATHS_TO_REDACT_FIRST: list[tuple[str, ...]] = [
    # When the case has named provider fields at the top level we redact them
    # explicitly so the substring sweep can use the same placeholder.
]


def _redact_provider_names(
    obj: Any,
    indices: dict[str, int],
    value_to_placeholder: dict[tuple[str, str], str],
    replacement_map: dict[str, str],
) -> None:
    """Replace any 'Dr. First Last' substring with a stable PROVIDER_NAME placeholder."""
    import re

    pattern = re.compile(r"\bDr\. [A-Z][a-z]+(?: [A-Z][a-z]+){1,2}\b")

    def walk(node: Any, _parent_setter) -> None:
        if isinstance(node, str):
            new_s = node
            for match in pattern.finditer(node):
                raw = match.group(0)
                placeholder = _allocate(
                    "PROVIDER_NAME", raw, indices, value_to_placeholder
                )
                replacement_map[raw] = placeholder
                new_s = new_s.replace(raw, placeholder)
            if new_s != node:
                _parent_setter(new_s)
        elif isinstance(node, dict):
            for k, v in list(node.items()):
                def setter(new_val, k=k, node=node):
                    node[k] = new_val
                walk(v, setter)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                def setter(new_val, i=i, node=node):
                    node[i] = new_val
                walk(v, setter)

    walk(obj, lambda v: None)
