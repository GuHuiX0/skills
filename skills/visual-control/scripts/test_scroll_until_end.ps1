# Regression for scroll-until-end.
#
# Opens a ListBox holding 2000 messages, sitting at the bottom (the shape of a long
# chat), and asks the skill to scroll up until the content stops changing.  The
# harness records every TopIndex change, so we can assert that the view really
# moved, that it stopped because it reached the top rather than a notch budget, and
# that the reverse direction terminates at the bottom.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$vc = Join-Path $root 'visual-control\scripts\visual_control.py'
$harness = Join-Path $root 'visual-control\scripts\scroll_window.ps1'
$res = Join-Path $env:TEMP 'vc-scroll.jsonl'
$out = Join-Path $env:TEMP 'vc-scroll-shots'
New-Item -ItemType Directory -Force -Path $out | Out-Null
if (Test-Path $res) { Remove-Item $res -Force }

function Invoke-VC {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  $json = & python $vc @Args 2>&1 | Out-String
  try { return ($json | ConvertFrom-Json) } catch { return [pscustomobject]@{ ok = $false; raw = $json } }
}
function Read-Tops {
  return @(Get-Content $res -Encoding utf8 -ErrorAction SilentlyContinue |
    Where-Object { $_ -match '"kind":"topindex"' } |
    ForEach-Object { [int]($_ | ConvertFrom-Json).value })
}

$pwshExe = (Get-Process -Id $PID).Path
$proc = Start-Process -FilePath $pwshExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-File',$harness,'-Result',$res) -PassThru
Start-Sleep -Seconds 3

$handle = $null
for ($i = 0; $i -lt 20 -and -not $handle; $i++) {
  $line = @(Get-Content $res -Encoding utf8 -ErrorAction SilentlyContinue) | Where-Object { $_ -match '"kind":"shown"' } | Select-Object -Last 1
  if ($line) { $handle = ($line | ConvertFrom-Json).value } else { Start-Sleep -Milliseconds 250 }
}
if (-not $handle) { Write-Output 'FAILED: scroll window never appeared'; exit 1 }

# Wait for the list to settle at the bottom before measuring anything.
$startTop = 0
for ($i = 0; $i -lt 30; $i++) {
  $tops = Read-Tops
  if ($tops.Count -gt 0) { $startTop = $tops[-1] }
  if ($startTop -gt 1000) { break }
  Start-Sleep -Milliseconds 200
}
Write-Output "window HWND=$handle start TopIndex=$startTop"

# Sanity: one explicit wheel notch must move this control upwards.
$probe = Invoke-VC scroll --window $handle --direction up --amount 6
Start-Sleep -Milliseconds 500
$afterProbe = (Read-Tops)[-1]
Write-Output "single up-scroll: ok=$($probe.ok) TopIndex $startTop -> $afterProbe"

# Get back to the bottom, then run the action under test.
[void](Invoke-VC scroll --window $handle --direction down --amount 200)
Start-Sleep -Milliseconds 900
$bottomTop = (Read-Tops)[-1]
Write-Output "reset to bottom: TopIndex=$bottomTop"

$r = Invoke-VC scroll-until-end --window $handle --direction up --amount 3 --settle 0.25 --max-scrolls 400 --confirm 2 --out (Join-Path $out 'final.png')
Start-Sleep -Milliseconds 600
$tops = Read-Tops
$endTop = $tops[-1]
$distinct = ($tops | Sort-Object -Unique).Count
Write-Output "scroll-until-end(up): scrolls=$($r.scrolls) iterations=$($r.iterations) reached_end=$($r.reached_end) reason=$($r.reason)"
Write-Output "TopIndex: bottom=$bottomTop end=$endTop distinct=$distinct"

# Running it again from the top must terminate almost immediately.
$r2 = Invoke-VC scroll-until-end --window $handle --direction up --amount 3 --settle 0.25 --max-scrolls 400 --out (Join-Path $out 'final2.png')
Write-Output "second run(up from top): scrolls=$($r2.scrolls) reached_end=$($r2.reached_end) reason=$($r2.reason)"

# The other direction must terminate at the bottom the same way.
$r3 = Invoke-VC scroll-until-end --window $handle --direction down --amount 6 --settle 0.25 --max-scrolls 400 --out (Join-Path $out 'final3.png')
Start-Sleep -Milliseconds 500
$endTop3 = (Read-Tops)[-1]
Write-Output "scroll-until-end(down): scrolls=$($r3.scrolls) reached_end=$($r3.reached_end) reason=$($r3.reason) endTop=$endTop3"

$flags = [ordered]@{
  wheel_moves_the_control     = ($afterProbe -lt $startTop)
  first_run_reached_end       = ($r.reached_end -eq $true)
  stopped_by_no_change        = ($r.reason -eq 'no-change')
  walked_the_whole_history    = (($bottomTop - $endTop) -gt 1000)
  many_distinct_positions     = ($distinct -gt 20)
  stopped_at_the_first_item   = ($endTop -eq 0)
  final_frame_saved           = (Test-Path (Join-Path $out 'final.png'))
  second_run_terminates_fast  = (($r2.reached_end -eq $true) -and ($r2.scrolls -le 9))
  down_run_reached_bottom     = (($r3.reached_end -eq $true) -and ($r3.reason -eq 'no-change'))
}
Write-Output ''
Write-Output '=== results ==='
$flags.GetEnumerator() | ForEach-Object { Write-Output ("{0,-28} {1}" -f $_.Key, $(if ($_.Value) { 'PASS' } else { 'FAIL' })) }
$failed = @($flags.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
if ($failed.Count) { Write-Output ("FAILED: " + ($failed -join ', ')) }
$flags | ConvertTo-Json | Set-Content (Join-Path $env:TEMP 'vc-scroll-result.json') -Encoding utf8

Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
