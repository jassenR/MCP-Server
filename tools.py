"""Tool definitions.

Every tool is single-purpose, has a strict input schema (pydantic constraints), and raises
ValueError with an actionable message on failure; the MCP SDK returns that as an isError result
so the agent can read the problem and recover.
"""
import hashlib
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from pydantic import Field

from audit import audited
from config import MAX_BYTES
from sandbox import WORKSPACE_ROOT, ensure_writable, rel, safe_path

SKIP_DIRS = {".git", ".trash"}
# The handoff files can never be deleted by an agent
PROTECTED_FILES = {"project_state.md", "plan_log.md", "checkpoints.md", "decisions.md"}
MAX_TREE_ENTRIES = 200

PathArg = Annotated[str, Field(min_length=1, max_length=300,
                               description="Path relative to the workspace root, e.g. 'notes/a.md'.")]
VersionArg = Annotated[Optional[str], Field(max_length=64,
                       description="Version string from read_file's header. If given, the edit only "
                                   "applies when the file is unchanged since you read it.")]


def _version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _check_version(p: Path, if_version: Optional[str]) -> None:
    if if_version is None:
        return
    if not p.is_file():
        raise ValueError("if_version was given but the file does not exist; omit if_version to create it.")
    current = _version(p.read_bytes())
    if current != if_version:
        raise ValueError(
            f"Version mismatch: the file changed since you read it (current version {current}, "
            f"you sent {if_version}). Re-read it with read_file, then redo your edit."
        )


