<#
.SYNOPSIS
    ChronoFox release build pipeline (planning/PROJECT.md §9).

.DESCRIPTION
    Fail-fast pipeline: ruff -> fast-lane pytest -> PyInstaller -> (Inno Setup,
    if available) -> portable zip (with README.txt) -> SHA256 checksums.
    Stops at the first failing step so a broken build never produces
    release artifacts.

.PARAMETER Version
    Release version string used in artifact filenames (default: 0.8.5).
    AUDIT-D7: default mirrors app_constants.APP_VERSION (the app-displayed version) and
    installer\chronofox.iss's MyAppVersion default -- PowerShell can't import the Python
    constant directly, so keep these three in sync by hand when bumping the version.

.PARAMETER SkipInno
    Skip the Inno Setup installer step even if iscc.exe is found.

.PARAMETER ValidateVersionOnly
    Validate all release version sources and exit before lint, tests, or builds.

.PARAMETER SignCertificateThumbprint
    Optional SHA-1 thumbprint of a code-signing certificate in the current
    user's certificate store. When supplied, ChronoFox.exe, Setup, and the
    embedded uninstaller are Authenticode-signed.

.PARAMETER SignToolPath
    Optional full path to signtool.exe. If omitted while a thumbprint is
    supplied, the script searches PATH and the Windows 10 SDK x64 folders.

.PARAMETER TimestampUrl
    RFC 3161 timestamp server used only for signed builds.

.EXAMPLE
    .\build_release.ps1
    .\build_release.ps1 -Version 0.8.5 -SkipInno
    .\build_release.ps1 -SignCertificateThumbprint "0123456789ABCDEF0123456789ABCDEF01234567"
#>

[CmdletBinding()]
param(
    [string]$Version = "0.8.5",
    [switch]$SkipInno,
    [switch]$ValidateVersionOnly,
    [string]$SignCertificateThumbprint = "",
    [string]$SignToolPath = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
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

function Assert-ReleaseVersionContract {
    $semVerPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
    if ($Version -notmatch $semVerPattern) {
        throw "Release version is not valid SemVer: $Version"
    }
    $versionParts = $Version.Split('-', 2)
    if ($versionParts.Count -eq 2) {
        foreach ($identifier in $versionParts[1].Split('.')) {
            if ($identifier -match '^\d+$' -and $identifier.Length -gt 1 -and $identifier.StartsWith('0')) {
                throw "Release version is not valid SemVer: $Version"
            }
        }
    }

    $constantsText = Get-Content -LiteralPath "chronofox\core\app_constants.py" -Raw
    $appMatch = [regex]::Match($constantsText, '(?m)^APP_VERSION\s*=\s*"([^"]+)"\s*$')
    $innoText = Get-Content -LiteralPath "installer\chronofox.iss" -Raw
    $innoMatch = [regex]::Match($innoText, '(?m)^\s*#define MyAppVersion "([^"]+)"\s*$')
    $resourceText = Get-Content -LiteralPath "version_info.txt" -Raw
    $resourceMatch = [regex]::Match($resourceText, 'filevers=\((\d+),\s*(\d+),\s*(\d+),\s*\d+\)')
    if (-not $appMatch.Success -or -not $innoMatch.Success -or -not $resourceMatch.Success) {
        throw "Version contract could not read APP_VERSION, MyAppVersion, or filevers."
    }

    $coreVersion = $Version.Split('-', 2)[0]
    $resourceVersion = "$($resourceMatch.Groups[1].Value).$($resourceMatch.Groups[2].Value).$($resourceMatch.Groups[3].Value)"
    if ($appMatch.Groups[1].Value -ne $Version -or $innoMatch.Groups[1].Value -ne $Version -or $resourceVersion -ne $coreVersion) {
        throw "Release version mismatch: argument=$Version APP_VERSION=$($appMatch.Groups[1].Value) Inno=$($innoMatch.Groups[1].Value) resource=$resourceVersion"
    }
}

function Find-SignTool {
    if ($SignToolPath) {
        if (-not (Test-Path -LiteralPath $SignToolPath -PathType Leaf)) {
            throw "signtool.exe not found at SignToolPath: $SignToolPath"
        }
        return (Resolve-Path -LiteralPath $SignToolPath).Path
    }

    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $kitsRoot = "${Env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitsRoot) {
        $candidates = @(
            Get-ChildItem -Path "$kitsRoot\*\x64\signtool.exe" -File -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending
        )
        if ($candidates.Count -gt 0) {
            return $candidates[0].FullName
        }
    }
    throw "Code signing was requested, but signtool.exe was not found. Install the Windows SDK or pass -SignToolPath."
}

function Assert-ValidSignature {
    param([Parameter(Mandatory)][string]$Path)

    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Authenticode verification failed for $Path (status: $($signature.Status))"
    }
}

function Invoke-SignFile {
    param([Parameter(Mandatory)][string]$Path)

    & $script:ResolvedSignTool sign /sha1 $script:NormalizedThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 /d "ChronoFox" $Path
    if ($LASTEXITCODE -ne 0) {
        throw "signtool.exe failed for $Path (exit code $LASTEXITCODE)"
    }
    Assert-ValidSignature -Path $Path
}

