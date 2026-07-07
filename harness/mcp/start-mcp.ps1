$ErrorActionPreference = "Stop"

$RepoRoot = $env:LUMEN_AUDIT_ROOT
if (-not $RepoRoot) {
    $RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LocalPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"

if (Test-Path -LiteralPath $VenvPython) {
    $Python = $VenvPython
} elseif (Test-Path -LiteralPath $LocalPython) {
    $Python = $LocalPython
} else {
    throw "Python not found. Run harness\scripts\run-audit.ps1 first."
}

& $Python (Join-Path $RepoRoot "harness\mcp\lumen_audit_mcp.py")

