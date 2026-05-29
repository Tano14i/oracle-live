$ErrorActionPreference = "Stop"

$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $baseDir ".venv\Scripts\python.exe"
$venvStreamlit = Join-Path $baseDir ".venv\Scripts\streamlit.exe"
$liveScript = Join-Path $baseDir "oracle_live.py"
$sniperScript = Join-Path $baseDir "Oracle_Sniper.py"
$sniperLauncher = Join-Path $baseDir "Oracle_Sniper_Launch.bat"
$appScript = Join-Path $baseDir "Oracle_App.py"
$appLauncher = Join-Path $baseDir "Oracle_App_Launch.bat"

function Test-RequiredFile {
    param(
        [string]$Path,
        [string]$Label
    )
    if (-not (Test-Path $Path)) {
        Write-Host "$Label not found: $Path" -ForegroundColor Red
        return $false
    }
    return $true
}

function Start-OracleProcess {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments
    )
    try {
        Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $baseDir | Out-Null
        Write-Host "$Label started." -ForegroundColor Green
    } catch {
        Write-Host "Unable to start $Label: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Show-Header {
    Clear-Host
    Write-Host "=========================" -ForegroundColor DarkCyan
    Write-Host "     ORACLE LAUNCHER     " -ForegroundColor Cyan
    Write-Host "=========================" -ForegroundColor DarkCyan
    Write-Host ""
    Write-Host "Workspace: $baseDir" -ForegroundColor DarkGray
    Write-Host ""
}

if (-not (Test-RequiredFile -Path $venvPython -Label "Python venv")) {
    exit 1
}

do {
    Show-Header
    Write-Host "1. Start Oracle Live" -ForegroundColor White
    Write-Host "2. Start Oracle Sniper" -ForegroundColor White
    Write-Host "3. Start Oracle App" -ForegroundColor White
    Write-Host "4. Start All" -ForegroundColor White
    Write-Host "5. Exit" -ForegroundColor White
    Write-Host ""
    $choice = Read-Host "Select an option"

    switch ($choice) {
        "1" {
            if (Test-RequiredFile -Path $liveScript -Label "oracle_live.py") {
                Start-OracleProcess -Label "Oracle Live" -FilePath $venvPython -Arguments @($liveScript)
            }
            Pause
        }
        "2" {
            if (Test-RequiredFile -Path $sniperLauncher -Label "Oracle_Sniper_Launch.bat") {
                Start-OracleProcess -Label "Oracle Sniper" -FilePath $sniperLauncher -Arguments @()
            }
            Pause
        }
        "3" {
            if (-not (Test-RequiredFile -Path $appLauncher -Label "Oracle_App_Launch.bat")) {
                Pause
                continue
            }
            if (Test-RequiredFile -Path $appScript -Label "Oracle_App.py") {
                Start-OracleProcess -Label "Oracle App" -FilePath $appLauncher -Arguments @()
            }
            Pause
        }
        "4" {
            if (Test-RequiredFile -Path $liveScript -Label "oracle_live.py") {
                Start-OracleProcess -Label "Oracle Live" -FilePath $venvPython -Arguments @($liveScript)
            }
            if (Test-RequiredFile -Path $sniperLauncher -Label "Oracle_Sniper_Launch.bat") {
                Start-OracleProcess -Label "Oracle Sniper" -FilePath $sniperLauncher -Arguments @()
            }
            if ((Test-RequiredFile -Path $appLauncher -Label "Oracle_App_Launch.bat") -and (Test-RequiredFile -Path $appScript -Label "Oracle_App.py")) {
                Start-OracleProcess -Label "Oracle App" -FilePath $appLauncher -Arguments @()
            }
            Pause
        }
        "5" {
            break
        }
        default {
            Write-Host "Invalid option." -ForegroundColor Yellow
            Start-Sleep -Seconds 1
        }
    }
} while ($true)