try {
    Assert-ReleaseVersionContract
    if ($ValidateVersionOnly) {
        Write-Host "Version contract valid: $Version"
        return
    }
    $script:NormalizedThumbprint = ($SignCertificateThumbprint -replace "\s", "").ToUpperInvariant()
    $SigningEnabled = [bool]$script:NormalizedThumbprint
    if ($SignToolPath -and -not $SigningEnabled) {
        throw "-SignToolPath requires -SignCertificateThumbprint."
    }
    if ($SigningEnabled) {
        if ($script:NormalizedThumbprint -notmatch "^[0-9A-F]{40}$") {
            throw "SignCertificateThumbprint must contain exactly 40 hexadecimal characters."
        }
        $timestamp = $null
        if (-not [Uri]::TryCreate($TimestampUrl, [UriKind]::Absolute, [ref]$timestamp) -or
            $timestamp.Scheme -notin @("http", "https") -or $TimestampUrl -match '[\s"]') {
            throw "TimestampUrl must be an absolute HTTP(S) URL without spaces or quotes."
        }
        $script:ResolvedSignTool = Find-SignTool
        Write-Host "Code signing enabled with certificate thumbprint $script:NormalizedThumbprint" -ForegroundColor Yellow
    } else {
        Write-Host "Code signing disabled (no certificate thumbprint supplied)." -ForegroundColor Yellow
    }

    # 1. Lint gate
    Invoke-Gate "ruff check" {
        python -m ruff check .
    }

    # 2. Fast-lane test gate (excludes `slow`-marked tests; full suite is a
    # separate pre-merge step per AGENTS.md, not part of this pipeline)
    Invoke-Gate "pytest (fast lane)" {
        $env:QT_QPA_PLATFORM = "offscreen"
        $pytestBaseTemp = Join-Path $env:TEMP ("cf_release_{0}" -f [Guid]::NewGuid().ToString("N"))
        python -m pytest -m "not slow" -q --basetemp="$pytestBaseTemp"
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

    if ($SigningEnabled) {
        Invoke-Gate "Authenticode sign ChronoFox.exe" {
            Invoke-SignFile -Path "out\dist\ChronoFox\ChronoFox.exe"
        }
    }

    # 4. Inno Setup installer (optional: skipped if iscc.exe isn't installed)
    $IsccPath = $null
    $InstallerArtifactPath = $null
    if (-not $SkipInno) {
        $isccCmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
        if ($isccCmd) {
            $IsccPath = $isccCmd.Source
        } else {
            foreach ($candidate in @(
                "${Env:ProgramFiles}\Inno Setup 7\ISCC.exe",
                "${Env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
                "${Env:LOCALAPPDATA}\Programs\Inno Setup 7\ISCC.exe",
                "${Env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "${Env:ProgramFiles}\Inno Setup 6\ISCC.exe",
                "${Env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
            )) {
                if ($candidate -and (Test-Path $candidate)) { $IsccPath = $candidate; break }
            }
        }
    }
    if ($IsccPath) {
        Invoke-Gate "Inno Setup compile" {
            $innoArguments = @("/DMyAppVersion=$Version")
            if ($SigningEnabled) {
                $innoSignCommand = '$q{0}$q sign /sha1 {1} /fd SHA256 /tr {2} /td SHA256 /d $qChronoFox$q $f' -f $script:ResolvedSignTool, $script:NormalizedThumbprint, $TimestampUrl
                $innoArguments += "/DEnableSigning=1"
                $innoArguments += "/SChronoFoxSign=$innoSignCommand"
            }
            $innoArguments += "installer\chronofox.iss"
            & $IsccPath @innoArguments
        }
        $InstallerArtifactPath = "installer\Output\ChronoFox-$Version-Setup.exe"
        if (-not (Test-Path -LiteralPath $InstallerArtifactPath -PathType Leaf)) {
            throw "Inno Setup did not produce $InstallerArtifactPath"
        }
        if ($SigningEnabled) {
            Assert-ValidSignature -Path $InstallerArtifactPath
        }
    } else {
        Write-Warning "Inno Setup (iscc.exe) not found - skipping installer build. Install Inno Setup (https://jrsoftware.org/isinfo.php) to produce ChronoFox-$Version-Setup.exe, or pass -SkipInno to silence this warning."
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

        if ($SigningEnabled) {
            $signatureNotice = @"
[디지털 서명 / Digital signature]
이 빌드는 ChronoFox 코드 서명 인증서로 서명되었습니다. 파일 속성의
"디지털 서명" 탭에서 게시자와 서명 상태를 확인할 수 있습니다.

This build is Authenticode-signed. You can verify the publisher and signature
status on the file's Digital Signatures properties tab.
"@
        } else {
            $signatureNotice = @"
[SmartScreen 안내 / SmartScreen notice]
이 빌드는 코드 서명이 되어 있지 않아 Windows SmartScreen이 "알 수 없는
게시자" 경고를 보여줄 수 있습니다. "추가 정보(More info)"에서 앱 이름과
배포 파일의 SHA256을 확인한 뒤 "실행(Run anyway)"을 선택하세요.

This build is not code-signed, so Windows SmartScreen may show an "Unknown
publisher" warning. Verify the app name and the release SHA256 before choosing
"More info" -> "Run anyway".
"@
        }

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

$signatureNotice
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
        if ($InstallerArtifactPath) {
            $targets += @(Get-Item -LiteralPath $InstallerArtifactPath)
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
