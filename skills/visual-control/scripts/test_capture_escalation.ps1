# Regression for the capture escalation ladder.
#
# PrintWindow(PW_RENDERFULLCONTENT) reads the DWM surface on this Windows build and
# normally succeeds even for occluded windows (see probe_capture_divergence.ps1),
# so a real blank surface cannot be produced on demand from a test app.  The
# trigger is therefore forced with --assume-blank, which marks every window
# capture as "empty" and drives the ladder deterministically:
#
#   --capture window -> keeps the own-pixel result and says it looks blank
#   --capture auto   -> raises the window, BitBlts it, restores focus afterwards
#   --capture focus  -> same ladder as auto (the explicit request)
#   --capture screen -> plain crop, never raises anything
#   --keep-focus     -> leaves the captured window in front instead of restoring
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$vc = Join-Path $root 'visual-control\scripts\visual_control.py'
$stubborn = Join-Path $root 'visual-control\scripts\stubborn_window.ps1'
$coverHarness = Join-Path $root 'visual-control\scripts\occlusion_window.ps1'
$out = Join-Path $env:TEMP 'vc-escalation'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$res = Join-Path $env:TEMP 'vc-escalation.jsonl'
if (Test-Path $res) { Remove-Item $res -Force }

function Invoke-VC {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  $json = & python $vc @Args 2>&1 | Out-String
  try { return ($json | ConvertFrom-Json) } catch { return [pscustomobject]@{ ok = $false; raw = $json } }
}

Add-Type -AssemblyName System.Drawing
Add-Type -Namespace VC -Name Win -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
'@

# A real WinForms window stands in for "the window the user was working in".  A
# console window is not reliably re-focusable, which would test the wrong thing.
function New-AnchorWindow {
  $code = @'
param([string]$Title)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$f = New-Object System.Windows.Forms.Form
$f.Text = $Title
$f.Size = New-Object System.Drawing.Size(560, 420)
$f.StartPosition = 'Manual'
$f.Location = New-Object System.Drawing.Point(320, 320)
$f.BackColor = [System.Drawing.Color]::FromArgb(238, 238, 238)
[System.Windows.Forms.Application]::Run($f)
'@
  $path = Join-Path $env:TEMP 'vc-anchor.ps1'
  Set-Content -Path $path -Value $code -Encoding UTF8
  $exe = (Get-Process -Id $PID).Path
  return Start-Process -FilePath $exe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$path,'-Title','VCAnchor') -PassThru
}

function Set-Anchored {
  param([int]$AnchorHandle)
  [void][VC.Win]::SetForegroundWindow([System.IntPtr]$AnchorHandle)
  Start-Sleep -Milliseconds 400
  return [int][VC.Win]::GetForegroundWindow()
}

# The stubborn window paints a blue header over a white body, so a correct capture
# contains both colours while a blank one is white-only.
function Classify-Png {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return 'missing' }
  $img = [System.Drawing.Bitmap]::FromFile($Path)
  $blue = 0; $white = 0; $other = 0; $total = 0
  for ($y = 5; $y -lt $img.Height - 5; $y += 9) {
    for ($x = 5; $x -lt $img.Width - 5; $x += 9) {
      $p = $img.GetPixel($x, $y); $total++
      if ($p.B -gt 150 -and $p.R -lt 120) { $blue++ }
      elseif ($p.R -gt 225 -and $p.G -gt 225 -and $p.B -gt 225) { $white++ }
      else { $other++ }
    }
  }
  $img.Dispose()
  if ($total -eq 0) { return 'empty' }
  $bp = [int](100 * $blue / $total); $wp = [int](100 * $white / $total); $op = [int](100 * $other / $total)
  if ($bp -gt 10 -and $wp -gt 20) { return "content(blue=$bp%,white=$wp%)" }
  return "blank(blue=$bp%,white=$wp%,other=$op%)"
}

$pwshExe = (Get-Process -Id $PID).Path
$stub = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$stubborn,'-Result',$res,'-Mode','content') -PassThru
Start-Sleep -Seconds 3
$anchorProc = New-AnchorWindow
Start-Sleep -Seconds 3

$handle = $null
for ($i = 0; $i -lt 20 -and -not $handle; $i++) {
  $line = @(Get-Content $res -Encoding utf8 -ErrorAction SilentlyContinue) | Where-Object { $_ -match 'shown' } | Select-Object -Last 1
  if ($line) { $handle = ($line | ConvertFrom-Json).value } else { Start-Sleep -Milliseconds 250 }
}
if (-not $handle) { Write-Output 'FAILED: stubborn window never appeared'; exit 1 }

# Resolve the anchor window through the skill itself (its own HWND source).
$anchorWin = $null
for ($i = 0; $i -lt 20 -and -not $anchorWin; $i++) {
  $anchorWin = (Invoke-VC windows --match VCAnchor --limit 5).windows | Select-Object -First 1
  if (-not $anchorWin) { Start-Sleep -Milliseconds 250 }
}
if (-not $anchorWin) { Write-Output 'FAILED: anchor window never appeared'; exit 1 }
$anchor = [int]$anchorWin.handle
Write-Output "stubborn HWND=$handle anchor HWND=$anchor"

