"""Deterministic placeholder-based redactor.

Replaces detected PHI spans with stable placeholders such as ``[PATIENT_NAME_1]``.
Identical surface forms get the same placeholder index across the document so
that the de-identified text stays internally consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .detector import PHIEntity, count_by_type


@dataclass
class RedactionResult:
    """Output of a redaction pass.

    The ``replacement_map`` contains raw PHI strings as keys and is therefore
    SENSITIVE. It must never be written to logs, telemetry, or summaries.
    """

    deidentified_text: str
    replacement_map: dict[str, str] = field(default_factory=dict)
    entity_counts: dict[str, int] = field(default_factory=dict)


def redact(text: str, entities: list[PHIEntity]) -> RedactionResult:
    """Replace each detected entity with a deterministic placeholder.

    The same surface text within the same call always maps to the same
    placeholder. Spans are replaced from right to left so earlier indices stay
    valid during substitution.
    """
    if not entities:
        return RedactionResult(
            deidentified_text=text,
            replacement_map={},
            entity_counts={},
        )

    type_indices: dict[str, int] = {}
    surface_to_placeholder: dict[tuple[str, str], str] = {}
    replacement_map: dict[str, str] = {}

    # Walk entities in original order so that placeholder numbering reads
    # left-to-right in the document.
    for entity in sorted(entities, key=lambda e: e.start_index):
        key = (entity.entity_type, entity.matched_text)
        if key not in surface_to_placeholder:
            type_indices[entity.entity_type] = type_indices.get(entity.entity_type, 0) + 1
            placeholder = f"[{entity.entity_type}_{type_indices[entity.entity_type]}]"
            surface_to_placeholder[key] = placeholder
            replacement_map[entity.matched_text] = placeholder

    # Apply substitutions right-to-left so original indices stay accurate.
    chars = list(text)
    for entity in sorted(entities, key=lambda e: e.start_index, reverse=True):
        placeholder = surface_to_placeholder[(entity.entity_type, entity.matched_text)]
        chars[entity.start_index : entity.end_index] = list(placeholder)

    return RedactionResult(
        deidentified_text="".join(chars),
        replacement_map=replacement_map,
        entity_counts=count_by_type(entities),
    )
