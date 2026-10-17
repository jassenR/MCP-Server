# Deploying the MCP file server

> **Note:** the server now has a secret endpoint. The connector URL is
> `https://<tunnel-host>/<MCP_SECRET>/mcp` (secret from `.env`; `start.bat` creates it, starts the
> tunnel and server for you, and prints the URL). Anywhere below that says `.../mcp` means
> `.../<MCP_SECRET>/mcp` once `MCP_SECRET` is set. See README.md for the full guide.


Goal: reachable over HTTPS at a public URL, and restarted automatically if it crashes.

```
MCP client  ->  https://<tunnel-host>/<secret>/mcp  ->  tunnel  ->  http://127.0.0.1:8000/mcp  ->  server.py
```

## 1. Serve over HTTP

`server.py` already runs the Streamable HTTP transport on port 8000.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt      # pins mcp<2 (v2 renamed FastMCP)
WORKSPACE_ROOT=./workspace python server.py
```

Windows PowerShell: `$env:WORKSPACE_ROOT="./workspace"; python server.py`

The MCP endpoint is `http://127.0.0.1:8000/mcp`. Test it without any LLM using MCP Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Choose transport "Streamable HTTP", enter the URL, connect, and call your tools.

## 2. Expose it with a tunnel

The tunnel gives your local port a public HTTPS URL. Hosted clients (Claude, ChatGPT)
connect from the cloud, so they cannot reach localhost.

**Cloudflare quick tunnel (no account needed):**

```bash
cloudflared tunnel --url http://localhost:8000
```

It prints a URL like `https://random-words.trycloudflare.com`. Your connector URL is that
URL plus `/mcp`. The hostname changes every time the tunnel restarts.

**ngrok (free account and authtoken needed):**

```bash
ngrok config add-authtoken <your-token>
ngrok http 8000
```

Use the printed `https://...` forwarding URL plus `/mcp`. Check ngrok's current free-tier
terms for whether you get a stable domain.

## 3. Keep it alive: pm2 (works on Windows, macOS, Linux)

```bash
npm install -g pm2
```

Use the `ecosystem.config.js` file in this folder (it picks the right Python path for Windows or Linux).
Because a quick tunnel's hostname changes on every start, start the tunnel first, then the server:

```powershell
pm2 start ecosystem.config.js --only mcp-tunnel
pm2 logs mcp-tunnel --lines 30          # copy the https://<words>.trycloudflare.com host
$env:TUNNEL_HOST="<words>.trycloudflare.com"
pm2 start ecosystem.config.js --only mcp-files
```

Commands:

```bash
pm2 start ecosystem.config.js
pm2 status                 # both should say "online"
pm2 logs mcp-tunnel        # find the trycloudflare.com URL here
pm2 logs mcp-files
pm2 restart mcp-files
pm2 save                   # remember the process list
```

Start on boot: on macOS/Linux run `pm2 startup`, then run the command it prints.
On Windows `pm2 startup` is not supported; use Task Scheduler or the community
`pm2-windows-startup` package.

Test it: `pm2 stop mcp-files`, wait, `pm2 start mcp-files`, and confirm the tools work again.
To prove crash recovery, kill the Python process and watch pm2 bring it back.

## 4. Keep it alive: systemd (Linux only)

Create `/etc/systemd/system/mcp-files.service` (adjust paths and user):

```ini
[Unit]
Description=MCP file server
After=network.target

[Service]
User=youruser
WorkingDirectory=/home/youruser/mcp_files
Environment=WORKSPACE_ROOT=/home/youruser/mcp_files/workspace
ExecStart=/home/youruser/mcp_files/.venv/bin/python server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/mcp-tunnel.service`:

```ini
[Unit]
Description=Cloudflare tunnel for MCP server
After=network-online.target mcp-files.service
Wants=network-online.target

[Service]
User=youruser
ExecStart=/usr/local/bin/cloudflared tunnel --url http://localhost:8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Commands:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-files mcp-tunnel
systemctl status mcp-files
journalctl -u mcp-tunnel -f      # find the tunnel URL here
sudo systemctl restart mcp-files
```

## 5. Connect a client

Add `https://<tunnel-host>/mcp` as a custom connector (Claude: Customize > Connectors >
Add custom connector). If the tunnel restarts and the hostname changes, update the URL.

## Security notes for the report

- The tunnel URL is public. Anyone who has it can call your tools, including `write_file`
  and `delete`. Add token auth before sharing it, and stop the tunnel when not demoing.
- All paths pass through `safe_path()`, so tools cannot leave `WORKSPACE_ROOT`.
- Keep `WORKSPACE_ROOT` a dedicated folder, not your home directory.
