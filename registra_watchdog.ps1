# Registra l'operazione pianificata che controlla il bot ogni dieci minuti.
#
# Perche' serve, oltre all'avvio automatico al login: il 9 ottobre 2026 il bot
# e' morto alle 23:49:59Z e nessuno l'ha rimesso in piedi per cinque ore e
# cinquanta. Windows non si era ne' spento ne' sospeso - uptime 73,6 ore -
# quindi nessun login e' avvenuto, e un avvio "al login" non sarebbe scattato.
# Il controllo periodico e' l'unica cosa che copre quel caso.
#
# Cosa fa: ogni dieci minuti lancia watchdog.py, che guarda se qualcuno tiene
# oracle_live.lock. Se il bot c'e' non fa niente e non scrive niente; se non
# c'e' avvia il supervisore staccato. Non puo' mai avviarne due.
#
# Per annullare tutto:
#   Unregister-ScheduledTask -TaskName "Oracle Live watchdog" -Confirm:$false

$dir = "C:\Users\Gebruiker\Desktop\Claude Workspace\Oracle Live"
$exe = Join-Path $dir ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $exe)) { Write-Error "interprete non trovato: $exe"; exit 1 }
if (-not (Test-Path (Join-Path $dir "watchdog.py"))) { Write-Error "watchdog.py non trovato in $dir"; exit 1 }

$azione = New-ScheduledTaskAction -Execute $exe -Argument '"watchdog.py"' -WorkingDirectory $dir
$alLogin = New-ScheduledTaskTrigger -AtLogOn
$ogniDieci = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10)
$impostazioni = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName "Oracle Live watchdog" `
    -Description "Avvia Oracle Live se non sta girando: al login e ogni 10 minuti." `
    -Action $azione -Trigger $alLogin, $ogniDieci -Settings $impostazioni -Force | Out-Null

$t = Get-ScheduledTask -TaskName "Oracle Live watchdog"
"registrata: $($t.TaskName) | stato: $($t.State)"
"trigger: $($t.Triggers.Count) (login + ripetizione ogni 10 minuti)"
"prova subito:  Start-ScheduledTask -TaskName 'Oracle Live watchdog'"
