param(
    [int] $Port = 9001
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

$pythonExe = $null

# 检查 .venv 是否存在
$dotVenvPath = Join-Path $scriptDir ".venv"
if (Test-Path (Join-Path $dotVenvPath "Scripts\python.exe")) {
    $pythonExe = Join-Path $dotVenvPath "Scripts\python.exe"
    Write-Host "Using .venv virtual environment: $dotVenvPath" -ForegroundColor Green
    & (Join-Path $dotVenvPath "Scripts\Activate.ps1")
} else {
    # 搜索匹配 python3* 的文件夹
    $pythonDir = Get-ChildItem -Path $scriptDir -Directory | Where-Object { $_.Name -like "python3*" } | Select-Object -First 1
    if ($pythonDir -ne $null -and (Test-Path (Join-Path $pythonDir.FullName "python.exe"))) {
        $pythonExe = Join-Path $pythonDir.FullName "python.exe"
        Write-Host "Using Python directory: $pythonExe" -ForegroundColor Yellow
    } else {
        Write-Host "Error: Could not locate .venv or python3* folder with python.exe" -ForegroundColor Red
        Read-Host "Press any key to exit"
        exit 1
    }
}

# 确保 python.exe 可执行
if (-not (Test-Path $pythonExe)) {
    Write-Host "Error: python.exe not found at $pythonExe" -ForegroundColor Red
    Read-Host "Press any key to exit"
    exit 1
}

Write-Host "Python version: " -NoNewline -ForegroundColor Cyan
& $pythonExe --version

Write-Host "PyTorch version: " -NoNewline -ForegroundColor Cyan
& $pythonExe -c "import torch; print(torch.__version__)"

$uvicornArgs = @(
    "src.api.main:app",
    "--host", "0.0.0.0",
    "--port", $Port.ToString(),
    "--reload"
)

Write-Host "Starting LexiVision AI Search on port $Port..." -ForegroundColor Green
& $pythonExe -m uvicorn @uvicornArgs

Read-Host "Press any key to exit"
