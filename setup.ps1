# One-time setup: virtual environment + pinned dependencies + tests. No broker connection is made.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
py -3.12 --version
if (-not (Test-Path ".\.venv")) { py -3.12 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path ".\.env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env from .env.example (placeholders only)." }
& .\.venv\Scripts\python.exe -m pytest
Write-Host "Setup complete. Start the terminal with .\start.ps1" -ForegroundColor Green
