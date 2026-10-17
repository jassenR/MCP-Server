"""Workspace sandbox: every path the agent supplies must go through safe_path()."""
from pathlib import Path

from config import WORKSPACE_ROOT

WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# Folders managed by the server; agents may not write to or delete them
INTERNAL_DIRS = {".git", ".trash"}


class SandboxError(ValueError):
    """Raised when a path is invalid or tries to leave the workspace."""


def safe_path(user_path: str) -> Path:
    """Resolve user_path against WORKSPACE_ROOT and reject anything that escapes it.

    resolve() collapses '..' and follows symlinks, so '../x', absolute paths,
    and symlinks pointing outside all end up outside the root and are rejected.
    is_relative_to() compares whole path parts, so a sibling folder like
    'workspace-evil' can't slip past a plain string-prefix check.
    """
    if not isinstance(user_path, str) or not user_path.strip():
        raise SandboxError("Path must be a non-empty string.")
    if "\x00" in user_path:
        raise SandboxError("Invalid path.")

    candidate = (WORKSPACE_ROOT / user_path).resolve()
    if not candidate.is_relative_to(WORKSPACE_ROOT):
        # Don't echo absolute paths back to the agent
        raise SandboxError("Path escapes the workspace root.")
    return candidate


def rel(path: Path) -> str:
    """Workspace-relative display path (never leaks the real location)."""
    return path.relative_to(WORKSPACE_ROOT).as_posix() or "."


def ensure_writable(path: Path) -> None:
    """Block writes/deletes inside git metadata and the trash folder (case-insensitive for Windows)."""
    parts = path.relative_to(WORKSPACE_ROOT).parts
    if parts and parts[0].lower() in INTERNAL_DIRS:
        raise SandboxError(f"'{parts[0]}/' is managed by the server and cannot be modified.")
