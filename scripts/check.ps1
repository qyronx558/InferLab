[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$workspaceRoot = Split-Path -Parent $PSScriptRoot
Push-Location $workspaceRoot
try {
    & npm.cmd run lint
    if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed." }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build/typecheck failed." }
    & uv run --locked ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Python lint failed." }
    & uv run --locked ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw "Python formatting failed." }
    & uv run --locked mypy
    if ($LASTEXITCODE -ne 0) { throw "Python typecheck failed." }
    & uv run --locked pytest
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed." }
}
finally { Pop-Location }
