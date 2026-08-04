#!/usr/bin/env python3
"""Offline/live smoke checks for exp_3 model adapters.

Default mode is --check-env and never calls adapter.call().
Use --live explicitly to send one tiny request per selected model.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


DEFAULT_MODELS = ("e4b", "gptoss", "gemma31b", "llama70b")
SUPPORTED_MODELS = set(DEFAULT_MODELS)
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _nvidia_env_names() -> list[str]:
    """動態列出已設定的 NVIDIA_API_KEY_<N>（依 N 排序，可跳號）；與 exp_3 pipeline 同款。"""
    prefix = "NVIDIA_API_KEY_"
    return [
        name
        for _n, name in sorted(
            (int(name[len(prefix):]), name)
            for name in os.environ
            if name.startswith(prefix) and name[len(prefix):].isdigit() and (os.getenv(name) or "").strip()
        )
    ]


def _ascii(value: object) -> str:
    text = str(value)
    return text.encode("unicode_escape", errors="backslashreplace").decode("ascii", errors="replace")


def _preview(raw: object, limit: int = 60) -> str:
    text = str(raw).replace("\r", " ").replace("\n", " ")
    escaped = _ascii(text)
    return escaped[:limit]


def _env_status(name: str) -> tuple[bool, str]:
    value = os.getenv(name)
    is_set = bool(value)
    return is_set, f"{name}:{'SET' if is_set else 'UNSET'}:len={len(value or '')}"


def _valid_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_models(raw: str) -> list[str]:
    models = [item.strip() for item in raw.split(",") if item.strip()]
    if not models:
        raise ValueError("no models selected")
    unknown = sorted(set(models) - SUPPORTED_MODELS)
    if unknown:
        raise ValueError("unknown models: " + ",".join(unknown))
    return models


def _prepare_import_path() -> tuple[Path, Path]:
    script_dir = Path(__file__).resolve().parent
    exp3_dir = script_dir.parent
    backend_dir = exp3_dir.parent

    for path in (exp3_dir, backend_dir):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)

    try:
        from dotenv import load_dotenv

        load_dotenv(backend_dir / ".env", override=False)
    except Exception:
        pass

    return exp3_dir, backend_dir


def _import_build_adapter() -> Callable[[str], Any]:
    _prepare_import_path()
    from exp_3_eval_batch import build_adapter

    return build_adapter


def _adapter_endpoint(model: str, adapter: Any) -> str | None:
    if model == "llama70b":
        return NVIDIA_BASE_URL
    return getattr(adapter, "endpoint", None)


def _model_env_parts(model: str) -> tuple[bool, list[str]]:
    if model == "e4b":
        is_set, part = _env_status("LM_STUDIO_CHAT_URL")
        return is_set, [part]

    if model == "gemma31b":
        # 2026-07-12：改直連 Google AI Studio（GEMINI_API_KEYS 多金鑰，見 exp_3_eval_batch）
        keys_set, keys_part = _env_status("GEMINI_API_KEYS")
        n_keys = len([k for k in (os.getenv("GEMINI_API_KEYS") or "").split(",") if k.strip()])
        return keys_set and n_keys > 0, [keys_part, f"keys_count={n_keys}"]

    if model == "gptoss":
        primary_set, primary = _env_status("LM_STUDIO_CHAT_URL_ALT")
        fallback_set, fallback = _env_status("LM_STUDIO_CHAT_URL")
        return primary_set, [primary, "fallback=" + fallback]

    if model == "llama70b":
        # 動態掃 .env 之 NVIDIA_API_KEY_<N>：有幾把用幾把，>=1 即通過（與 pipeline 動態金鑰口徑一致）。
        env_names = _nvidia_env_names()
        parts: list[str] = [part for _, part in (_env_status(n) for n in env_names)]
        parts.append(f"keys_count={len(env_names)}")
        return len(env_names) > 0, parts

    raise ValueError(f"unsupported model: {model}")


def check_model(model: str, build_adapter: Callable[[str], Any]) -> tuple[bool, str]:
    env_ok, env_parts = _model_env_parts(model)
    adapter = None
    adapter_error = ""

    try:
        adapter = build_adapter(model)
    except Exception as exc:
        adapter_error = f"{type(exc).__name__}:{_preview(exc, 80)}"

    url_ok = False
    adapter_class = "NA"
    strict_part = "strict_schema=NA"
    strict_ok = True

    if adapter is not None:
        adapter_class = adapter.__class__.__name__
        url_ok = _valid_url(_adapter_endpoint(model, adapter))
        if hasattr(adapter, "use_strict_schema"):
            strict_value = getattr(adapter, "use_strict_schema")
            strict_part = f"strict_schema={strict_value}"
            if model == "gptoss":
                strict_ok = strict_value is False
                strict_part += ":OK" if strict_ok else ":FAIL"
    else:
        url_ok = False

    ok = env_ok and url_ok and strict_ok and not adapter_error
    parts = [
        f"model={model}",
        f"status={'OK' if ok else 'FAIL'}",
        "env=" + ";".join(env_parts),
        f"url={'VALID' if url_ok else 'INVALID'}",
        f"adapter={adapter_class}",
        strict_part,
    ]
    if adapter_error:
        parts.append("adapter_error=" + adapter_error)
    return ok, " ".join(parts)


def _smoke_messages() -> tuple[str, str]:
    system = (
        "\u4f60\u662f\u7159\u9727\u6e2c\u8a66\u52a9\u624b\u3002"
        "\u53ea\u56de\u4e00\u884c JSON\uff0c\u9375\u70ba answer \u548c reasoning\u3002"
    )
    user = (
        "\u8acb\u56de\u7b54\u6b64\u7159\u9727\u6e2c\u8a66\uff1a"
        "{\"answer\":\"A\",\"reasoning\":\"ok\"}"
    )
    return system, user


def live_model(model: str, build_adapter: Callable[[str], Any]) -> tuple[bool, str]:
    preflight_ok, preflight_line = check_model(model, build_adapter)
    if not preflight_ok:
        return False, (
            f"model={model} status=FAIL latency_ms=0 "
            f"preview=preflight_failed detail={_preview(preflight_line, 120)}"
        )

    adapter = build_adapter(model)
    system, user = _smoke_messages()
    started = time.perf_counter()
    try:
        result = adapter.call(system, user)
        latency_ms = int((time.perf_counter() - started) * 1000)
        api_error = result.get("_api_error") if isinstance(result, dict) else None
        parse_error = result.get("_parse_error") if isinstance(result, dict) else None
        raw = result.get("raw", "") if isinstance(result, dict) else result
        if not raw and isinstance(result, dict):
            raw = json.dumps(
                {"answer": result.get("answer", ""), "reasoning": result.get("reasoning", "")},
                ensure_ascii=False,
            )
        ok = not api_error and not parse_error and bool(str(raw).strip())
        status = "OK" if ok else "FAIL"
        details = []
        if api_error:
            details.append("api_error=" + _preview(api_error, 80))
        if parse_error:
            details.append("parse_error=" + _preview(parse_error, 80))
        suffix = (" " + " ".join(details)) if details else ""
        return ok, (
            f"model={model} status={status} latency_ms={latency_ms} "
            f"preview={_preview(raw, 60)}{suffix}"
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return False, (
            f"model={model} status=FAIL latency_ms={latency_ms} "
            f"preview=exception error={type(exc).__name__}:{_preview(exc, 80)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-env", action="store_true", help="validate local env and adapters only")
    mode.add_argument("--live", action="store_true", help="send one tiny request per selected model")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS), help="comma-separated model keys")
    args = parser.parse_args(argv)

    try:
        models = _parse_models(args.models)
    except ValueError as exc:
        print("ERROR " + _ascii(exc), file=sys.stderr)
        return 2

    try:
        build_adapter = _import_build_adapter()
    except Exception as exc:
        print(f"ERROR import_failed {type(exc).__name__}:{_preview(exc, 120)}", file=sys.stderr)
        return 2

    lines: list[str] = []
    all_ok = True
    for model in models:
        ok, line = live_model(model, build_adapter) if args.live else check_model(model, build_adapter)
        all_ok = all_ok and ok
        lines.append(line)

    for line in lines:
        print(_ascii(line))

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
