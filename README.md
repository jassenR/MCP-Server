# MCP File Server

A sandboxed file-server connector built on the [Model Context Protocol](https://modelcontextprotocol.io).
An AI agent (Claude, or any MCP client) connects over HTTPS and can map, read, search, write, edit and
delete files inside one workspace folder. A handoff protocol lets a later session pick up exactly where
an earlier one stopped.

Built for the CS 3A / CS 3B Week 6 MCP midterm (Part 1: Build Your Own).

```
MCP client --HTTPS--> Cloudflare tunnel --> http://127.0.0.1:8000/<secret>/mcp --> server.py --> workspace/
```

## Features

- **Sandboxed workspace.** Every path is resolved against `WORKSPACE_ROOT`; `..`, absolute paths, null
  bytes and symlinks that point outside are rejected.
- **Secret endpoint.** The server only answers at `/<MCP_SECRET>/mcp`; every other path is 404.
- **9 single-purpose tools** with strict input schemas (pydantic constraints):

  | Tool | What it does |
  |---|---|
  | `list_files(path)` | List one directory (folders end with `/`) |
  | `tree(path, max_depth)` | Compact repo map with file sizes (depth 1-4, 200 entries max) |
  | `read_file(path, start_line, max_lines)` | Read in chunks (up to 2000 lines); header shows line range and a **version** |
  | `search(query, path, max_results)` | Case-insensitive grep across files (1-100 matches) |
  | `write_file(path, content, if_version)` | Create or overwrite atomically; optional version lock |
  | `str_replace(path, old_str, new_str, if_version)` | Replace one exact match; fails unless it matches exactly once |
  | `delete(path, confirm)` | Soft delete into `.trash/`; needs `confirm=true`; handoff files protected |
  | `git_status()` | Short status of the workspace repo (read-only) |
  | `git_log(max_entries)` | Recent commits, max 50 (read-only) |

- **Guards against bad writes:** atomic writes (temp file then rename), 1 MB size caps, no writes into
  `.git/` or `.trash/`, optional `if_version` locking so two sessions cannot silently overwrite each other.
- **Audit log:** every call is appended to `logs/tool_calls.jsonl` (tool, arguments, ok/error, duration,
  output size). File contents are never logged, only their length.
- **Roles:** `MCP_ROLE=reader` registers only the 6 read-only tools.
- **Handoff protocol** (`PROJECT_STATE`, `PLAN_LOG`, `CHECKPOINTS`, `DECISIONS`) for multi-session work.

## Requirements

- Python 3.10+
- Node.js (for pm2 and the optional MCP Inspector)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
  (Windows: `winget install Cloudflare.cloudflared`)
- git

## Setup

1. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   On macOS/Linux use `.venv/bin/python`. Requirements pin `mcp<2` because MCP SDK 2.x renamed `FastMCP`.

2. Run the tests (they use a throwaway workspace):

   ```powershell
   .venv\Scripts\python.exe test_sandbox.py
   .venv\Scripts\python.exe test_tools.py
   ```

   Expected: `all sandbox tests passed` and `all tool tests passed`. The symlink check is skipped on
   Windows unless Developer Mode or admin rights allow creating symlinks.

3. Give the workspace its own git repo and ignore the trash folder:

   ```powershell
   cd workspace
   echo .trash/> .gitignore
   git init
   git add .
   git commit -m "initial handoff files"
   cd ..
   ```

4. Install pm2: `npm install -g pm2`

## Run

**One click (Windows):** double-click `start.bat`. On first run it creates a random `MCP_SECRET` in
`.env`. It then starts the tunnel, waits for the public address, starts the server, copies the connector
URL to your clipboard, and runs `check_endpoint.py` to prove the endpoint is protected.
Stop everything with `stop.bat`.

**Manually:**

```powershell
pm2 start ecosystem.config.js --only mcp-tunnel
pm2 logs mcp-tunnel --lines 30          # find https://<words>.trycloudflare.com
$env:TUNNEL_HOST="<words>.trycloudflare.com"
pm2 start ecosystem.config.js --only mcp-files
pm2 status
```

`MCP_SECRET` must already be in `.env` (copy `.env.example`). The server refuses to start with a public
`TUNNEL_HOST` and no secret.

**Local only (no tunnel):** `.venv\Scripts\python.exe server.py`, then use
`http://127.0.0.1:8000/<MCP_SECRET>/mcp` (or `/mcp` if no secret is set).

### Configuration

Settings come from environment variables or a local `.env` file (never committed).

| Variable | Default | Purpose |
|---|---|---|
| `MCP_SECRET` | none | Secret path segment (16+ chars). Required when `TUNNEL_HOST` is set |
| `TUNNEL_HOST` | empty | Public hostname (no `https://`, no path) allowed through the Host check |
| `WORKSPACE_ROOT` | `./workspace` | The only folder the tools can touch |
| `MCP_ROLE` | `writer` | `reader` exposes read-only tools only |
| `LOG_DIR` | `./logs` | Where `tool_calls.jsonl` is written (outside the workspace) |
| `PORT` | `8000` | Local port the tunnel points at |
| `MAX_BYTES` | `1000000` | Per-read/write size cap |

## Connect a client

**Claude (claude.ai):** Customize > Connectors > Add custom connector. Name it `workspace-files`, paste
`https://<tunnel-host>/<MCP_SECRET>/mcp`, then enable it in a chat from the "+" menu. Tool permissions can
be set per tool (allow / needs approval / block); keep `write_file`, `str_replace` and `delete` on
approval.

**MCP Inspector (no LLM needed):**

```powershell
npx @modelcontextprotocol/inspector
```

Choose Streamable HTTP, enter the URL, connect, and call tools from the Tools tab.

Quick-tunnel hostnames change every time the tunnel starts. After a restart, run `start.bat` again and
update the connector URL (the secret stays the same).

## Handoff protocol

Agents have no memory between chats, so the workspace carries it. Four files live in `workspace/`:

| File | Role | Edit style |
|---|---|---|
| `PROJECT_STATE.md` | Current goal, status, done / in progress / next steps, blockers | Rewritten each session |
| `PLAN_LOG.md` | What each session planned, did and left unfinished | Append-only |
| `CHECKPOINTS.md` | Milestones with files touched and the exact action to resume from | Append-only |
| `DECISIONS.md` | Non-obvious choices with alternatives and reasons | Append-only |

Rules (also written at the top of `PROJECT_STATE.md`): read all four at session start; update
`PROJECT_STATE.md` before ending; append to the log files, never rewrite history. The server prevents
these four files from being deleted.

**Efficient agent workflow:** `tree` to orient, `search` to find the right lines, `read_file` with a line
range instead of whole files, `str_replace` with `if_version` for small edits, and `git_status` /
`git_log` to see what changed between sessions.

**Version locking:** `read_file` shows `version <hash>` in its header. Pass that as `if_version` when
editing. If another session changed the file in between, the edit fails with a clear message instead of
overwriting.

### Demo

1. **Session 1:** tell the agent to read the handoff files, do the first part of a multi-step task, then
   update all four files and stop.
2. **Session 2:** open a new chat with the connector enabled and say "resume from the handoff files". It
   should continue from the recorded next step with no other context.

Keep both chats' tool-call transcripts, `workspace/PLAN_LOG.md`, `workspace/CHECKPOINTS.md` and
`logs/tool_calls.jsonl` as evidence.

## Testing

| Command | Checks |
|---|---|
| `python test_sandbox.py` | Path traversal, absolute paths, sibling-prefix trick, null bytes, symlinks |
| `python test_tools.py` | Chunked reads, version locking, delete gating and trash, protected files, internal folders, audit log, roles, strict schemas, `isError` on bad input |
| `python check_endpoint.py https://<host>` | No secret and wrong secret return 404; the right secret returns 200 |
| MCP Inspector | Interactive check of every tool, including error cases |

## Stack and design choices

| Layer | Choice | Why |
|---|---|---|
| Runtime / SDK | Python with the official MCP SDK (`FastMCP`) | Fast to build and test; type hints become the tool schemas |
| Validation | pydantic `Field` constraints (min/max length, ranges) | Bad input is rejected before a tool runs and returns as `isError` |
| Transport | Streamable HTTP | Works through a tunnel, many clients can connect |
| Exposure | Cloudflare quick tunnel | Free, no account needed, HTTPS included |
| Process manager | pm2 | Cross-platform, restarts crashes, simple config |
| Auth | Secret URL path | Works with any client that only takes a URL (Claude custom connectors) |
| Version control | git in `workspace/` | `git_status` / `git_log` show what changed between sessions |

Code is split by responsibility: `config.py` (environment), `sandbox.py` (path safety), `audit.py` (call
log), `tools.py` (tools), `server.py` (wiring and transport). No secrets are in source code.

## Security model and limitations

| Threat | Mitigation |
|---|---|
| Path traversal / symlink escape | `safe_path()`: `resolve()` then `is_relative_to(WORKSPACE_ROOT)`; search re-checks resolved paths; tree skips symlinks |
| Anonymous use of the public URL | Endpoint only exists at `/<MCP_SECRET>/mcp`; server refuses to start publicly without a secret |
| Hostile Host headers | Allowlist of localhost and the tunnel host; others get HTTP 421 |
| Accidental data loss | `delete` needs `confirm=true`, moves to `.trash/`, protects handoff files and `.git`; atomic writes; version locking |
| Command injection via git | Read-only, no shell, fixed arguments |
| Oversized input | 1 MB caps, schema length limits |
| No visibility | Audit log of every call |

Known limitations:

- **The secret URL is a bearer credential.** Anyone who has it has full access to the workspace. Treat it
  like a password, never post it, and keep the workspace free of other secrets. To rotate, delete the
  `MCP_SECRET` line from `.env` and run `start.bat`. The secret appears in the tunnel provider's request
  path, which is a tradeoff compared with header-based tokens or OAuth.
- No per-user identity and no rate limiting; the audit log does not say which agent made a call.
- `MCP_ROLE=reader` is per server instance, not per connection.
- Quick tunnels have no uptime guarantee and a new hostname on every start. A named tunnel (needs a
  domain) gives a stable URL.
- Text files only (UTF-8), 1 MB per read or write.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Invalid Host header` | `TUNNEL_HOST` missing or stale; run `start.bat` again |
| 404 on the connector URL | The secret in the URL does not match `.env`; use the URL `start.bat` prints |
| `DNS_PROBE_FINISHED_NXDOMAIN` | Tunnel stopped or hostname changed; run `start.bat` |
| `Not Acceptable: Client must accept text/event-stream` in a browser | Normal; the server is up |
| `Refusing to start: TUNNEL_HOST is set ... MCP_SECRET is not` | Add `MCP_SECRET` to `.env` (or use `start.bat`) |
| PowerShell blocks `activate` | Skip activation and call `.venv\Scripts\python.exe` directly |
| `pm2` says `ecosystem.config.js not found` | Run it from the project folder, not `workspace/` |
| `git_status` says not a git repo | Run `git init` inside `workspace/` |
| pm2 cannot find `cloudflared` | Put its full path in the `script` line of `ecosystem.config.js` |

## Project layout

```
server.py             wiring: FastMCP app, secret path, Host allowlist, transport
tools.py              the 9 tools, schemas, role registration
sandbox.py            WORKSPACE_ROOT sandbox (safe_path, protected folders)
audit.py              JSONL audit log decorator
config.py             environment / .env settings and startup validation
test_sandbox.py       path-escape tests
test_tools.py         tool, guard, log and role tests
check_endpoint.py     public-endpoint secret check
ecosystem.config.js   pm2 config (server + tunnel)
start.ps1 / start.bat one-click startup (Windows); stop.bat stops both
.env.example          configuration template (copy to .env; never commit .env)
DEPLOY.md             deployment details (HTTP, tunnel, pm2, systemd)
requirements.txt      pinned dependencies
workspace/            sandboxed files the agent works in (its own git repo, gitignored here)
logs/                 audit log (gitignored)
```
