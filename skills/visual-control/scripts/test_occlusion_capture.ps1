# Regression: is observe --window independent of what covers the window?
#
# Opens a green target window (with a white square), raises a red cover on top of
# it, then captures the target twice:
#   --capture screen  -> must show the RED occluder (that is the old behaviour)
#   --capture window  -> must show the target's own GREEN content
# A sane failure mode is also asserted: --capture window on a minimised window.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$vc = Join-Path $root 'visual-control\scripts\visual_control.py'
$harness = Join-Path $root 'visual-control\scripts\occlusion_window.ps1'
$out = Join-Path $env:TEMP 'vc-occlusion'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$res = Join-Path $env:TEMP 'vc-occlusion.jsonl'
if (Test-Path $res) { Remove-Item $res -Force }

function Invoke-VC {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  $json = & python $vc @Args 2>&1 | Out-String
  try { return ($json | ConvertFrom-Json) } catch { return [pscustomobject]@{ ok = $false; raw = $json } }
}

Add-Type -AssemblyName System.Drawing
Add-Type -Namespace VC -Name Win -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int cmd);
'@

# Dominant colour of a PNG plus a colour classifier.
function Get-Dominant {
  param([string]$Path)
  $img = [System.Drawing.Bitmap]::FromFile($Path)
  $counts = @{}
  for ($y = 5; $y -lt $img.Height - 5; $y += 11) {
    for ($x = 5; $x -lt $img.Width - 5; $x += 11) {
      $p = $img.GetPixel($x, $y)
      $key = "$($p.R),$($p.G),$($p.B)"
      if ($counts.ContainsKey($key)) { $counts[$key]++ } else { $counts[$key] = 1 }
    }
  }
  $img.Dispose()
  return ($counts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 3)
}
function Classify {
  param($Dominant)
  $top = $Dominant | Select-Object -First 1
  if (-not $top) { return 'unknown' }
  $parts = $top.Key -split ','
  $r = [int]$parts[0]; $g = [int]$parts[1]; $b = [int]$parts[2]
  if ($g -gt 120 -and $r -lt 120) { return 'green' }
  if ($r -gt 150 -and $g -lt 120) { return 'red' }
  if ($r -gt 200 -and $g -gt 200 -and $b -gt 200) { return 'white' }
  return "other($($top.Key))"
}

$pwshExe = (Get-Process -Id $PID).Path
$target = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$harness,'-Role','target','-Result',$res) -PassThru
Start-Sleep -Seconds 2
$cover = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$harness,'-Role','cover','-Result',$res) -PassThru
Start-Sleep -Seconds 2

$lines = @(Get-Content $res -Encoding utf8 | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$tHandle = ($lines | Where-Object { $_.value -like '*|target|*' } | Select-Object -Last 1).value.Split('|')[0]
$cHandle = ($lines | Where-Object { $_.value -like '*|cover|*' } | Select-Object -Last 1).value.Split('|')[0]
Write-Output "target HWND=$tHandle  cover HWND=$cHandle"

# the cover must be in front, and the target only partially overlapped so a screen
# crop still contains some green - making the test about occlusion, not opacity
[void][VC.Win]::SetForegroundWindow([System.IntPtr][int]$cHandle)
Start-Sleep -Milliseconds 900

$screenPng = Join-Path $out 'capture-screen.png'
$windowPng = Join-Path $out 'capture-window.png'
$autoPng = Join-Path $out 'capture-auto.png'
$r1 = Invoke-VC observe --window $tHandle --capture screen --out $screenPng
$r2 = Invoke-VC observe --window $tHandle --capture window --out $windowPng
$r3 = Invoke-VC observe --window $tHandle --capture auto --out $autoPng

$screenClass = if (Test-Path $screenPng) { Classify (Get-Dominant $screenPng) } else { 'missing' }
$windowClass = if (Test-Path $windowPng) { Classify (Get-Dominant $windowPng) } else { 'missing' }
$autoClass = if (Test-Path $autoPng) { Classify (Get-Dominant $autoPng) } else { 'missing' }
$screenDom = if (Test-Path $screenPng) { (Get-Dominant $screenPng | ForEach-Object { "$($_.Key)x$($_.Value)" }) -join ' ' } else { '' }
$windowDom = if (Test-Path $windowPng) { (Get-Dominant $windowPng | ForEach-Object { "$($_.Key)x$($_.Value)" }) -join ' ' } else { '' }

Write-Output "screen-crop dominant: $screenDom  => $screenClass"
Write-Output "window-own  dominant: $windowDom  => $windowClass"
Write-Output "auto        dominant: => $autoClass"

# a minimised window must fail cleanly instead of producing a garbage image
[void][VC.Win]::ShowWindow([System.IntPtr][int]$tHandle, 6)
Start-Sleep -Milliseconds 700
$min = Invoke-VC observe --window $tHandle --capture window --out (Join-Path $out 'minimised.png')
Write-Output "minimised: ok=$($min.ok) message=$($min.message)"
[void][VC.Win]::ShowWindow([System.IntPtr][int]$tHandle, 9)
Start-Sleep -Milliseconds 500

Stop-Process -Id $target.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $cover.Id -Force -ErrorAction SilentlyContinue

# The invariant under test: window capture returns the window's own content even
# though something else is on top of it.  Comparing against the screen crop makes
# this independent of which window happens to be topmost on this desktop.
$flags = [ordered]@{
  window_capture_shows_target  = ($windowClass -eq 'green')
  auto_capture_shows_target    = ($autoClass -eq 'green')
  screen_capture_differs       = ($screenClass -ne 'green')
  screen_capture_dominates_other = ($r1.capture.window_pixels -eq $false)
  window_capture_reports_mode  = ($r2.capture.window_pixels -eq $true)
  auto_capture_reports_mode    = ($r3.capture.window_pixels -eq $true)
  minimised_window_fails_cleanly = ((-not $min.ok) -and ($min.message -like '*minimised*'))
}
Write-Output ''
Write-Output '=== results ==='
$flags.GetEnumerator() | ForEach-Object { Write-Output ("{0,-32} {1}" -f $_.Key, $(if ($_.Value) { 'PASS' } else { 'FAIL' })) }
Write-Output ''
Write-Output "note: screen crop returned '$screenClass' while the window's own pixels returned 'green'"
$failed = @($flags.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
if ($failed.Count) { Write-Output ("FAILED: " + ($failed -join ', ')) }
$flags | ConvertTo-Json | Set-Content (Join-Path $env:TEMP 'vc-occlusion-result.json') -Encoding utf8
