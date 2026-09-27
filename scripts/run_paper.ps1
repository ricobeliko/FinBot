# scripts/run_paper.ps1
# Executa um ciclo one-shot de Paper Trading local do FinBot.
# Projetado para execução manual ou acionamento periódico pelo Windows Task Scheduler.

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    [Console]::Error.WriteLine("ERRO [run_paper]: Ambiente virtual Python não encontrado em: $PythonExe")
    exit 1
}

# Executa o ciclo one-shot no diretório do projeto, preservando stdout, stderr e código de saída
Push-Location $ProjectRoot
try {
    & $PythonExe -m finbot.paper
    $ExitCode = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine("ERRO [run_paper]: Falha inesperada ao invocar finbot.paper: $_")
    $ExitCode = 1
}
finally {
    Pop-Location
}

exit $ExitCode
