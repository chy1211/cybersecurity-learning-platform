"""Strict B4 preflight and freeze-manifest helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


class PreflightError(ValueError):
    pass


def expected_result_keys(
    qids: Iterable[str],
    models: Iterable[str],
    conditions: Iterable[str] = ("base", "rag"),
) -> set[tuple[str, str, str]]:
    return {
        (str(model), str(qid), str(condition))
        for model in models
        for qid in qids
        for condition in conditions
    }


def validate_result_matrix(
    results_by_model: Mapping[str, Mapping[str, Mapping[str, Mapping[str, Any]]]],
    *,
    qids: Iterable[str],
    models: Iterable[str],
    conditions: Iterable[str] = ("base", "rag"),
) -> dict[str, Any]:
    """Require exact model × qid × condition coverage and zero run errors."""

    qid_list = [str(qid) for qid in qids]
    model_list = [str(model) for model in models]
    condition_list = [str(condition) for condition in conditions]
    expected = expected_result_keys(qid_list, model_list, condition_list)
    observed: set[tuple[str, str, str]] = set()
    errors: list[str] = []
    for model in model_list:
        by_qid = results_by_model.get(model)
        if not isinstance(by_qid, Mapping):
            errors.append(f"missing model result block: {model}")
            continue
        for qid in qid_list:
            by_condition = by_qid.get(qid)
            if not isinstance(by_condition, Mapping):
                errors.append(f"missing qid: {model}/{qid}")
                continue
            for condition in condition_list:
                key = (model, qid, condition)
                record = by_condition.get(condition)
                if not isinstance(record, Mapping):
                    errors.append(f"missing condition: {model}/{qid}/{condition}")
                    continue
                observed.add(key)
                for error_key in ("_api_error", "_parse_error", "_retrieval_error"):
                    if record.get(error_key):
                        errors.append(f"{error_key}: {model}/{qid}/{condition}")
                if not str(record.get("answer_norm") or "").strip():
                    errors.append(f"empty answer: {model}/{qid}/{condition}")

    extras = sorted(observed - expected)
    if extras:
        errors.append(f"unexpected result keys: {extras[:5]}")
    missing = sorted(expected - observed)
    if missing:
        errors.append(f"missing result keys: {missing[:5]}")
    if errors:
        raise PreflightError("; ".join(errors))
    return {
        "status": "PASS",
        "models": model_list,
        "qids": len(qid_list),
        "conditions": condition_list,
        "expected_records": len(expected),
        "observed_records": len(observed),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_freeze_manifest(paths: Iterable[Path], *, metadata: Mapping[str, Any]) -> dict[str, Any]:
    files = []
    for path in sorted((Path(item) for item in paths), key=lambda item: str(item)):
        if not path.is_file():
            raise PreflightError(f"freeze artifact is not a file: {path}")
        files.append({"path": str(path.resolve()), "sha256": sha256_file(path)})
    manifest = {
        "status": "FROZEN",
        "metadata": dict(metadata),
        "files": files,
    }
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return manifest


def verify_freeze_manifest(path: Path) -> dict[str, Any]:
    """Reject a heldout run when any frozen artifact or manifest hash changed."""

    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN":
        raise PreflightError("freeze manifest is not marked FROZEN")
    supplied_hash = manifest.get("manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True).encode("utf-8")
    actual_hash = hashlib.sha256(canonical).hexdigest()
    if supplied_hash != actual_hash:
        raise PreflightError("freeze manifest hash does not match its contents")
    changed: list[str] = []
    for item in manifest.get("files", []):
        file_path = Path(item["path"])
        if not file_path.is_file() or sha256_file(file_path) != item.get("sha256"):
            changed.append(str(file_path))
    if changed:
        raise PreflightError(f"frozen artifacts changed: {changed[:5]}")
    return manifest
