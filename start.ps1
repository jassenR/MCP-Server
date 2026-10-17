# Starts the Cloudflare tunnel, waits for its public hostname, then starts the MCP server with that
# hostname allowed. Creates a secret on first run. Run via start.bat (double-click) or:
#   powershell -ExecutionPolicy Bypass -File .\start.ps1

Set-Location -LiteralPath $PSScriptRoot

# --- Secret: created once and kept in .env (never committed). It becomes part of the URL path.
$envFile = Join-Path $PSScriptRoot ".env"
$secret = $null
if (Test-Path -LiteralPath $envFile) {
    $line = Select-String -LiteralPath $envFile -Pattern '^\s*MCP_SECRET\s*=\s*(\S+)' | Select-Object -First 1
    if ($line) { $secret = $line.Matches[0].Groups[1].Value }
}
if (-not $secret) {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = ([BitConverter]::ToString($bytes) -replace '-', '').ToLower()
    Add-Content -LiteralPath $envFile -Value "`r`nMCP_SECRET=$secret"
    Write-Host "Created a new MCP_SECRET in .env"
}

Write-Host "Stopping any old MCP processes..."
pm2 delete mcp-files 2>$null | Out-Null
pm2 delete mcp-tunnel 2>$null | Out-Null
pm2 flush 2>$null | Out-Null

$logDir = Join-Path $env:USERPROFILE ".pm2\logs"
$pattern = 'https://([a-z0-9-]+\.trycloudflare\.com)'

# pm2 flush does nothing for deleted apps, so old tunnel logs would survive and their stale
# address would be picked up. Delete them, and also remember any address still in them to ignore.
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $logDir "mcp-tunnel-*.log")
$stale = @()
foreach ($name in "mcp-tunnel-error.log", "mcp-tunnel-out.log") {
    $file = Join-Path $logDir $name
    if (Test-Path -LiteralPath $file) {
        $stale += Select-String -LiteralPath $file -Pattern $pattern -AllMatches -ErrorAction SilentlyContinue |
            ForEach-Object { $_.Matches } |
            ForEach-Object { $_.Groups[1].Value }
    }
}

Write-Host "Starting tunnel..."
pm2 start ecosystem.config.js --only mcp-tunnel | Out-Null

$tunnelHost = $null

# Wait up to ~60 seconds for cloudflared to print its address
for ($i = 0; $i -lt 30 -and -not $tunnelHost; $i++) {
    Start-Sleep -Seconds 2
    foreach ($name in "mcp-tunnel-error.log", "mcp-tunnel-out.log") {
        $file = Join-Path $logDir $name
        if (Test-Path -LiteralPath $file) {
            $found = Select-String -LiteralPath $file -Pattern $pattern -AllMatches -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Matches } |
                ForEach-Object { $_.Groups[1].Value } |
                Where-Object { $_ -ne "api.trycloudflare.com" -and $stale -notcontains $_ } |
                Select-Object -Last 1
            if ($found) { $tunnelHost = $found; break }
        }
    }
}

if (-not $tunnelHost) {
    Write-Host "Could not find the tunnel address. Check: pm2 logs mcp-tunnel" -ForegroundColor Red
    exit 1
}

$env:TUNNEL_HOST = $tunnelHost

Write-Host "Starting MCP server..."
pm2 start ecosystem.config.js --only mcp-files | Out-Null
pm2 save 2>$null | Out-Null

$url = "https://$tunnelHost/$secret/mcp"
Set-Clipboard -Value $url

Write-Host ""
Write-Host "Connector URL (copied to clipboard). Treat it like a password:" -ForegroundColor Green
Write-Host "  $url" -ForegroundColor Green
Write-Host ""
Write-Host "Paste it into claude.ai > Customize > Connectors (edit the Workspace-Files URL)."
Write-Host ""

# Prove the endpoint is protected (no secret = 404, right secret = 200)
Start-Sleep -Seconds 6
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $py) {
    Write-Host "Checking the public endpoint..."
    & $py check_endpoint.py "https://$tunnelHost"
    Write-Host "(If a check says 'got 0', the tunnel is still warming up: wait a minute and run" 
    Write-Host " .venv\Scripts\python.exe check_endpoint.py https://$tunnelHost)"
}
Write-Host ""
pm2 status
