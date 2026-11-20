<#
.SYNOPSIS
Installs the application silently, starts it and removes it again.

.DESCRIPTION
With -PreviousSetup that installer runs first, into the same folder, so the
check covers an upgrade: files the previous version shipped and the new one
does not must not keep the new version from starting.
#>
param(
    [Parameter(Mandatory = $true)] [string] $Setup,
    [Parameter(Mandatory = $true)] [string] $Target,
    [string] $PreviousSetup
)

$ErrorActionPreference = 'Stop'

function Install-Setup([string] $Path) {
    $arguments = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/DIR="' + $Target + '"'))
    $process = Start-Process -FilePath $Path -Wait -PassThru -ArgumentList $arguments
    if ($process.ExitCode -ne 0) { throw "Installer $Path exited with code $($process.ExitCode)." }
    Write-Host "Installed $(Split-Path -Leaf $Path) into $Target"
}

function Show-BundledFolders {
    $internal = Join-Path $Target '_internal'
    if (Test-Path -LiteralPath $internal) {
        $names = (Get-ChildItem -LiteralPath $internal -Directory | ForEach-Object Name) -join ', '
        Write-Host "Folders in _internal: $names"
    }
}

function Test-Application {
    $exe = Join-Path $Target 'CISProbePlacementScriptor.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw "The installer did not install $exe" }
    $env:CIS_PROBE_SMOKE_LOG = Join-Path $env:RUNNER_TEMP 'installed-start-up-check.log'
    Remove-Item -LiteralPath $env:CIS_PROBE_SMOKE_LOG -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $exe -ArgumentList '--smoke' -PassThru
    $null = $process.Handle
    # A start-up that fails before the check begins shows an error window and waits.
    if (-not $process.WaitForExit(90000)) {
        $process.Kill()
        throw "The installed application did not finish its start-up check: it is waiting on an error window."
    }
    if ($process.ExitCode -ne 0) {
        if (Test-Path -LiteralPath $env:CIS_PROBE_SMOKE_LOG) { Get-Content -LiteralPath $env:CIS_PROBE_SMOKE_LOG }
        throw "The installed application failed its start-up check with exit code $($process.ExitCode)."
    }
    Write-Host 'The installed application started.'
}

function Remove-Application {
    $uninstaller = Get-ChildItem -LiteralPath $Target -Filter 'unins*.exe' | Select-Object -First 1
    if (-not $uninstaller) { throw "Missing uninstaller in $Target" }
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
    $process = Start-Process -FilePath $uninstaller.FullName -Wait -PassThru -ArgumentList $arguments
    if ($process.ExitCode -ne 0) { throw "The uninstaller exited with code $($process.ExitCode)." }
    Write-Host 'Uninstalled.'
}

if ($PreviousSetup) {
    Install-Setup $PreviousSetup
    Show-BundledFolders
}
Install-Setup $Setup
Show-BundledFolders
try {
    Test-Application
}
finally {
    Remove-Application
}
