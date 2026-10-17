"""Run: python test_tools.py  -- exercises tool behavior, guards, audit log and roles in a throwaway workspace."""
import asyncio
import json
import os
import subprocess
import tempfile

os.environ["WORKSPACE_ROOT"] = tempfile.mkdtemp()
os.environ["LOG_DIR"] = tempfile.mkdtemp()

import mcp.types as types  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

import tools as t  # noqa: E402
from audit import LOG_FILE  # noqa: E402
from sandbox import WORKSPACE_ROOT  # noqa: E402


def fails(fn, *args, contains="", **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:  # SandboxError is a ValueError too
        assert contains.lower() in str(exc).lower(), f"expected {contains!r} in {exc!r}"
        return
    raise AssertionError(f"{fn.__name__}{args} should have failed")


# ---- write / read / chunking / versions
out = t.write_file("notes/a.md", "\n".join(f"line {i}" for i in range(1, 501)))
v1 = out.split("version ")[1]
r = t.read_file("notes/a.md")
assert r.splitlines()[0].startswith("[notes/a.md | version " + v1 + " | lines 1-400 of 500]"), r.splitlines()[0]
assert "start_line=401" in r
r2 = t.read_file("notes/a.md", start_line=401)
assert "lines 401-500 of 500" in r2 and "more lines remain" not in r2
fails(t.read_file, "notes/a.md", start_line=999, contains="past the end")
assert "empty file" in t.read_file(t.write_file("empty.txt", "") and "empty.txt")

# ---- version locking
v2 = t.str_replace("notes/a.md", "line 7\n", "LINE SEVEN\n", if_version=v1).split("version ")[1]
fails(t.write_file, "notes/a.md", "clobber", if_version=v1, contains="version mismatch")
fails(t.str_replace, "notes/a.md", "LINE SEVEN", "x", if_version=v1, contains="version mismatch")
t.write_file("notes/a.md", "fresh", if_version=v2)
fails(t.write_file, "new.txt", "x", if_version="abcdabcdabcd", contains="does not exist")

# ---- str_replace guards
t.write_file("dup.txt", "hello hello")
fails(t.str_replace, "dup.txt", "hello", "x", contains="2 places")
fails(t.str_replace, "dup.txt", "zzz", "x", contains="not found")

# ---- internal folders and symlink-free tree/search
fails(t.write_file, ".git/config", "x", contains="managed by the server")
fails(t.write_file, ".GIT/config", "x", contains="managed by the server")
fails(t.write_file, ".trash/x", "x", contains="managed by the server")
fails(t.write_file, "../x.txt", "x", contains="escapes")

# ---- delete: confirm gate, soft delete, protections
for name in ["PROJECT_STATE.md", "PLAN_LOG.md", "CHECKPOINTS.md", "DECISIONS.md"]:
    t.write_file(name, "# " + name)
    fails(t.delete, name, confirm=True, contains="handoff file")
fails(t.delete, "dup.txt", contains="confirm=true")
assert (WORKSPACE_ROOT / "dup.txt").exists()
msg = t.delete("dup.txt", confirm=True)
assert msg.startswith("Moved dup.txt to .trash/") and not (WORKSPACE_ROOT / "dup.txt").exists()
trashed = msg.split(" to ")[1]
assert (WORKSPACE_ROOT / trashed).read_text() == "hello hello"          # recoverable
fails(t.delete, ".", confirm=True, contains="workspace root")
fails(t.delete, ".git", confirm=True, contains="managed by the server")
fails(t.delete, "ghost.txt", confirm=True, contains="not found")

# ---- search / tree / list hide .trash and .git
assert t.search("hello") == []                       # only match is in .trash
assert any("fresh" in m for m in t.search("FRESH"))
assert len(t.search("line", max_results=1)) <= 1
tr = t.tree()
assert "notes/" in tr and ".trash" not in tr and "PROJECT_STATE.md" in tr
assert ".trash/" not in t.list_files()

# ---- git tools (read-only)
fails(t.git_status, contains="not a git repo")
subprocess.run(["git", "init", "-q"], cwd=WORKSPACE_ROOT, check=True)
subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=WORKSPACE_ROOT, check=True)
subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first"], cwd=WORKSPACE_ROOT, check=True)
assert "first" in t.git_log(3)
assert t.git_status().startswith("## ")

# ---- audit log: one line per call, contents never logged
lines = [json.loads(x) for x in LOG_FILE.read_text().splitlines()]
assert len(lines) > 30
assert all({"ts", "tool", "args", "ok", "ms"} <= set(x) for x in lines)
assert any(x["tool"] == "delete" and x["ok"] is False for x in lines)       # failures are logged
w = next(x for x in lines if x["tool"] == "write_file")
assert w["args"]["content"].startswith("<") and "line 1" not in json.dumps(w)  # length only, no contents

# ---- roles and strict schemas
reader, writer = FastMCP("r"), FastMCP("w")
assert set(t.register(reader, "reader")) == {"list_files", "tree", "read_file", "search", "git_status", "git_log"}
assert len(t.register(writer, "writer")) == 9
schema = next(x for x in writer._tool_manager.list_tools() if x.name == "read_file").parameters["properties"]
assert schema["max_lines"]["maximum"] == 2000 and schema["start_line"]["minimum"] == 1

# ---- bad input comes back as isError with a readable message, never a crash
async def call(name, args):
    h = writer._mcp_server.request_handlers[types.CallToolRequest]
    req = types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(name=name, arguments=args))
    return (await h(req)).root

res = asyncio.run(call("read_file", {"path": "../../etc/passwd"}))
assert res.isError and "escapes the workspace root" in res.content[0].text
res = asyncio.run(call("read_file", {"path": "notes/a.md", "max_lines": 99999}))
assert res.isError and "validation error" in res.content[0].text.lower()
res = asyncio.run(call("list_files", {}))
assert not res.isError

print("all tool tests passed")
