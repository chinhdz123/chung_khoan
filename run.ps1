param(
    [string]$EnvName = "kyluat-dautu",
    [int]$Port = 8000,
    [switch]$NoRun
)

$ErrorActionPreference = "Stop"

function Write-Step($message) {
    Write-Host "[KyLuatDauTu] $message" -ForegroundColor Cyan
}

function Test-CondaAvailable {
    $cmd = Get-Command conda -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

function Ensure-EnvFile($backendDir) {
    $envFile = Join-Path $backendDir ".env"
    $envExample = Join-Path $backendDir ".env.example"
    if (!(Test-Path $envFile) -and (Test-Path $envExample)) {
        Copy-Item $envExample $envFile
        Write-Step "Da tao .env tu .env.example"
    }
}

function Start-WithConda($backendDir, $envName, $port, $noRun) {
    Write-Step "Phat hien conda, uu tien su dung conda env '$envName'"

    $envList = conda env list --json | ConvertFrom-Json
    $exists = $false
    foreach ($path in $envList.envs) {
        if ((Split-Path $path -Leaf) -eq $envName) {
            $exists = $true
            break
        }
    }

    if (-not $exists) {
        Write-Step "Chua co env '$envName', tao moi (python=3.12)..."
        conda create -y -n $envName python=3.12 | Out-Host
    }

    Write-Step "Cai dependencies (neu da co se bo qua)..."
    conda run -n $envName --no-capture-output python -m pip install -r "$backendDir\requirements.txt"

    Ensure-EnvFile $backendDir

    if ($noRun) {
        Write-Step "Da setup xong (NoRun=true), khong khoi dong server."
        return
    }

    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    Write-Step "Khoi dong server tai http://localhost:$port"
    Push-Location $backendDir
    try {
        conda run -n $envName --no-capture-output python -m uvicorn app.main:app --reload --host 0.0.0.0 --port $port
    }
    finally {
        Pop-Location
    }
}

function Start-WithVenvFallback($backendDir, $port, $noRun) {
    Write-Step "Khong tim thay conda, fallback sang python venv"
    $venvDir = Join-Path $backendDir ".venv"
    $pythonExe = Join-Path $venvDir "Scripts\python.exe"

    if (!(Test-Path $pythonExe)) {
        Write-Step "Tao venv moi..."
        python -m venv $venvDir
    }

    Write-Step "Cai dependencies (neu da co se bo qua)..."
    & $pythonExe -m pip install -r "$backendDir\requirements.txt"

    Ensure-EnvFile $backendDir

    if ($noRun) {
        Write-Step "Da setup xong (NoRun=true), khong khoi dong server."
        return
    }

    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    Write-Step "Khoi dong server tai http://localhost:$port"
    Push-Location $backendDir
    try {
        & $pythonExe -m uvicorn app.main:app --reload --host 0.0.0.0 --port $port
    }
    finally {
        Pop-Location
    }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"

if (!(Test-Path $backendDir)) {
    throw "Khong tim thay thu muc backend tai: $backendDir"
}

if (Test-CondaAvailable) {
    Start-WithConda -backendDir $backendDir -envName $EnvName -port $Port -noRun:$NoRun
}
else {
    Start-WithVenvFallback -backendDir $backendDir -port $Port -noRun:$NoRun
}
