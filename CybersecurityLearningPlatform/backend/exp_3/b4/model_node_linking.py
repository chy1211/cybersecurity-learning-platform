"""Model-in-the-loop node linking for B4 (route 2).

For the mentions a question cannot resolve by exact/alias match, the evaluated
model is shown a bounded candidate set per mention and picks one node id or
``null``.  All of a question's pending mentions are packed into ONE request so
each question costs a single extra model call, and the same model that answers
the question also does its own linking (per-model retrieval).

The parser is fail closed: a pick outside the candidate set, a missing index or
malformed output resolves to ``None`` (unresolved), never to an arbitrary node.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence


class NodeLinkingError(ValueError):
    pass


def build_choice_items(requests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Index the per-mention choice requests for a single question."""

    items: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        candidates = request.get("candidates", [])
        if not candidates:
            raise NodeLinkingError(f"choice request {index} has no candidates")
        items.append(
            {
                "index": index,
                "mention": str(request.get("mention", "")),
                "origin": str(request.get("origin", "")),
                "candidates": [
                    {
                        "element_id": str(c["element_id"]),
                        "name": str(c["name"]),
                        **({"type": str(c["type"])} if c.get("type") is not None else {}),
                    }
                    for c in candidates
                ],
            }
        )
    return items


def build_prompt(template: str, requests: Sequence[Mapping[str, Any]]) -> str:
    items = build_choice_items(requests)
    payload = json.dumps({"mentions": items}, ensure_ascii=False, indent=2)
    return template.replace("<<<<MENTIONS_JSON>>>>", payload)


def _extract_json_block(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise NodeLinkingError("empty node-linking response")
    fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    raise NodeLinkingError("node-linking response does not contain a JSON object")


def parse_choices(
    raw: str | Mapping[str, Any], requests: Sequence[Mapping[str, Any]]
) -> dict[int, str | None]:
    """Return ``{request_index: chosen_element_id or None}`` for every request.

    A missing index, a null pick, or an id not in that request's candidate set
    all resolve to ``None`` (fail closed).  The pipeline still gets an entry for
    every request, so no mention is silently dropped.
    """

    if isinstance(raw, Mapping):
        payload: Any = dict(raw)
    else:
        try:
            payload = json.loads(_extract_json_block(raw))
        except json.JSONDecodeError as exc:
            raise NodeLinkingError(f"invalid node-linking JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise NodeLinkingError("node-linking payload must be an object")
    raw_choices = payload.get("choices")
    if not isinstance(raw_choices, list):
        raise NodeLinkingError("node-linking payload must contain a choices array")

    allowed: dict[int, set[str]] = {
        index: {str(c["element_id"]) for c in request.get("candidates", [])}
        for index, request in enumerate(requests)
    }
    decisions: dict[int, str | None] = {index: None for index in allowed}
    for choice in raw_choices:
        if not isinstance(choice, Mapping):
            continue
        try:
            index = int(choice.get("index"))
        except (TypeError, ValueError):
            continue
        if index not in allowed:
            continue
        picked = choice.get("element_id")
        if picked is None:
            decisions[index] = None
            continue
        picked = str(picked).strip()
        decisions[index] = picked if picked in allowed[index] else None
    return decisions
