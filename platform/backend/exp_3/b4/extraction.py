"""Validation helpers for the four-model B4 extractor matrix."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


class ExtractionMatrixError(ValueError):
    pass


def validate_extraction_artifact(
    payload: Mapping[str, Mapping[str, Any]],
    *,
    qids: Iterable[str],
    model: str,
) -> dict[str, Any]:
    expected = {str(qid) for qid in qids}
    observed = set(payload)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    errors: list[str] = []
    if missing:
        errors.append(f"missing qids: {missing[:5]}")
    if extra:
        errors.append(f"extra qids: {extra[:5]}")
    for qid in sorted(expected & observed):
        record = payload[qid]
        if not isinstance(record, Mapping):
            errors.append(f"invalid record: {qid}")
            continue
        if record.get("error"):
            errors.append(f"extractor error: {qid}")
        if record.get("qid") not in {None, qid}:
            errors.append(f"record qid mismatch: {qid}")
        evidence = record.get("subgraph", {}).get("evidence", [])
        if not isinstance(evidence, list):
            errors.append(f"invalid evidence list: {qid}")
    if errors:
        raise ExtractionMatrixError(f"{model}: " + "; ".join(errors))
    return {
        "status": "PASS",
        "model": model,
        "expected_questions": len(expected),
        "observed_questions": len(observed),
        "empty_evidence_questions": sum(
            not payload[qid].get("subgraph", {}).get("evidence", []) for qid in expected
        ),
    }

