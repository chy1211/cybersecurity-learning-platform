#!/usr/bin/env python
"""Stub test for ETL prompt routing without calling an LLM."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types as module_types
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[2]
ETL_02 = BACKEND_DIR / "ETL_module" / "02_extract_triples.py"
PROMPTS_DIR = BACKEND_DIR / "prompts" / "etl"


def install_google_genai_stub() -> None:
    google_module = sys.modules.get("google")
    if google_module is None:
        google_module = module_types.ModuleType("google")
        google_module.__path__ = []
        sys.modules["google"] = google_module

    genai_module = module_types.ModuleType("google.genai")

    class Client:
        def __init__(self, *args, **kwargs):
            self.models = None

    genai_module.Client = Client
    genai_types_module = module_types.ModuleType("google.genai.types")
    genai_module.types = genai_types_module
    google_module.genai = genai_module
    sys.modules["google.genai"] = genai_module
    sys.modules["google.genai.types"] = genai_types_module


def load_etl_02():
    install_google_genai_stub()
    spec = importlib.util.spec_from_file_location("etl_02_extract_triples", ETL_02)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load ETL 02 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_chunk(path: Path, source_id: str, source_file: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_id": source_id,
                "source_file": source_file,
                "text": text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    original_template = (PROMPTS_DIR / "extract_triples_user.md").read_text(encoding="utf-8")
    question_template = (PROMPTS_DIR / "extract_triples_user_question.md").read_text(encoding="utf-8")
    material_text = "Material concept: Encryption protects confidentiality."
    question_text = (
        "Question ID: Q001\n"
        "Question Type: single\n"
        "Stem:\n"
        "Which control protects data confidentiality?\n"
        "Options:\n"
        "A. Encryption\n"
        "B. Guessing\n"
        "Correct Answer: A. Encryption"
    )

    module = load_etl_02()
    captured_prompts: list[str] = []

    def fake_call_gemma(prompt: str) -> str:
        captured_prompts.append(prompt)
        return "[]"

    module.call_gemma = fake_call_gemma

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        chunks_dir = root / "Chunks"
        raw_triples_dir = root / "RawTriples"
        write_chunk(
            chunks_dir / "material_source" / "chunk_1.json",
            "chunk_1",
            "material_source.pdf",
            material_text,
        )
        write_chunk(
            chunks_dir / "questions_corpus.json" / "question_Q001.json",
            "question_Q001",
            "questions_corpus.json",
            question_text,
        )
        module.CHUNKS_DIR = str(chunks_dir)
        module.RAW_TRIPLES_DIR = str(raw_triples_dir)

        with contextlib.redirect_stdout(io.StringIO()):
            module.main()

    assert len(captured_prompts) == 2, f"captured={len(captured_prompts)}"
    material_prompt = next(prompt for prompt in captured_prompts if material_text in prompt)
    question_prompt = next(prompt for prompt in captured_prompts if question_text in prompt)

    expected_material_prompt = original_template.format(chunk_text=material_text)
    expected_question_prompt = question_template.format(chunk_text=question_text)

    assert material_prompt.encode("utf-8") == expected_material_prompt.encode("utf-8")
    print("assert_material_prompt_bytes=ok")

    assert "請分析以下文本並萃取三元組" in material_prompt
    print("assert_material_prompt_feature=ok")

    assert question_prompt == expected_question_prompt
    assert "資安考題" in question_prompt
    assert "干擾選項" in question_prompt
    print("assert_question_prompt_feature=ok")

    print("OK question_prompt_wiring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
