from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = SOURCE_ROOT.parent / "交接_release"
DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
TEXT_SCAN_MAX_BYTES = 2 * 1024 * 1024

ROOT_FILES = {
    ".gitignore",
    "DATA_MANIFEST.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "REPRODUCE_EXPERIMENTS.md",
    "SECURITY_NOTES.md",
    "GITHUB_RELEASE_CHECKLIST.md",
    "GITHUB_PUBLISH_PLAN.md",
    "HANDOFF_README_FOR_SUCCESSOR.md",
}
ROOT_TREES = {"Prompt", "本體論"}
TOOL_FILES = {
    "build_clean_release.py",
    "check_release_ready.py",
    "export_community_naming_evidence.py",
    "final_api_acceptance.py",
    "final_llm_smoke.py",
    "smoke_test_platform.py",
    "validate_post_apply_analysis.py",
    "SECURITY_NOTES.md",
}
PLATFORM_ROOT_FILES = {".gitignore"}
BACKEND_ROOT_FILES = {
    ".env.example",
    "app.py",
    "config.py",
    "llm_service.py",
    "neo4j_service.py",
    "persistence_service.py",
    "requirements.txt",
    "requirements-platform.txt",
    "requirements-etl.txt",
    "requirements-exp1.txt",
    "requirements-exp2.txt",
    "requirements-exp3.txt",
}
BACKEND_TREES = {"ETL_module", "exp_1", "exp_2", "exp_3", "prompts", "tests"}
ETL_PUBLIC_DATA_TREES = {"RawTriples", "Rejected", "Validated", "gamma實驗", "minCommunitySize實驗"}
EXPERIMENT_PUBLIC_TREES = {
    "exp_1": {"MatchGPT", "rerun_prep"},
    "exp_2": {"phase2"},
    "exp_3": {"b4", "config", "data", "scripts"},
}
FRONTEND_ROOT_FILES = {
    ".eslintrc.cjs",
    "eslint.config.js",
    "index.html",
    "package-lock.json",
    "package.json",
    "postcss.config.js",
    "tailwind.config.js",
    "vite.config.js",
}
FRONTEND_TREES = {"public", "scripts", "src"}

FORBIDDEN_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "archive",
    "archives",
    "backup",
    "backups",
    "cache",
    "caches",
    "chunks",
    "coverage",
    "dist",
    "graphify-out",
    "logs",
    "node_modules",
    "_migration_output",
}
FORBIDDEN_EXACT_NAMES = {
    ".env",
    ".graphifyignore",
    "graphify_detect_summary.json",
    "analysis_properties_before.json",
}
FORBIDDEN_DATA_NAME_FRAGMENTS = ("backup", "bytecode", "embedding_cache", "semantic_index")
FORBIDDEN_SUFFIXES = {".bak", ".log", ".pyc", ".pyo", ".tmp"}
ALLOWED_SUFFIXES = {
    "",
    ".cjs",
    ".css",
    ".csv",
    ".example",
    ".html",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".png",
    ".ps1",
    ".py",
    ".svg",
    ".toml",
    ".tsv",
    ".txt",
    ".xlsx",
    ".yaml",
    ".yml",
}

SECRET_PATTERNS = {
    "NVIDIA_API_KEY": re.compile(r"nvapi-[A-Za-z0-9_-]{20,}"),
    "GROQ_API_KEY": re.compile(r"gsk_[A-Za-z0-9_-]{20,}"),
    "GOOGLE_API_KEY": re.compile(r"AIza[A-Za-z0-9_-]{20,}"),
    "OPENAI_API_KEY": re.compile(r"sk-(?:proj-|live-)?[A-Za-z0-9_-]{20,}"),
}
ENV_ASSIGNMENT = re.compile(
    r"\b(OPENAI_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY(?:S)?|GROQ_API_KEY(?:_[0-9]+)?|"
    r"NVIDIA_API_KEY(?:_[0-9]+)?|NEO4J_PASSWORD)\s*=\s*(.+)"
)


class ReleaseBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    copied_files: int
    copied_bytes: int
    excluded_files: int
    excluded_reasons: dict[str, int]
    output: str


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized in {"changeme", "example", "none", "null", "placeholder", "replace_me"}
        or (normalized.startswith("<") and normalized.endswith(">"))
        or normalized.startswith("your_")
        or normalized.startswith("your-")
    )


def _forbidden_reason(relative: Path) -> str | None:
    lowered_parts = [part.lower() for part in relative.parts]
    name = relative.name.lower()
    if name in FORBIDDEN_EXACT_NAMES:
        return "private_or_local_file"
    if any(
        part in FORBIDDEN_PARTS
        or "backup" in part
        or part.startswith("_archive")
        or part.startswith("_pre_restore")
        for part in lowered_parts[:-1]
    ):
        return "forbidden_directory"
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        return "generated_or_log_suffix"
    if any(fragment in name for fragment in ("embedding_cache", "semantic_index", "bytecode")):
        return "cache_or_backup_name"
    if "backup" in name and relative.suffix.lower() not in {".md", ".py", ".txt"}:
        return "cache_or_backup_name"
    if name.startswith("pre_") and "kg" in name and relative.suffix.lower() in {".json", ".csv"}:
        return "database_snapshot_name"
    return None


