param([switch]$NoLaunch)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $PSScriptRoot "config.local.json"
$startScript = Join-Path $PSScriptRoot "start-studio.ps1"

$venv = Join-Path $PSScriptRoot ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Find-StudioPython {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidate = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0) { $candidates += $candidate }
    }
    $candidates += @(Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    foreach ($candidate in $candidates) {
        $supported = & $candidate -c "import sys; print('yes' if sys.version_info >= (3, 11) else 'no')"
        if ($supported -eq "yes") { return $candidate }
    }
    return $null
}
$systemPython = Find-StudioPython
if (-not $systemPython) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python fehlt. Installiere Python 3.12 von python.org und starte diesen Installer erneut."
    }
    Write-Host "Python wird für dieses Windows-Konto installiert."
    & winget install --id Python.Python.3.12 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python konnte nicht installiert werden. Starte den Installer nach der Python-Installation erneut." }
    $systemPython = Find-StudioPython
    if (-not $systemPython) { throw "Python wurde noch nicht gefunden. Öffne Codex neu und starte den Installer erneut." }
}
if (-not (Test-Path -LiteralPath $python)) {
    & $systemPython -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Die Python-Umgebung konnte nicht angelegt werden." }
}
& $python -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Die Python-Pakete konnten nicht installiert werden. Prüfe die Internetverbindung und starte erneut." }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw "Die Python-Pakete passen noch nicht zusammen." }

# Never import another person's local configuration or data.
if (-not (Test-Path -LiteralPath $configPath)) {
    $initial = @{ server_base_url = "https://www.starseven.at"; listen_port = 8765; accounts = @{} }
    [IO.File]::WriteAllText($configPath, ($initial | ConvertTo-Json -Depth 4), $utf8)
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Studio.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $startScript + '"'
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = "Instagram Studio starten"
$shortcut.Save()

Write-Host "Studio ist installiert. Die Desktop-Verknüpfung öffnet deinen persönlichen Einrichtungsassistenten."
if (-not $NoLaunch) { & $startScript }
