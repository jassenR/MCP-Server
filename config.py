"""All configuration comes from environment variables, optionally loaded from a local .env file.

Secrets (MCP_SECRET) live only in the environment / .env, never in source code.
"""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader. Real environment variables win over the file."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

# Only folder the tools can touch
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", str(BASE_DIR / "workspace"))).expanduser().resolve()
# Where the audit log (tool_calls.jsonl) is written; kept outside the workspace on purpose
LOG_DIR = Path(os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))).expanduser().resolve()

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8000"))
MAX_BYTES = int(os.environ.get("MAX_BYTES", "1000000"))  # cap per read/write (~1 MB)

# Public hostname of the tunnel (no https://, no path), allowed through the Host-header check
TUNNEL_HOST = os.environ.get("TUNNEL_HOST", "").strip()
# Secret path segment: the endpoint is served at /<MCP_SECRET>/mcp, anything else is 404
MCP_SECRET = os.environ.get("MCP_SECRET", "").strip()
# "writer" exposes all tools; "reader" exposes read-only tools only
ROLE = os.environ.get("MCP_ROLE", "writer").strip().lower()


def validate() -> None:
    """Fail fast on unsafe or invalid configuration."""
    if ROLE not in ("writer", "reader"):
        raise SystemExit("MCP_ROLE must be 'writer' or 'reader'.")
    if MCP_SECRET and not re.fullmatch(r"[A-Za-z0-9_-]{16,}", MCP_SECRET):
        raise SystemExit("MCP_SECRET must be 16+ characters of letters, digits, '-' or '_'.")
    if TUNNEL_HOST and not MCP_SECRET:
        raise SystemExit(
            "Refusing to start: TUNNEL_HOST is set (public endpoint) but MCP_SECRET is not. "
            "Add MCP_SECRET to .env (start.bat does this for you)."
        )
