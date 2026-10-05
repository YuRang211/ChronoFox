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
    [string]$Version = "0.8.10",
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

function Initialize-PortableStage {
    param(
        [Parameter(Mandatory)][string]$DistPath,
        [Parameter(Mandatory)][string]$StagePath
    )

    # Copy only frozen program inputs, never a profile created by a smoke run.
    $programPaths = @(
        (Join-Path $DistPath "ChronoFox.exe"),
        (Join-Path $DistPath "_internal")
    )
    if (-not (Test-Path -LiteralPath $programPaths[0] -PathType Leaf) -or
        -not (Test-Path -LiteralPath $programPaths[1] -PathType Container)) {
        throw "Portable program inputs require ChronoFox.exe and the _internal directory."
    }
    foreach ($path in $programPaths) {
        $items = @((Get-Item -LiteralPath $path))
        if (Test-Path -LiteralPath $path -PathType Container) {
            $items += @(Get-ChildItem -LiteralPath $path -Recurse -Force)
        }
        if ($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
            throw "Portable program input contains a reparse point: $path"
        }
    }
    if (Test-Path -LiteralPath $StagePath) {
        throw "Portable stage must be a new directory: $StagePath"
    }
    New-Item -ItemType Directory -Path $StagePath | Out-Null
    foreach ($path in $programPaths) {
        Copy-Item -LiteralPath $path -Destination $StagePath -Recurse
    }
    Set-Content -LiteralPath (Join-Path $StagePath "portable.ini") -Value "[ChronoFox]" -Encoding ASCII
}

function Invoke-InnoCompile {
    param(
        [Parameter(Mandatory)][string]$IsccPath,
        [Parameter(Mandatory)][string[]]$InnoArguments,
        [Parameter(Mandatory)][string]$Version,
        [Parameter(Mandatory)][string]$DiagnosticsRoot,
        [Parameter(Mandatory)][string]$PublishedPath,
        [switch]$RequireValidSignature
    )

    New-Item -ItemType Directory -Path $DiagnosticsRoot -Force | Out-Null
    $attempt = Join-Path (Resolve-Path -LiteralPath $DiagnosticsRoot).Path ([Guid]::NewGuid().ToString("N"))
    $outputDir = Join-Path $attempt "output"
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    $stdoutPath = Join-Path $attempt "stdout.log"
    $stderrPath = Join-Path $attempt "stderr.log"
    $manifestPath = Join-Path $attempt "compile.json"
    $candidate = Join-Path $outputDir "ChronoFox-$Version-Setup.exe"
    $started = [DateTime]::UtcNow
    $exitCode = $null
    $invocationError = $null
    try {
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = $null
        & $IsccPath @("/O$outputDir") @InnoArguments 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    } catch {
        $invocationError = $_.Exception.Message
    } finally {
        $ErrorActionPreference = $previousErrorAction
        $ended = [DateTime]::UtcNow
        if (-not (Test-Path -LiteralPath $stdoutPath)) { Set-Content -LiteralPath $stdoutPath -Value "" }
        if (-not (Test-Path -LiteralPath $stderrPath)) { Set-Content -LiteralPath $stderrPath -Value "" }
        $stdout = Get-Content -LiteralPath $stdoutPath -Raw
        $versionMatch = [regex]::Match($stdout, '(?m)^Compiler engine version:\s*(.+)$')
        $compilerVersion = if ($versionMatch.Success) { $versionMatch.Groups[1].Value.Trim() } else { $null }
        $artifactBytes = $null
        $artifactHash = $null
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $artifactBytes = (Get-Item -LiteralPath $candidate).Length
            $artifactHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $candidate).Hash.ToLowerInvariant()
        }
        [ordered]@{
            compiler_path = $IsccPath
            compiler_version = $compilerVersion
            started_utc = $started.ToString("o")
            ended_utc = $ended.ToString("o")
            exit_code = $exitCode
            invocation_error = $invocationError
            artifact_path = $candidate
            artifact_bytes = $artifactBytes
            artifact_sha256 = $artifactHash
        } | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    }

    Write-Host "Inno diagnostic evidence: $attempt"

    if ($invocationError) { throw "Inno Setup invocation failed: $invocationError" }
    if ($exitCode -ne 0) { throw "Inno Setup compile failed (exit code $exitCode); see $attempt" }
    if ($null -eq $artifactBytes) { throw "Inno Setup did not produce $candidate; see $attempt" }

    # Exit 0 alone is insufficient: an interrupted resource write once left a 950 KiB Setup.
    $stream = [IO.File]::OpenRead($candidate)
    try {
        $signature = New-Object byte[] 2
        $readCount = $stream.Read($signature, 0, 2)
        $peSignature = $null
        if ($artifactBytes -ge 64) {
            $reader = New-Object IO.BinaryReader($stream)
            $stream.Seek(0x3c, [IO.SeekOrigin]::Begin) | Out-Null
            $peOffset = $reader.ReadInt32()
            if ($peOffset -ge 64 -and $peOffset -le ($artifactBytes - 4)) {
                $stream.Seek($peOffset, [IO.SeekOrigin]::Begin) | Out-Null
                $peSignature = $reader.ReadUInt32()
            }
        }
    } finally {
        $stream.Dispose()
    }
    if ($artifactBytes -lt 1MB -or $readCount -ne 2 -or $signature[0] -ne 77 -or $signature[1] -ne 90 -or $peSignature -ne 0x00004550) {
        throw "Invalid setup artifact: $candidate ($artifactBytes bytes); see $attempt"
    }
    if ($RequireValidSignature) {
        Assert-ValidSignature -Path $candidate
    }

    if (-not [IO.Path]::IsPathRooted($PublishedPath)) {
        $PublishedPath = Join-Path (Get-Location).ProviderPath $PublishedPath
    }
    $PublishedPath = [IO.Path]::GetFullPath($PublishedPath)
    $publishedParent = Split-Path -Parent $PublishedPath
    New-Item -ItemType Directory -Path $publishedParent -Force | Out-Null
    $pending = Join-Path $publishedParent (".ChronoFox-$Version-Setup-" + [Guid]::NewGuid().ToString("N") + ".tmp")
    Copy-Item -LiteralPath $candidate -Destination $pending
    try {
        if (Test-Path -LiteralPath $PublishedPath -PathType Leaf) {
            [IO.File]::Replace($pending, $PublishedPath, (Join-Path $attempt "previous-setup.exe"))
        } else {
            [IO.File]::Move($pending, $PublishedPath)
        }
    } finally {
        if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending }
    }
    return $PublishedPath
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
        $innoArguments = @("/DMyAppVersion=$Version")
        if ($SigningEnabled) {
            $innoSignCommand = '$q{0}$q sign /sha1 {1} /fd SHA256 /tr {2} /td SHA256 /d $qChronoFox$q $f' -f $script:ResolvedSignTool, $script:NormalizedThumbprint, $TimestampUrl
            $innoArguments += "/DEnableSigning=1"
            $innoArguments += "/SChronoFoxSign=$innoSignCommand"
        }
        $innoArguments += "installer\chronofox.iss"
        $InstallerArtifactPath = Invoke-InnoCompile -IsccPath $IsccPath -InnoArguments $innoArguments -Version $Version -DiagnosticsRoot "out\inno-diagnostics" -PublishedPath "installer\Output\ChronoFox-$Version-Setup.exe" -RequireValidSignature:$SigningEnabled
    } else {
        Write-Warning "Inno Setup (iscc.exe) not found - skipping installer build. Install Inno Setup (https://jrsoftware.org/isinfo.php) to produce ChronoFox-$Version-Setup.exe, or pass -SkipInno to silence this warning."
    }

    # 5. Portable zip (program inputs + portable marker + README.txt)
    $releaseDir = "out\release"
    Invoke-Gate "portable zip" {
        if (Test-Path $releaseDir) { Remove-Item -Recurse -Force $releaseDir }
        New-Item -ItemType Directory -Path $releaseDir | Out-Null

        $portableName = "ChronoFox-$Version-portable"
        $portableStage = Join-Path $releaseDir $portableName
        Initialize-PortableStage -DistPath "out\dist\ChronoFox" -StagePath $portableStage

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
이 빌드는 코드 서명이 없어 Windows 실행 경고가 나타날 수 있습니다.
공식 Releases에서 받은 파일인지 확인하세요.

This build is not code-signed and Windows may show a warning.
Check that you downloaded it from the official Releases page.
"@
        }

        $readmeText = @"
