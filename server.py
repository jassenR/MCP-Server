"""Entry point: builds the MCP app, secures the endpoint, registers tools, serves Streamable HTTP.

Layout: config.py (env settings) / sandbox.py (path safety) / audit.py (call log) / tools.py (tools).
"""
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import config
import tools

config.validate()

# The SDK rejects unknown Host headers ("Invalid Host header"); allow localhost and the tunnel.
_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
if config.TUNNEL_HOST:
    _hosts.append(config.TUNNEL_HOST)
    _origins.append(f"https://{config.TUNNEL_HOST}")

# Secret path: with MCP_SECRET set, only /<secret>/mcp answers; every other path is 404.
endpoint = f"/{config.MCP_SECRET}/mcp" if config.MCP_SECRET else "/mcp"

mcp = FastMCP(
    "workspace-files",
    host=config.HOST,
    port=config.PORT,
    streamable_http_path=endpoint,
    log_level="WARNING",  # keeps the secret path out of access logs; see logs/tool_calls.jsonl instead
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_hosts,
        allowed_origins=_origins,
    ),
)
registered = tools.register(mcp, config.ROLE)

if __name__ == "__main__":
    shown = "/<secret>/mcp" if config.MCP_SECRET else "/mcp"
    print(f"workspace-files | role={config.ROLE} | {len(registered)} tools | "
          f"port {config.PORT} | endpoint {shown} | workspace {config.WORKSPACE_ROOT}", flush=True)
    mcp.run(transport="streamable-http")
