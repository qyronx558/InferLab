[CmdletBinding()]
param([string]$Python = "3.12")

$ErrorActionPreference = "Stop"
$workspaceRoot = Split-Path -Parent $PSScriptRoot
Push-Location $workspaceRoot
try {
    foreach ($tool in @("node", "npm.cmd", "uv")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "Missing $tool. Install Node.js 22.13+ (22.x or 24.x), npm, and uv; see README.md."
        }
    }
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
    & uv sync --locked --python $Python
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
    foreach ($example in @("apps/web/.env.example", "apps/api/.env.example", "worker/.env.example")) {
        $destination = $example -replace '\.example$', ''
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath $example -Destination $destination
        }
    }
    Write-Host "Setup complete. See README.md for per-app commands. Existing .env files were preserved."
}
finally { Pop-Location }
