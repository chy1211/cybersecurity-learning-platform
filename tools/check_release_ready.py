from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MAX_GITHUB_FILE_BYTES = 100 * 1024 * 1024

SKIP_PARTS = {".git", "node_modules", "graphify-out", "__pycache__", "dist", "build", "coverage"}
SKIP_NAMES = {".graphifyignore", "graphify_detect_summary.json"}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".env",
    ".example",
    ".yml",
    ".yaml",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".toml",
    ".ps1",
}

REQUIRED_PATHS = [
    "README.md",
    "HANDOFF_README_FOR_SUCCESSOR.md",
    "DATA_MANIFEST.md",
    "REPRODUCE_EXPERIMENTS.md",
    "SECURITY_NOTES.md",
    "GITHUB_RELEASE_CHECKLIST.md",
    "GITHUB_PUBLISH_PLAN.md",
    ".gitignore",
    "Prompt/README.md",
    "本體論",
    "CybersecurityLearningPlatform/backend/.env.example",
    "CybersecurityLearningPlatform/backend/ETL_module/RawTriples",
    "CybersecurityLearningPlatform/backend/ETL_module/Rejected",
    "CybersecurityLearningPlatform/backend/ETL_module/Validated",
    "CybersecurityLearningPlatform/backend/exp_1",
    "CybersecurityLearningPlatform/backend/exp_2",
    "CybersecurityLearningPlatform/backend/exp_2",
    "CybersecurityLearningPlatform/backend/prompts",
]

MUST_NOT_EXIST = [
    "CybersecurityLearningPlatform/backend/.env",
]

LOCAL_ONLY_ALLOWED = [
    "CybersecurityLearningPlatform/graphify-out",
    "CybersecurityLearningPlatform/.graphifyignore",
    "CybersecurityLearningPlatform/graphify_detect_summary.json",
    "CybersecurityLearningPlatform/frontend/node_modules",
    "CybersecurityLearningPlatform/frontend/dist",
]

REQUIRED_GITIGNORE_PATTERNS = [
    ".env",
    "node_modules/",
    "CybersecurityLearningPlatform/backend/ETL_module/Chunks/",
    "CybersecurityLearningPlatform/graphify-out/",
    "CybersecurityLearningPlatform/graphify_detect_summary.json",
    "CybersecurityLearningPlatform/.graphifyignore",
    "CybersecurityLearningPlatform/backend/**/archive/",
]

RAW_SECRET_PATTERNS = [
    ("NVIDIA_API_KEY", re.compile(r"nvapi-[A-Za-z0-9_-]{20,}")),
    ("GROQ_API_KEY", re.compile(r"gsk_[A-Za-z0-9_-]{20,}")),
    ("GOOGLE_API_KEY", re.compile(r"AIza[A-Za-z0-9_-]{20,}")),
    ("OPENAI_API_KEY", re.compile(r"sk-(?:proj-|live-)?[A-Za-z0-9_-]{20,}")),
]

ENV_ASSIGNMENT = re.compile(
    r"\b(OPENAI_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY|GROQ_API_KEY(?:_[0-9])?|"
    r"NVIDIA_API_KEY_[0-9]|NEO4J_PASSWORD)\s*=\s*(.+)"
)
LOCAL_ABSOLUTE_PATH = re.compile(r"\b[A-Za-z]:[\\/]")

FORBIDDEN_GIT_ADD_SUBSTRINGS = [
    ".env",
    "node_modules/",
    "graphify-out/",
    "graphify_detect_summary.json",
    ".graphifyignore",
    "backend/ETL_module/Chunks/",
    "/__pycache__/",
    "/archive/",
    "backend/ETL_module/03_validate_and_import_bak.py",
    "backend/ETL_module/03_validate_and_import_test.py",
]


def is_placeholder(value: str) -> bool:
    value = value.strip().strip("\"'")
    lower = value.lower()
    if not value:
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    return lower in {
        "your_api_key_here",
        "your-key-here",
        "replace_me",
        "changeme",
        "placeholder",
        "example",
        "none",
        "null",
    }


def is_text_candidate(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or ".env" in path.name


def iter_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.name not in SKIP_NAMES
        and not any(part in SKIP_PARTS for part in path.parts)
    ]


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def check_required_paths(errors: list[str], warnings: list[str]) -> None:
    for item in REQUIRED_PATHS:
        if not (ROOT / item).exists():
            errors.append(f"MISSING_REQUIRED_PATH {item}")
    for item in MUST_NOT_EXIST:
        if (ROOT / item).exists():
            errors.append(f"PRIVATE_FILE_PRESENT {item}")
    for item in LOCAL_ONLY_ALLOWED:
        if (ROOT / item).exists():
            warnings.append(f"LOCAL_ONLY_PRESENT_BUT_IGNORED {item}")


def check_gitignore(errors: list[str]) -> None:
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        errors.append("MISSING_ROOT_GITIGNORE .gitignore")
        return
    text = gitignore.read_text(encoding="utf-8")
    for pattern in REQUIRED_GITIGNORE_PATTERNS:
        if pattern not in text:
            errors.append(f"MISSING_GITIGNORE_PATTERN {pattern}")


def check_sizes(files: list[Path], errors: list[str]) -> None:
    for path in files:
        size = path.stat().st_size
        if size >= MAX_GITHUB_FILE_BYTES:
            errors.append(f"FILE_OVER_100MB {rel(path)} {size}")


def check_text(files: list[Path], errors: list[str]) -> None:
    for path in files:
        if not is_text_candidate(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pattern in RAW_SECRET_PATTERNS:
                if pattern.search(line):
                    errors.append(f"SECRET_LIKE_VALUE {rel(path)}:{line_no} {label}")
            match = ENV_ASSIGNMENT.search(line)
            if match and "getenv(" not in match.group(2) and not is_placeholder(match.group(2)):
                errors.append(f"NON_PLACEHOLDER_SECRET_ENV {rel(path)}:{line_no} {match.group(1)}")
            if LOCAL_ABSOLUTE_PATH.search(line):
                errors.append(f"LOCAL_ABSOLUTE_PATH {rel(path)}:{line_no}")


def check_git_dry_run(errors: list[str], warnings: list[str]) -> None:
    if not (ROOT / ".git").exists():
        warnings.append("GIT_DRY_RUN_SKIPPED repository is not initialized")
        return
    result = subprocess.run(
        ["git", "-C", str(ROOT), "add", "-n", "."],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        errors.append(f"GIT_DRY_RUN_FAILED exit={result.returncode}")
        return
    lines = [line for line in output.splitlines() if line.strip()]
    print(f"git_add_dry_run_lines={len(lines)}")
    for line in lines:
        normalized = line.replace("\\", "/")
        for forbidden in FORBIDDEN_GIT_ADD_SUBSTRINGS:
            if forbidden in normalized and ".env.example" not in normalized:
                errors.append(f"GIT_DRY_RUN_FORBIDDEN {normalized}")
                break


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    files = iter_files()

    check_required_paths(errors, warnings)
    check_gitignore(errors)
    check_sizes(files, errors)
    check_text(files, errors)
    check_git_dry_run(errors, warnings)

    print(f"repo_root={ROOT}")
    print(f"checked_files={len(files)}")
    print(f"warnings={len(warnings)}")
    for warning in warnings:
        print(f"WARNING {warning}")

    if errors:
        print(f"errors={len(errors)}")
        for error in errors:
            print(f"ERROR {error}")
        print("FAIL")
        return 1

    print("errors=0")
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
