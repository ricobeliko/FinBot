# scripts/run_dashboard.ps1
# Inicia o Dashboard visual local do FinBot via Streamlit em localhost.

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$StreamlitExe = Join-Path $ProjectRoot ".venv\Scripts\streamlit.exe"

if (-not (Test-Path $PythonExe)) {
    [Console]::Error.WriteLine("ERRO [run_dashboard]: Ambiente virtual Python não encontrado em: $PythonExe")
    exit 1
}

Write-Host "Iniciando FinBot Dashboard em http://127.0.0.1:8501 (Modo Read-Only)..."
Write-Host "Pressione Ctrl + C para encerrar o servidor."

Push-Location $ProjectRoot
try {
    if (Test-Path $StreamlitExe) {
        & $StreamlitExe run src/finbot/dashboard.py --server.address=127.0.0.1
    } else {
        & $PythonExe -m streamlit run src/finbot/dashboard.py --server.address=127.0.0.1
    }
}
finally {
    Pop-Location
}
