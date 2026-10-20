[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$workspaceRoot = Split-Path -Parent $PSScriptRoot
Push-Location $workspaceRoot
try {
    & npm.cmd run contracts:check
    if ($LASTEXITCODE -ne 0) { throw "Contract/schema/type/fixture drift detected." }
    & npm.cmd run format:check
    if ($LASTEXITCODE -ne 0) { throw "Frontend/config formatting failed." }
    & npm.cmd run lint
    if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed." }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build/typecheck failed." }
    & npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw "Frontend unit tests failed." }
    & uv run --locked ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Python lint failed." }
    & uv run --locked ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw "Python formatting failed." }
    & uv run --locked mypy
    if ($LASTEXITCODE -ne 0) { throw "Python typecheck failed." }
    & uv run --locked pytest -m "not gpu"
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed." }
    & uv run --locked pre-commit validate-config
    if ($LASTEXITCODE -ne 0) { throw "Pre-commit configuration invalid." }
}
finally { Pop-Location }
