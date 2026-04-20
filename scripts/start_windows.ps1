$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$RuntimeDir = Join-Path $RepoRoot ".runtime"
$UvDir = Join-Path $RuntimeDir "uv"
$UvExe = Join-Path $UvDir "uv.exe"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$TempDir = Join-Path $RuntimeDir "temp"
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
    "socket in a way forbidden by its access permissions",
    "ssl handshake",
    "tls handshake",
    "winerror 10013"
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
        $Arguments = @()
        if ($Command.Length -gt 1) {
            $Arguments = @($Command[1..($Command.Length - 1)])
        }

        $HasNativeCommandPreference = Test-Path Variable:\PSNativeCommandUseErrorActionPreference
        if ($HasNativeCommandPreference) {
            $PreviousNativeCommandPreference = $PSNativeCommandUseErrorActionPreference
        }

        $PreviousErrorActionPreference = $ErrorActionPreference
        try {
            if ($HasNativeCommandPreference) {
                $PSNativeCommandUseErrorActionPreference = $false
            }

            $ErrorActionPreference = "Continue"
            $Output = & $Command[0] @Arguments 2>&1
            $ExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $PreviousErrorActionPreference
            if ($HasNativeCommandPreference) {
                $PSNativeCommandUseErrorActionPreference = $PreviousNativeCommandPreference
            }
        }

        $OutputText = @(
            foreach ($Item in @($Output)) {
                if ($null -eq $Item) {
                    continue
                }

                if ($Item -is [System.Management.Automation.ErrorRecord]) {
                    $Text = $Item.Exception.Message
                }
                else {
                    $Text = [string]$Item
                }

                if ($Text) {
                    $Text.TrimEnd("`r", "`n")
                }
            }
        ) -join [Environment]::NewLine

        if ($OutputText) {
            Write-Host $OutputText
        }

        if ($ExitCode -ne 0) {
            throw "Command failed with exit code $ExitCode.`n$OutputText"
        }
    }
}

function Get-Python312Path {
    $Candidates = @()

    if ($env:LOCALAPPDATA) {
        $Candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    }

    foreach ($RegistryPath in @(
        "HKCU:\Software\Python\PythonCore\3.12\InstallPath",
        "HKLM:\Software\Python\PythonCore\3.12\InstallPath",
        "HKLM:\Software\WOW6432Node\Python\PythonCore\3.12\InstallPath"
    )) {
        try {
            $InstallRoot = (Get-Item $RegistryPath -ErrorAction Stop).GetValue("")
            if ($InstallRoot) {
                $Candidates += (Join-Path $InstallRoot "python.exe")
            }
        }
        catch {
        }
    }

    foreach ($Candidate in $Candidates | Select-Object -Unique) {
        if (-not $Candidate -or -not (Test-Path $Candidate)) {
            continue
        }

        try {
            $Handle = [System.IO.File]::Open($Candidate, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            $Handle.Dispose()
            return $Candidate
        }
        catch {
        }
    }

    return $null
}

function Install-LocalUv {
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    $env:UV_UNMANAGED_INSTALL = $UvDir
    Invoke-WithInternetRetry "Installing local uv" {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
}

try {
    if (-not (Test-Path $UvExe)) {
        Write-Host "Installing local uv..."
        Install-LocalUv
    }

    New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
    $env:UV_CACHE_DIR = Join-Path $RuntimeDir "uv-cache"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeDir "python"
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $RepoRoot ".playwright"
    $env:TEMP = $TempDir
    $env:TMP = $TempDir
    $env:TMPDIR = $TempDir

    if (-not (Test-Path $VenvPython)) {
        Write-Host "Creating project virtual environment..."
        $PythonSpecifier = Get-Python312Path
        if (-not $PythonSpecifier) {
            $PythonSpecifier = "3.12"
        }

        $VenvCommand = @(
            $UvExe,
            "venv",
            (Join-Path $RepoRoot ".venv"),
            "--python",
            $PythonSpecifier,
            "--seed",
            "--clear"
        )
        if ($PythonSpecifier -ne "3.12") {
            $VenvCommand += "--no-python-downloads"
        }

        Invoke-ExternalWithInternetRetry "Creating the project virtual environment" $VenvCommand
    }

    & $VenvPython (Join-Path $RepoRoot "scripts\launch.py")
    exit $LASTEXITCODE
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)"
    exit 1
}
