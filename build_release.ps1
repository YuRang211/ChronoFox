<#
.SYNOPSIS
    ChronoFox v1.0 release build pipeline (planning/specs/release-v1.md P8).

.DESCRIPTION
    Fail-fast pipeline: ruff -> fast-lane pytest -> PyInstaller -> (Inno Setup,
    if available) -> portable zip (with README.txt) -> SHA256 checksums.
    Stops at the first failing step so a broken build never produces
    release artifacts.

.PARAMETER Version
    Release version string used in artifact filenames (default: 1.0.0).

.PARAMETER SkipInno
    Skip the Inno Setup installer step even if iscc.exe is found.

.EXAMPLE
    .\build_release.ps1
    .\build_release.ps1 -Version 1.0.0 -SkipInno
#>

[CmdletBinding()]
param(
    [string]$Version = "1.0.0",
    [switch]$SkipInno
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

function Invoke-Gate {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Action
    )
    Write-Host ""
    Write-Host "==== $Name ====" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit code $LASTEXITCODE)"
    }
}

try {
    # 1. Lint gate
    Invoke-Gate "ruff check" {
        python -m ruff check .
    }

    # 2. Fast-lane test gate (excludes `slow`-marked tests; full suite is a
    # separate pre-merge step per CLAUDE.md, not part of this pipeline)
    Invoke-Gate "pytest (fast lane)" {
        $env:QT_QPA_PLATFORM = "offscreen"
        python -m pytest -m "not slow" -q --basetemp="$env:TEMP\cf_release"
    }

    # 3. PyInstaller onedir build (모든 산출물은 out\ 하위로 — repo-layout-v1 B단계)
    Invoke-Gate "PyInstaller build" {
        if (Test-Path "out\dist\ChronoFox") { Remove-Item -Recurse -Force "out\dist\ChronoFox" }
        if (Test-Path "out\build\chronofox") { Remove-Item -Recurse -Force "out\build\chronofox" }
        python -m PyInstaller chronofox.spec --noconfirm --workpath "out\build" --distpath "out\dist"
    }
    if (-not (Test-Path "out\dist\ChronoFox\ChronoFox.exe")) {
        throw "PyInstaller build did not produce out\dist\ChronoFox\ChronoFox.exe"
    }

    # 4. Inno Setup installer (optional: skipped if iscc.exe isn't installed)
    $IsccPath = $null
    if (-not $SkipInno) {
        $isccCmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
        if ($isccCmd) {
            $IsccPath = $isccCmd.Source
        } else {
            foreach ($candidate in @(
                "${Env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "${Env:ProgramFiles}\Inno Setup 6\ISCC.exe"
            )) {
                if ($candidate -and (Test-Path $candidate)) { $IsccPath = $candidate; break }
            }
        }
    }
    if ($IsccPath) {
        Invoke-Gate "Inno Setup compile" {
            & $IsccPath "installer\chronofox.iss" "/DMyAppVersion=$Version"
        }
    } else {
        Write-Warning "Inno Setup (iscc.exe) not found - skipping installer build. Install Inno Setup 6 (https://jrsoftware.org/isinfo.php) to produce ChronoFox-$Version-Setup.exe, or pass -SkipInno to silence this warning."
    }

    # 5. Portable zip (onedir output + README.txt)
    $releaseDir = "out\release"
    Invoke-Gate "portable zip" {
        if (Test-Path $releaseDir) { Remove-Item -Recurse -Force $releaseDir }
        New-Item -ItemType Directory -Path $releaseDir | Out-Null

        $portableName = "ChronoFox-$Version-portable"
        $portableStage = Join-Path $releaseDir $portableName
        New-Item -ItemType Directory -Path $portableStage | Out-Null
        Copy-Item -Recurse "out\dist\ChronoFox\*" $portableStage

        $readmeText = @"
ChronoFox $Version - Portable (무설치 버전)

[실행법 / How to run]
ChronoFox.exe를 더블클릭해 실행하세요. 별도 설치가 필요 없습니다.
Double-click ChronoFox.exe to run. No installation required.

[데이터 위치 / Data location]
%USERPROFILE%\.desktop_note_calendar
(config.json, data.json, Notes\, logs\ 등 앱 데이터가 저장됩니다.)
(config.json, data.json, Notes\, logs\, and other app data live here.)

이 폴더를 백업하거나 다른 PC의 같은 경로로 복사하면 데이터를 그대로
이어서 사용할 수 있습니다. 이 portable 폴더 자체를 지워도 위 데이터
폴더는 남아 있습니다.

Back up or copy that folder to the same path on another PC to carry your
data over. Deleting this portable folder does not delete your data.

[SmartScreen 안내 / SmartScreen notice]
ChronoFox는 아직 코드 서명이 되어 있지 않아, 처음 실행할 때 Windows
SmartScreen이 "알 수 없는 게시자" 경고를 보여줄 수 있습니다. 이 경우
"추가 정보(More info)" -> "실행(Run anyway)"을 선택하면 정상적으로
실행됩니다. (코드 서명은 이후 버전에서 검토 중입니다.)

ChronoFox is not code-signed yet, so Windows SmartScreen may show an
"Unknown publisher" warning the first time you run it. Click
"More info" -> "Run anyway" to proceed. (Code signing is under
evaluation for a future release.)
"@
        Set-Content -Path (Join-Path $portableStage "README.txt") -Value $readmeText -Encoding UTF8

        $zipPath = Join-Path $releaseDir "$portableName.zip"
        if (Test-Path $zipPath) { Remove-Item $zipPath }
        Compress-Archive -Path "$portableStage\*" -DestinationPath $zipPath -CompressionLevel Optimal
        Write-Host "Portable zip: $zipPath"
    }

    # 6. SHA256 checksums for every release artifact produced above
    Invoke-Gate "SHA256 checksums" {
        $targets = @(Get-ChildItem $releaseDir -Filter "*.zip" -ErrorAction SilentlyContinue)
        if (Test-Path "installer\Output") {
            $targets += @(Get-ChildItem "installer\Output" -Filter "*.exe" -ErrorAction SilentlyContinue)
        }
        if ($targets.Count -eq 0) {
            throw "No release artifacts found to checksum"
        }
        $checksumPath = Join-Path $releaseDir "SHA256SUMS.txt"
        $lines = foreach ($file in $targets) {
            $hash = Get-FileHash -Algorithm SHA256 -Path $file.FullName
            "$($hash.Hash.ToLower())  $($file.Name)"
        }
        Set-Content -Path $checksumPath -Value $lines -Encoding ASCII
        Write-Host "Checksums written to $checksumPath"
        $lines | ForEach-Object { Write-Host "  $_" }
    }

    Write-Host ""
    Write-Host "Release build complete. Artifacts in .\out\release\ (+ .\installer\Output\ if Inno Setup ran)." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "BUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
