#!/usr/bin/env python3
"""Run the minimal real-provider platform smoke without retaining demo data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "CybersecurityLearningPlatform" / "backend"
MISTAKES_FILE = BACKEND / "user_mistakes.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "final_llm_smoke_20260716.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def post_json(base_url: str, route: str, payload: dict, timeout: float) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{route}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": "non_json_http_error"}
        return exc.code, body


def atomic_restore(path: Path, existed: bool, original: bytes) -> None:
    if not existed:
        if path.exists():
            path.unlink()
        return
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".tmp-llm-smoke-", delete=False
        ) as handle:
            temp_path = handle.name
            handle.write(original)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def configured_provider() -> tuple[str, str]:
    sys.path.insert(0, str(BACKEND))
    from config import Config  # pylint: disable=import-outside-toplevel

    provider = Config.LLM_PROVIDER.lower()
    models = {
        "nvidia": Config.NVIDIA_MODEL,
        "groq": Config.GROQ_MODEL,
        "lm_studio": Config.LM_STUDIO_MODEL,
        "openai": "gpt-4o",
    }
    return provider, models.get(provider, "gpt-4o")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default="http://127.0.0.1:5000")
    parser.add_argument("--entity", default="common criteria")
    parser.add_argument("--timeout", type=float, default=190.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    provider, model = configured_provider()
    existed = MISTAKES_FILE.exists()
    original = MISTAKES_FILE.read_bytes() if existed else b""
    original_sha = sha256_bytes(original)
    marker = f"codex-final-llm-smoke-{uuid.uuid4()}"
    started = time.time()
    report = {
        "generated_at_epoch": started,
        "provider": provider,
        "model": model,
        "entity": args.entity,
        "result": "FAIL_LOCAL",
        "chat": {"called": False, "pass": False},
        "quiz": {"called": False, "pass": False},
        "mistake_explanation": {"called": False, "pass": False},
        "data_restore": {
            "original_existed": existed,
            "original_sha256": original_sha,
            "atomic_restore_attempted": False,
            "restored_exactly": False,
            "test_marker_absent": False,
        },
        "masked_failures": [],
    }

    try:
        report["chat"]["called"] = True
        status, body = post_json(
            args.backend_url,
            "/api/chat",
            {"message": f"請根據平台知識圖譜簡要說明 {args.entity}。"},
            args.timeout,
        )
        chat_pass = (
            status == 200
            and bool(str(body.get("answer", "")).strip())
            and bool(str(body.get("context_entity", "")).strip())
            and isinstance(body.get("evidence"), list)
            and body.get("retrieval_mode") == "platform_one_hop"
        )
        report["chat"].update({
            "http_status": status,
            "answer_nonempty": bool(str(body.get("answer", "")).strip()),
            "context_entity_nonempty": bool(str(body.get("context_entity", "")).strip()),
            "evidence_is_array": isinstance(body.get("evidence"), list),
            "evidence_count": len(body.get("evidence", [])) if isinstance(body.get("evidence"), list) else None,
            "retrieval_mode": body.get("retrieval_mode"),
            "pass": chat_pass,
        })
        if not chat_pass:
            report["masked_failures"].append({
                "endpoint": "chat", "http_status": status,
                "error_type": body.get("error", "schema_validation"),
            })

        report["quiz"]["called"] = True
        status, body = post_json(
            args.backend_url, "/api/quiz/generate", {"node_id": args.entity}, args.timeout
        )
        questions = body.get("questions")
        checks = []
        if isinstance(questions, list):
            for item in questions:
                options = item.get("options") if isinstance(item, dict) else None
                correct = item.get("correctAnswer") if isinstance(item, dict) else None
                checks.append(bool(
                    isinstance(item, dict)
                    and str(item.get("question", "")).strip()
                    and isinstance(options, list) and options
                    and isinstance(correct, int) and 0 <= correct < len(options)
                ))
        quiz_pass = status == 200 and bool(checks) and all(checks)
        report["quiz"].update({
            "http_status": status,
            "question_count": len(questions) if isinstance(questions, list) else None,
            "all_questions_valid": bool(checks) and all(checks),
            "pass": quiz_pass,
        })
        if not quiz_pass:
            report["masked_failures"].append({
                "endpoint": "quiz", "http_status": status,
                "error_type": body.get("error", "schema_validation"),
            })

        record_status, record_body = post_json(
            args.backend_url,
            "/api/mistakes/record",
            {
                "question_data": {
                    "question": f"{marker}: Which statement is correct?",
                    "options": ["incorrect", "correct"],
                    "correctAnswer": 1,
                    "entity_name": args.entity,
                    "node_id": args.entity,
                },
                "user_answer_index": 0,
            },
            args.timeout,
        )
        mistake_id = (record_body.get("mistake") or {}).get("id")
        report["mistake_explanation"]["record_http_status"] = record_status
        report["mistake_explanation"]["called"] = bool(mistake_id)
        if mistake_id:
            status, body = post_json(
                args.backend_url, "/api/mistakes/explain", {"mistake_id": mistake_id}, args.timeout
            )
            explain_pass = status == 200 and bool(str(body.get("explanation", "")).strip())
            report["mistake_explanation"].update({
                "http_status": status,
                "explanation_nonempty": bool(str(body.get("explanation", "")).strip()),
                "pass": explain_pass,
            })
            if not explain_pass:
                report["masked_failures"].append({
                    "endpoint": "mistake_explanation", "http_status": status,
                    "error_type": body.get("error", "schema_validation"),
                })
        else:
            report["masked_failures"].append({
                "endpoint": "mistake_record", "http_status": record_status,
                "error_type": record_body.get("error", "schema_validation"),
            })
    except (TimeoutError, urllib.error.URLError) as exc:
        report["masked_failures"].append({
            "endpoint": "transport", "http_status": None, "error_type": type(exc).__name__,
        })
    finally:
        report["data_restore"]["atomic_restore_attempted"] = True
        atomic_restore(MISTAKES_FILE, existed, original)
        restored = MISTAKES_FILE.read_bytes() if MISTAKES_FILE.exists() else b""
        report["data_restore"]["restored_exactly"] = (
            MISTAKES_FILE.exists() == existed and sha256_bytes(restored) == original_sha
        )
        report["data_restore"]["test_marker_absent"] = marker.encode("utf-8") not in restored

    endpoint_pass = all(report[key]["pass"] for key in ("chat", "quiz", "mistake_explanation"))
    restore_pass = all(report["data_restore"][key] for key in (
        "atomic_restore_attempted", "restored_exactly", "test_marker_absent"
    ))
    if endpoint_pass and restore_pass:
        report["result"] = "PASS"
    elif report["masked_failures"] and restore_pass:
        report["result"] = "BLOCKED_EXTERNAL_OR_PROVIDER"
    else:
        report["result"] = "FAIL_LOCAL"
    report["duration_seconds"] = round(time.time() - started, 3)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": report["result"], "provider": provider,
        "chat_pass": report["chat"]["pass"], "quiz_pass": report["quiz"]["pass"],
        "mistake_explanation_pass": report["mistake_explanation"]["pass"],
        "restored_exactly": report["data_restore"]["restored_exactly"],
        "output": str(args.output),
    }))
    return 0 if report["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
