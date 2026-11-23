$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Please install uv first: https://docs.astral.sh/uv/getting-started/installation/'
}
uv sync --frozen
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'ACM Agent: http://127.0.0.1:8000 (Ctrl+C to stop)'
uv run acm-agent --web
exit $LASTEXITCODE
