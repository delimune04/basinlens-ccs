#Requires -Version 7.0
<#
.SYNOPSIS
Bounded GMS capture, optional free Community choice and optional File/Open dialog observation.
.DESCRIPTION
Use an already normally installed GMS. Only the process started here and its
descendants are inspected. Screenshots, titles and UIA text stay private. The
public receipt contains metadata/counts/hashes only. Default behavior is passive;
-SelectFreeCommunityEdition permits at most one verified Community Edition button
click during normal startup. -ObserveFileOpenDialog permits one verified menu
command after that completed choice; it never selects or confirms a file. No
activation, trial or solver action is performed. A visible window does not
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
    [switch]$AllowStart,
    [switch]$SelectFreeCommunityEdition,
    [switch]$ObserveFileOpenDialog
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'This passive runtime probe requires Windows.' }
if (-not $AllowStart) { throw 'Normal target execution requires the explicit -AllowStart flag.' }
if ($SelectFreeCommunityEdition -and $ProjectPath) { throw 'The optional free Community choice is allowed only on normal startup without a project argument.' }
if ($ObserveFileOpenDialog -and (-not $SelectFreeCommunityEdition -or $ProjectPath)) { throw 'File/Open dialog observation requires the explicit normal-startup free Community path and no project argument.' }
if ($SelectFreeCommunityEdition -and ($ExpectedTargetSha256 -ne 'd69c77c42212aa8bc90652539e4f4102e47b1676a840d86b5bf9e4ea82f539c2' -or $ExpectedTargetSize -ne 145479264)) { throw 'The optional free Community choice requires the exact originally observed GMS 10.9.7 image identity.' }
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
    community_button_guard_observations = @(); community_button_guard_actions_enabled = $false
    free_community_selection_requested = [bool]$SelectFreeCommunityEdition
    free_community_selection_observations = @(); free_community_selection_attempted = $false
    post_selection_dialog_observed = $false; post_selection_window_observed = $false
    file_open_dialog_probe_requested = [bool]$ObserveFileOpenDialog
    file_open_command_attempted = $false; file_open_ui_actions = 0
    file_open_observation_seconds = if ($ObserveFileOpenDialog) { 15 } else { 0 }
    file_open_observations = @(); post_file_open_dialog_observations = @()
    post_file_open_dialog_observed = $false; fixed_open_dialog_context_observed = $false
    standard_menu_items_observed = $false
    classification_basis = 'Conservative passive visible-window and bounded child-control text; original text stays private.'
    activation_requests_initiated_by_probe = 0; licence_ui_actions = 0; target_ui_actions = 0
    target_network_activity_monitored = $false
    observation_seconds = $ObservationSeconds; screenshot_count = 0; private_observation_sha256 = $null
    probe_phase = 'initializing'
    qualification = 'Bounded startup/document observation. Optional explicit single free Community choice and File/Open dialog command only; no activation or numerical/full-product equivalence claim. UI text and screenshots stay private.'
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
  [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);
  [DllImport("user32.dll")] public static extern bool IsChild(IntPtr parent, IntPtr child);
  [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] private struct WindowInfo {
    public uint Size;
    public Rect Window,Client;
    public uint Style,ExStyle,Status,BorderX,BorderY;
    public ushort WindowType,CreatorVersion;
  }
  [DllImport("user32.dll")] private static extern bool GetWindowInfo(IntPtr h,ref WindowInfo info);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint command);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect r);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc callback, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,UIntPtr w,StringBuilder text,uint flags,uint milliseconds,out UIntPtr result);
  [DllImport("user32.dll", EntryPoint="SendMessageTimeoutW", SetLastError=true)] private static extern IntPtr SendButtonMessageTimeout(IntPtr h,uint m,UIntPtr w,IntPtr l,uint flags,uint milliseconds,out UIntPtr result);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder text, int count);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern IntPtr GetMenu(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] private struct MenuStyleInfo {
    public uint Size,Mask,Style,MaxHeight;
    public IntPtr Background;
    public uint ContextHelpId;
    public UIntPtr MenuData;
  }
  [DllImport("user32.dll")] private static extern bool GetMenuInfo(IntPtr menu,ref MenuStyleInfo info);
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
    public bool Enabled,Checked,Separator,OwnerDrawn,HasSubmenu,ContainingMenuStyleRead;
    public uint ContainingMenuStyle;
  }
  public class MenuSnapshot {
    public string Status = "unknown";
    public bool Truncated;
    public int ReadErrors;
    public bool RootStyleRead;
    public uint RootStyle;
    public MenuRecord[] Items = new MenuRecord[0];
  }
  public static IntPtr[] ForPids(HashSet<uint> pids) {
    var result = new List<IntPtr>();
    EnumWindows((h,l) => { uint p; GetWindowThreadProcessId(h,out p); if(pids.Contains(p) && IsWindowVisible(h)) result.Add(h); return true; },IntPtr.Zero);
    return result.ToArray();
  }
  // Raw handles, IDs, native class names and labels are PRIVATE evidence only.
  public class ControlRecord {
    public long Handle,ParentHandle,TopLevelHandle;
    public uint ProcessId;
    public int ControlId,ButtonType;
    public string ClassName="",Label="";
    public bool Visible,Enabled,OwnedProcess,SameProcessAsWindow,ParentRelationVerified,IsStandardButton,IsPushButton;
  }
  public class ControlSnapshot {
    public ControlRecord[] Controls=new ControlRecord[0];
    public bool Truncated;
    public int ReadErrors;
  }
  public class WindowContext {
    public string VisibleText="";
    public bool OwnedProcess,Visible,Enabled,IsDialog;
  }
  // This is an observation guard, NOT permission to select a control. It has
  // no invocation API. Its fixed label is documented in older official guidance;
  // an actual 10.9.7 observation is still required, and unknown labels stay private.
  public class CommunityCandidateEvidence {
    public bool StandardButton,PushButton,Enabled,Visible,OwnedProcess,SameProcessAsWindow,ParentRelationVerified;
  }
  public class CommunityGuard {
    public string FixedLabelCategory="community_edition";
    public string Status="unknown";
    public string NoLicenseContext="not_recognized_or_unavailable";
    public bool WindowOwnedProcess,WindowVisible,WindowEnabled,WindowIsDialog;
    public bool SnapshotTruncated;
    public int SnapshotReadErrors,InspectedControls,ExactLabelControlCount,ExactLabelStandardButtonCount,EnabledVisibleStandardButtonCount,FullyVerifiedCandidateCount;
    public bool UniqueExactLabelStandardButton,UniqueFullyVerifiedCandidate;
    public bool ActionsEnabled=false,RequiresReviewBeforeAnyAction=true;
    public CommunityCandidateEvidence[] MatchingControls=new CommunityCandidateEvidence[0];
  }
  public static bool IsDocumentedCommunityLabel(string label) {
    // Remove single mnemonic markers, preserving escaped && as a literal &.
    // Trim/collapse whitespace, but never join words or accept substrings,
    // punctuation changes, localization, synonyms or fuzzy matching.
    if(label==null) return false;
    var visibleLabel=new StringBuilder();
    for(int i=0;i<label.Length;i++) {
      if(label[i]!='&') visibleLabel.Append(label[i]);
      else if(i+1<label.Length && label[i+1]=='&') { visibleLabel.Append('&'); i++; }
    }
    string canonical=System.Text.RegularExpressions.Regex.Replace(visibleLabel.ToString(),@"\s+"," ").Trim();
    return String.Equals(canonical,"Community Edition",StringComparison.OrdinalIgnoreCase);
  }
  public static CommunityGuard AssessCommunityButton(WindowContext window,ControlSnapshot snapshot) {
    var guard=new CommunityGuard {
      WindowOwnedProcess=window.OwnedProcess,WindowVisible=window.Visible,WindowEnabled=window.Enabled,WindowIsDialog=window.IsDialog,
      SnapshotTruncated=snapshot.Truncated,SnapshotReadErrors=snapshot.ReadErrors,InspectedControls=snapshot.Controls.Length
    };
    bool context=System.Text.RegularExpressions.Regex.IsMatch(window.VisibleText ?? "",@"\bno\s+licen[cs]e\s+found\b",System.Text.RegularExpressions.RegexOptions.IgnoreCase|System.Text.RegularExpressions.RegexOptions.CultureInvariant);
    if(context) guard.NoLicenseContext="fixed_no_license_found_phrase_observed_context_unverified";
    var matches=new List<CommunityCandidateEvidence>();
    foreach(var control in snapshot.Controls) {
      if(!IsDocumentedCommunityLabel(control.Label)) continue;
      guard.ExactLabelControlCount++;
      matches.Add(new CommunityCandidateEvidence { StandardButton=control.IsStandardButton,PushButton=control.IsPushButton,
        Enabled=control.Enabled,Visible=control.Visible,OwnedProcess=control.OwnedProcess,
        SameProcessAsWindow=control.SameProcessAsWindow,ParentRelationVerified=control.ParentRelationVerified });
      if(!control.IsStandardButton || !control.IsPushButton) continue;
      guard.ExactLabelStandardButtonCount++;
      if(control.Enabled && control.Visible) guard.EnabledVisibleStandardButtonCount++;
      if(control.Enabled && control.Visible && control.OwnedProcess && control.SameProcessAsWindow && control.ParentRelationVerified) guard.FullyVerifiedCandidateCount++;
    }
    guard.MatchingControls=matches.ToArray();
    guard.UniqueExactLabelStandardButton=guard.ExactLabelStandardButtonCount==1;
    guard.UniqueFullyVerifiedCandidate=guard.FullyVerifiedCandidateCount==1 && guard.ExactLabelStandardButtonCount==1 && guard.ExactLabelControlCount==1;
    if(snapshot.Truncated || snapshot.ReadErrors>0) guard.Status="incomplete_control_snapshot_unknown";
    else if(!window.OwnedProcess || !window.Visible || !window.Enabled || !window.IsDialog) guard.Status="owned_visible_enabled_dialog_not_verified";
    else if(!context) guard.Status="fixed_no_license_found_context_not_observed";
    else if(guard.ExactLabelControlCount==0) guard.Status="exact_documented_label_not_observed";
    else if(guard.ExactLabelControlCount!=1 || guard.ExactLabelStandardButtonCount!=1) guard.Status="unique_standard_push_button_not_verified";
    else if(!guard.UniqueFullyVerifiedCandidate) guard.Status="candidate_enabled_visibility_or_ownership_relation_not_verified";
    else guard.Status="passive_candidate_observed_review_required_no_action";
    return guard;
  }
  public class FreeCommunitySelection {
    public string Policy="documented_free_community_normal_startup_v1",Status="not_checked";
    public string NoLicenseContext="not_recognized_or_unavailable";
    public bool ExplicitOptIn,NormalStartup,TargetIdentityVerified,LiveImagePathVerified,CompleteLiveSnapshots;
    public bool TermsAcceptanceContextObserved,OtherLicenceOptionsTextObserved,PolicyPermitsOneAttempt,Attempted,MessageCompleted;
    public int ExactLabelControlCount,VisibleDialogCount,AttemptBudgetUsed;
    public bool NoLicensePhraseRequiredByThisPolicy=false;
    public string Qualification="A unique actual free Community choice may be selected once; no activation or entitlement/numerical inference. Unknown no-license phrase remains unknown.";
  }
  public static FreeCommunitySelection AssessFreeSelection(WindowContext window,ControlSnapshot snapshot,bool optIn,bool normalStartup,bool identityVerified,int attemptsUsed,int globalLabels,int dialogs,bool complete) {
    var guard=AssessCommunityButton(window,snapshot);
    var selection=new FreeCommunitySelection { ExplicitOptIn=optIn,NormalStartup=normalStartup,TargetIdentityVerified=identityVerified,
      AttemptBudgetUsed=attemptsUsed,ExactLabelControlCount=globalLabels,VisibleDialogCount=dialogs,CompleteLiveSnapshots=complete,NoLicenseContext=guard.NoLicenseContext };
    // A normal licence chooser can mention paid keys or trials as alternatives.
    // The only eligible action remains the exact free Community button; those
    // mentions do not turn that action into registration or a trial request.
    // A separate terms-acceptance context still refuses automated selection.
    selection.TermsAcceptanceContextObserved=System.Text.RegularExpressions.Regex.IsMatch(window.VisibleText ?? "",@"\beula\b|\bterms\s+(?:and|&)\s+conditions\b|\bend[ -]user\s+licen[cs]e\b|\blicen[cs]e\s+agreement\b|\bterms\s+of\s+(?:use|service)\b|\b(?:agree|consent|accept)\b.{0,80}\b(?:agreement|terms)\b",System.Text.RegularExpressions.RegexOptions.IgnoreCase|System.Text.RegularExpressions.RegexOptions.CultureInvariant);
    selection.OtherLicenceOptionsTextObserved=System.Text.RegularExpressions.Regex.IsMatch(window.VisibleText ?? "",@"\b(evaluation|trial|billing|checkout|payment|purchase)\b|\blicen[cs]e\s+(?:key|code)\b|\blegacy\s+licensing\b",System.Text.RegularExpressions.RegexOptions.IgnoreCase|System.Text.RegularExpressions.RegexOptions.CultureInvariant);
    if(!optIn) selection.Status="passive_default_no_action";
    else if(!normalStartup) selection.Status="document_launch_disallows_free_choice";
    else if(attemptsUsed!=0) selection.Status="single_attempt_budget_already_used";
    else if(!identityVerified) selection.Status="fresh_target_identity_not_verified";
    else if(!complete || snapshot.Truncated || snapshot.ReadErrors>0) selection.Status="incomplete_live_snapshot_no_action";
    else if(globalLabels!=1 || dialogs!=1) selection.Status="global_dialog_or_exact_button_uniqueness_not_verified";
    else if(!window.OwnedProcess || !window.Visible || !window.Enabled || !window.IsDialog || !guard.UniqueFullyVerifiedCandidate) selection.Status="live_owned_enabled_standard_button_relation_not_verified";
    else if(selection.TermsAcceptanceContextObserved) selection.Status="terms_acceptance_context_no_action";
    else { selection.PolicyPermitsOneAttempt=true; selection.Status="one_documented_free_choice_attempt_permitted"; }
    return selection;
  }
  private class LiveSelectionState {
    public WindowContext Window=new WindowContext();
    public ControlSnapshot Snapshot=new ControlSnapshot();
    public IntPtr Button=IntPtr.Zero;
    public IntPtr Dialog=IntPtr.Zero,ButtonParent=IntPtr.Zero,ButtonRoot=IntPtr.Zero;
    public uint ProcessId;
    public int Labels,Dialogs;
    public bool Complete=true;
  }
  private static LiveSelectionState ReadSelectionState(HashSet<uint> pids) {
    var state=new LiveSelectionState(); var windows=ForPids(pids);
    if(windows.Length>8) { state.Complete=false; return state; }
    foreach(var window in windows) {
      uint pid; GetWindowThreadProcessId(window,out pid);
      var title=new StringBuilder(2048); GetWindowText(window,title,title.Capacity);
      if(title.Length>=title.Capacity-1) state.Complete=false;
      var nativeClass=new StringBuilder(256);
      if(GetClassName(window,nativeClass,nativeClass.Capacity)==0) state.Complete=false;
      var owner=GetWindow(window,4);
      bool dialog=nativeClass.ToString()=="#32770" || (owner!=IntPtr.Zero && !IsWindowEnabled(owner));
      if(dialog) state.Dialogs++;
      var snapshot=BoundedControls(window,pids);
      if(snapshot.Truncated || snapshot.ReadErrors>0) state.Complete=false;
      var text=new StringBuilder(title.ToString());
      foreach(var c in snapshot.Controls) if(c.Visible) text.Append(" ").Append(c.Label);
      var context=new WindowContext { VisibleText=text.ToString(),OwnedProcess=pids.Contains(pid),Visible=IsWindowVisible(window),Enabled=IsWindowEnabled(window),IsDialog=dialog };
      var guard=AssessCommunityButton(context,snapshot);
      state.Labels+=guard.ExactLabelControlCount;
      if(guard.UniqueFullyVerifiedCandidate && dialog) {
        state.Window=context; state.Snapshot=snapshot; state.ProcessId=pid;
        state.Dialog=window;
        foreach(var c in snapshot.Controls) if(IsDocumentedCommunityLabel(c.Label)) {
          state.Button=new IntPtr(c.Handle); state.ButtonParent=new IntPtr(c.ParentHandle);
          state.ButtonRoot=new IntPtr(c.TopLevelHandle);
        }
      }
    }
    return state;
  }
  private static bool VerifyPinnedImage(string path,string expectedHash,long expectedSize) {
    var info=new System.IO.FileInfo(path);
    if(!info.Exists || info.Length!=expectedSize) return false;
    using(var stream=System.IO.File.OpenRead(path)) using(var sha=System.Security.Cryptography.SHA256.Create()) {
      string hash=BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
      return String.Equals(hash,expectedHash,StringComparison.OrdinalIgnoreCase);
    }
  }
  public static FreeCommunitySelection SelectFreeCommunityOnce(HashSet<uint> pids,string imagePath,string expectedHash,long expectedSize,bool optIn,bool normalStartup,int attemptsUsed) {
    var selection=new FreeCommunitySelection { ExplicitOptIn=optIn,NormalStartup=normalStartup,AttemptBudgetUsed=attemptsUsed };
    if(!optIn || !normalStartup || attemptsUsed!=0) return AssessFreeSelection(new WindowContext(),new ControlSnapshot(),optIn,normalStartup,false,attemptsUsed,0,0,false);
    try {
      bool identity=VerifyPinnedImage(imagePath,expectedHash,expectedSize);
      var first=ReadSelectionState(pids);
      selection=AssessFreeSelection(first.Window,first.Snapshot,optIn,normalStartup,identity,attemptsUsed,first.Labels,first.Dialogs,first.Complete);
      if(!selection.PolicyPermitsOneAttempt || first.Button==IntPtr.Zero) return selection;
      string liveImage=Process.GetProcessById((int)first.ProcessId).MainModule.FileName;
      bool sameImage=String.Equals(System.IO.Path.GetFullPath(liveImage),System.IO.Path.GetFullPath(imagePath),StringComparison.OrdinalIgnoreCase);
      selection.LiveImagePathVerified=sameImage;
      // Fresh exact-byte verification precedes a second complete live snapshot.
      if(!sameImage || !VerifyPinnedImage(liveImage,expectedHash,expectedSize)) { selection.PolicyPermitsOneAttempt=false; selection.Status="live_process_exact_image_not_verified"; return selection; }
      var fresh=ReadSelectionState(pids);
      selection=AssessFreeSelection(fresh.Window,fresh.Snapshot,optIn,normalStartup,true,attemptsUsed,fresh.Labels,fresh.Dialogs,fresh.Complete);
      selection.LiveImagePathVerified=true;
      if(!selection.PolicyPermitsOneAttempt || fresh.Button==IntPtr.Zero) return selection;
      if(fresh.Button!=first.Button || fresh.ProcessId!=first.ProcessId || fresh.Dialog!=first.Dialog || fresh.ButtonParent!=first.ButtonParent || fresh.ButtonRoot!=first.ButtonRoot) { selection.PolicyPermitsOneAttempt=false; selection.Status="candidate_changed_during_fresh_checks_no_action"; return selection; }
      // Reserve the sole attempt BEFORE the only control-selection call. A
      // timeout can still mean delivery, so it is counted and never retried.
      selection.Attempted=true; selection.AttemptBudgetUsed=1;
      UIntPtr ignored;
      selection.MessageCompleted=SendButtonMessageTimeout(fresh.Button,0x00F5,UIntPtr.Zero,IntPtr.Zero,3,1000,out ignored)!=IntPtr.Zero; // BM_CLICK
      selection.Status=selection.MessageCompleted ? "single_free_community_click_sent" : "single_free_community_click_timeout_or_failure_no_retry";
    } catch { selection.PolicyPermitsOneAttempt=false; selection.Status=selection.Attempted ? "single_attempt_exception_no_retry" : "fresh_selection_check_failed_no_action"; }
    return selection;
  }
  public class FileOpenDecision {
    public string Policy="observed_file_open_dialog_only_v1",Status="not_checked";
    public uint CommandId=37447;
    public string ExpectedPosition="1/2";
    public bool ExplicitOptIn,NormalStartup,CommunityAttempted,CommunityMessageCompleted,TargetIdentityVerified,LiveImagePathVerified;
    public bool CompleteLiveSnapshots,WindowOwnedProcess,WindowVisible,WindowEnabled,WindowIsDialog,MenuComplete,EnabledAncestorChainVerified,CommandNotificationStyleVerified;
    public bool ConsistentWindowMenuSnapshots,PolicyPermitsOneAttempt,Attempted,MessageCompleted;
    public int VisibleDialogCount,EnabledMenuWindowCount,GlobalCommandCount,ExpectedPositionCommandCount,MenuItemCount,AttemptBudgetUsed;
    public string Qualification="One File/Open menu delivery only; no file selection, confirmation, model loading, edition entitlement or numerical execution is established.";
  }
  public static FileOpenDecision AssessFileOpen(WindowContext window,MenuSnapshot menu,bool optIn,bool normalStartup,bool communityAttempted,bool communityCompleted,bool identity,int used,int dialogs,int mainWindows,int globalCommands,bool complete) {
    var decision=new FileOpenDecision { ExplicitOptIn=optIn,NormalStartup=normalStartup,CommunityAttempted=communityAttempted,
      CommunityMessageCompleted=communityCompleted,TargetIdentityVerified=identity,AttemptBudgetUsed=used,VisibleDialogCount=dialogs,
      EnabledMenuWindowCount=mainWindows,GlobalCommandCount=globalCommands,CompleteLiveSnapshots=complete,
      WindowOwnedProcess=window.OwnedProcess,WindowVisible=window.Visible,WindowEnabled=window.Enabled,WindowIsDialog=window.IsDialog,
      MenuComplete=!menu.Truncated && menu.ReadErrors==0 && menu.Status=="materialized_standard_hmenu_observed",MenuItemCount=menu.Items.Length };
    int enabledAncestors=0,ancestorRecords=0;
    bool leafStyleVerified=false;
    foreach(var item in menu.Items) {
      if(item.PositionPath=="1") {
        ancestorRecords++;
        if(item.Enabled && !item.Separator && item.HasSubmenu && item.ContainingMenuStyleRead && (item.ContainingMenuStyle & 0x08000000)==0) enabledAncestors++;
      }
      if(item.CommandId==37447 && item.PositionPath=="1/2" && item.Enabled && !item.Separator && !item.HasSubmenu) {
        decision.ExpectedPositionCommandCount++;
        leafStyleVerified=item.ContainingMenuStyleRead && (item.ContainingMenuStyle & 0x08000000)==0;
      }
    }
    decision.EnabledAncestorChainVerified=ancestorRecords==1 && enabledAncestors==1;
    decision.CommandNotificationStyleVerified=menu.RootStyleRead && (menu.RootStyle & 0x08000000)==0 && leafStyleVerified;
    if(!optIn) decision.Status="passive_default_no_file_open_action";
    else if(!normalStartup) decision.Status="document_launch_disallows_file_open_probe";
    else if(!communityAttempted || !communityCompleted) decision.Status="completed_normal_free_choice_not_observed";
    else if(used!=0) decision.Status="file_open_attempt_budget_already_used";
    else if(!identity) decision.Status="fresh_exact_image_not_verified";
    else if(!complete || !decision.MenuComplete) decision.Status="incomplete_live_window_or_menu_snapshot_no_action";
    else if(!decision.EnabledAncestorChainVerified) decision.Status="enabled_complete_menu_ancestor_chain_not_verified";
    else if(!decision.CommandNotificationStyleVerified) decision.Status="wm_command_notification_style_not_verified";
    else if(dialogs!=0) decision.Status="owned_visible_dialog_prevents_file_open";
    else if(mainWindows!=1 || globalCommands!=1 || decision.ExpectedPositionCommandCount!=1) decision.Status="unique_expected_main_window_menu_command_not_verified";
    else if(!window.OwnedProcess || !window.Visible || !window.Enabled || window.IsDialog) decision.Status="owned_visible_enabled_main_window_not_verified";
    else { decision.PolicyPermitsOneAttempt=true; decision.Status="one_observed_file_open_delivery_permitted"; }
    return decision;
  }
  private class FileOpenState {
    public WindowContext Window=new WindowContext();
    public MenuSnapshot Menu=new MenuSnapshot();
    public IntPtr Handle=IntPtr.Zero,MenuHandle=IntPtr.Zero;
    public uint ProcessId;
    public int Dialogs,MainWindows,Commands;
    public bool Complete=true;
    public string MenuFingerprint="";
  }
  private static string NumericMenuFingerprint(MenuSnapshot menu) {
    var text=new StringBuilder(); text.Append(menu.RootStyleRead).Append('|').Append(menu.RootStyle).Append('\n');
    foreach(var item in menu.Items) text.Append(item.PositionPath).Append('|').Append(item.CommandId).Append('|').Append(item.Enabled).Append('|').Append(item.Checked).Append('|').Append(item.Separator).Append('|').Append(item.OwnerDrawn).Append('|').Append(item.HasSubmenu).Append('|').Append(item.ContainingMenuStyleRead).Append('|').Append(item.ContainingMenuStyle).Append('\n');
    using(var sha=System.Security.Cryptography.SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(text.ToString())));
  }
  private static FileOpenState ReadFileOpenState(HashSet<uint> pids) {
    var state=new FileOpenState(); var windows=ForPids(pids);
    if(windows.Length>8) { state.Complete=false; return state; }
    foreach(var window in windows) {
      uint pid; GetWindowThreadProcessId(window,out pid);
      var nativeClass=new StringBuilder(256);
      if(GetClassName(window,nativeClass,nativeClass.Capacity)==0) state.Complete=false;
      var owner=GetWindow(window,4);
      bool dialog=nativeClass.ToString()=="#32770" || (owner!=IntPtr.Zero && !IsWindowEnabled(owner));
      if(dialog) state.Dialogs++;
      var menuHandle=GetMenu(window);
      var menu=MaterializedMenu(window);
      if(menuHandle!=GetMenu(window) || menu.Truncated || menu.ReadErrors>0) state.Complete=false;
      foreach(var item in menu.Items) if(item.CommandId==37447) state.Commands++;
      bool enabled=IsWindowEnabled(window),visible=IsWindowVisible(window);
      if(!dialog && enabled && visible && menu.Items.Length>0) {
        state.MainWindows++;
        state.Handle=window; state.MenuHandle=menuHandle; state.ProcessId=pid; state.Menu=menu;
        state.MenuFingerprint=NumericMenuFingerprint(menu);
        state.Window=new WindowContext { OwnedProcess=pids.Contains(pid) && GetAncestor(window,2)==window,Visible=visible,Enabled=enabled,IsDialog=dialog };
      }
    }
    return state;
  }
  public static FileOpenDecision OpenFileDialogOnce(HashSet<uint> pids,string imagePath,string expectedHash,long expectedSize,bool optIn,bool normalStartup,bool communityAttempted,bool communityCompleted,int used) {
    var decision=new FileOpenDecision();
    if(!optIn || !normalStartup || !communityAttempted || !communityCompleted || used!=0)
      return AssessFileOpen(new WindowContext(),new MenuSnapshot(),optIn,normalStartup,communityAttempted,communityCompleted,false,used,0,0,0,false);
    try {
      bool identity=VerifyPinnedImage(imagePath,expectedHash,expectedSize);
      var first=ReadFileOpenState(pids);
      decision=AssessFileOpen(first.Window,first.Menu,optIn,normalStartup,communityAttempted,communityCompleted,identity,used,first.Dialogs,first.MainWindows,first.Commands,first.Complete);
      if(!decision.PolicyPermitsOneAttempt || first.Handle==IntPtr.Zero) return decision;
      string liveImage=Process.GetProcessById((int)first.ProcessId).MainModule.FileName;
      bool sameImage=String.Equals(System.IO.Path.GetFullPath(liveImage),System.IO.Path.GetFullPath(imagePath),StringComparison.OrdinalIgnoreCase);
      decision.LiveImagePathVerified=sameImage;
      if(!sameImage || !VerifyPinnedImage(liveImage,expectedHash,expectedSize)) { decision.PolicyPermitsOneAttempt=false; decision.Status="live_process_exact_image_not_verified"; return decision; }
      var fresh=ReadFileOpenState(pids);
      decision=AssessFileOpen(fresh.Window,fresh.Menu,optIn,normalStartup,communityAttempted,communityCompleted,true,used,fresh.Dialogs,fresh.MainWindows,fresh.Commands,fresh.Complete);
      decision.LiveImagePathVerified=true;
      if(!decision.PolicyPermitsOneAttempt || fresh.Handle==IntPtr.Zero) return decision;
      decision.ConsistentWindowMenuSnapshots=first.Handle==fresh.Handle && first.MenuHandle==fresh.MenuHandle && first.ProcessId==fresh.ProcessId && first.MenuFingerprint==fresh.MenuFingerprint;
      if(!decision.ConsistentWindowMenuSnapshots) { decision.PolicyPermitsOneAttempt=false; decision.Status="main_window_or_menu_changed_during_checks_no_action"; return decision; }
      // Reserve the sole File/Open attempt before WM_COMMAND. Timeout may still
      // mean delivery, so never retry and never confirm/select any file.
      decision.Attempted=true; decision.AttemptBudgetUsed=1;
      UIntPtr ignored;
      decision.MessageCompleted=SendButtonMessageTimeout(fresh.Handle,0x0111,new UIntPtr(37447),IntPtr.Zero,3,1000,out ignored)!=IntPtr.Zero; // WM_COMMAND menu command
      decision.Status=decision.MessageCompleted ? "single_file_open_command_sent" : "single_file_open_timeout_or_failure_no_retry";
    } catch { decision.PolicyPermitsOneAttempt=false; decision.Status=decision.Attempted ? "file_open_attempt_exception_no_retry" : "fresh_file_open_check_failed_no_action"; }
    return decision;
  }
  public class OpenDialogObservation {
    public string Status="post_command_dialog_context_unverified";
    public bool WindowOwnedProcess,WindowVisible,WindowEnabled,StandardDialogClass,FixedOpenTitleObserved,SnapshotTruncated;
    public int InspectedControls,SnapshotReadErrors,Buttons,Edits,ComboBoxes,ListViews,DirectUi,StaticControls,OtherControls;
    public bool FileSelectionOrConfirmationPerformed=false;
  }
  public static OpenDialogObservation ObserveOpenDialog(WindowContext window,ControlSnapshot snapshot,string nativeClass,string title) {
    var result=new OpenDialogObservation { WindowOwnedProcess=window.OwnedProcess,WindowVisible=window.Visible,WindowEnabled=window.Enabled,
      StandardDialogClass=nativeClass=="#32770",FixedOpenTitleObserved=String.Equals((title ?? "").Trim(),"Open",StringComparison.OrdinalIgnoreCase),
      SnapshotTruncated=snapshot.Truncated,SnapshotReadErrors=snapshot.ReadErrors,InspectedControls=snapshot.Controls.Length };
    foreach(var control in snapshot.Controls) {
      switch((control.ClassName ?? "").ToLowerInvariant()) {
        case "button": result.Buttons++; break;
        case "edit": result.Edits++; break;
        case "combobox": case "comboboxex32": result.ComboBoxes++; break;
        case "syslistview32": result.ListViews++; break;
        case "directuihwnd": result.DirectUi++; break;
        case "static": result.StaticControls++; break;
        default: result.OtherControls++; break;
      }
    }
    if(result.WindowOwnedProcess && result.WindowVisible && result.StandardDialogClass && result.FixedOpenTitleObserved)
      result.Status="fixed_open_title_standard_dialog_observed_effect_unverified";
    return result;
  }
  public static ControlSnapshot BoundedControls(IntPtr window,HashSet<uint> pids) {
    var snapshot=new ControlSnapshot(); var result=new List<ControlRecord>(); var watch=Stopwatch.StartNew();
    uint windowPid; GetWindowThreadProcessId(window,out windowPid);
    EnumChildWindows(window,(h,l) => {
      if(result.Count>=128 || watch.ElapsedMilliseconds>=1500) { snapshot.Truncated=true; return false; }
      uint pid; GetWindowThreadProcessId(h,out pid);
      var parent=GetParent(h); var root=GetAncestor(h,2);
      bool sameOwnedProcess=pids.Contains(pid) && pid==windowPid;
      var nativeClass=new StringBuilder(256);
      // Do not retrieve text from a foreign-process child attached to this window.
      if(!sameOwnedProcess) snapshot.ReadErrors++;
      else if(GetClassName(h,nativeClass,nativeClass.Capacity)==0) snapshot.ReadErrors++;
      bool visible=IsWindowVisible(h);
      var text=new StringBuilder(512);
      if(visible && sameOwnedProcess) { UIntPtr ignored; if(SendMessageTimeout(h,13,new UIntPtr(512),text,3,100,out ignored)==IntPtr.Zero || text.Length>=511) snapshot.ReadErrors++; }
      bool standard=String.Equals(nativeClass.ToString(),"Button",StringComparison.OrdinalIgnoreCase);
      int type=-1;
      if(standard) {
        var info=new WindowInfo { Size=(uint)Marshal.SizeOf(typeof(WindowInfo)) };
        if(GetWindowInfo(h,ref info)) type=(int)(info.Style & 15);
        else snapshot.ReadErrors++;
      }
      result.Add(new ControlRecord { Handle=h.ToInt64(),ParentHandle=parent.ToInt64(),TopLevelHandle=root.ToInt64(),
        ProcessId=pid,ControlId=GetDlgCtrlID(h),ButtonType=type,ClassName=nativeClass.ToString(),Label=text.ToString(),
        Visible=visible,Enabled=IsWindowEnabled(h),OwnedProcess=pids.Contains(pid),SameProcessAsWindow=pid==windowPid,
        ParentRelationVerified=parent!=IntPtr.Zero && IsChild(window,h) && root==window && (parent==window || GetAncestor(parent,2)==window),
        IsStandardButton=standard,IsPushButton=standard && (type==0 || type==1) });
      return true;
    },IntPtr.Zero);
    if(watch.ElapsedMilliseconds>=1500) snapshot.Truncated=true;
    snapshot.Controls=result.ToArray(); return snapshot;
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
    var style=new MenuStyleInfo { Size=(uint)Marshal.SizeOf(typeof(MenuStyleInfo)),Mask=0x10 }; // MIM_STYLE
    bool styleRead=GetMenuInfo(menu,ref style);
    if(!styleRead) snapshot.ReadErrors++;
    if(depth==0) { snapshot.RootStyleRead=styleRead; snapshot.RootStyle=style.Style; }
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
        Enabled=(info.State & 3)==0,Checked=(info.State & 8)!=0,Separator=(info.Type & 0x800)!=0,OwnerDrawn=(info.Type & 0x100)!=0,
        HasSubmenu=info.Submenu!=IntPtr.Zero,ContainingMenuStyleRead=styleRead,ContainingMenuStyle=style.Style });
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
    $selectionChecked = $false
    $fileOpenChecked = $false
    $continueAfterSelection = $false
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
            # No unbounded UIA traversal. This records at most 128 native controls,
            # with a 100ms per-control timeout and a 1.5sec total budget. Native
            # handles, IDs, labels and classes remain in the private JSON only.
            $entry.control_snapshot = [GmsPassiveWindows]::BoundedControls($handle,$pids)
            $entry.controls = @($entry.control_snapshot.Controls | Where-Object { $_.Visible -and $_.Label } | ForEach-Object { $_.Label })
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
                    @{ position_path=$_.PositionPath;command_id=$_.CommandId;depth=$_.Depth;enabled=$_.Enabled;checked=$_.Checked;separator=$_.Separator;owner_drawn=$_.OwnerDrawn;has_submenu=$_.HasSubmenu;containing_menu_style_read=$_.ContainingMenuStyleRead;containing_menu_style=$_.ContainingMenuStyle }
                })
                $summary=@{status=$entry.menu.Status;truncated=$entry.menu.Truncated;read_errors=$entry.menu.ReadErrors;root_style_read=$entry.menu.RootStyleRead;root_style=$entry.menu.RootStyle;items=$publicItems;
                    limitation='Materialized standard HMENU observation; any optional File/Open delivery is counted separately. Missing HMENU does not imply absent product capabilities.'}
                if ($entry.menu.Items.Count -gt 0) {
                    $receipt.standard_menu_items_observed=$true
                    $receipt.menu_observations=@($receipt.menu_observations | Where-Object { $_.items.Count -gt 0 } | Select-Object -Last 3) + @($summary)
                } else { $receipt.menu_observations += @($summary) }
            }
            $ownerHandle = [GmsPassiveWindows]::GetWindow($handle,4)
            $isDialog = $entry.class -eq '#32770' -or ($ownerHandle -ne [IntPtr]::Zero -and -not [GmsPassiveWindows]::IsWindowEnabled($ownerHandle))
            $windowPid=[uint32]0
            [void][GmsPassiveWindows]::GetWindowThreadProcessId($handle,[ref]$windowPid)
            $windowContext=[GmsPassiveWindows+WindowContext]::new()
            $windowContext.VisibleText=$visibleText
            $windowContext.OwnedProcess=$pids.Contains($windowPid)
            $windowContext.Visible=[GmsPassiveWindows]::IsWindowVisible($handle)
            $windowContext.Enabled=[GmsPassiveWindows]::IsWindowEnabled($handle)
            $windowContext.IsDialog=$isDialog
            $entry.community_button_guard=[GmsPassiveWindows]::AssessCommunityButton($windowContext,$entry.control_snapshot)
            # These typed guard objects contain only fixed categories, counts and
            # booleans. Never serialize the raw window/control objects publicly.
            if ($receipt.community_button_guard_observations.Count -lt 8) {
                $receipt.community_button_guard_observations += @($entry.community_button_guard)
            }
            if (-not $isDialog -and $entry.title -match '(?i)\bGMS\b' -and $entry.menu.Items.Count -gt 0) {
                $receipt.main_window_enabled_observed=[GmsPassiveWindows]::IsWindowEnabled($handle)
            }
            $category = 'unknown'
            if ($isDialog) {
                if ($visibleText -match '(?i)evalua|trial.*(expired|licen[cs]e)') { $category = 'evaluation' }
                elseif ($visibleText -match '(?i)activation|registration|licen[cs]e code|unlicensed|\bno\s+licen[cs]e\s+found\b') { $category = 'licensing' }
                elseif ($visibleText -match '(?i)opengl|graphics.*(driver|error)|failed.*render|hardware.*accel') { $category = 'graphics' }
                elseif ($visibleText -match '(?i)error|exception|fatal|failed|cannot|missing.*dll') { $category = 'error' }
                $receipt.blocking_dialog_observed = $true
                $receipt.dialog_categories_observed = @($receipt.dialog_categories_observed + $category | Select-Object -Unique)
                $receipt.startup_classification = if ($category -eq 'unknown') { 'unclassified_dialog_observed' } else { 'blocking_' + $category + '_dialog_observed' }
                $stopObservation = $true
                if ($receipt.free_community_selection_attempted) {
                    $receipt.post_selection_dialog_observed=$true
                    if ($receipt.file_open_command_attempted) {
                        $receipt.post_file_open_dialog_observed=$true
                        $openObservation=[GmsPassiveWindows]::ObserveOpenDialog($windowContext,$entry.control_snapshot,$entry.class,$entry.title)
                        $receipt.post_file_open_dialog_observations += @($openObservation)
                        $entry.post_file_open_dialog_observation=$openObservation
                        if ($openObservation.Status -eq 'fixed_open_title_standard_dialog_observed_effect_unverified') { $receipt.fixed_open_dialog_context_observed=$true }
                    }
                } elseif ($SelectFreeCommunityEdition -and -not $selectionChecked) {
                    $selectionChecked=$true
                    $receipt.probe_phase='fresh_optional_free_community_choice_checks'
                    $selection=[GmsPassiveWindows]::SelectFreeCommunityOnce($pids,$exe,$ExpectedTargetSha256,$ExpectedTargetSize,$true,($receipt.launch_method -eq 'normal_process_start'),[int]$receipt.target_ui_actions)
                    $receipt.free_community_selection_observations += @($selection)
                    $entry.free_community_selection=$selection
                    if ($selection.Attempted) {
                        $receipt.free_community_selection_attempted=$true
                        $receipt.licence_ui_actions=1
                        $receipt.target_ui_actions=1
                        $receipt.startup_classification='free_community_choice_attempted_workspace_unverified'
                        $stopObservation=$false
                        $continueAfterSelection=$true
                    }
                    $receipt.probe_phase='passive_post_choice_observation'
                }
            } elseif ($receipt.startup_classification -eq 'unknown' -and $entry.title -match '(?i)\bGMS\b') {
                $receipt.startup_classification = 'application_window_observed_mode_unknown'
            }
            if ($receipt.free_community_selection_attempted -and -not $isDialog) {
                $receipt.post_selection_window_observed=$true
            }
            if ($ObserveFileOpenDialog -and -not $fileOpenChecked -and -not $isDialog -and
                $receipt.free_community_selection_attempted -and $receipt.main_window_enabled_observed -eq $true -and
                $entry.menu.Items.Count -gt 0 -and [GmsPassiveWindows]::IsWindowEnabled($handle)) {
                $fileOpenChecked=$true
                $ceCompleted=@($receipt.free_community_selection_observations | Where-Object { $_.Attempted -and $_.MessageCompleted }).Count -eq 1
                $receipt.probe_phase='fresh_optional_file_open_dialog_checks'
                $openDecision=[GmsPassiveWindows]::OpenFileDialogOnce($pids,$exe,$ExpectedTargetSha256,$ExpectedTargetSize,$true,($receipt.launch_method -eq 'normal_process_start'),[bool]$receipt.free_community_selection_attempted,$ceCompleted,[int]$receipt.file_open_ui_actions)
                $receipt.file_open_observations += @($openDecision)
                $entry.file_open_decision=$openDecision
                if ($openDecision.Attempted) {
                    $receipt.file_open_command_attempted=$true
                    $receipt.file_open_ui_actions=1
                    $receipt.target_ui_actions=[int]$receipt.target_ui_actions + 1
                    $deadline=[DateTime]::UtcNow.AddSeconds($receipt.file_open_observation_seconds)
                    $continueAfterSelection=$true
                } else { $stopObservation=$true }
                $receipt.probe_phase='passive_post_file_open_command_observation'
            }
            # Capture only this target window's visible rectangle. Any blank or
            # occluded frame remains evidence of that limitation, never a fake UI.
            $width = $rect.Right - $rect.Left; $height = $rect.Bottom - $rect.Top
            if (-not $continueAfterSelection -and $width -gt 0 -and $height -gt 0 -and $width -le 4096 -and $height -le 4096 -and $receipt.screenshot_count -lt 4) {
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
            if ($stopObservation -or $continueAfterSelection) { break }
        }
        $continueAfterSelection=$false
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
        # End only this bounded probe's process tree. No further UI interaction,
        # alternate keys, evaluation request or registration action is allowed.
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
