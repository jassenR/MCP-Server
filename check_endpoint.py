"""Endpoint check: proves the public URL needs the secret.

Usage:  python check_endpoint.py https://<tunnel-host>          (secret read from .env / MCP_SECRET)
        python check_endpoint.py http://127.0.0.1:8000
Expected: no-secret and wrong-secret paths return 404; the correct secret path returns 200.
"""
import json
import sys
import urllib.error
import urllib.request

from config import MCP_SECRET

INIT = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {},
               "clientInfo": {"name": "endpoint-check", "version": "1"}},
}).encode()


def status(url: str) -> int:
    req = urllib.request.Request(url, data=INIT, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "mcp-endpoint-check/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except urllib.error.URLError:
        return 0  # unreachable (tunnel not ready yet, DNS not propagated, server down)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if not MCP_SECRET:
        print("MCP_SECRET is not set (check .env); cannot test the secret path.")
        return 2
    base = sys.argv[1].rstrip("/")
    checks = [
        ("no secret   /mcp", f"{base}/mcp", 404),
        ("wrong secret", f"{base}/not-the-secret/mcp", 404),
        ("right secret", f"{base}/{MCP_SECRET}/mcp", 200),
    ]
    ok = True
    for label, url, expected in checks:
        got = status(url)
        passed = got == expected
        ok &= passed
        print(f"{'PASS' if passed else 'FAIL'}  {label:<14} expected {expected}, got {got}")
    print("endpoint check passed" if ok else "endpoint check FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
