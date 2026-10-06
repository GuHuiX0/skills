# Deterministic end-to-end test of the visual-control skill against a real
# DPI-aware WinForms window.
#
# Why DPI aware: this host runs at 200% scaling.  A DPI-unaware window has its
# coordinates virtualised by Windows, so GetWindowRect returns logical pixels and
# a screenshot of that window would not line up with those coordinates.  Modern
# applications are per-monitor DPI aware, which is the case this test mirrors.
#
# Everything runs in one invocation because the sandbox reaps detached children
# when the shell exits.  Pure ASCII: Windows PowerShell parses .ps1 using the
# ANSI code page, so CJK sample text is built from code points.
#
# It drives a throwaway window with REAL synthetic input, so the pointer moves and
# keystrokes land in that window.  Run it on an idle desktop, with unsaved work
# closed.  It does not modify any system state.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$vc = Join-Path $root 'visual-control\scripts\visual_control.py'
$res = Join-Path $env:TEMP 'vc-e2e-events.jsonl'
$img = Join-Path $env:TEMP 'vc-e2e-window.png'

function Invoke-VC {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  $json = & python $vc @Args 2>&1 | Out-String
  try { return ($json | ConvertFrom-Json) } catch { return [pscustomobject]@{ ok = $false; raw = $json } }
}

$code = @'
param([string]$Result, [string]$Title = 'VisualControlInputTest')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace VC -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
Add-Type -Namespace VC -Name Dpi2 -MemberDefinition '[DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r); [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }'
[void][VC.Dpi]::SetProcessDPIAware()
function Ev([string]$k,[string]$v){ ([ordered]@{kind=$k;value=$v}) | ConvertTo-Json -Compress | Add-Content $Result -Encoding utf8 }
$f = New-Object System.Windows.Forms.Form
$f.Text=$Title; $f.Size=New-Object System.Drawing.Size(560,470)
$f.StartPosition='Manual'; $f.Location=New-Object System.Drawing.Point(160,160); $f.KeyPreview=$true
$t = New-Object System.Windows.Forms.TextBox
$t.Multiline=$true; $t.Location=New-Object System.Drawing.Point(12,12); $t.Size=New-Object System.Drawing.Size(520,150)
$t.Add_TextChanged({ Ev 'text' $t.Text })
$f.Controls.Add($t)
$c = New-Object System.Windows.Forms.CheckBox
$c.Text='ToggleMe'; $c.Location=New-Object System.Drawing.Point(12,175); $c.Size=New-Object System.Drawing.Size(220,24)
$c.Add_CheckedChanged({ Ev 'checkbox' $c.Checked.ToString() }); $f.Controls.Add($c)
$b = New-Object System.Windows.Forms.Button
$b.Text='PressMe'; $b.Location=New-Object System.Drawing.Point(12,205); $b.Size=New-Object System.Drawing.Size(130,32)
$b.Add_Click({ Ev 'button' 'clicked' }); $f.Controls.Add($b)
$l = New-Object System.Windows.Forms.ListBox
$l.Location=New-Object System.Drawing.Point(160,205); $l.Size=New-Object System.Drawing.Size(370,180)
for ($i=1; $i -le 60; $i++) { [void]$l.Items.Add("row $i") }
$l.Add_SelectedIndexChanged({ Ev 'listbox' $l.SelectedIndex.ToString() })
$l.Add_MouseWheel({ Ev 'mousewheel' $_.Delta.ToString() })
$f.Controls.Add($l)
$m = New-Object System.Windows.Forms.MenuStrip
$fm = New-Object System.Windows.Forms.ToolStripMenuItem('File')
$sv = New-Object System.Windows.Forms.ToolStripMenuItem('Save')
$sv.ShortcutKeys = [System.Windows.Forms.Keys]::Control -bor [System.Windows.Forms.Keys]::S
$sv.Add_Click({ Ev 'hotkey' 'ctrl+s' })
$fm.DropDownItems.Add($sv) | Out-Null
$m.Items.Add($fm) | Out-Null
$f.MainMenuStrip = $m; $f.Controls.Add($m)
$f.Add_KeyDown({ Ev 'keydown' $_.KeyCode.ToString() })
foreach ($pair in @(@('form',$f),@('textbox',$t),@('checkbox',$c),@('button',$b),@('listbox',$l))) {
  $nm = $pair[0]; $pair[1].Add_MouseDown({ Ev 'mousedown' $nm }.GetNewClosure())
}
$f.Add_Shown({
  $t.Focus()
  $info = [ordered]@{}
  foreach ($pair in @(@('form',$f),@('textbox',$t),@('checkbox',$c),@('button',$b),@('listbox',$l))) {
    $nm = $pair[0]; $ctrl = $pair[1]
    $o = $ctrl.PointToScreen([System.Drawing.Point]::new(0,0))
    $info[$nm] = @{
      x = $o.X; y = $o.Y; w = $ctrl.ClientSize.Width; h = $ctrl.ClientSize.Height
      clickX = $o.X + [int]($ctrl.ClientSize.Width/2); clickY = $o.Y + [int]($ctrl.ClientSize.Height/2)
    }
  }
  Ev 'geometry' ($info | ConvertTo-Json -Compress -Depth 4)
  $r = $f.RectangleToScreen($f.ClientRectangle)
  Ev 'frame' ($r.X.ToString() + ',' + $r.Y.ToString() + ',' + $r.Width.ToString() + ',' + $r.Height.ToString())
  $native = New-Object VC.Dpi2+RECT
  [void][VC.Dpi2]::GetWindowRect($f.Handle, [ref]$native)
  Ev 'native' ("$($native.L),$($native.T),$($native.R-$native.L),$($native.B-$native.T)")
  Ev 'shown' $f.Handle.ToString()
})
[System.Windows.Forms.Application]::Run($f)
'@
$harness = Join-Path $env:TEMP 'vc-e2e-harness.ps1'
Set-Content -Path $harness -Value $code -Encoding ASCII
if (Test-Path $res) { Remove-Item $res -Force }

