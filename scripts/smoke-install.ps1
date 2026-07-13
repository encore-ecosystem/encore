param(
    [Parameter(Mandatory = $true)]
    [string]$Archive
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$archivePath = (Resolve-Path $Archive).Path
$checksumPath = "$archivePath.sha256"
if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
    throw "Archive checksum is required: $checksumPath"
}

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("encore-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
$previousHome = $env:ENCORE_HOME
$previousVersion = $env:ENCORE_VERSION
$previousBase = $env:ENCORE_RELEASE_BASE_URL
try {
    $installRoot = Join-Path $temp "home"
    $archiveDirectory = Split-Path -Parent $archivePath
    $inspectRoot = Join-Path $temp "inspect"
    Expand-Archive $archivePath $inspectRoot
    $inspectPackage = Get-ChildItem $inspectRoot -Directory | Select-Object -First 1
    if (-not $inspectPackage) { throw "Release archive is empty" }
    $packageVersion = Get-Content (Join-Path $inspectPackage.FullName "VERSION")
    $env:ENCORE_HOME = $installRoot
    $env:ENCORE_VERSION = $packageVersion
    $env:ENCORE_RELEASE_BASE_URL = ([System.Uri]$archiveDirectory).AbsoluteUri
    & (Join-Path $repoRoot "install.ps1")

    $compiler = Join-Path $installRoot "bin/encore.exe"
    & $compiler --version

    $env:ENCORE_HOME = Join-Path $temp "home-v-prefix"
    $env:ENCORE_VERSION = "v$packageVersion"
    & (Join-Path $repoRoot "install.ps1")
    & (Join-Path $env:ENCORE_HOME "bin/encore.exe") --version

    $env:ENCORE_HOME = Join-Path $temp "mismatch"
    $env:ENCORE_VERSION = "wrong-version"
    try {
        & (Join-Path $repoRoot "install.ps1")
        throw "Installer accepted an archive with the wrong version"
    } catch {
        if ($_.Exception.Message -notlike "*Release version mismatch*") { throw }
    }
    $env:ENCORE_HOME = $installRoot
    $env:ENCORE_VERSION = $packageVersion

    $project = Join-Path $temp "project"
    Copy-Item -Recurse (Join-Path $repoRoot "examples/add_two_structs") $project
    Remove-Item -Recurse -Force (Join-Path $project "target") -ErrorAction SilentlyContinue
    Push-Location $project
    try {
        & $compiler build --profile debug
        if ($LASTEXITCODE -ne 0) { throw "Installed compiler failed to build smoke project" }
        & (Join-Path $project "target/debug/add_two_structs.exe")
        if ($LASTEXITCODE -ne 12) {
            throw "Smoke binary returned $LASTEXITCODE instead of 12"
        }
    } finally {
        Pop-Location
    }
} finally {
    $env:ENCORE_HOME = $previousHome
    $env:ENCORE_VERSION = $previousVersion
    $env:ENCORE_RELEASE_BASE_URL = $previousBase
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
}
