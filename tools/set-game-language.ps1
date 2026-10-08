[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$StateRoot,
    # Omit to read the current choice.
    [ValidateSet('Console default', 'English', 'French', 'German', 'Spanish', 'Spanish (Mexico)', 'Italian', 'Dutch',
        'Portuguese (Brazil)', 'Japanese', 'Polish', 'Russian')]
    [string]$Language
)

# The game's language is the console language: user_language and, for Mexican
# Spanish, user_country in <state>/config/pinyon_shift.toml. The IDs follow
# src/dlc/rally_pace_notes.cpp. The in-game settings screen edits the same keys.
# Prints {"language": "<name>"}.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'host-config.ps1')

$ids = [ordered]@{
    'English' = 1; 'Japanese' = 2; 'German' = 3; 'French' = 4; 'Spanish' = 5; 'Italian' = 6;
    'Portuguese (Brazil)' = 9; 'Polish' = 11; 'Russian' = 12; 'Dutch' = 16
}
$mexico = 71
$configPath = Join-Path ([IO.Path]::GetFullPath($StateRoot)) 'config/pinyon_shift.toml'
$text = if (Test-Path -LiteralPath $configPath -PathType Leaf) { [IO.File]::ReadAllText($configPath) } else { '' }

if ($Language) {
    if ($text.Length) { [void](New-HostConfigBackup $configPath) }
    if ($Language -eq 'Console default') {
        $text = Remove-TomlValue (Remove-TomlValue $text 'user_language') 'user_country'
    } elseif ($Language -eq 'Spanish (Mexico)') {
        $text = Set-TomlValue (Set-TomlValue $text 'user_language' $ids['Spanish']) 'user_country' $mexico
    } else {
        $text = Set-TomlValue $text 'user_language' $ids[$Language]
        if ((Get-TomlValue $text 'user_country' '') -eq "$mexico") { $text = Remove-TomlValue $text 'user_country' }
    }
    [void](New-Item -ItemType Directory -Force -Path (Split-Path $configPath))
    Write-HostConfig $configPath $text
}

$current = Get-TomlValue $text 'user_language' ''
$name = if (-not $current) {
    'Console default'
} elseif ($current -eq "$($ids['Spanish'])" -and (Get-TomlValue $text 'user_country' '') -eq "$mexico") {
    'Spanish (Mexico)'
} else {
    $ids.Keys | Where-Object { "$($ids[$_])" -eq $current } | Select-Object -First 1
}
if (-not $name) { $name = "Language $current" }
[ordered]@{ language = $name } | ConvertTo-Json -Compress
