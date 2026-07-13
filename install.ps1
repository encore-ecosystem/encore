param(
    [string]$Version = $env:ENCORE_VERSION,
    [string]$InstallRoot = $env:ENCORE_HOME,
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
if (-not $InstallRoot) { $InstallRoot = Join-Path $HOME ".encore" }
if (-not $Version) { $Version = "latest" }
if ($Uninstall) {
    Remove-Item -Recurse -Force $InstallRoot -ErrorAction SilentlyContinue
    Write-Host "Removed Encore from $InstallRoot"
    exit 0
}

$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
switch ($arch) {
    "x64" { $triple = "x86_64-pc-windows-msvc" }
    "arm64" { $triple = "aarch64-pc-windows-msvc" }
    default { throw "Unsupported architecture: $arch" }
}
$repository = if ($env:ENCORE_REPOSITORY) { $env:ENCORE_REPOSITORY } else { "encore-language/encore" }
$base = if ($Version -eq "latest") {
    "https://github.com/$repository/releases/latest/download"
} else {
    "https://github.com/$repository/releases/download/$Version"
}
$asset = "encore-$triple.zip"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("encore-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    Invoke-WebRequest "$base/$asset" -OutFile (Join-Path $temp $asset)
    Invoke-WebRequest "$base/$asset.sha256" -OutFile (Join-Path $temp "$asset.sha256")
    $expected = ((Get-Content (Join-Path $temp "$asset.sha256")) -split "\s+")[0].ToLowerInvariant()
    $actual = (Get-FileHash (Join-Path $temp $asset) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw "Checksum verification failed" }
    $unpack = Join-Path $temp "unpack"
    Expand-Archive (Join-Path $temp $asset) $unpack
    $package = Get-ChildItem $unpack -Directory | Select-Object -First 1
    if (-not $package) { throw "Release archive is empty" }
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    @("bin", "lib", "share", "VERSION") | ForEach-Object {
        Remove-Item -Recurse -Force (Join-Path $InstallRoot $_) -ErrorAction SilentlyContinue
        Copy-Item -Recurse -Force (Join-Path $package.FullName $_) $InstallRoot
    }
    Write-Host "Installed Encore $(Get-Content (Join-Path $InstallRoot 'VERSION')) in $InstallRoot"
    Write-Host "Add $InstallRoot\bin to PATH"
} finally {
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
}