$sample = 'Hello ' + [char]0x89C6 + [char]0x89C9 + [char]0x64CD + [char]0x4F5C + ' ' + [char]0x2713
$pwshExe = (Get-Process -Id $PID).Path
$proc = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$harness,'-Result',$res) -PassThru
Start-Sleep -Seconds 3

$geom = $null
for ($i=0; $i -lt 25 -and -not $geom; $i++) {
  $line = @(Get-Content $res -Encoding utf8 -ErrorAction SilentlyContinue) | Where-Object { $_ -match '"kind":"geometry"' } | Select-Object -Last 1
  if ($line) { $geom = ($line | ConvertFrom-Json).value | ConvertFrom-Json } else { Start-Sleep -Milliseconds 300 }
}
if (-not $geom) { Write-Output 'FAILED: harness never reported geometry'; Stop-Process -Id $proc.Id -Force; exit 1 }

$steps = [ordered]@{}
$wins = Invoke-VC windows --limit 40
$win = $wins.windows | Where-Object { $_.title -eq 'VisualControlInputTest' } | Select-Object -First 1
$steps['windows'] = $wins
$handle = $win.handle

# The skill must report the same window frame as a native GetWindowRect call in
# the target application's own process.  (WinForms PointToScreen/RectangleToScreen
# are not a valid reference here: they are reported in the window's own DPI
# context, which differs from physical pixels when a window is DPI virtualised.)
$nativeLine = @(Get-Content $res -Encoding utf8) | Where-Object { $_ -match '"kind":"native"' } | Select-Object -Last 1
$nativeVal = ($nativeLine | ConvertFrom-Json).value -split ','
$rectMatch = ($win.x -eq [int]$nativeVal[0]) -and ($win.y -eq [int]$nativeVal[1]) -and
             ($win.width -eq [int]$nativeVal[2]) -and ($win.height -eq [int]$nativeVal[3])
