$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $baseDir ".venv\Scripts\python.exe"
$venvStreamlit = Join-Path $baseDir ".venv\Scripts\streamlit.exe"
$liveScript = Join-Path $baseDir "oracle_live.py"
$sniperScript = Join-Path $baseDir "Oracle_Sniper.py"
$sniperLauncher = Join-Path $baseDir "Oracle_Sniper_Launch.bat"
$sniperLock = Join-Path $baseDir "oracle_sniper.lock"
$appScript = Join-Path $baseDir "Oracle_App.py"
$appLauncher = Join-Path $baseDir "Oracle_App_Launch.bat"
$appUrl = "http://localhost:8501"

function Test-RequiredFile {
    param(
        [string]$Path
    )
    return [bool](Test-Path $Path)
}

function Get-ScriptProcesses {
    param(
        [string]$ScriptName
    )
    $escaped = [regex]::Escape($ScriptName)
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $escaped
    })
}

function Get-ServiceState {
    param(
        [string]$ScriptName
    )
    $items = Get-ScriptProcesses -ScriptName $ScriptName
    if ($items.Count -gt 0) {
        return "Running ($($items.Count))"
    }
    return "Stopped"
}

function Get-ServiceRunning {
    param(
        [string]$ScriptName
    )
    return (Get-ScriptProcesses -ScriptName $ScriptName).Count -gt 0
}

function Test-PidRunning {
    param(
        [int]$Pid
    )
    if (-not $Pid) {
        return $false
    }
    try {
        $process = Get-Process -Id $Pid -ErrorAction Stop
        return $null -ne $process
    } catch {
        return $false
    }
}

function Get-SniperRuntimeState {
    $processRunning = Get-ServiceRunning -ScriptName "Oracle_Sniper.py"
    $lockExists = Test-Path $sniperLock
    if ($processRunning) {
        return @{
            Running = $true
            Label = Get-ServiceState -ScriptName "Oracle_Sniper.py"
            Source = "process"
        }
    }
    if (-not $lockExists) {
        return @{
            Running = $false
            Label = "Stopped"
            Source = "none"
        }
    }
    try {
        $raw = Get-Content -Path $sniperLock -Raw -ErrorAction Stop
        $pid = 0
        [void][int]::TryParse(($raw.Trim()), [ref]$pid)
        if (Test-PidRunning -Pid $pid) {
            return @{
                Running = $true
                Label = "Running (lock $pid)"
                Source = "lock"
            }
        }
        Remove-Item $sniperLock -Force -ErrorAction SilentlyContinue
        return @{
            Running = $false
            Label = "Stopped"
            Source = "stale_lock"
        }
    } catch {
        return @{
            Running = $false
            Label = "Stopped"
            Source = "lock_error"
        }
    }
}

function Start-ServiceProcess {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$ScriptName
    )
    if (-not (Test-Path $FilePath)) {
        [System.Windows.Forms.MessageBox]::Show("$Label executable not found.`n$FilePath", "Oracle Launcher Pro")
        return
    }
    if ((Get-ScriptProcesses -ScriptName $ScriptName).Count -gt 0) {
        [System.Windows.Forms.MessageBox]::Show("$Label is already running.", "Oracle Launcher Pro")
        return
    }
    if ($Arguments -and $Arguments.Count -gt 0) {
        Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $baseDir | Out-Null
    } else {
        Start-Process -FilePath $FilePath -WorkingDirectory $baseDir | Out-Null
    }
}

function Stop-ServiceProcess {
    param(
        [string]$ScriptName
    )
    $items = Get-ScriptProcesses -ScriptName $ScriptName
    foreach ($item in $items) {
        try {
            Stop-Process -Id $item.ProcessId -Force -ErrorAction Stop
        } catch {
        }
    }
}

