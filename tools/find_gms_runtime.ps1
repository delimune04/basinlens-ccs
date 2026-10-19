#Requires -Version 7.0
<#
.SYNOPSIS
Find the pinned unchanged normally installed GMS binary without guessing its name.
.DESCRIPTION
Read-only uninstall registry and bounded searches of plausible vendor install
roots. Does not execute applications, installers, licence tools or registry
commands. Full paths stay in the private result; public diagnostics are counts.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PrivateResultPath,
    [Parameter(Mandatory=$true)][string]$PublicDiagnosticPath,
    [string]$ExpectedSha256 = 'd69c77c42212aa8bc90652539e4f4102e47b1676a840d86b5bf9e4ea82f539c2',
    [long]$ExpectedSize = 145479264,
    [ValidateRange(100,100000)][int]$MaximumEntries = 50000,
    [ValidateRange(10,120)][int]$MaximumSeconds = 90
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Installed-runtime discovery requires Windows.' }
if ((Test-Path -LiteralPath $PrivateResultPath) -or (Test-Path -LiteralPath $PublicDiagnosticPath)) { throw 'Discovery outputs must be new.' }
$privateParent = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($PrivateResultPath)).TrimEnd('\')
$publicParent = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($PublicDiagnosticPath)).TrimEnd('\')
if ($privateParent.Equals($publicParent,[StringComparison]::OrdinalIgnoreCase) -or
    $privateParent.StartsWith($publicParent + '\',[StringComparison]::OrdinalIgnoreCase) -or
    $publicParent.StartsWith($privateParent + '\',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Private discovery paths and public diagnostics must use separate sibling trees.'
}
New-Item -ItemType Directory -Force -Path $privateParent,$publicParent | Out-Null
$roots = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$icons = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$visited = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$matchesByPath = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$diagnostic = [ordered]@{
    discovery_schema_version=1; status='searching'; executed_target=$false
    registry_gms_entries=0; registry_aquaveo_entries=0; registry_install_location_roots=0
    registry_icon_roots=0; conventional_vendor_roots=0; plausible_root_count=0
    examined_entries=0; executable_candidates=0; size_matching_candidates=0
    hash_matching_candidates=0; unreadable_locations=0; skipped_reparse_points=0
    budget_exhausted=$false; registration_present=$false; chosen_from_registered_icon=$false
    expected_target_sha256=$ExpectedSha256; expected_target_size=$ExpectedSize
    qualification='Discovery metadata only; no original application launch, licence operation or numerical execution.'
}
function Add-InstallRoot([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    try {
        $expanded = [Environment]::ExpandEnvironmentVariables($Value.Trim().Trim('"'))
        $full = [IO.Path]::GetFullPath($expanded).TrimEnd('\')
        if ($full.TrimEnd('\') -eq [IO.Path]::GetPathRoot($full).TrimEnd('\')) { return $false }
        foreach ($baseName in @('ProgramFiles','ProgramFiles(x86)','ProgramW6432','LOCALAPPDATA','ProgramData')) {
            $base = [Environment]::GetEnvironmentVariable($baseName)
            if ($base -and $full.Equals([IO.Path]::GetFullPath($base).TrimEnd('\'),[StringComparison]::OrdinalIgnoreCase)) { return $false }
        }
        if ($env:LOCALAPPDATA -and $full.Equals((Join-Path $env:LOCALAPPDATA 'Programs').TrimEnd('\'),[StringComparison]::OrdinalIgnoreCase)) { return $false }
        if (Test-Path -LiteralPath $full -PathType Container) {
            $item = Get-Item -LiteralPath $full
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { $diagnostic.skipped_reparse_points++; return $false }
            return $roots.Add($full)
        }
    } catch { $diagnostic.unreadable_locations++ }
    return $false
}
$registryLocations = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($location in $registryLocations) {
    foreach ($entry in @(Get-ItemProperty -Path $location -ErrorAction SilentlyContinue)) {
        $displayName = [string]$entry.DisplayName
        if ($displayName -match '(?i)Aquaveo') { $diagnostic.registry_aquaveo_entries++ }
        if ($displayName -notmatch '(?i)(^|\W)GMS(\W|$)|Groundwater\s+Modeling\s+System') { continue }
        $diagnostic.registry_gms_entries++
        if (Add-InstallRoot ([string]$entry.InstallLocation)) { $diagnostic.registry_install_location_roots++ }
        $icon = [string]$entry.DisplayIcon
        if ($icon) {
            try {
                # Strip only a normal icon-index suffix; never evaluate registry
                # command text or read any licence/activation registry values.
                $icon = ($icon.Trim() -replace ',\s*-?\d+\s*$','').Trim().Trim('"')
                $icon = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($icon))
                if (Test-Path -LiteralPath $icon -PathType Leaf) {
                    [void]$icons.Add($icon)
                    if (Add-InstallRoot ([IO.Path]::GetDirectoryName($icon))) { $diagnostic.registry_icon_roots++ }
                }
            } catch { $diagnostic.unreadable_locations++ }
        }
    }
}
$diagnostic.registration_present = $diagnostic.registry_gms_entries -gt 0
$conventionalParents = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($name in @('ProgramFiles','ProgramFiles(x86)','ProgramW6432','LOCALAPPDATA','ProgramData')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) { [void]$conventionalParents.Add($value) }
}
if ($env:LOCALAPPDATA) { [void]$conventionalParents.Add((Join-Path $env:LOCALAPPDATA 'Programs')) }
foreach ($parent in $conventionalParents) {
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { continue }
    foreach ($directory in @(Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue | Select-Object -First 2048)) {
        if ($directory.Name -match '(?i)GMS|Aquaveo|Groundwater') {
            if (Add-InstallRoot $directory.FullName) { $diagnostic.conventional_vendor_roots++ }
        }
    }
}
$diagnostic.plausible_root_count = $roots.Count
# Registered icon targets are checked directly even if their parent is a broad
# system install root that must not be recursively traversed.
foreach ($icon in $icons) {
    try {
        $item = Get-Item -LiteralPath $icon
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { $diagnostic.skipped_reparse_points++; continue }
        $diagnostic.executable_candidates++
        if ($item.Length -ne $ExpectedSize) { continue }
        $diagnostic.size_matching_candidates++
        if ((Get-FileHash -LiteralPath $icon -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedSha256) { [void]$matchesByPath.Add($icon) }
    } catch { $diagnostic.unreadable_locations++ }
}
$queue = [Collections.Generic.Queue[object]]::new()
foreach ($root in $roots) { $queue.Enqueue(@{ Path=$root; Depth=0 }) }
$watch = [Diagnostics.Stopwatch]::StartNew()
while ($queue.Count -gt 0) {
    if ($watch.Elapsed.TotalSeconds -gt $MaximumSeconds -or $diagnostic.examined_entries -ge $MaximumEntries) { $diagnostic.budget_exhausted=$true; break }
    $directory = $queue.Dequeue()
    if (-not $visited.Add($directory.Path)) { continue }
    try { $children = @(Get-ChildItem -LiteralPath $directory.Path -Force -ErrorAction Stop) }
    catch { $diagnostic.unreadable_locations++; continue }
    foreach ($child in $children) {
        $diagnostic.examined_entries++
        if ($diagnostic.examined_entries -gt $MaximumEntries -or $watch.Elapsed.TotalSeconds -gt $MaximumSeconds) { $diagnostic.budget_exhausted=$true; break }
        if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) { $diagnostic.skipped_reparse_points++; continue }
        if ($child.PSIsContainer) {
            if ($directory.Depth -lt 8) { $queue.Enqueue(@{Path=$child.FullName;Depth=($directory.Depth+1)}) }
            continue
        }
        if ($child.Extension -ne '.exe' -and -not $icons.Contains($child.FullName)) { continue }
        $diagnostic.executable_candidates++
        if ($child.Length -ne $ExpectedSize) { continue }
        $diagnostic.size_matching_candidates++
        try {
            if ((Get-FileHash -LiteralPath $child.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedSha256) { [void]$matchesByPath.Add($child.FullName) }
        } catch { $diagnostic.unreadable_locations++ }
    }
    if ($diagnostic.budget_exhausted) { break }
}
$diagnostic.hash_matching_candidates=$matchesByPath.Count
$registeredMatches = @($matchesByPath | Where-Object { $icons.Contains($_) })
$chosen = $null
if ($registeredMatches.Count -eq 1) { $chosen=$registeredMatches[0]; $diagnostic.chosen_from_registered_icon=$true }
elseif ($matchesByPath.Count -eq 1) { $chosen=@($matchesByPath)[0] }
$diagnostic.status = if ($chosen) { 'verified_installed_runtime_found' } elseif ($matchesByPath.Count -gt 1) { 'ambiguous_verified_installed_runtimes' } else { 'verified_installed_runtime_not_found' }
$diagnostic.finished_utc=[DateTime]::UtcNow.ToString('o')
@{ schema_version=1; runtime_executable_path=$chosen; matching_executable_paths=@($matchesByPath); searched_roots=@($roots) } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PrivateResultPath -Encoding utf8
$diagnostic | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PublicDiagnosticPath -Encoding utf8
Write-Output ('Installed-runtime discovery: ' + $diagnostic.status + '; matching hashes: ' + $matchesByPath.Count + '; GMS registry entries: ' + $diagnostic.registry_gms_entries)
if (-not $chosen) { exit 2 }
exit 0