def _atomic_write(p: Path, data: bytes) -> None:
    """Write to a temp file then rename, so a crash never leaves a half-written file."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)


def _is_skipped(name: str) -> bool:
    return name.lower() in SKIP_DIRS


# ---------------------------------------------------------------- read-only tools

@audited
def list_files(path: PathArg = ".") -> list[str]:
    """List the files and folders directly inside one workspace directory. Folders end with '/'.
    Use tree instead for a deeper overview of the structure."""
    p = safe_path(path)
    if not p.is_dir():
        raise ValueError(f"Not a directory: {path}")
    return sorted(rel(c) + ("/" if c.is_dir() else "") for c in p.iterdir() if not _is_skipped(c.name))


@audited
def tree(path: PathArg = ".",
         max_depth: Annotated[int, Field(ge=1, le=4, description="How many folder levels to show.")] = 2) -> str:
    """Compact map of the folder structure with file sizes (a repo map). Use this first to orient
    yourself in an unfamiliar workspace instead of listing folders one by one."""
    root = safe_path(path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {path}")
    lines: list[str] = []

    def walk(directory: Path, depth: int, indent: str) -> None:
        entries = sorted((c for c in directory.iterdir() if not _is_skipped(c.name) and not c.is_symlink()),
                         key=lambda c: (not c.is_dir(), c.name.lower()))
        for c in entries:
            if len(lines) >= MAX_TREE_ENTRIES:
                return
            if c.is_dir():
                lines.append(f"{indent}{c.name}/")
                if depth < max_depth:
                    walk(c, depth + 1, indent + "  ")
            else:
                lines.append(f"{indent}{c.name} ({c.stat().st_size} B)")

    walk(root, 1, "")
    if len(lines) >= MAX_TREE_ENTRIES:
        lines.append(f"... truncated at {MAX_TREE_ENTRIES} entries; narrow with path or lower max_depth")
    return "\n".join(lines) or "(empty)"


@audited
def read_file(path: PathArg,
              start_line: Annotated[int, Field(ge=1, description="First line to return (1-based).")] = 1,
              max_lines: Annotated[int, Field(ge=1, le=2000, description="Maximum lines to return.")] = 400) -> str:
    """Read a UTF-8 text file in chunks. The first line of the result is a header with the line range
    and the file's version (pass it as if_version when editing); it is not part of the file, so do not
    copy it into writes. If the file is longer than max_lines the result says where to continue.
    For large files, use search to find the right lines instead of reading everything."""
    p = safe_path(path)
    if not p.is_file():
        raise ValueError(f"Not a file: {path}")
    if p.stat().st_size > MAX_BYTES:
        raise ValueError("File too large to read.")
    data = p.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Not a UTF-8 text file.")
    lines = text.splitlines()
    total = len(lines)
    version = _version(data)
    if total == 0:
        return f"[{rel(p)} | version {version} | empty file]"
    if start_line > total:
        raise ValueError(f"start_line {start_line} is past the end of the file ({total} lines).")
    end = min(start_line + max_lines - 1, total)
    body = "\n".join(lines[start_line - 1:end])
    header = f"[{rel(p)} | version {version} | lines {start_line}-{end} of {total}]"
    footer = f"\n[more lines remain: call again with start_line={end + 1}]" if end < total else ""
    return f"{header}\n{body}{footer}"


@audited
def search(query: Annotated[str, Field(min_length=1, max_length=200, description="Text to look for (case-insensitive).")],
           path: PathArg = ".",
           max_results: Annotated[int, Field(ge=1, le=100, description="Stop after this many matches.")] = 50) -> list[str]:
    """Case-insensitive text search across workspace files, like grep. Returns 'path:line: text' matches.
    Use it to locate the right file or lines before reading. Skips binary files and the .git/.trash folders."""
    root = safe_path(path)
    if not root.exists():
        raise ValueError(f"Not found: {path}")
    needle = query.lower()
    matches: list[str] = []

    def candidates():
        if root.is_file():
            yield root
            return
        for dirpath, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if not _is_skipped(d)]
            for name in names:
                yield Path(dirpath) / name

    for f in candidates():
        try:
            real = f.resolve()
            if not real.is_relative_to(WORKSPACE_ROOT) or real.stat().st_size > MAX_BYTES:
                continue  # symlink leading outside, or too big
            text = real.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary, unreadable, or vanished
        for n, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                matches.append(f"{rel(real)}:{n}: {line.strip()[:200]}")
                if len(matches) >= max_results:
                    return matches
    return matches


def _git(*args: str) -> str:
    """Run a read-only git command inside the workspace (no shell, fixed arguments)."""
    if not (WORKSPACE_ROOT / ".git").exists():
        raise ValueError("Workspace is not a git repo. Run 'git init' inside the workspace folder.")
    try:
        out = subprocess.run(["git", *args], cwd=WORKSPACE_ROOT, capture_output=True,
                             text=True, timeout=10, check=False)
    except FileNotFoundError:
        raise ValueError("git is not installed on the server.")
    except subprocess.TimeoutExpired:
        raise ValueError("git command timed out.")
    if out.returncode != 0:
        raise ValueError(out.stderr.strip() or "git command failed.")
    return out.stdout.strip() or "(no output)"


@audited
def git_status() -> str:
    """Show changed and untracked files in the workspace git repo (short format). Read-only."""
    return _git("status", "--short", "--branch")


@audited
def git_log(max_entries: Annotated[int, Field(ge=1, le=50, description="Number of commits to show.")] = 10) -> str:
    """Show recent commits in the workspace git repo, one per line. Read-only."""
    return _git("log", f"-{max_entries}", "--oneline", "--decorate")


# ---------------------------------------------------------------- write tools

@audited
def write_file(path: PathArg,
               content: Annotated[str, Field(max_length=MAX_BYTES, description="Full new file content (UTF-8).")],
               if_version: VersionArg = None) -> str:
    """Create a file or overwrite it completely. Parent folders are created. When overwriting an existing
    file, pass if_version (from read_file) so you do not clobber changes another session made.
    To change just part of a file, prefer str_replace."""
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("Content too large to write.")
    p = safe_path(path)
    ensure_writable(p)
    if p.is_dir():
        raise ValueError(f"Is a directory: {path}")
    _check_version(p, if_version)
    _atomic_write(p, data)
    return f"Wrote {rel(p)} ({len(data)} bytes) | version {_version(data)}"


@audited
def str_replace(path: PathArg,
                old_str: Annotated[str, Field(min_length=1, max_length=100_000, description="Exact text to replace; must appear exactly once.")],
                new_str: Annotated[str, Field(max_length=100_000, description="Replacement text (may be empty to delete old_str).")],
                if_version: VersionArg = None) -> str:
    """Replace one exact occurrence of old_str in a file. old_str must appear exactly once or the call
    fails and nothing changes, so widen the match with surrounding text. Read the file first."""
    p = safe_path(path)
    ensure_writable(p)
    if not p.is_file():
        raise ValueError(f"Not a file: {path}")
    if p.stat().st_size > MAX_BYTES:
        raise ValueError("File too large to edit.")
    _check_version(p, if_version)
    text = p.read_text(encoding="utf-8")
    count = text.count(old_str)
    if count == 0:
        raise ValueError("old_str not found; nothing changed. Re-read the file and copy the text exactly.")
    if count > 1:
        raise ValueError(f"old_str matches {count} places; add more surrounding text to make it unique.")
    data = text.replace(old_str, new_str, 1).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("Result would be too large.")
    _atomic_write(p, data)
    return f"Edited {rel(p)} | version {_version(data)}"


@audited
def delete(path: PathArg,
           confirm: Annotated[bool, Field(description="Must be true to actually delete.")] = False) -> str:
    """Delete a file or folder by moving it into .trash/ inside the workspace (recoverable).
    Requires confirm=true. The workspace root, .git and the four handoff files cannot be deleted."""
    p = safe_path(path)
    if p == WORKSPACE_ROOT:
        raise ValueError("Refusing to delete the workspace root.")
    ensure_writable(p)
    if p.parent == WORKSPACE_ROOT and p.name.lower() in PROTECTED_FILES:
        raise ValueError(f"{p.name} is a handoff file and cannot be deleted. Edit it instead.")
    if not p.exists():
        raise ValueError(f"Not found: {path}")
    if not confirm:
        raise ValueError(f"Not deleted. Deleting '{rel(p)}' moves it to .trash/ (recoverable). "
                         "Call delete again with confirm=true if that is intended.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = WORKSPACE_ROOT / ".trash" / stamp / rel(p)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dest))
    return f"Moved {rel(p)} to {rel(dest)}"


READ_TOOLS = [list_files, tree, read_file, search, git_status, git_log]
WRITE_TOOLS = [write_file, str_replace, delete]


def register(mcp, role: str = "writer") -> list[str]:
    """Register tools on the FastMCP app. A 'reader' role gets read-only tools only."""
    chosen = READ_TOOLS if role == "reader" else READ_TOOLS + WRITE_TOOLS
    for fn in chosen:
        mcp.tool()(fn)
    return [fn.__name__ for fn in chosen]