function Update-StatusLabels {
    $liveRunning = Get-ServiceRunning -ScriptName "oracle_live.py"
    $sniperState = Get-SniperRuntimeState
    $sniperRunning = [bool]$sniperState.Running
    $appRunning = Get-ServiceRunning -ScriptName "Oracle_App.py"

    $liveStatusLabel.Text = if ($liveRunning) { "RUNNING" } else { "STOPPED" }
    $sniperStatusLabel.Text = if ($sniperRunning) { "RUNNING" } else { "STOPPED" }
    $appStatusLabel.Text = if ($appRunning) { "RUNNING" } else { "STOPPED" }

    $liveCountLabel.Text = Get-ServiceState -ScriptName "oracle_live.py"
    $sniperCountLabel.Text = [string]$sniperState.Label
    $appCountLabel.Text = Get-ServiceState -ScriptName "Oracle_App.py"

    foreach ($item in @(
        @{ Running = $liveRunning; Label = $liveStatusLabel; Panel = $liveAccentPanel },
        @{ Running = $sniperRunning; Label = $sniperStatusLabel; Panel = $sniperAccentPanel },
        @{ Running = $appRunning; Label = $appStatusLabel; Panel = $appAccentPanel }
    )) {
        if ($item.Running) {
            $item.Label.BackColor = [System.Drawing.Color]::FromArgb(25, 92, 57)
            $item.Label.ForeColor = [System.Drawing.Color]::FromArgb(143, 240, 175)
            $item.Panel.BackColor = [System.Drawing.Color]::FromArgb(36, 106, 68)
        } else {
            $item.Label.BackColor = [System.Drawing.Color]::FromArgb(72, 54, 26)
            $item.Label.ForeColor = [System.Drawing.Color]::FromArgb(255, 217, 120)
            $item.Panel.BackColor = [System.Drawing.Color]::FromArgb(90, 65, 29)
        }
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Oracle Launcher Pro"
$form.Size = New-Object System.Drawing.Size(860, 640)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(11, 20, 32)
$form.ForeColor = [System.Drawing.Color]::White
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$titleLabel = New-Object System.Windows.Forms.Label
$titleLabel.Text = "Oracle Launcher Pro"
$titleLabel.Font = New-Object System.Drawing.Font("Segoe UI", 22, [System.Drawing.FontStyle]::Bold)
$titleLabel.ForeColor = [System.Drawing.Color]::FromArgb(245, 247, 251)
$titleLabel.AutoSize = $true
$titleLabel.Location = New-Object System.Drawing.Point(24, 20)
$form.Controls.Add($titleLabel)

$subtitleLabel = New-Object System.Windows.Forms.Label
$subtitleLabel.Text = "Private control room for Oracle Live, Oracle Sniper and Oracle App"
$subtitleLabel.ForeColor = [System.Drawing.Color]::FromArgb(150, 170, 198)
$subtitleLabel.AutoSize = $true
$subtitleLabel.Location = New-Object System.Drawing.Point(28, 62)
$form.Controls.Add($subtitleLabel)

$summaryPanel = New-Object System.Windows.Forms.Panel
$summaryPanel.Location = New-Object System.Drawing.Point(24, 94)
$summaryPanel.Size = New-Object System.Drawing.Size(796, 58)
$summaryPanel.BackColor = [System.Drawing.Color]::FromArgb(15, 25, 38)
$form.Controls.Add($summaryPanel)

$summaryText = New-Object System.Windows.Forms.Label
$summaryText.Text = "Launch and monitor the full Oracle stack from one place."
$summaryText.ForeColor = [System.Drawing.Color]::FromArgb(214, 224, 239)
$summaryText.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$summaryText.AutoSize = $true
$summaryText.Location = New-Object System.Drawing.Point(18, 10)
$summaryPanel.Controls.Add($summaryText)

$summaryHint = New-Object System.Windows.Forms.Label
$summaryHint.Text = "Live = production bot | Sniper = speculative private engine | App = dashboard"
$summaryHint.ForeColor = [System.Drawing.Color]::FromArgb(138, 161, 193)
$summaryHint.AutoSize = $true
$summaryHint.Location = New-Object System.Drawing.Point(18, 31)
$summaryPanel.Controls.Add($summaryHint)

function New-SectionPanel {
    param(
        [string]$Title,
        [string]$Description,
        [int]$Top
    )
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Location = New-Object System.Drawing.Point(24, $Top)
    $panel.Size = New-Object System.Drawing.Size(796, 102)
    $panel.BackColor = [System.Drawing.Color]::FromArgb(18, 24, 36)

    $accent = New-Object System.Windows.Forms.Panel
    $accent.Location = New-Object System.Drawing.Point(0, 0)
    $accent.Size = New-Object System.Drawing.Size(8, 102)
    $accent.BackColor = [System.Drawing.Color]::FromArgb(36, 106, 68)
    $panel.Controls.Add($accent)

    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Title
    $label.Font = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
    $label.ForeColor = [System.Drawing.Color]::FromArgb(244, 201, 93)
    $label.AutoSize = $true
    $label.Location = New-Object System.Drawing.Point(20, 12)
    $panel.Controls.Add($label)

    $descriptionLabel = New-Object System.Windows.Forms.Label
    $descriptionLabel.Text = $Description
    $descriptionLabel.ForeColor = [System.Drawing.Color]::FromArgb(138, 161, 193)
    $descriptionLabel.AutoSize = $true
    $descriptionLabel.Location = New-Object System.Drawing.Point(20, 36)
    $panel.Controls.Add($descriptionLabel)

    $statusValue = New-Object System.Windows.Forms.Label
    $statusValue.Text = "CHECKING"
    $statusValue.ForeColor = [System.Drawing.Color]::FromArgb(143, 240, 175)
    $statusValue.BackColor = [System.Drawing.Color]::FromArgb(25, 92, 57)
    $statusValue.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $statusValue.AutoSize = $false
    $statusValue.TextAlign = "MiddleCenter"
    $statusValue.Location = New-Object System.Drawing.Point(22, 62)
    $statusValue.Size = New-Object System.Drawing.Size(102, 24)
    $panel.Controls.Add($statusValue)

    $countValue = New-Object System.Windows.Forms.Label
    $countValue.Text = "Checking..."
    $countValue.ForeColor = [System.Drawing.Color]::FromArgb(214, 224, 239)
    $countValue.AutoSize = $true
    $countValue.Location = New-Object System.Drawing.Point(136, 66)
    $panel.Controls.Add($countValue)

    return @{
        Panel = $panel
        Status = $statusValue
        Count = $countValue
        Accent = $accent
    }
}

function New-ActionButton {
    param(
        [string]$Text,
        [int]$Left,
        [int]$Top,
        [int]$Width = 110,
        [int]$Height = 34
    )
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $Text
    $button.Location = New-Object System.Drawing.Point($Left, $Top)
    $button.Size = New-Object System.Drawing.Size($Width, $Height)
    $button.FlatStyle = "Flat"
    $button.BackColor = [System.Drawing.Color]::FromArgb(24, 73, 112)
    $button.ForeColor = [System.Drawing.Color]::White
    $button.FlatAppearance.BorderSize = 0
    return $button
}

$liveSection = New-SectionPanel -Title "Oracle Live" -Description "Main Telegram engine for live, VIP and owner flows." -Top 170
$sniperSection = New-SectionPanel -Title "Oracle Sniper" -Description "Separate speculative engine with kill switch and low-volume routing." -Top 292
$appSection = New-SectionPanel -Title "Oracle App" -Description "Private dashboard for mobile and desktop monitoring." -Top 414

$liveStatusLabel = $liveSection.Status
$sniperStatusLabel = $sniperSection.Status
$appStatusLabel = $appSection.Status
$liveCountLabel = $liveSection.Count
$sniperCountLabel = $sniperSection.Count
$appCountLabel = $appSection.Count
$liveAccentPanel = $liveSection.Accent
$sniperAccentPanel = $sniperSection.Accent
$appAccentPanel = $appSection.Accent

$form.Controls.Add($liveSection.Panel)
$form.Controls.Add($sniperSection.Panel)
$form.Controls.Add($appSection.Panel)

$liveStart = New-ActionButton -Text "Start" -Left 540 -Top 32 -Width 108 -Height 36
$liveStop = New-ActionButton -Text "Stop" -Left 662 -Top 32 -Width 108 -Height 36
$liveStop.BackColor = [System.Drawing.Color]::FromArgb(124, 41, 41)
$liveSection.Panel.Controls.Add($liveStart)
$liveSection.Panel.Controls.Add($liveStop)

$sniperStart = New-ActionButton -Text "Start" -Left 540 -Top 32 -Width 108 -Height 36
$sniperStop = New-ActionButton -Text "Stop" -Left 662 -Top 32 -Width 108 -Height 36
$sniperStop.BackColor = [System.Drawing.Color]::FromArgb(124, 41, 41)
$sniperSection.Panel.Controls.Add($sniperStart)
$sniperSection.Panel.Controls.Add($sniperStop)

$appStart = New-ActionButton -Text "Start" -Left 418 -Top 32 -Width 108 -Height 36
$appOpen = New-ActionButton -Text "Open" -Left 540 -Top 32 -Width 108 -Height 36
$appStop = New-ActionButton -Text "Stop" -Left 662 -Top 32 -Width 108 -Height 36
$appOpen.BackColor = [System.Drawing.Color]::FromArgb(39, 104, 72)
$appStop.BackColor = [System.Drawing.Color]::FromArgb(124, 41, 41)
$appSection.Panel.Controls.Add($appStart)
$appSection.Panel.Controls.Add($appOpen)
$appSection.Panel.Controls.Add($appStop)

$footerPanel = New-Object System.Windows.Forms.Panel
$footerPanel.Location = New-Object System.Drawing.Point(24, 536)
$footerPanel.Size = New-Object System.Drawing.Size(796, 50)
$footerPanel.BackColor = [System.Drawing.Color]::FromArgb(11, 20, 32)
$form.Controls.Add($footerPanel)

$startAll = New-ActionButton -Text "Start All" -Left 0 -Top 0 -Width 140 -Height 38
$stopAll = New-ActionButton -Text "Stop All" -Left 154 -Top 0 -Width 140 -Height 38
$refreshBtn = New-ActionButton -Text "Refresh" -Left 308 -Top 0 -Width 140 -Height 38
$openFolder = New-ActionButton -Text "Open Folder" -Left 462 -Top 0 -Width 140 -Height 38
$openDashboard = New-ActionButton -Text "Open App" -Left 616 -Top 0 -Width 140 -Height 38
$openFolder.BackColor = [System.Drawing.Color]::FromArgb(39, 104, 72)
$openDashboard.BackColor = [System.Drawing.Color]::FromArgb(39, 104, 72)
$stopAll.BackColor = [System.Drawing.Color]::FromArgb(124, 41, 41)
$footerPanel.Controls.Add($startAll)
$footerPanel.Controls.Add($stopAll)
$footerPanel.Controls.Add($refreshBtn)
$footerPanel.Controls.Add($openFolder)
$footerPanel.Controls.Add($openDashboard)

$liveStart.Add_Click({
    if (-not (Test-RequiredFile -Path $venvPython) -or -not (Test-RequiredFile -Path $liveScript)) {
        [System.Windows.Forms.MessageBox]::Show("Missing Python venv or oracle_live.py", "Oracle Launcher Pro")
        return
    }
    Start-ServiceProcess -Label "Oracle Live" -FilePath $venvPython -Arguments @($liveScript) -ScriptName "oracle_live.py"
    Start-Sleep -Milliseconds 600
    Update-StatusLabels
})

$liveStop.Add_Click({
    Stop-ServiceProcess -ScriptName "oracle_live.py"
    Start-Sleep -Milliseconds 500
    Update-StatusLabels
})

$sniperStart.Add_Click({
    if (-not (Test-RequiredFile -Path $sniperLauncher) -or -not (Test-RequiredFile -Path $sniperScript)) {
        [System.Windows.Forms.MessageBox]::Show("Missing Oracle_Sniper_Launch.bat or Oracle_Sniper.py", "Oracle Launcher Pro")
        return
    }
    Start-ServiceProcess -Label "Oracle Sniper" -FilePath $sniperLauncher -Arguments @() -ScriptName "Oracle_Sniper.py"
    Start-Sleep -Milliseconds 600
    Update-StatusLabels
})

$sniperStop.Add_Click({
    Stop-ServiceProcess -ScriptName "Oracle_Sniper.py"
    Start-Sleep -Milliseconds 500
    Update-StatusLabels
})

$appStart.Add_Click({
    if (-not (Test-RequiredFile -Path $appLauncher) -or -not (Test-RequiredFile -Path $appScript)) {
        [System.Windows.Forms.MessageBox]::Show("Missing Oracle_App_Launch.bat or Oracle_App.py", "Oracle Launcher Pro")
        return
    }
    Start-ServiceProcess -Label "Oracle App" -FilePath $appLauncher -Arguments @() -ScriptName "Oracle_App.py"
    Start-Sleep -Seconds 2
    Start-Process $appUrl | Out-Null
    Update-StatusLabels
})

$appOpen.Add_Click({
    Start-Process $appUrl | Out-Null
})

$appStop.Add_Click({
    Stop-ServiceProcess -ScriptName "Oracle_App.py"
    Start-Sleep -Milliseconds 500
    Update-StatusLabels
})

$startAll.Add_Click({
    $liveStart.PerformClick()
    $sniperStart.PerformClick()
    $appStart.PerformClick()
})

$stopAll.Add_Click({
    Stop-ServiceProcess -ScriptName "oracle_live.py"
    Stop-ServiceProcess -ScriptName "Oracle_Sniper.py"
    Stop-ServiceProcess -ScriptName "Oracle_App.py"
    Start-Sleep -Milliseconds 700
    Update-StatusLabels
})

$refreshBtn.Add_Click({
    Update-StatusLabels
})

$openFolder.Add_Click({
    Start-Process explorer.exe $baseDir | Out-Null
})

$openDashboard.Add_Click({
    Start-Process $appUrl | Out-Null
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 3000
$timer.Add_Tick({
    Update-StatusLabels
})
$timer.Start()

$form.Add_Shown({
    Update-StatusLabels
})

[void]$form.ShowDialog()
