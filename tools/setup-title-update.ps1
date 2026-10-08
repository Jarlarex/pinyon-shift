<#
.SYNOPSIS
Fetches, verifies and installs the title update for a verified disc during setup.

.DESCRIPTION
Runs only when the verified disc's media ID is a verified base of the pinned
update (config/supported-title-updates.json). Builds the archive extractor if
neither build has it, then runs tools/fetch-title-update.py, which downloads
the package from its pinned sources and imports it through
manage-title-update.ps1. On the European disc, the update's own base, v4
becomes the default unless a base-disc profile already exists (v4 saves are
one-way); the player then chooses in the launcher. On the USA disc the base
build stays the default. Any failure only falls back to the base disc: this
step never fails setup.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$StateRoot,
    [Parameter(Mandatory)] [string]$MediaId,
    [string]$Region,
    [switch]$JsonEvents,
    # Tests pass their own interpreter; setup uses the provisioned one.
    [string]$Python
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

. (Join-Path $PSScriptRoot 'release-common.ps1')
$root = Get-PinyonRepoRoot
$updates = (Get-Content -LiteralPath (Join-Path $root 'config/supported-title-updates.json') -Raw | ConvertFrom-Json).updates
$isBase = @($updates | ForEach-Object { $_.verified_bases } | Where-Object { $_.media_id -eq $MediaId }).Count -gt 0
if (-not $isBase) { return }

try {
    $extractors = 'out/build/win-amd64-release', 'out/build/title-update-tools' |
        ForEach-Object { Join-Path (Join-Path $root $_) 'pinyon_shift_fh1_archive_extract.exe' }
    if (-not @($extractors | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })) {
        & (Join-Path $PSScriptRoot 'build-title-update-tools.ps1') -JsonEvents:$JsonEvents | Out-Host
    }
    if (-not $Python) { $Python = Get-PinyonPython }
    $arguments = @((Join-Path $PSScriptRoot 'fetch-title-update.py'), '--state-root', $StateRoot)
    if ($JsonEvents) { $arguments += '--json-events' }
    # Progress events pass through as they arrive; the last other line is the result.
    $output = [Collections.Generic.List[string]]::new()
    & $Python @arguments | ForEach-Object {
        if ($_ -like '::pinyon::*') { [Console]::Out.WriteLine($_) } else { $output.Add($_) }
    }
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) { throw "The title-update download step failed ($LASTEXITCODE)." }
    $result = $output[$output.Count - 1] | ConvertFrom-Json
    if (-not ($result.PSObject.Properties['imported'] -and $result.imported)) { return }

    if ($Region -eq 'EUR') {
        $manage = Join-Path $PSScriptRoot 'manage-title-update.ps1'
        $status = (& $manage -Action status -StateRoot $StateRoot) | ConvertFrom-Json
        $baseSaves = @($status.profiles.PSObject.Properties | Where-Object { $_.Value -eq 'base' }).Count
        if ($baseSaves -eq 0) {
            [void](& $manage -Action enable -StateRoot $StateRoot)
            Write-PinyonEvent tools 37 'The title update is installed and will be used: it was made for this disc.' `
                -JsonEvents:$JsonEvents
        } else {
            Write-PinyonEvent tools 37 ('The title update is installed. Your existing base-disc saves stay on the base ' +
                'disc until you choose "Use v4" in the launcher; v4 saves cannot go back.') -JsonEvents:$JsonEvents
        }
    }
}
catch {
    Write-PinyonEvent tools 37 "Continuing with the base disc: $($_.Exception.Message)" -JsonEvents:$JsonEvents
}
