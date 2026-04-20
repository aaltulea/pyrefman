$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$RuntimeDir = Join-Path $RepoRoot ".runtime"
$UvDir = Join-Path $RuntimeDir "uv"
$UvExe = Join-Path $UvDir "uv.exe"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$InternetRetryTimeoutSeconds = 300
$InternetRetryDelaySeconds = 5
$InternetErrorPatterns = @(
    "unable to connect to the remote server",
    "no such host is known",
    "the remote name could not be resolved",
    "network is unreachable",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "failed to download",
    "forbidden by its access permissions",
    "socket in a way forbidden by its access permissions",
    "ssl handshake",
    "tls handshake",
    "eacces"
)

function Test-InternetErrorText {
    param([string]$Text)

    $Normalized = ($Text | Out-String).ToLowerInvariant()
    foreach ($Pattern in $InternetErrorPatterns) {
        if ($Normalized.Contains($Pattern.ToLowerInvariant())) {
            return $true
        }
    }

    return $false
}

function Invoke-WithInternetRetry {
    param(
        [string]$StepName,
        [scriptblock]$Action
    )

    $Deadline = (Get-Date).AddSeconds($InternetRetryTimeoutSeconds)
    $Attempt = 1

    while ($true) {
        try {
            & $Action
            return
        }
        catch {
            $Message = $_ | Out-String
            if (-not (Test-InternetErrorText $Message)) {
                throw
            }

            if ((Get-Date) -ge $Deadline) {
                throw "$StepName kept failing due to missing internet access or a firewall block for 5 minutes.`n$Message"
            }

            $Remaining = [Math]::Max(0, [int](($Deadline - (Get-Date)).TotalSeconds))
            Write-Host "[WARNING] $StepName appears blocked by missing internet access or a firewall rule. Retrying in $InternetRetryDelaySeconds seconds (attempt $Attempt, up to $Remaining`s remaining)..."
            Start-Sleep -Seconds $InternetRetryDelaySeconds
            $Attempt += 1
        }
    }
}

function Invoke-ExternalWithInternetRetry {
    param(
        [string]$StepName,
        [string[]]$Command
    )

    Invoke-WithInternetRetry $StepName {
        $Output = & $Command[0] @($Command[1..($Command.Length - 1)]) 2>&1
        $ExitCode = $LASTEXITCODE
        if ($Output) {
            $Output | ForEach-Object { Write-Host $_ }
        }

        if ($ExitCode -ne 0) {
            $Message = $Output | Out-String
            throw "Command failed with exit code $ExitCode.`n$Message"
        }
    }
}

function Install-LocalUv {
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    $env:UV_UNMANAGED_INSTALL = $UvDir
    Invoke-WithInternetRetry "Installing local uv" {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
}

if (-not (Test-Path $UvExe)) {
    Write-Host "Installing local uv..."
    Install-LocalUv
}

$env:UV_CACHE_DIR = Join-Path $RuntimeDir "uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeDir "python"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $RepoRoot ".playwright"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating project virtual environment..."
    Invoke-ExternalWithInternetRetry "Creating the project virtual environment" @(
        $UvExe,
        "venv",
        (Join-Path $RepoRoot ".venv"),
        "--python",
        "3.12",
        "--seed"
    )
}

& $VenvPython (Join-Path $RepoRoot "scripts\launch.py")
exit $LASTEXITCODE
