"""Strict Step 2b relation-selection validation."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping


class RelationSelectionError(ValueError):
    pass


def _json_object(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        raise RelationSelectionError("empty Step 2b response")
    fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    elif not (text.startswith("{") and text.endswith("}")):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RelationSelectionError("Step 2b response does not contain JSON")
        text = match.group(0)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RelationSelectionError(f"invalid Step 2b JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise RelationSelectionError("Step 2b payload must be an object")
    return value


def parse_relation_selection(
    raw: str | Mapping[str, Any],
    candidate_relations: Iterable[str],
    *,
    max_relations: int = 10,
) -> dict[str, Any]:
    """Validate a model response without any top-k fallback."""

    candidates = sorted({str(item).strip() for item in candidate_relations if str(item).strip()})
    payload = _json_object(raw)
    selected = payload.get("selected_relations")
    if not isinstance(selected, list):
        raise RelationSelectionError("selected_relations must be an array")
    if len(selected) > max_relations:
        raise RelationSelectionError(
            f"selected_relations exceeds max_relations={max_relations}"
        )
    selected = [str(item).strip() for item in selected]
    if any(not item for item in selected):
        raise RelationSelectionError("selected_relations cannot contain empty values")
    if len(set(selected)) != len(selected):
        raise RelationSelectionError("selected_relations contains duplicates")
    invalid = sorted(set(selected) - set(candidates))
    if invalid:
        raise RelationSelectionError(
            f"selected_relations contains non-candidates: {invalid}"
        )
    reason = str(payload.get("decision_reason") or "").strip()
    if selected:
        status = "selected"
        if not reason:
            reason = "model selected a validated candidate relation subset"
    else:
        status = "empty"
        if not reason:
            reason = "model found no sufficiently relevant candidate relation"
    return {
        "status": status,
        "candidate_relations": candidates,
        "selected_relations": selected,
        "decision_reason": reason,
    }
