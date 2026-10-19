#Requires -Version 7.0
<#
.SYNOPSIS
Bounded normal GMS launch and passive UI capture. No activation or solver run.
.DESCRIPTION
Use an already normally installed GMS. Only the process started here and its
descendants are inspected. Screenshots, titles and UIA text stay private. The
public receipt contains metadata/counts/hashes only. A visible window does not
prove Community entitlement, successful model import, or numerical execution.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ExecutablePath,
    [Parameter(Mandatory=$true)][string]$PrivateOutputDirectory,
    [Parameter(Mandatory=$true)][string]$PublicReceiptPath,
    [string]$ExpectedTargetSha256 = 'd69c77c42212aa8bc90652539e4f4102e47b1676a840d86b5bf9e4ea82f539c2',
    [long]$ExpectedTargetSize = 145479264,
    [string]$ProjectPath,
    [ValidateRange(10,120)][int]$ObservationSeconds = 30,
    [switch]$AllowStart
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'This passive runtime probe requires Windows.' }
if (-not $AllowStart) { throw 'Normal target execution requires the explicit -AllowStart flag.' }
$exe = (Resolve-Path -LiteralPath $ExecutablePath).Path
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Select an installed regular GMS executable.' }
$actualHash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $ExpectedTargetSha256 -or (Get-Item -LiteralPath $exe).Length -ne $ExpectedTargetSize) {
    throw 'Installed GMS target does not match the pinned unchanged executable size and SHA256; it was not started.'
}
$privateFullPath = [IO.Path]::GetFullPath($PrivateOutputDirectory).TrimEnd('\')
$publicFullPath = [IO.Path]::GetFullPath($PublicReceiptPath)
$publicParentFullPath = [IO.Path]::GetDirectoryName($publicFullPath).TrimEnd('\')
if ($publicFullPath.StartsWith($privateFullPath + '\',[StringComparison]::OrdinalIgnoreCase) -or
    $privateFullPath.StartsWith($publicParentFullPath + '\',[StringComparison]::OrdinalIgnoreCase) -or
    $privateFullPath.Equals($publicParentFullPath,[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Private captures and the public receipt directory must be separate sibling trees.'
}
if (Test-Path -LiteralPath $PrivateOutputDirectory) { throw 'Private output directory must be new.' }
if (Test-Path -LiteralPath $PublicReceiptPath) { throw 'Public receipt must be new.' }
$private = New-Item -ItemType Directory -Path $PrivateOutputDirectory
$publicParent = Split-Path -Parent $PublicReceiptPath
if ($publicParent) { New-Item -ItemType Directory -Force -Path $publicParent | Out-Null }
$receipt = [ordered]@{
    probe_schema_version = 1; status = 'not_started'; started_utc = [DateTime]::UtcNow.ToString('o')
    target = @{ name = [IO.Path]::GetFileName($exe); sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant(); size_bytes = (Get-Item -LiteralPath $exe).Length; file_version = [Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileVersion }
    launch_method = 'normal_process_start'; target_started = $false; visible_window_observed = $false
    community_mode_confirmed = $false; numerical_run_observed = $false; paired_gms_comparisons = 0
    startup_classification = 'unknown'; dialog_categories_observed = @(); blocking_dialog_observed = $false
    reported_mode_category = 'unknown'; possible_community_option_text_observed = $false
    main_window_enabled_observed = $null; menu_observations = @()
    standard_menu_items_observed = $false
    classification_basis = 'Conservative passive visible-window and bounded child-control text; original text stays private.'
    activation_requests_initiated_by_probe = 0; licence_ui_actions = 0; target_ui_actions = 0
    target_network_activity_monitored = $false
    observation_seconds = $ObservationSeconds; screenshot_count = 0; private_observation_sha256 = $null
    probe_phase = 'initializing'
    qualification = 'Passive startup/document-window observation only. Screenshots and UI text are private; no numerical or full-product equivalence claim.'
}
$owned = $null
$ownedIds = [Collections.Generic.HashSet[uint]]::new()
$observations = [Collections.Generic.List[object]]::new()
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $PublicReceiptPath -Encoding utf8
try {
    $receipt.probe_phase='initialize_windows_api'
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    if (-not ('GmsPassiveWindows' -as [type])) {
    Add-Type @'
using System;
using System.Collections.Generic;
using System.Text;
using System.Diagnostics;
using System.Runtime.InteropServices;
public static class GmsPassiveWindows {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint command);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect r);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc callback, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,UIntPtr w,StringBuilder text,uint flags,uint milliseconds,out UIntPtr result);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder text, int count);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetMenuItemCount(IntPtr menu);
  [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool GetMenuItemInfo(IntPtr menu,uint item,bool byPosition,ref MenuInfo info);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetMenuString(IntPtr menu,uint item,StringBuilder label,int maximum,uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct MenuInfo {
    public uint Size,Mask,Type,State,Id;
    public IntPtr Submenu,CheckedBitmap,UncheckedBitmap;
    public UIntPtr ItemData;
    public IntPtr TypeData;
    public uint Characters;
    public IntPtr Bitmap;
  }
  public class MenuRecord {
    public string PositionPath,Label;
    public uint CommandId;
    public int Depth;
    public bool Enabled,Checked,Separator,OwnerDrawn;
  }
  public class MenuSnapshot {
    public string Status = "unknown";
    public bool Truncated;
    public int ReadErrors;
    public MenuRecord[] Items = new MenuRecord[0];
  }
  public static IntPtr[] ForPids(HashSet<uint> pids) {
    var result = new List<IntPtr>();
    EnumWindows((h,l) => { uint p; GetWindowThreadProcessId(h,out p); if(pids.Contains(p) && IsWindowVisible(h)) result.Add(h); return true; },IntPtr.Zero);
    return result.ToArray();
  }
  public static string[] VisibleControlText(IntPtr window) {
    var result = new List<string>(); var watch = Stopwatch.StartNew();
    EnumChildWindows(window,(h,l) => {
      if(result.Count >= 100 || watch.ElapsedMilliseconds >= 1500) return false;
      if(IsWindowVisible(h)) {
        var text = new StringBuilder(512); UIntPtr ignored;
        SendMessageTimeout(h,13,new UIntPtr(512),text,3,100,out ignored);
        if(text.Length > 0) result.Add(text.ToString());
      }
      return true;
    },IntPtr.Zero);
    return result.ToArray();
  }
  public static MenuSnapshot MaterializedMenu(IntPtr window) {
    var snapshot = new MenuSnapshot(); var menu = GetMenu(window);
    if(menu == IntPtr.Zero) { snapshot.Status = "no_standard_hmenu_custom_or_unavailable_unknown"; return snapshot; }
    var records = new List<MenuRecord>(); var seen = new HashSet<IntPtr>(); var watch = Stopwatch.StartNew();
    ReadMenu(menu,"",0,records,seen,watch,snapshot);
    snapshot.Items = records.ToArray();
    snapshot.Status = snapshot.ReadErrors > 0 ? "standard_hmenu_partially_read" : "materialized_standard_hmenu_observed";
    return snapshot;
  }
  private static void ReadMenu(IntPtr menu,string prefix,int depth,List<MenuRecord> records,HashSet<IntPtr> seen,Stopwatch watch,MenuSnapshot snapshot) {
    if(depth > 6 || records.Count >= 400 || watch.ElapsedMilliseconds >= 1500 || !seen.Add(menu)) { snapshot.Truncated=true; return; }
    int count = GetMenuItemCount(menu);
    if(count < 0) { snapshot.ReadErrors++; return; }
    for(uint position=0;position<count;position++) {
      if(records.Count >= 400 || watch.ElapsedMilliseconds >= 1500) { snapshot.Truncated=true; break; }
      var info = new MenuInfo { Size=(uint)Marshal.SizeOf(typeof(MenuInfo)), Mask=0x107 };
      // Metadata only: no bitmap requests and no dereferencing owner-draw data.
      if(!GetMenuItemInfo(menu,position,true,ref info)) { snapshot.ReadErrors++; continue; }
      var label = new StringBuilder(512); GetMenuString(menu,position,label,label.Capacity,0x400);
      string path = prefix + position.ToString();
      records.Add(new MenuRecord { PositionPath=path,Label=label.ToString(),CommandId=info.Id,Depth=depth,
        Enabled=(info.State & 3)==0,Checked=(info.State & 8)!=0,Separator=(info.Type & 0x800)!=0,OwnerDrawn=(info.Type & 0x100)!=0 });
      if(info.Submenu != IntPtr.Zero) ReadMenu(info.Submenu,path+"/",depth+1,records,seen,watch,snapshot);
    }
  }
}
'@
    }
    $receipt.probe_phase='check_desktop_and_document_association'
    $screen = [Windows.Forms.SystemInformation]::VirtualScreen
    if ($screen.Width -le 0 -or $screen.Height -le 0) { throw 'No capturable Windows desktop.' }
    if ($ProjectPath) {
        $project = (Resolve-Path -LiteralPath $ProjectPath).Path
        if ([IO.Path]::GetExtension($project) -ne '.gpr') { throw 'Only an existing GMS .gpr document is accepted.' }
        # Use only the installer's ordinary document association. No guessed
        # automation flags and no execution of registry command strings.
        $class = (Get-Item 'Registry::HKEY_CLASSES_ROOT\.gpr').GetValue('')
        $command = (Get-Item "Registry::HKEY_CLASSES_ROOT\$class\shell\open\command").GetValue('')
        $matchingAssociation = $command -match '^\s*"([^"]+)"\s+"?%[1Ll]"?\s*$'
        if (-not $matchingAssociation -or $Matches[1] -ne $exe) {
            throw 'A matching ordinary GMS document association is unavailable; project launch was not attempted.'
        }
        $receipt.launch_method = 'installed_gpr_document_association'
        $receipt.project_sha256 = (Get-FileHash -LiteralPath $project -Algorithm SHA256).Hash.ToLowerInvariant()
        $receipt.probe_phase='normal_document_launch'
        $owned = Start-Process -FilePath $exe -ArgumentList ('"' + $project + '"') -WorkingDirectory ([IO.Path]::GetDirectoryName($exe)) -PassThru
    } else {
        $receipt.probe_phase='normal_startup_launch'
        $owned = Start-Process -FilePath $exe -WorkingDirectory ([IO.Path]::GetDirectoryName($exe)) -PassThru
    }
    $receipt.target_started = $true
    $receipt.status = 'observing'
    $receipt.probe_phase='passive_window_observation'
    [void]$ownedIds.Add([uint32]$owned.Id)
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $PublicReceiptPath -Encoding utf8
    $deadline = [DateTime]::UtcNow.AddSeconds($ObservationSeconds)
    $iteration = 0
    $stopObservation = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        $iteration++
        $pids = [Collections.Generic.HashSet[uint]]::new()
        [void]$pids.Add([uint32]$owned.Id)
        $processes = @(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name)
        do {
            $added = $false
            foreach ($p in $processes) {
                if ($pids.Contains([uint32]$p.ParentProcessId) -and $pids.Add([uint32]$p.ProcessId)) { $added = $true }
            }
        } while ($added)
        foreach ($id in $pids) { [void]$ownedIds.Add($id) }
        foreach ($handle in [GmsPassiveWindows]::ForPids($pids)) {
            $title = [Text.StringBuilder]::new(2048)
            $className = [Text.StringBuilder]::new(256)
            [void][GmsPassiveWindows]::GetWindowText($handle,$title,$title.Capacity)
            [void][GmsPassiveWindows]::GetClassName($handle,$className,$className.Capacity)
            $rect = [GmsPassiveWindows+Rect]::new()
            [void][GmsPassiveWindows]::GetWindowRect($handle,[ref]$rect)
            $entry = [ordered]@{ captured_utc = [DateTime]::UtcNow.ToString('o'); title = $title.ToString(); class = $className.ToString(); controls = @() }
            $receipt.visible_window_observed = $true
            # No unbounded UIA descendant traversal. WM_GETTEXT has a 100ms
            # per-control timeout, 100 text values and a 1.5sec total budget.
            $entry.controls = [GmsPassiveWindows]::VisibleControlText($handle)
            $visibleText = $entry.title + ' ' + ($entry.controls -join ' ')
            if ($entry.title -match '(?i)\bGMS\b.*\bCommunity\b|\bCommunity\b.*\bGMS\b') {
                $receipt.reported_mode_category = 'community_text_in_application_title_entitlement_unverified'
            } elseif ($visibleText -match '(?i)\bcommunity\b' -and $receipt.reported_mode_category -eq 'unknown') {
                $receipt.reported_mode_category = 'community_text_observed_mode_unverified'
            }
            if (@($entry.controls | Where-Object { $_ -match '(?i)\bcommunity\b' }).Count -gt 0) {
                $receipt.possible_community_option_text_observed=$true
            }
            $entry.menu = [GmsPassiveWindows]::MaterializedMenu($handle)
            if ($entry.menu.Items.Count -gt 0 -or $receipt.menu_observations.Count -lt 4) {
                $publicItems=@($entry.menu.Items | ForEach-Object {
                    @{ position_path=$_.PositionPath;command_id=$_.CommandId;depth=$_.Depth;enabled=$_.Enabled;checked=$_.Checked;separator=$_.Separator;owner_drawn=$_.OwnerDrawn }
                })
                $summary=@{status=$entry.menu.Status;truncated=$entry.menu.Truncated;read_errors=$entry.menu.ReadErrors;items=$publicItems;
                    limitation='Only materialized standard HMENU state; menus were not opened or invoked. Missing HMENU does not imply absent product capabilities.'}
                if ($entry.menu.Items.Count -gt 0) {
                    $receipt.standard_menu_items_observed=$true
                    $receipt.menu_observations=@($receipt.menu_observations | Where-Object { $_.items.Count -gt 0 } | Select-Object -Last 3) + @($summary)
                } else { $receipt.menu_observations += @($summary) }
            }
            $ownerHandle = [GmsPassiveWindows]::GetWindow($handle,4)
            $isDialog = $entry.class -eq '#32770' -or ($ownerHandle -ne [IntPtr]::Zero -and -not [GmsPassiveWindows]::IsWindowEnabled($ownerHandle))
            if (-not $isDialog -and $entry.title -match '(?i)\bGMS\b' -and $entry.menu.Items.Count -gt 0) {
                $receipt.main_window_enabled_observed=[GmsPassiveWindows]::IsWindowEnabled($handle)
            }
            $category = 'unknown'
            if ($isDialog) {
                if ($visibleText -match '(?i)evalua|trial.*(expired|licen[cs]e)') { $category = 'evaluation' }
                elseif ($visibleText -match '(?i)activation|registration|licen[cs]e code|unlicensed') { $category = 'licensing' }
                elseif ($visibleText -match '(?i)opengl|graphics.*(driver|error)|failed.*render|hardware.*accel') { $category = 'graphics' }
                elseif ($visibleText -match '(?i)error|exception|fatal|failed|cannot|missing.*dll') { $category = 'error' }
                $receipt.blocking_dialog_observed = $true
                $receipt.dialog_categories_observed = @($receipt.dialog_categories_observed + $category | Select-Object -Unique)
                $receipt.startup_classification = if ($category -eq 'unknown') { 'unclassified_dialog_observed' } else { 'blocking_' + $category + '_dialog_observed' }
                $stopObservation = $true
            } elseif ($receipt.startup_classification -eq 'unknown' -and $entry.title -match '(?i)\bGMS\b') {
                $receipt.startup_classification = 'application_window_observed_mode_unknown'
            }
            # Capture only this target window's visible rectangle. Any blank or
            # occluded frame remains evidence of that limitation, never a fake UI.
            $width = $rect.Right - $rect.Left; $height = $rect.Bottom - $rect.Top
            if ($width -gt 0 -and $height -gt 0 -and $width -le 4096 -and $height -le 4096 -and $receipt.screenshot_count -lt 4) {
                $bitmap = [Drawing.Bitmap]::new($width,$height)
                $graphics = [Drawing.Graphics]::FromImage($bitmap)
                try {
                    $graphics.CopyFromScreen($rect.Left,$rect.Top,0,0,[Drawing.Size]::new($width,$height))
                    $shot = Join-Path $private.FullName ('window-' + $iteration + '-' + $receipt.screenshot_count + '.png')
                    $bitmap.Save($shot,[Drawing.Imaging.ImageFormat]::Png)
                    $entry.screenshot_sha256 = (Get-FileHash -LiteralPath $shot -Algorithm SHA256).Hash.ToLowerInvariant()
                    $receipt.screenshot_count++
                } finally { $graphics.Dispose(); $bitmap.Dispose() }
            }
            $observations.Add($entry)
            if ($stopObservation) { break }
        }
        if ($stopObservation) { break }
        $owned.Refresh()
        if ($owned.HasExited -and ([GmsPassiveWindows]::ForPids($pids)).Count -eq 0) { break }
        Start-Sleep -Seconds 3
    }
    $receipt.status = if ($receipt.visible_window_observed) { 'original_window_observed' } else { 'no_visible_original_window_observed' }
} catch {
    $receipt.status = 'probe_incomplete'
    # Exception messages, paths and UI strings stay private.
    $observations.Add(@{ error = $_.Exception.Message; type = $_.Exception.GetType().Name })
    $receipt.error_type = $_.Exception.GetType().Name
    $receipt.error_hresult = $_.Exception.HResult
    $receipt.failure_phase = $receipt.probe_phase
} finally {
    if ($owned) {
        # End only this bounded probe's process tree. Do not interact with licence
        # dialogs, try alternate keys, request evaluation, or touch registration.
        $owned.Refresh()
        if (-not $owned.HasExited) { & taskkill.exe /PID $owned.Id /T /F 2>&1 | Out-Null }
        foreach ($id in $ownedIds) {
            if (Get-Process -Id $id -ErrorAction SilentlyContinue) { & taskkill.exe /PID $id /T /F 2>&1 | Out-Null }
        }
    }
    $privateJson = Join-Path $private.FullName 'private-observation.json'
    ConvertTo-Json -Depth 12 -InputObject $observations.ToArray() | Set-Content -LiteralPath $privateJson -Encoding utf8
    $receipt.private_observation_sha256 = (Get-FileHash -LiteralPath $privateJson -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt.finished_utc = [DateTime]::UtcNow.ToString('o')
    $receipt.target_unchanged = ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $receipt.target.sha256)
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $PublicReceiptPath -Encoding utf8
}
Write-Output ('Probe receipt saved. Status: ' + $receipt.status + '. Numerical runs: 0. Public screenshots: 0.')
if (-not $receipt.target_unchanged -or $receipt.status -eq 'probe_incomplete') { exit 2 }
exit 0
