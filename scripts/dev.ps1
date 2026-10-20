[CmdletBinding()]
param([Parameter(Mandatory = $true)][ValidateSet("web", "api", "worker")][string]$App)

$ErrorActionPreference = "Stop"
$workspaceRoot = Split-Path -Parent $PSScriptRoot
Push-Location $workspaceRoot
try {
    switch ($App) {
        "web" { & npm.cmd run dev:web }
        "api" { & uv run --locked uvicorn inferlab_api.main:app --host 127.0.0.1 --port 8000 --reload }
        "worker" { & uv run --locked inferlab-worker }
    }
    if ($LASTEXITCODE -ne 0) { throw "$App exited with code $LASTEXITCODE." }
}
finally { Pop-Location }
