from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class CorpusText:
    path: str
    text: str


@dataclass(frozen=True)
class Leak:
    question_id: str
    field: str
    corpus_path: str
    snippet: str


@dataclass(frozen=True)
class LeakageResult:
    leaks: list[Leak]
    skipped_fragments: int
    checked_fragments: int


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    kept: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch.isspace() or category[0] in {"P", "Z"}:
            continue
        kept.append(ch)
    return "".join(kept)


def load_json_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        list_values = [value for value in data.values() if isinstance(value, list)]
        if len(list_values) != 1:
            raise ValueError(f"cannot identify record list in {path}")
        records = list_values[0]
    else:
        raise ValueError(f"unsupported JSON top-level type in {path}: {type(data).__name__}")

    if not all(isinstance(item, dict) for item in records):
        raise ValueError(f"not every record is an object in {path}")
    return records


def parse_path_list(value: str) -> list[Path]:
    paths: list[Path] = []
    for part in str(value).split(","):
        stripped = part.strip()
        if stripped:
            paths.append(Path(stripped))
    return paths


def collect_json_strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            collect_json_strings(item, out)
    elif isinstance(value, list):
        for item in value:
            collect_json_strings(item, out)


def read_corpus_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        strings: list[str] = []
        collect_json_strings(data, strings)
        return "\n".join(strings)
    raise ValueError(f"unsupported corpus file type: {path}")


def iter_corpus_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                child
                for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in {".txt", ".json"}
            )
        elif path.is_file() and path.suffix.lower() in {".txt", ".json"}:
            files.append(path)
        elif path.exists():
            raise ValueError(f"unsupported corpus path: {path}")
        else:
            raise FileNotFoundError(path)
    return sorted(files, key=lambda item: str(item).lower())


def load_corpus(paths: Iterable[Path]) -> list[CorpusText]:
    return [
        CorpusText(path=str(path), text=read_corpus_file(path))
        for path in iter_corpus_files(paths)
    ]


def question_id(record: dict[str, Any]) -> str:
    for key in ("qid", "id", "question_id", "raw_qno"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "(missing-id)"


def option_fragments(options: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(options, dict):
        for key in sorted(options):
            yield f"option:{key}", options[key]
    elif isinstance(options, list):
        for idx, value in enumerate(options):
            yield f"option:{idx}", value


def heldout_fragments(record: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    yield "stem", record.get("stem", "")
    yield from option_fragments(record.get("options", {}))


def detect_leaks(
    heldout_records: list[dict[str, Any]],
    corpus_texts: list[CorpusText],
    *,
    min_len: int,
) -> LeakageResult:
    normalized_corpus = [
        (corpus.path, normalize_text(corpus.text)) for corpus in corpus_texts
    ]
    leaks: list[Leak] = []
    skipped = 0
    checked = 0

    for record in heldout_records:
        qid = question_id(record)
        for field, raw_text in heldout_fragments(record):
            normalized_fragment = normalize_text(raw_text)
            if len(normalized_fragment) < min_len:
                skipped += 1
                continue
            checked += 1
            for corpus_path, corpus_norm in normalized_corpus:
                index = corpus_norm.find(normalized_fragment)
                if index >= 0:
                    leaks.append(
                        Leak(
                            question_id=qid,
                            field=field,
                            corpus_path=corpus_path,
                            snippet=corpus_norm[index : index + 40],
                        )
                    )

    return LeakageResult(
        leaks=leaks,
        skipped_fragments=skipped,
        checked_fragments=checked,
    )


def write_report(path: Path, result: LeakageResult) -> None:
    lines = [
        "# Leakage Check Report",
        "",
        f"CHECKED_FRAGMENTS={result.checked_fragments}",
        f"SKIPPED_SHORT_FRAGMENTS={result.skipped_fragments}",
        "",
        "## Leaks",
    ]
    if result.leaks:
        for leak in result.leaks:
            corpus_path = str(leak.corpus_path).replace("\n", " ")
            snippet = re.sub(r"\s+", " ", leak.snippet)
            lines.append(
                f"LEAK question_id={leak.question_id} field={leak.field} file={corpus_path} snippet={snippet}"
            )
    else:
        lines.append("(none)")
    lines.append(f"LEAK_COUNT={len(result.leaks)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check heldout question stems/options against construction corpus text."
    )
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--min-len", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    heldout_records = load_json_records(args.heldout)
    corpus = load_corpus(parse_path_list(args.corpus))
    result = detect_leaks(heldout_records, corpus, min_len=args.min_len)
    write_report(args.out, result)
    status = "LEAK" if result.leaks else "OK"
    print(f"{status} leak_count={len(result.leaks)} report={args.out.name}")
    return 1 if result.leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
