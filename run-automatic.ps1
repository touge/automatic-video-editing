# run Lexi Vision Ai

param(
    [int] $Port = 9001   # default port, can be overridden by -Port 参数
)

# Ensure console uses UTF-8 encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Switch to script directory so that tts_api package is found
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# Locate the python.exe in your python3.12.8 folder or a virtual environment
# Prioritize virtual environment if it exists
$venvPath = Join-Path $scriptDir "venv" # Common virtual environment name
$envPath = Join-Path $scriptDir "env"   # Another common virtual environment name

$pythonExe = $null

if (Test-Path (Join-Path $venvPath "Scripts\python.exe")) {
    $pythonExe = Join-Path $venvPath "Scripts\python.exe"
    Write-Host "Using virtual environment: $venvPath" -ForegroundColor Green
    # Activate the virtual environment
    & (Join-Path $venvPath "Scripts\Activate.ps1")
} elseif (Test-Path (Join-Path $envPath "Scripts\python.exe")) {
    $pythonExe = Join-Path $envPath "Scripts\python.exe"
    Write-Host "Using virtual environment: $envPath" -ForegroundColor Green
    # Activate the virtual environment
    & (Join-Path $envPath "Scripts\Activate.ps1")
} elseif (Test-Path (Join-Path $scriptDir "python3.12.8\python.exe")) {
    $pythonExe = Join-Path $scriptDir "python3.12.8\python.exe"
    Write-Host "Using hardcoded Python path: $pythonExe" -ForegroundColor Yellow
} else {
    Write-Host "Error: python.exe not found in 'venv', 'env' or 'python3.12.8' subdirectories." -ForegroundColor Red
    Write-Host "Please ensure Python 3.12.8 is installed or a virtual environment is set up." -ForegroundColor Red
    Read-Host "Press any key to exit"
    exit 1
}

if (-not (Test-Path $pythonExe)) {
    Write-Host "Error: python.exe not found at $pythonExe" -ForegroundColor Red
    Read-Host "Press any key to exit"
    exit 1
}

# Show Python version
Write-Host "Python version: " -NoNewline -ForegroundColor Cyan
& $pythonExe --version

# Show PyTorch version
Write-Host "PyTorch version: " -NoNewline -ForegroundColor Cyan
& $pythonExe -c "import torch; print(torch.__version__)"

# Build uvicorn argument array using dynamic $Port
$uvicornArgs = @(
    "src.api.main:app",
    "--host", "0.0.0.0",
    "--port", $Port.ToString()
    # "--reload"
)

# Launch the FastAPI app via uvicorn
Write-Host "Starting LexiVision AI Search on port $Port..." -ForegroundColor Green
& $pythonExe -m uvicorn @uvicornArgs # Use python -m uvicorn

# Pause to keep window open
Read-Host "Press any key to exit"