def _allowlisted(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in ROOT_FILES
    if parts[0] == "docs":
        return len(parts) > 2 and parts[1] == "images" and relative.suffix.lower() in ALLOWED_SUFFIXES
    if parts[0] in ROOT_TREES:
        return relative.suffix.lower() in ALLOWED_SUFFIXES
    if parts[0] == "tools":
        return len(parts) == 2 and parts[1] in TOOL_FILES
    if parts[0] != "CybersecurityLearningPlatform":
        return False
    if len(parts) == 2:
        return parts[1] in PLATFORM_ROOT_FILES
    if parts[1] == "backend":
        if len(parts) == 3:
            return parts[2] in BACKEND_ROOT_FILES
        area = parts[2]
        if area not in BACKEND_TREES or relative.suffix.lower() not in ALLOWED_SUFFIXES:
            return False
        if area in {"prompts", "tests"}:
            return True
        if area == "ETL_module":
            return len(parts) == 4 or (len(parts) > 4 and parts[3] in ETL_PUBLIC_DATA_TREES)
        if area in EXPERIMENT_PUBLIC_TREES:
            return len(parts) == 4 or (len(parts) > 4 and parts[3] in EXPERIMENT_PUBLIC_TREES[area])
        return False
    if parts[1] == "frontend":
        if len(parts) == 3:
            return parts[2] in FRONTEND_ROOT_FILES
        return parts[2] in FRONTEND_TREES and relative.suffix.lower() in ALLOWED_SUFFIXES
    return False


def _prepare_output(source: Path, output: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    if output == source or output in source.parents or source in output.parents:
        raise ReleaseBuildError(f"Unsafe output location: {output}")
    if output.parent != source.parent:
        raise ReleaseBuildError("Output must be a sibling of the source directory")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)


def _copy_candidates(source: Path, output: Path, max_file_bytes: int) -> BuildResult:
    copied_files = 0
    copied_bytes = 0
    excluded = Counter()
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        reason = _forbidden_reason(relative)
        if reason:
            excluded[reason] += 1
            continue
        if not _allowlisted(relative):
            excluded["not_allowlisted"] += 1
            continue
        size = path.stat().st_size
        if size > max_file_bytes:
            raise ReleaseBuildError(
                f"Unapproved oversized file: {_relative(path, source)} ({size} bytes; limit={max_file_bytes})"
            )
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied_files += 1
        copied_bytes += size
    return BuildResult(
        copied_files=copied_files,
        copied_bytes=copied_bytes,
        excluded_files=sum(excluded.values()),
        excluded_reasons=dict(sorted(excluded.items())),
        output=str(output),
    )


def validate_release(root: Path) -> list[str]:
    errors: list[str] = []
    root = root.resolve()
    if not root.is_dir():
        return [f"MISSING_RELEASE_ROOT {root}"]
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        reason = _forbidden_reason(relative)
        if reason:
            errors.append(f"FORBIDDEN_PATH {relative.as_posix()} reason={reason}")
            continue
        if not _allowlisted(relative) and relative.name != "RELEASE_BUILD_MANIFEST.json":
            errors.append(f"NOT_ALLOWLISTED {relative.as_posix()}")
        if path.stat().st_size > TEXT_SCAN_MAX_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    errors.append(f"SECRET_LIKE_VALUE {relative.as_posix()}:{line_no} {label}")
            match = ENV_ASSIGNMENT.search(line)
            if match and "getenv(" not in match.group(2) and not _is_placeholder(match.group(2)):
                errors.append(f"NON_PLACEHOLDER_SECRET_ENV {relative.as_posix()}:{line_no} {match.group(1)}")
    return errors


def build_release(source: Path, output: Path, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> BuildResult:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise ReleaseBuildError(f"Source directory does not exist: {source}")
    _prepare_output(source, output)
    result = _copy_candidates(source, output, max_file_bytes)
    errors = validate_release(output)
    if errors:
        shutil.rmtree(output)
        raise ReleaseBuildError("Release validation failed:\n" + "\n".join(errors[:50]))
    manifest = {
        "schema_version": 1,
        "copied_files": result.copied_files,
        "copied_bytes": result.copied_bytes,
        "excluded_files": result.excluded_files,
        "excluded_reasons": result.excluded_reasons,
        "policy": "allowlist",
        "source_tree_copied": False,
    }
    (output / "RELEASE_BUILD_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    post_manifest_errors = validate_release(output)
    if post_manifest_errors:
        shutil.rmtree(output)
        raise ReleaseBuildError("Post-manifest validation failed:\n" + "\n".join(post_manifest_errors[:50]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean public handoff release from an explicit allowlist.")
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-file-mib", type=int, default=DEFAULT_MAX_FILE_BYTES // (1024 * 1024))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.validate_only:
            errors = validate_release(args.output)
            if errors:
                print(f"errors={len(errors)}")
                for error in errors:
                    print(f"ERROR {error}")
                print("FAIL")
                return 1
            print("errors=0")
            print("PASS")
            return 0
        result = build_release(args.source, args.output, args.max_file_mib * 1024 * 1024)
    except ReleaseBuildError as exc:
        print(f"ERROR {exc}")
        print("FAIL")
        return 1
    summary = asdict(result)
    print(f"copied_files={summary['copied_files']}")
    print(f"copied_bytes={summary['copied_bytes']}")
    print(f"excluded_files={summary['excluded_files']}")
    print("excluded_reasons=" + json.dumps(summary["excluded_reasons"], ensure_ascii=False, sort_keys=True))
    print(f"output={summary['output']}")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
