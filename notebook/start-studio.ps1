$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$configPath = Join-Path $root "notebook\config.local.json"
$port = 8765
if (Test-Path -LiteralPath $configPath) {
    $configured = (Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).listen_port
    if ($configured -is [int] -and $configured -ge 1024 -and $configured -le 65535) { $port = $configured }
}
$url = "http://127.0.0.1:$port/"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Starte zuerst notebook\install-studio.ps1, um Studio einzurichten." }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    $codexBins = @(Get-ChildItem -Path "$env:LOCALAPPDATA\OpenAI\Codex\bin\*\codex.exe" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($codexBins.Count -gt 0) { $env:PATH = (Split-Path -Parent $codexBins[0].FullName) + ";" + $env:PATH }
}
$running = $false
try {
    $response = Invoke-WebRequest -Uri ($url + "api/profile") -Method Get -TimeoutSec 2 -UseBasicParsing
    $running = $response.StatusCode -eq 200 -and (($response.Content | ConvertFrom-Json).PSObject.Properties.Name -contains "profile")
} catch {}
if (-not $running) {
    $env:PYTHONPATH = Join-Path $root "notebook"
    Start-Process -FilePath $python -ArgumentList "-m", "studio.web" -WindowStyle Hidden -WorkingDirectory $root
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri ($url + "api/profile") -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200 -and (($response.Content | ConvertFrom-Json).PSObject.Properties.Name -contains "profile")) { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show("Studio konnte nicht starten. Starte den Installer in Codex erneut. Vorhandene Entwürfe bleiben erhalten.", "Studio") | Out-Null
        exit 1
    }
}
Start-Process $url
