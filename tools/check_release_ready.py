from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if __name__ == "__main__":
    # Importing the colocated policy helper must not make a clean release dirty.
    sys.dont_write_bytecode = True

try:
    from tools.build_clean_release import _allowlisted, _forbidden_reason
except ModuleNotFoundError:  # Direct execution: python tools/check_release_ready.py
    from build_clean_release import _allowlisted, _forbidden_reason


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
TEXT_SCAN_MAX_BYTES = 2 * 1024 * 1024
MAX_RELEASE_FILE_BYTES = 25 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024

REQUIRED_PATHS = {
    ".gitignore",
    "DATA_MANIFEST.md",
    "LICENSE",
    "README.md",
    "Prompt/README.md",
    "本體論",
    "CybersecurityLearningPlatform/backend/.env.example",
    "CybersecurityLearningPlatform/backend/ETL_module/Validated",
    "CybersecurityLearningPlatform/backend/exp_1",
    "CybersecurityLearningPlatform/backend/exp_2",
    "CybersecurityLearningPlatform/backend/exp_3",
    "CybersecurityLearningPlatform/frontend/src",
}
REQUIRED_GITIGNORE_PATTERNS = {
    ".env",
    "node_modules/",
    "CybersecurityLearningPlatform/backend/ETL_module/Chunks/",
    "CybersecurityLearningPlatform/graphify-out/",
    "CybersecurityLearningPlatform/backend/exp_1/MatchGPT/phase1_backups/",
    "CybersecurityLearningPlatform/backend/exp_3/cache/",
    "CybersecurityLearningPlatform/backend/exp_2/phase2/_migration_output/",
}
TEXT_SUFFIXES = {
    ".cjs",
    ".css",
    ".csv",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_BYTES = {
    "NVIDIA_API_KEY": re.compile(rb"nvapi-[A-Za-z0-9_-]{20,}"),
    "GROQ_API_KEY": re.compile(rb"gsk_[A-Za-z0-9_-]{20,}"),
    "GOOGLE_API_KEY": re.compile(rb"AIza[A-Za-z0-9_-]{20,}"),
    "OPENAI_API_KEY": re.compile(rb"sk-(?:proj-|live-)?[A-Za-z0-9_-]{20,}"),
}
ENV_ASSIGNMENT = re.compile(
    r"\b(OPENAI_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY(?:S)?|GROQ_API_KEY(?:_[0-9]+)?|"
    r"NVIDIA_API_KEY(?:_[0-9]+)?|NEO4J_PASSWORD)\s*=\s*(.+)"
)
LOCAL_ABSOLUTE_PATH = re.compile(r"\b[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class ReleaseCheckResult:
    errors: list[str]
    warnings: list[str]
    checked_files: int
    checked_bytes: int


def _placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized in {"changeme", "example", "none", "null", "placeholder", "replace_me"}
        or (normalized.startswith("<") and normalized.endswith(">"))
        or normalized.startswith("your_")
        or normalized.startswith("your-")
    )


def _data_evidence_path(relative: Path) -> bool:
    normalized = relative.as_posix()
    return relative.suffix.lower() in {".csv", ".json", ".tsv"} and any(
        marker in normalized
        for marker in (
            "/ETL_module/RawTriples/",
            "/ETL_module/Rejected/",
            "/ETL_module/Validated/",
            "/exp_1/MatchGPT/phase1_results/",
            "/exp_2/phase2/",
            "/exp_3/data/",
        )
    )


class ReleaseChecker:
    def __init__(self, root: Path, text_scan_max_bytes: int = TEXT_SCAN_MAX_BYTES) -> None:
        self.root = root.resolve()
        self.text_scan_max_bytes = text_scan_max_bytes

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return [path for path in self.root.rglob("*") if path.is_file()]

    def _check_required(self, errors: list[str]) -> None:
        for relative in sorted(REQUIRED_PATHS):
            if not (self.root / relative).exists():
                errors.append(f"MISSING_REQUIRED_PATH {relative}")

    def _check_gitignore(self, errors: list[str]) -> None:
        path = self.root / ".gitignore"
        if not path.is_file():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in sorted(REQUIRED_GITIGNORE_PATTERNS):
            if pattern not in text:
                errors.append(f"MISSING_GITIGNORE_PATTERN {pattern}")

    @staticmethod
    def _scan_secret_bytes(path: Path, relative: Path, errors: list[str]) -> None:
        overlap = 128
        tail = b""
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(READ_CHUNK_BYTES):
                    data = tail + chunk
                    for label, pattern in SECRET_BYTES.items():
                        if pattern.search(data):
                            errors.append(f"SECRET_LIKE_VALUE {relative.as_posix()} {label}")
                    tail = data[-overlap:]
        except OSError as exc:
            errors.append(f"READ_FAILED {relative.as_posix()} {type(exc).__name__}")

    def _check_text(self, path: Path, relative: Path, errors: list[str], warnings: list[str]) -> None:
        if path.suffix.lower() not in TEXT_SUFFIXES and ".env" not in path.name:
            return
        size = path.stat().st_size
        if size > self.text_scan_max_bytes:
            warnings.append(f"TEXT_SCAN_SKIPPED_SIZE {relative.as_posix()} {size}")
            return
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            warnings.append(f"TEXT_SCAN_SKIPPED_ENCODING {relative.as_posix()}")
            return
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            match = ENV_ASSIGNMENT.search(line)
            if match and "getenv(" not in match.group(2) and not _placeholder(match.group(2)):
                errors.append(f"NON_PLACEHOLDER_SECRET_ENV {relative.as_posix()}:{line_no} {match.group(1)}")
            if LOCAL_ABSOLUTE_PATH.search(line) and not _data_evidence_path(relative):
                errors.append(f"LOCAL_ABSOLUTE_PATH {relative.as_posix()}:{line_no}")

    def _check_git_dry_run(self, errors: list[str], warnings: list[str]) -> None:
        if not (self.root / ".git").exists():
            warnings.append("GIT_DRY_RUN_SKIPPED no_repository")
            return
        result = subprocess.run(
            ["git", "-C", str(self.root), "add", "-n", "."],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            errors.append(f"GIT_DRY_RUN_FAILED exit={result.returncode}")
        else:
            lines = [line for line in ((result.stdout or "") + (result.stderr or "")).splitlines() if line.strip()]
            warnings.append(f"GIT_DRY_RUN_LINES {len(lines)}")

    def run(self, check_git: bool = False) -> ReleaseCheckResult:
        errors: list[str] = []
        warnings: list[str] = []
        self._check_required(errors)
        self._check_gitignore(errors)
        files = self._files()
        checked_bytes = 0
        for path in files:
            relative = path.relative_to(self.root)
            checked_bytes += path.stat().st_size
            reason = _forbidden_reason(relative)
            if reason:
                errors.append(f"FORBIDDEN_PATH {relative.as_posix()} reason={reason}")
            if not _allowlisted(relative) and relative.name != "RELEASE_BUILD_MANIFEST.json":
                errors.append(f"NOT_ALLOWLISTED {relative.as_posix()}")
            size = path.stat().st_size
            if size > MAX_RELEASE_FILE_BYTES:
                errors.append(f"FILE_OVER_LIMIT {relative.as_posix()} {size}")
            self._scan_secret_bytes(path, relative, errors)
            self._check_text(path, relative, errors, warnings)
        if check_git:
            self._check_git_dry_run(errors, warnings)
        return ReleaseCheckResult(errors, warnings, len(files), checked_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a clean public handoff release.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--git-dry-run", action="store_true", help="Opt in to git add -n when the target is a repository.")
    args = parser.parse_args()
    checker = ReleaseChecker(args.root)
    result = checker.run(check_git=args.git_dry_run)
    print(f"release_root={checker.root}")
    print(f"checked_files={result.checked_files}")
    print(f"checked_bytes={result.checked_bytes}")
    print(f"warnings={len(result.warnings)}")
    for warning in result.warnings:
        print(f"WARNING {warning}")
    if result.errors:
        print(f"errors={len(result.errors)}")
        for error in result.errors:
            print(f"ERROR {error}")
        print("FAIL")
        return 1
    print("errors=0")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
