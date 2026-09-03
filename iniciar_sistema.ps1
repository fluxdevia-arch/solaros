$ErrorActionPreference = "Stop"
$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectPath

$streamlitPath = Join-Path $projectPath ".venv\Scripts\streamlit.exe"
$appPath = Join-Path $projectPath "streamlit_app.py"
$logPath = Join-Path $projectPath "logs"
$stdoutPath = Join-Path $logPath "streamlit-out.log"
$stderrPath = Join-Path $logPath "streamlit-error.log"
$healthUrl = "http://127.0.0.1:8501/_stcore/health"
$appUrl = "http://localhost:8501"

if (-not (Test-Path -LiteralPath $streamlitPath)) {
    Write-Host "Ambiente do CRM nao encontrado." -ForegroundColor Red
    Write-Host "Consulte o arquivo README.md para instalar as dependencias."
    exit 1
}

New-Item -ItemType Directory -Force -Path $logPath | Out-Null

function Test-CrmHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (-not (Test-CrmHealth)) {
    Write-Host "Iniciando o SolarOS..."
    Start-Process `
        -FilePath $streamlitPath `
        -ArgumentList @("run", $appPath, "--server.port=8501", "--server.headless=true") `
        -WorkingDirectory $projectPath `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath | Out-Null

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-CrmHealth) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        Write-Host "O CRM nao iniciou. Verifique o log abaixo:" -ForegroundColor Red
        if (Test-Path -LiteralPath $stderrPath) {
            Get-Content -LiteralPath $stderrPath -Tail 30
        }
        exit 1
    }
}

Write-Host "SolarOS disponivel em $appUrl" -ForegroundColor Green
Start-Process $appUrl
exit 0
