#!/usr/bin/env python
"""Knowledge-point overlap analysis across question and teaching sources."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[2]
PLATFORM_DIR = SCRIPT_PATH.parents[3]
HANDOFF_DIR = SCRIPT_PATH.parents[4]
THESIS_DIR = SCRIPT_PATH.parents[5]
WORKSPACE_DIR = SCRIPT_PATH.parents[6]

DEFAULT_ITE_PATH = BACKEND_DIR / "exp_3" / "data" / "question_bank_329.json"
DEFAULT_IPAS_PATHS = [
    WORKSPACE_DIR / "_tooling" / "rerun_test" / "ipas_sample_mgmt10.json",
    WORKSPACE_DIR / "_tooling" / "rerun_test" / "ipas_sample_tech10.json",
]
DEFAULT_SOURCE_DATA_DIR = THESIS_DIR / "SourceData"
DEFAULT_SLIDES_DIR = DEFAULT_SOURCE_DATA_DIR / "投影片"
DEFAULT_EXERCISES_DIR = DEFAULT_SOURCE_DATA_DIR / "習題解答"
DEFAULT_FALLBACK_DIR = BACKEND_DIR / "exp_1" / "MatchGPT" / "phase1_results"
DEFAULT_FALLBACK_CSVS = [
    DEFAULT_FALLBACK_DIR / "matchgpt_merged_t07.csv",
    DEFAULT_FALLBACK_DIR / "matchgpt_decisions.csv",
    DEFAULT_FALLBACK_DIR / "matchgpt_candidate_pairs.csv",
]
DEFAULT_OUT = WORKSPACE_DIR / "_tooling" / "rerun_test" / "overlap_analysis.txt"
DEFAULT_DETAILS = WORKSPACE_DIR / "_tooling" / "rerun_test" / "overlap_analysis_details.json"
SUPPORTED_SOURCES = {"ite", "ipas", "slides", "exercises"}


class VocabularyResult:
    def __init__(
        self,
        source: str,
        source_detail: str,
        entities: list[str],
        warnings: list[str] | None = None,
    ) -> None:
        self.source = source
        self.source_detail = source_detail
        self.entities = entities
        self.warnings = warnings or []


class SourceBundle:
    def __init__(self, name: str, texts: list[str], files: list[Path]) -> None:
        self.name = name
        self.texts = texts
        self.files = files


def normalize_for_match(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"\s+", "", text)


def display_entity(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def sort_key(value: str) -> tuple[str, str]:
    return (normalize_for_match(value), value)


def unique_entities(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    entities: list[str] = []
    for value in values:
        entity = display_entity(value)
        normalized = normalize_for_match(entity)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        entities.append(entity)
    return entities


def match_entities_in_text(vocabulary: Sequence[str], text: str) -> set[str]:
    normalized_text = normalize_for_match(text)
    matched: set[str] = set()
    for entity in vocabulary:
        normalized_entity = normalize_for_match(entity)
        if len(normalized_entity) < 2:
            continue
        if normalized_entity in normalized_text:
            matched.add(entity)
    return matched


def read_json_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("questions", "items", "data", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if all(isinstance(value, dict) for value in data.values()):
            return list(data.values())
    raise ValueError(f"Unsupported JSON structure: {path}")


def normalize_options(options: Any) -> list[tuple[str, str]]:
    if isinstance(options, dict):
        return [(str(key), str(value)) for key, value in sorted(options.items())]
    if isinstance(options, list):
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return [(letters[index], str(value)) for index, value in enumerate(options)]
    return []


def render_question_text(question: dict[str, Any]) -> str:
    qid = question.get("qid") or question.get("id") or ""
    stem = str(question.get("stem") or "").strip()
    subject = str(question.get("subject") or question.get("cert_type") or "").strip()
    year = str(question.get("year") or "").strip()
    lines = []
    if qid:
        lines.append(f"Question ID: {qid}")
    if subject:
        lines.append(f"Subject: {subject}")
    if year:
        lines.append(f"Year: {year}")
    lines.append("Stem:")
    lines.append(stem)
    options = normalize_options(question.get("options"))
    if options:
        lines.append("Options:")
        lines.extend(f"{key}. {value}" for key, value in options)
    return "\n".join(lines).strip()


def load_ite_texts(path: Path) -> list[str]:
    records = read_json_records(path)
    texts: list[str] = []
    for record in records:
        qid = str(record.get("qid") or record.get("id") or "")
        if not qid.startswith(("ISN-", "ISK-")):
            continue
        texts.append(render_question_text(record))
    return texts


def load_ipas_texts(paths: Sequence[Path]) -> list[str]:
    texts: list[str] = []
    for path in paths:
        for record in read_json_records(path):
            texts.append(render_question_text(record))
    return texts


def extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # type: ignore

        with fitz.open(path) as doc:
            return "\n".join(page.get_text("text") for page in doc)
    except Exception:
        try:
            import pdfplumber  # type: ignore

            with pdfplumber.open(path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as exc:
            raise RuntimeError(f"PDF text extraction failed for {path}: {exc}") from exc


def selected_pdfs(directory: Path, explicit_paths: Sequence[Path] | None, limit: int | None) -> list[Path]:
    if explicit_paths:
        files = [path for path in explicit_paths if path.exists()]
    else:
        files = sorted(path for path in directory.glob("*.pdf") if path.is_file())
    if limit is not None:
        files = files[:limit]
    return files


def load_pdf_texts(directory: Path, explicit_paths: Sequence[Path] | None, limit: int | None) -> tuple[list[str], list[Path]]:
    files = selected_pdfs(directory, explicit_paths, limit)
    return [extract_pdf_text(path) for path in files], files


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        values[key] = value
    return values


def collect_alias_values(row: Any) -> list[Any]:
    values: list[Any] = [row.get("name"), row.get("alias")]
    aliases = row.get("aliases")
    if isinstance(aliases, (list, tuple, set)):
        values.extend(aliases)
    else:
        values.append(aliases)
    return values


def load_neo4j_vocabulary(uri: str, user: str, password: str, database: str | None) -> VocabularyResult:
    from neo4j import GraphDatabase, READ_ACCESS  # type: ignore

    driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5)
    try:
        driver.verify_connectivity()
        session_kwargs: dict[str, Any] = {"default_access_mode": READ_ACCESS}
        if database:
            session_kwargs["database"] = database
        entities: list[str] = []
        with driver.session(**session_kwargs) as session:
            rows = session.run("MATCH (n) RETURN n.name AS name, n.alias AS alias, n.aliases AS aliases")
            for row in rows:
                entities.extend(collect_alias_values(row))
        deduped = unique_entities(entities)
        detail = uri if not database else f"{uri} database={database}"
        return VocabularyResult("neo4j", detail, deduped)
    finally:
        driver.close()


def load_fallback_vocabulary(csv_paths: Sequence[Path]) -> VocabularyResult:
    warnings: list[str] = []
    for path in csv_paths:
        if not path.exists() or not path.is_file():
            continue
        values: list[str] = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                fields = set(reader.fieldnames or [])
                name_fields = [field for field in ("name", "entity", "entity_name", "name_a", "name_b") if field in fields]
                if not name_fields:
                    warnings.append(f"No entity-name columns in {path}")
                    continue
                for row in reader:
                    values.extend(row.get(field, "") for field in name_fields)
        except Exception as exc:
            warnings.append(f"Failed reading fallback CSV {path}: {exc}")
            continue
        entities = unique_entities(values)
        if entities:
            return VocabularyResult("fallback", str(path), entities, warnings)
    return VocabularyResult("fallback", "", [], warnings + ["No fallback vocabulary file produced entities."])


def resolve_vocabulary(args: argparse.Namespace) -> VocabularyResult:
    warnings: list[str] = []
    if args.vocab_source in ("auto", "neo4j"):
        try:
            result = load_neo4j_vocabulary(args.neo4j_uri, args.user, args.password, args.database)
            if result.entities:
                return result
            warnings.append("Neo4j returned zero entities.")
        except Exception as exc:
            warnings.append(f"Neo4j vocabulary query failed: {type(exc).__name__}: {exc}")
            if args.vocab_source == "neo4j":
                return VocabularyResult("neo4j", args.neo4j_uri, [], warnings)

    fallback_paths = args.fallback_csv or DEFAULT_FALLBACK_CSVS
    result = load_fallback_vocabulary(fallback_paths)
    result.warnings = warnings + result.warnings
    return result


def rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_DIR.resolve()))
    except Exception:
        return str(path)


def parse_sources(value: str) -> list[str]:
    sources = [item.strip().lower() for item in value.split(",") if item.strip()]
    invalid = [source for source in sources if source not in SUPPORTED_SOURCES]
    if invalid:
        raise ValueError(f"Unsupported sources: {', '.join(invalid)}")
    return sources


def load_source_bundle(source: str, args: argparse.Namespace) -> SourceBundle:
    if source == "ite":
        path = args.ite_path
        return SourceBundle(source, load_ite_texts(path), [path])
    if source == "ipas":
        paths = args.ipas or [path for path in DEFAULT_IPAS_PATHS if path.exists()]
        return SourceBundle(source, load_ipas_texts(paths), list(paths))
    if source == "slides":
        texts, files = load_pdf_texts(args.slides_dir, args.slides_pdf, args.slides_limit)
        return SourceBundle(source, texts, files)
    if source == "exercises":
        texts, files = load_pdf_texts(args.exercises_dir, args.exercises_pdf, args.exercises_limit)
        return SourceBundle(source, texts, files)
    raise ValueError(f"Unsupported source: {source}")


def source_knowledge_points(vocabulary: Sequence[str], texts: Sequence[str]) -> list[str]:
    matched: set[str] = set()
    for text in texts:
        matched.update(match_entities_in_text(vocabulary, text))
    return sorted(matched, key=sort_key)


def pair_key(a_name: str, b_name: str) -> str:
    return f"{a_name}__{b_name}"


def analyze_overlap(
    vocabulary: Sequence[str],
    source_texts: dict[str, Sequence[str]],
    dry_run_note: str | None,
    vocabulary_source: str,
    vocabulary_source_detail: str,
    source_files: dict[str, Sequence[Path]] | None = None,
    warnings: Sequence[str] | None = None,
) -> dict[str, Any]:
    deduped_vocabulary = unique_entities(vocabulary)
    source_files = source_files or {}
    result: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "dry_run_note": dry_run_note,
            "vocabulary_source": vocabulary_source,
            "vocabulary_source_detail": vocabulary_source_detail,
            "vocabulary_entity_count": len(deduped_vocabulary),
            "warnings": list(warnings or []),
        },
        "sources": {},
        "pairwise": {},
    }

    source_sets: dict[str, set[str]] = {}
    for name, texts in source_texts.items():
        points = source_knowledge_points(deduped_vocabulary, texts)
        source_sets[name] = set(points)
        result["sources"][name] = {
            "text_count": len(texts),
            "file_count": len(source_files.get(name, [])),
            "files": [rel_path(path) for path in source_files.get(name, [])],
            "knowledge_point_count": len(points),
            "knowledge_points": points,
        }

    for a_name, b_name in combinations(source_texts.keys(), 2):
        a_points = source_sets[a_name]
        b_points = source_sets[b_name]
        common = sorted(a_points & b_points, key=sort_key)
        a_only = sorted(a_points - b_points, key=sort_key)
        b_only = sorted(b_points - a_points, key=sort_key)
        union_count = len(a_points | b_points)
        jaccard = (len(common) / union_count) if union_count else 0.0
        result["pairwise"][pair_key(a_name, b_name)] = {
            "a": a_name,
            "b": b_name,
            "a_count": len(a_points),
            "b_count": len(b_points),
            "common_count": len(common),
            "jaccard": round(jaccard, 4),
            "common_examples": common[:10],
            "a_only_examples": a_only[:10],
            "b_only_examples": b_only[:10],
        }
    return result


def format_examples(values: Sequence[str]) -> str:
    return "、".join(values) if values else "（無）"


def write_report(result: dict[str, Any], out_path: Path) -> None:
    metadata = result["metadata"]
    lines: list[str] = []
    lines.append("# 題源／教材知識點重疊分析")
    lines.append("")
    if metadata.get("dry_run_note"):
        lines.append(str(metadata["dry_run_note"]))
        lines.append("")
    lines.append(
        f"詞彙表來源：{metadata['vocabulary_source']}（{metadata['vocabulary_source_detail'] or 'n/a'}）；"
        f"實體數：{metadata['vocabulary_entity_count']}"
    )
    if metadata.get("warnings"):
        lines.append("")
        lines.append("警告：")
        for warning in metadata["warnings"]:
            lines.append(f"- {warning}")
    lines.append("")
    lines.append("## 每來源知識點數")
    lines.append("")
    lines.append("| 來源 | 文本數 | 檔案數 | 知識點數 |")
    lines.append("|---|---:|---:|---:|")
    for name, source in result["sources"].items():
        lines.append(f"| {name} | {source['text_count']} | {source['file_count']} | {source['knowledge_point_count']} |")

    lines.append("")
    lines.append("## 兩兩交集矩陣")
    lines.append("")
    lines.append("| A | B | A 有 | B 有 | 共同 | Jaccard |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for pair in result["pairwise"].values():
        lines.append(
            f"| {pair['a']} | {pair['b']} | {pair['a_count']} | {pair['b_count']} | "
            f"{pair['common_count']} | {pair['jaccard']:.4f} |"
        )

    lines.append("")
    lines.append("## 範例")
    for pair in result["pairwise"].values():
        lines.append("")
        lines.append(f"### {pair['a']} vs {pair['b']}")
        lines.append(f"- 共同知識點：{format_examples(pair['common_examples'])}")
        lines.append(f"- {pair['a']} 獨有：{format_examples(pair['a_only_examples'])}")
        lines.append(f"- {pair['b']} 獨有：{format_examples(pair['b_only_examples'])}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_details(result: dict[str, Any], details_path: Path) -> None:
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    env_values = read_env_file(BACKEND_DIR / ".env")
    env_example_values = read_env_file(BACKEND_DIR / ".env.example")
    default_uri = os.getenv("NEO4J_URI") or env_values.get("NEO4J_URI") or env_example_values.get("NEO4J_URI") or "bolt://127.0.0.1:7687"
    default_user = os.getenv("NEO4J_USER") or env_values.get("NEO4J_USER") or env_example_values.get("NEO4J_USER") or "neo4j"
    default_password = os.getenv("NEO4J_PASSWORD") or env_values.get("NEO4J_PASSWORD") or env_example_values.get("NEO4J_PASSWORD") or ""
    default_database = os.getenv("NEO4J_DATABASE") or env_values.get("NEO4J_DATABASE") or env_example_values.get("NEO4J_DATABASE") or None

    parser = argparse.ArgumentParser(description="Analyze named-source overlap using graph entity names as knowledge points.")
    parser.add_argument("--sources", default="ite,ipas,slides,exercises", help="Comma-separated source names: ite,ipas,slides,exercises.")
    parser.add_argument("--ite-path", type=Path, default=DEFAULT_ITE_PATH, help="ITE question_bank_329.json path.")
    parser.add_argument("--ipas", type=Path, nargs="*", default=None, help="One or more iPAS question JSON files.")
    parser.add_argument("--slides-dir", type=Path, default=DEFAULT_SLIDES_DIR, help="Slides PDF directory.")
    parser.add_argument("--slides-pdf", type=Path, action="append", default=None, help="Explicit slides PDF path; may repeat.")
    parser.add_argument("--slides-limit", type=int, default=None, help="Limit slides PDFs after sorting.")
    parser.add_argument("--exercises-dir", type=Path, default=DEFAULT_EXERCISES_DIR, help="Exercises PDF directory.")
    parser.add_argument("--exercises-pdf", type=Path, action="append", default=None, help="Explicit exercises PDF path; may repeat.")
    parser.add_argument("--exercises-limit", type=int, default=None, help="Limit exercise PDFs after sorting.")
    parser.add_argument("--vocab-source", choices=["auto", "neo4j", "fallback"], default="auto", help="Vocabulary source priority.")
    parser.add_argument("--fallback-csv", type=Path, action="append", default=None, help="Fallback CSV path; may repeat.")
    parser.add_argument("--neo4j-uri", "--uri", dest="neo4j_uri", default=default_uri, help="Neo4j URI.")
    parser.add_argument("--user", default=default_user, help="Neo4j username.")
    parser.add_argument("--password", default=default_password, help="Neo4j password; prefer environment or backend .env.")
    parser.add_argument("--database", "--db", dest="database", default=default_database, help="Optional Neo4j database.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="UTF-8 text report output path.")
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS, help="Full JSON details output path.")
    parser.add_argument("--dry-run", action="store_true", help="Mark the report as dry-run.")
    parser.add_argument("--dry-run-note", default=None, help="Custom dry-run note written at report top.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sources = parse_sources(args.sources)
    except ValueError as exc:
        print(f"status=error error={exc}")
        return 2

    vocab = resolve_vocabulary(args)
    if not vocab.entities:
        print("status=blocked reason=no_vocabulary")
        return 3

    source_texts: dict[str, Sequence[str]] = {}
    source_files: dict[str, Sequence[Path]] = {}
    for source in sources:
        bundle = load_source_bundle(source, args)
        source_texts[source] = bundle.texts
        source_files[source] = bundle.files

    dry_run_note = args.dry_run_note
    if args.dry_run and not dry_run_note:
        dry_run_note = "DRY-RUN：ipas 僅樣本 20 題、教材僅各 2 份；正式全量報告須改用完整 iPAS 題池與全教材。"

    result = analyze_overlap(
        vocabulary=vocab.entities,
        source_texts=source_texts,
        dry_run_note=dry_run_note,
        vocabulary_source=vocab.source,
        vocabulary_source_detail=vocab.source_detail,
        source_files=source_files,
        warnings=vocab.warnings,
    )
    write_report(result, args.out)
    write_details(result, args.details)

    print("status=ok")
    print(f"report={args.out}")
    print(f"details={args.details}")
    print(f"vocabulary_source={vocab.source}")
    print(f"vocabulary_count={len(vocab.entities)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
