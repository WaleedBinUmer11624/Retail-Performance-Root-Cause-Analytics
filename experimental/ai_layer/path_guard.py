"""Central path policy for all Phase 11 artifact access."""
from __future__ import annotations

import os
from pathlib import Path


class PathDeniedError(PermissionError):
    """Raised when an artifact path is outside the allowed project boundary."""


_DENIED_EXACT = {
    "_hidden_scenario.yaml",
    "config_hidden_scenario.yaml",
}
_DENIED_PREFIXES = (
    "_scenario_answer_key",
    "_planted_issues_log",
)
_DENIED_DIRECTORIES = {"evaluation"}


def _is_denied_name(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parts = [part.casefold() for part in normalized.split("/") if part]
    return (
        "calibration" in normalized.casefold()
        or any(part in _DENIED_DIRECTORIES for part in parts)
        or any(part in _DENIED_EXACT for part in parts)
        or any(part.startswith(_DENIED_PREFIXES) for part in parts)
    )


def guard_path(project_root: str | os.PathLike[str], candidate: str | os.PathLike[str]) -> Path:
    """Resolve a project path and reject forbidden names and escapes before file access."""
    try:
        raw = os.fspath(candidate)
    except TypeError as error:
        raise PathDeniedError("Artifact path is not permitted") from error
    if not raw or _is_denied_name(raw):
        raise PathDeniedError("Artifact path is denied by policy")

    root = Path(project_root).resolve()
    path = Path(raw)
    resolved = (path if path.is_absolute() else root / path).resolve(strict=False)
    if _is_denied_name(resolved.as_posix()):
        raise PathDeniedError("Artifact path is denied by policy")
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise PathDeniedError("Artifact path is outside the project root") from error
    return resolved


def guarded_files(project_root: str | os.PathLike[str], candidates: list[str | os.PathLike[str]]) -> list[Path]:
    """Validate a complete input list before a resolver or retriever reads any file."""
    root = Path(project_root).resolve()
    return [guard_path(root, candidate) for candidate in candidates]