Write-Output ("window rect: skill=({0},{1},{2},{3}) native-GetWindowRect=({4}) match={5}" -f $win.x,$win.y,$win.width,$win.height,($nativeVal -join ','),$rectMatch)

# 1) observe the window, with ruler, downscaled
$obs = Invoke-VC observe --window $handle --out $img --grid 100 --scale 0.5 --with-cursor --with-windows
$steps['observe'] = $obs
Write-Output ("observe: ok={0} image={1}x{2} scale={3}" -f $obs.ok, $obs.image.width, $obs.image.height, $obs.image.scale)

# 1b) app/window selection: a second window, addressed by title / HWND / 'last'
$helper = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$harness,'-Result',(Join-Path $env:TEMP 'vc-e2e-helper.jsonl'),'-Title','VisualControlHelper') -PassThru
Start-Sleep -Seconds 2
$helperWin = $null
for ($i=0; $i -lt 20 -and -not $helperWin; $i++) {
  $helperWin = (Invoke-VC windows --match VisualControlHelper --limit 5).windows | Select-Object -First 1
  if (-not $helperWin) { Start-Sleep -Milliseconds 250 }
}
$steps['find_helper_by_title'] = [pscustomobject]@{ ok = [bool]$helperWin; handle = $(if ($helperWin) { $helperWin.handle } else { 0 }) }
if ($helperWin) {
  $byHwnd = Invoke-VC windows --match $helperWin.handle --limit 5
  $steps['find_helper_by_hwnd'] = $byHwnd
  $atHelper = Invoke-VC observe --window VisualControlHelper --out (Join-Path $env:TEMP 'vc-e2e-helper.png')
  $steps['observe_helper_window'] = $atHelper
  # targeting by title must resolve to the helper, not to the main window
  $clickHelper = Invoke-VC --dry-run click --window VisualControlHelper --at "50%,50%"
  $steps['target_by_title'] = $clickHelper
  $steps['title_resolution_ok'] = [pscustomobject]@{
    ok = ($clickHelper.ok -and ($clickHelper.window.handle -eq $helperWin.handle))
    resolved = $(if ($clickHelper.window) { $clickHelper.window.handle } else { 0 })
    expected = $helperWin.handle
  }
  # 'last' must reuse whatever the previous command resolved
  $viaLast = Invoke-VC --dry-run click --window last --at 10,10
  $steps['target_by_last'] = $viaLast
  $steps['last_resolution_ok'] = [pscustomobject]@{
    ok = ($viaLast.ok -and ($viaLast.window.handle -eq $helperWin.handle))
    resolved = $(if ($viaLast.window) { $viaLast.window.handle } else { 0 })
    expected = $helperWin.handle
  }
  # an unresolvable title must fail with guidance, not silently pick something
  $bogus = Invoke-VC click --window NoSuchWindowXyz --at 10,10
  $steps['unknown_window_rejected'] = [pscustomobject]@{ ok = (-not $bogus.ok); message = $bogus.message }
}

# 2) focus + click the text box
$steps['focus'] = Invoke-VC focus --window $handle
Start-Sleep -Milliseconds 300
$steps['click_textbox'] = Invoke-VC click --at ("{0},{1}" -f $geom.textbox.clickX, $geom.textbox.clickY) --duration 0.15
Start-Sleep -Milliseconds 250

# 3) typing (unicode + CJK + symbol)
$steps['type'] = Invoke-VC type --text $sample
Start-Sleep -Milliseconds 400

# 4) click the checkbox then the button
$steps['click_checkbox'] = Invoke-VC click --at ("{0},{1}" -f $geom.checkbox.clickX, $geom.checkbox.clickY)
Start-Sleep -Milliseconds 300
$steps['click_button'] = Invoke-VC click --at ("{0},{1}" -f $geom.button.clickX, $geom.button.clickY)
Start-Sleep -Milliseconds 300

