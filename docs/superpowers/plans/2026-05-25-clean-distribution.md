# Clean Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable clean ZIP package for sharing MoistCanvas with other users.

**Architecture:** Add a small PowerShell packaging script that copies an explicit allowlist into a temporary staging folder, then compresses it into `dist/MoistCanvas-Clean.zip`. Update user-facing documentation so recipients know how to install, run, and configure API keys locally.

**Tech Stack:** PowerShell, Windows batch files, Python FastAPI app, static frontend assets.

---

## File Structure

- Create `scripts/build_clean_zip.ps1`: validates required project files, stages the clean allowlist, creates the ZIP, and checks for forbidden paths.
- Modify `README.md`: replace unreadable mojibake with Chinese usage and packaging instructions.
- Modify `README-FIRST.txt`: provide concise first-run instructions for recipients.
- Generate `dist/MoistCanvas-Clean.zip`: clean distributable artifact.

### Task 1: Packaging Script

**Files:**
- Create: `scripts/build_clean_zip.ps1`

- [ ] **Step 1: Create the script with an allowlist and forbidden-path validation**

```powershell
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
    "安装依赖.bat",
    "运行文件.bat",
    "static",
    "data\api_providers.json"
)

foreach ($Item in $RequiredItems) {
    $Path = Join-Path $Root $Item
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required item is missing: $Item"
    }
}

if (Test-Path -LiteralPath $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

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

foreach ($Item in $RequiredItems) {
    Copy-CleanItem -RelativePath $Item
}
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
```

- [ ] **Step 2: Run the script**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_clean_zip.ps1`

Expected: `dist\MoistCanvas-Clean.zip` is created.

### Task 2: Documentation

**Files:**
- Modify: `README.md`
- Modify: `README-FIRST.txt`

- [ ] **Step 1: Rewrite README in readable Chinese**

Include sections for what MoistCanvas is, ordinary Windows usage, requirements, local data, clean ZIP generation, and developer startup.

- [ ] **Step 2: Rewrite README-FIRST for package recipients**

Keep it short: extract ZIP, run installer, run app, open browser, set API key, close run window to stop.

### Task 3: Verification

**Files:**
- Verify: `dist/MoistCanvas-Clean.zip`

- [ ] **Step 1: List ZIP contents**

Run: `powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::OpenRead('dist\MoistCanvas-Clean.zip').Entries.FullName"`

Expected: entries start with `MoistCanvas/` and include app files.

- [ ] **Step 2: Check forbidden content**

Run: `powershell -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; $bad = [IO.Compression.ZipFile]::OpenRead('dist\MoistCanvas-Clean.zip').Entries.FullName | Where-Object { $_ -match '(^|/)MoistCanvas/(API/\\.env|\\.env|runtime/|output/|history\\.json|data/canvases_v2/|data/.*_cache\\.json|.*\\.log|\\.git/|.*__pycache__/)' }; if ($bad) { $bad; exit 1 } else { 'No forbidden files found.' }"`

Expected: `No forbidden files found.`
