param(
    [switch]$Full,
    [switch]$NoHtml
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LocalPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$LocalPython311 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"

function Select-BasePython {
    foreach ($Candidate in @($LocalPython, $LocalPython311)) {
        if (Test-Path -LiteralPath $Candidate) {
            return $Candidate
        }
    }
    $Cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($Cmd -and (Test-Path -LiteralPath $Cmd.Source) -and ((Get-Item $Cmd.Source).Length -gt 0)) {
        return $Cmd.Source
    }
    throw "No usable Python found. Install Python 3.11 or 3.12."
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $BasePython = Select-BasePython
    & $BasePython -m venv (Join-Path $RepoRoot ".venv")
}

& $VenvPython -m pip install --upgrade pip | Out-Host

$Probe = "import importlib.util; mods=['pytest','ruff','mypy','build','twine','pip_audit','fastapi','httpx','lumen_ai','lumen_ai_celery','lumen_ai_openlit']; missing=[m for m in mods if importlib.util.find_spec(m) is None]; raise SystemExit(1 if missing else 0)"
& $VenvPython -c $Probe
if ($LASTEXITCODE -ne 0) {
    & $VenvPython -m pip install -e packages/lumen-ai-core -e packages/lumen-ai-celery -e packages/lumen-ai-openlit pytest pytest-cov fastapi httpx ruff mypy build twine pip-audit celery | Out-Host
}

$ArgsList = @()
if ($Full) { $ArgsList += "--full" }
if ($NoHtml) { $ArgsList += "--no-html" }

& $VenvPython (Join-Path $RepoRoot "harness\scripts\collect_audit.py") @ArgsList
