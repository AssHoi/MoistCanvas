$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistDir = Join-Path $Root "dist"
$StageRoot = Join-Path $DistDir "_clean_stage"
$PackageName = "MoistCanvas"
$StageDir = Join-Path $StageRoot $PackageName
$ZipPath = Join-Path $DistDir "MoistCanvas-Clean.zip"

$RequiredItems = @(
    "main.py",
    "requirements.txt",
    "README.md",
    "README-FIRST.txt",
    "static",
    "data\api_providers.json"
)

foreach ($Item in $RequiredItems) {
    $Path = Join-Path $Root $Item
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required item is missing: $Item"
    }
}

$BatFiles = Get-ChildItem -LiteralPath $Root -Filter "*.bat" -File
$InstallBat = $BatFiles | Where-Object { Select-String -LiteralPath $_.FullName -Pattern "MoistCanvas - installer" -Quiet }
$RunBat = $BatFiles | Where-Object { Select-String -LiteralPath $_.FullName -Pattern "MoistCanvas - run" -Quiet }

if (-not $InstallBat) {
    throw "Installer BAT file was not found."
}
if (-not $RunBat) {
    throw "Run BAT file was not found."
}

if (Test-Path -LiteralPath $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

function Copy-CleanItem {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    $Source = Join-Path $Root $RelativePath
    $Destination = Join-Path $StageDir $RelativePath
    $DestinationParent = Split-Path -Parent $Destination

    if ($DestinationParent -and -not (Test-Path -LiteralPath $DestinationParent)) {
        New-Item -ItemType Directory -Force -Path $DestinationParent | Out-Null
    }

    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Copy-CleanFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationName
    )

    $Destination = Join-Path $StageDir $DestinationName
    Copy-Item -LiteralPath $SourcePath -Destination $Destination -Force
}

foreach ($Item in $RequiredItems) {
    Copy-CleanItem -RelativePath $Item
}
Copy-CleanFile -SourcePath $InstallBat.FullName -DestinationName $InstallBat.Name
Copy-CleanFile -SourcePath $RunBat.FullName -DestinationName $RunBat.Name
Copy-CleanItem -RelativePath "scripts\build_clean_zip.ps1"

$ForbiddenPatterns = @(
    "\\.git(\\|$)",
    "API\\.env$",
    "(^|\\)\\.env$",
    "(^|\\)runtime(\\|$)",
    "(^|\\)output(\\|$)",
    "(^|\\)history\\.json$",
    "data\\canvases_v2(\\|$)",
    "data\\.*_cache\\.json$",
    "\\.log$",
    "__pycache__(\\|$)"
)

$StageFiles = Get-ChildItem -LiteralPath $StageDir -Recurse -Force
foreach ($File in $StageFiles) {
    $Relative = $File.FullName.Substring($StageDir.Length).TrimStart("\")
    foreach ($Pattern in $ForbiddenPatterns) {
        if ($Relative -match $Pattern) {
            throw "Forbidden file included in clean package: $Relative"
        }
    }
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive -LiteralPath $StageDir -DestinationPath $ZipPath -Force
Remove-Item -LiteralPath $StageRoot -Recurse -Force

Write-Host "Clean package created:"
Write-Host $ZipPath
