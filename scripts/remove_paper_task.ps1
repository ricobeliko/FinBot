# scripts/remove_paper_task.ps1
# Remove a tarefa agendada do FinBot no Windows Task Scheduler.

$ErrorActionPreference = "Stop"

$TaskName = "FinBot Paper Runner"

Write-Host "Verificando tarefa '$TaskName' no Windows Task Scheduler..."

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Tarefa '$TaskName' foi removida com sucesso do Windows Task Scheduler."
} else {
    Write-Host "[INFO] A tarefa '$TaskName' nao foi encontrada ou ja havia sido removida."
}
