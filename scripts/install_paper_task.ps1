# scripts/install_paper_task.ps1
# Instala e configura a tarefa agendada local no Windows Task Scheduler.
# Executa o script run_paper.ps1 a cada 1 minuto de forma estritamente simulada.

$ErrorActionPreference = "Stop"

$TaskName = "FinBot Paper Runner"
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$ScriptPath = Join-Path $ProjectRoot "scripts\run_paper.ps1"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "ERRO: Script run_paper.ps1 nao encontrado em: $ScriptPath"
    exit 1
}

Write-Host "Configurando tarefa agendada no Windows Task Scheduler..."
Write-Host "Nome da Tarefa: $TaskName"
Write-Host "Script: $ScriptPath"
Write-Host "Intervalo: 1 minuto"
Write-Host "Politica de Concorrencia: IgnoreNew (Nao inicia nova instancia se anterior estiver ativa)"

# Remove tarefa existente previamente se houver
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Write-Host "Removendo versao anterior da tarefa..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 1. Acao: invoca powershell chamando run_paper.ps1 com janela oculta
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`"" `
    -WorkingDirectory $ProjectRoot

# 2. Gatilho (Trigger): Repeticao a cada 1 minuto por tempo indeterminado
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)

# 3. Configuracoes de Concorrencia e Energia:
# - MultipleInstances: IgnoreNew (evita sobreposicao)
# - AllowStartIfOnBatteries / DontStopIfGoingOnBatteries (notebook)
# - ExecutionTimeLimit: 5 minutos (timeout preventivo)
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

# 4. Registra a tarefa para o usuario local atual sem exigir privilegios de administrador
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "FinBot Automated Paper Runner - Ciclos One-Shot a cada 1m com protecao contra sobreposicao (IgnoreNew)."

Write-Host "`n[SUCESSO] Tarefa instalada com sucesso!"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State