# 5) scroll inside the list box
$steps['scroll'] = Invoke-VC scroll --direction down --amount 4 --at ("{0},{1}" -f $geom.listbox.clickX, $geom.listbox.clickY)
Start-Sleep -Milliseconds 400

# 6) drag-select rows 1..4 inside the list box
$steps['drag'] = Invoke-VC drag --start ("{0},{1}" -f $geom.listbox.x, ($geom.listbox.y + 8)) --to ("{0},{1}" -f ($geom.listbox.x + 60), ($geom.listbox.y + 50)) --duration 0.4
Start-Sleep -Milliseconds 400

# 7) hotkey
$steps['hotkey'] = Invoke-VC hotkey --keys ctrl+s
Start-Sleep -Milliseconds 400

# 8) dry run must never touch the pointer
$before = (Invoke-VC observe --region 0,0,4,4 --out (Join-Path $env:TEMP 'vc-cursor.png') --with-cursor).cursor
$steps['dry_run'] = Invoke-VC --dry-run click --at 5,5 --count 2
Start-Sleep -Milliseconds 200
$after = (Invoke-VC observe --region 0,0,4,4 --out (Join-Path $env:TEMP 'vc-cursor2.png') --with-cursor).cursor
$pointerUntouched = ($before.x -eq $after.x) -and ($before.y -eq $after.y)

Start-Sleep -Milliseconds 400
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
if ($helper) { Stop-Process -Id $helper.Id -Force -ErrorAction SilentlyContinue }
$events = @(Get-Content $res -Encoding utf8 | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$ev = { param($kind) @($events | Where-Object { $_.kind -eq $kind }) }
$last = { param($kind) ($events | Where-Object { $_.kind -eq $kind } | Select-Object -Last 1).value }
$listIndex = & $last 'listbox'

$okFlags = [ordered]@{
  window_rect_matches  = [bool]$rectMatch
  observe_ok           = [bool]$obs.ok
  find_window_by_title = [bool]$steps['find_helper_by_title'].ok
  target_by_title      = [bool]$steps['title_resolution_ok'].ok
  target_by_last       = [bool]$steps['last_resolution_ok'].ok
  unknown_window_fails = [bool]$steps['unknown_window_rejected'].ok
  click_textbox        = [bool]@($events | Where-Object { $_.kind -eq 'mousedown' -and $_.value -eq 'textbox' }).Count
  type_roundtrip       = ((& $last 'text') -eq $sample)
  checkbox_toggled     = ((& $last 'checkbox') -eq 'True')
  button_clicked       = (@($events | Where-Object { $_.kind -eq 'button' }).Count -ge 1)
  scroll_delivered     = (@($events | Where-Object { $_.kind -eq 'mousewheel' }).Count -ge 1)
  drag_selected_row    = [bool]$listIndex
  hotkey_fired         = (@($events | Where-Object { $_.kind -eq 'hotkey' }).Count -ge 1)
  dryrun_pointer_still = [bool]$pointerUntouched
  all_cli_steps_ok     = (@($steps.GetEnumerator() | Where-Object { $_.Value.ok -ne $true }).Count -eq 0)
}
Write-Output ''
Write-Output '=== results ==='
$okFlags.GetEnumerator() | ForEach-Object { Write-Output ("{0,-22} {1}" -f $_.Key, $(if ($_.Value) { 'PASS' } else { 'FAIL' })) }
Write-Output ''
Write-Output ("event kinds: " + (($events | Group-Object kind | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ', '))
Write-Output ("typed text : " + (& $last 'text'))
Write-Output ("listbox idx: " + $listIndex)
Write-Output ("window match: by-title={0} by-last={1}" -f $steps['title_resolution_ok'].ok, $steps['last_resolution_ok'].ok)
$failed = @($okFlags.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
if ($failed.Count -gt 0) { Write-Output ("FAILED: " + ($failed -join ', ')) }
$okFlags | ConvertTo-Json | Set-Content (Join-Path $env:TEMP 'vc-e2e-result.json') -Encoding utf8
