"""Audit log: every tool call is appended to logs/tool_calls.jsonl (outside the workspace).

File contents are never logged, only their length, so the log is safe to share as evidence.
"""
import functools
import inspect
import json
import threading
import time
from datetime import datetime, timezone

from config import LOG_DIR

LOG_FILE = LOG_DIR / "tool_calls.jsonl"
_lock = threading.Lock()
_SENSITIVE = {"content", "old_str", "new_str"}


def _summarize(name: str, value):
    if name in _SENSITIVE and isinstance(value, str):
        return f"<{len(value)} chars>"
    if isinstance(value, str) and len(value) > 80:
        return value[:77] + "..."
    return value


def _write(record: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _lock, LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break a tool call


def audited(fn):
    """Decorator: log tool name, summarized arguments, outcome, duration and output size."""
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        ok, error, result = True, None, None
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as exc:
            ok, error = False, str(exc)[:300]
            raise
        finally:
            try:
                bound = sig.bind_partial(*args, **kwargs).arguments
                size = len(result) if isinstance(result, (str, list)) else None
                _write({
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "tool": fn.__name__,
                    "args": {k: _summarize(k, v) for k, v in bound.items()},
                    "ok": ok,
                    "error": error,
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                    "out_size": size,
                })
            except Exception:
                pass

    return wrapper
