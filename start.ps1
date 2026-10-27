# Starts IndQuant Terminal on http://localhost:8501 (this computer only) and opens it in your browser.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Virtual environment not found. Run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}
Write-Host "Starting IndQuant Terminal... it opens at http://localhost:8501 (keep this window open; Ctrl+C stops it)."
Start-Job -ScriptBlock { Start-Sleep -Seconds 6; Start-Process "http://localhost:8501" } | Out-Null
& .\.venv\Scripts\python.exe -m streamlit run app.py --server.address localhost
