// pm2 config: keeps the MCP server and the Cloudflare quick tunnel running.
//
// Quick-tunnel hostnames change every time the tunnel starts, and the server must be told the
// current hostname (TUNNEL_HOST). So start the tunnel first, read its URL, then start the server:
//
//   pm2 start ecosystem.config.js --only mcp-tunnel
//   pm2 logs mcp-tunnel --lines 30          (find https://<words>.trycloudflare.com)
//   $env:TUNNEL_HOST="<words>.trycloudflare.com"      (PowerShell; host only, no https:// or /mcp)
//   pm2 start ecosystem.config.js --only mcp-files
//
// The server reads MCP_SECRET from .env (created by start.bat). The connector URL is
//   https://<TUNNEL_HOST>/<MCP_SECRET>/mcp
//
// If the tunnel restarts, its hostname changes: run `pm2 delete mcp-files`, set the new
// TUNNEL_HOST, and start mcp-files again.

const isWindows = process.platform === "win32";

module.exports = {
  apps: [
    {
      name: "mcp-files",
      script: "server.py",
      cwd: __dirname,
      interpreter: isWindows ? ".venv\\Scripts\\python.exe" : ".venv/bin/python",
      env: {
        WORKSPACE_ROOT: "./workspace",
        TUNNEL_HOST: process.env.TUNNEL_HOST || "",
      },
      autorestart: true,
      restart_delay: 3000,
      max_restarts: 20,
    },
    {
      name: "mcp-tunnel",
      // If pm2 can't find cloudflared, replace with its full path, e.g.
      // "C:\\Program Files (x86)\\cloudflared\\cloudflared.exe"
      script: "cloudflared",
      args: "tunnel --url http://localhost:8000",
      interpreter: "none",
      autorestart: true,
      restart_delay: 5000,
    },
  ],
};
