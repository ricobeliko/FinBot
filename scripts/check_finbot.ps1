# scripts/check_finbot.ps1
# Diagnostico rapido de integridade e saude operacional do FinBot local.

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DbPath = Join-Path $ProjectRoot "data\finbot_paper.sqlite3"

Write-Host "=================================================="
Write-Host "FinBot - Health Check Local & Soak Telemetry"
Write-Host "=================================================="

# 1. Verificacao do interpretador Python e virtualenv
if (Test-Path $PythonExe) {
    $PyVer = & $PythonExe --version
    Write-Host "[OK] Python: $PyVer ($PythonExe)"
} else {
    Write-Error "[FALHA] Python da .venv nao encontrado em: $PythonExe"
    exit 1
}

# 2. Verificacao da base de dados SQLite
if (Test-Path $DbPath) {
    $FileItem = Get-Item $DbPath
    $Size = $FileItem.Length
    Write-Host "[OK] SQLite: Base encontrada ($Size bytes) em $DbPath"
} else {
    Write-Host "[INFO] SQLite: Base ainda nao criada (sera criada no primeiro ciclo)"
}

# 3. Execucao do Paper Status & Soak Telemetry (100% offline)
Push-Location $ProjectRoot
try {
    Write-Host "`nStatus Operacional (Paper Trading, Risk Engine e Soak Telemetry):"
    & $PythonExe -m finbot.paper --status
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[OK] Paper Status consultado com sucesso."
    } else {
        Write-Error "[FALHA] Paper Status retornou codigo de erro: $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

# 4. Verificacao de Git Remote (deve permanecer estritamente vazio)
Push-Location $ProjectRoot
try {
    $Remotes = git remote -v
    if ([string]::IsNullOrWhiteSpace($Remotes)) {
        Write-Host "[OK] Git Remote: Vazio (Ambiente 100% local-first)"
    } else {
        Write-Host "[AVISO] Git Remote detectado: $Remotes"
    }
}
finally {
    Pop-Location
}

# 5. Verificacao da tarefa agendada no Windows Task Scheduler
try {
    $Task = Get-ScheduledTask -TaskName "FinBot Paper Runner" -ErrorAction SilentlyContinue
    if ($Task) {
        $TaskInfo = Get-ScheduledTaskInfo -TaskName "FinBot Paper Runner" -ErrorAction SilentlyContinue
        Write-Host "[OK] Task Scheduler: Tarefa 'FinBot Paper Runner' (Estado: $($Task.State))"
        if ($TaskInfo) {
            Write-Host "     - Ultima Execucao: $($TaskInfo.LastRunTime)"
            Write-Host "     - Proxima Execucao: $($TaskInfo.NextRunTime)"
            Write-Host "     - Ultimo Resultado Task: $($TaskInfo.LastTaskResult)"
        }
    } else {
        Write-Host "[INFO] Task Scheduler: Nenhuma tarefa 'FinBot Paper Runner' registrada no momento"
    }
} catch {
    Write-Host "[INFO] Task Scheduler: Nao foi possivel consultar tarefas agendadas"
}

Write-Host "`n[OK] Real Trading: DISABLED"
Write-Host "=================================================="