# The anchor is in front and covers the stubborn window (the anchor sits on top of
# it), which is the whole point: the user is working elsewhere.
$fgBefore = Set-Anchored -AnchorHandle $anchor
Write-Output "foreground before: $fgBefore (stubborn=$handle anchor=$anchor)"

# With the default threshold the own-pixel capture is trusted and nothing moves.
$normalPng = Join-Path $out 'normal.png'
$rNormal = Invoke-VC observe --window $handle --capture auto --out $normalPng
$fgAfterNormal = [int][VC.Win]::GetForegroundWindow()

# Forced blank detection: the ladder must escalate.
$rWin = Invoke-VC observe --window $handle --capture window --assume-blank --out (Join-Path $out 'window.png')
$fgAfterWin = [int][VC.Win]::GetForegroundWindow()

Set-Anchored -AnchorHandle $anchor | Out-Null
$rAuto = Invoke-VC observe --window $handle --capture auto --assume-blank --out (Join-Path $out 'auto.png')
$fgAfterAuto = [int][VC.Win]::GetForegroundWindow()

Set-Anchored -AnchorHandle $anchor | Out-Null
$rFocus = Invoke-VC observe --window $handle --capture focus --assume-blank --out (Join-Path $out 'focus.png')
$fgAfterFocus = [int][VC.Win]::GetForegroundWindow()

Set-Anchored -AnchorHandle $anchor | Out-Null
$fgBeforeScreen = [int][VC.Win]::GetForegroundWindow()
$rScreen = Invoke-VC observe --window $handle --capture screen --assume-blank --out (Join-Path $out 'screen.png')
$fgAfterScreen = [int][VC.Win]::GetForegroundWindow()

Set-Anchored -AnchorHandle $anchor | Out-Null
$rKeep = Invoke-VC observe --window $handle --capture focus --assume-blank --keep-focus --out (Join-Path $out 'keep.png')
$fgAfterKeep = [int][VC.Win]::GetForegroundWindow()

$classNormal = Classify-Png $normalPng
$classWin = Classify-Png (Join-Path $out 'window.png')
$classAuto = Classify-Png (Join-Path $out 'auto.png')
$classFocus = Classify-Png (Join-Path $out 'focus.png')
$classScreen = Classify-Png (Join-Path $out 'screen.png')
$classKeep = Classify-Png (Join-Path $out 'keep.png')

$autoNotes = ($rAuto.capture.notes -join ' ')
$focusNotes = ($rFocus.capture.notes -join ' ')
Write-Output "normal (default threshold): $classNormal notes=$($rNormal.capture.notes -join ' | ')"
Write-Output "window (forced blank)     : $classWin  window_pixels=$($rWin.capture.window_pixels)"
Write-Output "auto   (forced blank)     : $classAuto  notes=$autoNotes"
Write-Output "focus  (forced blank)     : $classFocus  notes=$focusNotes"
Write-Output "screen (forced blank)     : $classScreen"
Write-Output "keep-focus                : $classKeep fg=$fgAfterKeep target=$handle"
Write-Output "foreground trace: normal=$fgAfterNormal win=$fgAfterWin auto=$fgAfterAuto focus=$fgAfterFocus screen=$fgAfterScreen"

$flags = [ordered]@{
  default_threshold_uses_own_pixels = (($classNormal -like 'content*') -and ($rNormal.capture.window_pixels -eq $true) -and (-not $rNormal.capture.focus_fallback))
  default_threshold_leaves_focus    = ($fgAfterNormal -eq $anchor)
  forced_blank_keeps_own_pixels     = (($classWin -like 'content*') -and ($rWin.capture.window_pixels -eq $true))
  forced_blank_warns                = (($rWin.capture.notes -join ' ') -like '*almost uniformly*')
  auto_escalates                    = ($autoNotes -like '*foreground fallback*')
  auto_fallback_has_content         = ($classAuto -like 'content*')
  auto_fallback_not_window_pixels   = ($rAuto.capture.window_pixels -eq $false)
  auto_reports_focus_state          = ($rAuto.capture.focus_fallback.raised -eq $true)
  auto_restores_focus               = ($fgAfterAuto -eq $anchor)
  focus_mode_escalates              = ($focusNotes -like '*foreground fallback*')
  focus_mode_restores               = ($fgAfterFocus -eq $anchor)
  screen_mode_never_raises          = (($fgAfterScreen -eq $anchor) -and (($rScreen.capture.notes -join ' ') -notlike '*foreground fallback*'))
  keep_focus_leaves_target          = ($fgAfterKeep -eq [int]$handle)
  keep_focus_has_content            = ($classKeep -like 'content*')
}
Write-Output ''
Write-Output '=== results ==='
$flags.GetEnumerator() | ForEach-Object { Write-Output ("{0,-34} {1}" -f $_.Key, $(if ($_.Value) { 'PASS' } else { 'FAIL' })) }
$failed = @($flags.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
if ($failed.Count) { Write-Output ("FAILED: " + ($failed -join ', ')) }
$flags | ConvertTo-Json | Set-Content (Join-Path $env:TEMP 'vc-escalation-result.json') -Encoding utf8

Stop-Process -Id $stub.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $anchorProc.Id -Force -ErrorAction SilentlyContinue
