from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parent


class PromptNotFoundError(FileNotFoundError):
    """Raised when a prompt file is missing or the requested path is invalid."""


def prompt_path(name: str | Path) -> Path:
    rel_path = Path(name)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise PromptNotFoundError(f"Invalid prompt path: {name}")

    path = (PROMPTS_ROOT / rel_path).resolve()
    if path != PROMPTS_ROOT and PROMPTS_ROOT not in path.parents:
        raise PromptNotFoundError(f"Invalid prompt path: {name}")
    return path


@lru_cache(maxsize=None)
def load_prompt(name: str | Path) -> str:
    path = prompt_path(name)
    if not path.is_file():
        raise PromptNotFoundError(f"Prompt not found: {name} ({path})")
    return path.read_text(encoding="utf-8")
