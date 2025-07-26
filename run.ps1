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

# 获取并解析内存信息（转换为 MB，整合为一行显示）
$memRaw = & wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /Format:List
$totalKB = ($memRaw | Where-Object { $_ -match "^TotalVisibleMemorySize=" }) -replace "^.*=", ""
$freeKB = ($memRaw | Where-Object { $_ -match "^FreePhysicalMemory=" }) -replace "^.*=", ""

if ($totalKB -and $freeKB) {
    $totalMB = [math]::Round($totalKB / 1024)
    $usedMB = [math]::Round(($totalKB - $freeKB) / 1024)
    Write-Host "System Memory: ${usedMB}MB used of ${totalMB}MB" -ForegroundColor Cyan
} else {
    Write-Host "System Memory: Failed to retrieve." -ForegroundColor Red
}


# 获取 GPU 信息（整合为单行）
Write-Host "GPU Info: " -NoNewline -ForegroundColor Cyan
& $pythonExe -c "import torch; props = torch.cuda.get_device_properties(0); used = torch.cuda.memory_allocated(0)//(1024**2); total = props.total_memory//(1024**2); print(f'{props.name}, {used}MB used of {total}MB')"


$uvicornArgs = @(
    "src.api.main:app"
    ,"--host", "0.0.0.0"
    ,"--port", $Port.ToString()
    # ,"--reload"
)

Write-Host "Starting Automatic video editing on port $Port..." -ForegroundColor Green
& $pythonExe -m uvicorn @uvicornArgs

Read-Host "Press any key to exit"
