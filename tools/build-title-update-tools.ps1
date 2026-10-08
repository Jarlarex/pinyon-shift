<#
.SYNOPSIS
Builds the archive extractor that verifies a title update, without game code.

.DESCRIPTION
verify-fh1-title-update.py needs pinyon_shift_fh1_archive_extract.exe, which
the game build produces. A disc whose game build is not supported yet (or a
fresh setup that has not built the game) has none, so this configures a
host-only build (PINYON_SHIFT_HOST_TESTS_ONLY, like ci-host-tests.ps1) in
out/build/title-update-tools and builds only that target. The SDK runtime DLL
is copied beside it so it starts without changing PATH.
#>
[CmdletBinding()]
param([switch]$JsonEvents)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

. (Join-Path $PSScriptRoot 'release-common.ps1')
$root = Get-PinyonRepoRoot
$buildDirectory = Join-Path $root 'out/build/title-update-tools'
$extractor = Join-Path $buildDirectory 'pinyon_shift_fh1_archive_extract.exe'
$runtime = Join-Path $buildDirectory 'rexglue-artifacts/rexruntime.dll'
Write-PinyonEvent tools 40 'Building the title-update verifier.' -JsonEvents:$JsonEvents
$environment = Enter-PinyonBuildEnvironment
Push-Location $root
try {
    $sdk = Join-Path $root 'thirdparty/shiftglue-sdk'
    if (-not (Test-Path -LiteralPath (Join-Path $buildDirectory 'CMakeCache.txt') -PathType Leaf)) {
        $arguments = @(
            '-S', '.', '-B', $buildDirectory, '-G', 'Ninja',
            "-DCMAKE_MAKE_PROGRAM=$($environment.Ninja)",
            '-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER=clang', '-DCMAKE_CXX_COMPILER=clang++',
            '-DCMAKE_C_FLAGS=-msse4.1', '-DCMAKE_CXX_FLAGS=-msse4.1',
            '-DPINYON_SHIFT_CPU_BASELINE=sse4.1',
            "-DREXSDK_DIR=$sdk",
            '-DPINYON_SHIFT_HOST_TESTS_ONLY=ON',
            "-DPYTHON_EXECUTABLE=$(Get-PinyonPython)")
        & $environment.CMake @arguments
        if ($LASTEXITCODE -ne 0) { throw "Configuring the title-update verifier failed ($LASTEXITCODE)." }
    }
    & $environment.CMake --build $buildDirectory --target pinyon_shift_fh1_archive_extract
    if ($LASTEXITCODE -ne 0) { throw "Building the title-update verifier failed ($LASTEXITCODE)." }
    if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) { throw 'The SDK runtime DLL was not produced.' }
    if (-not (Test-Path -LiteralPath $extractor -PathType Leaf)) { throw 'The archive extractor was not produced.' }
    Copy-Item -LiteralPath $runtime -Destination $buildDirectory -Force
}
finally {
    Pop-Location
}
Write-PinyonEvent tools 45 'The title-update verifier is ready.' -JsonEvents:$JsonEvents