ChronoFox $Version - Portable (무설치 버전)

[실행법 / How to run]
ChronoFox.exe를 더블클릭해 실행하세요. 별도 설치가 필요 없습니다.
Double-click ChronoFox.exe to run. No installation required.

[데이터 위치 / Data location]
ChronoFox.exe 옆의 Data\ 폴더에 설정·일정·메모·백업·로그·캐시를 저장합니다.
portable.ini는 포터블 식별 파일이므로 삭제하지 마세요. 처음 실행할 때
Data\ 폴더를 만들며, 쓰기 가능한 폴더에서 실행해야 합니다.

Settings, schedules, notes, backups, logs, and cache are stored in Data\ beside
ChronoFox.exe. Keep portable.ini: it identifies portable mode. Data\ is created
on first run, so run from a folder where you have write permission.

[이동·업데이트·삭제 / Moving, upgrading, and deleting]
이동할 때 앱을 완전히 종료한 뒤 Data\를 포함한 프로그램 폴더 전체를
복사하세요. 업데이트할 때는 새 ZIP을 다른 폴더에 풀고, 앱을 종료한 뒤
기존 Data\를 새 폴더로 복사합니다. 기존 폴더를 삭제하기 전에 새 버전에서
데이터를 확인하세요. 프로그램 폴더를 삭제하면 안의 사용자 데이터도 삭제됩니다.
포터블에서는 Windows 시작 시 자동실행을 지원하지 않습니다.

To move, fully exit the app and copy the whole program folder including Data\.
To upgrade, extract the new ZIP into a separate folder, exit the app, then copy
your existing Data\ into the new folder. Check your data in the new version
before deleting the old folder. Deleting the program folder also deletes the
user data inside it. Start with Windows is not supported in portable mode.

[기존 데이터·이미지 / Existing data and images]
설치본이나 구형 포터블의 데이터는 자동으로 가져오지 않습니다. 기존 앱에서
ZIP 백업을 만든 뒤 새 포터블의 설정에서 복원하세요. 경로로 연결한 외부
이미지 파일은 ZIP 백업이나 프로그램 폴더 이동에 포함되지 않습니다.

Data from an installed app or older portable release is not imported automatically.
Create a ZIP backup in the old app, then restore it in the new portable app's
settings. External images linked by path are not included in ZIP backups or
program-folder moves.

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
